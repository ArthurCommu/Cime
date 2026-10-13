import argparse
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import textwrap

import pytest

from cime.fondation import lancer
from cime.fondation import reglages as reglages_mod
from cime.fondation.nom import VAR_AGENT, VAR_PROJET
from cime.fondation.projet import ErreurProjet, lire_manifeste

TMPDIR = "CLAUDE_CODE_TMPDIR"

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
HAIKU = "claude-haiku-4-5-20251001"


def _git(dossier, *a):
    subprocess.run(["git", "-C", str(dossier), "-c", "user.name=t",
                    "-c", "user.email=t@t", *a], check=True, capture_output=True)


@pytest.fixture
def projet(tmp_path, monkeypatch):
    monkeypatch.delenv(VAR_PROJET, raising=False)
    racine = (tmp_path / "depot").resolve()
    (racine / ".orga" / "teams" / "x" / "tasks" / "todo").mkdir(parents=True)
    (racine / ".orga" / "projet.toml").write_text(MANIFESTE)
    (racine / ".orga" / "teams" / "x" / "mandate.md").write_text("mandat")
    (racine / ".orga" / "teams" / "x" / "tasks" / "todo" / "y.md").write_text("tâche")
    (racine / ".claude").mkdir()
    (racine / ".claude" / "settings.json").write_text("{}")
    (racine / ".claude" / "settings-agent.json").write_text("{}")
    (racine / ".claude" / "settings-coordinateur.json").write_text("{}")
    _git(racine, "init", "-q", "-b", "main")
    _git(racine, "add", "-A")
    _git(racine, "commit", "-qm", "init")
    _git(racine, "worktree", "add", "-q", "-b", "equipe/x", str(racine / ".orga/worktrees/x"))
    monkeypatch.chdir(racine)
    return racine


@pytest.fixture
def tmux(monkeypatch):
    """Remplace tmux : enregistre les lancements, session_existe pilotable."""
    etat = {"existantes": set(), "appels": []}
    monkeypatch.setattr(lancer, "DUREE_SURVEILLANCE", 0)
    # L'autotest d'import ne lance pas l'interpréteur de l'outil : ce serait un sous-processus
    # réel, et celui de la machine (pas celui du test) ; on lui rend ce que voit ce processus.
    paquet = Path(lancer.os.path.realpath(reglages_mod._paquet_cime()))
    monkeypatch.setattr(reglages_mod, "sonder_import_cime",
                        lambda python: (paquet, [str(paquet.parent)]))
    monkeypatch.setattr(lancer, "_session_existe", lambda s: s in etat["existantes"])
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
    return argparse.Namespace(role=role, equipe=equipe, tache=tache,
                              modele=modele, essai_a_blanc=blanc)


def _manif(projet):
    return lire_manifeste(projet)


def test_assistant(projet):
    session, dossier, env, ligne = lancer.commande(
        projet, _manif(projet), "assistant", None, None, None)
    assert session == "essai-assistant"
    assert dossier == projet
    assert env == {VAR_AGENT: "assistant", VAR_PROJET: str(projet),
                   TMPDIR: str(projet / ".orga/etat/tmp")}
    assert ligne == [
        "claude", "--model", "modele-assistant", "--permission-mode", "auto",
        "--settings", str(reglages_mod.fichier_reglages_generes(projet, "assistant")),
        "Lis .orga/teams/assistant/CLAUDE.md et commence ta mission."]


def test_coordinateur(projet):
    session, dossier, env, ligne = lancer.commande(
        projet, _manif(projet), "coord", "x", None, None)
    assert session == "essai-coord-x"
    assert dossier == projet / ".orga" / "teams" / "x"
    assert env == {VAR_AGENT: "coord-x", VAR_PROJET: str(projet),
                   TMPDIR: str(projet / ".orga/etat/tmp")}
    assert ligne == [
        "claude", "--model", "modele-coord", "--permission-mode", "auto",
        "--settings", str(reglages_mod.fichier_reglages_generes(projet, "coord-x")),
        "Lis CLAUDE.md puis mandate.md et commence ta mission."]


def test_worker(projet, tmp_path):
    session, dossier, env, ligne = lancer.commande(
        projet, _manif(projet), "worker", "x", "y", HAIKU)
    assert session == "essai-worker-x-y"
    assert dossier == projet / ".orga/worktrees/x"
    assert env == {VAR_AGENT: "worker-x-y", VAR_PROJET: str(projet),
                   TMPDIR: str(projet / ".orga/etat/tmp")}
    en_cours = projet / ".orga/teams/x/tasks/in-progress/y.md"
    assert ligne == [
        "claude", "--model", HAIKU, "--permission-mode", "auto",
        "--settings", str(reglages_mod.fichier_reglages_generes(projet, "worker-x-y")),
        f"Lis {en_cours} et exécute-le."]


