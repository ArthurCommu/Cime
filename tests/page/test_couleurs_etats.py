"""Couleurs et états : une couleur = un sens, plus aucun rouge sans alarme grave ni source en échec.

vert = travaille / fait ; ambre = quelqu'un attend ; rouge = un problème et rien d'autre ; bleu = information ; gris = repos, clos.
Même convention que test_toast_et_degrade_mobile.py : analyse de texte du JS et du CSS de static/ (`verifier_couleurs(js)` lève AssertionError,
la table MUTATIONS prouve qu'elle échoue quand on casse chaque comportement), et une vérification exécutée par node
(`verifier_rendu`) : commun.js est chargé avec un DOM minimal, puis rend les cartes d'agents, d'alarmes, les puces d'équipes et le résumé
des effectifs de l'instantané exemple-etat.json ET d'une variante à alarmes graves, et chaque élément rouge doit s'expliquer par
un oracle écrit ici en Python (alarme rouge, agent arrêté cité par une alarme rouge, équipe bloquée par une alarme rouge).
Le mot « pause » est interdit dans les sources de la page (test_page_garde_fous.py, inchangé) : l'agent arrêté sans alarme est donc « à l’arrêt ».
"""
import copy
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

PAGE = Path(__file__).resolve().parents[2] / "src" / "cime" / "page"
STATIC = PAGE / "static"
EXEMPLE = Path(__file__).resolve().parent / "fixtures" / "exemple-etat.json"
NB = " "
ATTENTES = ("autorisation_en_attente", "question_sans_reponse")

# les seules règles de style qui emploient le rouge, et pourquoi
ROUGES_PERMIS = {
    "style.css": {
        '.age-donnee[data-niveau="rouge"]': "état figé",
        '.age-donnee[data-niveau="rouge"] .pouls': "état figé",
        ".capsule-figee": "état figé",
        ".legende-probleme": "légende de la scène : les signes de problème",
        ".injoignable-icone": "hôte injoignable",
        ".injoignable-icone::after": "hôte injoignable",
        ".bouton-danger": "boutons de refus et de clôture",
        ".ton-rouge": "le ton rouge lui-même (variables)",
        '.agent[data-alarme="grave"]': "agent cité par une alarme rouge",
        ".agent-alerte": "alarme rouge ou recouvrement",
        ".rouge": "ligne de nouveautés rouge (alarme rouge, agent arrêté avec alarme rouge)",
        '.org-equipe[data-alarme="grave"]': "équipe citée par une alarme rouge",
        '.graphe-boite[data-alarme="grave"]': "équipe citée par une alarme rouge",
        ".graphe-alerte": "équipe citée par une alarme rouge",
        ".arete.rouge": "recouvrement : même fichier",
        ".fleche-bas.rouge": "recouvrement : même fichier",
        ".fleche-gauche.rouge": "recouvrement : même fichier",
        ".arete-etiquette": "recouvrement : même fichier",
        ".alarme.ton-rouge": "alarme rouge",
        ".toast-rouge": "erreur de toast",
        ".texte-erreur": "erreur de lecture",
    },
    "equipe.css": {
        '.fichier[data-hors="oui"]': "fichier hors du périmètre déclaré",
        '.fichier[data-hors="oui"] .fichier-nom': "fichier hors du périmètre déclaré",
        '.fichier[data-hors="oui"] .fichier-marque': "fichier hors du périmètre déclaré",
        ".perim-alerte": "fichier hors du périmètre déclaré",
    },
    "pages-fil.css": {
        ".journal-ligne.erreur": "action en erreur",
        ".res-erreur": "action en erreur",
    },
}


def _corps(texte, debut, fin):
    i = texte.find(debut)
    assert i >= 0, debut
    j = texte.find(fin, i)
    assert j >= 0, fin
    return texte[i:j]


def _regles_rouges(css):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return {m.group(1).strip() for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css) if "--rouge" in m.group(2) and ":root" not in m.group(1)}


def _declarations(css, selecteur):
    m = re.search(r"(?:^|\n) *" + re.escape(selecteur) + r" \{([^}]*)\}", css)
    assert m, selecteur
    return {k.strip(): v.strip() for k, _, v in (d.partition(":") for d in re.sub(r"/\*.*?\*/", "", m.group(1), flags=re.S).split(";") if d.strip())}


