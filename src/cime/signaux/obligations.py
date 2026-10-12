"""Les obligations : ce qu'un agent doit à un message, ouvertes, satisfaites, repoussées ou abandonnées."""
from cime.fondation.registre import inscrire_transition


def ouvrir_obligation(conn, message_id, debiteur, attendu, echeance=None, commit=True) -> int:
    cur = conn.execute(
        "INSERT INTO obligations (message_id, debiteur, attendu, echeance, etat)"
        " VALUES (?, ?, ?, ?, 'ouverte')", (message_id, debiteur, attendu, echeance))
    if commit:
        conn.commit()
    return cur.lastrowid


def satisfaire(conn, message_id, ferme_par, commit=True) -> bool:
    """Ferme l'obligation ouverte du message ; False si elle n'existait pas ou était déjà fermée."""
    cur = conn.execute(
        "UPDATE obligations SET etat = 'satisfaite', ferme_par = ?"
        " WHERE message_id = ? AND etat = 'ouverte'", (ferme_par, message_id))
    if commit:
        conn.commit()
    return cur.rowcount == 1


def repousser(conn, message_id, echeance, commit=True) -> bool:
    cur = conn.execute(
        "UPDATE obligations SET echeance = ? WHERE message_id = ? AND etat = 'ouverte'",
        (echeance, message_id))
    if commit:
        conn.commit()
    return cur.rowcount == 1


def ouverte_pour(conn, message_id):
    """(debiteur, attendu, echeance) de l'obligation ouverte du message, ou None."""
    return conn.execute(
        "SELECT debiteur, attendu, echeance FROM obligations"
        " WHERE message_id = ? AND etat = 'ouverte'", (message_id,)).fetchone()


def ouvertes_de(conn, debiteur) -> list[dict]:
    lignes = conn.execute(
        "SELECT o.id, o.message_id, o.attendu, o.echeance, m.horodatage, m.de, m.nature,"
        " m.resume FROM obligations o JOIN messages m ON m.id = o.message_id"
        " WHERE o.debiteur = ? AND o.etat = 'ouverte' ORDER BY o.message_id",
        (debiteur,)).fetchall()
    cles = ("id", "message_id", "attendu", "echeance", "horodatage", "de", "nature", "resume")
    return [dict(zip(cles, ligne)) for ligne in lignes]


def abandonner_equipe(conn, equipe, auteur, evenement_id, autres=(), commit=True) -> list[int]:
    """La clôture d'une équipe abandonne toutes les obligations ouvertes dont le débiteur est de
    l'équipe (son coordinateur et ses workers). Pour chacune : obligation `abandonnee`, message en
    transition `abandonne` de preuve `{"cloture": équipe, "par_evenement": <id de la clôture>}`.
    `autres` : équipes dont le nom commence par `<équipe>-` (leurs workers ne sont pas les siens).
    À appeler dans la transaction qui écrit `CLOTUREE` (`commit=False`). Rend les messages abandonnés."""
    debiteurs = conn.execute(
        "SELECT message_id, debiteur FROM obligations WHERE etat = 'ouverte' AND"
        " (debiteur = ? OR debiteur LIKE ?) ORDER BY message_id",
        (f"coord-{equipe}", f"worker-{equipe}-%")).fetchall()
    ecartes = tuple(f"worker-{a}-" for a in autres)
    abandonnes = [m for m, d in debiteurs if not d.startswith(ecartes)]
    for message_id in abandonnes:
        conn.execute("UPDATE obligations SET etat = 'abandonnee', ferme_par = ?"
                     " WHERE message_id = ? AND etat = 'ouverte'", (evenement_id, message_id))
        inscrire_transition(conn, message_id, "abandonne", auteur,
                            {"cloture": equipe, "par_evenement": evenement_id}, commit=False)
    if commit:
        conn.commit()
    return abandonnes


def abandonner_inscrits_de(conn, agent, auteur, cause, commit=True) -> list[int]:
    """Les messages encore `inscrit` (dernière transition) adressés à `agent`, qui ne les
    lira jamais (session fermée), passent `abandonne` de preuve `{"cause": cause}` ; leur obligation
    ouverte est `abandonnee`. Les messages `livre` ou plus avancés ne sont pas touchés."""
    messages = [m for (m,) in conn.execute(
        "SELECT m.id FROM messages m WHERE m.a = ? AND (SELECT t.etat FROM transitions t"
        " WHERE t.message_id = m.id ORDER BY t.id DESC LIMIT 1) = 'inscrit' ORDER BY m.id",
        (agent,)).fetchall()]
    for message_id in messages:
        conn.execute("UPDATE obligations SET etat = 'abandonnee' WHERE message_id = ? AND etat = 'ouverte'",
                     (message_id,))
        inscrire_transition(conn, message_id, "abandonne", auteur, {"cause": cause}, commit=False)
    if commit:
        conn.commit()
    return messages
