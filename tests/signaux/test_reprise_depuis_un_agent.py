"""`cime reprise` depuis un agent : la section des lancements en attente lit le compte du facteur."""
from cime.signaux import facteur, ordres, reprise
from aide_charge import (  # noqa: F401
    WORKER, battement_vieux, compte_inscrit, fichier_charge, muet, poser_worker, projet, tmux)


# --- 6. cime reprise depuis un agent ---------------------------------------------------------

def test_reprise_depuis_un_agent_lit_le_compte_du_facteur(projet, tmux):
    tmux["sessions"] = {"p-worker-y-z"}
    facteur._etape_charge(projet, None, None)
    facteur.battre(projet)
    muet(tmux)
    poser_worker(projet)
    assert ("(g) File de lancements : 1 en attente (plafond 1, actifs 1) : worker-x-a"
            in reprise.texte_reprise(projet, "coord-x"))


def test_reprise_compte_inconnu_garde_la_section(projet, tmux):
    muet(tmux)
    poser_worker(projet)
    assert ("(g) File de lancements : 1 en attente (plafond 1, actifs ?) : worker-x-a"
            in reprise.texte_reprise(projet, "coord-x"))


def test_reprise_compte_inconnu_sans_lancement_en_file_pas_de_section(projet, tmux):
    muet(tmux)
    ordres.demander(projet, "coord-x", "fermer", "worker-x-a", {})
    assert "(g)" not in reprise.texte_reprise(projet, "coord-x")


def test_reprise_tmux_visible_comportement_inchange(projet, tmux):
    tmux["sessions"] = {"p-worker-y-z"}
    poser_worker(projet)
    assert ("(g) File de lancements : 1 en attente (plafond 1, actifs 1) : worker-x-a"
            in reprise.texte_reprise(projet, "assistant"))
    tmux["sessions"] = set()
    assert "(g)" not in reprise.texte_reprise(projet, "assistant")
