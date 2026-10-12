"""Étapes 3 et 4 : la livraison tmux (faux tmux), les tentatives, la reprise, les sessions."""
import argparse
import io
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import pytest

from aide import fabriquer_projet, lignes
from faux_tmux import REGLE, FauxTmux
from cime.fondation import hook
from cime.fondation.nom import VAR_AGENT, VAR_PROJET
from cime.fondation.registre import etat_message, inscrire_evenement, inscrire_transition, ouvrir
from cime.signaux import commandes, courrier, echeances, facteur, livraison

COORD, WORKER, ASSISTANT = "coord-x", "worker-x-t", "assistant"
S_COORD, S_WORKER, S_ASSISTANT = "essai-coord-x", "essai-worker-x-t", "essai-assistant"


@pytest.fixture
def projet(tmp_path, monkeypatch):
    racine = fabriquer_projet(tmp_path / "depot")
    monkeypatch.setenv(VAR_PROJET, str(racine))
    return racine


@pytest.fixture
def tmux(monkeypatch):
    faux = FauxTmux([S_COORD, S_WORKER, S_ASSISTANT])
    monkeypatch.setattr(livraison, "_tmux", faux)
    monkeypatch.setattr(livraison, "_dormir", lambda s: None)
    return faux


def evt(projet, agent, nom, **details):
    conn = ouvrir(projet)
    try:
        return inscrire_evenement(conn, agent=agent, session_id="s", evenement=nom, details=details)
    finally:
        conn.close()


def repos(projet, agent):
    evt(projet, agent, "UserPromptSubmit")
    evt(projet, agent, "Stop")


def poster(projet, de, a, resume="va", nature="consigne", attend="rien", objet=None):
    conn = ouvrir(projet)
    try:
        return commandes.inscrire(conn, de=de, a=a, nature=nature, resume=resume, attend=attend,
                                  objet=objet, equipe="x")
    finally:
        conn.close()


def maintenant(decalage=10.0):
    return datetime.now(timezone.utc) + timedelta(seconds=decalage)


def tour(projet, memoire=None, decalage=10.0):
    return facteur.tour(projet, maintenant(decalage), memoire or livraison.Memoire())


def etat(projet, identifiant):
    conn = ouvrir(projet)
    try:
        return etat_message(conn, identifiant)
    finally:
        conn.close()


def courriers(projet):
    return lignes(projet, "SELECT id, a, voie, etat, tentative FROM courriers ORDER BY id")


def signalements(projet, objet_debut=""):
    return lignes(projet, "SELECT a, objet, nature FROM messages WHERE de = 'cime' AND "
                  "nature = 'signalement' AND objet LIKE ? ORDER BY id", (objet_debut + "%",))


def preuves(projet, etat_, message_id):
    return [json.loads(p) for (p,) in lignes(
        projet, "SELECT preuve FROM transitions WHERE message_id = ? AND etat = ? ORDER BY id",
        (message_id, etat_))]


def frappes(tmux):
    return [a for a in tmux.appels if a[0] == "send-keys" and "-l" in a]


def accuser(monkeypatch, capsys, agent, prompt):
    monkeypatch.setenv(VAR_AGENT, agent)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"session_id": "s", "prompt": prompt})))
    hook.executer(argparse.Namespace(evenement="UserPromptSubmit"))
    capsys.readouterr()


# --- l'état de l'agent --------------------------------------------------------------------

def test_etat_agent(projet):
    conn = ouvrir(projet)
    now = maintenant()
    assert livraison.etat_agent(conn, COORD, now) == "inconnu"
    evt(projet, COORD, "SessionStart")   # session ouverte, aucun tour : invite vide (défaut 2, --resume)
    assert livraison.etat_agent(conn, COORD, now) == "repos"
    evt(projet, COORD, "UserPromptSubmit")
    assert livraison.etat_agent(conn, COORD, now) == "tour"
    evt(projet, COORD, "PostToolUse")
    assert livraison.etat_agent(conn, COORD, now) == "tour"
    evt(projet, COORD, "Stop")
    assert livraison.etat_agent(conn, COORD, now) == "repos"
    evt(projet, COORD, "UserPromptSubmit")
    assert livraison.etat_agent(conn, COORD, now) == "tour"
    evt(projet, COORD, "Notification", notification_type="idle_prompt")  # tour interrompu (Échap)
    assert livraison.etat_agent(conn, COORD, now) == "repos"
    evt(projet, WORKER, "StopFailure")
    assert livraison.etat_agent(conn, WORKER, now) == "repos"
    conn.close()


# --- la livraison nominale ----------------------------------------------------------------

def test_livraison_nominale_puis_accuse(projet, tmux, monkeypatch, capsys):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD, resume="regarde ceci")
    tour(projet)
    assert tmux.entrees == [(S_COORD, f"Assistant : regarde ceci (#{m})")]
    assert etat(projet, m) == "livre"
    assert preuves(projet, "livre", m)[0] == {"capture_avant": "vide", "tmux_rc": 0,
                                              "invite_apres": "vide", "octets": 12}
    assert courriers(projet) == [(1, COORD, "tmux", "ouvert", 1)]
    tour(projet)  # rien de plus tant que l'accusé n'est pas venu
    assert len(tmux.entrees) == 1
    accuser(monkeypatch, capsys, COORD, f"Assistant : regarde ceci (#{m})")
    assert etat(projet, m) == "clos" and courriers(projet)[0][3] == "acquitte"


def test_l_ordre_des_gestes_une_frappe_une_pause_un_enter(projet, tmux, monkeypatch):
    repos(projet, COORD)
    poster(projet, ASSISTANT, COORD)
    pauses = []
    monkeypatch.setattr(livraison, "_dormir", lambda s: pauses.append(s))
    tour(projet)
    envois = [a for a in tmux.appels if a[0] in ("send-keys", "capture-pane")]
    assert [a[0] for a in envois] == ["capture-pane", "capture-pane", "send-keys", "capture-pane",
                                      "send-keys", "capture-pane"]   # invite, relecture, frappe, contrôle, Enter, validation
    assert "-l" in envois[2] and envois[4][-1] == "Enter"
    assert pauses == [echeances.PAUSE_FRAPPE, echeances.PAUSE_VALIDATION]


