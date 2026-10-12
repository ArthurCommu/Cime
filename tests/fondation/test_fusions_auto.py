"""Fusions automatiques : la liste des chemins réservés (`est_reserve`, noyau + manifeste), l'empreinte,
l'état courant du réglage (registre jetable) et la commande `cime fusions-auto`. Jamais le registre
du vrai projet : `CIME_PROJET` et `CIME_AGENT` sont posés dans le test, sur un dossier jetable."""
import argparse
import hashlib
import json
import sqlite3
import textwrap

import pytest

from cime import cli
from cime.fondation import fusions_auto as fa
from cime.fondation.nom import VAR_AGENT, VAR_PROJET
from cime.fondation.projet import ErreurProjet
from cime.fondation.registre import ouvrir

MANIFESTE = textwrap.dedent("""\
    nom = "Essai"
    prefixe = "cc"
    branche_reference = "main"
    branche_equipe = "equipe/{equipe}"
    worktree_equipe = "../{depot}-{equipe}"
    equipes_speciales = ["assistant"]
    modele_assistant = "m"
    modele_coordinateur = "m"
""")

# (entrée du noyau, un chemin réservé, un chemin voisin qui ne l'est pas)
NOYAU_CAS = [
    (".claude/", ".claude/settings.json", "claude/settings.json"),
    (".orga/etat/", ".orga/etat/registre.sqlite", ".orga/etats/x"),
    (".env", ".env", "env"),
    (".env.*", ".env.local", ".envrc.md"),
    ("*.pem", "cles/serveur.pem", "cles/serveur.pem.md"),
    ("*.key", "a/b/c.key", "a/b/c.keys"),
    ("id_rsa*", "ssh/id_rsa.pub", "ssh/id_rsb"),
    ("id_ed25519*", "id_ed25519", "id_ed2551"),
    (".netrc", ".netrc", "netrc"),
    ("credentials*", "aws/credentials.json", "aws/cred.json"),
    (".orga/socle/", ".orga/socle/assistant.md", ".orga/socles/assistant.md"),
    (".orga/produit/", ".orga/produit/decisions-actees/x.md", ".orga/produits/x.md"),
    ("CLAUDE.md", "CLAUDE.md", "docs/CLAUDE.md"),
    (".orga/teams/*/CLAUDE.md", ".orga/teams/fondation/CLAUDE.md", ".orga/teams/fondation/x/CLAUDE.md"),
    (".orga/projet.toml", ".orga/projet.toml", ".orga/projet.toml.bak"),
    (".gitmodules", ".gitmodules", ".gitmodulesx"),
    (".github/", ".github/workflows/ci.yml", ".githubx/ci.yml"),
]
# Entrées qui ne sont plus dans le noyau : l'entrée, et un chemin qui n'est plus réservé
SORTIES = [
    (".orga/contracts/", ".orga/contracts/registre.schema.md"),
    (".orga/org-chart.md", ".orga/org-chart.md"),
    (".orga/dependencies.md", ".orga/dependencies.md"),
    (".orga/teams/*/mandate.md", ".orga/teams/page/mandate.md"),
    ("pyproject.toml", "pyproject.toml"),
    ("pyproject.toml", "sous/dossier/pyproject.toml"),
    ("uv.lock", "uv.lock"),
    ("package.json", "package.json"),
    ("package.json", "web/package.json"),
    ("package-lock.json", "package-lock.json"),
    ("pnpm-lock.yaml", "pnpm-lock.yaml"),
    ("yarn.lock", "yarn.lock"),
    ("requirements*.txt", "requirements-dev.txt"),
    ("Pipfile*", "Pipfile.lock"),
    ("Cargo.toml", "Cargo.toml"),
    ("Cargo.lock", "Cargo.lock"),
    ("go.mod", "go.mod"),
    ("go.sum", "go.sum"),
]
OFFRE = [
    # à n'importe quelle profondeur, pour les entrées sans `/` (hors CLAUDE.md)
    (".env", "a/b/.env"),
    ("id_rsa*", "x/y/id_rsa"),
    (".gitmodules", "sub/.gitmodules"),
]


def test_le_noyau_est_exactement_la_liste_attendue():
    assert len(fa.NOYAU) == len(set(fa.NOYAU)) == 17
    assert {c[0] for c in NOYAU_CAS} == set(fa.NOYAU)


