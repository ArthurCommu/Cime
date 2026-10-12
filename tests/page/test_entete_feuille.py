"""La tête de la feuille « Ce qui t'attend » tient sur une ligne au téléphone.

Pas de navigateur : un calcul, dans le style de test_entete_largeur.py. À 320, 360, 375 et 390 px, `largeur_tete` additionne la largeur naturelle des éléments
de la tête de la feuille (titre, « Fermer », et ce qui s'y trouverait en plus) avec les marges et le gap lus dans style.css, et la compare à la largeur de
l'écran (la feuille pleine écran). Les largeurs de texte sont estimées : 0,52 em par caractère pour le titre en gras, 0,46 em pour « Fermer » ; l'interrupteur
« Mode autonome » mesure 142 px (mesuré dans un navigateur : avec lui, la tête cassait sous ≈ 385 px). Les règles qui empêchent la coupure sont lues telles
quelles : « Fermer » en `flex: none` + `nowrap` (un bouton ne se coupe jamais au milieu d'un mot), le titre en `nowrap` et abrégé par une ellipse si la place manque.

Même convention que test_supervision_coince_dependances.py : `verifier_tete(css, commun, mobile)` lève AssertionError, la table MUTATIONS prouve qu'elle échoue quand on casse chaque règle.
"""
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "src" / "cime" / "page" / "static"
LARGEURS = (320, 360, 375, 390)
TITRE = "Ce qui t’attend"
INTERRUPTEUR = 142  # px, mesuré dans un navigateur
EM_TITRE, EM_FERMER = 0.52, 0.46


def _regle(css, selecteur):
    m = re.search(r"(?:^|\n) *" + re.escape(selecteur) + r" \{([^}]*)\}", css)
    assert m, selecteur
    corps = re.sub(r"/\*.*?\*/", "", m.group(1), flags=re.S)
    resultat = {}
    for d in corps.split(";"):
        if d.strip():
            nom, _, valeur = d.partition(":")
            resultat[nom.strip()] = valeur.strip()
    return resultat


def _px(valeur):
    return [int(x) for x in re.findall(r"(\d+)px", valeur)]


def _enfants_de_la_tete(commun):
    """Les enfants de <header class="feuille-tete">, dans l'ordre : 'titre', 'extra' (emplacement de tête), 'fermer'."""
    m = re.search(r"el\('header', \{ class: 'feuille-tete' \}, (.*?)\n    corps\)\);", commun, flags=re.S)
    assert m, "la tête de la feuille"
    corps = m.group(1)
    enfants = []
    for jeton, nom in (("intitule", "titre"), ("extra", "extra"), ("feuille-fermer", "fermer")):
        if jeton in corps:
            enfants.append((corps.index(jeton), nom))
    return [nom for _, nom in sorted(enfants)]


def largeur_tete(css, commun, mobile):
    """(largeur naturelle des enfants avec gaps et marges, largeur du titre, largeur de « Fermer »)."""
    tete = _regle(css, ".feuille-tete")
    padding = _px(tete["padding"])  # « 0 16px 8px » : haut, côtés, bas
    cotes = padding[0] * 2  # 16 + 16 (le « 0 » n'est pas capté par _px)
    gap = _px(tete["gap"])[0]
    bouton = _regle(css, ".bouton")
    pad_bouton = _px(bouton["padding"])[1] * 2  # « 9px 14px »
    fermer = len("Fermer") * EM_FERMER * _px(bouton["font-size"])[0] + pad_bouton + 2  # + bordures
    titre = len(TITRE) * EM_TITRE * _px(_regle(css, ".feuille-tete h2")["font-size"])[0]
    largeurs = {"titre": titre, "fermer": fermer, "extra": INTERRUPTEUR}
    enfants = _enfants_de_la_tete(commun)
    # l'emplacement de tête ne compte que si le code de la page y met quelque chose
    if "extra" in enfants and "enTete" not in mobile:
        enfants.remove("extra")
    total = sum(largeurs[e] for e in enfants) + gap * (len(enfants) - 1) + cotes
    return total, titre, fermer


def verifier_tete(css, commun, mobile):
    # 1. « Fermer » ne se coupe jamais : il ne rétrécit pas et ne passe pas à la ligne
    fermer = _regle(css, ".feuille-fermer")
    assert fermer.get("flex") == "none", fermer
    assert fermer.get("white-space") == "nowrap", fermer
    # 2. le titre tient sur une ligne ; si la place manque, il s'abrège par une ellipse
    titre = _regle(css, ".feuille-tete h2")
    assert titre.get("white-space") == "nowrap", titre
    assert titre.get("overflow") == "hidden" and titre.get("text-overflow") == "ellipsis" and titre.get("min-width") == "0", titre
    # 3. la tête est le titre et « Fermer », dans cet ordre, rien entre
    assert _enfants_de_la_tete(commun) == ["titre", "fermer"], _enfants_de_la_tete(commun)
    assert "enTete" not in mobile and "enTete" not in commun
    # 4. le calcul : à chaque largeur de téléphone, la tête entière tient sans rien couper
    for largeur in LARGEURS:
        total, _, _ = largeur_tete(css, commun, mobile)
        assert total <= largeur, (largeur, round(total))
    # 5. la tête garde sa mise en ligne : une rangée, les éléments centrés, « Fermer » à droite
    tete = _regle(css, ".feuille-tete")
    assert tete.get("display") == "flex" and tete.get("align-items") == "center" and tete.get("justify-content") == "space-between", tete


