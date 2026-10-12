# Cime

*[English version](README.en.md)*

Cime supervise une équipe d'agents Claude Code organisée comme une petite entreprise :
un Assistant, seul interlocuteur de l'utilisateur, des coordinateurs à la tête des équipes
et des workers qui exécutent chacun une tâche. Une page locale montre qui travaille, ce qui
se passe et où ça bloque. Ce qui demande attention passe au rouge. L'utilisateur y agit sans
casser la hiérarchie : il tranche ce qui lui revient et confie le reste à l'Assistant.

![La Scène : les agents du projet au travail](docs/captures/scene.png)

![Supervision : organigramme vivant, ce qui coince, avancement](docs/captures/supervision.png)

![Fil : qui parle à qui, ce qui attend une réponse](docs/captures/fil.png)

## Prérequis

- macOS (le lanceur s'appuie sur `launchd`, `open` et les notifications du système)
- Python 3.12 ou plus récent et [uv](https://docs.astral.sh/uv/)
- [Claude Code](https://docs.claude.com/en/docs/claude-code/overview) (la commande `claude`)
- tmux : chaque agent vit dans sa propre session
- git
- Node.js, seulement pour lancer les tests JavaScript

## Installation

Depuis une copie du dépôt :

```sh
cd cime
uv tool install .
cime --help
```

`uv tool install` place la commande `cime` dans le dossier d'outils d'uv (en général
`~/.local/bin`). S'il n'est pas sur le `PATH`, `uv tool update-shell` l'y ajoute. `cime init`
le vérifie, car les hooks qu'il écrit appellent `cime`.

## Démarrage

**Avec la page.** `cime ouvrir` démarre le lanceur (un par machine, sur `127.0.0.1`) et l'ouvre
dans le navigateur. On y crée un projet, on installe Cime dans un dossier existant, on ouvre la
page d'un projet, on le ferme ou on le rouvre.

```sh
cime ouvrir
```

**En ligne de commande.** `cime init` installe l'entreprise d'agents dans un dossier (créé et
passé sous git au besoin). `--apercu` montre ce qui serait écrit, sans rien écrire.

```sh
cime init ~/Projets/mon-projet --apercu
cime init ~/Projets/mon-projet --utilisateur Camille
```

`init` termine en indiquant la suite : ouvrir une fois le dossier dans Claude Code pour
l'approuver (`cd ~/Projets/mon-projet && claude`) puis lancer `cime lancer assistant`. L'option
`--lancer` enchaîne l'installation et le lancement de l'Assistant.

Pour ouvrir la page d'un projet sans passer par le lanceur, `cime servir ~/Projets/mon-projet`
démarre son serveur local et affiche l'adresse à ouvrir dans le navigateur
(`http://127.0.0.1:<port>/`).

`cime <sous-commande> --help` décrit chaque commande et ses options.

## Comment ça marche

```
                      utilisateur
                    ╱             ╲
          page (navigateur)     terminal : cime …
                    │                 │
         hôte local, 127.0.0.1 ───────┤
           │ lit          │ agit      │
           ▼              ▼           ▼
     observation ──▶ instantané   registre SQLite ◀── hooks Claude Code
     (git, tmux,                  (messages, états,       ▲
      transcripts)                 événements)            │
                                      │                   │
                                      ▼                   │
                                   facteur ──▶ sessions tmux des agents
                                               Assistant · coordinateurs · workers
```

`cime init` dépose dans le projet une structure `.orga/` (le rôle de chaque agent, les équipes,
les tâches) et des réglages Claude Code qui branchent les hooks de `cime`. Chaque agent tourne dans
une session tmux. Chaque équipe travaille sur sa branche, dans son propre worktree git. Les agents
ne se parlent jamais directement : ils écrivent au registre du projet (`cime envoyer`,
`cime repondre`) et un processus, le facteur, livre le courrier dans les terminaux. La page ne fait
que lire l'état. Ses rares actions passent par l'hôte, qui les journalise.

### Le code, paquet par paquet

Tout est dans `src/cime/`.

**`cli.py`** — la commande `cime`, qui renvoie chaque sous-commande vers son module.

**`fondation/`** — installer un projet et faire vivre ses agents.
- `init` installe la structure, crée le registre et génère les réglages Claude Code (hooks, interdits, bac à sable).
- `lancer` démarre un agent dans sa session tmux et `equipe` crée une équipe (dossier, branche, worktree).
- `terminer`, `fermer` et `rouvrir` clôturent une tâche, endorment ou réveillent un projet.
- La **garde** (commandes Bash) et le **périmètre** (outils de fichiers) contrôlent chaque action d'un agent avant qu'elle s'exécute.

**`signaux/`** — la messagerie entre agents.
- Une table dit quels messages existent et qui peut écrire quoi à qui.
- Un message peut créer une obligation pour son destinataire : accuser réception, répondre, rendre un travail.
- Le **facteur** tape chaque message dans le terminal de l'agent. Avant d'appuyer sur Entrée, il relit l'écran pour vérifier que la zone de saisie contient son texte et rien d'autre. Si l'utilisateur était en train d'y écrire, il n'envoie rien.
- Les **échéances** relancent un destinataire en retard puis préviennent son supérieur.

**`observation/`** — la photo de l'entreprise, en lecture seule.
- Sources : la structure déclarée dans `.orga/`, le registre, les sessions tmux, les branches git, les transcripts Claude Code (contexte et coût estimés).
- Une mesure qui échoue vaut « inconnu », jamais zéro.
- Les alarmes viennent d'une table unique de seuils.

**`hote/`** — le serveur local d'un projet (Starlette et uvicorn, sur `127.0.0.1` seulement).
- Il sert la page et lui pousse chaque nouvelle photo.
- Il exécute les décisions de l'utilisateur : autoriser, trancher, déposer un fichier, clôturer une équipe.
- Une demande de coordination (relancer une équipe, changer de cap) devient un message à l'Assistant.

**`page/`** — la page du projet, en HTML, CSS et JavaScript sans dépendance.
- La Scène, la Supervision, le Fil, le Journal, une fiche par équipe, les archives.
- Une mise en page dédiée au téléphone.

**`scene/`** — la vue d'accueil : les agents en pixel art à leur bureau, animés d'après les photos successives.
- Le dessin passe par une surface abstraite : les mêmes modules tournent sous Node dans les tests et produisent des PNG.

**`lanceur/`** — le processus unique de la machine.
- La liste des projets, leur création, leur ouverture et leur fermeture.
- Le texte de l'agent `launchd` qui le garde en vie (`cime lanceur --plist`, à installer soi-même).
- Un surveillant qui redémarre le facteur d'un projet actif s'il s'arrête.

**`gabarits/`** — ce que `cime init` dépose dans un projet : les rôles de l'Assistant, des coordinateurs et des workers, les modèles de tâche et de mandat, le manifeste `.orga/projet.toml`.

## Sécurité

Cime donne de l'autonomie à des agents. Les limites sont dans le code, pas dans les consignes.

- **La garde.** Avant chaque commande Bash d'un agent, le hook `PreToolUse` appelle la garde
  (`fondation/garde.py`). Elle refuse :
  - `git push` et la suppression de branche
  - toute fusion sur la branche de référence sans un accord de l'utilisateur donné pour ce commit
    précis (ou, s'il les a activées, sans remplir les conditions des fusions automatiques)
  - le Trousseau macOS (`security`)
  - l'accès direct à tmux et au registre
  - toute affectation des variables qui désignent l'agent et son projet

  Une commande qu'elle ne sait pas analyser et qui ressemble à une action interdite est refusée par
  prudence. Si l'exécutable `cime` a disparu, le hook refuse au lieu de laisser passer.
- **Le périmètre.** Le bac à sable de Claude Code enferme Bash, pas les outils de fichiers.
  `fondation/perimetre.py` refuse un Read, Write, Edit, Glob ou Grep dont le chemin sort du projet
  et limite l'écriture d'un agent d'équipe à son worktree.
- **Le bac à sable.** Les coordinateurs et les workers tournent dans le bac à sable de Claude Code
  (`fondation/reglages.py`) :
  - en lecture, le projet et les seuls outils dont ils ont besoin (git, uv), le reste du dossier
    personnel étant refusé
  - en écriture, les zones de l'agent
  - en réseau, les domaines que le projet déclare (`sites` dans `.orga/projet.toml`)
  - aucune commande hors bac à sable
- **Pas de push.** `git push` est interdit à tous les agents, Assistant compris (règles des
  réglages et garde). Ni l'hôte ni le lanceur ne poussent, ne fusionnent ou ne suppriment une
  branche : publier reste un geste de l'utilisateur.
- **Pas de lecture de secret.** `security` est refusé. Les réglages interdisent la lecture de
  `~/.ssh`, `~/.aws`, `~/.config/gh` et des fichiers `.env`.
- **Pas d'action non journalisée.** Chaque action de la page d'un projet ouvre une ligne de journal
  avant de s'exécuter et la clôt après, avec son auteur et son heure. Une action interrompue laisse
  donc sa trace. Le lanceur journalise chacune des siennes, succès ou échec. Les messages entre
  agents et leurs changements d'état sont inscrits au registre.
- **Un hôte qui n'obéit qu'à sa page.** L'hôte n'écoute que `127.0.0.1` et refuse toute requête
  dont l'en-tête `Host` ou `Origin` n'est pas le sien. Il ne lance que les commandes d'une liste
  blanche exacte (`hote/gardes.py`), seul module autorisé à créer un processus. Un test le vérifie.

## Tests

```sh
uv sync
uv run pytest tests -q
node --test tests/scene/js/*.test.mjs
```

La suite Python couvre chaque paquet. Certains tests ouvrent de vraies sessions tmux sur un socket
privé, rangé dans le dossier `.essai-tmux/` du dépôt. La suite JavaScript (la Scène et ses
graphismes, sous Node, sans navigateur) est aussi lancée par `tests/scene/test_js.py` quand Node
est présent. Sans Node, elle est sautée.

## Licence

MIT — voir [LICENSE](LICENSE).
