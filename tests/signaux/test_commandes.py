import json

import pytest

from aide import cime, fabriquer_projet, lignes
from cime.signaux import matrice
from cime.signaux.identite import ErreurIdentite, appelant


@pytest.fixture
def projet(tmp_path, monkeypatch):
    racine = fabriquer_projet(tmp_path / "depot")
    monkeypatch.setenv("CIME_PROJET", str(racine))
    monkeypatch.delenv("CLAUDECODE", raising=False)
    return racine


def envoyer(monkeypatch, projet, de, a, nature, *extra, resume="r"):
    return cime(monkeypatch, de, "envoyer", "--a", a, "--nature", nature, *extra, resume,
                projet=projet)


def dernier_id(capsys):
    return int(capsys.readouterr().out.strip().splitlines()[-1])


# --- identité ---------------------------------------------------------------------------

def test_appelant():
    assert appelant({"CIME_AGENT": "coord-x", "CLAUDECODE": "1"}) == "coord-x"
    assert appelant({"CIME_AGENT": "cime"}) == "cime"
    assert appelant({}) == "utilisateur"
    with pytest.raises(ErreurIdentite, match="agent sans identité"):
        appelant({"CLAUDECODE": "1"})
    with pytest.raises(ErreurIdentite):
        appelant({"CIME_AGENT": "Pirate!"})


# --- matrice : chaque nature, un couple permis et un refusé ---------------------------------

PERMIS = [
    ("assistant", "coord-x", "consigne"), ("coord-x", "worker-x-t", "consigne"),
    ("cime", "worker-x-t", "consigne"), ("cime", "assistant", "consigne"),
    ("utilisateur", "assistant", "consigne"),
    ("worker-x-t", "coord-x", "question"), ("coord-x", "assistant", "question"),
    ("worker-x-t", "coord-x", "compte_rendu"), ("coord-x", "assistant", "compte_rendu"),
    ("utilisateur", "assistant", "compte_rendu"),
    ("worker-x-t", "coord-x", "travail_pret"), ("coord-x", "assistant", "travail_pret"),
    ("coord-x", "assistant", "demande_accord"),
    ("coord-x", "assistant", "demande_cloture"),
    ("cime", "coord-x", "signalement"), ("cime", "utilisateur", "relance"),
    ("assistant", "utilisateur", "decision_utilisateur"), ("assistant", "utilisateur", "donnee_utilisateur"),
    ("assistant", "utilisateur", "rapport_utilisateur"),
]
REFUSES = [
    ("coord-x", "assistant", "consigne"), ("coord-y", "worker-x-t", "consigne"),
    ("worker-x-t", "worker-x-u", "consigne"), ("assistant", "worker-x-t", "consigne"),
    ("assistant", "coord-x", "question"), ("worker-x-t", "assistant", "question"),
    ("assistant", "coord-x", "compte_rendu"), ("worker-x-t", "assistant", "compte_rendu"),
    ("assistant", "coord-x", "travail_pret"), ("worker-x-t", "assistant", "travail_pret"),
    ("worker-x-t", "assistant", "demande_accord"), ("assistant", "coord-x", "demande_accord"),
    ("worker-x-t", "assistant", "demande_cloture"),
    ("assistant", "coord-x", "signalement"), ("worker-x-t", "coord-x", "relance"),
    ("coord-x", "utilisateur", "decision_utilisateur"), ("utilisateur", "assistant", "rapport_utilisateur"),
    ("coord-x", "utilisateur", "donnee_utilisateur"),
    ("assistant", "coord-x", "reponse"), ("assistant", "coord-x", "accord"),
    ("assistant", "coord-x", "refus"),
]


@pytest.mark.parametrize("de,a,nature", PERMIS)
def test_matrice_permis(projet, de, a, nature):
    assert matrice.verifier(de, a, nature, projet) is None


@pytest.mark.parametrize("de,a,nature", REFUSES)
def test_matrice_refuse(projet, de, a, nature):
    assert matrice.verifier(de, a, nature, projet)


def test_toutes_les_natures_du_registre_sont_dans_la_matrice():
    from cime.fondation.registre import NATURES
    assert set(NATURES) == set(matrice.MATRICE)