@pytest.fixture(scope="module")
def fichiers():
    return {n: (STATIC / n).read_text(encoding="utf-8") for n in ("style.css", "commun.js", "vues/mobile.js")}


def test_tete_de_feuille(fichiers):
    verifier_tete(fichiers["style.css"], fichiers["commun.js"], fichiers["vues/mobile.js"])


def test_la_marge_est_confortable(fichiers):
    # à 320 px, la tête (titre + « Fermer ») laisse au moins 40 px libres : un titre un peu plus long ne casse pas
    total, _, _ = largeur_tete(fichiers["style.css"], fichiers["commun.js"], fichiers["vues/mobile.js"])
    assert 320 - total >= 40, round(total)


def test_avec_l_interrupteur_dans_la_tete_la_tete_casse(fichiers):
    """Le défaut d'origine (318c00e) : le calcul le retrouve — la tête ne tient plus à 375 px."""
    commun = fichiers["commun.js"].replace("el('header', { class: 'feuille-tete' }, intitule,\n", "el('header', { class: 'feuille-tete' }, intitule, extra,\n")
    total, _, _ = largeur_tete(fichiers["style.css"], commun, "enTete: [interrupteurMode(etat)]")
    assert total > 375 and total > 360 and total > 320, round(total)
    assert total <= 390 + 30  # ... et il ne tient presque qu'à 390 px, comme la mesure en navigateur l'a montré


def _remplace(fichier, ancien, nouveau):
    def mutation(f):
        assert ancien in f[fichier], ancien
        return {**f, fichier: f[fichier].replace(ancien, nouveau, 1)}
    return mutation


MUTATIONS = {
    "Fermer sans nowrap": _remplace("style.css", ".feuille-fermer { flex: none; white-space: nowrap;", ".feuille-fermer { flex: none;"),
    "Fermer qui rétrécit": _remplace("style.css", ".feuille-fermer { flex: none; white-space: nowrap;", ".feuille-fermer { white-space: nowrap;"),
    "Fermer qui se coupe": _remplace("style.css", ".feuille-fermer { flex: none; white-space: nowrap;", ".feuille-fermer { white-space: normal;"),
    "titre sans nowrap": _remplace("style.css", "text-overflow: ellipsis; white-space: nowrap; font-size: 16px;", "text-overflow: ellipsis; font-size: 16px;"),
    "titre sans ellipse": _remplace("style.css", "overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 16px;", "white-space: nowrap; font-size: 16px;"),
    "titre sans min-width": _remplace("style.css", ".feuille-tete h2 { margin: 0; min-width: 0;", ".feuille-tete h2 { margin: 0;"),
    "interrupteur remis dans la tête": lambda f: {**f, "commun.js": f["commun.js"].replace("{ class: 'feuille-tete' }, intitule,\n", "{ class: 'feuille-tete' }, intitule, extra,\n", 1),
                                                 "vues/mobile.js": f["vues/mobile.js"] + "\n// enTete: [interrupteurMode(etat)]\n"},
    "tête dans l'autre ordre": _remplace("commun.js", "{ class: 'feuille-tete' }, intitule,\n      el('button', { type: 'button', class: 'bouton feuille-fermer', onclick: fermer }, 'Fermer')",
                                         "{ class: 'feuille-tete' }, el('button', { type: 'button', class: 'bouton feuille-fermer', onclick: fermer }, 'Fermer'),\n      intitule"),
    "marges de 120 px": _remplace("style.css", "gap: 8px; padding: 0 16px 8px; }\n.feuille-tete h2", "gap: 8px; padding: 0 120px 8px; }\n.feuille-tete h2"),
    "tête en colonne": _remplace("style.css", ".feuille-tete { flex: none; display: flex;", ".feuille-tete { flex: none; display: block;"),
}


@pytest.mark.parametrize("nom", MUTATIONS)
def test_mutation_detectee(nom, fichiers):
    mutee = MUTATIONS[nom](fichiers)
    with pytest.raises(AssertionError):
        verifier_tete(mutee["style.css"], mutee["commun.js"], mutee["vues/mobile.js"])
