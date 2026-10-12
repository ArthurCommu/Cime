import argparse
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
import textwrap
import types
from pathlib import Path

import pytest

from cime.fondation import hook, perimetre
from cime.fondation.nom import VAR_AGENT, VAR_PROJET

MANIFESTE = textwrap.dedent("""\
    nom = "Essai"
    prefixe = "cc"
    branche_reference = "main"
    branche_equipe = "equipe/{equipe}"
    worktree_equipe = ".orga/worktrees/{equipe}"
    equipes_speciales = ["assistant"]
    modele_assistant = "m"
    modele_coordinateur = "m"
""")


def _git(*args, cwd):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def depot(tmp_path, monkeypatch):
    """Vrai dépôt git jetable (projet), un dossier hors du projet, un HOME factice."""
    racine = tmp_path / "depot"
    (racine / ".orga").mkdir(parents=True)
    (racine / ".orga" / "projet.toml").write_text(MANIFESTE)
    (racine / "src").mkdir()
    (racine / "src" / "a.py").write_text("x = 1\n")
    _git("init", "-q", "-b", "main", cwd=racine)
    _git("add", "-A", cwd=racine)
    _git("commit", "-q", "-m", "init", cwd=racine)
    (tmp_path / "dehors").mkdir()
    (tmp_path / "dehors" / "a.txt").write_text("hors\n")
    (tmp_path / "depot-autre").mkdir()
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv(VAR_PROJET, str(racine))
    # L'Assistant n'est pas limité en écriture : ces tests historiques valent pour lui.
    # Les règles par équipe ont leurs propres tests, plus bas.
    monkeypatch.setenv(VAR_AGENT, "assistant")
    monkeypatch.delenv("TMUX", raising=False)
    return racine


def dehors(depot):
    return depot.parent / "dehors"


def entree(outil, tool_input, cwd):
    return {"tool_name": outil, "tool_input": tool_input, "cwd": str(cwd)}


# --- outils de fichiers hors et dans le projet ----------------------------------

OUTILS = ["Read", "Write", "Edit", "NotebookEdit", "Glob", "Grep"]


def _entrees_par_outil(d: Path) -> dict:
    return {
        "Read": {"file_path": str(d / "a.txt")},
        "Write": {"file_path": str(d / "b.txt"), "content": "x"},
        "Edit": {"file_path": str(d / "a.txt"), "old_string": "a", "new_string": "b"},
        "NotebookEdit": {"notebook_path": str(d / "n.ipynb")},
        "Glob": {"path": str(d), "pattern": "*.py"},
        "Grep": {"path": str(d), "pattern": "x"},
    }


@pytest.mark.parametrize("outil", OUTILS)
def test_hors_du_projet_refuse(depot, outil):
    tool_input = _entrees_par_outil(dehors(depot))[outil]
    motif = perimetre.decider(entree(outil, tool_input, depot), depot)
    assert motif is not None
    assert outil in motif


@pytest.mark.parametrize("outil", OUTILS)
def test_dans_le_projet_accepte(depot, outil):
    tool_input = _entrees_par_outil(depot)[outil]
    assert perimetre.decider(entree(outil, tool_input, depot), depot) is None


def test_refus_nomme_outil_chemin_demande_et_resolu(depot):
    cible = dehors(depot) / "a.txt"
    motif = perimetre.decider(entree("Read", {"file_path": str(cible)}, depot), depot)
    assert "Read" in motif
    assert str(cible) in motif
    assert "hors du projet" in motif


# --- worktrees --------------------------------------------------------------------

def test_worktree_dans_le_projet_accepte(depot):
    wt = depot / ".orga" / "worktrees" / "wt"
    _git("worktree", "add", "-q", "-b", "equipe/wt", str(wt), cwd=depot)
    fichier = wt / "src" / "a.py"
    assert perimetre.decider(entree("Read", {"file_path": str(fichier)}, depot), depot) is None


def test_worktree_frere_du_projet_refuse(depot):
    """Un worktree hors du projet (ancien emplacement, dossier frère) n'est plus permis."""
    frere = depot.parent / "depot-wt"
    _git("worktree", "add", "-q", "-b", "equipe/wt", str(frere), cwd=depot)
    fichier = frere / "src" / "a.py"
    motif = perimetre.decider(entree("Read", {"file_path": str(fichier)}, depot), depot)
    assert motif is not None
    assert "hors du projet" in motif


