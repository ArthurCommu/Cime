"""Vérifications navigateur du cadre de l'accueil, contre hote_factice.py.

Ce que pytest ne voit pas : les trois onglets dans l'ordre, `#/supervision` qui montre l'ancienne vue d'ensemble,
le plateau sur `#/` (la scène y est montée), l'en-tête de 56 px, l'absence de débordement horizontal à 390 et 1440 px, la console sans
erreur, et deux captures par taille à regarder. Usage (le faux hôte doit tourner sur CIME_PORT_TEST) :

    uv run --with playwright python tests/page/outils/scenario_cadre.py <dossier-captures>

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
        pg = nav.new_page(viewport={"width": 1440, "height": 900})
        pg.on("console", lambda m: erreurs.append(m.text) if m.type in ("error", "warning") else None)
        pg.on("pageerror", lambda e: erreurs.append(str(e)))

        # 1. la scène est l'accueil : trois onglets dans l'ordre, Scène courant, plateau présent et vide
        pg.goto(f"{BASE}/#/")
        pg.wait_for_selector(".plateau")
        onglets = pg.locator(".nav a").all_inner_texts()
        verifier("trois onglets, dans l'ordre", onglets == ["Scène", "Supervision", "Fil"], str(onglets))
        verifier("« Scène » est l'onglet courant sur #/", pg.locator(".nav a[aria-current=page]").all_inner_texts() == ["Scène"])
        verifier("le plateau existe sur #/", pg.locator("#plateau.plateau").count() == 1)
        pg.wait_for_selector("#plateau > canvas", timeout=5000)
        verifier("la scène est montée dans le plateau (un canvas)", pg.locator("#plateau > canvas").count() == 1)
        verifier("pas de bandeau « Ce qui t'attend » sur la scène", pg.locator(".bandeau").count() == 0)
        verifier("pas de pied de page", pg.locator("footer").count() == 0)

        # 2. l'en-tête : 56 px, ses éléments, « Demander à l'Assistant » présent
        hauteur = pg.evaluate("document.querySelector('.entete').getBoundingClientRect().height")
        verifier("l'en-tête fait 56 px à 1440 px", round(hauteur) == 56, str(hauteur))
        verifier("« En direct » dans l'en-tête", "En direct" in pg.locator(".age-donnee").inner_text(), pg.locator(".age-donnee").inner_text())
        verifier("bouton « Demander à l'Assistant » dans l'en-tête", pg.locator(".entete button.demander").inner_text() == "Demander à l’Assistant")
        verifier("pas de lien « Scène » vers /scene/", pg.locator("a[href^='/scene/']").count() == 0)

        # 3. Supervision : l'ancienne vue d'ensemble, ses deux liens de pied, plus de bouton Demander dedans
        pg.goto(f"{BASE}/#/supervision")
        pg.wait_for_selector(".organigramme")
        verifier("#/supervision affiche l'organigramme", pg.locator(".organigramme").count() == 1)
        verifier("« Supervision » est l'onglet courant", pg.locator(".nav a[aria-current=page]").all_inner_texts() == ["Supervision"])
        verifier("pied de Supervision : Journal des actions et Équipes clôturées",
                 pg.locator(".pied-supervision a").all_inner_texts() == ["Journal des actions", "Équipes clôturées"])
        verifier("un seul bouton « Demander à l'Assistant » sur l'écran", pg.get_by_role("button", name="Demander à l’Assistant").count() == 1)
        for ancre, titre in (("#/journal", "Journal"), ("#/archives", "Équipes clôturées")):
            pg.locator(f".pied-supervision a[href='{ancre}']").click()
            pg.wait_for_selector(".section-tete h2")
            verifier(f"{ancre} : aucun onglet courant", pg.locator(".nav a[aria-current=page]").count() == 0)
            verifier(f"{ancre} : le bon écran", pg.locator(".section-tete h2").first.inner_text() == titre)
        pg.goto(f"{BASE}/#/equipe/hote")
        pg.wait_for_selector(".eq-tete")
        verifier("fiche d'équipe : aucun onglet courant, lien « ← Supervision »",
                 pg.locator(".nav a[aria-current=page]").count() == 0 and pg.locator(".eq-tete a[href='#/supervision']").inner_text() == "← Supervision")
        pg.goto(f"{BASE}/#/n-importe-quoi")
        pg.wait_for_selector(".plateau")
        verifier("route inconnue → Scène", pg.locator(".nav a[aria-current=page]").all_inner_texts() == ["Scène"])

        # 4. le plateau survit au réaffichage : même nœud avant et après un nouveau rendu
        pg.goto(f"{BASE}/#/")
        pg.wait_for_selector(".plateau")
        pg.evaluate("document.getElementById('plateau').dataset.marque = 'x'")
        pg.evaluate("location.hash = '#/supervision'")
        pg.wait_for_selector(".organigramme")
        pg.evaluate("location.hash = '#/'")
        pg.wait_for_selector(".plateau")
        verifier("le plateau est le même nœud après un aller-retour", pg.evaluate("document.getElementById('plateau').dataset.marque") == "x")

        # 5. captures et débordement horizontal, à 1440×900 et 390×844
        for largeur, hauteur_vp in ((1440, 900), (390, 844)):
            pg.set_viewport_size({"width": largeur, "height": hauteur_vp})
            for ancre, nom in (("#/", "scene"), ("#/supervision", "supervision")):
                pg.goto(f"{BASE}/{ancre}")
                pg.wait_for_selector(".entete")
                pg.wait_for_timeout(400)
                debordement = pg.evaluate("document.documentElement.scrollWidth")
                verifier(f"{nom} : pas de débordement horizontal à {largeur} px", debordement <= largeur, f"scrollWidth={debordement}")
                pg.screenshot(path=str(sorties / f"cadre-{nom}-{largeur}x{hauteur_vp}.png"))
        nav.close()

    verifier("aucune erreur JS ni avertissement de console", not erreurs, "; ".join(erreurs))
    print(f"\n{len(OK)} OK, {len(KO)} KO : {KO}")
    return 1 if KO else 0


if __name__ == "__main__":
    sortie = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    sys.exit(main(sortie))
