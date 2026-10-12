"""Vérifications navigateur de Supervision (les sections, l'organigramme, la hauteur de page, « Ce qui coince » en liste, Dépendances),
sur `#/supervision` à 1440×900 et à 390×844, deux fois : sur l'état d'exemple du faux hôte (19 alarmes) et sur l'instantané « réel »
(servi par le faux hôte réglé sur `jeu=reel` : 8 équipes visibles, 6 alarmes à voir dont des doublons de type, 8 infos).

Ce que pytest ne voit pas : l'ordre des sections à l'écran, « Ce qui coince » dans un seul cadre (≈ 64 px par alarme, à voir groupés par type, infos en dernier),
le groupe replié puis déplié, le lien « n équipe(s) clôturée(s) » sous la grille (et le seul lien du pied : le journal), integration hors de la grille,
l'absence de « Décisions récentes » et de « Derniers échanges », la hauteur de la page (au plus 1 800 px au bureau **sur l'instantané réel** ; sur l'exemple, la mesure est
imprimée avec un seuil propre de 4 500 px, car 19 alarmes la rendent plus haute), l'onglet Dépendances (aucune erreur JS, graphe non vide), l'absence de barre
horizontale, l'en-tête de 761 à 1 280 px, réel et exemple (une ligne de texte, bouton dans la fenêtre), la console sans erreur, et des captures à regarder.

Usage (le faux hôte, `hote_factice.py`, doit tourner sur CIME_PORT_TEST ; le scénario règle lui-même `jeu=exemple` puis `jeu=reel`) :

    uv run --with playwright python tests/page/outils/scenario_supervision.py <dossier-captures>

Code de sortie 1 si une vérification échoue.
"""
import os
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

