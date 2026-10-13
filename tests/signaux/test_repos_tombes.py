"""Un coordinateur tombé (sa session a disparu sans que personne l'ait voulu, au redémarrage de la machine)
est réveillé comme un endormi : au premier message qui l'attend, le facteur pose un seul ordre `lancer …
reveil`. Son absence n'est pas une alarme `session-absente` tant que ce réveil n'a pas échoué ; la
disparition, elle, reste signalée."""
import pytest

from aide import lignes
from aide_repos import (
    ASSISTANT, CONVERSATION, COORD, S_COORD, WORKER, ajouter_session, au_repos, dans,
    dormir_pour_de_bon, evenements, evt, evt_sans_agent, machine, ordres_poses, poster,  # noqa: F401
    projet, transition,  # noqa: F401
)
from cime.fondation import fermeture, lancer
from cime.fondation.registre import ouvrir
from cime.signaux import facteur, livraison, ordres, repos

PARAMETRES = {"role": "coord", "equipe": "x", "reprendre": True, "session": CONVERSATION,
              "reveil": True, "modele": None}


@pytest.fixture
def lancements(machine, monkeypatch):
    """Remplace le lancement réel : il note ses arguments et recrée la session ; `issue` le fait échouer."""
    etat = {"args": [], "issue": None}

    def faux(args, projet_=None):
        etat["args"].append(args)
        if etat["issue"] == "refus":
            raise lancer.Refus("conversation introuvable")
        if etat["issue"] == "echec":
            return S_COORD, 1
        ajouter_session(machine, S_COORD)
        return S_COORD, 0

    monkeypatch.setattr(ordres, "_lancer", faux)
    monkeypatch.setattr(lancer, "processus_claude_dans", lambda d: [])
    monkeypatch.setattr(ordres, "_dormir", lambda s: None)
    return etat


def livrer(projet, decalage=25):
    livraison.livrer_tout(projet, dans(decalage), livraison.Memoire())


def tour(projet, memoire=None, decalage=25):
    return facteur.tour(projet, dans(decalage), memoire or livraison.Memoire())


def tomber(projet, machine, conversation=CONVERSATION):
    """Le coordinateur a vécu une session, puis la machine a redémarré : plus de session tmux, aucun
    `SessionEnd`, aucun `CoordEndormi`."""
    au_repos(projet, session_id=conversation)
    del machine.sessions[S_COORD]


def signalements(projet, debut):
    return lignes(projet, "SELECT a, objet FROM messages WHERE de = 'cime' AND nature = 'signalement'"
                  " AND objet LIKE ? ORDER BY id", (debut + "%",))


def marquer_ordres(projet, etat):
    conn = ouvrir(projet)
    with conn:
        conn.execute("UPDATE ordres SET etat = ?, resultat = '{}'", (etat,))
    conn.close()


def ordre_pose(projet, verbe, auteur="assistant", etat="execute", **parametres):
    ordres.demander(projet, auteur, verbe, COORD, {"role": "coord", "equipe": "x", **parametres})
    marquer_ordres(projet, etat)


# --- le réveil ------------------------------------------------------------------------------------

def test_un_message_pour_un_tombe_pose_un_seul_ordre_lancer_complet(projet, machine, lancements):
    tomber(projet, machine)
    poster(projet, ASSISTANT, COORD)
    livrer(projet)
    assert ordres_poses(projet) == [("cime", "lancer", COORD, PARAMETRES, "en_file")]


def test_la_conversation_de_l_ordre_est_la_derniere_connue(projet, machine, lancements):
    tomber(projet, machine)
    evt(projet, COORD, "Stop", "conv-x-9")
    poster(projet, ASSISTANT, COORD)
    livrer(projet)
    assert ordres_poses(projet)[0][3]["session"] == "conv-x-9"


def test_pas_de_second_ordre_tant_que_le_premier_est_en_file(projet, machine, lancements):
    tomber(projet, machine)
    poster(projet, ASSISTANT, COORD)
    memoire = livraison.Memoire()
    for _ in range(3):
        livraison.livrer_tout(projet, dans(25), memoire)
    assert len(ordres_poses(projet)) == 1


def test_l_execution_inscrit_coord_reveille_sans_consigne_d_ouverture_et_livre_le_message(
        projet, machine, lancements):
    tomber(projet, machine)
    message = poster(projet, ASSISTANT, COORD, resume="va voir x")
    tour(projet)
    tour(projet)
    (_, agent, session, details), = evenements(projet, "CoordReveille")
    assert agent is None and session is None
    assert details == {"auteur": "cime", "agent": COORD, "session": CONVERSATION, "par_ordre": 1}
    assert lignes(projet, "SELECT id FROM messages WHERE objet = 'ouverture'") == []
    assert [session for session, _ in machine.entrees] == [S_COORD]
    assert lignes(projet, "SELECT etat FROM transitions WHERE message_id = ? ORDER BY id", (message,)) \
        [-1] == ("livre",)


