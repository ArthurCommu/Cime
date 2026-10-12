"""`cime lancer` : un worker ne lance rien, un coordinateur ne lance que les workers de son équipe."""
import pytest

from cime.fondation.garde import decider
from cime.fondation.nom import VAR_AGENT


def entree(commande, cwd):
    return {"tool_name": "Bash", "tool_input": {"command": commande}, "cwd": str(cwd)}


@pytest.fixture
def identite(monkeypatch):
    def fixer(nom):
        if nom is None:
            monkeypatch.delenv(VAR_AGENT, raising=False)
        else:
            monkeypatch.setenv(VAR_AGENT, nom)
    return fixer


@pytest.fixture
def ici(tmp_path):
    return tmp_path


WORKER_REFUSE = [
    "cime lancer worker fondation t1 --modele m",
    "cime lancer coord fondation",
    "cime lancer assistant",
    "cime lancer",
    "/chemin/cime lancer worker fondation t1",
    "python -m cime lancer worker fondation t1",
    "python3.12 -m cime lancer assistant",
    "uv run cime lancer worker fondation t1",
    "uvx cime lancer assistant",
    'bash -c "cime lancer assistant"',
    "env cime lancer coord x",
    "xargs cime lancer assistant",
    "cime -- lancer assistant",
    "cime --modele m lancer worker fondation t1",
    "true && cime lancer assistant",
    "rtk cime lancer assistant",
]


@pytest.mark.parametrize("commande", WORKER_REFUSE)
def test_worker_ne_lance_rien(ici, identite, commande):
    identite("worker-fondation-t1")
    assert decider(entree(commande, ici), None) is not None


@pytest.mark.parametrize("commande", [
    "cime lancer worker fondation t1 --modele m",
    "cime lancer worker fondation t2 --reprendre",
    "/chemin/cime lancer worker fondation t1 --modele m",
    "python -m cime lancer worker fondation t1",
    "uv run cime lancer worker fondation t1 --modele m",
    'bash -c "cime lancer worker fondation t1"',
    "env cime lancer worker fondation t1",
    "cime envoyer --a coord-fondation --nature rapport_worker resume",
    "cime etat",
    "cime reprise",
    "cime compacter worker-fondation-t1",
])
def test_coordinateur_lance_les_workers_de_son_equipe(ici, identite, commande):
    identite("coord-fondation")
    assert decider(entree(commande, ici), None) is None


@pytest.mark.parametrize("commande", [
    "cime lancer assistant",
    "cime lancer coord fondation",
    "cime lancer coord autre",
    "cime lancer worker autre t1 --modele m",
    "cime lancer worker fondationx t1",
    "cime lancer worker $EQUIPE t1",
    "cime lancer worker `echo fondation` t1",
    "cime lancer worker $(echo fondation) t1",
    "cime lancer worker",
    "cime lancer",
    "cime lancer --modele m worker fondation t1",
    "cime -- lancer assistant",
    "cime --modele m lancer worker fondation t1",
    "/chemin/cime lancer assistant",
    "python -m cime lancer coord x",
    'bash -c "cime lancer assistant"',
    "env cime lancer coord x",
    "uv run cime lancer assistant",
    "uvx cime lancer coord x",
    "xargs cime lancer assistant",
    "find . -exec cime lancer assistant ;",
    "uv run --project /autre/cime cime lancer assistant",
])
def test_coordinateur_ne_lance_pas_le_reste(ici, identite, commande):
    identite("coord-fondation")
    motif = decider(entree(commande, ici), None)
    assert motif is not None
    assert "ne lances que les workers de ton équipe" in motif or \
        "option avant la sous-commande" in motif


@pytest.mark.parametrize("nom", [None, "assistant"])
def test_assistant_et_sans_identite_inchanges(ici, identite, nom):
    identite(nom)
    for commande in ("cime lancer assistant", "cime lancer coord fondation",
                     "cime lancer worker fondation t1"):
        assert decider(entree(commande, ici), None) is None


def test_message_du_coordinateur_dit_ce_qui_est_permis(ici, identite):
    identite("coord-fondation")
    motif = decider(entree("cime lancer assistant", ici), None)
    assert "`cime lancer worker <ton équipe> <tâche> --modele <modèle>`" in motif


def test_message_du_worker_dit_qu_il_ne_lance_rien(ici, identite):
    identite("worker-fondation-t1")
    motif = decider(entree("cime lancer worker fondation t2", ici), None)
    assert "ne lances aucun agent" in motif
