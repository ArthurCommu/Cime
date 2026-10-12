"""« lu » sur un message du registre : `POST /api/actions/lu` `{"attente_id": "msg-<n>"}` clôt le
message (transition `clos`, auteur `utilisateur`, preuve `{"lu_par", "journal_id"}`). Les autres
`attente_id` gardent le chemin existant (journal seulement). Le registre est créé par la fondation."""
import asyncio
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

import httpx
import pytest
from starlette.testclient import TestClient

from cime.fondation import registre
from cime.hote import actions_reponses, creer_app
from cime.hote.dependances import Dependances
from cime.hote.journal import MSG_ABSENT

PORT = 8768
PREFIXE = "cc-essai"
T = datetime(2026, 10, 11, 9, 0, tzinfo=timezone.utc)
URL = f"http://127.0.0.1:{PORT}"


@pytest.fixture
def projet(tmp_path, monkeypatch):
    registre.ouvrir(tmp_path).close()  # schéma réel, par la fondation
    monkeypatch.setenv("CIME_PROJET", str(tmp_path))
    return tmp_path


@pytest.fixture
def env(projet):
    inst = {"attentes_utilisateur": [], "fil": []}
    deps = Dependances(instantane=lambda p: inst, horloge=lambda: T, intervalle_s=60, prefixe=PREFIXE)
    app = creer_app(projet, deps, PORT)
    app.state.contexte.rafraichisseur.instantane = inst
    return TestClient(app, base_url=URL), app


def message(projet, *, a="utilisateur", nature="reponse", objet=None, etats=("livre",), obligation=None):
    """Inscrit un message avec ses transitions (et une obligation éventuelle) ; renvoie son id."""
    conn = registre.ouvrir(projet)
    try:
        n = registre.inscrire_message(conn, de="assistant", a=a, nature=nature,
                                      resume="Un message pour l'utilisateur", objet=objet)
        for etat in etats:
            registre.inscrire_transition(conn, n, etat, "cime", {})
        if obligation is not None:
            conn.execute("INSERT INTO obligations (message_id, debiteur, attendu, etat)"
                         " VALUES (?, 'utilisateur', 'reponse', ?)", (n, obligation))
            conn.commit()
        return n
    finally:
        conn.close()


def lire(projet, requete, params=()):
    with closing(sqlite3.connect(projet / ".orga" / "etat" / "registre.sqlite")) as c:
        return c.execute(requete, params).fetchall()


def transitions(projet, n):
    return lire(projet, "SELECT etat, auteur, preuve FROM transitions WHERE message_id = ? ORDER BY id", (n,))


def journal_lu(projet):
    return lire(projet, "SELECT id, cible, resultat, details FROM journal WHERE action = 'lu' ORDER BY id")


def nombre_messages(projet):
    return lire(projet, "SELECT COUNT(*) FROM messages")[0][0]


def lu(c, attente):
    return c.post("/api/actions/lu", json={"attente_id": attente})


# --- chemin nouveau : msg-<n> ----------------------------------------------------------------

def test_lu_clot_le_message_avec_preuve_et_journal(env, projet):
    c, _ = env
    n = message(projet, etats=("inscrit", "livre"))
    avant = nombre_messages(projet)

    r = lu(c, f"msg-{n}").json()

    assert r == {"resultat": "ok", "message": "marqué lu"}
    ((ligne_id, cible, resultat, details),) = journal_lu(projet)
    assert (cible, resultat, json.loads(details)) == (f"msg-{n}", "ok", {"message": str(n)})
    etats = transitions(projet, n)
    assert [e[0] for e in etats] == ["inscrit", "livre", "clos"]
    etat, auteur, preuve = etats[-1]
    assert auteur == "utilisateur"
    assert json.loads(preuve) == {"lu_par": "utilisateur", "journal_id": ligne_id}
    # ne prévient personne : aucun message écrit
    assert nombre_messages(projet) == avant


def test_second_appel_refuse_deja_lu(env, projet):
    c, _ = env
    n = message(projet)
    assert lu(c, f"msg-{n}").json()["resultat"] == "ok"

    r = lu(c, f"msg-{n}").json()

    assert r == {"resultat": "refuse", "message": "déjà lu"}
    assert [e[0] for e in transitions(projet, n)] == ["livre", "clos"]  # une seule clôture
    assert [l[2] for l in journal_lu(projet)] == ["ok", "refuse"]


