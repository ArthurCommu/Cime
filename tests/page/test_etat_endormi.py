"""Un coordinateur endormi : son propre état, gris, jamais une alarme ni un arrêt.

Sa session est fermée volontairement et rouverte au prochain message : il n'a pas de terminal à montrer, et aucune
pastille, aucun effectif, aucune équipe ne doit le faire passer pour un problème. Les vérifications sont exécutées par node
(commun.js chargé avec un DOM minimal, comme dans test_couleurs_etats.py) sur l'instantané exemple et sur quatre variantes.

Chaque comportement est une vérification nommée ; la table MUTATIONS casse le code une fois par comportement et prouve
que la vérification visée échoue (et que le code d'origine passe).
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

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node n'est pas installé : le rendu n'est pas exécuté")

SONDE = r"""
import { readFileSync } from 'node:fs';
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
const cas = JSON.parse(readFileSync(process.argv[3], 'utf8'));
const texte = (n) => (n instanceof Txt ? n.data : (n.children || []).map(texte).join(''));
const sous = (n) => (n instanceof Elt ? [n, ...n.children.flatMap(sous)] : []);
const sortie = {};
for (const [nom, etat] of Object.entries(cas)) {
  const agents = {};
  for (const a of etat.agents) agents[a.id] = { etat: commun.etatAffiche(a), def: commun.defEtatAgent(a, etat.alarmes) };
  const resume = commun.resumeAgents(etat);
  const equipes = {};
  for (const q of etat.equipes) equipes[q.nom] = commun.equipeALArret(q, etat.agents, etat.alarmes);
  const cartes = {};
  for (const a of etat.agents.filter((x) => x.role !== 'utilisateur')) {
    const carte = commun.carteAgent(a, { etat }, {});
    cartes[a.id] = { classes: sous(carte).flatMap((n) => n.classes), texte: texte(carte) };
  }
  sortie[nom] = { agents, resume: { texte: texte(resume), classes: resume.classes }, equipes, cartes };
}
console.log(JSON.stringify(sortie));
"""

ENDORMI = "coord-livraison"


def _jeux():
    v = json.loads(EXEMPLE.read_text(encoding="utf-8"))
    seul = copy.deepcopy(v)  # un endormi, et rien d'autre
    seul["agents"] = [a for a in seul["agents"] if a["id"] == ENDORMI]
    seul["alarmes"] = []
    deux = copy.deepcopy(seul)  # un second endormi, dans une autre équipe
    deux["agents"].append({**copy.deepcopy(next(a for a in v["agents"] if a["id"] == ENDORMI)), "id": "coord-veille", "equipe": "fondation"})
    zero = copy.deepcopy(v)  # le même coordinateur, réveillé : aucun endormi
    next(a for a in zero["agents"] if a["id"] == ENDORMI).update(etat="au_repos", vivant=True, session_tmux="cc-coord-livraison", etat_source="hook:Stop")
    grave = copy.deepcopy(v)  # une alarme grave qui cite le coordinateur endormi
    grave["alarmes"].append({"type": "recouvrement", "gravite": "grave", "agents": [ENDORMI], "equipes": ["livraison"],
                             "depuis": "2026-10-07T12:00:00.000Z", "mesure": "m", "quoi_faire": "q"})
    arret = copy.deepcopy(v)  # témoin : le coordinateur d'une équipe, arrêté et sans alarme, rend l'équipe « à l’arrêt »
    next(a for a in arret["agents"] if a["id"] == "coord-fondation").update(etat="arrete", vivant=False, session_tmux=None)
    arret["alarmes"] = []
    return {"exemple": v, "deux": deux, "zero": zero, "seul": seul, "grave": grave, "arret": arret}


def executer(static, jeux, travail):
    sonde = travail / "sonde-endormi.mjs"
    sonde.write_text(SONDE, encoding="utf-8")
    donnees = travail / "jeux-endormi.json"
    donnees.write_text(json.dumps(jeux), encoding="utf-8")
    res = subprocess.run(["node", str(sonde), str(static / "commun.js"), str(donnees)], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------------------
# Les vérifications : chacune lève AssertionError si le comportement manque
# ---------------------------------------------------------------------------
def verifier_etat(s):
    assert s["exemple"]["agents"][ENDORMI]["etat"] == "endormi"
    assert s["exemple"]["agents"][ENDORMI]["etat"] != "inconnu"


def verifier_mot_ton(s):
    for nom in ("exemple", "grave"):  # même avec une alarme grave qui le cite, il reste gris
        d = s[nom]["agents"][ENDORMI]["def"]
        assert (d["mot"], d["ton"]) == ("endormi", "gris"), (nom, d)


def verifier_effectifs(s):
    texte = s["exemple"]["resume"]["texte"]
    assert f"1{NB}endormi" in texte, texte
    assert texte.find("au repos") != -1 and texte.find("au repos") < texte.find("endormi"), texte  # après « au repos »
    assert f"2{NB}endormis" in s["deux"]["resume"]["texte"], s["deux"]["resume"]["texte"]
    assert "endormi" not in s["zero"]["resume"]["texte"], s["zero"]["resume"]["texte"]


def verifier_pastille_pas_rouge(s):
    for nom in ("seul", "deux"):  # un endormi, ou deux, ne rendent ni la pilule rouge ni ambre
        classes = s[nom]["resume"]["classes"]
        assert "ton-vert" in classes and "ton-rouge" not in classes and "ton-ambre" not in classes, (nom, classes)


def verifier_equipe_pas_a_l_arret(s):
    assert s["exemple"]["equipes"]["livraison"] is False, "une équipe dont le coordinateur dort n'est pas à l’arrêt"
    assert s["arret"]["equipes"]["fondation"] is True, "témoin : une équipe arrêtée sans alarme est à l’arrêt"


def verifier_fiche(s):
    carte = s["exemple"]["cartes"][ENDORMI]
    assert "pas de terminal : endormi" in carte["texte"], carte["texte"]
    assert "session absente" not in carte["texte"] and "inconnu" not in carte["texte"], carte["texte"]
    assert "agent-session" in carte["classes"] and "absente" not in carte["classes"], carte["classes"]
    assert "ton-gris" in carte["classes"] and "ton-rouge" not in carte["classes"], carte["classes"]


def verifier_rail(rail_js):
    m = re.search(r"const ETATS_QUI_TRAVAILLE = new Set\(\[([^\]]*)\]\)", rail_js)
    assert m, "ensemble ETATS_QUI_TRAVAILLE introuvable"
    assert "endormi" not in m.group(1), "un endormi n'est ni quelqu'un qui travaille ni quelqu'un qui attend"


CONTROLES = {
    "etat": verifier_etat,
    "mot et ton": verifier_mot_ton,
    "effectifs": verifier_effectifs,
    "pilule pas rouge": verifier_pastille_pas_rouge,
    "équipe pas à l’arrêt": verifier_equipe_pas_a_l_arret,
    "fiche d'équipe": verifier_fiche,
    "rail": verifier_rail,
}


def verifier_tout(s, rail_js):
    """Renvoie les contrôles qui échouent (liste vide : tout passe)."""
    echecs = []
    for nom, controle in CONTROLES.items():
        try:
            controle(rail_js) if nom == "rail" else controle(s)
        except AssertionError:
            echecs.append(nom)
    return echecs


@pytest.fixture(scope="module")
def static_jeux(tmp_path_factory):
    travail = tmp_path_factory.mktemp("endormi")
    return {"s": executer(STATIC, _jeux(), travail), "rail": (STATIC / "vues" / "rail.js").read_text(encoding="utf-8")}


def test_comportements_tiennent(static_jeux):
    assert verifier_tout(static_jeux["s"], static_jeux["rail"]) == []


def test_etat_affiche_endormi(static_jeux):
    verifier_etat(static_jeux["s"])


def test_mot_et_ton_gris(static_jeux):
    verifier_mot_ton(static_jeux["s"])


def test_effectifs(static_jeux):
    verifier_effectifs(static_jeux["s"])


def test_pilule_pas_rouge_ni_ambre(static_jeux):
    verifier_pastille_pas_rouge(static_jeux["s"])


def test_equipe_pas_a_l_arret(static_jeux):
    verifier_equipe_pas_a_l_arret(static_jeux["s"])


def test_fiche_equipe(static_jeux):
    verifier_fiche(static_jeux["s"])


def test_rail(static_jeux):
    verifier_rail(static_jeux["rail"])


# ---------------------------------------------------------------------------
# Mutations : chacune casse un comportement ; le contrôle visé doit échouer
# ---------------------------------------------------------------------------
MUTATIONS = [
    ("entrée retirée de ETATS_AGENT", "commun.js", "  endormi: { mot: 'endormi', ton: 'gris' },\n", "",
     {"etat", "mot et ton", "effectifs", "fiche d'équipe"}),
    ("ton rouge", "commun.js", "endormi: { mot: 'endormi', ton: 'gris' }", "endormi: { mot: 'endormi', ton: 'rouge' }", {"mot et ton"}),
    ("ton ambre", "commun.js", "endormi: { mot: 'endormi', ton: 'gris' }", "endormi: { mot: 'endormi', ton: 'ambre' }", {"mot et ton"}),
    ("effectifs sans endormi", "commun.js", "    n('endormi') ? mot(n('endormi'), 'endormi', 'endormis') : null,\n", "",
     {"effectifs"}),
    ("un endormi tire la pilule au rouge", "commun.js", "const ton = compte.arrete ? 'rouge'",
     "const ton = compte.arrete || compte.endormi ? 'rouge'", {"pilule pas rouge"}),
    ("équipe endormie « à l’arrêt »", "commun.js", "siens.every((a) => etatAffiche(a) === 'arrete')",
     "siens.every((a) => ['arrete', 'endormi'].includes(etatAffiche(a)))", {"équipe pas à l’arrêt"}),
    ("fiche : endormi traité en session absente", "commun.js", "  } else if (etatCle === 'endormi') {", "  } else if (false) {",
     {"fiche d'équipe"}),
    ("rail : endormi compté comme qui travaille", "vues/rail.js",
     "new Set(['travaille', 'attend_autorisation', 'attend_reponse'])",
     "new Set(['travaille', 'attend_autorisation', 'attend_reponse', 'endormi'])", {"rail"}),
]


@pytest.mark.parametrize("nom,fichier,ancien,nouveau,attendus", MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_mutation_detectee(tmp_path, nom, fichier, ancien, nouveau, attendus):
    copie = tmp_path / "static"
    shutil.copytree(STATIC, copie)
    cible = copie / fichier
    texte = cible.read_text(encoding="utf-8")
    assert texte.count(ancien) == 1, f"la mutation doit s'appliquer une fois : {nom}"
    cible.write_text(texte.replace(ancien, nouveau), encoding="utf-8")
    echecs = set(verifier_tout(executer(copie, _jeux(), tmp_path), (copie / "vues" / "rail.js").read_text(encoding="utf-8")))
    assert attendus <= echecs, (nom, echecs)
