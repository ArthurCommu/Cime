import json
import re
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from cime import cli
from cime.fondation import registre
from cime.fondation.nom import NOM, VAR_AGENT, VAR_PROJET
from cime.fondation.projet import (
    ErreurProjet, branche_equipe, equipe_de, lire_manifeste, session_tmux,
    trouver_projet, valider_identite, worktree_equipe,
)

MANIFESTE = textwrap.dedent("""\
    nom = "Centre de contrôle"
    prefixe = "cc"
    branche_reference = "main"
    branche_equipe = "equipe/{equipe}"
    worktree_equipe = "../{depot}-{equipe}"
    equipes_speciales = ["assistant", "integration", "verification"]
    modele_assistant = "claude-opus-5-5"
    modele_coordinateur = "claude-opus-5-5"
""")


@pytest.fixture
def projet(tmp_path, monkeypatch):
    monkeypatch.delenv(VAR_PROJET, raising=False)
    racine = tmp_path / "depot"
    (racine / ".orga").mkdir(parents=True)
    (racine / ".orga" / "projet.toml").write_text(MANIFESTE)
    return racine


def test_noms():
    assert (NOM, VAR_AGENT, VAR_PROJET) == ("cime", "CIME_AGENT", "CIME_PROJET")


def test_manifeste_complet(projet):
    m = lire_manifeste(projet)
    assert m.nom == "Centre de contrôle" and m.prefixe == "cc"
    assert m.equipes_speciales == ["assistant", "integration", "verification"]
    assert branche_equipe(m, "fondation") == "equipe/fondation"
    assert worktree_equipe(projet, m, "fondation") == (
        projet.parent / "depot-fondation").resolve()


def test_manifeste_cle_manquante(projet):
    (projet / ".orga" / "projet.toml").write_text(
        MANIFESTE.replace('prefixe = "cc"\n', ""))
    with pytest.raises(ErreurProjet) as e:
        lire_manifeste(projet)
    assert "prefixe" in str(e.value) and "projet.toml" in str(e.value)


def test_manifeste_cle_inconnue(projet):
    f = projet / ".orga" / "projet.toml"
    f.write_text(MANIFESTE + 'inconnue = 1\n')
    assert lire_manifeste(projet).prefixe == "cc"


def test_trouver_projet_remontee(projet):
    profond = projet / "a" / "b"
    profond.mkdir(parents=True)
    assert trouver_projet(profond) == projet


def test_trouver_projet_variable(projet, tmp_path, monkeypatch):
    monkeypatch.setenv(VAR_PROJET, str(projet))
    ailleurs = tmp_path / "ailleurs"
    ailleurs.mkdir()
    assert trouver_projet(ailleurs) == projet


def test_trouver_projet_echec(tmp_path, monkeypatch):
    monkeypatch.delenv(VAR_PROJET, raising=False)
    with pytest.raises(ErreurProjet, match="aucun projet trouvé"):
        trouver_projet(tmp_path)


def test_identites(projet):
    for ok in ("assistant", "utilisateur", "coord-fondation", "worker-fondation-socle"):
        assert valider_identite(ok) == ok
    for mauvais in ("", "Worker-x-y", "coord-", "coord-A", "worker-x", "robot"):
        with pytest.raises(ValueError):
            valider_identite(mauvais)
    m = lire_manifeste(projet)
    assert session_tmux(m, "coord-x") == "cc-coord-x"
    assert session_tmux(m, "utilisateur") is None


def test_equipe_de_avec_tiret(projet):
    for nom in ("a", "a-b"):
        (projet / ".orga" / "teams" / nom).mkdir(parents=True)
    assert equipe_de(projet, "coord-a-b") == "a-b"
    assert equipe_de(projet, "worker-a-b-tache") == "a-b"
    assert equipe_de(projet, "worker-a-tache") == "a"
    assert equipe_de(projet, "worker-zz-tache") is None
    assert equipe_de(projet, "assistant") is None


def test_horodatage():
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", registre.horodatage())


COLONNES = {
    "messages": ["id", "horodatage", "de", "a", "nature", "resume", "fichier",
                 "en_reponse_a", "equipe", "objet", "corps"],
    "evenements": ["id", "horodatage", "agent", "session_id", "evenement", "details"],
    "journal": ["id", "horodatage", "auteur", "action", "cible", "details", "resultat"],
}


def test_ouvrir(projet):
    conn = registre.ouvrir(projet)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    for table, colonnes in COLONNES.items():
        infos = conn.execute(f"PRAGMA table_info({table})").fetchall()
        assert [i[1] for i in infos] == colonnes
    registre.ouvrir(projet).close()  # idempotent


