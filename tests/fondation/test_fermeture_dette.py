"""La règle « un coordinateur a de quoi être gardé » : une seule définition, partagée par le plan de
fermeture et par la mise au repos des coordinateurs."""
from cime.fondation import fermeture


def dettes(**faits):
    base = dict(vivants=set(), equipes_connues=["hote", "page", "scene"],
                coordinables=["hote", "page", "scene"], taches=[], debiteurs=set(), en_attente=set())
    return fermeture.raisons_de_garder(**{**base, **faits})


def test_rien_ne_retient_un_coordinateur_sans_dette():
    assert dettes() == {}


def test_worker_vivant_de_l_equipe_retient_pour_travail():
    assert dettes(vivants={"worker-page-vue-y"}) == {"coord-page": "travail"}


def test_tache_en_cours_de_l_equipe_retient_pour_travail():
    assert dettes(taches=["scene/prise-1", "vieux/ancienne"]) == {"coord-scene": "travail"}


def test_obligation_ouverte_du_coordinateur_retient_pour_travail():
    assert dettes(debiteurs={"coord-hote", "worker-hote-t", "assistant"}) == {"coord-hote": "travail"}


def test_message_en_attente_retient_pour_message():
    assert dettes(en_attente={"coord-page"}) == {"coord-page": "message"}


def test_travail_l_emporte_sur_message():
    assert dettes(en_attente={"coord-page"}, taches=["page/t"]) == {"coord-page": "travail"}


def test_un_worker_en_attente_ou_debiteur_sans_session_ne_retient_personne():
    assert dettes(debiteurs={"worker-hote-t"}, en_attente={"worker-hote-t"}) == {}


def test_seules_les_equipes_demandees_sont_evaluees():
    assert dettes(coordinables=["hote"], taches=["page/t"], en_attente={"coord-page"}) == {}


def test_equipe_au_nom_prefixe_par_une_autre():
    assert dettes(equipes_connues=["hote", "hote-bis"], coordinables=["hote", "hote-bis"],
                  vivants={"worker-hote-bis-t"}) == {"coord-hote-bis": "travail"}


def test_l_ordre_des_coordinateurs_est_celui_des_equipes_triees():
    resultat = dettes(coordinables=["scene", "page", "hote"], en_attente={"coord-page", "coord-hote"})
    assert list(resultat) == ["coord-hote", "coord-page"]


def test_identites_vivantes_ne_garde_que_les_sessions_du_projet():
    assert fermeture.identites_vivantes("essai", {"essai-assistant", "essai-coord-hote", "autre-coord-x",
                                                    "essai"}) == {
        "assistant": "essai-assistant", "coord-hote": "essai-coord-hote"}
