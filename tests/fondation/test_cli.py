import os
import sys
import time
import types

import pytest

from cime import cli
from cime.fondation.nom import VAR_PROJET


def _projet(base, nom="p"):
    d = base / nom
    (d / ".orga").mkdir(parents=True)
    (d / ".orga" / "projet.toml").write_text("")
    return d


@pytest.fixture
def lanceur(monkeypatch):
    appels = []
    mod = types.ModuleType("cime.lanceur")
    mod.servir = lambda port=0, modele=None: appels.append((port, modele))
    mod.port_voulu = lambda: 47615
    monkeypatch.setitem(sys.modules, "cime.lanceur", mod)
    return appels, mod


@pytest.fixture
def hote(monkeypatch):
    appels = []
    mod = types.ModuleType("cime.hote")
    mod.servir = lambda projet, port=0: appels.append((projet, port))
    monkeypatch.setitem(sys.modules, "cime.hote", mod)
    return appels


def test_lanceur_defaut(lanceur):
    appels, _ = lanceur
    assert cli.main(["lanceur"]) == 0
    assert appels == [(47615, None)]


def test_lanceur_port_et_modele(lanceur):
    appels, _ = lanceur
    assert cli.main(["lanceur", "--port", "8123", "--modele", "m1"]) == 0
    assert appels == [(8123, "m1")]


def test_lanceur_absent(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "cime.lanceur", None)
    assert cli.main(["lanceur"]) == 1
    err = capsys.readouterr().err
    assert "cime.lanceur" in err and len(err.strip().splitlines()) == 1


def test_lanceur_systemexit_relaye(lanceur):
    def deja_vivant(port=0, modele=None):
        raise SystemExit("un lanceur tourne déjà")
    lanceur[1].servir = deja_vivant
    with pytest.raises(SystemExit) as e:
        cli.main(["lanceur"])
    assert e.value.code == "un lanceur tourne déjà"


def test_servir_chemin_l_emporte_sur_env(tmp_path, monkeypatch, hote):
    env = _projet(tmp_path, "env")
    voulu = _projet(tmp_path, "voulu")
    monkeypatch.setenv(VAR_PROJET, str(env))
    assert cli.main(["servir", str(voulu), "--port", "9"]) == 0
    assert hote == [(voulu.resolve(), 9)]


def test_servir_chemin_sans_manifeste(tmp_path, hote, capsys):
    assert cli.main(["servir", str(tmp_path)]) == 2
    assert "n'est pas un projet" in capsys.readouterr().err
    assert hote == []


def test_servir_sans_chemin_inchange(tmp_path, monkeypatch, hote):
    env = _projet(tmp_path, "env")
    monkeypatch.setenv(VAR_PROJET, str(env))
    assert cli.main(["servir"]) == 0
    assert hote == [(env, 0)]


def test_aide_decrit_lanceur_et_servir(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    sortie = capsys.readouterr().out
    assert "lanceur" in sortie and "servir" in sortie
    with pytest.raises(SystemExit):
        cli.main(["lanceur", "--help"])
    assert "--modele" in capsys.readouterr().out


def _hote_ecrivant(monkeypatch, delai, port="4321"):
    def servir(projet, port_voulu=0):
        time.sleep(delai)
        f = projet / ".orga" / "etat" / "hote.port"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(port)
        time.sleep(0.3)  # laisse le fil d'annonce lire
    mod = types.ModuleType("cime.hote")
    mod.servir = servir
    monkeypatch.setitem(sys.modules, "cime.hote", mod)


def _port_ancien(projet, port="1111"):
    f = projet / ".orga" / "etat" / "hote.port"
    f.parent.mkdir(parents=True)
    f.write_text(port)
    os.utime(f, (time.time() - 3600,) * 2)


def test_servir_imprime_l_url(tmp_path, monkeypatch, capsys):
    p = _projet(tmp_path)
    _hote_ecrivant(monkeypatch, 0.2)
    assert cli.main(["servir", str(p)]) == 0
    assert capsys.readouterr().out == "http://127.0.0.1:4321/\n"


def test_servir_ignore_un_port_ancien(tmp_path, monkeypatch, capsys):
    p = _projet(tmp_path)
    _port_ancien(p)
    _hote_ecrivant(monkeypatch, 0.2, port="2222")
    assert cli.main(["servir", str(p)]) == 0
    assert capsys.readouterr().out == "http://127.0.0.1:2222/\n"


def test_servir_avertit_si_rien(tmp_path, monkeypatch, capsys):
    p = _projet(tmp_path)
    _port_ancien(p)
    monkeypatch.setattr(cli, "ATTENTE_URL_S", 0.3)
    monkeypatch.setattr(cli._annoncer_url, "__defaults__", (0.3, 0.05))
    mod = types.ModuleType("cime.hote")
    mod.servir = lambda projet, port=0: time.sleep(0.6)
    monkeypatch.setitem(sys.modules, "cime.hote", mod)
    assert cli.main(["servir", str(p)]) == 0
    sortie = capsys.readouterr()
    assert sortie.out == ""
    assert "non annoncé" in sortie.err


def test_aide_du_lanceur_dit_que_les_hotes_lui_survivent(capsys):
    with pytest.raises(SystemExit):
        cli.main(["lanceur", "--help"])
    texte = " ".join(capsys.readouterr().out.split())
    assert "lui survivent" in texte and "hote.port" in texte
