"""Route `/api/actions/fusions-auto` : prérogative de l'utilisateur, journalisée, sans git.

La commande lancée est la vraie logique de `cime.fondation.fusions_auto.executer`, appelée par
`python -c` (il n'y a pas de `python -m cime` ; le binaire `cime` peut être une autre version).
"""
import json
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from cime.fondation import fusions_auto, registre
from cime.hote import creer_app
from cime.hote.dependances import Dependances
from cime.hote.gardes import Gardes

T = datetime(2026, 10, 11, 9, 0, 0, tzinfo=timezone.utc)
PORT = 8767
HOTE = {"host": f"127.0.0.1:{PORT}"}
ORIGINE = {"origin": f"http://127.0.0.1:{PORT}"}
P = "cc-essai-fusions"
# argv = [python, -c, LANCEUR, "fusions-auto", V] : sys.argv == ["-c", "fusions-auto", V]
SRC = Path(__file__).resolve().parents[2] / "src"  # le sous-processus ne voit pas le `pythonpath` de pytest
LANCEUR = (
    f"import sys, types; sys.path.insert(0, {str(SRC)!r}); from cime.fondation.fusions_auto import executer; "
    "sys.exit(executer(types.SimpleNamespace(valeur=sys.argv[2])))"
)


@pytest.fixture
def lances(monkeypatch):
    """Chaque lancement demandé à `Gardes` : (argv, options). Vérifie qu'aucun `git` n'est lancé."""
    vus = []
    orig = Gardes.aexecuter

    async def espionne(self, argv, **kw):
        vus.append((list(argv), kw))
        return await orig(self, argv, **kw)

    monkeypatch.setattr(Gardes, "aexecuter", espionne)
    yield vus
    assert not [a for a, _ in vus if a[0] == "git"]


@pytest.fixture
def projet(registre_vide, monkeypatch):
    monkeypatch.setenv("CIME_PROJET", str(registre_vide))  # `trouver_projet` exige le manifeste
    (registre_vide / ".orga" / "projet.toml").write_text('prefixe = "cc-essai"\n')
    registre.ouvrir(registre_vide).close()  # crée `reglages_projet`
    return registre_vide


def client(projet):
    deps = Dependances(
        instantane=lambda p: {}, horloge=lambda: T, prefixe=P,
        envoyer=[sys.executable, "-c", LANCEUR, "envoyer"],
    )
    return TestClient(creer_app(projet, deps, PORT), headers=HOTE)


def post(c, corps=None, origine=ORIGINE):
    r = c.post("/api/actions/fusions-auto", json=corps if corps is not None else {}, headers=origine)
    return r.json()


def reglages(projet):
    with closing(sqlite3.connect(projet / ".orga" / "etat" / "registre.sqlite")) as c:
        return c.execute(
            "SELECT valeur, auteur FROM reglages_projet WHERE cle = 'fusions_auto' ORDER BY id"
        ).fetchall()


def journal(projet):
    with closing(sqlite3.connect(projet / ".orga" / "etat" / "registre.sqlite")) as c:
        return [
            (a, ac, ci, r, json.loads(d))
            for a, ac, ci, r, d in c.execute(
                "SELECT auteur, action, cible, resultat, details FROM journal ORDER BY id")
        ]


def appels_fusions(lances):
    return [(a, kw) for a, kw in lances if "fusions-auto" in a]


def test_activer_puis_desactiver(projet, lances):
    c = client(projet)
    assert post(c, {"valeur": "active"}) == {"resultat": "ok", "message": "fusions automatiques activées"}
    assert reglages(projet) == [("active", "utilisateur")]
    assert fusions_auto.etat_courant(projet)["active"] is True

    assert post(c, {"valeur": "inactive"}) == {"resultat": "ok", "message": "fusions automatiques désactivées"}
    assert reglages(projet) == [("active", "utilisateur"), ("inactive", "utilisateur")]
    assert fusions_auto.etat_courant(projet)["active"] is False


def test_deja_actif_puis_deja_inactif(projet, lances):
    c = client(projet)
    assert post(c, {"valeur": "inactive"})["resultat"] == "refuse"  # déjà inactif au départ
    assert post(c, {"valeur": "inactive"})["message"] == "déjà inactif"
    assert post(c, {"valeur": "active"})["resultat"] == "ok"
    r = post(c, {"valeur": "active"})
    assert r["resultat"] == "refuse" and r["message"] == "déjà actif"
    assert reglages(projet) == [("active", "utilisateur")]  # le refus n'écrit rien


@pytest.mark.parametrize("corps", [{}, {"valeur": "oui"}, {"valeur": 1}, {"valeur": None},
                                   {"valeur": ""}, {"valeur": "active inactive"}])
def test_valeur_invalide_ne_lance_rien(projet, lances, corps):
    r = post(client(projet), corps)
    assert r["resultat"] == "refuse"
    assert appels_fusions(lances) == []
    assert reglages(projet) == []
    assert journal(projet)[-1][3] == "refuse"


def test_corps_non_json_ne_lance_rien(projet, lances):
    c = client(projet)
    r = c.post("/api/actions/fusions-auto", content=b"pas du json", headers=ORIGINE).json()
    assert r["resultat"] == "refuse"
    assert appels_fusions(lances) == [] and reglages(projet) == []


def test_journal_une_ligne_par_appel(projet, lances):
    c = client(projet)
    post(c, {"valeur": "active"})  # ok
    post(c, {"valeur": "active"})  # refusé : déjà actif
    post(c, {"valeur": "oui"})     # refusé : valeur invalide
    assert journal(projet) == [
        ("utilisateur", "fusions_auto", "projet", "ok",
         {"valeur": "active", "avant": "inactive", "reglage_id": 1}),
        ("utilisateur", "fusions_auto", "projet", "refuse",
         {"valeur": "active", "avant": "active", "reglage_id": None}),
        ("utilisateur", "fusions_auto", "projet", "refuse",
         {"valeur": "oui", "avant": None, "reglage_id": None}),
    ]


def test_processus_recoit_agent_utilisateur(projet, lances):
    post(client(projet), {"valeur": "active"})
    appels = appels_fusions(lances)
    assert len(appels) == 1
    argv, kw = appels[0]
    assert argv[-2:] == ["fusions-auto", "active"]
    assert kw["env"]["CIME_AGENT"] == "utilisateur"
    assert kw["env"]["CIME_PROJET"] == str(projet)
    assert [a for a, _ in lances if a[0] != sys.executable] == []  # aucune autre commande


def test_origine_etrangere_refusee(projet, lances):
    c = client(projet)
    r = c.post("/api/actions/fusions-auto", json={"valeur": "active"},
               headers={"origin": "http://evil.example"})
    assert r.status_code == 403
    assert reglages(projet) == [] and journal(projet) == [] and lances == []


def test_get_refuse(projet):
    assert client(projet).get("/api/actions/fusions-auto").status_code == 405


def test_echec_de_la_commande_donne_la_derniere_ligne(projet):
    echec = ("import sys; sys.stderr.write('Traceback (most recent call last):\\n  File \"x\"\\n"
             "ValueError: boom\\n'); sys.exit(1)")
    deps = Dependances(instantane=lambda p: {}, horloge=lambda: T, prefixe=P,
                       envoyer=[sys.executable, "-c", echec, "envoyer"])
    c = TestClient(creer_app(projet, deps, PORT), headers=HOTE)
    r = post(c, {"valeur": "active"})
    assert r == {"resultat": "erreur", "message": "ValueError: boom"}
    assert journal(projet)[-1][3] == "erreur: ValueError: boom"
