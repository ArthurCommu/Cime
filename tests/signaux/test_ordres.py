import json
import subprocess

import pytest

from aide import cime, fabriquer_projet, lignes
from cime.fondation import compacter, lancer, terminer
from cime.signaux import ordres


@pytest.fixture
def projet(tmp_path, monkeypatch):
    racine = fabriquer_projet(tmp_path / "depot")
    monkeypatch.setenv("CIME_PROJET", str(racine))
    monkeypatch.delenv("CLAUDECODE", raising=False)
    (racine / ".orga/teams/x/tasks/todo/t.md").write_text("tâche")
    return racine


@pytest.fixture
def tmux(monkeypatch):
    """Faux tmux : aucune commande réelle ne part ; une session par défaut est vivante."""
    etat = {"vivantes": {"essai-worker-x-t", "essai-coord-x"}, "appels": [], "ecran": "l1\nl2\n"}

    def faux(*args):
        etat["appels"].append(args)
        code, sortie = 0, ""
        if args[0] == "has-session":
            code = 0 if args[2].lstrip("=") in etat["vivantes"] else 1
        elif args[0] == "capture-pane":
            sortie = etat["ecran"]
        return subprocess.CompletedProcess(args, code, sortie, "")

    for module in (ordres, terminer, compacter):
        monkeypatch.setattr(module, "_tmux", faux)
    monkeypatch.setattr(compacter, "_attendre", lambda s: None)
    monkeypatch.setattr(compacter.invite, "brouillon", lambda cible: "")
    return etat


@pytest.fixture
def faux_lancer(monkeypatch, projet):
    """Remplace le lancement réel : déplace la tâche todo → in-progress, sans tmux ni claude."""
    appels = []

    def faux(args, projet_=None, attacher=False):
        appels.append((args.role, args.equipe, args.tache, args.modele))
        if args.role == "worker":
            base = projet / ".orga/teams" / args.equipe / "tasks"
            (base / "in-progress").mkdir(exist_ok=True)
            (base / "todo" / f"{args.tache}.md").rename(base / "in-progress" / f"{args.tache}.md")
        return f"essai-{args.role}", 0

    monkeypatch.setattr(lancer, "_lancer", faux)
    return appels


@pytest.fixture
def facteur(monkeypatch, projet):
    """Facteur simulé : pendant que la commande attend son ordre, il l'exécute."""
    monkeypatch.setattr(ordres, "_dormir", lambda s: ordres.facteur_une_fois(projet))


def accord_worker(monkeypatch, projet, capsys, modele="claude-haiku-5-5", parallele=False,
                  objet="lancer-worker:x:t"):
    cime(monkeypatch, "coord-x", "envoyer", "--a", "assistant", "--nature", "demande_accord",
         "--objet", objet, "go", projet=projet)
    demande = int(capsys.readouterr().out.strip().splitlines()[-1])
    extra = ["--parallele"] if parallele else []
    assert cime(monkeypatch, "assistant", "accorder", str(demande), "--modele", modele,
                *extra) == 0
    return int(capsys.readouterr().out.strip().splitlines()[-1])


def lancer_worker(monkeypatch, projet, modele="claude-haiku-5-5", tache="t"):
    return cime(monkeypatch, "coord-x", "lancer", "worker", "x", tache, "--modele", modele,
                projet=projet)


# --- lancer worker : préconditions ---------------------------------------------------------

def test_lancement_sans_accord_refuse(projet, tmux, faux_lancer, facteur, monkeypatch, capsys):
    assert lancer_worker(monkeypatch, projet) == 2
    assert "accord" in capsys.readouterr().err
    assert lignes(projet, "SELECT count(*) FROM ordres") == [(0,)] and faux_lancer == []


