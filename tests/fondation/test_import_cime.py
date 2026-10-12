"""`cime` doit s'importer sous le bac à sable de tout agent, et l'échec doit se voir."""
import json
import sqlite3
import textwrap
from pathlib import Path

import pytest

from cime.fondation import lancer
from cime.fondation.lancer import Refus
from cime.fondation.nom import VAR_AGENT, VAR_PROJET
from cime.fondation.reglages import bac_a_sable
from cime.signaux import hooks

HOME = Path("/opt/x")
PROJET = HOME / "Projets" / "autre"
IDENTITES = ("coord-equipe", "worker-equipe-tache", "worker-integration-r1")


def lectures(source, outil=None, identite="coord-equipe"):
    contenu = lancer.construire_reglages(
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
    source = lancer.dossier_source_cime()
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
    assert lancer.import_cime_non_lisible(bac_, src / "cime", [str(src)]) == []
    lancer.verifier_import_cime(bac_, src / "cime", [str(src)])


def test_controle_refuse_quand_allow_read_ne_couvre_pas(tmp_path):
    src = tmp_path / "src"
    (src / "cime").mkdir(parents=True)
    bac_ = {"filesystem": {"allowRead": [str(tmp_path / "autre")], "denyRead": [str(tmp_path)]}}
    assert lancer.import_cime_non_lisible(bac_, src / "cime", [str(src), "/n/existe/pas"]) == [src]
    with pytest.raises(Refus) as e:
        lancer.verifier_import_cime(bac_, src / "cime", [str(src)])
    assert str(src) in str(e.value)
    assert "n'est pas couverte par les lectures de l'agent" in str(e.value)
    assert "uv tool" in str(e.value)


def test_hors_deny_read_la_lecture_est_libre(tmp_path):
    src = tmp_path / "src"
    (src / "cime").mkdir(parents=True)
    bac_ = {"filesystem": {"allowRead": [], "denyRead": ["/opt/jamais"]}}
    assert lancer.import_cime_non_lisible(bac_, src / "cime", [str(src)]) == []


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


ERREUR = "Traceback (most recent call last):\nModuleNotFoundError: No module named 'cime'\n"


@pytest.mark.parametrize("entree", [
    {"tool_name": "Bash", "tool_response": {"stdout": "", "stderr": ERREUR}},
    {"tool_name": "Bash", "tool_response": ERREUR},
    {"tool_name": "Bash", "error": f"Exit code 1\n{ERREUR}"},
    {"tool_name": "Bash", "tool_response": {"stderr": "ImportError: cannot import name 'x' from 'cime.y'"}},
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
    entree = {"tool_name": "Bash", "tool_response": {"stderr": ERREUR}}
    hooks.sur_import_cime_manquant(conn, racine, "coord-essai", entree)
    assert hooks.sur_import_cime_manquant(conn, racine, "coord-essai", entree) == []
    assert len(signalements(conn)) == 2
    # un autre agent a son propre signalement
    hooks.sur_import_cime_manquant(conn, racine, "coord-autre", entree)
    assert len(signalements(conn)) == 4


def test_au_dela_d_une_heure_un_nouveau_signalement(registre):
    racine, conn = registre
    entree = {"tool_name": "Bash", "tool_response": {"stderr": ERREUR}}
    hooks.sur_import_cime_manquant(conn, racine, "coord-essai", entree)
    with conn:
        conn.execute("UPDATE messages SET horodatage = '2020-01-01T00:00:00.000Z'")
    hooks.sur_import_cime_manquant(conn, racine, "coord-essai", entree)
    assert len(signalements(conn)) == 4


@pytest.mark.parametrize("entree", [
    {"tool_name": "Bash", "tool_response": {"stdout": "ok", "stderr": ""}},
    {"tool_name": "Bash", "tool_response": {"stderr": "ModuleNotFoundError: No module named 'requests'"}},
    {"tool_name": "Bash", "tool_response": {"stderr": "ModuleNotFoundError: No module named 'cimex'"}},
    {"tool_name": "Bash", "tool_response": {"stdout": "j'aime le cime"}},
    {"tool_name": "Read"},
])
def test_sortie_ordinaire_ou_autre_paquet_rien(registre, entree):
    racine, conn = registre
    assert hooks.sur_import_cime_manquant(conn, racine, "coord-essai", entree) == []
    assert signalements(conn) == []


@pytest.mark.parametrize("evenement", ["PostToolUse", "PostToolUseFailure"])
def test_le_hook_cable_les_deux_evenements(registre, monkeypatch, evenement):
    import argparse, io, sys
    from cime.fondation import hook
    racine, conn = registre
    monkeypatch.setenv(VAR_AGENT, "coord-essai")
    entree = {"tool_name": "Bash", "error": ERREUR, "tool_response": {"stderr": ERREUR}}
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
