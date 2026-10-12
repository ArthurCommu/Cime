"""Clôturer une équipe : prérogative de l'utilisateur, sans jamais toucher git.

Le coordinateur demande, l'Assistant vérifie et prévient l'utilisateur, l'utilisateur clôture.
Clôturer = écrire `teams/<équipe>/CLOTUREE` et fermer les sessions tmux de l'équipe.
La branche et le worktree de l'équipe ne sont jamais touchés.
"""
from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .gardes import Interdit
from .journal import executer_action

_EQUIPE = re.compile(r"[a-z0-9-]+")
_SPECIALES = ["assistant", "integration", "verification"]
_REQ_DEMANDE = (
    "SELECT id FROM messages WHERE nature='demande_cloture' AND de=? AND a='assistant'"
    " ORDER BY id DESC"
)
_REQ_RAPPORT = (
    "SELECT id FROM messages WHERE nature='rapport_utilisateur' AND de='assistant' AND a='utilisateur'"
    " AND en_reponse_a=? AND equipe=? ORDER BY id DESC LIMIT 1"
)


def _heure(horloge) -> str:
    t = horloge()
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def _validation(registre: Path, equipe: str) -> tuple[int, int] | None:
    """(id demande, id rapport) si l'Assistant a validé la clôture, sinon None."""
    with closing(sqlite3.connect(f"{registre.resolve().as_uri()}?mode=ro", uri=True, timeout=5)) as con:
        for (d,) in con.execute(_REQ_DEMANDE, (f"coord-{equipe}",)).fetchall():
            r = con.execute(_REQ_RAPPORT, (d, equipe)).fetchone()
            if r is not None:
                return d, r[0]
    return None


def _sessions_a_fermer(prefixe: str, equipe: str, existantes: list[str], vivantes: list[str]) -> list[str]:
    autres = [e for e in existantes if e != equipe and e.startswith(equipe + "-")]
    pref = f"{prefixe}-worker-{equipe}-"
    sortie = []
    for s in vivantes:
        if s == f"{prefixe}-coord-{equipe}":
            sortie.append(s)
        elif s.startswith(pref) and not any(s.startswith(f"{prefixe}-worker-{a}-") for a in autres):
            sortie.append(s)
    return sortie


def _marquer_et_abandonner(contexte, marque: Path, equipe: str, demande: int, rapport: int, autres) -> list[int]:
    """Écrit `CLOTUREE` et abandonne les obligations de l'équipe dans la même transaction du registre :
    si l'un échoue, l'autre n'a pas lieu (la marque est retirée, ou rien n'est validé)."""
    from cime.fondation.registre import ouvrir
    from cime.signaux import obligations
    conn = ouvrir(contexte.projet)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            evenement = inscrire_evenement_sans_commit(conn, equipe, demande, rapport)
            abandonnees = obligations.abandonner_equipe(conn, equipe, "utilisateur", evenement, autres, commit=False)
            # le rapport de clôture adressé à l'utilisateur est lu par ce geste : plus de renotification
            if obligations.satisfaire(conn, rapport, evenement, commit=False):
                from cime.fondation.registre import inscrire_transition
                inscrire_transition(conn, rapport, "clos", "utilisateur", {"par_evenement": evenement}, commit=False)
            with marque.open("x", encoding="utf-8") as f:
                f.write(f"auteur: utilisateur\nheure: {_heure(contexte.deps.horloge)}\n"
                        f"demande: {demande}\nrapport: {rapport}\n")
            try:
                conn.commit()
            except sqlite3.Error:
                marque.unlink(missing_ok=True)
                raise
            return abandonnees
        except BaseException:
            if conn.in_transaction:
                conn.rollback()
            raise
    finally:
        conn.close()


def inscrire_evenement_sans_commit(conn, equipe: str, demande: int, rapport: int) -> int:
    from cime.fondation.registre import horodatage
    cur = conn.execute(
        "INSERT INTO evenements (horodatage, agent, session_id, evenement, details) VALUES (?, NULL, NULL, ?, ?)",
        (horodatage(), "Cloture", json.dumps({"equipe": equipe, "demande": demande, "rapport": rapport})))
    return cur.lastrowid


