"""Suites d'une fusion, contrats modifiés, intégration restreinte.

Projets et dépôts git jetables ; aucun test n'écrit dans le vrai registre ni ne lance tmux.
"""
import argparse
import io
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from aide import cime, lignes
from cime.fondation import garde, hook, init
from cime.fondation.nom import VAR_AGENT, VAR_PROJET
from cime.fondation.projet import ErreurProjet, lire_manifeste
from cime.fondation.registre import inscrire_message, inscrire_transition, ouvrir
from cime.signaux import ordres, suites

MANIFESTE = textwrap.dedent("""\
    nom = "Essai"
    prefixe = "cc"
    branche_reference = "main"
    branche_equipe = "equipe/{equipe}"
    worktree_equipe = ".orga/worktrees/{equipe}"
    equipes_speciales = ["assistant", "verification"]
    modele_assistant = "m"
    modele_coordinateur = "m"

    [contrats]
    etat = ["hote", "page"]
    "format-2.0" = ["observation"]
    api = ["fondation"]
    """)


def _git(*args, cwd):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   cwd=cwd, check=True, capture_output=True)


def _ecrire(chemin: Path, texte: str):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(texte)


@pytest.fixture
def depot(tmp_path, monkeypatch):
    """Dépôt principal (main) avec un projet, la branche equipe/x en avance d'un commit."""
    p = tmp_path / "depot"
    _ecrire(p / ".orga" / "projet.toml", MANIFESTE)
    for e in ("x", "hote", "page", "observation", "fondation"):
        (p / ".orga" / "teams" / e / "conversations").mkdir(parents=True)
    _ecrire(p / "src" / "exemple.json", '{"v": 1}\n')
    _ecrire(p / ".orga" / "contracts" / "etat.schema.md", "# etat\n")
    _git("init", "-q", "-b", "main", cwd=p)
    _git("add", ".", cwd=p)
    _git("commit", "-q", "-m", "init", cwd=p)
    _git("checkout", "-q", "-b", "equipe/x", cwd=p)
    _ecrire(p / "src" / "nouveau.txt", "x\n")
    _git("add", ".", cwd=p)
    _git("commit", "-q", "-m", "x", cwd=p)
    _git("checkout", "-q", "main", cwd=p)
    monkeypatch.setenv(VAR_PROJET, str(p))
    monkeypatch.delenv(VAR_AGENT, raising=False)
    monkeypatch.delenv("TMUX", raising=False)
    return p


def sha(depot, ref="HEAD"):
    return subprocess.run(["git", "rev-parse", ref], cwd=depot, capture_output=True, text=True,
                          check=True).stdout.strip()


def travail_pret(monkeypatch, depot, *specs, equipe_agent="coord-x"):
    argv = ["envoyer", "--a", "assistant", "--nature", "travail_pret"]
    for s in specs:
        argv += ["--suite", s]
    return cime(monkeypatch, equipe_agent, *argv, "rendu", projet=depot)


# --- déclarer --suite ---------------------------------------------------------------------

def test_suite_rangee_dans_la_preuve_du_travail_pret(depot, monkeypatch, capsys):
    assert travail_pret(monkeypatch, depot, "recopier:src/exemple.json:.orga/contracts/exemples/etat-exemple.json",
                        "migrer", "migrer") == 0
    ident = int(capsys.readouterr().out.strip())
    [(preuve,)] = lignes(depot, "SELECT preuve FROM transitions WHERE message_id = ? AND etat = 'inscrit'", (ident,))
    suites_ = json.loads(preuve)["suites"]
    assert suites_ == ["recopier:src/exemple.json:.orga/contracts/exemples/etat-exemple.json", "migrer"]
    assert lignes(depot, "SELECT corps FROM messages WHERE id = ?", (ident,)) == [(None,)]   # pas dans le texte livré
    assert lignes(depot, "SELECT name FROM sqlite_master WHERE name LIKE '%suite%'") == []   # pas de nouvelle table


@pytest.mark.parametrize("spec", [
    "reinstaller", "recopier", "recopier:a", "recopier:a:b:c", "migrer:x", "n'importe quoi", "",
    "recopier:/etc/passwd:src/x", "recopier:src/a:/tmp/x", "recopier:../dehors:src/x",
    "recopier:src/a:../../dehors", "recopier:src/../../x:src/y"])
