"""Diagnostic de la livraison à l'Assistant : Assistant au repos, message non tapé
pendant ~2 min puis livré par `PostToolUse`. Une hypothèse par cas, vrai chemin (vrai facteur, faux tmux
pilotable, horloge simulée). Les cas « caractérisation » fixent le comportement actuel ; ils ne
prétendent pas qu'il soit voulu."""
from pathlib import Path

from cime.fondation import invite
from cime.signaux import echeances

from e2e.aides import ASSISTANT, COORD, envoyer, etat, frappes


def _message_pour_l_assistant(banc):
    banc.au_repos(ASSISTANT)
    return envoyer(banc, COORD, ASSISTANT, "question", "tu peux regarder ?")


def _occupation(banc):
    return banc.prouve("SELECT occupe_par FROM occupation WHERE agent = ?", (ASSISTANT,))


def _differees(banc):
    return banc.prouve("SELECT json_extract(details, '$.raison'), json_extract(details, '$.message')"
                       " FROM evenements WHERE evenement = 'LivraisonDifferee' AND agent = ? ORDER BY id",
                       (ASSISTANT,))


# --- hypothèse 1 : window_activity, la fenêtre redessine sans cesse -------------------------------------

def test_fenetre_qui_redessine_toutes_les_secondes_rien_n_est_tape(banc):
    """Reproduit « repos + message en attente + rien tapé pendant plus de 30 s » dès que la TUI écrit au
    moins toutes les `SILENCE_FENETRE` secondes (terminal attaché qui redessine)."""
    m = _message_pour_l_assistant(banc)
    for _ in range(60):
        banc.tmux.activite(ASSISTANT)                     # la fenêtre vient d'écrire
        banc.facteur_tour()
        banc.horloge.avance(seconds=1)
    assert frappes(banc) == [] and etat(banc, m) == "inscrit"
    assert _occupation(banc) == [("invite",)]
    banc.faire_tourner(10, pas=2)                         # la fenêtre se tait : le facteur tape
    assert len(frappes(banc)) == 1 and etat(banc, m) == "livre"


def test_fenetre_qui_ecrit_moins_souvent_que_le_silence_est_livree(banc):
    m = _message_pour_l_assistant(banc)
    for _ in range(12):
        banc.tmux.activite(ASSISTANT)
        banc.horloge.avance(seconds=echeances.SILENCE_FENETRE + 0.5)
        banc.facteur_tour()
    assert etat(banc, m) == "livre"


# --- hypothèse 2 : un courrier tmux resté ouvert ------------------------------------------------------

def test_courrier_tmux_ouvert_retient_le_suivant_jusqu_a_la_fin_de_l_ecart(banc):
    """Un courrier tmux jamais accusé (l'Assistant continue son tour) retient le message suivant
    pendant `TENTATIVES_ECART_S[0]` s, pas plus ; au registre réel, aucun courrier tmux n'a jamais
    été ouvert pour l'Assistant, donc ce n'est pas la cause du retard observé."""
    premier = _message_pour_l_assistant(banc)
    banc.facteur_tour()
    assert etat(banc, premier) == "livre"
    deuxieme = envoyer(banc, COORD, ASSISTANT, "question", "et ça ?")
    banc.horloge.avance(seconds=10)
    banc.facteur_tour()
    assert etat(banc, deuxieme) == "inscrit" and len(frappes(banc)) == 1
    banc.horloge.avance(seconds=echeances.TENTATIVES_ECART_S[0])
    banc.facteur_tour()
    assert len(frappes(banc)) == 2


# --- hypothèse 3 : texte à l'invite (suggestion atténuée, brouillon) --------------------------------------

def _capture(suggestion_sgr):
    regle = "─" * 40
    return "\n".join([regle, f"❯\xa0{suggestion_sgr}", regle]) + "\n"


def test_suggestion_attenuee_par_sgr_2_est_ecartee(banc):
    assert invite.texte_invite(_capture("\x1b[2mrelance le test\x1b[0m")) == ""
    banc.au_repos(ASSISTANT)
    banc.tmux.suggestion(ASSISTANT, "relance le test")
    m = envoyer(banc, COORD, ASSISTANT, "question", "tu peux regarder ?")
    banc.faire_tourner(10, pas=2)
    assert etat(banc, m) == "livre"


def test_caracterisation_suggestion_grise_par_une_couleur_est_du_texte():
    """Une suggestion dessinée en gris (SGR 90, 256 couleurs, RVB) et non atténuée (SGR 2) est lue comme
    un brouillon : l'invite est « occupée » et le facteur ne tape pas. À confirmer sur une vraie capture."""
    for sgr in ("\x1b[90m", "\x1b[38;5;244m", "\x1b[38;2;136;136;136m"):
        assert invite.texte_invite(_capture(f"{sgr}relance le test\x1b[0m")) == "relance le test"


def test_brouillon_de_l_utilisateur_retient_la_frappe(banc):
    m = _message_pour_l_assistant(banc)
    banc.tmux.brouillon(ASSISTANT, "bonjour, je")
    banc.horloge.avance(seconds=10)
    banc.faire_tourner(60, pas=2)
    assert etat(banc, m) == "inscrit" and _occupation(banc) == [("invite",)]


# --- hypothèse 4 : un événement de tour postérieur au Stop ------------------------------------------------

