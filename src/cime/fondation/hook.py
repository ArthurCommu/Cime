"""`cime hook <Événement>` : écrit l'événement d'un hook Claude Code au registre.

Ne fait jamais échouer l'agent : toute exception est journalisée, code 0.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from cime.fondation.nom import VAR_AGENT

LIMITE = 2000

# Champs propres à chaque événement, recopiés du JSON reçu s'ils y figurent.
# Noms mesurés sur Claude Code 2.1.292.
# Le SubagentStop fantôme (agent_type "")
# est écrit tel quel : c'est le lecteur qui l'ignore.
CHAMPS = {
    "SessionStart": ("source", "model"),
    "SessionEnd": ("reason",),
    "UserPromptSubmit": ("prompt",),
    "Stop": ("last_assistant_message", "stop_hook_active"),
    "StopFailure": ("error", "last_assistant_message"),
    "PermissionRequest": ("tool_name", "tool_input"),
    "Notification": ("notification_type", "message"),
    "PostToolUse": ("tool_name",),
    "PostToolUseFailure": ("tool_name", "error"),
    "PreCompact": ("trigger",),
    "PostCompact": ("trigger",),
    "SubagentStart": ("agent_type", "agent_id"),
    "SubagentStop": ("agent_type", "agent_id"),
    "PreToolUse": (),
}
COMMUNS = ("cwd", "transcript_path")

DELAI_RESEAU = 0.5
DELAI_GIT = 5  # résolution d'une branche fusionnée, pour fusions.log
LIMITE_COMMANDE = 300  # commande copiée dans fusions.log
FUSION_AVANT = "fusion-avant"  # .orga/etat/ : pointe de la branche de référence avant la fusion


def _tronquer(valeur):
    if isinstance(valeur, str):
        return valeur[:LIMITE]
    if isinstance(valeur, (dict, list)):
        texte = json.dumps(valeur, ensure_ascii=False)
        if len(texte) > LIMITE:
            return {"_tronque": texte[:LIMITE]}
    return valeur


def _details(evenement: str, entree: dict) -> dict:
    details = {c: entree[c] for c in COMMUNS if c in entree}
    for champ in CHAMPS[evenement]:
        if champ in entree:
            details[champ] = _tronquer(entree[champ])
    if evenement == "PostToolUse":
        tool_input = entree.get("tool_input")
        if isinstance(tool_input, dict) and "file_path" in tool_input:
            details["file_path"] = tool_input["file_path"]
    return details


def _journaliser_erreur(projet: Path | None, evenement: str, erreur: BaseException):
    if projet is None:
        return
    try:
        from cime.fondation.registre import horodatage
        dossier = Path(projet) / ".orga" / "etat"
        dossier.mkdir(parents=True, exist_ok=True)
        with open(dossier / "hooks-erreurs.log", "a", encoding="utf-8") as f:
            f.write(f"{horodatage()} {evenement} {erreur!r}".replace("\n", " ") + "\n")
    except Exception:
        pass


def _inscrire(conn, agent, entree, evenement, details) -> int:
    from cime.fondation import registre
    return registre.inscrire_evenement(
        conn, agent=agent, session_id=entree.get("session_id"),
        evenement=evenement, details=details)


# Copie volontaire de garde._REPLI : ce repli doit marcher quand le module garde est
# absent (installation cassée). Un test vérifie que les deux listes sont identiques. Aucun
# motif ne traverse une fin de ligne ; les continuations (`\` final) sont jointes avant.
REPLI = [r"\bgit\b[^;&|\n]*\bpush\b", r"\bsecurity\b",
         r"\bgit\b[^;&|\n]*\bbranch\b[^;&|\n]*[^\S\n]-(d|D|-delete)\b",
         r"\brtk[^\S\n]+proxy\b",
         r"\btmux\b"]
M_GARDE_ABSENTE = ("le garde est indisponible (installation incomplète) et cette commande "
                   "ressemble à une action interdite (push, suppression de branche, "
                   "Trousseau, rtk proxy, tmux) : refusée par prudence. "
                   "Signale-le à ton supérieur.")


def _repli_garde_absente(entree: dict) -> str | None:
    """Garde introuvable : ne pas tout laisser passer. Bash seulement, texte brut."""
    import re
    commande = (entree.get("tool_input") or {}).get("command")
    if entree.get("tool_name") == "Bash" and isinstance(commande, str) \
            and any(re.search(r, commande.replace("\\\n", " ")) for r in REPLI):
        return M_GARDE_ABSENTE
    return None


# Copie volontaire de perimetre.CHAMPS et de la liste des outils de fichiers : ce
# refus doit tenir quand le module perimetre est absent.
CHAMPS_CHEMIN = ("file_path", "path", "notebook_path", "directory")
OUTILS_FICHIER = {"Read", "Write", "Edit", "NotebookEdit", "Glob", "Grep"}
M_PERIMETRE_ABSENT = ("le garde de périmètre est indisponible (installation incomplète) : "
                      "{outil} est refusé par prudence. Signale-le à ton supérieur.")


def _outil_de_fichier(entree: dict) -> bool:
    if entree.get("tool_name") == "Bash":
        return False
    tool_input = entree.get("tool_input")
    return entree.get("tool_name") in OUTILS_FICHIER or (
        isinstance(tool_input, dict) and any(c in tool_input for c in CHAMPS_CHEMIN))


def _perimetre(entree: dict, projet: Path, journal: Path | None) -> str | None:
    try:
        from cime.fondation import perimetre
    except ImportError as e:
        _journaliser_erreur(journal, "PreToolUse", e)
        if _outil_de_fichier(entree):
            return M_PERIMETRE_ABSENT.format(outil=entree.get("tool_name"))
        return None
    return perimetre.decider(entree, projet)


def _decider(entree: dict, projet: Path | None, journal: Path | None) -> str | None:
    try:
        from cime.fondation import garde
    except ImportError as e:
        _journaliser_erreur(journal, "PreToolUse", e)
        motif = _repli_garde_absente(entree)
    else:
        motif = garde.decider(entree, projet)
    # Sans projet, il n'y a pas de racine à comparer : le périmètre ne s'applique pas.
    if motif or projet is None:
        return motif
    return _perimetre(entree, projet, journal)


def _dossier_de_secours() -> Path | None:
    """Où journaliser quand aucun projet n'est lisible : le dossier de $CIME_PROJET
    s'il existe et a déjà un `.orga/` (on ne crée pas d'arborescence ailleurs)."""
    from cime.fondation.nom import VAR_PROJET
    valeur = os.environ.get(VAR_PROJET)
    if valeur and (Path(valeur) / ".orga").is_dir():
        return Path(valeur)
    return None


def _refus(motif: str) -> str:
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": motif,
    }}, ensure_ascii=False)


def _pre_tool_use_sans_projet(entree: dict) -> str | None:
    motif = _decider(entree, None, _dossier_de_secours())
    return _refus(motif) if motif else None


def _sha_commit(projet: Path, ref: str) -> str:
    """Sha complet vers lequel `ref` se résout dans le dépôt principal, ou `inconnu`."""
    if ref.startswith("-"):  # jamais lu comme une option de git
        return "inconnu"
    try:
        r = subprocess.run(["git", "-C", str(projet), "rev-parse", "--verify",
                            f"{ref}^{{commit}}"],
                           capture_output=True, text=True, timeout=DELAI_GIT)
    except (OSError, subprocess.SubprocessError):
        return "inconnu"
    sha = r.stdout.strip()
    return sha if r.returncode == 0 and sha else "inconnu"


def _journaliser_fusions(projet: Path, entree: dict) -> None:
    """Une ligne d'intention par branche que l'Assistant fait fusionner sur le dépôt
    principal, écrite avant la fusion. Ne bloque jamais la fusion : un échec d'écriture va
    dans hooks-erreurs.log.

    Le journal : `<horodatage> assistant <sha> <référence> <commande>` (intention), puis,
    après la fusion, `<horodatage> assistant <sha> <référence> resultat=<…>` (voir
    `_journaliser_resultats`). Une intention sans ligne de résultat : la commande n'a pas
    abouti (PostToolUse ne se déclenche pas sur un échec) ou le résultat est inconnu."""
    try:
        from cime.fondation import garde
        refs = garde.fusions_autorisees(entree, projet)
        if not refs:
            return
        from cime.fondation.registre import horodatage
        maintenant = horodatage()
        commande = str((entree.get("tool_input") or {}).get("command", ""))
        commande = commande.replace("\r", " ").replace("\n", " ")[:LIMITE_COMMANDE]
        dossier = Path(projet) / ".orga" / "etat"
        dossier.mkdir(parents=True, exist_ok=True)
        with open(dossier / "fusions.log", "a", encoding="utf-8") as f:
            for ref in refs:
                sha = _sha_commit(projet, ref)
                f.write(f"{maintenant} {garde.ASSISTANT} {sha} {ref} {commande}\n")
        # la pointe de la branche de référence AVANT la fusion : le diff de la fusion
        (dossier / FUSION_AVANT).write_text(_sha_commit(projet, "HEAD") + "\n", encoding="utf-8")
    except Exception as e:
        _journaliser_erreur(projet, "PreToolUse", e)


def _resultat(projet: Path, sha: str) -> str:
    """`fusionne` si `sha` est dans HEAD du dépôt principal, `non-fusionne` sinon, `inconnu`
    quand le sha n'a pas été résolu ou que git ne répond pas dans le délai."""
    if sha == "inconnu":
        return "inconnu"
    try:
        r = subprocess.run(["git", "-C", str(projet), "merge-base", "--is-ancestor", sha, "HEAD"],
                           capture_output=True, timeout=DELAI_GIT)
    except (OSError, subprocess.SubprocessError):
        return "inconnu"
    return {0: "fusionne", 1: "non-fusionne"}.get(r.returncode, "inconnu")