def test_une_session_nouvelle_clot_l_episode_une_nouvelle_chute_arme_un_nouveau_reveil(
        projet, machine, lancements):
    tomber(projet, machine)
    poster(projet, ASSISTANT, COORD)
    tour(projet)
    tour(projet)
    assert [e for *_, e in ordres_poses(projet)] == ["execute"]
    evt(projet, COORD, "SessionStart", "conv-x-2", source="resume")      # la session réveillée démarre
    evt(projet, COORD, "Stop", "conv-x-2")
    del machine.sessions[S_COORD]                                        # nouvelle chute
    poster(projet, ASSISTANT, COORD, resume="encore")
    tour(projet)
    assert [(e, p["session"]) for *_, p, e in ordres_poses(projet)] \
        == [("execute", CONVERSATION), ("en_file", "conv-x-2")]


def test_apres_un_reveil_reussi_sans_nouvelle_session_aucun_second_ordre(projet, machine, lancements):
    tomber(projet, machine)
    poster(projet, ASSISTANT, COORD)
    tour(projet)
    tour(projet)
    del machine.sessions[S_COORD]                       # il retombe avant d'avoir dit quoi que ce soit
    poster(projet, ASSISTANT, COORD, resume="encore")
    tour(projet)
    tour(projet)
    assert len(ordres_poses(projet)) == 1


# --- ce qui empêche de le réveiller ------------------------------------------------------------------

def _aucun_ordre(projet):
    poster(projet, ASSISTANT, COORD)
    livrer(projet)
    assert [o for o in ordres_poses(projet) if o[0] == "cime"] == []     # (l'ordre posé par le test ne compte pas)


def test_une_session_vivante_n_est_pas_tombee(projet, machine, lancements):
    au_repos(projet)
    _aucun_ordre(projet)


def test_sans_conversation_connue_pas_de_reveil(projet, machine, lancements):
    evt(projet, COORD, "SessionStart", None, source="startup")
    evt(projet, COORD, "Stop", None)
    del machine.sessions[S_COORD]
    _aucun_ordre(projet)


def test_sans_session_start_pas_de_reveil(projet, machine, lancements):
    evt(projet, COORD, "Stop")
    del machine.sessions[S_COORD]
    _aucun_ordre(projet)


def test_un_ordre_fermer_depuis_le_demarrage_n_est_pas_une_chute(projet, machine, lancements):
    tomber(projet, machine)
    ordre_pose(projet, "fermer")
    _aucun_ordre(projet)


def test_un_lancement_remplacer_depuis_le_demarrage_n_est_pas_une_chute(projet, machine, lancements):
    tomber(projet, machine)
    ordre_pose(projet, "lancer", remplacer=True)
    _aucun_ordre(projet)


def test_un_projet_ferme_n_est_pas_reveille(projet, machine, lancements):
    tomber(projet, machine)
    fermeture.chemin_repere(projet).write_text("{}")
    _aucun_ordre(projet)


def test_un_projet_ferme_apres_le_demarrage_n_est_pas_une_chute(projet, machine, lancements):
    tomber(projet, machine)
    evt_sans_agent(projet, "ProjetFerme")
    _aucun_ordre(projet)


def test_une_equipe_cloturee_n_est_pas_reveillee(projet, machine, lancements):
    tomber(projet, machine)
    (projet / ".orga" / "teams" / "x" / "CLOTUREE").write_text("")
    _aucun_ordre(projet)


def test_l_assistant_tombe_n_est_pas_reveille(projet, machine, lancements):
    au_repos(projet, agent=ASSISTANT)
    del machine.sessions["essai-assistant"]
    poster(projet, COORD, ASSISTANT)
    livrer(projet)
    assert ordres_poses(projet) == []


def test_sans_message_en_attente_aucun_ordre(projet, machine, lancements):
    tomber(projet, machine)
    livrer(projet)
    assert ordres_poses(projet) == []


@pytest.mark.parametrize("auteur", ["assistant", "cime"])
def test_un_lancement_deja_en_file_suffit_quel_qu_en_soit_l_auteur(projet, machine, lancements, auteur):
    tomber(projet, machine)
    poster(projet, ASSISTANT, COORD)
    ordre_pose(projet, "lancer", auteur=auteur, etat="en_file", reprendre=True, session=CONVERSATION)
    livrer(projet)
    assert [(a, e) for a, _, _, _, e in ordres_poses(projet)] == [(auteur, "en_file")]