def test_deux_messages_en_attente_un_courrier_une_frappe(projet, tmux):
    repos(projet, COORD)
    a = poster(projet, ASSISTANT, COORD, resume="un")
    b = poster(projet, ASSISTANT, COORD, resume="deux")
    tour(projet)
    assert len(courriers(projet)) == 1 and len(frappes(tmux)) == 1
    assert tmux.entrees[0][1] == f"Assistant : un (#{a}) ‖ Assistant : deux (#{b})"


def test_un_long_message_est_livre_par_fichier(projet, tmux):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD, resume="long")
    conn = ouvrir(projet)
    conn.execute("UPDATE messages SET corps = ? WHERE id = ?", ("x" * 900, m))
    conn.commit()
    conn.close()
    tour(projet)
    assert ".orga/etat/courrier/" in tmux.entrees[0][1] and (projet / ".orga/etat/courrier" / f"{m}.md").exists()


# --- ce qui retient le facteur ------------------------------------------------------------

def test_brouillon_rien_n_est_tape(projet, tmux):
    repos(projet, COORD)
    poster(projet, ASSISTANT, COORD)
    tmux.sessions[S_COORD]["invite"] = "je suis en train d'écrire"
    memoire = livraison.Memoire()
    tour(projet, memoire)
    assert frappes(tmux) == [] and courriers(projet) == []
    assert memoire.occupe_par[COORD] == "invite"
    assert tmux.sessions[S_COORD]["invite"] == "je suis en train d'écrire"  # ni lu ni effacé


def test_l_assistant_n_est_jamais_livre_s_il_a_un_brouillon(projet, tmux):
    repos(projet, ASSISTANT)
    poster(projet, "coord-x", ASSISTANT, nature="question", resume="?")
    tmux.sessions[S_ASSISTANT]["invite"] = "brouillon de l'utilisateur"
    memoire = livraison.Memoire()
    tour(projet, memoire)
    assert frappes(tmux) == [] and memoire.occupe_par[ASSISTANT] == "invite"
    tmux.sessions[S_ASSISTANT]["invite"] = ""
    tour(projet, memoire)  # l'invite est vide : le message est livré
    assert len(tmux.entrees) == 1 and tmux.entrees[0][0] == S_ASSISTANT


def test_texte_attenue_n_est_pas_un_brouillon(projet, tmux, monkeypatch):
    repos(projet, COORD)
    poster(projet, ASSISTANT, COORD)
    ecran = tmux.__call__

    def avec_suggestion(*args):
        r = ecran(*args)
        if args[0] == "capture-pane" and not tmux.sessions[S_COORD]["invite"]:
            r.stdout = r.stdout.replace("❯\xa0", "❯\xa0\x1b[2msuggestion\x1b[0m")
        return r

    monkeypatch.setattr(livraison, "_tmux", avec_suggestion)
    tour(projet)
    assert len(tmux.entrees) == 1


def test_tour_en_cours_rien_n_est_tape(projet, tmux):
    evt(projet, COORD, "UserPromptSubmit")
    evt(projet, COORD, "PostToolUse")
    poster(projet, ASSISTANT, COORD)
    memoire = livraison.Memoire()
    tour(projet, memoire)
    assert frappes(tmux) == [] and memoire.occupe_par[COORD] == "tour"


def test_agent_sans_evenement_rien_n_est_tape(projet, tmux):
    poster(projet, ASSISTANT, COORD)
    memoire = livraison.Memoire()
    tour(projet, memoire)
    assert frappes(tmux) == [] and memoire.occupe_par[COORD] == "inconnu"


def test_idle_prompt_confirme_le_repos_apres_un_tour_sans_stop(projet, tmux):
    evt(projet, COORD, "UserPromptSubmit")
    evt(projet, COORD, "Notification", notification_type="idle_prompt")
    poster(projet, ASSISTANT, COORD)
    tour(projet)
    assert len(tmux.entrees) == 1


def test_fenetre_active_depuis_moins_de_3_secondes(projet, tmux):
    repos(projet, COORD)
    poster(projet, ASSISTANT, COORD)
    tmux.sessions[S_COORD]["activite"] = time.time() + 9.0   # « maintenant » est à +10 s
    memoire = livraison.Memoire()
    tour(projet, memoire)
    assert frappes(tmux) == [] and memoire.occupe_par[COORD] == "invite"
    tmux.sessions[S_COORD]["activite"] = time.time() + 5.0   # 5 s de silence
    tour(projet, memoire)
    assert len(tmux.entrees) == 1


def test_le_hook_stop_attend_lui_meme(projet, tmux, monkeypatch):
    monkeypatch.setenv(echeances.VAR_ATTENTE_STOP, "120")
    repos(projet, WORKER)
    poster(projet, COORD, WORKER)
    memoire = livraison.Memoire()
    tour(projet, memoire)
    assert frappes(tmux) == [] and memoire.occupe_par[WORKER] == "attente_stop"
    tour(projet, memoire, decalage=200)   # l'attente est finie
    assert len(tmux.entrees) == 1


def test_l_assistant_n_a_pas_d_attente_a_l_arret(projet, tmux, monkeypatch):
    monkeypatch.setenv(echeances.VAR_ATTENTE_STOP, "120")
    repos(projet, ASSISTANT)
    poster(projet, COORD, ASSISTANT, nature="question", resume="?")
    tour(projet)
    assert len(tmux.entrees) == 1


