"""Réglages Claude Code générés à l'installation : hooks, interdits, permissions."""
import copy
import re
import shlex
from pathlib import Path

from cime.fondation.nom import NOM
from cime.signaux import echeances

EVENEMENTS = (
    "SessionStart", "SessionEnd", "UserPromptSubmit", "Stop", "PermissionRequest",
    "Notification", "PostToolUse", "PreCompact", "PostCompact", "SubagentStart",
    "SubagentStop", "StopFailure", "PostToolUseFailure",
)

_FIN_GARDE = "[ $c -eq 0 ] || exit 2"
DELAI_PERMISSION = 5  # secondes : forme acceptée par Claude Code

# Un coordinateur commite dans le worktree de son équipe (règle `allow` générée au lancement,
# voir `regles_commit_equipe` ; la garde refuse tout autre dossier) mais ne déplace ni ne défait
# rien, et ne réécrit pas l'historique : ni checkout, switch, stash, restore, reset, ni
# `commit --amend` ou `--no-verify`, avec ou sans `-C`.
_VERBES_HISTOIRE = ("checkout", "switch", "stash", "restore", "reset")
INTERDITS_COORDINATEUR = (
    *(f"Bash(git {v}*)" for v in _VERBES_HISTOIRE),
    *(f"Bash(git -C * {v}*)" for v in _VERBES_HISTOIRE),
    "Bash(git commit*--amend*)", "Bash(git commit*--no-verify*)",
    "Bash(git -C * commit*--amend*)", "Bash(git -C * commit*--no-verify*)",
)
# Registre 2.0 : la session d'intégration n'écrit pas le projet, elle ne commite jamais ni ne fusionne
# (une règle `deny` l'emporte sur toute règle `allow`), avec ou sans `-C`, et sa jumelle `rtk`.
INTERDITS_INTEGRATION = tuple(
    r for v in ("add", "commit", "merge")
    for r in (f"Bash(git {v}*)", f"Bash(rtk git {v}*)", f"Bash(git -C * {v}*)", f"Bash(rtk git -C * {v}*)"))
ROLES = ("commun", "agent", "coordinateur")
# Commun à tous (Assistant compris) : pas de push, pas de secrets.
INTERDITS_COMMUN = (
    "Bash(git push*)", "Bash(git -C * push*)",
    "Bash(security *)",
    "Read(~/.ssh/**)", "Read(~/.aws/**)", "Read(~/.config/gh/**)",
    "Read(**/.env)", "Read(**/.env.*)",
)
# Workers et coordinateurs : pas de suppression de branche, pas de fusion dans le dépôt
# principal, pas de notification macOS (seul l'Assistant en envoie).
_INTERDITS_AGENT_SANS_PROJET = (
    "Bash(git branch -D*)", "Bash(git branch -d*)", "Bash(git branch --delete*)",
    "Bash(git -C * branch -D*)", "Bash(git -C * branch -d*)", "Bash(git -C * branch --delete*)",
    "Bash(osascript *)",
)


def regles_commit_equipe(worktree: Path) -> list[str]:
    """Règles `allow` d'un coordinateur : `git add` et `git commit` dans le worktree de son équipe,
    et d'elle seule. Pas de jumelle `rtk` : on n'élargit pas ce qui écrit."""
    return [f"Bash(git -C {worktree} add*)", f"Bash(git -C {worktree} commit*)"]


def _avec_rtk(regles: list[str]) -> list[str]:
    """Chaque règle `Bash(<commande>)` suivie de sa jumelle `Bash(rtk <commande>)` : RTK
    réécrit `git status` en `rtk git status`, que la règle d'origine ne couvre plus."""
    resultat: list[str] = []
    for regle in regles:
        resultat.append(regle)
        if regle.startswith("Bash("):
            resultat.append(f"Bash(rtk {regle[len('Bash('):]}")
    return resultat


