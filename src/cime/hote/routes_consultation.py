"""Lectures seules : journal, terminal d'un agent, fichier de l'organisation."""
from __future__ import annotations

import asyncio
from pathlib import Path

from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

from .gardes import Interdit, chemin_lisible

TAILLE_MAX = 1024 * 1024


def _lire_fichier(racine_orga: Path, relatif: str) -> bytes:
    chemin = chemin_lisible(racine_orga, relatif)
    if not chemin.is_file():
        raise FileNotFoundError(relatif)
    with chemin.open("rb") as f:
        return f.read(TAILLE_MAX + 1)


def routes(contexte) -> list[Route]:
    async def journal(request):
        brut = request.query_params.get("limite", "100")
        try:
            limite = int(brut)
        except ValueError:
            limite = 0
        if not 1 <= limite <= 1000:
            return JSONResponse({"erreur": "limite : entier entre 1 et 1000"}, status_code=400)
        try:
            lignes = await asyncio.to_thread(contexte.journal.dernieres, limite)
        except Exception as e:
            return JSONResponse({"erreur": f"journal illisible : {e}"}, status_code=503)
        return JSONResponse({"lignes": lignes})

    async def terminal(request):
        inst = contexte.rafraichisseur.instantane or {}
        ident = request.path_params["id"]
        agent = next(
            (a for a in (inst.get("agents") or []) if isinstance(a, dict) and a.get("id") == ident),
            None,
        )
        session = agent.get("session_tmux") if agent else None
        if not session:
            return JSONResponse({"erreur": "agent inconnu ou sans session"}, status_code=404)
        try:
            r = await contexte.gardes().aexecuter(
                ["tmux", "capture-pane", "-p", "-J", "-S", "-200", "-t", session]
            )
        except Interdit as e:
            return JSONResponse({"erreur": str(e)}, status_code=403)
        except (OSError, RuntimeError) as e:
            return JSONResponse({"erreur": f"tmux indisponible : {e}"}, status_code=503)
        if r.returncode != 0:
            return JSONResponse({"erreur": "session absente"}, status_code=404)
        capture = contexte.deps.horloge().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        return JSONResponse({"texte": r.stdout, "capture_a": capture})

    async def fichier(request):
        relatif = request.query_params.get("chemin", "")
        if relatif.startswith(".orga/"):
            relatif = relatif[len(".orga/"):]
        racine_orga = Path(contexte.projet) / ".orga"
        try:
            brut = await asyncio.to_thread(_lire_fichier, racine_orga, relatif)
        except Interdit as e:
            return JSONResponse({"erreur": str(e)}, status_code=403)
        except (FileNotFoundError, NotADirectoryError):
            return JSONResponse({"erreur": "fichier absent"}, status_code=404)
        except OSError as e:
            return JSONResponse({"erreur": f"lecture impossible : {e}"}, status_code=500)
        if len(brut) > TAILLE_MAX:
            return JSONResponse({"erreur": "fichier trop gros (max 1 Mo)"}, status_code=413)
        try:
            texte = brut.decode("utf-8")
        except UnicodeDecodeError:
            return JSONResponse({"erreur": "fichier binaire"}, status_code=415)
        return PlainTextResponse(texte, media_type="text/plain; charset=utf-8")

    return [
        Route("/api/journal", journal, methods=["GET"]),
        Route("/api/agents/{id}/terminal", terminal, methods=["GET"]),
        Route("/api/fichier", fichier, methods=["GET"]),
    ]
