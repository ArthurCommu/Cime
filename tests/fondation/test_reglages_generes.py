"""Réglages générés au lancement : bac à sable, dossiers de travail, interdits par rôle,
reprise de l'Assistant."""
import argparse
import json
import os
import re
import shlex
import stat
import subprocess
import textwrap
import types
from pathlib import Path

import pytest

from cime.fondation import init, lancer
from cime.fondation.nom import VAR_AGENT, VAR_PROJET
from cime.fondation.projet import ErreurProjet, lire_manifeste, worktree_equipe
from cime.fondation.reglages import (
    INTERDITS_COORDINATEUR, _avec_rtk, bac_a_sable, reglages,
)

TMPDIR = "CLAUDE_CODE_TMPDIR"
HAIKU = "claude-haiku-4-5-20251001"
GABARIT = Path(__file__).resolve().parents[2] / "src" / "cime" / "gabarits" / ".orga" / "projet.toml"
MANIFESTE = textwrap.dedent("""\
    nom = "Essai"
    prefixe = "essai"
    branche_reference = "main"
    branche_equipe = "equipe/{equipe}"
    worktree_equipe = ".orga/worktrees/{equipe}"
    equipes_speciales = ["assistant"]
    modele_assistant = "modele-assistant"
    modele_coordinateur = "modele-coord"
""")


def _git(dossier, *a):
    subprocess.run(["git", "-C", str(dossier), "-c", "user.name=t",
                    "-c", "user.email=t@t", *a], check=True, capture_output=True)


@pytest.fixture
def maison(tmp_path, monkeypatch):
    """HOME jetable : Path.home() et ~/.claude pointent ici."""
    home = (tmp_path / "maison").resolve()
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


@pytest.fixture
def projet(tmp_path, monkeypatch, maison):
    monkeypatch.delenv(VAR_PROJET, raising=False)
    racine = (tmp_path / "depot").resolve()
    (racine / ".orga" / "teams" / "x" / "tasks" / "todo").mkdir(parents=True)
    (racine / ".orga" / "projet.toml").write_text(MANIFESTE)
    (racine / ".orga" / "teams" / "x" / "mandate.md").write_text("mandat")
    (racine / ".orga" / "teams" / "x" / "tasks" / "todo" / "y.md").write_text("tâche")
    (racine / ".claude").mkdir()
    for nom, marque in (("settings.json", "assistant"), ("settings-agent.json", "agent"),
                        ("settings-coordinateur.json", "coord")):
        (racine / ".claude" / nom).write_text(json.dumps(
            {"marque": marque, "permissions": {"allow": ["Bash(ls*)"], "deny": []}}))
    _git(racine, "init", "-q", "-b", "main")
    _git(racine, "add", "-A")
    _git(racine, "commit", "-qm", "init")
    _git(racine, "worktree", "add", "-q", "-b", "equipe/x", str(racine / ".orga/worktrees/x"))
    monkeypatch.chdir(racine)
    monkeypatch.setattr(lancer, "dossier_outil", lambda: None)  # PATH réel hors des tests
    return racine


@pytest.fixture
def tmux(monkeypatch):
    """Remplace tmux (aucune vraie session) ; processus claude simulés absents."""
    etat = {"existantes": set(), "appels": []}
    monkeypatch.setattr(lancer, "DUREE_SURVEILLANCE", 0)
    monkeypatch.setattr(lancer, "_session_existe", lambda s: s in etat["existantes"])
    monkeypatch.setattr(lancer, "processus_claude_dans", lambda d: [])
    reel = subprocess.run

    def faux(cmd, *a, **k):
        if cmd[0] == "tmux":
            if cmd[1] != "capture-pane":
                etat["appels"].append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return reel(cmd, *a, **k)
    monkeypatch.setattr(lancer.subprocess, "run", faux)
    return etat


def _args(role, equipe=None, tache=None, modele=None, blanc=False):
    return argparse.Namespace(role=role, equipe=equipe, tache=tache, modele=modele,
                              essai_a_blanc=blanc, reprendre=False, session=None)


