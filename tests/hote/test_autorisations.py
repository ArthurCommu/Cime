"""Demandes d'autorisation : lecture du menu tmux sur des captures, registre, routes, touche envoyée, refus et fermeture spontanée."""
import copy
import json
import re
import sqlite3
import subprocess
import sys
import textwrap
import time
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import pytest
from conftest import SOCKET_ESSAI, tmux_essai
from starlette.testclient import TestClient

from cime.hote import actions_autorisation, creer_app
from cime.hote.autorisations import Registre, bloc_demande, menu_affiche
from cime.hote.dependances import Dependances
from cime.hote.gardes import Gardes

FIXTURES = Path(__file__).parent / "fixtures"
CAPTURES = FIXTURES / "captures-autorisation"
T = datetime(2026, 10, 7, 13, 4, 11, 123000, tzinfo=timezone.utc)
PREFIXE = f"cc-essai-{uuid.uuid4().hex[:6]}"  # unique par exécution
SESSION = f"{PREFIXE}-t5"
AGENT = "worker-essai"
PORT = 8766
ECHAP = "\x1b"


def capture(n):
    return next(CAPTURES.glob(f"{n}-*.ansi")).read_text()


# -- menu_affiche sur les captures réelles ---------------------------------
@pytest.mark.parametrize(
    "n,attendu", [(1, True), (2, False), (3, True), (4, False), (5, True), (6, False)]
)
def test_menu_affiche_captures_reelles(n, attendu):
    assert menu_affiche(capture(n)) is attendu


MENUS = FIXTURES / "menus"
# (capture, outil) : menus réels de Claude Code 2.1.x où la règle de sûreté s'applique
MENUS_SURS = ["bash", "write", "edit", "read-hors-dossier", "webfetch"]
# WebFetch : pas de pied `Esc to cancel`, mais dernière option `No … (esc)`
MENUS_NON_SURS = ["negatif-model", "webfetch-apres-escape", "bash-apres-1", "write-apres-1", "write-apres-escape",
                  "edit-apres-1", "webfetch-apres-1", "read-hors-dossier-apres-1"]


def menu_reel(nom):
    return (MENUS / f"{nom}.ansi").read_text()


@pytest.mark.parametrize("nom", MENUS_SURS)
def test_menu_affiche_menus_reels_de_chaque_outil(nom):
    assert menu_affiche(menu_reel(nom)) is True
    assert bloc_demande(menu_reel(nom))


@pytest.mark.parametrize("nom", MENUS_NON_SURS)
def test_menu_affiche_refuse_ce_qui_n_est_pas_un_menu_sur(nom):
    assert menu_affiche(menu_reel(nom)) is False
    assert bloc_demande(menu_reel(nom)) is None


def test_blocs_des_menus_reels_distinguent_les_outils():
    blocs = {nom: bloc_demande(menu_reel(nom)) for nom in MENUS_SURS}
    assert "touch" in blocs["bash"] and "hello" in blocs["write"]
    assert "bonjour" in blocs["edit"] and "Read" in blocs["read-hors-dossier"]
    assert len(set(blocs.values())) == len(blocs)


def test_menu_affiche_insensible_aux_codes_ansi():
    assert menu_affiche(
        REGLE + "\n Bash command\n\x1b[1m Do you want\x1b[0m\x1b[2m to proceed?\x1b[0m\n"
        "\x1b[36m ❯ 1. Yes\x1b[0m\n   2. No\n Esc to cancel\n"
    )


REGLE = "─" * 40
OPTIONS = " ❯ 1. Yes\n   2. Yes, always\n   3. No\n"


def ecran_de(titre=" Do you want to proceed?\n", options=OPTIONS, pied=" Esc to cancel · Tab to amend\n",
             avant=" Bash command\n touch x\n", apres="\n\n"):
    return f"{REGLE}\n{avant}{titre}{options}{pied}{apres}"


def test_menu_synthetique_de_reference_est_sur():
    assert menu_affiche(ecran_de())


def test_pied_alternatif_no_esc_est_sur():
    assert menu_affiche(ecran_de(options=" ❯ 1. Yes\n   2. No, and tell Claude (esc)\n", pied=""))


