"""`cime fusionner <équipe>` : la file de fusion. Fige la tête de la branche de l'équipe, vérifie les
règles d'accord, attend que la machine soit libre, prend le verrou (une fusion à la fois), fusionne
dans un worktree d'essai, lance la suite entière comme la CI, puis, si tout est vert seulement,
annonce, fusionne dans le dépôt principal, journalise, réinstalle cime et arrête le facteur.

Réservée à l'Assistant et à l'utilisateur. Le premier échec arrête tout et dit pourquoi ; le worktree
d'essai et le verrou sont libérés dans tous les cas. Jamais de `git push`, jamais de suppression de
branche, jamais de `shell=True`."""
import errno
import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from cime.fondation import fusions_auto, garde, hook
from cime.fondation.nom import NOM, VAR_AGENT
from cime.fondation.projet import ErreurProjet, lire_manifeste, trouver_projet
from cime.fondation.registre import horodatage, ouvrir

CODE_FUSIONNE, CODE_REFUS, CODE_OCCUPE = 0, 1, 2

AUTORISES = ("assistant", "utilisateur")
DELAI_CHARGE_S = 20 * 60     # attente maximale d'une machine sans worker
SONDAGE_S = 15               # un sondage de la charge toutes les 15 secondes
STATUT_S = 60                # un message d'attente par minute
ECHECS_AFFICHES = 20
COMMANDE_SUITE = ("-m", "pytest", "tests", "-q", "-p", "no:cacheprovider")   # celle de la CI
VERROU = "fusionner.verrou"
RESUME_MAX = 160             # la longueur du résumé d'un message
CORPS_MAX = 4000             # celle de son corps
FICHIERS_AFFICHES = 3        # fichiers réservés nommés dans le résumé de la demande
VARIABLES_ECARTEES = ("CIME_AGENT", "CIME_PROJET", "CLAUDECODE", "TMUX")   # la CI n'en a aucune

# Les points d'appel des effets de bord : un test les remplace, la commande les appelle par ces noms.
_horloge = time.monotonic
_dormir = time.sleep


class _Refus(Exception):
    def __init__(self, message: str, code: int = CODE_REFUS):
        super().__init__(message)
        self.code = code


def _dire(texte: str) -> None:
    print(texte, flush=True)


def _git(projet, *args, cwd=None) -> subprocess.CompletedProcess:
    """Tout appel de git passe ici (arguments en liste, jamais de shell)."""
    return subprocess.run(["git", "-C", str(cwd or projet), *args], capture_output=True, text=True)


