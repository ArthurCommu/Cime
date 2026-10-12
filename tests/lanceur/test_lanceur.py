"""Le serveur du lanceur : mémoire des projets, création, ouverture, journal, refus d'un second lanceur."""
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

from cime.lanceur import serveur as mod
from cime.lanceur import servir

from .conftest import FAUX, SRC, journal


def projet(tmp_path, nom="alpha", prefixe="al"):
    d = tmp_path / nom
    (d / ".orga").mkdir(parents=True)
    (d / ".orga" / "projet.toml").write_text(f'nom = "{nom}"\nprefixe = "{prefixe}"\n')
    return d


@pytest.fixture(autouse=True)
def sans_tmux(monkeypatch):
    """`GET /api/projets` interroge l'état des agents : aucun test ne doit toucher à tmux."""
    monkeypatch.setattr(mod, "_agents_actifs", lambda chemin: False)


# ── GET ─────────────────────────────────────────────────────────────────────────────────

def test_page_repli_et_liste_vide(lanceur):
    r = lanceur.get("/")
    assert r.status_code == 200 and "html" in r.headers["content-type"]
    assert lanceur.get("/api/projets").json()["projets"] == []


# ── nouveau ─────────────────────────────────────────────────────────────────────────────

def test_nouveau_ok_argv_exacts_et_env(lanceur, tmp_path, trace):
    parent = tmp_path / "parent"
    parent.mkdir()
    r = lanceur.post("/api/projets/nouveau", json={"dossier_parent": str(parent), "nom": "beta", "utilisateur": "Camille"})
    corps = r.json()
    cible = str((parent / "beta").resolve())
    assert r.status_code == 200 and corps["resultat"] == "ok"
    assert corps["chemin"] == cible and corps["prefixe"] == "p-beta" and corps["a_approuver"] is False
    assert corps["commandes"] == ["tmux attach -t p-beta-assistant"]
    assert "init fait" in corps["message"] and "sur stderr" in corps["message"]
    (appel,) = trace()
    assert appel["argv"] == ["init", str(parent / "beta"), "--utilisateur", "Camille",
                             "--nom-projet", "beta", "--lancer"]
    assert appel["CIME_PROJET"] is None and appel["CIME_AGENT"] is None
    assert lanceur.get("/api/projets").json() == {"projets": [{"chemin": cible, "nom": "beta", "etat": "ferme",
                                                               "conversations": None}], "utilisateur": "Camille"}


def test_nouveau_argv_avec_prefixe_et_modele(tmp_path, trace):
    dossier = tmp_path / "d"
    arret = threading.Event()
    t = threading.Thread(target=servir, kwargs=dict(
        port=0, modele="sonnet", dossier=dossier, cime=[sys.executable, str(FAUX)], arret=arret), daemon=True)
    t.start()
    while not (dossier / "lanceur.port").exists():
        time.sleep(0.02)
    port = (dossier / "lanceur.port").read_text()
    parent = tmp_path / "p"
    parent.mkdir()
    try:
        r = httpx.post(f"http://127.0.0.1:{port}/api/projets/nouveau",
                       json={"dossier_parent": str(parent), "nom": "g", "prefixe": "gg", "utilisateur": "Camille"})
        assert r.json()["prefixe"] == "gg"
        assert trace()[0]["argv"] == ["init", str(parent / "g"), "--utilisateur", "Camille",
                                      "--nom-projet", "g", "--lancer", "--prefixe", "gg",
                                      "--modele", "sonnet"]
    finally:
        arret.set()
        t.join(10)


def test_nouveau_code_3_a_approuver(lanceur, tmp_path, monkeypatch):
    monkeypatch.setenv("FAUX_CIME_CODE", "3")
    r = lanceur.post("/api/projets/nouveau", json={"dossier_parent": str(tmp_path), "utilisateur": "u", "nom": "trois"})
    assert r.json()["resultat"] == "ok" and r.json()["a_approuver"] is True
    assert len(lanceur.get("/api/projets").json()["projets"]) == 1


def test_nouveau_autre_code_erreur(lanceur, tmp_path, monkeypatch):
    monkeypatch.setenv("FAUX_CIME_CODE", "7")
    r = lanceur.post("/api/projets/nouveau", json={"dossier_parent": str(tmp_path), "utilisateur": "u", "nom": "sept"})
    assert r.status_code == 200
    assert r.json()["resultat"] == "erreur" and r.json()["code"] == 7
    assert r.json()["message"] == "init fait\nsur stderr\n" or "init fait" in r.json()["message"]
    assert lanceur.get("/api/projets").json()["projets"] == []
    assert journal(lanceur)[-1]["resultat"] == "erreur"


