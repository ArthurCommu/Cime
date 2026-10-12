"""Clôture d'une équipe de bout en bout, sur un projet jetable (tmp_path) : la demande du
coordinateur, le rapport de l'Assistant à l'utilisateur, puis l'instantané d'observation."""
import argparse

from cime import cli
from cime.fondation import envoyer
from cime.fondation.nom import VAR_AGENT, VAR_PROJET
from cime.observation.instantane import instantane

MANIFESTE = """\
nom = "Essai"
prefixe = "essai"
branche_reference = "main"
branche_equipe = "equipe/{equipe}"
worktree_equipe = "../{depot}-{equipe}"
equipes_speciales = ["assistant"]
modele_assistant = "modele-assistant"
modele_coordinateur = "modele-coord"
"""


def _envoi(agent, monkeypatch, **kw):
    monkeypatch.setenv(VAR_AGENT, agent)
    args = argparse.Namespace(fichier=None, en_reponse_a=None, equipe=None, **kw)
    assert envoyer.executer(args) == 0


def test_cloture_proposee_avec_son_equipe(tmp_path, monkeypatch, capsys):
    racine = (tmp_path / "depot").resolve()
    (racine / ".orga" / "teams" / "x" / "tasks").mkdir(parents=True)
    (racine / ".orga" / "projet.toml").write_text(MANIFESTE)
    monkeypatch.setenv(VAR_PROJET, str(racine))

    _envoi("coord-x", monkeypatch, a="assistant", nature="demande_cloture", resume="x est finie")
    demande = int(capsys.readouterr().out.strip())
    monkeypatch.setenv(VAR_AGENT, "assistant")
    assert cli.main(["repondre", str(demande), "--nature", "rapport_utilisateur",
                     "clôturer x ?"]) == 0

    attentes = [a for a in instantane(racine)["attentes_utilisateur"] if a["nature"] == "cloture"]
    assert len(attentes) == 1
    assert attentes[0]["bloque"] == "x"
    assert attentes[0]["agent"] == "coord-x"
    assert attentes[0]["actions"] == ["cloturer"]
