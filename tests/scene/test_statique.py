"""Contrôles statiques de la scène (sans navigateur, sans node).

- index.html ne référence aucune ressource externe ;
- chaque import relatif et chaque script de module pointe un fichier existant ;
- aucun fichier sous src/cime/scene/static/ n'écrit, ne lit le stockage du navigateur,
  n'évalue de code, ni n'appelle l'API (la scène est en lecture seule).
  Aucun stockage du tout : la légende est celle de la page, qui garde ses préférences.
"""

import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
STATIC = RACINE / "src" / "cime" / "scene" / "static"

# Fichiers pas encore dans la branche : l'artiste les apporte. Leur absence est attendue tant qu'ils manquent.
EN_ATTENTE_ARTISTE = {"graphismes/atlas.js", "graphismes/palette.js"}

INTERDITS = [
    r"\bPOST\b",
    r"\bPUT\b",
    r"\bDELETE\b",
    r"XMLHttpRequest",
    r"localStorage",
    r"sessionStorage",
    r"\beval\(",
    r"fetch\(\s*['\"`]/api/",
    r"fetch\(\s*['\"`]https?://",
]


def fichiers_de_code():
    return [p for p in STATIC.rglob("*") if p.suffix in {".js", ".mjs", ".html", ".css"}]


def test_index_sans_ressource_externe():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert re.search(r"lang=\"fr\"", html)
    for motif in ["http://", "https://", "//cdn", "fonts.googleapis"]:
        assert motif not in html, f"ressource externe : {motif}"


def test_index_scripts_et_feuilles_locaux_existent():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    cibles = re.findall(r'<script type="module" src="([^"]+)"', html) + re.findall(r'<link rel="stylesheet" href="([^"]+)"', html)
    assert cibles, "aucun script ou feuille de style trouvé"
    for cible in cibles:
        assert (STATIC / cible).is_file(), cible


def test_imports_relatifs_existent():
    manquants = []
    motif = re.compile(r"""(?:from\s+|import\s*\(\s*|import\s+)['"](\.{1,2}/[^'"]+)['"]""")
    for fichier in fichiers_de_code():
        if fichier.suffix not in {".js", ".mjs"}:
            continue
        for cible in motif.findall(fichier.read_text(encoding="utf-8")):
            chemin = (fichier.parent / cible).resolve()
            relatif = str(chemin.relative_to(STATIC)) if STATIC in chemin.parents else cible
            if relatif in EN_ATTENTE_ARTISTE:
                continue
            if not chemin.is_file():
                manquants.append(f"{fichier.relative_to(STATIC)} → {cible}")
    assert manquants == [], manquants


@pytest.mark.parametrize("motif", INTERDITS)
def test_aucun_fichier_n_ecrit_ni_n_appelle(motif):
    trouves = []
    for fichier in fichiers_de_code():
        if re.search(motif, fichier.read_text(encoding="utf-8")):
            trouves.append(str(fichier.relative_to(STATIC)))
    assert trouves == [], f"{motif} dans {trouves}"


def test_aucun_stockage_ni_creation_de_style_dans_la_scene():
    """scene.js crée un canvas dans le conteneur et rien d'autre : ni stockage, ni feuille de style,
    ni texte injecté, ni évènement global (les touches de la page lui appartiennent)."""
    code = (STATIC / "scene.js").read_text(encoding="utf-8")
    for interdit in ["localStorage", "sessionStorage", "indexedDB", "innerHTML", "createElement('style')", "doc.addEventListener('key"]:
        assert interdit not in code, interdit
