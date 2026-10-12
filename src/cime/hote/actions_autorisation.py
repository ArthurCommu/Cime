"""Autoriser / refuser une demande d'autorisation : la seule écriture vers un agent."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .autorisations import ALLOW, DENY, bloc_demande, menu_affiche, registre_pour
from .gardes import Interdit
from .journal import executer_action

journal_log = logging.getLogger(__name__)

ATTENTE_INITIALE_S = 1.5
ATTENTE_ENTRE_S = 1.0
VERIFICATIONS = 3
RESUME_MAX = 160
COMMANDE_MAX = 200

PREFIXE_ATTENTE = "perm-"
TOUCHES = {"autoriser": ("1", ALLOW), "refuser": ("Escape", DENY)}


def _texte(valeur) -> str | None:
    return valeur if isinstance(valeur, str) and valeur else None


def _cible_outil(tool_input) -> dict:
    """`{commande: …}` ou `{chemin: …}` (tronqué) ; `{commande: None}` si aucun des deux."""
    if isinstance(tool_input, dict):
        for cle, nom in (("command", "commande"), ("file_path", "chemin")):
            valeur = _texte(tool_input.get(cle))
            if valeur:
                return {nom: valeur[:COMMANDE_MAX]}
    return {"commande": None}


async def _capturer(gardes, session: str) -> str:
    r = await gardes.aexecuter(["tmux", "capture-pane", "-p", "-t", session])
    if r.returncode != 0:
        raise RuntimeError(f"capture impossible ({r.stderr.strip() or r.returncode})")
    return r.stdout


def _resume_refus(tool_name: str, agent: str) -> str:
    texte = f"L'utilisateur a refusé {tool_name} à {agent} ; l'agent est interrompu et attend une consigne"
    texte = " ".join(texte.split())
    return texte if len(texte) <= RESUME_MAX else texte[: RESUME_MAX - 1] + "…"


async def _prevenir_assistant(contexte, gardes, demande: dict) -> str | None:
    """Renvoie None si l'Assistant est prévenu, sinon le motif de l'échec."""
    argv = gardes.envoyer + [
        "--a", "assistant", "--nature", "compte_rendu",
        _resume_refus(demande["tool_name"], demande["agent"]),
    ]
    env = dict(os.environ, CIME_AGENT="utilisateur", CIME_PROJET=str(os.path.abspath(contexte.projet)))
    try:
        r = await gardes.aexecuter(argv, env=env, cwd=env["CIME_PROJET"])
    except (OSError, Interdit) as e:
        return str(e)
    if r.returncode != 0:
        return (r.stderr or r.stdout).strip() or f"code de sortie {r.returncode}"
    return None


async def _repondre(contexte, action: str, demande_id: str, auteur: str = "utilisateur") -> tuple[str, str]:
    registre = registre_pour(contexte)
    touche, decision = TOUCHES[action]
    async with registre.verrou(demande_id):
        demande = registre.demandes.get(demande_id) or registre.retrouver_apres_redemarrage(
            demande_id, contexte.rafraichisseur.instantane
        )
        if demande is None:
            return "refuse", "demande inconnue"
        if demande["decision"] or demande["close"]:
            return "refuse", "déjà répondu"
        session = demande["session_tmux"]
        gardes = contexte.gardes()
        try:
            avant = await _capturer(gardes, session)
        except Interdit as e:
            return "refuse", str(e)
        if not menu_affiche(avant):
            return "refuse", (
                "aucune demande affichée dans la session (déjà répondue dans le terminal ?)"
            )
        bloc_avant = bloc_demande(avant)
        r = await gardes.aexecuter(["tmux", "send-keys", "-t", session, touche])
        if r.returncode != 0:
            return "erreur", f"envoi de la touche impossible ({r.stderr.strip() or r.returncode})"

        prise = False
        for i in range(VERIFICATIONS):
            await asyncio.sleep(ATTENTE_INITIALE_S if i == 0 else ATTENTE_ENTRE_S)
            apres = await _capturer(gardes, session)
            if not menu_affiche(apres) or bloc_demande(apres) != bloc_avant:
                prise = True
                break
        if not prise:
            return "erreur", "la touche n'a pas été prise en compte"
        demande["decision"] = decision
        try:  # la demande est tranchée : les relances de ses signalements n'ont plus d'objet
            await asyncio.to_thread(clore_signalements, contexte.projet, demande_id, auteur)
        except Exception:
            journal_log.exception("signalements d'autorisation non clos")
        if action == "autoriser":
            return "ok", "autorisé"
        if auteur != "utilisateur":
            return "ok", f"refusé par {auteur}"  # l'Assistant sait ce qu'il a refusé
        echec = await _prevenir_assistant(contexte, gardes, demande)
        if echec:
            return "erreur", f"refus transmis à l'agent, mais l'Assistant n'a pas été prévenu : {echec}"
        return "ok", "refusé ; Assistant prévenu"


def clore_signalements(projet, demande_id: str, auteur: str) -> int:
    """La demande est tranchée : ses signalements `autorisation:<id>` encore ouverts (copie de
    l'Assistant, escalade vers l'utilisateur) sont satisfaits, pour que les relances s'arrêtent."""
    from cime.fondation.registre import inscrire_transition, ouvrir
    conn = ouvrir(projet)
    try:
        fermes = 0
        with conn:
            for (ident,) in conn.execute(
                    "SELECT m.id FROM messages m JOIN obligations o ON o.message_id = m.id"
                    " WHERE m.nature = 'signalement' AND m.objet = ? AND o.etat = 'ouverte'",
                    (f"autorisation:{demande_id}",)).fetchall():
                conn.execute("UPDATE obligations SET etat = 'satisfaite' WHERE message_id = ?", (ident,))
                inscrire_transition(conn, ident, "clos", auteur, {"par_autorisation": True}, commit=False)
                fermes += 1
        return fermes
    finally:
        conn.close()


