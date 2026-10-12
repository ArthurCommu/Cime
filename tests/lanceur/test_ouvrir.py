"""`cime ouvrir` : ouvrir le lanceur dans le navigateur, le démarrer au besoin.

`launchctl` et `open` sont des faux en tête du PATH : aucun vrai `open` ni vrai `launchctl` n'est lancé.
Le démarrage détaché passe par un faux `Popen` (rien ne part). Le faux `launchctl` écrit `lanceur.port`
vers un serveur HTTP de test qui répond à la sonde."""
import argparse
import http.server
import json
import os
import socket
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from cime.fondation.fermeture import Echec, _exiger_utilisateur
from cime.lanceur import ouvrir as mod

LAUNCHCTL = (
    'printf "launchctl %s\\n" "$*" >> "$FAUX_TRACE"\n'
    '[ "$FAUX_LAUNCHCTL" = echec ] && exit 1\n'
    'printf "%s" "$FAUX_PORT" > "$FAUX_DOSSIER/lanceur.port"\n'
    "exit 0\n")
OPEN = (
    'printf "open %s\\n" "$*" >> "$FAUX_TRACE"\n'
    '[ "$FAUX_OPEN" = echec ] && exit 1\n'
    "exit 0\n")


@pytest.fixture(autouse=True)
def moi(monkeypatch):
    """Les tests sont l'utilisateur au clavier : aucune identité d'agent, pas de CLAUDECODE."""
    monkeypatch.delenv("CIME_AGENT", raising=False)
    monkeypatch.delenv("CLAUDECODE", raising=False)


@pytest.fixture
def faux(tmp_path, monkeypatch):
    bin_ = tmp_path / "faux-bin"
    bin_.mkdir()
    for nom, corps in (("launchctl", LAUNCHCTL), ("open", OPEN)):
        f = bin_ / nom
        f.write_text("#!/bin/sh\n" + corps, encoding="utf-8")
        f.chmod(0o755)
    trace = tmp_path / "trace.txt"
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("FAUX_TRACE", str(trace))
    monkeypatch.setenv("FAUX_LAUNCHCTL", "ok")
    monkeypatch.setenv("FAUX_OPEN", "ok")
    monkeypatch.setenv("FAUX_PORT", "0")
    monkeypatch.setenv("FAUX_DOSSIER", str(tmp_path))

    def appels():
        return trace.read_text(encoding="utf-8").splitlines() if trace.exists() else []
    return SimpleNamespace(appels=appels)


@pytest.fixture
def vivant():
    """Un serveur HTTP de test qui répond 200 à la sonde : « un lanceur qui répond »."""
    class Accueil(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            corps = b"[]"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(corps)))
            self.end_headers()
            self.wfile.write(corps)

        def log_message(self, *args):
            pass

    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Accueil)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield s.server_port
    s.shutdown()
    s.server_close()


