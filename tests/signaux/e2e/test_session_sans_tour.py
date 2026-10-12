"""Un `SessionStart` qui n'ouvre pas de tour ne vaut pas livraison : vrai chemin, faux tmux, horloge simulée.

Un coordinateur compacte son contexte au repos : Claude Code émet un `SessionStart` de source `compact`,
sans tour. Avant la correction, le hook `SessionStart` prenait le courrier et l'acquittait aussitôt, alors que
l'agent n'avait rien lu. Désormais, un `SessionStart` de source `compact`, `resume` ou `clear` ne prend rien :
le facteur tape à l'invite quand l'agent est au repos, ou le hook `PostToolUse`/`Stop` remet le texte si un
tour est en cours."""
import pytest

from e2e.aides import ASSISTANT, COORD, envoyer, etat, frappes


SOURCES_SANS_TOUR = ("compact", "resume", "clear")


def _session(banc, source):
    return banc.acteur(COORD).hook("SessionStart", {"source": source, "model": "claude-sonnet-5-5"})


def _remis_par_le_hook(r) -> bool:
    return "Courrier remis" in r.stdout


@pytest.mark.parametrize("source", SOURCES_SANS_TOUR)
def test_session_sans_tour_ne_prend_pas_le_courrier_le_facteur_le_tape_au_repos(banc, source):
    banc.au_repos(COORD)
    m = envoyer(banc, ASSISTANT, COORD, "consigne", "regarde les captures")
    r = _session(banc, source)
    assert not _remis_par_le_hook(r)
    assert etat(banc, m) == "inscrit" and banc.prouve("SELECT count(*) FROM courriers") == [(0,)]
    banc.tmux.repos(COORD)
    banc.faire_tourner(120, pas=10, jusqu_a=lambda: etat(banc, m) != "inscrit")
    assert len(frappes(banc)) == 1 and etat(banc, m) == "livre"


def test_session_startup_prend_toujours_le_courrier(banc):
    """Lancement neuf (source `startup`, comme sans source) : comportement inchangé."""
    banc.au_repos(COORD)
    m = envoyer(banc, ASSISTANT, COORD, "consigne", "bienvenue")
    r = banc.acteur(COORD).hook("SessionStart", {"source": "startup"})
    assert _remis_par_le_hook(r) and etat(banc, m) in ("livre", "clos")


def test_session_sans_source_prend_toujours_le_courrier(banc):
    banc.au_repos(COORD)
    m = envoyer(banc, ASSISTANT, COORD, "consigne", "bienvenue")
    r = banc.acteur(COORD).hook("SessionStart", {})
    assert _remis_par_le_hook(r) and etat(banc, m) in ("livre", "clos")


def test_compactage_en_plein_tour_remis_par_posttooluse_jamais_tape_deux_fois(banc):
    banc.au_travail(COORD)                                          # UserPromptSubmit : tour en cours
    m = envoyer(banc, ASSISTANT, COORD, "consigne", "regarde les captures")
    r = _session(banc, "compact")
    assert not _remis_par_le_hook(r) and etat(banc, m) == "inscrit"
    r = banc.acteur(COORD).hook("PostToolUse", {"tool_name": "Bash"})
    assert "regarde les captures" in (r.stdout + r.stderr)          # remis par le hook, pas par le facteur
    assert etat(banc, m) != "inscrit"
    banc.faire_tourner(120, pas=10)
    banc.au_repos(COORD)
    banc.faire_tourner(120, pas=10)
    assert frappes(banc) == [] and banc.tmux.entrees == []


def test_reste_d_invite_apres_echoue_efface_puis_nouveau_message_tape(banc):
    """Le scénario réel de la nuit : le texte d'un courrier `echoue` est resté à l'invite,
    sans Enter (une collision a fermé le courrier) ; le facteur redémarre ; un coordinateur compacte au
    repos ; un nouveau message arrive. Le facteur efface le reste et tape le nouveau message, une fois."""
    banc.au_repos(COORD)
    premier = envoyer(banc, ASSISTANT, COORD, "consigne", "premier")
    banc.tmux.injecter_apres_frappe("x")                            # l'utilisateur tape pendant la frappe
    banc.faire_tourner(60, pas=10)
    assert banc.prouve("SELECT etat FROM courriers ORDER BY id DESC LIMIT 1") == [("echoue",)]
    assert banc.tmux.entrees == [] and etat(banc, premier) == "inscrit"
    residu = banc.tmux.invite_de(COORD)[:-1]                        # le texte du facteur, sans le « x »
    banc.tmux.brouillon(COORD, residu)                              # l'utilisateur efface le « x » ; le texte reste
    banc.nouveau_facteur()
    second = envoyer(banc, ASSISTANT, COORD, "consigne", "second")  # arrivé avant le compactage
    assert not _remis_par_le_hook(_session(banc, "compact"))
    banc.faire_tourner(120, pas=10, jusqu_a=lambda: etat(banc, second) != "inscrit")
    assert len(banc.tmux.entrees) == 1 and "second" in banc.tmux.entrees[0][1]
    assert etat(banc, second) == "livre" and banc.tmux.invite_de(COORD) == ""
