"""Vérifications navigateur des workers terminés (« Historique »), contre hote_factice.py.

Ce que pytest ne voit pas (il n'exécute pas le JS) : l'organigramme rendu sans le worker terminé, l'en-tête et
la ligne « agents arrêtés » qui ne le comptent pas, le repli « + n workers terminés » sur la page d'équipe,
son dépliage au clic, l'absence de débordement à 390 px, et les captures à regarder. Usage (le faux hôte doit
tourner sur CIME_PORT_TEST, il sert l'état d'exemple) :

    uv run --with playwright python tests/page/outils/scenario_historique.py <dossier-captures>

Code de sortie 1 si une vérification échoue. Les captures sont écrites dans le dossier donné.
"""
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PORT = os.environ.get("CIME_PORT_TEST", "8791")
BASE = f"http://127.0.0.1:{PORT}"
CHROME = os.environ.get("CIME_CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
OK, KO = [], []


def verifier(nom, cond, detail=""):
    (OK if cond else KO).append(nom)
    print(("OK  " if cond else "KO  ") + nom + (f" — {detail}" if detail else ""))


def main(sorties):
    erreurs = []
    with sync_playwright() as p:
        nav = p.chromium.launch(executable_path=CHROME, headless=True)
        pg = nav.new_page(viewport={"width": 1440, "height": 1000})
        pg.on("console", lambda m: erreurs.append(m.text) if m.type in ("error", "warning") else None)
        pg.on("pageerror", lambda e: erreurs.append(str(e)))

        # 1. vue d'ensemble : le worker terminé n'est pas dessiné, le worker arrêté avec alarme l'est
        pg.goto(f"{BASE}/#/supervision")
        pg.wait_for_selector(".organigramme")
        pg.wait_for_selector(".nouveautes")
        org = pg.locator(".organigramme")
        verifier("organigramme : worker terminé absent (worker-hote-schema)",
                 org.locator(".agent[data-agent='worker-hote-schema']").count() == 0)
        verifier("organigramme : worker arrêté avec alarme présent (worker-observation-git)",
                 org.locator(".agent[data-agent='worker-observation-git']").count() == 1)
        verifier("organigramme : worker vivant présent (worker-hote-serveur)",
                 org.locator(".agent[data-agent='worker-hote-serveur']").count() == 1)
        verifier("organigramme : coordinateur présent (coord-hote)", org.locator(".agent[data-agent='coord-hote']").count() == 1)

        # 2. en-tête : un seul arrêté compté (worker-observation-git) ; le terminé n'est pas compté
        entete = pg.locator(".entete-etat").inner_text()
        verifier("en-tête : « 1 arrêté », le terminé n'est pas compté",
                 "1 arrêté" in entete and "2 arrêtés" not in entete, entete.replace("\n", " | "))

        # 3. nouveautés : « agents arrêtés » ne cite pas le terminé (son arrêt est pourtant dans la fenêtre)
        nouveautes = pg.locator(".nouveautes").inner_text()
        verifier("nouveautés : « 1 agent arrêté » avec worker-observation-git seul",
                 "1 agent arrêté : worker-observation-git" in nouveautes, nouveautes.replace("\n", " | ")[:200])
        verifier("nouveautés : le terminé n'est pas cité", "worker-hote-schema" not in nouveautes)

        # 4. page d'équipe hote : liste des vivants, puis « + 1 worker terminé » replié
        pg.goto(f"{BASE}/#/equipe/hote")
        pg.wait_for_selector(".eq-termines")
        bloc = pg.locator(".eq-termines")
        verifier("page hote : un seul repli des workers terminés", bloc.count() == 1)
        verifier("page hote : résumé « + 1 worker terminé »", bloc.locator("summary").inner_text() == "+ 1 worker terminé",
                 bloc.locator("summary").inner_text())
        verifier("page hote : repli fermé par défaut", bloc.get_attribute("open") is None)
        verifier("page hote : le terminé est dans le repli, caché tant que replié",
                 bloc.locator(".eq-termine").count() == 1 and not bloc.locator(".eq-termine").is_visible())
        verifier("page hote : workers vivants hors du repli",
                 pg.locator(".eq-agent[data-agent='worker-hote-serveur']").count() == 1
                 and pg.locator(".eq-termines .eq-agent").count() == 0)
        juste_avant = pg.evaluate("document.querySelector('.eq-termines').previousElementSibling.className")
        verifier("page hote : repli juste après la liste des vivants", "eq-agents" in juste_avant, juste_avant)
        pg.locator(".eq-termines summary").click()
        pg.wait_for_selector(".eq-termines[open] .eq-termine")
        verifier("page hote : le clic déplie le repli",
                 bloc.get_attribute("open") is not None and bloc.locator(".eq-termine").is_visible()
                 and "worker-hote-schema" in bloc.locator(".eq-termine").inner_text())
        pg.locator(".eq-termines").screenshot(path=str(sorties / "termines-ouvert-1440.png"))
        pg.locator(".eq-termines summary").click()  # on le replie pour la capture de la page entière

        # 5. page d'équipe observation : un worker arrêté avec alarme reste dans la liste, sans historique
        pg.goto(f"{BASE}/#/equipe/observation")
        pg.wait_for_selector(".eq-agent[data-agent='worker-observation-git']")
        verifier("page observation : worker arrêté avec alarme dans la liste",
                 pg.locator(".section .eq-agent[data-agent='worker-observation-git']").count() == 1)
        verifier("page observation : aucun repli des terminés", pg.locator(".eq-termines").count() == 0)

        # 6. captures à regarder, et pas de débordement à 1440 ni à 390 px
        for largeur in (1440, 390):
            pg.set_viewport_size({"width": largeur, "height": 1000})
            pg.goto(f"{BASE}/#/supervision")
            pg.wait_for_selector(".organigramme")
            pg.wait_for_timeout(300)
            debordement = pg.evaluate("document.documentElement.scrollWidth")
            verifier(f"vue d'ensemble : pas de débordement à {largeur} px", debordement <= largeur, f"scrollWidth={debordement}")
            if largeur == 1440:
                pg.screenshot(path=str(sorties / "ensemble-1440.png"), full_page=True)
            pg.goto(f"{BASE}/#/equipe/hote")
            pg.wait_for_selector(".eq-termines")
            pg.wait_for_timeout(300)
            debordement = pg.evaluate("document.documentElement.scrollWidth")
            verifier(f"page d'équipe : pas de débordement à {largeur} px", debordement <= largeur, f"scrollWidth={debordement}")
            if largeur == 1440:
                pg.screenshot(path=str(sorties / "equipe-hote-1440.png"), full_page=True)
        nav.close()

    verifier("aucune erreur JS ni avertissement de console", not erreurs, "; ".join(erreurs))
    print(f"\n{len(OK)} OK, {len(KO)} KO : {KO}")
    return 1 if KO else 0


if __name__ == "__main__":
    sortie = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    sys.exit(main(sortie))
