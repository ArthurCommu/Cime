"""Vérifie que chaque fixture de hook porte les champs communs et un nom conforme à son événement."""

import json
from pathlib import Path

import pytest

DOSSIER = Path(__file__).parent / "fixtures" / "hooks"
FICHIERS = sorted(DOSSIER.glob("*.json"))
CHAMPS = ["session_id", "transcript_path", "cwd", "hook_event_name"]


def test_fixtures_presentes():
    assert len(FICHIERS) >= 16


@pytest.mark.parametrize("fichier", FICHIERS, ids=lambda f: f.stem)
def test_champs_communs(fichier):
    d = json.loads(fichier.read_text(encoding="utf-8"))
    for champ in CHAMPS:
        assert champ in d, champ
    assert fichier.stem.startswith(d["hook_event_name"])
