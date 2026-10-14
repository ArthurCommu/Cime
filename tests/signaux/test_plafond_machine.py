"""Le plafond de workers est un réglage de la machine (`reglages.toml`), qu'un projet peut seulement
abaisser ; le facteur le relit à chaque ordre et compte les workers de tous les projets."""
import os
import sqlite3
from pathlib import Path

import pytest

from aide_charge import WORKER, tmux  # noqa: F401
from aide_machine import (  # noqa: F401
    dossier_machine, fixer_machine, poser_manifeste, poser_reglages, projet_libre)
from cime.fondation import plafond
from cime.signaux import ordres


@pytest.fixture
def projet(projet_libre):
    return projet_libre


# --- la fixture qui garde le vrai ~/.config ----------------------------------------------------

def test_la_fixture_place_la_config_sous_un_dossier_temporaire():
    import pwd
    vraie_maison = Path(pwd.getpwuid(os.getuid()).pw_dir)
    chemin = plafond.dossier_reglages()
    assert chemin.name == "cime" and chemin.parent == Path(os.environ["XDG_CONFIG_HOME"])
    assert not chemin.is_relative_to(vraie_maison / ".config")
    assert Path(os.environ["HOME"]) != vraie_maison


def test_sans_xdg_le_chemin_retombe_sur_home_config(monkeypatch):
    monkeypatch.delenv("XDG_CONFIG_HOME")
    assert plafond.dossier_reglages() == Path(os.environ["HOME"]) / ".config" / "cime"
    assert str(plafond.dossier_reglages()).startswith(os.environ["HOME"])


@pytest.mark.parametrize("valeur", ["", "relatif/dossier", "."])
def test_xdg_vide_ou_relatif_retombe_sur_home_config(monkeypatch, valeur):
    monkeypatch.setenv("XDG_CONFIG_HOME", valeur)
    assert plafond.dossier_reglages() == Path(os.environ["HOME"]) / ".config" / "cime"


def test_le_chemin_suit_la_variable_a_chaque_appel(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "a"))
    premier = plafond.dossier_reglages()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "b"))
    assert premier == tmp_path / "a" / "cime" and plafond.dossier_reglages() == tmp_path / "b" / "cime"


# --- 1. lecture du fichier de la machine -------------------------------------------------------

def test_fichier_absent_defaut_3(dossier_machine):
    assert plafond.lire_machine() == (3, "defaut")


@pytest.mark.parametrize("n", [1, 2, 5, 8])
def test_valeur_valide_lue(dossier_machine, n):
    fixer_machine(dossier_machine, n)
    assert plafond.lire_machine() == (n, "fichier")


@pytest.mark.parametrize("ligne", [
    "workers_max = 0", "workers_max = 9", "workers_max = -1", 'workers_max = "2"',
    "workers_max = 2.5", "workers_max = true", "workers_max = [2]", "workers_max = {a = 1}",
    "workers_max = = 3", "pas du toml du tout [[[", "autre = 4", ""])
def test_valeur_mauvaise_defaut_sans_exception(dossier_machine, ligne):
    poser_reglages(dossier_machine, ligne + "\n")
    assert plafond.lire_machine() == (3, "defaut")


def test_fichier_illisible_defaut(dossier_machine):
    dossier_machine.mkdir(parents=True)
    (dossier_machine / "reglages.toml").mkdir()          # un dossier à la place du fichier
    assert plafond.lire_machine() == (3, "defaut")


def test_octets_invalides_defaut(dossier_machine):
    dossier_machine.mkdir(parents=True)
    (dossier_machine / "reglages.toml").write_bytes(b"workers_max = \xff\xfe\n")
    assert plafond.lire_machine() == (3, "defaut")


def test_dossier_de_config_en_fichier_defaut(monkeypatch, tmp_path):
    fichier = tmp_path / "pas-un-dossier"
    fichier.write_text("x")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(fichier))
    assert plafond.lire_machine() == (3, "defaut")


def test_les_autres_cles_sont_ignorees(dossier_machine):
    poser_reglages(dossier_machine, 'theme = "x"\nworkers_max = 6\n[autre]\nworkers_max = 2\n')
    assert plafond.lire_machine() == (6, "fichier")


