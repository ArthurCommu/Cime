"""Vérifications navigateur de l'accueil sur téléphone à 390×844, sur le faux hôte (ou l'hôte réel).

Ce que pytest ne voit pas : l'en-tête de 52 px sur une seule ligne (marque et projet, pastille « En direct », ⚠ s'il y en a, bouton
carré à icône de 40×40), la barre d'onglets du bas (64 px, fixe, trois onglets, sans chevauchement avec la fin de chaque écran), le
bandeau d'attentes (ambre ou vert, 44 px), le plateau de 540 px avec « Légende » et le zoom au-dessus de la ligne de flottaison,
aucune barre de défilement horizontale de page, le bandeau → la feuille des attentes (ouvrir, agir sans fermer, fermer par la poignée,
par « Fermer » et par Échap), le toucher d'une pièce, d'un agent et de la porte de l'utilisateur → la feuille de détail à 70 % (fermée par
Échap, « Fermer », le voile), la légende qui tient dans la largeur et que le clic dans la scène referme, l'état figé et l'hôte
injoignable à 390 px, le toast d'une action (visible, au-dessus de la barre d'onglets, sans cadre clair, sans recouvrir les boutons de la carte
actionnée), la console muette. Captures à regarder : accueil calme, attentes, détail, Supervision, Fil.

Usage (le faux hôte, `hote_factice.py`, doit tourner sur CIME_PORT_TEST ; il sert /scene/ et /api/flux?depuis=) :

    uv run --with playwright python tests/page/outils/scenario_mobile.py <dossier-captures>

`CIME_HOTE_FACTICE=non` : l'hôte réel ; les parties qui règlent le faux hôte (coupure, panne) sont alors sautées.
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
LARGEUR, HAUTEUR = 390, 844
OK, KO = [], []
CIBLE = "import('/static/vues/scene.js').then((m) => m.selectionCourante())"
FEUILLE_DETAIL = "dialog.feuille-montante[open]"
FEUILLE_ATTENTES = "dialog.feuille-plein[open]"
IGNORES = ("Failed to load resource", "net::ERR", "EventSource", "Failed to fetch")


def verifier(nom, cond, detail=""):
    (OK if cond else KO).append(nom)
    print(("OK  " if cond else "KO  ") + nom + (f" — {detail}" if detail else ""))


def regler(q):
    if FAUX_HOTE:
        urllib.request.urlopen(f"{BASE}/test/regler?{q}").read()


def boite(pg, selecteur):
    return pg.locator(selecteur).first.bounding_box()


def compter_attentes(pg):
    """Le nombre d'attentes de l'utilisateur, relu à l'instant dans l'état servi (il change quand on agit)."""
    return len(pg.evaluate("fetch('/api/etat').then((r) => r.json()).then((e) => e.attentes_utilisateur)"))


def visible(pg, selecteur):
    return pg.locator(selecteur).count() > 0 and pg.locator(selecteur).first.is_visible()


def cle(cible):
    return None if cible is None else f"{cible['type']}:{cible.get('nom') or cible.get('id') or ''}"


def sans_debordement(pg):
    pg.wait_for_timeout(300)
    d = pg.evaluate("({ w: document.documentElement.scrollWidth, h: document.documentElement.scrollHeight })")
    return d["w"] <= LARGEUR, str(d)


def fin_au_dessus_de_la_barre(pg):
    """Le bas de la page défilée au maximum : la fin du contenu ne passe pas sous la barre fixe."""
    pg.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
    pg.wait_for_timeout(200)
    r = pg.evaluate("""() => {
        const barre = document.querySelector('.barre-onglets').getBoundingClientRect().top;
        const bas = Math.max(...[...document.querySelector('.page-contenu').children].map((c) => c.getBoundingClientRect().bottom));
        return { barre, bas };
    }""")
    pg.evaluate("window.scrollTo(0, 0)")
    return r["bas"] <= r["barre"] + 0.5, str(r)


def zones_interdites(pg):
    """Les boutons posés sur le canvas (Légende, zoom) : un balayage ne doit pas les cliquer."""
    return pg.locator("#plateau .commande-plateau").evaluate_all(
        "(bs) => bs.map((b) => { const r = b.getBoundingClientRect(); return [r.left - 8, r.top - 8, r.right + 8, r.bottom + 8]; })")


def balayer(pg, voulus, pas=14):
    """Touche une grille de points du canvas ; rend, par type voulu, le premier point qui atteint une cible de ce type.

    Une feuille de détail s'ouvre à chaque cible touchée : Échap la referme avant le point suivant (le point trouvé est gardé)."""
    zone = pg.locator("#plateau > canvas").bounding_box()
    interdits = zones_interdites(pg)
    trouvees = {}
    y = zone["y"] + pas
    while y < zone["y"] + zone["height"] and not set(voulus) <= set(trouvees):
        x = zone["x"] + pas
        while x < zone["x"] + zone["width"]:
            if not any(g <= x <= d and h <= y <= b for g, h, d, b in interdits):
                pg.mouse.click(x, y)
                cible = pg.evaluate(CIBLE)
                if cible is not None:
                    if cible["type"] in voulus and cible["type"] not in trouvees:
                        trouvees[cible["type"]] = (x, y)
                    pg.keyboard.press("Escape")
                    pg.wait_for_timeout(80)
            x += pas
        y += pas
    return trouvees


