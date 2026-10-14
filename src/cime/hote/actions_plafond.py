"""Route `/api/actions/plafond` : le plafond de workers de la machine, prérogative de l'utilisateur.

Le réglage est écrit par `cime plafond`, que l'hôte lance avec `CIME_AGENT=utilisateur` : la
commande refuse tout autre auteur. Elle écrit dans le dossier de configuration de la machine,
pas dans le projet ; l'hôte, lui, ne touche à aucun fichier.
"""
from __future__ import annotations

import os

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from cime.fondation.plafond import DEFAUT, MAX, MIN, lire_machine, valeur_valide

from .actions_fusions_auto import _derniere_ligne
from .gardes import Interdit
from .journal import executer_action

REFUS_VALEUR = f"valeur attendue : un entier de {MIN} à {MAX}, ou defaut"


def routes(contexte) -> list[Route]:
    async def plafond(request: Request) -> JSONResponse:
        try:
            corps = await request.json()
        except Exception:
            corps = None
        if not isinstance(corps, dict):
            corps = {}
        valeur = corps.get("valeur")
        details: dict = {"valeur": valeur, "avant": None, "horodatage": None}

        async def faire() -> tuple[str, str]:
            # `valeur_valide` écarte le booléen (un `int` en Python), le flottant et tout autre texte
            if valeur != "defaut" and not valeur_valide(valeur):
                return "refuse", REFUS_VALEUR
            projet = str(os.path.abspath(contexte.projet))
            details["avant"] = lire_machine()[0]
            gardes = contexte.gardes()
            base = gardes.plafond if gardes.plafond is not None else [*gardes.envoyer, "plafond"]
            argument = "--defaut" if valeur == "defaut" else str(valeur)
            env = dict(os.environ, CIME_AGENT="utilisateur", CIME_PROJET=projet)
            try:
                r = await gardes.aexecuter([*base, argument], env=env, cwd=projet)
            except (OSError, Interdit) as e:
                return "erreur", str(e)
            if r.returncode == 0:
                details["horodatage"] = (r.stdout or "").strip()
                if valeur == "defaut":
                    return "ok", f"plafond de workers : défaut ({DEFAUT})"
                return "ok", f"plafond de workers : {valeur}"
            texte = r.stderr or ""
            motif = _derniere_ligne(texte or r.stdout or "") or f"code de sortie {r.returncode}"
            if r.returncode == 1 and "déjà" in texte:
                return "refuse", texte[texte.index("déjà"):].splitlines()[0].strip()
            if r.returncode == 2:
                return "refuse", motif
            return "erreur", motif

        return await executer_action(
            contexte.journal, "utilisateur", "plafond", "machine", details, faire
        )

    return [Route("/api/actions/plafond", plafond, methods=["POST"])]
