"""`cime fermer` / `cime rouvrir` : un faux tmux, un faux
`lancer._lancer`, aucun vrai `kill`. Rien n'est lancé ni tué pour de vrai."""
import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

from cime import cli
from cime.fondation import fermeture, lancer
from cime.fondation.nom import VAR_AGENT, VAR_PROJET
from cime.fondation.registre import (
    horodatage, inscrire_evenement, inscrire_message, inscrire_transition, ouvrir,
)
from cime.signaux import obligations

MANIFESTE = textwrap.dedent("""\
    nom = "Essai"
    prefixe = "essai"
    branche_reference = "main"
    branche_equipe = "equipe/{equipe}"
    worktree_equipe = ".orga/worktrees/{equipe}"
    equipes_speciales = ["assistant"]
    modele_assistant = "modele-assistant"
    modele_coordinateur = "modele-coord"
""")


def _cp(code=0, sortie=""):
    return subprocess.CompletedProcess([], code, sortie, "")


class FauxTmux:
    """Remplace `fermeture._tmux` : sessions vivantes, `kill-session` enregistrés."""

    def __init__(self, projet):
        self.projet = projet
        self.sessions = set()
        self.kills = []
        self.repere_au_kill = []
        self.evenement_au_kill = []

    def __call__(self, *args):
        if args[0] == "list-sessions":
            return _cp(0, "".join(f"{s}\n" for s in sorted(self.sessions)))
        if args[0] == "kill-session":
            nom = args[args.index("-t") + 1].lstrip("=")
            self.kills.append(nom)
            self.repere_au_kill.append(fermeture.est_ferme(self.projet))
            self.evenement_au_kill.append(bool(evenements(self.projet, "ProjetFerme")))
            self.sessions.discard(nom)
            return _cp(0)
        return _cp(0)


class FauxLancer:
    """Remplace `lancer._lancer` : enregistre chaque lancement, rend (session, code)."""

    def __init__(self, projet, tmux):
        self.projet, self.tmux = projet, tmux
        self.lances = []
        self.codes = {}      # "assistant" | équipe -> code rendu
        self.erreurs = {}    # "assistant" | équipe -> exception levée

    def __call__(self, args, projet=None, attacher=False):
        cle = "assistant" if args.role == "assistant" else args.equipe
        self.lances.append({"cle": cle, "role": args.role, "session": args.session,
                            "reprendre": args.reprendre, "attacher": attacher,
                            "repere_present": fermeture.est_ferme(self.projet)})
        if cle in self.erreurs:
            raise self.erreurs[cle]
        nom = "essai-assistant" if cle == "assistant" else f"essai-coord-{cle}"
        self.tmux.sessions.add(nom)
        return nom, self.codes.get(cle, 0)