@pytest.mark.parametrize(
    "ecran",
    [
        pytest.param(ecran_de(options=" 1. Yes\n   2. No\n"), id="curseur-absent"),
        pytest.param(ecran_de(options="   1. Yes\n ❯ 2. No\n"), id="curseur-sur-2"),
        pytest.param(ecran_de(options=" ❯ 1. Yes, and more\n   2. No\n"), id="option-1-pas-exactement-Yes"),
        pytest.param(ecran_de(titre=" Do you want to proceed.\n"), id="titre-sans-point-d-interrogation"),
        pytest.param(ecran_de(titre=" Proceed?\n"), id="titre-autre-forme"),
        pytest.param(ecran_de(titre="", options=OPTIONS), id="titre-absent"),
        pytest.param(ecran_de(pied=""), id="pied-absent"),
        pytest.param(ecran_de(options=" ❯ 1. Yes\n   2. Oui, never (esc)\n   3. No\n", pied=""),
                     id="esc-sur-option-ne-commencant-pas-par-No"),
        pytest.param(ecran_de(options=" ❯ 1. Yes\n   2. No, merci (esc)\n   3. Autre\n", pied=""),
                     id="esc-sur-option-non-derniere"),
        pytest.param(ecran_de(options=" ❯ 1. Yes\n   2. No, merci (esc)\n", pied="", apres="\n texte\n"),
                     id="texte-apres-l-option-esc"),
        pytest.param(ecran_de(options=" ❯ 1. Yes\n   2. Nope (esc)\n", pied=""), id="Nope-n-est-pas-No"),
        pytest.param(ecran_de(pied=" Enter to confirm\n"), id="pied-autre"),
        pytest.param(ecran_de(apres="\n❯ quelque chose\n"), id="texte-apres-le-pied"),
        pytest.param(ecran_de(options=" ❯ 1. Yes\n" + "".join(f"   {i}. x\n" for i in range(2, 9))),
                     id="trop-d-options"),
        pytest.param(ecran_de(options=" ❯ 1. Yes\n   2. No\n" + "   suite\n" * 6), id="trop-de-lignes-de-suite"),
        pytest.param(ecran_de(options=" ❯ 1. Yes\n\n Autre chose\n 2. No\n")
                     .replace(" Autre chose\n", " Autre chose\n" * 5), id="texte-intercale"),
        pytest.param(f"Do you want to proceed?\n ❯ 1. Yes\n   2. No\n Esc to cancel\n", id="sans-regle-pleine"),
        pytest.param("", id="vide"),
    ],
)
def test_menu_affiche_cas_negatifs(ecran):
    assert menu_affiche(ecran) is False
    assert bloc_demande(ecran) is None


def test_titre_cite_dans_la_conversation_au_dessus_d_une_invite_vide():
    ecran = (
        "⏺ Le menu affiche « Do you want to proceed? » puis ❯ 1. Yes\n"
        " Do you want to proceed?\n ❯ 1. Yes\n   2. No\n Esc to cancel\n"
        f"{REGLE}\n❯ \n{REGLE}\n  ⏸ manual mode on\n"
    )
    assert menu_affiche(ecran) is False


def test_menu_ancien_au_dessus_de_la_derniere_regle_n_est_pas_sur():
    assert not menu_affiche(ecran_de(apres=f"\n{REGLE}\n❯ \n{REGLE}\n"))


def test_bloc_demande_distingue_les_commandes():
    b1, b3, b5 = (bloc_demande(capture(n)) for n in (1, 3, 5))
    assert "essai-1.txt" in b1 and "essai-3.txt" in b5
    assert len({b1, b3, b5}) == 3


# -- outillage -------------------------------------------------------------
FAUX_MENU = textwrap.dedent(
    """
    import sys, tty, time
    texte = open(sys.argv[1]).read()
    ignore = len(sys.argv) > 2 and sys.argv[2] == "ignore"
    tty.setraw(sys.stdin.fileno())
    def afficher():
        sys.stdout.write("\\x1b[2J\\x1b[H" + texte.replace("\\n", "\\r\\n"))
        sys.stdout.flush()
    afficher()
    while True:
        k = sys.stdin.read(1)
        if ignore:
            afficher()
            continue
        sys.stdout.write("\\x1b[2J\\x1b[HTOUCHE=" + repr(k) + "\\r\\n")
        sys.stdout.flush()
        time.sleep(60)
    """
)

