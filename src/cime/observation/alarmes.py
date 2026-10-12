"""Alarmes de l'instantané : la table unique des seuils et le calcul des alarmes.

Aucune alarme ne se calcule sur une mesure absente (`None`) : une source en échec
figure dans `sources`, et cela suffit. Chaque `id` vaut `<type>:<agent ou équipe>:<discriminant>`
et reste stable d'un instantané à l'autre tant que l'alarme dure.
"""

from datetime import datetime, timedelta, timezone

from cime.signaux import echeances

# --- Les seuils ---------------------------------------------------------------------------
# Les seuils de temps des alarmes qui naissent d'une obligation, d'un signalement ou d'une
# livraison sont ceux de `signaux/echeances.py` (ECHELLES et constantes voisines) : source unique.
SEUIL_AUTORISATION = echeances.ECHELLES["autorisation"][1].delai    # → l'utilisateur (page + notif)
SEUIL_QUESTION = echeances.ECHELLES["question"][0].delai            # 1er signal : relance
SEUIL_FIGE = echeances.FIGE
SEUIL_FIGE_GRAVE = echeances.FIGE_GRAVE
SEUIL_REPOS = echeances.ECHELLES["contexte"][1].delai               # contexte_au_repos : au repos depuis…
SEUIL_ASSISTANT_SOURD = echeances.ASSISTANT_SOURD
SEUIL_LIVRAISON_BLOQUEE = echeances.DELAI_OCCUPE
# Mesures hors du registre : leurs seuils restent ici.
SEUIL_CONTEXTE = 0.60                        # contexte_plein : part de la limite (a_voir)
SEUIL_BROUILLON = timedelta(seconds=60)      # brouillon : inactivité minimale de la session (a_voir)
SEUIL_DEMARRAGE = timedelta(minutes=2)       # bloque_au_demarrage (grave)
DUREE_REFUS_VISIBLE = timedelta(minutes=30)  # action_refusee reste visible (a_voir)
SEUIL_ORPHELINE = timedelta(minutes=60)               # session_orpheline : depuis la création (a_voir)
SEUIL_GROS_POSTE_PART = 0.40           # gros_poste : part des jetons lus du projet sur 15 min (provisoire, a_voir)
SEUIL_GROS_POSTE_PLANCHER = 1_000_000  # … seulement si le projet a lu au moins ceci sur 15 min (provisoire)
SEUIL_GROS_POSTE_LUS = 5_000_000       # gros_poste : jetons lus par l'agent sur 15 min (provisoire)
SEUIL_CONTEXTE_REPOS = 150_000         # contexte_au_repos : contexte en tokens (provisoire, a_voir)

GRAVITES = {
    "autorisation_en_attente": "grave",
    "question_sans_reponse": "grave",
    "recouvrement": "grave",
    "session_disparue": "grave",
    "bloque_au_demarrage": "grave",
    "assistant_sourd": "grave",
    "livraison_echouee": "grave",
    "livraison_bloquee": "grave",
    "facteur_arrete": "grave",
    "fin_sans_suite": "grave",
    "brouillon": "a_voir",
    "contexte_plein": "a_voir",
    "hors_perimetre": "a_voir",
    "action_refusee": "a_voir",
    "fige": "a_voir",  # grave au-delà de SEUIL_FIGE_GRAVE
    "session_orpheline": "a_voir",
    "gros_poste": "a_voir",
    "contexte_au_repos": "a_voir",
    "retard_sur_base": "info",
}
_ORDRE = {"grave": 0, "a_voir": 1, "info": 2}

# --- Calcul -----------------------------------------------------------------------------

