"""Le moteur des échéances, relances et escalades.

Entièrement piloté par `echeances.ECHELLES` : ce module ne contient aucun délai. À chaque tour
du facteur, pour chaque obligation `ouverte` dont l'étape suivante est échue, il inscrit un
message `relance` (Cime → débiteur) ou un `signalement` d'escalade, et avance `relances` /
`prochaine` dans la même transaction. Chaîne : worker → coordinateur → Assistant → l'utilisateur.
Idempotent : la clé de chaque message est (obligation, rang) — `objet` — et l'avance est gardée
par `WHERE relances = <rang>`.
"""
from datetime import datetime

from cime.fondation.projet import ErreurProjet
from cime.fondation.registre import ouvrir
from cime.signaux import autorisations, commandes, echeances, livraison, repos
from cime.signaux.echeances import Etape

UTILISATEUR = "utilisateur"
ASSISTANT = "assistant"
LIBELLES = {"reponse": "répondu", "accord": "accordé ou refusé", "revue": "traité le travail rendu",
            "rapport_utilisateur": "rendu son rapport", "decision": "tranché", "lu": "lu",
            "accuse": "accusé réception", "travail_pret": "rendu son travail",
            "action": "exécuté les suites de la fusion"}


def _sup(identite, projet):
    if identite in (UTILISATEUR, "cime") or not identite:
        return None
    try:
        return livraison.superieur(identite, projet)
    except ErreurProjet:
        return None


def resoudre(cible, debiteur, projet) -> str | None:
    """Qui reçoit : la cible de l'étape, relativement au débiteur. Au-delà de l'Assistant,
    c'est toujours l'utilisateur ; None si le débiteur n'a pas de supérieur connu."""
    if cible == "debiteur":
        return debiteur
    if cible == "utilisateur":
        return UTILISATEUR
    if cible == "assistant":
        return ASSISTANT
    sup = _sup(debiteur, projet) or (UTILISATEUR if debiteur != UTILISATEUR else None)
    if cible == "sup":
        return sup
    if cible == "supsup":
        return (_sup(sup, projet) or UTILISATEUR) if sup and sup != UTILISATEUR else sup
    raise ValueError(f"cible inconnue : {cible!r}")


def _existe(conn, objet, a) -> bool:
    return conn.execute("SELECT 1 FROM messages WHERE de = 'cime' AND a = ? AND objet = ?",
                        (a, objet)).fetchone() is not None