def test_modele_explicite_prime_sur_le_manifeste(projet):
    ligne = lancer.commande(projet, _manif(projet), "coord", "x", None, HAIKU)[3]
    assert ligne[2] == HAIKU


def test_worker_sans_modele(projet):
    with pytest.raises(ErreurProjet, match="--modele obligatoire"):
        lancer.commande(projet, _manif(projet), "worker", "x", "y", None)


def test_reglages_absents(projet):
    (projet / ".claude" / "settings-coordinateur.json").unlink()
    with pytest.raises(ErreurProjet, match="init"):
        reglages_mod.fichier_reglages_statique(projet, "coord")
    assert reglages_mod.fichier_reglages_statique(projet, "worker").name == "settings-agent.json"
    assert reglages_mod.fichier_reglages_statique(projet, "assistant").name == "settings.json"


@pytest.mark.parametrize("equipe,tache", [("X", "y"), ("x_1", "y"), ("x", "Y!"), ("x/..", "y")])
def test_noms_invalides(projet, tmux, capsys, equipe, tache):
    assert lancer.executer(_args("worker", equipe, tache, HAIKU)) == 1
    assert "invalide" in capsys.readouterr().err
    assert tmux["appels"] == []


def test_lancement_worker_deplace_la_tache(projet, tmux, capsys, tmp_path):
    assert lancer.executer(_args("worker", "x", "y", HAIKU)) == 0
    assert capsys.readouterr().out.strip() == "essai-worker-x-y"
    taches = projet / ".orga/teams/x/tasks"
    assert not (taches / "todo" / "y.md").exists()
    assert (taches / "in-progress" / "y.md").read_text() == "tâche"
    (cmd,) = tmux["appels"]
    assert cmd[:8] == ["tmux", "new-session", "-d", "-s", "essai-worker-x-y",
                       "-c", str(projet / ".orga/worktrees/x"), "-e"]
    assert f"{VAR_AGENT}=worker-x-y" in cmd and f"{VAR_PROJET}={projet}" in cmd
    ligne = shlex.split(cmd[-1])
    assert ligne[0] == "claude" and ligne[-1].endswith("y.md et exécute-le.")


def test_essai_a_blanc_ne_deplace_rien(projet, tmux, capsys):
    assert lancer.executer(_args("worker", "x", "y", HAIKU, blanc=True)) == 0
    sortie = capsys.readouterr().out
    assert sortie.startswith("tmux new-session -d -s essai-worker-x-y")
    assert tmux["appels"] == []
    assert (projet / ".orga/teams/x/tasks/todo/y.md").is_file()
    assert not (projet / ".orga/teams/x/tasks/in-progress/y.md").exists()


def test_lancement_coord_et_assistant(projet, tmux):
    assert lancer.executer(_args("coord", "x")) == 0
    assert lancer.executer(_args("assistant")) == 0
    assert [c[4] for c in tmux["appels"]] == ["essai-coord-x", "essai-assistant"]


def test_tache_absente(projet, tmux, capsys):
    assert lancer.executer(_args("worker", "x", "absente", HAIKU)) == 1
    assert "tâche absente" in capsys.readouterr().err
    assert tmux["appels"] == []


def test_session_deja_existante(projet, tmux, capsys):
    tmux["existantes"].add("essai-coord-x")
    assert lancer.executer(_args("coord", "x")) == 1
    assert "déjà lancée" in capsys.readouterr().err
    assert tmux["appels"] == []


def test_session_worker_existante_ne_deplace_pas(projet, tmux):
    tmux["existantes"].add("essai-worker-x-y")
    assert lancer.executer(_args("worker", "x", "y", HAIKU)) == 1
    assert (projet / ".orga/teams/x/tasks/todo/y.md").is_file()


def test_worktree_absent(projet, tmux, capsys):
    _git(projet, "worktree", "remove", "--force", str(projet / ".orga/worktrees/x"))
    assert lancer.executer(_args("worker", "x", "y", HAIKU)) == 1
    assert "worktree absent" in capsys.readouterr().err
    assert (projet / ".orga/teams/x/tasks/todo/y.md").is_file()


def test_equipe_sans_mandat(projet, tmux, capsys):
    (projet / ".orga/teams/x/mandate.md").unlink()
    assert lancer.executer(_args("coord", "x")) == 1
    assert "mandate.md" in capsys.readouterr().err


def test_equipe_cloturee(projet, tmux, capsys):
    (projet / ".orga/teams/x/CLOTUREE").write_text("")
    assert lancer.executer(_args("coord", "x")) == 1
    assert "terminée" in capsys.readouterr().err


def test_echec_tmux_remet_la_tache(projet, monkeypatch, tmux):
    def echec(cmd, *a, **k):
        return subprocess.CompletedProcess(cmd, 1, "", "boom")
    monkeypatch.setattr(lancer.subprocess, "run", echec)
    assert lancer.executer(_args("worker", "x", "y", HAIKU)) == 1
    assert (projet / ".orga/teams/x/tasks/todo/y.md").is_file()


