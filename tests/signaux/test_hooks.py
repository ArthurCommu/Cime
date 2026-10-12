"""Livraison par PostToolUse et Stop, attente à l'arrêt, dette, StopFailure."""
import argparse
import io
import json
import sys
import threading

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
    monkeypatch.setenv(VAR_AGENT, agent)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(
        {"session_id": "s", **(entree or {})})))
    code = hook.executer(argparse.Namespace(evenement=evenement))
    sortie = capsys.readouterr()
    return code, sortie.out, sortie.err


def lignes(projet, requete, params=()):
    conn = ouvrir(projet)
    try:
        return conn.execute(requete, params).fetchall()
    finally:
        conn.close()


# --- PostToolUse -------------------------------------------------------------------------

def test_post_tool_use_sans_courrier_ne_dit_rien(projet, monkeypatch, capsys):
    assert lancer(monkeypatch, capsys, "PostToolUse", "coord-x", {"tool_name": "Bash"}) == (0, "", "")


def test_post_tool_use_rend_le_courrier_code_2_stderr(projet, monkeypatch, capsys):
    m = poster(projet, "assistant", "coord-x", corps="fais A\nputis B", resume="A et B")
    code, out, err = lancer(monkeypatch, capsys, "PostToolUse", "coord-x", {"tool_name": "Bash"})
    assert code == 2 and out == "" and err == f"Assistant : fais A\nputis B (#{m})\n"
    assert lignes(projet, "SELECT voie, a, etat FROM courriers") == [
        ("hook:PostToolUse", "coord-x", "ouvert")]
    preuve = json.loads(lignes(projet, "SELECT preuve FROM transitions WHERE etat='livre'")[0][0])
    assert preuve["evenement"] == "PostToolUse" and preuve["evenement_id"] and preuve["octets"]
    # deuxième appel : le courrier est déjà pris, rien n'est redonné
    assert lancer(monkeypatch, capsys, "PostToolUse", "coord-x", {"tool_name": "Bash"})[0] == 0


def test_post_tool_use_d_un_autre_agent_ne_prend_rien(projet, monkeypatch, capsys):
    poster(projet, "assistant", "coord-x")
    assert lancer(monkeypatch, capsys, "PostToolUse", "coord-y", {})[0] == 0
    assert lignes(projet, "SELECT count(*) FROM courriers") == [(0,)]


def test_deux_post_tool_use_simultanes_un_seul_rend(projet):
    poster(projet, "assistant", "coord-x")
    ouvrir(projet).close()
    barriere = threading.Barrier(2)
    textes = []

    def agir():
        conn = ouvrir(projet)
        try:
            barriere.wait()
            evt = conn.execute("INSERT INTO evenements (horodatage, agent, session_id, evenement,"
                               " details) VALUES ('2026-10-09T00:00:00.000Z','coord-x','s',"
                               "'PostToolUse','{}')").lastrowid
            conn.commit()
            textes.append(hooks.sur_post_tool_use(conn, projet, "coord-x", evt))
        finally:
            conn.close()

    fils = [threading.Thread(target=agir) for _ in range(2)]
    [f.start() for f in fils]
    [f.join() for f in fils]
    assert sorted(t is not None for t in textes) == [False, True]


def test_accuse_indirect_par_le_post_tool_use_suivant(projet, monkeypatch, capsys):
    m = poster(projet, "assistant", "coord-x")
    lancer(monkeypatch, capsys, "PostToolUse", "coord-x", {})
    assert etat_message(ouvrir(projet), m) == "livre"
    lancer(monkeypatch, capsys, "PostToolUse", "coord-x", {})
    conn = ouvrir(projet)
    assert etat_message(conn, m) == "clos"  # attend rien : aucune obligation
    preuve = json.loads(conn.execute("SELECT preuve FROM transitions WHERE etat='pris_en_compte'"
                                     ).fetchone()[0])
    assert preuve["preuve"] == "indirecte"
    assert conn.execute("SELECT etat FROM courriers").fetchone() == ("acquitte",)


# --- Stop : ordre (1)(2)(3) ------------------------------------------------------------

def test_stop_ecrit_son_evenement_puis_rend_le_courrier(projet, monkeypatch, capsys):
    m = poster(projet, "coord-x", WORKER, resume="va")
    code, _, err = lancer(monkeypatch, capsys, "Stop", WORKER, {"last_assistant_message": "ok"})
    assert code == 2 and err == f"coordinateur x : va (#{m})\n"
    assert lignes(projet, "SELECT evenement FROM evenements") == [("Stop",)]


def test_stop_courrier_passe_avant_la_dette(projet, monkeypatch, capsys):
    poster(projet, "coord-x", WORKER, resume="d'abord", attend="reponse")
    code, _, err = lancer(monkeypatch, capsys, "Stop", WORKER, {})
    assert code == 2 and "d'abord" in err and "Tu dois encore" not in err


def test_stop_dette_une_seule_fois_grace_a_stop_hook_active(projet, monkeypatch, capsys):
    m = poster(projet, "coord-x", WORKER, resume="la tâche", attend="travail_pret",
               objet="tache:x:tache")
    lancer(monkeypatch, capsys, "Stop", WORKER, {})  # livre le courrier
    lancer(monkeypatch, capsys, "PostToolUse", WORKER, {})  # accuse indirectement
    code, _, err = lancer(monkeypatch, capsys, "Stop", WORKER, {"stop_hook_active": False})
    assert code == 2 and err.startswith("Tu dois encore : travail_pret pour coordinateur x")
    assert "la tâche" in err and f"#{m}" in err
    code, _, err = lancer(monkeypatch, capsys, "Stop", WORKER, {"stop_hook_active": True})
    assert (code, err) == (0, "")


