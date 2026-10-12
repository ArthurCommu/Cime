"""Vérifications navigateur de la scène dans le plateau, sur l'hôte réel ou le faux hôte.

Ce que pytest ne voit pas : la scène dessine (un canvas, `surPret` en moins de 1 s), un clic sur chaque pièce arrive
à la page et entoure la pièce, la légende s'ouvre et se ferme, les trois boutons zooment, la coupure du flux donne
l'état figé puis le retour sans recharger, l'écran « hôte injoignable » et son décompte, la console sans erreur, et
les captures à regarder (plateau en direct, légende ouverte, figé, injoignable) à 1440×900 et 390×844.

Usage (le faux hôte, `hote_factice.py`, doit tourner sur CIME_PORT_TEST ; il sert /scene/ et /api/flux?depuis=) :

    uv run --with playwright python tests/page/outils/scenario_plateau.py <dossier-captures>

La coupure passe par le réglage `flux=coupe` du faux hôte (le flux déjà ouvert est fermé) et par une route
interceptée (`/api/*` en échec) pour que la reconnexion échoue aussi. Sur l'hôte réel, seule la route interceptée
agit : la durée d'attente du flux muet (25 s) s'ajoute. Code de sortie 1 si une vérification échoue.
"""
import os
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

PORT = os.environ.get("CIME_PORT_TEST", "8791")
BASE = f"http://127.0.0.1:{PORT}"
CHROME = os.environ.get("CIME_CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
FAUX_HOTE = os.environ.get("CIME_HOTE_FACTICE", "oui") == "oui"
TAILLES = ((1440, 900), (390, 844))
OK, KO = [], []

# la photo du canvas : de quoi voir qu'il a changé (zoom, entourage) sans connaître les pixels
EMPREINTE = "(() => { const c = document.querySelector('#plateau canvas'); return c.toDataURL().length + ':' + c.toDataURL().slice(-64); })()"
CIBLE = "import('/static/vues/scene.js').then((m) => m.selectionCourante())"


def verifier(nom, cond, detail=""):
    (OK if cond else KO).append(nom)
    print(("OK  " if cond else "KO  ") + nom + (f" — {detail}" if detail else ""))


def regler(q):
    if FAUX_HOTE:
        urllib.request.urlopen(f"{BASE}/test/regler?{q}").read()


def cle(cible):
    return None if cible is None else f"{cible['type']}:{cible.get('nom') or cible.get('id') or ''}"


def balayer(pg):
    """Clique sur une grille de points du canvas et rend, par cible rencontrée, le premier point qui l'atteint."""
    boite = pg.locator("#plateau canvas").bounding_box()
    trouvees = {}
    pas = 8
    y = boite["y"] + pas
    while y < boite["y"] + boite["height"]:
        x = boite["x"] + pas
        while x < boite["x"] + boite["width"]:
            pg.mouse.click(x, y)
            cible = pg.evaluate(CIBLE)
            if cible is not None and cle(cible) not in trouvees:
                trouvees[cle(cible)] = (x, y)
            x += pas
        y += pas
    return trouvees


def capturer(pg, sorties, nom, largeur, hauteur):
    pg.screenshot(path=str(sorties / f"plateau-{nom}-{largeur}x{hauteur}.png"))


def main(sorties):
    erreurs = []
    ignores = ("Failed to load resource", "net::ERR", "EventSource", "Failed to fetch")
    with sync_playwright() as p:
        nav = p.chromium.launch(executable_path=CHROME, headless=True)
        ctx = nav.new_context(viewport={"width": 1440, "height": 900})
        pg = ctx.new_page()
        pg.on("console", lambda m: erreurs.append(m.text) if m.type in ("error", "warning") and not any(i in m.text for i in ignores) else None)
        pg.on("pageerror", lambda e: erreurs.append(str(e)))

        # 1. la scène dessine : un canvas dans le plateau, la silhouette disparaît en moins de 1 s
        pg.goto(f"{BASE}/#/")
        pg.wait_for_selector("#plateau")
        try:
            pg.wait_for_selector("#plateau canvas", timeout=3000)
            pg.wait_for_selector(".plateau-silhouette", state="detached", timeout=1000)
            pret = True
        except Exception as e:  # noqa: BLE001 — le détail va dans le rapport
            pret = False
            print(f"    (attente : {e})")
        verifier("la scène a dessiné (canvas présent, silhouette retirée en moins de 1 s)", pret)
        verifier("aucune phrase de repli : la scène est disponible", pg.locator(".plateau-calme").count() == 0)
        verifier("le plateau n'a qu'un seul canvas après plusieurs instantanés", (pg.wait_for_timeout(4000) or pg.locator("#plateau canvas").count()) == 1)
        capturer(pg, sorties, "direct", 1440, 900)

        # 2. un clic sur chaque pièce arrive à la page ; le vide remet la sélection à zéro ; Échap aussi
        trouvees = balayer(pg)
        equipes = sorted(c.split(":", 1)[1] for c in trouvees if c.startswith("equipe:"))
        attendues = pg.evaluate("fetch('/api/etat').then((r) => r.json()).then((e) => e.equipes.map((q) => q.nom).sort())")
        verifier("un clic atteint chaque pièce (une par équipe)", equipes == attendues, f"{equipes} / {attendues}")
        verifier("les clics atteignent aussi des agents ou la porte de l'utilisateur", any(c.startswith(("agent:", "utilisateur:")) for c in trouvees), str(sorted(trouvees)))
        scene_source = pg.evaluate("fetch('/scene/scene.js').then((r) => r.text())")
        if equipes:
            point = trouvees[f"equipe:{equipes[0]}"]
            pg.mouse.click(*point)
            avant = pg.evaluate(EMPREINTE)
            verifier("la page garde la sélection (selectionCourante)", cle(pg.evaluate(CIBLE)) == f"equipe:{equipes[0]}")
            pg.wait_for_timeout(300)
            apres = pg.evaluate(EMPREINTE)
            if "selectionner(" in scene_source:
                pg.mouse.click(point[0], point[1])  # le même clic : la sélection reste, l'entourage aussi
                pg.evaluate("document.querySelector('#plateau canvas').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))")
                pg.wait_for_timeout(300)
                verifier("Échap retire la sélection", pg.evaluate(CIBLE) is None)
                verifier("la pièce sélectionnée est entourée (le canvas change)", pg.evaluate(EMPREINTE) != avant or apres != avant)
            else:
                print("    (cette version de la scène n'a pas selectionner() : l'entourage n'est pas vérifié, fusion de equipe/scene attendue)")
                pg.evaluate("document.querySelector('#plateau canvas').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))")
                verifier("Échap retire la sélection", pg.evaluate(CIBLE) is None)
        pg.mouse.click(*(trouvees.get("equipe:" + equipes[0]) or (700, 450))) if equipes else None
        boite = pg.locator("#plateau canvas").bounding_box()
        pg.mouse.click(boite["x"] + 4, boite["y"] + 4)
        if "surVide" in scene_source:
            verifier("un clic dans le vide remet la sélection à zéro", pg.evaluate(CIBLE) is None)

        # 3. le survol : une info-bulle de la page, retirée quand on la quitte
        if equipes:
            pg.mouse.move(*trouvees[f"equipe:{equipes[0]}"])
            pg.mouse.move(trouvees[f"equipe:{equipes[0]}"][0] + 1, trouvees[f"equipe:{equipes[0]}"][1] + 1)
            pg.wait_for_timeout(200)
            verifier("survol : une info-bulle de la page (role=tooltip)", pg.locator(".infobulle-plateau[role=tooltip]").count() == 1)
            bulle = pg.locator(".infobulle-plateau").bounding_box()
            plateau = pg.locator("#plateau").bounding_box()
            verifier("l'info-bulle reste dans le plateau", bulle is not None and bulle["x"] >= plateau["x"] and bulle["x"] + bulle["width"] <= plateau["x"] + plateau["width"]
                     and bulle["y"] + bulle["height"] <= plateau["y"] + plateau["height"])
            pg.mouse.move(boite["x"] + 4, boite["y"] + 4)
            pg.wait_for_timeout(200)
            verifier("l'info-bulle est retirée hors d'une pièce", pg.locator(".infobulle-plateau").count() == 0)

        # 4. la légende : s'ouvre au-dessus du bouton, 300 px, se ferme au second clic et à Échap
        bouton = pg.get_by_role("button", name="Légende")
        verifier("le bouton Légende est en bas à gauche du plateau", bouton.bounding_box()["x"] < pg.locator("#plateau").bounding_box()["x"] + 60)
        verifier("la légende est fermée au départ", not pg.locator(".legende").is_visible())
        bouton.click()
        pg.wait_for_timeout(200)
        verifier("la légende s'ouvre", pg.locator(".legende").is_visible() and bouton.get_attribute("aria-expanded") == "true")
        zone = pg.locator(".legende").bounding_box()
        verifier("le panneau fait 300 px de large", round(zone["width"]) == 300, str(zone["width"]))
        verifier("il est au-dessus du bouton", zone["y"] + zone["height"] <= bouton.bounding_box()["y"] + 1)
        verifier("une ligne par entrée de la scène, avec son icône", pg.locator(".legende-ligne").count() > 8 and pg.locator(".legende-ligne canvas").count() == pg.locator(".legende-ligne").count())
        verifier("des intitulés de groupes", pg.locator(".legende-groupe h3").count() >= 2)
        rouges = pg.evaluate("[...document.querySelectorAll('.legende *')].filter((n) => getComputedStyle(n).color === 'rgb(232, 154, 145)').length")
        verifier("le rouge ne sert qu'aux signes de problème", rouges == pg.locator(".legende-probleme").count(), f"{rouges} rouges")
        capturer(pg, sorties, "legende", 1440, 900)
        bouton.click()
        verifier("le second clic la referme", not pg.locator(".legende").is_visible())
        bouton.click()
        pg.keyboard.press("Escape")
        verifier("Échap la referme", not pg.locator(".legende").is_visible())

        # 5. les trois boutons zooment (le canvas change), avec leur info-bulle
        titres = pg.locator(".commandes-zoom button").evaluate_all("(bs) => bs.map((b) => b.title)")
        verifier("trois boutons, leurs info-bulles", titres == ["Zoom arrière (−)", "Zoom avant (+)", "Tout voir (0)"], str(titres))
        taille = pg.locator(".commandes-zoom button").first.bounding_box()
        verifier("boutons de 32 px", round(taille["height"]) == 32 and round(taille["width"]) >= 32, str(taille))
        base = pg.evaluate(EMPREINTE)
        pg.get_by_role("button", name="Zoom avant (+)").click()
        pg.wait_for_timeout(400)
        zoome = pg.evaluate(EMPREINTE)
        verifier("« + » zoome", zoome != base)
        pg.get_by_role("button", name="Zoom arrière (−)").click()
        pg.get_by_role("button", name="Zoom arrière (−)").click()
        pg.wait_for_timeout(400)
        verifier("« − » dézoome", pg.evaluate(EMPREINTE) not in (zoome,))
        pg.get_by_role("button", name="Tout voir (0)").click()
        pg.wait_for_timeout(400)
        verifier("« tout voir » revient à la vue ajustée", pg.evaluate(EMPREINTE) == base)

        # 6. connexion perdue : désaturé, capsule rouge, retour sans recharger
        marque = pg.evaluate("window.__marque = 'x'")
        regler("flux=coupe")
        ctx.route("**/api/**", lambda route: route.abort())
        try:
            pg.wait_for_selector('#plateau[data-fige="oui"]', timeout=40000)
            fige = True
        except Exception:  # noqa: BLE001
            fige = False
        verifier("la connexion perdue marque le plateau (data-fige)", fige)
        if fige:
            pg.wait_for_timeout(2200)
            capsule = pg.locator(".capsule-figee")
            verifier("la capsule rouge dit l'image figée et l'hôte qui ne répond plus",
                     capsule.is_visible() and "Image figée depuis" in capsule.inner_text() and "l’hôte ne répond plus" in capsule.inner_text(), capsule.inner_text())
            verifier("elle est centrée en haut du plateau", abs((capsule.bounding_box()["x"] + capsule.bounding_box()["width"] / 2) - (pg.locator("#plateau").bounding_box()["x"] + pg.locator("#plateau").bounding_box()["width"] / 2)) < 3)
            verifier("le canvas est désaturé", pg.evaluate("getComputedStyle(document.querySelector('#plateau canvas')).filter") not in ("none", ""))
            ancien = capsule.inner_text()
            pg.wait_for_timeout(2200)
            verifier("la durée avance chaque seconde", capsule.inner_text() != ancien, f"{ancien} → {capsule.inner_text()}")
            verifier("pastille d'en-tête « Figé »", "Figé" in pg.locator(".age-donnee").inner_text())
            capturer(pg, sorties, "fige", 1440, 900)
        ctx.unroute("**/api/**")
        regler("flux=normal")
        try:
            pg.wait_for_selector('#plateau:not([data-fige])', timeout=40000)
            retour = True
        except Exception:  # noqa: BLE001
            retour = False
        verifier("le flux revenu, tout revient sans recharger", retour and pg.evaluate("window.__marque") == "x" and not pg.locator(".capsule-figee").is_visible())
        verifier("le canvas a perdu son filtre", pg.evaluate("getComputedStyle(document.querySelector('#plateau canvas')).filter") == "none")

        # 7. mobile : le plateau seul défile, jamais la page ; captures
        pg.set_viewport_size({"width": 390, "height": 844})
        pg.wait_for_timeout(600)
        verifier("390 px : pas de débordement horizontal de la page", pg.evaluate("document.documentElement.scrollWidth") <= 390)
        capturer(pg, sorties, "direct", 390, 844)
        pg.get_by_role("button", name="Légende").click()
        pg.wait_for_timeout(200)
        capturer(pg, sorties, "legende", 390, 844)
        zone = pg.locator(".legende").bounding_box()
        verifier("390 px : la légende tient dans le plateau", zone["x"] >= 0 and zone["x"] + zone["width"] <= 390)
        pg.keyboard.press("Escape")
        pg.set_viewport_size({"width": 1440, "height": 900})

        # 8. l'hôte injoignable au premier chargement : en-tête, carte, décompte
        for largeur, hauteur in TAILLES:
            autre = nav.new_context(viewport={"width": largeur, "height": hauteur})
            autre.route("**/api/**", lambda route: route.abort())
            q = autre.new_page()
            q.on("pageerror", lambda e: erreurs.append(str(e)))
            q.goto(f"{BASE}/#/")
            q.wait_for_selector(".injoignable-carte")
            if (largeur, hauteur) == TAILLES[0]:
                verifier("injoignable : l'en-tête de la page, sans onglets", q.locator(".entete .entete-appli").inner_text() == "Cime" and q.locator(".nav").count() == 0)
                verifier("injoignable : pastille rouge « Hôte injoignable »", "Hôte injoignable" in q.locator(".age-donnee").inner_text() and q.locator('.age-donnee[data-niveau="rouge"]').count() == 1)
                verifier("injoignable : la phrase", q.locator(".injoignable-phrase").inner_text() == "Cime n’arrive pas à joindre l’hôte.")
                verifier("injoignable : la phrase de fond dans l'info-bulle de la carte", "Rien n’est affiché tant que l’hôte ne répond pas" in q.locator(".injoignable-carte").get_attribute("title"))
                verifier("injoignable : ni bandeau ni pied", q.locator("footer").count() == 0 and q.locator(".bandeau").count() == 0)
                q.wait_for_timeout(300)
                a = q.locator(".injoignable-reessai").inner_text()
                q.wait_for_timeout(1100)
                b = q.locator(".injoignable-reessai").inner_text()
                verifier("injoignable : le décompte tourne chaque seconde", a.startswith("Nouvel essai dans") and a != b, f"{a} → {b}")
            q.wait_for_timeout(200)
            capturer(q, sorties, "injoignable", largeur, hauteur)
            verifier(f"injoignable {largeur} px : pas de débordement horizontal", q.evaluate("document.documentElement.scrollWidth") <= largeur)
            autre.close()

        # 9. scène absente : l'import peut échouer, une phrase calme, jamais d'erreur de console non attrapée
        sans_scene = nav.new_context(viewport={"width": 1440, "height": 900})
        sans_scene.route("**/scene/**", lambda route: route.fulfill(status=404, body="absent"))
        d = sans_scene.new_page()
        d.on("pageerror", lambda e: erreurs.append(str(e)))
        d.goto(f"{BASE}/#/")
        d.wait_for_selector(".plateau-calme")
        verifier("scène absente : une seule phrase calme", d.locator(".plateau-calme").inner_text() == "La scène n’est pas disponible ici." and d.locator("#plateau").evaluate("(n) => n.childElementCount") == 1)
        sans_scene.close()
        nav.close()

    verifier("aucune erreur JS ni avertissement de console (hors réseau coupé exprès)", not erreurs, "; ".join(erreurs))
    print(f"\n{len(OK)} OK, {len(KO)} KO : {KO}")
    return 1 if KO else 0


if __name__ == "__main__":
    sortie = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    sortie.mkdir(parents=True, exist_ok=True)
    sys.exit(main(sortie))