@pytest.mark.parametrize("entree,chemin", SORTIES)
def test_les_entrees_sorties_du_noyau_n_y_sont_plus_et_ne_reservent_plus(entree, chemin):
    assert entree not in fa.NOYAU
    assert fa.est_reserve(chemin, fa.NOYAU) is False


def test_l_entree_redondante_des_reglages_generes_n_est_plus_listee():
    assert ".orga/etat/reglages/" not in fa.NOYAU
    assert fa.est_reserve(".orga/etat/reglages/w.json", fa.NOYAU) is True    # couverte par .orga/etat/


@pytest.mark.parametrize("entree,reserve,voisin", NOYAU_CAS, ids=[c[0] for c in NOYAU_CAS])
def test_chaque_ligne_du_noyau_reserve_son_chemin_et_pas_le_voisin(entree, reserve, voisin):
    assert fa.est_reserve(reserve, [entree]) is True
    assert fa.est_reserve(voisin, [entree]) is False
    # et le noyau entier, lui, reserve bien ce chemin
    assert fa.est_reserve(reserve, fa.NOYAU) is True


@pytest.mark.parametrize("entree,chemin", OFFRE)
def test_une_entree_sans_barre_vaut_a_toute_profondeur(entree, chemin):
    assert fa.est_reserve(chemin, [entree]) is True


def test_claude_md_n_est_reserve_qu_a_la_racine_mais_ceux_d_equipe_le_sont():
    assert fa.est_reserve("CLAUDE.md", fa.NOYAU)
    assert not fa.est_reserve("src/CLAUDE.md", fa.NOYAU)
    assert not fa.est_reserve(".orga/teams/CLAUDE.md", fa.NOYAU)
    assert fa.est_reserve(".orga/teams/page/CLAUDE.md", fa.NOYAU)


def test_formes_prefixe_joker_nom_nu_avec_le_manifeste():
    liste = ["src/cime/fondation/", "src/cime/hote/actions_*.py", "tests/signaux/"]
    assert fa.est_reserve("src/cime/fondation/garde.py", liste)
    assert fa.est_reserve("src/cime/fondation/a/b/c.py", liste)
    assert not fa.est_reserve("src/cime/fondation2/x.py", liste)            # préfixe : un segment entier
    assert not fa.est_reserve("src/cime/fondation.py", liste)
    assert fa.est_reserve("src/cime/hote/actions_utilisateur.py", liste)
    assert not fa.est_reserve("src/cime/hote/actions/utilisateur.py", liste)       # `*` ne franchit pas `/`
    assert not fa.est_reserve("src/cime/hote/autre.py", liste)
    assert not fa.est_reserve("src/cime/hote/actions_x.py.bak", liste)       # nom complet, pas un préfixe


def test_le_joker_ne_franchit_pas_la_barre():
    assert fa.est_reserve(".orga/teams/a/CLAUDE.md", fa.NOYAU)
    assert not fa.est_reserve(".orga/teams/a/b/CLAUDE.md", fa.NOYAU)
    assert not fa.est_reserve(".orga/teams/a/mandate.md", fa.NOYAU)


def test_un_dossier_est_reserve_comme_lui_meme():
    assert fa.est_reserve(".claude", [".claude/"])


@pytest.mark.parametrize("chemin", [".CLAUDE/settings.json", ".Env", "ID_RSA.pub",
                                    ".GitHub/workflows/x.yml"])
def test_la_casse_ne_contourne_pas(chemin):
    """Sur un disque macOS, `.Claude/` est `.claude/` : dans le doute, réservé."""
    assert fa.est_reserve(chemin, fa.NOYAU)


@pytest.mark.parametrize("chemin", ["", "/etc/passwd", "../x", "a/../.claude/x", "."])
def test_un_chemin_pas_net_est_reserve(chemin):
    assert fa.est_reserve(chemin, []) is True


def test_une_entree_inconnue_ne_reserve_rien_d_autre():
    assert fa.est_reserve("src/app.py", fa.NOYAU) is False
    assert fa.est_reserve("src/cime/fondation/garde.py", fa.NOYAU) is False   # propre au dépôt : manifeste


def test_empreinte_sha256_de_la_liste_triee_suivie_du_plafond():
    attendu = hashlib.sha256("a\nb\nc\nchantiers_par_jour=5".encode()).hexdigest()
    assert fa.empreinte(["c", "a", "b"], 5) == fa.empreinte(["a", "b", "c"], 5) == attendu
    assert fa.empreinte(["a", "b"], 5) != fa.empreinte(["a", "b", "c"], 5)


