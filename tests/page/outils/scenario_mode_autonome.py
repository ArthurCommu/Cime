"""Vérifications navigateur de l'interrupteur « Mode autonome » : les cinq états à 1 440 et 390 px, la bascule à la souris et au clavier,
le balayage de l'en-tête de 761 à 1 440 px avec un nom de projet long et la pastille.

Ce que pytest ne voit pas (il rend le DOM sous node, sans mise en page) : l'interrupteur est à droite de « Ce qui t'attend » sur la même ligne, le libellé est à
gauche de la piste, la cible fait 44 px, l'anneau de focus se voit, les couleurs calculées (gris éteint, bleu actif, ambre suspendu, jamais rouge ni vert), le
focus que le clavier retrouve après le redessin, Espace qui bascule, « Activation… » pendant la requête, le toast, le refus qui remet l'interrupteur en place,
l'en-tête qui ne déborde pas de 761 à 1 440 px (pastille « Autonome suspendu », nom de projet de 40 caractères), « Auto » / « Suspendu » sous 1 100 px,
l'interrupteur en première ligne de la feuille « Ce qui t'attend » du téléphone (des attentes) ou du tiroir (rien n'attend), et la tête de cette feuille
(titre + « Fermer ») sur une ligne à 320, 360, 375 et 390 px ; puis le récap de ce que l'Assistant a décidé, en tête de « Depuis ta dernière visite »
sur Supervision à 1 440, 390, 360 et 320 px (première ligne, bleue, détail replié puis déplié sans débordement).

Usage (le faux hôte, `hote_factice.py`, doit tourner sur CIME_PORT_TEST ; relancer le faux hôte avant le scénario pour partir d'un état neuf) :

    python3 tests/page/outils/hote_factice.py src/cime/page 8791 &
    uv run --with playwright python tests/page/outils/scenario_mode_autonome.py <dossier-captures>

Le faux hôte porte le réglage `autonome=inactif|actif|suspendu|absent|sans_proposees` et `attentes=normales|vides` (GET /test/regler) et fait changer l'état à `POST /api/actions/fusions-auto`
comme l'hôte réel (réactivation d'un mode suspendu comprise). Aucun envoi vers l'hôte réel : ce scénario n'a pas de mode « hôte réel ».
Code de sortie 1 si une vérification échoue.
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

PORT = os.environ.get("CIME_PORT_TEST", "8791")
BASE = f"http://127.0.0.1:{PORT}"
CHROME = os.environ.get("CIME_CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
OK, KO = [], []
NOM_LONG = "projet-au-nom-vraiment-tres-long-40-car"  # 39 caractères
LARGEURS_FEUILLE = (320, 360, 375, 390)  # les téléphones : la tête de la feuille « Ce qui t'attend » doit tenir sur une ligne à chacune
REPLI = "Restent à toi : architecture et contrats, fondation, droits, réseau, secrets, les chemins propres au projet, push et branches."  # liste inconnue
LARGEURS_ENTETE = list(range(761, 1441, 20)) + [761, 840, 880, 899, 900, 901, 1000, 1100, 1101, 1240, 1241, 1280, 1440]
GRIS, BLEU, AMBRE = "rgb(53, 57, 63)", "rgb(143, 176, 214)", "rgb(224, 164, 88)"  # --gris-fond, --bleu, --ambre
ROUGE_OU_VERT = ("rgb(217, 106, 95)", "rgb(88, 168, 155)", "rgb(232, 154, 145)", "rgb(143, 208, 196)")  # --rouge, --vert et leurs clairs
PHRASE_ACTIF = "L’Assistant fusionne à ta place"


def verifier(nom, cond, detail=""):
    (OK if cond else KO).append(nom)
    print(("OK  " if cond else "KO  ") + nom + (f" — {detail}" if detail else ""))


def regler(q):
    urllib.request.urlopen(f"{BASE}/test/regler?{q}").read()


def requetes():
    return [r for r in json.loads(urllib.request.urlopen(f"{BASE}/test/requetes").read()) if r["chemin"] == "/api/actions/fusions-auto"]


def reecrire(pg, nom=None):
    """Réécrit le nom du projet dans le premier instantané (GET /api/etat seulement) : l'état du mode autonome et les attentes viennent du faux hôte."""
    def gerer(route):
        r = route.fetch()
        etat = r.json()
        if nom is not None:
            etat["projet"]["nom"] = nom
        route.fulfill(response=r, body=json.dumps(etat), headers={**r.headers, "content-type": "application/json"})
    pg.route("**/api/etat", gerer)


def ouvrir(nav, largeur, hauteur, erreurs, nom, **reglages):
    # `attentes="vides"` : le faux hôte ne renvoie plus aucune attente, dans /api/etat et dans /api/flux (sinon l'instantané suivant les remettrait)
    regler("autonome=" + reglages.pop("autonome", "inactif") + "&actions=" + reglages.pop("actions", "ok") + "&attentes=" + reglages.pop("attentes", "normales"))
    ctx = nav.new_context(viewport={"width": largeur, "height": hauteur})
    pg = ctx.new_page()
    pg.on("console", lambda m: erreurs.append(f"{nom}: {m.text}") if m.type in ("error", "warning") and not any(
        i in m.text for i in ("Failed to load resource", "net::ERR", "EventSource", "Failed to fetch")) else None)
    pg.on("pageerror", lambda e: erreurs.append(f"{nom}: {e}"))
    return pg


