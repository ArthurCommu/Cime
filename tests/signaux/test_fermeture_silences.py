"""Ce qui se tait tant que le projet est fermé : le facteur, les sessions disparues, les sessions absentes et
les échéances, qui ne courent pas pendant la fermeture."""
import json
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from aide import cime, fabriquer_projet, lignes
from faux_tmux import FauxTmux
from cime.fondation import fermeture
from cime.fondation.nom import VAR_PROJET
from cime.fondation.registre import inscrire_evenement, ouvrir
from cime.signaux import commandes, echeances, facteur, livraison, relances

COORD, WORKER, ASSISTANT = "coord-x", "worker-x-t", "assistant"
S_COORD, S_WORKER, S_ASSISTANT = "essai-coord-x", "essai-worker-x-t", "essai-assistant"
MIN = timedelta(minutes=1)


@pytest.fixture
def projet(tmp_path, monkeypatch):
    racine = fabriquer_projet(tmp_path / "depot")
    monkeypatch.setenv(VAR_PROJET, str(racine))
    return racine


@pytest.fixture
def tmux(monkeypatch):
    faux = FauxTmux([S_COORD, S_WORKER, S_ASSISTANT])
    monkeypatch.setattr(livraison, "_tmux", faux)
    monkeypatch.setattr(livraison, "_dormir", lambda s: None)
    return faux


def evt(projet, agent, nom, **details):
    conn = ouvrir(projet)
    try:
        return inscrire_evenement(conn, agent=agent, session_id="s", evenement=nom, details=details)
    finally:
        conn.close()


def poster(projet, de, a, resume="va", nature="consigne", attend="rien", objet=None):
    conn = ouvrir(projet)
    try:
        return commandes.inscrire(conn, de=de, a=a, nature=nature, resume=resume, attend=attend,
                                  objet=objet, equipe="x")
    finally:
        conn.close()


def signalements(projet, objet_debut=""):
    return lignes(projet, "SELECT a, objet, nature FROM messages WHERE de = 'cime' AND "
                  "nature = 'signalement' AND objet LIKE ? ORDER BY id", (objet_debut + "%",))


def maintenant(decalage=10.0):
    return datetime.now(timezone.utc) + timedelta(seconds=decalage)


def tour(projet, memoire=None, decalage=10.0):
    return facteur.tour(projet, maintenant(decalage), memoire or livraison.Memoire())


def fermer(projet):
    """Pose le repère comme `cime fermer` : le repère puis l'événement."""
    fermeture.ecrire_repere(projet, {"conversations": [], "a_relancer": ["assistant"],
                                     "raisons": {}, "taches_en_cours": []})
    return evt_sans_agent(projet, "ProjetFerme")


def evt_sans_agent(projet, nom):
    conn = ouvrir(projet)
    try:
        return inscrire_evenement(conn, agent=None, session_id=None, evenement=nom, details={})
    finally:
        conn.close()


def rouvrir(projet):
    (projet / ".orga/etat/ferme.json").unlink(missing_ok=True)
    return evt_sans_agent(projet, "ProjetRouvert")


# --- (a) le facteur sort ------------------------------------------------------------------

def test_le_facteur_sort_avec_le_motif_ferme_quand_le_repere_existe(projet, monkeypatch):
    tours = []
    monkeypatch.setattr(facteur, "tour", lambda *a, **k: tours.append(1))
    monkeypatch.setattr(facteur, "agents_actifs", lambda p: True)
    fermeture.ecrire_repere(projet, {"conversations": []})
    assert facteur.boucler(projet, threading.Event(), pas=0) == "ferme"
    assert len(tours) <= 1


def test_le_facteur_ne_sort_pas_sans_repere(projet, monkeypatch):
    arret = threading.Event()
    tours = []

    def un_tour(*a, **k):
        tours.append(1)
        if len(tours) == 3:
            arret.set()
    monkeypatch.setattr(facteur, "tour", un_tour)
    monkeypatch.setattr(facteur, "agents_actifs", lambda p: True)
    assert facteur.boucler(projet, arret, pas=0) == "arret" and len(tours) == 3


