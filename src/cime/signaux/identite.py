"""Identité de l'appelant d'une commande : un agent désigné, ou l'utilisateur au clavier."""
import os

from cime.fondation.nom import VAR_AGENT
from cime.fondation.projet import valider_identite

VAR_CLAUDECODE = "CLAUDECODE"


class ErreurIdentite(Exception):
    pass


def appelant(env=os.environ) -> str:
    """Qui appelle la commande : l'agent désigné par CIME_AGENT ; sinon, si la commande
    vient de l'outil Bash de Claude Code (CLAUDECODE), un agent sans identité — refusé,
    jamais pris pour l'utilisateur ; sinon un humain au clavier : l'utilisateur."""
    agent = env.get(VAR_AGENT)
    if agent:
        try:
            return valider_identite(agent, emetteur=True)
        except ValueError as e:
            raise ErreurIdentite(str(e)) from None
    if env.get(VAR_CLAUDECODE):
        raise ErreurIdentite("agent sans identité")
    return "utilisateur"