def test_suite_refusee_avec_la_liste_des_specs_valides(depot, monkeypatch, capsys, spec):
    assert travail_pret(monkeypatch, depot, spec) == 2
    erreur = capsys.readouterr().err
    assert "migrer" in erreur or "projet" in erreur
    assert lignes(depot, "SELECT count(*) FROM messages") == [(0,)]


def test_suite_inconnue_dit_les_specs_valides(depot, monkeypatch, capsys):
    travail_pret(monkeypatch, depot, "reinstaller")
    assert "recopier:<source>:<cible> | migrer" in capsys.readouterr().err


def test_suite_hors_projet_par_lien_symbolique_refusee(depot, monkeypatch, tmp_path):
    (tmp_path / "ailleurs").mkdir()
    os.symlink(tmp_path / "ailleurs", depot / "lien")
    assert travail_pret(monkeypatch, depot, "recopier:src/exemple.json:lien/copie.json") == 2


@pytest.mark.parametrize("nature,a,de", [("compte_rendu", "assistant", "coord-x"),
                                        ("question", "assistant", "coord-x"),
                                        ("travail_pret", "coord-x", "worker-x-t1")])
def test_suite_refusee_hors_travail_pret_vers_l_assistant(depot, monkeypatch, capsys, nature, a, de):
    assert cime(monkeypatch, de, "envoyer", "--a", a, "--nature", nature, "--suite", "migrer", "r",
                projet=depot) == 2
    assert "--suite" in capsys.readouterr().err
    assert lignes(depot, "SELECT count(*) FROM messages") == [(0,)]


def test_suite_par_repondre(depot, monkeypatch, capsys):
    assert cime(monkeypatch, "assistant", "envoyer", "--a", "coord-x", "--nature", "consigne",
                "--attend", "travail_pret", "fais-le", projet=depot) == 0
    consigne = int(capsys.readouterr().out.strip())
    assert cime(monkeypatch, "coord-x", "repondre", str(consigne), "--nature", "travail_pret",
                "--suite", "migrer", "rendu") == 0
    ident = int(capsys.readouterr().out.strip())
    [(preuve,)] = lignes(depot, "SELECT preuve FROM transitions WHERE message_id = ? AND etat = 'inscrit'", (ident,))
    assert json.loads(preuve)["suites"] == ["migrer"]
    assert cime(monkeypatch, "coord-x", "repondre", str(consigne), "--suite", "migrer", "non") == 2   # pas un travail_pret


# --- la fusion inscrit la consigne suites:<é> ---------------------------------------------------

SPEC_RECOPIE = "recopier:src/exemple.json:.orga/contracts/exemples/etat-exemple.json"


def preparer_travail_pret(monkeypatch, depot, capsys, *specs, equipe_agent="coord-x"):
    assert travail_pret(monkeypatch, depot, *specs, equipe_agent=equipe_agent) == 0
    return int(capsys.readouterr().out.strip())


def consignes_suites(depot):
    return lignes(depot, "SELECT id, de, a, objet, equipe FROM messages WHERE nature = 'consigne'"
                         " AND objet LIKE 'suites:%' ORDER BY id")


def test_fusion_simulee_inscrit_une_seule_consigne_par_equipe_et_par_fusion(depot, monkeypatch, capsys):
    preparer_travail_pret(monkeypatch, depot, capsys, SPEC_RECOPIE)
    s = sha(depot, "equipe/x")
    conn = ouvrir(depot)
    try:
        premiere = suites.apres_fusion_suites(conn, depot, [("equipe/x", s, "fusionne")], 7)
        assert len(premiere) == 1
        assert suites.apres_fusion_suites(conn, depot, [("equipe/x", s, "fusionne")], 8) == []   # idempotent
        assert suites.apres_fusion_suites(conn, depot, [("equipe/x", s, "non-fusionne")], 9) == []
        assert suites.apres_fusion_suites(conn, depot, [("equipe/autre", "abc", "fusionne")], 9) == []
    finally:
        conn.close()
    assert consignes_suites(depot) == [(premiere[0], "cime", "assistant", "suites:x", "x")]
    [(attendu, debiteur)] = lignes(depot, "SELECT attendu, debiteur FROM obligations WHERE message_id = ?",
                                   (premiere[0],))
    assert (attendu, debiteur) == ("action", "assistant")
    [(preuve,)] = lignes(depot, "SELECT preuve FROM transitions WHERE message_id = ? AND etat = 'inscrit'",
                         (premiere[0],))
    assert json.loads(preuve)["cle"] == s


