"""Conversations d'un projet, aperçu et installation de Cime dans un projet existant."""
import json

import pytest

from cime.lanceur import serveur as mod

from .conftest import journal


def projet(tmp_path, nom="alpha", prefixe="al"):
    d = tmp_path / nom
    (d / ".orga").mkdir(parents=True)
    (d / ".orga" / "projet.toml").write_text(f'nom = "{nom}"\nprefixe = "{prefixe}"\n')
    return d


def dossier_nu(tmp_path, nom="beta"):
    d = tmp_path / nom
    d.mkdir()
    (d / "README.md").write_text("bonjour\n")
    return d


def instantane(d):
    """Tout ce qui se trouve sous `d` : chemins et contenus (None pour un dossier)."""
    return {str(p.relative_to(d)): (None if p.is_dir() else p.read_bytes()) for p in sorted(d.rglob("*"))}


@pytest.fixture(autouse=True)
def agents_inactifs(monkeypatch):
    """Aucun test ne doit interroger tmux."""
    monkeypatch.setattr(mod, "_agents_actifs", lambda chemin: False)


class Ouvreur:
    """Faux `ouvrir_fenetre` : enregistre les sessions demandées, répond `reponse`."""

    def __init__(self):
        self.appels, self.reponse = [], True

    def __call__(self, dossier, session, terminal=None, lancer=None):
        self.appels.append(session)
        return self.reponse


@pytest.fixture(autouse=True)
def ouvreur(monkeypatch):
    o = Ouvreur()
    monkeypatch.setattr(mod, "ouvrir_fenetre", o)
    return o


# ── GET /api/projets/conversations ──────────────────────────────────────────────────────

CONVERSATIONS_FAUSSES = [
    {"session": "c-1", "date": "2026-10-12T09:00:00Z", "taille": 1234, "debut": "Bonjour"},
    {"session": "c-2", "date": "2026-10-11T18:00:00Z", "taille": 88, "debut": None},
    {"session": "c-3", "date": "2026-10-10T08:00:00Z", "taille": 4096, "debut": "Où en est la liste ?"},
]


def conversations(lanceur, chemin):
    return lanceur.get("/api/projets/conversations", params={"chemin": str(chemin)})


def test_conversations_ok_liste_telle_quelle(lanceur, tmp_path):
    p = projet(tmp_path)
    r = conversations(lanceur, p)
    corps = r.json()
    assert r.status_code == 200 and corps["resultat"] == "ok"
    assert corps["conversations"] == CONVERSATIONS_FAUSSES
    assert corps["fermeture"] is None


def test_conversations_fermeture_est_la_session_de_l_assistant(lanceur, tmp_path):
    p = projet(tmp_path)
    (p / ".orga" / "etat").mkdir(parents=True)
    (p / ".orga" / "etat" / "ferme.json").write_text(json.dumps({"conversations": [
        {"agent": "coord-hote", "session": "s-2", "tmux": "t2"},
        {"agent": "assistant", "session": "s-1", "tmux": "t1"}]}))
    assert conversations(lanceur, p).json()["fermeture"] == "s-1"


def test_conversations_ferme_json_sans_assistant_ou_illisible(lanceur, tmp_path):
    p = projet(tmp_path)
    (p / ".orga" / "etat").mkdir(parents=True)
    (p / ".orga" / "etat" / "ferme.json").write_text(json.dumps({"conversations": [
        {"agent": "coord-hote", "session": "s-2", "tmux": "t2"}]}))
    assert conversations(lanceur, p).json()["fermeture"] is None
    (p / ".orga" / "etat" / "ferme.json").write_text("{pas du json")
    assert conversations(lanceur, p).json()["fermeture"] is None


def test_conversations_plafonnees_a_trente(lanceur, tmp_path, monkeypatch):
    monkeypatch.setenv("FAUX_CIME_BEAUCOUP", "1")
    corps = conversations(lanceur, projet(tmp_path)).json()
    assert corps["resultat"] == "ok"
    assert [c["session"] for c in corps["conversations"]] == [f"c-{i}" for i in range(30)]


