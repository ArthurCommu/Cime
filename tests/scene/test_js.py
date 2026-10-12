"""Enveloppe pytest de la suite JavaScript de la scène : `node --test tests/scene/js/`.

Pas de navigateur : tout se teste sous node avec la surface PNG. Sans node, le test est sauté.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]


def test_suite_js_de_la_scene():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent : la suite JavaScript de la scène ne tourne pas")
    resultat = subprocess.run(
        [node, "--test", "tests/scene/js/"],
        cwd=RACINE,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert resultat.returncode == 0, resultat.stdout[-4000:] + resultat.stderr[-2000:]
