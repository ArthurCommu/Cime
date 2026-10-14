"""Deux fichiers de test de même nom, hors d'un paquet (`__init__.py`), cassent la collecte de
`pytest tests` (« import file mismatch ») : chaque équipe ne lance que son dossier et ne le voit
pas, la CI qui lance tout le voit."""
from collections import defaultdict
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]


def _dans_un_paquet(fichier: Path) -> bool:
    return (fichier.parent / "__init__.py").exists()


def test_noms_de_fichiers_de_test_uniques_hors_paquet():
    par_nom = defaultdict(list)
    for fichier in TESTS.rglob("test_*.py"):
        if not _dans_un_paquet(fichier):
            par_nom[fichier.name].append(str(fichier.relative_to(TESTS)))
    doublons = {nom: chemins for nom, chemins in par_nom.items() if len(chemins) > 1}
    assert not doublons, f"renomme l'un des fichiers : {doublons}"
