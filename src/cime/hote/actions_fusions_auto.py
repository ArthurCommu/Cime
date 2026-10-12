"""Interrupteur « Fusions automatiques » : prérogative de l'utilisateur, sans jamais toucher git.

Le réglage est écrit par `cime fusions-auto active|inactive`, que l'hôte lance avec
`CIME_AGENT=utilisateur` : c'est la seule écriture, et elle refuse tout autre auteur. L'hôte ne
fusionne rien, ne lance aucune commande git.
"""
from __future__ import annotations

import os

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from cime.fondation.fusions_auto import etat_courant

from .gardes import Interdit
from .journal import executer_action

VALEURS = ("active", "inactive")
MESSAGES = {"active": "fusions automatiques activées", "inactive": "fusions automatiques désactivées"}
DEJA = ("déjà actif", "déjà inactif")
ERREUR_MAX = 200


def _derniere_ligne(texte: str) -> str:
    """Le motif d'une erreur est la dernière ligne : celle d'une trace Python (`ValueError: …`)."""
    lignes = [l for l in texte.splitlines() if l.strip()]
    return lignes[-1].strip()[:ERREUR_MAX] if lignes else ""


def _reglage_id(sortie: str) -> int | None:
    try:
        return int(sortie.strip())
    except ValueError:
        return None


def routes(contexte) -> list[Route]:
    async def fusions_auto(request: Request) -> JSONResponse:
        try:
            corps = await request.json()
        except Exception:
            corps = None
        if not isinstance(corps, dict):
            corps = {}
        valeur = corps.get("valeur")
        details: dict = {"valeur": valeur, "avant": None, "reglage_id": None}

        async def faire() -> tuple[str, str]:
            if not isinstance(valeur, str) or valeur not in VALEURS:
                return "refuse", "valeur attendue : active ou inactive"
            projet = str(os.path.abspath(contexte.projet))
            details["avant"] = "active" if etat_courant(contexte.projet)["active"] else "inactive"
            gardes = contexte.gardes()
            base = gardes.fusions_auto if gardes.fusions_auto is not None else [*gardes.envoyer, "fusions-auto"]
            env = dict(os.environ, CIME_AGENT="utilisateur", CIME_PROJET=projet)
            try:
                r = await gardes.aexecuter([*base, valeur], env=env, cwd=projet)
            except (OSError, Interdit) as e:
                return "erreur", str(e)
            if r.returncode == 0:
                details["reglage_id"] = _reglage_id(r.stdout or "")
                return "ok", MESSAGES[valeur]
            texte = r.stderr or ""
            for deja in DEJA:
                if deja in texte:
                    return "refuse", deja
            return "erreur", _derniere_ligne(texte or r.stdout or "") or f"code de sortie {r.returncode}"

        return await executer_action(
            contexte.journal, "utilisateur", "fusions_auto", "projet", details, faire
        )

    return [Route("/api/actions/fusions-auto", fusions_auto, methods=["POST"])]
