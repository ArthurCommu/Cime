"""Le récap du matin : en tête de « Depuis ta dernière visite », ce que l'Assistant a décidé à la place de l'utilisateur (champ `fusions_auto.decisions`).

Même convention que test_mode_autonome.py : l'analyse de texte (`verifier_texte`, ses MUTATIONS) puis node pour la lecture (`verifier_lecture`) et le rendu de la
vue Supervision avec un DOM minimal (`verifier_rendu`), chacun avec ses mutations exécutées. La page lit `decisions`, elle ne le calcule pas.
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import test_page_garde_fous as garde_fous
from test_page_garde_fous import PHRASES_MODE_AUTONOME, chaines_interdites

PAGE = Path(__file__).resolve().parents[2] / "src" / "cime" / "page"
STATIC = PAGE / "static"
AU, ENS, CSS = "autonome.js", "vues/ensemble.js", "style.css"
EXE = "exemple-etat.json"
EXEMPLE_ETAT = Path(__file__).resolve().parent / "fixtures" / EXE
MO, COM = "vues/mode-autonome.js", "commun.js"  # la Scène et la lecture partagée de la dernière visite
DEC = "vues/decisions.js"  # la liste des décisions, rendue une seule fois pour la Supervision et la Scène
FICHIERS = [AU, ENS, CSS, MO, COM, DEC]
PHRASE_TABLE = "{ genre: 'fusion', un: 'fusion', plusieurs: 'fusions', verbe: 'fusionnée' }"


def _corps(texte, debut, fin):
    i = texte.find(debut)
    assert i >= 0, debut
    j = texte.find(fin, i + len(debut))
    assert j >= 0, fin
    return texte[i:j]


def _ordre(texte, *morceaux):
    positions = []
    for m in morceaux:
        assert m in texte, m
        positions.append(texte.index(m))
    assert positions == sorted(positions), morceaux


# ---------------------------------------------------------------------------
# Analyse de texte
# ---------------------------------------------------------------------------
def verifier_texte(js):
    au, ens, css, exe, mo, com, dec = (js[n] for n in (AU, ENS, CSS, EXE, MO, COM, DEC))

    # 1-2. la table : une ligne par genre, les mots du récap et pas d'autre
    table = _corps(au, "export const GENRES_DECISION = [", "\n];\n")
    _ordre(table, "genre: 'fusion'", "genre: 'chantier'", "genre: 'contrat'", "genre: 'autorisation'")
    for ligne in (PHRASE_TABLE,
                  "{ genre: 'chantier', un: 'chantier lancé', plusieurs: 'chantiers lancés', verbe: 'lancé' }",
                  "{ genre: 'contrat', un: 'contrat modifié', plusieurs: 'contrats modifiés', verbe: 'modifié' }",
                  "{ genre: 'autorisation', un: 'autorisation accordée', plusieurs: 'autorisations accordées', verbe: 'accordée' }"):
        assert ligne in table, ligne
    assert table.count("genre:") == 4
    assert "export const PHRASE_RECAP = 'L’Assistant a décidé à ta place';" in au and "export const LIBELLE_DECISIONS = 'Voir les décisions';" in au
    assert "export const MAX_DECISIONS = 50;" in au and "export const DECISIONS_VISIBLES = 10;" in au
    assert "decisions: actif ? lireDecisions(lecture.decisions) : []," in au and "if (!Array.isArray(v)) return [];" in au
    assert "portee: actif ? nombre(lecture.portee) : null," in au and "chantiers_max: actif ? nombre(lecture.chantiers_max) : null," in au
    assert "(memorisee ? decisions.filter((d) => Date.parse(d.horodatage) > visite) : decisions)" in au

    # 3. le récap : première ligne, hors des 5 lignes, bleu (jamais rouge ni ambre)
    assert "return recap ? [recap, ...lignes.slice(0, 5)] : lignes.slice(0, 5);" in ens
    ligne = _corps(ens, "function ligneRecap(visite) {", "\n}\n")
    assert "decisionsAVoir(lireMode(etat).decisions, visite.instant, visite.memorisee)" in ligne
    assert "if (!decisions.length) return null;" in ligne
    assert "class: 'nouveaute-recap'" in ligne and "rouge" not in ligne and "ambre" not in ligne
    assert "PHRASE_RECAP" in ligne and "${resumeDecisions(decisions)}" in ligne and "comptesDecisions" not in ligne  # le même texte que la Scène
    regle = re.search(r"\.nouveautes-liste \.nouveaute-recap \{([^}]*)\}", css)
    assert regle and "color: var(--bleu);" in regle.group(1) and "flex: 1 0 100%" in regle.group(1)
    assert "rouge" not in regle.group(1) and "ambre" not in regle.group(1)
    assert ".nouveautes-liste .nouveaute-recap + li::before { content: none; }" in css
    comptes = _corps(au, "export function comptesDecisions(decisions) {", "\n}\n")
    assert ".filter((c) => c.n > 0)" in comptes  # un genre à 0 est omis
    assert "GENRES_DECISION.map((g) => g.genre)" in comptes  # dans l'ordre de la table

    # 4. le détail : replié, chevron des réserves, 10 lignes puis « … et n autres », cle en mono qui ne se coupe qu'à la ligne
    assert "detailDecisions(decisions, decisionsVue, LIBELLE_DECISIONS, mesurerLargeur)" in ligne  # le détail vit dans decisions.js, replié d'office
    assert "const decisionsVue = etatDecisions();" in ens and "let decisionsOuvert" not in ens and "decisionsToutes" not in ens
    assert "import { detailDecisions, etatDecisions } from './decisions.js';" in ens
    assert "function listeDecisions" not in ens and "listeDecisions" not in ens  # une seule copie de la liste, dans le module partagé
    liste = _corps(dec, "export function listeDecisions(decisions, vue, apres = () => {}) {", "\n}\n")
    assert "const triees = [...decisions].sort((a, b) => Date.parse(b.horodatage) - Date.parse(a.horodatage));" in liste  # la plus récente d'abord, pour les deux vues
    assert "montrer(triees.slice(0, DECISIONS_VISIBLES));" in liste and "`… et ${reste} ${reste === 1 ? 'autre' : 'autres'}`" in liste
    assert "vue.toutes = true; montrer(triees); apres();" in liste and "if (reste <= 0 || vue.toutes) {" in liste
    ligne_dec = _corps(dec, "function ligneDecision(d) {", "\n}\n")
    assert "heureCourte(d.horodatage)" in ligne_dec and "verbeDecision(d.genre)" in ligne_dec and "mono(d.cle)" in ligne_dec
    assert "title: d.message === null ? null : `message n° ${d.message}`" in ligne_dec and "href" not in ligne_dec  # le Fil n'ouvre pas un message : pas de lien
    detail = _corps(dec, "export function detailDecisions(decisions, vue, libelle, apres = () => {}) {", "\n}\n")
    assert "el('details', { class: 'decisions', open: vue.ouvert }, el('summary', {}, libelle), listeDecisions(decisions, vue, apres))" in detail
    assert "detail.addEventListener('toggle', () => { vue.ouvert = detail.open; apres(); });" in detail
    assert "export const etatDecisions = () => ({ ouvert: false, toutes: false });" in dec  # un jeu d'états par appel : une vue ne partage rien
    assert "localStorage" not in dec and "setItem" not in dec  # les replis ne vont jamais dans le stockage
    assert ".decisions > summary::before {" in css and ".decisions[open] > summary::before { top: -3px; transform: rotate(45deg); }" in css
    cle = re.search(r"\.decision-cle \{([^}]*)\}", css).group(1)
    assert "overflow-wrap: break-word" in cle and "anywhere" not in cle and "word-break" not in cle  # à la ligne, jamais au milieu d'un sha qui tient

    # 5. ouverture d'office
    assert "l.classList.contains('rouge') || l.classList.contains('nouveaute-recap')" in ens

    # 2. la Scène : une ligne sous le paragraphe, avant « Voir la liste » ; actif et suspendu seulement ; même visite, même texte
    enc = _corps(mo, "export function encadreMode(etat, redessiner) {", "\n}\n")
    assert "      ligneRecapScene(etat),\n      detailsReserves(etat, mode, (g, c) => ligneReserves" in enc  # actif
    assert "    ligneRecapScene(etat),\n    detailsReserves(etat, mode, (g, c) => (c === null" in enc  # suspendu
    assert "ligneRecapScene" not in _corps(enc, "if (mode.etat === 'inactif') {", "if (mode.etat === 'actif') {")  # inactif : jamais
    scene = _corps(mo, "function ligneRecapScene(etat) {", "\n}\n")
    assert "const visite = derniereVisite(etat);" in scene
    assert "decisionsAVoir(lireMode(etat).decisions, visite.instant, visite.memorisee)" in scene
    assert "if (!decisions.length) return null;" in scene
    assert "return [el('p', { class: 'recap-scene' }, el('b', {}, PHRASE_RECAP), ` : ${resumeDecisions(decisions)}`),\n    detailDecisions(decisions, decisionsScene, LIBELLE_DETAIL_RECAP)];" in scene
    assert "href" not in scene and "#/" not in scene  # le résumé déplie la liste, sans changer de page
    assert "rouge" not in scene and "ambre" not in scene
    # le détail de la Scène a son propre jeu d'états (replié d'office), le libellé est une constante
    assert "const decisionsScene = etatDecisions();" in mo and "decisionsVue" not in mo and "decisionsScene" not in ens
    assert "export const LIBELLE_DETAIL_RECAP = 'Voir le détail';" in au and "LIBELLE_DETAIL_RECAP" in mo
    assert "import { detailDecisions, etatDecisions } from './decisions.js';" in mo
    assert ".recap-scene, .recap-scene b { color: var(--bleu); font-size: 13px; }" in css  # bleu, 13 px ; la règle du gras suit celle de `.etat-auto b`
    assert css.index(".recap-scene, .recap-scene b") > css.index(".etat-auto b { color: var(--texte)")
    assert "resumeDecisions" in mo and "PHRASE_RECAP" in mo and "derniereVisite" in mo
    assert au.count("'Voir le détail'") == 1 and "'Voir le détail'" not in mo + ens + dec  # un seul texte, dans la table des libellés

    # 8. la visite : une seule lecture, dans commun.js, en lecture seule ; la Scène ne la mémorise jamais
    lecture = _corps(com, "export function derniereVisite(etat) {", "\n}\n")
    assert "localStorage.getItem(cleVisite(etat))" in lecture and "setItem" not in lecture
    assert "export const cleVisite = (etat) => `cime:derniere-visite:${etat.projet ? etat.projet.nom : 'projet'}`;" in com
    assert "function lireDerniereVisite" not in ens and "const visite = derniereVisite(etat);" in ens
    assert "localStorage.setItem(cleVisite(etat), String(Math.floor(ctx.horloge.maintenant())))" in ens  # la Supervision seule écrit
    assert "addEventListener('pagehide', memoriserVisite)" in ens
    assert "setItem" not in mo and "memoriserVisite" not in mo and "localStorage" not in mo and "pagehide" not in mo

    # 10. l'exemple est inactif
    f = json.loads(exe)["fusions_auto"]
    assert f["decisions"] == [] and f["portee"] is None and f["chantiers_24h"] == 0 and f["chantiers_max"] is None


@pytest.fixture(scope="module")
def js():
    return {**{n: (STATIC / n).read_text(encoding="utf-8") for n in FICHIERS}, EXE: EXEMPLE_ETAT.read_text(encoding="utf-8")}


def test_recap_texte(js):
    verifier_texte(js)


def _remplace(fichier, ancien, nouveau):
    def mutation(js):
        assert ancien in js[fichier], ancien
        return {**js, fichier: js[fichier].replace(ancien, nouveau, 1)}
    return mutation


MUTATIONS = {
    "récap compté dans la limite de 5": _remplace(ENS, "return recap ? [recap, ...lignes.slice(0, 5)] : lignes.slice(0, 5);", "return (recap ? [recap, ...lignes] : lignes).slice(0, 5);"),
    "récap en dernière position": _remplace(ENS, "[recap, ...lignes.slice(0, 5)]", "[...lignes.slice(0, 5), recap]"),
    "récap en rouge": _remplace(ENS, "class: 'nouveaute-recap'", "class: 'nouveaute-recap rouge'"),
    "récap en ambre": _remplace(CSS, ".nouveautes-liste .nouveaute-recap { flex: 1 0 100%; color: var(--bleu); }", ".nouveautes-liste .nouveaute-recap { flex: 1 0 100%; color: var(--ambre); }"),
    "toutes les décisions au lieu de celles d'après la visite": _remplace(AU, "(memorisee ? decisions.filter((d) => Date.parse(d.horodatage) > visite) : decisions)", "decisions"),
    "genre à 0 affiché": _remplace(AU, ".filter((c) => c.n > 0)", ""),
    "ordre inversé": _remplace(DEC, "Date.parse(b.horodatage) - Date.parse(a.horodatage)", "Date.parse(a.horodatage) - Date.parse(b.horodatage)"),
    "plus de dix lignes sans « … et n autres »": _remplace(DEC, "montrer(triees.slice(0, DECISIONS_VISIBLES));", "montrer(triees);"),
    "détail ouvert d'office": _remplace(ENS, "const decisionsVue = etatDecisions();", "const decisionsVue = { ouvert: true, toutes: false };"),
    "un lien vers le Fil": _remplace(DEC, "  return el('li', { title:", "  return el('li', { href: '#/fil', title:"),
    "chevron absent": _remplace(CSS, ".decisions > summary::before {", ".decisions > summary::marker {"),
    "liste déplie aussi la Supervision (un seul jeu d'états)": _remplace(MO, "const decisionsScene = etatDecisions();", "const decisionsScene = etatDecisions(); const decisionsVue = decisionsScene;"),
    "bloc fermé malgré les décisions": _remplace(ENS, "l.classList.contains('rouge') || l.classList.contains('nouveaute-recap')", "l.classList.contains('rouge')"),
    "sha coupé n'importe où": _remplace(CSS, "overflow-wrap: break-word", "overflow-wrap: anywhere"),
    "mot ajouté à la table": _remplace(AU, "verbe: 'accordée' }", "verbe: 'accordée' },\n  { genre: 'pause', un: 'pause', plusieurs: 'pauses', verbe: 'posée' }"),
    "exemple avec des décisions": lambda js: {**js, EXE: js[EXE].replace('"decisions": []', '"decisions": [{}]')},
    # la Scène (p9-t4)
    "Scène : ligne absente en actif": _remplace(MO, "      ligneRecapScene(etat),\n      detailsReserves(etat, mode, (g, c) => ligneReserves", "      detailsReserves(etat, mode, (g, c) => ligneReserves"),
    "Scène : ligne présente en inactif": _remplace(MO, "      el('p', {}, phraseInactif(connue)),", "      el('p', {}, phraseInactif(connue)), ligneRecapScene(etat),"),
    "Scène : ligne rouge": _remplace(MO, "el('p', { class: 'recap-scene' }", "el('p', { class: 'recap-scene rouge' }"),
    "Scène : lien vers la Supervision conservé": _remplace(MO, "detailDecisions(decisions, decisionsScene, LIBELLE_DETAIL_RECAP)];", "detailDecisions(decisions, decisionsScene, LIBELLE_DETAIL_RECAP), el('a', { href: '#/supervision' }, 'Voir le détail')];"),
    "Scène : liste absente": _remplace(MO, "),\n    detailDecisions(decisions, decisionsScene, LIBELLE_DETAIL_RECAP)];", ")];"),
    "Scène : liste non filtrée": _remplace(MO, "detailDecisions(decisions, decisionsScene, LIBELLE_DETAIL_RECAP)];", "detailDecisions(lireMode(etat).decisions, decisionsScene, LIBELLE_DETAIL_RECAP)];"),
    "Scène : dépliée d'office": _remplace(MO, "const decisionsScene = etatDecisions();", "const decisionsScene = { ouvert: true, toutes: false };"),
    "Scène : bleu devenu ambre": _remplace(CSS, ".recap-scene, .recap-scene b { color: var(--bleu);", ".recap-scene, .recap-scene b { color: var(--ambre);"),
    "Scène : 14 px": _remplace(CSS, ".recap-scene, .recap-scene b { color: var(--bleu); font-size: 13px; }", ".recap-scene, .recap-scene b { color: var(--bleu); font-size: 14px; }"),
    "Scène : second calcul du texte": _remplace(MO, "${resumeDecisions(decisions)}`),", "${decisions.length} décisions`),"),
    "Scène : filtre « après la visite » oublié": _remplace(MO, "decisionsAVoir(lireMode(etat).decisions, visite.instant, visite.memorisee)", "lireMode(etat).decisions"),
    "Scène : la visite mémorisée par la Scène": _remplace(MO, "const visite = derniereVisite(etat);", "const visite = derniereVisite(etat);\n  localStorage.setItem('cime:derniere-visite:projet', '1');"),
    "la lecture partagée écrit la visite": _remplace(COM, "const valeur = Number(localStorage.getItem(cleVisite(etat)));", "localStorage.setItem(cleVisite(etat), '1');\n    const valeur = Number(localStorage.getItem(cleVisite(etat)));"),
    "la Supervision garde son propre lecteur de visite": _remplace(ENS, "const visite = derniereVisite(etat);", "const visite = lireDerniereVisite(etat);"),
}


@pytest.mark.parametrize("nom", MUTATIONS)
def test_mutation_detectee(nom, js):
    with pytest.raises(AssertionError):
        verifier_texte(MUTATIONS[nom](js))


# ---------------------------------------------------------------------------
# Les garde-fous de vocabulaire : des phrases entières et étroites, rien d'autre
# ---------------------------------------------------------------------------
def _sources_page():
    return {str(p.relative_to(PAGE)): p.read_text(encoding="utf-8") for p in [PAGE / "index.html", *STATIC.rglob("*")] if p.suffix in {".html", ".js", ".css"}}


def test_garde_fous_phrases_du_recap():
    ajoutees = [p for p in PHRASES_MODE_AUTONOME if "genre:" in p]
    assert ajoutees == [PHRASE_TABLE]  # exactement la phrase nécessaire, entière
    sources = _sources_page()
    assert {nom: chaines_interdites(t) for nom, t in sources.items() if chaines_interdites(t)} == {}
    # chacune est nécessaire : sans elle, la page ne passe plus le garde-fou
    for phrase, fichier in ((PHRASE_TABLE, "static/autonome.js"),):
        assert phrase in sources[fichier], phrase
        garde_fous_phrases = tuple(x for x in PHRASES_MODE_AUTONOME if x != phrase)
        garde_fous.PHRASES_MODE_AUTONOME = garde_fous_phrases
        try:
            assert chaines_interdites(sources[fichier]) == ["fusion"], phrase
        finally:
            garde_fous.PHRASES_MODE_AUTONOME = PHRASES_MODE_AUTONOME
    # aucun mot nu : « fusion » seul reste interdit, y compris dans la phrase du récap
    assert chaines_interdites("L’Assistant a décidé à ta place : 3 fusions") == ["fusion"]
    for phrase in (PHRASE_TABLE,):
        assert chaines_interdites(phrase) == [] and chaines_interdites(phrase + " fusion") == ["fusion"]


def test_une_phrase_trop_large_serait_detectee(monkeypatch):
    # mutation : « fusion » nu ajouté aux phrases permises → une fusion écrite à l'écran passerait
    assert chaines_interdites("3 fusions") == ["fusion"]
    monkeypatch.setattr(garde_fous, "PHRASES_MODE_AUTONOME", (*PHRASES_MODE_AUTONOME, "fusion"))
    assert chaines_interdites("3 fusions") == []  # la mutation est bien trop large…
    sources = _sources_page()
    # … et le test des phrases ci-dessus l'attrape : une phrase sans « genre: » ni « : » ne peut pas être un mot nu
    assert [p for p in garde_fous.PHRASES_MODE_AUTONOME if re.fullmatch(r"fusions?|fusionn\w*", p)] == ["fusion"]
    assert sources


# ---------------------------------------------------------------------------
# node : la lecture, puis le rendu de la vue Supervision
# ---------------------------------------------------------------------------
DOM = r"""
import { readFileSync } from 'node:fs';
class Node {}
class Txt extends Node { constructor(t) { super(); this.data = t; } }
class Elt extends Node {
  constructor(tag) { super(); this.tag = tag; this.attrs = {}; this.children = []; this.dataset = {}; this.style = {}; this.ecouteurs = {};
    this.classList = { contains: (c) => this.classes.includes(c), toggle() {}, add() {}, remove() {} }; }
  setAttribute(k, v) { this.attrs[k] = v; }
  getAttribute(k) { return this.attrs[k] ?? null; }
  addEventListener(t, f) { (this.ecouteurs[t] ||= []).push(f); }
  removeEventListener() {}
  append(...n) { this.children.push(...n); }
  prepend(...n) { this.children.unshift(...n); }
  querySelectorAll() { return []; }
  querySelector() { return null; }
  remove() {}
  focus() {}
  replaceChildren(...n) { this.children = n; }
  set textContent(v) { this.children = [new Txt(String(v))]; }
  set innerHTML(v) { this.content = { firstElementChild: new Elt('svg') }; }
  get classes() { return (this.attrs.class || '').split(/\s+/).filter(Boolean); }
}
globalThis.Node = Node;
globalThis.document = { createElement: (t) => new Elt(t), createTextNode: (t) => new Txt(t), documentElement: new Elt('html'), body: new Elt('body'),
  querySelector: () => null, querySelectorAll: () => [], addEventListener() {}, removeEventListener() {}, visibilityState: 'hidden', title: '' };
