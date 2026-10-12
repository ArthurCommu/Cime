<!-- socle {{version_socle}} — source : gabarits/socle/LISEZMOI.md — ne pas modifier à la main : ce fichier sera remplacé par une mise à jour du socle -->

# Le socle

Ce dossier contient ce qui est **commun à tous les projets** de {{utilisateur}} : le rôle
de l'Assistant, celui du coordinateur, les rôles des équipes intégration et
vérification, les gabarits de mandat, de tâche et de requête d'intégration, les règles d'économie de tokens.

Version installée : {{version_socle}}, le {{date}}.

## On ne l'édite pas à la main

Chaque fichier porte en tête sa version et sa source. Une mise à jour du socle
(`{{commande}} socle`, à venir) **remplace** ce dossier entier : une modification faite
ici serait perdue sans bruit, et ce projet divergerait des autres sans que personne ne
le sache.

Ce qui est propre au projet vit ailleurs, et une mise à jour du socle n'y touche
jamais : le `CLAUDE.md` racine, `.orga/projet.toml`, `org-chart.md`,
`dependencies.md`, `etapes.md`, `produit/`, `contracts/`, `socle/comment-travaille-l-utilisateur.md`
(la façon de travailler de {{utilisateur}}, que l'Assistant enrichit), et les `CLAUDE.md` et
`mandate.md` de chaque équipe. Les `CLAUDE.md` sont courts : tous
**disent quels fichiers du socle lire**, au lancement et après chaque `/compact`
(celui de la racine : `economie-de-tokens.md`), puis ajoutent les particularités du
projet. Aucun n'importe quoi que ce soit par `@` : un import externe demande une
approbation à l'utilisateur au premier lancement, refusée par défaut, qu'un agent
autonome ne peut pas donner. Une
particularité qui contredit le socle s'écrit là, avec sa raison.

## Le socle est vivant : comment proposer une leçon

Une leçon apprise sur un projet doit pouvoir profiter à tous. Le circuit :

1. un agent rencontre une faute qui lui apprend quelque chose ; il la remonte à son
   supérieur, jusqu'à l'Assistant ;
2. l'Assistant **propose** la leçon à {{utilisateur}}, dans le chat : la faute datée, la
   loi en une phrase, le fichier du socle où l'écrire, et ce qu'elle change ;
3. {{utilisateur}} **valide** (ou non) ;
4. validée, elle entre dans le socle source et une mise à jour l'applique à tous ses
   projets.

En attendant la mise à jour, l'Assistant peut l'écrire dans le `CLAUDE.md` du projet
concerné, comme particularité, pour qu'elle s'applique tout de suite ici.