def test_aucun_appel_git_pour_le_perimetre(depot, monkeypatch):
    appels = []

    def espion(args, **kw):
        appels.append(args)
        raise OSError("git interdit au périmètre")

    monkeypatch.setattr(subprocess, "run", espion)
    for cible in (depot / "src" / "a.py", dehors(depot) / "a.txt"):
        perimetre.decider(entree("Read", {"file_path": str(cible)}, depot), depot)
        perimetre.decider(entree("Write", {"file_path": str(cible)}, depot), depot)
    assert appels == []


# --- `..`, liens symboliques, préfixe, création, cwd, ~ -------------------------

def test_dotdot_qui_sort_refuse(depot):
    e = entree("Read", {"file_path": "../dehors/a.txt"}, depot)
    assert perimetre.decider(e, depot) is not None


def test_dotdot_qui_reste_accepte(depot):
    e = entree("Read", {"file_path": "src/../src/a.py"}, depot)
    assert perimetre.decider(e, depot) is None


def test_lien_symbolique_sortant_refuse(depot):
    (depot / "lien").symlink_to(dehors(depot), target_is_directory=True)
    e = entree("Read", {"file_path": str(depot / "lien" / "a.txt")}, depot)
    assert perimetre.decider(e, depot) is not None


def test_lien_symbolique_entrant_accepte(depot):
    lien = dehors(depot) / "lien"
    lien.symlink_to(depot / "src", target_is_directory=True)
    e = entree("Read", {"file_path": str(lien / "a.py")}, depot)
    assert perimetre.decider(e, depot) is None


def test_piege_du_prefixe_refuse(depot):
    autre = depot.parent / "depot-autre" / "a.txt"
    autre.write_text("x")
    e = entree("Read", {"file_path": str(autre)}, depot)
    assert perimetre.decider(e, depot) is not None


def test_write_nouveau_fichier(depot):
    dedans = entree("Write", {"file_path": str(depot / "src" / "nouveau" / "n.py")}, depot)
    assert perimetre.decider(dedans, depot) is None
    dehors_ = entree("Write", {"file_path": str(dehors(depot) / "nouveau.txt")}, depot)
    assert perimetre.decider(dehors_, depot) is not None


def test_chemin_relatif_resolu_avec_cwd(depot):
    assert perimetre.decider(entree("Read", {"file_path": "a.txt"}, depot), depot) is None
    assert perimetre.decider(entree("Read", {"file_path": "a.txt"}, dehors(depot)),
                             depot) is not None
    assert perimetre.decider(entree("Read", {"file_path": "../dehors/a.txt"}, depot),
                             depot) is not None


def test_tilde_refuse(depot):
    assert perimetre.decider(entree("Read", {"file_path": "~/x"}, depot), depot) is not None


# --- Glob et Grep ---------------------------------------------------------------

def test_glob_pattern_absolu_hors_refuse(depot):
    e = entree("Glob", {"pattern": f"{dehors(depot)}/**/*.py"}, depot)
    assert perimetre.decider(e, depot) is not None


def test_glob_pattern_absolu_dedans_accepte(depot):
    e = entree("Glob", {"pattern": f"{depot}/**/*.py"}, depot)
    assert perimetre.decider(e, depot) is None


def test_glob_pattern_relatif_ordinaire_accepte(depot):
    e = entree("Glob", {"path": str(depot), "pattern": "src/**/*.py"}, depot)
    assert perimetre.decider(e, depot) is None


def test_glob_pattern_avec_dotdot_refuse(depot):
    e = entree("Glob", {"pattern": "../dehors/**/*.txt"}, depot)
    assert perimetre.decider(e, depot) is not None


def test_glob_tilde_refuse(depot):
    e = entree("Glob", {"pattern": "~/**/*"}, depot)
    assert perimetre.decider(e, depot) is not None


def test_grep_sans_path_utilise_cwd(depot):
    assert perimetre.decider(entree("Grep", {"pattern": "x"}, depot), depot) is None
    assert perimetre.decider(entree("Grep", {"pattern": "x"}, dehors(depot)),
                             depot) is not None


# --- outils inconnus, Bash, absence de chemin, cas limites ------------------------

def test_outil_inconnu_avec_file_path_refuse(depot):
    e = entree("Lire", {"file_path": str(dehors(depot) / "a.txt")}, depot)
    assert perimetre.decider(e, depot) is not None


