"""Trois défauts de livraison, vrai chemin :
vraies commandes `cime`, vrais hooks, vrai facteur du banc, faux tmux, horloge simulée."""
import json

import pytest

from e2e.aides import ASSISTANT, COORD, envoyer, etat, frappes


# --- défaut 2 : agent repris muet ------------------------------------------------------------------
# `cime lancer coord <équipe> --reprendre` lance `claude --resume <id>` SANS message d'ouverture
# (lancer.py : « pas de message d'ouverture ») : la seule trace au registre est le `SessionStart`
# (source « resume »). Aucun `UserPromptSubmit`, aucun `Stop` : `etat_agent` rendait `inconnu`.

def _reprise(banc, agent=COORD):
    banc.acteur(agent).hook("SessionStart", {"source": "resume", "model": "claude-sonnet-5-5"})
    banc.tmux.repos(agent)


def _evenements(banc, agent):
    return [e for (e,) in banc.prouve("SELECT evenement FROM evenements WHERE agent = ? ORDER BY id",
                                      (agent,))]


def test_coordinateur_repris_sans_aucun_tour_recoit_son_courrier(banc):
    _reprise(banc)
    assert _evenements(banc, COORD) == ["SessionStart"]            # la mesure : rien d'autre
    m = envoyer(banc, ASSISTANT, COORD, "consigne", "reprends là où tu en étais")
    banc.faire_tourner(120, pas=10, jusqu_a=lambda: etat(banc, m) != "inscrit")
    assert len(frappes(banc)) == 1 and etat(banc, m) == "livre"
    assert banc.prouve("SELECT occupe_par FROM occupation WHERE agent = ?", (COORD,)) != [("inconnu",)]


def test_session_ouverte_puis_tour_en_cours_reste_tour(banc):
    _reprise(banc)
    banc.au_travail(COORD)                                          # UserPromptSubmit après SessionStart
    m = envoyer(banc, ASSISTANT, COORD, "consigne", "ne me coupe pas")
    banc.faire_tourner(120, pas=10)
    assert frappes(banc) == [] and etat(banc, m) == "inscrit"
    assert banc.prouve("SELECT occupe_par FROM occupation WHERE agent = ?", (COORD,)) == [("tour",)]


def test_ni_session_ni_tour_reste_inconnu(banc):
    banc.tmux.repos(COORD)
    m = envoyer(banc, ASSISTANT, COORD, "consigne", "es-tu là ?")
    banc.faire_tourner(120, pas=10)
    assert frappes(banc) == [] and etat(banc, m) == "inscrit"
    assert banc.prouve("SELECT occupe_par FROM occupation WHERE agent = ?", (COORD,)) == [("inconnu",)]


def test_lancement_neuf_consigne_d_ouverture_non_retapee(banc):
    """Un agent neuf reçoit son courrier par le hook `SessionStart` : le facteur ne tape pas en double."""
    m = envoyer(banc, ASSISTANT, COORD, "consigne", "bienvenue")
    r = banc.acteur(COORD).hook("SessionStart", {"source": "startup"})
    banc.tmux.repos(COORD)
    assert "bienvenue" in r.stdout
    banc.faire_tourner(120, pas=10)
    assert frappes(banc) == [] and etat(banc, m) in ("livre", "clos")


# --- défaut 2 bis : session remplacée ou tuée en plein tour ------------------------------------------
# Les événements de l'ancienne session restent au registre : le dernier est un `PostToolUse`, le
# `SessionStart` neuf est plus récent mais l'agent restait `tour` pour toujours.

def _ancienne_session_tuee_en_plein_tour(banc):
    banc.au_travail(COORD)
    banc.acteur(COORD).hook("PostToolUse", {"tool_name": "Bash"})


def test_source_figure_dans_les_details_de_l_evenement(banc):
    banc.acteur(COORD).hook("SessionStart", {"source": "resume"})
    assert banc.prouve("SELECT json_extract(details, '$.source') FROM evenements WHERE agent = ?",
                       (COORD,)) == [("resume",)]





@pytest.mark.parametrize("source", ["resume", "startup"])
def test_session_neuve_apres_un_tour_interrompu_est_au_repos(banc, source):
    _ancienne_session_tuee_en_plein_tour(banc)
    banc.acteur(COORD).hook("SessionStart", {"source": source})
    banc.tmux.repos(COORD)
    m = envoyer(banc, ASSISTANT, COORD, "consigne", "reprends")
    banc.faire_tourner(120, pas=10, jusqu_a=lambda: etat(banc, m) != "inscrit")
    assert len(frappes(banc)) == 1


@pytest.mark.parametrize("source", ["compact", "clear"])
def test_compact_et_clear_ne_prouvent_pas_le_repos(banc, source):
    _ancienne_session_tuee_en_plein_tour(banc)
    banc.acteur(COORD).hook("SessionStart", {"source": source})
    m = envoyer(banc, ASSISTANT, COORD, "consigne", "ne me coupe pas")
    banc.faire_tourner(120, pas=10)
    assert frappes(banc) == [] and etat(banc, m) == "inscrit"


