"""Un message remis par un hook n'est jamais relivré parce que son courrier a expiré pendant un tour long.

Règle : un courrier de voie `hook:*` dont le bail est passé reste ouvert (bail renouvelé) tant que l'agent n'a
émis aucun événement de tour postérieur à sa création, ni `SessionStart`, `SessionEnd` ou `idle_prompt` ; pour
`hook:Stop` seulement, au plus `COURRIER_STOP_PLAFOND_S` secondes. Horloge simulée, vrais hooks, vrai facteur.
"""
from e2e.aides import ASSISTANT, COORD, envoyer, etat, frappes, tape


def _remettre(banc, evenement, entree, texte):
    """Un message remis par le hook `evenement` : courrier `hook:<evenement>` ouvert, message `livre` par ce courrier."""
    m = envoyer(banc, ASSISTANT, COORD, "consigne", texte)
    r = banc.acteur(COORD).hook(evenement, entree)
    assert r.code == 2 and texte in r.stderr, (r.code, r.stderr)
    return m


def _livraisons(banc, message_id) -> int:
    return banc.prouve("SELECT count(*) FROM transitions WHERE message_id = ? AND etat = 'livre'",
                       (message_id,))[0][0]


def _etat_courrier(banc, voie) -> str:
    return banc.prouve("SELECT etat FROM courriers WHERE a = ? AND voie = ? ORDER BY id DESC LIMIT 1",
                       (COORD, voie))[0][0]


def test_a_post_tool_use_relu_apres_bail_n_est_livre_qu_une_fois(banc):
    banc.au_travail(COORD)
    banc.facteur_tour()
    m = _remettre(banc, "PostToolUse", {"tool_name": "Bash"}, "consigne en plein tour")
    banc.horloge.avance(seconds=150)                       # outil long : aucun événement pendant 150 s
    banc.facteur_tour()                                    # l'agent est en plein tour : rien ne se tape
    assert frappes(banc) == []
    assert banc.acteur(COORD).hook("PostToolUse", {"tool_name": "Bash"}).code == 0   # le tour finit : accusé
    assert _livraisons(banc, m) == 1
    assert frappes(banc) == []
    assert etat(banc, m) in ("pris_en_compte", "clos")


def test_b_stop_relu_apres_bail_n_est_livre_qu_une_fois(banc):
    banc.au_repos(COORD)
    banc.facteur_tour()
    m = _remettre(banc, "Stop", {"stop_hook_active": False}, "consigne remise par Stop")
    banc.tmux.repos(COORD)
    banc.horloge.avance(seconds=150)
    banc.facteur_tour()                                    # 150 s < plafond du Stop : pas refermé, rien tapé
    assert frappes(banc) == []
    banc.acteur(COORD).hook("Stop", {"stop_hook_active": False})   # l'agent repart puis s'arrête : accusé
    assert _livraisons(banc, m) == 1
    assert frappes(banc) == []
    assert etat(banc, m) in ("pris_en_compte", "clos")


def test_c_stop_sans_suite_est_referme_au_plafond_et_retape(banc):
    banc.au_repos(COORD)
    banc.facteur_tour()
    m = _remettre(banc, "Stop", {"stop_hook_active": False}, "consigne sans suite")
    banc.tmux.repos(COORD)
    banc.faire_tourner(200, pas=30)                        # aucun événement : bail renouvelé, sous le plafond
    assert _etat_courrier(banc, "hook:Stop") == "ouvert" and frappes(banc) == []
    banc.faire_tourner(200, pas=30)                        # 400 s : passé le plafond (300 s), refermé
    assert _etat_courrier(banc, "hook:Stop") == "echoue"
    assert _livraisons(banc, m) == 2                       # le hook, puis le facteur
    assert len(frappes(banc)) == 1 and "consigne sans suite" in tape(banc)


def test_d_post_tool_use_puis_idle_prompt_est_referme_et_retape(banc):
    banc.au_travail(COORD)
    banc.facteur_tour()
    m = _remettre(banc, "PostToolUse", {"tool_name": "Bash"}, "consigne suivie d'un repos")
    banc.horloge.avance(seconds=5)
    banc.au_repos(COORD, par="idle")                       # idle_prompt : l'agent est au repos, prouvé
    banc.horloge.avance(seconds=145)
    banc.facteur_tour()
    assert _etat_courrier(banc, "hook:PostToolUse") == "echoue"
    assert len(frappes(banc)) == 1 and "consigne suivie d'un repos" in tape(banc)
    assert _livraisons(banc, m) == 2


def test_e_post_tool_use_puis_session_start_est_referme(banc):
    banc.au_travail(COORD)
    banc.facteur_tour()
    m = _remettre(banc, "PostToolUse", {"tool_name": "Bash"}, "consigne avant nouvelle session")
    banc.horloge.avance(seconds=5)
    assert banc.acteur(COORD).hook("SessionStart", {"source": "startup"}).code == 0
    banc.tmux.repos(COORD)
    banc.horloge.avance(seconds=145)
    banc.facteur_tour()
    assert _etat_courrier(banc, "hook:PostToolUse") == "echoue"
    assert len(frappes(banc)) == 1 and "consigne avant nouvelle session" in tape(banc)
    assert _livraisons(banc, m) == 2
