"""Scénarios de l'instantané, rejoués à partir de fixtures (hooks, captures d'écran tmux, transcript).

Les collecteurs tmux et git sont remplacés par des données de test (monkeypatch) ; le manifeste,
les équipes et le registre sont construits dans `tmp_path` (structure fabriquée à la main).
"""

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from chrono import meilleur

from cime.observation import git, instantane, tmux, transcripts
from cime.observation.instantane import _titre_tache
from test_registre import MAINTENANT, Base, hook, iso

CAPTURES = Path(__file__).parent / "fixtures" / "captures"
TRANSCRIPT = Path(__file__).parent / "fixtures" / "transcript_assistant.jsonl"
W = "worker-observation-t2-registre"
_VRAI_LIRE_GIT = git.lire_git

MANIFESTE = """nom = "essai"
prefixe = "cc"
branche_reference = "main"
branche_equipe = "equipe/{equipe}"
worktree_equipe = "../{depot}-{equipe}"
equipes_speciales = ["assistant", "integration"]
modele_assistant = "claude-opus-5-5"
modele_coordinateur = "claude-opus-5-5"
"""


def _orga(racine: Path, equipes=("observation", "page")):
    orga = racine / ".orga"
    (orga / "teams").mkdir(parents=True, exist_ok=True)
    (orga / "projet.toml").write_text(MANIFESTE, encoding="utf-8")
    (orga / "etapes.md").write_text("- [x] Cadrage (atteinte le 2026-10-07)\n- [ ] Page\n", encoding="utf-8")
    for e in equipes:
        d = orga / "teams" / e
        for sous in ("todo", "in-progress", "done"):
            (d / "tasks" / sous).mkdir(parents=True, exist_ok=True)
        (d / "mandate.md").write_text(
            f"# Mandat {e}\n\n## Bloc 2\n\nMission de cette équipe dans le produit : **observer {e}**.\n\n"
            f"Scope : `src/cime/{e}/`, `tests/{e}/`\n", encoding="utf-8")
    if "observation" in equipes:
        (orga / "teams" / "observation" / "tasks" / "in-progress" / "t2-registre.md").write_text(
        "# Tâche : lire le registre\n\nCorps.\n", encoding="utf-8")


def _session(activite=iso(3)):
    return {"identite": None, "creee": iso(60), "activite": activite}


class Faux:
    """tmux et git remplacés ; état modifiable par chaque test."""

    def __init__(self, monkeypatch):
        self.sessions = {f"cc-{a}": _session() for a in ("assistant", "coord-observation", "coord-page", W)}
        for nom, s in self.sessions.items():
            s["identite"] = nom[3:]
        self.captures: dict = {}
        self.tmux_ok = True
        self.git = None
        monkeypatch.setattr(tmux, "lister_sessions", self.lister_sessions)
        monkeypatch.setattr(tmux, "lire_invites", self.lire_invites)
        monkeypatch.setattr(git, "lire_git", self.lire_git)
        monkeypatch.setattr(transcripts, "trouver_transcript", lambda *a, **k: None)

    def lister_sessions(self, prefixe):
        if not self.tmux_ok:
            return None, {"nom": "tmux", "ok": False, "erreur": "aucun serveur tmux"}
        return {k: dict(v) for k, v in self.sessions.items()}, {"nom": "tmux", "ok": True}

    def lire_invites(self, sessions, prefixe):
        sortie = {}
        for s in sessions:
            capture = self.captures.get(s)
            if s == "cc-assistant" or capture is None:
                sortie[s] = {"brouillon": None, "ecran_demarrage": None}
            else:
                sortie[s] = {"brouillon": tmux.extraire_brouillon(capture),
                             "ecran_demarrage": tmux.ecran_demarrage(capture)}
        return sortie, {"nom": "tmux-invites", "ok": True}

    def lire_git(self, racine, reference, equipes):
        if self.git is not None:
            return self.git, {"nom": "git", "ok": True}
        return ({"equipes": {e["nom"]: {"branche": e["branche"], "commit": "abc1234", "fichiers_touches": [],
                                        "hors_perimetre": [], "retard_sur_base": 0} for e in equipes},
                 "recouvrements": []}, {"nom": "git", "ok": True})


@pytest.fixture
def base(tmp_path):
    _orga(tmp_path)
    b = Base(tmp_path)
    yield b
    b.conn.close()


@pytest.fixture
def faux(monkeypatch):
    return Faux(monkeypatch)


def snap(racine, minutes_plus_tard=0.0):
    return instantane(racine, MAINTENANT + timedelta(minutes=minutes_plus_tard))


def types(d, t=None):
    return [a for a in d["alarmes"] if t is None or a["type"] == t]


def agent(d, aid):
    return next(a for a in d["agents"] if a["id"] == aid)


# --- 1. incident 1 : six minutes sur une demande d'autorisation ----------------------------

def test_incident_1_autorisation_en_attente_6_min(base, faux):
    base.evt(W, "UserPromptSubmit", "UserPromptSubmit", 20)
    base.evt(W, "PermissionRequest", "PermissionRequest-Bash", 6, demande_id="d-6")
    base.msg("cime", "assistant", "signalement", 6, objet="autorisation:d-6", obligation=True)  # E4
    d = snap(base.racine)
    a = agent(d, W)
    assert (a["etat"], a["etat_source"], a["etat_depuis"]) == ("attend_autorisation", "hook:PermissionRequest", iso(6))
    al = types(d, "autorisation_en_attente")
    assert len(al) == 1
    assert al[0]["id"] == f"autorisation_en_attente:{W}:perm-d-6"
    assert al[0]["gravite"] == "grave" and al[0]["equipes"] == ["observation"]
    assert "depuis 6 min" in al[0]["mesure"] and al[0]["quoi_faire"]
    assert al[0]["destinataire"] == "utilisateur"
    att = [x for x in d["attentes_utilisateur"] if x["id"] == "perm-d-6"]
    assert att == [{"id": "perm-d-6", "message_id": None, "objet": None, "nature": "autorisation",
                    "titre": "Bash : ls /home/exemple/projet",
                    "bloque": f"{W} : lire le registre", "depuis": iso(6), "agent": W, "equipe": "observation",
                    "actions": ["autoriser", "refuser"]}]
    assert next(e for e in d["equipes"] if e["nom"] == "observation")["statut"] == "bloquee"


def test_incident_1_a_1_min_attente_sans_alarme(base, faux):
    base.evt(W, "PermissionRequest", "PermissionRequest-Bash", 1, demande_id="d-1")
    d = snap(base.racine)
    assert [x["id"] for x in d["attentes_utilisateur"]] == ["perm-d-1"]
    assert types(d, "autorisation_en_attente") == []


