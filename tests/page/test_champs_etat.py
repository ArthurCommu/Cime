"""La table des champs (`champs-etat.md`) décrit exactement les champs de l'exemple d'état, et la page lit ceux qu'elle dit afficher.

`verifier_champs(exemple, table, js)` lève AssertionError ; le test la lance sur les vrais fichiers, et la table MUTATIONS
prouve qu'elle échoue si on retire une ligne de la table, si on en ajoute une fausse, si le sort est inconnu, ou si un champ
« affiché » n'est lu nulle part dans static/.

Les champs de l'exemple (`fixtures/exemple-etat.json`, un instantané complet) sont relevés sur tous les éléments des
listes, notés `liste[].champ`.
"""
import json
import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
STATIC = RACINE / "src" / "cime" / "page" / "static"
EXEMPLE = Path(__file__).resolve().parent / "fixtures" / "exemple-etat.json"
TABLE = Path(__file__).with_name("champs-etat.md")
SORTS = {"affiché", "écarté"}


def _chemins(objet, prefixe=""):
    if isinstance(objet, dict):
        for cle, valeur in objet.items():
            chemin = f"{prefixe}.{cle}" if prefixe else cle
            yield chemin
            yield from _chemins(valeur, chemin)
    elif isinstance(objet, list):
        for element in objet:
            yield from _chemins(element, prefixe + "[]")


def _chemins_de_l_exemple(texte):
    return set(_chemins(json.loads(texte)))


def _lignes_de_la_table(texte):
    """-> {chemin: (sort, pourquoi)}"""
    lignes = {}
    for brut in texte.splitlines():
        m = re.match(r"^\|\s*`([^`]+)`\s*\|\s*([^|]+?)\s*\|\s*(.*?)\s*\|$", brut)
        if m:
            assert m[1] not in lignes, f"champ en double dans la table : {m[1]}"
            lignes[m[1]] = (m[2], m[3])
    return lignes


def _sources_js():
    fichiers = sorted(STATIC.glob("*.js")) + sorted((STATIC / "vues").glob("*.js"))
    assert fichiers, "aucun fichier JS dans static/"
    return "\n".join(f.read_text(encoding="utf-8") for f in fichiers)


def verifier_champs(exemple, table, js):
    attendus, presents = _chemins_de_l_exemple(exemple), _lignes_de_la_table(table)
    manquants, en_trop = sorted(attendus - set(presents)), sorted(set(presents) - attendus)
    assert not manquants and not en_trop, (
        f"champs manquants dans la table : {manquants} ; champs en trop : {en_trop}")
    for chemin, (sort, pourquoi) in presents.items():
        assert sort in SORTS, f"{chemin} : sort « {sort} » inconnu"
        assert pourquoi, f"{chemin} : colonne « où / pourquoi » vide"
        if sort == "affiché":
            nom = chemin.split(".")[-1].split("[]")[-1] or chemin.split(".")[-1]
            assert re.search(rf"\b{re.escape(nom)}\b", js), (
                f"{chemin} est dit affiché mais « {nom} » n'apparaît dans aucun JS de static/")


@pytest.fixture(scope="module")
def exemple():
    return EXEMPLE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def table():
    return TABLE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def js():
    return _sources_js()


def test_table_egale_aux_champs_de_l_exemple(exemple, table, js):
    verifier_champs(exemple, table, js)


# --- preuve par mutation -----------------------------------------------------

def _sans_ligne(table, chemin):
    return "".join(l for l in table.splitlines(True) if not l.startswith(f"| `{chemin}` |"))


MUTATIONS = {
    "ligne retirée": lambda e, t, j: (e, _sans_ligne(t, "agents[].contexte.tokens"), j),
    "faux champ ajouté": lambda e, t, j: (e, t + "| `agents[].champ_invente` | écarté | faux |\n", j),
    "sort inconnu": lambda e, t, j: (e, t.replace("| `fil[].id` | affiché", "| `fil[].id` | peut-être"), j),
    "champ affiché absent du JS": lambda e, t, j: (e, t, j.replace("quoi_faire", "")),
    "exemple modifié": lambda e, t, j: (e.replace('"tache"', '"tache_renommee"'), t, j),
}


@pytest.mark.parametrize("nom", MUTATIONS)
def test_mutation_detectee(nom, exemple, table, js):
    with pytest.raises(AssertionError):
        verifier_champs(*MUTATIONS[nom](exemple, table, js))


def test_couverture_des_verifications():
    """Chaque vérification est éprouvée par au moins une mutation (ici : verifier_champs)."""
    toutes = {n for n, v in globals().items() if n.startswith("verifier_") and callable(v)}
    assert toutes == {"verifier_champs"} and MUTATIONS, sorted(toutes)
