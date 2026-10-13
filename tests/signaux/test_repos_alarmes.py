"""Les alarmes se taisent pour un coordinateur endormi, et seulement pour lui : `session-absente` (un
message attend une session absente), `session-disparue` (la session a disparu sans fin déclarée, par le
facteur et par le hook de fin de session). Un coordinateur mort sans sommeil donne toujours les alarmes ;
un réveil raté rend la parole à `session-absente`."""
import pytest

from aide import lignes
from aide_repos import (
    ASSISTANT, CONVERSATION, COORD, S_COORD, au_repos, dans, dormir_pour_de_bon,
    evenements, evt, evt_sans_agent, machine, obligation_seule, ordres_poses, poster,  # noqa: F401
    projet,  # noqa: F401
)
from cime.fondation.registre import ouvrir
from cime.signaux import hooks, livraison


def livrer(projet, decalage=25):
    livraison.livrer_tout(projet, dans(decalage), livraison.Memoire())


def signalements(projet, debut):
    return lignes(projet, "SELECT a, objet FROM messages WHERE de = 'cime' AND nature = 'signalement'"
                  " AND objet LIKE ? ORDER BY id", (debut + "%",))


def absente(projet):
    return signalements(projet, "session-absente")


def disparue(projet):
    return signalements(projet, "session-disparue")


def diagnostics(projet, agent=COORD):
    """Raisons des `LivraisonDifferee` notées pour `agent`."""
    return [r for (r,) in lignes(
        projet, "SELECT json_extract(details, '$.raison') FROM evenements"
        " WHERE evenement = 'LivraisonDifferee' AND agent = ? ORDER BY id", (agent,))]


def marquer_ordres(projet, etat):
    conn = ouvrir(projet)
    with conn:
        conn.execute("UPDATE ordres SET etat = ?, resultat = '{}'", (etat,))
    conn.close()


# --- session-absente --------------------------------------------------------------------------

def test_un_coordinateur_absent_sans_sommeil_donne_toujours_l_alarme(projet, machine):
    evt(projet, COORD, "Stop")                  # sans `SessionStart` : ni endormi ni tombé
    del machine.sessions[S_COORD]
    poster(projet, ASSISTANT, COORD)
    livrer(projet)
    assert absente(projet) == [(ASSISTANT, f"session-absente:{COORD}")]


def test_un_endormi_dont_le_message_attend_ne_donne_pas_l_alarme(projet, machine):
    dormir_pour_de_bon(projet, machine)
    poster(projet, ASSISTANT, COORD)
    livrer(projet)
    livrer(projet, decalage=600)
    assert absente(projet) == [] and len(ordres_poses(projet)) == 1
    assert diagnostics(projet) == []                      # il dort : aucune « session absente » à noter


def test_le_sommeil_d_un_coordinateur_ne_tait_pas_l_alarme_d_un_autre(projet, machine):
    dormir_pour_de_bon(projet, machine)
    poster(projet, ASSISTANT, COORD)
    poster(projet, ASSISTANT, "coord-y")
    livrer(projet)
    assert absente(projet) == [(ASSISTANT, "session-absente:coord-y")]


@pytest.mark.parametrize("etat", ["echec", "refuse"])
def test_un_reveil_rate_rend_la_parole_a_l_alarme(projet, machine, etat):
    dormir_pour_de_bon(projet, machine)
    poster(projet, ASSISTANT, COORD)
    livrer(projet)
    assert absente(projet) == [] and diagnostics(projet) == []
    marquer_ordres(projet, etat)
    livrer(projet, decalage=30)
    assert absente(projet) == [(ASSISTANT, f"session-absente:{COORD}")]
    assert diagnostics(projet) == ["session-absente"]
    assert len(ordres_poses(projet)) == 1                  # et aucun nouvel ordre


def test_apres_un_reveil_reussi_la_session_qui_disparait_donne_l_alarme(projet, machine):
    dormir_pour_de_bon(projet, machine)
    evt_sans_agent(projet, "CoordReveille", {"agent": COORD, "session": CONVERSATION})
    poster(projet, ASSISTANT, COORD)
    livrer(projet)
    assert absente(projet) == [(ASSISTANT, f"session-absente:{COORD}")] and ordres_poses(projet) == []
    assert diagnostics(projet) == ["session-absente"]


def test_une_session_relancee_par_ailleurs_puis_disparue_donne_l_alarme(projet, machine):
    dormir_pour_de_bon(projet, machine)
    evt(projet, COORD, "SessionStart", "conv-x-2", source="resume")
    evt(projet, COORD, "SessionEnd", "conv-x-2", reason="prompt_input_exit")     # sorti volontairement
    poster(projet, ASSISTANT, COORD)
    livrer(projet)
    assert absente(projet) == [(ASSISTANT, f"session-absente:{COORD}")]


def test_le_sommeil_du_coordinateur_ne_tait_pas_l_alarme_de_son_worker_absent(projet, machine):
    dormir_pour_de_bon(projet, machine)
    poster(projet, COORD, "worker-x-t")                  # son worker n'a pas de session
    livrer(projet)
    assert absente(projet) == [(ASSISTANT, "session-absente:worker-x-t")]


# --- session-disparue (le facteur) ----------------------------------------------------------------------

def test_un_coordinateur_disparu_sans_sommeil_donne_toujours_l_alarme(projet, machine):
    au_repos(projet)
    del machine.sessions[S_COORD]
    livrer(projet)
    assert disparue(projet) == [(ASSISTANT, f"session-disparue:{COORD}")]


def test_un_endormi_n_est_pas_un_disparu(projet, machine):
    dormir_pour_de_bon(projet, machine)
    livrer(projet)
    assert disparue(projet) == []


def test_un_reveil_rate_ne_fait_pas_d_un_endormi_un_disparu(projet, machine):
    dormir_pour_de_bon(projet, machine)
    poster(projet, ASSISTANT, COORD)
    livrer(projet)
    marquer_ordres(projet, "refuse")
    livrer(projet, decalage=30)
    assert disparue(projet) == []


def test_le_sommeil_d_un_autre_ne_tait_pas_la_disparition(projet, machine):
    evt(projet, COORD, "SessionStart", source="startup")
    evt_sans_agent(projet, "CoordEndormi", {"agent": "coord-y", "session": "conv-y"})
    del machine.sessions[S_COORD]
    livrer(projet)
    assert disparue(projet) == [(ASSISTANT, f"session-disparue:{COORD}")]


def test_une_session_demarree_apres_le_sommeil_puis_disparue_donne_l_alarme(projet, machine):
    dormir_pour_de_bon(projet, machine)
    evt(projet, COORD, "SessionStart", "conv-x-2", source="resume")      # réveillé…
    livrer(projet)
    assert disparue(projet) == [(ASSISTANT, f"session-disparue:{COORD}")]   # …et sa session manque


# --- session-disparue (le hook de fin de session) -------------------------------------------------------

def fin_de_session(projet, agent=COORD, raison="other"):
    conn = ouvrir(projet)
    try:
        hooks.sur_session_end(conn, projet, agent, {"reason": raison})
    finally:
        conn.close()


def test_la_fermeture_d_un_endormi_ne_signale_rien(projet, machine):
    dormir_pour_de_bon(projet, machine)
    fin_de_session(projet)
    assert disparue(projet) == []


def test_la_fin_d_un_coordinateur_avec_une_obligation_ouverte_sans_sommeil_signale_toujours(projet, machine):
    au_repos(projet)
    obligation_seule(projet, COORD)
    fin_de_session(projet)
    assert disparue(projet) == [(ASSISTANT, f"session-disparue:{COORD}")]