@pytest.mark.parametrize("cas", ["absent", "relatif", "sans", "vide"])
def test_conversations_chemin_refuse_400(lanceur, tmp_path, trace, cas):
    (tmp_path / "sans").mkdir()
    chemin = {"absent": str(tmp_path / "absent"), "relatif": "relatif", "sans": str(tmp_path / "sans"),
              "vide": ""}[cas]
    r = lanceur.get("/api/projets/conversations", params={"chemin": chemin})
    assert r.status_code == 400 and r.json()["resultat"] == "refuse"
    assert trace() == []


def test_conversations_sans_parametre_400(lanceur, tmp_path, trace):
    r = lanceur.get("/api/projets/conversations")
    assert r.status_code == 400 and r.json()["resultat"] == "refuse" and trace() == []


def test_conversations_commande_en_erreur(lanceur, tmp_path, monkeypatch):
    monkeypatch.setenv("FAUX_CIME_ERREUR", "registre absent")
    corps = conversations(lanceur, projet(tmp_path)).json()
    assert corps["resultat"] == "erreur" and corps["code"] == 1
    assert corps["message"] == "registre absent" and "conversations" not in corps
    assert "registre absent" in corps["sortie"]


def test_conversations_sortie_sans_objet_json(lanceur, tmp_path, monkeypatch):
    monkeypatch.setenv("FAUX_CIME_TEXTE", "1")
    corps = conversations(lanceur, projet(tmp_path)).json()
    assert corps["resultat"] == "erreur" and corps["code"] == 0
    assert corps["message"] == "La liste des conversations est indisponible."


def test_conversations_delai_depasse(lanceur, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "DELAI_CONVERSATIONS_S", 1)
    monkeypatch.setenv("FAUX_CIME_LENT", "1")
    corps = conversations(lanceur, projet(tmp_path)).json()
    assert corps["resultat"] == "erreur" and corps["code"] is None
    assert corps["message"] == "La commande a pris plus de 1 s (elle est peut-être encore en cours)."
    assert "sortie" in corps


def test_conversations_argv_env_et_sans_journal(lanceur, tmp_path, trace):
    p = projet(tmp_path)
    conversations(lanceur, p)
    (appel,) = trace()
    assert appel["argv"] == ["conversations", str(p.resolve()), "--json"]
    assert appel["CIME_PROJET"] is None and appel["CIME_AGENT"] is None
    assert journal(lanceur) == []


# ── ajouter : dossier sans manifeste → aperçu d'installation ────────────────────────────

APERCU = {"nom": "beta", "commit": False, "cree": [".orga/projet.toml", ".orga/etat/"],
          "complete": [], "garde": []}


def test_ajouter_sans_manifeste_propose_l_installation(lanceur, tmp_path, trace):
    d = dossier_nu(tmp_path)
    avant = instantane(d)
    r = lanceur.post("/api/projets/ajouter", json={"chemin": str(d)})
    assert r.status_code == 409
    assert r.json() == {"resultat": "refuse", "installable": True, "apercu": APERCU,
                        "message": "Cime n'est pas installé dans ce dossier."}
    assert instantane(d) == avant                       # l'aperçu n'écrit rien
    (appel,) = trace()
    assert appel["argv"] == ["init", "--apercu", str(d.resolve()), "--json"]
    assert lanceur.get("/api/projets").json()["projets"] == []


def test_ajouter_apercu_en_echec_non_installable(lanceur, tmp_path, monkeypatch):
    monkeypatch.setenv("FAUX_CIME_APERCU_ECHEC", "1")
    d = dossier_nu(tmp_path)
    avant = instantane(d)
    r = lanceur.post("/api/projets/ajouter", json={"chemin": str(d)})
    corps = r.json()
    assert r.status_code == 409 and corps["resultat"] == "refuse" and corps["installable"] is False
    assert corps["message"] == "L'aperçu de l'installation est indisponible." and "apercu" not in corps
    assert "aperçu impossible" in corps["sortie"]
    assert instantane(d) == avant


