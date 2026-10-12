# Dépendances entre équipes — {{nom_projet}}

Tenu exclusivement par l'Assistant. Une équipe lit ce fichier à son lancement pour
vérifier qu'elle n'est pas BLOQUÉE avant de lancer le moindre worker.

<!-- Une entrée par équipe, sur ce modèle :
## <équipe>
Dépend de : <équipes / contrats, ou rien>
Statut : <LIBRE | BLOQUÉE (en attente de <quoi>, depuis AAAA-MM-JJ)>
Ce qui casse si elle démarre quand même : <conséquence concrète, ou —>
-->

## verification
Dépend de : des décisions consignées dans `produit/` (rien à vérifier avant).
Statut : LIBRE dès la première série de questions consignée
Ce qui casse si elle démarre quand même : rien, elle n'aurait rien à vérifier.
