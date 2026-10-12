"""M5 : après `init`, si l'exécutable `cime` disparaît, le hook PreToolUse refuse (2)."""
import json
import os
import stat
import subprocess
import types

from cime.fondation import init


def _entree_bash():
    return json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                       "tool_input": {"command": "git status"}, "session_id": "s",
                       "cwd": "/tmp"})


def _commande_pretooluse(projet):
    reglages = json.loads((projet / ".claude" / "settings.json").read_text())
    return reglages["hooks"]["PreToolUse"][0]["hooks"][0]["command"]


def _lancer(commande):
    return subprocess.run(["/bin/sh", "-c", commande], input=_entree_bash(),
                          capture_output=True, text=True)


def test_garde_fermee_quand_cime_disparait(tmp_path, monkeypatch):
    faux = tmp_path / "bin" / "cime"
    faux.parent.mkdir()
    faux.write_text('#!/bin/sh\necho appel-normal "$@"\nexit 0\n')
    faux.chmod(faux.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(init, "executable_cime", lambda: str(faux))
    projet = tmp_path / "projet"
    args = types.SimpleNamespace(dossier=str(projet), utilisateur="Camille",
                                 nom_projet=None, prefixe=None)
    assert init.executer(args) == 0
    commande = _commande_pretooluse(projet)
    assert str(faux) in commande

    avant = _lancer(commande)
    assert avant.returncode == 0 and "appel-normal hook PreToolUse" in avant.stdout

    os.remove(faux)
    apres = _lancer(commande)
    assert apres.returncode == 2
    assert "introuvable" in apres.stderr and str(faux) in apres.stderr


def _commande_avec(tmp_path, corps):
    from cime.fondation.reglages import commande_hook
    faux = tmp_path / "bin" / "cime"
    faux.parent.mkdir(parents=True, exist_ok=True)
    faux.write_text("#!/bin/sh\n" + corps)
    faux.chmod(0o755)
    return commande_hook("PreToolUse", str(faux)), faux


def test_sortie_zero_passe_avec_stdout_et_entree(tmp_path):
    commande, _ = _commande_avec(tmp_path, 'echo "recu: $(cat)"\nexit 0\n')
    r = _lancer(commande)
    assert r.returncode == 0 and r.stdout == f"recu: {_entree_bash()}\n"


def test_tout_code_non_nul_devient_2(tmp_path):
    for code in (1, 126, 127, 3):
        commande, _ = _commande_avec(tmp_path, f"exit {code}\n")
        assert _lancer(commande).returncode == 2, code


def test_executable_absent_2_et_message(tmp_path):
    commande, faux = _commande_avec(tmp_path, "exit 0\n")
    faux.unlink()
    r = _lancer(commande)
    assert r.returncode == 2 and "introuvable" in r.stderr


def test_ancienne_forme_exec_remplacee_et_annoncee(tmp_path):
    from cime.fondation.reglages import commande_hook, fusionner, reglages
    nouveau = reglages(tmp_path, "main", executable="/opt/bin/cime")
    ancien = reglages(tmp_path, "main", executable="/opt/bin/cime")
    ancien["hooks"]["PreToolUse"][0]["hooks"][0]["command"] = commande_hook(
        "PreToolUse", "/opt/bin/cime", ancien=True)
    assert "exec " in ancien["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    fusion, ajouts = fusionner(ancien, nouveau)
    assert fusion["hooks"]["PreToolUse"] == nouveau["hooks"]["PreToolUse"]
    assert any(a.startswith("remplacé : hooks.PreToolUse") for a in ajouts)
    # idempotent : un second passage ne double rien
    _, ajouts2 = fusionner(fusion, nouveau)
    assert not any("hooks." in a for a in ajouts2)


def test_chemin_avec_espace_et_apostrophe(tmp_path):
    """Le chemin de `cime` est cité (shlex.quote) : une espace ou une apostrophe ne casse
    ni l'appel, ni le refus quand il disparaît, ni la fusion idempotente."""
    from cime.fondation.reglages import fusionner, reglages
    dossier = tmp_path / "mes outils d'essai"
    commande, faux = _commande_avec(dossier, 'echo "ok $1 $2"\nexit 0\n')
    r = _lancer(commande)
    assert r.returncode == 0 and "ok hook PreToolUse" in r.stdout
    os.remove(faux)
    r = _lancer(commande)
    assert r.returncode == 2 and str(faux) in r.stderr
    nouveau = reglages(tmp_path, "main", executable=str(faux))
    premier, _ = fusionner({}, nouveau)
    assert fusionner(premier, nouveau)[1] == []
