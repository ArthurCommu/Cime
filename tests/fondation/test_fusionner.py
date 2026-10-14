"""`cime fusionner <équipe>` : la file de fusion. Dépôt jetable (main, equipe/x), suite injectée (un
double qui passe, un qui échoue), réinstallation et arrêt du facteur remplacés par des doubles ;
l'historique de tous les appels de git est vérifié à la fin de chaque test (jamais de push, jamais
de suppression de branche, un seul worktree retiré : celui de l'essai)."""
import argparse
import json
import os
import re
import signal
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from cime.fondation import fusionner, garde
from cime.fondation.nom import VAR_AGENT
from cime.fondation.registre import ouvrir
from test_garde_fusion import _git, depot, donner_accord, identite, sha_de  # noqa: F401
from test_garde_fusions_auto import activer, annoncer, branche, ecrire, manifeste, valider  # noqa: F401

LIGNE_JOURNAL = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z (\S+) ([0-9a-f]{40}) (\S+) (.*)$")


class Monde:
    """Ce que les doubles ont vu."""

    def __init__(self):
        self.git = []                # [(args)] de chaque appel de git de la commande
        self.suites = []             # dossiers où la suite a été lancée
        self.reinstallations = []
        self.facteurs = []
        self.sorties = []            # les lignes dites par la commande (stdout)
        self.workers = 0
        self.suite = None            # (projet, dossier) -> (code, sortie) ; défaut : qui passe
        self.parents_a_la_suite = []


@pytest.fixture
def monde(depot, monkeypatch):
    m = Monde()
    identite(monkeypatch, "assistant")
    for k in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(k, "t")
    for k in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(k, "t@t")
    reel = fusionner._git

    def git_espionne(projet, *args, cwd=None):
        m.git.append(args)
        return reel(projet, *args, cwd=cwd)

    def suite(projet, dossier):
        m.suites.append(Path(dossier))
        m.parents_a_la_suite.append(
            subprocess.run(["git", "-C", str(dossier), "rev-list", "--parents", "-n", "1", "HEAD"],
                           capture_output=True, text=True).stdout.split()[1:])
        return (m.suite or (lambda p, d: (0, "..\n2 passed in 0.10s\n")))(projet, dossier)

    monkeypatch.setattr(fusionner, "_git", git_espionne)
    monkeypatch.setattr(fusionner, "_suite", suite)
    monkeypatch.setattr(fusionner, "_workers_actifs", lambda projet: m.workers)
    monkeypatch.setattr(fusionner, "_reinstaller", lambda p: (m.reinstallations.append(Path(p)), (True, ""))[1])
    monkeypatch.setattr(fusionner, "_arreter_facteur", lambda p: (m.facteurs.append(Path(p)), "facteur arrêté")[1])
    yield m
    # historique des appels de git : jamais de push ni de suppression de branche ; un worktree retiré,
    # celui de l'essai
    for args in m.git:
        assert "push" not in args
        assert not (args[0] == "branch" and any(a in ("-d", "-D", "--delete") for a in args))
        if args[:2] == ("worktree", "remove"):
            assert "/fe-" in args[-1] and ".orga/etat/tmp/" in args[-1]
        assert args[0] not in ("checkout", "reset", "switch", "stash")


def lancer(depot, capsys, equipe="x", maintenant=False, message=None):
    code = fusionner.executer(argparse.Namespace(equipe=equipe, maintenant=maintenant, message=message))
    sortie = capsys.readouterr()
    return code, sortie.out, sortie.err


def lignes_journal(depot):
    f = depot / ".orga" / "etat" / "fusions.log"
    return f.read_text().splitlines() if f.exists() else []


def worktrees(depot):
    return [l for l in subprocess.run(["git", "-C", str(depot), "worktree", "list", "--porcelain"],
                                      capture_output=True, text=True).stdout.splitlines()
            if l.startswith("worktree ")]


def essais(depot):
    d = depot / ".orga" / "etat" / "tmp"
    return sorted(d.glob("fe-*")) if d.exists() else []


