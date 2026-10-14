"""La branche de référence ne reçoit de fusion que par `cime fusionner <équipe>` : la garde refuse à
l'Assistant (et à tout autre) toute écriture directe de la référence par git, sous les formes que
l'analyse sait lire, et laisse passer la mise à jour d'une branche d'équipe, les commits ordinaires
et les lectures."""
import pytest

from cime.fondation.garde import decider
from test_garde_fusion import _git, depot, entree, identite  # noqa: F401

TOUS = ["assistant", "coord-fondation", "worker-fondation-x"]


@pytest.fixture
def monde(depot, tmp_path):
    """Le dépôt principal (main), un worktree d'équipe `equipe/w` en retard sur main, et une branche
    `equipe/c` qui entre en conflit avec main."""
    (depot / "a.txt").write_text("a\n")
    _git("add", "a.txt", cwd=depot)
    _git("commit", "-q", "-m", "a", cwd=depot)
    _git("branch", "equipe/c", cwd=depot)
    _git("checkout", "-q", "equipe/c", cwd=depot)
    (depot / "a.txt").write_text("c\n")
    _git("commit", "-q", "-am", "c", cwd=depot)
    _git("checkout", "-q", "main", cwd=depot)
    w = tmp_path / "depot-w"
    _git("worktree", "add", "-q", "-b", "equipe/w", str(w), cwd=depot)
    (depot / "a.txt").write_text("main\n")
    _git("commit", "-q", "-am", "main avance", cwd=depot)
    return depot, w


def juger(monde, monkeypatch, commande, agent="assistant", ou="P"):
    depot, w = monde
    identite(monkeypatch, agent)
    cmd = commande.format(P=depot, W=w)
    return decider(entree(cmd, depot if ou == "P" else w), depot)


# --- ce qui est refusé -----------------------------------------------------------------------

MERGE = [
    "git merge equipe/x",
    "git merge --no-ff -m x equipe/x",
    "git merge --no-commit equipe/x",
    "git merge --no-commit --no-ff equipe/x",
    "git merge --squash equipe/x",
    "git merge --continue",
    "git merge",
    "git -C {P} merge equipe/x",
    "git -C {P} merge --continue",
    "cd {P} && git merge equipe/x",
    "cd {P} && git merge --continue",
    'bash -c "git merge equipe/x"',
    'bash -c "cd {P} && git merge --continue"',
    "env git merge equipe/x",
    "true && git merge equipe/x",
    "git merge equipe/x; git status",
    "git -c alias.m=merge m equipe/x",
    "git -c 'alias.m=!git merge equipe/x' m",
    "git config alias.m 'merge equipe/x'",
    "GIT_DIR={P}/.git git merge equipe/x",
    "git --git-dir={P}/.git merge equipe/x",
    "echo equipe/x | xargs git merge",
]
AUTRES_ECRITURES = [
    "git pull",
    "git pull origin main",
    "git rebase equipe/x",
    "git -C {P} rebase equipe/x",
    "git cherry-pick equipe/x",
    "git cherry-pick --continue",
    "git am un.patch",
    "git reset --hard HEAD~1",
    "git reset --soft HEAD~1",
    "git reset --mixed HEAD~1",
    "git reset HEAD~1",
    "git reset --keep HEAD~1",
    "git -C {P} reset --soft HEAD~1",
    "cd {P} && git reset --soft HEAD~1",
    'bash -c "git reset --soft HEAD~1"',
    "git reset --so HEAD~1",
]
AMEND = [
    "git commit --amend",
    "git commit --amend -m x",
    "git commit --amend --no-edit",
    "git commit -a --amend --no-edit",
    "git commit --amen -m x",
    "git commit -m x --amend",
    "git -C {P} commit --amend --no-edit",
    "cd {P} && git commit --amend --no-edit",
    'bash -c "git commit --amend --no-edit"',
    "env git commit --amend --no-edit",
]
PLOMBERIE = [   # un commit à plusieurs parents ne se range sur la référence par aucun chemin
    "git update-ref refs/heads/main $(git commit-tree HEAD^{{tree}} -p HEAD -p equipe/x -m f)",
    "git update-ref -m fusion refs/heads/main equipe/x",
    "git update-ref --no-deref refs/heads/main equipe/x",
    "git branch -f main equipe/x",
    "git branch --force main equipe/x",
    "git branch -M equipe/x main",
    "git branch -C equipe/x main",
    "git branch -fq main equipe/x",
    "git branch --forc main equipe/x",
    "git fetch . equipe/x:main",
    "git fetch . +equipe/x:refs/heads/main",
    "git push . equipe/x:main",
    "git checkout -B main equipe/x",
    "git switch -C main equipe/x",
]


@pytest.mark.parametrize("commande", MERGE + AUTRES_ECRITURES + AMEND + PLOMBERIE)
def test_assistant_refuse(monde, monkeypatch, commande):
    assert juger(monde, monkeypatch, commande) is not None, commande


@pytest.mark.parametrize("commande", MERGE + AUTRES_ECRITURES[:7] + ["git reset --soft HEAD~1"])
def test_le_refus_renvoie_a_la_file(monde, monkeypatch, commande):
    motif = juger(monde, monkeypatch, commande)
    assert "cime fusionner" in motif and len(motif) < 400


@pytest.mark.parametrize("agent", ["coord-fondation", "worker-fondation-x"])
@pytest.mark.parametrize("commande", ["git merge equipe/x", "git merge --continue", "git pull",
                                      "git reset --soft HEAD~1", "git rebase equipe/x",
                                      "git cherry-pick equipe/x", "git am un.patch"])
def test_coordinateurs_et_workers_restent_refuses(monde, monkeypatch, agent, commande):
    assert juger(monde, monkeypatch, commande, agent=agent) is not None


