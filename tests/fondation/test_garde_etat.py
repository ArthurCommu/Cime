"""Registre 2.0, étape 5 : ce que la garde ferme pour qu'il n'y ait pas d'autre chemin que les
commandes `cime` — identité (b), fichiers d'état (d), registre.sqlite (e). Chaque règle a ses cas
« refusé » et ses cas « voisin permis »."""
import json
import textwrap
from pathlib import Path

import pytest

from cime.fondation import hook, perimetre
from cime.fondation.garde import decider
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
ROLES = ["assistant", "coord-x", "worker-x-t", None]
EQ = ".orga/teams/x"


@pytest.fixture
def projet(tmp_path, monkeypatch):
    p = (tmp_path / "depot").resolve()
    for sous in ("todo", "in-progress", "done"):
        (p / EQ / "tasks" / sous).mkdir(parents=True)
    (p / ".orga" / "etat").mkdir(parents=True)
    (p / ".orga" / "projet.toml").write_text(MANIFESTE)
    (p / EQ / "tasks" / "in-progress" / "t.md").write_text("tâche")
    monkeypatch.setenv(VAR_PROJET, str(p))
    return p


def entree(commande, cwd, outil="Bash"):
    e = json.loads(FIXTURE.read_text())
    e["tool_name"] = outil
    e["tool_input"] = {"command": commande, "description": "essai"}
    e["cwd"] = str(cwd)
    return e


def verdict(monkeypatch, projet, role, commande, cwd=None):
    if role is None:
        monkeypatch.delenv(VAR_AGENT, raising=False)
    else:
        monkeypatch.setenv(VAR_AGENT, role)
    return decider(entree(commande, cwd or projet), projet)


# --- (b) identité ---------------------------------------------------------------------------

IDENTITE_REFUSEE = [
    "CIME_AGENT=assistant cime envoyer --a utilisateur --nature rapport_utilisateur x",
    "CIME_PROJET=/tmp cime reprise",
    "CLAUDECODE= cime reprise",
    "CIME_AGENT+=x ls",
    "FOO=1 CIME_AGENT=assistant ls",
    "CIME_AGENT=assistant",
    "cd /tmp && CIME_AGENT=coord-x cime reprise",
    "env CIME_AGENT=assistant cime reprise",
    "env FOO=1 CIME_PROJET=/tmp cime reprise",
    "env -u CIME_AGENT cime reprise",
    "env -u CLAUDECODE cime reprise",
    "env -uCIME_PROJET cime reprise",
    "env --unset=CIME_AGENT cime reprise",
    "env --unset CIME_AGENT cime reprise",
    "env -i cime reprise",
    "env - cime reprise",
    "env --ignore-environment ls",
    "env -S 'CIME_AGENT=x cime reprise'",
    "unset CIME_AGENT",
    "unset -v CLAUDECODE",
    "unset FOO CIME_PROJET",
    "export CIME_PROJET=/tmp",
    "export CIME_AGENT",
    "export FOO=1 CIME_AGENT=assistant",
    "declare -x CIME_AGENT=assistant",
    "typeset -x CLAUDECODE",
    "readonly CIME_AGENT=x",
    "read CIME_AGENT",
    "printf -v CIME_AGENT x",
    "exec -c cime reprise",
    "bash -c 'export CIME_AGENT=x; cime reprise'",
    "sh -c 'env -u CIME_AGENT cime reprise'",
    "eval 'CIME_AGENT=x cime reprise'",
    "sudo env CIME_AGENT=x ls",
    "python3 -c \"import os; os.environ['CIME_AGENT'] = 'assistant'\"",
    "python3 -c \"import os; os.putenv('CIME_PROJET', '/tmp')\"",
    "python3 -c \"import os; os.unsetenv('CLAUDECODE')\"",
    "python3 -c \"import os; del os.environ['CLAUDECODE']\"",
    "python3 -c \"import os; os.environ.pop('CIME_PROJET')\"",
    "python3 -c \"import os; os.environ.update(CIME_AGENT='a')\"",
    "python3 -c \"import subprocess; subprocess.run(['cime'], env={'CIME_AGENT': 'a'})\"",
    "python -c \"import os; os.environ.setdefault('CIME_AGENT', 'a')\"",
    "node -e \"process.env.CIME_AGENT='a'; setenv('CIME_AGENT')\"",
]


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("commande", IDENTITE_REFUSEE)
def test_identite_refusee_a_tous_les_roles(monkeypatch, projet, role, commande):
    motif = verdict(monkeypatch, projet, role, commande)
    assert motif, f"{role} : {commande}"
    assert "CIME_" in motif or "CLAUDECODE" in motif or "env -i" in motif


