"""Un coordinateur au repos, sans dette, depuis assez longtemps est fermé (sa conversation est gardée) :
l'événement `CoordEndormi` est inscrit avant la fermeture de la session tmux."""
from datetime import timedelta

import pytest

from aide import lignes
from aide_repos import (
    ASSISTANT, CONVERSATION, COORD, S_ASSISTANT, S_COORD, S_WORKER, ajouter_session, au_repos,
    courrier_ouvert, dans, evenements, evt, evt_a, evt_sans_agent, machine, obligation_seule,  # noqa: F401
    poster, projet, regler_repos, tache_en_cours, transition,  # noqa: F401
)
from cime.fondation import fermeture
from cime.signaux import echeances, facteur, livraison, repos


def endormi_a_la_fin(projet, minutes=25):
    return repos.endormir(projet, dans(minutes))


def rien_ne_se_passe(projet, machine, minutes=25):
    assert endormi_a_la_fin(projet, minutes) == []
    assert machine.kills == [] and S_COORD in machine.sessions
    assert evenements(projet, "CoordEndormi") == []


# --- il s'endort -----------------------------------------------------------------------------

def test_un_coordinateur_au_repos_depuis_assez_longtemps_est_endormi(projet, machine):
    au_repos(projet)
    assert endormi_a_la_fin(projet) == [COORD]
    assert machine.kills == [S_COORD] and S_COORD not in machine.sessions
    assert S_ASSISTANT in machine.sessions


def test_l_evenement_porte_l_agent_la_conversation_et_le_delai_sans_agent_ni_session(projet, machine):
    regler_repos(projet, 7)
    au_repos(projet)
    assert endormi_a_la_fin(projet, 8) == [COORD]
    (_, agent, session, details), = evenements(projet, "CoordEndormi")
    assert agent is None and session is None
    assert details == {"auteur": "cime", "agent": COORD, "session": CONVERSATION, "repos_minutes": 7}


def test_une_ligne_de_journal_dit_qui_et_quand(projet, machine):
    au_repos(projet)
    endormi_a_la_fin(projet)
    assert lignes(projet, "SELECT auteur, action, resultat FROM journal") \
        == [("cime", "coord_endormir", "ok")]


def test_l_evenement_est_inscrit_avant_la_fermeture_de_la_session(projet, machine):
    vus = []
    machine.avant_kill.append(lambda session: vus.append(
        (session, [e[3]["agent"] for e in evenements(projet, "CoordEndormi")])))
    au_repos(projet)
    endormi_a_la_fin(projet)
    assert vus == [(S_COORD, [COORD])]


def test_la_conversation_retenue_est_celle_du_dernier_evenement(projet, machine):
    evt(projet, COORD, "SessionStart", "ancienne", source="startup")
    evt(projet, COORD, "SessionStart", "recente", source="resume")
    evt(projet, COORD, "Stop", "recente")
    endormi_a_la_fin(projet)
    assert evenements(projet, "CoordEndormi")[0][3]["session"] == "recente"


def test_deux_coordinateurs_au_repos_sont_endormis_chacun_avec_sa_conversation(projet, machine):
    ajouter_session(machine, "essai-coord-y")
    au_repos(projet)
    au_repos(projet, "coord-y", "conv-y")
    assert endormi_a_la_fin(projet) == [COORD, "coord-y"]
    assert [e[3]["session"] for e in evenements(projet, "CoordEndormi")] == [CONVERSATION, "conv-y"]
    assert machine.kills == [S_COORD, "essai-coord-y"]


def test_la_session_d_un_autre_projet_n_est_jamais_touchee(projet, machine):
    ajouter_session(machine, "autre-coord-x")
    au_repos(projet)
    endormi_a_la_fin(projet)
    assert machine.kills == [S_COORD] and "autre-coord-x" in machine.sessions


# --- le délai ---------------------------------------------------------------------------------

