"""Vérifications navigateur du rail de l'accueil et du détail au clic, sur le faux hôte (ou l'hôte réel).

Ce que pytest ne voit pas : le rail a ses quatre blocs et sa largeur de 344 px, la page ne défile pas à 1440×900, un clic sur
chacune des pièces, sur un agent, sur une enveloppe et sur la porte de l'utilisateur ouvre quelque chose dans le rail, « ← Retour »,
Échap (focus dans la scène ou dans le rail) et un clic dans le vide le referment, la coupure de l'hôte désactive les boutons
d'action, le rail passe sous le plateau à 390 px sans déborder, la console reste muette. Captures à regarder (calme, attentes,
détail d'une équipe, détail d'un agent) à 1440×900.

Usage (le faux hôte, `hote_factice.py`, doit tourner sur CIME_PORT_TEST ; il sert /scene/ et /api/flux?depuis=) :

    uv run --with playwright python tests/page/outils/scenario_rail.py <dossier-captures>

`CIME_HOTE_FACTICE=non` : l'hôte réel ; la coupure n'agit alors que par la route interceptée (+ 25 s d'attente du flux muet).
L'état « calme » (aucune attente) n'est vérifié que sur le faux hôte, réglé par `attentes=calme`.
Code de sortie 1 si une vérification échoue.
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
FAUX_HOTE = os.environ.get("CIME_HOTE_FACTICE", "oui") == "oui"
OK, KO = [], []
BLOCS = ["Ce qui t’attend", "Ce qui coince", "Qui travaille", "Derniers échanges"]
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
    """Clique sur une grille de points du canvas et rend, par cible rencontrée, le premier point qui l'atteint.

    Les points qui tombent sur « Légende » ou sur les boutons de zoom sont sautés : ce sont des boutons posés sur le canvas, et
    les cliquer ouvrait la légende (puis les clics suivants la refermaient une fois sur deux) ou changeait le zoom. Sinon
    la légende restait ouverte après le balayage, le premier Échap la refermait au lieu du
    détail, le rail restait en mode détail et « #rail .echange » n'existait pas.
    """
    boite = pg.locator("#plateau > canvas").bounding_box()
    interdits = pg.locator("#plateau .commande-plateau").evaluate_all(
        "(bs) => bs.map((b) => { const r = b.getBoundingClientRect(); return [r.left - 8, r.top - 8, r.right + 8, r.bottom + 8]; })")
    trouvees = {}
    pas = 8
    y = boite["y"] + pas
    while y < boite["y"] + boite["height"]:
        x = boite["x"] + pas
        while x < boite["x"] + boite["width"]:
            if any(g <= x <= d and h <= y <= b for g, h, d, b in interdits):
                x += pas
                continue
            pg.mouse.click(x, y)
            cible = pg.evaluate(CIBLE)
            if cible is not None and cle(cible) not in trouvees:
                trouvees[cle(cible)] = (x, y)
            x += pas
        y += pas
    return trouvees


def etat_attendu(pg):
    """L'instantané que la page affiche : celui de l'hôte."""
    return pg.evaluate("""fetch('/api/etat').then((r) => { if (!r.ok) throw 0; return r.json(); })""")


def detail(pg):
    return pg.locator("#rail .detail-rail")


def ferme(pg):
    return detail(pg).count() == 0 and pg.evaluate(CIBLE) is None


def sans_defilement(pg, largeur, hauteur):
    pg.wait_for_timeout(300)
    d = pg.evaluate("({ h: document.documentElement.scrollHeight, w: document.documentElement.scrollWidth })")
    return d["h"] <= hauteur and d["w"] <= largeur, str(d)


def parcourir(nav, nom, url, sorties, erreurs):
    ctx = nav.new_context(viewport={"width": 1440, "height": 900})
    pg = ctx.new_page()
    pg.on("console", lambda m: erreurs.append(f"{nom}: {m.text}") if m.type in ("error", "warning") and not any(
        i in m.text for i in ("Failed to load resource", "net::ERR", "EventSource", "Failed to fetch")) else None)
    pg.on("pageerror", lambda e: erreurs.append(f"{nom}: {e}"))

    def capturer(sujet):
        pg.screenshot(path=str(sorties / f"rail-{nom}-{sujet}-1440x900.png"))

    pg.goto(url)
    pg.wait_for_selector("#rail .bloc-rail")
    pg.wait_for_selector("#plateau > canvas", timeout=3000)
    pg.wait_for_timeout(500)

    # 1. le rail : quatre blocs dans l'ordre, 344 px, la page ne défile pas, le rail défile seul s'il déborde
    blocs = pg.locator("#rail .bloc-rail").evaluate_all("(bs) => bs.map((b) => b.getAttribute('aria-label'))")
    verifier(f"{nom} : le rail a ses quatre blocs, dans l'ordre", blocs == BLOCS, str(blocs))
    boite = pg.locator("#rail").bounding_box()
    verifier(f"{nom} : le rail fait 344 px de large", round(boite["width"]) == 344, str(boite["width"]))
    verifier(f"{nom} : le rail est à droite du plateau", boite["x"] >= pg.locator("#plateau").bounding_box()["x"] + pg.locator("#plateau").bounding_box()["width"])
    ok, d = sans_defilement(pg, 1440, 900)
    verifier(f"{nom} : aucune barre de défilement de page à 1440×900", ok, d)
    verifier(f"{nom} : au plus trois cartes d'attente", pg.locator("#rail .bloc-rail >> nth=0 >> .attente").count() <= 3)
    verifier(f"{nom} : au plus trois lignes qui coincent", pg.locator("#rail .bloc-rail >> nth=1 >> .rail-ligne").count() <= 3)
    verifier(f"{nom} : au plus trois échanges", pg.locator("#rail .bloc-rail >> nth=3 >> .echange").count() <= 3)
    verifier(f"{nom} : le rail défile seul (la page, non)", pg.evaluate("getComputedStyle(document.getElementById('rail')).overflowY") == "auto")
    if pg.locator("#rail .lien-autres").count():
        verifier(f"{nom} : « n autres points ▾ » est un bouton replié, qui déplie la liste complète dans le rail puis la replie",
                 pg.locator("#rail .lien-autres").evaluate("(n) => n.tagName") == "BUTTON"
                 and pg.locator("#rail .lien-autres").get_attribute("aria-expanded") == "false")
        avant = pg.locator("#rail .bloc-rail >> nth=0 >> .attente").count()
        pg.locator("#rail .lien-autres").click()
        deplie = pg.locator("#rail .bloc-rail >> nth=0 >> .attente").count()
        verifier(f"{nom} : dépliées, plus de cartes qu'en tête (« replier ▴ » proposé)",
                 deplie > avant and "replier" in pg.locator("#rail .lien-autres").inner_text(), f"{avant} → {deplie}")
        pg.locator("#rail .lien-autres").click()
        verifier(f"{nom} : replié, trois cartes de nouveau", pg.locator("#rail .bloc-rail >> nth=0 >> .attente").count() == avant)
    verifier(f"{nom} : rien de rouge hors alarme grave (étiquettes, compteurs, liens)",
             pg.evaluate("[...document.querySelectorAll('#rail .etiquette, #rail .compte, #rail .lien-autres, #rail .lien-bloc')].filter((n) => getComputedStyle(n).color === 'rgb(232, 154, 145)').length") == 0)
    capturer("attentes")

    # 2. un clic sur chaque pièce, sur un agent, sur la porte de l'utilisateur : quelque chose s'ouvre dans le rail
    trouvees = balayer(pg)
    pg.locator("#plateau .commande-legende").click()
    verifier(f"{nom} : « Légende » ouvre la légende", pg.locator("#legende-plateau").is_visible())
    # le premier point trouvé peut tomber sous la légende ouverte : on clique hors d'elle, pour que le clic atteigne la scène
    lg = pg.locator("#legende-plateau").bounding_box()
    hors = next(p for p in trouvees.values() if not (lg["x"] <= p[0] <= lg["x"] + lg["width"] and lg["y"] <= p[1] <= lg["y"] + lg["height"]))
    pg.mouse.click(*hors)
    pg.wait_for_timeout(150)
    verifier(f"{nom} : un clic dans la scène referme la légende", not pg.locator("#legende-plateau").is_visible())
    pg.locator("#plateau .commande-legende").click()
    pg.locator("#plateau > canvas").click(position={"x": 4, "y": 4})
    pg.wait_for_timeout(150)
    verifier(f"{nom} : un clic dans le vide referme aussi la légende", not pg.locator("#legende-plateau").is_visible())
    verifier(f"{nom} : la légende est fermée avant les Échap qui suivent", not pg.locator("#legende-plateau").is_visible())
    equipes = sorted(c.split(":", 1)[1] for c in trouvees if c.startswith("equipe:"))
    attendues = sorted(q["nom"] for q in etat_attendu(pg)["equipes"])
    verifier(f"{nom} : un clic atteint chaque pièce (une par équipe)", equipes == attendues, f"{equipes} / {attendues}")
    detail_equipe_fait = False
    for e in equipes:
        pg.mouse.click(*trouvees[f"equipe:{e}"])
        pg.wait_for_timeout(150)
        verifier(f"{nom} : clic sur la pièce « {e} » → son détail dans le rail",
                 detail(pg).count() == 1 and detail(pg).locator("h2").inner_text() == e and cle(pg.evaluate(CIBLE)) == f"equipe:{e}")
        if not detail_equipe_fait:
            verifier(f"{nom} : le détail d'équipe a son statut, ses deux chiffres et la fiche complète",
                     detail(pg).locator(".puce-statut").count() == 1 and detail(pg).locator(".detail-chiffre").count() == 2
                     and detail(pg).locator("a.bouton-lien").get_attribute("href") == f"#/equipe/{e}")
            ok, d = sans_defilement(pg, 1440, 900)
            verifier(f"{nom} : le détail ne fait pas défiler la page", ok, d)
            capturer("detail-equipe")
            detail_equipe_fait = True
        detail(pg).locator("button.retour").click()
        verifier(f"{nom} : « ← Retour » referme le détail de « {e} »", ferme(pg))
    agents = [c for c in trouvees if c.startswith("agent:")]
    verifier(f"{nom} : les clics atteignent au moins un agent", bool(agents), str(sorted(trouvees)))
    if agents:
        pg.mouse.click(*trouvees[agents[0]])
        pg.wait_for_timeout(150)
        verifier(f"{nom} : clic sur un agent → son détail (contexte, modèle, dettes, file, fiche de l'équipe)",
                 detail(pg).count() == 1 and "Contexte" in detail(pg).inner_text() and "Dettes" in detail(pg).inner_text()
                 and "File" in detail(pg).inner_text(), detail(pg).inner_text()[:80] if detail(pg).count() else "rien")
        capturer("detail-agent")
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(150)
        verifier(f"{nom} : Échap (focus dans la scène) referme le détail de l'agent", ferme(pg))
        ferme_ou_echoue = ferme(pg)
        if not ferme_ou_echoue:
            raise SystemExit("le rail est encore en détail : les étapes suivantes (« #rail .echange ») n'ont plus de sens")
    messages = [c for c in trouvees if c.startswith("message:")]
    if messages:
        pg.mouse.click(*trouvees[messages[0]])
        pg.wait_for_timeout(150)
        verifier(f"{nom} : clic sur une enveloppe → le message (de → à, nature, résumé, livraison, « Voir dans le fil → »)",
                 detail(pg).count() == 1 and "Voir dans le fil" in detail(pg).inner_text())
        detail(pg).locator("button.retour").click()
    else:
        print("    (aucune enveloppe en transit dans cet état : on passe par la ligne du bloc « Derniers échanges »)")
    pg.locator("#rail .echange").first.click()
    pg.wait_for_timeout(150)
    verifier(f"{nom} : clic sur un échange du rail → le message dans le détail",
             detail(pg).count() == 1 and "Voir dans le fil" in detail(pg).inner_text() and (pg.evaluate(CIBLE) or {}).get("type") == "message")
    pg.keyboard.press("Escape")  # le focus est dans le rail : l'écouteur du document ferme
    pg.wait_for_timeout(150)
    verifier(f"{nom} : Échap (focus dans le rail) referme le détail du message", ferme(pg))
    if pg.locator("#rail button.rail-ligne").count():
        pg.locator("#rail button.rail-ligne").first.click()
        pg.wait_for_timeout(150)
        verifier(f"{nom} : clic sur un agent de « Qui travaille » → son détail", detail(pg).count() == 1 and (pg.evaluate(CIBLE) or {}).get("type") == "agent")
        pg.locator("#plateau > canvas").click(position={"x": 4, "y": 4})
        pg.wait_for_timeout(150)
        verifier(f"{nom} : un clic dans le vide referme ce détail", ferme(pg))
    portes = [c for c in trouvees if c.startswith("utilisateur:")]
    verifier(f"{nom} : les clics atteignent la porte de l'utilisateur", bool(portes))
    if portes:
        pg.mouse.click(*trouvees[portes[0]])
        pg.wait_for_timeout(150)
        verifier(f"{nom} : clic sur la porte de l'utilisateur → « Ce qui t'attend » clignote, pas de détail",
                 detail(pg).count() == 0 and pg.locator("#rail .bloc-rail.clignote").count() == 1)
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(150)
        verifier(f"{nom} : Échap retire la sélection de la porte", pg.evaluate(CIBLE) is None)

    # 3. le détail se met à jour sur place : un instantané ne le ferme pas
    if equipes:
        pg.mouse.click(*trouvees[f"equipe:{equipes[0]}"])
        pg.wait_for_timeout(150)
        avant = detail(pg).locator("h2").inner_text()
        pg.wait_for_timeout(6000)
        verifier(f"{nom} : le détail reste ouvert (et le rail ne saute pas) après des instantanés",
                 detail(pg).count() == 1 and detail(pg).locator("h2").inner_text() == avant)
        detail(pg).locator("button.retour").click()
        if pg.evaluate("document.getElementById('rail').scrollHeight > document.getElementById('rail').clientHeight"):
            pg.locator("#rail").evaluate("(r) => { r.scrollTop = 60; }")
            pg.wait_for_timeout(2500)
            verifier(f"{nom} : la position de défilement du rail est gardée entre deux instantanés", pg.evaluate("document.getElementById('rail').scrollTop") >= 40)
        else:
            print("    (le rail ne déborde pas à 1440×900 : la position de défilement n'est pas vérifiée)")

    # 4. mobile (le détail complet est dans scenario_mobile.py) : le rail passe sous le plateau, sans déborder
    pg.set_viewport_size({"width": 390, "height": 844})
    pg.wait_for_timeout(500)
    verifier(f"{nom} : 390 px : le rail est sous le plateau", pg.locator("#rail").bounding_box()["y"] >= pg.locator("#plateau").bounding_box()["y"] + pg.locator("#plateau").bounding_box()["height"] - 1)
    verifier(f"{nom} : 390 px : pas de débordement horizontal de la page", pg.evaluate("document.documentElement.scrollWidth") <= 390)
    pg.set_viewport_size({"width": 1440, "height": 900})
    pg.wait_for_timeout(300)

    # 5. l'état « calme » (faux hôte seulement) : aucune attente, bandeau vert, pas de bloc « Ce qui coince »
    if nom == "hote" and FAUX_HOTE:
        regler("attentes=calme")
        calme = nav.new_context(viewport={"width": 1440, "height": 900})
        q = calme.new_page()
        q.on("pageerror", lambda e: erreurs.append(f"calme: {e}"))
        q.goto(url)
        q.wait_for_selector("#rail .bloc-rail")
        q.wait_for_timeout(800)
        verifier("calme : « Rien ne t'attend. Tout avance sans toi. » en bandeau vert", "Rien ne t’attend. Tout avance sans toi." in q.locator("#rail .rail-calme").inner_text())
        verifier("calme : pas de bloc « Ce qui coince »", "Ce qui coince" not in q.locator("#rail .bloc-rail").evaluate_all("(bs) => bs.map((b) => b.getAttribute('aria-label'))"))
        verifier("calme : pas de compteur d'attentes dans l'en-tête", q.locator(".compteur-attentes").count() == 0)
        verifier("calme : aucun élément rouge visible à l'écran — texte, fond ou liseré ; un agent arrêté sans alarme est « à l’arrêt », gris, et une source en échec grise (les éléments cachés — capsule figée, libellés « problème » de la légende fermée — ne comptent pas)", q.evaluate("[...document.querySelectorAll('body *')].filter((n) => { if (!n.checkVisibility()) return false; const c = getComputedStyle(n); return ['rgb(217, 106, 95)', 'rgb(232, 154, 145)'].includes(c.color) || ['rgb(217, 106, 95)', 'rgb(44, 29, 28)'].includes(c.backgroundColor) || ['rgb(217, 106, 95)', 'rgb(69, 47, 44)'].includes(c.borderLeftColor); }).length") == 0)
        q.screenshot(path=str(sorties / "rail-calme-1440x900.png"))
        calme.close()
        regler("attentes=normales")
        pg.reload()
        pg.wait_for_selector("#rail .bloc-rail")

    # 6. le compteur de l'en-tête sur les autres écrans : en clair, ambre, vers la scène ; plus de bandeau
    pg.goto(url.split("#")[0] + "#/supervision")
    pg.wait_for_selector(".organigramme")
    compteur = pg.locator(".compteur-attentes")
    verifier(f"{nom} : Supervision : le compteur dit « n points t'attendent » en clair, vers #/",
             compteur.count() == 1 and "attend" in compteur.inner_text() and compteur.get_attribute("href") == "#/", compteur.inner_text() if compteur.count() else "absent")
    verifier(f"{nom} : Supervision : plus de bandeau « Ce qui t'attend »", pg.locator(".bandeau").count() == 0)
    pg.goto(url.split("#")[0] + "#/fil")
    pg.wait_for_selector(".fil-page")
    verifier(f"{nom} : Fil : plus de bandeau non plus", pg.locator(".bandeau").count() == 0)
    ctx.close()


def coupure(nav, sorties, erreurs):
    """Image figée : les boutons d'action du rail sont désactivés, avec leur explication ; ils reviennent avec l'hôte."""
    ctx = nav.new_context(viewport={"width": 1440, "height": 900})
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: erreurs.append(f"coupure: {e}"))
    pg.goto(f"{BASE}/#/")
    pg.wait_for_selector("#rail .attente")
    verifier("coupure : avant, des boutons d'action actifs", pg.locator("#rail .attente-actions button:not(:disabled)").count() > 0)
    regler("flux=coupe")
    ctx.route("**/api/**", lambda route: route.abort())
    try:
        pg.wait_for_selector('#plateau[data-fige="oui"]', timeout=40000)
        fige = True
    except Exception:  # noqa: BLE001
        fige = False
    verifier("coupure : l'image se fige", fige)
    if fige:
        pg.wait_for_timeout(500)
        boutons = pg.locator("#rail .attente-actions button, #rail .attente-actions input")
        verifier("coupure : tous les boutons d'action du rail sont désactivés",
                 boutons.count() > 0 and pg.locator("#rail .attente-actions button:not(:disabled), #rail .attente-actions input:not(:disabled)").count() == 0)
        verifier("coupure : leur explication « L'hôte ne répond plus »", boutons.first.get_attribute("title") == "L’hôte ne répond plus")
        pg.screenshot(path=str(sorties / "rail-fige-1440x900.png"))
    ctx.unroute("**/api/**")
    regler("flux=normal")
    try:
        pg.wait_for_selector('#plateau:not([data-fige])', timeout=40000)
        retour = True
    except Exception:  # noqa: BLE001
        retour = False
    verifier("coupure : l'hôte revenu, les boutons redeviennent actifs", retour and pg.locator("#rail .attente-actions button:not(:disabled)").count() > 0)
    ctx.close()


def main(sorties):
    erreurs = []
    with sync_playwright() as p:
        nav = p.chromium.launch(executable_path=CHROME, headless=True)
        parcourir(nav, "hote", f"{BASE}/#/", sorties, erreurs)
        coupure(nav, sorties, erreurs)
        nav.close()
    verifier("aucune erreur JS ni avertissement de console (hors réseau coupé exprès)", not erreurs, "; ".join(erreurs))
    print(f"\n{len(OK)} OK, {len(KO)} KO : {KO}")
    return 1 if KO else 0


if __name__ == "__main__":
    sortie = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    sortie.mkdir(parents=True, exist_ok=True)
    sys.exit(main(sortie))
