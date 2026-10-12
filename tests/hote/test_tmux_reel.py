"""Aide commune aux essais tmux réels : détection de la socket d'essai, sans tmux lancé pour de vrai."""
import subprocess

import pytest
from conftest import SOCKET_ESSAI, creation_tmux_possible, decision_tmux_reel, sous_bac_a_sable


@pytest.fixture(autouse=True)
def detection_vide():
    """Un faux `subprocess.run` ne doit ni hériter ni laisser une détection en cache."""
    creation_tmux_possible.cache_clear()
    yield
    creation_tmux_possible.cache_clear()


def installer_tmux(monkeypatch, reponses=None, exception=None):
    """Remplace `subprocess.run` : chaque sous-commande tmux reçoit `(code, stderr)` ; défaut : succès."""
    reponses = reponses or {}
    appels = []

    def faux_run(args, **kwargs):
        appels.append(list(args))
        if exception is not None:
            raise exception
        code, stderr = reponses.get(args[3], (0, ""))  # args : tmux -S <socket> <commande>
        return subprocess.CompletedProcess(args, code, "", stderr)

    monkeypatch.setattr(subprocess, "run", faux_run)
    return appels


@pytest.mark.parametrize(
    "creation_ok,sandbox,attendu",
    [
        (True, True, "lancer"),
        (True, False, "lancer"),
        (False, True, "sauter"),
        (False, False, "echouer"),
    ],
)
def test_decision_quatre_combinaisons(creation_ok, sandbox, attendu):
    assert decision_tmux_reel(creation_ok, sandbox) == attendu


def test_sous_bac_a_sable_lit_sandbox_runtime(monkeypatch):
    monkeypatch.setenv("SANDBOX_RUNTIME", "1")
    assert sous_bac_a_sable() is True
    monkeypatch.setenv("SANDBOX_RUNTIME", "0")
    assert sous_bac_a_sable() is False
    monkeypatch.delenv("SANDBOX_RUNTIME")
    assert sous_bac_a_sable() is False


def test_detection_mise_en_cache_une_seule_tentative(monkeypatch):
    appels = installer_tmux(monkeypatch)
    premier = creation_tmux_possible()
    nombre = len(appels)
    assert nombre > 0
    assert creation_tmux_possible() == premier
    assert len(appels) == nombre  # le second appel ne relance aucun tmux
    assert premier == (True, "")


@pytest.mark.parametrize(
    "reponse,fragment",
    [
        ((1, "error creating /x: Operation not permitted"), "Operation not permitted"),
        ((0, "create window failed: fork failed: Operation not permitted"), "Operation not permitted"),
        ((1, ""), "new-session"),  # stderr vide : la raison reste non vide
    ],
    ids=["socket-refusee", "fork-refuse-code-0", "stderr-vide"],
)
def test_echec_creation_donne_raison_non_vide(monkeypatch, reponse, fragment):
    installer_tmux(monkeypatch, {"new-session": reponse})
    ok, raison = creation_tmux_possible()
    assert ok is False
    assert raison.strip()
    assert fragment in raison


def test_has_session_en_echec_donne_non_ok(monkeypatch):
    installer_tmux(monkeypatch, {"has-session": (1, "can't find session: sonde-detection")})
    ok, raison = creation_tmux_possible()
    assert ok is False
    assert "can't find session" in raison


@pytest.mark.parametrize(
    "reponses",
    [
        {"new-session": (1, "error creating /x: Operation not permitted")},
        {"has-session": (1, "can't find session")},
    ],
    ids=["new-session-en-echec", "has-session-en-echec"],
)
def test_sonde_toujours_tuee_sans_kill_server(monkeypatch, reponses):
    appels = installer_tmux(monkeypatch, reponses)
    creation_tmux_possible()
    commandes = [a[3:] for a in appels]
    assert ["kill-session", "-t", "sonde-detection"] in commandes
    assert all("kill-server" not in a for a in commandes)
    assert all(a[1:3] == ["-S", SOCKET_ESSAI] for a in appels)


def test_tmux_absent_ne_leve_pas(monkeypatch):
    installer_tmux(monkeypatch, exception=FileNotFoundError("tmux"))
    ok, raison = creation_tmux_possible()
    assert ok is False
    assert raison.strip()
