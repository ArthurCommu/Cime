"""Les ordres : toute action sur un terminal demandée par un
agent est une ligne `ordres` ; seul le facteur l'exécute.

Appelés à la main par l'utilisateur (`appelant() == "utilisateur"`), `lancer`, `terminer`, `compacter` et
`voir` s'exécutent directement, par les mêmes fonctions d'exécution que le facteur.

Une tâche orpheline (fiche dans `in-progress/`, ni session ni processus) se relance par le même
ordre `lancer`, sur le même accord : l'ordre porte alors `reprise: true`. Un coordinateur endormi se
réveille par le même ordre, posé par le facteur : il porte `reveil: true`.
"""
import argparse
import contextlib
import io
import json
import os
import re
import time
from pathlib import Path

from cime.fondation import plafond
from cime.fondation.projet import ErreurProjet, lire_manifeste, session_tmux
from cime.fondation.registre import horodatage, inscrire_transition, ouvrir
from cime.signaux import commandes, obligations, repos
from cime.signaux.commandes import Refus

ATTENTE_ORDRE = 30.0
VAR_ATTENTE = "CIME_ATTENTE_ORDRE"
PAS_ATTENTE = 0.5
ATTENTE_FIN_PROCESSUS = 10.0
CODE_APPROBATION = 3
CODE_EN_FILE = 4
LIGNES_CAPTUREES = 40


def _dormir(secondes: float) -> None:
    time.sleep(secondes)


def _tmux(*args: str):
    import subprocess
    return subprocess.run(["tmux", *args], capture_output=True, text=True)


def _lancer(args, projet):
    from cime.fondation import lancer
    return lancer._lancer(args, projet)


# --- la file ------------------------------------------------------------------------------

def demander(projet, auteur, verbe, cible, parametres) -> int:
    conn = ouvrir(projet)
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO ordres (horodatage, auteur, verbe, cible, parametres, etat)"
                " VALUES (?, ?, ?, ?, ?, 'en_file')",
                (horodatage(), auteur, verbe, cible,
                 json.dumps(parametres, ensure_ascii=False)))
        return cur.lastrowid
    finally:
        conn.close()


def delai_attente() -> float:
    try:
        return float(os.environ.get(VAR_ATTENTE, ATTENTE_ORDRE))
    except ValueError:
        return ATTENTE_ORDRE


def attendre_resultat(projet, identifiant, delai=None):
    """Résultat {"etat", "code", "texte"} de l'ordre, ou None si le délai est dépassé."""
    delai = delai_attente() if delai is None else delai
    fin = time.monotonic() + delai
    while True:
        conn = ouvrir(projet)
        try:
            ligne = conn.execute("SELECT etat, resultat FROM ordres WHERE id = ?",
                                 (identifiant,)).fetchone()
        finally:
            conn.close()
        if ligne is not None and ligne[0] != "en_file" and ligne[1] is not None:
            try:
                donnees = json.loads(ligne[1] or "{}")
            except ValueError:
                donnees = {"code": 1, "texte": ligne[1] or ""}
            return {"etat": ligne[0], "code": donnees.get("code", 1),
                    "texte": donnees.get("texte", "")}
        if time.monotonic() >= fin:
            return None
        _dormir(min(PAS_ATTENTE, max(fin - time.monotonic(), 0)))


def _attente(identifiant, projet) -> str:
    """Pourquoi un ordre reste en file. Le compte vient de tmux ou, depuis un agent, du facteur."""
    if projet is not None and _lancement_de_worker_en_file(projet, identifiant):
        actifs, plafond, _ = charge_machine(projet)
        if actifs is not None and actifs >= plafond:
            return (f"ordre #{identifiant} en file : {actifs} workers actifs sur la machine "
                    f"(plafond {plafond}) — il partira quand une place se libère")
    if projet is not None:
        from cime.lanceur.surveillant import battement_frais
        if battement_frais(Path(projet)):
            return f"ordre #{identifiant} en file : le facteur est actif, il partira à son tour"
    return f"ordre #{identifiant} en file, facteur arrêté"


def _issue(identifiant, resultat, projet=None) -> int:
    """Code de sortie d'une commande qui a posé un ordre, d'après son résultat. Avec `projet`,
    une attente due au plafond de workers le dit, et un facteur qui bat n'est pas accusé."""
    if resultat is None:
        print(_attente(identifiant, projet))
        return CODE_EN_FILE
    if resultat["texte"]:
        print(resultat["texte"])
    if resultat["etat"] == "refuse":
        return 2
    if resultat["etat"] == "echec":
        return 1
    return resultat["code"]


def poser_et_attendre(projet, auteur, verbe, cible, parametres) -> tuple[int, dict | None]:
    identifiant = demander(projet, auteur, verbe, cible, parametres)
    return identifiant, attendre_resultat(projet, identifiant)


# --- exécution (le facteur, ou l'utilisateur à la main) ------------------------------------------