def commande_hook(evenement: str, executable: str | None = None,
                  ancien: bool = False) -> str:
    """Ligne de commande d'un hook. Avec `executable` (chemin absolu de `cime`), le hook
    ne dépend pas du PATH de la session ; sans lui, c'est le nom nu (PATH requis).

    Mesuré : un hook qui sort en 127 est « non bloquant » pour
    Claude Code, la commande passe. Pour PreToolUse (la garde), un exécutable disparu sort
    donc en 2 avec un message, au lieu de laisser tout passer en silence."""
    if executable is None:
        return f"{NOM} hook {evenement}"
    exe = shlex.quote(executable)
    appel = f"{exe} hook {evenement}"
    if evenement != "PreToolUse":
        return appel
    message = shlex.quote(f"{NOM} : exécutable introuvable ({executable}) : la garde ne peut "
                          f"pas s'exécuter, commande refusée. Relancer `{NOM} init`.")
    garde = f"[ -x {exe} ] || {{ echo {message} >&2; exit 2; }}; "
    if ancien:
        return f"{garde}exec {appel}"
    # Pas d'`exec` : un `cime` présent mais cassé (sortie 1, 126…) est une erreur non
    # bloquante pour Claude Code ; tout code non nul est converti en 2 (blocage).
    return f"{garde}{appel}; c=$?; {_FIN_GARDE}"


def _hook(evenement: str, matcher: str | None = None,
          executable: str | None = None, timeout: int | None = None) -> list[dict]:
    commande = {"type": "command", "command": commande_hook(evenement, executable)}
    if evenement == "PermissionRequest":
        commande["timeout"] = DELAI_PERMISSION
    elif timeout is not None:
        commande["timeout"] = timeout
    groupe: dict = {"hooks": [commande]}
    if matcher:
        groupe = {"matcher": matcher, **groupe}
    return [groupe]


def bac_a_sable(projet: Path, sites: list[str], home: Path, uid: int,
                zones_ecriture: list[Path], outil: Path | None = None,
                source: Path | None = None) -> dict:
    """Bloc `sandbox` d'un agent : chemins propres à la machine et au projet. Ne lit aucun
    fichier : tout vient des arguments. Lecture : le projet seul (worktrees compris), plus
    `outil` (racine de l'environnement de `cime`, voir `lancer.dossier_outil`) s'il n'est
    pas déjà couvert par une lecture existante, et `source` (dossier d'où `cime` est
    effectivement importé, voir `lancer.dossier_source_cime`) sous la même condition, sauf si
    c'est la maison ou un parent de la maison. Écriture : `zones_ecriture`, celles de la
    garde de périmètre (voir `perimetre.zones_ecriture_projet`), plus les caches d'uv."""
    home = str(home)
    ecriture = list(dict.fromkeys(str(z) for z in zones_ecriture))
    ecriture += [f"{home}/.cache/uv", f"{home}/.local/share/uv/python"]
    lecture = [str(projet), f"{home}/.gitconfig", f"{home}/.config/git",
               f"{home}/.local/share/uv/python", f"{home}/.local/bin", f"{home}/.cache/uv"]
    if outil is not None and not any(Path(outil).is_relative_to(d) for d in lecture):
        lecture.append(str(outil))
    if source is not None:
        source = Path(source)
        maison = Path(home)
        if (source != maison and source not in maison.parents
                and not any(source.is_relative_to(d) for d in lecture)):
            lecture.append(str(source))
    return {"sandbox": {
        "enabled": True, "failIfUnavailable": True, "allowUnsandboxedCommands": False,
        "autoAllowBashIfSandboxed": True,
        "filesystem": {
            "denyRead": [home],
            "allowRead": lecture,
            "allowWrite": ecriture,
        },
        # Pas de `allowUnixSockets` : le socket tmux n'est plus accessible aux agents
        # ; seuls le facteur et l'utilisateur y accèdent.
        "network": {"allowLocalBinding": True, "allowedDomains": list(sites)},
    }}


