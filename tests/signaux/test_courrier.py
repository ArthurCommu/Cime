import json
import threading

import pytest

from aide import fabriquer_projet
from cime.fondation.registre import etat_message, horodatage, inscrire_transition, ouvrir
from cime.signaux import commandes, courrier


@pytest.fixture
def projet(tmp_path, monkeypatch):
    racine = fabriquer_projet(tmp_path / "depot")
    monkeypatch.setenv("CIME_PROJET", str(racine))
    return racine


def poster(projet, de, a, nature="consigne", resume="r", corps=None, attend="rien", objet=None):
    conn = ouvrir(projet)
    try:
        return commandes.inscrire(conn, de=de, a=a, nature=nature, resume=resume, corps=corps,
                                  attend=attend, objet=objet, equipe="x")
    finally:
        conn.close()


def prendre(projet, a="coord-x", voie="hook:Stop", **kw):
    conn = ouvrir(projet)
    try:
        return courrier.prendre(conn, a, voie, "cime", {"evenement": "Stop"}, **kw)
    finally:
        conn.close()


def test_en_attente_ordonne_et_ne_garde_que_inscrit(projet):
    a, b, c = (poster(projet, "assistant", "coord-x", resume=str(i)) for i in range(3))
    poster(projet, "assistant", "coord-y")
    conn = ouvrir(projet)
    inscrire_transition(conn, b, "livre", "cime", {})
    assert [m["id"] for m in courrier.en_attente(conn, "coord-x")] == [a, c]


def test_prendre_lot_de_cinq_au_plus_et_transition_livre(projet):
    ids = [poster(projet, "assistant", "coord-x", resume=f"m{i}") for i in range(7)]
    c = prendre(projet)
    assert [m["id"] for m in c.messages] == ids[:5] and c.tentative == 1
    conn = ouvrir(projet)
    assert etat_message(conn, ids[0]) == "livre" and etat_message(conn, ids[5]) == "inscrit"
    t = conn.execute("SELECT courrier_id, auteur, preuve FROM transitions WHERE message_id=?"
                     " AND etat='livre'", (ids[0],)).fetchone()
    assert t[0] == c.id and t[1] == "cime"
    assert json.loads(t[2]) == {"evenement": "Stop", "octets": 2}
    # le second preneur est refusé tant que le courrier est ouvert
    assert prendre(projet) is None
    assert etat_message(conn, ids[5]) == "inscrit"


def test_rien_a_prendre(projet):
    assert prendre(projet) is None


def test_huit_threads_un_seul_gagnant_aucun_message_livre_deux_fois(projet):
    for i in range(3):
        poster(projet, "assistant", "coord-x", resume=f"m{i}")
    ouvrir(projet).close()
    barriere = threading.Barrier(8)
    resultats = []

    def agir():
        conn = ouvrir(projet)
        try:
            barriere.wait()
            resultats.append(courrier.prendre(conn, "coord-x", "hook:PostToolUse", "cime", {}))
        finally:
            conn.close()

    fils = [threading.Thread(target=agir) for _ in range(8)]
    [f.start() for f in fils]
    [f.join() for f in fils]
    gagnants = [r for r in resultats if r is not None]
    assert len(resultats) == 8 and len(gagnants) == 1
    conn = ouvrir(projet)
    assert conn.execute("SELECT count(*) FROM transitions WHERE etat='livre'").fetchone() == (3,)
    assert conn.execute("SELECT count(*) FROM courriers").fetchone() == (1,)


def test_deux_destinataires_en_parallele_sans_conflit(projet):
    poster(projet, "assistant", "coord-x")
    poster(projet, "assistant", "coord-y")
    ouvrir(projet).close()
    barriere = threading.Barrier(2)
    resultats = {}

    def agir(a):
        conn = ouvrir(projet)
        try:
            barriere.wait()
            resultats[a] = courrier.prendre(conn, a, "hook:Stop", "cime", {})
        finally:
            conn.close()

    fils = [threading.Thread(target=agir, args=(a,)) for a in ("coord-x", "coord-y")]
    [f.start() for f in fils]
    [f.join() for f in fils]
    assert resultats["coord-x"] is not None and resultats["coord-y"] is not None


