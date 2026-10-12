"""Banc de bout en bout : livraison et courriers.

Chaque cas est rejoué avec les vraies commandes, les vrais hooks, le vrai facteur (horloge simulée),
SQLite. Chaque preuve est une requête SQL sur le registre du projet jetable. Dans la variante
« oubli », l'acteur ne fait pas sa part : le test vérifie d'abord qu'il n'a rien écrit, puis que le
code produit quand même le signal (ou ne perd rien).
"""
import threading
from pathlib import Path

import pytest

from cime.fondation import registre
from cime.fondation.registre import ouvrir
from cime.signaux import courrier, hooks, livraison

from e2e.aides import (ASSISTANT, BAIL, COORD, COORD_B, W, accuser, envoyer, etat, frappes,
                       rien_ecrit, signalements, tape)


# --- deux envoyer simultanés vers un même coordinateur ----------------------------------------

def test_livraison_au_repos_normal(banc):
    banc.au_repos(COORD)
    banc.facteur_tour()                                   # le facteur bat : pas d'alerte « arrêté »
    sorties = banc.en_processus(
        (ASSISTANT, ("envoyer", "--a", COORD, "--nature", "consigne", "--attend", "rien",
                     "audit du lot"), None),
        (W, ("envoyer", "--a", COORD, "--nature", "compte_rendu", "lot fini"), None))
    assert [s[0] for s in sorties] == [0, 0], sorties
    deja = sorted(int(s[1].strip().splitlines()[-1]) for s in sorties)
    banc.horloge.avance(seconds=10)
    banc.facteur_tour()
    # un seul courrier, les deux messages dedans, une seule frappe, dans l'ordre des id
    assert banc.prouve("SELECT count(*) FROM courriers WHERE a = ?", (COORD,)) == [(1,)]
    assert banc.prouve("SELECT message_id FROM transitions WHERE etat = 'livre' ORDER BY message_id"
                       ) == [(i,) for i in deja]
    assert banc.prouve("SELECT count(DISTINCT courrier_id) FROM transitions WHERE etat = 'livre'"
                       ) == [(1,)]
    assert len(frappes(banc)) == 1
    texte = tape(banc)
    assert texte.index(f"(#{deja[0]})") < texte.index(f"(#{deja[1]})") and " ‖ " in texte
    # un troisième message arrive pendant que le courrier est ouvert : il attend
    c1 = banc.prouve("SELECT id FROM courriers")[0][0]
    troisieme = envoyer(banc, ASSISTANT, COORD, "consigne", "suite du lot")
    banc.horloge.avance(seconds=5)
    banc.facteur_tour()
    assert etat(banc, troisieme) == "inscrit"
    assert banc.prouve("SELECT count(*) FROM courriers WHERE etat = 'ouvert'") == [(1,)]
    assert accuser(banc, COORD, texte).code == 0
    banc.au_repos(COORD)                                   # le Stop rend le troisième
    banc.faire_tourner(60)
    assert etat(banc, troisieme) in ("livre", "pris_en_compte", "clos")
    c2 = banc.prouve("SELECT courrier_id FROM transitions WHERE message_id = ? AND etat = 'livre'",
                     (troisieme,))[0][0]
    assert c2 != c1
    # fenêtres disjointes : le dernier accusé du premier courrier précède la première livraison du second
    assert banc.prouve(
        "SELECT (SELECT max(id) FROM transitions WHERE courrier_id = ? AND etat = 'pris_en_compte')"
        " < (SELECT min(id) FROM transitions WHERE courrier_id = ? AND etat = 'livre')", (c1, c2)
    ) == [(1,)]
    assert banc.prouve("SELECT etat FROM courriers WHERE id = ?", (c1,)) == [("acquitte",)]


