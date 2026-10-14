"""La table des échéances : constantes et échelles d'escalade.

Valeurs provisoires. `ECHELLES` est la source unique : `delai` en tire le premier signal
(qui fixe `obligations.echeance`), et le moteur `relances.py` en tire les marches suivantes.
`IMMEDIAT` = échu dès l'inscription.
"""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

IMMEDIAT = timedelta(0)
DELAI_OCCUPE = timedelta(minutes=10)      # accusé, agent au travail
DETTE_AU_REPOS = timedelta(minutes=5)
QUESTION = timedelta(minutes=15)
DEMANDE_ACCORD = timedelta(minutes=10)
TRAVAIL_PRET_COORD = timedelta(minutes=30)
TRAVAIL_PRET_ASSISTANT = timedelta(minutes=60)
DEMANDE_CLOTURE = timedelta(minutes=60)
AUTORISATION = IMMEDIAT                   # l'Assistant d'abord
ATTENTE_UTILISATEUR = IMMEDIAT                 # notification immédiate ; renotification à 2 h
RENOTIFICATION_UTILISATEUR = timedelta(hours=2)
SIGNALEMENT_UTILISATEUR_PLAFOND = RENOTIFICATION_UTILISATEUR  # un signalement à l'utilisateur est clos à 2 h au plus
SIGNAL_SUPERIEUR = IMMEDIAT               # fin-sans-suite, session-disparue, refus-garde…
FIN_SANS_TERMINER = timedelta(minutes=10) # session worker finie, tâche encore en cours
SUITES_FUSION = timedelta(minutes=10)
CONTEXTE = timedelta(minutes=10)

# Seuils d'observation d'alarmes qui ne naissent pas d'une obligation (source unique, avec ECHELLES)
FIGE = timedelta(minutes=15)             # fige : « travaille » sans événement ni activité de fenêtre
FIGE_GRAVE = timedelta(minutes=45)       # … puis grave
ASSISTANT_SOURD = timedelta(minutes=2)   # courrier tmux non acquitté après un idle_prompt, invite vide

PAS_FACTEUR = 2.0                         # s : un tour du facteur
PEREMPTION_BATTEMENT = 30                 # s : au-delà, le facteur est dit arrêté
FENETRE_DELAI = timedelta(seconds=30)     # un message attend depuis là : on regarde si une fenêtre bloque l'agent
SILENCE_FENETRE = 3.0                     # s : `window_activity` inchangé avant de taper
INCONNU_PROLONGE_S = SILENCE_FENETRE * 10  # s : écran `inconnu` avec un message en attente, noté (événement + journal)
PAUSE_VALIDATION = 1.0                     # s : entre l'Enter et la relecture de l'invite (défaut 4)
PAUSE_FRAPPE = 1.0                       # s : entre la frappe et l'Enter
STABILISATION_PAS = 0.5                  # s : entre deux relectures d'une invite pas encore notre frappe
STABILISATION_MAX = 6.0                  # s : durée totale d'attente que la TUI a pour afficher la frappe
# Tentatives de livraison tmux : +0, +30 s, +2 min, +5 min. Écart avant la
# tentative suivante, par rang de la tentative qui vient d'être faite ; attente de la dernière.
TENTATIVES_ECART_S = (30, 90, 180)
TENTATIVES = len(TENTATIVES_ECART_S) + 1  # 4 au total
ATTENTE_DERNIERE_S = 30                   # après la 4ᵉ frappe sans accusé : `echec`
SESSION_ABSENTE = timedelta(minutes=2)    # message inscrit depuis plus que ça, session absente
INACTIVITE_FACTEUR = timedelta(minutes=10)
# `cime envoyer` refuse un message identique à un message encore vivant inscrit depuis moins de cette durée
DOUBLON_FENETRE = timedelta(minutes=10)

# Courrier de voie `hook:Stop` resté ouvert sans accusé : son bail est renouvelé (le texte peut être dans
# un tour qui repart) au plus jusqu'à ce plafond ; ensuite il est refermé et le message revient en file.
COURRIER_STOP_PLAFOND_S = 300  # s

ATTENTE_STOP = 120   # s : le hook `Stop` attend un message (M-I) ; 0 pour l'Assistant
MARGE_STOP = 30      # s : marge du `timeout` du hook `Stop` au-delà de l'attente
VAR_ATTENTE_STOP = "CIME_ATTENTE_STOP"  # lue par le hook, pour les tests


