"""Vérifications navigateur de la fiche équipe, contre hote_factice.py en mode hôte.

Ce que pytest ne voit pas (il n'exécute ni le CSS ni la mise en page) : l'ordre réel des sections, les replis fermés puis ouverts, les hauteurs
mesurées (le terminal et 12 lignes de sa zone dans les 900 px de 1 440 × 900 ; son haut avant la fin de 390 × 844), l'absence de barre horizontale,
et les captures à regarder. Les hauteurs estimées par tests/page/test_fiche_equipe.py (`verifier_hauteurs`) sont ici mesurées pour de vrai.
Usage (le faux hôte doit tourner sur CIME_PORT_TEST, il sert l'état d'exemple) :

    uv run --with playwright python tests/page/outils/scenario_equipe.py <dossier-captures>

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
LIGNE_PX = 18.75  # une ligne du terminal : 12,5 px × 1,5
ECRANS = {"bureau": (1440, 900), "mobile": (390, 844)}

# hote : l'équipe de l'exemple qui a le plus d'agents, sans attente à elle ; page : deux attentes de l'utilisateur (une autorisation, une décision)
EQUIPE_CHARGEE, EQUIPE_AVEC_ATTENTE = "hote", "page"


def verifier(nom, cond, detail=""):
    (OK if cond else KO).append(nom)
    print(("OK  " if cond else "KO  ") + nom + (f" — {detail}" if detail else ""))


def ouvrir(pg, equipe):
    pg.goto(f"{BASE}/#/equipe/{equipe}")
    pg.wait_for_selector(".fiche .eq-tete")
    pg.wait_for_selector(".terminal-bloc .terminal")
    pg.wait_for_function("document.querySelector('.terminal').textContent.length > 0", timeout=8000)
    pg.wait_for_timeout(300)


def titres(pg):
    """Les titres des sections de la fiche, dans l'ordre de la page (le résumé fait le titre des replis)."""
    return pg.evaluate("[...document.querySelectorAll('.fiche > section h2, .fiche > details > summary h2')].map((n) => n.textContent.trim())")


def haut_terminal(pg):
    """(haut de la zone du terminal, bas de cette zone) en px depuis le haut de la page, sans défilement."""
    return pg.evaluate("(() => { const r = document.querySelector('.terminal').getBoundingClientRect(); return [r.top + scrollY, r.bottom + scrollY, r.height]; })()")


