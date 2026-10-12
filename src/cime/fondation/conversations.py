"""`conversations` : les conversations de l'Assistant d'un projet, avec leur début (lecture seule).

`debut` est le premier message de l'utilisateur, pas ce que Cime et Claude Code écrivent eux-mêmes
dans la conversation : prompt de lancement, courrier livré par le facteur, blocs système et de hook,
résumé de reprise après compaction, résultats d'outil. On ne lit que les premiers Kio du fichier :
une conversation peut peser des dizaines de Mo."""
import json
import re
from pathlib import Path

from cime.fondation import fermeture, lancer

LIMITE = 30
DEBUT_MAX = 120
LECTURE_MAX = 256 * 1024

# Blocs que Claude Code et ses hooks ajoutent au texte de l'utilisateur : balise fermée, ou ouverte
# jusqu'à la fin quand la lecture s'est arrêtée au milieu.
_BLOC_SYSTEME = re.compile(
    r"<(?P<balise>system-reminder|command-[a-z-]+|local-command-[a-z-]+|user-prompt-submit-hook"
    r"|[a-z-]*-hook)>.*?(?:</(?P=balise)>|\Z)", re.DOTALL)
# Courrier livré par le facteur : `<émetteur> : <corps> (#id)`, plusieurs séparés par « ‖ »
# (signaux/courrier.py : `formater`, `emetteur_lisible`) ; l'émetteur n'est jamais l'utilisateur ici.
_COURRIER = re.compile(r"(?:worker \S+|coordinateur \S+|Cime|Assistant) : .*\(#\d+\)", re.DOTALL)
_COURRIER_D_UTILISATEUR = re.compile(r"Utilisateur : (?P<texte>.*) \(#\d+\)", re.DOTALL)
_PROMPT_DE_LANCEMENT = re.compile(r"Lis .+ et (?:exécute-le|traite-la)\.")
_PREFIXES_CIME = ("Courrier remis à l'ouverture", "This session is being continued",
                  "[Request interrupted by user")
_PROMPTS_FIXES = (lancer.MESSAGE_ASSISTANT, lancer.MESSAGE_COORDINATEUR)


def _ouvrir(fichier: Path):
    return open(fichier, "rb")


def _ecrit_par_cime(texte: str) -> bool:
    return (texte in _PROMPTS_FIXES or bool(_PROMPT_DE_LANCEMENT.fullmatch(texte))
            or texte.startswith(_PREFIXES_CIME) or bool(_COURRIER.fullmatch(texte)))


def _texte_humain(texte: str) -> str:
    """Ce que l'utilisateur a écrit dans ce bloc de texte ; "" si c'est autre chose."""
    texte = " ".join(_BLOC_SYSTEME.sub(" ", texte).split())
    if not texte:
        return ""
    relaye = _COURRIER_D_UTILISATEUR.fullmatch(texte)
    if relaye:                      # l'utilisateur écrit dans la page : le facteur l'habille de son nom
        return relaye["texte"].strip()
    return "" if _ecrit_par_cime(texte) else texte


def _textes(contenu) -> list[str]:
    if isinstance(contenu, str):
        return [contenu]
    if not isinstance(contenu, list):
        return []
    return [b["text"] for b in contenu
            if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)]


def _message_humain(ligne) -> str:
    """Le texte de l'utilisateur dans cette ligne de transcript, "" s'il n'y en a pas."""
    if not isinstance(ligne, dict) or ligne.get("type") != "user":
        return ""
    if ligne.get("isMeta") or ligne.get("isCompactSummary") or ligne.get("isSidechain"):
        return ""
    message = ligne.get("message")
    if not isinstance(message, dict):
        return ""
    return " ".join(t for t in map(_texte_humain, _textes(message.get("content"))) if t)


def _couper(texte: str) -> str:
    return texte if len(texte) <= DEBUT_MAX else texte[:DEBUT_MAX - 1] + "…"


def debut_conversation(fichier: Path) -> str | None:
    """Premier message humain du fichier, vu dans ses `LECTURE_MAX` premiers octets ; None si
    aucun, ou si le fichier est illisible (`null` en JSON).
    Ne lève jamais."""
    try:
        with _ouvrir(fichier) as f:
            brut = f.read(LECTURE_MAX)
    except OSError:
        return None
    lignes = brut.decode("utf-8", errors="replace").split("\n")
    for ligne in lignes:
        try:
            texte = _message_humain(json.loads(ligne))
        except (ValueError, RecursionError):
            continue                # ligne illisible, ou coupée par la limite de lecture
        if texte:
            return _couper(texte)
    return None


def lister(projet: Path, racine_claude: Path | None = None) -> list[dict]:
    """Les `LIMITE` conversations les plus récentes du dossier de conversations de l'Assistant."""
    sous = lancer.dossier_conversations(projet, racine_claude)
    try:
        candidats = [f for f in sous.glob("*.jsonl") if f.is_file()]
    except OSError:
        return []
    trouves = []
    for f in candidats:
        try:
            trouves.append((f.stat().st_mtime, f.name, f, f.stat().st_size))
        except OSError:
            continue
    trouves.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [{"session": f.stem, "date": fermeture._date_conversation(f), "taille": taille,
             "debut": debut_conversation(f)}
            for _, _, f, taille in trouves[:LIMITE]]


def _lire(projet: Path, args, en_json: bool) -> int:
    liste = lister(projet)
    if en_json:
        print(json.dumps({"conversations": liste}, ensure_ascii=False), flush=True)
    elif not liste:
        print("aucune conversation", flush=True)
    else:
        for c in liste:
            print(f"{c['date']}  {c['taille']:>10} o  {c['session']}  {c['debut'] or ''}", flush=True)
    return 0


def executer(args) -> int:
    """`cime conversations <projet> [--json]` : l'utilisateur seulement (`debut` est du contenu)."""
    return fermeture._commande("conversations", args, _lire)