@pytest.fixture
def integration(projet):
    equipe = projet / ".orga" / "teams" / "integration"
    (equipe / "requests" / "todo").mkdir(parents=True)
    (equipe / "mandate.md").write_text("mandat")
    (equipe / "requests" / "todo" / "r1.md").write_text("requête")
    return equipe


def test_integration_commande(projet, integration):
    session, dossier, env, ligne = lancer.commande(
        projet, _manif(projet), "worker", "integration", "r1", HAIKU)
    assert session == "essai-worker-integration-r1"
    assert dossier == integration
    assert env == {TMPDIR: str(projet / ".orga/etat/tmp")}
    assert ligne == [
        "env", "-u", VAR_AGENT, "-u", VAR_PROJET,
        "claude", "--model", HAIKU, "--permission-mode", "auto",
        "--settings", str(reglages_mod.fichier_reglages_generes(projet, "worker-integration-r1")),
        f"Lis {integration / 'requests/todo/r1.md'} et traite-la."]


def test_integration_commande_tmux_sans_variables(projet, integration):
    session, dossier, env, ligne = lancer.commande(
        projet, _manif(projet), "worker", "integration", "r1", HAIKU)
    cmd = lancer._commande_tmux(session, dossier, env, ligne)
    assert cmd[cmd.index("-e") + 1] == f"{TMPDIR}={projet / '.orga/etat/tmp'}"
    assert not any(f"{v}=" in a for a in cmd for v in (VAR_AGENT, VAR_PROJET))
    assert cmd[-1].startswith(f"env -u {VAR_AGENT} -u {VAR_PROJET} claude ")


def test_autres_roles_gardent_leurs_variables(projet):
    _, _, env, ligne = lancer.commande(projet, _manif(projet), "coord", "x", None, HAIKU)
    assert env == {VAR_AGENT: "coord-x", VAR_PROJET: str(projet),
                   TMPDIR: str(projet / ".orga/etat/tmp")}
    assert ligne[0] == "claude"


def test_integration_sans_modele(projet, integration):
    with pytest.raises(ErreurProjet, match="--modele obligatoire"):
        lancer.commande(projet, _manif(projet), "worker", "integration", "r1", None)


def test_integration_lancement_ne_deplace_pas_la_requete(projet, integration, tmux, capsys):
    assert lancer.executer(_args("worker", "integration", "r1", HAIKU)) == 0
    assert capsys.readouterr().out.strip() == "essai-worker-integration-r1"
    assert (integration / "requests/todo/r1.md").read_text() == "requête"
    assert not (integration / "tasks").exists()
    (cmd,) = tmux["appels"]
    assert cmd[:7] == ["tmux", "new-session", "-d", "-s", "essai-worker-integration-r1",
                       "-c", str(integration)]


def test_integration_requete_absente(projet, integration, tmux, capsys):
    assert lancer.executer(_args("worker", "integration", "absente", HAIKU)) == 1
    err = capsys.readouterr().err
    assert "requête absente" in err and "requests/todo/absente.md" in err
    assert tmux["appels"] == []


def test_integration_essai_a_blanc(projet, integration, tmux, capsys):
    assert lancer.executer(_args("worker", "integration", "r1", HAIKU, blanc=True)) == 0
    assert capsys.readouterr().out.startswith(
        "tmux new-session -d -s essai-worker-integration-r1")
    assert tmux["appels"] == []
    assert (integration / "requests/todo/r1.md").is_file()


def test_integration_sans_mandat_ou_cloturee(projet, integration, tmux, capsys):
    (integration / "CLOTUREE").write_text("")
    assert lancer.executer(_args("worker", "integration", "r1", HAIKU)) == 1
    assert "terminée" in capsys.readouterr().err
    (integration / "CLOTUREE").unlink()
    (integration / "mandate.md").unlink()
    assert lancer.executer(_args("worker", "integration", "r1", HAIKU)) == 1
    assert "mandate.md" in capsys.readouterr().err
    assert tmux["appels"] == []


INVITE = Path(__file__).parent / "fixtures" / "invite"


def _capture(nom):
    return (INVITE / f"{nom}.ansi").read_text(encoding="utf-8")


@pytest.mark.parametrize("nom, attendu", [
    ("import-trust-sousdossier", "confiance"),
    ("import-demande-approbation", "imports"),
    ("invite-vide", None),
    ("agent-au-travail", None),
])
def test_ecran_de_demarrage_sur_captures_reelles(nom, attendu):
    assert lancer.ecran_de_demarrage(_capture(nom)) == attendu


def _surveiller(captures):
    suite = iter(captures)
    dormis = []
    r = lancer.surveiller_demarrage(
        "s", capturer=lambda s: next(suite, captures[-1]), delai=1, duree=3,
        dormir=dormis.append)
    return r, dormis


