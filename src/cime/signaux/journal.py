"""`cime journal <agent>` : ce qui s'est passé pour un agent sur une fenêtre, lu au registre.

Lecture seule : la connexion est `mode=ro`, rien n'est migré ni écrit. La sortie ne montre ni le contenu
des messages (seulement leur identifiant, leur état et leur horodatage), ni le contenu des tours (prompt,
dernier message de l'agent, entrée d'outil), ni les chemins de transcript ou de session. Pour les envois, seule
une empreinte courte du résumé (`sha1`) est montrée : elle permet de voir qu'un message se répète, sans le lire.
Droits : un agent lit le sien, l'Assistant lit ses coordinateurs, un coordinateur lit ses workers, l'utilisateur lit tout.
"""
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cime.fondation.compacter import est_superieur
from cime.fondation.registre import chemin_registre
from cime.signaux import commandes
from cime.signaux.commandes import Refus

FENETRE_DEFAUT = timedelta(hours=2)
EXTRAIT_MAX = 200
# contenus de conversation et chemins : jamais montrés, même tronqués
CHAMPS_EXCLUS = ("cwd", "transcript_path", "prompt", "last_assistant_message", "tool_input")


def journal(args) -> int:
    return commandes.lancer_commande("journal", _journal, args)


def _iso(instant: datetime) -> str:
    """Le format de l'horodatage du registre : UTC, millisecondes, suffixe `Z`."""
    return instant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _instant(texte: str) -> str:
    try:
        return _iso(datetime.fromisoformat(texte.replace("Z", "+00:00")))
    except ValueError:
        raise Refus(f"date illisible : {texte!r} (attendu ISO 8601, p. ex. 2026-10-11T10:00:00Z)", 1) from None


def _fenetre(args, maintenant: datetime) -> tuple[str, str]:
    jusqu = _instant(args.jusqu_a) if args.jusqu_a else _iso(maintenant)
    depuis = _instant(args.depuis) if args.depuis else _iso(maintenant - FENETRE_DEFAUT)
    if depuis > jusqu:
        raise Refus("--depuis est postérieur à --jusqu-a", 1)
    return depuis, jusqu


def _droits(moi: str, cible: str, projet) -> None:
    if moi in ("utilisateur", cible) or est_superieur(moi, cible, projet):
        return
    raise Refus(f"seul l'agent lui-même, son supérieur direct (l'Assistant pour un coordinateur, le coordinateur "
                f"de son équipe pour un worker) ou l'utilisateur peut lire le journal de {cible}")


def _lecture(projet) -> sqlite3.Connection:
    """Le registre en lecture seule : aucune migration, aucune écriture (`mode=ro`)."""
    chemin = chemin_registre(Path(projet))
    try:
        return sqlite3.connect(f"{chemin.resolve().as_uri()}?mode=ro", uri=True, timeout=5.0)
    except sqlite3.OperationalError as e:
        raise Refus(f"registre illisible ({e})", 1) from None


def _extrait(details: str) -> str:
    try:
        donnees = json.loads(details or "{}")
    except ValueError:
        return "(détails illisibles)"
    if isinstance(donnees, dict):
        donnees = {k: v for k, v in donnees.items()
                   if k not in CHAMPS_EXCLUS and "path" not in k and "chemin" not in k}
    texte = json.dumps(donnees, ensure_ascii=False, sort_keys=True)
    return texte if len(texte) <= EXTRAIT_MAX else texte[:EXTRAIT_MAX - 1] + "…"


def _evenements(conn, agent, depuis, jusqu) -> list:
    return conn.execute(
        "SELECT id, horodatage, evenement, details FROM evenements WHERE agent = ?"
        " AND horodatage >= ? AND horodatage <= ? ORDER BY id", (agent, depuis, jusqu)).fetchall()


