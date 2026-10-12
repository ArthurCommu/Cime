import json
import statistics
import subprocess
import textwrap
import time
from pathlib import Path

import pytest

from cime.fondation.garde import decider
from cime.fondation.nom import NOM

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


def _git(*args, cwd):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   cwd=cwd, check=True, capture_output=True)


@pytest.fixture(scope="module")
def depots(tmp_path_factory):
    """Vrais dépôts : principal (main), worktree d'équipe, dépôt isolé sur main et sur dev."""
    racine = tmp_path_factory.mktemp("garde")
    p = racine / "depot"
    p.mkdir()
    _git("init", "-q", "-b", "main", cwd=p)
    (p / ".orga").mkdir()
    (p / ".orga" / "projet.toml").write_text(MANIFESTE)
    _git("add", ".", cwd=p)
    _git("commit", "-q", "-m", "init", cwd=p)
    w = racine / "depot-fondation"
    _git("worktree", "add", "-q", "-b", "equipe/fondation", str(w), cwd=p)
    a = racine / "isole-main"
    a.mkdir()
    _git("init", "-q", "-b", "main", cwd=a)
    _git("commit", "-q", "--allow-empty", "-m", "init", cwd=a)
    d = racine / "isole-dev"
    d.mkdir()
    _git("init", "-q", "-b", "dev", cwd=d)
    _git("commit", "-q", "--allow-empty", "-m", "init", cwd=d)
    return {"P": p, "W": w, "A": a, "D": d}


def entree(commande, cwd, outil="Bash"):
    """Entrée construite sur la structure de la capture réelle PreToolUse.json."""
    e = json.loads(FIXTURE.read_text())
    e["tool_name"] = outil
    e["tool_input"] = {"command": commande, "description": "essai"}
    e["cwd"] = str(cwd)
    return e


R, OK = "refus", "passe"

# (commande, dossier courant, attendu) ; {P} principal, {W} worktree d'équipe,
# {A} dépôt isolé sur main, {D} dépôt isolé sur dev.
CAS = [
    # push, sous toutes ses formes
    ("git push", "W", R),
    ("git push origin equipe/fondation", "W", R),
    ("cd /x && git push", "W", R),
    ("git -C /x -c a=b push --force", "W", R),
    ("git --no-pager push", "W", R),
    ("git --git-dir=/x/.git --work-tree=/x push", "W", R),
    ("git push origin :vieille", "W", R),
    ("bash -c 'git push'", "W", R),
    ("sh -c \"cd /tmp; git push\"", "W", R),
    ("zsh -c 'bash -c \"git push\"'", "W", R),
    ("bash -lc 'git push'", "W", R),
    ("$(git push)", "W", R),
    ('echo "$(git push)"', "W", R),
    ("echo `git push`", "W", R),
    ("(git push)", "W", R),
    ("FOO=1 sudo git push", "W", R),
    ("env A=1 git push", "W", R),
    ("nohup git push &", "W", R),
    ("time git push", "W", R),
    ("exec git push", "W", R),
    ("command git push", "W", R),
    ("timeout 5 git push", "W", R),
    ("watch -n 5 git push", "W", R),
    ("echo x | xargs -n 1 git push", "W", R),
    ("eval \"git push\"", "W", R),
    ("git status\ngit push", "W", R),
    ("git status; git push", "W", R),
    ("true || git push", "W", R),
    ("/usr/bin/git push", "W", R),
    ("git -c alias.p=push p", "W", R),
    ("git -c 'alias.p=!git push' p", "W", R),
    ("git send-pack origin x", "W", R),
    ("bash <<'EOF'\ngit push\nEOF", "W", R),
    ("echo 'git push' | bash", "W", R),
    ("python3 -c \"import subprocess; subprocess.run(['git', 'push'])\"", "W", R),
    ("find . -name x -exec git push \\;", "W", R),
    ('echo "pas fermé; git push', "W", R),
    # suppression de branche
    ("git branch -D x", "W", R),
    ("git branch -d x", "W", R),
    ("git branch -Dr x", "W", R),
    ("git branch --delete x", "W", R),
    ("git branch --del x", "W", R),
    ("git -C . branch -D x", "W", R),
    ("git update-ref -d refs/heads/x", "W", R),
    # Trousseau
    ("security find-generic-password -s x -w", "W", R),
    ("/usr/bin/security dump-keychain", "W", R),
    ("sudo -u root security list-keychains", "W", R),
    # fusions dans le dépôt principal ou sur la branche de référence : refus
    ("git merge equipe/fondation", "P", R),
    ("cd {P} && git merge x", "W", R),
    ("git -C {P} merge x", "W", R),
    ("git -C {P} pull", "W", R),
    ("git -C {P} rebase equipe/fondation", "W", R),
    ("git -C {P} cherry-pick abc", "W", R),
    ("git -C {P} am < x.patch", "W", R),
    ("git -C {P} reset --hard HEAD~1", "W", R),
    ("git checkout main", "P", R),
    ("git switch main", "P", R),
    ("git -C {P}/.orga merge x", "W", R),
    ("(cd {W}) ; git merge x", "P", R),
    ("git -C \"$WT\" merge x", "W", R),
    ("cd $WT && git merge x", "W", R),
    ("git -C {A} merge x", "W", R),
    ("git branch -f main HEAD", "W", R),
    ("git fetch . equipe/fondation:main", "W", R),
    # fusions dans un worktree d'équipe sur sa branche : permises
    ("git -C {W} merge equipe/fondation-x", "P", OK),
    ("git merge equipe/fondation-x", "W", OK),
    ("cd {W} && git merge x", "P", OK),
    ("git -C {W} reset --hard HEAD", "W", OK),
    ("git -C {D} rebase x", "W", OK),
    ("git reset --soft HEAD~1", "P", OK),
    ("git checkout -- fichier", "P", OK),
    # du texte, pas des commandes
    ('echo "git push"', "W", OK),
    ("git log --grep push", "W", OK),
    ("grep -r security .", "W", OK),
    ('git commit -m "avant le push"', "W", OK),
    ("git status", "W", OK),
    ("git branch -a", "W", OK),
    ("git branch -vv", "W", OK),
    ("git branch nouvelle", "W", OK),
    ("cat > rapport.md <<'EOF'\ngit push interdit ; git branch -D x\nEOF", "W", OK),
    ("git log --oneline | head -n 3 && git diff --stat", "W", OK),
    ("ls -la", "W", OK),
    # RTK
    ("rtk git push", "W", R),
    ("rtk git -C /x push", "W", R),
    ("cd /x && rtk git push", "W", R),
    ("rtk git branch -D x", "W", R),
    ("rtk git -C /x branch -D y", "W", R),
    ("rtk proxy git status", "W", R),
    ("rtk proxy touch b.txt", "W", R),
    ("rtk err git push", "W", R),
    ("rtk git status", "W", OK),
    ("rtk gain", "W", OK),
    ("rtk --version", "W", OK),
    ("rtk discover", "W", OK),
    ("xargs echo", "W", OK),
    ('echo "$HOME"', "W", OK),
    (f"{NOM} envoyer --a assistant \"x\"", "W", OK),
]