class _Fusions(list):
    """[(sha, résultat)] d'une commande de fusion, avec `refs` : les références de la commande, dans
    le même ordre. La garde ne les redonne plus une fois l'accord consommé, d'où ce porteur."""
    refs: list = []
    details: list = []   # une entrée par référence : {"ref", "voie", …} (garde.fusions_detaillees)


def _journaliser_resultats(projet: Path, entree: dict) -> list[tuple[str, str]]:
    """Une ligne de résultat par référence que la garde a permise à l'Assistant (même liste
    que `_journaliser_fusions`, lue après la commande). Un échec va dans hooks-erreurs.log.
    Renvoie [(sha, résultat)] pour que l'appelant consomme les accords des fusions faites."""
    faits = _Fusions()
    try:
        from cime.fondation import garde
        faits.details = garde.fusions_detaillees(entree, projet)
        refs = [d["ref"] for d in faits.details]
        faits.refs = list(refs)
        if not refs:
            return faits
        from cime.fondation.registre import horodatage
        maintenant = horodatage()
        dossier = Path(projet) / ".orga" / "etat"
        dossier.mkdir(parents=True, exist_ok=True)
        with open(dossier / "fusions.log", "a", encoding="utf-8") as f:
            for ref in refs:
                sha = _sha_commit(projet, ref)
                resultat = _resultat(projet, sha)
                f.write(f"{maintenant} {garde.ASSISTANT} {sha} {ref} resultat={resultat}\n")
                faits.append((sha, resultat))
    except Exception as e:
        _journaliser_erreur(projet, "PostToolUse", e)
    return faits


