"""`cime fermer` et `cime rouvrir`.

Fermer un projet, c'est noter ce qui vivait (`.orga/etat/ferme.json`), puis fermer les sessions tmux et
l'hôte. Rouvrir, c'est reprendre l'Assistant et les coordinateurs qui avaient du travail, sur leur
conversation notée. Aucun `git`, aucune suppression : branche, worktrees, tâches, conversations et
courrier restent intacts.

Les fonctions pures (`calculer_plan`) décident ; les fonctions de bord (`_tmux`, `_pids_ecoutant`,
`_tuer`, fichiers, registre) agissent, et les tests les remplacent.
"""
import json
import os
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from cime.fondation import lancer
from cime.fondation.projet import ErreurProjet, est_un_projet, lire_manifeste
from cime.fondation.registre import horodatage, inscrire_evenement, ouvrir

CODE_ERREUR = 1
CODE_APPROBATION = 3
CODE_OCCUPES = 5

AUTEUR = "utilisateur"


class Echec(Exception):
    """Une commande qui s'arrête : message pour l'utilisateur, code de sortie, champs JSON en plus."""

    def __init__(self, message, code=CODE_ERREUR, **champs):
        super().__init__(message)
        self.code, self.champs = code, champs


# --- le repère `ferme.json` ---------------------------------------------------------------

def chemin_repere(projet) -> Path:
    return Path(projet) / ".orga" / "etat" / "ferme.json"


def est_ferme(projet) -> bool:
    """Projet fermé ⇔ le repère existe (lisible ou non : un repère illisible vaut « fermé »)."""
    try:
        return chemin_repere(projet).exists()
    except OSError:
        return False


