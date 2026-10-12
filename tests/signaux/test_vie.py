"""Démarrage du facteur, vie tant qu'un agent est actif, facteur arrêté."""
import argparse
import io
import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone

import pytest

from aide import cime, fabriquer_projet, lignes
from cime.fondation import hook, lancer
from cime.fondation.nom import VAR_AGENT, VAR_PROJET
from cime.fondation.registre import inscrire_evenement, ouvrir
from cime.signaux import commandes, echeances, facteur, hooks, ordres, vie

hooks_reel = hooks.sur_facteur_arrete   # capturé avant que le conftest ne le neutralise
COORD, WORKER = "coord-x", "worker-x-t"


@pytest.fixture
def projet(tmp_path, monkeypatch):
    racine = fabriquer_projet(tmp_path / "depot")
    monkeypatch.setenv(VAR_PROJET, str(racine))
    return racine


class FauxPopen:
    appels = []

    def __init__(self, commande, **kwargs):
        FauxPopen.appels.append((commande, kwargs))


@pytest.fixture
def popen(monkeypatch):
    FauxPopen.appels = []
    monkeypatch.setattr(vie, "_popen", FauxPopen)
    return FauxPopen.appels


def poster(projet, de, a, nature="consigne", resume="r", attend="rien", objet=None):
    conn = ouvrir(projet)
    try:
        return commandes.inscrire(conn, de=de, a=a, nature=nature, resume=resume, attend=attend,
                                  objet=objet, equipe="x")
    finally:
        conn.close()


# --- démarrer_si_absent -------------------------------------------------------------------

def test_demarre_un_processus_detache_si_absent(projet, popen):
    assert vie.demarrer_si_absent(projet) is True
    (commande, kwargs), = popen
    assert commande[-1] == "facteur"
    assert kwargs["start_new_session"] is True
    assert kwargs["env"][VAR_PROJET] == str(projet) and kwargs["env"][VAR_AGENT] == "utilisateur"
    assert "CLAUDECODE" not in kwargs["env"]
    assert kwargs["stderr"] == subprocess.STDOUT
    assert kwargs["stdout"].name == str(projet / ".orga/etat/facteur.log")


def test_ne_demarre_pas_un_facteur_vivant(projet, popen):
    with facteur.verrou(projet):
        assert vie.facteur_vivant(projet) is True
        assert vie.demarrer_si_absent(projet) is False
    assert popen == []


def test_pid_perime_le_facteur_est_relance(projet, popen):
    chemin = facteur.chemin_pid(projet)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text("999999\n")      # un pid d'un facteur mort : personne ne tient le verrou
    assert vie.facteur_vivant(projet) is False
    assert vie.demarrer_si_absent(projet) is True and len(popen) == 1


def test_un_demarrage_qui_echoue_ne_leve_pas(projet, monkeypatch, capsys):
    def casse(*a, **k):
        raise OSError("pas de cime")
    monkeypatch.setattr(vie, "_popen", casse)
    assert vie.demarrer_si_absent(projet) is False
    assert "démarrage impossible" in capsys.readouterr().err


def test_sous_pytest_le_vrai_popen_ne_lance_rien(projet):
    assert vie._popen(["false"]) is None


def test_cime_lancer_direct_demarre_le_facteur_avant_de_lancer(projet, monkeypatch):
    ordre = []
    monkeypatch.setattr(vie, "demarrer_si_absent", lambda p: ordre.append("facteur"))
    monkeypatch.setattr(lancer, "_lancer", lambda args, p=None, attacher=False: ordre.append("lancer") or ("s", 0))
    assert cime(monkeypatch, None, "lancer", "assistant", projet=projet) == 0
    assert ordre == ["facteur", "lancer"]


def test_cime_lancer_par_un_agent_ne_demarre_rien_il_inscrit_un_ordre(projet, monkeypatch):
    appels = []
    monkeypatch.setattr(vie, "demarrer_si_absent", lambda p: appels.append(p))
    monkeypatch.setenv("CIME_ATTENTE_ORDRE", "0")
    cime(monkeypatch, "assistant", "lancer", "assistant", projet=projet)
    assert appels == []


def test_init_lancer_demarre_le_facteur(projet, monkeypatch):
    ordre = []
    monkeypatch.setattr(vie, "demarrer_si_absent", lambda p: ordre.append(("facteur", str(p))))
    monkeypatch.setattr(lancer, "_lancer", lambda args, p=None: ordre.append("lancer") or ("s", 0))
    assert lancer.lancer_assistant(projet) == ("s", 0)
    assert ordre == [("facteur", str(projet.resolve())), "lancer"]


# --- la vie : tant qu'un agent est actif --------------------------------------------------

def test_le_facteur_s_arrete_apres_dix_minutes_sans_agent(projet, monkeypatch):
    horloge = {"t": datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)}
    monkeypatch.setattr(facteur, "_maintenant", lambda: horloge["t"])
    monkeypatch.setattr(facteur, "tour", lambda *a, **k: horloge.update(t=horloge["t"] + timedelta(minutes=3)))
    monkeypatch.setattr(facteur, "agents_actifs", lambda p: False)
    arret = threading.Event()
    facteur.boucler(projet, arret, pas=0)
    assert not arret.is_set()   # il s'est arrêté seul, de lui-même (et non à cause de `arret`)
    assert horloge["t"] >= datetime(2026, 10, 9, 12, 10, tzinfo=timezone.utc)


