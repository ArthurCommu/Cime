"""Réponses de l'utilisateur à l'Assistant : trancher, déposer, marquer lu, demander."""
import io
import json
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from cime.hote import actions_reponses, creer_app
from cime.hote.dependances import Dependances
from cime.hote.gardes import Gardes
from conftest import SOCKET_ESSAI

PORT = 8765
FAUX = str(Path(__file__).parent / "faux_envoyer.py")
ATTENTES = [
    {"id": "msg-12", "nature": "decision", "titre": "Port du serveur local"},
    {"id": "msg-13", "nature": "donnee"},
    {"id": "msg-14", "nature": "rapport"},
    {"id": "perm-d41", "nature": "autorisation"},
]


@pytest.fixture
def env(registre_vide, tmp_path, monkeypatch):
    note = tmp_path / "note.json"
    monkeypatch.setenv("FAUX_NOTE", str(note))
    monkeypatch.delenv("FAUX_REFUS", raising=False)
    inst = {"attentes_utilisateur": ATTENTES, "fil": [{"id": "msg-14", "fichier": ".orga/teams/x/reports/r.md"}]}
    deps = Dependances(instantane=lambda p: inst, prefixe="cc-essai", tmux_socket=SOCKET_ESSAI,
                       envoyer=[sys.executable, FAUX], intervalle_s=0.05)
    app = creer_app(registre_vide, deps, PORT)
    # instantané injecté directement : pas besoin d'attendre le rafraîchisseur
    app.state.contexte.rafraichisseur.instantane = inst
    c = TestClient(app, base_url=f"http://127.0.0.1:{PORT}")
    return c, registre_vide, note, app.state.contexte


def journal(projet):
    with closing(sqlite3.connect(projet / ".orga" / "etat" / "registre.sqlite")) as c:
        return c.execute("SELECT auteur, action, cible, resultat FROM journal ORDER BY id").fetchall()


def appel(note):
    return json.loads(note.read_text())


def trancher(c, attente="msg-12", reponse="Oui, on y va."):
    return c.post("/api/actions/trancher", json={"attente_id": attente, "reponse": reponse})


def test_trancher_ok(env):
    c, projet, note, _ = env
    r = trancher(c)
    assert r.json()["resultat"] == "ok"
    assert (projet / ".orga/depots/msg-12/reponse.md").read_text() == "Oui, on y va."
    a = appel(note)
    assert a["argv"] == ["12", "--fichier", ".orga/depots/msg-12/reponse.md",
                         "L'utilisateur a tranché : Oui, on y va."]
    assert a["CIME_AGENT"] == "utilisateur"
    assert a["CIME_PROJET"] == str(projet.resolve())
    assert journal(projet) == [("utilisateur", "trancher", "msg-12", "ok")]


def test_resume_une_ligne_et_borne():
    r = actions_reponses._resume_trancher("a\n\nb   c " + "x" * 500)
    assert "\n" not in r and len(r) <= 160 and r.startswith("L'utilisateur a tranché : a b c x")


def test_trancher_refus_de_la_commande_garde_le_fichier(env, monkeypatch):
    c, projet, note, _ = env
    monkeypatch.setenv("FAUX_REFUS", "1")
    r = trancher(c).json()
    assert r["resultat"] == "erreur"
    assert "registre indisponible" in r["message"]
    assert "réponse conservée dans .orga/depots/msg-12/reponse.md" in r["message"]
    assert (projet / ".orga/depots/msg-12/reponse.md").is_file()
    (ligne,) = journal(projet)
    assert ligne[3].startswith("erreur:") and "registre indisponible" in ligne[3]


def test_trancher_commande_introuvable(env):
    c, projet, _, contexte = env
    contexte.deps.envoyer = ["commande-qui-n-existe-pas-cime"]
    r = trancher(c).json()
    assert r["resultat"] == "erreur" and "introuvable" in r["message"]
    assert "réponse conservée" in r["message"]
    assert (projet / ".orga/depots/msg-12/reponse.md").is_file()


def test_trancher_deja_repondu(env):
    c, projet, note, _ = env
    assert trancher(c).json()["resultat"] == "ok"
    note.unlink()
    r = trancher(c, reponse="Autre").json()
    assert r["resultat"] == "refuse" and "déjà répondu" in r["message"]
    assert not note.exists()
    assert (projet / ".orga/depots/msg-12/reponse.md").read_text() == "Oui, on y va."


