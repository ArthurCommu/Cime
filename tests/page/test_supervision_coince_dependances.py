"""Supervision : l'onglet Dépendances qui plantait, « Ce qui coince » en liste dans un seul
cadre avec ses alarmes à voir groupées par type, integration hors de la grille, la ligne sous un agent sans info, le lien « n équipes clôturées »,
les chiffres sans mono, l'en-tête entre 760 et 1 000 px.

Même convention que test_supervision_organigramme.py : analyse de texte du JS et du CSS de static/ (`verifier_supervision_coince(js)` lève AssertionError, la table
MUTATIONS prouve qu'elle échoue quand on casse chaque comportement), puis node pour les fonctions pures (`verifier_fonctions`) et pour le rendu des écrans
avec un DOM minimal (`verifier_rendu_ensemble`, `verifier_rendu_des_vues`), chacun avec ses mutations ; sautés si node est absent.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

PAGE = Path(__file__).resolve().parents[2] / "src" / "cime" / "page"
STATIC = PAGE / "static"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
FEUILLES = ["style.css", "equipe.css", "archives.css", "pages-fil.css"]
EN, COM, CSS = "vues/ensemble.js", "commun.js", "style.css"
VUES = ["vues/ensemble.js", "vues/equipe.js", "vues/fil.js", "vues/journal.js", "vues/archives.js", "vues/scene.js", "vues/rail.js", "vues/mobile.js"]


def _corps(texte, debut, fin):
    i = texte.find(debut)
    assert i >= 0, debut
    j = texte.find(fin, i + len(debut))
    assert j >= 0, fin
    return texte[i:j]


def _declarations(css, selecteur):
    """Les déclarations de la règle dont le sélecteur est exactement `selecteur` : {propriété: valeur}."""
    m = re.search(r"(?:^|\n) *" + re.escape(selecteur) + r" \{([^}]*)\}", css)
    assert m, selecteur
    corps = re.sub(r"/\*.*?\*/", "", m.group(1), flags=re.S)
    resultat = {}
    for d in corps.split(";"):
        if d.strip():
            nom, _, valeur = d.partition(":")
            resultat[nom.strip()] = valeur.strip()
    return resultat


def _ordre(texte, *morceaux):
    positions = []
    for m in morceaux:
        assert m in texte, m
        positions.append(texte.index(m))
    assert positions == sorted(positions), morceaux


# ---------------------------------------------------------------------------
# Tout identifiant appelé dans une vue est défini ou importé (point 1)
# ---------------------------------------------------------------------------
GLOBAUX = {
    "Array", "Boolean", "Date", "Error", "JSON", "Map", "Math", "Number", "Object", "Promise", "Set", "String", "URLSearchParams", "Infinity", "Intl",
    "parseInt", "parseFloat", "isNaN", "setTimeout", "clearTimeout", "setInterval", "clearInterval", "requestAnimationFrame", "addEventListener",
    "removeEventListener", "decodeURIComponent", "encodeURIComponent", "fetch", "alert", "confirm", "getComputedStyle", "matchMedia", "scrollTo",
    "structuredClone", "queueMicrotask", "KeyboardEvent", "PointerEvent", "MouseEvent", "performance", "navigator", "Blob", "AbortController", "TextDecoder", "TextEncoder", "ResizeObserver", "IntersectionObserver", "MutationObserver", "CustomEvent", "Event", "Node", "Symbol", "RegExp",
    "if", "for", "while", "switch", "catch", "function", "return", "typeof", "await", "async", "import", "new", "super",
}


def identifiants_non_definis(source):
    """Les noms appelés `nom(` qui ne sont ni importés, ni déclarés (function/const/let/class), ni paramètres, ni globaux du navigateur."""
    sans_commentaires = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    sans_commentaires = re.sub(r"`(?:[^`\\]|\\.)*`", "''", sans_commentaires)  # gabarits : le texte n'est pas du code
    sans_chaines = re.sub(r"'(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\"", "''", sans_commentaires)
    sans_chaines = re.sub(r"//[^\n]*", "", sans_chaines)  # commentaires de ligne, une fois les chaînes (et leurs URL) retirées
    definis = set()
    for bloc in re.findall(r"import\s*\{([^}]*)\}\s*from", sans_chaines):
        definis |= {n.split(" as ")[-1].strip() for n in bloc.replace("\n", " ").split(",") if n.strip()}
    definis |= set(re.findall(r"import\s*\*\s*as\s+(\w+)", sans_chaines))
    definis |= set(re.findall(r"\b(?:function\*?|class)\s+(\w+)", sans_chaines))
    for decl in re.findall(r"\b(?:const|let|var)\s+(\{[^}]*\}|\[[^\]]*\]|\w+)", sans_chaines):
        definis |= set(re.findall(r"\w+", decl))
    for params in re.findall(r"\(([^()]*)\)\s*=>|function\s*\w*\s*\(([^()]*)\)|catch\s*\((\w+)\)", sans_chaines):
        for p in params:
            definis |= set(re.findall(r"\w+", p))
    definis |= set(re.findall(r"\b(\w+)\s*=>", sans_chaines))
    appeles = set(re.findall(r"(?<![\w.$])([A-Za-z_]\w*)\s*\(", sans_chaines))
    # les paramètres de méthode d'objet (`ontoggle() {}`) et les noms de fonctions fléchées en propriété ne sont pas des appels libres
    return sorted(n for n in appeles - definis - GLOBAUX if not re.search(r"\b" + n + r"\s*\([^()]*\)\s*\{", sans_chaines))


# ---------------------------------------------------------------------------
# Vérification statique
# ---------------------------------------------------------------------------
def verifier_supervision_coince(js):
    commun, ens, css = js[COM], js[EN], js[CSS]
    entete_import = _corps(ens, "import {", "} from '../commun.js'")

    # 1. l'onglet Dépendances : lienEquipe importé, et plus généralement aucune vue n'appelle un identifiant sans le définir
    assert re.search(r"\blienEquipe\b", entete_import), "lienEquipe n'est plus importé : l'onglet Dépendances plante"
    assert "export const lienEquipe = " in commun
    for vue in VUES:
        assert identifiants_non_definis(js[vue]) == [], (vue, identifiants_non_definis(js[vue]))

    # 4. la ligne sous un agent : une alarme grave, sinon l'attente, sinon une alarme à voir, sinon la tâche — jamais une info
    quoi = _corps(ens, "function quoiAgent(a)", "\n}\n")
    assert "const autre = alarmes.find((x) => x.gravite !== 'info');" in quoi
    assert "alarmes[0]" not in quoi
    _ordre(quoi, "if (alarme)", "if (attend)", "if (autre)", "a.tache")

    # 2. « Ce qui coince » : fonctions pures dans le socle, rendu par ensemble.js
    assert "export function grouperAlarmes(alarmes) {" in commun and "export function resumeGroupeProblemes(groupe) {" in commun
    assert "export const comparerDepuis = " in commun
    pure = _corps(commun, "export function grouperAlarmes(alarmes) {", "\n}\n")
    assert "rang(x) - rang(y) || comparerDepuis(x, y)" in pure  # grave → à voir → info, la plus ancienne d'abord
    assert "siennes.length === 1 ? seule(siennes[0])" in pure and "genre: 'groupe', gravite: 'a_voir'" in pure  # seule de son type : une ligne ordinaire
    assert "...grouperInfos(triees).map(" in pure
    _ordre(pure, "a.gravite === 'a_voir'", "...grouperInfos(triees)")
    assert "genre: 'groupe', gravite: 'grave'" not in pure  # les graves ne sont jamais groupées
    resume = _corps(commun, "export function resumeGroupeProblemes(groupe) {", "\n}\n")
    assert "new Set(" in resume and "a.agents.map(nomAgent)" in resume and "×${groupe.alarmes.length}" in resume
    groupe = _corps(ens, "function groupeProblemes(groupe)", "\n}\n")
    assert "const faire = groupe.alarmes[0].quoi_faire;" in groupe and "a.quoi_faire !== faire ?" in groupe  # « Quoi faire » écrit une fois
    assert "class: `al alarme-groupe groupe-probleme ton-${groupe.ton}`" in groupe and "open" not in groupe.replace("ontoggle", "")
    assert "groupe.alarmes.map(" in groupe and "ageAlarme(a)" in groupe and "mesurerLargeur" in groupe  # le dépliage montre chaque alarme avec son âge
    assert "el('span', { class: 'al-age discret' }, ageAlarme(groupe.alarmes[0])),\n" in groupe

    # 3. integration hors de la grille ; 5. le seul lien des équipes clôturées, avec le compte
    org = _corps(ens, "function organigramme()", "\n}\n")
    assert "equipeEnRetrait(q, etat.agents, etat.alarmes)" in org and "const cartes = actives ? actives.filter((q) => !retraits.includes(q)) : [];" in org
    assert org.rstrip().endswith("ligneLiens(retraits));")
    liens = _corps(ens, "function ligneLiens(retraits)", "\n}\n")
    assert "lienEquipe(q.nom), ' (spéciale, sans session)'" in liens
    assert "`${pluriel(cloturees, 'équipe clôturée', 'équipes clôturées')} →`" in liens and "'Équipes clôturées →'" in liens
    assert "q.statut === 'terminee').length" in liens
    assert ens.count("href: '#/archives'") == 1  # un seul lien : sous la grille, pas au pied
    assert "archives" not in _corps(ens, "function piedSupervision()", "\n}\n")
    en_retrait = _corps(commun, "export function equipeEnRetrait(equipe, agents, alarmes) {", "\n}\n")
    assert "!equipe.speciale || equipe.statut === 'terminee' || !Array.isArray(agents) || !Array.isArray(alarmes)" in en_retrait
    assert "a.vivant === false && !a.session_tmux" in en_retrait
    assert "alarmesDe(alarmes, { equipe: equipe.nom }).length === 0" in en_retrait and "alarmesDe(alarmes, { agent: a.id }).length === 0" in en_retrait
    assert _declarations(css, ".org-liens").get("font-size") == "13px"

    # 2 (CSS). la liste dans un seul cadre : ~64 px par alarme, rayon 10, filets, « Quoi faire : » en gras (pas en ambre)
    cadre = _declarations(css, ".alarmes-cadre")
    assert cadre.get("border-radius") == "var(--rayon)" and "var(--bord)" in cadre.get("border", "") and cadre.get("overflow") == "hidden" and cadre.get("gap") == "0"
    assert re.search(r"--rayon: 10px;", css)
    ligne = _declarations(css, ".al")
    assert ligne.get("grid-template-columns") == "74px minmax(0, 1fr) auto" and ligne.get("padding") == "12px 16px" and "var(--bord-doux)" in ligne.get("border-bottom", "")
    assert _declarations(css, ".al-faire b").get("font-weight") == "600" and "--ambre" not in _declarations(css, ".al-faire b").get("color", "")
    assert "var(--ambre)" not in _declarations(css, ".al-faire").get("color", "") and "text-transform" not in _declarations(css, ".al-faire")
    assert "alarmes-cadre" in ens

    # 6. polices : les chiffres de la Consommation ne sont plus en mono ; tabular-nums
    postes = _corps(ens, "function postesConso(postes)", "function sectionConsommation()")
    assert "el('span', { class: 'poste-valeur' }, jetonsOuInconnu(p.lus_15min))" in postes and "mono poste-valeur" not in ens
    assert "mono" not in _corps(ens, "function sectionConsommation()", "// ----")
    assert "tabular-nums" in _declarations(css, ".poste-valeur").get("font-variant-numeric", "") and "tabular-nums" in _declarations(css, ".conso-grand").get("font-variant-numeric", "")
    assert "font-family" not in _declarations(css, ".poste-valeur") and "font-family" not in _declarations(css, ".conso-grand")
    assert "tabular-nums" in _declarations(css, ".al-age").get("font-variant-numeric", "")

    # 7. l'en-tête entre 760 et 1 240 px : onglets et pastille sur une ligne, effectifs masqués jusqu'à 1 240 px, rien au-dessus, le bloc mobile seul sous 760
    assert "effectifs-texte" in _corps(commun, "export function resumeAgents(etat)", "function niveauAge")
    nowrap = re.search(r"(?:^|\n)\.nav a, \.pilule \{ white-space: nowrap; \}", css)
    assert nowrap, "les onglets et la pastille doivent rester sur une ligne"
    bloc = _corps(css, "@media (max-width: 1240px) {\n", "\n}\n")
    assert ".entete .effectifs-texte { display: none; }" in bloc
    assert css.count("@media (max-width: 1240px)") == 1 and "@media (max-width: 1000px)" not in css
    assert ".effectifs-texte" not in css.replace(bloc, "").replace(".effectifs-texte { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }", "")  # ailleurs, seulement l'ellipse : au-dessus de 1 240 px les effectifs restent
    _ordre(css, "@media (max-width: 1240px)", "@media (max-width: 760px) {\n  :root")  # le bloc mobile vient après et reste seul sous 760
    assert ".nav, .compteur-attentes, .entete-etat .pilule:not(.age-donnee) { display: none; }" in _corps(css, "@media (max-width: 760px) {\n  :root", "\n}\n")


# ---------------------------------------------------------------------------
# Fonctions pures, exécutées par node
# ---------------------------------------------------------------------------
SONDE_PURE = r"""
const c = await import(process.argv[2]);
const A = (id, type, gravite, agents = [], equipes = [], depuis = null) => ({ id, type, gravite, agents, equipes, depuis, mesure: 'm' + id, quoi_faire: 'q' + type });
const t = (h) => `2026-10-11T${h}:00.000Z`;
const entree = [
  A(1, 'contexte_au_repos', 'a_voir', ['coord-livraison'], ['livraison'], t('12:10')),
  A(2, 'contexte_au_repos', 'a_voir', ['coord-scene'], ['scene'], t('12:00')),
  A(3, 'contexte_au_repos', 'a_voir', ['assistant', 'coord-scene'], [], t('12:20')),
  A(4, 'action_refusee', 'a_voir', ['assistant'], [], t('12:30')),
  A(5, 'fige', 'grave', ['coord-x'], [], t('12:40')),
  A(6, 'fige', 'grave', ['coord-y'], [], t('12:05')),
  A(7, 'retard_sur_base', 'info', [], ['page'], t('11:00')),
  A(8, 'retard_sur_base', 'info', [], ['hote'], t('11:30')),
  A(9, 'session_orpheline', 'a_voir', [], [], t('13:00')),
  A(10, 'session_orpheline', 'a_voir', [], [], null),
  A(11, 'gros_poste', 'a_voir', [], ['page'], null),
  A(12, 'fige', 'xyz', [], [], t('09:00')),
  A(13, 'autorisation_en_attente', 'a_voir', ['coord-page'], ['page'], t('12:50')),
  A(14, 'autorisation_en_attente', 'a_voir', ['coord-hote'], ['hote'], t('12:51')),
];
const avant = JSON.stringify(entree);
const items = c.grouperAlarmes(entree);
const resume = (g) => c.resumeGroupeProblemes(g);
const vide = c.grouperAlarmes([]);
const ag = (id, vivant, session) => ({ id, equipe: 'integration', vivant, session_tmux: session });
const eq = (extra = {}) => ({ nom: 'integration', speciale: true, statut: 'au_repos', ...extra });
const retrait = [
  c.equipeEnRetrait(eq(), [], []),
  c.equipeEnRetrait(eq({ speciale: false }), [], []),
  c.equipeEnRetrait(eq(), [ag('coord-integration', true, 'cc-coord-integration')], []),
  c.equipeEnRetrait(eq(), [ag('coord-integration', false, null)], []),
  c.equipeEnRetrait(eq(), [ag('coord-integration', null, null)], []),
  c.equipeEnRetrait(eq(), [], [A(1, 'retard_sur_base', 'info', [], ['integration'])]),
  c.equipeEnRetrait(eq(), [ag('coord-integration', false, null)], [A(1, 'session_disparue', 'grave', ['coord-integration'])]),
  c.equipeEnRetrait(eq(), null, []),
  c.equipeEnRetrait(eq(), [], null),
  c.equipeEnRetrait(eq({ statut: 'terminee' }), [], []),
  c.equipeEnRetrait(eq(), [{ id: 'w', equipe: 'autre', vivant: true, session_tmux: 'cc-w' }], []),
  c.equipeEnRetrait(eq(), [ag('coord-integration', false, 'cc-reste')], []),
];
console.log(JSON.stringify({
  items: items.map((i) => ({ genre: i.genre, gravite: i.gravite, type: i.type, ids: i.alarmes.map((a) => a.id), ton: i.ton })),
  resumes: items.filter((i) => i.genre === 'groupe' && i.gravite === 'a_voir').map(resume),
  vide, retrait, inchange: JSON.stringify(entree) === avant,
}));
"""

ITEMS_ATTENDUS = [
    {"genre": "seule", "gravite": "grave", "type": "fige", "ids": [6], "ton": "rouge"},  # deux graves du même type : deux lignes, la plus ancienne d'abord
    {"genre": "seule", "gravite": "grave", "type": "fige", "ids": [5], "ton": "rouge"},
    {"genre": "groupe", "gravite": "a_voir", "type": "contexte_au_repos", "ids": [2, 1, 3], "ton": "ambre"},  # le groupe prend la place de son alarme la plus ancienne ; dans le groupe, la plus ancienne d'abord
    {"genre": "seule", "gravite": "a_voir", "type": "action_refusee", "ids": [4], "ton": "ambre"},  # seule de son type : une ligne ordinaire
    {"genre": "groupe", "gravite": "a_voir", "type": "autorisation_en_attente", "ids": [13, 14], "ton": "ambre"},
    {"genre": "groupe", "gravite": "a_voir", "type": "session_orpheline", "ids": [9, 10], "ton": "ambre"},  # sans cible, `depuis: null` en dernier
    {"genre": "seule", "gravite": "a_voir", "type": "gros_poste", "ids": [11], "ton": "ambre"},
    {"genre": "seule", "gravite": "xyz", "type": "fige", "ids": [12], "ton": "gris"},  # gravité inconnue : une ligne, après les à voir, avant les infos
    {"genre": "groupe", "gravite": "info", "type": "retard_sur_base", "ids": [7, 8], "ton": "gris"},  # les infos en dernier, groupées
]
RESUMES_ATTENDUS = [
    {"mot": "À voir", "type": "Contexte lourd au repos", "nombre": 3, "cibles": ["coord-scene", "coord-livraison", "Assistant"], "ligne": "Contexte lourd au repos ×3 · coord-scene, coord-livraison, Assistant"},  # cibles sans doublon, noms lisibles
    {"mot": "À voir", "type": "Autorisation en attente", "nombre": 2, "cibles": ["coord-page", "coord-hote"], "ligne": "Autorisation en attente ×2 · coord-page, coord-hote"},
    {"mot": "À voir", "type": "Session hors organigramme", "nombre": 2, "cibles": [], "ligne": "Session hors organigramme ×2"},  # une alarme sans cible : pas de « · » orphelin
]
RETRAIT_ATTENDU = [True, False, False, True, False, False, False, False, False, False, True, False]


def executer_pures(dossier_static):
    sonde = dossier_static / "sonde-lot4.mjs"
    sonde.write_text(SONDE_PURE, encoding="utf-8")
    res = subprocess.run(["node", str(sonde), str(dossier_static / "commun.js")], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


def verifier_fonctions(dossier_static):
    r = executer_pures(dossier_static)
    assert r["items"] == ITEMS_ATTENDUS, r["items"]
    assert r["resumes"] == RESUMES_ATTENDUS, r["resumes"]
    assert r["vide"] == [] and r["inchange"] is True  # l'entrée n'est pas modifiée
    assert r["retrait"] == RETRAIT_ATTENDU, r["retrait"]


# ---------------------------------------------------------------------------
# Le rendu exécuté par node (DOM minimal)
# ---------------------------------------------------------------------------
DOM = r"""
import { readFileSync } from 'node:fs';
class Node {}
class Txt extends Node { constructor(t) { super(); this.data = t; } }
class Elt extends Node {
  constructor(tag) { super(); this.tag = tag; this.attrs = {}; this.children = []; this.dataset = {}; this.style = {};
    this.classList = { contains: (c) => this.classes.includes(c), toggle() {}, add() {}, remove() {} }; }
  setAttribute(k, v) { this.attrs[k] = v; }
  getAttribute(k) { return this.attrs[k] ?? null; }
  addEventListener() {}
  removeEventListener() {}
  append(...n) { this.children.push(...n); }
  prepend(...n) { this.children.unshift(...n); }
  querySelectorAll() { return []; }
  querySelector() { return null; }
  remove() {}
  focus() {}
  replaceChildren(...n) { this.children = n; }
  get firstChild() { return this.children[0]; }
  get clientWidth() { return 800; }
  get offsetHeight() { return 100; }
  get classes() { return (this.attrs.class || '').split(/\s+/).filter(Boolean); }
}
globalThis.Node = Node;
globalThis.document = { createElement: (t) => new Elt(t), createTextNode: (t) => new Txt(t), documentElement: new Elt('html'), body: new Elt('body'),
  querySelector: () => null, querySelectorAll: () => [], addEventListener() {}, removeEventListener() {}, visibilityState: 'hidden', title: '' };