def test_livraison_au_repos_oubli(banc):
    """Le coordinateur reste occupé 3 min : rien n'est livré, rien n'est perdu, tout part à son repos."""
    inerte = banc.acteur(COORD).inerte()
    assert inerte.cime("repondre", "1", "oublié") is None
    assert rien_ecrit(banc, COORD)
    banc.au_travail(COORD)
    a = envoyer(banc, ASSISTANT, COORD, "consigne", "audit du lot")
    b = envoyer(banc, W, COORD, "compte_rendu", "lot fini")
    banc.faire_tourner(180)
    assert banc.prouve(BAIL) == [(0,)] and banc.prouve("SELECT count(*) FROM courriers") == [(0,)]
    assert [etat(banc, i) for i in (a, b)] == ["inscrit", "inscrit"]
    assert frappes(banc) == [] and signalements(banc) == []
    banc.au_repos(COORD, par="idle")                       # il revient : le facteur livre, tmux
    banc.faire_tourner(30, jusqu_a=lambda: banc.prouve(BAIL) != [(0,)])
    assert banc.prouve("SELECT message_id FROM transitions WHERE etat = 'livre' ORDER BY message_id"
                       ) == [(a,), (b,)]
    assert banc.prouve("SELECT count(*), min(voie) FROM courriers") == [(1, "tmux")]
    assert len(frappes(banc)) == 1


# --- trois états d'agent, trois voies --------------------------------------------------------

def _trois_destinataires(banc):
    banc.au_repos(COORD)
    banc.au_travail(W)
    banc.tmux.absente(COORD_B)
    banc.facteur_tour()
    return (envoyer(banc, ASSISTANT, COORD, "consigne", "pour le repos"),
            envoyer(banc, COORD, W, "consigne", "pour le travail"),
            envoyer(banc, ASSISTANT, COORD_B, "consigne", "pour l'absent"))


def test_destinataires_sans_reaction_normal(banc):
    repos, travail, absent = _trois_destinataires(banc)
    banc.horloge.avance(seconds=10)
    banc.facteur_tour()
    assert accuser(banc, COORD, tape(banc)).code == 0              # tmux : l'invite soumise
    r = banc.acteur(W).hook("PostToolUse", {"tool_name": "Bash"})   # au travail : le hook rend
    assert r.code == 2 and f"(#{travail})" in r.stderr
    assert banc.acteur(W).hook("PostToolUse", {"tool_name": "Bash"}).code == 0   # accusé indirect
    s = banc.acteur(COORD_B).hook("SessionStart", {"source": "startup"})          # session absente
    assert f"(#{absent})" in s.stdout
    assert banc.prouve("SELECT a, voie FROM courriers ORDER BY a") == [
        (COORD, "tmux"), (COORD_B, "hook:SessionStart"), (W, "hook:PostToolUse")]
    assert banc.prouve("SELECT message_id FROM transitions WHERE etat = 'pris_en_compte'"
                       " ORDER BY message_id") == [(repos,), (travail,), (absent,)]
    assert not [c for c in banc.tmux.commandes("facteur") if W in " ".join(map(str, c))
                and c[0] == "send-keys"]                           # le facteur n'a pas frappé chez le travailleur


def test_destinataires_sans_reaction_oubli(banc):
    """Les destinataires ne font rien : le code finit par signaler chaque cas, sans rien perdre."""
    assert banc.acteur(W).inerte().cime("repondre", "1", "oublié") is None
    assert rien_ecrit(banc, W, COORD_B)
    repos, travail, absent = _trois_destinataires(banc)
    banc.faire_tourner(11 * 60)
    # session absente depuis plus de 2 min : signalement à l'Assistant
    assert (ASSISTANT, f"session-absente:{COORD_B}") in signalements(banc)
    # agent au travail depuis plus de 10 min : information au supérieur
    assert (COORD, f"occupe:{W}") in signalements(banc)
    # repos sans accusé : retentés, puis échec + signalement au supérieur
    assert (ASSISTANT, f"livraison:{repos}") in signalements(banc)
    assert banc.prouve("SELECT count(*) FROM transitions WHERE message_id = ? AND etat = 'livre'",
                       (repos,)) == [(4,)]
    assert etat(banc, repos) == "echec"
    assert etat(banc, travail) == "inscrit" and etat(banc, absent) == "inscrit"   # rien perdu


