"""Fusion sur la branche de référence : l'Assistant seul, sous un accord de l'utilisateur non consommé
pour la pointe actuelle de la branche , chaque fusion journalisée, l'accord consommé."""
import argparse
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from cime.fondation import garde, hook
from cime.fondation.garde import decider, fusions_autorisees
from cime.fondation.nom import VAR_AGENT, VAR_PROJET

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
LIGNE_FUSIONS = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z assistant \S+ \S+ .*$")


def _git(*args, cwd):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def depot(tmp_path, monkeypatch):
    """Projet jetable : dépôt principal sur main, une branche equipe/x avec un commit."""
    p = tmp_path / "depot"
    (p / ".orga").mkdir(parents=True)
    (p / ".orga" / "projet.toml").write_text(MANIFESTE)
    _git("init", "-q", "-b", "main", cwd=p)
    _git("add", ".", cwd=p)
    _git("commit", "-q", "-m", "init", cwd=p)
    _git("checkout", "-q", "-b", "equipe/x", cwd=p)
    _git("commit", "-q", "--allow-empty", "-m", "x", cwd=p)
    _git("checkout", "-q", "main", cwd=p)
    monkeypatch.setenv(VAR_PROJET, str(p))
    monkeypatch.delenv(VAR_AGENT, raising=False)
    monkeypatch.delenv("TMUX", raising=False)
    return p


def entree(commande, cwd):
    e = json.loads(FIXTURE.read_text())
    e["tool_name"] = "Bash"
    e["tool_input"] = {"command": commande, "description": "essai"}
    e["cwd"] = str(cwd)
    return e


def identite(monkeypatch, nom):
    if nom is None:
        monkeypatch.delenv(VAR_AGENT, raising=False)
    else:
        monkeypatch.setenv(VAR_AGENT, nom)


def sha_de(depot, ref):
    return subprocess.run(["git", "rev-parse", ref], cwd=depot, capture_output=True,
                          text=True, check=True).stdout.strip()


def donner_accord(depot, ref="equipe/x", sha=None, equipe="x", clos=False):
    """Inscrit un `accord` de l'utilisateur →Assistant `fusion:<é>:<sha>` dans le registre jetable."""
    from cime.fondation.registre import inscrire_message, inscrire_transition, ouvrir
    conn = ouvrir(depot)
    try:
        ident = inscrire_message(conn, de="utilisateur", a="assistant", nature="accord",
                                 resume="accord", equipe=equipe,
                                 objet=f"fusion:{equipe}:{sha or sha_de(depot, ref)}")
        # Comme en vrai : l'accord est livré à l'Assistant (sinon un hook le lui rendrait) et
        # reste « pris en compte » jusqu'à ce que la fusion le consomme.
        for etat in ("inscrit", "livre", "pris_en_compte"):
            inscrire_transition(conn, ident, etat, "utilisateur", {})
        if clos:
            inscrire_transition(conn, ident, "clos", "cime", {"par_evenement": 1})
        return ident
    finally:
        conn.close()


@pytest.fixture
def accord_x(depot):
    return donner_accord(depot)


ASSISTANT_FUSIONNE_A_LA_MAIN = [
    "git merge equipe/x",
    "git -C {P} merge equipe/x",
    'git merge --no-ff -m "x" equipe/x',
    'bash -c "git merge equipe/x"',
]
ASSISTANT_REFUSE = [
    "git push",
    "git push origin main",
    "git -C {P} push",
    "git branch -D equipe/x",
    "git pull",
    "git rebase main",
    "git cherry-pick equipe/x",
    "git reset --hard HEAD~1",
    "git update-ref refs/heads/main equipe/x",
    "git branch -f main equipe/x",
    "git merge",
    "git merge -- ",
]