def test_id_d_alarme_stable_d_un_instantane_a_l_autre(base, faux):
    base.evt(W, "PermissionRequest", "PermissionRequest-Bash", 6, demande_id="d-6")
    assert [a["id"] for a in snap(base.racine)["alarmes"]] == [a["id"] for a in snap(base.racine, 2)["alarmes"]]


def test_notification_seule_sans_demande_id_n_inscrit_aucun_signalement_donc_aucune_alarme(base, faux):
    base.evt(W, "Notification", "Notification-permission_prompt", 5)
    d = snap(base.racine)
    assert agent(d, W)["etat"] == "attend_autorisation"
    assert types(d, "autorisation_en_attente") == []
    assert d["attentes_utilisateur"] == []  # rien à autoriser depuis la page sans demande_id


# --- 2. (retiré en 2.0) arrêt après annonce : fondé sur la prose, remplacé par la dette au repos ---

def test_pas_d_alarme_arret_apres_annonce_en_2_0(base, faux):
    base.evt("coord-observation", "Stop", "Stop", 40, last_assistant_message="Je lance maintenant la tâche T2.")
    d = snap(base.racine)
    assert agent(d, "coord-observation")["etat"] == "au_repos"
    assert "arret_apres_annonce" not in {a["type"] for a in d["alarmes"]}


# --- 3. incident 3 : texte en attente dans l'invite ----------------------------------------

@pytest.mark.parametrize("f", sorted(p.name for p in CAPTURES.glob("brouillon-*.ansi")))
def test_incident_3_vrai_brouillon(base, faux, f):
    faux.captures["cc-coord-page"] = (CAPTURES / f).read_text(encoding="utf-8")
    faux.sessions["cc-coord-page"]["activite"] = "2026-10-07T13:51:00.000Z"
    d = snap(base.racine)
    b = agent(d, "coord-page")["brouillon"]
    assert b and b["texte"] and b["depuis"] == "2026-10-07T13:51:00.000Z"
    assert "dernière activité de la fenêtre" in types(d, "brouillon")[0]["mesure"]
    assert "pas l'heure d'apparition" in types(d, "brouillon")[0]["mesure"]
    epoch = int(datetime(2026, 10, 7, 13, 51, tzinfo=timezone.utc).timestamp())
    al = types(d, "brouillon")
    assert [a["id"] for a in al] == [f"brouillon:coord-page:{epoch}"]
    assert al[0]["gravite"] == "a_voir" and al[0]["depuis"] == b["depuis"]


@pytest.mark.parametrize("f", sorted(p.name for p in CAPTURES.glob("suggestion-*.ansi"))
                         + sorted(p.name for p in CAPTURES.glob("cc-coord-*.ansi")))
def test_incident_3_suggestion_attenuee_ou_invite_vide_pas_de_brouillon(base, faux, f):
    faux.captures["cc-coord-page"] = (CAPTURES / f).read_text(encoding="utf-8")
    d = snap(base.racine)
    assert agent(d, "coord-page")["brouillon"] is None
    assert types(d, "brouillon") == []


def _brouillon_une_ligne(faux, activite_il_y_a_s):
    faux.captures["cc-coord-page"] = (CAPTURES / "brouillon-une-ligne.ansi").read_text(encoding="utf-8")
    faux.sessions["cc-coord-page"]["activite"] = tmux._iso(
        str(int((MAINTENANT - timedelta(seconds=activite_il_y_a_s)).timestamp())))


def test_brouillon_apres_5_s_d_activite_n_existe_pas(base, faux):
    _brouillon_une_ligne(faux, 5)
    d = snap(base.racine)
    assert agent(d, "coord-page")["brouillon"] is None and types(d, "brouillon") == []


def test_brouillon_apres_90_s_d_inactivite_existe(base, faux):
    _brouillon_une_ligne(faux, 90)
    d = snap(base.racine)
    assert agent(d, "coord-page")["brouillon"] and len(types(d, "brouillon")) == 1


def test_l_assistant_n_est_jamais_capture(base, faux):
    faux.captures["cc-assistant"] = (CAPTURES / "brouillon-une-ligne.ansi").read_text(encoding="utf-8")
    d = snap(base.racine)
    assert agent(d, "assistant")["brouillon"] is None and types(d, "brouillon") == []


# --- 4. recouvrement et hors périmètre ------------------------------------------------------

def test_recouvrement_grave_hors_perimetre_a_voir(base, faux):
    commun = "src/cime/observation/tmux.py"
    faux.git = {
        "equipes": {
            "observation": {"branche": "equipe/observation", "commit": "aaa", "fichiers_touches": [commun],
                            "hors_perimetre": [], "retard_sur_base": 0},
            "page": {"branche": "equipe/page", "commit": "bbb", "fichiers_touches": [commun, "src/cime/page/a.js"],
                     "hors_perimetre": [commun], "retard_sur_base": 3},
        },
        "recouvrements": [{"fichier": commun, "equipes": ["observation", "page"]}],
    }
    d = snap(base.racine)
    par_id = {a["id"]: a for a in d["alarmes"]}
    assert par_id[f"recouvrement:observation+page:{commun}"]["gravite"] == "grave"
    assert par_id[f"recouvrement:observation+page:{commun}"]["equipes"] == ["observation", "page"]
    assert par_id[f"hors_perimetre:page:{commun}"]["gravite"] == "a_voir"
    assert par_id["retard_sur_base:page:main"]["gravite"] == "info"
    page = next(e for e in d["equipes"] if e["nom"] == "page")
    assert (page["commit"], page["retard_sur_base"], page["hors_perimetre"]) == ("bbb", 3, [commun])


def test_recouvrement_sur_un_vrai_depot_git(tmp_path, faux, monkeypatch):
    monkeypatch.setattr(git, "lire_git", _VRAI_LIRE_GIT)
    _orga(tmp_path)
    _depot(tmp_path, {"observation": ["src/commun.py", "src/cime/observation/a.py"], "page": ["src/commun.py"]})
    d = instantane(tmp_path, MAINTENANT)
    ids = {a["id"] for a in d["alarmes"]}
    assert "recouvrement:observation+page:src/commun.py" in ids
    assert "hors_perimetre:page:src/commun.py" in ids and "hors_perimetre:observation:src/commun.py" in ids


def _git(racine, *args):
    subprocess.run(["git", "-C", str(racine), *args], check=True, capture_output=True)


