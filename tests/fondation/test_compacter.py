import json
import argparse
import subprocess
import textwrap

import pytest

from cime.fondation import compacter
from cime.fondation.nom import VAR_AGENT, VAR_PROJET
from cime.fondation.registre import NATURES, ouvrir
from cime.signaux import ordres

MANIFESTE = textwrap.dedent("""\
    nom = "Essai"
    prefixe = "essai"
    branche_reference = "main"
    branche_equipe = "equipe/{equipe}"
    worktree_equipe = "../{depot}-{equipe}"
    equipes_speciales = ["assistant"]
    modele_assistant = "modele-assistant"
    modele_coordinateur = "modele-coord"
""")


@pytest.fixture
def projet(tmp_path, monkeypatch):
    racine = (tmp_path / "depot").resolve()
    (racine / ".orga" / "teams" / "x" / "tasks").mkdir(parents=True)
    (racine / ".orga" / "projet.toml").write_text(MANIFESTE)
    (racine / "note.md").write_text("note")
    monkeypatch.setenv(VAR_PROJET, str(racine))
    monkeypatch.setenv(VAR_AGENT, "coord-x")
    monkeypatch.chdir(racine)
    return racine


@pytest.fixture
def tmux(monkeypatch):
    """tmux simulé : `etat["invites"]` est la file des valeurs de brouillon()
    (la dernière est répétée) ; `etat["appels"]` enregistre chaque commande tmux."""
    etat = {"existantes": {"essai-worker-x-y"}, "appels": [], "invites": [""], "pauses": []}

    def faux_tmux(*args):
        etat["appels"].append(args)
        code = 0
        if args[0] == "has-session":
            code = 0 if args[2].lstrip("=") in etat["existantes"] else 1
        return subprocess.CompletedProcess(args, code, "", "")

    def faux_brouillon(cible):
        etat["appels"].append(("brouillon", cible))
        file = etat["invites"]
        return file.pop(0) if len(file) > 1 else file[0]

    monkeypatch.setattr(compacter, "_tmux", faux_tmux)
    monkeypatch.setattr(compacter.invite, "brouillon", faux_brouillon)
    monkeypatch.setattr(compacter, "_attendre", lambda s: etat["pauses"].append(s))
    return etat



def _args(identite="worker-x-y", consignes="garde les décisions"):
    return argparse.Namespace(identite=identite, consignes=consignes)


def _messages(projet):
    conn = ouvrir(projet)
    try:
        return conn.execute("SELECT de, a, nature, resume FROM messages ORDER BY id").fetchall()
    finally:
        conn.close()


def _touches(etat):
    return [a for a in etat["appels"] if a[0] == "send-keys"]


@pytest.fixture(autouse=True)
def facteur_en_ligne(monkeypatch, projet):
    """Un facteur simulé : pendant que la commande attend son ordre, il l'exécute."""
    monkeypatch.setattr(ordres, "_dormir", lambda s: ordres.facteur_une_fois(projet))


def test_texte_puis_enter_en_deux_appels(projet, tmux, capsys):
    assert compacter.executer(_args()) == 0
    cible = "=essai-worker-x-y:"
    assert _touches(tmux) == [
        ("send-keys", "-t", cible, "-l", "/compact garde les décisions"),
        ("send-keys", "-t", cible, "Enter"),
    ]
    assert _messages(projet) == [("cime", "worker-x-y", "consigne",
                                  "/compact — garde les décisions — fait")]


def test_resume_tronque_a_140(projet, tmux):
    assert compacter.executer(_args(consignes="a" * 300)) == 0
    resume = _messages(projet)[0][3]
    assert len(resume) == 140 and resume.endswith(" — fait")


def test_refus_assistant_par_un_agent(projet, tmux, capsys):
    assert compacter.executer(_args("assistant")) == 2
    assert _touches(tmux) == []
    assert _messages(projet)[0][3].endswith("— refusé : Assistant compactable par l'utilisateur seul")
    assert "l'utilisateur" in capsys.readouterr().err


@pytest.mark.parametrize("appelant,cible,attendu", [
    ("assistant", "coord-x", True),
    ("assistant", "worker-x-y", False),
    ("assistant", "assistant", False),
    ("coord-x", "worker-x-y", True),
    ("coord-x", "worker-xy-z", False),
    ("coord-x", "worker-autre-y", False),
    ("coord-x", "coord-x", False),
    ("coord-x", "worker-integration-r", False),
    ("worker-x-y", "worker-x-z", False),
    ("worker-x-y", "coord-x", False),
])
def test_est_superieur(projet, appelant, cible, attendu):
    assert compacter.est_superieur(appelant, cible, projet) is attendu


def _equipes(projet, *noms):
    for nom in noms:
        (projet / ".orga" / "teams" / nom).mkdir(parents=True, exist_ok=True)