def test_le_facteur_sort_quand_le_repere_apparait_en_cours_de_route(projet, monkeypatch):
    tours = []

    def un_tour(*a, **k):
        tours.append(1)
        if len(tours) == 2:
            fermeture.ecrire_repere(projet, {"conversations": []})
    monkeypatch.setattr(facteur, "tour", un_tour)
    monkeypatch.setattr(facteur, "agents_actifs", lambda p: True)
    assert facteur.boucler(projet, threading.Event(), pas=0) == "ferme"
    assert len(tours) == 2


def test_le_facteur_qui_sort_ferme_ne_passe_pas_la_main(projet, monkeypatch):
    import signal
    anciens = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        _sortie_ferme_sans_successeur(projet, monkeypatch)
    finally:
        for s, h in anciens.items():
            signal.signal(s, h)


def _sortie_ferme_sans_successeur(projet, monkeypatch):
    passes = []
    monkeypatch.setattr(facteur, "_passer_la_main", lambda p: passes.append(p))
    monkeypatch.setattr(facteur, "boucler", lambda p, a: "ferme")
    monkeypatch.setattr(commandes, "projet_courant", lambda: projet)
    import argparse
    assert facteur.executer(argparse.Namespace(une_fois=False)) == 0
    assert passes == []


# --- (b) sessions disparues -----------------------------------------------------------------------------

def test_c5_signale_une_session_disparue_sans_fermeture(projet, tmux):
    evt(projet, WORKER, "SessionStart")
    del tmux.sessions[S_WORKER]
    tour(projet)
    assert len(signalements(projet, "session-disparue")) == 1


def test_c5_se_tait_pour_une_session_disparue_apres_un_projet_ferme(projet, tmux):
    evt(projet, WORKER, "SessionStart")
    evt(projet, COORD, "SessionStart")
    fermer(projet)
    del tmux.sessions[S_WORKER], tmux.sessions[S_COORD]
    tour(projet)
    assert signalements(projet, "session-disparue") == []
    rouvrir(projet)
    tour(projet)
    assert signalements(projet, "session-disparue") == []     # un worker n'est pas relancé


def test_c5_signale_de_nouveau_une_session_demarree_apres_la_reouverture(projet, tmux):
    evt(projet, COORD, "SessionStart")
    fermer(projet)
    del tmux.sessions[S_COORD]
    rouvrir(projet)
    evt(projet, COORD, "SessionStart")                         # le coordinateur est relancé…
    tour(projet)
    assert signalements(projet, "session-disparue") == [(ASSISTANT, f"session-disparue:{COORD}",
                                                         "signalement")]   # …et sa session disparaît


# --- (c) sessions absentes -----------------------------------------------------------------------------

def test_x5_signale_sans_fermeture(projet, tmux):
    poster(projet, ASSISTANT, "coord-y", resume="où es-tu")
    tour(projet, decalage=150)
    assert len(signalements(projet, "session-absente")) == 1


def test_x5_se_tait_tant_que_le_projet_est_ferme(projet, tmux):
    poster(projet, ASSISTANT, "coord-y", resume="où es-tu")
    fermer(projet)
    memoire = livraison.Memoire()
    tour(projet, memoire, decalage=150)
    tour(projet, memoire, decalage=36000)
    assert signalements(projet, "session-absente") == []


def test_x5_pas_de_signalement_juste_apres_la_reouverture(projet, tmux):
    poster(projet, ASSISTANT, "coord-y", resume="où es-tu")
    evenement_a(projet, "ProjetFerme", maintenant(5))
    evenement_a(projet, "ProjetRouvert", maintenant(100))       # réouvert 100 s après le message
    facteur.tour(projet, maintenant(150), livraison.Memoire())   # message vieux de 150 s, réouvert depuis 50 s
    assert signalements(projet, "session-absente") == []
    facteur.tour(projet, maintenant(250), livraison.Memoire())   # 150 s depuis la réouverture
    assert len(signalements(projet, "session-absente")) == 1


# --- (d) aucune échéance ne court pendant la fermeture -----------------------------------

def evenement_a(projet, evenement, instant):
    """Pose un événement sans agent à l'instant voulu (horodatage du registre)."""
    conn = ouvrir(projet)
    try:
        with conn:
            conn.execute("INSERT INTO evenements (horodatage, agent, session_id, evenement, details)"
                         " VALUES (?, NULL, NULL, ?, '{}')", (livraison._iso(instant), evenement))
    finally:
        conn.close()


