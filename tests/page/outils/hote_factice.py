"""Hôte factice minimal : sert la page, l'état d'exemple de tests/page/fixtures et la scène sur l'API de l'hôte (pas le vrai hôte).

Usage : python3 tests/page/outils/hote_factice.py src/cime/page 8791   (<racine src/cime/page> <port>)
Réglages (pour le test seulement) : GET /test/regler?cle=valeur
  flux=normal|muet|coupe   actions=ok|refuse|erreur|lent|casse   etat=ok|panne   jeu=exemple|reel
  attentes=normales|vides|calme   (vides : plus aucune attente de l'utilisateur, dans /api/etat comme dans le flux — « Ce qui t'attend » est calme ;
  calme : en plus, il ne reste que les alarmes d'information)
  autonome=inactif|actif|suspendu|absent|sans_proposees   (le mode autonome, champ `fusions_auto` de l'état : l'exemple est inactif, avec la liste proposée ;
  `absent` = un vieil hôte sans le champ ; POST /api/actions/fusions-auto {valeur} le fait changer, `suspendu` + `active` = réactivation, comme l'hôte réel)
  (jeu=reel : un état réaliste pour mesurer Supervision — 8 équipes visibles, integration spéciale sans session, 1 clôturée,
   6 alarmes à voir dont des doublons de type, 8 infos ; l'exemple d'état de la page n'est pas modifié)
Sert aussi la scène (/scene/…) et GET /api/flux?depuis= en JSON.
Journal des requêtes reçues : GET /test/requetes (JSON).
"""
import email.parser
import email.policy
import json
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

RACINE = Path(sys.argv[1]).resolve()
PORT = int(sys.argv[2])
SCENE = RACINE.parent / "scene" / "static"  # la scène, servie en lecture seule sous /scene/ (comme l'hôte réel)
EXEMPLES = Path(__file__).resolve().parents[1] / "fixtures"
ETAT = json.loads((EXEMPLES / "exemple-etat.json").read_text())
ETAT_EXEMPLE = json.loads(json.dumps(ETAT))  # l'exemple tel qu'il est, pour dériver les états du mode autonome
JOURNAL = json.loads((EXEMPLES / "exemple-journal.json").read_text())["lignes"]
TERMINAUX = json.loads((EXEMPLES / "exemple-terminaux.json").read_text())
REGLAGES = {"flux": "normal", "actions": "ok", "etat": "ok", "jeu": "exemple", "autonome": "inactif", "attentes": "normales"}
REQUETES = []
VERROU = threading.Lock()
GENERE = {"t": time.time()}


def jeu_reel(e):
    """Un instantané réaliste : 8 équipes visibles, 6 alarmes à voir (doublons de type), 8 infos."""
    modele_equipe = e["equipes"][0]
    modele_agent = next(a for a in e["agents"] if a["id"] == "coord-page")
    visibles = ["fondation", "observation", "hote", "page", "scene", "ergonomie", "verification", "livraison"]
    equipes = []
    for nom in visibles + ["integration", "signaux"]:
        q = json.loads(json.dumps(modele_equipe))
        q.update(nom=nom, mission=f"Mission de l’équipe {nom}, écrite sur une ou deux lignes.", speciale=nom in ("verification", "integration"),
                 statut="terminee" if nom == "signaux" else "au_repos", depend_de=[], retard_sur_base=2)
        equipes.append(q)
    agents = [a for a in e["agents"] if a["role"] in ("utilisateur", "assistant")]
    for nom in visibles:
        a = json.loads(json.dumps(modele_agent))
        a.update(id=f"coord-{nom}", equipe=nom, tache="Travaille sur sa tâche en cours")
        agents.append(a)
    depuis = lambda m: (datetime.now(timezone.utc) - timedelta(minutes=m)).isoformat().replace("+00:00", "Z")
    alarme = lambda n, type_, gravite, ags, eqs, m: {"id": f"{type_}:{n}", "type": type_, "gravite": gravite, "agents": ags, "equipes": eqs, "depuis": depuis(m),
                                                      "mesure": f"mesure {type_} {n}", "quoi_faire": f"Quoi faire pour {type_}.", "destinataire": "utilisateur"}
    alarmes = [
        alarme(1, "contexte_au_repos", "a_voir", ["coord-livraison"], ["livraison"], 70), alarme(2, "contexte_au_repos", "a_voir", ["coord-scene"], ["scene"], 40),
        alarme(3, "contexte_au_repos", "a_voir", ["assistant"], [], 20), alarme(4, "action_refusee", "a_voir", ["assistant"], [], 9),
        alarme(5, "action_refusee", "a_voir", ["assistant"], [], 5), alarme(6, "gros_poste", "a_voir", ["assistant"], [], 1),
    ] + [alarme(10 + i, "retard_sur_base", "info", [], [n], 120 + i) for i, n in enumerate(["signaux", "observation", "fondation", "livraison", "hote", "ergonomie", "page", "scene"])]
    e.update(equipes=equipes, agents=agents, alarmes=alarmes, attentes_utilisateur=[])
    return e


