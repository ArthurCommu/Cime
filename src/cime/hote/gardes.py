"""Les gardes : ce que l'hôte a le droit de lancer ou de lire, prouvé par le code.

Liste blanche exacte. Ce module est le seul de `cime.hote` qui lance un processus
(un test d'inventaire statique le vérifie pour tous les autres fichiers).
"""
from __future__ import annotations

import asyncio
import os
import fnmatch
import re
import subprocess
from pathlib import Path

TOUCHES_AUTORISATION = frozenset({"1", "Escape"})
DESTINATAIRE_ASSISTANT = "assistant"

_SESSION = re.compile(r"[A-Za-z0-9._-]+")
_ENTIER = re.compile(r"[0-9]{1,6}")
_TEXTE = r'"[^"\\\n]*"'
_NOTIFICATION = re.compile(
    rf"display notification {_TEXTE}(?: with title {_TEXTE})?(?: subtitle {_TEXTE})?"
)
_SOCKET_TMUX = re.compile(r"[A-Za-z0-9._/-]+")
_LONGUEUR_SOCKET_MAX = 100  # sockets Unix : ~104 octets sur macOS, marge pour le nul
_OPTIONS_ENVOI = ("--a", "--nature", "--fichier", "--attend", "--objet")
DEMANDE_PAGE = {"--nature": "consigne", "--attend": "reponse", "--objet": "demande-page"}
_OPTIONS_REPONDRE = ("--nature", "--fichier")
_NATURES_REPONDRE_HOTE = frozenset({"reponse"})
_SANS_VALEUR_CAPTURE = {"-p", "-e", "-J"}


class Interdit(Exception):
    pass


def _session_ok(prefixe: str, cible: str) -> bool:
    return (
        cible.startswith(prefixe + "-")
        and len(cible) > len(prefixe) + 1
        and _SESSION.fullmatch(cible) is not None
    )


def _socket_ok(chemin: str | os.PathLike) -> str:
    """Chemin de socket tmux (`tmux -S`) : absolu, court, sans caractère exotique ni `..`."""
    s = os.fspath(chemin)
    if not os.path.isabs(s):
        raise ValueError(f"socket tmux : chemin absolu attendu : {s!r}")
    if len(s) > _LONGUEUR_SOCKET_MAX:
        raise ValueError(f"socket tmux : chemin de plus de {_LONGUEUR_SOCKET_MAX} caractères : {s!r}")
    if not _SOCKET_TMUX.fullmatch(s):
        raise ValueError(f"socket tmux : caractères non autorisés : {s!r}")
    if ".." in s.split("/"):
        raise ValueError(f"socket tmux : composant '..' interdit : {s!r}")
    return s