def glisser(pg, dx):
    """Fait glisser la scène (le plateau, jamais la page) de dx pixels vers la gauche."""
    zone = pg.locator("#plateau > canvas").bounding_box()
    y = zone["y"] + zone["height"] / 2
    pg.mouse.move(zone["x"] + zone["width"] - 20, y)
    pg.mouse.down()
    pg.mouse.move(zone["x"] + zone["width"] - 20 - dx, y, steps=8)
    pg.mouse.up()
    pg.wait_for_timeout(200)


def ouvre_la_feuille_des_attentes(pg):
    pg.locator(".bandeau-attentes").click()
    pg.wait_for_selector(FEUILLE_ATTENTES, timeout=3000)


def parcourir(nav, nom, url, sorties, erreurs):
    ctx = nav.new_context(viewport={"width": LARGEUR, "height": HAUTEUR}, has_touch=True)
    pg = ctx.new_page()
    pg.on("console", lambda m: erreurs.append(f"{nom}: {m.text}") if m.type in ("error", "warning") and not any(i in m.text for i in IGNORES) else None)
    pg.on("pageerror", lambda e: erreurs.append(f"{nom}: {e}"))

    def capturer(sujet):
        pg.screenshot(path=str(sorties / f"mobile-{nom}-{sujet}-{LARGEUR}x{HAUTEUR}.png"))

    pg.goto(url)
    pg.wait_for_selector(".entete")
    pg.wait_for_selector("#plateau > canvas", timeout=4000)
    pg.wait_for_selector(".bandeau-attentes")
    pg.wait_for_timeout(600)

    # 1. l'en-tête : 52 px, une seule ligne, le bouton carré à icône
    entete = boite(pg, ".entete")
    verifier(f"{nom} : l'en-tête fait 52 px", round(entete["height"]) == 52, str(entete["height"]))
    verifier(f"{nom} : l'en-tête tient sur une ligne (rien ne déborde, rien ne passe dessous)",
             pg.evaluate("(() => { const e = document.querySelector('.entete'); return e.scrollHeight <= e.clientHeight && e.scrollWidth <= e.clientWidth; })()"))
    verifier(f"{nom} : « Cime » et le projet à gauche", pg.locator(".entete-titres").inner_text().startswith("Cime"))
    # la pastille se remplit au premier tic : on attend que son texte soit là plutôt que de la lire trop tôt
    try:
        pg.wait_for_function("() => { const n = document.querySelector('.age-donnee'); return n && n.innerText.includes('En direct'); }", timeout=5000)
    except Exception:
        pass  # la lecture ci-dessous échoue alors avec le texte réellement affiché
    verifier(f"{nom} : la pastille « En direct » sur la même ligne", visible(pg, ".age-donnee") and "En direct" in pg.locator(".age-donnee").inner_text()
             and abs(boite(pg, ".age-donnee")["y"] - boite(pg, ".entete-titres")["y"]) < 30)
    verifier(f"{nom} : les onglets, les effectifs et le compteur ont quitté l'en-tête",
             not visible(pg, ".entete .nav") and not visible(pg, ".entete .compteur-attentes") and not visible(pg, ".entete-etat .pilule:not(.age-donnee)"))
    b = boite(pg, "button.demander")
    verifier(f"{nom} : le bouton « Demander à l'Assistant » est un carré de 40×40", round(b["width"]) == 40 and round(b["height"]) == 40, str(b))
    verifier(f"{nom} : il porte une icône et aucun texte visible", pg.locator("button.demander svg").count() == 1 and pg.locator("button.demander").inner_text().strip() == "")
    verifier(f"{nom} : libellé et info-bulle inchangés (la phrase de hiérarchie)",
             pg.locator("button.demander").get_attribute("aria-label") == "Demander à l’Assistant"
             and "ne peut pas écrire aux agents" in pg.locator("button.demander").get_attribute("title"))
    verifier(f"{nom} : le bouton est dans l'écran, à droite", b["x"] + b["width"] <= LARGEUR and b["x"] > LARGEUR / 2)
    if pg.locator(".sources-echec").count():
        verifier(f"{nom} : ⚠ sur la même ligne que le bouton", abs(boite(pg, ".sources-echec")["y"] - b["y"]) < 30)

    # 2. la barre d'onglets du bas : 64 px, fixe, trois onglets, icône + libellé
    barre = boite(pg, ".barre-onglets")
    verifier(f"{nom} : la barre du bas fait 64 px et touche le bas de l'écran", round(barre["height"]) >= 64 and round(barre["y"] + barre["height"]) == HAUTEUR, str(barre))
    verifier(f"{nom} : trois onglets Scène · Supervision · Fil", pg.locator(".barre-onglets a").all_inner_texts() == ["Scène", "Supervision", "Fil"],
             str(pg.locator(".barre-onglets a").all_inner_texts()))
    verifier(f"{nom} : une icône par onglet, aucune police d'icônes", pg.locator(".barre-onglets a svg").count() == 3)
    verifier(f"{nom} : « Scène » est l'onglet courant, son icône est ambre",
             pg.locator(".barre-onglets a[aria-current=page]").all_inner_texts() == ["Scène"]
             and pg.evaluate("getComputedStyle(document.querySelector('.barre-onglets a[aria-current=page] svg')).color") == "rgb(224, 164, 88)")
    verifier(f"{nom} : chaque onglet fait au moins 44 px de haut", min(a["height"] for a in pg.locator(".barre-onglets a").evaluate_all(
        "(as) => as.map((a) => { const r = a.getBoundingClientRect(); return { height: r.height }; })")) >= 44)
    verifier(f"{nom} : la barre est fixe (elle ne défile pas avec la page)", pg.evaluate("getComputedStyle(document.querySelector('.barre-onglets')).position") == "fixed")

    # 3. le bandeau d'attentes, sous l'en-tête
    bandeau = boite(pg, ".bandeau-attentes")
    verifier(f"{nom} : le bandeau est un bouton de 44 px au moins, sous l'en-tête, pleine largeur",
             pg.locator(".bandeau-attentes").evaluate("(n) => n.tagName") == "BUTTON" and bandeau["height"] >= 44
             and bandeau["y"] >= entete["y"] + entete["height"] - 1 and round(bandeau["width"]) == LARGEUR, str(bandeau))
    texte = pg.locator(".bandeau-attentes").inner_text()
    attentes = compter_attentes(pg)
    verifier(f"{nom} : « n points t'attendent › » (ambre) : {attentes} points", f"{attentes} points" in texte and "t’attendent" in texte and texte.strip().endswith("›"), texte)
    verifier(f"{nom} : le bandeau est ambre", pg.evaluate("getComputedStyle(document.querySelector('.bandeau-attentes')).color") == "rgb(224, 164, 88)")

    # 4. le plateau : 540 px, pleine largeur, Légende et zoom au-dessus de la ligne de flottaison, aucune barre horizontale de page
    plateau = boite(pg, "#plateau")
    verifier(f"{nom} : le plateau fait 540 px de haut et {LARGEUR} px de large", round(plateau["height"]) == 540 and round(plateau["width"]) == LARGEUR, str(plateau))
    verifier(f"{nom} : le plateau tient au-dessus de la barre du bas", plateau["y"] + plateau["height"] <= barre["y"], str(plateau))
    bas = [boite(pg, "#plateau .commande-legende"), *[x for x in pg.locator("#plateau .commandes-zoom button").evaluate_all(
        "(bs) => bs.map((b) => { const r = b.getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height }; })")]]
    verifier(f"{nom} : « Légende » et les quatre boutons de zoom sont dans le plateau, au-dessus de la ligne de flottaison",
             len(bas) == 4 and all(c["y"] + c["height"] <= min(plateau["y"] + plateau["height"], HAUTEUR - 64) and c["x"] >= 0 and c["x"] + c["width"] <= LARGEUR for c in bas), str(bas))
    verifier(f"{nom} : les boutons du plateau restent de 32 px", all(round(c["height"]) == 32 for c in bas), str([c["height"] for c in bas]))
    ok, d = sans_debordement(pg)
    verifier(f"{nom} : aucune barre de défilement horizontale de page à {LARGEUR} px", ok, d)
    verifier(f"{nom} : la scène est montée (un canvas dans le plateau)", pg.locator("#plateau > canvas").count() == 1)
    capturer("accueil")

    # 5. la feuille basse, dans le flux : trois blocs, sans « Ce qui t'attend »
    blocs = pg.locator("#rail .bloc-rail").evaluate_all("(bs) => bs.map((b) => b.getAttribute('aria-label'))")
    verifier(f"{nom} : sous le plateau, « Ce qui coince », « Qui travaille » et « Derniers échanges », sans « Ce qui t’attend »",
             "Ce qui t’attend" not in blocs and set(blocs) <= {"Ce qui coince", "Qui travaille", "Derniers échanges"} and "Derniers échanges" in blocs, str(blocs))
    verifier(f"{nom} : le rail est sous le plateau et suit le flux de la page", boite(pg, "#rail")["y"] >= plateau["y"] + plateau["height"] - 1
             and pg.evaluate("getComputedStyle(document.getElementById('rail')).overflowY") == "visible")
    ok, d = fin_au_dessus_de_la_barre(pg)
    verifier(f"{nom} : la fin de la scène défilée n'est pas cachée par la barre", ok, d)

    # 6. la légende tient dans la largeur ; un clic dans la scène la referme
    pg.locator("#plateau .commande-legende").click()
    verifier(f"{nom} : « Légende » ouvre la légende", visible(pg, "#legende-plateau"))
    lg = boite(pg, "#legende-plateau")
    verifier(f"{nom} : la légende tient dans la largeur ({LARGEUR} − 32 px au plus)", lg["width"] <= LARGEUR - 32 + 1 and lg["x"] >= 0 and lg["x"] + lg["width"] <= LARGEUR, str(lg))
    pg.locator("#plateau > canvas").click(position={"x": 8, "y": 8})
    pg.wait_for_timeout(150)
    verifier(f"{nom} : un clic dans la scène referme la légende", not visible(pg, "#legende-plateau"))

    # 7. le bandeau → la feuille des attentes : plein écran, effectifs, toutes les cartes, agir sans fermer, trois façons de fermer
    ouvre_la_feuille_des_attentes(pg)
    f = boite(pg, FEUILLE_ATTENTES)
    verifier(f"{nom} : la feuille des attentes couvre l'écran", round(f["width"]) == LARGEUR and round(f["height"]) == HAUTEUR, str(f))
    verifier(f"{nom} : elle s'annonce comme un dialogue modal",
             pg.locator(FEUILLE_ATTENTES).get_attribute("aria-modal") == "true" and bool(pg.locator(FEUILLE_ATTENTES).get_attribute("aria-label")))
    verifier(f"{nom} : en haut, les effectifs en une ligne", pg.locator(f"{FEUILLE_ATTENTES} .feuille-effectifs .pilule").count() == 1
             and "travaillent" in pg.locator(f"{FEUILLE_ATTENTES} .feuille-effectifs").inner_text())
    cartes = pg.locator(f"{FEUILLE_ATTENTES} .attente").count()
    verifier(f"{nom} : toutes les cartes sont là, sans plafond de 3 ({attentes})", cartes == attentes, str(cartes))
    ordre = pg.locator(f"{FEUILLE_ATTENTES} .attente").evaluate_all("(cs) => cs.map((c) => c.dataset.nature)")
    rang = {"autorisation": 0, "decision": 1, "donnee": 2, "cloture": 3, "rapport": 4}
    verifier(f"{nom} : triées par genre (autorisation, décision, donnée, clôture, compte rendu)", [rang.get(n, 9) for n in ordre] == sorted(rang.get(n, 9) for n in ordre), str(ordre))
    verifier(f"{nom} : les boutons des cartes font au moins 44 px", pg.locator(f"{FEUILLE_ATTENTES} .attente .bouton").count() == 0 or min(
        r["height"] for r in pg.locator(f"{FEUILLE_ATTENTES} .attente .bouton").evaluate_all("(bs) => bs.map((b) => ({ height: b.getBoundingClientRect().height }))")) >= 44)
    ok, d = sans_debordement(pg)
    verifier(f"{nom} : la feuille ne fait pas déborder la page", ok, d)
    capturer("attentes")
    if pg.locator(f"{FEUILLE_ATTENTES} .attente-actions button:not(:disabled)").count():
        # agir sans fermer : « Lire » (ou le premier bouton ouvrant un dialogue) ouvre un dialogue par-dessus la feuille
        lire = pg.locator(f"{FEUILLE_ATTENTES} .attente button", has_text="Lire")
        if lire.count():
            lire.first.click()
            pg.wait_for_timeout(500)
            verifier(f"{nom} : « Lire » ouvre son dialogue par-dessus la feuille", pg.locator("dialog[open]").count() == 2)
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(200)
            verifier(f"{nom} : Échap ne ferme que le dialogue : la feuille des attentes reste ouverte", pg.locator(FEUILLE_ATTENTES).count() == 1)
    if FAUX_HOTE and nom == "hote" and pg.locator(f"{FEUILLE_ATTENTES} .attente[data-attente=perm-d41] button", has_text="Autoriser").count():
        n0 = len(json.loads(urllib.request.urlopen(f"{BASE}/test/requetes").read()))
        carte_actionnee = f"{FEUILLE_ATTENTES} .attente[data-attente=perm-d41]"
        boutons_avant = pg.locator(f"{carte_actionnee} button").evaluate_all(
            "(bs) => bs.map((b) => { const r = b.getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height }; })")
        pg.locator(f"{carte_actionnee} button", has_text="Autoriser").click()
        # on attend l'ÉTAT (la carte « envoyé, en attente de confirmation »), pas une durée : avec actions=ok le faux hôte retire la carte
        # au prochain instantané, avec actions=lent la réponse n'arrive qu'à 2 s
        pg.wait_for_selector(f"{carte_actionnee} .attente-envoyee", timeout=5000)
        posts = [r for r in json.loads(urllib.request.urlopen(f"{BASE}/test/requetes").read())[n0:] if r["m"] == "POST"]
        verifier(f"{nom} : « Autoriser » agit depuis la feuille (POST /api/actions/autoriser)", bool(posts) and posts[0]["chemin"] == "/api/actions/autoriser", str(posts))
        verifier(f"{nom} : la feuille reste ouverte et la carte dit « envoyé, en attente de confirmation »",
                 pg.locator(FEUILLE_ATTENTES).count() == 1 and "envoyé, en attente de confirmation" in pg.locator(f"{FEUILLE_ATTENTES} .attente[data-attente=perm-d41]").inner_text())
        pg.wait_for_selector(".toast", state="visible", timeout=5000)
        verifier(f"{nom} : le toast est visible au-dessus de la feuille", pg.locator(".toast").count() >= 1 and pg.locator(".toasts").evaluate("(n) => n.matches(':popover-open')"))
        # le toast ne masque rien : il est au-dessus de la barre d'onglets, sans cadre clair, et ne recouvre aucun bouton de la carte actionnée
        toast = pg.locator(".toast").last.bounding_box()
        barre = boite(pg, ".barre-onglets")
        verifier(f"{nom} : le toast est visible à l'écran et dans la largeur", toast is not None and toast["width"] > 0 and toast["x"] >= 0 and toast["x"] + toast["width"] <= LARGEUR, str(toast))
        verifier(f"{nom} : le toast est au-dessus de la barre d'onglets (sa boîte est au-dessus de celle de la barre)",
                 toast is not None and toast["y"] + toast["height"] <= barre["y"] + 1, f"{toast} / {barre}")
        verifier(f"{nom} : le toast n'est pas dans un cadre clair (fond transparent, pas de bordure sur la pile)",
                 pg.locator(".toasts").evaluate("(n) => { const s = getComputedStyle(n); return s.backgroundColor === 'rgba(0, 0, 0, 0)' && s.borderTopWidth === '0px' && s.paddingTop === '0px'; }"))
        verifier(f"{nom} : le toast ne recouvre aucun bouton de la carte actionnée ({len(boutons_avant)} boutons avant l'action)",
                 toast is not None and not any(
                     b["x"] < toast["x"] + toast["width"] and toast["x"] < b["x"] + b["width"]
                     and b["y"] < toast["y"] + toast["height"] and toast["y"] < b["y"] + b["height"] for b in boutons_avant), f"{toast} / {boutons_avant}")
    pg.locator(f"{FEUILLE_ATTENTES} .feuille-poignee").click()
    pg.wait_for_timeout(200)
    verifier(f"{nom} : la poignée ferme la feuille des attentes", pg.locator("dialog[open]").count() == 0)
    ouvre_la_feuille_des_attentes(pg)
    pg.locator(f"{FEUILLE_ATTENTES} button", has_text="Fermer").first.click()
    pg.wait_for_timeout(200)
    verifier(f"{nom} : « Fermer » ferme la feuille des attentes", pg.locator("dialog[open]").count() == 0)
    ouvre_la_feuille_des_attentes(pg)
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(200)
    verifier(f"{nom} : Échap ferme la feuille des attentes", pg.locator("dialog[open]").count() == 0)

    # 8. le toucher d'une pièce, d'un agent → la feuille de détail (70 %) ; fermer = plus de sélection
    trouvees = balayer(pg, ("equipe", "agent"))
    verifier(f"{nom} : un toucher atteint une pièce et un agent", {"equipe", "agent"} <= set(trouvees), str(sorted(trouvees)))
    if "equipe" in trouvees:
        pg.mouse.click(*trouvees["equipe"])
        pg.wait_for_selector(FEUILLE_DETAIL, timeout=3000)
        d = boite(pg, FEUILLE_DETAIL)
        verifier(f"{nom} : toucher une pièce ouvre la feuille de détail, montante, à 70 % de la hauteur",
                 abs(d["height"] - 0.7 * HAUTEUR) <= 3 and round(d["y"] + d["height"]) == HAUTEUR and round(d["width"]) == LARGEUR, str(d))
        verifier(f"{nom} : c'est le même détail que le rail du bureau (nom, statut, deux chiffres, fiche complète)",
                 pg.locator(f"{FEUILLE_DETAIL} .detail-tete h2").count() == 1 and pg.locator(f"{FEUILLE_DETAIL} .puce-statut").count() == 1
                 and pg.locator(f"{FEUILLE_DETAIL} .detail-chiffre").count() == 2 and pg.locator(f"{FEUILLE_DETAIL} a.bouton-lien").count() == 1)
        verifier(f"{nom} : la sélection est celle de la pièce", cle(pg.evaluate(CIBLE)) == "equipe:" + pg.locator(f"{FEUILLE_DETAIL} .detail-tete h2").inner_text())
        verifier(f"{nom} : le rail sous le plateau n'est pas passé en détail", pg.locator("#rail .detail-rail").count() == 0)
        capturer("detail")
        avant = pg.locator(f"{FEUILLE_DETAIL} .detail-tete h2").inner_text()
        pg.wait_for_timeout(6000)
        verifier(f"{nom} : la feuille se met à jour sur place sans se fermer après des instantanés",
                 pg.locator(FEUILLE_DETAIL).count() == 1 and pg.locator(f"{FEUILLE_DETAIL} .detail-tete h2").inner_text() == avant)
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(200)
        verifier(f"{nom} : Échap ferme la feuille de détail et retire la sélection", pg.locator("dialog[open]").count() == 0 and pg.evaluate(CIBLE) is None)
        pg.mouse.click(*trouvees["equipe"])
        pg.wait_for_selector(FEUILLE_DETAIL, timeout=3000)
        pg.locator(f"{FEUILLE_DETAIL} button", has_text="Fermer").first.click()
        pg.wait_for_timeout(200)
        verifier(f"{nom} : « Fermer » ferme la feuille de détail et retire la sélection", pg.locator("dialog[open]").count() == 0 and pg.evaluate(CIBLE) is None)
        pg.mouse.click(*trouvees["equipe"])
        pg.wait_for_selector(FEUILLE_DETAIL, timeout=3000)
        pg.locator(f"{FEUILLE_DETAIL} .feuille-poignee").click()
        pg.wait_for_timeout(200)
        verifier(f"{nom} : la poignée ferme la feuille de détail", pg.locator("dialog[open]").count() == 0 and pg.evaluate(CIBLE) is None)
        pg.mouse.click(*trouvees["equipe"])
        pg.wait_for_selector(FEUILLE_DETAIL, timeout=3000)
        pg.mouse.click(LARGEUR / 2, 40)  # le voile, au-dessus de la feuille
        pg.wait_for_timeout(200)
        verifier(f"{nom} : un toucher sur le voile ferme la feuille de détail", pg.locator("dialog[open]").count() == 0 and pg.evaluate(CIBLE) is None)
    if "agent" in trouvees:
        pg.mouse.click(*trouvees["agent"])
        pg.wait_for_selector(FEUILLE_DETAIL, timeout=3000)
        verifier(f"{nom} : toucher un agent ouvre son détail (contexte, dettes, file)",
                 all(m in pg.locator(FEUILLE_DETAIL).inner_text() for m in ("Contexte", "Dettes", "File")))
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(200)
    if "equipe" in trouvees:
        pg.mouse.click(*trouvees["equipe"])
        pg.wait_for_selector(FEUILLE_DETAIL, timeout=3000)
        nom_equipe = pg.locator(f"{FEUILLE_DETAIL} .detail-tete h2").inner_text()
        pg.locator(f"{FEUILLE_DETAIL} a.bouton-lien").click()
        pg.wait_for_timeout(500)
        verifier(f"{nom} : « Ouvrir la fiche complète → » ferme la feuille et ouvre la fiche",
                 pg.locator("dialog[open]").count() == 0 and pg.url.endswith(f"#/equipe/{nom_equipe}") and pg.locator(".eq-tete").count() == 1, pg.url)
        pg.goto(url)
        pg.wait_for_selector("#plateau > canvas", timeout=4000)
        pg.wait_for_timeout(500)

    # 9. la porte de l'utilisateur ouvre la feuille des attentes ; la fermer retire la sélection
    portes = balayer(pg, ("utilisateur",))
    for _ in range(3):
        if "utilisateur" in portes:
            break
        glisser(pg, 300)  # la porte est au bout du glissement
        portes = balayer(pg, ("utilisateur",))
    verifier(f"{nom} : un toucher atteint la porte de l'utilisateur (après avoir fait glisser la scène)", "utilisateur" in portes)
    if "utilisateur" in portes:
        pg.mouse.click(*portes["utilisateur"])
        pg.wait_for_selector(FEUILLE_ATTENTES, timeout=3000)
        verifier(f"{nom} : la porte de l'utilisateur ouvre la feuille des attentes (pas de feuille de détail)", pg.locator(FEUILLE_DETAIL).count() == 0)
        pg.locator(f"{FEUILLE_ATTENTES} button", has_text="Fermer").first.click()
        pg.wait_for_timeout(200)
        verifier(f"{nom} : la fermer retire la sélection", pg.locator("dialog[open]").count() == 0 and pg.evaluate(CIBLE) is None)
    ok, d = sans_debordement(pg)
    verifier(f"{nom} : après avoir fait glisser la scène, la page ne défile toujours pas à l'horizontale", ok, d)

    # 10. Supervision et Fil : la fin n'est pas sous la barre, le bandeau y est ambre, rien ne déborde
    for ancre, sujet, attendu in (("#/supervision", "supervision", ".organigramme"), ("#/fil", "fil", ".fil-page")):
        pg.goto(url.split("#")[0] + ancre)
        pg.wait_for_selector(attendu)
        pg.wait_for_timeout(500)
        verifier(f"{nom} : {sujet} : l'onglet courant de la barre", pg.locator(".barre-onglets a[aria-current=page]").all_inner_texts() == [{"supervision": "Supervision", "fil": "Fil"}[sujet]])
        ok, d = fin_au_dessus_de_la_barre(pg)
        verifier(f"{nom} : {sujet} : la fin de l'écran n'est pas cachée par la barre", ok, d)
        ok, d = sans_debordement(pg)
        verifier(f"{nom} : {sujet} : aucune barre de défilement horizontale de page", ok, d)
        verifier(f"{nom} : {sujet} : le bandeau ambre est là (il y a des points)", visible(pg, ".bandeau-attentes.bandeau-ambre"))
        verifier(f"{nom} : {sujet} : un seul bandeau d'attentes", pg.locator(".bandeau-attentes").count() == 1)
        capturer(sujet)
    pg.goto(url.split("#")[0] + "#/supervision")
    pg.wait_for_selector(".organigramme")
    pg.locator(".bandeau-attentes").click()
    pg.wait_for_selector(FEUILLE_ATTENTES, timeout=3000)
    attentes = compter_attentes(pg)  # recomptées : « Autoriser » en a retiré une depuis le premier comptage
    verifier(f"{nom} : depuis Supervision, le bandeau ouvre la même feuille des attentes ({attentes})", pg.locator(f"{FEUILLE_ATTENTES} .attente").count() == attentes)
    pg.keyboard.press("Escape")
    ctx.close()


