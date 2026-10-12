"""Flux coupé -> l'âge de la donnée passe au rouge -> flux rétabli -> retour à l'état normal.

Contre hote_factice.py déjà lancé (port CIME_PORT_TEST, 8791 par défaut).
Code de sortie 1 si une vérification échoue.
"""
import os
import sys
import urllib.request

from playwright.sync_api import sync_playwright

PORT = os.environ.get("CIME_PORT_TEST", "8791")
B = f"http://127.0.0.1:{PORT}"
CHROME = os.environ.get("CIME_CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
KO = []


def regler(q):
    urllib.request.urlopen(f"{B}/test/regler?{q}").read()


def verifier(nom, cond, detail=""):
    if not cond:
        KO.append(nom)
    print(("OK  " if cond else "KO  ") + nom + (f" — {detail}" if detail else ""))


with sync_playwright() as p:
    nav = p.chromium.launch(executable_path=CHROME, headless=True)
    pg = nav.new_page()
    pg.goto(B + "/#/supervision")
    pg.wait_for_timeout(2000)
    age = pg.locator(".age-donnee")
    lire = lambda: (age.get_attribute("data-niveau"), age.inner_text().replace("\n", " "))
    avant = lire()
    verifier("avant la coupure : donnée à jour", avant[0] == "ok", str(avant))
    regler("flux=coupe")
    niveaux = []
    for t in range(4):
        pg.wait_for_timeout(1000)
        niveaux.append(lire())
        print(f"coupé +{t + 1}s", niveaux[-1])
    verifier("flux coupé : la donnée passe au rouge", niveaux[-1][0] == "rouge", str(niveaux[-1]))
    regler("flux=normal")
    for t in range(4):
        pg.wait_for_timeout(2000)
        retour = lire()
        print(f"rétabli +{2 * t + 2}s", retour)
    verifier("flux rétabli : retour à jour", retour[0] == "ok", str(retour))
    nav.close()

print(f"\n{'KO' if KO else 'TOUT OK'} — {len(KO)} échec(s)")
sys.exit(1 if KO else 0)