def _journaliser_fusions_auto(conn, projet: Path, fusions) -> None:
    """Une ligne `journal` (auteur assistant, action `fusion_auto`) par fusion faite par la voie
    automatique, une seule fois par (cible, annonce). Le nombre de fichiers est celui de la fusion
    elle-même : de la pointe d'avant (FUSION_AVANT) à HEAD, la différence de la garde étant vide
    une fois la branche fusionnée."""
    from cime.fondation.registre import horodatage
    try:
        avant = (Path(projet) / ".orga" / "etat" / FUSION_AVANT).read_text(encoding="utf-8").strip()
    except OSError:
        avant = ""
    for (sha, resultat), d in zip(fusions, getattr(fusions, "details", [])):
        if resultat != "fusionne" or d.get("voie") != "auto":
            continue
        cible = f"fusion:{d['equipe']}:{sha}"
        deja = [json.loads(det or "{}").get("annonce") for (det,) in conn.execute(
            "SELECT details FROM journal WHERE action = 'fusion_auto' AND cible = ?", (cible,))]
        if d["annonce"] in deja:
            continue
        fichiers = None
        if avant:
            r = subprocess.run(["git", "-C", str(projet), "diff", "--name-only", "--no-renames",
                                "-z", avant, "HEAD"], capture_output=True, text=True,
                               timeout=DELAI_GIT)
            if r.returncode == 0:
                fichiers = len([c for c in r.stdout.split("\0") if c])
        with conn:
            conn.execute(
                "INSERT INTO journal (horodatage, auteur, action, cible, details, resultat)"
                " VALUES (?, 'assistant', 'fusion_auto', ?, ?, 'ok')",
                (horodatage(), cible, json.dumps(
                    {"annonce": d["annonce"], "reglage": d["reglage"],
                     "fichiers": d["fichiers"] if fichiers is None else fichiers})))