def verifier_couleurs(js):
    commun, rail, ens, equ, fil = js["commun.js"], js["vues/rail.js"], js["vues/ensemble.js"], js["vues/equipe.js"], js["vues/fil.js"]
    css = js["style.css"]
    tout_js = "\n".join(t for n, t in js.items() if n.endswith(".js"))

    # 1. « à l'arrêt » gris, « arrêté » rouge et « clos » gris : trois définitions, et le ton passe par une fonction qui reçoit agent et alarmes
    assert "  arrete: { mot: 'à l’arrêt', ton: 'gris' }," in commun
    assert "export const ETAT_ARRETE_GRAVE = { mot: 'arrêté', ton: 'rouge' };" in commun
    assert "export const ETAT_CLOS = { mot: 'clos', ton: 'gris' };" in commun
    definir = _corps(commun, "export function defEtatAgent(agent, alarmes, { equipeTerminee = false } = {}) {", "\n}\n")
    assert "const cle = etatAffiche(agent);" in definir and "if (cle !== 'arrete') return { cle, ...ETATS_AGENT[cle] };" in definir
    assert "if (equipeTerminee || workerTermine(agent, alarmes)) return { cle, ...ETAT_CLOS };" in definir
    assert "alarmesDe(alarmes, { agent: agent.id }).some(alarmeRouge)" in definir
    assert "grave ? ETAT_ARRETE_GRAVE : ETATS_AGENT.arrete" in definir
    assert commun.count("ETATS_AGENT[") == 3 and "ETATS_AGENT" not in rail + ens + equ  # lue par etatAffiche, defEtatAgent et le défaut de pastilleEtat seulement
    carte = _corps(commun, "export function carteAgent(agent, ctx, options = {})", "const PHRASE_AFFICHEE_MAX")
    assert "defEtatAgent(agent, ctx.etat.alarmes, { equipeTerminee: options.equipeTerminee })" in carte
    assert "pastilleEtat(etatCle, def))," in carte and "class: `agent ton-${def.ton}`" in carte
    ligne = _corps(rail, "function ligneAgent(", "\n}\n")
    assert "defEtatAgent(agent, etat.alarmes, { equipeTerminee: equipeTerminee(agent, etat) })" in ligne and "rail-ligne ton-${def.ton}" in ligne
    detail = _corps(rail, "function detailAgent(", "const dettes")
    assert "defEtatAgent(agent, etat.alarmes, { equipeTerminee: equipeTerminee(agent, etat) })" in detail and "pastilleEtat(def.cle, def)" in rail
    assert "const equipeTerminee = (agent, etat) => (etat.equipes || []).some((q) => q.nom === agent.equipe && q.statut === 'terminee');" in rail
    assert "carteAgent(a, ctx, { detail: true, equipeTerminee: terminee })" in equ  # fiche d'une équipe terminée : ses agents sont clos
    assert ens.count("{ equipeTerminee: q.statut === 'terminee' }") == 1 and "defEtatAgent(a, etat.alarmes, { equipeTerminee: q.statut === 'terminee' })" in ens  # Supervision aussi

    # 2. les effectifs : le point ne passe au rouge que pour un arrêté avec alarme rouge ; « n à l'arrêt » invariable, « n arrêté(s) » accordé
    resume = _corps(commun, "export function resumeAgents(etat)", "function niveauAge")
    assert "const def = defEtatAgent(a, etat.alarmes);" in resume
    assert "def.cle === 'arrete' ? (def.ton === 'rouge' ? 'arrete' : 'a_l_arret') : def.cle" in resume
    assert "const ton = compte.arrete ? 'rouge' : compte.attend ? 'ambre' : 'vert';" in resume
    effectifs = _corps(commun, "export function libelleEffectifs(compte)", "\n}\n")
    assert "n('a_l_arret') ? `${n('a_l_arret')}\\u00A0à l’arrêt` : null," in effectifs
    assert effectifs.index("n('a_l_arret')") < effectifs.index("n('inconnu')") < effectifs.index("n('arrete')")

    # 3. la couleur d'une alarme suit son type, en un seul endroit ; la gravité ne sert qu'à l'ordre
    assert "export const TYPES_ALARME_ATTENTE = ['autorisation_en_attente', 'question_sans_reponse'];" in commun
    ton_alarme = _corps(commun, "export function tonAlarme(alarme) {", "\n}\n")
    assert "if (TYPES_ALARME_ATTENTE.includes(alarme.type)) return 'ambre';" in ton_alarme
    assert "return (GRAVITES[alarme.gravite] || GRAVITES.info).ton;" in ton_alarme
    assert "export const alarmeRouge = (alarme) => tonAlarme(alarme) === 'rouge';" in commun
    assert "  grave: { mot: 'Grave', ton: 'rouge', rang: 0 },\n  a_voir: { mot: 'À voir', ton: 'ambre', rang: 1 },\n  info: { mot: 'Info', ton: 'gris', rang: 2 }," in commun
    assert not re.search(r"GRAVITES\[[^\]]*\]\)?\.ton", tout_js.replace(ton_alarme, ""))  # personne d'autre ne lit le ton de la gravité
    assert "gravite === 'grave')" not in tout_js and "gravite === 'grave').length" not in tout_js  # ni ne compare la gravité pour colorier ou compter les graves
    assert tout_js.count("gravite === 'grave'") == 1 and "a.gravite === 'grave' || a.gravite === 'a_voir'" in rail  # sauf pour choisir les lignes de « Ce qui coince »
    assert "el('article', { class: `alarme ton-${tonAlarme(a)}`, dataset: { gravite: a.gravite } }," in commun
    assert "rail-ligne ton-${tonAlarme(a)}`" in rail
    assert "alarmesDe(ctx.etat.alarmes, { agent: agent.id }).filter(alarmeRouge)" in carte
    assert ens.count("alarmesDe(etat.alarmes, { equipe: q.nom }).filter(alarmeRouge)") == 2  # organigramme et graphe
    assert "const graves = nouvelles.filter(alarmeRouge).length;" in ens
    assert "&& defEtatAgent(a, etat.alarmes).ton === 'rouge');" in ens  # « agents arrêtés » des nouveautés : seulement ceux qui sont un problème
    assert ".alarme.ton-rouge {" in css and ".alarme.ton-ambre {" in css and 'data-gravite="grave"' not in css  # le CSS lit le ton, pas la gravité

    # 4. une équipe bloquée par une seule attente n'est pas rouge
    statut = _corps(commun, "export function statutEquipeAffiche(equipe, alarmes) {", "\n}\n")
    assert "if (equipe.statut !== 'bloquee') return def;" in statut
    assert "alarmes.some((a) => alarmeRouge(a) && (a.equipes || []).includes(equipe.nom))" in statut
    assert "return rouge ? def : { ...def, ton: 'ambre' };" in statut
    assert "puceStatut(q.statut, statutEquipeAffiche(q, etat.alarmes))" in rail and equ.count("puceStatut(q.statut, def)") == 1 and ens.count("puceStatut(q.statut, def)") == 2
    assert "defStatutEquipe(" not in ens + equ + rail  # les vues ne lisent plus le statut brut
    assert ens.count("statutEquipeAffiche(q, etat.alarmes)") == 3

    # 5. la pastille d'en-tête n'a que deux états : En direct (vert) et Figé (rouge) ; plus d'ambre « En retard »
    assert "AGE_DONNEE_AMBRE_MS" not in tout_js and "En retard" not in tout_js and "En retard" not in css
    niveau = _corps(commun, "function niveauAge(ms) {", "\n}\n")
    assert "ambre" not in niveau and "return ms > AGE_DONNEE_ROUGE_MS ? 'rouge' : 'ok';" in niveau
    assert "export const AGE_DONNEE_ROUGE_MS = 30_000;" in commun
    age = _corps(commun, "function rafraichirAgeDonnee(noeud)", "\n}\n")
    assert "const niveau = interrompu ? 'rouge' : niveauAge(ms);" in age and "{ ok: 'En direct', rouge: 'Figé' }[niveau]" in age
    assert 'data-niveau="ambre"' not in css and 'data-niveau="ok"' in css and 'data-niveau="rouge"' in css

    # 6. les boutons : le rouge est réservé au refus et à la clôture ; le principal est clair ; « Accorder » n'est plus rouge
    for m in re.finditer(r"class: '([^']*)'[^\n]*'(Refuser|Clôturer l’équipe|[^']*)'\)", commun):
        if "bouton-danger" in m.group(1):
            assert m.group(2) in ("Refuser", "Clôturer l’équipe"), m.group(0)
    assert commun.count("bouton-danger") == 3
    assert re.search(r"type: 'submit', class: 'bouton bouton-principal' \}, accord\.bouton\)", commun)
    assert re.search(r"type: 'submit', class: 'bouton bouton-danger', disabled: true \}, 'Clôturer l’équipe'\)", commun)
    assert re.search(r"type: 'submit', class: 'bouton bouton-danger', disabled: true \}, 'Refuser'\)", commun)
    principal = _declarations(css, ".bouton-principal")
    assert principal.get("background") == "var(--texte)" and principal.get("color") == "var(--fond)" and principal.get("border-color") == "var(--texte)", principal
    assert "--ambre" not in _declarations(css, ".bouton-principal:hover").get("background", "")
    assert _declarations(css, ".bouton-vert").get("background") == "var(--vert)"

    # 7. le rouge n'est employé que par les règles permises, en CSS comme en JS
    for fichier, permises in ROUGES_PERMIS.items():
        assert _regles_rouges(js[fichier]) <= set(permises), sorted(_regles_rouges(js[fichier]) - set(permises))
    assert tout_js.count("ton: 'rouge'") == 4  # ETAT_ARRETE_GRAVE, bloquee, GRAVITES.grave, FAIL
    assert "ton: 'rouge'" in ens and ens.count("ton: 'rouge'") == 1  # FAIL d'un rapport d'intégration
    assert "toast-${reponse.resultat === 'refuse' ? 'ambre' : 'rouge'}" in commun

    # 8. les valeurs inconnues sont grises, avec leur info-bulle ; le rouge/ambre d'une dégradation est celui du ⚠ de l'en-tête
    assert _declarations(css, ".inconnu").get("color") == "var(--secondaire)" and "rouge" not in "".join(_declarations(css, ".inconnu").values())
    assert "rouge" not in "".join(_declarations(css, ".inconnu-bloc").values())
    assert "{ class: 'inconnu',\n    title: source ? `${mot} inconnu : source ${source} en échec (voir l’en-tête)` : `${mot} inconnu` }, `${mot} ?`" in commun
    assert "el('span', { class: 'inconnu', title: source ? `source en échec : ${source}` : null }," in commun
    assert "color: var(--ambre)" in _corps(css, ".sources-echec {", "}")
    assert _declarations(css, ".agent-session.absente").get("color") == "var(--secondaire)"  # une session absente est un agent à l'arrêt, pas une alarme
    assert "rouge" not in "".join(_declarations(js["pages-fil.css"], ".fil-indispo").values())  # le fil indisponible (registre en échec) est gris
    assert "var(--ambre)" in _declarations(css, ".attend-phrase.tard").get("color", "") and "var(--ambre)" in _declarations(css, ".fil-ligne.attend.tard").get("border-left-color", "")
    assert "border-left-width" in _declarations(js["pages-fil.css"], ".attentes-fil.a-rouge") and "rouge" not in "".join(_declarations(js["pages-fil.css"], ".attentes-fil.a-rouge").values())

    # 9. un « · » n'existe qu'entre deux morceaux présents : un âge absent ne laisse pas de séparateur
    assert "joindre([el('strong', {}, 'Brouillon resté dans le terminal'), age(a.brouillon.depuis, 'depuis')], ' · ')" in equ
    assert "joindre([age(rapport.date), dateCourte(rapport.date)], ' · ')" in ens
    assert not re.search(r"age\([^()]*\),\s*' · '|' · ',\s*age\(", equ + ens + rail.replace("[' · ', age(", ""))
    assert "joindre," in _corps(equ, "import {", "} from '../commun.js'") and "joindre," in _corps(ens, "import {", "} from '../commun.js'")


