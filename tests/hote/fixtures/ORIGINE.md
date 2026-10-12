# Fixtures de l'hôte

- `instantane-exemple.json` : un instantané complet synthétique (projet `mon-projet`, agents, tâches,
  fil de messages, attentes de l'utilisateur, alarmes). Le préfixe tmux `cc` et les sessions d'agents
  sont fictifs mais plausibles : ne jamais l'utiliser tel quel dans un test qui appelle tmux.
- `instantane-sources-absentes.json` : variante écrite à la main où les sources d'observation sont
  à `null` (sources absentes).
- `captures-autorisation/` et `menus/` : captures d'écran de terminal (`tmux capture-pane -p -e`,
  séquences ANSI conservées) de menus de demande d'autorisation de Claude Code, prises dans une
  session d'essai ; les chemins y sont génériques. Voir `captures-autorisation/ORIGINE.md`.
