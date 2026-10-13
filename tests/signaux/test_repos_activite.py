"""Le facteur ne s'arrête pas à cause d'un coordinateur endormi : `agents_actifs` compte les sessions du
projet et les ordres en file. Ce fichier constate ce comportement, il ne le change pas."""
from aide_repos import (
    ASSISTANT, COORD, S_ASSISTANT, dans, dormir_pour_de_bon, machine, poster, projet,  # noqa: F401
)
from cime.signaux import facteur, livraison


def test_l_assistant_vivant_tient_le_facteur_actif_meme_si_un_coordinateur_dort(projet, machine):
    dormir_pour_de_bon(projet, machine)
    assert set(machine.sessions) == {S_ASSISTANT}
    assert facteur.agents_actifs(projet) is True


def test_un_endormi_seul_sans_assistant_n_est_pas_actif(projet, machine):
    dormir_pour_de_bon(projet, machine)
    del machine.sessions[S_ASSISTANT]
    assert machine.sessions == {}
    assert facteur.agents_actifs(projet) is False


def test_un_ordre_de_reveil_en_file_tient_le_facteur_actif(projet, machine):
    dormir_pour_de_bon(projet, machine)
    del machine.sessions[S_ASSISTANT]
    poster(projet, ASSISTANT, COORD)
    livraison.livrer_tout(projet, dans(25), livraison.Memoire())
    assert facteur.agents_actifs(projet) is True


def test_la_boucle_du_facteur_ne_sort_pas_par_inactivite_tant_que_l_assistant_vit(projet, machine, monkeypatch):
    import threading
    dormir_pour_de_bon(projet, machine)
    arret = threading.Event()
    tours = []

    def un_tour(*a, **k):
        tours.append(1)
        if len(tours) == 3:
            arret.set()
    monkeypatch.setattr(facteur, "tour", un_tour)
    assert facteur.boucler(projet, arret, pas=0) == "arret"
