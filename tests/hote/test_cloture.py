"""Clôture d'une équipe par l'utilisateur : validation de l'Assistant, marque `CLOTUREE`, sessions fermées, journal."""
import json
import sqlite3
import uuid
import subprocess
import sys
from contextlib import closing
from datetime import datetime, timezone

import pytest
from starlette.testclient import TestClient

from cime.hote import creer_app
from cime.hote.dependances import Dependances
from cime.hote.gardes import Gardes
from conftest import SOCKET_ESSAI, tmux_essai

T = datetime(2026, 10, 7, 13, 4, 11, 123000, tzinfo=timezone.utc)
PORT = 8766
HOTE = {"host": f"127.0.0.1:{PORT}"}
P = f"cc-essai-{uuid.uuid4().hex[:6]}"  # unique par exécution


@pytest.fixture(autouse=True)
def espion(monkeypatch):
    vus = []
    orig = Gardes.aexecuter

    async def espionne(self, argv, **kw):
        vus.append(list(argv))
        return await orig(self, argv, **kw)

    monkeypatch.setattr(Gardes, "aexecuter", espionne)
    yield vus
    assert not [a for a in vus if a[0] == "git"]


def equipe(projet, nom):
    d = projet / ".orga" / "teams" / nom
    d.mkdir(parents=True, exist_ok=True)
    (d / "mandate.md").write_text("# mandat\n")
    return d


def msg(projet, de, a, nature, equipe_=None, rep=None):
    with closing(sqlite3.connect(projet / ".orga" / "etat" / "registre.sqlite")) as c:
        with c:
            cur = c.execute(
                "INSERT INTO messages(horodatage,de,a,nature,resume,en_reponse_a,equipe) VALUES('t',?,?,?,'r',?,?)",
                (de, a, nature, rep, equipe_),
            )
        return cur.lastrowid


def valider(projet, nom="eq"):
    d = msg(projet, f"coord-{nom}", "assistant", "demande_cloture")
    r = msg(projet, "assistant", "utilisateur", "rapport_utilisateur", nom, d)
    return d, r


def client(projet):
    deps = Dependances(instantane=lambda p: {}, horloge=lambda: T, prefixe=P, tmux_socket=SOCKET_ESSAI)
    return TestClient(creer_app(projet, deps, PORT), headers=HOTE)


def post(c, **corps):
    r = c.post("/api/actions/cloturer", json=corps, headers={"origin": f"http://127.0.0.1:{PORT}"})
    return r.json()


def journal(projet):
    with closing(sqlite3.connect(projet / ".orga" / "etat" / "registre.sqlite")) as c:
        return c.execute("SELECT auteur, action, cible, resultat FROM journal ORDER BY id").fetchall()


def sessions():
    r = tmux_essai("list-sessions", "-F", "#{session_name}")
    return {s for s in r.stdout.split() if s.startswith(P + "-")}


@pytest.mark.parametrize(
    "corps,motif",
    [
        ({"equipe": "Eq", "confirmation": "Eq"}, "invalide"),
        ({"equipe": "../x", "confirmation": "../x"}, "invalide"),
        ({"equipe": "eq", "confirmation": "autre"}, "confirmation"),
        ({"equipe": "eq"}, "confirmation"),
        ({"equipe": "inconnue", "confirmation": "inconnue"}, "inconnue"),
        ({"equipe": "integration", "confirmation": "integration"}, "spéciale"),
    ],
)
def test_refus_formes(registre_vide, corps, motif):
    p = registre_vide
    equipe(p, "eq")
    equipe(p, "integration")
    valider(p, "integration")
    r = post(client(p), **corps)
    assert r["resultat"] == "refuse" and motif in r["message"]
    assert not list((p / ".orga" / "teams").glob("*/CLOTUREE"))
    assert journal(p)[-1][:2] == ("utilisateur", "cloturer") and journal(p)[-1][3] == "refuse"


