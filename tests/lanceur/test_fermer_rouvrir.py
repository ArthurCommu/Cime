"""Fermer et rouvrir un projet, état ouvert/fermé du lanceur."""
import http.server
import json
import threading
from pathlib import Path

import httpx
import pytest

from cime.lanceur import serveur as mod

AGENTS_ACTIFS_REELS = mod._agents_actifs   # capturée avant que les tests ne la remplacent


def projet(tmp_path, nom="alpha", prefixe="al"):
    d = tmp_path / nom
    (d / ".orga").mkdir(parents=True)
    (d / ".orga" / "projet.toml").write_text(f'nom = "{nom}"\nprefixe = "{prefixe}"\n')
    return d


def ferme_json(p, n=2):
    (p / ".orga" / "etat").mkdir(parents=True, exist_ok=True)
    conv = [{"agent": f"a{i}", "session": f"s{i}", "tmux": f"t{i}"} for i in range(n)]
    (p / ".orga" / "etat" / "ferme.json").write_text(json.dumps({"conversations": conv}))


@pytest.fixture(autouse=True)
def agents_inactifs(monkeypatch):
    """Aucun test ne doit interroger tmux : par défaut, aucun agent n'est actif."""
    monkeypatch.setattr(mod, "_agents_actifs", lambda chemin: False)


class Ouvreur:
    """Faux `ouvrir_fenetre` : enregistre les sessions demandées, répond `reponse`."""

    def __init__(self):
        self.appels, self.reponse = [], True

    def __call__(self, dossier, session, terminal=None, lancer=None):
        self.appels.append(session)
        return self.reponse


@pytest.fixture(autouse=True)
def ouvreur(monkeypatch):
    o = Ouvreur()
    monkeypatch.setattr(mod, "ouvrir_fenetre", o)
    return o


@pytest.fixture
def hote_factice():
    """Un serveur HTTP qui répond 503 : un hôte « vivant » pour la sonde."""
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(503)
            self.end_headers()

        log_message = lambda *a: None
    s = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield s
    s.shutdown()


# ── GET /api/projets : état ouvert/fermé ────────────────────────────────────────────────

def test_hote_vivant_ouvert_sans_conversations(lanceur, tmp_path, hote_factice):
    p = projet(tmp_path)
    (p / ".orga" / "etat").mkdir(parents=True)
    (p / ".orga" / "etat" / "hote.port").write_text(str(hote_factice.server_port))
    lanceur.post("/api/projets/ajouter", json={"chemin": str(p)})
    (projet_lu,) = lanceur.get("/api/projets").json()["projets"]
    assert projet_lu["etat"] == "ouvert" and projet_lu["conversations"] is None


def test_sans_hote_ni_agent_ferme_avec_ferme_json(lanceur, tmp_path):
    p = projet(tmp_path)
    ferme_json(p, 2)
    lanceur.post("/api/projets/ajouter", json={"chemin": str(p)})
    (projet_lu,) = lanceur.get("/api/projets").json()["projets"]
    assert projet_lu["etat"] == "ferme" and projet_lu["conversations"] == 2


def test_sans_ferme_json_conversations_null(lanceur, tmp_path):
    p = projet(tmp_path)
    lanceur.post("/api/projets/ajouter", json={"chemin": str(p)})
    (projet_lu,) = lanceur.get("/api/projets").json()["projets"]
    assert projet_lu["etat"] == "ferme" and projet_lu["conversations"] is None


def test_ferme_json_illisible_conversations_null(lanceur, tmp_path):
    p = projet(tmp_path)
    (p / ".orga" / "etat").mkdir(parents=True)
    (p / ".orga" / "etat" / "ferme.json").write_text("{pas du json")
    lanceur.post("/api/projets/ajouter", json={"chemin": str(p)})
    (projet_lu,) = lanceur.get("/api/projets").json()["projets"]
    assert projet_lu["conversations"] is None


