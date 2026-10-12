"""Gardes : liste blanche des commandes, chemins lisibles, inventaire statique des lancements de processus et des routes."""
import ast
import re
import sys
from pathlib import Path

import pytest
from conftest import SOCKET_ESSAI, tmux_essai
from starlette.routing import Mount, Route

import cime.hote
from cime.hote import creer_app
from cime.hote.dependances import Dependances
from cime.hote.gardes import Gardes, Interdit, chemin_lisible

G = Gardes("cc-essai")
SRC = Path(cime.hote.__file__).parent

AUTORISES = [
    ["tmux", "capture-pane", "-p", "-e", "-J", "-S", "-200", "-t", "cc-essai-x"],
    ["tmux", "has-session", "-t", "cc-essai-x"],
    ["tmux", "list-sessions"],
    ["tmux", "list-sessions", "-F", "#{session_name}"],
    ["tmux", "kill-session", "-t", "cc-essai-x"],
    ["tmux", "send-keys", "-t", "cc-essai-x", "1"],
    ["tmux", "send-keys", "-t", "cc-essai-x", "Escape"],
    ["osascript", "-e", 'display notification "Utilisateur, ça bloque" with title "Centre"'],
    ["cime", "envoyer", "--a", "assistant", "--nature", "info", "--fichier", "x.md", "résumé"],
    ["cime", "repondre", "42", "ok"],
    ["cime", "repondre", "42", "--fichier", "x.md", "--nature", "reponse", "ok"],
    ["cime", "accorder", "42"],
    ["cime", "refuser", "42", "trop large"],
    ["cime", "fusions-auto", "active"],
    ["cime", "fusions-auto", "inactive"],
]

INTERDITS = [
    ["git", "push"],
    ["git", "-C", "x", "push"],
    ["git", "merge", "x"],
    ["git", "branch", "-D", "x"],
    ["git", "push", "--delete", "origin", "x"],
    ["git", "status"],
    ["security", "find-generic-password", "-s", "x"],
    ["tmux", "send-keys", "-t", "cc-essai-x", "rm -rf /", "Enter"],
    ["tmux", "send-keys", "-t", "cc-essai-x", "rm -rf /"],
    ["tmux", "send-keys", "-t", "cc-essai-x", "Enter"],
    ["tmux", "send-keys", "-t", "cc-essai-x", "2"],
    ["tmux", "send-keys", "-l", "-t", "cc-essai-x", "1"],
    ["tmux", "send-keys", "-t", "cc-essai-x", "-l", "1"],
    ["tmux", "send-keys", "-t", "cc-autre-x", "Enter"],
    ["tmux", "send-keys", "-t", "cc-autre-x", "1"],
    ["tmux", "send-keys", "-t", "cc-essai", "1"],
    ["tmux", "send-keys", "-t", "cc-essaiX-x", "1"],
    ["tmux", "kill-session", "-t", "cc-autre-x"],
    ["tmux", "kill-server"],
    ["tmux", "capture-pane", "-p"],
    ["tmux", "capture-pane", "-p", "-t", "autre"],
    ["tmux", "new-session"],
    ["tmux", "list-sessions", "-t", "x"],
    ["osascript", "-e", 'do shell script "id"'],
    ["osascript", "-e", 'display notification "a" & (do shell script "id")'],
    ["osascript", "-e", 'display notification "a"\ndo shell script "id"'],
    ["osascript", "-e", "display notification x"],
    ["osascript", "-e", 'display notification "a"', "-e", 'do shell script "id"'],
    ["osascript", "x.scpt"],
    ["cime", "envoyer", "--a", "coord-page", "résumé"],
    ["cime", "envoyer", "--a", "assistant", "--a", "coord", "x"],
    ["cime", "envoyer", "résumé"],
    ["cime", "envoyer", "--a", "assistant", "--exec", "x", "résumé"],
    ["cime", "envoyer", "--a", "assistant", "résumé", "autre"],
    ["cime", "envoyer", "--a", "assistant", "--nature"],
    ["cime", "envoyer", "--a", "assistant", "--en-reponse-a", "42", "ok"],
    ["cime", "repondre", "ok"],
    ["cime", "repondre", "42"],
    ["cime", "repondre", "42", "--nature", "accord", "ok"],
    ["cime", "repondre", "42", "--a", "coord-page", "ok"],
    ["cime", "repondre", "42", "ok", "autre"],
    ["cime", "repondre", "42", "--fichier", "x.md", "--fichier", "y.md", "ok"],
    ["cime", "accorder"],
    ["cime", "accorder", "abc"],
    ["cime", "accorder", "42", "--modele", "opus"],
    ["cime", "accorder", "42", "--parallele"],
    ["cime", "accorder", "42", "ok"],
    ["cime", "refuser", "42"],
    ["cime", "refuser", "42", "-x"],
    ["cime", "refuser", "42", "un", "deux"],
    ["cime", "refuser", "abc", "motif"],
    ["cime", "fusions-auto"],
    ["cime", "fusions-auto", ""],
    ["cime", "fusions-auto", "autre"],
    ["cime", "fusions-auto", "oui"],
    ["cime", "fusions-auto", "active", "--x"],
    ["cime", "fusions-auto", "active", "inactive"],
    ["cime", "fusions-auto", "--active"],
    ["cime", "autre"],
    ["sh", "-c", "id"],
    ["bash", "-c", "id"],
    ["zsh", "-c", "id"],
    ["env", "x"],
    ["python", "-c", "1"],
    ["rm", "-rf", "x"],
    ["cat", "x"],
    [],
    "tmux list-sessions",
    ["tmux", 1],
]


