"""`cime` doit s'importer sous le bac à sable de tout agent, et l'échec doit se voir."""
import json
import sqlite3
import textwrap
from pathlib import Path

import pytest

from cime.fondation import lancer
from cime.fondation import reglages as reglages_mod
from cime.fondation.lancer import Refus
from cime.fondation.nom import VAR_AGENT, VAR_PROJET
from cime.fondation.reglages import bac_a_sable
from cime.signaux import hooks

HOME = Path("/opt/x")
PROJET = HOME / "Projets" / "autre"
IDENTITES = ("coord-equipe", "worker-equipe-tache", "worker-integration-r1")


def lectures(source, outil=None, identite="coord-equipe"):
    contenu = reglages_mod.construire_reglages(
        {}, PROJET, identite, [], HOME, 501, [PROJET], outil, source=source)
    return contenu["sandbox"]["filesystem"]["allowRead"]


# --- 1. la source réelle est lue --------------------------------------------------------

@pytest.mark.parametrize("identite", IDENTITES)
def test_editable_source_hors_projet_ajoutee_une_fois(identite):
    source = Path("/Volumes/depots/cime/src")
    assert lectures(source, identite=identite).count(str(source)) == 1


@pytest.mark.parametrize("identite", IDENTITES)
def test_non_editable_site_packages_ajoute(identite):
    source = HOME / "venvs" / "lib" / "python3.12" / "site-packages"
    assert str(source) in lectures(source, identite=identite)


@pytest.mark.parametrize("identite", IDENTITES)
def test_source_dans_le_projet_rien_d_ajoute(identite):
    assert lectures(PROJET / "src", identite=identite) == lectures(None, identite=identite)


@pytest.mark.parametrize("identite", IDENTITES)
@pytest.mark.parametrize("source", [HOME, HOME.parent, Path("/")])
def test_source_maison_ou_parent_jamais_ajoutee(identite, source):
    assert lectures(source, identite=identite) == lectures(None, identite=identite)


def test_source_deja_couverte_par_l_outil_pas_de_doublon():
    outil = HOME / ".local" / "share" / "uv" / "tools" / "cime"
    source = outil / "lib" / "python3.12" / "site-packages"
    assert lectures(source, outil) == lectures(None, outil)


def test_la_source_n_ajoute_aucune_ecriture():
    avec = bac_a_sable(PROJET, [], HOME, 501, [PROJET], None, Path("/Volumes/c/src"))
    sans = bac_a_sable(PROJET, [], HOME, 501, [PROJET])
    assert avec["sandbox"]["filesystem"]["allowWrite"] == sans["sandbox"]["filesystem"]["allowWrite"]


def test_dossier_source_cime_est_le_dossier_d_import_reel():
    import cime
    source = reglages_mod.dossier_source_cime()
    if source is not None:
        assert (source / "cime").resolve() == Path(next(iter(cime.__path__))).resolve()


# --- 2. autotest : fonction pure ---------------------------------------------------------

def bac(allow):
    return {"filesystem": {"allowRead": allow, "denyRead": [str(HOME)]}}


def test_controle_passe_quand_allow_read_couvre(tmp_path):
    src = tmp_path / "src"
    (src / "cime").mkdir(parents=True)
    maison = tmp_path
    bac_ = {"filesystem": {"allowRead": [str(src)], "denyRead": [str(maison)]}}
    assert reglages_mod.import_cime_non_lisible(bac_, src / "cime", [str(src)]) == []
    reglages_mod.verifier_import_cime(bac_, src / "cime", [str(src)])


def test_controle_refuse_quand_allow_read_ne_couvre_pas(tmp_path):
    src = tmp_path / "src"
    (src / "cime").mkdir(parents=True)
    bac_ = {"filesystem": {"allowRead": [str(tmp_path / "autre")], "denyRead": [str(tmp_path)]}}
    assert reglages_mod.import_cime_non_lisible(bac_, src / "cime", [str(src), "/n/existe/pas"]) == [src]
    with pytest.raises(Refus) as e:
        reglages_mod.verifier_import_cime(bac_, src / "cime", [str(src)])
    assert str(src) in str(e.value)
    assert "n'est pas couverte par les lectures de l'agent" in str(e.value)
    assert "uv tool" in str(e.value)