def _depot(racine: Path, branches: dict):
    _git(racine, "init", "-q", "-b", "main")
    _git(racine, "config", "user.email", "t@t")
    _git(racine, "config", "user.name", "t")
    (racine / "LISEZMOI").write_text("x")
    _git(racine, "add", "LISEZMOI")
    _git(racine, "commit", "-q", "-m", "init")
    for equipe, fichiers in branches.items():
        _git(racine, "checkout", "-q", "-b", f"equipe/{equipe}", "main")
        for f in fichiers:
            (racine / f).parent.mkdir(parents=True, exist_ok=True)
            (racine / f).write_text(equipe)
            _git(racine, "add", f)
        _git(racine, "commit", "-q", "-m", equipe)
    _git(racine, "checkout", "-q", "main")


# --- 5. tmux en échec -------------------------------------------------------------------------

def test_tmux_en_echec_vivant_none_pas_d_arret_pas_de_session_disparue(base, faux):
    base.evt(W, "Stop", "Stop", 3)
    faux.tmux_ok = False
    d = snap(base.racine)
    tm = next(s for s in d["sources"] if s["nom"] == "tmux")
    assert tm == {"nom": "tmux", "ok": False, "erreur": "aucun serveur tmux"}
    for a in d["agents"]:
        assert a["vivant"] is None and a["etat"] != "arrete" and a["brouillon"] is None
    assert agent(d, W)["etat"] == "au_repos"
    assert types(d, "session_disparue") == []


def test_session_disparue_sans_session_end(base, faux):
    base.evt(W, "Stop", "Stop", 3)
    del faux.sessions[f"cc-{W}"]
    d = snap(base.racine)
    a = agent(d, W)
    assert (a["vivant"], a["etat"], a["etat_source"], a["etat_depuis"]) == (False, "arrete", "tmux:session_absente", iso(3))
    assert types(d, "session_disparue") == []   # l'alarme se lit dans le signalement, pas dans tmux
    base.msg("cime", "coord-observation", "signalement", 2, objet=f"session-disparue:{W}", equipe="observation")
    [al] = types(d := snap(base.racine), "session_disparue")
    assert al["id"] == f"session_disparue:{W}:cc-{W}" and al["gravite"] == "grave"
    assert al["destinataire"] == "coord-observation"



def test_modele_avant_tout_hook_pris_dans_la_commande_de_lancement(base, faux):
    # Écran « trust » : aucun hook, pas de transcript ; le manifeste dit Opus, la session tourne en Haiku.
    faux.sessions[f"cc-{W}"] = {**_session(), "identite": W, "modele_lancement": "claude-haiku-4-5-20251001"}
    assert agent(snap(base.racine), W)["modele"] == "claude-haiku-4-5-20251001"
    base.evt(W, "SessionStart", "SessionStart", 1, model="claude-sonnet-5-5", transcript_path=str(base.racine / "absent.jsonl"))
    assert agent(snap(base.racine), W)["modele"] == "claude-sonnet-5-5"  # le hook prime


def test_modele_du_manifeste_sans_session_ni_hook(base, faux):
    assert agent(snap(base.racine), "coord-page")["modele"] == "claude-opus-5-5"

def test_assistant_hors_tmux_sans_evenement_inconnu(base, faux):
    # L'Assistant peut vivre hors tmux ; session absente ne prouve pas qu'il est arrêté.
    del faux.sessions["cc-assistant"]
    d = snap(base.racine)
    a = agent(d, "assistant")
    assert (a["vivant"], a["etat"]) == (False, "inconnu")
    assert types(d, "session_disparue") == []


def test_assistant_hors_tmux_ses_hooks_disent_l_etat(base, faux):
    base.evt("assistant", "Stop", "Stop", 3)
    del faux.sessions["cc-assistant"]
    d = snap(base.racine)
    a = agent(d, "assistant")
    assert (a["vivant"], a["etat"], a["etat_depuis"]) == (False, "au_repos", iso(3))
    assert types(d, "session_disparue") == []


def test_assistant_hors_tmux_session_end_arrete(base, faux):
    base.evt("assistant", "SessionEnd", "SessionEnd", 3)
    del faux.sessions["cc-assistant"]
    a = agent(snap(base.racine), "assistant")
    assert (a["etat"], a["etat_source"]) == ("arrete", "hook:SessionEnd")


def test_session_terminee_proprement_ou_equipe_cloturee_pas_d_alarme(base, faux):
    base.evt(W, "Stop", "Stop", 3)
    base.evt(W, "SessionEnd", "SessionEnd", 2)
    base.evt("coord-page", "Stop", "Stop", 3)
    (base.racine / ".orga" / "teams" / "page" / "CLOTUREE").write_text("")
    del faux.sessions[f"cc-{W}"]
    del faux.sessions["cc-coord-page"]
    d = snap(base.racine)
    assert types(d, "session_disparue") == []
    a = agent(d, W)
    assert (a["etat"], a["etat_source"], a["etat_depuis"]) == ("arrete", "hook:SessionEnd", iso(2))
    assert next(e for e in d["equipes"] if e["nom"] == "page")["statut"] == "terminee"


# --- 6. registre absent -----------------------------------------------------------------------

def test_registre_absent(tmp_path, faux):
    _orga(tmp_path)
    d = instantane(tmp_path, MAINTENANT)
    reg = next(s for s in d["sources"] if s["nom"] == "registre")
    assert reg["ok"] is False and "registre absent" in reg["erreur"]
    assert d["fil"] is None
    assert d["attentes_utilisateur"] == []
    for a in d["agents"]:
        assert a["etat"] == "inconnu" and a["etat_source"] is None and a["etat_depuis"] is None
    assert all(e["statut"] is None for e in d["equipes"])
    assert not next(s for s in d["sources"] if s["nom"] == "transcripts")["ok"]


def test_registre_vide_fil_vide(base, faux):
    assert snap(base.racine)["fil"] == []


def test_manifeste_absent_instantane_quand_meme(tmp_path, faux):
    d = instantane(tmp_path, MAINTENANT)
    assert d["projet"] is None and d["equipes"] is None
    noms = {s["nom"]: s["ok"] for s in d["sources"]}
    assert noms == {"structure": False, "registre": False, "transcripts": False, "tmux": False,
                    "git": False, "tarifs": True}
    assert json.dumps(d)


# --- forme de l'instantané --------------------------------------------------------------------

