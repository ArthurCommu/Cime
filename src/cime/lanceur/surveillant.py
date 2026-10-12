"""Le surveillant de la machine.

Un outil de Cime, par machine, dans le lanceur : une boucle qui lit `~/.cime/projets.json` et,
pour chaque projet dont des agents sont actifs et dont le verrou de `facteur.pid` est libre (aucun
facteur ne tourne, même si son battement est encore frais), relance `cime facteur`
(`vie.demarrer_si_absent`) — 3 essais espacés de 10 s. Après 3 échecs,
une notification macOS à l'utilisateur (par `hote/notifications.py` : le surveillant n'écrit lui-même aucune commande de notification).
Journal : `~/.cime/surveillant.log`. Le surveillant tourne hors des agents.
"""
import asyncio
import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

PAS = 5.0                  # s entre deux passes (une lecture du verrou et une de tmux)
ESSAIS = 3
ESPACE = 10.0              # s entre deux essais (et attente du premier battement)
REPRISE_APRES_ABANDON = 300.0   # s : après 3 échecs, on ne réessaie qu'au bout de ce temps
PEREMPTION_S = 30          # même seuil que `commandes.facteur_arrete`


def battement_frais(projet: Path, maintenant: datetime | None = None) -> bool:
    """Le battement du facteur date de moins de 30 s (lecture seule du registre)."""
    chemin = Path(projet) / ".orga" / "etat" / "registre.sqlite"
    if not chemin.exists():
        return False
    try:
        conn = sqlite3.connect(f"file:{chemin}?mode=ro", uri=True, timeout=2)
        try:
            ligne = conn.execute("SELECT battement FROM facteur WHERE id = 1").fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return False
    if ligne is None:
        return False
    lu = datetime.strptime(ligne[0], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    return ((maintenant or datetime.now(timezone.utc)) - lu) <= timedelta(seconds=PEREMPTION_S)


def _agents_actifs(projet: Path) -> bool:
    from cime.signaux import facteur
    return facteur.agents_actifs(projet)


def _demarrer(projet: Path) -> bool:
    from cime.signaux import vie
    return vie.demarrer_si_absent(projet)


def _vivant(projet: Path) -> bool:
    from cime.signaux import vie
    return vie.facteur_vivant(projet)


def _notifier_mac(titre: str, texte: str) -> None:
    """La notification macOS passe par le notifieur de l'hôte (liste blanche des gardes)."""
    if os.environ.get("CIME_NOTIFICATIONS") == "0":   # sessions d'essai
        return
    from cime.hote.gardes import Gardes
    from cime.hote.notifications import NotifieurMac
    notifieur = NotifieurMac(Gardes("cime"))
    asyncio.run(notifieur.notifier(titre, texte))
    if notifieur.derniere_erreur:
        raise RuntimeError(notifieur.derniere_erreur)


class Surveillant:
    def __init__(self, dossier: Path, *, notifier=None, demarrer=None, agents_actifs=None,
                 frais=None, vivant=None, dormir=time.sleep, horloge=time.monotonic) -> None:
        self.dossier = Path(dossier)
        self.notifier = notifier or _notifier_mac
        self.demarrer = demarrer or _demarrer
        self.agents_actifs = agents_actifs or _agents_actifs
        self.frais = frais or battement_frais
        self.vivant = vivant or _vivant
        self.dormir = dormir
        self.horloge = horloge
        self.abandons: dict[str, float] = {}   # projet -> instant du dernier abandon (notifié)

    @property
    def journal(self) -> Path:
        return self.dossier / "surveillant.log"

    def ecrire(self, message: str) -> None:
        try:
            with self.journal.open("a", encoding="utf-8") as f:
                f.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")
        except OSError:
            pass

    def projets(self) -> list[dict]:
        try:
            donnees = json.loads((self.dossier / "projets.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [p for p in donnees if isinstance(p, dict) and isinstance(p.get("chemin"), str)]

    def passe(self) -> list[str]:
        """Une passe sur tous les projets connus ; renvoie les projets relancés avec succès."""
        relances = []
        for p in self.projets():
            chemin = Path(p["chemin"])
            nom = p.get("nom") or chemin.name
            try:
                if (chemin / ".orga" / "etat" / "ferme.json").exists():   # projet fermé : rien à relancer
                    continue
                if self.vivant(chemin):              # verrou tenu : un facteur tourne, il n'est pas doublé
                    self.abandons.pop(str(chemin), None)
                    continue
                if not (chemin / ".orga" / "etat" / "registre.sqlite").exists():
                    continue
                if not self.agents_actifs(chemin):
                    continue
                depuis = self.abandons.get(str(chemin))
                if depuis is not None and self.horloge() - depuis < REPRISE_APRES_ABANDON:
                    continue
                if self._relancer(chemin, nom):
                    relances.append(str(chemin))
            except Exception as e:   # un projet qui plante ne prive pas les autres
                self.ecrire(f"{nom} : erreur {type(e).__name__} : {e}")
        return relances

    def _relancer(self, chemin: Path, nom: str) -> bool:
        for essai in range(1, ESSAIS + 1):
            lance = self.demarrer(chemin)
            self.ecrire(f"{nom} : battement périmé, agents actifs — essai {essai}/{ESSAIS} "
                        f"({'facteur lancé' if lance else 'rien lancé'})")
            self.dormir(ESPACE)
            if self.frais(chemin):
                self.ecrire(f"{nom} : facteur reparti")
                self.abandons.pop(str(chemin), None)
                return True
        premier = str(chemin) not in self.abandons
        self.abandons[str(chemin)] = self.horloge()
        self.ecrire(f"{nom} : le facteur ne repart pas après {ESSAIS} essais")
        if premier:
            try:
                self.notifier(nom, f"Le facteur de {nom} ne repart pas après {ESSAIS} essais : "
                                   "les messages et les ordres n'avancent plus.")
            except Exception as e:
                self.ecrire(f"{nom} : notification impossible : {type(e).__name__} : {e}")
        return False

    def boucler(self, arret: threading.Event, pas: float = PAS) -> None:
        self.ecrire("surveillant démarré")
        while not arret.is_set():
            try:
                self.passe()
            except Exception as e:
                self.ecrire(f"erreur de passe : {type(e).__name__} : {e}")
            arret.wait(pas)
        self.ecrire("surveillant arrêté")
