"""La voie automatique : `cime lancer coord <é> --phase <p>` sans
accord de l'utilisateur, en mode autonome, sur annonce `chantier-auto:<é>:<p>` de l'Assistant. Registre
jetable ; le lancement est simulé (`faux_lancer`)."""
import json
import sqlite3

import pytest

from aide import cime, lignes
from cime.fondation import fusions_auto
from cime.fondation.projet import ErreurProjet
from cime.signaux import ordres
from test_ordres import facteur, faux_lancer, projet, tmux  # noqa: F401  (fixtures)

ANCIEN = "aucun accord de l'utilisateur non consommé pour chantier:x:p1"
CMD = ("lancer", "coord", "x", "--modele", "m", "--phase", "p1")


@pytest.fixture(autouse=True)
def mandat(projet):
    for equipe in ("x", "y"):
        (projet / ".orga/teams" / equipe / "mandate.md").write_text("# Mandat\nfaire le chantier\n")


def activer(monkeypatch, projet):
    assert cime(monkeypatch, "utilisateur", "fusions-auto", "active", projet=projet) == 0


def annoncer(monkeypatch, projet, capsys, equipe="x", phase="p1", suite=""):
    assert cime(monkeypatch, "assistant", "envoyer", "--a", "utilisateur", "--nature", "rapport_utilisateur",
                "--objet", f"chantier-auto:{equipe}:{phase}", f"{equipe} : phase {phase} lancée{suite}",
                projet=projet) == 0
    return int(capsys.readouterr().out.strip().splitlines()[-1])


def lancer(monkeypatch, projet, *cmd, agent="assistant"):
    return cime(monkeypatch, agent, *(cmd or CMD), projet=projet)


def refus(capsys):
    return capsys.readouterr().err


def ecrire_manifeste(projet, extra):
    chemin = projet / ".orga/projet.toml"
    chemin.write_text(chemin.read_text() + extra)


# --- la voie réussit -----------------------------------------------------------------------

def test_lancement_sur_annonce_consomme_l_annonce(projet, tmux, faux_lancer, facteur,  # noqa: F811
                                                  monkeypatch, capsys):
    activer(monkeypatch, projet)
    annonce = annoncer(monkeypatch, projet, capsys)
    assert lancer(monkeypatch, projet) == 0
    assert faux_lancer == [("coord", "x", None, "m")]
    [(ordre, brut)] = lignes(projet, "SELECT id, parametres FROM ordres")
    params = json.loads(brut)
    assert params["accord"] == annonce and params["voie"] == "auto"
    assert lignes(projet, "SELECT auteur, preuve FROM transitions WHERE message_id = ?"
                  " AND etat = 'clos'", (annonce,)) == [("cime", json.dumps({"par_ordre": ordre}))]


def test_l_annonce_ne_sert_qu_une_fois(projet, tmux, faux_lancer, facteur, monkeypatch, capsys):  # noqa: F811
    activer(monkeypatch, projet)
    annoncer(monkeypatch, projet, capsys)
    assert lancer(monkeypatch, projet) == 0
    assert lancer(monkeypatch, projet) == 2
    err = refus(capsys)
    assert f"{ANCIEN} {COMPLEMENT} 2 (annonce de l'Assistant)" in err
    assert len(faux_lancer) == 1


def test_la_plus_ancienne_annonce_est_prise(projet, tmux, faux_lancer, facteur, monkeypatch, capsys):  # noqa: F811
    activer(monkeypatch, projet)
    premiere = annoncer(monkeypatch, projet, capsys)
    seconde = annoncer(monkeypatch, projet, capsys, suite=" (bis)")
    assert lancer(monkeypatch, projet) == 0
    assert json.loads(lignes(projet, "SELECT parametres FROM ordres")[0][0])["accord"] == premiere
    assert lignes(projet, "SELECT count(*) FROM transitions WHERE message_id = ? AND etat = 'clos'",
                  (seconde,)) == [(0,)]
    assert lancer(monkeypatch, projet) == 0          # la seconde sert au lancement suivant
    assert json.loads(lignes(projet, "SELECT parametres FROM ordres")[1][0])["accord"] == seconde