def calme(nav, url, sorties, erreurs):
    """Faux hôte seulement : aucune attente. Bandeau vert sur la Scène, rien sur Supervision ni sur le Fil."""
    regler("attentes=calme")
    ctx = nav.new_context(viewport={"width": LARGEUR, "height": HAUTEUR}, has_touch=True)
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: erreurs.append(f"calme: {e}"))
    pg.goto(url)
    pg.wait_for_selector(".bandeau-attentes")
    pg.wait_for_selector("#plateau > canvas", timeout=4000)
    pg.wait_for_timeout(600)
    texte = pg.locator(".bandeau-attentes").inner_text()
    verifier("calme : le bandeau est vert « ✓ Rien ne t’attend › » sur la Scène", "✓ Rien ne t’attend" in texte and texte.strip().endswith("›")
             and pg.locator(".bandeau-attentes.bandeau-calme").count() == 1, texte)
    verifier("calme : le bandeau vert fait 44 px au moins", boite(pg, ".bandeau-attentes")["height"] >= 44)
    verifier("calme : aucun élément rouge visible à l'écran — texte, fond ou liseré ; un agent arrêté sans alarme est « à l’arrêt », gris, et une source en échec grise (les éléments cachés — capsule figée, libellés « problème » de la légende fermée — ne comptent pas)", pg.evaluate("[...document.querySelectorAll('body *')].filter((n) => { if (!n.checkVisibility()) return false; const c = getComputedStyle(n); return ['rgb(217, 106, 95)', 'rgb(232, 154, 145)'].includes(c.color) || ['rgb(217, 106, 95)', 'rgb(44, 29, 28)'].includes(c.backgroundColor) || ['rgb(217, 106, 95)', 'rgb(69, 47, 44)'].includes(c.borderLeftColor); }).length") == 0)
    pg.screenshot(path=str(sorties / f"mobile-calme-{LARGEUR}x{HAUTEUR}.png"))
    pg.locator(".bandeau-attentes").click()
    pg.wait_for_selector(FEUILLE_ATTENTES, timeout=3000)
    verifier("calme : la feuille des attentes dit « Rien ne t’attend » (et montre les effectifs)",
             "Rien ne t’attend" in pg.locator(FEUILLE_ATTENTES).inner_text() and pg.locator(f"{FEUILLE_ATTENTES} .feuille-effectifs .pilule").count() == 1)
    pg.keyboard.press("Escape")
    for ancre in ("#/supervision", "#/fil"):
        pg.goto(url.split("#")[0] + ancre)
        pg.wait_for_selector(".barre-onglets")
        pg.wait_for_timeout(400)
        verifier(f"calme : aucun bandeau sur {ancre} quand rien n'attend", pg.locator(".bandeau-attentes").count() == 0)
    ctx.close()
    regler("attentes=normales")


