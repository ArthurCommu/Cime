"""Un vrai shell sert d'oracle à la garde.

Une commande où bash ou zsh exécute réellement un appel interdit (push, suppression de branche,
Trousseau, tmux, rtk proxy) doit être refusée, quelle que soit l'enveloppe : sur le corpus écrit
à la main et sur des combinaisons produites à graine fixe. Le texte du corpus n'exécute rien.
"""
import pytest

from aide_garde_texte import REFUSEES, REFUSEES_PRUDENCE, TEXTES
from aide_oracle_shell import Oracle, generer
from cime.fondation import garde

GRAINE = 20261014
GENERES = 300
SHELLS = Oracle.disponibles()


@pytest.fixture(scope="module")
def oracle(tmp_path_factory):
    return Oracle(tmp_path_factory.mktemp("oracle"))


def motif(commande, cwd):
    return garde.decider({"tool_name": "Bash", "tool_input": {"command": commande},
                          "cwd": str(cwd)}, None)


def _shells_ou_saut():
    if not SHELLS:
        pytest.skip("ni /bin/bash ni /bin/zsh : l'oracle ne peut pas se lancer")
    return SHELLS


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_oracle_aucun_faux_negatif(oracle, shell):
    """Si un vrai shell exécute un appel interdit, la garde refuse la commande."""
    if shell not in SHELLS:
        pytest.skip(f"/bin/{shell} absent : l'oracle ne peut pas se lancer")
    corpus = REFUSEES + REFUSEES_PRUDENCE + TEXTES + generer(GENERES, GRAINE)
    vus = [(c, oracle.interdits(c, shell)) for c in corpus]
    manques = [(c, a) for c, a in vus if a and motif(c, oracle.travail) is None]
    assert manques == [], "\n\n".join(f"{c!r}\n  → {a}" for c, a in manques)


@pytest.mark.parametrize("commande", REFUSEES)
def test_le_corpus_refuse_est_execute_par_un_vrai_shell(oracle, commande):
    """Chaque cas « refusé » est une vraie action : sinon le corpus ne prouve rien."""
    assert any(oracle.interdits(commande, s) for s in _shells_ou_saut()), commande


@pytest.mark.parametrize("commande", TEXTES)
def test_le_texte_n_execute_rien(oracle, commande):
    for s in _shells_ou_saut():
        assert oracle.interdits(commande, s) == [], (s, commande)


def test_le_generateur_produit_des_actions_reelles(oracle):
    """Le corpus généré contient des appels réellement exécutés (sinon l'oracle ne teste rien)."""
    shell = _shells_ou_saut()[0]
    executes = [c for c in generer(GENERES, GRAINE) if oracle.interdits(c, shell)]
    assert len(executes) >= GENERES // 3


def test_le_generateur_est_fixe():
    assert generer(20, GRAINE) == generer(20, GRAINE)
    assert len(set(generer(GENERES, GRAINE))) > GENERES // 2


def test_les_faux_programmes_journalisent(oracle):
    shell = _shells_ou_saut()[0]
    assert oracle.appels("git -C . push origin; tmux ls; echo ok", shell) == [
        ("git", "-C", ".", "push", "origin"), ("tmux", "ls")]
    assert oracle.interdits("git status; rtk git log", shell) == []