def accords_en_attente(projet) -> list[dict]:
    """Les `accord`/`refus` d'autorisation adressés à `cime` que l'hôte n'a pas encore exécutés
    (dernière transition `inscrit`), du plus ancien au plus récent. Lecture seule."""
    chemin = Path(projet) / ".orga" / "etat" / "registre.sqlite"
    try:
        con = sqlite3.connect(f"{chemin.resolve().as_uri()}?mode=ro", uri=True, timeout=2)
    except sqlite3.Error:
        return []
    try:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute(
            "SELECT m.id, m.de, m.nature, m.objet FROM messages m WHERE m.a = 'cime'"
            " AND m.nature IN ('accord', 'refus') AND m.objet LIKE 'autorisation:%'"
            " AND (SELECT t.etat FROM transitions t WHERE t.message_id = m.id"
            "      ORDER BY t.id DESC LIMIT 1) = 'inscrit' ORDER BY m.id")]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def classe_et_mode(projet, demande_id: str) -> dict:
    """`classe` (lue dans le `corps` du signalement `autorisation:<id>`, None si absente)
    et `mode_autonome` (au moment de l'exécution), pour la ligne `journal`. Lecture seule."""
    from cime.signaux import autorisations, echeances
    classe = None
    chemin = Path(projet) / ".orga" / "etat" / "registre.sqlite"
    try:
        with closing(sqlite3.connect(f"{chemin.resolve().as_uri()}?mode=ro", uri=True, timeout=2)) as con:
            ligne = con.execute("SELECT corps FROM messages WHERE nature = 'signalement' AND objet = ?"
                                " ORDER BY id LIMIT 1", (f"autorisation:{demande_id}",)).fetchone()
        donnees = echeances.corps_autorisation(ligne[0]) if ligne else None
        classe = donnees["classe"] if donnees else None
    except sqlite3.Error:
        pass
    return {"classe": classe, "mode_autonome": autorisations.mode_actif(projet)}


