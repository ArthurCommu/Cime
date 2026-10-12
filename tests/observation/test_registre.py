"""Lecture du registre : fil, état des agents déduit des hooks, obligations, signaux, WAL et performance."""

import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from chrono import meilleur

from cime.observation import registre
from cime.signaux import matrice
from cime.observation.registre import lire_registre

HOOKS = Path(__file__).parent / "fixtures" / "hooks"
MAINTENANT = datetime(2026, 10, 7, 14, 0, 0, tzinfo=timezone.utc)

SCHEMA = """
CREATE TABLE messages (id INTEGER PRIMARY KEY, horodatage TEXT, de TEXT, a TEXT, nature TEXT,
  resume TEXT, fichier TEXT, en_reponse_a INTEGER, equipe TEXT, objet TEXT, corps TEXT);
CREATE TABLE transitions (id INTEGER PRIMARY KEY, horodatage TEXT, message_id INTEGER, etat TEXT,
  courrier_id INTEGER, auteur TEXT, preuve TEXT);
CREATE TABLE obligations (id INTEGER PRIMARY KEY, message_id INTEGER UNIQUE, debiteur TEXT,
  attendu TEXT, echeance TEXT, etat TEXT, relances INTEGER DEFAULT 0, prochaine TEXT, ferme_par INTEGER);
CREATE TABLE courriers (id INTEGER PRIMARY KEY, a TEXT, voie TEXT, cree TEXT, expire TEXT, etat TEXT,
  tentative INTEGER DEFAULT 1);
CREATE TABLE ordres (id INTEGER PRIMARY KEY, horodatage TEXT, auteur TEXT, verbe TEXT, cible TEXT,
  parametres TEXT, etat TEXT, resultat TEXT, fini TEXT);
CREATE TABLE facteur (id INTEGER PRIMARY KEY, battement TEXT, version TEXT);
CREATE TABLE occupation (agent TEXT PRIMARY KEY, occupe_par TEXT, maj TEXT);
CREATE TABLE evenements (id INTEGER PRIMARY KEY, horodatage TEXT, agent TEXT, session_id TEXT,
  evenement TEXT, details TEXT);
CREATE TABLE journal (id INTEGER PRIMARY KEY, horodatage TEXT, auteur TEXT, action TEXT,
  cible TEXT, details TEXT, resultat TEXT);
"""