def _args_reprise(role, equipe=None, session=None):
    return argparse.Namespace(role=role, equipe=equipe, tache=None, modele=None,
                              essai_a_blanc=False, reprendre=True, session=session)


# --- bloc sandbox -----------------------------------------------------------------

def _base(home: str, sites, zones, uid=501):
    return bac_a_sable(Path("/opt/x/projet"), sites, Path(home), uid, zones)


def test_bac_a_sable_tous_les_champs():
    s = _base("/opt/x", ["b.com", "a.com"],
              [Path("/opt/x/projet/.orga/teams/x"), Path("/opt/x/projet/.orga/worktrees/x")],
              )["sandbox"]
    assert s == {
        "enabled": True, "failIfUnavailable": True, "allowUnsandboxedCommands": False,
        "autoAllowBashIfSandboxed": True,
        "filesystem": {
            "denyRead": ["/opt/x"],
            "allowRead": ["/opt/x/projet", "/opt/x/.gitconfig",
                          "/opt/x/.config/git", "/opt/x/.local/share/uv/python",
                          "/opt/x/.local/bin", "/opt/x/.cache/uv"],
            "allowWrite": ["/opt/x/projet/.orga/teams/x",
                           "/opt/x/projet/.orga/worktrees/x",
                           "/opt/x/.cache/uv", "/opt/x/.local/share/uv/python"],
        },
        "network": {"allowLocalBinding": True, "allowedDomains": ["b.com", "a.com"]},
    }


def test_bac_a_sable_ordre_des_sites_conserve():
    s = _base("/opt/x", ["z.com", "a.com", "m.com"], [])["sandbox"]
    assert s["network"]["allowedDomains"] == ["z.com", "a.com", "m.com"]


def test_bac_a_sable_sites_vides_par_defaut():
    s = _base("/opt/x", [], [])["sandbox"]
    assert s["network"]["allowedDomains"] == []


def test_bac_a_sable_lecture_du_projet_seul():
    """Les worktrees sont dans le projet : rien d'autre n'est listé en lecture."""
    s = _base("/opt/x", [], [])["sandbox"]
    assert s["filesystem"]["allowRead"][0] == "/opt/x/projet"
    assert s["filesystem"]["allowRead"].count("/opt/x/projet") == 1
    assert not any("projet-" in chemin for chemin in s["filesystem"]["allowRead"])


def test_bac_a_sable_zones_sans_doublon_et_jamais_private_tmp():
    zones = [Path("/opt/x/projet/.orga/teams/x"), Path("/opt/x/projet/.orga/teams/x")]
    s = _base("/opt/x", [], zones)["sandbox"]["filesystem"]["allowWrite"]
    assert s.count("/opt/x/projet/.orga/teams/x") == 1
    assert "/private/tmp" not in s
    assert not any(c.startswith("/private/tmp") for c in s)


def test_bac_a_sable_ne_lit_pas_le_disque(tmp_path):
    """Tout vient des arguments : un projet inexistant ne fait pas d'erreur."""
    bac_a_sable(tmp_path / "absent", [], tmp_path / "absent-maison", 1, [])


def test_bac_a_sable_outil_ajoute_en_lecture_sans_doublon():
    projet, maison = Path("/opt/x/projet"), Path("/opt/x")
    base = bac_a_sable(projet, [], maison, 501, [])["sandbox"]["filesystem"]
    outil = Path("/opt/x/.local/share/uv/tools/cime")
    s = bac_a_sable(projet, [], maison, 501, [], outil)["sandbox"]["filesystem"]
    assert s["allowRead"] == base["allowRead"] + [str(outil)]
    assert s["allowWrite"] == base["allowWrite"]
    # déjà couvert par `~/.local/bin` : rien d'ajouté
    dans_bin = bac_a_sable(projet, [], maison, 501, [], Path("/opt/x/.local/bin/outil"))
    assert dans_bin["sandbox"]["filesystem"]["allowRead"] == base["allowRead"]


# --- manifeste ----------------------------------------------------------------------