globalThis.window = globalThis;
globalThis.addEventListener = () => {};
globalThis.matchMedia = () => ({ matches: false, addEventListener() {} });
let visiteMemorisee = null;
globalThis.localStorage = { getItem: () => visiteMemorisee, setItem() {} };
globalThis.ResizeObserver = class { observe() {} disconnect() {} };
globalThis.requestAnimationFrame = (f) => f();
globalThis.history = { replaceState() {} };
globalThis.location = { hash: '' };
const texte = (n) => (n instanceof Txt ? n.data : (n.children || []).map(texte).join(''));
const sous = (n) => (n instanceof Elt ? [n, ...n.children.flatMap(sous)] : []);
const a = (n, c) => sous(n).filter((m) => m.classes.includes(c));
const sortie = (objet) => process.stdout.write(JSON.stringify(objet) + '\n', () => process.exit(0));
"""

SONDE_LECTURE = DOM + r"""
const racine = process.argv[2];
const au = await import(`${racine}/autonome.js`);
const exemple = JSON.parse(readFileSync(process.argv[3], 'utf8'));
const d = (genre, cle, h) => ({ genre, cle, horodatage: h, message: 7 });
const bonnes = [d('fusion', 'aaaaaaa', '2026-10-07T12:50:00.000Z'), d('chantier', 'page:x', '2026-10-07T12:40:00.000Z')];
const lire = (f) => au.lireMode({ fusions_auto: f });
const actif = (decisions, plus = {}) => lire({ active: true, suspendue: false, decisions, ...plus });
sortie({
  absent: au.lireMode({}).decisions, nul: au.lireMode(null).decisions, vieilHote: lire({ active: true }).decisions,
  inactif: lire({ active: false, decisions: bonnes }).decisions,
  pasUneListe: [actif('x').decisions, actif({}).decisions, actif(null).decisions, actif(3).decisions],
  bonnes: actif(bonnes).decisions,
  malFormees: actif([null, 'x', 3, {}, { genre: 'fusion' }, { genre: 'fusion', cle: 'c' }, { genre: 'fusion', cle: 'c', horodatage: 'pas une date' },
    { genre: '', cle: 'c', horodatage: '2026-10-07T12:00:00.000Z' }, { genre: 'fusion', cle: '', horodatage: '2026-10-07T12:00:00.000Z' },
    { genre: 'fusion', cle: 'c', horodatage: 12 }, ...bonnes]).decisions.map((x) => x.cle),
  inconnu: actif([d('merveille', 'zz', '2026-10-07T12:00:00.000Z')]).decisions,
  sansMessage: actif([{ genre: 'fusion', cle: 'c', horodatage: '2026-10-07T12:00:00.000Z' }, { genre: 'fusion', cle: 'c', horodatage: '2026-10-07T12:00:00.000Z', message: 'x' }]).decisions.map((x) => x.message),
  cinquantaine: actif(Array.from({ length: 60 }, (_, i) => d('fusion', `c${i}`, '2026-10-07T12:00:00.000Z'))).decisions.length,
  champs: [actif([], { portee: 2, chantiers_24h: 3, chantiers_max: 5 }), lire({ active: false, portee: 2, chantiers_24h: 3, chantiers_max: 5 }), lire({ active: true }),
    actif([], { portee: 'x', chantiers_24h: -1, chantiers_max: null })].map((m) => [m.portee, m.chantiers_24h, m.chantiers_max]),
  exemple: au.lireMode(exemple).decisions,
  table: au.GENRES_DECISION,
  voir: {
    visite: [au.decisionsAVoir(bonnes, Date.parse('2026-10-07T12:45:00.000Z'), true).length, au.decisionsAVoir(bonnes, Date.parse('2026-10-07T12:45:00.000Z'), false).length,
      au.decisionsAVoir(bonnes, Date.parse('2026-10-07T12:50:00.000Z'), true).length, au.decisionsAVoir([], 0, false).length],
    comptes: au.comptesDecisions([d('autorisation', 'a', 'h'), d('fusion', 'b', 'h'), d('fusion', 'c', 'h'), d('fusion', 'd', 'h'), d('chantier', 'e', 'h'), d('autorisation', 'f', 'h')]).map((c) => c.texte),
    un: au.comptesDecisions([d('fusion', 'a', 'h'), d('chantier', 'b', 'h'), d('contrat', 'c', 'h'), d('autorisation', 'd', 'h')]).map((c) => c.texte),
    inconnus: au.comptesDecisions([d('merveille', 'a', 'h'), d('fusion', 'b', 'h'), d('merveille', 'c', 'h')]).map((c) => c.texte),
    verbes: ['fusion', 'chantier', 'contrat', 'autorisation', 'merveille'].map(au.verbeDecision),
  },
});
"""

SONDE_RENDU = DOM + r"""
const racine = process.argv[2];
const ensemble = await import(`${racine}/vues/ensemble.js`);
const base = JSON.parse(readFileSync(process.argv[3], 'utf8'));
const cas = JSON.parse(readFileSync(process.argv[4], 'utf8'));
const maintenant = Date.parse(base.genere_a);
const journal = Array.from({ length: 4 }, (_, i) => ({ id: i, horodatage: base.genere_a, auteur: 'utilisateur', action: 'lu', cible: 'x', details: {}, resultat: 'ok' }));
const resume = (li) => ({
  classes: li.classes, texte: texte(li),
});
const rendre = (etat, visite, avant) => {
  visiteMemorisee = visite === null ? null : String(visite);
  const c = new Elt('main');
  ensemble.rendre({ etat, contenu: c, route: { page: 'supervision', params: new URLSearchParams('') }, horloge: { maintenant: () => maintenant }, journal,
    tic() {}, source: { terminal: async () => null, agentsAvecTerminal: () => [] }, rerendre() {} });
  const bloc = a(c, 'nouveautes')[0];
  const liste = a(bloc, 'nouveautes-liste')[0];
  const lis = liste ? liste.children.filter((n) => n.tag === 'li') : [];
  const recap = lis.find((li) => li.classes.includes('nouveaute-recap')) || null;
  const detail = recap ? a(recap, 'decisions')[0] : null;
  const lignes = detail ? a(detail, 'decisions-liste')[0].children : [];
  const bouton = detail ? sous(detail).find((n) => n.tag === 'button') : null;
  return {
    ouvert: 'open' in bloc.attrs, titre: texte(a(bloc, 'nouveautes-titre')[0]), nombre: texte(a(bloc, 'nouveautes-nombre')[0]),
    n: lis.length, premier: lis.length ? resume(lis[0]) : null, recapEstPremier: Boolean(recap) && lis[0] === recap,
    recap: recap && { texte: texte(recap).slice(0, texte(recap).indexOf('Voir les décisions')), gras: sous(recap).filter((n) => n.tag === 'b').map(texte), classes: recap.classes },
    detail: detail && { ouvert: 'open' in detail.attrs, resume: texte(sous(detail).find((n) => n.tag === 'summary')),
      lignes: lignes.map((li) => [texte(a(li, 'decision-heure')[0]), texte(li.children[1]), texte(a(li, 'decision-cle')[0]), li.attrs.title ?? null, a(li, 'mono').map(texte), li.attrs.href ?? null]),
      bouton: bouton ? texte(bouton) : null },
    autres: lis.filter((li) => li !== recap).map(resume),
    texteTotal: texte(bloc),
    deplier: () => { if (bouton) (bouton.ecouteurs.click || []).forEach((f) => f({})); return detail ? a(detail, 'decisions-liste')[0].children.length : null; },
  };
};
const sorti = {};
for (const [nom, c] of Object.entries(cas)) {
  const r = rendre(c.etat, c.visite);
  if (c.deplier) { r.apres = r.deplier(); r.boutonApres = (() => { const rr = rendre(c.etat, c.visite); return rr.detail ? rr.detail.bouton : null; })(); }
  delete r.deplier;
  sorti[nom] = r;
}
sortie(sorti);
"""


SONDE_SCENE = DOM + r"""
const racine = process.argv[2];
const cas = JSON.parse(readFileSync(process.argv[3], 'utf8'));
const vue = await import(`${racine}/vues/mode-autonome.js`);
const ensemble = await import(`${racine}/vues/ensemble.js`);
const ecrits = [];
globalThis.localStorage = { getItem: () => visiteMemorisee, setItem: (k, v) => ecrits.push([k, v]) };
const detailDe = (n) => a(n, 'decisions')[0] ?? null;
// ce que la Scène montre : le récap, son détail (replié ou non, les lignes, le bouton « … et n autres »), les liens, l'ordre des enfants
const lire = (enc) => {
  const recap = a(enc, 'recap-scene')[0] ?? null;
  const d = detailDe(enc);
  const bouton = d ? sous(d).find((n) => n.tag === 'button') ?? null : null;
  const lignes = d ? a(d, 'decisions-liste')[0].children : [];
  return {
    recap: recap && { texte: texte(recap), gras: sous(recap).filter((n) => n.tag === 'b').map(texte), classes: recap.classes },
    detail: d && { ouvert: 'open' in d.attrs, classes: d.classes, resume: texte(sous(d).find((n) => n.tag === 'summary')),
      lignes: lignes.map((li) => [texte(a(li, 'decision-heure')[0]), texte(li.children[1]), texte(a(li, 'decision-cle')[0]), li.attrs.title ?? null]),
      bouton: bouton ? texte(bouton) : null },
    liens: sous(enc).filter((n) => n.tag === 'a').length,
    // l'ordre des enfants de l'encadré : le paragraphe, le récap, son détail, la liste (et le bouton en suspendu)
    ordre: enc.children.filter((n) => n instanceof Elt).map((n) => n.tag + (n.classes.length ? `.${n.classes[0]}` : '')),
    texte: texte(enc),
  };
};
const sorti = { cas: {} };
for (const [nom, c] of Object.entries(cas)) {
  visiteMemorisee = c.visite === null ? null : String(c.visite);
  ecrits.length = 0;
  const enc = vue.encadreMode(c.etat, () => {});
  const rendu = { ...lire(enc), ecrits: ecrits.length };
  const bouton = detailDe(enc) ? sous(detailDe(enc)).find((n) => n.tag === 'button') : undefined;
  if (c.deplier && bouton) {
    // « … et n autres » : la liste se déplie sur place (lu après le clic, à part)
    (bouton.ecouteurs.click || []).forEach((f) => f({}));
    rendu.apres = lire(enc).detail;
  }
  sorti.cas[nom] = rendu;
}

