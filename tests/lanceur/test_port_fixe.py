"""Port fixe du lanceur : port voulu, repli si le port est pris, `--plist --port`.

Le plist n'est qu'imprimé, rien n'est installé. `servir` tourne dans un thread, comme dans test_lanceur."""
import json
import plistlib
import socket
import threading
import time
from pathlib import Path

import pytest

from cime import cli
from cime import lanceur as paquet
from cime.lanceur import launchd
from cime.lanceur import serveur as mod
from cime.lanceur import servir


def ecrire_reglages(texte: str) -> None:
    dossier = Path.home() / ".cime"
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "lanceur.json").write_text(texte, encoding="utf-8")


def lire_reglages() -> dict:
    return json.loads((Path.home() / ".cime" / "lanceur.json").read_text(encoding="utf-8"))


@pytest.fixture
def espion(monkeypatch):
    """Remplace `servir` du paquet : enregistre (port, modèle) sans rien lancer."""
    appels = []
    monkeypatch.setattr(paquet, "servir", lambda port=0, modele=None: appels.append((port, modele)))
    return appels


# --- le port voulu -------------------------------------------------------------------------

def test_port_par_defaut_hors_plage_ephemere():
    assert mod.PORT_PAR_DEFAUT == 47615
    assert not 49152 <= mod.PORT_PAR_DEFAUT <= 65535


def test_option_port_l_emporte_sur_le_reglage(espion):
    ecrire_reglages('{"port": 5001}')
    assert cli.main(["lanceur", "--port", "5000"]) == 0
    assert espion == [(5000, None)]


def test_reglage_port_l_emporte_sur_le_defaut(espion):
    ecrire_reglages('{"port": 5001}')
    assert cli.main(["lanceur"]) == 0
    assert espion == [(5001, None)]


def test_sans_option_ni_reglage_le_port_par_defaut(espion):
    assert cli.main(["lanceur"]) == 0
    assert espion == [(47615, None)]


def test_option_port_zero_reste_un_port_libre(espion):
    assert cli.main(["lanceur", "--port", "0"]) == 0
    assert espion == [(0, None)]


@pytest.mark.parametrize("texte", [
    '{"port": "abc"}', '{"port": 0}', '{"port": 70000}', '{"port": true}', '{pas du json',
])
def test_reglage_port_illisible_ou_invalide_ignore(espion, texte):
    ecrire_reglages(texte)
    assert cli.main(["lanceur"]) == 0
    assert espion == [(47615, None)]


# --- repli si le port est pris -------------------------------------------------------------

def _port_occupe():
    """Un socket qui écoute : un autre processus tient ce port."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen()
    return s, s.getsockname()[1]


def _port_libre() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _lancer_servir(dossier, port, arret):
    t = threading.Thread(
        target=servir, kwargs=dict(port=port, dossier=dossier, cime=["x"], arret=arret), daemon=True)
    t.start()
    return t


def _attendre_port_ecrit(fichier: Path, fin_s: float = 10.0) -> int:
    limite = time.time() + fin_s
    while time.time() < limite:
        try:
            return int(fichier.read_text().strip())
        except (OSError, ValueError):
            time.sleep(0.02)
    raise AssertionError(f"{fichier} n'a jamais été écrit")


def test_port_pris_repli_sur_un_port_libre_dit_sur_stderr(tmp_path, capsys):
    occupant, voulu = _port_occupe()
    dossier = tmp_path / "d"
    arret = threading.Event()
    try:
        t = _lancer_servir(dossier, voulu, arret)
        effectif = _attendre_port_ecrit(dossier / "lanceur.port")
    finally:
        arret.set()
        t.join(10)
        occupant.close()
    assert effectif != voulu
    err = capsys.readouterr().err
    assert f"Le port {voulu} est pris : le lanceur écoute sur le port {effectif}." in err


def test_port_libre_pas_de_phrase_et_port_voulu(tmp_path, capsys):
    voulu = _port_libre()
    dossier = tmp_path / "d"
    arret = threading.Event()
    t = _lancer_servir(dossier, voulu, arret)
    try:
        effectif = _attendre_port_ecrit(dossier / "lanceur.port")
    finally:
        arret.set()
        t.join(10)
    assert effectif == voulu
    assert "pris" not in capsys.readouterr().err


# --- --plist --port ------------------------------------------------------------------------

def test_plist_port_par_defaut_et_reglage_ecrit(monkeypatch, capsys):
    monkeypatch.setattr(launchd.shutil, "which", lambda nom: "/usr/local/bin/cime")
    assert cli.main(["lanceur", "--plist"]) == 0
    donnees = plistlib.loads(capsys.readouterr().out.encode("utf-8"))
    assert donnees["ProgramArguments"] == ["/usr/local/bin/cime", "lanceur", "--port", "47615"]
    assert lire_reglages() == {"port": 47615}


def test_plist_port_option_ecrit_le_reglage_et_garde_le_reste(monkeypatch, capsys):
    monkeypatch.setattr(launchd.shutil, "which", lambda nom: "/usr/local/bin/cime")
    ecrire_reglages('{"utilisateur": "camille", "terminal": "iTerm"}')
    assert cli.main(["lanceur", "--plist", "--port", "5000"]) == 0
    donnees = plistlib.loads(capsys.readouterr().out.encode("utf-8"))
    assert donnees["ProgramArguments"][-2:] == ["--port", "5000"]
    assert lire_reglages() == {"utilisateur": "camille", "terminal": "iTerm", "port": 5000}


def test_plist_n_installe_rien(capsys):
    assert cli.main(["lanceur", "--plist"]) == 0
    assert plistlib.loads(capsys.readouterr().out.encode("utf-8"))["Label"] == "cime.lanceur"
    assert not (Path.home() / "Library").exists()


def test_plist_port_hors_plage_refuse_sans_rien_ecrire(capsys):
    assert cli.main(["lanceur", "--plist", "--port", "70000"]) == 2
    assert capsys.readouterr().out == ""
    assert not (Path.home() / ".cime" / "lanceur.json").exists()
