"""Le surveillant de la machine, l'agent launchd, la voie hôte."""
import asyncio
import json
import plistlib
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cime import cli
from cime.fondation.registre import ouvrir
from cime.lanceur import launchd, serveur, surveillant
from cime.lanceur.surveillant import Surveillant, battement_frais


def projet(tmp_path, nom="alpha"):
    racine = tmp_path / nom
    ouvrir(racine).close()                      # .orga/etat/registre.sqlite
    return racine


def battre(racine, il_y_a_s=0):
    instant = datetime.now(timezone.utc) - timedelta(seconds=il_y_a_s)
    conn = ouvrir(racine)
    conn.execute("INSERT OR REPLACE INTO facteur (id, battement, version) VALUES (1, ?, '3')",
                 (instant.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",))
    conn.commit()
    conn.close()


def connus(dossier, *projets):
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "projets.json").write_text(json.dumps(
        [{"chemin": str(p), "nom": p.name} for p in projets]))


class Monde:
    """Surveillant dont tout ce qui touche la machine est simulé."""

    def __init__(self, tmp_path, *projets, actifs=True, repart_apres=None, vivants=()):
        self.dossier = tmp_path / ".cime"
        connus(self.dossier, *projets)
        self.lances, self.notifs, self.pauses = [], [], []
        self.actifs, self.repart_apres, self.t = actifs, repart_apres, 0.0
        self.vivants = set(vivants)                  # projets dont le verrou de facteur.pid est tenu
        self.s = Surveillant(
            self.dossier, notifier=lambda titre, texte: self.notifs.append((titre, texte)),
            demarrer=self.demarrer, agents_actifs=lambda p: self.actifs, dormir=self.pauses.append,
            horloge=lambda: self.t, vivant=lambda p: p in self.vivants)

    def demarrer(self, chemin):
        self.lances.append(chemin)
        if self.repart_apres is not None and len(self.lances) >= self.repart_apres:
            battre(chemin)                       # le facteur est reparti : il bat
        return True


def test_battement_frais_ou_perime(tmp_path):
    p = projet(tmp_path)
    assert battement_frais(p) is False               # jamais battu
    battre(p, 5)
    assert battement_frais(p) is True
    battre(p, 45)
    assert battement_frais(p) is False
    assert battement_frais(tmp_path / "absent") is False


def test_relance_le_facteur_d_un_projet_actif_au_battement_perime(tmp_path):
    p = projet(tmp_path)
    battre(p, 120)
    m = Monde(tmp_path, p, repart_apres=1)
    assert m.s.passe() == [str(p)]
    assert m.lances == [p] and m.pauses == [surveillant.ESPACE] and m.notifs == []
    assert "facteur reparti" in (m.dossier / "surveillant.log").read_text()


def test_un_facteur_tue_repart_a_la_passe_suivante_sans_attendre_le_battement(tmp_path):
    p = projet(tmp_path)
    battre(p, 3)                                     # battement encore frais : il vient d'être tué
    m = Monde(tmp_path, p, repart_apres=1)           # verrou libre : personne ne le tient
    assert m.s.passe() == [str(p)]
    assert m.lances == [p] and m.notifs == []


def test_verrou_tenu_rien_n_est_fait_meme_battement_perime(tmp_path):
    p = projet(tmp_path)
    battre(p, 120)                                   # bloqué mais vivant : une autre panne
    m = Monde(tmp_path, p, vivants=(p,))
    assert m.s.passe() == [] and m.lances == [] and m.notifs == []


def test_la_passe_du_surveillant_est_toutes_les_cinq_secondes():
    assert surveillant.PAS == 5.0


def test_trois_essais_espaces_de_dix_secondes_puis_une_notification(tmp_path):
    p = projet(tmp_path, "beta")
    battre(p, 120)
    m = Monde(tmp_path, p)                           # il ne repart jamais
    assert m.s.passe() == []
    assert len(m.lances) == 3 and m.pauses == [10.0, 10.0, 10.0]
    assert len(m.notifs) == 1 and m.notifs[0][0] == "beta" and "3 essais" in m.notifs[0][1]
    assert "ne repart pas après 3 essais" in (m.dossier / "surveillant.log").read_text()


def test_apres_l_abandon_on_attend_et_on_ne_renotifie_pas(tmp_path):
    p = projet(tmp_path)
    battre(p, 120)
    m = Monde(tmp_path, p)
    m.s.passe()
    m.t = 100.0
    m.s.passe()                                      # trop tôt : rien
    assert len(m.lances) == 3
    m.t = surveillant.REPRISE_APRES_ABANDON + 1
    m.s.passe()                                      # on réessaie…
    assert len(m.lances) == 6 and len(m.notifs) == 1  # …sans renotifier
    battre(p)                                        # il repart enfin : il tient le verrou et bat
    m.vivants.add(p)
    m.s.passe()
    assert str(p) not in m.s.abandons                # oublié : une panne future renotifiera


def test_rien_a_faire_sans_agent_actif_ou_avec_un_facteur_vivant(tmp_path):
    p, q = projet(tmp_path, "p"), projet(tmp_path, "q")
    battre(p, 120)
    battre(q, 3)
    m = Monde(tmp_path, p, q, actifs=False, vivants=(q,))
    assert m.s.passe() == [] and m.lances == []
    m.actifs = True
    m.s.passe()                                      # p relancé (jamais reparti), q vivant : intact
    assert all(l == p for l in m.lances)


def test_un_projet_inconnu_ou_sans_registre_est_ignore(tmp_path):
    m = Monde(tmp_path, tmp_path / "fantome")
    assert m.s.passe() == [] and m.lances == []
    (m.dossier / "projets.json").write_text("= pas du json")
    assert m.s.passe() == []


def test_une_exception_dans_un_projet_ne_prive_pas_les_autres(tmp_path):
    p, q = projet(tmp_path, "p"), projet(tmp_path, "q")
    battre(p, 120)
    battre(q, 120)
    m = Monde(tmp_path, p, q, repart_apres=1)
    vrai = m.demarrer

    def capricieux(chemin):
        if chemin == p:
            raise RuntimeError("boum")
        return vrai(chemin)

    m.s.demarrer = capricieux
    assert m.s.passe() == [str(q)]
    assert "alpha" not in (m.dossier / "surveillant.log").read_text()
    assert "p : erreur RuntimeError" in (m.dossier / "surveillant.log").read_text()


def test_la_boucle_passe_jusqu_a_l_arret(tmp_path):
    m = Monde(tmp_path)
    arret = threading.Event()
    passes = []
    m.s.passe = lambda: passes.append(1) or (arret.set() if len(passes) == 3 else None)
    m.s.boucler(arret, pas=0)
    assert len(passes) == 3
    journal = (m.dossier / "surveillant.log").read_text()
    assert "surveillant démarré" in journal and "surveillant arrêté" in journal


def test_la_notification_passe_par_le_notifieur_de_l_hote(monkeypatch):
    from cime.hote.gardes import Gardes
    vus = []
    monkeypatch.setattr(Gardes, "executer", lambda self, argv, **kw: vus.append(argv))
    monkeypatch.delenv("CIME_NOTIFICATIONS", raising=False)
    surveillant._notifier_mac("Projet", "le facteur ne repart pas")
    assert vus == [["osascript", "-e",
                    'display notification "le facteur ne repart pas" with title "Projet"']]
    vus.clear()
    monkeypatch.setenv("CIME_NOTIFICATIONS", "0")
    surveillant._notifier_mac("Projet", "essai")
    assert vus == []


def test_le_code_du_surveillant_ne_contient_aucune_commande_de_notification():
    texte = Path(surveillant.__file__).read_text(encoding="utf-8")
    assert "osascript" not in texte and "subprocess" not in texte


def test_servir_demarre_le_surveillant_sauf_si_on_le_coupe(tmp_path, monkeypatch):
    vus = []
    monkeypatch.setattr(Surveillant, "boucler", lambda self, arret, pas=0: vus.append(self.dossier))
    monkeypatch.delenv("CIME_SANS_SURVEILLANT", raising=False)
    arret = threading.Event()
    d = tmp_path / "d"
    t = threading.Thread(target=serveur.servir, kwargs=dict(dossier=d, cime=["x"], arret=arret),
                         daemon=True)
    t.start()
    import time
    fin = time.time() + 10
    while not vus and time.time() < fin:
        time.sleep(0.02)
    arret.set()
    t.join(10)
    assert vus == [d]


# --- launchd ------------------------------------------------------------------------------

def test_le_plist_est_du_xml_valide(tmp_path):
    texte = launchd.plist(cime="/usr/local/bin/cime", home=tmp_path, path="/usr/bin:/bin")
    donnees = plistlib.loads(texte.encode("utf-8"))
    assert donnees["Label"] == "cime.lanceur"
    assert donnees["ProgramArguments"] == ["/usr/local/bin/cime", "lanceur", "--port", "47615"]
    assert donnees["RunAtLoad"] is True and donnees["KeepAlive"] is True
    assert donnees["StandardOutPath"] == str(tmp_path / ".cime" / "lanceur.log")
    assert donnees["EnvironmentVariables"]["PATH"] == "/usr/bin:/bin"
    assert texte.startswith("<?xml")


def test_cime_lanceur_plist_imprime_sans_rien_installer(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert cli.main(["lanceur", "--plist"]) == 0
    sortie = capsys.readouterr()
    assert plistlib.loads(sortie.out.encode("utf-8"))["ProgramArguments"][1:] == ["lanceur", "--port", "47615"]
    assert "launchctl load" in sortie.err                     # la marche à suivre pour l'utilisateur
    assert not (tmp_path / "Library").exists()                # rien d'installé


def test_un_projet_ferme_n_est_jamais_relance(tmp_path):
    """`cime fermer` pose ferme.json : le surveillant ne relance rien, ne notifie pas."""
    p, q = projet(tmp_path, "p"), projet(tmp_path, "q")
    battre(p, 120)
    battre(q, 120)
    (p / ".orga" / "etat" / "ferme.json").write_text(json.dumps({"conversations": []}))
    m = Monde(tmp_path, p, q, actifs=True, repart_apres=1)
    assert m.s.passe() == [str(q)]
    assert m.lances == [q] and m.notifs == []
