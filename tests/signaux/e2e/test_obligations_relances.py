"""Banc de bout en bout : obligations, relances, escalade.

Chaque délai est prouvé en minutes simulées entre le message d'origine (ou le `Stop`) et le message
que le code inscrit. Variante « oubli » : l'acteur ne fait pas sa part (il est inerte), et le code
produit quand même la relance, le signal ou l'escalade.
"""
import json
import sqlite3

import pytest

from e2e.aides import (ASSISTANT, BAIL, COORD, COORD_B, W, accuser, envoyer, etat, frappes,
                       minutes_apres, nb_ecrits, rien_ecrit, signalements, tape)

from cime.signaux import hooks

HOOKS_REEL = hooks.sur_facteur_arrete      # capturé avant que le conftest ne le neutralise
W2 = "worker-alpha-t2"
ECHELLE = "m.de = 'cime' AND (m.objet LIKE 'relance:%' OR m.objet LIKE 'escalade:%')"


def escalades(banc, reference):
    return minutes_apres(banc, reference, ECHELLE)


def obligation(banc, message_id):
    return banc.prouve("SELECT etat FROM obligations WHERE message_id = ?", (message_id,))


# --- une question worker → coordinateur ---------------------------------------------------------

def test_question_sans_reponse_normal(banc):
    q = envoyer(banc, W, COORD, "question", "quelle branche pour le lot ?")
    banc.horloge.avance(minutes=5)
    r = banc.acteur(COORD).cime("repondre", str(q), "la branche equipe/alpha")
    assert r.code == 0, r.erreur
    banc.faire_tourner(70 * 60, pas=60)
    assert obligation(banc, q) == [("satisfaite",)] and etat(banc, q) == "clos"
    assert escalades(banc, q) == []


def test_question_sans_reponse_oubli(banc):
    """Le coordinateur ne répond pas : relance à 15 min, signalement à l'Assistant à 30, à l'utilisateur à 60."""
    q = envoyer(banc, W, COORD, "question", "quelle branche pour le lot ?")
    assert banc.acteur(COORD).inerte().cime("repondre", str(q), "x") is None
    assert rien_ecrit(banc, COORD)
    banc.faire_tourner(61 * 60, pas=60)
    assert escalades(banc, q) == [(COORD, "relance", 15.0), (ASSISTANT, "signalement", 30.0),
                                  ("utilisateur", "signalement", 60.0)]
    assert obligation(banc, q) == [("ouverte",)]


# --- un worker doit rendre son travail_pret ----------------------------------------------------

def _consigne_de_travail(banc):
    c = envoyer(banc, COORD, W, "consigne", "fais le module A", "--attend", "travail_pret")
    banc.au_travail(W)
    banc.acteur(W).hook("PostToolUse", {"tool_name": "Bash"})          # la consigne lui est rendue
    return c


def test_travail_pret_sans_reponse_normal(banc):
    c = _consigne_de_travail(banc)
    r = banc.acteur(W).cime("repondre", str(c), "--nature", "travail_pret", "module A terminé")
    assert r.code == 0, r.erreur
    assert banc.prouve("SELECT de, a, nature, en_reponse_a FROM messages WHERE nature = 'travail_pret'"
                       ) == [(W, COORD, "travail_pret", c)]
    assert obligation(banc, c) == [("satisfaite",)]
    assert banc.prouve("SELECT debiteur, attendu FROM obligations WHERE message_id = ?", (r.id,)
                       ) == [(COORD, "revue")]
    assert banc.acteur(W).hook("Stop", {"stop_hook_active": False}).code == 0   # rien ne lui est dû
    assert signalements(banc) == []


