"""Fixtures communes : registre de projet vide, session tmux d'essai isolée, garde-fou sur le vrai projet."""
import os
import sqlite3
from contextlib import closing
from functools import cache
from pathlib import Path

import subprocess

import pytest

# Toute session tmux d'essai vit sur une socket DANS le worktree (et non dans /private/tmp,
# que le bac à sable de Claude Code refuse) : jamais sur le serveur par défaut.
RACINE = Path(__file__).resolve().parents[2]
DOSSIER_ESSAI = RACINE / ".essai-tmux"
DOSSIER_ESSAI.mkdir(exist_ok=True)
# `*` dans son propre .gitignore : git ignore le dossier sans toucher au .gitignore racine
if not (DOSSIER_ESSAI / ".gitignore").exists():
    (DOSSIER_ESSAI / ".gitignore").write_text("*\n")
SOCKET_ESSAI = str(DOSSIER_ESSAI / "hote.sock")
assert len(SOCKET_ESSAI) <= 100, f"socket d'essai trop longue : {SOCKET_ESSAI}"


def tmux_essai(*args, socket=SOCKET_ESSAI):
    """Lance `tmux -S <socket du worktree> <args>` ; ne jamais y mettre `kill-server`.

    `socket` n'est changé que par le test de ce helper (jamais par `import conftest` : sur la
    suite complète, ce nom désigne le conftest d'un autre dossier de tests).

    Un `new-session` en échec lève tout de suite : tmux peut rendre 0 en signalant
    l'erreur sur stderr, et le test passerait alors à vide.
    """
    r = subprocess.run(["tmux", "-S", socket, *args], capture_output=True, text=True)
    if args and args[0] == "new-session":
        erreurs = ("error creating", "error connecting", "Operation not permitted")
        if r.returncode != 0 or any(e in r.stderr for e in erreurs):
            raise AssertionError(f"new-session en échec (code {r.returncode}) : {r.stderr!r}")
    return r


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "tmux_reel: crée de vraies sessions tmux (sautés sous le bac à sable de Claude Code, exigés ailleurs)",
    )


SONDE = "sonde-detection"
ERREURS_TMUX = ("error creating", "error connecting", "Operation not permitted", "failed")


def sous_bac_a_sable():
    """Vrai sous le bac à sable de Claude Code, qui pose `SANDBOX_RUNTIME=1`.

    Variable constatée dans l'environnement d'une session sous le bac à sable.
    """
    return os.environ.get("SANDBOX_RUNTIME") == "1"


def _raison(r, commande):
    return r.stderr.strip()[:200] or f"{commande} : code de sortie {r.returncode}"


def _sonder():
    try:
        r = subprocess.run(
            ["tmux", "-S", SOCKET_ESSAI, "new-session", "-d", "-s", SONDE, "sleep 5"],
            capture_output=True, text=True,
        )
        if r.returncode != 0 or any(e in r.stderr for e in ERREURS_TMUX):
            return False, _raison(r, "new-session")
        vu = subprocess.run(
            ["tmux", "-S", SOCKET_ESSAI, "has-session", "-t", SONDE], capture_output=True, text=True,
        )
        if vu.returncode != 0:
            return False, _raison(vu, "has-session")
        return True, ""
    finally:
        # toujours tuée, jamais de `kill-server`
        subprocess.run(
            ["tmux", "-S", SOCKET_ESSAI, "kill-session", "-t", SONDE], capture_output=True, text=True,
        )


@cache
def creation_tmux_possible():
    """Une seule détection par processus pytest : peut-on créer une session sur la socket d'essai ?

    Renvoie `(ok, raison)` ; la raison est vide si ok, sinon non vide. Ne lève pas.
    """
    try:
        return _sonder()
    except OSError as e:
        return False, f"tmux inutilisable : {e}"


def decision_tmux_reel(creation_ok: bool, sous_bac_a_sable: bool) -> str:
    if creation_ok:
        return "lancer"
    return "sauter" if sous_bac_a_sable else "echouer"


def pytest_runtest_setup(item):
    if item.get_closest_marker("tmux_reel") is None:
        return
    ok, raison = creation_tmux_possible()
    decision = decision_tmux_reel(ok, sous_bac_a_sable())
    if decision == "sauter":
        pytest.skip(f"tmux_reel : {raison}; bac à sable de Claude Code")
    if decision == "echouer":
        pytest.fail(f"tmux_reel : impossible de créer une session tmux hors bac à sable : {raison}")


SCHEMA = """
CREATE TABLE messages(id INTEGER PRIMARY KEY, horodatage TEXT, de TEXT, a TEXT, nature TEXT,
    resume TEXT, fichier TEXT, en_reponse_a INTEGER, equipe TEXT);
CREATE TABLE evenements(id INTEGER PRIMARY KEY, horodatage TEXT, agent TEXT, session_id TEXT,
    evenement TEXT, details TEXT);
CREATE TABLE journal(id INTEGER PRIMARY KEY, horodatage TEXT NOT NULL, auteur TEXT NOT NULL,
    action TEXT NOT NULL, cible TEXT, details TEXT, resultat TEXT NOT NULL);
"""


@pytest.fixture
def registre_vide(tmp_path):
    """Crée le registre comme le ferait `cime init` ; renvoie la racine du projet."""
    d = tmp_path / ".orga" / "etat"
    d.mkdir(parents=True)
    with closing(sqlite3.connect(d / "registre.sqlite")) as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript(SCHEMA)
    return tmp_path


@pytest.fixture(autouse=True)
def projet_et_agent_isoles(tmp_path_factory, monkeypatch):
    """Garde-fou : aucun test n'écrit dans le vrai projet ni n'hérite de l'identité d'un worker."""
    monkeypatch.setenv("CIME_PROJET", str(tmp_path_factory.mktemp("cime-projet")))
    monkeypatch.delenv("CIME_AGENT", raising=False)


def test_cime_projet_n_est_pas_le_vrai_projet():
    import os
    from pathlib import Path

    # le vrai projet, sans littéral : ce dépôt, et le dépôt principal quand on est dans un worktree
    depot = Path(__file__).resolve().parents[2]
    reels = {depot} | ({depot.parents[2]} if depot.parent.name == "worktrees" else set())
    projet = Path(os.environ["CIME_PROJET"]).resolve()
    assert not any(projet == r or r in projet.parents for r in reels)
    assert "CIME_AGENT" not in os.environ


def test_isolement_serveur_par_defaut():
    """Une session d'essai créée par l'aide commune n'apparaît pas sur le serveur par défaut."""
    import shutil
    import uuid

    if not shutil.which("tmux"):
        pytest.skip("tmux absent")

    def defaut():
        r = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"], capture_output=True, text=True
        )
        return set(r.stdout.split()) if r.returncode == 0 else set()  # pas de serveur : vide

    nom = f"cc-essai-{uuid.uuid4().hex[:6]}-iso"
    avant = defaut()
    try:
        assert tmux_essai("new-session", "-d", "-s", nom, "sleep 30").returncode == 0
        assert nom in tmux_essai("list-sessions", "-F", "#{session_name}").stdout.split()
        apres = defaut()
        assert nom not in apres
        assert not {s for s in apres - avant if s.startswith("cc-essai-")}
    finally:
        tmux_essai("kill-session", "-t", nom)
