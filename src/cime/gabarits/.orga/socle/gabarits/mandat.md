<!-- socle {{version_socle}} — source : gabarits/socle/gabarits/mandat.md — ne pas modifier à la main : ce fichier sera remplacé par une mise à jour du socle -->
<!--
Gabarit à copier dans .orga/teams/<équipe>/mandate.md par l'Assistant (sans les deux
commentaires d'en-tête). Les trois blocs sont obligatoires, dans cet ordre. Rien
d'autre : un mandat ne change pas en cours de vie de l'équipe (cache, stabilité).
-->

# Mandat — équipe <équipe>

## Bloc 1 — Contexte produit
<!-- Copier ici, tel quel, le contenu de .orga/produit/contexte-court.md.
     Jamais paraphrasé ni raccourci : il est écrit court pour servir ici. -->

## Bloc 2 — Position dans le graphe
Mission de cette équipe dans le produit : <1-2 phrases>

En amont, tu consommes :
- <équipe / contrat, ou « rien — tu es une source primaire »>

En aval, tu alimentes :
- <équipe / contrat> — <ce qu'elle en fait, pourquoi ton format compte pour elle>

Pourquoi c'est important : <ce qui casse, silencieusement ou non, si ton contrat
change sans coordination>

## Bloc 3 — Mandat technique
Périmètre : <fichiers / modules du dépôt dont l'équipe est seule propriétaire>

Branche et worktree : <branche d'équipe> — <chemin du worktree>
(le dépôt principal reste sur {{branche_reference}} ; aucune fusion vers lui sans l'accord de l'utilisateur ; c'est l'Assistant qui fusionne)

Contrats d'interface concernés :
- Tu ÉCRIS selon : <.orga/contracts/x.schema.md, section précise, ou « aucun »>
- Tu LIS depuis : <.orga/contracts/y.schema.md, section précise, ou « aucun »>

Contraintes techniques : <ce qui est nécessaire, avec sa source si c'est un extrait
de .orga/produit/>

Definition of done :
- [ ] <critère 1, vérifiable par une mesure>
- [ ] <critère 2>
- [ ] Validation par l'équipe intégration si un contrat est concerné
