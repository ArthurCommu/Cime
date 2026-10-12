from pathlib import Path

import pytest

from cime.fondation import invite
from cime.fondation.invite import texte_invite

FIXTURES = Path(__file__).parent / "fixtures" / "invite"


def _lire(nom: str) -> str:
    return (FIXTURES / nom).read_text(encoding="utf-8")


# --- captures réelles (voir fixtures/invite) ---

@pytest.mark.parametrize("nom", [
    "invite-vide.ansi",
    "agent-au-travail.ansi",
    "placeholder-demarrage.ansi",
    "import-demarrage-racine.ansi",
    "suggestion-worker-t1-serveur.ansi",
    "suggestion-worker-t2-registre.ansi",
    "suggestion-worker-t3-tmux.ansi",
    "assistant-bordure-a-libelle-vide.ansi",          # la bordure porte « … review ─ »
    "assistant-bordure-a-libelle-suggestion.ansi",
])
def test_invite_vide_ou_suggestion_atténuée_donne_chaine_vide(nom):
    assert texte_invite(_lire(nom)) == ""


def test_brouillon_reel():
    assert texte_invite(_lire("invite-brouillon.ansi")) == "brouillon en cours"


def test_brouillon_multiligne_reel():
    assert texte_invite(_lire("invite-brouillon-multiligne.ansi")) == "ligne un\nligne deux"


@pytest.mark.parametrize("nom", [
    "demande-autorisation.ansi",
    "import-demande-approbation.ansi",
    "import-demarrage-sousdossier.ansi",
    "import-trust-sousdossier.ansi",
])
def test_ecran_sans_invite_donne_none(nom):
    assert texte_invite(_lire(nom)) is None


def test_capture_sans_rien():
    assert texte_invite("") is None
    assert texte_invite("$ ls\nfichier\n") is None


# --- cas SYNTHÉTIQUES : séquences de rétablissement (non capturées réellement) ---

REGLE = "\x1b[38;5;244m" + "─" * 40
PREFIXE = "\x1b[39m❯\xa0"


def _synthetique(contenu: str) -> str:
    return "\n".join(["sortie", REGLE, PREFIXE + contenu, REGLE, "  ⏸ manual mode on"])


@pytest.mark.parametrize("retablissement", ["\x1b[0m", "\x1b[22m", "\x1b[0;1m", "\x1b[m",
                                            "\x1b[1;22m"])
def test_synthetique_atténué_puis_texte_reel(retablissement):
    capture = _synthetique(f"\x1b[2msuggestion{retablissement}vrai")
    assert texte_invite(capture) == "vrai"


def test_synthetique_atténué_composite_avec_couleur():
    # `38;5;246` : le 5 et le 246 ne sont pas des paramètres SGR « 2 » ou « 22 »
    assert texte_invite(_synthetique("\x1b[38;5;246mtexte")) == "texte"
    assert texte_invite(_synthetique("\x1b[1;2mfantôme\x1b[22m")) == ""


def test_synthetique_atténué_non_ferme_jusqu_en_fin_de_ligne():
    assert texte_invite(_synthetique("\x1b[2msuggestion")) == ""


def test_synthetique_autres_sequences_retirees():
    assert texte_invite(_synthetique("\x1b[1mgras\x1b[0m et \x1b[4msouligné\x1b[24m")) \
        == "gras et souligné"


def test_synthetique_atténuation_reportee_sur_ligne_suivante():
    capture = "\n".join([REGLE, PREFIXE + "\x1b[2mdébut", "  suite\x1b[0m", REGLE])
    assert texte_invite(capture) == ""


# --- brouillon() / capturer() ---

def test_brouillon_utilise_capture_pane_avec_e(monkeypatch):
    appels = []

    class R:
        stdout = _lire("invite-brouillon.ansi")

    monkeypatch.setattr(invite.subprocess, "run",
                        lambda cmd, **k: appels.append(cmd) or R())
    assert invite.brouillon("essai-x") == "brouillon en cours"
    assert appels == [["tmux", "capture-pane", "-p", "-e", "-t", "essai-x"]]


# --- bordure à libellé (le facteur ne tapait jamais : l'invite était « inconnue ») ---

