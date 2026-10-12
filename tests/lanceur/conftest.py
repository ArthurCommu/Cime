"""Fixtures des tests du lanceur : isolation du dossier de la machine, faux `cime`, et filet interdisant tout vrai lancement."""
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

FAUX = Path(__file__).resolve().parent / "faux_cime.py"
SRC = Path(__file__).resolve().parents[2] / "src"


@pytest.fixture(autouse=True)
def isolation(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CIME_PROJET", str(tmp_path / "faux-projet-lanceur"))
    monkeypatch.setenv("CIME_AGENT", "worker-x")
    monkeypatch.setenv("CIME_SANS_SURVEILLANT", "1")   # le surveillant a ses propres tests
    monkeypatch.setenv("PYTHONPATH", str(SRC) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    monkeypatch.setenv("FAUX_CIME_TRACE", str(tmp_path / "trace.jsonl"))
    monkeypatch.delenv("FAUX_CIME_CODE", raising=False)
    monkeypatch.delenv("FAUX_CIME_JAMAIS", raising=False)
    monkeypatch.setattr(mod, "ATTENTE_HOTE_S", 2)
    monkeypatch.setattr(mod, "SONDAGE_S", 0.05)


class LancementInterdit(AssertionError):
    pass


@pytest.fixture(autouse=True)
def aucun_vrai_lancement(tmp_path, monkeypatch):
    """Un test ne lance jamais un vrai lanceur, un vrai `launchctl` ni un vrai `open` (`cime ouvrir`).

    Un lanceur détaché survit au test (parent 1) et prend le port fixe du vrai lanceur. Si un test
    atteint le lancement sans l'avoir injecté (une garde qui saute, une mutation), il échoue au
    lieu de lancer quoi que ce soit. Un faux `launchctl`/`open` placé sous `tmp_path` reste permis."""
    import shutil
    from cime.lanceur import ouvrir

    def popen(argv, **options):
        raise LancementInterdit(f"un test a voulu lancer un vrai processus : {list(argv)}")

    def run(argv, **options):
        trouve = shutil.which(argv[0])
        if not trouve or not Path(trouve).resolve().is_relative_to(tmp_path.resolve()):
            raise LancementInterdit(f"un test a voulu lancer un vrai {argv[0]} : {list(argv)}")
        return subprocess.run(argv, **options)

    monkeypatch.setattr(ouvrir, "_popen", popen)
    monkeypatch.setattr(ouvrir, "_run", run)


@pytest.fixture
def trace(tmp_path):
    def lire():
        f = tmp_path / "trace.jsonl"
        return [json.loads(l) for l in f.read_text().splitlines()] if f.exists() else []
    return lire


@pytest.fixture(autouse=True)
def nettoyage_hotes(monkeypatch):
    """Tue tout processus `servir` lancé par un test."""
    lances = []
    vrai = mod.executer

    def espion(*a, **k):
        r = vrai(*a, **k)
        if k.get("journal_sortie") is not None:
            lances.append(r)
        return r

    monkeypatch.setattr(mod, "executer", espion)
    yield lances
    for p in lances:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


@pytest.fixture
def lanceur(tmp_path):
    """Lanceur réel (thread) avec faux cime ; renvoie un client httpx et ses chemins."""
    dossier = tmp_path / "cime-dossier"
    arret = threading.Event()
    t = threading.Thread(
        target=servir, kwargs=dict(port=0, dossier=dossier, cime=[sys.executable, str(FAUX)], arret=arret),
        daemon=True)
    t.start()
    fichier = dossier / "lanceur.port"
    fin = time.time() + 10
    while not fichier.exists() and time.time() < fin:
        time.sleep(0.02)
    assert fichier.exists()
    port = int(fichier.read_text())
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=20) as c:
        c.dossier, c.port, c.arret, c.thread = dossier, port, arret, t
        yield c
    arret.set()
    t.join(10)


def journal(c):
    f = c.dossier / "journal.jsonl"
    return [json.loads(l) for l in f.read_text().splitlines()] if f.exists() else []