def test_surveillance_ecran_d_approbation():
    assert _surveiller(["", _capture("import-trust-sousdossier")]) == ("confiance", [1])
    assert _surveiller([_capture("import-demande-approbation")]) == ("imports", [])


def test_surveillance_invite_ou_agent_au_travail():
    assert _surveiller([_capture("invite-vide")]) == ("invite", [])
    assert _surveiller(["", _capture("agent-au-travail")]) == ("invite", [1])


def test_surveillance_rien_au_bout_du_delai():
    assert _surveiller([""]) == (None, [1, 1, 1])


def _tmux_avec_ecran(monkeypatch, tmux, ecran):
    touches = []
    reel = lancer.subprocess.run

    def faux(cmd, *a, **k):
        if cmd[:2] == ["tmux", "capture-pane"]:
            return subprocess.CompletedProcess(cmd, 0, ecran, "")
        if cmd[:2] == ["tmux", "send-keys"]:
            touches.append(cmd)
        return reel(cmd, *a, **k)
    monkeypatch.setattr(lancer.subprocess, "run", faux)
    return touches


@pytest.mark.parametrize("nom, libelle", [
    ("import-trust-sousdossier", "confiance du dossier"),
    ("import-demande-approbation", "imports externes"),
])
def test_lancer_ecran_d_approbation_code_3_sans_touche(
        projet, tmux, monkeypatch, capsys, nom, libelle):
    touches = _tmux_avec_ecran(monkeypatch, tmux, _capture(nom))
    assert lancer.executer(_args("coord", "x")) == 3
    sortie = capsys.readouterr()
    assert sortie.out.strip() == "essai-coord-x"
    assert sortie.err.strip() == (
        f"lancer : essai-coord-x attend une approbation de l'utilisateur ({libelle})"
        " — à faire une fois : tmux attach -t essai-coord-x")
    assert touches == []
    assert not any(c[1] in ("kill-session", "send-keys") for c in tmux["appels"])


def test_lancer_invite_atteinte_code_0(projet, tmux, monkeypatch, capsys):
    _tmux_avec_ecran(monkeypatch, tmux, _capture("invite-vide"))
    assert lancer.executer(_args("coord", "x")) == 0
    assert capsys.readouterr().err == ""


def test_lancer_rien_de_reconnu_avertit(projet, tmux, capsys):
    assert lancer.executer(_args("coord", "x")) == 0
    assert "écran non reconnu après" in capsys.readouterr().err


# --- reprise d'un coordinateur (--reprendre) ---------------------------------

def _args_reprise(role="coord", equipe="x", session=None, blanc=False, reprendre=True):
    a = _args(role, equipe, None, HAIKU if role == "worker" else None, blanc)
    a.reprendre, a.session = reprendre, session
    return a


@pytest.fixture
def claude(projet, tmp_path, monkeypatch):
    """Faux ~/.claude (HOME dans tmp_path), personne ne tourne dans le dossier."""
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(lancer, "processus_claude_dans", lambda dossier: [])
    sous = lancer.dossier_conversations(projet / ".orga" / "teams" / "x", home / ".claude")
    sous.mkdir(parents=True)
    return sous


def _conversation(sous, nom, mtime):
    f = sous / f"{nom}.jsonl"
    f.write_text("{}")
    os.utime(f, (mtime, mtime))
    return f


def test_encodage_mesure_sur_claude_2_1_293():
    # Mesuré : tout caractère hors [A-Za-z0-9] -> "-" ; "a b.c_d+é@x" -> "a-b-c-d---x".
    assert lancer.encoder_dossier(Path("/opt/exemple/mon-outil/.orga/teams/hote")) == \
        "-opt-exemple-mon-outil--orga-teams-hote"
    assert lancer.encoder_dossier(Path("/opt/u/a b.c_d+é@x")) == "-opt-u-a-b-c-d---x"


def test_encodage_utilise_le_chemin_reel(tmp_path):
    vrai = tmp_path / "vrai"
    vrai.mkdir()
    lien = tmp_path / "lien"
    lien.symlink_to(vrai)
    assert lancer.encoder_dossier(lien) == lancer.encoder_dossier(vrai)


def test_derniere_conversation_la_plus_recente(claude, projet):
    _conversation(claude, "vieille", 1000)
    _conversation(claude, "recente", 3000)
    _conversation(claude, "milieu", 2000)
    (claude / "sous").mkdir()
    _conversation(claude / "sous", "plus-recente-mais-en-sous-dossier", 9000)
    (claude / "notes.txt").write_text("pas une conversation")
    dossier = projet / ".orga" / "teams" / "x"
    assert lancer.derniere_conversation(dossier, claude.parent.parent) == "recente"


def test_derniere_conversation_session_explicite(claude, projet):
    _conversation(claude, "a", 1000)
    _conversation(claude, "b", 2000)
    dossier, racine = projet / ".orga" / "teams" / "x", claude.parent.parent
    assert lancer.derniere_conversation(dossier, racine, session="a") == "a"
    assert lancer.derniere_conversation(dossier, racine, session="absente") is None