def test_le_plafond_fait_partie_de_l_empreinte():
    assert fa.empreinte(["a"], 5) != fa.empreinte(["a"], 6) != fa.empreinte(["a"], 0)


# --- chemins_reserves : noyau puis manifeste ---------------------------------------------

def _projet(tmp_path, extra=""):
    racine = tmp_path / "depot"
    (racine / ".orga").mkdir(parents=True)
    (racine / ".orga" / "projet.toml").write_text(MANIFESTE + extra)
    return racine


def test_chemins_reserves_sans_table_c_est_le_noyau(tmp_path):
    assert fa.chemins_reserves(_projet(tmp_path)) == list(fa.NOYAU)


def test_chemins_reserves_noyau_puis_manifeste_sans_doublon(tmp_path):
    p = _projet(tmp_path, '\n[fusions_auto]\nreserves = ["src/a/", ".env", "src/b/*.py", "src/a/"]\n')
    assert fa.chemins_reserves(p) == [*fa.NOYAU, "src/a/", "src/b/*.py"]


def test_le_manifeste_ne_retire_rien_du_noyau(tmp_path):
    p = _projet(tmp_path, '\n[fusions_auto]\nreserves = []\n')
    assert set(fa.NOYAU) <= set(fa.chemins_reserves(p))


@pytest.mark.parametrize("extra", ['\n[fusions_auto]\nreserves = "src/"\n',
                                   '\n[fusions_auto]\nreserves = [1]\n',
                                   '\n[fusions_auto]\nreserves = [""]\n',
                                   '\nfusions_auto = 3\n',
                                   '\n[fusions_auto\n'])
def test_manifeste_mal_forme_leve(tmp_path, extra):
    with pytest.raises(ErreurProjet):
        fa.chemins_reserves(_projet(tmp_path, extra))


def test_manifeste_absent_leve(tmp_path):
    with pytest.raises(ErreurProjet):
        fa.chemins_reserves(tmp_path / "rien")


# --- état courant et commande ------------------------------------------------------------

@pytest.fixture
def projet(tmp_path, monkeypatch):
    racine = _projet(tmp_path, '\n[fusions_auto]\nreserves = ["src/cime/fondation/"]\n')
    monkeypatch.setenv(VAR_PROJET, str(racine))
    monkeypatch.setenv(VAR_AGENT, "utilisateur")
    return racine


def _lancer(*arguments):
    return cli.main(["fusions-auto", *arguments])


def _lignes(projet):
    conn = ouvrir(projet)
    try:
        return conn.execute("SELECT id, horodatage, cle, valeur, auteur, details"
                            " FROM reglages_projet ORDER BY id").fetchall()
    finally:
        conn.close()


def test_registre_vierge_etat_inactif(projet):
    e = fa.etat_courant(projet)
    assert e == {"active": False, "suspendue": False, "depuis": None, "par": None,
                 "reserves": [], "empreinte": None, "reglage_id": None, "portee": None, "plafond": 5}


def test_lecture_sans_argument_inactive(projet, capsys):
    assert _lancer() == 0
    sortie = capsys.readouterr().out
    assert "fusions automatiques : inactive" in sortie
    assert "src/cime/fondation/" in sortie and ".orga/socle/" in sortie   # la liste actuelle
    assert ".orga/contracts/" not in sortie
    assert _lignes(projet) == []                                              # lire n'écrit rien


def test_lecture_permise_a_tout_agent(projet, monkeypatch, capsys):
    monkeypatch.setenv(VAR_AGENT, "assistant")
    assert _lancer() == 0
    monkeypatch.setenv(VAR_AGENT, "worker-x-t")
    assert _lancer() == 0
    monkeypatch.delenv(VAR_AGENT)
    assert _lancer() == 0


@pytest.mark.parametrize("agent", ["assistant", "coord-x", "worker-x-t", "", "l'utilisateur", "utilisateur2"])
@pytest.mark.parametrize("valeur", ["active", "inactive"])
def test_ecriture_refusee_a_tout_autre_qu_utilisateur(projet, monkeypatch, capsys, agent, valeur):
    monkeypatch.setenv(VAR_AGENT, agent)
    assert _lancer(valeur) == 1
    assert "seul l'utilisateur" in capsys.readouterr().err
    assert _lignes(projet) == []


