"""Route `/api/actions/plafond` : prérogative de l'utilisateur, journalisée.

Un faux script tient la place de `cime` (il rend le code, la sortie et l'erreur voulus) ; un seul
test lance la vraie commande, sous un dossier de configuration jetable.
"""
import json
import os
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from cime.fondation import plafond
from cime.hote import creer_app
from cime.hote.dependances import Dependances
from cime.hote.gardes import Gardes

T = datetime(2026, 10, 11, 9, 0, 0, tzinfo=timezone.utc)
PORT = 8768
HOTE = {"host": f"127.0.0.1:{PORT}"}
ORIGINE = {"origin": f"http://127.0.0.1:{PORT}"}
P = "cc-essai-plafond"
HORODATAGE = "2026-10-11T09:00:00+00:00"
SRC = Path(__file__).resolve().parents[2] / "src"
# sys.argv == ["-c", "plafond", V] : `main` lit `sys.argv[1:]`
LANCEUR = "import sys; from cime.cli import main; sys.exit(main())"
# les clés que le vrai `cime` exige d'un manifeste pour s'exécuter
MANIFESTE = (
    'nom = "essai"\nprefixe = "cc-essai"\nbranche_reference = "main"\n'
    'branche_equipe = "equipe/{equipe}"\nworktree_equipe = ".orga/worktrees/{equipe}"\n'
    'equipes_speciales = ["assistant"]\nmodele_assistant = "m"\nmodele_coordinateur = "m"\n'
)


def faux(code=0, sortie="", erreur=""):
    """Un faux `cime` : sys.argv == ["-c", "plafond", V]."""
    script = (f"import sys; sys.stdout.write({sortie!r}); sys.stderr.write({erreur!r}); sys.exit({code})")
    return [sys.executable, "-c", script, "envoyer"]


@pytest.fixture
def lances(monkeypatch):
    """Chaque lancement demandé à `Gardes` : (argv, options)."""
    vus = []
    orig = Gardes.aexecuter

    async def espionne(self, argv, **kw):
        vus.append((list(argv), kw))
        return await orig(self, argv, **kw)

    monkeypatch.setattr(Gardes, "aexecuter", espionne)
    return vus


@pytest.fixture
def projet(registre_vide, monkeypatch):
    monkeypatch.setenv("CIME_PROJET", str(registre_vide))
    (registre_vide / ".orga" / "projet.toml").write_text(MANIFESTE)
    return registre_vide


def client(projet, envoyer=None):
    envoyer = envoyer if envoyer is not None else faux(0, HORODATAGE + "\n")
    deps = Dependances(instantane=lambda p: {}, horloge=lambda: T, prefixe=P, envoyer=envoyer)
    return TestClient(creer_app(projet, deps, PORT), headers=HOTE)


def post(c, corps=None, origine=ORIGINE):
    r = c.post("/api/actions/plafond", json=corps if corps is not None else {}, headers=origine)
    return r.json()


def journal(projet):
    with closing(sqlite3.connect(projet / ".orga" / "etat" / "registre.sqlite")) as c:
        return [
            (a, ac, ci, r, json.loads(d))
            for a, ac, ci, r, d in c.execute(
                "SELECT auteur, action, cible, resultat, details FROM journal ORDER BY id")
        ]


def appels(lances):
    return [(a, kw) for a, kw in lances if "plafond" in a]


def ecrire_reglage(valeur):
    dossier = plafond.dossier_reglages()
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / plafond.FICHIER).write_text(f"{plafond.CLE} = {valeur}\n")


def test_valeur_valide(projet, lances):
    r = post(client(projet), {"valeur": 3})
    assert r == {"resultat": "ok", "message": "plafond de workers : 3"}
    assert journal(projet) == [
        ("utilisateur", "plafond", "machine", "ok",
         {"valeur": 3, "avant": plafond.DEFAUT, "horodatage": HORODATAGE}),
    ]
    (argv, kw), = appels(lances)
    assert argv[-2:] == ["plafond", "3"]
    assert kw["env"]["CIME_AGENT"] == "utilisateur"
    assert kw["env"]["CIME_PROJET"] == str(projet)
    assert kw["cwd"] == str(projet)


def test_defaut(projet, lances):
    r = post(client(projet), {"valeur": "defaut"})
    assert r == {"resultat": "ok", "message": f"plafond de workers : défaut ({plafond.DEFAUT})"}
    assert appels(lances)[0][0][-2:] == ["plafond", "--defaut"]
    assert journal(projet)[-1] == (
        "utilisateur", "plafond", "machine", "ok",
        {"valeur": "defaut", "avant": plafond.DEFAUT, "horodatage": HORODATAGE})


