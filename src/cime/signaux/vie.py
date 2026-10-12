"""La vie du facteur.

Le facteur d'un projet est démarré par le premier lancement d'agent (`cime lancer`,
`cime init --lancer`) s'il est absent, vit tant qu'au moins un agent du projet est actif
(`facteur.boucler`), et le surveillant de la machine (`lanceur/surveillant.py`) le relance s'il
meurt pendant ce temps. Tout le démarrage passe par `demarrer_si_absent`.
"""
import fcntl
import os
import shutil
import subprocess
import sys
from pathlib import Path

from cime.fondation.nom import NOM, VAR_AGENT, VAR_PROJET
from cime.fondation.registre import ouvrir
from cime.signaux import facteur, obligations

VAR_CLAUDECODE = "CLAUDECODE"


def _popen(commande, **kwargs):
    if "PYTEST_CURRENT_TEST" in os.environ:  # filet : aucun vrai facteur lancé par une suite de tests
        return None
    return subprocess.Popen(commande, **kwargs)


def facteur_vivant(projet) -> bool:
    """Vrai si un facteur tient `facteur.pid` : le verrou est la vérité (il disparaît avec le
    processus, même tué) ; un pid resté dans le fichier ne prouve rien."""
    chemin = facteur.chemin_pid(projet)
    if not chemin.exists():
        return False
    try:
        with open(chemin, "a+") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return True
            fcntl.flock(f, fcntl.LOCK_UN)
    except OSError:
        return False
    return False


def commande_facteur() -> list[str]:
    exe = shutil.which(NOM)
    if exe:
        return [os.path.abspath(exe), "facteur"]
    return [sys.executable, "-c", "import sys; from cime.cli import main; sys.exit(main(['facteur']))"]


def demarrer_si_absent(projet) -> bool:
    """Lance `cime facteur` en processus détaché si `facteur.pid` ne désigne pas un facteur
    vivant. Renvoie True si un facteur a été lancé. Ne lève jamais : un facteur qui ne démarre
    pas est un problème signalé par le battement périmé, pas un motif de bloquer l'appelant."""
    projet = Path(projet)
    try:
        if facteur_vivant(projet):
            return False
        journal = projet / ".orga" / "etat" / "facteur.log"
        journal.parent.mkdir(parents=True, exist_ok=True)
        env = {k: v for k, v in os.environ.items() if k != VAR_CLAUDECODE}
        env[VAR_PROJET] = str(projet)
        env[VAR_AGENT] = "utilisateur"   # le facteur agit pour l'utilisateur
        with open(journal, "ab") as sortie:
            _popen(commande_facteur(), cwd=str(projet), env=env, stdin=subprocess.DEVNULL,
                   stdout=sortie, stderr=subprocess.STDOUT, start_new_session=True)
        return True
    except Exception as e:
        print(f"facteur : démarrage impossible ({type(e).__name__} : {e})", file=sys.stderr)
        return False


def clore_signalements_arret(projet) -> int:
    """Au retour du facteur (après ses ordres en file) : la ligne `signalement facteur-arrete`
    est close — non encore remise : abandonnée ; remise : son obligation est satisfaite."""
    conn = ouvrir(projet)
    fermes = 0
    try:
        from cime.fondation.registre import inscrire_transition
        for message_id, etat in conn.execute(
                "SELECT m.id, (SELECT t.etat FROM transitions t WHERE t.message_id = m.id"
                " ORDER BY t.id DESC LIMIT 1) FROM messages m WHERE m.de = 'cime'"
                " AND m.nature = 'signalement' AND m.objet = 'facteur-arrete'").fetchall():
            ouverte = obligations.ouverte_pour(conn, message_id) is not None
            if etat == "inscrit":
                inscrire_transition(conn, message_id, "abandonne", "cime", {"facteur_revenu": True})
                obligations.satisfaire(conn, message_id, None)
                fermes += 1
            elif ouverte:
                obligations.satisfaire(conn, message_id, None)
                fermes += 1
    finally:
        conn.close()
    return fermes