IDENTITE_PERMISE = [
    "echo $CIME_AGENT",
    'echo "$CIME_PROJET" "$CLAUDECODE"',
    "printenv CIME_AGENT",
    "env",
    "env | grep CIME",
    "env FOO=1 ls",
    "env -u HOME ls",
    "env -C /tmp ls",
    "FOO=1 cime reprise",
    "export FOO=1",
    "export -p",
    "declare -p CIME_AGENT",
    "unset FOO",
    "read x",
    "printf -v x y",
    "cime voir worker-x-t",
    "cime envoyer --a coord-x --nature question q",
    "python3 -c \"import os; print(os.environ['CIME_AGENT'])\"",
    "python3 -c \"import os; print(os.environ.get('CIME_PROJET'), os.environ['CIME_AGENT'] == 'a')\"",
    "python3 -c \"import os; os.environ['FOO'] = '1'\"",
    "grep -rn CIME_AGENT src",
]


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("commande", IDENTITE_PERMISE)
def test_identite_voisins_permis(monkeypatch, projet, role, commande):
    assert verdict(monkeypatch, projet, role, commande) is None


def test_script_python_qui_ecrit_l_identite_est_refuse(monkeypatch, projet):
    (projet / "mauvais.py").write_text("import os\nos.environ['CIME_AGENT'] = 'assistant'\n")
    (projet / "bon.py").write_text("import os\nprint(os.environ['CIME_AGENT'])\n")
    for role in ROLES:
        assert verdict(monkeypatch, projet, role, "python3 mauvais.py")
        assert verdict(monkeypatch, projet, role, "python3 -u mauvais.py")
        assert verdict(monkeypatch, projet, role, "python3 bon.py") is None


def test_heredoc_python_qui_ecrit_l_identite_est_refuse(monkeypatch, projet):
    mauvais = "python3 - <<'EOF'\nimport os\nos.environ['CIME_AGENT'] = 'a'\nEOF"
    bon = "python3 - <<'EOF'\nimport os\nprint(os.environ['CIME_AGENT'])\nEOF"
    assert verdict(monkeypatch, projet, "worker-x-t", mauvais)
    assert verdict(monkeypatch, projet, "worker-x-t", bon) is None


def test_script_shell_qui_pose_l_identite_est_refuse(monkeypatch, projet):
    (projet / "go.sh").write_text("#!/bin/sh\nexport CIME_AGENT=assistant\n")
    assert verdict(monkeypatch, projet, "coord-x", "sh go.sh")
    assert verdict(monkeypatch, projet, "coord-x", "bash -c 'source go.sh'")


# --- (d) fichiers d'état réservés aux commandes -------------------------------------------------

T_IP = f"{EQ}/tasks/in-progress"
T_DONE = f"{EQ}/tasks/done"
T_TODO = f"{EQ}/tasks/todo"

