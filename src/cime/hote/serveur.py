"""Assemblage de l'app Starlette et lancement d'uvicorn (127.0.0.1 uniquement)."""
from __future__ import annotations

import asyncio
import contextlib
import functools
import inspect
import json
import os
import sys
import tomllib
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware

from . import (
    routes_actions,
    routes_consultation,
    routes_lecture,
    routes_permissions,
)
from .dependances import Dependances
from .gardes import Gardes
from .journal import Journal, RegistreAbsent
from .notifications import NotifieurMac, Veilleur
from .rafraichisseur import Rafraichisseur
from .securite import SecuriteLocale

ADRESSE = "127.0.0.1"
ARRET_MAX_S = 3


@dataclass
class Contexte:
    projet: Path
    deps: Dependances
    port: int
    rafraichisseur: Rafraichisseur
    journal: Journal
    en_arret: bool = False  # posé au début de l'arrêt : les flux SSE se terminent d'eux-mêmes

    def manifeste(self) -> dict:
        """`.orga/projet.toml` lu à chaque appel ; {} s'il est absent."""
        chemin = Path(self.projet) / ".orga" / "projet.toml"
        if not chemin.exists():
            return {}
        with chemin.open("rb") as f:
            return tomllib.load(f)

    def gardes(self) -> Gardes:
        """Le seul moyen de lancer une commande. Préfixe : `deps.prefixe`, sinon la
        clé `prefixe` du manifeste ; absent → erreur explicite (jamais deviné)."""
        prefixe = self.deps.prefixe or self.manifeste().get("prefixe")
        if not prefixe:
            raise RuntimeError("clé `prefixe` manquante dans .orga/projet.toml : ajoute-la")
        return Gardes(prefixe, envoyer=list(self.deps.envoyer), tmux_socket=self.deps.tmux_socket)


def registre_de(projet: Path) -> Path:
    return Path(projet) / ".orga" / "etat" / "registre.sqlite"


def creer_app(projet: Path, deps: Dependances, port: int) -> Starlette:
    journal = Journal(registre_de(projet), deps.horloge)
    contexte = Contexte(projet, deps, port, Rafraichisseur(projet, deps), journal)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        try:
            journal.preparer()
        except RegistreAbsent as e:
            # L'hôte démarre quand même : l'instantané montre la source `registre` en
            # échec, le journal répond 503 et aucune action n'est exécutée sans lui.
            print(f"journal indisponible : {e}", file=sys.stderr)
        contexte.rafraichisseur.demarrer()
        try:
            yield
        finally:
            await contexte.rafraichisseur.arreter()

    if deps.notifieur is not None:
        contexte.rafraichisseur.ajouter_observateur(Veilleur(deps.notifieur, deps.horloge, projet=projet).observer)

    routes = []
    for module in (routes_lecture, routes_actions, routes_permissions, routes_consultation):
        routes += module.routes(contexte)
    app = Starlette(
        routes=routes,
        lifespan=lifespan,
        middleware=[Middleware(SecuriteLocale, port=lambda: contexte.port)],
    )
    app.state.contexte = contexte
    return app


