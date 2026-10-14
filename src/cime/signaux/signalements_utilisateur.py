"""Les signalements adressés à l'utilisateur.

Un `signalement` dont le destinataire est `utilisateur` n'ouvre aucune obligation : ni accusé, ni relance,
ni escalade, ni dette. Il est livré par l'hôte et reste visible tant que sa cause existe. Cime le clôt
elle-même, avec la preuve `{"cause_disparue": "<cause>"}` :

- `clore` (une passe du facteur, après les relances) : quand la cause a disparu, ou à 2 h
  (`SIGNALEMENT_UTILISATEUR_PLAFOND`) même si elle dure, sauf `facteur-arrete` (`vie.clore_signalements_arret`) ;
- `solder` (une fois, au démarrage du facteur) : les obligations de l'utilisateur sur des signalements, nées avant
  l'existence de ces signalements sans obligation, passent `abandonnee`. Les attentes réelles de l'utilisateur ne sont jamais touchées.

Une `relance` adressée à `utilisateur` (renotification d'une attente, objet `relance:<m>:<rang>`) se ferme de la
même façon : cause `relance-source` quand l'obligation du message `<m>` n'est plus ouverte, sinon le plafond.

Un message encore `inscrit` (l'hôte ne l'a pas notifié) se ferme `abandonne`, comme à l'arrêt du facteur ;
un message `livre` se ferme `clos`.
"""
import json

from cime.fondation.projet import ErreurProjet, equipe_de
from cime.fondation.registre import horodatage, inscrire_transition, ouvrir
from cime.signaux import autorisations, echeances, obligations

UTILISATEUR = "utilisateur"
MOTIF_SOLDE = "signalement-sans-obligation"
# Dernière transition du message m : son état courant
_DERNIERE = "(SELECT t.etat FROM transitions t WHERE t.message_id = m.id ORDER BY t.id DESC LIMIT 1)"
_FERMES = ("clos", "abandonne", "echec")
_OUVERTS = (f"SELECT m.id, m.objet, m.horodatage, {_DERNIERE} FROM messages m"
            " WHERE m.nature IN ('signalement', 'relance') AND m.a = 'utilisateur' AND m.objet IS NOT NULL"
            " AND m.objet != 'facteur-arrete'"
            f" AND {_DERNIERE} NOT IN ('clos', 'abandonne', 'echec') ORDER BY m.id")
# Objets dont la cause est la vie de l'agent : son prochain UserPromptSubmit ou Stop la lève
_CAUSES_VIVANTES = ("erreur-api:", "melange:", "collision-invite:", "invite-non-validee:", "occupe:",
                    "session-absente:", "fenetre-bloquante:")


def _evenement_apres(conn, agent, depuis, noms, source=None) -> bool:
    """Un événement de `agent` parmi `noms`, postérieur à `depuis` (et de `source` si elle est donnée)."""
    marques = ",".join("?" for _ in noms)
    requete = (f"SELECT 1 FROM evenements WHERE agent = ? AND horodatage > ?"
               f" AND evenement IN ({marques})")
    params = [agent, depuis, *noms]
    if source is not None:
        requete += " AND json_extract(details, '$.source') = ?"
        params.append(source)
    return conn.execute(requete + " LIMIT 1", params).fetchone() is not None


def _equipe_terminee(conn, projet, agent, depuis) -> bool:
    """La clôture de l'équipe de `agent` (événement `Cloture`, écrit avec `CLOTUREE`) est postérieure."""
    try:
        equipe = equipe_de(projet, agent)
    except ErreurProjet:
        return False
    if not equipe:
        return False
    return conn.execute(
        "SELECT 1 FROM evenements WHERE evenement = 'Cloture' AND horodatage > ?"
        " AND json_extract(details, '$.equipe') = ? LIMIT 1", (depuis, equipe)).fetchone() is not None


