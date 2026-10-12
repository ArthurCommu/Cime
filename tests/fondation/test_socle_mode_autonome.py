"""Le socle (assistant.md, coordinateur.md) dit le mode autonome : dépôt et gabarit portent le même
texte après substitution, et une garde de mots obligatoires contre la dérive du texte."""
import re
import types
from pathlib import Path

import pytest

GABARIT = Path(__file__).resolve().parents[2] / "src" / "cime" / "gabarits" / ".orga" / "socle"

MOTS_OBLIGATOIRES = {
    "assistant.md": ["mode autonome", "chantier-auto:", "contrat-auto:", "autorisation-auto:", "classe", "réservé"],
    "coordinateur.md": ["classe", "`reserve`", "`autonome`", "réservé"],
}


def _bloc_assistant(texte: str) -> str:
    return texte[texte.index("**Mode autonome (option"):texte.index("**Après la fusion**")]


def _sous_section_coordinateur(texte: str) -> str:
    return texte[texte.index("**Les demandes d'autorisation de tes workers.**"):texte.index("## 8.")]


def test_les_blocs_du_mode_autonome_du_gabarit_sont_generiques():
    bloc = _bloc_assistant((GABARIT / "assistant.md").read_text())
    sous = _sous_section_coordinateur((GABARIT / "coordinateur.md").read_text())
    for texte in (bloc, sous):
        assert not re.search(r"/(Users|home)/\w+", texte) and "Marie" not in texte
        assert "cime" not in texte, "le gabarit dit {{commande}}, jamais cime en dur"


@pytest.mark.parametrize("nom", ["assistant.md", "coordinateur.md"])
def test_mots_obligatoires_du_mode_autonome(nom):
    texte = (GABARIT / nom).read_text().lower()
    manquants = [m for m in MOTS_OBLIGATOIRES[nom] if m.lower() not in texte]
    assert manquants == [], f"{nom} ne dit plus : {manquants}"


def test_les_regles_precises_du_socle():
    assistant = (GABARIT / "assistant.md").read_text()
    assert "--phase" in assistant and "CHANGELOG" in assistant
    assert "ou mode autonome actif, voir plus bas" in assistant
    assert "Le mode autonome : son état, sa portée, son plafond et les chemins réservés" in assistant
    coord = (GABARIT / "coordinateur.md").read_text()
    assert "ne te trompes pas d'interlocuteur" in coord


def test_cime_init_ecrit_le_socle_sans_accolade(tmp_path, monkeypatch):
    from cime.fondation import init
    monkeypatch.setattr(init, "executable_cime", lambda: "/opt/outils/bin/cime")
    p = tmp_path / "neuf"
    assert init.executer(types.SimpleNamespace(dossier=str(p), utilisateur="Camille",
                                               nom_projet=None, prefixe=None)) == 0
    for nom in ("assistant.md", "coordinateur.md"):
        texte = (p / ".orga" / "socle" / nom).read_text()
        assert "{{" not in texte, nom
    assistant = (p / ".orga" / "socle" / "assistant.md").read_text()
    assert "Mode autonome (option de l'utilisateur)" in _bloc_assistant(assistant)
    assert "Camille" in _bloc_assistant(assistant) or "{{" not in _bloc_assistant(assistant)
    modele = _bloc_assistant((GABARIT / "assistant.md").read_text())
    assert _bloc_assistant(assistant) == modele.replace("{{commande}}", "cime").replace("{{utilisateur}}", "Camille")
    coord = (p / ".orga" / "socle" / "coordinateur.md").read_text()
    assert "Les demandes d'autorisation de tes workers" in _sous_section_coordinateur(coord)
    modele = _sous_section_coordinateur((GABARIT / "coordinateur.md").read_text())
    assert _sous_section_coordinateur(coord) == modele.replace("{{commande}}", "cime")
