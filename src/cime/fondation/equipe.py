"""`equipe` : crée le dossier, la branche et le worktree d'une équipe, sans la lancer."""
import os
import re
import subprocess
import sys
from pathlib import Path

from cime.fondation.envoyer import _projet
from cime.fondation.nom import NOM, VAR_AGENT, VAR_PROJET
from cime.fondation.projet import (branche_equipe, lire_manifeste, trouver_projet,
                                   valider_identite, worktree_equipe)
from cime.fondation.registre import inscrire_evenement, ouvrir

SOUS_DOSSIERS = ("conversations", "reports", "tasks/todo", "tasks/in-progress", "tasks/done")
GABARIT_CLAUDE = Path(".orga/templates/coordinateur-CLAUDE.md")
GABARIT_MANDAT = Path(".orga/socle/gabarits/mandat.md")
_NOM = re.compile(r"[a-z0-9-]+")
_EN_TETE = re.compile(r"\A(?:<!--.*?-->\s*)+", re.DOTALL)


class ErreurEquipe(Exception):
    pass


def _git(projet: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(projet), *args], capture_output=True, text=True)


def _worktrees(projet: Path) -> set[Path]:
    r = _git(projet, "worktree", "list", "--porcelain")
    if r.returncode != 0:
        raise ErreurEquipe(f"{projet} n'est pas un dépôt git : {r.stderr.strip()}")
    return {Path(ligne[len("worktree "):]).resolve()
            for ligne in r.stdout.splitlines() if ligne.startswith("worktree ")}


def _branche_existe(projet: Path, branche: str) -> bool:
    return _git(projet, "show-ref", "--verify", "--quiet", f"refs/heads/{branche}").returncode == 0


def _contenu_mandat(gabarit: str, equipe: str) -> str:
    return _EN_TETE.sub("", gabarit).replace("<équipe>", equipe)


def creer(projet: Path, equipe: str, essai: bool = False) -> dict[str, list[str]]:
    manifeste = lire_manifeste(projet)
    if not _NOM.fullmatch(equipe):
        raise ErreurEquipe(f"nom d'équipe invalide : {equipe!r} (attendu : [a-z0-9-]+)")
    if equipe == "utilisateur":
        raise ErreurEquipe(f"{equipe!r} est réservé à l'identité de l'utilisateur : "
                           "ce n'est jamais un nom d'équipe")
    if equipe in manifeste.equipes_speciales:
        raise ErreurEquipe(f"{equipe!r} est une équipe spéciale : elle n'est jamais créée ici")
    dossier = projet / ".orga" / "teams" / equipe
    branche = branche_equipe(manifeste, equipe)
    chemin = worktree_equipe(projet, manifeste, equipe)
    worktrees = _worktrees(projet)
    if chemin.exists() and chemin not in worktrees:
        raise ErreurEquipe(f"{chemin} existe déjà sans être un worktree de ce dépôt : "
                           "refus de l'écraser")
    existe_branche = _branche_existe(projet, branche)
    if not existe_branche and not _branche_existe(projet, manifeste.branche_reference):
        raise ErreurEquipe(f"branche de référence introuvable : {manifeste.branche_reference}")
    textes = {}
    for nom, gabarit in (("CLAUDE.md", GABARIT_CLAUDE), ("mandate.md", GABARIT_MANDAT)):
        if not (dossier / nom).exists():
            source = projet / gabarit
            if not source.is_file():
                raise ErreurEquipe(f"gabarit du projet introuvable : {gabarit}")
            texte = source.read_text(encoding="utf-8")
            textes[nom] = (_contenu_mandat(texte, equipe) if nom == "mandate.md"
                           else texte.replace("<équipe>", equipe))
    rapport: dict[str, list[str]] = {"ajouté": [], "déjà présent": []}
    for nom in ("CLAUDE.md", "mandate.md"):
        relatif = f".orga/teams/{equipe}/{nom}"
        if nom in textes:
            if not essai:
                dossier.mkdir(parents=True, exist_ok=True)
                (dossier / nom).write_text(textes[nom], encoding="utf-8")
            rapport["ajouté"].append(relatif)
        else:
            rapport["déjà présent"].append(relatif)
    for sous in SOUS_DOSSIERS:
        relatif = f".orga/teams/{equipe}/{sous}/"
        if (dossier / sous).is_dir():
            rapport["déjà présent"].append(relatif)
            continue
        if not essai:
            (dossier / sous).mkdir(parents=True)
            (dossier / sous / ".gitkeep").touch()
        rapport["ajouté"].append(relatif)
    if existe_branche:
        rapport["déjà présent"].append(f"branche {branche}")
    else:
        if not essai:
            r = _git(projet, "branch", branche, manifeste.branche_reference)
            if r.returncode != 0:
                raise ErreurEquipe(f"création de la branche {branche} : {r.stderr.strip()}")
        rapport["ajouté"].append(f"branche {branche} (depuis {manifeste.branche_reference})")
    if chemin in worktrees:
        rapport["déjà présent"].append(f"worktree {chemin}")
    else:
        if not essai:
            r = _git(projet, "worktree", "add", str(chemin), branche)
            if r.returncode != 0:
                raise ErreurEquipe(f"worktree {chemin} : {r.stderr.strip()}")
        rapport["ajouté"].append(f"worktree {chemin}")
    return rapport


