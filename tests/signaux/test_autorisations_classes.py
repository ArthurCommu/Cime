"""Mode autonome : les autorisations par classe.

Routage du hook `PermissionRequest`, échelles par classe et par mode (le mode est relu à chaque
échéance), qui peut accorder, annonce `autorisation-auto:` inscrite par `cime accorder`.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from aide import cime, fabriquer_projet, lignes
from cime.fondation import fusions_auto
from cime.fondation.nom import VAR_PROJET
from cime.fondation.registre import inscrire_evenement, ouvrir
from cime.signaux import commandes, echeances, hooks, relances, signalements_utilisateur

WORKER, COORD, ASSISTANT, UTILISATEUR = "worker-x-t", "coord-x", "assistant", "utilisateur"
LIBRE = {"tool_name": "Bash", "tool_input": {"command": "ls src"}}
RESERVE = {"tool_name": "Edit", "tool_input": {"file_path": "/etc/hosts"}}
AUTONOME = {"tool_name": "Bash", "tool_input": {"command": "uv add httpx"}}


@pytest.fixture
def projet(tmp_path, monkeypatch):
    racine = fabriquer_projet(tmp_path / "depot")
    (racine / "src").mkdir()
    monkeypatch.setenv(VAR_PROJET, str(racine))
    mode(monkeypatch, False)
    return racine


def mode(monkeypatch, actif, suspendue=False):
    """Le mode autonome tel que `fusions_auto.etat_courant` le lit (relu à chaque appel)."""
    etat = {"active": actif, "suspendue": suspendue}
    monkeypatch.setattr(fusions_auto, "etat_courant", lambda projet: dict(etat))
    return etat


def demander(projet, agent, entree, demande_id="d1"):
    """Le hook `PermissionRequest` : l'événement puis le signalement (comme `hook.py`)."""
    conn = ouvrir(projet)
    try:
        inscrire_evenement(conn, agent=agent, session_id="s", evenement="PermissionRequest",
                           details={"demande_id": demande_id, "tool_name": entree["tool_name"]})
        hooks.sur_permission_request(conn, projet, agent, {**entree, "cwd": str(projet)},
                                     {"demande_id": demande_id})
    finally:
        conn.close()
    return signalement(projet, demande_id)


def signalement(projet, demande_id="d1"):
    ids = lignes(projet, "SELECT id FROM messages WHERE objet = ? ORDER BY id",
                 (f"autorisation:{demande_id}",))
    return ids[0][0] if ids else None


def messages(projet, objet_like="%"):
    return lignes(projet, "SELECT de, a, nature, objet FROM messages WHERE objet LIKE ? ORDER BY id",
                  (objet_like,))


def obligation(projet, message_id):
    return lignes(projet, "SELECT debiteur, attendu, etat FROM obligations WHERE message_id = ?",
                  (message_id,))


def corps(projet, message_id):
    return json.loads(lignes(projet, "SELECT corps FROM messages WHERE id = ?", (message_id,))[0][0])


# --- routage (hook) ----------------------------------------------------------------------------

def test_libre_d_un_worker_va_a_son_coordinateur_pas_a_l_assistant(projet):
    s = demander(projet, WORKER, LIBRE)
    assert messages(projet) == [("cime", COORD, "signalement", "autorisation:d1")]
    assert obligation(projet, s) == [(COORD, "decision", "ouverte")]
    assert corps(projet, s) == {"outil": "Bash", "cible": "ls src", "classe": "libre", "theme": "projet"}
    assert lignes(projet, "SELECT resume FROM messages WHERE id = ?", (s,)) == [
        (f"{WORKER} demande Bash : ls src [libre]",)]


@pytest.mark.parametrize("actif", [False, True])
def test_libre_d_un_coordinateur_va_a_l_assistant(projet, monkeypatch, actif):
    mode(monkeypatch, actif)
    s = demander(projet, COORD, LIBRE)
    assert messages(projet) == [("cime", ASSISTANT, "signalement", "autorisation:d1")]
    assert obligation(projet, s) == [(ASSISTANT, "decision", "ouverte")]


def test_libre_d_un_worker_en_mode_actif_va_aussi_au_coordinateur(projet, monkeypatch):
    mode(monkeypatch, True)
    demander(projet, WORKER, LIBRE)
    assert messages(projet) == [("cime", COORD, "signalement", "autorisation:d1")]