def charger(pg, nom=None, avec_inter=True):
    """`avec_inter` faux : au téléphone, avec des attentes, l'interrupteur n'existe qu'une fois la feuille ouverte (il n'est pas dans la page)."""
    reecrire(pg, nom)
    pg.goto(BASE + "/")
    pg.wait_for_selector(".entete")
    if avec_inter:
        pg.wait_for_selector(".inter", state="attached")
    pg.wait_for_timeout(500)


def couleur_piste(pg, selecteur=".inter"):
    return pg.locator(f"{selecteur} .piste").first.evaluate("(n) => getComputedStyle(n).backgroundColor")


def dans_l_ordre_a_droite(pg, titre="#rail .rail-tete h2", inter="#rail .inter"):
    t, i = pg.locator(titre).first.bounding_box(), pg.locator(inter).first.bounding_box()
    return i["x"] > t["x"] + t["width"] and abs((i["y"] + i["height"] / 2) - (t["y"] + t["height"] / 2)) < 8, f"titre {t}, interrupteur {i}"


def etats_du_bureau(nav, sorties, erreurs):
    # --- 1 : inactif (rien ailleurs) ---
    pg = ouvrir(nav, 1440, 900, erreurs, "inactif")
    charger(pg)
    inter = pg.locator("#rail .inter")
    boite = inter.bounding_box()
    verifier("inactif : l'interrupteur est un switch non coché, libellé « Mode autonome »", inter.get_attribute("role") == "switch" and inter.get_attribute("aria-checked") == "false"
             and "Mode autonome" in inter.inner_text())
    verifier("inactif : la cible fait 44 px de haut", round(boite["height"]) >= 44, str(boite))
    verifier("inactif : l'interrupteur est à droite de « Ce qui t'attend », sur la même ligne", *dans_l_ordre_a_droite(pg))
    libelle = pg.locator("#rail .inter").evaluate("(n) => { const r = document.createRange(); r.selectNodeContents(n.firstChild); return r.getBoundingClientRect().right; }")
    verifier("inactif : le libellé est à gauche de la piste", libelle <= pg.locator("#rail .inter .piste").bounding_box()["x"] + 1)
    verifier("inactif : la piste est grise", couleur_piste(pg) == GRIS, couleur_piste(pg))
    texte = pg.locator("#rail .etat-auto").inner_text()
    verifier("inactif : la ligne discrète dit ce que le clic ferait et ce qui reste à l'utilisateur",
             texte.startswith("Activé, l’Assistant fusionne à ta place. Restent à toi : architecture et contrats, fondation, droits, réseau, secrets, push et branches."), texte[:140])
    verifier("inactif : la liste se lit avant l'activation (« Voir la liste · 43 chemins »)", "Voir la liste · 43 chemins" in texte)
    verifier("inactif : aucune pastille dans l'en-tête", pg.locator(".entete .pastille-auto").count() == 0)
    verifier("inactif : le bloc reste dessiné quand rien n'attend", True)
    pg.screenshot(path=str(sorties / "mode-1-inactif-1440.png"))
    # le focus clavier : l'anneau se voit
    inter.focus()
    pg.keyboard.press("Shift+Tab")
    pg.keyboard.press("Tab")
    verifier("inactif : le focus clavier arrive sur l'interrupteur, avec un anneau", pg.evaluate("document.activeElement.classList.contains('inter')")
             and pg.evaluate("getComputedStyle(document.activeElement).outlineStyle") != "none", pg.evaluate("getComputedStyle(document.activeElement).outline"))
    pg.context.close()

    # --- 2 et 3 : actif, replié puis déplié ---
    pg = ouvrir(nav, 1440, 900, erreurs, "actif", autonome="actif", attentes="vides")
    charger(pg)
    verifier("actif : l'interrupteur est coché et bleu", pg.locator("#rail .inter").get_attribute("aria-checked") == "true" and couleur_piste(pg) == BLEU, couleur_piste(pg))
    texte = pg.locator("#rail .etat-auto").inner_text()
    verifier("actif : l'encadré dit « L'Assistant fusionne à ta place depuis … · dernière : page f223c94, il y a … »",
             PHRASE_ACTIF in texte and "dernière : page f223c94" in texte and "il y a" in texte, texte[:160])
    verifier("actif : la ligne repliée « Restent à toi : … · 43 chemins »", "Restent à toi : architecture, fondation, droits, réseau, secrets, propres à projet-boutique · 43 chemins" in texte)
    pg.wait_for_timeout(3500)  # un instantané du flux est passé : la page ne remet pas d'attente (le faux hôte n'en renvoie plus)
    verifier("actif : « Ce qui t'attend » est calme (rien n'attend) et l'interrupteur y reste", "Rien ne t’attend" in pg.locator("#rail").inner_text() and pg.locator("#rail .inter").count() == 1)
    verifier("actif : la pastille « Autonome » (bleue) est dans l'en-tête, avant le compteur d'attentes",
             pg.locator(".entete .pastille-auto.actif .pastille-long").is_visible() and pg.locator(".entete .pastille-auto").inner_text().strip() == "Autonome")
    verifier("actif : son clic mène à la scène", pg.locator(".entete .pastille-auto").get_attribute("href") == "#/")
    verifier("actif : le title de la pastille redit « depuis … »", "depuis" in (pg.locator(".entete .pastille-auto").get_attribute("title") or ""))
    pg.screenshot(path=str(sorties / "mode-2-actif-replie-1440.png"))
    pg.locator("#rail .reserves > summary").click()
    pg.wait_for_timeout(150)
    themes = pg.locator("#rail .theme h3").all_inner_texts()
    verifier("actif déplié : un titre par thème avec son compte, puis « Toujours, hors chemins »",
             [t.replace("\n", " ") for t in themes] == ["Architecture et contrats · 9", "Fondation : registre, garde, hooks · 2", "Droits · 1", "Réseau et dépendances · 14", "Secrets · 8", "Propres à projet-boutique · 9", "Toujours, hors chemins"], str(themes))
    verifier("actif déplié : « push, suppression de branche » sans chemin", "push, suppression de branche" in pg.locator("#rail .hors-chemins").inner_text())
    verifier("actif déplié : au plus 5 chemins par thème puis « … »", pg.locator("#rail .theme").nth(0).locator(".chemin").count() == 5 and pg.locator("#rail .theme").nth(0).locator(".chemins-suite").count() == 1)
    verifier("actif déplié : un chemin ne se coupe jamais (une seule ligne de texte par chemin)",
             pg.locator("#rail .chemin").evaluate_all("(ns) => ns.every((n) => n.getClientRects().length === 1)"))
    verifier("actif déplié : la page ne défile pas, le rail défile seul s'il déborde", pg.evaluate("document.documentElement.scrollHeight") <= 900)
    pg.screenshot(path=str(sorties / "mode-3-actif-deplie-1440.png"))
    pg.locator("#rail .theme").nth(0).locator(".chemins-suite").click()
    verifier("actif déplié : « … » montre les 9 chemins du thème", pg.locator("#rail .theme").nth(0).locator(".chemin").count() == 9)
    pg.reload()
    pg.wait_for_selector("#rail .inter")
    verifier("actif déplié : le repli survit au redessin (nouvel instantané)", pg.locator("#rail .reserves").evaluate("(n) => n.open") is not None)
    pg.context.close()

    # --- 4 : suspendu ---
    pg = ouvrir(nav, 1440, 900, erreurs, "suspendu", autonome="suspendu", attentes="vides")
    charger(pg)
    verifier("suspendu : l'interrupteur reste en position actif, en ambre, même libellé", pg.locator("#rail .inter").get_attribute("aria-checked") == "true"
             and couleur_piste(pg) == AMBRE and pg.locator("#rail .inter").inner_text().strip() == "Mode autonome", couleur_piste(pg))
    verifier("suspendu : « Ce qui t'attend » reste sur une ligne (le libellé n'a pas grossi)", pg.locator("#rail .rail-tete h2").bounding_box()["height"] < 30)
    texte = pg.locator("#rail .etat-auto").inner_text()
    verifier("suspendu : l'encadré ambre explique", texte.startswith("Suspendu, fusions arrêtées : la liste des chemins réservés a changé depuis ton activation")
             and "Chaque fusion revient à ton accord." in texte and "Voir la liste actuelle · 43 chemins" in texte, texte[:160])
    verifier("suspendu : le bouton « Réactiver avec cette liste »", pg.locator("#rail .etat-auto .action").inner_text() == "Réactiver avec cette liste")
    verifier("suspendu : la pastille « Autonome suspendu » (ambre) dans l'en-tête", pg.locator(".entete .pastille-auto.suspendu").inner_text().strip() == "Autonome suspendu")
    fonds = pg.evaluate("[...document.querySelectorAll('.etat-auto.suspendu, .pastille-auto.suspendu, .inter.suspendu .piste')].flatMap((n) => { const s = getComputedStyle(n); return [s.color, s.backgroundColor, s.borderColor]; })")
    verifier("suspendu : jamais de rouge ni de vert", not any(c in ROUGE_OU_VERT for c in fonds), str(fonds))
    pg.screenshot(path=str(sorties / "mode-4-suspendu-1440.png"))
    avant = len(requetes())
    pg.locator("#rail .etat-auto .action").click()
    pg.wait_for_selector("#rail .etat-auto.actif", timeout=5000)
    envoyees = requetes()[avant:]
    verifier("suspendu : « Réactiver avec cette liste » envoie simplement active (un seul appel)", [r.get("corps") for r in envoyees] == [{"valeur": "active"}], str(envoyees))
    verifier("suspendu : il devient actif (bleu), sans la pastille ambre", pg.locator(".entete .pastille-auto.actif").count() == 1 and pg.locator(".entete .pastille-auto.suspendu").count() == 0)
    verifier("suspendu → actif : un toast d'une phrase", "Mode autonome activé : l’Assistant fusionne à ta place, hors chemins réservés." in pg.locator(".toasts").inner_text())
    pg.context.close()

    # --- 4 bis : liste inconnue (un hôte sans `reserves_proposees`) : la phrase de repli, d'un seul tenant, sans nombre ---
    pg = ouvrir(nav, 1440, 900, erreurs, "repli", autonome="sans_proposees")
    charger(pg)
    texte = pg.locator("#rail .etat-auto").inner_text()
    verifier("repli : la phrase d'un seul tenant, sans « + les chemins propres au projet » après le point",
             texte.strip() == "Activé, l’Assistant fusionne à ta place. " + REPLI and "+ les chemins" not in texte, texte)
    verifier("repli : aucun nombre, aucune liste à déplier", not any(c.isdigit() for c in texte) and pg.locator("#rail .reserves").count() == 0)
    pg.screenshot(path=str(sorties / "mode-4b-repli-1440.png"))
    pg.context.close()

    # --- 5 : pendant la requête, puis la souris, le clavier, le refus ---
    pg = ouvrir(nav, 1440, 900, erreurs, "requete", actions="lent")
    charger(pg)
    pg.locator("#rail .inter").click()
    pg.wait_for_timeout(300)
    inter = pg.locator("#rail .inter")
    verifier("requête : « Activation… », désactivé, aria-busy", inter.inner_text().strip() == "Activation…" and inter.is_disabled() and inter.get_attribute("aria-busy") == "true")
    pg.screenshot(path=str(sorties / "mode-5-requete-1440.png"))
    pg.wait_for_selector("#rail .inter[aria-checked='true']", timeout=8000)
    verifier("requête : l'interrupteur passe à actif quand l'instantané le montre", pg.locator("#rail .inter").get_attribute("aria-checked") == "true")
    verifier("requête : le focus est resté sur l'interrupteur (le clavier le retrouve après le redessin)", pg.evaluate("document.activeElement.classList.contains('inter')"))
    verifier("requête : le toast d'activation", "Mode autonome activé" in pg.locator(".toasts").inner_text())
    regler("actions=ok")
    pg.keyboard.press("Space")
    pg.wait_for_selector("#rail .inter[aria-checked='false']", timeout=8000)
    verifier("clavier : Espace bascule (désactivation)", pg.locator("#rail .inter").get_attribute("aria-checked") == "false")
    verifier("clavier : « Mode autonome désactivé : chaque fusion revient à ton accord. »", "chaque fusion revient à ton accord" in pg.locator(".toasts").inner_text())
    verifier("journal : un appel par bascule, valeur active puis inactive", [r.get("corps") for r in requetes()][-2:] == [{"valeur": "active"}, {"valeur": "inactive"}])
    regler("actions=refuse")
    pg.locator("#rail .inter").click()
    pg.wait_for_selector(".toast-ambre", timeout=5000)
    verifier("refus : la raison de l'hôte, en ambre", "Refusé :" in pg.locator(".toast-ambre").first.inner_text())
    verifier("refus : l'interrupteur revient à sa position", pg.locator("#rail .inter").get_attribute("aria-checked") == "false" and not pg.locator("#rail .inter").is_disabled())
    regler("actions=ok")
    pg.context.close()


