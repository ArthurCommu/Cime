"""La vue « organigramme en temps réel » : fonctions pures,
en lecture seule du registre, utilisées par l'observation. Aucune n'écrit, aucune ne lit un
contenu privé (le `corps` d'un message n'en sort pas)."""
import json
from datetime import timedelta

FENETRE_ARETES = timedelta(minutes=15)

_DERNIERE = "(SELECT t.etat FROM transitions t WHERE t.message_id = m.id ORDER BY t.id DESC LIMIT 1)"


def _preuve(texte) -> dict:
    try:
        valeur = json.loads(texte) if texte else {}
    except (TypeError, ValueError):
        return {}
    return valeur if isinstance(valeur, dict) else {}


def _voie(voie_courrier, preuve) -> str | None:
    """La voie d'une transition : celle du courrier qui la porte, sinon celle que la preuve déclare."""
    if voie_courrier:
        return voie_courrier
    voie = _preuve(preuve).get("voie")
    return voie if isinstance(voie, str) else None


def _transitions_de(conn, ids) -> dict:
    """message_id -> [{etat, horodatage, voie, auteur}] dans l'ordre d'inscription."""
    resultat: dict = {i: [] for i in ids}
    if not ids:
        return resultat
    marques = ",".join("?" for _ in ids)
    for message_id, etat, horodatage, auteur, preuve, voie in conn.execute(
            f"SELECT t.message_id, t.etat, t.horodatage, t.auteur, t.preuve, c.voie"
            f" FROM transitions t LEFT JOIN courriers c ON c.id = t.courrier_id"
            f" WHERE t.message_id IN ({marques}) ORDER BY t.id", tuple(ids)):
        resultat[message_id].append({"etat": etat, "horodatage": horodatage,
                                     "voie": _voie(voie, preuve), "auteur": auteur})
    return resultat


def flux(conn, limite=200) -> list[dict]:
    """Les `limite` dernières requêtes (messages), de la plus ancienne à la plus récente."""
    lignes = conn.execute(
        "SELECT m.id, m.de, m.a, m.nature, m.objet, m.resume, o.debiteur, o.echeance"
        " FROM messages m LEFT JOIN obligations o ON o.message_id = m.id"
        " ORDER BY m.id DESC LIMIT ?", (limite,)).fetchall()
    lignes.reverse()
    transitions = _transitions_de(conn, [ligne[0] for ligne in lignes])
    resultat = []
    for ident, de, a, nature, objet, resume, debiteur, echeance in lignes:
        suite = transitions[ident]
        resultat.append({
            "id": ident, "de": de, "a": a, "nature": nature, "objet": objet, "resume": resume,
            "transitions": suite, "etat": suite[-1]["etat"] if suite else None,
            "debiteur": debiteur, "echeance": echeance})
    return resultat


def aretes(conn, maintenant) -> list[dict]:
    """Agrégat par couple (de, a) : de quoi tracer et épaissir chaque lien. Les couples sans
    aucune activité (rien en file, rien d'ouvert, rien dans les 15 dernières minutes) sont omis."""
    depuis = (maintenant - FENETRE_ARETES).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    lignes = conn.execute(
        f"SELECT m.de, m.a,"
        f" SUM({_DERNIERE} = 'inscrit'),"
        f" SUM({_DERNIERE} = 'livre'),"
        f" SUM(EXISTS (SELECT 1 FROM obligations o WHERE o.message_id = m.id AND o.etat = 'ouverte')),"
        f" SUM(m.horodatage >= ?)"
        f" FROM messages m GROUP BY m.de, m.a ORDER BY m.de, m.a", (depuis,)).fetchall()
    return [{"de": de, "a": a, "en_file": en_file or 0, "livre": livre or 0,
             "ouvertes": ouvertes or 0, "total_15min": total or 0}
            for de, a, en_file, livre, ouvertes, total in lignes
            if en_file or livre or ouvertes or total]


def file_de(conn, agent) -> list[dict]:
    """Messages en attente de livraison pour `agent` (dernière transition `inscrit`)."""
    return [{"id": i, "de": de, "nature": nature, "objet": objet, "resume": resume,
             "depuis": horodatage}
            for i, de, nature, objet, resume, horodatage in conn.execute(
                f"SELECT m.id, m.de, m.nature, m.objet, m.resume, m.horodatage FROM messages m"
                f" WHERE m.a = ? AND {_DERNIERE} = 'inscrit' ORDER BY m.id", (agent,))]


def dettes_de(conn, agent) -> list[dict]:
    """Obligations ouvertes dont `agent` est débiteur."""
    return [{"id": i, "attendu": attendu, "de": de, "objet": objet, "depuis": horodatage}
            for i, attendu, de, objet, horodatage in conn.execute(
                "SELECT m.id, o.attendu, m.de, m.objet, m.horodatage FROM obligations o"
                " JOIN messages m ON m.id = o.message_id"
                " WHERE o.debiteur = ? AND o.etat = 'ouverte' ORDER BY m.id", (agent,))]


def ordres(conn, limite=50) -> list[dict]:
    """Les `limite` derniers ordres sur terminal, du plus ancien au plus récent."""
    lignes = conn.execute(
        "SELECT id, auteur, verbe, cible, etat FROM ordres ORDER BY id DESC LIMIT ?",
        (limite,)).fetchall()
    lignes.reverse()
    return [{"id": i, "auteur": auteur, "verbe": verbe, "cible": cible, "etat": etat}
            for i, auteur, verbe, cible, etat in lignes]


def transitions_depuis(conn, depuis_id) -> list[dict]:
    """Les transitions d'`id` > `depuis_id` (l'`id` est monotone), avec de quoi les situer."""
    return [{"id": i, "message_id": mid, "etat": etat, "horodatage": horodatage,
             "voie": _voie(voie, preuve), "auteur": auteur, "de": de, "a": a,
             "nature": nature, "objet": objet}
            for i, mid, etat, horodatage, auteur, preuve, voie, de, a, nature, objet
            in conn.execute(
                "SELECT t.id, t.message_id, t.etat, t.horodatage, t.auteur, t.preuve, c.voie,"
                " m.de, m.a, m.nature, m.objet FROM transitions t"
                " JOIN messages m ON m.id = t.message_id"
                " LEFT JOIN courriers c ON c.id = t.courrier_id"
                " WHERE t.id > ? ORDER BY t.id", (int(depuis_id),))]