def test_hors_deny_read_la_lecture_est_libre(tmp_path):
    src = tmp_path / "src"
    (src / "cime").mkdir(parents=True)
    bac_ = {"filesystem": {"allowRead": [], "denyRead": ["/opt/jamais"]}}
    assert reglages_mod.import_cime_non_lisible(bac_, src / "cime", [str(src)]) == []


# --- 3. le hook voit l'échec -------------------------------------------------------------

@pytest.fixture
def registre(tmp_path, monkeypatch):
    from cime.fondation import registre as reg
    racine = tmp_path / "depot"
    (racine / ".orga").mkdir(parents=True)
    (racine / ".orga" / "projet.toml").write_text(textwrap.dedent("""\
        nom = "Essai"
        prefixe = "cc"
        branche_reference = "main"
        branche_equipe = "equipe/{equipe}"
        worktree_equipe = "../{depot}-{equipe}"
        equipes_speciales = ["assistant"]
        modele_assistant = "m"
        modele_coordinateur = "m"
    """))
    monkeypatch.setenv(VAR_PROJET, str(racine))
    conn = reg.ouvrir(racine)
    yield racine, conn
    conn.close()


def signalements(conn):
    return conn.execute("SELECT a, nature, objet, resume FROM messages WHERE de = 'cime'"
                        " AND objet LIKE 'import-cime:%' ORDER BY id").fetchall()


PY = {"tool_input": {"command": "python -c 'import cime'"}}
ERREUR = "Traceback (most recent call last):\nModuleNotFoundError: No module named 'cime'\n"


@pytest.mark.parametrize("entree", [
    {"tool_name": "Bash", **PY, "tool_response": {"stdout": "", "stderr": ERREUR}},
    {"tool_name": "Bash", **PY, "tool_response": ERREUR},
    {"tool_name": "Bash", **PY, "error": f"Exit code 1\n{ERREUR}"},
    # le paquet lui-même illisible sous le bac à sable (dossier ou `cime/__init__.py`)
    {"tool_name": "Bash", **PY, "tool_response": {"stderr": "PermissionError: [Errno 1] Operation not "
                                                      "permitted: '/opt/x/src/cime/__init__.py'"}},
    {"tool_name": "Bash", **PY, "error": "PermissionError: [Errno 1] Operation not permitted: '/opt/x/src/cime'"},
    {"tool_name": "Bash", **PY, "tool_response": {"stderr": "ImportError: [Errno 1] Operation not permitted: "
                                                      "'/opt/x/src/cime/__init__.py'"}},
])
def test_echec_d_import_inscrit_un_signalement_par_destinataire(registre, entree):
    racine, conn = registre
    hooks.sur_import_cime_manquant(conn, racine, "coord-essai", entree)
    lignes = signalements(conn)
    assert [(l[0], l[1], l[2]) for l in lignes] == [
        ("assistant", "signalement", "import-cime:coord-essai"),
        ("utilisateur", "signalement", "import-cime:coord-essai")]
    assert all(len(l[3]) <= 160 and "coord-essai" in l[3] and "cime" in l[3] for l in lignes)


def test_meme_erreur_repetee_pas_de_second_signalement(registre):
    racine, conn = registre
    entree = {"tool_name": "Bash", **PY, "tool_response": {"stderr": ERREUR}}
    hooks.sur_import_cime_manquant(conn, racine, "coord-essai", entree)
    assert hooks.sur_import_cime_manquant(conn, racine, "coord-essai", entree) == []
    assert len(signalements(conn)) == 2
    # un autre agent a son propre signalement
    hooks.sur_import_cime_manquant(conn, racine, "coord-autre", entree)
    assert len(signalements(conn)) == 4


