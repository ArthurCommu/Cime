import tempfile
from pathlib import Path

import pytest

from cime.fondation.nom import VAR_AGENT, VAR_PROJET


@pytest.fixture(autouse=True)
def _sans_agent_ni_projet_reels(monkeypatch, tmp_path_factory):
    """Aucun test n'écrit dans le registre d'un vrai projet : chaque test part avec
    un projet jetable vide (sans .orga) à la place de celui hérité de l'agent qui
    lance la suite, et sans agent. Les tests qui ont besoin d'un projet le fixent."""
    monkeypatch.setenv(VAR_PROJET, str(tmp_path_factory.mktemp("projet-jetable")))
    monkeypatch.delenv(VAR_AGENT, raising=False)
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.setenv("CIME_ATTENTE_STOP", "0")  # le hook Stop n'attend jamais 120 s en test


DEPOT = Path(__file__).resolve().parents[2]


def exiger_jetable(racine, refuser_git=True) -> Path:
    """Voir tests/signaux/aide.py : une fabrique de projet refuse un dossier non jetable.
    `refuser_git=False` pour le garde-fou d'écriture : `cime init` crée légitimement `.git`."""
    racine = Path(racine).resolve()
    if refuser_git and (racine / ".git").exists():
        raise ValueError(f"{racine} contient .git : pas un dossier jetable")
    if racine == DEPOT or racine in DEPOT.parents or DEPOT in racine.parents:
        raise ValueError(f"{racine} est le dépôt (ou le contient) : pas un dossier jetable")
    temporaires = [Path(d).resolve() for d in (tempfile.gettempdir(), "/tmp", "/private/tmp")]
    if not any(racine.is_relative_to(t) for t in temporaires):
        raise ValueError(f"{racine} n'est pas sous un dossier temporaire : pas jetable")
    return racine


@pytest.fixture(autouse=True)
def _manifeste_seulement_en_dossier_jetable(monkeypatch):
    """Toutes les fabriques de projet des tests écrivent `.orga/projet.toml` par
    `Path.write_text` : on refuse l'écriture hors d'un dossier jetable."""
    ecrire = Path.write_text

    def garde(self, *args, **kwargs):
        if self.name == "projet.toml" and self.parent.name == ".orga":
            exiger_jetable(self.parent.parent, refuser_git=False)
        return ecrire(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", garde)


@pytest.fixture(autouse=True)
def _sans_signalement_facteur_arrete(monkeypatch):
    """Les tests de hooks n'ont pas de facteur : sans ceci, chaque hook inscrirait un
    `signalement facteur-arrete` et fausserait leurs comptes. Les tests du facteur remettent
    la vraie fonction (`hooks_reel`)."""
    from cime.signaux import hooks
    monkeypatch.setattr(hooks, "sur_facteur_arrete", lambda *a, **k: None)
