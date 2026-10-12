<!-- socle {{version_socle}} — source : gabarits/socle/gabarits/tache-worker.md — ne pas modifier à la main : ce fichier sera remplacé par une mise à jour du socle -->
<!--
Gabarit à copier dans tasks/todo/<tâche>.md par le coordinateur (sans les deux
commentaires d'en-tête). Test à appliquer avant de considérer la tâche prête : si
mandate.md disparaissait juste après l'écriture de ce fichier, le worker devrait
quand même pouvoir réaliser la tâche correctement.
-->

# Tâche : <titre court>

Équipe : <équipe>
Assigné : worker-<équipe>-<tâche>
Modèle : <modèle> — <raison du choix, selon la politique des workers ; par défaut Sonnet, Opus pour le jugement fin, jamais Haiku pour un worker>

## Contexte minimal nécessaire (ne cherche rien ailleurs dans le dépôt)
<Tout ce que le worker doit savoir pour comprendre POURQUOI cette tâche existe et à
quoi son résultat servira — distillé, pas un lien vers une spécification à lire.>

## Spécification technique
<Signatures, formats d'entrée et de sortie, exemples concrets, contraintes de style
ou de bibliothèques. Écris la MESURE à faire, jamais un résultat trouvé ailleurs.>

## Fichiers que tu écris (et aucun autre)
<liste exacte>

## Definition of done
- [ ] <critère vérifiable 1>
- [ ] <critère vérifiable 2>
- [ ] <tests, sur des données réelles dès que possible>

## Tests et essais
Tout test ou essai qui touche le registre fixe `{{var_projet}}` (et `{{var_agent}}`) **dans le
test** (fixture, `monkeypatch`) sur un dossier jetable (`tmp_path`) : sinon la commande
écrit dans le registre du vrai projet. N'écris jamais ces variables en ligne de commande
(`VAR=… cmd`, `env -u`, `unset`, `export`) : la garde refuse de les affecter ou de les retirer.

Teste sur du réel (captures, sessions réelles) dès que possible. Une fixture est une
copie : écris en tête d'où elle vient et quand, et remplace-y le dossier personnel de la
machine par un nom neutre (le dépôt peut être publié).

Tu n'as aucun accès à tmux (la garde refuse toute commande `tmux`). Un **test** qui a besoin
de tmux le fait dans son code (appel remplaçable par un faux), sur un serveur à part :
`tmux -L {{commande}}-essai …` — jamais le serveur par défaut, où vivent les vrais agents.
Une vraie session Claude Code d'essai se demande à ton coordinateur.

## Où tu travailles
Dans le worktree de l'équipe, `<chemin>`, branche `<branche d'équipe>`. Tu n'écris que
dans les fichiers listés ci-dessus et tu ne commites qu'eux. Tes réglages refusent, par
le code, `git push`, la suppression de branche, la fusion dans le dépôt principal et la
lecture de secrets (Trousseau, `~/.ssh`, `~/.aws`, `~/.config/gh`, `.env`) : ne cherche
pas à les contourner, ce sont des décisions de l'utilisateur.

## Économie de tokens
- Tout ce qu'il te faut est dans cette tâche : n'explore pas le dépôt au-delà des
  fichiers qu'elle cite.
- Lectures ciblées (`grep -n`, `sed -n 'X,Yp'`, Read avec offset/limit) ; ne relis pas
  un fichier que tu viens d'écrire.
- Sorties filtrées : `pytest -q`, `| tail -n 20`, `grep` dans les journaux au lieu de
  les afficher en entier.
- Ton coordinateur peut t'envoyer `/compact` entre deux phases : c'est normal, reprends
  à partir du résumé.

## En cas de doute
Ne tranche pas : demande à ton coordinateur, et attends sa réponse.
`{{commande}} envoyer --a coord-<équipe> --nature question "<la question en une ligne>"`
(question longue : `--corps -` avec le texte sur l'entrée standard, ou `--fichier` vers un fichier
de `<racine>/.orga/teams/<équipe>/conversations/`). Ta réponse arrive dans ta session,
préfixée de l'émetteur ; tu n'écris jamais dans un terminal.

Ne notifie jamais l'utilisateur : tu ne lances jamais `osascript` (l'hôte de Cime le
notifie ; lancé depuis une session de worker, `osascript` déclenche des demandes
d'autorisation au terminal).

## Rapport attendu
Écris ton rapport dans `<racine-du-dépôt-principal>/.orga/teams/<équipe>/reports/worker-<équipe>-<tâche>-<AAAA-MM-JJ>.md`
— **chemin absolu du dépôt principal, jamais un chemin relatif** : tu travailles dans
un worktree, et un rapport écrit là n'est pas vu par ton coordinateur. Contenu, court : ce qui est fait (fichiers,
commit), **ce que tu as mesuré et sur quoi**, décisions prises, incertitudes.
Puis préviens ton coordinateur **en répondant à la consigne de ta tâche** (son `#id` figure dans le
message de lancement que tu as reçu ; `{{commande}} reprise` le rappelle) :
`{{commande}} repondre <id> --nature travail_pret --fichier .orga/teams/<équipe>/reports/<ton rapport> "<résumé en une ligne>"`.
Tant que tu n'as pas fait cette commande, ta tâche est une dette : si tu t'arrêtes avant,
Cime te le rappelle une fois, puis prévient ton coordinateur.
