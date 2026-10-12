"""Compléments du banc de bout en bout : reprise après /compact, page de l'utilisateur, accord de phase,
contexte lourd, dépendance bloquante, demande formulée par la page, question latérale entre équipes,
vérification, écran de démarrage et ouverture d'un coordinateur.

Mêmes règles que les autres fichiers : vraies commandes, vrais hooks, vrai facteur à horloge simulée ;
seul `lancer._lancer` est remplacé. La page est l'hôte réel (Starlette) dont seul l'exécuteur de
commandes est branché sur les commandes du banc (jamais un vrai processus ni un vrai tmux).
"""
import contextlib
import io
import os
import types

import pytest

from e2e.aides import (ASSISTANT, COORD, COORD_B, W, accuser, envoyer, etat, minutes_apres, nb_ecrits,
                       rien_ecrit, signalements, tape)
from e2e.test_commandes_garde_git import (ECHELLE, MODELE, faux_lancer, facteur_pendant_les_attentes,  # noqa: F401
                                          ordres, tache)

from cime.signaux import hooks


def obligation(banc, message_id):
    return banc.prouve("SELECT etat FROM obligations WHERE message_id = ?", (message_id,))


def escalades(banc, reference):
    return minutes_apres(banc, reference, ECHELLE)


# --- /compact du coordinateur, puis relance --reprendre ---------------------------------------

def _coord_compacte(banc):
    """Le coordinateur a une dette (une question de son worker, livrée et accusée) ; l'Assistant le fait compacter."""
    banc.au_repos(COORD)
    q = envoyer(banc, W, COORD, "question", "quelle branche pour le lot ?")
    banc.facteur_tour()
    accuser(banc, COORD, tape(banc))
    facteur_pendant_les_attentes(banc)
    r = banc.acteur(ASSISTANT).cime("compacter", COORD, "garde les décisions")
    assert r.code == 0, r.erreur
    return q


def test_compactage_du_coordinateur_normal(banc, faux_lancer):
    q = _coord_compacte(banc)
    echeance = banc.prouve("SELECT echeance FROM obligations WHERE message_id = ?", (q,))
    assert any("/compact" in ligne for _, ligne in banc.tmux.entrees)                # tapé par le facteur seul
    banc.acteur(COORD).hook("PostCompact", {"trigger": "manual"})
    debut = banc.acteur(COORD).hook("SessionStart", {"source": "compact"})
    assert debut.code == 0 and "Reprise de coord-alpha" in debut.stdout and f"#{q}" in debut.stdout
    assert obligation(banc, q) == [("ouverte",)]                                      # la dette a survécu
    assert banc.prouve("SELECT echeance FROM obligations WHERE message_id = ?", (q,)) == echeance
    assert "Reprise de coord-alpha" in banc.acteur(COORD).cime("reprise").sortie
    banc.tmux.absente(COORD)                                                          # la session est fermée…
    r = banc.acteur(ASSISTANT).cime("lancer", "coord", "alpha", "--reprendre")
    assert r.code == 0, r.erreur
    assert faux_lancer == [("coord", "alpha", None, None)]
    assert banc.prouve("SELECT de, a, nature FROM messages WHERE objet = 'ouverture'"
                       ) == [("cime", COORD, "consigne")]                             # la reprise ouvre aussi
    reprise = banc.acteur(COORD).hook("SessionStart", {"source": "resume"})
    assert f"#{q}" in reprise.stdout and obligation(banc, q) == [("ouverte",)]
    assert banc.prouve("SELECT count(*) FROM evenements WHERE evenement = 'SessionStart'") == [(2,)]


def test_compactage_du_coordinateur_oubli(banc):
    """Le coordinateur ne fait rien après /compact : le code lui rend quand même la reprise, et la dette monte."""
    q = _coord_compacte(banc)
    assert banc.acteur(COORD).inerte().cime("repondre", str(q), "x") is None
    banc.acteur(COORD).hook("PostCompact", {"trigger": "manual"})
    debut = banc.acteur(COORD).hook("SessionStart", {"source": "compact"})
    assert f"#{q}" in debut.stdout                                                    # rendu par le hook, pas par l'agent
    assert rien_ecrit(banc, COORD)
    banc.faire_tourner(31 * 60, pas=60)
    assert escalades(banc, q) == [(COORD, "relance", 15.0), (ASSISTANT, "signalement", 30.0)]
    assert obligation(banc, q) == [("ouverte",)]


