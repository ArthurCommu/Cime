<!-- socle {{version_socle}} — source : gabarits/socle/economie-de-tokens.md — ne pas modifier à la main : ce fichier sera remplacé par une mise à jour du socle -->

# Économie de tokens

Chaque token lu ou produit coûte, et un contexte encombré raisonne moins bien. Ces
règles valent pour l'Assistant, les coordinateurs et les workers. Elles viennent de
pratiques publiées (Anthropic, « multi-agent research system » et « effective context
engineering » ; Cognition, « Don't build multi-agents ») et de la pratique de
l'utilisateur sur ses projets. Elles n'ont pas été mesurées sur ce projet-ci : une fois
l'observation en place, vérifie-les sur ses chiffres.

## 1. Entre agents

1. **Un message court, et un fichier pour le long**, jamais un long texte transmis de
   bouche en bouche : chaque relais ajoute des tokens et déforme. Les résultats
   s'écrivent dans des fichiers ; le message n'en donne que le chemin (`--fichier`).
2. **La tâche autosuffisante** : le contexte nécessaire est dans le fichier de tâche,
   le worker n'explore pas. Un sous-agent mal briefé duplique le travail ou cherche au
   mauvais endroit.
3. **Des préfixes stables pour profiter du cache** : `CLAUDE.md`, socle et mandats ne
   changent pas en cours de session ; ce qui change va dans des fichiers lus à la
   demande. Un `CLAUDE.md` modifié en cours de route casse le cache de tous ceux qui le
   chargent.
4. **Le bon modèle au bon niveau** : Opus pour l'Assistant et les coordinateurs ; pour
   les workers, la politique fixée avec l'utilisateur (par défaut : Sonnet, Opus pour
   le jugement fin, Haiku seulement pour les sessions d'essai), notée dans chaque tâche.
5. **Le contexte partagé, pas les décisions implicites** : deux agents qui travaillent
   sur le même fichier prennent des décisions contradictoires sans le savoir. D'où :
   jamais deux équipes sur le même fichier.

## 2. Lire moins

- Lectures ciblées : `grep -n` puis `sed -n 'X,Yp'` (ou Read avec offset/limit) plutôt
  qu'un fichier entier. Ne relis jamais un fichier que tu viens d'écrire.
- Sorties filtrées : `pytest -q`, `| tail -n 20`. Voir ce que fait un worker : `{{commande}} voir
  <agent>` (état et 40 lignes d'écran) — aucun agent n'a accès à tmux. Jamais un journal entier ni
  une trace complète dans le contexte : cherche dedans avec `grep`.
- Pour revoir une livraison : la fiche d'interface et le rapport, puis les tests et
  `git diff --stat`, et seulement ensuite les passages de code utiles.

## 3. Écrire moins

- Messages et rapports courts : faits, décisions, points ouverts. Pas de
  récapitulatif de ce que le destinataire sait déjà.
- Pour montrer du code : un chemin `fichier:ligne`, pas un copier-coller.

## 4. Compacter (`/compact`)

- Un agent ne peut pas taper `/compact` lui-même, et aucun agent n'écrit dans un terminal :
  c'est son supérieur direct qui le demande par `{{commande}} compacter <agent> "<consignes>"`
  (ce que l'agent doit garder). La commande inscrit un ordre ; le facteur (le code) tape
  `/compact` **quand la session est au repos et son invite vide** (jamais en plein tour, jamais
  sur un brouillon), puis Cime constate que le compactage a eu lieu. Tu n'as ni invite à
  capturer ni `Enter` à envoyer. L'Assistant n'est compacté que par l'utilisateur.
  ```bash
  {{commande}} compacter worker-<équipe>-<tâche> "Garde : la tâche, les fichiers modifiés, les tests en échec et les décisions prises."
  ```
- Quand : à la fin d'une phase (livraison vérifiée, question réglée), avant une phase
  nouvelle, ou quand le contexte dépasse environ la moitié de la fenêtre (`/context`).
  Pas au milieu d'un débogage dont le détail sert encore.
- Avant de compacter, tout ce qui compte est écrit dans des fichiers
  (`conversations/`, `reports/`, tâches) : c'est la mémoire durable.
- Un worker ne vit que le temps de sa tâche : une fois son rapport lu et son travail
  vérifié, ferme sa session plutôt que de lui confier une deuxième tâche sans rapport.
