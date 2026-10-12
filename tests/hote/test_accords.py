"""L'exécution des accords d'autorisation (l'hôte relit l'écran
et tape la touche) et « Accorder la fusion » / « Accorder le chantier ». Faux tmux : on remplace
`Gardes.executer` (la liste blanche, elle, s'applique) ; aucune commande n'est lancée pour de vrai."""
import asyncio
import functools
import json
import sqlite3
import subprocess
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from cime import cli
from cime.fondation import registre
from cime.hote import actions_autorisation, creer_app
from cime.hote.dependances import Dependances
from cime.hote.gardes import Gardes
from cime.signaux import commandes

FIXTURES = Path(__file__).parent / "fixtures"
MENU = next((FIXTURES / "captures-autorisation").glob("1-*.ansi")).read_text()
SANS_MENU = "$ \n"
T = datetime(2026, 10, 9, 13, 0, tzinfo=timezone.utc)
PREFIXE = "cc-essai"
PORT = 8767
DEMANDE = "d-0001"


def asynchrone(f):
    @functools.wraps(f)
    def enveloppe(*a, **k):
        asyncio.run(f(*a, **k))

    return enveloppe


class FauxTmux:
    """Une session dont l'écran montre le menu jusqu'à la première touche tapée."""

    def __init__(self, ecran=MENU):
        self.ecran, self.appels = ecran, []

    def __call__(self, gardes, argv, **kw):
        gardes.autoriser_commande(argv)             # la liste blanche reste en vigueur
        self.appels.append((list(argv), kw.get("env") or {}))
        if argv[0] == "tmux" and argv[1] == "capture-pane":
            return subprocess.CompletedProcess(argv, 0, self.ecran, "")
        if argv[0] == "tmux" and argv[1] == "send-keys":
            self.ecran = SANS_MENU
        return subprocess.CompletedProcess(argv, 0, "", "")

    def touches(self):
        return [a[-1] for a, _ in self.appels if a[0] == "tmux" and a[1] == "send-keys"]

    def commandes_cime(self):
        return [a for a, _ in self.appels if a[0] != "tmux"]


@pytest.fixture
def tmux(monkeypatch):
    faux = FauxTmux()
    monkeypatch.setattr(Gardes, "executer", lambda self, argv, **kw: faux(self, argv, **kw))
    monkeypatch.setattr(actions_autorisation, "ATTENTE_INITIALE_S", 0)
    monkeypatch.setattr(actions_autorisation, "ATTENTE_ENTRE_S", 0)
    return faux


@pytest.fixture
def projet(tmp_path, monkeypatch):
    (tmp_path / ".orga" / "teams" / "x").mkdir(parents=True)
    (tmp_path / ".orga" / "projet.toml").write_text(
        'nom = "Essai"\nprefixe = "cc-essai"\nbranche_reference = "main"\n'
        'branche_equipe = "equipe/{equipe}"\nworktree_equipe = "../{depot}-{equipe}"\n'
        'equipes_speciales = ["assistant"]\nmodele_assistant = "m"\nmodele_coordinateur = "m"\n')
    registre.ouvrir(tmp_path).close()
    monkeypatch.setenv("CIME_PROJET", str(tmp_path))
    monkeypatch.delenv("CLAUDECODE", raising=False)
    return tmp_path


@pytest.fixture
def contexte(projet):
    deps = Dependances(instantane=lambda p: {}, horloge=lambda: T, intervalle_s=60, prefixe=PREFIXE)
    app = creer_app(projet, deps, PORT)
    ctx = app.state.contexte
    ctx.app = app
    ctx.rafraichisseur.instantane = {"attentes_utilisateur": [], "agents": []}
    return ctx


def lignes(projet, requete, params=()):
    with closing(sqlite3.connect(projet / ".orga" / "etat" / "registre.sqlite")) as c:
        return c.execute(requete, params).fetchall()


def journal(projet):
    return lignes(projet, "SELECT auteur, action, cible, resultat FROM journal ORDER BY id")