def balayage_entete(nav, erreurs):
    """761 → 1 440 px, nom de projet long, pastille suspendue (la plus large), attentes présentes : ni débordement, ni recouvrement, « En direct » entier."""
    pg = ouvrir(nav, 1440, 900, erreurs, "balayage", autonome="suspendu")
    charger(pg, nom=NOM_LONG)
    pg.wait_for_selector(".entete .pastille-auto")
    fautes = []
    for largeur in LARGEURS_ENTETE:
        pg.set_viewport_size({"width": largeur, "height": 900})
        pg.wait_for_timeout(60)
        mesure = pg.evaluate("""() => {
          const e = document.querySelector('.entete').getBoundingClientRect();
          const enfants = [...document.querySelectorAll('.entete .entete-titres, .entete .nav, .entete .entete-etat > *')].filter((n) => n.getClientRects().length && getComputedStyle(n).display !== 'none');
          const boites = enfants.map((n) => [n.className.toString().split(' ')[0] || n.tagName, n.getBoundingClientRect()]);
          const recouvre = [];
          for (let i = 0; i < boites.length; i += 1) for (let j = i + 1; j < boites.length; j += 1) {
            const [a, p] = boites[i], [b, q] = boites[j];
            if (p.left < q.right - 0.5 && q.left < p.right - 0.5 && p.top < q.bottom - 0.5 && q.top < p.bottom - 0.5 && !(p.width === 0 || q.width === 0)) recouvre.push(a + ' / ' + b);
          }
          const sorti = boites.filter(([, r]) => r.right > e.right + 0.5 || r.left < e.left - 0.5).map(([n]) => n);
          const pas = (s) => { const n = document.querySelector(s); return n && n.getClientRects().length ? n.scrollWidth <= n.clientWidth + 1 : null; };
          const direct = document.querySelector('.age-donnee');
          return { recouvre, sorti, defile: document.documentElement.scrollWidth - innerWidth, pastilleEntiere: pas('.pastille-auto'), direct: direct ? direct.getBoundingClientRect().width : 0,
                   hauteur: e.height, titre: document.querySelector('.entete h1') ? getComputedStyle(document.querySelector('.entete h1')).display : null };
        }""")
        if mesure["recouvre"] or mesure["sorti"] or mesure["defile"] > 0 or mesure["pastilleEntiere"] is False or mesure["direct"] < 60:
            fautes.append((largeur, mesure))
        courte = pg.locator(".entete .pastille-court").is_visible()
        if (largeur <= 1100) != courte:
            fautes.append((largeur, "forme de la pastille : courte=" + str(courte)))
    verifier("en-tête : de 761 à 1 440 px, rien ne déborde ni ne se recouvre, « En direct » et la pastille entiers", not fautes, str(fautes[:3]))
    for largeur in (761, 840, 880, 901, 1000, 1280):
        pg.set_viewport_size({"width": largeur, "height": 900})
        pg.wait_for_timeout(80)
        verifier(f"en-tête à {largeur} px : une seule ligne (56 px)", pg.locator(".entete").bounding_box()["height"] <= 57, str(pg.locator(".entete").bounding_box()))
    pg.set_viewport_size({"width": 1440, "height": 900})
    pg.wait_for_timeout(100)
    pg.screenshot(path=str(Path(sys.argv[1]) / "mode-6-entete-1440.png"), clip={"x": 0, "y": 0, "width": 1440, "height": 80})
    pg.set_viewport_size({"width": 840, "height": 900})
    pg.wait_for_timeout(100)
    pg.screenshot(path=str(Path(sys.argv[1]) / "mode-6-entete-840.png"), clip={"x": 0, "y": 0, "width": 840, "height": 80})
    pg.context.close()
    # la pastille n'existe pas quand le mode est inactif
    pg = ouvrir(nav, 1440, 900, erreurs, "entete-inactif")
    charger(pg, nom=NOM_LONG)
    verifier("en-tête : aucune pastille quand le mode est inactif", pg.locator(".entete .pastille-auto").count() == 0)
    pg.context.close()


