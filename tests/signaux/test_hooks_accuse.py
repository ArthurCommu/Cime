"""Accusé de réception, reprise, autorisations, refus du garde, SessionEnd."""
import argparse
import io
import json
import sys

import pytest

from aide import fabriquer_projet
from cime.fondation import hook
from cime.fondation.nom import VAR_AGENT, VAR_PROJET
from cime.fondation.registre import etat_message, ouvrir
from cime.signaux import commandes, courrier, hooks

WORKER = "worker-x-tache"


@pytest.fixture
def projet(tmp_path, monkeypatch):
    racine = fabriquer_projet(tmp_path / "depot")
    monkeypatch.setenv(VAR_PROJET, str(racine))
    return racine


def poster(projet, de, a, nature="consigne", resume="r", attend="rien", objet=None, corps=None):
    conn = ouvrir(projet)
    try:
        return commandes.inscrire(conn, de=de, a=a, nature=nature, resume=resume, attend=attend,
                                  objet=objet, corps=corps, equipe="x")
    finally:
        conn.close()


def lancer(monkeypatch, capsys, evenement, agent, entree=None):
    if agent is None:
        monkeypatch.delenv(VAR_AGENT, raising=False)
    else:
        monkeypatch.setenv(VAR_AGENT, agent)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"session_id": "s", **(entree or {})})))
    code = hook.executer(argparse.Namespace(evenement=evenement))
    sortie = capsys.readouterr()
    return code, sortie.out, sortie.err


def lignes(projet, requete, params=()):
    conn = ouvrir(projet)
    try:
        return conn.execute(requete, params).fetchall()
    finally:
        conn.close()


def livrer_par_tmux(projet, a):
    """Ce que fera le facteur : prend le courrier (voie tmux) et renvoie la ligne tapée."""
    conn = ouvrir(projet)
    try:
        c = courrier.prendre(conn, a, "tmux", "cime", {"capture_avant": "vide"})
        return c, courrier.formater(conn, c, "tmux")
    finally:
        conn.close()


def etat(projet, m):
    conn = ouvrir(projet)
    try:
        return etat_message(conn, m)
    finally:
        conn.close()


# --- UserPromptSubmit ------------------------------------------------------------------

def test_prompt_identique_au_courrier_accuse(projet, monkeypatch, capsys):
    m = poster(projet, "coord-x", WORKER, resume="va", attend="reponse")
    c, ligne = livrer_par_tmux(projet, WORKER)
    assert lancer(monkeypatch, capsys, "UserPromptSubmit", WORKER, {"prompt": ligne}) == (0, "", "")
    assert etat(projet, m) == "pris_en_compte"
    (preuve,) = lignes(projet, "SELECT preuve FROM transitions WHERE etat='pris_en_compte'")
    p = json.loads(preuve[0])
    assert p["evenement"] == "UserPromptSubmit" and p["evenement_id"]
    assert lignes(projet, "SELECT etat FROM courriers") == [("acquitte",)]


def test_prompt_accuse_et_clot_sans_obligation(projet, monkeypatch, capsys):
    m = poster(projet, "coord-x", WORKER, resume="info")
    _, ligne = livrer_par_tmux(projet, WORKER)
    lancer(monkeypatch, capsys, "UserPromptSubmit", WORKER, {"prompt": ligne + "\n"})
    assert etat(projet, m) == "clos"


def test_lot_entier_accuse_par_un_seul_prompt(projet, monkeypatch, capsys):
    a = poster(projet, "coord-x", WORKER, resume="un", attend="reponse")
    b = poster(projet, "cime", WORKER, resume="deux", attend="reponse")
    _, ligne = livrer_par_tmux(projet, WORKER)
    assert " ‖ " in ligne
    lancer(monkeypatch, capsys, "UserPromptSubmit", WORKER, {"prompt": ligne})
    assert etat(projet, a) == etat(projet, b) == "pris_en_compte"