def test_rien_n_est_livre_a_utilisateur_ni_sans_session(projet, tmux):
    repos(projet, COORD)
    poster(projet, ASSISTANT, "utilisateur", nature="rapport_utilisateur", resume="rapport")
    poster(projet, ASSISTANT, "coord-y")           # session absente
    tour(projet)
    assert tmux.entrees == [] and courriers(projet) == []


# --- la course à la frappe ----------------------------------------------------------------

def test_invite_modifiee_entre_les_deux_lectures_rien_n_est_tape(projet, tmux):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD)
    tmux.apres_capture.append(lambda t, n: t.frapper(S_COORD, "z") if n == 1 else None)
    tour(projet)
    assert frappes(tmux) == [] and courriers(projet)[0][3] == "echoue"
    assert etat(projet, m) == "inscrit" and tmux.sessions[S_COORD]["invite"] == "z"


def test_caractere_de_l_utilisateur_devant_le_texte_pas_d_enter_et_effacement(projet, tmux):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD)
    tmux.apres_frappe.append(lambda t, s, texte: t.sessions[s].update(
        invite="x" + t.sessions[s]["invite"]))      # son « x » est arrivé avant notre texte
    tour(projet)
    assert tmux.entrees == []
    assert tmux.sessions[S_COORD]["invite"] == "x"   # effacé, l'invite est revenue à sa saisie
    assert signalements(projet, "collision") == []
    assert courriers(projet)[0][3] == "echoue" and etat(projet, m) == "inscrit"
    reprise = preuves(projet, "inscrit", m)[-1]
    assert reprise["collision"] is True and reprise["tentative"] == 2


def test_frappes_entrelacees_laisse_tel_quel_et_signale_a_utilisateur(projet, tmux):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD)

    def entrelace(t, s, texte):
        invite = t.sessions[s]["invite"]
        t.sessions[s]["invite"] = invite[:5] + "XY" + invite[5:]

    tmux.apres_frappe.append(entrelace)
    tour(projet)
    assert tmux.entrees == [] and "XY" in tmux.sessions[S_COORD]["invite"]   # laissé tel quel
    assert all("BSpace" not in a for a in tmux.appels if a[0] == "send-keys")
    assert signalements(projet, "collision-invite") == [("utilisateur", f"collision-invite:{COORD}",
                                                         "signalement")]
    assert etat(projet, m) == "inscrit" and courriers(projet)[0][3] == "echoue"


def test_caractere_apres_le_texte_pas_d_enter_et_signalement(projet, tmux):
    repos(projet, COORD)
    poster(projet, ASSISTANT, COORD)
    tmux.apres_frappe.append(lambda t, s, texte: t.sessions[s].update(
        invite=t.sessions[s]["invite"] + "x"))
    tour(projet)
    assert tmux.entrees == [] and len(signalements(projet, "collision-invite")) == 1


def test_echec_de_send_keys_le_courrier_echoue(projet, tmux):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD)
    tmux.echec_send_keys = True
    memoire = livraison.Memoire()
    tour(projet, memoire)
    assert etat(projet, m) == "inscrit" and "send-keys a échoué" in memoire.erreurs[COORD]


def affichage_differe(monkeypatch, tmux, vues):
    """Après la frappe, l'écran montre `vues[j]` à la j-ième capture (la dernière vue tient) : la TUI
    n'a pas fini d'afficher le texte. `None` = invite introuvable. Le faux garde le texte réel : l'Enter
    le tape comme d'habitude."""
    depuis = {"n": None}

    def tmux_differe(*args):
        if args[0] == "send-keys" and "-l" in args:
            depuis["n"] = 0
        if args[0] == "send-keys" and "Enter" in args:
            depuis["n"] = None
        r = tmux(*args)
        if args[0] == "capture-pane" and depuis["n"] is not None:
            vue = vues[min(depuis["n"], len(vues) - 1)]
            depuis["n"] += 1
            r.stdout = "" if vue is None else f"{REGLE}\n❯\xa0{vue}\n{REGLE}\n"
        return r

    monkeypatch.setattr(livraison, "_tmux", tmux_differe)


# --- la frappe encore en cours d'affichage ------------------------------------------------

def test_texte_entier_a_la_seconde_capture_un_enter(projet, tmux, monkeypatch):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD, resume="regarde ceci")
    texte = f"Assistant : regarde ceci (#{m})"
    affichage_differe(monkeypatch, tmux, ["", texte])
    tour(projet)
    assert tmux.entrees == [(S_COORD, texte)] and etat(projet, m) == "livre"
    assert courriers(projet)[0][3] != "echoue"


def test_invite_introuvable_a_la_premiere_capture_puis_texte_entier_un_enter(projet, tmux, monkeypatch):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD, resume="regarde ceci")
    texte = f"Assistant : regarde ceci (#{m})"
    affichage_differe(monkeypatch, tmux, [None, texte])
    tour(projet)
    assert tmux.entrees == [(S_COORD, texte)] and etat(projet, m) == "livre"
    assert courriers(projet)[0][3] != "echoue"


def test_prefixe_puis_texte_entier_un_enter(projet, tmux, monkeypatch):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD, resume="regarde ceci")
    texte = f"Assistant : regarde ceci (#{m})"
    affichage_differe(monkeypatch, tmux, [texte[:9], texte])
    tour(projet)
    assert tmux.entrees == [(S_COORD, texte)] and etat(projet, m) == "livre"


def test_invite_jamais_complete_attente_bornee_puis_comportement_d_avant(projet, tmux, monkeypatch):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD, resume="regarde ceci")
    texte = f"Assistant : regarde ceci (#{m})"
    pauses = []
    monkeypatch.setattr(livraison, "_dormir", lambda s: pauses.append(s))
    affichage_differe(monkeypatch, tmux, [texte[:9]])
    tour(projet)
    assert tmux.entrees == [] and len(pauses) > 2
    assert pauses[0] == echeances.PAUSE_FRAPPE
    assert sum(pauses) <= echeances.PAUSE_FRAPPE + echeances.STABILISATION_MAX
    assert courriers(projet)[0][3] == "echoue"
    assert len(signalements(projet, "collision-invite")) == 1


