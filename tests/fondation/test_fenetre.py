"""`fenetre.lire` : reconnaître une fenêtre de choix de Claude Code d'après une capture de tmux."""
from pathlib import Path

import pytest

from cime.fondation import fenetre

ICI = Path(__file__).resolve().parent
INVITE = ICI / "fixtures" / "invite"
AUTORISATION = ICI.parent / "hote" / "fixtures" / "captures-autorisation"
RECONSTITUEES = ICI / "fixtures" / "fenetre"
REGLE = "─" * 80


def _capture(dossier, nom):
    return (dossier / nom).read_text(encoding="utf-8")


# --- les fenêtres réelles --------------------------------------------------------------------

@pytest.mark.parametrize("dossier,nom,genre,option", [
    (AUTORISATION, "1-demande-avant.ansi", "permission", "Yes"),
    (AUTORISATION, "5-demande3-avant.ansi", "permission", "No"),
    (INVITE, "demande-autorisation.ansi", "permission", "No"),
    (INVITE, "import-demande-approbation.ansi", "imports", "Yes, allow external imports"),
    (INVITE, "import-demarrage-sousdossier.ansi", "imports", "No, disable external imports"),
    (INVITE, "import-trust-sousdossier.ansi", "confiance", "Yes, I trust this folder"),
])
def test_fenetres_reelles_reconnues(dossier, nom, genre, option):
    f = fenetre.lire(_capture(dossier, nom))
    assert f["genre"] == genre
    assert option in f["options"]
    assert f["question"] and len(f["question"]) <= 300


def test_la_question_d_une_autorisation_commence_a_la_fenetre_pas_a_l_historique():
    f = fenetre.lire(_capture(AUTORISATION, "1-demande-avant.ansi"))
    assert f["question"].startswith("Bash command")
    assert "Lance exactement" not in f["question"]
    assert f["question"].endswith("Do you want to proceed?")
    assert f["options"] == ["Yes", "Yes, and always allow access to", "No"]


# --- les fenêtres reconstituées (non observées) -----------------------------------------------

def test_question_a_choix_reconstituee():
    f = fenetre.lire(_capture(RECONSTITUEES, "ask-user-question-reconstituee.txt"))
    assert f["genre"] == "choix"
    assert "Quelle bibliothèque de dates" in f["question"]
    assert f["options"] == ["Bibliothèque standard", "Bibliothèque tierce", "Type something.",
                            "Chat about this"]


def test_offre_du_mode_auto_reconstituee():
    f = fenetre.lire(_capture(RECONSTITUEES, "offre-mode-auto-reconstituee.txt"))
    assert f["genre"] == "offre-mode-auto"
    assert f["options"] == ["Yes", "Not now", "Don't show again"]
    assert f["question"].startswith("Auto mode works better when it knows your environment")


def test_offre_du_mode_auto_par_l_autre_formulation():
    capture = (f"{REGLE}\n Teach auto mode about your environment?\n\n ❯ 1. Yes\n   2. Not now\n\n"
               " Enter to confirm · Esc to cancel\n")
    assert fenetre.lire(capture)["genre"] == "offre-mode-auto"


# --- la structure, sans texte propre à un outil -----------------------------------------------

def test_fenetre_inconnue_reste_un_choix():
    capture = f"{REGLE}\n Une question que personne n'a prévue ?\n ❯ 1. A\n   2. B\n\n Esc to exit\n"
    assert fenetre.lire(capture) == {"genre": "choix", "question": "Une question que personne n'a prévue ?",
                                     "options": ["A", "B"]}


def test_le_curseur_peut_etre_sur_une_autre_option():
    capture = f"{REGLE}\n Choisis\n   1. A\n ❯ 2. B\n\n Enter to select · Esc to cancel\n"
    assert fenetre.lire(capture)["options"] == ["A", "B"]


def test_l_ansi_est_toleree():
    capture = _capture(AUTORISATION, "1-demande-avant.ansi")
    assert "\x1b[" in capture
    assert fenetre.lire(capture)["genre"] == "permission"


def test_la_question_est_tronquee_a_300_caracteres():
    capture = f"{REGLE}\n {'x' * 900}\n ❯ 1. A\n   2. B\n\n Esc to cancel\n"
    assert len(fenetre.lire(capture)["question"]) == 300


def test_une_liste_dans_l_historique_n_est_pas_la_fenetre():
    capture = (f"⏺ Voici le plan :\n  1. A\n  2. B\n\n{REGLE}\n Une vraie question ?\n"
               " ❯ 1. Oui\n   2. Non\n\n Esc to cancel\n")
    f = fenetre.lire(capture)
    assert f["options"] == ["Oui", "Non"]
    assert f["question"] == "Une vraie question ?"


# --- ce qui n'est jamais une fenêtre ----------------------------------------------------------

@pytest.mark.parametrize("nom", ["invite-vide.ansi", "invite-brouillon.ansi",
                                 "invite-brouillon-multiligne.ansi", "agent-au-travail.ansi",
                                 "placeholder-demarrage.ansi", "import-demarrage-racine.ansi"])