def test_ajouter_apercu_erreur_json_donne_son_message(lanceur, tmp_path, monkeypatch):
    monkeypatch.setenv("FAUX_CIME_APERCU_JSON", "1")
    d = dossier_nu(tmp_path)
    corps = lanceur.post("/api/projets/ajouter", json={"chemin": str(d)}).json()
    assert corps["installable"] is False and "apercu" not in corps
    assert corps["message"] == "cime init : ce dossier n'est pas lisible"
    assert "{" not in corps["message"] and "resultat" not in corps["message"]


def test_ajouter_apercu_delai_depasse_non_installable(lanceur, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "DELAI_APERCU_S", 1)
    monkeypatch.setenv("FAUX_CIME_LENT", "1")
    d = dossier_nu(tmp_path)
    corps = lanceur.post("/api/projets/ajouter", json={"chemin": str(d)}).json()
    assert corps["installable"] is False
    assert corps["message"] == "La commande a pris plus de 1 s (elle est peut-être encore en cours)."


@pytest.mark.parametrize("cas", ["absent", "fichier"])
def test_ajouter_absent_ou_fichier_400(lanceur, tmp_path, trace, cas):
    (tmp_path / "fichier").write_text("x")
    chemin = tmp_path / ("absent" if cas == "absent" else "fichier")
    r = lanceur.post("/api/projets/ajouter", json={"chemin": str(chemin)})
    assert r.status_code == 400 and r.json()["resultat"] == "refuse"
    assert trace() == []


def test_ajouter_avec_manifeste_sans_apercu(lanceur, tmp_path, trace):
    p = projet(tmp_path)
    assert lanceur.post("/api/projets/ajouter", json={"chemin": str(p)}).json()["resultat"] == "ok"
    assert trace() == []


# ── installer ───────────────────────────────────────────────────────────────────────────

def installer(lanceur, chemin, **corps):
    return lanceur.post("/api/projets/installer", json={"chemin": str(chemin), **corps})


def test_installer_ok(lanceur, tmp_path, trace, ouvreur):
    d = dossier_nu(tmp_path, "gamma")
    r = installer(lanceur, d, utilisateur="Léa")
    corps = r.json()
    assert r.status_code == 200 and corps["resultat"] == "ok"
    assert corps["chemin"] == str(d.resolve()) and corps["prefixe"] == "p-gamma"
    assert corps["a_approuver"] is False and corps["fenetre"] is True
    assert corps["commandes"] == ["tmux attach -t p-gamma-assistant"]
    assert "init fait" in corps["message"]
    assert (d / ".orga" / "projet.toml").is_file()
    assert ouvreur.appels == ["p-gamma-assistant"]
    (appel,) = trace()
    assert appel["argv"] == ["init", str(d.resolve()), "--utilisateur", "Léa", "--lancer"]
    (projet_lu,) = lanceur.get("/api/projets").json()["projets"]
    assert projet_lu["chemin"] == str(d.resolve()) and projet_lu["nom"] == "gamma"


def test_installer_code_3_a_approuver(lanceur, tmp_path, monkeypatch):
    monkeypatch.setenv("FAUX_CIME_CODE", "3")
    corps = installer(lanceur, dossier_nu(tmp_path), utilisateur="Léa").json()
    assert corps["resultat"] == "ok" and corps["a_approuver"] is True


def test_installer_fenetre_fausse_donne_commandes(lanceur, tmp_path, ouvreur):
    ouvreur.reponse = False
    corps = installer(lanceur, dossier_nu(tmp_path, "delta"), utilisateur="Léa").json()
    assert corps["resultat"] == "ok" and corps["fenetre"] is False
    assert corps["commandes"] == ["tmux attach -t p-delta-assistant"]


def test_installer_nom_et_prefixe_transmis(lanceur, tmp_path, trace):
    d = dossier_nu(tmp_path, "epsilon-dossier")
    corps = installer(lanceur, d, utilisateur="Léa", nom="epsilon", prefixe="ep").json()
    assert corps["resultat"] == "ok" and corps["prefixe"] == "ep"
    assert corps["commandes"] == ["tmux attach -t ep-assistant"]
    (appel,) = trace()
    assert appel["argv"] == ["init", str(d.resolve()), "--utilisateur", "Léa", "--lancer",
                             "--nom-projet", "epsilon", "--prefixe", "ep"]


