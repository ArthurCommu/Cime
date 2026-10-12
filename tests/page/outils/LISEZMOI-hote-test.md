# Voir le rendu de la page

Outils pour vérifier la page dans un vrai navigateur, contre un hôte factice (bibliothèque standard seule). Ils ne sont pas collectés par pytest : Playwright reste hors de la suite de tests.

## Lancer un scénario

Depuis la racine du dépôt, avec Chrome installé sur le système :

```bash
python3 tests/page/outils/hote_factice.py src/cime/page 8791 &   # faux hôte ; noter le PID, l'arrêter avec kill <PID>
uv run --with playwright python tests/page/outils/scenario_hote.py
uv run --with playwright python tests/page/outils/scenario_coupure.py
```

Variables : `CIME_PORT_TEST` (port côté scénarios, 8791 par défaut, à accorder avec l'argument du faux hôte), `CIME_CHROME` (chemin de Chrome, celui de macOS par défaut). Code de sortie 1 si une vérification échoue. Relancer le faux hôte avant `scenario_hote.py` pour partir d'un état neuf.

## Ce que fait chaque outil

- `hote_factice.py` (nommé ainsi et non `hote_test.py`, que pytest collecterait) : sert la page et l'état d'exemple de `tests/page/fixtures/` sur l'API de l'hôte (`/api/etat`, `/api/flux`, `/api/journal`, actions, terminaux, fichiers). Réglages réservés au test : `GET /test/regler?flux=normal|muet|coupe&actions=ok|refuse|erreur|lent|casse&etat=ok|panne&autonome=inactif|actif|suspendu|absent|sans_proposees` (le mode autonome, champ `fusions_auto` ; `POST /api/actions/fusions-auto` le fait changer, réactivation d'un mode suspendu comprise) ; relevé des requêtes reçues : `GET /test/requetes`.
- `scenario_hote.py` : la page en mode hôte : affichage, actions (autoriser, refuser, trancher, déposer, clôturer, lu) et leurs refus ou erreurs, terminaux, flux muet puis coupé (rouge) puis rétabli, chemins appelés, aucune erreur JS.
- `scenario_coupure.py` : flux coupé, l'âge de la donnée passe au rouge ; flux rétabli, retour à « à jour ».
- `scenario_mode_autonome.py` : l'interrupteur « Mode autonome » dans la Scène : les cinq états à 1 440 et 390 px, la bascule à la souris et au clavier (Espace), « Activation… », le toast, le refus, la pastille d'en-tête, le balayage de l'en-tête de 761 à 1 440 px avec un nom de projet long, l'interrupteur dans la feuille et le tiroir du téléphone. `uv run --with playwright python tests/page/outils/scenario_mode_autonome.py <dossier-captures>` ; relancer le faux hôte avant.
- Les autres `scenario_*.py` (cadre, consommation, équipe, historique, lu, mobile, plateau, rail, supervision) vérifient chacun un écran ; leur docstring dit ce qu'il contrôle et comment le lancer.

## Captures et scénarios avec `nav.sh`

`nav.sh` lance un script de ce dossier avec Playwright, fourni par `uv` le temps de l'exécution. Trois commandes, depuis la racine du dépôt :

```bash
# 1. les captures de la page servie par le faux hôte (mode autonome : sans, actif, suspendu ; bureau 1 440 × 900 et mobile 390 × 844)
sh tests/page/outils/nav.sh tests/page/outils/capturer_faux_hote.py <dossier-captures>

# 2. un scénario de la page (le faux hôte doit tourner déjà, sur CIME_PORT_TEST)
python3 tests/page/outils/hote_factice.py src/cime/page 8796 &      # noter le PID, l'arrêter par kill <PID>
CIME_PORT_TEST=8796 sh tests/page/outils/nav.sh tests/page/outils/lancer_scenario.py tests/page/outils/scenario_mode_autonome.py <dossier-captures>

# 3. les tests de ces outils (sans navigateur)
uv run --with pytest python -m pytest tests/page/test_outils_navigateur.py -q
```

- `nav.sh` lit `PLAYWRIGHT_BROWSERS_PATH` (le dossier où Playwright cherche ses navigateurs ; son dossier par défaut sinon), `NAV_HORS_LIGNE=1` (rien n'est téléchargé : `uv` travaille hors ligne) et `TMPDIR` (fichiers temporaires).
- `capturer_faux_hote.py` démarre et arrête son propre faux hôte, et écrit chaque vue en écran et en page entière (`<vue>-<taille>.png`, `<vue>-<taille>-entiere.png`). Le réseau bloqué (Google Fonts, `ERR_TUNNEL_CONNECTION_FAILED`) est affiché mais ne fait pas échouer le script.
- `lancer_scenario.py` ne modifie pas le scénario : il lui fournit un vrai navigateur par contexte, et bloque toute requête autre que GET/HEAD sauf vers le faux hôte.

Les captures sont à regarder : un scénario vert ne dit rien d'une mise en page qui a bougé.
