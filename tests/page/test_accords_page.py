"""« Accorder la fusion » / « Accorder le chantier » sur la page.

Analyse de texte du JS de static/ (pas de navigateur dans pytest). `verifier_accords(js)` lève
AssertionError ; la table MUTATIONS prouve qu'elle échoue quand on casse chaque comportement.
"""
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "src" / "cime" / "page" / "static"


def _corps(texte, debut, fin):
    i = texte.index(debut)
    return texte[i:texte.index(fin, i)]


def verifier_accords(js):
    commun, source, journal = js["commun.js"], js["source.js"], js["vues/journal.js"]
    # 1. deux accords connus, chacun avec son bouton ; un seul nom de route pour accorder
    assert "{ prefixe: 'fusion:', bouton: 'Accorder la fusion', detail: 'Commit' }" in commun
    assert "{ prefixe: 'chantier:', bouton: 'Accorder le chantier', detail: 'Phase' }" in commun
    assert "accorder: '/api/actions/accorder'," in source
    # 2. accordDe : seulement une décision, d'objet connu, dont l'hôte a dit « accorder »
    accord = _corps(commun, "export function accordDe(attente)", "function dialogueAccorder")
    assert "attente.nature !== 'decision'" in accord
    assert "attente.actions.includes('accorder')" in accord
    assert "attente.objet.startsWith(a.prefixe)" in accord
    # 3. la décision à accorder remplace « Trancher » ; les autres décisions gardent « Trancher »
    decision = _corps(commun, "    case 'decision': {", "    case 'donnee'")
    assert "const accord = accordDe(attente);" in decision
    assert "dialogueAccorder(attente, accord)" in decision and "accord.bouton" in decision
    assert "dialogueRefuserAccord(attente, accord)" in decision and "'Refuser'" in decision
    assert decision.index("accordDe(attente)") < decision.index("dialogueTrancher(attente)")
    # 4. les dialogues : accorder en un geste confirmé, refuser avec un motif obligatoire d'une ligne
    ouvrir = _corps(commun, "function dialogueAccorder", "function dialogueRefuserAccord")
    assert "agir({ action: 'accorder', attente, corps: { attente_id: attente.id }" in ouvrir
    assert "accord.bouton" in ouvrir
    refus = _corps(commun, "function dialogueRefuserAccord", "function dialogueTrancher")
    assert "required: true, maxlength: '160'" in refus
    assert "agir({ action: 'refuser', attente, corps: { attente_id: attente.id, motif: champ.value.trim() }" in refus
    assert "valide: () => Boolean(champ.value.trim())" in refus
    # 5. la page ne lance rien d'autre : ni git, ni route de commande, dans le code des accords
    bloc = _corps(commun, "const ACCORDS = [", "function dialogueTrancher")
    assert not re.search(r"\bgit\b|merge|checkout", bloc)
    # 6. le journal distingue refuser une autorisation et refuser un accord
    assert "accorder: 'accord donné'," in journal
    assert "l.action === 'refuser' && l.details && typeof l.details.objet === 'string'" in journal
    assert "return 'accord refusé';" in journal


@pytest.fixture(scope="module")
def js():
    return {str(p.relative_to(STATIC)): p.read_text(encoding="utf-8") for p in STATIC.rglob("*.js")}


def test_accords_de_la_page(js):
    verifier_accords(js)


def _remplace(nom, avant, apres):
    def muter(js):
        assert avant in js[nom], (nom, avant)
        return {**js, nom: js[nom].replace(avant, apres)}
    return muter


MUTATIONS = {
    "bouton de fusion renommé": _remplace("commun.js", "'Accorder la fusion'", "'Fusionner'"),
    "route d'accord oubliée": _remplace("source.js", "accorder: '/api/actions/accorder',", ""),
    "accord sans l'avis de l'hôte": _remplace("commun.js", "!attente.actions.includes('accorder')", "false"),
    "Trancher d'abord": _remplace("commun.js", "      const accord = accordDe(attente);\n      if (accord) {",
                                  "      const accord = null;\n      if (accord) {"),
    "motif facultatif": _remplace("commun.js", "required: true, maxlength: '160'", "maxlength: '160'"),
    "refus sans motif": _remplace("commun.js", "corps: { attente_id: attente.id, motif: champ.value.trim() }",
                                  "corps: { attente_id: attente.id }"),
    "la page nomme git": _remplace("commun.js", "Cette page ne touche à aucune branche",
                                   "Cette page lance git merge"),
    "journal confond les refus": _remplace("vues/journal.js", "return 'accord refusé';", "return 'autorisation refusée';"),
}


@pytest.mark.parametrize("nom", sorted(MUTATIONS))
def test_chaque_mutation_est_vue(js, nom):
    with pytest.raises(AssertionError):
        verifier_accords(MUTATIONS[nom](js))