FAUX_ENVOI = textwrap.dedent(
    """
    import json, os, sys
    with open(os.environ["FAUX_JOURNAL"], "a") as f:
        f.write(json.dumps({"argv": sys.argv[1:], "agent": os.environ.get("CIME_AGENT"),
                            "projet": os.environ.get("CIME_PROJET")}) + "\\n")
    sys.stderr.write("boum")
    sys.exit(int(os.environ.get("FAUX_CODE", "0")))
    """
)


def tmux(*args):
    return tmux_essai(*args)


def ecran():
    return tmux("capture-pane", "-p", "-t", SESSION).stdout


@pytest.fixture
def session(tmp_path):
    assert SESSION.startswith(PREFIXE + "-")
    faux = tmp_path / "faux_menu.py"
    faux.write_text(FAUX_MENU)
    menu = tmp_path / "menu.txt"
    menu.write_text(re.sub(r"\x1b\[[0-9;]*m", "", capture(1)))

    def lancer(mode="", texte=None):
        if texte is not None:
            menu.write_text(re.sub(r"\x1b\[[0-9;]*m|\x1b\].*?\x1b\\", "", texte))
        tmux("kill-session", "-t", SESSION)
        r = tmux("new-session", "-d", "-s", SESSION, "-x", "200", "-y", "50",
                 f"{sys.executable} {faux} {menu} {mode}")
        assert r.returncode == 0, r.stderr
        for _ in range(50):
            if ecran().strip():  # n'importe quel faux écran : les captures n'ont pas toutes un menu
                time.sleep(0.2)
                return
            time.sleep(0.1)
        raise AssertionError("faux menu non affiché")

    yield lancer
    tmux("kill-session", "-t", SESSION)


@pytest.fixture(autouse=True)
def attentes_courtes(monkeypatch):
    # les vraies attentes (1,5 s puis 1 s) ne prouvent rien de plus et ralentiraient la suite
    monkeypatch.setattr(actions_autorisation, "ATTENTE_INITIALE_S", 0.5)
    monkeypatch.setattr(actions_autorisation, "ATTENTE_ENTRE_S", 0.3)


@pytest.fixture(autouse=True)
def env_faux(monkeypatch, tmp_path):
    monkeypatch.setenv("FAUX_JOURNAL", str(tmp_path / "envois.jsonl"))
    monkeypatch.setenv("FAUX_CODE", "0")


def instantane(etat="attend_autorisation", demande_id=None):
    d = copy.deepcopy(json.loads((FIXTURES / "instantane-exemple.json").read_text()))
    d["projet"]["prefixe"] = PREFIXE
    d["agents"] = [{"id": AGENT, "session_tmux": SESSION, "etat": etat}]
    d["attentes_utilisateur"] = (
        [{"id": f"perm-{demande_id}", "nature": "autorisation", "agent": AGENT, "titre": "Bash"}]
        if demande_id
        else []
    )
    d["genere_a"] = "2026-10-07T13:04:11.000Z"  # avant T : ne contredit pas les demandes
    return d


@pytest.fixture
def monde(registre_vide, tmp_path):
    faux = tmp_path / "faux_envoi.py"
    faux.write_text(FAUX_ENVOI)
    envois = tmp_path / "envois.jsonl"

    class M:
        projet = registre_vide

        @staticmethod
        def app(inst=None, envoyer=None):
            inst = inst or instantane()
            deps = Dependances(
                instantane=lambda p: inst, horloge=lambda: T, intervalle_s=0.2,
                envoyer=envoyer or [sys.executable, str(faux)], prefixe=PREFIXE,
                tmux_socket=SOCKET_ESSAI,
            )
            return creer_app(registre_vide, deps, PORT)

        @staticmethod
        def lignes():
            with closing(sqlite3.connect(registre_vide / ".orga/etat/registre.sqlite")) as c:
                return c.execute(
                    "SELECT auteur, action, cible, resultat FROM journal ORDER BY id"
                ).fetchall()

        @staticmethod
        def envoyes():
            if not envois.exists():
                return []
            return [json.loads(l) for l in envois.read_text().splitlines()]

    return M


def client(app):
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}")


def deposer(c, session=SESSION):
    demande_id = str(uuid.uuid4())
    r = c.post("/api/permissions", json={
        "demande_id": demande_id, "agent": AGENT, "session_tmux": session,
        "tool_name": "Bash", "tool_input": {"command": "touch essai-1.txt"}})
    assert r.status_code == 200 and r.json() == {"decision": "en_attente"}
    return demande_id