# --- le facteur est tué entre la livraison et l'accusé ----------------------------------------

def test_accuse_absent_courrier_expire_normal(banc):
    banc.au_repos(COORD)
    i = envoyer(banc, ASSISTANT, COORD, "consigne", "à faire", "--attend", "accuse")
    banc.facteur_tour()
    texte = tape(banc)
    assert etat(banc, i) == "livre"
    banc.nouveau_facteur()                                 # tué entre la frappe et l'accusé
    assert accuser(banc, COORD, texte).code == 0           # le hook écrit l'accusé sans le facteur
    banc.horloge.avance(minutes=2)                         # le bail du courrier est passé
    banc.facteur_tour()                                    # le facteur redémarré
    banc.facteur_tour()
    assert banc.prouve("SELECT count(*) FROM courriers") == [(1,)]
    assert banc.prouve("SELECT etat FROM courriers") == [("acquitte",)]
    assert banc.prouve("SELECT count(*) FROM transitions WHERE message_id = ? AND etat = "
                       "'pris_en_compte'", (i,)) == [(1,)]
    assert banc.prouve("SELECT count(*) FROM transitions WHERE message_id = ? AND etat = 'livre'",
                       (i,)) == [(1,)]
    assert etat(banc, i) == "clos" and len(frappes(banc)) == 1


def test_accuse_absent_courrier_expire_oubli(banc):
    """Pas d'accusé du tout : le facteur redémarré referme le courrier expiré et le rouvre, une fois."""
    banc.au_repos(COORD)
    i = envoyer(banc, ASSISTANT, COORD, "consigne", "à faire", "--attend", "accuse")
    banc.facteur_tour()
    assert banc.acteur(COORD).inerte().hook("UserPromptSubmit", {}) is None
    assert rien_ecrit(banc, COORD)
    banc.nouveau_facteur()
    banc.horloge.avance(minutes=2)
    banc.facteur_tour()
    assert banc.prouve("SELECT id, etat, tentative FROM courriers ORDER BY id") == [
        (1, "echoue", 1), (2, "ouvert", 2)]
    assert banc.prouve("SELECT count(*) FROM courriers WHERE etat = 'ouvert'") == [(1,)]
    assert banc.prouve("SELECT count(*) FROM transitions WHERE message_id = ? AND etat = 'livre'",
                       (i,)) == [(2,)]
    assert banc.prouve("SELECT count(*) FROM transitions WHERE etat IN ('pris_en_compte', 'clos')"
                       ) == [(0,)]
    assert etat(banc, i) == "livre"


# --- un message pour l'Assistant au repos ------------------------------------------------------

def test_compte_rendu_livre_normal(banc):
    banc.au_repos(ASSISTANT)
    i = envoyer(banc, COORD, ASSISTANT, "compte_rendu", "bilan du module A prêt")
    banc.facteur_tour()
    attendu = f"coordinateur alpha : bilan du module A prêt (#{i})"
    assert banc.tmux.entrees == [("es-assistant", attendu)]          # entier, une seule frappe
    assert banc.prouve("SELECT voie FROM courriers") == [("tmux",)]
    assert accuser(banc, ASSISTANT, attendu).code == 0
    assert banc.prouve("SELECT json_extract(preuve, '$.evenement') FROM transitions"
                       " WHERE message_id = ? AND etat = 'pris_en_compte'", (i,)) == [
        ("UserPromptSubmit",)]
    # le texte accusé est exactement le texte livré
    assert banc.prouve("SELECT json_extract(details, '$.prompt') FROM evenements"
                       " WHERE evenement = 'UserPromptSubmit' AND agent = ?", (ASSISTANT,)) == [(attendu,)]
    assert etat(banc, i) == "clos"