class ExecuteurAccords:
    """`cime accorder|refuser` sur un `signalement autorisation:<id>` n'écrit que
    l'`accord`/le `refus`. C'est l'hôte qui exécute le geste : il relit l'écran de l'agent (le menu
    « Do you want to proceed? » doit y être encore, sinon il n'envoie rien et le journal le dit),
    tape `1` ou `Escape` par le code d'autorisation, journalise (auteur = celui de l'accord,
    heure) puis clôt l'accord. Un accord n'est exécuté qu'une fois : sa dernière transition
    doit être `inscrit`."""

    def __init__(self, contexte) -> None:
        self.contexte = contexte
        self._pris: set[int] = set()

    async def observer(self, instantane: dict) -> None:
        try:
            await self.passer()
        except asyncio.CancelledError:
            raise
        except Exception:
            journal_log.exception("exécution des accords d'autorisation en erreur")

    async def passer(self) -> int:
        executes = 0
        for accord in await asyncio.to_thread(accords_en_attente, self.contexte.projet):
            if accord["id"] in self._pris:
                continue
            self._pris.add(accord["id"])
            await self._executer(accord)
            executes += 1
        return executes

    async def _executer(self, accord: dict) -> None:
        contexte = self.contexte
        demande_id = accord["objet"][len("autorisation:"):].lower()
        action = "autoriser" if accord["nature"] == "accord" else "refuser"
        registre = registre_pour(contexte)
        connue = registre.demandes.get(demande_id)
        details = {"agent": connue["agent"] if connue else None,
                   "outil": connue["tool_name"] if connue else None,
                   **(_cible_outil(connue["tool_input"]) if connue else {"commande": None}),
                   "accord": accord["id"],
                   **await asyncio.to_thread(classe_et_mode, contexte.projet, demande_id)}
        sortie: dict = {}

        async def faire():
            resultat, message = await _repondre(contexte, action, demande_id, auteur=accord["de"])
            sortie.update(resultat=resultat, message=message)
            if resultat != "ok":
                details["raison"] = message  # « rien n'a été envoyé » doit se lire au journal
            return resultat, message

        try:
            await executer_action(contexte.journal, accord["de"], action, PREFIXE_ATTENTE + demande_id,
                                  details, faire)
        finally:
            await asyncio.to_thread(self._clore, accord, sortie, demande_id)

    def _clore(self, accord: dict, sortie: dict, demande_id: str) -> None:
        from cime.fondation.registre import inscrire_transition, ouvrir
        conn = ouvrir(self.contexte.projet)
        try:
            inscrire_transition(conn, accord["id"], "clos", "cime", {
                "par_hote": True, "touche": TOUCHES[("autoriser" if accord["nature"] == "accord" else "refuser")][0],
                "resultat": sortie.get("resultat", "erreur"), "message": sortie.get("message")})
            if sortie.get("resultat") == "ok":
                clore_signalements(self.contexte.projet, demande_id, accord["de"])
        finally:
            conn.close()


def routes(contexte) -> list[Route]:
    registre = registre_pour(contexte)
    if getattr(contexte, "_executeur_accords", None) is None:
        contexte._executeur_accords = ExecuteurAccords(contexte)
        contexte.rafraichisseur.ajouter_observateur(contexte._executeur_accords.observer)

    def handler(action: str):
        async def appel(requete: Request) -> JSONResponse:
            try:
                corps = await requete.json()
            except ValueError:
                corps = None
            corps = corps if isinstance(corps, dict) else {}
            attente_id = _texte(corps.get("attente_id"))
            if action == "refuser" and attente_id is not None and attente_id.startswith("msg-"):
                from .actions_reponses import refuser_decision  # accord de fusion ou de chantier
                return await refuser_decision(contexte, corps)
            demande_id = _texte(corps.get("demande_id"))
            if attente_id is None and demande_id is None:
                return JSONResponse({"erreur": "attente_id ou demande_id manquant"}, status_code=400)
            demande_id = demande_id.lower() if demande_id else None
            de_l_attente = None
            if attente_id is not None and attente_id.startswith(PREFIXE_ATTENTE):
                de_l_attente = attente_id[len(PREFIXE_ATTENTE):].lower() or None
            resolu = de_l_attente or demande_id
            connue = registre.demandes.get(resolu) if resolu else None
            details = {
                "agent": connue["agent"] if connue else None,
                "outil": connue["tool_name"] if connue else None,
                **(_cible_outil(connue["tool_input"]) if connue else {"commande": None}),
                **(await asyncio.to_thread(classe_et_mode, contexte.projet, resolu) if resolu
                   else {"classe": None, "mode_autonome": None}),
            }
            cible = attente_id[:100] if attente_id is not None else PREFIXE_ATTENTE + demande_id

            async def faire():
                if attente_id is not None and de_l_attente is None:
                    return "refuse", "ce n'est pas une demande d'autorisation"
                if de_l_attente and demande_id and de_l_attente != demande_id:
                    return "refuse", "attente_id et demande_id désignent deux demandes différentes"
                return await _repondre(contexte, action, resolu)

            return await executer_action(contexte.journal, "utilisateur", action, cible, details, faire)

        return appel

    return [
        Route("/api/actions/autoriser", handler("autoriser"), methods=["POST"]),
        Route("/api/actions/refuser", handler("refuser"), methods=["POST"]),
    ]