def test_collision_reelle_aucune_attente_inutile(projet, tmux, monkeypatch):
    repos(projet, COORD)
    poster(projet, ASSISTANT, COORD)
    pauses = []
    monkeypatch.setattr(livraison, "_dormir", lambda s: pauses.append(s))
    tmux.apres_frappe.append(lambda t, s, texte: t.sessions[s].update(
        invite="x" + t.sessions[s]["invite"]))      # le « x » de l'utilisateur est arrivé avant notre texte
    tour(projet)
    assert pauses == [echeances.PAUSE_FRAPPE]
    assert tmux.entrees == [] and tmux.sessions[S_COORD]["invite"] == "x"   # effacé, comme avant
    assert courriers(projet)[0][3] == "echoue"


# --- la preuve porte ce que l'écran montrait : des mesures, jamais le texte ----------------

def _reprise_de(projet, m):
    """La transition `inscrit` de reprise de `m` : sa preuve dit pourquoi le courrier a échoué."""
    [preuve] = [p for p in preuves(projet, "inscrit", m) if "reprise" in p]
    return preuve


def _sans_texte(preuve, texte):
    brut = json.dumps(preuve, ensure_ascii=False)
    assert texte not in brut and livraison._norme(texte) not in brut and "regarde" not in brut


# (relation, écran vu d'après notre texte, écart attendu, lignes attendues)
RELATIONS = [
    ("prefixe", lambda t: t[:9], lambda n: 9, 1),
    ("suffixe", lambda t: t[5:], lambda n: 0, 1),
    ("contient", lambda t: t + "x", lambda n: len(n), 1),
    ("autre", lambda t: "une autre saisie sans rapport", lambda n: 0, 1),
    ("vide", lambda t: "", lambda n: 0, 0),
    ("introuvable", lambda t: None, lambda n: None, None),
]


@pytest.mark.parametrize("relation, vue, ecart, lignes", RELATIONS)
def test_collision_la_preuve_porte_les_mesures_de_l_ecran(projet, tmux, monkeypatch, relation, vue, ecart, lignes):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD, resume="regarde ceci")
    texte = f"Assistant : regarde ceci (#{m})"
    affichage_differe(monkeypatch, tmux, [vue(texte)])
    tour(projet)
    assert courriers(projet)[0][3] == "echoue"
    preuve = _reprise_de(projet, m)
    nous, lu = livraison._norme(texte), vue(texte)
    assert preuve["ecran"] == {"texte_len": len(nous), "vu_len": None if lu is None else len(livraison._norme(lu)),
                               "relation": relation, "ecart": ecart(nous), "lignes": lignes}
    assert preuve["collision"] is True and preuve["efface"] is False
    _sans_texte(preuve, texte)


def test_enter_en_echec_la_preuve_porte_l_ecran_identique(projet, tmux, monkeypatch):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD, resume="regarde ceci")
    texte = f"Assistant : regarde ceci (#{m})"

    def enter_en_echec(*args):
        if args[0] == "send-keys" and "Enter" in args:
            return subprocess.CompletedProcess(args, 1, "", "no server")
        return tmux(*args)

    monkeypatch.setattr(livraison, "_tmux", enter_en_echec)
    tour(projet)
    preuve = _reprise_de(projet, m)
    nous = livraison._norme(texte)
    assert preuve["tmux_rc"] == 1
    assert preuve["ecran"] == {"texte_len": len(nous), "vu_len": len(nous), "relation": "identique",
                               "ecart": None, "lignes": 1}
    _sans_texte(preuve, texte)


def test_texte_non_valide_la_livraison_porte_l_ecran(projet, tmux, monkeypatch):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD, resume="regarde ceci")
    texte = f"Assistant : regarde ceci (#{m})"

    def enter_sans_effet(*args):
        if args[0] == "send-keys" and "Enter" in args:
            return subprocess.CompletedProcess(args, 0, "", "")
        return tmux(*args)

    monkeypatch.setattr(livraison, "_tmux", enter_sans_effet)
    tour(projet)
    [preuve] = preuves(projet, "livre", m)
    nous = livraison._norme(texte)
    assert preuve["invite_apres"] == "non_validee"
    assert preuve["ecran"] == {"texte_len": len(nous), "vu_len": len(nous), "relation": "identique",
                               "ecart": None, "lignes": 1}
    _sans_texte(preuve, texte)


def bspaces(tmux):
    return [a for a in tmux.appels if a[0] == "send-keys" and "BSpace" in a]


# --- le reste de notre frappe perdue : reconnu et effacé ----------------------------------

def test_frappe_perdue_puis_texte_complet_efface_puis_refrappee_une_fois(projet, tmux, monkeypatch):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD, resume="regarde ceci")
    texte = f"Assistant : regarde ceci (#{m})"
    memoire = livraison.Memoire()
    affichage_differe(monkeypatch, tmux, [texte[:9]])
    tour(projet, memoire)                                   # (e) : pas d'Enter, texte resté à l'invite
    assert tmux.entrees == [] and courriers(projet)[0][3] == "echoue"
    monkeypatch.setattr(livraison, "_tmux", tmux)           # l'écran est enfin à jour
    tour(projet, memoire)
    assert bspaces(tmux) and tmux.entrees == [(S_COORD, texte)] and etat(projet, m) == "livre"


def test_saisie_de_l_utilisateur_differente_jamais_effacee(projet, tmux, monkeypatch):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD, resume="regarde ceci")
    memoire = livraison.Memoire()
    affichage_differe(monkeypatch, tmux, [f"Assistant : regarde ceci (#{m})"[:9]])
    tour(projet, memoire)
    monkeypatch.setattr(livraison, "_tmux", tmux)
    tmux.sessions[S_COORD]["invite"] = "brouillon de l'utilisateur"
    tour(projet, memoire)
    assert bspaces(tmux) == [] and tmux.entrees == []
    assert tmux.sessions[S_COORD]["invite"] == "brouillon de l'utilisateur"
    assert memoire.occupe_par[COORD] == "invite"


