"""Ce que les hooks de Claude Code font du registre : livrer le courrier, rappeler les
dettes, signaler. `fondation/hook.py` ne fait qu'appeler `rendre`.

Un hook ne tape jamais dans un terminal : il rend du texte (code 2 + stderr, ou stdout) et
inscrit des lignes. La prise d'un courrier (`courrier.prendre`) a lieu juste avant que
`hook.py` n'écrive ce texte : un hook tué avant n'a rien pris.
"""
import os
import re
import shlex
import time
from datetime import datetime, timedelta, timezone

from cime.fondation.projet import ErreurProjet, equipe_de
from cime.fondation.registre import etat_message, inscrire_transition
from cime.signaux import (autorisations, commandes, courrier, echeances, matrice, obligations,
                          reprise)

ASSISTANT = "assistant"
UTILISATEUR = "utilisateur"
MAX_DETTES_CITEES = 5
FIN_RECENTE = timedelta(minutes=10)  # un `fin:<t>` posé par `cime terminer` il y a moins que ça
REPRISE_IGNOREE = ("clear", "resume")  # SessionEnd : la session continue dans le même terminal
_PREFIXE = re.compile(courrier.expression_prefixe())  # les émetteurs que `emetteur_lisible` rend
_ID = re.compile(r"\(#(\d+)\)")


def _dormir(secondes: float) -> None:
    time.sleep(secondes)


def _horloge() -> float:
    return time.monotonic()


def attente_stop(agent: str | None) -> float:
    """Secondes pendant lesquelles le hook `Stop` attend un message : 0 pour l'Assistant."""
    if agent == ASSISTANT:
        return 0
    brut = os.environ.get(echeances.VAR_ATTENTE_STOP)
    if brut not in (None, ""):
        try:
            return max(0.0, float(brut))
        except ValueError:
            pass
    return echeances.ATTENTE_STOP


def superieur(agent: str, projet) -> str | None:
    """Qui prévenir quand `agent` va mal : coord pour un worker, l'Assistant pour un
    coordinateur, l'utilisateur pour l'Assistant."""
    if agent == ASSISTANT:
        return "utilisateur"
    return matrice.superieur(agent, projet)


def _doublon_ouvert(conn, a, objet) -> bool:
    """Un signalement de même `objet` pour `a` est-il encore là ? Pour l'utilisateur, il n'a pas
    d'obligation : il est là tant qu'il n'est pas clos ni abandonné."""
    if a == UTILISATEUR:
        return conn.execute(
            "SELECT 1 FROM messages m WHERE m.de = 'cime' AND m.a = ? AND m.nature = 'signalement'"
            " AND m.objet = ? AND (SELECT t.etat FROM transitions t WHERE t.message_id = m.id"
            " ORDER BY t.id DESC LIMIT 1) NOT IN ('clos', 'abandonne')", (a, objet)).fetchone() is not None
    return conn.execute(
        "SELECT 1 FROM messages m JOIN obligations o ON o.message_id = m.id"
        " WHERE m.de = 'cime' AND m.a = ? AND m.nature = 'signalement' AND m.objet = ?"
        " AND o.etat = 'ouverte'", (a, objet)).fetchone() is not None


def signaler(conn, projet, *, a, objet, resume, agent=None, unique=False,
             une_fois=False, corps=None) -> int | None:
    """Inscrit `cime → a` `signalement objet=…`. `unique` : rien si un signalement de même
    `objet` pour `a` est encore ouvert (obligation ouverte ; pour l'utilisateur, pas clos — pas de doublon).
    `une_fois` : rien si un signalement de même `objet` pour `a` a déjà été inscrit, quel que soit son
    état (l'objet porte la cause : la suite est l'affaire des relances de dette, pas d'un nouveau
    signalement)."""
    if unique and _doublon_ouvert(conn, a, objet):
        return None
    if une_fois and conn.execute(
            "SELECT 1 FROM messages m WHERE m.de = 'cime' AND m.a = ? AND m.nature = 'signalement'"
            " AND m.objet = ?", (a, objet)).fetchone():
        return None
    try:
        equipe = equipe_de(projet, agent) if agent else None
    except ErreurProjet:
        equipe = None
    return commandes.inscrire(
        conn, de="cime", a=a, nature="signalement", resume=resume[:160], objet=objet,
        equipe=equipe, corps=corps, preuve={"cmd": "hook", "pid": os.getpid()})