def _sha(projet, ref: str) -> str | None:
    r = _git(projet, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    sha = r.stdout.strip()
    return sha if r.returncode == 0 and sha else None


# --- charge de la machine ---------------------------------------------------------------------

def _workers_actifs(projet) -> int | None:
    from cime.signaux import ordres
    return ordres.charge_machine(projet)[0]


def _attendre_la_machine(projet, maintenant: bool) -> None:
    """Rien à attendre quand aucun worker ne tourne ; sinon le dit, puis attend (sondage de 15 s,
    un message par minute) jusqu'à 20 minutes, ou passe tout de suite avec `--maintenant`."""
    debut = _horloge()
    dernier = None
    while True:
        try:
            actifs = _workers_actifs(projet)
        except Exception as e:
            _dire(f"charge de la machine illisible ({type(e).__name__}) : je continue")
            return
        if actifs is None:
            _dire("charge de la machine inconnue (ni tmux ni facteur ne la donnent) : je continue")
            return
        if actifs == 0:
            return
        if maintenant:
            _dire(f"{actifs} worker(s) en cours : --maintenant, je n'attends pas")
            return
        ecoule = _horloge() - debut
        if ecoule >= DELAI_CHARGE_S:
            raise _Refus(f"{actifs} worker(s) en cours après {DELAI_CHARGE_S // 60} minutes "
                         "d'attente : refus (relance plus tard, ou avec --maintenant)", CODE_OCCUPE)
        if dernier is None or ecoule - dernier >= STATUT_S:
            dernier = ecoule
            _dire(f"{actifs} worker(s) en cours : j'attends qu'aucun ne tourne "
                  f"({int(ecoule // 60)} min sur {DELAI_CHARGE_S // 60})")
        _dormir(SONDAGE_S)


# --- verrou : une fusion à la fois -----------------------------------------------------------

def _vivant(pid) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _duree(depuis: str | None) -> str:
    try:
        debut = datetime.strptime(depuis, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        secondes = int((datetime.now(timezone.utc) - debut).total_seconds())
    except (TypeError, ValueError):
        return "un moment"
    return f"{secondes // 60} min {secondes % 60:02d} s" if secondes >= 60 else f"{secondes} s"


def _contenu(fd) -> dict:
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        donnees = json.loads(os.read(fd, 4096).decode("utf-8") or "{}")
    except (OSError, ValueError):
        return {}
    return donnees if isinstance(donnees, dict) else {}


class _Verrou:
    """`.orga/etat/fusionner.verrou`, tenu par un `flock` exclusif : il disparaît avec le processus
    qui meurt, même sans passer par `finally`. Contient le pid, l'équipe, le sha et l'heure."""

    def __init__(self, projet, equipe: str, sha: str):
        self.chemin = Path(projet) / ".orga" / "etat" / VERROU
        self.equipe, self.sha = equipe, sha
        self.fd = None

    def prendre(self) -> None:
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(5):    # le fichier a pu être retiré entre l'ouverture et le verrou
            fd = os.open(self.chemin, os.O_RDWR | os.O_CREAT, 0o644)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as e:
                if e.errno not in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES):
                    os.close(fd)
                    raise
                tenu = _contenu(fd)
                os.close(fd)
                raise _Refus(self._message_occupe(tenu), CODE_OCCUPE) from None
            try:
                meme = os.stat(self.chemin).st_ino == os.fstat(fd).st_ino
            except FileNotFoundError:
                meme = False
            if not meme:
                os.close(fd)
                continue
            self.fd = fd
            break
        else:
            raise _Refus("verrou de fusion introuvable après cinq essais", CODE_OCCUPE)
        ancien = _contenu(self.fd)
        if ancien.get("pid") is not None and not _vivant(ancien.get("pid")):
            _dire(f"verrou repris : la fusion de {ancien.get('equipe')} "
                  f"({str(ancien.get('sha', ''))[:7]}) du pid {ancien['pid']} n'existe plus")
        os.ftruncate(self.fd, 0)
        os.lseek(self.fd, 0, os.SEEK_SET)
        os.write(self.fd, json.dumps({"pid": os.getpid(), "equipe": self.equipe, "sha": self.sha,
                                      "depuis": horodatage()}).encode("utf-8"))

    @staticmethod
    def _message_occupe(tenu: dict) -> str:
        if not tenu:
            return "une fusion est en cours (verrou tenu) : relance dans un moment"
        return (f"fusion de {tenu.get('equipe')} ({str(tenu.get('sha', ''))[:7]}) en cours depuis "
                f"{_duree(tenu.get('depuis'))} par le pid {tenu.get('pid')} : relance après")

    def liberer(self) -> None:
        if self.fd is None:
            return
        try:
            self.chemin.unlink()
        except OSError:
            pass
        try:
            os.close(self.fd)    # relâche le flock
        finally:
            self.fd = None


# --- journal ----------------------------------------------------------------------------------

def _journaliser_refus(projet, auteur: str, equipe: str, branche: str, sha: str, resultat: str,
                       details: dict) -> None:
    """La ligne de `fusions.log` et la ligne `journal` d'une fusion refusée. Ne lève jamais :
    le refus est déjà dit à l'écran."""
    try:
        dossier = Path(projet) / ".orga" / "etat"
        dossier.mkdir(parents=True, exist_ok=True)
        with open(dossier / "fusions.log", "a", encoding="utf-8") as f:
            f.write(f"{horodatage()} {auteur} {sha} {branche} resultat={resultat}\n")
        conn = ouvrir(projet)
        try:
            with conn:
                conn.execute(
                    "INSERT INTO journal (horodatage, auteur, action, cible, details, resultat)"
                    " VALUES (?, ?, 'fusion_refusee', ?, ?, ?)",
                    (horodatage(), auteur, f"fusion:{equipe}:{sha}",
                     json.dumps(details, ensure_ascii=False), resultat))
        finally:
            conn.close()
    except Exception as e:
        print(f"{NOM} fusionner : journal du refus impossible ({type(e).__name__} : {e})",
              file=sys.stderr)


# --- essai et suite ----------------------------------------------------------------------------

def _python_du_projet(projet) -> str:
    python = Path(projet) / ".venv" / "bin" / "python"
    if not python.exists():
        raise _Refus(f"pas de Python du projet ({python}) : la suite ne peut pas tourner")
    return str(python)


def _lancer_suite(projet, dossier) -> tuple[int, str]:
    """La suite entière, la ligne de la CI, dans le worktree d'essai : (code, sortie)."""
    env = {k: v for k, v in os.environ.items() if k not in VARIABLES_ECARTEES}
    r = subprocess.run([_python_du_projet(projet), *COMMANDE_SUITE], cwd=dossier, env=env,
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


_COMPTES = re.compile(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed)")


def _resume_suite(sortie: str) -> tuple[int, int, list[str]]:
    """(échecs, total, lignes `FAILED …`/`ERROR …` du résumé de pytest)."""
    lignes = [l.rstrip() for l in sortie.splitlines()]
    en_echec = [l for l in lignes if l.startswith(("FAILED ", "ERROR "))]
    comptes = {}
    for l in reversed(lignes):
        trouves = _COMPTES.findall(l)
        if trouves and " in " in l:
            comptes = {nom.rstrip("s") if nom.startswith("error") else nom: int(n)
                       for n, nom in trouves}
            break
    echecs = comptes.get("failed", 0) + comptes.get("error", 0)
    return echecs, sum(comptes.values()), en_echec


def _retirer_essai(projet, essai: Path) -> None:
    """Retire le worktree d'essai, et seulement lui."""
    _git(projet, "worktree", "remove", "--force", str(essai))
    if essai.exists():
        shutil.rmtree(essai, ignore_errors=True)
    _git(projet, "worktree", "prune")


def nom_essai(sha: str) -> str:
    """Le dossier du worktree d'essai : de longueur fixe, indépendante du nom de l'équipe (les chemins
    de socket de la suite en dépendent), et le même pour le même sha (un reste d'essai est reconnu)."""
    return f"fe-{sha[:7]}"


def _essayer(projet, equipe: str, sha: str, base: str, branche: str, auteur: str) -> tuple[int, float]:
    """Fusionne `sha` sur `base` dans un worktree d'essai, lance la suite, retire l'essai dans tous
    les cas. Renvoie (nombre de tests, durée de la suite en secondes) ; `_Refus` si ça n'est pas vert."""
    essai = Path(projet) / ".orga" / "etat" / "tmp" / nom_essai(sha)
    essai.parent.mkdir(parents=True, exist_ok=True)
    if essai.exists():     # reste d'un essai interrompu : le même nom, donc le nôtre
        _retirer_essai(projet, essai)
    try:
        r = _git(projet, "worktree", "add", "--detach", str(essai), base)
        if r.returncode != 0:
            raise _Refus(f"worktree d'essai impossible : {r.stderr.strip()}")
        r = _git(projet, "merge", "--no-ff", "--no-edit", sha, cwd=essai)
        if r.returncode != 0:
            conflits = _git(projet, "diff", "--name-only", "--diff-filter=U", cwd=essai)
            fichiers = [f for f in conflits.stdout.splitlines() if f]
            _journaliser_refus(projet, auteur, equipe, branche, sha, "refuse-conflit",
                               {"fichiers": fichiers})
            raise _Refus("la fusion d'essai a des conflits : "
                         + (", ".join(fichiers) if fichiers else r.stderr.strip() or r.stdout.strip()))
        _dire(f"suite entière en cours sur l'essai de {equipe} ({sha[:7]}) …")
        debut = _horloge()
        code, sortie = _suite(projet, essai)
        duree = _horloge() - debut
        echecs, total, lignes = _resume_suite(sortie)
        if code != 0:
            echecs = echecs or 1
            _journaliser_refus(projet, auteur, equipe, branche, sha, "refuse-tests",
                               {"tests_en_echec": lignes[:ECHECS_AFFICHES], "echecs": echecs,
                                "total": total, "duree_s": round(duree, 1), "code_pytest": code})
            resume = [f"suite entière : {echecs} échec(s) sur {total} (pytest, code {code})"]
            resume += lignes[:ECHECS_AFFICHES]
            if len(lignes) > ECHECS_AFFICHES:
                resume.append(f"… et {len(lignes) - ECHECS_AFFICHES} autre(s)")
            if not lignes:
                resume += sortie.splitlines()[-ECHECS_AFFICHES:]
            raise _Refus("\n".join(resume))
        return total, duree
    finally:
        _retirer_essai(projet, essai)


_suite = _lancer_suite


# --- annonce, fusion, suites -----------------------------------------------------------------

def _annoncer(conn, equipe: str, sha: str, total: int) -> int:
    """L'annonce `fusion-auto:<équipe>:<sha40>` de l'Assistant à l'utilisateur, comme celle que
    l'Assistant envoie à la main ; une annonce déjà faite pour ce sha est reprise."""
    from cime.signaux import commandes
    objet = f"fusion-auto:{equipe}:{sha}"
    ligne = conn.execute("SELECT id FROM messages WHERE de = 'assistant' AND a = 'utilisateur'"
                         " AND nature = 'rapport_utilisateur' AND objet = ? ORDER BY id DESC",
                         (objet,)).fetchone()
    if ligne:
        return ligne[0]
    return commandes.inscrire(
        conn, de="assistant", a="utilisateur", nature="rapport_utilisateur", equipe=equipe,
        objet=objet, resume=f"Fusion automatique de {equipe} ({sha[:7]}) : suite entière verte "
                            f"({total} tests)", auteur="cime",
        preuve={"cmd": "fusionner", "pid": os.getpid()})


def _consommer_accord(conn, projet, sha: str) -> int | None:
    """Un accord = une fusion : l'accord de l'utilisateur qui vise cette pointe est clos."""
    from cime.fondation.registre import inscrire_transition
    accord = garde.accord_pour(sha, garde.accords_fusion_libres(projet))
    if accord is not None:
        inscrire_transition(conn, accord, "clos", "cime",
                            {"par_commande": "fusionner", "pid": os.getpid()})
    return accord


def _apres_fusion(conn, projet, branche: str, sha: str) -> None:
    """Ce que le hook fait après un `git merge` de l'Assistant : suites déclarées, contrats changés."""
    from cime.signaux import suites
    suites.apres_fusion_suites(conn, projet, [(branche, sha, "fusionne")], None)
    try:
        avant = (Path(projet) / ".orga" / "etat" / hook.FUSION_AVANT).read_text(encoding="utf-8").strip()
    except OSError:
        avant = ""
    suites.apres_fusion_contrats(conn, projet, avant, _sha(projet, "HEAD") or "")


def _reinstaller(projet) -> tuple[bool, str]:
    r = subprocess.run(["uv", "tool", "install", "--reinstall", "--quiet", str(projet)],
                       capture_output=True, text=True)
    return r.returncode == 0, (r.stderr or r.stdout).strip()


def _arreter_facteur(projet) -> str:
    """SIGTERM au facteur du projet s'il tourne ; ce qui le relance aujourd'hui le relancera."""
    fichier = Path(projet) / ".orga" / "etat" / "facteur.pid"
    try:
        pid = int(fichier.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return "facteur : pas de pid, rien à arrêter"
    if pid <= 1 or pid == os.getpid() or not _vivant(pid):
        return f"facteur : le pid {pid} ne tourne pas, rien à arrêter"
    os.kill(pid, signal.SIGTERM)
    return f"facteur arrêté (pid {pid})"


def _fusionner_dans_le_depot(projet, equipe: str, branche: str, sha: str, message: str,
                             auteur: str, voie: str, details: dict, total: int) -> None:
    """Annonce (voie automatique), fusion dans le dépôt principal, journal, accord consommé."""
    conn = ouvrir(projet)
    try:
        annonce = _annoncer(conn, equipe, sha, total) if voie == "auto" else None
        hook.ecrire_intentions_fusion(projet, [branche], f"{NOM} fusionner {equipe}", auteur,
                                      shas={branche: sha})
        r = _git(projet, "merge", "--no-ff", "-m", message, sha)
        if r.returncode != 0:
            _git(projet, "merge", "--abort")
            hook.ecrire_resultats_fusion(projet, [branche], auteur, shas={branche: sha})
            _journaliser_refus(projet, auteur, equipe, branche, sha, "refuse-main",
                               {"git": (r.stderr or r.stdout).strip()[:500]})
            raise _Refus("la fusion dans le dépôt principal a échoué (la suite était verte) : "
                         + ((r.stderr or r.stdout).strip() or f"git merge code {r.returncode}"))
        [(_, resultat)] = hook.ecrire_resultats_fusion(projet, [branche], auteur, shas={branche: sha})
        if resultat != "fusionne":
            raise _Refus(f"la fusion de {sha[:7]} n'est pas dans le dépôt principal (résultat : {resultat})")
        if voie == "auto":
            hook.journaliser_fusion_auto(conn, projet, sha, dict(details, annonce=annonce))
        else:
            _consommer_accord(conn, projet, sha)
        try:
            _apres_fusion(conn, projet, branche, sha)
        except Exception as e:
            print(f"{NOM} fusionner : suites et signalements de contrat non inscrits "
                  f"({type(e).__name__} : {e})", file=sys.stderr)
    finally:
        conn.close()


# --- la commande -----------------------------------------------------------------------------

def _regles(projet, branche: str, sha: str) -> tuple[str, dict]:
    """Les règles d'accord de `git merge <branche>`, jugées sur le sha figé : (voie, détails) ou `_Refus`."""
    voie, details, motif = garde.juger_fusion(projet, branche, sha)
    if voie is None:
        raise _Refus(f"fusion non permise : {motif}")
    return voie, details


def _reserves_touchees(projet, reference: str, sha: str) -> list[str] | None:
    """Les fichiers réservés que `merge-base..sha` touche (liste du manifeste plus celle enregistrée à
    l'activation de l'option, comme la voie automatique) ; None si le diff ne se calcule pas."""
    liste = fusions_auto.chemins_reserves(projet)
    liste += [e for e in fusions_auto.etat_courant(projet)["reserves"] if e not in liste]
    base = _git(projet, "merge-base", reference, sha)
    if base.returncode != 0 or not base.stdout.strip():
        return None
    diff = _git(projet, "diff", "--name-only", "--no-renames", "-z", base.stdout.strip(), sha)
    if diff.returncode != 0:
        return None
    return [c for c in diff.stdout.split("\0") if c and fusions_auto.est_reserve(c, liste)]


def _demande_requise(projet, reference: str, sha: str) -> list[str] | None:
    """None quand ce refus n'est pas « l'accord de l'utilisateur manque » ; sinon la liste des fichiers
    réservés touchés (vide : c'est l'option « Fusions automatiques » qui n'ouvre pas la voie). Une branche
    déjà dans la référence n'a rien à fusionner : rien à demander."""
    try:
        if _git(projet, "merge-base", "--is-ancestor", sha, reference).returncode == 0:
            return None
        if garde.accord_pour(sha, garde.accords_fusion_libres(projet)) is not None:
            return None
        etat = fusions_auto.etat_courant(projet)
        touches = _reserves_touchees(projet, reference, sha)
    except Exception:
        return None
    if etat["active"] and not etat["suspendue"] and not touches:
        return None   # la voie automatique est ouverte : le refus vient d'ailleurs (conflit, dépôt…)
    return touches or []


def _etat_de_la_demande(conn, numero: int) -> tuple[str, bool]:
    """(état en clair, refusée par l'utilisateur) d'une demande déjà posée."""
    reponses = {n for (n,) in conn.execute(
        "SELECT nature FROM messages WHERE en_reponse_a = ? AND de = 'utilisateur'", (numero,))}
    if "refus" in reponses:
        return "refusée", True
    if "accord" in reponses:
        return "accordée", False
    ligne = conn.execute("SELECT etat FROM obligations WHERE message_id = ?", (numero,)).fetchone()
    return {"ouverte": "en attente", "satisfaite": "close", "abandonnee": "abandonnée"}.get(
        ligne[0] if ligne else None, "close"), False


def _poser_la_demande(projet, equipe: str, sha: str, fichiers: list[str], motif: str) -> tuple[int, str]:
    """Inscrit la demande d'accord (jamais l'accord) pour ce sha, une seule fois ; renvoie (id de la
    demande, refus à dire). Une demande déjà posée, même close ou refusée, n'est pas reposée."""
    from cime.signaux import commandes
    objet = f"fusion:{equipe}:{sha}"
    conn = ouvrir(projet)
    try:
        ligne = conn.execute("SELECT id FROM messages WHERE de = 'assistant' AND a = 'utilisateur'"
                             " AND nature = 'decision_utilisateur' AND objet = ? ORDER BY id LIMIT 1",
                             (objet,)).fetchone()
        if ligne:
            numero = ligne[0]
            etat, refusee = _etat_de_la_demande(conn, numero)
            if refusee:
                return numero, (f"demande #{numero} refusée par l'utilisateur pour {equipe} {sha[:7]} : "
                                "elle n'est pas reposée (le sha est le même)")
            if etat == "accordée":
                return numero, (f"demande #{numero} déjà accordée pour ce sha et consommée : rien à refaire ; "
                                "si la branche a avancé, c'est un nouveau sha")
            return numero, (f"demande #{numero} déjà posée pour ce sha ({etat}) : attends l'accord de "
                            "l'utilisateur")
        if fichiers:
            noms = ", ".join(fichiers[:FICHIERS_AFFICHES]) + (" …" if len(fichiers) > FICHIERS_AFFICHES else "")
            resume = f"Fusion de {equipe} ({sha[:7]}) : accord requis, touche {noms}"
        else:
            resume = f"Fusion de {equipe} ({sha[:7]}) : accord requis : mode autonome inactif"
        if len(resume) > RESUME_MAX:
            resume = resume[:RESUME_MAX - 1] + "…"
        corps = "\n".join([f"Fusion de la branche de {equipe} au commit {sha}.",
                           "Fichiers réservés touchés : " + (", ".join(fichiers) if fichiers else "aucun"),
                           f"Motif donné par les règles : {motif}"])[:CORPS_MAX]
        numero = commandes.inscrire(
            conn, de="assistant", a="utilisateur", nature="decision_utilisateur", equipe=equipe,
            objet=objet, resume=resume, corps=corps, auteur="cime",
            preuve={"cmd": "fusionner", "pid": os.getpid()})
        return numero, (f"accord de l'utilisateur manquant pour {equipe} {sha[:7]} : demande #{numero} "
                        f"posée sur la page ; relance `{NOM} fusionner {equipe}` après son accord")
    finally:
        conn.close()


def _verifier_regles(projet, equipe: str, branche: str, sha: str, auteur: str,
                     reference: str | None = None) -> tuple[str, dict]:
    """Les règles d'accord, et le refus journalisé (`refuse-accord`) quand elles ne tiennent pas.
    Avec `reference`, un refus faute d'accord pour ce sha pose aussi la demande à l'utilisateur."""
    try:
        return _regles(projet, branche, sha)
    except _Refus as r:
        details = {"motif": str(r)}
        fichiers = _demande_requise(projet, reference, sha) if reference else None
        if fichiers is not None:
            try:
                numero, message = _poser_la_demande(projet, equipe, sha, fichiers, str(r))
            except Exception as e:
                print(f"{NOM} fusionner : demande d'accord non inscrite ({type(e).__name__} : {e})",
                      file=sys.stderr)
            else:
                details["demande"] = numero
                r = _Refus(message)
        _journaliser_refus(projet, auteur, equipe, branche, sha, "refuse-accord", details)
        raise r


def fusionner(projet, equipe: str, *, maintenant: bool = False, message: str | None = None,
              auteur: str = "assistant") -> int:
    debut = _horloge()
    if not re.fullmatch(r"[a-z0-9-]+", equipe):
        raise _Refus(f"nom d'équipe invalide : {equipe!r}")
    manifeste = lire_manifeste(projet)
    branche = manifeste.branche_equipe.format(equipe=equipe)
    reference = manifeste.branche_reference
    # 1. figer la tête : un seul sha, utilisé partout ensuite
    sha = _sha(projet, f"refs/heads/{branche}")
    if sha is None:
        raise _Refus(f"la branche {branche} n'existe pas")
    message = message or f"Fusion {equipe} {sha[:7]}"
    _dire(f"fusion de {branche} figée à {sha[:7]}")
    # 2. les règles d'accord, avant tout essai
    voie, details = _verifier_regles(projet, equipe, branche, sha, auteur, reference)
    # 3. la machine
    _attendre_la_machine(projet, maintenant)
    # 4. une fusion à la fois
    verrou = _Verrou(projet, equipe, sha)
    verrou.prendre()
    try:
        tete = _git(projet, "symbolic-ref", "--short", "HEAD").stdout.strip()
        if tete != reference:
            raise _Refus(f"le dépôt principal n'est pas sur {reference} (il est sur {tete or '?'})")
        # l'attente a pu durer : un accord a pu être consommé entre-temps
        voie, details = _verifier_regles(projet, equipe, branche, sha, auteur)
        base = _sha(projet, f"refs/heads/{reference}")
        if base is None:
            raise _Refus(f"la branche de référence {reference} ne se résout pas")
        # 5 et 6. l'essai et la suite entière
        total, duree = _essayer(projet, equipe, sha, base, branche, auteur)
        # 7. annonce, fusion, réinstallation, facteur
        _fusionner_dans_le_depot(projet, equipe, branche, sha, message, auteur, voie, details, total)
    finally:
        verrou.liberer()
    ok, sortie = _reinstaller(projet)
    if not ok:
        print(f"ATTENTION : fusion faite, mais la réinstallation de cime a échoué ({sortie}) : "
              f"lance `uv tool install --reinstall {projet}`", file=sys.stderr)
    _dire(_arreter_facteur(projet))
    minutes, secondes = divmod(int(duree), 60)
    _dire(f"fusionné : {equipe} {sha[:7]}, suite entière : {total} tests en "
          + (f"{minutes} min {secondes:02d} s" if minutes else f"{secondes} s")
          + f" (au total {int(_horloge() - debut)} s)")
    return CODE_FUSIONNE


def executer(args) -> int:
    agent = os.environ.get(VAR_AGENT) or None
    if agent not in AUTORISES:
        print(f"{NOM} fusionner : réservé à l'Assistant et à l'utilisateur ({VAR_AGENT} doit valoir "
              "assistant ou utilisateur) : la fusion se demande à l'Assistant", file=sys.stderr)
        return CODE_REFUS
    try:
        projet = trouver_projet()
        return fusionner(projet, args.equipe, maintenant=args.maintenant, message=args.message,
                         auteur=agent)
    except _Refus as r:
        print(f"{NOM} fusionner : refusé — {r}", file=sys.stderr)
        return r.code
    except ErreurProjet as e:
        print(f"{NOM} fusionner : {e}", file=sys.stderr)
        return CODE_REFUS
