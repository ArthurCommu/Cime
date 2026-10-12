import argparse
import io
import textwrap
from datetime import datetime, timedelta, timezone

import pytest

from cime.fondation import envoyer
from cime.fondation.nom import VAR_AGENT, VAR_PROJET
from cime.fondation.registre import NATURES, horodatage, inscrire_transition, ouvrir

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
    """`envoyer` n'écrit plus jamais dans un terminal : tout appel à tmux fait échouer le test."""
    etat = {"appels": []}

    def faux_tmux(*args):
        etat["appels"].append(args)
        raise AssertionError(f"tmux appelé par envoyer : {args}")

    monkeypatch.setattr(envoyer, "_tmux", faux_tmux)
    return etat


def _args(a="worker-x-y", nature="consigne", resume="fais ceci", fichier=None,
          attend="defaut", objet=None, corps=None, equipe=None):
    if attend == "defaut":
        attend = "rien" if nature == "consigne" else None
    return argparse.Namespace(a=a, nature=nature, resume=resume, fichier=fichier,
                              en_reponse_a=None, attend=attend, objet=objet, corps=corps,
                              equipe=equipe)


def _messages(projet):
    conn = ouvrir(projet)
    try:
        return conn.execute("SELECT id, de, a, nature, resume, fichier, equipe"
                            " FROM messages ORDER BY id").fetchall()
    finally:
        conn.close()


def test_n_ecrit_jamais_dans_tmux_et_inscrit_message_obligation_transition(projet, tmux, capsys):
    assert envoyer.executer(_args(attend="reponse")) == 0
    assert capsys.readouterr().out.strip() == "1"
    assert tmux["appels"] == []
    conn = ouvrir(projet)
    assert conn.execute("SELECT debiteur, attendu FROM obligations").fetchall() == [
        ("worker-x-y", "reponse")]
    assert conn.execute("SELECT etat, auteur FROM transitions").fetchall() == [
        ("inscrit", "coord-x")]


def test_destinataire_sans_session_inscrit_quand_meme(projet, tmux, capsys):
    assert envoyer.executer(_args()) == 0
    assert capsys.readouterr().out.strip() == "1"
    assert len(_messages(projet)) == 1


def test_facteur_arrete_signale_sur_stderr(projet, tmux, capsys):
    assert envoyer.executer(_args()) == 0
    assert "FACTEUR ARRÊTÉ" in capsys.readouterr().err
    conn = ouvrir(projet)
    conn.execute("INSERT INTO facteur (id, battement) VALUES (1, ?)", (horodatage(),))
    conn.commit()
    # un texte différent : un envoi identique serait refusé (doublon, doublons-livraison-envoi)
    assert envoyer.executer(_args(resume="fais ceci bis")) == 0
    assert "FACTEUR" not in capsys.readouterr().err


def test_nature_hors_liste(projet, tmux, capsys):
    assert envoyer.executer(_args(nature="blabla")) == 1
    err = capsys.readouterr().err
    assert all(n in err for n in NATURES)
    assert _messages(projet) == []


def test_agent_absent(projet, tmux, capsys, monkeypatch):
    monkeypatch.delenv(VAR_AGENT)
    monkeypatch.setenv("CLAUDECODE", "1")
    assert envoyer.executer(_args()) == 2
    assert "agent sans identité" in capsys.readouterr().err
    assert _messages(projet) == []


def test_identite_invalide(projet, tmux, capsys):
    assert envoyer.executer(_args(a="Pirate!")) == 1
    assert "identité invalide" in capsys.readouterr().err


def test_option_en_reponse_a_supprimee(projet, tmux, capsys):
    a = _args()
    a.en_reponse_a = 3
    assert envoyer.executer(a) == 2
    assert "cime repondre" in capsys.readouterr().err
    assert _messages(projet) == []


def test_corps_depuis_stdin_et_limite(projet, tmux, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("le message entier\nsur deux lignes"))
    assert envoyer.executer(_args(corps="-")) == 0
    conn = ouvrir(projet)
    assert conn.execute("SELECT corps FROM messages").fetchone() == ("le message entier\nsur deux lignes",)
    assert envoyer.executer(_args(corps="x" * 4001)) == 1
    assert len(_messages(projet)) == 1


def test_objet_enregistre(projet, tmux):
    assert envoyer.executer(_args(objet="tache:x:y")) == 0
    assert ouvrir(projet).execute("SELECT objet FROM messages").fetchone() == ("tache:x:y",)


