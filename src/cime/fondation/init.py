"""`init` : installe dans un projet l'entreprise d'agents (gabarits, registre, réglages)."""
import importlib.metadata
import importlib.resources
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from cime.fondation import lancer, registre
from cime.fondation.nom import NOM, VAR_AGENT, VAR_PROJET
from cime.fondation.reglages import (
    dossier_essais, dossier_memoire, dossier_tmp, fusionner, preparer_tmp, reglages,
)

BRANCHE_REFERENCE = "main"
MODELE = "claude-opus-5-5"
# Ignorés par git : l'état du projet, et les worktrees d'équipe (dans le projet).
LIGNES_GITIGNORE = (".orga/etat/", ".orga/worktrees/")
DOSSIERS_EQUIPE = ("tasks/todo", "tasks/in-progress", "tasks/done", "reports",
                   "conversations")
_VARIABLE = re.compile(r"\{\{([a-z_]+)\}\}")
_PREFIXE = re.compile(r"[a-z0-9-]+")
OPTION_SANS_CIME = "hooks-sans-cime"
_REGLAGES = {"settings.json": "commun", "settings-agent.json": "agent",
             "settings-coordinateur.json": "coordinateur"}


class ErreurInit(Exception):
    pass


def prefixe_par_defaut(nom_dossier: str) -> str:
    mots = [m for m in re.split(r"[-_\s]+", nom_dossier) if m]
    return "".join(m[0] for m in mots).lower()


def _version() -> str:
    try:
        return importlib.metadata.version(NOM)
    except importlib.metadata.PackageNotFoundError:
        return "0.0.0"


def _variables(args, dossier: Path) -> dict[str, str]:
    prefixe = args.prefixe or prefixe_par_defaut(dossier.name)
    if not _PREFIXE.fullmatch(prefixe):
        raise ErreurInit(f"préfixe invalide : {prefixe!r} (attendu : [a-z0-9-]+)")
    return {
        "utilisateur": getattr(args, "utilisateur", None) or "",
        "nom_projet": args.nom_projet or dossier.name,
        "prefixe": prefixe,
        "branche_reference": BRANCHE_REFERENCE,
        "commande": NOM,
        "var_agent": VAR_AGENT,
        "var_projet": VAR_PROJET,
        "date": date.today().isoformat(),
        "modele_assistant": MODELE,
        "modele_coordinateur": MODELE,
        "version_socle": _version(),
    }


def _remplacer(texte: str, variables: dict[str, str], source: str) -> str:
    def un(m):
        if m.group(1) not in variables:
            raise ErreurInit(f"variable inconnue {{{{{m.group(1)}}}}} dans le gabarit {source}")
        return variables[m.group(1)]
    return _VARIABLE.sub(un, texte)


def _gabarits(racine=None, relatif: Path = Path()):
    racine = racine or importlib.resources.files("cime") / "gabarits"
    for entree in sorted(racine.iterdir(), key=lambda e: e.name):
        chemin = relatif / entree.name
        if entree.name == "__pycache__":
            continue
        if entree.is_dir():
            yield from _gabarits(entree, chemin)
        elif chemin != Path("VARIABLES.md"):
            yield chemin, entree