def test_saisie_de_l_utilisateur_prefixee_de_notre_texte_non_reconnue(projet, tmux, monkeypatch):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD, resume="regarde ceci")
    texte = f"Assistant : regarde ceci (#{m})"
    memoire = livraison.Memoire()
    affichage_differe(monkeypatch, tmux, [texte[:9]])
    tour(projet, memoire)
    monkeypatch.setattr(livraison, "_tmux", tmux)
    tmux.sessions[S_COORD]["invite"] = texte + "x"          # notre texte, puis une lettre de l'utilisateur
    tour(projet, memoire)
    assert bspaces(tmux) == [] and tmux.sessions[S_COORD]["invite"] == texte + "x"
    assert tmux.entrees == []


def test_facteur_neuf_sans_memoire_comportement_d_avant(projet, tmux):
    repos(projet, COORD)
    poster(projet, ASSISTANT, COORD, resume="regarde ceci")
    tmux.sessions[S_COORD]["invite"] = "Assistant : regarde ceci (#1)"
    memoire = livraison.Memoire()
    tour(projet, memoire)
    assert bspaces(tmux) == [] and tmux.entrees == [] and memoire.occupe_par[COORD] == "invite"


# --- le reste de notre frappe après un redémarrage du facteur : le registre, pas la mémoire ----

def _tmux_attache(monkeypatch, tmux):
    """Le facteur a été relancé : l'écran n'est plus différé, la mémoire est neuve."""
    monkeypatch.setattr(livraison, "_tmux", tmux)


def _executer(projet, requete, *args):
    conn = ouvrir(projet)
    try:
        with conn:
            conn.execute(requete, args)
    finally:
        conn.close()


def test_facteur_redemarre_efface_le_reste_de_sa_frappe_d_apres_le_registre(projet, tmux, monkeypatch):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD, resume="regarde ceci")
    texte = f"Assistant : regarde ceci (#{m})"
    affichage_differe(monkeypatch, tmux, [texte[:9]])
    tour(projet)                                            # (e) : courrier echoue, texte resté à l'invite
    assert courriers(projet)[0][3] == "echoue" and tmux.sessions[S_COORD]["invite"] == texte
    _tmux_attache(monkeypatch, tmux)
    tour(projet, livraison.Memoire())
    assert bspaces(tmux) and tmux.entrees == [(S_COORD, texte)] and etat(projet, m) == "livre"


def test_facteur_redemarre_texte_replie_d_apres_le_registre_efface(projet, tmux, monkeypatch):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD, resume="regarde ceci")
    texte = f"Assistant : regarde ceci (#{m})"
    affichage_differe(monkeypatch, tmux, [texte[:9]])
    tour(projet)
    _tmux_attache(monkeypatch, tmux)
    # le faux compte les caractères (la TUI, un marqueur) : le repli tient dans les BSpace de notre texte
    tmux.sessions[S_COORD]["invite"] = "[Pasted text #1]" + texte[-12:]
    tour(projet, livraison.Memoire())
    assert bspaces(tmux) and tmux.entrees == [(S_COORD, texte)] and etat(projet, m) == "livre"


def test_facteur_redemarre_saisie_de_l_utilisateur_jamais_effacee_d_apres_le_registre(projet, tmux, monkeypatch):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD, resume="regarde ceci")
    texte = f"Assistant : regarde ceci (#{m})"
    affichage_differe(monkeypatch, tmux, [texte[:9]])
    tour(projet)
    _tmux_attache(monkeypatch, tmux)
    tmux.sessions[S_COORD]["invite"] = "brouillon de l'utilisateur"
    memoire = livraison.Memoire()
    tour(projet, memoire)
    assert bspaces(tmux) == [] and tmux.entrees == []
    assert tmux.sessions[S_COORD]["invite"] == "brouillon de l'utilisateur"
    assert memoire.occupe_par[COORD] == "invite"


def test_facteur_redemarre_texte_du_registre_plus_une_lettre_non_efface(projet, tmux, monkeypatch):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD, resume="regarde ceci")
    texte = f"Assistant : regarde ceci (#{m})"
    affichage_differe(monkeypatch, tmux, [texte[:9]])
    tour(projet)
    _tmux_attache(monkeypatch, tmux)
    tmux.sessions[S_COORD]["invite"] = texte + "x"
    tour(projet, livraison.Memoire())
    assert bspaces(tmux) == [] and tmux.entrees == [] and tmux.sessions[S_COORD]["invite"] == texte + "x"


def test_facteur_redemarre_dernier_courrier_acquitte_rien_n_est_efface(projet, tmux, monkeypatch):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD, resume="regarde ceci")
    texte = f"Assistant : regarde ceci (#{m})"
    affichage_differe(monkeypatch, tmux, [texte[:9]])
    tour(projet)
    _executer(projet, "UPDATE courriers SET etat = 'acquitte' WHERE id = 1")
    poster(projet, ASSISTANT, COORD, resume="autre")        # un message attend : la livraison regarde l'invite
    _tmux_attache(monkeypatch, tmux)
    memoire = livraison.Memoire()
    tour(projet, memoire)
    assert bspaces(tmux) == [] and tmux.entrees == [] and tmux.sessions[S_COORD]["invite"] == texte
    assert memoire.occupe_par[COORD] == "invite"


