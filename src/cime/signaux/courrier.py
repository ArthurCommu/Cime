"""Le courrier : la file d'un destinataire, sa prise atomique, son format, son accusé.

Partagé par les hooks (`fondation/hook.py` via `signaux/hooks.py`) et par le facteur. Rien ici ne touche un terminal.
"""
import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cime.fondation.registre import horodatage, inscrire_transition
from cime.signaux import echeances, obligations

BAIL_S = 60
LOT_MAX = 5
LIGNE_TMUX_MAX = 600
SEPARATEUR_LOT = " ‖ "
SAUT_TMUX = " ⏎ "
# Événements qui signalent un tour de l'agent (comme `livraison.EVENEMENTS_DE_TOUR` ; ce module
# ne peut pas importer `livraison`)
_EVENEMENTS_DE_TOUR = ("UserPromptSubmit", "PostToolUse", "Stop", "StopFailure")
# Sources d'un `SessionStart` sans tour (ouverture sans message) : jamais une preuve de lecture
_SOURCES_SANS_TOUR = ("compact", "resume", "clear")

_COLONNES = ("id", "de", "a", "nature", "resume", "fichier", "equipe", "objet", "corps",
             "horodatage")
_SELECT = ("SELECT m.id, m.de, m.a, m.nature, m.resume, m.fichier, m.equipe, m.objet,"
           " m.corps, m.horodatage FROM messages m")
_DERNIERE = "(SELECT t.etat FROM transitions t WHERE t.message_id = m.id ORDER BY t.id DESC LIMIT 1)"


@dataclass
class Courrier:
    id: int
    a: str
    voie: str
    tentative: int
    messages: list[dict] = field(default_factory=list)


def _dicts(lignes) -> list[dict]:
    return [dict(zip(_COLONNES, ligne)) for ligne in lignes]


def en_attente(conn, a) -> list[dict]:
    """Messages `a=<a>` dont la dernière transition est `inscrit`, dans l'ordre d'inscription."""
    return _dicts(conn.execute(
        f"{_SELECT} WHERE m.a = ? AND {_DERNIERE} = 'inscrit' ORDER BY m.id", (a,)).fetchall())


def agents_en_attente(conn) -> list[str]:
    """Destinataires qui ont au moins un message `inscrit`, par ordre alphabétique."""
    return [r[0] for r in conn.execute(
        f"SELECT DISTINCT m.a FROM messages m WHERE {_DERNIERE} = 'inscrit' ORDER BY m.a")]


def ouvert_de(conn, a):
    """Le courrier ouvert de `a` : (id, voie, cree, expire, tentative), ou None."""
    return conn.execute(
        "SELECT id, voie, cree, expire, tentative FROM courriers WHERE a = ? AND etat = 'ouvert'",
        (a,)).fetchone()


def renouveler(conn, courrier_id, expire: str) -> None:
    """Le facteur renouvelle le bail tant qu'il attend l'accusé."""
    with conn:
        conn.execute("UPDATE courriers SET expire = ? WHERE id = ? AND etat = 'ouvert'",
                     (expire, courrier_id))