CLES = {
    "racine": {"version", "genere_a", "duree_collecte_ms", "projet", "sources", "agents", "equipes",
               "fil", "attentes_utilisateur", "flux", "aretes", "ordres", "facteur", "alarmes", "fusions_auto",
               "consommation", "sessions_hors_organigramme", "decisions_recentes"},
    "projet": {"nom", "racine", "prefixe", "branche_reference", "etapes"},
    "agent": {"id", "role", "equipe", "parent", "session_tmux", "vivant", "etat", "etat_depuis",
              "etat_source", "tache", "derniere_phrase", "modele", "contexte", "cout_usd_estime", "brouillon", "consommation",
              "dettes", "file", "occupe_par"},
    "equipe": {"nom", "mission", "speciale", "statut", "cloturee_le", "branche", "commit", "worktree", "avancement",
               "fichiers_touches", "perimetre_declare", "hors_perimetre", "retard_sur_base",
               "en_avance_sur_base", "depend_de"},
    "fil": {"id", "horodatage", "de", "a", "nature", "resume", "fichier", "en_attente", "etat_livraison",
            "non_lu", "preuve", "source"},
    "attente": {"id", "message_id", "objet", "nature", "titre", "bloque", "depuis", "agent", "equipe", "actions"},
    "alarme": {"id", "type", "gravite", "agents", "equipes", "depuis", "mesure", "quoi_faire", "destinataire"},
}
ETATS = {"travaille", "au_repos", "attend_autorisation", "attend_reponse", "arrete", "inconnu"}
TYPES = {"autorisation_en_attente", "question_sans_reponse", "recouvrement",
         "brouillon", "contexte_plein", "hors_perimetre", "retard_sur_base", "session_disparue", "action_refusee",
         "bloque_au_demarrage", "fige", "session_orpheline", "gros_poste", "contexte_au_repos",
         "assistant_sourd", "livraison_echouee", "livraison_bloquee", "facteur_arrete", "fin_sans_suite"}


def test_json_et_toutes_les_cles(base, faux):
    base.evt("assistant", "UserPromptSubmit", "UserPromptSubmit", 30, prompt="Où ça bloque ?",
             transcript_path=str(TRANSCRIPT))
    base.evt("assistant", "Stop", "Stop", 29, last_assistant_message="Rien ne bloque.",
             transcript_path=str(TRANSCRIPT))
    base.evt(W, "PermissionRequest", "PermissionRequest-Write", 6, demande_id="d-9")
    q = base.msg("coord-page", "assistant", "question", 40, resume="Quel port ?")
    base.msg("assistant", "coord-page", "consigne", 50, resume="Construire la page")
    base.msg("assistant", "utilisateur", "decision_utilisateur", 20, resume="Choisir le port", equipe="page")
    base.evt("coord-page", "Stop", "Stop", 30, last_assistant_message="J'attends la réponse.")
    base.conn.execute("INSERT INTO evenements (horodatage, agent, session_id, evenement, details) VALUES (?,?,?,?,?)",
                      (iso(5), "coord-page", "s", "PreToolUse",
                       json.dumps({"tool_name": "Bash", "tool_input": {"command": "git push"}, "motif": "push interdit"})))
    base.conn.commit()
    faux.captures["cc-coord-observation"] = (CAPTURES / "brouillon-une-ligne.ansi").read_text(encoding="utf-8")
    d = snap(base.racine)
    texte = json.dumps(d, ensure_ascii=False)
    assert json.loads(texte) == d
    assert set(d) == CLES["racine"] and set(d["projet"]) == CLES["projet"]
    assert d["projet"]["etapes"] == [{"nom": "Cadrage", "atteinte": True, "date": "2026-10-07"},
                                     {"nom": "Page", "atteinte": False, "date": None}]
    assert [s["nom"] for s in d["sources"]] == ["structure", "registre", "transcripts", "tmux", "git", "tarifs"]
    for a in d["agents"]:
        assert set(a) == CLES["agent"] and a["etat"] in ETATS
        assert a["etat_source"] or (a["id"] == "utilisateur" and a["etat_source"] is None)
    for e in d["equipes"]:
        assert set(e) == CLES["equipe"]
    for m in d["fil"]:
        assert set(m) == CLES["fil"] and isinstance(m["id"], str)
    for x in d["attentes_utilisateur"]:
        assert set(x) == CLES["attente"]
    for al in d["alarmes"]:
        assert set(al) == CLES["alarme"] and al["type"] in TYPES
        assert al["id"].startswith(al["type"] + ":") and al["mesure"] and al["quoi_faire"]
    # contenu de quelques champs
    utilisateur = agent(d, "utilisateur")
    assert utilisateur["etat"] == "inconnu" and all(utilisateur[k] is None for k in (
        "vivant", "modele", "contexte", "cout_usd_estime", "tache", "derniere_phrase", "brouillon", "consommation"))
    ass = agent(d, "assistant")
    assert ass["contexte"]["source"] == "transcript" and ass["cout_usd_estime"] is not None
    assert agent(d, "coord-page")["tache"] == "Construire la page"
    assert agent(d, "coord-page")["etat"] == "attend_reponse"
    assert [m["de"] for m in d["fil"] if m["source"] == "hook"] == ["assistant", "utilisateur"]
    att = {x["id"]: x for x in d["attentes_utilisateur"]}
    assert att["perm-d-9"]["agent"] == W
    decision = next(x for x in d["attentes_utilisateur"] if x["nature"] == "decision")
    assert decision["actions"] == ["trancher"] and decision["agent"] == "assistant" and decision["bloque"] == "page"
    ids = {a["id"] for a in d["alarmes"]}
    assert f"question_sans_reponse:coord-page:msg-{q}" in ids
    assert any(i.startswith("action_refusee:coord-page:") for i in ids)
    assert any(i.startswith("brouillon:coord-observation:") for i in ids)


def test_tarifs_en_echec_cout_null_partout(base, faux, tmp_path):
    lignes = TRANSCRIPT.read_text(encoding="utf-8").replace("claude-opus-5-5", "claude-inconnu-9")
    autre = tmp_path / "inconnu.jsonl"
    autre.write_text(lignes, encoding="utf-8")
    base.evt("assistant", "Stop", "Stop", 5, transcript_path=str(TRANSCRIPT))
    base.evt("coord-page", "Stop", "Stop", 5, transcript_path=str(autre))
    d = snap(base.racine)
    tarifs = next(s for s in d["sources"] if s["nom"] == "tarifs")
    assert tarifs["ok"] is False and "claude-inconnu-9" in tarifs["erreur"]
    assert all(a["cout_usd_estime"] is None for a in d["agents"])


# --- performance --------------------------------------------------------------------------------