@pytest.mark.parametrize("actif, suspendue, dest", [(False, False, UTILISATEUR), (True, True, UTILISATEUR),
                                                    (True, False, ASSISTANT)])
def test_autonome_selon_le_mode(projet, monkeypatch, actif, suspendue, dest):
    mode(monkeypatch, actif, suspendue)
    s = demander(projet, WORKER, AUTONOME)
    assert messages(projet) == [("cime", dest, "signalement", "autorisation:d1")]
    assert corps(projet, s)["classe"] == "autonome"
    assert obligation(projet, s) == ([] if dest == UTILISATEUR else [(ASSISTANT, "decision", "ouverte")])


def test_autonome_mode_illisible_vaut_inactif(projet, monkeypatch):
    def casse(projet):
        raise RuntimeError("registre illisible")
    monkeypatch.setattr(fusions_auto, "etat_courant", casse)
    demander(projet, WORKER, AUTONOME)
    assert messages(projet) == [("cime", UTILISATEUR, "signalement", "autorisation:d1")]


@pytest.mark.parametrize("actif", [False, True])
def test_reserve_va_a_utilisateur_et_informe_le_superieur(projet, monkeypatch, actif):
    mode(monkeypatch, actif)
    s = demander(projet, WORKER, RESERVE)
    assert messages(projet) == [("cime", UTILISATEUR, "signalement", "autorisation:d1"),
                                ("cime", COORD, "signalement", "autorisation-reservee:d1")]
    assert corps(projet, s) == {"outil": "Edit", "cible": "/etc/hosts", "classe": "reserve",
                                "theme": "hors_projet"}
    info, = lignes(projet, "SELECT id FROM messages WHERE objet = 'autorisation-reservee:d1'")
    assert obligation(projet, s) == [] and obligation(projet, info[0]) == []


def test_reserve_d_un_coordinateur_informe_l_assistant(projet):
    demander(projet, COORD, RESERVE)
    assert messages(projet) == [("cime", UTILISATEUR, "signalement", "autorisation:d1"),
                                ("cime", ASSISTANT, "signalement", "autorisation-reservee:d1")]


def test_l_assistant_reste_ignore(projet):
    demander(projet, ASSISTANT, RESERVE)
    assert messages(projet) == []


def test_resume_et_cible_tronques(projet):
    longue = "ls " + "a" * 400
    s = demander(projet, WORKER, {"tool_name": "Bash", "tool_input": {"command": longue}})
    resume, = lignes(projet, "SELECT resume FROM messages WHERE id = ?", (s,))[0]
    assert len(resume) <= 160 and resume.endswith("…")
    assert corps(projet, s)["cible"] == longue[:200]


# --- échelles : fonctions pures ----------------------------------------------------------------

@pytest.mark.parametrize("classe, debiteur, attendu", [
    ("libre", COORD, "autorisation_libre_worker"), ("libre", ASSISTANT, "autorisation_libre_coord"),
    ("autonome", ASSISTANT, "autorisation_autonome"), ("autonome", UTILISATEUR, "autorisation_autonome"),
    ("reserve", UTILISATEUR, "autorisation_reserve")])
def test_type_d_echeance_lu_dans_le_corps(classe, debiteur, attendu):
    c = json.dumps({"outil": "Bash", "cible": "x", "classe": classe, "theme": "t"})
    assert echeances.type_obligation("signalement", "decision", debiteur, "autorisation:d", c) == attendu


@pytest.mark.parametrize("c", [None, "", "{", "[]", json.dumps({"classe": "inconnue"})])
def test_type_d_echeance_sans_corps_lisible(c):
    assert echeances.type_obligation("signalement", "decision", ASSISTANT, "autorisation:d", c) \
        == "autorisation"