# --- lancer un coordinateur sous accord de l'utilisateur -------------------------------------------------

def _accord_de_chantier(banc, phase="p1"):
    """L'Assistant demande à l'utilisateur, qui accorde (à la main hors Claude Code, ou par la page)."""
    d = envoyer(banc, ASSISTANT, "utilisateur", "decision_utilisateur", f"ouvrir le chantier alpha ({phase}) ?",
                "--objet", f"chantier:alpha:{phase}")
    return d


def test_accord_de_phase_normal(banc, faux_lancer):
    facteur_pendant_les_attentes(banc)
    a = banc.acteur(ASSISTANT)
    sans_phase = a.cime("lancer", "coord", "alpha", "--modele", MODELE)
    assert sans_phase.code == 2 and "--phase obligatoire" in sans_phase.erreur
    sans_accord = a.cime("lancer", "coord", "alpha", "--modele", MODELE, "--phase", "p1")
    assert sans_accord.code == 2 and "aucun accord de l'utilisateur non consommé" in sans_accord.erreur
    assert ordres(banc) == [] and faux_lancer == []
    d = _accord_de_chantier(banc)
    accord = banc.acteur(None).cime("accorder", str(d))
    assert accord.code == 0, accord.erreur
    ok = a.cime("lancer", "coord", "alpha", "--modele", MODELE, "--phase", "p1")
    assert ok.code == 0, ok.erreur
    assert faux_lancer == [("coord", "alpha", None, MODELE)]
    assert etat(banc, accord.id) == "clos"                                        # un accord = un lancement
    autre = a.cime("lancer", "coord", "alpha", "--modele", MODELE, "--phase", "p1")
    assert autre.code == 2 and len(faux_lancer) == 1
    pas_la = a.cime("lancer", "coord", "alpha", "--modele", MODELE, "--phase", "p2")
    assert pas_la.code == 2                                                       # l'accord porte sur la phase p1
    assert banc.prouve("SELECT de, a, nature, objet FROM messages WHERE id = ?", (accord.id,)
                       ) == [("utilisateur", ASSISTANT, "accord", "chantier:alpha:p1")]


def test_accord_de_phase_oubli(banc, faux_lancer):
    """L'utilisateur ne répond pas : rien ne part ; la commande refuse, la décision est renotifiée à 2 h, jamais acceptée d'office."""
    d = _accord_de_chantier(banc)
    assert banc.acteur(None).inerte().cime("accorder", str(d)) is None
    r = banc.acteur(ASSISTANT).cime("lancer", "coord", "alpha", "--modele", MODELE, "--phase", "p1")
    assert r.code == 2 and faux_lancer == []
    banc.faire_tourner(121 * 60, pas=300)
    assert minutes_apres(banc, d, "m.de = 'cime' AND m.nature = 'relance'") == [("utilisateur", "relance", 120.0)]
    assert obligation(banc, d) == [("ouverte",)]
    assert banc.acteur(ASSISTANT).cime("lancer", "coord", "alpha", "--modele", MODELE, "--phase", "p1").code == 2


# --- ouverture d'un coordinateur -----------------------------------------------------------------

def _lancer_coord(banc, reprendre=False):
    d = _accord_de_chantier(banc)
    banc.acteur(None).cime("accorder", str(d))
    plus = ("--reprendre",) if reprendre else ("--phase", "p1")
    return banc.acteur(ASSISTANT).cime("lancer", "coord", "alpha", "--modele", MODELE, *plus)


def test_lancement_de_coordinateur_normal(banc, faux_lancer):
    facteur_pendant_les_attentes(banc)
    r = _lancer_coord(banc)
    assert r.code == 0, r.erreur
    assert banc.prouve("SELECT verbe, cible, etat FROM ordres") == [("lancer", COORD, "execute")]
    assert banc.tmux("has-session", "-t", f"=es-{COORD}:").returncode == 0           # la session existe


