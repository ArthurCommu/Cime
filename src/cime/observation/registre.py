"""Lecture du registre (échanges et événements) et état des agents déduit des hooks.

Lecture seule : la base est ouverte avec `mode=ro` (jamais `immutable=1`, qui lirait
un état périmé sans le dire). Tout est lu dans une seule transaction, donc cohérent.

Comportement en WAL (mesuré, voir test_registre.py) :
- un écrivain actif n'empêche pas la lecture : on voit l'état validé (commit) le plus récent ;
- `-wal` et `-shm` présents : lecture normale ;
- `-wal` et `-shm` absents (écrivain arrêté proprement) : lecture normale ;
- `-wal` présent mais `-shm` absent (écrivain tué) : voir `test_wal_shm_absent`.
"""

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from cime.signaux import echeances, vue

NOM = "registre"
_TAILLE_FIL = 200
_TAILLE_REFUS = 50
_TAILLE_RESUME = 160
_TAILLE_PHRASE = 300

_NATURES_UTILISATEUR = {"rapport_utilisateur", "decision_utilisateur", "donnee_utilisateur"}
_FERMANTS = ("Stop", "UserPromptSubmit", "PostToolUse")
_NOTIF = "Notification:permission_prompt"
_EVENEMENTS_ETAT = (*_FERMANTS, "PermissionRequest", _NOTIF, "SessionStart")


def _echec(msg: str) -> tuple[None, dict]:
    return None, {"nom": NOM, "ok": False, "erreur": msg}


def _ouvrir(chemin: Path) -> sqlite3.Connection:
    """Connexion en lecture seule ; toute écriture y échoue."""
    uri = f"file:{quote(str(chemin))}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=1.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def _ligne(texte, taille: int = _TAILLE_RESUME) -> str | None:
    """Texte réduit à une ligne, tronqué à `taille` caractères (… compris)."""
    if texte is None:
        return None
    une = re.sub(r"\s+", " ", str(texte)).strip()
    return une if len(une) <= taille else une[: taille - 1] + "…"


def _fin(texte: str, taille: int = _TAILLE_PHRASE) -> str:
    """La fin du texte, où se trouvent les annonces : `…` + les `taille - 1` derniers caractères."""
    return texte if len(texte) <= taille else "…" + texte[-(taille - 1):]