def _manifeste_avec(tmp_path, extra: str):
    (tmp_path / ".orga").mkdir(exist_ok=True)
    (tmp_path / ".orga" / "projet.toml").write_text(MANIFESTE + extra)
    return lire_manifeste(tmp_path)


def test_manifeste_sites_absent_donne_vide(tmp_path):
    assert _manifeste_avec(tmp_path, "").sites == []


def test_manifeste_sites_lus(tmp_path):
    m = _manifeste_avec(tmp_path, '\n[bac_a_sable]\nsites = ["pypi.org", "files.pythonhosted.org"]\n')
    assert m.sites == ["pypi.org", "files.pythonhosted.org"]


@pytest.mark.parametrize("extra", [
    '\n[bac_a_sable]\nsites = "pypi.org"\n',
    '\n[bac_a_sable]\nsites = [1]\n',
    '\n[bac_a_sable]\nsites = [""]\n',
    '\n[bac_a_sable]\nsites = ["  "]\n',
    '\nbac_a_sable = 3\n',
])
def test_manifeste_sites_invalides_refuses(tmp_path, extra):
    with pytest.raises(ErreurProjet, match="bac_a_sable"):
        _manifeste_avec(tmp_path, extra)


def test_gabarit_contient_la_table():
    texte = GABARIT.read_text(encoding="utf-8")
    assert "[bac_a_sable]" in texte and "sites = []" in texte


def test_gabarit_worktrees_dans_le_projet():
    texte = GABARIT.read_text(encoding="utf-8")
    assert 'worktree_equipe = ".orga/worktrees/{equipe}"' in texte
    assert "{depot}" not in texte


def test_init_produit_un_manifeste_lisible(tmp_path, monkeypatch):
    monkeypatch.setattr(init, "executable_cime", lambda: "/opt/outils/bin/cime")
    p = tmp_path / "mon-projet"
    init.installer(types.SimpleNamespace(dossier=str(p), utilisateur="Camille",
                                         nom_projet=None, prefixe=None))
    assert lire_manifeste(p).sites == []


# --- génération au lancement ----------------------------------------------------------

def test_lancer_ecrit_le_fichier_genere(projet, tmux, maison, tmp_path):
    assert lancer.executer(_args("worker", "x", "y", HAIKU)) == 0
    fichier = lancer.fichier_reglages_generes(projet, "worker-x-y")
    assert fichier == projet / ".orga" / "etat" / "reglages" / "worker-x-y.json"
    contenu = json.loads(fichier.read_text(encoding="utf-8"))
    # le contenu statique du rôle (worker = agent) est conservé
    assert contenu["marque"] == "agent"
    assert contenu["permissions"] == {"allow": ["Bash(ls*)"], "deny": []}
    s = contenu["sandbox"]
    assert s["filesystem"]["allowRead"][0] == str(projet)
    assert str(tmp_path / "depot-x") not in s["filesystem"]["allowRead"]
    assert s["network"]["allowedDomains"] == []
    assert s["filesystem"]["denyRead"] == [str(maison)]
    assert contenu["autoMemoryDirectory"] == str(projet / ".orga/etat/memoire/worker-x-y")
    assert (projet / ".orga/etat/memoire/worker-x-y").is_dir()
    (cmd,) = tmux["appels"]
    assert f"{TMPDIR}={projet / '.orga/etat/tmp'}" in cmd
    assert str(fichier) in shlex.join(cmd)


def test_lancer_relit_les_sites_du_manifeste(projet, tmux):
    with open(projet / ".orga" / "projet.toml", "a", encoding="utf-8") as f:
        f.write('\n[bac_a_sable]\nsites = ["pypi.org"]\n')
    assert lancer.executer(_args("worker", "x", "y", HAIKU)) == 0
    contenu = json.loads(lancer.fichier_reglages_generes(projet, "worker-x-y").read_text())
    assert contenu["sandbox"]["network"]["allowedDomains"] == ["pypi.org"]


def test_lancer_pose_le_dossier_tmp_prive(projet, tmux):
    (projet / ".orga" / "etat" / "tmp").mkdir(parents=True)
    os.chmod(projet / ".orga" / "etat" / "tmp", 0o755)
    assert lancer.executer(_args("coord", "x", None, None)) == 0
    tmp = projet / ".orga" / "etat" / "tmp"
    assert stat.S_IMODE(os.stat(tmp).st_mode) == 0o700