def test_compte_rendu_livre_oubli(banc):
    """L'Assistant ne soumet rien : le message reste livré, jamais perdu, et est redonné."""
    banc.au_repos(ASSISTANT)
    assert banc.acteur(ASSISTANT).inerte().cime("repondre", "1", "oublié") is None
    assert rien_ecrit(banc, ASSISTANT)
    i = envoyer(banc, COORD, ASSISTANT, "compte_rendu", "bilan du module A prêt")
    banc.faire_tourner(60, jusqu_a=lambda: banc.prouve(
        "SELECT count(*) FROM transitions WHERE etat = 'livre'") == [(2,)])
    assert banc.prouve("SELECT count(*) FROM transitions WHERE message_id = ? AND etat = 'livre'",
                       (i,)) == [(2,)]
    assert banc.prouve("SELECT count(*) FROM transitions WHERE etat IN ('pris_en_compte', 'clos')"
                       ) == [(0,)]
    assert banc.prouve("SELECT count(*) FROM courriers WHERE etat = 'ouvert'") == [(1,)]
    assert [t for _, t in banc.tmux.entrees][0] == [t for _, t in banc.tmux.entrees][1]


# --- commande ET fichier pour-assistant -------------------------------------------------------

def _poser_fichier(banc):
    fichier = banc.projet / ".orga" / "teams" / "alpha" / "conversations" / "pour-assistant-lot.md"
    fichier.write_text("Question pour l'Assistant : on fusionne ?\n")
    return fichier


def test_question_a_l_assistant_normal(banc):
    banc.au_repos(ASSISTANT)
    envoyer(banc, COORD, ASSISTANT, "question", "on fusionne le lot ?")
    fichier = _poser_fichier(banc)
    assert banc.acteur(COORD).hook("Stop", {"stop_hook_active": False}).code in (0, 2)  # le hook ne lit pas le fichier
    banc.facteur_tour()
    assert fichier.exists()
    assert banc.prouve("SELECT count(*) FROM messages WHERE a = ? AND nature = 'question'",
                       (ASSISTANT,)) == [(1,)]
    assert banc.prouve("SELECT count(*) FROM messages WHERE de = ?", (COORD,)) == [(1,)]
    assert banc.prouve("SELECT count(*) FROM courriers WHERE a = ?", (ASSISTANT,)) == [(1,)]
    assert banc.prouve(BAIL) == [(1,)] and len(frappes(banc)) == 1


def test_question_a_l_assistant_oubli(banc):
    """Le coordinateur pose le fichier mais oublie la commande : aucune ligne, aucune livraison."""
    banc.au_repos(ASSISTANT)
    assert banc.acteur(COORD).inerte().cime("envoyer", "--a", ASSISTANT) is None
    assert rien_ecrit(banc, COORD)
    _poser_fichier(banc)
    banc.acteur(COORD).hook("Stop", {"stop_hook_active": False})
    banc.faire_tourner(120)
    assert banc.prouve("SELECT count(*) FROM messages") == [(0,)]
    assert banc.prouve("SELECT count(*) FROM courriers") == [(0,)]
    assert banc.prouve(BAIL) == [(0,)] and frappes(banc) == []


# --- le hook Stop attend un message -----------------------------------------------------------

def _stop_qui_attend(banc, evenement_pendant_attente):
    """Le worker s'arrête et son hook `Stop` attend 120 s ; `evenement_pendant_attente(h, ecoule)`
    est appelé à chaque seconde simulée d'attente."""
    debut = banc.horloge.monotonic()
    banc.horloge.pendant_sommeil.append(lambda h: evenement_pendant_attente(h, h.monotonic() - debut))
    return banc.acteur(W, CIME_ATTENTE_STOP="120").hook("Stop", {"stop_hook_active": False})