def _details(brut) -> dict:
    try:
        d = json.loads(brut) if brut else {}
    except (TypeError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _resume_outil(tool_input) -> str | None:
    """Une ligne lisible : commande Bash ou chemin de fichier, tel qu'écrit."""
    if isinstance(tool_input, str):
        return _ligne(tool_input)
    if isinstance(tool_input, dict):
        for cle in ("command", "file_path", "path", "notebook_path"):
            if isinstance(tool_input.get(cle), str):
                return _ligne(tool_input[cle])
        return _ligne(json.dumps(tool_input, ensure_ascii=False))
    return None


def _cle(ligne) -> tuple:
    return (ligne["horodatage"], ligne["id"])


def _etat_agent(derniers: dict, dernier_evt, ouverts: list, refus: dict | None = None) -> dict:
    """Applique la règle d'état sur les derniers événements d'un agent.

    `refus` : dernière ligne `refuser` (ok) du journal pour une demande de l'agent ; elle compte
    comme un `Stop` (un Escape interrompt le tour sans hook)."""
    ferm = [derniers[e] for e in _FERMANTS if e in derniers] + ([refus] if refus else [])
    f = max(ferm, key=_cle) if ferm else None
    etat = {"etat": "inconnu", "etat_depuis": None, "etat_source": None, "etat_evenement_id": None,
            "autorisation_ouverte": None}
    if ouverts:
        premier = ouverts[0]
        etat.update(etat="attend_autorisation", etat_depuis=premier["horodatage"],
                    etat_evenement_id=premier["id"],
                    etat_source="hook:Notification:permission_prompt"
                    if premier["evenement"] == "Notification" else "hook:PermissionRequest")
        demandes = [o for o in ouverts if o["evenement"] == "PermissionRequest"]
        if demandes:
            d = demandes[-1]
            det = _details(d["details"])
            etat["autorisation_ouverte"] = {
                "demande_id": det.get("demande_id"),
                "tool_name": det.get("tool_name"),
                "resume_outil": _resume_outil(det.get("tool_input")),
                "depuis": d["horodatage"],
            }
    elif f is refus and refus is not None:
        etat.update(etat="au_repos", etat_depuis=f["horodatage"], etat_source="journal:refuser")
    elif f is not None:
        etat.update(etat="au_repos" if f["evenement"] == "Stop" else "travaille",
                    etat_depuis=f["horodatage"], etat_source=f"hook:{f['evenement']}",
                    etat_evenement_id=f["id"])
    stop = derniers.get("Stop")
    phrase = _details(stop["details"]).get("last_assistant_message") if stop else None
    ss = derniers.get("SessionStart")
    det_dernier = _details(dernier_evt["details"])
    etat.update(
        derniere_phrase=_fin(phrase) if isinstance(phrase, str) else None,
        dernier_evenement={"evenement": dernier_evt["evenement"], "horodatage": dernier_evt["horodatage"]},
        modele=_details(ss["details"]).get("model") if ss else None,
        transcript_path=det_dernier.get("transcript_path"),
        session_id=dernier_evt["session_id"],
    )
    return etat


def _reponses_page(conn) -> dict:
    """`demande_id` -> (horodatage, action) de la réponse de l'utilisateur depuis la page (journal, `resultat = 'ok'`).

    Un refus (Escape) n'émet aucun hook : cette ligne est l'événement fermant de la demande."""
    reponses: dict = {}
    for r in conn.execute(
        """SELECT cible, horodatage, action FROM journal WHERE action IN ('autoriser', 'refuser')
           AND resultat = 'ok' AND cible LIKE 'perm-%' ORDER BY horodatage, id"""):
        reponses[r["cible"][len("perm-"):]] = (r["horodatage"], r["action"])
    return reponses


def _agents(conn, journal: bool = False) -> dict:
    # Dernier événement de chaque catégorie, par agent (Notification : seulement permission_prompt).
    cat = ("CASE WHEN evenement = 'Notification' THEN 'Notification:' || "
           "json_extract(details, '$.notification_type') ELSE evenement END")
    marques = ",".join("?" * len(_EVENEMENTS_ETAT))
    derniers: dict = {}
    for r in conn.execute(
        f"""SELECT e.id, e.horodatage, e.agent, e.evenement, e.details, c.cat FROM evenements e
            JOIN (SELECT id, cat FROM (
                SELECT id, {cat} AS cat, ROW_NUMBER() OVER (
                    PARTITION BY agent, {cat} ORDER BY horodatage DESC, id DESC) AS rn
                FROM evenements WHERE agent IS NOT NULL
                  AND evenement IN ({",".join("?" * (len(_EVENEMENTS_ETAT) - 1))}, 'Notification')
            ) WHERE rn = 1 AND cat IN ({marques})) c ON c.id = e.id""",
        (*[e for e in _EVENEMENTS_ETAT if e != _NOTIF], *_EVENEMENTS_ETAT),
    ):
        derniers.setdefault(r["agent"], {})[r["cat"]] = r
    evts = {}
    for r in conn.execute(
        """SELECT e.id, e.horodatage, e.agent, e.session_id, e.evenement, e.details FROM evenements e
           JOIN (SELECT id FROM (SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY agent ORDER BY horodatage DESC, id DESC) AS rn
                 FROM evenements WHERE agent IS NOT NULL) WHERE rn = 1) d ON d.id = e.id"""
    ):
        evts[r["agent"]] = r
    reponses = _reponses_page(conn) if journal else {}
    refus_par_agent: dict = {}
    refuses = [i for i, (_, action) in reponses.items() if action == "refuser"]
    if refuses:
        for r in conn.execute(
            f"""SELECT agent, json_extract(details, '$.demande_id') AS d FROM evenements
                WHERE evenement = 'PermissionRequest' AND agent IS NOT NULL
                  AND json_extract(details, '$.demande_id') IN ({",".join("?" * len(refuses))})""",
            refuses):
            ligne = {"id": 0, "horodatage": reponses[r["d"]][0], "evenement": "refuser"}
            if r["agent"] not in refus_par_agent or _cle(ligne) > _cle(refus_par_agent[r["agent"]]):
                refus_par_agent[r["agent"]] = ligne
    resultat = {}
    for agent, dernier_evt in evts.items():
        d = derniers.get(agent, {})
        ferm = [d[e] for e in _FERMANTS if e in d]
        borne = max(ferm, key=_cle) if ferm else None
        ouverts = []
        if any(k in d for k in ("PermissionRequest", _NOTIF)):
            ouverts = [
                r for r in conn.execute(
                    """SELECT id, horodatage, evenement, details FROM evenements
                       WHERE agent = ? AND (evenement = 'PermissionRequest' OR (evenement = 'Notification'
                             AND json_extract(details, '$.notification_type') = 'permission_prompt'))
                       ORDER BY horodatage, id""", (agent,))
                if borne is None or _cle(r) > _cle(borne)
            ]
            # Réponse de l'utilisateur depuis la page : ferme les demandes de cet agent et ce qui les précède.
            fermees = [reponses[i][0] for o in ouverts if o["evenement"] == "PermissionRequest"
                       if (i := _details(o["details"]).get("demande_id")) in reponses]
            if fermees:
                limite = max(fermees)
                ouverts = [o for o in ouverts if o["horodatage"] > limite]
        resultat[agent] = _etat_agent(d, dernier_evt, ouverts, refus_par_agent.get(agent))
    return resultat


def _fil(conn, tables: set) -> list:
    lignes = []
    avec_transitions = "transitions" in tables
    avec_obligations = "obligations" in tables
    etat_livraison = ("(SELECT t.etat FROM transitions t WHERE t.message_id = m.id"
                      " ORDER BY t.id DESC LIMIT 1)") if avec_transitions else "NULL"
    preuve = ("(SELECT t.preuve FROM transitions t WHERE t.message_id = m.id"
              " ORDER BY t.id DESC LIMIT 1)") if avec_transitions else "NULL"
    attente = ("EXISTS (SELECT 1 FROM obligations o WHERE o.message_id = m.id"
               " AND o.etat = 'ouverte')") if avec_obligations else "0"
    objet = "m.objet" if "objet" in _colonnes(conn, "messages") else "NULL"
    for r in conn.execute(
        f"""SELECT m.id, m.horodatage, m.de, m.a, m.nature, m.resume, m.fichier, {objet} AS objet,
                   {attente} AS attente, {etat_livraison} AS etat_livraison, {preuve} AS preuve
            FROM messages m ORDER BY m.horodatage DESC, m.id DESC LIMIT ?""", (_TAILLE_FIL,)):
        lignes.append((r["horodatage"], 1, r["id"], {
            "id": f"msg-{r['id']}", "horodatage": r["horodatage"], "de": r["de"], "a": r["a"],
            "nature": r["nature"], "resume": r["resume"], "fichier": r["fichier"],
            "en_attente": bool(r["attente"]), "etat_livraison": r["etat_livraison"],
            # message livré à l'utilisateur, sans obligation ouverte, hors voie perm-…
            "non_lu": (r["a"] == "utilisateur" and r["etat_livraison"] == "livre" and not r["attente"]
                       and not (r["objet"] or "").startswith("autorisation:")),
            "preuve": _details(r["preuve"]) if r["preuve"] is not None else None,
            "source": "registre"}))
    for r in conn.execute(
        """SELECT id, horodatage, evenement, details FROM evenements
           WHERE agent = 'assistant' AND evenement IN ('UserPromptSubmit', 'Stop')
           ORDER BY horodatage DESC, id DESC LIMIT ?""", (_TAILLE_FIL,)):
        prompt = r["evenement"] == "UserPromptSubmit"
        texte = _details(r["details"]).get("prompt" if prompt else "last_assistant_message")
        # Fin d'un agent en arrière-plan : Claude Code l'injecte comme un prompt, mais l'utilisateur
        # n'a rien tapé.
        if prompt and isinstance(texte, str) and texte.lstrip().startswith("<task-notification>"):
            continue
        lignes.append((r["horodatage"], 0, r["id"], {
            "id": f"evt-{r['id']}", "horodatage": r["horodatage"],
            "de": "utilisateur" if prompt else "assistant", "a": "assistant" if prompt else "utilisateur",
            "nature": None, "resume": _ligne(texte) or "", "fichier": None,
            "en_attente": False, "etat_livraison": None, "non_lu": False, "preuve": None,
            "source": "hook"}))
    lignes.sort(key=lambda t: t[:3], reverse=True)
    return [t[3] for t in lignes[:_TAILLE_FIL]]


def _questions(conn, tables: set) -> list:
    """Questions dont l'obligation de réponse est ouverte (une seule définition de l'attente)."""
    if "obligations" not in tables:
        return []
    return [
        {"id": f"msg-{r['id']}", "de": r["de"], "a": r["a"], "horodatage": r["horodatage"],
         "resume": r["resume"]}
        for r in conn.execute(
            """SELECT m.id, m.de, m.a, m.horodatage, m.resume FROM messages m
               JOIN obligations o ON o.message_id = m.id AND o.etat = 'ouverte'
               WHERE m.nature = 'question'
               ORDER BY m.horodatage DESC, m.id DESC""")
    ]


def _attentes_utilisateur(conn, journal: bool, tables: set) -> list:
    """Obligations ouvertes dont `utilisateur` est débiteur (décision, donnée, rapport, clôture)."""
    if "obligations" not in tables:
        return []
    lus = set()
    if journal:
        lus = {r[0] for r in conn.execute("SELECT cible FROM journal WHERE action = 'lu'")}
    objet = "m.objet" if "objet" in _colonnes(conn, "messages") else "NULL"
    sortie = []
    for r in conn.execute(
        f"""SELECT m.id, m.horodatage, m.de, m.resume, m.fichier, m.nature, m.equipe, {objet} AS objet,
                   (SELECT p.nature FROM messages p WHERE p.id = m.en_reponse_a) AS nature_parent,
                   (SELECT p.de FROM messages p WHERE p.id = m.en_reponse_a) AS de_parent
            FROM messages m JOIN obligations o ON o.message_id = m.id
            WHERE o.debiteur = 'utilisateur' AND o.etat = 'ouverte'
              AND m.nature IN ('rapport_utilisateur', 'decision_utilisateur', 'donnee_utilisateur')
            ORDER BY m.horodatage DESC, m.id DESC"""):
        if r["nature"] == "decision_utilisateur":
            nature = "decision"
        elif r["nature"] == "donnee_utilisateur":
            nature = "donnee"
        elif r["nature_parent"] == "demande_cloture":
            nature = "cloture"
        elif f"msg-{r['id']}" in lus:
            continue
        else:
            nature = "rapport"
        sortie.append({"id": f"msg-{r['id']}", "message_id": r["id"], "objet": r["objet"],
                       "horodatage": r["horodatage"], "de": r["de"],
                       "resume": r["resume"], "fichier": r["fichier"], "nature": nature,
                       "equipe": r["equipe"],
                       "origine": r["de_parent"] if nature == "cloture" else r["de"]})
    return sortie


def _colonnes(conn, table: str) -> set:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _par_agent(conn, tables: set, maintenant: datetime) -> dict:
    """Ce que le modèle 2.0 dit de chaque agent : dettes, file, occupation ; et la vue d'ensemble."""
    dettes: dict = {}
    files: dict = {}
    occupation: dict = {}
    if "obligations" in tables:
        for (debiteur,) in conn.execute(
                "SELECT DISTINCT debiteur FROM obligations WHERE etat = 'ouverte'").fetchall():
            dettes[debiteur] = vue.dettes_de(conn, debiteur)
    if "transitions" in tables:
        for (destinataire,) in conn.execute(
                "SELECT DISTINCT m.a FROM messages m WHERE (SELECT t.etat FROM transitions t"
                " WHERE t.message_id = m.id ORDER BY t.id DESC LIMIT 1) = 'inscrit'").fetchall():
            files[destinataire] = vue.file_de(conn, destinataire)
    if "occupation" in tables:
        occupation = {r[0]: r[1] for r in conn.execute("SELECT agent, occupe_par FROM occupation")}
    facteur = None
    if "facteur" in tables:
        ligne = conn.execute("SELECT battement FROM facteur WHERE id = 1").fetchone()
        if ligne is None:
            facteur = {"battement": None, "age_s": None, "arrete": True}
        else:
            try:
                age = int((maintenant - datetime.fromisoformat(
                    ligne[0].replace("Z", "+00:00"))).total_seconds())
            except (AttributeError, ValueError):
                age = None
            facteur = {"battement": ligne[0], "age_s": age,
                       "arrete": age is None or age > echeances.PEREMPTION_BATTEMENT}
    return {
        "dettes": dettes, "files": files, "occupation": occupation, "facteur": facteur,
        "flux": vue.flux(conn) if "transitions" in tables else [],
        "aretes": vue.aretes(conn, maintenant) if "transitions" in tables else [],
        "ordres": vue.ordres(conn) if "ordres" in tables else [],
    }


def _signal_ouvert(signal) -> bool:
    """Le supérieur n'a pas encore pris acte d'un signalement : pour l'utilisateur, il n'est pas clos ;
    pour un autre, son obligation est ouverte."""
    if signal["a"] == "utilisateur":
        return signal["derniere"] not in ("clos", "abandonne")
    return signal["etat"] == "ouverte"


def _signaux(conn, tables: set, files: dict, ordres: list, facteur) -> dict | None:
    """Ce dont les alarmes dérivées des obligations ont besoin (voir `alarmes.calculer`)."""
    if not {"obligations", "transitions"} <= tables:
        return None
    obligations = []
    # Un signalement à l'utilisateur n'a pas d'obligation : il compte tant qu'il n'est pas clos.
    for r in conn.execute(
        """SELECT m.id AS message_id, COALESCE(o.debiteur, m.a) AS debiteur,
                  COALESCE(o.attendu, 'accuse') AS attendu, o.echeance, m.de, m.a, m.objet, m.resume,
                  m.horodatage FROM messages m
           LEFT JOIN obligations o ON o.message_id = m.id AND o.etat = 'ouverte'
           WHERE m.nature = 'signalement' AND m.objet IS NOT NULL AND (
                 (m.a = 'utilisateur' AND (SELECT t.etat FROM transitions t WHERE t.message_id = m.id
                  ORDER BY t.id DESC LIMIT 1) NOT IN ('clos', 'abandonne'))
                 OR (m.a != 'utilisateur' AND o.message_id IS NOT NULL))
           ORDER BY m.id""").fetchall():
        ligne = dict(r)
        if ligne["objet"].startswith("autorisation:"):
            demande = conn.execute(
                "SELECT agent FROM evenements WHERE evenement = 'PermissionRequest'"
                " AND json_extract(details, '$.demande_id') = ? LIMIT 1",
                (ligne["objet"].split(":", 1)[1],)).fetchone()
            ligne["agent_demande"] = demande[0] if demande else None
        obligations.append(ligne)
    echecs = []
    for (ident,) in conn.execute("SELECT DISTINCT message_id FROM transitions WHERE etat = 'echec'").fetchall():
        derniere = conn.execute(
            "SELECT etat, horodatage FROM transitions WHERE message_id = ? ORDER BY id DESC LIMIT 1",
            (ident,)).fetchone()
        if derniere["etat"] != "echec":
            continue
        message = conn.execute("SELECT a, resume FROM messages WHERE id = ?", (ident,)).fetchone()
        signal = conn.execute(
            "SELECT m.a, o.etat, (SELECT t.etat FROM transitions t WHERE t.message_id = m.id"
            " ORDER BY t.id DESC LIMIT 1) AS derniere FROM messages m"
            " LEFT JOIN obligations o ON o.message_id = m.id"
            " WHERE m.nature = 'signalement' AND m.objet = ? AND (m.a = 'utilisateur' OR o.message_id IS NOT NULL)"
            " ORDER BY m.id DESC LIMIT 1", (f"livraison:{ident}",)).fetchone()
        if signal is not None and not _signal_ouvert(signal):
            continue  # le supérieur a pris acte
        echecs.append({"id": ident, "a": message["a"], "resume": message["resume"],
                       "depuis": derniere["horodatage"], "signale_a": signal["a"] if signal else None})
    courrier = conn.execute(
        """SELECT c.id, c.cree FROM courriers c WHERE c.a = 'assistant' AND c.etat = 'ouvert'
             AND c.voie LIKE 'tmux%' AND EXISTS (SELECT 1 FROM transitions t WHERE t.courrier_id = c.id
               AND t.etat = 'livre' AND json_extract(t.preuve, '$.capture_avant') = 'vide')""").fetchone()
    idle = conn.execute(
        "SELECT horodatage FROM evenements WHERE agent = 'assistant' AND evenement = 'Notification'"
        " AND json_extract(details, '$.notification_type') = 'idle_prompt' ORDER BY id DESC LIMIT 1").fetchone()
    return {
        "obligations": obligations, "echecs": echecs, "facteur": facteur,
        "attente": {
            "messages": sum(1 for liste in files.values() for m in liste if m["objet"] != "facteur-arrete"),
            "ordres": sum(1 for o in ordres if o["etat"] == "en_file")},
        "courrier_assistant": dict(courrier) if courrier else None,
        "idle_prompt_assistant": idle[0] if idle else None,
    }


def _refus_garde(conn) -> list:
    sortie = []
    for r in conn.execute(
        """SELECT id, horodatage, agent, details FROM evenements WHERE evenement = 'PreToolUse'
           ORDER BY horodatage DESC, id DESC LIMIT ?""", (_TAILLE_REFUS,)):
        det = _details(r["details"])
        sortie.append({"id": r["id"], "agent": r["agent"], "horodatage": r["horodatage"],
                       "tool_name": det.get("tool_name"),
                       "resume_outil": _resume_outil(det.get("tool_input")),
                       "motif": det.get("motif")})
    return sortie


def _lire(conn, maintenant: datetime) -> dict:
    conn.execute("BEGIN")  # un seul instantané pour toutes les requêtes
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        for t in ("messages", "evenements"):
            if t not in tables:
                raise LookupError(f"registre incomplet : table « {t} » absente")
        vue_2_0 = _par_agent(conn, tables, maintenant)
        return {
            "fil": _fil(conn, tables),
            "questions_en_attente": _questions(conn, tables),
            "agents": _agents(conn, "journal" in tables),
            "attentes_utilisateur": _attentes_utilisateur(conn, "journal" in tables, tables),
            **vue_2_0,
            "signaux": _signaux(conn, tables, vue_2_0["files"], vue_2_0["ordres"], vue_2_0["facteur"]),
            "refus_garde": _refus_garde(conn),
            "evenements_sans_agent": conn.execute(
                "SELECT COUNT(*) FROM evenements WHERE agent IS NULL").fetchone()[0],
        }
    finally:
        conn.execute("ROLLBACK")


def lire_registre(racine: Path, maintenant: datetime) -> tuple[dict | None, dict]:
    """Lit `<racine>/.orga/etat/registre.sqlite`. Ne lève jamais.

    `maintenant` ne sert qu'à l'âge du battement du facteur et à la fenêtre des arêtes ;
    les autres âges, le consommateur les dérive des horodatages (qui sont ceux de la base).
    """
    chemin = Path(racine) / ".orga" / "etat" / "registre.sqlite"
    if not chemin.is_file():
        return _echec(f"registre absent : {chemin}")
    conn = None
    try:
        conn = _ouvrir(chemin)
        return _lire(conn, maintenant), {"nom": NOM, "ok": True}
    except LookupError as e:
        return _echec(str(e))
    except sqlite3.Error as e:
        return _echec(f"registre illisible : {e}")
    except Exception as e:  # noqa: BLE001 — ne lève jamais
        return _echec(f"registre illisible : {e}")
    finally:
        if conn is not None:
            conn.close()
