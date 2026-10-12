"""Faux `cime` pour les tests du lanceur.
init  : écrit ses argv dans $FAUX_CIME_TRACE (JSON, une ligne par appel, avec les variables
        CIME_PROJET/CIME_AGENT vues), crée <cible>/.orga/projet.toml, sort avec $FAUX_CIME_CODE.
init --apercu : répond l'aperçu convenu, ne crée rien ; $FAUX_CIME_APERCU_ECHEC → code 1 (texte) ;
        $FAUX_CIME_APERCU_JSON → code 1 avec une erreur en JSON.
conversations : répond la liste convenue ; $FAUX_CIME_BEAUCOUP → 31 entrées ; $FAUX_CIME_TEXTE →
        pas de JSON ; $FAUX_CIME_ERREUR → code 1 avec une erreur en JSON.
fermer / rouvrir : $FAUX_CIME_TEXTE → pas de JSON (code 0) ; $FAUX_CIME_ERREUR → code 1 avec une
        erreur en JSON (pour fermer comme pour rouvrir).
servir: écrit une trace, puis démarre un vrai petit hôte (cime.hote.servir) ; avec
        $FAUX_CIME_JAMAIS=1 il dort sans rien démarrer."""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

args = sys.argv[1:]
trace = os.environ.get("FAUX_CIME_TRACE")
if trace:
    with open(trace, "a") as f:
        f.write(json.dumps({"argv": args, "cwd": os.getcwd(),
                            "CIME_PROJET": os.environ.get("CIME_PROJET"),
                            "CIME_AGENT": os.environ.get("CIME_AGENT")}) + "\n")


def _attendre_si_lent():
    if os.environ.get("FAUX_CIME_LENT"):
        time.sleep(60)


if args[0] == "init" and "--apercu" in args:
    # une ligne de progression JSON avant le résultat : le lecteur doit prendre la DERNIÈRE ligne
    print(json.dumps({"etape": "apercu"}), flush=True)
    _attendre_si_lent()
    if os.environ.get("FAUX_CIME_APERCU_JSON"):
        print(json.dumps({"resultat": "erreur", "message": "cime init : ce dossier n'est pas lisible"}))
        sys.exit(1)
    if os.environ.get("FAUX_CIME_APERCU_ECHEC"):
        print("aperçu impossible")
        sys.exit(1)
    cible = Path(args[args.index("--apercu") + 1])
    print(json.dumps({"nom": cible.name, "commit": False, "cree": [".orga/projet.toml", ".orga/etat/"],
                      "complete": [], "garde": []}))
    sys.exit(0)

if args[0] == "init":
    cible = Path(args[1])
    # sans --nom-projet, le nom est celui du dossier
    nom = args[args.index("--nom-projet") + 1] if "--nom-projet" in args else cible.name
    prefixe = args[args.index("--prefixe") + 1] if "--prefixe" in args else "p-" + nom
    (cible / ".orga").mkdir(parents=True, exist_ok=True)
    (cible / ".orga" / "projet.toml").write_text(f'nom = "{nom}"\nprefixe = "{prefixe}"\n')
    print("init fait")
    print("sur stderr", file=sys.stderr)
    sys.exit(int(os.environ.get("FAUX_CIME_CODE", "0")))


if args[0] == "conversations":
    if os.environ.get("FAUX_CIME_TEXTE"):
        print("ceci n'est pas du JSON")
        sys.exit(0)
    print(json.dumps({"etape": "conversations"}), flush=True)
    _attendre_si_lent()
    if os.environ.get("FAUX_CIME_ERREUR"):
        print(json.dumps({"resultat": "erreur", "message": os.environ["FAUX_CIME_ERREUR"]}))
        print("sur stderr", file=sys.stderr)
        sys.exit(1)
    if os.environ.get("FAUX_CIME_BEAUCOUP"):
        conversations = [{"session": f"c-{i}", "date": "2026-10-01T00:00:00Z", "taille": i,
                          "debut": f"message {i}"} for i in range(31)]
    else:
        conversations = [{"session": "c-1", "date": "2026-10-12T09:00:00Z", "taille": 1234, "debut": "Bonjour"},
                         {"session": "c-2", "date": "2026-10-11T18:00:00Z", "taille": 88, "debut": None},
                         {"session": "c-3", "date": "2026-10-10T08:00:00Z", "taille": 4096,
                          "debut": "Où en est la liste ?"}]
    print(json.dumps({"conversations": conversations}))
    sys.exit(0)


