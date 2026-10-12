"""`init --migrer` : retirer de settings.json les interdits réservés aux agents d'équipe."""
import json
import types
from pathlib import Path

import pytest

from cime.fondation import init
from cime.fondation.reglages import reglages

EXE = "/opt/outils/bin/cime"
A_LA_MAIN = "Bash(rm -rf build*)"


@pytest.fixture(autouse=True)
def cime_installe(monkeypatch):
    monkeypatch.setattr(init, "executable_cime", lambda: EXE)


def args(dossier, migrer=False):
    return types.SimpleNamespace(dossier=str(dossier), utilisateur="Camille", nom_projet=None,
                                 prefixe=None, migrer=migrer)


def agent_seules(projet: Path) -> list[str]:
    agent = reglages(projet, "main", "agent")["permissions"]["deny"]
    commun = reglages(projet, "main", "commun")["permissions"]["deny"]
    return [r for r in agent if r not in commun]


def ancien_projet(tmp_path: Path) -> Path:
    """Projet installé, puis settings.json réécrit comme un `init` d'avant la répartition :
    les règles agent-seules y sont, avec une règle ajoutée à la main au milieu."""
    p = tmp_path / "x"
    init.executer(args(p))
    cible = p / ".claude" / "settings.json"
    donnees = json.loads(cible.read_text())
    seules = agent_seules(p)
    deny = donnees["permissions"]["deny"]
    deny = deny[:2] + seules[:3] + [A_LA_MAIN] + seules[3:] + deny[2:]
    donnees["permissions"]["deny"] = deny
    donnees["cle_inconnue"] = {"garde": 1}
    cible.write_text(json.dumps(donnees, indent=2) + "\n")
    return p


def deny_de(p: Path) -> list[str]:
    return json.loads((p / ".claude" / "settings.json").read_text())["permissions"]["deny"]


def test_regles_agent_seules_incluent_branches_osascript_et_merge(tmp_path):
    seules = agent_seules(tmp_path)
    assert "Bash(git branch -D*)" in seules and "Bash(rtk git branch -D*)" in seules
    assert "Bash(osascript *)" in seules and "Bash(rtk osascript *)" in seules
    assert f"Bash(git -C {tmp_path.resolve()} merge*)" in seules
    assert not [r for r in seules if r.startswith("Bash(security")]


def test_migrer_retire_les_regles_agent_et_garde_la_main(tmp_path, capsys):
    p = ancien_projet(tmp_path)
    avant = deny_de(p)
    assert set(agent_seules(p)) & set(avant)
    capsys.readouterr()

    assert init.executer(args(p, migrer=True)) == 0

    apres = deny_de(p)
    assert A_LA_MAIN in apres
    assert not set(agent_seules(p)) & set(apres)
    # Seules les règles agent-seules ont disparu, l'ordre du reste est conservé.
    assert apres == [r for r in avant if r not in set(agent_seules(p))]
    # Le reste du fichier est intact.
    assert json.loads((p / ".claude" / "settings.json").read_text())["cle_inconnue"] == \
        {"garde": 1}
    sortie = capsys.readouterr().out
    for regle in set(avant) & set(agent_seules(p)):
        assert f"retiré : permissions.deny : {regle}" in sortie
    assert f"retiré : permissions.deny : {A_LA_MAIN}" not in sortie


def test_migrer_est_idempotent(tmp_path, capsys):
    p = ancien_projet(tmp_path)
    init.executer(args(p, migrer=True))
    apres_premier = (p / ".claude" / "settings.json").read_text()
    capsys.readouterr()

    assert init.executer(args(p, migrer=True)) == 0

    assert (p / ".claude" / "settings.json").read_text() == apres_premier
    sortie = capsys.readouterr().out
    assert "rien à migrer" in sortie and "retiré" not in sortie


def test_init_seul_avertit_et_ne_retire_rien(tmp_path, capsys):
    p = ancien_projet(tmp_path)
    avant = (p / ".claude" / "settings.json").read_text()
    capsys.readouterr()

    assert init.executer(args(p)) == 0

    assert (p / ".claude" / "settings.json").read_text() == avant
    sortie = capsys.readouterr().out
    assert "règles à migrer : lance `cime init --migrer`" in sortie
    assert "retiré" not in sortie


def test_projet_propre_pas_d_avertissement(tmp_path, capsys):
    p = tmp_path / "x"
    init.executer(args(p))
    capsys.readouterr()
    assert init.executer(args(p, migrer=True)) == 0
    sortie = capsys.readouterr().out
    assert "règles à migrer" not in sortie
    assert "rien à migrer" in sortie


def test_migrer_apres_migration_plus_d_avertissement(tmp_path, capsys):
    p = ancien_projet(tmp_path)
    init.executer(args(p, migrer=True))
    capsys.readouterr()
    init.executer(args(p))
    assert "règles à migrer" not in capsys.readouterr().out


def test_settings_illisible_reste_une_erreur(tmp_path, capsys):
    p = tmp_path / "x"
    init.executer(args(p))
    (p / ".claude" / "settings.json").write_text("{pas du json")
    assert init.executer(args(p, migrer=True)) == 2
    assert "n'est pas du JSON valide" in capsys.readouterr().err
    assert (p / ".claude" / "settings.json").read_text() == "{pas du json"


# --- Bash(tmux *) n'est plus pré-approuvé (tmux est fermé à tous les agents par la garde) -------

TMUX = "Bash(tmux *)"


@pytest.mark.parametrize("role", sorted(__import__("cime.fondation.reglages", fromlist=["ROLES"]).ROLES))
def test_reglages_generes_sans_tmux_pre_approuve(tmp_path, role):
    assert TMUX not in reglages(tmp_path, "main", role)["permissions"]["allow"]


def test_init_n_ecrit_pas_tmux_dans_allow(tmp_path):
    p = tmp_path / "x"
    init.executer(args(p))
    for f in (p / ".claude").glob("settings*.json"):
        assert TMUX not in json.loads(f.read_text())["permissions"]["allow"], f.name


def test_migrer_retire_tmux_de_l_allow_et_rien_d_autre(tmp_path):
    p = tmp_path / "x"
    init.executer(args(p))
    cible = p / ".claude" / "settings.json"
    donnees = json.loads(cible.read_text())
    a_la_main = "Bash(make *)"
    donnees["permissions"]["allow"] = [TMUX, *donnees["permissions"]["allow"], a_la_main]
    cible.write_text(json.dumps(donnees, indent=2) + "\n")
    attendu = dict(donnees, permissions=dict(donnees["permissions"],
                                             allow=donnees["permissions"]["allow"][1:]))
    assert init.executer(args(p, migrer=True)) == 0
    assert json.loads(cible.read_text()) == attendu
    avant = cible.read_text()
    assert init.executer(args(p, migrer=True)) == 0                       # deuxième passage : sans effet
    assert cible.read_text() == avant
