"""Les demandes d'autorisation par classe : ce que le hook, `cime
accorder|refuser`, le moteur des échéances et la fermeture des signalements à l'utilisateur ont en commun.

Le mode autonome se lit à chaque appel (`fusions_auto.etat_courant`), jamais figé : « actif » =
`active` et non `suspendue` ; toute erreur de lecture vaut inactif.
"""
import json

from cime.fondation import fusions_auto
from cime.signaux import echeances

PREFIXE = "autorisation:"
PREFIXE_RESERVEE = "autorisation-reservee:"   # information au supérieur d'une demande `reserve`
PREFIXE_ANNONCE = "autorisation-auto:"        # accord de l'Assistant en mode autonome
CIBLE_MAX = 200
RESUME_MAX = 160
# Ce qui dit que l'agent n'attend plus sur son menu : son tour a fini, ou sa session.
EVENEMENTS_DE_SUITE = ("Stop", "UserPromptSubmit", "SessionStart", "SessionEnd")


def mode_actif(projet) -> bool:
    try:
        etat = fusions_auto.etat_courant(projet)
        return bool(etat.get("active")) and not bool(etat.get("suspendue"))
    except Exception:
        return False


def tronquer(texte: str, n: int) -> str:
    texte = " ".join(str(texte).split())
    return texte if len(texte) <= n else texte[:n - 1] + "…"


def cible_outil(tool_input) -> str:
    """La commande, le chemin ou l'URL de la demande (≤ 200 caractères), comme l'hôte."""
    if isinstance(tool_input, dict):
        for cle in ("command", "file_path", "notebook_path", "url", "path", "pattern", "query"):
            valeur = tool_input.get(cle)
            if isinstance(valeur, str) and valeur:
                return valeur[:CIBLE_MAX]
    return ""


def corps(outil: str, cible: str, classement: dict) -> str:
    return json.dumps({"outil": outil, "cible": cible, "classe": classement["classe"],
                       "theme": classement["theme"]}, ensure_ascii=False)


def classe_de(message_corps) -> tuple[str, str]:
    """(classe, thème) d'un signalement ; sans classe lisible : `reserve` (« dans le doute »)."""
    donnees = echeances.corps_autorisation(message_corps)
    if donnees is None:
        return "reserve", "classe illisible"
    return donnees["classe"], str(donnees.get("theme") or "?")


def agent_de(conn, demande_id: str) -> str | None:
    ligne = conn.execute(
        "SELECT agent FROM evenements WHERE evenement = 'PermissionRequest'"
        " AND json_extract(details, '$.demande_id') = ? ORDER BY id LIMIT 1", (demande_id,)).fetchone()
    return ligne[0] if ligne else None


def tranchee(conn, demande_id: str, depuis: str) -> bool:
    """La demande n'attend plus : un `accord`/`refus` inscrit, une réponse de la page (journal
    `perm-<id>` réussi, ou signalement clos par l'hôte), ou l'agent a repris (fin de tour, nouvelle
    session) depuis `depuis`."""
    objet = PREFIXE + demande_id
    if conn.execute("SELECT 1 FROM messages WHERE nature IN ('accord', 'refus') AND objet = ? LIMIT 1",
                    (objet,)).fetchone():
        return True
    if conn.execute("SELECT 1 FROM journal WHERE cible = ? AND action IN ('autoriser', 'refuser')"
                    " AND resultat = 'ok' LIMIT 1", ("perm-" + demande_id,)).fetchone():
        return True
    if conn.execute("SELECT 1 FROM transitions t JOIN messages m ON m.id = t.message_id"
                    " WHERE m.objet = ? AND json_extract(t.preuve, '$.par_autorisation') IS NOT NULL"
                    " LIMIT 1", (objet,)).fetchone():
        return True
    agent = agent_de(conn, demande_id)
    if agent is None:
        return False
    marques = ",".join("?" for _ in EVENEMENTS_DE_SUITE)
    return conn.execute(
        f"SELECT 1 FROM evenements WHERE agent = ? AND horodatage > ? AND evenement IN ({marques})"
        " LIMIT 1", (agent, depuis, *EVENEMENTS_DE_SUITE)).fetchone() is not None