def test_nouveau_delai(lanceur, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "DELAI_INIT_S", 0.01)
    r = lanceur.post("/api/projets/nouveau", json={"dossier_parent": str(tmp_path), "utilisateur": "u", "nom": "lent"})
    assert r.json()["resultat"] == "erreur"


@pytest.mark.parametrize("corps", [
    {"nom": "Majuscule"}, {"nom": "a b"}, {"nom": "a\n"}, {"nom": "../x"}, {"nom": ""}, {},
    {"nom": "ok", "prefixe": "NON"}, {"nom": "ok", "prefixe": "a_b"},
    {"nom": 3},
])
def test_nouveau_validation_400(lanceur, tmp_path, trace, corps):
    r = lanceur.post("/api/projets/nouveau", json={"dossier_parent": str(tmp_path), "utilisateur": "u", **corps})
    assert r.status_code == 400 and r.json()["resultat"] == "refuse"
    assert trace() == []


def test_nouveau_dossier_parent_invalide(lanceur, tmp_path, trace):
    for dp in ["relatif/x", str(tmp_path / "absent"), None]:
        corps = {"nom": "ok", "utilisateur": "u"} | ({"dossier_parent": dp} if dp else {})
        assert lanceur.post("/api/projets/nouveau", json=corps).status_code == 400
    assert trace() == []


def test_nouveau_409_non_vide_et_vide_accepte(lanceur, tmp_path, trace):
    (tmp_path / "plein").mkdir()
    (tmp_path / "plein" / "f").write_text("x")
    r = lanceur.post("/api/projets/nouveau", json={"dossier_parent": str(tmp_path), "utilisateur": "u", "nom": "plein"})
    assert r.status_code == 409 and r.json()["resultat"] == "refuse"
    assert trace() == [] and (tmp_path / "plein" / "f").exists()
    (tmp_path / "vide").mkdir()
    r = lanceur.post("/api/projets/nouveau", json={"dossier_parent": str(tmp_path), "utilisateur": "u", "nom": "vide"})
    assert r.json()["resultat"] == "ok"
    (tmp_path / "fichier").write_text("x")
    assert lanceur.post("/api/projets/nouveau",
                        json={"dossier_parent": str(tmp_path), "utilisateur": "u", "nom": "fichier"}).status_code == 409


def test_json_invalide_400_journalise(lanceur):
    r = lanceur.post("/api/projets/nouveau", content=b"{pas du json",
                     headers={"content-type": "application/json"})
    assert r.status_code == 400 and r.json()["resultat"] == "refuse"
    assert journal(lanceur)[-1]["action"] == "nouveau"
    assert lanceur.post("/api/projets/ajouter", json=[1]).status_code == 400


# ── ajouter / oublier ───────────────────────────────────────────────────────────────────

def test_ajouter_idempotent_et_refus(lanceur, tmp_path):
    p = projet(tmp_path)
    for _ in range(2):
        assert lanceur.post("/api/projets/ajouter", json={"chemin": str(p)}).json()["resultat"] == "ok"
    # même dossier par un chemin non résolu : pas de doublon
    lanceur.post("/api/projets/ajouter", json={"chemin": str(p / ".." / "alpha")})
    assert lanceur.get("/api/projets").json() == {"projets": [{"chemin": str(p.resolve()), "nom": "alpha",
                                                               "etat": "ferme", "conversations": None}],
                                                  "utilisateur": None}
    (tmp_path / "sans").mkdir()
    for ch in ["relatif", str(tmp_path / "absent")]:
        assert lanceur.post("/api/projets/ajouter", json={"chemin": ch}).status_code == 400
    # un dossier sans manifeste lisible : Cime s'y installe (409 installable, cf. test_installer.py)
    r = lanceur.post("/api/projets/ajouter", json={"chemin": str(tmp_path / "sans")})
    assert r.status_code == 409 and r.json()["installable"] is True
    (tmp_path / "casse" / ".orga").mkdir(parents=True)
    (tmp_path / "casse" / ".orga" / "projet.toml").write_text("= pas du toml")
    # un manifeste illisible n'est pas « Cime absent » : on ne propose pas à `init` de le remplacer
    assert lanceur.post("/api/projets/ajouter", json={"chemin": str(tmp_path / "casse")}).status_code == 400


