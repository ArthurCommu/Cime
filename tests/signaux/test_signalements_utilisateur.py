"""Signalements à l'utilisateur : aucune obligation, fermeture
par la cause, plafond de 2 h, solde au démarrage du facteur. Registre jetable ; les horodatages sont
posés à la main (T0 + minutes) pour que chaque cas soit exact."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from aide import fabriquer_projet
from cime.fondation.nom import VAR_PROJET
from cime.fondation.registre import inscrire_transition, ouvrir
from cime.signaux import commandes, echeances, hooks, matrice, obligations, signalements_utilisateur, vue

UTILISATEUR = "utilisateur"
COORD, WORKER = "coord-x", "worker-x-t"
T0 = datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def projet(tmp_path, monkeypatch):
    racine = fabriquer_projet(tmp_path / "depot")
    monkeypatch.setenv(VAR_PROJET, str(racine))
    return racine


def instant(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def iso(minutes: float) -> str:
    return instant(minutes).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def message(projet, de, a, nature, minutes, objet=None, etat="inscrit"):
    """Un message daté `minutes`, avec ses obligations selon la matrice, puis `livre` si demandé."""
    conn = ouvrir(projet)
    try:
        mid = commandes.inscrire(conn, de=de, a=a, nature=nature, resume="r", objet=objet, equipe="x")
        conn.execute("UPDATE messages SET horodatage = ? WHERE id = ?", (iso(minutes), mid))
        conn.execute("UPDATE transitions SET horodatage = ? WHERE message_id = ?", (iso(minutes), mid))
        if etat == "livre":
            inscrire_transition(conn, mid, "livre", "cime", {}, commit=False)
            conn.execute("UPDATE transitions SET horodatage = ? WHERE message_id = ? AND etat = 'livre'",
                         (iso(minutes), mid))
        conn.commit()
        return mid
    finally:
        conn.close()


def evenement(projet, agent, nom, minutes, details=None):
    conn = ouvrir(projet)
    try:
        conn.execute("INSERT INTO evenements (horodatage, agent, session_id, evenement, details)"
                     " VALUES (?, ?, 's', ?, ?)", (iso(minutes), agent, nom, json.dumps(details or {})))
        conn.commit()
    finally:
        conn.close()


def etat(projet, mid):
    """(dernière transition, preuve) du message."""
    conn = ouvrir(projet)
    try:
        nom, preuve = conn.execute(
            "SELECT etat, preuve FROM transitions WHERE message_id = ? ORDER BY id DESC LIMIT 1",
            (mid,)).fetchone()
        return nom, json.loads(preuve)
    finally:
        conn.close()


def obligation(projet, mid):
    conn = ouvrir(projet)
    try:
        return conn.execute("SELECT etat, ferme_par FROM obligations WHERE message_id = ?", (mid,)).fetchone()
    finally:
        conn.close()


def passer(projet, minutes) -> int:
    conn = ouvrir(projet)
    try:
        return signalements_utilisateur.clore(conn, projet, instant(minutes))
    finally:
        conn.close()


# --- la règle de la matrice ---------------------------------------------------------------

def test_matrice_signalement_a_utilisateur_n_ouvre_rien():
    assert matrice.obligation("signalement", UTILISATEUR, "escalade:3:1") is None
    assert matrice.obligation("signalement", UTILISATEUR, f"session-disparue:{WORKER}") is None
    assert matrice.obligation("signalement", UTILISATEUR, "melange:worker-x-t") is None


def test_matrice_entre_agents_et_attentes_reelles_inchangees():
    assert matrice.obligation("signalement", COORD, f"session-disparue:{WORKER}") == (COORD, "accuse")
    assert matrice.obligation("signalement", "assistant", "autorisation:3") == ("assistant", "decision")
    assert matrice.obligation("decision_utilisateur", UTILISATEUR) == (UTILISATEUR, "decision")
    assert matrice.obligation("donnee_utilisateur", UTILISATEUR) == (UTILISATEUR, "reponse")
    assert matrice.obligation("rapport_utilisateur", UTILISATEUR) == (UTILISATEUR, "lu")
    assert matrice.obligation("demande_accord", UTILISATEUR) == (UTILISATEUR, "accord")


def test_signalement_a_utilisateur_ne_cree_aucune_obligation(projet):
    mid = message(projet, "cime", UTILISATEUR, "signalement", 0, objet="escalade:9:1")
    assert obligation(projet, mid) is None
    conn = ouvrir(projet)
    try:
        assert vue.dettes_de(conn, UTILISATEUR) == []
    finally:
        conn.close()


def test_signalement_entre_agents_ouvre_toujours_son_accuse(projet):
    conn = ouvrir(projet)
    try:
        mid = hooks.signaler(conn, projet, a=COORD, objet=f"session-disparue:{WORKER}", resume="s")
        assert obligation(projet, mid) == ("ouverte", None)
        assert [(d["attendu"], d["de"]) for d in vue.dettes_de(conn, COORD)] == [("accuse", "cime")]
    finally:
        conn.close()


# --- déduplication --------------------------------------------------------------------

def test_melange_ne_se_duplique_pas_tant_que_le_premier_n_est_pas_clos(projet):
    conn = ouvrir(projet)
    try:
        objet = f"melange:{WORKER}"
        premier = hooks.signaler(conn, projet, a=UTILISATEUR, objet=objet, resume="m", unique=True)
        assert premier is not None
        assert hooks.signaler(conn, projet, a=UTILISATEUR, objet=objet, resume="m", unique=True) is None
        inscrire_transition(conn, premier, "clos", "cime", {"cause_disparue": "agent-vivant"})
        conn.commit()
        assert hooks.signaler(conn, projet, a=UTILISATEUR, objet=objet, resume="m", unique=True) is not None
    finally:
        conn.close()


# --- fermeture par la cause ---------------------------------------------------------------

@pytest.mark.parametrize("objet", ["erreur-api:", "melange:", "collision-invite:",
                                   "invite-non-validee:", "occupe:", "session-absente:"])
@pytest.mark.parametrize("evenement_", ["UserPromptSubmit", "Stop"])
def test_agent_qui_vit_ferme_le_signalement(projet, objet, evenement_):
    mid = message(projet, "cime", UTILISATEUR, "signalement", 5, objet=objet + WORKER)
    evenement(projet, WORKER, evenement_, 2)                   # antérieur : ne compte pas
    assert passer(projet, 10) == 0
    assert etat(projet, mid)[0] == "inscrit"
    evenement(projet, "worker-y-t", evenement_, 12)            # un autre agent : ne compte pas
    assert passer(projet, 13) == 0
    evenement(projet, WORKER, evenement_, 12)
    assert passer(projet, 15) == 1
    assert etat(projet, mid) == ("abandonne", {"cause_disparue": "agent-vivant"})


def test_escalade_ferme_quand_l_obligation_du_message_n_est_plus_ouverte(projet):
    q = message(projet, WORKER, COORD, "question", 0)
    esc = message(projet, "cime", UTILISATEUR, "signalement", 5, objet=f"escalade:{q}:2")
    assert passer(projet, 10) == 0
    conn = ouvrir(projet)
    try:
        obligations.satisfaire(conn, q, None)
    finally:
        conn.close()
    assert passer(projet, 15) == 1
    assert etat(projet, esc) == ("abandonne", {"cause_disparue": "escalade"})


@pytest.mark.parametrize("etat_initial, final", [("inscrit", "abandonne"), ("livre", "clos")])
def test_cause_disparue_donne_abandonne_si_non_remis_clos_si_livre(projet, etat_initial, final):
    mid = message(projet, "cime", UTILISATEUR, "signalement", 5, objet=f"session-disparue:{WORKER}",
                  etat=etat_initial)
    evenement(projet, WORKER, "SessionStart", 12)
    assert passer(projet, 15) == 1
    assert etat(projet, mid) == (final, {"cause_disparue": "session-disparue"})


def test_session_disparue_attend_un_session_start_posterieur(projet):
    mid = message(projet, "cime", UTILISATEUR, "signalement", 5, objet=f"session-disparue:{WORKER}")
    evenement(projet, WORKER, "SessionStart", 2)
    assert passer(projet, 10) == 0
    evenement(projet, WORKER, "SessionStart", 12)
    assert passer(projet, 15) == 1
    assert etat(projet, mid)[1] == {"cause_disparue": "session-disparue"}


def test_equipe_terminee_ferme_fin_sans_suite(projet):
    travail = message(projet, WORKER, COORD, "travail_pret", 0)
    fin = message(projet, "cime", UTILISATEUR, "signalement", 5, objet=f"fin-sans-suite:{WORKER}:{travail}")
    assert passer(projet, 10) == 0                                # l'obligation est encore ouverte
    conn = ouvrir(projet)
    try:
        conn.execute("INSERT INTO evenements (horodatage, agent, session_id, evenement, details)"
                     " VALUES (?, NULL, NULL, 'Cloture', ?)", (iso(12), json.dumps({"equipe": "x"})))
        conn.commit()
    finally:
        conn.close()
    assert passer(projet, 15) == 1
    assert etat(projet, fin) == ("abandonne", {"cause_disparue": "equipe-terminee"})


@pytest.mark.parametrize("nom, details", [("PostCompact", {}), ("SessionStart", {"source": "compact"})])
def test_contexte_ferme_au_compactage(projet, nom, details):
    mid = message(projet, "cime", UTILISATEUR, "signalement", 5, objet=f"contexte:{WORKER}")
    evenement(projet, WORKER, "SessionStart", 12, {"source": "startup"})   # pas un compactage
    assert passer(projet, 15) == 0
    evenement(projet, WORKER, nom, 16, details)
    assert passer(projet, 20) == 1
    assert etat(projet, mid) == ("abandonne", {"cause_disparue": "compactage"})


@pytest.mark.parametrize("objet", ["livraison:12", "import-cime:worker-x-t"])
def test_autre_objet_ferme_a_2_h(projet, objet):
    mid = message(projet, "cime", UTILISATEUR, "signalement", 0, objet=objet)
    assert passer(projet, 119) == 0
    assert passer(projet, 120) == 1
    assert etat(projet, mid) == ("abandonne", {"cause_disparue": "echeance"})


def test_plafond_ferme_meme_si_la_cause_dure(projet):
    assert echeances.SIGNALEMENT_UTILISATEUR_PLAFOND == echeances.RENOTIFICATION_UTILISATEUR == timedelta(hours=2)
    q = message(projet, WORKER, COORD, "question", 0)                    # obligation encore ouverte
    esc = message(projet, "cime", UTILISATEUR, "signalement", 5, objet=f"escalade:{q}:2")
    assert passer(projet, 124) == 0
    assert passer(projet, 125) == 1
    assert etat(projet, esc) == ("abandonne", {"cause_disparue": "echeance"})


def test_facteur_arrete_n_est_pas_touche_par_la_passe(projet):
    mid = message(projet, "cime", UTILISATEUR, "signalement", 0, objet="facteur-arrete")
    assert passer(projet, 600) == 0
    assert etat(projet, mid)[0] == "inscrit"


def test_signalement_entre_agents_n_est_jamais_ferme_par_la_passe(projet):
    mid = message(projet, "cime", COORD, "signalement", 5, objet=f"session-disparue:{WORKER}")
    evenement(projet, WORKER, "SessionStart", 12)
    assert passer(projet, 300) == 0
    assert etat(projet, mid)[0] == "inscrit"


# --- relances à l'utilisateur (renotifications, accusés d'avant les signalements sans obligation) -----------------------------

@pytest.mark.parametrize("etat_initial, final", [("inscrit", "abandonne"), ("livre", "clos")])
def test_relance_a_utilisateur_fermee_quand_son_obligation_source_est_fermee(projet, etat_initial, final):
    source = message(projet, "cime", UTILISATEUR, "signalement", 0, objet="livraison:3")
    _ouvrir_obligation_heritee(projet, source, UTILISATEUR, "accuse")
    mid = message(projet, "cime", UTILISATEUR, "relance", 5, objet=f"relance:{source}:0", etat=etat_initial)
    assert passer(projet, 6) == 0                                    # l'obligation source est encore ouverte
    conn = ouvrir(projet)
    try:
        obligations.satisfaire(conn, source, None)
    finally:
        conn.close()
    assert passer(projet, 10) == 1
    assert etat(projet, mid) == (final, {"cause_disparue": "relance-source"})


def test_relance_accuse_d_avant_la_serie_28_se_ferme_a_la_passe_suivante(projet):
    source = message(projet, "cime", UTILISATEUR, "signalement", 0, objet="livraison:3")
    _ouvrir_obligation_heritee(projet, source, UTILISATEUR, "accuse")
    mid = message(projet, "cime", UTILISATEUR, "relance", 5, objet=f"relance:{source}:0")
    assert passer(projet, 6) == 0
    assert signalements_utilisateur.solder(projet) == 1                   # l'accusé de `source` est soldé
    assert passer(projet, 10) == 1
    assert etat(projet, mid) == ("abandonne", {"cause_disparue": "relance-source"})


def test_relance_a_utilisateur_d_objet_inattendu_se_ferme_a_2_h(projet):
    mid = message(projet, "cime", UTILISATEUR, "relance", 0, objet="rappel:7")
    assert passer(projet, 119) == 0
    assert passer(projet, 120) == 1
    assert etat(projet, mid) == ("abandonne", {"cause_disparue": "echeance"})


def test_relance_a_un_agent_jamais_touchee_par_la_passe(projet):
    source = message(projet, WORKER, COORD, "question", 0)
    mid = message(projet, "cime", COORD, "relance", 5, objet=f"relance:{source}:1")
    autre = message(projet, "cime", WORKER, "relance", 5, objet="rappel:7")
    assert passer(projet, 600) == 0
    assert etat(projet, mid)[0] == "inscrit"
    assert etat(projet, autre)[0] == "inscrit"


def test_relance_a_utilisateur_reste_ouverte_tant_que_son_obligation_source_l_est(projet):
    source = message(projet, "assistant", UTILISATEUR, "decision_utilisateur", 0)
    mid = message(projet, "cime", UTILISATEUR, "relance", 5, objet=f"relance:{source}:1")
    assert passer(projet, 124) == 0                                  # 2 h après la relance : pas avant
    assert obligation(projet, source)[0] == "ouverte"
    assert passer(projet, 125) == 1
    assert etat(projet, mid) == ("abandonne", {"cause_disparue": "echeance"})


# --- solde au démarrage du facteur ---------------------------------------------

def _ouvrir_obligation_heritee(projet, mid, debiteur, attendu):
    conn = ouvrir(projet)
    try:
        obligations.ouvrir_obligation(conn, mid, debiteur, attendu)
    finally:
        conn.close()


def _journal(projet):
    conn = ouvrir(projet)
    try:
        return conn.execute("SELECT auteur, action, cible, details, resultat FROM journal ORDER BY id").fetchall()
    finally:
        conn.close()


def test_solde_n_abandonne_que_les_obligations_de_l_utilisateur_sur_signalement(projet):
    sig_livre = message(projet, "cime", UTILISATEUR, "signalement", 0, objet=f"session-disparue:{WORKER}",
                        etat="livre")
    sig_inscrit = message(projet, "cime", UTILISATEUR, "signalement", 0, objet="livraison:3")
    _ouvrir_obligation_heritee(projet, sig_livre, UTILISATEUR, "accuse")
    _ouvrir_obligation_heritee(projet, sig_inscrit, UTILISATEUR, "accuse")
    decision = message(projet, "assistant", UTILISATEUR, "decision_utilisateur", 0)
    donnee = message(projet, "assistant", UTILISATEUR, "donnee_utilisateur", 0)
    accord = message(projet, COORD, UTILISATEUR, "demande_accord", 0)
    autorisation = message(projet, "cime", "assistant", "signalement", 0, objet="autorisation:3")
    cloture = message(projet, COORD, "assistant", "demande_cloture", 0)
    evenement(projet, WORKER, "SessionStart", 12)                        # la cause de sig_livre a disparu

    assert signalements_utilisateur.solder(projet) == 2

    assert obligation(projet, sig_livre) == ("abandonnee", None)
    assert obligation(projet, sig_inscrit) == ("abandonnee", None)
    assert etat(projet, sig_livre) == ("clos", {"cause_disparue": "session-disparue"})
    assert etat(projet, sig_inscrit)[0] == "inscrit"                     # cause présente : rien d'autre
    for mid in (decision, donnee, accord, autorisation, cloture):
        assert obligation(projet, mid)[0] == "ouverte"
    journal = _journal(projet)
    assert [(a, b, c, json.loads(d), r) for a, b, c, d, r in journal] == [
        ("cime", "solder", f"msg-{sig_livre}", {"motif": "signalement-sans-obligation"}, "ok"),
        ("cime", "solder", f"msg-{sig_inscrit}", {"motif": "signalement-sans-obligation"}, "ok")]


def test_second_demarrage_ne_solde_rien(projet):
    sig = message(projet, "cime", UTILISATEUR, "signalement", 0, objet="livraison:3")
    _ouvrir_obligation_heritee(projet, sig, UTILISATEUR, "accuse")
    assert signalements_utilisateur.solder(projet) == 1
    assert signalements_utilisateur.solder(projet) == 0
    assert len(_journal(projet)) == 1