@pytest.fixture
def espion(monkeypatch):
    appels = []
    original = Gardes.aexecuter

    async def aexecuter(self, argv, **kw):
        appels.append(list(argv))
        return await original(self, argv, **kw)

    monkeypatch.setattr(Gardes, "aexecuter", aexecuter)
    return appels


# -- routes de permission --------------------------------------------------
def test_deposer_sans_route_de_lecture(monde):
    with client(monde.app()) as c:
        d = deposer(c)
        assert c.get(f"/api/permissions/{d}").status_code in (404, 405)
        for manquant in ("agent", "session_tmux"):
            corps = {"demande_id": str(uuid.uuid4()), "agent": "a", "session_tmux": "s", "tool_name": "t"}
            del corps[manquant]
            assert c.post("/api/permissions", json=corps).status_code == 400
        mauvais = {"demande_id": "pas-un-uuid", "agent": "a", "session_tmux": "s", "tool_name": "t"}
        assert c.post("/api/permissions", json=mauvais).status_code == 400
        assert c.post("/api/permissions", content="{").status_code == 400
    assert monde.lignes() == []


def test_corps_invalide_des_actions(monde):
    with client(monde.app()) as c:
        assert c.post("/api/actions/autoriser", json={}).status_code == 400


# -- tmux réel -------------------------------------------------------------
@pytest.mark.tmux_reel
def test_autoriser_envoie_1(monde, session):
    session()
    with client(monde.app()) as c:
        d = deposer(c)
        r = c.post("/api/actions/autoriser", json={"demande_id": d}).json()
        assert r["resultat"] == "ok", r
        assert "TOUCHE='1'" in ecran()
        r2 = c.post("/api/actions/refuser", json={"demande_id": d}).json()
        assert r2 == {"resultat": "refuse", "message": "déjà répondu"}
    assert monde.lignes() == [("utilisateur", "autoriser", f"perm-{d}", "ok"), ("utilisateur", "refuser", f"perm-{d}", "refuse")]
    assert monde.envoyes() == []


@pytest.mark.parametrize("nom", MENUS_SURS)
@pytest.mark.tmux_reel
def test_autoriser_envoie_1_sur_le_menu_reel_de_chaque_outil(monde, session, nom):
    session(texte=menu_reel(nom))
    with client(monde.app()) as c:
        d = deposer(c)
        r = c.post("/api/actions/autoriser", json={"demande_id": d}).json()
        assert r["resultat"] == "ok", r
        assert "TOUCHE='1'" in ecran()


@pytest.mark.parametrize("nom", ["negatif-model", "webfetch-apres-escape"])
@pytest.mark.tmux_reel
def test_autoriser_n_envoie_aucune_touche_hors_regle(monde, session, nom):
    session(texte=menu_reel(nom))
    with client(monde.app()) as c:
        d = deposer(c)
        r = c.post("/api/actions/autoriser", json={"demande_id": d}).json()
        assert r["resultat"] == "refuse", r
        assert "TOUCHE=" not in ecran()


@pytest.mark.tmux_reel
def test_refuser_envoie_echap_et_previent_assistant(monde, session):
    session()
    with client(monde.app()) as c:
        d = deposer(c)
        r = c.post("/api/actions/refuser", json={"demande_id": d}).json()
        assert r["resultat"] == "ok", r
        assert f"TOUCHE={ECHAP!r}" in ecran()
    (envoi,) = monde.envoyes()
    assert envoi["argv"] == [
        "--a", "assistant", "--nature", "compte_rendu",
        f"L'utilisateur a refusé Bash à {AGENT} ; l'agent est interrompu et attend une consigne",
    ]
    assert envoi["agent"] == "utilisateur"
    assert envoi["projet"] == str(monde.projet)
    assert monde.lignes() == [("utilisateur", "refuser", f"perm-{d}", "ok")]


@pytest.mark.tmux_reel
def test_refus_envoi_en_echec(monde, session, monkeypatch):
    session()
    monkeypatch.setenv("FAUX_CODE", "1")
    with client(monde.app()) as c:
        d = deposer(c)
        r = c.post("/api/actions/refuser", json={"demande_id": d}).json()
        message = "refus transmis à l'agent, mais l'Assistant n'a pas été prévenu : boum"
        assert r == {"resultat": "erreur", "message": message}
        assert f"TOUCHE={ECHAP!r}" in ecran()  # la touche est partie, jamais renvoyée
    assert monde.lignes() == [("utilisateur", "refuser", f"perm-{d}", "erreur: " + message)]