@dataclass(frozen=True)
class Etape:
    """Une marche de l'échelle d'une obligation.
    `delai` : depuis l'étape précédente (la première : depuis l'inscription du message).
    `action` : "relance" (message `relance` de Cime, en réponse au message d'origine) ou
    "signalement" (escalade) ; None = l'étape a déjà été faite par l'événement qui a inscrit
    le message (le « immédiat » de la table) : le moteur ne fait qu'avancer d'un rang.
    `cible` : "debiteur", "sup" (supérieur du débiteur), "supsup", "assistant", "utilisateur".
    `renotifier` : répéter une notification déjà faite à la même cible reste voulu.
    `actif` : la marche à faire à sa place si le mode autonome est actif **à l'échéance** (relu à
    chaque fois). `info` : un `signalement` d'information à l'utilisateur
    (« autorisation sans réponse »). `repeter` : la dernière marche revient tous les `delai` tant
    que la demande attend (renotification de l'utilisateur pour une demande `reserve`)."""
    delai: timedelta
    action: str | None = None
    cible: str | None = None
    renotifier: bool = False
    actif: "Etape | None" = None
    info: bool = False
    repeter: bool = False


def etape_effective(etape: Etape, mode_actif: bool) -> Etape:
    """La marche à faire, selon le mode autonome lu à l'échéance."""
    return etape.actif if mode_actif and etape.actif is not None else etape


def _minutes(n: int) -> timedelta:
    return timedelta(minutes=n)