def mort() -> int:
    """Un port où personne n'écoute."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Lancement:
    """Faux `subprocess.Popen` : enregistre argv et options, ne lance rien."""

    def __init__(self):
        self.appels = []

    def __call__(self, argv, **options):
        self.appels.append({
            "argv": list(argv), "stdin": options["stdin"], "stderr": options["stderr"],
            "start_new_session": options["start_new_session"], "sortie": options["stdout"].name})
        return SimpleNamespace(pid=0)


def appeler(dossier, lancement, *, plist=None, dormir=None, delai_s=1, **kw):
    return mod.ouvrir_lanceur(
        dossier=dossier, agent=plist or dossier / "pas-d-agent.plist", uid=501,
        cime="/usr/local/bin/cime", lancer_detache=lancement,
        dormir=dormir or (lambda s: None), delai_s=delai_s, **kw)


def ecrire_port(dossier: Path, port: int) -> None:
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "lanceur.port").write_text(str(port), encoding="utf-8")


# --- lanceur déjà en marche ----------------------------------------------------------------

def test_deja_en_marche_rien_ne_demarre(lanceur, faux):
    lancement = Lancement()
    donnees = appeler(lanceur.dossier, lancement)
    assert donnees["resultat"] == "ok" and donnees["demarre"] == "deja"
    assert donnees["url"] == f"http://127.0.0.1:{lanceur.port}/"
    assert "Le lanceur tournait déjà." in donnees["phrases"]
    assert faux.appels() == [f"open http://127.0.0.1:{lanceur.port}/"]
    assert lancement.appels == []


def test_resultat_ok_a_les_champs_documentes(lanceur, faux):
    donnees = appeler(lanceur.dossier, Lancement())
    assert set(donnees) == {"resultat", "url", "port", "demarre", "phrases"}


# --- lanceur arrêté ------------------------------------------------------------------------

def test_arrete_avec_agent_launchd_kickstart_puis_open(faux, tmp_path, vivant, monkeypatch):
    dossier = tmp_path / "cime"
    dossier.mkdir()
    plist = tmp_path / "cime.lanceur.plist"
    plist.write_text("agent", encoding="utf-8")
    monkeypatch.setenv("FAUX_PORT", str(vivant))
    monkeypatch.setenv("FAUX_DOSSIER", str(dossier))
    lancement = Lancement()
    donnees = appeler(dossier, lancement, plist=plist)
    assert donnees["resultat"] == "ok" and donnees["demarre"] == "launchd"
    assert "Le lanceur a été démarré (agent launchd)." in donnees["phrases"]
    assert faux.appels() == [
        "launchctl kickstart gui/501/cime.lanceur",
        f"open http://127.0.0.1:{vivant}/"]
    assert lancement.appels == []


def test_arrete_sans_agent_processus_detache(faux, tmp_path, vivant):
    dossier = tmp_path / "cime"
    lancement = Lancement()

    def dormir(_):                                # le processus détaché « démarre » : il écrit son port
        ecrire_port(dossier, vivant)

    donnees = appeler(dossier, lancement, dormir=dormir)
    assert donnees["resultat"] == "ok" and donnees["demarre"] == "detache"
    assert "Le lanceur a été démarré (processus détaché)." in donnees["phrases"]
    assert lancement.appels == [{
        "argv": ["/usr/local/bin/cime", "lanceur"], "stdin": subprocess.DEVNULL,
        "stderr": subprocess.STDOUT, "start_new_session": True,
        "sortie": str(dossier / "lanceur.log")}]
    assert faux.appels() == [f"open http://127.0.0.1:{vivant}/"]


def test_agent_present_launchctl_echoue_repli_sur_detache(faux, tmp_path, vivant, monkeypatch):
    monkeypatch.setenv("FAUX_LAUNCHCTL", "echec")
    dossier = tmp_path / "cime"
    plist = tmp_path / "cime.lanceur.plist"
    plist.write_text("agent", encoding="utf-8")
    lancement = Lancement()
    donnees = appeler(dossier, lancement, plist=plist, dormir=lambda _: ecrire_port(dossier, vivant))
    assert donnees["resultat"] == "ok" and donnees["demarre"] == "detache"
    assert faux.appels()[0] == "launchctl kickstart gui/501/cime.lanceur"
    assert len(lancement.appels) == 1


def test_lanceur_port_perime_est_pris_pour_arrete(faux, tmp_path, vivant):
    dossier = tmp_path / "cime"
    ecrire_port(dossier, mort())                   # un fichier périmé : personne n'écoute
    lancement = Lancement()
    donnees = appeler(dossier, lancement, dormir=lambda _: ecrire_port(dossier, vivant))
    assert donnees["resultat"] == "ok" and donnees["demarre"] == "detache"
    assert len(lancement.appels) == 1
    assert donnees["port"] == vivant


def test_port_qui_change_pendant_l_attente_est_suivi(faux, tmp_path, vivant):
    dossier = tmp_path / "cime"
    ecrire_port(dossier, mort())
    tours = []

    def dormir(_):
        tours.append(1)
        if len(tours) == 1:
            ecrire_port(dossier, mort())           # toujours mort, mais un autre port
        if len(tours) == 3:
            ecrire_port(dossier, vivant)           # le lanceur finit par répondre sur celui-ci

    donnees = appeler(dossier, Lancement(), dormir=dormir, delai_s=2)
    assert donnees["resultat"] == "ok" and donnees["port"] == vivant
    assert len(tours) == 3


def test_delai_depasse_erreur_et_pas_d_ouverture(faux, tmp_path):
    dossier = tmp_path / "cime"
    lancement = Lancement()
    donnees = appeler(dossier, lancement, delai_s=1)
    assert donnees == {
        "resultat": "erreur",
        "message": "Le lanceur ne répond pas après 1 s. Regarde ~/.cime/lanceur.log."}
    assert faux.appels() == []
    assert len(lancement.appels) == 1


def test_echec_au_demarrage_du_processus_est_une_erreur(tmp_path, faux):
    def leve(argv, **options):
        raise OSError("cime introuvable")
    donnees = appeler(tmp_path / "cime", leve)
    assert donnees["resultat"] == "erreur"
    assert "cime introuvable" in donnees["message"]
    assert faux.appels() == []


# --- le port habituel ----------------------------------------------------------------------

def test_port_effectif_different_du_reglage_le_dit(faux, tmp_path, vivant):
    dossier = tmp_path / "cime"
    ecrire_port(dossier, vivant)
    (dossier / "lanceur.json").write_text(json.dumps({"port": 5001}), encoding="utf-8")
    donnees = appeler(dossier, Lancement())
    assert (f"Le port habituel (5001) était pris : le lanceur est sur le port {vivant}."
            in donnees["phrases"])


def test_port_effectif_egal_au_reglage_pas_de_phrase(faux, tmp_path, vivant):
    dossier = tmp_path / "cime"
    ecrire_port(dossier, vivant)
    (dossier / "lanceur.json").write_text(json.dumps({"port": vivant}), encoding="utf-8")
    donnees = appeler(dossier, Lancement())
    assert not any("habituel" in p for p in donnees["phrases"])


# --- ouverture du navigateur ---------------------------------------------------------------

def test_open_echoue_url_en_phrase(faux, tmp_path, vivant, monkeypatch):
    monkeypatch.setenv("FAUX_OPEN", "echec")
    dossier = tmp_path / "cime"
    ecrire_port(dossier, vivant)
    donnees = appeler(dossier, Lancement())
    assert donnees["resultat"] == "erreur"
    assert f"Ouvre http://127.0.0.1:{vivant}/ dans ton navigateur." in donnees["message"]


def test_url_n_ouvre_pas_le_navigateur(faux, tmp_path, vivant):
    dossier = tmp_path / "cime"
    ecrire_port(dossier, vivant)
    donnees = appeler(dossier, Lancement(), url_seule=True)
    assert donnees["resultat"] == "ok"
    assert donnees["phrases"] == [f"http://127.0.0.1:{vivant}/"]
    assert faux.appels() == []


# --- la commande : texte, JSON, code de sortie (lanceur réel dans HOME/.cime) --------------

def _home_cime(vivant: int) -> Path:
    dossier = Path.home() / ".cime"
    ecrire_port(dossier, vivant)
    (dossier / "lanceur.json").write_text(json.dumps({"port": vivant}), encoding="utf-8")
    return dossier


def test_executer_texte_ouvre_et_dit(faux, vivant, capsys):
    _home_cime(vivant)
    assert mod.executer(argparse.Namespace(url=False, sortie_json=False)) == 0
    assert capsys.readouterr().out == "Le lanceur tournait déjà.\n"
    assert faux.appels() == [f"open http://127.0.0.1:{vivant}/"]


def test_executer_json_format_exact(faux, vivant, capsys):
    _home_cime(vivant)
    assert mod.executer(argparse.Namespace(url=False, sortie_json=True)) == 0
    sortie = capsys.readouterr().out
    assert len(sortie.splitlines()) == 1
    assert json.loads(sortie) == {
        "resultat": "ok", "url": f"http://127.0.0.1:{vivant}/", "port": vivant, "demarre": "deja"}


def test_executer_url_imprime_seulement_l_url(faux, vivant, capsys):
    _home_cime(vivant)
    assert mod.executer(argparse.Namespace(url=True, sortie_json=False)) == 0
    assert capsys.readouterr().out == f"http://127.0.0.1:{vivant}/\n"
    assert faux.appels() == []


def test_executer_open_echoue_code_1_et_url_en_phrase(faux, vivant, monkeypatch, capsys):
    monkeypatch.setenv("FAUX_OPEN", "echec")
    _home_cime(vivant)
    assert mod.executer(argparse.Namespace(url=False, sortie_json=False)) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"Ouvre http://127.0.0.1:{vivant}/ dans ton navigateur." in captured.err


def test_executer_erreur_en_json_et_en_texte(monkeypatch, capsys):
    monkeypatch.setattr(mod, "ouvrir_lanceur", lambda **kw: {
        "resultat": "erreur", "message": "Le lanceur ne répond pas après 20 s. Regarde ~/.cime/lanceur.log."})
    assert mod.executer(argparse.Namespace(url=False, sortie_json=True)) == 1
    sortie = capsys.readouterr().out
    assert json.loads(sortie) == {
        "resultat": "erreur", "message": "Le lanceur ne répond pas après 20 s. Regarde ~/.cime/lanceur.log."}
    assert mod.executer(argparse.Namespace(url=False, sortie_json=False)) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Le lanceur ne répond pas après 20 s. Regarde ~/.cime/lanceur.log.\n"


# --- la garde : réservé à l'utilisateur, comme `fermer` -----------------------------------

@pytest.mark.parametrize("env", [{"CIME_AGENT": "worker-x"}, {"CLAUDECODE": "1"}])
def test_agent_refuse_avec_la_garde_de_fermer(faux, monkeypatch, capsys, env):
    for cle, valeur in env.items():
        monkeypatch.setenv(cle, valeur)
    with pytest.raises(Echec) as e:
        _exiger_utilisateur("fermer")
    attendu = str(e.value).replace("fermer :", "ouvrir :", 1)
    assert mod.executer(argparse.Namespace(url=False, sortie_json=False)) == 1
    assert capsys.readouterr().err == attendu + "\n"
    assert faux.appels() == []


def test_agent_refuse_en_json(faux, monkeypatch, capsys):
    monkeypatch.setenv("CIME_AGENT", "worker-x")
    assert mod.executer(argparse.Namespace(url=False, sortie_json=True)) == 1
    donnees = json.loads(capsys.readouterr().out)
    assert donnees["resultat"] == "erreur" and donnees["message"].startswith("ouvrir : réservé")
    assert faux.appels() == []


# --- un test ne lance jamais un vrai lanceur (incident : 3 `cime lanceur` orphelins sur le port fixe) ---

def test_garde_qui_saute_ne_lance_aucun_vrai_lanceur(faux, monkeypatch):
    """La garde retirée + CIME_AGENT posé + aucun lanceur qui répond : sans filet, `executer` démarrait
    un vrai `cime lanceur` détaché. Le filet de conftest l'arrête avant qu'un processus parte."""
    monkeypatch.setenv("CIME_AGENT", "worker-x")
    monkeypatch.setattr(mod, "_exiger_utilisateur", lambda nom: None)
    with pytest.raises(AssertionError, match="un test a voulu lancer un vrai processus"):
        mod.executer(argparse.Namespace(url=False, sortie_json=False))
    assert faux.appels() == []                       # ni launchctl ni open


def test_le_demarrage_par_defaut_passe_par_le_filet(tmp_path):
    with pytest.raises(AssertionError, match="un test a voulu lancer un vrai processus"):
        mod.ouvrir_lanceur(dossier=tmp_path / "d", agent=tmp_path / "pas-d-agent.plist", cime="/x/cime",
                           dormir=lambda s: None, delai_s=1)


def test_un_vrai_open_est_refuse(vivant, tmp_path):
    ecrire_port(tmp_path / "d", vivant)              # le lanceur « répond » : on arrive jusqu'à `open`
    with pytest.raises(AssertionError, match="un test a voulu lancer un vrai open"):
        mod.ouvrir_lanceur(dossier=tmp_path / "d", agent=tmp_path / "pas-d-agent.plist")