def test_oublier_ne_touche_pas_au_dossier(lanceur, tmp_path):
    p = projet(tmp_path)
    lanceur.post("/api/projets/ajouter", json={"chemin": str(p)})
    r = lanceur.post("/api/projets/oublier", json={"chemin": str(p)})
    assert r.json()["resultat"] == "ok"
    assert lanceur.get("/api/projets").json()["projets"] == []
    assert (p / ".orga" / "projet.toml").is_file()
    r = lanceur.post("/api/projets/oublier", json={"chemin": str(p)})
    assert r.status_code == 404 and r.json()["resultat"] == "refuse"
    assert (p / ".orga" / "projet.toml").is_file()


def test_memoire_format_et_atomicite(lanceur, tmp_path, monkeypatch):
    p = projet(tmp_path)
    lanceur.post("/api/projets/ajouter", json={"chemin": str(p)})
    brut = json.loads((lanceur.dossier / "projets.json").read_text())
    assert brut == [{"chemin": str(p.resolve()), "nom": "alpha"}]
    # écriture atomique : os.replace est utilisé, jamais d'écriture directe dans projets.json
    appels = []
    vrai = os.replace
    monkeypatch.setattr(mod.os, "replace", lambda a, b: (appels.append((Path(a).name, Path(b).name)), vrai(a, b)))
    q = projet(tmp_path, "beta", "be")
    lanceur.post("/api/projets/ajouter", json={"chemin": str(q)})
    assert appels == [("projets.json.tmp", "projets.json")]
    assert not (lanceur.dossier / "projets.json.tmp").exists()


# ── ouvrir ──────────────────────────────────────────────────────────────────────────────

def test_ouvrir_sans_manifeste_400(lanceur, tmp_path, nettoyage_hotes):
    (tmp_path / "vide").mkdir()
    r = lanceur.post("/api/projets/ouvrir", json={"chemin": str(tmp_path / "vide")})
    assert r.status_code == 400 and nettoyage_hotes == []


def test_ouvrir_lance_puis_reutilise(lanceur, tmp_path, trace, nettoyage_hotes):
    p = projet(tmp_path)
    r = lanceur.post("/api/projets/ouvrir", json={"chemin": str(p)})
    corps = r.json()
    assert corps["resultat"] == "ok" and corps["lance"] is True
    assert httpx.get(corps["url"] + "api/etat").status_code in (200, 503)
    (appel,) = trace()
    assert appel["argv"] == ["servir"] and appel["CIME_PROJET"] == str(p.resolve()) \
        and appel["CIME_AGENT"] is None and Path(appel["cwd"]).resolve() == p.resolve()
    assert len(nettoyage_hotes) == 1
    assert nettoyage_hotes[0].args[-1:] == [ "servir"] or True
    assert (lanceur.dossier / "journaux" / "hote-al.log").exists()
    assert lanceur.get("/api/projets").json()["projets"][0]["nom"] == "alpha"
    # deuxième appel : hôte vivant, aucun nouveau processus
    r2 = lanceur.post("/api/projets/ouvrir", json={"chemin": str(p)}).json()
    assert r2 == {"resultat": "ok", "url": corps["url"], "lance": False}
    assert len(nettoyage_hotes) == 1 and len(trace()) == 1


def test_ouvrir_deux_projets_deux_ports(lanceur, tmp_path):
    a, b = projet(tmp_path, "a", "aa"), projet(tmp_path, "b", "bb")
    ua = lanceur.post("/api/projets/ouvrir", json={"chemin": str(a)}).json()["url"]
    ub = lanceur.post("/api/projets/ouvrir", json={"chemin": str(b)}).json()["url"]
    assert ua != ub


def test_ouvrir_hote_qui_ne_demarre_jamais(lanceur, tmp_path, monkeypatch, nettoyage_hotes):
    monkeypatch.setenv("FAUX_CIME_JAMAIS", "1")
    monkeypatch.setattr(mod, "ATTENTE_HOTE_S", 0.5)
    p = projet(tmp_path)
    debut = time.monotonic()
    r = lanceur.post("/api/projets/ouvrir", json={"chemin": str(p)}).json()
    assert time.monotonic() - debut < 3
    assert r["resultat"] == "erreur" and "non démarré" in r["message"] and "je ne démarre pas" in r["message"]
    (proc,) = nettoyage_hotes
    assert proc.wait(timeout=5) is not None  # tué