def test_agents_actifs_donnent_ouvert(lanceur, tmp_path, monkeypatch):
    p = projet(tmp_path)
    ferme_json(p, 2)
    monkeypatch.setattr(mod, "_agents_actifs", lambda chemin: True)
    lanceur.post("/api/projets/ajouter", json={"chemin": str(p)})
    (projet_lu,) = lanceur.get("/api/projets").json()["projets"]
    assert projet_lu["etat"] == "ouvert"


def test_agents_actifs_exception_vaut_pas_actifs(lanceur, tmp_path, monkeypatch):
    import cime.signaux.facteur as facteur

    def casse(chemin):
        raise RuntimeError("tmux absent")
    monkeypatch.setattr(mod, "_agents_actifs", AGENTS_ACTIFS_REELS)   # l'enveloppe réelle
    monkeypatch.setattr(facteur, "agents_actifs", casse)
    p = projet(tmp_path)
    lanceur.post("/api/projets/ajouter", json={"chemin": str(p)})
    (projet_lu,) = lanceur.get("/api/projets").json()["projets"]
    assert projet_lu["etat"] == "ferme"


# ── fermer ──────────────────────────────────────────────────────────────────────────────

def test_fermer_ok_ecrit_ferme_json_et_argv(lanceur, tmp_path, trace):
    p = projet(tmp_path)
    r = lanceur.post("/api/projets/fermer", json={"chemin": str(p)})
    corps = r.json()
    assert r.status_code == 200 and corps["resultat"] == "ok"
    assert [c["agent"] for c in corps["conversations"]] == ["assistant", "coord-hote"]
    assert corps["taches_en_cours"] == []
    assert (p / ".orga" / "etat" / "ferme.json").is_file()
    (appel,) = trace()
    assert appel["argv"] == ["fermer", str(p.resolve()), "--json"]


def test_fermer_recopie_echecs_tel_quel(lanceur, tmp_path, monkeypatch):
    monkeypatch.setenv("FAUX_CIME_ECHECS", "1")
    p = projet(tmp_path)
    corps = lanceur.post("/api/projets/fermer", json={"chemin": str(p)}).json()
    assert corps["echecs"] == ["équipe lente"]


def test_fermer_sans_cime_cible_en_env(lanceur, tmp_path, trace):
    p = projet(tmp_path)
    lanceur.post("/api/projets/fermer", json={"chemin": str(p)})
    (appel,) = trace()
    assert appel["CIME_PROJET"] is None and appel["CIME_AGENT"] is None


def test_fermer_occupes_409_sans_ferme_json(lanceur, tmp_path, monkeypatch):
    monkeypatch.setenv("FAUX_CIME_OCCUPES", "assistant,coord-hote")
    p = projet(tmp_path)
    r = lanceur.post("/api/projets/fermer", json={"chemin": str(p)})
    corps = r.json()
    assert r.status_code == 409 and corps["resultat"] == "refuse"
    assert corps["occupes"] == ["assistant", "coord-hote"] and corps["message"] == "agents occupés"
    assert not (p / ".orga" / "etat" / "ferme.json").exists()


def test_fermer_forcer_passe_l_option(lanceur, tmp_path, monkeypatch, trace):
    monkeypatch.setenv("FAUX_CIME_OCCUPES", "assistant")
    p = projet(tmp_path)
    r = lanceur.post("/api/projets/fermer", json={"chemin": str(p), "forcer": True})
    assert r.status_code == 200 and r.json()["resultat"] == "ok"
    (appel,) = trace()
    assert appel["argv"] == ["fermer", str(p.resolve()), "--json", "--forcer"]


@pytest.mark.parametrize("forcer", ["oui", 1, []])
def test_fermer_forcer_non_booleen_400(lanceur, tmp_path, trace, forcer):
    p = projet(tmp_path)
    r = lanceur.post("/api/projets/fermer", json={"chemin": str(p), "forcer": forcer})
    assert r.status_code == 400 and r.json()["resultat"] == "refuse"
    assert trace() == []