def test_posttooluse_apres_le_stop_garde_l_agent_en_tour_jusqu_a_idle_prompt(banc):
    banc.au_repos(ASSISTANT)
    banc.acteur(ASSISTANT).hook("PostToolUse", {"tool_name": "Bash"})     # arrivé après le Stop
    m = envoyer(banc, COORD, ASSISTANT, "question", "tu peux regarder ?")
    banc.faire_tourner(60, pas=2)
    assert frappes(banc) == [] and _occupation(banc) == [("tour",)]
    banc.acteur(ASSISTANT).hook("Notification", {"notification_type": "idle_prompt"})
    banc.faire_tourner(10, pas=2)
    assert etat(banc, m) == "livre"


# --- hypothèse 5 : la boucle ------------------------------------------------------------------------------

def test_un_coordinateur_en_attente_de_stop_ne_retarde_pas_l_assistant(banc):
    banc.au_repos(COORD)                                                  # Stop récent : attente_stop
    envoyer(banc, ASSISTANT, COORD, "consigne", "audit du lot")
    m = _message_pour_l_assistant(banc)
    avant = len(banc.horloge.sommeils)
    banc.horloge.avance(seconds=5)
    banc.facteur_tour()
    assert etat(banc, m) == "livre"                                       # dès le premier tour
    assert sum(banc.horloge.sommeils[avant:]) <= (echeances.PAUSE_FRAPPE + echeances.PAUSE_VALIDATION) * 2


# --- observabilité : LivraisonDifferee, uniquement aux changements de raison -----------------------------------

def test_LivraisonDifferee_tour_puis_invite_puis_rien_deux_evenements(banc):
    banc.au_travail(ASSISTANT)
    m = envoyer(banc, COORD, ASSISTANT, "question", "tu peux regarder ?")
    banc.facteur_tour()
    banc.facteur_tour()                                                   # même raison : rien de plus
    banc.au_repos(ASSISTANT, par="idle")        # un Stop livrerait le message par le hook
    banc.tmux.brouillon(ASSISTANT, "bonjour, je")
    banc.horloge.avance(seconds=10)
    banc.facteur_tour()
    banc.facteur_tour()
    banc.tmux.repos(ASSISTANT)                                            # le brouillon est parti : tape
    banc.horloge.avance(seconds=10)
    banc.facteur_tour()
    assert etat(banc, m) == "livre"
    assert _differees(banc) == [("tour", m), ("invite", m)]
    age, detail = banc.prouve("SELECT json_extract(details, '$.age_s'),"
                              " json_extract(details, '$.texte_a_l_invite') FROM evenements"
                              " WHERE evenement = 'LivraisonDifferee' ORDER BY id DESC LIMIT 1")[0]
    assert age >= 10 and detail == len("bonjour, je")


# --- cause établie : bordure à libellé ⇒ invite « inconnue » ⇒ le facteur ne tapait jamais ----

CAPTURES = Path(__file__).resolve().parents[2] / "fondation" / "fixtures" / "invite"


def test_ecran_reel_a_bordure_a_libelle_le_facteur_tape(banc):
    capture = (CAPTURES / "assistant-bordure-a-libelle-vide.ansi").read_text(encoding="utf-8")
    banc.au_repos(ASSISTANT)
    banc.tmux.ecran_brut(ASSISTANT, capture)
    m = envoyer(banc, COORD, ASSISTANT, "question", "tu peux regarder ?")
    banc.faire_tourner(10, pas=2)
    assert len(frappes(banc)) == 1 and etat(banc, m) == "livre"
    assert [c for c in banc.tmux.commandes("facteur") if c[0] == "send-keys" and "Enter" in c]
    assert _differees(banc) == []                                         # jamais « inconnu »


# --- `inconnu` prolongé : noté une fois par épisode (événement + facteur.log) -------------------------------

def test_inconnu_prolonge_est_note_une_fois_dans_l_evenement_et_le_journal(banc, capsys):
    banc.au_repos(ASSISTANT)
    banc.tmux.ecran_brut(ASSISTANT, "Do you want to proceed?\n 1. Yes\n 2. No\n")      # aucune invite reconnue
    m = envoyer(banc, COORD, ASSISTANT, "question", "tu peux regarder ?")
    banc.faire_tourner(int(echeances.INCONNU_PROLONGE_S) - 10, pas=2)
    assert _differees(banc) == [("inconnu", m)]                                         # le changement de raison
    assert "écran non reconnu" not in capsys.readouterr().out
    banc.faire_tourner(60, pas=2)
    banc.faire_tourner(60, pas=2)                                                       # toujours pas de doublon
    assert _differees(banc) == [("inconnu", m), ("inconnu", m)]
    duree, prolonge = banc.prouve("SELECT json_extract(details, '$.duree_s'), json_extract(details, '$.prolonge')"
                                  " FROM evenements WHERE evenement = 'LivraisonDifferee' ORDER BY id DESC LIMIT 1")[0]
    assert prolonge == 1 and echeances.INCONNU_PROLONGE_S <= duree < echeances.INCONNU_PROLONGE_S + 4
    sortie = capsys.readouterr().out
    assert sortie.count("écran non reconnu") == 1 and f"message #{m}" in sortie
    banc.tmux.repos(ASSISTANT)                                                          # l'écran redevient lisible
    banc.faire_tourner(10, pas=2)
    assert etat(banc, m) == "livre" and len(_differees(banc)) == 2