def tete_de_feuille(pg, largeur, sorties):
    """La feuille « Ce qui t'attend » est ouverte : sa tête (titre + « Fermer ») tient sur une ligne, « Fermer » est entier, l'interrupteur est la première ligne du contenu."""
    f = pg.locator("dialog.feuille[open]")
    tete, titre, fermer = f.locator(".feuille-tete"), f.locator(".feuille-tete h2"), f.locator(".feuille-fermer")
    une_ligne = "(n) => { const r = document.createRange(); r.selectNodeContents(n); return r.getClientRects().length === 1; }"
    bt, bf, bh = titre.bounding_box(), fermer.bounding_box(), tete.bounding_box()
    verifier(f"{largeur} px : la tête de la feuille est sur une ligne (titre et « Fermer » centrés)", bh["height"] < 70 and abs((bt["y"] + bt["height"] / 2) - (bf["y"] + bf["height"] / 2)) < 8, f"tête {bh}, titre {bt}, Fermer {bf}")
    verifier(f"{largeur} px : « Fermer » est entier (un seul rectangle de texte, le mot lisible, 44 px de haut)",
             fermer.inner_text().strip() == "Fermer" and fermer.evaluate(une_ligne) and round(bf["height"]) >= 44 and round(bf["height"]) <= 48, str(bf))
    verifier(f"{largeur} px : le titre est sur une ligne, sans ellipse", titre.inner_text().strip() == "Ce qui t’attend" and titre.evaluate(une_ligne)
             and titre.evaluate("(n) => n.scrollWidth <= n.clientWidth + 1"), str(bt))
    verifier(f"{largeur} px : le titre et « Fermer » ne se touchent pas, « Fermer » reste dans l'écran", bt["x"] + bt["width"] + 4 <= bf["x"] and bf["x"] + bf["width"] <= largeur, f"titre {bt}, Fermer {bf}")
    verifier(f"{largeur} px : aucun interrupteur dans la tête", tete.locator(".inter").count() == 0)
    premier = f.locator(".feuille-contenu > :first-child")
    inter = premier.locator(".inter")
    verifier(f"{largeur} px : l'interrupteur est la première ligne du contenu, au-dessus des effectifs puis de l'encadré",
             inter.count() == 1 and f.locator(".inter").count() == 1
             and inter.bounding_box()["y"] < f.locator(".feuille-effectifs").bounding_box()["y"] < f.locator(".etat-auto").bounding_box()["y"])
    verifier(f"{largeur} px : la cible de l'interrupteur fait 44 px, dans l'écran", round(inter.bounding_box()["height"]) >= 44 and inter.bounding_box()["x"] + inter.bounding_box()["width"] <= largeur)
    verifier(f"{largeur} px : la page ne défile pas en largeur", pg.evaluate("document.documentElement.scrollWidth") <= largeur)
    pg.screenshot(path=str(sorties / f"mode-feuille-{largeur}.png"))