def verrou(depot):
    return depot / ".orga" / "etat" / fusionner.VERROU


def journal_registre(depot, action):
    conn = ouvrir(depot)
    try:
        return conn.execute("SELECT auteur, cible, details, resultat FROM journal WHERE action = ?",
                            (action,)).fetchall()
    finally:
        conn.close()


def propre(depot, monde):
    """Rien ne traîne : pas d'essai, pas de verrou, un seul worktree (le principal)."""
    assert essais(depot) == [] and not verrou(depot).exists()
    assert len(worktrees(depot)) == 1


def avec_fichier(depot, nom="a.txt", contenu="a\n"):
    """equipe/x porte un vrai commit (le fichier `nom`)."""
    _git("checkout", "-q", "equipe/x", cwd=depot)
    ecrire(depot, {nom: contenu})
    valider(depot, "ajout")
    _git("checkout", "-q", "main", cwd=depot)


# --- la suite passe ---------------------------------------------------------------------------

def test_suite_verte_voie_accord_fusionne_journalise_reinstalle(depot, monde, capsys):
    avec_fichier(depot)
    sha = sha_de(depot, "equipe/x")
    avant = sha_de(depot, "main")
    accord = donner_accord(depot)
    code, sortie, _ = lancer(depot, capsys)
    assert code == 0, sortie
    # la fusion est dans main, commit de fusion à deux parents, sujet par défaut
    assert subprocess.run(["git", "-C", str(depot), "merge-base", "--is-ancestor", sha, "main"]).returncode == 0
    assert subprocess.run(["git", "-C", str(depot), "log", "-1", "--format=%s", "main"],
                          capture_output=True, text=True).stdout.strip() == f"Fusion x {sha[:7]}"
    assert subprocess.run(["git", "-C", str(depot), "rev-list", "--parents", "-n", "1", "main"],
                          capture_output=True, text=True).stdout.split()[1:] == [avant, sha]
    # deux lignes dans fusions.log, au format du hook ; FUSION_AVANT écrit
    intention, resultat = lignes_journal(depot)
    assert LIGNE_JOURNAL.match(intention).groups() == ("assistant", sha, "equipe/x", "cime fusionner x")
    assert LIGNE_JOURNAL.match(resultat).groups() == ("assistant", sha, "equipe/x", "resultat=fusionne")
    assert (depot / ".orga" / "etat" / "fusion-avant").read_text().strip() == avant
    # l'accord est consommé ; la suite a tourné sur l'essai (déjà fusionné) ; réinstallation sur la racine
    assert garde.accords_fusion_libres(depot) == []
    conn = ouvrir(depot)
    try:
        assert conn.execute("SELECT etat, auteur FROM transitions WHERE message_id = ? ORDER BY id DESC LIMIT 1",
                            (accord,)).fetchone() == ("clos", "cime")
    finally:
        conn.close()
    assert monde.parents_a_la_suite == [[avant, sha]]
    assert monde.reinstallations == [depot] and monde.facteurs == [depot]
    assert re.search(rf"fusionné : x {sha[:7]}, suite entière : 2 tests en \d+ s", sortie)
    propre(depot, monde)


def test_suite_verte_voie_auto_annonce_puis_journal(depot, monde, capsys):
    manifeste(depot, '\n[fusions_auto]\nreserves = ["src/cime/fondation/"]\n')
    activer(depot)
    sha = sha_de(depot, "equipe/x")
    code, sortie, _ = lancer(depot, capsys, message="Fusion de x")
    assert code == 0, sortie
    conn = ouvrir(depot)
    try:
        [(ident, objet, de, a, nature)] = conn.execute(
            "SELECT id, objet, de, a, nature FROM messages WHERE objet LIKE 'fusion-auto:%'").fetchall()
    finally:
        conn.close()
    assert (objet, de, a, nature) == (f"fusion-auto:x:{sha}", "assistant", "utilisateur", "rapport_utilisateur")
    [(auteur, cible, details, res)] = journal_registre(depot, "fusion_auto")
    assert (auteur, cible, res) == ("assistant", f"fusion:x:{sha}", "ok")
    assert json.loads(details)["annonce"] == ident
    assert subprocess.run(["git", "-C", str(depot), "log", "-1", "--format=%s", "main"],
                          capture_output=True, text=True).stdout.strip() == "Fusion de x"
    assert monde.reinstallations == [depot] and monde.facteurs == [depot]
    propre(depot, monde)