def signaler_une_fois(conn, projet, *, a, objet, resume, cle, agent=None, corps=None) -> int | None:
    """`cime → a` `signalement`, une seule fois pour (a, objet, cle) — `cle` est gardée dans la
    preuve de la transition `inscrit`, donc un facteur redémarré ne redit rien et la clé ne
    se mêle pas au texte livré."""
    if conn.execute(
            "SELECT 1 FROM messages m JOIN transitions t ON t.message_id = m.id"
            " AND t.etat = 'inscrit' WHERE m.de = 'cime' AND m.a = ? AND m.nature = 'signalement'"
            " AND m.objet = ? AND json_extract(t.preuve, '$.cle') = ? LIMIT 1",
            (a, objet, cle)).fetchone():
        return None
    try:
        equipe = equipe_de(projet, agent) if agent else None
    except ErreurProjet:
        equipe = None
    return commandes.inscrire(conn, de="cime", a=a, nature="signalement", resume=resume[:160],
                              objet=objet, equipe=equipe, corps=corps,
                              preuve={"cmd": "facteur", "cle": cle})


# L'échec d'import du paquet `cime` lui-même : introuvable (`No module named 'cime'`), ou son
# dossier, ou son `cime/__init__.py`, illisible. Jamais un sous-module pas encore écrit
# (`No module named 'cime.nouveau'`) ni un nom manquant (`cannot import name …`) : c'est un
# test rouge écrit avant son module, pas une installation cassée.
_IMPORT_CIME = re.compile(
    r"No module named '?cime'?(?![\w.])"
    r"|(?:PermissionError|ImportError)\b(?![^\n]*cannot import name)[^\n]*"
    r"[/\\]cime(?:[/\\]__init__\.py)?['\"]?(?![\w./\\-])")
PAUSE_IMPORT_CIME = timedelta(hours=1)  # une alerte par agent et par heure : pas de rafale


# Seule la sortie d'un programme Python dit qu'un import a échoué. Un `cat`, un `grep`, un `git log`
# ou une lecture de fichier qui *cite* le texte ne prouve rien : le premier mot de chaque commande
# de la ligne (après `;`, `&&`, `||`, `|`, `(`, des `X=1` et de `env`/`time`/`nice`/…) doit être
# un interpréteur ou un lanceur Python. `cime` en est un (son script est lancé par Python), mais
# il affiche aussi des messages qui citent le texte : sa panne d'import est une trace, donc sa
# sortie doit porter `Traceback`.
_LANCEURS_PYTHON = re.compile(r"python[\d.]*|pytest|py\.test|uv|uvx|pip[\d.]*|pipx|coverage")
_ENVELOPPES_SANS_SENS = {"env", "time", "nice", "nohup", "command", "exec"}
_AFFECTATION_ENV = re.compile(r"[A-Za-z_]\w*\+?=")
_TRACE = "Traceback (most recent call last)"


def _sans_commentaires(commande: str) -> str:
    """La commande sans ses commentaires ; si le module garde ne s'importe pas (installation
    incomplète), la commande brute : un garde cassé ne doit pas faire tomber les hooks."""
    try:
        from cime.fondation.garde import sans_commentaires
    except Exception:
        return commande
    return sans_commentaires(commande)


def _premiers_mots(commande: str) -> list[str]:
    """Le nom (sans dossier) du premier mot de chaque commande de la ligne ; [] si illisible."""
    try:
        lex = shlex.shlex(_sans_commentaires(commande), posix=True, punctuation_chars="();<>|&\n")
        lex.whitespace, lex.whitespace_split, lex.commenters = " \t\r", True, ""
        jetons = list(lex)
    except ValueError:
        return []
    mots, debut = [], True
    for t in jetons:
        if t and set(t) <= set("();<>|&\n"):
            debut = True
        elif debut and (_AFFECTATION_ENV.match(t) or t in _ENVELOPPES_SANS_SENS
                        or (mots and mots[-1] in _ENVELOPPES_SANS_SENS
                            and (t.startswith("-") or t.isdigit()))):
            if t in _ENVELOPPES_SANS_SENS:
                mots.append(t)  # repère pour sauter ses options, retiré plus bas
        elif debut:
            mots.append(os.path.basename(t))
            debut = False
    return [m for m in mots if m not in _ENVELOPPES_SANS_SENS]


