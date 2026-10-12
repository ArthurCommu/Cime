"""Lecture de la structure d'un projet : manifeste, étapes, équipes, mandats, dépendances, clôture."""

from pathlib import Path

import pytest

from cime.observation.structure import lire_equipes, lire_projet

FIXTURES = Path(__file__).parent / "fixtures"

MANIFESTE = """\
nom = "Projet exemple"
prefixe = "cc"
branche_reference = "main"
branche_equipe = "equipe/{equipe}"
worktree_equipe = "../{depot}-{equipe}"
equipes_speciales = ["assistant", "integration", "verification"]
modele_assistant = "claude-opus-5-5"
modele_coordinateur = "claude-opus-5-5"
"""


def fabrique(tmp_path, manifeste=MANIFESTE, nom="monprojet"):
    racine = tmp_path / nom
    (racine / ".orga" / "teams").mkdir(parents=True)
    if manifeste is not None:
        (racine / ".orga" / "projet.toml").write_text(manifeste, encoding="utf-8")
    return racine


def equipe(racine, nom, mandat="# Mandat\n", tasks=True):
    d = racine / ".orga" / "teams" / nom
    d.mkdir(parents=True, exist_ok=True)
    (d / "mandate.md").write_text(mandat, encoding="utf-8")
    if tasks:
        for s in ("todo", "in-progress", "done"):
            (d / "tasks" / s).mkdir(parents=True, exist_ok=True)
    return d


def test_manifeste_complet(tmp_path):
    racine = fabrique(tmp_path)
    projet, source = lire_projet(racine)
    assert source == {"nom": "manifeste", "ok": True}
    assert projet == {
        "nom": "Projet exemple", "racine": str(racine.resolve()), "prefixe": "cc",
        "branche_reference": "main", "branche_equipe": "equipe/{equipe}",
        "worktree_equipe": "../{depot}-{equipe}",
        "equipes_speciales": ["assistant", "integration", "verification"],
        "modele_assistant": "claude-opus-5-5", "modele_coordinateur": "claude-opus-5-5",
        "etapes": None,
    }


@pytest.mark.parametrize("cle", ["nom", "prefixe", "branche_reference", "branche_equipe", "worktree_equipe"])
def test_cle_manquante_nomme_la_cle(tmp_path, cle):
    texte = "\n".join(l for l in MANIFESTE.splitlines() if not l.startswith(cle + " "))
    projet, source = lire_projet(fabrique(tmp_path, texte))
    assert projet is None
    assert source["ok"] is False and f"`{cle}`" in source["erreur"]


def test_manifeste_absent_ou_illisible(tmp_path):
    projet, source = lire_projet(fabrique(tmp_path, manifeste=None))
    assert projet is None and "projet.toml" in source["erreur"]
    projet, source = lire_projet(fabrique(tmp_path, "ceci n'est pas = = du toml", nom="autre"))
    assert projet is None and source["ok"] is False
    projet, source = lire_projet(tmp_path / "inexistant")
    assert projet is None and source["ok"] is False


def test_cle_inconnue_ignoree(tmp_path):
    projet, source = lire_projet(fabrique(tmp_path, MANIFESTE + 'couleur = "rouge"\n'))
    assert source["ok"] is True and "couleur" not in projet


def test_etapes_avec_lignes_parasites(tmp_path):
    racine = fabrique(tmp_path)
    (racine / ".orga" / "etapes.md").write_text(
        "# Étapes\n\nIntro.\n"
        "- [x] Cadrage (atteinte le 2026-10-07)\n"
        "- [ ] Maquette validée\n"
        "- [x] Sans date\n"
        "* [ ] mauvaise puce\n"
        "- [X] majuscule\n"
        "  - [ ] indentée\n"
        "- [ ] Dernière\n",
        encoding="utf-8",
    )
    projet, _ = lire_projet(racine)
    assert projet["etapes"] == [
        {"nom": "Cadrage", "atteinte": True, "date": "2026-10-07"},
        {"nom": "Maquette validée", "atteinte": False, "date": None},
        {"nom": "Dernière", "atteinte": False, "date": None},
    ]


