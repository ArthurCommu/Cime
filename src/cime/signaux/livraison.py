"""La livraison par le facteur : la voie « au repos », par tmux.

Le facteur est le seul qui écrit dans un terminal. Tout appel à tmux passe par `_tmux`, la
pause par `_dormir` : les tests les remplacent. Le déroulé de la frappe est celui de la
« course à la frappe » — l'`Enter` est l'unique geste irréversible, et il n'est
tapé que si l'invite vaut exactement le texte envoyé.
"""
import json
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from cime.fondation import fermeture, invite
from cime.fondation.projet import equipe_de, lire_manifeste, session_tmux
from cime.fondation import registre
from cime.fondation.registre import ouvrir
from cime.signaux import courrier, echeances, hooks

UTILISATEUR = "utilisateur"
ASSISTANT = "assistant"
EVENEMENTS_DE_TOUR = ("UserPromptSubmit", "PostToolUse", "Stop", "StopFailure")
FIN_DE_TOUR = ("Stop", "StopFailure")


def _dormir(secondes: float) -> None:
    time.sleep(secondes)


def _tmux(*args: str):
    return subprocess.run(["tmux", *args], capture_output=True, text=True)


@dataclass
class Memoire:
    """Ce que le facteur garde entre deux tours (rien d'essentiel : tout est en base)."""
    demarre: bool = False
    occupe_par: dict = field(default_factory=dict)   # agent -> tour|invite|attente_stop|None
    erreurs: dict = field(default_factory=dict)      # agent -> dernière erreur de livraison
    detail: dict = field(default_factory=dict)       # agent -> précision de la raison de non-frappe
    inconnu_depuis: dict = field(default_factory=dict)   # agent -> instant où `inconnu` a commencé
    inconnu_note: set = field(default_factory=set)       # agents dont l'épisode `inconnu` est déjà noté
    episodes: dict = field(default_factory=dict)         # agent -> raison notée (un événement par épisode)
    frappes_perdues: dict = field(default_factory=dict)  # agent -> texte tapé par nous, resté à l'invite sans être validé


def _lire(horodatage: str) -> datetime:
    return echeances._lire(horodatage)


def _iso(instant: datetime) -> str:
    return instant.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _secondes(maintenant: datetime, iso: str) -> float:
    return (maintenant - _lire(iso)).total_seconds()


# --- l'état de l'agent, lu dans `evenements` ----------------------------------------------

def _dernier(conn, agent, evenements):
    marques = ",".join("?" for _ in evenements)
    return conn.execute(
        f"SELECT id, evenement, horodatage FROM evenements WHERE agent = ?"
        f" AND evenement IN ({marques}) ORDER BY id DESC LIMIT 1", (agent, *evenements)).fetchone()


def _idle_prompt_apres(conn, agent, evenement_id) -> bool:
    return conn.execute(
        "SELECT 1 FROM evenements WHERE agent = ? AND evenement = 'Notification' AND id > ?"
        " AND json_extract(details, '$.notification_type') = 'idle_prompt' LIMIT 1",
        (agent, evenement_id)).fetchone() is not None


def _ouverture_apres(conn, agent, evenement_id):
    """(id, horodatage) du dernier `SessionStart` de source `startup` ou `resume` postérieur à
    `evenement_id` : une session neuve s'ouvre sur une invite vide, même si l'ancienne a été tuée en
    plein tour. Pas `compact` (peut survenir en plein tour) ni `clear`."""
    return conn.execute(
        "SELECT id, horodatage FROM evenements WHERE agent = ? AND evenement = 'SessionStart' AND id > ?"
        " AND json_extract(details, '$.source') IN ('startup', 'resume') ORDER BY id DESC LIMIT 1",
        (agent, evenement_id)).fetchone()


def etat_agent(conn, agent, maintenant) -> str:
    """`tour` si le dernier événement de l'agent parmi {UserPromptSubmit, PostToolUse, Stop,
    StopFailure} n'est pas une fin de tour ; `repos` sinon ; `inconnu` s'il n'y en a aucun.
    Un `idle_prompt` postérieur confirme le repos (M-J), y compris après un tour interrompu.
    Une session ouverte (`SessionStart`) sans aucun événement de tour est au repos : elle s'ouvre
    sur une invite vide (un agent repris par `--resume` n'émet rien d'autre)."""
    dernier = _dernier(conn, agent, EVENEMENTS_DE_TOUR)
    if dernier is None:
        if _idle_prompt_apres(conn, agent, 0) or _dernier(conn, agent, ("SessionStart",)):
            return "repos"
        return "inconnu"
    if dernier[1] in FIN_DE_TOUR or _idle_prompt_apres(conn, agent, dernier[0]) \
            or _ouverture_apres(conn, agent, dernier[0]):
        return "repos"
    return "tour"


