"""La fenêtre de terminal de `rouvrir` (iTerm, sinon Terminal) et le réglage `terminal`.
Aucun test n'ouvre de vraie fenêtre : `lancer` est toujours un faux."""
import json
import os
import stat
from types import SimpleNamespace

from cime.lanceur.fenetre import ouvrir_fenetre
from cime.lanceur.serveur import Contexte

CONTENU = ('#!/bin/zsh\nexport PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"\n'
           "exec tmux attach -t p-alpha-assistant\n")


class Lancer:
    """Faux `subprocess.run` : enregistre les argv, répond selon `iterm` et `open_ok`."""

    def __init__(self, iterm=True, open_ok=True, leve=None):
        self.appels, self.iterm, self.open_ok, self.leve = [], iterm, open_ok, leve

    def __call__(self, argv, **kwargs):
        self.appels.append(list(argv))
        if self.leve:
            raise self.leve
        if argv[:3] == ["open", "-Ra", "iTerm"]:
            return SimpleNamespace(returncode=0 if self.iterm else 1)
        return SimpleNamespace(returncode=0 if self.open_ok else 1)


def reglages(dossier, **valeurs):
    (dossier / "lanceur.json").write_text(json.dumps(valeurs), encoding="utf-8")


def test_script_contenu_mode_et_ouverture(tmp_path):
    lancer = Lancer()
    assert ouvrir_fenetre(tmp_path, "p-alpha-assistant", terminal="iTerm", lancer=lancer) is True
    script = tmp_path / "fenetres" / "p-alpha-assistant.command"
    assert script.read_text(encoding="utf-8") == CONTENU
    assert stat.S_IMODE(script.stat().st_mode) == 0o700
    assert lancer.appels == [["open", "-a", "iTerm", str(script)]]


def test_terminal_du_reglage_sans_detection(tmp_path):
    reglages(tmp_path, terminal="Terminal", utilisateur="Camille")
    lancer = Lancer()
    assert ouvrir_fenetre(tmp_path, "p-alpha-assistant", lancer=lancer) is True
    assert lancer.appels == [["open", "-a", "Terminal", str(tmp_path / "fenetres" / "p-alpha-assistant.command")]]


def test_argument_terminal_l_emporte_sur_le_reglage(tmp_path):
    reglages(tmp_path, terminal="Terminal")
    lancer = Lancer()
    ouvrir_fenetre(tmp_path, "p-alpha-assistant", terminal="iTerm", lancer=lancer)
    assert lancer.appels[-1][:3] == ["open", "-a", "iTerm"]


def test_iterm_absent_donne_terminal(tmp_path):
    lancer = Lancer(iterm=False)
    assert ouvrir_fenetre(tmp_path, "p-alpha-assistant", lancer=lancer) is True
    assert lancer.appels[0] == ["open", "-Ra", "iTerm"]
    assert lancer.appels[-1][:3] == ["open", "-a", "Terminal"]


def test_iterm_present_donne_iterm(tmp_path):
    lancer = Lancer(iterm=True)
    ouvrir_fenetre(tmp_path, "p-alpha-assistant", lancer=lancer)
    assert lancer.appels[-1][:3] == ["open", "-a", "iTerm"]


def test_session_invalide_faux_et_rien_n_est_ecrit(tmp_path):
    lancer = Lancer()
    for session in ["", "a/b", "p;rm", "x y", "é", "a\n"]:
        assert ouvrir_fenetre(tmp_path, session, terminal="iTerm", lancer=lancer) is False
    assert lancer.appels == []
    assert not (tmp_path / "fenetres").exists()


def test_echec_de_open_faux(tmp_path):
    assert ouvrir_fenetre(tmp_path, "p-alpha-assistant", terminal="iTerm", lancer=Lancer(open_ok=False)) is False


def test_exception_faux_sans_lever(tmp_path):
    assert ouvrir_fenetre(tmp_path, "p-alpha-assistant", terminal="iTerm",
                          lancer=Lancer(leve=OSError("pas de open"))) is False


def test_aucun_osascript(tmp_path):
    lancer = Lancer(iterm=False)
    ouvrir_fenetre(tmp_path, "p-alpha-assistant", lancer=lancer)
    ouvrir_fenetre(tmp_path, "p-beta-assistant", terminal="Terminal", lancer=lancer)
    assert lancer.appels and all(argv[0] != "osascript" for argv in lancer.appels)


def test_fenetre_du_contexte_passe_par_la_fonction(tmp_path, monkeypatch):
    vus = []

    def faux(dossier, session, terminal=None, lancer=None):
        vus.append((dossier, session))
        return True
    monkeypatch.setattr("cime.lanceur.serveur.ouvrir_fenetre", faux)
    assert Contexte(tmp_path, [], None).fenetre("p-alpha-assistant") is True
    assert vus == [(tmp_path, "p-alpha-assistant")]


# ── garder_utilisateur fusionne le réglage au lieu de l'écraser ─────────────────────────

def test_garder_utilisateur_conserve_terminal_et_autres_cles(tmp_path):
    reglages(tmp_path, terminal="iTerm", autre=[1, 2])
    Contexte(tmp_path, [], None).garder_utilisateur("Camille")
    lu = json.loads((tmp_path / "lanceur.json").read_text(encoding="utf-8"))
    assert lu == {"terminal": "iTerm", "autre": [1, 2], "utilisateur": "Camille"}
    assert not os.path.exists(tmp_path / "lanceur.json.tmp")


def test_garder_utilisateur_sans_fichier_cree_le_reglage(tmp_path):
    Contexte(tmp_path, [], None).garder_utilisateur("Camille")
    assert json.loads((tmp_path / "lanceur.json").read_text(encoding="utf-8")) == {"utilisateur": "Camille"}
