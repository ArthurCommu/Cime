"""Les réglages générés d'un agent, octet pour octet : chaque rôle produit exactement le
fichier de référence (`references/reglages-<cas>.json`), tout ce qui varie étant fixé."""
import json
import os
import re
import subprocess
import textwrap
from pathlib import Path

import pytest

from cime.fondation import lancer
from cime.fondation import reglages as reglages_mod
from cime.fondation.nom import VAR_PROJET
from cime.fondation.projet import ErreurProjet, lire_manifeste
from cime.fondation.reglages import INTERDITS_INTEGRATION

# Le module qui construit les réglages générés : seul endroit à changer si cette
# construction change de module.
SUT = reglages_mod

REFERENCES = Path(__file__).resolve().parent / "references"
MARQUEUR = "<RACINE>"
MANIFESTE = textwrap.dedent("""\
    nom = "Essai"
    prefixe = "essai"
    branche_reference = "main"
    branche_equipe = "equipe/{equipe}"
    worktree_equipe = ".orga/worktrees/{equipe}"
    equipes_speciales = ["assistant"]
    modele_assistant = "modele-assistant"
    modele_coordinateur = "modele-coord"

    [bac_a_sable]
    sites = ["b.example", "a.example"]
""")
STATIQUES = {
    "settings.json": {"marque": "assistant", "hooks": {"Stop": [{"hooks": [
        {"type": "command", "command": "exemple hook Stop"}]}]},
        "permissions": {"allow": ["Bash(ls*)"], "deny": ["Bash(rm*)"]},
        "sandbox": {"enabled": False}},
    "settings-agent.json": {"marque": "agent", "env": {"A": "1"},
                            "permissions": {"allow": ["Bash(ls*)"], "deny": []}},
    "settings-coordinateur.json": {"marque": "coord",
                                   "permissions": {"allow": ["Bash(ls*)"], "deny": []}},
}
# cas : (identité, rôle, intégration)
CAS = {
    "assistant": ("assistant", "assistant", False),
    "worker": ("worker-x-y", "worker", False),
    "coord": ("coord-z", "coord", False),
    "coord-worktree": ("coord-x", "coord", False),
    "integration": ("worker-integration-r1", "coord", True),
}


def _git(dossier, *a):
    subprocess.run(["git", "-C", str(dossier), "-c", "user.name=t",
                    "-c", "user.email=t@t", *a], check=True, capture_output=True)


@pytest.fixture
def projet(tmp_path, monkeypatch):
    racine = tmp_path.resolve()
    maison = racine / "maison"
    maison.mkdir()
    monkeypatch.setenv("HOME", str(maison))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: maison))
    monkeypatch.setattr(os, "getuid", lambda: 501)
    monkeypatch.delenv(VAR_PROJET, raising=False)
    monkeypatch.setattr(SUT, "dossier_outil", lambda: racine / "outil")
    monkeypatch.setattr(SUT, "dossier_source_cime", lambda: racine / "source" / "src")
    depot = racine / "depot"
    for equipe in ("x", "z", "integration"):
        (depot / ".orga" / "teams" / equipe / "tasks" / "todo").mkdir(parents=True)
        (depot / ".orga" / "teams" / equipe / "mandate.md").write_text("mandat")
    (depot / ".orga" / "projet.toml").write_text(MANIFESTE)
    (depot / ".claude").mkdir()
    for nom, contenu in STATIQUES.items():
        (depot / ".claude" / nom).write_text(json.dumps(contenu))
    _git(depot, "init", "-q", "-b", "main")
    _git(depot, "add", "-A")
    _git(depot, "commit", "-qm", "init")
    _git(depot, "worktree", "add", "-q", "-b", "equipe/x", str(depot / ".orga/worktrees/x"))
    monkeypatch.chdir(depot)
    return depot


def _normaliser(texte: str, projet: Path) -> str:
    return texte.replace(str(projet.parent), MARQUEUR)


def _ecrit(projet: Path, cas: str) -> tuple[str, dict]:
    identite, role, integration = CAS[cas]
    manifeste = lire_manifeste(projet)
    attendu = SUT.contenu_reglages_generes(projet, identite, role, manifeste, integration)
    fichier = SUT.ecrire_reglages_generes(projet, identite, role, manifeste, integration)
    return _normaliser(fichier.read_bytes().decode("utf-8"), projet), attendu