@pytest.mark.parametrize("equipe,phase", [("x", "p2"), ("y", "p1")])
def test_annonce_d_une_autre_phase_ou_equipe_ne_sert_pas(projet, tmux, faux_lancer, facteur,  # noqa: F811
                                                         monkeypatch, capsys, equipe, phase):
    activer(monkeypatch, projet)
    annonce = annoncer(monkeypatch, projet, capsys, equipe, phase)
    assert lancer(monkeypatch, projet) == 2
    assert "condition 2 (annonce de l'Assistant)" in refus(capsys)
    assert faux_lancer == []
    assert lignes(projet, "SELECT count(*) FROM transitions WHERE message_id = ? AND etat = 'clos'",
                  (annonce,)) == [(0,)]


@pytest.mark.parametrize("de,a,nature", [("coord-x", "utilisateur", "rapport_utilisateur"),
                                         ("assistant", "coord-x", "rapport_utilisateur"),
                                         ("assistant", "utilisateur", "signalement")])
def test_seule_l_annonce_de_l_assistant_a_utilisateur_compte(projet, tmux, faux_lancer, facteur,  # noqa: F811
                                                        monkeypatch, capsys, de, a, nature):
    from cime.fondation.registre import ouvrir
    from cime.signaux import commandes
    activer(monkeypatch, projet)
    conn = ouvrir(projet)
    try:
        commandes.inscrire(conn, de=de, a=a, nature=nature, resume="faux", equipe="x",
                           objet="chantier-auto:x:p1")
    finally:
        conn.close()
    assert lancer(monkeypatch, projet) == 2
    assert "condition 2" in refus(capsys)


def test_accord_de_l_utilisateur_prioritaire_et_annonce_intacte(projet, tmux, faux_lancer, facteur,  # noqa: F811
                                                        monkeypatch, capsys):
    activer(monkeypatch, projet)
    annonce = annoncer(monkeypatch, projet, capsys)
    cime(monkeypatch, "assistant", "envoyer", "--a", "utilisateur", "--nature", "decision_utilisateur",
         "--objet", "chantier:x:p1", "ouvrir ?")
    d = int(capsys.readouterr().out.strip().splitlines()[-1])
    assert cime(monkeypatch, None, "accorder", str(d)) == 0
    capsys.readouterr()
    assert lancer(monkeypatch, projet) == 0
    params = json.loads(lignes(projet, "SELECT parametres FROM ordres")[0][0])
    assert params["accord"] != annonce and "voie" not in params
    assert lignes(projet, "SELECT count(*) FROM transitions WHERE message_id = ? AND etat = 'clos'",
                  (annonce,)) == [(0,)]


# --- mode inactif : le message est celui d'avant, mot pour mot ------------------------------

def test_mode_inactif_message_inchange(projet, tmux, faux_lancer, facteur, monkeypatch, capsys):  # noqa: F811
    annoncer(monkeypatch, projet, capsys)            # l'annonce existe, le mode non
    assert lancer(monkeypatch, projet) == 2
    assert refus(capsys).strip().endswith(ANCIEN) is True
    capsys.readouterr()
    assert lancer(monkeypatch, projet) == 2
    err = refus(capsys)
    assert "Mode autonome" not in err and "voie automatique" not in err
    assert faux_lancer == []


def test_mode_desactive_message_inchange(projet, tmux, faux_lancer, facteur, monkeypatch, capsys):  # noqa: F811
    activer(monkeypatch, projet)
    assert cime(monkeypatch, "utilisateur", "fusions-auto", "inactive", projet=projet) == 0
    annoncer(monkeypatch, projet, capsys)
    assert lancer(monkeypatch, projet) == 2
    assert "voie automatique" not in refus(capsys)


# --- les cinq conditions, une par une ------------------------------------------------------

COMPLEMENT = "L'option « Mode autonome » est active, mais la voie automatique est refusée : condition"


def test_condition_1_mode_suspendu(projet, tmux, faux_lancer, facteur, monkeypatch, capsys):  # noqa: F811
    activer(monkeypatch, projet)
    annoncer(monkeypatch, projet, capsys)
    ecrire_manifeste(projet, '\n[fusions_auto]\nreserves = ["src/neuf/"]\n')   # liste ≠ activation
    assert lancer(monkeypatch, projet) == 2
    err = refus(capsys)
    assert f"{ANCIEN} {COMPLEMENT} 1 (mode autonome actif)" in err
    assert faux_lancer == []


