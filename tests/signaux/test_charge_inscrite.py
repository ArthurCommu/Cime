"""Le facteur inscrit le compte de workers actifs ; la sonde tmux distingue « zéro » de « muet »."""
import json
import subprocess

import pytest

from cime.signaux import facteur, livraison, ordres
from aide_charge import (  # noqa: F401
    WORKER, battement_vieux, compte_inscrit, fichier_charge, muet, poser_worker, projet, tmux)


# --- 1. le facteur inscrit le compte ---------------------------------------------------------

def test_le_facteur_inscrit_le_compte_a_chaque_changement(projet, tmux):
    for sessions, attendu in [({"p-worker-x-a"}, 1),
                              ({"p-worker-x-a", "q-worker-y-b", "p-coord-x"}, 2),
                              (set(), 0)]:
        tmux["sessions"] = sessions
        facteur._etape_charge(projet, None, None)
        assert compte_inscrit(projet) == attendu


def test_le_facteur_ne_reecrit_pas_un_compte_inchange(projet, tmux, monkeypatch):
    tmux["sessions"] = {"p-worker-x-a"}
    facteur._etape_charge(projet, None, None)
    ecritures = []
    vrai = ordres.os.replace
    monkeypatch.setattr(ordres.os, "replace", lambda a, b: (ecritures.append(b), vrai(a, b)))
    facteur._etape_charge(projet, None, None)
    assert ecritures == []
    tmux["sessions"] = set()
    facteur._etape_charge(projet, None, None)
    assert len(ecritures) == 1


def test_l_ecriture_est_atomique(projet, tmux, monkeypatch):
    tmux["sessions"] = {"p-worker-x-a"}
    facteur._etape_charge(projet, None, None)
    vus = []

    def remplacer(source, cible):
        vus.append((str(source), str(cible), json.loads(open(source).read())))
        raise OSError("coupure")

    monkeypatch.setattr(ordres.os, "replace", remplacer)
    tmux["sessions"] = set()
    with pytest.raises(OSError):
        ordres.inscrire_charge(projet)
    assert len(vus) == 1
    source, cible, contenu = vus[0]
    assert source != cible and contenu == {"workers_actifs": 0}     # complet avant le remplacement
    assert compte_inscrit(projet) == 1                              # l'ancien reste lisible


def test_tmux_muet_le_facteur_n_inscrit_rien(projet, tmux):
    tmux["sessions"] = {"p-worker-x-a"}
    facteur._etape_charge(projet, None, None)
    muet(tmux)
    facteur._etape_charge(projet, None, None)
    assert compte_inscrit(projet) == 1      # jamais « 0 » parce que la sonde a échoué


def test_l_etape_charge_suit_les_ordres_dans_le_tour():
    noms = [nom for nom, _ in facteur.ETAPES]
    assert noms.index("charge") == noms.index("ordres") + 1


# --- 7 et 8. le facteur décide avec tmux -----------------------------------------------------

def test_le_facteur_garde_l_ordre_tant_que_le_plafond_est_atteint(projet, tmux, monkeypatch):
    executes = []
    monkeypatch.setattr(ordres, "executer", lambda p, o: (executes.append(o["id"]),
                                                          ("execute", 0, ""))[1])
    tmux["sessions"] = {"p-worker-y-z"}
    poser_worker(projet)
    assert ordres._executer_en_file(projet, 1) is False and executes == []
    tmux["sessions"] = set()
    assert ordres._executer_en_file(projet, 1) is True and executes == [1]


def test_tmux_muet_cote_facteur_ne_fait_pas_croire_a_zero_worker(projet, tmux, monkeypatch):
    executes = []
    monkeypatch.setattr(ordres, "executer", lambda p, o: (executes.append(o["id"]),
                                                          ("execute", 0, ""))[1])
    muet(tmux)
    poser_worker(projet)
    assert ordres._executer_en_file(projet, 1) is False and executes == []
    ordres.demander(projet, "coord-x", "fermer", "worker-x-a", {})
    assert ordres._executer_en_file(projet, 2) is True      # le plafond ne retient que les lancements


def completed(code, erreur="", sortie=""):
    return subprocess.CompletedProcess([], code, sortie, erreur)


@pytest.mark.parametrize("reponse,attendu", [
    (completed(0, sortie="a\nb\n"), {"a", "b"}),
    (completed(1, "no server running on /private/tmp/tmux-501/default"), set()),
    (completed(1, "error connecting to /private/tmp/tmux-501/default (No such file or directory)"),
     set()),
    (completed(1, "error connecting to /private/tmp/tmux-501/default (Operation not permitted)"),
     None),
    (completed(127, "inconnu"), None),
])
def test_la_sonde_distingue_zero_session_et_tmux_muet(monkeypatch, reponse, attendu):
    monkeypatch.setattr(livraison, "_tmux", lambda *a: reponse)
    assert livraison.sonde_sessions() == attendu


def test_la_sonde_binaire_absent(monkeypatch):
    def absent(*a):
        raise FileNotFoundError("tmux")
    monkeypatch.setattr(livraison, "_tmux", absent)
    assert livraison.sonde_sessions() is None


def test_sessions_vivantes_du_facteur_ne_change_pas(monkeypatch):
    monkeypatch.setattr(livraison, "_tmux", lambda *a: completed(1, "Operation not permitted"))
    assert livraison.sessions_vivantes() == set()
