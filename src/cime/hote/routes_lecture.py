"""/, /static, /scene, /api/etat, /api/flux."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

PAGE = Path(__file__).resolve().parent.parent / "page"
SCENE = Path(__file__).resolve().parent.parent / "scene"

PAGE_ABSENTE = (
    "<!doctype html><meta charset='utf-8'><title>Centre de contrôle</title>"
    "<p>La page n'est pas encore installée.</p>"
)


class _Statiques(StaticFiles):
    """StaticFiles qui répond 404 (et non une erreur) quand le dossier n'est pas encore livré."""

    async def __call__(self, scope, receive, send):
        if not Path(self.directory).is_dir():
            await PlainTextResponse("Not Found", status_code=404)(scope, receive, send)
            return
        await super().__call__(scope, receive, send)


def _age_ms(genere_a: str, maintenant: datetime) -> int | None:
    try:
        t = datetime.fromisoformat(genere_a.replace("Z", "+00:00"))
        return round((maintenant - t).total_seconds() * 1000)
    except (ValueError, AttributeError, TypeError):
        return None


def _lire_flux(projet: Path, depuis: str) -> dict:
    """`GET /api/flux?depuis=<id de transition>` : les transitions nouvelles ;
    `depuis=` vide : les 200 dernières requêtes, et `dernier_id` pour continuer. Lecture seule."""
    from cime.signaux import vue
    chemin = Path(projet) / ".orga" / "etat" / "registre.sqlite"
    conn = sqlite3.connect(f"file:{quote(str(chemin))}?mode=ro", uri=True, timeout=1.0)
    conn.row_factory = sqlite3.Row
    try:
        dernier = conn.execute("SELECT COALESCE(MAX(id), 0) FROM transitions").fetchone()[0]
        if depuis == "":
            return {"requetes": vue.flux(conn, 200), "dernier_id": dernier}
        transitions = vue.transitions_depuis(conn, int(depuis))
        return {"transitions": transitions, "dernier_id": transitions[-1]["id"] if transitions else int(depuis)}
    finally:
        conn.close()


def corps_etat(contexte) -> dict | None:
    inst = contexte.rafraichisseur.instantane
    if inst is None:
        return None
    corps = dict(inst)
    corps["age_ms"] = _age_ms(inst.get("genere_a"), contexte.deps.horloge())
    if contexte.rafraichisseur.derniere_erreur:
        corps["erreur_rafraichissement"] = contexte.rafraichisseur.derniere_erreur
    return corps


def routes(contexte) -> list:
    async def accueil(request: Request):
        index = PAGE / "index.html"
        if index.is_file():
            return FileResponse(index)
        return HTMLResponse(PAGE_ABSENTE)

    async def etat(request: Request):
        corps = corps_etat(contexte)
        if corps is None:
            return JSONResponse({"erreur": "aucun instantané encore"}, status_code=503)
        return JSONResponse(corps)

    async def flux(request: Request):
        if "depuis" in request.query_params:
            depuis = request.query_params["depuis"]
            if depuis != "" and not depuis.isdigit():
                return JSONResponse({"erreur": "depuis : un id de transition (entier) ou vide"}, status_code=400)
            try:
                return JSONResponse(await asyncio.to_thread(_lire_flux, contexte.projet, depuis))
            except sqlite3.Error as e:
                return JSONResponse({"erreur": f"registre illisible : {e}"}, status_code=503)
        raf = contexte.rafraichisseur

        async def generateur():
            vu = 0
            dernier_vivant = time.monotonic()  # `vivant` à cadence fixe, même quand des `etat` arrivent sans cesse
            while True:
                if contexte.en_arret or await request.is_disconnected():
                    return
                if raf.numero > vu:
                    vu = raf.numero
                    corps = corps_etat(contexte)
                    if corps is not None:
                        yield f"event: etat\ndata: {json.dumps(corps)}\n\n"
                    continue
                avant_vivant = contexte.deps.vivant_s - (time.monotonic() - dernier_vivant)
                if avant_vivant <= 0:
                    yield "event: vivant\ndata: {}\n\n"
                    dernier_vivant = time.monotonic()
                    continue
                try:  # attente bornée pour constater régulièrement une déconnexion
                    await asyncio.wait_for(raf.attendre_nouveau(vu), timeout=min(avant_vivant, 0.5))
                except asyncio.TimeoutError:
                    pass

        return StreamingResponse(
            generateur(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return [
        Route("/", accueil),
        Mount("/static", _Statiques(directory=PAGE / "static", check_dir=False)),
        Mount("/scene", _Statiques(directory=SCENE / "static", html=True, check_dir=False)),
        Route("/api/etat", etat),
        Route("/api/flux", flux),
    ]
