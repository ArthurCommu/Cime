"""La voie « hote » du Veilleur, `GET /api/flux?depuis=`, et les
signalements de contexte du rafraîchisseur. Registre fabriqué dans `tmp_path` ; faux notifieur."""
import asyncio
import functools
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest
from starlette.testclient import TestClient

from cime.fondation import registre
from cime.hote import creer_app
from cime.hote.dependances import Dependances
from cime.hote.notifications import Veilleur
from cime.hote.rafraichisseur import signaler_contextes
from cime.signaux import commandes

T0 = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


def asynchrone(f):
    @functools.wraps(f)
    def enveloppe(*a, **k):
        asyncio.run(f(*a, **k))

    return enveloppe


class Faux:
    def __init__(self, erreur=None, leve=False):
        self.envois, self.derniere_erreur, self.leve = [], erreur, leve

    async def notifier(self, titre, texte):
        self.envois.append((titre, texte))
        if self.leve:
            raise RuntimeError("boum")


class Horloge:
    def __init__(self):
        self.t = T0

    def __call__(self):
        return self.t


async def _pas_de_sommeil(_):
    await asyncio.Event().wait()


def veilleur(projet, faux=None):
    faux = faux or Faux()
    return Veilleur(faux, Horloge(), dormir=_pas_de_sommeil, projet=projet), faux


@pytest.fixture
def projet(tmp_path):
    (tmp_path / ".orga" / "teams" / "x").mkdir(parents=True)
    (tmp_path / ".orga" / "projet.toml").write_text(
        'nom = "Essai"\nprefixe = "essai"\nbranche_reference = "main"\n'
        'branche_equipe = "equipe/{equipe}"\nworktree_equipe = "../{depot}-{equipe}"\n'
        'equipes_speciales = ["assistant"]\nmodele_assistant = "m"\nmodele_coordinateur = "m"\n')
    registre.ouvrir(tmp_path).close()
    return tmp_path


def decision(projet, objet="fusion:signaux:abc1234"):
    conn = registre.ouvrir(projet)
    try:
        return commandes.inscrire(conn, de="assistant", a="utilisateur", nature="decision_utilisateur",
                                  resume="Fusionner ?", objet=objet)
    finally:
        conn.close()


def attente(ident, nature="decision", **champs):
    return {"id": f"msg-{ident}", "message_id": ident, "objet": None, "nature": nature,
            "titre": f"titre {ident}", "agent": "assistant", "depuis": "2026-10-09T11:00:00Z", **champs}


def lignes(projet, requete, params=()):
    with closing(sqlite3.connect(projet / ".orga" / "etat" / "registre.sqlite")) as c:
        return c.execute(requete, params).fetchall()


def livraisons(projet, ident):
    return lignes(projet, "SELECT t.auteur, t.preuve, c.voie, c.a FROM transitions t"
                          " LEFT JOIN courriers c ON c.id = t.courrier_id"
                          " WHERE t.message_id = ? AND t.etat = 'livre'", (ident,))


# --- la voie hote -----------------------------------------------------------------------------

@asynchrone
async def test_notification_reussie_ecrit_livre_voie_hote(projet):
    ident = decision(projet)
    v, faux = veilleur(projet)
    await v.observer({"projet": {"nom": "p"}, "attentes_utilisateur": [attente(ident)]})
    assert len(faux.envois) == 1
    [(auteur, preuve, voie, a)] = livraisons(projet, ident)
    assert (auteur, json.loads(preuve), voie, a) == ("cime", {"notif": True}, "hote", "utilisateur")
    assert lignes(projet, "SELECT etat FROM transitions WHERE message_id = ? ORDER BY id", (ident,)) == [
        ("inscrit",), ("livre",)]


@asynchrone
async def test_une_seule_livraison_par_message_meme_apres_redemarrage_de_l_hote(projet):
    ident = decision(projet)
    inst = {"projet": {"nom": "p"}, "attentes_utilisateur": [attente(ident)]}
    v, faux = veilleur(projet)
    await v.observer(inst)
    await v.observer(inst)
    v2, faux2 = veilleur(projet)          # l'hôte a redémarré : mémoire vide
    await v2.observer(inst)
    assert len(livraisons(projet, ident)) == 1
    assert len(faux.envois) == 1 and faux2.envois == []   # et il ne renotifie pas


@asynchrone
@pytest.mark.parametrize("faux", [Faux(leve=True), Faux(erreur="osascript refusé")])
async def test_notification_en_echec_n_ecrit_rien(projet, faux):
    ident = decision(projet)
    v, _ = veilleur(projet, faux)
    await v.observer({"projet": {"nom": "p"}, "attentes_utilisateur": [attente(ident)]})
    assert len(faux.envois) == 1
    assert livraisons(projet, ident) == []


