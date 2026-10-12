"""Fixtures du banc de bout en bout : projet jetable (préfixe `es`, équipes alpha et beta), dépôt git
jetable, horloge simulée unique, faux tmux branché sur tous les seams `_tmux`."""
import subprocess
import textwrap
from pathlib import Path

import pytest

from aide import exiger_jetable
from e2e.banc import Banc, FauxTmuxE2E, Horloge, brancher_horloge

from cime.fondation.nom import VAR_AGENT, VAR_PROJET
from cime.fondation.registre import ouvrir

MANIFESTE = textwrap.dedent("""\
    nom = "Banc"
    prefixe = "es"
    branche_reference = "main"
    branche_equipe = "equipe/{equipe}"
    worktree_equipe = ".orga/worktrees/{equipe}"
    equipes_speciales = ["assistant"]
    modele_assistant = "modele-assistant"
    modele_coordinateur = "modele-coord"

    [contrats]
    etat = ["alpha"]
    """)
EQUIPES = ("alpha", "beta")
SEAMS_TMUX = ("cime.signaux.livraison", "cime.signaux.ordres", "cime.fondation.envoyer",
              "cime.fondation.terminer", "cime.fondation.compacter", "cime.observation.tmux")


def _git(*args, cwd):
    subprocess.run(["git", "-c", "user.name=banc", "-c", "user.email=banc@banc", *args],
                   cwd=cwd, check=True, capture_output=True)


def _arborescence(racine: Path) -> None:
    for e in EQUIPES:
        for sous in ("tasks/todo", "tasks/in-progress", "tasks/done", "reports", "conversations"):
            (racine / ".orga" / "teams" / e / sous).mkdir(parents=True, exist_ok=True)
        (racine / ".orga" / "teams" / e / "mandate.md").write_text(f"# {e}\n")
    (racine / ".orga" / "projet.toml").write_text(MANIFESTE)


@pytest.fixture
def projet(tmp_path, monkeypatch):
    """Projet jetable complet, sans git. `CIME_PROJET` pointe dessus, jamais sur le vrai."""
    racine = exiger_jetable(tmp_path / "projet")
    racine.mkdir()
    _arborescence(racine)
    (racine / "note.md").write_text("note")
    ouvrir(racine).close()
    monkeypatch.setenv(VAR_PROJET, str(racine))
    monkeypatch.delenv(VAR_AGENT, raising=False)
    monkeypatch.delenv("CLAUDECODE", raising=False)
    return racine


@pytest.fixture
def depot(tmp_path, monkeypatch):
    """Dépôt git jetable : `main`, `equipe/alpha` en avance d'un commit, et son worktree
    `.orga/worktrees/alpha`. Le projet est le dépôt lui-même (jamais le dépôt réel)."""
    racine = tmp_path / "depot"
    racine.mkdir()
    _arborescence(racine)
    (racine / "src").mkdir()
    (racine / "src" / "base.txt").write_text("base\n")
    (racine / ".gitignore").write_text(".orga/etat/\n.orga/worktrees/\n")
    _git("init", "-q", "-b", "main", cwd=racine)
    _git("add", ".", cwd=racine)
    _git("commit", "-q", "-m", "init", cwd=racine)
    _git("branch", "equipe/alpha", cwd=racine)
    _git("worktree", "add", "-q", str(racine / ".orga" / "worktrees" / "alpha"), "equipe/alpha", cwd=racine)
    travail = racine / ".orga" / "worktrees" / "alpha"
    (travail / "src" / "alpha.txt").write_text("alpha\n")
    _git("add", "src/alpha.txt", cwd=travail)
    _git("commit", "-q", "-m", "alpha", cwd=travail)
    ouvrir(racine).close()
    monkeypatch.setenv(VAR_PROJET, str(racine))
    monkeypatch.delenv(VAR_AGENT, raising=False)
    monkeypatch.delenv("CLAUDECODE", raising=False)
    return racine


@pytest.fixture
def horloge(monkeypatch):
    """L'horloge simulée unique : `horloge.avance(minutes=5)` avance TOUT le code de Cime."""
    h = Horloge()
    brancher_horloge(h, monkeypatch)
    return h


@pytest.fixture
def tmux(monkeypatch, horloge):
    """Le faux tmux, branché sur tous les seams `_tmux` ; une session `es-<agent>` par agent."""
    import importlib
    faux = FauxTmuxE2E(horloge, nommer=lambda agent: f"es-{agent}")
    for nom in SEAMS_TMUX:
        monkeypatch.setattr(importlib.import_module(nom), "_tmux", faux)
    return faux


@pytest.fixture
def banc(projet, horloge, tmux):
    return Banc(projet, horloge, tmux)


@pytest.fixture
def banc_depot(depot, horloge, tmux):
    return Banc(depot, horloge, tmux)

