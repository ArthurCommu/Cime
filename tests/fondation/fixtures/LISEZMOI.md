# Fixtures de `tests/fondation`

- `hooks/*.json` : l'entrée standard que Claude Code envoie à un hook, un fichier par événement
  (première occurrence observée). `StopFailure.json` est dérivé de `Stop.json` (champ `error`
  ajouté, `stop_hook_active` retiré) : ce n'est pas une capture.
- `invite/*.ansi` : sorties brutes de `tmux capture-pane -p -e` sur une session Claude Code
  (invite vide, brouillon, suggestion atténuée, écrans d'approbation…).

Les chemins personnels et les noms propres à la machine d'enregistrement ont été remplacés par
des valeurs génériques (`/home/exemple`, `/tmp/exemple`).