def test_facteur_redemarre_courrier_echoue_plus_ancien_rien_n_est_efface(projet, tmux, monkeypatch):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD, resume="regarde ceci")
    texte = f"Assistant : regarde ceci (#{m})"
    affichage_differe(monkeypatch, tmux, [texte[:9]])
    tour(projet)                                            # courrier 1 : echoue, son texte à l'invite
    _executer(projet, "INSERT INTO courriers (a, voie, cree, expire, etat, tentative)"
                      " VALUES (?, 'tmux', '2026-10-12T00:00:00.000Z', '2026-10-12T00:00:00.000Z',"
                      " 'acquitte', 1)", COORD)            # courrier 2 : le plus récent de l'agent, acquitté
    poster(projet, ASSISTANT, COORD, resume="autre")
    _tmux_attache(monkeypatch, tmux)
    tour(projet, livraison.Memoire())
    assert bspaces(tmux) == [] and tmux.entrees == [] and tmux.sessions[S_COORD]["invite"] == texte


def test_facteur_redemarre_enter_envoye_puis_echoue_rien_n_est_efface(projet, tmux, monkeypatch):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD, resume="regarde ceci")
    texte = f"Assistant : regarde ceci (#{m})"
    affichage_differe(monkeypatch, tmux, [texte[:9]])
    tour(projet)
    _executer(projet, "UPDATE transitions SET preuve = json_set(preuve, '$.tmux_rc', 0) WHERE courrier_id = 1"
                      " AND etat = 'livre'")                # un Enter a bien été envoyé pour ce courrier
    poster(projet, ASSISTANT, COORD, resume="autre")
    _tmux_attache(monkeypatch, tmux)
    memoire = livraison.Memoire()
    tour(projet, memoire)
    assert bspaces(tmux) == [] and tmux.entrees == [] and memoire.occupe_par[COORD] == "invite"


def test_facteur_redemarre_message_long_par_fichier_reconnu(projet, tmux, monkeypatch):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD, resume="long")
    _executer(projet, "UPDATE messages SET corps = ? WHERE id = ?", "x" * 900, m)
    affichage_differe(monkeypatch, tmux, ["Assistant"])
    tour(projet)
    assert courriers(projet)[0][3] == "echoue" and ".orga/etat/courrier/" in tmux.sessions[S_COORD]["invite"]
    _tmux_attache(monkeypatch, tmux)
    tour(projet, livraison.Memoire())
    assert len(bspaces(tmux)) > 0 and len(tmux.entrees) == 1 and ".orga/etat/courrier/" in tmux.entrees[0][1]
    assert etat(projet, m) == "livre"


def test_facteur_redemarre_message_disparu_rien_n_est_efface(projet, tmux, monkeypatch):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD, resume="regarde ceci")
    texte = f"Assistant : regarde ceci (#{m})"
    affichage_differe(monkeypatch, tmux, [texte[:9]])
    tour(projet)
    _executer(projet, "DELETE FROM messages WHERE id = ?", m)   # le texte du courrier ne se recalcule plus
    poster(projet, ASSISTANT, COORD, resume="autre")
    _tmux_attache(monkeypatch, tmux)
    tour(projet, livraison.Memoire())
    assert bspaces(tmux) == [] and tmux.entrees == [] and tmux.sessions[S_COORD]["invite"] == texte


# --- une invite plus haute que sa fenêtre : la TUI ne montre que la fin de notre texte -----

CORPS_LONG = " ".join(f"mot{i:03d}" for i in range(80))   # une ligne tmux (≤ 600), plusieurs à l'écran


def message_long(projet, m):
    """Le corps de `m` devient CORPS_LONG ; renvoie le texte livré à l'invite."""
    conn = ouvrir(projet)
    try:
        with conn:
            conn.execute("UPDATE messages SET corps = ? WHERE id = ?", (CORPS_LONG, m))
    finally:
        conn.close()
    return f"Assistant : {CORPS_LONG} (#{m})"


def defile(texte, lignes, largeur=60):
    """Ce que la TUI montre d'une saisie plus haute que sa fenêtre : ses `lignes` dernières tranches."""
    tranches = [texte[i:i + largeur] for i in range(0, len(texte), largeur)]
    return "\n  ".join(tranches[-lignes:])


def test_fenetre_defilee_suffixe_de_notre_texte_un_enter(projet, tmux, monkeypatch):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD)
    texte = message_long(projet, m)
    affichage_differe(monkeypatch, tmux, [defile(texte, 7)])
    tour(projet)
    assert tmux.entrees == [(S_COORD, texte)] and etat(projet, m) == "livre"
    assert preuves(projet, "livre", m)[0]["replie"] is True
    assert signalements(projet, "collision-invite") == []


@pytest.mark.parametrize("lignes, largeur", [(2, 60), (7, 4)], ids=["deux-lignes", "vingt-huit-caracteres"])
def test_fenetre_defilee_trop_courte_reste_une_collision(projet, tmux, monkeypatch, lignes, largeur):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD)
    texte = message_long(projet, m)
    affichage_differe(monkeypatch, tmux, [defile(texte, lignes, largeur)])
    tour(projet)
    assert tmux.entrees == [] and bspaces(tmux) == [] and courriers(projet)[0][3] == "echoue"
    assert len(signalements(projet, "collision-invite")) == 1


def test_fenetre_d_un_autre_texte_reste_une_collision(projet, tmux, monkeypatch):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD)
    texte = message_long(projet, m)
    affichage_differe(monkeypatch, tmux, [defile("une autre saisie sans rapport, " * 12, 7)])
    tour(projet)
    assert tmux.entrees == [] and bspaces(tmux) == [] and courriers(projet)[0][3] == "echoue"
    assert len(signalements(projet, "collision-invite")) == 1


def test_fenetre_en_cours_de_frappe_on_attend_puis_un_enter(projet, tmux, monkeypatch):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD)
    texte = message_long(projet, m)
    # une fenêtre au milieu du texte (sous-chaîne, pas un suffixe), puis la fin : la TUI a fini de taper
    affichage_differe(monkeypatch, tmux, [defile(texte[:-200], 7), defile(texte, 7)])
    tour(projet)
    assert tmux.entrees == [(S_COORD, texte)] and etat(projet, m) == "livre"
    assert signalements(projet, "collision-invite") == []