def signalement_autorisation(projet, a="assistant", classe="libre"):
    """Le signalement du hook (la classe est dans le `corps`). Par défaut une
    demande `libre` adressée à l'Assistant, que l'Assistant peut accorder."""
    conn = registre.ouvrir(projet)
    try:
        corps = None if classe is None else json.dumps(
            {"outil": "Bash", "cible": "touch a", "classe": classe, "theme": "projet"})
        return commandes.inscrire(conn, de="cime", a=a, nature="signalement",
                                  resume="worker-x demande l'autorisation d'utiliser Bash",
                                  objet=f"autorisation:{DEMANDE}", corps=corps)
    finally:
        conn.close()


def donner(monkeypatch, projet, agent, *argv):
    monkeypatch.setenv("CIME_AGENT", agent)
    return cli.main(list(argv))


def preparer_demande(contexte):
    actions_autorisation.registre_pour(contexte).enregistrer(
        DEMANDE, "worker-x", f"{PREFIXE}-worker-x", "Bash", {"command": "touch a"}, None)


# --- exécution des accords d'autorisation -------------------------------------------------

@asynchrone
async def test_accord_de_l_assistant_tape_1_une_seule_fois_et_se_clot(projet, contexte, tmux, monkeypatch):
    preparer_demande(contexte)
    s = signalement_autorisation(projet)
    assert donner(monkeypatch, projet, "assistant", "accorder", str(s)) == 0
    executeur = contexte._executeur_accords
    assert await executeur.passer() == 1
    assert tmux.touches() == ["1"]
    assert journal(projet) == [("assistant", "autoriser", f"perm-{DEMANDE}", "ok")]
    assert lignes(projet, "SELECT etat, auteur FROM transitions WHERE message_id = 2 ORDER BY id") == [
        ("inscrit", "assistant"), ("clos", "cime")]
    assert await executeur.passer() == 0           # rien de nouveau : une seule touche
    assert tmux.touches() == ["1"]


@asynchrone
@pytest.mark.parametrize("actif", [False, True])
async def test_le_journal_porte_la_classe_et_le_mode(projet, contexte, tmux, monkeypatch, actif):
    """La ligne `journal` d'une autorisation exécutée porte `classe` et `mode_autonome`."""
    from cime.fondation import fusions_auto
    monkeypatch.setattr(fusions_auto, "etat_courant", lambda p: {"active": actif, "suspendue": False})
    preparer_demande(contexte)
    s = signalement_autorisation(projet, classe="autonome")
    assert donner(monkeypatch, projet, "assistant", "accorder", str(s)) == (0 if actif else 2)
    if not actif:
        assert donner(monkeypatch, projet, "utilisateur", "accorder", str(s)) == 0
    await contexte._executeur_accords.passer()
    [(details,)] = lignes(projet, "SELECT details FROM journal")
    d = json.loads(details)
    assert d["classe"] == "autonome" and d["mode_autonome"] is actif


@asynchrone
async def test_le_journal_sans_classe_porte_null(projet, contexte, tmux, monkeypatch):
    preparer_demande(contexte)
    s = signalement_autorisation(projet, a="utilisateur", classe=None)
    assert donner(monkeypatch, projet, "utilisateur", "accorder", str(s)) == 0
    await contexte._executeur_accords.passer()
    [(details,)] = lignes(projet, "SELECT details FROM journal")
    d = json.loads(details)
    assert d["classe"] is None and d["mode_autonome"] is False


@asynchrone
async def test_un_accord_deja_pris_en_compte_n_envoie_rien_de_plus(projet, contexte, tmux, monkeypatch):
    preparer_demande(contexte)
    s = signalement_autorisation(projet)
    donner(monkeypatch, projet, "assistant", "accorder", str(s))
    await contexte._executeur_accords.passer()
    neuf = actions_autorisation.ExecuteurAccords(contexte)   # hôte redémarré : mémoire vide
    assert await neuf.passer() == 0 and tmux.touches() == ["1"]


