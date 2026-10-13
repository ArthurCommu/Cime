"""Un message pour un coordinateur endormi le réveille : le facteur pose un ordre `lancer … reveil`, une
seule fois par sommeil ; l'exécuter inscrit `CoordReveille`, sans consigne d'ouverture ; le message est livré
ensuite par le chemin normal."""
import pytest

from aide import lignes
from aide_repos import (
    ASSISTANT, CONVERSATION, COORD, S_COORD, accuser_reception, ajouter_session, au_repos,
    courrier_ouvert, dans, dormir_pour_de_bon,
    evenements, evt, machine, ordres_poses, poster, projet, transition,  # noqa: F401
)
from cime.fondation import lancer
from cime.fondation.registre import ouvrir
from cime.signaux import facteur, livraison, ordres, repos

PARAMETRES = {"role": "coord", "equipe": "x", "reprendre": True, "session": CONVERSATION,
              "reveil": True, "modele": None}


@pytest.fixture
def lancements(machine, monkeypatch):
    """Remplace le lancement réel : il note ses arguments et recrée la session, comme le vrai ; aucun
    processus claude ne survit à la fermeture. `echec` et `refus` font échouer le lancement."""
    etat = {"args": [], "issue": None, "sondes": []}    # `sondes` : réponses successives de la sonde de processus

    def faux(args, projet_=None):
        etat["args"].append(args)
        if etat["issue"] == "refus":
            raise lancer.Refus("conversation introuvable")
        if etat["issue"] == "echec":
            return S_COORD, 1
        ajouter_session(machine, S_COORD)
        return S_COORD, etat["issue"] or 0

    monkeypatch.setattr(ordres, "_lancer", faux)
    monkeypatch.setattr(lancer, "processus_claude_dans",
                        lambda d: etat["sondes"].pop(0) if etat["sondes"] else [])
    monkeypatch.setattr(ordres, "_dormir", lambda s: None)
    return etat


def livrer(projet, decalage=25):
    livraison.livrer_tout(projet, dans(decalage), livraison.Memoire())


def tour(projet, memoire=None, decalage=25):
    return facteur.tour(projet, dans(decalage), memoire or livraison.Memoire())


def consignes_d_ouverture(projet):
    return lignes(projet, "SELECT id FROM messages WHERE objet = 'ouverture'")


# --- l'ordre de réveil ------------------------------------------------------------------------

def test_un_message_pour_un_endormi_pose_un_seul_ordre_lancer_complet(projet, machine, lancements):
    dormir_pour_de_bon(projet, machine)
    poster(projet, ASSISTANT, COORD)
    livrer(projet)
    assert ordres_poses(projet) == [("cime", "lancer", COORD, PARAMETRES, "en_file")]


def test_pas_de_second_ordre_tant_que_le_premier_est_en_file(projet, machine, lancements):
    dormir_pour_de_bon(projet, machine)
    poster(projet, ASSISTANT, COORD)
    memoire = livraison.Memoire()
    for _ in range(3):
        livraison.livrer_tout(projet, dans(25), memoire)
    assert len(ordres_poses(projet)) == 1


def test_un_lancement_de_cette_cible_deja_en_file_suffit_aucun_ordre_de_plus(projet, machine, lancements):
    dormir_pour_de_bon(projet, machine)
    poster(projet, ASSISTANT, COORD)
    ordres.demander(projet, "assistant", "lancer", COORD,
                    {"role": "coord", "equipe": "x", "reprendre": True, "session": CONVERSATION,
                     "modele": None})
    livrer(projet)
    assert [e for *_, e in ordres_poses(projet)] == ["en_file"]


def test_le_lancement_en_file_d_une_autre_cible_ne_compte_pas(projet, machine, lancements):
    dormir_pour_de_bon(projet, machine)
    poster(projet, ASSISTANT, COORD)
    ordres.demander(projet, "assistant", "lancer", "coord-y", {"role": "coord", "equipe": "y"})
    livrer(projet)
    assert [c for _, _, c, *_ in ordres_poses(projet)] == ["coord-y", COORD]


@pytest.mark.parametrize("etat", ["echec", "refuse", "execute"])
def test_l_issue_d_un_lancement_ordinaire_ne_compte_pas_comme_un_reveil(projet, machine, lancements, etat):
    dormir_pour_de_bon(projet, machine)
    poster(projet, ASSISTANT, COORD)
    ordres.demander(projet, "assistant", "lancer", COORD, {"role": "coord", "equipe": "x"})
    conn = ouvrir(projet)
    with conn:
        conn.execute("UPDATE ordres SET etat = ?, resultat = '{}'", (etat,))
    conn.close()
    livrer(projet)
    assert [(a, e) for a, _, _, _, e in ordres_poses(projet)] == [("assistant", etat), ("cime", "en_file")]


def test_un_ordre_de_reveil_pris_et_sans_resultat_n_est_pas_double(projet, machine, lancements):
    dormir_pour_de_bon(projet, machine)
    poster(projet, ASSISTANT, COORD)
    livrer(projet)
    conn = ouvrir(projet)
    with conn:
        conn.execute("UPDATE ordres SET etat = 'execute'")
    conn.close()
    livrer(projet)
    assert [e for *_, e in ordres_poses(projet)] == ["execute"]