@pytest.mark.parametrize("argv", AUTORISES)
def test_autorise(argv):
    G.autoriser_commande(argv)


@pytest.mark.parametrize("argv", INTERDITS, ids=lambda a: str(a)[:60])
def test_interdit(argv):
    with pytest.raises(Interdit):
        G.autoriser_commande(argv)


def test_fusions_auto_forme_substituee():
    """Commande d'envoi substituée (essais) : `<envoyer> fusions-auto V` seulement, comme `accorder`."""
    g = Gardes("cc-essai", envoyer=[sys.executable, "faux.py"])
    assert g.fusions_auto is None
    g.autoriser_commande([sys.executable, "faux.py", "fusions-auto", "active"])
    g.autoriser_commande([sys.executable, "faux.py", "fusions-auto", "inactive"])
    for reste in (["fusions-auto"], ["fusions-auto", "oui"], ["fusions-auto", "active", "x"]):
        with pytest.raises(Interdit):
            g.autoriser_commande([sys.executable, "faux.py", *reste])


def test_executer_refuse_avant_de_lancer():
    with pytest.raises(Interdit):
        G.executer(["git", "push"])


def test_python_seulement_si_prefixe_injecte():
    faux = [sys.executable, "faux.py"]
    g = Gardes("cc-essai", envoyer=faux)
    g.autoriser_commande(faux + ["--a", "assistant", "résumé"])
    with pytest.raises(Interdit):
        g.autoriser_commande(faux + ["--a", "coord", "résumé"])
    with pytest.raises(Interdit):
        g.autoriser_commande([sys.executable, "-c", "1"])
    with pytest.raises(Interdit):
        G.autoriser_commande(faux + ["--a", "assistant", "résumé"])


def test_socket_tmux_insere_ou_absente(monkeypatch):
    vus = []

    def faux_run(argv, **kw):
        vus.append(list(argv))

    monkeypatch.setattr("cime.hote.gardes.subprocess.run", faux_run)
    Gardes("cc-essai", tmux_socket="/x/y/hote.sock").executer(["tmux", "list-sessions"])
    Gardes("cc-essai").executer(["tmux", "list-sessions"])
    assert vus == [["tmux", "-S", "/x/y/hote.sock", "list-sessions"], ["tmux", "list-sessions"]]


@pytest.mark.parametrize(
    "chemin",
    [
        "",
        "relatif/hote.sock",
        "/x/a b.sock",
        "/x/a;b.sock",
        "/x/../hote.sock",
        "/" + "a" * 100 + ".sock",
    ],
)
def test_socket_tmux_invalide(chemin):
    with pytest.raises(ValueError):
        Gardes("cc-essai", tmux_socket=chemin)


def test_socket_tmux_accepte_un_chemin_pathlike():
    assert Gardes("cc-essai", tmux_socket=Path("/x/y/hote.sock")).tmux_socket == "/x/y/hote.sock"


@pytest.mark.parametrize("socket", [None, "/x/y/hote.sock"])
@pytest.mark.parametrize(
    "argv",
    [
        ["tmux", "-L", "autre", "list-sessions"],
        ["tmux", "-S", "/tmp/x", "list-sessions"],
        ["tmux", "list-sessions", "-L", "autre"],
        ["tmux", "has-session", "-L", "x", "-t", "cc-essai-x"],
    ],
)
def test_serveur_tmux_choix_reserve_aux_gardes(socket, argv):
    with pytest.raises(Interdit):
        Gardes("cc-essai", tmux_socket=socket).executer(argv)


def test_list_sessions_reel():
    import shutil

    if not shutil.which("tmux"):
        pytest.skip("tmux absent")
    r = Gardes("cc-essai", tmux_socket=SOCKET_ESSAI).executer(["tmux", "list-sessions"])
    assert r.returncode in (0, 1)


def test_tmux_essai_leve_si_new_session_echoue():
    import shutil

    if not shutil.which("tmux"):
        pytest.skip("tmux absent")
    with pytest.raises(AssertionError):
        tmux_essai("new-session", "-d", "-s", "x", "sleep 1", socket="/nonexistent/x.sock")


def test_socket_d_essai_dans_le_worktree():
    racine = str(Path(__file__).resolve().parents[2])
    assert SOCKET_ESSAI.startswith(racine + "/")
    assert "/tmp/tmux-" not in SOCKET_ESSAI


