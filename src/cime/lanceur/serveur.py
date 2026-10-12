"""Serveur du lanceur (127.0.0.1 uniquement). Il crée un projet (`cime init`), ouvre la page de
son hôte (`cime servir`), ferme et rouvre les projets (`cime fermer`, `cime rouvrir`), liste les
conversations d'un projet (`cime conversations`), installe Cime dans un dossier existant
(`cime init --apercu`, `cime init`), et tient la mémoire des projets connus dans `<dossier>/projets.json`."""
from __future__ import annotations

import asyncio
import contextlib
import fcntl
import hashlib
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import tomllib
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from cime.hote.securite import SecuriteLocale
from .fenetre import ouvrir_fenetre

ADRESSE = "127.0.0.1"
PORT_PAR_DEFAUT = 47615   # hors de la plage éphémère de macOS (49152–65535) : on le met en favori
ARRET_MAX_S = 3
PAGE = Path(__file__).resolve().parent / "page" / "index.html"
PAGE_ABSENTE = (
    "<!doctype html><meta charset='utf-8'><title>Lanceur</title>"
    "<p>La page du lanceur n'est pas encore installée.</p>"
)
MOTIF = re.compile(r"[a-z0-9-]+")
SESSION = re.compile(r"[A-Za-z0-9_-]{1,80}")

# Délais (secondes) : variables de module pour que les tests les raccourcissent.
DELAI_INIT_S = 120
DELAI_FERMER_S = 90
DELAI_ROUVRIR_S = 120
DELAI_CONVERSATIONS_S = 30
DELAI_APERCU_S = 30
MAX_CONVERSATIONS = 30
SORTIE_MAX = 2000   # la sortie brute d'une commande `cime` en erreur, gardée à part (jamais affichée)
ATTENTE_HOTE_S = 10
SONDAGE_S = 0.1
SONDE_S = 1


# ── Le seul endroit où l'on lance un processus ──────────────────────────────────────────