def test_lancement_de_coordinateur_normal_message_d_ouverture(banc, faux_lancer):
    facteur_pendant_les_attentes(banc)
    assert _lancer_coord(banc).code == 0
    assert banc.prouve("SELECT de, a, nature, objet FROM messages WHERE objet = 'ouverture'"
                       ) == [("cime", COORD, "consigne", "ouverture")]


def test_lancement_de_coordinateur_oubli(banc, faux_lancer):
    facteur_pendant_les_attentes(banc)
    assert _lancer_coord(banc).code == 0
    banc.tmux.absente(COORD)                                                         # la session meurt avant de démarrer
    banc.faire_tourner(5 * 60, pas=30)
    assert (ASSISTANT, "session-absente:" + COORD) in signalements(banc)


# --- écran de démarrage qui attend l'utilisateur -----------------------------------------------------

@pytest.fixture
def lancer_bloque(monkeypatch, faux_lancer):
    """Le lancement naît mais Claude Code affiche son écran de confiance : `lancer` rend le code 3."""
    from cime.fondation import lancer
    normal = lancer._lancer

    def bloque(args, projet=None):
        session, _ = normal(args, projet)
        return session, lancer.CODE_APPROBATION
    monkeypatch.setattr(lancer, "_lancer", bloque)
    return faux_lancer


def test_approbation_terminal_bloquee_normal(banc, lancer_bloque):
    facteur_pendant_les_attentes(banc)
    r = _lancer_coord(banc)
    assert r.code == 3, r.erreur                                                     # code 3 : approbation attendue
    assert banc.prouve("SELECT verbe, etat FROM ordres") == [("lancer", "execute")]
    assert banc.prouve("SELECT etat FROM transitions WHERE message_id = 1 ORDER BY id DESC LIMIT 1") == [("clos",)]


def test_approbation_terminal_bloquee_oubli(banc, lancer_bloque):
    """Personne n'approuve dans le terminal : le code doit le signaler à l'Assistant puis à l'utilisateur (2 min)."""
    facteur_pendant_les_attentes(banc)
    assert _lancer_coord(banc).code == 3
    banc.faire_tourner(3 * 60, pas=30)
    assert (ASSISTANT, f"approbation:es-{COORD}") in signalements(banc)
    s = banc.prouve("SELECT id FROM messages WHERE objet = ?", (f"approbation:es-{COORD}",))[0][0]
    assert escalades(banc, s)[-1][:2] == ("utilisateur", "signalement")


# --- un contexte lourd est signalé au supérieur, qui fait compacter ----------------------------

def _contexte_lourd(banc, agent=COORD, depuis=1000):
    """L'hôte voit l'alarme `contexte_au_repos` (le calcul de jetons est celui de l'observation, hors banc)."""
    from cime.hote.rafraichisseur import signaler_contextes
    inst = {"alarmes": [{"type": "contexte_au_repos", "agents": [agent], "depuis": depuis}]}
    return signaler_contextes(banc.projet, inst)


def test_compactage_de_l_assistant_normal(banc):
    banc.au_repos(ASSISTANT)
    banc.au_repos(COORD)
    facteur_pendant_les_attentes(banc)
    assert _contexte_lourd(banc) == 1 and _contexte_lourd(banc) == 0                  # une seule fois par épisode
    (s, a, nature), = banc.prouve("SELECT id, a, nature FROM messages WHERE objet = ?", (f"contexte:{COORD}",))
    assert (a, nature) == (ASSISTANT, "signalement")
    banc.facteur_tour()
    accuser(banc, ASSISTANT, tape(banc))
    r = banc.acteur(ASSISTANT).cime("compacter", COORD, "garde les décisions")        # le geste est une commande
    assert r.code == 0, r.erreur
    banc.acteur(COORD).hook("PostCompact", {"trigger": "manual"})
    assert banc.prouve("SELECT verbe, cible, etat FROM ordres") == [("compacter", COORD, "execute")]
    assert _contexte_lourd(banc, depuis=2000) == 1                                    # un nouvel épisode signale de nouveau
    assert etat(banc, s) in ("pris_en_compte", "clos")


