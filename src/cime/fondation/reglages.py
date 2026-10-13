"""Réglages Claude Code générés à l'installation : hooks, interdits, permissions. Construit
aussi les réglages générés d'un agent au lancement : bac à sable, dossiers de travail."""
import copy
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from cime.fondation.nom import NOM
from cime.fondation.perimetre import zones_ecriture_projet
from cime.fondation.projet import ErreurProjet, Manifeste, worktree_equipe
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
    `outil` (racine de l'environnement de `cime`, voir `reglages.dossier_outil`) s'il n'est
    pas déjà couvert par une lecture existante, et `source` (dossier d'où `cime` est
    effectivement importé, voir `reglages.dossier_source_cime`) sous la même condition, sauf si
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


class Refus(ErreurProjet):
    """Reprise refusée avant tout lancement (code 2)."""


_FICHIER_ROLE = {"assistant": "settings.json", "worker": "settings-agent.json",
                 "coord": "settings-coordinateur.json"}


def fichier_reglages_statique(projet: Path, role: str) -> Path:
    """Fichier statique du rôle (`.claude/settings*.json`), écrit par `init`."""
    nom = _FICHIER_ROLE[role]
    fichier = (Path(projet) / ".claude" / nom).resolve()
    if not fichier.is_file():
        raise ErreurProjet(
            f"réglages absents : {fichier} — relance `{NOM} init` dans ce projet "
            "(il écrit les fichiers de réglages manquants, sans toucher aux autres)")
    return fichier


def dossier_etat(projet: Path) -> Path:
    return Path(projet) / ".orga" / "etat"


def dossier_tmp(projet: Path) -> Path:
    """Dossier temporaire de Claude Code (CLAUDE_CODE_TMPDIR) : privé, il veut 0o700."""
    return dossier_etat(projet) / "tmp"


def dossier_memoire(projet: Path) -> Path:
    return dossier_etat(projet) / "memoire"


def dossier_essais(projet: Path) -> Path:
    """Essais et intégration : jamais hors du projet (voir le socle, `integration.md`)."""
    return dossier_etat(projet) / "essais"


def preparer_tmp(projet: Path) -> None:
    dossier = dossier_tmp(projet)
    dossier.mkdir(parents=True, exist_ok=True)
    os.chmod(dossier, 0o700)


def fichier_reglages_generes(projet: Path, identite: str) -> Path:
    return dossier_etat(projet) / "reglages" / f"{identite}.json"


def racine_de_l_outil(cible: Path) -> Path:
    """Dossier à rouvrir en lecture pour que `cible` (exécutable déjà résolu) tourne : le
    premier parent qui contient un `pyvenv.cfg` (racine de son environnement), sinon le
    dossier qui le contient. Rien de codé en dur."""
    cible = Path(cible)
    for parent in cible.parents:
        if (parent / "pyvenv.cfg").is_file():
            return parent
    return cible.parent


def dossier_outil() -> Path | None:
    """Dossier de l'outil `cime` à rouvrir en lecture dans le bac à sable (`None` si rien à
    ouvrir). Un environnement dont la racine serait la maison, ou la contiendrait, n'est
    jamais rouvert : ce serait rouvrir toute la maison, `~/.ssh` compris."""
    trouve = shutil.which(NOM)
    if trouve is None:
        trouve = sys.argv[0] if os.sep in sys.argv[0] else sys.executable
    racine = racine_de_l_outil(Path(os.path.realpath(trouve)))
    maison = Path.home().resolve()
    if racine == maison or racine in maison.parents:
        return None
    return racine


def _paquet_cime() -> str:
    """Dossier du paquet `cime` (`cime` est un paquet-espace de noms : pas de `__file__`)."""
    import cime
    return next(iter(cime.__path__))


def dossier_source_cime() -> Path | None:
    """Entrée de `sys.path` d'où `cime` est effectivement importé (`<…>/src` en éditable,
    `…/site-packages` sinon), `realpath`, jamais écrite en dur. `None` si c'est la maison ou un
    parent de la maison : on ne rouvre jamais toute la maison."""
    source = Path(os.path.realpath(_paquet_cime())).parent
    maison = Path.home().resolve()
    if source == maison or source in maison.parents:
        return None
    return source


def _lisible(chemin: Path, allow: list[str], deny: list[str]) -> bool:
    """Le bac à sable laisse-t-il lire `chemin` ? Une entrée de `allowRead` l'emporte sur
    `denyRead` ; hors de l'un et de l'autre, la lecture est libre."""
    chemin = Path(chemin)
    if any(chemin.is_relative_to(a) for a in allow):
        return True
    return not any(chemin.is_relative_to(d) for d in deny)


def import_cime_non_lisible(sandbox: dict, paquet_cime: Path, chemins: list[str]) -> list[Path]:
    """Fonction pure : les dossiers que `cime` doit lire pour s'importer sans que les lectures
    du bac à sable `sandbox` (bloc `sandbox` généré) les couvrent. `paquet_cime` est le
    dossier du paquet `cime` (`cime.__path__`) ; `chemins`, le `sys.path` de l'interpréteur de l'outil (les entrées
    inexistantes sont ignorées). Liste vide : l'import passe."""
    lectures = sandbox.get("filesystem", {})
    allow = [str(a) for a in lectures.get("allowRead", [])]
    deny = [str(d) for d in lectures.get("denyRead", [])]
    manquants = []
    for chemin in [Path(paquet_cime).parent, *(Path(c) for c in chemins if c)]:
        if chemin.exists() and not _lisible(chemin, allow, deny) and chemin not in manquants:
            manquants.append(chemin)
    return manquants


def sonder_import_cime(python: str) -> tuple[Path, list[str]]:
    """(dossier du paquet `cime`, `sys.path`) vus par `python -I` : l'interpréteur de l'outil. `Refus` si
    `cime` ne s'y importe pas du tout."""
    try:
        r = subprocess.run(
            [python, "-I", "-c",
             "import json, sys, cime; print(json.dumps([list(cime.__path__)[0], sys.path]))"],
            capture_output=True, text=True, timeout=30)
        fichier, chemins = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 else (None, None)
    except (OSError, subprocess.SubprocessError, ValueError, IndexError) as e:
        raise Refus(f"autotest : `{python} -c 'import cime'` n'a pas pu s'exécuter ({e}) ; "
                    "vérifie l'installation `uv tool`") from e
    if fichier is None:
        raise Refus(f"autotest : cime ne s'importe pas avec {python} : "
                    f"{r.stderr.strip().splitlines()[-1] if r.stderr.strip() else r.returncode} ; "
                    "vérifie l'installation `uv tool`")
    return Path(os.path.realpath(fichier)), chemins


def verifier_import_cime(sandbox: dict, paquet_cime: Path, chemins: list[str]) -> None:
    """Refuse (`Refus`, code 2) si `cime` ne peut pas s'importer sous les lectures `sandbox`.
    Le message dit quoi faire."""
    manquants = import_cime_non_lisible(sandbox, paquet_cime, chemins)
    if manquants:
        liste = ", ".join(f"`{m}`" for m in manquants)
        raise Refus(f"la source de cime {liste} n'est pas couverte par les lectures de "
                    "l'agent (allowRead) : `cime reprise` y échouerait avec ModuleNotFoundError "
                    "et l'agent serait muet ; vérifie l'installation `uv tool`")


def python_de_l_outil() -> str:
    """Interpréteur de l'environnement de `cime` : `<racine>/bin/python`, à défaut celui-ci."""
    racine = dossier_outil()
    candidat = racine / "bin" / "python" if racine is not None else None
    return str(candidat) if candidat is not None and candidat.exists() else sys.executable


def construire_reglages(statique: dict, projet: Path, identite: str, sites: list[str],
                        home: Path, uid: int, zones_ecriture: list[Path],
                        outil: Path | None = None, regles_allow: list[str] | None = None,
                        regles_deny: tuple[str, ...] = (), source: Path | None = None) -> dict:
    """Contenu du fichier généré au lancement (fonction pure). Les clés du fichier statique
    passent telles quelles, sauf `sandbox` et `autoMemoryDirectory`, qui sont remplacés.
    L'Assistant ne tourne pas dans le bac à sable : pas de `sandbox`."""
    memoire = str(dossier_memoire(projet) / identite)
    if identite == "assistant":
        return {k: v for k, v in statique.items() if k != "sandbox"} | {
            "autoMemoryDirectory": memoire}
    contenu = {**statique,
               **bac_a_sable(projet, sites, home, uid, zones_ecriture, outil, source),
               "autoMemoryDirectory": memoire}
    if regles_allow:  # ex. le droit de commit d'un coordinateur dans le worktree de son équipe
        permissions = copy.deepcopy(contenu.get("permissions") or {})
        permissions["allow"] = [*permissions.get("allow", []),
                                *(r for r in regles_allow if r not in permissions.get("allow", []))]
        contenu["permissions"] = permissions
    if regles_deny:  # ex. la session d'intégration ne commite ni ne fusionne jamais
        permissions = copy.deepcopy(contenu.get("permissions") or {})
        permissions["deny"] = [*permissions.get("deny", []),
                               *(r for r in regles_deny if r not in permissions.get("deny", []))]
        contenu["permissions"] = permissions
    return contenu


def zones_du_bac_a_sable(projet: Path, identite: str, integration: bool = False) -> list[Path]:
    """Où l'agent peut écrire : celles de sa garde ; le projet entier si la garde ne le
    limite pas ; et `.orga/etat/essais` pour une session d'intégration."""
    zones = zones_ecriture_projet(projet, identite)
    zones = [projet] if zones is None else zones
    return [*zones, dossier_essais(projet)] if integration else zones


def contenu_reglages_generes(projet: Path, identite: str, role: str, manifeste: Manifeste,
                             integration: bool = False) -> dict:
    """Ce que `ecrire_reglages_generes` écrit, sans rien écrire."""
    projet = Path(projet).resolve()
    statique = json.loads(fichier_reglages_statique(projet, role).read_text(encoding="utf-8"))
    regles = []
    if role == "coord" and identite.startswith("coord-"):
        regles = regles_commit_equipe(worktree_equipe(projet, manifeste, identite[len("coord-"):]))
    contenu = construire_reglages(statique, projet, identite, manifeste.sites,
                                  Path.home().resolve(), os.getuid(),
                                  zones_du_bac_a_sable(projet, identite, integration),
                                  dossier_outil(), regles,
                                  INTERDITS_INTEGRATION if integration else (),
                                  dossier_source_cime())
    return contenu


def ecrire_reglages_generes(projet: Path, identite: str, role: str, manifeste: Manifeste,
                            integration: bool = False, contenu: dict | None = None) -> Path:
    """Écrit `<projet>/.orga/etat/reglages/<identité>.json` et crée les dossiers de travail."""
    projet = Path(projet).resolve()
    if contenu is None:
        contenu = contenu_reglages_generes(projet, identite, role, manifeste, integration)
    preparer_tmp(projet)
    (dossier_memoire(projet) / identite).mkdir(parents=True, exist_ok=True)
    fichier = fichier_reglages_generes(projet, identite)
    fichier.parent.mkdir(parents=True, exist_ok=True)
    fichier.write_text(json.dumps(contenu, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    return fichier