def repos_depuis(conn, agent, maintenant):
    """(id, horodatage) de l'événement qui a mis l'agent au repos (`Stop`, `StopFailure` ou
    `idle_prompt` après un tour interrompu), ou None s'il n'est pas au repos."""
    dernier = _dernier(conn, agent, EVENEMENTS_DE_TOUR)
    if etat_agent(conn, agent, maintenant) != "repos":
        return None
    if dernier is None:
        ouverture = _dernier(conn, agent, ("SessionStart",))
        return (ouverture[0], ouverture[2]) if ouverture else None
    if dernier[1] in FIN_DE_TOUR:
        return dernier[0], dernier[2]
    return conn.execute(
        "SELECT id, horodatage FROM evenements WHERE agent = ? AND evenement = 'Notification'"
        " AND id > ? AND json_extract(details, '$.notification_type') = 'idle_prompt'"
        " ORDER BY id LIMIT 1", (agent, dernier[0])).fetchone() or _ouverture_apres(conn, agent, dernier[0])


def attente_stop_en_cours(conn, agent, maintenant) -> bool:
    """Le dernier `Stop` date de moins de `ATTENTE_STOP` : le hook attend lui-même un message
    et le livrera. Pour l'Assistant, `ATTENTE_STOP` = 0 : jamais."""
    attente = hooks.attente_stop(agent)
    if attente <= 0:
        return False
    dernier = _dernier(conn, agent, EVENEMENTS_DE_TOUR)
    return dernier is not None and dernier[1] == "Stop" \
        and 0 <= _secondes(maintenant, dernier[2]) < attente


# --- signalements -------------------------------------------------------------------------

def superieur(agent, projet):
    return hooks.superieur(agent, projet)


# --- tmux ---------------------------------------------------------------------------------

def sessions_vivantes() -> set[str]:
    r = _tmux("list-sessions", "-F", "#{session_name}")
    return set(r.stdout.split()) if r.returncode == 0 else set()


def _capturer(session: str) -> str:
    return _tmux("capture-pane", "-p", "-e", "-t", f"={session}:").stdout


def _invite(session: str) -> str | None:
    """Texte de l'invite (texte atténué écarté) ; None si on ne la voit pas."""
    return _lire_invite(session)[0]


def _lire_invite(session: str) -> tuple[str | None, str]:
    """Le texte de l'invite et la capture brute d'où il vient (une seule capture)."""
    capture = _capturer(session)
    return invite.texte_invite(capture), capture


def _taille_pane(session: str) -> list[int] | None:
    """Largeur et hauteur du pane en colonnes et lignes ; None si tmux ne les donne pas."""
    r = _tmux("display-message", "-p", "-t", f"={session}:", "#{pane_width} #{pane_height}")
    if r.returncode != 0 or not re.fullmatch(r"\d+ \d+", r.stdout.strip()):
        return None
    return [int(n) for n in r.stdout.split()]


def _activite(session: str) -> float | None:
    r = _tmux("display-message", "-p", "-t", f"={session}:", "#{window_activity}")
    try:
        return float(r.stdout.strip()) if r.returncode == 0 else None
    except ValueError:
        return None


def _norme(texte: str) -> str:
    """Les retours à la ligne d'un texte qui déborde de la fenêtre ne sont pas du texte."""
    return re.sub(r"\s+", "", texte or "")


# une fenêtre de saisie défilée n'est reconnue comme la nôtre que si elle est assez longue et sur assez de
# lignes pour ne pas ressembler à une saisie étrangère (un suffixe court reste une collision)
FENETRE_CARACTERES = 80
FENETRE_LIGNES = 4


def _fenetre_defilee(apres: str | None, texte: str) -> bool:
    """La TUI a replié notre texte dans une fenêtre plus basse que lui : l'écran n'en montre que la fin
    (suffixe strict de notre texte), sur au moins `FENETRE_LIGNES` lignes et `FENETRE_CARACTERES` caractères."""
    if apres is None or apres.count("\n") < FENETRE_LIGNES - 1:
        return False
    vu, nous = _norme(apres), _norme(texte)
    return FENETRE_CARACTERES <= len(vu) < len(nous) and nous.endswith(vu)


def _est_notre_frappe(apres: str | None, texte: str) -> bool:
    """L'invite vaut notre texte, ou la TUI l'a replié : marqueur(s) `[Pasted text #N …]` en tête,
    suivis au plus de la fin de NOTRE texte (l'écran réel garde la fin tapée) ; ou une fenêtre défilée
    (`_fenetre_defilee`) qui n'en montre que la fin. Un marqueur suivi de
    tout autre texte n'est pas notre frappe. (Un marqueur déjà présent avant la frappe est écarté
    en amont : `_frapper (a)` n'accepte qu'une invite vide.)"""
    if apres is None:
        return False
    if _norme(apres) == _norme(texte) or _fenetre_defilee(apres, texte):
        return True
    debut = re.match(r"\s*(?:" + invite.MARQUEUR.pattern + r"\s*)+", apres)
    if debut is None:
        return False
    reste, nous = _norme(apres[debut.end():]), _norme(texte)
    # le marqueur doit avoir « mangé » un préfixe non vide de notre texte ; sinon il n'est pas de nous
    return nous.endswith(reste) and len(reste) < len(nous)


# --- la livraison d'un agent --------------------------------------------------------------