def test_inscrire_message(projet):
    conn = registre.ouvrir(projet)
    i = registre.inscrire_message(conn, de="assistant", a="coord-x",
                                  nature="consigne", resume="go", equipe="x")
    j = registre.inscrire_message(conn, de="coord-x", a="assistant",
                                  nature="reponse", resume="ok", en_reponse_a=i)
    assert conn.execute("SELECT en_reponse_a FROM messages WHERE id=?", (j,)).fetchone() == (i,)
    base = dict(de="a", a="b", nature="consigne", resume="r")
    for changement in ({"nature": "bidule"}, {"resume": "a\nb"},
                       {"resume": "x" * 161}, {"en_reponse_a": 999}):
        with pytest.raises(ValueError):
            registre.inscrire_message(conn, **{**base, **changement})
    registre.inscrire_message(conn, **{**base, "resume": "x" * 160})


def test_inscrire_evenement(projet):
    conn = registre.ouvrir(projet)
    i = registre.inscrire_evenement(conn, agent="assistant", session_id="s",
                                    evenement="Stop", details={"é": 1})
    d = conn.execute("SELECT details FROM evenements WHERE id=?", (i,)).fetchone()[0]
    assert d == '{"é": 1}' and json.loads(d) == {"é": 1}


ECRIVAIN = """
import sys
from pathlib import Path
from cime.fondation import registre
conn = registre.ouvrir(Path(sys.argv[1]))
for k in range(200):
    registre.inscrire_message(conn, de=sys.argv[2], a="x", nature="signalement", resume=str(k))
"""


def test_ecritures_paralleles(projet):
    registre.ouvrir(projet).close()
    src = str(Path(__file__).resolve().parents[2] / "src")
    procs = [subprocess.Popen([sys.executable, "-c", ECRIVAIN, str(projet), n],
                              env={"PYTHONPATH": src}, stderr=subprocess.PIPE, text=True)
             for n in ("p1", "p2")]
    for p in procs:
        _, err = p.communicate(timeout=60)
        assert p.returncode == 0, err
    n = sqlite3.connect(registre.chemin_registre(projet)).execute(
        "SELECT COUNT(*) FROM messages").fetchone()[0]
    assert n == 400


# --- CLI ---

def _sans_module(monkeypatch, *noms):
    """Rend ces modules introuvables, même s'ils existent par ailleurs."""
    for nom in noms:
        monkeypatch.setitem(sys.modules, nom, None)  # -> ImportError, pas ModuleNotFoundError
    real = cli.importlib.import_module

    def faux(nom, *a, **k):
        if nom in noms:
            raise ModuleNotFoundError(f"No module named {nom!r}", name=nom)
        return real(nom, *a, **k)
    monkeypatch.setattr(cli.importlib, "import_module", faux)


def test_cli_hook_module_absent(monkeypatch):
    _sans_module(monkeypatch, "cime.fondation.hook")
    assert cli.main(["hook", "Stop"]) == 0


def test_cli_hook_erreur_argparse():
    assert cli.main(["hook"]) == 0


def test_cli_hook_exception(monkeypatch):
    def boum(args):
        raise RuntimeError("boum")
    monkeypatch.setattr(cli, "_executer", boum)
    assert cli.main(["hook", "Stop"]) == 0


def test_cli_non_livree(monkeypatch, capsys):
    _sans_module(monkeypatch, "cime.fondation.envoyer")
    assert cli.main(["envoyer", "--a", "x", "--nature", "consigne", "r"]) == 2
    assert "envoyer : pas encore livrée dans cette version" in capsys.readouterr().err


def test_cli_livree_appelee(monkeypatch):
    class Faux:
        @staticmethod
        def executer(args):
            return 7 if args.role == "coord" and args.equipe == "x" else 99
    real = cli.importlib.import_module
    monkeypatch.setattr(cli.importlib, "import_module",
                        lambda n, *a, **k: Faux if n == "cime.fondation.lancer" else real(n, *a, **k))
    assert cli.main(["lancer", "coord", "x", "--essai-a-blanc"]) == 7


@pytest.mark.parametrize("cmd,module,msg", [
    ("servir", "cime.hote", "servir : le module hôte (cime.hote) n'est pas présent"),
    ("etat", "cime.observation", "etat : le module d'observation (cime.observation)"),
])
def test_cli_modules_optionnels_absents(cmd, module, msg, projet, monkeypatch, capsys):
    monkeypatch.chdir(projet)
    _sans_module(monkeypatch, module)
    assert cli.main([cmd]) == 1
    assert msg in capsys.readouterr().err