@pytest.mark.parametrize("cas", list(CAS))
def test_reglages_octet_pour_octet(projet, cas):
    texte, contenu = _ecrit(projet, cas)
    reference = REFERENCES / f"reglages-{cas}.json"
    if os.environ.get("REGENERER_REFERENCES"):
        REFERENCES.mkdir(exist_ok=True)
        reference.write_bytes(texte.encode("utf-8"))
    assert reference.read_bytes() == texte.encode("utf-8")
    assert _normaliser(json.dumps(contenu, indent=2, ensure_ascii=False) + "\n",
                       projet) == texte


def test_l_integration_porte_ses_interdits_et_ses_essais(projet):
    texte, _ = _ecrit(projet, "integration")
    contenu = json.loads(texte)
    assert all(r in contenu["permissions"]["deny"] for r in INTERDITS_INTEGRATION)
    assert len(INTERDITS_INTEGRATION) == 12
    assert f"{MARQUEUR}/depot/.orga/etat/essais" in contenu["sandbox"]["filesystem"]["allowWrite"]
    ordinaire, _ = _ecrit(projet, "coord")
    assert ".orga/etat/essais" not in ordinaire


def test_les_references_sont_non_vides_et_toutes_differentes():
    textes = {}
    for cas in CAS:
        texte = (REFERENCES / f"reglages-{cas}.json").read_text(encoding="utf-8")
        assert len(texte) > 300, cas
        assert json.loads(texte), cas
        textes[cas] = texte
    assert len(set(textes.values())) == len(CAS)


def test_les_references_disent_le_contenu_attendu():
    lu = {cas: json.loads((REFERENCES / f"reglages-{cas}.json").read_text(encoding="utf-8"))
          for cas in CAS}
    assert "sandbox" not in lu["assistant"]
    assert lu["assistant"]["autoMemoryDirectory"] == f"{MARQUEUR}/depot/.orga/etat/memoire/assistant"
    for cas in ("worker", "coord", "coord-worktree", "integration"):
        assert lu[cas]["sandbox"]["filesystem"]["denyRead"] == [f"{MARQUEUR}/maison"], cas
        assert lu[cas]["sandbox"]["network"]["allowedDomains"] == ["b.example", "a.example"], cas
        assert f"{MARQUEUR}/outil" in lu[cas]["sandbox"]["filesystem"]["allowRead"], cas
        assert f"{MARQUEUR}/source/src" in lu[cas]["sandbox"]["filesystem"]["allowRead"], cas
    assert any("commit*" in r and "/.orga/worktrees/x" in r
               for r in lu["coord-worktree"]["permissions"]["allow"])
    assert any(r.startswith("Bash(git -C") and "/.orga/worktrees/z" in r
               for r in lu["coord"]["permissions"]["allow"])
    assert lu["worker"]["permissions"]["allow"] == ["Bash(ls*)"]
    assert lu["worker"]["env"] == {"A": "1"}


# --- l'architecture : la sécurité de l'agent n'est plus dans `lancer.py` ------------

SOURCES = Path(__file__).resolve().parents[2] / "src" / "cime" / "fondation"


@pytest.mark.parametrize("motif", ['"sandbox":', "bac_a_sable(", "denyRead", "allowRead",
                                   "allowWrite", "autoMemoryDirectory"])
def test_lancer_ne_construit_plus_le_bac_a_sable_ni_les_reglages_generes(motif):
    assert motif not in (SOURCES / "lancer.py").read_text(encoding="utf-8")


def test_reglages_n_importe_pas_lancer():
    source = (SOURCES / "reglages.py").read_text(encoding="utf-8")
    assert not re.search(r"^\s*(from\s+cime\.fondation\.lancer\b|"
                         r"from\s+cime\.fondation\s+import\s+.*\blancer\b|import\s+.*\blancer\b)",
                         source, re.MULTILINE)


def test_refus_est_une_seule_classe():
    assert lancer.Refus is reglages_mod.Refus
    assert issubclass(reglages_mod.Refus, ErreurProjet)


def test_construire_reglages_ne_modifie_pas_le_statique_ne_pas_muter(tmp_path):
    statique = {"permissions": {"allow": ["Bash(ls*)"], "deny": ["Bash(rm*)"]}}
    avant = json.dumps(statique)
    contenu = SUT.construire_reglages(
        statique, tmp_path / "p", "coord-x", [], tmp_path / "maison", 501, [],
        regles_allow=["Bash(git add*)"], regles_deny=("Bash(git push*)",))
    assert contenu["permissions"] == {"allow": ["Bash(ls*)", "Bash(git add*)"],
                                      "deny": ["Bash(rm*)", "Bash(git push*)"]}
    assert json.dumps(statique) == avant