def test_reste_fenetre_defilee_efface_puis_refrappe(projet, tmux, monkeypatch):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD)
    texte = message_long(projet, m)
    memoire = livraison.Memoire()
    memoire.frappes_perdues[COORD] = texte                  # notre texte complet, resté à l'invite
    tmux.sessions[S_COORD]["invite"] = defile(texte, 7)      # l'écran n'en montre que la fin
    tour(projet, memoire)
    assert sum(a.count("BSpace") for a in bspaces(tmux)) == len(texte)
    assert tmux.entrees == [(S_COORD, texte)] and etat(projet, m) == "livre"


def test_facteur_redemarre_reste_fenetre_defilee_efface_d_apres_le_registre(projet, tmux, monkeypatch):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD)
    texte = message_long(projet, m)
    affichage_differe(monkeypatch, tmux, [texte[:9]])
    tour(projet)                                            # (e) : courrier echoue, texte resté à l'invite
    assert courriers(projet)[0][3] == "echoue"
    _tmux_attache(monkeypatch, tmux)
    tmux.sessions[S_COORD]["invite"] = defile(texte, 7)     # le facteur neuf ne voit que la fin
    tour(projet, livraison.Memoire())
    assert sum(a.count("BSpace") for a in bspaces(tmux)) == len(texte)
    assert tmux.entrees == [(S_COORD, texte)] and etat(projet, m) == "livre"


# --- les tentatives -----------------------------------------------------------------------

def _dater_courrier(projet, instant):
    """Le courrier ouvert a été créé à l'instant simulé `instant` (horloge de test)."""
    conn = ouvrir(projet)
    conn.execute("UPDATE courriers SET cree = ? WHERE etat = 'ouvert'", (livraison._iso(instant),))
    conn.commit()
    conn.close()


def test_quatre_tentatives_sans_accuse_puis_echec_et_signalement(projet, tmux):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD, resume="important")
    memoire = livraison.Memoire()
    t0 = maintenant(10)
    facteur.tour(projet, t0, memoire)                       # +0
    _dater_courrier(projet, t0)
    facteur.tour(projet, t0 + timedelta(seconds=20), memoire)
    assert len(tmux.entrees) == 1                           # < 30 s : on attend
    t1 = t0 + timedelta(seconds=31)
    facteur.tour(projet, t1, memoire)                       # +30 s
    _dater_courrier(projet, t1)
    t2 = t1 + timedelta(seconds=91)
    facteur.tour(projet, t2, memoire)                       # +2 min
    _dater_courrier(projet, t2)
    t3 = t2 + timedelta(seconds=181)
    facteur.tour(projet, t3, memoire)                       # +5 min
    _dater_courrier(projet, t3)
    assert len(tmux.entrees) == 4 and courriers(projet)[-1][4] == 4
    facteur.tour(projet, t3 + timedelta(seconds=10), memoire)
    assert etat(projet, m) == "ouvert" or etat(projet, m) == "livre"
    facteur.tour(projet, t3 + timedelta(seconds=31), memoire)
    assert etat(projet, m) == "echec"
    assert preuves(projet, "echec", m)[0]["tentatives"] == 4
    assert signalements(projet, "livraison") == [(ASSISTANT, f"livraison:{m}", "signalement")]
    facteur.tour(projet, t3 + timedelta(seconds=90), memoire)
    assert len(tmux.entrees) == 4 and len(signalements(projet, "livraison")) == 1


def test_un_agent_au_travail_n_est_pas_un_echec_avant_dix_minutes(projet, tmux):
    evt(projet, COORD, "UserPromptSubmit")
    m = poster(projet, ASSISTANT, COORD)
    memoire = livraison.Memoire()
    tour(projet, memoire, decalage=9 * 60)
    assert signalements(projet, "occupe") == []
    tour(projet, memoire, decalage=11 * 60)
    assert signalements(projet, "occupe") == [(ASSISTANT, f"occupe:{COORD}", "signalement")]
    tour(projet, memoire, decalage=12 * 60)
    assert len(signalements(projet, "occupe")) == 1        # une seule fois
    assert etat(projet, m) == "inscrit"


def test_collisions_repetees_epuisent_les_tentatives(projet, tmux):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD)
    memoire = livraison.Memoire()
    for _ in range(4):
        tmux.sessions[S_COORD]["invite"] = ""
        tmux.apres_capture[:] = [lambda t, n: t.frapper(S_COORD, "z") if n % 2 == 0 else None]
        tmux.captures = 0
        tour(projet, memoire)
    tmux.apres_capture.clear()
    tmux.sessions[S_COORD]["invite"] = ""
    tour(projet, memoire)
    assert etat(projet, m) == "echec" and len(signalements(projet, "livraison")) == 1


# --- reprise, sessions absentes, sessions disparues -----------------------------

def _courrier_tmux_perime(projet, a, ids):
    conn = ouvrir(projet)
    c = courrier.prendre(conn, a, "tmux", "cime", {"capture_avant": "vide"}, bail_s=-5)
    conn.close()
    return c


def test_redemarrage_le_courrier_perime_est_redonne_avec_la_tentative_suivante(projet, tmux):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD)
    c = _courrier_tmux_perime(projet, COORD, [m])          # le facteur est mort après la frappe
    assert etat(projet, m) == "livre"
    tour(projet)                                            # un nouveau facteur : mémoire vierge
    assert [r[3] for r in courriers(projet)] == ["echoue", "ouvert"]
    assert courriers(projet)[1][4] == 2 and len(tmux.entrees) == 1
    assert preuves(projet, "inscrit", m)[-1]["reprise"] == c.id