globalThis.window = globalThis;
globalThis.addEventListener = () => {};
globalThis.localStorage = { getItem: () => null, setItem() {} };
globalThis.ResizeObserver = class { observe() {} disconnect() {} };
globalThis.requestAnimationFrame = (f) => f();
globalThis.history = { replaceState() {} };
globalThis.location = { hash: '' };
const texte = (n) => (n instanceof Txt ? n.data : (n.children || []).map(texte).join(''));
const sous = (n) => (n instanceof Elt ? [n, ...n.children.flatMap(sous)] : []);
const a = (n, c) => sous(n).filter((m) => m.classes.includes(c));
"""

SONDE_ENSEMBLE = DOM + r"""
const ens = await import(process.argv[2]);
const jeux = JSON.parse(readFileSync(process.argv[3], 'utf8'));
const sortie = {};
for (const [nom, etat] of Object.entries(jeux)) {
  const sortieJeu = {};
  for (const onglet of ['organigramme', 'dependances']) {
    const c = new Elt('main');
    const params = new URLSearchParams(onglet === 'dependances' ? 'onglet=dependances' : '');
    try {
      ens.rendre({ etat, contenu: c, route: { params }, horloge: { maintenant: () => Date.parse(etat.genere_a) }, journal: [], tic() {} });
    } catch (e) { sortieJeu[onglet] = { erreur: `${e.name}: ${e.message}` }; continue; }
    const org = sous(c).find((n) => n.classes.includes('organigramme'));
    const alarmes = sous(c).find((n) => n.attrs.id === 'alarmes');
    const cadre = alarmes ? a(alarmes, 'alarmes')[0] : null;
    sortieJeu[onglet] = {
      texte: texte(c),
      enfants: org ? org.children.map((n) => n.classes[0]) : null,
      grille: org ? a(org, 'org-equipes')[0] ? a(org, 'org-equipes')[0].children.map((q) => texte(a(q, 'org-equipe-nom')[0])) : null : null,
      liens: org ? a(org, 'org-liens').map((p) => ({ texte: texte(p), href: sous(p).filter((n) => n.tag === 'a').map((n) => n.attrs.href) })) : null,
      archives: sous(c).filter((n) => n.tag === 'a' && n.attrs.href === '#/archives').length,
      agents: org ? a(org, 'ag').map((l) => ({ id: texte(a(l, 'ag-id')[0]), quoi: a(l, 'ag-quoi').map(texte) })) : [],
      graphe: sous(c).filter((n) => n.classes.includes('graphe-boite')).length,
      listeDeps: sous(c).filter((n) => n.classes.includes('graphe-liste')).length,
      cadres: alarmes ? a(alarmes, 'alarmes-cadre').length : 0,
      lignes: cadre ? cadre.children.map((n) => ({
        tag: n.tag, classes: n.classes, gravite: n.dataset.gravite ?? null, type: n.dataset.type ?? null,
        texte: texte(n), faire: a(n, 'al-faire').map(texte), mot: a(n, 'probleme-mot').map(texte), age: a(n, 'al-age').map(texte),
        gras: a(n, 'al-faire').flatMap((f) => sous(f).filter((m) => m.tag === 'b').map(texte)),
        ouvert: 'open' in n.attrs, detail: a(n, 'alarme-detail').length, lignesGroupe: a(n, 'groupe-alarme').length,
      })) : null,
      entete: alarmes ? texte(sous(alarmes).find((n) => n.tag === 'h2')) + '|' + a(alarmes, 'sous-titre').map(texte).join('') : null,
      pied: sous(c.children[c.children.length - 1]).filter((n) => n.tag === 'a').map((n) => [n.attrs.href, texte(n)]),
      conso: texte(sous(c).find((n) => n.attrs.id === 'consommation') || new Txt('')),
      monoConso: sous(sous(c).find((n) => n.attrs.id === 'consommation') || new Txt('')).filter((n) => n.classes.includes('mono') && !n.classes.includes('poste-nom')).length,
    };
  }
  sortie[nom] = sortieJeu;
}
console.log(JSON.stringify(sortie));
"""

SONDE_VUES = DOM + r"""
const chemin = process.argv[2];
const jeux = JSON.parse(readFileSync(process.argv[3], 'utf8'));
const vues = ['ensemble', 'equipe', 'fil', 'journal', 'archives'];
const sortie = {};
for (const vue of vues) {
  const mod = await import(`${chemin}/vues/${vue}.js`);
  for (const [nom, etat] of Object.entries(jeux)) {
    for (const route of [{ nom: 'hote', params: '' }, { nom: 'inconnue', params: 'onglet=dependances' }]) {
      const c = new Elt('main');
      const cle = `${vue}|${nom}|${route.nom}|${route.params}`;
      try {
        mod.rendre({ etat, contenu: c, route: { page: vue, nom: route.nom, params: new URLSearchParams(route.params) }, horloge: { maintenant: () => Date.parse(etat.genere_a) },
          journal: etat.journal_test, tic() {}, source: { terminal: async () => null, agentsAvecTerminal: () => [] }, rerendre() {} });
        sortie[cle] = c.children.length > 0 ? 'ok' : 'vide';
      } catch (e) { sortie[cle] = `${e.name}: ${e.message}`; }
    }
  }
}
console.log(JSON.stringify(sortie));
"""


def _exemple():
    return json.loads((FIXTURES / "exemple-etat.json").read_text(encoding="utf-8"))


def _agent(ident, role, equipe, etat="travaille", vivant=True, tache=None):
    return {"id": ident, "role": role, "equipe": equipe, "parent": "assistant", "session_tmux": ("cc-" + ident) if vivant else None, "vivant": vivant,
            "etat": etat, "etat_depuis": "2026-10-07T12:00:00.000Z", "etat_source": "hook:Stop", "tache": tache, "derniere_phrase": "phrase technique",
            "modele": "claude-sonnet-5-5", "contexte": {"tokens": 1000, "limite": 1000000, "source": "transcript"}, "cout_usd_estime": 1.5,
            "consommation": None, "brouillon": None, "dettes": [], "file": [], "occupe_par": None}


def _equipe(nom, statut="au_repos", speciale=False, depend_de=()):
    return {"nom": nom, "mission": "Une mission.", "speciale": speciale, "statut": statut, "cloturee_le": None, "branche": "equipe/" + nom, "commit": "abc1234",
            "worktree": "/x", "avancement": {"faites": 3, "en_cours": 1, "a_faire": 2}, "fichiers_touches": [], "perimetre_declare": [],
            "hors_perimetre": [], "retard_sur_base": 0, "en_avance_sur_base": 0, "depend_de": list(depend_de)}


def _alarme(type_, gravite, agents=(), equipes=(), depuis="2026-10-07T12:00:00.000Z", n=0):
    return {"id": f"{type_}:{n}", "type": type_, "gravite": gravite, "agents": list(agents), "equipes": list(equipes),
            "depuis": depuis, "mesure": f"mesure {type_} {n}", "quoi_faire": f"faire {type_}", "destinataire": "utilisateur"}


def _jeux_ensemble():
    base = _exemple()

    def variante(modifier, partir_de=None):
        v = json.loads(json.dumps(partir_de or base))
        modifier(v)
        return v

    def onze(v):
        noms = [q["nom"] for q in v["equipes"]]
        for i in range(11 - len(noms)):
            v["equipes"].append(_equipe(f"extra{i}", depend_de=[noms[i % len(noms)]]))
        v["agents"] += [_agent(f"coord-extra{i}", "coordinateur", f"extra{i}") for i in range(11 - len(noms))]

    def integration(v):
        v["equipes"] += [_equipe("integration", speciale=True), _equipe("signaux", "terminee"), _equipe("scene", "terminee")]

    def integration_active(v):
        integration(v)
        v["agents"].append(_agent("coord-integration", "coordinateur", "integration"))

    def integration_alarmee(v):
        integration(v)
        v["alarmes"].append(_alarme("recouvrement", "grave", [], ["integration"]))

    def reel(v):
        # le jeu d'un instantané réel : 8 équipes visibles, 6 alarmes à voir (doublons de type), 8 infos
        v["equipes"] = [_equipe(n, depend_de=d) for n, d in [("fondation", []), ("observation", ["fondation"]), ("hote", ["observation"]), ("page", ["hote"]),
                                                              ("scene", ["page"]), ("ergonomie", []), ("verification", ["page"]), ("livraison", ["fondation"])]]
        v["equipes"] += [_equipe("integration", speciale=True), _equipe("signaux", "terminee")]
        v["agents"] = [a for a in v["agents"] if a["role"] in ("assistant", "utilisateur")]
        v["agents"] += [_agent(f"coord-{q['nom']}", "coordinateur", q["nom"]) for q in v["equipes"] if q["nom"] not in ("integration", "signaux")]
        v["alarmes"] = [
            _alarme("contexte_au_repos", "a_voir", ["coord-livraison"], ["livraison"], n=1), _alarme("contexte_au_repos", "a_voir", ["coord-scene"], ["scene"], n=2),
            _alarme("contexte_au_repos", "a_voir", ["assistant"], [], n=3), _alarme("action_refusee", "a_voir", ["assistant"], [], n=4),
            _alarme("action_refusee", "a_voir", ["assistant"], [], n=5), _alarme("gros_poste", "a_voir", ["assistant"], [], n=6),
        ] + [_alarme("retard_sur_base", "info", [], [n], n=i) for i, n in enumerate(["signaux", "observation", "fondation", "livraison", "hote", "ergonomie", "page", "scene"])]

    def ligne_agent(info_seule=False, a_voir=False, grave=False):
        def modifier(v):
            cible = next(a for a in v["agents"] if a["id"] == "coord-page")
            cible["tache"] = "Écrire le test de rendu"
            v["alarmes"] = [x for x in v["alarmes"] if "coord-page" not in x["agents"]]
            v["fil"] = [m for m in v["fil"] if m.get("de") != "coord-page" and m.get("a") != "coord-page"]
            if info_seule or a_voir or grave:
                v["alarmes"].append(_alarme("retard_sur_base", "info", ["coord-page"], ["page"], n=1))
            if a_voir:
                v["alarmes"].append(_alarme("gros_poste", "a_voir", ["coord-page"], ["page"], n=2))
            if grave:
                v["alarmes"].append(_alarme("session_disparue", "grave", ["coord-page"], ["page"], n=3))
        return modifier

    return {
        "exemple": base,
        "onze equipes": variante(onze),
        "integration seule": variante(integration),
        "integration avec agent": variante(integration_active),
        "integration avec alarme": variante(integration_alarmee),
        "reel": variante(reel),
        "agent sans alarme": variante(ligne_agent()),
        "agent avec info seule": variante(ligne_agent(info_seule=True)),
        "agent info et a voir": variante(ligne_agent(a_voir=True)),
        "agent grave et info": variante(ligne_agent(grave=True)),
        "sans alarme": variante(lambda v: v.update(alarmes=[])),
        "alarmes inconnues": variante(lambda v: v.update(alarmes=None)),
        "equipes inconnues": variante(lambda v: v.update(equipes=None)),
        "agents inconnus": variante(lambda v: v.update(agents=None)),
        "aucune alarme a voir": variante(lambda v: v.update(alarmes=[a for a in v["alarmes"] if a["gravite"] == "info"])),
    }


def _ecrire_et_lancer(dossier_static, sonde, jeux, cible):
    (dossier_static / "sonde.mjs").write_text(sonde, encoding="utf-8")
    (dossier_static / "jeux.json").write_text(json.dumps(jeux), encoding="utf-8")
    res = subprocess.run(["node", str(dossier_static / "sonde.mjs"), str(cible), str(dossier_static / "jeux.json")], capture_output=True, text=True, timeout=120)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


def verifier_rendu_ensemble(dossier_static):
    r = _ecrire_et_lancer(dossier_static, SONDE_ENSEMBLE, _jeux_ensemble(), dossier_static / "vues" / "ensemble.js")

    # 1. chaque onglet se rend, avec l'exemple et avec onze équipes ; l'onglet Dépendances dessine son graphe et sa liste
    for nom in ("exemple", "onze equipes"):
        for onglet in ("organigramme", "dependances"):
            assert "erreur" not in r[nom][onglet], (nom, onglet, r[nom][onglet])
    assert r["onze equipes"]["dependances"]["graphe"] == 10 and r["onze equipes"]["dependances"]["listeDeps"] == 1
    assert r["exemple"]["dependances"]["graphe"] == 6 and r["exemple"]["dependances"]["graphe"] > 0  # les 6 équipes non terminées de l'exemple, celle dont le coordinateur dort comprise
    assert "dépend de" in r["onze equipes"]["dependances"]["texte"]
    for nom, jeu in r.items():
        for onglet, vue in jeu.items():
            assert "erreur" not in vue, (nom, onglet, vue)  # aucun état, même vide ou inconnu, ne lève d'erreur

    # 3. integration hors de la grille, dans la ligne de liens ; une équipe spéciale avec agent ou alarme reste une carte
    seule = r["integration seule"]["organigramme"]
    noms = lambda v: [n.split(" ·")[0] for n in v["grille"]]
    assert "integration" not in noms(seule) and seule["enfants"] == ["org-tete", "org-equipes", "org-liens"], seule["enfants"]
    assert len(seule["liens"]) == 1 and seule["liens"][0]["texte"] == "integration (spéciale, sans session) · 3 équipes clôturées →", seule["liens"]
    assert seule["liens"][0]["href"] == ["#/equipe/integration", "#/archives"]
    avec_agent = r["integration avec agent"]["organigramme"]
    assert "integration" in noms(avec_agent) and avec_agent["liens"][0]["texte"] == "3 équipes clôturées →"
    avec_alarme = r["integration avec alarme"]["organigramme"]
    assert "integration" in noms(avec_alarme) and "spéciale, sans session" not in avec_alarme["liens"][0]["texte"]
    ex = r["exemple"]["organigramme"]
    assert ex["liens"][0]["texte"] == "1 équipe clôturée →" and ex["liens"][0]["href"] == ["#/archives"]  # le compte, au singulier
    assert "verification" in noms(ex)  # spéciale mais vivante : elle garde sa carte
    # 5. un seul lien des équipes clôturées dans tout l'écran, et le pied n'a que le journal
    for nom, jeu in r.items():
        for onglet, vue in jeu.items():
            assert vue["archives"] == (1 if onglet == "organigramme" else 0), (nom, onglet, vue["archives"])
            assert vue["pied"] == [["#/journal", "Journal des actions"]], vue["pied"]
    assert r["equipes inconnues"]["organigramme"]["liens"][0]["texte"] == "Équipes clôturées →"  # compte inconnu : pas de zéro inventé

    # 4. la ligne sous un agent : jamais une info
    def quoi(nom):
        return next(ag["quoi"] for ag in r[nom]["organigramme"]["agents"] if ag["id"] == "coord-page")
    assert quoi("agent sans alarme") == ["Écrire le test de rendu"]
    assert quoi("agent avec info seule") == ["Écrire le test de rendu"], quoi("agent avec info seule")  # pas « Retard sur la branche de base »
    assert quoi("agent info et a voir") == ["Gros consommateur"]
    assert quoi("agent grave et info") == ["Session disparue"]
    for nom, jeu in r.items():
        assert not any("Retard sur la branche de base" in q for ag in jeu["organigramme"]["agents"] for q in ag["quoi"]), nom

    # 2. « Ce qui coince » : un cadre unique, une ligne par alarme grave, une ligne dépliable par type à voir, les infos en dernier
    reel = r["reel"]["organigramme"]
    assert reel["cadres"] == 1
    assert [(l["tag"], l["gravite"]) for l in reel["lignes"]] == [("details", "a_voir"), ("details", "a_voir"), ("article", "a_voir"), ("details", None)], reel["lignes"]
    contexte, refusee, gros, infos = reel["lignes"]
    assert contexte["type"] == "contexte_au_repos" and contexte["lignesGroupe"] == 3 and not contexte["ouvert"]
    assert contexte["mot"] == ["À voir"] and contexte["gras"] == ["Quoi faire :"] and contexte["faire"] == ["Quoi faire : faire contexte_au_repos"]  # écrit une fois
    assert contexte["texte"].count("faire contexte_au_repos") == 1
    assert "Contexte lourd au repos ×3 · coord-livraison, coord-scene, Assistant" in contexte["texte"], contexte["texte"]
    assert refusee["type"] == "action_refusee" and refusee["lignesGroupe"] == 2 and "Action refusée par le garde ×2 · Assistant" in refusee["texte"]  # le même agent une fois
    assert gros["gravite"] == "a_voir" and gros["detail"] == 1 and gros["mot"] == ["À voir"] and gros["gras"] == ["Quoi faire :"]
    assert gros["faire"][0].startswith("Quoi faire : faire gros_poste") and gros["faire"][0].endswith("Détail") and not gros["ouvert"]
    assert infos["type"] == "retard_sur_base" and infos["lignesGroupe"] == 8 and "Info ×8" in infos["texte"] and not infos["ouvert"]
    assert reel["entete"].startswith("Ce qui coince|") and "6 à voir" in reel["entete"] and "8 info" in reel["entete"]
    exa = r["exemple"]["organigramme"]["lignes"]
    graves = [l for l in exa if l["gravite"] == "grave"]
    assert graves and all(l["tag"] == "article" and l["gras"] == ["Quoi faire :"] and l["mot"] == (["À trancher"] if "ton-ambre" in l["classes"] else ["Grave"]) for l in graves)  # un problème = une ligne, jamais groupé ; une attente grave est « À trancher »
    assert [l["gravite"] for l in exa[: len(graves)]] == ["grave"] * len(graves)  # les graves d'abord
    assert all(len(l["age"]) == 1 for l in exa if l["tag"] == "article")  # l'âge à droite de la ligne 1
    # états sans alarme, inconnus : inchangés
    assert r["sans alarme"]["organigramme"]["lignes"] is None and r["sans alarme"]["organigramme"]["cadres"] == 0 and r["sans alarme"]["organigramme"]["texte"].count("Aucune alarme.") == 1
    assert r["alarmes inconnues"]["organigramme"]["lignes"] is None and "Alarmes inconnues" in r["alarmes inconnues"]["organigramme"]["texte"]
    assert [l["gravite"] for l in r["aucune alarme a voir"]["organigramme"]["lignes"]] == [None]  # que des infos : une seule ligne groupée

    # 6. les chiffres de la Consommation ne sont plus en mono (la mono ne sert qu'aux identifiants)
    assert all(vue["monoConso"] == 0 for jeu in r.values() for vue in jeu.values())


def verifier_rendu_des_vues(dossier_static):
    """Aucune vue rendue par app.js ne lève d'erreur (ReferenceError en tête), ni avec l'exemple, ni à vide, ni avec des sources en échec."""
    exemple = _exemple()
    vide = json.loads(json.dumps(exemple))
    vide.update(equipes=[], agents=[], alarmes=[], fil=[], attentes_utilisateur=[], sessions_hors_organigramme=[], integration=None)
    nul = json.loads(json.dumps(exemple))
    nul.update(equipes=None, agents=None, alarmes=None, fil=None, attentes_utilisateur=None, consommation=None, sessions_hors_organigramme=None)
    onze = _jeux_ensemble()["onze equipes"]
    jeux = {"exemple": exemple, "vide": vide, "nul": nul, "onze": onze}
    for jeu in jeux.values():
        jeu["journal_test"] = []
    jeux["nul"]["journal_test"] = None
    r = _ecrire_et_lancer(dossier_static, SONDE_VUES, jeux, dossier_static)
    erreurs = {cle: v for cle, v in r.items() if v not in ("ok", "vide")}
    assert not erreurs, erreurs
    assert len(r) == 5 * 4 * 2, len(r)


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def js():
    fichiers = sorted(STATIC.glob("*.js")) + sorted((STATIC / "vues").glob("*.js")) + [STATIC / f for f in FEUILLES]
    return {str(f.relative_to(STATIC)): f.read_text(encoding="utf-8") for f in fichiers}


def test_supervision_coince_dependances(js):
    verifier_supervision_coince(js)


def _remplace(fichier, ancien, nouveau):
    def mutation(js):
        assert ancien in js[fichier], ancien
        return {**js, fichier: js[fichier].replace(ancien, nouveau, 1)}
    return mutation


MUTATIONS = {
    # 1. identifiants
    "lienEquipe retiré de l'import": _remplace(EN, "equipeEnRetrait, lienEquipe, plusGrosPostes", "equipeEnRetrait, plusGrosPostes"),
    "jetonsOuInconnu retiré de l'import": _remplace(EN, "CONTEXTE_CHAUD, jetonsOuInconnu,", "CONTEXTE_CHAUD,"),
    "grouperAlarmes retiré de l'import": _remplace(EN, "  grouperAlarmes, resumeGroupeInfos,", "  resumeGroupeInfos,"),
    "appel d'un identifiant inconnu dans une autre vue": _remplace("vues/archives.js", "puceStatut(", "puceStatutInconnu("),
    "fonction appelée supprimée": _remplace(EN, "function ligneFaire(a) {", "function ligneFaireAutre(a) {"),
    "lienEquipe non exporté": _remplace(COM, "export const lienEquipe = ", "const lienEquipe = "),
    # 4. ligne sous l'agent
    "info sous l'agent": _remplace(EN, "const autre = alarmes.find((x) => x.gravite !== 'info');", "const autre = alarmes[0];"),
    "tâche avant l'attente": _remplace(EN, "  if (attend) {\n    return el('span', { class: 'ag-quoi ton-ambre' }", "  if (a.tache) return el('span', { class: 'ag-quoi', title: a.tache }, a.tache);\n  if (attend) {\n    return el('span', { class: 'ag-quoi ton-ambre' }"),
    # 2. alarmes
    "grouperAlarmes : plus ancien en dernier": _remplace(COM, "rang(x) - rang(y) || comparerDepuis(x, y)", "rang(x) - rang(y) || comparerDepuis(y, x)"),
    "grouperAlarmes : alarme seule groupée": _remplace(COM, "siennes.length === 1 ? seule(siennes[0])", "false ? seule(siennes[0])"),
    "grouperAlarmes : graves groupées": _remplace(COM, "...triees.filter((a) => rang(a) === GRAVITES.grave.rang && a.gravite in GRAVITES).map(seule),", "...[...new Set(triees.filter((a) => a.gravite in GRAVITES && rang(a) === 0).map((a) => a.type))].map((type) => ({ genre: 'groupe', gravite: 'grave', type, alarmes: triees.filter((a) => a.type === type && rang(a) === 0), ton: 'rouge' })),"),
    "résumé : doublons de cibles": _remplace(COM, "const cibles = [...new Set(groupe.alarmes.flatMap((a) => ((a.agents || []).length ? a.agents.map(nomAgent) : (a.equipes || []))))];", "const cibles = groupe.alarmes.flatMap((a) => ((a.agents || []).length ? a.agents.map(nomAgent) : (a.equipes || [])));"),
    "résumé : compte absent": _remplace(COM, "ligne: `${type} ×${groupe.alarmes.length}", "ligne: `${type}"),
    "groupe sans Quoi faire écrit une fois": _remplace(EN, "const faire = groupe.alarmes[0].quoi_faire;", "const faire = '';"),
    "groupe ouvert au chargement": _remplace(EN, "return el('details', { class: `al alarme-groupe groupe-probleme", "return el('details', { open: true, class: `al alarme-groupe groupe-probleme"),
    "groupe sans âge": _remplace(EN, "el('span', { class: 'al-age discret' }, ageAlarme(groupe.alarmes[0])),\n", ""),
    "cadre par alarme": _remplace(EN, "{ class: 'alarmes alarmes-cadre' }", "{ class: 'alarmes' }"),
    "cadre sans rayon 10": _remplace(CSS, ".alarmes-cadre { gap: 0; background: var(--carte); border: 1px solid var(--bord); border-radius: var(--rayon);", ".alarmes-cadre { gap: 0; background: var(--carte); border: 1px solid var(--bord); border-radius: 4px;"),
    "Quoi faire en ambre": _remplace(CSS, ".al-faire b { font-weight: 600; color: var(--texte-doux); }", ".al-faire b { font-weight: 600; color: var(--ambre); }"),
    "ligne trop haute": _remplace(CSS, "  padding: 12px 16px; border-bottom: 1px solid var(--bord-doux);\n}", "  padding: 24px 16px; border-bottom: 1px solid var(--bord-doux);\n}"),
    # 3 et 5. integration et lien des clôturées
    "integration reste en carte": _remplace(EN, "const cartes = actives ? actives.filter((q) => !retraits.includes(q)) : [];", "const cartes = actives || [];"),
    "ligne de liens oubliée": _remplace(EN, "        : retraits.length ? null : el('p', { class: 'vide-calme' }, 'Aucune équipe pour l’instant.'),\n    ligneLiens(retraits));", "        : retraits.length ? null : el('p', { class: 'vide-calme' }, 'Aucune équipe pour l’instant.'));"),
    "compte des clôturées perdu": _remplace(EN, "`${pluriel(cloturees, 'équipe clôturée', 'équipes clôturées')} →`", "'Équipes clôturées →'"),
    "pluriel des clôturées perdu": _remplace(EN, "pluriel(cloturees, 'équipe clôturée', 'équipes clôturées')", "pluriel(cloturees, 'équipe clôturée', 'équipe clôturée')"),
    "second lien au pied": _remplace(EN, "el('a', { href: '#/journal' }, 'Journal des actions'));", "el('a', { href: '#/journal' }, 'Journal des actions'), el('a', { href: '#/archives' }, 'Équipes clôturées'));"),
    "équipe spéciale vivante en retrait": _remplace(COM, "if (!siens.every((a) => a.vivant === false && !a.session_tmux)) return false;", ""),
    "équipe non spéciale en retrait": _remplace(COM, "if (!equipe.speciale || equipe.statut === 'terminee' ||", "if (equipe.statut === 'terminee' ||"),
    "alarme d'équipe ignorée pour le retrait": _remplace(COM, "return alarmesDe(alarmes, { equipe: equipe.nom }).length === 0 && siens.every((a) => alarmesDe(alarmes, { agent: a.id }).length === 0);\n}\n\nfunction formatTokens", "return siens.every((a) => alarmesDe(alarmes, { agent: a.id }).length === 0);\n}\n\nfunction formatTokens"),
    # 6. polices
    "chiffres de la conso en mono": _remplace(EN, "el('span', { class: 'poste-valeur' }, jetonsOuInconnu(p.lus_15min))", "el('span', { class: 'mono poste-valeur' }, jetonsOuInconnu(p.lus_15min))"),
    "chiffres sans tabular-nums": _remplace(CSS, ".poste-valeur { text-align: right; color: var(--secondaire); font-variant-numeric: tabular-nums; }", ".poste-valeur { text-align: right; color: var(--secondaire); }"),
    # 7. en-tête
    "effectifs toujours visibles": _remplace(CSS, "  .entete .effectifs-texte { display: none; }", "  .entete .effectifs-texte { display: inline; }"),
    "effectifs masqués au bureau": _remplace(CSS, "/* entre 760 et 1 240 px", ".effectifs-texte { display: none; }\n/* entre 760 et 1 240 px"),
    "seuil de l'en-tête à 1 000": _remplace(CSS, "@media (max-width: 1240px) {\n  .entete .effectifs-texte", "@media (max-width: 1000px) {\n  .entete .effectifs-texte"),
    "seuil de l'en-tête à 1 300": _remplace(CSS, "@media (max-width: 1240px) {\n  .entete .effectifs-texte", "@media (max-width: 1300px) {\n  .entete .effectifs-texte"),
    "onglets qui se coupent": _remplace(CSS, ".nav a, .pilule { white-space: nowrap; }", ".nav a, .pilule { white-space: normal; }"),
    "effectifs sans leur span": _remplace(COM, "el('span', { class: 'effectifs-texte' }, phrase)", "phrase"),
}


@pytest.mark.parametrize("nom", MUTATIONS)
def test_mutation_detectee(nom, js):
    mutee = MUTATIONS[nom](js)  # hors du raises : la mutation doit s'appliquer, sinon le test serait faux
    with pytest.raises(AssertionError):
        verifier_supervision_coince(mutee)


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node n'est pas installé : le rendu n'est pas exécuté")


@pytest.fixture
def copie_static(tmp_path):
    cible = tmp_path / "static"
    shutil.copytree(STATIC, cible, ignore=shutil.ignore_patterns("__pycache__"))
    return cible


@needs_node
def test_fonctions_executees(copie_static):
    verifier_fonctions(copie_static)


@needs_node
def test_rendu_ensemble_execute(copie_static):
    verifier_rendu_ensemble(copie_static)


@needs_node
def test_rendu_des_vues_execute(copie_static):
    verifier_rendu_des_vues(copie_static)


# mutations qui ne se voient qu'à l'exécution : (fichier, ancien, nouveau, vérification qui doit échouer)
MUTATIONS_EXECUTEES = {
    # le bloquant 1 : l'import retiré fait lever ReferenceError à l'exécution
    "lienEquipe retiré (rendu des onglets)": (EN, "equipeEnRetrait, lienEquipe, plusGrosPostes", "equipeEnRetrait, plusGrosPostes", verifier_rendu_ensemble),
    "lienEquipe retiré (toutes les vues)": (EN, "equipeEnRetrait, lienEquipe, plusGrosPostes", "equipeEnRetrait, plusGrosPostes", verifier_rendu_des_vues),
    "identifiant retiré de l'import de la fiche équipe": ("vues/equipe.js", "puceStatut,", "", verifier_rendu_des_vues),
    "identifiant inconnu dans l'archive": ("vues/archives.js", "puceStatut('terminee')", "puceStatutInconnu('terminee')", verifier_rendu_des_vues),
    "identifiant inconnu dans le journal": ("vues/journal.js", "mesurerLargeur();\n    return;", "mesurerLargeurInconnue();\n    return;", verifier_rendu_des_vues),
    "info sous l'agent": (EN, "const autre = alarmes.find((x) => x.gravite !== 'info');", "const autre = alarmes[0];", verifier_rendu_ensemble),
    "ordre des alarmes : plus ancien en dernier": (COM, "rang(x) - rang(y) || comparerDepuis(x, y)", "rang(x) - rang(y) || comparerDepuis(y, x)", verifier_fonctions),
    "alarme seule groupée": (COM, "siennes.length === 1 ? seule(siennes[0])", "false ? seule(siennes[0])", verifier_fonctions),
    "alarme seule rendue en groupe": (COM, "siennes.length === 1 ? seule(siennes[0])", "siennes.length === 0 ? seule(siennes[0])", verifier_fonctions),
    "graves groupées": (COM, "...triees.filter((a) => rang(a) === GRAVITES.grave.rang && a.gravite in GRAVITES).map(seule),", "...triees.filter((a) => rang(a) === GRAVITES.grave.rang && a.gravite in GRAVITES).slice(0, 1).map(seule),", verifier_fonctions),
    "à voir groupés par agent": (COM, "const siennes = aVoir.filter((a) => a.type === type);", "const siennes = aVoir.filter((a) => a.type === type && a.agents.length < 2);", verifier_fonctions),
    "gravité inconnue perdue": (COM, "    ...triees.filter((a) => !['grave', 'a_voir', 'info'].includes(a.gravite)).map(seule),\n", "", verifier_fonctions),
    "infos devant les gravités inconnues": (COM, "    ...triees.filter((a) => !['grave', 'a_voir', 'info'].includes(a.gravite)).map(seule),\n    ...grouperInfos", "    ...grouperInfos", verifier_fonctions),
    "cibles en double": (COM, "const cibles = [...new Set(groupe.alarmes.flatMap((a) => ((a.agents || []).length ? a.agents.map(nomAgent) : (a.equipes || []))))];", "const cibles = groupe.alarmes.flatMap((a) => ((a.agents || []).length ? a.agents.map(nomAgent) : (a.equipes || [])));", verifier_fonctions),
    "équipes avant agents": (COM, "((a.agents || []).length ? a.agents.map(nomAgent) : (a.equipes || []))))];", "((a.equipes || []).length ? a.equipes : (a.agents || []).map(nomAgent))))];", verifier_fonctions),
    "agents bruts": (COM, "a.agents.map(nomAgent) : (a.equipes || []))))];", "a.agents : (a.equipes || []))))];", verifier_fonctions),
    "infos avant les graves": (COM, "  return [\n    ...triees.filter((a) => rang(a)", "  return [\n    ...grouperInfos(triees).map((g) => ({ genre: 'groupe', gravite: 'info', type: g.type, alarmes: g.alarmes, ton: g.ton })),\n    ...triees.filter((a) => rang(a)", verifier_fonctions),
    "séparateur orphelin": (COM, "${cibles.length ? ` · ${cibles.join(', ')}` : ''}", " · ${cibles.join(', ')}", verifier_fonctions),
    "ligne sans le compte": (COM, "ligne: `${type} ×${groupe.alarmes.length}", "ligne: `${type}", verifier_fonctions),
    "entrée modifiée par le tri": (COM, "const triees = [...alarmes].sort(", "const triees = alarmes.sort(", verifier_fonctions),
    "retrait : tout est en retrait": (COM, "if (!equipe.speciale || equipe.statut === 'terminee' ||", "if (equipe.statut === 'terminee' ||", verifier_fonctions),
    "retrait : agent vivant ignoré": (COM, "if (!siens.every((a) => a.vivant === false && !a.session_tmux)) return false;", "", verifier_fonctions),
    "retrait : vivant inconnu accepté": (COM, "a.vivant === false && !a.session_tmux", "!a.vivant && !a.session_tmux", verifier_fonctions),
    "retrait : session restante ignorée": (COM, "a.vivant === false && !a.session_tmux", "a.vivant === false", verifier_fonctions),
    "retrait : alarme d'équipe ignorée": (COM, "return alarmesDe(alarmes, { equipe: equipe.nom }).length === 0 && siens.every((a) => alarmesDe(alarmes, { agent: a.id }).length === 0);\n}\n\nfunction formatTokens", "return siens.every((a) => alarmesDe(alarmes, { agent: a.id }).length === 0);\n}\n\nfunction formatTokens", verifier_fonctions),
    "retrait : alarme d'agent ignorée": (COM, " && siens.every((a) => alarmesDe(alarmes, { agent: a.id }).length === 0);\n}\n\nfunction formatTokens", ";\n}\n\nfunction formatTokens", verifier_fonctions),
    "retrait : agents inconnus acceptés": (COM, "equipe.statut === 'terminee' || !Array.isArray(agents) || !Array.isArray(alarmes)) return false;\n  const siens = agents.filter((a) => a.equipe === equipe.nom);\n  if (!siens.every", "equipe.statut === 'terminee' || !Array.isArray(alarmes)) return false;\n  const siens = (agents || []).filter((a) => a.equipe === equipe.nom);\n  if (!siens.every", verifier_fonctions),
    "retrait : alarmes inconnues acceptées": (COM, "equipe.statut === 'terminee' || !Array.isArray(agents) || !Array.isArray(alarmes)) return false;\n  const siens = agents.filter((a) => a.equipe === equipe.nom);\n  if (!siens.every", "equipe.statut === 'terminee' || !Array.isArray(agents)) return false;\n  const siens = agents.filter((a) => a.equipe === equipe.nom);\n  if (!siens.every", verifier_fonctions),
    "integration reste en carte": (EN, "const cartes = actives ? actives.filter((q) => !retraits.includes(q)) : [];", "const cartes = actives || [];", verifier_rendu_ensemble),
    "ligne de liens oubliée": (EN, "        : retraits.length ? null : el('p', { class: 'vide-calme' }, 'Aucune équipe pour l’instant.'),\n    ligneLiens(retraits));", "        : retraits.length ? null : el('p', { class: 'vide-calme' }, 'Aucune équipe pour l’instant.'));", verifier_rendu_ensemble),
    "compte des clôturées perdu": (EN, "`${pluriel(cloturees, 'équipe clôturée', 'équipes clôturées')} →`", "'Équipes clôturées →'", verifier_rendu_ensemble),
    "compte des clôturées inconnu dit zéro": (EN, "const cloturees = Array.isArray(etat.equipes) ? etat.equipes.filter((q) => q.statut === 'terminee').length : null;", "const cloturees = Array.isArray(etat.equipes) ? etat.equipes.filter((q) => q.statut === 'terminee').length : 0;", verifier_rendu_ensemble),
    "équipes spéciales sans nom dans la ligne": (EN, "lienEquipe(q.nom), ' (spéciale, sans session)'", "q.nom, ' (spéciale, sans session)'", verifier_rendu_ensemble),
    "second lien au pied": (EN, "el('a', { href: '#/journal' }, 'Journal des actions'));", "el('a', { href: '#/journal' }, 'Journal des actions'), el('a', { href: '#/archives' }, 'Équipes clôturées'));", verifier_rendu_ensemble),
    "lignes d'alarme hors du cadre unique": (EN, "{ class: 'alarmes alarmes-cadre' }", "{ class: 'alarmes' }", verifier_rendu_ensemble),
    "tout en lignes seules": (EN, "const ligneAlarme = (item) => (item.genre === 'seule' ? ligneProbleme(item.alarmes[0])", "const ligneAlarme = (item) => (item.genre !== 'groupe' || true ? ligneProbleme(item.alarmes[0])", verifier_rendu_ensemble),
    "infos en lignes seules": (EN, "item.gravite === 'info' ? groupeInfos(item) : groupeProblemes(item)", "groupeProblemes(item)", verifier_rendu_ensemble),
    "Quoi faire non gras": (EN, "el('b', {}, 'Quoi faire :'), ` ${a.quoi_faire} `", "'Quoi faire :', ` ${a.quoi_faire} `", verifier_rendu_ensemble),
    "Quoi faire répété dans le groupe": (EN, "const faire = groupe.alarmes[0].quoi_faire;", "const faire = '';", verifier_rendu_ensemble),
    "groupe ouvert": (EN, "return el('details', { class: `al alarme-groupe groupe-probleme", "return el('details', { open: true, class: `al alarme-groupe groupe-probleme", verifier_rendu_ensemble),
    "groupe sans le détail des alarmes": (EN, "    el('ul', { class: 'groupe-liste' }, groupe.alarmes.map((a) => el('li', { class: 'groupe-alarme' },\n      el('div', { class: 'alarme-tete' }, ciblesAlarme(a)", "    el('ul', { class: 'groupe-liste' }, [].map((a) => el('li', { class: 'groupe-alarme' },\n      el('div', { class: 'alarme-tete' }, ciblesAlarme(a)", verifier_rendu_ensemble),
    "alarme grave sans âge": (EN, "    el('span', { class: 'al-age discret' }, ageAlarme(a)),\n    ligneFaire(a));", "    null,\n    ligneFaire(a));", verifier_rendu_ensemble),
    "chiffres de la conso en mono": (EN, "el('span', { class: 'poste-valeur' }, jetonsOuInconnu(p.lus_15min))", "el('span', { class: 'mono poste-valeur' }, jetonsOuInconnu(p.lus_15min))", verifier_rendu_ensemble),
}


@needs_node
@pytest.mark.parametrize("nom", MUTATIONS_EXECUTEES)
def test_mutation_executee_detectee(nom, copie_static):
    fichier, ancien, nouveau, verification = MUTATIONS_EXECUTEES[nom]
    cible = copie_static / fichier
    texte = cible.read_text(encoding="utf-8")
    assert ancien in texte, ancien  # la mutation doit s'appliquer
    cible.write_text(texte.replace(ancien, nouveau, 1), encoding="utf-8")
    with pytest.raises((AssertionError, KeyError, StopIteration, ValueError)):
        verification(copie_static)


def test_couverture_des_verifications():
    toutes = {n for n, v in globals().items() if n.startswith("verifier_") and callable(v)}
    assert toutes == {"verifier_supervision_coince", "verifier_fonctions", "verifier_rendu_ensemble", "verifier_rendu_des_vues"} and MUTATIONS and MUTATIONS_EXECUTEES, sorted(toutes)
    assert {v[3] for v in MUTATIONS_EXECUTEES.values()} == {verifier_fonctions, verifier_rendu_ensemble, verifier_rendu_des_vues}  # chacune a ses mutations
