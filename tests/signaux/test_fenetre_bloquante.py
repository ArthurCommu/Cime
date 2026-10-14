"""Une fenêtre de choix qui bloque un agent : le facteur la reconnaît, ne tape rien dedans, et le dit
une fois par session à l'Assistant et à l'utilisateur, avec la question lue à l'écran."""
import json
from pathlib import Path

import pytest

from aide import fabriquer_projet, lignes
from faux_tmux import REGLE, FauxTmux
from cime.fondation.nom import VAR_PROJET
from cime.fondation.registre import inscrire_evenement, ouvrir
from cime.signaux import commandes, courrier, facteur, livraison, signalements_utilisateur
from datetime import datetime, timedelta, timezone

COORD, WORKER, ASSISTANT = "coord-x", "worker-x-t", "assistant"
S_COORD, S_WORKER, S_ASSISTANT = "essai-coord-x", "essai-worker-x-t", "essai-assistant"
ICI = Path(__file__).resolve().parent
RECONSTITUEES = ICI.parent / "fondation" / "fixtures" / "fenetre"
AUTORISATION = ICI.parent / "hote" / "fixtures" / "captures-autorisation" / "1-demande-avant.ansi"
APRES_LE_DELAI = 60.0       # « maintenant » est à +60 s : le message attend depuis plus de 30 s


def _ecran(nom):
    return (RECONSTITUEES / nom).read_text(encoding="utf-8")


QUESTION = _ecran("ask-user-question-reconstituee.txt")
OFFRE = _ecran("offre-mode-auto-reconstituee.txt")
PERMISSION = AUTORISATION.read_text(encoding="utf-8")


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


def demarrer(projet, agent):
    evt(projet, agent, "SessionStart", source="startup")


def repos(projet, agent):
    demarrer(projet, agent)
    evt(projet, agent, "UserPromptSubmit")
    evt(projet, agent, "Stop")


def poster(projet, de, a):
    conn = ouvrir(projet)
    try:
        return commandes.inscrire(conn, de=de, a=a, nature="consigne", resume="va", attend="rien",
                                  equipe="x")
    finally:
        conn.close()


def tour(projet, memoire, decalage=APRES_LE_DELAI):
    return facteur.tour(projet, datetime.now(timezone.utc) + timedelta(seconds=decalage), memoire)


def signalements(projet, agent=COORD):
    return lignes(projet, "SELECT a, objet, resume, corps FROM messages WHERE de = 'cime'"
                  " AND nature = 'signalement' AND objet = ? ORDER BY id", (f"fenetre-bloquante:{agent}",))


def evenements(projet):
    return [json.loads(d) for (d,) in lignes(
        projet, "SELECT details FROM evenements WHERE evenement = 'FenetreBloquante' ORDER BY id")]


def frappes(tmux):
    return [a for a in tmux.appels if a[0] == "send-keys"]


# --- une fenêtre est reconnue, signalée, jamais tapée --------------------------------------

def test_question_a_choix_un_signalement_a_l_assistant_un_a_l_utilisateur(projet, tmux):
    repos(projet, COORD)
    poster(projet, ASSISTANT, COORD)
    tmux.forcer_ecran(S_COORD, QUESTION)
    memoire = livraison.Memoire()
    tour(projet, memoire)
    assert frappes(tmux) == [] and tmux.entrees == []
    assert memoire.occupe_par[COORD] == "fenetre"
    (a1, o1, r1, c1), (a2, o2, r2, c2) = signalements(projet)
    assert (a1, a2) == (ASSISTANT, "utilisateur") and o1 == o2 == f"fenetre-bloquante:{COORD}"
    assert r1 == r2 and r1.startswith(f"{S_COORD} attend une réponse dans une fenêtre (choix) : ")
    assert "Quelle bibliothèque de dates" in r1 and len(r1) <= 160
    assert "Quelle bibliothèque de dates" in c1 and "1. Bibliothèque standard" in c1 and len(c1) <= 600
    (e,) = evenements(projet)
    assert e["agent"] == COORD and e["session"] == S_COORD and e["genre"] == "choix"
    assert e["options"][0] == "Bibliothèque standard" and "Quelle bibliothèque" in e["question"]