@pytest.mark.parametrize("commande", AMEND)
@pytest.mark.parametrize("agent", TOUS)
def test_amend_sur_la_reference_refuse_a_tous(monde, monkeypatch, agent, commande):
    assert juger(monde, monkeypatch, commande, agent=agent) is not None


# --- un commit qui achève une fusion en cours --------------------------------------------------

@pytest.fixture
def fusion_en_cours(monde):
    """Le dépôt principal au milieu d'une fusion conflictuelle (faite hors garde : `MERGE_HEAD`)."""
    import subprocess
    depot, _ = monde
    r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "merge", "equipe/c"],
                       cwd=depot, capture_output=True, text=True)
    assert r.returncode != 0 and (depot / ".git" / "MERGE_HEAD").exists()
    (depot / "a.txt").write_text("resolu\n")
    _git("add", "a.txt", cwd=depot)
    return monde


@pytest.mark.parametrize("commande", ["git commit", "git commit --no-edit", 'git commit -m "fusion"',
                                      "git commit -a -m x", "git -C {P} commit --no-edit",
                                      "cd {P} && git commit --no-edit",
                                      'bash -c "git commit --no-edit"'])
@pytest.mark.parametrize("agent", TOUS)
def test_commit_pendant_une_fusion_en_cours_refuse(fusion_en_cours, monkeypatch, agent, commande):
    motif = juger(fusion_en_cours, monkeypatch, commande, agent=agent)
    assert motif is not None
    if agent == "assistant":
        assert "cime fusionner" in motif


def test_abandonner_la_fusion_en_cours_reste_permis(fusion_en_cours, monkeypatch):
    for commande in ("git merge --abort", "git merge --quit", "git -C {P} merge --abort"):
        assert juger(fusion_en_cours, monkeypatch, commande) is None, commande


# --- ce qui reste permis ----------------------------------------------------------------------

def test_mettre_a_jour_une_branche_d_equipe_avec_main(monde, monkeypatch):
    for commande in ("git -C {W} merge --no-ff -q main", "git -C {W} merge main",
                     "cd {W} && git merge --no-ff -q main", 'bash -c "git -C {W} merge --no-ff -q main"',
                     "git -C {W} merge --abort"):
        assert juger(monde, monkeypatch, commande) is None, commande
    assert juger(monde, monkeypatch, "git merge --no-ff -q main", ou="W") is None


def test_une_fusion_d_equipe_en_conflit_s_acheve_dans_son_worktree(monde, monkeypatch):
    depot, w = monde
    import subprocess
    (w / "a.txt").write_text("w\n")
    _git("-C", str(w), "commit", "-q", "-am", "w", cwd=depot)
    r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(w), "merge", "main"],
                       capture_output=True, text=True)
    assert r.returncode != 0     # le conflit laisse la fusion en cours dans le worktree d'équipe
    for commande in ("git -C {W} commit -a --no-edit", "git commit -a --no-edit"):
        assert juger(monde, monkeypatch, commande, ou="W" if commande.startswith("git commit") else "P") is None


@pytest.mark.parametrize("commande", [
    'git add .orga/produit/x.md', 'git commit -m "note"', "git commit -a -m note",
    "git -C {P} commit -m note", "cd {P} && git commit -m note", 'git commit -q -F -',
    "git commit --allow-empty -m note", 'bash -c "git commit -m note"',
    "git commit -m 'parle de --amend et de merge'",
])
def test_commit_ordinaire_de_l_assistant_sur_la_reference(monde, monkeypatch, commande):
    assert juger(monde, monkeypatch, commande) is None, commande


@pytest.mark.parametrize("commande", [
    "git log --oneline -3", "git diff main equipe/w", "git status", "git show HEAD",
    "git merge-base main equipe/w", "git worktree list", "git -C {P} log -1", "git branch -a",
    "git branch nouvelle", "git branch -m ancien nouveau", "git checkout -- a.txt",
    "git restore --staged a.txt", "git fetch origin", "git merge-tree --write-tree main equipe/w",
    "git cherry main equipe/w", "git rev-list main..equipe/w",
])
def test_lectures_et_gestes_voisins_permis(monde, monkeypatch, commande):
    assert juger(monde, monkeypatch, commande) is None, commande


@pytest.mark.parametrize("commande", ["cime fusionner fondation", "cime fusionner fondation --maintenant",
                                      'bash -c "cime fusionner fondation"'])
def test_cime_fusionner_reste_permis_a_l_assistant(monde, monkeypatch, commande):
    assert juger(monde, monkeypatch, commande) is None


@pytest.mark.parametrize("commande", ["cime fusionner fondation", "env cime fusionner fondation"])
@pytest.mark.parametrize("agent", ["coord-fondation", "worker-fondation-x"])
def test_cime_fusionner_reste_refuse_aux_coordinateurs_et_workers(monde, monkeypatch, agent, commande):
    motif = juger(monde, monkeypatch, commande, agent=agent)
    assert motif is not None and "se demande à l'Assistant" in motif


@pytest.mark.parametrize("commande", [
    "git update-ref HEAD equipe/x", "git -C {P} update-ref -m x HEAD equipe/x",
    "git branch -m nouveau", "git branch -m main ancien", "git branch --move main ancien",
    "git -C {P} branch -m nouveau",
])
def test_autres_chemins_qui_deplacent_ou_renomment_la_reference(monde, monkeypatch, commande):
    assert juger(monde, monkeypatch, commande) is not None, commande


def test_deplacer_la_branche_d_un_worktree_d_equipe_reste_permis(monde, monkeypatch):
    for commande in ("git -C {W} update-ref HEAD equipe/x", "git -C {W} branch -m renommee"):
        assert juger(monde, monkeypatch, commande) is None, commande