def _racine_git(dossier: Path) -> Path | None:
    """Racine du dépôt git que `dossier` voit (le dossier lui-même ou un dépôt parent), sinon None."""
    r = subprocess.run(["git", "-C", str(dossier), "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True)
    return Path(r.stdout.strip()).resolve() if r.returncode == 0 and r.stdout.strip() else None


def executable_cime() -> str | None:
    """Chemin absolu de l'exécutable `cime` que le PATH de l'appelant désigne, sinon None.

    Sous `uv run`, c'est celui du venv : il existe vraiment, c'est ce qui compte (le PATH
    d'une session tmux, lui, vient du serveur tmux et peut ne pas contenir `cime`)."""
    trouve = shutil.which(NOM)
    return os.path.abspath(trouve) if trouve else None


def _plan_reglages(plan: "Plan", nom: str, role: str) -> None:
    """Décide, sans écrire, ce que `init` fait de `.claude/<nom>` : l'écrire, le compléter, le laisser."""
    projet = plan.dossier
    fichier = projet / ".claude" / nom
    voulu = reglages(projet, BRANCHE_REFERENCE, role, plan.executable)
    relatif = fichier.relative_to(projet)
    rapport = plan.rapport
    if not fichier.exists():
        plan.ecritures_reglages.append(
            (fichier, json.dumps(voulu, indent=2, ensure_ascii=False) + "\n"))
        rapport["ajouté"].append(str(relatif))
        return
    try:
        existant = json.loads(fichier.read_text())
    except json.JSONDecodeError as e:
        raise ErreurInit(f"{relatif} existe mais n'est pas du JSON valide : {e}") from None
    fusion, ajouts = fusionner(existant, voulu)
    perso = _regles_de_l_utilisateur(existant, voulu)
    if perso:
        plan.garde_en_plus.append(f"{relatif} ({perso} règle(s) de l'utilisateur conservée(s))")
    if not ajouts:
        rapport["déjà présent"].append(str(relatif))
        return
    plan.ecritures_reglages.append(
        (fichier, json.dumps(fusion, indent=2, ensure_ascii=False) + "\n"))
    rapport["complété"].append(f"{relatif} (+{len(ajouts)})")
    rapport["complété"].extend(f"  {a}" for a in ajouts)


def _regles_de_l_utilisateur(existant: dict, voulu: dict) -> int:
    """Nombre de règles de permission du fichier existant que `init` n'aurait pas générées."""
    total = 0
    for liste in ("allow", "deny", "ask"):
        generees = set(voulu.get("permissions", {}).get(liste, []))
        total += sum(1 for r in existant.get("permissions", {}).get(liste, []) if r not in generees)
    return total


def _regles_agent_seules(projet: Path) -> set[str]:
    """Interdits du rôle `agent` qui ne sont pas du rôle `commun` : réservés aux agents
    d'équipe, l'Assistant ne doit pas les avoir."""
    agent = reglages(projet, BRANCHE_REFERENCE, "agent")["permissions"]["deny"]
    commun = reglages(projet, BRANCHE_REFERENCE, "commun")["permissions"]["deny"]
    return set(agent) - set(commun)


def _lire_settings(projet: Path) -> dict:
    fichier = projet / ".claude" / "settings.json"
    try:
        return json.loads(fichier.read_text())
    except json.JSONDecodeError as e:
        raise ErreurInit(f"{fichier.relative_to(projet)} existe mais n'est pas du JSON valide : "
                         f"{e}") from None


# Autorisations d'un `init` d'avant le registre : tmux est fermé à tous les agents par la garde.
AUTORISATIONS_PERIMEES = ("Bash(tmux *)",)


def _migrer(projet: Path, rapport: dict) -> None:
    """Retire de settings.json les interdits réservés aux agents d'équipe, posés par un
    `init` d'avant la répartition par rôle, et les autorisations périmées (`Bash(tmux *)`).
    Seule une règle égale, caractère pour caractère, à une règle générée part : le reste du
    fichier reste tel quel, ordre compris."""
    voulues = _regles_agent_seules(projet)
    donnees = _lire_settings(projet)
    permissions = donnees.get("permissions", {})
    deny = permissions.get("deny", [])
    allow = permissions.get("allow", [])
    retirees = [r for r in deny if r in voulues]
    perimees = [r for r in allow if r in AUTORISATIONS_PERIMEES]
    if not retirees and not perimees:
        rapport["migration"].append("rien à migrer")
        return
    if retirees:
        permissions["deny"] = [r for r in deny if r not in voulues]
    if perimees:
        permissions["allow"] = [r for r in allow if r not in AUTORISATIONS_PERIMEES]
    (projet / ".claude" / "settings.json").write_text(
        json.dumps(donnees, indent=2, ensure_ascii=False) + "\n")
    rapport["migration"].extend(f"retiré : permissions.deny : {r}" for r in retirees)
    rapport["migration"].extend(f"retiré : permissions.allow : {r}" for r in perimees)


def _plan_gitignore(plan: "Plan") -> None:
    fichier = plan.dossier / ".gitignore"
    contenu = fichier.read_text() if fichier.exists() else ""
    presentes = {ligne.strip() for ligne in contenu.splitlines()}
    manquantes = []
    for ligne in LIGNES_GITIGNORE:
        if ligne in presentes:
            plan.rapport["déjà présent"].append(f".gitignore ({ligne})")
        else:
            manquantes.append(ligne)
    if not manquantes:
        return
    sep = "" if not contenu or contenu.endswith("\n") else "\n"
    plan.ajout_gitignore = sep + "".join(f"{ligne}\n" for ligne in manquantes)
    plan.rapport["complété" if contenu else "ajouté"].extend(
        f".gitignore ({ligne})" for ligne in manquantes)


def _migrer_registre(projet: Path, rapport: dict) -> None:
    """Migre un registre ancien : messages antérieurs clos, questions sans réponse listées."""
    from cime.signaux import migration
    stats = migration.migrer(projet)
    rapport["migration"].append(
        f"registre : {stats['clos']} messages clos, {stats['clos_par_fichier']} clos par "
        f"fichier de réponse, {stats['ouvertes']} questions restées ouvertes")


@dataclass
class Plan:
    """Ce que `init` ferait, calculé sans rien écrire. `installer` l'exécute, `--apercu` le rend."""
    dossier: Path
    nom: str
    executable: str | None
    git_init: bool = False
    rapport: dict[str, list[str]] = field(default_factory=lambda: {
        "ajouté": [], "déjà présent": [], "complété": [], "migration": [], "avertissements": []})
    gabarits: list[tuple[Path, str]] = field(default_factory=list)    # (chemin relatif, texte)
    ajout_gitignore: str = ""
    ecritures_reglages: list[tuple[Path, str]] = field(default_factory=list)
    garde_en_plus: list[str] = field(default_factory=list)            # laissé tel quel, hors rapport

    @property
    def garde(self) -> list[str]:
        return [*self.rapport["déjà présent"], *self.garde_en_plus]


def _premier_existant(chemin: Path) -> Path:
    while not chemin.exists() and chemin != chemin.parent:
        chemin = chemin.parent
    return chemin


def planifier(args, executable: str | None) -> Plan:
    """Calcule le plan de `init` sur `args.dossier` : aucune écriture, aucun effet de bord
    (le dossier peut ne pas exister). L'ordre des lignes du rapport est celui de `init`."""
    dossier = Path(args.dossier).expanduser().resolve()
    variables = _variables(args, dossier)
    plan = Plan(dossier=dossier, nom=variables["nom_projet"], executable=executable)
    rapport = plan.rapport
    # Le dépôt que `init` verrait une fois le dossier créé : celui du premier ancêtre existant.
    racine_git = _racine_git(_premier_existant(dossier))
    if racine_git != dossier:
        plan.git_init = True
        if racine_git is None:
            rapport["ajouté"].append(f".git (branche {BRANCHE_REFERENCE})")
        else:
            rapport["ajouté"].append(
                f".git (dépôt propre : le dossier est dans le dépôt {racine_git})")
    for relatif, source in _gabarits():
        if (dossier / relatif).exists():
            rapport["déjà présent"].append(str(relatif))
            continue
        plan.gabarits.append(
            (relatif, _remplacer(source.read_text(encoding="utf-8"), variables, str(relatif))))
        rapport["ajouté"].append(str(relatif))
    _plan_gitignore(plan)
    for chemin, libelle in ((dossier / ".orga" / "etat" / "registre.sqlite", None),
                            (dossier_tmp(dossier), ".orga/etat/tmp (0o700)"),
                            (dossier_memoire(dossier), ".orga/etat/memoire"),
                            (dossier_essais(dossier), ".orga/etat/essais"),
                            (dossier / ".orga" / "worktrees", ".orga/worktrees")):
        existe = chemin.exists() if libelle is None else chemin.is_dir()
        rapport["déjà présent" if existe else "ajouté"].append(
            libelle or ".orga/etat/registre.sqlite")
    for nom, role in _REGLAGES.items():
        _plan_reglages(plan, nom, role)
    return plan


def installer(args) -> dict[str, list[str]]:
    executable = executable_cime()
    if executable is None and not getattr(args, "hooks_sans_cime", False):
        raise ErreurInit(
            f"la commande {NOM} est introuvable sur le PATH : les hooks de .claude/ ne "
            f"la trouveraient pas et ne s'exécuteraient pas (Claude Code laisse alors passer "
            f"les commandes, garde comprise) ; rien n'a été écrit. Installe-la "
            f"(uv tool install --editable <dépôt de l'application>) puis relance ; "
            f"ou écris les hooks quand même, à tes risques : --{OPTION_SANS_CIME}")
    plan = planifier(args, executable)
    dossier, rapport = plan.dossier, plan.rapport
    dossier.mkdir(parents=True, exist_ok=True)
    if plan.git_init:
        r = subprocess.run(["git", "init", "-b", BRANCHE_REFERENCE, str(dossier)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise ErreurInit(f"git init a échoué : {r.stderr.strip()}")
    for relatif, texte in plan.gabarits:
        cible = dossier / relatif
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_text(texte, encoding="utf-8")
    # Dossiers d'équipe manquants : seulement ceux que les gabarits prévoient pour cette équipe.
    for relatif, _ in _gabarits():
        p = relatif.parts
        if len(p) > 3 and p[:2] == (".orga", "teams"):
            for sous in DOSSIERS_EQUIPE:
                if "/".join(p[3:]).startswith(sous + "/"):
                    (dossier / ".orga" / "teams" / p[2] / sous).mkdir(parents=True, exist_ok=True)
    if plan.ajout_gitignore:
        with open(dossier / ".gitignore", "a") as f:
            f.write(plan.ajout_gitignore)
    if getattr(args, "migrer", False):
        from cime.signaux import migration
        if migration.sauvegarder(dossier):  # avant que `ouvrir` ne touche à la base
            rapport["migration"].append(
                f"sauvegarde du registre : .orga/etat/{migration.SAUVEGARDE}")
    registre.ouvrir(dossier).close()
    preparer_tmp(dossier)
    dossier_memoire(dossier).mkdir(parents=True, exist_ok=True)
    dossier_essais(dossier).mkdir(parents=True, exist_ok=True)
    (dossier / ".orga" / "worktrees").mkdir(parents=True, exist_ok=True)
    for fichier, texte in plan.ecritures_reglages:
        fichier.parent.mkdir(parents=True, exist_ok=True)
        fichier.write_text(texte)
    if getattr(args, "migrer", False):
        _migrer(dossier, rapport)
        _migrer_registre(dossier, rapport)
    deny = _lire_settings(dossier).get("permissions", {}).get("deny", [])
    if any(r in _regles_agent_seules(dossier) for r in deny):
        rapport["avertissements"].append(
            f"règles à migrer : lance `{NOM} init --migrer`")
    if executable is None:
        rapport["avertissements"].append(
            f"hooks écrits avec le nom nu `{NOM}` (--{OPTION_SANS_CIME}) : sans `{NOM}` "
            "sur le PATH de la session, ils sortent en 127 et Claude Code laisse passer "
            "les commandes, garde comprise")
    elif ".venv" in Path(executable).parts:
        rapport["avertissements"].append(
            f"hooks pointés sur {executable}, dans un venv local qui disparaît avec lui : "
            f"préfère `uv tool install --editable <dépôt de l'application>`")
    return rapport


def apercu(args) -> dict:
    """Ce que `init` ferait, sans rien écrire (`cime init --apercu`). `commit` : `init` ne fait
    aucun commit (`git init` seul, jamais `git commit`), donc faux."""
    plan = planifier(args, executable_cime())
    return {"nom": plan.nom, "commit": False, "cree": list(plan.rapport["ajouté"]),
            "complete": [c for c in plan.rapport["complété"] if not c.startswith("  ")],
            "garde": plan.garde}


def _executer_apercu(args) -> int:
    for option in ("lancer", "migrer"):
        if getattr(args, option, False):
            print(f"{NOM} init : --apercu n'écrit rien, il ne se combine pas avec --{option}",
                  file=sys.stderr)
            return 2
    try:
        donnees = apercu(args)
    except ErreurInit as e:
        print(f"{NOM} init : {e}", file=sys.stderr)
        return 2
    if getattr(args, "sortie_json", False):
        print(json.dumps(donnees, ensure_ascii=False))
        return 0
    print(f"Projet « {donnees['nom']} » — aperçu de `{NOM} init` (rien n'est écrit, aucun commit) :")
    for titre, cle in (("créerait", "cree"), ("compléterait", "complete"),
                       ("garderait tel quel", "garde")):
        print(f"{titre} :" + ("" if donnees[cle] else " rien"))
        for ligne in donnees[cle]:
            print(f"  {ligne}")
    return 0


def _suite(racine: Path, lancement: tuple[str, int] | None) -> None:
    print("\nSuite :")
    if lancement is None:
        print(f"  1. ouvre une fois le projet dans Claude Code pour approuver le dossier "
              f"(aucun agent ne répond à cet écran) : cd {racine} && claude")
        print(f"  2. puis : cd {racine} && {NOM} lancer assistant")
        print(f"  (ou, en une fois : {NOM} init {racine} --utilisateur <nom> --lancer)")
        return
    session, code = lancement
    if code == lancer.CODE_APPROBATION:
        print(f"  l'Assistant ({session}) attend que tu approuves le dossier, toi seul : "
              f"tmux attach -t {session}")
        print("  réponds à l'écran (« Yes, I trust this folder »), puis il commence ses questions.")
    elif code == 0:
        print(f"  l'Assistant est lancé : tmux attach -t {session}")
    else:
        print(f"  le lancement de l'Assistant a échoué (code {code}) : voir le message ci-dessus ; "
              f"le projet est installé, tu peux relancer : cd {racine} && {NOM} lancer assistant")


def executer(args) -> int:
    if getattr(args, "apercu", False):
        return _executer_apercu(args)
    if not getattr(args, "utilisateur", None):
        print(f"{NOM} init : --utilisateur est requis (sauf avec --apercu)", file=sys.stderr)
        return 2
    try:
        rapport = installer(args)
    except ErreurInit as e:
        print(f"{NOM} init : {e}", file=sys.stderr)
        return 2
    for titre, lignes in rapport.items():
        if lignes:
            print(f"{titre} :")
            for ligne in lignes:
                print(ligne if ligne.startswith("  ") else f"  {ligne}")
    racine = Path(args.dossier).expanduser().resolve()
    lancement = None
    if getattr(args, "lancer", False):
        lancement = lancer.lancer_assistant(racine, getattr(args, "modele", None))
    _suite(racine, lancement)
    return 0 if lancement is None else lancement[1]