@dataclass
class Contexte:
    projet: object
    conn: object
    manifeste: object
    maintenant: datetime
    memoire: Memoire
    sessions: set
    journaliser: object = None


def _reste_du_registre(ctx, agent, texte_invite) -> str | None:
    """Le texte de notre dernier courrier tmux, s'il est `echoue` : après un redémarrage du facteur, sa
    mémoire ne le sait plus, mais le registre, si. Seul le dernier courrier compte ; `None` s'il n'est pas
    `echoue`, si un `Enter` a été envoyé pour lui (un texte resté à l'invite après un Enter ignoré n'est
    pas à effacer : la TUI ne l'a pas pris), s'il n'a plus de message, si son texte ne se recalcule pas,
    ou si l'invite n'a pas de texte visible hors marqueurs (un marqueur seul peut être un collage de l'utilisateur)."""
    ligne = ctx.conn.execute(
        "SELECT id, etat FROM courriers WHERE a = ? AND voie = 'tmux' ORDER BY id DESC LIMIT 1",
        (agent,)).fetchone()
    if ligne is None or ligne[1] != "echoue":
        return None
    if ctx.conn.execute("SELECT 1 FROM transitions WHERE courrier_id = ? AND etat = 'livre'"
                        " AND json_extract(preuve, '$.tmux_rc') IS NOT NULL LIMIT 1", (ligne[0],)).fetchone():
        return None
    if not _norme(invite.MARQUEUR.sub("", texte_invite)):
        return None
    courrier_ = courrier.charger(ctx.conn, ligne[0])
    if courrier_ is None or not courrier_.messages:
        return None
    try:
        return courrier.formater(ctx.conn, courrier_, "tmux", ctx.projet)
    except Exception:
        return None


def _conditions(ctx, agent, session) -> str | None:
    """None si on peut taper ; sinon la raison (valeur d'`occupe_par`) — ou `inconnu`."""
    etat = etat_agent(ctx.conn, agent, ctx.maintenant)
    if etat == "tour":
        return "tour"
    if etat == "inconnu":
        return "inconnu"
    if attente_stop_en_cours(ctx.conn, agent, ctx.maintenant):
        return "attente_stop"
    activite = _activite(session)
    if activite is not None:
        ctx.memoire.detail[agent] = {"fenetre_calme_depuis_s": round(ctx.maintenant.timestamp() - activite, 1)}
    if activite is None or ctx.maintenant.timestamp() - activite < echeances.SILENCE_FENETRE:
        return "invite"
    texte = _invite(session)
    if texte is None:
        return "inconnu"
    perdu = ctx.memoire.frappes_perdues.get(agent)
    if perdu is None and texte:
        perdu = _reste_du_registre(ctx, agent, texte)   # repli : la mémoire est prioritaire
    if perdu is not None and _est_notre_frappe(texte, perdu):
        # le reste de NOTRE frappe, non validée : on l'efface, puis on relit (jamais une saisie de l'utilisateur)
        _tmux("send-keys", "-t", f"={session}:", *(["BSpace"] * len(perdu)))
        texte = _invite(session)
        if texte is None:
            return "inconnu"
    if texte == "":
        ctx.memoire.frappes_perdues.pop(agent, None)   # le reste n'est plus là (validé ou effacé)
        return None
    ctx.memoire.detail[agent] = {"texte_a_l_invite": len(texte)}
    return "invite"


def _noter_differe(ctx, agent, avant, raison, message) -> None:
    """Un message attend et la raison de non-frappe vient de changer : un événement
    `LivraisonDifferee` (uniquement aux changements) pour qu'un diagnostic lise l'historique."""
    if raison is None or raison == avant:
        return
    details = {"raison": raison, "message": message["id"],
               "age_s": int(_secondes(ctx.maintenant, message["horodatage"]))}
    details.update(ctx.memoire.detail.get(agent) or {})
    registre.inscrire_evenement(ctx.conn, agent=agent, session_id=None,
                                evenement="LivraisonDifferee", details=details)


def _noter_inconnu_prolonge(ctx, agent, raison, message) -> None:
    """`inconnu` qui dure au-delà de `INCONNU_PROLONGE_S` avec un message en attente : une fois par
    épisode, un événement `LivraisonDifferee` (`prolonge`, `duree_s`) et une ligne du journal du
    facteur (`facteur.log`, sa sortie standard)."""
    if raison != "inconnu":
        ctx.memoire.inconnu_depuis.pop(agent, None)
        ctx.memoire.inconnu_note.discard(agent)
        return
    depuis = ctx.memoire.inconnu_depuis.setdefault(agent, ctx.maintenant)
    duree = (ctx.maintenant - depuis).total_seconds()
    if duree < echeances.INCONNU_PROLONGE_S or agent in ctx.memoire.inconnu_note:
        return
    ctx.memoire.inconnu_note.add(agent)
    details = {"raison": "inconnu", "message": message["id"], "prolonge": True, "duree_s": int(duree),
               "age_s": int(_secondes(ctx.maintenant, message["horodatage"]))}
    registre.inscrire_evenement(ctx.conn, agent=agent, session_id=None,
                                evenement="LivraisonDifferee", details=details)
    print(f"facteur : {agent} : écran non reconnu depuis {int(duree)} s, message #{message['id']} "
          "en attente (rien n'est tapé)", flush=True)