def _capter(fonction):
    sortie = io.StringIO()
    with contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(sortie):
        retour = fonction()
    return retour, sortie.getvalue().strip()


def _fermer_pour_remplacer(projet, p) -> None:
    """`--remplacer` : le facteur ferme la session du coordinateur (seul à toucher tmux), puis
    attend la fin du processus claude pour que la reprise ne s'y heurte pas. Idempotent : sans
    session, il n'y a rien à fermer et l'ordre se réduit à `--reprendre`."""
    session = session_tmux(lire_manifeste(projet), p["cible"])
    if session is None or _tmux("has-session", "-t", f"={session}").returncode != 0:
        return
    r = _tmux("kill-session", "-t", f"={session}")
    if r.returncode != 0:
        raise ErreurProjet(f"fermeture de la session {session} impossible : {r.stderr.strip()}")
    _attendre_fin_du_processus(projet, p["equipe"])


def _attendre_fin_du_processus(projet, equipe) -> None:
    """Attend (au plus `ATTENTE_FIN_PROCESSUS`) que plus aucun processus claude ne tourne dans le
    dossier de l'équipe : la reprise d'une conversation s'y heurterait."""
    from cime.fondation import lancer
    dossier = lancer._dossier_equipe(projet, equipe)
    for _ in range(int(ATTENTE_FIN_PROCESSUS / PAS_ATTENTE)):
        if not lancer.processus_claude_dans(dossier):
            return
        _dormir(PAS_ATTENTE)


def _executer_lancer(projet, ordre_id, p):
    from cime.fondation import lancer
    if p.get("remplacer"):
        try:
            _fermer_pour_remplacer(projet, p)
        except ErreurProjet as e:
            return "echec", 1, str(e)
    if p.get("reveil"):     # réveil d'un coordinateur endormi : sa session vient d'être fermée
        _attendre_fin_du_processus(projet, p["equipe"])
    args = argparse.Namespace(
        role=p["role"], equipe=p.get("equipe"), tache=p.get("tache"), modele=p.get("modele"),
        essai_a_blanc=False, reprendre=bool(p.get("reprendre")), session=p.get("session"),
        auteur=p.get("auteur"))
    try:
        (session, code), texte = _capter(lambda: _lancer(args, projet))
    except lancer.Refus as e:
        return "refuse", 2, str(e)
    except ErreurProjet as e:
        return "echec", 1, str(e)
    if code not in (0, CODE_APPROBATION):
        return "echec", code, texte
    conn = ouvrir(projet)
    try:
        if p.get("role") == "worker" and p.get("equipe") != lancer.EQUIPE_INTEGRATION:
            _consigne_de_tache(conn, projet, p)
        if p.get("reveil"):     # le message qui l'a réveillé suffit : pas de consigne d'ouverture
            repos.noter_reveil(projet, conn, p["cible"], p.get("session"), ordre_id)
        elif p.get("role") == "coord":
            _consigne_d_ouverture(conn, p)
        if code == CODE_APPROBATION:
            _signalement_d_approbation(conn, p, session)
        if p.get("accord") is not None:
            inscrire_transition(conn, p["accord"], "clos", "cime", {"par_ordre": ordre_id})
    finally:
        conn.close()
    return "execute", code, texte


def _consigne_de_tache(conn, projet, p) -> None:
    equipe, tache = p["equipe"], p["tache"]
    relatif = f".orga/teams/{equipe}/tasks/in-progress/{tache}.md"
    resume = f"tâche {tache} : lis {relatif} et exécute-la"
    if p.get("reprise"):   # la fiche est jointe : le résumé garde la place de la consigne
        resume = (f"tâche {tache} : reprise après interruption — lis git status, git log du "
                  "worktree et la fiche ; ne refais pas ce qui est fait")
    commandes.inscrire(
        conn, de=f"coord-{equipe}", a=f"worker-{equipe}-{tache}", nature="consigne",
        resume=resume[:160],
        fichier=relatif if (projet / relatif).exists() else None, equipe=equipe,
        objet=f"tache:{equipe}:{tache}", attend="travail_pret",
        preuve={"cmd": "lancer", "pid": os.getpid()})


def _consigne_d_ouverture(conn, p) -> None:
    """La consigne d'ouverture que reçoit un coordinateur lancé (première fois ou reprise)."""
    equipe = p["equipe"]
    # Texte distinct de l'invite initiale (`lancer.MESSAGE_COORDINATEUR`) : le coordinateur ne doit
    # pas recevoir deux fois la même phrase. L'id n'est connu qu'après l'inscription : le résumé est
    # mis à jour dans la même transaction.
    def avec_id(identifiant):
        conn.execute("UPDATE messages SET resume = ? WHERE id = ?",
                     (f"Cime : ouverture enregistrée (#{identifiant}) — accuse réception par ton prochain tour.",
                      identifiant))

    commandes.inscrire(
        conn, de="cime", a=f"coord-{equipe}", nature="consigne", resume="Cime : ouverture enregistrée.",
        equipe=equipe, objet="ouverture", attend="accuse", preuve={"cmd": "lancer", "pid": os.getpid()},
        dans_transaction=avec_id)