def test_ecriture_refusee_sans_identite(projet, monkeypatch, capsys):
    monkeypatch.delenv(VAR_AGENT)
    assert _lancer("active") == 1
    assert _lignes(projet) == []


def test_activation_enregistre_liste_actuelle_et_empreinte(projet, capsys):
    assert _lancer("active") == 0
    assert capsys.readouterr().out.strip() == "1"
    [(ident, horo, cle, valeur, auteur, details)] = _lignes(projet)
    assert (ident, cle, valeur, auteur) == (1, "fusions_auto", "active", "utilisateur")
    assert horo.endswith("Z")
    d = json.loads(details)
    assert d["reserves"] == [*fa.NOYAU, "src/cime/fondation/"]
    assert d["empreinte"] == fa.empreinte(d["reserves"], 5)
    assert d["portee"] == 2 == fa.PORTEE and d["chantiers_par_jour"] == 5
    assert set(d) == {"reserves", "empreinte", "portee", "chantiers_par_jour"}
    e = fa.etat_courant(projet)
    assert (e["active"], e["suspendue"], e["par"], e["reglage_id"]) == (True, False, "utilisateur", 1)
    assert e["reserves"] == d["reserves"] and e["depuis"] == horo and e["empreinte"] == d["empreinte"]
    assert e["portee"] == 2 and e["plafond"] == 5


def test_deja_actif_et_deja_inactif(projet, capsys):
    assert _lancer("inactive") == 1
    assert "déjà inactif" in capsys.readouterr().err
    assert _lancer("active") == 0
    capsys.readouterr()
    assert _lancer("active") == 1
    assert "déjà actif" in capsys.readouterr().err
    assert len(_lignes(projet)) == 1


def test_desactivation_ajoute_une_ligne_et_garde_l_ancienne(projet, capsys):
    _lancer("active")
    avant = _lignes(projet)
    capsys.readouterr()
    assert _lancer("inactive") == 0
    assert capsys.readouterr().out.strip() == "2"
    lignes = _lignes(projet)
    assert lignes[0] == avant[0]                           # jamais modifiée
    assert lignes[1][3] == "inactive" and json.loads(lignes[1][5]) == {"avant": 1}
    assert fa.etat_courant(projet)["active"] is False
    assert _lancer("active") == 0                          # on peut la réactiver : ligne 3
    assert [l[0] for l in _lignes(projet)] == [1, 2, 3]


def test_etat_inactif_apres_desactivation_donne_la_liste_actuelle(projet, capsys):
    _lancer("active")
    _lancer("inactive")
    capsys.readouterr()
    assert _lancer() == 0
    assert "fusions automatiques : inactive" in capsys.readouterr().out


def test_lecture_active_donne_etat_date_auteur_et_liste_enregistree(projet, capsys):
    _lancer("active")
    capsys.readouterr()
    assert _lancer() == 0
    sortie = capsys.readouterr().out
    assert "fusions automatiques : active\n" in sortie
    assert "par utilisateur" in sortie
    assert "enregistrée à l'activation" in sortie and "src/cime/fondation/" in sortie


def _modifier_manifeste(projet, extra):
    (projet / ".orga" / "projet.toml").write_text(MANIFESTE + extra)


def test_manifeste_modifie_option_suspendue_et_reactivation_permise(projet, capsys):
    _lancer("active")
    _modifier_manifeste(projet, '\n[fusions_auto]\nreserves = ["src/cime/fondation/", "src/neuf/"]\n')
    e = fa.etat_courant(projet)
    assert e["active"] and e["suspendue"]
    assert "src/neuf/" not in e["reserves"]                  # la liste enregistrée, celle que l'utilisateur a vue
    capsys.readouterr()
    assert _lancer() == 0
    assert "active mais suspendue" in capsys.readouterr().out
    assert _lancer("active") == 0                            # revalider la liste : permis, valeur déjà `active`
    e = fa.etat_courant(projet)
    assert e["active"] and not e["suspendue"] and "src/neuf/" in e["reserves"]
    assert [l[3] for l in _lignes(projet)] == ["active", "active"]


