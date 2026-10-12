import argparse
import io
import json
import subprocess
import sys
import textwrap

import pytest

from cime.fondation import envoyer, hook
from cime.fondation.nom import VAR_AGENT, VAR_PROJET
from cime.fondation.registre import inscrire_message, ouvrir

MANIFESTE = textwrap.dedent("""\
    nom = "Essai"
    prefixe = "essai"
    branche_reference = "main"
    branche_equipe = "equipe/{equipe}"
    worktree_equipe = "../{depot}-{equipe}"
    equipes_speciales = ["assistant"]
    modele_assistant = "m"
    modele_coordinateur = "m"
""")
WORKER = "worker-mon-equipe-tache"
RAPPORT = ".orga/teams/mon-equipe/reports/worker-mon-equipe-tache-2026-10-08.md"


@pytest.fixture
def projet(tmp_path, monkeypatch):
    racine = (tmp_path / "depot").resolve()
    (racine / ".orga" / "teams" / "mon-equipe" / "reports").mkdir(parents=True)
    (racine / ".orga" / "teams" / "mon-equipe" / "conversations").mkdir()
    (racine / ".orga" / "projet.toml").write_text(MANIFESTE)
    monkeypatch.setenv(VAR_PROJET, str(racine))
    monkeypatch.setenv(VAR_AGENT, WORKER)
    monkeypatch.delenv("TMUX", raising=False)
    return racine


@pytest.fixture
def tmux(monkeypatch):
    etat = {"existantes": {"essai-coord-mon-equipe"}, "appels": []}

    def faux_tmux(*args):
        etat["appels"].append(args)
        code = 0
        if args[0] == "has-session":
            code = 0 if args[2].lstrip("=") in etat["existantes"] else 1
        return subprocess.CompletedProcess(args, code, "", "")

    monkeypatch.setattr(envoyer, "_tmux", faux_tmux)
    return etat


def stop(monkeypatch, agent=WORKER, dernier="Terminé."):
    monkeypatch.setenv(VAR_AGENT, agent)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"last_assistant_message": dernier})))
    assert hook.executer(argparse.Namespace(evenement="Stop")) == 0


def lignes_tapees(tmux):
    return [a[-1] for a in tmux["appels"] if a[0] == "send-keys" and "-l" in a]


def messages(projet):
    conn = ouvrir(projet)
    try:
        return conn.execute("SELECT de, a, nature, resume, fichier, equipe FROM messages"
                            " ORDER BY id").fetchall()
    finally:
        conn.close()


def erreurs(projet):
    f = projet / ".orga" / "etat" / "signal-erreurs.log"
    return f.read_text().splitlines() if f.exists() else []


# Registre 2.0 : le hook `Stop` ne lit plus `reports/`, `pour-assistant-*` ni le « ? » final,
# et ne tape plus jamais dans tmux. Ces anciens déclencheurs sont devenus sans effet (la
# logique de remplacement est testée dans tests/signaux/test_hooks.py).

def test_rapport_dans_reports_ne_signale_plus_rien(projet, tmux, monkeypatch):
    (projet / RAPPORT).write_text("# rapport")
    stop(monkeypatch)
    stop(monkeypatch)
    assert messages(projet) == []
    assert tmux["appels"] == []
    assert erreurs(projet) == []


def test_dix_stop_ordinaires_ne_font_rien(projet, tmux, monkeypatch):
    for _ in range(10):
        stop(monkeypatch, dernier="J'ai avancé.  \n")
    assert tmux["appels"] == []
    assert messages(projet) == []
    assert erreurs(projet) == []


def test_question_finale_n_est_plus_lue(projet, tmux, monkeypatch):
    stop(monkeypatch, dernier="Je fais A ou B ?  \n")
    assert tmux["appels"] == [] and messages(projet) == []


def pour_assistant(projet, h="2026-10-08T10-00", texte="\n# Faut-il couper ?\nDétail"):
    dossier = projet / ".orga" / "teams" / "mon-equipe" / "conversations"
    (dossier / f"pour-assistant-{h}.md").write_text(texte)


def test_pour_assistant_n_est_plus_lu(projet, tmux, monkeypatch):
    pour_assistant(projet)
    stop(monkeypatch, agent="coord-mon-equipe")
    assert messages(projet) == [] and tmux["appels"] == []


def test_stop_sans_agent_ne_fait_rien(projet, tmux, monkeypatch):
    monkeypatch.delenv(VAR_AGENT, raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    assert hook.executer(argparse.Namespace(evenement="Stop")) == 0
    assert messages(projet) == []