def _vient_de_python(entree: dict, sortie: str) -> bool:
    """La sortie vient-elle d'une commande Bash qui exécute du Python ? Sans commande lisible : non."""
    if entree.get("tool_name") != "Bash":
        return False
    outil = entree.get("tool_input")
    commande = outil.get("command") if isinstance(outil, dict) else None
    if not isinstance(commande, str):
        return False
    mots = _premiers_mots(commande)
    if any(_LANCEURS_PYTHON.fullmatch(m) for m in mots):
        return True
    return "cime" in mots and _TRACE in sortie


def _sortie_de_l_outil(entree: dict) -> str:
    """Tout le texte qu'un outil a rendu : `error` (PostToolUseFailure) ou `tool_response`."""
    morceaux = [entree.get("error"), entree.get("tool_response")]
    texte = []
    for m in morceaux:
        if isinstance(m, str):
            texte.append(m)
        elif isinstance(m, dict):
            texte += [v for v in m.values() if isinstance(v, str)]
    return "\n".join(texte)


def sur_import_cime_manquant(conn, projet, agent, entree) -> list[int]:
    """La sortie d'un outil dit que `cime` ne s'importe pas (bac à sable de l'agent qui ne couvre
    pas la source) : un `signalement` →Assistant et →l'utilisateur, une fois par agent et par heure.
    Le hook tourne hors du bac à sable : lui seul peut l'écrire quand l'agent est muet."""
    sortie = _sortie_de_l_outil(entree)
    trouve = _IMPORT_CIME.search(sortie) if _vient_de_python(entree, sortie) else None
    if trouve is None:
        return []
    nom = agent or "inconnu"
    objet = f"import-cime:{nom}"
    depuis = (datetime.now(timezone.utc) - PAUSE_IMPORT_CIME).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    resume = f"{nom} ne peut pas importer cime ({trouve.group(0)[:70]}) : bac à sable sans la source"
    inscrits = []
    for destinataire in (ASSISTANT, "utilisateur"):
        if conn.execute(
                "SELECT 1 FROM messages WHERE de = 'cime' AND a = ? AND nature = 'signalement'"
                " AND objet = ? AND horodatage >= ? LIMIT 1", (destinataire, objet, depuis)
        ).fetchone():
            continue
        identifiant = signaler(conn, projet, a=destinataire, objet=objet, resume=resume, agent=agent)
        if identifiant is not None:
            inscrits.append(identifiant)
    return inscrits


def sur_facteur_arrete(conn, projet) -> int | None:
    """Un battement périmé (> 30 s, ou jamais battu) alors qu'un message ou un ordre attend
    ⇒ `signalement facteur-arrete` →Assistant, une fois par arrêt (la clé est le dernier
    battement). Rendu au prochain hook de l'Assistant ; clos au retour du facteur."""
    etat = commandes.facteur_arrete(conn)
    if etat is False:
        return None
    attend = conn.execute(
        "SELECT 1 FROM ordres WHERE etat = 'en_file' UNION ALL"
        " SELECT 1 FROM messages m WHERE (SELECT t.etat FROM transitions t WHERE t.message_id = m.id"
        " ORDER BY t.id DESC LIMIT 1) = 'inscrit' AND m.objet IS NOT 'facteur-arrete' LIMIT 1"
    ).fetchone()
    if attend is None:
        return None
    ligne = conn.execute("SELECT battement FROM facteur WHERE id = 1").fetchone()
    cle = f"battement:{ligne[0] if ligne else 'jamais'}"
    depuis = "depuis toujours" if etat is None else f"depuis {etat} s"
    return signaler_une_fois(
        conn, projet, a=ASSISTANT, objet="facteur-arrete", cle=cle,
        resume=f"le facteur est arrêté {depuis} : messages et ordres attendent (cime facteur)")


# --- livraison ---------------------------------------------------------------------------

