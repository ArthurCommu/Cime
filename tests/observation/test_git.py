"""Tests de la lecture git, sur de vrais dépôts créés dans tmp_path."""

import subprocess
from pathlib import Path

import pytest

from chrono import meilleur

from cime.observation import git as mod
from cime.observation.git import est_dans_perimetre, lire_git


def g(d: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(d), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True, capture_output=True,
    )


def commit(d: Path, fichier: str, contenu: str = "x") -> None:
    p = d / fichier
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(contenu)
    g(d, "add", "-A")
    g(d, "commit", "-m", f"modif {fichier}")


@pytest.fixture
def depot(tmp_path):
    g(tmp_path, "init", "-b", "main")
    commit(tmp_path, "README.md", "base")
    return tmp_path


def branche(d: Path, nom: str, *fichiers: str) -> None:
    g(d, "checkout", "-b", f"equipe/{nom}", "main")
    for f in fichiers:
        commit(d, f, nom)
    g(d, "checkout", "main")


def eq(nom, perimetre=None, br="auto"):
    return {"nom": nom, "branche": f"equipe/{nom}" if br == "auto" else br, "perimetre_declare": perimetre}


def test_aucun_recouvrement(depot):
    branche(depot, "a", "src/a/x.py")
    branche(depot, "b", "src/b/y.py")
    d, s = lire_git(depot, "main", [eq("a"), eq("b")])
    assert s == {"nom": "git", "ok": True}
    assert d["recouvrements"] == []
    assert d["equipes"]["a"]["fichiers_touches"] == ["src/a/x.py"]
    assert d["equipes"]["a"]["hors_perimetre"] is None
    assert len(d["equipes"]["a"]["commit"]) >= 7 or d["equipes"]["a"]["commit"]


def test_recouvrement(depot):
    branche(depot, "a", "README.md")
    branche(depot, "b", "README.md")
    d, _ = lire_git(depot, "main", [eq("a"), eq("b")])
    assert [{k: r[k] for k in ("fichier", "equipes")} for r in d["recouvrements"]] == [
        {"fichier": "README.md", "equipes": ["a", "b"]}]
    assert d["recouvrements"][0]["depuis"]  # mesuré ; valeur exacte : test des dates ci-dessous


def test_hors_perimetre(depot):
    branche(depot, "a", "src/b/y.py")
    d, _ = lire_git(depot, "main", [eq("a", ["src/a/"])])
    assert d["equipes"]["a"]["hors_perimetre"] == ["src/b/y.py"]


def test_retard_sur_base(depot):
    branche(depot, "a", "src/a/x.py")
    for i in range(3):
        commit(depot, f"m{i}.txt")
    d, _ = lire_git(depot, "main", [eq("a")])
    assert d["equipes"]["a"]["retard_sur_base"] == 3


def test_branche_absente_ou_nulle(depot):
    d, s = lire_git(depot, "main", [eq("a"), eq("spec", br=None)])
    assert s["ok"] is True
    for nom in ("a", "spec"):
        e = d["equipes"][nom]
        assert e["commit"] is None and e["fichiers_touches"] is None
        assert e["hors_perimetre"] is None and e["retard_sur_base"] is None
    assert d["recouvrements"] == []


def test_dossier_sans_git(tmp_path):
    d, s = lire_git(tmp_path, "main", [eq("a")])
    assert d is None and s["ok"] is False and s["erreur"]


def test_dossier_inexistant(tmp_path):
    d, s = lire_git(tmp_path / "nulle-part", "main", [])
    assert d is None and s["ok"] is False


def test_est_dans_perimetre():
    assert est_dans_perimetre("src/a/x.py", ["src/a/"])
    assert not est_dans_perimetre("src/ab/x.py", ["src/a/"])
    assert est_dans_perimetre("README.md", ["README.md"])
    assert not est_dans_perimetre("README.md.bak", ["README.md"])


def test_lecture_seule(depot, monkeypatch):
    branche(depot, "a", "src/a/x.py")
    appels = []
    reel = subprocess.run

    def espion(cmd, *a, **k):
        appels.append(cmd)
        return reel(cmd, *a, **k)

    monkeypatch.setattr(mod.subprocess, "run", espion)
    lire_git(depot, "main", [eq("a", ["src/a/"]), eq("z")])
    sous_commandes = {c[3] for c in appels}  # git -C <racine> <sous-commande>
    assert appels and sous_commandes <= {"rev-parse", "diff", "rev-list", "for-each-ref", "log"}


