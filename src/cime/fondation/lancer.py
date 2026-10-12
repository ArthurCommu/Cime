"""`cime lancer` : prépare les réglages d'un agent et démarre sa session tmux.

Un worker dont la fiche est restée dans `in-progress/` sans session tmux ni processus `claude`
est orphelin : le lancer reprend la même fiche dans une nouvelle session, sans rien déplacer."""

import argparse
import copy
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from cime.fondation.nom import NOM, VAR_AGENT, VAR_PROJET
from cime.fondation.perimetre import zones_ecriture_projet
from cime.fondation.projet import (
    ErreurProjet, Manifeste, lire_manifeste, session_tmux, trouver_projet,
    worktree_equipe,
)
from cime.fondation.reglages import INTERDITS_INTEGRATION, bac_a_sable, regles_commit_equipe

_NOM_VALIDE = re.compile(r"[a-z0-9-]+")
_NOM_SESSION = re.compile(r"[A-Za-z0-9-]+")
_NON_ALNUM = re.compile(r"[^A-Za-z0-9]")

EQUIPE_INTEGRATION = "integration"

CODE_REFUS = 2
CODE_APPROBATION = 3
DUREE_SURVEILLANCE = 10.0
DELAI_SURVEILLANCE = 1.0

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x1b]*\x1b\\")
_LIBELLES = {"confiance": "confiance du dossier", "imports": "imports externes"}

MESSAGE_ASSISTANT = "Lis .orga/teams/assistant/CLAUDE.md et commence ta mission."
MESSAGE_COORDINATEUR = "Lis CLAUDE.md puis mandate.md et commence ta mission."


class Refus(ErreurProjet):
    """Reprise refusée avant tout lancement (code 2)."""


def _nom(valeur: str | None, libelle: str) -> str:
    if not valeur:
        raise ErreurProjet(f"{libelle} requis pour ce rôle")
    if not _NOM_VALIDE.fullmatch(valeur):
        raise ErreurProjet(f"{libelle} invalide : {valeur!r} (attendu : [a-z0-9-]+)")
    return valeur


_FICHIER_ROLE = {"assistant": "settings.json", "worker": "settings-agent.json",
                 "coord": "settings-coordinateur.json"}


def reglages(projet: Path, role: str) -> Path:
    """Fichier statique du rôle (`.claude/settings*.json`), écrit par `init`."""
    nom = _FICHIER_ROLE[role]
    fichier = (Path(projet) / ".claude" / nom).resolve()
    if not fichier.is_file():
        raise ErreurProjet(
            f"réglages absents : {fichier} — relance `{NOM} init` dans ce projet "
            "(il écrit les fichiers de réglages manquants, sans toucher aux autres)")
    return fichier


def dossier_etat(projet: Path) -> Path:
    return Path(projet) / ".orga" / "etat"


def dossier_tmp(projet: Path) -> Path:
    """Dossier temporaire de Claude Code (CLAUDE_CODE_TMPDIR) : privé, il veut 0o700."""
    return dossier_etat(projet) / "tmp"


def dossier_memoire(projet: Path) -> Path:
    return dossier_etat(projet) / "memoire"


def dossier_essais(projet: Path) -> Path:
    """Essais et intégration : jamais hors du projet (voir le socle, `integration.md`)."""
    return dossier_etat(projet) / "essais"


def preparer_tmp(projet: Path) -> None:
    dossier = dossier_tmp(projet)
    dossier.mkdir(parents=True, exist_ok=True)
    os.chmod(dossier, 0o700)


def fichier_reglages_generes(projet: Path, identite: str) -> Path:
    return dossier_etat(projet) / "reglages" / f"{identite}.json"


def _identite(role: str, equipe: str | None, tache: str | None) -> str:
    if role == "assistant":
        return "assistant"
    if role == "coord":
        return f"coord-{equipe}"
    return f"worker-{equipe}-{tache}"


def racine_de_l_outil(cible: Path) -> Path:
    """Dossier à rouvrir en lecture pour que `cible` (exécutable déjà résolu) tourne : le
    premier parent qui contient un `pyvenv.cfg` (racine de son environnement), sinon le
    dossier qui le contient. Rien de codé en dur."""
    cible = Path(cible)
    for parent in cible.parents:
        if (parent / "pyvenv.cfg").is_file():
            return parent
    return cible.parent


