"""Messages « non lus » : un message adressé à l'utilisateur sans rien lui demander porte « Marquer comme lu ».

Champ `fil[].non_lu` et action `lu` sur `msg-<n>`. Analyse de texte
du JS et du CSS de static/ (pas de navigateur dans pytest). `verifier_lu_messages(js)` lève AssertionError ;
la table MUTATIONS prouve qu'elle échoue quand on casse chaque comportement. Le rendu réel (repère, clic,
désactivation, « envoyé ») est vérifié dans un vrai navigateur par tests/page/outils/scenario_lu.py.
"""
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "src" / "cime" / "page" / "static"


def _corps(texte, debut, fin):
    i = texte.index(debut)
    return texte[i:texte.index(fin, i)]


def verifier_lu_messages(js):
    commun, ensemble, journal = js["commun.js"], js["vues/ensemble.js"], js["vues/journal.js"]
    # 1. la fonction pure : exportée une fois, vraie seulement pour `true` strict
    assert len(re.findall(r"export function estNonLu\(", commun)) == 1
    pure = _corps(commun, "export function estNonLu(m)", "\n}\n")
    assert "return m.non_lu === true;" in pure
    # 2. ligneFil : le repère n'existe que si estNonLu ; frère du bouton de dépliage, pas dedans
    ligne = _corps(commun, "export function ligneFil(m)", "\n}\n")
    assert "}, bouton, panneau, estNonLu(m) ? repereNonLu(m) : null);" in ligne
    dep = _corps(ligne, "const { bouton, panneau } = texteDepliable(", "]);")
    assert "repereNonLu" not in dep and "estNonLu" not in dep
    # 3. le repère : texte « non lu », bouton « Marquer comme lu », jamais ouvert en dialogue
    rep = _corps(commun, "function repereNonLu(m)", "\n}\n")
    assert "el('span', { class: 'fil-non-lu' }, 'non lu')" in rep
    assert "'Marquer comme lu'" in rep
    assert ("onclick: () => agir({ action: 'lu', attente: m, corps: { attente_id: m.id }, cible: m.id, "
            "details: { message: m.id } })") in rep
    assert "ouvrirDialogue" not in rep and "dialogue" not in rep.lower()
    # 4. le bouton est désactivé pendant l'action ; après « ok », « envoyé » remplace le bouton
    assert "disabled: attenteEnCours(m.id) || actionsFigees," in rep  # et l'image figée désactive aussi
    assert "if (attenteEnvoyee(m.id))" in rep and "MOT_ENVOYEE" in rep
    # 5. attentes et en-tête ignorent non_lu : seul estNonLu le lit, aucune vue ne le lit
    attentes = _corps(commun, "export function attentesOuvertes(etat)", "\n}\n")
    assert "non_lu" not in attentes and "estNonLu" not in attentes
    assert commun.count("m.non_lu") == 1
    assert "non_lu" not in ensemble and "non_lu" not in journal
    # 6. style : le repère est ambre, jamais rouge (ce n'est pas un retard)
    css = js["style.css"]
    repere = _corps(css, ".fil-non-lu {", "}")
    assert "color: var(--ambre)" in repere and "rouge" not in repere


@pytest.fixture(scope="module")
def js():
    fichiers = sorted(STATIC.glob("*.js")) + sorted((STATIC / "vues").glob("*.js")) + [STATIC / "style.css"]
    return {str(f.relative_to(STATIC)): f.read_text(encoding="utf-8") for f in fichiers}


def test_lu_messages(js):
    verifier_lu_messages(js)


def _remplace(fichier, ancien, nouveau):
    def mutation(js):
        assert ancien in js[fichier], ancien
        return {**js, fichier: js[fichier].replace(ancien, nouveau)}
    return mutation


NIV = "commun.js"
EN = "vues/ensemble.js"
MUTATIONS = {
    "estNonLu truthy (non_lu non booléen compté)": _remplace(NIV, "return m.non_lu === true;", "return !!m.non_lu;"),
    "estNonLu sur « absent ou faux » (non_lu !== undefined)": _remplace(NIV, "return m.non_lu === true;", "return m.non_lu !== undefined;"),
    "repère sans condition": _remplace(NIV, "}, bouton, panneau, estNonLu(m) ? repereNonLu(m) : null);", "}, bouton, panneau, repereNonLu(m));"),
    "repère inversé": _remplace(NIV, "}, bouton, panneau, estNonLu(m) ? repereNonLu(m) : null);", "}, bouton, panneau, !estNonLu(m) ? repereNonLu(m) : null);"),
    "repère dans le bouton de dépliage": _remplace(NIV, "m.en_attente ? phraseAttente(m, true) : null]);",
                                                   "m.en_attente ? phraseAttente(m, true) : null, estNonLu(m) ? repereNonLu(m) : null]);"),
    "action autre que lu": _remplace(NIV, "onclick: () => agir({ action: 'lu', attente: m,", "onclick: () => agir({ action: 'deposer', attente: m,"),
    "attente_id qui n'est pas m.id": _remplace(NIV, "corps: { attente_id: m.id }, cible: m.id, details: { message: m.id } })",
                                               "corps: { attente_id: 'msg' }, cible: m.id, details: { message: m.id } })"),
    "dialogue de confirmation sur le chemin": _remplace(NIV, "onclick: () => agir({ action: 'lu', attente: m,",
                                                        "onclick: () => ouvrirDialogue(m.resume, () => []) || agir({ action: 'lu', attente: m,"),
    "bouton jamais désactivé en cours": _remplace(NIV, "disabled: attenteEnCours(m.id) || actionsFigees,", "disabled: false,"),
    "« envoyé » ne remplace pas le bouton": _remplace(NIV, "if (attenteEnvoyee(m.id))", "if (false)"),
    "attentes lisent non_lu": _remplace(NIV, "return Array.isArray(etat.attentes_utilisateur) ? etat.attentes_utilisateur : null;",
                                        "return Array.isArray(etat.attentes_utilisateur) ? etat.attentes_utilisateur.concat(etat.fil.filter((m) => m.non_lu === true)) : null;"),
    "en-tête lit non_lu": _remplace(EN, "function sectionNouveautes()",
                                    "const compteNonLu = (etat) => etat.fil.filter((m) => m.non_lu === true).length;\nfunction sectionNouveautes()"),
    "repère en rouge": _remplace("style.css", ".fil-non-lu { font-size: 11px; font-weight: 600; letter-spacing: 0.6px; text-transform: uppercase; color: var(--ambre); }",
                                 ".fil-non-lu { font-size: 11px; font-weight: 600; letter-spacing: 0.6px; text-transform: uppercase; color: var(--rouge); }"),
}


@pytest.mark.parametrize("nom", MUTATIONS)
def test_mutation_detectee(nom, js):
    mutee = MUTATIONS[nom](js)  # hors du raises : la mutation doit s'appliquer, sinon le test serait faux
    with pytest.raises(AssertionError):
        verifier_lu_messages(mutee)


def test_couverture_des_verifications():
    toutes = {n for n, v in globals().items() if n.startswith("verifier_") and callable(v)}
    assert toutes == {"verifier_lu_messages"} and MUTATIONS, sorted(toutes)