def test_prompt_mele_a_une_frappe_pas_d_accuse_signalement_utilisateur(projet, monkeypatch, capsys):
    m = poster(projet, "coord-x", WORKER, resume="va", attend="reponse")
    _, ligne = livrer_par_tmux(projet, WORKER)
    lancer(monkeypatch, capsys, "UserPromptSubmit", WORKER, {"prompt": "bonjour " + ligne})
    assert etat(projet, m) == "livre"  # pas d'accusé ; le bail expirera
    # préfixe correct mais texte altéré
    lancer(monkeypatch, capsys, "UserPromptSubmit", WORKER, {"prompt": ligne + " xx"})
    assert etat(projet, m) == "livre"
    assert lignes(projet, "SELECT de, a, nature, objet FROM messages WHERE nature='signalement'") == [
        ("cime", "utilisateur", "signalement", f"melange:{WORKER}")]  # une seule fois (unique)
    transitions = {r[0] for r in lignes(projet, "SELECT DISTINCT etat FROM transitions")}
    assert transitions <= {"inscrit", "livre"}  # aucun état ajouté


def test_identifiant_jamais_reconnu_chez_un_non_destinataire(projet, monkeypatch, capsys):
    m = poster(projet, "assistant", "coord-x", resume="va", attend="reponse")
    _, ligne = livrer_par_tmux(projet, "coord-x")
    lancer(monkeypatch, capsys, "UserPromptSubmit", "coord-y", {"prompt": ligne})
    lancer(monkeypatch, capsys, "UserPromptSubmit", WORKER, {"prompt": ligne})
    assert etat(projet, m) == "livre"
    assert lignes(projet, "SELECT count(*) FROM messages WHERE nature='signalement'") == [(0,)]


@pytest.mark.parametrize("prompt", [
    "écris (#1) pour voir", "<task-notification>Assistant : x (#1)</task-notification>",
    "Assistant : sans identifiant", ""])
def test_prompt_sans_motif_ne_fait_rien(projet, monkeypatch, capsys, prompt):
    m = poster(projet, "assistant", WORKER, resume="x", attend="reponse")
    livrer_par_tmux(projet, WORKER)
    lancer(monkeypatch, capsys, "UserPromptSubmit", WORKER, {"prompt": prompt})
    assert etat(projet, m) == "livre"


@pytest.mark.parametrize("de,equipe,prefixe", [
    ("utilisateur", None, "Utilisateur : "),
    ("assistant", None, "Assistant : "),
    ("cime", None, "Cime : "),
    ("coord-x", None, "coordinateur x : "),
    ("worker-x-t", "x", "worker x/t : "),
    ("worker-mon-eq-tache-1", "mon-eq", "worker mon-eq/tache-1 : "),
    ("worker-alpha", None, "worker alpha : "),
])
def test_chaque_emetteur_rendu_par_emetteur_lisible_est_reconnu_par_le_prefixe(tmp_path, de, equipe, prefixe):
    """Le texte tapé par le facteur pour un message de cet émetteur commence par le préfixe attendu :
    le préfixe est lu depuis les mêmes mots que `emetteur_lisible`, et chaque mot est épinglé ici."""
    m = {"id": 7, "de": de, "equipe": equipe, "corps": None, "resume": "va"}
    texte = courrier.formater(None, courrier.Courrier(1, WORKER, "tmux", 1, [m]), "tmux", tmp_path)
    assert texte.startswith(prefixe)
    assert hooks._PREFIXE.match(texte), texte


def test_livraison_par_hook_n_est_pas_accusee_par_prompt(projet, monkeypatch, capsys):
    m = poster(projet, "assistant", WORKER, resume="x", attend="reponse")
    code, _, err = lancer(monkeypatch, capsys, "PostToolUse", WORKER, {})
    assert code == 2
    lancer(monkeypatch, capsys, "UserPromptSubmit", WORKER, {"prompt": err.strip()})
    assert etat(projet, m) == "livre"


# --- SessionStart ----------------------------------------------------------------------