def test_attente_du_stop_normal(banc):
    vus, envoye = [], []

    def pendant(h, ecoule):
        if ecoule >= 10 and not vus:
            conn = ouvrir(banc.projet)
            try:
                vus.append(livraison.etat_agent(conn, W, h.maintenant()))
            finally:
                conn.close()
        if ecoule >= 30 and not envoye:
            envoye.append(envoyer(banc, COORD, W, "consigne", "relis le lot"))

    r = _stop_qui_attend(banc, pendant)
    i = envoye[0]
    assert vus == ["repos"]                                  # lu au repos pendant l'attente
    assert r.code == 2 and f"(#{i})" in r.stderr
    assert banc.prouve("SELECT voie FROM courriers WHERE a = ?", (W,)) == [("hook:Stop",)]
    assert banc.prouve(
        "SELECT round((julianday(t.horodatage) - julianday(e.horodatage)) * 86400)"
        " FROM transitions t, evenements e WHERE t.message_id = ? AND t.etat = 'livre'"
        " AND e.agent = ? AND e.evenement = 'Stop'", (i, W)) == [(30.0,)]
    assert banc.prouve("SELECT json_extract(preuve, '$.attente_s') FROM transitions"
                       " WHERE message_id = ? AND etat = 'livre'", (i,)) == [(30,)]
    assert frappes(banc) == []                               # aucune frappe : voie hook


def test_attente_du_stop_echap(banc):
    """Échap (le hook est tué) pendant l'attente : aucun courrier créé, le message n'est pas perdu."""
    tues, envoye = [], []

    def pendant(h, ecoule):
        if ecoule >= 10 and not tues:
            tues.append(ecoule)
            raise KeyboardInterrupt                           # le hook est coupé
    _stop_qui_attend(banc, pendant)
    assert tues and banc.prouve("SELECT count(*) FROM courriers") == [(0,)]
    banc.horloge.pendant_sommeil.clear()
    i = envoyer(banc, COORD, W, "consigne", "relis le lot")
    assert banc.prouve("SELECT count(*) FROM courriers") == [(0,)] and etat(banc, i) == "inscrit"
    assert livraison.etat_agent(ouvrir(banc.projet), W, banc.horloge.maintenant()) == "repos"


def test_attente_du_stop_oubli(banc):
    """L'agent ne s'arrête jamais (aucun Stop) : le message attend, puis l'information monte à 10 min."""
    banc.au_travail(W)
    assert banc.acteur(W).inerte().hook("Stop", {}) is None
    assert rien_ecrit(banc, W)
    i = envoyer(banc, COORD, W, "consigne", "relis le lot")
    banc.faire_tourner(9 * 60)
    assert signalements(banc) == [] and etat(banc, i) == "inscrit"
    banc.faire_tourner(120)
    assert signalements(banc) == [(COORD, f"occupe:{W}")]
    assert etat(banc, i) == "inscrit" and banc.prouve(BAIL) == [(0,)]


# --- deux PostToolUse parallèles pendant qu'un message arrive ---------------------------------

def _deux_posttooluse(banc):
    corps = '{"session_id": "s", "tool_name": "Bash"}'
    return banc.en_processus((W, ("hook", "PostToolUse"), corps), (W, ("hook", "PostToolUse"), corps))


def test_accuse_concurrent_normal(banc):
    banc.au_travail(W)
    banc.facteur_tour()
    i = envoyer(banc, COORD, W, "consigne", "étape suivante")
    sorties = _deux_posttooluse(banc)
    assert sorted(s[0] for s in sorties) == [0, 2], sorties
    rendus = "".join(s[2] for s in sorties)
    assert rendus.count(f"(#{i})") == 1                      # rendu une seule fois
    assert banc.prouve("SELECT count(*) FROM courriers WHERE a = ?", (W,)) == [(1,)]
    assert banc.prouve("SELECT voie FROM courriers WHERE a = ?", (W,)) == [("hook:PostToolUse",)]
    assert banc.prouve("SELECT count(*) FROM transitions WHERE message_id = ? AND etat = 'livre'",
                       (i,)) == [(1,)]