def test_pas_de_consigne_sans_suite_declaree(depot, monkeypatch, capsys):
    preparer_travail_pret(monkeypatch, depot, capsys)       # un travail_pret sans --suite
    conn = ouvrir(depot)
    try:
        assert suites.apres_fusion_suites(conn, depot, [("equipe/x", sha(depot, "equipe/x"), "fusionne")], 1) == []
    finally:
        conn.close()
    assert consignes_suites(depot) == []


def test_la_consigne_suites_suit_l_echelle_des_suites_de_fusion():
    from cime.signaux import echeances
    assert echeances.type_obligation("consigne", "action", "assistant", "suites:x") == "suites_fusion"
    e = echeances.ECHELLES["suites_fusion"]
    assert [x.delai.total_seconds() // 60 for x in e] == [0, 10, 20]      # 10 min relance, 30 min l'utilisateur


# --- le hook PostToolUse d'une vraie fusion --------------------------------------------------------

def _donner_accord(depot, ref="equipe/x", equipe="x"):
    conn = ouvrir(depot)
    try:
        ident = inscrire_message(conn, de="utilisateur", a="assistant", nature="accord", resume="accord",
                                 equipe=equipe, objet=f"fusion:{equipe}:{sha(depot, ref)}")
        for etat in ("inscrit", "livre", "pris_en_compte"):
            inscrire_transition(conn, ident, etat, "utilisateur", {})
    finally:
        conn.close()


def _hook(monkeypatch, depot, evenement, commande):
    monkeypatch.setenv(VAR_AGENT, "assistant")
    entree = {"hook_event_name": evenement, "session_id": "s", "cwd": str(depot),
              "tool_name": "Bash", "tool_input": {"command": commande}}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(entree)))
    # 2 : le hook rend du courrier à l'Assistant (la consigne `suites:`), c'est son contrat
    assert hook.executer(argparse.Namespace(evenement=evenement)) in (0, 2)


def _fusionner_par_la_file(monkeypatch, depot):
    """`cime fusionner x` en processus, sans la suite entière ni la réinstallation ; git est réel."""
    from cime.fondation import fusionner
    monkeypatch.setenv(VAR_AGENT, "assistant")
    monkeypatch.setattr(fusionner, "_suite", lambda projet, dossier: (0, "2 passed in 0.10s\n"))
    monkeypatch.setattr(fusionner, "_workers_actifs", lambda projet: 0)
    monkeypatch.setattr(fusionner, "_reinstaller", lambda projet: (True, ""))
    monkeypatch.setattr(fusionner, "_arreter_facteur", lambda projet: "facteur arrêté")
    assert fusionner.fusionner(depot, "x", maintenant=True) == 0


def test_fusion_reelle_inscrit_les_suites_et_signale_les_lecteurs_du_contrat(depot, monkeypatch, capsys):
    preparer_travail_pret(monkeypatch, depot, capsys, SPEC_RECOPIE)
    # la branche touche le contrat `etat` : les contrats modifiés doivent signaler hote et page seulement
    _git("checkout", "-q", "equipe/x", cwd=depot)
    _ecrire(depot / ".orga" / "contracts" / "etat.schema.md", "# etat 2\n")
    _git("commit", "-qam", "contrat", cwd=depot)
    _git("checkout", "-q", "main", cwd=depot)
    _donner_accord(depot)
    _fusionner_par_la_file(monkeypatch, depot)
    assert len(consignes_suites(depot)) == 1
    signaux = lignes(depot, "SELECT a, objet FROM messages WHERE nature = 'signalement' ORDER BY a")
    assert signaux == [("coord-hote", "contrat:etat"), ("coord-page", "contrat:etat")]
    # le hook rejoué sur la commande ne redit rien : la file a tout fait elle-même
    commande = "cime fusionner x"
    _hook(monkeypatch, depot, "PostToolUse", commande)
    assert len(consignes_suites(depot)) == 1
    assert lignes(depot, "SELECT count(*) FROM messages WHERE nature = 'signalement'") == [(2,)]