def test_performance_10_equipes_50000_evenements(tmp_path, faux, capsys, monkeypatch):
    equipes = [f"equipe{i}" for i in range(10)]
    _orga(tmp_path, equipes)
    _depot(tmp_path, {e: [f"src/cime/{e}/a.py", "src/commun.py" if i < 2 else f"src/cime/{e}/b.py"]
                      for i, e in enumerate(equipes)})
    faux.sessions = {f"cc-coord-{e}": {**_session(), "identite": f"coord-{e}"} for e in equipes}
    b = Base(tmp_path)
    agents = [f"coord-{e}" for e in equipes] + [f"worker-{e}-t{j}" for e in equipes for j in range(2)]
    noms = ["UserPromptSubmit", "PostToolUse", "PostToolUse", "Stop", "PermissionRequest"]
    base_t = MAINTENANT - timedelta(days=2)
    det = json.dumps(hook("PostToolUse-Bash"))
    lignes = [((base_t + timedelta(seconds=3 * i)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
               agents[i % len(agents)], "s", noms[i % len(noms)], det) for i in range(50_000)]
    b.conn.executemany("INSERT INTO evenements (horodatage, agent, session_id, evenement, details) "
                       "VALUES (?,?,?,?,?)", lignes)
    b.conn.commit()
    monkeypatch.setattr(git, "lire_git", _VRAI_LIRE_GIT)
    duree, d = meilleur(lambda: instantane(tmp_path, MAINTENANT), 3)
    ms = duree * 1000
    b.conn.close()
    with capsys.disabled():
        print(f"\n[perf] instantane 10 équipes / 50 000 événements / 10 branches = {ms:.0f} ms "
              f"(duree_collecte_ms = {d['duree_collecte_ms']})")
    assert all(s["ok"] for s in d["sources"] if s["nom"] in ("structure", "registre", "git")), d["sources"]
    assert len(d["equipes"]) == 10
    assert "recouvrement:equipe0+equipe1:src/commun.py" in {a["id"] for a in d["alarmes"]}
    assert ms < 2000


# --- corrections après revue ------------------------------------------------------------------

def test_session_end_avec_session_encore_ouverte_est_arrete(base, faux):
    base.evt(W, "SessionEnd", "SessionEnd", 2)
    a = agent(snap(base.racine), W)
    assert (a["vivant"], a["etat"], a["etat_source"], a["etat_depuis"]) == (True, "arrete", "hook:SessionEnd", iso(2))


def test_vivant_sans_evenement_d_etat_inconnu_depuis_creation_de_session(base, faux):
    base.evt(W, "SessionStart", "SessionStart", 30)  # connu du registre, aucun événement d'état
    d = snap(base.racine)
    for aid in (W, "coord-page"):  # coord-page : inconnu du registre
        a = agent(d, aid)
        assert (a["etat"], a["etat_source"], a["etat_depuis"]) == ("inconnu", "aucun_evenement", iso(60))


def test_coordinateur_d_equipe_speciale_seulement_s_il_est_vu(tmp_path, faux):
    _orga(tmp_path, ("observation", "page", "integration"))
    ids = {a["id"] for a in instantane(tmp_path, MAINTENANT)["agents"]}
    assert "coord-page" in ids and "coord-integration" not in ids
    faux.sessions["cc-coord-integration"] = {**_session(), "identite": "coord-integration"}
    a = agent(instantane(tmp_path, MAINTENANT), "coord-integration")
    assert a["vivant"] is True and a["equipe"] == "integration"


def test_coordinateur_d_equipe_speciale_vu_dans_le_registre(base, faux):
    (base.racine / ".orga" / "teams" / "integration" / "tasks").mkdir(parents=True)
    (base.racine / ".orga" / "teams" / "integration" / "mandate.md").write_text("# Mandat\n", encoding="utf-8")
    base.evt("coord-integration", "Stop", "Stop", 3)
    a = agent(snap(base.racine), "coord-integration")
    assert (a["vivant"], a["etat"], a["etat_source"]) == (False, "arrete", "tmux:session_absente")


def test_rapport_action_lu(base, faux):
    m = base.msg("assistant", "utilisateur", "rapport_utilisateur", 10, resume="Rapport de vérification")
    att = [x for x in snap(base.racine)["attentes_utilisateur"] if x["id"] == f"msg-{m}"]
    assert att and att[0]["nature"] == "rapport" and att[0]["actions"] == ["lu"]


# --- depuis mesurés (git, transcript) -------------------------------------------

def _reponse(i, contexte, ts):
    return json.dumps({"type": "assistant", "isSidechain": False, "timestamp": ts,
                       "message": {"id": f"m{i}", "model": "claude-opus-5-5", "usage": {
                           "input_tokens": 0, "cache_creation_input_tokens": 0,
                           "cache_read_input_tokens": contexte, "output_tokens": 1}}}) + "\n"


def test_contexte_plein_depuis_la_premiere_reponse_au_dessus(base, faux, tmp_path):
    # fabriqué à la main : 100 k, 700 k (/compact) 50 k, puis 650 k et 700 k jetons sur 1 M
    t = tmp_path / "contexte.jsonl"
    t.write_text("".join(_reponse(i, c, f"2026-10-07T13:0{i}:00.000Z")
                         for i, c in enumerate([100_000, 700_000, 50_000, 650_000, 700_000])))
    base.evt("coord-page", "Stop", "Stop", 1, transcript_path=str(t))
    al = types(snap(base.racine), "contexte_plein")
    assert [(a["id"], a["depuis"]) for a in al] == [
        ("contexte_plein:coord-page:claude-opus-5-5", "2026-10-07T13:03:00.000Z")]


def test_depuis_git_sur_un_vrai_depot(tmp_path, faux, monkeypatch):
    monkeypatch.setattr(git, "lire_git", _VRAI_LIRE_GIT)
    _orga(tmp_path)
    _depot(tmp_path, {"observation": ["src/commun.py"], "page": ["src/commun.py"]})
    d = instantane(tmp_path, MAINTENANT)
    par_id = {a["id"]: a for a in d["alarmes"]}
    rec = par_id["recouvrement:observation+page:src/commun.py"]
    hors = {e: par_id[f"hors_perimetre:{e}:src/commun.py"]["depuis"] for e in ("observation", "page")}
    assert all(h and h.endswith("Z") and len(h) == 24 for h in hors.values())
    assert rec["depuis"] == max(hors.values())  # le recouvrement naît avec le second commit


def test_depuis_git_transmis_aux_alarmes(base, faux):
    faux.git = {
        "equipes": {"page": {"branche": "equipe/page", "commit": "b", "fichiers_touches": ["x.py"],
                             "hors_perimetre": ["x.py"], "retard_sur_base": 1,
                             "dates_fichiers": {"x.py": "2026-10-07T09:00:00.000Z"},
                             "retard_depuis": "2026-10-07T08:00:00.000Z"}},
        "recouvrements": [{"fichier": "x.py", "equipes": ["observation", "page"],
                           "depuis": "2026-10-07T10:00:00.000Z"}],
    }
    par_id = {a["id"]: a["depuis"] for a in snap(base.racine)["alarmes"]}
    assert par_id["hors_perimetre:page:x.py"] == "2026-10-07T09:00:00.000Z"
    assert par_id["retard_sur_base:page:main"] == "2026-10-07T08:00:00.000Z"
    assert par_id["recouvrement:observation+page:x.py"] == "2026-10-07T10:00:00.000Z"


# --- bloque_au_demarrage ------------------------------------------------------------------

def _ecran(faux, nom, agent_="coord-page", creee_il_y_a_min=3):
    faux.captures[f"cc-{agent_}"] = (CAPTURES / nom).read_text(encoding="utf-8")
    faux.sessions[f"cc-{agent_}"]["creee"] = iso(creee_il_y_a_min)


@pytest.mark.parametrize("nom,mot", [("demarrage-confiance-dossier.ansi", "confiance du dossier"),
                                      ("demarrage-imports-externes.ansi", "imports externes")])
def test_bloque_au_demarrage_a_3_min(base, faux, nom, mot):
    base.evt("coord-observation", "SessionStart", "UserPromptSubmit", 30)  # le registre est lisible
    _ecran(faux, nom)
    d = snap(base.racine)
    al = types(d, "bloque_au_demarrage")
    assert len(al) == 1
    epoch = int(datetime.fromisoformat(faux.sessions["cc-coord-page"]["activite"].replace("Z", "+00:00")).timestamp())
    assert al[0]["id"] == f"bloque_au_demarrage:coord-page:{epoch}"
    assert al[0]["gravite"] == "grave" and al[0]["depuis"] == iso(3) and al[0]["equipes"] == ["page"]
    assert mot in al[0]["mesure"] and "3 min" in al[0]["mesure"]
    assert "cc-coord-page" in al[0]["quoi_faire"]
    assert d["attentes_utilisateur"] == []
    assert agent(d, "coord-page")["etat"] == "inconnu"
    assert next(e for e in d["equipes"] if e["nom"] == "page")["statut"] == "bloquee"


def test_pas_d_alarme_a_1_min(base, faux):
    base.evt("coord-observation", "UserPromptSubmit", "UserPromptSubmit", 30)
    _ecran(faux, "demarrage-confiance-dossier.ansi", creee_il_y_a_min=1)
    assert types(snap(base.racine), "bloque_au_demarrage") == []


def test_pas_d_alarme_si_evenement_depuis_la_creation(base, faux):
    base.evt("coord-page", "UserPromptSubmit", "UserPromptSubmit", 2)
    _ecran(faux, "demarrage-confiance-dossier.ansi", creee_il_y_a_min=3)
    assert types(snap(base.racine), "bloque_au_demarrage") == []


def test_alarme_si_evenement_anterieur_a_la_creation(base, faux):
    base.evt("coord-page", "Stop", "Stop", 20)
    _ecran(faux, "demarrage-confiance-dossier.ansi", creee_il_y_a_min=3)
    assert len(types(snap(base.racine), "bloque_au_demarrage")) == 1


def test_pas_d_alarme_si_registre_en_echec(tmp_path, faux):
    _orga(tmp_path)  # pas de registre
    _ecran(faux, "demarrage-confiance-dossier.ansi")
    assert types(instantane(tmp_path, MAINTENANT), "bloque_au_demarrage") == []


def test_pas_d_alarme_pour_l_assistant(base, faux):
    base.evt("coord-observation", "UserPromptSubmit", "UserPromptSubmit", 30)
    _ecran(faux, "demarrage-confiance-dossier.ansi", agent_="assistant")
    assert types(snap(base.racine), "bloque_au_demarrage") == []


def test_pas_d_alarme_terminal_qui_cite_l_ecran(base, faux):
    from test_tmux import citation_au_milieu
    base.evt("coord-observation", "UserPromptSubmit", "UserPromptSubmit", 30)
    faux.captures["cc-coord-page"] = citation_au_milieu()
    faux.sessions["cc-coord-page"]["creee"] = iso(10)
    assert types(snap(base.racine), "bloque_au_demarrage") == []


# --- statut d'équipe -----------------------------------------------------------

def statut(d, nom="page"):
    return next(e for e in d["equipes"] if e["nom"] == nom)["statut"]


def test_statut_terminee(base, faux):
    (base.racine / ".orga" / "teams" / "page" / "CLOTUREE").write_text("x")
    base.evt("coord-page", "PermissionRequest", "PermissionRequest-Bash", 6, demande_id="d")
    assert statut(snap(base.racine)) == "terminee"


def test_cloturee_le_transmis(base, faux):
    # Format écrit par l'hôte (actions_cloture.py) ; heure fabriquée.
    (base.racine / ".orga" / "teams" / "page" / "CLOTUREE").write_text(
        "auteur: utilisateur\nheure: 2026-10-07T21:12:03.456Z\ndemande: 3\nrapport: 4\n")
    eqs = {e["nom"]: e for e in snap(base.racine)["equipes"]}
    assert eqs["page"]["statut"] == "terminee" and eqs["page"]["cloturee_le"] == "2026-10-07T21:12:03.456Z"
    assert all(e["cloturee_le"] is None for n, e in eqs.items() if n != "page")


def test_statut_bloquee_par_autorisation(base, faux):
    base.evt("coord-page", "PermissionRequest", "PermissionRequest-Bash", 1, demande_id="d")
    assert statut(snap(base.racine)) == "bloquee"


def test_statut_active_agent_qui_travaille(base, faux):
    del faux.sessions["cc-" + W]
    base.evt("coord-page", "UserPromptSubmit", "UserPromptSubmit", 1)
    assert statut(snap(base.racine)) == "active"


def test_statut_active_deux_workers_vivants_sans_evenement(base, faux):
    base.evt("coord-observation", "UserPromptSubmit", "UserPromptSubmit", 1)  # registre lisible
    for t in ("t1", "t2"):
        faux.sessions[f"cc-worker-page-{t}"] = {**_session(), "identite": f"worker-page-{t}"}
    d = snap(base.racine)
    assert statut(d) == "active"


def test_statut_au_repos(base, faux):
    base.evt("coord-page", "Stop", "Stop", 5)
    assert statut(snap(base.racine)) == "au_repos"


def test_statut_null_sans_evenement_ni_worker_vivant(base, faux):
    base.evt("coord-observation", "UserPromptSubmit", "UserPromptSubmit", 1)
    assert statut(snap(base.racine)) is None


def test_titre_tache_repli_sur_le_nom_du_fichier(tmp_path):
    d = tmp_path / ".orga" / "teams" / "obs" / "tasks" / "in-progress"
    d.mkdir(parents=True)
    (d / "t9-sans-titre.md").write_text("\nCorps sans titre.\n", encoding="utf-8")
    (d / "t1-ok.md").write_text("# Tâche : avec titre\n", encoding="utf-8")
    assert _titre_tache(tmp_path, "obs", "t9-sans-titre") == "t9-sans-titre"
    assert _titre_tache(tmp_path, "obs", "t1-ok") == "avec titre"
    assert _titre_tache(tmp_path, "obs", "absent") is None


# --- conversation utilisateur ↔ Assistant privée par défaut -------------------------

def _conversation(base):
    base.evt("assistant", "UserPromptSubmit", "UserPromptSubmit", 30, prompt="Secret de l'utilisateur")
    base.evt("assistant", "Stop", "Stop", 29, last_assistant_message="Je lance maintenant la tâche T2.")
    base.msg("assistant", "utilisateur", "decision_utilisateur", 20, resume="Choisir le port", equipe="page")
    base.msg("assistant", "coord-page", "consigne", 50, resume="Construire la page")


def test_par_defaut_aucun_texte_de_la_conversation(base, faux):
    _conversation(base)
    d = snap(base.racine)
    texte = json.dumps(d, ensure_ascii=False)
    for secret in ("Secret de l'utilisateur", "Je lance maintenant", "Choisir le port"):
        assert secret not in texte
    a = agent(d, "assistant")
    assert (a["derniere_phrase"], a["brouillon"], a["etat"]) == (None, None, "au_repos")
    prives = [m for m in d["fil"] if {m["de"], m["a"]} <= {"utilisateur", "assistant"}]
    assert len(prives) == 3 and all(m["resume"] is None and m["horodatage"] for m in prives)
    assert [m["resume"] for m in d["fil"] if m["a"] == "coord-page"] == ["Construire la page"]
    assert agent(d, "coord-page")["tache"] == "Construire la page"
    att = next(x for x in d["attentes_utilisateur"] if x["nature"] == "decision")
    assert att["titre"] is None and att["depuis"]


def test_complet_tout_le_texte(base, faux):
    _conversation(base)
    d = instantane(base.racine, MAINTENANT, complet=True)
    texte = json.dumps(d, ensure_ascii=False)
    for secret in ("Secret de l'utilisateur", "Je lance maintenant", "Choisir le port"):
        assert secret in texte
    assert agent(d, "assistant")["derniere_phrase"] == "Je lance maintenant la tâche T2."


# --- B3 : agent figé -------------------------------------------------------------------------

def test_fige_a_voir_puis_grave(base, faux):
    base.evt(W, "UserPromptSubmit", "UserPromptSubmit", 20)
    faux.sessions[f"cc-{W}"]["activite"] = iso(18)
    d = snap(base.racine)
    assert agent(d, W)["etat"] == "travaille"
    [al] = types(d, "fige")
    epoch = int((MAINTENANT - timedelta(minutes=18)).timestamp())
    assert (al["id"], al["gravite"], al["depuis"]) == (f"fige:{W}:{epoch}", "a_voir", iso(18))
    assert al["agents"] == [W] and al["equipes"] == ["observation"]
    [al] = types(snap(base.racine, minutes_plus_tard=30), "fige")
    assert (al["id"], al["gravite"]) == (f"fige:{W}:{epoch}", "grave")


def test_fige_pas_d_alarme(base, faux):
    base.evt(W, "UserPromptSubmit", "UserPromptSubmit", 20)  # fenêtre active il y a 3 min
    base.evt("coord-page", "UserPromptSubmit", "UserPromptSubmit", 5)  # événement récent
    faux.sessions["cc-coord-page"]["activite"] = iso(30)
    base.evt("coord-observation", "Stop", "Stop", 40, last_assistant_message="Fini.")  # au repos
    faux.sessions["cc-coord-observation"]["activite"] = iso(40)
    assert types(snap(base.racine), "fige") == []


def test_fige_pas_d_alarme_sans_tmux(base, faux):
    base.evt(W, "UserPromptSubmit", "UserPromptSubmit", 20)
    faux.tmux_ok = False
    assert types(snap(base.racine), "fige") == []


# --- B5 : en avance sur la base ----------------------------------------------------------------

def test_en_avance_sur_base_transmis_sans_alarme(base, faux):
    faux.git = {"equipes": {"observation": {"branche": "equipe/observation", "commit": "aaa", "fichiers_touches": [],
                                            "hors_perimetre": [], "retard_sur_base": 0, "en_avance_sur_base": 5},
                            "page": {"branche": "equipe/page", "commit": None, "fichiers_touches": None,
                                     "hors_perimetre": None, "retard_sur_base": None, "en_avance_sur_base": None}},
                "recouvrements": []}
    d = snap(base.racine)
    eqs = {e["nom"]: e["en_avance_sur_base"] for e in d["equipes"]}
    assert eqs == {"observation": 5, "page": None}
    assert [a for a in d["alarmes"] if "avance" in a["id"]] == []


# --- attentes et questions ------------------------------------------------------------------------

def test_attentes_portent_leur_equipe(base, faux):
    base.evt(W, "PermissionRequest", "PermissionRequest-Write", 6, demande_id="d-9")
    base.msg("assistant", "utilisateur", "decision_utilisateur", 20, resume="Choisir le port", equipe="page")
    base.msg("assistant", "utilisateur", "rapport_utilisateur", 10, resume="Nuit calme")
    eqs = {x["id"].split("-")[0] + ":" + x["nature"]: x["equipe"] for x in snap(base.racine)["attentes_utilisateur"]}
    assert eqs == {"perm:autorisation": "observation", "msg:decision": "page", "msg:rapport": None}


def test_question_en_attente_ne_bloque_pas_une_equipe_qui_travaille(base, faux):
    base.msg("coord-page", "assistant", "question", 40, resume="Quel port ?")
    base.evt("coord-page", "UserPromptSubmit", "UserPromptSubmit", 5)
    d = snap(base.racine)
    assert agent(d, "coord-page")["etat"] == "travaille"
    assert next(e for e in d["equipes"] if e["nom"] == "page")["statut"] == "active"


# --- sessions hors organigramme, décisions récentes ---------------------------------------

def test_sessions_hors_organigramme_et_alarme(base, faux):
    faux.sessions["cc-essai-t17"] = {"identite": None, "creee": iso(90), "activite": iso(2)}
    faux.sessions["cc-integration-check"] = {"identite": None, "creee": iso(30), "activite": iso(1)}
    faux.sessions["cc-coord-inconnue"] = {"identite": "coord-inconnue", "creee": iso(5), "activite": iso(1)}
    d = snap(base.racine)
    assert d["sessions_hors_organigramme"] == [
        {"nom": "cc-coord-inconnue", "depuis": iso(5), "activite": iso(1)},
        {"nom": "cc-essai-t17", "depuis": iso(90), "activite": iso(2)},
        {"nom": "cc-integration-check", "depuis": iso(30), "activite": iso(1)}]
    [al] = types(d, "session_orpheline")
    epoch = int((MAINTENANT - timedelta(minutes=90)).timestamp())
    assert (al["id"], al["gravite"], al["depuis"]) == (f"session_orpheline:cc-essai-t17:{epoch}", "a_voir", iso(90))
    assert (al["agents"], al["equipes"]) == ([], [])


def test_sessions_hors_organigramme_null_sans_tmux(base, faux):
    faux.tmux_ok = False
    d = snap(base.racine)
    assert d["sessions_hors_organigramme"] is None and types(d, "session_orpheline") == []


def test_aucune_session_hors_organigramme(base, faux):
    assert snap(base.racine)["sessions_hors_organigramme"] == []


def test_decisions_recentes(base, faux):
    assert snap(base.racine)["decisions_recentes"] is None  # pas de CHANGELOG
    d = base.racine / ".orga" / "contracts"
    d.mkdir()
    lignes = ["# Historique", "", "## Pas daté", ""] + [f"## 2026-10-{j:02d} — etat 1.{j}\n\n- détail" for j in range(1, 13)]
    (d / "CHANGELOG.md").write_text("\n".join(lignes) + "\n", encoding="utf-8")
    dec = snap(base.racine)["decisions_recentes"]
    assert len(dec) == 10
    assert dec[0] == {"date": "2026-10-12", "titre": "etat 1.12"} and dec[-1] == {"date": "2026-10-03", "titre": "etat 1.3"}


# --- le registre alimente l'instantané ----------------------------------------

def test_version_2_et_champs_retires(base, faux):
    d = snap(base.racine)
    assert d["version"] == 2
    assert "integration" not in d
    assert d["flux"] == [] and d["aretes"] == [] and d["ordres"] == []
    assert d["facteur"] == {"battement": None, "age_s": None, "arrete": True}


def test_agents_portent_dettes_file_et_occupation(base, faux):
    base.msg("assistant", "coord-page", "travail_pret", 9, resume="À relire", objet="revue:page")
    base.msg("assistant", "coord-page", "consigne", 8, resume="Ensuite")
    base.conn.execute("INSERT INTO transitions (horodatage, message_id, etat, auteur, preuve)"
                      " VALUES (?,1,'livre','cime','{}')", (iso(8),))
    base.conn.execute("INSERT INTO occupation VALUES ('coord-page', 'tour', ?)", (iso(1),))
    base.conn.commit()
    d = snap(base.racine)
    page = agent(d, "coord-page")
    assert page["dettes"] == [{"id": 1, "attendu": "revue", "de": "assistant",
                               "objet": "revue:page", "depuis": iso(9)}]
    assert [m["id"] for m in page["file"]] == [2] and page["occupe_par"] == "tour"
    assert agent(d, "coord-observation")["dettes"] == [] and agent(d, "coord-observation")["occupe_par"] is None


def test_cime_n_est_pas_un_agent(base, faux):
    base.msg("cime", "coord-page", "signalement", 5, resume="contexte", objet="contexte:coord-page")
    base.evt("cime", "Stop", "Stop", 4)
    d = snap(base.racine)
    assert "cime" not in [a["id"] for a in d["agents"]]
    assert [f["de"] for f in d["flux"]] == ["cime"]


def test_attente_utilisateur_porte_message_id_et_objet(base, faux):
    base.msg("assistant", "utilisateur", "decision_utilisateur", 20, resume="Fusionner ?", objet="fusion:page:abc1234")
    [att] = snap(base.racine, )["attentes_utilisateur"]
    assert (att["message_id"], att["objet"], att["nature"]) == (1, "fusion:page:abc1234", "decision")


def test_la_question_sans_obligation_n_est_plus_une_attente(base, faux):
    base.msg("coord-page", "assistant", "question", 40, resume="Quel port ?", obligation=False)
    d = snap(base.racine)
    assert [m["en_attente"] for m in d["fil"]] == [False]
    assert agent(d, "coord-page")["etat"] != "attend_reponse"


def test_masque_de_la_conversation_utilisateur_assistant_dans_le_nouveau_modele(base, faux):
    base.msg("utilisateur", "assistant", "consigne", 9, resume="secret de l'utilisateur", objet="prive",
             obligation=False)
    base.msg("assistant", "utilisateur", "decision_utilisateur", 8, resume="secret de l'Assistant", objet="prive2")
    d = snap(base.racine)
    assert all(m["resume"] is None and m["objet"] is None for m in d["flux"])
    assert all(m["resume"] is None and m["preuve"] is None for m in d["fil"] if m["source"] == "registre")
    assert agent(d, "utilisateur")["dettes"][0]["objet"] is None
    complet = instantane(base.racine, MAINTENANT, complet=True)
    assert [m["resume"] for m in complet["flux"]] == ["secret de l'utilisateur", "secret de l'Assistant"]


def test_actions_d_une_decision_de_fusion_ou_de_chantier(base, faux):
    base.msg("assistant", "utilisateur", "decision_utilisateur", 9, resume="Fusionner ?", objet="fusion:page:abc1234")
    base.msg("assistant", "utilisateur", "decision_utilisateur", 8, resume="Phase 4 ?", objet="chantier:page:4")
    base.msg("assistant", "utilisateur", "decision_utilisateur", 7, resume="Quel port ?", objet="port")
    base.msg("assistant", "utilisateur", "decision_utilisateur", 6, resume="Sans objet")
    actions = {x["message_id"]: x["actions"] for x in snap(base.racine)["attentes_utilisateur"]}
    assert actions == {1: ["accorder", "refuser"], 2: ["accorder", "refuser"], 3: ["trancher"], 4: ["trancher"]}