def dossier_outil() -> Path | None:
    """Dossier de l'outil `cime` à rouvrir en lecture dans le bac à sable (`None` si rien à
    ouvrir). Un environnement dont la racine serait la maison, ou la contiendrait, n'est
    jamais rouvert : ce serait rouvrir toute la maison, `~/.ssh` compris."""
    trouve = shutil.which(NOM)
    if trouve is None:
        trouve = sys.argv[0] if os.sep in sys.argv[0] else sys.executable
    racine = racine_de_l_outil(Path(os.path.realpath(trouve)))
    maison = Path.home().resolve()
    if racine == maison or racine in maison.parents:
        return None
    return racine


def _paquet_cime() -> str:
    """Dossier du paquet `cime` (`cime` est un paquet-espace de noms : pas de `__file__`)."""
    import cime
    return next(iter(cime.__path__))


def dossier_source_cime() -> Path | None:
    """Entrée de `sys.path` d'où `cime` est effectivement importé (`<…>/src` en éditable,
    `…/site-packages` sinon), `realpath`, jamais écrite en dur. `None` si c'est la maison ou un
    parent de la maison : on ne rouvre jamais toute la maison."""
    source = Path(os.path.realpath(_paquet_cime())).parent
    maison = Path.home().resolve()
    if source == maison or source in maison.parents:
        return None
    return source


def _lisible(chemin: Path, allow: list[str], deny: list[str]) -> bool:
    """Le bac à sable laisse-t-il lire `chemin` ? Une entrée de `allowRead` l'emporte sur
    `denyRead` ; hors de l'un et de l'autre, la lecture est libre."""
    chemin = Path(chemin)
    if any(chemin.is_relative_to(a) for a in allow):
        return True
    return not any(chemin.is_relative_to(d) for d in deny)


def import_cime_non_lisible(sandbox: dict, paquet_cime: Path, chemins: list[str]) -> list[Path]:
    """Fonction pure : les dossiers que `cime` doit lire pour s'importer sans que les lectures
    du bac à sable `sandbox` (bloc `sandbox` généré) les couvrent. `paquet_cime` est le
    dossier du paquet `cime` (`cime.__path__`) ; `chemins`, le `sys.path` de l'interpréteur de l'outil (les entrées
    inexistantes sont ignorées). Liste vide : l'import passe."""
    lectures = sandbox.get("filesystem", {})
    allow = [str(a) for a in lectures.get("allowRead", [])]
    deny = [str(d) for d in lectures.get("denyRead", [])]
    manquants = []
    for chemin in [Path(paquet_cime).parent, *(Path(c) for c in chemins if c)]:
        if chemin.exists() and not _lisible(chemin, allow, deny) and chemin not in manquants:
            manquants.append(chemin)
    return manquants


def sonder_import_cime(python: str) -> tuple[Path, list[str]]:
    """(dossier du paquet `cime`, `sys.path`) vus par `python -I` : l'interpréteur de l'outil. `Refus` si
    `cime` ne s'y importe pas du tout."""
    try:
        r = subprocess.run(
            [python, "-I", "-c",
             "import json, sys, cime; print(json.dumps([list(cime.__path__)[0], sys.path]))"],
            capture_output=True, text=True, timeout=30)
        fichier, chemins = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 else (None, None)
    except (OSError, subprocess.SubprocessError, ValueError, IndexError) as e:
        raise Refus(f"autotest : `{python} -c 'import cime'` n'a pas pu s'exécuter ({e}) ; "
                    "vérifie l'installation `uv tool`") from e
    if fichier is None:
        raise Refus(f"autotest : cime ne s'importe pas avec {python} : "
                    f"{r.stderr.strip().splitlines()[-1] if r.stderr.strip() else r.returncode} ; "
                    "vérifie l'installation `uv tool`")
    return Path(os.path.realpath(fichier)), chemins


def verifier_import_cime(sandbox: dict, paquet_cime: Path, chemins: list[str]) -> None:
    """Refuse (`Refus`, code 2) si `cime` ne peut pas s'importer sous les lectures `sandbox`.
    Le message dit quoi faire."""
    manquants = import_cime_non_lisible(sandbox, paquet_cime, chemins)
    if manquants:
        liste = ", ".join(f"`{m}`" for m in manquants)
        raise Refus(f"la source de cime {liste} n'est pas couverte par les lectures de "
                    "l'agent (allowRead) : `cime reprise` y échouerait avec ModuleNotFoundError "
                    "et l'agent serait muet ; vérifie l'installation `uv tool`")


