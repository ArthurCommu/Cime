# Organigramme — {{nom_projet}}

Tenu exclusivement par l'Assistant. Mis à jour à chaque création d'équipe, changement
substantiel de mission, et passage d'une équipe en « terminée ».

**Un organigramme obsolète est plus dangereux qu'absent** : il est lu comme vrai.

Ce fichier sert à COMPRENDRE le paysage, pas à agir. Un coordinateur ne contacte jamais
directement une autre équipe — toute coordination latérale passe par l'Assistant, sauf
le canal explicitement autorisé vers l'équipe intégration.

Hiérarchie : **{{utilisateur}}** → **Assistant** (`{{prefixe}}-assistant`,
`{{modele_assistant}}`) → coordinateurs (`{{modele_coordinateur}}`) → workers (modèle
selon la politique fixée avec {{utilisateur}}, noté dans chaque tâche).

---

## Équipes

<!-- Une entrée par équipe, sur ce modèle :
### <équipe>
Mission : <une phrase>
Statut : <en cours (lancement AAAA-MM-JJ) | terminée (AAAA-MM-JJ)>
Écrit vers (contrats) : <contrats, ou aucun>
Lit depuis (contrats) : <contrats, ou aucun>
Coordinateur : <modèle> (session tmux {{prefixe}}-coord-<équipe>)
Branche / worktree : <branche> — <chemin>
Créée le : <AAAA-MM-JJ>
-->

### verification
Mission : vérifier que l'Assistant fait bien ce qui a été décidé (matrice décisions →
mandats, contrats, code). N'implémente rien ; ne rend compte qu'à l'Assistant.
Statut : installée, lancée après la première série de questions ; permanente
Écrit vers (contrats) : aucun
Lit depuis (contrats) : tous, en lecture
Coordinateur : {{modele_coordinateur}} (session tmux {{prefixe}}-coord-verification)
Branche / worktree : aucun
Créée le : {{date}}

### integration
Mission : vérifier l'interopérabilité réelle entre blocs de deux équipes.
Statut : à la demande de l'Assistant (n'est plus installée par défaut ; l'Assistant la crée quand un
coordinateur la lui demande, `{{commande}} envoyer --a assistant --nature question --objet integration:<équipe>`)
Créée le : —
