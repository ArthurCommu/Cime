"""Alarmes : seuils, gravités, destinataires et identifiants stables, calculés sur des mesures fabriquées."""

from datetime import datetime, timedelta, timezone

import pytest

from cime.observation import alarmes
from cime.signaux import echeances

MAINTENANT = datetime(2026, 10, 7, 14, 0, 0, tzinfo=timezone.utc)


def iso(minutes_ago: float) -> str:
    dt = MAINTENANT - timedelta(minutes=minutes_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# --- calcul direct ------------------------------------------------------------------------

def _agent(aid="coord-page", **champs):
    a = {"id": aid, "role": "coordinateur", "equipe": "page", "parent": "assistant",
         "session_tmux": f"cc-{aid}", "vivant": True, "etat": "travaille", "etat_depuis": iso(1),
         "etat_source": "hook:PostToolUse", "tache": None, "derniere_phrase": None,
         "modele": "claude-opus-5-5", "contexte": None, "cout_usd_estime": None, "brouillon": None, "consommation": None}
    a.update(champs)
    return a


def _calculer(agents=(), internes=None, **kw):
    params = dict(agents=list(agents), internes=internes or {}, equipes=[], recouvrements=[],
                  questions=[], refus=[], tmux_ok=True,
                  branche_reference="main",
                  equipe_de=lambda a: a.split("-")[1] if a and a.startswith(("coord-", "worker-")) else None,
                  maintenant=MAINTENANT)
    params.update(kw)
    return alarmes.calculer(**params)


def test_seuils_de_temps_lus_dans_la_table_des_echeances():
    """Source unique : les seuils d'obligation ne sont pas écrits dans alarmes.py."""
    assert alarmes.SEUIL_AUTORISATION == echeances.ECHELLES["autorisation"][1].delai == timedelta(minutes=2)
    assert alarmes.SEUIL_QUESTION == echeances.ECHELLES["question"][0].delai == timedelta(minutes=15)
    assert alarmes.SEUIL_REPOS == echeances.ECHELLES["contexte"][1].delai
    assert alarmes.SEUIL_LIVRAISON_BLOQUEE == echeances.DELAI_OCCUPE
    assert alarmes.SEUIL_FIGE == echeances.FIGE and alarmes.SEUIL_ASSISTANT_SOURD == echeances.ASSISTANT_SOURD
    assert alarmes.SEUIL_CONTEXTE == 0.60
    assert alarmes.DUREE_REFUS_VISIBLE == timedelta(minutes=30)
    assert "arret_apres_annonce" not in alarmes.GRAVITES


@pytest.mark.parametrize("tokens,attendu", [(600_000, 0), (600_001, 1)])
def test_contexte_plein_au_dessus_de_60_pourcent(tokens, attendu):
    a = _agent(contexte={"tokens": tokens, "limite": 1_000_000, "source": "transcript"})
    al = _calculer([a])
    assert len(al) == attendu
    if attendu:
        assert al[0]["id"] == "contexte_plein:coord-page:claude-opus-5-5"
        assert al[0]["gravite"] == "a_voir"
        assert "600 001 jetons sur 1 000 000 (60 %, seuil 60 %)" in al[0]["mesure"]


def test_contexte_limite_inconnue_pas_d_alarme():
    a = _agent(contexte={"tokens": 900_000, "limite": None, "source": "transcript"})
    assert _calculer([a]) == []


@pytest.mark.parametrize("age,attendu", [(14, 0), (16, 1)])
def test_question_sans_reponse_15_minutes(age, attendu):
    q = {"id": "msg-64", "de": "worker-observation-tmux", "a": "coord-observation",
         "horodatage": iso(age), "resume": "Quel préfixe ?"}
    al = _calculer(questions=[q])
    assert len(al) == attendu
    if attendu:
        assert al[0]["id"] == "question_sans_reponse:worker-observation-tmux:msg-64"
        assert al[0]["gravite"] == "grave"
        assert al[0]["equipes"] == ["observation"]


@pytest.mark.parametrize("age,attendu", [(29, 1), (31, 0)])
def test_action_refusee_visible_30_minutes(age, attendu):
    r = {"id": 5127, "agent": "coord-hote", "horodatage": iso(age), "tool_name": "Bash",
         "resume_outil": "git push origin main", "motif": "git push interdit"}
    al = _calculer(refus=[r])
    assert len(al) == attendu
    if attendu:
        assert al[0]["id"] == "action_refusee:coord-hote:5127"
        assert al[0]["gravite"] == "a_voir"
        assert "git push origin main" in al[0]["mesure"] and "git push interdit" in al[0]["mesure"]


def test_action_refusee_motif_termine_par_un_point_pas_de_double_point():
    r = {"id": 1, "agent": "coord-hote", "horodatage": iso(1), "tool_name": "Bash",
         "resume_outil": "git push", "motif": "git push interdit."}
    mesure = _calculer(refus=[r])[0]["mesure"]
    assert mesure.endswith("git push interdit.") and ".." not in mesure


def test_retard_sur_base_info_et_mesures_absentes_sans_alarme():
    eq = [{"nom": "page", "branche": "equipe/page", "statut": "active", "hors_perimetre": None,
           "retard_sur_base": 2},
          {"nom": "hote", "branche": "equipe/hote", "statut": "active", "hors_perimetre": None,
           "retard_sur_base": None}]
    al = _calculer(equipes=eq)
    assert [(a["id"], a["gravite"]) for a in al] == [("retard_sur_base:page:main", "info")]


def test_sources_absentes_aucune_alarme():
    a = _agent(etat="inconnu", vivant=None, etat_depuis=None)
    assert _calculer([a], equipes=None, recouvrements=None, questions=None, refus=None,
                     signaux=None, tmux_ok=False) == []


def test_tri_grave_d_abord():
    eq = [{"nom": "page", "branche": "equipe/page", "statut": "active",
           "hors_perimetre": ["a.py"], "retard_sur_base": 1}]
    al = _calculer(equipes=eq, recouvrements=[{"fichier": "b.py", "equipes": ["page", "hote"]}])
    assert [a["gravite"] for a in al] == ["grave", "a_voir", "info"]
    assert al[0]["id"] == "recouvrement:hote+page:b.py"


# --- alarmes dérivées des obligations ------------------------------------------

def _signalement(objet, age, **champs):
    o = {"message_id": 7, "debiteur": "assistant", "attendu": "decision", "echeance": None,
         "de": "cime", "a": "assistant", "objet": objet, "resume": "r", "horodatage": iso(age)}
    o.update(champs)
    return o


def _signaux(**champs):
    base = {"obligations": [], "echecs": [], "facteur": {"battement": iso(0.1), "age_s": 6, "arrete": False},
            "attente": {"messages": 0, "ordres": 0}, "courrier_assistant": None,
            "idle_prompt_assistant": None}
    base.update(champs)
    return base


def _en_attente_d_autorisation(**auto):
    d = {"demande_id": "d-1", "tool_name": "Bash", "resume_outil": "ls", "depuis": iso(6)}
    d.update(auto)
    return _agent("worker-page-t1", etat="attend_autorisation", etat_depuis=iso(6),
                  etat_source="hook:PermissionRequest"), {"worker-page-t1": {"autorisation": d}}


@pytest.mark.parametrize("age,attendu", [(1, 0), (3, 1)])
def test_autorisation_en_attente_apres_deux_minutes_de_signalement_ouvert(age, attendu):
    agent, internes = _en_attente_d_autorisation()
    o = _signalement("autorisation:d-1", age, agent_demande="worker-page-t1")
    al = _calculer([agent], internes, signaux=_signaux(obligations=[o]))
    assert len(al) == attendu
    if attendu:
        assert al[0]["id"] == "autorisation_en_attente:worker-page-t1:perm-d-1"
        assert al[0]["gravite"] == "grave" and al[0]["destinataire"] == "utilisateur"  # marche « 2 min : l'utilisateur »


def test_autorisation_sans_obligation_ouverte_ou_agent_repris_pas_d_alarme():
    agent, internes = _en_attente_d_autorisation()
    assert _calculer([agent], internes, signaux=_signaux()) == []                      # aucune obligation
    repris = dict(agent, etat="travaille")
    o = _signalement("autorisation:d-1", 6, agent_demande="worker-page-t1")
    assert _calculer([repris], internes, signaux=_signaux(obligations=[o])) == []      # l'agent a repris
    autre = _signalement("autorisation:d-2", 6, agent_demande="worker-page-t1")
    assert _calculer([agent], internes, signaux=_signaux(obligations=[autre])) == []   # une autre demande


def test_question_sans_reponse_destinataire_suit_l_echelle():
    def q(age):
        return {"id": "msg-5", "de": "worker-page-t1", "a": "coord-page", "horodatage": iso(age), "resume": "?"}
    assert _calculer(questions=[q(16)])[0]["destinataire"] == "coord-page"       # relance au destinataire
    assert _calculer(questions=[q(31)])[0]["destinataire"] == "assistant"        # → sup du destinataire
    assert _calculer(questions=[q(61)])[0]["destinataire"] == "utilisateur"           # → l'utilisateur


@pytest.mark.parametrize("objet,type_", [("session-disparue:worker-page-t1", "session_disparue"),
                                         ("fin-sans-suite:worker-page-t1", "fin_sans_suite")])
def test_signalements_graves_ouverts(objet, type_):
    o = _signalement(objet, 1, a="coord-page", message_id=9)
    [al] = _calculer([_agent("worker-page-t1")], signaux=_signaux(obligations=[o]))
    assert al["type"] == type_ and al["gravite"] == "grave" and al["agents"] == ["worker-page-t1"]
    assert al["destinataire"] == "coord-page"
    plus_tard = _calculer([_agent("worker-page-t1")], signaux=_signaux(obligations=[dict(o, horodatage=iso(11))]))
    assert plus_tard[0]["destinataire"] == "assistant"                           # 10 min : → sup du sup
    assert _calculer([_agent("worker-page-t1")], signaux=_signaux()) == []        # fermé : plus d'alarme


def test_session_disparue_d_une_equipe_terminee_ignoree():
    o = _signalement("session-disparue:worker-page-t1", 1, a="coord-page")
    eq = [{"nom": "page", "statut": "terminee", "branche": "equipe/page", "hors_perimetre": None,
           "retard_sur_base": None}]
    assert _calculer([_agent("worker-page-t1")], equipes=eq, signaux=_signaux(obligations=[o])) == []


def test_session_disparue_adressee_a_utilisateur_tant_que_le_signalement_est_ouvert():
    """Un signalement à l'utilisateur n'a pas d'obligation ; il se lit comme « accuse » dû à l'utilisateur."""
    o = _signalement("session-disparue:worker-page-t1", 1, a="utilisateur", debiteur="utilisateur", attendu="accuse")
    [al] = _calculer([_agent("worker-page-t1")], signaux=_signaux(obligations=[o]))
    assert (al["type"], al["gravite"], al["destinataire"]) == ("session_disparue", "grave", "utilisateur")
    assert _calculer([_agent("worker-page-t1")], signaux=_signaux()) == []         # clos : plus d'alarme


def test_livraison_echouee_signalee_a_utilisateur_reste_visible_jusqu_a_sa_fermeture():
    e = {"id": 12, "a": "worker-page-t1", "resume": "x", "depuis": iso(3), "signale_a": "utilisateur"}
    [al] = _calculer(signaux=_signaux(echecs=[e]))
    assert al["destinataire"] == "utilisateur"


def test_livraison_echouee_tant_que_le_superieur_n_a_pas_pris_acte():
    e = {"id": 12, "a": "worker-page-t1", "resume": "x", "depuis": iso(3), "signale_a": "coord-page"}
    [al] = _calculer(signaux=_signaux(echecs=[e]))
    assert (al["type"], al["gravite"], al["destinataire"]) == ("livraison_echouee", "grave", "coord-page")
    assert al["id"] == "livraison_echouee:worker-page-t1:msg-12"
    assert _calculer(signaux=_signaux(echecs=[])) == []


def _bloque(age, etat="inconnu"):
    return _agent("coord-page", etat=etat, file=[{"id": 3, "depuis": iso(age)}])


@pytest.mark.parametrize("age,etat,attendu", [(9, "inconnu", 0), (11, "inconnu", 1), (11, "au_repos", 0)])
def test_livraison_bloquee_agent_inconnu_depuis_plus_de_delai_occupe(age, etat, attendu):
    al = _calculer([_bloque(age, etat)], signaux=_signaux())
    assert len(al) == attendu
    if attendu:
        assert al[0]["id"] == "livraison_bloquee:coord-page:msg-3" and al[0]["destinataire"] == "assistant"


@pytest.mark.parametrize("arrete,attente,attendu", [
    (True, {"messages": 1, "ordres": 0}, 1), (True, {"messages": 0, "ordres": 2}, 1),
    (True, {"messages": 0, "ordres": 0}, 0), (False, {"messages": 3, "ordres": 0}, 0)])
def test_facteur_arrete_seulement_si_quelque_chose_attend(arrete, attente, attendu):
    facteur = {"battement": iso(2), "age_s": 120, "arrete": arrete}
    al = _calculer(signaux=_signaux(facteur=facteur, attente=attente))
    assert len(al) == attendu
    if attendu:
        assert (al[0]["type"], al[0]["gravite"], al[0]["destinataire"]) == ("facteur_arrete", "grave", "assistant")


@pytest.mark.parametrize("idle_age,courrier_age,attendu", [
    (3, 5, 1),      # idle_prompt il y a 3 min, courrier plus ancien : sourd
    (1, 5, 0),      # idle_prompt trop récent
    (3, 2, 0),      # le courrier est postérieur à l'idle_prompt : pas encore laissé à lui-même
])
def test_assistant_sourd(idle_age, courrier_age, attendu):
    sig = _signaux(courrier_assistant={"id": 4, "cree": iso(courrier_age)}, idle_prompt_assistant=iso(idle_age))
    al = _calculer(signaux=sig)
    assert len(al) == attendu
    if attendu:
        assert (al[0]["type"], al[0]["destinataire"]) == ("assistant_sourd", "utilisateur")


def test_assistant_sourd_pas_d_alarme_sans_courrier_ou_sans_idle():
    assert _calculer(signaux=_signaux(idle_prompt_assistant=iso(5))) == []
    assert _calculer(signaux=_signaux(courrier_assistant={"id": 4, "cree": iso(9)})) == []


def test_chaque_alarme_a_un_destinataire():
    r = {"id": 1, "agent": "worker-page-t1", "horodatage": iso(1), "tool_name": "Bash",
         "resume_outil": "rm -rf x", "motif": "m"}
    eq = [{"nom": "page", "branche": "equipe/page", "statut": "active", "hors_perimetre": ["a.py"],
           "retard_sur_base": 1}]
    al = _calculer(refus=[r], equipes=eq, recouvrements=[{"fichier": "b.py", "equipes": ["page", "hote"]}])
    assert {a["type"]: a["destinataire"] for a in al} == {
        "action_refusee": "coord-page", "recouvrement": "assistant", "hors_perimetre": "assistant",
        "retard_sur_base": "assistant"}


def test_aucune_alarme_dependante_du_registre_si_signaux_absents():
    assert _calculer([_agent("coord-page", etat="inconnu", file=[{"id": 1, "depuis": iso(60)}])],
                     signaux=None) == []