def test_essai_a_blanc_n_ecrit_rien(projet, tmux, capsys):
    assert lancer.executer(_args("worker", "x", "y", HAIKU, blanc=True)) == 0
    assert str(lancer.fichier_reglages_generes(projet, "worker-x-y")) in capsys.readouterr().out
    assert not (projet / ".orga" / "etat").exists()
    assert tmux["appels"] == []


@pytest.mark.parametrize("role,equipe,tache,marque", [
    ("assistant", None, None, "assistant"),
    ("worker", "x", "y", "agent"),
    ("coord", "x", None, "coord"),
])
def test_fichier_statique_choisi_par_role(projet, role, equipe, tache, marque):
    identite = lancer._identite(role, equipe, tache)
    m = lire_manifeste(projet)
    fichier = lancer.ecrire_reglages_generes(projet, identite, role, m)
    assert json.loads(fichier.read_text())["marque"] == marque


def _ecriture(projet, identite, role, integration=False):
    fichier = lancer.ecrire_reglages_generes(projet, identite, role, lire_manifeste(projet),
                                             integration=integration)
    return json.loads(fichier.read_text())["sandbox"]["filesystem"]["allowWrite"]


def test_zones_ecriture_par_identite(projet):
    assert _ecriture(projet, "worker-x-y", "worker") == [
        str(projet / ".orga/teams/x"), str(projet / ".orga/teams/integration/requests"),
        str(projet / ".orga/etat/tmp"), str(projet / ".orga/etat/memoire/worker-x-y"),
        str(projet / ".orga/worktrees/x"),
    ] + _caches()
    assert _ecriture(projet, "coord-x", "coord")[-1] == _caches()[-1]
    assert str(projet / ".orga/worktrees/x") in _ecriture(projet, "coord-x", "coord")


def test_assistant_hors_bac_a_sable(projet):
    """Décision de l'utilisateur : l'Assistant ne tourne pas dans le bac à sable. Pas de `sandbox`,
    mais les autres réglages du rôle commun restent (hooks, permissions, mémoire, tmp)."""
    fichier = lancer.ecrire_reglages_generes(projet, "assistant", "assistant",
                                             lire_manifeste(projet))
    contenu = json.loads(fichier.read_text(encoding="utf-8"))
    assert "sandbox" not in contenu
    assert contenu["marque"] == "assistant"
    assert contenu["autoMemoryDirectory"] == str(projet / ".orga/etat/memoire/assistant")
    assert (projet / ".orga/etat/memoire/assistant").is_dir()


def test_assistant_garde_le_statique_de_son_role(projet):
    """Hooks et permissions de `settings.json` passent telles quels à l'Assistant."""
    statique = json.loads((projet / ".claude" / "settings.json").read_text())
    fichier = lancer.ecrire_reglages_generes(projet, "assistant", "assistant",
                                             lire_manifeste(projet))
    contenu = json.loads(fichier.read_text(encoding="utf-8"))
    assert contenu["permissions"] == statique["permissions"] == {
        "allow": ["Bash(ls*)"], "deny": []}
    assert contenu["marque"] == "assistant"


@pytest.mark.parametrize("role,identite,integration", [
    ("coord", "coord-x", False), ("worker", "worker-x-y", False),
    ("coord", "worker-integration-r1", True),
])
def test_agents_gardent_leur_bac_a_sable(projet, role, identite, integration):
    fichier = lancer.ecrire_reglages_generes(projet, identite, role, lire_manifeste(projet),
                                             integration=integration)
    contenu = json.loads(fichier.read_text(encoding="utf-8"))
    assert contenu["sandbox"]["enabled"] is True
    assert contenu["sandbox"]["failIfUnavailable"] is True


# --- dossier de l'outil cime, rouvert en lecture ----------------------------------------

