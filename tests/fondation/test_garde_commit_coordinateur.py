"""Registre 2.0 : le coordinateur commite dans le worktree de SON équipe, jamais ailleurs.

Vrais dépôts jetables (principal, deux worktrees d'équipe) ; l'identité est posée par `CIME_AGENT`.
Chaque règle a un cas refusé et son voisin permis.
"""
import json
import subprocess
import textwrap
from pathlib import Path

import pytest

from cime.fondation.garde import decider
from cime.fondation.nom import VAR_AGENT

MANIFESTE = textwrap.dedent("""\
    nom = "Essai"
    prefixe = "cc"
    branche_reference = "main"
    branche_equipe = "equipe/{equipe}"
    worktree_equipe = "../{depot}-{equipe}"
    equipes_speciales = ["assistant"]
    modele_assistant = "claude-opus-5-5"
    modele_coordinateur = "claude-opus-5-5"
""")
FIXTURE = Path(__file__).parent / "fixtures" / "hooks" / "PreToolUse.json"


def _git(*args, cwd):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   cwd=cwd, check=True, capture_output=True)


@pytest.fixture(scope="module")
def depots(tmp_path_factory):
    racine = tmp_path_factory.mktemp("commit-coord")
    p = racine / "depot"
    p.mkdir()
    _git("init", "-q", "-b", "main", cwd=p)
    (p / ".orga").mkdir()
    (p / ".orga" / "projet.toml").write_text(MANIFESTE)
    _git("add", ".", cwd=p)
    _git("commit", "-q", "-m", "init", cwd=p)
    w, v = racine / "depot-fondation", racine / "depot-observation"
    _git("worktree", "add", "-q", "-b", "equipe/fondation", str(w), cwd=p)
    _git("worktree", "add", "-q", "-b", "equipe/observation", str(v), cwd=p)
    (w / "sous").mkdir()
    return {"P": p, "W": w, "V": v, "S": w / "sous", "R": racine}


def entree(commande, cwd):
    e = json.loads(FIXTURE.read_text())
    e["tool_name"], e["tool_input"], e["cwd"] = "Bash", {"command": commande}, str(cwd)
    return e


def motif(depots, commande, ou, agent="coord-fondation", monkeypatch=None):
    monkeypatch.setenv(VAR_AGENT, agent)
    return decider(entree(commande.format(**{k: str(v) for k, v in depots.items()}), depots[ou]),
                   depots["P"])


PERMIS = [
    ("git add .", "W"),
    ("git add fichier.py && git commit -m 'travail'", "W"),
    ("git commit -m 'travail'", "S"),                       # un sous-dossier de son worktree
    ("git -C {W} add -A", "P"),
    ("git -C {W} commit -m x", "P"),
    ("git -C {W}/sous commit -m x", "P"),
    ("cd {W} && git add -A && git commit -m x", "P"),
    ("rtk git -C {W} commit -m x", "P"),
    ("git commit -am 'message avec n dedans'", "W"),         # -a puis -m : pas un -n
    ("git commit -m \"réécrire --amend dans le texte\"", "W"),   # du texte, pas une option
    ("git commit -m 'sans --no-verify'", "W"),
    ("git status", "P"),                                     # le reste n'est pas touché
    ("git -C {W} merge equipe/fondation-x", "P"),
]

REFUSES = [
    ("git add .", "P"),                                      # dépôt principal
    ("git commit -m x", "P"),
    ("git -C {P} commit -m x", "W"),
    ("git -C {P} add -A", "W"),
    ("git -C {V} commit -m x", "W"),                         # worktree d'une autre équipe
    ("git -C {V} add .", "P"),
    ("cd {V} && git commit -m x", "W"),                      # cd ailleurs
    ("git commit -m x", "V"),
    ("git -C {W}/.. commit -m x", "P"),                      # remonte hors de son worktree
    ("git -C {R} add .", "W"),
    ("git --git-dir={V}/.git --work-tree={V} commit -m x", "W"),   # dépôt détourné
    ("GIT_DIR={V}/.git git commit -m x", "W"),
    ("cd $AILLEURS && git add .", "W"),                      # dossier non résoluble
    ("git -C {W} commit --amend", "P"),                      # pas de réécriture d'historique
    ("git commit --amend --no-edit", "W"),
    ("git commit --amen", "W"),
    ("git -C {W} commit --no-verify -m x", "P"),
    ("git commit -n -m x", "W"),
    ("git commit -nm x", "W"),
    ("git commit -anm x", "W"),
    ("git commit --no-v -m x", "W"),
    ("git -C {W} reset --hard", "P"),                        # reset refusé partout
    ("git -C {W} reset --soft HEAD~1", "P"),
    ("git reset --hard", "W"),
    ("git checkout -- fichier", "W"),
    ("git -C {W} checkout equipe/autre", "P"),
    ("git switch autre", "W"),
    ("git stash", "W"),
    ("git -C {W} stash pop", "P"),
    ("git restore fichier", "W"),
    ("git -C {W} restore --staged .", "P"),
]


@pytest.mark.parametrize("commande,ou", PERMIS)
def test_permis(depots, monkeypatch, commande, ou):
    assert motif(depots, commande, ou, monkeypatch=monkeypatch) is None


@pytest.mark.parametrize("commande,ou", REFUSES)
def test_refuse(depots, monkeypatch, commande, ou):
    assert motif(depots, commande, ou, monkeypatch=monkeypatch), commande


def test_le_message_dit_ou_commiter(depots, monkeypatch):
    m = motif(depots, "git commit -m x", "P", monkeypatch=monkeypatch)
    assert str(depots["W"]) in m and "git -C" in m
    m = motif(depots, "git -C {V} add .", "P", monkeypatch=monkeypatch)
    assert str(depots["W"]) in m                      # SON worktree, pas celui qu'il a visé


def test_chaque_coordinateur_a_son_worktree(depots, monkeypatch):
    assert motif(depots, "git -C {V} commit -m x", "P", "coord-observation", monkeypatch) is None
    assert motif(depots, "git -C {W} commit -m x", "P", "coord-observation", monkeypatch)


@pytest.mark.parametrize("agent", ["worker-fondation-t1", "assistant"])
@pytest.mark.parametrize("commande,ou", [("git -C {V} commit -m x", "P"), ("git commit --amend", "W"),
                                         ("git -C {W} reset --soft HEAD~1", "P")])
def test_la_garde_du_coordinateur_ne_touche_ni_les_workers_ni_l_assistant(depots, monkeypatch,
                                                                         agent, commande, ou):
    assert motif(depots, commande, ou, agent, monkeypatch) is None


def test_fusion_dans_le_depot_principal_garde_son_motif(depots, monkeypatch):
    m = motif(depots, "git -C {P} reset --hard HEAD~1", "W", monkeypatch=monkeypatch)
    assert "réservé à l'utilisateur" in m               # le motif historique prime sur le nouveau