def _fermeture(conn, cid, etat) -> str | None:
    """L'heure à laquelle un courrier non ouvert a été fermé, déduite des transitions (le registre n'a pas de
    colonne pour elle) : `acquitte` → son dernier accusé ; `echoue` → la reprise qui l'a refermé (ou son `echec`).
    `?` si rien ne la prouve (`acquitte` sans accusé : tous ses messages étaient déjà pris). None si ouvert."""
    if etat == "acquitte":
        ligne = conn.execute("SELECT max(horodatage) FROM transitions WHERE courrier_id = ?"
                             " AND etat = 'pris_en_compte'", (cid,)).fetchone()
    elif etat == "echoue":
        ligne = conn.execute("SELECT min(horodatage) FROM transitions WHERE etat = 'inscrit'"
                             " AND json_extract(preuve, '$.reprise') = ?", (cid,)).fetchone()
        if ligne[0] is None:
            ligne = conn.execute("SELECT min(horodatage) FROM transitions WHERE courrier_id = ?"
                                 " AND etat = 'echec'", (cid,)).fetchone()
    else:
        return None
    return ligne[0] or "?"


def _cause(conn, cid, etat) -> dict | None:
    """La preuve de la reprise qui a refermé un courrier `echoue` (sa première transition `inscrit` de reprise) :
    c'est elle qui dit pourquoi la frappe a échoué. None pour un courrier qui n'est pas `echoue`."""
    if etat != "echoue":
        return None
    ligne = conn.execute("SELECT preuve FROM transitions WHERE etat = 'inscrit'"
                         " AND json_extract(preuve, '$.reprise') = ? ORDER BY id LIMIT 1", (cid,)).fetchone()
    return json.loads(ligne[0]) if ligne else None


def _courriers(conn, agent, depuis, jusqu) -> list:
    """Courriers créés dans la fenêtre, chacun avec ses transitions (message, état, horodatage), son heure de
    fermeture (None s'il est ouvert) et la cause de son échec (None si rien de connu)."""
    rendus = []
    for courrier in conn.execute(
            "SELECT id, voie, cree, expire, etat, tentative FROM courriers WHERE a = ?"
            " AND cree >= ? AND cree <= ? ORDER BY id", (agent, depuis, jusqu)).fetchall():
        transitions = conn.execute(
            "SELECT message_id, etat, horodatage FROM transitions WHERE courrier_id = ? ORDER BY id",
            (courrier[0],)).fetchall()
        cause = _cause_rendue(_cause(conn, courrier[0], courrier[4]))
        rendus.append((courrier, transitions, _fermeture(conn, courrier[0], courrier[4]), cause))
    return rendus


def _ecran_rendu(ecran: dict) -> str:
    """Les mesures de l'écran à l'échec (`livraison._releve_ecran`), en clair : jamais de texte."""
    if ecran.get("vu_len") is None:
        return f"écran {ecran.get('relation')}"
    ecart = ecran.get("ecart")
    return (f"écran {ecran.get('relation')} vu {ecran.get('vu_len')}/{ecran.get('texte_len')}"
            f" écart {'aucun' if ecart is None else ecart} lignes {ecran.get('lignes')}")


def _zone_rendue(zone: dict) -> str | None:
    """La zone de saisie telle que l'écran la lisait (`invite.mesures_invite`), en nombres : seules les clés
    connues, jamais le reste. None si aucune n'y figure."""
    morceaux = []
    if isinstance(zone.get("attenue_ligne0"), int) and isinstance(zone.get("attenue_perdu"), int):
        morceaux.append(f"ligne0 attenue {zone['attenue_ligne0']} / total {zone['attenue_perdu']}")
    if isinstance(zone.get("visible_par_ligne"), list):
        morceaux.append("par ligne " + ",".join(str(n) for n in zone["visible_par_ligne"]))
    if isinstance(zone.get("regles"), list):
        morceaux.append("règles " + ",".join(str(n) for n in zone["regles"]))
    if isinstance(zone.get("zone_haut"), int) and isinstance(zone.get("capture_lignes"), int):
        morceaux.append(f"haut {zone['zone_haut']}/{zone['capture_lignes']}")
    return "zone " + ", ".join(morceaux) if morceaux else None