@pytest.mark.parametrize("commande,ou,attendu", CAS)
def test_garde(depots, commande, ou, attendu):
    cmd = commande.format(**{k: str(v) for k, v in depots.items()})
    motif = decider(entree(cmd, depots[ou]), depots["P"])
    assert (R if motif else OK) == attendu, motif
    if motif:
        assert isinstance(motif, str) and len(motif) < 400


def test_motifs_explicites(depots):
    w = depots["W"]
    assert "push" in decider(entree("git push", w), depots["P"])
    assert "supérieur" in decider(entree("git push", w), depots["P"])
    assert "cime envoyer" in decider(entree("tmux ls", w), depots["P"])
    assert "proxy" in decider(entree("rtk proxy ls", w), depots["P"])


SANS_PROJET = [
    ("git push", "W", R),
    ("git branch -D x", "W", R),
    ("security find-generic-password", "W", R),
    ("git merge x", "A", R),
    ("git pull", "A", R),
    ("git merge x", "D", OK),
    ("git merge x", "W", OK),
    ("git merge x", "P", R),  # le principal est sur main
]


@pytest.mark.parametrize("commande,ou,attendu", SANS_PROJET)
def test_garde_sans_projet(depots, commande, ou, attendu):
    motif = decider(entree(commande, depots[ou]), None)
    assert (R if motif else OK) == attendu, motif


def test_tmux_refuse_meme_sans_projet(depots):
    assert decider(entree("tmux ls", depots["W"]), None)


def test_autres_outils_et_entrees_invalides(depots):
    e = json.loads(FIXTURE.read_text())  # vraie entrée : outil Read
    assert decider(e, depots["P"]) is None
    assert decider(entree("git push", depots["W"], outil="Write"), None) is None
    assert decider({"tool_name": "Bash", "tool_input": {}}, None) is None
    assert decider({"tool_name": "Bash"}, None) is None
    assert decider("pas un dict", None) is None  # type: ignore[arg-type]
    assert decider(entree("git push", depots["W"]), Path("/inexistant")) is not None


def test_mesure(depots, capsys):
    def mediane(cmd, n):
        e = entree(cmd, depots["W"])
        t = []
        for _ in range(n):
            d = time.perf_counter()
            decider(e, depots["P"])
            t.append(time.perf_counter() - d)
        return statistics.median(t) * 1000

    sans_git = mediane("ls -la | grep x && echo fini", 200)
    fusion = mediane(f"git -C {depots['W']} merge x", 20)
    with capsys.disabled():
        print(f"\n[garde] médiane sans git : {sans_git:.3f} ms ; "
              f"avec fusion (1 sous-processus) : {fusion:.1f} ms")
    assert sans_git < 2
    assert fusion < 200