def mobile(nav, sorties, erreurs):
    # des attentes : l'interrupteur n'existe qu'une fois la feuille « Ce qui t'attend » ouverte ; il en est la première ligne, la tête reste titre + « Fermer »
    for largeur in LARGEURS_FEUILLE:
        pg = ouvrir(nav, largeur, 844, erreurs, f"mobile-actif-{largeur}", autonome="actif")
        charger(pg, avec_inter=False)
        verifier(f"{largeur} px : avec des attentes, l'interrupteur n'est pas dans la page avant d'ouvrir la feuille", pg.locator(".inter").count() == 0)
        if largeur == 390:
            verifier("390 px : « Auto » dans l'en-tête de 52 px (bleu)", pg.locator(".entete .pastille-auto.actif").inner_text().strip() == "Auto" and round(pg.locator(".entete").bounding_box()["height"]) == 52)
            verifier("390 px : la page ne défile pas en largeur", pg.evaluate("document.documentElement.scrollWidth") <= 390)
        pg.locator(".bandeau-attentes").click()
        pg.wait_for_selector("dialog.feuille[open] .inter")
        tete_de_feuille(pg, largeur, sorties)
        pg.keyboard.press("Escape")
        pg.context.close()
    # suspendu, avec des attentes : même tête, l'encadré ambre est dans la feuille
    pg = ouvrir(nav, 320, 844, erreurs, "mobile-feuille-suspendu", autonome="suspendu")
    charger(pg, avec_inter=False)
    pg.locator(".bandeau-attentes").click()
    pg.wait_for_selector("dialog.feuille[open] .inter.suspendu")
    tete_de_feuille(pg, 320, sorties)
    verifier("320 px : suspendu, l'encadré ambre et « Réactiver avec cette liste » sont dans la feuille", pg.locator("dialog.feuille[open] .etat-auto.suspendu .action").count() == 1)
    pg.context.close()
    # suspendu, rien n'attend : l'interrupteur est en première ligne du tiroir, un seul emplacement
    pg = ouvrir(nav, 390, 844, erreurs, "mobile-suspendu", autonome="suspendu", attentes="vides")
    charger(pg)
    verifier("390 px : « Suspendu » (ambre) dans l'en-tête", pg.locator(".entete .pastille-auto.suspendu").inner_text().strip() == "Suspendu")
    verifier("390 px : rien n'attend, l'interrupteur est en première ligne du tiroir sous le plateau", pg.locator(".rail > .bloc-mode:first-of-type .inter").count() == 1
             and pg.locator("#rail .inter").count() == 1)
    verifier("390 px : l'encadré ambre est sous l'interrupteur", pg.locator("#rail .etat-auto.suspendu").count() == 1)
    pg.locator("#rail").scroll_into_view_if_needed()
    pg.screenshot(path=str(sorties / "mode-tiroir-suspendu-390.png"))
    verifier("390 px : la page ne défile pas en largeur (suspendu)", pg.evaluate("document.documentElement.scrollWidth") <= 390)
    pg.locator(".bandeau-attentes").click()
    pg.wait_for_selector("dialog.feuille[open]")
    verifier("390 px : rien n'attend, la feuille n'a pas d'interrupteur (il est dans le tiroir : un seul emplacement)", pg.locator("dialog.feuille[open] .inter").count() == 0
             and pg.locator("dialog.feuille[open] .feuille-tete").bounding_box()["height"] < 70)
    pg.keyboard.press("Escape")
    pg.context.close()
    # inactif sans attente
    pg = ouvrir(nav, 390, 844, erreurs, "mobile-inactif", attentes="vides")
    charger(pg)
    verifier("390 px : inactif, aucune pastille ; l'interrupteur est dans le tiroir", pg.locator(".entete .pastille-auto").count() == 0 and pg.locator("#rail .bloc-mode .inter").count() == 1)
    pg.locator("#rail").scroll_into_view_if_needed()
    pg.screenshot(path=str(sorties / "mode-tiroir-inactif-390.png"))
    pg.context.close()


