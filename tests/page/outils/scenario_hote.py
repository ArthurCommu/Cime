"""Scénario de la page en mode hôte contre hote_factice.py (port CIME_PORT_TEST, 8791 par défaut ; état neuf).

Les attentes de l'utilisateur vivent dans le rail de la scène (#/), trois cartes au plus, triées par genre (autorisation, décision, donnée,
clôture, compte rendu) puis la plus ancienne d'abord : ici perm-d41, msg-59 et msg-60 ; msg-62 (clôture) et msg-58 (compte rendu) sont
derrière « 2 autres points ▾ » (le bouton déplie la liste complète dans le rail, « replier ▴ » la replie) et paraissent d'eux-mêmes
quand des cartes sont traitées. Les parcours d'action sont rejoués dans cet ordre : perm-d41 en tête, puis msg-59, msg-60, et
msg-58 / msg-62 en dépliant le rail si besoin."""
import json
import os
import re
import sys
import urllib.request

from playwright.sync_api import sync_playwright

PORT = os.environ.get("CIME_PORT_TEST", "8791")
BASE = f"http://127.0.0.1:{PORT}"
CHROME = os.environ.get("CIME_CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
OK = []
KO = []


def regler(**kw):
    q = "&".join(f"{k}={v}" for k, v in kw.items())
    urllib.request.urlopen(f"{BASE}/test/regler?{q}").read()


def requetes():
    return json.loads(urllib.request.urlopen(f"{BASE}/test/requetes").read())


def verifier(nom, cond, detail=""):
    (OK if cond else KO).append(nom)
    print(("OK  " if cond else "KO  ") + nom + (f" — {detail}" if detail else ""))


def posts(depuis):
    return [r for r in requetes()[depuis:] if r["m"] == "POST"]


def deplier_si_besoin(pg, attente):
    """La carte `attente` est derrière « n autres points ▾ » : on déplie le rail pour la voir."""
    if pg.locator(f".attente[data-attente={attente}]").count() == 0 and pg.locator("#rail .lien-autres").count():
        pg.locator("#rail .lien-autres").click()


with sync_playwright() as p:
    nav = p.chromium.launch(executable_path=CHROME, headless=True)
    pg = nav.new_page(viewport={"width": 1440, "height": 1000})
    erreurs = []
    pg.on("console", lambda m: erreurs.append(m.text) if m.type in ("error", "warning") else None)
    pg.on("pageerror", lambda e: erreurs.append(str(e)))

    # 0. hôte injoignable au chargement, puis retour
    regler(etat="panne")
    pg.goto(f"{BASE}/#/")
    pg.wait_for_timeout(1500)
    texte = pg.locator("body").inner_text()
    # « essai n° 1 » n'est plus que dans l'info-bulle (attribut title) de la carte « Hôte injoignable »
    verifier("injoignable : page lisible", "Hôte injoignable" in texte and "essai n° 1" in (pg.locator(".injoignable-carte").get_attribute("title") or ""),
             texte[:80].replace("\n", " "))
    regler(etat="ok")
    pg.wait_for_timeout(3500)
    verifier("injoignable : réessai puis page normale (3 cartes dans le rail, 2 autres points ▾)",
             pg.locator("#rail .attente").count() == 3 and "2 autres points ▾" in pg.locator("#rail").inner_text())
    ordre = pg.locator("#rail .attente").evaluate_all("(cs) => cs.map((c) => c.dataset.attente)")
    verifier("le rail trie par genre : autorisation, décision, donnée", ordre == ["perm-d41", "msg-59", "msg-60"], str(ordre))
    pg.locator("#rail .lien-autres").click()
    ordre = pg.locator("#rail .attente").evaluate_all("(cs) => cs.map((c) => c.dataset.attente)")
    verifier("« 2 autres points ▾ » déplie les cinq attentes, clôture puis compte rendu en dernier",
             ordre == ["perm-d41", "msg-59", "msg-60", "msg-62", "msg-58"] and "replier ▴" in pg.locator("#rail .lien-autres").inner_text(), str(ordre))
    pg.locator("#rail .lien-autres").click()
    verifier("« replier ▴ » revient à trois cartes", pg.locator("#rail .attente").count() == 3 and "2 autres points ▾" in pg.locator("#rail").inner_text())
    erreurs.clear()  # le 503 voulu est loggé par Chrome

    # 1. instantané + flux
    n0 = len(requetes())
    pg.wait_for_timeout(4000)
    gets = [r["chemin"] for r in requetes()[n0:] if r["m"] == "GET"]
    verifier("flux : pas de relecture de /api/etat après le chargement", "/api/etat" not in gets, str(gets))
    verifier("journal relu après un instantané (≤ 1 / 5 s)", 1 <= gets.count("/api/journal") <= 2, str(gets.count("/api/journal")))
    verifier("en-tête : à jour", pg.locator(".age-donnee").get_attribute("data-niveau") == "ok", pg.locator(".age-donnee").inner_text())

    # 2. Refuser : confirmation, Annuler n'envoie rien
    n0 = len(requetes())
    pg.locator(".attente[data-attente=perm-d41] button", has_text="Refuser").click()
    dlg = pg.locator("dialog[open]")
    verifier("refuser : confirmation affichée",
             "Refuser arrête l’agent jusqu’à ce que l’Assistant le relance. Confirmer ?" in dlg.inner_text())
    verifier("refuser : boutons Annuler + Refuser",
             [b.strip() for b in dlg.locator("button").all_inner_texts()] == ["Annuler", "Refuser"])
    dlg.locator("button", has_text="Annuler").click()
    pg.wait_for_timeout(300)
    verifier("refuser : Annuler n'envoie rien", posts(n0) == [])

    # 3. Refuser confirmé, l'hôte répond « refuse » → toast ambre, l'attente reste
    regler(actions="refuse")
    pg.locator(".attente[data-attente=perm-d41] button", has_text="Refuser").click()
    pg.locator("dialog[open] button.bouton-danger").click()
    pg.wait_for_timeout(500)
    ps = posts(n0)
    verifier("refuser : corps exact", ps and ps[-1]["chemin"] == "/api/actions/refuser" and ps[-1]["corps"] == {"attente_id": "perm-d41"}, str(ps[-1:]))
    verifier("refuse → toast ambre avec message", pg.locator(".toast-ambre").count() == 1 and "attente déjà traitée" in pg.locator(".toast-ambre").inner_text())
    verifier("refuse → l'attente reste avec ses boutons", pg.locator(".attente[data-attente=perm-d41] button", has_text="Autoriser").is_enabled())

    # 4. erreur métier, puis réponse cassée (500 non JSON) → toast rouge, on peut réessayer
    regler(actions="erreur")
    pg.locator(".attente[data-attente=perm-d41] button", has_text="Autoriser").click()
    pg.wait_for_timeout(500)
    verifier("erreur → toast rouge avec message", "tmux n’a pas répondu" in pg.locator(".toast-rouge").last.inner_text())
    regler(actions="casse")
    pg.locator(".attente[data-attente=perm-d41] button", has_text="Autoriser").click()
    pg.wait_for_timeout(500)
    verifier("500 non JSON → toast rouge", "HTTP 500" in pg.locator(".toast-rouge").last.inner_text())

    # 5. Autoriser lent : bouton désactivé pendant l'appel, puis « envoyé… », puis disparition
    regler(actions="lent")
    n0 = len(requetes())
    pg.locator(".attente[data-attente=perm-d41] button", has_text="Autoriser").click()
    pg.wait_for_timeout(300)
    verifier("pendant l'appel : boutons désactivés", pg.locator(".attente[data-attente=perm-d41] button", has_text="Autoriser").is_disabled())
    pg.locator(".attente[data-attente=perm-d41] button", has_text="Autoriser").click(force=True)
    pg.wait_for_timeout(2000)
    ps = posts(n0)
    verifier("pas de double envoi", len(ps) == 1, str(len(ps)))
    verifier("autoriser : corps exact", ps and ps[0]["chemin"] == "/api/actions/autoriser" and ps[0]["corps"] == {"attente_id": "perm-d41"})
    verifier("ok → « envoyé, en attente de confirmation »",
             "envoyé, en attente de confirmation" in pg.locator(".attente[data-attente=perm-d41]").inner_text())
    verifier("ok → toast", "Inscrit au journal" in pg.locator(".toast").last.inner_text())
    pg.wait_for_timeout(3500)
    verifier("prochain instantané → attente retirée", pg.locator(".attente[data-attente=perm-d41]").count() == 0)
    regler(actions="ok")

    # 6. Accorder la fusion : msg-59 est une décision `fusion:` ; son bouton n'est plus « Trancher ».
    # L'exemple n'a aucune décision d'un autre objet : le parcours « Trancher » (action trancher, champ de réponse) n'y est pas rejouable.
    n0 = len(requetes())
    carte = pg.locator(".attente[data-attente=msg-59]")
    verifier("accorder : la décision de fusion propose « Accorder la fusion » et « Refuser », pas « Trancher »",
             carte.locator("button", has_text="Accorder la fusion").count() == 1 and carte.locator("button", has_text="Refuser").count() == 1
             and carte.locator("button", has_text="Trancher").count() == 0)
    carte.locator("button", has_text="Accorder la fusion").click()
    verifier("accorder : le dialogue dit l'équipe et le commit, et que la page ne touche à aucune branche",
             all(m in pg.locator("dialog[open]").inner_text() for m in ("page", "abc1234", "aucune branche")), pg.locator("dialog[open]").inner_text()[:120])
    pg.locator("dialog[open] button[type=submit]").click()
    pg.wait_for_timeout(600)
    ps = posts(n0)
    verifier("accorder : corps exact", ps and ps[0]["chemin"] == "/api/actions/accorder" and ps[0]["corps"] == {"attente_id": "msg-59"}, str(ps))
    verifier("accorder : dialogue fermé sur ok", pg.locator("dialog[open]").count() == 0)

    # 7. Déposer : multipart
    n0 = len(requetes())
    pg.locator(".attente[data-attente=msg-60] input[type=file]").set_input_files(
        [{"name": "tarifs.json", "mimeType": "application/json", "buffer": b'{"a": 1}'},
         {"name": "notes.txt", "mimeType": "text/plain", "buffer": b"abc"}])
    pg.wait_for_timeout(600)
    ps = posts(n0)
    c = ps[0]["corps"] if ps else {}
    verifier("déposer : multipart avec attente_id et fichiers", ps and ps[0]["chemin"] == "/api/actions/deposer"
             and ps[0]["type"].startswith("multipart/form-data") and c.get("attente_id") == ["msg-60"]
             and [f["fichier"] for f in c.get("fichier", [])] == ["tarifs.json", "notes.txt"], json.dumps(c))

    # 8. Lire + Marquer comme lu (texte depuis /api/fichier)
    n0 = len(requetes())
    deplier_si_besoin(pg, "msg-58")
    pg.locator(".attente[data-attente=msg-58] button", has_text="Lire").click()
    pg.wait_for_timeout(500)
    verifier("lire : texte complet lu sur l'hôte", "Contenu de test du fichier" in pg.locator("dialog[open]").inner_text())
    pg.locator("dialog[open] button", has_text="Marquer comme lu").click()
    pg.wait_for_timeout(500)
    ps = posts(n0)
    gets = [r for r in requetes()[n0:] if r["chemin"] == "/api/fichier"]
    verifier("lire : chemin demandé", gets and gets[0]["requete"].startswith("chemin=.orga%2F"), str(gets))
    verifier("lu : corps exact", ps and ps[0]["chemin"] == "/api/actions/lu" and ps[0]["corps"] == {"attente_id": "msg-58"})

    # 9. Clôturer
    n0 = len(requetes())
    deplier_si_besoin(pg, "msg-62")
    pg.locator(".attente[data-attente=msg-62] button", has_text="Clôturer").click()
    pg.locator("dialog[open] input[type=text]").fill("fondatio")
    verifier("clôturer : bouton désactivé tant que le nom diffère", pg.locator("dialog[open] button[type=submit]").is_disabled())
    pg.locator("dialog[open] input[type=text]").fill("fondation")
    pg.locator("dialog[open] button[type=submit]").click()
    pg.wait_for_timeout(600)
    ps = posts(n0)
    verifier("clôturer : corps exact", ps and ps[0]["chemin"] == "/api/actions/cloturer"
             and ps[0]["corps"] == {"equipe": "fondation", "confirmation": "fondation"}, str(ps))
    verifier("POST : Origin du même hôte", all(r["origin"] in (None, BASE) for r in posts(0)))
    pg.wait_for_timeout(3500)
    verifier("toutes les attentes traitées", "Rien ne t’attend." in pg.locator("#rail").inner_text())

    # 10. Journal : celui de l'hôte
    pg.goto(f"{BASE}/#/journal")
    pg.wait_for_timeout(1200)
    lignes = pg.locator(".journal-ligne")
    verifier("journal de l'hôte (exemple + 5 actions ok)", lignes.count() == 11 + 5, str(lignes.count()))
    verifier("navigation : aucun onglet courant sur le journal", pg.locator(".nav a[aria-current=page]").count() == 0)

    # 11. Fil : texte complet, 404 clair
    pg.goto(f"{BASE}/#/fil?equipe=cadrage")
    pg.wait_for_timeout(1000)
    for b in pg.locator(".fil-ligne > button").all():
        b.click()
    pg.wait_for_timeout(500)
    t = " | ".join(pg.locator(".fil-texte:not([hidden])").all_inner_texts())
    verifier("fil : 404 → message clair", "fichier introuvable" in t, t[:120].replace("\n", " "))
    verifier("fil : filtre lu dans l'ancre", pg.locator("select").first.input_value() == "cadrage")

    # 12. Retour arrière du navigateur
    pg.go_back()
    pg.wait_for_timeout(800)
    verifier("bouton Retour → journal", pg.locator(".section-tete h2").first.inner_text() == "Journal")

    # 13. Terminal : toutes les 5 s, seulement sur le détail d'équipe
    n0 = len(requetes())
    pg.goto(f"{BASE}/#/equipe/hote")
    pg.wait_for_timeout(11_000)
    term = [r for r in requetes()[n0:] if r["chemin"].endswith("/terminal")]
    verifier("terminal : 3 lectures en 11 s", len(term) == 3, str(len(term)))
    verifier("terminal : agent choisi", term and term[0]["chemin"] == "/api/agents/coord-hote/terminal")
    verifier("terminal : capture affichée", "capturé il y a" in pg.locator(".terminal-meta").inner_text())
    pg.evaluate("location.hash = '#/supervision'")
    n0 = len(requetes())
    pg.wait_for_timeout(6000)
    verifier("terminal : arrêt hors du détail", not [r for r in requetes()[n0:] if r["chemin"].endswith("/terminal")])

    # 14. Flux muet > 25 s → rouge, puis retour
    regler(flux="muet")
    pg.wait_for_timeout(27_000)
    age = pg.locator(".age-donnee")
    # la pastille n'a que deux états : « En direct » (vert) et « Figé · n s » (rouge) ; l'info-bulle dit que l'hôte ne donne plus de nouvelles
    verifier("flux muet → rouge « Figé · n s », info-bulle « plus aucune nouvelle de l’hôte »",
             age.get_attribute("data-niveau") == "rouge" and age.get_attribute("data-flux") == "interrompu"
             and re.match(r"^Figé · .+$", age.inner_text().replace("\n", " ").strip()) is not None
             and "plus aucune nouvelle de l’hôte" in (age.get_attribute("title") or ""), age.inner_text().replace("\n", " "))
    regler(flux="normal")
    pg.wait_for_timeout(4000)
    verifier("flux revenu → normal", age.get_attribute("data-niveau") == "ok", pg.locator(".age-donnee").inner_text().replace("\n", " "))

    # 15. Flux coupé (connexion fermée, reconnexions en 503) → rouge, puis retour
    regler(flux="coupe")
    pg.wait_for_timeout(2000)
    verifier("flux coupé → rouge", pg.locator(".age-donnee").get_attribute("data-niveau") == "rouge", pg.locator(".age-donnee").inner_text().replace("\n", " "))
    regler(flux="normal")
    pg.wait_for_timeout(10_000)
    verifier("flux rétabli → reconnexion seule", pg.locator(".age-donnee").get_attribute("data-niveau") == "ok", pg.locator(".age-donnee").inner_text().replace("\n", " "))

    # 16. routes appelées : uniquement celles de l'hôte
    chemins = sorted({r["chemin"] for r in requetes() if not r["chemin"].startswith("/test/")})
    print("chemins appelés :", chemins)
    autres = [e for e in erreurs if "503" not in e and "Failed to load resource" not in e and "EventSource" not in e]
    verifier("aucune erreur JS", not autres, str(autres[:3]))
    nav.close()

print(f"\n{len(OK)} OK, {len(KO)} KO : {KO}")
sys.exit(1 if KO else 0)