def main(sorties):
    erreurs = []
    with sync_playwright() as p:
        nav = p.chromium.launch(executable_path=CHROME, headless=True)
        for ecran, (largeur, hauteur) in ECRANS.items():
            pg = nav.new_page(viewport={"width": largeur, "height": hauteur})
            pg.on("console", lambda m: erreurs.append(m.text) if m.type in ("error", "warning") else None)
            pg.on("pageerror", lambda e: erreurs.append(str(e)))

            # 1. l'équipe chargée : l'ordre des sections, les replis fermés, le terminal dans le premier écran
            ouvrir(pg, EQUIPE_CHARGEE)
            t = titres(pg)
            verifier(f"{ecran} · {EQUIPE_CHARGEE} : l'ordre des sections", t == [
                "Ses agents", "Terminal en direct", "Ses derniers échanges", "Ses alarmes",
                "Périmètre : 2 chemins · 2 fichiers touchés · 1 hors périmètre", "Dépendances : 4"], str(t))
            verifier(f"{ecran} · {EQUIPE_CHARGEE} : pas de section « Attend de toi » sans attente", "Attend de toi" not in t)
            verifier(f"{ecran} · {EQUIPE_CHARGEE} : périmètre et dépendances repliés",
                     pg.locator(".eq-repli[open]").count() == 0 and pg.locator(".eq-repli").count() == 2)
            verifier(f"{ecran} · {EQUIPE_CHARGEE} : le contenu replié n'est pas visible",
                     not pg.locator(".eq-perimetre .eq-repli-corps").is_visible() and not pg.locator(".eq-dependances .eq-repli-corps").is_visible())
            verifier(f"{ecran} · {EQUIPE_CHARGEE} : « + 1 worker terminé » replié, aucun identifiant visible",
                     pg.locator(".eq-termines > summary").inner_text() == "+ 1 worker terminé"
                     and pg.locator(".eq-termines[open]").count() == 0 and not pg.locator(".eq-termine").first.is_visible())
            verifier(f"{ecran} · {EQUIPE_CHARGEE} : plus de ligne « Sans session capturée »", "Sans session capturée" not in pg.inner_text(".fiche"))
            haut, bas, zone = haut_terminal(pg)
            verifier(f"{ecran} · {EQUIPE_CHARGEE} : la zone du terminal fait au moins 12 lignes", zone >= 12 * LIGNE_PX, f"{zone:.0f} px")
            verifier(f"{ecran} · {EQUIPE_CHARGEE} : le haut du terminal est dans le premier écran ({hauteur} px)", haut < hauteur, f"haut = {haut:.0f} px")
            if ecran == "bureau":
                verifier(f"{ecran} · {EQUIPE_CHARGEE} : au moins 12 lignes du terminal dans le premier écran",
                         haut + 53 + 12 * LIGNE_PX + 14 <= hauteur or haut + 12 * LIGNE_PX + 14 <= hauteur, f"haut = {haut:.0f} px, bas = {bas:.0f} px")
            verifier(f"{ecran} · {EQUIPE_CHARGEE} : pas de barre horizontale", pg.evaluate("document.documentElement.scrollWidth") <= largeur,
                     f"scrollWidth = {pg.evaluate('document.documentElement.scrollWidth')}")
            pg.screenshot(path=str(sorties / f"fiche-{EQUIPE_CHARGEE}-{ecran}-replie.png"))
            pg.screenshot(path=str(sorties / f"fiche-{EQUIPE_CHARGEE}-{ecran}-entiere.png"), full_page=True)

            # 2. les replis s'ouvrent au clic, sans barre horizontale, et se referment
            pg.locator(".eq-termines > summary").click()
            verifier(f"{ecran} · les workers terminés se listent un par ligne, avec leur tâche et leur âge",
                     pg.locator(".eq-termine").first.is_visible() and "Figer le schéma" in pg.locator(".eq-termine").first.inner_text()
                     and pg.locator(".eq-termine time").count() == 1, pg.locator(".eq-termine").first.inner_text().replace("\n", " | "))
            pg.locator(".eq-perimetre > summary").click()
            pg.locator(".eq-dependances > summary").click()
            verifier(f"{ecran} · périmètre et dépendances s'ouvrent", pg.locator(".eq-perimetre .eq-repli-corps").is_visible()
                     and pg.locator(".eq-dependances .eq-repli-corps").is_visible())
            verifier(f"{ecran} · replis ouverts : pas de barre horizontale", pg.evaluate("document.documentElement.scrollWidth") <= largeur,
                     f"scrollWidth = {pg.evaluate('document.documentElement.scrollWidth')}")
            pg.screenshot(path=str(sorties / f"fiche-{EQUIPE_CHARGEE}-{ecran}-replis-ouverts.png"), full_page=True)
            for selecteur in (".eq-termines > summary", ".eq-perimetre > summary", ".eq-dependances > summary"):
                pg.locator(selecteur).click()
            verifier(f"{ecran} · les replis se referment", pg.locator(".eq-repli[open], .eq-termines[open]").count() == 0)

            # 3. un agent : la ligne s'ouvre sur sa carte complète, sans déplacer le terminal hors de la page
            pg.locator(".eq-agent > summary").first.click()
            verifier(f"{ecran} · la ligne d'agent s'ouvre sur sa carte", pg.locator(".eq-agent[open] .agent").first.is_visible())
            pg.locator(".eq-agent > summary").first.click()

            # 4. une équipe avec des attentes : elles passent en premier, avec leurs boutons, le terminal reste atteignable
            ouvrir(pg, EQUIPE_AVEC_ATTENTE)
            t = titres(pg)
            verifier(f"{ecran} · {EQUIPE_AVEC_ATTENTE} : « Attend de toi » en premier, avant « Ses agents »", t[:2] == ["Attend de toi", "Ses agents"], str(t))
            boutons = pg.locator(".fiche .attente .bouton").all_inner_texts()
            verifier(f"{ecran} · {EQUIPE_AVEC_ATTENTE} : les boutons du rail (Autoriser, Refuser…)", "Autoriser" in boutons and "Refuser" in boutons, str(boutons))
            haut, _, _ = haut_terminal(pg)
            if ecran == "bureau":
                verifier(f"{ecran} · {EQUIPE_AVEC_ATTENTE} : le haut du terminal reste dans le premier écran", haut < hauteur, f"haut = {haut:.0f} px")
            else:
                print(f"INFO {ecran} · {EQUIPE_AVEC_ATTENTE} : le terminal commence à {haut:.0f} px (les attentes de l'utilisateur passent avant)")
            pg.screenshot(path=str(sorties / f"fiche-{EQUIPE_AVEC_ATTENTE}-{ecran}-entiere.png"), full_page=True)
            verifier(f"{ecran} · {EQUIPE_AVEC_ATTENTE} : pas de barre horizontale", pg.evaluate("document.documentElement.scrollWidth") <= largeur)

            # 5. une équipe clôturée : sa note, ses sections lisibles, pas de terminal
            pg.goto(f"{BASE}/#/equipe/cadrage")
            pg.wait_for_selector(".fiche .eq-tete")
            verifier(f"{ecran} · équipe clôturée : la note de clôture et pas de terminal",
                     "Équipe clôturée" in pg.locator(".eq-note").inner_text() and pg.locator(".terminal").count() == 0)
            verifier(f"{ecran} · équipe clôturée : pas de barre horizontale", pg.evaluate("document.documentElement.scrollWidth") <= largeur)
            pg.screenshot(path=str(sorties / f"fiche-cadrage-{ecran}-entiere.png"), full_page=True)
            pg.close()
        nav.close()

    verifier("aucune erreur JS ni avertissement de console", not erreurs, "; ".join(erreurs))
    print(f"\n{len(OK)} OK, {len(KO)} KO : {KO}")
    return 1 if KO else 0


if __name__ == "__main__":
    sortie = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    sortie.mkdir(parents=True, exist_ok=True)
    sys.exit(main(sortie))
