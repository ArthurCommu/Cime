import json
import subprocess
import types
from pathlib import Path

import pytest

from cime.fondation import equipe, init
from cime.fondation.nom import VAR_AGENT, VAR_PROJET
from cime.fondation.registre import ouvrir


@pytest.fixture
def projet(tmp_path, monkeypatch):
    """Projet réel installé par `init` dans un dépôt git jetable, avec un commit sur main."""
    monkeypatch.setattr(init, "executable_cime", lambda: "/opt/outils/bin/cime")
    racine = tmp_path / "depot"
    init.installer(types.SimpleNamespace(dossier=str(racine), utilisateur="Camille",
                                         nom_projet=None, prefixe=None))
    git(racine, "add", "-A")
    git(racine, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    monkeypatch.setenv(VAR_PROJET, str(racine))
    monkeypatch.setenv(VAR_AGENT, "assistant")
    return racine


def git(racine, *a):
    return subprocess.run(["git", "-C", str(racine), *a], capture_output=True,
                          text=True, check=True).stdout


def args(nom, blanc=False):
    return types.SimpleNamespace(nom=nom, essai_a_blanc=blanc)


def instantane(racine: Path):
    return {str(p.relative_to(racine)): p.read_bytes() if p.is_file() else None
            for p in racine.rglob("*") if ".git" not in p.relative_to(racine).parts}


def test_creation_complete(projet, capsys):
    assert equipe.executer(args("alpha")) == 0
    d = projet / ".orga/teams/alpha"
    assert "alpha" in (d / "CLAUDE.md").read_text()
    assert "<équipe>" not in (d / "CLAUDE.md").read_text()
    mandat = (d / "mandate.md").read_text()
    assert "# Mandat — équipe alpha" in mandat and "<!--" not in mandat.split("## Bloc 1")[0]
    for sous in equipe.SOUS_DOSSIERS:
        assert (d / sous / ".gitkeep").is_file()
    wt = projet / ".orga/worktrees/alpha"
    assert (wt / ".git").exists()
    assert git(wt, "branch", "--show-current").strip() == "equipe/alpha"
    assert git(projet, "rev-parse", "equipe/alpha") == git(projet, "rev-parse", "main")
    assert git(projet, "branch", "--show-current").strip() == "main"
    assert "cime lancer coord alpha" in capsys.readouterr().out


def test_second_passage_tout_deja_present(projet, capsys):
    equipe.executer(args("alpha"))
    avant = instantane(projet)
    capsys.readouterr()
    assert equipe.executer(args("alpha")) == 0
    sortie = capsys.readouterr().out
    assert "ajouté" not in sortie.replace("déjà présent", "")
    assert instantane(projet) == avant


def test_claude_md_existant_laisse(projet):
    d = projet / ".orga/teams/alpha"
    d.mkdir(parents=True)
    (d / "CLAUDE.md").write_text("adapté")
    assert equipe.executer(args("alpha")) == 0
    assert (d / "CLAUDE.md").read_text() == "adapté"
    assert (d / "mandate.md").is_file()


def test_gabarit_du_projet_prime(projet):
    g = projet / ".orga/templates/coordinateur-CLAUDE.md"
    g.write_text("adapté pour <équipe>\n")
    equipe.executer(args("alpha"))
    assert (projet / ".orga/teams/alpha/CLAUDE.md").read_text() == "adapté pour alpha\n"


@pytest.mark.parametrize("nom", ["assistant", "verification", "utilisateur", "Majuscule", "a_b",
                                 "a/b", ""])
def test_refus_nom(projet, nom, capsys):
    avant = instantane(projet)
    assert equipe.executer(args(nom)) == 2
    assert instantane(projet) == avant


def test_l_identite_de_l_utilisateur_n_est_pas_un_nom_d_equipe(projet, capsys):
    """Le motif des identités valides lit `utilisateur` comme l'utilisateur, jamais comme une équipe."""
    assert equipe.executer(args("utilisateur")) == 2
    assert "réservé" in capsys.readouterr().err
    assert equipe.executer(args("utilisateur", blanc=True)) == 2


def test_integration_n_est_plus_speciale_par_defaut_mais_le_reste_ou_le_manifeste_la_declare(projet, capsys):
    """Registre 2.0 : `cime init` n'installe plus l'équipe intégration (le nom reste libre) ; un
    projet qui la déclare encore dans `equipes_speciales` la garde réservée."""
    manifeste = projet / ".orga" / "projet.toml"
    assert "integration" not in manifeste.read_text()
    manifeste.write_text(manifeste.read_text().replace(
        'equipes_speciales = ["assistant", "verification"]',
        'equipes_speciales = ["assistant", "integration", "verification"]'))
    avant = instantane(projet)
    assert equipe.executer(args("integration")) == 2
    assert instantane(projet) == avant


def test_chemin_de_worktree_occupe(projet, capsys):
    (projet / ".orga/worktrees/alpha").mkdir(parents=True)
    assert equipe.executer(args("alpha")) == 2
    assert not (projet / ".orga/teams/alpha").exists()
    assert "equipe/alpha" not in git(projet, "branch")


def test_branche_existante_reutilisee(projet):
    git(projet, "branch", "equipe/alpha")
    assert equipe.executer(args("alpha")) == 0
    assert (projet / ".orga/worktrees/alpha/.git").exists()


def test_essai_a_blanc(projet, capsys):
    avant = instantane(projet)
    assert equipe.executer(args("alpha", blanc=True)) == 0
    assert instantane(projet) == avant
    assert not (projet / ".orga/worktrees/alpha").exists()
    assert "equipe/alpha" not in git(projet, "branch")
    assert "serait ajouté" in capsys.readouterr().out


def messages(projet):
    conn = ouvrir(projet)
    try:
        return conn.execute("SELECT de, a, nature, resume, fichier, equipe FROM messages").fetchall()
    finally:
        conn.close()


def evenements(projet, nom):
    conn = ouvrir(projet)
    try:
        return [(a, json.loads(d)) for a, d in conn.execute(
            "SELECT agent, details FROM evenements WHERE evenement = ?", (nom,))]
    finally:
        conn.close()


def test_creation_inscrite_au_registre(projet, capsys):
    """D15 : la création est un événement `EquipeCreee`, jamais une ligne `messages`."""
    assert equipe.executer(args("alpha")) == 0
    assert messages(projet) == []
    assert evenements(projet, "EquipeCreee") == [(None, {
        "equipe": "alpha", "auteur": "assistant", "mandat": ".orga/teams/alpha/mandate.md"})]
    assert "inscrit : événement #" in capsys.readouterr().out


@pytest.mark.parametrize("variable", [VAR_PROJET, VAR_AGENT])
def test_refus_sans_variable_avant_creation(projet, variable, monkeypatch, capsys):
    avant = instantane(projet)
    monkeypatch.delenv(variable)
    assert equipe.executer(args("alpha")) == 2
    assert variable in capsys.readouterr().err
    assert instantane(projet) == avant
    assert not (projet / ".orga/worktrees/alpha").exists()
    assert "equipe/alpha" not in git(projet, "branch")


def test_essai_a_blanc_sans_variables(projet, monkeypatch, capsys):
    monkeypatch.delenv(VAR_AGENT)
    monkeypatch.delenv(VAR_PROJET)
    monkeypatch.chdir(projet)
    avant = instantane(projet)
    assert equipe.executer(args("alpha", blanc=True)) == 0
    assert instantane(projet) == avant


def test_second_passage_n_inscrit_rien(projet, capsys):
    equipe.executer(args("alpha"))
    capsys.readouterr()
    equipe.executer(args("alpha"))
    assert messages(projet) == [] and len(evenements(projet, "EquipeCreee")) == 1
    assert "inscrit :" not in capsys.readouterr().out


def test_aide_dit_la_decision(capsys):
    from cime.cli import main
    with pytest.raises(SystemExit):
        main(["equipe", "--help"])
    sortie = " ".join(capsys.readouterr().out.split())
    assert "sans lancer son coordinateur" in sortie
    assert "décision de l'utilisateur" in sortie


def test_refus_hors_assistant_journalise_rien_cree(projet, monkeypatch, capsys):
    monkeypatch.setenv(VAR_AGENT, "coord-x")
    assert equipe.executer(args("alpha")) == 2
    assert "Assistant" in capsys.readouterr().err
    assert not (projet / ".orga/worktrees/alpha").exists()
    assert "equipe/alpha" not in git(projet, "branch")
    assert not (projet / ".orga/teams/alpha").exists()
    assert messages(projet) == []                      # D15 : pas de faux message au coordinateur
    assert evenements(projet, "EquipeRefusee") == [(None, {
        "equipe": "alpha", "auteur": "coord-x", "motif": "création d'équipe réservée à l'Assistant"})]


def test_worktree_cree_dans_le_projet_sans_dossier_parent(projet):
    """`.orga/worktrees/` n'existe pas encore : git crée le dossier avec le worktree."""
    (projet / ".orga/worktrees").rmdir()  # `init` le crée vide ; ici il manque
    assert equipe.executer(args("alpha")) == 0
    assert (projet / ".orga/worktrees/alpha/.git").exists()
    assert ".orga/worktrees/alpha" in git(projet, "worktree", "list")