def test_aexecuter_refuse():
    import asyncio

    with pytest.raises(Interdit):
        asyncio.run(G.aexecuter(["sh", "-c", "id"]))


# -- inventaire statique -------------------------------------------------
INTERDIT_IMPORTS = {"subprocess", "pty", "pexpect"}
ATTRS_OS = re.compile(r"^(system|popen|exec.*|spawn.*)$")


def violations(source: str) -> list[str]:
    arbre = ast.parse(source)
    trouvees = []
    for n in ast.walk(arbre):
        if isinstance(n, ast.Import):
            trouvees += [a.name for a in n.names if a.name.split(".")[0] in INTERDIT_IMPORTS]
        elif isinstance(n, ast.ImportFrom):
            m = (n.module or "").split(".")[0]
            if m in INTERDIT_IMPORTS:
                trouvees.append(n.module)
            if m == "os":
                trouvees += [f"os.{a.name}" for a in n.names if ATTRS_OS.match(a.name)]
            if m == "asyncio":
                trouvees += [a.name for a in n.names if a.name.startswith("create_subprocess_")]
        elif isinstance(n, ast.Attribute):
            if isinstance(n.value, ast.Name):
                if n.value.id == "os" and ATTRS_OS.match(n.attr):
                    trouvees.append(f"os.{n.attr}")
                if n.value.id == "asyncio" and n.attr.startswith("create_subprocess_"):
                    trouvees.append(f"asyncio.{n.attr}")
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "__import__":
            trouvees.append("__import__")
    return trouvees


def fichiers_hors_gardes():
    return [p for p in SRC.rglob("*.py") if p.name != "gardes.py"]


def test_aucun_processus_hors_gardes():
    assert fichiers_hors_gardes()
    for p in fichiers_hors_gardes():
        assert violations(p.read_text()) == [], p.name


@pytest.mark.parametrize(
    "code",
    [
        "import subprocess",
        "from subprocess import run",
        "import pty",
        "import pexpect",
        "import os\nos.system('x')",
        "import os\nos.popen('x')",
        "import os\nos.execv('x', [])",
        "import os\nos.spawnl(0, 'x')",
        "from os import system",
        "import asyncio\nasyncio.create_subprocess_exec('x')",
        "from asyncio import create_subprocess_shell",
    ],
)
def test_detecteur_attrape_la_violation(code):
    assert violations(code)


def test_inventaire_echoue_si_un_fichier_viole(tmp_path):
    intrus = SRC / "_intrus_temporaire.py"
    intrus.write_text("import subprocess\nsubprocess.run(['ls'])\n")
    try:
        with pytest.raises(AssertionError):
            test_aucun_processus_hors_gardes()
    finally:
        intrus.unlink()
    test_aucun_processus_hors_gardes()


# -- inventaire des routes -----------------------------------------------
def test_inventaire_des_routes(tmp_path):
    app = creer_app(tmp_path, Dependances(instantane=lambda p: {}), 8765)
    trouvees = set()
    for r in app.routes:
        if isinstance(r, Mount):
            trouvees.add(("MOUNT", r.path))
        else:
            assert isinstance(r, Route)
            for m in r.methods - {"HEAD"}:
                trouvees.add((m, re.sub(r"\{[^}]*\}", "{}", r.path)))
    attendues = {
        ("GET", "/"),
        ("MOUNT", "/static"),
        ("MOUNT", "/scene"),
        ("GET", "/api/etat"),
        ("GET", "/api/flux"),
        ("GET", "/api/journal"),
        ("GET", "/api/agents/{}/terminal"),
        ("GET", "/api/fichier"),
        ("POST", "/api/permissions"),
    } | {("POST", f"/api/actions/{a}") for a in
         ("autoriser", "refuser", "accorder", "cloturer", "trancher", "deposer", "lu", "demander",
          "fusions-auto")}
    assert trouvees == attendues


# -- chemin_lisible -------------------------------------------------------
@pytest.fixture
def orga(tmp_path):
    o = tmp_path / ".orga"
    (o / "teams/a").mkdir(parents=True)
    (o / "teams/a/mandate.md").write_text("m")
    (o / "x").mkdir()
    (o / "x/.env").write_text("secret")
    (o / "x/cle.pem").write_text("k")
    (o / "x/.ssh").mkdir()
    (o / "x/.ssh/config").write_text("c")
    (o / "lien").symlink_to(Path.home())
    (o / "lien-env").symlink_to(o / "x/.env")
    (tmp_path / "dehors.md").write_text("d")
    return o


def test_chemin_ok(orga):
    assert chemin_lisible(orga, "teams/a/mandate.md") == (orga / "teams/a/mandate.md").resolve()


@pytest.mark.parametrize(
    "rel",
    [
        "../dehors.md",
        "teams/../../dehors.md",
        "/etc/passwd",
        "lien",
        "lien/.zshrc",
        "x/.env",
        "x/cle.pem",
        "x/.ssh/config",
        "lien-env",
    ],
)
def test_chemin_interdit(orga, rel):
    with pytest.raises(Interdit):
        chemin_lisible(orga, rel)
