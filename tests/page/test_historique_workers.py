"""Workers terminés : hors de la vue d'ensemble, rangés en « + n workers terminés » (un repli) sur la page d'équipe.

Un worker terminé est arrêté et ne porte aucune alarme (`workerTermine` dans commun.js). Analyse de texte
du JS de static/ (pas de navigateur dans pytest). `verifier_historique(js)` lève AssertionError ; la table
MUTATIONS prouve qu'elle échoue quand on casse chaque comportement. Le rendu réel (organigramme, en-tête,
bloc replié, clic) est vérifié dans un vrai navigateur par tests/page/outils/scenario_historique.py.
"""
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "src" / "cime" / "page" / "static"


def _corps(texte, debut, fin):
    i = texte.index(debut)
    return texte[i:texte.index(fin, i)]


def verifier_historique(js):
    commun, ensemble, equipe = js["commun.js"], js["vues/ensemble.js"], js["vues/equipe.js"]
    # 1. la fonction pure : un seul exemplaire, worker arrêté, sans alarme qui le cite ; réutilise alarmesDe
    assert len(re.findall(r"export function workerTermine\(", commun)) == 1
    pure = _corps(commun, "export function workerTermine(agent, alarmes)", "\n}\n")
    assert "if (agent.role !== 'worker' || etatAffiche(agent) !== 'arrete') return false;" in pure
    assert "return alarmesDe(alarmes, { agent: agent.id }).length === 0;" in pure
    # 2. organigramme : les workers terminés ne sont pas dessinés (les coordinateurs restent)
    bloc = _corps(ensemble, "function agentsEquipe(q)", "function blocEquipe(q)")
    assert "const termines = siens.filter((a) => workerTermine(a, etat.alarmes));" in bloc
    assert "const vivants = siens.filter((a) => !termines.includes(a));" in bloc
    assert "vivants.filter((a) => a.role === 'coordinateur')" in bloc  # les coordinateurs d'abord, jamais retirés
    assert "`+ ${termines} ${termines === 1 ? 'worker terminé' : 'workers terminés'}`" in ensemble  # ils ne sont que comptés
    # 3. en-tête : un terminé n'est pas compté ; une équipe clôturée l'est déjà exclue
    resume = _corps(commun, "function resumeAgents(etat)", "function niveauAge")
    assert "terminees.has(a.equipe) || workerTermine(a, etat.alarmes)" in resume
    # 4. nouveautés : « agents arrêtés » ne compte pas les terminés
    nouv = _corps(ensemble, "function lignesNouveautes(visite)", "function sectionNouveautes()")
    assert "apres(a.etat_depuis)\n    && defEtatAgent(a, etat.alarmes).ton === 'rouge');" in nouv
    # 5. page d'équipe : liste des vivants, puis « + n workers terminés » replié (une ligne par worker), puis le reste
    sec = _corps(equipe, "function sectionAgents(q, agents, terminee)", "// Terminal en direct")
    assert "const { vivants, termines } = grouperAgents(agents, etat.alarmes);" in sec
    assert "const termines = agents.filter((a) => workerTermine(a, alarmes))" in _corps(equipe, "export function grouperAgents", "/** Le résumé du repli")
    assert "const vivants = agents.filter((a) => !termines.includes(a))" in equipe
    assert "const repli = termines.length ? el('details', { class: 'eq-termines' }," in sec
    assert "el('summary', {}, resumeTermines(termines.length))," in sec
    assert "{ class: 'eq-termines', open" not in sec  # replié par défaut
    assert "el('ul', { class: 'eq-termines-liste' }, termines.map(ligneTerminee))) : null;" in sec
    assert "corps,\n    repli,\n" in sec  # juste après la liste des vivants
    assert "'Aucun agent en cours.'" in sec  # tous terminés : la liste des vivants le dit
    assert "if (!agents.length) {" in sec  # le message « aucun agent » n'est dit que sans aucun agent
    assert "'Aucun agent de cette équipe dans l’instantané.'" in sec
    assert "Historique" not in sec  # un seul repli, pas de double
    # un vivant : une ligne, puis la carte habituelle, en détail, sous la ligne
    carte = _corps(equipe, "function carteAvecBrouillon(a, terminee)", "/** Un agent vivant")
    assert "carteAgent(a, ctx, { detail: true, equipeTerminee: terminee })" in carte