def test_accuse_concurrent_normal_accuse_sans_doublon(banc):
    """Deux hooks qui suivent la livraison accusent chacun le courrier ouvert : un seul accusé doit survivre.
    L'entrelacement est forcé (barrière juste avant l'écriture) : la course des processus réels
    l'a produit dans environ un cas sur huit."""
    banc.au_travail(W)
    i = envoyer(banc, COORD, W, "consigne", "étape suivante")
    assert banc.acteur(W).hook("PostToolUse", {"tool_name": "Bash"}).code == 2
    banc.horloge.avance(seconds=1)
    conn0 = ouvrir(banc.projet)
    evenement = registre.inscrire_evenement(conn0, agent=W, session_id="s", evenement="PostToolUse",
                                            details={})
    conn0.close()
    barriere, vrai = threading.Barrier(2), courrier.acquitter

    def acquitter_apres_la_lecture_de_l_autre(*a, **k):
        barriere.wait(timeout=10)                  # les deux ont lu « livre » sans accusé
        return vrai(*a, **k)

    def un_hook():
        conn = ouvrir(banc.projet)
        try:
            hooks._accuser_indirectement(conn, W, "PostToolUse", evenement)
        finally:
            conn.close()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(courrier, "acquitter", acquitter_apres_la_lecture_de_l_autre)
        fils = [threading.Thread(target=un_hook) for _ in range(2)]
        [f.start() for f in fils]
        [f.join() for f in fils]
    assert banc.prouve("SELECT count(*) FROM transitions WHERE message_id = ? AND etat = "
                       "'pris_en_compte'", (i,)) == [(1,)]
    assert banc.prouve("SELECT count(*) FROM transitions WHERE message_id = ? AND etat = 'clos'",
                       (i,)) == [(1,)]


def test_accuse_concurrent_oubli(banc):
    """L'agent n'émet aucun PostToolUse : le message est livré au plus tard à son Stop."""
    banc.au_travail(W)
    banc.facteur_tour()
    assert banc.acteur(W).inerte().hook("PostToolUse", {}) is None
    assert rien_ecrit(banc, W)
    i = envoyer(banc, COORD, W, "consigne", "étape suivante")
    banc.faire_tourner(60)
    assert etat(banc, i) == "inscrit"
    r = banc.acteur(W).hook("Stop", {"stop_hook_active": False})
    assert r.code == 2 and f"(#{i})" in r.stderr
    assert banc.prouve("SELECT voie FROM courriers WHERE a = ?", (W,)) == [("hook:Stop",)]


# --- l'utilisateur écrit dans le terminal de l'Assistant quand un message arrive -----------------------

def _message_pour_assistant(banc, resume="bilan du module A prêt"):
    banc.au_repos(ASSISTANT)
    return envoyer(banc, COORD, ASSISTANT, "compte_rendu", resume)


def test_frappe_et_collisions_normal(banc):
    """(a) un brouillon réel bloque la livraison, intact ; une suggestion atténuée ne la bloque pas."""
    i = _message_pour_assistant(banc)
    banc.tmux.brouillon(ASSISTANT, "je note une idée pour demain")
    banc.horloge.avance(seconds=10)
    banc.faire_tourner(120)
    assert banc.prouve(BAIL) == [(0,)] and etat(banc, i) == "inscrit"
    assert [c for c in banc.tmux.commandes("facteur") if c[0] == "send-keys"] == []
    assert banc.tmux.invite_de(ASSISTANT) == "je note une idée pour demain"   # brouillon intact
    banc.tmux.repos(ASSISTANT)                                  # l'utilisateur a envoyé son brouillon
    banc.facteur_tour()
    assert etat(banc, i) == "livre" and len(frappes(banc)) == 1  # livré à l'invite vide
    accuser(banc, ASSISTANT, tape(banc))
    banc.au_repos(ASSISTANT)
    j = envoyer(banc, COORD, ASSISTANT, "compte_rendu", "second bilan")
    banc.tmux.suggestion(ASSISTANT, "lance les tests")           # texte atténué seul
    banc.horloge.avance(seconds=10)
    banc.facteur_tour()
    assert etat(banc, j) == "livre" and len(frappes(banc)) == 2   # n'empêche pas la livraison