def _age(maintenant: datetime, iso: str) -> str:
    minutes = int((maintenant - echeances._lire(iso)).total_seconds() // 60)
    return f"{minutes // 60} h {minutes % 60:02d}" if minutes >= 120 else f"{minutes} min"


def _inscrire_etape(conn, projet, etape: Etape, *, objet, cible, message, resume_relance,
                    resume_signal, avancer) -> int | None:
    """Inscrit le message de l'étape et l'avance de l'obligation dans UNE transaction."""
    nature = "relance" if etape.action == "relance" else "signalement"
    return commandes.inscrire(
        conn, de="cime", a=cible, nature=nature,
        resume=(resume_relance if nature == "relance" else resume_signal)[:160],
        en_reponse_a=message, objet=objet, preuve={"cmd": "facteur", "etape": objet},
        dans_transaction=avancer)


def executer(projet, maintenant: datetime) -> int:
    """Une passe : les étapes échues des obligations ouvertes, puis la dette au repos.
    Renvoie le nombre de messages inscrits."""
    conn = ouvrir(projet)
    inscrits = 0
    try:
        lignes = conn.execute(
            "SELECT o.id, o.message_id, o.debiteur, o.attendu, o.echeance, o.relances,"
            " o.prochaine, m.nature, m.objet, m.resume, m.horodatage, m.corps"
            " FROM obligations o JOIN messages m ON m.id = o.message_id"
            " WHERE o.etat = 'ouverte' ORDER BY o.id").fetchall()
        for (oid, mid, debiteur, attendu, echeance, rang, prochaine, nature, objet, resume,
             horodatage, corps) in lignes:
            type_ = echeances.type_obligation(nature, attendu, debiteur, objet, corps)
            echelle = echeances.ECHELLES.get(type_) if type_ else None
            if not echelle or rang >= len(echelle):
                continue
            due = echeance if rang == 0 else prochaine
            if due is None:
                continue
            # aucune échéance ne court pendant une fermeture : la marche part au plus tôt à la
            # dernière réouverture, plus son délai
            if echeances.echue_a(conn, due, echelle[rang].delai) > maintenant:
                continue
            while True:   # une marche de délai nul a lieu dans la même passe que la précédente
                inscrits += _etape_obligation(conn, projet, maintenant, oid, mid, debiteur, attendu,
                                              rang, echelle, resume, horodatage)
                rang += 1
                if rang >= len(echelle) or echelle[rang].delai:
                    break
        inscrits += autorisations_a_utilisateur(conn, projet, maintenant)
        inscrits += dette_au_repos(conn, projet, maintenant)
    finally:
        conn.close()
    return inscrits


def _etape_obligation(conn, projet, maintenant, oid, mid, debiteur, attendu, rang, echelle,
                      resume, horodatage) -> int:
    etape = echelle[rang]
    if etape.actif is not None:   # le mode autonome est lu à l'échéance, jamais figé
        etape = echeances.etape_effective(etape, autorisations.mode_actif(projet))
    suivante = echelle[rang + 1] if rang + 1 < len(echelle) else None
    prochaine = None if suivante is None else livraison._iso(maintenant + suivante.delai)

    def avancer(_message_id=None):
        cur = conn.execute("UPDATE obligations SET relances = ?, prochaine = ?"
                           " WHERE id = ? AND etat = 'ouverte' AND relances = ?",
                           (rang + 1, prochaine, oid, rang))
        if cur.rowcount != 1:  # fermée ou déjà avancée entre-temps : on n'ajoute rien
            raise _Perdue()

    cible = resoudre(etape.cible, debiteur, projet) if etape.action else None
    objet = f"relance:{mid}:{rang}" if etape.action == "relance" else f"escalade:{mid}:{rang}"
    sauter = (etape.action is None or cible is None or _existe(conn, objet, cible)
              or (etape.action == "signalement" and not etape.renotifier and conn.execute(
                  "SELECT 1 FROM messages WHERE de = 'cime' AND a = ? AND objet LIKE ?",
                  (cible, f"escalade:{mid}:%")).fetchone() is not None))
    try:
        if sauter:
            with conn:
                avancer()
            return 0
        libelle = LIBELLES.get(attendu, attendu)
        age = _age(maintenant, horodatage)
        _inscrire_etape(
            conn, projet, etape, objet=objet, cible=cible, message=mid,
            resume_relance=f"rappel : {debiteur} n'a pas encore {libelle} ({age}) — {resume} (#{mid})",
            resume_signal=(f"autorisation sans réponse depuis {age} — {resume} (#{mid})" if etape.info
                           else f"{debiteur} n'a pas {libelle} depuis {age} — {resume} (#{mid})"),
            avancer=avancer)
        return 1
    except _Perdue:
        return 0


class _Perdue(Exception):
    pass


# --- autorisations adressées à l'utilisateur (sans obligation) ------------------------------

def _rang_du(echelle, ecoule) -> int | None:
    """Le rang de la dernière marche échue après `ecoule` (une marche `repeter` compte une
    occurrence de plus tous les `delai`), ou None."""
    cumul, du = echeances.IMMEDIAT, None
    for rang, etape in enumerate(echelle):
        cumul += etape.delai
        if cumul > ecoule:
            break
        du = rang
        if etape.repeter:
            du = rang + int((ecoule - cumul) / etape.delai)
    return du


def autorisations_a_utilisateur(conn, projet, maintenant: datetime) -> int:
    """Une demande `reserve` ou `autonome` adressée à l'utilisateur n'a pas d'obligation (un signalement
    à l'utilisateur n'en ouvre aucune) : son échelle se calcule sur l'âge de la demande, tant qu'elle
    n'est pas tranchée. Clé de chaque marche : `relance:<id>:<rang>` / `escalade:<id>:<rang>`,
    une seule fois par rang. Aucune marche ne refuse. Renvoie le nombre de messages inscrits."""
    inscrits = 0
    for mid, objet, corps, resume, horodatage in conn.execute(
            "SELECT id, objet, corps, resume, horodatage FROM messages m WHERE de = 'cime'"
            " AND a = 'utilisateur' AND nature = 'signalement' AND objet LIKE 'autorisation:%'"
            " AND NOT EXISTS (SELECT 1 FROM messages r WHERE r.objet = m.objet"
            " AND r.nature IN ('accord', 'refus')) ORDER BY id").fetchall():
        type_ = echeances.type_autorisation(corps, UTILISATEUR)
        if type_ not in ("autorisation_reserve", "autorisation_autonome"):
            continue
        if autorisations.tranchee(conn, objet[len(autorisations.PREFIXE):], horodatage):
            continue
        echelle = echeances.ECHELLES[type_]
        rang = _rang_du(echelle, maintenant - echeances.depart(conn, horodatage))
        if rang is None:
            continue
        etape = echelle[min(rang, len(echelle) - 1)]
        if etape.actif is not None:
            etape = echeances.etape_effective(etape, autorisations.mode_actif(projet))
        if etape.action is None or conn.execute(
                "SELECT 1 FROM messages WHERE de = 'cime' AND objet IN (?, ?)",
                (f"relance:{mid}:{rang}", f"escalade:{mid}:{rang}")).fetchone():
            continue
        if etape.action == "signalement" and etape.cible == UTILISATEUR and not etape.renotifier:
            continue                    # l'utilisateur a déjà la demande : rien de neuf à lui dire
        cible = resoudre(etape.cible, UTILISATEUR, projet)
        age = _age(maintenant, horodatage)
        relance = etape.action == "relance"
        commandes.inscrire(
            conn, de="cime", a=cible, nature="relance" if relance else "signalement",
            resume=(f"rappel : demande d'autorisation en attente ({age}) — {resume} (#{mid})" if relance
                    else f"autorisation sans réponse depuis {age} — {resume} (#{mid})" if etape.info
                    else f"toujours en attente depuis {age} — {resume} (#{mid})")[:160],
            en_reponse_a=mid, objet=f"{'relance' if relance else 'escalade'}:{mid}:{rang}",
            preuve={"cmd": "facteur", "etape": f"{mid}:{rang}"})
        inscrits += 1
    return inscrits


# --- dette au repos ---------------------------------------------------------------------

def dette_au_repos(conn, projet, maintenant: datetime) -> int:
    """Un agent au repos depuis plus de `DETTE_AU_REPOS` avec une obligation ouverte à son nom :
    relance au débiteur, puis signalement → sup, → sup du sup. L'échelle repart à chaque repos
    (la clé porte l'id de l'événement de fin de tour). Rien ne court pour un coordinateur endormi, et
    le repos d'avant son sommeil ne compte pas après son réveil. Sans dette, jamais rien. Jamais de
    relance de dette à l'Assistant (ni à l'utilisateur) : leurs seules échéances sont les lignes explicites
    de `echeances.ECHELLES`."""
    inscrits = 0
    agents = [r[0] for r in conn.execute(
        "SELECT DISTINCT debiteur FROM obligations WHERE etat = 'ouverte' AND attendu != 'accuse'"
        " AND debiteur NOT IN ('utilisateur', 'assistant')")]
    for agent in agents:
        fin_de_tour = livraison.repos_depuis(conn, agent, maintenant)
        if fin_de_tour is None:
            continue
        evenement_id, depuis = fin_de_tour
        if repos.episode(conn, agent):
            continue                    # il dort : aucune échéance ne court tant que sa session est fermée
        depart = echeances.depart(conn, depuis)
        sommeil = repos.sommeil_ou_reveil_a(conn, agent)
        ecoule = (maintenant - (max(depart, sommeil) if sommeil else depart)).total_seconds()
        cumul = 0.0
        for rang, etape in enumerate(echeances.ECHELLE_DETTE_AU_REPOS):
            cumul += etape.delai.total_seconds()
            if ecoule < cumul:
                break
            cible = resoudre(etape.cible, agent, projet)
            objet = f"dette:{agent}:{evenement_id}:{rang}"
            if cible is None or _existe(conn, objet, cible) or (
                    etape.action == "signalement" and conn.execute(
                        "SELECT 1 FROM messages WHERE de = 'cime' AND a = ? AND objet LIKE ?",
                        (cible, f"dette:{agent}:{evenement_id}:%")).fetchone()):
                continue
            dettes = conn.execute(
                "SELECT o.message_id, m.resume FROM obligations o JOIN messages m ON m.id = o.message_id"
                " WHERE o.debiteur = ? AND o.etat = 'ouverte' AND o.attendu != 'accuse'"
                " ORDER BY o.message_id", (agent,)).fetchall()
            premier = dettes[0]
            plus = f" (+{len(dettes) - 1})" if len(dettes) > 1 else ""
            commandes.inscrire(
                conn, de="cime", a=cible,
                nature="relance" if etape.action == "relance" else "signalement",
                resume=(f"tu es au repos et il te reste à faire : {premier[1]} (#{premier[0]}){plus}"
                        if etape.action == "relance" else
                        f"{agent} est au repos depuis {_age(maintenant, depuis)} avec une dette : "
                        f"{premier[1]} (#{premier[0]}){plus}")[:160],
                en_reponse_a=premier[0] if etape.action == "relance" else None, objet=objet,
                preuve={"cmd": "facteur", "etape": objet})
            inscrits += 1
            break  # une marche par tour
    return inscrits
