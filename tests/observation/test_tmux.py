"""Lecture de tmux : sessions, brouillons, écrans de démarrage, sur des captures d'écran et un faux `subprocess`."""

import shutil
import subprocess
from pathlib import Path

import pytest

from chrono import meilleur
from cime.observation import tmux

CAPTURES = Path(__file__).parent / "fixtures" / "captures"


def lire(nom: str) -> str:
    return (CAPTURES / nom).read_text(encoding="utf-8")


def test_aucune_capture_hors_projet_cc():
    for f in CAPTURES.glob("*.ansi"):
        assert f.name.startswith(("cc-", "suggestion-", "brouillon-", "autorisation", "demarrage-")), f.name
        assert not f.name.startswith("cc-assistant")


@pytest.mark.parametrize("f", sorted(p.name for p in CAPTURES.glob("cc-coord-*.ansi")))
def test_invite_vide_reelle(f):
    assert tmux.extraire_brouillon(lire(f)) == ""


@pytest.mark.parametrize("f", sorted(p.name for p in CAPTURES.glob("suggestion-*.ansi")))
def test_suggestion_attenuee_reelle_n_est_pas_un_brouillon(f):
    capture = lire(f)
    assert "\x1b[2m" in capture  # la suggestion atténuée est bien présente
    assert tmux.extraire_brouillon(capture) == ""


def test_suggestions_reelles_presentes():
    assert len(list(CAPTURES.glob("suggestion-*.ansi"))) >= 2


def test_brouillon_une_ligne():
    assert (
        tmux.extraire_brouillon(lire("brouillon-une-ligne.ansi"))
        == "refais l'analyse du fichier alpha, version é ü"
    )


def test_brouillon_deux_lignes():
    assert (
        tmux.extraire_brouillon(lire("brouillon-deux-lignes.ansi"))
        == "première ligne du brouillon\nseconde ligne du brouillon"
    )


def test_ecran_d_autorisation_sans_invite():
    assert tmux.extraire_brouillon(lire("autorisation.ansi")) is None


def test_invite_introuvable():
    assert tmux.extraire_brouillon("") is None
    assert tmux.extraire_brouillon("juste du texte\nsans invite") is None


def test_attenue_apres_brouillon_reel_ecarte():
    regle = "\x1b[38;5;244m" + "─" * 20 + "\x1b[39m"
    cap = f"{regle}\n\x1b[39m❯ vrai\x1b[2m fantôme\x1b[0m\n{regle}\n"
    assert tmux.extraire_brouillon(cap) == "vrai"
    cap = f"{regle}\n\x1b[39m❯ \x1b[2mfantôme\x1b[22m suite\n{regle}\n"
    assert tmux.extraire_brouillon(cap) == "suite"


def test_historique_n_est_pas_l_invite():
    # l'écho « ❯ texte » dans l'historique n'est pas encadré de règles
    cap = "\x1b[48;5;237m❯ ancien message\x1b[0m\nréponse\n"
    assert tmux.extraire_brouillon(cap) is None


class Espion:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.appels = []
        self.res = subprocess.CompletedProcess([], returncode, stdout, stderr)

    def __call__(self, cmd, **kw):
        self.appels.append(cmd)
        return self.res


def test_assistant_jamais_capture(monkeypatch):
    espion = Espion(stdout=lire("cc-coord-alpha.ansi"))
    monkeypatch.setattr(subprocess, "run", espion)
    res, source = tmux.lire_invites(["cc-assistant", "cc-coord-page"], "cc")
    assert source == {"nom": "tmux-invites", "ok": True}
    assert res == {"cc-assistant": {"brouillon": None, "ecran_demarrage": None},
                   "cc-coord-page": {"brouillon": "", "ecran_demarrage": None}}
    assert all("cc-assistant" not in c for c in espion.appels)
    assert len(espion.appels) == 1


def test_seulement_lecture(monkeypatch):
    espion = Espion(stdout="cc-coord-x\t1760000000\t1760000100\n")
    monkeypatch.setattr(subprocess, "run", espion)
    tmux.lister_sessions("cc")
    tmux.lire_invites(["cc-coord-x"], "cc")
    verbes = {c[1] for c in espion.appels}
    assert verbes == {"list-sessions", "capture-pane"}
    assert all("send-keys" not in c for c in espion.appels)


def test_lister_filtre_et_identite(monkeypatch):
    sortie = (
        "cc-assistant\t1760000000\t1760000100\n"
        "cc-coord-page\t1760000000\t1760000100\n"
        "cc-worker-obs-t3-tmux\t1760000000\t1760000100\n"
        "cc-essai-obs-brouillon\t1760000000\t1760000100\n"
        "coord-banc\t1760000000\t1760000100\n"
        "ccx-coord-a\t1760000000\t1760000100\n"
    )
    monkeypatch.setattr(subprocess, "run", Espion(stdout=sortie))
    res, source = tmux.lister_sessions("cc")
    assert source == {"nom": "tmux", "ok": True}
    assert set(res) == {
        "cc-assistant", "cc-coord-page", "cc-worker-obs-t3-tmux", "cc-essai-obs-brouillon",
    }
    assert res["cc-assistant"]["identite"] == "assistant"
    assert res["cc-coord-page"]["identite"] == "coord-page"
    assert res["cc-worker-obs-t3-tmux"]["identite"] == "worker-obs-t3-tmux"
    assert res["cc-essai-obs-brouillon"]["identite"] is None
    assert res["cc-coord-page"]["creee"] == "2025-10-09T08:53:20.000Z"