def test_outil_mcp_avec_path_refuse(depot):
    e = entree("mcp__x__lister", {"path": str(dehors(depot))}, depot)
    assert perimetre.decider(e, depot) is not None


def test_outil_inconnu_sans_cle_chemin_ignore(depot):
    e = entree("Sleep", {"duration": 3}, dehors(depot))
    assert perimetre.decider(e, depot) is None


def test_bash_non_concerne(depot):
    e = entree("Bash", {"command": f"cat {dehors(depot)}/a.txt"}, depot)
    assert perimetre.decider(e, depot) is None


def test_absence_de_chemin_accepte(depot):
    assert perimetre.decider(entree("Read", {}, dehors(depot)), depot) is None


def test_sans_projet_ne_s_applique_pas(depot):
    e = entree("Read", {"file_path": str(dehors(depot) / "a.txt")}, depot)
    assert perimetre.decider(e, None) is None


def test_exception_injectee_accepte(depot, monkeypatch):
    cible = dehors(depot) / "a.txt"
    e = entree("Read", {"file_path": str(cible)}, depot)
    assert perimetre.decider(e, depot) is not None
    monkeypatch.setattr(perimetre, "EXCEPTIONS", [dehors(depot)])
    assert perimetre.decider(e, depot) is None
    fils = entree("Read", {"file_path": str(dehors(depot) / "sous" / "b.txt")}, depot)
    assert perimetre.decider(fils, depot) is None
    freres = entree("Read", {"file_path": str(depot.parent / "depot-autre" / "a.txt")},
                    depot)
    assert perimetre.decider(freres, depot) is not None


def test_erreur_interne_refuse(depot):
    e = entree("Read", {"file_path": 42}, depot)
    motif = perimetre.decider(e, depot)
    assert motif is not None
    assert "erreur interne" in motif


# --- le hook complet -------------------------------------------------------------

def lancer(monkeypatch, capsys, entree_):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(entree_)))
    code = hook.executer(argparse.Namespace(evenement="PreToolUse"))
    assert code == 0
    return capsys.readouterr().out


def lignes(depot):
    conn = sqlite3.connect(depot / ".orga" / "etat" / "registre.sqlite")
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("select * from evenements order by id")]
    finally:
        conn.close()


def _hook_entree(outil, tool_input, cwd):
    return {"session_id": "s1", "cwd": str(cwd), "hook_event_name": "PreToolUse",
            "tool_name": outil, "tool_input": tool_input}


def test_hook_refus_inscrit_evenement(depot, monkeypatch, capsys):
    cible = str(dehors(depot) / "a.txt")
    sortie = json.loads(lancer(monkeypatch, capsys,
                               _hook_entree("Read", {"file_path": cible}, depot)))
    assert sortie["hookSpecificOutput"]["permissionDecision"] == "deny"
    motif = sortie["hookSpecificOutput"]["permissionDecisionReason"]
    (ligne,) = lignes(depot)
    assert ligne["evenement"] == "PreToolUse"
    details = json.loads(ligne["details"])
    assert details["tool_name"] == "Read"
    assert details["tool_input"] == {"file_path": cible}
    assert details["motif"] == motif


def test_hook_chemin_permis_n_inscrit_rien(depot, monkeypatch, capsys):
    out = lancer(monkeypatch, capsys,
                 _hook_entree("Read", {"file_path": str(depot / "src" / "a.py")}, depot))
    assert out == ""
    assert not (depot / ".orga" / "etat" / "registre.sqlite").exists()


def test_hook_perimetre_absent_refuse_outil_de_fichier(depot, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "cime.fondation.perimetre", None)  # ImportError
    monkeypatch.delattr("cime.fondation.perimetre", raising=False)
    cible = str(dehors(depot) / "a.txt")
    sortie = json.loads(lancer(monkeypatch, capsys,
                               _hook_entree("Read", {"file_path": cible}, depot)))
    assert sortie["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "indisponible" in sortie["hookSpecificOutput"]["permissionDecisionReason"]
    assert (depot / ".orga" / "etat" / "hooks-erreurs.log").exists()


def test_hook_perimetre_absent_laisse_bash(depot, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "cime.fondation.perimetre", None)  # ImportError
    monkeypatch.delattr("cime.fondation.perimetre", raising=False)
    assert lancer(monkeypatch, capsys,
                  _hook_entree("Bash", {"command": "ls"}, depot)) == ""


# --- écriture par équipe ----------------------------------------------------------

MANIFESTE_EQUIPES = MANIFESTE.replace('equipes_speciales = ["assistant"]',
                                      'equipes_speciales = ["integration"]')


def worktree(depot, equipe) -> Path:
    """Worktree d'une équipe : dans le projet, comme `cime equipe` le crée."""
    return depot / ".orga" / "worktrees" / equipe


def _segment(chemin) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(chemin))