@pytest.mark.parametrize("commande", ASSISTANT_FUSIONNE_A_LA_MAIN)
def test_assistant_ne_fusionne_plus_a_la_main_meme_avec_accord(depot, accord_x, monkeypatch, commande):
    """La fusion vers la référence passe par `cime fusionner` : l'accord n'y change rien."""
    identite(monkeypatch, "assistant")
    cmd = commande.format(P=depot)
    motif = decider(entree(cmd, depot), depot)
    assert motif is not None and "cime fusionner" in motif
    assert fusions_autorisees(entree(cmd, depot), depot) == []


@pytest.mark.parametrize("commande", ASSISTANT_REFUSE)
def test_assistant_ne_fait_pas_le_reste(depot, monkeypatch, commande):
    identite(monkeypatch, "assistant")
    cmd = commande.format(P=depot)
    assert decider(entree(cmd, depot), depot) is not None


@pytest.mark.parametrize("nom", ["coord-fondation", "worker-fondation-x"])
def test_coordinateur_et_worker_refuses_avec_le_message_assistant(depot, monkeypatch, nom):
    identite(monkeypatch, nom)
    motif = decider(entree("git merge equipe/x", depot), depot)
    assert motif is not None
    assert "faite par l'Assistant" in motif
    assert "réservé à l'utilisateur" not in motif


def test_sans_identite_refuse_avec_le_message_actuel(depot, monkeypatch):
    identite(monkeypatch, None)
    motif = decider(entree("git merge equipe/x", depot), depot)
    assert motif is not None
    assert "réservé à l'utilisateur" in motif


@pytest.mark.parametrize("commande", [
    "CIME_AGENT=assistant git merge equipe/x",
    "env CIME_AGENT=assistant git merge equipe/x",
])
def test_affectation_dans_la_commande_ne_donne_pas_l_identite(depot, monkeypatch, commande):
    identite(monkeypatch, None)
    assert decider(entree(commande, depot), depot) is not None


@pytest.mark.parametrize("nom", ["assistant-bis", "coord-assistant"])
def test_identite_qui_ressemble_refusee(depot, monkeypatch, nom):
    identite(monkeypatch, nom)
    assert decider(entree("git merge equipe/x", depot), depot) is not None


def test_merge_sans_branche_nommee_refusee_a_l_assistant(depot, monkeypatch):
    identite(monkeypatch, "assistant")
    motif = decider(entree("git merge", depot), depot)
    assert "cime fusionner" in motif


def test_abort_permis_sans_fusion_journalisee(depot, monkeypatch):
    identite(monkeypatch, "assistant")
    assert decider(entree("git merge --abort", depot), depot) is None
    assert fusions_autorisees(entree("git merge --abort", depot), depot) == []


def test_fusions_autorisees_vide_pour_les_autres(depot, monkeypatch):
    e = entree("git merge equipe/x", depot)
    identite(monkeypatch, "coord-fondation")
    assert fusions_autorisees(e, depot) == []
    identite(monkeypatch, None)
    assert fusions_autorisees(e, depot) == []


def test_fusions_autorisees_vide_si_refus(depot, monkeypatch):
    identite(monkeypatch, "assistant")
    e = entree("git merge equipe/x && git push", depot)
    assert decider(e, depot) is not None
    assert fusions_autorisees(e, depot) == []


# --- hook : journal fusions.log -------------------------------------------

def lancer(monkeypatch, capsys, commande, agent):
    identite(monkeypatch, agent)
    texte = json.dumps(entree(commande, os.environ[VAR_PROJET]))
    monkeypatch.setattr(sys, "stdin", io.StringIO(texte))
    assert hook.executer(argparse.Namespace(evenement="PreToolUse")) == 0
    return capsys.readouterr().out


def fusions(depot):
    f = depot / ".orga" / "etat" / "fusions.log"
    return f.read_text(encoding="utf-8").splitlines() if f.exists() else None


def sha(depot, ref):
    return subprocess.run(["git", "rev-parse", ref], cwd=depot, capture_output=True,
                          text=True, check=True).stdout.strip()