def _course(banc, injection):
    """Un message arrive ; `injection(tmux)` pose la frappe de l'utilisateur ; un tour du facteur."""
    i = _message_pour_assistant(banc)
    banc.horloge.avance(seconds=10)
    injection(banc.tmux)
    banc.facteur_tour()
    return i


def _derniere_preuve(banc, i, cle):
    return banc.prouve(f"SELECT json_extract(preuve, '$.{cle}') FROM transitions WHERE message_id = ?"
                       " AND etat = 'inscrit' ORDER BY id DESC LIMIT 1", (i,))[0][0]


def test_frappe_et_collisions_normal_course_avant_la_frappe(banc):
    """Un caractère s'ajoute entre la relecture et la frappe : pas d'Enter, le texte du facteur est effacé."""
    i = _course(banc, lambda t: t.injecter_apres(t.captures + 2, "x", ASSISTANT))
    assert banc.tmux.entrees == []                                   # pas d'Enter
    assert banc.tmux.invite_de(ASSISTANT) == "x"                     # la saisie de l'utilisateur seule
    assert _derniere_preuve(banc, i, "collision") == 1 and _derniere_preuve(banc, i, "efface") == 1
    assert banc.prouve("SELECT etat FROM courriers") == [("echoue",)] and etat(banc, i) == "inscrit"
    assert signalements(banc) == []                                  # effacé : rien à signaler
    banc.tmux.repos(ASSISTANT)                                       # l'utilisateur a vidé son invite
    banc.horloge.avance(seconds=30)
    banc.facteur_tour()                                              # retenté à l'invite vide
    assert etat(banc, i) == "livre" and len(banc.tmux.entrees) == 1
    assert banc.prouve("SELECT tentative FROM courriers ORDER BY id DESC LIMIT 1") == [(2,)]


def test_frappe_et_collisions_normal_course_apres_la_frappe(banc):
    """Un caractère arrive entre la frappe et l'Enter : pas d'Enter, signalement collision-invite à l'utilisateur."""
    i = _course(banc, lambda t: t.injecter_apres_frappe("x"))
    assert banc.tmux.entrees == []
    assert banc.tmux.invite_de(ASSISTANT).endswith("x")               # laissé tel quel
    assert _derniere_preuve(banc, i, "collision") == 1 and _derniere_preuve(banc, i, "efface") == 0
    assert signalements(banc) == [("utilisateur", f"collision-invite:{ASSISTANT}")]
    assert banc.prouve("SELECT etat FROM courriers") == [("echoue",)]


def test_frappe_et_collisions_normal_course_entrelacee(banc):
    """Une frappe de l'utilisateur s'entrelace au texte du facteur : pas d'Enter, signalement."""
    i = _course(banc, lambda t: t.entrelacer("x"))
    assert banc.tmux.entrees == []
    assert _derniere_preuve(banc, i, "collision") == 1 and _derniere_preuve(banc, i, "efface") == 0
    assert signalements(banc) == [("utilisateur", f"collision-invite:{ASSISTANT}")]
    assert banc.prouve("SELECT etat FROM courriers") == [("echoue",)] and etat(banc, i) == "inscrit"


def test_frappe_et_collisions_normal_residu_apres_enter(banc):
    """Un résidu de l'utilisateur après l'Enter : l'accusé est refusé (mélange), signalement, message redonné."""
    i = _message_pour_assistant(banc)
    banc.horloge.avance(seconds=10)
    banc.facteur_tour()
    texte = tape(banc)
    accuser(banc, ASSISTANT, texte + "x")                             # le modèle reçoit le message + la frappe
    assert banc.prouve("SELECT count(*) FROM transitions WHERE message_id = ? AND etat IN "
                       "('pris_en_compte', 'clos')", (i,)) == [(0,)]
    assert (("utilisateur", f"melange:{ASSISTANT}")) in signalements(banc)
    banc.au_repos(ASSISTANT)
    banc.horloge.avance(seconds=30)
    banc.facteur_tour()
    assert banc.prouve("SELECT count(*) FROM transitions WHERE message_id = ? AND etat = 'livre'",
                       (i,)) == [(2,)]                                # redonné