def test_lancement_avec_accord(projet, tmux, faux_lancer, facteur, monkeypatch, capsys):
    accord = accord_worker(monkeypatch, projet, capsys)
    assert lancer_worker(monkeypatch, projet) == 0
    assert faux_lancer == [("worker", "x", "t", "claude-haiku-5-5")]
    assert lignes(projet, "SELECT auteur, verbe, cible, etat FROM ordres") == [
        ("coord-x", "lancer", "worker-x-t", "execute")]
    # le message d'ouverture est une consigne du coordinateur au worker, avec son obligation
    assert lignes(projet, "SELECT de, a, nature, objet FROM messages WHERE objet = 'tache:x:t'"
                  ) == [("coord-x", "worker-x-t", "consigne", "tache:x:t")]
    assert lignes(projet, "SELECT debiteur, attendu, etat FROM obligations o JOIN messages m"
                  " ON m.id = o.message_id WHERE m.objet = 'tache:x:t'") == [
        ("worker-x-t", "travail_pret", "ouverte")]
    # l'accord est consommé par l'ordre
    ordre = lignes(projet, "SELECT id FROM ordres")[0][0]
    assert lignes(projet, "SELECT preuve FROM transitions WHERE message_id = ? AND etat = 'clos'",
                  (accord,)) == [(json.dumps({"par_ordre": ordre}),)]


def test_accord_reutilise_refuse(projet, tmux, faux_lancer, facteur, monkeypatch, capsys):
    accord_worker(monkeypatch, projet, capsys)
    assert lancer_worker(monkeypatch, projet) == 0
    (projet / ".orga/teams/x/tasks/todo/t.md").write_text("de nouveau")
    (projet / ".orga/teams/x/tasks/in-progress/t.md").unlink()
    assert lancer_worker(monkeypatch, projet) == 2
    assert len(faux_lancer) == 1


def test_modele_different_refuse(projet, tmux, faux_lancer, facteur, monkeypatch, capsys):
    accord_worker(monkeypatch, projet, capsys, modele="claude-haiku-5-5")
    assert lancer_worker(monkeypatch, projet, modele="claude-opus-5-5") == 2
    assert "claude-haiku-5-5" in capsys.readouterr().err and faux_lancer == []


def test_equipe_bloquee_refusee(projet, tmux, faux_lancer, facteur, monkeypatch, capsys):
    accord_worker(monkeypatch, projet, capsys)
    (projet / ".orga/dependencies.md").write_text(
        "# Dépendances\n\n## y\nStatut : OK\n\n## x\nStatut : BLOQUÉ — attend l'API\n")
    assert lancer_worker(monkeypatch, projet) == 2
    assert "bloquée" in capsys.readouterr().err and faux_lancer == []
    (projet / ".orga/dependencies.md").write_text("## x\nStatut : EN COURS\n")
    assert lancer_worker(monkeypatch, projet) == 0


def test_un_autre_worker_actif_sauf_parallele(projet, tmux, faux_lancer, facteur, monkeypatch,
                                              capsys):
    (projet / ".orga/teams/x/tasks/in-progress/autre.md").write_text("en cours")
    accord_worker(monkeypatch, projet, capsys)
    assert lancer_worker(monkeypatch, projet) == 2
    assert "déjà actif" in capsys.readouterr().err
    accord_worker(monkeypatch, projet, capsys, parallele=True)
    assert lancer_worker(monkeypatch, projet) == 0


def test_tache_absente_de_todo(projet, tmux, faux_lancer, facteur, monkeypatch, capsys):
    (projet / ".orga/teams/x/tasks/todo/t.md").unlink()
    accord_worker(monkeypatch, projet, capsys)
    assert lancer_worker(monkeypatch, projet) == 2


def test_lancer_worker_par_un_autre_coordinateur(projet, tmux, faux_lancer, facteur,
                                                 monkeypatch, capsys):
    accord_worker(monkeypatch, projet, capsys)
    assert cime(monkeypatch, "coord-y", "lancer", "worker", "x", "t", "--modele", "m",
                projet=projet) == 2


# --- lancer coord / assistant --------------------------------------------------------------

