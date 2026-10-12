"""Socle de l'hôte : état et flux SSE, sécurité Host/Origin, port publié, instantané servi tel quel."""
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient

from cime.hote import creer_app, servir
from cime.hote.dependances import Dependances

FIX = Path(__file__).parent / "fixtures"
EXEMPLE = json.loads((FIX / "instantane-exemple.json").read_text())
ABSENTES = json.loads((FIX / "instantane-sources-absentes.json").read_text())
PORT = 8765
HOTE = {"Host": f"127.0.0.1:{PORT}"}


def deps(inst=EXEMPLE, **kw):
    kw.setdefault("intervalle_s", 0.05)
    return Dependances(instantane=lambda p: inst, **kw)


def client(d, registre_vide):
    return TestClient(creer_app(registre_vide, d, PORT), base_url=f"http://127.0.0.1:{PORT}")


def attendre(cond, delai=3.0):
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if cond():
            return True
        time.sleep(0.01)
    return False


import contextlib


@contextlib.contextmanager
def serveur_reel(registre_vide, d):
    arret = threading.Event()
    t = threading.Thread(target=servir, args=(registre_vide, 0, d, arret), daemon=True)
    t.start()
    fichier = registre_vide / ".orga" / "etat" / "hote.port"
    assert attendre(fichier.exists)
    try:
        yield int(fichier.read_text())
    finally:
        arret.set()
        t.join(5)


def lire_flux(port, arret_si, max_lignes=60, delai=5.0):
    """Lit au plus max_lignes lignes du flux, jamais plus de `delai` secondes."""
    lignes = []
    fin = time.monotonic() + delai
    with httpx.stream("GET", f"http://127.0.0.1:{port}/api/flux", timeout=delai) as r:
        for l in r.iter_lines():
            lignes.append(l)
            if arret_si(lignes) or len(lignes) >= max_lignes or time.monotonic() > fin:
                break
    return lignes


def test_etat_age_ms(registre_vide):
    t = datetime(2026, 10, 7, 13, 4, 11, 123000, tzinfo=timezone.utc) + timedelta(milliseconds=1234)
    with client(deps(horloge=lambda: t), registre_vide) as c:
        assert attendre(lambda: c.get("/api/etat").status_code == 200)
        r = c.get("/api/etat").json()
    assert r["age_ms"] == 1234
    assert r["agents"] == EXEMPLE["agents"]


def test_etat_503_avant_premier(registre_vide):
    lance = threading.Event()

    def lent(p):
        lance.wait(2)
        return EXEMPLE

    with client(Dependances(instantane=lent, intervalle_s=0.05), registre_vide) as c:
        r = c.get("/api/etat")
        assert r.status_code == 503 and r.json() == {"erreur": "aucun instantané encore"}
        lance.set()


def test_sources_absentes(registre_vide):
    with client(deps(ABSENTES), registre_vide) as c:
        assert attendre(lambda: c.get("/api/etat").status_code == 200)
        r = c.get("/api/etat").json()
        assert r["fil"] is None and r["alarmes"] is None and r["attentes_utilisateur"] is None
    with serveur_reel(registre_vide, deps(ABSENTES)) as port:
        lignes = lire_flux(port, lambda l: len(l) >= 2)
    assert lignes[0] == "event: etat"
    assert json.loads(lignes[1][6:])["fil"] is None


def test_rafraichissement_et_erreur(registre_vide):
    n = {"v": 0}

    def inst(p):
        n["v"] += 1
        if n["v"] > 3:
            raise RuntimeError("boum")
        return EXEMPLE

    with client(Dependances(instantane=inst, intervalle_s=0.05), registre_vide) as c:
        assert attendre(lambda: n["v"] >= 6)
        r = c.get("/api/etat").json()
    assert r["agents"] == EXEMPLE["agents"]
    assert "boum" in r["erreur_rafraichissement"]


def test_plusieurs_appels(registre_vide):
    n = {"v": 0}

    def inst(p):
        n["v"] += 1
        return EXEMPLE

    with client(Dependances(instantane=inst, intervalle_s=0.05), registre_vide):
        time.sleep(0.3)
    assert n["v"] >= 3


