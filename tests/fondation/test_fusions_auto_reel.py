"""Essai réel des fusions automatiques : un dépôt jetable créé par `cime init`, le vrai hook
`cime hook PreToolUse` / `PostToolUse` lancé en sous-processus avec un JSON `Bash` réaliste (la fixture
`fixtures/hooks/PreToolUse.json`), `cime fusions-auto` et `cime envoyer` en sous-processus. Les
variables `CIME_PROJET` et `CIME_AGENT` passent par l'environnement des sous-processus (`env=`),
jamais par la ligne de commande. Lancer avec `-s` pour voir les sorties."""
import json
import os
import sqlite3
import subprocess
import sys
import types
from pathlib import Path

import pytest

from cime.fondation import init
from cime.fondation.nom import VAR_AGENT, VAR_PROJET

FIXTURE = Path(__file__).parent / "fixtures" / "hooks" / "PreToolUse.json"
SRC = Path(__file__).resolve().parents[2] / "src"


def _git(*args, cwd):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd,
                          check=True, capture_output=True, text=True).stdout.strip()


def _cime(projet, agent, *args, entree=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CIME_", "GIT_"))}
    env.update({VAR_PROJET: str(projet), VAR_AGENT: agent, "PYTHONPATH": str(SRC)})
    return subprocess.run([sys.executable, "-m", "cime.cli", *args], env=env, cwd=projet,
                          input=entree, capture_output=True, text=True, timeout=60)


def _evenement(projet, commande, nom):
    e = json.loads(FIXTURE.read_text())
    e.update({"tool_name": "Bash", "tool_input": {"command": commande, "description": "essai"},
              "cwd": str(projet), "hook_event_name": nom})
    return json.dumps(e)


def _decision(sortie: str) -> str:
    if not sortie.strip():
        return "(rien : la commande passe)"
    d = json.loads(sortie)["hookSpecificOutput"]
    return f"{d['permissionDecision']} — {d['permissionDecisionReason']}"


def test_essai_reel_de_bout_en_bout(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(init, "executable_cime", lambda: "/opt/outils/bin/cime")
    projet = tmp_path / "essai"
    assert init.executer(types.SimpleNamespace(dossier=str(projet), utilisateur="Camille",
                                               nom_projet=None, prefixe=None)) == 0
    _git("add", "-A", cwd=projet)   # `init` ignore .orga/etat/ (.gitignore)
    _git("commit", "-q", "-m", "init", cwd=projet)
    ref = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=projet)
    assert ref == "main" or _git("branch", "-m", "main", cwd=projet) == ""
    _git("checkout", "-q", "-b", "equipe/x", cwd=projet)
    (projet / "src").mkdir()
    (projet / "src" / "app.py").write_text("print('x')\n")
    (projet / "src" / "autre.py").write_text("print('y')\n")
    _git("add", "-A", cwd=projet)   # `init` ignore .orga/etat/ (.gitignore)
    _git("commit", "-q", "-m", "x : deux fichiers", cwd=projet)
    _git("checkout", "-q", "main", cwd=projet)
    sha = _git("rev-parse", "equipe/x", cwd=projet)
    merge = "git merge --no-ff -m x equipe/x"
    etapes = []

    def pre(titre):
        r = _cime(projet, "assistant", "hook", "PreToolUse", entree=_evenement(projet, merge, "PreToolUse"))
        assert r.returncode == 0, r.stderr
        etapes.append((titre, _decision(r.stdout)))
        return r.stdout

    # 1. option inactive : l'accord par sha est exigé, comme avant
    sortie = pre("1. option inactive, aucune annonce")
    assert "exige un accord de l'utilisateur non consommé" in sortie and "Fusions automatiques" not in sortie

    # 2. L'utilisateur active l'option (CIME_AGENT=utilisateur dans l'environnement du sous-processus)
    r = _cime(projet, "assistant", "fusions-auto", "active")
    assert r.returncode == 1 and "seul l'utilisateur" in r.stderr
    etapes.append(("2a. `cime fusions-auto active` par l'Assistant", f"exit {r.returncode} — {r.stderr.strip()}"))
    r = _cime(projet, "utilisateur", "fusions-auto", "active")
    assert r.returncode == 0 and r.stdout.strip() == "1"
    etapes.append(("2b. `cime fusions-auto active` par utilisateur", f"exit 0, id {r.stdout.strip()}"))
    r = _cime(projet, "assistant", "fusions-auto")
    assert "fusions automatiques : active\n" in r.stdout
    etapes.append(("2c. `cime fusions-auto` (lecture, Assistant)", "\n".join(r.stdout.splitlines()[:4]) + " …"))

    # 3. sans annonce : refus, avec la condition qui échoue
    sortie = pre("3. option active, sans annonce")
    assert "condition 4" in sortie and "exige un accord de l'utilisateur non consommé" in sortie

    # 4. l'annonce, par `cime envoyer`
    r = _cime(projet, "assistant", "envoyer", "--a", "utilisateur", "--nature", "rapport_utilisateur",
              "--objet", f"fusion-auto:x:{sha}", f"x {sha[:7]} : deux fichiers ; vérifié : essai réel")
    assert r.returncode == 0, r.stderr
    etapes.append(("4. `cime envoyer … fusion-auto:x:<sha>`", f"exit 0, message n°{r.stdout.strip()}"))

    # 5. passage
    assert pre("5. option active, avec annonce") == ""

    # 6. la fusion elle-même, puis PostToolUse
    _git("merge", "--no-ff", "-m", "x", "equipe/x", cwd=projet)
    r = _cime(projet, "assistant", "hook", "PostToolUse", entree=_evenement(projet, merge, "PostToolUse"))
    # 2 = texte rendu à l'agent sur stderr : ici « le facteur est arrêté » (il n'y a pas de facteur dans l'essai)
    assert r.returncode in (0, 2) and (r.returncode == 0 or "facteur est arrêté" in r.stderr), r.stderr
    journal = (projet / ".orga" / "etat" / "fusions.log").read_text().splitlines()
    assert len(journal) == 2 and journal[1].endswith("resultat=fusionne")
    conn = sqlite3.connect(projet / ".orga" / "etat" / "registre.sqlite")
    try:
        lignes = conn.execute("SELECT auteur, action, cible, details, resultat FROM journal"
                              " WHERE action = 'fusion_auto'").fetchall()
        clos = conn.execute("SELECT COUNT(*) FROM transitions WHERE etat = 'clos'").fetchone()[0]
    finally:
        conn.close()
    assert len(lignes) == 1 and lignes[0][:3] == ("assistant", "fusion_auto", f"fusion:x:{sha}")
    assert json.loads(lignes[0][3]) == {"annonce": 1, "reglage": 1, "fichiers": 2} and lignes[0][4] == "ok"
    assert clos == 0 and not (projet / ".orga" / "etat" / "hooks-erreurs.log").exists()
    etapes.append(("6a. PostToolUse : fusions.log", "\n".join(journal)))
    etapes.append(("6b. PostToolUse : journal du registre", repr(lignes[0])))
    etat = json.loads(_cime(projet, "assistant", "etat").stdout)["fusions_auto"]
    assert etat["active"] and etat["derniere_fusion"]["sha"] == sha and etat["derniere_fusion"]["equipe"] == "x"
    etapes.append(("7. `cime etat` → fusions_auto", json.dumps({k: v for k, v in etat.items() if k != "reserves"})))

    with capsys.disabled():
        print()
        for titre, sortie in etapes:
            print(f"--- {titre}\n{sortie}")
