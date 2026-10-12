"""Lecture de la structure d'un projet équipé : manifeste, étapes, équipes.

Le module ne connaît du projet que ce que celui-ci déclare dans `.orga/`.
Aucune fonction n'écrit ni ne lève : un échec renvoie `(None, source en échec)`.
"""

import os
import re
import tomllib
import unicodedata
from pathlib import Path

CLES_OBLIGATOIRES = ("nom", "prefixe", "branche_reference", "branche_equipe", "worktree_equipe")
EQUIPES_ECARTEES = {"socle"}
PREFIXE_MISSION = "Mission de cette équipe dans le produit :"

_ETAPE_FAITE = re.compile(r"^- \[x\] (.+?) \(atteinte le (\d{4}-\d{2}-\d{2})\)\s*$")
_ETAPE_A_FAIRE = re.compile(r"^- \[ \] (.+?)\s*$")


def _ok(nom: str) -> dict:
    return {"nom": nom, "ok": True}


def _echec(nom: str, erreur: str) -> tuple[None, dict]:
    return None, {"nom": nom, "ok": False, "erreur": erreur}


def _lire_etapes(fichier: Path) -> list[dict] | None:
    try:
        lignes = fichier.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    etapes = []
    for ligne in lignes:
        if m := _ETAPE_FAITE.match(ligne):
            etapes.append({"nom": m.group(1), "atteinte": True, "date": m.group(2)})
        elif m := _ETAPE_A_FAIRE.match(ligne):
            etapes.append({"nom": m.group(1), "atteinte": False, "date": None})
    return etapes


