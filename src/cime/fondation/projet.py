"""Manifeste d'un projet (`.orga/projet.toml`), recherche de sa racine et validation des identités d'agents."""

import os
import re
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

from cime.fondation.nom import VAR_PROJET


class ErreurProjet(Exception):
    pass


def _manifeste(racine: Path) -> Path:
    return racine / ".orga" / "projet.toml"


def sous_worktrees(dossier: Path) -> bool:
    """Vrai si `dossier` est sous un `.orga/worktrees/` : la copie de `projet.toml` qu'un
    worktree d'équipe porte n'est jamais un projet."""
    parties = Path(dossier).parts
    return any(parties[i:i + 2] == (".orga", "worktrees") for i in range(len(parties) - 1))


def est_un_projet(dossier: Path) -> bool:
    """Un `.orga/projet.toml` lisible, ailleurs que sous un `.orga/worktrees/`."""
    return _manifeste(Path(dossier)).is_file() and not sous_worktrees(Path(dossier))


def trouver_projet(depart: Path | None = None) -> Path:
    env = os.environ.get(VAR_PROJET)
    if env and est_un_projet(Path(env)):
        return Path(env)
    depart = Path(depart) if depart is not None else Path.cwd()
    # Un agent d'un worktree remonte jusqu'au vrai projet, ou échoue : « pas de projet ».
    for dossier in (depart, *depart.parents):
        if est_un_projet(dossier):
            return dossier
    raise ErreurProjet(
        f"aucun projet trouvé : ni ${VAR_PROJET} ni .orga/projet.toml "
        f"en remontant depuis {depart}"
    )


@dataclass(frozen=True)
class Manifeste:
    nom: str
    prefixe: str
    branche_reference: str
    branche_equipe: str
    worktree_equipe: str
    equipes_speciales: list[str]
    modele_assistant: str
    modele_coordinateur: str
    # sites permis aux commandes des agents (réseau) : `[bac_a_sable] sites`, optionnel
    sites: list[str] = field(default_factory=list)
    # contrats que le projet suit : `[contrats] <nom> = ["<équipe lectrice>", …]`, optionnel
    contrats: dict[str, list[str]] = field(default_factory=dict)
    # workers actifs en même temps sur la machine : `[charge] workers_max`, optionnel, au moins 1
    workers_max: int = 1


def _contrats(donnees: dict, fichier: Path) -> dict[str, list[str]]:
    table = donnees.get("contrats", {})
    if not isinstance(table, dict):
        raise ErreurProjet(f"[contrats] doit être une table ({fichier})")
    for nom, lectrices in table.items():
        if not isinstance(lectrices, list) or not all(
                isinstance(e, str) and e.strip() for e in lectrices):
            raise ErreurProjet(
                f"contrats.{nom} doit être une liste de noms d'équipe (chaînes non vides) ({fichier})")
    return {nom: list(lectrices) for nom, lectrices in table.items()}


def _sites(donnees: dict, fichier: Path) -> list[str]:
    table = donnees.get("bac_a_sable", {})
    if not isinstance(table, dict):
        raise ErreurProjet(f"[bac_a_sable] doit être une table ({fichier})")
    sites = table.get("sites", [])
    if not isinstance(sites, list) or not all(
            isinstance(s, str) and s.strip() for s in sites):
        raise ErreurProjet(
            f"bac_a_sable.sites doit être une liste de chaînes non vides ({fichier})")
    return sites


def _workers_max(donnees: dict, fichier: Path) -> int:
    table = donnees.get("charge", {})
    if not isinstance(table, dict):
        raise ErreurProjet(f"[charge] doit être une table ({fichier})")
    valeur = table.get("workers_max", 1)
    if isinstance(valeur, bool) or not isinstance(valeur, int) or valeur < 1:
        raise ErreurProjet(
            f"charge.workers_max doit être un entier au moins égal à 1 ({fichier})")
    return valeur


def lire_manifeste(projet: Path) -> Manifeste:
    fichier = _manifeste(Path(projet))
    try:
        with open(fichier, "rb") as f:
            donnees = tomllib.load(f)
    except FileNotFoundError:
        raise ErreurProjet(f"manifeste introuvable : {fichier}") from None
    except tomllib.TOMLDecodeError as e:
        raise ErreurProjet(f"manifeste illisible ({fichier}) : {e}") from None
    valeurs = {}
    for champ in fields(Manifeste):
        if champ.name in ("sites", "contrats", "workers_max"):
            continue
        if champ.name not in donnees:
            raise ErreurProjet(
                f"clé manquante : ajoutez `{champ.name}` dans {fichier}"
            )
        valeurs[champ.name] = donnees[champ.name]
    valeurs["sites"] = _sites(donnees, fichier)
    valeurs["contrats"] = _contrats(donnees, fichier)
    valeurs["workers_max"] = _workers_max(donnees, fichier)
    return Manifeste(**valeurs)


_MOTIF_SEGMENT = r"[a-z0-9-]+"
_IDENTITE = re.compile(
    rf"(assistant|utilisateur|coord-{_MOTIF_SEGMENT}|worker-{_MOTIF_SEGMENT})"
)


_IDENTITES_VALIDES = "assistant, utilisateur, coord-<équipe>, worker-<équipe>-<tâche>"


def valider_identite(s: str, emetteur: bool = False) -> str:
    """`cime` (le code lui-même) n'est valide que comme émetteur."""
    if emetteur and s == "cime":
        return s
    if not isinstance(s, str) or not _IDENTITE.fullmatch(s):
        raise ValueError(f"identité invalide : {s!r} (attendu : {_IDENTITES_VALIDES})")
    if s.startswith("worker-") and "-" not in s[len("worker-"):]:
        raise ValueError(f"identité invalide (worker-<équipe>-<tâche>) : {s!r}")
    return s


def session_tmux(manifeste: Manifeste, identite: str) -> str | None:
    if identite == "utilisateur":
        return None
    return f"{manifeste.prefixe}-{identite}"


def equipe_de(projet: Path, identite: str) -> str | None:
    if identite.startswith("coord-"):
        return identite[len("coord-"):]
    if identite.startswith("worker-"):
        dossier = Path(projet) / ".orga" / "teams"
        if not dossier.is_dir():
            return None
        candidates = [
            d.name
            for d in dossier.iterdir()
            if d.is_dir() and identite.startswith(f"worker-{d.name}-")
        ]
        return max(candidates, key=len) if candidates else None
    return None


def branche_equipe(m: Manifeste, equipe: str) -> str:
    return m.branche_equipe.format(equipe=equipe)


def worktree_equipe(projet: Path, m: Manifeste, equipe: str) -> Path:
    projet = Path(projet)
    chemin = m.worktree_equipe.format(depot=projet.name, equipe=equipe)
    return (projet / chemin).resolve()