def test_courrier_expire_sans_accuse_est_repris_tentative_plus_un(projet):
    m = poster(projet, "assistant", "coord-x")
    # voie tmux : un courrier hook: expiré n'est plus refermé sans accusé (doublons-livraison-envoi)
    premier = prendre(projet, voie="tmux", bail_s=-1)
    assert premier.tentative == 1
    second = prendre(projet, voie="tmux")
    assert second is not None and second.tentative == 2
    assert [x["id"] for x in second.messages] == [m]
    conn = ouvrir(projet)
    assert conn.execute("SELECT etat FROM courriers WHERE id=?", (premier.id,)
                        ).fetchone() == ("echoue",)
    reprise = conn.execute("SELECT preuve FROM transitions WHERE message_id=? AND etat='inscrit'"
                           " ORDER BY id DESC", (m,)).fetchone()
    assert json.loads(reprise[0]) == {"reprise": premier.id, "tentative": 2}


def test_courrier_expire_deja_pris_en_compte_passe_acquitte(projet):
    m = poster(projet, "assistant", "coord-x")
    # voie tmux : un courrier hook: expiré n'est plus refermé sans accusé (doublons-livraison-envoi)
    premier = prendre(projet, voie="tmux", bail_s=-1)
    conn = ouvrir(projet)
    inscrire_transition(conn, m, "pris_en_compte", "coord-x", {"preuve": "indirecte"})
    assert prendre(projet, voie="tmux") is None
    assert conn.execute("SELECT etat FROM courriers WHERE id=?", (premier.id,)
                        ).fetchone() == ("acquitte",)
    assert etat_message(conn, m) == "pris_en_compte"


def test_formater_hook_corps_entier_et_lots(projet):
    poster(projet, "assistant", "worker-x-t", corps="ligne 1\nligne 2", resume="résumé")
    poster(projet, "coord-x", "worker-x-t", resume="court")
    poster(projet, "cime", "worker-x-t", resume="c")
    c = prendre(projet, "worker-x-t")
    conn = ouvrir(projet)
    ids = [m["id"] for m in c.messages]
    assert courrier.formater(conn, c, "hook") == (
        f"Assistant : ligne 1\nligne 2 (#{ids[0]}) ‖ coordinateur x : court (#{ids[1]})"
        f" ‖ Cime : c (#{ids[2]})")


@pytest.mark.parametrize("de,attendu", [
    ("worker-x-t", "worker x/t"), ("utilisateur", "Utilisateur"), ("coord-x", "coordinateur x")])
def test_emetteurs_lisibles(de, attendu):
    assert courrier.emetteur_lisible(de) == attendu


def test_emetteur_worker_avec_equipe_a_tiret():
    assert courrier.emetteur_lisible("worker-mon-eq-tache-1", "mon-eq") == "worker mon-eq/tache-1"


def test_formater_tmux_une_ligne(projet):
    poster(projet, "assistant", "coord-x", corps="a\nb", resume="r")
    c = prendre(projet)
    conn = ouvrir(projet)
    texte = courrier.formater(conn, c, "tmux")
    assert texte == f"Assistant : a ⏎ b (#{c.messages[0]['id']})" and "\n" not in texte


def test_formater_tmux_long_ecrit_un_fichier(projet):
    long = "x" * 700
    ident = poster(projet, "assistant", "coord-x", corps=long, resume="le résumé")
    c = prendre(projet)
    conn = ouvrir(projet)
    texte = courrier.formater(conn, c, "tmux")
    chemin = projet / ".orga" / "etat" / "courrier" / f"{ident}.md"
    assert texte == f"Assistant : le résumé — {chemin} (#{ident})" and len(texte) <= 600
    assert chemin.read_text() == long
    assert courrier.formater(conn, c, "tmux") == texte  # déterministe