def test_la_meme_fenetre_a_la_passe_suivante_ne_signale_pas_deux_fois(projet, tmux):
    repos(projet, COORD)
    poster(projet, ASSISTANT, COORD)
    tmux.forcer_ecran(S_COORD, QUESTION)
    memoire = livraison.Memoire()
    tour(projet, memoire)
    tour(projet, memoire, APRES_LE_DELAI + 5)
    tour(projet, livraison.Memoire(), APRES_LE_DELAI + 10)     # un facteur redémarré non plus
    assert len(signalements(projet)) == 2 and len(evenements(projet)) == 1
    assert frappes(tmux) == []


def test_nouvelle_session_nouveau_signalement(projet, tmux):
    repos(projet, COORD)
    poster(projet, ASSISTANT, COORD)
    tmux.forcer_ecran(S_COORD, QUESTION)
    memoire = livraison.Memoire()
    tour(projet, memoire)
    demarrer(projet, COORD)                       # la session repart
    tour(projet, memoire, APRES_LE_DELAI + 5)
    assert len(signalements(projet)) == 4 and len(evenements(projet)) == 2


def test_offre_du_mode_auto_signalee_de_meme(projet, tmux):
    repos(projet, WORKER)
    poster(projet, COORD, WORKER)
    tmux.forcer_ecran(S_WORKER, OFFRE)
    tour(projet, livraison.Memoire())
    assert frappes(tmux) == []
    assert [a for a, *_ in signalements(projet, WORKER)] == [ASSISTANT, "utilisateur"]
    assert evenements(projet)[0]["genre"] == "offre-mode-auto"
    assert "knows your environment" in signalements(projet, WORKER)[0][2]


def test_demande_d_autorisation_signalee_jamais_tapee(projet, tmux):
    repos(projet, COORD)
    poster(projet, ASSISTANT, COORD)
    tmux.forcer_ecran(S_COORD, PERMISSION)
    tour(projet, livraison.Memoire())
    assert frappes(tmux) == []
    assert evenements(projet)[0]["genre"] == "permission"
    assert "touch essai-1.txt" in signalements(projet)[0][2]


def test_agent_en_plein_tour_derriere_une_fenetre_est_signale(projet, tmux):
    """Un `tour` qui ne finit pas parce qu'une fenêtre attend : même signalement."""
    demarrer(projet, COORD)
    evt(projet, COORD, "UserPromptSubmit")
    evt(projet, COORD, "PostToolUse")
    poster(projet, ASSISTANT, COORD)
    tmux.forcer_ecran(S_COORD, QUESTION)
    memoire = livraison.Memoire()
    tour(projet, memoire)
    assert memoire.occupe_par[COORD] == "fenetre" and len(signalements(projet)) == 2


def test_l_assistant_est_signale_a_l_utilisateur_seul(projet, tmux):
    repos(projet, ASSISTANT)
    poster(projet, COORD, ASSISTANT)
    tmux.forcer_ecran(S_ASSISTANT, QUESTION)
    tour(projet, livraison.Memoire())
    assert [a for a, *_ in signalements(projet, ASSISTANT)] == ["utilisateur"]


def test_pas_de_signalement_avant_le_delai(projet, tmux):
    repos(projet, COORD)
    poster(projet, ASSISTANT, COORD)
    tmux.forcer_ecran(S_COORD, QUESTION)
    memoire = livraison.Memoire()
    tour(projet, memoire, decalage=10.0)
    assert signalements(projet) == [] and memoire.occupe_par[COORD] == "inconnu"
    assert frappes(tmux) == []


def test_sans_message_en_attente_le_facteur_ne_regarde_pas(projet, tmux):
    repos(projet, COORD)
    tmux.forcer_ecran(S_COORD, QUESTION)
    tour(projet, livraison.Memoire())
    assert signalements(projet) == []


# --- ce qui ne change pas ---------------------------------------------------------------------

def test_un_ecran_qui_n_est_pas_une_fenetre_garde_le_comportement_actuel(projet, tmux):
    repos(projet, COORD)
    poster(projet, ASSISTANT, COORD)
    tour(projet, livraison.Memoire())
    assert len(tmux.entrees) == 1 and signalements(projet) == []