def _cumul(type_):
    total, sortie = timedelta(0), []
    for e in echeances.ECHELLES[type_]:
        total += e.delai
        sortie.append(int(total.total_seconds() // 60))
    return sortie


def test_les_echelles_reprennent_les_delais_attendus():
    assert _cumul("autorisation_libre_worker") == [0, 2, 2, 4, 10]
    assert _cumul("autorisation_libre_coord") == [0, 2, 10]
    assert _cumul("autorisation_autonome") == [0, 2, 10]
    assert _cumul("autorisation_reserve") == [0, 120]
    assert echeances.ECHELLES["autorisation_reserve"][-1].repeter


def _marche(type_, rang, actif):
    e = echeances.etape_effective(echeances.ECHELLES[type_][rang], actif)
    return (e.action, e.cible, e.info)


@pytest.mark.parametrize("type_, rang, actif, attendu", [
    # libre, worker : 2 min (les deux modes) relance coord + signalement Assistant
    ("autorisation_libre_worker", 1, False, ("relance", "debiteur", False)),
    ("autorisation_libre_worker", 1, True, ("relance", "debiteur", False)),
    ("autorisation_libre_worker", 2, False, ("signalement", "assistant", False)),
    ("autorisation_libre_worker", 2, True, ("signalement", "assistant", False)),
    # 4 min : inactif l'utilisateur ; actif relance à l'Assistant
    ("autorisation_libre_worker", 3, False, ("signalement", "utilisateur", False)),
    ("autorisation_libre_worker", 3, True, ("relance", "assistant", False)),
    # 10 min : inactif renotification ; actif information
    ("autorisation_libre_worker", 4, False, ("signalement", "utilisateur", False)),
    ("autorisation_libre_worker", 4, True, ("signalement", "utilisateur", True)),
    # libre, coordinateur : 2 min inactif l'utilisateur / actif relance ; 10 min renotif / information
    ("autorisation_libre_coord", 1, False, ("signalement", "utilisateur", False)),
    ("autorisation_libre_coord", 1, True, ("relance", "debiteur", False)),
    ("autorisation_libre_coord", 2, False, ("signalement", "utilisateur", False)),
    ("autorisation_libre_coord", 2, True, ("signalement", "utilisateur", True)),
    # autonome : 2 min actif relance à l'Assistant / inactif l'utilisateur ; 10 min renotif / information
    ("autorisation_autonome", 1, True, ("relance", "assistant", False)),
    ("autorisation_autonome", 1, False, ("signalement", "utilisateur", False)),
    ("autorisation_autonome", 2, False, ("signalement", "utilisateur", False)),
    ("autorisation_autonome", 2, True, ("signalement", "utilisateur", True)),
    # réservé : renotification de l'utilisateur toutes les 2 h, quel que soit le mode
    ("autorisation_reserve", 1, False, ("signalement", "utilisateur", False)),
    ("autorisation_reserve", 1, True, ("signalement", "utilisateur", False)),
])
def test_chaque_case_du_tableau(type_, rang, actif, attendu):
    assert _marche(type_, rang, actif) == attendu


def test_aucune_marche_ne_refuse():
    for type_, echelle in echeances.ECHELLES.items():
        for e in echelle:
            for v in (e, e.actif):
                assert v is None or v.action in (None, "relance", "signalement"), type_


# --- échelles : le moteur, horloge simulée -------------------------------------------------------

def _passes(projet, instants, debut, monkeypatch=None, modes=None):
    """Une passe du moteur à chaque instant (minutes depuis `debut`) ; `modes[i]` : le mode à
    cet instant. Renvoie les messages de Cime ajoutés à chaque passe (a, nature, objet)."""
    sortie = []
    for i, minutes in enumerate(instants):
        if modes is not None:
            mode(monkeypatch, modes[i])
        avant = len(lignes(projet, "SELECT id FROM messages"))
        relances.executer(projet, debut + timedelta(minutes=minutes))
        sortie.append([(a, n, o) for _, a, n, o in lignes(
            projet, "SELECT de, a, nature, objet FROM messages ORDER BY id")[avant:]])
    return sortie


def t0():
    return datetime.now(timezone.utc)


def _resume(projet, objet):
    return lignes(projet, "SELECT resume FROM messages WHERE objet = ?", (objet,))[0][0]


def test_libre_worker_mode_inactif(projet, monkeypatch):
    s = demander(projet, WORKER, LIBRE)
    d = t0()
    p = _passes(projet, [0, 1, 2.1, 3, 4.3, 9, 10.5], d)
    assert p[0] == [] and p[1] == []
    assert p[2] == [(COORD, "relance", f"relance:{s}:1"),            # même échéance : les deux
                    (ASSISTANT, "signalement", f"escalade:{s}:2")]
    assert p[3] == []
    assert p[4] == [(UTILISATEUR, "signalement", f"escalade:{s}:3")]
    assert p[5] == []
    assert p[6] == [(UTILISATEUR, "signalement", f"escalade:{s}:4")]     # renotification


def test_libre_worker_mode_actif_jamais_utilisateur_avant_l_information(projet, monkeypatch):
    mode(monkeypatch, True)
    s = demander(projet, WORKER, LIBRE)
    d = t0()
    p = _passes(projet, [0, 2.1, 4.3, 10.5], d)
    assert p[1] == [(COORD, "relance", f"relance:{s}:1"), (ASSISTANT, "signalement", f"escalade:{s}:2")]
    assert p[2] == [(ASSISTANT, "relance", f"relance:{s}:3")]       # pas l'utilisateur
    assert p[3] == [(UTILISATEUR, "signalement", f"escalade:{s}:4")]
    assert "autorisation sans réponse" in _resume(projet, f"escalade:{s}:4")


def test_libre_worker_le_mode_est_relu_a_chaque_echeance(projet, monkeypatch):
    """Créée en mode actif, la demande voit le mode coupé à 4 min : l'utilisateur, pas une relance."""
    mode(monkeypatch, True)
    s = demander(projet, WORKER, LIBRE)
    d = t0()
    p = _passes(projet, [0, 2.1, 4.3], d, monkeypatch, [True, True, False])
    assert p[2] == [(UTILISATEUR, "signalement", f"escalade:{s}:3")]


def test_libre_worker_cree_inactif_puis_mode_actif(projet, monkeypatch):
    s = demander(projet, WORKER, LIBRE)
    d = t0()
    p = _passes(projet, [0, 2.1, 4.3], d, monkeypatch, [False, False, True])
    assert p[2] == [(ASSISTANT, "relance", f"relance:{s}:3")]


def test_libre_coordinateur_mode_inactif_comme_avant(projet):
    s = demander(projet, COORD, LIBRE)
    d = t0()
    p = _passes(projet, [0, 1, 2.1, 9, 10.5], d)
    assert p[:2] == [[], []]
    assert p[2] == [(UTILISATEUR, "signalement", f"escalade:{s}:1")]
    assert p[3] == []
    assert p[4] == [(UTILISATEUR, "signalement", f"escalade:{s}:2")]


def test_libre_coordinateur_mode_actif(projet, monkeypatch):
    mode(monkeypatch, True)
    s = demander(projet, COORD, LIBRE)
    d = t0()
    p = _passes(projet, [0, 2.1, 10.5], d)
    assert p[1] == [(ASSISTANT, "relance", f"relance:{s}:1")]
    assert p[2] == [(UTILISATEUR, "signalement", f"escalade:{s}:2")]
    assert "autorisation sans réponse" in _resume(projet, f"escalade:{s}:2")


def test_autonome_mode_actif_relance_puis_information(projet, monkeypatch):
    mode(monkeypatch, True)
    s = demander(projet, WORKER, AUTONOME)
    d = t0()
    p = _passes(projet, [0, 2.1, 10.5], d)
    assert p[1] == [(ASSISTANT, "relance", f"relance:{s}:1")]
    assert p[2] == [(UTILISATEUR, "signalement", f"escalade:{s}:2")]
    assert "autorisation sans réponse" in _resume(projet, f"escalade:{s}:2")


def test_autonome_mode_coupe_pendant_l_attente_passe_a_utilisateur(projet, monkeypatch):
    mode(monkeypatch, True)
    s = demander(projet, WORKER, AUTONOME)
    d = t0()
    p = _passes(projet, [0, 2.1, 10.5], d, monkeypatch, [True, False, False])
    assert p[1] == [(UTILISATEUR, "signalement", f"escalade:{s}:1")]
    assert p[2] == [(UTILISATEUR, "signalement", f"escalade:{s}:2")]      # renotification


def test_autonome_cree_inactif_utilisateur_deja_prevenu_puis_renotifie(projet):
    s = demander(projet, WORKER, AUTONOME)
    d = t0()
    p = _passes(projet, [0, 2.1, 9, 10.5, 11], d)
    assert p[:3] == [[], [], []]
    assert p[3] == [(UTILISATEUR, "signalement", f"escalade:{s}:2")]
    assert p[4] == []


def test_autonome_cree_inactif_puis_mode_actif_relance_l_assistant(projet, monkeypatch):
    s = demander(projet, WORKER, AUTONOME)
    d = t0()
    p = _passes(projet, [2.1, 10.5], d, monkeypatch, [True, True])
    assert p[0] == [(ASSISTANT, "relance", f"relance:{s}:1")]
    assert p[1] == [(UTILISATEUR, "signalement", f"escalade:{s}:2")]


def test_reserve_renotifie_toutes_les_2_h(projet, monkeypatch):
    s = demander(projet, WORKER, RESERVE)
    d = t0()
    p = _passes(projet, [1, 60, 119, 121, 122, 200, 241, 242], d)
    assert p[:3] == [[], [], []]
    assert p[3] == [(UTILISATEUR, "signalement", f"escalade:{s}:1")]
    assert p[4] == [] and p[5] == []
    assert p[6] == [(UTILISATEUR, "signalement", f"escalade:{s}:2")]
    assert p[7] == []


def test_reserve_tranchee_plus_de_renotification(projet, monkeypatch, capsys):
    s = demander(projet, WORKER, RESERVE)
    assert cime(monkeypatch, UTILISATEUR, "accorder", str(s)) == 0
    assert _passes(projet, [121, 241], t0()) == [[], []]


def test_reserve_tranchee_par_la_page_plus_de_renotification(projet):
    s = demander(projet, WORKER, RESERVE)
    conn = ouvrir(projet)
    with conn:
        conn.execute("INSERT INTO journal (horodatage, auteur, action, cible, details, resultat)"
                     " VALUES ('2026-01-01T00:00:00.000Z', 'utilisateur', 'autoriser', 'perm-d1', '{}', 'ok')")
    conn.close()
    assert _passes(projet, [121], t0()) == [[]]


def test_reserve_agent_reparti_plus_de_renotification(projet):
    s = demander(projet, WORKER, RESERVE)
    conn = ouvrir(projet)
    inscrire_evenement(conn, agent=WORKER, session_id="s", evenement="Stop", details={})
    conn.close()
    assert _passes(projet, [121], t0()) == [[]]


def test_aucune_marche_n_ecrit_de_refus(projet, monkeypatch):
    for i, (agent, entree) in enumerate([(WORKER, LIBRE), (COORD, LIBRE), (WORKER, AUTONOME),
                                         (WORKER, RESERVE)]):
        demander(projet, agent, entree, demande_id=f"d{i}")
    _passes(projet, [2.1, 4.3, 10.5, 130, 250], t0())
    assert lignes(projet, "SELECT count(*) FROM messages WHERE nature IN ('refus', 'accord')") == [(0,)]


def test_escalade_vers_utilisateur_d_une_demande_sans_obligation_reste_ouverte(projet):
    """L'escalade d'une demande adressée à l'utilisateur se ferme quand la demande est tranchée, pas
    parce que l'original n'a pas d'obligation."""
    s = demander(projet, WORKER, RESERVE)
    d = t0()
    _passes(projet, [121], d)
    conn = ouvrir(projet)
    try:
        signalements_utilisateur.clore(conn, projet, t0() + timedelta(minutes=1))   # l'escalade est d'à l'instant
        esc = lignes(projet, "SELECT id FROM messages WHERE objet = ?", (f"escalade:{s}:1",))[0][0]
        from cime.fondation.registre import etat_message
        assert etat_message(conn, esc) not in ("clos", "abandonne")
        inscrire_evenement(conn, agent=WORKER, session_id="s", evenement="Stop", details={})
        signalements_utilisateur.clore(conn, projet, t0() + timedelta(minutes=1))
        assert etat_message(conn, esc) in ("clos", "abandonne")       # tranchée : fermée
    finally:
        conn.close()


def test_demande_a_utilisateur_close_quand_tranchee(projet, monkeypatch, capsys):
    s = demander(projet, WORKER, RESERVE)
    conn = ouvrir(projet)
    inscrire_evenement(conn, agent=WORKER, session_id="s", evenement="UserPromptSubmit", details={})
    signalements_utilisateur.clore(conn, projet, t0() + timedelta(minutes=1))
    from cime.fondation.registre import etat_message
    assert etat_message(conn, s) in ("clos", "abandonne")
    conn.close()


# --- qui peut répondre ---------------------------------------------------------------------------

def accorder(monkeypatch, capsys, qui, s):
    capsys.readouterr()
    code = cime(monkeypatch, qui, "accorder", str(s))
    return code, capsys.readouterr().err


def refuser(monkeypatch, capsys, qui, s):
    capsys.readouterr()
    code = cime(monkeypatch, qui, "refuser", str(s), "non")
    return code, capsys.readouterr().err


def accords(projet):
    return lignes(projet, "SELECT de, a, nature, objet FROM messages WHERE nature IN ('accord', 'refus')")


@pytest.mark.parametrize("qui", [COORD, ASSISTANT])
@pytest.mark.parametrize("actif", [False, True])
def test_reserve_refusee_a_l_assistant_et_au_coordinateur(projet, monkeypatch, capsys, qui, actif):
    mode(monkeypatch, actif)
    s = demander(projet, WORKER, RESERVE)
    code, err = accorder(monkeypatch, capsys, qui, s)
    assert code == 2 and "réservé à l'utilisateur : hors_projet" in err
    assert accords(projet) == []


def test_reserve_accordee_par_utilisateur(projet, monkeypatch, capsys):
    s = demander(projet, WORKER, RESERVE)
    assert accorder(monkeypatch, capsys, UTILISATEUR, s)[0] == 0
    assert accords(projet) == [(UTILISATEUR, "cime", "accord", "autorisation:d1")]
    assert accorder(monkeypatch, capsys, UTILISATEUR, s)[0] == 2      # une fois


def test_autonome_mode_inactif_assistant_refuse(projet, monkeypatch, capsys):
    s = demander(projet, WORKER, AUTONOME)
    code, err = accorder(monkeypatch, capsys, ASSISTANT, s)
    assert code == 2 and "le mode autonome n'est plus actif : l'accord est à l'utilisateur" in err
    assert accords(projet) == []


def test_autonome_mode_actif_coordinateur_refuse(projet, monkeypatch, capsys):
    mode(monkeypatch, True)
    s = demander(projet, WORKER, AUTONOME)
    code, err = accorder(monkeypatch, capsys, COORD, s)
    assert code == 2 and accords(projet) == []


def test_autonome_mode_actif_assistant_accorde_et_annonce(projet, monkeypatch, capsys):
    mode(monkeypatch, True)
    s = demander(projet, WORKER, AUTONOME)
    assert accorder(monkeypatch, capsys, ASSISTANT, s)[0] == 0
    assert accords(projet) == [(ASSISTANT, "cime", "accord", "autorisation:d1")]
    annonce = lignes(projet, "SELECT id, de, a, nature, resume FROM messages WHERE objet = ?",
                     ("autorisation-auto:d1",))
    assert [a[1:] for a in annonce] == [(ASSISTANT, UTILISATEUR, "rapport_utilisateur",
                                         f"{WORKER} : Bash uv add httpx, accordé")]
    assert obligation(projet, annonce[0][0]) == []                   # aucune obligation
    assert obligation(projet, s) == [(ASSISTANT, "decision", "satisfaite")]


def test_autonome_mode_coupe_apres_la_demande_assistant_refuse(projet, monkeypatch, capsys):
    mode(monkeypatch, True)
    s = demander(projet, WORKER, AUTONOME)
    mode(monkeypatch, True, suspendue=True)
    code, err = accorder(monkeypatch, capsys, ASSISTANT, s)
    assert code == 2 and "le mode autonome n'est plus actif" in err
    mode(monkeypatch, False)
    code, err = accorder(monkeypatch, capsys, ASSISTANT, s)
    assert code == 2 and "le mode autonome n'est plus actif" in err
    assert obligation(projet, s) == [(ASSISTANT, "decision", "ouverte")]   # rien n'est écrit
    assert accords(projet) == [] and messages(projet, "autorisation-auto:%") == []


def test_autonome_cree_inactif_puis_mode_actif_assistant_accorde(projet, monkeypatch, capsys):
    s = demander(projet, WORKER, AUTONOME)
    mode(monkeypatch, True)
    assert accorder(monkeypatch, capsys, ASSISTANT, s)[0] == 0
    assert messages(projet, "autorisation-auto:%") == [(ASSISTANT, UTILISATEUR, "rapport_utilisateur",
                                                        "autorisation-auto:d1")]


@pytest.mark.parametrize("actif", [False, True])
def test_autonome_accordee_par_utilisateur_sans_annonce(projet, monkeypatch, capsys, actif):
    mode(monkeypatch, actif)
    s = demander(projet, WORKER, AUTONOME)
    assert accorder(monkeypatch, capsys, UTILISATEUR, s)[0] == 0
    assert messages(projet, "autorisation-auto:%") == []


def test_autonome_refusee_par_l_assistant_sans_annonce(projet, monkeypatch, capsys):
    mode(monkeypatch, True)
    s = demander(projet, WORKER, AUTONOME)
    assert refuser(monkeypatch, capsys, ASSISTANT, s)[0] == 0
    assert messages(projet, "autorisation-auto:%") == []


def test_libre_accordee_par_le_coordinateur_sans_annonce(projet, monkeypatch, capsys):
    mode(monkeypatch, True)
    s = demander(projet, WORKER, LIBRE)
    assert accorder(monkeypatch, capsys, COORD, s)[0] == 0
    assert accords(projet) == [(COORD, "cime", "accord", "autorisation:d1")]
    assert messages(projet, "autorisation-auto:%") == []


def test_libre_l_assistant_n_est_pas_le_destinataire(projet, monkeypatch, capsys):
    s = demander(projet, WORKER, LIBRE)
    code, err = accorder(monkeypatch, capsys, ASSISTANT, s)
    assert code == 2 and "n'est pas adressé à assistant" in err


def test_libre_accordee_par_utilisateur_ferme_l_obligation_du_coordinateur(projet, monkeypatch, capsys):
    s = demander(projet, WORKER, LIBRE)
    assert accorder(monkeypatch, capsys, UTILISATEUR, s)[0] == 0
    assert obligation(projet, s) == [(COORD, "decision", "satisfaite")]


@pytest.mark.parametrize("c", [None, "{", json.dumps({"outil": "Bash"})])
def test_sans_classe_lisible_traite_comme_reserve(projet, monkeypatch, capsys, c):
    conn = ouvrir(projet)
    s = commandes.inscrire(conn, de="cime", a=COORD, nature="signalement", resume="r",
                           objet="autorisation:d9", corps=c)
    conn.close()
    code, err = accorder(monkeypatch, capsys, COORD, s)
    assert code == 2 and "réservé à l'utilisateur" in err
    assert refuser(monkeypatch, capsys, COORD, s)[0] == 0        # refuser : le débiteur, toujours


@pytest.mark.parametrize("classe", ["libre", "autonome", "reserve"])
@pytest.mark.parametrize("actif", [False, True])
def test_refuser_jamais_refuse_pour_une_raison_de_classe(projet, monkeypatch, capsys, classe, actif):
    """Le débiteur refuse toujours, quelle que soit la classe et le mode."""
    mode(monkeypatch, actif)
    conn = ouvrir(projet)
    s = commandes.inscrire(conn, de="cime", a=COORD, nature="signalement", resume="r",
                           objet="autorisation:d8", corps=json.dumps({"classe": classe, "theme": "t"}))
    conn.close()
    assert refuser(monkeypatch, capsys, COORD, s)[0] == 0
    assert accords(projet) == [(COORD, "cime", "refus", "autorisation:d8")]


def test_refuser_reste_au_debiteur(projet, monkeypatch, capsys):
    """Comme avant les classes : un signalement à l'utilisateur n'a pas de débiteur, son refus
    passe par la page ; un tiers ne refuse pas à la place du destinataire."""
    s = demander(projet, WORKER, RESERVE)
    assert refuser(monkeypatch, capsys, UTILISATEUR, s)[0] == 2
    s2 = demander(projet, WORKER, LIBRE, demande_id="d2")
    assert refuser(monkeypatch, capsys, ASSISTANT, s2)[0] == 2
    assert accords(projet) == []


def test_annonce_atomique_avec_l_accord(projet, monkeypatch, capsys):
    """L'annonce échoue ⇒ ni accord, ni annonce, obligation ouverte."""
    mode(monkeypatch, True)
    s = demander(projet, WORKER, AUTONOME)
    from cime.signaux import commandes as c

    def casse(*a, **k):
        raise RuntimeError("panne au milieu")
    monkeypatch.setattr(c, "_annonce_autorisation", casse)
    with pytest.raises(RuntimeError):
        cime(monkeypatch, ASSISTANT, "accorder", str(s))
    assert accords(projet) == [] and messages(projet, "autorisation-auto:%") == []
    assert obligation(projet, s) == [(ASSISTANT, "decision", "ouverte")]