def test_session_ancienne_puis_tour_en_cours_reste_tour(banc):
    _ancienne_session_tuee_en_plein_tour(banc)
    banc.acteur(COORD).hook("SessionStart", {"source": "resume"})
    banc.au_travail(COORD)
    m = envoyer(banc, ASSISTANT, COORD, "consigne", "ne me coupe pas")
    banc.faire_tourner(120, pas=10)
    assert frappes(banc) == [] and etat(banc, m) == "inscrit"


# --- défaut 3 : `occupe_par` périmé après une livraison par hook ----------------------------------------

def _occupe_par(banc, agent=COORD):
    return banc.prouve("SELECT occupe_par FROM occupation WHERE agent = ?", (agent,))


def _tour_avec_message_livre_par_le_hook_stop(banc):
    banc.au_travail(COORD)
    m = envoyer(banc, ASSISTANT, COORD, "consigne", "x")
    banc.faire_tourner(60, pas=10)
    assert _occupe_par(banc) == [("tour",)] and etat(banc, m) == "inscrit"
    banc.acteur(COORD).hook("Stop", {"stop_hook_active": False})   # le hook livre le message
    banc.tmux.repos(COORD)
    assert etat(banc, m) == "livre"
    return m


def test_occupe_par_ne_reste_pas_tour_quand_le_hook_a_livre(banc):
    _tour_avec_message_livre_par_le_hook_stop(banc)
    banc.faire_tourner(120, pas=10)
    assert _occupe_par(banc) == [(None,)] and frappes(banc) == []


def test_ligne_perimee_d_un_facteur_precedent_est_remise_a_zero(banc):
    _tour_avec_message_livre_par_le_hook_stop(banc)
    banc.nouveau_facteur()                                         # le facteur repart sans mémoire
    banc.faire_tourner(60, pas=10)
    assert _occupe_par(banc) == [(None,)]


def test_agent_en_tour_avec_message_en_attente_reste_tour(banc):
    banc.au_travail(COORD)
    envoyer(banc, ASSISTANT, COORD, "consigne", "x")
    banc.faire_tourner(300, pas=10)
    assert _occupe_par(banc) == [("tour",)] and frappes(banc) == []


# --- défaut 1 : message replié par la TUI (`[Pasted text #N …]`) ------------------------------------------
# Écran réel d'un coordinateur : `❯ [Pasted text #1].orga/etat/courrier/7.md
# (#7) ‖ Assistant : … (#8)`. Le « ‖ » sépare deux courriers : #7 et #8 ont été tapés ensemble
# en une frappe ; le marqueur remplace le début du texte, la fin reste visible. Aucune capture réelle du
# marqueur (attributs SGR compris) n'existe dans le dépôt.

REGLE = "─" * 40


def _frappe_repliee(banc, marqueur, garde=0):
    banc.au_repos(COORD)
    banc.tmux.replier(marqueur, garde)
    m = envoyer(banc, ASSISTANT, COORD, "consigne", "regarde les captures")
    banc.faire_tourner(120, pas=10, jusqu_a=lambda: etat(banc, m) != "inscrit")
    return m


@pytest.mark.parametrize("marqueur", ["[Pasted text #1]", "[Pasted text #2]", "[Pasted text #1 +4 lines]",
                                      "[Pasted text #3 +1 line]"])
def test_invite_reduite_au_seul_marqueur_est_notre_frappe(banc, marqueur):
    m = _frappe_repliee(banc, marqueur)
    assert len(frappes(banc)) == 1 and etat(banc, m) in ("livre", "clos")
    assert "regarde les captures" in banc.tmux.entrees[-1][1]


def test_marqueur_suivi_de_la_fin_de_notre_texte_est_notre_frappe(banc):
    """L'écran réel : le marqueur couvre le début du texte, la fin est restée tapée."""
    m = _frappe_repliee(banc, "[Pasted text #1]", garde=25)
    assert len(frappes(banc)) == 1 and etat(banc, m) in ("livre", "clos")
    assert banc.tmux.entrees and "regarde les captures" in banc.tmux.entrees[-1][1]


def test_marqueur_et_autre_texte_reste_une_collision(banc):
    banc.au_repos(COORD)
    banc.tmux.replier("[Pasted text #1]")
    banc.tmux.injecter_apres_frappe("Z")                           # l'utilisateur tape pendant la frappe
    m = envoyer(banc, ASSISTANT, COORD, "consigne", "regarde")
    banc.faire_tourner(60, pas=10)
    assert banc.tmux.entrees == [] and etat(banc, m) != "livre"
    assert [r for r in banc.prouve("SELECT objet FROM messages WHERE objet LIKE 'collision-invite:%'")]