def test_une_option_suspendue_se_desactive(projet, capsys):
    _lancer("active")
    _modifier_manifeste(projet, '\n[fusions_auto]\nreserves = []\n')
    assert fa.etat_courant(projet)["suspendue"]
    assert _lancer("inactive") == 0


def test_manifeste_illisible_apres_activation_suspend(projet):
    _lancer("active")
    (projet / ".orga" / "projet.toml").write_text("[ce n'est pas du toml")
    e = fa.etat_courant(projet)
    assert e["active"] and e["suspendue"]


def test_activation_avec_manifeste_illisible_echoue_sans_ligne(projet, capsys):
    (projet / ".orga" / "projet.toml").write_text("[pas du toml")
    assert cli.main(["fusions-auto", "active"]) == 1
    assert _lignes(projet) == []


# --- erreurs de lecture : toujours inactive, jamais d'exception -------------------------------

def test_registre_absent_inactif(tmp_path):
    assert fa.etat_courant(_projet(tmp_path))["active"] is False


def test_table_absente_inactif(tmp_path):
    p = _projet(tmp_path)
    (p / ".orga" / "etat").mkdir()
    conn = sqlite3.connect(p / ".orga" / "etat" / "registre.sqlite")
    conn.execute("CREATE TABLE messages (id INTEGER)")
    conn.commit()
    conn.close()
    assert fa.etat_courant(p)["active"] is False


def test_registre_illisible_inactif(tmp_path):
    p = _projet(tmp_path)
    (p / ".orga" / "etat").mkdir()
    (p / ".orga" / "etat" / "registre.sqlite").write_text("pas une base sqlite" * 50)
    assert fa.etat_courant(p)["active"] is False


@pytest.mark.parametrize("details", [None, "", "pas du json", "[]", '{"reserves": "x", "empreinte": "y"}',
                                     '{"reserves": ["a"]}', '{"empreinte": "y"}'])
def test_ligne_active_aux_details_inutilisables_inactif(projet, details):
    conn = ouvrir(projet)
    with conn:
        conn.execute("INSERT INTO reglages_projet (horodatage, cle, valeur, auteur, details)"
                     " VALUES ('2026-10-11T00:00:00.000Z', 'fusions_auto', 'active', 'utilisateur', ?)",
                     (details,))
    conn.close()
    assert fa.etat_courant(projet)["active"] is False


def test_la_valeur_courante_est_la_ligne_de_plus_grand_id(projet):
    conn = ouvrir(projet)
    d = json.dumps({"reserves": ["x"], "empreinte": fa.empreinte(["x"], 5), "portee": 2})
    with conn:
        conn.execute("INSERT INTO reglages_projet (id, horodatage, cle, valeur, auteur, details)"
                     " VALUES (5, 'h', 'fusions_auto', 'active', 'utilisateur', ?)", (d,))
        conn.execute("INSERT INTO reglages_projet (id, horodatage, cle, valeur, auteur, details)"
                     " VALUES (3, 'h', 'fusions_auto', 'inactive', 'utilisateur', '{}')")
        conn.execute("INSERT INTO reglages_projet (id, horodatage, cle, valeur, auteur, details)"
                     " VALUES (9, 'h', 'autre_cle', 'inactive', 'utilisateur', '{}')")
    conn.close()
    assert fa.etat_courant(projet)["reglage_id"] == 5


def test_la_commande_est_dans_le_parser_et_le_dispatch(projet):
    args = cli._parser().parse_args(["fusions-auto", "active"])
    assert args.valeur == "active"
    assert cli._parser().parse_args(["fusions-auto"]).valeur is None
    with pytest.raises(SystemExit):
        cli._parser().parse_args(["fusions-auto", "peut-etre"])


# --- gabarits : manifeste généré et socle ---------------------------------------------------------

def test_cime_init_recopie_la_table_fusions_auto_vide(tmp_path, monkeypatch):
    import types
    from cime.fondation import init
    monkeypatch.setattr(init, "executable_cime", lambda: "/opt/outils/bin/cime")
    p = tmp_path / "neuf"
    assert init.executer(types.SimpleNamespace(dossier=str(p), utilisateur="Camille",
                                               nom_projet=None, prefixe=None)) == 0
    toml = (p / ".orga" / "projet.toml").read_text()
    assert "[fusions_auto]\nreserves = []" in toml
    assert "\nchantiers_par_jour = 5" in toml
    assert "lancements automatiques de chantier par 24 h ; 0 = sans plafond" in toml
    assert fa.plafond_chantiers(p) == 5
    assert "Chemins que les fusions automatiques ne touchent jamais" in toml
    assert fa.chemins_reserves(p) == list(fa.NOYAU)          # une liste vide : le noyau seul
    socle = (p / ".orga" / "socle" / "assistant.md").read_text()
    assert "{{" not in socle and "`cime fusions-auto`" in socle
    assert "Mode autonome (option de l'utilisateur)" in socle