def test_travail_pret_sans_reponse_oubli(banc):
    """Le worker s'arrête deux fois sans rien déclarer : signalement fin-sans-suite immédiat, puis escalade."""
    c = _consigne_de_travail(banc)
    assert banc.acteur(W).inerte().cime("repondre", str(c), "x") is None
    assert rien_ecrit(banc, W)
    premier = banc.acteur(W).hook("Stop", {"stop_hook_active": False, "last_assistant_message": "fini"})
    assert premier.code == 2 and "Tu dois encore" in premier.stderr and signalements(banc) == []
    second = banc.acteur(W).hook("Stop", {"stop_hook_active": True, "last_assistant_message": "fini"})
    assert second.code == 0
    assert signalements(banc) == [(COORD, f"fin-sans-suite:{W}:{c}")]
    s = banc.prouve("SELECT id FROM messages WHERE nature = 'signalement'")[0][0]
    assert banc.prouve("SELECT round((julianday(m.horodatage) - julianday(e.horodatage)) * 86400)"
                       " FROM messages m, evenements e WHERE m.id = ? AND e.id = (SELECT max(id) "
                       "FROM evenements WHERE evenement = 'Stop')", (s,)) == [(0.0,)]   # immédiat
    banc.faire_tourner(31 * 60, pas=60)
    assert escalades(banc, s) == [(ASSISTANT, "signalement", 10.0), ("utilisateur", "signalement", 30.0)]


# --- une demande d'autorisation ---------------------------------------------------------------

def _demande_d_autorisation(banc, agent=W):
    banc.au_repos(ASSISTANT)
    r = banc.acteur(agent).hook("PermissionRequest", {"tool_name": "Bash", "tool_input": {"command": "ls"}})
    assert r.code == 0
    (s, objet), = banc.prouve("SELECT id, objet FROM messages WHERE nature = 'signalement'")
    assert objet.startswith("autorisation:")
    return s


def test_autorisation_sans_reponse_normal(banc):
    """La demande `libre` d'un worker va à son coordinateur, qui l'accorde."""
    s = _demande_d_autorisation(banc)
    assert banc.prouve("SELECT a FROM messages WHERE id = ?", (s,)) == [(COORD,)]   # à t0
    r = banc.acteur(COORD).cime("accorder", str(s))
    assert r.code == 0, r.erreur
    assert obligation(banc, s) == [("satisfaite",)] and etat(banc, s) == "clos"
    banc.faire_tourner(15 * 60, pas=30)
    assert escalades(banc, s) == []


def test_autorisation_sans_reponse_oubli(banc):
    """Le coordinateur n'agit pas (mode inactif) : relance et Assistant à 2 min, l'utilisateur à 4,
    renotifié à 10."""
    s = _demande_d_autorisation(banc)
    assert banc.acteur(COORD).inerte().cime("accorder", str(s)) is None
    assert rien_ecrit(banc, COORD)
    banc.faire_tourner(11 * 60, pas=30)
    assert escalades(banc, s) == [(COORD, "relance", 2.0), (ASSISTANT, "signalement", 2.0),
                                  ("utilisateur", "signalement", 4.0), ("utilisateur", "signalement", 10.0)]
    assert obligation(banc, s) == [("ouverte",)]


def test_autorisation_sans_reponse_coordinateur_normal(banc):
    """Comportement conservé : la demande `libre` d'un coordinateur va à l'Assistant."""
    s = _demande_d_autorisation(banc, COORD)
    assert banc.prouve("SELECT a FROM messages WHERE id = ?", (s,)) == [(ASSISTANT,)]   # à t0
    r = banc.acteur(ASSISTANT).cime("accorder", str(s))
    assert r.code == 0, r.erreur
    assert obligation(banc, s) == [("satisfaite",)] and etat(banc, s) == "clos"
    banc.faire_tourner(15 * 60, pas=30)
    assert escalades(banc, s) == []


def test_autorisation_sans_reponse_coordinateur_oubli(banc):
    """Comportement conservé : l'Assistant n'agit pas, l'utilisateur est prévenu à 2 min, renotifié à 10."""
    s = _demande_d_autorisation(banc, COORD)
    assert banc.acteur(ASSISTANT).inerte().cime("accorder", str(s)) is None
    assert rien_ecrit(banc, ASSISTANT)
    banc.faire_tourner(11 * 60, pas=30)
    assert escalades(banc, s) == [("utilisateur", "signalement", 2.0), ("utilisateur", "signalement", 10.0)]
    assert obligation(banc, s) == [("ouverte",)]


# --- un coordinateur s'arrête avec une dette ----------------------------------------------------