@pytest.mark.skipif(not shutil.which("tmux"), reason="tmux absent")
def test_serveur_absent_est_un_echec(monkeypatch, tmp_path):
    monkeypatch.setenv("TMUX_TMPDIR", str(tmp_path))
    monkeypatch.delenv("TMUX", raising=False)
    res, source = tmux.lister_sessions("cc")
    assert res is None
    assert source["ok"] is False
    assert source["erreur"] == "aucun serveur tmux"


def test_tmux_introuvable(monkeypatch):
    def boum(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", boum)
    res, source = tmux.lister_sessions("cc")
    assert res is None and source["ok"] is False


@pytest.mark.skipif(not shutil.which("tmux"), reason="tmux absent")
def test_vraie_machine_ne_leve_pas():
    res, source = tmux.lister_sessions("cc")
    assert source["nom"] == "tmux"
    assert (res is None) == (source["ok"] is False)


def test_quinze_sessions_en_parallele(monkeypatch):
    import time

    def lent(cmd, **kw):
        time.sleep(0.2)
        return subprocess.CompletedProcess([], 0, lire("cc-coord-alpha.ansi"), "")

    monkeypatch.setattr(subprocess, "run", lent)
    noms = [f"cc-coord-s{i}" for i in range(15)]
    duree, (res, _) = meilleur(lambda: tmux.lire_invites(noms, "cc"), 3)
    assert duree < 0.5  # en série : 15 × 0,2 s = 3 s
    assert {v["brouillon"] for v in res.values()} == {""}


# --- écrans de démarrage ------------------------------------------------------------------

def test_ecran_demarrage_captures_reelles():
    assert tmux.ecran_demarrage(lire("demarrage-confiance-dossier.ansi")) == "confiance"
    assert tmux.ecran_demarrage(lire("demarrage-imports-externes.ansi")) == "imports"


@pytest.mark.parametrize("f", sorted(p.name for p in CAPTURES.glob("cc-coord-*.ansi")))
def test_ecran_demarrage_invite_ordinaire_none(f):
    assert tmux.ecran_demarrage(lire(f)) is None


def test_ecran_demarrage_autre_et_vide():
    assert tmux.ecran_demarrage("Quelque chose\n Enter to confirm · Esc to cancel \n\n") == "autre"
    assert tmux.ecran_demarrage("") is None


def citation_au_milieu() -> str:
    """Capture cc-coord-beta avec, au milieu, des lignes citant l'écran (fabriqué)."""
    lignes = lire("cc-coord-beta.ansi").split("\n")
    citation = ["Quick safety check: Is this a project you created or one you trust?",
                "Allow external CLAUDE.md file imports?", "Enter to confirm · Esc to cancel"]
    return "\n".join(lignes[:2] + citation + lignes[2:])


def test_ecran_demarrage_citation_au_milieu_ne_compte_pas():
    assert "Enter to confirm" in citation_au_milieu()
    assert tmux.ecran_demarrage(citation_au_milieu()) is None


def test_lire_invites_une_seule_capture_par_session(monkeypatch):
    espion = Espion(stdout=lire("demarrage-confiance-dossier.ansi"))
    monkeypatch.setattr(subprocess, "run", espion)
    res, _ = tmux.lire_invites(["cc-coord-page"], "cc")
    assert res["cc-coord-page"]["ecran_demarrage"] == "confiance"
    assert len(espion.appels) == 1


def test_list_sessions_lit_window_activity(monkeypatch):
    espion = Espion(stdout="cc-coord-x\t1760000000\t1760000100\n")
    monkeypatch.setattr(subprocess, "run", espion)
    res, _ = tmux.lister_sessions("cc")
    fmt = espion.appels[0][espion.appels[0].index("-F") + 1]
    assert "window_activity" in fmt and "session_activity" not in fmt and "session_created" in fmt
    assert res["cc-coord-x"]["activite"] == tmux._iso("1760000100")


def test_modele_de_la_commande_de_lancement(monkeypatch):
    # Commande d'un worker (forme de `#{pane_start_command}`), tabulation comprise.
    espion = Espion(stdout=(
        'cc-worker-a-t1\t1760000000\t1760000100\t/tmp/w\t"claude --model claude-haiku-4-5-20251001 '
        '--permission-mode auto \\"Lis\tla tâche\\""\n'
        "cc-coord-b\t1760000000\t1760000100\t/tmp/b\tclaude --model=sonnet\n"
        "cc-coord-c\t1760000000\t1760000100\t\tzsh\n"
        "cc-coord-d\t1760000000\t1760000100\n"))
    monkeypatch.setattr(subprocess, "run", espion)
    res, _ = tmux.lister_sessions("cc")
    fmt = espion.appels[0][espion.appels[0].index("-F") + 1]
    assert fmt.endswith("\t#{pane_start_command}")
    assert {n: s["modele_lancement"] for n, s in res.items()} == {
        "cc-worker-a-t1": "claude-haiku-4-5-20251001", "cc-coord-b": "sonnet",
        "cc-coord-c": None, "cc-coord-d": None}
    assert {n: s["cwd"] for n, s in res.items()} == {
        "cc-worker-a-t1": "/tmp/w", "cc-coord-b": "/tmp/b", "cc-coord-c": None, "cc-coord-d": None}
    assert "#{pane_current_path}" in fmt