def test_deux_lignes_de_journal_meme_format_que_le_hook(depot, monde, capsys):
    donner_accord(depot)
    lancer(depot, capsys)
    for l in lignes_journal(depot):
        assert LIGNE_JOURNAL.match(l)


# --- la suite échoue ---------------------------------------------------------------------------

def sortie_en_echec(n=25):
    lignes = [f"FAILED tests/t_{i}.py::test_{i} - assert 0" for i in range(n)]
    return (1, "...\n=== short test summary info ===\n" + "\n".join(lignes)
            + f"\n{n} failed, 7 passed in 3.21s\n")


def test_suite_en_echec_refuse_sans_toucher_main(depot, monde, capsys):
    avec_fichier(depot)
    donner_accord(depot)
    avant = sha_de(depot, "main")
    sha = sha_de(depot, "equipe/x")
    monde.suite = lambda p, d: sortie_en_echec()
    code, sortie, erreur = lancer(depot, capsys)
    assert code == 1
    assert sha_de(depot, "main") == avant
    echecs = [l for l in erreur.splitlines() if l.startswith("FAILED ")]
    assert len(echecs) == 20 and "… et 5 autre(s)" in erreur
    assert "25 échec(s) sur 32" in erreur
    [l] = lignes_journal(depot)
    assert LIGNE_JOURNAL.match(l).groups() == ("assistant", sha, "equipe/x", "resultat=refuse-tests")
    [(auteur, cible, details, res)] = journal_registre(depot, "fusion_refusee")
    assert (auteur, cible, res) == ("assistant", f"fusion:x:{sha}", "refuse-tests")
    assert len(json.loads(details)["tests_en_echec"]) == 20 and json.loads(details)["total"] == 32
    assert garde.accords_fusion_libres(depot) != []          # l'accord n'est pas consommé
    assert monde.reinstallations == [] and monde.facteurs == []
    assert len(monde.suites) == 1                            # un seul pytest par essai
    propre(depot, monde)


def test_suite_en_echec_sans_ligne_failed_montre_la_fin_de_la_sortie(depot, monde, capsys):
    donner_accord(depot)
    monde.suite = lambda p, d: (2, "collecting ...\nImportError: pas de module truc\n")
    code, _, erreur = lancer(depot, capsys)
    assert code == 1 and "ImportError: pas de module truc" in erreur and "code 2" in erreur


def test_resume_de_pytest():
    sortie = "x\nFAILED a.py::t - e\nERROR b.py::u\n1 failed, 1 error, 8 passed, 1 skipped in 2.0s\n"
    assert fusionner._resume_suite(sortie) == (2, 11, ["FAILED a.py::t - e", "ERROR b.py::u"])
    assert fusionner._resume_suite("5 passed in 0.5s\n") == (0, 5, [])


# --- conflit de fusion d'essai -----------------------------------------------------------------

def test_conflit_d_essai_refuse_main_inchange(depot, monde, capsys):
    ecrire(depot, {"f.txt": "base\n"})
    valider(depot, "base")
    _git("branch", "-f", "equipe/x", "main", cwd=depot)
    avec_fichier(depot, "f.txt", "equipe\n")
    ecrire(depot, {"f.txt": "main\n"})
    valider(depot, "main change f")
    donner_accord(depot)
    avant, sha = sha_de(depot, "main"), sha_de(depot, "equipe/x")
    code, _, erreur = lancer(depot, capsys)
    assert code == 1 and "conflits" in erreur and "f.txt" in erreur
    assert sha_de(depot, "main") == avant and monde.suites == []
    assert LIGNE_JOURNAL.match(lignes_journal(depot)[-1]).group(4) == "resultat=refuse-conflit"
    assert journal_registre(depot, "fusion_refusee")[0][1] == f"fusion:x:{sha}"
    propre(depot, monde)