def fermer_expires(conn, a, auteur) -> int:
    """Ferme les courriers ouverts de `a` dont le bail est passé, dans UNE transaction `BEGIN IMMEDIATE`
    (même règle que `prendre`) : `acquitte` si tous leurs messages sont pris en compte, sinon `echoue` et
    les messages reviennent en file (tentative +1). Renvoie le nombre fermés."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        avant = conn.execute("SELECT count(*) FROM courriers WHERE a = ? AND etat = 'ouvert'",
                             (a,)).fetchone()[0]
        _fermer_expires(conn, a, auteur)
        apres = conn.execute("SELECT count(*) FROM courriers WHERE a = ? AND etat = 'ouvert'",
                             (a,)).fetchone()[0]
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return avant - apres


def fermer_expires_de_tous(conn, auteur) -> int:
    """Reprise après redémarrage : pour chaque destinataire, les courriers ouverts dont le
    bail est passé sont fermés (`fermer_expires`). Renvoie le nombre fermés."""
    maintenant = horodatage()
    destinataires = [r[0] for r in conn.execute(
        "SELECT DISTINCT a FROM courriers WHERE etat = 'ouvert' AND expire < ?", (maintenant,))]
    return sum(fermer_expires(conn, a, auteur) for a in destinataires)


def echouer(conn, courrier_id, auteur, preuve, definitif=False) -> list[int]:
    """Ferme le courrier `echoue` (jamais si déjà fermé). Chaque message encore `livre` (dernière transition) repasse
    `inscrit` (tentative +1, `preuve` jointe) ou, si `definitif`, `echec`. Renvoie leurs ids."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        ligne = conn.execute("SELECT tentative, etat FROM courriers WHERE id = ?",
                             (courrier_id,)).fetchone()
        if ligne is None or ligne[1] != "ouvert":
            conn.commit()
            return []
        ids = [r[0] for r in conn.execute(
            "SELECT DISTINCT message_id FROM transitions WHERE courrier_id = ? AND etat = 'livre'"
            " ORDER BY message_id", (courrier_id,))]
        # seuls les messages dont l'état courant est `livre` (par ce courrier) sont repris :
        # `clos`, `abandonne`, `echec`, `pris_en_compte` sont terminaux
        non_pris = [i for i in ids if conn.execute(
            "SELECT etat, courrier_id FROM transitions WHERE message_id = ? ORDER BY id DESC LIMIT 1",
            (i,)).fetchone() == ("livre", courrier_id)]
        conn.execute("UPDATE courriers SET etat = 'echoue' WHERE id = ?", (courrier_id,))
        for i in non_pris:
            if definitif:
                inscrire_transition(conn, i, "echec", auteur, {"tentatives": ligne[0], **preuve},
                                    courrier_id=courrier_id, commit=False)
            else:
                inscrire_transition(conn, i, "inscrit", auteur,
                                    {"reprise": courrier_id, "tentative": ligne[0] + 1, **preuve},
                                    commit=False)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return non_pris


def completer_livraison(conn, courrier_id, ajout: dict) -> None:
    """Complète la preuve des transitions `livre` d'un courrier (tmux_rc, invite_apres…)."""
    with conn:
        for identifiant, brut in conn.execute(
                "SELECT id, preuve FROM transitions WHERE courrier_id = ? AND etat = 'livre'",
                (courrier_id,)).fetchall():
            conn.execute("UPDATE transitions SET preuve = ? WHERE id = ?",
                         (json.dumps({**json.loads(brut), **ajout}, ensure_ascii=False),
                          identifiant))


def livraisons_de(conn, message_id) -> int:
    return conn.execute("SELECT count(*) FROM transitions WHERE message_id = ? AND etat = 'livre'",
                        (message_id,)).fetchone()[0]


def charger(conn, courrier_id) -> "Courrier | None":
    """Relit un courrier (ses messages = ceux qui portent une transition `livre` de ce courrier)."""
    ligne = conn.execute("SELECT id, a, voie, tentative FROM courriers WHERE id = ?",
                         (courrier_id,)).fetchone()
    if ligne is None:
        return None
    messages = _dicts(conn.execute(
        f"{_SELECT} WHERE m.id IN (SELECT message_id FROM transitions WHERE courrier_id = ?"
        " AND etat = 'livre') ORDER BY m.id", (courrier_id,)).fetchall())
    return Courrier(*ligne, messages)


def _octets(message: dict) -> int:
    return len((message["corps"] or message["resume"]).encode("utf-8"))


