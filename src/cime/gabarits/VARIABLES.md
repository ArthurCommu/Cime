# Gabarits de l'installation — variables et répartition

Ce fichier n'est **pas** recopié dans un projet installé. Tout le reste de `gabarits/`
l'est, tel quel (arborescence comprise), en remplaçant chaque variable.

## 1. Les variables

Syntaxe exacte : deux accolades, nom en `[a-z_]+`. Rien d'autre dans les gabarits ne
ressemble à cette syntaxe (les accolades simples de `projet.toml`, `{equipe}` et
`{depot}`, sont des motifs lus par l'application et doivent rester telles quelles ;
`{depot}` ne sert plus qu'aux anciens manifestes, dont le worktree était un dossier frère).

| variable | sens | exemple |
|---|---|---|
| `{{utilisateur}}` | nom de l'utilisateur, tel qu'il veut être désigné (`--utilisateur`) | `Camille` |
| `{{nom_projet}}` | nom affiché du projet | `Mon projet` |
| `{{prefixe}}` | préfixe des sessions tmux du projet | `mp` |
| `{{branche_reference}}` | branche de référence, où seul l'utilisateur fusionne | `main` |
| `{{commande}}` | nom de la commande de l'application (constante `NOM`) | — |
| `{{var_agent}}` | nom de la variable d'environnement qui porte l'identité de l'agent (`VAR_AGENT`) | — |
| `{{var_projet}}` | nom de la variable d'environnement qui porte la racine du projet (`VAR_PROJET`) | — |
| `{{date}}` | date d'installation, `AAAA-MM-JJ` | `2025-01-31` |
| `{{modele_assistant}}` | modèle de l'Assistant (Opus par défaut) | `claude-opus-5-5` |
| `{{modele_coordinateur}}` | modèle des coordinateurs (Opus par défaut) | `claude-opus-5-5` |
| `{{version_socle}}` | version du socle installé | `0.1.0` |

`{{var_projet}}` (et `{{var_agent}}`) sert dans les consignes de mesure : une session qui
hérite de ces variables les retire avec `env -u` avant de lancer un essai (voir les
socles `integration.md`, `coordinateur.md` et `gabarits/tache-worker.md`).

Valeurs techniques fixes, **qui ne sont pas des variables** : l'identité `utilisateur` et
les natures `rapport_utilisateur`, `decision_utilisateur`, `donnee_utilisateur` du registre.
Elles désignent l'utilisateur quel que soit son nom ; `socle/assistant.md` section 5 et
`socle/coordinateur.md` section 5 le disent.

## 2. Répartition socle / propre au projet

**Socle** (`.orga/socle/`, commun à tous les projets, remplacé en bloc par une mise à
jour du socle ; chaque fichier commence par l'en-tête
`<!-- socle {{version_socle}} — source : gabarits/socle/<chemin> — ne pas modifier à la main : … -->`) :

| fichier | contenu |
|---|---|
| `socle/assistant.md` | rôle de l'Assistant, dont la série de questions du premier démarrage (section 2) et la relecture après `/compact` |
| `socle/coordinateur.md` | rôle du coordinateur : lancer, superviser, clôturer un worker, écrire à l'Assistant, solliciter l'intégration |
| `socle/integration.md` | rôle de l'équipe intégration |
| `socle/verification.md` | ce qui est propre à l'équipe vérification (en plus du rôle de coordinateur) |
| `socle/economie-de-tokens.md` | règles d'économie de tokens, dont `/compact` |
| `socle/gabarits/mandat.md`, `tache-worker.md`, `requete-integration.md` | gabarits de documents |
| `socle/LISEZMOI.md` | ce qu'est le socle, qu'on ne l'édite pas, comment proposer une leçon |

Note sur l'en-tête : il porte `source : gabarits/socle/<chemin>`, forme imposée par la
tâche ; le chemin réel, sous ce dossier, est `.orga/socle/<chemin>`.

**Propre au projet** (jamais touché par une mise à jour du socle) :
`CLAUDE.md` racine, `.orga/projet.toml`, `org-chart.md`, `dependencies.md`,
`etapes.md`, `socle/comment-travaille-l-utilisateur.md` (neutre à l'installation, enrichi par l'Assistant), `produit/` (`index.md`, `contexte-court.md`, `arbitrages-en-cours.md`,
`decisions-actees/`), `contracts/CHANGELOG.md`, `templates/coordinateur-CLAUDE.md`,
`teams/assistant/CLAUDE.md`, `teams/verification/{CLAUDE.md,mandate.md}` et les `.gitkeep` des dossiers vides.

**Comment chaque agent reçoit son rôle** — une consigne de lecture, **jamais un import**
(syntaxe `@chemin` de Claude Code) :

| fichier | charge ou fait lire |
|---|---|
| `CLAUDE.md` racine | fait lire `socle/economie-de-tokens.md` (seul fichier commun à tous les agents) |
| `teams/assistant/CLAUDE.md` | fait lire `socle/assistant.md`, `socle/comment-travaille-l-utilisateur.md` |
| `templates/coordinateur-CLAUDE.md` (→ `teams/<équipe>/CLAUDE.md`) | fait lire `socle/coordinateur.md` |
| `teams/verification/CLAUDE.md` | fait lire `socle/coordinateur.md`, `socle/verification.md` |

« Fait lire » : le fichier dit « lis-le maintenant, et relis-le après chaque
`/compact` ». **Règle : aucun `@` dans les gabarits** (contrôle :
`grep -rn '^\s*@' .` lancé dans ce dossier → vide ; `tests/fondation/test_gabarits.py`
le vérifie). Raison : un import par `@` d'un fichier hors du dossier de travail — y
compris depuis le `CLAUDE.md` racine, que les coordinateurs et workers chargent aussi
comme parent — affiche au premier lancement l'écran « Allow external CLAUDE.md file
imports? » (défaut No, choix mémorisé) ; un agent autonome resterait bloqué, et approuver
est un geste de sécurité réservé à l'utilisateur (`cime lancer` signale cet écran, code 3).

**Pourquoi pas d'import, dans les équipes comme à la racine** : depuis la racine,
`@.orga/socle/x.md` est chargé sans question pour l'Assistant, mais pas pour un
coordinateur qui charge ce fichier en parent ; depuis `teams/<équipe>/`, `@../../socle/x.md`
est un import « externe » qui affiche un écran d'approbation au premier lancement,
**défaut No, choix mémorisé**. Un agent autonome ne recevrait jamais son rôle. Ce qu'on
perd : le rôle n'est plus chargé par le code mais lu sur consigne, et doit être relu
après chaque `/compact`.

**Le rôle de l'Assistant n'est pas importé à la racine** : le `CLAUDE.md`
racine **n'importe pas** le rôle de l'Assistant. Claude Code charge les `CLAUDE.md` du
dossier courant et de tous ses parents : un coordinateur (lancé dans
`.orga/teams/<équipe>/`) et un worker (lancé dans un worktree, qui contient le
`CLAUDE.md` racine versionné) recevraient sinon le rôle complet de l'Assistant —
tokens payés par tous, et risque de confusion de rôle. La racine porte donc le cadrage
commun (« qui es-tu ? », hiérarchie, interdits, rappel du premier démarrage) ; le rôle
de l'Assistant est dans `teams/assistant/CLAUDE.md`, que son prompt d'ouverture lui
fait lire (« Lis .orga/teams/assistant/CLAUDE.md et commence ta mission. », écrit dans
la tâche `lancer`) et qu'il relit, avec les fichiers du socle qu'il cite, après chaque `/compact`
(`socle/assistant.md`, en tête).