@pytest.fixture
def projet(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    racine = (tmp_path / "depot").resolve()
    for equipe in ("hote", "page", "scene", "vieux"):
        for sous in ("todo", "in-progress", "done"):
            (racine / ".orga/teams" / equipe / "tasks" / sous).mkdir(parents=True)
        (racine / ".orga/teams" / equipe / "mandate.md").write_text("mandat")
    (racine / ".orga/teams/vieux/CLOTUREE").write_text("")
    (racine / ".orga/projet.toml").write_text(MANIFESTE)
    ailleurs = tmp_path / "ailleurs"
    ailleurs.mkdir()
    monkeypatch.chdir(ailleurs)          # aucune commande ne doit dépendre du dossier courant
    return racine


@pytest.fixture
def tmux(projet, monkeypatch):
    faux = FauxTmux(projet)
    monkeypatch.setattr(fermeture, "_tmux", faux)
    return faux


@pytest.fixture
def lanceur(projet, tmux, monkeypatch):
    faux = FauxLancer(projet, tmux)
    monkeypatch.setattr(lancer, "_lancer", faux)
    facteurs = []
    monkeypatch.setattr(lancer, "_demarrer_facteur",
                        lambda p=None: facteurs.append(fermeture.est_ferme(projet)))
    faux.facteurs = facteurs
    return faux


@pytest.fixture(autouse=True)
def hote(monkeypatch):
    """Jamais de vrai `lsof` ni de vrai `kill` : les pids et les signaux sont enregistrés."""
    etat = {"ecoutants": [], "tues": [], "ports": []}

    def ecoutants(port):
        etat["ports"].append(port)
        return list(etat["ecoutants"])
    monkeypatch.setattr(fermeture, "_pids_ecoutant", ecoutants)
    monkeypatch.setattr(fermeture, "_tuer", lambda pid: etat["tues"].append(pid))
    return etat


def evt(projet, agent, nom, session_id="s", **details):
    conn = ouvrir(projet)
    try:
        return inscrire_evenement(conn, agent=agent, session_id=session_id, evenement=nom,
                                  details=details)
    finally:
        conn.close()


def evenements(projet, nom):
    conn = ouvrir(projet)
    try:
        return conn.execute("SELECT agent, session_id, details FROM evenements WHERE evenement = ?"
                            " ORDER BY id", (nom,)).fetchall()
    finally:
        conn.close()


def conversation(dossier, session, mtime=1000):
    sous = lancer.dossier_conversations(dossier)
    sous.mkdir(parents=True, exist_ok=True)
    f = sous / f"{session}.jsonl"
    f.write_text("{}")
    os.utime(f, (mtime, mtime))
    return f


def cime(capsys, *argv, agent=None, claudecode=False, monkeypatch=None):
    if monkeypatch is not None:
        monkeypatch.delenv(VAR_AGENT, raising=False)
        monkeypatch.delenv("CLAUDECODE", raising=False)
        if agent:
            monkeypatch.setenv(VAR_AGENT, agent)
        if claudecode:
            monkeypatch.setenv("CLAUDECODE", "1")
    code = cli.main(list(argv))
    sortie = capsys.readouterr()
    return code, sortie.out, sortie.err


@pytest.fixture
def lancement(capsys, monkeypatch):
    def aller(*argv, agent=None, claudecode=False):
        return cime(capsys, *argv, agent=agent, claudecode=claudecode, monkeypatch=monkeypatch)
    return aller


def objet_json(sortie):
    lignes = [l for l in sortie.strip().splitlines() if l.startswith("{")]
    return json.loads(lignes[-1])


@pytest.fixture
def monde(projet, tmux):
    """Un assistant, deux coordinateurs au travail (un avec worker, un avec tâche), un coordinateur
    sans rien, et leurs conversations."""
    evt(projet, "assistant", "SessionStart", "a-vieille")
    evt(projet, "assistant", "SessionStart", "a-recente")
    evt(projet, "assistant", "Stop", "a-recente")
    evt(projet, "coord-hote", "SessionStart", "h-1")
    evt(projet, "coord-hote", "Stop", "h-1")
    evt(projet, "worker-hote-route-x", "SessionStart", "w-1")
    evt(projet, "worker-hote-route-x", "Stop", "w-1")
    evt(projet, "coord-page", "SessionStart", "p-1")
    evt(projet, "coord-page", "Stop", "p-1")
    evt(projet, "coord-scene", "SessionStart", "s-1")
    evt(projet, "coord-scene", "Stop", "s-1")
    (projet / ".orga/teams/page/tasks/in-progress/vue-y.md").write_text("t")
    (projet / ".orga/teams/hote/tasks/in-progress/route-x.md").write_text("t")
    tmux.sessions |= {"essai-assistant", "essai-coord-hote", "essai-worker-hote-route-x",
                      "essai-coord-page", "essai-coord-scene"}
    return projet


# --- le repère ferme.json -----------------------------------------------------------------

def test_repere_absent_puis_ecrit_puis_relu(projet):
    assert fermeture.est_ferme(projet) is False and fermeture.lire_repere(projet) is None
    donnees = {"heure": "2026-10-12T22:14:03+02:00", "conversations": [], "a_relancer": ["assistant"],
               "raisons": {"assistant": "assistant"}, "taches_en_cours": []}
    fermeture.ecrire_repere(projet, donnees)
    assert fermeture.est_ferme(projet) is True
    assert fermeture.lire_repere(projet) == donnees
    assert (projet / ".orga/etat/ferme.json").is_file()


def test_ecriture_atomique_pas_de_fichier_temporaire_restant(projet):
    fermeture.ecrire_repere(projet, {"conversations": []})
    fermeture.ecrire_repere(projet, {"conversations": [{"agent": "assistant"}]})
    assert sorted(p.name for p in (projet / ".orga/etat").iterdir() if p.name != "registre.sqlite"
                  and not p.name.startswith("registre.sqlite")) == ["ferme.json"]


def test_ecriture_atomique_l_ancien_repere_survit_a_un_echec(projet, monkeypatch):
    fermeture.ecrire_repere(projet, {"conversations": [], "ancien": True})

    def casse(*a, **k):
        raise OSError("disque plein")
    monkeypatch.setattr(os, "replace", casse)
    with pytest.raises(OSError):
        fermeture.ecrire_repere(projet, {"nouveau": True})
    monkeypatch.undo()
    assert fermeture.lire_repere(projet)["ancien"] is True


@pytest.mark.parametrize("contenu", ["", "{pas du json", "[1, 2]", "null", '"texte"'])
def test_repere_illisible_est_ferme_et_ne_leve_jamais(projet, contenu):
    (projet / ".orga/etat").mkdir(parents=True)
    (projet / ".orga/etat/ferme.json").write_text(contenu)
    assert fermeture.est_ferme(projet) is True
    repere = fermeture.lire_repere(projet)
    assert repere["illisible"] is True
    assert repere["conversations"] == [] and repere["a_relancer"] == []


def test_repere_octets_invalides_ne_leve_pas(projet):
    (projet / ".orga/etat").mkdir(parents=True)
    (projet / ".orga/etat/ferme.json").write_bytes(b"\xff\xfe\x00")
    assert fermeture.est_ferme(projet) is True
    assert fermeture.lire_repere(projet)["illisible"] is True


# --- le plan (fonction pure) --------------------------------------------------------------

def plan(**faits):
    base = dict(prefixe="essai", sessions=set(), session_de={}, equipes_connues=["hote", "page", "scene"],
                coordinables=["hote", "page", "scene"], taches=[], debiteurs=set(), en_attente=set())
    return fermeture.calculer_plan(**{**base, **faits})


def test_plan_assistant_toujours_relance_meme_sans_session():
    p = plan()
    assert p["a_relancer"] == ["assistant"] and p["raisons"] == {"assistant": "assistant"}
    assert p["conversations"] == [] and p["taches_en_cours"] == []


def test_plan_conversations_dernier_session_id_des_sessions_vivantes_seulement():
    p = plan(sessions={"essai-assistant", "essai-coord-hote", "essai-worker-hote-route-x", "autre-chose"},
             session_de={"assistant": "a1", "coord-hote": "h1", "worker-hote-route-x": "w1",
                         "coord-page": "p1"})
    assert p["conversations"] == [
        {"agent": "assistant", "session": "a1", "tmux": "essai-assistant"},
        {"agent": "coord-hote", "session": "h1", "tmux": "essai-coord-hote", "equipe": "hote"},
        {"agent": "worker-hote-route-x", "session": "w1", "tmux": "essai-worker-hote-route-x",
         "equipe": "hote"}]


def test_plan_agent_vivant_sans_conversation_connue_n_est_pas_compte():
    p = plan(sessions={"essai-assistant", "essai-coord-hote"}, session_de={"assistant": "a1"})
    assert [c["agent"] for c in p["conversations"]] == ["assistant"]


def test_plan_coordinateur_avec_worker_vivant_est_a_relancer_pour_travail():
    p = plan(sessions={"essai-worker-page-vue-y"})
    assert p["a_relancer"] == ["assistant", "coord-page"]
    assert p["raisons"]["coord-page"] == "travail"


def test_plan_coordinateur_avec_tache_en_cours_de_son_equipe():
    p = plan(taches=["scene/prise-1", "vieux/ancienne"])
    assert p["a_relancer"] == ["assistant", "coord-scene"]
    assert p["raisons"]["coord-scene"] == "travail"
    assert p["taches_en_cours"] == ["scene/prise-1", "vieux/ancienne"]


def test_plan_coordinateur_avec_obligation_ouverte_dont_il_est_debiteur():
    p = plan(debiteurs={"coord-hote", "worker-hote-t", "assistant"})
    assert p["a_relancer"] == ["assistant", "coord-hote"]
    assert p["raisons"]["coord-hote"] == "travail"


def test_plan_coordinateur_avec_message_en_attente_raison_message():
    p = plan(en_attente={"coord-page"})
    assert p["a_relancer"] == ["assistant", "coord-page"]
    assert p["raisons"]["coord-page"] == "message"


def test_plan_travail_l_emporte_sur_message():
    p = plan(en_attente={"coord-page"}, taches=["page/t"])
    assert p["raisons"]["coord-page"] == "travail"


def test_plan_coordinateur_sans_travail_ni_message_n_est_pas_relance():
    p = plan(sessions={"essai-coord-scene"}, session_de={"coord-scene": "s1"})
    assert p["a_relancer"] == ["assistant"]


def test_plan_un_worker_n_est_jamais_relance_meme_avec_message_ou_dette():
    p = plan(sessions={"essai-worker-hote-t"}, debiteurs={"worker-hote-t"},
             en_attente={"worker-hote-t"}, session_de={"worker-hote-t": "w"})
    assert p["a_relancer"] == ["assistant", "coord-hote"]      # le worker vivant fait relancer son coordinateur
    assert plan(debiteurs={"worker-hote-t"}, en_attente={"worker-hote-t"})["a_relancer"] == ["assistant"]


def test_plan_equipe_cloturee_ou_sans_mandat_pas_de_coordinateur():
    p = plan(coordinables=["hote"], taches=["page/t"], en_attente={"coord-page"})
    assert p["a_relancer"] == ["assistant"]


def test_plan_equipe_au_nom_prefixe_par_une_autre():
    # worker-hote-bis-t appartient à l'équipe hote-bis (plus long préfixe), pas à hote
    p = plan(equipes_connues=["hote", "hote-bis"], coordinables=["hote", "hote-bis"],
             sessions={"essai-worker-hote-bis-t"})
    assert p["a_relancer"] == ["assistant", "coord-hote-bis"]


# --- fermer : appelant -----------------------------------------------------------------

@pytest.mark.parametrize("agent,claudecode", [("coord-hote", False), ("assistant", False),
                                              ("worker-hote-t", False), (None, True)])
def test_fermer_refuse_a_tout_agent(monde, tmux, lancement, agent, claudecode):
    code, sortie, err = lancement("fermer", str(monde), "--json", agent=agent, claudecode=claudecode)
    assert code == 1
    donnees = objet_json(sortie)
    assert donnees["resultat"] == "erreur" and "réservé à l'utilisateur" in donnees["message"]
    assert not fermeture.est_ferme(monde) and tmux.kills == []
    assert evenements(monde, "ProjetFerme") == []


def test_fermer_refus_texte_sur_stderr(monde, lancement):
    code, sortie, err = lancement("fermer", str(monde), agent="assistant")
    assert code == 1 and "réservé à l'utilisateur" in err and sortie == ""


def test_fermer_accepte_utilisateur_pose_par_l_hote(monde, lancement):
    code, _, _ = lancement("fermer", str(monde), "--json", agent="utilisateur")
    assert code == 0 and fermeture.est_ferme(monde)


def test_fermer_projet_inconnu(tmp_path, lancement):
    code, sortie, _ = lancement("fermer", str(tmp_path), "--json")
    assert code == 1 and objet_json(sortie)["resultat"] == "erreur"


# --- fermer : occupés -----------------------------------------------------------------

def test_fermer_refuse_si_un_agent_travaille_code_5_rien_touche(monde, tmux, lancement, hote):
    evt(monde, "coord-hote", "UserPromptSubmit", "h-1")
    code, sortie, _ = lancement("fermer", str(monde), "--json")
    assert code == 5
    donnees = objet_json(sortie)
    assert donnees["resultat"] == "refuse" and donnees["occupes"] == ["coord-hote"]
    assert donnees["message"]
    assert not fermeture.est_ferme(monde) and tmux.kills == [] and hote["tues"] == []
    assert evenements(monde, "ProjetFerme") == []


def test_fermer_refus_texte_nomme_les_occupes(monde, lancement):
    evt(monde, "assistant", "UserPromptSubmit", "a-recente")
    evt(monde, "coord-page", "PostToolUse", "p-1")
    code, sortie, err = lancement("fermer", str(monde))
    assert code == 5 and "assistant" in err and "coord-page" in err and "--forcer" in err


def test_fermer_demande_d_autorisation_ouverte_compte_comme_occupe(monde, tmux, lancement):
    evt(monde, "coord-page", "PermissionRequest", "p-1", demande_id="perm-1", tool_name="Bash")
    code, sortie, _ = lancement("fermer", str(monde), "--json")
    assert code == 5 and objet_json(sortie)["occupes"] == ["coord-page"]
    assert tmux.kills == []


def test_fermer_session_reprise_apres_un_tour_tue_n_est_pas_occupee(monde, lancement):
    evt(monde, "coord-hote", "UserPromptSubmit", "h-1")          # tour interrompu : jamais de Stop
    evt(monde, "coord-hote", "SessionStart", "h-1", source="resume")
    assert lancement("fermer", str(monde), "--json")[0] == 0


def test_fermer_courrier_en_cours_de_livraison_compte_comme_occupe(monde, tmux, lancement):
    conn = ouvrir(monde)
    with conn:
        conn.execute("INSERT INTO courriers (a, voie, cree, expire, etat) VALUES"
                     " ('coord-scene', 'tmux', ?, ?, 'ouvert')", (horodatage(), horodatage()))
    conn.close()
    code, sortie, _ = lancement("fermer", str(monde), "--json")
    assert code == 5 and objet_json(sortie)["occupes"] == ["coord-scene"]
    assert tmux.kills == []


def test_fermer_courrier_acquitte_n_est_pas_occupe(monde, lancement):
    conn = ouvrir(monde)
    with conn:
        conn.execute("INSERT INTO courriers (a, voie, cree, expire, etat) VALUES"
                     " ('coord-scene', 'tmux', ?, ?, 'acquitte')", (horodatage(), horodatage()))
    conn.close()
    assert lancement("fermer", str(monde), "--json")[0] == 0


def test_fermer_forcer_ferme_malgre_les_occupes(monde, tmux, lancement):
    evt(monde, "coord-hote", "UserPromptSubmit", "h-1")
    evt(monde, "coord-page", "PermissionRequest", "p-1", demande_id="perm-2")
    code, sortie, _ = lancement("fermer", str(monde), "--forcer", "--json")
    assert code == 0 and objet_json(sortie)["resultat"] == "ok"
    assert fermeture.est_ferme(monde) and len(tmux.kills) == 5


def test_fermer_utilisateur_n_est_jamais_un_occupe(monde, lancement):
    conn = ouvrir(monde)
    with conn:
        conn.execute("INSERT INTO courriers (a, voie, cree, expire, etat) VALUES"
                     " ('utilisateur', 'hote', ?, ?, 'ouvert')", (horodatage(), horodatage()))
    conn.close()
    assert lancement("fermer", str(monde), "--json")[0] == 0


# --- fermer : le déroulé ---------------------------------------------------------------

def test_fermer_ecrit_le_repere_et_l_evenement_avant_les_kill(monde, tmux, lancement):
    code, _, _ = lancement("fermer", str(monde), "--json")
    assert code == 0 and len(tmux.kills) == 5
    assert tmux.repere_au_kill == [True] * 5
    assert tmux.evenement_au_kill == [True] * 5


def test_fermer_ferme_chaque_session_du_prefixe_et_seulement_celles_la(monde, tmux, lancement):
    tmux.sessions |= {"autreprojet-assistant", "essai-integration-r1"}
    lancement("fermer", str(monde), "--json")
    assert sorted(tmux.kills) == sorted(["essai-assistant", "essai-coord-hote", "essai-coord-page",
                                         "essai-coord-scene", "essai-worker-hote-route-x",
                                         "essai-integration-r1"])
    assert tmux.sessions == {"autreprojet-assistant"}


def test_fermer_sortie_json_et_contenu_du_repere(monde, lancement):
    code, sortie, _ = lancement("fermer", str(monde), "--json")
    donnees = objet_json(sortie)
    assert donnees == {
        "resultat": "ok",
        "conversations": [
            {"agent": "assistant", "session": "a-recente", "tmux": "essai-assistant"},
            {"agent": "coord-hote", "session": "h-1", "tmux": "essai-coord-hote", "equipe": "hote"},
            {"agent": "coord-page", "session": "p-1", "tmux": "essai-coord-page", "equipe": "page"},
            {"agent": "coord-scene", "session": "s-1", "tmux": "essai-coord-scene",
             "equipe": "scene"},
            {"agent": "worker-hote-route-x", "session": "w-1",
             "tmux": "essai-worker-hote-route-x", "equipe": "hote"}],
        "taches_en_cours": ["hote/route-x", "page/vue-y"]}
    repere = fermeture.lire_repere(monde)
    assert repere["conversations"] == donnees["conversations"]
    assert repere["taches_en_cours"] == donnees["taches_en_cours"]
    assert repere["a_relancer"] == ["assistant", "coord-hote", "coord-page"]
    assert repere["raisons"] == {"assistant": "assistant", "coord-hote": "travail",
                                 "coord-page": "travail"}
    assert repere["heure"].count("T") == 1 and repere["heure"][-6] in "+-"


def test_fermer_sortie_texte(monde, lancement):
    code, sortie, _ = lancement("fermer", str(monde))
    assert code == 0 and sortie.strip() == "fermé, 5 conversations gardées"


def test_fermer_ne_demande_ni_projet_courant_ni_agent(monde, lancement, monkeypatch):
    monkeypatch.delenv(VAR_PROJET, raising=False)
    assert lancement("fermer", str(monde), "--json")[0] == 0


def test_fermer_journalise_l_evenement_avec_l_auteur(monde, lancement):
    lancement("fermer", str(monde), "--json", "--forcer")
    (ligne,) = evenements(monde, "ProjetFerme")
    details = json.loads(ligne[2])
    assert ligne[0] is None and details["auteur"] == "utilisateur" and details["forcer"] is True
    conn = ouvrir(monde)
    journal = conn.execute("SELECT auteur, action, resultat FROM journal").fetchall()
    conn.close()
    assert journal == [("utilisateur", "fermer", "ok")]


def test_fermer_idempotente_rien_refait(monde, tmux, lancement, hote):
    premier = objet_json(lancement("fermer", str(monde), "--json")[1])
    avant = fermeture.lire_repere(monde)
    tmux.kills.clear()
    code, sortie, _ = lancement("fermer", str(monde), "--json")
    assert code == 0 and objet_json(sortie) == premier
    assert tmux.kills == [] and fermeture.lire_repere(monde) == avant
    assert len(evenements(monde, "ProjetFerme")) == 1


def test_fermer_deja_ferme_ne_refuse_pas_pour_un_occupe(monde, lancement):
    lancement("fermer", str(monde), "--json")
    evt(monde, "coord-hote", "UserPromptSubmit", "h-1")
    assert lancement("fermer", str(monde), "--json")[0] == 0


def test_fermer_repere_illisible_le_dit_et_n_echoue_pas(monde, lancement):
    (monde / ".orga/etat").mkdir(parents=True, exist_ok=True)
    (monde / ".orga/etat/ferme.json").write_text("{pas du json")
    code, sortie, err = lancement("fermer", str(monde), "--json")
    donnees = objet_json(sortie)
    assert code == 0 and donnees["resultat"] == "ok" and donnees["conversations"] == []
    assert "repère illisible" in donnees["message"]


def test_fermer_projet_sans_aucune_session(projet, tmux, lancement):
    code, sortie, _ = lancement("fermer", str(projet), "--json")
    assert code == 0 and objet_json(sortie)["conversations"] == []
    assert fermeture.lire_repere(projet)["a_relancer"] == ["assistant"]


def test_fermer_sans_tmux_du_tout(projet, monkeypatch, lancement):
    def absent(*a):
        raise FileNotFoundError("tmux")
    monkeypatch.setattr(fermeture, "_tmux", absent)
    code, sortie, _ = lancement("fermer", str(projet), "--json")
    assert code == 0 and fermeture.est_ferme(projet)


def test_fermer_un_kill_qui_echoue_n_arrete_pas_les_autres(monde, tmux, lancement, monkeypatch):
    reel = tmux.__call__

    def capricieux(*args):
        if args[0] == "kill-session" and args[-1] == "=essai-coord-hote":
            return _cp(1)
        return reel(*args)
    monkeypatch.setattr(fermeture, "_tmux", capricieux)
    code, sortie, _ = lancement("fermer", str(monde), "--json")
    assert code == 0 and "essai-coord-scene" in tmux.kills and "essai-worker-hote-route-x" in tmux.kills


def test_fermer_ne_lance_aucun_git_ni_ne_supprime(monde, lancement, monkeypatch):
    appels = []
    reel = subprocess.run

    def espion(cmd, *a, **k):
        appels.append(cmd)
        return reel(cmd, *a, **k)
    monkeypatch.setattr(subprocess, "run", espion)
    avant = sorted(str(p) for p in monde.rglob("*") if p.name != "registre.sqlite"
                   and "registre.sqlite" not in p.name and p.name != "etat")
    lancement("fermer", str(monde), "--json")
    assert not any(c and c[0] == "git" for c in appels)
    apres = sorted(str(p) for p in monde.rglob("*") if p.name != "registre.sqlite"
                   and "registre.sqlite" not in p.name and p.name != "etat")
    assert set(avant) <= set(apres)


# --- fermer : l'hôte ------------------------------------------------------------------

def test_fermer_arrete_l_hote_qui_ecoute_sur_le_port(monde, lancement, hote):
    (monde / ".orga/etat").mkdir(parents=True, exist_ok=True)
    (monde / ".orga/etat/hote.port").write_text("43210\n")
    hote["ecoutants"] = [777, 778]
    assert lancement("fermer", str(monde), "--json")[0] == 0
    assert hote["ports"] == [43210] and hote["tues"] == [777, 778]


@pytest.mark.parametrize("contenu", [None, "", "pas un port", "0", "-3", "99999999"])
def test_fermer_sans_port_exploitable_arret_de_l_hote_sans_effet(monde, lancement, hote, contenu):
    if contenu is not None:
        (monde / ".orga/etat").mkdir(parents=True, exist_ok=True)
        (monde / ".orga/etat/hote.port").write_text(contenu)
    hote["ecoutants"] = [777]
    code, _, _ = lancement("fermer", str(monde), "--json")
    assert code == 0 and hote["tues"] == []


def test_fermer_port_sans_processus_a_l_ecoute_sans_effet(monde, lancement, hote):
    (monde / ".orga/etat").mkdir(parents=True, exist_ok=True)
    (monde / ".orga/etat/hote.port").write_text("43210")
    assert lancement("fermer", str(monde), "--json")[0] == 0 and hote["tues"] == []


def test_fermer_ne_se_tue_jamais_soi_meme(monde, lancement, hote):
    (monde / ".orga/etat").mkdir(parents=True, exist_ok=True)
    (monde / ".orga/etat/hote.port").write_text("43210")
    hote["ecoutants"] = [os.getpid(), 4242]
    lancement("fermer", str(monde), "--json")
    assert hote["tues"] == [4242]


def test_fermer_processus_deja_disparu_ou_lsof_absent(monde, lancement, monkeypatch):
    (monde / ".orga/etat").mkdir(parents=True, exist_ok=True)
    (monde / ".orga/etat/hote.port").write_text("43210")
    monkeypatch.setattr(fermeture, "_pids_ecoutant", lambda port: [31337])

    def disparu(pid):
        raise ProcessLookupError(pid)
    monkeypatch.setattr(fermeture, "_tuer", disparu)
    assert lancement("fermer", str(monde), "--json")[0] == 0
    monkeypatch.setattr(fermeture, "_pids_ecoutant", lambda port: (_ for _ in ()).throw(
        FileNotFoundError("lsof")))
    (monde / ".orga/etat/ferme.json").unlink()
    assert lancement("fermer", str(monde), "--json")[0] == 0


# --- rouvrir ----------------------------------------------------------------------------

@pytest.fixture
def ferme(monde, lancement, lanceur):
    """Le monde, fermé ; les conversations existent sur disque ; un lanceur de faux."""
    conversation(monde, "a-vieille", 1000)
    conversation(monde, "a-recente", 2000)
    conversation(monde / ".orga/teams/hote", "h-1", 1500)
    conversation(monde / ".orga/teams/page", "p-1", 1600)
    assert lancement("fermer", str(monde), "--json")[0] == 0
    lanceur.lances.clear()
    lanceur.facteurs.clear()
    return monde


def test_rouvrir_refuse_a_tout_agent(ferme, lanceur, lancement):
    for agent, cc in (("coord-hote", False), ("assistant", False), (None, True)):
        code, sortie, _ = lancement("rouvrir", str(ferme), "--json", agent=agent, claudecode=cc)
        assert code == 1 and "réservé à l'utilisateur" in objet_json(sortie)["message"]
    assert lanceur.lances == [] and fermeture.est_ferme(ferme)
    assert evenements(ferme, "ProjetRouvert") == []


def test_rouvrir_reprend_l_assistant_puis_les_coordinateurs_a_relancer(ferme, lanceur, lancement):
    code, sortie, _ = lancement("rouvrir", str(ferme), "--json")
    assert code == 0
    assert [(l["cle"], l["session"]) for l in lanceur.lances] == [
        ("assistant", "a-recente"), ("hote", "h-1"), ("page", "p-1")]
    assert all(l["reprendre"] and l["attacher"] is False for l in lanceur.lances)
    donnees = objet_json(sortie)
    assert donnees["resultat"] == "ok" and donnees["assistant"] == "essai-assistant"
    assert donnees["coordinateurs"] == ["hote", "page"]
    assert donnees["conversation"]["session"] == "a-recente"
    assert donnees["conversation"]["date"].startswith("1970-01-01T00:33:20")
    assert donnees["echecs"] == [] and donnees["a_approuver"] is False
    assert donnees["taches_en_cours"] == ["hote/route-x", "page/vue-y"]
    assert set(donnees) == {"resultat", "assistant", "conversation", "coordinateurs", "echecs",
                            "a_approuver", "taches_en_cours"}


def test_rouvrir_ne_relance_ni_workers_ni_coordinateur_sans_travail(ferme, lanceur, lancement):
    lancement("rouvrir", str(ferme), "--json")
    assert {l["cle"] for l in lanceur.lances} == {"assistant", "hote", "page"}
    assert all(l["role"] in ("assistant", "coord") for l in lanceur.lances)


def test_rouvrir_retire_le_repere_en_dernier_et_inscrit_l_evenement(ferme, lanceur, lancement):
    lancement("rouvrir", str(ferme), "--json")
    assert all(l["repere_present"] for l in lanceur.lances)
    assert not fermeture.est_ferme(ferme)
    (ligne,) = evenements(ferme, "ProjetRouvert")
    assert ligne[0] is None and json.loads(ligne[2])["auteur"] == "utilisateur"
    conn = ouvrir(ferme)
    assert conn.execute("SELECT auteur, action, resultat FROM journal"
                        " WHERE action = 'rouvrir'").fetchall() == [("utilisateur", "rouvrir", "ok")]
    conn.close()


def test_rouvrir_demarre_le_facteur_avant_l_assistant_et_apres_le_retrait_du_repere(
        ferme, lanceur, lancement):
    lancement("rouvrir", str(ferme), "--json")
    assert lanceur.facteurs == [True, False]      # avant les lancements (repère là), puis après (retiré)


def test_rouvrir_choix_de_la_conversation_session_explicite_d_abord(ferme, lanceur, lancement):
    code, sortie, _ = lancement("rouvrir", str(ferme), "--session", "a-vieille", "--json")
    assert lanceur.lances[0]["session"] == "a-vieille"
    assert objet_json(sortie)["conversation"]["session"] == "a-vieille"


def test_rouvrir_session_explicite_absente_se_replie_sur_le_repere(ferme, lanceur, lancement):
    lancement("rouvrir", str(ferme), "--session", "inconnue", "--json")
    assert lanceur.lances[0]["session"] == "a-recente"


def test_rouvrir_sans_repere_prend_le_dernier_evenement_du_registre(projet, lanceur, lancement):
    evt(projet, "assistant", "SessionStart", "a-vieille")
    evt(projet, "assistant", "Stop", "a-vieille")
    conversation(projet, "a-vieille", 1000)
    conversation(projet, "plus-recente", 3000)
    code, sortie, _ = lancement("rouvrir", str(projet), "--json")
    assert code == 0 and lanceur.lances[0]["session"] == "a-vieille"


def test_rouvrir_sans_rien_au_registre_prend_la_plus_recente(projet, lanceur, lancement):
    conversation(projet, "ancienne", 1000)
    conversation(projet, "recente", 3000)
    code, sortie, _ = lancement("rouvrir", str(projet), "--json")
    assert code == 0 and lanceur.lances[0]["session"] == "recente"
    assert objet_json(sortie)["coordinateurs"] == []


def test_rouvrir_repere_dont_la_conversation_a_disparu_se_replie_sur_le_registre(
        ferme, lanceur, lancement):
    lancer.dossier_conversations(ferme).joinpath("a-recente.jsonl").unlink()
    evt(ferme, "assistant", "Stop", "a-vieille")
    lancement("rouvrir", str(ferme), "--json")
    assert lanceur.lances[0]["session"] == "a-vieille"


def test_rouvrir_aucune_conversation_refus_clair_rien_lance_repere_garde(
        projet, lanceur, lancement):
    fermeture.ecrire_repere(projet, {"conversations": [], "a_relancer": ["assistant"],
                                     "raisons": {}, "taches_en_cours": []})
    code, sortie, _ = lancement("rouvrir", str(projet), "--json")
    donnees = objet_json(sortie)
    assert code == 1 and donnees["resultat"] == "erreur" and "conversation" in donnees["message"]
    assert lanceur.lances == [] and fermeture.est_ferme(projet)
    assert evenements(projet, "ProjetRouvert") == []


def test_rouvrir_seulement_assistant(ferme, lanceur, lancement):
    code, sortie, _ = lancement("rouvrir", str(ferme), "--seulement-assistant", "--json")
    assert code == 0 and [l["cle"] for l in lanceur.lances] == ["assistant"]
    assert objet_json(sortie)["coordinateurs"] == [] and not fermeture.est_ferme(ferme)


def test_rouvrir_un_echec_n_arrete_pas_les_autres(ferme, lanceur, lancement):
    lanceur.erreurs["hote"] = lancer.Refus("conversation h-1 introuvable")
    code, sortie, _ = lancement("rouvrir", str(ferme), "--json")
    donnees = objet_json(sortie)
    assert code == 0 and donnees["coordinateurs"] == ["page"]
    assert [e["agent"] for e in donnees["echecs"]] == ["coord-hote"]
    assert "introuvable" in donnees["echecs"][0]["message"]
    assert [l["cle"] for l in lanceur.lances] == ["assistant", "hote", "page"]
    assert not fermeture.est_ferme(ferme)


def test_rouvrir_exception_inattendue_d_un_coordinateur_est_un_echec(ferme, lanceur, lancement):
    lanceur.erreurs["hote"] = RuntimeError("boom")
    code, sortie, _ = lancement("rouvrir", str(ferme), "--json")
    donnees = objet_json(sortie)
    assert code == 0 and donnees["coordinateurs"] == ["page"] and len(donnees["echecs"]) == 1


def test_rouvrir_coordinateur_sans_conversation_notee_est_un_echec_pas_un_arret(
        ferme, lanceur, lancement):
    lancer.dossier_conversations(ferme / ".orga/teams/hote").joinpath("h-1.jsonl").unlink()
    lanceur.erreurs["hote"] = lancer.Refus("aucune conversation trouvée")
    code, sortie, _ = lancement("rouvrir", str(ferme), "--json")
    assert code == 0 and objet_json(sortie)["coordinateurs"] == ["page"]


def test_rouvrir_ecran_de_confiance_code_3_et_a_approuver(ferme, lanceur, lancement):
    lanceur.codes["assistant"] = 3
    code, sortie, _ = lancement("rouvrir", str(ferme), "--json")
    donnees = objet_json(sortie)
    assert code == 3 and donnees["a_approuver"] is True and donnees["resultat"] == "ok"
    assert donnees["assistant"] == "essai-assistant"
    assert not fermeture.est_ferme(ferme) and len(evenements(ferme, "ProjetRouvert")) == 1


def test_rouvrir_ecran_de_confiance_d_un_coordinateur_aussi(ferme, lanceur, lancement):
    lanceur.codes["page"] = 3
    code, sortie, _ = lancement("rouvrir", str(ferme), "--json")
    assert code == 3 and objet_json(sortie)["a_approuver"] is True


def test_rouvrir_ne_touche_pas_une_session_deja_vivante(ferme, lanceur, tmux, lancement):
    tmux.sessions |= {"essai-assistant", "essai-coord-hote"}
    code, sortie, _ = lancement("rouvrir", str(ferme), "--json")
    donnees = objet_json(sortie)
    assert [l["cle"] for l in lanceur.lances] == ["page"]
    assert donnees["assistant"] == "essai-assistant" and donnees["coordinateurs"] == ["page"]
    assert [e["agent"] for e in donnees["echecs"]] == ["coord-hote"]
    assert "vivante" in donnees["echecs"][0]["message"]
    assert not fermeture.est_ferme(ferme)


def test_rouvrir_sans_fermeture_prealable_est_utilisable(projet, lanceur, lancement):
    evt(projet, "assistant", "SessionStart", "a-1")
    conversation(projet, "a-1", 1000)
    code, sortie, _ = lancement("rouvrir", str(projet), "--json")
    assert code == 0 and objet_json(sortie)["resultat"] == "ok"
    assert len(evenements(projet, "ProjetRouvert")) == 1


def test_rouvrir_taches_en_cours_lues_maintenant(ferme, lanceur, lancement):
    (ferme / ".orga/teams/hote/tasks/in-progress/route-x.md").unlink()
    (ferme / ".orga/teams/scene/tasks/in-progress/nouvelle.md").write_text("t")
    donnees = objet_json(lancement("rouvrir", str(ferme), "--json")[1])
    assert donnees["taches_en_cours"] == ["page/vue-y", "scene/nouvelle"]


def test_rouvrir_sortie_texte(ferme, lanceur, lancement):
    code, sortie, _ = lancement("rouvrir", str(ferme))
    assert code == 0 and "rouvert" in sortie and "essai-assistant" in sortie


def test_rouvrir_erreur_de_lancement_de_l_assistant_code_1_repere_garde(ferme, lanceur, lancement):
    lanceur.erreurs["assistant"] = lancer.ErreurProjet("tmux a échoué : no server")
    code, sortie, _ = lancement("rouvrir", str(ferme), "--json")
    assert code == 1 and objet_json(sortie)["resultat"] == "erreur"
    assert [l["cle"] for l in lanceur.lances] == ["assistant"] and fermeture.est_ferme(ferme)


# --- l'essai bout en bout contre les faux -----------------------------------------------

def test_bout_en_bout_fermer_rouvrir_fermer_rouvrir_session(monde, lanceur, lancement, hote, capsys):
    conversation(monde, "a-vieille", 1000)
    conversation(monde, "a-recente", 2000)
    conversation(monde / ".orga/teams/hote", "h-1", 1500)
    conversation(monde / ".orga/teams/page", "p-1", 1600)
    (monde / ".orga/etat").mkdir(parents=True, exist_ok=True)
    (monde / ".orga/etat/hote.port").write_text("43210")
    hote["ecoutants"] = [4242]
    etapes = []

    def pas(titre, *argv, **kw):
        code, sortie, _ = lancement(*argv, **kw)
        etapes.append((titre, code, sortie.strip()))
        return code, sortie

    evt(monde, "coord-hote", "UserPromptSubmit", "h-1")
    code, sortie = pas("1. fermer (coord-hote travaille)", "fermer", str(monde), "--json")
    assert code == 5 and objet_json(sortie)["occupes"] == ["coord-hote"]
    assert not fermeture.est_ferme(monde)
    code, sortie = pas("2. fermer --forcer", "fermer", str(monde), "--forcer", "--json")
    assert code == 0 and fermeture.est_ferme(monde) and hote["tues"] == [4242]
    code, sortie = pas("3. rouvrir", "rouvrir", str(monde), "--json")
    assert code == 0 and not fermeture.est_ferme(monde)
    assert objet_json(sortie)["conversation"]["session"] == "a-recente"
    evt(monde, "coord-hote", "Stop", "h-1")
    evt(monde, "assistant", "Stop", "a-recente")
    evt(monde, "coord-page", "Stop", "p-1")
    code, sortie = pas("4. fermer", "fermer", str(monde), "--json")
    assert code == 0 and objet_json(sortie)["resultat"] == "ok"
    code, sortie = pas("5. rouvrir --session a-vieille", "rouvrir", str(monde),
                       "--session", "a-vieille", "--json")
    assert code == 0 and objet_json(sortie)["conversation"]["session"] == "a-vieille"
    assert lanceur.lances[-3]["session"] == "a-vieille"
    assert [e[0] for e in evenements(monde, "ProjetFerme")] == [None, None]
    assert [e[0] for e in evenements(monde, "ProjetRouvert")] == [None, None]
    with capsys.disabled():
        for titre, code, sortie in etapes:
            print(f"\n[{titre}] code {code}\n{sortie}")


# --- le câblage de la ligne de commande -------------------------------------------------

def test_commandes_cablees_dans_cli(projet):
    parser = cli._parser()
    a = parser.parse_args(["fermer", str(projet), "--forcer", "--json"])
    assert a.commande == "fermer" and a.forcer is True
    r = parser.parse_args(["rouvrir", str(projet), "--session", "x", "--seulement-assistant"])
    assert r.commande == "rouvrir" and r.session == "x" and r.seulement_assistant is True