def iso(minutes_ago: float = 0.0) -> str:
    dt = MAINTENANT - timedelta(minutes=minutes_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def hook(nom: str) -> dict:
    return json.loads((HOOKS / f"{nom}.json").read_text(encoding="utf-8"))


class Base:
    def __init__(self, racine: Path, journal: bool = True):
        self.racine = racine
        (racine / ".orga" / "etat").mkdir(parents=True)
        self.chemin = racine / ".orga" / "etat" / "registre.sqlite"
        self.conn = sqlite3.connect(self.chemin)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA if journal else SCHEMA.split("CREATE TABLE journal")[0])

    def evt(self, agent, evenement, fixture, minutes_ago, **remplace):
        det = hook(fixture)
        det.update(remplace)
        cur = self.conn.execute(
            "INSERT INTO evenements (horodatage, agent, session_id, evenement, details) VALUES (?,?,?,?,?)",
            (iso(minutes_ago), agent, det.get("session_id"), evenement, json.dumps(det)))
        self.conn.commit()
        return cur.lastrowid

    def msg(self, de, a, nature, minutes_ago, resume="x", en_reponse_a=None, equipe=None, fichier=None,
            id=None, objet=None, obligation=True):
        """Comme `cime envoyer` : le message, l'obligation que la matrice en tire, la transition
        `inscrit` ; une `reponse` de son débiteur ferme l'obligation du message cité."""
        cur = self.conn.execute(
            "INSERT INTO messages (id, horodatage, de, a, nature, resume, fichier, en_reponse_a, equipe, objet)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (id, iso(minutes_ago), de, a, nature, resume, fichier, en_reponse_a, equipe, objet))
        ident = cur.lastrowid
        self.conn.execute("INSERT INTO transitions (horodatage, message_id, etat, auteur, preuve)"
                          " VALUES (?,?,'inscrit',?,'{}')", (iso(minutes_ago), ident, de))
        regle = matrice.obligation(nature, a, objet) if obligation else None
        if regle:
            self.conn.execute("INSERT INTO obligations (message_id, debiteur, attendu, etat)"
                              " VALUES (?,?,?,'ouverte')", (ident, *regle[:2]))
        if nature == "reponse" and en_reponse_a is not None:
            self.conn.execute("UPDATE obligations SET etat='satisfaite', ferme_par=? WHERE message_id=?"
                              " AND debiteur=? AND etat='ouverte'", (ident, en_reponse_a, de))
        self.conn.commit()
        return ident

    def satisfaire(self, message_id):
        self.conn.execute("UPDATE obligations SET etat='satisfaite' WHERE message_id=?", (message_id,))
        self.conn.commit()

    def journal(self, action, cible, minutes_ago=0, resultat="ok"):
        self.conn.execute("INSERT INTO journal (horodatage, auteur, action, cible, resultat) VALUES (?,?,?,?,?)",
                          (iso(minutes_ago), "hote", action, cible, resultat))
        self.conn.commit()


@pytest.fixture
def base(tmp_path):
    b = Base(tmp_path)
    yield b
    b.conn.close()


def lire(base):
    donnees, source = lire_registre(base.racine, MAINTENANT)
    assert source == {"nom": "registre", "ok": True}, source
    return donnees


def agent(base, nom="worker-observation-t2"):
    return lire(base)["agents"][nom]


W = "worker-observation-t2"


# --- réponse de l'utilisateur depuis la page ------------------------------------------------------

DID = "3f2c9a40-0000-4000-8000-000000000001"


@pytest.mark.parametrize("action", ["refuser", "autoriser"])
def test_reponse_page_ferme_la_demande(base, action):
    base.evt(W, "Stop", "Stop", 20)
    base.evt(W, "PermissionRequest", "PermissionRequest-Bash", 6, demande_id=DID)
    base.evt(W, "Notification", "Notification-permission_prompt", 5.9)
    base.journal(action, f"perm-{DID}", 5)
    a = agent(base)
    assert a["etat"] == "au_repos" and a["autorisation_ouverte"] is None


def test_reponse_page_en_erreur_laisse_la_demande_ouverte(base):
    base.evt(W, "PermissionRequest", "PermissionRequest-Bash", 6, demande_id=DID)
    base.journal("refuser", f"perm-{DID}", 5, resultat="erreur: tmux absent")
    a = agent(base)
    assert a["etat"] == "attend_autorisation" and a["autorisation_ouverte"]["demande_id"] == DID


def test_reponse_page_pour_une_autre_demande_laisse_ouverte(base):
    base.evt(W, "PermissionRequest", "PermissionRequest-Bash", 6, demande_id=DID)
    base.journal("refuser", "perm-autre", 5)
    assert agent(base)["etat"] == "attend_autorisation"


def test_reponse_page_journal_absent_laisse_ouverte(tmp_path):
    b = Base(tmp_path, journal=False)
    b.evt(W, "PermissionRequest", "PermissionRequest-Bash", 6, demande_id=DID)
    donnees, source = lire_registre(tmp_path, MAINTENANT)
    b.conn.close()
    assert source["ok"] is True and donnees["agents"][W]["etat"] == "attend_autorisation"


def test_reponse_page_ferme_aussi_les_notifications_anterieures(base):
    base.evt(W, "Notification", "Notification-permission_prompt", 7)
    base.evt(W, "PermissionRequest", "PermissionRequest-Bash", 6, demande_id=DID)
    base.journal("refuser", f"perm-{DID}", 5)
    assert agent(base)["etat"] == "au_repos"  # le refus compte comme un Stop
    base.evt(W, "Notification", "Notification-permission_prompt", 1)  # postérieure : rouvre
    assert agent(base)["etat"] == "attend_autorisation"


# --- un refus depuis la page met l'agent au repos (Escape : aucun hook) ---------

def test_refus_page_apres_le_prompt_met_au_repos(base):
    # T14 de l'hôte : l'agent restait « travaille » indéfiniment.
    base.evt(W, "UserPromptSubmit", "UserPromptSubmit", 10)
    base.evt(W, "PostToolUse", "PostToolUse-Read", 8)
    base.evt(W, "PermissionRequest", "PermissionRequest-Bash", 6, demande_id=DID)
    base.journal("refuser", f"perm-{DID}", 5)
    a = agent(base)
    assert (a["etat"], a["etat_depuis"], a["etat_source"]) == ("au_repos", iso(5), "journal:refuser")
    assert a["autorisation_ouverte"] is None


def test_refus_page_suivi_d_un_prompt_travaille(base):
    base.evt(W, "PermissionRequest", "PermissionRequest-Bash", 6, demande_id=DID)
    base.journal("refuser", f"perm-{DID}", 5)
    base.evt(W, "UserPromptSubmit", "UserPromptSubmit", 2)
    a = agent(base)
    assert (a["etat"], a["etat_source"]) == ("travaille", "hook:UserPromptSubmit")


def test_autorisation_page_ne_met_pas_au_repos(base):
    base.evt(W, "UserPromptSubmit", "UserPromptSubmit", 10)
    base.evt(W, "PermissionRequest", "PermissionRequest-Bash", 6, demande_id=DID)
    base.journal("autoriser", f"perm-{DID}", 5)
    assert agent(base)["etat"] == "travaille"


def test_refus_page_en_erreur_ou_d_un_autre_agent_sans_effet(base):
    base.evt(W, "UserPromptSubmit", "UserPromptSubmit", 10)
    base.evt("coord-page", "UserPromptSubmit", "UserPromptSubmit", 10)
    base.evt("coord-page", "PermissionRequest", "PermissionRequest-Bash", 6, demande_id=DID)
    base.journal("refuser", f"perm-{DID}", 5)
    base.evt(W, "PermissionRequest", "PermissionRequest-Bash", 4, demande_id="d-w")
    base.journal("refuser", "perm-d-w", 3, resultat="erreur: tmux absent")
    assert agent(base, "coord-page")["etat"] == "au_repos"
    assert agent(base)["etat"] == "attend_autorisation"


# --- états -------------------------------------------------------------------------------

def test_incident_1_autorisation_en_attente_depuis_6_minutes(base):
    base.evt(W, "UserPromptSubmit", "UserPromptSubmit", 20)
    base.evt(W, "PermissionRequest", "PermissionRequest-Bash", 6, demande_id="3f2c9a40-0000-4000-8000-000000000001")
    a = agent(base)
    assert a["etat"] == "attend_autorisation"
    assert a["etat_depuis"] == iso(6)
    assert a["etat_source"] == "hook:PermissionRequest"
    assert a["autorisation_ouverte"] == {
        "demande_id": "3f2c9a40-0000-4000-8000-000000000001", "tool_name": "Bash",
        "resume_outil": "ls /home/exemple/projet",
        "depuis": iso(6)}


def test_notification_seule_attend_autorisation_sans_detail_d_outil(base):
    base.evt(W, "Notification", "Notification-permission_prompt", 3)
    a = agent(base)
    assert (a["etat"], a["etat_depuis"], a["etat_source"]) == (
        "attend_autorisation", iso(3), "hook:Notification:permission_prompt")
    assert a["autorisation_ouverte"] is None


def test_permission_puis_notification_etat_depuis_le_premier(base):
    base.evt(W, "PermissionRequest", "PermissionRequest-Write", 6)
    base.evt(W, "Notification", "Notification-permission_prompt", 5.9)
    a = agent(base)
    assert a["etat_depuis"] == iso(6)
    assert a["autorisation_ouverte"]["tool_name"] == "Write"
    assert a["autorisation_ouverte"]["resume_outil"].endswith("nouveau.txt")


def test_autre_notification_ne_declenche_pas_l_attente(base):
    base.evt(W, "Stop", "Stop", 10)
    base.evt(W, "Notification", "Notification-permission_prompt", 5, notification_type="idle_prompt")
    assert agent(base)["etat"] == "au_repos"


def test_autorisation_accordee_puis_travail_continu(base):
    base.evt(W, "PermissionRequest", "PermissionRequest-Write", 6)
    base.evt(W, "Notification", "Notification-permission_prompt", 5.9)
    base.evt(W, "PostToolUse", "PostToolUse-Write", 5.5)
    a = agent(base)
    assert a["etat"] == "travaille"
    assert (a["etat_depuis"], a["etat_source"]) == (iso(5.5), "hook:PostToolUse")
    assert a["autorisation_ouverte"] is None
    # une nouvelle demande, après, rouvre l'attente
    base.evt(W, "PermissionRequest", "PermissionRequest-Bash", 1)
    assert agent(base)["etat"] == "attend_autorisation"


@pytest.mark.parametrize("fermant,fixture", [("Stop", "Stop"), ("UserPromptSubmit", "UserPromptSubmit")])
def test_fermants_stop_et_prompt(base, fermant, fixture):
    base.evt(W, "PermissionRequest", "PermissionRequest-Bash", 6)
    base.evt(W, fermant, fixture, 4)
    assert agent(base)["etat"] != "attend_autorisation"


def test_stop_puis_rien_au_repos_avec_derniere_phrase(base):
    base.evt(W, "SessionStart", "SessionStart", 30)
    base.evt(W, "UserPromptSubmit", "UserPromptSubmit", 20)
    base.evt(W, "Stop", "Stop", 10)
    a = agent(base)
    assert (a["etat"], a["etat_depuis"], a["etat_source"]) == ("au_repos", iso(10), "hook:Stop")
    phrase = hook("Stop")["last_assistant_message"]
    assert a["derniere_phrase"] == (phrase if len(phrase) <= 300 else "…" + phrase[-299:])
    assert a["dernier_evenement"] == {"evenement": "Stop", "horodatage": iso(10)}
    assert a["modele"] == "claude-haiku-4-5-20251001"
    assert a["transcript_path"] == hook("Stop")["transcript_path"]
    assert a["session_id"] == hook("Stop")["session_id"]


def test_derniere_phrase_garde_la_fin_en_300_caracteres(base):
    # les annonces (« je lance maintenant… ») sont à la fin du message : on garde la fin
    base.evt(W, "Stop", "Stop", 10, last_assistant_message="début " + "é" * 1000 + " Je lance T2.")
    phrase = agent(base)["derniere_phrase"]
    assert len(phrase) == 300 and phrase.startswith("…é") and phrase.endswith("é Je lance T2.")


def test_derniere_phrase_courte_intacte(base):
    base.evt(W, "Stop", "Stop", 10, last_assistant_message="é" * 300)
    assert agent(base)["derniere_phrase"] == "é" * 300


def test_dernier_evenement_y_compris_session_end(base):
    base.evt(W, "Stop", "Stop", 10)
    base.evt(W, "SessionEnd", "SessionEnd", 9)
    a = agent(base)
    assert a["dernier_evenement"] == {"evenement": "SessionEnd", "horodatage": iso(9)}
    assert a["etat"] == "au_repos"  # SessionEnd ne change pas l'état calculé ici


def test_prompt_apres_stop_travaille(base):
    base.evt(W, "Stop", "Stop", 10)
    base.evt(W, "UserPromptSubmit", "UserPromptSubmit", 8)
    a = agent(base)
    assert (a["etat"], a["etat_source"]) == ("travaille", "hook:UserPromptSubmit")
    assert a["derniere_phrase"] is not None  # celle du dernier Stop


def test_posttooluse_apres_stop_travaille(base):
    base.evt(W, "Stop", "Stop", 10)
    base.evt(W, "PostToolUse", "PostToolUse-Read", 2)
    assert agent(base)["etat"] == "travaille"


def test_session_start_seul_est_inconnu_et_modele_absent_en_print(base):
    base.evt(W, "SessionStart", "SessionStart-print", 5)
    a = agent(base)
    assert (a["etat"], a["etat_depuis"], a["etat_source"]) == ("inconnu", None, None)
    assert "model" not in hook("SessionStart-print")
    assert a["modele"] is None


def test_session_start_compact_n_est_pas_un_changement_d_etat(base):
    base.evt(W, "Stop", "Stop", 10)
    base.evt(W, "SessionStart", "SessionStart-compact", 9)
    assert agent(base)["etat"] == "au_repos"


def test_agent_sans_evenement_absent_et_evenements_sans_agent_comptes(base):
    base.evt(None, "SessionStart", "SessionStart", 5)
    base.evt(None, "Stop", "Stop", 4)
    d = lire(base)
    assert d["agents"] == {}
    assert d["evenements_sans_agent"] == 2


def test_agents_independants(base):
    base.evt("coord-observation", "Stop", "Stop", 10)
    base.evt(W, "PermissionRequest", "PermissionRequest-Bash", 6)
    d = lire(base)["agents"]
    assert d["coord-observation"]["etat"] == "au_repos"
    assert d[W]["etat"] == "attend_autorisation"


def test_refus_garde_apparait_et_ne_change_pas_l_etat(base):
    base.evt(W, "Stop", "Stop", 10)
    refus = base.evt(W, "PreToolUse", "PostToolUse-Bash", 2, hook_event_name="PreToolUse",
                     tool_input={"command": "git push origin main"}, motif="git push interdit")
    d = lire(base)
    assert d["agents"][W]["etat"] == "au_repos"
    assert d["refus_garde"] == [{"id": refus, "agent": W, "horodatage": iso(2), "tool_name": "Bash",
                                 "resume_outil": "git push origin main", "motif": "git push interdit"}]


def test_refus_garde_tool_input_tronque_en_texte_et_limite_50(base):
    base.evt(W, "PreToolUse", "PostToolUse-Bash", 1, tool_input='{"command": "rm -rf /tm', motif="m")
    for i in range(60):
        base.evt(None, "PreToolUse", "PostToolUse-Bash", 100 - i, motif="m")
    refus = lire(base)["refus_garde"]
    assert len(refus) == 50
    assert refus[0]["resume_outil"] == '{"command": "rm -rf /tm' and refus[0]["agent"] == W
    assert refus[1]["agent"] is None


# --- messages, questions, attentes ---------------------------------------------------------

def test_question_12_en_attente_puis_repondue(base):
    for i in range(1, 12):
        base.msg("assistant", "coord-observation", "consigne", 100 - i, id=i)
    base.msg("coord-observation", "assistant", "question", 50, resume="Quel format ?", id=12)
    d = lire(base)
    assert d["questions_en_attente"] == [{"id": "msg-12", "de": "coord-observation", "a": "assistant",
                                          "horodatage": iso(50), "resume": "Quel format ?"}]
    assert next(m for m in d["fil"] if m["id"] == "msg-12")["en_attente"] is True
    assert next(m for m in d["fil"] if m["id"] == "msg-1")["en_attente"] is False
    base.msg("assistant", "coord-observation", "reponse", 40, en_reponse_a=12)
    d = lire(base)
    assert d["questions_en_attente"] == []
    assert next(m for m in d["fil"] if m["id"] == "msg-12")["en_attente"] is False


def test_questions_en_attente_hors_des_200_du_fil(base):
    base.msg("a", "b", "question", 1000, id=1)
    for i in range(2, 260):
        base.msg("a", "b", "consigne", 900 - i, id=i)
    d = lire(base)
    assert len(d["fil"]) == 200
    assert all(m["id"] != "msg-1" for m in d["fil"])
    assert [q["id"] for q in d["questions_en_attente"]] == ["msg-1"]


def test_fil_ordre_recent_d_abord_ids_texte(base):
    base.msg("assistant", "coord-x", "consigne", 5, id=1, fichier="/f")
    base.msg("coord-x", "assistant", "compte_rendu", 1, id=2)
    fil = lire(base)["fil"]
    assert [m["id"] for m in fil] == ["msg-2", "msg-1"]
    assert fil[1] == {"id": "msg-1", "horodatage": iso(5), "de": "assistant", "a": "coord-x",
                      "nature": "consigne", "resume": "x", "fichier": "/f", "en_attente": False,
                      "etat_livraison": "inscrit", "non_lu": False, "preuve": {}, "source": "registre"}


def test_fil_echanges_utilisateur_assistant_intercales(base):
    base.msg("assistant", "coord-x", "consigne", 10, id=1)
    p = base.evt("assistant", "UserPromptSubmit", "UserPromptSubmit", 12)
    s = base.evt("assistant", "Stop", "Stop", 8, last_assistant_message="Bonjour\n\nl'utilisateur " + "x" * 400)
    base.msg("coord-x", "assistant", "compte_rendu", 5, id=2)
    base.evt("coord-x", "UserPromptSubmit", "UserPromptSubmit", 6)  # autre agent : exclu
    base.evt("coord-x", "Stop", "Stop", 7)
    fil = lire(base)["fil"]
    assert [m["id"] for m in fil] == ["msg-2", f"evt-{s}", "msg-1", f"evt-{p}"]
    prompt, stop = fil[3], fil[1]
    assert (prompt["de"], prompt["a"], prompt["source"], prompt["nature"]) == ("utilisateur", "assistant", "hook", None)
    assert prompt["resume"] == hook("UserPromptSubmit")["prompt"]
    assert (stop["de"], stop["a"], stop["fichier"], stop["en_attente"]) == ("assistant", "utilisateur", None, False)
    assert stop["resume"].startswith("Bonjour l'utilisateur x") and len(stop["resume"]) == 160


def test_fil_ecarte_les_task_notifications(base):
    # Fin d'un agent en arrière-plan injectée comme prompt : l'utilisateur n'a rien tapé
    # Fabriqué : texte d'une vraie notification abrégé.
    n = base.evt("assistant", "UserPromptSubmit", "UserPromptSubmit", 4,
                 prompt="<task-notification>\n<task-id>b61h2of7p</task-id>\n<status>completed</status>")
    p = base.evt("assistant", "UserPromptSubmit", "UserPromptSubmit", 3)
    fil = lire(base)["fil"]
    assert [m["id"] for m in fil] == [f"evt-{p}"]
    assert lire(base)["agents"]["assistant"]["etat"] == "travaille"


def test_fil_garde_les_200_plus_recents_apres_fusion(base):
    for i in range(150):
        base.msg("a", "b", "consigne", 1000 - 2 * i, id=i + 1)
    for i in range(150):
        base.evt("assistant", "Stop", "Stop", 999 - 2 * i)
    fil = lire(base)["fil"]
    assert len(fil) == 200
    assert [m["horodatage"] for m in fil] == sorted((m["horodatage"] for m in fil), reverse=True)
    assert sum(m["source"] == "hook" for m in fil) == 100


def test_attentes_utilisateur_quatre_natures_puis_reponse_d_utilisateur(base):
    base.msg("coord-obs", "assistant", "demande_cloture", 50, id=1, equipe="obs")
    base.msg("assistant", "utilisateur", "rapport_utilisateur", 40, id=2, en_reponse_a=1, equipe="obs", fichier="/r.md", resume="Clôture ?")
    base.msg("assistant", "utilisateur", "rapport_utilisateur", 39, id=3, equipe="obs")
    base.msg("assistant", "utilisateur", "decision_utilisateur", 38, id=4, equipe="obs")
    base.msg("assistant", "utilisateur", "donnee_utilisateur", 37, id=5)
    att = {a["id"]: a for a in lire(base)["attentes_utilisateur"]}
    assert {i: a["nature"] for i, a in att.items()} == {
        "msg-2": "cloture", "msg-3": "rapport", "msg-4": "decision", "msg-5": "donnee"}
    assert att["msg-2"] == {"id": "msg-2", "message_id": 2, "objet": None, "horodatage": iso(40), "de": "assistant", "resume": "Clôture ?",
                            "fichier": "/r.md", "nature": "cloture", "equipe": "obs",
                            "origine": "coord-obs"}
    for i, cible in enumerate((2, 3, 4, 5)):
        base.msg("utilisateur", "assistant", "reponse", 30 - i, en_reponse_a=cible)
        restant = {a["id"] for a in lire(base)["attentes_utilisateur"]}
        assert restant == {f"msg-{c}" for c in (2, 3, 4, 5)} - {f"msg-{c}" for c in (2, 3, 4, 5)[: i + 1]}


def test_origine_cloture_est_le_demandeur_les_autres_le_message(base):
    base.msg("coord-obs", "assistant", "demande_cloture", 50, id=1)
    base.msg("assistant", "utilisateur", "rapport_utilisateur", 40, id=2, en_reponse_a=1)
    base.msg("assistant", "utilisateur", "rapport_utilisateur", 39, id=3)
    base.msg("assistant", "utilisateur", "decision_utilisateur", 38, id=4)
    base.msg("assistant", "utilisateur", "donnee_utilisateur", 37, id=5)
    o = {a["id"]: a["origine"] for a in lire(base)["attentes_utilisateur"]}
    assert o == {"msg-2": "coord-obs", "msg-3": "assistant", "msg-4": "assistant", "msg-5": "assistant"}


def test_une_reponse_d_un_autre_que_utilisateur_ne_clot_pas_l_attente(base):
    base.msg("assistant", "utilisateur", "decision_utilisateur", 40, id=1)
    base.msg("coord-x", "assistant", "reponse", 30, en_reponse_a=1)
    assert [a["id"] for a in lire(base)["attentes_utilisateur"]] == ["msg-1"]


def test_rapport_simple_disparait_apres_lu_au_journal(base):
    base.msg("assistant", "utilisateur", "rapport_utilisateur", 40, id=7)
    base.msg("assistant", "utilisateur", "rapport_utilisateur", 39, id=8)
    base.journal("autre", "msg-7")
    base.journal("lu", "msg-70")
    assert {a["id"] for a in lire(base)["attentes_utilisateur"]} == {"msg-7", "msg-8"}
    base.journal("lu", "msg-7")
    assert [a["id"] for a in lire(base)["attentes_utilisateur"]] == ["msg-8"]


def test_lu_ne_ferme_ni_decision_ni_cloture(base):
    base.msg("assistant", "coord-x", "demande_cloture", 50, id=1)
    base.msg("assistant", "utilisateur", "rapport_utilisateur", 40, id=2, en_reponse_a=1)
    base.msg("assistant", "utilisateur", "decision_utilisateur", 39, id=3)
    base.journal("lu", "msg-2")
    base.journal("lu", "msg-3")
    assert {a["id"] for a in lire(base)["attentes_utilisateur"]} == {"msg-2", "msg-3"}


def test_journal_absent_pas_d_erreur(tmp_path):
    b = Base(tmp_path, journal=False)
    b.msg("assistant", "utilisateur", "rapport_utilisateur", 40, id=1)
    donnees, source = lire_registre(tmp_path, MAINTENANT)
    b.conn.close()
    assert source["ok"] is True
    assert [a["id"] for a in donnees["attentes_utilisateur"]] == ["msg-1"]


def test_registre_vide_fil_vide_pas_none(base):
    d = lire(base)
    assert d["fil"] == [] and d["agents"] == {} and d["questions_en_attente"] == []
    assert d["attentes_utilisateur"] == [] and d["refus_garde"] == [] and d["evenements_sans_agent"] == 0


# --- échecs --------------------------------------------------------------------------------

def test_base_absente(tmp_path):
    donnees, source = lire_registre(tmp_path, MAINTENANT)
    assert donnees is None
    assert source == {"nom": "registre", "ok": False,
                      "erreur": f"registre absent : {tmp_path}/.orga/etat/registre.sqlite"}


def test_base_corrompue(tmp_path):
    (tmp_path / ".orga" / "etat").mkdir(parents=True)
    (tmp_path / ".orga" / "etat" / "registre.sqlite").write_bytes(b"ceci n'est pas du sqlite" * 200)
    donnees, source = lire_registre(tmp_path, MAINTENANT)
    assert donnees is None and source["ok"] is False and source["erreur"].startswith("registre illisible")


@pytest.mark.parametrize("manquante", ["messages", "evenements"])
def test_table_manquante(tmp_path, manquante):
    (tmp_path / ".orga" / "etat").mkdir(parents=True)
    conn = sqlite3.connect(tmp_path / ".orga" / "etat" / "registre.sqlite")
    conn.execute("CREATE TABLE " + ("evenements" if manquante == "messages" else "messages") + " (id INTEGER)")
    conn.commit()
    conn.close()
    donnees, source = lire_registre(tmp_path, MAINTENANT)
    assert donnees is None and not source["ok"]
    assert manquante in source["erreur"]


def test_colonne_manquante_est_un_echec_pas_une_exception(tmp_path):
    (tmp_path / ".orga" / "etat").mkdir(parents=True)
    conn = sqlite3.connect(tmp_path / ".orga" / "etat" / "registre.sqlite")
    conn.executescript("CREATE TABLE messages (id INTEGER); CREATE TABLE evenements (id INTEGER);")
    conn.commit()
    conn.close()
    donnees, source = lire_registre(tmp_path, MAINTENANT)
    assert donnees is None and source["ok"] is False


# --- lecture seule et WAL ---------------------------------------------------------------------

def test_connexion_en_lecture_seule(base):
    conn = registre._ouvrir(base.chemin)
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        conn.execute("INSERT INTO messages (de) VALUES ('x')")
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        conn.execute("CREATE TABLE t (x)")
    conn.close()


def test_lire_registre_n_ecrit_rien(base):
    base.msg("a", "b", "consigne", 1)
    avant = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in base.chemin.parent.iterdir()}
    lire(base)
    apres = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in base.chemin.parent.iterdir()}
    assert {k: v for k, v in avant.items() if not k.endswith("-shm")} == \
           {k: v for k, v in apres.items() if not k.endswith("-shm")}