def test_redemarrage_sans_redonner_ce_dont_l_accuse_est_ecrit(projet, tmux, monkeypatch, capsys):
    repos(projet, COORD)
    a = poster(projet, ASSISTANT, COORD, resume="un")
    b = poster(projet, ASSISTANT, COORD, resume="deux")
    _courrier_tmux_perime(projet, COORD, [a, b])
    conn = ouvrir(projet)
    courrier.acquitter(conn, a, COORD, {"evenement": "UserPromptSubmit", "evenement_id": 1})
    conn.close()
    tour(projet)
    assert etat(projet, a) == "clos"
    assert len(tmux.entrees) == 1 and f"#{b}" in tmux.entrees[0][1] and f"#{a}" not in tmux.entrees[0][1]


def test_session_absente_signalee_une_fois_par_message(projet, tmux):
    m = poster(projet, ASSISTANT, "coord-y", resume="où es-tu")      # pas de session essai-coord-y
    memoire = livraison.Memoire()
    tour(projet, memoire, decalage=60)
    assert signalements(projet, "session-absente") == []
    tour(projet, memoire, decalage=150)
    assert signalements(projet, "session-absente") == [(ASSISTANT, "session-absente:coord-y",
                                                        "signalement")]
    tour(projet, memoire, decalage=300)
    assert len(signalements(projet, "session-absente")) == 1
    m2 = poster(projet, ASSISTANT, "coord-y", resume="encore")
    tour(projet, memoire, decalage=500)
    assert len(signalements(projet, "session-absente")) == 2 and etat(projet, m) == "inscrit"


def test_session_disparue_signalee_au_superieur_une_fois_tant_que_l_agent_ne_revient_pas(projet, tmux):
    evt(projet, WORKER, "SessionStart")
    del tmux.sessions[S_WORKER]
    tour(projet)
    assert signalements(projet, "session-disparue") == [(COORD, f"session-disparue:{WORKER}",
                                                         "signalement")]
    tour(projet)
    assert len(signalements(projet, "session-disparue")) == 1
    tmux.sessions[S_WORKER] = {"invite": "", "activite": time.time() - 100}   # il revient…
    evt(projet, WORKER, "SessionStart")
    del tmux.sessions[S_WORKER]                                               # …et disparaît encore
    tour(projet)
    assert len(signalements(projet, "session-disparue")) == 2


def test_session_finie_proprement_n_est_pas_disparue(projet, tmux):
    evt(projet, WORKER, "SessionStart")
    evt(projet, WORKER, "SessionEnd", reason="other")
    del tmux.sessions[S_WORKER]
    tour(projet)
    assert signalements(projet, "session-disparue") == []


def test_sans_aucune_session_connue_pas_d_appel_a_tmux(projet, tmux):
    tour(projet)
    assert tmux.appels == []


def test_un_message_clos_dans_un_courrier_perime_n_est_pas_relivre(projet, tmux):
    """Un accord livré puis consommé (`clos`) ne repasse pas `inscrit` quand son courrier échoue ;
    son voisin encore `livre` si."""
    repos(projet, COORD)
    clos = poster(projet, ASSISTANT, COORD, resume="accord consommé")
    voisin = poster(projet, ASSISTANT, COORD, resume="voisin")
    c = _courrier_tmux_perime(projet, COORD, [clos, voisin])
    conn = ouvrir(projet)
    inscrire_transition(conn, clos, "clos", "cime", {"par_evenement": 1})
    conn.close()
    assert etat(projet, clos) == "clos" and etat(projet, voisin) == "livre"
    tour(projet)                                            # le courrier périmé échoue (reprise)
    assert [r[3] for r in courriers(projet)][0] == "echoue"
    assert etat(projet, clos) == "clos"
    suite = [e for (e,) in lignes(projet, "SELECT etat FROM transitions WHERE message_id = ? ORDER BY id",
                                  (clos,))]
    assert suite[-2:] == ["livre", "clos"] and suite.count("livre") == 1
    assert preuves(projet, "inscrit", voisin)[-1]["reprise"] == c.id
    assert len(tmux.entrees) == 1 and f"#{voisin}" in tmux.entrees[0][1] and f"#{clos}" not in tmux.entrees[0][1]


# --- mesures de la zone et du pane, dans la preuve d'une frappe échouée (jamais de texte) ---

def test_collision_la_preuve_porte_les_mesures_de_la_zone(projet, tmux, monkeypatch):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD, resume="regarde ceci")
    texte = f"Assistant : regarde ceci (#{m})"
    vu = texte + "x"
    affichage_differe(monkeypatch, tmux, [vu])
    tour(projet)
    preuve = _reprise_de(projet, m)
    assert preuve["zone"] == {"capture_lignes": 4, "regles": [0, 2], "zone_haut": 1, "zone_lignes": 1,
                              "visible_par_ligne": [len("".join(vu.split()))],
                              "attenue_perdu": 0, "attenue_ligne0": 0}
    _sans_texte(preuve, texte)


def test_pane_releve_une_seule_fois_a_l_abandon(projet, tmux, monkeypatch):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD, resume="regarde ceci")
    texte = f"Assistant : regarde ceci (#{m})"
    affichage_differe(monkeypatch, tmux, [texte + "x"])
    tour(projet)
    assert _reprise_de(projet, m)["pane"] == [78, 45]
    releves = [a for a in tmux.appels if a[0] == "display-message" and "#{pane_width} #{pane_height}" in a]
    assert len(releves) == 1


def test_pane_illisible_la_cle_est_absente(projet, tmux, monkeypatch):
    repos(projet, COORD)
    m = poster(projet, ASSISTANT, COORD, resume="regarde ceci")
    texte = f"Assistant : regarde ceci (#{m})"
    affichage_differe(monkeypatch, tmux, [texte + "x"])
    sous = livraison._tmux

    def sans_pane(*args):
        if args[0] == "display-message" and "#{pane_width} #{pane_height}" in args:
            return subprocess.CompletedProcess(args, 1, "", "no server")
        return sous(*args)

    monkeypatch.setattr(livraison, "_tmux", sans_pane)
    tour(projet)
    preuve = _reprise_de(projet, m)
    assert "pane" not in preuve and preuve["collision"] is True