def test_derniere_conversation_aucune(tmp_path):
    assert lancer.derniere_conversation(tmp_path / "x", tmp_path / "rien") is None


def test_reprise_commande(projet):
    _, _, env, ligne = lancer.commande(projet, _manif(projet), "coord", "x", None, HAIKU, "abc-123")
    assert env == {VAR_AGENT: "coord-x", VAR_PROJET: str(projet),
                   TMPDIR: str(projet / ".orga/etat/tmp")}
    assert ligne == [
        "claude", "--model", HAIKU, "--permission-mode", "auto",
        "--settings", str(reglages_mod.fichier_reglages_generes(projet, "coord-x")),
        "--resume", "abc-123"]


def test_reprise_essai_a_blanc(claude, projet, tmux, capsys):
    f = _conversation(claude, "abc-123", 1000)
    assert lancer.executer(_args_reprise(blanc=True)) == 0
    sortie = capsys.readouterr().out
    assert "--resume abc-123" in sortie and "Lis CLAUDE.md" not in sortie
    assert f"conversation : abc-123\nfichier : {f}" in sortie
    assert tmux["appels"] == []


def test_reprise_lance_avec_resume_sans_message(claude, projet, tmux, capsys):
    _conversation(claude, "abc-123", 1000)
    assert lancer.executer(_args_reprise()) == 0
    (cmd,) = tmux["appels"]
    assert cmd[:5] == ["tmux", "new-session", "-d", "-s", "essai-coord-x"]
    assert cmd[-1].endswith("--resume abc-123")
    assert capsys.readouterr().out.strip() == "essai-coord-x"


def test_reprise_session_explicite_absente(claude, projet, tmux, capsys):
    _conversation(claude, "abc-123", 1000)
    assert lancer.executer(_args_reprise(session="autre")) == 2
    assert "conversation autre introuvable dans" in capsys.readouterr().err
    assert tmux["appels"] == []


def test_reprise_session_explicite_choisie(claude, projet, tmux):
    _conversation(claude, "ancienne", 1000)
    _conversation(claude, "recente", 2000)
    assert lancer.executer(_args_reprise(session="ancienne")) == 0
    assert tmux["appels"][0][-1].endswith("--resume ancienne")


def test_reprise_aucune_conversation(claude, projet, tmux, capsys):
    assert lancer.executer(_args_reprise()) == 2
    err = capsys.readouterr().err
    assert "aucune conversation trouvée dans" in err and str(claude) in err
    assert tmux["appels"] == []


def test_reprise_session_tmux_existante(claude, projet, tmux, capsys):
    _conversation(claude, "abc-123", 1000)
    tmux["existantes"].add("essai-coord-x")
    assert lancer.executer(_args_reprise()) == 2
    assert "fermer d'abord l'ancienne session" in capsys.readouterr().err
    assert tmux["appels"] == []


def test_reprise_conversation_ouverte_ailleurs(claude, projet, tmux, monkeypatch, capsys):
    _conversation(claude, "abc-123", 1000)
    vus = []
    monkeypatch.setattr(lancer, "processus_claude_dans",
                        lambda d: vus.append(d) or [4242])
    assert lancer.executer(_args_reprise()) == 2
    err = capsys.readouterr().err
    assert "encore ouverte" in err and "4242" in err
    assert vus == [projet / ".orga" / "teams" / "x"]
    assert tmux["appels"] == []


@pytest.mark.parametrize("role,equipe", [("worker", "x")])
def test_reprise_refusee_hors_coord(claude, projet, tmux, capsys, role, equipe):
    assert lancer.executer(_args_reprise(role, equipe)) == 2
    assert "n'est accepté que pour coord" in capsys.readouterr().err
    assert tmux["appels"] == []


def test_session_sans_reprendre(claude, projet, tmux, capsys):
    assert lancer.executer(_args_reprise(session="abc", reprendre=False)) == 2
    assert "--session n'a de sens qu'avec --reprendre" in capsys.readouterr().err


def test_reprise_ecran_d_approbation_code_3(claude, projet, tmux, monkeypatch, capsys):
    _conversation(claude, "abc-123", 1000)
    touches = _tmux_avec_ecran(monkeypatch, tmux, _capture("import-trust-sousdossier"))
    assert lancer.executer(_args_reprise()) == 3
    assert touches == []


def test_processus_claude_dans_filtre_sur_le_dossier(monkeypatch, tmp_path):
    cible = tmp_path.resolve()
    sorties = {
        "ps": "  10 /opt/u/.local/bin/claude\n  11 /bin/zsh\n  12 claude\n",
        "lsof": f"p10\nn{cible}\np12\nn/ailleurs\n",
    }

    def faux(cmd, *a, **k):
        return subprocess.CompletedProcess(cmd, 0, sorties[cmd[0]], "")
    monkeypatch.setattr(lancer.subprocess, "run", faux)
    assert lancer.processus_claude_dans(tmp_path) == [10]