def test_refus_registre(registre_vide):
    p = registre_vide
    equipe(p, "eq")
    equipe(p, "autre")
    c = client(p)
    assert "non validée" in post(c, equipe="eq", confirmation="eq")["message"]  # rien
    d = msg(p, "coord-eq", "assistant", "demande_cloture")  # demande sans rapport
    assert post(c, equipe="eq", confirmation="eq")["resultat"] == "refuse"
    d2 = msg(p, "coord-eq", "assistant", "demande_cloture")
    msg(p, "assistant", "utilisateur", "rapport_utilisateur", "eq", d + 1000)  # cite une autre demande
    assert post(c, equipe="eq", confirmation="eq")["resultat"] == "refuse"
    msg(p, "assistant", "utilisateur", "rapport_utilisateur", "autre", d2)  # mauvaise équipe
    assert post(c, equipe="eq", confirmation="eq")["resultat"] == "refuse"
    msg(p, "coord-autre", "assistant", "demande_cloture")
    msg(p, "assistant", "utilisateur", "rapport_utilisateur", "eq", d2 + 1)  # rapport vers la demande d'une autre équipe
    assert post(c, equipe="eq", confirmation="eq")["resultat"] == "refuse"
    assert not list((p / ".orga" / "teams").glob("*/CLOTUREE"))
    assert [j[3] for j in journal(p)] == ["refuse"] * 5


def test_deja_cloturee_et_registre_illisible(registre_vide):
    p = registre_vide
    d = equipe(p, "eq")
    valider(p)
    (d / "CLOTUREE").write_text("x")
    assert "déjà clôturée" in post(client(p), equipe="eq", confirmation="eq")["message"]
    (d / "CLOTUREE").unlink()
    with closing(sqlite3.connect(p / ".orga" / "etat" / "registre.sqlite")) as c:
        c.execute("DROP TABLE messages")
    r = post(client(p), equipe="eq", confirmation="eq")
    assert r["resultat"] == "erreur" and not (d / "CLOTUREE").exists()


@pytest.mark.tmux_reel
def test_cloture_reelle(registre_vide):
    if subprocess.run(["which", "tmux"], capture_output=True).returncode:
        pytest.skip("tmux absent")
    p = registre_vide
    d = equipe(p, "eq")
    equipe(p, "eq-x")
    dd, rr = valider(p)
    from cime.fondation.registre import ouvrir
    with closing(ouvrir(p)) as c:   # le rapport attend la lecture de l'utilisateur
        c.execute("INSERT INTO obligations (message_id, debiteur, attendu, etat) VALUES (?, 'utilisateur', 'lu', 'ouverte')", (rr,))
        c.commit()
    noms = [f"{P}-coord-eq", f"{P}-worker-eq-t1", f"{P}-worker-eq-x-t1", f"{P}-coord-autre"]
    try:
        for n in noms:
            assert tmux_essai("new-session", "-d", "-s", n, "sleep 120").returncode == 0
        r = post(client(p), equipe="eq", confirmation="eq")
        assert r["resultat"] == "ok", r
        assert sessions() == {noms[2], noms[3]}
        lignes = (d / "CLOTUREE").read_text().splitlines()
        assert lignes == [
            "auteur: utilisateur", "heure: 2026-10-07T13:04:11.123Z", f"demande: {dd}", f"rapport: {rr}",
        ]
        assert journal(p) == [("utilisateur", "cloturer", "equipe:eq", "ok")]
        with closing(sqlite3.connect(p / ".orga" / "etat" / "registre.sqlite")) as c:
            assert c.execute("SELECT etat FROM obligations WHERE message_id = ?", (rr,)).fetchone() == ("satisfaite",)
            assert c.execute("SELECT etat FROM transitions WHERE message_id = ? ORDER BY id DESC LIMIT 1",
                             (rr,)).fetchone() == ("clos",)
    finally:
        for n in noms:
            tmux_essai("kill-session", "-t", n)


def _lignes(p):
    with closing(sqlite3.connect(p / ".orga" / "etat" / "registre.sqlite")) as c:
        return c.execute("SELECT cible, details FROM journal ORDER BY id").fetchall()


def test_journal_cible_et_details(registre_vide):
    p = registre_vide
    equipe(p, "eq")
    post(client(p), equipe="eq", confirmation="autre")  # refusé avant la demande
    assert _lignes(p) == [("equipe:eq", '{"demande": null}')]
    d, _ = valider(p)
    assert post(client(p), equipe="eq", confirmation="eq")["resultat"] == "ok"
    assert _lignes(p)[-1] == ("equipe:eq", json.dumps({"demande": f"msg-{d}"}))