def _faux_environnement(tmp_path):
    """Environnement d'outil façon `uv tool` : tools/cime/pyvenv.cfg, bin/cime ; et un
    lien `autre/bin/cime-lien` vers lui, hors de cet environnement."""
    env = tmp_path / "tools" / "cime"
    (env / "bin").mkdir(parents=True)
    (env / "pyvenv.cfg").write_text("home = /x\n")
    cible = env / "bin" / "cime"
    cible.write_text("#!/bin/sh\n")
    lien_dossier = tmp_path / "autre" / "bin"
    lien_dossier.mkdir(parents=True)
    (lien_dossier / "cime-lien").symlink_to(cible)
    return env, cible, lien_dossier / "cime-lien"


def test_racine_de_l_outil_remonte_jusqu_au_pyvenv(tmp_path):
    env, cible, _ = _faux_environnement(tmp_path)
    assert lancer.racine_de_l_outil(cible.resolve()) == env.resolve()


def test_racine_de_l_outil_sans_pyvenv_prend_le_dossier_de_la_cible(tmp_path):
    (tmp_path / "nu" / "bin").mkdir(parents=True)
    cible = tmp_path / "nu" / "bin" / "cime"
    cible.write_text("")
    assert lancer.racine_de_l_outil(cible) == tmp_path / "nu" / "bin"


def test_dossier_outil_resout_le_lien_par_which(tmp_path, monkeypatch, maison):
    env, _, lien = _faux_environnement(tmp_path)
    monkeypatch.setattr(lancer.shutil, "which", lambda nom: str(lien))
    assert lancer.dossier_outil() == env.resolve()


def test_dossier_outil_jamais_la_maison(tmp_path, monkeypatch, maison):
    """Un exécutable posé directement dans la maison ne rouvre pas la maison entière."""
    cible = maison / "cime"
    cible.write_text("")
    monkeypatch.setattr(lancer.shutil, "which", lambda nom: str(cible))
    assert lancer.dossier_outil() is None


def test_dossier_outil_sans_which_se_rabat_sur_python(tmp_path, monkeypatch, maison):
    env, cible, _ = _faux_environnement(tmp_path)
    monkeypatch.setattr(lancer.shutil, "which", lambda nom: None)
    monkeypatch.setattr(lancer.sys, "argv", ["cime"])
    monkeypatch.setattr(lancer.sys, "executable", str(cible))
    assert lancer.dossier_outil() == env.resolve()


def test_outil_dans_le_projet_n_ajoute_rien(projet):
    venv = projet / ".venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("")
    lecture = bac_a_sable(projet, [], Path.home(), 1, [], outil=venv)["sandbox"]["filesystem"]
    assert lecture["allowRead"] == bac_a_sable(projet, [], Path.home(), 1, [])["sandbox"][
        "filesystem"]["allowRead"]


def test_outil_hors_projet_ajoute_une_fois_en_lecture(projet, tmp_path, monkeypatch):
    env, _, _ = _faux_environnement(tmp_path)
    monkeypatch.setattr(lancer, "dossier_outil", lambda: env.resolve())
    for role, identite, integration in (("coord", "coord-x", False),
                                        ("worker", "worker-x-y", False),
                                        ("coord", "worker-integration-r1", True)):
        fichier = lancer.ecrire_reglages_generes(projet, identite, role, lire_manifeste(projet),
                                                 integration=integration)
        filesystem = json.loads(fichier.read_text())["sandbox"]["filesystem"]
        assert filesystem["allowRead"].count(str(env.resolve())) == 1, identite
        assert not any(c == str(env.resolve()) for c in filesystem["allowWrite"]), identite


def test_integration_ecrit_dans_essais_et_jamais_private_tmp(projet):
    (projet / ".orga" / "teams" / "integration").mkdir(parents=True)
    ecriture = _ecriture(projet, "worker-integration-r1", "coord", integration=True)
    assert str(projet / ".orga/etat/essais") in ecriture
    assert str(projet / ".orga/teams/integration") in ecriture
    assert not any(c.startswith("/private/tmp") for c in ecriture)
    assert str(projet / ".orga/worktrees/x") not in ecriture


