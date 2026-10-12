"""Matrice des natures de message, sous forme de données."""
from pathlib import Path

from cime.fondation.projet import equipe_de

# Codes de direction : "sup>sub", "sub>sup", ">sup", "cime>tout", "utilisateur>assistant",
# "worker>coord", "coord>assistant", "assistant>verification",
# "verification>assistant", "assistant>utilisateur", "cime>agent".
# `via_repondre` : nature écrite seulement par repondre/accorder/refuser (par le
# destinataire du message cité : la direction est alors celle de la réponse).
MATRICE = {
    "consigne": {"permis": ("sup>sub", "cime>tout", "utilisateur>assistant", "assistant>verification")},
    "question": {"permis": ("sub>sup",)},
    "reponse": {"via_repondre": True},
    "accord": {"via_repondre": True},
    "refus": {"via_repondre": True},
    "compte_rendu": {"permis": (">sup", "utilisateur>assistant")},
    "travail_pret": {"permis": ("worker>coord", "coord>assistant")},
    "demande_accord": {"permis": ("coord>assistant",)},
    "demande_cloture": {"permis": ("coord>assistant",)},
    "signalement": {"permis": ("cime>agent", "verification>assistant")},
    "relance": {"permis": ("cime>debiteur",)},
    "decision_utilisateur": {"permis": ("assistant>utilisateur",)},
    "donnee_utilisateur": {"permis": ("assistant>utilisateur",)},
    "rapport_utilisateur": {"permis": ("assistant>utilisateur",)},
}

# Objets d'un `rapport_utilisateur` qui annonce une décision prise en mode autonome : aucune obligation.
ANNONCES_AUTO = ("fusion-auto:", "chantier-auto:", "contrat-auto:", "autorisation-auto:")

# Signalements d'information à un agent qui n'ouvrent aucune obligation.
INFORMATIONS_SANS_OBLIGATION = ("autorisation-reservee:",)

ATTENTES_CONSIGNE = ("rien", "accuse", "travail_pret", "reponse")


def role(identite: str) -> str:
    if identite in ("assistant", "utilisateur", "cime"):
        return identite
    if identite.startswith("coord-"):
        return "coord"
    if identite.startswith("worker-"):
        return "worker"
    return "inconnu"


def superieur(identite: str, projet: Path) -> str | None:
    r = role(identite)
    if r == "worker":
        equipe = equipe_de(projet, identite)
        return f"coord-{equipe}" if equipe else None
    if r == "coord":
        return "assistant"
    return None


def _est_agent(identite: str) -> bool:
    return role(identite) in ("assistant", "coord", "worker")


def _est_verification(identite: str) -> bool:
    """La session de vérification est un `worker-integration-<t>` : facultative, elle ne
    parle qu'à l'Assistant."""
    return role(identite) == "worker" and identite.startswith("worker-integration-")


def _direction_ok(code: str, de: str, a: str, projet: Path) -> bool:
    rd, ra = role(de), role(a)
    if code == "sup>sub":
        return superieur(a, projet) == de
    if code == "sub>sup":
        return superieur(de, projet) == a
    if code == ">sup":
        return superieur(de, projet) == a
    if code == "cime>tout":
        return de == "cime" and _est_agent(a)
    if code == "cime>debiteur":
        return de == "cime" and (_est_agent(a) or a == "utilisateur")
    if code == "cime>agent":
        return de == "cime" and _est_agent(a)
    if code == "assistant>verification":
        return de == "assistant" and _est_verification(a)
    if code == "verification>assistant":
        return _est_verification(de) and a == "assistant"
    if code == "utilisateur>assistant":
        return de == "utilisateur" and a == "assistant"
    if code == "worker>coord":
        return rd == "worker" and superieur(de, projet) == a
    if code == "coord>assistant":
        return rd == "coord" and a == "assistant"
    if code == "assistant>utilisateur":
        return de == "assistant" and a == "utilisateur"
    return False


def verifier(de: str, a: str, nature: str, projet: Path, via_repondre: bool = False):
    """None si l'envoi est permis, sinon le motif du refus."""
    regle = MATRICE.get(nature)
    if regle is None:
        return f"nature hors matrice : {nature!r}"
    if regle.get("via_repondre"):
        if via_repondre:
            return None
        verbe = {"reponse": "repondre", "accord": "accorder", "refus": "refuser"}[nature]
        return f"la nature {nature!r} ne s'écrit pas avec `envoyer` : utilise `cime {verbe}`"
    if any(_direction_ok(c, de, a, projet) for c in regle["permis"]):
        return None
    return f"{de} ne peut pas envoyer de {nature} à {a} (hors matrice)"


def obligation(nature: str, a: str, objet: str | None = None, attend: str | None = None):
    """(débiteur, attendu) de l'obligation ouverte par un message, ou None."""
    if nature == "consigne":
        return None if attend in (None, "rien") else (a, attend)
    if nature == "question":
        return (a, "reponse")
    if nature == "travail_pret":
        return (a, "revue")
    if nature == "demande_accord":
        return (a, "accord")
    if nature == "demande_cloture":
        return (a, "rapport_utilisateur")
    if nature == "signalement":
        if a == "utilisateur":
            return None        # un signalement à l'utilisateur n'attend rien de lui
        if (objet or "").startswith(INFORMATIONS_SANS_OBLIGATION):
            return None        # l'information d'une demande réservée n'attend rien
        return (a, "decision") if (objet or "").startswith("autorisation:") else (a, "accuse")
    if nature == "decision_utilisateur":
        return ("utilisateur", "decision")
    if nature == "donnee_utilisateur":
        return ("utilisateur", "reponse")
    if nature == "rapport_utilisateur":
        if (objet or "").startswith(ANNONCES_AUTO):
            return None        # l'annonce d'une décision automatique n'attend rien de l'utilisateur
        return ("utilisateur", "lu")
    return None
