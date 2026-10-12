"""Périmètre : refuse les outils de fichiers dont le chemin sort du projet.

`decider(entree, projet)` reçoit le JSON d'un hook `PreToolUse` et retourne un
motif (refus) ou `None`. Il ne lève jamais.

Le bac à sable de Claude Code enferme Bash, pas Read, Write, Edit, NotebookEdit,
Glob ni Grep : c'est ce module qui les contrôle.

Par équipe : un `coord-<équipe>` ou un `worker-<équipe>-<tâche>` n'écrit que dans
son dossier `.orga/teams/<équipe>/`, dans le worktree de son équipe (sous
`.orga/worktrees/<équipe>/`), dans les requêtes à l'intégration et dans les dossiers de
travail de Claude Code du projet, où la mémoire n'est écrivable que sous le nom de son
identité (`.orga/etat/memoire/<identité>/`). Il lit tout le projet, et les transcriptions
de ce projet dans `~/.claude/projects/`.

Aucun appel à `git` : le périmètre est le dossier du projet, worktrees compris.
"""
import os
import re
from pathlib import Path

from cime.fondation.nom import VAR_AGENT
from cime.fondation.projet import equipe_de, lire_manifeste, worktree_equipe

CHAMPS = ("file_path", "path", "notebook_path", "directory")

# Outils qui écrivent. Les outils de lecture sont listés ; un outil inconnu qui porte
# un chemin est traité comme une écriture, par prudence.
OUTILS_ECRITURE = {"Write", "Edit", "NotebookEdit"}
OUTILS_LECTURE = {"Read", "Glob", "Grep"}

# Chemins hors du projet acceptés. Vide pour l'instant : chaque ajout doit être justifié
# par une mesure, et c'est l'utilisateur qui valide la liste.
EXCEPTIONS: list[Path] = []

M_HORS = ("{outil} refusé : {demande} mène hors du projet (résolu en {resolu}). "
          "Seul le dossier du projet est permis : "
          "demande à ton supérieur si tu as besoin d'autre chose.")
M_ECRITURE_EQUIPE = ("{outil} refusé : l'équipe {equipe} n'écrit que dans son dossier, "
                     "son worktree, les requêtes à l'intégration et les dossiers de travail "
                     "de Claude Code ({zones}). {demande} mène ailleurs (résolu en {resolu}). "
                     "Demande à l'Assistant si tu dois écrire ailleurs.")
M_EQUIPE_INCONNUE = ("{outil} refusé : l'équipe de {identite} est introuvable dans le projet. "
                     "Sans équipe connue, aucune écriture n'est permise.")
M_ERREUR = ("le garde de périmètre n'a pas pu vérifier ce chemin (erreur interne) : "
            "refusé par prudence.")


# Fichiers d'état réservés aux commandes `cime`.
# Les commandes les écrivent dans leur propre processus ; un agent ne les écrit ni ne les déplace.
_TACHES_RESERVEES = re.compile(r"(^|/)tasks/(in-progress|done)(/|$)")
FICHIERS_REGISTRE = ("registre.sqlite", "registre.sqlite-wal", "registre.sqlite-shm")
M_CLOTUREE = ("`CLOTUREE` ne se crée ni ne se déplace à la main : la clôture d'une équipe est "
              "faite par l'utilisateur sur la page (`cime clore <équipe>`), après ta demande_cloture et "
              "ton rapport_utilisateur.")
M_TACHES = ("les fichiers de `tasks/in-progress/` et `tasks/done/` ne s'écrivent ni ne se "
            "déplacent que par les commandes `cime` : `cime lancer worker` (todo → in-progress) "
            "et `cime terminer` (→ done).")
M_REGISTRE = ("le registre (`registre.sqlite`, `-wal`, `-shm`) ne s'écrit que par les commandes "
              "`cime` : `cime envoyer`, `cime repondre`, `cime accorder`, `cime refuser`.")


def motif_reserve(chemin: str) -> str | None:
    """Motif de refus d'une écriture sur ce chemin (déjà normalisé), ou None."""
    chemin = chemin.replace(os.sep, "/")
    nom = chemin.rsplit("/", 1)[-1]
    if nom == "CLOTUREE":
        return M_CLOTUREE
    if nom in FICHIERS_REGISTRE:
        return M_REGISTRE
    if _TACHES_RESERVEES.search(chemin):
        return M_TACHES
    return None


def _exceptions() -> list[Path]:
    return [Path(os.path.realpath(e)) for e in EXCEPTIONS]


def _base_du_pattern(pattern: str, dossier) -> str:
    """Retire les segments de caractères joker en fin ; ce qui reste est un chemin."""
    segments = pattern.split("/")
    while segments and any(c in segments[-1] for c in "*?["):
        segments.pop()
    base = "/".join(segments)
    if not base:
        base = "/" if pattern.startswith("/") else "."
    if base.startswith(("/", "~")):
        return base
    return os.path.join(dossier, base)


