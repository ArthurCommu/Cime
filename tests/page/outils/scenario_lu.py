"""Vérifications navigateur du bouton « Marquer comme lu » (`fil[].non_lu`), contre hote_factice.py.

Ce que pytest ne voit pas (il n'exécute pas le JS) : le repère « non lu » et le bouton présents sur le message
non lu de l'exemple et absents sur l'entrée `autorisation:`, le clic qui envoie exactement
`POST /api/actions/lu` avec `{"attente_id": "msg-<n>"}`, le bouton désactivé pendant l'action puis remplacé par
« envoyé, en attente de confirmation », aucune boîte de dialogue, aucune erreur de console, et les captures à
regarder. La page est servie par le faux hôte, qui répond `ok` à toute action. Usage (le faux hôte doit tourner
sur CIME_PORT_TEST) :

    uv run --with playwright python tests/page/outils/scenario_lu.py <dossier-captures>

Code de sortie 1 si une vérification échoue. Les captures sont écrites dans le dossier donné.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

PORT = os.environ.get("CIME_PORT_TEST", "8791")
BASE = f"http://127.0.0.1:{PORT}"
CHROME = os.environ.get("CIME_CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
MOT_ENVOYEE = "envoyé, en attente de confirmation"
OK, KO = [], []


def verifier(nom, cond, detail=""):
    (OK if cond else KO).append(nom)
    print(("OK  " if cond else "KO  ") + nom + (f" — {detail}" if detail else ""))


def hote(chemin):
    with urllib.request.urlopen(BASE + chemin) as r:
        return json.loads(r.read())


def posts_lu():
    return [r for r in hote("/test/requetes") if r["m"] == "POST" and r["chemin"] == "/api/actions/lu"]


def main(sorties):
    erreurs = []
    hote("/test/regler?actions=ok&flux=normal")
    with sync_playwright() as p:
        nav = p.chromium.launch(executable_path=CHROME, headless=True)
        pg = nav.new_page(viewport={"width": 1440, "height": 1000})
        pg.on("console", lambda m: erreurs.append(m.text) if m.type in ("error", "warning") else None)
        pg.on("pageerror", lambda e: erreurs.append(str(e)))

        # 1. vue d'ensemble : msg-66 (non lu, récent) est dans les cinq du fil, avec repère et bouton
        pg.goto(f"{BASE}/#/supervision")
        pg.wait_for_selector(".fil-ligne[data-id='msg-66']")
        ligne = pg.locator(".fil-ligne[data-id='msg-66']")
        verifier("ensemble : repère « non lu » sur msg-66", ligne.locator(".fil-non-lu").count() == 1)
        verifier("ensemble : bouton « Marquer comme lu » sur msg-66",
                 ligne.locator("button", has_text="Marquer comme lu").count() == 1)
        verifier("ensemble : le bouton n'est pas dans le bouton de dépliage",
                 ligne.locator(".fil-ouvrir button").count() == 0)
        pg.locator(".fil").screenshot(path=str(sorties / "ensemble-fil-lu-1440.png"))
        pg.screenshot(path=str(sorties / "ensemble-lu-1440.png"), full_page=True)

        # 2. fil : msg-50 (ancien, non lu) a son repère ; l'autorisation: n'en a pas ; un hook non plus
        pg.goto(f"{BASE}/#/fil")
        pg.wait_for_selector(".fil-ligne[data-id='msg-50']")
        verifier("fil : msg-50 (non lu, ancien) a son repère et son bouton",
                 pg.locator(".fil-ligne[data-id='msg-50'] .fil-non-lu").count() == 1
                 and pg.locator(".fil-ligne[data-id='msg-50']").locator("button", has_text="Marquer comme lu").count() == 1)
        auto = pg.locator(".fil-ligne[data-id='msg-67']")
        verifier("fil : entrée « autorisation: » (msg-67) sans repère ni bouton",
                 auto.count() == 1 and auto.locator(".fil-non-lu").count() == 0
                 and auto.locator("button", has_text="Marquer comme lu").count() == 0)
        hook = pg.locator(".fil-ligne[data-id='evt-324']")
        verifier("fil : entrée hook (evt-324) sans repère", hook.count() == 1 and hook.locator(".fil-non-lu").count() == 0)
        pg.locator(".fil").screenshot(path=str(sorties / "fil-lu-1440.png"))

        # 3. clic : une seule requête, le corps exact ; le bouton est désactivé pendant l'action
        hote("/test/regler?actions=lent")
        avant = len(posts_lu())
        ligne = pg.locator(".fil-ligne[data-id='msg-66']")
        bouton = ligne.locator("button", has_text="Marquer comme lu")
        bouton.click()
        verifier("pendant l'action : bouton désactivé", bouton.is_disabled())
        verifier("pendant l'action : pas de boîte de dialogue", pg.locator("dialog[open]").count() == 0)
        pg.wait_for_selector(f".fil-ligne[data-id='msg-66'] .attente-envoyee:text-is('{MOT_ENVOYEE}')", timeout=8000)
        verifier("après « ok » : « envoyé, en attente de confirmation » remplace le bouton",
                 ligne.locator("button", has_text="Marquer comme lu").count() == 0)
        verifier("après « ok » : le repère « non lu » reste", ligne.locator(".fil-non-lu").count() == 1)
        hote("/test/regler?actions=ok")
        envois = posts_lu()[avant:]
        verifier("un seul POST /api/actions/lu", len(envois) == 1, f"{len(envois)} envoi(s)")
        verifier("corps exact {\"attente_id\": \"msg-66\"}",
                 len(envois) == 1 and envois[0].get("corps") == {"attente_id": "msg-66"},
                 str(envois[0].get("corps")) if envois else "aucun")

        # 4. aucune erreur JS ni avertissement
        verifier("aucune erreur JS ni avertissement de console", not erreurs, "; ".join(erreurs))
        nav.close()

    print(f"\n{len(OK)} OK, {len(KO)} KO : {KO}")
    return 1 if KO else 0


if __name__ == "__main__":
    sortie = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    sys.exit(main(sortie))