# --- règles d'accord avant tout essai ---------------------------------------------------------

def test_accord_manquant_refuse_avant_tout_essai(depot, monde, capsys):
    avant = sha_de(depot, "main")
    code, _, erreur = lancer(depot, capsys)
    assert code == 1 and "accord" in erreur
    assert not any(a[:2] == ("worktree", "add") for a in monde.git)
    assert monde.suites == [] and sha_de(depot, "main") == avant
    assert LIGNE_JOURNAL.match(lignes_journal(depot)[-1]).group(4) == "resultat=refuse-accord"
    propre(depot, monde)


def test_chemin_reserve_sans_accord_refuse_avant_tout_essai(depot, monde, capsys):
    manifeste(depot, '\n[fusions_auto]\nreserves = ["src/cime/fondation/"]\n')
    branche(depot, "equipe/r", {"src/cime/fondation/a.py": "x"})
    activer(depot)
    code, _, erreur = lancer(depot, capsys, equipe="r")
    assert code == 1 and "accord de l'utilisateur manquant pour r" in erreur
    conn = ouvrir(depot)
    try:
        resume, corps = conn.execute("SELECT resume, corps FROM messages WHERE nature = 'decision_utilisateur'"
                                     ).fetchone()
    finally:
        conn.close()
    assert "src/cime/fondation/a.py" in resume and "src/cime/fondation/a.py" in corps
    assert not any(a[:2] == ("worktree", "add") for a in monde.git) and monde.suites == []


def test_accord_pour_un_ancien_sha_ne_vaut_pas(depot, monde, capsys):
    donner_accord(depot, sha="0" * 40)
    code, _, erreur = lancer(depot, capsys)
    assert code == 1 and "demande #" in erreur and monde.suites == []
    assert "aucun accord pour ce sha" in journal_registre(depot, "fusion_refusee")[0][2]


def test_branche_inconnue(depot, monde, capsys):
    code, _, erreur = lancer(depot, capsys, equipe="zzz")
    assert code == 1 and "n'existe pas" in erreur
    code, _, erreur = lancer(depot, capsys, equipe="X; rm")
    assert code == 1 and "invalide" in erreur


def test_depot_principal_pas_sur_la_reference(depot, monde, capsys):
    donner_accord(depot)
    _git("checkout", "-q", "-b", "autre", cwd=depot)
    code, _, erreur = lancer(depot, capsys)
    assert code == 1 and "n'est pas sur main" in erreur and monde.suites == []
    propre(depot, monde)


# --- verrou -----------------------------------------------------------------------------------

def test_verrou_pris_par_un_pid_vivant_refuse_tout_de_suite(depot, monde, capsys):
    donner_accord(depot)
    detenteur = fusionner._Verrou(depot, "y", "a" * 40)
    detenteur.prendre()
    try:
        code, _, erreur = lancer(depot, capsys)
    finally:
        detenteur.liberer()
    assert code == 2
    assert re.search(rf"fusion de y \(aaaaaaa\) en cours depuis \d+ s par le pid {os.getpid()}", erreur)
    assert monde.suites == [] and not any(a[:2] == ("worktree", "add") for a in monde.git)


def test_verrou_d_un_pid_mort_est_repris(depot, monde, capsys):
    donner_accord(depot)
    mort = subprocess.Popen([sys.executable, "-c", "pass"])
    mort.wait()
    verrou(depot).parent.mkdir(parents=True, exist_ok=True)
    verrou(depot).write_text(json.dumps({"pid": mort.pid, "equipe": "y", "sha": "b" * 40,
                                         "depuis": "2026-01-01T00:00:00.000Z"}))
    code, sortie, _ = lancer(depot, capsys)
    assert code == 0, sortie
    assert f"verrou repris : la fusion de y (bbbbbbb) du pid {mort.pid} n'existe plus" in sortie
    propre(depot, monde)