def test_lancer_coord_demande_l_accord_de_l_utilisateur(projet, tmux, faux_lancer, facteur,
                                                monkeypatch, capsys):
    cmd = ("lancer", "coord", "x", "--modele", "m", "--phase", "2")
    assert cime(monkeypatch, "assistant", *cmd, projet=projet) == 2
    assert faux_lancer == []
    cime(monkeypatch, "assistant", "envoyer", "--a", "utilisateur", "--nature", "decision_utilisateur",
         "--objet", "chantier:x:2", "ouvrir la phase 2 ?")
    d = int(capsys.readouterr().out.strip().splitlines()[-1])
    assert cime(monkeypatch, None, "accorder", str(d)) == 0
    assert cime(monkeypatch, "assistant", *cmd) == 0
    assert faux_lancer == [("coord", "x", None, "m")]
    assert cime(monkeypatch, "assistant", *cmd) == 2  # accord consommé


def test_lancer_coord_reprendre_sans_accord(projet, tmux, faux_lancer, facteur, monkeypatch):
    assert cime(monkeypatch, "assistant", "lancer", "coord", "x", "--reprendre",
                projet=projet) == 0
    assert cime(monkeypatch, "coord-x", "lancer", "coord", "x", "--reprendre") == 2


def test_lancer_assistant_sans_accord(projet, tmux, faux_lancer, facteur, monkeypatch):
    assert cime(monkeypatch, "assistant", "lancer", "assistant", projet=projet) == 0
    assert cime(monkeypatch, "coord-x", "lancer", "assistant") == 2


# --- le facteur et le délai ---------------------------------------------------------------

def test_delai_depasse_ordre_reste_en_file_puis_execute_une_fois(projet, tmux, faux_lancer,
                                                                 monkeypatch, capsys):
    accord_worker(monkeypatch, projet, capsys)
    monkeypatch.setenv("CIME_ATTENTE_ORDRE", "0")
    assert lancer_worker(monkeypatch, projet) == 4
    assert "ordre #1 en file, facteur arrêté" in capsys.readouterr().out
    assert lignes(projet, "SELECT etat FROM ordres") == [("en_file",)] and faux_lancer == []
    assert cime(monkeypatch, "coord-x", "facteur", "--une-fois") == 0
    assert lignes(projet, "SELECT etat FROM ordres") == [("execute",)]
    assert len(faux_lancer) == 1
    assert cime(monkeypatch, "coord-x", "facteur", "--une-fois") == 0  # rien de plus
    assert len(faux_lancer) == 1
    assert lignes(projet, "SELECT count(*) FROM facteur") == [(1,)]


def test_ordres_executes_dans_l_ordre_des_id(projet, tmux, monkeypatch):
    vus = []
    monkeypatch.setattr(ordres, "executer", lambda p, o: vus.append(o["id"]) or ("execute", 0, ""))
    for cible in ("worker-x-a", "worker-x-b", "worker-x-c"):
        ordres.demander(projet, "coord-x", "capturer", cible, {})
    ordres.facteur_une_fois(projet)
    assert vus == [1, 2, 3]


def test_code_3_ecran_d_approbation_repris(projet, tmux, monkeypatch, facteur, capsys):
    monkeypatch.setattr(lancer, "_lancer", lambda args, p=None: ("essai-coord-x", 3))
    assert cime(monkeypatch, "assistant", "lancer", "coord", "x", "--reprendre",
                projet=projet) == 3


def test_ordre_refuse_par_l_executeur_donne_2(projet, tmux, monkeypatch, facteur):
    def refus(args, p=None):
        raise lancer.Refus("session déjà lancée")
    monkeypatch.setattr(lancer, "_lancer", refus)
    assert cime(monkeypatch, "assistant", "lancer", "coord", "x", "--reprendre",
                projet=projet) == 2
    assert lignes(projet, "SELECT etat FROM ordres") == [("refuse",)]


# --- terminer ------------------------------------------------------------------------------

def preparer_fin(projet, travail_pret=True, synthese=True, rapport=True):
    equipe = projet / ".orga/teams/x"
    (equipe / "tasks/in-progress/t.md").write_text("tâche")
    if rapport:
        (equipe / "reports/worker-x-t-2026-10-09.md").write_text("rapport")
    if synthese:
        (equipe / "conversations/t-2026-10-09.md").write_text("synthèse")


