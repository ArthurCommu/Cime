"""Les fabriques de projet des tests refusent tout dossier qui n'est pas jetable : jamais le dépôt."""
from pathlib import Path

import pytest

from aide import DEPOT, exiger_jetable, fabriquer_projet


def test_fabriquer_projet_refuse_le_depot_et_son_worktree():
    with pytest.raises(ValueError):
        fabriquer_projet(DEPOT)
    with pytest.raises(ValueError):
        fabriquer_projet(DEPOT.parent)


def test_refus_d_un_dossier_avec_git(tmp_path):
    (tmp_path / "depot" / ".git").mkdir(parents=True)
    with pytest.raises(ValueError, match=".git"):
        exiger_jetable(tmp_path / "depot")
    assert not (tmp_path / "depot" / ".orga").exists()


def test_refus_d_un_dossier_hors_du_temporaire():
    with pytest.raises(ValueError, match="pas sous"):
        exiger_jetable(Path("/usr/local/un-projet"))


def test_un_dossier_jetable_est_accepte(tmp_path):
    racine = fabriquer_projet(tmp_path / "p")
    assert (racine / ".orga" / "projet.toml").is_file()