def _coord_avec_dette(banc):
    """Une consigne `reponse` livrée et accusée ; le coordinateur dit « j'y vais » et s'arrête."""
    banc.au_repos(COORD)
    c = envoyer(banc, ASSISTANT, COORD, "consigne", "dis-moi où en est le lot", "--attend", "reponse")
    banc.horloge.avance(seconds=10)
    banc.facteur_tour()
    accuser(banc, COORD, tape(banc))
    r = banc.acteur(COORD).hook("Stop", {"stop_hook_active": False, "last_assistant_message": "j'y vais"})
    assert r.code == 2 and f"(#{c})" in r.stderr and "Tu dois encore" in r.stderr
    return c


def test_dette_du_coordinateur_normal(banc):
    c = _coord_avec_dette(banc)
    assert banc.acteur(COORD).cime("repondre", str(c), "le lot est à moitié").code == 0
    assert banc.acteur(COORD).hook("Stop", {"stop_hook_active": True}).code == 0
    banc.faire_tourner(35 * 60, pas=60)
    assert banc.prouve("SELECT count(*) FROM messages WHERE objet LIKE 'dette:%'") == [(0,)]
    assert obligation(banc, c) == [("satisfaite",)]


def test_dette_du_coordinateur_oubli(banc):
    """Il ne fait rien : relance à 5 min, +10 min l'Assistant, +15 min l'utilisateur. Aucune prose n'est lue."""
    c = _coord_avec_dette(banc)
    assert banc.acteur(COORD).inerte().cime("repondre", str(c), "x") is None
    assert rien_ecrit(banc, COORD)
    banc.acteur(COORD).hook("Stop", {"stop_hook_active": True, "last_assistant_message": "j'ai tout fait"})
    arret = banc.prouve("SELECT max(horodatage) FROM evenements WHERE evenement = 'Stop'")[0][0]
    banc.faire_tourner(31 * 60, pas=60)
    assert banc.prouve(
        "SELECT m.a, m.nature, round((julianday(m.horodatage) - julianday(?)) * 1440)"
        " FROM messages m WHERE m.objet LIKE 'dette:%' ORDER BY m.id", (arret,)
    ) == [(COORD, "relance", 5.0), (ASSISTANT, "signalement", 15.0), ("utilisateur", "signalement", 30.0)]
    assert obligation(banc, c) == [("ouverte",)]


# --- la session d'un worker disparaît -----------------------------------------------------------

def _worker_demarre(banc):
    banc.acteur(W).hook("SessionStart", {"source": "startup"})
    banc.tmux.repos(W)
    banc.facteur_tour()


def test_fin_de_session_du_worker_normal(banc):
    """Le worker déclare sa fin (SessionEnd) avant que la session ne s'éteigne : rien à signaler."""
    _worker_demarre(banc)
    banc.acteur(W).hook("SessionEnd", {"reason": "other"})
    banc.tmux.absente(W)
    banc.faire_tourner(15 * 60, pas=60)
    assert signalements(banc) == []


def test_fin_de_session_du_worker_oubli(banc):
    """Session tuée à la main, sans SessionEnd : le code le voit, une seule fois, et escalade."""
    _worker_demarre(banc)
    assert banc.acteur(W).inerte().hook("SessionEnd", {}) is None
    assert rien_ecrit(banc, W)
    banc.tmux.absente(W)
    banc.faire_tourner(31 * 60, pas=60)
    assert banc.prouve("SELECT a, count(*) FROM messages WHERE objet = ? GROUP BY a",
                       (f"session-disparue:{W}",)) == [(COORD, 1)]
    s = banc.prouve("SELECT id FROM messages WHERE objet = ?", (f"session-disparue:{W}",))[0][0]
    assert escalades(banc, s) == [(ASSISTANT, "signalement", 10.0), ("utilisateur", "signalement", 30.0)]


# --- une erreur d'API (StopFailure) -------------------------------------------------------------

def _erreur_api(banc):
    banc.au_repos(COORD)
    banc.au_travail(W)
    banc.acteur(W).hook("StopFailure", {"error": "model_not_found", "last_assistant_message": "…"})
    (s, a, objet, resume), = banc.prouve(
        "SELECT id, a, objet, resume FROM messages WHERE nature = 'signalement'")
    assert (a, objet) == (COORD, f"erreur-api:{W}") and "model_not_found" in resume
    return s