def test_un_agent_actif_garde_le_facteur_en_vie(projet, monkeypatch):
    horloge = {"t": datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc), "tours": 0}
    arret = threading.Event()

    def tour(*a, **k):
        horloge["t"] += timedelta(minutes=3)
        horloge["tours"] += 1
        if horloge["tours"] == 12:
            arret.set()

    monkeypatch.setattr(facteur, "_maintenant", lambda: horloge["t"])
    monkeypatch.setattr(facteur, "tour", tour)
    monkeypatch.setattr(facteur, "agents_actifs", lambda p: True)
    facteur.boucler(projet, arret, pas=0)
    assert horloge["tours"] == 12


def test_inactivite_remise_a_zero_si_un_agent_revient(projet, monkeypatch):
    horloge = {"t": datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc), "n": 0}
    actifs = iter([False, False, False, True, False, False, False, False, False, False])

    def tour(*a, **k):
        horloge["t"] += timedelta(minutes=4)
        horloge["n"] += 1

    monkeypatch.setattr(facteur, "_maintenant", lambda: horloge["t"])
    monkeypatch.setattr(facteur, "tour", tour)
    monkeypatch.setattr(facteur, "agents_actifs", lambda p: next(actifs))
    facteur.boucler(projet, threading.Event(), pas=0)
    assert horloge["n"] == 8   # 3 sans agent (< 10 min), 1 actif, puis 10 min sans agent


def test_agents_actifs_session_du_prefixe_ou_ordre_en_file(projet, monkeypatch):
    monkeypatch.setattr(facteur.livraison, "sessions_vivantes", lambda: {"autre-chose"})
    assert facteur.agents_actifs(projet) is False
    monkeypatch.setattr(facteur.livraison, "sessions_vivantes", lambda: {"essai-coord-x"})
    assert facteur.agents_actifs(projet) is True
    monkeypatch.setattr(facteur.livraison, "sessions_vivantes", lambda: set())
    ordres.demander(projet, COORD, "capturer", WORKER, {})
    assert facteur.agents_actifs(projet) is True


# --- facteur arrêté ------------------------------------------------------------------

def _hook(monkeypatch, capsys, evenement, agent, entree=None):
    monkeypatch.setenv(VAR_AGENT, agent)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"session_id": "s", **(entree or {})})))
    code = hook.executer(argparse.Namespace(evenement=evenement))
    sortie = capsys.readouterr()
    return code, sortie.err


def signalements(projet):
    return lignes(projet, "SELECT a, objet FROM messages WHERE nature = 'signalement' "
                  "AND objet = 'facteur-arrete'")


def test_facteur_arrete_un_seul_signalement_a_l_assistant(projet, monkeypatch, capsys):
    monkeypatch.setattr(hooks, "sur_facteur_arrete", hooks_reel)
    poster(projet, "assistant", COORD)                        # un message attend, personne ne bat
    _hook(monkeypatch, capsys, "PostToolUse", WORKER)
    _hook(monkeypatch, capsys, "PostToolUse", WORKER)
    assert signalements(projet) == [("assistant", "facteur-arrete")]
    code, err = _hook(monkeypatch, capsys, "PostToolUse", "assistant")   # rendu au hook de l'Assistant
    assert code == 2 and "facteur est arrêté" in err


def test_pas_de_signalement_si_le_facteur_bat_ou_si_rien_n_attend(projet, monkeypatch, capsys):
    monkeypatch.setattr(hooks, "sur_facteur_arrete", hooks_reel)
    _hook(monkeypatch, capsys, "PostToolUse", WORKER)         # rien n'attend
    poster(projet, "assistant", COORD)
    facteur.battre(projet)                                    # il bat
    _hook(monkeypatch, capsys, "PostToolUse", WORKER)
    assert signalements(projet) == []


def test_un_battement_perime_est_un_arret(projet, monkeypatch, capsys):
    monkeypatch.setattr(hooks, "sur_facteur_arrete", hooks_reel)
    facteur.battre(projet)
    conn = ouvrir(projet)
    conn.execute("UPDATE facteur SET battement = '2020-01-01T00:00:00.000Z'")
    conn.commit()
    conn.close()
    poster(projet, "assistant", COORD)
    _hook(monkeypatch, capsys, "Stop", WORKER)
    assert signalements(projet) == [("assistant", "facteur-arrete")]


def test_au_retour_les_ordres_sont_traites_puis_le_signalement_est_clos(projet, monkeypatch, capsys):
    monkeypatch.setattr(hooks, "sur_facteur_arrete", hooks_reel)
    vus = []
    monkeypatch.setitem(ordres._EXECUTEURS, "capturer",
                        lambda p, i, params: vus.append(i) or ("execute", 0, "ok"))
    ordres.demander(projet, COORD, "capturer", WORKER, {})
    _hook(monkeypatch, capsys, "PostToolUse", WORKER)         # un ordre attend : signalement
    assert len(signalements(projet)) == 1
    facteur.tour(projet)                                      # le facteur revient
    assert vus == [1]
    obligation = lignes(projet, "SELECT o.etat FROM obligations o JOIN messages m ON "
                        "m.id = o.message_id WHERE m.objet = 'facteur-arrete'")
    assert obligation == [("satisfaite",)]
    etat_final = lignes(projet, "SELECT t.etat FROM transitions t JOIN messages m ON m.id = t.message_id "
                  "WHERE m.objet = 'facteur-arrete' ORDER BY t.id DESC LIMIT 1")
    assert etat_final == [("abandonne",)]                           # jamais remis : plus la peine
