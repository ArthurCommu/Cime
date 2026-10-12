"""Affichage de l'état : seuil des questions écrites, sessions hors organigramme, intégration, décisions.

Analyse de texte du JS et du CSS de static/ (pas de navigateur dans pytest). `verifier_affichage(js)`
lève AssertionError ; la table MUTATIONS prouve qu'elle échoue quand on casse chaque comportement.
"""
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "src" / "cime" / "page" / "static"


def _corps(texte, debut, fin):
    i = texte.index(debut)
    return texte[i:texte.index(fin, i)]


def verifier_affichage(js):
    commun, ensemble, fil = js["commun.js"], js["vues/ensemble.js"], js["vues/fil.js"]
    css = js["style.css"]
    # 1. seuil des questions écrites : constantes, fonction pure unique, bornes strictes
    assert "SEUIL_QUESTION_ECRITE_MS = 30 * 60_000;" in commun
    assert "SEUIL_QUESTION_ECRITE_GRAVE_MS = 2 * 3600_000;" in commun
    assert "SEUIL_QUESTION_MS = 15 * 60_000;" in commun
    assert len(re.findall(r"export function niveauRetard\(m, maintenantMs\)", commun)) == 1
    niveau = _corps(commun, "export function niveauRetard", "/** Le message derrière")
    assert "if (!aSeuil(m) || !m.horodatage) return null;" in niveau
    assert "estQuestionEcrite(m)" in niveau
    assert re.search(r"attente > SEUIL_QUESTION_ECRITE_GRAVE_MS \? 'rouge' : attente > SEUIL_QUESTION_ECRITE_MS \? 'ambre' : null", niveau)
    assert re.search(r"return attente > SEUIL_QUESTION_MS \? 'rouge' : null;", niveau)
    assert ">=" not in niveau
    assert niveau.index("SEUIL_QUESTION_ECRITE_GRAVE_MS") < niveau.index("SEUIL_QUESTION_MS ?")  # le registre garde 15 min
    # la coloration, la phrase et le fil passent par niveauRetard, sans seuil en dur
    colorier = _corps(commun, "export function colorierAttentes", "/** Lignes du fil")
    assert "niveauRetard(m, maintenant)" in colorier
    assert re.search(r"toggle\('a-voir', niveau === 'ambre'\)", colorier)
    assert len(re.findall(r"toggle\('tard', niveau === 'rouge'\)", colorier)) == 2  # phrase et ligne du fil
    assert "SEUIL_" not in colorier
    assert "' · sans réponse'" in commun and "' · en retard'" in commun
    assert re.search(r"MOTS_RETARD = \{ ambre: ' · sans réponse', rouge: ' · en retard' \}", commun)
    assert "mot.textContent = MOTS_RETARD[niveau] || ''" in colorier
    assert "niveauRetard(m, horloge.maintenant()) === 'rouge'" in fil and "SEUIL_" not in fil
    assert re.search(r"estQuestionEcrite\(m\) \? ' ecrite' : ''", commun)  # neutre avant 30 min
    # avant son seuil, une attente est neutre : l'ambre ne veut dire que « sans réponse »
    assert ".attend-phrase { color: var(--secondaire); }" in css
    assert re.search(r"\.attend-phrase\.ecrite \{ color: var\(--secondaire\); \}", css)
    assert re.search(r"\.attend-phrase\.a-voir \{ color: var\(--ambre\); \}", css)
    assert css.index(".attend-phrase.a-voir") < css.index(".attend-phrase.tard")
    # 2. sessions hors organigramme : type d'alarme, section après Alarmes, trois états
    assert re.search(r"TYPES_ALARME = \{[^}]*\bsession_orpheline: 'Session hors organigramme'", commun)
    sessions = _corps(ensemble, "function sectionSessionsOrphelines", "// ----")
    assert "if (Array.isArray(sessions) && !sessions.length) return null;" in sessions
    assert "inconnu(sourceEnEchec(etat, 'tmux'), 'inconnues')" in sessions
    assert "mono(x.nom)" in sessions and "'ouverte '" in sessions and "'activité '" in sessions
    assert "x.depuis ? age(x.depuis)" in sessions and "x.activite ? age(x.activite)" in sessions
    assert "des sessions tmux au préfixe du projet que l’organigramme ne connaît pas" in sessions
    assert "button" not in sessions and "onclick" not in sessions
    # 3. intégration : absente si null, pastille de verdict, fichier dépliable, requêtes
    integ = _corps(ensemble, "const VERDICTS", "// 8. Pied")
    assert re.search(r"VERDICTS = \{ PASS: \{ mot: 'PASS', ton: 'vert' \}, FAIL: \{ mot: 'FAIL', ton: 'rouge' \} \}", integ)
    assert "{ mot: 'verdict non lu', ton: 'gris' }" in integ
    assert "if (!rapport) return el('p', { class: 'vide-calme' }, 'aucun rapport');" in integ
    assert "texteDepliable(" in integ and "mono(rapport.fichier)" in integ
    assert "ETATS_REQUETE = { todo: 'à traiter', 'in-progress': 'en cours' }" in integ
    assert "'aucune requête en cours'" in integ and "age(r.depuis, 'depuis')" in integ
    assert "if (!sourceEnEchec(etat, 'structure')) return null;" in integ
    assert "if (!integration.dernier_rapport && !(integration.requetes || []).length) return null;" in integ  # ni rapport ni requête : rien
    assert integ.count("inconnu(sourceEnEchec(etat, 'structure'), 'inconnues')") == 1
    assert "'Vérifications d’intégration'" in integ and "'Dernier rapport'" in integ and "'Requêtes en cours'" in integ
    assert "alarme" not in integ.lower() and "ton-rouge" not in integ
    # le dépliage du fil et celui du rapport sont le même code
    assert "export function texteDepliable" in commun
    assert "texteDepliable(m, 'fil-ouvrir'" in _corps(commun, "export function ligneFil", "// ----")
    # dépliage du rapport : le contenu du fichier seul, ni « Document joint », ni seconde « Fichier : »
    assert "{ seulContenu: true }" in integ
    assert "Document joint" not in integ and "Fichier :" not in integ and "rendreTexte" not in integ
    panneau = _corps(commun, "function remplirPanneau", "/** Un bouton qui déplie")
    seul = _corps(panneau, "if (seulContenu) {", "  vider(panneau, lu.erreur\n    ? [el('p', {}, m.resume)")
    assert "el('div', { class: 'texte-fichier' }, lu.t.contenu)" in seul
    assert "`Texte complet illisible : ${lu.erreur}.`" in seul  # l'erreur de lecture reste dite
    for interdit in ("m.resume", "Fichier :", "Document joint", "rendreTexte", "note", "avant"):
        assert interdit not in seul, interdit
    assert "remplirPanneau(panneau, m, seulContenu)" in _corps(commun, "export function texteDepliable", "/** Une ligne du fil")
    assert "seulContenu" not in _corps(commun, "export function ligneFil", "// ----")  # le fil reste inchangé
    assert "Document joint" not in commun
    assert "filOuverts" not in _corps(commun, "export function ligneFil", "// ----")  # un seul dépliage
    # 4. décisions récentes et derniers échanges : retirés de Supervision ; le pied est la dernière ligne
    assert "sectionDecisions" not in ensemble and "Décisions récentes" not in ensemble and "decisions_recentes" not in ensemble
    assert "sectionFil" not in ensemble and "Derniers échanges" not in ensemble and "ligneFil" not in ensemble
    rendu = _corps(ensemble, "export function rendre", "\n}\n")
    ordre = [rendu.index(f"{n}()") for n in (
        "sectionAlarmes", "sectionSessionsOrphelines", "sectionIntegration", "piedSupervision")]
    assert ordre == sorted(ordre)
    # aucun bouton pour agir sur une session
    for nom in ("sectionSessionsOrphelines", "sectionIntegration"):
        assert "agir(" not in _corps(ensemble, f"function {nom}", "\n}\n")
    # 5. couleurs : variables seulement
    nouveau = css[css.index("/* Supervision : sessions hors"):]
    assert not re.search(r"#[0-9A-Fa-f]{3,8}\b", nouveau)


