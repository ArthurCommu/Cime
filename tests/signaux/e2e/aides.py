"""Aides communes aux cas du banc de bout en bout (acteurs, preuves SQL fréquentes)."""
from cime.fondation.registre import ouvrir  # noqa: F401  (réexporté aux cas)

ASSISTANT, COORD, COORD_B, W = "assistant", "coord-alpha", "coord-beta", "worker-alpha-t1"
BAIL = "SELECT count(*) FROM transitions WHERE etat = 'livre'"


def envoyer(banc, de, a, nature, resume, *extra):
    if nature == "consigne" and "--attend" not in extra:
        extra = ("--attend", "rien", *extra)
    r = banc.acteur(de).cime("envoyer", "--a", a, "--nature", nature, *extra, resume)
    assert r.code == 0, r.erreur
    return r.id


def accuser(banc, agent, texte):
    """Ce que Claude Code fait quand la ligne tapée est soumise : `UserPromptSubmit`."""
    return banc.acteur(agent).hook("UserPromptSubmit", {"prompt": texte})


def tape(banc) -> str:
    """Le dernier texte validé par `Enter` dans un terminal."""
    return banc.tmux.entrees[-1][1]


def frappes(banc):
    return [c for c in banc.tmux.commandes("facteur") if c[0] == "send-keys" and "-l" in c]


def etat(banc, identifiant) -> str:
    return banc.prouve("SELECT etat FROM transitions WHERE message_id = ? ORDER BY id DESC LIMIT 1",
                       (identifiant,))[0][0]


def rien_ecrit(banc, *agents) -> bool:
    """Variante oubli : l'acteur inerte n'a écrit aucune ligne `messages`."""
    marques = ",".join("?" for _ in agents)
    return banc.prouve(f"SELECT count(*) FROM messages WHERE de IN ({marques})", agents) == [(0,)]


def signalements(banc):
    return banc.prouve("SELECT a, objet FROM messages WHERE nature = 'signalement' ORDER BY id")


def minutes_apres(banc, reference: int, where: str, params=()):
    """Minutes écoulées entre le message `reference` et chaque message de la clause `where`."""
    return banc.prouve(
        "SELECT m.a, m.nature, round((julianday(m.horodatage) - julianday(r.horodatage)) * 1440)"
        f" FROM messages m, messages r WHERE r.id = ? AND ({where}) ORDER BY m.id",
        (reference, *params))


def nb_ecrits(banc, agent) -> int:
    return banc.prouve("SELECT count(*) FROM messages WHERE de = ?", (agent,))[0][0]
