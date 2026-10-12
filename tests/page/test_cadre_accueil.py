"""Le cadre de l'accueil : en-tête unique, trois onglets, routes, plateau.

Analyse de texte du JS et du CSS de static/ (pas de navigateur dans pytest). `verifier_cadre_accueil(js)` lève
AssertionError ; la table MUTATIONS prouve qu'elle échoue quand on casse chaque comportement. Le rendu réel
(onglets, 56 px, plateau, débordement à 390 px) est vérifié dans un vrai navigateur par
tests/page/outils/scenario_cadre.py.
"""
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "src" / "cime" / "page" / "static"

PAGES_ATTENDUES = (
    "export const PAGES = [\n"
    "  { id: 'scene', href: '#/', titre: 'Scène' },\n"
    "  { id: 'supervision', href: '#/supervision', titre: 'Supervision' },\n"
    "  { id: 'fil', href: '#/fil', titre: 'Fil' },\n"
)
PLATEAU = "const plateau = el('div', { class: 'plateau', id: 'plateau' });"


def _corps(texte, debut, fin):
    i = texte.index(debut)
    return texte[i:texte.index(fin, i)]


def _dans_l_ordre(texte, morceaux):
    positions = [texte.index(m) for m in morceaux]
    assert positions == sorted(positions), morceaux


