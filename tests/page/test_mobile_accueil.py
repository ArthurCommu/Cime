"""L'accueil sur téléphone, et trois retouches du rail.

Analyse de texte du JS et du CSS de static/ (pas de navigateur dans pytest), même convention que test_rail_accueil.py :
`verifier_mobile_accueil(js)` lève AssertionError ; la table MUTATIONS prouve qu'elle échoue quand on casse chaque comportement.
`trierAttentes` est de plus exécutée par node (si node est installé) sur des attentes réelles, avec ses propres mutations.
Le rendu réel (en-tête de 52 px, barre du bas sans chevauchement, plateau de 540 px avec ses commandes au-dessus de la ligne de
flottaison, aucune barre horizontale de page à 390 px, bandeau → feuille des attentes, toucher d'une pièce → feuille de détail à
70 %, Échap / Fermer) est vérifié dans un vrai navigateur par tests/page/outils/scenario_mobile.py.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

PAGE = Path(__file__).resolve().parents[2] / "src" / "cime" / "page"
STATIC = PAGE / "static"
TAILLES_PERMISES = {"11", "12", "13", "14", "16", "20"}


def _corps(texte, debut, fin):
    i = texte.find(debut)
    assert i >= 0, debut
    j = texte.find(fin, i)
    assert j >= 0, fin
    return texte[i:j]


def _regle(css, selecteur):
    """Le corps de la règle CSS dont le sélecteur est exactement `selecteur` (à l'indentation près)."""
    m = re.search(r"(?:^|\n) *" + re.escape(selecteur) + r" \{([^}]*)\}", css)
    assert m, selecteur
    return m.group(1)


def _avant_le_bloc(css):
    """Tout le CSS hors du bloc téléphone : ce que voit le bureau."""
    debut = css.index("@media (max-width: 760px) {")
    fin = css.index("\n}\n", debut) + 3
    return css[:debut] + css[fin:]


def verifier_mobile_accueil(js):
    commun, app, scene, rail, mobile_js, css, index = (
        js[n] for n in ("commun.js", "app.js", "vues/scene.js", "vues/rail.js", "vues/mobile.js", "style.css", "index.html"))

    # 1. le point de rupture : 760 px, partout le même ; un seul bloc @media pour les règles mobiles de l'accueil
    assert "export const POINT_DE_RUPTURE = 760;" in mobile_js
    assert "window.matchMedia(`(max-width: ${POINT_DE_RUPTURE}px)`)" in mobile_js
    assert "export const estTelephone = () => formatTelephone.matches;" in mobile_js
    assert css.count("@media (max-width: 760px)") == 1
    bloc = _corps(css, "@media (max-width: 760px) {\n  :root", "\n}\n")
    bureau = _avant_le_bloc(css)

    # 2. le bureau ne bouge pas : ce que le téléphone ajoute est masqué hors du bloc, et ses mesures n'y sont pas
    assert ".bandeau-attentes, .barre-onglets, .demander-icone { display: none; }" in bureau
    for selecteur in (".bandeau-attentes", ".barre-onglets"):
        assert len(re.findall(re.escape(selecteur) + r"(?![-\w])", bureau)) == 1, selecteur  # une seule règle hors du bloc : celle qui masque
    # la seule exception : « Demander à l'Assistant » réduit à son icône entre 761 et 900 px (la pastille du mode autonome prend sa place)
    bureau_strict = bureau.replace("  .entete .demander { width: 40px; height: 40px;", "  .entete .demander {")
    for mesure in ("height: 540px", "height: 52px", "min-height: 52px", "width: 40px; height: 40px", "position: fixed; left: 0; right: 0; bottom: 0"):
        assert mesure not in bureau_strict, mesure
    assert "min-height: 56px" in _regle(bureau, ".entete") and "height: calc(100vh - 56px - 40px)" in _regle(bureau, ".plateau")
    assert "grid-template-columns: minmax(0, 1fr) 344px" in _regle(bureau, ".accueil")
    assert "@font-face" not in css  # ni police d'icônes ni bibliothèque : des tracés en ligne
    assert ":hover" not in bloc and ":hover" not in _corps(css, "/* ---------- Les feuilles", "/* ---------- Téléphone")  # aucun survol indispensable

    # 3. l'en-tête de 52 px, sur une ligne : onglets et compteur partent, la pastille, ⚠ et le bouton restent
    assert "  .entete { height: 52px; min-height: 52px; padding: 0 12px; gap: 8px; }" in bloc
    assert "  .entete-titres { flex: 1; min-width: 0; margin-right: 0; }" in bloc
    assert "overflow: hidden; text-overflow: ellipsis" in _regle(bloc, ".entete h1")
    assert "  .nav, .compteur-attentes, .entete-etat .pilule:not(.age-donnee) { display: none; }" in bloc
    assert "  .entete-etat { flex: none; gap: 8px; }" in bloc
    assert "sources-echec" not in bloc and ".age-donnee {" not in bloc

    # 4. le bouton « Demander à l'Assistant » devient un carré de 40×40 à icône ; libellé, info-bulle et phrase de hiérarchie inchangés
    demander = _regle(bloc, ".demander")
    assert "width: 40px; height: 40px" in demander and "padding: 0;" in demander
    assert "display: none" in _regle(bloc, ".demander-texte") and "display: block" in _regle(bloc, ".demander-icone")
    assert "inset: -2px" in _regle(bloc, ".demander::before")
    entete = _corps(commun, "function entete(ctx)", "\n}\n")
    assert ("el('button', { type: 'button', class: 'bouton demander', title: TITRE_DEMANDER, 'aria-label': 'Demander à l’Assistant', onclick: dialogueDemander },\n"
            "        icone('bulle', 'demander-icone'), el('span', { class: 'demander-texte' }, 'Demander à l’Assistant'))") in entete
    assert "bulle: [" in commun

    # 5. les icônes : du SVG en ligne, sans bibliothèque ; une par onglet de la barre
    icone = _corps(commun, "export function icone(", "\n}\n")
    assert 'stroke="currentColor"' in icone and "<svg " in icone and "aria-hidden=\"true\"" in icone and "ICONES[nom].map(" in icone
    assert "innerHTML" in icone and "createElementNS" not in commun  # le balisage vient de la table ICONES, jamais d'une donnée
    table = _corps(commun, "export const ICONES = {", "\n};\n")
    assert re.findall(r"^  (\w+): \[", table, re.M) == ["bulle", "scene", "supervision", "fil"]
    pages = _corps(commun, "export const PAGES = [", "\n];\n")
    assert re.findall(r"id: '(\w+)'", pages) == ["scene", "supervision", "fil"]  # pas de Journal dans la barre : un lien en pied de Supervision

    # 6. la barre d'onglets : trois onglets, icône + libellé, l'onglet courant marqué, 64 px fixe, zone sûre, rendue à chaque affichage
    barre = _corps(mobile_js, "export function barreOnglets(", "\n}\n")
    assert "el('nav', { class: 'barre-onglets', 'aria-label': 'Pages' }," in barre
    assert "PAGES.map((p) => el('a', { href: p.href, 'aria-current': p.id === ctx.page ? 'page' : null }, icone(p.id), el('span', {}, p.titre)))" in barre
    regle = _regle(bloc, ".barre-onglets")
    assert "position: fixed; left: 0; right: 0; bottom: 0" in regle and "display: flex" in regle
    assert "height: calc(64px + env(safe-area-inset-bottom, 0px))" in regle and "padding-bottom: env(safe-area-inset-bottom, 0px)" in regle
    lien = _regle(bloc, ".barre-onglets a")
    assert "min-height: 44px" in lien and "font-size: 11px" in lien and "flex-direction: column" in lien and "flex: 1" in lien
    assert "color: var(--texte)" in _regle(bloc, '.barre-onglets a[aria-current="page"]')
    assert "color: var(--ambre)" in _regle(bloc, '.barre-onglets a[aria-current="page"] svg')
    assert "viewport-fit=cover" in index
    rendre = _corps(mobile_js, "export function rendreMobile(", "\n}\n")
    assert "entete.after(bandeau)" in rendre and "page.append(barreOnglets(ctx))" in rendre and "majFeuilleAttentes(ctx.etat)" in rendre
    assert "import { rendreMobile } from './vues/mobile.js';" in app
    ordre = [app.find("rendreSocle({"), app.find("rendreMobile(ctx);"), app.find("VUES[route.page].rendre(ctx)")]
    assert 0 <= ordre[0] < ordre[1] < ordre[2], ordre  # le socle, puis le téléphone, puis l'écran

    # 7. tous les écrans gardent leur fin au-dessus de la barre
    assert "padding-bottom: calc(64px + env(safe-area-inset-bottom, 0px) + 24px)" in _regle(bloc, ".page-corps")
    assert "calc(64px + env(safe-area-inset-bottom, 0px) + 16px)" in _regle(bloc, ".page-corps.sur-scene")
    assert "min-height: 44px" in _regle(bloc, ".attente .bouton")

    # 8. un seul bandeau d'attentes, sous l'en-tête : vert sur la Scène seulement, ambre partout s'il y a des points, absent sinon
    bandeau = _corps(mobile_js, "export function bandeauAttentes(", "\n}\n")
    assert "if (attentes === null) return null;" in bandeau
    assert "if (n === 0 && ctx.page !== 'scene') return null;" in bandeau
    assert "n === 0 ? '✓ Rien ne t’attend' : `${pluriel(n, 'point')} ${n === 1 ? 't’attend' : 't’attendent'}`" in bandeau
    assert "el('button', { type: 'button', class: `bandeau-attentes ${n === 0 ? 'bandeau-calme' : 'bandeau-ambre'}`," in bandeau
    assert "onclick: () => ouvrirFeuilleAttentes()" in bandeau and "'›'" in bandeau
    assert "min-height: 44px" in _regle(bloc, ".bandeau-attentes") and "display: flex" in _regle(bloc, ".bandeau-attentes") and "width: 100%" in _regle(bloc, ".bandeau-attentes")
    assert "var(--vert-fond)" in _regle(bloc, ".bandeau-calme") and "var(--ambre-fond)" in _regle(bloc, ".bandeau-ambre")
    assert "bandeau" not in app.lower() and "bandeau" not in rail.lower()

    # 9. le plateau : pleine largeur, 540 px, la page ne glisse pas ; les commandes restent dans les 540 px et gardent 44 px de toucher
    plateau = _regle(bloc, ".plateau")
    assert "height: 540px" in plateau and "border-radius: 0" in plateau
    assert "grid-template-columns: minmax(0, 1fr); gap: 0" in _regle(bloc, ".accueil")
    commande = _regle(bureau, ".commande-plateau")
    assert "min-width: 32px" in commande and "height: 32px" in commande  # les boutons du plateau restent de 32 px
    assert "inset: -6px" in _regle(bloc, ".commande-plateau::before")  # 32 + 2 × 6 = 44 px de zone de toucher
    assert "gap: 12px" in _regle(bloc, ".commandes-zoom")  # les zones de toucher voisines ne se recouvrent pas
    assert "bottom: 16px" in _regle(bureau, ".commande-legende") and "bottom: 16px" in _regle(bureau, ".commandes-zoom")
    assert "max-width: calc(100vw - 32px)" in _regle(bloc, ".legende")

    # 10. la légende se referme au clic dans la scène (cible ou vide), au bureau comme au téléphone
    options = _corps(scene, "monterScene(plateau, {", "    });")
    assert "surClic: (cible) => { basculerLegende(false); choisir(cible); }," in options
    assert "surVide: () => { basculerLegende(false); choisir(null); }," in options
    assert "estTelephone" not in options
    assert "function basculerLegende(ouverte = legende.hidden) {" in scene and "legende.hidden = !ouverte;" in scene

    # 11. le composant feuille(titre, contenu, { pleinEcran }) : un <dialog> modal, fermé par la poignée, « Fermer », Échap et le voile
    feuille = _corps(commun, "export function feuille(", "\n}\n")
    assert "export function feuille(titre, contenu, { pleinEcran = false, surFermeture = null } = {})" in feuille
    assert "const dialogue = el('dialog', { class: `feuille ${pleinEcran ? 'feuille-plein' : 'feuille-montante'}`, 'aria-label': titre, 'aria-modal': 'true' });" in feuille
    assert "dialogue.showModal();" in feuille
    assert "const fermer = () => { if (dialogue.open) dialogue.close(); };" in feuille
    assert "el('button', { type: 'button', class: 'feuille-poignee', 'aria-label': 'Fermer', onclick: fermer }," in feuille
    assert "el('button', { type: 'button', class: 'bouton feuille-fermer', onclick: fermer }, 'Fermer')" in feuille
    assert "dialogue.addEventListener('click', (ev) => { if (ev.target === dialogue) fermer(); });" in feuille
    assert "dialogue.addEventListener('close', () => {\n    dialogue.remove();\n    if (surFermeture) surFermeture();\n  });" in feuille
    assert "preventDefault" not in feuille and "'cancel'" not in feuille  # Échap : le <dialog> se ferme seul, puis 'close'
    assert "remplacer: (...noeuds) => vider(corps, ...noeuds)," in feuille and "retitrer:" in feuille
    assert "height: 70vh; height: 70dvh" in _regle(bureau, ".feuille-montante")
    assert "height: 100%" in _regle(bureau, ".feuille-plein") and "margin: auto 0 0" in _regle(bureau, ".feuille")
    assert "height: 44px" in _regle(bureau, ".feuille-poignee") and "min-height: 44px" in _regle(bureau, ".feuille-fermer")
    assert ".feuille[open] { display: flex; }" in bureau

    # 12. la feuille des attentes (plein écran) : les effectifs en une ligne, puis toutes les cartes de la page, triées, avec leurs boutons
    contenu = _corps(mobile_js, "function contenuAttentes(", "\n}\n")
    effectifs, cartes = contenu.find("resumeAgents(etat)"), contenu.find("carteAttente(a, { etat })")
    assert 0 <= effectifs < cartes, (effectifs, cartes)
    assert "trierAttentes(attentes).map((a) => carteAttente(a, { etat }))" in contenu
    assert "slice" not in mobile_js and "MAX_" not in mobile_js  # pas de plafond de 3
    ouvrir = _corps(mobile_js, "export function ouvrirFeuilleAttentes(", "\n}\n")
    assert "feuille('Ce qui t’attend', contenuAttentes(etat), {\n    pleinEcran: true," in ouvrir
    assert "if (ouverte) return;" in ouvrir
    for mot in ("Autoriser", "Refuser", "Accorder", "Trancher", "Clôturer", "Déposer", "agir("):
        assert mot not in mobile_js, mot  # les boutons sont ceux de la page, jamais recopiés
    assert "export function resumeAgents(etat)" in commun
    maj = _corps(mobile_js, "export function majFeuilleAttentes(", "\n}\n")
    assert "if (ouverte) {" in maj and "ouverte.feuille.remplacer(...contenuAttentes(etat));" in maj and "remplacerTete" not in maj
    assert "addEventListener('hashchange', fermerFeuilleAttentes);" in mobile_js
    assert "if (!formatTelephone.matches) fermerFeuilleAttentes();" in mobile_js
    assert "dialogue.showModal" in commun and "popover: 'manual'" in commun and "pile.showPopover();" in commun  # un toast passe au-dessus d'une feuille

    # 13. la feuille de détail (montante) : le contenu du rail, ouvert au toucher d'une cible ; la porte de l'utilisateur ouvre les attentes
    synchro = _corps(scene, "function synchroniserFeuilles(", "\n}\n")
    assert "const cible = telephone && selection && selection.type !== 'utilisateur' ? trouverCible(selection, etat) : null;" in synchro
    assert "const ouverte = feuille(TITRES_DETAIL[selection.type], [detailCible(cible, etat, choisir)], {" in synchro
    assert "pleinEcran" not in synchro  # montante, à 70 % de la hauteur
    assert "feuilleDetail.remplacer(detailCible(cible, etat, choisir));" in synchro  # mise à jour sur place, sans fermer
    assert "if (feuilleDetail !== ouverte) return;\n        feuilleDetail = null;\n        choisir(null);" in synchro  # fermer = sélection null
    assert "const porte = telephone && selection !== null && selection.type === 'utilisateur';" in synchro
    assert "ouvrirFeuilleAttentes({ surFermeture: () => { porteOuverte = false; if (selection && selection.type === 'utilisateur') choisir(null); } });" in synchro
    assert "fermerFeuilleAttentes();" in synchro and "fermerFeuilleDetail();" in synchro
    assert "surSelection((cible) => {\n  clignotement = Boolean(cible && cible.type === 'utilisateur');\n  dessinerRail();\n});" in scene
    assert "synchroniserFeuilles(etat, telephone);" in _corps(scene, "function dessinerRail()", "\n}\n")
    assert "const telephone = estTelephone();" in _corps(scene, "function dessinerRail()", "\n}\n")
    assert "surChangementDeFormat(dessinerRail);" in scene
    assert "if (dernierEtat) majFeuilleAttentes(dernierEtat);" in _corps(scene, "function majFige()", "\n}\n")
    assert "ouvrirFeuilleAttentes, fermerFeuilleAttentes, majFeuilleAttentes } from './mobile.js';" in scene

    # 14. un seul contenu de détail : la feuille réutilise le composant du rail, elle ne le copie pas
    assert "import { rendreRail, trouverCible, detailCible } from './rail.js';" in scene
    for copie in ("detailEquipe", "detailAgent", "detailMessage", "jauge-barre", "detail-chiffre", "'Dettes'", "'File'", "Ouvrir la fiche"):
        assert copie not in scene and copie not in mobile_js, copie
    detail = _corps(rail, "export function detailCible(", "\n}\n")
    assert "if (trouve.equipe) return detailEquipe(trouve.equipe, etat, ouvrir, nouvelles);" in detail
    assert "trouve.agent ? detailAgent(trouve.agent, etat) : detailMessage(trouve.message)" in detail
    assert "detailCible(trouve, etat, ouvrir, nouvelles)" in _corps(rail, "export function rendreRail(", "\n}\n")

    # 15. la feuille basse, sous le plateau : ce qui coince, qui travaille, derniers échanges — sans « Ce qui t'attend », sans détail
    dessin = _corps(rail, "export function rendreRail(", "\n}\n")
    assert "telephone = false }" in dessin
    assert "} else if (telephone) {\n" in dessin
    assert TIROIR in dessin
    assert "const trouve = !telephone && selection" in dessin
    assert "overflow: visible" in _regle(bloc, ".rail") and "height: auto" in _regle(bloc, ".rail")
    assert "width: 40px; height: 4px" in _regle(bloc, ".rail::before")  # la poignée visuelle

    # 16. le tri des attentes du rail : par genre (autorisation, décision, donnée, clôture, rapport), puis la plus ancienne d'abord
    assert "export const ORDRE_GENRES = ['autorisation', 'decision', 'donnee', 'cloture', 'rapport'];" in rail
    assert set(re.findall(r"^  (\w+): '", _corps(commun, "export const NATURES_ATTENTE = {", "\n};\n"), re.M)) == {
        "autorisation", "decision", "donnee", "cloture", "rapport"}  # aucun genre oublié dans l'ordre
    assert "rang === -1 ? ORDRE_GENRES.length : rang" in rail  # un genre inconnu passe après les autres
    tri = _corps(rail, "export function trierAttentes(", "\n}\n")
    assert "return [...attentes].sort((a, b) => rangGenre(a) - rangGenre(b) || plusAncienDabord(a, b));" in tri
    assert "const triees = trierAttentes(attentes);" in _corps(rail, "function blocAttentes(", "\n}\n")
    assert "export const MAX_ATTENTES = 3;" in rail  # le plafond de 3 reste

    # 17. « n autres points ▾ » déplie la liste complète dans le rail (replié par défaut) ; « replier ▴ » revient
    assert "let attentesDepliees = false;" in rail
    attentes = _corps(rail, "function blocAttentes(", "\n}\n")
    assert "const depliees = attentesDepliees && reste > 0;" in attentes
    assert "(depliees ? triees : triees.slice(0, MAX_ATTENTES))" in attentes
    assert "onclick: () => { attentesDepliees = !depliees; redessiner(); } }," in attentes
    assert "depliees ? 'replier ▴' : `${pluriel(reste, 'autre point', 'autres points')} ▾`" in attentes
    assert "el('button', { type: 'button', class: 'lien-autres'," in attentes
    assert not re.search(r"el\('a', \{[^}]*lien-autres", rail)  # plus de lien vers Supervision
    assert "redessiner: dessinerRail" in scene

    # 18. le CSS ajouté n'emploie que l'existant : variables, tailles, graisses, rayons ; rien de rouge ; aucune ombre
    neuf = _corps(css, "/* ---------- Les feuilles", "/* =====") + bloc  # le bloc mobile, placé en fin de fichier, est contrôlé comme avant
    assert not re.findall(r"#[0-9A-Fa-f]{3,8}\b", neuf)
    assert set(re.findall(r"font-size: (\d+)px", neuf)) <= TAILLES_PERMISES
    assert set(re.findall(r"font-weight: (\d+)", neuf)) <= {"400", "500", "600"}
    assert set(re.findall(r"border-radius: ([^;]+);", neuf)) <= {"0", "999px", "var(--rayon) var(--rayon) 0 0"}
    assert "rouge" not in neuf and "box-shadow" not in neuf


# ---------------------------------------------------------------------------
# trierAttentes exécutée (node)
# ---------------------------------------------------------------------------
SONDE = """
const { trierAttentes } = await import(process.argv[2]);
const a = (id, nature, depuis) => ({ id, nature, depuis });
const entree = [a('r1', 'rapport', '2026-01-01T00:00:00Z'), a('c1', 'cloture', '2026-01-02T00:00:00Z'), a('p2', 'autorisation', '2026-01-03T00:00:00Z'),
  a('p1', 'autorisation', '2026-01-01T00:00:00Z'), a('d1', 'donnee', '2026-01-01T00:00:00Z'), a('x', 'inconnue', '2025-01-01T00:00:00Z'),
  a('t1', 'decision', '2026-01-05T00:00:00Z'), a('t0', 'decision', '2026-01-04T00:00:00Z')];
const copie = JSON.stringify(entree);
const sortie = trierAttentes(entree);
console.log(JSON.stringify({ ordre: sortie.map((x) => x.id), intact: JSON.stringify(entree) === copie, autre: sortie !== entree }));
"""
ORDRE_ATTENDU = ["p1", "p2", "t0", "t1", "d1", "c1", "r1", "x"]  # genre d'abord, puis la plus ancienne ; le genre inconnu à la fin


def executer_tri(dossier_static):
    import json
    sonde = dossier_static / "sonde-tri.mjs"
    sonde.write_text(SONDE, encoding="utf-8")
    res = subprocess.run(["node", str(sonde), str(dossier_static / "vues" / "rail.js")], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


def verifier_tri_execute(dossier_static):
    r = executer_tri(dossier_static)
    assert r["ordre"] == ORDRE_ATTENDU, r
    assert r["intact"] and r["autre"], r  # fonction pure : le tableau reçu n'est pas modifié


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def js():
    fichiers = sorted(STATIC.glob("*.js")) + sorted((STATIC / "vues").glob("*.js")) + [STATIC / "style.css"]
    sources = {str(f.relative_to(STATIC)): f.read_text(encoding="utf-8") for f in fichiers}
    sources["index.html"] = (PAGE / "index.html").read_text(encoding="utf-8")
    return sources


def test_mobile_accueil(js):
    verifier_mobile_accueil(js)


def _remplace(fichier, ancien, nouveau):
    def mutation(js):
        assert ancien in js[fichier], ancien
        return {**js, fichier: js[fichier].replace(ancien, nouveau)}
    return mutation


def _plusieurs(fichier, remplacements):
    def mutation(js):
        texte = js[fichier]
        for ancien, nouveau in remplacements:
            assert ancien in texte, ancien
            texte = texte.replace(ancien, nouveau)
        return {**js, fichier: texte}
    return mutation


NIV = "commun.js"
APP = "app.js"
SC = "vues/scene.js"
RA = "vues/rail.js"
MO = "vues/mobile.js"
CSS = "style.css"
HTML = "index.html"
BLOC = "@media (max-width: 760px) {\n  :root"
TIROIR = "vider(conteneur, rienNAttend ? blocTiroirMode(etat, redessiner) : null, blocCoince(etat), blocTravaille(etat, ouvrir), blocEchanges(etat, ouvrir));"  # le tiroir du téléphone : le mode autonome en premier quand rien n'attend
MUTATIONS = {
    # 1. le point de rupture
    "rupture à 700": _remplace(MO, "export const POINT_DE_RUPTURE = 760;", "export const POINT_DE_RUPTURE = 700;"),
    "rupture lue d'ailleurs": _remplace(MO, "window.matchMedia(`(max-width: ${POINT_DE_RUPTURE}px)`)", "window.matchMedia('(max-width: 700px)')"),
    "estTelephone figé": _remplace(MO, "export const estTelephone = () => formatTelephone.matches;", "export const estTelephone = () => false;"),
    "bloc mobile à 700": _remplace(CSS, "@media (max-width: 760px) {\n  :root", "@media (max-width: 700px) {\n  :root"),
    "second bloc mobile": _remplace(CSS, "/* ---------- Les feuilles", "@media (max-width: 760px) {\n  .rail { gap: 8px; }\n}\n/* ---------- Les feuilles"),
    # 2. le bureau ne bouge pas
    "bandeau visible au bureau": _remplace(CSS, ".bandeau-attentes, .barre-onglets, .demander-icone { display: none; }", ".barre-onglets, .demander-icone { display: none; }"),
    "barre visible au bureau": _remplace(CSS, ".bandeau-attentes, .barre-onglets, .demander-icone { display: none; }", ".bandeau-attentes, .demander-icone { display: none; }"),
    "icône visible au bureau": _remplace(CSS, ".bandeau-attentes, .barre-onglets, .demander-icone { display: none; }", ".bandeau-attentes, .barre-onglets { display: none; }"),
    "règle de barre hors du bloc": _remplace(CSS, "/* ---------- Les feuilles", ".barre-onglets { height: 64px; }\n/* ---------- Les feuilles"),
    "plateau de 540 px au bureau": _remplace(CSS, ".page-corps.sur-scene { max-width: none; padding: 20px; }", ".page-corps.sur-scene { max-width: none; padding: 20px; }\n.plateau { height: 540px; }"),
    "en-tête de 52 px au bureau": _remplace(CSS, "  min-height: 56px;\n  display: flex; align-items: center; gap: 8px 32px;", "  min-height: 52px;\n  display: flex; align-items: center; gap: 8px 32px;"),
    "rail à 300 px": _remplace(CSS, "grid-template-columns: minmax(0, 1fr) 344px; gap: 20px;", "grid-template-columns: minmax(0, 1fr) 300px; gap: 20px;"),
    "police d'icônes": _remplace(CSS, "/* ---------- Les feuilles", "@font-face { font-family: 'Icones'; src: local('x'); }\n/* ---------- Les feuilles"),
    "survol indispensable (bloc)": _remplace(CSS, "  .demander-texte { display: none; }", "  .demander-texte { display: none; }\n  .demander:hover { background: var(--champ); }"),
    "survol indispensable (feuille)": _remplace(CSS, ".feuille-barre {", ".feuille-poignee:hover { background: var(--champ); }\n.feuille-barre {"),
    # 3. l'en-tête
    "en-tête de 56 px au téléphone": _remplace(CSS, "  .entete { height: 52px; min-height: 52px;", "  .entete { height: 56px; min-height: 56px;"),
    "en-tête sans hauteur fixe": _remplace(CSS, "  .entete { height: 52px; min-height: 52px;", "  .entete { min-height: 52px;"),
    "titres qui ne rétrécissent pas": _remplace(CSS, "  .entete-titres { flex: 1; min-width: 0; margin-right: 0; }", "  .entete-titres { flex: none; }"),
    "projet sans points de suite": _remplace(CSS, "overflow: hidden; text-overflow: ellipsis; font-size: 12px;", "font-size: 12px;"),
    "onglets gardés dans l'en-tête": _remplace(CSS, "  .nav, .compteur-attentes, .entete-etat", "  .compteur-attentes, .entete-etat"),
    "compteur gardé dans l'en-tête": _remplace(CSS, "  .nav, .compteur-attentes, .entete-etat", "  .nav, .entete-etat"),
    "effectifs gardés dans l'en-tête": _remplace(CSS, ".entete-etat .pilule:not(.age-donnee) { display: none; }", ".entete-etat .pilule.rien { display: none; }"),
    "état d'en-tête qui rétrécit": _remplace(CSS, "  .entete-etat { flex: none; gap: 8px; }", "  .entete-etat { gap: 8px; }"),
    "pastille masquée": _remplace(CSS, "  .entete-etat { flex: none; gap: 8px; }", "  .entete-etat { flex: none; gap: 8px; }\n  .age-donnee {\n    display: none; }"),
    "sources masquées": _remplace(CSS, "  .demander-icone { display: block; }", "  .demander-icone { display: block; }\n  .sources-echec { display: none; }"),
    # 4. le bouton carré à icône
    "bouton de 36 px": _remplace(CSS, "width: 40px; height: 40px; min-height: 0;", "width: 36px; height: 36px; min-height: 0;"),
    "bouton rectangulaire": _remplace(CSS, "width: 40px; height: 40px; min-height: 0; padding: 0;", "width: 40px; height: 40px; min-height: 0; padding: 0 12px;"),
    "libellé gardé": _remplace(CSS, "  .demander-texte { display: none; }", "  .demander-texte { display: inline; }"),
    "icône toujours cachée": _remplace(CSS, "  .demander-icone { display: block; }", "  .demander-icone { display: none; }"),
    "bouton sans zone de toucher": _remplace(CSS, "  .demander::before { content: ''; position: absolute; inset: -2px; }", "  .demander::before { content: ''; position: absolute; inset: 0; }"),
    "bouton sans icône": _remplace(NIV, "        icone('bulle', 'demander-icone'), el('span'", "        el('span'"),
    "bouton sans libellé accessible": _remplace(NIV, "title: TITRE_DEMANDER, 'aria-label': 'Demander à l’Assistant', onclick", "title: TITRE_DEMANDER, onclick"),
    "bouton sans info-bulle": _remplace(NIV, "class: 'bouton demander', title: TITRE_DEMANDER, 'aria-label'", "class: 'bouton demander', 'aria-label'"),
    "bouton : libellé changé": _remplace(NIV, "el('span', { class: 'demander-texte' }, 'Demander à l’Assistant')", "el('span', { class: 'demander-texte' }, 'Demander')"),
    "icône bulle absente": _remplace(NIV, "  bulle: [", "  bulles: ["),
    # 5. les icônes
    "icône en police": _remplace(NIV, 'stroke="currentColor"', 'stroke="#fff"'),
    "icône par createElementNS": _remplace(NIV, "export function icone(", "const _ns = document.createElementNS;\nexport function icone("),
    "icône lue d'une donnée": _remplace(NIV, "${ICONES[nom].map((d) => `<path d=\"${d}\"/>`).join('')}", "${nom}"),
    "icône exposée aux lecteurs d'écran": _remplace(NIV, 'aria-hidden="true" focusable="false"', 'focusable="false"'),
    "icône de scène oubliée": _remplace(NIV, "  scene: ['M3 10l9-6 9 6v10H3z', 'M9 20v-6h6v6'],\n", ""),
    "icône de supervision oubliée": _remplace(NIV, "  supervision: [", "  supervisions: ["),
    "Journal dans la barre": _remplace(NIV, "  { id: 'fil', href: '#/fil', titre: 'Fil' },\n", "  { id: 'fil', href: '#/fil', titre: 'Fil' },\n  { id: 'journal', href: '#/journal', titre: 'Journal' },\n"),
    "Fil oublié de la barre": _remplace(NIV, "  { id: 'fil', href: '#/fil', titre: 'Fil' },\n", ""),
    # 6. la barre d'onglets
    "barre sans libellé": _remplace(MO, "icone(p.id), el('span', {}, p.titre)", "icone(p.id)"),
    "barre sans icône": _remplace(MO, "icone(p.id), el('span', {}, p.titre)", "el('span', {}, p.titre)"),
    "onglet courant jamais marqué": _remplace(MO, "'aria-current': p.id === ctx.page ? 'page' : null }, icone", "'aria-current': null }, icone"),
    "barre sans nom": _remplace(MO, "el('nav', { class: 'barre-onglets', 'aria-label': 'Pages' },", "el('nav', { class: 'barre-onglets' },"),
    "barre non fixe": _remplace(CSS, "position: fixed; left: 0; right: 0; bottom: 0; z-index: 10; display: flex;", "position: sticky; left: 0; right: 0; bottom: 0; z-index: 10; display: flex;"),
    "barre de 56 px": _remplace(CSS, "height: calc(64px + env(safe-area-inset-bottom, 0px)); padding-bottom", "height: calc(56px + env(safe-area-inset-bottom, 0px)); padding-bottom"),
    "barre sans zone sûre (hauteur)": _remplace(CSS, "height: calc(64px + env(safe-area-inset-bottom, 0px)); padding-bottom", "height: 64px; padding-bottom"),
    "barre sans zone sûre (marge)": _remplace(CSS, "padding-bottom: env(safe-area-inset-bottom, 0px);\n    background: var(--fond)", "padding-bottom: 0;\n    background: var(--fond)"),
    "onglets de 40 px": _remplace(CSS, "flex: 1; min-width: 0; min-height: 44px; display: flex; flex-direction: column;", "flex: 1; min-width: 0; min-height: 40px; display: flex; flex-direction: column;"),
    "libellés de 12 px": _remplace(CSS, "color: var(--secondaire); font-size: 11px; font-weight: 500; text-decoration: none;", "color: var(--secondaire); font-size: 12px; font-weight: 500; text-decoration: none;"),
    "onglets côte à côte": _remplace(CSS, "min-height: 44px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px;", "min-height: 44px; display: flex; flex-direction: row; align-items: center; justify-content: center; gap: 4px;"),
    "onglet courant éteint": _remplace(CSS, '.barre-onglets a[aria-current="page"] { color: var(--texte); }', '.barre-onglets a[aria-current="page"] { color: var(--secondaire); }'),
    "icône courante sans ambre": _remplace(CSS, '.barre-onglets a[aria-current="page"] svg { color: var(--ambre); }', '.barre-onglets a[aria-current="page"] svg { color: var(--texte); }'),
    "viewport sans zone sûre": _remplace(HTML, ", viewport-fit=cover", ""),
    "barre jamais posée": _remplace(MO, "  page.append(barreOnglets(ctx));\n", ""),
    "bandeau jamais posé": _remplace(MO, "  if (bandeau) entete.after(bandeau);\n", ""),
    "feuille non mise à jour": _remplace(MO, "  majFeuilleAttentes(ctx.etat);\n}", "}"),
    "mobile jamais rendu": _remplace(APP, "  rendreMobile(ctx); // les attentes en tête d'écran et la barre du bas (masquées au bureau)\n", ""),
    "mobile rendu après l'écran": _remplace(APP, "  rendreMobile(ctx); // les attentes en tête d'écran et la barre du bas (masquées au bureau)\n  const arret = VUES[route.page].rendre(ctx);",
                                            "  const arret = VUES[route.page].rendre(ctx);\n  rendreMobile(ctx);"),
    "mobile non importé": _remplace(APP, "import { rendreMobile } from './vues/mobile.js';\n", "import { rendreMobile as _m } from './vues/mobile.js';\nconst rendreMobile = () => {};\n"),
    # 7. la fin des écrans reste visible
    "écrans sans marge basse": _remplace(CSS, "padding-top: 16px; padding-bottom: calc(64px + env(safe-area-inset-bottom, 0px) + 24px); }", "padding-top: 16px; }"),
    "marge basse sans zone sûre": _remplace(CSS, "padding-bottom: calc(64px + env(safe-area-inset-bottom, 0px) + 24px); }", "padding-bottom: calc(64px + 24px); }"),
    "scène sans marge basse": _remplace(CSS, ".page-corps.sur-scene { gap: 0; padding: 0 0 calc(64px + env(safe-area-inset-bottom, 0px) + 16px); }", ".page-corps.sur-scene { gap: 0; padding: 0; }"),
    "boutons d'attente de 32 px": _remplace(CSS, "  .attente .bouton { min-height: 44px; }", "  .attente .bouton { min-height: 32px; }"),
    # 8. le bandeau
    "bandeau sur des attentes inconnues": _remplace(MO, "  if (attentes === null) return null; // inconnues (sources en échec) : ne rien affirmer\n  const n = attentes.length;", "  const n = attentes ? attentes.length : 0;"),
    "bandeau vert partout": _remplace(MO, "if (n === 0 && ctx.page !== 'scene') return null;", "if (n === 0 && false) return null;"),
    "bandeau vert nulle part": _remplace(MO, "if (n === 0 && ctx.page !== 'scene') return null;", "if (n === 0) return null;"),
    "bandeau ambre seulement sur la scène": _remplace(MO, "if (n === 0 && ctx.page !== 'scene') return null;", "if (ctx.page !== 'scene') return null;"),
    "bandeau sans pluriel": _remplace(MO, "`${pluriel(n, 'point')} ${n === 1 ? 't’attend' : 't’attendent'}`", "`${n} points t’attendent`"),
    "bandeau toujours au pluriel": _remplace(MO, "${n === 1 ? 't’attend' : 't’attendent'}", "${true ? 't’attend' : 't’attendent'}"),
    "bandeau vert : autre phrase": _remplace(MO, "'✓ Rien ne t’attend' :", "'Rien' :"),
    "bandeau qui n'est pas un bouton": _remplace(MO, "return el('button', { type: 'button', class: `bandeau-attentes", "return el('div', { type: 'button', class: `bandeau-attentes"),
    "bandeau sans état": _remplace(MO, "class: `bandeau-attentes ${n === 0 ? 'bandeau-calme' : 'bandeau-ambre'}`", "class: 'bandeau-attentes'"),
    "bandeau qui n'ouvre rien": _remplace(MO, "onclick: () => ouvrirFeuilleAttentes() },", "onclick: () => {} },"),
    "bandeau sans flèche": _remplace(MO, ", el('span', { class: 'bandeau-fleche', 'aria-hidden': 'true' }, '›'));", ");"),
    "bandeau de 40 px": _remplace(CSS, "width: 100%; min-height: 44px; padding: 0 16px;", "width: 100%; min-height: 40px; padding: 0 16px;"),
    "bandeau en ligne": _remplace(CSS, "  .bandeau-attentes {\n    display: flex;", "  .bandeau-attentes {\n    display: inline-flex;"),
    "bandeau étroit": _remplace(CSS, "width: 100%; min-height: 44px; padding: 0 16px;", "min-height: 44px; padding: 0 16px;"),
    "bandeau calme pas vert": _remplace(CSS, ".bandeau-calme { background: var(--vert-fond);", ".bandeau-calme { background: var(--ambre-fond);"),
    "bandeau d'attentes pas ambre": _remplace(CSS, ".bandeau-ambre { background: var(--ambre-fond);", ".bandeau-ambre { background: var(--vert-fond);"),
    "bandeau dans le rail": _remplace(RA, "export const MAX_ALARMES = 3;", "export const MAX_ALARMES = 3;\n// bandeau"),
    "bandeau dans l'application": _remplace(APP, "const VUES = {", "// bandeau\nconst VUES = {"),
    # 9. le plateau
    "plateau de 706 px": _remplace(CSS, "  .plateau { height: 540px;", "  .plateau { height: 706px;"),
    "plateau de 600 px": _remplace(CSS, "  .plateau { height: 540px;", "  .plateau { height: 600px;"),
    "plateau à coins ronds": _remplace(CSS, "border-width: 0 0 1px; border-radius: 0; }", "border-width: 0 0 1px; border-radius: var(--rayon); }"),
    "scène en deux colonnes": _remplace(CSS, "  .accueil { grid-template-columns: minmax(0, 1fr); gap: 0; }", "  .accueil { grid-template-columns: minmax(0, 1fr) 344px; gap: 0; }"),
    "boutons du plateau de 44 px": _remplace(CSS, "position: relative; min-width: 32px; height: 32px; padding: 0 8px;", "position: relative; min-width: 44px; height: 44px; padding: 0 8px;"),
    "boutons du plateau sans zone de toucher": _remplace(CSS, "  .commande-plateau::before { content: ''; position: absolute; inset: -6px; }", "  .commande-plateau::before { content: ''; position: absolute; inset: 0; }"),
    "zones de toucher qui se recouvrent": _remplace(CSS, "  .commandes-zoom { gap: 12px; }", "  .commandes-zoom { gap: 8px; }"),
    "zoom sous la ligne de flottaison": _remplace(CSS, ".commandes-zoom { position: absolute; right: 16px; bottom: 16px;", ".commandes-zoom { position: absolute; right: 16px; bottom: -60px;"),
    "légende sous la ligne de flottaison": _remplace(CSS, ".commande-legende { position: absolute; left: 16px; bottom: 16px;", ".commande-legende { position: absolute; left: 16px; bottom: -60px;"),
    "légende plus large que l'écran": _remplace(CSS, "  .legende { max-width: calc(100vw - 32px); }", "  .legende { max-width: 300px; }"),
    # 10. la légende se referme au clic dans la scène
    "clic sur une cible : légende ouverte": _remplace(SC, "surClic: (cible) => { basculerLegende(false); choisir(cible); },", "surClic: (cible) => { choisir(cible); },"),
    "clic dans le vide : légende ouverte": _remplace(SC, "surVide: () => { basculerLegende(false); choisir(null); },", "surVide: () => { choisir(null); },"),
    "légende fermée au téléphone seulement": _remplace(SC, "surVide: () => { basculerLegende(false); choisir(null); },", "surVide: () => { if (estTelephone()) basculerLegende(false); choisir(null); },"),
    "clic qui ouvre la légende": _remplace(SC, "surClic: (cible) => { basculerLegende(false); choisir(cible); },", "surClic: (cible) => { basculerLegende(true); choisir(cible); },"),
    "basculer sans état": _remplace(SC, "  legende.hidden = !ouverte;\n", ""),
    # 11. le composant feuille
    "feuille sans signature": _remplace(NIV, "export function feuille(titre, contenu, { pleinEcran = false, surFermeture = null } = {}) {", "export function feuille(titre, contenu, { pleinEcran = true, surFermeture = null } = {}) {"),
    "feuille non modale": _remplace(NIV, "  dialogue.showModal();\n  return {\n    dialogue,", "  dialogue.show();\n  return {\n    dialogue,"),
    "feuille sans rôle modal": _remplace(NIV, "'aria-label': titre, 'aria-modal': 'true' });", "'aria-label': titre });"),
    "feuille sans nom": _remplace(NIV, "'aria-label': titre, 'aria-modal': 'true' });", "'aria-modal': 'true' });"),
    "feuille : classes inversées": _remplace(NIV, "${pleinEcran ? 'feuille-plein' : 'feuille-montante'}", "${pleinEcran ? 'feuille-montante' : 'feuille-plein'}"),
    "feuille sans poignée": _remplace(NIV, "    el('button', { type: 'button', class: 'feuille-poignee', 'aria-label': 'Fermer', onclick: fermer },\n      el('span', { class: 'feuille-barre', 'aria-hidden': 'true' })),\n", ""),
    "poignée qui ne ferme pas": _remplace(NIV, "class: 'feuille-poignee', 'aria-label': 'Fermer', onclick: fermer }", "class: 'feuille-poignee', 'aria-label': 'Fermer' }"),
    "poignée sans libellé": _remplace(NIV, "class: 'feuille-poignee', 'aria-label': 'Fermer', onclick", "class: 'feuille-poignee', onclick"),
    "feuille sans bouton Fermer": _remplace(NIV, "      el('button', { type: 'button', class: 'bouton feuille-fermer', onclick: fermer }, 'Fermer')),", "      null),"),
    "bouton Fermer qui ne ferme pas": _remplace(NIV, "class: 'bouton feuille-fermer', onclick: fermer }", "class: 'bouton feuille-fermer' }"),
    "bouton Fermer : autre libellé": _remplace(NIV, "class: 'bouton feuille-fermer', onclick: fermer }, 'Fermer')", "class: 'bouton feuille-fermer', onclick: fermer }, 'OK')"),
    "voile qui ne ferme pas": _remplace(NIV, "if (ev.target === dialogue) fermer(); });", "if (false) fermer(); });"),
    "tout clic ferme": _remplace(NIV, "if (ev.target === dialogue) fermer(); });", "fermer(); });"),
    "feuille jamais retirée": _remplace(NIV, "    dialogue.remove();\n    if (surFermeture) surFermeture();", "    if (surFermeture) surFermeture();"),
    "fermeture sans rappel": _remplace(NIV, "    dialogue.remove();\n    if (surFermeture) surFermeture();", "    dialogue.remove();"),
    "Échap neutralisé": _remplace(NIV, "  const fermer = () => { if (dialogue.open) dialogue.close(); };", "  const fermer = () => { if (dialogue.open) dialogue.close(); };\n  dialogue.addEventListener('cancel', (ev) => ev.preventDefault());"),
    "feuille non retitrable": _remplace(NIV, "    retitrer: (texte) =>", "    retitre: (texte) =>"),
    "contenu non remplaçable": _remplace(NIV, "    remplacer: (...noeuds) => vider(corps, ...noeuds),\n", ""),
    "toast sous la feuille": _remplace(NIV, "pile = el('div', { class: 'toasts', role: 'status', 'aria-live': 'polite', popover: 'manual' });", "pile = el('div', { class: 'toasts', role: 'status', 'aria-live': 'polite' });"),
    "toast jamais remonté": _remplace(NIV, "    pile.showPopover();\n", ""),
    "feuille montante de 50 %": _remplace(CSS, ".feuille-montante { height: 70vh; height: 70dvh;", ".feuille-montante { height: 50vh; height: 50dvh;"),
    "feuille montante de 100 %": _remplace(CSS, ".feuille-montante { height: 70vh; height: 70dvh;", ".feuille-montante { height: 100vh; height: 100dvh;"),
    "feuille pleine à mi-hauteur": _remplace(CSS, ".feuille-plein { height: 100%;", ".feuille-plein { height: 50%;"),
    "feuille en haut": _remplace(CSS, "width: 100%; max-width: none; margin: auto 0 0; padding: 0;", "width: 100%; max-width: none; margin: 0; padding: 0;"),
    "feuille ouverte en bloc": _remplace(CSS, ".feuille[open] { display: flex; }", ".feuille[open] { display: block; }"),
    "poignée de 24 px": _remplace(CSS, "justify-content: center; width: 100%; height: 44px; padding: 0;", "justify-content: center; width: 100%; height: 24px; padding: 0;"),
    "bouton Fermer de 32 px": _remplace(CSS, ".feuille-fermer { flex: none; white-space: nowrap; min-height: 44px; }", ".feuille-fermer { flex: none; white-space: nowrap; min-height: 32px; }"),
    # 12. la feuille des attentes
    "attentes sans effectifs": _remplace(MO, "    el('div', { class: 'feuille-effectifs' }, resumeAgents(etat)),\n", ""),
    "effectifs après les cartes": _plusieurs(MO, [
        ("    el('div', { class: 'feuille-effectifs' }, resumeAgents(etat)),\n    modeDansLaFeuille(etat)", "    modeDansLaFeuille(etat)"),
        ("'✓ Rien ne t’attend. Tout avance sans toi.'),\n  ];", "'✓ Rien ne t’attend. Tout avance sans toi.'),\n    el('div', { class: 'feuille-effectifs' }, resumeAgents(etat)),\n  ];")]),
    "attentes plafonnées": _remplace(MO, "trierAttentes(attentes).map((a) => carteAttente(a, { etat }))", "trierAttentes(attentes).slice(0, 3).map((a) => carteAttente(a, { etat }))"),
    "attentes non triées (feuille)": _remplace(MO, "trierAttentes(attentes).map((a) => carteAttente(a, { etat }))", "attentes.map((a) => carteAttente(a, { etat }))"),
    "cartes recopiées": _remplace(MO, "export function bandeauAttentes(", "// Autoriser\nexport function bandeauAttentes("),
    "feuille des attentes montante": _remplace(MO, "contenuAttentes(etat), {\n    pleinEcran: true,", "contenuAttentes(etat), {\n    pleinEcran: false,"),
    "feuille des attentes rouverte à chaque clic": _remplace(MO, "  if (ouverte) return;\n  const etat = dernierEtat;", "  const etat = dernierEtat;"),
    "feuille des attentes figée": _remplace(MO, "    ouverte.feuille.remplacer(...contenuAttentes(etat));\n", ""),
    "navigation sans fermeture": _remplace(MO, "addEventListener('hashchange', fermerFeuilleAttentes);\n", ""),
    "retour au bureau sans fermeture": _remplace(MO, "if (!formatTelephone.matches) fermerFeuilleAttentes();", "if (formatTelephone.matches) fermerFeuilleAttentes();"),
    "effectifs non exportés": _remplace(NIV, "export function resumeAgents(etat) {", "function resumeAgents(etat) {"),
    # 13. la feuille de détail
    "détail hors téléphone": _remplace(SC, "const cible = telephone && selection && selection.type !== 'utilisateur' ? trouverCible(selection, etat) : null;", "const cible = selection && selection.type !== 'utilisateur' ? trouverCible(selection, etat) : null;"),
    "détail pour la porte de l'utilisateur": _remplace(SC, "const cible = telephone && selection && selection.type !== 'utilisateur' ? trouverCible(selection, etat) : null;", "const cible = telephone && selection ? trouverCible(selection, etat) : null;"),
    "détail montant en plein écran": _remplace(SC, "const ouverte = feuille(TITRES_DETAIL[selection.type], [detailCible(cible, etat, choisir)], {\n      surFermeture", "const ouverte = feuille(TITRES_DETAIL[selection.type], [detailCible(cible, etat, choisir)], {\n      pleinEcran: true,\n      surFermeture"),
    "détail qui se rouvre": _remplace(SC, "  } else if (feuilleDetail) {\n    feuilleDetail.retitrer(TITRES_DETAIL[selection.type]);\n    feuilleDetail.remplacer(detailCible(cible, etat, choisir));\n  } else {", "  } else {"),
    "détail figé": _remplace(SC, "    feuilleDetail.remplacer(detailCible(cible, etat, choisir));", "    feuilleDetail.retitrer(TITRES_DETAIL[selection.type]);"),
    "fermer sans désélectionner": _remplace(SC, "        feuilleDetail = null;\n        choisir(null);\n      },", "        feuilleDetail = null;\n      },"),
    "détail jamais refermé": _remplace(SC, "  if (!cible) {\n    fermerFeuilleDetail();\n  } else if", "  if (!cible) {\n    // rien\n  } else if"),
    "porte de l'utilisateur sans feuille": _remplace(SC, "const porte = telephone && selection !== null && selection.type === 'utilisateur';", "const porte = false;"),
    "porte de l'utilisateur au bureau": _remplace(SC, "const porte = telephone && selection !== null && selection.type === 'utilisateur';", "const porte = selection !== null && selection.type === 'utilisateur';"),
    "porte de l'utilisateur : sélection gardée": _remplace(SC, "porteOuverte = false; if (selection && selection.type === 'utilisateur') choisir(null); }", "porteOuverte = false; }"),
    "porte de l'utilisateur : feuille gardée": _remplace(SC, "  } else if (!porte && porteOuverte) {\n    fermerFeuilleAttentes(); // sa fermeture remet porteOuverte à faux\n  }", "  }"),
    "feuilles jamais synchronisées": _remplace(SC, "  synchroniserFeuilles(etat, telephone);\n", ""),
    "téléphone jamais mesuré": _remplace(SC, "  const telephone = estTelephone();\n", "  const telephone = false;\n"),
    "changement de format ignoré": _remplace(SC, "surChangementDeFormat(dessinerRail);", ""),
    "figé : feuille des attentes oubliée": _remplace(SC, "    if (dernierEtat) majFeuilleAttentes(dernierEtat); // et ceux de la feuille des attentes, si elle est ouverte\n", ""),
    "import de la feuille oublié": _remplace(SC, "ouvrirFeuilleAttentes, fermerFeuilleAttentes, majFeuilleAttentes } from './mobile.js';", "ouvrirFeuilleAttentes, fermerFeuilleAttentes } from './mobile.js';\nconst majFeuilleAttentes = () => {};"),
    "sélection non écoutée": _remplace(SC, "surSelection((cible) => {\n  clignotement = Boolean(cible && cible.type === 'utilisateur');\n  dessinerRail();\n});", "surSelection((cible) => {\n  clignotement = Boolean(cible && cible.type === 'utilisateur');\n});"),
    # 14. un seul contenu de détail
    "détail recopié dans la scène": _remplace(SC, "const TITRES_DETAIL = {", "function detailAgent() {}\nconst TITRES_DETAIL = {"),
    "détail recopié dans mobile": _remplace(MO, "export function bandeauAttentes(", "function detailEquipe() {}\nexport function bandeauAttentes("),
    "jauge recopiée": _remplace(SC, "const TITRES_DETAIL = {", "const _jauge = 'jauge-barre';\nconst TITRES_DETAIL = {"),
    "détail non importé": _remplace(SC, "import { rendreRail, trouverCible, detailCible } from './rail.js';", "import { rendreRail, trouverCible } from './rail.js';\nconst detailCible = () => null;"),
    "détail d'équipe oublié": _remplace(RA, "  if (trouve.equipe) return detailEquipe(trouve.equipe, etat, ouvrir, nouvelles);\n", ""),
    "détail du rail recopié": _remplace(RA, "vider(conteneur, el('section', { class: 'detail-rail', 'aria-label': 'Détail' }, retour, detailCible(trouve, etat, ouvrir, nouvelles)));", "vider(conteneur, el('section', { class: 'detail-rail', 'aria-label': 'Détail' }, retour, trouve.equipe ? detailEquipe(trouve.equipe, etat, ouvrir, nouvelles) : null));"),
    # 15. la feuille basse
    "feuille basse avec les attentes": _remplace(RA, TIROIR, "vider(conteneur, blocAttentes(etat, nouvelles, clignote, redessiner), blocCoince(etat), blocTravaille(etat, ouvrir), blocEchanges(etat, ouvrir));"),
    "feuille basse sans échanges": _remplace(RA, TIROIR, "vider(conteneur, blocCoince(etat), blocTravaille(etat, ouvrir));"),
    "feuille basse sans « Qui travaille »": _remplace(RA, TIROIR, "vider(conteneur, blocCoince(etat), blocEchanges(etat, ouvrir));"),
    "feuille basse sans « Ce qui coince »": _remplace(RA, TIROIR, "vider(conteneur, blocTravaille(etat, ouvrir), blocEchanges(etat, ouvrir));"),
    "téléphone jamais passé au rail": _remplace(RA, "clignote = false, telephone = false }", "clignote = false, telephone = true }"),
    "détail du rail sur téléphone": _remplace(RA, "const trouve = !telephone && selection", "const trouve = selection"),
    "feuille basse jamais choisie": _remplace(RA, "  } else if (telephone) {\n", "  } else if (false) {\n"),
    "rail qui défile sur téléphone": _remplace(CSS, "  .rail { height: auto; overflow: visible; gap: 20px; padding: 0 16px; }", "  .rail { height: auto; overflow: auto; gap: 20px; padding: 0 16px; }"),
    "rail de hauteur fixe sur téléphone": _remplace(CSS, "  .rail { height: auto; overflow: visible; gap: 20px; padding: 0 16px; }", "  .rail { height: 400px; overflow: visible; gap: 20px; padding: 0 16px; }"),
    "feuille basse sans poignée": _remplace(CSS, "  .rail::before { content: ''; align-self: center; width: 40px; height: 4px;", "  .rail::before { content: ''; align-self: center; width: 40px; height: 0;"),
    # 16. le tri
    "genres dans le désordre": _remplace(RA, "['autorisation', 'decision', 'donnee', 'cloture', 'rapport']", "['autorisation', 'decision', 'cloture', 'donnee', 'rapport']"),
    "rapport en tête": _remplace(RA, "['autorisation', 'decision', 'donnee', 'cloture', 'rapport']", "['rapport', 'autorisation', 'decision', 'donnee', 'cloture']"),
    "genre oublié": _remplace(RA, "['autorisation', 'decision', 'donnee', 'cloture', 'rapport']", "['autorisation', 'decision', 'donnee', 'cloture']"),
    "genre inconnu en tête": _remplace(RA, "rang === -1 ? ORDRE_GENRES.length : rang", "rang === -1 ? -1 : rang"),
    "tri sans ancienneté": _remplace(RA, "rangGenre(a) - rangGenre(b) || plusAncienDabord(a, b)", "rangGenre(a) - rangGenre(b)"),
    "tri : plus récente d'abord": _remplace(RA, "rangGenre(a) - rangGenre(b) || plusAncienDabord(a, b)", "rangGenre(a) - rangGenre(b) || plusAncienDabord(b, a)"),
    "tri sans genre": _remplace(RA, "rangGenre(a) - rangGenre(b) || plusAncienDabord(a, b)", "plusAncienDabord(a, b)"),
    "tri qui modifie son entrée": _remplace(RA, "return [...attentes].sort(", "return attentes.sort("),
    "tri non exporté": _remplace(RA, "export function trierAttentes(attentes) {", "function trierAttentes(attentes) {"),
    "rail non trié": _remplace(RA, "const triees = trierAttentes(attentes);", "const triees = [...attentes];"),
    "plafond de 4": _remplace(RA, "export const MAX_ATTENTES = 3;", "export const MAX_ATTENTES = 4;"),
    # 17. le dépliage
    "dépliage : replié pour toujours": _remplace(RA, "const depliees = attentesDepliees && reste > 0;", "const depliees = false;"),
    "dépliage : déplié d'office": _remplace(RA, "let attentesDepliees = false;", "let attentesDepliees = true;"),
    "dépliage : jamais mémorisé": _remplace(RA, "onclick: () => { attentesDepliees = !depliees; redessiner(); } },", "onclick: () => { redessiner(); } },"),
    "dépliage : rail non redessiné": _remplace(RA, "onclick: () => { attentesDepliees = !depliees; redessiner(); } },", "onclick: () => { attentesDepliees = !depliees; } },"),
    "dépliage : à sens unique": _remplace(RA, "attentesDepliees = !depliees;", "attentesDepliees = true;"),
    "dépliage : liste partielle": _remplace(RA, "(depliees ? triees : triees.slice(0, MAX_ATTENTES))", "triees.slice(0, MAX_ATTENTES)"),
    "dépliage : pas de « replier »": _remplace(RA, "depliees ? 'replier ▴' :", "depliees ? 'autres points ▾' :"),
    "dépliage : flèche vers le haut": _remplace(RA, "'autres points')} ▾`", "'autres points')} ▴`"),
    "dépliage : encore un lien": _remplace(RA, "el('button', { type: 'button', class: 'lien-autres',", "el('a', { href: '#/supervision', class: 'lien-autres',"),
    "dépliage : rail jamais redessiné par la scène": _remplace(SC, "redessiner: dessinerRail, ", ""),
    # 18. le CSS ajouté
    "taille hors échelle": _remplace(CSS, ".bandeau-fleche { font-size: 20px;", ".bandeau-fleche { font-size: 22px;"),
    "graisse hors échelle": _remplace(CSS, ".feuille-tete h2 { margin: 0; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 16px; font-weight: 600; }", ".feuille-tete h2 { margin: 0; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 16px; font-weight: 700; }"),
    "couleur en dur": _remplace(CSS, ".feuille-barre { width: 40px; height: 4px; border-radius: 999px; background: var(--bord-fort); }", ".feuille-barre { width: 40px; height: 4px; border-radius: 999px; background: #444; }"),
    "rayon hors échelle": _remplace(CSS, "border-width: 1px 0 0; border-radius: var(--rayon) var(--rayon) 0 0;", "border-width: 1px 0 0; border-radius: 20px 20px 0 0;"),
    "rouge dans les feuilles": _remplace(CSS, ".feuille-effectifs { font-size: 13px; }", ".feuille-effectifs { font-size: 13px; color: var(--rouge); }"),
    "ombre sous la barre": _remplace(CSS, "background: var(--fond); border-top: 1px solid var(--bord);", "background: var(--fond); border-top: 1px solid var(--bord); box-shadow: 0 -2px 6px rgba(0, 0, 0, 0.3);"),
}

MUTATIONS_TRI = {
    "genres dans le désordre": ("['autorisation', 'decision', 'donnee', 'cloture', 'rapport']", "['autorisation', 'decision', 'cloture', 'donnee', 'rapport']"),
    "tri sans ancienneté": ("rangGenre(a) - rangGenre(b) || plusAncienDabord(a, b)", "rangGenre(a) - rangGenre(b)"),
    "plus récente d'abord": ("rangGenre(a) - rangGenre(b) || plusAncienDabord(a, b)", "rangGenre(a) - rangGenre(b) || plusAncienDabord(b, a)"),
    "genre inconnu en tête": ("rang === -1 ? ORDRE_GENRES.length : rang", "rang === -1 ? -1 : rang"),
    "tri qui modifie son entrée": ("return [...attentes].sort(", "return attentes.sort("),
    "tri par genre seul, ancienneté inversée": ("const instant = (iso) => Date.parse(iso) || Number.MAX_SAFE_INTEGER;", "const instant = (iso) => -(Date.parse(iso) || 0);"),
}


@pytest.mark.parametrize("nom", MUTATIONS)
def test_mutation_detectee(nom, js):
    mutee = MUTATIONS[nom](js)  # hors du raises : la mutation doit s'appliquer, sinon le test serait faux
    with pytest.raises(AssertionError):
        verifier_mobile_accueil(mutee)


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node n'est pas installé : trierAttentes n'est pas exécutée")


@pytest.fixture
def copie_static(tmp_path):
    cible = tmp_path / "static"
    shutil.copytree(STATIC, cible, ignore=shutil.ignore_patterns("__pycache__"))
    return cible


@needs_node
def test_tri_execute(copie_static):
    verifier_tri_execute(copie_static)


@needs_node
@pytest.mark.parametrize("nom", MUTATIONS_TRI)
def test_mutation_du_tri_detectee(nom, copie_static):
    ancien, nouveau = MUTATIONS_TRI[nom]
    fichier = copie_static / "vues" / "rail.js"
    texte = fichier.read_text(encoding="utf-8")
    assert ancien in texte, ancien  # la mutation doit s'appliquer
    fichier.write_text(texte.replace(ancien, nouveau), encoding="utf-8")
    with pytest.raises(AssertionError):
        verifier_tri_execute(copie_static)


def test_couverture_des_verifications():
    toutes = {n for n, v in globals().items() if n.startswith("verifier_") and callable(v)}
    assert toutes == {"verifier_mobile_accueil", "verifier_tri_execute"} and MUTATIONS and MUTATIONS_TRI, sorted(toutes)