# --- plafond des lancements de chantier --------------------------------------------------------

@pytest.mark.parametrize("extra,attendu", [
    ("", 5),
    ("\n[fusions_auto]\nreserves = []\n", 5),
    ("\n[fusions_auto]\nchantiers_par_jour = 0\n", 0),
    ("\n[fusions_auto]\nchantiers_par_jour = 12\n", 12),
])
def test_plafond_chantiers_valeur_et_defaut(tmp_path, extra, attendu):
    assert fa.plafond_chantiers(_projet(tmp_path, extra)) == attendu


@pytest.mark.parametrize("valeur", ["-1", "true", "false", '"5"', "2.5", "[5]", "{a = 1}"])
def test_plafond_chantiers_invalide_leve(tmp_path, valeur):
    with pytest.raises(ErreurProjet):
        fa.plafond_chantiers(_projet(tmp_path, f"\n[fusions_auto]\nchantiers_par_jour = {valeur}\n"))


@pytest.mark.parametrize("extra", ["\n[fusions_auto\n", "\nfusions_auto = 3\n"])
def test_plafond_chantiers_manifeste_mal_forme_leve(tmp_path, extra):
    with pytest.raises(ErreurProjet):
        fa.plafond_chantiers(_projet(tmp_path, extra))


def test_plafond_chantiers_manifeste_absent_leve(tmp_path):
    with pytest.raises(ErreurProjet):
        fa.plafond_chantiers(tmp_path / "rien")


def test_les_reserves_restent_lisibles_avec_le_plafond(tmp_path):
    p = _projet(tmp_path, '\n[fusions_auto]\nreserves = ["src/a/"]\nchantiers_par_jour = 3\n')
    assert fa.chemins_reserves(p) == [*fa.NOYAU, "src/a/"]


# --- portée, plafond dans l'empreinte --------------------------------------------------------

def _activation_a_la_main(projet, details):
    conn = ouvrir(projet)
    with conn:
        conn.execute("INSERT INTO reglages_projet (horodatage, cle, valeur, auteur, details)"
                     " VALUES ('2026-10-12T00:00:00.000Z', 'fusions_auto', 'active', 'utilisateur', ?)",
                     (json.dumps(details),))
    conn.close()


def _details(projet, **en_plus):
    reserves = fa.chemins_reserves(projet)
    d = {"reserves": reserves, "empreinte": fa.empreinte(reserves, fa.plafond_chantiers(projet)),
         "portee": 2, "chantiers_par_jour": fa.plafond_chantiers(projet)}
    d.update(en_plus)
    return {k: v for k, v in d.items() if v is not ABSENT}


ABSENT = object()


def test_activation_a_la_main_complete_n_est_pas_suspendue(projet):
    _activation_a_la_main(projet, _details(projet))
    e = fa.etat_courant(projet)
    assert e["active"] and not e["suspendue"] and e["portee"] == 2


@pytest.mark.parametrize("portee", [ABSENT, None, 1, 0, -3, "2", 2.0, True, [2]])
def test_une_portee_manquante_ou_inferieure_a_2_suspend_meme_a_empreinte_identique(projet, portee):
    _activation_a_la_main(projet, _details(projet, portee=portee))
    e = fa.etat_courant(projet)
    assert e["active"] is True and e["suspendue"] is True


def test_une_portee_superieure_a_2_ne_suspend_pas(projet):
    _activation_a_la_main(projet, _details(projet, portee=3))
    e = fa.etat_courant(projet)
    assert e["suspendue"] is False and e["portee"] == 3


def test_portee_inconnue_donne_none(projet):
    _activation_a_la_main(projet, _details(projet, portee=ABSENT))
    assert fa.etat_courant(projet)["portee"] is None


def test_inactif_portee_none_mais_plafond_du_manifeste(projet):
    e = fa.etat_courant(projet)
    assert e["portee"] is None and e["plafond"] == 5


