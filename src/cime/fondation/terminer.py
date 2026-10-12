"""`cime terminer` : clôt la tâche d'un worker, sur sa demande ou sur ordre de son supérieur."""

import subprocess
import sys

from cime.fondation.compacter import est_superieur
from cime.fondation.envoyer import _projet
from cime.fondation.nom import VAR_PROJET
from cime.fondation.projet import (ErreurProjet, equipe_de, lire_manifeste,
                                   session_tmux, valider_identite)
from cime.fondation.registre import inscrire_message, inscrire_transition, ouvrir
from cime.signaux.identite import ErreurIdentite, appelant


_LIBELLE = {"refuse": "refusé", "echec": "échec"}


def _tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", *args], capture_output=True, text=True)


def _erreur(message: str, code: int = 2) -> int:
    print(f"terminer : {message}", file=sys.stderr)
    return code


def journaliser(projet, *, de, worker, tache, resultat, rapport=None) -> int:
    """Ligne de traçabilité (consigne, `--attend rien`) : déjà close, elle n'est jamais livrée."""
    conn = ouvrir(projet)
    try:
        with conn:
            identifiant = inscrire_message(
                conn, de=de, a=worker, nature="consigne",
                resume=f"fin de tâche {tache} — {resultat}"[:160],
                fichier=str(rapport.relative_to(projet)) if rapport else None,
                equipe=equipe_de(projet, worker), commit=False)
            inscrire_transition(conn, identifiant, "clos", de,
                                {"journal": "terminer"}, commit=False)
        return identifiant
    finally:
        conn.close()


_journaliser = journaliser


class _Refus(Exception):
    def __init__(self, motif: str, message: str, code: int = 2, genre: str = "refusé"):
        super().__init__(message)
        self.motif, self.code, self.genre = motif, code, genre


def _terminer(args) -> int:
    try:
        de = appelant()
    except ErreurIdentite as e:
        return _erreur(str(e))
    equipe, tache = args.equipe, args.tache
    worker = f"worker-{equipe}-{tache}"
    try:
        valider_identite(de)
        valider_identite(worker)
    except ValueError as e:
        return _erreur(str(e))
    projet = _projet()
    if projet is None:
        return _erreur(f"{VAR_PROJET} absent (ou ne désigne pas un projet) : lance cette "
                       "commande depuis un agent lancé par `cime lancer`")
    rapport = None
    try:
        if getattr(args, "verifie", None) or getattr(args, "motif", None):
            return _verifie(projet, de, equipe, tache, worker, args)
        if de != "utilisateur" and not est_superieur(de, worker, projet):
            raise _Refus("pas le supérieur direct",
                         f"seul coord-{equipe} peut terminer {worker}")
        if de != "utilisateur":
            return _par_ordre(projet, de, equipe, tache, worker)
        rapport = _tenter(projet, equipe, tache, worker)
    except _Refus as e:
        journaliser(projet, de=de, worker=worker, tache=tache,
                    resultat=f"{e.genre} : {e.motif}")
        return _erreur(str(e), e.code)
    except Exception as e:
        journaliser(projet, de=de, worker=worker, tache=tache,
                    resultat=f"échec : {e}"[:80])
        raise
    identifiant = journaliser(projet, de=de, worker=worker, tache=tache,
                              resultat="rapport accepté, session fermée", rapport=rapport)
    print(f"message #{identifiant} inscrit")
    return 0


def _dans_main(projet, sha: str) -> bool:
    """Vrai si `sha` est un commit de `main` (ancêtre de `main`, ou `main` lui-même)."""
    def git(*a):
        return subprocess.run(["git", "-C", str(projet), *a], capture_output=True, text=True)
    if git("rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}").returncode != 0:
        return False
    return git("merge-base", "--is-ancestor", sha, "main").returncode == 0