@pytest.mark.tmux_reel
def test_refus_commande_envoi_introuvable(monde, session):
    session()
    with client(monde.app(envoyer=["/nulle/part/cime", "envoyer"])) as c:
        d = deposer(c)
        r = c.post("/api/actions/refuser", json={"demande_id": d}).json()
    assert r["resultat"] == "erreur" and "Assistant n'a pas été prévenu" in r["message"]


@pytest.mark.tmux_reel
def test_menu_absent_aucune_touche(monde, session, espion):
    session()
    tmux("send-keys", "-t", SESSION, "1")  # le faux menu efface l'écran
    for _ in range(30):
        if "Do you want" not in ecran():
            break
        time.sleep(0.1)
    espion.clear()
    with client(monde.app()) as c:
        d = deposer(c)
        r = c.post("/api/actions/autoriser", json={"demande_id": d}).json()
    assert r["resultat"] == "refuse" and "aucune demande affichée" in r["message"]
    assert espion and all(a[1] != "send-keys" for a in espion)
    assert monde.lignes() == [("utilisateur", "autoriser", f"perm-{d}", "refuse")]


@pytest.mark.tmux_reel
def test_touche_sans_effet(monde, session):
    session("ignore")
    with client(monde.app()) as c:
        d = deposer(c)
        r = c.post("/api/actions/autoriser", json={"demande_id": d}).json()
        message = "la touche n'a pas été prise en compte"
        assert r == {"resultat": "erreur", "message": message}
    assert monde.lignes() == [("utilisateur", "autoriser", f"perm-{d}", "erreur: " + message)]


@pytest.mark.tmux_reel
def test_hote_redemarre_session_retrouvee_par_l_instantane(monde, session):
    session()
    d = str(uuid.uuid4())
    with client(monde.app(instantane(demande_id=d))) as c:  # registre mémoire vide
        r = c.post("/api/actions/autoriser", json={"demande_id": d}).json()
        assert r["resultat"] == "ok", r
        assert "TOUCHE='1'" in ecran()


# -- refus sans tmux -------------------------------------------------------
def test_demande_inconnue(monde):
    d = str(uuid.uuid4())
    with client(monde.app()) as c:
        r = c.post("/api/actions/autoriser", json={"demande_id": d}).json()
    assert r == {"resultat": "refuse", "message": "demande inconnue"}
    assert monde.lignes() == [("utilisateur", "autoriser", f"perm-{d}", "refuse")]


def test_session_hors_prefixe_refusee(monde, espion):
    with client(monde.app()) as c:
        d = deposer(c, session="cc-assistant")
        r = c.post("/api/actions/autoriser", json={"demande_id": d}).json()
    assert r["resultat"] == "refuse" and "hors du projet" in r["message"]
    assert not any(a[1] == "send-keys" for a in espion)
    assert monde.lignes() == [("utilisateur", "autoriser", f"perm-{d}", "refuse")]


# -- fermeture spontanée ---------------------------------------------------
def test_fermeture_spontanee():
    r = Registre()
    r.enregistrer("a", AGENT, SESSION, "Bash", {}, T)
    r.enregistrer("b", AGENT, SESSION, "Bash", {}, T)
    r.demandes["b"]["decision"] = "allow"
    r.observer(instantane(etat="travaille"))  # antérieur à la demande : ne la contredit pas
    assert not r.demandes["a"]["close"]
    recent = instantane(etat="attend_autorisation")
    recent["genere_a"] = "2026-10-07T13:05:00.000Z"
    r.observer(recent)
    assert not r.demandes["a"]["close"]
    recent["agents"][0]["etat"] = "travaille"
    r.observer(recent)
    assert r.demandes["a"]["close"] and not r.demandes["b"]["close"]