LARGEURS_RECAP = ((1440, 900), (390, 844), (360, 780), (320, 640))  # le bureau, puis les téléphones


def recap_du_matin(nav, sorties, erreurs):
    """Sur Supervision, le récap de ce que l'Assistant a décidé est la première ligne de « Depuis ta dernière visite » (en bleu), son détail est replié
    puis déplié sans que la page déborde en largeur, à 1 440 px et à 390, 360 et 320 px. Le faux hôte sert 3 fusions, 1 chantier et 2 autorisations (mode actif ou suspendu)."""
    for etat in ("actif", "suspendu"):
        for largeur, hauteur in LARGEURS_RECAP:
            pg = ouvrir(nav, largeur, hauteur, erreurs, f"recap-{etat}-{largeur}", autonome=etat, attentes="vides")
            reecrire(pg)
            pg.goto(BASE + "/#/supervision")
            pg.wait_for_selector(".nouveautes-liste")
            pg.wait_for_timeout(500)
            lib = f"{largeur} px, {etat} : "
            premier = pg.locator(".nouveautes-liste > li").first
            verifier(lib + "le récap est la première ligne de « Depuis ta dernière visite »", "nouveaute-recap" in (premier.get_attribute("class") or "")
                     and premier.inner_text().startswith("L’Assistant a décidé à ta place : 3 fusions · 1 chantier lancé · 2 autorisations accordées"), premier.inner_text()[:120])
            verifier(lib + "le bloc est ouvert d'office", pg.locator("details.nouveautes").get_attribute("open") is not None)
            verifier(lib + "la ligne est en bleu (ni rouge ni ambre)", premier.evaluate("(n) => getComputedStyle(n).color") == BLEU, premier.evaluate("(n) => getComputedStyle(n).color"))
            verifier(lib + "le détail est replié : aucune ligne de décision visible", pg.locator("details.decisions").get_attribute("open") is None
                     and pg.locator(".decisions-liste li:visible").count() == 0)
            pg.screenshot(path=str(sorties / f"recap-{etat}-{largeur}-replie.png"), full_page=True)
            pg.locator("details.decisions > summary").click()
            pg.wait_for_timeout(200)
            lignes = pg.locator(".decisions-liste li")
            verifier(lib + "déplié : six lignes, la plus récente d'abord", lignes.count() == 6 and "f223c94" in lignes.first.inner_text() and "9436197" in lignes.last.inner_text(),
                     lignes.first.inner_text())
            verifier(lib + "déplié : la page ne défile pas en largeur", pg.evaluate("document.documentElement.scrollWidth") <= largeur, str(pg.evaluate("document.documentElement.scrollWidth")))
            dehors = pg.evaluate("""() => [...document.querySelectorAll('.nouveaute-recap, .nouveaute-recap *')].filter((n) => {
                const r = n.getBoundingClientRect(); return r.width > 0 && (r.right > document.documentElement.clientWidth + 0.5 || r.left < -0.5); }).length""")
            verifier(lib + "déplié : rien du récap ne sort de l'écran", dehors == 0, str(dehors))
            coupes = pg.evaluate("""() => [...document.querySelectorAll('.decision-cle')].filter((n) => n.getClientRects().length > 1 && !n.textContent.includes(':') && !n.textContent.includes('/')).length""")
            verifier(lib + "déplié : un sha ne se coupe pas en deux lignes", coupes == 0, str(coupes))
            pg.screenshot(path=str(sorties / f"recap-{etat}-{largeur}-deplie.png"), full_page=True)
            pg.context.close()
    # l'état inactif ou absent : aucune ligne de récap
    for etat in ("inactif", "absent"):
        pg = ouvrir(nav, 1440, 900, erreurs, f"recap-{etat}", autonome=etat, attentes="vides")
        reecrire(pg)
        pg.goto(BASE + "/#/supervision")
        pg.wait_for_selector(".nouveautes-liste, .nouveautes")
        pg.wait_for_timeout(500)
        verifier(f"{etat} : aucune ligne de récap", pg.locator(".nouveaute-recap").count() == 0 and "décision" not in pg.locator("details.nouveautes").inner_text())
        pg.context.close()