@asynchrone
async def test_ecran_sans_menu_rien_n_est_envoye_et_le_journal_le_dit(projet, contexte, tmux, monkeypatch):
    tmux.ecran = SANS_MENU
    preparer_demande(contexte)
    s = signalement_autorisation(projet)
    donner(monkeypatch, projet, "assistant", "accorder", str(s))
    await contexte._executeur_accords.passer()
    assert tmux.touches() == []
    assert journal(projet) == [("assistant", "autoriser", f"perm-{DEMANDE}", "refuse")]
    [(details,)] = lignes(projet, "SELECT details FROM journal")
    assert "aucune demande affichée" in json.loads(details)["raison"]
    assert lignes(projet, "SELECT etat FROM transitions WHERE message_id = 2 ORDER BY id")[-1] == ("clos",)


@asynchrone
async def test_refus_de_l_utilisateur_sur_une_copie_est_refuse_et_ne_tape_rien(projet, contexte, tmux, monkeypatch):
    """La copie d'une demande adressée à l'utilisateur n'ouvre aucune obligation :
    son refus est refusé, et rien ne part au terminal."""
    preparer_demande(contexte)
    s = signalement_autorisation(projet, a="utilisateur")
    assert donner(monkeypatch, projet, "utilisateur", "refuser", str(s), "trop large") == 2
    await contexte._executeur_accords.passer()
    assert tmux.touches() == []
    assert journal(projet) == []


@asynchrone
async def test_refus_de_l_assistant_tape_escape_sans_se_prevenir_lui_meme(projet, contexte, tmux, monkeypatch):
    preparer_demande(contexte)
    s = signalement_autorisation(projet)
    donner(monkeypatch, projet, "assistant", "refuser", str(s), "non")
    await contexte._executeur_accords.passer()
    assert tmux.touches() == ["Escape"] and tmux.commandes_cime() == []
    assert journal(projet) == [("assistant", "refuser", f"perm-{DEMANDE}", "ok")]


@asynchrone
async def test_la_decision_ne_donne_aucune_obligation_a_la_copie_de_l_utilisateur(projet, contexte, tmux, monkeypatch):
    """La copie adressée à l'utilisateur n'a pas d'obligation, et la décision de l'Assistant n'en
    ajoute pas. Sa fermeture relève de `signaux/signalements_utilisateur.py` (cause ou plafond de 2 h)."""
    preparer_demande(contexte)
    copie_assistant = signalement_autorisation(projet)
    copie_utilisateur = signalement_autorisation(projet, a="utilisateur")
    donner(monkeypatch, projet, "assistant", "accorder", str(copie_assistant))
    await contexte._executeur_accords.passer()
    assert lignes(projet, "SELECT count(*) FROM obligations WHERE message_id = ?", (copie_utilisateur,)) == [(0,)]


# --- « Accorder la fusion » / « Accorder le chantier » -------------------------------------

def decision(projet, objet, a="utilisateur", nature="decision_utilisateur"):
    conn = registre.ouvrir(projet)
    try:
        return commandes.inscrire(conn, de="assistant", a=a, nature=nature, resume="Fusionner ?", objet=objet)
    finally:
        conn.close()


def attente(ident, objet, nature="decision"):
    return {"id": f"msg-{ident}", "message_id": ident, "objet": objet, "nature": nature, "titre": "t",
            "agent": "assistant", "depuis": "x"}


def client(contexte, *attentes):
    contexte.rafraichisseur.instantane = {"attentes_utilisateur": list(attentes), "agents": []}
    return TestClient(contexte.app, base_url=f"http://127.0.0.1:{PORT}")


@pytest.mark.parametrize("objet", ["fusion:signaux:abc1234", "chantier:signaux:4"])
def test_accorder_la_fusion_lance_cime_accorder_en_tant_qu_utilisateur(projet, contexte, tmux, objet):
    ident = decision(projet, objet)
    c = client(contexte, attente(ident, objet))
    r = c.post("/api/actions/accorder", json={"attente_id": f"msg-{ident}"}).json()
    assert r["resultat"] == "ok" and objet in r["message"]
    [(argv, env)] = [(a, e) for a, e in tmux.appels]
    assert argv[-2:] == ["accorder", str(ident)] and env["CIME_AGENT"] == "utilisateur"
    assert not any("git" in a for a, _ in tmux.appels)           # l'hôte ne lance jamais git
    assert journal(projet) == [("utilisateur", "accorder", f"msg-{ident}", "ok")]