def test_marqueur_deja_present_avant_la_frappe_aucune_frappe_aucun_enter(banc):
    banc.au_repos(COORD)
    banc.tmux.brouillon(COORD, "[Pasted text #1]")
    m = envoyer(banc, ASSISTANT, COORD, "consigne", "regarde")
    banc.faire_tourner(300, pas=10)
    assert frappes(banc) == [] and banc.tmux.entrees == [] and etat(banc, m) == "inscrit"


def test_marqueur_attenue_n_est_jamais_une_invite_vide(banc):
    """Quels que soient les attributs SGR du marqueur (atténué ou non), l'invite n'est pas vide."""
    banc.au_repos(COORD)
    banc.tmux.ecran_brut(COORD, f"{REGLE}\n❯\xa0\x1b[2m[Pasted text #1]\x1b[0m\n{REGLE}\n")
    m = envoyer(banc, ASSISTANT, COORD, "consigne", "regarde")
    banc.faire_tourner(300, pas=10)
    assert frappes(banc) == [] and etat(banc, m) == "inscrit"


def test_apres_un_abandon_avec_marqueur_le_facteur_ne_retape_pas(banc):
    banc.au_repos(COORD)
    banc.tmux.replier("[Pasted text #1]")
    banc.tmux.injecter_apres_frappe("Z")
    envoyer(banc, ASSISTANT, COORD, "consigne", "regarde")
    banc.faire_tourner(600, pas=10)
    assert len(frappes(banc)) == 1 and banc.tmux.entrees == []


def test_marqueur_suivi_de_tout_notre_texte_est_une_collision(banc):
    """Le marqueur n'a mangé aucun préfixe de notre texte : il ne vient pas de notre frappe (collage
    de l'utilisateur entre le contrôle de l'invite vide et la frappe, par exemple) ⇒ pas d'Enter."""
    banc.au_repos(COORD)
    banc.tmux.replier("[Pasted text #1]", garde=10_000)            # marqueur + texte complet
    m = envoyer(banc, ASSISTANT, COORD, "consigne", "regarde")
    banc.faire_tourner(60, pas=10)
    assert banc.tmux.entrees == [] and etat(banc, m) != "livre"
    assert banc.prouve("SELECT count(*) FROM transitions WHERE json_extract(preuve, '$.collision') = 1")[0][0] >= 1


# --- défaut 4 : texte tapé SANS Entrée ---------
# Cas reproduits : l'Enter part (rc 0) mais la TUI ne le prend pas ; le message était déjà marqué livré,
# l'invite restait pleine et `_conditions` rendait `invite` à tous les passages, sans signalement.
# La cause réelle n'est pas établie (aucune capture) : ce banc ne prouve que la vérification.

def _enters(banc):
    return [c for c in banc.tmux.commandes("facteur") if c[0] == "send-keys" and "Enter" in c]


def _non_valides(banc):
    return banc.prouve("SELECT count(*) FROM messages WHERE objet LIKE 'invite-non-validee:%'")[0][0]


def _preuve(banc, m):
    return json.loads(banc.prouve("SELECT preuve FROM transitions WHERE message_id = ? AND etat = 'livre'",
                                  (m,))[0][0])


def test_invite_vide_apres_enter_un_seul_enter(banc):
    banc.au_repos(COORD)
    m = envoyer(banc, ASSISTANT, COORD, "consigne", "regarde")
    banc.faire_tourner(20, pas=10)
    assert len(_enters(banc)) == 1 and _non_valides(banc) == 0
    assert "entree_renvoyee" not in _preuve(banc, m)


def test_tui_qui_avale_le_premier_enter_puis_accepte_le_second(banc):
    banc.au_repos(COORD)
    banc.tmux.avaler_enters(1)
    m = envoyer(banc, ASSISTANT, COORD, "consigne", "regarde")
    banc.faire_tourner(20, pas=10)
    assert len(_enters(banc)) == 2 and len(banc.tmux.entrees) == 1
    assert "regarde" in banc.tmux.entrees[0][1] and _non_valides(banc) == 0
    assert _preuve(banc, m)["entree_renvoyee"] is True and _preuve(banc, m)["invite_apres"] == "vide"


def test_tui_qui_n_accepte_jamais_deux_enter_au_plus_un_signalement_plus_de_frappe(banc):
    banc.au_repos(COORD)
    banc.tmux.avaler_enters(100)
    envoyer(banc, ASSISTANT, COORD, "consigne", "regarde")
    banc.faire_tourner(1200, pas=10)
    assert len(_enters(banc)) == 2 and banc.tmux.entrees == []
    assert len(frappes(banc)) == 1 and _non_valides(banc) == 1
    assert _occupe_par(banc) == [("invite",)]


def test_autre_texte_a_l_invite_apres_enter_rien_n_est_renvoye(banc):
    banc.au_repos(COORD)
    banc.tmux.saisie_apres_enter("une saisie de l'utilisateur")
    envoyer(banc, ASSISTANT, COORD, "consigne", "regarde")
    banc.faire_tourner(20, pas=10)
    assert len(_enters(banc)) == 1 and len(frappes(banc)) == 1 and _non_valides(banc) == 1
