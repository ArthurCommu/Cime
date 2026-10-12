"""Lecture de tmux : sessions vivantes, vrais brouillons et écrans de démarrage.

Lecture seule : seuls `list-sessions` et `capture-pane` sont appelés.
"""

import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

_SGR = re.compile(r"\x1b\[([0-9;:]*)m")
_ANSI = re.compile(r"\x1b(?:\[[0-9;:?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-Z\\-_])")
_REGLE = re.compile(r"^─{3,}$")
_IDENTITE = re.compile(r"^(assistant|coord-[a-z0-9-]+|worker-[a-z0-9-]+)$")


def _iso(epoch: str) -> str:
    dt = datetime.fromtimestamp(int(epoch), tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", *args], capture_output=True, text=True, timeout=2)


_MODELE_LANCEMENT = re.compile(r"--model[= ]+[\"']?([A-Za-z0-9][A-Za-z0-9._\[\]-]*)")

def lister_sessions(prefixe: str) -> tuple[dict | None, dict]:
    nom = "tmux"
    try:
        res = _tmux(
            "list-sessions", "-F",
            "#{session_name}\t#{session_created}\t#{window_activity}\t#{pane_current_path}\t#{pane_start_command}",
        )
    except FileNotFoundError:
        return None, {"nom": nom, "ok": False, "erreur": "tmux n'est pas installé"}
    except subprocess.TimeoutExpired:
        return None, {"nom": nom, "ok": False, "erreur": "tmux n'a pas répondu en 2 s"}
    except Exception as e:  # noqa: BLE001 — ne lève jamais
        return None, {"nom": nom, "ok": False, "erreur": f"tmux illisible : {e}"}
    if res.returncode != 0:
        err = (res.stderr or "").strip()
        if "no server running" in err or "error connecting" in err:
            msg = "aucun serveur tmux"
        else:
            msg = f"tmux a échoué : {err or 'code ' + str(res.returncode)}"
        return None, {"nom": nom, "ok": False, "erreur": msg}
    sessions: dict = {}
    try:
        for ligne in res.stdout.splitlines():
            champs = ligne.split("\t", 4)
            if len(champs) not in (3, 4, 5) or not champs[0].startswith(f"{prefixe}-"):
                continue
            nom_s, creee, activite = champs[:3]
            # 5 champs : cwd puis commande ; 4 champs (ancien format) : la commande seule
            cwd = champs[3] or None if len(champs) == 5 else None
            commande = champs[-1] if len(champs) > 3 else ""
            lancement = _MODELE_LANCEMENT.search(commande)
            identite = nom_s[len(prefixe) + 1:]
            sessions[nom_s] = {
                "identite": identite if _IDENTITE.match(identite) else None,
                "creee": _iso(creee),
                "cwd": cwd,
                "activite": _iso(activite),
                # `--model` de la commande de lancement : connu avant tout hook (écran de démarrage)
                "modele_lancement": lancement.group(1) if lancement else None,
            }
    except Exception as e:  # noqa: BLE001
        return None, {"nom": nom, "ok": False, "erreur": f"sortie tmux illisible : {e}"}
    return sessions, {"nom": nom, "ok": True}


def _sans_attenue(ligne: str) -> str:
    """Retire le texte atténué (SGR 2 actif) et toutes les séquences d'échappement."""
    sortie: list[str] = []
    attenue = False
    pos = 0
    for m in _SGR.finditer(ligne):
        if not attenue:
            sortie.append(ligne[pos:m.start()])
        pos = m.end()
        params = [p for p in re.split(r"[;:]", m.group(1))]
        if not params or params == [""]:
            params = ["0"]
        i = 0
        while i < len(params):
            p = params[i]
            if p in ("38", "48", "58"):  # couleur étendue : saute ses arguments
                i += 2 if i + 1 < len(params) and params[i + 1] == "5" else 4
                continue
            if p in ("0", ""):
                attenue = False
            elif p == "2":
                attenue = True
            elif p == "22":
                attenue = False
            i += 1
    if not attenue:
        sortie.append(ligne[pos:])
    return _ANSI.sub("", "".join(sortie))


def extraire_brouillon(capture_ansi: str) -> str | None:
    try:
        lignes = capture_ansi.split("\n")
        nues = [_ANSI.sub("", l).rstrip() for l in lignes]
        regle = [bool(_REGLE.match(n.strip())) for n in nues]
        # dernière invite : ligne `❯` encadrée au-dessus par une ligne de `─`
        for i in range(len(lignes) - 1, 0, -1):
            if not regle[i - 1] or not nues[i].lstrip().startswith("❯"):
                continue
            fin = next((j for j in range(i + 1, len(lignes)) if regle[j]), None)
            if fin is None:
                continue
            bloc = lignes[i:fin]
            textes = []
            attenue = False
            for k, l in enumerate(bloc):
                if k == 0:
                    l = l.replace("❯", "", 1) if "❯" in l else l
                # l'état atténué ne traverse pas les lignes
                textes.append(_sans_attenue(l))
            premier = textes[0].lstrip("  ") if textes else ""
            suite = [t[2:] if t.startswith("  ") else t for t in textes[1:]]
            texte = "\n".join([premier, *suite]).replace(" ", " ").rstrip()
            return texte.strip(" \n")
        return None
    except Exception:  # noqa: BLE001 — ne lève jamais
        return None


_DERNIERE_LIGNE_DEMARRAGE = "Enter to confirm · Esc to cancel"


def ecran_demarrage(capture_ansi: str) -> str | None:
    """`"confiance"`, `"imports"`, `"autre"` si l'écran est un écran de démarrage de Claude Code, sinon `None`.

    Critère : la dernière ligne non vide (ANSI retiré, bords nettoyés) est exactement
    `Enter to confirm · Esc to cancel`. Un texte qui cite l'écran plus haut ne compte pas.
    """
    try:
        texte = _ANSI.sub("", capture_ansi).replace("\xa0", " ")
        lignes = [l.strip() for l in texte.split("\n")]
        non_vides = [l for l in lignes if l]
        if not non_vides or non_vides[-1] != _DERNIERE_LIGNE_DEMARRAGE:
            return None
        if "trust this folder" in texte:
            return "confiance"
        if "Allow external CLAUDE.md file imports" in texte:
            return "imports"
        return "autre"
    except Exception:  # noqa: BLE001 — ne lève jamais
        return None


def _capturer(session: str) -> dict:
    """Une seule capture par session : brouillon et écran de démarrage."""
    try:
        res = _tmux("capture-pane", "-p", "-e", "-t", session)
        if res.returncode != 0:
            return {"brouillon": None, "ecran_demarrage": None}
        return {"brouillon": extraire_brouillon(res.stdout),
                "ecran_demarrage": ecran_demarrage(res.stdout)}
    except Exception:  # noqa: BLE001
        return {"brouillon": None, "ecran_demarrage": None}


def lire_invites(sessions: list[str], prefixe: str) -> tuple[dict | None, dict]:
    nom = "tmux-invites"
    try:
        privee = f"{prefixe}-assistant"
        a_lire = [s for s in sessions if s != privee]
        resultats: dict = {s: {"brouillon": None, "ecran_demarrage": None} for s in sessions}
        if a_lire:
            with ThreadPoolExecutor(max_workers=min(16, len(a_lire))) as pool:
                for s, r in zip(a_lire, pool.map(_capturer, a_lire)):
                    resultats[s] = r
        return resultats, {"nom": nom, "ok": True}
    except Exception as e:  # noqa: BLE001
        return None, {"nom": nom, "ok": False, "erreur": f"lecture des invites impossible : {e}"}