def test_flux_etat_puis_etat_puis_vivant(registre_vide):
    with serveur_reel(registre_vide, deps(vivant_s=0.1, intervalle_s=0.3)) as port:
        def fini(l):
            ev = [x for x in l if x.startswith("event:")]
            return ev.count("event: etat") >= 2 and "event: vivant" in ev

        lignes = lire_flux(port, fini)
    ev = [x[7:] for x in lignes if x.startswith("event:")]
    assert ev[0] == "etat" and ev.count("etat") >= 2 and "vivant" in ev



def test_vivant_a_cadence_fixe_meme_si_etat_continu(registre_vide):
    # `vivant` à cadence fixe, même quand des `etat` arrivent sans cesse
    with serveur_reel(registre_vide, deps(vivant_s=0.3, intervalle_s=0.05)) as port:
        lignes = lire_flux(port, lambda l: l.count("event: vivant") >= 3, max_lignes=10_000, delai=3.0)
    ev = [x[7:] for x in lignes if x.startswith("event:")]
    assert ev.count("etat") >= 10 and ev.count("vivant") >= 3

ROUTES = [("POST", f"/api/actions/{a}") for a in ("autoriser", "refuser", "cloturer", "trancher", "deposer", "lu")] + [
    ("POST", "/api/permissions"),
    ("GET", "/api/agents/x/terminal"),
    ("GET", "/api/fichier"),
]


def test_securite(registre_vide):
    with client(deps(), registre_vide) as c:
        assert c.get("/api/etat", headers={"Host": "evil.com"}).status_code == 403
        for m, u in ROUTES:
            if m == "POST":  # une page web étrangère ne peut déclencher aucune action
                assert c.post(u, json={}, headers={"Origin": "http://evil.com"}).status_code == 403, u
        # sans Origin (hook local) ou avec la bonne origine : le middleware laisse passer
        assert c.post("/api/actions/lu", json={}).status_code != 403
        assert c.post("/api/actions/lu", json={}, headers={"Origin": f"http://localhost:{PORT}"}).status_code != 403


def test_aucune_route_ne_repond_501(registre_vide):
    """Toutes les routes sont implémentées (aucune ne répond 501)."""
    assert len(ROUTES) == 9
    with client(deps(), registre_vide) as c:
        for m, u in ROUTES:
            assert c.request(m, u).status_code != 501, (m, u)


def test_page_absente_et_static(registre_vide):
    with client(deps(), registre_vide) as c:
        r = c.get("/")
        assert r.status_code == 200 and "pas encore installée" in r.text or "<html" in r.text.lower()
        assert c.get("/static/inexistant.js").status_code == 404


def test_servir(registre_vide):
    """Port 0 : le système choisit (pas de course entre exécutions parallèles), le vrai port est publié."""
    fichier = registre_vide / ".orga" / "etat" / "hote.port"
    arret = threading.Event()
    t = threading.Thread(target=servir, args=(registre_vide, 0, deps(), arret), daemon=True)
    t.start()
    try:
        assert attendre(fichier.exists)
        port = int(fichier.read_text())
        assert port > 0
        assert attendre(lambda: httpx.get(f"http://127.0.0.1:{port}/api/etat").status_code == 200)
        with pytest.raises(SystemExit, match=f"déjà.*{port}"):
            servir(registre_vide, 0, deps())
        assert fichier.exists()  # le refus n'a pas effacé le fichier du premier
    finally:
        arret.set()
        t.join(5)
    assert not fichier.exists()


def test_servir_fichier_perime(registre_vide):
    fichier = registre_vide / ".orga" / "etat" / "hote.port"
    fichier.parent.mkdir(parents=True, exist_ok=True)
    fichier.write_text("1")  # port 1 : personne n'y répond, le fichier est périmé
    arret = threading.Event()
    t = threading.Thread(target=servir, args=(registre_vide, 0, deps(), arret), daemon=True)
    t.start()
    try:
        assert attendre(lambda: fichier.exists() and fichier.read_text() not in ("", "1"))
    finally:
        arret.set()
        t.join(5)


