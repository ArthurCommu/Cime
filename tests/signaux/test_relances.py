"""Le moteur des échéances, relances et escalades, horloge simulée."""
from datetime import datetime, timedelta, timezone

import pytest

from aide import fabriquer_projet, lignes
from cime.fondation.nom import VAR_PROJET
from cime.fondation.registre import inscrire_evenement, ouvrir
from cime.signaux import commandes, echeances, facteur, hooks, livraison, obligations, relances
from cime.signaux.echeances import Etape

COORD, WORKER, ASSISTANT = "coord-x", "worker-x-t", "assistant"
MIN = timedelta(minutes=1)


@pytest.fixture
def projet(tmp_path, monkeypatch):
    racine = fabriquer_projet(tmp_path / "depot")
    monkeypatch.setenv(VAR_PROJET, str(racine))
    return racine


def poster(projet, de, a, nature="consigne", resume="r", attend="rien", objet=None):
    conn = ouvrir(projet)
    try:
        return commandes.inscrire(conn, de=de, a=a, nature=nature, resume=resume, attend=attend,
                                  objet=objet, equipe="x")
    finally:
        conn.close()


def signaler(projet, a, objet):
    return poster(projet, "cime", a, nature="signalement", resume="signal", objet=objet)


def evt(projet, agent, nom):
    conn = ouvrir(projet)
    try:
        return inscrire_evenement(conn, agent=agent, session_id="s", evenement=nom, details={})
    finally:
        conn.close()


def t0():
    return datetime.now(timezone.utc)


def passer(projet, instant):
    return relances.executer(projet, instant)


def envoyes(projet, objet_debut=""):
    """(a, nature, objet) des messages de Cime, dans l'ordre."""
    return lignes(projet, "SELECT a, nature, objet FROM messages WHERE de = 'cime' AND objet "
                  "LIKE ? ORDER BY id", (objet_debut + "%",))


def rang(projet, message_id):
    return lignes(projet, "SELECT relances, etat FROM obligations WHERE message_id = ?",
                  (message_id,))[0]