# ---------------------------------------------------------------------------
# Le rendu exécuté par node
# ---------------------------------------------------------------------------
SONDE = r"""
import { readFileSync, writeFileSync } from 'node:fs';
class Node {}
class Txt extends Node { constructor(t) { super(); this.data = t; } }
class Elt extends Node {
  constructor(tag) { super(); this.tag = tag; this.attrs = {}; this.children = []; this.dataset = {}; }
  setAttribute(k, v) { this.attrs[k] = v; }
  getAttribute(k) { return this.attrs[k] ?? null; }
  addEventListener() {}
  append(...n) { this.children.push(...n); }
  get classes() { return (this.attrs.class || '').split(/\s+/).filter(Boolean); }
}
globalThis.Node = Node;
globalThis.document = { createElement: (t) => new Elt(t), createTextNode: (t) => new Txt(t) };
const commun = await import(process.argv[2]);
const jeux = JSON.parse(readFileSync(process.argv[3], 'utf8'));
const texte = (n) => (n instanceof Txt ? n.data : (n.children || []).map(texte).join(''));
const sous = (n) => (n instanceof Elt ? [n, ...n.children.flatMap(sous)] : []);
const rouges = (racine) => sous(racine).filter((n) => n.classes.includes('ton-rouge') || n.classes.includes('rouge'));
const sortie = {};
for (const [nom, etat] of Object.entries(jeux)) {
  const terminees = new Set(etat.equipes.filter((q) => q.statut === 'terminee').map((q) => q.nom));
  const resume = commun.resumeAgents(etat);
  const agents = etat.agents.filter((a) => a.role !== 'utilisateur').map((a) => {
    const carte = commun.carteAgent(a, { etat }, { equipeTerminee: terminees.has(a.equipe) });
    const pastille = sous(carte).find((n) => n.classes.includes('etat'));
    return { id: a.id, alarme: carte.dataset.alarme ?? null, classes: carte.classes, pastille: pastille.classes, mot: texte(pastille), nRouges: rouges(carte).length };
  });
  const alarmes = etat.alarmes.map((a) => {
    const carte = commun.carteAlarme(a);
    return { type: a.type, gravite: a.gravite, classes: carte.classes, mot: texte(sous(carte).find((n) => n.classes.includes('alarme-gravite'))), nRouges: rouges(carte).length };
  });
  const equipes = etat.equipes.map((q) => {
    const puce = commun.puceStatut(q.statut, commun.statutEquipeAffiche(q, etat.alarmes));
    return { nom: q.nom, classes: puce.classes, mot: texte(puce) };
  });
  const inconnus = [commun.inconnu('tarifs'), commun.inconnuCourt('coût', 'tarifs')].map((n) => ({ classes: n.classes, nRouges: rouges(n).length, title: n.getAttribute('title') }));
  sortie[nom] = {
    effectifs: { classes: resume.classes, texte: texte(resume), pastille: rouges(resume).length },
    agents, alarmes, equipes, inconnus,
    tons: { attentes: commun.TYPES_ALARME_ATTENTE, graves: etat.alarmes.map((a) => commun.tonAlarme(a)) },
    eff: [{}, { a_l_arret: 1 }, { a_l_arret: 3, arrete: 1 }, { travaille: 2, attend: 1, a_l_arret: 2, inconnu: 1, arrete: 2 }].map(commun.libelleEffectifs),
  };
}
console.log(JSON.stringify(sortie));
"""


def _variante(etat):
    """L'instantané exemple, plus quatre coordinateurs arrêtés : sans alarme, avec une attente seule, avec un recouvrement, dans une équipe terminée."""
    v = copy.deepcopy(etat)
    modele = next(a for a in v["agents"] if a["id"] == "coord-fondation")
    for ident, equipe in (("coord-repos", "fondation"), ("coord-attend", "fondation"), ("coord-casse", "verification"), ("coord-ferme", "cadrage")):
        v["agents"].append({**copy.deepcopy(modele), "id": ident, "role": "coordinateur", "equipe": equipe, "etat": "arrete", "vivant": False,
                            "session_tmux": None})
    v["alarmes"].append({"type": "autorisation_en_attente", "gravite": "grave", "agents": ["coord-attend"], "equipes": ["fondation"],
                         "depuis": "2026-10-07T12:00:00.000Z", "mesure": "m", "quoi_faire": "q"})
    v["alarmes"].append({"type": "recouvrement", "gravite": "grave", "agents": ["coord-casse"], "equipes": ["verification"],
                         "depuis": "2026-10-07T12:00:00.000Z", "mesure": "m", "quoi_faire": "q"})
    v["alarmes"].append({"type": "recouvrement", "gravite": "grave", "agents": ["coord-ferme"], "equipes": ["cadrage"],
                         "depuis": "2026-10-07T12:00:00.000Z", "mesure": "m", "quoi_faire": "q"})
    return v


