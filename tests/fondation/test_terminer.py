import argparse
import subprocess
import textwrap

import pytest

from cime.fondation import terminer
from cime.fondation.nom import VAR_AGENT, VAR_PROJET
from cime.fondation.registre import inscrire_message, ouvrir
from cime.signaux import ordres

MANIFESTE = textwrap.dedent("""\
    nom = "Essai"
    prefixe = "essai"
    branche_reference = "main"
    branche_equipe = "equipe/{equipe}"
    worktree_equipe = "../{depot}-{equipe}"
    equipes_speciales = ["assistant"]
    modele_assistant = "modele-assistant"
    modele_coordinateur = "modele-coord"
""")


@pytest.fixture
def projet(tmp_path, monkeypatch):
    racine = (tmp_path / "depot").resolve()
    equipe = racine / ".orga" / "teams" / "x"
    (equipe / "tasks" / "in-progress").mkdir(parents=True)
    (equipe / "tasks" / "in-progress" / "y.md").write_text("tâche")
    (equipe / "reports").mkdir()
    (racine / ".orga" / "projet.toml").write_text(MANIFESTE)
    monkeypatch.setenv(VAR_PROJET, str(racine))
    monkeypatch.setenv(VAR_AGENT, "coord-x")
    # préconditions d'un agent : travail_pret du worker, synthèse de sa conversation
    (equipe / "conversations").mkdir()
    (equipe / "conversations" / "y-2026-10-08.md").write_text("synthèse")
    conn = ouvrir(racine)
    inscrire_message(conn, de="worker-x-y", a="coord-x", nature="travail_pret",
                     resume="prêt", equipe="x")
    conn.close()
    # un facteur simulé : pendant que la commande attend son ordre, il l'exécute
    monkeypatch.setattr(ordres, "_dormir", lambda s: ordres.facteur_une_fois(racine))
    return racine


@pytest.fixture
def tmux(monkeypatch):
    etat = {"existantes": {"essai-worker-x-y", "essai-worker-x-z"}, "appels": []}

    def faux_tmux(*args):
        etat["appels"].append(args)
        code = 0
        if args[0] == "has-session":
            code = 0 if args[2].lstrip("=") in etat["existantes"] else 1
        return subprocess.CompletedProcess(args, code, "", "")

    monkeypatch.setattr(terminer, "_tmux", faux_tmux)
    return etat


def _rapport(projet, nom="worker-x-y-2026-10-08.md"):
    (projet / ".orga" / "teams" / "x" / "reports" / nom).write_text("rapport")


def _args():
    return argparse.Namespace(role="worker", equipe="x", tache="y")


def _resumes(projet):
    conn = ouvrir(projet)
    try:
        return [r[0] for r in conn.execute(
            "SELECT resume FROM messages WHERE nature = 'consigne' ORDER BY id")]
    finally:
        conn.close()


def _tue(etat):
    return [a for a in etat["appels"] if a[0] == "kill-session"]


def test_termine_ferme_deplace_journalise(projet, tmux, capsys):
    _rapport(projet)
    assert terminer.executer(_args()) == 0
    assert _tue(tmux) == [("kill-session", "-t", "=essai-worker-x-y")]
    equipe = projet / ".orga" / "teams" / "x" / "tasks"
    assert (equipe / "done" / "y.md").read_text() == "tâche"
    assert not (equipe / "in-progress" / "y.md").exists()
    conn = ouvrir(projet)
    lignes = conn.execute("SELECT de, a, nature, resume, fichier FROM messages"
                          " WHERE nature = 'consigne'").fetchall()
    conn.close()
    assert lignes == [("coord-x", "worker-x-y", "consigne",
                       "fin de tâche y — rapport accepté, session fermée",
                       ".orga/teams/x/reports/worker-x-y-2026-10-08.md")]


def test_refus_sans_rapport(projet, tmux, capsys):
    _rapport(projet, "worker-x-autre-2026-10-08.md")
    assert terminer.executer(_args()) == 2
    assert _tue(tmux) == []
    assert (projet / ".orga/teams/x/tasks/in-progress/y.md").exists()
    assert "reports/worker-x-y-*.md" in capsys.readouterr().err
    assert _resumes(projet)[0].startswith("fin de tâche y — refusé : aucun rapport")


def test_refus_tache_absente(projet, tmux):
    _rapport(projet)
    (projet / ".orga/teams/x/tasks/in-progress/y.md").unlink()
    assert terminer.executer(_args()) == 2 and _tue(tmux) == []
    assert _resumes(projet)[0].startswith("fin de tâche y — refusé : tâche introuvable")


def test_refus_sans_identite(projet, tmux, monkeypatch):
    _rapport(projet)
    monkeypatch.delenv(VAR_AGENT)
    monkeypatch.setenv("CLAUDECODE", "1")
    assert terminer.executer(_args()) == 2 and _tue(tmux) == []


def test_refus_sans_projet(projet, tmux, monkeypatch):
    monkeypatch.delenv(VAR_PROJET)
    assert terminer.executer(_args()) == 2 and _tue(tmux) == []


def test_refus_cible_done_existante(projet, tmux):
    _rapport(projet)
    done = projet / ".orga/teams/x/tasks/done"
    done.mkdir()
    (done / "y.md").write_text("ancien")
    assert terminer.executer(_args()) == 2
    assert _tue(tmux) == [] and (done / "y.md").read_text() == "ancien"
    assert _resumes(projet)[0].startswith("fin de tâche y — refusé : la cible existe déjà")


def test_session_absente_on_continue(projet, tmux, capsys):
    _rapport(projet)
    tmux["existantes"].clear()
    assert terminer.executer(_args()) == 0
    assert _tue(tmux) == []
    assert "absente" in capsys.readouterr().out
    assert (projet / ".orga/teams/x/tasks/done/y.md").exists()


def test_refus_pas_de_session_dans_le_manifeste(projet, tmux, monkeypatch):
    _rapport(projet)
    monkeypatch.setattr(terminer, "session_tmux", lambda manifeste, identite: None)
    assert terminer.executer(_args()) == 2 and _tue(tmux) == []
    assert _resumes(projet)[0].startswith("fin de tâche y — refusé : pas de session")


def test_echec_fermeture_journalise(projet, tmux, monkeypatch):
    _rapport(projet)
    monkeypatch.setattr(terminer, "_tmux", lambda *a: subprocess.CompletedProcess(
        a, 0 if a[0] == "has-session" else 1, "", "boom"))
    assert terminer.executer(_args()) == 1
    assert (projet / ".orga/teams/x/tasks/in-progress/y.md").exists()
    assert _resumes(projet)[0].startswith("fin de tâche y — échec : fermeture de la session essai-worker-x-y impossible")


@pytest.mark.parametrize("appelant", ["coord-y", "assistant", "worker-x-u"])
def test_refus_si_pas_le_coordinateur_de_l_equipe(projet, tmux, monkeypatch, appelant):
    _rapport(projet)
    monkeypatch.setenv(VAR_AGENT, appelant)
    assert terminer.executer(_args()) == 2
    assert _tue(tmux) == []
    assert (projet / ".orga/teams/x/tasks/in-progress/y.md").exists()
    assert _resumes(projet) == ["fin de tâche y — refusé : pas le supérieur direct"]
    conn = ouvrir(projet)
    assert conn.execute("SELECT de FROM messages WHERE nature = 'consigne'").fetchall() == [(appelant,)]
    conn.close()