@pytest.mark.parametrize(
    "construire, motif",
    [
        (lambda p: message(p, a="assistant"), "n'est pas adressé à l'utilisateur"),
        (lambda p: message(p, nature="signalement", objet="autorisation:d-0001"), "demande d'autorisation"),
        (lambda p: message(p, obligation="ouverte"), "attend une décision ou une réponse"),
        (lambda p: message(p, etats=("inscrit",)), "pas encore livré (dernier état : inscrit)"),
        (lambda p: 999, "inexistant"),
    ],
    ids=["pas_a_utilisateur", "autorisation", "obligation_ouverte", "inscrit", "absent"],
)
def test_refus_sans_transition_avec_ligne_de_journal(env, projet, construire, motif):
    c, _ = env
    n = construire(projet)
    avant = transitions(projet, n)

    r = lu(c, f"msg-{n}").json()

    assert r["resultat"] == "refuse" and motif in r["message"]
    assert transitions(projet, n) == avant  # aucune transition écrite
    assert [(l[1], l[2]) for l in journal_lu(projet)] == [(f"msg-{n}", "refuse")]


@pytest.mark.parametrize("attente", ["msg-0", "msg-x", "msg-1; DROP TABLE messages", "msg-1234567890", "msg-01"])
def test_attente_mal_formee_refusee(env, projet, attente):
    c, _ = env
    n = message(projet)

    r = lu(c, attente).json()

    assert r["resultat"] == "refuse"
    assert transitions(projet, n) == [("livre", "cime", "{}")]
    assert [l[2] for l in journal_lu(projet)] == ["refuse"]


def test_numero_du_message_forme_stricte():
    assert actions_reponses._numero_lu_message("msg-12") == 12
    for mauvais in ("msg-0", "msg-01", "msg-x", "msg-", "msg-1 ", "msg-1\n", None, 12):
        assert actions_reponses._numero_lu_message(mauvais) is None


def test_deux_appels_simultanes_un_seul_ok(env, projet):
    _, app = env
    n = message(projet)

    async def deux():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=URL) as ac:
            return await asyncio.gather(
                ac.post("/api/actions/lu", json={"attente_id": f"msg-{n}"}),
                ac.post("/api/actions/lu", json={"attente_id": f"msg-{n}"}),
            )

    reponses = [r.json() for r in asyncio.run(deux())]

    assert sorted(r["resultat"] for r in reponses) == ["ok", "refuse"]
    assert [r["message"] for r in reponses if r["resultat"] == "refuse"] == ["déjà lu"]
    assert [e[0] for e in transitions(projet, n)].count("clos") == 1


def test_registre_absent_erreur_sans_creation(tmp_path, monkeypatch):
    monkeypatch.setenv("CIME_PROJET", str(tmp_path))
    deps = Dependances(instantane=lambda p: {}, horloge=lambda: T, intervalle_s=60, prefixe=PREFIXE)
    app = creer_app(tmp_path, deps, PORT)
    app.state.contexte.rafraichisseur.instantane = {"attentes_utilisateur": [], "fil": []}
    c = TestClient(app, base_url=URL)

    r = lu(c, "msg-1")

    assert r.status_code == 503 and r.json()["resultat"] == "erreur"
    assert not (tmp_path / ".orga").exists()  # ni registre, ni dossier créé


def test_marquer_lu_sans_registre_ne_cree_rien(tmp_path):
    assert actions_reponses._marquer_lu(tmp_path, 1, 1) == ("erreur", MSG_ABSENT)
    assert not (tmp_path / ".orga").exists()


# --- chemin existant : inchangé ---------------------------------------------------------------

def test_lu_sur_une_attente_rapport_ecrit_seulement_au_journal(env, projet):
    c, app = env
    # le message existe, livré à l'utilisateur, sans obligation : la voie msg-<n> l'aurait clos
    n = message(projet)
    app.state.contexte.rafraichisseur.instantane = {
        "attentes_utilisateur": [{"id": f"msg-{n}", "nature": "rapport"}], "fil": []}

    r = lu(c, f"msg-{n}").json()

    assert r["resultat"] == "ok" and "personne n'est prévenu" in r["message"]
    assert [(l[1], l[2]) for l in journal_lu(projet)] == [(f"msg-{n}", "ok")]
    assert transitions(projet, n) == [("livre", "cime", "{}")]  # aucune transition écrite
    assert nombre_messages(projet) == 1