def _episode(ctx, agent, raison, message, **extra) -> None:
    """Un épisode de non-livraison (`raison`) qui dure : un événement `LivraisonDifferee` à son début,
    pas à chaque passage. Sans message en attente, il n'y a rien à noter : l'épisode finit. Ne touche
    pas à `occupe_par`."""
    if message is None:
        return _fin_episode(ctx, agent, raison)
    if ctx.memoire.episodes.get(agent) == raison:
        return
    ctx.memoire.episodes[agent] = raison
    details = {"raison": raison, "message": message["id"],
               "age_s": int(_secondes(ctx.maintenant, message["horodatage"])), **extra}
    registre.inscrire_evenement(ctx.conn, agent=agent, session_id=None,
                                evenement="LivraisonDifferee", details=details)


def _fin_episode(ctx, agent, raison) -> None:
    if ctx.memoire.episodes.get(agent) == raison:
        del ctx.memoire.episodes[agent]


def _courrier_hook(ctx, agent, ouvert) -> bool:
    """Un courrier de voie hook est ouvert : le hook a remis son texte, l'agent n'a pas encore accusé.
    Non expiré, son bail le protège : rien n'est tapé, l'attente est notée une fois (`courrier-hook-ouvert`),
    et `occupe_par` vaut `None` (la raison vit dans l'événement). Expiré, il est fermé comme `prendre` le
    ferait (ses messages reviennent en file) et la livraison continue. Renvoie True si elle peut continuer."""
    if courrier.fermer_expires(ctx.conn, agent, "cime"):
        _fin_episode(ctx, agent, "courrier-hook-ouvert")
        return True
    courrier_id, _voie, _cree, expire, _tentative = ouvert
    ctx.memoire.occupe_par[agent] = None
    _episode(ctx, agent, "courrier-hook-ouvert", next(iter(courrier.en_attente(ctx.conn, agent)), None),
             courrier=courrier_id, expire=expire)
    return False


def livrer(ctx, agent) -> None:
    session = session_tmux(ctx.manifeste, agent)
    if session is None or session not in ctx.sessions:
        ctx.memoire.occupe_par[agent] = None
        _episode(ctx, agent, "session-absente", next(iter(courrier.en_attente(ctx.conn, agent)), None))
        return
    _fin_episode(ctx, agent, "session-absente")
    ouvert = courrier.ouvert_de(ctx.conn, agent)
    if ouvert is not None and not ouvert[1].startswith("tmux"):
        if not _courrier_hook(ctx, agent, ouvert):
            return
    else:
        _fin_episode(ctx, agent, "courrier-hook-ouvert")
        if ouvert is not None and _suivre_attente(ctx, agent, ouvert) != "ferme":
            return
    messages = courrier.en_attente(ctx.conn, agent)
    if not messages:
        ctx.memoire.occupe_par[agent] = None
        return
    tentatives = max(courrier.livraisons_de(ctx.conn, m["id"]) for m in messages)
    if tentatives >= echeances.TENTATIVES:
        _echec_definitif(ctx, agent, messages, tentatives)
        return
    avant = ctx.memoire.occupe_par.get(agent)
    ctx.memoire.detail.pop(agent, None)
    raison = _conditions(ctx, agent, session)
    ctx.memoire.occupe_par[agent] = raison
    _noter_differe(ctx, agent, avant, raison, messages[0])
    _noter_inconnu_prolonge(ctx, agent, raison, messages[0])
    if raison is not None:
        if raison == "tour":
            _signaler_occupe(ctx, agent, messages[0]["id"], messages[0]["horodatage"])
        return
    pris = courrier.prendre(ctx.conn, agent, "tmux", "cime", {"capture_avant": "vide"})
    if pris is not None:
        _frapper(ctx, agent, session, pris)


def _signaler_occupe(ctx, agent, message_id, depuis_iso) -> None:
    """Un agent au travail n'est pas un échec avant `DELAI_OCCUPE` ; à ce délai, un
    signalement d'information au supérieur (une fois)."""
    if _secondes(ctx.maintenant, depuis_iso) < echeances.DELAI_OCCUPE.total_seconds():
        return
    sup = superieur(agent, ctx.projet)
    if sup:
        hooks.signaler_une_fois(ctx.conn, ctx.projet, a=sup, objet=f"occupe:{agent}", agent=agent,
                          cle=f"msg:{message_id}",
                          resume=f"{agent} est au travail depuis plus de "
                                 f"{int(echeances.DELAI_OCCUPE.total_seconds() // 60)} min : "
                                 f"le message #{message_id} attend")