def travail_pret(monkeypatch, projet, capsys):
    cime(monkeypatch, "cime", "envoyer", "--a", "worker-x-t", "--nature", "consigne",
         "--attend", "travail_pret", "--objet", "tache:x:t", "ouverture", projet=projet)
    capsys.readouterr()
    assert cime(monkeypatch, "worker-x-t", "envoyer", "--a", "coord-x", "--nature",
                "travail_pret", "fini") == 0
    return int(capsys.readouterr().out.strip().splitlines()[-1])


def test_terminer_sans_travail_pret_refuse(projet, tmux, facteur, monkeypatch, capsys):
    preparer_fin(projet)
    assert cime(monkeypatch, "coord-x", "terminer", "worker", "x", "t", projet=projet) == 2
    assert "travail_pret" in capsys.readouterr().err
    assert lignes(projet, "SELECT count(*) FROM ordres") == [(0,)]


def test_terminer_sans_synthese_refuse(projet, tmux, facteur, monkeypatch, capsys):
    preparer_fin(projet, synthese=False)
    travail_pret(monkeypatch, projet, capsys)
    assert cime(monkeypatch, "coord-x", "terminer", "worker", "x", "t") == 2
    assert "conversations" in capsys.readouterr().err
    assert not any(a[0] == "kill-session" for a in tmux["appels"])


def test_terminer_sans_rapport_refuse(projet, tmux, facteur, monkeypatch, capsys):
    preparer_fin(projet, rapport=False)
    travail_pret(monkeypatch, projet, capsys)
    assert cime(monkeypatch, "coord-x", "terminer", "worker", "x", "t") == 2


def test_terminer_ferme_et_satisfait_les_obligations(projet, tmux, facteur, monkeypatch, capsys):
    preparer_fin(projet)
    tp = travail_pret(monkeypatch, projet, capsys)
    assert cime(monkeypatch, "coord-x", "terminer", "worker", "x", "t") == 0
    assert ("kill-session", "-t", "=essai-worker-x-t") in tmux["appels"]
    assert (projet / ".orga/teams/x/tasks/done/t.md").exists()
    assert lignes(projet, "SELECT etat FROM obligations ORDER BY id") == [
        ("satisfaite",), ("satisfaite",)]
    assert lignes(projet, "SELECT etat FROM ordres") == [("execute",)]
    assert tp


def test_terminer_par_un_autre_que_son_coordinateur(projet, tmux, facteur, monkeypatch, capsys):
    preparer_fin(projet)
    travail_pret(monkeypatch, projet, capsys)
    for qui in ("coord-y", "assistant"):
        assert cime(monkeypatch, qui, "terminer", "worker", "x", "t") == 2


# --- compacter -----------------------------------------------------------------------------

def test_compacter_l_assistant_refuse_a_un_agent(projet, tmux, facteur, monkeypatch, capsys):
    assert cime(monkeypatch, "coord-x", "compacter", "assistant", "x", projet=projet) == 2
    assert cime(monkeypatch, "assistant", "compacter", "assistant", "x") == 2
    assert lignes(projet, "SELECT count(*) FROM ordres") == [(0,)]
    assert tmux["appels"] == []


def test_compacter_par_le_superieur_passe_par_un_ordre(projet, tmux, facteur, monkeypatch):
    assert cime(monkeypatch, "assistant", "compacter", "coord-x", "garde tout",
                projet=projet) == 0
    assert ("send-keys", "-t", "=essai-coord-x:", "-l", "/compact garde tout") in tmux["appels"]
    assert lignes(projet, "SELECT verbe, etat FROM ordres") == [("compacter", "execute")]


# --- voir ----------------------------------------------------------------------------------

def test_voir(projet, tmux, facteur, monkeypatch, capsys):
    tmux["ecran"] = "\n".join(f"ligne {i}" for i in range(100)) + "\n"
    assert cime(monkeypatch, "coord-x", "voir", "worker-x-t", projet=projet) == 0
    sortie = capsys.readouterr().out.splitlines()
    assert sortie[0] == "ligne 60" and sortie[-1] == "ligne 99" and len(sortie) == 40