def _caches():
    home = str(Path.home())
    return [f"{home}/.cache/uv", f"{home}/.local/share/uv/python"]


def test_fichier_statique_absent_message_clair(projet, tmux, capsys):
    (projet / ".claude" / "settings-agent.json").unlink()
    assert lancer.executer(_args("worker", "x", "y", HAIKU)) == 1
    err = capsys.readouterr().err
    assert "settings-agent.json" in err and "init" in err
    assert tmux["appels"] == []


# --- interdits par rôle -----------------------------------------------------------------

PROJET = Path("/opt/x/projet")
ASSOCIES = ("Bash(git branch -D*)", "Bash(git branch --delete*)",
            "Bash(git -C /opt/x/projet merge*)", "Bash(osascript *)")


def test_commun_garde_push_et_secrets_sans_les_interdits_d_agent():
    deny = reglages(PROJET, "main", "commun")["permissions"]["deny"]
    for r in ("Bash(git push*)", "Bash(git -C * push*)", "Bash(rtk git push*)",
              "Bash(security *)", "Read(~/.ssh/**)", "Read(~/.aws/**)",
              "Read(~/.config/gh/**)", "Read(**/.env)", "Read(**/.env.*)"):
        assert r in deny, r
    for r in ASSOCIES:
        assert r not in deny, r


def test_agent_ajoute_branches_merge_et_osascript():
    commun = reglages(PROJET, "main", "commun")["permissions"]["deny"]
    agent = reglages(PROJET, "main", "agent")["permissions"]["deny"]
    assert set(commun) <= set(agent)
    for r in ASSOCIES + ("Bash(git -C * branch -D*)", "Bash(rtk git branch -d*)"):
        assert r in agent, r
    assert not any(r in INTERDITS_COORDINATEUR for r in agent)


def test_coordinateur_ajoute_ses_interdits_git():
    agent = reglages(PROJET, "main", "agent")["permissions"]["deny"]
    coord = reglages(PROJET, "main", "coordinateur")["permissions"]["deny"]
    assert set(agent) <= set(coord)
    assert set(_avec_rtk(list(INTERDITS_COORDINATEUR))) <= set(coord)


def test_role_inconnu_refuse():
    with pytest.raises(ValueError):
        reglages(PROJET, "main", "inconnu")


# --- init : fichier agent et second passage ---------------------------------------------

def test_init_ecrit_settings_agent_puis_second_passage_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(init, "executable_cime", lambda: "/opt/outils/bin/cime")
    p = tmp_path / "mon-projet"
    args = types.SimpleNamespace(dossier=str(p), utilisateur="Camille", nom_projet=None,
                                 prefixe=None)
    premier = init.installer(args)
    assert ".claude/settings-agent.json" in premier["ajouté"]
    assert (p / ".orga/etat/tmp").is_dir() and (p / ".orga/etat/memoire").is_dir()
    assert stat.S_IMODE(os.stat(p / ".orga/etat/tmp").st_mode) == 0o700
    second = init.installer(args)
    assert ".claude/settings-agent.json" in second["déjà présent"]
    assert not [l for l in second["complété"] + second["ajouté"] if "settings" in l]


def test_init_complete_un_projet_sans_settings_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(init, "executable_cime", lambda: "/opt/outils/bin/cime")
    p = tmp_path / "ancien"
    args = types.SimpleNamespace(dossier=str(p), utilisateur="Camille", nom_projet=None,
                                 prefixe=None)
    init.installer(args)
    (p / ".claude" / "settings-agent.json").unlink()
    rapport = init.installer(args)
    assert ".claude/settings-agent.json" in rapport["ajouté"]


# --- reprise de l'Assistant -------------------------------------------------------------

def _conversation(projet, nom="abc-1"):
    dossier = lancer.dossier_conversations(projet)
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / f"{nom}.jsonl").write_text("{}")


def test_reprise_assistant_resume_sans_message_et_identite(projet, tmux, maison, capsys):
    _conversation(projet)
    assert lancer.executer(_args_reprise("assistant")) == 0
    (cmd,) = tmux["appels"]
    assert cmd[cmd.index("-e") + 1] == f"{VAR_AGENT}=assistant"
    ligne = cmd[-1]
    assert "--resume abc-1" in ligne
    assert "commence ta mission" not in ligne