class Gardes:
    def __init__(
        self, prefixe: str, envoyer: list[str] | None = None,
        tmux_socket: str | os.PathLike | None = None,
        repondre: list[str] | None = None,
    ) -> None:
        self.prefixe = prefixe
        self.tmux_socket = _socket_ok(tmux_socket) if tmux_socket is not None else None
        self.envoyer = list(envoyer) if envoyer is not None else ["cime", "envoyer"]
        # `accorder`/`refuser` : la décision de l'utilisateur sur un accord de fusion ou de chantier ;
        # None quand la commande d'envoi est substituée (essais) : la même sert à tout.
        self.accorder = self.refuser = self.fusions_auto = None
        if repondre is not None:
            self.repondre = list(repondre)
        elif self.envoyer[-1:] == ["envoyer"]:
            self.repondre = [*self.envoyer[:-1], "repondre"]
            self.accorder = [*self.envoyer[:-1], "accorder"]
            self.refuser = [*self.envoyer[:-1], "refuser"]
            self.fusions_auto = [*self.envoyer[:-1], "fusions-auto"]
        else:  # commande d'envoi substituée (essais) : la même sert aux deux
            self.repondre = list(self.envoyer)

    # -- liste blanche ---------------------------------------------------
    def autoriser_commande(self, argv) -> None:
        """Retourne None si la commande est permise, lève `Interdit` sinon."""
        if (
            not isinstance(argv, (list, tuple))
            or not argv
            or not all(isinstance(a, str) for a in argv)
        ):
            raise Interdit("argv doit être une liste non vide de chaînes")
        argv = list(argv)
        if self.accorder is not None and argv[: len(self.accorder)] == self.accorder:
            return self._accorder(argv[len(self.accorder):])
        if self.refuser is not None and argv[: len(self.refuser)] == self.refuser:
            return self._refuser(argv[len(self.refuser):])
        if self.fusions_auto is not None and argv[: len(self.fusions_auto)] == self.fusions_auto:
            return self._fusions_auto(argv[len(self.fusions_auto):])
        if self.accorder is None and argv[: len(self.envoyer)] == self.envoyer:
            reste = argv[len(self.envoyer):]
            if len(reste) == 1 and _ENTIER.fullmatch(reste[0]):  # forme de `accorder <id>` (essais)
                return None
            if self.fusions_auto is None and reste[:1] == ["fusions-auto"]:  # idem (essais)
                return self._fusions_auto(reste[1:])
        if argv[: len(self.repondre)] == self.repondre:
            reste = argv[len(self.repondre):]
            if self.repondre != self.envoyer or (reste and reste[0].isdigit()):
                return self._repondre(reste)
        if argv[: len(self.envoyer)] == self.envoyer:
            return self._envoi(argv[len(self.envoyer):])
        if argv[0] == "tmux":
            return self._tmux(argv[1:])
        if argv[0] == "osascript":
            return self._osascript(argv[1:])
        raise Interdit(f"commande hors liste blanche : {argv[0]}")

    def _cible(self, valeur: str) -> None:
        if not _session_ok(self.prefixe, valeur):
            raise Interdit(f"session hors du projet (préfixe {self.prefixe}-) : {valeur!r}")

    def _tmux(self, a: list[str]) -> None:
        if not a:
            raise Interdit("tmux sans sous-commande")
        # -S est aussi l'option « début » de capture-pane : seul -S global (avant la
        # sous-commande) désigne un socket
        if "-L" in a or a[0] in ("-L", "-S"):
            raise Interdit("tmux : le choix du serveur appartient aux gardes")
        sous, reste = a[0], a[1:]
        if sous == "capture-pane":
            cible = False
            i = 0
            while i < len(reste):
                o = reste[i]
                if o in _SANS_VALEUR_CAPTURE:
                    i += 1
                elif o == "-S" and i + 1 < len(reste):
                    if not re.fullmatch(r"-?[0-9]{1,6}", reste[i + 1]):
                        raise Interdit("-S attend un entier")
                    i += 2
                elif o == "-t" and i + 1 < len(reste):
                    self._cible(reste[i + 1])
                    cible = True
                    i += 2
                else:
                    raise Interdit(f"option capture-pane non autorisée : {o}")
            if not cible:
                raise Interdit("capture-pane sans -t")
        elif sous in ("has-session", "kill-session"):
            if len(reste) != 2 or reste[0] != "-t":
                raise Interdit(f"{sous} : seulement -t <session>")
            self._cible(reste[1])
        elif sous == "list-sessions":
            if reste and not (len(reste) == 2 and reste[0] == "-F"):
                raise Interdit("list-sessions : seulement -F <format>")
        elif sous == "send-keys":
            if len(reste) != 3 or reste[0] != "-t":
                raise Interdit("send-keys : seulement -t <session> <touche>")
            self._cible(reste[1])
            if reste[2] not in TOUCHES_AUTORISATION:
                raise Interdit(f"touche non autorisée : {reste[2]!r}")
        else:
            raise Interdit(f"sous-commande tmux non autorisée : {sous}")

    def _osascript(self, a: list[str]) -> None:
        if len(a) != 2 or a[0] != "-e" or not _NOTIFICATION.fullmatch(a[1]):
            raise Interdit("osascript : seulement -e 'display notification \"…\"'")

    def _envoi(self, a: list[str]) -> None:
        vus: dict[str, str] = {}
        i = 0
        while i < len(a) and a[i] in _OPTIONS_ENVOI:
            if a[i] in vus or i + 1 >= len(a):
                raise Interdit(f"option d'envoi répétée ou sans valeur : {a[i]}")
            vus[a[i]] = a[i + 1]
            i += 2
        if vus.get("--a") != DESTINATAIRE_ASSISTANT:
            raise Interdit("envoi : le destinataire est imposé (--a assistant)")
        if ("--attend" in vus or "--objet" in vus) and any(vus.get(k) != v for k, v in DEMANDE_PAGE.items()):
            raise Interdit("envoi : --attend et --objet ne servent qu'à la demande de la page "
                           "(consigne, attend reponse, objet demande-page)")
        reste = a[i:]
        if len(reste) != 1 or not reste[0] or reste[0].startswith("-"):
            raise Interdit("envoi : un résumé, et rien d'autre, après les options")

    def _repondre(self, a: list[str]) -> None:
        """`repondre <id> [--nature reponse] [--fichier F] "<résumé>"` : l'utilisateur répond à un
        message qui lui est adressé ; le destinataire est celui du message cité."""
        if not a or not _ENTIER.fullmatch(a[0]):
            raise Interdit("repondre : un numéro de message d'abord")
        vus: dict[str, str] = {}
        i = 1
        while i < len(a) and a[i] in _OPTIONS_REPONDRE:
            if a[i] in vus or i + 1 >= len(a):
                raise Interdit(f"option de réponse répétée ou sans valeur : {a[i]}")
            vus[a[i]] = a[i + 1]
            i += 2
        if vus.get("--nature", "reponse") not in _NATURES_REPONDRE_HOTE:
            raise Interdit("repondre : l'hôte ne répond que par une réponse")
        reste = a[i:]
        if len(reste) != 1 or not reste[0] or reste[0].startswith("-"):
            raise Interdit("repondre : un résumé, et rien d'autre, après les options")

    def _accorder(self, a: list[str]) -> None:
        """`accorder <id>` : rien d'autre (ni `--modele` ni `--parallele`)."""
        if len(a) != 1 or not _ENTIER.fullmatch(a[0]):
            raise Interdit("accorder : un numéro de message, et rien d'autre")

    def _refuser(self, a: list[str]) -> None:
        """`refuser <id> "<motif>"` : un motif d'une ligne, rien d'autre."""
        if len(a) != 2 or not _ENTIER.fullmatch(a[0]) or not a[1] or a[1].startswith("-") or "\n" in a[1]:
            raise Interdit("refuser : un numéro de message et un motif, et rien d'autre")

    def _fusions_auto(self, a: list[str]) -> None:
        """`fusions-auto active|inactive` : la valeur, et rien d'autre (l'utilisateur seul, par `CIME_AGENT`)."""
        if len(a) != 1 or a[0] not in ("active", "inactive"):
            raise Interdit("fusions-auto : active ou inactive, et rien d'autre")

    # -- exécution -------------------------------------------------------
    def executer(
        self, argv: list[str], *, timeout: float = 5, env: dict | None = None,
        cwd: str | os.PathLike | None = None,
    ) -> subprocess.CompletedProcess:
        self.autoriser_commande(argv)
        argv = list(argv)
        if argv[0] == "tmux" and self.tmux_socket is not None:
            argv[1:1] = ["-S", self.tmux_socket]
        return subprocess.run(
            argv, shell=False, capture_output=True, text=True, timeout=timeout, env=env,
            cwd=cwd,
        )

    async def aexecuter(
        self, argv: list[str], *, timeout: float = 5, env: dict | None = None,
        cwd: str | os.PathLike | None = None,
    ):
        return await asyncio.to_thread(self.executer, argv, timeout=timeout, env=env, cwd=cwd)


