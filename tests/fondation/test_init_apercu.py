"""`cime init --apercu` : le plan de `init`, sans rien écrire."""
import json
import os
import subprocess
import types
from pathlib import Path

import pytest

from cime import cli
from cime.fondation import init
from cime.fondation.nom import VAR_AGENT

EXE = "/opt/outils/bin/cime"


@pytest.fixture(autouse=True)
def cime_installe(monkeypatch):
    monkeypatch.setattr(init, "executable_cime", lambda: EXE)
    for var in (VAR_AGENT, "CLAUDECODE"):
        monkeypatch.delenv(var, raising=False)


def args(dossier, utilisateur="Camille", nom_projet=None, prefixe=None, **autres):
    return types.SimpleNamespace(dossier=str(dossier), utilisateur=utilisateur,
                                 nom_projet=nom_projet, prefixe=prefixe, **autres)


def arbre(racine: Path) -> dict:
    """Tout ce qui existe sous `racine` : chemin -> (type, mode, octets)."""
    etat = {}
    if not os.path.lexists(racine):
        return {"<absent>": None}
    for chemin in [racine, *sorted(racine.rglob("*"))]:
        relatif = str(chemin.relative_to(racine))
        if chemin.is_symlink():
            etat[relatif] = ("lien", os.readlink(chemin))
        elif chemin.is_dir():
            etat[relatif] = ("dossier", chemin.stat().st_mode)
        else:
            etat[relatif] = ("fichier", chemin.stat().st_mode, chemin.read_bytes())
    return etat


def apercu_json(capsys, dossier, *plus):
    code = cli.main(["init", "--apercu", str(dossier), "--json", *plus])
    sortie = capsys.readouterr()
    return code, sortie.out, sortie.err


def depot_git(chemin: Path):
    chemin.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(chemin)], check=True)


def etat_absent(base):
    return base / "projet"


def etat_vide(base):
    d = base / "projet"
    d.mkdir()
    return d


def etat_claude_et_reglages(base):
    d = base / "projet"
    (d / ".claude").mkdir(parents=True)
    (d / "CLAUDE.md").write_text("# à moi\n")
    (d / ".claude" / "settings.json").write_text(json.dumps({
        "permissions": {"allow": ["Bash(make *)"], "deny": ["Read(/secrets/**)"]}}))
    (d / ".gitignore").write_text("*.pyc\n")
    return d


def etat_deja_initialise(base):
    d = base / "projet"
    init.installer(args(d))
    return d


def etat_dans_un_depot_parent(base):
    depot_git(base / "depot")
    return base / "depot" / "sous" / "projet"


ETATS = [etat_absent, etat_vide, etat_claude_et_reglages, etat_deja_initialise,
         etat_dans_un_depot_parent]


# --- ne rien écrire ---------------------------------------------------------------------------

@pytest.mark.parametrize("etat", ETATS, ids=lambda f: f.__name__)
def test_apercu_n_ecrit_rien_octet_pour_octet(tmp_path, capsys, etat):
    dossier = etat(tmp_path)
    avant_dossier, avant_parent = arbre(dossier), arbre(dossier.parent)
    code, sortie, _ = apercu_json(capsys, dossier)
    assert code == 0
    json.loads(sortie)
    assert arbre(dossier) == avant_dossier
    assert arbre(dossier.parent) == avant_parent


def test_dossier_absent_n_est_pas_cree(tmp_path, capsys):
    dossier = tmp_path / "pas" / "encore" / "la"
    code, _, _ = apercu_json(capsys, dossier)
    assert code == 0
    assert not (tmp_path / "pas").exists()


def test_apercu_sans_git_init_ni_registre_ni_reglages_ni_gitignore(tmp_path, capsys):
    dossier = etat_vide(tmp_path)
    apercu_json(capsys, dossier)
    assert list(dossier.iterdir()) == []