def test_equipe_normale_et_speciale(tmp_path):
    racine = fabrique(tmp_path)
    projet, _ = lire_projet(racine)
    equipe(racine, "alpha")
    equipe(racine, "verification")
    equipes, source = lire_equipes(racine, projet)
    assert source == {"nom": "equipes", "ok": True}
    alpha, verif = equipes
    assert alpha["nom"] == "alpha" and alpha["speciale"] is False
    assert alpha["branche"] == "equipe/alpha"
    assert alpha["worktree"] == str(racine.resolve().parent / "monprojet-alpha")
    assert verif["speciale"] is True and verif["branche"] is None and verif["worktree"] is None


def test_equipe_cloturee(tmp_path):
    racine = fabrique(tmp_path)
    projet, _ = lire_projet(racine)
    d = equipe(racine, "alpha")
    equipe(racine, "beta")
    (d / "CLOTUREE").write_text("", encoding="utf-8")
    equipes, _ = lire_equipes(racine, projet)
    assert {e["nom"]: e["cloturee"] for e in equipes} == {"alpha": True, "beta": False}


def test_tasks_absent_vaut_none_et_dossier_absent_vaut_zero(tmp_path):
    racine = fabrique(tmp_path)
    projet, _ = lire_projet(racine)
    equipe(racine, "sans", tasks=False)
    d = equipe(racine, "avec", tasks=False)
    (d / "tasks" / "in-progress").mkdir(parents=True)
    (d / "tasks" / "in-progress" / "t1-a.md").write_text("x")
    (d / "tasks" / "in-progress" / "t2-b.md").write_text("x")
    (d / "tasks" / "done").mkdir()
    (d / "tasks" / "done" / "t0.md").write_text("x")
    equipes, _ = lire_equipes(racine, projet)
    par = {e["nom"]: e for e in equipes}
    assert par["sans"]["avancement"] is None and par["sans"]["taches_en_cours"] is None
    assert par["avec"]["avancement"] == {"faites": 1, "en_cours": 2, "a_faire": 0}
    assert par["avec"]["taches_en_cours"] == ["t1-a", "t2-b"]


def test_socle_et_dossiers_sans_mandat_ecartes(tmp_path):
    racine = fabrique(tmp_path)
    projet, _ = lire_projet(racine)
    equipe(racine, "socle")
    equipe(racine, "alpha")
    (racine / ".orga" / "teams" / "sansmandat").mkdir()
    (racine / ".orga" / "socle").mkdir()
    equipes, _ = lire_equipes(racine, projet)
    assert [e["nom"] for e in equipes] == ["alpha"]


def test_teams_absent_est_une_erreur(tmp_path):
    racine = tmp_path / "vide"
    racine.mkdir()
    equipes, source = lire_equipes(racine, {"branche_equipe": "e/{equipe}", "worktree_equipe": "../{equipe}"})
    assert equipes is None and source["ok"] is False


def test_mandat_mission_et_perimetre(tmp_path):
    racine = fabrique(tmp_path)
    projet, _ = lire_projet(racine)
    d = equipe(racine, "alpha", tasks=False)
    (d / "mandate.md").write_text((FIXTURES / "mandate_alpha.md").read_text(encoding="utf-8"), encoding="utf-8")
    equipes, _ = lire_equipes(racine, projet)
    obs = equipes[0]
    assert obs["mission"].startswith("construire. À partir de ce qu'un projet laisse comme traces (manifeste,")
    assert obs["mission"].endswith("qui travaille et les alarmes.")
    assert "**" not in obs["mission"] and "Mission de cette équipe" not in obs["mission"]
    assert obs["perimetre_declare"] == ["src/exemple/", "tests/exemple/"]


def test_mandat_sans_scope_ni_bloc2(tmp_path):
    racine = fabrique(tmp_path)
    projet, _ = lire_projet(racine)
    equipe(racine, "alpha", mandat="# Mandat\nrien\n")
    equipes, _ = lire_equipes(racine, projet)
    assert equipes[0]["mission"] is None and equipes[0]["perimetre_declare"] is None


