"""signaux/vue.py et la table `occupation` : registre fabriqué dans un dossier jetable."""
from datetime import datetime, timedelta, timezone

from cime.fondation import registre
from cime.signaux import facteur, livraison, obligations, vue

MAINTENANT = datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)


def _iso(instant):
    return instant.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _message(conn, de, a, nature="consigne", *, age=timedelta(minutes=1), objet=None, resume="x"):
    ident = registre.inscrire_message(conn, de=de, a=a, nature=nature, resume=resume, objet=objet)
    conn.execute("UPDATE messages SET horodatage = ? WHERE id = ?", (_iso(MAINTENANT - age), ident))
    conn.commit()
    return ident


def test_occupation_table_creee_et_migree(tmp_path):
    conn = registre.ouvrir(tmp_path)
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='occupation'").fetchone()
    registre.ouvrir(tmp_path)  # idempotent


def test_facteur_persiste_l_occupation(tmp_path):
    memoire = livraison.Memoire(occupe_par={"coord-x": "tour", "worker-x": None})
    livraison.persister_occupation(tmp_path, MAINTENANT, memoire)
    memoire.occupe_par["coord-x"] = "invite"
    livraison.persister_occupation(tmp_path, MAINTENANT, memoire)
    conn = registre.ouvrir(tmp_path)
    assert dict(conn.execute("SELECT agent, occupe_par FROM occupation")) == {
        "coord-x": "invite", "worker-x": None}


def test_un_tour_du_facteur_ecrit_occupation(tmp_path, monkeypatch):
    memoire = livraison.Memoire(occupe_par={"coord-x": "tour"})
    monkeypatch.setattr(livraison, "livrer_tout", lambda *a, **k: None)
    facteur._etape_livraison(tmp_path, MAINTENANT, memoire)
    conn = registre.ouvrir(tmp_path)
    assert conn.execute("SELECT occupe_par FROM occupation WHERE agent='coord-x'").fetchone() == ("tour",)


def test_flux_transitions_et_voie(tmp_path):
    conn = registre.ouvrir(tmp_path)
    m1 = _message(conn, "assistant", "coord-x", objet="o1")
    registre.inscrire_transition(conn, m1, "inscrit", "assistant", {})
    cur = conn.execute("INSERT INTO courriers (a, voie, cree, expire, etat) VALUES"
                       " ('coord-x', 'tmux', 't', 't', 'ouvert')")
    registre.inscrire_transition(conn, m1, "livre", "cime", {}, courrier_id=cur.lastrowid)
    m2 = _message(conn, "cime", "utilisateur", "signalement")
    registre.inscrire_transition(conn, m2, "inscrit", "cime", {})
    registre.inscrire_transition(conn, m2, "livre", "cime", {"voie": "hote", "notif": True})
    obligations.ouvrir_obligation(conn, m1, "coord-x", "reponse", "2026-10-09T12:30:00.000Z")
    lignes = vue.flux(conn)
    assert [ligne["id"] for ligne in lignes] == [m1, m2]
    premiere = lignes[0]
    assert premiere["etat"] == "livre" and premiere["debiteur"] == "coord-x"
    assert premiere["echeance"] == "2026-10-09T12:30:00.000Z"
    assert [(t["etat"], t["voie"], t["auteur"]) for t in premiere["transitions"]] == [
        ("inscrit", None, "assistant"), ("livre", "tmux", "cime")]
    assert lignes[1]["transitions"][1]["voie"] == "hote"
    assert lignes[1]["debiteur"] is None


def test_flux_limite_aux_dernieres(tmp_path):
    conn = registre.ouvrir(tmp_path)
    ids = [_message(conn, "assistant", "coord-x") for _ in range(5)]
    assert [ligne["id"] for ligne in vue.flux(conn, limite=2)] == ids[-2:]


def test_aretes_agregat(tmp_path):
    conn = registre.ouvrir(tmp_path)
    a = _message(conn, "assistant", "coord-x")                                  # en file
    registre.inscrire_transition(conn, a, "inscrit", "assistant", {})
    b = _message(conn, "assistant", "coord-x", age=timedelta(minutes=30))       # livré, ouvert
    registre.inscrire_transition(conn, b, "inscrit", "assistant", {})
    registre.inscrire_transition(conn, b, "livre", "cime", {})
    obligations.ouvrir_obligation(conn, b, "coord-x", "reponse")
    c = _message(conn, "coord-x", "assistant", age=timedelta(hours=3))          # clos, vieux
    registre.inscrire_transition(conn, c, "inscrit", "coord-x", {})
    registre.inscrire_transition(conn, c, "clos", "assistant", {})
    assert vue.aretes(conn, MAINTENANT) == [
        {"de": "assistant", "a": "coord-x", "en_file": 1, "livre": 1, "ouvertes": 1, "total_15min": 1}]


def test_file_et_dettes(tmp_path):
    conn = registre.ouvrir(tmp_path)
    a = _message(conn, "assistant", "coord-x", objet="o")
    registre.inscrire_transition(conn, a, "inscrit", "assistant", {})
    b = _message(conn, "assistant", "coord-x")
    registre.inscrire_transition(conn, b, "inscrit", "assistant", {})
    registre.inscrire_transition(conn, b, "livre", "cime", {})
    obligations.ouvrir_obligation(conn, b, "coord-x", "reponse")
    assert [m["id"] for m in vue.file_de(conn, "coord-x")] == [a]
    assert vue.file_de(conn, "coord-y") == []
    dettes = vue.dettes_de(conn, "coord-x")
    assert [(d["id"], d["attendu"], d["de"]) for d in dettes] == [(b, "reponse", "assistant")]
    obligations.satisfaire(conn, b, None)
    assert vue.dettes_de(conn, "coord-x") == []


def test_ordres_et_curseur(tmp_path):
    conn = registre.ouvrir(tmp_path)
    for i in range(3):
        conn.execute("INSERT INTO ordres (horodatage, auteur, verbe, cible, parametres, etat)"
                     " VALUES ('t', 'assistant', 'lancer', ?, '{}', 'execute')", (f"c{i}",))
    conn.commit()
    assert [o["cible"] for o in vue.ordres(conn, limite=2)] == ["c1", "c2"]
    m = _message(conn, "assistant", "coord-x")
    t1 = registre.inscrire_transition(conn, m, "inscrit", "assistant", {})
    t2 = registre.inscrire_transition(conn, m, "livre", "cime", {"voie": "hook"})
    assert [t["id"] for t in vue.transitions_depuis(conn, 0)] == [t1, t2]
    nouvelles = vue.transitions_depuis(conn, t1)
    assert [(t["id"], t["voie"], t["a"]) for t in nouvelles] == [(t2, "hook", "coord-x")]
    assert vue.transitions_depuis(conn, t2) == []
