"""Un courrier de voie hook resté ouvert ne réduit plus le facteur au silence : vrai chemin, faux tmux, horloge simulée.

Le hook `Stop` remet un message (courrier `hook:Stop` ouvert) ; l'agent n'ouvre aucun tour ensuite ; le
bail (60 s) passe ; un second message attend. Avant la correction, `livrer` rendait `return` sur ce courrier
sans condition d'expiration et sans rien écrire : rien n'était tapé."""
import json

from e2e.aides import ASSISTANT, COORD, envoyer, etat, frappes


def _remettre_par_le_hook(banc, texte):
    """Un message remis par le hook `Stop` : courrier `hook:Stop` ouvert, message `livre` par ce courrier."""
    m = envoyer(banc, ASSISTANT, COORD, "consigne", texte)
    r = banc.acteur(COORD).hook("Stop", {"stop_hook_active": False})
    assert r.code == 2 and texte in r.stderr                              # le hook rend le texte sur stderr
    return m


def _notes(banc, raison):
    return banc.prouve("SELECT count(*) FROM evenements WHERE evenement = 'LivraisonDifferee' AND agent = ?"
                       " AND json_extract(details, '$.raison') = ?", (COORD, raison))[0][0]


def test_courrier_hook_expire_est_referme_et_le_message_est_livre(banc):
    banc.au_repos(COORD)
    banc.facteur_tour()     # facteur en régime établi : son premier passage ferme les courriers expirés (reprise)
    m1 = _remettre_par_le_hook(banc, "première consigne")
    banc.tmux.repos(COORD)
    m2 = envoyer(banc, ASSISTANT, COORD, "consigne", "deuxième consigne")   # en attente, pas prise
    # bail du hook passé, aucun tour : depuis la règle doublons-livraison-envoi, un `hook:Stop` n'est refermé
    # qu'au plafond COURRIER_STOP_PLAFOND_S (300 s) — ce test attendait 120 s
    banc.horloge.avance(seconds=320)
    banc.faire_tourner(320, pas=10, jusqu_a=lambda: etat(banc, m2) == "livre")
    assert len(frappes(banc)) == 1
    assert etat(banc, m1) == "livre" and etat(banc, m2) == "livre"
    assert banc.prouve("SELECT etat FROM courriers WHERE a = ? AND voie = 'hook:Stop'", (COORD,)) == [("echoue",)]


def test_courrier_hook_non_expire_ne_tape_rien_et_se_note_une_fois(banc):
    banc.au_repos(COORD)
    _remettre_par_le_hook(banc, "première consigne")
    banc.tmux.repos(COORD)
    m2 = envoyer(banc, ASSISTANT, COORD, "consigne", "deuxième consigne")
    banc.faire_tourner(30, pas=10)                                          # bail encore valable
    assert frappes(banc) == [] and etat(banc, m2) == "inscrit"
    assert _notes(banc, "courrier-hook-ouvert") == 1
    details = banc.prouve("SELECT details FROM evenements WHERE evenement = 'LivraisonDifferee' AND agent = ?"
                          " AND json_extract(details, '$.raison') = 'courrier-hook-ouvert'", (COORD,))[0][0]
    assert {"courrier", "expire", "message"} <= set(json.loads(details))


def test_session_absente_avec_message_une_note_par_episode(banc):
    banc.au_repos(COORD)
    banc.tmux.absente(COORD)
    envoyer(banc, ASSISTANT, COORD, "consigne", "es-tu là ?")
    banc.faire_tourner(120, pas=10)
    assert frappes(banc) == [] and _notes(banc, "session-absente") == 1