if args[0] in ("fermer", "rouvrir"):
    chemin = Path(args[1])
    etat = chemin / ".orga" / "etat"
    # une ligne de progression JSON avant le résultat : le lecteur doit prendre la DERNIÈRE ligne
    print(json.dumps({"etape": args[0]}), flush=True)
    _attendre_si_lent()
    if args[0] == "fermer":
        if os.environ.get("FAUX_CIME_TEXTE"):
            print("ceci n'est pas du JSON")
            sys.exit(0)
        if os.environ.get("FAUX_CIME_ERREUR"):
            print(json.dumps({"resultat": "erreur", "message": os.environ["FAUX_CIME_ERREUR"]}))
            print("sur stderr", file=sys.stderr)
            sys.exit(1)
        if os.environ.get("FAUX_CIME_OCCUPES") and "--forcer" not in args:
            print(json.dumps({"resultat": "refuse", "occupes": os.environ["FAUX_CIME_OCCUPES"].split(","),
                              "message": "agents occupés"}))
            print("sur stderr", file=sys.stderr)
            sys.exit(5)
        conversations = [{"agent": "assistant", "session": "s-1", "tmux": "p-alpha-assistant"},
                         {"agent": "coord-hote", "session": "s-2", "tmux": "p-alpha-coord-hote"}]
        etat.mkdir(parents=True, exist_ok=True)
        (etat / "ferme.json").write_text(json.dumps({"heure": "2026-10-12T00:00:00Z", "conversations": conversations,
                                                     "a_relancer": [], "taches_en_cours": []}))
        reponse = {"resultat": "ok", "conversations": conversations, "taches_en_cours": []}
        if os.environ.get("FAUX_CIME_ECHECS"):
            reponse["echecs"] = ["équipe lente"]
        print(json.dumps(reponse))
        print("sur stderr", file=sys.stderr)
        sys.exit(0)
    # rouvrir
    if os.environ.get("FAUX_CIME_TEXTE"):
        print("ceci n'est pas du JSON")
        sys.exit(0)
    if os.environ.get("FAUX_CIME_ERREUR"):
        print(json.dumps({"resultat": "erreur", "message": os.environ["FAUX_CIME_ERREUR"]}))
        print("sur stderr", file=sys.stderr)
        sys.exit(1)
    (etat / "ferme.json").unlink(missing_ok=True)
    assistant = f"p-{chemin.name}-assistant"
    a_approuver = os.environ.get("FAUX_CIME_CODE") == "3"
    print(json.dumps({"resultat": "ok", "assistant": assistant, "coordinateurs": ["p-alpha-coord-hote"],
                      "equipes": ["hote"],
                      "a_approuver": a_approuver, "taches_en_cours": [],
                      "conversation": {"session": "s-1", "date": "2026-10-11T18:00:00Z"}}))
    print("sur stderr", file=sys.stderr)
    sys.exit(3 if a_approuver else 0)

if args[0] == "servir":
    if os.environ.get("FAUX_CIME_MEURT"):
        print("registre cassé", flush=True)
        sys.exit(4)
    if os.environ.get("FAUX_CIME_JAMAIS"):
        print("je ne démarre pas", flush=True)
        time.sleep(60)
        sys.exit(1)
    import sqlite3
    from cime.hote.dependances import Dependances
    from cime.hote.serveur import servir
    projet = Path(os.environ["CIME_PROJET"])
    (projet / ".orga" / "etat").mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(projet / ".orga" / "etat" / "registre.sqlite")
    con.executescript(
        "CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, horodatage TEXT, de TEXT, a TEXT,"
        " nature TEXT, resume TEXT, fichier TEXT, en_reponse_a INTEGER, equipe TEXT);"
        "CREATE TABLE IF NOT EXISTS evenements(id INTEGER PRIMARY KEY, horodatage TEXT, agent TEXT,"
        " session_id TEXT, evenement TEXT, details TEXT);"
        "CREATE TABLE IF NOT EXISTS journal(id INTEGER PRIMARY KEY, horodatage TEXT NOT NULL,"
        " auteur TEXT NOT NULL, action TEXT NOT NULL, cible TEXT, details TEXT, resultat TEXT NOT NULL);")
    con.commit()
    con.close()
    inst = lambda p: {"version": 1, "genere_a": datetime.now(timezone.utc).isoformat()}
    servir(projet, 0, deps=Dependances(instantane=inst))
