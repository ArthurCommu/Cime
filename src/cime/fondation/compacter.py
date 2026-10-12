"""`cime compacter` : demande à la session d'un agent subordonné de compacter son contexte."""

import subprocess
import sys
import time

from cime.fondation import invite
from cime.fondation.envoyer import _projet
from cime.fondation.nom import VAR_PROJET
from cime.fondation.projet import (ErreurProjet, equipe_de, lire_manifeste,
                                   session_tmux, valider_identite)
from cime.fondation.registre import inscrire_message, inscrire_transition, ouvrir
from cime.signaux.identite import ErreurIdentite, appelant

TOUCHE_VALIDATION = "Enter"
PAUSE = 1.0
RESUME_MAX = 140
_LIBELLE = {"refuse": "refusé", "echec": "échec"}


def _tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", *args], capture_output=True, text=True)


def _attendre(secondes: float) -> None:
    time.sleep(secondes)


def _erreur(message: str, code: int = 1) -> int:
    print(f"compacter : {message}", file=sys.stderr)
    return code


def est_superieur(appelant: str, cible: str, projet) -> bool:
    """Vrai si `appelant` est le supérieur direct de `cible` : l'Assistant pour un
    coordinateur, `coord-<é>` pour un worker dont l'équipe (résolue par les dossiers
    d'équipe du projet) est `<é>`. Équipe introuvable : faux."""
    if appelant == "assistant":
        return cible.startswith("coord-")
    if appelant.startswith("coord-") and cible.startswith("worker-"):
        return equipe_de(projet, cible) == appelant[len("coord-"):]
    return False


def journaliser(projet, *, de, a, consignes, resultat) -> int:
    """Ligne de traçabilité (consigne, `--attend rien`) : déjà close, elle n'est jamais livrée.
    Toujours inscrite `de=cime` : l'utilisateur ne parle qu'à l'Assistant, la ligne ne traverse pas la
    hiérarchie. L'auteur réel (`de`) est dans la preuve."""
    resume = f"/compact — {consignes}"
    resume = f"{resume[:RESUME_MAX - len(resultat) - 3]} — {resultat}"
    conn = ouvrir(projet)
    try:
        with conn:
            identifiant = inscrire_message(
                conn, de="cime", a=a, nature="consigne", resume=resume,
                equipe=equipe_de(projet, a) or equipe_de(projet, de), commit=False)
            inscrire_transition(conn, identifiant, "clos", "cime",
                                {"journal": "compacter", "auteur": de}, commit=False)
        return identifiant
    finally:
        conn.close()


_journaliser = journaliser


def _compacter(args) -> int:
    try:
        de = appelant()
    except ErreurIdentite as e:
        return _erreur(str(e), 2)
    a = args.identite
    try:
        valider_identite(de)
        valider_identite(a)
    except ValueError as e:
        return _erreur(str(e), 2)
    projet = _projet()
    if projet is None:
        return _erreur(f"{VAR_PROJET} absent (ou ne désigne pas un projet) : lance cette "
                       "commande depuis un agent lancé par `cime lancer`", 2)
    tentative = _Tentative(projet, de, a, args.consignes)
    try:
        code = _tenter(projet, de, a, args.consignes, tentative)
    except Exception as e:
        tentative.clore(f"échec : {e}"[:80])
        raise
    return code


class _Tentative:
    """Inscrit au registre une seule ligne par tentative, quel qu'en soit le résultat."""

    def __init__(self, projet, de, a, consignes):
        self.projet, self.de, self.a, self.consignes = projet, de, a, consignes
        self.identifiant = None

    def clore(self, resultat: str) -> None:
        if self.identifiant is None:
            self.identifiant = _journaliser(self.projet, de=self.de, a=self.a,
                                            consignes=self.consignes, resultat=resultat)


def _refus(tentative, motif: str, message: str) -> int:
    tentative.clore(f"refusé : {motif}")
    return _erreur(message, 2)


def _tenter(projet, de, a, consignes, tentative) -> int:
    if de != "utilisateur":
        if a == "assistant":
            return _refus(tentative, "Assistant compactable par l'utilisateur seul",
                          "l'Assistant n'est compacté que par l'utilisateur (alarme contexte)")
        if not est_superieur(de, a, projet):
            return _refus(tentative, "pas le supérieur direct",
                          f"seul le supérieur direct de {a} peut la compacter")
        from cime.signaux import ordres
        identifiant, resultat = ordres.poser_et_attendre(
            projet, de, "compacter", a, {"consignes": consignes})
        if resultat is None:
            tentative.clore(f"ordre #{identifiant} en file")
        elif resultat["etat"] == "execute":
            tentative.clore("fait")
            print(tentative.identifiant)
            return 0
        else:
            tentative.clore(f"{_LIBELLE[resultat['etat']]} : {resultat['texte']}"[:80])
        return ordres._issue(identifiant, resultat)
    etat, texte = frapper(projet, a, consignes)
    tentative.clore("fait" if etat == "execute" else f"{_LIBELLE[etat]} : {texte}"[:80])
    if etat == "execute":
        print(tentative.identifiant)
        return 0
    return _erreur(texte, 2 if etat == "refuse" else 1)


def frapper(projet, a: str, consignes: str) -> tuple[str, str]:
    """Exécution (facteur, ou l'utilisateur à la main) : tape `/compact <consignes>` dans la session
    de `a`. Ne contrôle plus l'état de l'agent ni son invite : le facteur attend le repos.
    Retourne (état de l'ordre, texte)."""
    session = session_tmux(lire_manifeste(projet), a)
    if session is None or _tmux("has-session", "-t", f"={session}").returncode != 0:
        return "refuse", f"session de {a} absente"
    cible = f"={session}:"
    _tmux("send-keys", "-t", cible, "-l", f"/compact {consignes}")
    _attendre(PAUSE)
    _tmux("send-keys", "-t", cible, TOUCHE_VALIDATION)
    for essai in range(2):
        _attendre(PAUSE)
        if not invite.brouillon(cible):  # vide, ou None : la commande tourne
            return "execute", "fait"
        if essai == 0:
            _tmux("send-keys", "-t", cible, TOUCHE_VALIDATION)
    return "echec", f"/compact resté dans l'invite de {a}"


def executer(args) -> int:
    try:
        return _compacter(args)
    except (ErreurProjet, ValueError) as e:
        return _erreur(str(e))