def test_reprise_assistant_commande_resume(projet):
    _conversation(projet, "conv-9")
    _, dossier, env, ligne = lancer.commande(
        projet, lire_manifeste(projet), "assistant", None, None, None, "conv-9")
    assert dossier == projet
    assert env[VAR_AGENT] == "assistant"
    assert ligne[-2:] == ["--resume", "conv-9"]


def test_reprise_assistant_session_explicite(projet, tmux, maison):
    _conversation(projet, "choisie")
    _conversation(projet, "autre")
    assert lancer.executer(_args_reprise("assistant", session="choisie")) == 0
    assert "--resume choisie" in tmux["appels"][0][-1]


def test_reprise_assistant_refus_si_session_existe(projet, tmux, maison, capsys):
    _conversation(projet)
    tmux["existantes"].add("essai-assistant")
    assert lancer.executer(_args_reprise("assistant")) == 2
    assert "encore lancée" in capsys.readouterr().err
    assert tmux["appels"] == []


def test_reprise_assistant_refus_sans_conversation(projet, tmux, maison, capsys):
    assert lancer.executer(_args_reprise("assistant")) == 2
    assert "aucune conversation" in capsys.readouterr().err
    assert tmux["appels"] == []


def test_reprise_assistant_refus_si_claude_ouvert_dans_le_dossier(projet, tmux, maison,
                                                                  monkeypatch, capsys):
    _conversation(projet)
    monkeypatch.setattr(lancer, "processus_claude_dans", lambda d: [4242])
    assert lancer.executer(_args_reprise("assistant")) == 2
    assert "encore ouverte" in capsys.readouterr().err
    assert tmux["appels"] == []


def test_reprise_worker_toujours_refusee(projet, tmux, maison, capsys):
    assert lancer.executer(_args_reprise("worker", "x")) == 2
    assert "n'est accepté que pour coord et assistant" in capsys.readouterr().err
    assert tmux["appels"] == []


def _s_applique(groupe: dict, outil: str) -> bool:
    """La règle de Claude Code : un groupe sans `matcher` s'applique à tout outil ; un groupe
    avec `matcher` s'applique si le nom de l'outil correspond."""
    matcher = groupe.get("matcher")
    return not matcher or re.fullmatch(matcher, outil) is not None


OUTILS_GARDES = ("Write", "Read", "Edit", "Grep", "Glob", "NotebookEdit")


@pytest.mark.parametrize("role", ["commun", "agent", "coordinateur"])
def test_hook_pretooluse_s_applique_aux_outils_de_chemin(role):
    """Le défaut mesuré en réel : avec `matcher: Bash`, la garde de périmètre n'était jamais
    appelée pour Write, Read, Edit… Le hook doit s'appliquer à chacun, pour chaque rôle."""
    groupes = reglages(PROJET, "main", role)["hooks"]["PreToolUse"]
    assert len(groupes) == 1
    for outil in (*OUTILS_GARDES, "Bash"):
        assert [g for g in groupes if _s_applique(g, outil)], outil


# --- hooks de la phase 2b : StopFailure, timeout de Stop, socket tmux retiré -----------------

def _stop(role):
    from cime.fondation.reglages import reglages
    return reglages(Path("/opt/x/projet"), "main", role)["hooks"]


def test_hook_stop_failure_present():
    for role in ("commun", "agent", "coordinateur"):
        assert "StopFailure" in _stop(role)


def test_timeout_stop_couvre_l_attente_plus_la_marge():
    from cime.signaux import echeances
    assert _stop("agent")["Stop"][0]["hooks"][0]["timeout"] == \
        echeances.ATTENTE_STOP + echeances.MARGE_STOP
    assert _stop("coordinateur")["Stop"][0]["hooks"][0]["timeout"] == 150
    # l'Assistant (fichier "commun") ne dort jamais : marge seule
    assert _stop("commun")["Stop"][0]["hooks"][0]["timeout"] == echeances.MARGE_STOP
    assert "timeout" not in _stop("agent")["PostToolUse"][0]["hooks"][0]