# l'oracle : ce que la page doit dire, calculé ici sans passer par commun.js
def _rouge(alarme):
    return alarme["type"] not in ATTENTES and alarme["gravite"] == "grave"


def _etat_attendu(agent, etat):
    """(mot, ton) d'un agent."""
    if agent["etat"] == "arrete" and agent["vivant"] is None:
        return "inconnu", "gris"
    if agent["etat"] != "arrete":
        return {"travaille": ("travaille", "vert"), "au_repos": ("au repos", "gris"), "attend_autorisation": ("attend une autorisation", "ambre"),
                "attend_reponse": ("attend une réponse", "ambre"), "inconnu": ("inconnu", "gris")}[agent["etat"]]
    citent = [a for a in etat["alarmes"] if agent["id"] in a.get("agents", [])]
    terminee = any(q["nom"] == agent["equipe"] and q["statut"] == "terminee" for q in etat["equipes"])
    if terminee or (agent["role"] == "worker" and not citent):
        return "clos", "gris"
    return ("arrêté", "rouge") if any(_rouge(a) for a in citent) else ("à l’arrêt", "gris")


def _effectifs_attendus(etat):
    terminees = {q["nom"] for q in etat["equipes"] if q["statut"] == "terminee"}
    n = {"travaille": 0, "au_repos": 0, "attend": 0, "a_l_arret": 0, "inconnu": 0, "arrete": 0}
    for a in etat["agents"]:
        if a["role"] == "utilisateur" or a["equipe"] in terminees:
            continue
        mot, ton = _etat_attendu(a, etat)
        if mot == "clos":
            continue
        n["arrete" if mot == "arrêté" else "a_l_arret" if mot == "à l’arrêt" else "travaille" if mot == "travaille" else "au_repos" if mot == "au repos"
          else "inconnu" if mot == "inconnu" else "attend"] += 1
    mot = lambda k, un, pl: f"{k}{NB}{un if k == 1 else pl}"  # noqa: E731
    morceaux = [mot(n["travaille"], "travaille", "travaillent")]
    if n["au_repos"]:
        morceaux.append(mot(n["au_repos"], "au repos", "au repos"))
    if n["attend"]:
        morceaux.append(mot(n["attend"], "attend", "attendent"))
    if n["a_l_arret"]:
        morceaux.append(f"{n['a_l_arret']}{NB}à l’arrêt")
    if n["inconnu"]:
        morceaux.append(mot(n["inconnu"], "inconnu", "inconnus"))
    if n["arrete"]:
        morceaux.append(mot(n["arrete"], "arrêté", "arrêtés"))
    return " · ".join(morceaux), ("rouge" if n["arrete"] else "ambre" if n["attend"] else "vert")


def verifier_rendu(r, jeux):
    for nom, etat in jeux.items():
        rendu = r[nom]
        # les effectifs : le libellé, et le ton du point
        libelle, ton = _effectifs_attendus(etat)
        assert rendu["effectifs"]["texte"] == libelle, (nom, rendu["effectifs"]["texte"], libelle)
        assert f"ton-{ton}" in rendu["effectifs"]["classes"], (nom, rendu["effectifs"]["classes"], ton)
        assert rendu["effectifs"]["pastille"] == (1 if ton == "rouge" else 0), nom  # le point n'est rouge que s'il le faut
        # chaque agent : mot et ton de la pastille, cadre rouge seulement si une alarme rouge le cite
        for a in rendu["agents"]:
            agent = next(x for x in etat["agents"] if x["id"] == a["id"])
            mot, ton = _etat_attendu(agent, etat)
            affiche = "?inconnu" if mot == "inconnu" else mot  # la pastille d'un état inconnu porte un « ? »
            assert a["mot"] == affiche and f"ton-{ton}" in a["pastille"], (nom, a["id"], a["mot"], a["pastille"], mot, ton)
            assert f"ton-{ton}" in a["classes"], (nom, a["id"], a["classes"])
            citent_rouge = any(_rouge(x) for x in etat["alarmes"] if a["id"] in x.get("agents", []))
            assert a["alarme"] == ("grave" if citent_rouge else None), (nom, a["id"], a["alarme"])
            # tout rouge de la carte (pastille, cadre) s'explique : un agent arrêté cité par une alarme rouge, ou une alarme rouge qui le cite
            attendus = (1 if ton == "rouge" else 0)
            assert a["nRouges"] >= attendus and (a["nRouges"] == 0 or ton == "rouge" or citent_rouge), (nom, a["id"], a["nRouges"])
        # chaque alarme : sa couleur suit son type
        for a in rendu["alarmes"]:
            attendue = "ambre" if a["type"] in ATTENTES else {"grave": "rouge", "a_voir": "ambre", "info": "gris"}[a["gravite"]]
            assert f"ton-{attendue}" in a["classes"] and (a["nRouges"] > 0) == (attendue == "rouge"), (nom, a)
            mot = "À trancher" if a["type"] in ATTENTES and a["gravite"] == "grave" else {"grave": "Grave", "a_voir": "À voir", "info": "Info"}[a["gravite"]]
            assert a["mot"] == mot, a  # la gravité reste dite ; une attente grave se lit « À trancher »
        # chaque équipe : « bloquée » n'est rouge que si une alarme rouge la cite ; les autres statuts gardent leur ton
        for q in rendu["equipes"]:
            equipe = next(x for x in etat["equipes"] if x["nom"] == q["nom"])
            if equipe["statut"] == "bloquee":
                attendu = "rouge" if any(_rouge(x) and q["nom"] in x.get("equipes", []) for x in etat["alarmes"]) else "ambre"
            else:
                attendu = {"active": "vert", "au_repos": "gris", "terminee": "bleu"}[equipe["statut"]]
            assert f"ton-{attendu}" in q["classes"], (nom, q)
        # les valeurs inconnues : grises, avec leur info-bulle
        for i in rendu["inconnus"]:
            assert "inconnu" in i["classes"] and i["nRouges"] == 0 and i["title"] and "tarifs" in i["title"], i
        # les libellés d'effectifs exécutés
        assert rendu["eff"] == [f"0{NB}travaillent", f"0{NB}travaillent · 1{NB}à l’arrêt", f"0{NB}travaillent · 3{NB}à l’arrêt · 1{NB}arrêté",
                                f"2{NB}travaillent · 1{NB}attend · 2{NB}à l’arrêt · 1{NB}inconnu · 2{NB}arrêtés"], rendu["eff"]
        assert rendu["tons"]["attentes"] == list(ATTENTES), rendu["tons"]

    # les faits qui rendent le critère non vide : l'exemple a un arrêté rouge, des attentes graves ambres, une équipe bloquée ambre
    exemple, variante = r["exemple"], r["variante"]
    ids = {a["id"]: a for a in exemple["agents"]}
    assert ids["worker-observation-git"]["mot"] == "arrêté" and "ton-rouge" in ids["worker-observation-git"]["pastille"]
    assert ids["worker-hote-schema"]["mot"] == "clos" and ids["coord-cadrage"]["mot"] == "clos"
    assert ids["coord-page"]["alarme"] is None and "ton-ambre" in ids["coord-page"]["pastille"]  # autorisation en attente grave : ambre
    assert [q["classes"] for q in exemple["equipes"] if q["nom"] == "page"][0].count("ton-ambre") == 1  # bloquée par une attente, pas rouge
    assert all("ton-rouge" in [q["classes"] for q in exemple["equipes"] if q["nom"] == n][0] for n in ("observation", "hote"))
    vids = {a["id"]: a for a in variante["agents"]}
    assert vids["coord-repos"]["mot"] == "à l’arrêt" and "ton-gris" in vids["coord-repos"]["pastille"]
    assert vids["coord-attend"]["mot"] == "à l’arrêt" and vids["coord-attend"]["alarme"] is None
    assert vids["coord-casse"]["mot"] == "arrêté" and vids["coord-casse"]["alarme"] == "grave"
    assert vids["coord-ferme"]["mot"] == "clos" and "ton-gris" in vids["coord-ferme"]["pastille"]  # équipe terminée : clos même cité par une alarme rouge
    assert "à l’arrêt" in variante["effectifs"]["texte"] and "arrêté" in variante["effectifs"]["texte"]