def verifier_cadre_accueil(js):
    commun, app, ensemble, scene, equipe, css = (js[n] for n in (
        "commun.js", "app.js", "vues/ensemble.js", "vues/scene.js", "vues/equipe.js", "style.css"))
    # 1. trois onglets exactement ; Journal et Archives n'en sont plus, mais Supervision y renvoie
    pages = _corps(commun, "export const PAGES = [", "];")
    assert pages == PAGES_ATTENDUES
    assert "journal" not in pages and "archives" not in pages
    pied = _corps(ensemble, "function piedSupervision()", "\n}\n")
    assert "el('a', { href: '#/journal' }, 'Journal des actions')" in pied
    assert "archives" not in pied  # le lien des équipes clôturées est sous la grille de l'organigramme (un seul), avec leur compte
    assert "el('a', { href: '#/archives' }, cloturees === null ? 'Équipes clôturées →'" in _corps(ensemble, "function ligneLiens(retraits)", "\n}\n")
    assert "    piedSupervision());" in _corps(ensemble, "export function rendre(contexte)", "\n}\n")
    # 2. le routeur : scène par défaut, #/supervision → ensemble, l'ancre dependances → Supervision
    assert "const VUES = { scene, supervision: ensemble, fil, journal, equipe, archives };" in app
    assert "import * as scene from './vues/scene.js';" in app
    assert "const page = morceaux[0] in VUES ? morceaux[0] : 'scene';" in app
    assert "'index'" not in app
    ancre = _corps(app, "if (brut === 'dependances')", "\n")
    assert "page: 'supervision'" in ancre and "onglet=dependances" in ancre and "cle: 'supervision'" in ancre
    assert "'#/supervision?onglet=dependances' : '#/supervision'" in ensemble
    # 3. l'en-tête, dans l'ordre : marque et projet · onglets · effectifs · direct · sources · mode autonome · attentes · Demander
    entete = _corps(commun, "function entete(ctx)", "\n}\n")
    _dans_l_ordre(entete, ["entete-appli", "el('h1'", "el('nav', { class: 'nav'", "PAGES.map(", "entete-etat",
                           "resumeAgents(ctx.etat)", "age-donnee", "iconeSources(ctx.etat)", "pastilleAutonome(ctx.etat)", "compteurAttentes(ctx.etat)",
                           "'Demander à l’Assistant'"])
    assert "'aria-current': p.id === ctx.page ? 'page' : null" in entete
    assert "el('button', { type: 'button', class: 'bouton demander', title: TITRE_DEMANDER, 'aria-label': 'Demander à l’Assistant', onclick: dialogueDemander }," in entete
    assert "export const PHRASE_HIERARCHIE =" in commun
    # le survol de l'icône dit d'abord ce qu'elle fait, puis la hiérarchie
    assert "export const TITRE_DEMANDER = `Demander à l’Assistant : ${PHRASE_HIERARCHIE.charAt(0).toLowerCase()}${PHRASE_HIERARCHIE.slice(1)}`;" in commun
    assert "Demander à l’Assistant" not in ensemble and "dialogueDemander" not in ensemble
    # 4. la pastille : « En direct » / « Figé · n s », l'info-bulle porte l'âge et la version ; le niveau reste lu
    age = _corps(commun, "function rafraichirAgeDonnee(noeud)", "\n}\n")
    assert "{ ok: 'En direct', rouge: 'Figé' }[niveau]" in age
    assert "niveau === 'ok' ? null : [' · ', el('span', { class: 'chiffres' }, duree(ms))]" in age
    assert "noeud.dataset.niveau = niveau;" in age
    assert "instantané v${etatCourant.version} · collecté en ${etatCourant.duree_collecte_ms} ms" in age
    assert "instantané reçu il y a ${duree(ms)}" in age
    assert "à jour" not in age
    # 5. ⚠ n : regroupe les sources en échec, absent si aucune ; le compteur d'attentes renvoie à #/, absent si 0
    sources = _corps(commun, "function iconeSources(etat)", "\n}\n")
    assert "if (!echecs.length) return null;" in sources
    assert "SOURCES_EN_ECHEC[s.nom]" in sources and "title:" in sources and "`⚠ ${echecs.length}`" in sources
    compteur = _corps(commun, "function compteurAttentes(etat)", "\n}\n")
    assert "if (!attentes || !attentes.length) return null;" in compteur
    assert "href: '#/'" in compteur and "pluriel(attentes.length, 'point')" in compteur
    assert "attentes.length === 1 ? 't’attend' : 't’attendent'" in compteur  # « n point(s) t'attend(ent) » en clair, plus de pastille nue
    assert "String(attentes.length)" not in compteur
    # 6. le socle : plus de pied (l'hôte injoignable non plus), plus de lien vers /scene/
    socle = _corps(commun, "export function rendreSocle(ctx)", "\n}\n")
    assert "footer" not in socle and "pied(" not in socle and "navigation(" not in socle
    assert "function pied(" not in commun and "function navigation(" not in commun
    assert "footer" not in _corps(commun, "export function rendreInjoignable", "\n}\n")  # l'écran de l'hôte injoignable non plus
    for nom, texte in js.items():
        assert "LIEN_SCENE" not in texte and "lien-scene" not in texte, nom
    # 7. plus de bandeau « Ce qui t'attend » nulle part : le compteur de l'en-tête le remplace hors de la scène
    assert "el('div', { class: `page-corps${ctx.page === 'scene' ? ' sur-scene' : ''}` }, contenu));" in socle
    assert "rendreBandeau" not in commun and "bandeauDeplie" not in commun and "bandeauDiscret" not in commun
    # 8. le plateau : créé une fois (variable de module), vide, réattaché à chaque rendu
    assert scene.count(PLATEAU) == 1
    rendu = _corps(scene, "export function rendre(ctx)", "\n}\n")
    assert "el('div'" not in rendu and "plateau" in rendu
    assert "ctx.contenu.append(el('section', { class: 'accueil' }, plateau, rail));" in rendu
    assert scene.index(PLATEAU) < scene.index("export function rendre(ctx)")
    assert "innerHTML" not in scene and "textContent" not in scene
    # 9. les fiches d'équipe renvoient à Supervision
    assert "el('a', { href: '#/supervision' }, '← Supervision')" in equipe
    assert "el('a', { href: '#/supervision', class: 'lien-suite' }, '← Supervision')" in equipe
    assert "Vue d’ensemble" not in equipe
    # 10. style : en-tête de 56 px, onglet courant souligné en ambre, pastille qui bat, plateau, mobile
    bloc = _corps(css, ".entete {", "}")
    assert "min-height: 56px" in bloc and "position: sticky" in bloc
    assert "border-bottom: 2px solid transparent" in _corps(css, ".nav a {", "}")
    assert "border-bottom-color: var(--ambre)" in _corps(css, '.nav a[aria-current="page"]', "}")
    assert "animation: battre" in _corps(css, ".pouls {", "}")
    assert "@keyframes battre" in css
    assert 'color: var(--rouge-clair)' in _corps(css, '.age-donnee[data-niveau="rouge"]', "}")
    assert "color: var(--ambre)" in _corps(css, ".sources-echec {", "}") and "color: var(--ambre)" in _corps(css, ".compteur-attentes {", "}")
    plateau = _corps(css, ".plateau {", "}")
    assert "radial-gradient(ellipse at 50% 45%, #1C2029 0%, #121418 70%)" in plateau
    assert "height: calc(100vh - 56px - 40px)" in plateau
    assert "border: 1px solid var(--bord)" in plateau and "border-radius: var(--rayon)" in plateau
    assert "padding: 20px" in _corps(css, ".page-corps.sur-scene {", "}")
    # téléphone : l'en-tête tient sur une ligne de 52 px (le détail est dans test_mobile_accueil.py) ; les onglets et les effectifs en partent
    mobile = _corps(css, "@media (max-width: 760px) {\n  :root", "\n}\n")
    assert ".nav, .compteur-attentes, .entete-etat .pilule:not(.age-donnee) { display: none; }" in mobile
    assert "height: 52px; min-height: 52px" in _corps(mobile, "  .entete {", "}")