def _suivre_attente(ctx, agent, ouvert) -> str:
    """Un courrier tmux est ouvert, l'accusé n'est pas venu. Renvoie `ferme` si la tentative
    suivante doit avoir lieu maintenant (le courrier est fermé, ses messages reviennent en
    file), `echec` si les tentatives sont épuisées, sinon `attend` (bail renouvelé)."""
    courrier_id, _voie, cree, _expire, tentative = ouvert
    age = _secondes(ctx.maintenant, cree)
    etat = etat_agent(ctx.conn, agent, ctx.maintenant)
    if etat == "tour":
        message = ctx.conn.execute(
            "SELECT m.id, m.horodatage FROM messages m JOIN transitions t ON t.message_id = m.id"
            " WHERE t.courrier_id = ? AND t.etat = 'livre' ORDER BY m.id LIMIT 1",
            (courrier_id,)).fetchone()
        if message:
            _signaler_occupe(ctx, agent, message[0], cree)
    else:
        if tentative >= echeances.TENTATIVES:
            if age >= echeances.ATTENTE_DERNIERE_S:
                messages = courrier.charger(ctx.conn, courrier_id).messages
                derniere = ctx.memoire.erreurs.get(agent) or "aucun accusé de réception"
                ids = courrier.echouer(ctx.conn, courrier_id, "cime", {"derniere_erreur": derniere},
                                       definitif=True)
                _signaler_echec(ctx, agent, [m for m in messages if m["id"] in ids], tentative,
                                derniere)
                return "echec"
        elif age >= echeances.TENTATIVES_ECART_S[tentative - 1]:
            courrier.echouer(ctx.conn, courrier_id, "cime", {"sans_accuse": True})
            return "ferme"
    courrier.renouveler(ctx.conn, courrier_id, _iso(ctx.maintenant + timedelta(seconds=courrier.BAIL_S)))
    return "attend"


def _signaler_echec(ctx, agent, messages, tentatives, erreur) -> None:
    if not messages:
        return
    sup = superieur(agent, ctx.projet)
    premier = messages[0]["id"]
    if sup:
        hooks.signaler_une_fois(
            ctx.conn, ctx.projet, a=sup, objet=f"livraison:{premier}", agent=agent,
            cle=f"echec:{premier}",
            resume=f"le message #{premier} n'a pas pu être livré à {agent} "
                   f"après {tentatives} tentatives ({erreur})")


def _echec_definitif(ctx, agent, messages, tentatives) -> None:
    """Les tentatives sont épuisées sans courrier ouvert (collisions successives)."""
    erreur = ctx.memoire.erreurs.get(agent) or "invite occupée à chaque tentative"
    for m in messages:
        ctx.conn.execute("BEGIN IMMEDIATE")
        try:
            from cime.fondation.registre import inscrire_transition
            inscrire_transition(ctx.conn, m["id"], "echec", "cime",
                                {"tentatives": tentatives, "derniere_erreur": erreur},
                                commit=False)
            ctx.conn.commit()
        except BaseException:
            ctx.conn.rollback()
            raise
    _signaler_echec(ctx, agent, messages, tentatives, erreur)


# --- la frappe ----------------------------------------------------------------------------

def _verifier_validation(ctx, agent, session, pris, texte, preuve) -> None:
    """Après l'`Enter` : l'invite doit être vide. Si elle vaut encore NOTRE texte (la TUI n'a pas pris
    l'`Enter`), un seul `Enter` de plus ; si elle n'est toujours pas vide, ou porte autre chose que notre
    texte, plus rien n'est envoyé : `occupe_par = invite` et un signalement `invite-non-validee`."""
    conn, memoire = ctx.conn, ctx.memoire
    cible = f"={session}:"
    _dormir(echeances.PAUSE_VALIDATION)
    restant = _invite(session)
    if restant and _est_notre_frappe(restant, texte):
        r = _tmux("send-keys", "-t", cible, "Enter")
        preuve["entree_renvoyee"] = True
        preuve["tmux_rc_renvoi"] = r.returncode
        _dormir(echeances.PAUSE_VALIDATION)
        restant = _invite(session)
    if restant:    # non vide : non validée, ou autre chose que notre texte
        preuve["invite_apres"] = "non_validee"
        preuve["ecran"] = _releve_ecran(restant, texte)
        courrier.completer_livraison(conn, pris.id, preuve)
        memoire.occupe_par[agent] = "invite"
        memoire.detail[agent] = {"texte_a_l_invite": len(restant)}
        memoire.erreurs[agent] = "le texte est resté dans l'invite sans être validé"
        hooks.signaler_une_fois(
            conn, ctx.projet, a=UTILISATEUR, objet=f"invite-non-validee:{agent}", agent=agent,
            cle=f"courrier:{pris.id}",
            resume=f"un message de {courrier.emetteur_lisible(pris.messages[0]['de'])} à {agent} est resté "
                   "dans l'invite sans être validé (Entrée non prise)")
        return
    if restant is None:
        preuve["invite_apres"] = "inconnue"
    courrier.completer_livraison(conn, pris.id, preuve)
    memoire.erreurs.pop(agent, None)
    memoire.occupe_par[agent] = None


def _fenetre_en_cours(apres: str | None, texte: str) -> bool:
    """Une fenêtre au milieu de notre texte (sous-chaîne stricte, pas un suffixe), assez longue et sur
    assez de lignes : la TUI défile encore, sa fenêtre n'a pas fini de se poser sur la fin."""
    if apres is None or apres.count("\n") < FENETRE_LIGNES - 1:
        return False
    vu, nous = _norme(apres), _norme(texte)
    return FENETRE_CARACTERES <= len(vu) < len(nous) and vu in nous and not nous.endswith(vu)


