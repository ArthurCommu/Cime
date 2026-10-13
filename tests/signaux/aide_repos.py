"""Outils communs aux tests des coordinateurs au repos (mise au repos, réveil, alarmes, reprise)."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from aide import fabriquer_projet, lignes
from faux_tmux import FauxTmux
from cime.fondation import fermeture
from cime.fondation.nom import VAR_PROJET
from cime.fondation.registre import (
    horodatage, inscrire_evenement, inscrire_message, inscrire_transition, ouvrir,
)
from cime.signaux import commandes, livraison, ordres

COORD, ASSISTANT, WORKER = "coord-x", "assistant", "worker-x-t"
S_COORD, S_ASSISTANT, S_WORKER = "essai-coord-x", "essai-assistant", "essai-worker-x-t"
CONVERSATION = "conv-x-1"


@pytest.fixture
def projet(tmp_path, monkeypatch):
    racine = fabriquer_projet(tmp_path / "depot")
    monkeypatch.setenv(VAR_PROJET, str(racine))
    return racine


@pytest.fixture
def machine(monkeypatch):
    """Un faux tmux unique, vu par la livraison, par la fermeture et par les ordres."""
    faux = FauxTmux([S_ASSISTANT, S_COORD])
    monkeypatch.setattr(livraison, "_tmux", faux)
    monkeypatch.setattr(fermeture, "_tmux", faux)
    monkeypatch.setattr(ordres, "_tmux", faux)
    monkeypatch.setattr(ordres, "_sessions_vivantes", lambda: set(faux.sessions))
    monkeypatch.setattr(livraison, "_dormir", lambda s: None)
    return faux


def regler_repos(projet, minutes):
    fichier = projet / ".orga" / "projet.toml"
    fichier.write_text(fichier.read_text() + f"\n[charge]\ncoordinateur_repos_minutes = {minutes}\n")


def dans(minutes) -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


def evt(projet, agent, nom, session_id=CONVERSATION, **details):
    return _evt(projet, agent, nom, session_id, details)


def _evt(projet, agent, nom, session_id, details):
    conn = ouvrir(projet)
    try:
        return inscrire_evenement(conn, agent=agent, session_id=session_id, evenement=nom,
                                  details=details)
    finally:
        conn.close()


def evt_sans_agent(projet, nom, details=None):
    """Un événement sans agent, comme `ProjetFerme` ou `CoordEndormi`."""
    return _evt(projet, None, nom, None, details or {})


def au_repos(projet, agent=COORD, session_id=CONVERSATION):
    """L'agent a ouvert une session et fini un tour : au repos depuis maintenant."""
    evt(projet, agent, "SessionStart", session_id, source="startup")
    return evt(projet, agent, "Stop", session_id)


def evenements(projet, nom):
    """Les événements `nom`, du plus ancien au plus récent : (id, agent, session_id, détails)."""
    return [(i, a, s, json.loads(d)) for i, a, s, d in lignes(
        projet, "SELECT id, agent, session_id, details FROM evenements WHERE evenement = ?"
        " ORDER BY id", (nom,))]


def poster(projet, de, a, resume="va", nature="consigne", attend="rien", objet=None):
    conn = ouvrir(projet)
    try:
        return commandes.inscrire(conn, de=de, a=a, nature=nature, resume=resume, attend=attend,
                                  objet=objet, equipe="x")
    finally:
        conn.close()


def transition(projet, message_id, etat):
    conn = ouvrir(projet)
    try:
        inscrire_transition(conn, message_id, etat, "cime", {})
    finally:
        conn.close()


def obligation_seule(projet, debiteur):
    """Une obligation ouverte de `debiteur`, sans aucun message en attente à son adresse."""
    identifiant = poster(projet, ASSISTANT, debiteur, attend="travail_pret")
    transition(projet, identifiant, "clos")
    assert lignes(projet, "SELECT etat FROM obligations WHERE debiteur = ?", (debiteur,)) \
        == [("ouverte",)]
    return identifiant


def courrier_ouvert(projet, a):
    conn = ouvrir(projet)
    try:
        with conn:
            conn.execute("INSERT INTO courriers (a, voie, cree, expire, etat) VALUES"
                         " (?, 'tmux', ?, ?, 'ouvert')", (a, horodatage(), horodatage()))
    finally:
        conn.close()


def tache_en_cours(projet, equipe="x", tache="t"):
    (projet / ".orga" / "teams" / equipe / "tasks" / "in-progress" / f"{tache}.md").write_text("t")


def ajouter_session(machine, nom):
    machine.sessions[nom] = {"invite": "", "activite": 0.0}


def evt_a(projet, agent, nom, quand: datetime, session_id=CONVERSATION, **details):
    """Un événement daté de `quand` (pour dire « il y a 60 minutes » sans attendre)."""
    conn = ouvrir(projet)
    try:
        with conn:
            conn.execute("INSERT INTO evenements (horodatage, agent, session_id, evenement, details)"
                         " VALUES (?, ?, ?, ?, ?)",
                         (livraison._iso(quand), agent, session_id, nom, json.dumps(details)))
    finally:
        conn.close()


def dormir_pour_de_bon(projet, machine, minutes=25):
    """Le coordinateur est au repos, puis endormi par le facteur : sa session n'existe plus."""
    from cime.signaux import repos
    au_repos(projet)
    assert repos.endormir(projet, dans(minutes)) == [COORD]
    assert S_COORD not in machine.sessions


def ordres_poses(projet):
    """Les ordres : (auteur, verbe, cible, paramètres, état), dans l'ordre des id."""
    return [(a, v, c, json.loads(p), e) for a, v, c, p, e in lignes(
        projet, "SELECT auteur, verbe, cible, parametres, etat FROM ordres ORDER BY id")]


def accuser_reception(projet, a=COORD):
    """L'agent a accusé réception : son courrier tmux n'est plus en cours de livraison."""
    conn = ouvrir(projet)
    try:
        with conn:
            conn.execute("UPDATE courriers SET etat = 'acquitte' WHERE a = ? AND etat = 'ouvert'", (a,))
    finally:
        conn.close()


def evt_sans_agent_a(projet, nom, quand: datetime, details: dict):
    """Comme `evt_a`, pour un événement sans agent (`CoordEndormi`, `CoordReveille`)."""
    conn = ouvrir(projet)
    try:
        with conn:
            conn.execute("INSERT INTO evenements (horodatage, agent, session_id, evenement, details)"
                         " VALUES (?, NULL, NULL, ?, ?)", (livraison._iso(quand), nom, json.dumps(details)))
    finally:
        conn.close()