def test_au_repos_depuis_moins_de_n_minutes_n_est_pas_endormi(projet, machine):
    au_repos(projet)
    rien_ne_se_passe(projet, machine, minutes=19)


def test_exactement_n_minutes_suffit(projet, machine):
    au_repos(projet)
    (stop,) = lignes(projet, "SELECT horodatage FROM evenements WHERE evenement = 'Stop'")[0]
    assert repos.endormir(projet, echeances._lire(stop) + timedelta(minutes=19, seconds=59)) == []
    assert repos.endormir(projet, echeances._lire(stop) + timedelta(minutes=20)) == [COORD]


def test_le_delai_est_celui_du_manifeste(projet, machine):
    regler_repos(projet, 30)
    au_repos(projet)
    rien_ne_se_passe(projet, machine, minutes=25)
    assert endormi_a_la_fin(projet, minutes=31) == [COORD]


def test_une_session_reprise_depuis_moins_de_n_minutes_n_est_pas_endormie(projet, machine):
    evt_a(projet, COORD, "Stop", dans(-60))
    evt_a(projet, COORD, "SessionStart", dans(-5), source="resume")
    rien_ne_se_passe(projet, machine, minutes=0)
    assert endormi_a_la_fin(projet, minutes=16) == [COORD]


def test_un_repos_ancien_sans_reprise_suffit(projet, machine):
    evt_a(projet, COORD, "Stop", dans(-60))
    assert endormi_a_la_fin(projet, minutes=0) == [COORD]


# --- ce qui l'empêche -------------------------------------------------------------------------

def test_zero_minute_ne_ferme_jamais(projet, machine):
    regler_repos(projet, 0)
    au_repos(projet)
    rien_ne_se_passe(projet, machine, minutes=100000)


def test_projet_ferme_rien_n_est_endormi(projet, machine):
    au_repos(projet)
    fermeture.ecrire_repere(projet, {"conversations": [], "a_relancer": [], "raisons": {},
                                     "taches_en_cours": []})
    rien_ne_se_passe(projet, machine)


def test_l_assistant_n_est_jamais_endormi(projet, machine):
    au_repos(projet, ASSISTANT, "conv-a")
    assert endormi_a_la_fin(projet, minutes=100000) == []
    assert machine.kills == [] and S_ASSISTANT in machine.sessions
    assert evenements(projet, "CoordEndormi") == []


def test_un_coordinateur_qui_travaille_n_est_pas_endormi(projet, machine):
    au_repos(projet)
    evt(projet, COORD, "UserPromptSubmit")
    rien_ne_se_passe(projet, machine)


def test_un_coordinateur_qui_attend_une_autorisation_n_est_pas_endormi(projet, machine):
    au_repos(projet)
    evt(projet, COORD, "PermissionRequest", demande_id="perm-1", tool_name="Bash")
    rien_ne_se_passe(projet, machine)


def test_un_worker_vivant_de_l_equipe_retient_son_coordinateur(projet, machine):
    ajouter_session(machine, S_WORKER)
    au_repos(projet)
    rien_ne_se_passe(projet, machine)


def test_un_worker_vivant_d_une_autre_equipe_ne_le_retient_pas(projet, machine):
    ajouter_session(machine, "essai-worker-y-t")
    au_repos(projet)
    assert endormi_a_la_fin(projet) == [COORD]


def test_une_tache_en_cours_de_l_equipe_retient_son_coordinateur(projet, machine):
    tache_en_cours(projet, "x")
    au_repos(projet)
    rien_ne_se_passe(projet, machine)


def test_une_tache_en_cours_d_une_autre_equipe_ne_le_retient_pas(projet, machine):
    tache_en_cours(projet, "y")
    au_repos(projet)
    assert endormi_a_la_fin(projet) == [COORD]


def test_une_obligation_ouverte_dont_il_est_debiteur_le_retient(projet, machine):
    au_repos(projet)
    obligation_seule(projet, COORD)
    rien_ne_se_passe(projet, machine)