def test_fusion_qui_ne_touche_aucun_contrat_ne_signale_personne(depot, monkeypatch, capsys):
    _donner_accord(depot)
    _fusionner_par_la_file(monkeypatch, depot)
    assert lignes(depot, "SELECT count(*) FROM messages WHERE nature = 'signalement'") == [(0,)]


# --- cime suites <équipe> ------------------------------------------------------------------------------

def test_suites_refusee_par_un_autre_que_l_assistant(depot, monkeypatch, capsys):
    preparer_travail_pret(monkeypatch, depot, capsys, SPEC_RECOPIE)
    for agent in ("coord-x", None):
        assert cime(monkeypatch, agent, "suites", "x", projet=depot) == 2
    assert "réservé à l'Assistant" in capsys.readouterr().err


def test_suites_avant_la_fusion_refusee(depot, monkeypatch, capsys):
    preparer_travail_pret(monkeypatch, depot, capsys, SPEC_RECOPIE)
    assert cime(monkeypatch, "assistant", "suites", "x", projet=depot) == 2
    assert "pas encore dans la branche de référence" in capsys.readouterr().err
    assert not (depot / ".orga" / "contracts" / "exemples" / "etat-exemple.json").exists()


def test_suites_sans_declaration_refusee(depot, monkeypatch, capsys):
    assert cime(monkeypatch, "assistant", "suites", "x", projet=depot) == 2
    assert "ne déclare de suite" in capsys.readouterr().err


def fusionner(depot):
    _git("merge", "--no-ff", "-m", "x", "equipe/x", cwd=depot)


def test_suites_apres_la_fusion_deux_executions_meme_resultat(depot, monkeypatch, capsys):
    preparer_travail_pret(monkeypatch, depot, capsys, SPEC_RECOPIE)
    s = sha(depot, "equipe/x")
    conn = ouvrir(depot)
    obligation = suites.apres_fusion_suites(conn, depot, [("equipe/x", s, "fusionne")], 1)[0]
    conn.close()
    fusionner(depot)
    cible = depot / ".orga" / "contracts" / "exemples" / "etat-exemple.json"
    assert cime(monkeypatch, "assistant", "suites", "x", projet=depot) == 0
    premiere = capsys.readouterr().out
    assert "copié" in premiere and cible.read_text() == '{"v": 1}\n'
    assert lignes(depot, "SELECT etat FROM obligations WHERE message_id = ?", (obligation,)) == [("satisfaite",)]
    assert lignes(depot, "SELECT etat FROM transitions WHERE message_id = ? ORDER BY id", (obligation,))[-1] == ("clos",)
    assert cime(monkeypatch, "assistant", "suites", "x", projet=depot) == 0
    seconde = capsys.readouterr().out
    assert "déjà identique, rien à faire" in seconde
    assert [l for l in seconde.splitlines() if l.startswith("recopier")] == [
        "recopier src/exemple.json → .orga/contracts/exemples/etat-exemple.json : déjà identique, rien à faire"]
    assert cible.read_text() == '{"v": 1}\n'


def test_suite_migrer_appelle_init_migrer_une_fois_par_execution(depot, monkeypatch, capsys):
    appels = []
    monkeypatch.setattr(init, "installer", lambda args: appels.append(args) or {
        "ajouté": [], "complété": [], "migration": [], "déjà présent": [], "avertissements": []})
    preparer_travail_pret(monkeypatch, depot, capsys, "migrer")
    fusionner(depot)
    assert cime(monkeypatch, "assistant", "suites", "x", projet=depot) == 0
    assert "migrer : init --migrer exécuté (0 ajouté(s), 0 complété(s))" in capsys.readouterr().out
    assert len(appels) == 1 and appels[0].migrer is True and Path(appels[0].dossier) == depot