def lire_repere(projet) -> dict | None:
    """Le repère, `None` s'il n'y en a pas. Jamais d'exception : un repère illisible est rendu comme
    un repère vide marqué `illisible` (le projet reste fermé, et on le dit)."""
    if not est_ferme(projet):
        return None
    try:
        donnees = json.loads(chemin_repere(projet).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        donnees = None
    if not isinstance(donnees, dict):
        return {"illisible": True, "conversations": [], "a_relancer": [], "raisons": {},
                "taches_en_cours": []}
    for cle in ("conversations", "a_relancer", "taches_en_cours"):
        if not isinstance(donnees.get(cle), list):
            donnees[cle] = []
    if not isinstance(donnees.get("raisons"), dict):
        donnees["raisons"] = {}
    return donnees


def ecrire_repere(projet, donnees: dict) -> None:
    """Écriture atomique : fichier temporaire dans le même dossier, puis renommage."""
    chemin = chemin_repere(projet)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    temporaire = chemin.with_name(f".{chemin.name}.{os.getpid()}.tmp")
    try:
        temporaire.write_text(json.dumps(donnees, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
        os.replace(temporaire, chemin)
    except BaseException:
        try:
            temporaire.unlink()
        except OSError:
            pass
        raise


def retirer_repere(projet) -> None:
    try:
        chemin_repere(projet).unlink()
    except FileNotFoundError:
        pass


# --- le plan (fonctions pures) ------------------------------------------------------------

def _equipe_du_worker(identite: str, equipes_connues) -> str | None:
    """`worker-<équipe>-<tâche>` : l'équipe est le plus long nom connu qui préfixe l'identité."""
    candidates = [e for e in equipes_connues if identite.startswith(f"worker-{e}-")]
    return max(candidates, key=len) if candidates else None


def _rang(identite: str) -> tuple:
    return (0 if identite == "assistant" else 1 if identite.startswith("coord-") else 2, identite)


def identites_vivantes(prefixe: str, sessions) -> dict:
    """Identité → nom de session, pour les sessions tmux `<préfixe>-<identité>`."""
    marque = f"{prefixe}-"
    return {session[len(marque):]: session for session in sessions if session.startswith(marque)}


def raisons_de_garder(*, vivants, equipes_connues, coordinables, taches, debiteurs,
                      en_attente) -> dict:
    """Coordinateur → pourquoi on le garde, pour chaque équipe de `coordinables` qui en a une :
    `travail` (un worker de l'équipe vit, une tâche de l'équipe est en cours, ou le coordinateur est
    débiteur d'une obligation ouverte) ou `message` (un message `inscrit` ou `livre` lui est adressé).
    Un coordinateur absent du résultat n'a aucune dette. `vivants` : identités des sessions vivantes.
    C'est la seule définition de « sans dette » : `calculer_plan` (qui relancer) et la mise au repos
    des coordinateurs (qui fermer) l'appellent toutes deux."""
    equipes_avec_worker = {_equipe_du_worker(i, equipes_connues) for i in vivants
                           if i.startswith("worker-")}
    equipes_avec_tache = {t.split("/", 1)[0] for t in taches}
    raisons = {}
    for equipe in sorted(coordinables):
        coord = f"coord-{equipe}"
        if equipe in equipes_avec_worker or equipe in equipes_avec_tache or coord in debiteurs:
            raisons[coord] = "travail"
        elif coord in en_attente:
            raisons[coord] = "message"
    return raisons


def calculer_plan(*, prefixe: str, sessions, session_de: dict, equipes_connues, coordinables,
                  taches, debiteurs, en_attente) -> dict:
    """Ce que le repère retient. `sessions` : noms de sessions tmux vivantes ; `session_de` : agent →
    dernier `session_id` du registre ; `equipes_connues` : toutes les équipes ; `coordinables` :
    celles qui ont un coordinateur à relancer ; `taches` : `équipe/tâche` en cours ; `debiteurs` :
    agents qui ont une obligation ouverte ; `en_attente` : agents qui ont un message `inscrit` ou
    `livre`."""
    vivants = identites_vivantes(prefixe, sessions)
    conversations = []
    for identite in sorted(vivants, key=_rang):
        session_id = session_de.get(identite)
        if not session_id:
            continue
        entree = {"agent": identite, "session": session_id, "tmux": vivants[identite]}
        if identite.startswith("coord-"):
            entree["equipe"] = identite[len("coord-"):]
        elif identite.startswith("worker-"):
            equipe = _equipe_du_worker(identite, equipes_connues)
            if equipe:
                entree["equipe"] = equipe
        conversations.append(entree)
    gardes = raisons_de_garder(vivants=vivants, equipes_connues=equipes_connues,
                               coordinables=coordinables, taches=taches, debiteurs=debiteurs,
                               en_attente=en_attente)
    a_relancer, raisons = ["assistant", *gardes], {"assistant": "assistant", **gardes}
    return {"conversations": conversations, "a_relancer": a_relancer, "raisons": raisons,
            "taches_en_cours": sorted(taches)}


# --- lecture du projet ---------------------------------------------------------------------

def _dossier_equipes(projet) -> Path:
    return Path(projet) / ".orga" / "teams"


def equipes_connues(projet) -> list[str]:
    dossier = _dossier_equipes(projet)
    return sorted(d.name for d in dossier.iterdir() if d.is_dir()) if dossier.is_dir() else []


def equipes_coordinables(projet, manifeste) -> list[str]:
    """Équipes dont le coordinateur se relance : un mandat, pas clôturée, ni spéciale, ni l'intégration
    (elle n'a que des sessions de worker)."""
    ecartees = {*manifeste.equipes_speciales, lancer.EQUIPE_INTEGRATION}
    return [e for e in equipes_connues(projet)
            if e not in ecartees and (_dossier_equipes(projet) / e / "mandate.md").is_file()
            and not (_dossier_equipes(projet) / e / "CLOTUREE").exists()]


def taches_en_cours(projet) -> list[str]:
    """`équipe/tâche` pour chaque `tasks/in-progress/*.md`, toutes équipes confondues."""
    return sorted(f"{e}/{f.stem}" for e in equipes_connues(projet)
                  for f in (_dossier_equipes(projet) / e / "tasks" / "in-progress").glob("*.md"))


def _dernieres_sessions(conn) -> dict:
    """Agent → `session_id` de son dernier événement (celui du hook : la conversation de Claude Code)."""
    return dict(conn.execute(
        "SELECT agent, session_id FROM evenements WHERE id IN (SELECT max(id) FROM evenements"
        " WHERE agent IS NOT NULL AND session_id IS NOT NULL GROUP BY agent)").fetchall())


def _agents_en_attente(conn) -> set:
    return {a for (a,) in conn.execute(
        "SELECT DISTINCT m.a FROM messages m WHERE (SELECT t.etat FROM transitions t"
        " WHERE t.message_id = m.id ORDER BY t.id DESC LIMIT 1) IN ('inscrit', 'livre')")}


def _debiteurs(conn) -> set:
    return {d for (d,) in conn.execute("SELECT DISTINCT debiteur FROM obligations"
                                        " WHERE etat = 'ouverte'")}


def occupes(projet, conn, donnees=None) -> list[str]:
    """Agents occupés : état d'observation `travaille` ou demande d'autorisation ouverte (règle de
    `observation/registre.py`), ou courrier dont la livraison est en cours (bail pris).

    Un état d'observation que seul un `SessionStart` (`startup`/`resume`) plus récent contredit
    n'est pas un travail en cours : la session a été tuée en plein tour et reprise (comme
    `livraison.etat_agent`).

    `donnees` : la lecture du registre d'observation, si l'appelant l'a déjà faite."""
    from cime.observation.registre import lire_registre
    noms = set()
    if donnees is None:
        donnees, _ = lire_registre(Path(projet), datetime.now(timezone.utc))
    for agent, etat in ((donnees or {}).get("agents") or {}).items():
        if etat.get("etat") not in ("travaille", "attend_autorisation") or agent == AUTEUR:
            continue
        depuis = etat.get("etat_evenement_id") or 0
        neuve = conn.execute(
            "SELECT 1 FROM evenements WHERE agent = ? AND evenement = 'SessionStart' AND id > ?"
            " AND json_extract(details, '$.source') IN ('startup', 'resume') LIMIT 1",
            (agent, depuis)).fetchone()
        if not neuve:
            noms.add(agent)
    noms |= {a for (a,) in conn.execute("SELECT DISTINCT a FROM courriers WHERE etat = 'ouvert'")}
    return sorted(noms - {AUTEUR, "cime"})


# --- bord : tmux, hôte --------------------------------------------------------------------

def _tmux(*args: str):
    return subprocess.run(["tmux", *args], capture_output=True, text=True)


def sessions_vivantes() -> set[str]:
    try:
        r = _tmux("list-sessions", "-F", "#{session_name}")
    except (OSError, subprocess.SubprocessError):
        return set()
    return set(r.stdout.split()) if r.returncode == 0 else set()


def _fermer_session(session: str) -> None:
    try:
        _tmux("kill-session", "-t", f"={session}")
    except (OSError, subprocess.SubprocessError):
        pass                            # déjà partie : rien à fermer


def _port_hote(projet) -> int | None:
    try:
        port = int((Path(projet) / ".orga" / "etat" / "hote.port").read_text().strip())
    except (OSError, ValueError):
        return None
    return port if 0 < port < 65536 else None


def _pids_ecoutant(port: int) -> list[int]:
    """Processus `cime` qui écoutent sur `port`. Un autre programme qui aurait repris un port resté
    dans un `hote.port` périmé n'est jamais touché."""
    try:
        r = subprocess.run(["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
                           capture_output=True, text=True, timeout=10)
        pids = [int(p) for p in r.stdout.split() if p.isdigit()]
        retenus = []
        for pid in pids:
            ps = subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                                capture_output=True, text=True, timeout=10)
            if "cime" in ps.stdout:
                retenus.append(pid)
        return retenus
    except (OSError, subprocess.SubprocessError):
        return []


def _tuer(pid: int) -> None:
    os.kill(pid, signal.SIGTERM)


def arreter_hote(projet) -> list[int]:
    """SIGTERM au processus qui écoute sur le port de `hote.port`. Port absent, illisible, ou plus
    personne à l'écoute : sans effet. Ne lève jamais."""
    port = _port_hote(projet)
    if port is None:
        return []
    try:
        pids = _pids_ecoutant(port)
    except Exception:
        return []
    arretes = []
    for pid in pids:
        if pid == os.getpid():
            continue
        try:
            _tuer(pid)
            arretes.append(pid)
        except OSError:
            pass                        # déjà arrêté, ou pas le nôtre
    return arretes


# --- journal --------------------------------------------------------------------------------

def _noter(projet, evenement: str, action: str, details: dict, conn=None, auteur=AUTEUR) -> None:
    """Événement (`agent` NULL, comme `EquipeCreee`) et ligne de journal, auteur et heure compris."""
    propre = conn is None
    conn = ouvrir(projet) if propre else conn
    try:
        inscrire_evenement(conn, agent=None, session_id=None, evenement=evenement,
                           details={"auteur": auteur, **details})
        with conn:
            conn.execute(
                "INSERT INTO journal (horodatage, auteur, action, cible, details, resultat)"
                " VALUES (?, ?, ?, ?, ?, 'ok')",
                (horodatage(), auteur, action, str(projet), json.dumps(details, ensure_ascii=False)))
    finally:
        if propre:
            conn.close()


# --- la commande : appelant, sortie ---------------------------------------------------------

def _exiger_utilisateur(nom: str) -> None:
    from cime.signaux.identite import ErreurIdentite, appelant
    try:
        moi = appelant()
    except ErreurIdentite as e:
        raise Echec(f"{nom} : réservé à l'utilisateur ({e})") from None
    if moi != AUTEUR:
        raise Echec(f"{nom} : réservé à l'utilisateur — {moi} ne peut pas le faire "
                    "(un agent demande à l'Assistant, qui demande à l'utilisateur)")


def _projet(chemin) -> Path:
    projet = Path(chemin).expanduser().resolve()
    if not est_un_projet(projet):
        raise Echec(f"{projet} n'est pas un projet (.orga/projet.toml introuvable)")
    return projet


def _sortie(donnees: dict, texte: str, en_json: bool) -> None:
    print(json.dumps(donnees, ensure_ascii=False) if en_json else texte, flush=True)


def _conversations_gardees(n: int) -> str:
    return f"{n} conversation gardée" if n == 1 else f"{n} conversations gardées"


def _commande(nom: str, args, fonction) -> int:
    en_json = getattr(args, "sortie_json", False)
    try:
        _exiger_utilisateur(nom)
        return fonction(_projet(args.projet), args, en_json)
    except Echec as e:
        if e.code == CODE_OCCUPES:
            donnees = {"resultat": "refuse", "message": str(e), **e.champs}
        else:
            donnees = {"resultat": "erreur", "message": str(e), **e.champs}
        if en_json:
            print(json.dumps(donnees, ensure_ascii=False), flush=True)
        else:
            print(str(e), file=sys.stderr)
        return e.code
    except ErreurProjet as e:
        message = f"{nom} : {e}"
        if en_json:
            print(json.dumps({"resultat": "erreur", "message": message}, ensure_ascii=False),
                  flush=True)
        else:
            print(message, file=sys.stderr)
        return CODE_ERREUR


# --- fermer ---------------------------------------------------------------------------------

def _deja_ferme(repere: dict, en_json: bool) -> int:
    donnees = {"resultat": "ok", "conversations": repere["conversations"],
               "taches_en_cours": repere["taches_en_cours"]}
    texte = f"déjà fermé, {_conversations_gardees(len(repere['conversations']))}"
    if repere.get("illisible"):
        donnees["message"] = "repère illisible : le projet est considéré comme fermé"
        texte = "déjà fermé (repère illisible)"
    _sortie(donnees, texte, en_json)
    return 0


def _fermer(projet: Path, args, en_json: bool) -> int:
    repere = lire_repere(projet)
    if repere is not None:                      # idempotente : rien n'est refait
        return _deja_ferme(repere, en_json)
    manifeste = lire_manifeste(projet)
    conn = ouvrir(projet)
    try:
        if not args.forcer:
            occupees = occupes(projet, conn)
            if occupees:
                raise Echec(
                    f"fermer : {', '.join(occupees)} {'travaille' if len(occupees) == 1 else 'travaillent'} "
                    "encore — rien n'est fermé ; `--forcer` pour fermer quand même",
                    code=CODE_OCCUPES, occupes=occupees)
        marque = f"{manifeste.prefixe}-"
        sessions = sorted(s for s in sessions_vivantes() if s.startswith(marque))
        plan = calculer_plan(
            prefixe=manifeste.prefixe, sessions=sessions, session_de=_dernieres_sessions(conn),
            equipes_connues=equipes_connues(projet),
            coordinables=equipes_coordinables(projet, manifeste), taches=taches_en_cours(projet),
            debiteurs=_debiteurs(conn), en_attente=_agents_en_attente(conn))
        repere = {"heure": datetime.now().astimezone().isoformat(timespec="seconds"), **plan}
        ecrire_repere(projet, repere)           # d'abord : c'est le repère qui fait taire le reste
        try:
            _noter(projet, "ProjetFerme", "fermer",
                   {"forcer": bool(args.forcer), "conversations": len(plan["conversations"]),
                    "a_relancer": plan["a_relancer"]}, conn)
        except Exception as e:
            retirer_repere(projet)              # pas de fermeture sans trace
            raise Echec(f"fermer : le registre n'a pas pu noter la fermeture ({e}) ; rien n'est fermé")
    finally:
        conn.close()
    for session in sessions:
        _fermer_session(session)
    arreter_hote(projet)
    _sortie({"resultat": "ok", "conversations": plan["conversations"],
             "taches_en_cours": plan["taches_en_cours"]},
            f"fermé, {_conversations_gardees(len(plan['conversations']))}", en_json)
    return 0


def executer_fermer(args) -> int:
    return _commande("fermer", args, _fermer)


# --- rouvrir --------------------------------------------------------------------------------

def _date_conversation(fichier: Path) -> str | None:
    try:
        return datetime.fromtimestamp(fichier.stat().st_mtime, timezone.utc).isoformat(
            timespec="seconds")
    except OSError:
        return None


def choisir_conversation(dossier: Path, *candidates) -> str | None:
    """Premier identifiant, parmi `candidates` (dans l'ordre), dont le fichier existe ; à défaut la
    conversation la plus récente du dossier ; `None` s'il n'y en a aucune."""
    for candidate in candidates:
        if candidate and lancer.derniere_conversation(dossier, session=candidate):
            return candidate
    return lancer.derniere_conversation(dossier)


def _arguments_reprise(role: str, equipe: str | None, session: str | None):
    import argparse
    return argparse.Namespace(role=role, equipe=equipe, tache=None, modele=None,
                              essai_a_blanc=False, reprendre=True, session=session,
                              remplacer=False, detache=True)


def _relancer(projet: Path, role: str, equipe: str | None, session: str | None):
    """(session tmux, code de `lancer`). Le terminal n'est jamais attaché ici : c'est le lanceur."""
    return lancer._lancer(_arguments_reprise(role, equipe, session), projet, attacher=False)


def _rouvrir(projet: Path, args, en_json: bool) -> int:
    manifeste = lire_manifeste(projet)
    repere = lire_repere(projet) or {}
    notees = {c.get("agent"): c.get("session") for c in repere.get("conversations", [])
              if isinstance(c, dict)}
    conn = ouvrir(projet)
    try:
        dernieres = _dernieres_sessions(conn)
    finally:
        conn.close()
    vivantes = sessions_vivantes()
    session_assistant = f"{manifeste.prefixe}-assistant"

    # 1. la conversation de l'Assistant : --session, le repère, le registre, la plus récente
    choisie = choisir_conversation(projet, args.session, notees.get("assistant"),
                                   dernieres.get("assistant"))
    assistant_vivant = session_assistant in vivantes
    if choisie is None and not assistant_vivant:
        raise Echec("rouvrir : aucune conversation de l'Assistant à reprendre dans "
                    f"{lancer.dossier_conversations(projet)} — rien n'est lancé")
    fichier = lancer.dossier_conversations(projet) / f"{choisie}.jsonl" if choisie else None
    conversation = {"session": choisie, "date": _date_conversation(fichier) if fichier else None}

    # 2. le facteur (il lit encore le repère : il bat une fois puis sort ; il repart plus bas),
    #    puis l'Assistant, sauf s'il vit déjà
    lancer._demarrer_facteur(projet)
    a_approuver = False
    if not assistant_vivant:
        try:
            _, code = _relancer(projet, "assistant", None, choisie)
        except ErreurProjet as e:
            raise Echec(f"rouvrir : l'Assistant n'a pas pu être repris : {e}") from None
        a_approuver = code == CODE_APPROBATION

    # 3. les coordinateurs qui avaient du travail, un par un ; un échec n'arrête pas les autres
    coordinateurs, echecs = [], []
    if not args.seulement_assistant:
        for agent in repere.get("a_relancer", []):
            if not isinstance(agent, str) or not agent.startswith("coord-"):
                continue
            equipe = agent[len("coord-"):]
            if f"{manifeste.prefixe}-{agent}" in vivantes:
                echecs.append({"agent": agent, "message": "session déjà vivante : laissée telle quelle"})
                continue
            try:
                dossier = lancer._dossier_equipe(projet, equipe)
                _, code = _relancer(projet, "coord", equipe, choisir_conversation(
                    dossier, notees.get(agent), dernieres.get(agent)))
            except Exception as e:
                echecs.append({"agent": agent, "message": str(e)})
                continue
            coordinateurs.append(equipe)
            a_approuver = a_approuver or code == CODE_APPROBATION

    # 4. le repère en dernier, puis le facteur qui peut enfin rester, puis la trace
    try:
        retirer_repere(projet)
    except OSError as e:
        raise Echec(f"rouvrir : le repère de fermeture n'a pas pu être retiré ({e})") from None
    lancer._demarrer_facteur(projet)
    try:
        _noter(projet, "ProjetRouvert", "rouvrir",
               {"conversation": choisie, "coordinateurs": coordinateurs, "echecs": len(echecs),
                "a_approuver": a_approuver})
    except Exception as e:
        print(f"rouvrir : réouverture non notée au registre ({e})", file=sys.stderr)

    donnees = {"resultat": "ok", "assistant": session_assistant, "conversation": conversation,
               "coordinateurs": coordinateurs, "echecs": echecs, "a_approuver": a_approuver,
               "taches_en_cours": taches_en_cours(projet)}
    texte = [f"rouvert : {session_assistant}"
             + (f", conversation {choisie}" if choisie else "")
             + (f", coordinateurs : {', '.join(coordinateurs)}" if coordinateurs else "")]
    texte += [f"échec {e['agent']} : {e['message']}" for e in echecs]
    if a_approuver:
        texte.append("un écran de confiance attend ton approbation dans le terminal")
    _sortie(donnees, "\n".join(texte), en_json)
    return CODE_APPROBATION if a_approuver else 0


def executer_rouvrir(args) -> int:
    return _commande("rouvrir", args, _rouvrir)