# --- lancer_assistant (init --lancer) ---------------------------------------------

def test_lancer_assistant_ignore_l_environnement_de_l_appelant(projet, tmux, monkeypatch, tmp_path):
    autre = tmp_path / "autre"
    (autre / ".orga").mkdir(parents=True)
    (autre / ".orga" / "projet.toml").write_text(MANIFESTE)
    monkeypatch.setenv(VAR_PROJET, str(autre))
    monkeypatch.setenv(VAR_AGENT, "worker-intrus")
    monkeypatch.chdir(autre)
    session, code = lancer.lancer_assistant(projet, HAIKU)
    assert (session, code) == ("essai-assistant", 0)
    (cmd,) = tmux["appels"]
    assert f"{VAR_PROJET}={projet}" in cmd and f"{VAR_AGENT}=assistant" in cmd
    assert not any(str(autre) in c for c in cmd)
    assert cmd[cmd.index("-c") + 1] == str(projet)
    assert HAIKU in cmd[-1] and lancer.MESSAGE_ASSISTANT in cmd[-1]


def test_lancer_assistant_ecran_de_confiance_code_3_sans_touche(
        projet, tmux, monkeypatch, capsys):
    touches = _tmux_avec_ecran(monkeypatch, tmux, _capture("import-trust-sousdossier"))
    assert lancer.lancer_assistant(projet) == ("essai-assistant", 3)
    assert "tmux attach -t essai-assistant" in capsys.readouterr().err
    assert touches == []
    assert not any(c[1] in ("kill-session", "send-keys") for c in tmux["appels"])


def test_lancer_assistant_session_existante_code_1(projet, tmux, capsys):
    tmux["existantes"].add("essai-assistant")
    assert lancer.lancer_assistant(projet)[1] == 1
    assert "déjà lancée" in capsys.readouterr().err
    assert tmux["appels"] == []


def test_lancer_assistant_projet_non_installe(tmp_path, tmux, capsys):
    assert lancer.lancer_assistant(tmp_path)[1] == 1
    assert "manifeste introuvable" in capsys.readouterr().err


def test_lancer_assistant_pose_identite_et_projet_dans_la_commande_tmux(projet, tmux):
    """`cime lancer assistant` pose CIME_AGENT=assistant et CIME_PROJET=<projet>."""
    assert lancer.executer(_args("assistant")) == 0
    (cmd,) = tmux["appels"]
    variables = {cmd[i + 1] for i, a in enumerate(cmd) if a == "-e"}
    assert f"{VAR_AGENT}=assistant" in variables
    assert f"{VAR_PROJET}={projet}" in variables


# --- attache du terminal quand un humain lance -------------------------------------

class _Flux(io.StringIO):
    def __init__(self, tty):
        super().__init__()
        self.tty = tty

    def isatty(self):
        return self.tty


@pytest.fixture
def attache(projet, tmux, monkeypatch):
    """Humain au clavier par défaut ; os.execvp et le terminal sont des enregistreurs."""
    for var in (VAR_AGENT, "CLAUDECODE", "TMUX"):
        monkeypatch.delenv(var, raising=False)
    etat = {"exec": []}
    monkeypatch.setattr(lancer.os, "execvp", lambda f, a: etat["exec"].append((f, a)))

    class _Sys:
        """`sys` vu par lancer : stdin/stdout fixés, le reste (stderr capturé) délégué."""
        def __init__(self, entree, sortie):
            self.stdin, self.stdout = _Flux(entree), _Flux(sortie)

        def __getattr__(self, nom):
            return getattr(sys, nom)

    def terminal(entree=True, sortie=True):
        monkeypatch.setattr(lancer, "sys", _Sys(entree, sortie))
    terminal()
    etat["terminal"] = terminal
    etat["tmux"] = tmux
    etat["monkeypatch"] = monkeypatch
    return etat


def _args_att(role="assistant", equipe=None, **extra):
    a = _args(role, equipe)
    a.reprendre = extra.get("reprendre", False)
    a.session = None
    a.detache = extra.get("detache", False)
    return a


def test_humain_assistant_attache_apres_la_creation(attache):
    assert lancer.executer(_args_att()) == 0
    assert attache["exec"] == [("tmux", ["tmux", "attach", "-t", "essai-assistant"])]
    assert any(c[1] == "new-session" for c in attache["tmux"]["appels"])


def test_humain_dans_tmux_bascule_le_client(attache):
    attache["monkeypatch"].setenv("TMUX", "/tmp/tmux-1/default,1,0")
    assert lancer.executer(_args_att()) == 0
    assert attache["exec"] == []
    assert ["tmux", "switch-client", "-t", "essai-assistant"] in attache["tmux"]["appels"]