def test_compactage_de_l_assistant_oubli(banc):
    """L'Assistant ne compacte rien : relance à 10 min, puis le supérieur de l'Assistant (l'utilisateur) à 30 min."""
    banc.au_repos(COORD)
    assert _contexte_lourd(banc) == 1
    s = banc.prouve("SELECT id FROM messages WHERE objet = ?", (f"contexte:{COORD}",))[0][0]
    assert banc.acteur(ASSISTANT).inerte().cime("compacter", COORD, "x") is None
    assert banc.prouve("SELECT count(*) FROM ordres") == [(0,)]
    banc.faire_tourner(31 * 60, pas=60)
    assert escalades(banc, s) == [(ASSISTANT, "relance", 10.0), ("utilisateur", "signalement", 30.0)]


# --- un coordinateur ne peut pas demander son compactage ---------

def test_aucun_chemin_pour_demander_son_compactage(banc, faux_lancer):
    banc.au_repos(ASSISTANT)
    banc.au_repos(COORD)
    c = banc.acteur(COORD)
    essais = [("compacter", "assistant", "x"), ("compacter", COORD, "x"),
              ("envoyer", "--a", "assistant", "--nature", "consigne", "--attend", "rien", "compacte-moi"),
              ("envoyer", "--a", "assistant", "--nature", "compacter", "compacte-moi")]
    assert [c.cime(*e).code for e in essais] == [2, 2, 2, 1]
    assert banc.prouve("SELECT count(*) FROM ordres") == [(0,)]
    assert banc.prouve("SELECT count(*) FROM messages WHERE resume LIKE '/compact%' AND resume LIKE '%refusé%'"
                       ) == [(2,)]                                                  # seules traces : les deux refus, déjà clos
    assert banc.prouve("SELECT count(*) FROM obligations") == [(0,)]
    q = c.cime("envoyer", "--a", "assistant", "--nature", "question", "--objet", "compacter", "peux-tu me compacter ?")
    assert q.code == 0                                                       # une question ordinaire, rien de plus
    banc.faire_tourner(60, pas=30)
    assert banc.prouve("SELECT count(*) FROM ordres") == [(0,)]
    assert not any("/compact" in ligne for _, ligne in banc.tmux.entrees)    # personne n'a rien tapé chez lui


# --- dépendance bloquante entre équipes -----------------------------------------------------------

def _dependances(banc, statut):
    (banc.projet / ".orga" / "dependencies.md").write_text(f"# Dépendances\n\n## alpha\n\n- Statut : {statut}\n")


def _accord_worker(banc):
    d = envoyer(banc, COORD, ASSISTANT, "demande_accord", "lancer t1", "--objet", "lancer-worker:alpha:t1")
    return banc.acteur(ASSISTANT).cime("accorder", str(d), "--modele", MODELE).id


def test_dependances_non_lues_normal(banc, faux_lancer):
    tache(banc)
    facteur_pendant_les_attentes(banc)
    accord = _accord_worker(banc)
    _dependances(banc, "BLOQUÉ (attend le contrat de beta)")
    r = banc.acteur(COORD).cime("lancer", "worker", "alpha", "t1", "--modele", MODELE)
    assert r.code == 2 and "bloquée" in r.erreur and faux_lancer == [] and ordres(banc) == []
    assert etat(banc, accord) == "inscrit"                                   # l'accord n'est pas consommé par un refus
    _dependances(banc, "EN COURS")
    ok = banc.acteur(COORD).cime("lancer", "worker", "alpha", "t1", "--modele", MODELE)
    assert ok.code == 0, ok.erreur
    assert faux_lancer == [("worker", "alpha", "t1", MODELE)] and etat(banc, accord) == "clos"


def test_dependances_non_lues_oubli(banc, faux_lancer):
    """Le coordinateur ne lit pas `dependencies.md` et lance quand même, à chaque fois : la commande refuse."""
    tache(banc)
    accord = _accord_worker(banc)
    _dependances(banc, "BLOQUÉ (attend le contrat de beta)")
    for _ in range(3):
        assert banc.acteur(COORD).cime("lancer", "worker", "alpha", "t1", "--modele", MODELE).code == 2
    assert faux_lancer == [] and ordres(banc) == [] and etat(banc, accord) == "inscrit"
    assert (banc.projet / ".orga/teams/alpha/tasks/todo/t1.md").exists()     # la tâche n'a pas bougé


