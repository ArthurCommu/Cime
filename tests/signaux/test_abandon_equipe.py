"""`obligations.abandonner_equipe` : seule, dans une transaction que l'appelant valide."""
from aide import exiger_jetable  # noqa: F401  (même racine de tests que les autres)

from cime.fondation.registre import ouvrir, inscrire_message, inscrire_transition
from cime.signaux import obligations


def _message(conn, de, a, debiteur):
    m = inscrire_message(conn, de=de, a=a, nature="question", resume="q", commit=False)
    inscrire_transition(conn, m, "inscrit", de, {}, commit=False)
    obligations.ouvrir_obligation(conn, m, debiteur, "reponse", commit=False)
    return m


def test_abandonne_les_obligations_de_l_equipe_seulement(tmp_path):
    racine = tmp_path / "p"
    racine.mkdir()
    conn = ouvrir(racine)
    q_coord = _message(conn, "assistant", "coord-alpha", "coord-alpha")
    q_worker = _message(conn, "coord-alpha", "worker-alpha-t1", "worker-alpha-t1")
    q_autre = _message(conn, "assistant", "coord-beta", "coord-beta")
    q_bis = _message(conn, "coord-alpha-bis", "worker-alpha-bis-t1", "worker-alpha-bis-t1")
    q_assistant = _message(conn, "coord-alpha", "assistant", "assistant")
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    fait = obligations.abandonner_equipe(conn, "alpha", "utilisateur", 42, autres=("alpha-bis",), commit=False)
    conn.rollback()                                                       # l'appelant renonce : rien n'a eu lieu
    assert fait == [q_coord, q_worker]
    assert conn.execute("SELECT count(*) FROM obligations WHERE etat = 'abandonnee'").fetchone() == (0,)
    conn.execute("BEGIN IMMEDIATE")
    obligations.abandonner_equipe(conn, "alpha", "utilisateur", 42, autres=("alpha-bis",), commit=False)
    conn.commit()
    etats = dict(conn.execute("SELECT message_id, etat FROM obligations"))
    assert etats == {q_coord: "abandonnee", q_worker: "abandonnee", q_autre: "ouverte", q_bis: "ouverte",
                     q_assistant: "ouverte"}
    assert conn.execute("SELECT etat, auteur, json_extract(preuve, '$.cloture'), json_extract(preuve, '$.par_evenement')"
                        " FROM transitions WHERE message_id = ? ORDER BY id DESC LIMIT 1", (q_coord,)
                        ).fetchone() == ("abandonne", "utilisateur", "alpha", 42)
    assert obligations.abandonner_equipe(conn, "alpha", "utilisateur", 43, autres=("alpha-bis",)) == []   # idempotent
