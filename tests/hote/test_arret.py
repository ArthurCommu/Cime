"""`hote.port` effacé à l'arrêt par SIGTERM comme par SIGINT, y compris avec un flux SSE ouvert
(uvicorn relève le signal à la sortie de serve() : sans cela le `finally` de `servir` n'était pas
atteint, et l'arrêt restait bloqué par le flux)."""
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
PROGRAMME = """
import sys
from pathlib import Path
from datetime import datetime, timezone
sys.path.insert(0, {src!r})
from cime.hote.dependances import Dependances
from cime.hote.serveur import servir
inst = lambda p: {{"version": 1, "genere_a": datetime.now(timezone.utc).isoformat()}}
servir(Path({projet!r}), {port}, deps=Dependances(instantane=inst))
"""


def _ouvrir_flux(port, ouvert):
    try:
        with httpx.stream("GET", f"http://127.0.0.1:{port}/api/flux", timeout=30) as r:
            for _ in r.iter_lines():
                ouvert.set()
    except httpx.HTTPError:
        pass


@pytest.mark.parametrize("flux", [False, True], ids=["sans_flux", "flux_ouvert"])
@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
def test_hote_port_efface_au_signal(registre_vide, sig, flux):
    port = 0  # le système choisit : pas de course entre exécutions parallèles
    fichier = registre_vide / ".orga" / "etat" / "hote.port"
    code = PROGRAMME.format(src=str(SRC), projet=str(registre_vide), port=port)
    proc = subprocess.Popen([sys.executable, "-c", code])
    try:
        fin = time.time() + 15
        while not fichier.exists() and time.time() < fin:
            time.sleep(0.05)
        assert fichier.exists(), "l'hôte n'a pas écrit son port"
        if flux:
            ouvert = threading.Event()
            threading.Thread(target=_ouvrir_flux, args=(int(fichier.read_text()), ouvert), daemon=True).start()
            assert ouvert.wait(10), "le flux n'a rien envoyé"
        debut = time.monotonic()
        proc.send_signal(sig)
        proc.wait(timeout=10)
        assert time.monotonic() - debut < 2, "arrêt trop lent : le flux a retenu le serveur"
        assert not fichier.exists(), f"hote.port laissé après {sig.name}"
    finally:
        if proc.poll() is None:
            proc.kill()
