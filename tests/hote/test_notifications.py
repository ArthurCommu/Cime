"""Notifications macOS : regroupement des attentes de l'utilisateur, reprise après redémarrage, échecs sans conséquence."""
import asyncio
import functools
import time
from datetime import datetime, timedelta, timezone

from starlette.testclient import TestClient

from cime.hote import creer_app
from cime.hote.dependances import Dependances
from cime.hote.gardes import Gardes
from cime.hote.notifications import NotifieurMac, Veilleur, nettoyer

def asynchrone(f):
    @functools.wraps(f)
    def enveloppe():
        asyncio.run(f())

    return enveloppe


T0 = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


class Horloge:
    def __init__(self):
        self.t = T0

    def __call__(self):
        return self.t

    def avance(self, s):
        self.t = T0 + timedelta(seconds=s)


class Faux:
    def __init__(self, erreur=False):
        self.envois = []
        self.erreur = erreur

    async def notifier(self, titre, texte):
        self.envois.append((titre, texte))
        if self.erreur:
            raise RuntimeError("boum")


def att(i, nature="decision", depuis="2026-10-07T10:00:00Z"):
    return {"id": i, "nature": nature, "titre": f"titre {i}", "agent": "a", "depuis": depuis}


def inst(*attentes):
    return {"projet": {"nom": "proj"}, "attentes_utilisateur": list(attentes)}


def veilleur(faux=None):
    h = Horloge()
    f = faux or Faux()

    async def pas_de_sommeil(_):
        await asyncio.Event().wait()  # la reprise se fait par observer()

    return Veilleur(f, h, dormir=pas_de_sommeil), f, h


@asynchrone
async def test_regroupement_sur_une_minute():
    v, f, h = veilleur()
    await v.observer(inst(att("a")))
    assert f.envois == [("proj", "titre a")]
    h.avance(10)
    await v.observer(inst(att("a"), att("b", depuis="2026-10-07T11:00:00Z")))
    h.avance(20)
    await v.observer(inst(att("a"), att("b", depuis="2026-10-07T11:00:00Z"), att("c", "cloture", "2026-10-07T09:00:00Z")))
    assert len(f.envois) == 1
    h.avance(60)
    await v.observer(inst(att("a"), att("b"), att("c")))
    assert f.envois[1] == ("proj", "2 choses t'attendent : titre c")
    assert len(f.envois) == 2
    await v.observer(inst(att("a"), att("b"), att("c")))
    assert len(f.envois) == 2


@asynchrone
async def test_rapport_seul_et_id_revu():
    v, f, h = veilleur()
    await v.observer(inst(att("r", "rapport")))
    assert f.envois == []
    await v.observer(inst(att("a")))
    h.avance(120)
    await v.observer(inst(att("a")))
    assert len(f.envois) == 1


@asynchrone
async def test_attente_disparue_retiree():
    v, f, h = veilleur()
    await v.observer(inst(att("a")))
    h.avance(5)
    await v.observer(inst(att("b")))
    h.avance(10)
    await v.observer(inst())
    h.avance(70)
    await v.observer(inst())
    assert len(f.envois) == 1


@asynchrone
async def test_premier_instantane_regroupe_et_null():
    v, f, _ = veilleur()
    await v.observer({"projet": {"nom": "p"}, "attentes_utilisateur": None})
    assert f.envois == []
    await v.observer(inst(att("a"), att("b"), att("r", "rapport")))
    assert len(f.envois) == 1 and f.envois[0][1].startswith("2 choses")


@asynchrone
async def test_tache_programmee_envoie_apres_delai():
    h = Horloge()
    f = Faux()
    v = Veilleur(f, h, dormir=lambda d: asyncio.sleep(0))
    await v.observer(inst(att("a")))
    h.avance(1)
    await v.observer(inst(att("a"), att("b")))
    assert len(f.envois) == 1
    h.avance(61)
    await asyncio.sleep(0.05)
    assert len(f.envois) == 2


@asynchrone
async def test_notifieur_qui_leve_ne_propage_pas():
    v, f, _ = veilleur(Faux(erreur=True))
    await v.observer(inst(att("a")))
    assert len(f.envois) == 1


def test_nettoyer():
    assert nettoyer('a"b\\c\nd') == "a”bc d"
    t = nettoyer('x"\\\n' + "y" * 500)
    assert '"' not in t and "\\" not in t and "\n" not in t and len(t) == 200


@asynchrone
async def test_notifieur_mac_argv_et_gardes():
    appels = []

    class Espion:
        async def aexecuter(self, argv, **kw):
            appels.append(argv)

    await NotifieurMac(Espion()).notifier('Pro"j', 'dis "oui"\\\nou non')
    argv = appels[0]
    assert argv == [
        "osascript", "-e",
        'display notification "dis ”oui” ou non" with title "Pro”j"',
    ]
    Gardes("cc-essai").autoriser_commande(argv)


@asynchrone
async def test_notifieur_mac_retient_les_erreurs():
    class Casse:
        async def aexecuter(self, argv, **kw):
            raise RuntimeError("non")

    n = NotifieurMac(Casse())
    await n.notifier("t", "x")
    assert "non" in n.derniere_erreur
    # Gardes réelles, commande interdite : retenue aussi (on ne lance rien)
    class Refuse:
        def aexecuter(self, argv, **kw):
            Gardes("cc-essai").autoriser_commande(["rm"])

    n2 = NotifieurMac(Refuse())
    await n2.notifier("t", "x")
    assert n2.derniere_erreur


def test_hote_continue_si_notifieur_leve(registre_vide):
    f = Faux(erreur=True)
    d = Dependances(
        instantane=lambda p: inst(att("a")), intervalle_s=0.05, prefixe="cc-essai", notifieur=f
    )
    with TestClient(creer_app(registre_vide, d, 8765), base_url="http://127.0.0.1:8765") as c:
        fin = time.monotonic() + 3
        while not f.envois and time.monotonic() < fin:
            time.sleep(0.01)
        assert f.envois
        r = c.get("/api/etat", headers={"Host": "127.0.0.1:8765"})
        assert r.status_code == 200