def _accuser_indirectement(conn, agent, evenement, evenement_id) -> None:
    """Voie hook, pas de trace dans le transcript : tout `PostToolUse`/`Stop` postérieur
    du même agent vaut accusé, marqué `"preuve":"indirecte"`."""
    horodatage = conn.execute("SELECT horodatage FROM evenements WHERE id = ?",
                              (evenement_id,)).fetchone()
    if horodatage is None:
        return
    for (courrier_id,) in conn.execute(
            "SELECT id FROM courriers WHERE a = ? AND etat = 'ouvert' AND voie LIKE 'hook:%'"
            " AND cree <= ?", (agent, horodatage[0])).fetchall():
        for (message_id,) in conn.execute(
                "SELECT l.message_id FROM transitions l WHERE l.courrier_id = ?"
                " AND l.etat = 'livre' AND NOT EXISTS (SELECT 1 FROM transitions p"
                " WHERE p.message_id = l.message_id AND p.id > l.id"
                " AND p.etat IN ('pris_en_compte', 'clos'))", (courrier_id,)).fetchall():
            courrier.acquitter(conn, message_id, agent, {
                "preuve": "indirecte", "evenement": evenement, "evenement_id": evenement_id})


def _prendre(conn, projet, agent, evenement, evenement_id, **preuve) -> str | None:
    c = courrier.prendre(conn, agent, f"hook:{evenement}", "cime",
                         {"evenement": evenement, "evenement_id": evenement_id, **preuve})
    return None if c is None else courrier.formater(conn, c, "hook", projet)


def sur_post_tool_use(conn, projet, agent, evenement_id) -> str | None:
    if not agent:
        return None
    _accuser_indirectement(conn, agent, "PostToolUse", evenement_id)
    return _prendre(conn, projet, agent, "PostToolUse", evenement_id)


def _dette(conn, projet, agent) -> list[dict]:
    return obligations.ouvertes_de(conn, agent)


def _texte_dette(dettes) -> str:
    citees = [f"{d['attendu']} pour {courrier.emetteur_lisible(d['de'])} — {d['resume']}"
              f" (#{d['message_id']})" for d in dettes[:MAX_DETTES_CITEES]]
    reste = len(dettes) - len(citees)
    plus = f" ; et {reste} autre(s)" if reste > 0 else ""
    return "Tu dois encore : " + " ; ".join(citees) + plus


def sur_stop(conn, projet, agent, entree, evenement_id) -> str | None:
    """Dans l'ordre : (1) courrier en attente, (2) dette rappelée une fois, (3) attente d'un
    message jusqu'à `ATTENTE_STOP`. L'Assistant : (1) seulement, sans attente."""
    if not agent:
        return None
    _accuser_indirectement(conn, agent, "Stop", evenement_id)
    texte = _prendre(conn, projet, agent, "Stop", evenement_id, attente_s=0)
    if texte:
        return texte
    if agent != ASSISTANT:
        dettes = _dette(conn, projet, agent)
        actif = bool(entree.get("stop_hook_active"))
        if dettes and not actif:
            return _texte_dette(dettes)
        if dettes and actif and agent.startswith("worker-") \
                and any(d["attendu"] == "travail_pret" for d in dettes):
            coord = superieur(agent, projet)
            if coord:
                # un seul signalement par worker et par obligation, une fois pour toutes.
                du = min(d["message_id"] for d in dettes if d["attendu"] == "travail_pret")
                signaler(conn, projet, a=coord, objet=f"fin-sans-suite:{agent}:{du}", agent=agent,
                         resume=f"{agent} s'est arrêté sans rendre son travail_pret",
                         unique=True, une_fois=True)
    attente = attente_stop(agent)
    debut = _horloge()
    while _horloge() - debut < attente:
        _dormir(min(1.0, max(0.0, attente - (_horloge() - debut))))
        if courrier.en_attente(conn, agent):
            texte = _prendre(conn, projet, agent, "Stop", evenement_id,
                             attente_s=int(_horloge() - debut))
            if texte:
                return texte
    return None


def sur_stop_failure(conn, projet, agent, entree, evenement_id) -> None:
    """Fin de tour par erreur d'API (M-F) : `signalement erreur-api` immédiat au supérieur."""
    if not agent:
        return
    sup = superieur(agent, projet)
    if not sup:
        return
    erreur = str(entree.get("error") or "inconnue")
    signaler(conn, projet, a=sup, objet=f"erreur-api:{agent}", agent=agent,
             resume=f"{agent} : erreur d'API ({erreur})")


# --- accusé de réception (voie tmux) -----------------------------------------------------