@pytest.mark.parametrize("attente,reponse", [
    ("msg-99", "x"),           # inconnue
    ("msg-13", "x"),           # mauvaise nature
    ("perm-d41", "x"),         # demande de permission
    ("../msg-12", "x"),
    ("msg-12", ""),
    ("msg-12", "   \n"),
    ("msg-12", "x" * 20_001),
    ("msg-12", 3),
    (None, "x"),
])
def test_trancher_refuse(env, attente, reponse):
    c, projet, note, _ = env
    r = trancher(c, attente, reponse)
    assert r.json()["resultat"] == "refuse"
    assert not note.exists() and not (projet / ".orga/depots").exists()
    (ligne,) = journal(projet)
    assert ligne[:2] == ("utilisateur", "trancher") and ligne[3] == "refuse"


def test_trancher_corps_illisible(env):
    c, projet, _, _ = env
    r = c.post("/api/actions/trancher", content=b"pas du json")
    assert r.json()["resultat"] == "refuse"
    assert len(journal(projet)) == 1


def test_trancher_sans_instantane(env):
    c, projet, _, contexte = env
    contexte.rafraichisseur.instantane = None
    assert trancher(c).json()["resultat"] == "refuse"
    contexte.rafraichisseur.instantane = {"attentes_utilisateur": None}
    assert trancher(c).json()["resultat"] == "refuse"


def deposer(c, fichiers, attente="msg-13"):
    return c.post("/api/actions/deposer", data={"attente_id": attente},
                  files=[("f", (nom, io.BytesIO(contenu))) for nom, contenu in fichiers])


def test_deposer_noms_hostiles_et_doublons(env):
    c, projet, note, _ = env
    r = deposer(c, [("../../x", b"1"), (".env", b"2"), ("a/b.txt", b"3"), ("b.txt", b"4"),
                    ("b.txt", b"5"), ("é ü.pdf", b"7")])
    assert r.json()["resultat"] == "ok", r.text
    dossier = projet / ".orga/depots/msg-13"
    assert sorted(p.name for p in dossier.iterdir()) == sorted(
        ["x", "env", "b.txt", "b-2.txt", "b-3.txt", "___.pdf"])
    assert (dossier / "b.txt").read_bytes() == b"3" and (dossier / "b-3.txt").read_bytes() == b"5"
    assert not (projet.parent / "x").exists()
    a = appel(note)
    assert a["argv"] == ["13", "L'utilisateur a déposé 6 fichier(s) dans .orga/depots/msg-13/"]
    assert a["CIME_AGENT"] == "utilisateur"
    assert journal(projet) == [("utilisateur", "deposer", "msg-13", "ok")]


def test_deposer_trop_gros(env, monkeypatch):
    c, projet, note, _ = env
    monkeypatch.setattr(actions_reponses, "TOTAL_DEPOT_MAX", 10)
    r = deposer(c, [("a", b"123456"), ("b", b"123456")]).json()
    assert r["resultat"] == "refuse" and "rien n'a été écrit" in r["message"]
    assert not (projet / ".orga/depots").exists() and not note.exists()
    assert journal(projet)[0][3] == "refuse"


def test_deposer_limite_exacte_acceptee(env, monkeypatch):
    c, _, _, _ = env
    monkeypatch.setattr(actions_reponses, "TOTAL_DEPOT_MAX", 12)
    assert deposer(c, [("a", b"123456"), ("b", b"123456")]).json()["resultat"] == "ok"


@pytest.mark.parametrize("attente", ["msg-12", "msg-99", "perm-d41", "../x", ""])
def test_deposer_refuse(env, attente):
    c, projet, note, _ = env
    assert deposer(c, [("a", b"1")], attente).json()["resultat"] == "refuse"
    assert not (projet / ".orga/depots").exists() and not note.exists()


def test_deposer_sans_fichier_ni_multipart(env):
    c, projet, _, _ = env
    assert c.post("/api/actions/deposer", data={"attente_id": "msg-13"}).json()["resultat"] == "refuse"
    assert c.post("/api/actions/deposer", json={"attente_id": "msg-13"}).json()["resultat"] == "refuse"
    assert len(journal(projet)) == 2