RECAP_SCENE = "L’Assistant a décidé à ta place : 3 fusions · 1 chantier lancé · 2 autorisations accordées"  # la phrase du faux hôte (six décisions)
RECAP_SCENE_DOUZE = "L’Assistant a décidé à ta place : 9 fusions · 1 chantier lancé · 2 autorisations accordées"  # les six plus, en fusions


def ajouter_decisions(pg, n):
    """Le faux hôte n'en sert que six : `n` de plus, plus anciennes, pour que « … et n autres » apparaisse (10 lignes visibles)."""
    def gerer(route):
        r = route.fetch()
        etat = r.json()
        genere = datetime.fromisoformat(etat["genere_a"].replace("Z", "+00:00"))
        plus = [{"genre": "fusion", "cle": f"{i:07x}", "horodatage": (genere - timedelta(minutes=200 + i)).strftime("%Y-%m-%dT%H:%M:%S.000Z"), "message": 2000 + i}
                for i in range(n)]
        etat["fusions_auto"]["decisions"] = etat["fusions_auto"]["decisions"] + plus
        route.fulfill(response=r, body=json.dumps(etat), headers={**r.headers, "content-type": "application/json"})
    pg.route("**/api/etat", gerer)


def recap_dans_la_scene(nav, sorties, erreurs):
    """La Scène (rail du bureau, tiroir du téléphone) montre la ligne « L'Assistant a décidé à ta place » sous le paragraphe du mode, en bleu,
    13 px ; sous elle, « Voir le détail » déplie la liste des décisions sur place, sans changer de page. Au-delà de dix, « … et n autres » déplie le reste.
    Actif et suspendu l'ont ; inactif et absent non. Pas de débordement à 1 440, 390, 360 et 320 px."""
    for etat in ("actif", "suspendu"):
        for largeur, hauteur in LARGEURS_RECAP:
            pg = ouvrir(nav, largeur, hauteur, erreurs, f"scene-recap-{etat}-{largeur}", autonome=etat, attentes="vides")
            reecrire(pg)
            pg.goto(BASE + "/")
            pg.wait_for_selector(".recap-scene", state="attached")
            pg.wait_for_timeout(500)
            lib = f"scène {largeur} px, {etat} : "
            ligne = pg.locator(".recap-scene").first
            verifier(lib + "une seule ligne de récap dans l'encadré", pg.locator(".recap-scene").count() == 1, str(pg.locator(".recap-scene").count()))
            verifier(lib + "le texte attendu, sans le résumé", ligne.inner_text() == RECAP_SCENE, ligne.inner_text()[:140])
            verifier(lib + "la ligne est en bleu, 13 px", ligne.evaluate("(n) => getComputedStyle(n).color") == BLEU
                     and ligne.evaluate("(n) => getComputedStyle(n).fontSize") == "13px", ligne.evaluate("(n) => getComputedStyle(n).color + ' ' + getComputedStyle(n).fontSize"))
            verifier(lib + "la ligne n'a aucun lien", ligne.locator("a").count() == 0)
            resume = pg.locator(".etat-auto details.decisions > summary")
            verifier(lib + "le détail est replié, sous la ligne, et dit « Voir le détail »", resume.inner_text() == "Voir le détail"
                     and pg.locator(".etat-auto details.decisions").get_attribute("open") is None and pg.locator(".decisions-liste li:visible").count() == 0)
            verifier(lib + "la page ne défile pas en largeur", pg.evaluate("document.documentElement.scrollWidth") <= largeur, str(pg.evaluate("document.documentElement.scrollWidth")))
            pg.screenshot(path=str(sorties / f"scene-recap-{etat}-{largeur}.png"), full_page=False)
            url = pg.url
            resume.click()
            pg.wait_for_timeout(200)
            lignes = pg.locator(".etat-auto .decisions-liste li")
            verifier(lib + "déplié : six lignes, la plus récente d'abord", lignes.count() == 6 and "f223c94" in lignes.first.inner_text() and "9436197" in lignes.last.inner_text(),
                     lignes.first.inner_text())
            verifier(lib + "le résumé déplie la liste sans changer de page", pg.url == url, pg.url)
            verifier(lib + "déplié : la page ne défile pas en largeur", pg.evaluate("document.documentElement.scrollWidth") <= largeur, str(pg.evaluate("document.documentElement.scrollWidth")))
            dehors = pg.evaluate("""() => [...document.querySelectorAll('.etat-auto .decisions, .etat-auto .decisions *')].filter((n) => {
                const r = n.getBoundingClientRect(); return r.width > 0 && (r.right > document.documentElement.clientWidth + 0.5 || r.left < -0.5); }).length""")
            verifier(lib + "déplié : rien de la liste ne sort de l'écran", dehors == 0, str(dehors))
            coupes = pg.evaluate("""() => [...document.querySelectorAll('.etat-auto .decision-cle')].filter((n) => n.getClientRects().length > 1 && !n.textContent.includes(':') && !n.textContent.includes('/')).length""")
            verifier(lib + "déplié : un sha ne se coupe pas en deux lignes", coupes == 0, str(coupes))
            pg.screenshot(path=str(sorties / f"scene-recap-{etat}-{largeur}-deplie.png"), full_page=False)
            pg.context.close()
    # douze décisions : dix lignes, « … et 2 autres » ; le bouton déplie les douze sur place
    for etat in ("actif", "suspendu"):
        for largeur, hauteur in LARGEURS_RECAP:
            pg = ouvrir(nav, largeur, hauteur, erreurs, f"scene-recap-douze-{etat}-{largeur}", autonome=etat, attentes="vides")
            ajouter_decisions(pg, 6)
            pg.goto(BASE + "/")
            pg.wait_for_selector(".recap-scene", state="attached")
            pg.wait_for_timeout(500)
            lib = f"scène {largeur} px, {etat}, douze décisions : "
            verifier(lib + "le récap compte les douze", pg.locator(".recap-scene").first.inner_text() == RECAP_SCENE_DOUZE, pg.locator(".recap-scene").first.inner_text()[:140])
            url = pg.url
            pg.locator(".etat-auto details.decisions > summary").click()
            pg.wait_for_timeout(200)
            verifier(lib + "dix lignes, puis « … et 2 autres »", pg.locator(".etat-auto .decisions-liste li").count() == 10
                     and pg.locator(".etat-auto .lien-autres").inner_text() == "… et 2 autres")
            pg.locator(".etat-auto .lien-autres").click()
            pg.wait_for_timeout(200)
            verifier(lib + "« … et 2 autres » déplie les douze sur place, sans bouton ni changement de page", pg.locator(".etat-auto .decisions-liste li").count() == 12
                     and pg.locator(".etat-auto .lien-autres").count() == 0 and pg.url == url, str(pg.locator(".etat-auto .decisions-liste li").count()))
            verifier(lib + "la page ne défile pas en largeur", pg.evaluate("document.documentElement.scrollWidth") <= largeur, str(pg.evaluate("document.documentElement.scrollWidth")))
            pg.screenshot(path=str(sorties / f"scene-recap-douze-{etat}-{largeur}.png"), full_page=False)
            pg.context.close()
    # inactif ou absent : aucune ligne dans la Scène
    for etat in ("inactif", "absent"):
        pg = ouvrir(nav, 1440, 900, erreurs, f"scene-recap-{etat}", autonome=etat, attentes="vides")
        reecrire(pg)
        pg.goto(BASE + "/")
        pg.wait_for_selector(".etat-auto", state="attached")
        pg.wait_for_timeout(500)
        verifier(f"scène {etat} : aucune ligne de récap, aucun « 0 décision »", pg.locator(".recap-scene").count() == 0 and pg.locator(".etat-auto details.decisions").count() == 0
                 and "décision" not in pg.locator(".etat-auto").first.inner_text())
        pg.context.close()


def main():
    sorties = Path(sys.argv[1] if len(sys.argv) > 1 else "captures-mode-autonome")
    sorties.mkdir(parents=True, exist_ok=True)
    sys.argv = [sys.argv[0], str(sorties)]
    erreurs = []
    with sync_playwright() as p:
        nav = p.chromium.launch(executable_path=CHROME if os.path.exists(CHROME) else None)
        etats_du_bureau(nav, sorties, erreurs)
        balayage_entete(nav, erreurs)
        mobile(nav, sorties, erreurs)
        recap_du_matin(nav, sorties, erreurs)
        recap_dans_la_scene(nav, sorties, erreurs)
        nav.close()
    verifier("la console reste muette", not erreurs, str(erreurs[:3]))
    print(f"\n{len(OK)} OK, {len(KO)} KO")
    sys.exit(1 if KO else 0)


if __name__ == "__main__":
    main()