def fige_et_injoignable(nav, erreurs):
    """Image figée : capsule dans la largeur, boutons des attentes désactivés ; hôte injoignable au chargement : écran lisible à 390 px."""
    ctx = nav.new_context(viewport={"width": LARGEUR, "height": HAUTEUR}, has_touch=True)
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: erreurs.append(f"coupure: {e}"))
    pg.goto(f"{BASE}/#/")
    pg.wait_for_selector(".bandeau-attentes")
    pg.wait_for_selector("#plateau > canvas", timeout=4000)
    regler("flux=coupe")
    ctx.route("**/api/**", lambda route: route.abort())
    try:
        pg.wait_for_selector('#plateau[data-fige="oui"]', timeout=40000)
        fige = True
    except Exception:  # noqa: BLE001
        fige = False
    verifier("figé : l'image se fige", fige)
    if fige:
        pg.wait_for_timeout(500)
        capsule = boite(pg, ".capsule-figee")
        verifier("figé : la capsule rouge tient dans la largeur du plateau", capsule["x"] >= 0 and capsule["x"] + capsule["width"] <= LARGEUR, str(capsule))
        verifier("figé : la pastille d'en-tête dit « Figé »", "Figé" in pg.locator(".age-donnee").inner_text())
        entete = boite(pg, ".entete")
        verifier("figé : l'en-tête reste de 52 px sur une ligne", round(entete["height"]) == 52 and pg.evaluate("(() => { const e = document.querySelector('.entete'); return e.scrollWidth <= e.clientWidth; })()"))
        ok, d = sans_debordement(pg)
        verifier("figé : aucune barre horizontale de page", ok, d)
        pg.locator(".bandeau-attentes").click()
        pg.wait_for_selector(FEUILLE_ATTENTES, timeout=3000)
        boutons = pg.locator(f"{FEUILLE_ATTENTES} .attente-actions button, {FEUILLE_ATTENTES} .attente-actions input")
        verifier("figé : tous les boutons de la feuille des attentes sont désactivés, avec leur explication",
                 boutons.count() > 0 and pg.locator(f"{FEUILLE_ATTENTES} .attente-actions button:not(:disabled), {FEUILLE_ATTENTES} .attente-actions input:not(:disabled)").count() == 0
                 and boutons.first.get_attribute("title") == "L’hôte ne répond plus")
        pg.screenshot(path=str(Path(sys.argv[1] if len(sys.argv) > 1 else ".") / f"mobile-fige-{LARGEUR}x{HAUTEUR}.png"))
        pg.keyboard.press("Escape")
    ctx.unroute("**/api/**")
    regler("flux=normal")
    ctx.close()

    ctx = nav.new_context(viewport={"width": LARGEUR, "height": HAUTEUR}, has_touch=True)
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: erreurs.append(f"panne: {e}"))
    regler("etat=panne")
    pg.goto(f"{BASE}/#/")
    pg.wait_for_selector(".injoignable-carte", timeout=5000)
    pg.wait_for_timeout(500)
    carte = boite(pg, ".injoignable-carte")
    verifier("injoignable : la carte tient dans la largeur", carte["x"] >= 0 and carte["x"] + carte["width"] <= LARGEUR, str(carte))
    verifier("injoignable : l'en-tête fait 52 px", round(boite(pg, ".entete")["height"]) == 52)
    ok, d = sans_debordement(pg)
    verifier("injoignable : aucune barre horizontale de page", ok, d)
    regler("etat=ok")
    ctx.close()


def main(sorties):
    erreurs = []
    with sync_playwright() as p:
        nav = p.chromium.launch(executable_path=CHROME, headless=True)
        parcourir(nav, "hote", f"{BASE}/#/", sorties, erreurs)
        if FAUX_HOTE:
            calme(nav, f"{BASE}/#/", sorties, erreurs)
        if FAUX_HOTE:
            fige_et_injoignable(nav, erreurs)
        else:
            print("    (hôte réel : l'état figé et l'hôte injoignable ne sont pas rejoués ici)")
        nav.close()
    verifier("aucune erreur JS ni avertissement de console (hors réseau coupé exprès)", not erreurs, "; ".join(erreurs))
    print(f"\n{len(OK)} OK, {len(KO)} KO : {KO}")
    return 1 if KO else 0


if __name__ == "__main__":
    sortie = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    sortie.mkdir(parents=True, exist_ok=True)
    sys.exit(main(sortie))