@pytest.fixture
def equipes(depot, monkeypatch):
    """Projet avec les équipes a et b (worktrees réels), et l'intégration (spéciale)."""
    (depot / ".orga" / "projet.toml").write_text(MANIFESTE_EQUIPES)
    for equipe in ("a", "b", "integration"):
        (depot / ".orga" / "teams" / equipe).mkdir(parents=True)
    (depot / ".orga" / "teams" / "integration" / "requests").mkdir(parents=True)
    _git("worktree", "add", "-q", "-b", "equipe/a", str(worktree(depot, "a")), cwd=depot)
    _git("worktree", "add", "-q", "-b", "equipe/b", str(worktree(depot, "b")), cwd=depot)
    monkeypatch.setenv(VAR_AGENT, "coord-a")
    return depot


@pytest.mark.parametrize("identite", ["coord-a", "worker-a-tache"])
def test_equipe_ecrit_dans_son_dossier(equipes, monkeypatch, identite):
    monkeypatch.setenv(VAR_AGENT, identite)
    assert perimetre.decider(entree("Write", {"file_path": str(equipes / ".orga/teams/a/n.md")},
                                    equipes), equipes) is None


@pytest.mark.parametrize("identite", ["coord-a", "worker-a-tache"])
def test_equipe_ecrit_dans_son_worktree(equipes, monkeypatch, identite):
    monkeypatch.setenv(VAR_AGENT, identite)
    cible = worktree(equipes, "a") / "src" / "n.py"
    assert perimetre.decider(entree("Write", {"file_path": str(cible)}, equipes), equipes) is None


@pytest.mark.parametrize("identite", ["coord-a", "worker-a-tache"])
def test_equipe_refuse_hors_de_son_perimetre(equipes, monkeypatch, identite):
    monkeypatch.setenv(VAR_AGENT, identite)
    cibles = [equipes / ".orga" / "teams" / "b" / "n.md",
              worktree(equipes, "b") / "src" / "n.py",
              equipes / "src" / "n.py",
              equipes / "racine.md"]
    for cible in cibles:
        motif = perimetre.decider(entree("Write", {"file_path": str(cible)}, equipes), equipes)
        assert motif is not None, cible
        assert "l'équipe a" in motif
        assert "n'écrit que dans" in motif


def test_requetes_integration_accepte_pour_toute_equipe(equipes, monkeypatch):
    monkeypatch.setenv(VAR_AGENT, "coord-a")
    cible = equipes / ".orga" / "teams" / "integration" / "requests" / "todo" / "x.md"
    assert perimetre.decider(entree("Write", {"file_path": str(cible)}, equipes), equipes) is None


def test_equipe_speciale_sans_worktree(equipes, monkeypatch):
    monkeypatch.setenv(VAR_AGENT, "coord-integration")
    dedans = equipes / ".orga" / "teams" / "integration" / "x.md"
    assert perimetre.decider(entree("Write", {"file_path": str(dedans)}, equipes), equipes) is None
    sans_worktree = worktree(equipes, "integration") / "x.py"
    assert perimetre.decider(entree("Write", {"file_path": str(sans_worktree)}, equipes),
                             equipes) is not None
    assert perimetre.decider(entree("Write", {"file_path": str(equipes / "src" / "a.py")},
                                    equipes), equipes) is not None


def test_dossiers_de_travail_claude_code_accepte_registre_refuse(equipes, monkeypatch):
    monkeypatch.setenv(VAR_AGENT, "coord-a")
    cible = equipes / ".orga" / "etat" / "tmp" / "x"
    assert perimetre.decider(entree("Write", {"file_path": str(cible)}, equipes),
                             equipes) is None
    registre = equipes / ".orga" / "etat" / "registre.sqlite"
    assert perimetre.decider(entree("Write", {"file_path": str(registre)}, equipes),
                             equipes) is not None