def test_verrou_contient_pid_equipe_sha_heure(depot, monde, capsys):
    donner_accord(depot)
    vu = {}

    def suite(p, d):
        vu.update(json.loads(verrou(depot).read_text()))
        return 0, "1 passed in 0.1s\n"
    monde.suite = suite
    assert lancer(depot, capsys)[0] == 0
    assert vu["pid"] == os.getpid() and vu["equipe"] == "x" and vu["sha"] == sha_de(depot, "equipe/x")
    assert re.match(r"\d{4}-\d\d-\d\dT", vu["depuis"])


@pytest.mark.parametrize("erreur", [RuntimeError("panne"), KeyboardInterrupt()])
def test_verrou_et_essai_liberes_apres_exception_ou_interruption(depot, monde, capsys, erreur):
    donner_accord(depot)

    def suite(p, d):
        raise erreur
    monde.suite = suite
    with pytest.raises(type(erreur)):
        fusionner.executer(argparse.Namespace(equipe="x", maintenant=False, message=None))
    capsys.readouterr()
    propre(depot, monde)
    assert sha_de(depot, "main") == sha_de(depot, "main")
    # le verrou se reprend aussitôt
    v = fusionner._Verrou(depot, "x", "c" * 40)
    v.prendre()
    v.liberer()


def test_main_inchange_apres_exception(depot, monde, capsys):
    donner_accord(depot)
    avant = sha_de(depot, "main")
    monde.suite = lambda p, d: (_ for _ in ()).throw(RuntimeError("panne"))
    with pytest.raises(RuntimeError):
        fusionner.executer(argparse.Namespace(equipe="x", maintenant=False, message=None))
    assert sha_de(depot, "main") == avant


# --- charge de la machine ----------------------------------------------------------------------

class Horloge:
    def __init__(self):
        self.t = 0.0
        self.pauses = []

    def __call__(self):
        return self.t

    def dormir(self, s):
        self.pauses.append(s)
        self.t += s


@pytest.fixture
def horloge(monkeypatch):
    h = Horloge()
    monkeypatch.setattr(fusionner, "_horloge", h)
    monkeypatch.setattr(fusionner, "_dormir", h.dormir)
    return h


def test_workers_actifs_la_commande_attend_et_le_dit(depot, monde, capsys, horloge):
    donner_accord(depot)
    monde.workers = 2
    comptes = iter([2, 2, 1] + [1] * 6 + [0])
    monkey = pytest.MonkeyPatch()
    monkey.setattr(fusionner, "_workers_actifs", lambda p: next(comptes))
    try:
        code, sortie, _ = lancer(depot, capsys)
    finally:
        monkey.undo()
    assert code == 0, sortie
    assert horloge.pauses and set(horloge.pauses) == {15}
    assert "2 worker(s) en cours : j'attends" in sortie
    # un message de statut par minute, pas un par sondage
    statuts = [l for l in sortie.splitlines() if "en cours : j'attends" in l]
    assert len(statuts) == 3 and len(horloge.pauses) == 9


def test_workers_actifs_avec_maintenant_passe_sans_attendre(depot, monde, capsys, horloge):
    donner_accord(depot)
    monde.workers = 3
    code, sortie, _ = lancer(depot, capsys, maintenant=True)
    assert code == 0 and horloge.pauses == []
    assert "3 worker(s) en cours : --maintenant" in sortie


def test_delai_depasse_refuse_code_occupe(depot, monde, capsys, horloge):
    donner_accord(depot)
    monde.workers = 1
    code, _, erreur = lancer(depot, capsys)
    assert code == 2 and "1 worker(s) en cours après 20 minutes" in erreur
    assert sum(horloge.pauses) == 20 * 60
    assert monde.suites == [] and not any(a[:2] == ("worktree", "add") for a in monde.git)
    assert not verrou(depot).exists()


