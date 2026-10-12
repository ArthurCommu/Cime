"""Journal d'erreurs des signaux des hooks : `.orga/etat/signal-erreurs.log`.

Le signal du hook `Stop` (rapports, « ? » final, pour-assistant-*) n'existe plus : la livraison
et les dettes sont lues dans le registre (`cime.signaux.hooks`).
"""
from pathlib import Path

from cime.fondation import registre


def journal_erreurs(projet: Path) -> Path:
    return Path(projet) / ".orga" / "etat" / "signal-erreurs.log"


def _journaliser(projet: Path, agent: str, quoi: str) -> None:
    try:
        chemin = journal_erreurs(projet)
        chemin.parent.mkdir(parents=True, exist_ok=True)
        ligne = f"{registre.horodatage()} {agent} {quoi}".replace("\n", " ")
        with open(chemin, "a", encoding="utf-8") as f:
            f.write(ligne + "\n")
    except Exception:
        pass