def test_l_obligation_d_un_autre_ne_le_retient_pas(projet, machine):
    au_repos(projet)
    obligation_seule(projet, "coord-y")
    assert endormi_a_la_fin(projet) == [COORD]


def test_un_message_inscrit_a_son_adresse_le_retient(projet, machine):
    au_repos(projet)
    poster(projet, ASSISTANT, COORD)
    rien_ne_se_passe(projet, machine)


def test_un_message_livre_a_son_adresse_le_retient(projet, machine):
    au_repos(projet)
    transition(projet, poster(projet, ASSISTANT, COORD), "livre")
    rien_ne_se_passe(projet, machine)


def test_un_message_clos_ne_le_retient_pas(projet, machine):
    au_repos(projet)
    transition(projet, poster(projet, ASSISTANT, COORD), "clos")
    assert endormi_a_la_fin(projet) == [COORD]


def test_un_courrier_en_cours_de_livraison_le_retient(projet, machine):
    au_repos(projet)
    courrier_ouvert(projet, COORD)
    rien_ne_se_passe(projet, machine)


def test_sans_conversation_connue_au_registre_il_n_est_pas_endormi(projet, machine):
    evt(projet, COORD, "SessionStart", None, source="startup")
    evt(projet, COORD, "Stop", None)
    rien_ne_se_passe(projet, machine)


def test_session_deja_absente_rien_a_fermer_pas_d_evenement(projet, machine):
    au_repos(projet)
    del machine.sessions[S_COORD]
    assert endormi_a_la_fin(projet) == []
    assert machine.kills == [] and evenements(projet, "CoordEndormi") == []


def test_la_dette_d_un_coordinateur_ne_retient_pas_l_autre(projet, machine):
    ajouter_session(machine, "essai-coord-y")
    au_repos(projet)
    au_repos(projet, "coord-y", "conv-y")
    poster(projet, ASSISTANT, "coord-y")
    assert endormi_a_la_fin(projet) == [COORD]
    assert "essai-coord-y" in machine.sessions


def test_un_episode_deja_ouvert_dont_la_session_vit_encore_n_est_pas_repris(projet, machine):
    au_repos(projet)
    evt_sans_agent(projet, "CoordEndormi",
                   {"agent": COORD, "session": CONVERSATION, "repos_minutes": 20})
    assert endormi_a_la_fin(projet) == []
    assert machine.kills == [] and len(evenements(projet, "CoordEndormi")) == 1


def test_un_tmux_muet_n_endort_personne(projet, machine, monkeypatch):
    au_repos(projet)
    monkeypatch.setattr(fermeture, "_tmux", lambda *a: (_ for _ in ()).throw(OSError("pas de tmux")))
    assert endormi_a_la_fin(projet) == []
    assert evenements(projet, "CoordEndormi") == []


def test_un_registre_d_observation_illisible_n_endort_personne(projet, machine, monkeypatch):
    from cime.observation import registre
    au_repos(projet)
    monkeypatch.setattr(registre, "lire_registre", lambda *a, **k: (None, {"ok": False}))
    rien_ne_se_passe(projet, machine)


# --- le tour du facteur ----------------------------------------------------------------------

def test_l_etape_repos_vient_apres_les_echeances():
    assert [nom for nom, _ in facteur.ETAPES][-2:] == ["echeances", "repos"]


def test_deux_tours_de_suite_n_inscrivent_qu_un_coord_endormi(projet, machine):
    au_repos(projet)
    memoire = livraison.Memoire()
    facteur.tour(projet, dans(25), memoire)
    facteur.tour(projet, dans(26), memoire)
    assert len(evenements(projet, "CoordEndormi")) == 1 and machine.kills == [S_COORD]
    assert len(lignes(projet, "SELECT 1 FROM journal WHERE action = 'coord_endormir'")) == 1


def test_le_tour_du_facteur_endort_et_ne_signale_aucune_erreur(projet, machine):
    au_repos(projet)
    assert facteur.tour(projet, dans(25), livraison.Memoire())["erreurs"] == []
    assert machine.kills == [S_COORD]