def test_mission_sans_prefixe(tmp_path):
    racine = fabrique(tmp_path)
    projet, _ = lire_projet(racine)
    equipe(racine, "alpha", mandat="## Bloc 2 — Position\n\n**Faire** des choses.\nSuite\n")
    equipes, _ = lire_equipes(racine, projet)
    assert equipes[0]["mission"] == "Faire des choses. Suite"


def test_dependances_lues_dans_un_fichier_d_exemple(tmp_path):
    racine = fabrique(tmp_path)
    projet, _ = lire_projet(racine)
    for n in ("alpha", "beta", "gamma", "delta", "epsilon"):
        equipe(racine, n)
    equipes, _ = lire_equipes(racine, projet)
    assert all(e["depend_de"] is None for e in equipes)  # fichier absent
    (racine / ".orga" / "dependencies.md").write_text(
        (FIXTURES / "dependencies.md").read_text(encoding="utf-8"), encoding="utf-8")
    equipes, _ = lire_equipes(racine, projet)
    assert {e["nom"]: e["depend_de"] for e in equipes} == {
        "alpha": [],
        "beta": ["gamma", "alpha"],  # dans l'ordre de la phrase
        "gamma": ["alpha"],
        "delta": ["beta"],  # « bêta » (accent) reconnu comme `beta`, « l'utilisateur » ignoré
        "epsilon": [],  # pas de section
    }


def test_dependances_mots_entiers_sans_doublon(tmp_path):
    racine = fabrique(tmp_path)
    projet, _ = lire_projet(racine)
    for n in ("a", "pagex", "page"):
        equipe(racine, n)
    (racine / ".orga" / "dependencies.md").write_text(
        "## a\nDépend de : pagex, page, pagex-bis et page.\n", encoding="utf-8")
    equipes, _ = lire_equipes(racine, projet)
    assert equipes[0]["depend_de"] == ["pagex", "page"]


def test_scope_sur_deux_lignes_sans_jeton_non_chemin(tmp_path):
    racine = fabrique(tmp_path)
    projet, _ = lire_projet(racine)
    d = equipe(racine, "beta")
    (d / "mandate.md").write_text((FIXTURES / "mandate_beta.md").read_text(encoding="utf-8"), encoding="utf-8")
    equipes, _ = lire_equipes(racine, projet)
    assert equipes[0]["perimetre_declare"] == [
        "pyproject.toml", "src/exemple/cli.py", "src/exemple/modele/", "tests/modele/"]


def test_dependance_sur_ligne_coupee_et_sans_accents(tmp_path):
    racine = fabrique(tmp_path)
    projet, _ = lire_projet(racine)
    equipe(racine, "hote")
    equipe(racine, "page")
    (racine / ".orga" / "dependencies.md").write_text(
        "## page\nDépend de : l'utilisateur (validation) pour la phase 2 ; Hôte\n(API) pour le branchement.\nStatut : LIBRE\n",
        encoding="utf-8")
    equipes, _ = lire_equipes(racine, projet)
    assert {e["nom"]: e["depend_de"] for e in equipes}["page"] == ["hote"]


def test_cloturee_le_lu_dans_cloturee(tmp_path):
    # Contenu au format écrit par l'hôte (actions_cloture.py) ; heure fabriquée.
    racine = fabrique(tmp_path)
    projet, _ = lire_projet(racine)
    d = equipe(racine, "alpha")
    equipe(racine, "beta")
    vide = equipe(racine, "gamma")
    (d / "CLOTUREE").write_text("auteur: utilisateur\nheure: 2026-10-07T21:12:03.456Z\ndemande: 12\nrapport: 14\n",
                               encoding="utf-8")
    (vide / "CLOTUREE").write_text("", encoding="utf-8")
    equipes, _ = lire_equipes(racine, projet)
    assert {e["nom"]: e["cloturee_le"] for e in equipes} == {
        "alpha": "2026-10-07T21:12:03.456Z", "beta": None, "gamma": None}
