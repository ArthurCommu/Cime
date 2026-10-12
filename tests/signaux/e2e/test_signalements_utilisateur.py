"""Signalements à l'utilisateur : le vrai facteur, le faux tmux et l'horloge simulée.

Un signalement `cime → utilisateur` n'ouvre aucune obligation : pas de relance, pas d'escalade, pas de dette.
Il est clos par sa cause, ou à 2 h. Un signalement entre agents garde son accusé.
"""
from e2e.aides import ASSISTANT, COORD, W, envoyer, etat

from cime.fondation.registre import ouvrir
from cime.signaux import commandes, hooks, vue

UTILISATEUR = "utilisateur"


def _obligations_de_signalements_a_utilisateur(banc) -> int:
    return banc.prouve("SELECT count(*) FROM obligations o JOIN messages m ON m.id = o.message_id"
                       " WHERE m.a = 'utilisateur' AND m.nature = 'signalement'")[0][0]


def _dettes_de_l_utilisateur(banc) -> list[dict]:
    conn = ouvrir(banc.projet)
    try:
        return vue.dettes_de(conn, UTILISATEUR)
    finally:
        conn.close()


def test_signalements_a_utilisateur_sans_relance_sans_escalade_sans_dette(banc):
    """Une escalade de `relances` vers l'utilisateur (question sans réponse) et un signalement direct : aucun
    ne prend d'obligation, rien ne se relance pendant 3 h, et les dettes de l'utilisateur sont vides."""
    q = envoyer(banc, W, COORD, "question", "quelle branche pour le lot ?")
    assert banc.acteur(COORD).inerte().cime("repondre", str(q), "x") is None  # le coordinateur ne répond pas
    banc.faire_tourner(61 * 60, pas=60)                                        # escalade à l'utilisateur à 60 min
    [esc] = banc.prouve("SELECT id FROM messages WHERE a = 'utilisateur' AND objet LIKE 'escalade:%'")
    assert banc.prouve("SELECT count(*) FROM obligations WHERE message_id = ?", (esc[0],)) == [(0,)]

    conn = ouvrir(banc.projet)
    try:
        hooks.signaler(conn, banc.projet, a=UTILISATEUR, objet="livraison:9", resume="signal direct")
    finally:
        conn.close()
    assert _obligations_de_signalements_a_utilisateur(banc) == 0
    assert _dettes_de_l_utilisateur(banc) == []

    messages_avant = banc.prouve("SELECT count(*) FROM messages WHERE de = 'cime' AND a = 'utilisateur'")[0][0]
    banc.faire_tourner(3 * 3600, pas=300)
    messages_apres = banc.prouve("SELECT count(*) FROM messages WHERE de = 'cime' AND a = 'utilisateur'")[0][0]
    assert messages_apres == messages_avant                                    # ni relance ni escalade nouvelle
    assert _obligations_de_signalements_a_utilisateur(banc) == 0
    assert _dettes_de_l_utilisateur(banc) == []


def test_signalement_a_utilisateur_se_clot_a_2_h_sans_cause_mesurable(banc):
    """Le signalement de l'escalade reste visible jusqu'à 2 h, puis Cime le clôt (cause `echeance`)."""
    q = envoyer(banc, W, COORD, "question", "quelle branche pour le lot ?")
    assert banc.acteur(COORD).inerte().cime("repondre", str(q), "x") is None
    banc.faire_tourner(61 * 60, pas=60)
    [esc] = banc.prouve("SELECT id FROM messages WHERE a = 'utilisateur' AND objet LIKE 'escalade:%'")
    banc.faire_tourner(60 * 60, pas=60)                                        # 1 h : encore ouvert
    assert etat(banc, esc[0]) == "inscrit"
    banc.faire_tourner(61 * 60, pas=60)                                        # 2 h passées
    assert etat(banc, esc[0]) == "abandonne"
    assert banc.prouve("SELECT preuve FROM transitions WHERE message_id = ? ORDER BY id DESC LIMIT 1",
                       (esc[0],)) == [('{"cause_disparue": "echeance"}',)]


def test_signalement_entre_agents_ouvre_toujours_son_accuse(banc):
    conn = ouvrir(banc.projet)
    try:
        hooks.signaler(conn, banc.projet, a=COORD, objet=f"session-disparue:{W}", resume="s")
        assert [(d["attendu"], d["de"]) for d in vue.dettes_de(conn, COORD)] == [("accuse", "cime")]
    finally:
        conn.close()
    assert banc.prouve("SELECT count(*) FROM obligations WHERE debiteur = ? AND attendu = 'accuse'",
                       (COORD,)) == [(1,)]


def test_dettes_de_l_utilisateur_ne_gardent_que_les_vraies_attentes(banc):
    """Après un signalement à l'utilisateur et son escalade : ses dettes ne contiennent que sa décision."""
    envoyer(banc, W, COORD, "question", "quelle branche pour le lot ?")
    banc.faire_tourner(61 * 60, pas=60)                                        # l'escalade part à l'utilisateur
    conn = ouvrir(banc.projet)
    try:
        hooks.signaler(conn, banc.projet, a=UTILISATEUR, objet=f"melange:{ASSISTANT}", resume="mélange")
        commandes.inscrire(conn, de=ASSISTANT, a=UTILISATEUR, nature="decision_utilisateur", resume="tranche le lot")
        assert [d["attendu"] for d in vue.dettes_de(conn, UTILISATEUR)] == ["decision"]
    finally:
        conn.close()


def _relances_a_utilisateur(banc, source):
    """Les relances à l'utilisateur qui renotifient l'attente `source` (objet `relance:<source>:<rang>`)."""
    return banc.prouve("SELECT id FROM messages WHERE de = 'cime' AND a = ? AND objet LIKE ? ORDER BY id",
                       (UTILISATEUR, f"relance:{source}:%"))


def test_relance_a_utilisateur_se_ferme_quand_il_tranche(banc):
    """Attente de décision : la renotification à 2 h est inscrite, reste ouverte tant que l'utilisateur ne
    tranche pas, puis la passe suivante la ferme (cause `relance-source`)."""
    d = envoyer(banc, ASSISTANT, UTILISATEUR, "decision_utilisateur", "tranche le lot")
    banc.faire_tourner(119 * 60, pas=60)                                       # 1 h 59 : rien encore
    assert _relances_a_utilisateur(banc, d) == []
    banc.faire_tourner(5 * 60, pas=60)                                         # 2 h : renotification
    [(rel,)] = _relances_a_utilisateur(banc, d)
    assert etat(banc, rel) == "inscrit"
    banc.faire_tourner(30 * 60, pas=60)                                        # décision encore ouverte
    assert etat(banc, rel) == "inscrit"
    assert banc.utilisateur().cime("repondre", str(d), "l'option B").code == 0      # l'utilisateur tranche
    banc.faire_tourner(60, pas=60)
    assert etat(banc, rel) == "abandonne"
    assert banc.prouve("SELECT preuve FROM transitions WHERE message_id = ? ORDER BY id DESC LIMIT 1",
                       (rel,)) == [('{"cause_disparue": "relance-source"}',)]