# --- question latérale entre équipes --------------------------------------------------------------

def test_consigne_laterale_normal(banc):
    banc.au_repos(ASSISTANT)
    banc.au_repos(COORD_B)
    q = envoyer(banc, COORD, ASSISTANT, "question", "quel est le format du fil côté beta ?", "--objet", "laterale:beta")
    c = envoyer(banc, ASSISTANT, COORD_B, "consigne", "alpha demande le format du fil", "--attend", "reponse")
    r = banc.acteur(COORD_B).cime("repondre", str(c), "le fil est en JSON lignes")
    assert r.code == 0, r.erreur
    r2 = banc.acteur(ASSISTANT).cime("repondre", str(q), "beta dit : JSON lignes")
    assert r2.code == 0, r2.erreur
    assert banc.prouve("SELECT m.id, o.debiteur, o.etat FROM messages m JOIN obligations o ON o.message_id = m.id"
                       " WHERE m.id IN (?, ?) ORDER BY m.id", (q, c)) == [(q, ASSISTANT, "satisfaite"),
                                                                           (c, COORD_B, "satisfaite")]
    assert banc.prouve("SELECT count(*) FROM messages WHERE de = ? AND a = ?", (COORD, COORD_B)) == [(0,)]  # jamais en direct


def test_consigne_laterale_oubli(banc):
    """L'Assistant ne pose pas sa consigne à l'autre coordinateur : il reste débiteur, la question monte."""
    q = envoyer(banc, COORD, ASSISTANT, "question", "quel est le format du fil côté beta ?", "--objet", "laterale:beta")
    assert banc.acteur(ASSISTANT).inerte().cime("envoyer", "--a", COORD_B, "x") is None
    assert nb_ecrits(banc, ASSISTANT) == 0
    banc.faire_tourner(61 * 60, pas=60)
    assert escalades(banc, q) == [(ASSISTANT, "relance", 15.0), ("utilisateur", "signalement", 30.0)]
    assert obligation(banc, q) == [("ouverte",)]
    assert banc.prouve("SELECT count(*) FROM messages WHERE a = ?", (COORD_B,)) == [(0,)]


# --- la vérification et l'Assistant --------------------------------------------------------------

VERIFICATION = "worker-integration-r1"


def test_verification_sans_reponse_normal(banc):
    (banc.projet / ".orga" / "teams" / "integration").mkdir()
    c = banc.acteur(ASSISTANT).cime("envoyer", "--a", VERIFICATION, "--nature", "consigne", "--attend", "reponse",
                                    "vérifie le lot alpha")
    assert c.code == 0, c.erreur
    s = banc.acteur(VERIFICATION).cime("envoyer", "--a", ASSISTANT, "--nature", "signalement", "--objet", "ecart:alpha",
                                       "écart entre la décision et le code")
    assert s.code == 0, s.erreur
    r = banc.acteur(VERIFICATION).cime("repondre", str(c.id), "lot conforme")
    assert r.code == 0 and etat(banc, c.id) == "clos"


def test_verification_sans_reponse_oubli(banc):
    """La vérification ne répond pas : relance par la dette au repos."""
    (banc.projet / ".orga" / "teams" / "integration").mkdir()
    facteur_pendant_les_attentes(banc)
    banc.au_repos(ASSISTANT)
    banc.au_repos(VERIFICATION)
    c = banc.acteur(ASSISTANT).cime("envoyer", "--a", VERIFICATION, "--nature", "consigne", "--attend", "reponse",
                                    "vérifie le lot alpha")
    assert c.code == 0, c.erreur
    banc.faire_tourner(61 * 60, pas=60)
    assert banc.prouve("SELECT a, nature FROM messages WHERE objet LIKE 'dette:%' AND nature = 'relance' ORDER BY id"
                       ) == [(VERIFICATION, "relance")]                          # la dette au repos relance le débiteur
    assert obligation(banc, c.id) == [("ouverte",)]


# --- la page de l'utilisateur : l'hôte réel, dont seules les commandes sont celles du banc ---------------------------

