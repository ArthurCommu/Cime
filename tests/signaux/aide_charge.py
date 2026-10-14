"""Aides des tests du compte de workers : la sonde tmux simulée et le battement du facteur."""
import json

import pytest

from aide import fabriquer_projet
from aide_machine import fixer_machine
from cime.fondation import plafond
from cime.fondation.registre import ouvrir
from cime.signaux import ordres

WORKER = {"role": "worker", "equipe": "x", "modele": "m"}


@pytest.fixture
def projet(tmp_path, monkeypatch):
    racine = fabriquer_projet(tmp_path / "depot")
    monkeypatch.setenv("CIME_PROJET", str(racine))
    monkeypatch.setenv("CIME_ATTENTE_ORDRE", "0")
    fixer_machine(plafond.dossier_reglages(), 1)      # un seul worker à la fois sur cette machine
    return racine


@pytest.fixture
def tmux(monkeypatch):
    """La sonde tmux : un ensemble de sessions, ou None quand tmux est muet (bac à sable)."""
    etat = {"sessions": set()}
    monkeypatch.setattr(ordres, "_sessions_vivantes", lambda: etat["sessions"])
    return etat


def muet(tmux):
    tmux["sessions"] = None


def fichier_charge(projet):
    return ordres.chemin_charge(projet)


def compte_inscrit(projet):
    return json.loads(fichier_charge(projet).read_text())["workers_actifs"]


def battement_vieux(projet):
    conn = ouvrir(projet)
    try:
        with conn:
            conn.execute("INSERT OR REPLACE INTO facteur (id, battement, version) "
                         "VALUES (1, '2020-01-01T00:00:00.000Z', 'banc')")
    finally:
        conn.close()


def poser_worker(projet):
    return ordres.demander(projet, "coord-x", "lancer", "worker-x-a",
                           {**WORKER, "tache": "a"})


def sortie_de_issue(projet, capsys, verbe="lancer"):
    identifiant = poser_worker(projet)
    code = ordres._issue(identifiant, None, projet)
    return identifiant, code, capsys.readouterr().out.strip()