def test_demande_fermee_ne_se_decide_plus(monde):
    inst = instantane(etat="travaille")
    inst["genere_a"] = "2026-10-07T13:05:00.000Z"
    with client(monde.app(inst)) as c:
        d = deposer(c)
        demandes = c.app.state.contexte._registre_autorisations.demandes
        for _ in range(30):
            if demandes[d]["close"]:
                break
            time.sleep(0.1)
        assert demandes[d]["close"]
        r = c.post("/api/actions/autoriser", json={"demande_id": d}).json()
    assert r == {"resultat": "refuse", "message": "déjà répondu"}


# -- corps : attente_id et/ou demande_id -----------------------------------
def _details(monde):
    with closing(sqlite3.connect(monde.projet / ".orga/etat/registre.sqlite")) as c:
        return [json.loads(x[0]) for x in c.execute("SELECT details FROM journal ORDER BY id")]


@pytest.mark.tmux_reel
def test_attente_id_seul(monde, session):
    session()
    with client(monde.app()) as c:
        d = deposer(c)
        r = c.post("/api/actions/autoriser", json={"attente_id": f"perm-{d}"}).json()
        assert r["resultat"] == "ok", r
    assert "TOUCHE='1'" in ecran()
    assert monde.lignes() == [("utilisateur", "autoriser", f"perm-{d}", "ok")]


@pytest.mark.tmux_reel
def test_demande_id_seul_journalise_en_perm(monde, session):
    session()
    with client(monde.app()) as c:
        d = deposer(c)
        assert c.post("/api/actions/refuser", json={"demande_id": d}).json()["resultat"] == "ok"
    assert monde.lignes() == [("utilisateur", "refuser", f"perm-{d}", "ok")]


@pytest.mark.tmux_reel
def test_attente_id_et_demande_id_concordants(monde, session):
    session()
    with client(monde.app()) as c:
        d = deposer(c)
        r = c.post("/api/actions/autoriser", json={"attente_id": f"perm-{d}", "demande_id": d}).json()
        assert r["resultat"] == "ok", r
    assert monde.lignes() == [("utilisateur", "autoriser", f"perm-{d}", "ok")]


def test_attente_id_et_demande_id_discordants(monde, espion):
    with client(monde.app()) as c:
        d, autre = deposer(c), deposer(c)
        espion.clear()
        r = c.post("/api/actions/autoriser", json={"attente_id": f"perm-{d}", "demande_id": autre}).json()
    assert r["resultat"] == "refuse"
    assert not any(a[1] == "send-keys" for a in espion)
    assert monde.lignes() == [("utilisateur", "autoriser", f"perm-{d}", "refuse")]


@pytest.mark.parametrize("action", ["autoriser", "refuser"])
def test_attente_id_message_refusee(monde, espion, action):
    with client(monde.app()) as c:
        r = c.post(f"/api/actions/{action}", json={"attente_id": "msg-12"}).json()
    # « refuser » d'un msg-<n> est le refus d'un accord de fusion/chantier : sans
    # décision de cette nature, c'est refusé ; « autoriser » ne connaît que les demandes perm-.
    attendu = ("msg-12 n'est pas une décision en cours" if action == "refuser"
               else "ce n'est pas une demande d'autorisation")
    assert r == {"resultat": "refuse", "message": attendu}
    assert espion == []
    assert monde.lignes() == [("utilisateur", action, "msg-12", "refuse")]


def test_details_autoriser_refuser(monde):
    with client(monde.app()) as c:
        d = deposer(c, session="cc-assistant")  # refusée avant toute touche : seul le journal nous importe
        c.post("/api/actions/autoriser", json={"attente_id": f"perm-{d}"})
        inconnue = str(uuid.uuid4())
        c.post("/api/actions/refuser", json={"demande_id": inconnue})
        d2 = str(uuid.uuid4())
        c.post("/api/permissions", json={
            "demande_id": d2, "agent": AGENT, "session_tmux": "cc-assistant", "tool_name": "Write",
            "tool_input": {"file_path": "src/" + "x" * 300}})
        c.post("/api/actions/refuser", json={"demande_id": d2})
    # `classe` (corps du signalement, null sans signalement) et `mode_autonome`
    sans = {"classe": None, "mode_autonome": False}
    assert _details(monde) == [
        {"agent": AGENT, "outil": "Bash", "commande": "touch essai-1.txt", **sans},
        {"agent": None, "outil": None, "commande": None, **sans},
        {"agent": AGENT, "outil": "Write", "chemin": ("src/" + "x" * 300)[:200], **sans},
    ]