def test_refuser_la_fusion_passe_le_motif(projet, contexte, tmux):
    ident = decision(projet, "fusion:signaux:abc1234")
    c = client(contexte, attente(ident, "fusion:signaux:abc1234"))
    r = c.post("/api/actions/refuser", json={"attente_id": f"msg-{ident}", "motif": "pas avant demain"}).json()
    assert r["resultat"] == "ok"
    assert tmux.appels[0][0][-3:] == ["refuser", str(ident), "pas avant demain"]
    assert journal(projet) == [("utilisateur", "refuser", f"msg-{ident}", "ok")]


def test_refuser_sans_motif_ou_avec_motif_en_option_est_refuse(projet, contexte, tmux):
    ident = decision(projet, "fusion:signaux:abc1234")
    c = client(contexte, attente(ident, "fusion:signaux:abc1234"))
    for motif in (None, "  ", "-x", "m" * 161):
        r = c.post("/api/actions/refuser", json={"attente_id": f"msg-{ident}", "motif": motif}).json()
        assert r["resultat"] == "refuse"
    assert tmux.appels == []


def test_garde_seules_les_decisions_de_fusion_ou_de_chantier_ouvertes_pour_utilisateur(projet, contexte, tmux):
    autre = decision(projet, "port")                                  # une décision ordinaire
    rapport = decision(projet, "fusion:x:abc", nature="rapport_utilisateur")   # pas une décision
    pas_a_utilisateur = decision(projet, "fusion:x:abc", a="coord-x")      # pas adressée à l'utilisateur
    close = decision(projet, "fusion:x:def")
    conn = registre.ouvrir(projet)
    conn.execute("UPDATE obligations SET etat = 'satisfaite' WHERE message_id = ?", (close,))
    conn.commit()
    conn.close()
    c = client(contexte,
               attente(autre, "port"), attente(rapport, "fusion:x:abc", "rapport"),
               attente(pas_a_utilisateur, "fusion:x:abc"), attente(close, "fusion:x:def"))
    for ident in (autre, rapport, pas_a_utilisateur, close, 999):
        r = c.post("/api/actions/accorder", json={"attente_id": f"msg-{ident}"}).json()
        assert r["resultat"] == "refuse", (ident, r)
    for mauvais in ("perm-d1", "abc", None):
        assert c.post("/api/actions/accorder", json={"attente_id": mauvais}).json()["resultat"] == "refuse"
    assert tmux.appels == []                                          # rien n'a été lancé


def test_accorder_deux_fois_ne_lance_qu_une_commande(projet, contexte, tmux, monkeypatch):
    ident = decision(projet, "fusion:signaux:abc1234")
    c = client(contexte, attente(ident, "fusion:signaux:abc1234"))
    assert c.post("/api/actions/accorder", json={"attente_id": f"msg-{ident}"}).json()["resultat"] == "ok"
    assert c.post("/api/actions/accorder", json={"attente_id": f"msg-{ident}"}).json() == {
        "resultat": "refuse", "message": "déjà accordé"}
    assert len(tmux.appels) == 1


def test_la_commande_cime_echoue_l_erreur_remonte(projet, contexte, monkeypatch):
    def echec(self, argv, **kw):
        self.autoriser_commande(argv)
        return subprocess.CompletedProcess(argv, 2, "", "le message n'a plus d'obligation ouverte")
    monkeypatch.setattr(Gardes, "executer", echec)
    ident = decision(projet, "fusion:signaux:abc1234")
    c = client(contexte, attente(ident, "fusion:signaux:abc1234"))
    r = c.post("/api/actions/accorder", json={"attente_id": f"msg-{ident}"}).json()
    assert r["resultat"] == "erreur" and "obligation ouverte" in r["message"]
    assert journal(projet)[0][3].startswith("erreur")