def python_de_l_outil() -> str:
    """Interpréteur de l'environnement de `cime` : `<racine>/bin/python`, à défaut celui-ci."""
    racine = dossier_outil()
    candidat = racine / "bin" / "python" if racine is not None else None
    return str(candidat) if candidat is not None and candidat.exists() else sys.executable


def construire_reglages(statique: dict, projet: Path, identite: str, sites: list[str],
                        home: Path, uid: int, zones_ecriture: list[Path],
                        outil: Path | None = None, regles_allow: list[str] | None = None,
                        regles_deny: tuple[str, ...] = (), source: Path | None = None) -> dict:
    """Contenu du fichier généré au lancement (fonction pure). Les clés du fichier statique
    passent telles quelles, sauf `sandbox` et `autoMemoryDirectory`, qui sont remplacés.
    L'Assistant ne tourne pas dans le bac à sable : pas de `sandbox`."""
    memoire = str(dossier_memoire(projet) / identite)
    if identite == "assistant":
        return {k: v for k, v in statique.items() if k != "sandbox"} | {
            "autoMemoryDirectory": memoire}
    contenu = {**statique,
               **bac_a_sable(projet, sites, home, uid, zones_ecriture, outil, source),
               "autoMemoryDirectory": memoire}
    if regles_allow:  # ex. le droit de commit d'un coordinateur dans le worktree de son équipe
        permissions = copy.deepcopy(contenu.get("permissions") or {})
        permissions["allow"] = [*permissions.get("allow", []),
                                *(r for r in regles_allow if r not in permissions.get("allow", []))]
        contenu["permissions"] = permissions
    if regles_deny:  # ex. la session d'intégration ne commite ni ne fusionne jamais
        permissions = copy.deepcopy(contenu.get("permissions") or {})
        permissions["deny"] = [*permissions.get("deny", []),
                               *(r for r in regles_deny if r not in permissions.get("deny", []))]
        contenu["permissions"] = permissions
    return contenu


def zones_du_bac_a_sable(projet: Path, identite: str, integration: bool = False) -> list[Path]:
    """Où l'agent peut écrire : celles de sa garde ; le projet entier si la garde ne le
    limite pas ; et `.orga/etat/essais` pour une session d'intégration."""
    zones = zones_ecriture_projet(projet, identite)
    zones = [projet] if zones is None else zones
    return [*zones, dossier_essais(projet)] if integration else zones


def contenu_reglages_generes(projet: Path, identite: str, role: str, manifeste: Manifeste,
                             integration: bool = False) -> dict:
    """Ce que `ecrire_reglages_generes` écrit, sans rien écrire."""
    projet = Path(projet).resolve()
    statique = json.loads(reglages(projet, role).read_text(encoding="utf-8"))
    regles = []
    if role == "coord" and identite.startswith("coord-"):
        regles = regles_commit_equipe(worktree_equipe(projet, manifeste, identite[len("coord-"):]))
    contenu = construire_reglages(statique, projet, identite, manifeste.sites,
                                  Path.home().resolve(), os.getuid(),
                                  zones_du_bac_a_sable(projet, identite, integration),
                                  dossier_outil(), regles,
                                  INTERDITS_INTEGRATION if integration else (),
                                  dossier_source_cime())
    return contenu