def test_fin_sans_suite_immediat_une_seule_fois(projet, monkeypatch, capsys):
    m = poster(projet, "cime", WORKER, resume="la tâche", attend="travail_pret",
           objet="tache:x:tache")
    lancer(monkeypatch, capsys, "Stop", WORKER, {})  # courrier
    lancer(monkeypatch, capsys, "PostToolUse", WORKER, {})
    lancer(monkeypatch, capsys, "Stop", WORKER, {"stop_hook_active": True})
    lancer(monkeypatch, capsys, "Stop", WORKER, {"stop_hook_active": True})
    signaux = lignes(projet, "SELECT de, a, nature, objet, resume FROM messages"
                             " WHERE nature = 'signalement'")
    assert len(signaux) == 1
    assert signaux[0][:4] == ("cime", "coord-x", "signalement", f"fin-sans-suite:{WORKER}:{m}")   # clé = worker + obligation


def test_pas_de_fin_sans_suite_pour_un_coordinateur_ni_sans_travail_pret(projet, monkeypatch, capsys):
    poster(projet, "assistant", "coord-x", resume="q", attend="reponse")
    lancer(monkeypatch, capsys, "Stop", "coord-x", {})
    lancer(monkeypatch, capsys, "PostToolUse", "coord-x", {})
    lancer(monkeypatch, capsys, "Stop", "coord-x", {"stop_hook_active": True})
    poster(projet, "coord-x", WORKER, resume="q", attend="reponse")
    lancer(monkeypatch, capsys, "Stop", WORKER, {})
    lancer(monkeypatch, capsys, "PostToolUse", WORKER, {})
    lancer(monkeypatch, capsys, "Stop", WORKER, {"stop_hook_active": True})
    assert lignes(projet, "SELECT count(*) FROM messages WHERE nature='signalement'") == [(0,)]


# --- Stop : attente --------------------------------------------------------------------

def test_stop_attend_un_message_via_cime_attente_stop(projet, monkeypatch, capsys):
    monkeypatch.setenv("CIME_ATTENTE_STOP", "2")
    horloge = {"t": 0.0}
    monkeypatch.setattr(hooks, "_horloge", lambda: horloge["t"])

    def dormir(s):
        horloge["t"] += s
        if horloge["t"] >= 1:  # un message arrive pendant l'attente
            if not lignes(projet, "SELECT 1 FROM messages"):
                poster(projet, "coord-x", WORKER, resume="arrivé")
    monkeypatch.setattr(hooks, "_dormir", dormir)
    code, _, err = lancer(monkeypatch, capsys, "Stop", WORKER, {})
    assert code == 2 and "arrivé" in err
    preuve = json.loads(lignes(projet, "SELECT preuve FROM transitions WHERE etat='livre'")[0][0])
    assert preuve["attente_s"] == 1


def test_stop_attend_puis_sort_en_0(projet, monkeypatch, capsys):
    monkeypatch.setenv("CIME_ATTENTE_STOP", "3")
    horloge = {"t": 0.0}
    dormis = []
    monkeypatch.setattr(hooks, "_horloge", lambda: horloge["t"])
    monkeypatch.setattr(hooks, "_dormir", lambda s: (dormis.append(s), horloge.update(t=horloge["t"] + s)))
    assert lancer(monkeypatch, capsys, "Stop", WORKER, {}) == (0, "", "")
    assert dormis == [1.0, 1.0, 1.0]


def test_attente_par_defaut_120_et_zero_pour_l_assistant(monkeypatch):
    monkeypatch.delenv("CIME_ATTENTE_STOP", raising=False)
    assert hooks.attente_stop("coord-x") == 120 and hooks.attente_stop("assistant") == 0
    monkeypatch.setenv("CIME_ATTENTE_STOP", "7")
    assert hooks.attente_stop("coord-x") == 7 and hooks.attente_stop("assistant") == 0


def test_assistant_ni_attente_ni_dette_seulement_le_courrier(projet, monkeypatch, capsys):
    monkeypatch.setenv("CIME_ATTENTE_STOP", "50")
    poster(projet, "coord-x", "assistant", nature="question", resume="et alors ?", attend=None)
    dormis = []
    monkeypatch.setattr(hooks, "_dormir", dormis.append)
    code, _, err = lancer(monkeypatch, capsys, "Stop", "assistant", {})
    assert code == 2 and "et alors ?" in err  # (1) courrier
    lancer(monkeypatch, capsys, "PostToolUse", "assistant", {})
    # dette ouverte (la question), stop_hook_active faux : aucun rappel, aucune attente
    assert lancer(monkeypatch, capsys, "Stop", "assistant", {"stop_hook_active": False}) == (0, "", "")
    assert dormis == []


# --- StopFailure -----------------------------------------------------------------------

@pytest.mark.parametrize("agent,sup", [(WORKER, "coord-x"), ("coord-x", "assistant"),
                                       ("assistant", "utilisateur")])
def test_stop_failure_signale_au_superieur(projet, monkeypatch, capsys, agent, sup):
    assert lancer(monkeypatch, capsys, "StopFailure", agent,
                  {"error": "rate_limit", "last_assistant_message": "x"}) == (0, "", "")
    [(de, a, nature, objet, resume)] = lignes(
        projet, "SELECT de, a, nature, objet, resume FROM messages")
    assert (de, a, nature, objet) == ("cime", sup, "signalement", f"erreur-api:{agent}")
    assert "rate_limit" in resume
    assert lignes(projet, "SELECT evenement FROM evenements") == [("StopFailure",)]
