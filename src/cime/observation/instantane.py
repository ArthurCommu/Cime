"""L'instantané de l'entreprise : assemble les collecteurs.

Lecture seule de bout en bout. Une mesure qui a échoué vaut `None`, jamais zéro, et sa
source figure en échec dans `sources` ; aucune alarme n'est calculée sur elle.
"""

import json
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from . import alarmes, charge, git, registre, structure, tmux, transcripts

VERSION = 2
_TITRE_TACHE = re.compile(r"^#\s*Tâche\s*:\s*(.+?)\s*$")
_ACTIONS = {"decision": ["trancher"], "donnee": ["deposer"], "cloture": ["cloturer"], "rapport": ["lu"]}


def _iso(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _epoch(iso: str | None) -> int | None:
    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    except (AttributeError, ValueError):
        return None


def _regrouper(nom: str, parties: list[dict]) -> dict:
    echecs = [p for p in parties if not p.get("ok")]
    if not echecs:
        return {"nom": nom, "ok": True}
    return {"nom": nom, "ok": False, "erreur": " ; ".join(p.get("erreur", p["nom"]) for p in echecs)}


def _echec(nom: str, erreur: str) -> dict:
    return {"nom": nom, "ok": False, "erreur": erreur}


def _titre_tache(racine: Path, equipe: str | None, tache: str | None) -> str | None:
    if not equipe or not tache:
        return None
    fichier = racine / ".orga" / "teams" / equipe / "tasks" / "in-progress" / f"{tache}.md"
    try:
        with open(fichier, encoding="utf-8") as f:
            for ligne in f:
                if m := _TITRE_TACHE.match(ligne):
                    return m.group(1)
                if ligne.strip():
                    return tache
    except (OSError, UnicodeDecodeError):
        return None
    return tache


def _decouper_worker(aid: str, equipes: list[str]) -> tuple[str | None, str | None]:
    """`worker-<équipe>-<tâche>` : le plus long nom d'équipe connu qui convient, sinon le 1er segment."""
    reste = aid.removeprefix("worker-")
    for nom in sorted(equipes, key=len, reverse=True):
        if reste.startswith(f"{nom}-"):
            return nom, reste[len(nom) + 1:] or None
    tete, _, queue = reste.partition("-")
    return tete or None, queue or None


def instantane(projet: Path, maintenant: datetime | None = None, *, complet: bool = False) -> dict:
    """`complet=False` (défaut) masque le contenu de la conversation utilisateur ↔ Assistant."""
    debut = time.perf_counter()
    maintenant = maintenant or datetime.now(timezone.utc)
    racine = Path(projet)

    proj, src_manifeste = structure.lire_projet(racine)
    if proj:
        racine = Path(proj["racine"])
    prefixe = proj["prefixe"] if proj else None

    with ThreadPoolExecutor(max_workers=5) as pool:
        f_reg = pool.submit(registre.lire_registre, racine, maintenant)
        f_tmux = pool.submit(tmux.lister_sessions, prefixe) if prefixe else None
        f_eq = pool.submit(structure.lire_equipes, racine, proj) if proj else None
        f_charge = pool.submit(charge.lire_charge, racine)
        equipes_l, src_equipes = f_eq.result() if f_eq else (None, _echec("equipes", "manifeste en échec"))
        f_git = None
        if proj and equipes_l is not None:
            f_git = pool.submit(git.lire_git, racine, proj["branche_reference"], equipes_l)
        sessions, src_tmux = f_tmux.result() if f_tmux else (None, _echec("tmux", "préfixe des sessions inconnu : manifeste en échec"))
        brouillons, src_invites = None, None
        if sessions is not None:
            f_brouillons = pool.submit(tmux.lire_invites, list(sessions), prefixe)
        try:
            bloc_charge, src_charge = f_charge.result()
        except Exception as e:  # noqa: BLE001 — une collecte qui lève reste une source en échec
            bloc_charge, src_charge = None, _echec("charge", str(e) or type(e).__name__)
        reg, src_registre = f_reg.result()
        if reg is not None:  # l'émetteur `cime` n'est pas un agent
            reg["agents"] = {a: r for a, r in reg["agents"].items() if a != "cime"}

        # transcripts : chemin donné par le dernier hook, sinon recherche par session_id, sinon
        # (agent en session tmux dont le cwd n'est partagé avec aucune autre session) par cwd
        def _transcript(item):
            aid, info, cwd = item
            chemin = info.get("transcript_path")
            if not chemin or not Path(chemin).is_file():
                chemin = transcripts.trouver_transcript(info.get("session_id") or "")
            repli = False
            if chemin is None and cwd:
                chemin = transcripts.trouver_par_cwd(cwd)
                repli = chemin is not None
            if chemin is None:
                return None, _echec("transcript", f"transcript introuvable (session {info.get('session_id')})"), None, None
            res, src = transcripts.lire_transcript(Path(chemin))
            ctx = (res or {}).get("contexte") or {}
            depuis = None
            if ctx.get("limite") and ctx.get("tokens") is not None \
                    and ctx["tokens"] > alarmes.SEUIL_CONTEXTE * ctx["limite"]:
                depuis = transcripts.premiere_reponse_au_dessus(
                    Path(chemin), alarmes.SEUIL_CONTEXTE * ctx["limite"])
            conso = transcripts.consommation(Path(chemin), maintenant)
            if repli:
                if res and res.get("contexte"):
                    res = {**res, "contexte": {**res["contexte"], "source": "transcript:cwd"}}
                if conso:
                    conso["source"] = "transcript:cwd"
            return res, src, depuis, conso

        agents_reg = reg["agents"] if reg is not None else {}
        endormis = reg["endormis"] if reg is not None else {}
        cwds = [s.get("cwd") for s in (sessions or {}).values() if s.get("cwd")]
        cwd_de = {s["identite"]: s["cwd"] for s in (sessions or {}).values()
                  if s.get("identite") and s.get("cwd") and cwds.count(s["cwd"]) == 1}
        a_lire = {aid: (aid, info, cwd_de.get(aid)) for aid, info in agents_reg.items()}
        for aid, cwd in cwd_de.items():
            a_lire.setdefault(aid, (aid, {}, cwd))
        lus = dict(zip(a_lire, pool.map(_transcript, a_lire.values())))
        if sessions is not None:
            brouillons, src_invites = f_brouillons.result()
        git_d, src_git = f_git.result() if f_git else (None, _echec("git", "équipes inconnues : structure en échec"))

    # --- sources --------------------------------------------------------------------
    src_structure = _regrouper("structure", [src_manifeste, src_equipes])
    if reg is None:
        src_transcripts = _echec("transcripts", "aucun transcript localisable : registre en échec")
    else:
        parties = [{**lus[aid][1], "erreur": f"{aid} : {lus[aid][1].get('erreur')}"} for aid in agents_reg]
        src_transcripts = _regrouper("transcripts", parties)
    src_tmux_g = _regrouper("tmux", [src_tmux] + ([src_invites] if src_invites else []))

    # --- identités ------------------------------------------------------------------
    fil = reg["fil"] if reg is not None else None
    # questions : les obligations de réponse ouvertes du registre, du plus récent au plus ancien
    questions = reg["questions_en_attente"] if reg is not None else None
    noms_equipes = [e["nom"] for e in equipes_l or []]
    vus = set(agents_reg) | {s["identite"] for s in (sessions or {}).values() if s.get("identite")}
    # équipe spéciale : coordinateur seulement s'il a été vu (tmux ou registre), sinon il
    # paraîtrait « arrêté » sans avoir jamais démarré
    coords = {f"coord-{e['nom']}" for e in equipes_l or [] if not e["speciale"]}
    coords |= {a for a in vus if a.startswith("coord-")}
    coords |= {q["de"] for q in questions or [] if q["de"] and q["de"].startswith("coord-")}
    workers = {a for a in vus if a.startswith("worker-")}

    def equipe_de(aid: str | None) -> str | None:
        if not aid:
            return None
        if aid.startswith("coord-"):
            return aid.removeprefix("coord-")
        if aid.startswith("worker-"):
            return _decouper_worker(aid, noms_equipes)[0]
        return None

    demandeurs = {q["de"]: q for q in questions or []}  # du plus récent au plus ancien : la plus ancienne gagne

    # modèles observés : transcripts, puis SessionStart du registre
    def modele_de(aid):
        t = lus.get(aid, (None, None, None, None))[0]
        return (t or {}).get("modele") or agents_reg.get(aid, {}).get("modele")

    observes = {m for m in map(modele_de, vus) if m}
    sans_prix = sorted(m for m in observes if m not in transcripts.PRIX_PAR_MTOK)
    src_tarifs = (_echec("tarifs", "aucun prix connu pour : " + ", ".join(sans_prix))
                  if sans_prix else {"nom": "tarifs", "ok": True})

    tmux_ok = sessions is not None
    agents: list[dict] = []
    internes: dict = {}

    def construire(aid, role, equipe, parent, tache, modele_defaut):
        session = f"{prefixe}-{aid}" if prefixe else None
        vivant = (session in sessions) if tmux_ok and session else None
        r = agents_reg.get(aid)
        dernier = r["dernier_evenement"] if r else None
        if role == "coordinateur" and vivant is False and aid in endormis:
            etat, depuis, source = "endormi", endormis[aid], "registre:CoordEndormi"
        elif dernier and dernier["evenement"] == "SessionEnd":
            etat, depuis, source = "arrete", dernier["horodatage"], "hook:SessionEnd"
        elif tmux_ok and vivant is False and role != "assistant":  # l'Assistant peut vivre hors tmux
            etat, depuis, source = "arrete", dernier["horodatage"] if dernier else None, "tmux:session_absente"
        elif reg is None:
            etat, depuis, source = "inconnu", None, None
        elif r is None or r["etat"] == "inconnu":
            etat, depuis, source = "inconnu", sessions[session]["creee"] if vivant else None, "aucun_evenement"
        else:
            etat, depuis, source = r["etat"], r["etat_depuis"], r["etat_source"]
            if etat == "au_repos" and aid in demandeurs:
                q = demandeurs[aid]
                etat, depuis, source = "attend_reponse", q["horodatage"], f"{q.get('source', 'registre')}:question"
        t = lus.get(aid, (None, None, None, None))[0] or {}
        brouillon = None
        activite = sessions[session]["activite"] if vivant else None
        invite = (brouillons or {}).get(session) or {}
        dt_activite = alarmes._dt(activite)
        if (role != "assistant" and vivant and invite.get("brouillon")
                and dt_activite and maintenant - dt_activite > alarmes.SEUIL_BROUILLON):
            brouillon = {"texte": invite["brouillon"], "depuis": activite}
        demarrage = None
        if role != "assistant" and vivant and reg is not None and invite.get("ecran_demarrage"):
            creee = sessions[session]["creee"]
            demarrage = {"ecran": invite["ecran_demarrage"], "creee": creee,
                         "activite_epoch": _epoch(activite),
                         "sans_evenement": (dernier is None or dernier["horodatage"] < creee)}
        agents.append({
            "id": aid, "role": role, "equipe": equipe, "parent": parent,
            "session_tmux": session, "vivant": vivant,
            "etat": etat, "etat_depuis": depuis, "etat_source": source,
            "tache": tache,
            "derniere_phrase": r["derniere_phrase"] if r else None,
            "modele": modele_de(aid) or (sessions[session].get("modele_lancement") if vivant else None) or modele_defaut,
            "contexte": t.get("contexte"),
            "cout_usd_estime": t.get("cout_usd_estime") if src_tarifs["ok"] else None,
            "brouillon": brouillon,
            "consommation": lus.get(aid, (None, None, None, None))[3],
            **_modele_2_0(reg, aid),
        })
        internes[aid] = {
            "etat_evenement_id": r.get("etat_evenement_id") if r else None,
            "autorisation": r.get("autorisation_ouverte") if r else None,
            "activite_epoch": _epoch(activite) if brouillon else None,
            "dernier_signe": dernier["horodatage"] if dernier else None,
            "activite": activite,
            "connu_registre": r is not None,
            "demarrage": demarrage,
            "contexte_depuis": lus.get(aid, (None, None, None, None))[2],
        }

    agents.append({"id": "utilisateur", "role": "utilisateur", "equipe": None, "parent": None,
                   "session_tmux": None, "vivant": None, "etat": "inconnu", "etat_depuis": None,
                   "etat_source": None, "tache": None, "derniere_phrase": None, "modele": None,
                   "contexte": None, "cout_usd_estime": None, "brouillon": None,
                   "consommation": None, **_modele_2_0(reg, "utilisateur")})
    construire("assistant", "assistant", None, "utilisateur", None, proj and proj.get("modele_assistant"))
    for aid in sorted(coords):
        consigne = next((m["resume"] for m in fil or []
                         if m.get("nature") == "consigne" and m.get("a") == aid), None)
        construire(aid, "coordinateur", equipe_de(aid), "assistant", consigne,
                   proj and proj.get("modele_coordinateur"))
    for aid in sorted(workers):
        eq, tache = _decouper_worker(aid, noms_equipes)
        construire(aid, "worker", eq, f"coord-{eq}" if eq else None,
                   _titre_tache(racine, eq, tache), None)

    # --- équipes --------------------------------------------------------------------
    equipes = []
    for e in equipes_l or []:
        g = (git_d or {}).get("equipes", {}).get(e["nom"]) if git_d else None
        membres = [a for a in agents if a["equipe"] == e["nom"]]
        if e["cloturee"]:
            statut = "terminee"
        elif reg is None:
            statut = None  # registre en échec : états inconnus
        elif any(a["etat"] in ("attend_autorisation", "attend_reponse") for a in membres):
            statut = "bloquee"
        elif any(a["etat"] == "travaille" or (a["role"] == "worker" and a["vivant"] is True)
                 for a in membres):
            statut = "active"
        elif membres and all(a["etat"] in ("au_repos", "arrete", "endormi") for a in membres):
            statut = "au_repos"
        else:
            statut = None  # état non mesuré : la page affiche « non mesuré »
        equipes.append({
            "nom": e["nom"], "mission": e["mission"], "speciale": e["speciale"], "statut": statut,
            "cloturee_le": e.get("cloturee_le"),
            "branche": e["branche"], "commit": g["commit"] if g else None, "worktree": e["worktree"],
            "avancement": e["avancement"],
            "fichiers_touches": g["fichiers_touches"] if g else None,
            "perimetre_declare": e["perimetre_declare"],
            "hors_perimetre": g["hors_perimetre"] if g else None,
            "retard_sur_base": g["retard_sur_base"] if g else None,
            "en_avance_sur_base": g.get("en_avance_sur_base") if g else None,
            "depend_de": e["depend_de"],
        })

    # --- ce qui attend l'utilisateur -------------------------------------------------------
    attentes = []
    for a in agents:
        auto = internes.get(a["id"], {}).get("autorisation")
        if a["etat"] != "attend_autorisation" or not auto:
            continue
        repondable = bool(auto.get("demande_id"))
        attentes.append({
            "message_id": None, "objet": None,
            "id": f"perm-{auto['demande_id']}" if repondable else f"perm-evt-{internes[a['id']]['etat_evenement_id']}",
            "nature": "autorisation",
            "titre": f"{auto.get('tool_name')} : {auto.get('resume_outil')}",
            "bloque": f"{a['id']} : {a['tache']}" if a["tache"] else a["id"],
            "depuis": auto.get("depuis"), "agent": a["id"], "equipe": a["equipe"],
            "actions": ["autoriser", "refuser"] if repondable else [],
        })
    for m in (reg or {}).get("attentes_utilisateur") or []:
        attentes.append({
            "id": m["id"], "message_id": m["message_id"], "objet": m["objet"],
            "nature": m["nature"], "titre": m["resume"],
            "bloque": m.get("equipe"), "depuis": m["horodatage"], "agent": m["origine"],
            "equipe": m.get("equipe") or equipe_de(m["origine"]),
            "actions": _actions_de(m),
        })

    # --- sessions hors organigramme ----------------------------------------------
    def rattachee(identite):
        if identite == "assistant":
            return True
        return bool(identite) and identite.startswith(("coord-", "worker-")) and equipe_de(identite) in noms_equipes

    orphelines = None if not tmux_ok else [
        {"nom": nom, "depuis": s["creee"], "activite": s["activite"]}
        for nom, s in sorted(sessions.items()) if not rattachee(s.get("identite"))]

    liste_alarmes = alarmes.calculer(
        agents=agents, internes=internes, equipes=equipes if equipes_l is not None else None,
        recouvrements=git_d["recouvrements"] if git_d else None, questions=questions,
        refus=reg["refus_garde"] if reg is not None else None,
        signaux=reg["signaux"] if reg is not None else None,
        tmux_ok=tmux_ok, branche_reference=proj["branche_reference"] if proj else None,
        equipe_de=equipe_de, maintenant=maintenant, orphelines=orphelines,
        dates_git=None if not git_d else {
            n: {"dates_fichiers": g.get("dates_fichiers"), "retard_depuis": g.get("retard_depuis")}
            for n, g in git_d["equipes"].items()})

    bloques_au_demarrage = {e for al in liste_alarmes if al["type"] == "bloque_au_demarrage"
                            for e in al["equipes"]}
    for eq in equipes:
        if eq["statut"] != "terminee" and eq["nom"] in bloques_au_demarrage:
            eq["statut"] = "bloquee"

    flux = reg["flux"] if reg is not None else None
    ordres = reg["ordres"] if reg is not None else None
    if not complet:
        _masquer_conversation(agents, fil, attentes, liste_alarmes, flux)

    return {
        "version": VERSION,
        "genere_a": _iso(maintenant),
        "duree_collecte_ms": round((time.perf_counter() - debut) * 1000),
        "projet": None if proj is None else {
            "nom": proj["nom"], "racine": proj["racine"], "prefixe": proj["prefixe"],
            "branche_reference": proj["branche_reference"], "etapes": proj["etapes"]},
        "sources": [src_structure, src_registre, src_transcripts, src_tmux_g, src_git, src_tarifs, src_charge],
        "agents": agents,
        "equipes": equipes if equipes_l is not None else None,
        "fil": fil,
        "attentes_utilisateur": attentes,
        "flux": flux,
        "aretes": reg["aretes"] if reg is not None else None,
        "ordres": ordres,
        "facteur": reg["facteur"] if reg is not None else None,
        "charge": bloc_charge,
        "alarmes": liste_alarmes,
        "fusions_auto": _fusions_auto(racine, maintenant),
        "consommation": _consommation_projet(agents),
        "sessions_hors_organigramme": orphelines,
        "decisions_recentes": structure.lire_decisions(racine) if proj else None,
    }


_PREFIXES_ACCORD = ("fusion:", "chantier:")


def _reserves_proposees(racine: Path) -> list[str]:
    """La liste qu'une activation enregistrerait maintenant (noyau + manifeste) ; `[]` si le
    manifeste est illisible. Ne lève jamais."""
    from cime.fondation.fusions_auto import chemins_reserves
    try:
        return chemins_reserves(Path(racine))
    except Exception:  # noqa: BLE001 — manifeste illisible : rien à proposer
        return []


_GENRES_AUTO = ("fusion", "chantier", "contrat", "autorisation")
_DECISIONS_MAX = 50


def _plafond_manifeste(racine: Path) -> int:
    """`chantiers_par_jour` du manifeste ; 5 (le défaut) s'il ne se lit pas. Ne lève jamais."""
    from cime.fondation.fusions_auto import PLAFOND_DEFAUT, plafond_chantiers
    try:
        return plafond_chantiers(Path(racine))
    except Exception:  # noqa: BLE001 — manifeste illisible ou valeur invalide
        return PLAFOND_DEFAUT


def _decisions(conn, depuis: str) -> list[dict]:
    """Les annonces `<genre>-auto:<clé>` (rapport de l'Assistant à l'utilisateur) d'horodatage postérieur à
    `depuis`, du plus récent au plus ancien, 50 au plus. Ne lève jamais."""
    prefixes = [f"{g}-auto:" for g in _GENRES_AUTO]
    essai = " OR ".join("substr(objet, 1, ?) = ?" for _ in prefixes)
    parametres = [x for p in prefixes for x in (len(p), p)]
    try:
        lignes = conn.execute(
            "SELECT id, horodatage, objet FROM messages WHERE de = 'assistant' AND a = 'utilisateur'"
            f" AND nature = 'rapport_utilisateur' AND horodatage > ? AND ({essai})"
            " ORDER BY horodatage DESC, id DESC LIMIT ?",
            [depuis, *parametres, _DECISIONS_MAX]).fetchall()
    except sqlite3.Error:
        return []
    decisions = []
    for ident, horodatage, objet in lignes:
        genre, _, cle = objet.partition(":")
        decisions.append({"genre": genre.removesuffix("-auto"), "cle": cle,
                          "horodatage": horodatage, "message": ident})
    return decisions


def _fusions_auto(racine: Path, maintenant: datetime | None = None) -> dict:
    """Le champ `fusions_auto` : le réglage courant, sa portée, les décisions annoncées
    depuis l'activation, les lancements de chantier des 24 h et la dernière fusion automatique, lus
    dans le registre en lecture seule. Toujours présent, inactif par défaut ; ne lève jamais.
    `suspendue` se décide avec `fusions_auto.etat_courant` (la liste et le plafond actuels, que seul ce
    module sait recalculer ; la portée) : active mais impossible à recalculer = suspendue.
    `reserves_proposees` : la liste actuelle, présente même inactif."""
    from cime.fondation.fusions_auto import lancements_auto_24h
    champ = {"active": False, "suspendue": False, "depuis": None, "par": None, "reserves": [],
             "reserves_proposees": [], "derniere_fusion": None, "portee": None,
             "chantiers_24h": 0, "chantiers_max": _plafond_manifeste(racine), "decisions": []}
    champ["reserves_proposees"] = _reserves_proposees(racine)
    champ["chantiers_24h"] = lancements_auto_24h(Path(racine), maintenant)
    chemin = Path(racine) / ".orga" / "etat" / "registre.sqlite"
    try:
        conn = sqlite3.connect(f"file:{quote(str(chemin))}?mode=ro", uri=True, timeout=1.0)
        try:
            reglage = conn.execute(
                "SELECT horodatage, valeur, auteur, details FROM reglages_projet"
                " WHERE cle = 'fusions_auto' ORDER BY id DESC LIMIT 1").fetchone()
        except sqlite3.Error:
            reglage = None   # registre sans la table : inactif
        try:
            fusion = conn.execute(
                "SELECT horodatage, cible FROM journal WHERE action = 'fusion_auto'"
                " ORDER BY id DESC LIMIT 1").fetchone()
        except sqlite3.Error:
            fusion = None
        if reglage is not None and reglage[1] == "active":
            champ["decisions"] = _decisions(conn, reglage[0])
        conn.close()
    except Exception:  # noqa: BLE001 — registre absent ou illisible : l'instantané reste entier
        return champ
    if reglage is not None:
        champ["depuis"], champ["par"] = reglage[0], reglage[2]
        if reglage[1] == "active":
            champ["active"] = True
            try:
                reserves = json.loads(reglage[3] or "{}").get("reserves")
                champ["reserves"] = [e for e in reserves if isinstance(e, str)]
            except Exception:  # noqa: BLE001 — détails illisibles : liste vide, option suspendue
                pass
            try:
                from cime.fondation.fusions_auto import etat_courant
                etat = etat_courant(racine)
                champ["suspendue"] = not (etat["active"] and not etat["suspendue"])
                champ["portee"] = etat["portee"]
            except Exception:  # noqa: BLE001 — impossible à recalculer : on ne laisse pas croire qu'elle tient
                champ["suspendue"] = True
    if fusion is not None:
        morceaux = (fusion[1] or "").split(":")
        if len(morceaux) == 3 and morceaux[0] == "fusion":
            champ["derniere_fusion"] = {"equipe": morceaux[1], "sha": morceaux[2],
                                        "horodatage": fusion[0]}
    return champ


def _actions_de(attente: dict) -> list[str]:
    """Une décision d'objet `fusion:<équipe>:<sha>` ou `chantier:<équipe>:<phase>` s'accorde ou se
    refuse (`cime accorder|refuser`) ; les autres décisions se tranchent."""
    if attente["nature"] == "decision" and (attente.get("objet") or "").startswith(_PREFIXES_ACCORD):
        return ["accorder", "refuser"]
    return list(_ACTIONS.get(attente["nature"], []))


def _modele_2_0(reg, agent: str) -> dict:
    """`dettes`, `file` et `occupe_par` d'un agent ; None si le registre est en échec."""
    if reg is None:
        return {"dettes": None, "file": None, "occupe_par": None}
    return {"dettes": reg["dettes"].get(agent, []), "file": reg["files"].get(agent, []),
            "occupe_par": reg["occupation"].get(agent)}


def _consommation_projet(agents: list[dict]) -> dict | None:
    """Somme des agents mesurés ; None si aucun agent n'est mesuré."""
    mesures = [(a["id"], a["consommation"]) for a in agents if a.get("consommation")]
    if not mesures:
        return None
    total = {f: {k: sum(c[f][k] for _, c in mesures) for k in ("lus", "ecrits", "tours")}
             for f in ("15min", "60min")}
    gros = sorted(((aid, c["15min"]["lus"]) for aid, c in mesures if c["15min"]["lus"] > 0),
                  key=lambda x: -x[1])[:5]
    total["gros_postes"] = [{"agent": aid, "lus_15min": n,
                             "part_15min": round(n / total["15min"]["lus"], 3)} for aid, n in gros]
    return total


_PRIVES = {"utilisateur", "assistant"}
_CITATION = re.compile(r"« .*? »", re.S)


def _masquer_conversation(agents, fil, attentes, liste_alarmes, flux=None) -> None:
    """Textes échangés entre l'utilisateur et l'Assistant à null ; heures, états, compteurs gardés."""
    for a in agents:
        if a["id"] == "assistant":
            a["derniere_phrase"] = None
            a["brouillon"] = None
    for a in agents:
        for d in a.get("dettes") or []:
            if {d["de"], a["id"]} <= _PRIVES:
                d["objet"] = None
        for f in a.get("file") or []:
            if {f["de"], a["id"]} <= _PRIVES:
                f["resume"] = f["objet"] = None
    for m in fil or []:
        if {m.get("de"), m.get("a")} <= _PRIVES:
            m["resume"] = None
            m["preuve"] = None
    for m in flux or []:
        if {m["de"], m["a"]} <= _PRIVES:
            m["resume"] = m["objet"] = None
    for at in attentes:
        if at["agent"] == "assistant" and at["nature"] != "autorisation":
            at["titre"] = None
    for al in liste_alarmes:
        if "assistant" in al["agents"] and set(al["agents"]) <= _PRIVES:
            al["mesure"] = _CITATION.sub("« (masqué : conversation privée) »", al["mesure"])
