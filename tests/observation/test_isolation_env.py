"""Vérifie que la suite tourne sur un projet jetable et sans identité d'agent."""

import os
import tempfile
from pathlib import Path


def test_environnement_reel_isole():
    projet = Path(os.environ["CIME_PROJET"]).resolve()
    assert projet.is_relative_to(Path(tempfile.gettempdir()).resolve())
    assert "CIME_AGENT" not in os.environ