def test_fichier_joint_chemin_relatif(projet, tmux, capsys):
    assert envoyer.executer(_args(fichier="note.md")) == 0
    assert _messages(projet)[0][5] == "note.md"
    assert _messages(projet)[0][5] == "note.md"


def test_fichier_relatif_resolu_depuis_le_dossier_de_l_appelant(projet, tmux, monkeypatch):
    equipe = projet / ".orga" / "teams" / "x"
    (equipe / "conversations").mkdir()
    (equipe / "conversations" / "x.md").write_text("d")
    monkeypatch.chdir(equipe)
    assert envoyer.executer(_args(fichier="conversations/x.md")) == 0
    assert _messages(projet)[0][5] == ".orga/teams/x/conversations/x.md"   # inscrit relatif à la racine


def test_fichier_relatif_a_la_racine_depuis_la_racine(projet, tmux):
    (projet / "sous").mkdir()
    (projet / "sous" / "doc.md").write_text("d")
    assert envoyer.executer(_args(fichier="sous/doc.md")) == 0
    assert _messages(projet)[0][5] == "sous/doc.md"


def test_fichier_relatif_n_est_plus_resolu_depuis_la_racine(projet, tmux, monkeypatch, capsys):
    """Ancien comportement abandonné : depuis un sous-dossier, un chemin racine-relatif n'existe pas."""
    equipe = projet / ".orga" / "teams" / "x"
    monkeypatch.chdir(equipe)
    assert envoyer.executer(_args(fichier="note.md")) == 1
    assert "fichier introuvable" in capsys.readouterr().err
    assert _messages(projet) == []


def test_fichier_remontant_hors_du_projet_refuse(projet, tmux, monkeypatch, capsys, tmp_path):
    (tmp_path / "hors-projet").write_text("x")
    assert envoyer.executer(_args(fichier="../hors-projet")) == 1
    assert "hors du projet" in capsys.readouterr().err
    assert _messages(projet) == []


def test_fichier_inexistant_refuse(projet, tmux, capsys):
    assert envoyer.executer(_args(fichier="nulle-part.md")) == 1
    assert "fichier introuvable" in capsys.readouterr().err


def test_fichier_absolu_sous_la_racine_accepte(projet, tmux):
    assert envoyer.executer(_args(fichier=str(projet / "note.md"))) == 0
    assert _messages(projet)[0][5] == "note.md"


def test_fichier_hors_du_projet_refuse(projet, tmux, capsys, tmp_path):
    dehors = tmp_path / "dehors.md"
    dehors.write_text("x")
    assert envoyer.executer(_args(fichier=str(dehors))) == 1
    assert "hors du projet" in capsys.readouterr().err
    assert _messages(projet) == []


def test_sans_variable_projet_refus(projet, tmux, capsys, monkeypatch):
    monkeypatch.delenv(VAR_PROJET)
    assert envoyer.executer(_args()) == 1
    assert f"{VAR_PROJET} absent" in capsys.readouterr().err
    assert _messages(projet) == []


def test_variable_vers_dossier_sans_manifeste_refus(projet, tmux, capsys, monkeypatch, tmp_path):
    vide = tmp_path / "vide"
    vide.mkdir()
    monkeypatch.setenv(VAR_PROJET, str(vide))
    assert envoyer.executer(_args()) == 1
    assert f"{VAR_PROJET} absent" in capsys.readouterr().err
    assert _messages(projet) == []


def test_dossier_courant_d_un_autre_projet_ignore(projet, tmux, monkeypatch, tmp_path):
    autre = tmp_path / "autre"
    (autre / ".orga").mkdir(parents=True)
    (autre / ".orga" / "projet.toml").write_text(MANIFESTE)
    monkeypatch.chdir(autre)
    assert envoyer.executer(_args()) == 0
    assert len(_messages(projet)) == 1
    assert not (autre / ".orga" / "etat").exists()


def test_fichier_inexistant(projet, tmux, capsys):
    assert envoyer.executer(_args(fichier="absent.md")) == 1
    assert "introuvable" in capsys.readouterr().err
    assert _messages(projet) == []


# --- option --equipe -------------------------------------------------------------

def _avec_equipe(equipe, **kw):
    a = _args(**kw)
    a.equipe = equipe
    return a


def _demande_cloture(projet):
    assert envoyer.executer(_args(a="assistant", nature="demande_cloture",
                                  resume="x est finie")) == 0
    return _messages(projet)[-1][0]


