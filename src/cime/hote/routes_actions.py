"""Actions de l'utilisateur : chaque famille d'actions vit dans son module."""
from __future__ import annotations

from starlette.routing import Route

from . import actions_autorisation, actions_cloture, actions_fusions_auto, actions_plafond, actions_reponses


def routes(contexte) -> list[Route]:
    return (
        actions_autorisation.routes(contexte)
        + actions_cloture.routes(contexte)
        + actions_reponses.routes(contexte)
        + actions_fusions_auto.routes(contexte)
        + actions_plafond.routes(contexte)
    )