def test_condition_1_portee_insuffisante(projet, tmux, faux_lancer, facteur, monkeypatch, capsys):  # noqa: F811
    activer(monkeypatch, projet)
    annoncer(monkeypatch, projet, capsys)
    vrai = fusions_auto.etat_courant(projet)
    monkeypatch.setattr(fusions_auto, "etat_courant",
                        lambda p: dict(vrai, suspendue=False, portee=1))
    assert lancer(monkeypatch, projet) == 2
    assert f"{COMPLEMENT} 1 (mode autonome actif)" in refus(capsys)


def test_condition_2_sans_annonce(projet, tmux, faux_lancer, facteur, monkeypatch, capsys):  # noqa: F811
    activer(monkeypatch, projet)
    assert lancer(monkeypatch, projet) == 2
    err = refus(capsys)
    assert f"{ANCIEN} {COMPLEMENT} 2 (annonce de l'Assistant)" in err and "chantier-auto:x:p1" in err
    assert faux_lancer == []


def test_condition_3_mandat_absent(projet, tmux, faux_lancer, facteur, monkeypatch, capsys):  # noqa: F811
    activer(monkeypatch, projet)
    annoncer(monkeypatch, projet, capsys)
    (projet / ".orga/teams/x/mandate.md").unlink()
    assert lancer(monkeypatch, projet) == 2
    err = refus(capsys)
    assert f"{COMPLEMENT} 3 (mandat et dépendances) — .orga/teams/x/mandate.md absent" in err
    assert faux_lancer == []


@pytest.mark.parametrize("contenu", ["", "   \n\n\t\n"])
def test_condition_3_mandat_vide(projet, tmux, faux_lancer, facteur, monkeypatch, capsys, contenu):  # noqa: F811
    activer(monkeypatch, projet)
    annonce = annoncer(monkeypatch, projet, capsys)
    (projet / ".orga/teams/x/mandate.md").write_text(contenu)
    assert lancer(monkeypatch, projet) == 2
    err = refus(capsys)
    assert f"{COMPLEMENT} 3 (mandat et dépendances)" in err and "vide" in err
    assert lignes(projet, "SELECT count(*) FROM transitions WHERE message_id = ? AND etat = 'clos'",
                  (annonce,)) == [(0,)]


def test_condition_3_equipe_bloquee(projet, tmux, faux_lancer, facteur, monkeypatch, capsys):  # noqa: F811
    activer(monkeypatch, projet)
    annoncer(monkeypatch, projet, capsys)
    (projet / ".orga/dependencies.md").write_text(
        "# Dépendances\n\n## x\n\nStatut : BLOQUÉ — attend y\n\n## y\n\nStatut : actif\n")
    assert lancer(monkeypatch, projet) == 2
    err = refus(capsys)
    assert f"{COMPLEMENT} 3 (mandat et dépendances)" in err and "BLOQUÉ" in err
    assert faux_lancer == []


def test_condition_3_autre_equipe_bloquee_ne_gene_pas(projet, tmux, faux_lancer, facteur,  # noqa: F811
                                                      monkeypatch, capsys):
    activer(monkeypatch, projet)
    annoncer(monkeypatch, projet, capsys)
    (projet / ".orga/dependencies.md").write_text(
        "## x\n\nStatut : actif\n\n## y\n\nStatut : BLOQUÉ — attend x\n")
    assert lancer(monkeypatch, projet) == 0


def test_condition_4_plafond_atteint(projet, tmux, faux_lancer, facteur, monkeypatch, capsys):  # noqa: F811
    ecrire_manifeste(projet, "\n[fusions_auto]\nchantiers_par_jour = 1\n")
    activer(monkeypatch, projet)
    annoncer(monkeypatch, projet, capsys, "x", "p1")
    annoncer(monkeypatch, projet, capsys, "y", "p1")
    assert lancer(monkeypatch, projet) == 0
    assert lancer(monkeypatch, projet, "lancer", "coord", "y", "--modele", "m",
                  "--phase", "p1") == 2
    err = refus(capsys)
    assert f"{COMPLEMENT} 4 (plafond de lancements)" in err and "chantier:y:p1" in err
    assert len(faux_lancer) == 1