PORT = os.environ.get("CIME_PORT_TEST", "8791")
BASE = f"http://127.0.0.1:{PORT}"
CHROME = os.environ.get("CIME_CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
OK, KO = [], []
ORDRE = ["Ce qui coince", "Avancement du projet", "Consommation"]
RETIRES = ["Décisions récentes", "Derniers échanges", "Tout le fil"]
HAUTEUR_MAX = 1800  # critère de hauteur de la page entière au bureau — sur l'instantané réel
HAUTEUR_MAX_EXEMPLE = 4500  # l'exemple (19 alarmes) est plus haute que le réel : mesurée et imprimée, avec ce seuil propre
BRUIT = ("Failed to load resource", "net::ERR", "EventSource", "Failed to fetch")


def verifier(nom, cond, detail=""):
    (OK if cond else KO).append(nom)
    print(("OK  " if cond else "KO  ") + nom + (f" — {detail}" if detail else ""))


def mesure(pg):
    """Hauteur et largeur de la page, et si quelque chose dépasse horizontalement."""
    return pg.evaluate("({ h: document.documentElement.scrollHeight, w: document.documentElement.scrollWidth, vue: document.documentElement.clientWidth })")


def positions(pg, titres):
    """La position verticale de chaque titre de section (h2), None s'il manque."""
    return pg.evaluate("""(titres) => titres.map((t) => {
        const h = [...document.querySelectorAll('.page-corps h2')].find((n) => n.textContent.trim() === t);
        return h ? Math.round(h.getBoundingClientRect().top + scrollY) : null;
    })""", titres)


def ouvrir(nav, nom, largeur, hauteur, erreurs, reel, hash_="#/supervision"):
    ctx = nav.new_context(viewport={"width": largeur, "height": hauteur})
    pg = ctx.new_page()
    pg.on("console", lambda m: erreurs.append(f"{nom}: {m.text}") if m.type in ("error", "warning") and not any(i in m.text for i in BRUIT) else None)
    pg.on("pageerror", lambda e: erreurs.append(f"{nom}: {e}"))
    pg.goto(f"{BASE}/{hash_}")
    pg.wait_for_selector(".page-corps .section")
    return ctx, pg


def parcourir(nav, nom, largeur, hauteur, sorties, erreurs, reel):
    ctx, pg = ouvrir(nav, nom, largeur, hauteur, erreurs, reel)
    pg.wait_for_timeout(400)
    tel = largeur <= 760

    # 1. l'ordre à l'écran : ce qui coince, avancement, consommation, puis le pied
    ys = positions(pg, ORDRE)
    verifier(f"{nom} : les trois sections sont là, dans l'ordre", None not in ys and ys == sorted(ys), str(ys))
    pied = pg.locator(".pied-supervision")
    verifier(f"{nom} : le pied vient après la consommation", pied.count() == 1 and pied.evaluate("(n) => n.getBoundingClientRect().top + scrollY") > ys[-1])
    verifier(f"{nom} : la visite et les onglets précèdent « Ce qui coince »",
             pg.evaluate("(y) => { const d = document.querySelector('details.nouveautes'); const o = document.querySelector('.onglets');"
                         " return d && o && d.getBoundingClientRect().top + scrollY < o.getBoundingClientRect().top + scrollY"
                         " && o.getBoundingClientRect().top + scrollY < y; }", ys[0]))

    # 1 bis. l'organigramme : la tête sur une ligne, la grille de cartes-liens de hauteur égale par rangée
    tete = pg.locator(".org-tete")
    verifier(f"{nom} : la tête Utilisateur → Assistant est là", tete.count() == 1 and tete.locator(".org-utilisateur").count() == 1 and tete.locator(".org-assistant").count() == 1)
    boite = tete.bounding_box()
    verifier(f"{nom} : la tête est basse ({'deux lignes' if tel else 'une ligne, ≈ 70 px'})", boite is not None and boite["height"] <= (260 if tel else 100), str(boite))
    xa, xs = (tete.locator(s).bounding_box() for s in (".org-utilisateur", ".org-assistant"))
    verifier(f"{nom} : l'utilisateur est {'au-dessus' if tel else 'à gauche'} de l'Assistant", (xa["y"] < xs["y"]) if tel else (xa["x"] < xs["x"] and abs(xa["y"] - xs["y"]) < 4), f"{xa} {xs}")
    cartes_equipes = pg.locator("a.org-equipe")
    verifier(f"{nom} : des cartes d'équipe, toutes des liens vers #/equipe/", cartes_equipes.count() > 0 and all((h or "").startswith("#/equipe/") for h in cartes_equipes.evaluate_all("(ns) => ns.map((n) => n.getAttribute('href'))")))
    colonnes = pg.evaluate("getComputedStyle(document.querySelector('.org-equipes')).gridTemplateColumns.split(' ').length")
    verifier(f"{nom} : la grille a {1 if tel else 4} colonne(s)", colonnes == (1 if tel else 4), str(colonnes))
    rangees = pg.evaluate("""() => { const r = {}; for (const n of document.querySelectorAll('a.org-equipe')) { const b = n.getBoundingClientRect(); (r[Math.round(b.top)] ||= []).push(Math.round(b.height)); } return Object.values(r); }""")
    verifier(f"{nom} : dans une rangée, les cartes ont la même hauteur", all(len(set(h)) == 1 for h in rangees), str(rangees))
    if tel:
        verifier(f"{nom} : chaque carte est une cible tactile d'au moins 44 px", all(h >= 44 for rang in rangees for h in rang), str(rangees))
    verifier(f"{nom} : plus de « session absente », de « aucune tâche déclarée », de coût ni de modèle dans l'organigramme",
             not any(t in pg.locator(".organigramme").inner_text() for t in ("session absente", "aucune tâche déclarée", "coût", "claude-", "hook:")))
    print(f"MES {nom} : organigramme = {pg.locator('.organigramme').evaluate('(n) => Math.round(n.getBoundingClientRect().height)')} px")

    # 2. ce qui est retiré ne revient pas
    texte = pg.locator(".page-corps").inner_text()
    verifier(f"{nom} : ni « Décisions récentes » ni « Derniers échanges »", not any(r in texte for r in RETIRES), str([r for r in RETIRES if r in texte]))
    verifier(f"{nom} : plus de libellés « MESURE » / « QUOI FAIRE » en capitales", "MESURE" not in texte and "QUOI FAIRE" not in texte)

    # 3. un seul lien des équipes clôturées, sous la grille, avec le compte ; le pied n'a que le journal
    liens = pied.locator("a")
    verifier(f"{nom} : un seul lien au pied, « Journal des actions »", liens.all_inner_texts() == ["Journal des actions"] and liens.first.get_attribute("href") == "#/journal")
    archives = pg.locator("a[href='#/archives']")
    verifier(f"{nom} : un seul lien vers les équipes clôturées, avec leur compte, sous la grille",
             archives.count() == 1 and archives.inner_text().strip().endswith(("clôturée →", "clôturées →")), str(archives.all_inner_texts()))
    verifier(f"{nom} : la ligne de liens vient après la grille", pg.evaluate("""() => { const g = document.querySelector('.org-equipes'); const l = document.querySelector('.org-liens');
        return g && l && l.getBoundingClientRect().top >= g.getBoundingClientRect().bottom - 1; }"""))
    if reel:  # l'exemple n'a pas d'équipe integration
        verifier(f"{nom} : integration n'a pas de carte, elle est dans la ligne de liens",
                 not any(n.startswith("integration") for n in pg.locator(".org-equipe-nom").all_inner_texts()) and "integration (spéciale, sans session)" in pg.locator(".org-liens").inner_text())
    verifier(f"{nom} : le pied n'est pas une carte", pied.evaluate("(n) => { const s = getComputedStyle(n); return s.backgroundColor === 'rgba(0, 0, 0, 0)' && s.borderTopWidth === '0px'; }"))

    # 4. « Ce qui coince » : un seul cadre, des lignes de ≈ 64 px, « Quoi faire : » en gras (pas en ambre), la mesure repliée derrière « Détail »
    cadre = pg.locator(".alarmes-cadre")
    verifier(f"{nom} : un cadre unique pour les alarmes", cadre.count() == 1 and cadre.evaluate("(n) => getComputedStyle(n).borderTopWidth === '1px' && getComputedStyle(n).borderTopLeftRadius === '10px'"))
    cartes = pg.locator(".al.probleme")
    verifier(f"{nom} : des lignes pour les alarmes graves et à voir seules de leur type", cartes.count() > 0, str(cartes.count()))
    verifier(f"{nom} : plus de cartes d'alarme de 142 px", pg.locator(".alarmes-cadre > .alarme").count() == 0)
    premiere = cartes.first
    verifier(f"{nom} : « Quoi faire : » est visible en ligne, en gras, pas en ambre", "Quoi faire :" in premiere.inner_text() and premiere.locator(".al-faire b").evaluate(
        "(n) => Number(getComputedStyle(n).fontWeight) >= 600 && getComputedStyle(n).color !== getComputedStyle(document.documentElement).getPropertyValue('--ambre')"))
    verifier(f"{nom} : le mot de gravité n'est pas en capitales", premiere.locator(".probleme-mot").evaluate("(n) => getComputedStyle(n).textTransform === 'none'"))
    hauteurs = cartes.evaluate_all("(ns) => ns.map((n) => Math.round(n.getBoundingClientRect().height))")
    if not tel:
        verifier(f"{nom} : une ligne d'alarme fait ≈ 64 px (au plus 100 px)", all(h <= 100 for h in hauteurs), str(hauteurs))
    detail = premiere.locator("details.alarme-detail")
    mesure_texte = detail.locator(".alarme-ligne")
    verifier(f"{nom} : la mesure est repliée", detail.count() == 1 and not mesure_texte.is_visible())
    detail.locator("summary").click()
    verifier(f"{nom} : « Détail » déplie la mesure", mesure_texte.is_visible())
    detail.locator("summary").click()
    # les alarmes à voir d'un même type : une ligne dépliable, « Quoi faire » écrit une fois, chaque alarme avec son âge
    voir = pg.locator("details.groupe-probleme")
    if voir.count():
        v = voir.first
        verifier(f"{nom} : le groupe à voir est replié au chargement", v.evaluate("(n) => !n.open") and not v.locator(".groupe-liste").is_visible())
        verifier(f"{nom} : le groupe à voir dit « type ×n · cibles » et « Quoi faire : »", " ×" in v.locator("summary").inner_text() and "Quoi faire :" in v.locator("summary").inner_text(), v.locator("summary").inner_text())
        n_voir = v.locator(".groupe-alarme").count()
        v.locator("summary").click()
        pg.wait_for_timeout(150)
        verifier(f"{nom} : déplié, le groupe à voir montre chaque alarme avec son âge", v.locator(".groupe-liste").is_visible() and n_voir >= 2 and v.locator(".groupe-alarme .alarme-tete .discret").count() == n_voir, str(n_voir))
        v.locator("summary").click()
    if reel:
        # l'instantané réel : 6 à voir = 2 groupes (×3, ×2) + 1 ligne ordinaire, puis 1 ligne d'infos ; l'ensemble tient dans ≈ 300 px
        verifier(f"{nom} : 6 alarmes à voir en 3 lignes (2 groupes + 1 ordinaire) et 1 ligne d'infos", voir.count() == 2 and cartes.count() == 1 and pg.locator("details.alarme-groupe:not(.groupe-probleme)").count() == 1,
                 f"{voir.count()} groupes, {cartes.count()} ordinaire(s)")
        haut_cadre = cadre.evaluate("(n) => Math.round(n.getBoundingClientRect().height)")
        print(f"MES {nom} : « Ce qui coince » (cadre) = {haut_cadre} px")
        if not tel:
            verifier(f"{nom} : le cadre des alarmes tient en 400 px au plus (4 lignes)", haut_cadre <= 400, str(haut_cadre))
        verifier(f"{nom} : la grille a 8 cartes", pg.locator("a.org-equipe").count() == 8, str(pg.locator("a.org-equipe").count()))
        if not tel:
            verifier(f"{nom} : la grille tient en 2 rangées", len(rangees) == 2, str(rangees))

    # 5. les infos : une ligne par type, repliée ; dépliée, chaque alarme
    groupes = pg.locator("details.alarme-groupe:not(.groupe-probleme)")
    if groupes.count():
        g = groupes.first
        verifier(f"{nom} : le groupe d'infos est replié au chargement", g.evaluate("(n) => !n.open") and not g.locator(".groupe-liste").is_visible())
        verifier(f"{nom} : le groupe dit « Info ×n » et son type", g.locator("summary").inner_text().strip().startswith("Info ×"), g.locator("summary").inner_text())
        n_lignes = g.locator(".groupe-alarme").count()
        h_replie = pg.evaluate("document.documentElement.scrollHeight")
        g.locator("summary").click()
        pg.wait_for_timeout(200)
        verifier(f"{nom} : déplié, le groupe montre chaque alarme", g.locator(".groupe-liste").is_visible() and n_lignes >= 1, str(n_lignes))
        verifier(f"{nom} : déplier le groupe allonge la page", pg.evaluate("document.documentElement.scrollHeight") > h_replie)
        pg.screenshot(path=str(sorties / f"supervision-{nom}-groupe-deplie.png"), full_page=True)
        g.locator("summary").click()
    else:
        print(f"--  {nom} : aucune alarme info dans l'exemple, le groupe n'est pas vérifié")
    cible_tactile = groupes.first.locator("summary").bounding_box() if groupes.count() else None
    if tel and cible_tactile:
        verifier(f"{nom} : la ligne du groupe est une cible d'au moins 44 px", cible_tactile["height"] >= 44, str(cible_tactile))

    # 6. consommation : au plus trois barres, jamais rouges
    verifier(f"{nom} : les chiffres de la consommation ne sont pas en mono", pg.evaluate("""() => [...document.querySelectorAll('#consommation .conso-grand, #consommation .poste-valeur')]
        .every((n) => !getComputedStyle(n).fontFamily.toLowerCase().includes('mono') && getComputedStyle(n).fontVariantNumeric.includes('tabular-nums'))"""))
    barres = pg.locator("#consommation .poste")
    verifier(f"{nom} : au plus trois postes de consommation", 0 <= barres.count() <= 3, str(barres.count()))
    verifier(f"{nom} : les barres ne sont pas rouges", pg.evaluate("""() => [...document.querySelectorAll('#consommation .poste-plein')]
        .every((n) => { const [r, g, b] = getComputedStyle(n).backgroundColor.match(/\\d+/g).map(Number); return !(r > 150 && g < 90 && b < 90); })"""))

    # 7. mobile : une colonne, pas de barre horizontale ; bureau aussi
    m = mesure(pg)
    verifier(f"{nom} : pas de barre horizontale", m["w"] <= m["vue"], str(m))
    print(f"MES {nom} : document.documentElement.scrollHeight = {m['h']} px")
    if not tel:
        seuil = HAUTEUR_MAX if reel else HAUTEUR_MAX_EXEMPLE
        verifier(f"{nom} : la page tient en {seuil} px au plus (1440×900, {'instantané réel' if reel else 'exemple, 19 alarmes : seuil propre'})", m["h"] <= seuil, f"{m['h']} px")
    if tel:
        etapes = pg.locator(".etapes .etape")
        xs = pg.evaluate("[...document.querySelectorAll('.etapes .etape')].map((n) => Math.round(n.getBoundingClientRect().left))")
        verifier(f"{nom} : les étapes sont en une colonne", len(set(xs)) == 1 and etapes.count() > 1, str(xs))
        verifier(f"{nom} : consommation en une colonne", pg.evaluate("getComputedStyle(document.querySelector('#consommation .conso')).gridTemplateColumns.split(' ').length") == 1)
    pg.screenshot(path=str(sorties / f"supervision-{nom}.png"), full_page=True)

    # 8. l'onglet Dépendances garde la suite de l'écran
    pg.get_by_role("tab", name="Dépendances").click()
    pg.wait_for_timeout(300)
    ys2 = positions(pg, ORDRE)
    verifier(f"{nom} : onglet Dépendances, les sections suivent toujours dans l'ordre", None not in ys2 and ys2 == sorted(ys2), str(ys2))
    verifier(f"{nom} : onglet Dépendances, le graphe et la liste ne sont pas vides", pg.locator(".graphe-boite").count() > 0 and pg.locator(".graphe-liste li").count() > 0,
             f"{pg.locator('.graphe-boite').count()} boîtes, {pg.locator('.graphe-liste li').count()} lignes")
    ctx.close()


def dependances_direct(nav, nom, reel, erreurs):
    """Le lien direct `#/supervision?onglet=dependances` : aucune erreur de page, le graphe n'est pas vide."""
    avant = len(erreurs)
    ctx, pg = ouvrir(nav, nom, 1440, 900, erreurs, reel, "#/supervision?onglet=dependances")
    pg.wait_for_timeout(400)
    verifier(f"{nom} : #/supervision?onglet=dependances : l'onglet Dépendances est sélectionné", pg.locator("[role=tab][aria-selected=true]").inner_text().strip() == "Dépendances")
    verifier(f"{nom} : #/supervision?onglet=dependances : graphe non vide", pg.locator(".graphe-boite").count() > 0 and pg.locator(".graphe-liste li").count() > 0)
    verifier(f"{nom} : #/supervision?onglet=dependances : aucune erreur de page (pas de ReferenceError)", len(erreurs) == avant, "; ".join(erreurs[avant:]))
    pg.screenshot(path=str(SORTIES / f"supervision-{nom}-dependances.png"), full_page=True)
    ctx.close()


LIGNES_DE_TEXTE = """(selecteur) => [...document.querySelectorAll(selecteur)].map((n) => {
    // seuls les nœuds texte comptent : ni le rectangle d'un point coloré, ni celui d'un élément n'entrent dans le compte des lignes
    const parcours = document.createTreeWalker(n, NodeFilter.SHOW_TEXT);
    const hauts = new Set();
    for (let t = parcours.nextNode(); t; t = parcours.nextNode()) {
        if (!t.textContent.trim()) continue;
        const plage = document.createRange();
        plage.selectNodeContents(t);
        for (const r of plage.getClientRects()) if (r.width > 0) hauts.add(Math.round(r.top));
    }
    return { texte: n.textContent.trim(), lignes: hauts.size };
})"""


def entete(nav, erreurs):
    """L'en-tête entre 761 et 1 280 px, sur le réel et sur l'exemple : onglets et pastille sur une ligne de texte (comptée par les rectangles du texte, pas par
    la hauteur du lien, qui fait toute celle de l'en-tête), effectifs masqués jusqu'à 1 240 px, ⚠ et compteur sur une ligne, bouton « Demander à l'Assistant »
    entièrement dans la fenêtre, aucune barre horizontale à aucune largeur (pas de 40 px)."""
    largeurs = sorted(set(range(761, 1281, 40)) | {761, 880, 900, 901, 920, 1000, 1024, 1240, 1241, 1280})
    for jeu, reel in (("exemple", False), ("reel", True)):
        regler_jeu(jeu)
        suffixe = "reel" if reel else "exemple"
        for largeur in largeurs:
            ctx, pg = ouvrir(nav, f"entete-{suffixe}-{largeur}", largeur, 800, erreurs, reel)
            pg.wait_for_timeout(300)
            etiquette = f"en-tête {suffixe} {largeur} px"
            lignes = pg.evaluate(LIGNES_DE_TEXTE, ".nav a, .entete .age-donnee, .entete .sources-echec, .entete .compteur-attentes, .entete .demander-texte")
            coupes = [n["texte"] for n in lignes if n["lignes"] > 1]
            verifier(f"{etiquette} : onglets, pastille, ⚠, compteur et bouton sur une ligne de texte", coupes == [], str(coupes))
            effectifs = pg.locator(".entete .effectifs-texte")
            visible = effectifs.count() == 1 and effectifs.is_visible()
            verifier(f"{etiquette} : effectifs {'visibles' if largeur > 1240 else 'masqués'}", visible == (largeur > 1240))
            point = pg.locator(".entete .pilule:not(.age-donnee)")
            verifier(f"{etiquette} : le point redit les effectifs (title et aria-label)", point.count() == 1 and bool(point.get_attribute("title")) and point.get_attribute("title") == point.get_attribute("aria-label"))
            bouton = pg.evaluate("""() => { const r = document.querySelector('.entete .demander').getBoundingClientRect(); return { gauche: r.left, droite: r.right, vue: document.documentElement.clientWidth }; }""")
            verifier(f"{etiquette} : le bouton « Demander à l’Assistant » est entièrement dans la fenêtre", bouton["gauche"] >= 0 and bouton["droite"] <= bouton["vue"], str(bouton))
            m = mesure(pg)
            verifier(f"{etiquette} : pas de barre horizontale", m["w"] <= m["vue"], str(m))
            nom = pg.evaluate("""() => { const h = document.querySelector('.entete h1'); return { affiche: getComputedStyle(h).display !== 'none', titre: document.title }; }""")
            verifier(f"{etiquette} : le nom du projet est {'masqué' if largeur <= 900 else 'affiché'} (900 px)", nom["affiche"] == (largeur > 900), str(nom))
            verifier(f"{etiquette} : le nom du projet reste dans le titre de l’onglet", "Cime" in nom["titre"] and len(nom["titre"]) > len("Cime"), nom["titre"])
            if largeur <= 1240:
                ecart = pg.evaluate("""() => { const a = document.querySelector('.entete .pilule:not(.age-donnee)').getBoundingClientRect(), b = document.querySelector('.entete .age-donnee').getBoundingClientRect(); return b.left - a.right; }""")
                verifier(f"{etiquette} : les points des effectifs et de « En direct » ne se touchent pas (≥ 8 px)", ecart >= 8, str(ecart))
            marque = pg.evaluate("""() => { const t = document.querySelector('.entete-titres').getBoundingClientRect(), n = document.querySelector('.nav').getBoundingClientRect(); return n.left - t.right; }""")
            verifier(f"{etiquette} : la marque est à distance des onglets", marque >= 8, str(marque))
            if largeur in (761, 1024, 1240, 1280):
                pg.screenshot(path=str(SORTIES / f"entete-{suffixe}-{largeur}.png"))
            ctx.close()
    regler_jeu("exemple")


SORTIES = Path(".")


def regler_jeu(jeu):
    urllib.request.urlopen(f"{BASE}/test/regler?jeu={jeu}", timeout=10).read()


def main(sorties):
    global SORTIES
    SORTIES = sorties
    erreurs = []
    sorties.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        nav = p.chromium.launch(executable_path=CHROME, headless=True)
        for jeu, reel in (("exemple", False), ("reel", True)):
            regler_jeu(jeu)
            suffixe = "reel" if reel else "exemple"
            parcourir(nav, f"bureau-{suffixe}", 1440, 900, sorties, erreurs, reel)
            parcourir(nav, f"mobile-{suffixe}", 390, 844, sorties, erreurs, reel)
            dependances_direct(nav, f"bureau-{suffixe}", reel, erreurs)
        entete(nav, erreurs)
        nav.close()
    verifier("aucune erreur JS ni avertissement de console (hors réseau)", not erreurs, "; ".join(erreurs))
    print(f"\n{len(OK)} vérifications réussies, {len(KO)} échouées")
    return 1 if KO else 0


if __name__ == "__main__":
    sortie = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    sys.exit(main(sortie))