def test_wal_ecrivain_actif_transaction_ouverte(base):
    base.msg("a", "b", "consigne", 5, id=1)
    base.conn.execute("BEGIN")  # écrivain actif, non validé
    base.conn.execute("INSERT INTO messages (id, horodatage, de, a, nature, resume) VALUES (2,?,?,?,?,?)",
                      (iso(1), "a", "b", "consigne", "non validé"))
    assert (base.chemin.parent / "registre.sqlite-wal").exists()
    assert [m["id"] for m in lire(base)["fil"]] == ["msg-1"]  # l'état validé, sans erreur ni attente
    base.conn.commit()
    assert [m["id"] for m in lire(base)["fil"]] == ["msg-2", "msg-1"]  # le WAL non checkpointé est lu


def test_wal_ecrivain_arrete_sans_wal_ni_shm(base):
    base.msg("a", "b", "consigne", 5, id=1)
    base.conn.close()  # dernière connexion : checkpoint, -wal et -shm supprimés
    assert not (base.chemin.parent / "registre.sqlite-wal").exists()
    assert not (base.chemin.parent / "registre.sqlite-shm").exists()
    d, source = lire_registre(base.racine, MAINTENANT)
    assert source["ok"] and [m["id"] for m in d["fil"]] == ["msg-1"]
    base.conn = sqlite3.connect(base.chemin)  # pour la fermeture de la fixture


