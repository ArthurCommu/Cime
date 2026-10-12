"""Défauts trouvés à l'essai réel : chaque cas passe par le vrai chemin.

Ouverture : l'ouverture d'un coordinateur a son propre texte.
Consigne de tâche : la consigne de tâche d'un worker, inscrite par un vrai `cime lancer worker` (ordre exécuté par
le facteur du banc ; seul `lancer._lancer` est remplacé), doit pouvoir recevoir son `travail_pret`.
"""
from e2e.aides import ASSISTANT, COORD, W, minutes_apres, signalements
from e2e.test_complements import _lancer_coord
from e2e.test_commandes_garde_git import (_accord_de_lancement, faux_lancer,  # noqa: F401
                                          facteur_pendant_les_attentes, lancer_worker, ordres, tache)

ECHELLE = "m.de = 'cime' AND (m.objet LIKE 'relance:%' OR m.objet LIKE 'escalade:%')"


def _worker_lance(banc):
    """`coord-alpha` pose l'accord et lance le worker ; le worker reçoit sa consigne de tâche."""
    tache(banc)
    facteur_pendant_les_attentes(banc)
    _accord_de_lancement(banc)
    r = lancer_worker(banc)
    assert r.code == 0, r.erreur
    ((c, de),) = banc.prouve("SELECT id, de FROM messages WHERE objet = 'tache:alpha:t1'")
    assert de == COORD                                                   # inscrite au nom du coordinateur
    assert banc.prouve("SELECT json_extract(preuve, '$.cmd') FROM transitions WHERE message_id = ?"
                       " AND etat = 'inscrit'", (c,)) == [("lancer",)]
    banc.au_travail(W)
    banc.acteur(W).hook("PostToolUse", {"tool_name": "Bash"})            # la consigne lui est rendue
    return c


def test_consigne_de_tache_normal(banc, faux_lancer):  # noqa: F811
    c = _worker_lance(banc)
    r = banc.acteur(W).cime("repondre", str(c), "--nature", "travail_pret", "tâche terminée")
    assert r.code == 0, r.erreur
    assert banc.prouve("SELECT etat FROM obligations WHERE message_id = ?", (c,)) == [("satisfaite",)]
    assert banc.prouve("SELECT de, a, nature, en_reponse_a FROM messages WHERE nature = 'travail_pret'"
                       ) == [(W, COORD, "travail_pret", c)]
    assert banc.acteur(W).hook("Stop", {"stop_hook_active": False}).code == 0   # rien ne lui est dû
    (banc.projet / ".orga/teams/alpha/reports" / f"{W}-2026-10-10.md").write_text("rapport\n")
    (banc.projet / ".orga/teams/alpha/conversations/t1-synthese.md").write_text("synthèse\n")
    fin = banc.acteur(COORD).cime("terminer", "worker", "alpha", "t1")
    assert fin.code == 0, fin.erreur
    assert (banc.projet / ".orga/teams/alpha/tasks/done/t1.md").exists()
    assert signalements(banc) == []


def test_consigne_de_tache_oubli(banc, faux_lancer):  # noqa: F811
    """Le worker ne rend rien : comme pour un `travail_pret` jamais rendu, à partir de la consigne réelle (fin-sans-suite puis escalade)."""
    c = _worker_lance(banc)
    assert banc.acteur(W).inerte().cime("repondre", str(c), "x") is None
    premier = banc.acteur(W).hook("Stop", {"stop_hook_active": False, "last_assistant_message": "fini"})
    assert premier.code == 2 and "Tu dois encore" in premier.stderr and signalements(banc) == []
    second = banc.acteur(W).hook("Stop", {"stop_hook_active": True, "last_assistant_message": "fini"})
    assert second.code == 0
    assert signalements(banc) == [(COORD, f"fin-sans-suite:{W}:{c}")]
    s = banc.prouve("SELECT id FROM messages WHERE nature = 'signalement'")[0][0]
    banc.faire_tourner(31 * 60, pas=60)
    assert minutes_apres(banc, s, ECHELLE) == [(ASSISTANT, "signalement", 10.0), ("utilisateur", "signalement", 30.0)]
    assert banc.prouve("SELECT etat FROM obligations WHERE message_id = ?", (c,)) == [("ouverte",)]