def test_charge_inconnue_est_dite_pas_tue(depot, monde, capsys, monkeypatch):
    donner_accord(depot)
    monkeypatch.setattr(fusionner, "_workers_actifs", lambda p: None)
    code, sortie, _ = lancer(depot, capsys)
    assert code == 0 and "charge de la machine inconnue" in sortie


# --- identité --------------------------------------------------------------------------------

@pytest.mark.parametrize("nom", ["coord-fondation", "worker-fondation-t1", "integration", None])
def test_autre_identite_refusee_par_la_commande_elle_meme(depot, monde, capsys, monkeypatch, nom):
    donner_accord(depot)
    identite(monkeypatch, nom)
    code, _, erreur = lancer(depot, capsys)
    assert code == 1 and "réservé à l'Assistant et à l'utilisateur" in erreur
    assert monde.git == [] and monde.suites == []


@pytest.mark.parametrize("nom", ["assistant", "utilisateur"])
def test_assistant_et_utilisateur_passent(depot, monde, capsys, monkeypatch, nom):
    donner_accord(depot)
    identite(monkeypatch, nom)
    code, _, _ = lancer(depot, capsys)
    assert code == 0
    assert LIGNE_JOURNAL.match(lignes_journal(depot)[0]).group(1) == nom


# --- tête figée --------------------------------------------------------------------------------

def test_branche_qui_avance_pendant_l_essai_c_est_l_ancien_sha_qui_est_fusionne(depot, monde, capsys):
    donner_accord(depot)
    ancien = sha_de(depot, "equipe/x")

    def suite(p, d):
        arbre = subprocess.run(["git", "-C", str(depot), "rev-parse", f"{ancien}^{{tree}}"],
                               capture_output=True, text=True).stdout.strip()
        nouveau = subprocess.run(
            ["git", "-C", str(depot), "-c", "user.name=t", "-c", "user.email=t@t", "commit-tree",
             arbre, "-p", ancien, "-m", "plus tard"], capture_output=True, text=True).stdout.strip()
        subprocess.run(["git", "-C", str(depot), "update-ref", "refs/heads/equipe/x", nouveau], check=True)
        return 0, "1 passed in 0.1s\n"
    monde.suite = suite
    code, _, _ = lancer(depot, capsys)
    nouveau = sha_de(depot, "equipe/x")
    assert code == 0 and nouveau != ancien
    ancetre = lambda s: subprocess.run(["git", "-C", str(depot), "merge-base", "--is-ancestor", s, "main"]).returncode == 0
    assert ancetre(ancien) and not ancetre(nouveau)
    assert all(LIGNE_JOURNAL.match(l).group(2) == ancien for l in lignes_journal(depot))


# --- fusion dans main qui échoue après un essai vert ---------------------------------------------

def test_main_qui_a_bouge_pendant_l_essai_refuse_proprement(depot, monde, capsys):
    ecrire(depot, {"f.txt": "base\n"})
    valider(depot, "base")
    _git("branch", "-f", "equipe/x", "main", cwd=depot)
    avec_fichier(depot, "f.txt", "equipe\n")
    donner_accord(depot)

    def suite(p, d):                 # un commit direct sur main pendant la suite
        ecrire(depot, {"f.txt": "direct\n"})
        valider(depot, "direct")
        return 0, "1 passed in 0.1s\n"
    monde.suite = suite
    avant_direct = sha_de(depot, "main")
    code, _, erreur = lancer(depot, capsys)
    assert code == 1 and "dépôt principal a échoué" in erreur
    assert sha_de(depot, "main") != avant_direct                       # le commit direct est resté
    assert subprocess.run(["git", "-C", str(depot), "status", "--porcelain", "--untracked-files=no"],
                          capture_output=True, text=True).stdout == ""   # pas de fusion à moitié faite
    assert [LIGNE_JOURNAL.match(l).group(4) for l in lignes_journal(depot)[1:]] == [
        "resultat=non-fusionne", "resultat=refuse-main"]
    assert journal_registre(depot, "fusion_refusee")[0][3] == "refuse-main"
    assert monde.reinstallations == [] and monde.facteurs == []
    propre(depot, monde)


