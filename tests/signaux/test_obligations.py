from datetime import timedelta

from cime.fondation.projet import valider_identite
from cime.fondation.registre import inscrire_message, ouvrir
from cime.signaux import echeances, matrice, obligations
import pytest


def test_cime_valide_comme_emetteur_seulement():
    assert valider_identite("cime", emetteur=True) == "cime"
    with pytest.raises(ValueError):
        valider_identite("cime")


def test_echeances_par_defaut():
    assert echeances.delai("question", "reponse", "coord-x") == timedelta(minutes=15)
    assert echeances.delai("demande_accord", "accord", "assistant") == timedelta(minutes=10)
    assert echeances.delai("travail_pret", "revue", "coord-x") == timedelta(minutes=30)
    assert echeances.delai("travail_pret", "revue", "assistant") == timedelta(minutes=60)
    assert echeances.delai("demande_cloture", "rapport_utilisateur", "assistant") == timedelta(minutes=60)
    assert echeances.delai("consigne", "reponse", "coord-x") is None
    assert echeances.delai("consigne", "accuse", "coord-x") == echeances.DELAI_OCCUPE


def test_tout_signalement_est_echu_aussitot():
    assert echeances.delai("signalement", "accuse", "assistant", "fige") == echeances.IMMEDIAT
    assert echeances.delai("signalement", "decision", "assistant", "autorisation:3") \
        == echeances.IMMEDIAT
    assert echeances.delai("signalement", "accuse", "coord-x", "facteur-arrete") \
        == echeances.IMMEDIAT
    assert echeances.echeance("2026-10-09T10:00:00.000Z", None) is None
    assert echeances.echeance("2026-10-09T10:00:00.000Z", timedelta(minutes=15)) \
        == "2026-10-09T10:15:00.000Z"


def test_obligation_selon_la_nature():
    assert matrice.obligation("consigne", "coord-x", None, "rien") is None
    assert matrice.obligation("consigne", "coord-x", None, "accuse") == ("coord-x", "accuse")
    assert matrice.obligation("signalement", "assistant", "autorisation:3") == (
        "assistant", "decision")
    assert matrice.obligation("signalement", "assistant", "fige") == ("assistant", "accuse")
    assert matrice.obligation("rapport_utilisateur", "utilisateur") == ("utilisateur", "lu")
    assert matrice.obligation("compte_rendu", "assistant") is None
    assert matrice.obligation("relance", "coord-x") is None


def test_ouvrir_satisfaire_ouvertes_de(tmp_path):
    conn = ouvrir(tmp_path)
    m = inscrire_message(conn, de="coord-x", a="assistant", nature="question", resume="?")
    obligations.ouvrir_obligation(conn, m, "assistant", "reponse", "2026-10-09T10:15:00.000Z")
    ouvertes = obligations.ouvertes_de(conn, "assistant")
    assert [o["message_id"] for o in ouvertes] == [m]
    assert obligations.satisfaire(conn, m, ferme_par=99) is True
    assert obligations.satisfaire(conn, m, ferme_par=100) is False
    assert obligations.ouvertes_de(conn, "assistant") == []
    assert conn.execute("SELECT etat, ferme_par FROM obligations").fetchone() == ("satisfaite", 99)