def test_pas_de_fenetre_sur_une_invite_ni_un_agent_au_travail(nom):
    assert fenetre.lire(_capture(INVITE, nom)) is None


@pytest.mark.parametrize("capture", ["", "\n\n", "   \n"])
def test_capture_vide(capture):
    assert fenetre.lire(capture) is None


def test_liste_numerotee_dans_une_reponse_sans_pied():
    capture = ("⏺ Trois choix possibles :\n  ❯ 1. A\n    2. B\n    3. C\n\n"
               f"{REGLE}\n❯\xa0\n{REGLE}\n")
    assert fenetre.lire(capture) is None


def test_liste_numerotee_sans_pied_de_fenetre():
    assert fenetre.lire(f"{REGLE}\n Question ?\n ❯ 1. A\n   2. B\n\n Enter to select\n") is None


def test_un_pied_perdu_haut_dans_l_ecran_ne_compte_pas():
    pied = " Esc to cancel\n"
    capture = f"{pied}{REGLE}\n Question ?\n ❯ 1. A\n   2. B\n" + "\n".join(f"ligne {i}" for i in range(8)) + "\n"
    assert fenetre.lire(capture) is None


def test_sans_curseur_ce_n_est_pas_une_fenetre():
    assert fenetre.lire(f"{REGLE}\n Question ?\n   1. A\n   2. B\n\n Esc to cancel\n") is None


def test_une_seule_option_ne_fait_pas_une_fenetre():
    assert fenetre.lire(f"{REGLE}\n Question ?\n ❯ 1. A\n\n Esc to cancel\n") is None


def test_la_zone_de_saisie_l_emporte_sur_tout_le_reste():
    """Une saisie de l'utilisateur dans l'invite n'est jamais une fenêtre, même si l'écran montre
    au-dessus une liste à curseur et un pied `Esc to cancel`."""
    capture = (f"{REGLE}\n Question ?\n ❯ 1. A\n   2. B\n\n Esc to cancel\n"
               f"{REGLE}\n❯\xa0mon brouillon\n{REGLE}\n")
    assert fenetre.lire(capture) is None


# --- toutes les captures réelles des menus et de l'observation ----------------------------------

MENUS = ICI.parent / "hote" / "fixtures" / "menus"
OBSERVATION = ICI.parent / "observation" / "fixtures" / "captures"
FENETRES_REELLES = [
    (MENUS, "bash.ansi", "permission", 3), (MENUS, "edit.ansi", "permission", 3),
    (MENUS, "write.ansi", "permission", 3), (MENUS, "read-hors-dossier.ansi", "permission", 3),
    (MENUS, "webfetch.ansi", "permission", 3), (MENUS, "negatif-model.ansi", "choix", 9),
    (OBSERVATION, "autorisation.ansi", "permission", 3),
    (OBSERVATION, "autorisation-en-attente.ansi", "permission", 3),
    (OBSERVATION, "demarrage-confiance-dossier.ansi", "confiance", 2),
    (OBSERVATION, "demarrage-imports-externes.ansi", "imports", 2),
]
SANS_FENETRE = [(d, f.name) for d in (MENUS, OBSERVATION) for f in sorted(d.glob("*.ansi"))
                if (d, f.name) not in {(a, b) for a, b, *_ in FENETRES_REELLES}]


@pytest.mark.parametrize("dossier,nom,genre,nombre", FENETRES_REELLES)
def test_captures_reelles_des_menus_et_de_l_observation(dossier, nom, genre, nombre):
    f = fenetre.lire(_capture(dossier, nom))
    assert f["genre"] == genre and len(f["options"]) == nombre
    assert f["question"]


@pytest.mark.parametrize("dossier,nom", SANS_FENETRE)
def test_captures_reelles_sans_fenetre(dossier, nom):
    assert fenetre.lire(_capture(dossier, nom)) is None


def test_les_captures_sans_fenetre_couvrent_apres_brouillons_coordinateurs_suggestions():
    noms = " ".join(n for _, n in SANS_FENETRE)
    for motif in ("-apres-", "brouillon", "cc-coord-", "suggestion"):
        assert motif in noms


def test_demande_de_fetch_dont_le_pied_est_la_derniere_option():
    f = fenetre.lire(_capture(MENUS, "webfetch.ansi"))
    assert f["genre"] == "permission"
    assert f["options"] == ["Yes", "Yes, and don't ask again for example.com",
                            "No, and tell Claude what to do differently (esc)"]
    assert f["question"] == ("Fetch Claude wants to fetch content from example.com url: "
                             "https://example.com/ prompt: What is the page title? "
                             "Do you want to allow Claude to fetch this content?")


def test_le_pied_esc_entre_parentheses_n_ouvre_pas_la_zone_de_saisie():
    capture = (f"{REGLE}\n Question ?\n ❯ 1. A\n   2. B (esc)\n{REGLE}\n❯\xa0\n{REGLE}\n")
    assert fenetre.lire(capture) is None
