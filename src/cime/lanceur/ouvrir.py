"""`cime ouvrir` : ouvrir le lanceur dans le navigateur, et le démarrer s'il ne tourne pas.

Ordre : le lanceur répond-il déjà (sonde de `lanceur.port`) ? Sinon, l'agent launchd s'il est installé
(`launchctl kickstart`), et à défaut ou si launchctl échoue, un processus détaché (`cime lanceur`).
On attend qu'il réponde, puis on ouvre la page avec `open`. Réservé à l'utilisateur, comme `fermer` :
un agent ne démarre rien et n'ouvre aucun navigateur."""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from cime.fondation.fermeture import Echec, _exiger_utilisateur
from cime.lanceur.serveur import _sonde, port_voulu

LABEL = "cime.lanceur"
ATTENTE_S = 20.0
PAS_S = 0.2
PHRASES = {
    "deja": "Le lanceur tournait déjà.",
    "launchd": "Le lanceur a été démarré (agent launchd).",
    "detache": "Le lanceur a été démarré (processus détaché).",
}


def _run(*args, **kw):
    """`subprocess.run`, résolu à l'appel : un test le remplace (il ne lance jamais un vrai `launchctl` ni un vrai `open`)."""
    return subprocess.run(*args, **kw)


def _popen(*args, **kw):
    """`subprocess.Popen`, résolu à l'appel : un test le remplace (il ne lance jamais un vrai lanceur)."""
    return subprocess.Popen(*args, **kw)


def _port_en_marche(dossier: Path) -> int | None:
    """Le port écrit dans lanceur.port, si un lanceur y répond : un fichier périmé ne compte pas."""
    try:
        port = int((dossier / "lanceur.port").read_text().strip())
    except (OSError, ValueError):
        return None
    return port if _sonde(port, "/api/projets", (200,)) else None


def _demarrer(dossier: Path, agent: Path, uid: int, cime, lancer, lancer_detache) -> str:
    """Démarre le lanceur ; renvoie « launchd » ou « detache ». Lève OSError si aucun processus ne part."""
    if agent.exists():
        try:
            if lancer(["launchctl", "kickstart", f"gui/{uid}/{LABEL}"],
                      capture_output=True).returncode == 0:
                return "launchd"
        except OSError:
            pass                                  # launchctl absent : on passe au processus détaché
    exe = cime or shutil.which("cime") or os.path.abspath(sys.argv[0])
    dossier.mkdir(parents=True, exist_ok=True)
    with (dossier / "lanceur.log").open("ab") as journal:
        lancer_detache([exe, "lanceur"], stdin=subprocess.DEVNULL, stdout=journal,
                       stderr=subprocess.STDOUT, start_new_session=True)
    return "detache"


def _attendre(dossier: Path, dormir, delai_s: float) -> int | None:
    """Relit lanceur.port à chaque tour (le port peut changer) jusqu'à `delai_s` secondes."""
    essais = max(1, round(delai_s / PAS_S))
    for _ in range(essais):
        port = _port_en_marche(dossier)
        if port is not None:
            return port
        dormir(PAS_S)
    return _port_en_marche(dossier)


def _erreur(message: str) -> dict:
    return {"resultat": "erreur", "message": message}


def ouvrir_lanceur(*, dossier=None, agent=None, url_seule=False, uid=None, cime=None,
                   lancer=None, lancer_detache=None,
                   dormir=time.sleep, delai_s=ATTENTE_S) -> dict:
    """Renvoie `{"resultat": "ok", "url", "port", "demarre", "phrases"}` ou `{"resultat": "erreur",
    "message", …}`. Ne lève pas. Les effets externes (launchctl, open, processus, attente) sont
    injectables pour les tests."""
    lancer = lancer or _run
    lancer_detache = lancer_detache or _popen
    dossier = Path(dossier) if dossier is not None else Path.home() / ".cime"
    agent = Path(agent) if agent is not None else Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    uid = os.getuid() if uid is None else uid
    habituel = port_voulu(dossier)

    port = _port_en_marche(dossier)
    if port is not None:
        demarre = "deja"
    else:
        try:
            demarre = _demarrer(dossier, agent, uid, cime, lancer, lancer_detache)
        except OSError as e:
            return _erreur(f"Le lanceur n'a pas pu être démarré ({e}).")
        port = _attendre(dossier, dormir, delai_s)
        if port is None:
            return _erreur(f"Le lanceur ne répond pas après {delai_s:g} s. Regarde ~/.cime/lanceur.log.")

    url = f"http://127.0.0.1:{port}/"
    phrases = [PHRASES[demarre]]
    if port != habituel:
        phrases.append(f"Le port habituel ({habituel}) était pris : le lanceur est sur le port {port}.")
    if url_seule:
        return {"resultat": "ok", "url": url, "port": port, "demarre": demarre, "phrases": [url]}
    try:
        ouvert = lancer(["open", url], capture_output=True).returncode == 0
    except OSError:
        ouvert = False
    if not ouvert:
        return {"resultat": "erreur", "url": url, "port": port, "demarre": demarre,
                "message": "\n".join(phrases + [f"Ouvre {url} dans ton navigateur."])}
    return {"resultat": "ok", "url": url, "port": port, "demarre": demarre, "phrases": phrases}


def _sortir(donnees: dict, en_json: bool) -> int:
    phrases = donnees.pop("phrases", None)
    ok = donnees["resultat"] == "ok"
    if en_json:
        print(json.dumps(donnees, ensure_ascii=False), flush=True)
    elif ok:
        print("\n".join(phrases), flush=True)
    else:
        print(donnees["message"], file=sys.stderr, flush=True)
    return 0 if ok else 1


def executer(args) -> int:
    en_json = getattr(args, "sortie_json", False)
    try:
        _exiger_utilisateur("ouvrir")
    except Echec as e:
        return _sortir(_erreur(str(e)), en_json)
    return _sortir(ouvrir_lanceur(url_seule=args.url), en_json)