ETAT_REFUSE = [
    f"touch {T_IP}/n.md",
    f"touch {EQ}/CLOTUREE",
    "touch CLOTUREE",
    f"echo fini > {EQ}/CLOTUREE",
    f"echo x > {T_IP}/t.md",
    f"echo x >> {T_DONE}/t.md",
    f"echo x >| {T_DONE}/t.md",
    f"cat note.md > {T_IP}/t.md",
    f"mv {T_TODO}/a.md {T_IP}/a.md",
    f"mv {T_IP}/t.md {T_DONE}/",
    f"mv {T_IP}/t.md /tmp/",
    f"cp /tmp/x {T_IP}/t.md",
    f"cp -r a b {T_DONE}/",
    f"cp -t {T_DONE} a",
    f"cp --target-directory={T_DONE} a",
    f"rm {T_IP}/t.md",
    f"rm -rf {T_DONE}",
    f"rm -f {T_DONE}/*",
    f"tee {T_IP}/t.md",
    f"echo x | tee -a {T_DONE}/t.md",
    f"ln -s /tmp/x {T_IP}/lien.md",
    f"install -m 644 note.md {T_DONE}/n.md",
    f"install -t {T_DONE} note.md",
    f"dd if=/dev/zero of={T_DONE}/z bs=1 count=1",
    f"rsync -a src/ {T_IP}/",
    f"sed -i 's/a/b/' {T_IP}/t.md",
    f"sed -i '' 's/a/b/' {T_IP}/t.md",
    f"sed -i.bak 's/a/b/' {T_IP}/t.md",
    f"sed --in-place s/a/b/ {T_DONE}/t.md",
    f"git mv {T_TODO}/a.md {T_IP}/a.md",
    f"git rm {T_DONE}/t.md",
    f"truncate -s 0 {T_IP}/t.md",
    f"cd {T_IP} && touch a.md",
    f"cd {T_IP}; echo x > a.md",
    f"(cd {T_DONE} && rm t.md)",
    f"bash -c 'touch {T_DONE}/a'",
    f"find {T_DONE} -delete",
    f"find {T_IP} -name '*.md' -exec rm {{}} ';'",
    f"git -C {EQ} rm tasks/done/t.md",
]


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("commande", ETAT_REFUSE)
def test_ecriture_d_etat_refusee_a_tous_les_roles(monkeypatch, projet, role, commande):
    motif = verdict(monkeypatch, projet, role, commande)
    assert motif, f"{role} : {commande}"
    assert "cime" in motif and "Lire reste permis" in motif


ETAT_PERMIS = [
    f"ls {T_IP}",
    f"ls -la {T_DONE} {EQ}",
    f"cat {T_IP}/t.md",
    f"grep -rn tâche {T_IP} {T_DONE}",
    f"head -n 3 {T_IP}/t.md | wc -l",
    f"cp {T_IP}/t.md /tmp/copie.md",
    f"cp {T_IP}/t.md {T_TODO}/copie.md",
    f"find {T_IP} -name '*.md'",
    f"git diff {T_IP}",
    "git status",
    f"touch {T_TODO}/n.md",
    f"echo x > {T_TODO}/n.md",
    f"mv {T_TODO}/a.md {T_TODO}/b.md",
    f"rm {T_TODO}/a.md",
    f"sed -n 1p {T_IP}/t.md",
    f"sed -i 's/a/b/' {T_TODO}/a.md",
    "cime envoyer --a coord-x --nature question q",
    "cime terminer x t",
    f"echo 'fichier {T_IP}/t.md' > note-locale.md",
    "touch CLOTUREE.txt",
    f"cd {T_TODO} && touch a.md",
]


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("commande", ETAT_PERMIS)
def test_etat_voisins_permis(monkeypatch, projet, role, commande):
    assert verdict(monkeypatch, projet, role, commande) is None, f"{role} : {commande}"


def _outil(projet, outil, chemin):
    return {"tool_name": outil, "tool_input": {"file_path": str(chemin)},
            "cwd": str(projet)}


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("outil", ["Write", "Edit", "NotebookEdit"])
@pytest.mark.parametrize("sous", [f"{T_IP}/t.md", f"{T_IP}/nouveau.md", f"{T_DONE}/t.md",
                                  f"{EQ}/CLOTUREE", "CLOTUREE"])