def test_instantane_complet():
    """`complet=True` si l'observation le connaît, sinon appel inchangé."""
    from cime.hote.serveur import instantane_complet
    appels = []

    def recent(projet, maintenant=None, complet=False):
        appels.append(complet)
        return {}

    def ancien(projet, maintenant=None):
        appels.append("ancien")
        return {}

    instantane_complet(recent)(Path("."))
    instantane_complet(ancien)(Path("."))
    assert appels == [True, "ancien"]


@pytest.mark.parametrize("valeur, attendu", [("0", False), (None, True), ("1", True)])
def test_cime_notifications_0_coupe_osascript(registre_vide, monkeypatch, valeur, attendu):
    import cime.hote.serveur as serveur

    construits = []

    class FauxNotifieur:  # jamais le vrai osascript dans les tests
        def __init__(self, gardes):
            construits.append(gardes)

        async def notifier(self, titre, texte):
            pass

    monkeypatch.setattr(serveur, "NotifieurMac", FauxNotifieur)
    d = deps()
    contexte = creer_app(registre_vide, d, PORT).state.contexte
    monkeypatch.setattr(contexte, "gardes", lambda: "gardes")  # projet.toml minimal du test
    environ = {} if valeur is None else {"CIME_NOTIFICATIONS": valeur}
    avant = len(contexte.rafraichisseur._observateurs)
    assert serveur.brancher_notifications_mac(contexte, d, environ) is attendu
    assert len(construits) == int(attendu)
    assert len(contexte.rafraichisseur._observateurs) == avant + int(attendu)


def _instantane_etendu():
    """Exemple canonique + des champs que l'exemple ne porte pas (fil étendu, questions sans réponse, alarmes)."""
    inst = json.loads(json.dumps(EXEMPLE))
    inst["fil"].append({
        "id": "fic-alpha-2026-10-08-0400", "de": "coord-alpha", "a": "assistant", "nature": "question",
        "resume": "Question essai : faut-il X ?", "fichier": ".orga/teams/alpha/conversations/pour-assistant-2026-10-08-0400.md",
        "en_attente": True, "source": "structure", "le": "2026-10-08T03:20:00Z",
    })
    inst["alarmes"] += [
        {"id": "question_sans_reponse:coord-alpha:fic-alpha-2026-10-08-0400", "type": "question_sans_reponse",
         "gravite": "a_voir", "agents": ["coord-alpha"], "depuis": "2026-10-08T03:20:00Z",
         "mesure": "question sans réponse depuis 40 min", "quoi_faire": "répondre"},
        {"id": "fige:worker-alpha-t1:1759893600", "type": "fige", "gravite": "grave", "agents": ["worker-alpha-t1"],
         "depuis": "2026-10-08T03:20:00Z", "mesure": "aucun signe depuis 50 min", "quoi_faire": "regarder"},
    ]
    for i, e in enumerate(inst["equipes"]):
        e["en_avance_sur_base"] = None if i == 0 else i
    return inst


def test_champs_etendus_servis_tel_quel(registre_vide):
    # `fil[].non_lu` et champs étendus : l'hôte ne filtre ni ne réécrit rien ; il ajoute seulement age_ms
    inst = _instantane_etendu()
    assert [e["id"] for e in inst["fil"] if e.get("non_lu")] == ["msg-50"]  # la fixture porte bien non_lu
    with serveur_reel(registre_vide, deps(inst, vivant_s=5)) as port:
        r = httpx.get(f"http://127.0.0.1:{port}/api/etat").json()
        lignes = lire_flux(port, lambda l: any(x.startswith("data:") for x in l))
    assert {k: v for k, v in r.items() if k != "age_ms"} == inst
    flux = json.loads(next(x for x in lignes if x.startswith("data:"))[5:])
    assert {k: v for k, v in flux.items() if k != "age_ms"} == inst