def test_detache_garde_l_ancien_comportement(attache):
    assert lancer.executer(_args_att(detache=True)) == 0
    assert attache["exec"] == []


@pytest.mark.parametrize("var, valeur", [("CLAUDECODE", "1"), (VAR_AGENT, "coord-x")])
def test_agent_ne_s_attache_jamais(attache, var, valeur):
    attache["monkeypatch"].setenv(var, valeur)
    assert not lancer.humain_au_terminal()
    lancer.executer(_args_att())
    assert attache["exec"] == []


@pytest.mark.parametrize("entree, sortie", [(False, True), (True, False)])
def test_sans_terminal_ne_s_attache_pas(attache, entree, sortie):
    attache["terminal"](entree, sortie)
    assert lancer.executer(_args_att()) == 0
    assert attache["exec"] == []


def test_essai_a_blanc_ne_s_attache_pas(attache):
    a = _args_att()
    a.essai_a_blanc = True
    assert lancer.executer(a) == 0
    assert attache["exec"] == []


def test_coord_lance_par_un_humain_ne_s_attache_pas_hors_approbation(attache):
    assert lancer.executer(_args_att("coord", "x")) == 0
    assert attache["exec"] == []


def test_ecran_d_approbation_humain_attache(attache, monkeypatch):
    _tmux_avec_ecran(monkeypatch, attache["tmux"], _capture("import-trust-sousdossier"))
    assert lancer.executer(_args_att("coord", "x")) == 3
    assert attache["exec"] == [("tmux", ["tmux", "attach", "-t", "essai-coord-x"])]