def test_recopier_source_absente_ne_ferme_pas_l_obligation(depot, monkeypatch, capsys):
    preparer_travail_pret(monkeypatch, depot, capsys, "recopier:src/absent.json:src/copie.json")
    conn = ouvrir(depot)
    obligation = suites.apres_fusion_suites(conn, depot, [("equipe/x", sha(depot, "equipe/x"), "fusionne")], 1)[0]
    conn.close()
    fusionner(depot)
    assert cime(monkeypatch, "assistant", "suites", "x", projet=depot) == 2
    assert "source absente" in capsys.readouterr().err
    assert lignes(depot, "SELECT etat FROM obligations WHERE message_id = ?", (obligation,)) == [("ouverte",)]


# --- [contrats] du manifeste ------------------------------------------------------------------------------

def test_manifeste_lit_la_table_contrats(depot):
    assert lire_manifeste(depot).contrats == {
        "etat": ["hote", "page"], "format-2.0": ["observation"], "api": ["fondation"]}


def test_manifeste_sans_contrats_donne_une_table_vide(tmp_path):
    p = tmp_path / "p"
    _ecrire(p / ".orga" / "projet.toml", MANIFESTE.split("[contrats]")[0])
    assert lire_manifeste(p).contrats == {}


@pytest.mark.parametrize("extra", ['\n[contrats]\netat = "hote"\n', '\n[contrats]\netat = [1]\n',
                                   '\n[contrats]\netat = [""]\n', '\ncontrats = 3\n',
                                   '\n[contrats]\nformat-2.0 = ["a"]\n'])   # clé non quotée = table imbriquée
def test_contrats_invalides_refuses(tmp_path, extra):
    p = tmp_path / "p"
    _ecrire(p / ".orga" / "projet.toml", MANIFESTE.split("[contrats]")[0] + extra)
    with pytest.raises(ErreurProjet, match="contrats"):
        lire_manifeste(p)


@pytest.mark.parametrize("chemin,nom", [
    (".orga/contracts/etat.schema.md", "etat"), (".orga/contracts/format-2.0.schema.md", "format-2.0"),
    (".orga/contracts/exemples/etat-exemple.json", "etat"), (".orga/contracts/exemples/journal-exemple.json", "journal"),
    (".orga/contracts/CHANGELOG.md", None), (".orga/contracts/sous/etat.schema.md", None),
    ("src/etat.schema.md", None)])
def test_nom_du_contrat(chemin, nom):
    assert suites.nom_du_contrat(chemin) == nom


def _commit_contrat(depot, fichier):
    _ecrire(depot / fichier, "changé\n")
    _git("add", ".", cwd=depot)
    _git("commit", "-qm", "contrat", cwd=depot)


def contrats(conn_depot):
    return lignes(conn_depot, "SELECT a, objet FROM messages WHERE nature = 'signalement' ORDER BY a, objet")


def test_contrat_touche_signale_les_seules_equipes_lectrices(depot):
    avant = sha(depot)
    _commit_contrat(depot, ".orga/contracts/etat.schema.md")
    conn = ouvrir(depot)
    try:
        assert len(suites.apres_fusion_contrats(conn, depot, avant, sha(depot))) == 2
    finally:
        conn.close()
    assert contrats(depot) == [("coord-hote", "contrat:etat"), ("coord-page", "contrat:etat")]


def test_exemple_touche_signale_le_contrat_de_meme_nom_et_pas_deux_fois(depot):
    avant = sha(depot)
    _commit_contrat(depot, ".orga/contracts/exemples/etat-exemple.json")
    conn = ouvrir(depot)
    try:
        assert len(suites.apres_fusion_contrats(conn, depot, avant, sha(depot))) == 2
        assert suites.apres_fusion_contrats(conn, depot, avant, sha(depot)) == []     # unique par (contrat, sha)
    finally:
        conn.close()
    assert lignes(depot, "SELECT count(*) FROM messages WHERE nature = 'signalement'") == [(2,)]


def test_un_autre_sha_du_meme_contrat_signale_de_nouveau(depot):
    avant = sha(depot)
    _commit_contrat(depot, ".orga/contracts/etat.schema.md")
    milieu = sha(depot)
    _ecrire(depot / ".orga" / "contracts" / "etat.schema.md", "encore\n")
    _git("commit", "-qam", "bis", cwd=depot)
    conn = ouvrir(depot)
    try:
        suites.apres_fusion_contrats(conn, depot, avant, milieu)
        assert len(suites.apres_fusion_contrats(conn, depot, milieu, sha(depot))) == 2
    finally:
        conn.close()
    assert lignes(depot, "SELECT count(*) FROM messages WHERE nature = 'signalement'") == [(4,)]


