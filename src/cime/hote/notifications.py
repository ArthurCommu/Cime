"""Notifications macOS pour ce qui attend la décision de l'utilisateur."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Protocol

from .gardes import Gardes

journal_log = logging.getLogger(__name__)

NATURES_NOTIFIABLES = frozenset({"autorisation", "decision", "donnee", "cloture"})
LONGUEUR_MAX = 200


class Notifieur(Protocol):
    async def notifier(self, titre: str, texte: str) -> None: ...


def nettoyer(texte: object) -> str:
    """Rend un texte acceptable par les gardes : ni `"`, ni `\\`, ni saut de ligne."""
    t = str(texte).replace('"', "”").replace("\\", "")
    t = " ".join(t.replace("\r", "\n").split("\n"))
    return t[:LONGUEUR_MAX]


class NotifieurMac:
    """Lance `osascript` par les gardes. Aucune erreur n'est propagée."""

    def __init__(self, gardes: Gardes) -> None:
        self.gardes = gardes
        self.derniere_erreur: str | None = None

    async def notifier(self, titre: str, texte: str) -> None:
        script = f'display notification "{nettoyer(texte)}" with title "{nettoyer(titre)}"'
        try:
            await self.gardes.aexecuter(["osascript", "-e", script])
            self.derniere_erreur = None
        except asyncio.CancelledError:
            raise
        except Exception as e:  # dont Interdit : l'hôte ne tombe pas pour une notification
            self.derniere_erreur = f"{type(e).__name__}: {e}"
            journal_log.warning("notification échouée : %s", self.derniere_erreur)


def marquer_livre(projet: Path, message_id: int) -> bool:
    """Le message adressé à `utilisateur` est `livre` par la voie `hote` (page +
    notification), auteur `cime`. Idempotent : False si une livraison existe déjà."""
    from cime.fondation.registre import horodatage, inscrire_transition, ouvrir
    conn = ouvrir(projet)
    try:
        ligne = conn.execute("SELECT a FROM messages WHERE id = ?", (message_id,)).fetchone()
        if ligne is None or conn.execute(
                "SELECT 1 FROM transitions WHERE message_id = ? AND etat = 'livre'",
                (message_id,)).fetchone():
            return False
        with conn:
            courrier_id = conn.execute(
                "INSERT INTO courriers (a, voie, cree, expire, etat) VALUES (?, 'hote', ?, ?, 'acquitte')",
                (ligne[0], horodatage(), horodatage())).lastrowid
            inscrire_transition(conn, message_id, "livre", "cime", {"notif": True},
                                courrier_id=courrier_id, commit=False)
        return True
    finally:
        conn.close()


def _deja_livre(projet: Path, message_id: int) -> bool:
    from cime.fondation.registre import ouvrir
    conn = ouvrir(projet)
    try:
        return conn.execute("SELECT 1 FROM transitions WHERE message_id = ? AND etat = 'livre'",
                            (message_id,)).fetchone() is not None
    finally:
        conn.close()


def _secondes(t: object) -> float:
    return t.timestamp() if isinstance(t, datetime) else float(t)  # type: ignore[arg-type]


class Veilleur:
    """Regroupe les nouvelles attentes de l'utilisateur : au plus une notification par minute."""

    def __init__(
        self,
        notifieur: Notifieur,
        horloge: Callable[[], datetime],
        intervalle_min_s: float = 60,
        dormir: Callable[[float], object] = asyncio.sleep,
        projet: Path | None = None,
    ) -> None:
        self.projet = Path(projet) if projet is not None else None
        self.notifieur = notifieur
        self.horloge = horloge
        self.intervalle_min_s = intervalle_min_s
        self._dormir = dormir
        self._vus: set[str] = set()
        self._file: dict[str, dict] = {}
        self._derniere: float | None = None
        self._projet = ""
        self._tache: asyncio.Task | None = None

    def _delai(self) -> float:
        if self._derniere is None:
            return 0.0
        return max(0.0, self._derniere + self.intervalle_min_s - _secondes(self.horloge()))

    async def observer(self, instantane: dict) -> None:
        self._projet = ((instantane or {}).get("projet") or {}).get("nom") or self._projet
        attentes = (instantane or {}).get("attentes_utilisateur") or []
        presentes = set()
        for a in attentes:
            if not isinstance(a, dict) or not isinstance(a.get("id"), str):
                continue
            presentes.add(a["id"])
            if a.get("nature") not in NATURES_NOTIFIABLES or a["id"] in self._vus:
                continue
            self._vus.add(a["id"])
            if self._livre_par_une_vie_precedente(a):
                continue  # l'hôte a redémarré : ne pas renotifier ce qui l'a déjà été
            self._file[a["id"]] = a
        for i in [i for i in self._file if i not in presentes]:
            del self._file[i]  # disparue avant l'envoi
        await self._tenter()

    def _livre_par_une_vie_precedente(self, attente: dict) -> bool:
        ident = attente.get("message_id")
        if self.projet is None or not isinstance(ident, int):
            return False
        try:
            return _deja_livre(self.projet, ident)
        except Exception:
            journal_log.exception("lecture de la livraison impossible")
            return False

    async def _tenter(self) -> None:
        if not self._file:
            self._annuler_tache()
            return
        delai = self._delai()
        if delai <= 0:
            self._annuler_tache()
            await self._envoyer()
        elif self._tache is None or self._tache.done():
            self._tache = asyncio.create_task(self._plus_tard(delai))

    def _annuler_tache(self) -> None:
        if self._tache is not None and self._tache is not asyncio.current_task():
            self._tache.cancel()
        self._tache = None

    async def _plus_tard(self, delai: float) -> None:
        r = self._dormir(delai)
        if hasattr(r, "__await__"):
            await r
        self._tache = None
        await self._tenter()

    async def _envoyer(self) -> None:
        attentes = sorted(self._file.values(), key=lambda a: str(a.get("depuis") or ""))
        self._file.clear()
        if not attentes:
            return
        if len(attentes) == 1:
            texte = str(attentes[0].get("titre") or "")
        else:
            texte = f"{len(attentes)} choses t'attendent : {attentes[0].get('titre') or ''}"
        self._derniere = _secondes(self.horloge())
        try:
            await self.notifieur.notifier(self._projet or "Centre de contrôle", texte)
        except asyncio.CancelledError:
            raise
        except Exception:
            journal_log.exception("notifieur en erreur")
            return
        if getattr(self.notifieur, "derniere_erreur", None):
            return  # la notification a échoué : rien n'est dit livré
        self._marquer_livres(attentes)

    def _marquer_livres(self, attentes: list[dict]) -> None:
        if self.projet is None:
            return
        for a in attentes:
            ident = a.get("message_id")
            if not isinstance(ident, int):
                continue  # une autorisation depuis l'état de l'agent : pas un message
            try:
                marquer_livre(self.projet, ident)
            except Exception:
                journal_log.exception("transition `livre` non écrite pour le message %s", ident)