def _hote_repond(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://{ADRESSE}:{port}/api/etat", timeout=2) as r:
            r.read()
        return True
    except urllib.error.HTTPError:
        return True  # 503 avant le premier instantané : l'hôte est bien là
    except Exception:
        return False


def instantane_complet(fonction):
    """L'hôte sert la page à l'utilisateur, il demande l'instantané complet
    (conversation de l'utilisateur ↔ Assistant comprise). Une observation antérieure, sans le
    paramètre `complet`, est appelée telle quelle."""
    try:
        parametres = inspect.signature(fonction).parameters
    except (TypeError, ValueError):
        return fonction
    if "complet" in parametres:
        return functools.partial(fonction, complet=True)
    return fonction


def brancher_notifications_mac(contexte, deps: Dependances, environ=os.environ) -> bool:
    """Branche les notifications macOS, sauf si `CIME_NOTIFICATIONS=0` (sessions d'essai)."""
    if environ.get("CIME_NOTIFICATIONS") == "0":
        print("notifications désactivées (CIME_NOTIFICATIONS=0)", file=sys.stderr)
        return False
    try:
        notifieur = NotifieurMac(contexte.gardes())
        contexte.rafraichisseur.ajouter_observateur(Veilleur(notifieur, deps.horloge, projet=contexte.projet).observer)
    except Exception as e:  # pas de notification plutôt qu'un hôte qui ne démarre pas
        print(f"notifications désactivées : {e}", file=sys.stderr)
        return False
    return True


def servir(
    projet: Path,
    port: int,
    deps: Dependances | None = None,
    arret: threading.Event | None = None,
) -> None:
    """Bloquant. `deps` et `arret` ne servent qu'aux tests ; sinon l'observation réelle est importée.

    Variable d'environnement `CIME_NOTIFICATIONS=0` : aucune notification macOS (aucun
    `osascript`), pour les sessions d'essai : `CIME_NOTIFICATIONS=0 cime servir`.
    """
    projet = Path(projet)
    production = deps is None
    if deps is None:
        try:
            from cime.observation import instantane
        except Exception as e:
            sys.exit(f"Impossible d'importer cime.observation.instantane : {e}")
        deps = Dependances(instantane=instantane_complet(instantane))
        deps.intervalle_s = min(max(deps.intervalle_s, 2.0), 5.0)

    if not (projet / ".orga").is_dir():
        sys.exit(f"{projet} n'est pas un projet (.orga absent) : lancez cime init")

    fichier = projet / ".orga" / "etat" / "hote.port"
    if fichier.exists():
        try:
            ancien = int(fichier.read_text().strip())
        except ValueError:
            ancien = None
        if ancien is not None and _hote_repond(ancien):
            sys.exit(f"Un hôte tourne déjà pour ce projet sur le port {ancien}")

    app = creer_app(projet, deps, port)
    if production and deps.notifieur is None:
        # chemin de production seulement : les tests n'atteignent jamais le vrai osascript
        brancher_notifications_mac(app.state.contexte, deps)
    # timeout_graceful_shutdown : filet si une connexion ne se ferme pas d'elle-même.
    serveur = uvicorn.Server(uvicorn.Config(
        app, host=ADRESSE, port=port, log_level="warning", timeout_graceful_shutdown=ARRET_MAX_S))
    ecrit = False
    startup = serveur.startup

    async def startup_puis_fichier(sockets=None):
        # Le fichier n'est écrit qu'une fois le socket ouvert (startup lie le port).
        nonlocal ecrit
        await startup(sockets=sockets)
        if serveur.started:
            # port=0 : le système a choisi ; on publie le port réellement ouvert.
            reel = serveur.servers[0].sockets[0].getsockname()[1]
            app.state.contexte.port = reel
            fichier.parent.mkdir(parents=True, exist_ok=True)
            fichier.write_text(str(reel))
            ecrit = True
            if arret is not None:
                asyncio.get_running_loop().create_task(_surveiller(arret, serveur))

    shutdown = serveur.shutdown

    async def shutdown_puis_effacer(sockets=None):
        # Sur SIGTERM, uvicorn relève le signal à la sortie de serve() : le `finally`
        # ci-dessous n'est alors jamais atteint. On efface donc dès la fin de l'arrêt.
        # uvicorn attend la fin des réponses en cours : sans ce drapeau, un flux SSE
        # ouvert (la page en garde toujours un) bloquait l'arrêt indéfiniment.
        app.state.contexte.en_arret = True
        try:
            await shutdown(sockets=sockets)
        finally:
            _effacer()

    def _effacer():
        if ecrit:
            with contextlib.suppress(FileNotFoundError):
                fichier.unlink()

    serveur.startup = startup_puis_fichier
    serveur.shutdown = shutdown_puis_effacer
    try:
        serveur.run()
    finally:
        _effacer()


async def _surveiller(arret: threading.Event, serveur: uvicorn.Server) -> None:
    while not arret.is_set():
        await asyncio.sleep(0.05)
    serveur.should_exit = True
