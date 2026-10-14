import argparse
import io
import json
import socket
import sqlite3
import sys
import textwrap
import threading
import time
import types
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from cime.fondation import hook
from cime.fondation.nom import VAR_AGENT, VAR_PROJET

FIXTURES = Path(__file__).parent / "fixtures" / "hooks"
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
COMMUNS = {"cwd", "transcript_path"}


@pytest.fixture
def projet(tmp_path, monkeypatch):
    racine = tmp_path / "depot"
    (racine / ".orga").mkdir(parents=True)
    (racine / ".orga" / "projet.toml").write_text(MANIFESTE)
    monkeypatch.setenv(VAR_PROJET, str(racine))
    monkeypatch.setenv(VAR_AGENT, "worker-essai-hook")
    monkeypatch.delenv("TMUX", raising=False)
    return racine


def fixture(nom) -> dict:
    return json.loads((FIXTURES / f"{nom}.json").read_text())


def lancer(monkeypatch, capsys, evenement, entree):
    texte = entree if isinstance(entree, str) else json.dumps(entree)
    monkeypatch.setattr(sys, "stdin", io.StringIO(texte))
    code = hook.executer(argparse.Namespace(evenement=evenement))
    assert code == 0
    return capsys.readouterr().out


def lignes(projet):
    conn = sqlite3.connect(projet / ".orga" / "etat" / "registre.sqlite")
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("select * from evenements order by id")]
    finally:
        conn.close()


ATTENDU = {
    "SessionStart": {"source", "model"},
    "SessionEnd": {"reason"},
    "UserPromptSubmit": {"prompt"},
    "Stop": {"last_assistant_message", "stop_hook_active"},
    "StopFailure": {"error", "last_assistant_message"},
    "Notification": {"notification_type", "message"},
    "PostToolUse": {"tool_name", "file_path"},
    "PreCompact": {"trigger"},
    "PostCompact": {"trigger"},
    "SubagentStart": {"agent_type", "agent_id"},
    "SubagentStop": {"agent_type", "agent_id"},
}


@pytest.mark.parametrize("evenement", sorted(ATTENDU))
def test_fixture_reelle(projet, monkeypatch, capsys, evenement):
    entree = fixture(evenement)
    sortie = lancer(monkeypatch, capsys, evenement, entree)
    # SessionStart rend la reprise sur stdout (M-E) ; les autres événements ne disent rien
    assert ("Reprise de worker-essai-hook" in sortie if evenement == "SessionStart"
            else sortie == "")
    (ligne,) = lignes(projet)
    assert ligne["evenement"] == evenement
    assert ligne["agent"] == "worker-essai-hook"
    assert ligne["session_id"] == entree["session_id"]
    assert ligne["horodatage"].endswith("Z")
    details = json.loads(ligne["details"])
    assert set(details) == COMMUNS | ATTENDU[evenement]
    for cle, valeur in details.items():
        source = entree["tool_input"]["file_path"] if cle == "file_path" else entree[cle]
        assert valeur == source


def test_champs_hors_liste_jamais_copies(projet, monkeypatch, capsys):
    lancer(monkeypatch, capsys, "PostToolUse", fixture("PostToolUse"))
    details = json.loads(lignes(projet)[0]["details"])
    assert "tool_response" not in details and "tool_input" not in details


def test_sans_agent_colonne_null(projet, monkeypatch, capsys):
    monkeypatch.delenv(VAR_AGENT)
    lancer(monkeypatch, capsys, "Stop", fixture("Stop"))
    assert lignes(projet)[0]["agent"] is None


def test_session_start_sans_model(projet, monkeypatch, capsys):
    entree = fixture("SessionStart")
    del entree["model"]
    lancer(monkeypatch, capsys, "SessionStart", entree)
    details = json.loads(lignes(projet)[0]["details"])
    assert "model" not in details and details["source"] == "startup"


def test_session_start_apres_compact(projet, monkeypatch, capsys):
    entree = {**fixture("SessionStart"), "source": "compact", "prompt_id": "x"}
    lancer(monkeypatch, capsys, "SessionStart", entree)
    assert json.loads(lignes(projet)[0]["details"])["source"] == "compact"