def test_envoyer_refuse_hors_matrice_code_2(projet, monkeypatch, capsys):
    assert envoyer(monkeypatch, projet, "worker-x-t", "assistant", "consigne",
                   "--attend", "rien") == 2
    assert "hors matrice" in capsys.readouterr().err
    assert lignes(projet, "SELECT count(*) FROM messages") == [(0,)]


def test_envoyer_refuse_une_identite_agent_sans_nom(projet, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDECODE", "1")
    assert envoyer(monkeypatch, projet, None, "assistant", "compte_rendu") == 2
    assert "agent sans identité" in capsys.readouterr().err


def test_consigne_sans_attend_refusee(projet, monkeypatch, capsys):
    assert envoyer(monkeypatch, projet, "coord-x", "worker-x-t", "consigne") == 2
    assert "--attend" in capsys.readouterr().err
    assert envoyer(monkeypatch, projet, "coord-x", "worker-x-t", "consigne",
                   "--attend", "peut-etre") == 2


def test_attend_refuse_hors_consigne(projet, monkeypatch):
    assert envoyer(monkeypatch, projet, "coord-x", "assistant", "question",
                   "--attend", "rien") == 2


@pytest.mark.parametrize("attend,attendu", [("accuse", "accuse"),
                                            ("travail_pret", "travail_pret"),
                                            ("reponse", "reponse")])
def test_consigne_ouvre_l_obligation_du_destinataire(projet, monkeypatch, capsys, attend, attendu):
    assert envoyer(monkeypatch, projet, "coord-x", "worker-x-t", "consigne",
                   "--attend", attend) == 0
    assert lignes(projet, "SELECT debiteur, attendu FROM obligations") == [
        ("worker-x-t", attendu)]


def test_consigne_rien_sans_obligation(projet, monkeypatch):
    assert envoyer(monkeypatch, projet, "coord-x", "worker-x-t", "consigne",
                   "--attend", "rien") == 0
    assert lignes(projet, "SELECT count(*) FROM obligations") == [(0,)]


@pytest.mark.parametrize("nature", ["reponse", "accord", "refus"])
def test_reponse_accord_refus_via_envoyer_refuses(projet, monkeypatch, capsys, nature):
    assert envoyer(monkeypatch, projet, "assistant", "coord-x", nature) == 2
    assert "cime " in capsys.readouterr().err


def test_question_echeance_15_minutes(projet, monkeypatch):
    envoyer(monkeypatch, projet, "worker-x-t", "coord-x", "question")
    (h, e), = lignes(projet, "SELECT m.horodatage, o.echeance FROM obligations o"
                             " JOIN messages m ON m.id = o.message_id")
    from cime.signaux.echeances import _lire
    assert (_lire(e) - _lire(h)).total_seconds() == 15 * 60


# --- repondre ------------------------------------------------------------------------------

def _question(monkeypatch, projet, capsys):
    envoyer(monkeypatch, projet, "worker-x-t", "coord-x", "question", resume="Q ?")
    return dernier_id(capsys)


def test_repondre_ferme_l_obligation_et_clot_le_message(projet, monkeypatch, capsys):
    q = _question(monkeypatch, projet, capsys)
    assert cime(monkeypatch, "coord-x", "repondre", str(q), "oui") == 0
    r = dernier_id(capsys)
    assert lignes(projet, "SELECT de, a, nature, en_reponse_a FROM messages WHERE id = ?",
                  (r,)) == [("coord-x", "worker-x-t", "reponse", q)]
    assert lignes(projet, "SELECT etat, ferme_par FROM obligations WHERE message_id = ?",
                  (q,)) == [("satisfaite", r)]
    assert lignes(projet, "SELECT etat, preuve FROM transitions WHERE message_id = ?"
                  " ORDER BY id", (q,))[-1] == ("clos", json.dumps({"par_message": r}))


def test_repondre_deux_fois_refuse(projet, monkeypatch, capsys):
    q = _question(monkeypatch, projet, capsys)
    assert cime(monkeypatch, "coord-x", "repondre", str(q), "oui") == 0
    assert cime(monkeypatch, "coord-x", "repondre", str(q), "encore") == 2
    assert "déjà satisfaite" in capsys.readouterr().err
    assert lignes(projet, "SELECT count(*) FROM messages") == [(2,)]


def test_repondre_par_un_tiers_refuse(projet, monkeypatch, capsys):
    q = _question(monkeypatch, projet, capsys)
    for tiers in ("coord-y", "assistant", "worker-x-t"):
        assert cime(monkeypatch, tiers, "repondre", str(q), "moi") == 2
    assert lignes(projet, "SELECT count(*) FROM messages") == [(1,)]


def test_repondre_message_inconnu(projet, monkeypatch):
    assert cime(monkeypatch, "coord-x", "repondre", "99", "x", projet=projet) == 2


def test_repondre_question_en_retour_ouvre_une_autre_obligation(projet, monkeypatch, capsys):
    envoyer(monkeypatch, projet, "assistant", "coord-x", "consigne", "--attend", "reponse")
    c = dernier_id(capsys)
    assert cime(monkeypatch, "coord-x", "repondre", str(c), "--nature", "question",
                "lequel ?") == 0
    q = dernier_id(capsys)
    assert lignes(projet, "SELECT debiteur, attendu, etat FROM obligations ORDER BY id") == [
        ("coord-x", "reponse", "satisfaite"), ("assistant", "reponse", "ouverte")]
    assert q == c + 1


def test_repondre_nature_non_permise(projet, monkeypatch, capsys):
    q = _question(monkeypatch, projet, capsys)
    assert cime(monkeypatch, "coord-x", "repondre", str(q), "--nature", "accord", "x") == 2


def test_compte_rendu_repousse_sans_fermer(projet, monkeypatch, capsys):
    envoyer(monkeypatch, projet, "worker-x-t", "coord-x", "travail_pret")
    t = dernier_id(capsys)
    # compte_rendu → supérieur seulement : le coordinateur ne peut pas en renvoyer au worker
    assert cime(monkeypatch, "coord-x", "repondre", str(t), "--nature", "compte_rendu",
                "en revue") == 2
    envoyer(monkeypatch, projet, "coord-x", "worker-x-t", "consigne", "--attend", "travail_pret")
    c = dernier_id(capsys)
    assert cime(monkeypatch, "worker-x-t", "repondre", str(c), "--nature", "compte_rendu",
                "en cours") == 0
    assert lignes(projet, "SELECT etat FROM obligations WHERE message_id = ?", (c,)) == [
        ("ouverte",)]
    assert lignes(projet, "SELECT count(*) FROM transitions WHERE message_id = ?"
                  " AND etat = 'clos'", (c,)) == [(0,)]


def test_repondre_fichier_relatif_depuis_le_dossier_de_l_appelant(projet, monkeypatch, capsys):
    q = _question(monkeypatch, projet, capsys)
    sous = projet / ".orga" / "teams" / "x"
    sous.mkdir(parents=True, exist_ok=True)
    (sous / "r.md").write_text("r")
    monkeypatch.chdir(sous)
    assert cime(monkeypatch, "coord-x", "repondre", str(q), "--fichier", "r.md", "x") == 0
    assert lignes(projet, "SELECT fichier FROM messages WHERE en_reponse_a = ?", (q,)
                  ) == [(".orga/teams/x/r.md",)]


def test_repondre_fichier_inexistant(projet, monkeypatch, capsys):
    monkeypatch.chdir(projet)
    q = _question(monkeypatch, projet, capsys)
    assert cime(monkeypatch, "coord-x", "repondre", str(q), "--fichier", "absent.md", "x") == 1
    assert cime(monkeypatch, "coord-x", "repondre", str(q), "--fichier", "note.md", "x") == 0


# --- accorder / refuser --------------------------------------------------------------------

def _demande(monkeypatch, projet, capsys, objet):
    envoyer(monkeypatch, projet, "coord-x", "assistant", "demande_accord", "--objet", objet)
    return dernier_id(capsys)


def test_accorder_lancer_worker_exige_le_modele(projet, monkeypatch, capsys):
    d = _demande(monkeypatch, projet, capsys, "lancer-worker:x:t")
    assert cime(monkeypatch, "assistant", "accorder", str(d)) == 2
    assert "--modele" in capsys.readouterr().err
    assert cime(monkeypatch, "assistant", "accorder", str(d), "--modele", "claude-haiku-5-5",
                "--parallele") == 0
    a = dernier_id(capsys)
    assert lignes(projet, "SELECT de, a, nature, objet, corps, en_reponse_a FROM messages"
                  " WHERE id = ?", (a,)) == [
        ("assistant", "coord-x", "accord", "lancer-worker:x:t",
         json.dumps({"modele": "claude-haiku-5-5", "parallele": True}), d)]
    assert lignes(projet, "SELECT etat FROM obligations WHERE message_id = ?", (d,)) == [
        ("satisfaite",)]
    assert cime(monkeypatch, "assistant", "accorder", str(d), "--modele", "m") == 2


def test_accorder_par_un_autre_que_le_destinataire(projet, monkeypatch, capsys):
    d = _demande(monkeypatch, projet, capsys, "fusion:x:abc")
    assert cime(monkeypatch, "coord-x", "accorder", str(d)) == 2
    assert cime(monkeypatch, "assistant", "accorder", str(d)) == 0


def test_refuser(projet, monkeypatch, capsys):
    d = _demande(monkeypatch, projet, capsys, "lancer-worker:x:t")
    assert cime(monkeypatch, "assistant", "refuser", str(d), "pas maintenant") == 0
    r = dernier_id(capsys)
    assert lignes(projet, "SELECT nature, resume, a FROM messages WHERE id = ?", (r,)) == [
        ("refus", "pas maintenant", "coord-x")]


def test_accord_de_l_utilisateur_chantier_et_fusion(projet, monkeypatch, capsys):
    for objet in ("chantier:x:2", "fusion:x:abc123"):
        envoyer(monkeypatch, projet, "assistant", "utilisateur", "decision_utilisateur",
                "--objet", objet)
        d = dernier_id(capsys)
        assert cime(monkeypatch, "assistant", "accorder", str(d)) == 2  # pas son accord
        assert cime(monkeypatch, None, "accorder", str(d)) == 0
        a = dernier_id(capsys)
        assert lignes(projet, "SELECT de, a, nature, objet FROM messages WHERE id = ?", (a,)) \
            == [("utilisateur", "assistant", "accord", objet)]


LIBRE = '{"outil": "Bash", "cible": "ls", "classe": "libre", "theme": "projet"}'


def _signalement_autorisation(monkeypatch, projet, capsys, a="assistant", objet="autorisation:7",
                              corps=LIBRE):
    """Le signalement que le hook écrit (classe dans le `corps`). Par défaut
    une demande `libre` d'un coordinateur, adressée à l'Assistant : le cas d'avant les classes."""
    from cime.fondation.registre import ouvrir
    from cime.signaux.commandes import inscrire
    conn = ouvrir(projet)
    try:
        return inscrire(conn, de="cime", a=a, nature="signalement", resume="demande d'autorisation",
                        objet=objet, corps=corps)
    finally:
        conn.close()


def test_accorder_une_autorisation_inscrit_seulement_l_accord(projet, monkeypatch, capsys):
    s = _signalement_autorisation(monkeypatch, projet, capsys)
    assert cime(monkeypatch, "assistant", "accorder", str(s)) == 0
    a = dernier_id(capsys)
    assert lignes(projet, "SELECT de, a, nature, objet, en_reponse_a FROM messages WHERE id = ?",
                  (a,)) == [("assistant", "cime", "accord", "autorisation:7", s)]
    assert lignes(projet, "SELECT etat FROM obligations WHERE message_id = ?", (s,)) == [("satisfaite",)]
    assert lignes(projet, "SELECT etat, auteur FROM transitions WHERE message_id = ? ORDER BY id", (a,)) == [
        ("inscrit", "assistant")]            # l'hôte seul le prendra en charge
    assert lignes(projet, "SELECT etat FROM transitions WHERE message_id = ? ORDER BY id", (s,))[-1] == ("clos",)


def test_refuser_un_signalement_a_utilisateur_est_refuse_il_n_attend_rien(projet, monkeypatch, capsys):
    """Un signalement adressé à l'utilisateur n'ouvre aucune obligation : rien à
    refuser, et le refus n'écrit aucune ligne. (Remplace le cas où l'utilisateur refusait ce même signalement.)"""
    s = _signalement_autorisation(monkeypatch, projet, capsys, a="utilisateur")
    assert lignes(projet, "SELECT count(*) FROM obligations WHERE message_id = ?", (s,)) == [(0,)]
    assert cime(monkeypatch, None, "refuser", str(s), "trop large") == 2
    assert lignes(projet, "SELECT count(*) FROM messages WHERE nature = 'refus'") == [(0,)]


def test_accorder_une_autorisation_sans_classe_est_reservee_a_utilisateur(projet, monkeypatch, capsys):
    """Sans `corps` lisible, la demande est `reserve` — l'Assistant, qui
    l'accordait avant les classes, est refusé ; l'utilisateur passe."""
    s = _signalement_autorisation(monkeypatch, projet, capsys, corps=None)
    assert cime(monkeypatch, "assistant", "accorder", str(s)) == 2
    assert "réservé à l'utilisateur" in capsys.readouterr().err
    assert cime(monkeypatch, "utilisateur", "accorder", str(s)) == 0
    assert lignes(projet, "SELECT de FROM messages WHERE nature = 'accord'") == [("utilisateur",)]


def test_accorder_une_autorisation_deux_fois_ou_par_un_tiers_refuse(projet, monkeypatch, capsys):
    s = _signalement_autorisation(monkeypatch, projet, capsys)
    assert cime(monkeypatch, "coord-x", "accorder", str(s)) == 2       # pas son signalement
    assert cime(monkeypatch, "assistant", "accorder", str(s)) == 0
    capsys.readouterr()
    assert cime(monkeypatch, "assistant", "accorder", str(s)) == 2     # déjà accordé : pas de seconde touche
    assert "déjà satisfaite" in capsys.readouterr().err
    assert lignes(projet, "SELECT count(*) FROM messages WHERE nature = 'accord'") == [(1,)]


def test_accorder_un_message_qui_n_est_pas_une_demande(projet, monkeypatch, capsys):
    q = _question(monkeypatch, projet, capsys)
    assert cime(monkeypatch, "coord-x", "accorder", str(q)) == 2


def test_utilisateur_repond_a_une_decision_comme_l_hote(projet, monkeypatch, capsys):
    envoyer(monkeypatch, projet, "assistant", "utilisateur", "decision_utilisateur", resume="on y va ?")
    d = dernier_id(capsys)
    monkeypatch.chdir(projet)
    assert cime(monkeypatch, "utilisateur", "repondre", str(d), "--fichier", "note.md",
                "L'utilisateur a tranché : oui") == 0
    r = dernier_id(capsys)
    assert lignes(projet, "SELECT de, a, nature, en_reponse_a, fichier FROM messages"
                  " WHERE id = ?", (r,)) == [("utilisateur", "assistant", "reponse", d, "note.md")]
    assert lignes(projet, "SELECT etat FROM obligations WHERE message_id = ?", (d,)) == [
        ("satisfaite",)]


def test_utilisateur_previent_l_assistant_par_un_compte_rendu(projet, monkeypatch):
    assert envoyer(monkeypatch, projet, "utilisateur", "assistant", "compte_rendu") == 0


# --- rapport_utilisateur en réponse à une demande_cloture (correction 1 de l'Assistant) -----------

def test_repondre_rapport_utilisateur_va_a_utilisateur_et_ferme_la_demande(projet, monkeypatch, capsys):
    envoyer(monkeypatch, projet, "coord-x", "assistant", "demande_cloture", resume="x finie")
    demande = dernier_id(capsys)
    assert cime(monkeypatch, "assistant", "repondre", str(demande), "--nature",
                "rapport_utilisateur", "rapport") == 0
    rapport = dernier_id(capsys)
    assert lignes(projet, "SELECT de, a, nature, en_reponse_a, equipe FROM messages WHERE id=?",
                  (rapport,)) == [("assistant", "utilisateur", "rapport_utilisateur", demande, "x")]
    assert lignes(projet, "SELECT etat, ferme_par FROM obligations WHERE message_id=?",
                  (demande,)) == [("satisfaite", rapport)]
    assert lignes(projet, "SELECT debiteur, attendu, etat FROM obligations WHERE message_id=?",
                  (rapport,)) == [("utilisateur", "lu", "ouverte")]


def test_repondre_rapport_utilisateur_exige_une_demande_cloture(projet, monkeypatch, capsys):
    envoyer(monkeypatch, projet, "coord-x", "assistant", "question")
    q = dernier_id(capsys)
    assert cime(monkeypatch, "assistant", "repondre", str(q), "--nature", "rapport_utilisateur",
                "r") == 2
    assert "demande_cloture" in capsys.readouterr().err