def test_contrat_inconnu_du_manifeste_ou_manifeste_sans_contrats_ne_signale_personne(depot):
    avant = sha(depot)
    _commit_contrat(depot, ".orga/contracts/structure.schema.md")          # absent de [contrats]
    conn = ouvrir(depot)
    try:
        assert suites.apres_fusion_contrats(conn, depot, avant, sha(depot)) == []
        _ecrire(depot / ".orga" / "projet.toml", MANIFESTE.split("[contrats]")[0])
        _commit_contrat(depot, ".orga/contracts/etat.schema.md")
        assert suites.apres_fusion_contrats(conn, depot, avant, sha(depot)) == []
    finally:
        conn.close()
    assert contrats(depot) == []


def test_fichier_hors_contrats_ne_signale_rien(depot):
    avant = sha(depot)
    _commit_contrat(depot, "src/etat.schema.md")
    conn = ouvrir(depot)
    try:
        assert suites.apres_fusion_contrats(conn, depot, avant, sha(depot)) == []
        assert suites.apres_fusion_contrats(conn, depot, "", sha(depot)) == []     # « avant » inconnu : rien
    finally:
        conn.close()


# --- intégration restreinte ----------------------------------------------------------------------------------------

@pytest.fixture
def sans_git(tmp_path, monkeypatch):
    """Projet jetable avec l'équipe intégration et ses requêtes (sans dépôt git)."""
    from aide import fabriquer_projet
    racine = fabriquer_projet(tmp_path / "p", equipes=("x", "integration"))
    (racine / ".orga" / "teams" / "integration" / "requests" / "todo").mkdir(parents=True)
    (racine / ".orga" / "teams" / "integration" / "requests" / "todo" / "r1.md").write_text("req")
    monkeypatch.setenv(VAR_PROJET, str(racine))
    monkeypatch.delenv(VAR_AGENT, raising=False)
    return racine


def _lancer_integration(monkeypatch, projet, agent, requete="r1"):
    return cime(monkeypatch, agent, "lancer", "worker", "integration", requete, "--modele", "claude-haiku-5-5",
                projet=projet)


def test_un_coordinateur_ne_lance_pas_le_worker_d_integration(sans_git, monkeypatch, capsys):
    capteur = []
    monkeypatch.setattr(ordres, "poser_et_attendre", lambda *a: capteur.append(a) or (1, {"etat": "execute"}))
    for agent in ("coord-x", "coord-integration"):
        assert _lancer_integration(monkeypatch, sans_git, agent) == 2
        erreur = capsys.readouterr().err
        assert "demande-le à l'Assistant" in erreur and "--objet integration:" in erreur
    assert capteur == [] and lignes(sans_git, "SELECT count(*) FROM ordres") == [(0,)]


def test_l_assistant_lance_le_worker_d_integration_sans_accord(sans_git, monkeypatch, capsys):
    capteur = []
    monkeypatch.setattr(ordres, "poser_et_attendre",
                        lambda projet, auteur, verbe, cible, params: capteur.append((auteur, verbe, cible, params))
                        or (7, {"etat": "execute", "texte": "ok", "code": 0}))
    code = _lancer_integration(monkeypatch, sans_git, "assistant")
    assert code == 0
    assert capteur == [("assistant", "lancer", "worker-integration-r1",
                        {"role": "worker", "equipe": "integration", "tache": "r1", "modele": "claude-haiku-5-5"})]


def test_l_assistant_et_la_requete_absente(sans_git, monkeypatch, capsys):
    assert _lancer_integration(monkeypatch, sans_git, "assistant", requete="inconnue") == 2
    assert "requête absente" in capsys.readouterr().err