def test_au_dela_d_une_heure_un_nouveau_signalement(registre):
    racine, conn = registre
    entree = {"tool_name": "Bash", **PY, "tool_response": {"stderr": ERREUR}}
    hooks.sur_import_cime_manquant(conn, racine, "coord-essai", entree)
    with conn:
        conn.execute("UPDATE messages SET horodatage = '2020-01-01T00:00:00.000Z'")
    hooks.sur_import_cime_manquant(conn, racine, "coord-essai", entree)
    assert len(signalements(conn)) == 4


@pytest.mark.parametrize("entree", [
    {"tool_name": "Bash", **PY, "tool_response": {"stdout": "ok", "stderr": ""}},
    {"tool_name": "Bash", **PY, "tool_response": {"stderr": "ModuleNotFoundError: No module named 'requests'"}},
    {"tool_name": "Bash", **PY, "tool_response": {"stderr": "ModuleNotFoundError: No module named 'cimex'"}},
    {"tool_name": "Bash", **PY, "tool_response": {"stdout": "j'aime le cime"}},
    {"tool_name": "Read", **PY},
    # un test rouge écrit avant son module : pas une panne d'installation
    {"tool_name": "Bash", **PY, "tool_response": {"stderr": "ImportError: cannot import name 'x' from 'cime.y'"}},
    {"tool_name": "Bash", **PY, "tool_response": {"stdout": "E   ImportError: cannot import name 'plafond' "
                                                      "from 'cime.fondation' (/opt/x/src/cime/fondation/"
                                                      "__init__.py)"}},
    {"tool_name": "Bash", **PY, "tool_response": {"stdout": "E   ImportError: cannot import name 'y' from "
                                                      "'cime' (/opt/x/src/cime/__init__.py)"}},
    {"tool_name": "Bash", **PY, "tool_response": {"stdout": "ModuleNotFoundError: No module named 'cime.nouveau'"}},
    {"tool_name": "Bash", **PY, "tool_response": {"stdout": "ModuleNotFoundError: No module named "
                                                      "'cime.fondation.nouveau'"}},
    {"tool_name": "Bash", **PY, "error": "PermissionError: [Errno 1] Operation not permitted: "
                                   "'/opt/x/src/cime/fondation/x.py'"},
])
def test_sortie_ordinaire_ou_autre_paquet_rien(registre, entree):
    racine, conn = registre
    assert hooks.sur_import_cime_manquant(conn, racine, "coord-essai", entree) == []
    assert signalements(conn) == []


# --- 4. seule la sortie d'un programme Python compte --------------------------------------

def avec(commande, sortie=ERREUR, outil="Bash"):
    entree = {"tool_name": outil, "tool_response": {"stdout": sortie}}
    if commande is not None:
        entree["tool_input"] = {"command": commande}
    return entree


@pytest.mark.parametrize("commande", [
    "python -c \"import cime\"",
    ".venv/bin/python -m pytest tests/x -k y",
    "uv run python x.py",
    "uv tool run pytest",
    "uvx pytest",
    "cd d && python3 x.py",
    "PYTHONPATH=x python3 -m cime reprise",
    "env X=1 pytest",
    "/usr/bin/python3 x.py 2>&1 | tail -5",
    "ls; time nice -n 5 python x.py",
    "cd d && (exec .venv/bin/python3.12 x.py)",
    "false || coverage run x.py",
    "pip install -e .",
    "pipx run x",
    "py.test -q",
    "nohup command pytest",
])
def test_une_commande_python_alerte(registre, commande):
    racine, conn = registre
    assert len(hooks.sur_import_cime_manquant(conn, racine, "coord-essai", avec(commande))) == 2


@pytest.mark.parametrize("commande", [
    "cat fichier", "sed -n 1,5p f", "grep -n x f", "echo \"python x\"", "git log", "ls -la",
    "printf 'python' | head", "find . -name python", "awk '{print}' f", "rg python", "tail -3 f",
    "cd python && cat f", "X=python cat f", "cat python", "less pytest.ini", "git -C pytest log",
    "", None, 'echo "non fermé', {"pas": "une chaîne"},
])
def test_une_commande_qui_n_est_pas_python_n_alerte_pas(registre, commande):
    racine, conn = registre
    assert hooks.sur_import_cime_manquant(conn, racine, "coord-essai", avec(commande)) == []
    assert signalements(conn) == []