def test_notification_permission_prompt_sans_tool_name(projet, monkeypatch, capsys):
    lancer(monkeypatch, capsys, "Notification", fixture("Notification"))
    details = json.loads(lignes(projet)[0]["details"])
    assert details["notification_type"] == "permission_prompt"
    assert "tool_name" not in details


def test_subagent_stop_fantome_ecrit(projet, monkeypatch, capsys):
    entree = {**fixture("SubagentStop"), "agent_type": "", "agent_id": "ghost"}
    lancer(monkeypatch, capsys, "SubagentStop", entree)
    details = json.loads(lignes(projet)[0]["details"])
    assert details["agent_type"] == ""


def test_troncatures(projet, monkeypatch, capsys):
    long = "é" * 5000
    lancer(monkeypatch, capsys, "UserPromptSubmit", {**fixture("UserPromptSubmit"), "prompt": long})
    lancer(monkeypatch, capsys, "Stop", {**fixture("Stop"), "last_assistant_message": long})
    gros = {**fixture("PermissionRequest"), "tool_input": {"command": "x" * 5000}}
    lancer(monkeypatch, capsys, "PermissionRequest", gros)
    prompt, stop, perm = (json.loads(r["details"]) for r in lignes(projet))
    assert prompt["prompt"] == long[:2000]
    assert stop["last_assistant_message"] == long[:2000]
    assert set(perm["tool_input"]) == {"_tronque"}
    assert len(perm["tool_input"]["_tronque"]) == 2000
    assert perm["tool_input"]["_tronque"] == json.dumps(gros["tool_input"], ensure_ascii=False)[:2000]


def test_evenement_inconnu_ou_projet_introuvable(projet, monkeypatch, capsys, tmp_path):
    assert lancer(monkeypatch, capsys, "Inconnu", fixture("Stop")) == ""
    assert not (projet / ".orga" / "etat").exists()
    monkeypatch.setenv(VAR_PROJET, str(tmp_path / "rien"))
    monkeypatch.chdir(tmp_path)
    assert lancer(monkeypatch, capsys, "Stop", fixture("Stop")) == ""


def test_registre_illisible(projet, monkeypatch, capsys):
    etat = projet / ".orga" / "etat"
    etat.mkdir()
    (etat / "registre.sqlite").write_text("ceci n'est pas une base sqlite" * 50)
    assert lancer(monkeypatch, capsys, "Stop", fixture("Stop")) == ""
    journal = (etat / "hooks-erreurs.log").read_text().splitlines()
    assert len(journal) == 1 and " Stop " in journal[0]


def test_json_invalide_journalise(projet, monkeypatch, capsys):
    assert lancer(monkeypatch, capsys, "Stop", "pas du json") == ""
    assert (projet / ".orga" / "etat" / "hooks-erreurs.log").read_text().count("\n") == 1


def test_json_invalide_code_0_sur_chaque_evenement_a_sortie(projet, monkeypatch, capsys):
    for evenement in ("Stop", "PostToolUse", "SessionStart", "UserPromptSubmit", "StopFailure"):
        monkeypatch.setattr(sys, "stdin", io.StringIO("{pas du json"))
        assert hook.executer(argparse.Namespace(evenement=evenement)) == 0
        sortie = capsys.readouterr()
        assert sortie.out == "" and sortie.err == ""


def test_main_hook_renvoie_le_code_du_hook(projet, monkeypatch, capsys):
    from cime import cli
    monkeypatch.setattr(hook, "_texte_a_rendre", lambda *a: "bonjour")
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(fixture("Stop"))))
    assert cli.main(["hook", "Stop"]) == 2
    assert capsys.readouterr().err == "bonjour\n"
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(fixture("SessionStart"))))
    assert cli.main(["hook", "SessionStart"]) == 0
    assert capsys.readouterr().out == "bonjour"


# --- PreToolUse -------------------------------------------------------------