def test_equipe_par_defaut_celle_de_l_appelant(projet, tmux):
    assert envoyer.executer(_args(a="assistant", nature="question")) == 0
    assert _messages(projet)[-1][6] == "x"


def test_equipe_explicite(projet, tmux, monkeypatch):
    monkeypatch.setenv(VAR_AGENT, "assistant")
    (projet / ".orga" / "teams" / "z").mkdir()
    assert envoyer.executer(_avec_equipe("z", a="utilisateur", nature="rapport_utilisateur")) == 0
    assert _messages(projet)[-1][6] == "z"


def test_rapport_libre_meme_avec_une_demande_cloture_ouverte(projet, tmux, monkeypatch):
    """Correction 1 : plus de refus, plus de lien — l'obligation de la demande reste ouverte."""
    ident = _demande_cloture(projet)
    monkeypatch.setenv(VAR_AGENT, "assistant")
    assert envoyer.executer(_args(a="utilisateur", nature="rapport_utilisateur")) == 0
    conn = ouvrir(projet)
    assert conn.execute("SELECT etat FROM obligations WHERE message_id = ?",
                        (ident,)).fetchone() == ("ouverte",)
    assert conn.execute("SELECT en_reponse_a FROM messages ORDER BY id DESC LIMIT 1"
                        ).fetchone() == (None,)


@pytest.mark.parametrize("equipe", ["absente", "assistant"])
def test_equipe_inexistante_ou_speciale_refusee(projet, tmux, monkeypatch, equipe):
    monkeypatch.setenv(VAR_AGENT, "assistant")
    assert envoyer.executer(_avec_equipe(equipe, a="utilisateur", nature="rapport_utilisateur")) == 1
    assert _messages(projet) == []


def test_jamais_de_tmux_avec_equipe(projet, tmux):
    assert envoyer.executer(_avec_equipe("x", a="assistant", nature="demande_cloture")) == 0
    assert tmux["appels"] == []


# --- doublons : un envoi identique à un message encore vivant est refusé (doublons-livraison-envoi) ---

def _vieillir(projet, identifiant, minutes):
    """Recule l'horodatage d'un message (l'horloge réelle ne se règle pas dans ce test)."""
    recule = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    conn = ouvrir(projet)
    try:
        with conn:
            conn.execute("UPDATE messages SET horodatage = ? WHERE id = ?", (recule, identifiant))
    finally:
        conn.close()


def _cloturer(projet, identifiant, etat):
    conn = ouvrir(projet)
    try:
        inscrire_transition(conn, identifiant, etat, "coord-x", {})
    finally:
        conn.close()


def test_envoi_identique_a_la_suite_est_refuse(projet, tmux, capsys):
    assert envoyer.executer(_args(resume="même chose")) == 0
    premier = int(capsys.readouterr().out.strip())
    assert envoyer.executer(_args(resume="même chose")) == 1
    assert f"déjà envoyé : #{premier} (inscrit, il y a " in capsys.readouterr().err
    assert [m[0] for m in _messages(projet)] == [premier]


def test_texte_ou_destinataire_ou_nature_differents_sont_acceptes(projet, tmux, capsys):
    assert envoyer.executer(_args(resume="même chose")) == 0
    assert envoyer.executer(_args(resume="autre texte")) == 0
    assert envoyer.executer(_args(a="worker-x-z", resume="même chose")) == 0
    assert envoyer.executer(_args(a="assistant", nature="question", attend=None, resume="même chose")) == 0
    assert envoyer.executer(_args(a="assistant", nature="demande_accord", attend=None, resume="même chose")) == 0
    assert len(_messages(projet)) == 5


@pytest.mark.parametrize("etat", ["clos", "abandonne", "echec"])
def test_premier_termine_ne_bloque_pas_un_nouvel_envoi(projet, tmux, capsys, etat):
    assert envoyer.executer(_args(resume="même chose")) == 0
    premier = int(capsys.readouterr().out.strip())
    _cloturer(projet, premier, etat)
    assert envoyer.executer(_args(resume="même chose")) == 0
    assert len(_messages(projet)) == 2


def test_premier_de_plus_de_dix_minutes_ne_bloque_pas(projet, tmux, capsys):
    assert envoyer.executer(_args(resume="même chose")) == 0
    premier = int(capsys.readouterr().out.strip())
    _vieillir(projet, premier, minutes=11)
    assert envoyer.executer(_args(resume="même chose")) == 0
    assert len(_messages(projet)) == 2