def message_a(projet, instant, **kw):
    """Inscrit un message puis recale son horodatage (et l'échéance de son obligation)."""
    mid = poster(projet, **kw)
    conn = ouvrir(projet)
    try:
        with conn:
            conn.execute("UPDATE messages SET horodatage = ? WHERE id = ?",
                         (livraison._iso(instant), mid))
            ligne = conn.execute("SELECT m.nature, o.attendu, o.debiteur, m.objet, m.corps"
                                 " FROM messages m JOIN obligations o ON o.message_id = m.id"
                                 " WHERE m.id = ?", (mid,)).fetchone()
            if ligne:
                d = echeances.delai(*ligne[:4], corps=ligne[4])
                conn.execute("UPDATE obligations SET echeance = ? WHERE message_id = ?",
                             (echeances.echeance(livraison._iso(instant), d), mid))
    finally:
        conn.close()
    return mid


def envoyes(projet, objet_debut=""):
    return lignes(projet, "SELECT a, nature, objet FROM messages WHERE de = 'cime' AND objet "
                  "LIKE ? ORDER BY id", (objet_debut + "%",))


def test_une_echeance_ne_court_pas_pendant_la_fermeture(projet):
    t0 = datetime.now(timezone.utc) - timedelta(hours=10)
    message_a(projet, t0, de=ASSISTANT, a=COORD, nature="question", attend="reponse", resume="q ?")
    evenement_a(projet, "ProjetFerme", t0 + MIN)
    evenement_a(projet, "ProjetRouvert", t0 + timedelta(hours=9))
    reouvert = t0 + timedelta(hours=9)
    assert relances.executer(projet, reouvert + 5 * MIN) == 0                  # QUESTION = 15 min
    assert envoyes(projet, "relance:") == []
    assert relances.executer(projet, reouvert + 16 * MIN) == 1                 # 15 min après le retour
    assert len(envoyes(projet, "relance:")) == 1


def test_sans_fermeture_la_meme_echeance_est_echue(projet):
    t0 = datetime.now(timezone.utc) - timedelta(hours=10)
    message_a(projet, t0, de=ASSISTANT, a=COORD, nature="question", attend="reponse", resume="q ?")
    assert relances.executer(projet, t0 + timedelta(hours=9)) == 1


def test_une_fermeture_sans_reouverture_n_avance_rien_et_une_ancienne_reouverture_ne_change_rien(
        projet):
    t0 = datetime.now(timezone.utc) - timedelta(hours=10)
    evenement_a(projet, "ProjetRouvert", t0 - timedelta(hours=5))     # bien avant le message
    message_a(projet, t0, de=ASSISTANT, a=COORD, nature="question", attend="reponse", resume="q ?")
    assert relances.executer(projet, t0 + 16 * MIN) == 1


def test_les_marches_suivantes_repartent_aussi_de_la_reouverture(projet):
    t0 = datetime.now(timezone.utc) - timedelta(hours=10)
    message_a(projet, t0, de=ASSISTANT, a=COORD, nature="question", attend="reponse", resume="q ?")
    assert relances.executer(projet, t0 + 16 * MIN) == 1               # la relance, avant la fermeture
    evenement_a(projet, "ProjetFerme", t0 + 17 * MIN)
    reouvert = t0 + timedelta(hours=9)
    evenement_a(projet, "ProjetRouvert", reouvert)
    assert relances.executer(projet, reouvert + 5 * MIN) == 0          # prochaine marche : +15 min
    assert relances.executer(projet, reouvert + 16 * MIN) == 1


def test_demande_d_autorisation_a_utilisateur_age_depuis_la_reouverture(projet):
    t0 = datetime.now(timezone.utc) - timedelta(hours=10)
    corps = json.dumps({"classe": "reserve"})
    mid = message_a(projet, t0, de="cime", a="utilisateur", nature="signalement",
                    objet="autorisation:perm-1", resume="Bash ?")
    conn = ouvrir(projet)
    with conn:
        conn.execute("UPDATE messages SET corps = ? WHERE id = ?", (corps, mid))
    conn.close()
    reouvert = t0 + timedelta(hours=9)
    evenement_a(projet, "ProjetFerme", t0 + MIN)
    evenement_a(projet, "ProjetRouvert", reouvert)
    # `reserve` : l'utilisateur d'emblée, renotification toutes les 2 h — pas de fil rouge sur 10 h
    conn = ouvrir(projet)
    assert relances.autorisations_a_utilisateur(conn, projet, reouvert + 5 * MIN) == 0
    conn.close()


