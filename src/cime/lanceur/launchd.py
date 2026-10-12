"""L'agent launchd de la machine : un seul, qui relance `cime lanceur` (et donc le surveillant).

Ce module ne fait que **générer** le texte du `.plist` ; il ne l'installe pas (l'utilisateur l'installe,
une fois : `cime lanceur --plist > ~/Library/LaunchAgents/cime.lanceur.plist`)."""
import os
import plistlib
import shutil
from pathlib import Path

from .serveur import PORT_PAR_DEFAUT

LABEL = "cime.lanceur"


def plist(cime: str | None = None, home: Path | None = None, path: str | None = None,
          port: int = PORT_PAR_DEFAUT) -> str:
    """Le texte XML de l'agent : lancé à l'ouverture de session (`RunAtLoad`), relancé s'il
    s'arrête (`KeepAlive`), `cime lanceur --port <port>` en commande. `cime` : chemin absolu de
    l'exécutable (launchd n'a pas le PATH de l'utilisateur)."""
    home = Path(home) if home is not None else Path.home()
    exe = cime or shutil.which("cime") or "cime"
    contenu = {
        "Label": LABEL,
        "ProgramArguments": [os.path.abspath(exe) if os.path.sep in exe else exe, "lanceur",
                             "--port", str(port)],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 30,
        "StandardOutPath": str(home / ".cime" / "lanceur.log"),
        "StandardErrorPath": str(home / ".cime" / "lanceur.log"),
        "EnvironmentVariables": {"PATH": path or os.environ.get("PATH", "/usr/bin:/bin")},
    }
    return plistlib.dumps(contenu).decode("utf-8")


INSTALLATION = (
    "# Installation (une fois, par l'utilisateur) :\n"
    "#   cime lanceur --plist > ~/Library/LaunchAgents/cime.lanceur.plist\n"
    "#   launchctl load ~/Library/LaunchAgents/cime.lanceur.plist\n"
    "# Le port du lanceur est fixe : `cime ouvrir` ouvre la page dans le navigateur.\n")