def test_session_start_rend_la_reprise_et_accuse_le_courrier(projet, monkeypatch, capsys):
    m = poster(projet, "assistant", "coord-x", resume="reprends ici", attend="reponse",
               corps="détail complet du message")
    code, out, err = lancer(monkeypatch, capsys, "SessionStart", "coord-x", {"source": "startup"})
    assert code == 0 and err == ""
    assert "Reprise de coord-x" in out and "(c) Courrier" in out and "reprends ici" in out
    assert "détail complet du message" in out
    assert etat(projet, m) == "pris_en_compte"
    (preuve,) = lignes(projet, "SELECT preuve FROM transitions WHERE etat='pris_en_compte'")
    assert json.loads(preuve[0])["preuve"] == "indirecte"
    assert lignes(projet, "SELECT voie FROM courriers") == [("hook:SessionStart",)]


@pytest.mark.parametrize("source", ["resume", "compact"])
def test_session_start_sans_tour_rend_la_reprise_sans_prendre_le_courrier(projet, monkeypatch, capsys, source):
    """Une ouverture sans message (reprise, compactage au repos) ne prouve pas que l'agent a lu le
    courrier : la reprise est rendue, le courrier reste `inscrit` pour le facteur, rien n'est écrit."""
    m = poster(projet, "assistant", "coord-x", resume="reprends ici", attend="reponse",
               corps="détail complet du message")
    code, out, err = lancer(monkeypatch, capsys, "SessionStart", "coord-x", {"source": source})
    assert code == 0 and err == ""
    assert "Reprise de coord-x" in out and "Courrier remis" not in out
    assert etat(projet, m) == "inscrit"
    assert lignes(projet, "SELECT count(*) FROM courriers") == [(0,)]


def test_session_start_sans_agent_ne_rend_rien(projet, monkeypatch, capsys):
    poster(projet, "assistant", "coord-x")
    assert lancer(monkeypatch, capsys, "SessionStart", None, {"source": "startup"}) == (0, "", "")
    assert lignes(projet, "SELECT count(*) FROM courriers") == [(0,)]


# --- PermissionRequest ------------------------------------------------------------------

def test_permission_d_un_coordinateur_inscrit_un_signalement_autorisation_pour_l_assistant(
        projet, monkeypatch, capsys):
    """Comportement conservé : une demande `libre` d'un coordinateur va à l'Assistant,
    échéance immédiate."""
    lancer(monkeypatch, capsys, "PermissionRequest", "coord-x",
           {"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": str(projet)})
    [(demande,)] = lignes(projet, "SELECT json_extract(details,'$.demande_id') FROM evenements"
                                  " WHERE evenement='PermissionRequest'")
    assert lignes(projet, "SELECT de, a, nature, objet FROM messages") == [
        ("cime", "assistant", "signalement", f"autorisation:{demande}")]
    assert lignes(projet, "SELECT debiteur, attendu, echeance, etat FROM obligations"
                          " JOIN messages m ON m.id = message_id") [0][:2] == ("assistant", "decision")
    h, e = lignes(projet, "SELECT m.horodatage, o.echeance FROM obligations o JOIN messages m"
                          " ON m.id = o.message_id")[0]
    assert h == e  # échéance immédiate


def test_permission_d_un_worker_inscrit_un_signalement_autorisation_pour_son_coordinateur(
        projet, monkeypatch, capsys):
    """Une demande `libre` d'un worker
    va à son coordinateur, avec la classe dans le `corps`."""
    lancer(monkeypatch, capsys, "PermissionRequest", WORKER,
           {"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": str(projet)})
    [(demande,)] = lignes(projet, "SELECT json_extract(details,'$.demande_id') FROM evenements"
                                  " WHERE evenement='PermissionRequest'")
    assert lignes(projet, "SELECT de, a, nature, objet, json_extract(corps, '$.classe') FROM messages") == [
        ("cime", "coord-x", "signalement", f"autorisation:{demande}", "libre")]
    assert lignes(projet, "SELECT debiteur, attendu, echeance, etat FROM obligations"
                          " JOIN messages m ON m.id = message_id") [0][:2] == ("coord-x", "decision")