def test_modifier_le_plafond_suspend_et_reactiver_revalide(projet, capsys):
    _lancer("active")
    _modifier_manifeste(projet, '\n[fusions_auto]\nreserves = ["src/cime/fondation/"]\nchantiers_par_jour = 9\n')
    e = fa.etat_courant(projet)
    assert e["active"] and e["suspendue"] and e["plafond"] == 9
    assert _lancer("active") == 0
    e = fa.etat_courant(projet)
    assert not e["suspendue"] and e["plafond"] == 9
    assert json.loads(_lignes(projet)[-1][5])["chantiers_par_jour"] == 9


def test_plafond_illisible_apres_activation_suspend(projet):
    _lancer("active")
    _modifier_manifeste(projet, '\n[fusions_auto]\nchantiers_par_jour = "x"\n')
    e = fa.etat_courant(projet)
    assert e["active"] and e["suspendue"] and e["plafond"] is None


def test_activation_avec_plafond_invalide_echoue_sans_ligne(projet):
    _modifier_manifeste(projet, '\n[fusions_auto]\nchantiers_par_jour = -2\n')
    assert _lancer("active") == 1
    assert _lignes(projet) == []


# --- lancements automatiques des 24 dernières heures -------------------------------------------

from datetime import datetime, timedelta, timezone

NOW = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _annonce(projet, objet, *, de="assistant", a="utilisateur", nature="rapport_utilisateur", clos_il_y_a=None,
             auteur="cime", etat="clos", maintenant=NOW):
    """Un message et, si `clos_il_y_a`, une transition `etat` par `auteur` datée de NOW - clos_il_y_a."""
    conn = ouvrir(projet)
    with conn:
        ident = conn.execute(
            "INSERT INTO messages (horodatage, de, a, nature, resume, objet) VALUES (?, ?, ?, ?, 'r', ?)",
            (_iso(maintenant - timedelta(days=3)), de, a, nature, objet)).lastrowid
        if clos_il_y_a is not None:
            conn.execute("INSERT INTO transitions (horodatage, message_id, etat, auteur, preuve)"
                         " VALUES (?, ?, ?, ?, '{}')",
                         (_iso(maintenant - clos_il_y_a), ident, etat, auteur))
    conn.close()
    return ident


H = timedelta(hours=1)


def test_lancements_comptent_les_annonces_de_chantier_closes_par_cime_dans_les_24_h(projet):
    _annonce(projet, "chantier-auto:a:1", clos_il_y_a=2 * H)
    _annonce(projet, "chantier-auto:b:1", clos_il_y_a=23 * H)
    assert fa.lancements_auto_24h(projet, NOW) == 2 == fa.lancements_auto_24h_strict(projet, NOW)


@pytest.mark.parametrize("kw", [
    dict(clos_il_y_a=25 * H),                       # trop ancien
    dict(clos_il_y_a=None),                         # non consommé
    dict(clos_il_y_a=H, auteur="assistant"),        # clos par un autre que cime
    dict(clos_il_y_a=H, etat="livre"),              # autre transition
    dict(clos_il_y_a=H, de="coord-x"),              # pas de l'Assistant
    dict(clos_il_y_a=H, a="assistant"),             # pas à l'utilisateur
    dict(clos_il_y_a=H, nature="signalement"),      # pas un rapport_utilisateur
])
def test_lancements_ne_comptent_pas(projet, kw):
    _annonce(projet, "chantier-auto:a:1", **kw)
    assert fa.lancements_auto_24h(projet, NOW) == 0
    assert fa.lancements_auto_24h_strict(projet, NOW) == 0


@pytest.mark.parametrize("objet", ["fusion-auto:a:" + "0" * 40, "contrat-auto:x", "autorisation-auto:3",
                                   "chantier:a:1", "Chantier-auto:a:1", "x chantier-auto:a:1", None])
def test_lancements_ne_comptent_que_le_prefixe_chantier_auto(projet, objet):
    _annonce(projet, objet, clos_il_y_a=H)
    assert fa.lancements_auto_24h(projet, NOW) == 0


def test_lancements_frontiere_des_24_h(projet):
    _annonce(projet, "chantier-auto:a:1", clos_il_y_a=24 * H + timedelta(seconds=1))
    _annonce(projet, "chantier-auto:b:1", clos_il_y_a=24 * H - timedelta(seconds=1))
    assert fa.lancements_auto_24h(projet, NOW) == 1