@pytest.mark.parametrize("appelant,cible,attendu", [
    ("coord-x", "worker-x-y-t", False),
    ("coord-x-y", "worker-x-y-t", True),
    ("coord-x", "worker-x-t", True),
])
def test_est_superieur_equipes_x_et_x_y(projet, appelant, cible, attendu):
    _equipes(projet, "x", "x-y")
    assert compacter.est_superieur(appelant, cible, projet) is attendu


def test_est_superieur_seule_x_presente(projet):
    assert compacter.est_superieur("coord-x", "worker-x-y-t", projet) is True


def test_est_superieur_equipe_absente(projet):
    assert compacter.est_superieur("coord-z", "worker-z-t", projet) is False
    assert compacter.est_superieur("coord-x", "worker-z-t", projet) is False


@pytest.mark.parametrize("appelant,cible", [
    ("coord-x", "coord-x"), ("coord-x", "worker-autre-y"),
    ("worker-x-y", "worker-x-z"), ("assistant", "worker-x-y")])
def test_refus_si_pas_le_superieur(projet, tmux, monkeypatch, capsys, appelant, cible):
    monkeypatch.setenv(VAR_AGENT, appelant)
    tmux["existantes"].update({"essai-coord-x", "essai-worker-x-z", "essai-worker-autre-y"})
    assert compacter.executer(_args(cible)) == 2
    assert _touches(tmux) == []
    assert f"seul le supérieur direct de {cible} peut la compacter" in capsys.readouterr().err
    assert _messages(projet)[0][3].endswith("— refusé : pas le supérieur direct")


def test_refus_sans_identite(projet, tmux, monkeypatch):
    monkeypatch.delenv(VAR_AGENT)
    monkeypatch.setenv("CLAUDECODE", "1")
    assert compacter.executer(_args()) == 2 and _touches(tmux) == []


def test_refus_sans_projet(projet, tmux, monkeypatch):
    monkeypatch.delenv(VAR_PROJET)
    assert compacter.executer(_args()) == 2 and _touches(tmux) == []


def test_refus_session_absente(projet, tmux):
    tmux["existantes"].clear()
    assert compacter.executer(_args()) == 2 and _touches(tmux) == []
    assert _messages(projet)[0][3].endswith("— refusé : session de worker-x-y absente")


def test_plus_de_controle_d_invite_ni_de_tour_en_cours(projet, tmux):
    # le facteur attendra le repos : la commande ne refuse plus ni brouillon ni tour en cours
    tmux["invites"] = ["je tape", ""]
    assert compacter.executer(_args()) == 0
    assert len(_touches(tmux)) >= 2


def test_ordre_inscrit_puis_execute_par_le_facteur(projet, tmux):
    assert compacter.executer(_args()) == 0
    conn = ouvrir(projet)
    assert conn.execute("SELECT auteur, verbe, cible, etat FROM ordres").fetchall() == [
        ("coord-x", "compacter", "worker-x-y", "execute")]


def test_utilisateur_a_la_main_compacte_directement(projet, tmux, monkeypatch):
    monkeypatch.delenv(VAR_AGENT)
    assert compacter.executer(_args("assistant")) == 2  # session absente, mais pas refusé d'avance
    tmux["existantes"].add("essai-assistant")
    assert compacter.executer(_args("assistant")) == 0
    assert ouvrir(projet).execute("SELECT count(*) FROM ordres").fetchone() == (0,)


def test_echec_si_texte_reste_dans_l_invite(projet, tmux):
    tmux["invites"] = ["/compact x"]
    assert compacter.executer(_args()) == 1
    assert len(_messages(projet)) == 1
    assert _messages(projet)[0][3].endswith("— échec : /compact resté dans l'invite de worker-x-y")


@pytest.mark.parametrize("auteur,cible", [(None, "assistant"), ("assistant", "coord-x"),
                                          ("coord-x", "worker-x-y")])
def test_consigne_de_compactage_toujours_de_cime_auteur_dans_la_preuve(projet, tmux, monkeypatch, auteur,
                                                                       cible):
    """L'utilisateur (hors agent), l'Assistant, un coordinateur : la ligne est `cime → cible`, close, sans
    obligation ; l'auteur réel est dans la preuve, jamais un `utilisateur→…` / `coord-…→…` dans `messages`."""
    if auteur is None:
        monkeypatch.delenv(VAR_AGENT)
    else:
        monkeypatch.setenv(VAR_AGENT, auteur)
    tmux["existantes"].add(f"essai-{cible}")
    assert compacter.executer(_args(cible)) == 0
    conn = ouvrir(projet)
    (de,), = conn.execute("SELECT DISTINCT de FROM messages").fetchall()
    assert de == "cime"
    assert conn.execute("SELECT count(*) FROM messages WHERE de != 'cime'").fetchone() == (0,)
    assert conn.execute("SELECT count(*) FROM obligations").fetchone() == (0,)
    (etat, preuve), = conn.execute(
        "SELECT etat, preuve FROM transitions WHERE etat = 'clos'").fetchall()
    assert json.loads(preuve) == {"journal": "compacter", "auteur": auteur or "utilisateur"}