def test_condition_4_sous_le_plafond_passe(projet, tmux, faux_lancer, facteur, monkeypatch, capsys):  # noqa: F811
    ecrire_manifeste(projet, "\n[fusions_auto]\nchantiers_par_jour = 2\n")
    activer(monkeypatch, projet)
    annoncer(monkeypatch, projet, capsys, "x", "p1")
    annoncer(monkeypatch, projet, capsys, "y", "p1")
    assert lancer(monkeypatch, projet) == 0
    assert lancer(monkeypatch, projet, "lancer", "coord", "y", "--modele", "m",
                  "--phase", "p1") == 0
    annoncer(monkeypatch, projet, capsys, "x", "p2")
    assert lancer(monkeypatch, projet, "lancer", "coord", "x", "--modele", "m",
                  "--phase", "p2") == 2
    assert "condition 4" in refus(capsys)


def test_condition_4_plafond_zero_sans_limite(projet, tmux, faux_lancer, facteur, monkeypatch, capsys):  # noqa: F811
    ecrire_manifeste(projet, "\n[fusions_auto]\nchantiers_par_jour = 0\n")
    activer(monkeypatch, projet)
    for phase in ("p1", "p2", "p3"):
        annoncer(monkeypatch, projet, capsys, "x", phase)
        assert lancer(monkeypatch, projet, "lancer", "coord", "x", "--modele", "m",
                      "--phase", phase) == 0
    assert len(faux_lancer) == 3


# --- condition 5 : une erreur de lecture vaut refus, de la condition qui la subit -----------

def _lire_impossible(*_a, **_k):
    raise ErreurProjet("disque en feu")


def test_condition_5_lecture_du_mode(projet, tmux, faux_lancer, facteur, monkeypatch, capsys):  # noqa: F811
    activer(monkeypatch, projet)
    annoncer(monkeypatch, projet, capsys)
    monkeypatch.setattr(fusions_auto, "etat_courant", _lire_impossible)
    assert lancer(monkeypatch, projet) == 2
    err = refus(capsys)
    assert "condition 1 (mode autonome actif)" in err
    assert "lecture impossible (ErreurProjet : disque en feu)" in err
    assert faux_lancer == []