def _double_garde(monkeypatch, retour):
    module = types.ModuleType("cime.fondation.garde")
    module.decider = lambda entree, projet: retour
    monkeypatch.setitem(sys.modules, "cime.fondation.garde", module)
    monkeypatch.setattr("cime.fondation.garde", module, raising=False)


def test_pretooluse_refus(projet, monkeypatch, capsys):
    _double_garde(monkeypatch, "git push interdit")
    sortie = lancer(monkeypatch, capsys, "PreToolUse", fixture("PreToolUse"))
    assert json.loads(sortie) == {"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": "git push interdit"}}
    (ligne,) = lignes(projet)
    assert ligne["evenement"] == "PreToolUse"
    details = json.loads(ligne["details"])
    assert set(details) == COMMUNS | {"tool_name", "tool_input", "motif"}
    assert details["motif"] == "git push interdit"


def _lecture_permise(projet) -> dict:
    """Read d'un fichier du projet : le périmètre le laisse passer."""
    entree = fixture("PreToolUse")
    entree["cwd"] = str(projet)
    entree["tool_input"] = {"file_path": str(projet / "a.txt")}
    return entree


def test_pretooluse_passe(projet, monkeypatch, capsys):
    _double_garde(monkeypatch, None)
    assert lancer(monkeypatch, capsys, "PreToolUse", _lecture_permise(projet)) == ""
    assert not (projet / ".orga" / "etat" / "registre.sqlite").exists()


def test_pretooluse_garde_absente(projet, monkeypatch, capsys):
    # indépendant de la présence réelle du module : ni dans sys.modules, ni
    # en attribut du paquet (un autre test a pu l'importer)
    monkeypatch.setitem(sys.modules, "cime.fondation.garde", None)  # ImportError
    monkeypatch.delattr("cime.fondation.garde", raising=False)
    assert lancer(monkeypatch, capsys, "PreToolUse", _lecture_permise(projet)) == ""
    assert (projet / ".orga" / "etat" / "hooks-erreurs.log").exists()


# --- PermissionRequest contre un faux hôte -----------------------------------

class FauxHote:
    def __init__(self, decision):
        self.decision = decision
        self.posts = []
        self.gets = 0
        hote = self

        class Gestionnaire(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _repondre(self, objet):
                corps = json.dumps(objet).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(corps)))
                self.end_headers()
                self.wfile.write(corps)

            def do_POST(self):
                n = int(self.headers["Content-Length"])
                hote.posts.append((self.path, json.loads(self.rfile.read(n))))
                self._repondre({"ok": True})

            def do_GET(self):
                hote.gets += 1
                self._repondre({"decision": hote.decision})

        self.serveur = HTTPServer(("127.0.0.1", 0), Gestionnaire)
        self.port = self.serveur.server_address[1]
        threading.Thread(target=self.serveur.serve_forever, daemon=True).start()

    def fermer(self):
        self.serveur.shutdown()
        self.serveur.server_close()


@pytest.fixture
def faux_hote(projet):
    ouverts = []

    def creer(decision):
        h = FauxHote(decision)
        ouverts.append(h)
        (projet / ".orga" / "etat").mkdir(exist_ok=True)
        (projet / ".orga" / "etat" / "hote.port").write_text(str(h.port))
        return h

    yield creer
    for h in ouverts:
        h.fermer()


def test_permission_sans_fichier_de_port(projet, monkeypatch, capsys):
    assert lancer(monkeypatch, capsys, "PermissionRequest", fixture("PermissionRequest")) == ""
    (ligne,) = lignes(projet)
    details = json.loads(ligne["details"])
    assert set(details) == COMMUNS | {"tool_name", "tool_input", "demande_id"}


def test_permission_port_ferme(projet, monkeypatch, capsys):
    h = FauxHote("allow")
    port = h.port
    h.fermer()
    (projet / ".orga" / "etat").mkdir(exist_ok=True)
    (projet / ".orga" / "etat" / "hote.port").write_text(str(port))
    assert lancer(monkeypatch, capsys, "PermissionRequest", fixture("PermissionRequest")) == ""