@pytest.mark.parametrize("deja", ["déjà 5", "déjà au défaut"])
def test_deja_refuse_et_journalise(projet, lances, deja):
    c = client(projet, faux(1, erreur=f"plafond : {deja}\n"))
    assert post(c, {"valeur": 5}) == {"resultat": "refuse", "message": deja}
    ligne = journal(projet)[-1]
    assert ligne[3] == "refuse" and ligne[4]["horodatage"] is None


@pytest.mark.parametrize("corps", [
    {}, {"valeur": 0}, {"valeur": 9}, {"valeur": -1}, {"valeur": True}, {"valeur": False},
    {"valeur": 3.5}, {"valeur": 3.0}, {"valeur": "abc"}, {"valeur": "3"}, {"valeur": None},
    {"valeur": ""}, {"valeur": "--defaut"}, {"valeur": [3]},
], ids=repr)
def test_valeur_invalide_ne_lance_rien(projet, lances, corps):
    r = post(client(projet), corps)
    assert r == {"resultat": "refuse", "message": "valeur attendue : un entier de 1 à 8, ou defaut"}
    assert appels(lances) == []
    assert journal(projet)[-1][3] == "refuse"
    assert journal(projet)[-1][4]["horodatage"] is None


def test_corps_non_json_ne_lance_rien(projet, lances):
    r = client(projet).post("/api/actions/plafond", content=b"pas du json", headers=ORIGINE).json()
    assert r["resultat"] == "refuse"
    assert appels(lances) == []


def test_code_2_refuse_avec_le_motif(projet, lances):
    c = client(projet, faux(2, erreur="plafond : 9 est hors de 1 à 8\n"))
    assert post(c, {"valeur": 4}) == {"resultat": "refuse", "message": "plafond : 9 est hors de 1 à 8"}
    assert journal(projet)[-1][3] == "refuse"


def test_autre_code_1_est_une_erreur(projet, lances):
    c = client(projet, faux(1, erreur="plafond : fichier illisible\nligne finale " + "x" * 300 + "\n"))
    r = post(c, {"valeur": 4})
    assert r["resultat"] == "erreur" and r["message"].startswith("ligne finale") and len(r["message"]) == 200


def test_autre_code_est_une_erreur(projet, lances):
    r = post(client(projet, faux(7)), {"valeur": 4})
    assert r == {"resultat": "erreur", "message": "code de sortie 7"}


def test_oserror_est_une_erreur(projet, lances, monkeypatch):
    def casse(*a, **kw):
        raise OSError("lancement impossible")

    monkeypatch.setattr("cime.hote.gardes.subprocess.run", casse)
    r = post(client(projet), {"valeur": 4})
    assert r == {"resultat": "erreur", "message": "lancement impossible"}
    assert journal(projet)[-1][3] == "erreur: lancement impossible"


def test_avant_est_le_plafond_de_la_machine(projet, lances):
    ecrire_reglage(5)
    assert post(client(projet), {"valeur": 2})["resultat"] == "ok"
    assert journal(projet)[-1][4] == {"valeur": 2, "avant": 5, "horodatage": HORODATAGE}


def test_origine_etrangere_refusee(projet, lances):
    r = client(projet).post("/api/actions/plafond", json={"valeur": 3},
                            headers={"origin": "http://evil.example"})
    assert r.status_code == 403 and journal(projet) == [] and lances == []


def test_get_refuse(projet):
    assert client(projet).get("/api/actions/plafond").status_code == 405


def test_de_bout_en_bout_avec_le_vrai_cime(projet, lances, monkeypatch):
    """Le vrai point d'entrée `cime.cli:main` de cette branche, sous un dossier de configuration jetable."""
    monkeypatch.setenv("PYTHONPATH", str(SRC))  # le sous-processus ne voit pas le `pythonpath` de pytest
    c = client(projet, [sys.executable, "-c", LANCEUR, "envoyer"])
    assert post(c, {"valeur": 6}) == {"resultat": "ok", "message": "plafond de workers : 6"}
    assert plafond.lire_machine() == (6, "fichier")
    assert post(c, {"valeur": 6})["message"] == "déjà 6"
    assert post(c, {"valeur": "defaut"})["resultat"] == "ok"
    assert plafond.lire_machine() == (plafond.DEFAUT, "defaut")
    assert post(c, {"valeur": "defaut"})["message"] == "déjà au défaut"
    lignes = journal(projet)
    assert [l[3] for l in lignes] == ["ok", "refuse", "ok", "refuse"]
    assert lignes[0][4]["avant"] == plafond.DEFAUT and lignes[2][4]["avant"] == 6
    assert lignes[0][4]["horodatage"] and lignes[2][4]["horodatage"]
    assert str(plafond.dossier_reglages()).startswith(os.environ["XDG_CONFIG_HOME"])