def mode_autonome(nom):
    """Le champ `fusions_auto` dans l'un de ses états ; None = champ absent (vieil hôte). Dérivé de l'exemple : pas de second état à entretenir."""
    base = json.loads(json.dumps(ETAT_EXEMPLE["fusions_auto"]))
    proposees = base["reserves_proposees"]
    depuis = (datetime.now(timezone.utc) - timedelta(hours=14)).isoformat().replace("+00:00", "Z")
    if nom == "absent":
        return None
    if nom == "sans_proposees":
        del base["reserves_proposees"]
        return base
    if nom in ("suspendu", "actif"):
        # ce que l'Assistant a décidé : 3 fusions, 1 chantier, 2 autorisations, toutes après la « dernière visite » par défaut (3 h), la plus récente d'abord
        il_y_a = lambda minutes: (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")
        decisions = [{"genre": g, "cle": c, "horodatage": il_y_a(m), "message": 1412 - 3 * i}
                     for i, (g, c, m) in enumerate([("fusion", "f223c94", 12), ("autorisation", "integration:lecture-journal", 35), ("fusion", "6eb0bf1", 62),
                                                    ("chantier", "page:lot-6-recap", 95), ("autorisation", "hote:ecriture-etat", 128), ("fusion", "9436197", 160)])]
        plus = {"portee": 2, "chantiers_24h": 1, "chantiers_max": 5, "decisions": decisions}
        if nom == "suspendu":
            return {**base, **plus, "active": True, "suspendue": True, "depuis": depuis, "reserves": proposees[:-1]}
        return {**base, **plus, "active": True, "depuis": depuis, "reserves": proposees, "derniere_fusion": {"equipe": "page", "sha": "f223c94", "horodatage": il_y_a(12)}}
    return base


def regler_autonome(nom):
    with VERROU:
        champ = mode_autonome(nom)
        if champ is None:
            ETAT.pop("fusions_auto", None)
        else:
            ETAT["fusions_auto"] = champ


def basculer_autonome(corps):
    """POST /api/actions/fusions-auto : comme l'hôte. Renvoie la réponse { resultat, message }."""
    valeur = corps.get("valeur")
    with VERROU:
        courant = ETAT.get("fusions_auto") or mode_autonome("inactif")
        if valeur not in ("active", "inactive"):
            return {"resultat": "refuse", "message": "valeur inconnue (active ou inactive)"}
        actif = bool(courant["active"])
        if valeur == "active" and actif and not courant.get("suspendue"):
            return {"resultat": "refuse", "message": "déjà actif"}
        if valeur == "inactive" and not actif:
            return {"resultat": "refuse", "message": "déjà inactif"}
        avant = "suspendu" if courant.get("suspendue") else ("actif" if actif else "inactif")
        ETAT["fusions_auto"] = mode_autonome("actif" if valeur == "active" else "inactif")
        JOURNAL.append({"id": len(JOURNAL) + 100, "horodatage": maintenant_iso(), "auteur": "utilisateur", "action": "fusions_auto", "cible": "projet",
                        "details": {"valeur": valeur, "avant": avant, "reglage_id": len(JOURNAL) + 1}, "resultat": "ok"})
    return {"resultat": "ok", "message": "fait"}


def instantane():
    with VERROU:
        e = json.loads(json.dumps(ETAT))
    if REGLAGES["jeu"] == "reel":
        e = jeu_reel(e)
    if REGLAGES["attentes"] in ("vides", "calme"):
        e["attentes_utilisateur"] = []
    if REGLAGES["attentes"] == "calme":
        e["alarmes"] = [a for a in e["alarmes"] if a["gravite"] == "info"]
    e["age_ms"] = int((time.time() - GENERE["t"]) * 1000) + 400
    return e


def maintenant_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class Gestion(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def garde(self, post):
        hotes = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
        if self.headers.get("Host") not in hotes:
            return False
        if post:
            origine = self.headers.get("Origin")
            if origine is not None and origine not in {f"http://{h}" for h in hotes}:
                return False
        return True

    def repondre(self, code, corps, type_="application/json; charset=utf-8"):
        if isinstance(corps, (dict, list)):
            corps = json.dumps(corps, ensure_ascii=False)
        if isinstance(corps, str):
            corps = corps.encode()
        self.send_response(code)
        self.send_header("Content-Type", type_)
        self.send_header("Content-Length", str(len(corps)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corps)

    def do_GET(self):
        u = urlparse(self.path)
        REQUETES.append({"m": "GET", "chemin": u.path, "requete": u.query})
        if u.path.startswith("/test/"):
            return self.test(u)
        if not self.garde(False):
            return self.repondre(403, {"erreur": "hôte refusé"})
        if u.path == "/":
            return self.repondre(200, (RACINE / "index.html").read_bytes(), "text/html; charset=utf-8")
        if u.path.startswith("/static/"):
            f = (RACINE / "static" / u.path[len("/static/"):]).resolve()
            if not str(f).startswith(str(RACINE / "static")) or not f.is_file():
                return self.repondre(404, "absent", "text/plain")
            types = {".js": "text/javascript", ".css": "text/css", ".json": "application/json"}
            return self.repondre(200, f.read_bytes(), types.get(f.suffix, "application/octet-stream") + "; charset=utf-8")
        if u.path.startswith("/scene/"):
            f = (SCENE / (u.path[len("/scene/"):] or "index.html")).resolve()
            if not str(f).startswith(str(SCENE)) or not f.is_file():
                return self.repondre(404, "absent", "text/plain")
            types = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".html": "text/html", ".json": "application/json"}
            return self.repondre(200, f.read_bytes(), types.get(f.suffix, "application/octet-stream") + "; charset=utf-8")
        if u.path == "/api/etat":
            if REGLAGES["etat"] == "panne":
                return self.repondre(503, {"erreur": "panne"})
            return self.repondre(200, instantane())
        if u.path == "/api/journal":
            limite = int(parse_qs(u.query).get("limite", ["100"])[0])
            with VERROU:
                lignes = sorted(JOURNAL, key=lambda l: l["horodatage"], reverse=True)[:limite]
            return self.repondre(200, {"lignes": lignes})
        if u.path.startswith("/api/agents/") and u.path.endswith("/terminal"):
            agent = u.path[len("/api/agents/"):-len("/terminal")]
            if agent not in TERMINAUX:
                return self.repondre(404, {"erreur": "aucune session"})
            return self.repondre(200, {"texte": TERMINAUX[agent]["texte"] + f"\n[{maintenant_iso()}]", "capture_a": maintenant_iso()})
        if u.path == "/api/fichier":
            chemin = parse_qs(u.query).get("chemin", [""])[0]
            if not chemin.startswith(".orga/") or ".." in chemin:
                return self.repondre(403, {"erreur": "hors de .orga"})
            if "cadrage" in chemin:
                return self.repondre(404, {"erreur": "absent"})
            return self.repondre(200, f"# {chemin}\n\nContenu de test du fichier.\nDeuxième ligne.\n", "text/plain; charset=utf-8")
        if u.path == "/api/flux" and "depuis" in parse_qs(u.query, keep_blank_values=True):
            # lecture JSON des transitions (la source alimentée de la scène) : aucune transition dans le faux hôte
            return self.repondre(200, {"transitions": [], "dernier_id": 0})
        if u.path == "/api/flux":
            return self.flux()
        return self.repondre(404, "absent", "text/plain")

    def flux(self):
        if REGLAGES["flux"] == "coupe":
            self.close_connection = True
            return self.repondre(503, "coupé", "text/plain")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        dernier_vivant = 0
        dernier_etat = 0
        try:
            while True:
                if REGLAGES["flux"] == "coupe":
                    self.close_connection = True
                    return
                t = time.time()
                if REGLAGES["flux"] == "normal":
                    if t - dernier_etat >= 3:
                        GENERE["t"] = t
                        self.wfile.write(f"event: etat\ndata: {json.dumps(instantane(), ensure_ascii=False)}\n\n".encode())
                        dernier_etat = t
                    if t - dernier_vivant >= 10:
                        self.wfile.write(b"event: vivant\ndata: {}\n\n")
                        dernier_vivant = t
                    self.wfile.flush()
                time.sleep(0.5)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
            return

    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        brut = self.rfile.read(n)
        entree = {"m": "POST", "chemin": u.path, "type": self.headers.get("Content-Type", ""), "origin": self.headers.get("Origin")}
        if not self.garde(True):
            REQUETES.append(entree)
            return self.repondre(403, {"resultat": "refuse", "message": "origine refusée"})
        if entree["type"].startswith("application/json"):
            entree["corps"] = json.loads(brut or b"{}")
        elif entree["type"].startswith("multipart/form-data"):
            msg = email.parser.BytesParser(policy=email.policy.default).parsebytes(
                b"Content-Type: " + entree["type"].encode() + b"\r\n\r\n" + brut)
            champs = {}
            for partie in msg.iter_parts():
                nom = partie.get_param("name", header="content-disposition")
                fichier = partie.get_filename()
                valeur = {"fichier": fichier, "taille": len(partie.get_payload(decode=True))} if fichier else partie.get_content()
                champs.setdefault(nom, []).append(valeur)
            entree["corps"] = champs
        REQUETES.append(entree)
        action = u.path.rsplit("/", 1)[-1]
        mode = REGLAGES["actions"]
        if mode == "lent":
            time.sleep(2)
        if mode == "refuse":
            return self.repondre(200, {"resultat": "refuse", "message": "attente déjà traitée"})
        if mode == "erreur":
            return self.repondre(200, {"resultat": "erreur", "message": "tmux n’a pas répondu"})
        if mode == "casse":
            return self.repondre(500, "boum", "text/plain")
        corps = entree.get("corps", {})
        if action == "fusions-auto":
            return self.repondre(200, basculer_autonome(corps))
        attente = corps.get("attente_id")
        if isinstance(attente, list):
            attente = attente[0]
        with VERROU:
            if action == "cloturer":
                ETAT["attentes_utilisateur"] = [a for a in ETAT["attentes_utilisateur"] if a["nature"] != "cloture"]
                cible = f"equipe:{corps.get('equipe')}"
            else:
                ETAT["attentes_utilisateur"] = [a for a in ETAT["attentes_utilisateur"] if a["id"] != attente]
                cible = attente
            JOURNAL.append({"id": len(JOURNAL) + 100, "horodatage": maintenant_iso(), "auteur": "utilisateur",
                            "action": action, "cible": cible, "details": {"attente": attente}, "resultat": "ok"})
        return self.repondre(200, {"resultat": "ok", "message": "fait"})

    def test(self, u):
        if u.path == "/test/regler":
            for cle, valeurs in parse_qs(u.query).items():
                REGLAGES[cle] = valeurs[0]
                if cle == "autonome":
                    regler_autonome(valeurs[0])
            return self.repondre(200, REGLAGES)
        if u.path == "/test/requetes":
            return self.repondre(200, REQUETES)
        return self.repondre(404, "absent", "text/plain")


ThreadingHTTPServer(("127.0.0.1", PORT), Gestion).serve_forever()
