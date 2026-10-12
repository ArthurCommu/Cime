"""Les outils de la page en navigateur : tests/page/outils/nav.sh, lancer_scenario.py, capturer_faux_hote.py.

Rien ici ne lance de navigateur. nav.sh est exécuté avec un faux `uv` sur le PATH, qui affiche ses arguments et son environnement ;
la garde du lanceur est extraite de son source (AST) et exécutée sur de faux objets `route`, sans playwright.
"""

import ast
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

OUTILS = Path(__file__).resolve().parent / "outils"
NAV = OUTILS / "nav.sh"
LANCEUR = OUTILS / "lancer_scenario.py"
CAPTURES = OUTILS / "capturer_faux_hote.py"


def lancer_nav(tmp_path, env_extra=None):
    faux = tmp_path / "uv"
    faux.write_text('#!/bin/sh\necho "BROWSERS=$PLAYWRIGHT_BROWSERS_PATH"\necho "ARGS=$*"\n')
    faux.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k not in ("PLAYWRIGHT_BROWSERS_PATH", "NAV_HORS_LIGNE")}
    env["PATH"] = f"{tmp_path}{os.pathsep}{env['PATH']}"
    env.update(env_extra or {})
    res = subprocess.run(["sh", str(NAV), "sonde.py"], cwd=tmp_path, env=env, capture_output=True, text=True, check=True)
    return dict(ligne.split("=", 1) for ligne in res.stdout.splitlines())


def fonctions_du_lanceur(*noms):
    """Les fonctions nommées de lancer_scenario.py, exécutées dans un espace où FAUX_HOTE et PORT_TEST sont fixés."""
    arbre = ast.parse(LANCEUR.read_text())
    noeuds = [n for n in arbre.body if isinstance(n, ast.FunctionDef) and n.name in noms]
    espace = {"FAUX_HOTE": True, "PORT_TEST": "8796", "urlsplit": urlsplit, "sys": sys}
    exec(compile(ast.Module(body=noeuds, type_ignores=[]), str(LANCEUR), "exec"), espace)
    return espace


class FauxRoute:
    def __init__(self, methode, url):
        self.request = SimpleNamespace(method=methode, url=url)
        self.fait = None

    def fallback(self):
        self.fait = "laissée passer"

    def abort(self):
        self.fait = "bloquée"


def test_nav_lance_le_script_avec_playwright_depuis_n_importe_quel_dossier(tmp_path):
    sortie = lancer_nav(tmp_path)
    assert sortie["ARGS"] == "run --no-project --with playwright --with pillow python sonde.py"
    assert sortie["BROWSERS"] == ""


def test_nav_travaille_hors_ligne_sur_demande(tmp_path):
    sortie = lancer_nav(tmp_path, {"NAV_HORS_LIGNE": "1"})
    assert sortie["ARGS"] == "run --offline --no-project --with playwright --with pillow python sonde.py"


def test_nav_laisse_choisir_le_dossier_des_navigateurs(tmp_path):
    sortie = lancer_nav(tmp_path, {"PLAYWRIGHT_BROWSERS_PATH": "/ailleurs/navigateurs"})
    assert sortie["BROWSERS"] == "/ailleurs/navigateurs"


def test_capturer_faux_hote_ne_tue_que_son_faux_hote():
    texte = CAPTURES.read_text()
    assert "proc.terminate()" in texte
    assert "pkill" not in texte and "killall" not in texte


def test_capturer_faux_hote_ne_pose_aucune_route():
    """Une route posée sur la page empêche le plateau de la Scène de se dessiner ."""
    assert ".route(" not in CAPTURES.read_text()


@pytest.mark.parametrize("methode, url, attendu", [
    ("GET", "https://exemple.invalide/", "laissée passer"),
    ("HEAD", "https://exemple.invalide/", "laissée passer"),
    ("POST", "http://127.0.0.1:8796/api/actions/fusions-auto", "laissée passer"),
    ("POST", "http://localhost:8796/api/actions/fusions-auto", "laissée passer"),
    ("POST", "http://127.0.0.1:9999/api/actions/fusions-auto", "bloquée"),
    ("POST", "https://hote-reel.exemple/api/actions/fusions-auto", "bloquée"),
    ("PUT", "https://hote-reel.exemple/", "bloquée"),
    ("DELETE", "http://127.0.0.1:8796/api/x", "laissée passer"),
])
def test_garde_bloque_hors_faux_hote(methode, url, attendu):
    route = FauxRoute(methode, url)
    fonctions_du_lanceur("vers_faux_hote", "garde")["garde"](route)
    assert route.fait == attendu