// les deux vues ont chacune leur détail : ouvrir l'une n'ouvre pas l'autre
const journal = Array.from({ length: 4 }, (_, i) => ({ id: i, horodatage: cas.actif.etat.genere_a, auteur: 'utilisateur', action: 'lu', cible: 'x', details: {}, resultat: 'ok' }));
const supervision = (etat) => {
  visiteMemorisee = null;
  const c = new Elt('main');
  ensemble.rendre({ etat, contenu: c, route: { page: 'supervision', params: new URLSearchParams('') }, horloge: { maintenant: () => Date.parse(etat.genere_a) }, journal,
    tic() {}, source: { terminal: async () => null, agentsAvecTerminal: () => [] }, rerendre() {} });
  return sous(c).find((n) => n instanceof Elt && n.tag === 'details' && n.classes.includes('decisions'));
};
const basculer = (d) => { if (!d) return; d.open = !('open' in d.attrs); (d.ecouteurs.toggle || []).forEach((f) => f({})); };
const ouverte = (d) => (d ? 'open' in d.attrs : null);  // null : pas de détail (une mutation le retire)
const etat = cas.actif.etat;
const croisee = {};
const s1 = supervision(etat);
croisee.supervisionAuDebut = ouverte(s1);
basculer(s1);                                                 // L'utilisateur déplie la Supervision
croisee.sceneApresSupervisionOuverte = ouverte(detailDe(vue.encadreMode(etat, () => {})));
const sc1 = detailDe(vue.encadreMode(etat, () => {}));
basculer(sc1);                                                // puis la Scène
croisee.supervisionApresSceneOuverte = ouverte(supervision(etat));
const s2 = supervision(etat);
basculer(s2);                                                 // L'utilisateur replie la Supervision : la Scène reste dépliée
croisee.sceneApresSupervisionFermee = ouverte(detailDe(vue.encadreMode(etat, () => {})));
sorti.croisee = croisee;
sortie(sorti);
"""



def _exemple():
    return json.loads(EXEMPLE_ETAT.read_text(encoding="utf-8"))


def _heure(iso):  # TZ=Europe/Paris, été : UTC + 2
    h, m = int(iso[11:13]) + 2, int(iso[14:16])
    return f"{h % 24} h {m:02d}" if m else f"{h % 24} h"


def _cas():
    base = _exemple()
    genere = base["genere_a"]
    t0 = int(__import__("datetime").datetime.fromisoformat(genere.replace("Z", "+00:00")).timestamp() * 1000)

    def il_y_a(minutes):
        return __import__("datetime").datetime.fromtimestamp((t0 - minutes * 60_000) / 1000, __import__("datetime").timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    six = [("fusion", "f223c94", 12), ("autorisation", "integration:lecture-journal", 35), ("fusion", "6eb0bf1", 62),
           ("chantier", "page:lot-6-recap", 95), ("autorisation", "hote:ecriture-etat", 128), ("fusion", "9436197", 160)]
    decisions = [{"genre": g, "cle": c, "horodatage": il_y_a(m), "message": 1412 - 3 * i} for i, (g, c, m) in enumerate(six)]

    def avec(champ, **plus):
        e = json.loads(json.dumps(base))
        if champ is None:
            e.pop("fusions_auto")
        else:
            e["fusions_auto"] = {**base["fusions_auto"], **champ, **plus}
        return e

    def calme(e):  # ni alarme ni agent arrêté : rien en rouge dans « Depuis ta dernière visite »
        e["alarmes"] = []
        for ag in e["agents"]:
            if ag.get("etat") == "arrete":
                ag["etat"] = "inactif"
        return e

    actif = {"active": True, "suspendue": False, "portee": 2, "chantiers_24h": 1, "chantiers_max": 5}
    beaucoup = [{"genre": "fusion", "cle": f"{i:07x}", "horodatage": il_y_a(1 + i), "message": 2000 + i} for i in range(12)]
    return decisions, il_y_a, t0, {
        "sans decisions": {"etat": avec(base["fusions_auto"]), "visite": None},
        "actif": {"etat": avec(actif, decisions=decisions), "visite": None},
        "actif visite il y a 1 h": {"etat": avec(actif, decisions=decisions), "visite": t0 - 60 * 60_000},
        "visite recente sans decisions": {"etat": calme(avec(base["fusions_auto"])), "visite": t0 - 20 * 60_000},
        "visite recente": {"etat": calme(avec(actif, decisions=decisions)), "visite": t0 - 20 * 60_000},
        "actif visite apres tout": {"etat": avec(actif, decisions=decisions), "visite": t0 - 5 * 60_000},
        "actif visite memorisee ancienne": {"etat": avec(actif, decisions=decisions), "visite": t0 - 30 * 3600_000},
        "actif vide": {"etat": avec(actif, decisions=[]), "visite": None},
        "inactif avec decisions": {"etat": avec({"active": False, "suspendue": False}, decisions=decisions), "visite": None},
        "absent": {"etat": avec(None), "visite": None},
        "vieil hote": {"etat": avec({"active": True, "suspendue": False}), "visite": None},
        "suspendu": {"etat": avec({**actif, "suspendue": True}, decisions=decisions), "visite": None},
        "desordre": {"etat": avec(actif, decisions=[decisions[2], decisions[0], decisions[5], decisions[1]]), "visite": None},
        "inconnu": {"etat": avec(actif, decisions=[{"genre": "merveille", "cle": "zz", "horodatage": il_y_a(5), "message": None}, decisions[0]]), "visite": None},
        "dix": {"etat": avec(actif, decisions=beaucoup[:10]), "visite": None},
        "onze": {"etat": avec(actif, decisions=beaucoup[:11]), "visite": None},
        "douze": {"etat": avec(actif, decisions=beaucoup), "visite": None, "deplier": True},
        # (le dernier : une fois déplié, le reste reste déplié d'un instantané à l'autre)
        "vieille": {"etat": avec(actif, decisions=[decisions[0], {"genre": "contrat", "cle": ".orga/contracts/etat.schema.md", "horodatage": il_y_a(600), "message": 1300}]), "visite": None},
        "vieille avec visite": {"etat": avec(actif, decisions=[decisions[0], {"genre": "contrat", "cle": ".orga/contracts/etat.schema.md", "horodatage": il_y_a(600), "message": 1300}]),
                                "visite": t0 - 180 * 60_000},
        "mal formee": {"etat": avec(actif, decisions=[{"genre": "fusion", "cle": "x", "horodatage": "pas une date"}, decisions[1]]), "visite": None},
    }


def _lancer(dossier_static, sonde, arguments):
    fichier = dossier_static / "sonde-recap.mjs"
    fichier.write_text(sonde, encoding="utf-8")
    res = subprocess.run(["node", str(fichier), *[str(x) for x in arguments]], capture_output=True, text=True, timeout=120, env={**os.environ, "TZ": "Europe/Paris"})
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


def verifier_lecture(static):
    r = _lancer(static, SONDE_LECTURE, [static, EXEMPLE_ETAT])
    # jamais `undefined` : un tableau vide pour tout ce qui n'est pas une liste de décisions d'un mode actif
    assert r["absent"] == r["nul"] == r["vieilHote"] == r["inactif"] == r["exemple"] == [] and r["pasUneListe"] == [[], [], [], []]
    assert [x["cle"] for x in r["bonnes"]] == ["aaaaaaa", "page:x"] and r["bonnes"][0] == {"genre": "fusion", "cle": "aaaaaaa", "horodatage": "2026-10-07T12:50:00.000Z", "message": 7}
    assert r["malFormees"] == ["aaaaaaa", "page:x"]  # les entrées mal formées sont écartées, les autres gardées dans l'ordre reçu
    assert r["inconnu"] == [{"genre": "merveille", "cle": "zz", "horodatage": "2026-10-07T12:00:00.000Z", "message": 7}]  # un genre inconnu mais bien formé est gardé
    assert r["sansMessage"] == [None, None] and r["cinquantaine"] == 50
    assert r["champs"] == [[2, 3, 5], [None, 0, None], [None, 0, None], [None, 0, None]], r["champs"]
    assert [g["genre"] for g in r["table"]] == ["fusion", "chantier", "contrat", "autorisation"]
    assert [(g["un"], g["plusieurs"], g["verbe"]) for g in r["table"]] == [
        ("fusion", "fusions", "fusionnée"), ("chantier lancé", "chantiers lancés", "lancé"), ("contrat modifié", "contrats modifiés", "modifié"),
        ("autorisation accordée", "autorisations accordées", "accordée")]
    v = r["voir"]
    assert v["visite"] == [1, 2, 0, 0], v["visite"]  # après la visite seulement ; sans visite mémorisée, toutes
    assert v["comptes"] == ["3 fusions", "1 chantier lancé", "2 autorisations accordées"], v["comptes"]  # l'ordre de la table, pas d'apparition
    assert v["un"] == ["1 fusion", "1 chantier lancé", "1 contrat modifié", "1 autorisation accordée"]
    assert v["inconnus"] == ["1 fusion", "2 merveille"], v["inconnus"]  # le genre inconnu s'écrit tel quel, après ceux de la table
    assert v["verbes"] == ["fusionnée", "lancé", "modifié", "accordée", "merveille"]


def verifier_rendu(static):
    decisions, il_y_a, t0, cas = _cas()
    fichier = static / "cas-recap.json"
    fichier.write_text(json.dumps(cas), encoding="utf-8")
    r = _lancer(static, SONDE_RENDU, [static, EXEMPLE_ETAT, fichier])
    PHRASE = "L’Assistant a décidé à ta place : "
    attendu = PHRASE + "3 fusions · 1 chantier lancé · 2 autorisations accordées"

    # références : sans décision, aucune ligne de récap (ni « 0 décision »), et la limite de 5 lignes est atteinte par les autres lignes
    base = r["sans decisions"]
    assert base["recap"] is None and base["detail"] is None and not base["recapEstPremier"] and base["n"] == 5, base["n"]
    for sans in ("sans decisions", "actif vide", "inactif avec decisions", "absent", "vieil hote"):
        x = r[sans]
        assert x["recap"] is None and x["detail"] is None and x["n"] == 5 and x["autres"] == base["autres"], sans
        assert "décision" not in x["texteTotal"] and "Assistant" not in x["texteTotal"] and x["ouvert"] == base["ouvert"], sans
    # une visite plus récente que toutes les décisions : aucune ligne non plus (les autres lignes, elles, suivent la visite)
    x = r["actif visite apres tout"]
    assert x["recap"] is None and x["detail"] is None and "décision" not in x["texteTotal"] and "Assistant" not in x["texteTotal"]

    # 3. le récap : première ligne, avant toutes les autres, sans couper la 5e ; bleu (la classe porte le bleu, pas de rouge)
    a_ = r["actif"]
    assert a_["recapEstPremier"] and a_["n"] == 6 and a_["autres"] == base["autres"], a_["n"]  # les 5 autres lignes sont toutes là
    assert a_["recap"]["texte"] == attendu and a_["recap"]["gras"] == ["L’Assistant a décidé à ta place"] and a_["recap"]["classes"] == ["nouveaute-recap"]
    assert "rouge" not in a_["recap"]["classes"]
    # 5. le bloc s'ouvre d'office ; le sous-titre compte le récap pour 1
    assert r["visite recente sans decisions"]["ouvert"] is False and r["visite recente"]["ouvert"] is True  # sans rouge, c'est le récap seul qui l'ouvre
    assert r["visite recente"]["recap"]["texte"] == PHRASE + "1 fusion" and r["visite recente"]["detail"]["ouvert"] is False
    assert a_["ouvert"] is True and a_["nombre"] == f" · {base['n'] + 1} changements", a_["nombre"]
    # 4. le détail : replié, la plus récente d'abord, heure courte, mot de la table, cle en mono, n° du message en title seulement, pas de lien
    d = a_["detail"]
    assert d["ouvert"] is False and d["resume"] == "Voir les décisions" and d["bouton"] is None
    assert d["lignes"] == [
        [_heure(il_y_a(m)), mot, cle, f"message n° {1412 - 3 * i}", [cle], None]
        for i, (mot, cle, m) in enumerate([("fusionnée", "f223c94", 12), ("accordée", "integration:lecture-journal", 35), ("fusionnée", "6eb0bf1", 62),
                                           ("lancé", "page:lot-6-recap", 95), ("accordée", "hote:ecriture-etat", 128), ("fusionnée", "9436197", 160)])], d["lignes"]
    # des décisions reçues en désordre sont rangées de la plus récente à la plus ancienne
    assert [x[2] for x in r["desordre"]["detail"]["lignes"]] == ["f223c94", "integration:lecture-journal", "6eb0bf1", "9436197"]
    assert r["desordre"]["recap"]["texte"] == PHRASE + "3 fusions · 1 autorisation accordée"

    # la dernière visite : seules les décisions d'après elle (12 et 35 min : une fusion, une autorisation) ; une visite plus récente que tout : aucune ligne
    assert r["actif visite il y a 1 h"]["recap"]["texte"] == PHRASE + "1 fusion · 1 autorisation accordée"
    assert [x[2] for x in r["actif visite il y a 1 h"]["detail"]["lignes"]] == ["f223c94", "integration:lecture-journal"]
    assert r["actif visite memorisee ancienne"]["recap"]["texte"] == attendu
    # sans visite mémorisée : toutes les décisions, même celles de plus de 3 heures (c'est le matin) ; la plus vieille ici date de 160 min
    assert r["vieille"]["recap"]["texte"] == PHRASE + "1 fusion · 1 contrat modifié" and r["vieille"]["detail"]["lignes"][1][2] == ".orga/contracts/etat.schema.md"
    assert r["vieille avec visite"]["recap"]["texte"] == PHRASE + "1 fusion"

    assert not re.search(r"\b(cle|genre|decisions)\b", a_["texteTotal"]), a_["texteTotal"]  # aucun jargon à l'écran

    # 6. états : suspendu garde la ligne sans parler de suspension ; un genre inconnu s'écrit tel quel
    s = r["suspendu"]
    assert s["recap"]["texte"] == attendu and "uspendu" not in s["recap"]["texte"] and "uspendu" not in s["texteTotal"]
    assert r["inconnu"]["recap"]["texte"] == PHRASE + "1 fusion · 1 merveille" and r["inconnu"]["detail"]["lignes"][0][1:4] == ["merveille", "zz", None]
    # une entrée à l'horodatage illisible est écartée sans casser la page
    assert r["mal formee"]["recap"]["texte"] == PHRASE + "1 autorisation accordée"

    # 4. au plus 10 lignes ; au-delà « … et n autres » qui déplie le reste ; 10 pile ou 11 : pas de bouton / « … et 1 autre »
    assert len(r["dix"]["detail"]["lignes"]) == 10 and r["dix"]["detail"]["bouton"] is None
    assert len(r["onze"]["detail"]["lignes"]) == 10 and r["onze"]["detail"]["bouton"] == "… et 1 autre"
    z = r["douze"]
    assert len(z["detail"]["lignes"]) == 10 and z["detail"]["bouton"] == "… et 2 autres" and z["apres"] == 12 and z["boutonApres"] is None
    assert [x[2] for x in z["detail"]["lignes"]] == [f"{i:07x}" for i in range(10)]  # les 10 plus récentes d'abord


def verifier_scene(static):
    """La Scène montre la ligne et, dessous, « Voir le détail » qui déplie la liste sur place (replié d'office, même liste que la
    Supervision, sans changer de page) ; la Supervision et la Scène ont chacune leurs replis."""
    decisions, il_y_a, t0, cas = _cas()
    fichier = static / "cas-scene.json"
    fichier.write_text(json.dumps(cas), encoding="utf-8")
    r = _lancer(static, SONDE_SCENE, [static, fichier])
    c = r["cas"]
    PHRASE = "L’Assistant a décidé à ta place : "
    six = [("fusionnée", "f223c94", 12), ("accordée", "integration:lecture-journal", 35), ("fusionnée", "6eb0bf1", 62),
           ("lancé", "page:lot-6-recap", 95), ("accordée", "hote:ecriture-etat", 128), ("fusionnée", "9436197", 160)]
    lignes6 = [[_heure(il_y_a(m)), mot, cle, f"message n° {1412 - 3 * i}"] for i, (mot, cle, m) in enumerate(six)]
    attendu = PHRASE + "3 fusions · 1 chantier lancé · 2 autorisations accordées"
    detail6 = {"ouvert": False, "classes": ["decisions"], "resume": "Voir le détail", "lignes": lignes6, "bouton": None}

    # l'état actif : la ligne, son détail replié d'office, dans cet ordre ; bleu (la classe porte le bleu), sans lien, sans changer de page
    a_ = c["actif"]
    assert a_["recap"] == {"texte": attendu, "gras": ["L’Assistant a décidé à ta place"], "classes": ["recap-scene"]}, a_["recap"]
    assert a_["detail"] == detail6, a_["detail"]
    assert a_["ordre"] == ["p", "p.recap-scene", "details.decisions", "details.reserves"], a_["ordre"]
    assert a_["liens"] == 0 and "Voir le détail" in a_["texte"]
    # le suspendu la garde, sans parler de suspension ; le bouton de réactivation reste en dernier
    s = c["suspendu"]
    assert s["recap"]["texte"] == attendu and "uspendu" not in s["recap"]["texte"]  # (le paragraphe du mode, lui, dit qu'il est suspendu)
    assert s["detail"] == detail6 and s["liens"] == 0
    assert s["ordre"] == ["p", "p.recap-scene", "details.decisions", "details.reserves", "button.action"], s["ordre"]
    # la même visite que la Supervision : la ligne et la liste disent les mêmes décisions
    assert c["actif visite il y a 1 h"]["recap"]["texte"] == PHRASE + "1 fusion · 1 autorisation accordée"
    assert [x[2] for x in c["actif visite il y a 1 h"]["detail"]["lignes"]] == ["f223c94", "integration:lecture-journal"]
    assert c["visite recente"]["recap"]["texte"] == PHRASE + "1 fusion" and [x[2] for x in c["visite recente"]["detail"]["lignes"]] == ["f223c94"]
    assert c["actif visite apres tout"]["recap"] is None and c["actif visite apres tout"]["detail"] is None
    assert c["inconnu"]["recap"]["texte"] == PHRASE + "1 fusion · 1 merveille"
    assert c["mal formee"]["recap"]["texte"] == PHRASE + "1 autorisation accordée"
    # des décisions reçues en désordre : la liste est rangée comme celle de la Supervision, la plus récente d'abord
    assert [x[2] for x in c["desordre"]["detail"]["lignes"]] == ["f223c94", "integration:lecture-journal", "6eb0bf1", "9436197"]
    # aucune décision à dire, inactif, absent, vieil hôte : aucune ligne ni détail (pas de « 0 décision »)
    for sans in ("sans decisions", "actif vide", "inactif avec decisions", "absent", "vieil hote"):
        assert c[sans]["recap"] is None and c[sans]["detail"] is None and "décidé" not in c[sans]["texte"] and "décision" not in c[sans]["texte"], sans
    # au plus 10 lignes ; au-delà « … et n autres » déplie le reste sur place ; 10 pile ou 11 : pas de bouton / « … et 1 autre »
    assert len(c["dix"]["detail"]["lignes"]) == 10 and c["dix"]["detail"]["bouton"] is None
    assert len(c["onze"]["detail"]["lignes"]) == 10 and c["onze"]["detail"]["bouton"] == "… et 1 autre"
    z = c["douze"]
    assert len(z["detail"]["lignes"]) == 10 and z["detail"]["bouton"] == "… et 2 autres"
    assert [x[2] for x in z["detail"]["lignes"]] == [f"{i:07x}" for i in range(10)]
    assert len(z["apres"]["lignes"]) == 12 and z["apres"]["bouton"] is None  # déplié sur place : les 12, plus de bouton
    # la Scène ne mémorise rien : aucune écriture de la visite, dans aucun cas
    assert all(x["ecrits"] == 0 for x in c.values()), {k: x["ecrits"] for k, x in c.items() if x["ecrits"]}
    # ouvrir le détail de l'une n'ouvre pas l'autre (chacune a ses replis) : la Supervision s'ouvre, la Scène reste repliée ; et l'inverse
    assert r["croisee"] == {"supervisionAuDebut": False, "sceneApresSupervisionOuverte": False, "supervisionApresSceneOuverte": True,
                            "sceneApresSupervisionFermee": True}, r["croisee"]


@pytest.fixture
def copie_static(tmp_path):
    cible = tmp_path / "static"
    shutil.copytree(STATIC, cible, ignore=shutil.ignore_patterns("__pycache__"))
    return cible


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node n'est pas installé : le récap n'est pas exécuté")


@needs_node
def test_lecture_executee(copie_static):
    verifier_lecture(copie_static)


@needs_node
def test_rendu_execute(copie_static):
    verifier_rendu(copie_static)


@needs_node
def test_scene_executee(copie_static):
    verifier_scene(copie_static)


MUTATIONS_EXECUTEES = {
    # la lecture
    "décisions lues même inactif": (AU, "decisions: actif ? lireDecisions(lecture.decisions) : [],", "decisions: lireDecisions(lecture.decisions),", verifier_lecture),
    "décisions indéfinies si absentes": (AU, "if (!Array.isArray(v)) return [];", "if (!Array.isArray(v)) return undefined;", verifier_lecture),
    "entrée mal formée gardée": (AU, "&& typeof d.horodatage === 'string' && !Number.isNaN(Date.parse(d.horodatage)))", "&& typeof d.horodatage === 'string')", verifier_lecture),
    "genre inconnu écarté": (AU, "typeof d.genre === 'string' && d.genre &&", "GENRES_DECISION.some((g) => g.genre === d.genre) &&", verifier_lecture),
    "plus de cinquante": (AU, ".slice(0, MAX_DECISIONS);", ";", verifier_lecture),
    "genre inconnu non écrit": (AU, "const ligne = GENRES_DECISION.find((g) => g.genre === c.genre);", "const ligne = GENRES_DECISION.find((g) => g.genre === c.genre) || { un: '?', plusieurs: '?' };", verifier_lecture),
    "toutes les décisions au lieu de celles d'après la visite": (AU, "(memorisee ? decisions.filter((d) => Date.parse(d.horodatage) > visite) : decisions)", "decisions", verifier_lecture),
    "genre à 0 affiché": (AU, ".filter((c) => c.n > 0)", "", verifier_lecture),
    "ordre de la table ignoré": (AU, "const genres = [...GENRES_DECISION.map((g) => g.genre), ...new Set(decisions.map((d) => d.genre))];", "const genres = [...new Set(decisions.map((d) => d.genre))];", verifier_lecture),
    # le rendu
    "récap absent": (ENS, "return recap ? [recap, ...lignes.slice(0, 5)] : lignes.slice(0, 5);", "return lignes.slice(0, 5);", verifier_rendu),
    "récap compté dans la limite de 5": (ENS, "return recap ? [recap, ...lignes.slice(0, 5)] : lignes.slice(0, 5);", "return (recap ? [recap, ...lignes] : lignes).slice(0, 5);", verifier_rendu),
    "récap en dernière position": (ENS, "[recap, ...lignes.slice(0, 5)]", "[...lignes.slice(0, 5), recap]", verifier_rendu),
    "récap en rouge": (ENS, "class: 'nouveaute-recap'", "class: 'nouveaute-recap rouge'", verifier_rendu),
    "inactif affiche « 0 »": (ENS, "if (!decisions.length) return null;", "if (!decisions.length) return el('li', { class: 'nouveaute-recap' }, '0 décision');", verifier_rendu),
    "toutes les décisions au lieu de celles d'après la visite (rendu)": (ENS, "decisionsAVoir(lireMode(etat).decisions, visite.instant, visite.memorisee)", "lireMode(etat).decisions", verifier_rendu),
    "ordre inversé": (DEC, "Date.parse(b.horodatage) - Date.parse(a.horodatage)", "Date.parse(a.horodatage) - Date.parse(b.horodatage)", verifier_rendu),
    "genre à 0 affiché (rendu)": (AU, ".filter((c) => c.n > 0)", "", verifier_rendu),
    "plus de dix lignes sans « … et n autres »": (DEC, "montrer(triees.slice(0, DECISIONS_VISIBLES));", "montrer(triees);", verifier_rendu),
    "« … et n autres » ne déplie pas": (DEC, "vue.toutes = true; montrer(triees); apres();", "vue.toutes = true; apres();", verifier_rendu),
    "détail ouvert d'office": (ENS, "const decisionsVue = etatDecisions();", "const decisionsVue = { ouvert: true, toutes: false };", verifier_rendu),
    "bloc fermé malgré les décisions": (ENS, "l.classList.contains('rouge') || l.classList.contains('nouveaute-recap')", "l.classList.contains('rouge')", verifier_rendu),
    "récap non compté dans le sous-titre": (ENS, "return recap ? [recap, ...lignes.slice(0, 5)] : lignes.slice(0, 5);", "return lignes.slice(0, 5);", verifier_rendu),
    "cle sans mono": (DEC, "el('span', { class: 'decision-cle' }, mono(d.cle))", "el('span', { class: 'decision-cle' }, d.cle)", verifier_rendu),
    "un lien vers le Fil": (DEC, "  return el('li', { title:", "  return el('li', { href: '#/fil', title:", verifier_rendu),
    "suspension dite": (ENS, "el('b', {}, PHRASE_RECAP), ` : ", "el('b', {}, PHRASE_RECAP), lireMode(etat).etat === 'suspendu' ? ' (suspendu)' : '', ` : ", verifier_rendu),
    # la Scène (p9-t4)
    "Scène : ligne absente en actif": (MO, "      ligneRecapScene(etat),\n      detailsReserves(etat, mode, (g, c) => ligneReserves", "      detailsReserves(etat, mode, (g, c) => ligneReserves", verifier_scene),
    "Scène : ligne absente en suspendu": (MO, "    ligneRecapScene(etat),\n    detailsReserves(etat, mode, (g, c) => (c === null", "    detailsReserves(etat, mode, (g, c) => (c === null", verifier_scene),
    "Scène : décisions lues sans le filtre du mode": (MO, "decisionsAVoir(lireMode(etat).decisions, visite.instant, visite.memorisee)", "decisionsAVoir((etat.fusions_auto || {}).decisions || [], visite.instant, visite.memorisee)", verifier_scene),
    "Scène : « 0 décision » en actif": (MO, "if (!decisions.length) return null;", "if (!decisions.length) return el('p', {}, '0 décision');", verifier_scene),
    "Scène : toutes les décisions au lieu de celles d'après la visite": (MO, "decisionsAVoir(lireMode(etat).decisions, visite.instant, visite.memorisee)", "lireMode(etat).decisions", verifier_scene),
    "Scène : la visite écrite à l'affichage": (MO, "const visite = derniereVisite(etat);", "const visite = derniereVisite(etat); localStorage.setItem('cime:derniere-visite:projet', '1');", verifier_scene),
    "Scène : la lecture partagée écrit la visite": (COM, "const valeur = Number(localStorage.getItem(cleVisite(etat)));", "localStorage.setItem(cleVisite(etat), '1');\n    const valeur = Number(localStorage.getItem(cleVisite(etat)));", verifier_scene),
    "Scène : lien vers la Supervision conservé": (MO, "detailDecisions(decisions, decisionsScene, LIBELLE_DETAIL_RECAP)];", "detailDecisions(decisions, decisionsScene, LIBELLE_DETAIL_RECAP), el('a', { href: '#/supervision' }, 'Voir le détail')];", verifier_scene),
    "Scène : liste absente": (MO, "),\n    detailDecisions(decisions, decisionsScene, LIBELLE_DETAIL_RECAP)];", ")];", verifier_scene),
    "Scène : liste non filtrée": (MO, "detailDecisions(decisions, decisionsScene, LIBELLE_DETAIL_RECAP)];", "detailDecisions(lireMode(etat).decisions, decisionsScene, LIBELLE_DETAIL_RECAP)];", verifier_scene),
    "Scène : dépliée d'office": (MO, "const decisionsScene = etatDecisions();", "const decisionsScene = { ouvert: true, toutes: false };", verifier_scene),
    "états partagés entre les deux vues": (DEC, "export const etatDecisions = () => ({ ouvert: false, toutes: false });", "const partage = { ouvert: false, toutes: false };\nexport const etatDecisions = () => partage;", verifier_scene),
    "Scène : ligne rouge": (MO, "el('p', { class: 'recap-scene' }", "el('p', { class: 'recap-scene rouge' }", verifier_scene),
    "Scène : texte recalculé à part": (MO, "${resumeDecisions(decisions)}`),", "${decisions.length} décisions`),", verifier_scene),
}


@needs_node
@pytest.mark.parametrize("nom", MUTATIONS_EXECUTEES)
def test_mutation_executee_detectee(nom, copie_static):
    fichier, ancien, nouveau, verification = MUTATIONS_EXECUTEES[nom]
    cible = copie_static / fichier
    texte = cible.read_text(encoding="utf-8")
    assert ancien in texte, ancien  # la mutation doit s'appliquer
    cible.write_text(texte.replace(ancien, nouveau, 1), encoding="utf-8")
    with pytest.raises((AssertionError, KeyError, StopIteration, ValueError, IndexError, TypeError)):
        verification(copie_static)


def test_couverture_des_verifications():
    toutes = {n for n, v in globals().items() if n.startswith("verifier_") and callable(v)}
    assert toutes == {"verifier_texte", "verifier_lecture", "verifier_rendu", "verifier_scene"} and MUTATIONS and MUTATIONS_EXECUTEES, sorted(toutes)
    assert {v[3] for v in MUTATIONS_EXECUTEES.values()} == {verifier_lecture, verifier_rendu, verifier_scene}  # chacune des vérifications exécutées a ses mutations
