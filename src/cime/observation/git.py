"""Lecture de git : fichiers touchés, périmètre, recouvrements, retard sur la base.

Lecture seule : seules `rev-parse`, `diff --name-only`, `rev-list` et `log` sont lancées.
Les branches d'équipe sont lues dans le dépôt principal (les worktrees en partagent
les références). Limite acceptée : un fichier modifié mais non commité dans un
worktree n'est pas vu, puisque seule la branche commitée est comparée.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

NOM_SOURCE = "git"
_DELAI_S = 2


def _git(racine: Path, *args: str) -> str | None:
    """Sortie standard d'une commande git, ou None si elle échoue (jamais d'exception)."""
    try:
        res = subprocess.run(
            ["git", "-C", str(racine), *args],
            capture_output=True,
            text=True,
            timeout=_DELAI_S,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if res.returncode != 0:
        return None
    return res.stdout


def est_dans_perimetre(fichier: str, perimetre: list[str]) -> bool:
    """Pure. Préfixe de chemin terminé par '/' = dossier ; sinon fichier exact."""
    for prefixe in perimetre:
        if prefixe.endswith("/"):
            if fichier.startswith(prefixe):
                return True
        elif fichier == prefixe:
            return True
    return False


def _iso_utc(texte: str) -> str | None:
    """Date git `%cI` (avec décalage) → ISO 8601 UTC à la milliseconde."""
    try:
        dt = datetime.fromisoformat(texte.strip()).astimezone(timezone.utc)
    except ValueError:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _premieres_dates(racine: Path, reference: str, ref: str) -> dict[str, str] | None:
    """Pour chaque fichier, date (committer) du premier commit de la branche depuis la base qui le touche."""
    sortie = _git(racine, "log", "--reverse", "--format=%x01%cI", "--name-only", "-z", f"{reference}..{ref}")
    if sortie is None:
        return None
    dates: dict[str, str] = {}
    date = None
    for jeton in sortie.split("\0"):
        jeton = jeton.strip("\n")
        if jeton.startswith("\x01"):  # en-tête d'un commit : sa date
            date = _iso_utc(jeton[1:])
        elif jeton and date and jeton not in dates:
            dates[jeton] = date
    return dates


def _plus_ancien_retard(racine: Path, reference: str, ref: str) -> str | None:
    """Date du plus ancien commit de la base absent de la branche."""
    sortie = _git(racine, "log", "--format=%cI", f"{ref}..{reference}")
    if not sortie:
        return None
    dates = [d for d in map(_iso_utc, sortie.split()) if d]
    return min(dates) if dates else None


def _echec(erreur: str) -> tuple[None, dict]:
    return None, {"nom": NOM_SOURCE, "ok": False, "erreur": erreur}


def _lire_equipe(racine: Path, reference: str, branche: str | None, perimetre: list[str] | None) -> dict:
    vide = {
        "branche": branche,
        "commit": None,
        "fichiers_touches": None,
        "hors_perimetre": None,
        "retard_sur_base": None,
        "en_avance_sur_base": None,
        "dates_fichiers": None,
        "retard_depuis": None,
    }
    if not branche:
        return vide
    ref = f"refs/heads/{branche}"
    if _git(racine, "rev-parse", "--verify", "--quiet", ref) is None:
        return vide
    commit = _git(racine, "rev-parse", "--short", ref)
    sortie = _git(racine, "diff", "--name-only", "-z", f"{reference}...{ref}")
    retard = _git(racine, "rev-list", "--count", f"{ref}..{reference}")
    avance = _git(racine, "rev-list", "--count", f"{reference}..{ref}")
    fichiers = sorted(f for f in sortie.split("\0") if f) if sortie is not None else None
    hors = None
    if fichiers is not None and perimetre is not None:
        hors = [f for f in fichiers if not est_dans_perimetre(f, perimetre)]
    try:
        retard_n = int(retard.strip()) if retard is not None else None
    except ValueError:
        retard_n = None
    try:
        avance_n = int(avance.strip()) if avance is not None else None
    except ValueError:
        avance_n = None
    return {
        "branche": branche,
        "commit": commit.strip() if commit else None,
        "fichiers_touches": fichiers,
        "hors_perimetre": hors,
        "retard_sur_base": retard_n,
        "en_avance_sur_base": avance_n,
        "dates_fichiers": _premieres_dates(racine, reference, ref),
        "retard_depuis": _plus_ancien_retard(racine, reference, ref) if retard_n else None,
    }


def lire_git(racine: Path, reference: str, equipes: list[dict]) -> tuple[dict | None, dict]:
    """source nom = "git". `equipes` : [{"nom", "branche" (str | None), "perimetre_declare": [...] | None}].

    Renvoie
    {"equipes": {"<nom>": {"branche", "commit", "fichiers_touches", "hors_perimetre",
                           "retard_sur_base", "en_avance_sur_base" (commits de la branche
                           absents de la base),
                           "dates_fichiers": {fichier: date ISO UTC du premier commit de la
                                              branche (depuis la base) qui le touche} | None,
                           "retard_depuis": date du plus ancien commit de la base absent
                                            de la branche | None}},
     "recouvrements": [{"fichier", "equipes": [noms triés], "depuis": la plus récente des
                        dates_fichiers des équipes | None}]}
    Une équipe sans branche ou dont la branche n'existe pas : valeurs None, et la
    source reste ok. Dépôt git absent ou référence introuvable : source en échec.
    """
    try:
        if _git(racine, "rev-parse", "--git-dir") is None:
            return _echec(f"{racine} n'est pas un dépôt git lisible")
        if _git(racine, "rev-parse", "--verify", "--quiet", f"{reference}^{{commit}}") is None:
            return _echec(f"référence git introuvable : {reference}")
        resultat: dict[str, dict] = {}
        par_fichier: dict[str, set[str]] = {}
        for eq in equipes:
            nom = eq["nom"]
            info = _lire_equipe(racine, reference, eq.get("branche"), eq.get("perimetre_declare"))
            resultat[nom] = info
            for f in info["fichiers_touches"] or []:
                par_fichier.setdefault(f, set()).add(nom)
        recouvrements = []
        for f, noms in sorted(par_fichier.items()):
            if len(noms) > 1:
                # le recouvrement naît avec le second commit : la plus récente des premières dates
                dates = [(resultat[n]["dates_fichiers"] or {}).get(f) for n in noms]
                depuis = max(dates) if all(dates) else None
                recouvrements.append({"fichier": f, "equipes": sorted(noms), "depuis": depuis})
        return {"equipes": resultat, "recouvrements": recouvrements}, {"nom": NOM_SOURCE, "ok": True}
    except Exception as e:  # noqa: BLE001 — le collecteur ne lève jamais
        return _echec(f"lecture git impossible : {e}")