def test_fermer_sans_manifeste_400(lanceur, tmp_path, trace):
    (tmp_path / "vide").mkdir()
    assert lanceur.post("/api/projets/fermer", json={"chemin": str(tmp_path / "vide")}).status_code == 400
    assert trace() == []


def test_fermer_sortie_sans_json_erreur(lanceur, tmp_path, monkeypatch):
    monkeypatch.setenv("FAUX_CIME_TEXTE", "1")
    p = projet(tmp_path)
    r = lanceur.post("/api/projets/fermer", json={"chemin": str(p)})
    corps = r.json()
    assert r.status_code == 200 and corps["resultat"] == "erreur" and corps["code"] == 0
    assert corps["message"] == "La fermeture a échoué."
    assert "ceci n'est pas du JSON" in corps["sortie"]


# ── erreurs en phrase : jamais le JSON brut (fermer, rouvrir) ───────────────────────────

def dernier_journal(c, action):
    lignes = [json.loads(l) for l in (c.dossier / "journal.jsonl").read_text().splitlines()]
    return [l for l in lignes if l["action"] == action][-1]


def test_fermer_erreur_json_donne_son_message_seul(lanceur, tmp_path, monkeypatch):
    monkeypatch.setenv("FAUX_CIME_ERREUR", "cime fermer : le registre est verrouillé")
    p = projet(tmp_path)
    r = lanceur.post("/api/projets/fermer", json={"chemin": str(p)})
    corps = r.json()
    assert r.status_code == 200 and corps["resultat"] == "erreur" and corps["code"] == 1
    assert corps["message"] == "cime fermer : le registre est verrouillé"
    assert "{" not in corps["message"] and "resultat" not in corps["message"]
    assert "resultat" in corps["sortie"]     # la sortie brute est gardée, à part


def test_fermer_erreur_journal_message_puis_sortie(lanceur, tmp_path, monkeypatch):
    monkeypatch.setenv("FAUX_CIME_ERREUR", "le registre est verrouillé")
    p = projet(tmp_path)
    corps = lanceur.post("/api/projets/fermer", json={"chemin": str(p)}).json()
    assert dernier_journal(lanceur, "fermer")["message"] == (
        "le registre est verrouillé | sortie : " + " ".join(corps["sortie"].split()))
    assert dernier_journal(lanceur, "fermer")["resultat"] == "erreur"


def test_fermer_sortie_texte_donne_phrase_generique(lanceur, tmp_path, monkeypatch):
    monkeypatch.setenv("FAUX_CIME_TEXTE", "1")          # code 0, pas de JSON
    p = projet(tmp_path)
    corps = lanceur.post("/api/projets/fermer", json={"chemin": str(p)}).json()
    assert corps["message"] == "La fermeture a échoué." and corps["code"] == 0
    assert dernier_journal(lanceur, "fermer")["message"].startswith("La fermeture a échoué. | sortie : ")


def test_rouvrir_erreur_json_donne_son_message_seul(lanceur, tmp_path, monkeypatch, ouvreur):
    monkeypatch.setenv("FAUX_CIME_ERREUR", "cime rouvrir : le registre est verrouillé")
    p = projet(tmp_path)
    corps = lanceur.post("/api/projets/rouvrir", json={"chemin": str(p)}).json()
    assert corps["resultat"] == "erreur" and corps["code"] == 1
    assert corps["message"] == "cime rouvrir : le registre est verrouillé"
    assert "{" not in corps["message"] and "resultat" not in corps["message"]
    assert ouvreur.appels == []


def test_rouvrir_erreur_journal_message_puis_sortie(lanceur, tmp_path, monkeypatch):
    monkeypatch.setenv("FAUX_CIME_ERREUR", "registre cassé")
    p = projet(tmp_path)
    corps = lanceur.post("/api/projets/rouvrir", json={"chemin": str(p)}).json()
    assert dernier_journal(lanceur, "rouvrir")["message"] == "registre cassé | sortie : " + " ".join(corps["sortie"].split())