def _courrier_tmux_livre(conn, message_id, agent):
    ligne = conn.execute(
        "SELECT l.courrier_id FROM messages m JOIN transitions l ON l.message_id = m.id"
        " AND l.id = (SELECT max(id) FROM transitions WHERE message_id = m.id)"
        " JOIN courriers c ON c.id = l.courrier_id"
        " WHERE m.id = ? AND m.a = ? AND l.etat = 'livre' AND c.voie LIKE 'tmux%'",
        (message_id, agent)).fetchone()
    return None if ligne is None else courrier.charger(conn, ligne[0])


def sur_user_prompt_submit(conn, projet, agent, entree, evenement_id) -> None:
    """Le `prompt` du destinataire est exactement le texte que le facteur a tapé ⇒ accusé.
    Sinon (une frappe de l'utilisateur s'est mêlée) : aucun accusé, `signalement melange` →l'utilisateur."""
    prompt = entree.get("prompt")
    if not agent or not isinstance(prompt, str) or not _PREFIXE.match(prompt):
        return
    for message_id in (int(i) for i in _ID.findall(prompt)):
        c = _courrier_tmux_livre(conn, message_id, agent)
        if c is None:
            continue
        if prompt.strip() != courrier.formater(conn, c, "tmux", projet).strip():
            signaler(conn, projet, a="utilisateur", objet=f"melange:{agent}", agent=agent,
                     resume=f"le message #{message_id} livré à {agent} s'est mêlé à une saisie"
                            " : non acquitté, il sera redonné", unique=True)
            return
        for m in c.messages:
            if etat_livre(conn, m["id"]):
                courrier.acquitter(conn, m["id"], agent, {
                    "evenement": "UserPromptSubmit", "evenement_id": evenement_id})
        return


def etat_livre(conn, message_id) -> bool:
    return etat_message(conn, message_id) == "livre"


# --- reprise ------------------------------------------------------------------------------

def sur_session_start(conn, projet, agent, evenement_id) -> str | None:
    """`cime reprise` rendu sur stdout (M-E) ; le courrier en attente y figure (section (c)),
    pris par `hook:SessionStart` puis accusé « indirect » (pas de trace à attendre)."""
    if not agent:
        return None
    c = courrier.prendre(conn, agent, "hook:SessionStart", "cime",
                         {"evenement": "SessionStart", "evenement_id": evenement_id})
    texte = reprise.texte_reprise(projet, agent)
    if c is not None:
        texte += "\n\nCourrier remis à l'ouverture :\n" + courrier.formater(conn, c, "hook", projet)
        for m in c.messages:
            courrier.acquitter(conn, m["id"], agent, {
                "preuve": "indirecte", "evenement": "SessionStart", "evenement_id": evenement_id})
    return texte + "\n"


# --- autorisations, refus du garde, sessions disparues ------------------------------------

def destinataire_autorisation(projet, agent, classe) -> str:
    """`libre` → le supérieur (coordinateur d'un worker, Assistant d'un
    coordinateur) ; `autonome` → l'Assistant en mode actif, l'utilisateur sinon ; `reserve` → l'utilisateur."""
    if classe == "libre":
        return superieur(agent, projet) or ASSISTANT
    if classe == "autonome":
        return ASSISTANT if autorisations.mode_actif(projet) else UTILISATEUR
    return UTILISATEUR


def sur_permission_request(conn, projet, agent, entree, details) -> None:
    """`signalement autorisation:<demande_id>`, classé avant d'être écrit ; pour une demande `reserve`, une information au supérieur (sans obligation)."""
    if not agent or agent == ASSISTANT or not details.get("demande_id"):
        return
    from cime.fondation.autorisations_auto import classer_autorisation
    demande_id = details["demande_id"]
    outil = entree.get("tool_name") or "?"
    tool_input = entree.get("tool_input")
    classement = classer_autorisation(projet, agent, outil, tool_input, cwd=entree.get("cwd"))
    classe = classement["classe"]
    cible = autorisations.cible_outil(tool_input)
    signaler(conn, projet, a=destinataire_autorisation(projet, agent, classe), agent=agent,
             objet=f"{autorisations.PREFIXE}{demande_id}",
             corps=autorisations.corps(outil, cible, classement),
             resume=autorisations.tronquer(f"{agent} demande {outil} : {cible} [{classe}]",
                                           autorisations.RESUME_MAX))
    if classe == "reserve":
        sup = superieur(agent, projet) or ASSISTANT
        signaler(conn, projet, a=sup, agent=agent, objet=f"{autorisations.PREFIXE_RESERVEE}{demande_id}",
                 resume=autorisations.tronquer(
                     f"{agent} attend l'utilisateur ({classement['theme']}) : {outil} {cible}",
                     autorisations.RESUME_MAX))


