"""Hôte local du Centre de contrôle : serveur HTTP (127.0.0.1) qui sert la page et exécute les actions de l'utilisateur."""
from .serveur import creer_app, servir

__all__ = ["creer_app", "servir"]
