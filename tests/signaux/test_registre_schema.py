import sqlite3

import pytest

from cime.fondation import registre

ANCIEN = """
CREATE TABLE messages (
  id INTEGER PRIMARY KEY, horodatage TEXT NOT NULL, de TEXT NOT NULL, a TEXT NOT NULL,
  nature TEXT NOT NULL, resume TEXT NOT NULL, fichier TEXT, en_reponse_a INTEGER,
  equipe TEXT);
"""


def _colonnes(conn):
    return [r[1] for r in conn.execute("PRAGMA table_info(messages)")]


def _tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_base_neuve(tmp_path):
    conn = registre.ouvrir(tmp_path)
    assert {"objet", "corps"} <= set(_colonnes(conn))
    assert {"courriers", "transitions", "obligations", "ordres", "facteur"} <= _tables(conn)
    noms = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"courrier_ouvert", "transitions_message", "obligations_debiteur"} <= noms


def test_ancienne_base_migree_deux_fois(tmp_path):
    chemin = registre.chemin_registre(tmp_path)
    chemin.parent.mkdir(parents=True)
    ancien = sqlite3.connect(chemin)
    ancien.executescript(ANCIEN)
    ancien.execute("INSERT INTO messages (horodatage,de,a,nature,resume) VALUES ('t','assistant','utilisateur','consigne','x')")
    ancien.commit()
    ancien.close()
    for _ in range(2):
        conn = registre.ouvrir(tmp_path)
        assert {"objet", "corps"} <= set(_colonnes(conn))
        assert conn.execute("SELECT resume, objet FROM messages").fetchall() == [("x", None)]
        conn.close()


def test_deux_courriers_ouverts_pour_le_meme_destinataire(tmp_path):
    conn = registre.ouvrir(tmp_path)
    req = "INSERT INTO courriers (a, voie, cree, expire, etat) VALUES (?, 'tmux', 't', 't', ?)"
    conn.execute(req, ("assistant", "ouvert"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(req, ("assistant", "ouvert"))
    conn.execute(req, ("assistant", "acquitte"))
    conn.execute(req, ("coord-x", "ouvert"))


def test_message_objet_corps_et_limite(tmp_path):
    conn = registre.ouvrir(tmp_path)
    i = registre.inscrire_message(conn, de="assistant", a="utilisateur", nature="accord",
                                  resume="r", objet="o", corps="c")
    assert conn.execute("SELECT objet, corps FROM messages WHERE id=?", (i,)).fetchone() == ("o", "c")
    with pytest.raises(ValueError):
        registre.inscrire_message(conn, de="assistant", a="utilisateur", nature="accord",
                                  resume="r", corps="x" * 4001)


def test_transitions(tmp_path):
    conn = registre.ouvrir(tmp_path)
    i = registre.inscrire_message(conn, de="assistant", a="utilisateur", nature="consigne", resume="r")
    assert registre.etat_message(conn, i) is None
    registre.inscrire_transition(conn, i, "inscrit", "assistant", {"cmd": "envoyer"})
    registre.inscrire_transition(conn, i, "clos", "cime", {"x": 1})
    assert registre.etat_message(conn, i) == "clos"