# L'échelle de chaque type d'obligation : colonnes « Premier signal / Escalade 1 / Escalade 2 »
# de la table des échéances, en délais depuis l'étape précédente (cumulés entre parenthèses).
ECHELLES: dict[str, tuple[Etape, ...]] = {
    # accusé d'une consigne : la livraison (tentatives, `echec`, `occupe`) en est responsable
    "accuse": (Etape(DELAI_OCCUPE),),
    # question : 15 min relance, 30 min → sup du destinataire, 60 min l'utilisateur
    "question": (Etape(QUESTION, "relance", "debiteur"), Etape(_minutes(15), "signalement", "sup"),
                 Etape(_minutes(30), "signalement", "utilisateur")),
    # demande_accord : 10 min relance à l'Assistant, 20 min l'utilisateur
    "demande_accord": (Etape(DEMANDE_ACCORD, "relance", "debiteur"),
                       Etape(_minutes(10), "signalement", "utilisateur")),
    # travail_pret → coordinateur : 30 min relance, 60 min → assistant
    "travail_pret_coord": (Etape(TRAVAIL_PRET_COORD, "relance", "debiteur"),
                           Etape(_minutes(30), "signalement", "sup")),
    # travail_pret → assistant : 60 min relance, 120 min l'utilisateur
    "travail_pret_assistant": (Etape(TRAVAIL_PRET_ASSISTANT, "relance", "debiteur"),
                               Etape(_minutes(60), "signalement", "utilisateur")),
    # demande_cloture : 60 min relance, 120 min l'utilisateur
    "demande_cloture": (Etape(DEMANDE_CLOTURE, "relance", "debiteur"),
                        Etape(_minutes(60), "signalement", "utilisateur")),
    # autorisation : immédiat Assistant, 2 min l'utilisateur (page + notif), 10 min renotification
    "autorisation": (Etape(AUTORISATION), Etape(_minutes(2), "signalement", "utilisateur"),
                     Etape(_minutes(8), "signalement", "utilisateur", renotifier=True)),
    # autorisations par classe : la classe est dans le `corps` du
    # signalement ; « actif » = mode autonome actif et non suspendu à l'échéance.
    # libre, demande d'un worker (débiteur : son coordinateur) : 2 min relance au coordinateur et
    # signalement à l'Assistant ; 4 min l'utilisateur (actif : relance à l'Assistant) ; 10 min
    # renotification de l'utilisateur (actif : information à l'utilisateur)
    "autorisation_libre_worker": (
        Etape(AUTORISATION), Etape(_minutes(2), "relance", "debiteur"),
        Etape(IMMEDIAT, "signalement", "assistant"),
        Etape(_minutes(2), "signalement", "utilisateur", actif=Etape(_minutes(2), "relance", "assistant")),
        Etape(_minutes(6), "signalement", "utilisateur", renotifier=True,
              actif=Etape(_minutes(6), "signalement", "utilisateur", renotifier=True, info=True))),
    # libre, demande d'un coordinateur (débiteur : l'Assistant) : 2 min l'utilisateur (actif : relance) ;
    # 10 min renotification (actif : information)
    "autorisation_libre_coord": (
        Etape(AUTORISATION),
        Etape(_minutes(2), "signalement", "utilisateur", actif=Etape(_minutes(2), "relance", "debiteur")),
        Etape(_minutes(8), "signalement", "utilisateur", renotifier=True,
              actif=Etape(_minutes(8), "signalement", "utilisateur", renotifier=True, info=True))),
    # autonome (Assistant en mode actif, l'utilisateur sinon) : 2 min relance à l'Assistant (inactif :
    # l'utilisateur, s'il ne l'a pas déjà eue) ; 10 min renotification (actif : information)
    "autorisation_autonome": (
        Etape(AUTORISATION),
        Etape(_minutes(2), "signalement", "utilisateur", actif=Etape(_minutes(2), "relance", "assistant")),
        Etape(_minutes(8), "signalement", "utilisateur", renotifier=True,
              actif=Etape(_minutes(8), "signalement", "utilisateur", renotifier=True, info=True))),
    # réservé : l'utilisateur d'emblée, renotification toutes les 2 h (comme une attente de l'utilisateur)
    "autorisation_reserve": (
        Etape(AUTORISATION),
        Etape(RENOTIFICATION_UTILISATEUR, "signalement", "utilisateur", renotifier=True, repeter=True)),
    # approbation : l'écran de démarrage attend l'utilisateur ; immédiat Assistant, 2 min l'utilisateur (page)
    "approbation": (Etape(AUTORISATION), Etape(_minutes(2), "signalement", "utilisateur")),
    # attente de l'utilisateur : notification immédiate, 2 h renotification, jamais d'action implicite
    "attente_utilisateur": (Etape(ATTENTE_UTILISATEUR), Etape(RENOTIFICATION_UTILISATEUR, "relance", "debiteur")),
    # fin-sans-suite, session-disparue, refus-garde, facteur-arrete, erreur-api (StopFailure) :
    # immédiat → sup, 10 min → sup du sup, 30 min l'utilisateur. Le débiteur est déjà le sup.
    "signalement_grave": (Etape(SIGNAL_SUPERIEUR), Etape(_minutes(10), "signalement", "sup"),
                          Etape(_minutes(20), "signalement", "utilisateur")),
    # suites de fusion : 10 min relance, 30 min l'utilisateur (le signalement est l'étape immédiate)
    "suites_fusion": (Etape(IMMEDIAT), Etape(SUITES_FUSION, "relance", "debiteur"),
                      Etape(_minutes(20), "signalement", "utilisateur")),
    # contexte : 10 min relance au sup, 30 min → sup du sup (idem)
    "contexte": (Etape(IMMEDIAT), Etape(CONTEXTE, "relance", "debiteur"),
                 Etape(_minutes(20), "signalement", "sup")),
    # signalement d'information (occupé, session absente, collision, mélange, escalade) :
    # échu aussitôt, sans escalade
    "signalement_info": (Etape(IMMEDIAT),),
}

# Dette au repos : agent `Stop` avec une obligation ouverte. 5 min relance au débiteur,
# +10 min signalement → sup, +15 min → sup du sup (l'utilisateur = page).
ECHELLE_DETTE_AU_REPOS: tuple[Etape, ...] = (
    Etape(DETTE_AU_REPOS, "relance", "debiteur"), Etape(_minutes(10), "signalement", "sup"),
    Etape(_minutes(15), "signalement", "supsup"))

# Le type d'un `signalement` se lit dans le préfixe de son `objet`.
TYPES_DE_SIGNALEMENT: tuple[tuple[str, str], ...] = (
    ("autorisation:", "autorisation"), ("approbation:", "approbation"),
    ("erreur-api:", "signalement_grave"), ("fin-sans-suite:", "signalement_grave"),
    ("session-disparue:", "signalement_grave"), ("fin-sans-terminer:", "signalement_grave"), ("refus-garde:", "signalement_grave"),
    ("facteur-arrete", "signalement_grave"),
    ("suites:", "suites_fusion"), ("contexte:", "contexte"),
)