def test_rouvrir_sortie_texte_donne_phrase_generique(lanceur, tmp_path, monkeypatch, ouvreur):
    monkeypatch.setenv("FAUX_CIME_TEXTE", "1")          # code 0, pas de JSON
    p = projet(tmp_path)
    corps = lanceur.post("/api/projets/rouvrir", json={"chemin": str(p)}).json()
    assert corps["message"] == "La réouverture a échoué." and corps["code"] == 0
    assert "ceci n'est pas du JSON" in corps["sortie"] and ouvreur.appels == []




def test_fermer_delai_depasse_erreur(lanceur, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "DELAI_FERMER_S", 0.5)
    monkeypatch.setenv("FAUX_CIME_LENT", "1")
    p = projet(tmp_path)
    corps = lanceur.post("/api/projets/fermer", json={"chemin": str(p)}).json()
    assert corps["resultat"] == "erreur" and corps["code"] is None
    assert corps["message"] == "La commande a pris plus de 0.5 s (elle est peut-être encore en cours)."


# ── rouvrir ─────────────────────────────────────────────────────────────────────────────

def test_rouvrir_ok_retire_ferme_json_ouvre_hote_et_fenetre(lanceur, tmp_path, trace, ouvreur, nettoyage_hotes):
    p = projet(tmp_path)
    ferme_json(p, 2)
    r = lanceur.post("/api/projets/rouvrir", json={"chemin": str(p)})
    corps = r.json()
    assert r.status_code == 200 and corps["resultat"] == "ok"
    assert not (p / ".orga" / "etat" / "ferme.json").exists()
    assert corps["url"].startswith("http://127.0.0.1:") and httpx.get(corps["url"] + "api/etat").status_code in (200, 503)
    assert corps["assistant"] == "p-alpha-assistant" and corps["coordinateurs"] == ["p-alpha-coord-hote"]
    assert corps["a_approuver"] is False and corps["fenetre"] is True
    assert corps["commandes"] == ["tmux attach -t p-alpha-assistant"]
    assert "avertissement" not in corps
    assert ouvreur.appels == ["p-alpha-assistant"]
    (appel,) = [a for a in trace() if a["argv"][0] == "rouvrir"]
    assert appel["argv"] == ["rouvrir", str(p.resolve()), "--json"]
    assert appel["CIME_PROJET"] is None and appel["CIME_AGENT"] is None
    assert len(nettoyage_hotes) == 1


def test_rouvrir_transmet_conversation(lanceur, tmp_path):
    p = projet(tmp_path)
    corps = lanceur.post("/api/projets/rouvrir", json={"chemin": str(p)}).json()
    assert corps["conversation"] == {"session": "s-1", "date": "2026-10-11T18:00:00Z"}
    assert corps["equipes"] == ["hote"]   # les noms lisibles, pour la page


def test_rouvrir_session_transmise(lanceur, tmp_path, trace):
    p = projet(tmp_path)
    r = lanceur.post("/api/projets/rouvrir", json={"chemin": str(p), "session": "abc-123_X"})
    assert r.json()["resultat"] == "ok"
    (appel,) = [a for a in trace() if a["argv"][0] == "rouvrir"]
    assert appel["argv"] == ["rouvrir", str(p.resolve()), "--json", "--session", "abc-123_X"]


@pytest.mark.parametrize("session", ["", "a b", "x" * 81, "a/b", 3, "é"])
def test_rouvrir_session_hors_motif_400(lanceur, tmp_path, trace, session):
    p = projet(tmp_path)
    r = lanceur.post("/api/projets/rouvrir", json={"chemin": str(p), "session": session})
    assert r.status_code == 400 and r.json()["resultat"] == "refuse"
    assert trace() == []


