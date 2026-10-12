"""Route `/scene/` : sert les fichiers statiques de la scène, en lecture seule et sans CORS."""
from pathlib import Path

from starlette.testclient import TestClient

from cime.hote import creer_app, routes_lecture
from cime.hote.dependances import Dependances

PORT = 8765
SCENE_REELLE = Path(routes_lecture.__file__).resolve().parent.parent / "scene" / "static"


def deps():
    return Dependances(instantane=lambda p: None, intervalle_s=0.05)


def client(d, registre_vide):
    return TestClient(creer_app(registre_vide, d, PORT), base_url=f"http://127.0.0.1:{PORT}")


def test_scene_index(registre_vide):
    with client(deps(), registre_vide) as c:
        r = c.get("/scene/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert r.content == (SCENE_REELLE / "index.html").read_bytes()


def test_scene_fichier_js(registre_vide):
    with client(deps(), registre_vide) as c:
        r = c.get("/scene/app.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    assert r.content == (SCENE_REELLE / "app.js").read_bytes()


def test_scene_methodes_refusees(registre_vide):
    with client(deps(), registre_vide) as c:
        for chemin in ("/scene/", "/scene/app.js"):
            assert c.post(chemin).status_code == 405
            assert c.put(chemin).status_code == 405
            assert c.delete(chemin).status_code == 405
            assert c.patch(chemin).status_code == 405


def test_scene_absente_404(registre_vide, monkeypatch, tmp_path):
    monkeypatch.setattr(routes_lecture, "SCENE", tmp_path / "absent")
    with client(deps(), registre_vide) as c:
        r = c.get("/scene/")
    assert r.status_code == 404


def test_scene_sans_cors(registre_vide):
    with client(deps(), registre_vide) as c:
        for chemin in ("/scene/", "/scene/app.js"):
            r = c.get(chemin)
            assert not [k for k in r.headers if k.lower().startswith("access-control-")]