def _apres_fusion(conn, projet: Path, entree: dict, fusions, evenement_id) -> None:
    """Après une fusion faite : `consigne suites:<é>`, `signalement contrat:<nom>`."""
    from cime.signaux import suites
    refs = getattr(fusions, "refs", [])   # même liste, même ordre que `fusions` (lue avant l'accord consommé)
    suites.apres_fusion_suites(
        conn, projet, [(ref, sha, resultat) for ref, (sha, resultat) in zip(refs, fusions)],
        evenement_id)
    try:
        avant = (Path(projet) / ".orga" / "etat" / FUSION_AVANT).read_text(encoding="utf-8").strip()
    except OSError:
        avant = ""
    suites.apres_fusion_contrats(conn, projet, avant, _sha_commit(projet, "HEAD"))


def _pre_tool_use(projet: Path, agent, entree: dict) -> str | None:
    motif = _decider(entree, projet, projet)
    if not motif:
        _journaliser_fusions(projet, entree)
        return None
    details = _details("PreToolUse", entree)
    for champ in ("tool_name", "tool_input"):
        if champ in entree:
            details[champ] = _tronquer(entree[champ])
    details["motif"] = motif
    from cime.fondation import registre
    conn = registre.ouvrir(projet)
    try:
        evenement_id = _inscrire(conn, agent, entree, "PreToolUse", details)
        try:  # le refus doit sortir même si le signalement échoue
            from cime.signaux import hooks
            hooks.sur_refus_garde(conn, projet, agent, entree, evenement_id, motif)
        except Exception as e:
            _journaliser_erreur(projet, "PreToolUse", e)
    finally:
        conn.close()
    return _refus(motif)


def _session_tmux(projet: Path, agent) -> str | None:
    if os.environ.get("TMUX"):
        import subprocess
        r = subprocess.run(["tmux", "display-message", "-p", "#S"],
                           capture_output=True, text=True, timeout=DELAI_RESEAU)
        nom = r.stdout.strip()
        return nom if r.returncode == 0 and nom else None
    if agent:
        from cime.fondation.projet import lire_manifeste, session_tmux
        return session_tmux(lire_manifeste(projet), agent)
    return None


def _notifier_hote(port: int, corps: dict) -> None:
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=DELAI_RESEAU)
    try:
        conn.request("POST", "/api/permissions", body=json.dumps(corps).encode(),
                     headers={"Content-Type": "application/json"})
        conn.getresponse().read()
    finally:
        conn.close()


def _permission(projet: Path, agent, entree: dict, demande_id: str) -> None:
    """Prévient l'hôte, une seule fois, sans attendre : le hook ne décide jamais ;
    la demande s'affiche dans le terminal."""
    fichier_port = projet / ".orga" / "etat" / "hote.port"
    try:
        port = int(fichier_port.read_text().strip())
    except (OSError, ValueError):
        return
    try:
        session = _session_tmux(projet, agent)
    except Exception:
        session = None
    try:
        _notifier_hote(port, {
            "demande_id": demande_id,
            "agent": agent,
            "session_tmux": session,
            "tool_name": entree.get("tool_name"),
            "tool_input": entree.get("tool_input"),
        })
    except Exception:
        pass


# Sorties : un hook rend son texte sur stderr avec le code 2 (`Stop`, `PostToolUse` : l'agent
# le lit et repart, M-A/M-B) ou sur stdout avec le code 0 (`SessionStart`, `UserPromptSubmit`).
SORTIE_STDERR = ("Stop", "PostToolUse")