def sur_refus_garde(conn, projet, agent, entree, evenement_id, motif) -> None:
    """`signalement refus-garde:<evt>` →supérieur (coordinateur ⇒ Assistant ; l'Assistant
    voit son refus, rien n'est inscrit)."""
    if not agent or agent == ASSISTANT:
        return
    sup = superieur(agent, projet)
    if sup:
        signaler(conn, projet, a=sup, agent=agent, objet=f"refus-garde:{evenement_id}",
                 resume=f"{agent} : {entree.get('tool_name') or 'action'} refusée par la garde "
                        f": {motif}")


def _fin_recente(conn, agent) -> bool:
    limite = (datetime.now(timezone.utc) - FIN_RECENTE).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return conn.execute(
        "SELECT 1 FROM messages WHERE a = ? AND objet LIKE 'fin:%' AND horodatage >= ?",
        (agent, limite)).fetchone() is not None


def _fermeture_voulue(conn, agent) -> bool:
    from cime.signaux import livraison
    debut = conn.execute("SELECT max(id) FROM evenements WHERE agent = ? AND evenement = 'SessionStart'",
                         (agent,)).fetchone()[0]
    return debut is not None and livraison._fermeture_ordonnee(conn, agent, debut)


def sur_session_end(conn, projet, agent, entree) -> None:
    """Session finie avec une obligation ouverte, sans passage par `cime terminer`."""
    if not agent or agent == ASSISTANT or entree.get("reason") in REPRISE_IGNOREE:
        return
    if not obligations.ouvertes_de(conn, agent) or _fin_recente(conn, agent):
        return
    if _fermeture_voulue(conn, agent):
        return                                      # `fermer` / `lancer --remplacer` : pas une panne
    sup = superieur(agent, projet)
    if sup:
        signaler(conn, projet, a=sup, agent=agent, objet=f"session-disparue:{agent}",
                 resume=f"la session de {agent} s'est terminée avec des obligations ouvertes",
                 unique=True)


def consommer_accords_fusion(conn, projet, fusions, evenement_id) -> list[int]:
    """Chaque fusion faite (`resultat=fusionne`) consomme un accord de l'utilisateur pour la
    pointe fusionnée : transition `clos`, preuve `{"par_evenement": N}`. Renvoie les accords
    consommés. Un accord = une fusion."""
    from cime.fondation import garde
    consommes: list[int] = []
    for sha, resultat in fusions:
        if resultat != "fusionne" or sha == "inconnu":
            continue
        libres = [(i, a) for i, a in garde.accords_fusion_libres(projet) if i not in consommes]
        accord = garde.accord_pour(sha, libres)
        if accord is None:
            continue
        inscrire_transition(conn, accord, "clos", "cime", {"par_evenement": evenement_id})
        consommes.append(accord)
    return consommes


def rendre(conn, projet, agent, evenement, entree, evenement_id, details=None) -> str | None:
    """Texte à rendre à l'agent pour cet événement, ou None."""
    sur_facteur_arrete(conn, projet)
    if evenement == "PostToolUse":
        return sur_post_tool_use(conn, projet, agent, evenement_id)
    if evenement == "Stop":
        return sur_stop(conn, projet, agent, entree, evenement_id)
    if evenement == "StopFailure":
        sur_stop_failure(conn, projet, agent, entree, evenement_id)
    elif evenement == "UserPromptSubmit":
        sur_user_prompt_submit(conn, projet, agent, entree, evenement_id)
    elif evenement == "SessionStart":
        return sur_session_start(conn, projet, agent, evenement_id)
    elif evenement == "PermissionRequest":
        sur_permission_request(conn, projet, agent, entree, details or {})
    elif evenement == "SessionEnd":
        sur_session_end(conn, projet, agent, entree)
    return None
