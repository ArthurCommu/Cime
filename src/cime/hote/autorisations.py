"""Demandes d'autorisation des agents : registre en mémoire et lecture du menu tmux."""
from __future__ import annotations

import asyncio
import re
from datetime import datetime

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\].*?(?:\x07|\x1b\\)")
_REGLE_PLEINE = re.compile(r"^\s*─{3,}\s*$")
_TITRE = re.compile(r"^\s*Do you want to\b.*\?\s*$")
_OPTION_OUI = re.compile(r"^\s*❯\s*1\.\s+Yes\s*$")
_OPTION = re.compile(r"^\s*\d+\.\s+\S")
_PIED = "Esc to cancel"
# pied alternatif (WebFetch) : la dernière option est « No … (esc) », rien après
_OPTION_NON_ESC = re.compile(r"^\s*\d+\.\s+No\b.*\(esc\)\s*$")
_OPTIONS_MAX = 4  # « au plus quelques options » : Yes comprise
_SUITE_MAX = 4  # lignes de retour à la ligne d'une option (chemins longs)

EN_ATTENTE = "en_attente"
ALLOW = "allow"
DENY = "deny"


def sans_ansi(capture: str) -> str:
    return _ANSI.sub("", capture)


def _menu(capture: str) -> tuple[list[str], int] | None:
    """(lignes sans ANSI, indice du titre) si le menu d'autorisation est sûr, sinon None.

    Sûr : après la dernière règle pleine, un titre `Do you want to … ?`, puis `❯ 1. Yes`,
    quelques options, une ligne de pied `Esc to cancel` (ou, pour WebFetch, une dernière
    option `No … (esc)`), et rien d'autre ensuite.
    """
    lignes = sans_ansi(capture).splitlines()
    regles = [i for i, l in enumerate(lignes) if _REGLE_PLEINE.match(l)]
    if not regles:
        return None
    titres = [i for i in range(regles[-1] + 1, len(lignes)) if _TITRE.match(lignes[i])]
    if not titres:
        return None
    titre = titres[-1]
    i = titre + 1
    while i < len(lignes) and not lignes[i].strip():
        i += 1
    if i >= len(lignes) or not _OPTION_OUI.match(lignes[i]):
        return None
    options, suite = 1, 0
    i += 1
    while i < len(lignes):
        ligne = lignes[i]
        if _PIED in ligne or _OPTION_NON_ESC.match(ligne):
            options += _OPTION.match(ligne) is not None
            break
        if _OPTION.match(ligne):
            options += 1
        elif ligne.strip():
            suite += 1
        if options > _OPTIONS_MAX or suite > _SUITE_MAX:
            return None
        i += 1
    if i >= len(lignes) or options > _OPTIONS_MAX or any(l.strip() for l in lignes[i + 1:]):
        return None
    return lignes, titre


def menu_affiche(capture: str) -> bool:
    return _menu(capture) is not None


def bloc_demande(capture: str) -> str | None:
    """Le bloc de l'outil demandé : de la dernière règle pleine au titre du menu."""
    menu = _menu(capture)
    if menu is None:
        return None
    lignes, titre = menu
    debut = max(i for i in range(titre) if _REGLE_PLEINE.match(lignes[i])) + 1
    return "\n".join(l.rstrip() for l in lignes[debut:titre]).strip()


def _instant(texte) -> datetime | None:
    try:
        return datetime.fromisoformat(str(texte).replace("Z", "+00:00"))
    except ValueError:
        return None


class Registre:
    """demande_id → {agent, session_tmux, tool_name, tool_input, recue_a, decision, close}."""

    def __init__(self) -> None:
        self.demandes: dict[str, dict] = {}
        self._verrous: dict[str, asyncio.Lock] = {}

    def enregistrer(self, demande_id, agent, session_tmux, tool_name, tool_input, recue_a) -> None:
        if demande_id in self.demandes:
            return  # le hook peut rejouer : la première demande fait foi
        self.demandes[demande_id] = {
            "agent": agent,
            "session_tmux": session_tmux,
            "tool_name": tool_name,
            "tool_input": tool_input,
            "recue_a": recue_a,
            "decision": None,
            "close": False,
        }

    def verrou(self, demande_id: str) -> asyncio.Lock:
        return self._verrous.setdefault(demande_id, asyncio.Lock())

    def retrouver_apres_redemarrage(self, demande_id: str, instantane: dict | None) -> dict | None:
        """Hôte redémarré : reconstruit la demande depuis l'attente `perm-<id>`."""
        if not instantane:
            return None
        attente = next(
            (a for a in instantane.get("attentes_utilisateur") or [] if a.get("id") == f"perm-{demande_id}"),
            None,
        )
        if attente is None:
            return None
        agent = next(
            (a for a in instantane.get("agents") or [] if a.get("id") == attente.get("agent")), None
        )
        if not agent or not agent.get("session_tmux"):
            return None
        self.demandes[demande_id] = {
            "agent": agent["id"],
            "session_tmux": agent["session_tmux"],
            "tool_name": attente.get("titre") or "outil",
            "tool_input": None,
            "recue_a": None,
            "decision": None,
            "close": False,
        }
        return self.demandes[demande_id]

    def observer(self, instantane: dict) -> None:
        """Ferme les demandes ouvertes dont l'agent n'attend plus d'autorisation."""
        genere = _instant(instantane.get("genere_a"))
        etats = {a.get("id"): a.get("etat") for a in instantane.get("agents") or []}
        for d in self.demandes.values():
            if d["decision"] or d["close"]:
                continue
            # un instantané antérieur à la demande ne peut pas la contredire
            if genere is not None and d["recue_a"] is not None and genere < d["recue_a"]:
                continue
            if etats.get(d["agent"]) != "attend_autorisation":
                d["close"] = True


def registre_pour(contexte) -> Registre:
    """Le registre du contexte, créé (avec son observateur) au premier appel."""
    registre = getattr(contexte, "_registre_autorisations", None)
    if registre is None:
        registre = Registre()
        contexte._registre_autorisations = registre
        contexte.rafraichisseur.ajouter_observateur(registre.observer)
    return registre
