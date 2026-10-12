"""Journal des actions : protocole en deux temps, lecture, et hôte démarré sans registre lisible."""
import asyncio
import sqlite3
import threading
import time
from contextlib import closing
from datetime import datetime, timezone

import pytest
from starlette.testclient import TestClient

from cime.hote import creer_app, servir
from cime.hote.dependances import Dependances
from cime.hote.journal import Journal, executer_action

T = datetime(2026, 10, 7, 13, 4, 11, 123000, tzinfo=timezone.utc)
PORT = 8765


def journal_de(projet):
    return Journal(projet / ".orga" / "etat" / "registre.sqlite", lambda: T)


def lignes(projet):
    with closing(sqlite3.connect(projet / ".orga" / "etat" / "registre.sqlite")) as c:
        return c.execute("SELECT horodatage, auteur, action, cible, details, resultat FROM journal ORDER BY id").fetchall()


def lancer(j, faire, auteur="utilisateur"):
    return asyncio.run(executer_action(j, auteur, "autoriser", "demande-1", {"k": 1}, faire))


def test_ligne_avant_execution(registre_vide):
    j = journal_de(registre_vide)
    vu = []

    async def faire():
        vu.append(j.dernieres(10))
        return "ok", "fait"

    r = lancer(j, faire)
    assert r.status_code == 200
    assert vu[0][0]["resultat"] == "erreur: en cours" and vu[0][0]["details"] == {"k": 1}
    assert lignes(registre_vide) == [("2026-10-07T13:04:11.123Z", "utilisateur", "autoriser", "demande-1", '{"k": 1}', "ok")]


def test_exception_et_refus(registre_vide):
    j = journal_de(registre_vide)

    async def boum():
        raise ValueError("cassé")

    r = lancer(j, boum)
    assert r.status_code == 200 and b'"erreur"' in r.body and b"ValueError: cass" in r.body

    async def non():
        return "refuse", "non"

    lancer(j, non)
    assert [l[5] for l in lignes(registre_vide)] == ["erreur: ValueError: cassé", "refuse"]


def test_journal_indisponible(registre_vide, monkeypatch):
    j = journal_de(registre_vide)
    n = {"v": 0}

    def casse(*a):
        raise sqlite3.OperationalError("attempt to write a readonly database")

    monkeypatch.setattr(j, "ouvrir_ligne", casse)

    async def faire():
        n["v"] += 1
        return "ok", ""

    r = lancer(j, faire)
    assert n["v"] == 0 and r.status_code == 503
    assert b"action non ex" in r.body


def test_cloture_impossible(registre_vide, monkeypatch):
    j = journal_de(registre_vide)

    def casse(*a):
        raise sqlite3.OperationalError("disque plein")

    monkeypatch.setattr(j, "clore_ligne", casse)

    async def faire():
        return "ok", "x"

    r = lancer(j, faire)
    assert r.status_code == 200 and b"a \xc3\xa9t\xc3\xa9 ex\xc3\xa9cut\xc3\xa9e" in r.body
    assert lignes(registre_vide)[0][5] == "erreur: en cours"


def test_concurrence_messages(registre_vide):
    j = journal_de(registre_vide)
    chemin = registre_vide / ".orga" / "etat" / "registre.sqlite"
    erreurs = []

    def ecrivain():
        try:
            for i in range(200):
                with closing(sqlite3.connect(chemin, timeout=5)) as c:
                    with c:
                        c.execute("INSERT INTO messages(de) VALUES ('x')")
        except Exception as e:
            erreurs.append(e)

    t = threading.Thread(target=ecrivain)
    t.start()
    try:
        for i in range(200):
            j.clore_ligne(j.ouvrir_ligne("assistant", "a", None, {}), "ok")
    except Exception as e:
        erreurs.append(e)
    t.join()
    assert erreurs == []


def test_auteur_refuse(registre_vide):
    j = journal_de(registre_vide)
    with pytest.raises(ValueError):
        j.ouvrir_ligne("pirate", "a", None, {})

    async def faire():
        raise AssertionError

    with pytest.raises(ValueError):
        lancer(j, faire, auteur="pirate")
    assert lignes(registre_vide) == []


def test_api_journal(registre_vide):
    j = journal_de(registre_vide)
    for i in range(5):
        j.clore_ligne(j.ouvrir_ligne("utilisateur", f"a{i}", None, {"i": i}), "ok")
    d = Dependances(instantane=lambda p: {}, intervalle_s=0.05, horloge=lambda: T)
    with TestClient(creer_app(registre_vide, d, PORT), base_url=f"http://127.0.0.1:{PORT}") as c:
        r = c.get("/api/journal?limite=3").json()["lignes"]
        assert [l["action"] for l in r] == ["a4", "a3", "a2"] and r[0]["details"] == {"i": 4}
        assert len(c.get("/api/journal").json()["lignes"]) == 5
        for mauvais in ("0", "1001", "abc", ""):
            assert c.get(f"/api/journal?limite={mauvais}").status_code == 400


def test_registre_absent_ou_incomplet(tmp_path):
    """L'hôte démarre sans registre lisible, pour
    que l'utilisateur voie le problème dans la page ; le journal répond 503, aucune action ne
    s'exécute, et rien n'est jamais créé dans le registre."""
    d = Dependances(instantane=lambda p: {"version": 1, "sources": [{"nom": "registre", "ok": False}]})
    with pytest.raises(SystemExit, match="pas un projet"):
        servir(tmp_path, 0, d)
    assert not (tmp_path / ".orga").exists()

    base = tmp_path / ".orga" / "etat"
    base.mkdir(parents=True)
    registre = base / "registre.sqlite"

    def verifier():
        with TestClient(creer_app(tmp_path, d, PORT), base_url=f"http://127.0.0.1:{PORT}") as c:
            fin = time.monotonic() + 3
            while c.get("/api/etat").status_code != 200 and time.monotonic() < fin:
                time.sleep(0.02)
            assert c.get("/api/etat").status_code == 200
            assert c.get("/api/journal").status_code == 503
            r = c.post("/api/actions/lu", json={"attente_id": "msg-1"})
            assert r.status_code == 503

    verifier()  # registre absent
    assert not registre.exists(), "l'hôte a créé un registre"
    with closing(sqlite3.connect(registre)) as c:
        c.execute("CREATE TABLE messages(id INTEGER)")
    verifier()  # registre sans table journal
    with closing(sqlite3.connect(registre)) as c:
        assert [r[0] for r in c.execute("SELECT name FROM sqlite_master")] == ["messages"]