def _cause_rendue(preuve: dict | None) -> str | None:
    """La cause d'un échec, lue dans sa preuve de reprise : seules les clés connues, jamais le reste. None si
    aucune n'y figure."""
    if not preuve:
        return None
    morceaux = []
    if preuve.get("collision"):
        morceaux.append("collision")
    if "efface" in preuve:
        morceaux.append(f"efface {'oui' if preuve['efface'] else 'non'}")
    if preuve.get("invite_changee"):
        morceaux.append("invite changée")
    if "tmux_rc" in preuve:
        morceaux.append(f"tmux_rc {preuve['tmux_rc']}")
    if preuve.get("sans_accuse"):
        morceaux.append("sans accusé")
    if isinstance(preuve.get("ecran"), dict):
        morceaux.append(_ecran_rendu(preuve["ecran"]))
    if isinstance(preuve.get("zone"), dict) and (zone := _zone_rendue(preuve["zone"])):
        morceaux.append(zone)
    pane = preuve.get("pane")
    if isinstance(pane, list) and len(pane) == 2 and all(isinstance(n, int) for n in pane):
        morceaux.append(f"pane {pane[0]}x{pane[1]}")
    return ", ".join(morceaux) or None


def _envois(conn, agent, depuis, jusqu) -> list:
    """Messages écrits par `agent` dans la fenêtre : (id, horodatage, a, nature, état courant, résumé, corps)."""
    return conn.execute(
        "SELECT m.id, m.horodatage, m.a, m.nature,"
        " (SELECT t.etat FROM transitions t WHERE t.message_id = m.id ORDER BY t.id DESC LIMIT 1),"
        " m.resume, m.corps FROM messages m WHERE m.de = ? AND m.horodatage >= ? AND m.horodatage <= ?"
        " ORDER BY m.id", (agent, depuis, jusqu)).fetchall()


def _empreinte(resume: str, corps: str | None) -> str:
    """Huit caractères qui identifient le texte d'un envoi, sans le montrer."""
    return hashlib.sha1((resume + "\n" + (corps or "")).encode("utf-8")).hexdigest()[:8]


def _rendu(agent, depuis, jusqu, evenements, courriers, envois) -> str:
    lignes = [f"journal de {agent} — de {depuis} à {jusqu}", "", f"événements ({len(evenements)}) :"]
    lignes += [f"  #{i}  {h}  {nature}  {_extrait(details)}" for i, h, nature, details in evenements]
    if not evenements:
        lignes.append("  (aucun)")
    lignes += ["", f"courriers ({len(courriers)}) :"]
    for (cid, voie, cree, expire, etat, tentative), transitions, fermeture, cause in courriers:
        ligne = f"  #{cid}  {voie}  créé {cree}  expire {expire}  état {etat}  tentative {tentative}"
        lignes.append(ligne if fermeture is None else f"{ligne}  fermé {fermeture}")
        if cause is not None:
            lignes.append(f"    cause : {cause}")
        lignes += [f"      message #{mid}  {etat_t}  {h}" for mid, etat_t, h in transitions]
    if not courriers:
        lignes.append("  (aucun)")
    lignes += ["", f"envois ({len(envois)}) :"]
    lignes += [f"  #{i}  {h}  → {a}  {nature}  {etat}  empreinte {_empreinte(resume, corps)}"
               for i, h, a, nature, etat, resume, corps in envois]
    if not envois:
        lignes.append("  (aucun)")
    return "\n".join(lignes)


def _journal(args) -> int:
    projet = commandes.projet_courant()
    _droits(commandes.identite_appelant(), args.agent, projet)
    depuis, jusqu = _fenetre(args, datetime.now(timezone.utc))
    conn = _lecture(projet)
    try:
        evenements = _evenements(conn, args.agent, depuis, jusqu)
        courriers = _courriers(conn, args.agent, depuis, jusqu)
        envois = _envois(conn, args.agent, depuis, jusqu)
    except sqlite3.OperationalError as e:
        raise Refus(f"registre illisible ({e})", 1) from None
    finally:
        conn.close()
    print(_rendu(args.agent, depuis, jusqu, evenements, courriers, envois))
    return 0