def test_apercu_n_appelle_pas_installer(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(init, "installer", lambda *a, **k: pytest.fail("installer appelé"))
    code, _, _ = apercu_json(capsys, tmp_path / "x")
    assert code == 0


# --- la forme ---------------------------------------------------------------------------------

def test_forme_json(tmp_path, capsys):
    code, sortie, _ = apercu_json(capsys, tmp_path / "mon-projet")
    donnees = json.loads(sortie)
    assert code == 0
    assert set(donnees) == {"nom", "commit", "cree", "complete", "garde"}
    assert donnees["nom"] == "mon-projet"
    assert donnees["commit"] is False
    assert "CLAUDE.md" in donnees["cree"]
    assert ".claude/settings.json" in donnees["cree"]
    assert donnees["complete"] == [] and donnees["garde"] == []


def test_nom_projet_retenu(tmp_path, capsys):
    _, sortie, _ = apercu_json(capsys, tmp_path / "dossier", "--nom-projet", "Autre nom")
    assert json.loads(sortie)["nom"] == "Autre nom"


def test_commit_est_faux_et_init_ne_commite_pas(tmp_path, capsys):
    dossier = tmp_path / "p"
    _, sortie, _ = apercu_json(capsys, dossier)
    assert json.loads(sortie)["commit"] is False
    init.installer(args(dossier))
    r = subprocess.run(["git", "-C", str(dossier), "rev-list", "--all", "--count"],
                       capture_output=True, text=True)
    assert r.stdout.strip() == "0"


def test_garde_rend_claude_md_et_les_regles_de_l_utilisateur(tmp_path, capsys):
    dossier = etat_claude_et_reglages(tmp_path)
    _, sortie, _ = apercu_json(capsys, dossier)
    donnees = json.loads(sortie)
    assert "CLAUDE.md" in donnees["garde"]
    assert "CLAUDE.md" not in donnees["cree"]
    assert any(g.startswith(".claude/settings.json") and "utilisateur" in g
               for g in donnees["garde"])
    assert any(c.startswith(".claude/settings.json") for c in donnees["complete"])
    assert any(c.startswith(".gitignore") for c in donnees["complete"])


def test_sortie_texte_lisible(tmp_path, capsys):
    dossier = etat_claude_et_reglages(tmp_path)
    code = cli.main(["init", "--apercu", str(dossier)])
    sortie = capsys.readouterr().out
    assert code == 0
    assert "projet" in sortie
    assert "CLAUDE.md" in sortie
    assert "créerait" in sortie.lower() and "garde" in sortie.lower()
    assert not sortie.lstrip().startswith("{")


# --- cohérence avec `init` --------------------------------------------------------------------

@pytest.mark.parametrize("etat", ETATS, ids=lambda f: f.__name__)
def test_cree_egale_ce_que_init_ajoute(tmp_path, capsys, etat):
    dossier = etat(tmp_path)
    _, sortie, _ = apercu_json(capsys, dossier)
    donnees = json.loads(sortie)
    rapport = init.installer(args(dossier))
    assert donnees["cree"] == rapport["ajouté"]
    assert donnees["complete"] == [ligne for ligne in rapport["complété"]
                                   if not ligne.startswith("  ")]
    assert set(rapport["déjà présent"]) <= set(donnees["garde"])


def test_projet_deja_initialise_ne_cree_rien(tmp_path, capsys):
    dossier = etat_deja_initialise(tmp_path)
    _, sortie, _ = apercu_json(capsys, dossier)
    donnees = json.loads(sortie)
    assert donnees["cree"] == [] and donnees["complete"] == []
    assert "CLAUDE.md" in donnees["garde"]


def test_le_plan_est_partage(tmp_path, monkeypatch):
    """`installer` passe par le plan, il n'a pas le sien."""
    appels = []
    vrai = init.planifier
    monkeypatch.setattr(init, "planifier",
                        lambda *a, **k: appels.append(1) or vrai(*a, **k))
    init.installer(args(tmp_path / "p"))
    assert appels == [1]


def test_apercu_dans_un_depot_parent_annonce_le_depot_propre(tmp_path, capsys):
    dossier = etat_dans_un_depot_parent(tmp_path)
    _, sortie, _ = apercu_json(capsys, dossier)
    assert any(c.startswith(".git (dépôt propre") for c in json.loads(sortie)["cree"])


# --- options ----------------------------------------------------------------------------------

def test_utilisateur_pas_exige_avec_apercu(tmp_path, capsys):
    code = cli.main(["init", "--apercu", str(tmp_path / "x")])
    capsys.readouterr()
    assert code == 0


def test_utilisateur_reste_exige_sans_apercu(tmp_path, capsys):
    try:
        code = cli.main(["init", str(tmp_path / "x")])
    except SystemExit as e:
        code = e.code
    capsys.readouterr()
    assert code == 2
    assert not (tmp_path / "x").exists()


@pytest.mark.parametrize("option", ["--lancer", "--migrer"])
def test_apercu_refuse_lancer_et_migrer(tmp_path, capsys, option):
    dossier = etat_vide(tmp_path)
    avant = arbre(tmp_path)
    code = cli.main(["init", "--apercu", str(dossier), option])
    sortie = capsys.readouterr()
    assert code == 2
    assert "apercu" in sortie.err
    assert arbre(tmp_path) == avant


def test_cime_introuvable_ne_fait_pas_echouer_l_apercu(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(init, "executable_cime", lambda: None)
    dossier = tmp_path / "p"
    code, sortie, _ = apercu_json(capsys, dossier)
    assert code == 0
    assert "CLAUDE.md" in json.loads(sortie)["cree"]
    assert not dossier.exists()


def test_cime_introuvable_fait_toujours_echouer_init(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(init, "executable_cime", lambda: None)
    code = cli.main(["init", str(tmp_path / "p"), "--utilisateur", "C"])
    capsys.readouterr()
    assert code == 2 and not (tmp_path / "p").exists()


def test_prefixe_invalide_refuse_code_2(tmp_path, capsys):
    code = cli.main(["init", "--apercu", str(tmp_path / "p"), "--prefixe", "NON valide"])
    assert code == 2
    assert "préfixe invalide" in capsys.readouterr().err


def test_reglages_illisibles_refuses_avant_toute_ecriture(tmp_path, capsys):
    dossier = etat_vide(tmp_path)
    (dossier / ".claude").mkdir()
    (dossier / ".claude" / "settings.json").write_text("{pas du json")
    avant = arbre(dossier)
    with pytest.raises(init.ErreurInit):
        init.installer(args(dossier))
    assert arbre(dossier) == avant
    code, _, err = apercu_json(capsys, dossier)
    assert code == 2 and "settings.json" in err