def reglages(projet: Path, branche_reference: str, role: str = "commun",
             executable: str | None = None) -> dict:
    if role not in ROLES:
        raise ValueError(f"rôle de réglages inconnu : {role!r}")
    projet = Path(projet).resolve()
    # Worktrees d'équipe : dans le projet, sous `.orga/worktrees/<équipe>`.
    worktrees = projet / ".orga" / "worktrees"
    # Read/Edit : chemin absolu = deux barres obliques ; Bash : chemin tel quel.
    lecture_ecriture = []
    for racine in (projet, worktrees):
        lecture_ecriture += [f"Read(/{racine}/**)", f"Edit(/{racine}/**)"]
    deny = list(INTERDITS_COMMUN)
    if role in ("agent", "coordinateur"):
        deny += [*_INTERDITS_AGENT_SANS_PROJET, f"Bash(git -C {projet} merge*)"]
    if role == "coordinateur":
        deny += INTERDITS_COORDINATEUR
    deny = _avec_rtk(deny)
    # Seules les lectures ont une jumelle `rtk` : on n'élargit pas ce qui écrit.
    lectures = _avec_rtk([
        "Bash(git status*)", "Bash(git log*)", "Bash(git diff*)", "Bash(git show*)",
        "Bash(git worktree list*)",
    ])
    allow = [
        "Bash(uv *)", f"Bash({NOM} *)",
        *lectures,
        f"Bash(git -C {worktrees}/* commit*)", f"Bash(git -C {worktrees}/* merge*)",
        "Bash(pytest*)",
        *lecture_ecriture,
    ]
    # `Stop` attend un message (M-I) : son timeout couvre l'attente plus une marge. Le fichier
    # "commun" est celui de l'Assistant, dont le hook `Stop` ne dort jamais.
    attente = 0 if role == "commun" else echeances.ATTENTE_STOP
    hooks = {e: _hook(e, None, executable,
                      attente + echeances.MARGE_STOP if e == "Stop" else None)
             for e in EVENEMENTS}
    # Sans filtre : la garde de périmètre voit tous les outils (Write, Read, Edit…), pas
    # seulement Bash. Mesuré en réel : avec `matcher: Bash`, elle ne tournait pas.
    hooks["PreToolUse"] = _hook("PreToolUse", None, executable)
    return {"hooks": hooks, "permissions": {"allow": allow, "deny": deny}}


_APPEL_HOOK = re.compile(rf"{NOM}'? hook (\w+)(?:; c=\$\?; {re.escape(_FIN_GARDE)})?$")


def _identite(commande) -> str | None:
    """Un hook `cime hook X` reste le même hook, qu'il soit écrit en nom nu ou en chemin
    absolu : la fusion ne doit pas le doubler."""
    if isinstance(commande, str) and (m := _APPEL_HOOK.search(commande)):
        return f"{NOM} hook {m.group(1)}"
    return commande


def _commandes(groupes: list) -> set[tuple[str, str]]:
    return {(g.get("matcher", ""), _identite(h.get("command")))
            for g in groupes if isinstance(g, dict)
            for h in g.get("hooks", []) if isinstance(h, dict)}


def _anciennes_formes(evenement: str, cible: str) -> set[str]:
    """Commandes qu'un projet d'avant a pu écrire pour `cible` : le nom nu, et pour la garde
    la forme `exec` au même chemin."""
    anciennes = {commande_hook(evenement)}
    if evenement == "PreToolUse" and "; c=$?;" in cible:
        debut = cible.split("; c=$?;")[0]  # …; <appel>
        anciennes.add(debut.rsplit("; ", 1)[0] + "; exec " + debut.rsplit("; ", 1)[1])
    return anciennes


def _remplacer_noms_nus(hooks: dict, nouveau: dict) -> list[str]:
    """Seule réécriture permise : un hook dont la commande est exactement l'appel en nom
    nu `cime hook <Év>`, ou l'ancienne forme `exec` de la garde au même chemin (même
    événement, même matcher), prend la forme au chemin absolu que `nouveau` porte. Un nom nu sort en 127 sans `cime` sur le PATH, et un PreToolUse en 127
    laisse passer la commande. Sans chemin absolu dans `nouveau`, rien n'est réécrit."""
    remplaces: list[str] = []
    for evenement, groupes in nouveau.get("hooks", {}).items():
        nu = commande_hook(evenement)
        for voulu in groupes:
            cible = voulu["hooks"][0]["command"]
            if cible == nu:
                continue
            anciennes = _anciennes_formes(evenement, cible)
            for groupe in hooks.get(evenement, []):
                if not isinstance(groupe, dict) or \
                        groupe.get("matcher", "") != voulu.get("matcher", ""):
                    continue
                for h in groupe.get("hooks", []):
                    if isinstance(h, dict) and h.get("command") in anciennes:
                        remplaces.append(
                            f"remplacé : hooks.{evenement} : {h['command']} → {cible}")
                        h["command"] = cible
    return remplaces


