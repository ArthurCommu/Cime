"""Supervision, l'organigramme — la tête Utilisateur → Assistant, la grille des équipes, les lignes d'agent allégées.

Même convention que test_supervision_sections.py : analyse de texte du JS et du CSS de static/ (`verifier_organigramme(js)` lève AssertionError,
la table MUTATIONS prouve qu'elle échoue quand on casse chaque comportement), puis le rendu exécuté par node avec un DOM minimal
(`verifier_rendu_organigramme`, `verifier_equipe_a_l_arret`, chacun avec ses mutations ; sautés si node est absent).
La hauteur réelle de la page (≤ 1 800 px au bureau) est mesurée par tests/page/outils/scenario_supervision.py ; ici on vérifie ce qui la rend tenable :
quatre colonnes, cartes de hauteur égale, mission sur deux lignes, workers terminés repliés.
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
EN = "vues/ensemble.js"
CSS = "style.css"


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
    """Les morceaux sont tous présents, et dans cet ordre (AssertionError sinon, jamais ValueError)."""
    positions = []
    for m in morceaux:
        assert m in texte, m
        positions.append(texte.index(m))
    assert positions == sorted(positions), morceaux


def verifier_organigramme(js):
    commun, ens, css = js["commun.js"], js[EN], js[CSS]
    telephone = _corps(css, "@media (max-width: 760px) {\n  :root", "\n}\n")

    # 1. la tête : une ligne, l'utilisateur à gauche, l'Assistant à droite
    organigramme = _corps(ens, "function organigramme()", "\n}\n")
    assert "el('div', { class: 'org-tete' }, noeudUtilisateur(), noeudAssistant())" in organigramme
    _ordre(organigramme, "org-tete", "org-equipes")
    utilisateur = _corps(ens, "function noeudUtilisateur()", "\n}\n")
    assert "n ? el('a', { class: 'org-utilisateur-attentes', href: '#/' }, `${pluriel(n, 'point')} ${n === 1 ? 't’attend' : 't’attendent'}`)" in utilisateur
    assert "n === null ? 'ce qui t’attend : inconnu' : 'rien ne t’attend'" in utilisateur
    assistant = _corps(ens, "function noeudAssistant()", "\n}\n")
    assert "defEtatAgent(a, etat.alarmes)" in assistant and "pastilleEtat(def.cle, def)" in assistant and "age(a.etat_depuis, 'court')" in assistant
    assert "attend.qui === 'utilisateur' ? 't’attend ' : `attend ${nomAgent(attend.qui)} `, age(attend.depuis, 'depuis')" in assistant
    assert "el('span', { class: 'org-attend' }," in assistant and "jaugeFine(a)" in assistant
    assert "el('span', { class: 'org-phrase', title: a.derniere_phrase }, a.derniere_phrase)" in assistant
    _ordre(assistant, "org-attend", "jaugeFine(a)", "org-phrase")
    assert "inconnu(sourceEnEchec(etat, 'structure'), 'Assistant inconnu')" in assistant and "inconnu(null, 'Assistant introuvable')" in assistant
    jauge = _corps(ens, "function jaugeFine(agent)", "\n}\n")
    assert "dataset: { chaud: part > CONTEXTE_CHAUD ? 'oui' : 'non' }" in jauge and "inconnuCourt('contexte'" in jauge
    assert "Math.min(100, Math.round(part * 100))" in jauge
    assert _declarations(css, ".org-jauge i").get("width") == "56px"  # la jauge fine
    assert "var(--ambre)" in _declarations(css, '.org-jauge[data-chaud="oui"] i b').get("background", "")
    assert "var(--vert)" in _declarations(css, ".org-jauge i b").get("background", "")
    phrase = _declarations(css, ".org-phrase")
    assert phrase.get("font-style") == "italic" and phrase.get("white-space") == "nowrap" and phrase.get("text-overflow") == "ellipsis" and phrase.get("overflow") == "hidden"
    assert _declarations(css, ".org-attend").get("color") == "var(--ambre)" and _declarations(css, ".org-utilisateur-attentes").get("color") == "var(--ambre)"
    tete = _declarations(css, ".org-tete")
    assert tete.get("grid-template-columns") == "auto minmax(0, 1fr)"  # Utilisateur | Assistant, sur une ligne

    # 2. la grille : quatre colonnes, deux sous 1 100 px, une sous 760 px ; cartes de hauteur égale
    grille = _declarations(css, ".org-equipes")
    assert grille.get("display") == "grid" and grille.get("grid-template-columns") == "repeat(4, minmax(0, 1fr))" and grille.get("align-items") == "stretch"
    assert "@media (max-width: 1100px) {\n  .org-equipes { grid-template-columns: repeat(2, minmax(0, 1fr)); }\n}" in css
    assert "  .org-equipes { grid-template-columns: minmax(0, 1fr); }" in telephone
    _ordre(css, "@media (max-width: 1100px)", "@media (max-width: 760px)")  # la règle mobile vient après et l'emporte
    carte = _declarations(css, ".org-equipe")
    assert carte.get("display") == "flex" and carte.get("flex-direction") == "column" and carte.get("min-width") == "0" and carte.get("min-height") == "44px"
    assert carte.get("text-decoration") == "none" and "var(--ton)" in carte.get("border-top", "")
    assert _declarations(css, ".org-termines").get("margin-top") == "auto"  # le pied de carte reste en bas : les cartes d'une rangée s'alignent
    assert _declarations(css, ".org-equipe.a-l-arret").get("opacity") not in (None, "1")  # atténuée
    mission = _declarations(css, ".org-equipe-mission")
    assert mission.get("-webkit-line-clamp") == "2" and mission.get("overflow") == "hidden" and mission.get("display") == "-webkit-box"
    nom = _declarations(css, ".org-equipe-nom")
    assert nom.get("font-family") == "var(--mono)" and nom.get("font-size") == "15px"
    assert _declarations(css, ".ag-id").get("font-family") == "var(--mono)" and _declarations(css, ".ag-id").get("font-size") == "12px"
    for sel in (".ag-id", ".ag-quoi"):
        d = _declarations(css, sel)
        assert d.get("text-overflow") == "ellipsis" and d.get("white-space") == "nowrap", sel
    assert _declarations(css, ".org-barre b").get("background") == "var(--vert)"  # jamais rouge
    assert "var(--rouge" not in "".join(_declarations(css, s).get("background", "") for s in (".org-barre", ".org-barre b"))
    # tête mobile : l'utilisateur au-dessus de l'Assistant
    assert "  .org-tete { grid-template-columns: minmax(0, 1fr); }" in telephone and "  .org-utilisateur { border-right: 0; border-bottom: 1px solid var(--bord); }" in telephone

    # 3. la carte : un lien vers la fiche d'équipe, quatre blocs, la liste des agents vivants
    bloc = _corps(ens, "function blocEquipe(q)", "\n/** La ligne sous la grille")
    assert "return el('a', { class: `org-equipe ton-${def.ton}${arret ? ' a-l-arret' : ''}`, href: routeEquipe(q.nom)" in bloc
    assert "q.speciale ? el('span', { class: 'org-speciale' }, ' · spéciale') : null" in bloc and "puceStatut(q.statut, def)" in bloc
    assert "el('p', { class: 'org-equipe-mission', title: q.mission }, q.mission)" in bloc
    _ordre(bloc, "org-equipe-tete", "org-equipe-mission", "avancement(q)", "org-agents", "org-termines")
    assert "const arret = equipeALArret(q, etat.agents, etat.alarmes);" in bloc
    assert "const def = arret ? STATUT_EQUIPE_A_L_ARRET : statutEquipeAffiche(q, etat.alarmes);" in bloc
    assert "vivants.map((a) => ligneAgent(a, q))" in bloc and "el('span', { class: 'discret' }, 'aucun agent en cours')" in bloc
    assert "inconnu(sourceEnEchec(etat, 'structure'), 'agents inconnus')" in bloc
    assert "`+ ${termines} ${termines === 1 ? 'worker terminé' : 'workers terminés'}`" in bloc and "termines ? el('span'" in bloc  # rien à 0
    assert "Détail →" not in ens and "org-detail" not in ens + css  # la carte entière est le lien
    equipes = _corps(ens, "function agentsEquipe(q)", "function blocEquipe(q)")
    assert "const termines = siens.filter((a) => workerTermine(a, etat.alarmes));" in equipes
    assert "const vivants = siens.filter((a) => !termines.includes(a));" in equipes
    assert "if (!Array.isArray(etat.agents)) return { vivants: null, termines: 0 };" in equipes
    actives = _corps(ens, "function equipesActives()", "\n}\n")
    assert "q.statut !== 'terminee'" in actives and "equipesActives()" in organigramme  # une équipe clôturée n'a pas de carte
    assert "cartes.length ? el('div', { class: 'org-equipes' }, cartes.map(blocEquipe))" in organigramme and "'Aucune équipe pour l’instant.'" in organigramme
    assert "const cartes = actives ? actives.filter((q) => !retraits.includes(q)) : [];" in organigramme  # les équipes en retrait n'ont pas de carte
    assert "inconnu(sourceEnEchec(etat, 'structure'), 'inconnues')" in organigramme

    # 4. l'avancement de la carte : barre fine, « n / m » ou « 0 tâche »
    avance = _corps(ens, "function avancement(q)", "\n}\n")
    assert "total ? el('span', {}, `${a.faites} / ${total}`) : el('span', {}, '0 tâche')" in avance
    assert "inconnu(sourceEnEchec(etat, 'structure'), 'avancement inconnu')" in avance
    assert _declarations(css, ".org-barre").get("height") == "4px"

    # 5. la ligne d'agent : puce, identifiant, âge, puis l'alarme ou l'attente (ambre) ou la tâche — et rien de technique
    ligne = _corps(ens, "function ligneAgent(a, q)", "\n}\n")
    assert "defEtatAgent(a, etat.alarmes, { equipeTerminee: q.statut === 'terminee' })" in ligne
    _ordre(ligne, "pastille", "ag-id", "ag-age", "quoiAgent(a)")
    assert "a.etat_depuis ? age(a.etat_depuis, 'court') : inconnu(null, '?')" in ligne
    quoi = _corps(ens, "function quoiAgent(a)", "\n}\n")
    _ordre(quoi, "if (alarme)", "if (attend)", "if (autre)", "a.tache")
    assert "const alarme = alarmes.find(alarmeRouge);" in quoi and "class: 'ag-quoi ton-ambre'" in quoi
    assert "ton-${tonAlarme(alarme)}" in quoi and "TYPES_ALARME[alarme.type]" in quoi
    assert _declarations(css, '.ag-quoi[class*="ton-"]').get("color") == "var(--ton-texte)"
    avant_org = _corps(ens, "// 2a. Organigramme", "// 2b. Dépendances")
    for retire in ("carteAgent", "hook:", "etat_source", "aucune tâche déclarée", "cout_usd", "agent.modele", "a.modele", "consommation", "session absente",
                   "jaugeContexte", "agent-mesures", "agent-pied"):
        assert retire not in avant_org, retire  # ce qui reste dans le détail de l'agent (rail, fiche d'équipe) ne revient pas dans l'organigramme
    assert "carteAgent" not in _corps(ens, "import {", "} from '../commun.js'")
    # ...et ces données restent à leur place, dans la fiche d'équipe et le socle
    assert "export function carteAgent(agent, ctx, options = {})" in commun and "carteAgent(a, ctx, { detail: true" in js["vues/equipe.js"]
    for garde in ("agent.etat_source", "aucune tâche déclarée", "ligneConso(agent)", "cout(agent, ctx.etat)", "agent.modele"):
        assert garde in commun, garde
    assert "carteAgent" in js["vues/rail.js"] or "detailAgent" in js["vues/rail.js"]

    # 6. équipes clôturées : la phrase sous la grille est retirée ; le lien reste au pied (un seul)
    assert "n’apparaît" not in ens and "voir les archives" not in ens and "terminees ? el('p'" not in organigramme
    assert ens.count("href: '#/archives'") == 1 and "{ href: '#/archives' }, cloturees === null ? 'Équipes clôturées →'" in ens  # un seul lien, sous la grille (ligneLiens)

    # 7. l'équipe à l'arrêt : une fonction pure, un seul exemplaire, grise
    pure = _corps(commun, "export function equipeALArret(equipe, agents, alarmes)", "\n}\n")
    assert "equipe.statut === 'terminee' || equipe.statut === 'bloquee' || !Array.isArray(agents) || !Array.isArray(alarmes)" in pure
    assert "!siens.length || !siens.every((a) => etatAffiche(a) === 'arrete')" in pure
    assert "alarmesDe(alarmes, { equipe: equipe.nom }).length === 0 && siens.every((a) => alarmesDe(alarmes, { agent: a.id }).length === 0)" in pure
    assert "export const STATUT_EQUIPE_A_L_ARRET = { mot: 'à l’arrêt', ton: 'gris' };" in commun
    assert commun.count("export function equipeALArret(") == 1

    # 8. mobile : une colonne, pas de barre horizontale (min-width 0 partout), cible tactile d'au moins 44 px
    assert "minmax(0, 1fr)" in grille["grid-template-columns"] and _declarations(css, ".ag").get("grid-template-columns") == "14px minmax(0, 1fr) auto"
    assert "  .org-attend, .org-jauge { grid-column: 1 / -1; }" in telephone

    # 9. le garde-fou des mots, et les couleurs : aucune nouvelle règle rouge
    for mot in ("pause", "fusion", "compact"):
        assert not re.search(mot, avant_org, re.I), mot
    regles_org = _corps(css, "/* Organigramme : la tête", "/* Dépendances */")
    rouges = [r.strip() for r in re.findall(r"[^{}]+\{[^{}]*--rouge[^{}]*\}", regles_org)]
    assert rouges == ['.org-equipe[data-alarme="grave"] { border-color: var(--rouge-bord); border-top-color: var(--rouge); }'], rouges  # seule l'équipe citée par une alarme rouge


# ---------------------------------------------------------------------------
# Le rendu exécuté par node (DOM minimal)
# ---------------------------------------------------------------------------
SONDE = r"""
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
const a = (n, c) => sous(n).filter((m) => m.classes.includes(c));
const sortie = {};
for (const [nom, etat] of Object.entries(jeux)) {
  const c = new Elt('main');
  ens.rendre({ etat, contenu: c, route: { params: new URLSearchParams() }, horloge: { maintenant: () => Date.parse(etat.genere_a) }, journal: [], tic() {} });
  const org = sous(c).find((n) => n.classes.includes('organigramme'));
  const tete = a(org, 'org-tete')[0];
  const grille = a(org, 'org-equipes')[0];
  const jauge = a(org, 'org-jauge')[0];
  sortie[nom] = {
    enfants: org.children.map((n) => n.classes[0]),
    tete: { enfants: tete.children.map((n) => n.classes[0]), utilisateur: texte(a(tete, 'org-utilisateur')[0]),
      lienUtilisateur: a(tete, 'org-utilisateur-attentes').map((n) => [n.tag, n.attrs.href]),
      assistant: texte(a(tete, 'org-assistant')[0]), etatAge: a(tete, 'org-etat-age').length, attend: a(tete, 'org-attend').map(texte), phrase: a(tete, 'org-phrase').map((n) => texte(n)),
      jauge: jauge ? { chaud: jauge.dataset.chaud ?? null, largeurs: sous(jauge).filter((n) => n.tag === 'b').map((n) => n.attrs.style), texte: texte(jauge) } : null },
    cartes: grille ? grille.children.map((q) => ({
      tag: q.tag, href: q.attrs.href, classes: q.classes, alarme: q.dataset.alarme ?? null,
      nom: texte(a(q, 'org-equipe-nom')[0]), statut: texte(a(q, 'puce-statut')[0]), mission: texte(a(q, 'org-equipe-mission')[0]),
      avance: texte(a(q, 'org-avance')[0] || { children: [] }), texte: texte(q),
      agents: a(q, 'ag').map((l) => ({ id: texte(a(l, 'ag-id')[0]), etat: l.dataset.etat, quoi: a(l, 'ag-quoi').map((n) => ({ texte: texte(n), classes: n.classes })), classes: l.classes })),
      termines: a(q, 'org-termines').map(texte),
    })) : null,
    texteOrg: texte(org),
    liens: sous(c).filter((n) => n.tag === 'a' && n.attrs.href === '#/archives').length,
  };
}
console.log(JSON.stringify(sortie));
"""

SONDE_PURE = r"""
const commun = await import(process.argv[2]);
const [equipe, agents, alarmes] = JSON.parse(process.argv[3]);
console.log(JSON.stringify(commun.equipeALArret(equipe, agents, alarmes)));
"""


def _exemple():
    return json.loads((FIXTURES / "exemple-etat.json").read_text(encoding="utf-8"))


def _agent(ident, role, equipe, etat="arrete", vivant=False, tache=None):
    return {"id": ident, "role": role, "equipe": equipe, "parent": "assistant", "session_tmux": None if not vivant else "cc-" + ident, "vivant": vivant,
            "etat": etat, "etat_depuis": "2026-10-07T12:00:00.000Z", "etat_source": "hook:Stop", "tache": tache, "derniere_phrase": "phrase technique",
            "modele": "claude-sonnet-5-5", "contexte": {"tokens": 1000, "limite": 1000000, "source": "transcript"}, "cout_usd_estime": 1.5,
            "consommation": None, "brouillon": None, "dettes": [], "file": [], "occupe_par": None}


def _equipe(nom, statut="au_repos", speciale=False, faites=3, en_cours=0, a_faire=0, mission="Une mission."):
    return {"nom": nom, "mission": mission, "speciale": speciale, "statut": statut, "cloturee_le": None, "branche": "equipe/" + nom, "commit": "abc1234",
            "worktree": "/x", "avancement": {"faites": faites, "en_cours": en_cours, "a_faire": a_faire}, "fichiers_touches": [], "perimetre_declare": [],
            "hors_perimetre": [], "retard_sur_base": 0, "en_avance_sur_base": 0, "depend_de": []}


def _alarme(type_, gravite, agents=(), equipes=()):
    return {"id": f"{type_}:{'-'.join(agents)}", "type": type_, "gravite": gravite, "agents": list(agents), "equipes": list(equipes),
            "depuis": "2026-10-07T12:00:00.000Z", "mesure": "m", "quoi_faire": "q", "destinataire": "utilisateur"}


def _jeux():
    base = _exemple()

    def variante(modifier):
        v = json.loads(json.dumps(base))
        modifier(v)
        return v

    def equipes_terminees(v):
        for q in v["equipes"]:
            if q["nom"] == "page":
                q["statut"] = "terminee"

    def terminee_et_alarme(v):
        # alpha : un worker arrêté avec alarme (reste), un sans alarme (compté), un travaillant ; beta : à l'arrêt ; gamma : sans agent ; delta : spéciale, sans avancement
        v["equipes"] += [_equipe("alpha", "active"), _equipe("beta", "au_repos"), _equipe("gamma", "au_repos", faites=0), _equipe("delta", "au_repos", speciale=True, faites=0)]
        v["equipes"].append(_equipe("epsilon", "au_repos"))
        v["agents"] += [_agent("w-alpha-casse", "worker", "alpha"), _agent("w-alpha-rendu", "worker", "alpha"), _agent("w-alpha-vif", "worker", "alpha", "travaille", True, "Écrire"),
                        _agent("coord-alpha", "coordinateur", "alpha", "travaille", True, "Coordonner alpha"),  # après ses workers : l'ordre d'affichage est celui de la page
                        _agent("coord-beta", "coordinateur", "beta"), _agent("w-beta-rendu", "worker", "beta"), _agent("coord-epsilon", "coordinateur", "epsilon")]
        v["alarmes"].append(_alarme("recouvrement", "grave", [], ["epsilon"]))
        v["alarmes"].append(_alarme("session_disparue", "grave", ["w-alpha-casse"], ["alpha"]))

    def agents_inconnus(v):
        v["agents"] = None

    def attend_un_coordinateur(v):
        v["fil"].append({"id": "msg-90", "horodatage": "2026-10-07T12:52:11.123Z", "de": "assistant", "a": "coord-hote", "nature": "question", "resume": "r",
                         "fichier": None, "en_attente": True, "source": "registre", "etat_livraison": "livre", "non_lu": False, "preuve": None})
        for m in v["fil"]:
            if m["de"] == "assistant" and m["a"] == "utilisateur":
                m["en_attente"] = False

    def leger(v):
        for a in v["agents"]:
            if a["role"] == "assistant":
                a["contexte"] = {"tokens": 280000, "limite": 1000000, "source": "transcript"}
                a["derniere_phrase"] = None

    return {
        "exemple": base,
        "terminee exclue": variante(equipes_terminees),
        "worker arrete": variante(terminee_et_alarme),
        "agents inconnus": variante(agents_inconnus),
        "rien n'attend": variante(lambda v: v.update(attentes_utilisateur=[])),
        "attentes inconnues": variante(lambda v: v.update(attentes_utilisateur=None)),
        "sans equipe": variante(lambda v: v.update(equipes=[])),
        "equipes inconnues": variante(lambda v: v.update(equipes=None)),
        "assistant attend": variante(attend_un_coordinateur),
        "assistant leger": variante(leger),
        "sans assistant": variante(lambda v: v.update(agents=[a for a in v["agents"] if a["role"] != "assistant"])),
    }


def rendre(dossier_static):
    sonde = dossier_static / "sonde-organigramme.mjs"
    sonde.write_text(SONDE, encoding="utf-8")
    jeux = dossier_static / "jeux-organigramme.json"
    jeux.write_text(json.dumps(_jeux()), encoding="utf-8")
    res = subprocess.run(["node", str(sonde), str(dossier_static / "vues" / "ensemble.js"), str(jeux)], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


def _alarmes_citant(etat, ident):
    return [a for a in (etat["alarmes"] or []) if ident in a["agents"]]


def _termine(etat, a):
    """L'oracle : un worker arrêté (tmux a répondu), qu'aucune alarme ne cite."""
    return a["role"] == "worker" and a["etat"] == "arrete" and a["vivant"] is not None and not _alarmes_citant(etat, a["id"])


def verifier_rendu_organigramme(dossier_static):
    r = rendre(dossier_static)
    jeux = _jeux()
    ex, etat = r["exemple"], jeux["exemple"]

    # la tête : l'utilisateur puis l'Assistant, avant la grille ; plus d'arbre ni de trait
    assert ex["enfants"] == ["org-tete", "org-equipes", "org-liens"], ex["enfants"]
    assert ex["tete"]["enfants"] == ["org-utilisateur", "org-assistant"]
    n = len(etat["attentes_utilisateur"])
    assert ex["tete"]["utilisateur"] == f"Utilisateur{n} points t’attendent", ex["tete"]["utilisateur"]
    assert ex["tete"]["lienUtilisateur"] == [["a", "#/"]]
    assert r["rien n'attend"]["tete"]["utilisateur"] == "Utilisateurrien ne t’attend", r["rien n'attend"]["tete"]["utilisateur"]
    assert r["rien n'attend"]["tete"]["lienUtilisateur"] == []
    assert r["attentes inconnues"]["tete"]["utilisateur"] == "Utilisateurce qui t’attend : inconnu"
    assert ex["tete"]["assistant"].startswith("Assistant")
    assert ex["tete"]["etatAge"] == 1  # la durée de l'état, vivante (le ticker la réécrit)
    assert "travaille" in ex["tete"]["assistant"] and "contexte" in ex["tete"]["assistant"] and "64" in ex["tete"]["assistant"]
    assert ex["tete"]["phrase"] == [next(a for a in etat["agents"] if a["role"] == "assistant")["derniere_phrase"]]
    assert ex["tete"]["jauge"]["chaud"] == "oui" and ex["tete"]["jauge"]["largeurs"] == ["width: 64%"]  # 640 k / 1 M : lourd, ambre
    assert r["assistant leger"]["tete"]["jauge"]["chaud"] == "non" and r["assistant leger"]["tete"]["jauge"]["largeurs"] == ["width: 28%"]
    assert r["assistant leger"]["tete"]["phrase"] == []  # pas de phrase : pas de ligne
    # ce que l'Assistant attend
    assert ex["tete"]["attend"] and ex["tete"]["attend"][0].startswith("t’attend")  # l'exemple : il attend l'utilisateur
    assert r["assistant attend"]["tete"]["attend"] and r["assistant attend"]["tete"]["attend"][0].startswith("attend coord-hote")
    assert r["assistant leger"]["tete"]["attend"] == ex["tete"]["attend"]
    # l'Assistant absent ou inconnu
    assert "Assistant introuvable" in r["sans assistant"]["tete"]["assistant"]
    assert "Assistant inconnu" in r["agents inconnus"]["tete"]["assistant"]

    # la grille : une carte-lien par équipe non clôturée, dans l'ordre des données
    attendues = [q for q in etat["equipes"] if q["statut"] != "terminee"]
    assert [c["nom"].replace(" · spéciale", "") for c in ex["cartes"]] == [q["nom"] for q in attendues], [c["nom"] for c in ex["cartes"]]
    assert all(c["tag"] == "a" and c["href"] == "#/equipe/" + c["nom"].replace(" · spéciale", "") for c in ex["cartes"])
    assert all("cadrage" not in c["nom"] for c in ex["cartes"])  # l'équipe clôturée n'a pas de carte
    terminee = r["terminee exclue"]
    assert [c["nom"] for c in terminee["cartes"]] == [q["nom"] + (" · spéciale" if q["speciale"] else "") for q in jeux["terminee exclue"]["equipes"] if q["statut"] != "terminee"]
    assert "page" not in [c["nom"] for c in terminee["cartes"]]
    # chaque carte : nom, statut, mission en entier (l'ellipse est dans le CSS), avancement
    for c, q in zip(ex["cartes"], attendues):
        assert c["mission"] == q["mission"]
        av = q["avancement"]
        total = av["faites"] + av["en_cours"] + av["a_faire"]
        assert c["avance"] == (f"{av['faites']} / {total}" if total else "0 tâche"), c["avance"]
        assert c["statut"], c["nom"]
    # agents vivants seulement, workers terminés comptés
    for c, q in zip(ex["cartes"], attendues):
        siens = [a for a in etat["agents"] if a["equipe"] == q["nom"]]
        vivants = [a["id"] for a in siens if not _termine(etat, a)]
        assert sorted(l["id"] for l in c["agents"]) == sorted(vivants), (q["nom"], c["agents"])
        nt = sum(1 for a in siens if _termine(etat, a))
        assert c["termines"] == ([f"+ {nt} worker terminé" if nt == 1 else f"+ {nt} workers terminés"] if nt else []), (q["nom"], c["termines"])
    hote = next(c for c in ex["cartes"] if c["nom"] == "hote")
    assert "worker-hote-schema" not in [l["id"] for l in hote["agents"]]  # arrêté sans alarme : compté, pas listé
    assert hote["termines"] == ["+ 1 worker terminé"]
    # ce que la carte d'agent ne montre plus
    for c in ex["cartes"]:
        for interdit in ("hook:", "aucune tâche déclarée", "conso", "coût", "claude-", "contexte", "session absente", "Détail"):
            assert interdit not in c["texte"], (c["nom"], interdit)
    # sous l'agent : l'alarme grave, sinon l'attente (ambre), sinon la tâche
    page = next(c for c in ex["cartes"] if c["nom"] == "page")
    coord_page = next(l for l in page["agents"] if l["id"] == "coord-page")
    assert coord_page["quoi"][0]["texte"] == "Autorisation en attente" and "ton-ambre" in coord_page["quoi"][0]["classes"]
    obs = next(c for c in ex["cartes"] if c["nom"] == "observation")
    w_tmux = next(l for l in obs["agents"] if l["id"] == "worker-observation-tmux")
    assert w_tmux["quoi"][0]["classes"] == ["ag-quoi", "ton-ambre"]  # une question sans réponse : une attente, ambre
    verif = next(c for c in ex["cartes"] if c["nom"].startswith("verification"))
    assert "ton-gris" in verif["classes"] or "ton-vert" in verif["classes"]
    assert "spéciale" in verif["nom"] and "spéciale" not in next(c for c in ex["cartes"] if c["nom"] == "page")["nom"]
    assert next(l for l in verif["agents"] if l["id"] == "coord-verification")["quoi"][0]["classes"] == ["ag-quoi", "ton-ambre"]  # alarme « fige », à voir
    # un worker arrêté AVEC alarme reste listé, rouge ; celui sans alarme est compté ; un worker vivant reste
    w = r["worker arrete"]["cartes"]
    alpha = next(c for c in w if c["nom"] == "alpha")
    assert sorted(l["id"] for l in alpha["agents"]) == ["coord-alpha", "w-alpha-casse", "w-alpha-vif"]
    assert alpha["agents"][0]["id"] == "coord-alpha"  # le coordinateur d'abord
    casse = next(l for l in alpha["agents"] if l["id"] == "w-alpha-casse")
    assert "ton-rouge" in casse["classes"] and casse["etat"] == "arrete" and casse["quoi"][0]["texte"] == "Session disparue"
    assert alpha["termines"] == ["+ 1 worker terminé"] and alpha["alarme"] == "grave"
    # équipe à l'arrêt : atténuée, grise, mot « à l’arrêt » ; la même, avec une alarme, ne l'est plus
    beta = next(c for c in w if c["nom"] == "beta")
    assert "a-l-arret" in beta["classes"] and "ton-gris" in beta["classes"] and beta["statut"] == "à l’arrêt", beta
    assert [l["id"] for l in beta["agents"]] == ["coord-beta"] and beta["termines"] == ["+ 1 worker terminé"]
    assert all("a-l-arret" not in c["classes"] for c in ex["cartes"] if c["nom"] != "cadrage")  # l'exemple n'a pas d'équipe à l'arrêt
    # une équipe sans agent : « aucun agent en cours », 0 tâche, spéciale
    gamma = next(c for c in w if c["nom"] == "gamma")
    assert "aucun agent en cours" in gamma["texte"] and gamma["agents"] == [] and gamma["termines"] == [] and gamma["avance"] == "0 tâche"
    assert "a-l-arret" not in gamma["classes"]  # sans agent, elle n'est pas « à l'arrêt »
    epsilon = next(c for c in w if c["nom"] == "epsilon")  # arrêtée aussi, mais une alarme cite l'équipe
    assert "a-l-arret" not in epsilon["classes"] and epsilon["statut"] != "à l’arrêt" and epsilon["alarme"] == "grave"
    # delta : spéciale, sans session ni alarme → plus de carte, elle passe dans la ligne sous la grille
    assert not any(c["nom"].startswith("delta") for c in w) and "delta (spéciale, sans session)" in r["worker arrete"]["texteOrg"]
    # source en échec : « inconnu », jamais 0
    inc = r["agents inconnus"]
    assert all("agents inconnus" in c["texte"] and c["agents"] == [] and c["termines"] == [] for c in inc["cartes"]), inc["cartes"]
    assert all("a-l-arret" not in c["classes"] for c in inc["cartes"])
    assert "aucun agent en cours" not in inc["texteOrg"] and "workers terminés" not in inc["texteOrg"]
    # états vides
    assert r["sans equipe"]["cartes"] is None and "Aucune équipe pour l’instant." in r["sans equipe"]["texteOrg"]
    assert r["equipes inconnues"]["cartes"] is None and "Équipes : inconnues" in r["equipes inconnues"]["texteOrg"]
    # les clôturées : pas de phrase, un seul lien, avec le compte, dans la ligne sous la grille (et plus au pied de page)
    assert "n’apparaît" not in ex["texteOrg"] and "archives" not in ex["texteOrg"] and ex["texteOrg"].count("clôturée") == 1
    assert ex["texteOrg"].endswith("1 équipe clôturée →"), ex["texteOrg"]
    assert ex["liens"] == 1, ex["liens"]


def verifier_equipe_a_l_arret(dossier_static):
    sonde = dossier_static / "sonde-arret.mjs"
    sonde.write_text(SONDE_PURE, encoding="utf-8")

    def appel(equipe, agents, alarmes):
        res = subprocess.run(["node", str(sonde), str(dossier_static / "commun.js"), json.dumps([equipe, agents, alarmes])], capture_output=True, text=True, timeout=30)
        assert res.returncode == 0, res.stderr
        return json.loads(res.stdout.strip().splitlines()[-1])

    q = _equipe("e")
    coord, ouvrier = _agent("c", "coordinateur", "e"), _agent("w", "worker", "e")
    assert appel(q, [coord, ouvrier], []) is True
    assert appel(q, [coord], []) is True
    assert appel(q, [], []) is False  # sans agent : pas « à l'arrêt »
    assert appel(q, [_agent("c", "coordinateur", "e", "au_repos", True)], []) is False  # en session
    assert appel(q, [coord, _agent("w", "worker", "e", "travaille", True)], []) is False
    assert appel(q, [_agent("c", "coordinateur", "e", "arrete", None)], []) is False  # tmux n'a pas répondu : inconnu, pas arrêté
    assert appel(q, [coord], [_alarme("recouvrement", "grave", [], ["e"])]) is False  # une alarme cite l'équipe
    assert appel(q, [coord, ouvrier], [_alarme("session_disparue", "grave", ["w"], [])]) is False  # une alarme cite un agent
    assert appel(q, [coord], [_alarme("session_disparue", "grave", ["autre"], ["autre-equipe"])]) is True  # une alarme d'ailleurs ne compte pas
    assert appel(q, [coord, _agent("x", "coordinateur", "ailleurs", "travaille", True)], []) is True  # les agents d'une autre équipe ne comptent pas
    assert appel(q, [coord], None) is False  # alarmes inconnues : on ne l'affirme pas
    assert appel(q, None, []) is False
    assert appel({**q, "statut": "bloquee"}, [coord], []) is False and appel({**q, "statut": "terminee"}, [coord], []) is False


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def js():
    fichiers = sorted(STATIC.glob("*.js")) + sorted((STATIC / "vues").glob("*.js")) + [STATIC / f for f in FEUILLES]
    return {str(f.relative_to(STATIC)): f.read_text(encoding="utf-8") for f in fichiers}


def test_organigramme(js):
    verifier_organigramme(js)


def _remplace(fichier, ancien, nouveau):
    def mutation(js):
        assert ancien in js[fichier], ancien
        return {**js, fichier: js[fichier].replace(ancien, nouveau, 1)}
    return mutation


MUTATIONS = {
    # 1. la tête
    "tête sans l'Assistant": _remplace(EN, "noeudUtilisateur(), noeudAssistant())", "noeudUtilisateur())"),
    "Assistant avant l'utilisateur": _remplace(EN, "noeudUtilisateur(), noeudAssistant())", "noeudAssistant(), noeudUtilisateur())"),
    "lien des points perdu": _remplace(EN, "n ? el('a', { class: 'org-utilisateur-attentes', href: '#/' },", "n ? el('span', { class: 'org-utilisateur-attentes' },"),
    "attentes inconnues dites vides": _remplace(EN, "n === null ? 'ce qui t’attend : inconnu' : 'rien ne t’attend'", "'rien ne t’attend'"),
    "état de l'Assistant brut": _remplace(EN, "pastilleEtat(def.cle, def)", "pastilleEtat(a.etat)"),
    "durée de l'état perdue": _remplace(EN, "age(a.etat_depuis, 'court')", "null"),
    "attente de l'Assistant perdue": _remplace(EN, "el('span', { class: 'org-attend' },", "el('span', { class: 'org-attendue' },"),
    "attente en gris": _remplace(CSS, ".org-attend { color: var(--ambre);", ".org-attend { color: var(--secondaire);"),
    "phrase hors de l'ellipse": _remplace(CSS, "overflow: hidden; text-overflow: ellipsis; white-space: nowrap;\n}\n.org-equipes", "}\n.org-equipes"),
    "phrase non italique": _remplace(CSS, "font-style: italic; font-size: 13px;", "font-size: 13px;"),
    "jauge jamais chaude": _remplace(EN, "part > CONTEXTE_CHAUD ? 'oui' : 'non'", "'non'"),
    "jauge large": _remplace(CSS, ".org-jauge i { display: inline-block; width: 56px;", ".org-jauge i { display: inline-block; width: 120px;"),
    "jauge chaude verte": _remplace(CSS, '.org-jauge[data-chaud="oui"] i b { background: var(--ambre); }', '.org-jauge[data-chaud="oui"] i b { background: var(--vert); }'),
    "jauge inconnue dite vide": _remplace(EN, "if (!c || !c.limite) return el('span', { class: 'org-jauge' }, inconnuCourt('contexte', sourceEnEchec(etat, 'transcripts')));",
                                          "if (!c || !c.limite) return el('span', { class: 'org-jauge' });"),
    "Assistant absent muet": _remplace(EN, "inconnu(null, 'Assistant introuvable')", "''"),
    "tête sur deux colonnes égales": _remplace(CSS, ".org-tete {\n  display: grid; grid-template-columns: auto minmax(0, 1fr);", ".org-tete {\n  display: grid; grid-template-columns: 1fr 1fr;"),
    "tête mobile en ligne": _remplace(CSS, "  .org-tete { grid-template-columns: minmax(0, 1fr); }\n", ""),
    # 2. la grille
    "grille à trois colonnes": _remplace(CSS, ".org-equipes { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr));", ".org-equipes { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));"),
    "colonnes qui débordent": _remplace(CSS, ".org-equipes { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr));", ".org-equipes { display: grid; grid-template-columns: repeat(4, 1fr);"),
    "cartes de hauteur libre": _remplace(CSS, "gap: 12px; align-items: stretch; }", "gap: 12px; align-items: start; }"),
    "pied de carte flottant": _remplace(CSS, ".org-termines { margin-top: auto;", ".org-termines { margin-top: 0;"),
    "carte sans colonne": _remplace(CSS, "display: flex; flex-direction: column; gap: 10px; min-width: 0; min-height: 44px;", "display: block; min-width: 0; min-height: 44px;"),
    "carte sans cible tactile": _remplace(CSS, "gap: 10px; min-width: 0; min-height: 44px;", "gap: 10px; min-width: 0;"),
    "deux colonnes perdues": _remplace(CSS, "@media (max-width: 1100px) {\n  .org-equipes { grid-template-columns: repeat(2, minmax(0, 1fr)); }\n}", "@media (max-width: 1100px) {\n}"),
    "une colonne perdue": _remplace(CSS, "  .org-equipes { grid-template-columns: minmax(0, 1fr); }\n", ""),
    "mission sur trois lignes": _remplace(CSS, "display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;\n}\n.org-avance", "display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;\n}\n.org-avance"),
    "mission sans ellipse": _remplace(CSS, "display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;\n}\n.org-avance", "}\n.org-avance"),
    "nom d'équipe en police du texte": _remplace(CSS, ".org-equipe-nom { font-family: var(--mono); font-weight: 600; font-size: 15px;", ".org-equipe-nom { font-weight: 600; font-size: 15px;"),
    "identifiant sans ellipse": _remplace(CSS, ".ag-id { font-family: var(--mono); font-size: 12px; color: var(--texte-doux); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }",
                                          ".ag-id { font-family: var(--mono); font-size: 12px; color: var(--texte-doux); }"),
    "tâche sans ellipse": _remplace(CSS, ".ag-quoi { grid-column: 2 / 4; color: var(--secondaire); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }",
                                    ".ag-quoi { grid-column: 2 / 4; color: var(--secondaire); }"),
    "barre d'avancement rouge": _remplace(CSS, ".org-barre b { display: block; height: 100%; background: var(--vert); }", ".org-barre b { display: block; height: 100%; background: var(--rouge); }"),
    "équipe à l'arrêt non atténuée": _remplace(CSS, ".org-equipe.a-l-arret { opacity: 0.78; }", ".org-equipe.a-l-arret { opacity: 1; }"),
    "ligne d'agent trop large": _remplace(CSS, "grid-template-columns: 14px minmax(0, 1fr) auto; gap: 2px 8px;", "grid-template-columns: 14px 1fr auto; gap: 2px 8px;"),
    # 3. la carte
    "carte qui n'est plus un lien": _remplace(EN, "return el('a', { class: `org-equipe ton-", "return el('section', { class: `org-equipe ton-"),
    "lien vers une autre page": _remplace(EN, "href: routeEquipe(q.nom), dataset", "href: '#/supervision', dataset"),
    "« spéciale » perdue": _remplace(EN, "q.speciale ? el('span', { class: 'org-speciale' }, ' · spéciale') : null", "null"),
    "mission perdue": _remplace(EN, "el('p', { class: 'org-equipe-mission', title: q.mission }, q.mission),\n", ""),
    "avancement avant la mission": _remplace(EN, "    el('p', { class: 'org-equipe-mission', title: q.mission }, q.mission),\n    avancement(q),\n", "    avancement(q),\n    el('p', { class: 'org-equipe-mission', title: q.mission }, q.mission),\n"),
    "« 0 tâche » perdu": _remplace(EN, "el('span', {}, '0 tâche')", "el('span', {}, '0 / 0')"),
    "avancement inconnu muet": _remplace(EN, "inconnu(sourceEnEchec(etat, 'structure'), 'avancement inconnu')", "''"),
    "agents inconnus dits vides": _remplace(EN, "if (!Array.isArray(etat.agents)) return { vivants: null, termines: 0 };", "if (!Array.isArray(etat.agents)) return { vivants: [], termines: 0 };"),
    "agents inconnus muets": _remplace(EN, "inconnu(sourceEnEchec(etat, 'structure'), 'agents inconnus')", "''"),
    "« aucun agent en cours » perdu": _remplace(EN, "el('span', { class: 'discret' }, 'aucun agent en cours')", "null"),
    "terminés listés": _remplace(EN, "const vivants = siens.filter((a) => !termines.includes(a));", "const vivants = siens;"),
    "terminés non comptés": _remplace(EN, "termines ? el('span', { class: 'org-termines' }", "false ? el('span', { class: 'org-termines' }"),
    "terminés comptés à 0": _remplace(EN, "termines ? el('span', { class: 'org-termines' }", "el('span', { class: 'org-termines' }"),
    "pluriel du compte perdu": _remplace(EN, "termines === 1 ? 'worker terminé' : 'workers terminés'", "'workers terminés'"),
    "Détail → revenu": _remplace(EN, "avancement(q),\n    graves.length", "avancement(q), el('a', { class: 'org-detail' }, 'Détail →'),\n    graves.length"),
    "équipe clôturée en grille": _remplace(EN, "q.statut !== 'terminee') : null;", "true) : null;"),
    "équipe sans carte muette": _remplace(EN, "'Aucune équipe pour l’instant.'", "''"),
    "équipes inconnues muettes": _remplace(EN, "'Équipes : ', inconnu(sourceEnEchec(etat, 'structure'), 'inconnues')", "''"),
    "équipe à l'arrêt jamais détectée": _remplace(EN, "const arret = equipeALArret(q, etat.agents, etat.alarmes);", "const arret = false;"),
    "équipe à l'arrêt en vert": _remplace(EN, "const def = arret ? STATUT_EQUIPE_A_L_ARRET : statutEquipeAffiche(q, etat.alarmes);", "const def = statutEquipeAffiche(q, etat.alarmes);"),
    # 4. la ligne d'agent
    "carte d'agent complète revenue": _remplace(EN, "vivants.map((a) => ligneAgent(a, q))", "vivants.map((a) => carteAgent(a, { etat }))"),
    "âge perdu": _remplace(EN, "a.etat_depuis ? age(a.etat_depuis, 'court') : inconnu(null, '?')", "''"),
    "âge inconnu dit 0": _remplace(EN, "a.etat_depuis ? age(a.etat_depuis, 'court') : inconnu(null, '?')", "a.etat_depuis ? age(a.etat_depuis, 'court') : '0 s'"),
    "attente avant l'alarme": _remplace(EN, "  if (alarme) return el('span', { class: `ag-quoi ton-${tonAlarme(alarme)}`, title: alarme.mesure }, TYPES_ALARME[alarme.type] || alarme.type);\n  if (attend) {",
                                        "  if (attend) {"),
    "attente en gris": _remplace(EN, "class: 'ag-quoi ton-ambre' },\n      attend.qui", "class: 'ag-quoi' },\n      attend.qui"),
    "alarme brute": _remplace(EN, "TYPES_ALARME[alarme.type] || alarme.type);\n  if (attend)", "alarme.type);\n  if (attend)"),
    "tâche avant l'attente": _remplace(EN, "  if (alarme) return", "  if (a.tache) return el('span', { class: 'ag-quoi', title: a.tache }, a.tache);\n  if (alarme) return"),
    "tâche perdue": _remplace(EN, "return a.tache ? el('span', { class: 'ag-quoi', title: a.tache }, a.tache) : null;", "return null;"),
    "couleur de l'alarme ignorée": _remplace(CSS, '.ag-quoi[class*="ton-"] { color: var(--ton-texte); }', ".ag-quoi[class*=\"ton-\"] { color: var(--secondaire); }"),
    "clos d'une équipe terminée perdu": _remplace(EN, "defEtatAgent(a, etat.alarmes, { equipeTerminee: q.statut === 'terminee' })", "defEtatAgent(a, etat.alarmes)"),
    "dernier évènement revenu": _remplace(EN, "el('span', { class: 'ag-age' },", "el('span', { class: 'ag-age', title: a.etat_source },"),
    "modèle revenu": _remplace(EN, "    quoiAgent(a));", "    el('span', { class: 'ag-modele' }, a.modele),\n    quoiAgent(a));"),
    # 5. équipes clôturées
    "phrase des clôturées revenue": _remplace(EN, "      : cartes.length ? el('div', { class: 'org-equipes' }", "      : cartes.length ? el('p', {}, 'voir les archives', el('a', { href: '#/archives' }, 'x')) && el('div', { class: 'org-equipes' }"),
    # 6. l'équipe à l'arrêt, la fonction pure
    "équipe bloquée à l'arrêt": _remplace("commun.js", "equipe.statut === 'terminee' || equipe.statut === 'bloquee' ||", "equipe.statut === 'terminee' ||"),
    "alarmes inconnues sans effet": _remplace("commun.js", " || !Array.isArray(alarmes)) return false;\n  const siens", ") return false;\n  const siens"),
    "équipe sans agent à l'arrêt": _remplace("commun.js", "if (!siens.length || !siens.every((a) => etatAffiche(a) === 'arrete')) return false;", "if (!siens.every((a) => etatAffiche(a) === 'arrete')) return false;"),
    "inconnu rangé à l'arrêt": _remplace("commun.js", "siens.every((a) => etatAffiche(a) === 'arrete')", "siens.every((a) => a.etat === 'arrete')"),
    "alarme d'agent ignorée": _remplace("commun.js", " && siens.every((a) => alarmesDe(alarmes, { agent: a.id }).length === 0);", ";"),
    "alarme d'équipe ignorée": _remplace("commun.js", "return alarmesDe(alarmes, { equipe: equipe.nom }).length === 0 && siens", "return siens"),
    "état d'équipe en vert": _remplace("commun.js", "export const STATUT_EQUIPE_A_L_ARRET = { mot: 'à l’arrêt', ton: 'gris' };", "export const STATUT_EQUIPE_A_L_ARRET = { mot: 'à l’arrêt', ton: 'vert' };"),
}


@pytest.mark.parametrize("nom", MUTATIONS)
def test_mutation_detectee(nom, js):
    mutee = MUTATIONS[nom](js)  # hors du raises : la mutation doit s'appliquer, sinon le test serait faux
    with pytest.raises(AssertionError):
        verifier_organigramme(mutee)


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node n'est pas installé : le rendu n'est pas exécuté")


@pytest.fixture
def copie_static(tmp_path):
    cible = tmp_path / "static"
    shutil.copytree(STATIC, cible, ignore=shutil.ignore_patterns("__pycache__"))
    return cible


@needs_node
def test_rendu_execute(copie_static):
    verifier_rendu_organigramme(copie_static)


@needs_node
def test_equipe_a_l_arret_executee(copie_static):
    verifier_equipe_a_l_arret(copie_static)


# mutations qui ne se voient qu'à l'exécution : (fichier, ancien, nouveau, vérification qui doit échouer)
MUTATIONS_EXECUTEES = {
    "les points de l'utilisateur toujours dits": ("vues/ensemble.js", "n ? el('a', { class: 'org-utilisateur-attentes', href: '#/' }", "true ? el('a', { class: 'org-utilisateur-attentes', href: '#/' }", verifier_rendu_organigramme),
    "Assistant : durée en fin d'état perdue": ("vues/ensemble.js", "a.etat_depuis ? el('span', { class: 'org-etat-age' }, age(a.etat_depuis, 'court')) : null", "null", verifier_rendu_organigramme),
    "phrase absente": ("vues/ensemble.js", "a.derniere_phrase ? el('span', { class: 'org-phrase', title: a.derniere_phrase }, a.derniere_phrase) : null", "null", verifier_rendu_organigramme),
    "phrase toujours là": ("vues/ensemble.js", "a.derniere_phrase ? el('span', { class: 'org-phrase'", "true ? el('span', { class: 'org-phrase'", verifier_rendu_organigramme),
    "attente de l'Assistant jamais dite": ("vues/ensemble.js", "attend ? el('span', { class: 'org-attend' },", "false ? el('span', { class: 'org-attend' },", verifier_rendu_organigramme),
    "attente prise pour une demande à l'utilisateur": ("vues/ensemble.js", "attend.qui === 'utilisateur' ? 't’attend ' : `attend ${nomAgent(attend.qui)} `, age(attend.depuis, 'depuis')) : null,\n    jaugeFine",
                                                  "`attend ${nomAgent(attend.qui)} `, age(attend.depuis, 'depuis')) : null,\n    jaugeFine", verifier_rendu_organigramme),
    "ordre des équipes inversé": ("vues/ensemble.js", "cartes.map(blocEquipe)", "[...cartes].reverse().map(blocEquipe)", verifier_rendu_organigramme),
    "mission tronquée en JS": ("vues/ensemble.js", "title: q.mission }, q.mission)", "title: q.mission }, q.mission.slice(0, 20))", verifier_rendu_organigramme),
    "avancement faussé": ("vues/ensemble.js", "`${a.faites} / ${total}`", "`${a.faites} / ${a.faites + a.en_cours}`", verifier_rendu_organigramme),
    "coordinateurs en dernier": ("vues/ensemble.js", "vivants: [...vivants.filter((a) => a.role === 'coordinateur'), ...vivants.filter((a) => a.role !== 'coordinateur')]", "vivants", verifier_rendu_organigramme),
    "worker avec alarme rangé terminé": ("commun.js", "return alarmesDe(alarmes, { agent: agent.id }).length === 0;", "return true;", verifier_rendu_organigramme),
    "équipe sans agent à l'arrêt (rendu)": ("commun.js", "if (!siens.length || !siens.every(", "if (!siens.every(", verifier_rendu_organigramme),
    "équipe à l'arrêt malgré l'alarme": ("commun.js", "return alarmesDe(alarmes, { equipe: equipe.nom }).length === 0 && siens.every((a) => alarmesDe(alarmes, { agent: a.id }).length === 0);", "return true;", verifier_rendu_organigramme),
    "clôturées affichées": ("vues/ensemble.js", "return Array.isArray(etat.equipes) ? etat.equipes.filter((q) => q.statut !== 'terminee') : null;", "return Array.isArray(etat.equipes) ? etat.equipes : null;", verifier_rendu_organigramme),
    "agents inconnus comptés 0": ("vues/ensemble.js", "if (!Array.isArray(etat.agents)) return { vivants: null, termines: 0 };", "if (!Array.isArray(etat.agents)) return { vivants: [], termines: 0 };", verifier_rendu_organigramme),
    "carte sans lien d'équipe": ("vues/ensemble.js", "href: routeEquipe(q.nom), dataset", "dataset", verifier_rendu_organigramme),
    "pluriel perdu": ("vues/ensemble.js", "termines === 1 ? 'worker terminé' : 'workers terminés'", "'workers terminés'", verifier_rendu_organigramme),
    "tâche d'un agent montrée avant son alarme": ("vues/ensemble.js", "  if (alarme) return", "  if (a.tache) return el('span', { class: 'ag-quoi', title: a.tache }, a.tache);\n  if (alarme) return", verifier_rendu_organigramme),
    "équipe bloquée à l'arrêt (pure)": ("commun.js", "equipe.statut === 'terminee' || equipe.statut === 'bloquee' ||", "equipe.statut === 'terminee' ||", verifier_equipe_a_l_arret),
    "équipe sans agent à l'arrêt (pure)": ("commun.js", "if (!siens.length || !siens.every(", "if (!siens.every(", verifier_equipe_a_l_arret),
    "arrêt inconnu accepté": ("commun.js", "etatAffiche(a) === 'arrete')) return false;", "a.etat === 'arrete')) return false;", verifier_equipe_a_l_arret),
    "agents d'une autre équipe comptés": ("commun.js", "const siens = agents.filter((a) => a.equipe === equipe.nom);", "const siens = agents;", verifier_equipe_a_l_arret),
    "alarme d'agent ignorée (pure)": ("commun.js", " && siens.every((a) => alarmesDe(alarmes, { agent: a.id }).length === 0);", ";", verifier_equipe_a_l_arret),
    "alarme d'équipe ignorée (pure)": ("commun.js", "return alarmesDe(alarmes, { equipe: equipe.nom }).length === 0 && siens", "return siens", verifier_equipe_a_l_arret),
    "alarmes inconnues acceptées": ("commun.js", " || !Array.isArray(alarmes)) return false;\n  const siens", ") return false;\n  const siens", verifier_equipe_a_l_arret),
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
    assert toutes == {"verifier_organigramme", "verifier_rendu_organigramme", "verifier_equipe_a_l_arret"} and MUTATIONS and MUTATIONS_EXECUTEES, sorted(toutes)
    assert {v[3] for v in MUTATIONS_EXECUTEES.values()} == {verifier_rendu_organigramme, verifier_equipe_a_l_arret}  # chacune a ses mutations