# --- effets de bord réels ------------------------------------------------------------------------

def test_arreter_le_facteur_envoie_sigterm_au_pid_inscrit(tmp_path):
    (tmp_path / ".orga" / "etat").mkdir(parents=True)
    proc = subprocess.Popen(["sleep", "30"])
    try:
        (tmp_path / ".orga" / "etat" / "facteur.pid").write_text(f"{proc.pid}\n")
        assert f"pid {proc.pid}" in fusionner._arreter_facteur(tmp_path)
        assert proc.wait(timeout=5) == -signal.SIGTERM
        assert "ne tourne pas" in fusionner._arreter_facteur(tmp_path)
    finally:
        proc.kill()
        proc.wait()


def test_arreter_le_facteur_sans_fichier_ne_fait_rien(tmp_path):
    assert "rien à arrêter" in fusionner._arreter_facteur(tmp_path)


def test_la_suite_est_la_ligne_de_la_ci_dans_l_essai(tmp_path, monkeypatch):
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text('#!/bin/sh\necho "args=$*"\necho "cwd=$(pwd -P)"\necho "agent=${CIME_AGENT-absent}"\n'
                     'echo "projet=${CIME_PROJET-absent}"\nexit 3\n')
    python.chmod(0o755)
    essai = tmp_path / "essai"
    essai.mkdir()
    monkeypatch.setenv("CIME_AGENT", "assistant")
    monkeypatch.setenv("CIME_PROJET", str(tmp_path))
    code, sortie = fusionner._lancer_suite(tmp_path, essai)
    assert code == 3
    assert "args=-m pytest tests -q -p no:cacheprovider" in sortie
    assert f"cwd={essai.resolve()}" in sortie
    assert "agent=absent" in sortie and "projet=absent" in sortie


def test_sans_python_du_projet_la_suite_ne_se_lance_pas(tmp_path):
    with pytest.raises(fusionner._Refus, match="pas de Python du projet"):
        fusionner._lancer_suite(tmp_path, tmp_path)


def test_essai_reel_avec_une_vraie_suite_de_deux_tests(depot, monde, capsys, monkeypatch):
    """Sans double de suite : un vrai pytest sur un dépôt jetable qui porte deux tests."""
    _git("checkout", "-q", "equipe/x", cwd=depot)
    ecrire(depot, {"tests/test_deux.py": "def test_un():\n    assert 1\n\n\ndef test_deux():\n    assert 2\n"})
    valider(depot, "tests")
    _git("checkout", "-q", "main", cwd=depot)
    (depot / ".venv" / "bin").mkdir(parents=True)
    python = depot / ".venv" / "bin" / "python"
    python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    python.chmod(0o755)
    donner_accord(depot)
    monkeypatch.setattr(fusionner, "_suite", fusionner._lancer_suite)
    code, sortie, _ = lancer(depot, capsys)
    assert code == 0, sortie
    assert re.search(r"suite entière : 2 tests en", sortie)
    propre(depot, monde)


def test_branche_qui_avance_pendant_l_attente_l_essai_fusionne_l_ancien_sha(depot, monde, capsys, monkeypatch):
    """Entre le moment où la tête est figée et l'essai (la charge, le verrou), la branche avance."""
    from test_garde_fusionner import avancer
    avec_fichier(depot)
    donner_accord(depot)
    avant, ancien = sha_de(depot, "main"), sha_de(depot, "equipe/x")

    def charge(projet):
        avancer(depot)
        return 0
    monkeypatch.setattr(fusionner, "_workers_actifs", charge)
    code, sortie, _ = lancer(depot, capsys)
    assert code == 0, sortie
    assert monde.parents_a_la_suite == [[avant, ancien]]
    assert sha_de(depot, "equipe/x") != ancien
    assert subprocess.run(["git", "-C", str(depot), "rev-list", "--parents", "-n", "1", "main"],
                          capture_output=True, text=True).stdout.split()[1:] == [avant, ancien]