def test_condition_5_lecture_du_registre(projet, tmux, faux_lancer, facteur, monkeypatch, capsys):  # noqa: F811
    activer(monkeypatch, projet)
    annoncer(monkeypatch, projet, capsys)

    def casse(*_a, **_k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(ordres, "_annonces_libres", casse)
    assert lancer(monkeypatch, projet) == 2
    err = refus(capsys)
    assert "condition 2 (annonce de l'Assistant)" in err
    assert "lecture impossible (OperationalError : database is locked)" in err
    assert faux_lancer == []


def test_condition_5_lecture_des_dependances(projet, tmux, faux_lancer, facteur, monkeypatch, capsys):  # noqa: F811
    activer(monkeypatch, projet)
    annoncer(monkeypatch, projet, capsys)
    monkeypatch.setattr(ordres, "statut_equipe", _lire_impossible)
    assert lancer(monkeypatch, projet) == 2
    err = refus(capsys)
    assert "condition 3 (mandat et dépendances)" in err and "lecture impossible (ErreurProjet" in err
    assert faux_lancer == []


def test_condition_5_lecture_du_mandat(projet, tmux, faux_lancer, facteur, monkeypatch, capsys):  # noqa: F811
    activer(monkeypatch, projet)
    annoncer(monkeypatch, projet, capsys)
    (projet / ".orga/teams/x/mandate.md").write_bytes(b"\xff\xfe\x00 pas de l'utf-8 \xc3")
    assert lancer(monkeypatch, projet) == 2
    err = refus(capsys)
    assert "condition 3 (mandat et dépendances)" in err and "lecture impossible (UnicodeDecodeError" in err
    assert faux_lancer == []


def test_condition_5_lecture_du_plafond(projet, tmux, faux_lancer, facteur, monkeypatch, capsys):  # noqa: F811
    activer(monkeypatch, projet)
    annoncer(monkeypatch, projet, capsys)
    sain = fusions_auto.etat_courant(projet)
    monkeypatch.setattr(fusions_auto, "etat_courant", lambda p: sain)   # la condition 1 passe
    monkeypatch.setattr(fusions_auto, "plafond_chantiers", _lire_impossible)
    assert lancer(monkeypatch, projet) == 2
    err = refus(capsys)
    assert "condition 4 (plafond de lancements)" in err and "lecture impossible (ErreurProjet" in err
    assert faux_lancer == []


def test_condition_5_lecture_du_decompte(projet, tmux, faux_lancer, facteur, monkeypatch, capsys):  # noqa: F811
    activer(monkeypatch, projet)
    annoncer(monkeypatch, projet, capsys)
    monkeypatch.setattr(fusions_auto, "lancements_auto_24h_strict", _lire_impossible)
    assert lancer(monkeypatch, projet) == 2
    err = refus(capsys)
    assert "condition 4 (plafond de lancements)" in err and "lecture impossible" in err
    assert faux_lancer == []


def test_condition_5_plafond_zero_ne_lit_pas_le_decompte(projet, tmux, faux_lancer, facteur,  # noqa: F811
                                                         monkeypatch, capsys):
    ecrire_manifeste(projet, "\n[fusions_auto]\nchantiers_par_jour = 0\n")
    activer(monkeypatch, projet)
    annoncer(monkeypatch, projet, capsys)
    monkeypatch.setattr(fusions_auto, "lancements_auto_24h_strict", _lire_impossible)
    assert lancer(monkeypatch, projet) == 0


# --- inchangés -----------------------------------------------------------------------------

def test_reprendre_et_remplacer_sans_accord_ni_annonce(projet, tmux, faux_lancer, facteur,  # noqa: F811
                                                       monkeypatch, capsys):
    activer(monkeypatch, projet)
    annonce = annoncer(monkeypatch, projet, capsys)
    assert lancer(monkeypatch, projet, "lancer", "coord", "x", "--reprendre") == 0
    params = json.loads(lignes(projet, "SELECT parametres FROM ordres")[0][0])
    assert "accord" not in params and "voie" not in params
    assert lignes(projet, "SELECT count(*) FROM transitions WHERE message_id = ? AND etat = 'clos'",
                  (annonce,)) == [(0,)]


def test_reprendre_en_mode_inactif_sans_accord(projet, tmux, faux_lancer, facteur, monkeypatch):  # noqa: F811
    assert lancer(monkeypatch, projet, "lancer", "coord", "x", "--reprendre") == 0


def test_remplacer_sans_accord_ni_annonce(projet, tmux, faux_lancer, facteur, monkeypatch, capsys):  # noqa: F811
    monkeypatch.setattr(ordres, "_fermer_pour_remplacer", lambda projet_, p: None)
    activer(monkeypatch, projet)
    annonce = annoncer(monkeypatch, projet, capsys)
    assert lancer(monkeypatch, projet, "lancer", "coord", "x", "--reprendre", "--remplacer") == 0
    params = json.loads(lignes(projet, "SELECT parametres FROM ordres")[0][0])
    assert params["remplacer"] is True and "accord" not in params and "voie" not in params
    assert lignes(projet, "SELECT count(*) FROM transitions WHERE message_id = ? AND etat = 'clos'",
                  (annonce,)) == [(0,)]
    assert lancer(monkeypatch, projet, "lancer", "coord", "x", "--remplacer") == 2   # sans --reprendre


def test_phase_omise_refuse_toujours(projet, tmux, faux_lancer, facteur, monkeypatch, capsys):  # noqa: F811
    activer(monkeypatch, projet)
    annoncer(monkeypatch, projet, capsys)
    assert lancer(monkeypatch, projet, "lancer", "coord", "x", "--modele", "m") == 2
    assert "--phase obligatoire" in refus(capsys)
    assert faux_lancer == []


def test_un_coordinateur_ne_lance_pas_de_coordinateur(projet, tmux, faux_lancer, facteur,  # noqa: F811
                                                      monkeypatch, capsys):
    activer(monkeypatch, projet)
    annoncer(monkeypatch, projet, capsys)
    assert lancer(monkeypatch, projet, agent="coord-x") == 2
    assert "seul l'Assistant lance un coordinateur" in refus(capsys)
    assert faux_lancer == []


def test_un_worker_ne_passe_pas_par_la_voie_automatique(projet, tmux, faux_lancer, facteur,  # noqa: F811
                                                        monkeypatch, capsys):
    activer(monkeypatch, projet)
    annoncer(monkeypatch, projet, capsys)
    assert cime(monkeypatch, "coord-x", "lancer", "worker", "x", "t", "--modele",
                "claude-haiku-5-5", projet=projet) == 2
    err = refus(capsys)
    assert "aucun accord non consommé pour lancer-worker:x:t" in err and "voie automatique" not in err
    assert faux_lancer == []
