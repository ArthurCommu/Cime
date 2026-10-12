"""La fenêtre de terminal où revient l'Assistant après `rouvrir` : un fichier `.command` qui
s'attache à la session tmux, ouvert par `open -a` (iTerm, sinon Terminal). Aucun `osascript` :
le Lanceur n'a pas le droit de piloter une application par Apple Events.
"""
import json
import re
import subprocess
from pathlib import Path

SESSION = re.compile(r"[A-Za-z0-9_-]+")
# le PATH d'une fenêtre ouverte par `open` est celui de la session graphique : tmux (Homebrew) n'y est pas toujours
CONTENU = ('#!/bin/zsh\nexport PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"\n'
           "exec tmux attach -t {session}\n")


def _terminal_du_reglage(dossier: Path) -> str | None:
    try:
        valeur = json.loads((dossier / "lanceur.json").read_text(encoding="utf-8")).get("terminal")
    except (OSError, ValueError, AttributeError):
        return None
    return valeur if isinstance(valeur, str) and valeur else None


def ouvrir_fenetre(dossier_lanceur, session, terminal=None, lancer=subprocess.run) -> bool:
    """Ouvre une fenêtre attachée à `session`. Renvoie vrai si `open` a réussi ; ne lève jamais."""
    try:
        if not isinstance(session, str) or not SESSION.fullmatch(session):
            return False
        dossier = Path(dossier_lanceur)
        script = dossier / "fenetres" / f"{session}.command"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(CONTENU.format(session=session), encoding="utf-8")
        script.chmod(0o700)
        choisi = terminal or _terminal_du_reglage(dossier)
        if choisi is None:
            ok = lancer(["open", "-Ra", "iTerm"], capture_output=True).returncode == 0
            choisi = "iTerm" if ok else "Terminal"
        return lancer(["open", "-a", choisi, str(script)], capture_output=True).returncode == 0
    except Exception:
        return False