def _rendre(evenement: str, texte: str | None) -> int:
    """Écrit `texte` là où l'événement le lit ; renvoie le code de sortie du hook."""
    if not texte:
        return 0
    if evenement in SORTIE_STDERR:
        sys.stderr.write(texte if texte.endswith("\n") else texte + "\n")
        sys.stderr.flush()
        return 2
    sys.stdout.write(texte)
    sys.stdout.flush()
    return 0


def executer(args) -> int:
    """Code de sortie : 0, ou 2 avec le texte à rendre sur stderr. Toute exception est
    journalisée et le code est 0 : un hook ne fait jamais échouer l'agent."""
    evenement = args.evenement
    projet = None
    try:
        if evenement not in CHAMPS:
            return 0
        from cime.fondation.projet import ErreurProjet, trouver_projet
        try:
            projet = trouver_projet()
        except ErreurProjet as e:
            if evenement != "PreToolUse":
                return 0
            # Les interdits universels ne dépendent pas du manifeste : sans projet,
            # la garde tourne quand même (seul l'enregistrement est abandonné).
            _journaliser_erreur(_dossier_de_secours(), evenement, RuntimeError(
                f"garde sans manifeste, règles universelles seulement : {e}"))
        agent = os.environ.get(VAR_AGENT) or None
        entree = json.loads(sys.stdin.read() or "{}")
        if not isinstance(entree, dict):
            raise ValueError("le JSON du hook n'est pas un objet")
        if evenement == "PreToolUse" and projet is None:
            sortie = _pre_tool_use_sans_projet(entree)
            if sortie:
                sys.stdout.write(sortie)
                sys.stdout.flush()
            return 0
        if evenement == "PreToolUse":
            sortie = _pre_tool_use(projet, agent, entree)
            if sortie:
                sys.stdout.write(sortie)
                sys.stdout.flush()
            return 0
        details = _details(evenement, entree)
        if evenement == "PermissionRequest":
            import uuid
            demande_id = str(uuid.uuid4())
            details["demande_id"] = demande_id
        from cime.fondation import registre
        conn = registre.ouvrir(projet)
        try:
            evenement_id = _inscrire(conn, agent, entree, evenement, details)
            if evenement == "PermissionRequest":
                _permission(projet, agent, entree, demande_id)
            if evenement == "PostToolUse":
                fusions = _journaliser_resultats(projet, entree)
                if any(r == "fusionne" for _, r in fusions):
                    try:  # un accord = une fusion : l'accord de chaque fusion faite est consommé
                        from cime.signaux import hooks   # (pas celui d'une fusion automatique : elle n'en a pas)
                        par_accord = [f for f, d in zip(fusions, fusions.details)
                                      if d.get("voie") != "auto"]
                        hooks.consommer_accords_fusion(conn, projet, par_accord, evenement_id)
                    except Exception as e:
                        _journaliser_erreur(projet, "PostToolUse", e)
                    try:  # fusions faites par l'option « Fusions automatiques »
                        _journaliser_fusions_auto(conn, projet, fusions)
                    except Exception as e:
                        _journaliser_erreur(projet, "PostToolUse", e)
                    try:  # suites déclarées et contrats modifiés
                        _apres_fusion(conn, projet, entree, fusions, evenement_id)
                    except Exception as e:
                        _journaliser_erreur(projet, "PostToolUse", e)
            if evenement in ("PostToolUse", "PostToolUseFailure"):
                try:  # `cime` introuvable sous le bac à sable de l'agent : on le rend bruyant
                    from cime.signaux import hooks
                    hooks.sur_import_cime_manquant(conn, projet, agent, entree)
                except Exception as e:
                    _journaliser_erreur(projet, evenement, e)
            return _rendre(evenement, _texte_a_rendre(
                conn, projet, agent, evenement, entree, evenement_id, details))
        finally:
            conn.close()
    except BaseException as e:  # jamais d'échec côté agent
        _journaliser_erreur(projet, evenement, e)
    return 0


def _texte_a_rendre(conn, projet, agent, evenement, entree, evenement_id,
                    details=None) -> str | None:
    """Courrier à rendre à l'agent (la prise se fait ici, juste avant l'écriture)."""
    from cime.signaux import hooks
    return hooks.rendre(conn, projet, agent, evenement, entree, evenement_id, details)