# -- lecture de fichiers --------------------------------------------------
_DOSSIERS_SENSIBLES = {".ssh", ".aws", ".git"}


def _nom_sensible(nom: str) -> bool:
    return (
        nom == ".env"
        or nom.startswith(".env.")
        or fnmatch.fnmatch(nom, "*.pem")
        or fnmatch.fnmatch(nom, "*.key")
        or nom.startswith("id_rsa")
        or nom in _DOSSIERS_SENSIBLES
    )


def chemin_lisible(racine_orga: Path, relatif: str) -> Path:
    """Chemin résolu d'un fichier lisible sous `racine_orga`, sinon `Interdit`.

    Un fichier inexistant lève `FileNotFoundError` (le chemin est sain, il manque).
    """
    if not isinstance(relatif, str) or not relatif or "\0" in relatif:
        raise Interdit("chemin invalide")
    p = Path(relatif)
    if p.is_absolute() or ".." in p.parts:
        raise Interdit("chemin absolu ou contenant ..")
    if any(_nom_sensible(c) for c in p.parts):
        raise Interdit("nom sensible")
    racine = racine_orga.resolve(strict=True)
    resolu = (racine / p).resolve(strict=True)
    try:
        interne = resolu.relative_to(racine)
    except ValueError:
        raise Interdit("hors de la racine") from None
    if any(_nom_sensible(c) for c in interne.parts):
        raise Interdit("nom sensible (après résolution)")
    return resolu