def test_refus_du_coordinateur_pas_de_journal_fusion(depot, monkeypatch, capsys):
    sortie = lancer(monkeypatch, capsys, "git merge equipe/x", "coord-fondation")
    assert "permissionDecision" in sortie
    assert fusions(depot) is None
    conn = sqlite3.connect(depot / ".orga" / "etat" / "registre.sqlite")
    try:
        n = conn.execute("select count(*) from evenements where evenement = 'PreToolUse'"
                         ).fetchone()[0]
    finally:
        conn.close()
    assert n == 1


def test_commande_qui_n_est_pas_une_fusion_n_ecrit_rien(depot, monkeypatch, capsys):
    assert lancer(monkeypatch, capsys, "git status", "assistant") == ""
    assert fusions(depot) is None


# --- résultat de la fusion (PostToolUse) ----------------------------------

def poste(monkeypatch, capsys, commande, agent):
    identite(monkeypatch, agent)
    evenement = {**entree(commande, os.environ[VAR_PROJET]), "hook_event_name": "PostToolUse"}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(evenement)))
    assert hook.executer(argparse.Namespace(evenement="PostToolUse")) == 0
    return capsys.readouterr().out


def test_reference_non_resolue_pas_de_resultat(depot, monkeypatch, capsys):
    poste(monkeypatch, capsys, "git merge nexistepas", "assistant")
    assert fusions(depot) is None


def test_post_tool_use_sur_une_commande_qui_n_est_pas_une_fusion_n_ecrit_rien(
        depot, monkeypatch, capsys):
    assert poste(monkeypatch, capsys, "git status", "assistant") == ""
    assert fusions(depot) is None


def test_post_tool_use_du_coordinateur_n_ecrit_rien(depot, monkeypatch, capsys):
    assert poste(monkeypatch, capsys, "git merge equipe/x", "coord-fondation") == ""
    assert fusions(depot) is None


# --- dépôt non résolu et dépôt détourné : refus pour tous ----------------

@pytest.mark.parametrize("nom", ["assistant", "coord-fondation", "worker-fondation-x"])
def test_depot_non_resolu_refuse_pour_tous(depot, monkeypatch, nom):
    identite(monkeypatch, nom)
    monkeypatch.setattr(garde, "_etat_depot", lambda *a: (None, None))
    motif = decider(entree("git merge equipe/x", depot), depot)
    assert motif is not None and "ne peut pas résoudre" in motif
    assert "git -C /chemin merge" in motif


@pytest.mark.parametrize("nom", ["assistant", "worker-fondation-x"])
def test_dossier_non_depot_refuse_pour_tous(depot, monkeypatch, tmp_path, nom):
    identite(monkeypatch, nom)
    nu = tmp_path / "nu"
    nu.mkdir()
    motif = decider(entree("git merge equipe/x", nu), depot)
    assert motif is not None and "ne peut pas résoudre" in motif


def _autre_depot(tmp_path):
    autre = tmp_path / "autre"
    _git("init", "-q", "-b", "main", str(autre), cwd=tmp_path)
    _git("commit", "-q", "--allow-empty", "-m", "autre", cwd=autre)
    return autre / ".git"


@pytest.mark.parametrize("nom", ["assistant", "worker-fondation-x"])
def test_git_dir_hors_projet_refuse_depuis_la_racine(depot, monkeypatch, tmp_path, nom):
    identite(monkeypatch, nom)
    autre = _autre_depot(tmp_path)
    motif = decider(entree(f"GIT_DIR={autre} git merge equipe/x", depot), depot)
    assert motif is not None and "GIT_DIR" in motif
    motif = decider(entree(f"git --git-dir={autre} merge equipe/x", depot), depot)
    assert motif is not None


def test_git_dir_dans_l_environnement_de_l_agent_refuse(depot, monkeypatch, tmp_path):
    identite(monkeypatch, "assistant")
    monkeypatch.setenv("GIT_DIR", str(_autre_depot(tmp_path)))
    assert decider(entree("git merge equipe/x", depot), depot) is not None