def test_erreur_api_normal(banc):
    s = _erreur_api(banc)
    assert banc.prouve("SELECT round((julianday(m.horodatage) - julianday(e.horodatage)) * 86400)"
                       " FROM messages m, evenements e WHERE m.id = ? AND e.evenement = 'StopFailure'",
                       (s,)) == [(0.0,)]                                # immédiat, sans attendre « fige »
    banc.horloge.avance(seconds=10)
    banc.facteur_tour()
    accuser(banc, COORD, tape(banc))                                    # le coordinateur le reçoit
    assert obligation(banc, s) == [("satisfaite",)]
    banc.faire_tourner(35 * 60, pas=60)
    assert escalades(banc, s) == []


def test_erreur_api_oubli(banc):
    s = _erreur_api(banc)
    assert banc.acteur(COORD).inerte().hook("UserPromptSubmit", {}) is None
    assert rien_ecrit(banc, COORD, W)
    banc.faire_tourner(31 * 60, pas=60)
    assert escalades(banc, s) == [(ASSISTANT, "signalement", 10.0), ("utilisateur", "signalement", 30.0)]


# --- clôture d'équipe avec des obligations ouvertes --------------------------------------------

def _equipe_a_cloturer(banc, valider=True):
    q = envoyer(banc, W, COORD, "question", "dernière question du lot")
    c = envoyer(banc, COORD, W, "consigne", "dernier lot", "--attend", "travail_pret")
    if valider:
        d = envoyer(banc, COORD, ASSISTANT, "demande_cloture", "le lot est fini, on clôt alpha")
        banc.acteur(ASSISTANT).cime("repondre", str(d), "--nature", "rapport_utilisateur", "alpha est prête à clore")
    return q, c


def _cloturer(banc, monkeypatch, equipe="alpha"):
    from starlette.testclient import TestClient
    from cime.hote import creer_app
    from cime.hote.dependances import Dependances
    from cime.hote.gardes import Gardes

    async def faux(self, argv, **kw):          # le terminal est celui du banc, jamais un vrai tmux
        return banc.tmux(*argv[1:])
    monkeypatch.setattr(Gardes, "aexecuter", faux)
    port = 8767
    deps = Dependances(instantane=lambda p: {}, horloge=banc.horloge.maintenant, prefixe="es")
    client = TestClient(creer_app(banc.projet, deps, port), headers={"host": f"127.0.0.1:{port}"})
    return client.post("/api/actions/cloturer", json={"equipe": equipe, "confirmation": equipe},
                       headers={"origin": f"http://127.0.0.1:{port}"}).json()


def test_cloture_d_equipe_normal(banc, monkeypatch):
    q, c = _equipe_a_cloturer(banc)
    banc.tmux.repos(COORD)
    reponse = _cloturer(banc, monkeypatch)
    assert (banc.projet / ".orga" / "teams" / "alpha" / "CLOTUREE").exists(), reponse
    for m in (q, c):
        assert obligation(banc, m) == [("abandonnee",)]
        assert etat(banc, m) == "abandonne"
        assert banc.prouve("SELECT json_extract(preuve, '$.cloture') IS NOT NULL FROM transitions"
                           " WHERE message_id = ? AND etat = 'abandonne'", (m,)) == [(1,)]
    banc.faire_tourner(70 * 60, pas=120)                                # plus aucune relance pour elles
    assert escalades(banc, q) == [] and escalades(banc, c) == []


def test_cloture_d_equipe_oubli(banc, monkeypatch):
    """L'Assistant ne valide pas la clôture : rien n'est clos, rien n'est abandonné."""
    q, c = _equipe_a_cloturer(banc, valider=False)
    assert banc.acteur(ASSISTANT).inerte().cime("repondre", "1", "--nature", "rapport_utilisateur", "x") is None
    assert rien_ecrit(banc, ASSISTANT)
    reponse = _cloturer(banc, monkeypatch)
    assert not (banc.projet / ".orga" / "teams" / "alpha" / "CLOTUREE").exists(), reponse
    assert [obligation(banc, m) for m in (q, c)] == [[("ouverte",)], [("ouverte",)]]
    assert banc.prouve("SELECT count(*) FROM transitions WHERE etat = 'abandonne'") == [(0,)]


# --- le facteur est arrêté ----------------------------------------------------------------

def _facteur_mort(banc, monkeypatch):
    monkeypatch.setattr(hooks, "sur_facteur_arrete", HOOKS_REEL)
    banc.au_repos(COORD_B)
    banc.tmux.repos(W)
    banc.tmux.repos(W2)
    banc.facteur_tour()
    banc.horloge.avance(seconds=60)                      # battement périmé (> 30 s)