def _signalement_d_approbation(conn, p, session) -> None:
    """L'écran de démarrage (confiance, imports) attend l'utilisateur dans le terminal."""
    commandes.inscrire(
        conn, de="cime", a="assistant", nature="signalement", equipe=p.get("equipe"),
        resume=f"{session} attend une approbation dans le terminal (tmux attach -t {session})"[:160],
        objet=f"approbation:{session}", preuve={"cmd": "lancer", "pid": os.getpid()})


def _executer_fermer(projet, ordre_id, p):
    from cime.fondation import terminer
    equipe, tache, worker = p["equipe"], p["tache"], p["worker"]
    try:
        _rapport, texte = _capter(lambda: terminer._tenter(projet, equipe, tache, worker))
    except terminer._Refus as e:
        return ("refuse" if e.code == 2 else "echec"), e.code, str(e)
    conn = ouvrir(projet)
    try:
        journal = terminer.journaliser(projet, de=p.get("auteur", "cime"), worker=worker,
                                       tache=tache, resultat="rapport accepté, session fermée",
                                       rapport=_rapport)
        with conn:
            for (identifiant,) in conn.execute(
                    "SELECT m.id FROM messages m WHERE (m.objet = ? AND m.a = ?)"
                    " OR (m.nature = 'travail_pret' AND m.de = ?)",
                    (f"tache:{equipe}:{tache}", worker, worker)).fetchall():
                obligations.satisfaire(conn, identifiant, journal, commit=False)
            # ce que le worker n'a pas lu avant sa fermeture ne lui sera jamais remis
            obligations.abandonner_inscrits_de(conn, worker, "cime", "fermer", commit=False)
    finally:
        conn.close()
    return "execute", 0, texte


def _executer_compacter(projet, ordre_id, p):
    from cime.fondation import compacter
    etat, texte = compacter.frapper(projet, p["cible"], p["consignes"])
    return etat, (0 if etat == "execute" else 2 if etat == "refuse" else 1), texte


def _executer_capturer(projet, ordre_id, p):
    session = session_tmux(lire_manifeste(projet), p["cible"])
    if session is None or _tmux("has-session", "-t", f"={session}").returncode != 0:
        return "refuse", 2, f"session de {p['cible']} absente"
    r = _tmux("capture-pane", "-p", "-t", f"={session}:")
    if r.returncode != 0:
        return "echec", 1, f"capture impossible : {r.stderr.strip()}"
    lignes = r.stdout.rstrip("\n").splitlines()[-LIGNES_CAPTUREES:]
    return "execute", 0, "\n".join(lignes)


_EXECUTEURS = {"lancer": _executer_lancer, "fermer": _executer_fermer,
               "compacter": _executer_compacter, "capturer": _executer_capturer}


def executer(projet, ordre: dict):
    """Exécute un ordre ({id, auteur, verbe, cible, parametres}) : (etat, code, texte)."""
    parametres = dict(ordre["parametres"], cible=ordre["cible"], auteur=ordre["auteur"])
    return _EXECUTEURS[ordre["verbe"]](Path(projet), ordre["id"], parametres)


def _prendre_ordre(projet, identifiant):
    """Prise atomique : l'ordre passe de `en_file` à `execute` en une instruction ; un seul
    appelant (facteur, thread) voit `rowcount == 1`. Renvoie l'ordre pris, ou None."""
    conn = ouvrir(projet)
    try:
        with conn:
            cur = conn.execute(
                "UPDATE ordres SET etat = 'execute' WHERE id = ? AND etat = 'en_file'",
                (identifiant,))
        if cur.rowcount != 1:
            return None
        ligne = conn.execute(
            "SELECT id, auteur, verbe, cible, parametres FROM ordres WHERE id = ?",
            (identifiant,)).fetchone()
    finally:
        conn.close()
    ordre = dict(zip(("id", "auteur", "verbe", "cible", "parametres"), ligne))
    ordre["parametres"] = json.loads(ordre["parametres"])
    return ordre


def compter_workers(sessions) -> int:
    """Nombre de sessions de worker parmi `sessions` : celles dont le nom contient `-worker-`,
    quel que soit le préfixe (un seul serveur tmux voit tous les projets de la machine).
    Limite connue : un worker lancé hors tmux n'est pas vu, et une session tmux étrangère nommée
    `…-worker-…` compterait aussi."""
    return sum("-worker-" in nom for nom in sessions)


def _sessions_vivantes() -> set[str] | None:
    """Les sessions tmux de la machine ; None quand tmux est muet (le bac à sable d'un agent)."""
    from cime.signaux import livraison
    return livraison.sonde_sessions()