def _verifie(projet, de, equipe, tache, worker, args) -> int:
    """Tâche finie avant le registre, sans `travail_pret` au registre : l'Assistant atteste, sha de `main` à
    l'appui. Inscrit un `travail_pret` de reprise au nom du worker, puis la fermeture suit son chemin
    habituel (rapport et synthèse restent exigés)."""
    from cime.signaux import commandes, ordres
    sha, motif = args.verifie, (args.motif or "").strip()
    if not sha:
        raise _Refus("--motif sans --verifie", "--motif ne va qu'avec --verifie <sha>")
    if de != "assistant":
        raise _Refus("--verifie réservé à l'Assistant",
                     "--verifie est réservé à l'Assistant (il atteste qu'une tâche finie avant le registre est livrée)")
    if not motif:
        raise _Refus("--verifie sans --motif", "--verifie exige --motif \"<texte>\"")
    if not _dans_main(projet, sha):
        raise _Refus("sha hors main", f"le commit {sha} est inconnu ou n'est pas dans main")
    rapports = projet / ".orga" / "teams" / equipe / "reports"
    if not list(rapports.glob(f"{worker}-*.md")):
        m = f"aucun rapport : cherché .orga/teams/{equipe}/reports/{worker}-*.md"
        raise _Refus(m, m)
    if not ordres._synthese_presente(projet, equipe, tache):
        m = f"aucune synthèse de conversation : cherché .orga/teams/{equipe}/conversations/{tache}-*.md"
        raise _Refus(m, m)
    conn = ouvrir(projet)
    try:
        if ordres.verifier_fermeture(conn, projet, de, equipe, tache) is not None:   # pas de travail_pret
            commandes.inscrire(
                conn, de=worker, a=f"coord-{equipe}", nature="travail_pret",
                resume=f"reprise vérifiée par l'Assistant ({sha[:12]}) : {motif}"[:160],
                equipe=equipe, auteur=de,
                preuve={"cmd": "terminer", "verifie": sha, "par": de, "motif": motif})
    finally:
        conn.close()
    return _par_ordre(projet, de, equipe, tache, worker)


def _par_ordre(projet, de, equipe, tache, worker) -> int:
    """Agent : préconditions, puis un ordre `fermer` que le facteur exécute."""
    from cime.signaux import ordres
    conn = ouvrir(projet)
    try:
        motif = ordres.verifier_fermeture(conn, projet, de, equipe, tache)
    finally:
        conn.close()
    if motif:
        raise _Refus(motif, motif)
    identifiant, resultat = ordres.poser_et_attendre(
        projet, de, "fermer", worker, {"equipe": equipe, "tache": tache, "worker": worker})
    if resultat is None:
        journaliser(projet, de=de, worker=worker, tache=tache,
                    resultat=f"ordre #{identifiant} en file")
    elif resultat["etat"] != "execute":
        journaliser(projet, de=de, worker=worker, tache=tache,
                    resultat=f"{_LIBELLE[resultat['etat']]} : {resultat['texte']}"[:80])
    return ordres._issue(identifiant, resultat)


def _tenter(projet, equipe, tache, worker):
    """Ferme la session, déplace la tâche ; renvoie le rapport retenu ou lève _Refus."""
    manifeste = lire_manifeste(projet)
    racine = projet / ".orga" / "teams" / equipe
    source = racine / "tasks" / "in-progress" / f"{tache}.md"
    cible_done = racine / "tasks" / "done" / f"{tache}.md"
    if not source.is_file():
        raise _Refus("tâche introuvable", f"tâche introuvable : {source.relative_to(projet)}")
    rapports = sorted((racine / "reports").glob(f"{worker}-*.md"))
    if not rapports:
        raise _Refus("aucun rapport", "aucun rapport : cherché "
                     f"{(racine / 'reports' / (worker + '-*.md')).relative_to(projet)}")
    if cible_done.exists():
        raise _Refus("cible déjà présente",
                     f"la cible existe déjà : {cible_done.relative_to(projet)}")

    session = session_tmux(manifeste, worker)
    if session is None:
        raise _Refus("pas de session", f"pas de session pour {worker}")
    if _tmux("has-session", "-t", f"={session}").returncode == 0:
        r = _tmux("kill-session", "-t", f"={session}")
        if r.returncode != 0:
            raise _Refus(f"fermeture de {session} impossible",
                         f"fermeture de la session {session} impossible : {r.stderr.strip()}", 1, "échec")
        print(f"session {session} fermée")
    else:
        print(f"terminer : session {session} absente, rien à fermer", file=sys.stderr)
    cible_done.parent.mkdir(parents=True, exist_ok=True)
    source.rename(cible_done)
    print(f"tâche déplacée : {cible_done.relative_to(projet)}")
    return rapports[-1]


def executer(args) -> int:
    try:
        return _terminer(args)
    except (ErreurProjet, ValueError) as e:
        return _erreur(str(e), 1)