@pytest.fixture(scope="module")
def js():
    fichiers = sorted(STATIC.glob("*.js")) + sorted((STATIC / "vues").glob("*.js")) + [STATIC / "style.css"]
    return {str(f.relative_to(STATIC)): f.read_text(encoding="utf-8") for f in fichiers}


def test_historique(js):
    verifier_historique(js)


def _remplace(fichier, ancien, nouveau):
    def mutation(js):
        assert ancien in js[fichier], ancien
        return {**js, fichier: js[fichier].replace(ancien, nouveau)}
    return mutation


NIV = "commun.js"
EN = "vues/ensemble.js"
EQ = "vues/equipe.js"
MUTATIONS = {
    "vivant null rangé quand même": _remplace("commun.js", "etatAffiche(agent) !== 'arrete') return false;", "agent.etat !== 'arrete') return false;"),
    "coordinateur arrêté compté terminé": _remplace(NIV, "if (agent.role !== 'worker' || etatAffiche(agent) !== 'arrete') return false;",
                                                    "if (agent.etat !== 'arrete') return false;"),
    "worker travaillant compté terminé": _remplace(NIV, "if (agent.role !== 'worker' || etatAffiche(agent) !== 'arrete') return false;",
                                                   "if (agent.role !== 'worker') return false;"),
    "worker inconnu compté terminé": _remplace(NIV, "if (agent.role !== 'worker' || etatAffiche(agent) !== 'arrete') return false;",
                                               "if (agent.role !== 'worker' || !['arrete', 'inconnu'].includes(agent.etat)) return false;"),
    "worker arrêté avec alarme compté terminé": _remplace(NIV, "return alarmesDe(alarmes, { agent: agent.id }).length === 0;", "return true;"),
    "alarme de l'équipe au lieu de l'agent": _remplace(NIV, "return alarmesDe(alarmes, { agent: agent.id }).length === 0;",
                                                       "return alarmesDe(alarmes, { equipe: agent.equipe }).length === 0;"),
    "organigramme dessine les terminés": _remplace(EN, "const vivants = siens.filter((a) => !termines.includes(a));", "const vivants = siens;"),
    "en-tête compte les terminés": _remplace(NIV, "terminees.has(a.equipe) || workerTermine(a, etat.alarmes)", "terminees.has(a.equipe)"),
    "nouveautés comptent les terminés": _remplace(EN, " && apres(a.etat_depuis)\n    && defEtatAgent(a, etat.alarmes).ton === 'rouge');",
                                                  " && apres(a.etat_depuis));"),
    "historique ouvert d'office": _remplace(EQ, "el('details', { class: 'eq-termines' },", "el('details', { class: 'eq-termines', open: true },"),
    "compte absent du repli": _remplace(EQ, "el('summary', {}, resumeTermines(termines.length)),", "el('summary', {}, '+ workers terminés'),"),
    "repli affiché à 0": _remplace(EQ, "const repli = termines.length ? el('details'", "const repli = true ? el('details'"),
    "terminés encore dans la liste des vivants": _remplace(EQ, "const vivants = agents.filter((a) => !termines.includes(a))", "const vivants = agents.filter(() => true)"),
    "message « Aucun agent en cours. » absent": _remplace(EQ, "'Aucun agent en cours.'", "'.'"),
    "message « aucun agent » dit à tort": _remplace(EQ, "if (!agents.length) {", "if (!vivants.length) {"),
    "carte réduite sous la ligne": _remplace(EQ, "carteAgent(a, ctx, { detail: true, equipeTerminee: terminee })", "carteAgent(a, ctx)"),
    "repli avant les vivants": _remplace(EQ, "    corps,\n    repli,\n", "    repli,\n    corps,\n"),
}


@pytest.mark.parametrize("nom", MUTATIONS)
def test_mutation_detectee(nom, js):
    mutee = MUTATIONS[nom](js)  # hors du raises : la mutation doit s'appliquer, sinon le test serait faux
    with pytest.raises(AssertionError):
        verifier_historique(mutee)


def test_couverture_des_verifications():
    toutes = {n for n, v in globals().items() if n.startswith("verifier_") and callable(v)}
    assert toutes == {"verifier_historique"} and MUTATIONS, sorted(toutes)