def test_memoire_ecrite_seulement_dans_le_dossier_de_l_identite(equipes, monkeypatch):
    memoire = equipes / ".orga" / "etat" / "memoire"
    monkeypatch.setenv(VAR_AGENT, "worker-a-x")
    entree_ecriture = lambda chemin: entree("Write", {"file_path": str(chemin)}, equipes)
    assert perimetre.decider(entree_ecriture(memoire / "worker-a-x" / "n.md"), equipes) is None
    assert perimetre.decider(entree_ecriture(memoire / "worker-a-y" / "n.md"), equipes) is not None
    assert perimetre.decider(entree_ecriture(memoire / "n.md"), equipes) is not None
    lecture = entree("Read", {"file_path": str(memoire / "worker-a-y" / "n.md")}, equipes)
    assert perimetre.decider(lecture, equipes) is None


def test_memoire_du_coordinateur_limitee_a_son_dossier(equipes, monkeypatch):
    memoire = equipes / ".orga" / "etat" / "memoire"
    monkeypatch.setenv(VAR_AGENT, "coord-a")
    assert perimetre.decider(entree("Edit", {"file_path": str(memoire / "coord-a" / "m.md")},
                                    equipes), equipes) is None
    assert perimetre.decider(entree("Edit", {"file_path": str(memoire / "worker-a-x" / "m.md")},
                                    equipes), equipes) is not None


def test_memoire_assistant_non_limitee(equipes, monkeypatch):
    monkeypatch.setenv(VAR_AGENT, "assistant")
    cible = equipes / ".orga" / "etat" / "memoire" / "worker-a-x" / "n.md"
    assert perimetre.decider(entree("Write", {"file_path": str(cible)}, equipes), equipes) is None


def test_assistant_ecrit_partout_dans_le_projet(equipes, monkeypatch):
    monkeypatch.setenv(VAR_AGENT, "assistant")
    cibles = [worktree(equipes, "b") / "src" / "n.py",
              equipes / ".orga" / "teams" / "b" / "n.md",
              equipes / "racine.md"]
    for cible in cibles:
        assert perimetre.decider(entree("Write", {"file_path": str(cible)}, equipes),
                                 equipes) is None
    assert perimetre.decider(entree("Write", {"file_path": str(dehors(equipes) / "x")},
                                    equipes), equipes) is not None


def test_sans_identite_comportement_d_avant(equipes, monkeypatch):
    monkeypatch.delenv(VAR_AGENT, raising=False)
    cible = equipes / ".orga" / "teams" / "b" / "n.md"
    assert perimetre.decider(entree("Write", {"file_path": str(cible)}, equipes), equipes) is None


def test_zones_ecriture_projet_par_identite(equipes):
    assert perimetre.zones_ecriture_projet(equipes, "assistant") is None
    assert perimetre.zones_ecriture_projet(equipes, "utilisateur") is None
    assert perimetre.zones_ecriture_projet(equipes, None) is None
    zones = perimetre.zones_ecriture_projet(equipes, "worker-a-tache")
    coord = perimetre.zones_ecriture_projet(equipes, "coord-a")
    hors_memoire = [z for z in zones if "memoire" not in z.parts]
    assert hors_memoire == [z for z in coord if "memoire" not in z.parts]
    assert os.path.realpath(equipes / ".orga" / "etat" / "memoire" / "worker-a-tache") in \
        [str(z) for z in zones]
    assert os.path.realpath(equipes / ".orga" / "etat" / "memoire" / "coord-a") in \
        [str(z) for z in coord]
    assert os.path.realpath(worktree(equipes, "a")) in [str(z) for z in zones]
    assert os.path.realpath(worktree(equipes, "b")) not in [str(z) for z in zones]
    assert perimetre.zones_ecriture_projet(equipes, "coord-integration") == [
        Path(os.path.realpath(equipes / ".orga" / "teams" / "integration")),
        Path(os.path.realpath(equipes / ".orga" / "teams" / "integration" / "requests")),
        Path(os.path.realpath(equipes / ".orga" / "etat" / "tmp")),
        Path(os.path.realpath(equipes / ".orga" / "etat" / "memoire" / "coord-integration")),
    ]


def test_zones_ecriture_projet_equipe_inconnue_aucune_zone(equipes):
    assert perimetre.zones_ecriture_projet(equipes, "coord-absente") == []


