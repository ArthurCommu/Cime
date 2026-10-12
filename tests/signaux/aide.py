"""Outils communs aux tests de tests/signaux."""
import tempfile
import textwrap
from pathlib import Path

from cime import cli
from cime.fondation.nom import VAR_AGENT, VAR_PROJET
from cime.fondation.registre import ouvrir

MANIFESTE = textwrap.dedent("""\
    nom = "Essai"
    prefixe = "essai"
    branche_reference = "main"
    branche_equipe = "equipe/{equipe}"
    worktree_equipe = "../{depot}-{equipe}"
    equipes_speciales = ["assistant"]
    modele_assistant = "modele-assistant"
    modele_coordinateur = "modele-coord"
""")


DEPOT = Path(__file__).resolve().parents[2]


def exiger_jetable(racine) -> Path:
    """Garde-fou (un manifeste d'essai ne doit jamais écraser celui du dépôt) : une fabrique de
    projet refuse tout dossier qui n'est pas jetable — il contient
    `.git`, est le dépôt ou son worktree (ou en contient un), ou n'est pas sous le dossier
    temporaire du système."""
    racine = Path(racine).resolve()
    if (racine / ".git").exists():
        raise ValueError(f"{racine} contient .git : pas un dossier jetable")
    if racine == DEPOT or racine in DEPOT.parents or DEPOT in racine.parents:
        raise ValueError(f"{racine} est le dépôt (ou le contient) : pas un dossier jetable")
    temporaires = [Path(d).resolve() for d in (tempfile.gettempdir(), "/tmp", "/private/tmp")]
    if not any(racine.is_relative_to(t) for t in temporaires):
        raise ValueError(f"{racine} n'est pas sous un dossier temporaire : pas jetable")
    return racine


def fabriquer_projet(racine, equipes=("x", "y")):
    racine = exiger_jetable(racine)
    for e in equipes:
        for sous in ("tasks/todo", "tasks/in-progress", "tasks/done", "reports", "conversations"):
            (racine / ".orga" / "teams" / e / sous).mkdir(parents=True)
    (racine / ".orga" / "projet.toml").write_text(MANIFESTE)
    (racine / "note.md").write_text("note")
    return racine


def cime(monkeypatch, agent, *argv, projet=None):
    """Lance `cime <argv>` en tant qu'`agent` (None = humain au clavier)."""
    if agent is None:
        monkeypatch.delenv(VAR_AGENT, raising=False)
    else:
        monkeypatch.setenv(VAR_AGENT, agent)
    if projet is not None:
        monkeypatch.setenv(VAR_PROJET, str(projet))
    return cli.main(list(argv))


def lignes(projet, requete, params=()):
    conn = ouvrir(projet)
    try:
        return conn.execute(requete, params).fetchall()
    finally:
        conn.close()
