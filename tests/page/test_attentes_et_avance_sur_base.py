"""Affichage de l'état : équipe d'une attente, questions écrites, agent figé, avance sur la base.

Analyse de texte du JS de static/ (pas de navigateur dans pytest). `verifier_affichage(js)`
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
    commun, equipe = js["commun.js"], js["vues/equipe.js"]
    # 3. agent figé : un type d'alarme connu, et un type inconnu s'affiche par son nom brut
    assert re.search(r"TYPES_ALARME = \{[^}]*\bfige: 'Agent figé'", commun)
    assert "TYPES_ALARME[a.type] || a.type" in commun
    # 1. équipe d'une attente : le champ prime, sans déduire de l'agent
    fonction = _corps(commun, "export function equipeDeLAttente", "/** Dialogue de clôture")
    assert re.search(r"typeof attente\.equipe === 'string' && attente\.equipe\) return attente\.equipe;", fonction)
    assert fonction.index("return attente.equipe") < fonction.index(".find(")
    carte = _corps(commun, "function carteAttente", "// En-tête unique")
    assert re.search(r"attente\.equipe\s*\?\s*\[[^\]]*lienEquipe\(attente\.equipe\)[^\]]*\]\s*:\s*null", carte)
    # 2. questions écrites : jamais une conversation, repérées, aucun id supposé numérique
    assert re.search(r"estConversation = \(m\) => m\.nature === null && m\.source === 'hook';", commun)
    assert re.search(r"estQuestionEcrite = \(m\) => m\.source === 'structure' && m\.nature === 'question';", commun)
    assert re.search(r"libelleNature = [^\n]*estQuestionEcrite\(m\) \? 'question écrite'", commun)
    assert "libelleNature(m)" in _corps(commun, "export function ligneFil", "// ----")
    for nom, texte in js.items():
        assert "msg-" not in texte, nom
        assert not re.search(r"(parseInt|Number|parseFloat)\([^)]*\.id\b|\+\w+\.id\b", texte), nom
    # 4. avance sur la base : trois cas, pluriel, jamais une alarme
    avance = _corps(equipe, "let avance;", "return el('header'")
    assert "`rien d’avance sur ${base}`" in avance
    assert re.search(r"pluriel\(q\.en_avance_sur_base, 'commit'\)\} pas encore dans \$\{base\}", avance)
    assert re.search(r"q\.branche \? inconnu\(sourceEnEchec\(etat, 'git'\), 'inconnu'\) : 'pas de branche'", avance)
    assert "=== 0" in avance and "ton-rouge" not in avance and "alarme" not in avance
    assert re.search(r"'Avance sur la base'\), el\('span', \{\}, avance\)", equipe)


@pytest.fixture(scope="module")
def js():
    fichiers = sorted(STATIC.glob("*.js")) + sorted((STATIC / "vues").glob("*.js"))
    return {str(f.relative_to(STATIC)): f.read_text(encoding="utf-8") for f in fichiers}


def test_affichage(js):
    verifier_affichage(js)


def _remplace(fichier, ancien, nouveau):
    def mutation(js):
        assert ancien in js[fichier], ancien
        return {**js, fichier: js[fichier].replace(ancien, nouveau)}
    return mutation


MUTATIONS = {
    "fige sans libellé": _remplace("commun.js", "fige: 'Agent figé',", ""),
    "type inconnu sans nom brut": _remplace("commun.js", "TYPES_ALARME[a.type] || a.type", "TYPES_ALARME[a.type]"),
    "équipe déduite de l'agent d'abord": _remplace(
        "commun.js", "  if (typeof attente.equipe === 'string' && attente.equipe) return attente.equipe;\n", ""),
    "équipe absente de l'attente": _remplace("commun.js", "lienEquipe(attente.equipe)", "attente.equipe"),
    "équipe affichée même nulle": _remplace("commun.js", "typeof attente.equipe === 'string' && attente.equipe ? [", "true ? ["),
    "question écrite prise pour une conversation": _remplace(
        "commun.js", "m.nature === null && m.source === 'hook';", "m.source !== 'registre';"),
    "question écrite sans repère": _remplace("commun.js", "estQuestionEcrite(m) ? 'question écrite'", "false ? 'question écrite'"),
    "id supposé numérique": _remplace("commun.js", "const estConversation", "const idNum = (m) => parseInt(m.id.replace('msg-', ''));\nconst estConversation"),
    "avance 0 sans mot": _remplace("vues/equipe.js", "`rien d’avance sur ${base}`", "'0'"),
    "avance sans pluriel": _remplace("vues/equipe.js", "pluriel(q.en_avance_sur_base, 'commit')", "q.en_avance_sur_base + ' commit'"),
    "avance null sans branche": _remplace("vues/equipe.js", "'pas de branche'", "'inconnu'"),
    "avance null sans source en échec": _remplace("vues/equipe.js", "inconnu(sourceEnEchec(etat, 'git'), 'inconnu') : 'pas de branche'", "'inconnu' : 'pas de branche'"),
    "avance en rouge": _remplace("vues/equipe.js", "avance = q.branche", "avance = el('span', { class: 'ton-rouge' }, 'x'); avance = q.branche"),
    "avance non affichée": _remplace("vues/equipe.js", "el('span', {}, avance)", "el('span', {}, '')"),
}


@pytest.mark.parametrize("nom", MUTATIONS)
def test_mutation_detectee(nom, js):
    with pytest.raises(AssertionError):
        verifier_affichage(MUTATIONS[nom](js))


def test_couverture_des_verifications():
    toutes = {n for n, v in globals().items() if n.startswith("verifier_") and callable(v)}
    assert toutes == {"verifier_affichage"} and MUTATIONS, sorted(toutes)