# --- la consigne d'ouverture n'est pas l'invite initiale --------------------------------------------

def test_ouverture_distincte_de_l_invite_initiale(banc, faux_lancer):  # noqa: F811
    from cime.fondation import lancer
    facteur_pendant_les_attentes(banc)
    assert _lancer_coord(banc).code == 0
    ((ident, resume),) = banc.prouve("SELECT id, resume FROM messages WHERE objet = 'ouverture'")
    assert resume != lancer.MESSAGE_COORDINATEUR
    assert resume == f"Cime : ouverture enregistrée (#{ident}) — accuse réception par ton prochain tour." \
        and len(resume) <= 100
    banc.tmux.repos(COORD)
    stop = banc.acteur(COORD).hook("Stop", {"stop_hook_active": False})   # le message lui est rendu à l'arrêt
    assert resume in stop.stderr and lancer.MESSAGE_COORDINATEUR not in stop.stderr
    banc.au_travail(COORD)
    banc.acteur(COORD).hook("PostToolUse", {"tool_name": "Bash"})        # son tour suivant vaut accusé
    assert banc.prouve("SELECT etat FROM obligations WHERE message_id = ?", (ident,)) == [("satisfaite",)]


# --- aucune relance de dette à l'Assistant ------------------------------------------------------------

DETTES = "SELECT a, nature, objet FROM messages WHERE de = 'cime' AND objet LIKE 'dette:%' ORDER BY id"


def test_pas_de_relance_de_dette_a_l_assistant(banc):
    from e2e.aides import envoyer
    banc.au_repos(ASSISTANT)
    envoyer(banc, "utilisateur", ASSISTANT, "consigne", "demande de la page", "--attend", "reponse",
            "--objet", "demande-page")
    banc.au_repos(ASSISTANT)
    banc.faire_tourner(2 * 3600, pas=60)
    assert banc.prouve(DETTES) == []
    assert banc.prouve("SELECT count(*) FROM messages WHERE nature = 'relance' AND a = ?", (ASSISTANT,)) == [(0,)]


def test_controle_un_coordinateur_est_relance(banc):
    from e2e.aides import envoyer
    banc.au_repos(COORD)
    envoyer(banc, ASSISTANT, COORD, "consigne", "dis-moi où en est le lot", "--attend", "reponse")
    banc.au_repos(COORD)
    banc.faire_tourner(30 * 60, pas=60)
    assert [(a, n) for a, n, _ in banc.prouve(DETTES)][:1] == [(COORD, "relance")]


# --- un seul fin-sans-suite par worker et par obligation, une fois pour toutes -----------------------------------------

def fins(banc):
    return banc.prouve("SELECT a, objet FROM messages WHERE objet LIKE 'fin-sans-suite:%' ORDER BY id")


def test_sept_arrets_un_seul_signalement(banc, faux_lancer):  # noqa: F811
    c = _worker_lance(banc)
    arret = {"stop_hook_active": True, "last_assistant_message": "fini"}
    objet = f"fin-sans-suite:{W}:{c}"
    banc.acteur(W).hook("Stop", {"stop_hook_active": False, "last_assistant_message": "fini"})
    for i in range(7):
        banc.horloge.avance(seconds=90)
        banc.facteur_tour()
        banc.acteur(W).hook("Stop", arret)
        if i == 2:                                       # le coordinateur le reçoit (accusé) : toujours un seul
            banc.au_travail(COORD)
            banc.acteur(COORD).hook("PostToolUse", {"tool_name": "Bash"})
    assert fins(banc) == [(COORD, objet)]
    assert banc.prouve("SELECT count(*) FROM messages WHERE objet = ? AND (SELECT etat FROM transitions t"
                       " WHERE t.message_id = messages.id ORDER BY t.id DESC LIMIT 1) != 'clos'", (objet,)) == [(1,)]
    # le coordinateur a fini son tour (signalement clos) : un nouvel arrêt n'en inscrit toujours pas
    # d'autre — essai réel du 10/10 : le coord, toujours actif, closait chaque signalement aussitôt
    banc.acteur(COORD).hook("Stop", {"stop_hook_active": False})
    banc.acteur(W).hook("Stop", arret)
    assert fins(banc) == [(COORD, objet)]
