"""La boucle, le battement, les ordres, le verrou."""
import argparse
import os
import signal
import threading
from datetime import timedelta

import pytest

from aide import fabriquer_projet, lignes
from cime.fondation.registre import ouvrir
from cime.signaux import echeances, facteur, ordres, vie


@pytest.fixture
def projet(tmp_path, monkeypatch):
    racine = fabriquer_projet(tmp_path / "depot")
    monkeypatch.setenv("CIME_PROJET", str(racine))
    return racine


def test_un_tour_execute_les_ordres_dans_l_ordre_et_bat(projet, monkeypatch):
    faits = []
    monkeypatch.setitem(ordres._EXECUTEURS, "capturer",
                        lambda p, i, params: faits.append(i) or ("execute", 0, "ok"))
    ids = [ordres.demander(projet, "coord-x", "capturer", f"worker-x-{n}", {}) for n in "abc"]
    bilan = facteur.tour(projet)
    assert faits == ids and bilan == {"ordres": 3, "erreurs": []}
    assert lignes(projet, "SELECT etat FROM ordres ORDER BY id") == [("execute",)] * 3
    battement, version = lignes(projet, "SELECT battement, version FROM facteur")[0]
    assert battement.endswith("Z") and version == facteur.VERSION


def test_chaque_tour_bat(projet):
    facteur.tour(projet)
    premier = lignes(projet, "SELECT battement FROM facteur")[0][0]
    facteur.tour(projet)
    assert lignes(projet, "SELECT battement FROM facteur")[0][0] >= premier
    assert lignes(projet, "SELECT count(*) FROM facteur") == [(1,)]


def test_un_second_facteur_du_meme_projet_est_refuse(projet, capsys):
    with facteur.verrou(projet):
        assert facteur.chemin_pid(projet).read_text().strip() == str(os.getpid())
        with pytest.raises(facteur.DejaEnCours) as e:
            with facteur.verrou(projet):
                pass
        assert str(os.getpid()) in str(e.value)
        code = facteur.executer(argparse.Namespace(une_fois=True))
        assert code == 0 and f"déjà en cours (pid {os.getpid()})" in capsys.readouterr().out
    assert not facteur.chemin_pid(projet).exists()
    with facteur.verrou(projet):  # libéré
        pass


def test_une_exception_d_etape_est_journalisee_et_n_arrete_pas_le_tour(projet, monkeypatch):
    vus = []

    def casse(projet_, maintenant, memoire):
        raise RuntimeError("boum")

    monkeypatch.setattr(facteur, "ETAPES", (("ordres", casse),
                                             ("livraison", lambda *a: vus.append("livraison")),
                                             ("echeances", lambda *a: vus.append("echeances"))))
    bilan = facteur.tour(projet)
    assert bilan["erreurs"] == ["ordres"] and vus == ["livraison", "echeances"]
    assert "ordres RuntimeError: boum" in facteur.chemin_erreurs(projet).read_text()


def test_la_boucle_fait_un_tour_par_pas_jusqu_a_l_arret(projet, monkeypatch):
    arret = threading.Event()
    appels = []

    def tour_compte(projet_, maintenant=None, memoire=None):
        appels.append(memoire)
        if len(appels) == 4:
            arret.set()

    monkeypatch.setattr(facteur, "tour", tour_compte)
    monkeypatch.setattr(facteur, "agents_actifs", lambda p: True)
    facteur.boucler(projet, arret, pas=0)
    assert len(appels) == 4 and len({id(m) for m in appels}) == 1  # même mémoire d'un tour à l'autre


def test_sigterm_finit_le_tour_et_retire_le_pid(projet, monkeypatch):
    anciens = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}

    def boucle_factice(projet_, arret):
        assert facteur.chemin_pid(projet).exists()
        os.kill(os.getpid(), signal.SIGTERM)
        assert arret.wait(2)

    monkeypatch.setattr(facteur, "boucler", boucle_factice)
    try:
        assert facteur.executer(argparse.Namespace(une_fois=False)) == 0
    finally:
        for s, h in anciens.items():
            signal.signal(s, h)
    assert not facteur.chemin_pid(projet).exists()


def test_la_commande_une_fois_fait_un_tour(projet, monkeypatch, capsys):
    from aide import cime
    monkeypatch.setitem(ordres._EXECUTEURS, "capturer", lambda p, i, params: ("execute", 0, "ok"))
    ordres.demander(projet, "coord-x", "capturer", "worker-x-a", {})
    assert cime(monkeypatch, None, "facteur", "--une-fois") == 0
    assert "1 ordre(s) exécuté(s)" in capsys.readouterr().out


# --- arrêt propre : le successeur est demandé après la libération du verrou ----------------

@pytest.fixture
def signaux_restaures():
    anciens = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
    yield
    for s, h in anciens.items():
        signal.signal(s, h)


@pytest.fixture
def successeurs(monkeypatch):
    """Espionne `vie.demarrer_si_absent` : pour chaque demande, (projet, verrou encore tenu ?)."""
    vus = []
    monkeypatch.setattr(vie, "demarrer_si_absent",
                        lambda p: vus.append((p, facteur.chemin_pid(p).exists())) or True)
    return vus


def boucle_recevant_sigterm(motif):
    def boucle(projet_, arret):
        os.kill(os.getpid(), signal.SIGTERM)
        assert arret.wait(2)
        return motif
    return boucle


def test_boucler_dit_pourquoi_il_sort(projet, monkeypatch):
    monkeypatch.setattr(facteur, "tour", lambda *a, **k: None)
    monkeypatch.setattr(facteur, "agents_actifs", lambda p: True)
    arret = threading.Event()
    arret.set()
    assert facteur.boucler(projet, arret, pas=0) == "arret"
    monkeypatch.setattr(facteur, "agents_actifs", lambda p: False)
    monkeypatch.setattr(echeances, "INACTIVITE_FACTEUR", timedelta(0))
    assert facteur.boucler(projet, threading.Event(), pas=0) == "inactivite"


def test_arret_par_signal_avec_agents_actifs_demande_le_successeur_verrou_libre(
        projet, monkeypatch, successeurs, signaux_restaures):
    monkeypatch.setattr(facteur, "agents_actifs", lambda p: True)
    monkeypatch.setattr(facteur, "boucler", boucle_recevant_sigterm("arret"))
    assert facteur.executer(argparse.Namespace(une_fois=False)) == 0
    assert successeurs == [(projet, False)]


def test_arret_par_signal_sans_agent_actif_pas_de_successeur(
        projet, monkeypatch, successeurs, signaux_restaures):
    monkeypatch.setattr(facteur, "agents_actifs", lambda p: False)
    monkeypatch.setattr(facteur, "boucler", boucle_recevant_sigterm("arret"))
    assert facteur.executer(argparse.Namespace(une_fois=False)) == 0
    assert successeurs == []


def test_sortie_par_inactivite_pas_de_successeur(projet, monkeypatch, successeurs, signaux_restaures):
    monkeypatch.setattr(facteur, "agents_actifs", lambda p: True)
    monkeypatch.setattr(facteur, "boucler", lambda projet_, arret: "inactivite")
    assert facteur.executer(argparse.Namespace(une_fois=False)) == 0
    assert successeurs == []


def test_une_fois_pas_de_successeur(projet, monkeypatch, successeurs, signaux_restaures):
    monkeypatch.setattr(facteur, "agents_actifs", lambda p: True)
    assert facteur.executer(argparse.Namespace(une_fois=True)) == 0
    assert successeurs == []