def _message_et_ordres(banc):
    """Pendant l'arrêt : un message, deux `voir` (ordres). Rend (id du message, sorties des commandes)."""
    envoi = banc.acteur(ASSISTANT).cime("envoyer", "--a", COORD_B, "--nature", "consigne",
                                        "--attend", "rien", "reprends le module B")
    voir = [banc.acteur(COORD, CIME_ATTENTE_ORDRE="2").cime("voir", agent) for agent in (W, W2)]
    return envoi, voir


def _ordres(banc):
    return banc.prouve("SELECT id, etat FROM ordres ORDER BY id")


def test_facteur_arrete_normal(banc, monkeypatch):
    _facteur_mort(banc, monkeypatch)
    envoi, voir = _message_et_ordres(banc)
    assert "FACTEUR ARRÊTÉ" in envoi.erreur and envoi.code == 0
    assert [v.code for v in voir] == [4, 4] and all("en file, facteur arrêté" in v.sortie for v in voir)
    assert _ordres(banc) == [(1, "en_file"), (2, "en_file")]
    # un hook rend le signalement à l'Assistant
    r = banc.acteur(ASSISTANT).hook("PostToolUse", {"tool_name": "Bash"})
    assert r.code == 2 and "facteur est arrêté" in r.stderr
    assert banc.acteur(ASSISTANT).hook("PostToolUse", {"tool_name": "Bash"}).code == 0   # une seule fois
    assert banc.prouve("SELECT a, count(*) FROM messages WHERE objet = 'facteur-arrete'") == [(ASSISTANT, 1)]
    # le facteur revient : ordres dans l'ordre d'id, message livré, signalement clos
    banc.facteur_tour()
    assert _ordres(banc) == [(1, "execute"), (2, "execute")]
    assert banc.prouve("SELECT id FROM ordres ORDER BY fini, id") == [(1,), (2,)]
    assert etat(banc, envoi.id) == "livre" and len(frappes(banc)) == 1
    assert banc.prouve("SELECT o.etat FROM obligations o JOIN messages m ON m.id = o.message_id"
                       " WHERE m.objet = 'facteur-arrete'") == [("satisfaite",)]
    fini = banc.prouve("SELECT fini FROM ordres ORDER BY id")
    banc.facteur_tour()
    assert banc.prouve("SELECT fini FROM ordres ORDER BY id") == fini      # exécutés une seule fois


def test_facteur_arrete_oubli(banc, monkeypatch):
    """L'Assistant ne lit rien : le signalement (créé par le hook d'un autre agent) est abandonné au retour."""
    _facteur_mort(banc, monkeypatch)
    envoi, voir = _message_et_ordres(banc)
    avant = nb_ecrits(banc, ASSISTANT)
    assert banc.acteur(ASSISTANT).inerte().hook("PostToolUse", {}) is None
    assert nb_ecrits(banc, ASSISTANT) == avant
    banc.acteur(W).hook("PostToolUse", {"tool_name": "Bash"})               # un autre agent travaille
    (s,), = banc.prouve("SELECT id FROM messages WHERE objet = 'facteur-arrete'")
    assert etat(banc, s) == "inscrit"
    banc.facteur_tour()
    assert etat(banc, s) == "abandonne" and not [f for f in frappes(banc) if "facteur" in f[-1]]
    assert _ordres(banc) == [(1, "execute"), (2, "execute")] and etat(banc, envoi.id) == "livre"


def _surveillant(banc, tmp_path, demarrer):
    from cime.lanceur.surveillant import Surveillant, battement_frais
    dossier = tmp_path / "maison"
    dossier.mkdir()
    (dossier / "projets.json").write_text(json.dumps([{"chemin": str(banc.projet), "nom": "Banc"}]))
    notifications = []
    s = Surveillant(dossier, notifier=lambda titre, texte: notifications.append((titre, texte)),
                    demarrer=demarrer, agents_actifs=lambda p: True,
                    frais=lambda p: battement_frais(p, banc.horloge.maintenant()),
                    dormir=banc.horloge.sleep, horloge=banc.horloge.monotonic)
    return s, notifications