def _jeux():
    etat = json.loads(EXEMPLE.read_text(encoding="utf-8"))
    return {"exemple": etat, "variante": _variante(etat)}


def executer(dossier_static, jeux):
    sonde = dossier_static / "sonde-couleurs.mjs"
    sonde.write_text(SONDE, encoding="utf-8")
    donnees = dossier_static / "jeux-couleurs.json"
    donnees.write_text(json.dumps(jeux), encoding="utf-8")
    res = subprocess.run(["node", str(sonde), str(dossier_static / "commun.js"), str(donnees)], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


def verifier_fonctions_rendues(dossier_static):
    jeux = _jeux()
    verifier_rendu(executer(dossier_static, jeux), jeux)


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def js():
    fichiers = sorted(STATIC.glob("*.js")) + sorted((STATIC / "vues").glob("*.js")) + sorted(STATIC.glob("*.css"))
    return {str(f.relative_to(STATIC)): f.read_text(encoding="utf-8") for f in fichiers}


def test_couleurs_etats(js):
    verifier_couleurs(js)


def _remplace(fichier, ancien, nouveau):
    def mutation(js):
        assert ancien in js[fichier], ancien
        return {**js, fichier: js[fichier].replace(ancien, nouveau)}
    return mutation


COM, RA, EN, EQ, CSS, PFC = "commun.js", "vues/rail.js", "vues/ensemble.js", "vues/equipe.js", "style.css", "pages-fil.css"
MUTATIONS = {
    # 1. à l'arrêt, arrêté, clos
    "arrêté sans alarme encore rouge": _remplace(COM, "arrete: { mot: 'à l’arrêt', ton: 'gris' }", "arrete: { mot: 'arrêté', ton: 'rouge' }"),
    "à l'arrêt en ambre": _remplace(COM, "arrete: { mot: 'à l’arrêt', ton: 'gris' }", "arrete: { mot: 'à l’arrêt', ton: 'ambre' }"),
    "mot « pause » (interdit par le garde-fou)": _remplace(COM, "arrete: { mot: 'à l’arrêt', ton: 'gris' }", "arrete: { mot: 'en pause', ton: 'gris' }"),
    "arrêté avec alarme en gris": _remplace(COM, "ETAT_ARRETE_GRAVE = { mot: 'arrêté', ton: 'rouge' }", "ETAT_ARRETE_GRAVE = { mot: 'arrêté', ton: 'gris' }"),
    "clos en rouge": _remplace(COM, "ETAT_CLOS = { mot: 'clos', ton: 'gris' }", "ETAT_CLOS = { mot: 'clos', ton: 'rouge' }"),
    "clos dit arrêté": _remplace(COM, "ETAT_CLOS = { mot: 'clos', ton: 'gris' }", "ETAT_CLOS = { mot: 'arrêté', ton: 'gris' }"),
    "équipe terminée oubliée": _remplace(COM, "if (equipeTerminee || workerTermine(agent, alarmes))", "if (workerTermine(agent, alarmes))"),
    "worker terminé oublié": _remplace(COM, "if (equipeTerminee || workerTermine(agent, alarmes))", "if (equipeTerminee)"),
    "toute alarme rend rouge": _remplace(COM, "alarmesDe(alarmes, { agent: agent.id }).some(alarmeRouge)", "alarmesDe(alarmes, { agent: agent.id }).length > 0"),
    "gravité seule rend rouge": _remplace(COM, "alarmesDe(alarmes, { agent: agent.id }).some(alarmeRouge)", "alarmesDe(alarmes, { agent: agent.id }).some((a) => a.gravite === 'grave')"),
    "états non arrêtés recalculés": _remplace(COM, "if (cle !== 'arrete') return { cle, ...ETATS_AGENT[cle] };", "if (cle !== 'arrete') return { cle, ...ETAT_CLOS };"),
    "carte d'agent lit la table": _remplace(COM, "const def = defEtatAgent(agent, ctx.etat.alarmes, { equipeTerminee: options.equipeTerminee });", "const def = { cle: etatAffiche(agent), ...ETATS_AGENT[etatAffiche(agent)] };"),
    "carte sans équipe terminée": _remplace(COM, "{ equipeTerminee: options.equipeTerminee })", "{})"),
    "pastille sans le mot calculé": _remplace(COM, "pastilleEtat(etatCle, def)),", "pastilleEtat(etatCle)),"),
    "ligne du rail lit la table": _remplace(RA, "const def = defEtatAgent(agent, etat.alarmes, { equipeTerminee: equipeTerminee(agent, etat) });\n  const quoi", "const def = ETATS_AGENT[etatAffiche(agent)];\n  const quoi"),
    "ligne du rail sans équipe terminée": _remplace(RA, "function ligneAgent(agent, etat, ouvrir, { avecEtat = false } = {}) {\n  const def = defEtatAgent(agent, etat.alarmes, { equipeTerminee: equipeTerminee(agent, etat) });", "function ligneAgent(agent, etat, ouvrir, { avecEtat = false } = {}) {\n  const def = defEtatAgent(agent, etat.alarmes);"),
    "détail d'agent sans alarmes": _remplace(RA, "function detailAgent(agent, etat) {\n  const def = defEtatAgent(agent, etat.alarmes, { equipeTerminee: equipeTerminee(agent, etat) });", "function detailAgent(agent, etat) {\n  const def = defEtatAgent(agent, [], { equipeTerminee: equipeTerminee(agent, etat) });"),
    "équipe terminée jamais reconnue": _remplace(RA, "q.nom === agent.equipe && q.statut === 'terminee'", "q.nom === agent.equipe && q.statut === 'active'"),
    "fiche d'équipe terminée sans clos": _remplace(EQ, "carteAgent(a, ctx, { detail: true, equipeTerminee: terminee })", "carteAgent(a, ctx, { detail: true })"),
    "Supervision sans clos (lignes d'agent)": _remplace(EN, "defEtatAgent(a, etat.alarmes, { equipeTerminee: q.statut === 'terminee' })", "defEtatAgent(a, etat.alarmes)"),
    # 2. effectifs
    "effectifs : point rouge dès un arrêt": _remplace(COM, "def.ton === 'rouge' ? 'arrete' : 'a_l_arret'", "'arrete'"),
    "effectifs : arrêt avec alarme compté à l'arrêt": _remplace(COM, "def.ton === 'rouge' ? 'arrete' : 'a_l_arret'", "'a_l_arret'"),
    "effectifs : point jamais rouge": _remplace(COM, "const ton = compte.arrete ? 'rouge' : compte.attend", "const ton = compte.attend"),
    "effectifs : point rouge à l'arrêt": _remplace(COM, "const ton = compte.arrete ? 'rouge' : compte.attend", "const ton = compte.arrete || compte.a_l_arret ? 'rouge' : compte.attend"),
    "effectifs : ambre oublié": _remplace(COM, "compte.attend ? 'ambre' : 'vert'", "'vert'"),
    "effectifs : état calculé sans alarmes": _remplace(COM, "const def = defEtatAgent(a, etat.alarmes);", "const def = defEtatAgent(a, []);"),
    "effectifs : « à l'arrêt » accordé": _remplace(COM, "`${n('a_l_arret')}\\u00A0à l’arrêt`", "`${n('a_l_arret')}\\u00A0à l’arrêt${n('a_l_arret') > 1 ? 's' : ''}`"),
    "effectifs : espace ordinaire": _remplace(COM, "`${n('a_l_arret')}\\u00A0à l’arrêt`", "`${n('a_l_arret')} à l’arrêt`"),
    "effectifs : « à l'arrêt » dit à zéro": _remplace(COM, "n('a_l_arret') ? `${n('a_l_arret')}\\u00A0à l’arrêt` : null", "`${n('a_l_arret')}\\u00A0à l’arrêt`"),
    "effectifs : « à l'arrêt » après les inconnus": _remplace(COM, "    n('a_l_arret') ? `${n('a_l_arret')}\\u00A0à l’arrêt` : null,\n    n('inconnu') ? mot(n('inconnu'), 'inconnu', 'inconnus') : null,", "    n('inconnu') ? mot(n('inconnu'), 'inconnu', 'inconnus') : null,\n    n('a_l_arret') ? `${n('a_l_arret')}\\u00A0à l’arrêt` : null,"),
    # 3. la couleur d'une alarme suit son type
    "autorisation en attente rouge": _remplace(COM, "['autorisation_en_attente', 'question_sans_reponse']", "['question_sans_reponse']"),
    "question sans réponse rouge": _remplace(COM, "['autorisation_en_attente', 'question_sans_reponse']", "['autorisation_en_attente']"),
    "attentes ambres oubliées": _remplace(COM, "  if (TYPES_ALARME_ATTENTE.includes(alarme.type)) return 'ambre';\n", ""),
    "attentes grises": _remplace(COM, "if (TYPES_ALARME_ATTENTE.includes(alarme.type)) return 'ambre';", "if (TYPES_ALARME_ATTENTE.includes(alarme.type)) return 'gris';"),
    "alarme grave en ambre": _remplace(COM, "  grave: { mot: 'Grave', ton: 'rouge', rang: 0 },", "  grave: { mot: 'Grave', ton: 'ambre', rang: 0 },"),
    "alarme à voir en rouge": _remplace(COM, "a_voir: { mot: 'À voir', ton: 'ambre', rang: 1 }", "a_voir: { mot: 'À voir', ton: 'rouge', rang: 1 }"),
    "alarme rouge selon la gravité": _remplace(COM, "export const alarmeRouge = (alarme) => tonAlarme(alarme) === 'rouge';", "export const alarmeRouge = (alarme) => alarme.gravite === 'grave';"),
    "carte d'alarme selon la gravité": _remplace(COM, "class: `alarme ton-${tonAlarme(a)}`", "class: `alarme ton-${g.ton}`"),
    "rail : « Ce qui coince » selon la gravité": _remplace(RA, "rail-ligne ton-${tonAlarme(a)}`", "rail-ligne ton-${GRAVITES[a.gravite].ton}`"),
    "cadre d'agent selon la gravité": _remplace(COM, "alarmesDe(ctx.etat.alarmes, { agent: agent.id }).filter(alarmeRouge)", "alarmesDe(ctx.etat.alarmes, { agent: agent.id }).filter((a) => a.gravite === 'grave')"),
    "cadre d'équipe selon la gravité (organigramme)": _remplace(EN, "  const graves = alarmesDe(etat.alarmes, { equipe: q.nom }).filter(alarmeRouge);\n  const arret", "  const graves = alarmesDe(etat.alarmes, { equipe: q.nom }).filter((a) => a.gravite === 'grave');\n  const arret"),
    "cadre d'équipe selon la gravité (graphe)": _remplace(EN, "  const graves = alarmesDe(etat.alarmes, { equipe: q.nom }).filter(alarmeRouge);\n  const def = statutEquipeAffiche(q, etat.alarmes);\n  const ton = def.ton;\n  const a = q.avancement;", "  const graves = alarmesDe(etat.alarmes, { equipe: q.nom }).filter((a) => a.gravite === 'grave');\n  const def = statutEquipeAffiche(q, etat.alarmes);\n  const ton = def.ton;\n  const a = q.avancement;"),
    "nouveautés : graves selon la gravité": _remplace(EN, "nouvelles.filter(alarmeRouge).length", "nouvelles.filter((a) => a.gravite === 'grave').length"),
    "nouveautés : tout arrêté en rouge": _remplace(EN, "&& defEtatAgent(a, etat.alarmes).ton === 'rouge');", "&& !workerTermine(a, etat.alarmes));"),
    "CSS d'alarme lit la gravité": _remplace(CSS, ".alarme.ton-rouge {", '.alarme[data-gravite="grave"] {'),
    "CSS d'alarme ambre perdu": _remplace(CSS, ".alarme.ton-ambre {", ".alarme.ton-x {"),
    # 4. équipes bloquées
    "bloquée toujours rouge": _remplace(COM, "return rouge ? def : { ...def, ton: 'ambre' };", "return def;"),
    "bloquée toujours ambre": _remplace(COM, "return rouge ? def : { ...def, ton: 'ambre' };", "return { ...def, ton: 'ambre' };"),
    "bloquée : gravité au lieu du type": _remplace(COM, "alarmes.some((a) => alarmeRouge(a) && (a.equipes", "alarmes.some((a) => a.gravite === 'grave' && (a.equipes"),
    "bloquée : n'importe quelle équipe": _remplace(COM, "alarmeRouge(a) && (a.equipes || []).includes(equipe.nom)", "alarmeRouge(a)"),
    "autres statuts changés": _remplace(COM, "if (equipe.statut !== 'bloquee') return def;", "if (equipe.statut === 'active') return def;"),
    "rail : puce de l'équipe brute": _remplace(RA, "puceStatut(q.statut, statutEquipeAffiche(q, etat.alarmes))", "puceStatut(q.statut)"),
    "fiche d'équipe : puce brute": _remplace(EQ, "      puceStatut(q.statut, def),", "      puceStatut(q.statut),"),
    "organigramme : puce brute": _remplace(EN, "      puceStatut(q.statut, def)),\n    el('p', { class: 'org-equipe-mission'", "      puceStatut(q.statut)),\n    el('p', { class: 'org-equipe-mission'"),
    "graphe : statut brut": _remplace(EN, "el('span', { class: 'graphe-statut' }, def.mot,", "el('span', { class: 'graphe-statut' }, defStatutEquipe(q.statut).mot,"),
    # 5. la pastille d'en-tête
    "« En retard » revenu": _remplace(COM, "{ ok: 'En direct', rouge: 'Figé' }[niveau]", "{ ok: 'En direct', ambre: 'En retard', rouge: 'Figé' }[niveau]"),
    "niveau ambre revenu": _remplace(COM, "return ms > AGE_DONNEE_ROUGE_MS ? 'rouge' : 'ok';", "return ms > AGE_DONNEE_ROUGE_MS ? 'rouge' : ms > 15_000 ? 'ambre' : 'ok';"),
    "constante ambre revenue": _remplace(COM, "export const AGE_DONNEE_ROUGE_MS = 30_000;", "export const AGE_DONNEE_AMBRE_MS = 15_000;\nexport const AGE_DONNEE_ROUGE_MS = 30_000;"),
    "seuil du figé déplacé": _remplace(COM, "export const AGE_DONNEE_ROUGE_MS = 30_000;", "export const AGE_DONNEE_ROUGE_MS = 15_000;"),
    "flux interrompu plus figé": _remplace(COM, "const niveau = interrompu ? 'rouge' : niveauAge(ms);", "const niveau = niveauAge(ms);"),
    "CSS ambre de la pastille revenu": _remplace(CSS, '.age-donnee[data-niveau="rouge"] { color', '.age-donnee[data-niveau="ambre"] { color: var(--ambre); }\n.age-donnee[data-niveau="rouge"] { color'),
    # 6. boutons
    "Accorder rouge": _remplace(COM, "class: 'bouton bouton-principal' }, accord.bouton)", "class: 'bouton bouton-danger' }, accord.bouton)"),
    "Accorder neutre": _remplace(COM, "class: 'bouton bouton-principal' }, accord.bouton)", "class: 'bouton' }, accord.bouton)"),
    "autre bouton rouge": _remplace(COM, "class: 'bouton bouton-principal', disabled: true }, 'Trancher')", "class: 'bouton bouton-danger', disabled: true }, 'Trancher')"),
    "Refuser plus rouge": _remplace(COM, "class: 'bouton bouton-danger', disabled: true }, 'Refuser')", "class: 'bouton bouton-principal', disabled: true }, 'Refuser')"),
    "Clôturer plus rouge": _remplace(COM, "class: 'bouton bouton-danger', disabled: true }, 'Clôturer l’équipe')", "class: 'bouton bouton-principal', disabled: true }, 'Clôturer l’équipe')"),
    "principal encore ambre": _remplace(CSS, ".bouton-principal { background: var(--texte); color: var(--fond); border-color: var(--texte);", ".bouton-principal { background: var(--ambre); color: var(--fond); border-color: var(--ambre);"),
    "principal à texte clair": _remplace(CSS, ".bouton-principal { background: var(--texte); color: var(--fond);", ".bouton-principal { background: var(--texte); color: var(--texte);"),
    "principal au survol ambre": _remplace(CSS, ".bouton-principal:hover { background: var(--texte-doux);", ".bouton-principal:hover { background: var(--ambre);"),
    "vert changé": _remplace(CSS, ".bouton-vert { background: var(--vert);", ".bouton-vert { background: var(--ambre);"),
    # 7. le rouge ailleurs
    "nouvelle règle rouge": _remplace(CSS, ".agent-attend { font-size: 12px; color: var(--ambre); }", ".agent-attend { font-size: 12px; color: var(--rouge-clair); }"),
    "retard d'attente rouge": _remplace(CSS, ".attend-phrase.tard { color: var(--ambre); font-weight: 600; }", ".attend-phrase.tard { color: var(--rouge-clair); }"),
    "ligne de fil en retard rouge": _remplace(CSS, ".fil-ligne.attend.tard { border-left-color: var(--ambre); border-left-width: 4px; }", ".fil-ligne.attend.tard { border-left-color: var(--rouge); }"),
    "attentes du fil rouges": _remplace(PFC, ".attentes-fil.a-rouge { border-left-width: 5px; }", ".attentes-fil.a-rouge { border-left-color: var(--rouge); }"),
    "ton rouge ajouté": _remplace(EN, "FAIL: { mot: 'FAIL', ton: 'rouge' } }", "FAIL: { mot: 'FAIL', ton: 'rouge' }, WARN: { mot: 'WARN', ton: 'rouge' } }"),
    "toast d'erreur plus rouge": _remplace(COM, "'ambre' : 'rouge'}` }, phraseEchec", "'ambre' : 'ambre'}` }, phraseEchec"),
    # 8. inconnus et sources en échec
    "inconnu en rouge": _remplace(CSS, ".inconnu {\n  color: var(--secondaire);", ".inconnu {\n  color: var(--rouge-clair);"),
    "bloc inconnu en rouge": _remplace(CSS, ".inconnu-bloc {\n  background: var(--carte); border: 1px dashed var(--bord-fort);", ".inconnu-bloc {\n  background: var(--carte); border: 1px dashed var(--rouge);"),
    "inconnu court sans info-bulle": _remplace(COM, "title: source ? `${mot} inconnu : source ${source} en échec (voir l’en-tête)` : `${mot} inconnu` }", "title: null }"),
    "inconnu sans info-bulle": _remplace(COM, "title: source ? `source en échec : ${source}` : null }", "title: null }"),
    "⚠ plus ambre": _remplace(CSS, "background: transparent; color: var(--ambre);\n  border: 1px solid var(--ambre-bord)", "background: transparent; color: var(--texte);\n  border: 1px solid var(--ambre-bord)"),
    "session absente rouge": _remplace(CSS, ".agent-session.absente { color: var(--secondaire); }", ".agent-session.absente { color: var(--rouge-clair); }"),
    "fil indisponible rouge": _remplace(PFC, "border: 1px dashed var(--bord-fort);\n  border-radius: var(--rayon); background: var(--carte); color: var(--secondaire);", "border: 1px solid var(--rouge-bord);\n  border-radius: var(--rayon); background: var(--rouge-fond); color: var(--rouge-clair);"),
    # 9. séparateurs
    "brouillon : âge sans joindre": _remplace(EQ, "joindre([el('strong', {}, 'Brouillon resté dans le terminal'), age(a.brouillon.depuis, 'depuis')], ' · ')", "el('strong', {}, 'Brouillon resté dans le terminal'), ' · ', age(a.brouillon.depuis, 'depuis')"),
    "rapport : date sans joindre": _remplace(EN, "joindre([age(rapport.date), dateCourte(rapport.date)], ' · ')", "[age(rapport.date), ' · ', dateCourte(rapport.date)]"),
    "joindre non importé (fiche)": _remplace(EQ, "mesurerLargeur, joindre, statutEquipeAffiche,", "mesurerLargeur, statutEquipeAffiche,"),
}

# rendu exécuté : mutations de commun.js qui doivent changer ce que node voit
MUTATIONS_EXECUTEES = {
    "arrêté sans alarme rouge": ("arrete: { mot: 'à l’arrêt', ton: 'gris' }", "arrete: { mot: 'à l’arrêt', ton: 'rouge' }"),
    "arrêté sans alarme dit arrêté": ("arrete: { mot: 'à l’arrêt', ton: 'gris' }", "arrete: { mot: 'arrêté', ton: 'gris' }"),
    "arrêté avec alarme gris": ("ETAT_ARRETE_GRAVE = { mot: 'arrêté', ton: 'rouge' }", "ETAT_ARRETE_GRAVE = { mot: 'arrêté', ton: 'gris' }"),
    "équipe terminée oubliée": ("if (equipeTerminee || workerTermine(agent, alarmes))", "if (workerTermine(agent, alarmes))"),
    "worker terminé rouge": ("if (equipeTerminee || workerTermine(agent, alarmes))", "if (equipeTerminee)"),
    "toute alarme rend rouge": ("alarmesDe(alarmes, { agent: agent.id }).some(alarmeRouge)", "alarmesDe(alarmes, { agent: agent.id }).length > 0"),
    "gravité rend rouge": ("alarmesDe(alarmes, { agent: agent.id }).some(alarmeRouge)", "alarmesDe(alarmes, { agent: agent.id }).some((a) => a.gravite === 'grave')"),
    "autorisation rouge": ("['autorisation_en_attente', 'question_sans_reponse']", "['question_sans_reponse']"),
    "question rouge": ("['autorisation_en_attente', 'question_sans_reponse']", "['autorisation_en_attente']"),
    "attentes plus ambres": ("  if (TYPES_ALARME_ATTENTE.includes(alarme.type)) return 'ambre';\n", ""),
    "alarme grave ambre": ("  grave: { mot: 'Grave', ton: 'rouge', rang: 0 },", "  grave: { mot: 'Grave', ton: 'ambre', rang: 0 },"),
    "alarme à voir rouge": ("a_voir: { mot: 'À voir', ton: 'ambre', rang: 1 }", "a_voir: { mot: 'À voir', ton: 'rouge', rang: 1 }"),
    "alarmeRouge par la gravité": ("export const alarmeRouge = (alarme) => tonAlarme(alarme) === 'rouge';", "export const alarmeRouge = (alarme) => alarme.gravite === 'grave';"),
    "carte d'alarme par la gravité": ("class: `alarme ton-${tonAlarme(a)}`", "class: `alarme ton-${g.ton}`"),
    "cadre d'agent par la gravité": ("alarmesDe(ctx.etat.alarmes, { agent: agent.id }).filter(alarmeRouge)", "alarmesDe(ctx.etat.alarmes, { agent: agent.id }).filter((a) => a.gravite === 'grave')"),
    "carte d'agent sans équipe terminée": ("{ equipeTerminee: options.equipeTerminee })", "{})"),
    "effectifs : arrêt sans alarme en rouge": ("def.ton === 'rouge' ? 'arrete' : 'a_l_arret'", "'arrete'"),
    "effectifs : point jamais rouge": ("const ton = compte.arrete ? 'rouge' : compte.attend", "const ton = compte.attend"),
    "effectifs : sans alarmes": ("const def = defEtatAgent(a, etat.alarmes);", "const def = defEtatAgent(a, []);"),
    "effectifs : « à l'arrêt » accordé": ("`${n('a_l_arret')}\\u00A0à l’arrêt`", "`${n('a_l_arret')}\\u00A0à l’arrêt${n('a_l_arret') > 1 ? 's' : ''}`"),
    "effectifs : zéro à l'arrêt dit": ("n('a_l_arret') ? `${n('a_l_arret')}\\u00A0à l’arrêt` : null", "`${n('a_l_arret')}\\u00A0à l’arrêt`"),
    "bloquée toujours rouge": ("return rouge ? def : { ...def, ton: 'ambre' };", "return def;"),
    "bloquée toujours ambre": ("return rouge ? def : { ...def, ton: 'ambre' };", "return { ...def, ton: 'ambre' };"),
    "bloquée par n'importe quelle alarme rouge": ("alarmeRouge(a) && (a.equipes || []).includes(equipe.nom)", "alarmeRouge(a)"),
    "bloquée par la gravité": ("alarmes.some((a) => alarmeRouge(a) && (a.equipes", "alarmes.some((a) => a.gravite === 'grave' && (a.equipes"),
    "inconnu rougi": ("return el('span', { class: 'inconnu',\n    title", "return el('span', { class: 'inconnu ton-rouge',\n    title"),
    "inconnu sans info-bulle": ("title: source ? `source en échec : ${source}` : null }", "title: null }"),
}

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node n'est pas installé : le rendu des couleurs n'est pas exécuté")


@pytest.mark.parametrize("nom", MUTATIONS)
def test_mutation_detectee(nom, js):
    mutee = MUTATIONS[nom](js)  # hors du raises : la mutation doit s'appliquer, sinon le test serait faux
    with pytest.raises(AssertionError):
        verifier_couleurs(mutee)


@pytest.fixture
def copie_static(tmp_path):
    cible = tmp_path / "static"
    shutil.copytree(STATIC, cible, ignore=shutil.ignore_patterns("__pycache__"))
    return cible


@needs_node
def test_rendu_execute(copie_static):
    verifier_fonctions_rendues(copie_static)


@needs_node
@pytest.mark.parametrize("nom", MUTATIONS_EXECUTEES)
def test_mutation_executee_detectee(nom, copie_static):
    ancien, nouveau = MUTATIONS_EXECUTEES[nom]
    fichier = copie_static / "commun.js"
    texte = fichier.read_text(encoding="utf-8")
    assert ancien in texte, ancien  # la mutation doit s'appliquer
    fichier.write_text(texte.replace(ancien, nouveau), encoding="utf-8")
    with pytest.raises(AssertionError):
        verifier_fonctions_rendues(copie_static)


def test_couverture_des_verifications():
    toutes = {n for n, v in globals().items() if n.startswith("verifier_") and callable(v)}
    assert toutes == {"verifier_couleurs", "verifier_rendu", "verifier_fonctions_rendues"} and MUTATIONS and MUTATIONS_EXECUTEES, sorted(toutes)