@pytest.mark.parametrize("outil", ["Read", "Grep", "Glob", "Edit", "Task"])
def test_un_autre_outil_qu_un_bash_n_alerte_pas(registre, outil):
    racine, conn = registre
    assert hooks.sur_import_cime_manquant(
        conn, racine, "coord-essai", avec("python x.py", outil=outil)) == []


def test_commande_absente_ou_entree_illisible_n_alerte_pas(registre):
    racine, conn = registre
    for entree in (avec(None), {"tool_name": "Bash", "tool_input": None, "tool_response": ERREUR},
                   {"tool_name": "Bash", "tool_input": "python x", "tool_response": ERREUR}):
        assert hooks.sur_import_cime_manquant(conn, racine, "coord-essai", entree) == []


MESSAGE_CITE = "Reçu de l'Assistant : « l'import a levé No module named 'cime' hier »\n"
PANNE_CIME = "Traceback (most recent call last):\n  File \"/x/bin/cime\", line 3\n" \
             "ModuleNotFoundError: No module named 'cime'\n"


def test_cime_qui_affiche_un_message_cite_n_alerte_pas(registre):
    racine, conn = registre
    assert hooks.sur_import_cime_manquant(
        conn, racine, "coord-essai", avec("cime reprise", MESSAGE_CITE)) == []


def test_cime_qui_ne_s_importe_pas_alerte(registre):
    racine, conn = registre
    assert len(hooks.sur_import_cime_manquant(
        conn, racine, "coord-essai", avec("cime reprise", PANNE_CIME))) == 2


def test_cime_dans_un_pipe_qui_affiche_un_message_cite_n_alerte_pas(registre):
    racine, conn = registre
    assert hooks.sur_import_cime_manquant(
        conn, racine, "coord-essai", avec("cime reprise | cat", MESSAGE_CITE)) == []


@pytest.fixture
def garde_cassee(monkeypatch):
    import sys
    from cime.fondation import garde  # noqa: F401  (chargé avant d'être masqué)
    monkeypatch.setitem(sys.modules, "cime.fondation.garde", None)  # `import` lève ImportError


def test_garde_non_importable_l_alerte_fonctionne_sur_la_commande_brute(registre, garde_cassee):
    racine, conn = registre
    assert len(hooks.sur_import_cime_manquant(
        conn, racine, "coord-essai", avec("cd d && python3 x.py"))) == 2


def test_garde_non_importable_une_commande_non_python_n_alerte_pas(registre, garde_cassee):
    racine, conn = registre
    assert hooks.sur_import_cime_manquant(conn, racine, "coord-essai", avec("cat f")) == []


@pytest.mark.parametrize("evenement", ["PostToolUse", "PostToolUseFailure"])
def test_le_hook_cable_les_deux_evenements(registre, monkeypatch, evenement):
    import argparse, io, sys
    from cime.fondation import hook
    racine, conn = registre
    monkeypatch.setenv(VAR_AGENT, "coord-essai")
    entree = {"tool_name": "Bash", **PY, "error": ERREUR, "tool_response": {"stderr": ERREUR}}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(entree)))
    assert hook.executer(argparse.Namespace(evenement=evenement)) == 0
    assert len(signalements(conn)) == 2


def test_post_tool_use_failure_est_cable():
    from cime.fondation import hook
    from cime.fondation.reglages import EVENEMENTS, reglages
    assert "PostToolUseFailure" in EVENEMENTS and "PostToolUseFailure" in hook.CHAMPS
    assert "PostToolUseFailure" in reglages(Path("/opt/x/projet"), "main", "agent")["hooks"]


# --- 5. petits points --------------------------------------------------------------------

def test_refus_option_avant_la_sous_commande_donne_la_forme_attendue():
    from cime.fondation import garde
    assert "`cime <sous-commande> --help`" in garde.M_CIME_OPTION
    assert "`cime <sous-commande> <options>`" in garde.M_CIME_OPTION