CLASSES_AUTORISATION = ("libre", "autonome", "reserve")


def corps_autorisation(corps) -> dict | None:
    """Le `corps` JSON d'un `signalement autorisation:` s'il porte une classe connue, sinon None."""
    try:
        donnees = json.loads(corps) if isinstance(corps, str) else None
    except ValueError:
        return None
    if not isinstance(donnees, dict) or donnees.get("classe") not in CLASSES_AUTORISATION:
        return None
    return donnees


def type_autorisation(corps, debiteur: str | None) -> str:
    """Le type d'échéance d'une demande d'autorisation, lu dans son `corps` (classe) et son
    débiteur (le coordinateur pour un worker, l'Assistant pour un coordinateur). Sans classe
    lisible : l'échelle d'avant les classes."""
    donnees = corps_autorisation(corps)
    if donnees is None:
        return "autorisation"
    classe = donnees["classe"]
    if classe == "libre":
        return "autorisation_libre_worker" if (debiteur or "").startswith("coord-") \
            else "autorisation_libre_coord"
    return f"autorisation_{classe}"


def type_obligation(nature: str, attendu: str, debiteur: str, objet: str | None = None,
                    corps: str | None = None):
    """Clé de `ECHELLES` pour une obligation, ou None (pas d'échéance absolue)."""
    if nature in ("question", "demande_accord", "demande_cloture"):
        return nature
    if nature == "travail_pret":
        return "travail_pret_coord" if debiteur.startswith("coord-") else "travail_pret_assistant"
    if nature == "signalement" and (objet or "").startswith("autorisation:"):
        return type_autorisation(corps, debiteur)
    if nature == "signalement":
        for prefixe, type_ in TYPES_DE_SIGNALEMENT:
            if (objet or "").startswith(prefixe):
                return type_
        return "signalement_info"
    if nature in ("decision_utilisateur", "donnee_utilisateur", "rapport_utilisateur"):
        return "attente_utilisateur"
    if nature == "consigne" and (objet or "").startswith("suites:"):
        return "suites_fusion"      # la consigne que le code adresse à l'Assistant après une fusion
    if nature == "consigne" and attendu == "accuse":
        return "accuse"
    return None  # consigne reponse/travail_pret : pas d'échéance absolue, la dette au repos


def delai(nature: str, attendu: str, debiteur: str, objet: str | None = None,
          corps: str | None = None):
    """Délai du premier signal de l'obligation, ou None. La table `ECHELLES` en est la source."""
    type_ = type_obligation(nature, attendu, debiteur, objet, corps)
    return ECHELLES[type_][0].delai if type_ else None


def _lire(horodatage: str) -> datetime:
    return datetime.strptime(horodatage, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


def depart(conn, horodatage: str) -> datetime:
    """Le départ d'une échéance : le plus tardif de l'horodatage d'origine et de
    la dernière réouverture du projet (`ProjetRouvert`). Aucune échéance ne court pendant une
    fermeture ; c'est le seul point par où passent les moteurs d'échéances (`relances`,
    sessions absentes, fins sans terminer)."""
    debut = _lire(horodatage)
    reouverture = derniere_reouverture(conn)
    return debut if reouverture is None else max(debut, reouverture)


def derniere_reouverture(conn) -> datetime | None:
    ligne = conn.execute("SELECT max(horodatage) FROM evenements"
                         " WHERE evenement = 'ProjetRouvert'").fetchone()
    return _lire(ligne[0]) if ligne and ligne[0] else None


def echue_a(conn, due: str, delai_: timedelta) -> datetime:
    """Quand une marche dont `due` est l'échéance calculée (départ + `delai_`) est échue vraiment :
    pas avant `delai_` après la dernière réouverture."""
    reouverture = derniere_reouverture(conn)
    due_ = _lire(due)
    return due_ if reouverture is None else max(due_, reouverture + delai_)


def echeance(horodatage_message: str, delai_: timedelta | None) -> str | None:
    """Horodatage du message + délai, au format du registre ; None si pas de délai."""
    if delai_ is None:
        return None
    return (_lire(horodatage_message) + delai_).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
