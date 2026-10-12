"""Le facteur : processus séparé, `cime facteur`.

Un tour fait, dans cet ordre : (1) les ordres `en_file`, par id ; (2) la livraison tmux ;
(3) les échéances. Le facteur est le seul qui lit et écrit les terminaux. Une exception dans
une étape est journalisée (`.orga/etat/facteur-erreurs.log`) et n'arrête pas la boucle.
"""
import contextlib
import fcntl
import os
import signal
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from cime.fondation import fermeture
from cime.fondation.registre import horodatage, ouvrir
from cime.signaux import commandes, echeances, livraison, ordres, relances, signalements_utilisateur
from cime.signaux.livraison import Memoire

PAS_FACTEUR = echeances.PAS_FACTEUR
VERSION = "3"


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def _etat(projet) -> Path:
    return Path(projet) / ".orga" / "etat"


def chemin_pid(projet) -> Path:
    return _etat(projet) / "facteur.pid"


def chemin_erreurs(projet) -> Path:
    return _etat(projet) / "facteur-erreurs.log"


class DejaEnCours(Exception):
    def __init__(self, pid):
        super().__init__(f"déjà en cours (pid {pid})")
        self.pid = pid


@contextlib.contextmanager
def verrou(projet):
    """Un seul facteur par projet : `facteur.pid` (pid) tenu par un `flock` exclusif."""
    chemin = chemin_pid(projet)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    f = open(chemin, "a+")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.seek(0)
        pid = f.read().strip() or "?"
        f.close()
        raise DejaEnCours(pid) from None
    try:
        f.seek(0)
        f.truncate()
        f.write(f"{os.getpid()}\n")
        f.flush()
        yield
    finally:
        with contextlib.suppress(OSError):
            chemin.unlink()
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def journaliser_erreur(projet, etape, erreur) -> None:
    try:
        with open(chemin_erreurs(projet), "a", encoding="utf-8") as f:
            trace = "".join(traceback.format_exception_only(type(erreur), erreur)).strip()
            f.write(f"{horodatage()} {etape} {trace}".replace("\n", " ") + "\n")
    except OSError:
        pass


def battre(projet) -> None:
    conn = ouvrir(projet)
    try:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO facteur (id, battement, version) VALUES (1, ?, ?)",
                (horodatage(), VERSION))
    finally:
        conn.close()


def _etape_ordres(projet, maintenant, memoire) -> int:
    if not memoire.demarre:
        ordres.clore_interrompus(projet)
    executes = 0
    for identifiant in ordres.ordres_en_file(projet):
        executes += bool(ordres._executer_en_file(projet, identifiant))
    from cime.signaux import vie
    vie.clore_signalements_arret(projet)   # le facteur est revenu, ses ordres sont traités
    return executes


def _etape_livraison(projet, maintenant, memoire) -> None:
    if not memoire.demarre:
        conn = ouvrir(projet)
        try:
            from cime.signaux import courrier
            courrier.fermer_expires_de_tous(conn, "cime")
        finally:
            conn.close()
        signalements_utilisateur.solder(projet)
    livraison.livrer_tout(projet, maintenant, memoire,
                          journaliser=lambda etape, e: journaliser_erreur(projet, etape, e))
    livraison.persister_occupation(projet, maintenant, memoire)


def _etape_echeances(projet, maintenant, memoire) -> None:
    relances.executer(projet, maintenant)
    conn = ouvrir(projet)
    try:
        signalements_utilisateur.clore(conn, projet, maintenant)
    finally:
        conn.close()


ETAPES = (("ordres", _etape_ordres), ("livraison", _etape_livraison),
          ("echeances", _etape_echeances))


def tour(projet, maintenant=None, memoire=None) -> dict:
    """Un passage. Renvoie {"ordres": n, "erreurs": [étapes en erreur]}."""
    memoire = memoire if memoire is not None else Memoire()
    maintenant = maintenant or _maintenant()
    bilan = {"ordres": 0, "erreurs": []}
    try:
        battre(projet)
    except Exception as e:
        journaliser_erreur(projet, "battement", e)
        bilan["erreurs"].append("battement")
    for nom, etape in ETAPES:
        try:
            resultat = etape(projet, maintenant, memoire)
            if nom == "ordres":
                bilan["ordres"] = resultat
        except Exception as e:
            journaliser_erreur(projet, nom, e)
            bilan["erreurs"].append(nom)
    memoire.demarre = True
    return bilan


def agents_actifs(projet) -> bool:
    """Au moins un agent du projet est actif : une session `<préfixe>-*` existe, ou un ordre
    attend."""
    from cime.fondation.projet import lire_manifeste
    if ordres.ordres_en_file(projet):
        return True
    prefixe = lire_manifeste(projet).prefixe + "-"
    return any(s.startswith(prefixe) for s in livraison.sessions_vivantes())


def boucler(projet, arret, memoire=None, pas=None) -> str:
    """Appelle `tour` toutes les `PAS_FACTEUR` secondes jusqu'à ce que `arret` soit posé, ou
    que plus aucun agent ne soit actif pendant `INACTIVITE_FACTEUR`, ou que le projet soit fermé
    (`ferme.json`, vérifié après chaque tour). Renvoie pourquoi elle sort : "arret", "inactivite"
    ou "ferme"."""
    memoire = memoire if memoire is not None else Memoire()
    pas = PAS_FACTEUR if pas is None else pas
    sans_agent_depuis = None
    motif = "arret"
    while not arret.is_set():
        tour(projet, memoire=memoire)
        try:
            actif = agents_actifs(projet)
        except Exception as e:
            journaliser_erreur(projet, "activite", e)
            actif = True
        if fermeture.est_ferme(projet):
            motif = "ferme"     # le projet est fermé (`cime fermer`) : rien à livrer ni à relancer
            break
        if actif:
            sans_agent_depuis = None
        else:
            sans_agent_depuis = sans_agent_depuis or _maintenant()
            if _maintenant() - sans_agent_depuis >= echeances.INACTIVITE_FACTEUR:
                motif = "inactivite"
                break
        arret.wait(pas)
    return motif


def _passer_la_main(projet) -> None:
    """Arrêt par signal, verrou libéré : si des agents sont actifs, le successeur est demandé
    (il lit le code de la version installée). Un doute sur l'activité compte comme actif."""
    from cime.signaux import vie
    try:
        actif = agents_actifs(projet)
    except Exception as e:
        journaliser_erreur(projet, "successeur", e)
        actif = True
    if actif:
        vie.demarrer_si_absent(projet)


def executer(args) -> int:
    """`cime facteur` : la boucle ; `--une-fois` : un tour. Un arrêt par signal avec des agents
    actifs passe la main à un successeur, une fois `facteur.pid` libéré."""
    def lancer(_):
        projet = commandes.projet_courant()
        motif = None
        try:
            with verrou(projet):
                if args.une_fois:
                    bilan = tour(projet)
                    print(f"{bilan['ordres']} ordre(s) exécuté(s)")
                    return 0
                arret = threading.Event()
                signal.signal(signal.SIGTERM, lambda *_: arret.set())
                signal.signal(signal.SIGINT, lambda *_: arret.set())
                motif = boucler(projet, arret)
        except DejaEnCours as e:
            print(f"facteur : {e}")
            return 0
        if motif == "arret":
            _passer_la_main(projet)
        return 0
    return commandes.lancer_commande("facteur", lancer, args)