def test_dette_au_repos_court_depuis_la_reouverture(projet):
    t0 = datetime.now(timezone.utc) - timedelta(hours=10)
    message_a(projet, t0, de=ASSISTANT, a=COORD, nature="consigne", attend="reponse", resume="fais")
    conn = ouvrir(projet)
    with conn:
        conn.execute("INSERT INTO evenements (horodatage, agent, session_id, evenement, details)"
                     " VALUES (?, ?, 's', 'UserPromptSubmit', '{}')", (livraison._iso(t0), COORD))
        conn.execute("INSERT INTO evenements (horodatage, agent, session_id, evenement, details)"
                     " VALUES (?, ?, 's', 'Stop', '{}')", (livraison._iso(t0 + MIN), COORD))
    conn.close()
    reouvert = t0 + timedelta(hours=9)
    evenement_a(projet, "ProjetFerme", t0 + 2 * MIN)
    evenement_a(projet, "ProjetRouvert", reouvert)
    conn = ouvrir(projet)
    assert relances.dette_au_repos(conn, projet, reouvert + 2 * MIN) == 0     # 5 min de repos
    assert relances.dette_au_repos(conn, projet, reouvert + 6 * MIN) == 1
    conn.close()


def test_depart_est_le_plus_tardif_du_message_et_de_la_derniere_reouverture(projet):
    t0 = datetime.now(timezone.utc) - timedelta(hours=10)
    conn = ouvrir(projet)
    iso = livraison._iso
    assert echeances.depart(conn, iso(t0)) == echeances._lire(iso(t0))
    evenement_a(projet, "ProjetRouvert", t0 + MIN)
    evenement_a(projet, "ProjetRouvert", t0 + 3 * MIN)
    assert echeances.depart(conn, iso(t0)) == echeances._lire(iso(t0 + 3 * MIN))
    assert echeances.depart(conn, iso(t0 + 5 * MIN)) == echeances._lire(iso(t0 + 5 * MIN))
    conn.close()


def test_fin_sans_terminer_ne_signale_pas_un_worker_tue_par_la_fermeture(projet, tmux):
    (projet / ".orga/teams/x/tasks/in-progress/t.md").write_text("t")
    evt(projet, WORKER, "SessionStart")
    fermer(projet)
    evt(projet, WORKER, "SessionEnd", reason="other")
    del tmux.sessions[S_WORKER]
    rouvrir(projet)
    tour(projet, decalage=3600)
    assert signalements(projet, "fin-sans-terminer") == []


def test_fin_sans_terminer_signale_toujours_une_fin_survenue_apres_la_reouverture(projet, tmux):
    (projet / ".orga/teams/x/tasks/in-progress/t.md").write_text("t")
    fermer(projet)
    rouvrir(projet)
    evt(projet, WORKER, "SessionStart")
    evt(projet, WORKER, "SessionEnd", reason="other")
    del tmux.sessions[S_WORKER]
    tour(projet, decalage=3600)
    assert len(signalements(projet, "fin-sans-terminer")) == 1


# --- la reprise de l'Assistant dit les tâches en cours ----------------------------------

def test_cime_reprise_apres_un_session_start_de_l_assistant_contient_les_taches_en_cours(
        projet, monkeypatch, capsys):
    (projet / ".orga/teams/x/tasks/in-progress/route-x.md").write_text("t")
    (projet / ".orga/teams/y/tasks/in-progress/vue-y.md").write_text("t")
    evt(projet, ASSISTANT, "SessionStart", source="resume")
    assert cime(monkeypatch, ASSISTANT, "reprise", projet=projet) == 0
    texte = capsys.readouterr().out
    assert "(d) Équipes et tâches en cours" in texte
    assert "x : route-x" in texte and "y : vue-y" in texte