def _affichage_incomplet(apres: str | None, texte: str) -> bool:
    """L'invite n'est pas (encore) notre frappe, mais peut le devenir : introuvable, vide, un préfixe
    strict non vide de notre texte, ou une fenêtre en cours de défilement (`_fenetre_en_cours`) — la TUI
    n'a pas fini de l'afficher. Un autre texte est une collision."""
    vu, nous = _norme(apres or ""), _norme(texte)
    return vu == "" or (nous.startswith(vu) and len(vu) < len(nous)) or _fenetre_en_cours(apres, texte)


def _releve_ecran(apres: str | None, texte: str) -> dict:
    """Ce que l'écran montrait, en mesures seulement (jamais de texte), pour lire après coup pourquoi la
    frappe n'a pas été reconnue. `relation` range l'écran par rapport à notre texte (normalisés), `ecart` est
    le premier caractère qui diffère (None si identiques ou introuvable), `lignes` le nombre de lignes lues."""
    nous = _norme(texte)
    if apres is None:
        return {"texte_len": len(nous), "vu_len": None, "relation": "introuvable", "ecart": None, "lignes": None}
    vu = _norme(apres)
    if vu == nous:
        relation = "identique"
    elif vu == "":
        relation = "vide"
    elif nous.startswith(vu):
        relation = "prefixe"
    elif nous.endswith(vu):
        relation = "suffixe"
    elif nous in vu:
        relation = "contient"
    else:
        relation = "autre"
    ecart = None if vu == nous else next(
        (i for i, (a, b) in enumerate(zip(vu, nous)) if a != b), min(len(vu), len(nous)))
    return {"texte_len": len(nous), "vu_len": len(vu), "relation": relation, "ecart": ecart,
            "lignes": 0 if apres == "" else apres.count("\n") + 1}


def _frapper(ctx, agent, session, pris) -> None:
    conn, memoire = ctx.conn, ctx.memoire
    texte = courrier.formater(conn, pris, "tmux", ctx.projet)
    cible = f"={session}:"

    def abandon(preuve, erreur, capture=None):
        memoire.erreurs[agent] = erreur
        taille = _taille_pane(session)                 # relevé une seule fois, ici, à l'abandon
        if taille is not None:
            preuve["pane"] = taille
        mesures = invite.mesures_invite(capture) if capture is not None else None
        if mesures is not None:
            preuve["zone"] = mesures                   # des nombres : la zone de saisie telle que lue
        courrier.echouer(conn, pris.id, "cime", preuve)

    # (a) relecture immédiate de l'invite
    avant = _invite(session)
    if avant != "":
        memoire.occupe_par[agent] = "invite"
        abandon({"invite_changee": True}, "l'invite n'était plus vide")
        return
    # (b) une seule frappe du texte complet
    r = _tmux("send-keys", "-t", cible, "-l", texte)
    if r.returncode != 0:
        abandon({"tmux_rc": r.returncode}, f"send-keys a échoué ({r.returncode})")
        return
    # (c) la pause qu'impose l'Enter, puis (d) nouvelle capture : exactement le texte envoyé
    _dormir(echeances.PAUSE_FRAPPE)
    apres, capture = _lire_invite(session)
    # (d') la TUI peut n'avoir pas fini d'afficher la frappe : on relit jusqu'à STABILISATION_MAX
    attendu = 0.0
    while not _est_notre_frappe(apres, texte) and _affichage_incomplet(apres, texte) \
            and attendu < echeances.STABILISATION_MAX:
        _dormir(echeances.STABILISATION_PAS)
        attendu += echeances.STABILISATION_PAS
        apres, capture = _lire_invite(session)
    if _est_notre_frappe(apres, texte):
        r = _tmux("send-keys", "-t", cible, "Enter")
        preuve = {"tmux_rc": r.returncode, "invite_apres": "vide"}
        if _norme(apres) != _norme(texte):
            preuve["replie"] = True
        if r.returncode != 0:
            courrier.completer_livraison(conn, pris.id, preuve)
            abandon({"tmux_rc": r.returncode, "ecran": _releve_ecran(apres, texte)},
                    f"Enter a échoué ({r.returncode})", capture)
            return
        _verifier_validation(ctx, agent, session, pris, texte, preuve)
        return
    # (e) l'invite diffère : pas d'Enter
    efface = False
    if apres is not None and _norme(apres).endswith(_norme(texte)):
        vu = _norme(apres)
        reste = vu[:len(vu) - len(_norme(texte))]
        _tmux("send-keys", "-t", cible, *(["BSpace"] * len(texte)))
        verif = _invite(session)
        efface = verif is not None and _norme(verif) == reste
    if not efface:
        memoire.frappes_perdues[agent] = texte          # le texte peut apparaître plus tard : on s'en souviendra
        sup = UTILISATEUR
        hooks.signaler_une_fois(
            conn, ctx.projet, a=sup, objet=f"collision-invite:{agent}", agent=agent,
            cle=f"courrier:{pris.id}",
            resume=f"un message de {courrier.emetteur_lisible(pris.messages[0]['de'])} "
                   f"à {agent} est resté mêlé à votre saisie, rien n'a été envoyé")
    memoire.occupe_par[agent] = "invite"
    abandon({"collision": True, "efface": efface, "ecran": _releve_ecran(apres, texte)},
            "collision avec une saisie dans l'invite", capture)


