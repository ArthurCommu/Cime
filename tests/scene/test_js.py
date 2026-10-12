"""Enveloppe pytest de la suite JavaScript de la scène : `node --test tests/scene/js/*.test.mjs`.

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
        # Les fichiers sont nommés un à un : un dossier passé à `node --test` n'est accepté
        # qu'à partir de Node 23.
        [node, "--test", *sorted(str(f.relative_to(RACINE)) for f in (RACINE / "tests/scene/js").glob("*.test.mjs"))],
        cwd=RACINE,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert resultat.returncode == 0, resultat.stdout[-4000:] + resultat.stderr[-2000:]