def _controles(entree: dict) -> list[tuple[str, str, str | None]]:
    """(demande, chemin à résoudre, cwd) pour chaque chemin à contrôler. Bash n'y est pas."""
    outil = entree.get("tool_name")
    if outil == "Bash":
        return []
    cwd = entree.get("cwd")
    tool_input = entree.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}
    controles = [(tool_input[c], tool_input[c], cwd)
                 for c in CHAMPS if tool_input.get(c) is not None]
    if outil in ("Glob", "Grep") and tool_input.get("path") is None and cwd is not None:
        controles.append((cwd, cwd, cwd))
    pattern = tool_input.get("pattern")
    if outil == "Glob" and isinstance(pattern, str) \
            and (pattern.startswith(("/", "~")) or ".." in pattern.split("/")):
        dossier = tool_input.get("path") or cwd
        controles.append((pattern, _base_du_pattern(pattern, dossier), cwd))
    return controles


def _resoudre(brut: str, cwd: str | None) -> Path:
    chemin = Path(os.path.expanduser(brut))
    if not chemin.is_absolute():
        if cwd is None:
            raise ValueError("chemin relatif sans cwd")
        chemin = Path(cwd) / chemin
    return Path(os.path.realpath(chemin))


def _identite_limitee(identite: str | None) -> bool:
    return identite is not None and identite.startswith(("coord-", "worker-"))


def _zones_ecriture(projet: Path, equipe: str, identite: str) -> list[Path]:
    """Où une équipe peut écrire. Une équipe spéciale n'a pas de worktree. La mémoire n'est
    écrivable que dans le dossier de l'identité : celle des autres est lisible, pas
    modifiable."""
    zones = [projet / ".orga" / "teams" / equipe,
             projet / ".orga" / "teams" / "integration" / "requests",
             projet / ".orga" / "etat" / "tmp",
             projet / ".orga" / "etat" / "memoire" / identite]
    manifeste = lire_manifeste(projet)
    if equipe not in manifeste.equipes_speciales:
        zones.append(worktree_equipe(projet, manifeste, equipe))
    return [Path(os.path.realpath(z)) for z in zones]


def zones_ecriture_projet(projet: Path, identite: str | None) -> list[Path] | None:
    """Dossiers où cette identité peut écrire, ou None si elle n'est pas limitée
    (Assistant, l'utilisateur, sans identité). Une équipe introuvable n'a aucune zone : `[]`.
    Source unique de la garde et du bac à sable : `reglages.bac_a_sable` les reçoit."""
    projet = Path(projet)
    if not _identite_limitee(identite):
        return None
    equipe = equipe_de(projet, identite)
    if equipe is None or not (projet / ".orga" / "teams" / equipe).is_dir():
        return []
    return _zones_ecriture(projet, equipe, identite)


def _segment(racine: Path) -> str:
    """Nom du dossier que Claude Code range sous ~/.claude/projects pour cette racine."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(racine))


def _transcription_du_projet(resolu: Path, racine: Path) -> bool:
    """Une transcription (lecture seule) de ce projet, et rien d'autre.

    Le premier segment doit être le nom du projet, ou le commencer suivi de `--` : c'est
    le dossier d'un agent lancé dans `.orga/teams/<équipe>` ou `.orga/worktrees/<équipe>`.
    """
    dossier = Path(os.path.realpath(Path.home() / ".claude" / "projects"))
    if not resolu.is_relative_to(dossier):
        return False
    parties = resolu.relative_to(dossier).parts
    if not parties:
        return False
    premier = parties[0]
    segment = _segment(racine)
    return premier == segment or premier.startswith(segment + "--")


def decider(entree: dict, projet: Path | None) -> str | None:
    try:
        if projet is None:
            return None
        controles = _controles(entree)
        if not controles:
            return None
        projet = Path(projet)
        racine = Path(os.path.realpath(projet))
        outil = entree.get("tool_name")
        ecriture = outil not in OUTILS_LECTURE
        identite = os.environ.get(VAR_AGENT) or None
        racines = [racine, *_exceptions()]
        zones = None
        if ecriture and _identite_limitee(identite):
            zones = zones_ecriture_projet(projet, identite)
            if not zones:
                return M_EQUIPE_INCONNUE.format(outil=outil, identite=identite)
            equipe = equipe_de(projet, identite)
        if ecriture:
            for demande, a_resoudre, cwd in controles:
                motif = motif_reserve(str(_resoudre(a_resoudre, cwd)))
                if motif:
                    return f"{outil} refusé : {motif}"
        for demande, a_resoudre, cwd in controles:
            resolu = _resoudre(a_resoudre, cwd)
            if zones is not None:
                if not any(resolu.is_relative_to(z) for z in zones):
                    return M_ECRITURE_EQUIPE.format(
                        outil=outil, equipe=equipe,
                        zones=", ".join(str(z) for z in zones),
                        demande=repr(demande), resolu=resolu)
                continue
            if any(resolu.is_relative_to(r) for r in racines):
                continue
            if not ecriture and _transcription_du_projet(resolu, racine):
                continue
            return M_HORS.format(outil=outil, demande=repr(demande), resolu=resolu)
        return None
    except Exception:
        # Une erreur interne ne vaut jamais autorisation.
        return M_ERREUR