def test_un_etat_travaille_que_seule_une_reprise_contredit_n_est_pas_un_repos(projet, machine):
    evt_a(projet, COORD, "UserPromptSubmit", dans(-60))           # tour tué en route, puis session reprise
    evt_a(projet, COORD, "SessionStart", dans(-50), source="resume")
    rien_ne_se_passe(projet, machine, minutes=0)


# --- l'état « endormi » ----------------------------------------------------------------------

def dormir(projet, agent=COORD, session=CONVERSATION):
    return evt_sans_agent(projet, "CoordEndormi", {"agent": agent, "session": session})


def test_apres_coord_endormi_l_agent_est_endormi_avec_sa_conversation(projet):
    evt(projet, COORD, "SessionStart", source="startup")
    dormir(projet)
    from cime.fondation.registre import ouvrir
    conn = ouvrir(projet)
    try:
        assert repos.endormis(conn) == {COORD: CONVERSATION}
        assert repos.episode(conn, COORD)[1] == CONVERSATION and repos.episode(conn, "coord-y") is None
    finally:
        conn.close()


@pytest.mark.parametrize("suite", ["SessionStart", "CoordReveille"])
def test_un_demarrage_de_session_ou_un_reveil_clot_l_episode(projet, suite):
    dormir(projet)
    if suite == "SessionStart":
        evt(projet, COORD, "SessionStart", source="resume")
    else:
        evt_sans_agent(projet, "CoordReveille", {"agent": COORD, "session": CONVERSATION})
    from cime.fondation.registre import ouvrir
    conn = ouvrir(projet)
    try:
        assert repos.endormis(conn) == {} and repos.episode(conn, COORD) is None
    finally:
        conn.close()


def test_un_nouveau_sommeil_apres_un_reveil_ouvre_un_nouvel_episode(projet):
    dormir(projet)
    evt_sans_agent(projet, "CoordReveille", {"agent": COORD, "session": CONVERSATION})
    evt(projet, COORD, "SessionStart", source="resume")
    dormir(projet, session="conv-suivante")
    from cime.fondation.registre import ouvrir
    conn = ouvrir(projet)
    try:
        assert repos.endormis(conn) == {COORD: "conv-suivante"}
    finally:
        conn.close()


def test_le_demarrage_d_un_autre_agent_ne_clot_pas_l_episode(projet):
    dormir(projet)
    evt(projet, "coord-y", "SessionStart", source="startup")
    from cime.fondation.registre import ouvrir
    conn = ouvrir(projet)
    try:
        assert list(repos.endormis(conn)) == [COORD]
    finally:
        conn.close()


def test_le_reveil_d_un_autre_coordinateur_ne_reveille_pas_celui_ci(projet):
    dormir(projet)
    dormir(projet, "coord-y", "conv-y")
    evt_sans_agent(projet, "CoordReveille", {"agent": "coord-y", "session": "conv-y"})
    from cime.fondation.registre import ouvrir
    conn = ouvrir(projet)
    try:
        assert repos.endormis(conn) == {COORD: CONVERSATION}
    finally:
        conn.close()


def test_sans_aucun_coordinateur_connu_tmux_n_est_pas_appele(projet):
    # le garde-fou de conftest fait échouer le test si `fermeture._tmux` est appelé
    evt(projet, ASSISTANT, "SessionStart", source="startup")
    assert repos.endormir(projet, dans(100000)) == []


def test_une_passe_ne_lit_qu_une_fois_le_registre_d_observation(projet, machine, monkeypatch):
    from cime.observation import registre
    lectures = []
    vraie = registre.lire_registre
    monkeypatch.setattr(registre, "lire_registre", lambda *a, **k: lectures.append(1) or vraie(*a, **k))
    au_repos(projet)
    assert endormi_a_la_fin(projet) == [COORD]
    assert len(lectures) == 1