def _dt(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


def _iso(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _minutes(delta: timedelta) -> int:
    return int(delta.total_seconds() // 60)


def _milliers(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _alarme(type_, cle, discriminant, agents, equipes, depuis, mesure, quoi_faire, gravite=None,
            destinataire=None) -> dict:
    suffixe = f":{discriminant}" if discriminant != "" else ""  # gros_poste : id stable, sans discriminant
    return {"id": f"{type_}:{cle}{suffixe}", "type": type_, "gravite": gravite or GRAVITES[type_],
            "agents": agents, "equipes": equipes, "depuis": depuis,
            "mesure": mesure, "quoi_faire": quoi_faire, "destinataire": destinataire}


def _superieur(agent: str, equipe_de) -> str:
    """Chaîne worker → coordinateur → Assistant → l'utilisateur."""
    if agent == "assistant":
        return "utilisateur"
    if agent.startswith("worker-"):
        equipe = equipe_de(agent)
        return f"coord-{equipe}" if equipe else "assistant"
    return "assistant"


def _resoudre(cible: str, debiteur: str, equipe_de) -> str:
    if cible == "sup":
        return _superieur(debiteur, equipe_de)
    if cible == "supsup":
        return _superieur(_superieur(debiteur, equipe_de), equipe_de)
    return debiteur if cible == "debiteur" else cible  # "assistant" | "utilisateur"


def _destinataire(echelle: str, age: timedelta, debiteur: str, equipe_de) -> str:
    """Qui l'échelle `echeances.ECHELLES[echelle]` a atteint à l'âge `age` : le débiteur tant
    qu'aucune marche à cible n'est franchie."""
    cible, cumul = debiteur, timedelta(0)
    for etape in echeances.ECHELLES[echelle]:
        cumul += etape.delai
        if age < cumul:
            break
        if etape.cible:
            cible = _resoudre(etape.cible, debiteur, equipe_de)
    return cible


def _depuis_les_obligations(agents, internes, signaux, terminees, maintenant, eqs, equipe_de) -> list[dict]:
    """Alarmes qui se lisent dans les obligations, les transitions et le battement du facteur
    Aucune si `signaux` est None (registre en échec)."""
    if signaux is None:
        return []
    sortie: list[dict] = []
    par_id = {a["id"]: a for a in agents}
    for o in signaux.get("obligations") or []:
        objet, depuis = o["objet"] or "", _dt(o["horodatage"])
        if depuis is None or ":" not in objet:
            continue
        age, sujet = maintenant - depuis, objet.split(":", 1)[1]
        if objet.startswith("autorisation:"):
            a = par_id.get(o.get("agent_demande"))
            auto = (internes.get(a["id"], {}).get("autorisation") or {}) if a else {}
            if (a is None or a["etat"] != "attend_autorisation" or auto.get("demande_id") != sujet
                    or age <= SEUIL_AUTORISATION):
                continue
            sortie.append(_alarme(
                "autorisation_en_attente", a["id"], f"perm-{sujet}", [a["id"]], eqs(a["id"]), o["horodatage"],
                f"Signalement {objet} (n°{o['message_id']}) sans réponse depuis {_minutes(age)} min "
                f"(seuil {_minutes(SEUIL_AUTORISATION)} min) : {auto.get('tool_name')} « {auto.get('resume_outil')} », "
                "sans Stop, UserPromptSubmit ni PostToolUse depuis.",
                "Autoriser ou refuser la demande dans « Ce qui t'attend » : l'agent est immobile tant qu'elle n'est pas tranchée.",
                destinataire=_destinataire("autorisation", age, o["a"], equipe_de)))
        elif objet.startswith(("session-disparue:", "fin-sans-suite:")):
            agent = sujet
            if eqs(agent) and set(eqs(agent)) <= terminees:
                continue
            type_ = "session_disparue" if objet.startswith("session-disparue:") else "fin_sans_suite"
            session = (par_id.get(agent) or {}).get("session_tmux") or f"msg-{o['message_id']}"
            if type_ == "session_disparue":
                mesure = (f"Signalement {objet} (n°{o['message_id']}) ouvert depuis {_minutes(age)} min : "
                          f"la session de {agent} a disparu sans fin déclarée ({o['resume']}).")
                faire = ("Demander à l'Assistant de vérifier ce que l'agent a laissé et de le faire relancer "
                         "si sa tâche n'est pas rendue.")
            else:
                mesure = (f"Signalement {objet} (n°{o['message_id']}) ouvert depuis {_minutes(age)} min : "
                          f"{agent} s'est arrêté avec une obligation ouverte ({o['resume']}).")
                faire = "Demander à l'Assistant pourquoi l'agent s'est arrêté, et de le relancer ou de réassigner sa tâche."
            sortie.append(_alarme(
                type_, agent, session if type_ == "session_disparue" else o["message_id"], [agent], eqs(agent),
                o["horodatage"], mesure, faire,
                destinataire=_destinataire("signalement_grave", age, o["a"], equipe_de)))
    for e in signaux.get("echecs") or []:
        depuis = _dt(e["depuis"])
        age = (maintenant - depuis) if depuis else timedelta(0)
        sortie.append(_alarme(
            "livraison_echouee", e["a"], f"msg-{e['id']}", [e["a"]], eqs(e["a"]), e["depuis"],
            f"Le message n°{e['id']} pour {e['a']} est en échec de livraison ({e['resume']}).",
            "Demander à l'Assistant de relancer l'agent ou de redire le message autrement ; le message ne sera pas retenté seul.",
            destinataire=_destinataire("signalement_info", age, e.get("signale_a") or _superieur(e["a"], equipe_de),
                                       equipe_de)))
    for a in agents:
        file = a.get("file") or []
        if a["role"] == "utilisateur" or a["etat"] != "inconnu" or not file:
            continue
        premier = min(file, key=lambda m: m["depuis"])
        depuis = _dt(premier["depuis"])
        if depuis and maintenant - depuis > SEUIL_LIVRAISON_BLOQUEE:
            sortie.append(_alarme(
                "livraison_bloquee", a["id"], f"msg-{premier['id']}", [a["id"]], eqs(a["id"]), premier["depuis"],
                f"Le message n°{premier['id']} attend {a['id']} depuis {_minutes(maintenant - depuis)} min "
                f"(seuil {_minutes(SEUIL_LIVRAISON_BLOQUEE)} min) et l'agent n'a émis ni Stop ni idle_prompt : "
                "rien ne dit que sa session écoute.",
                "Vérifier que la session de l'agent existe et répond ; demander à l'Assistant de la relancer sinon."))
    facteur, attente = signaux.get("facteur"), signaux.get("attente") or {}
    if facteur and facteur.get("arrete") and (attente.get("messages") or attente.get("ordres")):
        battement = _dt(facteur.get("battement"))
        age = (maintenant - battement) if battement else timedelta(0)
        sortie.append(_alarme(
            "facteur_arrete", "facteur", facteur.get("battement") or "jamais", [], [], facteur.get("battement"),
            ("Le facteur n'a jamais battu" if battement is None else
             f"Dernier battement du facteur il y a {int(age.total_seconds())} s "
             f"(seuil {echeances.PEREMPTION_BATTEMENT} s)")
            + f" ; {attente.get('messages', 0)} message(s) et {attente.get('ordres', 0)} ordre(s) attendent.",
            "Relancer le facteur (`cime facteur`) ou demander à l'Assistant de le faire : rien n'est livré tant qu'il est arrêté.",
            destinataire=_destinataire("signalement_grave", age, "assistant", equipe_de)))
    sourd, idle = signaux.get("courrier_assistant"), _dt(signaux.get("idle_prompt_assistant"))
    cree = _dt((sourd or {}).get("cree"))
    if sourd and idle and cree and idle >= cree and maintenant - idle > SEUIL_ASSISTANT_SOURD:
        sortie.append(_alarme(
            "assistant_sourd", "assistant", sourd["id"], ["assistant"], [], sourd["cree"],
            f"Le courrier tmux n°{sourd['id']} tapé dans l'invite vide de l'Assistant à {sourd['cree']} n'est pas "
            f"acquitté, et l'Assistant est au repos (idle_prompt) depuis {_minutes(maintenant - idle)} min "
            f"(seuil {_minutes(SEUIL_ASSISTANT_SOURD)} min).",
            "Regarder le terminal de l'Assistant : le message n'a pas été pris ; lui écrire directement.",
            destinataire="utilisateur"))
    return sortie


def calculer(*, agents: list[dict], internes: dict, equipes: list[dict] | None,
             recouvrements: list[dict] | None, questions: list[dict] | None,
             refus: list[dict] | None, tmux_ok: bool,
             branche_reference: str | None, equipe_de, maintenant: datetime,
             dates_git: dict | None = None, orphelines: list[dict] | None = None,
             signaux: dict | None = None) -> list[dict]:
    """Toutes les alarmes, les plus graves d'abord.

    `internes[agent]` : {"etat_evenement_id", "autorisation" (dict | None),
    "activite_epoch" (int | None), "dernier_signe" (iso | None), "connu_registre" (bool),
    "contexte_depuis" (iso | None : 1re réponse au-dessus du seuil dans la série en cours)}.
    `dates_git[équipe]` : {"dates_fichiers", "retard_depuis"} de `lire_git` (depuis mesurés).
    `orphelines` : sessions au préfixe du projet hors organigramme, [{"nom", "depuis", "activite"}].
    `signaux` : ce que le registre dit des obligations (`observation.registre._signaux`) :
    {"obligations": signalements ouverts, "echecs": livraisons échouées, "facteur": {...},
    "attente": {"messages", "ordres"}, "courrier_assistant": {...} | None, "idle_prompt_assistant"}.
    `None` = registre en échec : aucune des alarmes qui en dépendent n'est calculée.
    Chaque alarme porte un `destinataire` : où en est la chaîne (`echeances.ECHELLES`).
    `equipe_de(agent_id)` : nom d'équipe ou None. Un argument `None` = mesure absente.
    """
    sortie: list[dict] = []
    lus_projet = sum(a["consommation"]["15min"]["lus"] for a in agents if a.get("consommation"))
    terminees = {e["nom"] for e in equipes or [] if e.get("statut") == "terminee"}

    def eqs(*ids):
        return sorted({e for e in map(equipe_de, ids) if e})

    for a in agents:
        aid, etat = a["id"], a["etat"]
        if a["role"] == "utilisateur":
            continue
        info = internes.get(aid, {})
        depuis = _dt(a["etat_depuis"])
        session = a["session_tmux"]

        if a["brouillon"] is not None and info.get("activite_epoch") is not None:
            texte = a["brouillon"]["texte"]
            extrait = texte if len(texte) <= 80 else texte[:79] + "…"
            sortie.append(_alarme(
                "brouillon", aid, info["activite_epoch"], [aid], eqs(aid), a["brouillon"]["depuis"],
                f"Capture tmux de {session} : texte non envoyé dans l'invite (« {extrait} »), "
                f"texte présent, dernière activité de la fenêtre le {a['brouillon']['depuis']} "
                f"(pas l'heure d'apparition du brouillon).",
                "Faire vérifier par l'Assistant : ce texte partirait avec le prochain message envoyé à cet agent ; l'envoyer ou l'effacer."))

        dem = info.get("demarrage")
        if dem and dem.get("ecran") and dem.get("sans_evenement") is True:
            creee = _dt(dem["creee"])
            if creee and maintenant - creee > SEUIL_DEMARRAGE:
                ecran = {"confiance": "confiance du dossier", "imports": "imports externes"}.get(
                    dem["ecran"], "écran de démarrage")
                sortie.append(_alarme(
                    "bloque_au_demarrage", aid, dem["activite_epoch"], [aid], eqs(aid), dem["creee"],
                    f"Écran « {ecran} » affiché depuis {_minutes(maintenant - creee)} min "
                    f"(seuil {_minutes(SEUIL_DEMARRAGE)} min) : aucun événement de l'agent depuis la création de {session}.",
                    f"Répondre dans le terminal de {session} (le choix par défaut est « non » : il quitte ou "
                    "désactive les imports), ou demander à l'Assistant de relancer l'agent depuis un dossier déjà approuvé."))

        ctx = a["contexte"]
        if ctx and ctx.get("limite") and ctx.get("tokens") is not None and ctx["tokens"] > SEUIL_CONTEXTE * ctx["limite"]:
            part = round(100 * ctx["tokens"] / ctx["limite"])
            sortie.append(_alarme(
                "contexte_plein", aid, a["modele"], [aid], eqs(aid), info.get("contexte_depuis"),
                f"{_milliers(ctx['tokens'])} jetons sur {_milliers(ctx['limite'])} ({part} %, "
                f"seuil {round(100 * SEUIL_CONTEXTE)} %), lus dans le transcript.",
                "Prévoir un /compact de cet agent entre deux sujets, avant que sa mémoire de travail ne se dégrade."))

        conso = a.get("consommation")
        if conso:
            lus15 = conso["15min"]["lus"]
            part = lus15 / lus_projet if lus_projet else 0
            if lus15 > SEUIL_GROS_POSTE_LUS or (part > SEUIL_GROS_POSTE_PART
                                                 and lus_projet >= SEUIL_GROS_POSTE_PLANCHER):
                sortie.append(_alarme(
                    "gros_poste", aid, "", [aid], eqs(aid), _iso(maintenant),
                    f"{_milliers(lus15)} jetons lus en 15 min ({round(100 * part)} % du projet, "
                    f"{_milliers(lus_projet)} au total ; seuils {_milliers(SEUIL_GROS_POSTE_LUS)} jetons, ou "
                    f"{round(100 * SEUIL_GROS_POSTE_PART)} % si le projet lit au moins {_milliers(SEUIL_GROS_POSTE_PLANCHER)}).",
                    "Regarder ce que fait l'agent ; le compacter ou réduire ses tours."))

        ctx_tokens = (a["contexte"] or {}).get("tokens") if a.get("contexte") else None
        if (etat == "au_repos" and depuis and maintenant - depuis > SEUIL_REPOS
                and ctx_tokens is not None and ctx_tokens > SEUIL_CONTEXTE_REPOS):
            sortie.append(_alarme(
                "contexte_au_repos", aid, int(depuis.timestamp()), [aid], eqs(aid), a["etat_depuis"],
                f"{_milliers(ctx_tokens)} jetons de contexte, agent au repos depuis "
                f"{_minutes(maintenant - depuis)} min (seuils {_milliers(SEUIL_CONTEXTE_REPOS)} jetons, "
                f"{_minutes(SEUIL_REPOS)} min).",
                "À compacter avant son prochain tour."))

        # fige : travaille, mais ni événement de registre ni activité de la fenêtre depuis SEUIL_FIGE
        signe, activite = _dt(info.get("dernier_signe")), _dt(info.get("activite"))
        if etat == "travaille" and signe and activite:
            calme = maintenant - max(signe, activite)
            if calme > SEUIL_FIGE:
                sortie.append(_alarme(
                    "fige", aid, int(activite.timestamp()), [aid], eqs(aid),
                    info["dernier_signe"] if signe >= activite else info["activite"],
                    f"État « travaille », mais aucun événement au registre depuis {_minutes(maintenant - signe)} min "
                    f"et aucune activité de la fenêtre {session} depuis {_minutes(maintenant - activite)} min "
                    f"(seuils {_minutes(SEUIL_FIGE)} min, grave à {_minutes(SEUIL_FIGE_GRAVE)} min).",
                    f"Regarder le terminal de {session} : commande qui ne rend pas la main ou agent sorti ; "
                    "demander à l'Assistant de le débloquer ou de le relancer.",
                    "grave" if calme > SEUIL_FIGE_GRAVE else None))


    sortie.extend(_depuis_les_obligations(agents, internes, signaux, terminees, maintenant, eqs, equipe_de))

    for q in questions or []:
        dq = _dt(q["horodatage"])
        if dq and maintenant - dq > SEUIL_QUESTION:
            de, a_ = q["de"], q["a"]
            faire = (f"Demander à l'Assistant de répondre à {de}, ou de trancher sa question."
                     if a_ == "assistant" else
                     f"Demander à l'Assistant de faire répondre {a_} à {de}.")
            mesure = (f"Question de {de} à {a_} sans réponse depuis {_minutes(maintenant - dq)} min "
                      f"(seuil {_minutes(SEUIL_QUESTION)} min) : « {q['resume']} »")
            sortie.append(_alarme(
                "question_sans_reponse", de, q["id"], [x for x in (de, a_) if x], eqs(de, a_), q["horodatage"],
                mesure, faire, destinataire=_destinataire("question", maintenant - dq, a_, equipe_de)))

    branches = {e["nom"]: e.get("branche") for e in equipes or []}
    for r in recouvrements or []:
        noms = sorted(r["equipes"])
        sortie.append(_alarme(
            "recouvrement", "+".join(noms), r["fichier"], [f"coord-{n}" for n in noms], noms, r.get("depuis"),
            f"git diff : les branches {', '.join(str(branches.get(n)) for n in noms)} modifient toutes {r['fichier']}.",
            "Faire trancher par l'Assistant quelle équipe garde ce fichier, avant toute fusion."))

    for e in equipes or []:
        dates = (dates_git or {}).get(e["nom"]) or {}
        for f in e.get("hors_perimetre") or []:
            sortie.append(_alarme(
                "hors_perimetre", e["nom"], f, [f"coord-{e['nom']}"], [e["nom"]],
                (dates.get("dates_fichiers") or {}).get(f),
                f"git diff : {f} est modifié sur {e['branche']}, hors du périmètre déclaré de l'équipe {e['nom']}.",
                "Demander à l'Assistant d'élargir le périmètre de l'équipe ou de faire annuler la modification."))
        retard = e.get("retard_sur_base")
        if retard is not None and retard > 0 and branche_reference:
            sortie.append(_alarme(
                "retard_sur_base", e["nom"], branche_reference, [f"coord-{e['nom']}"], [e["nom"]],
                dates.get("retard_depuis"),
                f"git rev-list : la branche {e['branche']} a {retard} commit(s) de retard sur {branche_reference}.",
                "Rien d'urgent ; l'équipe devra se mettre à jour avant sa prochaine fusion."))

    for o in orphelines or []:
        creee = _dt(o["depuis"])
        if creee and maintenant - creee > SEUIL_ORPHELINE:
            sortie.append(_alarme(
                "session_orpheline", o["nom"], int(creee.timestamp()), [], [], o["depuis"],
                f"La session tmux {o['nom']} existe depuis {_minutes(maintenant - creee)} min "
                f"(seuil {_minutes(SEUIL_ORPHELINE)} min) et n'est ni l'Assistant, ni un coordinateur, "
                f"ni un worker d'une équipe connue ; dernière activité le {o['activite']}.",
                "Demander à l'Assistant si cette session (essai, intégration) sert encore ; sinon la faire fermer."))

    for r in refus or []:
        dr = _dt(r["horodatage"])
        if dr and maintenant - dr < DUREE_REFUS_VISIBLE:
            agent = r["agent"] or "inconnu"
            sortie.append(_alarme(
                "action_refusee", agent, r["id"], [agent] if r["agent"] else [], eqs(agent), r["horodatage"],
                f"Le garde a refusé {r['tool_name']} « {r['resume_outil']} » (événement PreToolUse {r['id']}) : {str(r['motif']).rstrip(' .')}.",
                "L'agent a tenté une action interdite (push, fusion, secret…) : demander à l'Assistant pourquoi, avant qu'il ne réessaie autrement."))

    for al in sortie:  # destinataire par défaut : le supérieur du premier agent concerné
        if al["destinataire"] is None:
            al["destinataire"] = _superieur(al["agents"][0], equipe_de) if al["agents"] else "assistant"
    sortie.sort(key=lambda x: (_ORDRE[x["gravite"]], x["depuis"] or "", x["id"]))
    return sortie
