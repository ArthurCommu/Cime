"""Manifeste : la table `[charge]` et son réglage `workers_max`."""
import pytest

from cime.fondation.projet import ErreurProjet, lire_manifeste

BASE = '''nom = "Essai"
prefixe = "essai"
branche_reference = "main"
branche_equipe = "equipe/{equipe}"
worktree_equipe = ".orga/worktrees/{equipe}"
equipes_speciales = ["assistant"]
modele_assistant = "m"
modele_coordinateur = "m"
'''


def manifeste(tmp_path, suite=""):
    racine = tmp_path / "depot"
    (racine / ".orga").mkdir(parents=True)
    (racine / ".orga" / "projet.toml").write_text(BASE + suite)
    return racine


def test_workers_max_absent_vaut_none(tmp_path):
    assert lire_manifeste(manifeste(tmp_path)).workers_max is None


def test_table_charge_sans_la_cle_vaut_none(tmp_path):
    assert lire_manifeste(manifeste(tmp_path, "[charge]\n")).workers_max is None


def test_workers_max_lu(tmp_path):
    assert lire_manifeste(manifeste(tmp_path, "[charge]\nworkers_max = 3\n")).workers_max == 3


@pytest.mark.parametrize("valeur", ["0", "-1", '"2"', "true", "1.5", "[2]"])
def test_workers_max_invalide_refuse(tmp_path, valeur):
    racine = manifeste(tmp_path, f"[charge]\nworkers_max = {valeur}\n")
    with pytest.raises(ErreurProjet, match=r"charge\.workers_max"):
        lire_manifeste(racine)


def test_charge_qui_n_est_pas_une_table_refusee(tmp_path):
    racine = tmp_path / "depot"
    (racine / ".orga").mkdir(parents=True)
    # `charge` doit précéder toute table pour rester une clé de premier niveau
    texte = BASE.replace('nom = "Essai"', 'charge = 2\nnom = "Essai"')
    (racine / ".orga" / "projet.toml").write_text(texte)
    with pytest.raises(ErreurProjet, match=r"\[charge\]"):
        lire_manifeste(racine)


def test_le_gabarit_declare_le_plafond_a_1():
    import tomllib
    from pathlib import Path

    gabarit = (Path(__file__).resolve().parents[2] / "src" / "cime" / "gabarits"
               / ".orga" / "projet.toml")
    assert tomllib.loads(gabarit.read_text())["charge"]["workers_max"] == 1


# --- charge.coordinateur_repos_minutes ----------------------------------------------------------

def test_coordinateur_repos_minutes_vaut_20_par_defaut(tmp_path):
    assert lire_manifeste(manifeste(tmp_path)).coordinateur_repos_minutes == 20


def test_table_charge_sans_la_cle_repos_vaut_20(tmp_path):
    racine = manifeste(tmp_path, "[charge]\nworkers_max = 2\n")
    assert lire_manifeste(racine).coordinateur_repos_minutes == 20


def test_coordinateur_repos_minutes_lu(tmp_path):
    racine = manifeste(tmp_path, "[charge]\ncoordinateur_repos_minutes = 5\n")
    assert lire_manifeste(racine).coordinateur_repos_minutes == 5


def test_coordinateur_repos_minutes_zero_est_lu(tmp_path):
    racine = manifeste(tmp_path, "[charge]\ncoordinateur_repos_minutes = 0\n")
    assert lire_manifeste(racine).coordinateur_repos_minutes == 0


@pytest.mark.parametrize("valeur", ["-1", '"20"', "true", "20.5", "[20]"])
def test_coordinateur_repos_minutes_invalide_refuse(tmp_path, valeur):
    racine = manifeste(tmp_path, f"[charge]\ncoordinateur_repos_minutes = {valeur}\n")
    with pytest.raises(ErreurProjet, match=r"charge\.coordinateur_repos_minutes"):
        lire_manifeste(racine)


def test_repos_et_plafond_se_lisent_ensemble(tmp_path):
    racine = manifeste(tmp_path, "[charge]\nworkers_max = 3\ncoordinateur_repos_minutes = 7\n")
    lu = lire_manifeste(racine)
    assert (lu.workers_max, lu.coordinateur_repos_minutes) == (3, 7)


def test_charge_qui_n_est_pas_une_table_refusee_aussi_pour_le_repos(tmp_path):
    racine = tmp_path / "depot"
    (racine / ".orga").mkdir(parents=True)
    texte = BASE.replace('nom = "Essai"', 'charge = 2\nnom = "Essai"')
    (racine / ".orga" / "projet.toml").write_text(texte)
    with pytest.raises(ErreurProjet, match=r"\[charge\]"):
        lire_manifeste(racine)


def test_le_gabarit_declare_le_repos_des_coordinateurs_a_20():
    import tomllib
    from pathlib import Path

    gabarit = (Path(__file__).resolve().parents[2] / "src" / "cime" / "gabarits"
               / ".orga" / "projet.toml")
    assert tomllib.loads(gabarit.read_text())["charge"]["coordinateur_repos_minutes"] == 20
