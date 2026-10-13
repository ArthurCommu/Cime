"""`cime reprise` marque les coordinateurs endormis dans la section « équipes et tâches en cours »."""
import pytest

from aide_repos import (
    CONVERSATION, COORD, evt, evt_sans_agent, projet, tache_en_cours,  # noqa: F401
)
from cime.signaux import reprise


def dormir(projet, agent=COORD):
    evt_sans_agent(projet, "CoordEndormi", {"agent": agent, "session": CONVERSATION})


def lignes_des_equipes(projet, moi="assistant"):
    texte = reprise.texte_reprise(projet, moi)
    bloc = texte.split("(d) Équipes et tâches en cours\n")[1].split("\n\n")[0]
    return [ligne.strip() for ligne in bloc.splitlines()]


def test_un_coordinateur_endormi_est_marque(projet):
    dormir(projet)
    assert lignes_des_equipes(projet) == ["x (coordinateur endormi) : rien en cours", "y : rien en cours"]


@pytest.mark.parametrize("moi", ["assistant", "coord-x", "coord-y", "utilisateur"])
def test_la_marque_se_lit_pour_chacun(projet, moi):
    dormir(projet)
    assert "x (coordinateur endormi) : rien en cours" in lignes_des_equipes(projet, moi)


def test_sans_sommeil_aucune_marque(projet):
    assert lignes_des_equipes(projet) == ["x : rien en cours", "y : rien en cours"]
    assert "endormi" not in reprise.texte_reprise(projet, "assistant")


def test_un_coordinateur_qui_a_repris_sa_session_n_est_plus_marque(projet):
    dormir(projet)
    evt(projet, COORD, "SessionStart", "conv-x-2", source="resume")
    assert lignes_des_equipes(projet) == ["x : rien en cours", "y : rien en cours"]


def test_un_coordinateur_reveille_n_est_plus_marque(projet):
    dormir(projet)
    evt_sans_agent(projet, "CoordReveille", {"agent": COORD, "session": CONVERSATION})
    assert "endormi" not in reprise.texte_reprise(projet, "assistant")


def test_la_marque_est_celle_de_la_bonne_equipe_et_garde_les_taches(projet):
    tache_en_cours(projet, "y", "route")
    dormir(projet, "coord-y")
    assert lignes_des_equipes(projet) == ["x : rien en cours", "y (coordinateur endormi) : route"]


def test_la_marque_suit_la_mention_cloturee(projet):
    (projet / ".orga/teams/x/CLOTUREE").write_text("")
    dormir(projet)
    assert lignes_des_equipes(projet)[0] == "x (clôturée) (coordinateur endormi) : rien en cours"


def test_un_worker_n_est_jamais_marque_endormi(projet):
    dormir(projet, "worker-x-t")
    assert "endormi" not in reprise.texte_reprise(projet, "assistant")