@pytest.mark.parametrize("decision", ["allow", "deny", "en_attente"])
def test_permission_ne_decide_jamais(projet, monkeypatch, capsys, faux_hote, decision):
    h = faux_hote(decision)
    entree = fixture("PermissionRequest")
    debut = time.monotonic()
    sortie = lancer(monkeypatch, capsys, "PermissionRequest", entree)
    assert time.monotonic() - debut < 0.6
    assert sortie == ""
    assert h.gets == 0

    ((chemin, corps),) = h.posts
    demande_id = json.loads(lignes(projet)[0]["details"])["demande_id"]
    assert chemin == "/api/permissions"
    assert corps == {
        "demande_id": demande_id, "agent": "worker-essai-hook",
        "session_tmux": "cc-worker-essai-hook",
        "tool_name": "Bash", "tool_input": entree["tool_input"]}


def test_permission_hote_muet_rend_la_main_vite(projet, monkeypatch, capsys):
    ecoute = socket.socket()
    ecoute.bind(("127.0.0.1", 0))
    ecoute.listen(1)  # accepte la connexion, ne répond jamais
    (projet / ".orga" / "etat").mkdir(exist_ok=True)
    (projet / ".orga" / "etat" / "hote.port").write_text(str(ecoute.getsockname()[1]))
    try:
        debut = time.monotonic()
        assert lancer(monkeypatch, capsys, "PermissionRequest", fixture("PermissionRequest")) == ""
        # Le délai réseau du hook est d'une demi-seconde. La marge couvre une machine lente.
        assert time.monotonic() - debut < 2
    finally:
        ecoute.close()


def test_permission_session_tmux_via_tmux(projet, monkeypatch, capsys, faux_hote):
    h = faux_hote("allow")
    monkeypatch.setenv("TMUX", "/tmp/x,1,0")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="ma-session\n"))
    lancer(monkeypatch, capsys, "PermissionRequest", fixture("PermissionRequest"))
    assert h.posts[0][1]["session_tmux"] == "ma-session"


def test_permission_sans_agent_session_null(projet, monkeypatch, capsys, faux_hote):
    h = faux_hote("allow")
    monkeypatch.delenv(VAR_AGENT)
    lancer(monkeypatch, capsys, "PermissionRequest", fixture("PermissionRequest"))
    assert h.posts[0][1]["agent"] is None and h.posts[0][1]["session_tmux"] is None


def test_environnement_isole_par_defaut(tmp_path_factory):
    import os
    base = tmp_path_factory.getbasetemp().resolve()
    jetable = Path(os.environ[VAR_PROJET]).resolve()
    assert base in jetable.parents
    assert not (jetable / ".orga").exists()
    assert VAR_AGENT not in os.environ


# Sans manifeste lisible, la garde ne doit pas rester « ouverte ». Les interdits universels ne dépendent pas du manifeste.
UNIVERSELS = ["git push", "rtk git push", "echo ok && git push", "git branch -D x",
              "security find-generic-password -s x", "rtk proxy git status"]


def _bash(commande):
    entree = fixture("PreToolUse")  # capture réelle d'un Read : on en fait un Bash
    entree["tool_name"] = "Bash"
    entree["tool_input"] = {"command": commande}
    return entree


