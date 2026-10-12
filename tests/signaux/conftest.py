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


@pytest.fixture(autouse=True)
def _jamais_le_vrai_tmux(monkeypatch):
    """Aucun test de signaux ne lance le vrai `tmux` : tout appel du facteur échoue le test,
    sauf si le test pose son faux tmux (`monkeypatch.setattr(livraison, "_tmux", faux)`)."""
    from cime.signaux import livraison, ordres

    def interdit(*args):
        raise AssertionError(f"tmux réel appelé : {args}")

    monkeypatch.setattr(livraison, "_tmux", interdit)
    monkeypatch.setattr(ordres, "_tmux", interdit)


@pytest.fixture(autouse=True)
def _sans_signalement_facteur_arrete(monkeypatch):
    """Les tests de hooks n'ont pas de facteur : sans ceci, chaque hook inscrirait un
    `signalement facteur-arrete` et fausserait leurs comptes. Les tests du facteur arrêté remettent
    la vraie fonction (`hooks_reel`)."""
    from cime.signaux import hooks
    monkeypatch.setattr(hooks, "sur_facteur_arrete", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _aucun_worker_vivant(monkeypatch):
    """Le plafond de workers lit les sessions tmux de la machine : par défaut, aucune n'est
    vivante. Un test qui veut un plafond atteint pose ses sessions."""
    from cime.signaux import ordres
    monkeypatch.setattr(ordres, "_sessions_vivantes", lambda: set())