def test_voir_jamais_l_assistant_ni_un_non_subordonne(projet, tmux, facteur, monkeypatch):
    assert cime(monkeypatch, "coord-x", "voir", "assistant", projet=projet) == 2
    assert cime(monkeypatch, "assistant", "voir", "assistant") == 2
    assert cime(monkeypatch, "coord-y", "voir", "worker-x-t") == 2
    assert cime(monkeypatch, "worker-x-t", "voir", "coord-x") == 2
    assert lignes(projet, "SELECT count(*) FROM ordres") == [(0,)]


# --- L'utilisateur à la main ---------------------------------------------------------------------

def test_utilisateur_a_la_main_execute_directement(projet, tmux, faux_lancer, monkeypatch):
    # ni CIME_AGENT ni CLAUDECODE : aucun ordre, aucun accord exigé, exécution directe
    assert cime(monkeypatch, None, "lancer", "worker", "x", "t", "--modele", "m",
                projet=projet) == 0
    assert faux_lancer == [("worker", "x", "t", "m")]
    assert lignes(projet, "SELECT count(*) FROM ordres") == [(0,)]


def test_utilisateur_voit_directement(projet, tmux, monkeypatch, capsys):
    assert cime(monkeypatch, None, "voir", "worker-x-t", projet=projet) == 0
    assert "l1" in capsys.readouterr().out
    assert lignes(projet, "SELECT count(*) FROM ordres") == [(0,)]


