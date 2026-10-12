"""Routes de lecture : journal, terminal d'un agent, fichier de l'organisation."""
import copy
import uuid
import json
import subprocess
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from cime.hote import creer_app
from cime.hote.dependances import Dependances
from cime.hote.gardes import Gardes
from conftest import SOCKET_ESSAI, tmux_essai

FIX = Path(__file__).parent / "fixtures"
PORT = 8765
PREFIXE = f"cc-essai-{uuid.uuid4().hex[:6]}"  # unique par exécution
SESSION = f"{PREFIXE}-t4"


def instantane(session):
    inst = copy.deepcopy(json.loads((FIX / "instantane-exemple.json").read_text()))
    inst["projet"]["prefixe"] = PREFIXE
    inst["agents"] = [
        {"id": "essai", "session_tmux": session},
        {"id": "sans-session", "session_tmux": None},
    ]
    return inst


def client(projet, inst):
    d = Dependances(instantane=lambda p: inst, prefixe=PREFIXE, intervalle_s=0.05,
                    tmux_socket=SOCKET_ESSAI)
    app = creer_app(projet, d, PORT)
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}")


def attendre_instantane(c):
    fin = time.monotonic() + 3
    while time.monotonic() < fin:
        if c.app.state.contexte.rafraichisseur.instantane is not None:
            return
        time.sleep(0.01)
    raise AssertionError("pas d'instantané")


@pytest.fixture
def session_essai():
    tmux_essai("kill-session", "-t", SESSION)
    assert tmux_essai("new-session", "-d", "-s", SESSION, "printf 'bonjour\\n'; sleep 30").returncode == 0
    try:
        time.sleep(0.5)
        yield SESSION
    finally:
        tmux_essai("kill-session", "-t", SESSION)


@pytest.mark.tmux_reel
def test_terminal_reel_sans_send_keys(registre_vide, session_essai, monkeypatch):
    appels = []
    origine = Gardes.aexecuter

    async def espion(self, argv, **kw):
        appels.append(list(argv))
        return await origine(self, argv, **kw)

    monkeypatch.setattr(Gardes, "aexecuter", espion)
    with client(registre_vide, instantane(session_essai)) as c:
        attendre_instantane(c)
        r = c.get("/api/agents/essai/terminal")
    assert r.status_code == 200
    j = r.json()
    assert "bonjour" in j["texte"]
    assert j["capture_a"].endswith("Z") and len(j["capture_a"]) == 24
    assert appels == [["tmux", "capture-pane", "-p", "-J", "-S", "-200", "-t", SESSION]]
    assert not any("send-keys" in a for a in appels)


def test_terminal_404(registre_vide):
    with client(registre_vide, instantane(f"{PREFIXE}-absente")) as c:
        attendre_instantane(c)
        assert c.get("/api/agents/inconnu/terminal").status_code == 404
        assert c.get("/api/agents/sans-session/terminal").status_code == 404
        r = c.get("/api/agents/essai/terminal")
    assert r.status_code == 404 and r.json() == {"erreur": "session absente"}


def test_terminal_agents_null(registre_vide):
    inst = instantane(f"{PREFIXE}-x")
    inst["agents"] = None
    with client(registre_vide, inst) as c:
        attendre_instantane(c)
        assert c.get("/api/agents/essai/terminal").status_code == 404


def test_terminal_hors_prefixe_403(registre_vide):
    with client(registre_vide, instantane("autre-x")) as c:
        attendre_instantane(c)
        assert c.get("/api/agents/essai/terminal").status_code == 403


# -- fichier ---------------------------------------------------------------
@pytest.fixture
def orga(registre_vide):
    o = registre_vide / ".orga"
    (o / "messages").mkdir()
    (o / "messages" / "a.md").write_text("héllo\n", encoding="utf-8")
    (o / ".env").write_text("SECRET=1")
    (o / "gros.txt").write_bytes(b"a" * (1024 * 1024 + 1))
    (o / "limite.txt").write_bytes(b"a" * (1024 * 1024))
    (o / "bin.dat").write_bytes(b"\xff\xfe\x00\x80")
    dehors = registre_vide.parent / "dehors-t4.txt"
    dehors.write_text("hors orga")
    (o / "lien.txt").symlink_to(dehors)
    return registre_vide


def get(projet, chemin):
    with client(projet, instantane(f"{PREFIXE}-x")) as c:
        return c.get("/api/fichier", params={"chemin": chemin})


def test_fichier_ok(orga):
    for chemin in ("messages/a.md", ".orga/messages/a.md"):
        r = get(orga, chemin)
        assert r.status_code == 200 and r.text == "héllo\n"
        assert r.headers["content-type"] == "text/plain; charset=utf-8"
    assert get(orga, "limite.txt").status_code == 200


@pytest.mark.parametrize(
    "chemin", ["../x", "messages/../../x", "/etc/passwd", "lien.txt", ".env", ""]
)
def test_fichier_interdit(orga, chemin):
    assert get(orga, chemin).status_code == 403


def test_fichier_absent_gros_binaire(orga):
    assert get(orga, "nexiste-pas.md").status_code == 404
    assert get(orga, "gros.txt").status_code == 413
    assert get(orga, "bin.dat").status_code == 415
