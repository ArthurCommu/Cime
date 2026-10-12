"""Tout ce qui touche le monde extérieur, injectable pour les tests."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def _instantane_absent(projet: Path) -> dict:
    raise RuntimeError("aucune fonction d'instantané n'a été injectée")


@dataclass
class Dependances:
    instantane: Callable[[Path], dict] = _instantane_absent
    horloge: Callable[[], datetime] = field(default=_maintenant)
    intervalle_s: float = 3.0
    vivant_s: float = 10.0
    # commande d'envoi vers l'Assistant ; les tests la remplacent par un faux script
    envoyer: list[str] = field(default_factory=lambda: ["cime", "envoyer"])
    # préfixe tmux du projet ; None = lu dans .orga/projet.toml (clé `prefixe`)
    prefixe: str | None = None
    # notifieur macOS ; None = pas de notification
    notifieur: object | None = None
    # socket tmux (`tmux -S <chemin>`) ; None = serveur par défaut (production)
    tmux_socket: str | None = None