@pytest.mark.parametrize("identite", ["coord-inconnue", "worker-inconnue-tache",
                                      "coord-absente"])
def test_equipe_introuvable_refuse_toute_ecriture(equipes, monkeypatch, identite):
    monkeypatch.setenv(VAR_AGENT, identite)
    cible = equipes / ".orga" / "teams" / "a" / "n.md"
    motif = perimetre.decider(entree("Write", {"file_path": str(cible)}, equipes), equipes)
    assert motif is not None
    assert "introuvable" in motif
    lecture = perimetre.decider(entree("Read", {"file_path": str(cible)}, equipes), equipes)
    assert lecture is None


def test_lecture_dans_worktree_autre_equipe_accepte(equipes):
    cible = worktree(equipes, "b") / "src" / "a.py"
    assert perimetre.decider(entree("Read", {"file_path": str(cible)}, equipes), equipes) is None
    assert perimetre.decider(entree("Glob", {"path": str(worktree(equipes, "b")),
                                             "pattern": "**/*.py"}, equipes),
                             equipes) is None


def test_edit_autre_equipe_refuse_read_accepte(equipes):
    cible = worktree(equipes, "b") / "src" / "a.py"
    assert perimetre.decider(entree("Edit", {"file_path": str(cible), "old_string": "x",
                                             "new_string": "y"}, equipes), equipes) is not None
    assert perimetre.decider(entree("Read", {"file_path": str(cible)}, equipes), equipes) is None


def test_outil_inconnu_avec_file_path_autre_equipe_refuse(equipes):
    cible = worktree(equipes, "b") / "src" / "a.py"
    motif = perimetre.decider(entree("Patcher", {"file_path": str(cible)}, equipes), equipes)
    assert motif is not None
    assert "l'équipe a" in motif


def test_transcriptions_du_projet_lisibles(equipes, monkeypatch):
    dossier = Path(os.environ["HOME"]) / ".claude" / "projects"
    segments = [_segment(equipes), _segment(equipes) + "--orga-teams-a",
                _segment(worktree(equipes, "a"))]
    for segment in segments:
        (dossier / segment).mkdir(parents=True)
        (dossier / segment / "x.jsonl").write_text("{}\n")
        cible = dossier / segment / "x.jsonl"
        assert perimetre.decider(entree("Read", {"file_path": str(cible)}, equipes),
                                 equipes) is None, segment


@pytest.mark.parametrize("nom", ["{seg}-autre", "-Users-autre-projet"])
def test_transcriptions_trompeuses_ou_autres_refusees(equipes, nom):
    dossier = Path(os.environ["HOME"]) / ".claude" / "projects"
    segment = nom.format(seg=_segment(equipes))
    (dossier / segment).mkdir(parents=True)
    cible = dossier / segment / "x.jsonl"
    cible.write_text("{}\n")
    assert perimetre.decider(entree("Read", {"file_path": str(cible)}, equipes),
                             equipes) is not None


def test_ecriture_dans_transcriptions_refusee(equipes, monkeypatch):
    monkeypatch.setenv(VAR_AGENT, "assistant")
    dossier = Path(os.environ["HOME"]) / ".claude" / "projects" / _segment(equipes)
    dossier.mkdir(parents=True)
    cible = dossier / "x.jsonl"
    assert perimetre.decider(entree("Write", {"file_path": str(cible)}, equipes),
                             equipes) is not None
    monkeypatch.setenv(VAR_AGENT, "coord-a")
    assert perimetre.decider(entree("Edit", {"file_path": str(cible)}, equipes),
                             equipes) is not None


def test_hook_refus_d_equipe_inscrit_evenement(equipes, monkeypatch, capsys):
    monkeypatch.setenv(VAR_AGENT, "coord-a")
    cible = str(worktree(equipes, "b") / "src" / "a.py")
    sortie = json.loads(lancer(monkeypatch, capsys,
                               _hook_entree("Write", {"file_path": cible, "content": "x"},
                                            equipes)))
    assert sortie["hookSpecificOutput"]["permissionDecision"] == "deny"
    (ligne,) = lignes(equipes)
    assert ligne["evenement"] == "PreToolUse"
    assert json.loads(ligne["details"])["motif"] == \
        sortie["hookSpecificOutput"]["permissionDecisionReason"]