@pytest.mark.parametrize("commande", UNIVERSELS)
def test_pretooluse_sans_manifeste_refuse_les_universels(monkeypatch, capsys, tmp_path, commande):
    rien = tmp_path / "rien"  # CIME_PROJET sans .orga/projet.toml, cwd hors de tout projet
    rien.mkdir()
    monkeypatch.setenv(VAR_PROJET, str(rien))
    monkeypatch.chdir(tmp_path)
    sortie = json.loads(lancer(monkeypatch, capsys, "PreToolUse", _bash(commande)))
    assert sortie["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert not (rien / ".orga").exists()  # rien créé hors d'un projet


def test_pretooluse_sans_manifeste_laisse_passer_le_reste(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv(VAR_PROJET, str(tmp_path))
    monkeypatch.chdir(tmp_path)
    assert lancer(monkeypatch, capsys, "PreToolUse", _bash("git status")) == ""


def test_pretooluse_sans_manifeste_journalise_pourquoi(monkeypatch, capsys, tmp_path):
    racine = tmp_path / "orga-sans-manifeste"
    (racine / ".orga").mkdir(parents=True)
    monkeypatch.setenv(VAR_PROJET, str(racine))
    monkeypatch.chdir(tmp_path)
    assert lancer(monkeypatch, capsys, "PreToolUse", _bash("git push")) != ""
    journal = (racine / ".orga" / "etat" / "hooks-erreurs.log").read_text()
    assert "garde sans manifeste" in journal


# Ni une garde absente ni une erreur interne de la garde ne valent autorisation. Pour Bash, repli textuel prudent ; le reste passe.
REPLI_REFUSE = ["git push", "cd /x && git -C y push", "security dump-keychain",
                "git branch -D x", "rtk proxy ls", "tmux send-keys -t cc-assistant x"]
REPLI_PASSE = ["git status", "ls -la", "cime voir worker-essai-hook"]


def _sans_module_garde(monkeypatch):
    monkeypatch.setitem(sys.modules, "cime.fondation.garde", None)  # ImportError
    monkeypatch.delattr("cime.fondation.garde", raising=False)


@pytest.mark.parametrize("commande", REPLI_REFUSE)
def test_garde_absente_repli_refuse(projet, monkeypatch, capsys, commande):
    _sans_module_garde(monkeypatch)
    sortie = json.loads(lancer(monkeypatch, capsys, "PreToolUse", _bash(commande)))
    assert sortie["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "indisponible" in sortie["hookSpecificOutput"]["permissionDecisionReason"]
    assert (projet / ".orga" / "etat" / "hooks-erreurs.log").exists()


@pytest.mark.parametrize("commande", REPLI_PASSE)
def test_garde_absente_repli_laisse_passer(projet, monkeypatch, capsys, commande):
    _sans_module_garde(monkeypatch)
    assert lancer(monkeypatch, capsys, "PreToolUse", _bash(commande)) == ""


def test_garde_absente_sans_projet_refuse(monkeypatch, capsys, tmp_path):
    _sans_module_garde(monkeypatch)
    monkeypatch.setenv(VAR_PROJET, str(tmp_path))
    monkeypatch.chdir(tmp_path)
    assert lancer(monkeypatch, capsys, "PreToolUse", _bash("git push")) != ""


@pytest.mark.parametrize("commande", REPLI_REFUSE)
def test_erreur_interne_de_la_garde_repli_refuse(monkeypatch, commande):
    from cime.fondation import garde

    def panne(*a, **k):
        raise RuntimeError("panne simulée")
    monkeypatch.setattr(garde, "_analyser", panne)
    assert garde.decider(_bash(commande), None) == garde.M_ERREUR


@pytest.mark.parametrize("commande", REPLI_PASSE)
def test_erreur_interne_de_la_garde_laisse_passer_le_reste(monkeypatch, commande):
    from cime.fondation import garde

    def panne(*a, **k):
        raise RuntimeError("panne simulée")
    monkeypatch.setattr(garde, "_analyser", panne)
    assert garde.decider(_bash(commande), None) is None


# Le repli juge chaque ligne : « git » ici et « push » plus bas ne font pas une commande. Une
# continuation (`\` en fin de ligne) fait une seule ligne.
@pytest.mark.parametrize("commande", ["git status\n# Ni push", "git log\n" + "x\n" * 30 + "# push"])
def test_garde_absente_repli_ne_traverse_pas_les_lignes(projet, monkeypatch, capsys, commande):
    _sans_module_garde(monkeypatch)
    assert lancer(monkeypatch, capsys, "PreToolUse", _bash(commande)) == ""


def test_garde_absente_repli_joint_les_continuations(projet, monkeypatch, capsys):
    _sans_module_garde(monkeypatch)
    sortie = json.loads(lancer(monkeypatch, capsys, "PreToolUse", _bash("git \\\n  push")))
    assert sortie["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_repli_du_hook_identique_a_celui_de_la_garde():
    from cime.fondation import garde
    assert hook.REPLI == [r.pattern for r in garde._REPLI]