def _journaliser_refus(projet: Path, de: str, equipe: str) -> None:
    """Un événement, pas un message : le coordinateur n'existe pas, personne ne lira ceci."""
    conn = ouvrir(projet)
    try:
        inscrire_evenement(conn, agent=None, session_id=None, evenement="EquipeRefusee",
                           details={"equipe": equipe, "auteur": de,
                                    "motif": "création d'équipe réservée à l'Assistant"})
    finally:
        conn.close()


def _journaliser(projet: Path, de: str, equipe: str) -> int:
    """Événement `EquipeCreee` (équipe, auteur, mandat). L'ouverture du coordinateur est la consigne
    `objet=ouverture` que `lancer coord` inscrira : la création n'est pas un message."""
    conn = ouvrir(projet)
    try:
        return inscrire_evenement(conn, agent=None, session_id=None, evenement="EquipeCreee",
                                  details={"equipe": equipe, "auteur": de,
                                           "mandat": f".orga/teams/{equipe}/mandate.md"})
    finally:
        conn.close()


def executer(args) -> int:
    blanc = args.essai_a_blanc
    de = None
    try:
        if blanc:
            projet = trouver_projet()
        else:
            de = os.environ.get(VAR_AGENT)
            if not de:
                raise ErreurEquipe(f"{VAR_AGENT} absent : lance cette commande depuis un agent "
                                   "lancé par `cime lancer`")
            projet = _projet()
            if projet is None:
                raise ErreurEquipe(f"{VAR_PROJET} absent (ou ne désigne pas un projet) : lance "
                                   "cette commande depuis un agent lancé par `cime lancer`")
            try:
                valider_identite(de)
                valider_identite(f"coord-{args.nom}")
            except ValueError as e:
                raise ErreurEquipe(str(e))
            if de != "assistant":
                _journaliser_refus(projet, de, args.nom)
                raise ErreurEquipe("seul l'Assistant crée une équipe")
        rapport = creer(projet, args.nom, essai=blanc)
    except ErreurEquipe as e:
        print(f"{NOM} equipe : {e}", file=sys.stderr)
        return 2
    titres = {"ajouté": "serait ajouté" if blanc else "ajouté",
              "déjà présent": "déjà présent"}
    for titre, lignes in rapport.items():
        if lignes:
            print(f"{titres[titre]} :")
            for ligne in lignes:
                print(f"  {ligne}")
    if blanc:
        print("\n(essai à blanc : rien n'a été touché)")
    else:
        print(f"\nSuite : remplis .orga/teams/{args.nom}/mandate.md, puis l'Assistant lance "
              f"le coordinateur : {NOM} lancer coord {args.nom}")
        if rapport["ajouté"]:
            print(f"inscrit : événement #{_journaliser(projet, de, args.nom)} (EquipeCreee)")
    return 0
