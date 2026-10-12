"""Demandes de permission : le hook de Claude Code prévient l'hôte, la page décide."""
from __future__ import annotations

import uuid

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .autorisations import EN_ATTENTE, registre_pour


def _uuid_valide(valeur) -> bool:
    try:
        return isinstance(valeur, str) and str(uuid.UUID(valeur)) == valeur.lower()
    except ValueError:
        return False


def routes(contexte) -> list[Route]:
    registre = registre_pour(contexte)

    async def deposer(requete: Request) -> JSONResponse:
        try:
            corps = await requete.json()
        except ValueError:
            return JSONResponse({"erreur": "corps JSON invalide"}, status_code=400)
        if not isinstance(corps, dict) or not _uuid_valide(corps.get("demande_id")):
            return JSONResponse({"erreur": "demande_id doit être un UUID"}, status_code=400)
        for cle in ("agent", "session_tmux", "tool_name"):
            if not isinstance(corps.get(cle), str) or not corps[cle]:
                return JSONResponse({"erreur": f"{cle} manquant"}, status_code=400)
        registre.enregistrer(
            corps["demande_id"].lower(),
            corps["agent"],
            corps["session_tmux"],
            corps["tool_name"],
            corps.get("tool_input"),
            contexte.deps.horloge(),
        )
        return JSONResponse({"decision": EN_ATTENTE})

    return [Route("/api/permissions", deposer, methods=["POST"])]