def test_outils_de_fichier_ne_touchent_pas_l_etat(monkeypatch, projet, role, outil, sous):
    if role is None:
        monkeypatch.delenv(VAR_AGENT, raising=False)
    else:
        monkeypatch.setenv(VAR_AGENT, role)
    motif = perimetre.decider(_outil(projet, outil, projet / sous), projet)
    assert motif and "cime" in motif
    # et via le hook (garde puis périmètre)
    assert hook._decider(_outil(projet, outil, projet / sous), projet, projet)


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("outil,sous", [
    ("Write", f"{T_TODO}/n.md"), ("Edit", f"{T_TODO}/n.md"), ("Write", "note.md"),
    ("Write", f"{EQ}/reports/r.md"), ("Read", f"{T_IP}/t.md"), ("Read", f"{EQ}/CLOTUREE"),
    ("Glob", f"{T_DONE}"), ("Grep", f"{T_IP}"), ("Read", ".orga/etat/registre.sqlite"),
])
def test_outils_voisins_permis(monkeypatch, projet, role, outil, sous):
    if role is None:
        monkeypatch.delenv(VAR_AGENT, raising=False)
    else:
        monkeypatch.setenv(VAR_AGENT, role)
    if role in ("worker-x-t", "coord-x") and sous == "note.md":
        pytest.skip("un coordinateur ou un worker n'écrit pas hors de son équipe (périmètre existant)")
    assert perimetre.decider(_outil(projet, outil, projet / sous), projet) is None


# --- (e) registre.sqlite ------------------------------------------------------------------------

SQLITE_REFUSE = [
    "sqlite3 .orga/etat/registre.sqlite .tables",
    "sqlite3 -readonly .orga/etat/registre.sqlite 'select count(*) from messages'",
    "/usr/bin/sqlite3 f.db",
    "echo '.tables' | sqlite3 .orga/etat/registre.sqlite",
    "litecli .orga/etat/registre.sqlite",
    "sqlite-utils query .orga/etat/registre.sqlite 'select 1'",
    "uvx sqlite-utils tables f.db",
    "uv run sqlite-utils tables f.db",
    "python3 -m sqlite3 f.db",
    "bash -c 'sqlite3 f.db .tables'",
    "cd .orga/etat && sqlite3 registre.sqlite .schema",
    "sudo sqlite3 f.db",
    "env FOO=1 sqlite3 f.db",
    "cp copie.sqlite .orga/etat/registre.sqlite",
    "rm .orga/etat/registre.sqlite-wal",
    "mv x .orga/etat/registre.sqlite-shm",
    "echo > .orga/etat/registre.sqlite",
]


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("commande", SQLITE_REFUSE)
def test_registre_refuse_a_tous_les_roles(monkeypatch, projet, role, commande):
    motif = verdict(monkeypatch, projet, role, commande)
    assert motif and "cime" in motif, f"{role} : {commande}"


SQLITE_PERMIS = [
    "ls .orga/etat",
    "ls -la .orga/etat/registre.sqlite",
    "cp .orga/etat/registre.sqlite /tmp/copie.sqlite",
    "grep -rn sqlite3 src",
    "echo sqlite3",
    "cat README.md | grep sqlite3",
    "cime reprise",
    "cime voir worker-x-t",
    # résidu connu, non analysé (risque mesuré par la phase 4) : un client SQLite en Python
    "python3 -c \"import sqlite3; sqlite3.connect('f.db')\"",
]


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("commande", SQLITE_PERMIS)
def test_registre_voisins_permis(monkeypatch, projet, role, commande):
    assert verdict(monkeypatch, projet, role, commande) is None, f"{role} : {commande}"


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("outil", ["Write", "Edit", "NotebookEdit"])
@pytest.mark.parametrize("nom", ["registre.sqlite", "registre.sqlite-wal", "registre.sqlite-shm"])
def test_outils_de_fichier_ne_touchent_pas_le_registre(monkeypatch, projet, role, outil, nom):
    if role is None:
        monkeypatch.delenv(VAR_AGENT, raising=False)
    else:
        monkeypatch.setenv(VAR_AGENT, role)
    chemin = projet / ".orga" / "etat" / nom
    motif = perimetre.decider(_outil(projet, outil, chemin), projet)
    assert motif and "cime" in motif and "registre" in motif