# --- PreToolUse : refus du garde ----------------------------------------------------------

@pytest.mark.parametrize("agent,sup", [(WORKER, "coord-x"), ("coord-x", "assistant")])
def test_refus_du_garde_signale_au_superieur(projet, monkeypatch, capsys, agent, sup):
    code, out, _ = lancer(monkeypatch, capsys, "PreToolUse", agent,
                          {"tool_name": "Bash", "tool_input": {"command": "git push origin main"}})
    assert code == 0 and json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"
    [(evt,)] = lignes(projet, "SELECT id FROM evenements WHERE evenement='PreToolUse'")
    assert lignes(projet, "SELECT de, a, nature, objet FROM messages") == [
        ("cime", sup, "signalement", f"refus-garde:{evt}")]


def test_refus_du_garde_de_l_assistant_n_inscrit_rien(projet, monkeypatch, capsys):
    code, out, _ = lancer(monkeypatch, capsys, "PreToolUse", "assistant",
                          {"tool_name": "Bash", "tool_input": {"command": "git push origin main"}})
    assert "deny" in out
    assert lignes(projet, "SELECT count(*) FROM messages") == [(0,)]


def test_commande_permise_n_inscrit_pas_de_signalement(projet, monkeypatch, capsys):
    lancer(monkeypatch, capsys, "PreToolUse", WORKER,
           {"tool_name": "Bash", "tool_input": {"command": "ls"}})
    assert lignes(projet, "SELECT count(*) FROM messages") == [(0,)]


# --- SessionEnd -------------------------------------------------------------------------

def test_session_end_avec_obligation_signale_session_disparue_une_fois(projet, monkeypatch, capsys):
    poster(projet, "cime", WORKER, attend="travail_pret", objet="tache:x:tache")
    for _ in range(2):
        lancer(monkeypatch, capsys, "SessionEnd", WORKER, {"reason": "other"})
    assert lignes(projet, "SELECT de, a, nature, objet FROM messages WHERE nature='signalement'") == [
        ("cime", "coord-x", "signalement", f"session-disparue:{WORKER}")]


def test_session_end_coordinateur_previent_l_assistant(projet, monkeypatch, capsys):
    poster(projet, "assistant", "coord-x", attend="reponse")
    lancer(monkeypatch, capsys, "SessionEnd", "coord-x", {"reason": "other"})
    assert lignes(projet, "SELECT a, objet FROM messages WHERE nature='signalement'") == [
        ("assistant", "session-disparue:coord-x")]


def test_session_end_apres_terminer_ne_signale_rien(projet, monkeypatch, capsys):
    poster(projet, "cime", WORKER, attend="travail_pret", objet="tache:x:tache")
    poster(projet, "coord-x", WORKER, objet="fin:tache")
    lancer(monkeypatch, capsys, "SessionEnd", WORKER, {"reason": "other"})
    assert lignes(projet, "SELECT count(*) FROM messages WHERE nature='signalement'") == [(0,)]


@pytest.mark.parametrize("agent,reason", [(WORKER, "other"), ("assistant", "other")])
def test_session_end_sans_obligation_ou_assistant_rien(projet, monkeypatch, capsys, agent, reason):
    if agent == "assistant":
        poster(projet, "coord-x", "assistant", nature="question", attend=None)
    lancer(monkeypatch, capsys, "SessionEnd", agent, {"reason": reason})
    assert lignes(projet, "SELECT count(*) FROM messages WHERE nature='signalement'") == [(0,)]


def test_session_end_clear_ne_signale_rien(projet, monkeypatch, capsys):
    poster(projet, "cime", WORKER, attend="travail_pret", objet="tache:x:tache")
    lancer(monkeypatch, capsys, "SessionEnd", WORKER, {"reason": "clear"})
    assert lignes(projet, "SELECT count(*) FROM messages WHERE nature='signalement'") == [(0,)]
