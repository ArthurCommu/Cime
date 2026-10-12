"""Vérifications navigateur de la consommation de jetons, contre hote_factice.py.

Ce que pytest ne peut pas voir (il n'exécute pas le JS) : les bornes de `jetons`, la section
« Consommation » rendue, la carte d'agent et la grille de la page d'équipe, l'absence de débordement
à 390 px, et les captures à regarder. Usage (le faux hôte doit tourner sur CIME_PORT_TEST) :

    uv run --with playwright python tests/page/outils/scenario_consommation.py <dossier-captures>

Code de sortie 1 si une vérification échoue. Les captures sont écrites dans le dossier donné.
"""
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PORT = os.environ.get("CIME_PORT_TEST", "8791")
BASE = f"http://127.0.0.1:{PORT}"
CHROME = os.environ.get("CIME_CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
NBSP = " "
OK, KO = [], []


def verifier(nom, cond, detail=""):
    (OK if cond else KO).append(nom)
    print(("OK  " if cond else "KO  ") + nom + (f" — {detail}" if detail else ""))


# Valeurs de jetons attendues, évaluées par le module de la page (bornes 999 / 1 000 / 999 999 / 1 000 000).
ATTENDU = [
    (999, "999"),
    (1000, "1 k"),
    (999999, "999 k"),
    (1000000, "1,0 M"),
    (812, "812"),
    (12000, "12 k"),
    (4300000, "4,3 M"),
]


def main(sorties):
    erreurs = []
    with sync_playwright() as p:
        nav = p.chromium.launch(executable_path=CHROME, headless=True)
        pg = nav.new_page(viewport={"width": 1440, "height": 1000})
        pg.on("console", lambda m: erreurs.append(m.text) if m.type in ("error", "warning") else None)
        pg.on("pageerror", lambda e: erreurs.append(str(e)))

        # 1. fonctions pures, évaluées dans la page
        pg.goto(f"{BASE}/#/supervision")
        pg.wait_for_selector("#consommation")
        bornes = pg.evaluate("""async () => {
            const m = await import('/static/commun.js');
            return { jetons: [999, 1000, 999999, 1000000, 812, 12000, 4300000, null, undefined, 'x']
                .map((n) => m.jetons(n)), pourcent: m.pourcent(0.31) };
        }""")
        for i, (nombre, attendu) in enumerate(ATTENDU):
            verifier(f"jetons({nombre}) = « {attendu} »", bornes["jetons"][i] == attendu, repr(bornes["jetons"][i]))
        verifier("jetons(null), jetons(undefined), jetons('x') : null (inconnu, jamais 0)",
                 bornes["jetons"][7] is None and bornes["jetons"][8] is None and bornes["jetons"][9] is None)
        verifier("pourcent(0.31) = « 31 » + espace insécable + « % »", bornes["pourcent"] == f"31{NBSP}%", repr(bornes["pourcent"]))

        # 2. vue d'ensemble : section après Alarmes, deux fenêtres, gros postes, barres neutres
        section = pg.locator("#consommation")
        texte = section.text_content()  # inner_text transformerait le titre (majuscules CSS)
        verifier("section Consommation présente", section.count() == 1)
        verifier("fenêtre 15 dernières min", "15 dernières min : 8,0 M lus" in texte, texte[:160].replace("\n", " | "))
        verifier("fenêtre 60 dernières min", "60 dernières min : 21,9 M lus" in texte)
        verifier("gros postes (15 min) titre", "Gros postes (15 min)" in texte)
        postes = section.locator(".conso-poste")
        verifier("cinq gros postes", postes.count() == 5, str(postes.count()))
        premier = postes.nth(0).inner_text()
        verifier("premier gros poste : observation, 3,4 M, 42 %",
                 "observation" in premier and "3,4 M" in premier and f"42{NBSP}%" in premier, premier.replace("\n", " | "))
        verifier("lien vers l'équipe du gros poste", postes.nth(0).locator("a").count() == 1)
        couleur = pg.evaluate("getComputedStyle(document.querySelector('#consommation .conso-plein')).backgroundColor")
        verifier("barre neutre : gris (--gris), ni vert ni rouge",
                 section.locator(".conso-plein").count() == 5 and couleur == "rgb(140, 136, 128)", couleur)
        ordre = pg.evaluate("[...document.querySelectorAll('#alarmes, #consommation, #sessions-orphelines')].map((n) => n.id)")
        verifier("ordre : alarmes, consommation, sessions hors organigramme",
                 ordre == ["alarmes", "consommation", "sessions-orphelines"], str(ordre))

        # 3. carte d'agent : ligne discrète, sous-agents, « conso inconnue » sans transcript, rien pour l'utilisateur
        ligne = pg.locator(".agent[data-agent='coord-observation'] .conso-ligne").inner_text()
        verifier("carte coord-observation : conso avec sous-agents",
                 ligne == "conso 15 min : 3,4 M lus (dont 1,7 M sous-agents) · 60 min : 8,9 M lus", ligne)
        verifier("carte sans transcript : conso inconnue",
                 pg.locator(".agent[data-agent='worker-hote-serveur'] .conso-ligne").inner_text() == "conso inconnue")
        verifier("carte utilisateur : aucune ligne de conso", pg.locator(".agent[data-agent='utilisateur'] .conso-ligne").count() == 0)

        # 4. page d'équipe : grille à deux colonnes ; une valeur absente reste « inconnu », jamais 0
        pg.goto(f"{BASE}/#/equipe/observation")
        pg.wait_for_selector(".conso-grille")
        grille = pg.locator(".agent[data-agent='coord-observation'] .conso-grille").inner_text()
        verifier("grille : écrits, tours, contexte moyen",
                 all(m in grille for m in ("écrits", "tours", "contexte moyen")), grille.replace("\n", " | "))
        pg.goto(f"{BASE}/#/equipe/fondation")
        pg.wait_for_selector(".conso-grille")
        fondation = pg.locator(".agent[data-agent='coord-fondation'] .conso-grille")
        verifier("grille : contexte moyen « inconnu » quand aucune réponse principale sur 15 min (jamais 0)",
                 fondation.count() == 1 and "inconnu" in fondation.inner_text(),
                 fondation.inner_text().replace("\n", " | ") if fondation.count() else "absente")

        # 5. largeurs : aucun débordement, captures à regarder
        for largeur in (1440, 390):
            pg.set_viewport_size({"width": largeur, "height": 1000})
            pg.goto(f"{BASE}/#/supervision")
            pg.wait_for_selector("#consommation")
            pg.wait_for_timeout(300)
            debordement = pg.evaluate("document.documentElement.scrollWidth")
            verifier(f"vue d'ensemble : pas de débordement à {largeur} px", debordement <= largeur, f"scrollWidth={debordement}")
            pg.locator("#consommation").screenshot(path=str(sorties / f"consommation-{largeur}.png"))
            pg.screenshot(path=str(sorties / f"ensemble-{largeur}.png"), full_page=True)
            pg.goto(f"{BASE}/#/equipe/observation")
            pg.wait_for_selector(".conso-grille")
            pg.wait_for_timeout(300)
            debordement = pg.evaluate("document.documentElement.scrollWidth")
            verifier(f"page d'équipe : pas de débordement à {largeur} px", debordement <= largeur, f"scrollWidth={debordement}")
            pg.locator(".agent[data-agent='coord-observation']").screenshot(path=str(sorties / f"carte-agent-{largeur}.png"))
        nav.close()

    verifier("aucune erreur JS ni avertissement de console", not erreurs, "; ".join(erreurs))
    print(f"\n{len(OK)} OK, {len(KO)} KO : {KO}")
    return 1 if KO else 0


if __name__ == "__main__":
    sortie = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    sys.exit(main(sortie))