def test_un_endormi_n_est_pas_un_tombe(projet, machine, lancements):
    """Le chemin de l'endormi reste le sien : un seul ordre, sur la conversation du sommeil."""
    dormir_pour_de_bon(projet, machine)
    assert repos.tombe(projet, ouvrir(projet), COORD) is None


# --- la fin déclarée ---------------------------------------------------------------------------------

@pytest.mark.parametrize("raison", ["prompt_input_exit", "logout"])
def test_une_sortie_volontaire_n_est_pas_une_chute(projet, machine, lancements, raison):
    tomber(projet, machine)
    evt(projet, COORD, "SessionEnd", reason=raison)
    _aucun_ordre(projet)


@pytest.mark.parametrize("raison", ["other", "clear", "resume", "bypass_permissions_disabled", None])
def test_toute_autre_fin_declaree_est_une_chute(projet, machine, lancements, raison):
    tomber(projet, machine)
    evt(projet, COORD, "SessionEnd", **({} if raison is None else {"reason": raison}))
    poster(projet, ASSISTANT, COORD)
    livrer(projet)
    assert [e for *_, e in ordres_poses(projet)] == ["en_file"]


def test_une_fin_volontaire_d_une_session_precedente_ne_compte_pas(projet, machine, lancements):
    evt(projet, COORD, "SessionStart", "conv-x-0", source="startup")
    evt(projet, COORD, "SessionEnd", "conv-x-0", reason="prompt_input_exit")
    tomber(projet, machine)
    poster(projet, ASSISTANT, COORD)
    livrer(projet)
    assert [e for *_, e in ordres_poses(projet)] == ["en_file"]


# --- le réveil qui échoue ---------------------------------------------------------------------------

@pytest.mark.parametrize("issue,etat", [("refus", "refuse"), ("echec", "echec")])
def test_un_reveil_echoue_n_est_pas_repose_en_boucle_et_l_alarme_reprend(
        projet, machine, lancements, issue, etat):
    lancements["issue"] = issue
    tomber(projet, machine)
    poster(projet, ASSISTANT, COORD)
    memoire = livraison.Memoire()
    for _ in range(4):
        facteur.tour(projet, dans(25), memoire)
    assert [e for *_, e in ordres_poses(projet)] == [etat]
    assert evenements(projet, "CoordReveille") == []
    assert signalements(projet, "session-absente") == [(ASSISTANT, f"session-absente:{COORD}")]


def test_un_reveil_echoue_d_une_chute_precedente_ne_bloque_pas_la_suivante(projet, machine, lancements):
    lancements["issue"] = "refus"
    tomber(projet, machine)
    poster(projet, ASSISTANT, COORD)
    tour(projet)
    tour(projet)
    assert [e for *_, e in ordres_poses(projet)] == ["refuse"]
    evt(projet, COORD, "SessionStart", "conv-x-2", source="resume")      # relancé à la main
    evt(projet, COORD, "Stop", "conv-x-2")
    lancements["issue"] = None
    tour(projet)
    assert [e for *_, e in ordres_poses(projet)] == ["refuse", "en_file"]


# --- les alarmes ---------------------------------------------------------------------------------------

def test_pas_de_session_absente_pendant_que_le_reveil_est_attendu(projet, machine, lancements):
    tomber(projet, machine)
    poster(projet, ASSISTANT, COORD)
    livrer(projet)
    assert signalements(projet, "session-absente") == []


def test_la_session_disparue_sonne_toujours_pour_un_tombe(projet, machine, lancements):
    tomber(projet, machine)
    poster(projet, ASSISTANT, COORD)
    livrer(projet)
    assert signalements(projet, "session-disparue") == [(ASSISTANT, f"session-disparue:{COORD}")]


def test_une_absence_non_attendue_donne_toujours_l_alarme(projet, machine, lancements):
    """Une session sans `SessionStart` : ni endormi ni tombé, l'alarme sonne comme avant."""
    evt(projet, COORD, "Stop")
    del machine.sessions[S_COORD]
    poster(projet, ASSISTANT, COORD)
    livrer(projet)
    assert signalements(projet, "session-absente") == [(ASSISTANT, f"session-absente:{COORD}")]
    assert ordres_poses(projet) == []


def test_un_worker_absent_donne_session_absente_jamais_un_reveil(projet, machine, lancements):
    au_repos(projet, agent=WORKER)
    poster(projet, ASSISTANT, WORKER)
    livrer(projet)
    assert signalements(projet, "session-absente") == [(ASSISTANT, f"session-absente:{WORKER}")]
    assert ordres_poses(projet) == []


def test_un_tombe_n_est_pas_un_endormi(projet, machine, lancements):
    tomber(projet, machine)
    assert repos.endormis(ouvrir(projet)) == {}
