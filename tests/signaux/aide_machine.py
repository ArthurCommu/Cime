"""Aides des tests du plafond de la machine : le fichier de réglages et son journal."""
import json
import os
from pathlib import Path

import pytest

from cime.fondation import plafond


@pytest.fixture
def dossier_machine():
    """Le dossier `cime/` des réglages de la machine, sous le dossier de config du test."""
    return Path(os.environ["XDG_CONFIG_HOME"]) / "cime"


def poser_reglages(dossier, texte):
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "reglages.toml").write_text(texte, encoding="utf-8")


def fixer_machine(dossier, n):
    poser_reglages(dossier, f"workers_max = {n}\n")


def lire_journal(dossier):
    chemin = dossier / "reglages.journal"
    if not chemin.exists():
        return []
    return [json.loads(ligne) for ligne in chemin.read_text().splitlines()]


def poser_manifeste(projet, n):
    fichier = projet / ".orga" / "projet.toml"
    fichier.write_text(fichier.read_text() + f"\n[charge]\nworkers_max = {n}\n")


@pytest.fixture
def projet_libre(tmp_path, monkeypatch):
    """Un projet sans plafond de projet et sans fichier de réglages : le défaut de la machine s'applique."""
    from aide import fabriquer_projet
    racine = fabriquer_projet(tmp_path / "depot")
    monkeypatch.setenv("CIME_PROJET", str(racine))
    monkeypatch.setenv("CIME_ATTENTE_ORDRE", "0")
    return racine
