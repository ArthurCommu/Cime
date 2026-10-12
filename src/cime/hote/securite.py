"""Middleware Host/Origin : une page web quelconque ne doit pas piloter l'hôte."""
from __future__ import annotations

from collections.abc import Callable

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class SecuriteLocale:
    def __init__(self, app: ASGIApp, port: int | Callable[[], int]) -> None:
        # `port` peut être une fonction : avec `servir(port=0)`, le vrai port n'est connu
        # qu'après l'ouverture du socket.
        self.app = app
        self._port = port if callable(port) else (lambda: port)

    @property
    def hotes(self) -> set[str]:
        p = self._port()
        return {f"127.0.0.1:{p}", f"localhost:{p}"}

    @property
    def origines(self) -> set[str]:
        p = self._port()
        return {f"http://127.0.0.1:{p}", f"http://localhost:{p}"}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        en_tetes = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        refus = None
        if en_tetes.get("host") not in self.hotes:
            refus = "Host refusé"
        elif (
            scope["type"] == "websocket" or scope["method"] not in ("GET", "HEAD")
        ) and "origin" in en_tetes and en_tetes["origin"] not in self.origines:
            refus = "Origin refusé"
        if refus:
            if scope["type"] == "http":
                await PlainTextResponse(refus, status_code=403)(scope, receive, send)
            else:
                await send({"type": "websocket.close", "code": 1008})
            return
        await self.app(scope, receive, send)