@pytest.mark.parametrize("ligne, attendu", [
    ("─" * 40, True),
    ("\x1b[38;5;244m" + "─" * 40 + "\x1b[39m", True),
    ("─" * 40 + " NOTES-DE-TRAVAIL.md review ─", True),
    ("\x1b[38;5;244m" + "─" * 40 + " a.b - c ─\x1b[39m", True),
    ("─" * 9, False),
    ("─" * 9 + " libellé ─", False),
    ("── texte ordinaire ──", False),
    ("─" * 40 + " texte sans fin", False),
    ("a " + "─" * 40, False),
])
def test_est_regle(ligne, attendu):
    assert invite._est_regle(ligne) is attendu


def test_bordure_a_libelle_est_une_zone_de_saisie():
    capture = "\n".join(["─" * 30 + " review.md ─", "❯\xa0bonjour", "─" * 30]) + "\n"
    assert texte_invite(capture) == "bonjour"


# --- texte replié par la TUI : un marqueur n'est jamais « vide » (défaut 1 de livraison) ---
# Fabriquées : aucune capture réelle du marqueur (attributs SGR compris) n'existe dans le dépôt.

def _ecran(ligne: str) -> str:
    regle = "─" * 40
    return f"{regle}\n❯\xa0{ligne}\n{regle}\n"


@pytest.mark.parametrize("marqueur", ["[Pasted text #1]", "[Pasted text #2 +12 lines]", "[Pasted text #3 +1 line]"])
def test_marqueur_de_repli_visible_ou_attenue_n_est_pas_vide(marqueur):
    assert texte_invite(_ecran(marqueur)) == marqueur
    assert texte_invite(_ecran(f"\x1b[2m{marqueur}\x1b[0m")) == marqueur


def test_marqueur_attenue_suivi_de_texte_visible_garde_les_deux():
    assert texte_invite(_ecran("\x1b[2m[Pasted text #1]\x1b[0mfin du texte")) == "[Pasted text #1]fin du texte"


def test_suggestion_attenuee_sans_marqueur_reste_vide():
    assert texte_invite(_ecran("\x1b[2mrelance le test\x1b[0m")) == ""


# --- mesures de la zone (diagnostic d'un échec de frappe) : des nombres, jamais du texte ---
# Synthétiques : le même écran que `_synthetique`, avec une règle de plus ou une ligne atténuée en tête.

def test_mesures_zone_sans_defaut_bordures_seules():
    capture = "\n".join(["sortie", REGLE, PREFIXE + "bonjour", REGLE, "  ⏸ manual mode on"])
    assert invite.mesures_invite(capture) == {
        "capture_lignes": 5, "regles": [1, 3], "zone_haut": 2, "zone_lignes": 1,
        "visible_par_ligne": [7], "attenue_perdu": 0, "attenue_ligne0": 0}


def test_mesures_premiere_ligne_attenuee_compte_ce_qui_est_ecarte():
    # cas 1 : le début de la saisie est atténué, il est écarté par texte_invite
    capture = _synthetique("\x1b[2mpremier\x1b[22m suite")
    assert texte_invite(capture) == " suite"
    mesures = invite.mesures_invite(capture)
    assert mesures["attenue_ligne0"] == 7 and mesures["attenue_perdu"] == 7
    assert mesures["visible_par_ligne"] == [5]


def test_mesures_haut_de_l_invite_au_bord_de_la_capture():
    # cas 2 : la bordure haute est la toute première ligne lue, la capture n'a pas plus de haut
    capture = "\n".join([REGLE, PREFIXE + "bonjour", REGLE, "  ⏸ manual mode on"])
    mesures = invite.mesures_invite(capture)
    assert mesures["regles"][0] == 0 and mesures["zone_haut"] == 1
    assert mesures["capture_lignes"] == 4


def test_mesures_regle_intermediaire_dans_la_zone():
    # cas 3 : une ligne de règle au milieu de la saisie est prise pour la bordure haute
    capture = "\n".join([REGLE, PREFIXE + "une phrase", REGLE, "  suite de la phrase", REGLE])
    mesures = invite.mesures_invite(capture)
    assert mesures["regles"] == [0, 2, 4]
    assert mesures["zone_haut"] == 1 and mesures["zone_lignes"] == 1


def test_mesures_sans_zone_donne_none():
    assert invite.mesures_invite("rien du tout\n") is None
    assert invite.mesures_invite("") is None


def test_mesures_ne_contiennent_que_des_nombres():
    capture = _synthetique("\x1b[2msecret\x1b[22m texte-secret")
    valeurs = invite.mesures_invite(capture).values()
    assert all(isinstance(v, int) or (isinstance(v, list) and all(isinstance(n, int) for n in v))
               for v in valeurs)
    assert "secret" not in repr(invite.mesures_invite(capture))