def test_rouvrir_code_3_a_approuver(lanceur, tmp_path, monkeypatch):
    monkeypatch.setenv("FAUX_CIME_CODE", "3")
    p = projet(tmp_path)
    corps = lanceur.post("/api/projets/rouvrir", json={"chemin": str(p)}).json()
    assert corps["resultat"] == "ok" and corps["a_approuver"] is True


def test_rouvrir_fenetre_faux_donne_la_commande(lanceur, tmp_path, ouvreur):
    ouvreur.reponse = False
    p = projet(tmp_path)
    corps = lanceur.post("/api/projets/rouvrir", json={"chemin": str(p)}).json()
    assert corps["resultat"] == "ok" and corps["fenetre"] is False
    assert corps["commandes"] == ["tmux attach -t p-alpha-assistant"]
    assert "message" in corps and "tmux attach" in corps["message"]


def test_rouvrir_hote_qui_ne_demarre_pas_reste_ok(lanceur, tmp_path, monkeypatch, nettoyage_hotes, ouvreur):
    monkeypatch.setenv("FAUX_CIME_JAMAIS", "1")
    monkeypatch.setattr(mod, "ATTENTE_HOTE_S", 0.5)
    p = projet(tmp_path)
    corps = lanceur.post("/api/projets/rouvrir", json={"chemin": str(p)}).json()
    assert corps["resultat"] == "ok" and corps["url"] is None
    assert "non démarré" in corps["avertissement"]
    assert corps["fenetre"] is True and ouvreur.appels == ["p-alpha-assistant"]


def test_rouvrir_erreur_de_cime(lanceur, tmp_path, monkeypatch, ouvreur):
    monkeypatch.setenv("FAUX_CIME_ERREUR", "registre cassé")
    p = projet(tmp_path)
    corps = lanceur.post("/api/projets/rouvrir", json={"chemin": str(p)}).json()
    assert corps["resultat"] == "erreur" and corps["code"] == 1 and "registre cass" in corps["message"]
    assert ouvreur.appels == []


def test_rouvrir_delai_depasse_erreur(lanceur, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "DELAI_ROUVRIR_S", 0.5)
    monkeypatch.setenv("FAUX_CIME_LENT", "1")
    p = projet(tmp_path)
    corps = lanceur.post("/api/projets/rouvrir", json={"chemin": str(p)}).json()
    assert corps["resultat"] == "erreur" and corps["code"] is None
    assert corps["message"] == "La commande a pris plus de 0.5 s (elle est peut-être encore en cours)."


def test_rouvrir_sans_manifeste_400(lanceur, tmp_path):
    (tmp_path / "vide").mkdir()
    assert lanceur.post("/api/projets/rouvrir", json={"chemin": str(tmp_path / "vide")}).status_code == 400


# ── journal ─────────────────────────────────────────────────────────────────────────────

def test_journal_fermer_rouvrir_une_ligne_par_appel(lanceur, tmp_path, monkeypatch):
    p = projet(tmp_path)
    lanceur.post("/api/projets/fermer", json={"chemin": str(p)})                 # ok
    monkeypatch.setenv("FAUX_CIME_OCCUPES", "assistant")
    lanceur.post("/api/projets/fermer", json={"chemin": str(p)})                 # refuse
    monkeypatch.delenv("FAUX_CIME_OCCUPES")
    monkeypatch.setenv("FAUX_CIME_ERREUR", "boum")
    lanceur.post("/api/projets/rouvrir", json={"chemin": str(p)})                # erreur
    lignes = [json.loads(l) for l in (lanceur.dossier / "journal.jsonl").read_text().splitlines()]
    assert [(l["action"], l["resultat"]) for l in lignes] == [
        ("fermer", "ok"), ("fermer", "refuse"), ("rouvrir", "erreur")]
    assert all(l["auteur"] == "utilisateur" and l["cible"] == str(p.resolve()) for l in lignes)
