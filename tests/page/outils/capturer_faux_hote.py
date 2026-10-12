"""Captures de la page servie par le faux hôte : bureau et téléphone, dans les trois états du mode autonome.

sh tests/page/outils/nav.sh tests/page/outils/capturer_faux_hote.py <dossier-captures>   (voir nav.sh)

Démarre lui-même le faux hôte (hote_factice.py, sur CIME_PORT_TEST ou un port libre) et l'arrête à la fin, par son PID.
Chaque vue : écran puis page entière ; bureau 1 440 × 900, mobile 390 × 844 (tactile).
Un navigateur par capture : en --single-process, fermer un contexte ferme tout.
Les erreurs de page et de console sont affichées ; le code de sortie ne compte pas celles de réseau bloqué
(Google Fonts : `ERR_TUNNEL_CONNECTION_FAILED`, la page retombe sur les polices locales). Les captures sont à regarder.
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright
from lancer_scenario import proxy

OUTILS = Path(__file__).resolve().parent
PAGE = OUTILS.parents[2] / "src" / "cime" / "page"
ATTENTE = float(os.environ.get("ATTENTE", "3"))
TAILLES = {"bureau": (1440, 900), "mobile": (390, 844)}
VUES = {"accueil": "inactif", "autonome-actif": "actif", "autonome-suspendu": "suspendu"}
RESEAU_BLOQUE = "ERR_TUNNEL_CONNECTION_FAILED"


def port_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def demarrer_hote(port):
    proc = subprocess.Popen([sys.executable, str(OUTILS / "hote_factice.py"), str(PAGE), str(port)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            urllib.request.urlopen(base + "/api/etat", timeout=1).read()
            return proc, base
        except OSError:
            time.sleep(0.2)
    proc.terminate()
    raise RuntimeError("le faux hôte ne répond pas")


def capturer(p, url, nom, dossier, taille):
    w, h = TAILLES[taille]
    mobile = taille == "mobile"
    nav = p.chromium.launch(headless=True, args=["--single-process"], proxy=proxy())
    erreurs = []
    try:
        ctx = nav.new_context(viewport={"width": w, "height": h}, device_scale_factor=1, locale="fr-FR",
                              is_mobile=mobile, has_touch=mobile)
        page = ctx.new_page()
        # Pas de page.route : le faux hôte est local et la capture ne fait que des GET. Une route posée ici
        # empêche le plateau de la Scène de se dessiner (constaté par bisection).
        page.on("pageerror", lambda e: erreurs.append(str(e)))
        page.on("console", lambda m: erreurs.append(m.text) if m.type == "error" else None)
        page.goto(url, wait_until="domcontentloaded")
        time.sleep(ATTENTE)
        page.screenshot(path=str(dossier / f"{nom}-{taille}.png"))
        page.screenshot(path=str(dossier / f"{nom}-{taille}-entiere.png"), full_page=True)
        hauteur = page.evaluate("document.documentElement.scrollHeight")
        large = page.evaluate("document.documentElement.scrollWidth")
        print(f"{nom}-{taille}: hauteur={hauteur} largeur={large} (fenêtre {w}) erreurs={erreurs[:3]}", flush=True)
    finally:
        nav.close()
    return erreurs


def main():
    dossier = Path(sys.argv[1])
    dossier.mkdir(parents=True, exist_ok=True)
    port = int(os.environ.get("CIME_PORT_TEST") or port_libre())
    proc, base = demarrer_hote(port)
    toutes = []
    try:
        with sync_playwright() as p:
            for nom, autonome in VUES.items():
                urllib.request.urlopen(f"{base}/test/regler?autonome={autonome}", timeout=5).read()
                for taille in TAILLES:
                    try:
                        toutes += capturer(p, f"{base}/", nom, dossier, taille)
                    except Exception as e:  # noqa: BLE001
                        print(f"{nom}-{taille}: ÉCHEC {str(e).splitlines()[0]}", flush=True)
                        toutes.append(str(e))
    finally:
        proc.terminate()
        proc.wait(timeout=5)
    reelles = [e for e in toutes if RESEAU_BLOQUE not in e]
    print(f"\nerreurs de page ou de console : {len(toutes)} dont {len(reelles)} hors réseau bloqué")
    for e in toutes[:10]:
        print("  -", e)
    sys.exit(1 if reelles else 0)


if __name__ == "__main__":
    main()