def test_agent_sans_identite_refuse(projet, tmux, faux_lancer, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDECODE", "1")
    for cmd in (("lancer", "worker", "x", "t", "--modele", "m"), ("voir", "worker-x-t"),
                ("compacter", "worker-x-t", "c"), ("terminer", "worker", "x", "t")):
        assert cime(monkeypatch, None, *cmd, projet=projet) == 2
    assert "agent sans identité" in capsys.readouterr().err
    assert faux_lancer == [] and tmux["appels"] == []


def test_un_ordre_n_est_execute_qu_une_fois_par_quatre_threads(projet, monkeypatch):
    import threading
    exec_ = []
    monkeypatch.setitem(ordres._EXECUTEURS, "capturer",
                        lambda p, i, params: exec_.append(i) or ("execute", 0, "ok"))
    identifiant = ordres.demander(projet, "coord-x", "capturer", "worker-x-t", {})
    barriere = threading.Barrier(4)
    gagnants = []

    def course():
        barriere.wait()
        if ordres._executer_en_file(projet, identifiant):
            gagnants.append(1)

    fils = [threading.Thread(target=course) for _ in range(4)]
    [f.start() for f in fils]
    [f.join() for f in fils]
    assert len(gagnants) == 1 and exec_ == [identifiant]
    etat, = lignes(projet, "SELECT etat FROM ordres WHERE id = ?", (identifiant,))[0]
    assert etat == "execute"


def test_un_ordre_pris_dont_le_facteur_est_mort_est_clos_en_echec_jamais_rejoue(projet):
    identifiant = ordres.demander(projet, "coord-x", "capturer", "worker-x-t", {})
    assert ordres._prendre_ordre(projet, identifiant) is not None   # pris, puis facteur tué
    assert ordres._prendre_ordre(projet, identifiant) is None
    assert ordres.clore_interrompus(projet) == 1
    etat, = lignes(projet, "SELECT etat FROM ordres WHERE id = ?", (identifiant,))[0]
    assert etat == "echec" and ordres.clore_interrompus(projet) == 0


# --- facteur arrêté : code 4 pour tous les verbes -----------------------------------------

def test_sans_facteur_lancer_terminer_compacter_voir_sortent_en_code_4(
        projet, tmux, faux_lancer, monkeypatch, capsys):
    monkeypatch.setenv("CIME_ATTENTE_ORDRE", "0")
    accord_worker(monkeypatch, projet, capsys)
    assert lancer_worker(monkeypatch, projet) == 4
    preparer_fin(projet)
    travail_pret(monkeypatch, projet, capsys)
    capsys.readouterr()
    assert cime(monkeypatch, "coord-x", "terminer", "worker", "x", "t", projet=projet) == 4
    assert cime(monkeypatch, "assistant", "compacter", "coord-x", "garde tout", projet=projet) == 4
    assert cime(monkeypatch, "coord-x", "voir", "worker-x-t", projet=projet) == 4
    sortie = capsys.readouterr().out
    assert sortie.count("facteur arrêté") == 3   # le message du 1er code 4 a été lu plus haut
    assert [v for (v,) in lignes(projet, "SELECT verbe FROM ordres ORDER BY id")] == [
        "lancer", "fermer", "compacter", "capturer"]
    assert {e for (e,) in lignes(projet, "SELECT etat FROM ordres")} == {"en_file"}
    assert tmux["appels"] == [] and faux_lancer == []   # aucun terminal touché, rien exécuté


# --- lancer worker : reprise d'une tâche orpheline -----------------------------------------------

@pytest.fixture
def orpheline(projet, monkeypatch):
    """Fiche en `in-progress/`, ni session tmux ni processus claude (sondes simulées)."""
    taches = projet / ".orga/teams/x/tasks"
    (taches / "todo" / "t.md").rename(taches / "in-progress" / "t.md")
    sondes = {"session": False, "pids": []}
    monkeypatch.setattr(lancer, "_session_existe", lambda s: sondes["session"])
    monkeypatch.setattr(lancer, "processus_claude_dans", lambda d: sondes["pids"])
    return sondes


@pytest.fixture
def lancer_sans_deplacement(monkeypatch):
    """Remplace le lancement réel d'une reprise : il ne déplace rien."""
    appels = []

    def faux(args, projet_=None, attacher=False):
        appels.append((args.role, args.equipe, args.tache, args.auteur))
        return "essai-worker-x-t", 0

    monkeypatch.setattr(lancer, "_lancer", faux)
    return appels


def _parametres_des_ordres(projet):
    return [json.loads(p) for (p,) in lignes(projet, "SELECT parametres FROM ordres")]


def test_reprise_orpheline_sans_accord_refusee(projet, tmux, orpheline, lancer_sans_deplacement,
                                               facteur, monkeypatch, capsys):
    assert lancer_worker(monkeypatch, projet) == 2
    assert "aucun accord non consommé" in capsys.readouterr().err
    assert lignes(projet, "SELECT count(*) FROM ordres") == [(0,)] and lancer_sans_deplacement == []


def test_reprise_orpheline_avec_accord(projet, tmux, orpheline, lancer_sans_deplacement, facteur,
                                       monkeypatch, capsys):
    accord = accord_worker(monkeypatch, projet, capsys)
    assert lancer_worker(monkeypatch, projet) == 0
    assert lancer_sans_deplacement == [("worker", "x", "t", "coord-x")]
    (params,) = _parametres_des_ordres(projet)
    assert params["reprise"] is True and params["accord"] == accord
    ordre = lignes(projet, "SELECT id FROM ordres")[0][0]
    assert lignes(projet, "SELECT preuve FROM transitions WHERE message_id = ? AND etat = 'clos'",
                  (accord,)) == [(json.dumps({"par_ordre": ordre}),)]
    ((resume, fichier),) = lignes(projet, "SELECT resume, fichier FROM messages"
                                          " WHERE objet = 'tache:x:t'")
    assert "reprise après interruption" in resume and "git status" in resume
    assert "ne refais pas ce qui est fait" in resume and len(resume) <= 160
    assert fichier is None or fichier.endswith("in-progress/t.md")


def test_reprise_orpheline_avec_session_vivante_refus_inchange(
        projet, tmux, orpheline, lancer_sans_deplacement, facteur, monkeypatch, capsys):
    orpheline["session"] = True
    accord_worker(monkeypatch, projet, capsys)
    assert lancer_worker(monkeypatch, projet) == 2
    assert "tâche absente" in capsys.readouterr().err
    assert lancer_sans_deplacement == [] and lignes(projet, "SELECT count(*) FROM ordres") == [(0,)]


def test_reprise_orpheline_avec_processus_claude_refus_inchange(
        projet, tmux, orpheline, lancer_sans_deplacement, facteur, monkeypatch, capsys):
    orpheline["pids"] = [4242]
    accord_worker(monkeypatch, projet, capsys)
    assert lancer_worker(monkeypatch, projet) == 2
    assert "tâche absente" in capsys.readouterr().err
    assert lancer_sans_deplacement == [] and lignes(projet, "SELECT count(*) FROM ordres") == [(0,)]


def test_reprise_orpheline_refusee_si_projet_ferme(projet, tmux, orpheline,
                                                    lancer_sans_deplacement, facteur,
                                                    monkeypatch, capsys):
    accord = accord_worker(monkeypatch, projet, capsys)
    (projet / ".orga/etat").mkdir(parents=True, exist_ok=True)
    (projet / ".orga/etat/ferme.json").write_text("{}")
    assert lancer_worker(monkeypatch, projet) == 2
    assert "projet fermé : rouvrir d'abord" in capsys.readouterr().err
    assert lancer_sans_deplacement == [] and lignes(projet, "SELECT count(*) FROM ordres") == [(0,)]
    assert (projet / ".orga/teams/x/tasks/in-progress/t.md").read_text() == "tâche"
    assert lignes(projet, "SELECT count(*) FROM transitions WHERE message_id = ? AND etat = 'clos'",
                  (accord,)) == [(0,)]


def test_lancement_normal_ne_parle_pas_de_reprise(projet, tmux, faux_lancer, facteur,
                                                  monkeypatch, capsys):
    accord_worker(monkeypatch, projet, capsys)
    assert lancer_worker(monkeypatch, projet) == 0
    (params,) = _parametres_des_ordres(projet)
    assert "reprise" not in params
    ((resume,),) = lignes(projet, "SELECT resume FROM messages WHERE objet = 'tache:x:t'")
    assert "reprise" not in resume and resume.startswith("tâche t : lis ")


def test_fiche_en_todo_et_en_cours_ne_donne_pas_de_reprise(projet, tmux, orpheline,
                                                            lancer_sans_deplacement, facteur,
                                                            monkeypatch, capsys):
    (projet / ".orga/teams/x/tasks/todo/t.md").write_text("double")
    accord_worker(monkeypatch, projet, capsys)
    assert lancer_worker(monkeypatch, projet) == 0
    (params,) = _parametres_des_ordres(projet)
    assert "reprise" not in params


# --- plafond de workers : l'accord d'un lancement en file ---------------------------------------

def test_second_lancement_pour_le_meme_objet_pendant_que_le_premier_est_en_file(
        projet, tmux, faux_lancer, monkeypatch, capsys):
    """L'accord n'est consommé qu'à l'exécution : tant qu'un ordre en file le porte, un second
    lancement pour le même objet est refusé, sans second ordre."""
    accord = accord_worker(monkeypatch, projet, capsys)
    monkeypatch.setenv("CIME_ATTENTE_ORDRE", "0")
    assert lancer_worker(monkeypatch, projet) == 4
    capsys.readouterr()
    assert lancer_worker(monkeypatch, projet) == 2
    assert "déjà en file : ordre #1" in capsys.readouterr().err
    assert [p["accord"] for p in _parametres_des_ordres(projet)] == [accord]
    monkeypatch.setattr(ordres, "_sessions_vivantes", lambda: set())
    ordres.facteur_une_fois(projet)
    assert lignes(projet, "SELECT etat FROM ordres ORDER BY id") == [("execute",)]
    assert len(faux_lancer) == 1


def test_un_autre_accord_libre_permet_un_second_lancement_en_file(
        projet, tmux, faux_lancer, monkeypatch, capsys):
    """Seul l'accord déjà porté par un ordre en file est écarté : un second accord reste utilisable."""
    premier = accord_worker(monkeypatch, projet, capsys)
    second = accord_worker(monkeypatch, projet, capsys)
    monkeypatch.setenv("CIME_ATTENTE_ORDRE", "0")
    assert lancer_worker(monkeypatch, projet) == 4
    assert lancer_worker(monkeypatch, projet) == 4
    assert [p["accord"] for p in _parametres_des_ordres(projet)] == [premier, second]
