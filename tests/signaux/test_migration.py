import sqlite3

from aide import fabriquer_projet
from cime.fondation import init
from cime.fondation.registre import chemin_registre
from cime.signaux import migration

ANCIEN = """
CREATE TABLE messages (
  id INTEGER PRIMARY KEY, horodatage TEXT NOT NULL, de TEXT NOT NULL, a TEXT NOT NULL,
  nature TEXT NOT NULL, resume TEXT NOT NULL, fichier TEXT, en_reponse_a INTEGER,
  equipe TEXT);
CREATE TABLE evenements (id INTEGER PRIMARY KEY, horodatage TEXT NOT NULL, agent TEXT,
  session_id TEXT, evenement TEXT NOT NULL, details TEXT NOT NULL);
CREATE TABLE journal (id INTEGER PRIMARY KEY, horodatage TEXT NOT NULL, auteur TEXT NOT NULL,
  action TEXT NOT NULL, cible TEXT, details TEXT, resultat TEXT NOT NULL);
"""


def ancien_registre(projet):
    (projet / ".orga/etat").mkdir(parents=True, exist_ok=True)
    (projet / ".orga/teams/x/conversations").mkdir(parents=True, exist_ok=True)
    (projet / ".orga/teams/x/pour-assistant-20261001.md").write_text("q")
    (projet / ".orga/teams/x/reponse-assistant-20261001.md").write_text("r")
    conn = sqlite3.connect(chemin_registre(projet))
    conn.executescript(ANCIEN)
    lignes = [
        # 1 : question répondue par fichier ; 2 : question ouverte ; 3 : ordinaire ;
        # 4 : question avec réponse enregistrée, 5 : sa réponse
        ("coord-x", "assistant", "question", "répondue par fichier",
         ".orga/teams/x/pour-assistant-20261001.md", None),
        ("coord-x", "assistant", "question", "toujours ouverte",
         ".orga/teams/x/pour-assistant-20261002.md", None),
        ("assistant", "coord-x", "consigne", "ordinaire", None, None),
        ("coord-x", "assistant", "question", "répondue", None, None),
        ("assistant", "coord-x", "reponse", "voilà", None, 4),
    ]
    for de, a, nature, resume, fichier, rep in lignes:
        conn.execute("INSERT INTO messages (horodatage,de,a,nature,resume,fichier,en_reponse_a)"
                     " VALUES ('2026-10-01T10:00:00.000Z',?,?,?,?,?,?)",
                     (de, a, nature, resume, fichier, rep))
    conn.commit()
    conn.close()


def etats(projet):
    conn = sqlite3.connect(chemin_registre(projet))
    return {i: (e, p) for i, e, p in conn.execute(
        "SELECT message_id, etat, preuve FROM transitions ORDER BY id")}


def test_migration_ancien_registre(tmp_path):
    projet = fabriquer_projet(tmp_path / "depot")
    ancien_registre(projet)
    stats = migration.migrer(projet)
    assert stats["sauvegarde"] and stats["clos"] == 3 and stats["clos_par_fichier"] == 1
    assert stats["ouvertes"] == 1
    e = etats(projet)
    assert e[1] == ("clos", '{"preuve": "migration:fichier"}')
    assert e[3] == ("clos", '{"preuve": "migration-1.10"}') and e[4][0] == "clos" and e[5][0] == "clos"
    assert e[2][0] == "inscrit"
    conn = sqlite3.connect(chemin_registre(projet))
    assert conn.execute("SELECT message_id, debiteur, attendu, echeance, etat FROM obligations"
                        ).fetchall() == [(2, "assistant", "reponse", None, "ouverte")]
    rapport = (projet / ".orga/etat/migration-registre-2.0.md").read_text()
    assert "#2 · coord-x → assistant · toujours ouverte" in rapport and "#1" not in rapport
    # la sauvegarde est l'ancien registre, intact
    ancien = sqlite3.connect(migration.chemin_sauvegarde(projet))
    assert ancien.execute("SELECT count(*) FROM messages").fetchone() == (5,)
    assert "transitions" not in {r[0] for r in ancien.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def test_migration_idempotente(tmp_path):
    projet = fabriquer_projet(tmp_path / "depot")
    ancien_registre(projet)
    migration.migrer(projet)
    conn = sqlite3.connect(chemin_registre(projet))
    avant = [conn.execute(f"SELECT * FROM {t}").fetchall()
             for t in ("transitions", "obligations")]
    sauvegarde = migration.chemin_sauvegarde(projet).stat().st_mtime_ns
    rapport = (projet / ".orga/etat/migration-registre-2.0.md").read_text()
    stats = migration.migrer(projet)
    assert (stats["sauvegarde"], stats["clos"], stats["ouvertes"]) == (False, 0, 0)
    assert avant == [conn.execute(f"SELECT * FROM {t}").fetchall()
                     for t in ("transitions", "obligations")]
    assert migration.chemin_sauvegarde(projet).stat().st_mtime_ns == sauvegarde
    assert (projet / ".orga/etat/migration-registre-2.0.md").read_text() == rapport


def test_sauvegarde_jamais_ecrasee(tmp_path):
    projet = fabriquer_projet(tmp_path / "depot")
    ancien_registre(projet)
    migration.chemin_sauvegarde(projet).write_bytes(b"deja la")
    assert migration.sauvegarder(projet) is False
    assert migration.chemin_sauvegarde(projet).read_bytes() == b"deja la"


def test_init_migrer_ajoute_la_migration_du_registre(tmp_path, monkeypatch):
    import argparse
    monkeypatch.setattr(init, "executable_cime", lambda: "/usr/bin/cime")
    projet = tmp_path / "neuf"
    args = argparse.Namespace(dossier=str(projet), utilisateur="Camille", nom_projet=None,
                              prefixe=None, lancer=False, modele=None, migrer=True,
                              hooks_sans_cime=False)
    rapport = init.installer(args)
    assert any("messages clos" in m for m in rapport["migration"])
    again = init.installer(args)
    assert any("0 messages clos" in m for m in again["migration"])