def _cause(conn, projet, objet, depuis):
    """Le nom de la cause de `objet` si elle a disparu depuis `depuis` (l'inscription), sinon None."""
    if objet.startswith(autorisations.PREFIXE):
        return "autorisation-tranchee" if autorisations.tranchee(
            conn, objet[len(autorisations.PREFIXE):], depuis) else None
    if objet.startswith("escalade:"):
        message = objet.split(":")[1]
        if not message.isdigit():
            return None
        origine = conn.execute("SELECT a, objet, horodatage FROM messages WHERE id = ?",
                               (int(message),)).fetchone()
        if origine and origine[0] == UTILISATEUR and (origine[1] or "").startswith(autorisations.PREFIXE):
            # une demande adressée à l'utilisateur n'a pas d'obligation : sa fin est la décision
            return "autorisation-tranchee" if autorisations.tranchee(
                conn, origine[1][len(autorisations.PREFIXE):], origine[2]) else None
        return "escalade" if obligations.ouverte_pour(conn, int(message)) is None else None
    if objet.startswith("fin-sans-suite:"):
        agent, _, message = objet[len("fin-sans-suite:"):].rpartition(":")
        if message.isdigit() and obligations.ouverte_pour(conn, int(message)) is None:
            return "fin-sans-suite"
        return "equipe-terminee" if _equipe_terminee(conn, projet, agent, depuis) else None
    if objet.startswith("session-disparue:"):
        agent = objet.split(":", 1)[1]
        if _evenement_apres(conn, agent, depuis, ("SessionStart",)):
            return "session-disparue"
        return "equipe-terminee" if _equipe_terminee(conn, projet, agent, depuis) else None
    for prefixe in _CAUSES_VIVANTES:
        if objet.startswith(prefixe):
            agent = objet[len(prefixe):]
            return "agent-vivant" if _evenement_apres(conn, agent, depuis, ("UserPromptSubmit", "Stop")) else None
    if objet.startswith("contexte:"):
        agent = objet.split(":", 1)[1]
        if _evenement_apres(conn, agent, depuis, ("PostCompact",)) \
                or _evenement_apres(conn, agent, depuis, ("SessionStart",), source="compact"):
            return "compactage"
    if objet.startswith("relance:"):
        parties = objet.split(":")
        if len(parties) == 3 and parties[1].isdigit():
            return "relance-source" if obligations.ouverte_pour(conn, int(parties[1])) is None else None
        return None      # une autre relance à l'utilisateur : le plafond la ferme
    return None      # toute autre cause n'est pas mesurable dans le registre : le plafond la ferme


def _fermer(conn, message_id, etat, cause) -> None:
    """Ferme un signalement à l'utilisateur (sans commit : l'appelant tient la transaction)."""
    conn.execute("UPDATE obligations SET etat = 'abandonnee' WHERE message_id = ? AND etat = 'ouverte'",
                 (message_id,))
    inscrire_transition(conn, message_id, "abandonne" if etat == "inscrit" else "clos", "cime",
                        {"cause_disparue": cause}, commit=False)


def clore(conn, projet, maintenant) -> int:
    """La passe de fermeture : chaque signalement à l'utilisateur encore ouvert dont la cause a disparu, ou qui
    atteint le plafond de 2 h, est fermé. Renvoie le nombre fermé."""
    fermes = 0
    with conn:
        for message_id, objet, depuis, etat in conn.execute(_OUVERTS).fetchall():
            cause = _cause(conn, projet, objet, depuis)
            if cause is None and maintenant - echeances._lire(depuis) >= echeances.SIGNALEMENT_UTILISATEUR_PLAFOND:
                cause = "echeance"
            if cause is None:
                continue
            _fermer(conn, message_id, etat, cause)
            fermes += 1
    return fermes


def solder(projet) -> int:
    """Une fois, au démarrage du facteur : les obligations `ouvertes` de l'utilisateur sur un signalement passent
    `abandonnee` (sans `ferme_par`), chacune journalisée dans `journal`. Si la cause a déjà disparu, le
    message est fermé. Idempotent : un second démarrage ne trouve plus rien. Renvoie le nombre soldé."""
    conn = ouvrir(projet)
    soldees = 0
    try:
        with conn:
            lignes = conn.execute(
                f"SELECT o.message_id, m.objet, m.horodatage, {_DERNIERE} FROM obligations o"
                " JOIN messages m ON m.id = o.message_id"
                " WHERE o.etat = 'ouverte' AND o.debiteur = 'utilisateur' AND m.nature = 'signalement'"
                " ORDER BY o.message_id").fetchall()
            for message_id, objet, depuis, etat in lignes:
                conn.execute("UPDATE obligations SET etat = 'abandonnee', ferme_par = NULL"
                             " WHERE message_id = ? AND etat = 'ouverte'", (message_id,))
                conn.execute(
                    "INSERT INTO journal (horodatage, auteur, action, cible, details, resultat)"
                    " VALUES (?, 'cime', 'solder', ?, ?, 'ok')",
                    (horodatage(), f"msg-{message_id}",
                     json.dumps({"motif": MOTIF_SOLDE}, ensure_ascii=False)))
                soldees += 1
                cause = _cause(conn, projet, objet, depuis) if etat not in _FERMES else None
                if cause is not None:
                    _fermer(conn, message_id, etat, cause)
    finally:
        conn.close()
    return soldees