def cumul(type_):
    total, sortie = timedelta(0), []
    for etape in echeances.ECHELLES[type_]:
        total += etape.delai
        sortie.append(int(total.total_seconds() // 60))
    return sortie


# --- la table des échéances ---------------------------------------------------------

def test_la_table_reprend_les_delais_attendus():
    assert cumul("question") == [15, 30, 60]
    assert cumul("demande_accord") == [10, 20]
    assert cumul("travail_pret_coord") == [30, 60]
    assert cumul("travail_pret_assistant") == [60, 120]
    assert cumul("demande_cloture") == [60, 120]
    assert cumul("autorisation") == [0, 2, 10]
    assert cumul("attente_utilisateur") == [0, 120]
    assert cumul("signalement_grave") == [0, 10, 30]
    assert cumul("suites_fusion") == [0, 10, 30]
    assert cumul("contexte") == [0, 10, 30]
    assert cumul("signalement_info") == [0]
    assert [int(e.delai.total_seconds() // 60) for e in echeances.ECHELLE_DETTE_AU_REPOS] == [5, 10, 15]


def test_delai_vient_de_la_table(monkeypatch):
    monkeypatch.setitem(echeances.ECHELLES, "question", (Etape(timedelta(minutes=7), "relance", "debiteur"),))
    assert echeances.delai("question", "reponse", COORD) == timedelta(minutes=7)


# --- une obligation de chaque type -------------------------------------------------------

def _echelle(projet, message_id, debut, instants):
    """Passe le moteur à chacun des `instants` (minutes depuis `debut`) ; renvoie, pour chaque
    passe, les messages de Cime ajoutés."""
    sortie, avant = [], len(envoyes(projet))
    for minutes in instants:
        passer(projet, debut + timedelta(minutes=minutes))
        maintenant = envoyes(projet)
        sortie.append(maintenant[avant:])
        avant = len(maintenant)
    return sortie


def test_question_relance_puis_sup_puis_utilisateur(projet):
    m = poster(projet, WORKER, COORD, nature="question", resume="quelle API ?")
    debut = t0()
    assert _echelle(projet, m, debut, [14]) == [[]]
    relance, = _echelle(projet, m, debut, [16])
    assert relance == [(COORD, "relance", f"relance:{m}:0")]
    assert _echelle(projet, m, debut, [30]) == [[]]           # +15 min depuis l'étape (16)
    sup, = _echelle(projet, m, debut, [32])
    assert sup == [(ASSISTANT, "signalement", f"escalade:{m}:1")]
    utilisateur, = _echelle(projet, m, debut, [63])
    assert utilisateur == [("utilisateur", "signalement", f"escalade:{m}:2")]
    assert rang(projet, m) == (3, "ouverte")
    assert _echelle(projet, m, debut, [200]) == [[]]          # l'échelle est finie


def test_la_relance_est_une_ligne_relance_en_reponse_au_message_d_origine(projet):
    m = poster(projet, WORKER, COORD, nature="question")
    passer(projet, t0() + 16 * MIN)
    ligne = lignes(projet, "SELECT de, a, nature, en_reponse_a FROM messages WHERE nature = 'relance'")
    assert ligne == [("cime", COORD, "relance", m)]
    conn = ouvrir(projet)
    from cime.fondation.registre import etat_message
    assert etat_message(conn, lignes(projet, "SELECT id FROM messages WHERE nature='relance'")[0][0]) \
        == "inscrit"   # livrée comme tout message
    assert obligations.ouverte_pour(conn, lignes(projet, "SELECT id FROM messages WHERE nature='relance'")[0][0]) is None
    conn.close()


@pytest.mark.parametrize("de, a, nature, premier, cibles", [
    (COORD, ASSISTANT, "demande_accord", 11, [(ASSISTANT, "relance"), ("utilisateur", "signalement")]),
    (WORKER, COORD, "travail_pret", 31, [(COORD, "relance"), (ASSISTANT, "signalement")]),
    (COORD, ASSISTANT, "travail_pret", 61, [(ASSISTANT, "relance"), ("utilisateur", "signalement")]),
    (COORD, ASSISTANT, "demande_cloture", 61, [(ASSISTANT, "relance"), ("utilisateur", "signalement")]),
])
def test_chaque_type_a_sa_relance_puis_son_escalade(projet, de, a, nature, premier, cibles):
    m = poster(projet, de, a, nature=nature)
    debut = t0()
    pas = {"demande_accord": 10, "travail_pret": 30 if a == COORD else 60, "demande_cloture": 60}[nature]
    avant, premiere = _echelle(projet, m, debut, [premier - 2, premier])
    assert avant == [] and [(c[0], c[1]) for c in premiere] == [cibles[0]]
    seconde, = _echelle(projet, m, debut, [premier + pas + 1])
    assert [(c[0], c[1]) for c in seconde] == [cibles[1]]
    assert rang(projet, m)[0] == 2


def test_autorisation_assistant_puis_utilisateur_a_2_min_puis_renotification_a_10(projet):
    m = signaler(projet, ASSISTANT, "autorisation:7")          # le signalement est l'étape immédiate
    debut = t0()
    assert _echelle(projet, m, debut, [0]) == [[]] and rang(projet, m)[0] == 1
    assert _echelle(projet, m, debut, [1]) == [[]]
    utilisateur, = _echelle(projet, m, debut, [3])
    assert utilisateur == [("utilisateur", "signalement", f"escalade:{m}:1")]
    renotif, = _echelle(projet, m, debut, [12])
    assert renotif == [("utilisateur", "signalement", f"escalade:{m}:2")]   # renotification voulue


def test_attente_de_l_utilisateur_notifiee_puis_renotifiee_a_2_h_sans_action_implicite(projet):
    m = poster(projet, ASSISTANT, "utilisateur", nature="decision_utilisateur", resume="A ou B ?")
    debut = t0()
    assert _echelle(projet, m, debut, [0, 60, 119]) == [[], [], []]
    renotif, = _echelle(projet, m, debut, [125])
    assert renotif == [("utilisateur", "relance", f"relance:{m}:1")]
    assert _echelle(projet, m, debut, [500]) == [[]]


def test_signalement_grave_vers_sup_du_sup_puis_utilisateur(projet):
    m = signaler(projet, COORD, f"fin-sans-suite:{WORKER}")    # immédiat → sup (coord) : fait
    debut = t0()
    assert _echelle(projet, m, debut, [0]) == [[]]
    sup, = _echelle(projet, m, debut, [11])
    assert sup == [(ASSISTANT, "signalement", f"escalade:{m}:1")]
    utilisateur, = _echelle(projet, m, debut, [32])
    assert utilisateur == [("utilisateur", "signalement", f"escalade:{m}:2")]


def test_stopfailure_10_min_sup_du_sup_30_min_utilisateur(projet):
    conn = ouvrir(projet)
    hooks.sur_stop_failure(conn, projet, WORKER, {"error": "overloaded"}, 1)
    conn.close()
    m, = [r[0] for r in lignes(projet, "SELECT id FROM messages WHERE objet = ?",
                               (f"erreur-api:{WORKER}",))]
    assert lignes(projet, "SELECT a FROM messages WHERE id = ?", (m,)) == [(COORD,)]
    debut = t0()
    assert _echelle(projet, m, debut, [0]) == [[]]
    sup, = _echelle(projet, m, debut, [11])
    assert sup[0][0] == ASSISTANT
    utilisateur, = _echelle(projet, m, debut, [32])
    assert utilisateur[0][0] == "utilisateur"


def test_signalement_d_information_jamais_escalade(projet):
    m = signaler(projet, ASSISTANT, f"occupe:{COORD}")
    debut = t0()
    assert _echelle(projet, m, debut, [0, 30, 600]) == [[], [], []]


def test_suites_de_fusion_et_contexte(projet):
    m = signaler(projet, ASSISTANT, "suites:equipe-x")
    n = signaler(projet, COORD, f"contexte:{WORKER}")
    debut = t0()
    assert _echelle(projet, m, debut, [0]) == [[]] and _echelle(projet, n, debut, [0]) == [[]]
    passes, = _echelle(projet, m, debut, [11])
    assert (ASSISTANT, "relance", f"relance:{m}:1") in passes
    assert (COORD, "relance", f"relance:{n}:1") in passes
    fin, = _echelle(projet, m, debut, [32])
    assert ("utilisateur", "signalement", f"escalade:{m}:2") in fin       # suites : l'utilisateur
    assert (ASSISTANT, "signalement", f"escalade:{n}:2") in fin     # contexte : sup du sup


def test_accuse_d_une_consigne_la_livraison_s_en_charge(projet):
    m = poster(projet, ASSISTANT, COORD, attend="accuse")
    assert _echelle(projet, m, t0(), [11, 60]) == [[], []]
    assert rang(projet, m) == (1, "ouverte")


def test_consigne_sans_echeance_absolue_n_est_pas_relancee_par_les_echeances(projet):
    m = poster(projet, ASSISTANT, COORD, attend="reponse")
    assert _echelle(projet, m, t0(), [30, 600]) == [[], []]
    assert rang(projet, m) == (0, "ouverte")


# --- arrêt, idempotence, pilotage par les données -----------------------------------------

def test_obligation_satisfaite_escalade_stoppee(projet):
    m = poster(projet, WORKER, COORD, nature="question")
    debut = t0()
    _echelle(projet, m, debut, [16])
    conn = ouvrir(projet)
    obligations.satisfaire(conn, m, None)
    conn.close()
    assert _echelle(projet, m, debut, [40, 100, 400]) == [[], [], []]
    assert rang(projet, m) == (1, "satisfaite")


def test_un_tour_rejoue_ne_double_rien(projet):
    m = poster(projet, WORKER, COORD, nature="question")
    instant = t0() + 16 * MIN
    assert passer(projet, instant) == 1
    assert passer(projet, instant) == 0 and passer(projet, instant + timedelta(seconds=1)) == 0
    assert len(envoyes(projet)) == 1 and rang(projet, m)[0] == 1


def test_la_cle_objet_empeche_le_doublon_meme_si_le_rang_n_a_pas_avance(projet):
    m = poster(projet, WORKER, COORD, nature="question")
    instant = t0() + 16 * MIN
    passer(projet, instant)
    conn = ouvrir(projet)
    conn.execute("UPDATE obligations SET relances = 0, prochaine = NULL WHERE message_id = ?", (m,))
    conn.commit()
    conn.close()
    passer(projet, instant)                                    # rejoué : la relance existe déjà
    assert len(envoyes(projet, "relance")) == 1 and rang(projet, m)[0] == 1


def test_le_moteur_n_a_aucun_delai_en_dur(projet, monkeypatch):
    monkeypatch.setitem(echeances.ECHELLES, "question", (
        Etape(timedelta(minutes=1), "signalement", "utilisateur"),))
    m = poster(projet, WORKER, COORD, nature="question")
    # obligation créée avec l'ancienne échéance (15 min) : on la recale sur la table
    conn = ouvrir(projet)
    conn.execute("UPDATE obligations SET echeance = ? WHERE message_id = ?",
                 (echeances.echeance(
                     conn.execute("SELECT horodatage FROM messages WHERE id = ?", (m,)).fetchone()[0],
                     echeances.delai("question", "reponse", COORD)), m))
    conn.commit()
    conn.close()
    assert [(c[0], c[1]) for c in _echelle(projet, m, t0(), [2])[0]] == [("utilisateur", "signalement")]


def test_facteur_tour_execute_les_echeances(projet):
    poster(projet, WORKER, COORD, nature="question")
    facteur.tour(projet, t0() + 16 * MIN, livraison.Memoire())
    assert len(envoyes(projet, "relance")) == 1


# --- dette au repos -----------------------------------------------------------------------

def test_dette_au_repos_worker(projet):
    m = poster(projet, COORD, WORKER, attend="reponse", resume="réponds-moi")
    evt(projet, WORKER, "UserPromptSubmit")
    evt(projet, WORKER, "Stop")
    debut = t0()
    assert _echelle(projet, m, debut, [4]) == [[]]
    relance, = _echelle(projet, m, debut, [5.5])
    assert relance[0][:2] == (WORKER, "relance") and relance[0][2].startswith(f"dette:{WORKER}:")
    assert _echelle(projet, m, debut, [14]) == [[]]
    sup, = _echelle(projet, m, debut, [16])
    assert sup[0][:2] == (COORD, "signalement")
    assert _echelle(projet, m, debut, [29]) == [[]]
    supsup, = _echelle(projet, m, debut, [31])
    assert supsup[0][:2] == (ASSISTANT, "signalement")
    assert _echelle(projet, m, debut, [31, 90, 400]) == [[], [], []]   # chaque marche une fois


def test_dette_au_repos_coordinateur_jusqu_a_utilisateur(projet):
    poster(projet, ASSISTANT, COORD, attend="reponse")
    evt(projet, COORD, "Stop")
    debut = t0()
    cibles = []
    for minutes in (5.5, 16, 31):
        cibles += [c[0] for c in _echelle(projet, 0, debut, [minutes])[0]]
    assert cibles == [COORD, ASSISTANT, "utilisateur"]


def test_dette_pas_au_travail_ni_apres_acquittement(projet):
    m = poster(projet, COORD, WORKER, attend="reponse")
    evt(projet, WORKER, "UserPromptSubmit")                    # au travail : pas de dette « au repos »
    assert _echelle(projet, m, t0(), [10, 60]) == [[], []]
    evt(projet, WORKER, "Stop")
    conn = ouvrir(projet)
    obligations.satisfaire(conn, m, None)
    conn.close()
    assert _echelle(projet, m, t0(), [10, 60]) == [[], []]


def test_dette_repart_a_chaque_repos(projet):
    m = poster(projet, COORD, WORKER, attend="reponse")
    evt(projet, WORKER, "Stop")
    debut = t0()
    _echelle(projet, m, debut, [6])
    evt(projet, WORKER, "UserPromptSubmit")
    evt(projet, WORKER, "Stop")                                # un nouveau repos
    apres, = _echelle(projet, m, debut, [12])
    assert [c[:2] for c in apres] == [(WORKER, "relance")] and len(envoyes(projet, "dette")) == 2


def test_l_assistant_au_repos_sans_dette_n_est_jamais_relance(projet):
    evt(projet, ASSISTANT, "Stop")
    assert _echelle(projet, 0, t0(), [6, 60, 600]) == [[], [], []]
    poster(projet, "utilisateur", ASSISTANT, attend="rien", resume="info")
    assert _echelle(projet, 0, t0(), [6, 60, 600]) == [[], [], []]


def test_l_assistant_avec_dette_n_est_jamais_relance(projet):
    """Aucune relance de dette à l'Assistant, ni escalade par la dette au repos."""
    poster(projet, "utilisateur", ASSISTANT, attend="reponse", resume="réponds")   # pas d'échéance absolue
    evt(projet, ASSISTANT, "Stop")
    debut = t0()
    cibles = []
    for minutes in (5.5, 16, 31, 300):
        cibles += [c[0] for c in _echelle(projet, 0, debut, [minutes])[0]]
    assert cibles == []