def test_ecran_d_approbation_agent_message_inchange(attache, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDECODE", "1")
    attache["terminal"](False, False)
    _tmux_avec_ecran(monkeypatch, attache["tmux"], _capture("import-trust-sousdossier"))
    code = lancer._lancer(_args_att("coord", "x"), attacher=lancer.humain_au_terminal())[1]
    assert code == 3
    assert attache["exec"] == []
    assert "tmux attach -t essai-coord-x" in capsys.readouterr().err


def test_autotest_import_refuse_le_lancement_sans_rien_ecrire(projet, monkeypatch, tmux, capsys):
    # une source de cime que les lectures générées ne couvrent pas : refus, code 2
    perdu = Path.home().resolve() / "ailleurs-introuvable" / "src"
    monkeypatch.setattr(reglages_mod, "sonder_import_cime", lambda python: (perdu / "cime", [str(perdu)]))
    monkeypatch.setattr(Path, "exists", lambda self: True if self == perdu else
                        Path.is_dir(self) or Path.is_file(self))
    assert lancer.executer(_args("worker", "x", "y", HAIKU)) == lancer.CODE_REFUS
    assert "n'est pas couverte par les lectures de l'agent" in capsys.readouterr().err
    assert (projet / ".orga/teams/x/tasks/todo/y.md").is_file()
    assert not reglages_mod.fichier_reglages_generes(projet, "worker-x-y").exists()
    assert tmux["appels"] == []


def test_essai_a_blanc_imprime_le_verdict_statique_sans_rien_lancer(projet, monkeypatch, tmux, capsys):
    # le sys.path de ce processus de test (venv du dépôt) n'est pas celui d'un outil installé
    monkeypatch.setattr(lancer.sys, "path", [str(Path(reglages_mod._paquet_cime()).parent)])
    assert lancer.executer(_args("worker", "x", "y", HAIKU, blanc=True)) == 0
    sortie = capsys.readouterr().out
    assert "autotest import cime (statique) : ok" in sortie
    assert tmux["appels"] == []
    assert not reglages_mod.fichier_reglages_generes(projet, "worker-x-y").exists()


# --- reprise d'une tâche orpheline ------------------------------------------------------------

def _evenements_reprise(projet):
    from cime.fondation.registre import ouvrir
    conn = ouvrir(projet)
    try:
        return conn.execute("SELECT agent, details FROM evenements WHERE evenement = 'TacheReprise'"
                            ).fetchall()
    finally:
        conn.close()


@pytest.fixture
def orpheline(projet, tmux, monkeypatch):
    """Fiche en `in-progress/`, ni session tmux ni processus claude (sonde simulée)."""
    taches = projet / ".orga/teams/x/tasks"
    (taches / "in-progress").mkdir(exist_ok=True)
    (taches / "todo" / "y.md").rename(taches / "in-progress" / "y.md")
    sondes = []
    monkeypatch.setattr(lancer, "processus_claude_dans", lambda d: sondes.append(d) or [])
    return {"fiche": taches / "in-progress" / "y.md", "todo": taches / "todo" / "y.md",
            "sondes": sondes}


def test_reprise_orpheline_ne_deplace_pas_la_fiche(orpheline, projet, tmux, capsys):
    assert lancer.executer(_args("worker", "x", "y", HAIKU)) == 0
    assert capsys.readouterr().out.strip() == "essai-worker-x-y"
    assert orpheline["fiche"].read_text() == "tâche" and not orpheline["todo"].exists()
    (cmd,) = tmux["appels"]
    assert cmd[:8] == ["tmux", "new-session", "-d", "-s", "essai-worker-x-y",
                       "-c", str(projet / ".orga/worktrees/x"), "-e"]
    ligne = shlex.split(cmd[-1])
    assert ligne[-1] == f"Lis {orpheline['fiche']} et exécute-le."
    (evenement,) = _evenements_reprise(projet)
    assert evenement[0] is None
    assert json.loads(evenement[1]) == {"auteur": "utilisateur", "equipe": "x", "tache": "y"}
    assert orpheline["sondes"] == [projet / ".orga/worktrees/x"]


def test_reprise_orpheline_avec_session_vivante_refus_inchange(orpheline, projet, tmux, capsys):
    tmux["existantes"].add("essai-worker-x-y")
    assert lancer.executer(_args("worker", "x", "y", HAIKU)) == 1
    assert "tâche absente" in capsys.readouterr().err
    assert tmux["appels"] == [] and _evenements_reprise(projet) == []
    assert orpheline["fiche"].is_file()


def test_reprise_orpheline_avec_processus_claude_refus_inchange(orpheline, projet, tmux,
                                                                 monkeypatch, capsys):
    monkeypatch.setattr(lancer, "processus_claude_dans", lambda d: [4242])
    assert lancer.executer(_args("worker", "x", "y", HAIKU)) == 1
    assert "tâche absente" in capsys.readouterr().err
    assert tmux["appels"] == [] and _evenements_reprise(projet) == []
    assert orpheline["fiche"].is_file()


def test_fiche_en_todo_et_en_cours_refus_inchange(orpheline, projet, tmux, capsys):
    orpheline["todo"].write_text("double")
    assert lancer.executer(_args("worker", "x", "y", HAIKU)) == 1
    assert "tâche déjà en cours" in capsys.readouterr().err
    assert tmux["appels"] == [] and _evenements_reprise(projet) == []
    assert orpheline["todo"].read_text() == "double" and orpheline["fiche"].read_text() == "tâche"


def test_reprise_orpheline_refusee_si_projet_ferme(orpheline, projet, tmux, capsys):
    (projet / ".orga/etat").mkdir(parents=True, exist_ok=True)
    (projet / ".orga/etat/ferme.json").write_text("{}")
    assert lancer.executer(_args("worker", "x", "y", HAIKU)) == 2
    assert "projet fermé : rouvrir d'abord" in capsys.readouterr().err
    assert tmux["appels"] == [] and _evenements_reprise(projet) == []
    assert orpheline["fiche"].read_text() == "tâche" and not orpheline["todo"].exists()


def test_lancement_normal_projet_ferme_garde_son_comportement(projet, tmux, capsys):
    (projet / ".orga/etat").mkdir(parents=True, exist_ok=True)
    (projet / ".orga/etat/ferme.json").write_text("{}")
    assert lancer.executer(_args("worker", "x", "y", HAIKU)) == 0
    assert _evenements_reprise(projet) == []


def test_aucune_fiche_nulle_part_tache_absente(projet, tmux, capsys):
    (projet / ".orga/teams/x/tasks/in-progress").mkdir()
    assert lancer.executer(_args("worker", "x", "rien", HAIKU)) == 1
    assert "tâche absente" in capsys.readouterr().err
    assert tmux["appels"] == [] and _evenements_reprise(projet) == []


def test_lancement_normal_n_ecrit_pas_de_reprise(projet, tmux, capsys):
    assert lancer.executer(_args("worker", "x", "y", HAIKU)) == 0
    assert _evenements_reprise(projet) == []
    assert (projet / ".orga/teams/x/tasks/in-progress/y.md").is_file()
    assert not (projet / ".orga/teams/x/tasks/todo/y.md").exists()


def test_reprise_orpheline_laisse_le_travail_du_worktree(orpheline, projet, tmux, capsys):
    arbre = projet / ".orga/worktrees/x"
    (arbre / "fait.txt").write_text("commité")
    _git(arbre, "add", "fait.txt")
    _git(arbre, "commit", "-qm", "travail fait")
    (arbre / "en_cours.txt").write_text("pas commité")
    avant = subprocess.run(["git", "-C", str(arbre), "rev-parse", "HEAD"],
                           capture_output=True, text=True).stdout
    assert lancer.executer(_args("worker", "x", "y", HAIKU)) == 0
    assert (arbre / "en_cours.txt").read_text() == "pas commité"
    assert (arbre / "fait.txt").read_text() == "commité"
    assert subprocess.run(["git", "-C", str(arbre), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout == avant
    status = subprocess.run(["git", "-C", str(arbre), "status", "--porcelain"],
                            capture_output=True, text=True).stdout
    assert "en_cours.txt" in status