def test_frappe_et_collisions_oubli(banc):
    """L'utilisateur ne vide jamais son brouillon : il n'est ni lu ni effacé, le message attend, rien n'est perdu."""
    i = _message_pour_assistant(banc)
    assert banc.utilisateur().inerte().cime("envoyer") is None
    assert rien_ecrit(banc, "utilisateur")
    banc.tmux.brouillon(ASSISTANT, "je note une idée pour demain")
    banc.horloge.avance(seconds=10)
    banc.faire_tourner(15 * 60)
    assert banc.tmux.invite_de(ASSISTANT) == "je note une idée pour demain"
    assert [c for c in banc.tmux.commandes("facteur") if c[0] == "send-keys"] == []
    assert etat(banc, i) == "inscrit" and banc.prouve(BAIL) == [(0,)]
    assert banc.prouve("SELECT occupe_par FROM occupation WHERE agent = ?", (ASSISTANT,)) == [("invite",)]
    assert banc.prouve("SELECT count(*) FROM courriers") == [(0,)]


# --- un message long à l'Assistant -------------------------------------------------------------

CORPS_LONG = ("Synthèse du lot : " + "analyse détaillée du périmètre et des écarts relevés. " * 12).strip()


def _chemin_courrier(banc, i) -> Path:
    return banc.projet / ".orga" / "etat" / "courrier" / f"{i}.md"


def test_redistribution_courrier_long_normal(banc):
    assert len(CORPS_LONG) > 600
    banc.au_repos(ASSISTANT)
    i = envoyer(banc, COORD, ASSISTANT, "compte_rendu", "synthèse longue du lot", "--corps", CORPS_LONG)
    banc.horloge.avance(seconds=10)
    banc.facteur_tour()
    chemin = _chemin_courrier(banc, i)
    attendu = f"coordinateur alpha : synthèse longue du lot — {chemin} (#{i})"
    assert tape(banc) == attendu                                     # entière, préfixée, avec le chemin
    assert chemin.read_text(encoding="utf-8") == CORPS_LONG          # créé par le code
    assert sorted(p.name for p in chemin.parent.iterdir()) == [f"{i}.md"]
    assert banc.prouve("SELECT fichier FROM messages WHERE id = ?", (i,)) == [(None,)]  # aucun nom choisi par l'agent
    accuser(banc, ASSISTANT, attendu)
    assert etat(banc, i) == "clos"
    # un message court est livré entier, sans fichier
    banc.au_repos(ASSISTANT)
    j = envoyer(banc, COORD, ASSISTANT, "compte_rendu", "court", "--corps", "tout tient en une ligne")
    banc.horloge.avance(seconds=10)
    banc.facteur_tour()
    assert tape(banc) == f"coordinateur alpha : tout tient en une ligne (#{j})"
    assert not _chemin_courrier(banc, j).exists()


def test_redistribution_courrier_long_oubli(banc):
    """L'Assistant n'accuse pas : la redistribution cite le même fichier, aucun autre n'est créé."""
    banc.au_repos(ASSISTANT)
    assert banc.acteur(ASSISTANT).inerte().hook("UserPromptSubmit", {}) is None
    assert rien_ecrit(banc, ASSISTANT)
    i = envoyer(banc, COORD, ASSISTANT, "compte_rendu", "synthèse longue du lot", "--corps", CORPS_LONG)
    banc.horloge.avance(seconds=10)
    banc.faire_tourner(60, jusqu_a=lambda: len(banc.tmux.entrees) == 2)
    assert len(banc.tmux.entrees) == 2 and banc.tmux.entrees[0][1] == banc.tmux.entrees[1][1]
    assert str(_chemin_courrier(banc, i)) in banc.tmux.entrees[1][1]
    assert sorted(p.name for p in _chemin_courrier(banc, i).parent.iterdir()) == [f"{i}.md"]
    assert banc.prouve("SELECT count(*) FROM transitions WHERE message_id = ? AND etat = 'livre'",
                       (i,)) == [(2,)]