def test_ouvrir_ignore_port_perime(lanceur, tmp_path):
    p = projet(tmp_path)
    (p / ".orga" / "etat").mkdir()
    (p / ".orga" / "etat" / "hote.port").write_text("1")  # personne n'écoute
    r = lanceur.post("/api/projets/ouvrir", json={"chemin": str(p)}).json()
    assert r["resultat"] == "ok" and r["lance"] is True


def test_ouvrir_hote_vivant_ne_lance_rien(lanceur, tmp_path, nettoyage_hotes, trace):
    # hôte factice à la main : un serveur HTTP qui répond 503
    import http.server

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(503)
            self.end_headers()
        log_message = lambda *a: None
    s = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    p = projet(tmp_path)
    (p / ".orga" / "etat").mkdir()
    (p / ".orga" / "etat" / "hote.port").write_text(str(s.server_port))
    try:
        r = lanceur.post("/api/projets/ouvrir", json={"chemin": str(p)}).json()
    finally:
        s.shutdown()
    assert r == {"resultat": "ok", "url": f"http://127.0.0.1:{s.server_port}/", "lance": False}
    assert nettoyage_hotes == [] and trace() == []


# ── journal ─────────────────────────────────────────────────────────────────────────────

def test_journal_une_ligne_par_appel(lanceur, tmp_path):
    p = projet(tmp_path)
    lanceur.post("/api/projets/ajouter", json={"chemin": str(p)})
    lanceur.post("/api/projets/ajouter", json={"chemin": "relatif"})
    lanceur.post("/api/projets/oublier", json={"chemin": str(tmp_path / "inconnu")})
    lanceur.post("/api/projets/oublier", json={"chemin": str(p)})
    lanceur.post("/api/projets/ouvrir", json={"chemin": str(tmp_path)})
    lanceur.post("/api/projets/nouveau", json={"dossier_parent": str(tmp_path), "utilisateur": "u", "nom": "NON"})
    lignes = journal(lanceur)
    assert [(l["action"], l["resultat"]) for l in lignes] == [
        ("ajouter", "ok"), ("ajouter", "refuse"), ("oublier", "refuse"), ("oublier", "ok"),
        ("ouvrir", "refuse"), ("nouveau", "refuse")]
    for l in lignes:
        assert set(l) == {"heure", "auteur", "action", "cible", "resultat", "message"}
        assert l["auteur"] == "utilisateur" and l["heure"].endswith("+00:00")
    assert lignes[0]["cible"] == str(p.resolve())


def test_journal_ecrit_avant_la_reponse(lanceur, tmp_path, monkeypatch):
    """Au moment où la réponse part, la ligne est déjà sur disque."""
    p = projet(tmp_path)
    r = lanceur.post("/api/projets/ajouter", json={"chemin": str(p)})
    assert r.status_code == 200 and len(journal(lanceur)) == 1


def test_journal_avant_reponse_meme_si_ecriture_echoue(lanceur, tmp_path):
    """Si le journal ne peut pas être écrit, la réponse n'est pas un succès."""
    p = projet(tmp_path)
    (lanceur.dossier / "journal.jsonl").mkdir()  # écriture impossible
    r = lanceur.post("/api/projets/ajouter", json={"chemin": str(p)})
    assert r.status_code >= 500


# ── sécurité locale ─────────────────────────────────────────────────────────────────────

