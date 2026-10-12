"""Boucle de rafraîchissement de l'instantané, et réveil des abonnés."""
from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Callable
from pathlib import Path

from .dependances import Dependances

journal_log = logging.getLogger(__name__)

ALARMES_CONTEXTE = ("contexte_au_repos", "contexte_plein")


def signaler_contextes(projet: Path, inst: dict) -> int:
    """Pour chaque alarme `contexte_au_repos`/`contexte_plein` vraie, inscrit **une fois**
    `cime → <supérieur de l'agent>` `signalement objet=contexte:<agent>` (le supérieur de
    l'Assistant est `utilisateur`). La clé — type d'alarme et son `depuis` — est gardée dans la preuve
    de la transition `inscrit` : un hôte redémarré ne redit rien ; un nouvel épisode (autre
    `depuis`) signale de nouveau. Le moteur de relances fait le reste (échelle `contexte`)."""
    if not (Path(projet) / ".orga" / "etat" / "registre.sqlite").is_file():
        return 0
    alarmes = [a for a in inst.get("alarmes") or [] if a.get("type") in ALARMES_CONTEXTE and a.get("agents")]
    if not alarmes:
        return 0
    from cime.fondation.registre import ouvrir
    from cime.signaux import hooks
    conn = ouvrir(projet)
    inscrits = 0
    try:
        for alarme in alarmes:
            agent = alarme["agents"][0]
            sup = hooks.superieur(agent, projet)
            if not sup:
                continue
            if hooks.signaler_une_fois(
                    conn, projet, a=sup, objet=f"contexte:{agent}", agent=agent,
                    cle=f"{alarme['type']}:{alarme.get('depuis')}",
                    resume=f"{agent} : contexte lourd ({alarme['type']}) — à compacter"):
                inscrits += 1
    finally:
        conn.close()
    return inscrits


class Rafraichisseur:
    def __init__(self, projet: Path, deps: Dependances) -> None:
        self.projet = projet
        self.deps = deps
        self.instantane: dict | None = None
        self.derniere_erreur: str | None = None
        self.numero = 0  # incrémenté à chaque nouvel instantané
        self._condition = asyncio.Condition()
        self._tache: asyncio.Task | None = None
        self._observateurs: list[Callable[[dict], object]] = []

    def ajouter_observateur(self, fonction: Callable[[dict], object]) -> None:
        """`fonction(instantane)` (synchrone ou coroutine) est appelée à chaque nouvel
        instantané. Une erreur d'observateur est consignée, jamais propagée."""
        self._observateurs.append(fonction)

    async def _prevenir_observateurs(self, inst: dict) -> None:
        for fonction in self._observateurs:
            try:
                r = fonction(inst)
                if inspect.isawaitable(r):
                    await r
            except asyncio.CancelledError:
                raise
            except Exception:
                journal_log.exception("observateur d'instantané en erreur")

    async def _signaler_contextes(self, inst: dict) -> None:
        try:
            await asyncio.to_thread(signaler_contextes, self.projet, inst)
        except asyncio.CancelledError:
            raise
        except Exception:
            journal_log.exception("signalement de contexte en erreur")

    def demarrer(self) -> None:
        self._tache = asyncio.create_task(self._boucle())

    async def arreter(self) -> None:
        if self._tache is not None:
            self._tache.cancel()
            try:
                await self._tache
            except asyncio.CancelledError:
                pass
            self._tache = None

    async def attendre_nouveau(self, apres: int) -> int:
        """Bloque jusqu'à ce que `numero` dépasse `apres` ; renvoie le numéro courant."""
        async with self._condition:
            await self._condition.wait_for(lambda: self.numero > apres)
            return self.numero

    async def _boucle(self) -> None:
        while True:
            debut = time.monotonic()
            try:
                inst = await asyncio.to_thread(self.deps.instantane, self.projet)
                self.instantane = inst
                self.derniere_erreur = None
                self.numero += 1
                async with self._condition:
                    self._condition.notify_all()
                await self._signaler_contextes(inst)
                await self._prevenir_observateurs(inst)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # on garde le précédent et on continue
                self.derniere_erreur = f"{type(e).__name__}: {e}"
            reste = self.deps.intervalle_s - (time.monotonic() - debut)
            await asyncio.sleep(max(reste, 0))