def lire_projet(racine: Path) -> tuple[dict | None, dict]:
    nom = "manifeste"
    try:
        racine = Path(racine).resolve()
        manifeste = racine / ".orga" / "projet.toml"
        if not manifeste.is_file():
            return _echec(
                nom,
                f"manifeste absent : créer {manifeste} avec les clés "
                + ", ".join(CLES_OBLIGATOIRES),
            )
        try:
            brut = tomllib.loads(manifeste.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
            return _echec(nom, f"manifeste illisible ({manifeste}) : {e}")
        for cle in CLES_OBLIGATOIRES:
            if cle not in brut:
                return _echec(nom, f"clé manquante : ajouter `{cle}` à {manifeste}")
            if not isinstance(brut[cle], str):
                return _echec(nom, f"clé `{cle}` invalide dans {manifeste} : texte attendu")
        speciales = brut.get("equipes_speciales", [])
        if not isinstance(speciales, list) or not all(isinstance(s, str) for s in speciales):
            return _echec(nom, f"clé `equipes_speciales` invalide dans {manifeste} : liste de textes attendue")
        projet = {cle: brut[cle] for cle in CLES_OBLIGATOIRES}
        projet["racine"] = str(racine)
        projet["equipes_speciales"] = list(speciales)
        for cle in ("modele_assistant", "modele_coordinateur"):
            val = brut.get(cle)
            projet[cle] = val if isinstance(val, str) else None
        projet["etapes"] = _lire_etapes(racine / ".orga" / "etapes.md")
        return projet, _ok(nom)
    except Exception as e:  # garde-fou : la fonction ne lève jamais
        return _echec(nom, f"lecture du manifeste impossible : {e}")


_ETIQUETTE = re.compile(r"^[A-ZÀ-Ý][^:`]{0,40} : ")


def _ligne_logique(lignes: list[str], debut: int) -> str:
    """La ligne `debut` et ses continuations (lignes non vides qui ne sont ni titre, ni puce, ni étiquette)."""
    morceaux = [lignes[debut].strip()]
    for suivante in lignes[debut + 1:]:
        if (not suivante.strip() or suivante.startswith(("#", "- ", "* "))
                or _ETIQUETTE.match(suivante)):
            break
        morceaux.append(suivante.strip())
    return " ".join(morceaux)


def _normaliser(texte: str) -> str:
    sans = unicodedata.normalize("NFD", texte)
    return "".join(c for c in sans if not unicodedata.combining(c)).casefold()


def _mission(lignes: list[str]) -> str | None:
    for i, ligne in enumerate(lignes):
        if ligne.startswith("## Bloc 2"):
            for j in range(i + 1, len(lignes)):
                if lignes[j].strip():
                    texte = _ligne_logique(lignes, j)
                    texte = texte.removeprefix(PREFIXE_MISSION).replace("**", "").strip()
                    return texte or None
            return None
    return None


def _perimetre(lignes: list[str]) -> list[str] | None:
    for i, ligne in enumerate(lignes):
        if ligne.startswith("Scope :"):
            jetons = re.findall(r"`([^`]+)`", _ligne_logique(lignes, i))
            return [j for j in jetons if "/" in j or "." in j]
    return None


def _compter(dossier: Path) -> list[str] | None:
    try:
        return sorted(p.name for p in dossier.iterdir() if p.is_file() and not p.name.startswith("."))
    except OSError:
        return None


def _avancement(equipe_dir: Path) -> tuple[dict | None, list[str] | None]:
    tasks = equipe_dir / "tasks"
    if not tasks.is_dir():
        return None, None
    noms = {}
    for cle, sous in (("faites", "done"), ("en_cours", "in-progress"), ("a_faire", "todo")):
        noms[cle] = _compter(tasks / sous) if (tasks / sous).is_dir() else []
        if noms[cle] is None:
            return None, None
    avancement = {cle: len(v) for cle, v in noms.items()}
    en_cours = [n.removesuffix(".md") for n in noms["en_cours"]]
    return avancement, en_cours


def _dependances(fichier: Path, existantes: list[str]) -> dict[str, list[str]] | None:
    try:
        lignes = fichier.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    sections: dict[str, list[str]] = {}
    courante = None
    for i, ligne in enumerate(lignes):
        if ligne.startswith("## "):
            courante = ligne[3:].strip()
            sections.setdefault(courante, [])
        elif courante is not None and ligne.startswith("Dépend de :") and not sections[courante]:
            prose = _normaliser(_ligne_logique(lignes, i).removeprefix("Dépend de :"))
            trouvees = []
            for nom in existantes:
                m = re.search(rf"(?<![\w-]){re.escape(_normaliser(nom))}(?![\w-])", prose)
                if m:
                    trouvees.append((m.start(), nom))
            sections[courante] = [n for _, n in sorted(trouvees)]
    return sections


_HEURE_CLOTURE = re.compile(r"^heure:\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z)\s*$", re.MULTILINE)


def _cloturee_le(fichier: Path) -> str | None:
    """Horodatage de la ligne `heure: …` que l'hôte écrit dans CLOTUREE ; None si absent ou illisible."""
    try:
        m = _HEURE_CLOTURE.search(fichier.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None
    return m.group(1) if m else None


def lire_equipes(racine: Path, projet: dict) -> tuple[list[dict] | None, dict]:
    nom = "equipes"
    try:
        racine = Path(racine).resolve()
        teams = racine / ".orga" / "teams"
        if not teams.is_dir():
            return _echec(nom, f"dossier des équipes absent : {teams}")
        speciales = projet.get("equipes_speciales") or []
        dossiers = sorted(
            d for d in teams.iterdir()
            if d.is_dir() and d.name not in EQUIPES_ECARTEES and (d / "mandate.md").is_file()
        )
        noms = [d.name for d in dossiers]
        deps = _dependances(racine / ".orga" / "dependencies.md", noms)
        equipes = []
        for d in dossiers:
            try:
                lignes = (d / "mandate.md").read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                lignes = None
            speciale = d.name in speciales
            avancement, en_cours = _avancement(d)
            branche = worktree = None
            if not speciale:
                branche = projet["branche_equipe"].format(equipe=d.name)
                chemin = projet["worktree_equipe"].format(depot=racine.name, equipe=d.name)
                worktree = os.path.normpath(racine / chemin)
            equipes.append({
                "nom": d.name,
                "speciale": speciale,
                "mission": _mission(lignes) if lignes is not None else None,
                "perimetre_declare": _perimetre(lignes) if lignes is not None else None,
                "branche": branche,
                "worktree": worktree,
                "avancement": avancement,
                "taches_en_cours": en_cours,
                "cloturee": (d / "CLOTUREE").exists(),
                "cloturee_le": _cloturee_le(d / "CLOTUREE"),
                "depend_de": None if deps is None else deps.get(d.name, []),
            })
        return equipes, _ok(nom)
    except Exception as e:  # garde-fou : la fonction ne lève jamais
        return _echec(nom, f"lecture des équipes impossible : {e}")


_DECISION = re.compile(r"^## (\d{4}-\d{2}-\d{2}) — (.+?)\s*$")
_NB_DECISIONS = 10


def lire_decisions(racine: Path) -> list[dict] | None:
    """Les 10 dernières entrées datées (`## AAAA-MM-JJ — titre`) de `.orga/contracts/CHANGELOG.md`,
    de la plus récente à la plus ancienne (le fichier s'écrit dans l'ordre chronologique).
    Fichier absent ou illisible : None."""
    try:
        with open(racine / ".orga" / "contracts" / "CHANGELOG.md", encoding="utf-8") as f:
            entrees = [{"date": m.group(1), "titre": m.group(2)} for ligne in f if (m := _DECISION.match(ligne))]
    except (OSError, UnicodeDecodeError):
        return None
    return entrees[-_NB_DECISIONS:][::-1]