def test_facteur_qui_ne_repart_pas_normal(banc, monkeypatch, tmp_path):
    _facteur_mort(banc, monkeypatch)
    envoi, voir = _message_et_ordres(banc)
    assert "FACTEUR ARRÊTÉ" in envoi.erreur and [v.code for v in voir] == [4, 4]
    assert banc.acteur(ASSISTANT).hook("PostToolUse", {}).code == 2          # le signalement est rendu
    lancements = []

    def demarrer(projet):                       # le surveillant relance `cime facteur`
        lancements.append(projet)
        banc.facteur_tour()
        return True
    surveillant, notifications = _surveillant(banc, tmp_path, demarrer)
    assert surveillant.passe() == [str(banc.projet)] and len(lancements) == 1 and notifications == []
    assert _ordres(banc) == [(1, "execute"), (2, "execute")]
    assert banc.prouve("SELECT id FROM ordres ORDER BY fini, id") == [(1,), (2,)]
    assert banc.prouve("SELECT count(*) FROM transitions WHERE message_id = ? AND etat = 'livre'",
                       (envoi.id,)) == [(1,)]
    from cime.signaux import facteur
    with facteur.verrou(banc.projet):           # il bat et tient son verrou : rien à relancer
        assert surveillant.passe() == [] and len(lancements) == 1


def test_facteur_qui_ne_repart_pas_oubli(banc, monkeypatch, tmp_path):
    """Personne ne réagit et le facteur ne repart pas : notification après 3 échecs, une seule, rien perdu."""
    _facteur_mort(banc, monkeypatch)
    envoi, voir = _message_et_ordres(banc)
    avant = nb_ecrits(banc, ASSISTANT)
    assert banc.acteur(ASSISTANT).inerte().cime("accorder", "1") is None
    assert nb_ecrits(banc, ASSISTANT) == avant
    essais = []
    surveillant, notifications = _surveillant(banc, tmp_path, lambda p: essais.append(p) or False)
    assert surveillant.passe() == [] and len(essais) == 3
    assert len(notifications) == 1 and "ne repart pas après 3 essais" in notifications[0][1]
    banc.horloge.avance(seconds=60)
    assert surveillant.passe() == [] and len(essais) == 3 and len(notifications) == 1   # pas de rafale
    assert _ordres(banc) == [(1, "en_file"), (2, "en_file")] and etat(banc, envoi.id) == "inscrit"
    banc.facteur_tour()                                                     # l'utilisateur relance à la main
    assert _ordres(banc) == [(1, "execute"), (2, "execute")]
    assert banc.prouve("SELECT id FROM ordres ORDER BY fini, id") == [(1,), (2,)]


# --- un fichier pour-assistant-*.md sans commande -----------------------------------------------

def _fichier_sans_commande(banc):
    fichier = banc.projet / ".orga" / "teams" / "alpha" / "conversations" / "pour-assistant-lot.md"
    fichier.write_text("Question pour l'Assistant : on fusionne ?\n")
    return fichier


def test_voie_unique_la_commande_normal(banc):
    """La seule voie est la commande : une ligne, livrée."""
    banc.au_repos(ASSISTANT)
    i = envoyer(banc, COORD, ASSISTANT, "question", "on fusionne le lot ?")
    banc.horloge.avance(seconds=10)
    banc.facteur_tour()
    assert etat(banc, i) == "livre" and banc.prouve("SELECT count(*) FROM messages") == [(1,)]


def test_voie_unique_la_commande_oubli(banc):
    """Le fichier seul ne produit ni ligne ni signal, quels que soient les hooks et le temps."""
    banc.au_repos(ASSISTANT)
    banc.tmux.repos(COORD)
    assert banc.acteur(COORD).inerte().cime("envoyer", "--a", ASSISTANT) is None
    assert rien_ecrit(banc, COORD)
    _fichier_sans_commande(banc)
    for evenement in ("SessionStart", "PostToolUse", "UserPromptSubmit", "Stop"):
        banc.acteur(COORD).hook(evenement, {"prompt": "x", "stop_hook_active": False})
    banc.faire_tourner(2 * 3600, pas=300)
    assert banc.prouve("SELECT count(*) FROM messages") == [(0,)]
    assert banc.prouve("SELECT count(*) FROM courriers") == [(0,)]
    assert banc.prouve(BAIL) == [(0,)] and frappes(banc) == []