def test_cli_etat(projet, monkeypatch, capsys):
    import types
    monkeypatch.chdir(projet)
    mod = types.ModuleType("cime.observation")
    mod.instantane = lambda p: {"projet": p.name, "é": 1}
    monkeypatch.setitem(sys.modules, "cime.observation", mod)
    assert cli.main(["etat"]) == 0
    assert json.loads(capsys.readouterr().out) == {"projet": "depot", "é": 1}


def test_cli_erreur_projet(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(VAR_PROJET, raising=False)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["servir"]) == 1
    assert "aucun projet trouvé" in capsys.readouterr().err


def test_index_du_registre(projet):
    # six index, colonnes dans cet ordre
    attendus = {
        ("evenements", ("agent", "evenement", "horodatage", "id")),
        ("evenements", ("agent", "horodatage", "id")),
        ("evenements", ("evenement", "horodatage", "id")),
        ("messages", ("horodatage", "id")),
        ("messages", ("en_reponse_a", "nature")),
        ("messages", ("nature", "horodatage", "id")),
    }
    conn = registre.ouvrir(projet)
    trouves = set()
    for table in ("evenements", "messages"):
        for _, nom, *_ in conn.execute(f"PRAGMA index_list({table})").fetchall():
            colonnes = tuple(r[2] for r in conn.execute(f"PRAGMA index_info({nom})"))
            trouves.add((table, colonnes))
    assert attendus <= trouves


# --- un projet.toml sous .orga/worktrees/ n'est jamais un projet ----------------------

def _depot_avec_worktree(tmp_path):
    racine = tmp_path / "depot"
    copie = racine / ".orga" / "worktrees" / "x" / ".orga"
    copie.mkdir(parents=True)
    (racine / ".orga" / "projet.toml").write_text(MANIFESTE)
    (copie / "projet.toml").write_text(MANIFESTE)  # copie tracée par git dans le worktree
    return racine, racine / ".orga" / "worktrees" / "x"


def test_un_agent_d_un_worktree_remonte_jusqu_au_vrai_projet(tmp_path, monkeypatch):
    from cime.fondation.nom import VAR_PROJET
    from cime.fondation.projet import trouver_projet
    racine, worktree = _depot_avec_worktree(tmp_path)
    monkeypatch.delenv(VAR_PROJET, raising=False)
    assert trouver_projet(worktree) == racine
    assert trouver_projet(worktree / ".orga") == racine


def test_cime_projet_vers_un_worktree_est_ignore(tmp_path, monkeypatch):
    from cime.fondation.nom import VAR_PROJET
    from cime.fondation.projet import trouver_projet
    racine, worktree = _depot_avec_worktree(tmp_path)
    monkeypatch.setenv(VAR_PROJET, str(worktree))
    assert trouver_projet(worktree) == racine


def _dossier_hors_de_tout_projet(tmp_path):
    """Un dossier sans `.orga/projet.toml` dans ses ancêtres : `/private/tmp` si on peut y
    écrire, sinon `tmp_path` ; None si un projet est au-dessus (TMPDIR dans le vrai projet)."""
    import tempfile
    try:
        base = Path(tempfile.mkdtemp(dir="/private/tmp"))
    except OSError:
        base = tmp_path
    if any((p / ".orga" / "projet.toml").exists() for p in [base, *base.parents]):
        return None
    return base


def test_worktree_sans_vrai_projet_echoue_pas_de_projet(tmp_path, monkeypatch):
    from cime.fondation.nom import VAR_PROJET
    from cime.fondation.projet import ErreurProjet, trouver_projet
    base = _dossier_hors_de_tout_projet(tmp_path)
    if base is None:
        pytest.skip("un .orga/projet.toml existe au-dessus du dossier temporaire")
    racine, worktree = _depot_avec_worktree(base)
    (racine / ".orga" / "projet.toml").unlink()
    monkeypatch.delenv(VAR_PROJET, raising=False)
    with pytest.raises(ErreurProjet, match="aucun projet trouvé"):
        trouver_projet(worktree)


def test_envoyer_refuse_un_cime_projet_qui_est_un_worktree(tmp_path, monkeypatch):
    from cime.fondation import envoyer
    from cime.fondation.nom import VAR_PROJET
    racine, worktree = _depot_avec_worktree(tmp_path)
    monkeypatch.setenv(VAR_PROJET, str(worktree))
    assert envoyer._projet() is None
    monkeypatch.setenv(VAR_PROJET, str(racine))
    assert envoyer._projet() == racine.resolve()
