#!/bin/sh
# Lance un script Python de tests/page/outils avec Playwright, sans l'installer dans le projet (uv le fournit le temps de l'exécution).
# Usage : sh tests/page/outils/nav.sh tests/page/outils/lancer_scenario.py <scenario.py> <dossier-captures>
#         sh tests/page/outils/nav.sh tests/page/outils/capturer_faux_hote.py <dossier-captures>
# Variables : PLAYWRIGHT_BROWSERS_PATH (où Playwright cherche ses navigateurs ; son dossier par défaut sinon),
#             NAV_HORS_LIGNE=1 (rien n'est téléchargé : uv travaille hors ligne), TMPDIR (fichiers temporaires).
if [ "${NAV_HORS_LIGNE:-}" = "1" ]; then
  exec uv run --offline --no-project --with playwright --with pillow python "$@"
fi
exec uv run --no-project --with playwright --with pillow python "$@"