def test_wal_shm_absent(base, tmp_path):
    """Écrivain tué : `-wal` conservé (transactions validées non checkpointées), `-shm` perdu."""
    base.msg("a", "b", "consigne", 5, id=1)
    copie = tmp_path / "copie"
    (copie / ".orga" / "etat").mkdir(parents=True)
    src = base.chemin
    for suffixe in ("", "-wal"):  # copie à chaud : -shm volontairement omis
        shutil.copy(str(src) + suffixe, str(copie / ".orga" / "etat" / ("registre.sqlite" + suffixe)))
    d, source = lire_registre(copie, MAINTENANT)
    # Mesuré (SQLite 3.51) : mode=ro fonctionne, relit le -wal et recrée un -shm (fichier d'index, pas de donnée).
    assert source["ok"] is True and [m["id"] for m in d["fil"]] == ["msg-1"]
    assert (copie / ".orga" / "etat" / "registre.sqlite-shm").exists()


# --- performance --------------------------------------------------------------------------------

def _grosse_base(tmp_path, indexes: bool):
    b = Base(tmp_path)
    agents = [f"worker-obs-t{i}" for i in range(30)] + ["assistant", "coord-obs"]
    types = ["PostToolUse"] * 8 + ["UserPromptSubmit", "Stop", "PermissionRequest", "Notification", "PreToolUse"]
    det = {"PostToolUse": json.dumps(hook("PostToolUse-Bash")), "UserPromptSubmit": json.dumps(hook("UserPromptSubmit")),
           "Stop": json.dumps(hook("Stop")), "PermissionRequest": json.dumps(hook("PermissionRequest-Bash")),
           "Notification": json.dumps(hook("Notification-permission_prompt")),
           "PreToolUse": json.dumps({**hook("PostToolUse-Bash"), "motif": "m"})}
    base_t = MAINTENANT - timedelta(days=3)
    lignes = []
    for i in range(50_000):
        t = types[i % len(types)]
        h = (base_t + timedelta(seconds=i * 5)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        lignes.append((h, agents[i % len(agents)] if i % 97 else None, "s", t, det[t]))
    b.conn.executemany("INSERT INTO evenements (horodatage, agent, session_id, evenement, details) VALUES (?,?,?,?,?)", lignes)
    natures = ["consigne", "question", "reponse", "compte_rendu", "rapport_utilisateur", "demande_cloture"]
    ms = []
    for i in range(10_000):
        h = (base_t + timedelta(seconds=i * 20)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        n = natures[i % 6]
        ms.append((h, "assistant", "coord-obs", n, "r", None, (i - 1) if n == "reponse" else None, "obs"))
    b.conn.executemany("INSERT INTO messages (horodatage, de, a, nature, resume, fichier, en_reponse_a, equipe) VALUES (?,?,?,?,?,?,?,?)", ms)
    if indexes:
        b.conn.executescript(INDEX)
    b.conn.commit()
    return b


INDEX = """
CREATE INDEX ev_agent_evt ON evenements (agent, evenement, horodatage, id);
CREATE INDEX ev_agent ON evenements (agent, horodatage, id);
CREATE INDEX ev_evt ON evenements (evenement, horodatage, id);
CREATE INDEX msg_horo ON messages (horodatage, id);
CREATE INDEX msg_repond ON messages (en_reponse_a, nature);
CREATE INDEX msg_nature ON messages (nature, horodatage, id);
"""


@pytest.mark.parametrize("indexes", [True, False], ids=["avec_index", "sans_index"])
def test_performance_50000_evenements_10000_messages(tmp_path, indexes, capsys):
    b = _grosse_base(tmp_path, indexes)
    lire_registre(tmp_path, MAINTENANT)  # chauffe le cache
    duree, (d, source) = meilleur(lambda: lire_registre(tmp_path, MAINTENANT), 5)
    ms = duree * 1000
    b.conn.close()
    with capsys.disabled():
        print(f"\n[perf {'avec' if indexes else 'sans'} index] lire_registre = {ms:.0f} ms")
    assert source["ok"], source
    assert len(d["fil"]) == 200 and len(d["agents"]) == 32
    if indexes:  # sans index : non exigé. Marge large : les machines d'intégration continue sont lentes.
        assert ms < 1000


# --- etat_evenement_id (discriminant des id d'alarme) -------------------------

def test_etat_evenement_id_est_l_evenement_qui_fixe_l_etat(base):
    base.evt(W, "SessionStart", "SessionStart", 30)
    assert agent(base)["etat_evenement_id"] is None  # aucun événement d'état
    stop = base.evt(W, "Stop", "Stop", 20)
    assert agent(base)["etat_evenement_id"] == stop
    demande = base.evt(W, "PermissionRequest", "PermissionRequest-Bash", 6, demande_id="d-1")
    base.evt(W, "Notification", "Notification-permission_prompt", 5)
    assert agent(base)["etat_evenement_id"] == demande  # le premier ouvrant, comme etat_depuis
    suite = base.evt(W, "PostToolUse", "PostToolUse-Bash", 4)
    assert agent(base)["etat_evenement_id"] == suite


# --- etat_livraison, preuve, dettes, file, occupation, flux, facteur ------------

def test_fil_porte_la_derniere_transition_et_son_horodatage_de_preuve(base):
    m = base.msg("assistant", "coord-x", "consigne", 5, id=1)
    base.conn.execute("INSERT INTO transitions (horodatage, message_id, etat, auteur, preuve)"
                      " VALUES (?,?,'livre','cime','{\"voie\":\"tmux\"}')", (iso(4), m))
    base.conn.commit()
    entree = lire(base)["fil"][0]
    assert (entree["etat_livraison"], entree["preuve"]) == ("livre", {"voie": "tmux"})


def test_en_attente_est_l_obligation_ouverte_pas_la_question_sans_reponse(base):
    base.msg("coord-x", "assistant", "question", 9, id=1, obligation=False)   # aucune obligation
    base.msg("assistant", "coord-x", "consigne", 8, id=2)                       # consigne sans dette
    base.msg("assistant", "coord-x", "travail_pret", 7, id=3)                   # dette « revue »
    d = lire(base)
    assert [m["id"] for m in d["fil"] if m["en_attente"]] == ["msg-3"]
    assert d["questions_en_attente"] == []


def test_attentes_utilisateur_sont_les_obligations_dont_utilisateur_est_debiteur(base):
    base.msg("assistant", "utilisateur", "decision_utilisateur", 9, id=1, objet="fusion:signaux:abc123")
    base.msg("assistant", "utilisateur", "donnee_utilisateur", 8, id=2, obligation=False)   # pas d'obligation
    base.msg("assistant", "utilisateur", "decision_utilisateur", 7, id=3)
    base.satisfaire(3)
    att = lire(base)["attentes_utilisateur"]
    assert [(a["id"], a["message_id"], a["objet"]) for a in att] == [("msg-1", 1, "fusion:signaux:abc123")]


def test_dettes_file_et_occupation_par_agent(base):
    base.msg("assistant", "coord-x", "travail_pret", 9, id=1, objet="o")
    base.msg("assistant", "coord-x", "consigne", 8, id=2, objet="en-file")
    base.conn.execute("INSERT INTO transitions (horodatage, message_id, etat, auteur, preuve)"
                      " VALUES (?,1,'livre','cime','{}')", (iso(8),))
    base.conn.execute("INSERT INTO occupation VALUES ('coord-x', 'tour', ?)", (iso(1),))
    base.conn.commit()
    d = lire(base)
    assert d["dettes"]["coord-x"] == [{"id": 1, "attendu": "revue", "de": "assistant",
                                       "objet": "o", "depuis": iso(9)}]
    assert [(m["id"], m["objet"]) for m in d["files"]["coord-x"]] == [(2, "en-file")]
    assert d["occupation"] == {"coord-x": "tour"}


def test_flux_aretes_ordres_du_registre(base):
    base.msg("assistant", "coord-x", "consigne", 2, id=1)
    base.conn.execute("INSERT INTO ordres (horodatage, auteur, verbe, cible, parametres, etat)"
                      " VALUES ('t', 'assistant', 'lancer', 'coord-x', '{}', 'execute')")
    base.conn.commit()
    d = lire(base)
    assert [f["id"] for f in d["flux"]] == [1] and d["flux"][0]["etat"] == "inscrit"
    assert d["aretes"] == [{"de": "assistant", "a": "coord-x", "en_file": 1, "livre": 0,
                            "ouvertes": 0, "total_15min": 1}]
    assert d["ordres"] == [{"id": 1, "auteur": "assistant", "verbe": "lancer",
                            "cible": "coord-x", "etat": "execute"}]


@pytest.mark.parametrize("battement, age, arrete", [
    (60, 60, True), (10, 10, False), (None, None, True)])
def test_facteur_battement_age_et_arret(base, battement, age, arrete):
    if battement is not None:
        base.conn.execute("INSERT INTO facteur VALUES (1, ?, '3')", (iso(battement / 60),))
        base.conn.commit()
    f = lire(base)["facteur"]
    assert f["age_s"] == age and f["arrete"] is arrete


def test_registre_1_x_sans_tables_2_0_se_lit_encore(tmp_path):
    chemin = tmp_path / ".orga" / "etat" / "registre.sqlite"
    chemin.parent.mkdir(parents=True)
    conn = sqlite3.connect(chemin)
    conn.executescript("""
        CREATE TABLE messages (id INTEGER PRIMARY KEY, horodatage TEXT, de TEXT, a TEXT, nature TEXT,
          resume TEXT, fichier TEXT, en_reponse_a INTEGER, equipe TEXT);
        CREATE TABLE evenements (id INTEGER PRIMARY KEY, horodatage TEXT, agent TEXT, session_id TEXT,
          evenement TEXT, details TEXT);
        INSERT INTO messages VALUES (1, '2026-10-07T13:00:00.000Z', 'a', 'b', 'question', 'x', NULL, NULL, NULL);""")
    conn.commit()
    conn.close()
    d, source = lire_registre(tmp_path, MAINTENANT)
    assert source["ok"] is True
    assert d["questions_en_attente"] == [] and d["flux"] == [] and d["facteur"] is None
    assert d["fil"][0]["etat_livraison"] is None and d["fil"][0]["en_attente"] is False


# --- `signaux`, les données des alarmes dérivées des obligations -----------------

def test_signaux_obligations_ouvertes_et_agent_de_la_demande(base):
    base.evt(W, "PermissionRequest", "PermissionRequest-Bash", 6, demande_id="d-6")
    base.msg("cime", "assistant", "signalement", 6, id=1, objet="autorisation:d-6")
    base.msg("cime", "coord-x", "signalement", 5, id=2, objet="session-disparue:worker-x-t1")
    base.msg("assistant", "coord-x", "travail_pret", 4, id=3)          # pas un signalement : écarté
    base.satisfaire(2)
    o = lire(base)["signaux"]["obligations"]
    assert [(x["message_id"], x["objet"], x["agent_demande"]) for x in o] == [(1, "autorisation:d-6", W)]


def test_signaux_echec_de_livraison_jusqu_a_prise_d_acte_du_superieur(base):
    m = base.msg("assistant", "worker-x-t1", "consigne", 20, id=1)
    base.conn.execute("INSERT INTO transitions (horodatage, message_id, etat, auteur, preuve)"
                      " VALUES (?,?,'echec','cime','{}')", (iso(10), m))
    base.conn.commit()
    [e] = lire(base)["signaux"]["echecs"]
    assert (e["id"], e["a"], e["depuis"], e["signale_a"]) == (1, "worker-x-t1", iso(10), None)
    base.msg("cime", "coord-x", "signalement", 9, id=2, objet="livraison:1")
    assert lire(base)["signaux"]["echecs"][0]["signale_a"] == "coord-x"
    base.satisfaire(2)                                                   # le supérieur a pris acte
    assert lire(base)["signaux"]["echecs"] == []
    base.conn.execute("INSERT INTO transitions (horodatage, message_id, etat, auteur, preuve)"
                      " VALUES (?,1,'inscrit','cime','{}')", (iso(1),))   # retentée : plus en échec
    base.conn.commit()
    assert lire(base)["signaux"]["echecs"] == []


def test_signaux_courrier_tmux_de_l_assistant_et_idle_prompt(base):
    base.msg("coord-x", "assistant", "compte_rendu", 6, id=1)
    base.conn.execute("INSERT INTO courriers (a, voie, cree, expire, etat) VALUES ('assistant','tmux',?,?,'ouvert')",
                      (iso(5), iso(4)))
    base.conn.execute("INSERT INTO transitions (horodatage, message_id, etat, courrier_id, auteur, preuve)"
                      " VALUES (?,1,'livre',1,'cime','{\"capture_avant\":\"vide\"}')", (iso(5),))
    base.evt("assistant", "Notification", "Notification-permission_prompt", 3, notification_type="idle_prompt")
    d = lire(base)["signaux"]
    assert d["courrier_assistant"] == {"id": 1, "cree": iso(5)}
    assert d["idle_prompt_assistant"] == iso(3)
    base.conn.execute("UPDATE transitions SET preuve = '{\"capture_avant\":\"texte\"}' WHERE etat = 'livre'")
    base.conn.commit()
    assert lire(base)["signaux"]["courrier_assistant"] is None            # invite non vide à la frappe


def test_signaux_attente_du_facteur_ignore_son_propre_signalement(base):
    base.msg("assistant", "coord-x", "consigne", 2, id=1)
    base.msg("cime", "assistant", "signalement", 1, id=2, objet="facteur-arrete")
    base.conn.execute("INSERT INTO ordres (horodatage, auteur, verbe, cible, parametres, etat)"
                      " VALUES ('t','assistant','lancer','c','{}','en_file')")
    base.conn.commit()
    assert lire(base)["signaux"]["attente"] == {"messages": 1, "ordres": 1}


def _clore(base, message_id, cause="session-disparue"):
    base.conn.execute("INSERT INTO transitions (horodatage, message_id, etat, auteur, preuve)"
                      " VALUES (?,?,'clos','cime',?)", (iso(1), message_id, json.dumps({"cause_disparue": cause})))
    base.conn.commit()


def test_signalement_a_utilisateur_sans_obligation_reste_visible_tant_qu_il_n_est_pas_clos(base):
    base.msg("cime", "utilisateur", "signalement", 9, id=1, objet="session-disparue:worker-x-t1")
    [o] = lire(base)["signaux"]["obligations"]
    assert (o["message_id"], o["debiteur"], o["attendu"], o["echeance"], o["a"]) == (
        1, "utilisateur", "accuse", None, "utilisateur")
    _clore(base, 1)
    assert lire(base)["signaux"]["obligations"] == []


def test_livraison_echouee_signalee_a_utilisateur_disparait_une_fois_close(base):
    base.msg("assistant", "worker-x-t1", "consigne", 20, id=1)
    base.conn.execute("INSERT INTO transitions (horodatage, message_id, etat, auteur, preuve)"
                      " VALUES (?,1,'echec','cime','{}')", (iso(10),))
    base.conn.commit()
    base.msg("cime", "utilisateur", "signalement", 9, id=2, objet="livraison:1")
    assert lire(base)["signaux"]["echecs"][0]["signale_a"] == "utilisateur"
    _clore(base, 2)
    assert lire(base)["signaux"]["echecs"] == []


# --- fil[].non_lu ----------------------------------------------------

def _livrer(base, message_id):
    base.conn.execute("INSERT INTO transitions (horodatage, message_id, etat, auteur, preuve)"
                      " VALUES (?,?,'livre','cime','{}')", (iso(1), message_id))
    base.conn.commit()


def test_non_lu_vrai_seulement_pour_un_message_livre_a_utilisateur_sans_obligation_hors_autorisation(base):
    base.msg("assistant", "utilisateur", "compte_rendu", 9, id=1, obligation=False)             # livré, sans dette
    base.msg("assistant", "utilisateur", "compte_rendu", 8, id=2, obligation=False)             # pas livré
    base.msg("assistant", "utilisateur", "decision_utilisateur", 7, id=3)                            # dette ouverte
    base.msg("assistant", "utilisateur", "compte_rendu", 6, id=4, obligation=False,
             objet="autorisation:perm-1")                                                  # voie perm-…
    base.msg("assistant", "coord-x", "compte_rendu", 5, id=5, obligation=False)            # pas pour l'utilisateur
    for m in (1, 3, 4, 5):
        _livrer(base, m)
    non_lu = {m["id"]: m["non_lu"] for m in lire(base)["fil"]}
    assert non_lu == {"msg-1": True, "msg-2": False, "msg-3": False, "msg-4": False, "msg-5": False}


def test_non_lu_faux_apres_clos_et_pour_les_entrees_hook(base):
    base.msg("assistant", "utilisateur", "compte_rendu", 9, id=1, obligation=False)
    base.conn.execute("INSERT INTO transitions (horodatage, message_id, etat, auteur, preuve)"
                      " VALUES (?,1,'clos','hote','{\"lu_par\":\"utilisateur\",\"journal_id\":3}')", (iso(1),))
    base.evt("assistant", "Stop", "Stop", 2, last_assistant_message="fini")
    base.conn.commit()
    assert all(m["non_lu"] is False for m in lire(base)["fil"])