@asynchrone
async def test_lot_de_notifications_marque_chaque_message_et_ignore_les_autorisations(projet):
    a, b = decision(projet), decision(projet, objet="chantier:signaux:5")
    v, faux = veilleur(projet)
    perm = {"id": "perm-d41", "message_id": None, "nature": "autorisation", "titre": "Bash", "depuis": "x"}
    await v.observer({"projet": {"nom": "p"}, "attentes_utilisateur": [attente(a), attente(b), perm]})
    assert len(faux.envois) == 1 and "3 choses" in faux.envois[0][1]
    assert len(livraisons(projet, a)) == len(livraisons(projet, b)) == 1
    assert lignes(projet, "SELECT count(*) FROM transitions WHERE etat = 'livre'") == [(2,)]


@asynchrone
async def test_rapport_non_notifiable_n_est_pas_marque_livre(projet):
    conn = registre.ouvrir(projet)
    ident = commandes.inscrire(conn, de="assistant", a="utilisateur", nature="rapport_utilisateur", resume="Nuit calme")
    conn.close()
    v, faux = veilleur(projet)
    await v.observer({"projet": {"nom": "p"}, "attentes_utilisateur": [attente(ident, "rapport")]})
    assert faux.envois == [] and livraisons(projet, ident) == []


# --- GET /api/flux?depuis= --------------------------------------------------------------------

@pytest.fixture
def client(projet):
    deps = Dependances(instantane=lambda p: {}, intervalle_s=60)
    return TestClient(creer_app(projet, deps, 8766), base_url="http://127.0.0.1:8766")


def test_flux_ne_rend_que_les_transitions_nouvelles(projet, client):
    a = decision(projet)
    d0 = client.get("/api/flux?depuis=0").json()
    assert [t["etat"] for t in d0["transitions"]] == ["inscrit"] and d0["transitions"][0]["message_id"] == a
    assert d0["dernier_id"] == d0["transitions"][0]["id"]
    from cime.hote.notifications import marquer_livre
    assert marquer_livre(projet, a) is True and marquer_livre(projet, a) is False
    d1 = client.get(f"/api/flux?depuis={d0['dernier_id']}").json()
    assert [(t["etat"], t["voie"], t["auteur"]) for t in d1["transitions"]] == [("livre", "hote", "cime")]
    d2 = client.get(f"/api/flux?depuis={d1['dernier_id']}").json()
    assert d2 == {"transitions": [], "dernier_id": d1["dernier_id"]}


def test_flux_sans_valeur_rend_les_200_dernieres_requetes(projet, client):
    for _ in range(3):
        decision(projet)
    d = client.get("/api/flux?depuis=").json()
    assert [r["id"] for r in d["requetes"]] == [1, 2, 3] and d["dernier_id"] == 3
    assert d["requetes"][0]["transitions"][0]["etat"] == "inscrit"


def test_flux_depuis_invalide_ou_registre_absent(tmp_path):
    deps = Dependances(instantane=lambda p: {}, intervalle_s=60)
    c = TestClient(creer_app(tmp_path, deps, 8766), base_url="http://127.0.0.1:8766")
    assert c.get("/api/flux?depuis=abc").status_code == 400
    assert c.get("/api/flux?depuis=0").status_code == 503


# --- signalements de contexte -------------------------------------------------------------

def alarme(type_, agent, depuis="2026-10-09T10:00:00.000Z"):
    return {"id": f"{type_}:{agent}:x", "type": type_, "agents": [agent], "depuis": depuis}


def signalements(projet):
    return lignes(projet, "SELECT de, a, objet, nature FROM messages WHERE objet LIKE 'contexte:%' ORDER BY id")


def test_contexte_inscrit_une_fois_pour_le_superieur(projet):
    inst = {"alarmes": [alarme("contexte_au_repos", "worker-x-t1"), alarme("contexte_plein", "assistant"),
                        alarme("fige", "coord-x")]}
    assert signaler_contextes(projet, inst) == 2
    assert signalements(projet) == [("cime", "coord-x", "contexte:worker-x-t1", "signalement"),
                                    ("cime", "utilisateur", "contexte:assistant", "signalement")]
    assert signaler_contextes(projet, inst) == 0          # idempotent
    assert len(signalements(projet)) == 2


def test_contexte_nouvel_episode_signale_de_nouveau_et_sans_registre_rien(projet, tmp_path):
    signaler_contextes(projet, {"alarmes": [alarme("contexte_au_repos", "coord-x")]})
    signaler_contextes(projet, {"alarmes": [alarme("contexte_au_repos", "coord-x", depuis="2026-10-09T11:00:00.000Z")]})
    assert [s[1] for s in signalements(projet)] == ["assistant", "assistant"]
    vide = tmp_path / "ailleurs"
    vide.mkdir()
    assert signaler_contextes(vide, {"alarmes": [alarme("contexte_plein", "coord-x")]}) == 0
    assert not (vide / ".orga").exists()


def test_l_app_donne_son_projet_au_veilleur(projet):
    deps = Dependances(instantane=lambda p: {}, notifieur=Faux(), intervalle_s=60)
    app = creer_app(projet, deps, 8766)
    veilleurs = [o.__self__ for o in app.state.contexte.rafraichisseur._observateurs
                 if isinstance(getattr(o, "__self__", None), Veilleur)]
    assert [v.projet for v in veilleurs] == [projet]