def test_deposer_envoi_refuse_garde_les_fichiers(env, monkeypatch):
    c, projet, _, _ = env
    monkeypatch.setenv("FAUX_REFUS", "1")
    r = deposer(c, [("a.txt", b"1")]).json()
    assert r["resultat"] == "erreur" and "fichiers conservés" in r["message"]
    assert (projet / ".orga/depots/msg-13/a.txt").is_file()


def test_lu_journal_seulement(env, monkeypatch):
    c, projet, note, _ = env

    async def espion(self, *a, **k):
        raise AssertionError("aexecuter appelé")

    monkeypatch.setattr(Gardes, "aexecuter", espion)
    r = c.post("/api/actions/lu", json={"attente_id": "msg-14"})
    assert r.json()["resultat"] == "ok"
    assert journal(projet) == [("utilisateur", "lu", "msg-14", "ok")]
    assert not note.exists()


@pytest.mark.parametrize("attente", ["msg-12", "msg-99", "perm-d41", None])
def test_lu_refuse(env, attente):
    c, projet, _, _ = env
    assert c.post("/api/actions/lu", json={"attente_id": attente}).json()["resultat"] == "refuse"
    assert journal(projet)[0][3] == "refuse"


def test_nettoyer_nom():
    n = actions_reponses.nettoyer_nom
    assert [n(x) for x in ["../../x", ".env", "a/b.txt", "..", ".", "", None, "a\\b\\c.md", "x y"]] == [
        "x", "env", "b.txt", "fichier", "fichier", "fichier", "fichier", "c.md", "x_y"]


def test_trancher_nouvel_essai_apres_envoi_rate(env, monkeypatch):
    """Envoi raté → L'utilisateur peut réessayer ; l'ancien texte est gardé en reponse-1.md."""
    c, projet, note, _ = env
    monkeypatch.setenv("FAUX_REFUS", "1")
    assert trancher(c, reponse="Premier").json()["resultat"] == "erreur"
    monkeypatch.delenv("FAUX_REFUS")
    r = trancher(c, reponse="Second").json()
    assert r["resultat"] == "ok", r
    d = projet / ".orga/depots/msg-12"
    assert (d / "reponse.md").read_text() == "Second"
    assert (d / "reponse-1.md").read_text() == "Premier"
    # une fois transmise, plus de nouvel essai
    r = trancher(c, reponse="Troisième").json()
    assert r["resultat"] == "refuse" and "déjà répondu" in r["message"]
    assert (d / "reponse.md").read_text() == "Second"


def test_deposer_nouvel_essai_apres_envoi_rate(env, monkeypatch):
    c, projet, note, _ = env
    monkeypatch.setenv("FAUX_REFUS", "1")
    assert deposer(c, [("a.txt", b"1")]).json()["resultat"] == "erreur"
    monkeypatch.delenv("FAUX_REFUS")
    assert deposer(c, [("a.txt", b"2")]).json()["resultat"] == "ok"
    d = projet / ".orga/depots/msg-13"
    assert (d / "a.txt").read_bytes() == b"1" and (d / "a-2.txt").read_bytes() == b"2"
    r = deposer(c, [("b.txt", b"3")]).json()
    assert r["resultat"] == "refuse" and "déjà répondu" in r["message"]
    assert not (d / "b.txt").exists()


def test_envoyer_lance_depuis_la_racine_du_projet(env, monkeypatch, tmp_path):
    """`cime repondre` résout `--fichier` depuis le répertoire courant :
    l'hôte doit le lancer depuis la racine du projet, quel que soit son propre répertoire."""
    import json, os
    c, projet, note, _ = env
    ailleurs = tmp_path / "ailleurs"
    ailleurs.mkdir()
    monkeypatch.chdir(ailleurs)
    assert trancher(c).json()["resultat"] == "ok"
    vu = json.loads(note.read_text())
    assert os.path.realpath(vu["cwd"]) == os.path.realpath(projet)


def _lignes_completes(projet):
    with closing(sqlite3.connect(projet / ".orga" / "etat" / "registre.sqlite")) as c:
        return c.execute("SELECT action, cible, details FROM journal ORDER BY id").fetchall()