def routes(contexte) -> list[Route]:
    async def cloturer(request: Request) -> JSONResponse:
        try:
            corps = await request.json()
        except Exception:
            corps = None
        if not isinstance(corps, dict):
            corps = {}
        equipe = corps.get("equipe")
        confirmation = corps.get("confirmation")
        cible = f"equipe:{equipe}" if isinstance(equipe, str) else None
        details: dict = {"demande": None}

        async def faire() -> tuple[str, str]:
            # 1. forme de la demande
            if not isinstance(equipe, str) or not _EQUIPE.fullmatch(equipe):
                return "refuse", "nom d'équipe invalide (attendu : [a-z0-9-]+)"
            if confirmation != equipe:
                return "refuse", "confirmation absente ou différente du nom de l'équipe"
            # 2. l'équipe
            teams = Path(contexte.projet) / ".orga" / "teams"
            dossier = teams / equipe
            if not (dossier / "mandate.md").is_file():
                return "refuse", f"équipe inconnue : {equipe}"
            speciales = contexte.manifeste().get("equipes_speciales", _SPECIALES)
            if equipe in speciales:
                return "refuse", f"équipe spéciale, jamais clôturée ici : {equipe}"
            marque = dossier / "CLOTUREE"
            if marque.exists():
                return "refuse", f"équipe déjà clôturée : {equipe}"
            # 3. validation par l'Assistant
            registre = Path(contexte.projet) / ".orga" / "etat" / "registre.sqlite"
            try:
                valide = _validation(registre, equipe)
            except (sqlite3.Error, OSError) as e:
                return "erreur", f"registre illisible : {e}"
            if valide is None:
                return "refuse", "clôture non validée par l'Assistant"
            d, r = valide
            details["demande"] = f"msg-{d}"
            gardes = contexte.gardes()
            # 4. la marque et l'abandon des obligations de l'équipe : une seule transaction du registre
            autres = sorted(p.parent.name for p in teams.glob("*/mandate.md")
                            if p.parent.name != equipe and p.parent.name.startswith(equipe + "-"))
            try:
                await asyncio.to_thread(
                    _marquer_et_abandonner, contexte, marque, equipe, d, r, autres)
            except FileExistsError:
                return "refuse", f"équipe déjà clôturée : {equipe}"
            except (sqlite3.Error, OSError) as e:
                return "erreur", f"clôture non faite (registre ou marque illisible) : {e}"
            # 5. les sessions
            try:
                res = await gardes.aexecuter(["tmux", "list-sessions", "-F", "#{session_name}"])
            except (Interdit, OSError) as e:
                return "erreur", f"CLOTUREE écrit, mais sessions illisibles : {e}"
            if res.returncode != 0 and "no server running" not in (res.stderr or "") \
                    and "error connecting" not in (res.stderr or ""):
                return "erreur", f"CLOTUREE écrit, mais tmux list-sessions a échoué : {(res.stderr or '').strip()}"
            vivantes = [l for l in (res.stdout or "").splitlines() if l] if res.returncode == 0 else []
            existantes = sorted(p.parent.name for p in teams.glob("*/mandate.md"))
            a_fermer = _sessions_a_fermer(gardes.prefixe, equipe, existantes, vivantes)
            fermees, restantes = [], list(a_fermer)
            for s in a_fermer:
                try:
                    k = await gardes.aexecuter(["tmux", "kill-session", "-t", s])
                except (Interdit, OSError) as e:
                    return "erreur", _echec(fermees, restantes, str(e))
                if k.returncode != 0:
                    return "erreur", _echec(fermees, restantes, (k.stderr or "").strip())
                fermees.append(s)
                restantes.remove(s)
            liste = ", ".join(fermees) if fermees else "aucune"
            return "ok", f"équipe {equipe} clôturée ; sessions fermées : {liste}"

        return await executer_action(
            contexte.journal, "utilisateur", "cloturer", cible, details, faire
        )

    return [Route("/api/actions/cloturer", cloturer, methods=["POST"])]


def _echec(fermees: list[str], restantes: list[str], cause: str) -> str:
    return (
        f"CLOTUREE écrit, mais fermeture échouée ({cause}) ; fermées : "
        f"{', '.join(fermees) or 'aucune'} ; encore ouvertes : {', '.join(restantes)}"
    )
