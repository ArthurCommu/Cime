import pytest

from conftest import DEPOT, exiger_jetable


def test_ecrire_un_manifeste_dans_le_depot_est_refuse():
    with pytest.raises(ValueError):
        (DEPOT / ".orga" / "projet.toml").write_text("nom = \"Essai\"\n")


def test_une_fabrique_refuse_un_dossier_avec_git(tmp_path):
    (tmp_path / "d" / ".git").mkdir(parents=True)
    with pytest.raises(ValueError, match=".git"):
        exiger_jetable(tmp_path / "d")


def test_un_dossier_jetable_est_accepte(tmp_path):
    (tmp_path / "d" / ".orga").mkdir(parents=True)
    (tmp_path / "d" / ".orga" / "projet.toml").write_text("x")
    assert exiger_jetable(tmp_path / "d")