def test_journal_cible_et_details(env):
    c, projet, _, _ = env
    trancher(c, reponse="8765\nvoilà")
    deposer(c, [("a.txt", b"1"), ("b.txt", b"22")])
    c.post("/api/actions/lu", json={"attente_id": "msg-14"})
    assert _lignes_completes(projet) == [
        ("trancher", "msg-12", json.dumps({"question": "Port du serveur local", "choix": "8765 voilà"}, ensure_ascii=False)),
        ("deposer", "msg-13", json.dumps(
            {"fichiers": [".orga/depots/msg-13/a.txt", ".orga/depots/msg-13/b.txt"], "octets": 3})),
        ("lu", "msg-14", json.dumps({"rapport": ".orga/teams/x/reports/r.md"})),
    ]


def test_journal_details_un_seul_fichier_et_troncature(env):
    c, projet, _, _ = env
    trancher(c, reponse="x" * 500)
    deposer(c, [("a.txt", b"1234")])
    lignes = _lignes_completes(projet)
    assert json.loads(lignes[0][2])["choix"] == "x" * 200
    assert json.loads(lignes[1][2]) == {"fichier": ".orga/depots/msg-13/a.txt", "octets": 4}


def test_journal_details_cas_null_et_refus_avant_rangement(env):
    c, projet, _, _ = env
    c.post("/api/actions/lu", json={"attente_id": "attente-99"})  # introuvable (forme msg-<n> : voie registre)
    trancher(c, attente="msg-77")  # attente inconnue : question null
    deposer(c, [("a.txt", b"1")], attente="msg-12")  # mauvaise nature : refusé avant rangement
    assert [(a, json.loads(d)) for a, _, d in _lignes_completes(projet)] == [
        ("lu", {"rapport": None}),
        ("trancher", {"question": None, "choix": "Oui, on y va."}),
        ("deposer", {"fichier": "a.txt", "octets": 1}),
    ]


# --- demander : la page formule une demande à l'Assistant ------------------------------------------

def demander(c, texte="relance l'équipe alpha"):
    return c.post("/api/actions/demander", json={"texte": texte})


def test_demander_ok(env):
    c, projet, note, _ = env
    r = demander(c, "  relance   l'équipe alpha ")
    assert r.json()["resultat"] == "ok"
    a = appel(note)
    assert a["argv"] == ["--a", "assistant", "--nature", "consigne", "--attend", "reponse",
                         "--objet", "demande-page", "relance l'équipe alpha"]
    assert a["CIME_AGENT"] == "utilisateur"
    assert journal(projet) == [("utilisateur", "demander", "assistant", "ok")]


@pytest.mark.parametrize("texte", [None, "", "   ", "-x", "a" * 161, 12])
def test_demander_refuse(env, texte):
    c, projet, note, _ = env
    assert demander(c, texte).json()["resultat"] == "refuse"
    assert not note.exists()
    assert journal(projet)[0][1:] == ("demander", "assistant", "refuse")


def test_demander_envoi_en_echec(env, monkeypatch):
    c, projet, note, _ = env
    monkeypatch.setenv("FAUX_REFUS", "1")
    assert demander(c).json()["resultat"] == "erreur"
    assert journal(projet) == [("utilisateur", "demander", "assistant", "erreur: registre indisponible")]


def test_gardes_envoi_demande_page_seulement():
    from cime.hote.gardes import Gardes, Interdit
    g = Gardes("cc-essai")
    base = [*g.envoyer, "--a", "assistant"]
    g.autoriser_commande([*base, "--nature", "consigne", "--attend", "reponse", "--objet", "demande-page", "x"])
    for mal in (["--nature", "consigne", "--attend", "travail_pret", "--objet", "demande-page", "x"],
                ["--nature", "consigne", "--objet", "autre", "x"],
                ["--nature", "question", "--attend", "reponse", "x"]):
        with pytest.raises(Interdit):
            g.autoriser_commande([*base, *mal])
    with pytest.raises(Interdit):
        g.autoriser_commande([*g.envoyer, "--a", "coord-alpha", "--nature", "consigne", "--attend", "reponse",
                              "--objet", "demande-page", "x"])