def test_un_courrier_reste_ouvert_sans_message_en_attente_ne_reveille_pas(projet, machine, lancements):
    dormir_pour_de_bon(projet, machine)
    courrier_ouvert(projet, COORD)
    livrer(projet)
    assert ordres_poses(projet) == []


def test_sans_message_en_attente_aucun_ordre(projet, machine, lancements):
    dormir_pour_de_bon(projet, machine)
    livrer(projet)
    assert ordres_poses(projet) == []


def test_un_message_pour_un_coordinateur_absent_qui_n_est_pas_endormi_ne_pose_aucun_ordre(
        projet, machine, lancements):
    del machine.sessions[S_COORD]
    poster(projet, ASSISTANT, COORD)
    livrer(projet)
    assert ordres_poses(projet) == []


def test_un_message_pour_un_coordinateur_vivant_ne_pose_aucun_ordre(projet, machine, lancements):
    au_repos(projet)
    poster(projet, ASSISTANT, COORD)
    livrer(projet)
    assert ordres_poses(projet) == []


def test_la_conversation_de_l_ordre_est_celle_du_sommeil_pas_la_plus_recente(projet, machine, lancements):
    dormir_pour_de_bon(projet, machine)
    evt(projet, COORD, "Stop", "autre-conversation")        # un événement tardif d'une autre session
    poster(projet, ASSISTANT, COORD)
    livrer(projet)
    assert ordres_poses(projet)[0][3]["session"] == CONVERSATION


def test_le_lancement_d_un_coordinateur_n_est_jamais_retenu_par_le_plafond(projet, machine, lancements):
    ajouter_session(machine, "essai-worker-y-z")                # plafond de 1 atteint
    dormir_pour_de_bon(projet, machine)
    poster(projet, ASSISTANT, COORD)
    tour(projet)
    tour(projet)
    assert [e for *_, e in ordres_poses(projet)] == ["execute"]


# --- l'exécution -----------------------------------------------------------------------------

def test_l_execution_reprend_la_conversation_du_sommeil_avec_le_modele_du_manifeste(
        projet, machine, lancements):
    dormir_pour_de_bon(projet, machine)
    poster(projet, ASSISTANT, COORD)
    tour(projet)
    tour(projet)
    (args,) = lancements["args"]
    assert (args.role, args.equipe, args.reprendre, args.session, args.modele) \
        == ("coord", "x", True, CONVERSATION, None)
    assert [e for *_, e in ordres_poses(projet)] == ["execute"]


def test_l_execution_inscrit_coord_reveille_sans_agent_ni_session(projet, machine, lancements):
    dormir_pour_de_bon(projet, machine)
    poster(projet, ASSISTANT, COORD)
    tour(projet)
    tour(projet)
    (_, agent, session, details), = evenements(projet, "CoordReveille")
    assert agent is None and session is None
    assert details == {"auteur": "cime", "agent": COORD, "session": CONVERSATION, "par_ordre": 1}
    assert lignes(projet, "SELECT auteur, action, resultat FROM journal WHERE action = 'coord_reveiller'") \
        == [("cime", "coord_reveiller", "ok")]


def test_l_execution_n_envoie_pas_la_consigne_d_ouverture(projet, machine, lancements):
    dormir_pour_de_bon(projet, machine)
    poster(projet, ASSISTANT, COORD)
    tour(projet)
    tour(projet)
    assert consignes_d_ouverture(projet) == []


def test_un_lancement_ordinaire_de_coordinateur_envoie_toujours_la_consigne_d_ouverture(
        projet, machine, lancements):
    ordres.demander(projet, "assistant", "lancer", COORD,
                    {"role": "coord", "equipe": "x", "reprendre": True, "session": CONVERSATION,
                     "modele": None})
    ordres.facteur_une_fois(projet)
    assert len(consignes_d_ouverture(projet)) == 1 and evenements(projet, "CoordReveille") == []


def test_le_message_est_livre_ensuite_par_le_chemin_normal(projet, machine, lancements):
    dormir_pour_de_bon(projet, machine)
    message = poster(projet, ASSISTANT, COORD, resume="va voir x")
    tour(projet)
    tour(projet)
    assert [session for session, _ in machine.entrees] == [S_COORD]
    assert "va voir x" in machine.entrees[0][1]
    assert lignes(projet, "SELECT etat FROM transitions WHERE message_id = ? ORDER BY id", (message,)) \
        [-1] == ("livre",)


def test_le_reveil_attend_la_fin_du_processus_claude_de_l_ancienne_session(
        projet, machine, lancements, monkeypatch):
    pauses = []
    monkeypatch.setattr(ordres, "_dormir", pauses.append)
    lancements["sondes"] = [[4242], [4242]]                # encore là deux fois, puis parti
    dormir_pour_de_bon(projet, machine)
    poster(projet, ASSISTANT, COORD)
    tour(projet)
    tour(projet)
    assert len(pauses) == 2 and len(lancements["args"]) == 1
    assert [e for *_, e in ordres_poses(projet)] == ["execute"]