def _retirer_filtre(courants: list, evenement: str, groupes: list) -> list[str]:
    """Forme d'avant : un hook `cime` était sous un filtre (`matcher: Bash`). Le groupe voulu,
    sans filtre, le remplace : notre hook sort du groupe filtré, les autres hooks de ce
    groupe restent, et un groupe vide disparaît. Annoncé."""
    anciennes: set[str] = set()
    for voulu in groupes:
        if not voulu.get("matcher"):
            for h in voulu["hooks"]:
                anciennes |= {h["command"], *_anciennes_formes(evenement, h["command"])}
    remplaces: list[str] = []
    for groupe in list(courants):
        if not isinstance(groupe, dict) or not groupe.get("matcher"):
            continue
        gardes = [h for h in groupe.get("hooks", [])
                  if not (isinstance(h, dict) and h.get("command") in anciennes)]
        if len(gardes) == len(groupe.get("hooks", [])):
            continue
        remplaces.append(f"remplacé : hooks.{evenement} : matcher {groupe['matcher']} "
                         "→ tous les outils")
        if gardes:
            groupe["hooks"] = gardes
        else:
            courants.remove(groupe)
    return remplaces


def _ajouter_timeouts(hooks: dict, nouveau: dict) -> list[str]:
    """Un hook déjà installé (1.10) qui n'a pas de `timeout` alors que le hook voulu en porte un
    (le `Stop` qui attend un message) le reçoit. Un `timeout` déjà présent n'est jamais changé."""
    ajouts: list[str] = []
    for evenement, groupes in nouveau.get("hooks", {}).items():
        for voulu in groupes:
            for h_voulu in voulu["hooks"]:
                if "timeout" not in h_voulu:
                    continue
                identite = _identite(h_voulu["command"])
                for groupe in hooks.get(evenement, []):
                    if not isinstance(groupe, dict) or \
                            groupe.get("matcher", "") != voulu.get("matcher", ""):
                        continue
                    for h in groupe.get("hooks", []):
                        if isinstance(h, dict) and "timeout" not in h \
                                and _identite(h.get("command")) == identite:
                            h["timeout"] = h_voulu["timeout"]
                            ajouts.append(f"hooks.{evenement} : timeout {h_voulu['timeout']}")
    return ajouts


def fusionner(existant: dict, nouveau: dict) -> tuple[dict, list[str]]:
    """Fusion additive : ajoute le manquant, ne retire rien. Exceptions annoncées : les hooks
    au nom nu `cime hook <Év>` prennent la forme au chemin absolu, et un hook `cime` sous un
    filtre (forme d'avant) est remplacé par le groupe sans filtre."""
    resultat = copy.deepcopy(existant)
    ajouts: list[str] = []
    permissions = resultat.setdefault("permissions", {})
    for liste in ("allow", "deny"):
        courante = permissions.setdefault(liste, [])
        for regle in nouveau.get("permissions", {}).get(liste, []):
            if regle not in courante:
                courante.append(regle)
                ajouts.append(f"permissions.{liste} : {regle}")
    hooks = resultat.setdefault("hooks", {})
    ajouts += _remplacer_noms_nus(hooks, nouveau)
    ajouts += _ajouter_timeouts(hooks, nouveau)
    for evenement, groupes in nouveau.get("hooks", {}).items():
        courants = hooks.setdefault(evenement, [])
        ajouts += _retirer_filtre(courants, evenement, groupes)
        presents = _commandes(courants)
        for groupe in groupes:
            matcher = groupe.get("matcher", "")
            if any((matcher, _identite(h["command"])) not in presents for h in groupe["hooks"]):
                courants.append(copy.deepcopy(groupe))
                ajouts.append(f"hooks.{evenement} : {groupe['hooks'][0]['command']}")
    for cle in ("permissions", "hooks"):
        if not resultat[cle] and cle not in existant:
            del resultat[cle]
    return resultat, ajouts