@pytest.fixture(scope="module")
def js():
    fichiers = sorted(STATIC.glob("*.js")) + sorted((STATIC / "vues").glob("*.js")) + [STATIC / "style.css"]
    return {str(f.relative_to(STATIC)): f.read_text(encoding="utf-8") for f in fichiers}


def test_cadre_accueil(js):
    verifier_cadre_accueil(js)


def _remplace(fichier, ancien, nouveau):
    def mutation(js):
        assert ancien in js[fichier], ancien
        return {**js, fichier: js[fichier].replace(ancien, nouveau)}
    return mutation


NIV = "commun.js"
APP = "app.js"
EN = "vues/ensemble.js"
SC = "vues/scene.js"
EQ = "vues/equipe.js"
CSS = "style.css"
ENTETE_ETAT = "      resumeAgents(ctx.etat),\n      el('span', { class: 'pilule age-donnee' }),\n      iconeSources(ctx.etat),\n      pastilleAutonome(ctx.etat),\n      compteurAttentes(ctx.etat),\n"
MUTATIONS = {
    "onglet Journal de retour": _remplace(NIV, "  { id: 'fil', href: '#/fil', titre: 'Fil' },\n",
                                          "  { id: 'fil', href: '#/fil', titre: 'Fil' },\n  { id: 'journal', href: '#/journal', titre: 'Journal' },\n"),
    "onglets dans le désordre": _remplace(NIV, "  { id: 'scene', href: '#/', titre: 'Scène' },\n  { id: 'supervision', href: '#/supervision', titre: 'Supervision' },\n",
                                          "  { id: 'supervision', href: '#/supervision', titre: 'Supervision' },\n  { id: 'scene', href: '#/', titre: 'Scène' },\n"),
    "Fil renommé": _remplace(NIV, "titre: 'Fil' }", "titre: 'Fil des échanges' }"),
    "lien Journal retiré de Supervision": _remplace(EN, "el('a', { href: '#/journal' }, 'Journal des actions'));", ");"),
    "lien Archives pointe ailleurs": _remplace(EN, "el('a', { href: '#/archives' }, cloturees === null", "el('a', { href: '#/fil' }, cloturees === null"),
    "pied de Supervision non rendu": _remplace(EN, "    sectionIntegration(),\n    piedSupervision());", "    sectionIntegration());"),
    "route inconnue → Supervision": _remplace(APP, "morceaux[0] in VUES ? morceaux[0] : 'scene';", "morceaux[0] in VUES ? morceaux[0] : 'supervision';"),
    "#/supervision sans vue ensemble": _remplace(APP, "supervision: ensemble,", "supervision: scene,"),
    "ancre dependances vers la scène": _remplace(APP, "{ page: 'supervision', nom: null, params: new URLSearchParams('onglet=dependances'), cle: 'supervision' }",
                                                 "{ page: 'scene', nom: null, params: new URLSearchParams('onglet=dependances'), cle: 'scene' }"),
    "ancre dependances sans onglet": _remplace(APP, "new URLSearchParams('onglet=dependances'), cle: 'supervision'", "new URLSearchParams(''), cle: 'supervision'"),
    "onglet Dépendances revient sur #/": _remplace(EN, "'#/supervision?onglet=dependances' : '#/supervision'", "'#/?onglet=dependances' : '#/'"),
    "en-tête : onglets avant la marque": _remplace(NIV, "    el('div', { class: 'entete-titres' },\n      el('span', { class: 'entete-appli' }, 'Cime'),\n      el('h1', {}, ctx.etat.projet ? ctx.etat.projet.nom : 'projet inconnu')),\n    el('nav', { class: 'nav', 'aria-label': 'Pages' },\n      PAGES.map((p) => el('a', { href: p.href, 'aria-current': p.id === ctx.page ? 'page' : null }, p.titre))),\n",
                                                   "    el('nav', { class: 'nav', 'aria-label': 'Pages' },\n      PAGES.map((p) => el('a', { href: p.href, 'aria-current': p.id === ctx.page ? 'page' : null }, p.titre))),\n    el('div', { class: 'entete-titres' },\n      el('span', { class: 'entete-appli' }, 'Cime'),\n      el('h1', {}, ctx.etat.projet ? ctx.etat.projet.nom : 'projet inconnu')),\n"),
    "en-tête : compteur avant les sources": _remplace(NIV, ENTETE_ETAT,
                                                      "      resumeAgents(ctx.etat),\n      el('span', { class: 'pilule age-donnee' }),\n      pastilleAutonome(ctx.etat),\n      compteurAttentes(ctx.etat),\n      iconeSources(ctx.etat),\n"),
    "en-tête : pastille avant les effectifs": _remplace(NIV, ENTETE_ETAT,
                                                       "      el('span', { class: 'pilule age-donnee' }),\n      resumeAgents(ctx.etat),\n      iconeSources(ctx.etat),\n      pastilleAutonome(ctx.etat),\n      compteurAttentes(ctx.etat),\n"),
    "onglet courant jamais marqué": _remplace(NIV, "'aria-current': p.id === ctx.page ? 'page' : null }, p.titre))),\n    el('div', { class: 'entete-etat' }",
                                              "'aria-current': null }, p.titre))),\n    el('div', { class: 'entete-etat' }"),
    "bouton Demander sans info-bulle de hiérarchie": _remplace(NIV, "class: 'bouton demander', title: TITRE_DEMANDER,", "class: 'bouton demander',"),
    "bouton Demander sans action": _remplace(NIV, "title: TITRE_DEMANDER, 'aria-label': 'Demander à l’Assistant', onclick: dialogueDemander },", "title: TITRE_DEMANDER, 'aria-label': 'Demander à l’Assistant' },"),
    "bouton Demander de retour dans Supervision": _remplace(EN, "n === null ? 'ce qui t’attend : inconnu' : 'rien ne t’attend'));",
                                                            "n === null ? 'ce qui t’attend : inconnu' : 'rien ne t’attend'),\n    el('button', { type: 'button', class: 'bouton' }, 'Demander à l’Assistant'));"),
    "info-bulle de l'icône sans son nom": _remplace(NIV, "export const TITRE_DEMANDER = `Demander à l’Assistant : ${PHRASE_HIERARCHIE.charAt(0)", "export const TITRE_DEMANDER = `${PHRASE_HIERARCHIE.charAt(0)"),
    "phrase de hiérarchie supprimée": _remplace(NIV, "export const PHRASE_HIERARCHIE =", "export const PHRASE_HIERARCHIE_ANCIENNE ="),
    "pastille « à jour »": _remplace(NIV, "ok: 'En direct',", "ok: 'à jour',"),
    "pastille rouge sans « Figé »": _remplace(NIV, "rouge: 'Figé' }", "rouge: 'figée' }"),
    "durée affichée même en direct": _remplace(NIV, "niveau === 'ok' ? null : [' · ',", "[' · ',"),
    "niveau de la pastille plus écrit": _remplace(NIV, "  noeud.dataset.niveau = niveau;\n", ""),
    "info-bulle sans la version": _remplace(NIV, " · instantané v${etatCourant.version} · collecté en ${etatCourant.duree_collecte_ms} ms", ""),
    "info-bulle sans l'âge exact": _remplace(NIV, "const age = `instantané reçu il y a ${duree(ms)}`;", "const age = 'instantané reçu';"),
    "⚠ toujours affiché": _remplace(NIV, "  if (!echecs.length) return null;\n", ""),
    "⚠ sans libellés des sources": _remplace(NIV, "echecs.map((s) => SOURCES_EN_ECHEC[s.nom] || `${s.nom} en échec`)", "echecs.map((s) => s.nom)"),
    "⚠ sans nombre": _remplace(NIV, "`⚠ ${echecs.length}`", "'⚠'"),
    "compteur : la pastille nue de retour": _remplace(NIV, "{ class: 'compteur-attentes', href: '#/', title: 'Voir ce qui t’attend sur la scène' }, phrase);", "{ class: 'compteur-attentes', href: '#/', title: 'Voir ce qui t’attend sur la scène' }, String(attentes.length));"),
    "compteur : toujours « t'attendent »": _remplace(NIV, "attentes.length === 1 ? 't’attend' : 't’attendent'}`;\n  return el('a', { class: 'compteur-attentes'", "true ? 't’attendent' : 't’attendent'}`;\n  return el('a', { class: 'compteur-attentes'"),
    "compteur affiché à 0": _remplace(NIV, "if (!attentes || !attentes.length) return null;", "if (!attentes) return null;"),
    "compteur vers Supervision": _remplace(NIV, "class: 'compteur-attentes', href: '#/',", "class: 'compteur-attentes', href: '#/supervision',"),
    "pied de retour dans le socle": _remplace(NIV, "el('div', { class: `page-corps${ctx.page === 'scene' ? ' sur-scene' : ''}` }, contenu));",
                                              "el('div', { class: `page-corps${ctx.page === 'scene' ? ' sur-scene' : ''}` }, contenu), el('footer', { class: 'pied' }));"),
    "pied dans l'hôte injoignable": _remplace(NIV, "        delai ? reste : null))));", "        delai ? reste : null)),\n    el('footer', { class: 'pied' })));"),
    "LIEN_SCENE de retour": _remplace(NIV, "export const PAGES = [", "export const LIEN_SCENE = '/scene/?source=direct';\nexport const PAGES = ["),
    "classe lien-scene de retour": _remplace(CSS, ".demander { white-space: nowrap; flex: none; }", ".demander { white-space: nowrap; flex: none; }\n.lien-scene { color: var(--secondaire); }"),
    "bandeau de retour dans le socle": _remplace(NIV, "}` }, contenu));", "}` }, el('section', { class: 'bandeau' }), contenu));"),
    "rendreBandeau de retour": _remplace(NIV, "// En-tête unique (56 px, tous les écrans)", "function rendreBandeau() {}\n// En-tête unique (56 px, tous les écrans)"),
    "bandeauDeplie de retour": _remplace(NIV, "// En-tête unique (56 px, tous les écrans)", "let bandeauDeplie = false;\n// En-tête unique (56 px, tous les écrans)"),
    "plateau recréé à chaque rendu": lambda js: {**js, SC: js[SC].replace(PLATEAU + "\n", "").replace(
        "ctx.contenu.append(el('section', { class: 'accueil' }, plateau));",
        "const plateau = el('div', { class: 'plateau', id: 'plateau' });\n  ctx.contenu.append(el('section', { class: 'accueil' }, plateau));")},
    "plateau non réattaché": _remplace(SC, "{ class: 'accueil' }, plateau, rail)", "{ class: 'accueil' }, rail)"),
    "rail non réattaché": _remplace(SC, "{ class: 'accueil' }, plateau, rail)", "{ class: 'accueil' }, plateau)"),
    "plateau rempli à la création": _remplace(SC, "{ class: 'plateau', id: 'plateau' });", "{ class: 'plateau', id: 'plateau' }, 'bientôt');"),
    "plateau vidé par innerHTML": _remplace(SC, "  ctx.tic();", "  plateau.innerHTML = '';\n  ctx.tic();"),
    "fiche : lien vers la vue d'ensemble": _remplace(EQ, "el('a', { href: '#/supervision' }, '← Supervision')", "el('a', { href: '#/' }, '← Vue d’ensemble')"),
    "fiche : lien d'en-tête vers #/": _remplace(EQ, "el('a', { href: '#/supervision', class: 'lien-suite' }, '← Supervision')", "el('a', { href: '#/', class: 'lien-suite' }, '← Supervision')"),
    "en-tête sans hauteur de 56 px": _remplace(CSS, "  min-height: 56px;\n  display: flex; align-items: center; gap: 8px 32px;", "  min-height: 48px;\n  display: flex; align-items: center; gap: 8px 32px;"),
    "en-tête non collant": _remplace(CSS, "  position: sticky; top: 0; z-index: 10;\n  min-height: 56px;", "  min-height: 56px;"),
    "onglet courant sans ambre": _remplace(CSS, '.nav a[aria-current="page"] { color: var(--texte); border-bottom-color: var(--ambre); }',
                                           '.nav a[aria-current="page"] { color: var(--texte); border-bottom-color: var(--texte); }'),
    "pastille qui ne bat pas": _remplace(CSS, "background: var(--vert); box-shadow: 0 0 0 0 rgba(88, 168, 155, 0.5); animation: battre 2s infinite; }",
                                         "background: var(--vert); box-shadow: 0 0 0 0 rgba(88, 168, 155, 0.5); }"),
    "animation battre absente": _remplace(CSS, "@keyframes battre", "@keyframes autre"),
    "figé en vert": _remplace(CSS, '.age-donnee[data-niveau="rouge"] { color: var(--rouge-clair); }', '.age-donnee[data-niveau="rouge"] { color: var(--vert-clair); }'),
    "⚠ en rouge": _remplace(CSS, "background: transparent; color: var(--ambre);\n  border: 1px solid var(--ambre-bord)", "background: transparent; color: var(--rouge);\n  border: 1px solid var(--ambre-bord)"),
    "compteur en rouge": _remplace(CSS, "background: var(--ambre-fond); color: var(--ambre);", "background: var(--ambre-fond); color: var(--rouge);"),
    "plateau sans dégradé": _remplace(CSS, "radial-gradient(ellipse at 50% 45%, #1C2029 0%, #121418 70%)", "var(--carte)"),
    "plateau de mauvaise hauteur": _remplace(CSS, "height: calc(100vh - 56px - 40px);", "height: 100vh;"),
    "plateau sans bord": _remplace(CSS, "border: 1px solid var(--bord); border-radius: var(--rayon);\n  overflow: hidden;", "border-radius: var(--rayon);\n  overflow: hidden;"),
    "plateau à coins carrés": _remplace(CSS, "border: 1px solid var(--bord); border-radius: var(--rayon);\n  overflow: hidden;", "border: 1px solid var(--bord);\n  overflow: hidden;"),
    "scène sans marge de 20 px": _remplace(CSS, ".page-corps.sur-scene { max-width: none; padding: 20px; }", ".page-corps.sur-scene { max-width: none; padding: 0; }"),
    "mobile : effectifs gardés": _remplace(CSS, "  .nav, .compteur-attentes, .entete-etat .pilule:not(.age-donnee) { display: none; }\n", "  .nav, .compteur-attentes { display: none; }\n"),
    "mobile : onglets d'en-tête gardés": _remplace(CSS, "  .nav, .compteur-attentes, .entete-etat .pilule:not(.age-donnee) { display: none; }\n", "  .compteur-attentes, .entete-etat .pilule:not(.age-donnee) { display: none; }\n"),
    "mobile : en-tête de 56 px": _remplace(CSS, "  .entete { height: 52px; min-height: 52px;", "  .entete { height: 56px; min-height: 56px;"),
}


@pytest.mark.parametrize("nom", MUTATIONS)
def test_mutation_detectee(nom, js):
    mutee = MUTATIONS[nom](js)  # hors du raises : la mutation doit s'appliquer, sinon le test serait faux
    with pytest.raises(AssertionError):
        verifier_cadre_accueil(mutee)


def test_couverture_des_verifications():
    toutes = {n for n, v in globals().items() if n.startswith("verifier_") and callable(v)}
    assert toutes == {"verifier_cadre_accueil"} and MUTATIONS, sorted(toutes)
