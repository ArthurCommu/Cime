# Dépendances entre équipes — exemple

## alpha
Dépend de : rien.
Statut : LIBRE

## beta
Dépend de : gamma (instantané), alpha (hook).
Statut : LIBRE

## gamma
Dépend de : alpha (socle).
Statut : LIBRE

## delta
Dépend de : l'utilisateur (validation) pour la phase 2 ; bêta
(API) pour le branchement.
Statut : phase 2 BLOQUÉE