def ecrire_reglages_generes(projet: Path, identite: str, role: str, manifeste: Manifeste,
                            integration: bool = False, contenu: dict | None = None) -> Path:
    """Écrit `<projet>/.orga/etat/reglages/<identité>.json` et crée les dossiers de travail."""
    projet = Path(projet).resolve()
    if contenu is None:
        contenu = contenu_reglages_generes(projet, identite, role, manifeste, integration)
    preparer_tmp(projet)
    (dossier_memoire(projet) / identite).mkdir(parents=True, exist_ok=True)
    fichier = fichier_reglages_generes(projet, identite)
    fichier.parent.mkdir(parents=True, exist_ok=True)
    fichier.write_text(json.dumps(contenu, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    return fichier


def _dossier_equipe(projet: Path, equipe: str) -> Path:
    return Path(projet) / ".orga" / "teams" / equipe


def _verifier_equipe(projet: Path, equipe: str) -> Path:
    dossier = _dossier_equipe(projet, equipe)
    if not (dossier / "mandate.md").is_file():
        raise ErreurProjet(f"l'équipe {equipe} n'a pas de mandate.md")
    if (dossier / "CLOTUREE").exists():
        raise ErreurProjet(f"l'équipe {equipe} est terminée (CLOTUREE présent)")
    return dossier


def _tache_a_lancer(projet: Path, equipe: str, tache: str) -> tuple[Path, Path]:
    taches = _dossier_equipe(projet, equipe) / "tasks"
    return taches / "todo" / f"{tache}.md", taches / "in-progress" / f"{tache}.md"


def tache_orpheline(projet: Path, manifeste: Manifeste, equipe: str, tache: str) -> bool:
    """Fiche dans `in-progress/` seule (pas dans `todo/`), ni session tmux du worker ni processus
    `claude` dans son worktree : personne ne la porte plus. Même sonde que `--reprendre`."""
    todo, en_cours = _tache_a_lancer(projet, equipe, tache)
    if todo.exists() or not en_cours.is_file():
        return False
    session = session_tmux(manifeste, f"worker-{equipe}-{tache}")
    if session is None or _session_existe(session):
        return False
    return not processus_claude_dans(worktree_equipe(projet, manifeste, equipe))


def _requete(projet: Path, requete: str) -> Path:
    return _dossier_equipe(projet, EQUIPE_INTEGRATION) / "requests" / "todo" / f"{requete}.md"


def _est_integration(role: str, equipe: str | None) -> bool:
    return role == "worker" and equipe == EQUIPE_INTEGRATION


def encoder_dossier(dossier: Path) -> str:
    """Nom du dossier de conversations de Claude Code : chemin réel, tout caractère
    hors [A-Za-z0-9] devient `-` (mesuré sur 2.1.293, mesuré sur le terrain)."""
    return _NON_ALNUM.sub("-", str(Path(dossier).resolve()))


def dossier_conversations(dossier: Path, racine_claude: Path | None = None) -> Path:
    racine = Path.home() / ".claude" if racine_claude is None else Path(racine_claude)
    return racine / "projects" / encoder_dossier(dossier)


def derniere_conversation(dossier: Path, racine_claude: Path | None = None,
                          session: str | None = None) -> str | None:
    """Identifiant de la conversation à reprendre, d'après les seuls noms et dates des
    `*.jsonl` placés directement dans le dossier de conversations (jamais leur contenu).

    Avec `session` : cet identifiant s'il existe, sinon None."""
    sous = dossier_conversations(dossier, racine_claude)
    if session is not None:
        return session if (sous / f"{session}.jsonl").is_file() else None
    fichiers = [f for f in sous.glob("*.jsonl") if f.is_file()] if sous.is_dir() else []
    if not fichiers:
        return None
    return max(fichiers, key=lambda f: (f.stat().st_mtime, f.name)).stem


def processus_claude_dans(dossier: Path) -> list[int]:
    """PID des processus `claude` dont le dossier courant est `dossier` (ps + lsof).

    Mesuré : une conversation reprise alors qu'elle est ouverte ailleurs n'avertit pas et
    les deux sessions écrivent le même fichier."""
    try:
        ps = subprocess.run(["ps", "-axo", "pid=,comm="], capture_output=True, text=True)
        pids = [p for p, comm in (l.split(None, 1) for l in ps.stdout.splitlines()
                                  if len(l.split(None, 1)) == 2)
                if Path(comm.strip()).name == "claude"]
        if not pids:
            return []
        lsof = subprocess.run(["lsof", "-a", "-d", "cwd", "-Fpn", "-p", ",".join(pids)],
                              capture_output=True, text=True)
    except FileNotFoundError:
        return []
    cible, trouves, pid = str(Path(dossier).resolve()), [], None
    for ligne in lsof.stdout.splitlines():
        if ligne.startswith("p"):
            pid = int(ligne[1:])
        elif ligne.startswith("n") and ligne[1:] == cible and pid is not None:
            trouves.append(pid)
    return trouves


def commande(projet: Path, manifeste: Manifeste, role: str, equipe: str | None,
             tache: str | None, modele: str | None, reprise: str | None = None):
    """(session, dossier de travail, variables d'environnement, ligne `claude`).

    `--settings` désigne le fichier généré au lancement (voir `ecrire_reglages_generes`) ;
    ici on ne vérifie que la présence du fichier statique du rôle.
    Avec `reprise` (coordinateur ou Assistant) : `--resume <id>` et pas de message d'ouverture."""
    projet = Path(projet).resolve()
    if reprise and role not in ("coord", "assistant"):
        raise Refus("--reprendre n'est accepté que pour coord et assistant")
    if role == "assistant":
        dossier = projet
        message = MESSAGE_ASSISTANT
        modele = modele or manifeste.modele_assistant
    elif role == "coord":
        equipe = _nom(equipe, "équipe")
        dossier = _dossier_equipe(projet, equipe)
        message = MESSAGE_COORDINATEUR
        modele = modele or manifeste.modele_coordinateur
    elif role == "worker":
        equipe = _nom(equipe, "équipe")
        tache = _nom(tache, "tâche")
        if not modele:
            raise ErreurProjet(
                "--modele obligatoire pour un worker : la politique de modèles "
                "des workers se décide avec l'utilisateur"
            )
        if _est_integration(role, equipe):
            # pas de worktree : l'intégration travaille dans le dépôt principal
            dossier = _dossier_equipe(projet, equipe)
            message = f"Lis {_requete(projet, tache)} et traite-la."
        else:
            dossier = worktree_equipe(projet, manifeste, equipe)
            _, en_cours = _tache_a_lancer(projet, equipe, tache)
            message = f"Lis {en_cours} et exécute-le."
    else:
        raise ErreurProjet(f"rôle inconnu : {role!r}")
    identite = _identite(role, equipe, tache)
    reglages_role = "coord" if _est_integration(role, equipe) else role
    reglages(projet, reglages_role)  # présence vérifiée tôt : refus clair si absent
    env = {VAR_AGENT: identite, VAR_PROJET: str(projet),
           "CLAUDE_CODE_TMPDIR": str(dossier_tmp(projet))}
    ligne = ["claude", "--model", modele, "--permission-mode", "auto",
             "--settings", str(fichier_reglages_generes(projet, identite))]
    ligne += ["--resume", reprise] if reprise else [message]
    if _est_integration(role, equipe):
        # une session d'intégration mesure sur des projets jetables : elle ne porte
        # jamais l'identité du vrai projet, ni celle de l'appelant, ni celle du serveur tmux
        env = {"CLAUDE_CODE_TMPDIR": env["CLAUDE_CODE_TMPDIR"]}
        ligne = ["env", "-u", VAR_AGENT, "-u", VAR_PROJET] + ligne
    return session_tmux(manifeste, identite), dossier, env, ligne


def _session_existe(session: str) -> bool:
    try:
        r = subprocess.run(["tmux", "has-session", "-t", f"={session}"],
                           capture_output=True)
    except FileNotFoundError:
        return False
    return r.returncode == 0


def _commande_tmux(session: str, dossier: Path, env: dict, ligne: list[str]) -> list[str]:
    cmd = ["tmux", "new-session", "-d", "-s", session, "-c", str(dossier)]
    for cle, valeur in env.items():
        cmd += ["-e", f"{cle}={valeur}"]
    return cmd + [shlex.join(ligne)]


def ecran_de_demarrage(capture: str) -> str | None:
    """Écran d'approbation qui bloque un agent autonome : "confiance", "imports" ou None."""
    texte = _ANSI.sub("", capture)
    if "Allow external CLAUDE.md file imports" in texte:
        return "imports"
    if "Quick safety check" in texte or "trust this folder" in texte:
        return "confiance"
    return None


def _invite_atteinte(capture: str) -> bool:
    """Ligne d'invite `❯` + espace insécable, encadrée de lignes `─`, ou agent au travail."""
    lignes = _ANSI.sub("", capture).splitlines()
    if any("esc to interrupt" in ligne for ligne in lignes):
        return True
    return any(
        ligne.startswith("❯\xa0") and 0 < i < len(lignes) - 1
        and lignes[i - 1].startswith("─") and lignes[i + 1].startswith("─")
        for i, ligne in enumerate(lignes))


def _capturer(session: str) -> str:
    r = subprocess.run(["tmux", "capture-pane", "-p", "-t", f"={session}:"],
                       capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def surveiller_demarrage(session: str, capturer=_capturer, delai: float | None = None,
                         duree: float | None = None, dormir=time.sleep) -> str | None:
    """Capture le pane jusqu'à `duree` s : "confiance", "imports", "invite" ou None.

    Ne presse aucune touche : approuver un dossier est réservé à l'utilisateur."""
    delai = DELAI_SURVEILLANCE if delai is None else delai
    duree = DUREE_SURVEILLANCE if duree is None else duree
    ecoule = 0.0
    while True:
        capture = capturer(session)
        ecran = ecran_de_demarrage(capture)
        if ecran:
            return ecran
        if _invite_atteinte(capture):
            return "invite"
        if ecoule >= duree:
            return None
        dormir(delai)
        ecoule += delai


def _conversation_a_reprendre(dossier: Path, session: str | None):
    if session is not None and not _NOM_SESSION.fullmatch(session):
        raise Refus(f"identifiant de conversation invalide : {session!r}")
    trouvee = derniere_conversation(dossier, session=session)
    sous = dossier_conversations(dossier)
    if trouvee is None:
        raise Refus(f"conversation {session} introuvable dans {sous}" if session
                    else f"aucune conversation trouvée dans {sous}")
    return trouvee, sous / f"{trouvee}.jsonl"


def humain_au_terminal(env=os.environ) -> bool:
    """Un humain au clavier : ni agent (CLAUDECODE, CIME_AGENT) ni sortie redirigée."""
    if env.get(VAR_AGENT) or env.get("CLAUDECODE"):
        return False
    return sys.stdin.isatty() and sys.stdout.isatty()


def _attacher(session: str) -> None:
    """Attache le terminal à la session (après l'inscription : l'exec ne revient pas)."""
    sys.stdout.flush()
    if os.environ.get("TMUX"):
        subprocess.run(["tmux", "switch-client", "-t", session])
        return
    os.execvp("tmux", ["tmux", "attach", "-t", session])


def _lancer(args, projet: Path | None = None, attacher: bool = False) -> tuple[str, int]:
    projet = (trouver_projet() if projet is None else Path(projet)).resolve()
    manifeste = lire_manifeste(projet)
    role, equipe, tache = args.role, args.equipe, args.tache
    if role != "worker":
        tache = None
    if role == "assistant":
        equipe = None
    else:
        _verifier_equipe(projet, _nom(equipe, "équipe"))
    reprendre = getattr(args, "reprendre", False)
    session_id = getattr(args, "session", None)
    if reprendre and role not in ("coord", "assistant"):
        raise Refus("--reprendre n'est accepté que pour coord et assistant")
    if session_id and not reprendre:
        raise Refus("--session n'a de sens qu'avec --reprendre")
    reprise = fichier = None
    if reprendre:
        dossier_conv = projet if role == "assistant" else _dossier_equipe(projet, equipe)
        reprise, fichier = _conversation_a_reprendre(dossier_conv, session_id)
    session, dossier, env, ligne = commande(
        projet, manifeste, role, equipe, tache, args.modele, reprise)
    if not dossier.is_dir():
        if role == "worker":
            raise ErreurProjet(
                f"worktree absent : {dossier} — c'est l'Assistant qui crée la "
                "branche et le worktree d'une équipe")
        raise ErreurProjet(f"dossier de travail absent : {dossier}")
    integration = _est_integration(role, equipe)
    reprise_tache = False
    if integration:
        requete = _requete(projet, tache)
        if not requete.is_file():
            raise ErreurProjet(f"requête absente : {requete}")
    elif role == "worker":
        todo, en_cours = _tache_a_lancer(projet, equipe, tache)
        if tache_orpheline(projet, manifeste, equipe, tache):
            from cime.fondation import fermeture
            if fermeture.est_ferme(projet):
                raise Refus("projet fermé : rouvrir d'abord")
            reprise_tache = True
        else:
            if not todo.is_file():
                raise ErreurProjet(f"tâche absente : {todo}")
            if en_cours.exists():
                raise ErreurProjet(f"tâche déjà en cours : {en_cours}")
    if reprendre:
        if _session_existe(session):
            raise Refus(f"session {session} encore lancée : fermer d'abord l'ancienne session")
        pids = processus_claude_dans(dossier)
        if pids:
            raise Refus(
                f"la conversation {reprise} est encore ouverte : processus claude "
                f"{', '.join(map(str, pids))} dans {dossier} — fermer d'abord l'ancienne session")
    elif _session_existe(session):
        raise ErreurProjet(
            f"session {session} déjà lancée : un coordinateur garde la même "
            "session toute sa vie")
    cmd = _commande_tmux(session, dossier, env, ligne)
    identite = _identite(role, equipe, tache)
    role_reglages = "coord" if integration else role
    contenu = None
    if role != "assistant":   # l'Assistant ne tourne pas dans le bac à sable
        contenu = contenu_reglages_generes(projet, identite, role_reglages, manifeste, integration)
    if args.essai_a_blanc:
        print(shlex.join(cmd))
        if contenu is not None:  # verdict statique seul : rien n'est lancé
            try:
                verifier_import_cime(contenu["sandbox"], Path(os.path.realpath(_paquet_cime())),
                                     sys.path)
                print("autotest import cime (statique) : ok")
            except Refus as e:
                print(f"autotest import cime (statique) : refus — {e}")
        if reprendre:
            print(f"conversation : {reprise}\nfichier : {fichier}")
        return session, 0
    if contenu is not None:   # avant toute écriture : un refus ne laisse rien derrière lui
        verifier_import_cime(contenu["sandbox"], *sonder_import_cime(python_de_l_outil()))
    ecrire_reglages_generes(projet, identite, role_reglages, manifeste, integration, contenu)
    deplace = role == "worker" and not integration and not reprise_tache
    if deplace:
        en_cours.parent.mkdir(parents=True, exist_ok=True)
        todo.rename(en_cours)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        if deplace:
            en_cours.rename(todo)
        raise ErreurProjet(f"tmux a échoué : {r.stderr.strip()}")
    if reprise_tache:
        from cime.fondation import fermeture
        auteur = getattr(args, "auteur", None) or fermeture.AUTEUR
        fermeture._noter(projet, "TacheReprise", "reprendre_tache",
                         {"equipe": equipe, "tache": tache, "auteur": auteur}, auteur=auteur)
    print(session)
    ecran = surveiller_demarrage(session)
    attacher = attacher and not getattr(args, "detache", False)
    if ecran in _LIBELLES:
        suite = "le terminal s'y attache" if attacher else f"à faire une fois : tmux attach -t {session}"
        print(f"lancer : {session} attend une approbation de l'utilisateur "
              f"({_LIBELLES[ecran]}) — {suite}", file=sys.stderr)
        if attacher:
            _attacher(session)
        return session, CODE_APPROBATION
    if ecran is None:
        print(f"lancer : {session} : écran non reconnu après "
              f"{DUREE_SURVEILLANCE:g} s", file=sys.stderr)
    if attacher and role == "assistant":
        _attacher(session)
    return session, 0


def _demarrer_facteur(projet: Path | None = None) -> None:
    """Le facteur du projet est démarré par le premier lancement d'agent s'il est absent,
    avant d'inscrire ou d'exécuter quoi que ce soit. Ne bloque jamais le lancement."""
    from cime.signaux import vie
    try:
        vie.demarrer_si_absent(projet if projet is not None else trouver_projet())
    except ErreurProjet:
        pass


def executer(args) -> int:
    from cime.signaux.identite import ErreurIdentite, appelant
    try:
        moi = appelant()
    except ErreurIdentite as e:
        print(f"lancer : {e}", file=sys.stderr)
        return CODE_REFUS
    try:
        if moi != "utilisateur" and not getattr(args, "essai_a_blanc", False):
            # un agent n'ouvre pas de terminal : préconditions, puis un ordre pour le facteur
            from cime.signaux import ordres
            from cime.signaux.commandes import lancer_commande
            return lancer_commande("lancer", lambda a: ordres.lancer_par_agent(moi, a), args)
        if not getattr(args, "essai_a_blanc", False):
            _demarrer_facteur()
        return _lancer(args, attacher=humain_au_terminal())[1]
    except Refus as e:
        print(f"lancer : {e}", file=sys.stderr)
        return CODE_REFUS
    except ErreurProjet as e:
        print(f"lancer : {e}", file=sys.stderr)
        return 1


def lancer_assistant(projet: Path, modele: str | None = None) -> tuple[str, int]:
    """Lance l'Assistant de `projet` comme `lancer assistant`, sans dépendre des variables
    d'environnement de l'appelant (VAR_PROJET, VAR_AGENT) : (session, code de sortie)."""
    projet = Path(projet).resolve()
    args = argparse.Namespace(role="assistant", equipe=None, tache=None, modele=modele,
                              essai_a_blanc=False, reprendre=False, session=None)
    try:
        _demarrer_facteur(projet)
        return _lancer(args, projet)
    except ErreurProjet as e:
        print(f"lancer : {e}", file=sys.stderr)
        return "", CODE_REFUS if isinstance(e, Refus) else 1