class Page:
    PORT = 8767

    def __init__(self, banc, monkeypatch):
        from starlette.testclient import TestClient
        from cime.hote import creer_app
        from cime.hote.dependances import Dependances
        from cime.hote.gardes import Gardes
        self.banc = banc

        async def faux(_self, argv, **kw):
            if argv[0] == "tmux":                       # le terminal est celui du banc, jamais un vrai tmux
                return banc.tmux(*argv[1:])
            with contextlib.chdir(kw.get("cwd") or os.getcwd()):                # l'hôte lance depuis la racine du projet
                r = banc.acteur(kw["env"]["CIME_AGENT"]).cime(*argv[1:])  # `cime <verbe> …` en tant qu'utilisateur
            return types.SimpleNamespace(returncode=r.code, stdout=r.sortie, stderr=r.erreur)
        monkeypatch.setattr(Gardes, "aexecuter", faux)
        deps = Dependances(instantane=lambda p: {}, horloge=banc.horloge.maintenant, prefixe="es")
        self.client = TestClient(creer_app(banc.projet, deps, self.PORT), headers={"host": f"127.0.0.1:{self.PORT}"})
        self.entetes = {"origin": f"http://127.0.0.1:{self.PORT}"}

    def voir(self):
        """Ce que la page affiche : l'instantané réel du projet jetable (attentes de l'utilisateur comprises)."""
        import importlib
        inst = importlib.import_module("cime.observation.instantane").instantane(self.banc.projet)
        self.client.app.state.contexte.rafraichisseur.instantane = inst
        return inst

    def poster(self, route, **corps):
        self.voir()
        return self.client.post(f"/api/actions/{route}", json=corps, headers=self.entetes).json()


@pytest.fixture
def page(banc, monkeypatch):
    return Page(banc, monkeypatch)


# --- la page de l'utilisateur : trancher, déposer, refuser ------------------------------------------

def _attentes(banc):
    d = envoyer(banc, ASSISTANT, "utilisateur", "decision_utilisateur", "quelle option ?", "--objet", "choix:cap")
    f = envoyer(banc, ASSISTANT, "utilisateur", "donnee_utilisateur", "dépose le jeu de données", "--objet", "donnee:jeu")
    g = envoyer(banc, ASSISTANT, "utilisateur", "decision_utilisateur", "fusionner alpha ?", "--objet", "fusion:alpha:abc123")
    return d, f, g


def _ligne(banc, message_id):
    return banc.prouve("SELECT de, a, nature, en_reponse_a FROM messages WHERE en_reponse_a = ? AND de = 'utilisateur'",
                       (message_id,))


def test_attentes_de_l_utilisateur_normal(banc, page):
    d, f, g = _attentes(banc)
    assert {a["id"] for a in page.voir()["attentes_utilisateur"]} == {f"msg-{d}", f"msg-{f}", f"msg-{g}"}
    assert page.poster("trancher", attente_id=f"msg-{d}", reponse="l'option B")["resultat"] == "ok"
    envoi = page.client.post("/api/actions/deposer", data={"attente_id": f"msg-{f}"}, headers=page.entetes,
                             files={"fichier": ("jeu.csv", b"a,b\n1,2\n")})
    assert envoi.json()["resultat"] == "ok", envoi.json()
    assert page.poster("refuser", attente_id=f"msg-{g}", motif="pas avant la revue")["resultat"] == "ok"
    assert _ligne(banc, d) == [("utilisateur", ASSISTANT, "reponse", d)]
    assert _ligne(banc, f) == [("utilisateur", ASSISTANT, "reponse", f)]
    assert _ligne(banc, g) == [("utilisateur", ASSISTANT, "refus", g)]
    assert [obligation(banc, m) for m in (d, f, g)] == [[("satisfaite",)]] * 3
    assert (banc.projet / ".orga" / "depots" / f"msg-{f}" / "jeu.csv").read_bytes() == b"a,b\n1,2\n"
    assert page.poster("trancher", attente_id=f"msg-{d}", reponse="encore")["resultat"] == "refuse"      # une fois seulement
    banc.au_repos(ASSISTANT)                                                         # son `Stop` lui rend les trois réponses
    assert banc.prouve("SELECT count(*) FROM transitions WHERE etat = 'livre' AND message_id IN"
                       " (SELECT id FROM messages WHERE de = 'utilisateur' AND a = 'assistant')") == [(3,)]
    assert page.voir()["attentes_utilisateur"] == []