def test_lancements_un_message_a_plusieurs_transitions_compte_une_fois(projet):
    ident = _annonce(projet, "chantier-auto:a:1", clos_il_y_a=H)
    conn = ouvrir(projet)
    with conn:
        conn.execute("INSERT INTO transitions (horodatage, message_id, etat, auteur, preuve)"
                     " VALUES (?, ?, 'clos', 'cime', '{}')", (_iso(NOW - 2 * H), ident))
    conn.close()
    assert fa.lancements_auto_24h(projet, NOW) == 1


def test_lancements_sans_argument_utilise_l_heure_courante(projet):
    conn = ouvrir(projet)
    with conn:
        ident = conn.execute("INSERT INTO messages (horodatage, de, a, nature, resume, objet)"
                             " VALUES (?, 'assistant', 'utilisateur', 'rapport_utilisateur', 'r', 'chantier-auto:a:1')",
                             (_iso(datetime.now(timezone.utc)),)).lastrowid
        conn.execute("INSERT INTO transitions (horodatage, message_id, etat, auteur, preuve)"
                     " VALUES (?, ?, 'clos', 'cime', '{}')", (_iso(datetime.now(timezone.utc)), ident))
    conn.close()
    assert fa.lancements_auto_24h(projet) == 1 == fa.lancements_auto_24h_strict(projet)


def _registre_illisible(p):
    (p / ".orga" / "etat").mkdir(exist_ok=True)
    (p / ".orga" / "etat" / "registre.sqlite").write_text("pas une base sqlite" * 50)


def _table_absente(p):
    (p / ".orga" / "etat").mkdir(exist_ok=True)
    conn = sqlite3.connect(p / ".orga" / "etat" / "registre.sqlite")
    conn.execute("CREATE TABLE journal (id INTEGER)")
    conn.commit()
    conn.close()


@pytest.mark.parametrize("abimer", [lambda p: None, _registre_illisible, _table_absente],
                         ids=["registre-absent", "illisible", "table-absente"])
def test_lancements_lecture_en_erreur_donne_0_mais_la_version_stricte_leve(tmp_path, abimer):
    p = _projet(tmp_path)
    abimer(p)
    assert fa.lancements_auto_24h(p, NOW) == 0                  # jamais d'exception
    with pytest.raises(ErreurProjet):
        fa.lancements_auto_24h_strict(p, NOW)                   # une erreur de lecture vaut refus


# --- cime fusions-auto : portée, plafond, lancements -----------------------------------------------

def test_lecture_inactive_affiche_plafond_et_zero_lancement(projet, capsys):
    assert _lancer() == 0
    sortie = capsys.readouterr().out
    assert "lancements automatiques de chantier : 0 sur 5" in sortie
    assert "portée" not in sortie


def test_lecture_active_affiche_portee_plafond_et_lancements(projet, capsys):
    _modifier_manifeste(projet, '\n[fusions_auto]\nchantiers_par_jour = 3\n')
    _lancer("active")
    _annonce(projet, "chantier-auto:a:1", clos_il_y_a=H, maintenant=datetime.now(timezone.utc))
    capsys.readouterr()
    assert _lancer() == 0
    sortie = capsys.readouterr().out
    assert "portée : 2" in sortie
    assert "lancements automatiques de chantier : 1 sur 3" in sortie


def test_lecture_plafond_zero_se_dit_sans_plafond(projet, capsys):
    _modifier_manifeste(projet, '\n[fusions_auto]\nchantiers_par_jour = 0\n')
    assert _lancer() == 0
    assert "lancements automatiques de chantier : 0 (sans plafond)" in capsys.readouterr().out


def test_lecture_suspendue_par_portee_le_dit(projet, capsys):
    _activation_a_la_main(projet, _details(projet, portee=ABSENT))
    assert _lancer() == 0
    sortie = capsys.readouterr().out
    assert "active mais suspendue" in sortie and "portée" in sortie


def test_lecture_avec_registre_illisible_ne_leve_pas(tmp_path, monkeypatch, capsys):
    p = _projet(tmp_path)
    _registre_illisible(p)
    monkeypatch.setenv(VAR_PROJET, str(p))
    assert _lancer() == 0
    assert "lancements automatiques de chantier" in capsys.readouterr().out
