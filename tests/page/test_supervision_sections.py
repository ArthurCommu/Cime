"""Supervision, les sections (retraits, « Ce qui coince », avancement, consommation, pied) et le point de rupture unique à 760 px.

Même convention que test_couleurs_etats.py et test_toast_et_degrade_mobile.py : analyse de texte du JS et du CSS de static/ (pas de navigateur dans pytest),
`verifier_supervision(js)` lève AssertionError ; la table MUTATIONS prouve qu'elle échoue quand on casse chaque comportement.
Les fonctions pures de commun.js (regroupement des alarmes `info` par type, ligne repliée d'un groupe, trois plus gros postes, largeur de barre)
sont de plus exécutées par node (sautées si node est absent) : `verifier_fonctions_executees`, avec ses propres mutations.
L'écran lui-même (ordre à l'œil, groupe replié puis déplié, hauteur de page, barre horizontale) est mesuré par tests/page/outils/scenario_supervision.py.
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
SECTIONS = ["sectionNouveautes()", "sectionOnglets()", "sectionAlarmes()", "sectionAvancement()", "sectionConsommation()",
            "sectionSessionsOrphelines()", "sectionIntegration()", "piedSupervision()"]
FEUILLES = ["style.css", "equipe.css", "archives.css", "pages-fil.css"]


def _corps(texte, debut, fin):
    i = texte.find(debut)
    assert i >= 0, debut
    j = texte.find(fin, i + len(debut))
    assert j >= 0, fin
    return texte[i:j]


def _ordre(texte, *morceaux):
    """Les morceaux sont tous présents, et dans cet ordre (AssertionError sinon, jamais ValueError)."""
    positions = []
    for m in morceaux:
        assert m in texte, m
        positions.append(texte.index(m))
    assert positions == sorted(positions), morceaux


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


def _importes(source):
    entete = _corps(source, "import {", "} from '../commun.js'")
    return [n.strip() for n in entete[len("import {"):].replace("\n", " ").split(",") if n.strip()]


def verifier_supervision(js):
    commun, ens, css = js["commun.js"], js["vues/ensemble.js"], js["style.css"]
    telephone = _corps(css, "@media (max-width: 760px) {\n  :root", "\n}\n")

    # 1. retraits : « Décisions récentes » et « Derniers échanges » ne sont plus dans Supervision, ni leur code mort
    for mort in ("sectionDecisions", "sectionFil", "Décisions récentes", "Derniers échanges", "decisions_recentes", "ligneFil", "journal des décisions", "etat.fil.slice"):
        assert mort not in ens, mort
    for utilise in _importes(ens):  # chaque nom importé sert : un import mort est du code mort
        assert len(re.findall(r"\b" + re.escape(utilise) + r"\b", ens)) >= 2, utilise
    assert "export function ligneFil" in commun and "ligneFil" in js["vues/fil.js"] and "ligneFil" in js["vues/equipe.js"]  # le Fil et la fiche équipe l'emploient encore
    assert "export function carteAlarme" in commun and "carteAlarme" in js["vues/equipe.js"] and "carteAlarme" not in ens  # la fiche équipe garde ses cartes
    assert ".lien-suite" in css and "lien-suite" in js["vues/equipe.js"]  # le style du lien « Tout le fil » sert la fiche équipe
    for ancien in (".frise", ".conso-fenetre", ".conso-poste", ".conso-barre", ".conso-plein"):
        assert ancien not in css, ancien  # les styles des sections refaites ne traînent pas

    # 2. l'ordre de l'écran : visite, onglets, ce qui coince, avancement, consommation, puis (s'il y en a) intégration et sessions, puis le pied
    rendu = _corps(ens, "export function rendre", "\n}\n")
    assert [rendu.index(s) for s in SECTIONS] == sorted(rendu.index(s) for s in SECTIONS)
    assert all(rendu.count(s) == 1 for s in SECTIONS)
    assert len([ligne for ligne in rendu.splitlines() if ligne.startswith("    ")]) == len(SECTIONS)  # rien d'autre dans l'écran

    # 3. « Ce qui coince » : une liste dans un seul cadre ; les graves en lignes, les à voir groupés par type, les infos en dernier
    alarmes = _corps(ens, "function sectionAlarmes()", "// ----")
    assert "enteteSection('Ce qui coince', sous)" in alarmes and "enteteSection('Alarmes'" not in ens
    assert "id: 'alarmes'" in alarmes
    assert "el('div', { class: 'vide-calme' }, 'Aucune alarme.')" in alarmes
    assert "'Alarmes ', inconnu(echecs || null, 'inconnues')" in alarmes and "l’absence d’alarme ne peut pas être affirmée" in alarmes
    assert "el('div', { class: 'alarmes alarmes-cadre' }, grouperAlarmes(etat.alarmes).map(ligneAlarme))" in alarmes  # un seul cadre, l'ordre vient de grouperAlarmes
    assert "comparerDepuis" not in ens and "carteProbleme" not in ens and "grouperInfos" not in ens
    aiguille = _corps(ens, "const ligneAlarme = ", ";\n")
    assert "item.genre === 'seule' ? ligneProbleme(item.alarmes[0])" in aiguille and "item.gravite === 'info' ? groupeInfos(item) : groupeProblemes(item)" in aiguille
    faire = _corps(ens, "function ligneFaire(a)", "\n}\n")
    assert "el('b', {}, 'Quoi faire :')" in faire and "` ${a.quoi_faire} `" in faire and "el('span', { class: 'al-lien' }, 'Détail')" in faire
    _ordre(faire, "'Quoi faire :'", "'Détail'", "a.mesure")  # « Quoi faire » en ligne, la mesure repliée derrière « Détail »
    assert "el('p', { class: 'alarme-ligne' }, a.mesure)" in faire and "open" not in faire.replace("ontoggle", "")
    carte = _corps(ens, "function ligneProbleme(a)", "\n}\n")
    assert "class: `al probleme ton-${tonAlarme(a)}`" in carte  # la couleur suit le type, pas la gravité
    assert "ciblesAlarme(a)" in carte and "ageAlarme(a)" in carte and "ligneFaire(a)" in carte
    _ordre(carte, "probleme-mot", "alarme-type", "ciblesAlarme(a)", "al-age", "ligneFaire(a)")  # ligne 1 : gravité, type, cibles, âge ; ligne 2 : quoi faire
    assert "alarme-cle" not in carte + faire and "'Mesure'" not in carte + faire and "'QUOI FAIRE'" not in ens and "'MESURE'" not in ens
    assert "mesurerLargeur" in faire
    groupe = _corps(ens, "function groupeInfos(groupe)", "\n}\n")
    assert "const r = resumeGroupeInfos(groupe);" in groupe and "el('details', { class: `al alarme-groupe ton-${groupe.ton}`" in groupe
    assert "open" not in groupe.replace("ontoggle", "").replace("opened", "")  # replié au chargement
    assert "el('span', { class: 'groupe-mot' }, r.mot)" in groupe and "r.type, r.cibles.length ? ` : ${r.cibles.join(', ')}` : ''" in groupe
    assert "groupe.alarmes.map(" in groupe and "a.mesure" in groupe and "a.quoi_faire" in groupe  # déplié : chaque alarme, entière
    assert "mesurerLargeur" in groupe
    assert "export function carteAlarme" in commun and "alarme-cle" in commun and "carteAlarme" not in ens  # la fiche équipe garde ses libellés
    # aucun libellé en capitales dans les nouvelles règles
    for sel in (".probleme-mot", ".al-faire b", ".alarme-detail > summary", ".alarme-groupe > summary", ".groupe-mot", ".groupe-resume", ".groupe-alarme", ".al-quoi"):
        assert "text-transform" not in _declarations(css, sel), sel
    assert "text-transform" not in _corps(css, "/* Supervision, « Ce qui coince »", "/* Fil : une ligne dense")
    assert "text-transform" not in _corps(css, "/* Avancement du projet", "/* Alarmes */")
    assert "--ambre" not in _declarations(css, ".al-faire b").get("color", "") and "ton-texte" not in _declarations(css, ".al-faire b").get("color", "")  # « Quoi faire : » en gras, jamais en ambre
    assert _declarations(css, ".al-faire b").get("font-weight") == "600"
    cadre = _declarations(css, ".alarmes-cadre")  # un cadre unique : bord, rayon 10, lignes séparées par un filet
    assert "var(--bord)" in cadre.get("border", "") and cadre.get("border-radius") == "var(--rayon)" and cadre.get("overflow") == "hidden"
    assert "var(--bord-doux)" in _declarations(css, ".al").get("border-bottom", "") and _declarations(css, ".al:last-child").get("border-bottom") == "0"

    # 4. avancement : sur la donnée telle qu'elle est (rien n'est inventé ni caché)
    avancement = _corps(ens, "function sectionAvancement()", "// ----")
    assert "etat.projet && etat.projet.etapes" in avancement and "el('ol', { class: 'etapes' }" in avancement
    assert "e.atteinte ? 'faite' : i === prochaine ? 'prochaine' : 'à venir'" in avancement
    assert "e.date ? ` · ${dateCourte(e.date)}` : ''" in avancement and "el('span', { class: 'etape-nom' }, e.nom)" in avancement
    assert "const prochaine = etapes.findIndex((e) => !e.atteinte);" in avancement
    assert "inconnu(sourceEnEchec(etat, 'structure'), 'étapes inconnues')" in avancement
    assert "enteteSection('Avancement du projet'" in avancement and "id: 'avancement'" in avancement
    for note in ("rafraîchir", "etapes.md", "périmé", "en service"):
        assert note not in avancement, note  # la page ne commente pas la donnée
    assert "frise" not in ens

    # 5. consommation : un grand chiffre, une ligne, trois barres
    conso = _corps(ens, "function sectionConsommation()", "// ----")
    assert "el('div', { class: 'conso-grand' }, jetonsOuInconnu(f15.lus))" in conso
    assert "Number.isInteger(f15.tours) ? pluriel(f15.tours, 'tour') : ['tours : ', inconnu(null)]" in conso
    assert "typeof f60.lus === 'number' ? [jetonsOuInconnu(f60.lus), ' sur 60 min'] : ['60 min : ', inconnu(null)]" in conso
    assert "], ' · ')" in conso and "joindre([" in conso
    postes = _corps(ens, "function postesConso(postes)", "function sectionConsommation()")
    assert "plusGrosPostes(postes)" in postes and "el('span', { class: 'poste-valeur' }, jetonsOuInconnu(p.lus_15min))" in postes
    assert "export function plusGrosPostes(postes, n = 3)" in commun
    assert "ecrits" not in ens and "contexte_moyen" not in ens and "dont_sous_agents" not in ens  # le détail par agent n'est plus à l'écran
    assert "largeurBarre(p.part_15min)" in ens and "style: `width: ${largeur}%`" in ens

    # 6. sessions hors organigramme et intégration : gardées, en bas, seulement quand elles ont un contenu
    assert rendu.index("sectionConsommation()") < rendu.index("sectionSessionsOrphelines()") < rendu.index("sectionIntegration()") < rendu.index("piedSupervision()")
    assert "if (Array.isArray(sessions) && !sessions.length) return null;" in ens
    assert "if (!integration.dernier_rapport && !(integration.requetes || []).length) return null;" in ens

    # 7. le pied : un lien discret, pas de carte (le lien des équipes clôturées est sous la grille de l'organigramme)
    pied = _corps(ens, "function piedSupervision()", "\n}\n")
    assert pied.count("el('a', { href:") == 1 and "{ href: '#/journal' }, 'Journal des actions'" in pied and "archives" not in pied
    assert "class: 'pied-supervision'" in pied and "carte" not in pied and "bouton" not in pied
    regle = _declarations(css, ".pied-supervision")
    assert not {"background", "border", "padding", "border-radius"} & set(regle), regle  # un lien, pas une carte

    # 8. le point de rupture mobile : 760 px, partout
    for feuille in FEUILLES:
        seuils = re.findall(r"@media \((max|min)-width: (\d+)px\)", js[feuille])
        autorises = {("max", "760"), ("max", "899"), ("min", "900"), ("max", "900"), ("max", "1100"), ("max", "1240"), ("max", "1280")}  # 1100 : les deux colonnes de la grille des équipes (étape 2) ; 900, 1240, 1280 : l'en-tête resserré, sans effectifs, aux intervalles réduits (p7-t4)
        assert set(seuils) <= autorises, (feuille, seuils)
        assert ("max", "700") not in seuils
    assert css.count("@media (max-width: 760px)") == 1 and js["equipe.css"].count("@media (max-width: 760px)") == 1 and js["archives.css"].count("@media (max-width: 760px)") == 1
    assert js["pages-fil.css"].count("@media (min-width: 900px)") == 1 and css.count("@media (max-width: 899px)") == 1  # seuils du Fil, signalés et inchangés
    assert re.findall(r"\b700px\b", "\n".join(js[f] for f in FEUILLES)) == []
    assert css.index(telephone) > css.index(".etapes {") and css.index(telephone) > css.index(".poste {")  # le bloc mobile vient après les règles qu'il surcharge

    # 9. mobile (390 px) : une colonne, groupes repliés, rien qui déborde
    assert "  .etapes { grid-template-columns: 1fr; gap: 12px; }" in telephone
    assert "  .conso { grid-template-columns: 1fr; gap: 14px; }" in telephone
    assert "  .poste { grid-template-columns: 110px minmax(0, 1fr) 56px; }" in telephone
    assert "  .alarme { flex-direction: column; gap: 8px; padding: 12px 14px; }" in telephone
    assert _declarations(css, ".alarmes").get("flex-direction") == "column"
    assert _declarations(css, ".groupe-resume").get("overflow-wrap") == "anywhere" and _declarations(css, ".groupe-resume").get("min-width") == "0"
    assert _declarations(css, ".alarme-detail > .alarme-ligne").get("overflow-wrap") == "anywhere"
    assert _declarations(css, ".poste-nom").get("text-overflow") == "ellipsis"
    assert "minmax(0, 1fr)" in _declarations(css, ".poste").get("grid-template-columns") and "minmax(0, 1fr)" in _declarations(css, ".conso").get("grid-template-columns")
    assert _declarations(css, ".alarme-groupe > summary").get("min-height") == "44px"  # une cible tactile
    assert _declarations(css, ".conso-petit").get("overflow-wrap") == "anywhere"

    # 10. couleurs : variables seulement, barres jamais rouges
    nouveau = _corps(css, "/* Avancement du projet", "/* Fil : une ligne dense")
    assert not re.search(r"#[0-9A-Fa-f]{3,8}\b", nouveau)
    assert "rouge" not in _corps(css, "/* Consommation : un chiffre", "/* Alarmes */")


# ---------------------------------------------------------------------------
# Fonctions pures exécutées (node)
# ---------------------------------------------------------------------------
SONDE = """
const { grouperInfos, resumeGroupeInfos, plusGrosPostes, largeurBarre } = await import(process.argv[2]);
const A = (type, gravite, extra = {}) => ({ type, gravite, equipes: [], agents: [], ...extra });
const alarmes = [
  A('retard_sur_base', 'info', { equipes: ['signaux'], id: 1 }),
  A('gros_poste', 'a_voir', { agents: ['assistant'], id: 2 }),
  A('retard_sur_base', 'info', { equipes: ['observation'], id: 3 }),
  A('session_orpheline', 'info', { agents: ['assistant', 'coord-hote'], id: 4 }),
  A('retard_sur_base', 'info', { equipes: ['signaux', 'page'], id: 5 }),
  A('question_sans_reponse', 'info', { agents: ['coord-page'], equipes: ['page'], id: 6 }),
  A('retard_sur_base', 'grave', { equipes: ['hote'], id: 7 }),
  A('session_orpheline', 'info', { id: 8 }),
];
const groupes = grouperInfos(alarmes);
const resumes = groupes.map(resumeGroupeInfos);
const vide = grouperInfos([A('gros_poste', 'grave'), A('fige', 'a_voir')]);
const sansInfo = grouperInfos([]);
const postes = [
  { agent: 'a', lus_15min: 1, part_15min: 0.1 }, { agent: 'b', lus_15min: 5, part_15min: 0.5 }, { agent: 'c', lus_15min: null, part_15min: null },
  { agent: 'd', lus_15min: 3, part_15min: 0.3 }, { agent: 'e', lus_15min: 3, part_15min: 0.3 }, { agent: 'f', lus_15min: 2, part_15min: 0.2 },
];
const trois = plusGrosPostes(postes).map((p) => p.agent);
const deux = plusGrosPostes(postes.slice(0, 2)).map((p) => p.agent);
const inconnuEnQueue = plusGrosPostes([{ agent: 'x', part_15min: null }, { agent: 'y', part_15min: 0 }, { agent: 'z' }]).map((p) => p.agent);
const quatre = plusGrosPostes(postes, 4).map((p) => p.agent);
const largeurs = [0, 0.521, 1, 1.5, -0.2, null, undefined, Infinity, -Infinity, '0.5'].map(largeurBarre);
console.log(JSON.stringify({
  types: groupes.map((g) => g.type),
  ids: groupes.map((g) => g.alarmes.map((a) => a.id)),
  tons: groupes.map((g) => g.ton),
  resumes, vide, sansInfo, trois, deux, inconnuEnQueue, quatre, largeurs,
  entree: alarmes.map((a) => a.id),
}));
"""
ATTENDU = {
    "types": ["retard_sur_base", "session_orpheline", "question_sans_reponse"],  # une ligne par type, dans l'ordre d'apparition
    "ids": [[1, 3, 5], [4, 8], [6]],  # l'ordre des alarmes de chaque groupe est conservé ; les graves et à voir n'y sont pas
    "tons": ["gris", "gris", "ambre"],  # une attente reste ambre jusque dans une ligne d'info
    "resumes": [
        {"mot": "Info ×3", "type": "Retard sur la branche de base", "cibles": ["signaux", "observation", "page"]},  # sans doublon
        {"mot": "Info ×2", "type": "Session hors organigramme", "cibles": ["Assistant", "coord-hote"]},  # agents faute d'équipe, noms lisibles
        {"mot": "Info ×1", "type": "Question sans réponse", "cibles": ["page"]},  # l'équipe prime sur l'agent
    ],
    "vide": [],
    "sansInfo": [],
    "trois": ["b", "d", "e"],  # les trois plus grosses parts ; à égalité, l'ordre reçu
    "deux": ["b", "a"],
    "inconnuEnQueue": ["y", "x", "z"],  # part inconnue : après toutes les parts connues (même 0), ordre reçu
    "quatre": ["b", "d", "e", "f"],
    "largeurs": [0, 52.1, 100, 100, 0, None, None, None, None, None],  # bornée à 0–100 ; inconnue → null (pas de barre), jamais 0
    "entree": [1, 2, 3, 4, 5, 6, 7, 8],  # l'entrée n'est pas modifiée
}


def executer(dossier_static):
    sonde = dossier_static / "sonde-supervision.mjs"
    sonde.write_text(SONDE, encoding="utf-8")
    res = subprocess.run(["node", str(sonde), str(dossier_static / "commun.js")], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


def verifier_fonctions_executees(dossier_static):
    r = executer(dossier_static)
    for cle, attendu in ATTENDU.items():
        if cle == "largeurs":
            assert [None if v is None else round(v, 6) for v in r[cle]] == attendu, (cle, r[cle])
        else:
            assert r[cle] == attendu, (cle, r[cle])



# ---------------------------------------------------------------------------
# Le rendu de l'écran, exécuté par node avec un DOM minimal
# ---------------------------------------------------------------------------
SONDE_RENDU = r"""
import { readFileSync } from 'node:fs';
class Node {}
class Txt extends Node { constructor(t) { super(); this.data = t; } }
class Elt extends Node {
  constructor(tag) { super(); this.tag = tag; this.attrs = {}; this.children = []; this.dataset = {}; this.style = {};
    this.classList = { contains: (c) => this.classes.includes(c), toggle() {}, add() {}, remove() {} }; }
  setAttribute(k, v) { this.attrs[k] = v; }
  getAttribute(k) { return this.attrs[k] ?? null; }
  addEventListener() {}
  append(...n) { this.children.push(...n); }
  querySelectorAll() { return []; }
  remove() {}
  replaceChildren(...n) { this.children = n; }
  get firstChild() { return this.children[0]; }
  get clientWidth() { return 800; }
  get classes() { return (this.attrs.class || '').split(/\s+/).filter(Boolean); }
}
globalThis.Node = Node;
globalThis.document = { createElement: (t) => new Elt(t), createTextNode: (t) => new Txt(t), documentElement: new Elt('html') };
globalThis.window = globalThis;
globalThis.addEventListener = () => {};
globalThis.localStorage = { getItem: () => null, setItem() {} };
globalThis.ResizeObserver = class { observe() {} disconnect() {} };
globalThis.requestAnimationFrame = (f) => f();
globalThis.history = { replaceState() {} };
const ens = await import(process.argv[2]);
const jeux = JSON.parse(readFileSync(process.argv[3], 'utf8'));
const texte = (n) => (n instanceof Txt ? n.data : (n.children || []).map(texte).join(''));
const sous = (n) => (n instanceof Elt ? [n, ...n.children.flatMap(sous)] : []);
const sortie = {};
for (const [nom, etat] of Object.entries(jeux)) {
  const c = new Elt('main');
  ens.rendre({ etat, contenu: c, route: { params: new URLSearchParams() }, horloge: { maintenant: () => Date.parse(etat.genere_a) }, journal: [], tic() {} });
  const section = (id) => c.children.find((n) => n.attrs.id === id);
  const alarmes = section('alarmes');
  const cartes = sous(alarmes).filter((n) => n.classes.includes('probleme'));
  const groupes = sous(alarmes).filter((n) => n.classes.includes('alarme-groupe'));
  const conso = section('consommation');
  const pied = c.children.find((n) => n.tag === 'nav');
  sortie[nom] = {
    ordre: c.children.map((n) => n.attrs.id || n.attrs.class || n.tag),
    titres: c.children.map((n) => { const h = sous(n).find((m) => m.tag === 'h2'); return h ? texte(h) : null; }),
    cartes: cartes.map((n) => ({ gravite: n.dataset.gravite, classes: n.classes, quoi: texte(sous(n).find((m) => m.classes.includes('al-faire'))),
      detail: texte(sous(n).find((m) => m.classes.includes('alarme-detail'))), ouvert: 'open' in sous(n).find((m) => m.classes.includes('alarme-detail')).attrs })),
    groupes: groupes.map((n) => ({ type: n.dataset.type, ouvert: 'open' in n.attrs, resume: texte(sous(n).find((m) => m.tag === 'summary')), lignes: sous(n).filter((m) => m.classes.includes('groupe-alarme')).length })),
    alarmesTexte: texte(alarmes),
    etapes: sous(section('avancement')).filter((n) => n.classes.includes('etape')).map((n) => ({ classes: n.classes, texte: texte(n) })),
    avancementTexte: texte(section('avancement')),
    consoTexte: texte(conso),
    barres: sous(conso).filter((n) => n.classes.includes('poste-plein')).map((n) => n.attrs.style),
    postes: sous(conso).filter((n) => n.classes.includes('poste')).length,
    pied: sous(pied).filter((n) => n.tag === 'a').map((n) => [n.attrs.href, texte(n)]),
    texteEntier: texte(c),
  };
}
console.log(JSON.stringify(sortie));
"""


def _etat_de_rendu():
    base = json.loads((FIXTURES / "exemple-etat.json").read_text(encoding="utf-8"))

    def variante(modifier):
        v = json.loads(json.dumps(base))
        modifier(v)
        return v

    def huit_infos(v):
        v["alarmes"] = [a for a in v["alarmes"] if a["gravite"] != "info"]
        for i, equipe in enumerate(["signaux", "observation", "fondation", "page"]):
            v["alarmes"].append({"type": "retard_sur_base", "gravite": "info", "agents": [], "equipes": [equipe], "depuis": "2026-10-07T12:0%d:00.000Z" % i,
                                 "mesure": "mesure %s" % equipe, "quoi_faire": "rien d'urgent"})
        v["alarmes"].append({"type": "session_orpheline", "gravite": "info", "agents": [], "equipes": [], "depuis": None, "mesure": "m", "quoi_faire": "q"})

    def inconnues(v):
        v["consommation"] = {"15min": {}, "60min": {}, "gros_postes": [{"agent": "assistant", "lus_15min": None, "part_15min": None}]}
        v["projet"]["etapes"] = None

    return {
        "exemple": base,
        "infos": variante(huit_infos),
        "sans alarme": variante(lambda v: v.update(alarmes=[])),
        "alarmes nulles": variante(lambda v: v.update(alarmes=None)),
        "conso nulle": variante(lambda v: v.update(consommation=None)),
        "inconnues": variante(inconnues),
        "integration vide": variante(lambda v: v.update(integration={"dernier_rapport": None, "requetes": []}, sessions_hors_organigramme=[])),
        "integration pleine": variante(lambda v: v.update(integration={"dernier_rapport": None, "requetes": [{"fichier": "r.md", "etat": "todo", "depuis": "2026-10-07T12:00:00.000Z"}]})),
    }


def rendre_ecran(dossier_static):
    sonde = dossier_static / "sonde-rendu.mjs"
    sonde.write_text(SONDE_RENDU, encoding="utf-8")
    jeux = dossier_static / "jeux-rendu.json"
    jeux.write_text(json.dumps(_etat_de_rendu()), encoding="utf-8")
    res = subprocess.run(["node", str(sonde), str(dossier_static / "vues" / "ensemble.js"), str(jeux)], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


def verifier_rendu(dossier_static):
    r = rendre_ecran(dossier_static)
    etat = _etat_de_rendu()
    # l'ordre, sur l'exemple : visite, onglets, ce qui coince, avancement, consommation, sessions hors organigramme, pied
    ex = r["exemple"]
    assert ex["ordre"][:2] == ["nouveautes", "section"], ex["ordre"]
    assert ex["ordre"][2:5] == ["alarmes", "avancement", "consommation"] and ex["ordre"][-1] == "pied-supervision", ex["ordre"]
    assert ex["titres"][2:5] == ["Ce qui coince", "Avancement du projet", "Consommation"], ex["titres"]
    assert all(t not in ex["texteEntier"] for t in ("Décisions récentes", "Derniers échanges", "Tout le fil", "MESURE", "QUOI FAIRE", "Gros postes"))
    assert ex["pied"] == [["#/journal", "Journal des actions"]]  # le lien des équipes clôturées est sous la grille
    # les cartes : une par alarme grave ou à voir, « Quoi faire » en ligne, mesure repliée
    nb = lambda e, g: sum(1 for a in e["alarmes"] if a["gravite"] == g)
    assert len(ex["cartes"]) == nb(etat["exemple"], "grave") + nb(etat["exemple"], "a_voir")
    assert [c["gravite"] for c in ex["cartes"]] == sorted((c["gravite"] for c in ex["cartes"]), key=lambda g: {"grave": 0, "a_voir": 1}[g])
    for c in ex["cartes"]:
        assert c["quoi"].startswith("Quoi faire : ") and c["quoi"].endswith(" Détail") and not c["ouvert"] and c["detail"].startswith("Quoi faire :")
    # les infos : une ligne par type, repliée, avec ses cibles ; dépliable pour voir chaque alarme
    inf = r["infos"]
    assert len(inf["cartes"]) == len(ex["cartes"])  # aucune info en carte
    assert [(g["type"], g["lignes"], g["ouvert"]) for g in inf["groupes"]] == [("retard_sur_base", 4, False), ("session_orpheline", 1, False)], inf["groupes"]
    assert inf["groupes"][0]["resume"].startswith("Info ×4Retard sur la branche de base : ") and "signaux" in inf["groupes"][0]["resume"] and "page" in inf["groupes"][0]["resume"]
    assert inf["groupes"][1]["resume"] == "Info ×1Session hors organigramme"
    assert inf["ordre"][2:5] == ["alarmes", "avancement", "consommation"]
    # états vides ou inconnus, honnêtes
    assert r["sans alarme"]["alarmesTexte"].endswith("Aucune alarme.") and r["sans alarme"]["cartes"] == [] and r["sans alarme"]["groupes"] == []
    assert "Alarmes inconnues" in r["alarmes nulles"]["alarmesTexte"] and "ne peut pas être affirmée" in r["alarmes nulles"]["alarmesTexte"]
    assert "Consommation inconnue" in r["conso nulle"]["consoTexte"] and r["conso nulle"]["barres"] == []
    inc = r["inconnues"]
    assert not re.search(r"\b0\b", inc["consoTexte"].replace("15 dernières minutes", ""))  # une valeur inconnue n'est jamais dite 0
    assert "tours : inconnu" in inc["consoTexte"] and "60 min : inconnu" in inc["consoTexte"] and "part inconnue" in inc["consoTexte"] and inc["barres"] == []
    assert "étapes inconnues" in inc["avancementTexte"]
    # avancement : faite / prochaine / à venir, sur la donnée telle qu'elle est
    et = ex["etapes"]
    donnees = etat["exemple"]["projet"]["etapes"]
    assert len(et) == len(donnees)
    prochaine = next(i for i, e in enumerate(donnees) if not e["atteinte"])
    for i, (e, d) in enumerate(zip(et, donnees)):
        mot = "faite" if d["atteinte"] else "prochaine" if i == prochaine else "à venir"
        assert e["texte"].startswith(mot) and d["nom"] in e["texte"], e
        assert ("faite" in e["classes"]) == d["atteinte"] and ("prochaine" in e["classes"]) == (i == prochaine)
    # consommation : un grand chiffre, la ligne, au plus trois barres neutres
    conso = etat["exemple"]["consommation"]
    assert ex["postes"] == min(3, len(conso["gros_postes"])) and len(ex["barres"]) == ex["postes"]
    attendues = [f"width: {p['part_15min'] * 100}%" for p in sorted(conso["gros_postes"], key=lambda p: -p["part_15min"])[:3]]
    assert ex["barres"] == attendues, ex["barres"]
    assert "8,0 M" in ex["consoTexte"] and "78 tours · 22,1 M sur 60 min" in ex["consoTexte"], ex["consoTexte"]
    # intégration et sessions : rien quand il n'y a rien
    assert "integration" not in r["integration vide"]["ordre"] and "sessions-orphelines" not in r["integration vide"]["ordre"], r["integration vide"]["ordre"]
    assert r["integration pleine"]["ordre"].index("consommation") < r["integration pleine"]["ordre"].index("integration") < r["integration pleine"]["ordre"].index("pied-supervision")


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def js():
    fichiers = sorted(STATIC.glob("*.js")) + sorted((STATIC / "vues").glob("*.js")) + [STATIC / f for f in FEUILLES]
    return {str(f.relative_to(STATIC)): f.read_text(encoding="utf-8") for f in fichiers}


def test_supervision_sections(js):
    verifier_supervision(js)


def _remplace(fichier, ancien, nouveau, tout=False):
    def mutation(js):
        assert ancien in js[fichier], ancien
        return {**js, fichier: js[fichier].replace(ancien, nouveau) if tout else js[fichier].replace(ancien, nouveau, 1)}
    return mutation


EN, COM, CSS = "vues/ensemble.js", "commun.js", "style.css"
RENDU = "    sectionNouveautes(),\n    sectionOnglets(),\n    sectionAlarmes(),\n    sectionAvancement(),\n    sectionConsommation(),\n    sectionSessionsOrphelines(),\n    sectionIntegration(),\n    piedSupervision());"
MUTATIONS = {
    # 1. retraits
    "décisions revenues": _remplace(EN, "    piedSupervision());", "    sectionDecisions(),\n    piedSupervision());"),
    "échanges revenus": _remplace(EN, "// 8. Pied", "function sectionFil() { return null; }\n// 8. Pied"),
    "mot « Derniers échanges » revenu": _remplace(EN, "// 8. Pied", "// Derniers échanges\n// 8. Pied"),
    "import mort": _remplace(EN, "mesurerLargeur, dateCourte,", "mesurerLargeur, ligneFil, dateCourte,"),
    "import mort d'un autre nom": _remplace(EN, "attentesOuvertes, attenteDe, sourceEnEchec,", "attentesOuvertes, attenteDe, heureLocale, sourceEnEchec,"),
    "ligneFil retiré du socle": _remplace(COM, "export function ligneFil(m) {", "function ligneFil(m) {"),
    "carteAlarme retirée de la fiche équipe": _remplace(COM, "export function carteAlarme(a) {", "function carteAlarme(a) {"),
    "carteAlarme employée par Supervision": _remplace(EN, "const ligneAlarme = (item) => (item.genre === 'seule' ? ligneProbleme(item.alarmes[0])", "const ligneAlarme = (item) => (item.genre === 'seule' ? carteAlarme(item.alarmes[0])"),
    "style de la frise gardé": _remplace(CSS, "/* Consommation : un chiffre", ".frise { display: grid; }\n/* Consommation : un chiffre"),
    "style de consommation mort gardé": _remplace(CSS, "/* Alarmes */", ".conso-fenetre { margin: 0; }\n/* Alarmes */"),
    "style du lien du Fil perdu": _remplace(CSS, ".lien-suite { font-size: 13px; margin-left: auto; }\n", ""),
    # 2. ordre
    "avancement avant ce qui coince": _remplace(EN, "    sectionAlarmes(),\n    sectionAvancement(),", "    sectionAvancement(),\n    sectionAlarmes(),"),
    "consommation avant l'avancement": _remplace(EN, "    sectionAvancement(),\n    sectionConsommation(),", "    sectionConsommation(),\n    sectionAvancement(),"),
    "pied avant la consommation": _remplace(EN, "    sectionConsommation(),\n    sectionSessionsOrphelines(),\n    sectionIntegration(),\n    piedSupervision());", "    piedSupervision(),\n    sectionConsommation(),\n    sectionSessionsOrphelines(),\n    sectionIntegration());"),
    "intégration avant la consommation": _remplace(EN, "    sectionConsommation(),\n    sectionSessionsOrphelines(),\n    sectionIntegration(),", "    sectionIntegration(),\n    sectionConsommation(),\n    sectionSessionsOrphelines(),"),
    "onglets avant la visite": _remplace(EN, "    sectionNouveautes(),\n    sectionOnglets(),", "    sectionOnglets(),\n    sectionNouveautes(),"),
    "section de plus": _remplace(EN, "    piedSupervision());", "    el('p', {}, 'x'),\n    piedSupervision());"),
    # 3. ce qui coince
    "section encore intitulée Alarmes": _remplace(EN, "enteteSection('Ce qui coince', sous)", "enteteSection('Alarmes', sous)"),
    "état calme perdu": _remplace(EN, "'Aucune alarme.'", "''"),
    "état inconnu perdu": _remplace(EN, "l’absence d’alarme ne peut pas être affirmée", ""),
    "infos en lignes seules": _remplace(EN, "item.gravite === 'info' ? groupeInfos(item) : groupeProblemes(item)", "groupeProblemes(item)"),
    "infos sans groupe": _remplace(EN, "grouperAlarmes(etat.alarmes).map(ligneAlarme)", "grouperAlarmes(etat.alarmes.filter((a) => a.gravite !== 'info')).map(ligneAlarme)"),
    "alarmes sans cadre unique": _remplace(EN, "{ class: 'alarmes alarmes-cadre' }", "{ class: 'alarmes' }"),
    "ordre local au lieu de grouperAlarmes": _remplace(EN, "grouperAlarmes(etat.alarmes).map(ligneAlarme)", "etat.alarmes.map((a) => ligneProbleme(a))"),
    "couleur d'après la gravité": _remplace(EN, "class: `al probleme ton-${tonAlarme(a)}`", "class: `al probleme ton-${(GRAVITES[a.gravite] || GRAVITES.info).ton}`"),
    "libellé « Quoi faire » en capitales": _remplace(EN, "el('b', {}, 'Quoi faire :'), ` ${a.quoi_faire} `", "el('b', {}, 'QUOI FAIRE :'), ` ${a.quoi_faire} `"),
    "libellé « Quoi faire » absent": _remplace(EN, "el('b', {}, 'Quoi faire :'), ` ${a.quoi_faire} `", "` ${a.quoi_faire} `"),
    "mesure hors du détail": _remplace(EN, "    el('p', { class: 'alarme-ligne' }, a.mesure));\n}\n\n/** Une alarme grave", "    null);\n}\n\n/** Une alarme grave"),
    "mesure avec libellé en capitales": _remplace(EN, "    el('p', { class: 'alarme-ligne' }, a.mesure));\n}\n\n/** Une alarme grave", "    el('p', { class: 'alarme-ligne' }, el('span', { class: 'alarme-cle' }, 'Mesure'), a.mesure));\n}\n\n/** Une alarme grave"),
    "détail sans titre": _remplace(EN, "el('span', { class: 'al-lien' }, 'Détail')", "el('span', { class: 'al-lien' }, '')"),
    "détail ouvert": _remplace(EN, "el('details', { class: 'alarme-detail', ontoggle", "el('details', { open: true, class: 'alarme-detail', ontoggle"),
    "groupe ouvert": _remplace(EN, "el('details', { class: `al alarme-groupe ton-${groupe.ton}`,", "el('details', { open: true, class: `al alarme-groupe ton-${groupe.ton}`,"),
    "groupe sans résumé": _remplace(EN, "const r = resumeGroupeInfos(groupe);", "const r = { mot: 'Info', type: '', cibles: [] };"),
    "groupe sans cibles": _remplace(EN, "r.type, r.cibles.length ? ` : ${r.cibles.join(', ')}` : ''", "r.type"),
    "groupe sans le détail des alarmes": _remplace(EN, "r.cibles.join(', ')}` : '')),\n    el('ul', { class: 'groupe-liste' }, groupe.alarmes.map(", "r.cibles.join(', ')}` : '')),\n    el('ul', { class: 'groupe-liste' }, [].map("),
    "groupe sans mesure": _remplace(EN, "      ciblesAlarme(a),\n      el('p', { class: 'alarme-ligne' }, a.mesure),", "      ciblesAlarme(a),"),
    "groupe sans « quoi faire »": _remplace(EN, "      el('p', { class: 'alarme-ligne' }, a.mesure),\n      el('p', { class: 'alarme-ligne alarme-quoi' }, el('b', {}, 'Quoi faire : '), a.quoi_faire)))));", "      el('p', { class: 'alarme-ligne' }, a.mesure)))));"),
    "dépliage sans remesure (carte)": _remplace(EN, "el('details', { class: 'alarme-detail', ontoggle: () => mesurerLargeur() },", "el('details', { class: 'alarme-detail' },"),
    "dépliage sans remesure (groupe)": _remplace(EN, "return el('details', { class: `al alarme-groupe ton-${groupe.ton}`, dataset: { type: groupe.type }, ontoggle: () => mesurerLargeur() },", "return el('details', { class: `al alarme-groupe ton-${groupe.ton}`, dataset: { type: groupe.type } },"),
    "mot de gravité en capitales": _remplace(CSS, ".probleme-mot { font-size: 12px;", ".probleme-mot { text-transform: uppercase; font-size: 12px;"),
    "résumé de groupe en capitales": _remplace(CSS, ".groupe-resume { min-width: 0;", ".groupe-resume { text-transform: uppercase; min-width: 0;"),
    "« Quoi faire » en capitales (CSS)": _remplace(CSS, ".al-faire b { font-weight: 600;", ".al-faire b { text-transform: uppercase; font-weight: 600;"),
    "« Quoi faire » en ambre": _remplace(CSS, ".al-faire b { font-weight: 600; color: var(--texte-doux); }", ".al-faire b { font-weight: 600; color: var(--ambre); }"),
    "cadre sans bord": _remplace(CSS, ".alarmes-cadre { gap: 0; background: var(--carte); border: 1px solid var(--bord);", ".alarmes-cadre { gap: 0; background: var(--carte);"),
    "lignes sans filet": _remplace(CSS, "padding: 12px 16px; border-bottom: 1px solid var(--bord-doux);\n}", "padding: 12px 16px;\n}"),
    # 4. avancement
    "étape faite dite atteinte": _remplace(EN, "e.atteinte ? 'faite' :", "e.atteinte ? 'atteinte' :"),
    "prochaine perdue": _remplace(EN, "i === prochaine ? 'prochaine' :", "i === prochaine ? 'à venir' :"),
    "date perdue": _remplace(EN, "e.date ? ` · ${dateCourte(e.date)}` : ''", "''"),
    "prochaine = dernière": _remplace(EN, "etapes.findIndex((e) => !e.atteinte)", "etapes.length - 1"),
    "étapes inconnues muettes": _remplace(EN, "inconnu(sourceEnEchec(etat, 'structure'), 'étapes inconnues')", "''"),
    "note sur la donnée périmée": _remplace(EN, "    corps);\n}\n\n// ---------------------------------------------------------------------------\n// 5.", "    corps, el('p', {}, 'Donnée à rafraîchir : etapes.md'));\n}\n\n// ---------------------------------------------------------------------------\n// 5."),
    "étapes tirées d'ailleurs": _remplace(EN, "etat.projet && etat.projet.etapes", "etat.projet && etat.projet.jalons"),
    "frise ancienne": _remplace(EN, "el('ol', { class: 'etapes' }", "el('ol', { class: 'frise' }"),
    "avancement sans ancre": _remplace(EN, "id: 'avancement'", "id: 'x'"),
    # 5. consommation
    "grand chiffre sur 60 min": _remplace(EN, "jetonsOuInconnu(f15.lus))", "jetonsOuInconnu(f60.lus))"),
    "tours perdus": _remplace(EN, "Number.isInteger(f15.tours) ? pluriel(f15.tours, 'tour') :", "false ? '' :"),
    "fenêtre de 60 min perdue": _remplace(EN, "[jetonsOuInconnu(f60.lus), ' sur 60 min']", "''"),
    "séparateur de la ligne": _remplace(EN, "], ' · '))),\n      Array.isArray(c.gros_postes)", "], ', '))),\n      Array.isArray(c.gros_postes)"),
    "tous les postes": _remplace(EN, "plusGrosPostes(postes).map(", "postes.map("),
    "largeur non calculée": _remplace(EN, "const largeur = largeurBarre(p.part_15min);", "const largeur = p.part_15min * 100;"),
    "jetons écrits revenus": _remplace(EN, "jetonsOuInconnu(f15.lus)),\n        el('div', { class: 'conso-petit' }", "jetonsOuInconnu(f15.lus), jetonsOuInconnu(f15.ecrits)),\n        el('div', { class: 'conso-petit' }"),
    "poste sans valeur": _remplace(EN, "      el('span', { class: 'poste-valeur' }, jetonsOuInconnu(p.lus_15min)));", "      '');"),
    # 6. sessions et intégration
    "sessions vides affichées": _remplace(EN, "if (Array.isArray(sessions) && !sessions.length) return null;", ""),
    "intégration vide affichée": _remplace(EN, "  if (!integration.dernier_rapport && !(integration.requetes || []).length) return null;\n", ""),
    "intégration sans rapport masquée": _remplace(EN, "!integration.dernier_rapport && !(integration.requetes || []).length", "!integration.dernier_rapport"),
    # 7. pied
    "lien du journal perdu": _remplace(EN, "el('a', { href: '#/journal' }, 'Journal des actions'));", ");"),
    "lien des archives revenu au pied": _remplace(EN, "el('a', { href: '#/journal' }, 'Journal des actions'));", "el('a', { href: '#/journal' }, 'Journal des actions'), el('a', { href: '#/archives' }, 'Équipes clôturées'));"),
    "pied en bouton": _remplace(EN, "el('a', { href: '#/journal' }, 'Journal des actions')", "el('a', { href: '#/journal', class: 'bouton' }, 'Journal des actions')"),
    "pied en carte": _remplace(CSS, ".pied-supervision { display: flex;", ".pied-supervision { background: var(--carte); border: 1px solid var(--bord); padding: 14px; display: flex;"),
    # 8. rupture
    "style.css à 700": _remplace(CSS, "@media (max-width: 760px) {\n  :root", "@media (max-width: 700px) {\n  :root"),
    "equipe.css à 700": _remplace("equipe.css", "@media (max-width: 760px)", "@media (max-width: 700px)"),
    "archives.css à 700": _remplace("archives.css", "@media (max-width: 760px)", "@media (max-width: 700px)"),
    "seuil de plus": _remplace("equipe.css", "@media (max-width: 760px)", "@media (max-width: 800px)"),
    "seuil du Fil déplacé": _remplace("pages-fil.css", "@media (min-width: 900px)", "@media (min-width: 760px)"),
    "second bloc mobile": _remplace(CSS, "/* Alarmes */", "@media (max-width: 760px) { .alarmes { gap: 4px; } }\n/* Alarmes */"),
    # 9. mobile
    "étapes en plusieurs colonnes": _remplace(CSS, "  .etapes { grid-template-columns: 1fr; gap: 12px; }\n", ""),
    "consommation en deux colonnes": _remplace(CSS, "  .conso { grid-template-columns: 1fr; gap: 14px; }\n", ""),
    "postes à largeur fixe": _remplace(CSS, "  .poste { grid-template-columns: 110px minmax(0, 1fr) 56px; }", "  .poste { grid-template-columns: 110px 300px 56px; }"),
    "cartes en ligne": _remplace(CSS, "  .alarme { flex-direction: column; gap: 8px; padding: 12px 14px; }\n", ""),
    "résumé de groupe qui déborde": _remplace(CSS, ".groupe-resume { min-width: 0; overflow-wrap: anywhere; }", ".groupe-resume { white-space: nowrap; }"),
    "mesure qui déborde": _remplace(CSS, ".alarme-detail > .alarme-ligne { margin-top: 6px; overflow-wrap: anywhere; }", ".alarme-detail > .alarme-ligne { margin-top: 6px; }"),
    "nom de poste qui déborde": _remplace(CSS, "text-overflow: ellipsis; white-space: nowrap; }\n.poste-barre", "white-space: nowrap; }\n.poste-barre"),
    "cible tactile trop basse": _remplace(CSS, "color: var(--secondaire); min-height: 44px; box-sizing: border-box;", "color: var(--secondaire); box-sizing: border-box;"),
    "total de consommation qui déborde": _remplace(CSS, ".conso-petit { font-size: 12px; color: var(--secondaire); overflow-wrap: anywhere; }", ".conso-petit { font-size: 12px; color: var(--secondaire); }"),
    # 10. couleurs
    "barre en couleur en dur": _remplace(CSS, ".poste-plein { display: block; height: 100%; background: var(--gris); }", ".poste-plein { display: block; height: 100%; background: #8C8880; }"),
    "barre rouge": _remplace(CSS, ".poste-plein { display: block; height: 100%; background: var(--gris); }", ".poste-plein { display: block; height: 100%; background: var(--rouge); }"),
    "étape en couleur en dur": _remplace(CSS, ".etape.faite::after { background: var(--vert);", ".etape.faite::after { background: #5FA777;"),
    # 11. exemple
}


MUTATIONS_EXECUTEES = {
    "info groupée par type sautée": ("infos.map((a) => a.type)", "infos.map((a, i) => i)"),
    "graves dans les groupes": ("alarmes.filter((a) => a.gravite === 'info')", "alarmes.filter((a) => a.gravite !== 'xxx')"),
    "groupes dans l'ordre alphabétique": ("return [...new Set(infos.map((a) => a.type))].map(", "return [...new Set(infos.map((a) => a.type))].sort().map("),
    "attente info grise": ("siennes.some((a) => tonAlarme(a) === 'ambre') ? 'ambre' : 'gris'", "'gris'"),
    "toutes les infos ambre": ("siennes.some((a) => tonAlarme(a) === 'ambre') ? 'ambre' : 'gris'", "'ambre'"),
    "compte du groupe faux": ("`Info ×${groupe.alarmes.length}`", "`Info ×${groupe.alarmes.length + 1}`"),
    "libellé de gravité sans le signe ×": ("`Info ×${groupe.alarmes.length}`", "`Info ${groupe.alarmes.length}`"),
    "type brut": ("type: TYPES_ALARME[groupe.type] || groupe.type", "type: groupe.type"),
    "cibles en double": ("const cibles = [...new Set(", "const cibles = [...(("),
    "agents avant équipes": ("((a.equipes || []).length ? a.equipes : (a.agents || []).map(nomAgent))", "((a.agents || []).length ? (a.agents || []).map(nomAgent) : a.equipes || [])"),
    "agents bruts": ("(a.agents || []).map(nomAgent))))]", "(a.agents || [])))]"),
    "postes dans l'ordre reçu": (".sort((x, y) => part(y.p) - part(x.p) || x.i - y.i)", ".sort((x, y) => x.i - y.i)"),
    "égalité départagée à l'envers": ("part(y.p) - part(x.p) || x.i - y.i", "part(y.p) - part(x.p) || y.i - x.i"),
    "quatre postes": ("export function plusGrosPostes(postes, n = 3)", "export function plusGrosPostes(postes, n = 4)"),
    "deux postes": ("export function plusGrosPostes(postes, n = 3)", "export function plusGrosPostes(postes, n = 2)"),
    "part inconnue en tête": ("typeof p.part_15min === 'number' ? p.part_15min : -1", "typeof p.part_15min === 'number' ? p.part_15min : 2"),
    "part inconnue avant un zéro": ("typeof p.part_15min === 'number' ? p.part_15min : -1", "typeof p.part_15min === 'number' ? p.part_15min : 0"),
    "largeur non bornée en haut": ("Math.min(100, Math.max(0, part * 100))", "Math.max(0, part * 100)"),
    "largeur non bornée en bas": ("Math.min(100, Math.max(0, part * 100))", "Math.min(100, part * 100)"),
    "largeur en fraction": ("Math.min(100, Math.max(0, part * 100))", "Math.min(1, Math.max(0, part))"),
    "part inconnue à zéro": ("Number.isFinite(part) ? Math.min(100, Math.max(0, part * 100)) : null", "Number.isFinite(part) ? Math.min(100, Math.max(0, part * 100)) : 0"),
    "infini en barre": ("typeof part === 'number' && Number.isFinite(part)", "typeof part === 'number'"),
    "texte en barre": ("typeof part === 'number' && Number.isFinite(part)", "Number.isFinite(Number(part))"),
}

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node n'est pas installé : les fonctions pures ne sont pas exécutées")


@pytest.mark.parametrize("nom", MUTATIONS)
def test_mutation_detectee(nom, js):
    mutee = MUTATIONS[nom](js)  # hors du raises : la mutation doit s'appliquer, sinon le test serait faux
    with pytest.raises(AssertionError):
        verifier_supervision(mutee)


@pytest.fixture
def copie_static(tmp_path):
    cible = tmp_path / "static"
    shutil.copytree(STATIC, cible, ignore=shutil.ignore_patterns("__pycache__"))
    return cible


@needs_node
def test_fonctions_executees(copie_static):
    verifier_fonctions_executees(copie_static)


@needs_node
@pytest.mark.parametrize("nom", MUTATIONS_EXECUTEES)
def test_mutation_executee_detectee(nom, copie_static):
    ancien, nouveau = MUTATIONS_EXECUTEES[nom]
    fichier = copie_static / "commun.js"
    texte = fichier.read_text(encoding="utf-8")
    assert ancien in texte, ancien  # la mutation doit s'appliquer
    fichier.write_text(texte.replace(ancien, nouveau), encoding="utf-8")
    with pytest.raises(AssertionError):
        verifier_fonctions_executees(copie_static)


MUTATIONS_RENDU = {
    "infos en lignes seules": ("vues/ensemble.js", "item.gravite === 'info' ? groupeInfos(item) : groupeProblemes(item)", "groupeProblemes(item)"),
    "infos sans groupe": ("vues/ensemble.js", "grouperAlarmes(etat.alarmes).map(ligneAlarme)", "grouperAlarmes(etat.alarmes.filter((a) => a.gravite !== 'info')).map(ligneAlarme)"),
    "groupe ouvert": ("vues/ensemble.js", "el('details', { class: `al alarme-groupe ton-${groupe.ton}`,", "el('details', { open: true, class: `al alarme-groupe ton-${groupe.ton}`,"),
    "groupe sans cibles": ("vues/ensemble.js", "r.type, r.cibles.length ? ` : ${r.cibles.join(', ')}` : ''", "r.type"),
    "groupe sans le détail": ("vues/ensemble.js", "r.cibles.join(', ')}` : '')),\n    el('ul', { class: 'groupe-liste' }, groupe.alarmes.map(", "r.cibles.join(', ')}` : '')),\n    el('ul', { class: 'groupe-liste' }, [].map("),
    "détail ouvert": ("vues/ensemble.js", "el('details', { class: 'alarme-detail', ontoggle", "el('details', { open: true, class: 'alarme-detail', ontoggle"),
    "« Quoi faire » absent": ("vues/ensemble.js", "el('b', {}, 'Quoi faire :'), ` ${a.quoi_faire} `", "` ${a.quoi_faire} `"),
    "section Alarmes": ("vues/ensemble.js", "enteteSection('Ce qui coince', sous)", "enteteSection('Alarmes', sous)"),
    "calme muet": ("vues/ensemble.js", "'Aucune alarme.'", "''"),
    "alarmes inconnues dites vides": ("vues/ensemble.js", "  if (!Array.isArray(etat.alarmes)) {\n    const echecs", "  if (false) {\n    const echecs"),
    "avancement avant ce qui coince": ("vues/ensemble.js", "    sectionAlarmes(),\n    sectionAvancement(),", "    sectionAvancement(),\n    sectionAlarmes(),"),
    "consommation après le pied": ("vues/ensemble.js", "    sectionConsommation(),\n    sectionSessionsOrphelines(),\n    sectionIntegration(),\n    piedSupervision());", "    sectionSessionsOrphelines(),\n    sectionIntegration(),\n    piedSupervision(),\n    sectionConsommation());"),
    "décisions revenues": ("vues/ensemble.js", "    piedSupervision());", "    el('section', { id: 'decisions' }, el('h2', {}, 'Décisions récentes')),\n    piedSupervision());"),
    "étape faite dite atteinte": ("vues/ensemble.js", "e.atteinte ? 'faite' :", "e.atteinte ? 'atteinte' :"),
    "prochaine perdue": ("vues/ensemble.js", "i === prochaine ? 'prochaine' :", "i === prochaine ? 'à venir' :"),
    "étapes inconnues muettes": ("vues/ensemble.js", "inconnu(sourceEnEchec(etat, 'structure'), 'étapes inconnues')", "''"),
    "tous les postes": ("vues/ensemble.js", "plusGrosPostes(postes).map(", "postes.map("),
    "barre à 0 pour une part inconnue": ("vues/ensemble.js", "largeur === null ? inconnu(null, 'part inconnue')", "largeur === null ? el('span', { class: 'poste-plein', style: 'width: 0%' })"),
    "tours inconnus comptés 0": ("vues/ensemble.js", "['tours : ', inconnu(null)]", "'0 tour'"),
    "60 min inconnue comptée 0": ("vues/ensemble.js", "['60 min : ', inconnu(null)]", "'0 sur 60 min'"),
    "grand chiffre inventé": ("vues/ensemble.js", "jetonsOuInconnu(f15.lus)),\n        el('div', { class: 'conso-petit' }", "String(f15.lus ?? 0)),\n        el('div', { class: 'conso-petit' }"),
    "consommation nulle muette": ("vues/ensemble.js", "inconnu(sourceEnEchec(etat, 'transcripts'), 'inconnue')", "''"),
    "lien du journal perdu": ("vues/ensemble.js", "el('a', { href: '#/journal' }, 'Journal des actions'));", ");"),
    "lien des archives au pied": ("vues/ensemble.js", "el('a', { href: '#/journal' }, 'Journal des actions'));", "el('a', { href: '#/journal' }, 'Journal des actions'), el('a', { href: '#/archives' }, 'Équipes clôturées'));"),
    "intégration vide affichée": ("vues/ensemble.js", "  if (!integration.dernier_rapport && !(integration.requetes || []).length) return null;\n", ""),
    "intégration avec requête masquée": ("vues/ensemble.js", "!integration.dernier_rapport && !(integration.requetes || []).length", "!integration.dernier_rapport"),
    "sessions vides affichées": ("vues/ensemble.js", "if (Array.isArray(sessions) && !sessions.length) return null;", ""),
}

@needs_node
def test_rendu_execute(copie_static):
    verifier_rendu(copie_static)


@needs_node
@pytest.mark.parametrize("nom", MUTATIONS_RENDU)
def test_mutation_rendu_detectee(nom, copie_static):
    fichier, ancien, nouveau = MUTATIONS_RENDU[nom]
    cible = copie_static / fichier
    texte = cible.read_text(encoding="utf-8")
    assert ancien in texte, ancien  # la mutation doit s'appliquer
    cible.write_text(texte.replace(ancien, nouveau, 1), encoding="utf-8")
    with pytest.raises((AssertionError, KeyError, StopIteration, ValueError)):
        verifier_rendu(copie_static)


def test_couverture_des_verifications():
    toutes = {n for n, v in globals().items() if n.startswith("verifier_") and callable(v)}
    assert toutes == {"verifier_supervision", "verifier_fonctions_executees", "verifier_rendu"} and MUTATIONS and MUTATIONS_EXECUTEES and MUTATIONS_RENDU, sorted(toutes)