def test_depot_de_quelques_equipes_lu_vite(depot):
    for n in ("a", "b", "c", "d"):
        branche(depot, n, f"src/{n}/x.py")
    equipes = [eq(n, None) for n in ("a", "b", "c", "d")]
    duree, (d, s) = meilleur(lambda: lire_git(depot, "main", equipes), 3)
    assert duree < 2  # les machines de la CI sont plus lentes qu'un Mac de développement
    assert s["nom"] == "git"


# --- dates mesurées dans git ---------------------------------

def commit_date(d: Path, fichier: str, date: str, contenu: str = "x") -> None:
    p = d / fichier
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(contenu)
    env = {**__import__("os").environ, "GIT_COMMITTER_DATE": date, "GIT_AUTHOR_DATE": date}
    for args in (("add", "-A"), ("commit", "-m", f"modif {fichier}")):
        subprocess.run(["git", "-C", str(d), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                       check=True, capture_output=True, env=env)


def test_dates_premier_commit_par_fichier_et_recouvrement_au_second(depot):
    g(depot, "checkout", "-b", "equipe/a", "main")
    commit_date(depot, "src/a/x.py", "2026-10-07T10:00:00+02:00")
    commit_date(depot, "commun.py", "2026-10-07T11:00:00+02:00", "a1")
    commit_date(depot, "commun.py", "2026-10-07T12:00:00+02:00", "a2")  # pas le premier : ignoré
    g(depot, "checkout", "-b", "equipe/b", "main")
    commit_date(depot, "commun.py", "2026-10-07T13:30:00+02:00", "b")
    g(depot, "checkout", "main")
    d, s = lire_git(depot, "main", [{"nom": "a", "branche": "equipe/a", "perimetre_declare": ["src/a/"]},
                                    {"nom": "b", "branche": "equipe/b", "perimetre_declare": ["src/b/"]}])
    assert s["ok"]
    assert d["equipes"]["a"]["dates_fichiers"] == {"src/a/x.py": "2026-10-07T08:00:00.000Z",
                                                   "commun.py": "2026-10-07T09:00:00.000Z"}
    assert d["equipes"]["a"]["hors_perimetre"] == ["commun.py"]
    assert d["recouvrements"] == [{"fichier": "commun.py", "equipes": ["a", "b"],
                                   "depuis": "2026-10-07T11:30:00.000Z"}]


def test_retard_depuis_le_plus_ancien_commit_de_la_base_absent(depot):
    branche(depot, "a", "src/a/x.py")
    commit_date(depot, "base1.md", "2026-10-07T09:00:00+00:00")
    commit_date(depot, "base2.md", "2026-10-07T10:00:00+00:00")
    d, _ = lire_git(depot, "main", [{"nom": "a", "branche": "equipe/a", "perimetre_declare": None}])
    e = d["equipes"]["a"]
    assert (e["retard_sur_base"], e["retard_depuis"]) == (2, "2026-10-07T09:00:00.000Z")


def test_sans_retard_ni_branche_dates_absentes(depot):
    branche(depot, "a", "src/a/x.py")
    d, _ = lire_git(depot, "main", [{"nom": "a", "branche": "equipe/a", "perimetre_declare": None},
                                    {"nom": "z", "branche": "equipe/z", "perimetre_declare": None}])
    assert d["equipes"]["a"]["retard_depuis"] is None
    assert d["equipes"]["z"]["dates_fichiers"] is None and d["equipes"]["z"]["retard_depuis"] is None


def test_en_avance_sur_base(depot):
    branche(depot, "a", "src/a/x.py")
    for i in range(3):
        commit(depot, f"m{i}.txt")
    d, _ = lire_git(depot, "main", [eq("a"), eq("spec", br=None), eq("z")])
    assert d["equipes"]["a"]["en_avance_sur_base"] == 1  # le retard (3) ne compte pas
    assert d["equipes"]["spec"]["en_avance_sur_base"] is None  # pas de branche
    assert d["equipes"]["z"]["en_avance_sur_base"] is None  # branche absente