def test_un_lancement_ordinaire_ne_sonde_pas_les_processus(projet, machine, lancements, monkeypatch):
    def interdit(dossier):
        raise AssertionError("sonde des processus appelée")
    monkeypatch.setattr(lancer, "processus_claude_dans", interdit)
    ordres.demander(projet, "assistant", "lancer", COORD,
                    {"role": "coord", "equipe": "x", "reprendre": True, "session": CONVERSATION,
                     "modele": None})
    ordres.facteur_une_fois(projet)
    assert [e for *_, e in ordres_poses(projet)] == ["execute"]


def test_un_reveil_qui_aboutit_a_un_ecran_de_confiance_est_note_et_signale(projet, machine, lancements):
    lancements["issue"] = ordres.CODE_APPROBATION
    dormir_pour_de_bon(projet, machine)
    poster(projet, ASSISTANT, COORD)
    tour(projet)
    tour(projet)
    assert len(evenements(projet, "CoordReveille")) == 1
    assert lignes(projet, "SELECT a FROM messages WHERE objet = ?", (f"approbation:{S_COORD}",)) \
        == [("assistant",)]


# --- un seul réveil par sommeil -----------------------------------------------------------------

def test_apres_un_reveil_reussi_aucun_nouvel_ordre_meme_si_la_session_disparait(projet, machine, lancements):
    dormir_pour_de_bon(projet, machine)
    poster(projet, ASSISTANT, COORD)
    tour(projet)
    tour(projet)
    del machine.sessions[S_COORD]                       # le coordinateur réveillé s'est ensuite écroulé
    poster(projet, ASSISTANT, COORD, resume="encore")
    tour(projet)
    tour(projet)
    assert len(ordres_poses(projet)) == 1


def test_un_nouveau_sommeil_puis_un_nouveau_message_arment_un_nouveau_reveil(projet, machine, lancements):
    dormir_pour_de_bon(projet, machine)
    premier = poster(projet, ASSISTANT, COORD)
    tour(projet)
    tour(projet)
    assert len(ordres_poses(projet)) == 1
    evt(projet, COORD, "SessionStart", "conv-x-2", source="resume")      # la session réveillée démarre
    evt(projet, COORD, "Stop", "conv-x-2")
    transition(projet, premier, "clos")
    accuser_reception(projet)
    assert repos.endormir(projet, dans(60)) == [COORD]
    poster(projet, ASSISTANT, COORD, resume="deuxième")
    tour(projet, decalage=60)
    assert [(e, p["session"]) for *_, p, e in ordres_poses(projet)] \
        == [("execute", CONVERSATION), ("en_file", "conv-x-2")]


def test_un_demarrage_de_session_apres_le_sommeil_clot_l_episode_aucun_ordre(projet, machine, lancements):
    dormir_pour_de_bon(projet, machine)
    evt(projet, COORD, "SessionStart", "conv-x-2", source="resume")      # relancé par ailleurs
    evt(projet, COORD, "SessionEnd", "conv-x-2", reason="prompt_input_exit")     # puis sorti volontairement
    poster(projet, ASSISTANT, COORD)
    livrer(projet)
    assert ordres_poses(projet) == []


# --- le réveil qui échoue ---------------------------------------------------------------------

@pytest.mark.parametrize("issue,etat", [("refus", "refuse"), ("echec", "echec")])
def test_un_reveil_echoue_n_est_pas_repose_en_boucle(projet, machine, lancements, issue, etat):
    lancements["issue"] = issue
    dormir_pour_de_bon(projet, machine)
    poster(projet, ASSISTANT, COORD)
    memoire = livraison.Memoire()
    for _ in range(4):
        facteur.tour(projet, dans(25), memoire)
    assert [e for *_, e in ordres_poses(projet)] == [etat]
    assert evenements(projet, "CoordReveille") == []


def test_un_reveil_echoue_d_un_sommeil_precedent_ne_bloque_pas_le_suivant(projet, machine, lancements):
    lancements["issue"] = "refus"
    dormir_pour_de_bon(projet, machine)
    poster(projet, ASSISTANT, COORD)
    tour(projet)
    tour(projet)
    assert [e for *_, e in ordres_poses(projet)] == ["refuse"]
    evt(projet, COORD, "SessionStart", "conv-x-2", source="resume")      # relancé à la main
    evt(projet, COORD, "Stop", "conv-x-2")
    ajouter_session(machine, S_COORD)
    for (identifiant,) in lignes(projet, "SELECT id FROM messages"):    # sans message en attente...
        transition(projet, identifiant, "clos")
    assert repos.endormir(projet, dans(60)) == [COORD]                  # ... il se rendort
    lancements["issue"] = None
    poster(projet, ASSISTANT, COORD, resume="suite")
    tour(projet, decalage=60)
    assert [e for *_, e in ordres_poses(projet)] == ["refuse", "en_file"]
