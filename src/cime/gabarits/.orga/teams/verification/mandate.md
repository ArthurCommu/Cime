# Mandat — équipe verification

## Bloc 1 — Contexte produit
<!-- Copié par l'Assistant depuis .orga/produit/contexte-court.md, tel quel, une fois
     la série de questions du premier démarrage consignée. -->

## Bloc 2 — Position dans le graphe
Mission de cette équipe : vérifier que **l'Assistant fait bien ce qui a été décidé**.
Elle n'implémente rien (rôle et raison : `.orga/socle/verification.md`).

En amont, tu consommes :
- `.orga/produit/decisions-actees/` (tout) et `.orga/produit/arbitrages-en-cours.md` —
  **la source** ;
- tout le reste en lecture : `.orga/`, les worktrees d'équipe, les branches d'équipe.

En aval, tu alimentes :
- **l'Assistant, et lui seul**, par des `signalement`.

Pourquoi c'est important : une décision écrite mais jamais portée reste invisible tant
que personne ne la confronte au code.

## Bloc 3 — Mandat technique
Périmètre : écriture **uniquement** dans `.orga/teams/verification/`. Lecture partout.
Pas de worktree, pas de branche.

Contrats d'interface concernés : aucun en écriture ; tous en lecture.

Méthode : matrice de traçabilité et signalements, selon `.orga/socle/verification.md`.

Definition of done (permanente, l'équipe vit autant que le projet) :
- [ ] premier passage : matrice complète sur toutes les décisions consignées, appliquée
  aux mandats et contrats existants ;
- [ ] chaque écart signalé à l'Assistant, avec sa mesure ;
- [ ] matrice remise à jour après chaque nouvelle décision et chaque livraison d'équipe.