def test_installer_utilisateur_du_lanceur_a_defaut(lanceur, tmp_path, trace):
    (lanceur.dossier / "lanceur.json").write_text(json.dumps({"utilisateur": "Max"}))
    d = dossier_nu(tmp_path, "zeta")
    assert installer(lanceur, d).json()["resultat"] == "ok"
    assert trace()[0]["argv"][2:4] == ["--utilisateur", "Max"]


@pytest.mark.parametrize("val", [None, "", "   "])
def test_installer_utilisateur_absent_partout_400(lanceur, tmp_path, trace, val):
    d = dossier_nu(tmp_path)
    corps = {} if val is None else {"utilisateur": val}
    r = installer(lanceur, d, **corps)
    assert r.status_code == 400 and r.json()["resultat"] == "refuse"
    assert trace() == [] and not (d / ".orga").exists()


def test_installer_utilisateur_du_corps_gardé_sans_effacer_terminal(lanceur, tmp_path):
    (lanceur.dossier / "lanceur.json").write_text(json.dumps({"terminal": "iTerm", "utilisateur": "Ancien"}))
    assert installer(lanceur, dossier_nu(tmp_path), utilisateur="Léa").json()["resultat"] == "ok"
    assert json.loads((lanceur.dossier / "lanceur.json").read_text()) == {"terminal": "iTerm", "utilisateur": "Léa"}


@pytest.mark.parametrize("cle, val", [("nom", "Epsilon"), ("nom", "a b"), ("nom", "../x"), ("nom", ""),
                                      ("prefixe", "X_y"), ("prefixe", "")])
def test_installer_nom_ou_prefixe_hors_motif_400(lanceur, tmp_path, trace, cle, val):
    d = dossier_nu(tmp_path)
    r = installer(lanceur, d, utilisateur="Léa", **{cle: val})
    assert r.status_code == 400 and r.json()["resultat"] == "refuse"
    assert trace() == [] and not (d / ".orga").exists()


def test_installer_deja_installe_409(lanceur, tmp_path, trace):
    p = projet(tmp_path)
    r = installer(lanceur, p, utilisateur="Léa")
    assert r.status_code == 409 and r.json()["resultat"] == "refuse"
    assert "déjà installé" in r.json()["message"] and trace() == []


def test_installer_manifeste_illisible_refuse_sans_rien_lancer(lanceur, tmp_path, trace):
    p = tmp_path / "casse"
    (p / ".orga").mkdir(parents=True)
    (p / ".orga" / "projet.toml").write_text("= pas du toml")
    r = installer(lanceur, p, utilisateur="Léa")
    assert r.status_code == 409 and "pas lisible" in r.json()["message"]
    assert trace() == [] and (p / ".orga" / "projet.toml").read_text() == "= pas du toml"


@pytest.mark.parametrize("cas", ["absent", "fichier"])
def test_installer_absent_ou_fichier_400(lanceur, tmp_path, trace, cas):
    (tmp_path / "fichier").write_text("x")
    chemin = tmp_path / cas
    r = installer(lanceur, chemin, utilisateur="Léa")
    assert r.status_code == 400 and r.json()["resultat"] == "refuse" and trace() == []


def test_installer_code_inattendu_erreur(lanceur, tmp_path, monkeypatch, ouvreur):
    monkeypatch.setenv("FAUX_CIME_CODE", "5")
    corps = installer(lanceur, dossier_nu(tmp_path), utilisateur="Léa").json()
    assert corps["resultat"] == "erreur" and corps["code"] == 5
    assert ouvreur.appels == [] and lanceur.get("/api/projets").json()["projets"] == []


def test_installer_journal_une_ligne_auteur_utilisateur(lanceur, tmp_path):
    d = dossier_nu(tmp_path, "eta")
    installer(lanceur, d, utilisateur="Léa")
    (ligne,) = journal(lanceur)
    assert ligne["action"] == "installer" and ligne["auteur"] == "utilisateur"
    assert ligne["resultat"] == "ok" and ligne["cible"] == str(d.resolve())