@pytest.fixture(scope="module")
def js():
    fichiers = sorted(STATIC.glob("*.js")) + sorted((STATIC / "vues").glob("*.js")) + [STATIC / "style.css"]
    return {str(f.relative_to(STATIC)): f.read_text(encoding="utf-8") for f in fichiers}


def test_affichage(js):
    verifier_affichage(js)


def _remplace(fichier, ancien, nouveau):
    def mutation(js):
        assert ancien in js[fichier], ancien
        return {**js, fichier: js[fichier].replace(ancien, nouveau)}
    return mutation


NIV = "commun.js"
MUTATIONS = {
    "écrite ambre à 40 min": _remplace(NIV, "SEUIL_QUESTION_ECRITE_MS = 30 * 60_000", "SEUIL_QUESTION_ECRITE_MS = 40 * 60_000"),
    "écrite rouge à 3 h": _remplace(NIV, "SEUIL_QUESTION_ECRITE_GRAVE_MS = 2 * 3600_000", "SEUIL_QUESTION_ECRITE_GRAVE_MS = 3 * 3600_000"),
    "registre rouge à 30 min": _remplace(NIV, "SEUIL_QUESTION_MS = 15 * 60_000", "SEUIL_QUESTION_MS = 30 * 60_000"),
    "borne de 30 min incluse": _remplace(NIV, "attente > SEUIL_QUESTION_ECRITE_MS ?", "attente >= SEUIL_QUESTION_ECRITE_MS ?"),
    "borne de 2 h incluse": _remplace(NIV, "attente > SEUIL_QUESTION_ECRITE_GRAVE_MS ?", "attente >= SEUIL_QUESTION_ECRITE_GRAVE_MS ?"),
    "registre : borne incluse": _remplace(NIV, "return attente > SEUIL_QUESTION_MS", "return attente >= SEUIL_QUESTION_MS"),
    "écrite traitée comme le registre": _remplace(NIV, "if (estQuestionEcrite(m)) {", "if (false) {"),
    "niveaux inversés": _remplace(NIV, "? 'rouge' : attente > SEUIL_QUESTION_ECRITE_MS ? 'ambre'", "? 'ambre' : attente > SEUIL_QUESTION_ECRITE_MS ? 'rouge'"),
    "deux fonctions de niveau": _remplace(NIV, "/** Le message derrière", "export function niveauRetard(m, maintenantMs) { return null; }\n/** Le message derrière"),
    "niveau sans filtre aSeuil": _remplace(NIV, "if (!aSeuil(m) || !m.horodatage) return null;", "if (!m.horodatage) return null;"),
    "coloration sans niveau": _remplace(NIV, "niveauRetard(m, maintenant)", "null"),
    "ambre non appliqué": _remplace(NIV, "toggle('a-voir', niveau === 'ambre')", "toggle('a-voir', false)"),
    "ligne du fil jamais rouge": _remplace(NIV, "ligneParente.classList.toggle('tard', niveau === 'rouge');", ""),
    "mot « sans réponse » perdu": _remplace(NIV, "ambre: ' · sans réponse'", "ambre: ''"),
    "mot « en retard » perdu": _remplace(NIV, "rouge: ' · en retard'", "rouge: ''"),
    "écrite sans repère neutre": _remplace(NIV, "estQuestionEcrite(m) ? ' ecrite' : ''", "''"),
    "neutre devenu ambre": _remplace("style.css", ".attend-phrase.ecrite { color: var(--secondaire); }", ".attend-phrase.ecrite { color: var(--ambre); }"),
    "fil : seuil en dur": _remplace("vues/fil.js", "niveauRetard(m, horloge.maintenant()) === 'rouge'", "niveauRetard(m, horloge.maintenant()) !== null"),
    "orpheline sans libellé": _remplace(NIV, "session_orpheline: 'Session hors organigramme',", ""),
    "sessions toujours affichées": _remplace("vues/ensemble.js", "if (Array.isArray(sessions) && !sessions.length) return null;", ""),
    "sessions null sans source": _remplace("vues/ensemble.js", "inconnu(sourceEnEchec(etat, 'tmux'), 'inconnues')", "'aucune'"),
    "session sans activité": _remplace("vues/ensemble.js", "'activité '", "''"),
    "session sans ancienneté": _remplace("vues/ensemble.js", "'ouverte '", "''"),
    "sous-titre des sessions perdu": _remplace("vues/ensemble.js", "que l’organigramme ne connaît pas", "inconnues"),
    "bouton sur une session": _remplace("vues/ensemble.js", "mono(x.nom),", "mono(x.nom), el('button', { onclick: () => {} }, 'fermer'),"),
    "intégration toujours affichée": _remplace("vues/ensemble.js", "if (!sourceEnEchec(etat, 'structure')) return null;", ""),
    "intégration masquée même en échec": _remplace("vues/ensemble.js", "if (!sourceEnEchec(etat, 'structure')) return null;", "return null;"),
    "attente ambre avant le seuil": _remplace("style.css", ".attend-phrase { color: var(--secondaire); }", ".attend-phrase { color: var(--ambre); }"),
    "décisions introuvables même en échec": _remplace("vues/ensemble.js", "sourceEnEchec(etat, 'structure')\n      ? inconnu(sourceEnEchec(etat, 'structure'), 'inconnues')", "false\n      ? inconnu(sourceEnEchec(etat, 'structure'), 'inconnues')"),
    "PASS en rouge": _remplace("vues/ensemble.js", "PASS: { mot: 'PASS', ton: 'vert' }", "PASS: { mot: 'PASS', ton: 'rouge' }"),
    "FAIL en vert": _remplace("vues/ensemble.js", "FAIL: { mot: 'FAIL', ton: 'rouge' }", "FAIL: { mot: 'FAIL', ton: 'vert' }"),
    "verdict nul sans mot": _remplace("vues/ensemble.js", "'verdict non lu'", "''"),
    "rapport absent muet": _remplace("vues/ensemble.js", "'aucun rapport'", "''"),
    "requêtes vides muettes": _remplace("vues/ensemble.js", "'aucune requête en cours'", "''"),
    "état todo brut": _remplace("vues/ensemble.js", "todo: 'à traiter'", "todo: 'todo'"),
    "état in-progress brut": _remplace("vues/ensemble.js", "'in-progress': 'en cours'", "'in-progress': 'in-progress'"),
    "requête sans ancienneté": _remplace("vues/ensemble.js", "age(r.depuis, 'depuis')", "''"),
    "rapport non dépliable": _remplace("vues/ensemble.js", "texteDepliable(", "String("),
    "alarme d'intégration": _remplace("vues/ensemble.js", "const ETATS_REQUETE", "const alarmeIntegration = true;\nconst ETATS_REQUETE"),
    "rapport avec le résumé du message": _remplace(NIV, "if (seulContenu) {", "if (seulContenu) {\n    vider(panneau, el('p', {}, m.resume));"),
    "rapport avec « Fichier : »": _remplace(NIV, "el('div', { class: 'texte-fichier' }, lu.t.contenu)\n        : el", "el('div', { class: 'texte-fichier' }, lu.t.contenu), `Fichier : ${m.fichier}`\n        : el"),
    "rapport avec le gabarit du message": _remplace(NIV, "if (seulContenu) {", "if (seulContenu) {\n    vider(panneau, rendreTexte(lu.t));"),
    "rapport : « Document joint » en dur": _remplace("vues/ensemble.js", "{ seulContenu: true }", "{ seulContenu: true }, 'Document joint au message.'"),
    "rapport sans option de contenu seul": _remplace("vues/ensemble.js", ", { seulContenu: true }", ""),
    "rapport : erreur de lecture tue": _remplace(NIV, "`Texte complet illisible : ${lu.erreur}.`)\n      : typeof", "'')\n      : typeof"),
    "option perdue au rechargement": _remplace(NIV, "remplirPanneau(panneau, m, seulContenu)\n    }", "remplirPanneau(panneau, m)\n    }"),
    "fil avec l'option": _remplace(NIV, "m.en_attente ? phraseAttente(m, true) : null]);", "m.en_attente ? phraseAttente(m, true) : null], { seulContenu: true });"),
    "dépliage dupliqué": _remplace(NIV, "texteDepliable(m, 'fil-ouvrir'", "String(m, 'fil-ouvrir'"),
    "décisions récentes revenues": _remplace("vues/ensemble.js", "    piedSupervision());", "    sectionDecisions(),\n    piedSupervision());"),
    "fonction des décisions revenue": _remplace("vues/ensemble.js", "function piedSupervision()", "function sectionDecisions() { return el('section', {}, 'Décisions récentes'); }\nfunction piedSupervision()"),
    "derniers échanges revenus": _remplace("vues/ensemble.js", "    piedSupervision());", "    sectionFil(),\n    piedSupervision());"),
    "ligne du fil revenue": _remplace("vues/ensemble.js", "  joindre, statutEquipeAffiche,", "  ligneFil, joindre, statutEquipeAffiche,"),
    "champ des décisions relu": _remplace("vues/ensemble.js", "function piedSupervision()", "const lesDecisions = () => etat.decisions_recentes;\nfunction piedSupervision()"),
    "intégration vide affichée": _remplace("vues/ensemble.js", "  if (!integration.dernier_rapport && !(integration.requetes || []).length) return null;\n", ""),
    "pied avant l'intégration": _remplace("vues/ensemble.js", "    sectionIntegration(),\n    piedSupervision());", "    piedSupervision(),\n    sectionIntegration());"),
    "intégration avant les sessions": _remplace(
        "vues/ensemble.js", "    sectionSessionsOrphelines(),\n    sectionIntegration(),", "    sectionIntegration(),\n    sectionSessionsOrphelines(),"),
    "couleur en dur": _remplace("style.css", "color: var(--bleu-clair); text-decoration: underline;", "color: #8FB0D6; text-decoration: underline;"),
}


@pytest.mark.parametrize("nom", MUTATIONS)
def test_mutation_detectee(nom, js):
    with pytest.raises(AssertionError):
        verifier_affichage(MUTATIONS[nom](js))


def test_couverture_des_verifications():
    toutes = {n for n, v in globals().items() if n.startswith("verifier_") and callable(v)}
    assert toutes == {"verifier_affichage"} and MUTATIONS, sorted(toutes)