def test_aucun_socket_unix_dans_le_bac_a_sable():
    assert "allowUnixSockets" not in _base("/opt/x", [], [])["sandbox"]["network"]


def test_reprise_assistant_pose_identite_et_projet_dans_la_commande_tmux(projet, tmux, maison):
    """`cime lancer assistant --reprendre` pose aussi CIME_AGENT=assistant et CIME_PROJET."""
    _conversation(projet)
    assert lancer.executer(_args_reprise("assistant")) == 0
    (cmd,) = tmux["appels"]
    variables = {cmd[i + 1] for i, a in enumerate(cmd) if a == "-e"}
    assert f"{VAR_AGENT}=assistant" in variables
    assert f"{VAR_PROJET}={projet}" in variables


# --- le droit de commit du coordinateur dans le worktree de son équipe -----------

def _allow(projet, identite, role):
    fichier = lancer.ecrire_reglages_generes(projet, identite, role, lire_manifeste(projet))
    return json.loads(fichier.read_text())["permissions"]["allow"]


def test_la_liste_generee_du_coordinateur_porte_la_regle_de_son_equipe_et_d_elle_seule(projet):
    m = lire_manifeste(projet)
    wt_x, wt_y = (worktree_equipe(projet, m, e) for e in ("x", "y"))
    allow_x = _allow(projet, "coord-x", "coord")
    assert f"Bash(git -C {wt_x} add*)" in allow_x and f"Bash(git -C {wt_x} commit*)" in allow_x
    assert not any(str(wt_y) in r for r in allow_x)
    allow_y = _allow(projet, "coord-y", "coord")
    assert f"Bash(git -C {wt_y} commit*)" in allow_y and not any(str(wt_x) in r for r in allow_y)
    # le fichier statique reste intact : la règle n'est pas écrite pour tous
    assert not any(" add*)" in r for r in json.loads(
        (projet / ".claude" / "settings-coordinateur.json").read_text())["permissions"]["allow"])


@pytest.mark.parametrize("identite,role", [("worker-x-y", "worker"), ("assistant", "assistant")])
def test_ni_le_worker_ni_l_assistant_ne_recoivent_la_regle(projet, identite, role):
    assert not any(" add*)" in r for r in _allow(projet, identite, role))


def test_le_coordinateur_ne_commite_plus_sous_un_interdit_de_permission(projet):
    deny = reglages(PROJET, "main", "coordinateur")["permissions"]["deny"]
    assert "Bash(git commit*)" not in deny and "Bash(git add*)" not in deny
    for r in ("Bash(git reset*)", "Bash(git -C * reset*)", "Bash(git -C * checkout*)",
              "Bash(git commit*--amend*)", "Bash(git -C * commit*--no-verify*)"):
        assert r in deny, r


def test_integration_ne_commite_ni_ne_fusionne_jamais(projet):
    """Registre 2.0 : la session d'intégration n'écrit pas le projet. Ses réglages refusent
    `git add`, `git commit` et `git merge`, avec ou sans `-C` (un `deny` l'emporte sur tout `allow`)."""
    m = lire_manifeste(projet)
    integration = json.loads(lancer.ecrire_reglages_generes(
        projet, "worker-integration-r1", "coord", m, integration=True).read_text())
    deny = integration["permissions"]["deny"]
    for verbe in ("add", "commit", "merge"):
        for regle in (f"Bash(git {verbe}*)", f"Bash(git -C * {verbe}*)",
                      f"Bash(rtk git {verbe}*)", f"Bash(rtk git -C * {verbe}*)"):
            assert regle in deny, regle
    # un coordinateur d'équipe, lui, garde son droit de commit : la règle ne le touche pas
    coord = json.loads(lancer.ecrire_reglages_generes(projet, "coord-x", "coord", m).read_text())
    assert not any(r.startswith(("Bash(git add", "Bash(git commit", "Bash(git merge"))
                   for r in coord["permissions"]["deny"])