# --- sessions absentes, sessions disparues ------------------------------------------------

def sessions_absentes(ctx) -> None:
    """Un message `inscrit` depuis plus de 2 min et la session absente ⇒ `signalement
    session-absente:<agent>` à l'Assistant, une fois par message. Muet tant que le projet est
    fermé ; les deux minutes repartent de la réouverture."""
    if fermeture.est_ferme(ctx.projet):
        return
    for agent in courrier.agents_en_attente(ctx.conn):
        session = session_tmux(ctx.manifeste, agent)
        if session is None or session in ctx.sessions:
            continue
        destinataire = UTILISATEUR if agent == ASSISTANT else ASSISTANT
        for m in courrier.en_attente(ctx.conn, agent):
            if (ctx.maintenant - echeances.depart(ctx.conn, m["horodatage"])).total_seconds() \
                    >= echeances.SESSION_ABSENTE.total_seconds():
                hooks.signaler_une_fois(
                    ctx.conn, ctx.projet, a=destinataire, objet=f"session-absente:{agent}",
                    agent=agent, cle=f"msg:{m['id']}",
                    resume=f"la session de {agent} est absente : le message #{m['id']} attend "
                           "(il sera remis à son retour)")


def _fermeture_ordonnee(conn, agent, debut_id) -> bool:
    """Un ordre `fermer` de cet agent (ou un `lancer … --remplacer`, qui ferme avant de reprendre),
    en file ou exécuté, posé depuis le démarrage de la session (`SessionStart` n° debut_id) :
    sa disparition est la fermeture propre, pas une panne."""
    return conn.execute(
        "SELECT 1 FROM ordres o, evenements e WHERE e.id = ? AND o.cible = ?"
        " AND (o.verbe = 'fermer' OR (o.verbe = 'lancer' AND json_extract(o.parametres, '$.remplacer') = 1))"
        " AND o.etat IN ('en_file', 'execute') AND o.horodatage >= e.horodatage LIMIT 1",
        (debut_id, agent)).fetchone() is not None


def _projet_ferme_apres(conn, evenement_id) -> bool:
    """Un `ProjetFerme` suit cet événement : la session a été fermée avec le projet, pas perdue
    (même statut que `_fermeture_ordonnee`)."""
    return conn.execute("SELECT 1 FROM evenements WHERE evenement = 'ProjetFerme' AND id > ? LIMIT 1",
                        (evenement_id,)).fetchone() is not None


def _fermee_avec_le_projet(conn, evenement_id) -> bool:
    """Le dernier événement de fermeture ou de réouverture avant celui-ci est un `ProjetFerme` : la
    session s'est terminée alors que le projet était fermé."""
    ligne = conn.execute("SELECT evenement FROM evenements WHERE evenement IN ('ProjetFerme',"
                         " 'ProjetRouvert') AND id < ? ORDER BY id DESC LIMIT 1",
                         (evenement_id,)).fetchone()
    return ligne is not None and ligne[0] == "ProjetFerme"


def sessions_disparues(ctx) -> None:
    """Session absente alors que l'agent en avait une et qu'aucun `SessionEnd` ne suit son
    dernier `SessionStart` ⇒ `signalement session-disparue:<agent>` au supérieur, une fois
    par session démarrée."""
    for agent, debut_id in ctx.conn.execute(
            "SELECT agent, max(id) FROM evenements WHERE evenement = 'SessionStart'"
            " AND agent IS NOT NULL GROUP BY agent").fetchall():
        session = session_tmux(ctx.manifeste, agent)
        if session is None or session in ctx.sessions:
            continue
        if ctx.conn.execute("SELECT 1 FROM evenements WHERE agent = ? AND evenement = 'SessionEnd'"
                            " AND id > ? LIMIT 1", (agent, debut_id)).fetchone():
            continue
        if _fermeture_ordonnee(ctx.conn, agent, debut_id):
            continue                                # `cime terminer` : la fermeture est voulue
        if _projet_ferme_apres(ctx.conn, debut_id):
            continue                                # `cime fermer` : la disparition est voulue
        sup = superieur(agent, ctx.projet)
        if sup:
            hooks.signaler_une_fois(
                ctx.conn, ctx.projet, a=sup, objet=f"session-disparue:{agent}", agent=agent,
                cle=f"debut:{debut_id}",
                resume=f"la session de {agent} a disparu sans fin déclarée")