def chemin_charge(projet) -> Path:
    """Ce que le facteur inscrit pour les agents, qui ne voient ni tmux ni les réglages de la machine."""
    return Path(projet) / ".orga" / "etat" / "charge.json"


def _miroir(projet) -> dict:
    """Le contenu du fichier du facteur ; vide s'il est absent, illisible ou n'est pas un objet."""
    try:
        donnees = json.loads(chemin_charge(projet).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return donnees if isinstance(donnees, dict) else {}


def _compte_inscrit(projet) -> int | None:
    compte = _miroir(projet).get("workers_actifs")
    return compte if isinstance(compte, int) and not isinstance(compte, bool) and compte >= 0 \
        else None


def _plafond_machine_inscrit(projet) -> tuple[int, str] | None:
    miroir = _miroir(projet)
    valeur, source = miroir.get("plafond_machine"), miroir.get("source_machine")
    if plafond.valeur_valide(valeur) and source in (plafond.FICHIER_SOURCE, plafond.DEFAUT_SOURCE):
        return valeur, source
    return None


def prefixe_de_session(nom: str) -> str:
    """Ce qui précède `-worker-` : le préfixe du projet qui a lancé la session."""
    return nom.partition("-worker-")[0]


def workers_par_projet(sessions) -> dict[str, int]:
    """Les workers actifs regroupés par préfixe de projet."""
    comptes: dict[str, int] = {}
    for nom in sessions:
        if "-worker-" in nom:
            prefixe = prefixe_de_session(nom)
            comptes[prefixe] = comptes.get(prefixe, 0) + 1
    return comptes


def _detail_inscrit(projet) -> dict[str, int] | None:
    detail = _miroir(projet).get("par_projet")
    if isinstance(detail, dict) and all(
            isinstance(prefixe, str) and isinstance(n, int) and not isinstance(n, bool) and n >= 0
            for prefixe, n in detail.items()):
        return detail
    return None


def workers_vus(projet, sessions) -> tuple[int | None, dict[str, int] | None]:
    """(workers actifs, détail par préfixe de projet) tels que l'appelant les voit : par tmux s'il
    répond, sinon par le miroir du facteur quand son battement est frais ; (None, None) quand on ne
    sait pas. Chaque moitié du miroir se juge seule."""
    if sessions is not None:
        return compter_workers(sessions), workers_par_projet(sessions)
    from cime.lanceur.surveillant import battement_frais
    if not battement_frais(Path(projet)):
        return None, None
    return _compte_inscrit(projet), _detail_inscrit(projet)


def inscrire_charge(projet) -> bool:
    """Le facteur, qui voit tmux et les réglages, inscrit pour les agents ce qu'ils ne peuvent pas
    voir : les workers actifs (total et par projet) et le plafond de la machine. Réécrit seulement
    quand l'une de ces valeurs change, de façon atomique (fichier voisin puis remplacement).
    Renvoie True s'il a écrit. Tmux muet : rien n'est inscrit."""
    sessions = _sessions_vivantes()
    if sessions is None:
        return False
    valeur, source = plafond.lire_machine()
    voulu = {"workers_actifs": compter_workers(sessions), "plafond_machine": valeur,
             "source_machine": source, "par_projet": workers_par_projet(sessions)}
    if _miroir(projet) == voulu:
        return False
    chemin = chemin_charge(projet)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    temporaire = chemin.with_name(chemin.name + ".tmp")
    temporaire.write_text(json.dumps(voulu), encoding="utf-8")
    os.replace(temporaire, chemin)
    return True


def plafond_machine(projet, sessions) -> tuple[int, str]:
    """(plafond de la machine, source). Un appelant qui voit tmux (le facteur, l'utilisateur) lit le
    fichier de réglages ; sans tmux (un agent), le plafond inscrit par le facteur quand son
    battement est frais, sinon la lecture directe du fichier, puis le défaut."""
    if sessions is None:
        from cime.lanceur.surveillant import battement_frais
        if battement_frais(Path(projet)):
            inscrit = _plafond_machine_inscrit(projet)
            if inscrit is not None:
                return inscrit
    return plafond.lire_machine()


def _en_vigueur(projet, sessions) -> tuple[int, str]:
    return plafond.en_vigueur(plafond_machine(projet, sessions)[0], plafond.plafond_projet(projet))


def plafond_en_vigueur(projet) -> tuple[int, str]:
    """(plafond, source) : le plus bas du plafond de la machine et de celui du projet."""
    return _en_vigueur(projet, _sessions_vivantes())


def charge_machine(projet) -> tuple[int | None, int, str | None]:
    """(workers actifs, plafond en vigueur, source du compte). Source : `"tmux"` quand
    l'appelant voit tmux ; `"facteur"` quand le compte vient du fichier du facteur, qui bat ;
    None quand on ne sait pas (facteur arrêté, fichier absent ou illisible) — un compte inscrit
    par un facteur arrêté est périmé et ne sert pas."""
    sessions = _sessions_vivantes()
    limite = _en_vigueur(projet, sessions)[0]
    if sessions is not None:
        return compter_workers(sessions), limite, "tmux"
    from cime.lanceur.surveillant import battement_frais
    actifs = _compte_inscrit(projet) if battement_frais(Path(projet)) else None
    return actifs, limite, ("facteur" if actifs is not None else None)


def plafond_atteint(projet) -> tuple[bool, int, int]:
    """(atteint, workers actifs sur la machine, plafond), d'après tmux : pour l'appelant qui le voit."""
    sessions = _sessions_vivantes() or set()
    actifs, limite = compter_workers(sessions), _en_vigueur(projet, sessions)[0]
    return actifs >= limite, actifs, limite


def _lancement_de_worker_en_file(projet, identifiant) -> bool:
    """Vrai si l'ordre est encore en file et lance un worker pour un autre que l'utilisateur
    (le seul lancement que le plafond peut retenir)."""
    conn = ouvrir(projet)
    try:
        ligne = conn.execute(
            "SELECT verbe, auteur, parametres FROM ordres WHERE id = ? AND etat = 'en_file'",
            (identifiant,)).fetchone()
    finally:
        conn.close()
    if ligne is None or ligne[0] != "lancer" or ligne[1] == "utilisateur":
        return False
    return json.loads(ligne[2] or "{}").get("role") == "worker"


def _retenu_par_le_plafond(projet, identifiant) -> bool:
    """Décision du facteur, qui voit tmux : un lancement de worker attend si le plafond est atteint
    ou si tmux ne répond pas (un tmux muet n'est pas « zéro worker »)."""
    if not _lancement_de_worker_en_file(projet, identifiant):
        return False
    sessions = _sessions_vivantes()
    return sessions is None or compter_workers(sessions) >= _en_vigueur(projet, sessions)[0]


def cibles_en_file(projet) -> list[str]:
    """Cibles des lancements de worker en file, dans l'ordre de la file."""
    conn = ouvrir(projet)
    try:
        en_file = conn.execute(
            "SELECT id, cible FROM ordres WHERE etat = 'en_file' AND verbe = 'lancer' ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    return [cible for identifiant, cible in en_file
            if _lancement_de_worker_en_file(projet, identifiant)]


def lancements_retenus(projet) -> tuple[list[str], int | None, int]:
    """(cibles des lancements de worker qui attendent une place, workers actifs, plafond). Les
    cibles sont vides tant que le plafond n'est pas atteint ; avec un compte inconnu (actifs
    None), tout lancement en file est dit en attente."""
    cibles = cibles_en_file(projet)
    actifs, plafond, _ = charge_machine(projet)
    retenu = actifs is None or actifs >= plafond
    return (cibles if retenu else []), actifs, plafond


def _executer_en_file(projet, identifiant) -> bool:
    """Prend l'ordre s'il est encore `en_file` (prise atomique), l'exécute, écrit son résultat :
    un ordre n'est exécuté qu'une seule fois. Renvoie True si cet appelant l'a exécuté.
    Un lancement de worker n'est pas pris tant que le plafond de workers est atteint : il reste
    en file et sera repris au tour suivant."""
    if _retenu_par_le_plafond(projet, identifiant):
        return False
    ordre = _prendre_ordre(projet, identifiant)
    if ordre is None:
        return False
    try:
        etat, code, texte = executer(projet, ordre)
    except Exception as e:  # un ordre qui plante ne bloque pas la file
        etat, code, texte = "echec", 1, f"{type(e).__name__} : {e}"
    conn = ouvrir(projet)
    try:
        with conn:
            conn.execute(
                "UPDATE ordres SET etat = ?, resultat = ?, fini = ? WHERE id = ?",
                (etat, json.dumps({"code": code, "texte": texte}, ensure_ascii=False),
                 horodatage(), identifiant))
    finally:
        conn.close()
    return True


def clore_interrompus(projet) -> int:
    """Au démarrage du facteur : un ordre pris (`execute`) dont le résultat n'a jamais été écrit
    (facteur tué en route) est clos en `echec` — jamais rejoué : il a peut-être agi."""
    conn = ouvrir(projet)
    try:
        with conn:
            cur = conn.execute(
                "UPDATE ordres SET etat = 'echec', fini = ?, resultat = ? "
                "WHERE etat = 'execute' AND resultat IS NULL",
                (horodatage(), json.dumps(
                    {"code": 1, "texte": "facteur interrompu pendant l'exécution : "
                                         "vérifier l'effet, l'ordre n'est pas rejoué"},
                    ensure_ascii=False)))
        return cur.rowcount
    finally:
        conn.close()


def ordres_en_file(projet) -> list[int]:
    conn = ouvrir(projet)
    try:
        return [r[0] for r in conn.execute(
            "SELECT id FROM ordres WHERE etat = 'en_file' ORDER BY id")]
    finally:
        conn.close()


def facteur_une_fois(projet) -> int:
    """Bat, puis exécute dans l'ordre d'id les ordres en file. Retourne leur nombre."""
    conn = ouvrir(projet)
    try:
        with conn:
            conn.execute(
                "INSERT INTO facteur (id, battement, version) VALUES (1, ?, 'banc') "
                "ON CONFLICT(id) DO UPDATE SET battement = excluded.battement",
                (horodatage(),))
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM ordres WHERE etat = 'en_file' ORDER BY id")]
    finally:
        conn.close()
    for identifiant in ids:
        _executer_en_file(projet, identifiant)
    return len(ids)


def facteur(args) -> int:
    def lancer_facteur(_):
        projet = commandes.projet_courant()
        print(f"{facteur_une_fois(projet)} ordre(s) exécuté(s)")
        return 0
    return commandes.lancer_commande("facteur", lancer_facteur, args)


# --- préconditions de lancer / terminer / compacter / voir --------------------------------

def _accords_libres(conn, de, a, objet):
    return conn.execute(
        "SELECT id, corps FROM messages m WHERE nature = 'accord' AND de = ? AND a = ?"
        " AND objet = ? AND NOT EXISTS (SELECT 1 FROM transitions t"
        " WHERE t.message_id = m.id AND t.etat = 'clos') ORDER BY id",
        (de, a, objet)).fetchall()


def _ordre_en_file_portant(conn, accord: int) -> int | None:
    """Id de l'ordre encore en file qui consommera cet accord, s'il y en a un."""
    ligne = conn.execute(
        "SELECT id FROM ordres WHERE etat = 'en_file' AND json_extract(parametres, '$.accord') = ?"
        " ORDER BY id LIMIT 1", (accord,)).fetchone()
    return ligne[0] if ligne else None


def statut_equipe(projet: Path, equipe: str) -> str | None:
    fichier = Path(projet) / ".orga" / "dependencies.md"
    if not fichier.is_file():
        return None
    section = None
    for ligne in fichier.read_text(encoding="utf-8").splitlines():
        if ligne.startswith("## "):
            section = ligne[3:].strip().strip("`")
        elif section == equipe:
            trouve = re.match(r"^\W*Statut\W*:\s*(.*)$", ligne)
            if trouve:
                return trouve.group(1).strip().lstrip("*_` ").strip()
    return None


def workers_actifs(projet: Path, equipe: str) -> list[str]:
    dossier = Path(projet) / ".orga" / "teams" / equipe / "tasks" / "in-progress"
    return sorted(f.stem for f in dossier.glob("*.md")) if dossier.is_dir() else []


def message_integration(equipe: str | None = None) -> str:
    cible = equipe or "<équipe>"
    return ("le worker d'intégration est lancé par l'Assistant seul : demande-le à l'Assistant "
            f"(`cime envoyer --a assistant --nature question --objet integration:{cible}`)")


def _preconditions_integration(projet, moi, args) -> dict:
    """`cime lancer worker integration <requête>` : réservé à l'Assistant, qui n'a pas besoin
    d'accord (c'est lui qui les donne) ; la requête est un fichier `requests/todo/<requête>.md`."""
    if moi != "assistant":
        origine = moi[len("coord-"):] if moi.startswith("coord-") else None
        raise Refus(message_integration(origine))
    if not args.modele:
        raise Refus("--modele obligatoire pour un worker")
    requete = Path(projet) / ".orga" / "teams" / "integration" / "requests" / "todo" / f"{args.tache}.md"
    if not requete.is_file():
        raise Refus(f"requête absente : {requete.relative_to(projet)}")
    return {"role": "worker", "equipe": args.equipe, "tache": args.tache, "modele": args.modele}


def _preconditions_worker(conn, projet, moi, args) -> dict:
    equipe, tache, modele = args.equipe, args.tache, args.modele
    from cime.fondation.lancer import EQUIPE_INTEGRATION
    if equipe == EQUIPE_INTEGRATION:
        return _preconditions_integration(projet, moi, args)
    if moi != f"coord-{equipe}":
        raise Refus(f"seul coord-{equipe} lance un worker de l'équipe {equipe}")
    if not modele:
        raise Refus("--modele obligatoire pour un worker")
    objet = f"lancer-worker:{equipe}:{tache}"
    libres = _accords_libres(conn, "assistant", moi, objet)
    if not libres:
        raise Refus(f"aucun accord non consommé pour {objet} : fais une "
                    "`demande_accord` à l'Assistant")
    # Un accord n'est consommé qu'à l'exécution : tant qu'un ordre en file le porte, il est pris.
    pris = {identifiant: _ordre_en_file_portant(conn, identifiant) for identifiant, _ in libres}
    if all(pris.values()):
        raise Refus(f"déjà en file : ordre #{min(pris.values())} ({objet})")
    libres = [(i, c) for i, c in libres if not pris[i]]
    candidats = []
    for identifiant, corps in libres:
        try:
            donnees = json.loads(corps or "{}")
        except ValueError:
            donnees = {}
        if donnees.get("modele") == modele:
            candidats.append((identifiant, donnees))
    if not candidats:
        accordes = sorted({json.loads(c or "{}").get("modele", "?") for _, c in libres})
        raise Refus(f"l'accord pour {objet} porte le modèle {', '.join(accordes)}, "
                    f"pas {modele}")
    statut = statut_equipe(projet, equipe)
    if statut and statut.startswith("BLOQUÉ"):
        raise Refus(f"l'équipe {equipe} est bloquée (dependencies.md) : {statut}")
    autres = [t for t in workers_actifs(projet, equipe) if t != tache]
    if autres:  # un autre worker est actif : il faut un accord parallèle
        candidats = [c for c in candidats if c[1].get("parallele")]
        if not candidats:
            raise Refus(f"un worker est déjà actif dans l'équipe {equipe} "
                        f"({', '.join(autres)}) et l'accord n'est pas parallèle")
    bon = candidats[0]
    todo = projet / ".orga" / "teams" / equipe / "tasks" / "todo" / f"{tache}.md"
    params = {"role": "worker", "equipe": equipe, "tache": tache, "modele": modele,
              "accord": bon[0]}
    if not todo.is_file():
        from cime.fondation import fermeture, lancer
        if not lancer.tache_orpheline(projet, lire_manifeste(projet), equipe, tache):
            raise Refus(f"tâche absente : {todo.relative_to(projet)}")
        if fermeture.est_ferme(projet):
            raise Refus("projet fermé : rouvrir d'abord")
        params["reprise"] = True
    return params


def _preconditions_coord(conn, projet, moi, args) -> dict:
    if moi != "assistant":
        raise Refus("seul l'Assistant lance un coordinateur")
    equipe = args.equipe
    params = {"role": "coord", "equipe": equipe, "modele": args.modele,
              "reprendre": bool(args.reprendre), "session": args.session}
    if getattr(args, "remplacer", False):
        if not args.reprendre:
            raise Refus("--remplacer n'a de sens qu'avec --reprendre")
        params["remplacer"] = True
    if args.reprendre:
        return params
    phase = getattr(args, "phase", None)
    if not phase:
        raise Refus("--phase obligatoire : l'accord de l'utilisateur porte sur une phase du chantier")
    objet = f"chantier:{equipe}:{phase}"
    libres = _accords_libres(conn, "utilisateur", "assistant", objet)
    if libres:   # l'accord de l'utilisateur est essayé en premier, et rien ne change
        params["accord"] = libres[0][0]
        return params
    annonce, complement = _voie_automatique(conn, projet, equipe, phase)
    if annonce is None:
        message = f"aucun accord de l'utilisateur non consommé pour {objet}"
        raise Refus(f"{message} {complement}" if complement else message)
    params["accord"] = annonce   # l'exécution de l'ordre la clôt avec {"par_ordre": id}
    params["voie"] = "auto"
    return params


_NOMS_CONDITIONS = {1: "mode autonome actif", 2: "annonce de l'Assistant",
                    3: "mandat et dépendances", 4: "plafond de lancements"}


def _annonces_libres(conn, equipe, phase):
    return conn.execute(
        "SELECT id FROM messages m WHERE nature = 'rapport_utilisateur' AND de = 'assistant'"
        " AND a = 'utilisateur' AND objet = ? AND NOT EXISTS (SELECT 1 FROM transitions t"
        " WHERE t.message_id = m.id AND t.etat = 'clos') ORDER BY id",
        (f"chantier-auto:{equipe}:{phase}",)).fetchall()


def _voie_automatique(conn, projet, equipe, phase):
    """Les cinq conditions de la voie automatique, dans l'ordre.
    Rend (id de l'annonce, None) si toutes tiennent ; sinon (None, complément du refus) — le
    complément nomme la première qui échoue, ou vaut None quand le mode est inactif (le message
    de refus reste alors celui d'avant). Une erreur de lecture fait échouer la condition qui la
    subit (la cinquième) : jamais un laissez-passer."""
    from cime.fondation import fusions_auto

    def refus(numero, cause):
        return None, (f"L'option « Mode autonome » est active, mais la voie automatique est "
                      f"refusée : condition {numero} ({_NOMS_CONDITIONS[numero]}) — {cause}.")

    def illisible(numero, e):
        return refus(numero, f"lecture impossible ({type(e).__name__} : {e})")

    try:
        etat = fusions_auto.etat_courant(projet)
        if not etat["active"]:
            return None, None
        if etat["suspendue"]:
            return refus(1, "le mode est suspendu (la liste réservée, le plafond ou la portée "
                            "ne sont plus ceux de l'activation)")
        if (etat["portee"] or 0) < fusions_auto.PORTEE:
            return refus(1, f"la portée de l'activation ({etat['portee']}) ne couvre pas les "
                            f"chantiers (≥ {fusions_auto.PORTEE})")
    except Exception as e:
        return illisible(1, e)

    try:
        annonces = _annonces_libres(conn, equipe, phase)
    except Exception as e:
        return illisible(2, e)
    if not annonces:
        return refus(2, f"aucune annonce non consommée chantier-auto:{equipe}:{phase} "
                        "(rapport_utilisateur de l'Assistant à l'utilisateur)")

    try:
        mandat = Path(projet) / ".orga" / "teams" / equipe / "mandate.md"
        if not mandat.is_file():
            return refus(3, f"{mandat.relative_to(projet)} absent")
        if not mandat.read_text(encoding="utf-8").strip():
            return refus(3, f"{mandat.relative_to(projet)} vide")
        statut = statut_equipe(projet, equipe)
        if statut and statut.startswith("BLOQUÉ"):
            return refus(3, f"l'équipe {equipe} est bloquée (dependencies.md) : {statut}")
    except Exception as e:
        return illisible(3, e)

    try:
        plafond = fusions_auto.plafond_chantiers(projet)
        if plafond > 0:
            n = fusions_auto.lancements_auto_24h_strict(projet)
            if n >= plafond:
                return refus(4, f"{n} lancements automatiques dans les dernières 24 h, "
                                f"plafond {plafond}")
    except Exception as e:
        return illisible(4, e)

    return annonces[0][0], None


def lancer_par_agent(moi: str, args) -> int:
    projet = commandes.projet_courant()
    conn = ouvrir(projet)
    try:
        if getattr(args, "remplacer", False) and (args.role != "coord" or moi != "assistant"):
            raise Refus("--remplacer est réservé à l'Assistant, pour un coordinateur "
                        "(lancer coord <équipe> --reprendre --remplacer)")
        if args.role == "worker":
            params = _preconditions_worker(conn, projet, moi, args)
        elif args.role == "coord":
            params = _preconditions_coord(conn, projet, moi, args)
        else:
            if moi != "assistant":
                raise Refus("seuls l'utilisateur et l'Assistant relancent l'Assistant")
            params = {"role": "assistant", "modele": args.modele,
                      "reprendre": bool(args.reprendre), "session": args.session}
    finally:
        conn.close()
    cible = {"worker": f"worker-{args.equipe}-{args.tache}", "coord": f"coord-{args.equipe}",
             "assistant": "assistant"}[args.role]
    identifiant, resultat = poser_et_attendre(projet, moi, "lancer", cible, params)
    return _issue(identifiant, resultat, projet)


def _synthese_presente(projet, equipe, tache) -> bool:
    dossier = Path(projet) / ".orga" / "teams" / equipe / "conversations"
    return dossier.is_dir() and any(dossier.glob(f"{tache}-*.md"))


def verifier_fermeture(conn, projet, moi, equipe, tache) -> str | None:
    """Motif de refus d'un `terminer` par un agent, ou None."""
    worker = f"worker-{equipe}-{tache}"
    if conn.execute("SELECT 1 FROM messages WHERE de = ? AND a = ? AND nature = 'travail_pret'",
                    (worker, f"coord-{equipe}")).fetchone() is None:
        return f"aucun travail_pret de {worker} à coord-{equipe}"
    rapports = Path(projet) / ".orga" / "teams" / equipe / "reports"
    if not list(rapports.glob(f"{worker}-*.md")):
        return f"aucun rapport : cherché .orga/teams/{equipe}/reports/{worker}-*.md"
    if not _synthese_presente(projet, equipe, tache):
        return (f"aucune synthèse de conversation : cherché "
                f".orga/teams/{equipe}/conversations/{tache}-*.md")
    return None


def voir(args) -> int:
    return commandes.lancer_commande("voir", _voir, args)


def _voir(args) -> int:
    from cime.fondation.compacter import est_superieur
    moi = commandes.identite_appelant()
    projet = commandes.projet_courant()
    cible = args.agent
    if cible == "assistant":
        raise Refus("la session de l'Assistant est privée : on ne la regarde jamais")
    if moi != "utilisateur" and not est_superieur(moi, cible, projet):
        raise Refus(f"seul le supérieur direct de {cible} peut la voir")
    if moi == "utilisateur":
        etat, code, texte = executer(projet, {"id": 0, "auteur": moi, "verbe": "capturer",
                                              "cible": cible, "parametres": {}})
        if texte:
            print(texte)
        return 2 if etat == "refuse" else 1 if etat == "echec" else 0
    identifiant, resultat = poser_et_attendre(projet, moi, "capturer", cible, {})
    return _issue(identifiant, resultat, projet)
