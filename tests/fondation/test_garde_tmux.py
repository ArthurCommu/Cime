"""tmux fermé à tous les rôles, lecture comprise : la conversation passe
par le registre, un agent n'a plus d'accès à tmux. Chaque refus renvoie vers la commande `cime`
équivalente. Les tests analysent des chaînes avec `decider` et ne lancent aucun tmux."""
import json
import textwrap
from pathlib import Path

import pytest

from cime.fondation.garde import decider
from cime.fondation.nom import VAR_AGENT

FIXTURE = Path(__file__).parent / "fixtures" / "hooks" / "PreToolUse.json"

MANIFESTE = textwrap.dedent("""\
    nom = "Essai"
    prefixe = "cc"
    branche_reference = "main"
    branche_equipe = "equipe/{equipe}"
    worktree_equipe = "../{depot}-{equipe}"
    equipes_speciales = ["assistant", "integration", "verification"]
    modele_assistant = "claude-opus-5-5"
    modele_coordinateur = "claude-opus-5-5"
""")

ROLES = ["assistant", "coord-fondation", "worker-fondation-x", None]


@pytest.fixture
def projet(tmp_path):
    p = tmp_path / "projet"
    (p / ".orga" / "teams" / "fondation").mkdir(parents=True)
    (p / ".orga" / "projet.toml").write_text(MANIFESTE)
    return p


def entree(commande, cwd):
    e = json.loads(FIXTURE.read_text())
    e["tool_name"] = "Bash"
    e["tool_input"] = {"command": commande, "description": "essai"}
    e["cwd"] = str(cwd)
    return e


def verdict(monkeypatch, projet, role, commande):
    if role is None:
        monkeypatch.delenv(VAR_AGENT, raising=False)
    else:
        monkeypatch.setenv(VAR_AGENT, role)
    return decider(entree(commande, projet), projet)


REFUSEES = [
    # écriture
    "tmux send-keys -t cc-coord-fondation 'x' Enter",
    "tmux send-keys -t cc-worker-fondation-x -l 'ligne'",
    "tmux send -t cc-worker-fondation-x x",
    "tmux kill-session -t cc-worker-fondation-x",
    "tmux new-session -d -s cc-nouveau",
    "tmux load-buffer f && tmux paste-buffer -t cc-worker-fondation-x",
    "tmux paste-buffer -t cc-worker-fondation-x",
    "tmux run-shell 'ls'",
    # lecture
    "tmux capture-pane -p -t cc-worker-fondation-x",
    "tmux capture-pane -pt cc-assistant",
    "tmux has-session -t cc-worker-fondation-x",
    "tmux list-sessions",
    "tmux ls",
    "tmux display-message -p '#S'",
    "tmux attach",
    "tmux",
    # formes détournées
    "/opt/homebrew/bin/tmux ls",
    "command tmux ls",
    "env FOO=1 tmux ls",
    "sudo tmux ls",
    "tmux -L autre ls",
    "tmux -S /tmp/sock ls",
    "bash -c 'tmux ls'",
    "cd /tmp && tmux ls",
    "echo x | xargs tmux send-keys -t cc-worker-fondation-x",
    "parallel tmux ls ::: a",
    "find . -exec tmux ls ';'",
    "ls | tmux load-buffer -",
    "x=1; tmux ls",
    "rtk tmux ls",
    "(tmux ls)",
    "timeout 5 tmux ls",
]


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("commande", REFUSEES)
def test_tmux_refuse_a_tous_les_roles(monkeypatch, projet, role, commande):
    motif = verdict(monkeypatch, projet, role, commande)
    assert motif, f"{role} : {commande}"
    assert "cime envoyer" in motif and "cime voir" in motif


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("commande", [
    "cime voir worker-fondation-x",
    "cime envoyer --a coord-fondation --nature question 'et tmux ?'",
    "echo tmux",
    "grep -rn tmux src",
    "ls tmux",
    "which cime",
    "cat tmux.conf",
])
def test_voisins_permis(monkeypatch, projet, role, commande):
    assert verdict(monkeypatch, projet, role, commande) is None


def test_script_qui_lance_tmux_refuse(monkeypatch, projet):
    script = projet / "go.sh"
    script.write_text("#!/bin/sh\ntmux ls\n")
    for role in ROLES:
        assert verdict(monkeypatch, projet, role, f"sh {script}")
        assert verdict(monkeypatch, projet, role, f"bash -c 'source {script}'")


def test_repli_textuel_refuse_tmux_sur_commande_non_analysable(monkeypatch, projet):
    """Guillemet non fermé : la commande ne s'analyse pas ; le repli textuel voit `tmux`."""
    assert verdict(monkeypatch, projet, "worker-fondation-x", "tmux ls 'oups")
    assert verdict(monkeypatch, projet, "assistant", "echo 'oups tmux")
    assert verdict(monkeypatch, projet, "worker-fondation-x", "echo 'oups") is None