def test_le_lancement_d_integration_n_inscrit_pas_de_consigne_de_tache(sans_git, monkeypatch):
    from cime.fondation import lancer
    monkeypatch.setattr(ordres, "_lancer", lambda args, projet: ("cc-worker-integration-r1", 0))
    ordres._executer_lancer(sans_git, 1, {"role": "worker", "equipe": "integration", "tache": "r1",
                                          "modele": "m"})
    assert lignes(sans_git, "SELECT count(*) FROM messages") == [(0,)]
    ordres._executer_lancer(sans_git, 2, {"role": "worker", "equipe": "x", "tache": "t1", "modele": "m"})
    assert lignes(sans_git, "SELECT objet FROM messages") == [("tache:x:t1",)]


# --- la garde : même refus, même message ------------------------------------------------------------------------------

def _decider(monkeypatch, agent, commande, tmp_path):
    monkeypatch.setenv(VAR_AGENT, agent)
    return garde.decider({"tool_name": "Bash", "tool_input": {"command": commande}, "cwd": str(tmp_path)}, None)


@pytest.mark.parametrize("commande", [
    "cime lancer worker integration r1 --modele m", "cime lancer worker integration r1",
    "uv run cime lancer worker integration r1"])
def test_la_garde_refuse_le_worker_d_integration_a_un_coordinateur(monkeypatch, tmp_path, commande):
    for agent in ("coord-x", "coord-integration"):
        motif = _decider(monkeypatch, agent, commande, tmp_path)
        assert motif and "demande-le à l'Assistant" in motif
        assert "--objet integration:" in motif and agent[len("coord-"):] in motif


def test_la_garde_laisse_un_coordinateur_lancer_les_workers_de_son_equipe(monkeypatch, tmp_path):
    assert _decider(monkeypatch, "coord-x", "cime lancer worker x t1 --modele m", tmp_path) is None
    assert _decider(monkeypatch, "coord-x", "cime lancer worker y t1 --modele m", tmp_path)   # l'équipe d'un autre


def test_la_garde_ne_touche_pas_l_assistant(monkeypatch, tmp_path):
    assert _decider(monkeypatch, "assistant", "cime lancer worker integration r1 --modele m", tmp_path) is None


# --- init : plus d'équipe intégration par défaut ----------------------------------------------------------------------------

def _installer(dossier, monkeypatch):
    monkeypatch.setattr(init, "executable_cime", lambda: "/opt/outils/bin/cime")
    # `cime` est un paquet-espace de noms (dépôt principal + worktree) : on ne lit que les gabarits de CE code
    monkeypatch.setattr(init.importlib.resources, "files", lambda _: Path(init.__file__).parents[1])
    return init.installer(argparse.Namespace(dossier=str(dossier), utilisateur="Camille", nom_projet=None,
                                             prefixe=None, migrer=False, hooks_sans_cime=False))


def test_init_d_un_projet_neuf_sans_equipe_integration(tmp_path, monkeypatch):
    p = tmp_path / "neuf"
    _installer(p, monkeypatch)
    assert not (p / ".orga" / "teams" / "integration").exists()
    m = lire_manifeste(p)
    assert "integration" not in m.equipes_speciales and m.equipes_speciales == ["assistant", "verification"]
    assert "[contrats]" in (p / ".orga" / "projet.toml").read_text() and m.contrats == {}
    assert (p / ".orga" / "socle" / "integration.md").is_file()      # le socle reste : l'Assistant peut la créer


def test_init_d_un_projet_qui_l_a_deja_conserve_dossier_et_manifeste(tmp_path, monkeypatch):
    p = tmp_path / "ancien"
    _ecrire(p / ".orga" / "teams" / "integration" / "mandate.md", "mon mandat\n")
    _ecrire(p / ".orga" / "teams" / "integration" / "requests" / "todo" / "r.md", "req\n")
    manifeste = MANIFESTE.replace('["assistant", "verification"]', '["assistant", "integration", "verification"]')
    _ecrire(p / ".orga" / "projet.toml", manifeste)
    _installer(p, monkeypatch)
    assert (p / ".orga" / "teams" / "integration" / "mandate.md").read_text() == "mon mandat\n"
    assert (p / ".orga" / "teams" / "integration" / "requests" / "todo" / "r.md").is_file()
    assert (p / ".orga" / "projet.toml").read_text() == manifeste       # le manifeste existant n'est pas touché
    assert "integration" in lire_manifeste(p).equipes_speciales