def test_acquitter_sans_obligation_clot_dans_la_meme_transaction(projet):
    m = poster(projet, "assistant", "coord-x")  # attend rien : aucune obligation
    c = prendre(projet)
    conn = ouvrir(projet)
    courrier.acquitter(conn, m, "coord-x", {"evenement": "UserPromptSubmit", "evenement_id": 9})
    assert [r[0] for r in conn.execute(
        "SELECT etat FROM transitions WHERE message_id=? ORDER BY id", (m,))] == [
        "inscrit", "livre", "pris_en_compte", "clos"]
    assert json.loads(conn.execute("SELECT preuve FROM transitions WHERE message_id=? AND"
                                   " etat='clos'", (m,)).fetchone()[0]) == {"par_evenement": 9}
    assert conn.execute("SELECT etat FROM courriers WHERE id=?", (c.id,)).fetchone() == ("acquitte",)


def test_acquitter_avec_obligation_ouverte_ne_clot_pas(projet):
    m = poster(projet, "assistant", "coord-x", attend="reponse")
    prendre(projet)
    conn = ouvrir(projet)
    courrier.acquitter(conn, m, "coord-x", {"evenement_id": 1})
    assert etat_message(conn, m) == "pris_en_compte"


def test_acquitter_obligation_accuse_est_satisfaite_par_l_accuse(projet):
    m = poster(projet, "assistant", "coord-x", attend="accuse")
    prendre(projet)
    conn = ouvrir(projet)
    courrier.acquitter(conn, m, "coord-x", {"evenement_id": 1})
    assert etat_message(conn, m) == "clos"
    assert conn.execute("SELECT etat FROM obligations WHERE message_id=?", (m,)
                        ).fetchone() == ("satisfaite",)


def test_courrier_acquitte_seulement_quand_tous_les_messages_le_sont(projet):
    a = poster(projet, "assistant", "coord-x")
    b = poster(projet, "assistant", "coord-x")
    c = prendre(projet)
    conn = ouvrir(projet)
    courrier.acquitter(conn, a, "coord-x", {"evenement_id": 1})
    assert conn.execute("SELECT etat FROM courriers WHERE id=?", (c.id,)).fetchone() == ("ouvert",)
    courrier.acquitter(conn, b, "coord-x", {"evenement_id": 2})
    assert conn.execute("SELECT etat FROM courriers WHERE id=?", (c.id,)).fetchone() == ("acquitte",)


def test_acquitter_ne_clot_pas_un_accord_qui_reste_a_consommer(projet):
    conn = ouvrir(projet)
    m = commandes.inscrire(conn, de="utilisateur", a="assistant", nature="accord", resume="ok",
                           objet="fusion:x:abcdef0")
    conn.close()
    prendre(projet, "assistant")
    conn = ouvrir(projet)
    courrier.acquitter(conn, m, "assistant", {"evenement_id": 3})
    assert etat_message(conn, m) == "pris_en_compte"


def _session_start(projet, source, agent="coord-x"):
    """Un `SessionStart` au registre (forme de `fondation/hook.py`) ; rend son id. `source` None : absente."""
    details = {} if source is None else {"source": source}
    conn = ouvrir(projet)
    try:
        with conn:
            cur = conn.execute("INSERT INTO evenements (horodatage, agent, session_id, evenement, details)"
                               " VALUES (?, ?, NULL, 'SessionStart', ?)",
                               (horodatage(), agent, json.dumps(details)))
        return cur.lastrowid
    finally:
        conn.close()


def prendre_a_la_session(projet, evenement_id, a="coord-x"):
    conn = ouvrir(projet)
    try:
        return courrier.prendre(conn, a, "hook:SessionStart", "cime",
                                {"evenement": "SessionStart", "evenement_id": evenement_id})
    finally:
        conn.close()


@pytest.mark.parametrize("source", ["compact", "resume", "clear"])
def test_session_sans_tour_ne_prend_rien_et_le_message_reste_inscrit(projet, source):
    m = poster(projet, "assistant", "coord-x")
    assert prendre_a_la_session(projet, _session_start(projet, source)) is None
    conn = ouvrir(projet)
    assert etat_message(conn, m) == "inscrit"
    assert conn.execute("SELECT count(*) FROM courriers").fetchone() == (0,)


@pytest.mark.parametrize("source", ["startup", None])
def test_session_neuve_ou_sans_source_prend_le_courrier(projet, source):
    m = poster(projet, "assistant", "coord-x")
    assert prendre_a_la_session(projet, _session_start(projet, source)) is not None
    assert etat_message(ouvrir(projet), m) == "livre"