def test_git_dir_du_depot_principal_ne_contourne_pas_la_file(depot, accord_x, monkeypatch):
    identite(monkeypatch, "assistant")
    cmd = f"GIT_DIR={depot}/.git git merge --no-ff -m x equipe/x"
    motif = decider(entree(cmd, depot), depot)
    assert motif is not None and "cime fusionner" in motif
    assert fusions_autorisees(entree(cmd, depot), depot) == []


# --- l'accord de l'utilisateur ---------------------------------------------------------------

CMD = "git merge --no-ff -m x equipe/x"


def refuse(depot, ref="equipe/x"):
    """Le motif de refus des règles de fusion pour `ref` (celles que `cime fusionner` applique), ou None."""
    return garde.juger_fusion(depot, ref)[2]


def test_sans_accord_refus_avec_la_commande_a_utiliser(depot):
    motif = refuse(depot)
    assert motif is not None and "aucun accord de l'utilisateur non consommé" in motif
    assert "cime envoyer --a utilisateur --nature decision_utilisateur" in motif
    assert f"fusion:<équipe>:{sha_de(depot, 'equipe/x')}" in motif


def test_avec_accord_sur_la_pointe_actuelle_permis(depot, accord_x):
    assert refuse(depot) is None


def test_accord_sur_sha_abrege_de_7_caracteres_ou_plus(depot):
    donner_accord(depot, sha=sha_de(depot, "equipe/x")[:7])
    assert refuse(depot) is None


def test_accord_caduc_la_branche_a_avance(depot, accord_x):
    _git("checkout", "-q", "equipe/x", cwd=depot)
    _git("commit", "-q", "--allow-empty", "-m", "encore", cwd=depot)
    _git("checkout", "-q", "main", cwd=depot)
    motif = refuse(depot)
    assert motif is not None and "la branche a avancé" in motif


def test_accord_deja_consomme_refuse(depot):
    donner_accord(depot, clos=True)
    assert refuse(depot) is not None


def test_accord_d_un_autre_emetteur_ou_autre_objet_ne_compte_pas(depot):
    from cime.fondation.registre import inscrire_message, ouvrir
    conn = ouvrir(depot)
    sha = sha_de(depot, "equipe/x")
    inscrire_message(conn, de="assistant", a="assistant", nature="accord", resume="faux",
                     objet=f"fusion:x:{sha}")
    inscrire_message(conn, de="utilisateur", a="assistant", nature="accord", resume="chantier",
                     objet=f"chantier:x:{sha}")
    inscrire_message(conn, de="utilisateur", a="assistant", nature="refus", resume="non",
                     objet=f"fusion:x:{sha}")
    conn.close()
    assert refuse(depot) is not None


def test_registre_illisible_refuse(depot):
    etat = depot / ".orga" / "etat"
    etat.mkdir(parents=True)
    (etat / "registre.sqlite").write_text("pas une base" * 100)
    motif = refuse(depot)
    assert motif is not None and "registre est illisible" in motif


def test_un_accord_ne_couvre_que_la_pointe_qu_il_vise(depot, accord_x):
    _git("branch", "equipe/y", "equipe/x", cwd=depot)
    _git("checkout", "-q", "equipe/y", cwd=depot)
    _git("commit", "-q", "--allow-empty", "-m", "y", cwd=depot)
    _git("checkout", "-q", "main", cwd=depot)
    assert refuse(depot) is None
    assert refuse(depot, "equipe/y") is not None


def test_abort_et_worktree_n_exigent_aucun_accord(depot, monkeypatch, tmp_path):
    identite(monkeypatch, "assistant")
    assert decider(entree("git merge --abort", depot), depot) is None
    w = tmp_path / "wt"
    _git("worktree", "add", "-q", "-b", "equipe/w", str(w), cwd=depot)
    identite(monkeypatch, "worker-fondation-x")
    assert decider(entree("git merge main", w), depot) is None
