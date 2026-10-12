"""Fusions automatiques : l'annonce `rapport_utilisateur`
`fusion-auto:<é>:<sha>` n'attend rien de l'utilisateur — ni obligation, ni échéance, ni relance, ni
renotification. Tout autre `rapport_utilisateur` est inchangé. Registre jetable."""
from datetime import datetime, timedelta, timezone

import pytest

from aide import fabriquer_projet
from cime.fondation.nom import VAR_PROJET
from cime.fondation.registre import ouvrir
from cime.signaux import commandes, matrice, relances

SHA = "0123456789abcdef0123456789abcdef01234567"
ANNONCE = f"fusion-auto:x:{SHA}"


@pytest.fixture
def projet(tmp_path, monkeypatch):
    racine = fabriquer_projet(tmp_path / "depot")
    monkeypatch.setenv(VAR_PROJET, str(racine))
    return racine


def _envoyer(projet, objet):
    conn = ouvrir(projet)
    try:
        ident = commandes.inscrire(conn, de="assistant", a="utilisateur", nature="rapport_utilisateur",
                                   resume="x : ce que ça apporte", objet=objet, equipe="x")
        obligations = conn.execute("SELECT debiteur, attendu, echeance FROM obligations"
                                   " WHERE message_id = ?", (ident,)).fetchall()
    finally:
        conn.close()
    return ident, obligations


PREFIXES = ["fusion-auto:", "chantier-auto:", "contrat-auto:", "autorisation-auto:"]


def test_matrice_annonce_de_fusion_auto_n_ouvre_rien():
    assert matrice.obligation("rapport_utilisateur", "utilisateur", ANNONCE) is None
    assert matrice.obligation("rapport_utilisateur", "utilisateur", "fusion-auto:") is None


@pytest.mark.parametrize("prefixe", PREFIXES)
def test_matrice_chaque_annonce_auto_n_ouvre_rien(prefixe):
    """Fusion, chantier, contrat, autorisation — aucune obligation."""
    assert matrice.obligation("rapport_utilisateur", "utilisateur", prefixe + "x:1") is None
    assert matrice.obligation("rapport_utilisateur", "utilisateur", prefixe) is None


@pytest.mark.parametrize("objet", ["inconnu-auto:x", "decision-auto:x", "auto:x", "chantier-aut:x",
                                   "contrat:x", "autorisation:3", "chantierauto:x",
                                   "Chantier-auto:x", "x:contrat-auto:y"])
def test_matrice_un_autre_objet_auto_garde_l_obligation(objet):
    assert matrice.obligation("rapport_utilisateur", "utilisateur", objet) == ("utilisateur", "lu")


@pytest.mark.parametrize("prefixe", PREFIXES)
def test_matrice_le_prefixe_ne_vaut_que_pour_le_rapport_utilisateur(prefixe):
    """Une décision ou une donnée d'objet `…-auto:` attend toujours l'utilisateur."""
    assert matrice.obligation("decision_utilisateur", "utilisateur", prefixe + "x") == ("utilisateur", "decision")
    assert matrice.obligation("donnee_utilisateur", "utilisateur", prefixe + "x") == ("utilisateur", "reponse")


@pytest.mark.parametrize("objet", [None, "", "fusion:x:" + SHA, "fusionauto:x", "x:fusion-auto:y",
                                   "Fusion-auto:x:" + SHA])
def test_matrice_les_autres_rapports_utilisateur_sont_inchanges(objet):
    assert matrice.obligation("rapport_utilisateur", "utilisateur", objet) == ("utilisateur", "lu")


def test_annonce_n_ouvre_aucune_obligation_en_base(projet):
    _, obligations = _envoyer(projet, ANNONCE)
    assert obligations == []


@pytest.mark.parametrize("prefixe", PREFIXES)
def test_chaque_annonce_auto_n_ouvre_aucune_obligation_en_base(projet, prefixe):
    _, obligations = _envoyer(projet, prefixe + "x:1")
    assert obligations == []


def test_un_autre_objet_auto_ouvre_son_obligation_en_base(projet):
    _, obligations = _envoyer(projet, "inconnu-auto:x")
    assert [(d, a) for d, a, _ in obligations] == [("utilisateur", "lu")]
    assert obligations[0][2] is not None


def test_autre_rapport_utilisateur_ouvre_toujours_son_obligation_avec_echeance(projet):
    _, obligations = _envoyer(projet, None)
    assert [(d, a) for d, a, _ in obligations] == [("utilisateur", "lu")]
    assert obligations[0][2] is not None


@pytest.mark.parametrize("prefixe", PREFIXES)
def test_ni_echeance_ni_relance_ni_renotification(projet, prefixe):
    _envoyer(projet, prefixe + "x:1")
    plus_tard = datetime.now(timezone.utc) + timedelta(days=30)
    assert relances.executer(projet, plus_tard) == 0
    conn = ouvrir(projet)
    try:
        assert conn.execute("SELECT COUNT(*) FROM messages WHERE nature = 'relance'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
    finally:
        conn.close()


def test_le_rapport_ordinaire_avance_bien_son_echelle(projet):
    """Contre-épreuve : la passe qui ne touche à rien pour l'annonce fait avancer l'échelle de
    l'obligation d'un rapport ordinaire."""
    ident, _ = _envoyer(projet, None)
    relances.executer(projet, datetime.now(timezone.utc) + timedelta(days=30))
    conn = ouvrir(projet)
    try:
        rang = conn.execute("SELECT relances FROM obligations WHERE message_id = ?",
                            (ident,)).fetchone()[0]
    finally:
        conn.close()
    assert rang >= 1