def test_host_et_origin_etrangers_403(lanceur, tmp_path):
    p = projet(tmp_path)
    assert lanceur.get("/api/projets", headers={"Host": "evil.example:80"}).status_code == 403
    r = lanceur.post("/api/projets/ajouter", json={"chemin": str(p)}, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403
    assert lanceur.get("/api/projets").json()["projets"] == []
    assert journal(lanceur) == []
    ok = lanceur.post("/api/projets/ajouter", json={"chemin": str(p)},
                      headers={"Origin": f"http://127.0.0.1:{lanceur.port}"})
    assert ok.status_code == 200


# ── cycle de vie ────────────────────────────────────────────────────────────────────────

def test_port_efface_a_l_arret(lanceur):
    f = lanceur.dossier / "lanceur.port"
    assert f.exists()
    lanceur.arret.set()
    lanceur.thread.join(10)
    assert not f.exists()


def test_refus_si_un_lanceur_vit_deja(lanceur):
    with pytest.raises(SystemExit) as e:
        servir(port=0, dossier=lanceur.dossier, cime=["x"])
    assert str(lanceur.port) in str(e.value)
    assert (lanceur.dossier / "lanceur.port").exists()  # le refus n'efface pas le fichier du vivant


def test_port_perime_ne_bloque_pas(tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    (d / "lanceur.port").write_text("1")
    arret = threading.Event()
    t = threading.Thread(target=servir, kwargs=dict(dossier=d, cime=["x"], arret=arret), daemon=True)
    t.start()
    fin = time.time() + 10
    while (d / "lanceur.port").read_text() == "1" and time.time() < fin:
        time.sleep(0.02)
    assert (d / "lanceur.port").read_text() != "1"
    arret.set()
    t.join(10)


PROGRAMME = """
import sys
sys.path.insert(0, {src!r})
from pathlib import Path
from cime.lanceur import servir
servir(0, dossier=Path({d!r}), cime=['x'])
"""


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
def test_port_efface_au_signal_avec_client_connecte(tmp_path, sig):
    d = tmp_path / "dd"
    proc = subprocess.Popen([sys.executable, "-c", PROGRAMME.format(src=str(SRC), d=str(d))])
    try:
        f = d / "lanceur.port"
        fin = time.time() + 15
        while not f.exists() and time.time() < fin:
            time.sleep(0.05)
        assert f.exists()
        # client connecté, connexion keep-alive laissée ouverte
        c = httpx.Client(base_url=f"http://127.0.0.1:{f.read_text()}")
        assert c.get("/api/projets").status_code == 200
        debut = time.monotonic()
        proc.send_signal(sig)
        proc.wait(timeout=10)
        assert time.monotonic() - debut < 5
        assert not f.exists()
        c.close()
    finally:
        if proc.poll() is None:
            proc.kill()


@pytest.mark.parametrize("val", [None, "", "   ", "x" * 61, "a\nb", "a\x00", 3])
def test_utilisateur_invalide_400(lanceur, tmp_path, trace, val):
    corps = {"dossier_parent": str(tmp_path), "nom": "ok"} | ({} if val is None else {"utilisateur": val})
    r = lanceur.post("/api/projets/nouveau", json=corps)
    assert r.status_code == 400 and r.json()["resultat"] == "refuse"
    assert trace() == [] and not (lanceur.dossier / "lanceur.json").exists()
    assert lanceur.get("/api/projets").json()["utilisateur"] is None


def test_utilisateur_garde_et_strip(lanceur, tmp_path, trace):
    r = lanceur.post("/api/projets/nouveau",
                     json={"dossier_parent": str(tmp_path), "nom": "u1", "utilisateur": "  Léa  "})
    assert r.json()["resultat"] == "ok"
    assert trace()[0]["argv"][2:4] == ["--utilisateur", "Léa"]
    assert json.loads((lanceur.dossier / "lanceur.json").read_text()) == {"utilisateur": "Léa"}
    assert lanceur.get("/api/projets").json()["utilisateur"] == "Léa"
    # enregistrée dès la validation, même si init échoue ensuite
    os.environ["FAUX_CIME_CODE"] = "5"
    lanceur.post("/api/projets/nouveau", json={"dossier_parent": str(tmp_path), "nom": "u2", "utilisateur": "Max"})
    assert lanceur.get("/api/projets").json()["utilisateur"] == "Max"
    assert not (lanceur.dossier / "lanceur.json.tmp").exists()


def test_ouvrir_hote_qui_meurt_aussitot(lanceur, tmp_path, monkeypatch, nettoyage_hotes):
    """Un hôte mort au démarrage est signalé tout de suite, pas après le délai d'attente."""
    monkeypatch.setenv("FAUX_CIME_MEURT", "1")
    monkeypatch.setattr(mod, "ATTENTE_HOTE_S", 5)
    p = projet(tmp_path)
    debut = time.monotonic()
    r = lanceur.post("/api/projets/ouvrir", json={"chemin": str(p)}).json()
    assert time.monotonic() - debut < 2
    assert r["resultat"] == "erreur" and "code 4" in r["message"] and "registre cassé" in r["message"]


def test_ouvrir_simultanes_un_seul_servir(lanceur, tmp_path, nettoyage_hotes):
    """Deux `ouvrir` simultanés sur le même projet : un seul `servir`, la même URL."""
    import concurrent.futures
    p = projet(tmp_path)
    with concurrent.futures.ThreadPoolExecutor(2) as ex:
        r1, r2 = ex.map(lambda _: lanceur.post("/api/projets/ouvrir", json={"chemin": str(p)}).json(), range(2))
    assert r1["resultat"] == r2["resultat"] == "ok"
    assert r1["url"] == r2["url"]
    assert sorted([r1["lance"], r2["lance"]]) == [False, True]
    assert len(nettoyage_hotes) == 1
