"""Lecture des transcripts Claude Code : contexte et coût estimés (côté client).

Ces chiffres sont des estimations tirées des `usage` écrits dans le transcript,
pas la facture. Le module ne lit que, et n'écrit jamais rien.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

NOM_SOURCE = "transcript"

# Fenêtres de contexte (tokens) — source : tableau « Compare models » de
# https://platform.claude.com/docs/en/about-claude/models/overview
# (anciennement docs.claude.com), consulté le 2026-10-07.
FENETRES_CONTEXTE: dict[str, int] = {
    "claude-fable-5-1": 1_000_000,
    "claude-opus-5-5": 1_000_000,
    "claude-sonnet-5-5": 1_000_000,
    "claude-haiku-4-5-20251001": 200_000,
    "claude-haiku-4-5": 200_000,
}

# Prix en USD par million de tokens — source : tableau « Model pricing » de
# https://platform.claude.com/docs/en/about-claude/pricing
# consulté le 2026-10-07. Prix API standard (hors batch, fast mode, résidence US).
# Lecture du cache : 0,05× l'entrée sur Opus 5.5, 0,025× sur Fable 5.1, 0,1× ailleurs.
_PRIX_FABLE_5_1 = {"entree": 10.0, "sortie": 50.0, "cache_5m": 12.5, "cache_1h": 20.0, "cache_lecture": 0.25}
_PRIX_OPUS_5_5 = {"entree": 4.0, "sortie": 20.0, "cache_5m": 5.0, "cache_1h": 8.0, "cache_lecture": 0.20}
_PRIX_SONNET_5_5 = {"entree": 2.0, "sortie": 10.0, "cache_5m": 2.5, "cache_1h": 4.0, "cache_lecture": 0.20}
_PRIX_HAIKU_4_5 = {"entree": 1.0, "sortie": 5.0, "cache_5m": 1.25, "cache_1h": 2.0, "cache_lecture": 0.10}
PRIX_PAR_MTOK: dict[str, dict[str, float]] = {
    "claude-fable-5-1": _PRIX_FABLE_5_1,
    "claude-opus-5-5": _PRIX_OPUS_5_5,
    "claude-sonnet-5-5": _PRIX_SONNET_5_5,
    "claude-haiku-4-5-20251001": _PRIX_HAIKU_4_5,
    "claude-haiku-4-5": _PRIX_HAIKU_4_5,
}

# Réponses d'erreur fabriquées par Claude Code, sans appel au modèle.
_MODELE_SYNTHETIQUE = "<synthetic>"

# (chemin, taille, mtime_ns) -> état ; voir _lire_etat.
_CACHE: dict[str, dict] = {}


def _iso(texte) -> str | None:
    """Normalise un horodatage en ISO 8601 UTC à la milliseconde."""
    try:
        dt = datetime.fromisoformat(str(texte).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return None
        dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    except (ValueError, TypeError):
        return None


def _entier(valeur) -> int:
    return valeur if isinstance(valeur, int) and not isinstance(valeur, bool) else 0


def _tokens(usage: dict) -> dict[str, int]:
    """Catégories de tokens d'un `usage`. Sans détail 5 min / 1 h, l'écriture de
    cache est comptée au tarif 5 min (hypothèse, le détail est absent)."""
    ecriture = _entier(usage.get("cache_creation_input_tokens"))
    detail = usage.get("cache_creation")
    if isinstance(detail, dict):
        c5 = _entier(detail.get("ephemeral_5m_input_tokens"))
        c1 = _entier(detail.get("ephemeral_1h_input_tokens"))
        if c5 + c1 == ecriture:
            return _construire(usage, c5, c1)
    return _construire(usage, ecriture, 0)


def _construire(usage: dict, c5: int, c1: int) -> dict[str, int]:
    return {
        "entree": _entier(usage.get("input_tokens")),
        "sortie": _entier(usage.get("output_tokens")),
        "cache_5m": c5,
        "cache_1h": c1,
        "cache_lecture": _entier(usage.get("cache_read_input_tokens")),
    }


def _appliquer_ligne(etat: dict, brut: bytes) -> None:
    try:
        ligne = json.loads(brut)
    except ValueError:
        return
    if not isinstance(ligne, dict):
        return
    ts = _iso(ligne.get("timestamp"))
    if ts and (etat["derniere_activite"] is None or ts > etat["derniere_activite"]):
        etat["derniere_activite"] = ts
    if ligne.get("type") != "assistant":
        return
    message = ligne.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("usage"), dict):
        return
    modele = message.get("model")
    if modele == _MODELE_SYNTHETIQUE:
        return
    identifiant = message.get("id")
    if not isinstance(identifiant, str):
        # Sans identifiant impossible de dédupliquer : clé propre à la ligne.
        identifiant = f"ligne-{etat['seq'] + 1}"
    etat["seq"] += 1
    # Même message.id sur plusieurs lignes : la dernière occurrence l'emporte.
    etat["reponses"][identifiant] = {
        "seq": etat["seq"],
        "modele": modele if isinstance(modele, str) else None,
        "sidechain": ligne.get("isSidechain") is True,
        "horodatage": ts,
        "tokens": _tokens(message["usage"]),
    }


def _lire_depuis(etat: dict, chemin: Path, debut: int, taille: int) -> dict:
    """Lit [debut, taille) ; renvoie l'état. Les lignes terminées par \\n sont
    consommées définitivement ; une dernière ligne incomplète est lue sur une
    copie (l'ajout est idempotent grâce à la déduplication) puis relue plus tard."""
    with open(chemin, "rb") as f:
        f.seek(debut)
        donnees = f.read(taille - debut)
    fin = donnees.rfind(b"\n") + 1
    for brut in donnees[:fin].splitlines():
        if brut.strip():
            _appliquer_ligne(etat, brut)
    etat["offset"] = debut + fin
    reste = donnees[fin:].strip()
    if reste:
        copie = {
            "seq": etat["seq"],
            "derniere_activite": etat["derniere_activite"],
            "reponses": dict(etat["reponses"]),
        }
        _appliquer_ligne(copie, reste)
        return copie
    return etat


def _contexte(t: dict[str, int]) -> int:
    return t["entree"] + t["cache_5m"] + t["cache_1h"] + t["cache_lecture"]


def _resultat(etat: dict) -> dict:
    reponses = list(etat["reponses"].values())
    principales = [r for r in reponses if not r["sidechain"]]
    modele = contexte = None
    if principales:
        derniere = max(principales, key=lambda r: r["seq"])
        modele = derniere["modele"]
        t = derniere["tokens"]
        contexte = {
            "tokens": _contexte(t),
            "limite": FENETRES_CONTEXTE.get(modele) if modele else None,
            "source": NOM_SOURCE,
        }
    return {
        "modele": modele,
        "contexte": contexte,
        "cout_usd_estime": _cout(reponses),
        "derniere_activite": etat["derniere_activite"],
    }


def _cout(reponses: list[dict]) -> float | None:
    """Somme sidechains comprises. Un seul modèle sans prix connu rend le coût
    inconnu (None) : un total partiel serait présenté comme complet."""
    if not reponses:
        return None
    total = 0.0
    for r in reponses:
        prix = PRIX_PAR_MTOK.get(r["modele"]) if r["modele"] else None
        if prix is None:
            return None
        total += sum(r["tokens"][k] * prix[k] for k in prix) / 1_000_000
    return total


def lire_transcript(chemin: Path) -> tuple[dict | None, dict]:
    """source nom = "transcript". Ne lève jamais.

    Renvoie ({"modele", "contexte": {"tokens", "limite", "source"} | None,
    "cout_usd_estime", "derniere_activite"}, source). Le résultat est mis en
    cache par (chemin, taille, mtime) ; si le fichier a grandi, seule la partie
    ajoutée est relue."""
    try:
        chemin = Path(chemin)
        stat = chemin.stat()
        cle = str(chemin)
        taille, mtime = stat.st_size, stat.st_mtime_ns
        memo = _CACHE.get(cle)
        if memo and memo["taille"] == taille and memo["mtime"] == mtime:
            return memo["resultat"], {"nom": NOM_SOURCE, "ok": True}
        if memo and taille > memo["taille"]:
            etat = memo["etat"]
            debut = etat["offset"]
        else:
            etat = {"offset": 0, "seq": 0, "derniere_activite": None, "reponses": {}}
            debut = 0
        courant = _lire_depuis(etat, chemin, debut, taille)
        resultat = _resultat(courant)
        _CACHE[cle] = {"taille": taille, "mtime": mtime, "etat": etat, "courant": courant,
                       "resultat": resultat}
        return resultat, {"nom": NOM_SOURCE, "ok": True}
    except Exception as e:  # noqa: BLE001 — ne lève jamais : un collecteur en échec ne fait pas tomber l'instantané
        return None, {"nom": NOM_SOURCE, "ok": False, "erreur": f"transcript illisible : {e}"}


def premiere_reponse_au_dessus(chemin: Path, seuil_tokens: float) -> str | None:
    """Horodatage de la première réponse principale de la série en cours dont le contexte
    dépasse `seuil_tokens` ; None si la dernière réponse est sous le seuil ou si rien n'est
    mesurable. Après un /compact le contexte retombe : la série repart de la dernière
    réponse sous le seuil. Lit via `lire_transcript` (cache incrémental). Ne lève jamais."""
    try:
        resultat, source = lire_transcript(chemin)
        if resultat is None:
            return None
        principales = sorted((r for r in _CACHE[str(Path(chemin))]["courant"]["reponses"].values()
                              if not r["sidechain"]), key=lambda r: r["seq"])
        debut = None
        for r in principales:
            if _contexte(r["tokens"]) > seuil_tokens:
                debut = debut or r
            else:
                debut = None
        return debut.get("horodatage") if debut else None
    except Exception:  # noqa: BLE001 — ne lève jamais
        return None


def trouver_transcript(
    session_id: str, racine_claude: Path = Path.home() / ".claude" / "projects"
) -> Path | None:
    """Cherche <session_id>.jsonl sous racine_claude (un niveau de dossiers)."""
    try:
        if not session_id or "/" in session_id or "\\" in session_id or session_id.startswith("."):
            return None
        for dossier in sorted(Path(racine_claude).iterdir()):
            candidat = dossier / f"{session_id}.jsonl"
            if candidat.is_file():
                return candidat
    except Exception:  # noqa: BLE001
        pass
    return None


def trouver_par_cwd(
    cwd: str, racine_claude: Path = Path.home() / ".claude" / "projects"
) -> Path | None:
    """Repli sans registre : le `*.jsonl` le plus récent du dossier Claude Code de ce cwd
    (nom du dossier = cwd dont tout caractère non alphanumérique devient « - »)."""
    try:
        if not cwd:
            return None
        dossier = Path(racine_claude) / re.sub(r"[^A-Za-z0-9]", "-", cwd)
        fichiers = [f for f in dossier.glob("*.jsonl") if f.is_file()]
        return max(fichiers, key=lambda f: f.stat().st_mtime_ns) if fichiers else None
    except Exception:  # noqa: BLE001
        return None


def sous_agents(chemin: Path) -> list[Path]:
    """Transcripts des sous-agents : <dossier>/<session>/subagents/*.jsonl, triés. Ne lève jamais."""
    try:
        chemin = Path(chemin)
        return sorted((chemin.parent / chemin.stem / "subagents").glob("*.jsonl"))
    except Exception:  # noqa: BLE001
        return []


def _reponses(chemin: Path) -> list[dict] | None:
    resultat, _ = lire_transcript(chemin)
    if resultat is None:
        return None
    return list(_CACHE[str(Path(chemin))]["courant"]["reponses"].values())


def consommation(chemin: Path, maintenant: datetime) -> dict | None:
    """Jetons lus et écrits sur 15 et 60 min : transcript principal + sous-agents.
    Lit via `lire_transcript` (cache incrémental). None si rien n'est lisible. Ne lève jamais."""
    try:
        principal = _reponses(Path(chemin))
        if principal is None:
            return None
        ensemble = [(r, False) for r in principal]
        for f in sous_agents(Path(chemin)):
            ensemble += [(r, True) for r in _reponses(f) or []]
        sortie: dict = {}
        for nom, minutes in (("15min", 15), ("60min", 60)):
            debut = maintenant - timedelta(minutes=minutes)
            lus = ecrits = tours = sub = 0
            ctx: list[int] = []
            for r, est_sub in ensemble:
                dt = datetime.fromisoformat(r["horodatage"].replace("Z", "+00:00")) if r["horodatage"] else None
                if dt is None or dt < debut:
                    continue
                t = r["tokens"]
                n = _contexte(t)
                lus += n
                ecrits += t["sortie"]
                tours += 1
                if est_sub:
                    sub += n
                elif not r["sidechain"]:
                    ctx.append(n)
            sortie[nom] = {"lus": lus, "ecrits": ecrits, "tours": tours,
                           "contexte_moyen": sum(ctx) // len(ctx) if ctx else None,
                           "dont_sous_agents": sub}
        sortie["source"] = NOM_SOURCE
        return sortie
    except Exception:  # noqa: BLE001 — ne lève jamais : un collecteur en échec ne fait pas tomber l'instantané
        return None