def fins_sans_terminer(ctx) -> None:
    """Le `SessionEnd` d'un worker dont la tâche est encore `in-progress` (personne n'a lancé
    `cime terminer`), sans nouvelle session depuis, et que le signalement de session disparue n'a pas déjà été fait ⇒ `signalement
    fin-sans-terminer:<worker>` au coordinateur, 10 min après la fin, une fois par fin de session —
    même si le worker n'a plus aucune obligation ouverte (il a rendu son `travail_pret`)."""
    for evenement_id, agent, horodatage, details in ctx.conn.execute(
            "SELECT id, agent, horodatage, details FROM evenements WHERE evenement = 'SessionEnd'"
            " AND agent LIKE 'worker-%' ORDER BY id").fetchall():
        if (ctx.maintenant - echeances.depart(ctx.conn, horodatage)).total_seconds() \
                < echeances.FIN_SANS_TERMINER.total_seconds():
            continue
        if _raison_ignoree(details):
            continue
        if _fermee_avec_le_projet(ctx.conn, evenement_id):
            continue                                # `cime fermer` a fermé la session du worker
        if ctx.conn.execute("SELECT 1 FROM evenements WHERE agent = ? AND id > ? AND evenement ="
                            " 'SessionStart' LIMIT 1", (agent, evenement_id)).fetchone():
            continue                                # une nouvelle session a repris la tâche
        equipe = equipe_de(ctx.projet, agent)
        sup = superieur(agent, ctx.projet)
        if not equipe or not sup:
            continue
        tache = agent[len(f"worker-{equipe}-"):]
        if not (Path(ctx.projet) / ".orga" / "teams" / equipe / "tasks" / "in-progress" / f"{tache}.md").is_file():
            continue                                # `terminer` a rangé la tâche
        if ctx.conn.execute("SELECT 1 FROM messages WHERE nature = 'signalement' AND objet = ?"
                            " LIMIT 1", (f"session-disparue:{agent}",)).fetchone():
            continue                                # déjà signalé comme session disparue
        hooks.signaler_une_fois(
            ctx.conn, ctx.projet, a=sup, objet=f"fin-sans-terminer:{agent}", agent=agent,
            cle=f"fin:{evenement_id}",
            resume=f"la session de {agent} s'est terminée sans `cime terminer` : la tâche {tache} est encore en cours")


def _raison_ignoree(details) -> bool:
    try:
        return json.loads(details or "{}").get("reason") in hooks.REPRISE_IGNOREE
    except ValueError:
        return False


def persister_occupation(projet, maintenant, memoire) -> None:
    """Écrit dans `occupation` ce que le facteur sait (une ligne par agent connu) : l'observation
    et la page lisent pourquoi une livraison attend sans parler au facteur."""
    if not memoire.occupe_par:
        return
    conn = ouvrir(projet)
    try:
        with conn:
            conn.executemany(
                "INSERT OR REPLACE INTO occupation (agent, occupe_par, maj) VALUES (?, ?, ?)",
                [(agent, raison, _iso(maintenant)) for agent, raison in memoire.occupe_par.items()])
    finally:
        conn.close()


def _oublier_occupations_perimees(conn, maintenant, memoire, agents) -> None:
    """`occupe_par` dit pourquoi un message attend : sans courrier en attente ni courrier tmux ouvert
    (livré par un hook, par exemple), il n'y a plus de raison à afficher. Les agents servis à ce
    passage recalculent la leur ; les autres repassent à `None`, en mémoire et dans `occupation`."""
    for agent in memoire.occupe_par:
        if agent not in agents:
            memoire.occupe_par[agent] = None
    marques = ",".join("?" for _ in agents)
    with conn:
        conn.execute("UPDATE occupation SET occupe_par = NULL, maj = ? WHERE occupe_par IS NOT NULL"
                     f" AND agent NOT IN ({marques})", (_iso(maintenant), *sorted(agents)))


def livrer_tout(projet, maintenant, memoire, journaliser=None) -> None:
    """Une passe de livraison : chaque agent qui a du courrier, puis les sessions absentes."""
    conn = ouvrir(projet)
    try:
        # ceux qui ont du courrier en attente, et ceux dont un courrier attend son accusé (tmux, ou hook
        # dont le bail doit être tenu ou refermé même sans autre message)
        agents = set(courrier.agents_en_attente(conn)) | {r[0] for r in conn.execute(
            "SELECT a FROM courriers WHERE etat = 'ouvert'")}
        _oublier_occupations_perimees(conn, maintenant, memoire, agents)
        a_surveiller = conn.execute(
            "SELECT 1 FROM evenements WHERE evenement = 'SessionStart' LIMIT 1").fetchone()
        if not agents and not a_surveiller:
            return  # rien à livrer, aucune session connue : pas même un appel à tmux
        ctx = Contexte(projet, conn, lire_manifeste(projet), maintenant, memoire,
                       sessions_vivantes(), journaliser)
        for agent in sorted(agents - {UTILISATEUR, "cime"}):  # l'utilisateur : voie hôte ; `cime` : pas un agent
            try:
                livrer(ctx, agent)
            except Exception as e:  # un agent ne bloque pas les autres
                if journaliser:
                    journaliser(f"livraison {agent}", e)
        sessions_absentes(ctx)
        sessions_disparues(ctx)
        fins_sans_terminer(ctx)
    finally:
        conn.close()
