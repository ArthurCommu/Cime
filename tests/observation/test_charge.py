"""Le bloc `charge` de l'instantané : plafond en vigueur, son origine, workers actifs, et l'échec
d'une collecte sans effet sur le reste. Réglages de la machine jetables (XDG_CONFIG_HOME posé par
le conftest) ; sessions tmux fixées par monkeypatch, jamais le vrai tmux."""
import json

import pytest

from cime.fondation import plafond
from cime.lanceur import surveillant
from cime.observation import charge as module
from cime.observation.instantane import instantane
from cime.signaux import livraison
from test_instantane import MANIFESTE, Faux, _orga
from test_registre import MAINTENANT

SESSIONS = {"cc-assistant", "cc-worker-obs-t1", "cc-worker-obs-t2", "ai-worker-x-y"}


@pytest.fixture
def projet(tmp_path):
    _orga(tmp_path)
    return tmp_path


@pytest.fixture
def reglages():
    dossier = plafond.dossier_reglages()
    dossier.mkdir(parents=True, exist_ok=True)
    return dossier


@pytest.fixture
def sessions(monkeypatch):
    def poser(valeur):
        monkeypatch.setattr(livraison, "sonde_sessions", lambda: valeur)
    return poser


def _manifeste(projet, ajout=""):
    (projet / ".orga" / "projet.toml").write_text(MANIFESTE + ajout, encoding="utf-8")


def _machine(dossier, valeur, apres=None):
    (dossier / "reglages.toml").write_text(f"workers_max = {valeur}\n", encoding="utf-8")
    if apres is not None:
        ligne = {"cle": "workers_max", "apres": apres, "horodatage": "2026-10-07T09:12:03.512Z",
                 "auteur": "utilisateur"}
        (dossier / "reglages.journal").write_text(json.dumps(ligne) + "\n", encoding="utf-8")


def test_defaut_sans_reglage_ni_plafond_de_projet(projet, sessions):
    sessions(SESSIONS)
    bloc, source = module.lire_charge(projet)
    assert bloc == {"workers_max": 3, "source": "machine",
                    "machine": {"valeur": 3, "source": "defaut", "depuis": None, "par": None},
                    "projet": None, "workers_actifs": 3, "par_projet": {"ai": 1, "cc": 2}}
    assert source == {"nom": "charge", "ok": True}


def test_reglage_de_la_machine_et_plafond_de_projet_plus_bas(projet, sessions, reglages):
    _machine(reglages, 6, apres=6)
    _manifeste(projet, "\n[charge]\nworkers_max = 4\n")
    sessions(SESSIONS)
    bloc, _ = module.lire_charge(projet)
    assert bloc["workers_max"] == 4 and bloc["source"] == "projet"
    assert bloc["machine"] == {"valeur": 6, "source": "fichier",
                               "depuis": "2026-10-07T09:12:03.512Z", "par": "utilisateur"}
    assert bloc["projet"] == 4


def test_plafond_de_projet_plus_haut_que_la_machine_ne_compte_pas(projet, sessions):
    _manifeste(projet, "\n[charge]\nworkers_max = 5\n")
    sessions(SESSIONS)
    bloc, _ = module.lire_charge(projet)
    assert (bloc["workers_max"], bloc["source"], bloc["projet"]) == (3, "machine", 5)


@pytest.mark.parametrize("apres", [None, 5])
def test_journal_absent_ou_ne_posant_plus_la_valeur(projet, sessions, reglages, apres):
    _machine(reglages, 6, apres=apres)
    sessions(SESSIONS)
    bloc, _ = module.lire_charge(projet)
    assert bloc["machine"] == {"valeur": 6, "source": "fichier", "depuis": None, "par": None}


def test_tmux_muet_sans_miroir_frais_les_comptes_sont_inconnus(projet, sessions, monkeypatch):
    sessions(None)
    monkeypatch.setattr(surveillant, "battement_frais", lambda *a, **k: False)
    bloc, _ = module.lire_charge(projet)
    assert (bloc["workers_actifs"], bloc["par_projet"]) == (None, None)


def test_tmux_muet_avec_miroir_frais_compte_du_facteur(projet, sessions, reglages, monkeypatch):
    _machine(reglages, 6, apres=6)
    (projet / ".orga" / "etat").mkdir(parents=True)
    (projet / ".orga" / "etat" / "charge.json").write_text(json.dumps({
        "workers_actifs": 5, "plafond_machine": 6, "source_machine": "fichier",
        "par_projet": {"ai": 2, "cc": 3}}), encoding="utf-8")
    sessions(None)
    monkeypatch.setattr(surveillant, "battement_frais", lambda *a, **k: True)
    bloc, _ = module.lire_charge(projet)
    assert bloc["workers_actifs"] == 5 and bloc["par_projet"] == {"ai": 2, "cc": 3}
    assert (bloc["machine"]["valeur"], bloc["machine"]["source"]) == (6, "fichier")


def test_bloc_charge_dans_l_instantane(projet, monkeypatch):
    Faux(monkeypatch)
    d = instantane(projet, MAINTENANT)
    assert d["charge"]["workers_max"] == 3 and d["charge"]["workers_actifs"] == 1
    assert {"nom": "charge", "ok": True} in d["sources"]
    assert json.loads(json.dumps(d))["charge"] == d["charge"]


def test_collecte_qui_leve_source_en_echec_reste_de_l_instantane_intact(projet, monkeypatch):
    Faux(monkeypatch)

    def boum(racine):
        raise RuntimeError("boum")

    monkeypatch.setattr(module, "lire_charge", boum)
    d = instantane(projet, MAINTENANT)
    assert d["charge"] is None
    assert {"nom": "charge", "ok": False, "erreur": "boum"} in d["sources"]
    assert d["equipes"] is not None and isinstance(d["alarmes"], list)
    assert json.loads(json.dumps(d)) == d