def executer(argv, *, env, cwd=None, delai=None, journal_sortie=None):
    """Lance `argv`.
    - `journal_sortie` None : attend la fin (au plus `delai` s) et renvoie
      `(code, sortie)` ; stdout et stderr fusionnés ; `(None, sortie)` si le délai est dépassé.
    - sinon : lance **détaché** (nouvelle session), sortie vers ce fichier, renvoie le `Popen`."""
    if journal_sortie is not None:
        journal_sortie = Path(journal_sortie)
        journal_sortie.parent.mkdir(parents=True, exist_ok=True)
        with journal_sortie.open("ab") as f:
            return subprocess.Popen(
                argv, env=env, cwd=cwd, stdin=subprocess.DEVNULL,
                stdout=f, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        r = subprocess.run(
            argv, env=env, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, timeout=delai)
        return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace")
    except subprocess.TimeoutExpired as e:
        sortie = ((e.stdout or b"") + (e.stderr or b"")).decode("utf-8", "replace")
        return None, sortie


# ── Mémoire, journal ────────────────────────────────────────────────────────────────────

def _manifeste(chemin: Path) -> dict | None:
    try:
        with (chemin / ".orga" / "projet.toml").open("rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return None


def _reglages_du(dossier: Path) -> dict:
    try:
        v = json.loads((dossier / "lanceur.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return v if isinstance(v, dict) else {}


def port_voulu(dossier: Path | None = None) -> int:
    """Le port que le lanceur veut : la clé `port` de lanceur.json (entier 1–65535), sinon le défaut.
    Une valeur illisible ou hors plage est ignorée, sans erreur."""
    dossier = Path(dossier) if dossier is not None else Path.home() / ".cime"
    p = _reglages_du(dossier).get("port")
    if type(p) is int and 1 <= p <= 65535:       # `type is int` : `true` n'est pas un port
        return p
    return PORT_PAR_DEFAUT


def garder_port(port: int, dossier: Path | None = None) -> None:
    """Écrit la clé `port` dans lanceur.json ; les autres clés restent (écriture atomique)."""
    dossier = Path(dossier) if dossier is not None else Path.home() / ".cime"
    dossier.mkdir(parents=True, exist_ok=True)
    reglages = _reglages_du(dossier)
    reglages["port"] = port
    tmp = dossier / "lanceur.json.tmp"
    tmp.write_text(json.dumps(reglages, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, dossier / "lanceur.json")


class Contexte:
    def __init__(self, dossier: Path, cime: list[str], modele: str | None, fenetre=None) -> None:
        self.dossier = dossier
        self.cime = cime
        self.modele = modele
        self.port = 0
        self.verrou = threading.Lock()
        # défaut résolu à l'appel (les tests remplacent `ouvrir_fenetre` du module)
        self.fenetre = fenetre or (lambda session: ouvrir_fenetre(dossier, session))

    @property
    def reglages(self) -> Path:
        return self.dossier / "lanceur.json"

    def _lire_reglages(self) -> dict:
        return _reglages_du(self.dossier)

    def utilisateur(self) -> str | None:
        v = self._lire_reglages().get("utilisateur")
        return v if isinstance(v, str) else None

    def garder_utilisateur(self, valeur: str) -> None:
        with self.verrou:
            reglages = self._lire_reglages()     # fusion : `terminal` et les autres clés restent
            reglages["utilisateur"] = valeur
            tmp = self.reglages.with_name("lanceur.json.tmp")
            tmp.write_text(json.dumps(reglages, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.reglages)

    @property
    def memoire(self) -> Path:
        return self.dossier / "projets.json"

    def lire(self) -> list[dict]:
        try:
            return json.loads(self.memoire.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []

    def _ecrire(self, projets: list[dict]) -> None:
        tmp = self.memoire.with_name("projets.json.tmp")
        tmp.write_text(json.dumps(projets, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.memoire)

    def ajouter(self, chemin: Path, nom: str) -> None:
        with self.verrou:
            projets = self.lire()
            if any(p["chemin"] == str(chemin) for p in projets):
                return
            projets.append({"chemin": str(chemin), "nom": nom})
            self._ecrire(projets)

    def oublier(self, chemin: Path) -> bool:
        with self.verrou:
            projets = self.lire()
            reste = [p for p in projets if p["chemin"] != str(chemin)]
            if len(reste) == len(projets):
                return False
            self._ecrire(reste)
            return True

    def journaliser(self, action: str, cible: str, resultat: str, message: str) -> None:
        ligne = {
            "heure": datetime.now(timezone.utc).isoformat(),
            "auteur": "utilisateur", "action": action, "cible": cible,
            "resultat": resultat, "message": message,
        }
        with self.verrou, (self.dossier / "journal.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(ligne, ensure_ascii=False) + "\n")

    def env(self, **ajouts) -> dict:
        env = {k: v for k, v in os.environ.items() if k not in ("CIME_PROJET", "CIME_AGENT")}
        env.update(ajouts)
        return env


# ── Sondes ──────────────────────────────────────────────────────────────────────────────

def _sonde(port: int, chemin: str, acceptes: tuple[int, ...]) -> bool:
    req = urllib.request.Request(
        f"http://{ADRESSE}:{port}{chemin}", headers={"Host": f"{ADRESSE}:{port}"})
    try:
        with urllib.request.urlopen(req, timeout=SONDE_S) as r:
            return r.status in acceptes
    except urllib.error.HTTPError as e:
        return e.code in acceptes
    except Exception:
        return False


def _port_libre(port: int) -> bool:
    """Vrai si 127.0.0.1:<port> peut être lié, comme le fera uvicorn (SO_REUSEADDR). Le port 0 l'est."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((ADRESSE, port))
        except OSError:
            return False
    return True


def _port_hote(chemin: Path) -> int | None:
    try:
        p = int((chemin / ".orga" / "etat" / "hote.port").read_text().strip())
    except (OSError, ValueError):
        return None
    return p if _sonde(p, "/api/etat", (200, 503)) else None


# ── Validation ──────────────────────────────────────────────────────────────────────────

class Refus(Exception):
    def __init__(self, message: str, statut: int = 400) -> None:
        super().__init__(message)
        self.statut = statut


async def _corps(request) -> dict:
    try:
        corps = await request.json()
    except Exception:
        raise Refus("corps JSON invalide") from None
    if not isinstance(corps, dict):
        raise Refus("le corps doit être un objet JSON")
    return corps


def _texte(corps: dict, cle: str, obligatoire: bool = True) -> str | None:
    v = corps.get(cle)
    if v is None and not obligatoire:
        return None
    if not isinstance(v, str) or not v:
        raise Refus(f"`{cle}` manquant ou invalide")
    return v


def _absolu(valeur: str, cle: str) -> Path:
    p = Path(valeur)
    if not p.is_absolute():
        raise Refus(f"`{cle}` doit être un chemin absolu")
    return p.resolve()


def _projet_connu(corps: dict) -> tuple[Path, dict]:
    chemin = _absolu(_texte(corps, "chemin"), "chemin")
    manifeste = _manifeste(chemin)
    if manifeste is None:
        raise Refus("pas de .orga/projet.toml lisible dans ce dossier")
    return chemin, manifeste


def _nom_de(manifeste: dict, chemin: Path) -> str:
    nom = manifeste.get("nom")
    return nom if isinstance(nom, str) and nom else chemin.name


# ── Actions (synchrones, exécutées hors de la boucle) ───────────────────────────────────

def _utilisateur(corps: dict) -> str:
    v = corps.get("utilisateur")
    if not isinstance(v, str) or not v.strip():
        raise Refus("`utilisateur` manquant ou vide")
    v = v.strip()
    if len(v) > 60 or any(unicodedata.category(c) == "Cc" for c in v):
        raise Refus("`utilisateur` : 60 caractères au plus, sans caractère de contrôle")
    return v


def _nouveau(ctx: Contexte, corps: dict):
    nom = _texte(corps, "nom")
    prefixe = _texte(corps, "prefixe", obligatoire=False)
    if not MOTIF.fullmatch(nom):
        raise Refus("`nom` doit correspondre à [a-z0-9-]+")
    if prefixe is not None and not MOTIF.fullmatch(prefixe):
        raise Refus("`prefixe` doit correspondre à [a-z0-9-]+")
    parent = _absolu(_texte(corps, "dossier_parent"), "dossier_parent")
    if not parent.is_dir():
        raise Refus("`dossier_parent` n'existe pas")
    utilisateur = _utilisateur(corps)
    ctx.garder_utilisateur(utilisateur)
    cible = parent / nom
    chemin_cible = str(cible)
    if cible.exists() and (not cible.is_dir() or any(cible.iterdir())):
        raise Refus(f"{cible} existe déjà et n'est pas vide", 409)
    argv = ctx.cime + ["init", str(cible), "--utilisateur", utilisateur, "--nom-projet", nom, "--lancer"]
    if prefixe:
        argv += ["--prefixe", prefixe]
    if ctx.modele:
        argv += ["--modele", ctx.modele]
    code, sortie = executer(argv, env=ctx.env(), delai=DELAI_INIT_S)
    if code is None:
        return 200, {"resultat": "erreur", "code": None,
                     "message": f"cime init : délai de {DELAI_INIT_S} s dépassé\n{sortie}"}, chemin_cible
    if code not in (0, 3):
        return 200, {"resultat": "erreur", "code": code, "message": sortie}, chemin_cible
    manifeste = _manifeste(cible)
    if manifeste is None:
        return 200, {"resultat": "erreur", "code": code,
                     "message": f"cime init terminé sans .orga/projet.toml lisible\n{sortie}"}, chemin_cible
    reel = manifeste.get("prefixe") or prefixe or nom
    ctx.ajouter(cible.resolve(), _nom_de(manifeste, cible))
    return 200, {
        "resultat": "ok", "chemin": str(cible.resolve()), "prefixe": reel,
        "a_approuver": code == 3,
        "commandes": [f"tmux attach -t {reel}-assistant"], "message": sortie,
    }, chemin_cible


@contextlib.contextmanager
def _verrou_projet(ctx: Contexte, chemin: Path):
    """Un seul `ouvrir` à la fois par projet : deux clics simultanés ne lancent qu'un
    `servir`. Verrou fichier dans le dossier du lanceur, jamais dans le projet."""
    dossier = ctx.dossier / "verrous"
    dossier.mkdir(parents=True, exist_ok=True)
    nom = hashlib.sha256(str(chemin).encode()).hexdigest()[:16]
    with open(dossier / f"ouvrir-{nom}.lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _ouvrir(ctx: Contexte, corps: dict):
    chemin, manifeste = _projet_connu(corps)
    with _verrou_projet(ctx, chemin):
        return _ouvrir_verrouille(ctx, chemin, manifeste)


def _ouvrir_verrouille(ctx: Contexte, chemin: Path, manifeste: dict):
    cible = str(chemin)
    ctx.ajouter(chemin, _nom_de(manifeste, chemin))
    p = _port_hote(chemin)
    if p is not None:
        return 200, {"resultat": "ok", "url": f"http://{ADRESSE}:{p}/", "lance": False}, cible
    prefixe = str(manifeste.get("prefixe") or _nom_de(manifeste, chemin))
    journal = ctx.dossier / "journaux" / f"hote-{re.sub(r'[^A-Za-z0-9_-]', '_', prefixe)}.log"
    proc = executer(ctx.cime + ["servir"], env=ctx.env(CIME_PROJET=str(chemin)),
                    cwd=chemin, journal_sortie=journal)
    fin = time.monotonic() + ATTENTE_HOTE_S
    while True:
        p = _port_hote(chemin)
        if p is not None:
            return 200, {"resultat": "ok", "url": f"http://{ADRESSE}:{p}/", "lance": True}, cible
        if time.monotonic() >= fin or proc.poll() is not None:
            break  # délai dépassé, ou l'hôte est déjà mort : inutile d'attendre
        time.sleep(SONDAGE_S)
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGKILL)
    with contextlib.suppress(Exception):
        proc.wait(timeout=2)
    try:
        fin_log = "\n".join(journal.read_text(errors="replace").splitlines()[-10:])
    except OSError:
        fin_log = ""
    cause = (f"hôte arrêté (code {proc.returncode})" if proc.returncode not in (None, -signal.SIGKILL)
             else f"hôte non démarré en {ATTENTE_HOTE_S} s")
    return 200, {"resultat": "erreur", "message": f"{cause} : {fin_log}"}, cible


def _ajouter(ctx: Contexte, corps: dict):
    chemin = _absolu(_texte(corps, "chemin"), "chemin")
    # un manifeste présent mais illisible n'est pas « Cime absent » : `init` pourrait l'écraser
    if _manifeste(chemin) is None and chemin.is_dir() and not (chemin / ".orga" / "projet.toml").exists():
        return _proposer_installation(ctx, chemin)
    chemin, manifeste = _projet_connu(corps)
    ctx.ajouter(chemin, _nom_de(manifeste, chemin))
    return 200, {"resultat": "ok", "chemin": str(chemin)}, str(chemin)


APERCU_CLES = ("nom", "commit", "cree", "complete", "garde")


def _proposer_installation(ctx: Contexte, chemin: Path):
    """Dossier sans manifeste : l'aperçu de `cime init --apercu` (il ne crée rien), à montrer à l'utilisateur."""
    code, sortie = executer(ctx.cime + ["init", "--apercu", str(chemin), "--json"],
                            env=ctx.env(), delai=DELAI_APERCU_S)
    objet = _objet_json(sortie)
    if code == 0 and objet is not None and objet.get("resultat") != "erreur":
        apercu = {cle: objet.get(cle) for cle in APERCU_CLES}
        return 409, {"resultat": "refuse", "installable": True, "apercu": apercu,
                     "message": "Cime n'est pas installé dans ce dossier."}, str(chemin)
    message = (_delai_depasse(DELAI_APERCU_S) if code is None
               else _message_erreur(objet, sortie, "L'aperçu de l'installation est indisponible."))
    return 409, {"resultat": "refuse", "installable": False, "message": message,
                 "sortie": sortie[:SORTIE_MAX]}, str(chemin)


def _installer(ctx: Contexte, corps: dict):
    chemin = _absolu(_texte(corps, "chemin"), "chemin")
    if not chemin.is_dir():
        raise Refus("`chemin` doit être un dossier existant")
    if _manifeste(chemin) is not None:
        raise Refus("Cime est déjà installé ici", 409)
    if (chemin / ".orga" / "projet.toml").exists():
        raise Refus("`.orga/projet.toml` existe mais n'est pas lisible : le réparer à la main, `init` ne le remplace pas", 409)
    nom = _texte(corps, "nom", obligatoire=False)
    prefixe = _texte(corps, "prefixe", obligatoire=False)
    if nom is not None and not MOTIF.fullmatch(nom):
        raise Refus("`nom` doit correspondre à [a-z0-9-]+")
    if prefixe is not None and not MOTIF.fullmatch(prefixe):
        raise Refus("`prefixe` doit correspondre à [a-z0-9-]+")
    if corps.get("utilisateur") is not None:
        utilisateur = _utilisateur(corps)
        ctx.garder_utilisateur(utilisateur)
    else:
        utilisateur = ctx.utilisateur()
        if not utilisateur:
            raise Refus("`utilisateur` manquant")
    argv = ctx.cime + ["init", str(chemin), "--utilisateur", utilisateur, "--lancer"]
    if nom:
        argv += ["--nom-projet", nom]
    if prefixe:
        argv += ["--prefixe", prefixe]
    if ctx.modele:
        argv += ["--modele", ctx.modele]
    cible = str(chemin)
    code, sortie = executer(argv, env=ctx.env(), delai=DELAI_INIT_S)
    if code is None:
        return 200, {"resultat": "erreur", "code": None,
                     "message": f"cime init : délai de {DELAI_INIT_S} s dépassé\n{sortie}"}, cible
    if code not in (0, 3):
        return 200, {"resultat": "erreur", "code": code, "message": sortie}, cible
    manifeste = _manifeste(chemin)
    if manifeste is None:
        return 200, {"resultat": "erreur", "code": code,
                     "message": f"cime init terminé sans .orga/projet.toml lisible\n{sortie}"}, cible
    reel = str(manifeste.get("prefixe") or prefixe or _nom_de(manifeste, chemin))
    ctx.ajouter(chemin, _nom_de(manifeste, chemin))
    fenetre = bool(ctx.fenetre(f"{reel}-assistant"))
    return 200, {
        "resultat": "ok", "chemin": str(chemin), "prefixe": reel, "a_approuver": code == 3,
        "fenetre": fenetre, "commandes": [f"tmux attach -t {reel}-assistant"], "message": sortie,
    }, cible


def _oublier(ctx: Contexte, corps: dict):
    chemin = _absolu(_texte(corps, "chemin"), "chemin")
    if not ctx.oublier(chemin):
        raise Refus("projet absent de la mémoire", 404)
    return 200, {"resultat": "ok", "chemin": str(chemin)}, str(chemin)


def _fermer(ctx: Contexte, corps: dict):
    chemin, _ = _projet_connu(corps)
    forcer = corps.get("forcer", False)
    if not isinstance(forcer, bool):
        raise Refus("`forcer` doit être un booléen")
    argv = ctx.cime + ["fermer", str(chemin), "--json"] + (["--forcer"] if forcer else [])
    code, sortie = executer(argv, env=ctx.env(), delai=DELAI_FERMER_S)
    cible = str(chemin)
    objet = _objet_json(sortie)
    # le refus se reconnaît à son résultat, quel que soit le code de sortie
    if objet is not None and objet.get("resultat") == "refuse":
        reponse = {"resultat": "refuse", "occupes": objet.get("occupes", []), "message": objet.get("message", "")}
        return 409, _recopier(objet, reponse), cible
    if code is None:
        return 200, _erreur(None, _delai_depasse(DELAI_FERMER_S), sortie), cible
    if code == 0 and objet is not None and objet.get("resultat") == "ok":
        reponse = {"resultat": "ok", "conversations": objet.get("conversations", []),
                   "taches_en_cours": objet.get("taches_en_cours", [])}
        return 200, _recopier(objet, reponse), cible
    return 200, _erreur(code, _message_erreur(objet, sortie, "La fermeture a échoué."), sortie), cible


def _rouvrir(ctx: Contexte, corps: dict):
    chemin, manifeste = _projet_connu(corps)
    session = corps.get("session")
    if session is not None and (not isinstance(session, str) or not SESSION.fullmatch(session)):
        raise Refus("`session` doit correspondre à [A-Za-z0-9_-]{1,80}")
    cible = str(chemin)
    argv = ctx.cime + ["rouvrir", cible, "--json"] + (["--session", session] if session is not None else [])
    code, sortie = executer(argv, env=ctx.env(), delai=DELAI_ROUVRIR_S)
    if code is None:
        return 200, _erreur(None, _delai_depasse(DELAI_ROUVRIR_S), sortie), cible
    objet = _objet_json(sortie)
    if code not in (0, 3) or objet is None or objet.get("resultat") != "ok":
        return 200, _erreur(code, _message_erreur(objet, sortie, "La réouverture a échoué."), sortie), cible
    # l'Assistant est revenu : l'hôte passe après, et un échec ici ne change pas le résultat
    with _verrou_projet(ctx, chemin):
        _, ouverture, _ = _ouvrir_verrouille(ctx, chemin, manifeste)
    url, avertissement = (ouverture["url"], None) if ouverture["resultat"] == "ok" else (None, ouverture["message"])
    assistant = objet.get("assistant")
    fenetre = isinstance(assistant, str) and bool(ctx.fenetre(assistant))
    commandes = [f"tmux attach -t {assistant}"] if isinstance(assistant, str) else []
    reponse = {
        "resultat": "ok", "url": url, "assistant": assistant,
        "coordinateurs": objet.get("coordinateurs", []), "a_approuver": bool(objet.get("a_approuver")),
        "taches_en_cours": objet.get("taches_en_cours", []), "fenetre": fenetre, "commandes": commandes,
    }
    if avertissement is not None:
        reponse["avertissement"] = avertissement
    if not fenetre:
        reponse["message"] = f"Aucune fenêtre ouverte : lancer `{' '.join(commandes)}` dans un terminal."
    return 200, _recopier(objet, reponse), cible


def _objet_json(sortie: str) -> dict | None:
    """La dernière ligne de `sortie` qui est un objet JSON (stdout et stderr sont fusionnés)."""
    for ligne in reversed(sortie.splitlines()):
        try:
            v = json.loads(ligne)
        except ValueError:
            continue
        if isinstance(v, dict):
            return v
    return None


def _delai_depasse(delai) -> str:
    return f"La commande a pris plus de {delai} s (elle est peut-être encore en cours)."


def _message_erreur(objet: dict | None, sortie: str, generique: str) -> str:
    """Le `message` d'une erreur de `cime`, en phrase. Jamais la sortie brute : elle part dans `sortie`
    (et au journal), pas dans l'affichage. `sortie` ne sert qu'à l'appelant, qui la range dans la réponse."""
    if objet is not None and objet.get("resultat") == "erreur":
        message = objet.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return generique


def _erreur(code, message: str, sortie: str) -> dict:
    return {"resultat": "erreur", "code": code, "message": message, "sortie": sortie[:SORTIE_MAX]}


def _recopier(objet: dict, reponse: dict) -> dict:
    """Recopie tel quel les champs que `cime` peut porter en plus (`conversation`, `equipes`, `echecs`)."""
    for cle in ("conversation", "equipes", "echecs"):
        if cle in objet:
            reponse[cle] = objet[cle]
    return reponse


# ── Conversations (lecture seule, pas de journal) ───────────────────────────────────────

def _session_fermeture(chemin: Path) -> str | None:
    """La session de l'Assistant notée à la fermeture (`ferme.json`), ou None."""
    try:
        conversations = json.loads((chemin / ".orga" / "etat" / "ferme.json").read_text(encoding="utf-8"))["conversations"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(conversations, list):
        return None
    for c in conversations:
        if isinstance(c, dict) and c.get("agent") == "assistant" and isinstance(c.get("session"), str):
            return c["session"]
    return None


def _lister_conversations(ctx: Contexte, chemin: Path) -> dict:
    code, sortie = executer(ctx.cime + ["conversations", str(chemin), "--json"],
                            env=ctx.env(), delai=DELAI_CONVERSATIONS_S)
    if code is None:
        return _erreur(None, _delai_depasse(DELAI_CONVERSATIONS_S), sortie)
    objet = _objet_json(sortie)
    conversations = objet.get("conversations") if objet is not None else None
    if code != 0 or not isinstance(conversations, list):
        return _erreur(code, _message_erreur(objet, sortie, "La liste des conversations est indisponible."), sortie)
    return {"resultat": "ok", "conversations": conversations[:MAX_CONVERSATIONS],
            "fermeture": _session_fermeture(chemin)}


# ── État ouvert/fermé (lecture seule) ───────────────────────────────────────────────────

def _agents_actifs(chemin: Path) -> bool:
    """Même critère que le surveillant. Toute exception vaut « pas actifs »."""
    try:
        from cime.signaux import facteur
        return bool(facteur.agents_actifs(chemin))
    except Exception:
        return False


def _conversations(chemin: Path) -> int | None:
    try:
        conversations = json.loads((chemin / ".orga" / "etat" / "ferme.json").read_text(encoding="utf-8"))["conversations"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return len(conversations) if isinstance(conversations, list) else None


def _etat_projets(ctx: Contexte) -> list[dict]:
    projets = []
    for p in ctx.lire():
        chemin = Path(p["chemin"])
        ouvert = _port_hote(chemin) is not None or _agents_actifs(chemin)
        projets.append({**p, "etat": "ouvert" if ouvert else "ferme", "conversations": _conversations(chemin)})
    return projets


# ── Application ─────────────────────────────────────────────────────────────────────────

def creer_app(ctx: Contexte) -> Starlette:
    def action(nom: str, fonction):
        async def route(request):
            cible = ""
            try:
                corps = await _corps(request)
                cible = str(corps.get("chemin") or corps.get("dossier_parent") or "")
                statut, reponse, cible = await asyncio.to_thread(fonction, ctx, corps)
            except Refus as r:
                statut, reponse = r.statut, {"resultat": "refuse", "message": str(r)}
            except Exception as e:
                statut, reponse = 500, {"resultat": "erreur", "message": f"{type(e).__name__}: {e}"}
            # le journal est écrit avant la réponse, succès ou non ; la sortie brute y suit le message, sur une ligne
            message = str(reponse.get("message", ""))
            if reponse.get("sortie"):
                message += " | sortie : " + " ".join(reponse["sortie"].split())
            await asyncio.to_thread(ctx.journaliser, nom, cible, reponse["resultat"], message)
            return JSONResponse(reponse, status_code=statut)
        return route

    async def page(request):
        if PAGE.is_file():
            return HTMLResponse(PAGE.read_text(encoding="utf-8"))
        return HTMLResponse(PAGE_ABSENTE)

    async def projets(request):
        return JSONResponse({"projets": await asyncio.to_thread(_etat_projets, ctx), "utilisateur": ctx.utilisateur()})

    async def conversations(request):
        # GET : pas de journal (on ne change rien)
        try:
            chemin, _ = _projet_connu({"chemin": request.query_params.get("chemin")})
            reponse = await asyncio.to_thread(_lister_conversations, ctx, chemin)
        except Refus as r:
            return JSONResponse({"resultat": "refuse", "message": str(r)}, status_code=r.statut)
        return JSONResponse(reponse)

    app = Starlette(
        routes=[
            Route("/", page),
            Route("/api/projets", projets),
            Route("/api/projets/conversations", conversations, methods=["GET"]),
            Route("/api/projets/nouveau", action("nouveau", _nouveau), methods=["POST"]),
            Route("/api/projets/ouvrir", action("ouvrir", _ouvrir), methods=["POST"]),
            Route("/api/projets/ajouter", action("ajouter", _ajouter), methods=["POST"]),
            Route("/api/projets/installer", action("installer", _installer), methods=["POST"]),
            Route("/api/projets/oublier", action("oublier", _oublier), methods=["POST"]),
            Route("/api/projets/fermer", action("fermer", _fermer), methods=["POST"]),
            Route("/api/projets/rouvrir", action("rouvrir", _rouvrir), methods=["POST"]),
        ],
        middleware=[Middleware(SecuriteLocale, port=lambda: ctx.port)],
    )
    app.state.contexte = ctx
    return app


def servir(
    port: int = 0,
    modele: str | None = None,
    *,
    dossier: Path | None = None,
    cime: list[str] | None = None,
    arret: threading.Event | None = None,
    surveillant: bool = True,
    fenetre=None,
) -> None:
    """Bloquant. `dossier`, `cime`, `arret`, `surveillant` et `fenetre` ne servent qu'aux tests."""
    dossier = Path(dossier) if dossier is not None else Path.home() / ".cime"
    dossier.mkdir(parents=True, exist_ok=True)
    fichier = dossier / "lanceur.port"
    if fichier.exists():
        try:
            ancien = int(fichier.read_text().strip())
        except ValueError:
            ancien = None
        if ancien is not None and _sonde(ancien, "/api/projets", (200,)):
            sys.exit(f"Un lanceur tourne déjà sur le port {ancien}")

    demande = port
    if port and not _port_libre(port):     # pris par autre chose : un port libre, et on le dit
        port = 0

    ctx = Contexte(dossier, list(cime) if cime else ["cime"], modele, fenetre)
    app = creer_app(ctx)
    serveur = uvicorn.Server(uvicorn.Config(
        app, host=ADRESSE, port=port, log_level="warning", timeout_graceful_shutdown=ARRET_MAX_S))
    ecrit = False
    startup = serveur.startup

    async def startup_puis_fichier(sockets=None):
        nonlocal ecrit
        await startup(sockets=sockets)
        if serveur.started:
            ctx.port = serveur.servers[0].sockets[0].getsockname()[1]
            if demande and ctx.port != demande:
                print(f"Le port {demande} est pris : le lanceur écoute sur le port {ctx.port}.",
                      file=sys.stderr, flush=True)
            fichier.write_text(str(ctx.port))
            ecrit = True
            if arret is not None:
                asyncio.get_running_loop().create_task(_surveiller(arret, serveur))

    shutdown = serveur.shutdown

    async def shutdown_puis_effacer(sockets=None):
        # Sur SIGTERM uvicorn relève le signal après serve() : on efface dès la fin de l'arrêt.
        try:
            await shutdown(sockets=sockets)
        finally:
            _effacer()

    def _effacer():
        if ecrit:
            with contextlib.suppress(FileNotFoundError):
                fichier.unlink()

    serveur.startup = startup_puis_fichier
    serveur.shutdown = shutdown_puis_effacer
    fin_surveillant = threading.Event()
    if surveillant and not os.environ.get("CIME_SANS_SURVEILLANT"):   # le surveillant du facteur de chaque projet
        from .surveillant import Surveillant
        threading.Thread(target=Surveillant(dossier).boucler, args=(fin_surveillant,),
                         daemon=True, name="surveillant").start()
    try:
        serveur.run()
    finally:
        fin_surveillant.set()
        _effacer()


async def _surveiller(arret: threading.Event, serveur: uvicorn.Server) -> None:
    while not arret.is_set():
        await asyncio.sleep(0.05)
    serveur.should_exit = True