@pytest.mark.parametrize("ecran", [
    "⏺ Je réfléchis…\n  1. A\n  2. B\n\n✻ Working… (esc to interrupt)\n",
    f"⏺ Trois choix :\n  ❯ 1. A\n    2. B\n\n{REGLE}\n❯\xa0\n{REGLE}\n",
    "",
])
def test_un_ecran_sans_fenetre_ne_signale_rien(projet, tmux, ecran):
    repos(projet, COORD)
    poster(projet, ASSISTANT, COORD)
    tmux.forcer_ecran(S_COORD, ecran)
    tour(projet, livraison.Memoire())
    assert signalements(projet) == [] and tmux.entrees == []


def test_la_vraie_saisie_de_l_utilisateur_reste_une_collision(projet, tmux):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD)

    def entrelace(t, s, texte):
        invite = t.sessions[s]["invite"]
        t.sessions[s]["invite"] = invite[:5] + "XY" + invite[5:]

    tmux.apres_frappe.append(entrelace)
    memoire = livraison.Memoire()
    tour(projet, memoire)
    assert lignes(projet, "SELECT a, objet FROM messages WHERE objet LIKE 'collision-invite:%'") == [
        ("utilisateur", f"collision-invite:{COORD}")]
    assert signalements(projet) == [] and evenements(projet) == []
    assert memoire.occupe_par[COORD] == "invite" and m


def test_l_utilisateur_qui_tape_pendant_un_choix_n_est_pas_une_fenetre(projet, tmux):
    """Brouillon à l'invite + 30 s d'attente : le message attend, aucune fenêtre n'est annoncée."""
    repos(projet, COORD)
    poster(projet, ASSISTANT, COORD)
    tmux.frapper(S_COORD, "je tape")
    tmux.sessions[S_COORD]["activite"] -= 100
    tour(projet, livraison.Memoire())
    assert signalements(projet) == [] and tmux.entrees == []


def test_une_fenetre_apparue_entre_deux_lectures_n_est_jamais_tapee(projet, tmux):
    """Le facteur voit l'invite vide, puis une fenêtre prend la place avant la frappe : rien n'est tapé."""
    repos(projet, COORD)
    poster(projet, ASSISTANT, COORD)

    def fenetre_apres_la_premiere_capture(t, n):
        if n == 1:
            t.forcer_ecran(S_COORD, QUESTION)

    tmux.apres_capture.append(fenetre_apres_la_premiere_capture)
    memoire = livraison.Memoire()
    tour(projet, memoire)
    assert [a for a in frappes(tmux) if "-l" in a] == []
    assert memoire.occupe_par[COORD] == "fenetre" and len(signalements(projet)) == 2


def test_une_fenetre_qui_surgit_pendant_la_frappe_est_signalee_pas_prise_pour_une_saisie(projet, tmux):
    repos(projet, COORD)
    poster(projet, ASSISTANT, COORD)
    tmux.apres_frappe.append(lambda t, s, texte: t.forcer_ecran(s, QUESTION))
    memoire = livraison.Memoire()
    tour(projet, memoire)
    assert tmux.entrees == []
    assert memoire.occupe_par[COORD] == "fenetre"
    assert len(signalements(projet)) == 2
    assert lignes(projet, "SELECT 1 FROM messages WHERE objet LIKE 'collision-invite:%'") == []


# --- la cause se ferme quand l'agent reprend la vie ------------------------------------------

def test_le_signalement_a_l_utilisateur_se_ferme_quand_l_agent_reprend(projet, tmux):
    repos(projet, COORD)
    poster(projet, ASSISTANT, COORD)
    tmux.forcer_ecran(S_COORD, QUESTION)
    tour(projet, livraison.Memoire())
    assert "fenetre-bloquante:" in signalements_utilisateur._CAUSES_VIVANTES
    conn = ouvrir(projet)
    try:
        maintenant = datetime.now(timezone.utc) + timedelta(seconds=APRES_LE_DELAI)
        assert signalements_utilisateur.clore(conn, projet, maintenant) == 0
        inscrire_evenement(conn, agent=COORD, session_id="s", evenement="UserPromptSubmit", details={})
        assert signalements_utilisateur.clore(conn, projet, maintenant) == 1
    finally:
        conn.close()