def test_attentes_de_l_utilisateur_oubli(banc, page):
    """L'utilisateur ne clique sur rien : rien n'est décidé à sa place, la page garde les attentes et le code les renotifie à 2 h."""
    d, f, g = _attentes(banc)
    banc.faire_tourner(121 * 60, pas=300)
    assert [_ligne(banc, m) for m in (d, f, g)] == [[], [], []]
    assert [obligation(banc, m) for m in (d, f, g)] == [[("ouverte",)]] * 3
    assert len(page.voir()["attentes_utilisateur"]) == 3
    assert minutes_apres(banc, d, "m.de = 'cime' AND m.nature = 'relance' AND m.en_reponse_a = r.id"
                         ) == [("utilisateur", "relance", 120.0)]
    assert page.poster("trancher", attente_id="msg-999", reponse="x")["resultat"] == "refuse"           # attente inconnue


# --- une demande de l'utilisateur formulée depuis la page est un acte de coordination -----------------------

def _demande(banc, a=ASSISTANT):
    return banc.acteur("utilisateur").cime("envoyer", "--a", a, "--nature", "consigne", "--attend", "reponse",
                                      "--objet", "demande-page", "relance l'équipe alpha")


def test_demande_a_l_assistant_normal(banc):
    banc.au_repos(ASSISTANT)
    vers_coord = _demande(banc, COORD)
    assert vers_coord.code == 2 and "hors matrice" in vers_coord.erreur         # jamais vers un coordinateur
    assert banc.prouve("SELECT count(*) FROM messages") == [(0,)]
    d = _demande(banc)
    assert d.code == 0, d.erreur
    assert banc.prouve("SELECT de, a, nature, objet FROM messages WHERE id = ?", (d.id,)
                       ) == [("utilisateur", ASSISTANT, "consigne", "demande-page")]
    banc.facteur_tour()
    accuser(banc, ASSISTANT, tape(banc))
    assert obligation(banc, d.id) == [("ouverte",)]
    r = banc.acteur(ASSISTANT).cime("repondre", str(d.id), "alpha est relancée")
    assert r.code == 0 and obligation(banc, d.id) == [("satisfaite",)]


def test_demande_a_l_assistant_oubli(banc):
    """L'Assistant ne traite pas la demande : elle est livrée, et reste ouverte. Aucune relance de dette
 : l'Assistant n'est jamais relancé dans son terminal, la demande n'a pas d'échéance absolue."""
    banc.au_repos(ASSISTANT)
    d = _demande(banc)
    assert banc.acteur(ASSISTANT).inerte().cime("repondre", str(d.id), "x") is None
    banc.faire_tourner(31 * 60, pas=60)
    assert minutes_apres(banc, d.id, "m.de = 'cime' AND m.nature = 'relance'") == []
    assert banc.prouve("SELECT count(*) FROM messages WHERE objet LIKE 'dette:%'") == [(0,)]
    assert obligation(banc, d.id) == [("ouverte",)]


def test_demande_a_l_assistant_normal_route_de_la_page(banc, page):
    """La page formule sa demande à l'Assistant par `POST /api/actions/demander` : même ligne de registre que la commande."""
    banc.au_repos(ASSISTANT)
    r = page.poster("demander", texte="relance l'équipe alpha")
    assert r["resultat"] == "ok", r
    (d, de, a, nature, attend, objet), = banc.prouve(
        "SELECT m.id, m.de, m.a, m.nature, o.attendu, m.objet FROM messages m JOIN obligations o ON o.message_id = m.id")
    assert (de, a, nature, attend, objet) == ("utilisateur", ASSISTANT, "consigne", "reponse", "demande-page")
    assert banc.prouve("SELECT auteur, action, cible, resultat FROM journal") == [("utilisateur", "demander", "assistant", "ok")]
    assert page.poster("demander", texte="")["resultat"] == "refuse"
    assert banc.prouve("SELECT count(*) FROM messages") == [(1,)]                   # jamais d'autre destinataire