def _plus_bail(bail_s: int) -> str:
    return ((datetime.now(timezone.utc) + timedelta(seconds=bail_s))
            .strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z")


def _reste_ouvert(conn, a, voie, cree) -> bool:
    """Un courrier de voie hook dont le bail est passé reste ouvert (bail renouvelé) tant que l'agent n'a
    émis, depuis `cree`, aucun événement de tour, ni `SessionStart`, `SessionEnd` ou `idle_prompt` : le texte
    est dans le tour en cours, le relivrer le doublerait. Pour `hook:Stop` seulement, au plus
    `COURRIER_STOP_PLAFOND_S` secondes (un Stop rendu à un agent qui ne repart pas ne bloque pas plus).
    Sinon le courrier est refermé comme avant."""
    if not voie.startswith("hook:"):
        return False
    if voie == "hook:Stop" and (echeances._lire(horodatage()) - echeances._lire(cree)).total_seconds() \
            >= echeances.COURRIER_STOP_PLAFOND_S:
        return False
    marques = ",".join("?" for _ in _EVENEMENTS_DE_TOUR)
    return conn.execute(
        "SELECT 1 FROM evenements WHERE agent = ? AND horodatage > ? AND ("
        f" evenement IN ({marques})"
        " OR evenement IN ('SessionStart', 'SessionEnd')"
        " OR (evenement = 'Notification' AND json_extract(details, '$.notification_type') = 'idle_prompt'))"
        " LIMIT 1", (a, cree, *_EVENEMENTS_DE_TOUR)).fetchone() is None


def _fermer_expires(conn, a, auteur) -> None:
    """Dans la transaction en cours : les courriers ouverts de `a` dont le bail est passé
    deviennent `acquitte` (tous leurs messages sont pris en compte) ou `echoue` (les
    autres reviennent en file par une transition `inscrit` de reprise), sauf ceux que
    `_reste_ouvert` garde : leur bail est renouvelé."""
    maintenant = horodatage()
    expires = conn.execute(
        "SELECT id, tentative, voie, cree FROM courriers WHERE a = ? AND etat = 'ouvert' AND expire < ?",
        (a, maintenant)).fetchall()
    for courrier_id, tentative, voie, cree in expires:
        if _reste_ouvert(conn, a, voie, cree):
            conn.execute("UPDATE courriers SET expire = ? WHERE id = ?", (_plus_bail(BAIL_S), courrier_id))
            continue
        ids = [r[0] for r in conn.execute(
            "SELECT DISTINCT message_id FROM transitions WHERE courrier_id = ? AND etat = 'livre'"
            " ORDER BY message_id", (courrier_id,))]
        # seuls les messages dont l'état courant est `livre` (par ce courrier) sont repris :
        # `clos`, `abandonne`, `echec`, `pris_en_compte` sont terminaux
        non_pris = [i for i in ids if conn.execute(
            "SELECT etat, courrier_id FROM transitions WHERE message_id = ? ORDER BY id DESC LIMIT 1",
            (i,)).fetchone() == ("livre", courrier_id)]
        conn.execute("UPDATE courriers SET etat = ? WHERE id = ?",
                     ("echoue" if non_pris else "acquitte", courrier_id))
        for i in non_pris:
            inscrire_transition(conn, i, "inscrit", auteur,
                                {"reprise": courrier_id, "tentative": tentative + 1},
                                commit=False)


def _session_sans_tour(conn, preuve_base) -> bool:
    """Vrai si l'événement de la prise est un `SessionStart` de source `compact`, `resume` ou `clear` :
    Claude Code l'émet sans tour (compactage au repos, reprise sans message d'ouverture, `/clear`), donc
    rien ne prouve que l'agent a lu le courrier. Une source absente ou `startup` ne tombe pas ici."""
    return conn.execute(
        "SELECT 1 FROM evenements WHERE id = ? AND evenement = 'SessionStart'"
        f" AND json_extract(details, '$.source') IN ({','.join('?' for _ in _SOURCES_SANS_TOUR)})",
        (preuve_base.get("evenement_id"), *_SOURCES_SANS_TOUR)).fetchone() is not None


def prendre(conn, a, voie, auteur, preuve_base, limite=LOT_MAX, bail_s=BAIL_S) -> Courrier | None:
    """Prend jusqu'à `limite` messages en attente de `a` dans UNE transaction `BEGIN IMMEDIATE`.
    `None` si rien n'attend ou si `a` a déjà un courrier ouvert (index unique `courrier_ouvert`).
    `None` aussi, sans rien écrire, pour la voie `hook:SessionStart` d'une session sans tour
    (`_session_sans_tour`) : les messages restent `inscrit` et le facteur les tape à l'invite au repos."""
    if voie == "hook:SessionStart" and _session_sans_tour(conn, preuve_base):
        return None
    conn.execute("BEGIN IMMEDIATE")
    try:
        _fermer_expires(conn, a, auteur)
        messages = en_attente(conn, a)[:limite]
        if not messages:
            conn.commit()
            return None
        livraisons = max(conn.execute(
            "SELECT count(*) FROM transitions WHERE message_id = ? AND etat = 'livre'",
            (m["id"],)).fetchone()[0] for m in messages)
        try:
            cur = conn.execute(
                "INSERT INTO courriers (a, voie, cree, expire, etat, tentative)"
                " VALUES (?, ?, ?, ?, 'ouvert', ?)",
                (a, voie, horodatage(), _plus_bail(bail_s), livraisons + 1))
        except sqlite3.IntegrityError:
            conn.commit()  # garde les fermetures déjà faites ; rien n'est pris
            return None
        for m in messages:
            inscrire_transition(conn, m["id"], "livre", auteur,
                                {**preuve_base, "octets": _octets(m)},
                                courrier_id=cur.lastrowid, commit=False)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return Courrier(cur.lastrowid, a, voie, livraisons + 1, messages)


# --- format -----------------------------------------------------------------------------

# Les mots que `emetteur_lisible` rend. `hooks.py` reconnaît le préfixe d'un courrier tapé à
# partir de ces mêmes constantes (`expression_prefixe`) : un mot ne change qu'ici.
LISIBLE_ASSISTANT = "Assistant"
LISIBLE_UTILISATEUR = "Utilisateur"
LISIBLE_CIME = "Cime"
PREFIXE_COORDINATEUR = "coordinateur "
PREFIXE_WORKER = "worker "


def emetteur_lisible(de: str, equipe: str | None = None) -> str:
    if de == "assistant":
        return LISIBLE_ASSISTANT
    if de == "utilisateur":
        return LISIBLE_UTILISATEUR
    if de == "cime":
        return LISIBLE_CIME
    if de.startswith("coord-"):
        return f"{PREFIXE_COORDINATEUR}{de[len('coord-'):]}"
    if de.startswith("worker-"):
        reste = de[len("worker-"):]
        if equipe and reste.startswith(equipe + "-"):
            return f"{PREFIXE_WORKER}{equipe}/{reste[len(equipe) + 1:]}"
        equipe_, _, tache = reste.partition("-")
        return f"{PREFIXE_WORKER}{equipe_}/{tache}" if tache else f"{PREFIXE_WORKER}{reste}"
    return de


def expression_prefixe() -> str:
    """Le préfixe d'un courrier tapé, en expression régulière : chaque forme que `emetteur_lisible`
    peut rendre, rien d'autre. Un nom d'agent ne contient que des minuscules, chiffres et tirets ;
    un `worker` sans équipe ne porte pas de « / »."""
    nom = "[a-z0-9-]+"
    formes = [re.escape(LISIBLE_ASSISTANT), re.escape(LISIBLE_UTILISATEUR), re.escape(LISIBLE_CIME),
              re.escape(PREFIXE_COORDINATEUR) + nom,
              re.escape(PREFIXE_WORKER) + nom + f"(?:/{nom})?"]
    return "(?:" + "|".join(formes) + ") : "


def _racine_projet(conn) -> Path | None:
    for _, nom, fichier in conn.execute("PRAGMA database_list"):
        if nom == "main" and fichier:
            return Path(fichier).parents[2]  # <projet>/.orga/etat/registre.sqlite
    return None


def chemin_courrier(projet: Path, message_id: int) -> Path:
    return Path(projet) / ".orga" / "etat" / "courrier" / f"{message_id}.md"


def _ligne(texte: str) -> str:
    return texte.replace("\r\n", "\n").replace("\n", SAUT_TMUX)


def formater(conn, courrier, mode, projet=None) -> str:
    """Texte livré. `mode` = "hook" (corps entier) ou "tmux" (une ligne ≤ 600 caractères ;
    plus long : résumé + chemin du fichier `.orga/etat/courrier/<id>.md`, écrit ici)."""
    messages = courrier.messages
    if mode == "hook":
        return SEPARATEUR_LOT.join(
            f"{emetteur_lisible(m['de'], m['equipe'])} : {m['corps'] or m['resume']} (#{m['id']})"
            for m in messages)
    if mode != "tmux":
        raise ValueError(f"mode inconnu : {mode!r}")
    projet = Path(projet) if projet else _racine_projet(conn)

    def courte(m):
        return (f"{emetteur_lisible(m['de'], m['equipe'])} : "
                f"{_ligne(m['corps'] or m['resume'])} (#{m['id']})")

    def longue(m):
        chemin = chemin_courrier(projet, m["id"])
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(m["corps"] or m["resume"], encoding="utf-8")
        return (f"{emetteur_lisible(m['de'], m['equipe'])} : {_ligne(m['resume'])}"
                f" — {chemin} (#{m['id']})")

    lignes = {m["id"]: courte(m) for m in messages}
    for m in sorted(messages, key=lambda m: -len(lignes[m["id"]])):
        if len(SEPARATEUR_LOT.join(lignes[x["id"]] for x in messages)) <= LIGNE_TMUX_MAX \
                and len(lignes[m["id"]]) <= LIGNE_TMUX_MAX:
            break
        lignes[m["id"]] = longue(m)
    return SEPARATEUR_LOT.join(lignes[m["id"]] for m in messages)


# --- accusé -----------------------------------------------------------------------------

def acquitter(conn, message_id, auteur, preuve) -> None:
    """`pris_en_compte` ; sans obligation ouverte, `clos` dans la même transaction ; courrier
    `acquitte` quand tous ses messages sont pris en compte. Une obligation `accuse` est
    satisfaite par l'accusé lui-même. L'état du message est relu DANS la transaction (verrou
    d'écriture pris d'abord) : si un autre accusé est déjà passé, rien n'est écrit."""
    with conn:
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        etat = conn.execute("SELECT etat FROM transitions WHERE message_id = ? ORDER BY id DESC LIMIT 1",
                            (message_id,)).fetchone()
        if etat is not None and etat[0] in ("pris_en_compte", "clos"):
            return
        dernier = conn.execute(
            "SELECT courrier_id FROM transitions WHERE message_id = ? AND etat = 'livre'"
            " ORDER BY id DESC LIMIT 1", (message_id,)).fetchone()
        courrier_id = dernier[0] if dernier else None
        inscrire_transition(conn, message_id, "pris_en_compte", auteur, preuve,
                            courrier_id=courrier_id, commit=False)
        ouverte = obligations.ouverte_pour(conn, message_id)
        if ouverte is not None and ouverte[1] == "accuse":
            obligations.satisfaire(conn, message_id, None, commit=False)
            ouverte = None
        nature = conn.execute("SELECT nature FROM messages WHERE id = ?", (message_id,)).fetchone()[0]
        # Un `accord` est un jeton : il reste `pris_en_compte` jusqu'à ce que `cime lancer` ou la
        # fusion le consomme (transition `clos`). Le clore à l'accusé le consommerait avant usage.
        if ouverte is None and nature != "accord":
            cause = ({"par_message": preuve["par_message"]} if "par_message" in preuve
                     else {"par_evenement": preuve.get("evenement_id")})
            inscrire_transition(conn, message_id, "clos", auteur, cause,
                                courrier_id=courrier_id, commit=False)
        if courrier_id is not None:
            restants = conn.execute(
                "SELECT 1 FROM transitions l WHERE l.courrier_id = ? AND l.etat = 'livre'"
                " AND NOT EXISTS (SELECT 1 FROM transitions p WHERE p.message_id = l.message_id"
                " AND p.etat = 'pris_en_compte' AND p.id > l.id) LIMIT 1",
                (courrier_id,)).fetchone()
            if restants is None:
                conn.execute("UPDATE courriers SET etat = 'acquitte'"
                             " WHERE id = ? AND etat = 'ouvert'", (courrier_id,))