def test_lecture_sans_cache(dossier_machine):
    fixer_machine(dossier_machine, 2)
    assert plafond.lire_machine()[0] == 2
    fixer_machine(dossier_machine, 7)
    assert plafond.lire_machine()[0] == 7


def test_xdg_relatif_lit_home_config(monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", "relatif")
    home = plafond.dossier_reglages()
    home.mkdir(parents=True)
    (home / "reglages.toml").write_text("workers_max = 4\n")
    assert plafond.lire_machine() == (4, "fichier")


# --- 2. le plus bas des deux -------------------------------------------------------------------

@pytest.mark.parametrize("machine,projet_max,attendu", [
    (5, 2, (2, "projet")),
    (2, 5, (2, "machine")),
    (3, 3, (3, "machine")),
    (4, None, (4, "machine")),
    (8, 1, (1, "projet")),
    (1, 8, (1, "machine")),
])
def test_en_vigueur_est_le_plus_bas(machine, projet_max, attendu):
    assert plafond.en_vigueur(machine, projet_max) == attendu


def test_le_projet_n_est_jamais_au_dessus(projet, tmux, dossier_machine):  # noqa: F811
    tmux["sessions"] = set()
    fixer_machine(dossier_machine, 2)
    poser_manifeste(projet, 6)
    assert ordres.plafond_en_vigueur(projet) == (2, "machine")
    poser_manifeste_remplace(projet, 1)
    assert ordres.plafond_en_vigueur(projet) == (1, "projet")


def poser_manifeste_remplace(projet, n):
    fichier = projet / ".orga" / "projet.toml"
    lignes = [ligne for ligne in fichier.read_text().splitlines()
              if not ligne.startswith("workers_max") and ligne != "[charge]"]
    fichier.write_text("\n".join(lignes) + f"\n[charge]\nworkers_max = {n}\n")


def test_projet_sans_cle_pas_de_limite(projet, tmux, dossier_machine):  # noqa: F811
    tmux["sessions"] = set()
    fixer_machine(dossier_machine, 7)
    assert plafond.plafond_projet(projet) is None
    assert ordres.plafond_en_vigueur(projet) == (7, "machine")


def test_defaut_machine_sans_fichier_ni_projet(projet, tmux):  # noqa: F811
    tmux["sessions"] = set()
    assert ordres.plafond_en_vigueur(projet) == (3, "machine")


# --- le manifeste : `workers_max` optionnel ----------------------------------------------------

def test_manifeste_sans_cle_none(projet):
    from cime.fondation.projet import lire_manifeste
    assert lire_manifeste(projet).workers_max is None


@pytest.mark.parametrize("valeur", ["0", "-1", "true", '"2"', "1.5"])
def test_manifeste_valeur_invalide_refusee(projet, valeur):
    from cime.fondation.projet import ErreurProjet, lire_manifeste
    poser_manifeste(projet, valeur)
    with pytest.raises(ErreurProjet, match=r"charge\.workers_max"):
        lire_manifeste(projet)


def test_manifeste_pas_de_borne_haute(projet):
    from cime.fondation.projet import lire_manifeste
    poser_manifeste(projet, 50)
    assert lire_manifeste(projet).workers_max == 50


# --- 3. le facteur -----------------------------------------------------------------------------

@pytest.fixture
def machine(monkeypatch):
    etat = {"vivantes": set(), "executes": []}
    monkeypatch.setattr(ordres, "_sessions_vivantes", lambda: set(etat["vivantes"]))

    def executer(projet, ordre):
        etat["executes"].append(ordre["id"])
        if ordre["verbe"] == "lancer" and ordre["parametres"].get("role") == "worker":
            etat["vivantes"].add(f"essai-worker-x-{ordre['parametres']['tache']}")
        return "execute", 0, ""

    monkeypatch.setattr(ordres, "executer", executer)
    return etat


def lancer(projet, tache):
    return ordres.demander(projet, "coord-x", "lancer", f"worker-x-{tache}",
                           {**WORKER, "tache": tache})


def test_le_plafond_change_dans_le_fichier_le_tour_suivant(projet, machine, dossier_machine):  # noqa: F811
    fixer_machine(dossier_machine, 1)
    machine["vivantes"] = {"cc-worker-y-z"}
    lancer(projet, "a")
    ordres.facteur_une_fois(projet)
    assert machine["executes"] == []                      # 1 actif, plafond 1 : attend
    fixer_machine(dossier_machine, 2)                     # sans redémarrer
    ordres.facteur_une_fois(projet)
    assert machine["executes"] == [1]                     # la place s'est ouverte
    lancer(projet, "b")
    ordres.facteur_une_fois(projet)
    assert machine["executes"] == [1]                     # 2 actifs, plafond 2
    fixer_machine(dossier_machine, 3)
    ordres.facteur_une_fois(projet)
    assert machine["executes"] == [1, 2]


def test_baisser_le_plafond_ne_tue_rien_mais_retient(projet, machine, dossier_machine):  # noqa: F811
    fixer_machine(dossier_machine, 4)
    machine["vivantes"] = {"cc-worker-y-a", "cc-worker-y-b", "ai-worker-q-c"}
    fixer_machine(dossier_machine, 2)
    lancer(projet, "n")
    ordres.facteur_une_fois(projet)
    assert machine["executes"] == [] and len(machine["vivantes"]) == 3


def test_le_compte_porte_sur_tous_les_prefixes(projet, machine, dossier_machine):  # noqa: F811
    fixer_machine(dossier_machine, 2)
    machine["vivantes"] = {"cc-worker-a-1", "ai-worker-b-2"}       # deux projets
    assert ordres.plafond_atteint(projet) == (True, 2, 2)
    lancer(projet, "c")
    ordres.facteur_une_fois(projet)
    assert machine["executes"] == []
    machine["vivantes"].discard("ai-worker-b-2")
    ordres.facteur_une_fois(projet)
    assert machine["executes"] == [1]


def test_le_plafond_du_projet_retient_aussi(projet, machine, dossier_machine):  # noqa: F811
    fixer_machine(dossier_machine, 6)
    poser_manifeste(projet, 1)
    machine["vivantes"] = {"cc-worker-a-1"}
    lancer(projet, "c")
    ordres.facteur_une_fois(projet)
    assert machine["executes"] == []


def test_detail_par_projet():
    sessions = {"cc-worker-a-1", "cc-worker-b-2", "ai-worker-c-3", "cc-coord-a", "bureau",
                "worker-x-t", "x-worker-y-z-w"}
    assert ordres.workers_par_projet(sessions) == {"cc": 2, "ai": 1, "x": 1}
    assert ordres.workers_par_projet(set()) == {}


def test_le_prefixe_est_ce_qui_precede_worker():
    assert ordres.prefixe_de_session("cc-worker-a-1") == "cc"
    assert ordres.prefixe_de_session("a-b-worker-x-y") == "a-b"


# --- 7. le registre ne porte plus ce réglage ---------------------------------------------------

def test_une_ligne_au_registre_ne_change_rien(projet, tmux, dossier_machine):  # noqa: F811
    from cime.fondation import registre
    tmux["sessions"] = set()
    fixer_machine(dossier_machine, 5)
    conn = registre.ouvrir(projet)
    with conn:
        conn.execute("INSERT INTO reglages_projet (horodatage, cle, valeur, auteur, details)"
                     " VALUES (?, 'workers_max', '1', 'utilisateur', NULL)", (registre.horodatage(),))
    conn.close()
    assert ordres.plafond_en_vigueur(projet) == (5, "machine")


def test_la_lecture_n_ouvre_pas_le_registre(projet, tmux, dossier_machine, monkeypatch):  # noqa: F811
    tmux["sessions"] = set()
    fixer_machine(dossier_machine, 5)

    def interdit(*a, **k):
        raise AssertionError("registre ouvert")

    monkeypatch.setattr(sqlite3, "connect", interdit)
    assert ordres.plafond_en_vigueur(projet) == (5, "machine")
    assert ordres.plafond_atteint(projet) == (False, 0, 5)


def test_plafond_py_ne_connait_plus_le_registre():
    source = Path(plafond.__file__).read_text()
    assert "reglages_projet" not in source and "sqlite3" not in source
    assert "registre.ouvrir" not in source and "ouvrir(" not in source
