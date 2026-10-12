"""Classement d'une demande d'autorisation.

`classer_autorisation` dit, avant que le hook `PermissionRequest` n'écrive le signalement, qui
peut l'accorder : `reserve` (l'utilisateur seul), `autonome` (l'utilisateur, ou l'Assistant en mode autonome
actif), `libre` (la chaîne coordinateur → Assistant). Elle ne juge ni la philosophie ni
l'architecture : elle borne la portée. Fonction pure : elle lit le manifeste et le système de
fichiers (`realpath`), n'écrit rien et ne lève jamais — toute erreur vaut `reserve`.

**Dans le doute, réservé** : une commande se juge sous-commande par sous-commande et la classe la
plus fermée l'emporte (`reserve` > `autonome` > `libre`). Les verbes et motifs sont des données
(tables ci-dessous), un test par ligne.
"""
import os
import re
import shlex
from pathlib import Path

from cime.fondation.fusions_auto import est_reserve
from cime.fondation.projet import lire_manifeste, worktree_equipe

LIBRE, AUTONOME, RESERVE = "libre", "autonome", "reserve"
RANG = {LIBRE: 0, AUTONOME: 1, RESERVE: 2}

# --- les tables ------------------------------------------------------------------------------

# Ce que le classement ne voit pas, à dessein (à ne changer que sciemment) : un
# interpréteur lancé sur du code — `python script.py`, `python -c …`, `bash script.sh`, `node x.js` —
# reste `libre`. Son contenu est opaque ; le bac à sable et la garde le bornent, pas le classement.
# `test_interpreteur_opaque_reste_libre` l'acte : le changer est une décision, pas un accident.

OUTILS_ECRITURE = ("Edit", "Write", "MultiEdit", "NotebookEdit")
OUTILS_LECTURE = ("Read", "Glob", "Grep")
OUTILS_WEB = ("WebFetch", "WebSearch")
OUTIL_SHELL = "Bash"

# Noyau « machine » : chemins jugés relativement à la racine du dépôt ou du worktree où ils sont.
# Ni `socle`, ni `produit`, ni `CLAUDE.md` : l'écriture dans un worktree est libre, c'est la
# fusion qui les réserve.
NOYAU_MACHINE: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("droits", (".claude/", ".orga/etat/", ".git/", ".orga/projet.toml")),
    ("secrets", (".env", ".env.*", "*.pem", "*.key", "id_rsa*", "id_ed25519*", ".netrc",
                 "credentials*")),
)
# La lecture (Read/Glob/Grep) n'est réservée que pour les secrets (et hors projet).
THEMES_LECTURE = ("secrets",)

# Fichiers hors projet qu'une commande peut nommer sans rien atteindre.
CHEMINS_NEUTRES = ("/dev/null", "/dev/stdout", "/dev/stderr", "/dev/stdin", "/dev/tty")

VERBES_SYSTEME = ("sudo", "su", "chmod", "chown", "launchctl", "defaults", "osascript", "open",
                  "kill", "pkill", "killall", "security", "diskutil", "networksetup", "pmset",
                  "crontab",
                  # gestionnaires de paquets et services du système
                  "brew", "port", "apt", "apt-get", "aptitude", "yum", "dnf", "dpkg", "rpm", "zypper",
                  "pacman", "apk", "snap", "flatpak", "nix", "nix-env", "softwareupdate", "mas",
                  "systemctl", "service", "corepack",
                  # conteneurs et machines virtuelles
                  "docker", "docker-compose", "podman", "podman-compose", "buildah", "nerdctl",
                  "colima", "limactl", "kubectl",
                  # réglages de la machine
                  "scutil", "dscl", "sysctl", "shutdown", "reboot", "halt", "hdiutil", "tmutil",
                  "spctl", "csrutil", "mount", "umount", "visudo", "passwd")

# Sous-commandes réservées : (verbe, sous-commandes dans l'ordre, premier mot qui la libère — une
# lecture —, thème). Cherchées parmi les mots comme les dépendances : un paquet qui porte le nom
# d'une sous-commande (`npm install config`) est un faux positif, dans le sens sûr.
SOUS_COMMANDES_RESERVEES: tuple[tuple[str, tuple[str, ...], tuple[str, ...], str], ...] = (
    ("npm", ("config",), ("get", "list", "ls"), "systeme"),
    ("npm", ("set",), (), "systeme"),
    ("pnpm", ("config",), ("get", "list"), "systeme"),
    ("yarn", ("config",), ("get", "list"), "systeme"),
    ("pip", ("config",), ("get", "list", "debug"), "systeme"),
    ("pip3", ("config",), ("get", "list", "debug"), "systeme"),
    ("python", ("-m", "pip", "config"), ("get", "list", "debug"), "systeme"),
    ("python3", ("-m", "pip", "config"), ("get", "list", "debug"), "systeme"),
    ("uv", ("tool", "uninstall"), (), "systeme"),
    ("pipx", ("uninstall",), (), "systeme"),
    ("pipx", ("uninstall-all",), (), "systeme"),
    ("npm", ("link",), (), "hors_projet"),
    ("npm", ("unlink",), (), "hors_projet"),
    # installés hors du projet par nature (`~/.cargo/bin`, `$GOPATH/bin`, paquets globaux de yarn)
    ("cargo", ("install",), (), "hors_projet"),
    ("go", ("install",), (), "hors_projet"),
    ("yarn", ("global",), (), "hors_projet"),
    # publier un paquet : ce qui sort du dépôt, comme `git push`
    ("npm", ("publish",), (), "push"), ("pnpm", ("publish",), (), "push"),
    ("yarn", ("publish",), (), "push"), ("cargo", ("publish",), (), "push"),
    ("uv", ("publish",), (), "push"), ("twine", ("upload",), (), "push"),
    ("npm", ("login",), (), "push"), ("npm", ("adduser",), (), "push"),
    ("npm", ("token",), (), "push"), ("cargo", ("login",), (), "push"),
)

# git : (sous-commande, options qui la réservent — None = toujours —, options qui la laissent
# libre, thème)
GIT_RESERVE: tuple[tuple[str, tuple[str, ...] | None, tuple[str, ...], str], ...] = (
    ("push", None, (), "push"),
    ("remote", None, (), "push"),
    ("config", None, ("--get", "--get-all", "--get-regexp", "--list", "-l"), "push"),
    ("branch", ("-d", "-D", "-m", "-M", "--delete", "--move"), (), "branches"),
    ("reset", ("--hard",), (), "branches"),
    ("clean", ("-f", "--force"), (), "branches"),   # `-f` aussi groupé : `-fd`, `-xdf`
)
GIT_RESEAU = ("clone", "fetch", "pull", "ls-remote")
# Sous-commandes de sous-commandes qui vont chercher du réseau : jugées comme `fetch` (un hôte
# écrit hors `sites`, ou aucun hôte écrit ⇒ réservé). `submodule foreach` lance une commande : jugée.
GIT_RESEAU_SOUS_COMMANDES = (("submodule", ("add", "update", "init", "sync")),
                             ("subtree", ("add", "pull", "push")))
# Options globales de git qui prennent une valeur au mot suivant
GIT_OPTIONS_VALEUR = ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path")

# Commandes réseau ; pour chacune, les options qui prennent une valeur au mot suivant, et si
# seul le premier positionnel est un hôte (ssh, nc, ftp : la suite est une commande ou un port).
RESEAU: tuple[tuple[str, tuple[str, ...], bool], ...] = (
    ("curl", ("-o", "--output", "-H", "--header", "-d", "--data", "--data-raw",
              "--data-binary", "-X", "--request", "-u", "--user", "-A", "--user-agent",
              "-e", "--referer", "-w", "--write-out", "-T", "--upload-file", "-F", "--form",
              "-b", "--cookie", "-c", "--cookie-jar", "-m", "--max-time", "-x", "--proxy",
              "--connect-timeout", "-r", "--range", "-K", "--config"), False),
    ("wget", ("-O", "--output-document", "-o", "--output-file", "-P", "--directory-prefix",
              "--header", "-U", "--user-agent", "-t", "--tries", "-T", "--timeout"), False),
    ("ssh", ("-i", "-p", "-l", "-o", "-F", "-L", "-R", "-D", "-J", "-W", "-b", "-c", "-E",
             "-m", "-O", "-Q", "-S", "-w"), True),
    ("scp", ("-i", "-P", "-o", "-F", "-c", "-l", "-S", "-J"), False),
    ("rsync", ("-e", "--rsh", "--exclude", "--include", "--filter", "-f"), False),
    ("nc", ("-p", "-s", "-w", "-X", "-x", "-I", "-O", "-T"), True),
    ("ftp", ("-P",), True),
)

# Ajout d'une dépendance, ou récupération et exécution d'un paquet distant (`npx`, `uvx`…) :
# (verbe, sous-commandes attendues dans l'ordre parmi les mots ; () = le verbe seul).
DEPENDANCES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("uv", ("add",)), ("uv", ("sync",)), ("uv", ("pip", "install")),
    ("pip", ("install",)), ("pip3", ("install",)),
    ("python", ("-m", "pip", "install")), ("python3", ("-m", "pip", "install")),
    ("npm", ("add",)), ("npm", ("install",)), ("npm", ("i",)), ("npm", ("ci",)),
    ("pnpm", ("add",)), ("pnpm", ("install",)), ("pnpm", ("i",)),
    ("yarn", ("add",)), ("yarn", ("install",)),
    ("cargo", ("add",)), ("go", ("get",)),
    # paquets distants récupérés puis exécutés ou téléchargés
    ("npx", ()), ("uvx", ()), ("bunx", ()), ("pnpm", ("dlx",)), ("yarn", ("dlx",)),
    ("npm", ("exec",)), ("pipx", ("install",)), ("pipx", ("run",)),
    ("uv", ("tool", "install")), ("uv", ("tool", "run")),
    ("pip", ("download",)), ("pip3", ("download",)),
    ("python", ("-m", "pip", "download")), ("python3", ("-m", "pip", "download")),
    # équivalents qui vont chercher du réseau
    ("pipx", ("upgrade",)), ("pipx", ("upgrade-all",)), ("pipx", ("inject",)),
    ("uv", ("tool", "upgrade")), ("uv", ("lock",)), ("uv", ("pip", "sync")),
    ("npm", ("update",)), ("pnpm", ("update",)), ("yarn", ("upgrade",)),
    ("bun", ("add",)), ("bun", ("install",)), ("bun", ("i",)),
    ("cargo", ("fetch",)), ("cargo", ("update",)), ("go", ("mod", "download")),
    ("go", ("mod", "tidy")),
)
# Une commande de dépendance avec l'une d'elles s'installe hors du projet ⇒ réservé. (`--target`,
# `--prefix`, `--root` : leur valeur est jugée comme un chemin, comme tout mot de la commande.)
OPTIONS_HORS_PROJET = ("-g", "--global", "--system", "--user", "--break-system-packages",
                       "--location=global")
GESTIONNAIRES_JS = ("npm", "pnpm", "yarn", "bun")   # `-gD` : options groupées, le `g` y est
# Verbe lancé avec des paquets apportés par option : (verbe, sous-commande, options qui apportent
# des paquets, options qui coupent le réseau — alors rien n'est récupéré). Jugé sur les options
# qui précèdent la commande lancée.
PAQUETS_PAR_OPTION = (
    ("uv", "run", ("--with", "--with-editable", "--with-requirements"), ("--offline", "--no-index")),
)
# Options qui désignent une source explicite (index, dépôt) : son hôte doit être un site permis.
OPTIONS_SOURCE = ("--index-url", "--extra-index-url", "-i", "--index", "--default-index",
                  "--find-links", "-f", "--registry", "--git", "--source")

# Évaluation d'un texte comme commande : illisible si le texte n'est pas donné en clair.
VERBES_ILLISIBLES = ("eval",)
SHELLS = ("sh", "bash", "zsh", "dash", "ksh")
# Préfixes qui lancent la commande qui suit (on juge la commande qui suit)
ENVELOPPES = ("env", "time", "nice", "nohup", "command", "builtin", "exec", "xargs", "timeout",
              "stdbuf", "caffeinate", "watch")
ENVELOPPES_DOUBLES = (("uv", "run"), ("poetry", "run"), ("pipx", "run"), ("pdm", "run"))
# Leurs options qui prennent une valeur au mot suivant (sinon la valeur serait prise pour la
# commande lancée)
ENVELOPPES_OPTIONS_VALEUR = ("--with", "--with-editable", "--with-requirements", "--python", "-p",
                             "--directory", "--project", "--package", "--env-file", "--extra",
                             "--group", "--index", "--index-url", "--extra-index-url",
                             "--find-links", "--script", "--spec", "--config-file", "--cache-dir")

# La boucle locale ne sort pas de la machine (et le bac à sable autorise `allowLocalBinding`) :
# pour ces commandes et `WebFetch`, ce n'est pas un site hors liste. Hôtes exacts :
# `localhost.evil.com` n'en est pas un.
HOTES_BOUCLE_LOCALE = ("localhost", "127.0.0.1", "::1")
RESEAU_BOUCLE_LOCALE = ("curl", "wget")
# Options qui envoient la requête ailleurs que vers l'hôte écrit : la boucle locale ne vaut plus.
OPTIONS_DETOURNANT = ("-x", "--proxy", "--preproxy", "--socks4", "--socks4a", "--socks5",
                      "--socks5-hostname", "--connect-to", "--resolve", "--unix-socket",
                      "--abstract-unix-socket", "-e", "--execute")

_URL = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://(?:[^/@]*@)?(\[[^\]]+\]|[^/:?#]+)")
_SCP = re.compile(r"^(?:[A-Za-z0-9._-]+@)?([A-Za-z0-9.-]+\.[A-Za-z]{2,}|(?i:localhost)):")
_HOTE_NU = re.compile(r"^(?:[A-Za-z0-9._-]+@)?([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+|(?i:localhost))(?::\d+)?(?:/.*)?$")
_VARIABLE = re.compile(r"\$[A-Za-z_{0-9@*#?!$-]")
_AFFECTATION = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\+?=")
_PONCTUATION = set("();<>|&\n")
_BOUCLE_IPV6 = re.compile(r"^(?:\[::1\](?::\d+)?(?:/.*)?|::1)$")


class _Verdict(Exception):
    """Un `reserve` trouvé : rien ne peut le rouvrir."""


def _resultat(classe: str, theme: str, motif: str) -> dict:
    return {"classe": classe, "theme": theme, "motif": motif[:200]}


def _reserve(theme: str, motif: str) -> dict:
    return _resultat(RESERVE, theme, motif)


def plus_fermee(verdicts: list[dict]) -> dict:
    """La classe la plus fermée gagne ; à égalité, le premier verdict."""
    meilleur = None
    for v in verdicts:
        if meilleur is None or RANG[v["classe"]] > RANG[meilleur["classe"]]:
            meilleur = v
    return meilleur or _resultat(LIBRE, "projet", "rien à signaler")


# --- les racines et les chemins ----------------------------------------------------------------

class _Cadre:
    """Ce que le classement lit du projet : les racines (dépôt principal, worktrees d'équipe)
    et les sites permis."""

    def __init__(self, projet: Path):
        self.projet = Path(os.path.realpath(projet))
        m = lire_manifeste(self.projet)
        self.sites = [s.strip().lower() for s in m.sites]
        racines = {self.projet}
        equipes = self.projet / ".orga" / "teams"
        if equipes.is_dir():
            for d in equipes.iterdir():
                if d.is_dir():
                    racines.add(Path(os.path.realpath(worktree_equipe(self.projet, m, d.name))))
        dossier_wt = self.projet / ".orga" / "worktrees"
        if dossier_wt.is_dir():   # un worktree d'équipe sous le dépôt est une racine à part
            for d in dossier_wt.iterdir():
                if d.is_dir():
                    racines.add(Path(os.path.realpath(d)))
        # la plus profonde d'abord : un chemin se juge dans le worktree où il est
        self.racines = sorted(racines, key=lambda p: len(p.parts), reverse=True)

    def site_permis(self, hote: str) -> bool:
        hote = hote.strip("[]").lower().rstrip(".")
        for site in self.sites:
            site = site.split(":")[0]
            if site.startswith("*."):
                if hote.endswith(site[1:]):
                    return True
            elif hote == site:
                return True
        return False


def _themes_noyau(relatif: str, themes=None) -> str | None:
    for theme, motifs in NOYAU_MACHINE:
        if themes is not None and theme not in themes:
            continue
        if relatif and est_reserve(relatif, motifs):
            return theme
    return None


def juger_chemin(cadre: _Cadre, chemin: str, cwd: Path, *, themes=None) -> dict | None:
    """Verdict `reserve` pour un chemin hors projet ou du noyau machine (limité à `themes` s'il
    est donné), None sinon. `realpath` : les liens sont suivis."""
    if chemin in CHEMINS_NEUTRES:
        return None
    if chemin.startswith("~"):
        return _reserve("hors_projet", f"chemin hors du projet : {chemin}")
    absolu = Path(os.path.realpath(os.path.join(cwd, chemin)))
    for racine in cadre.racines:
        if absolu == racine or absolu.is_relative_to(racine):
            relatif = absolu.relative_to(racine).as_posix()
            theme = _themes_noyau("" if relatif == "." else relatif, themes)
            if theme:
                return _reserve(theme, f"{theme} : {chemin}")
            return None
    return _reserve("hors_projet", f"chemin hors du projet : {chemin}")


# --- les outils sans commande -------------------------------------------------------------------

def est_boucle_locale(hote: str) -> bool:
    return hote.strip("[]").lower().rstrip(".") in HOTES_BOUCLE_LOCALE


def _hote_url(url: str) -> str | None:
    m = _URL.match(url or "")
    return m.group(1) if m else None


def _classer_fichier(cadre, outil, entree, cwd) -> dict:
    cles = ("file_path", "notebook_path") if outil in OUTILS_ECRITURE else ("file_path", "path")
    chemins = [entree.get(c) for c in cles if isinstance(entree.get(c), str) and entree.get(c)]
    if outil == "Glob":
        motif = entree.get("pattern")
        if isinstance(motif, str) and (motif.startswith(("/", "~")) or ".." in motif.split("/")):
            chemins.append(motif.split("*")[0] or "/")
    if outil in OUTILS_ECRITURE and not chemins:
        return _reserve("illisible", f"{outil} sans chemin")
    themes = None if outil in OUTILS_ECRITURE else THEMES_LECTURE
    verdicts = [v for v in (juger_chemin(cadre, c, cwd, themes=themes) for c in chemins) if v]
    return plus_fermee(verdicts) if verdicts else _resultat(LIBRE, "projet", f"{outil} dans le projet")


def _classer_web(cadre, outil, entree) -> dict:
    hote = _hote_url(entree.get("url") or "") if outil == "WebFetch" else None
    if hote and est_boucle_locale(hote):
        return _resultat(LIBRE, "projet", f"{outil} vers la boucle locale : {hote}")
    if hote and cadre.site_permis(hote):
        return _resultat(LIBRE, "projet", f"{outil} vers un site permis : {hote}")
    return _reserve("reseau", f"{outil} vers un hôte qui n'est pas un site permis : {hote or '?'}")


# --- Bash ---------------------------------------------------------------------------------------

def _illisible(motif: str) -> dict:
    return _reserve("illisible", f"commande illisible : {motif}")


def _variable_hors_apostrophes(texte: str) -> bool:
    """Un `$NOM`, `${…}`, `$(`… hors guillemets simples : la valeur n'est connue qu'à l'exécution."""
    etat, i = None, 0
    while i < len(texte):
        c = texte[i]
        if c == "\\" and etat != "'":
            i += 2
            continue
        if etat is None and c in "'\"":
            etat = c
        elif etat == c:
            etat = None
        elif etat != "'" and c == "$" and _VARIABLE.match(texte, i):
            return True
        elif etat != "'" and c == "`":
            return True
        i += 1
    return False


def _jetons(texte: str) -> list[str]:
    lex = shlex.shlex(texte, posix=True, punctuation_chars="();<>|&\n")
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    lex.commenters = ""
    return list(lex)


_HEREDOC = re.compile(r"(?<!<)<<(?!<)(-?)\s*(?:'([^']*)'|\"([^\"]*)\"|\\?([A-Za-z_][\w.-]*))")
_FD_REDIRECTION = re.compile(r"(?<![^\s;|&(])\d+(?=[<>])")


def _heredocs(texte: str) -> tuple[str, list[tuple[str, str]]]:
    """Retire les corps de heredoc : (texte restant, [(corps, ligne qui l'ouvre)])."""
    lignes, garde, corps, i = texte.split("\n"), [], [], 0
    while i < len(lignes):
        ligne = lignes[i]
        garde.append(ligne)
        i += 1
        for m in _HEREDOC.finditer(ligne):
            delim = next(g for g in m.groups()[1:] if g is not None)
            for j in range(i, len(lignes)):
                fin = lignes[j].lstrip("\t") if m.group(1) else lignes[j]
                if fin == delim:
                    corps.append(("\n".join(lignes[i:j]), ligne))
                    i = j + 1
                    break
            else:
                raise ValueError("heredoc non fermé")
    return "\n".join(garde), corps


class _Shell:
    def __init__(self, cadre: _Cadre):
        self.cadre = cadre
        self.verdicts: list[dict] = []

    def noter(self, verdict: dict | None) -> None:
        if verdict is None:
            return
        self.verdicts.append(verdict)
        if verdict["classe"] == RESERVE:
            raise _Verdict()

    def analyser(self, texte: str, cwd: Path, prof: int = 0) -> None:
        if prof > 6:
            self.noter(_illisible("imbrication trop profonde"))
        texte = texte.replace("\\\n", " ")
        try:
            texte, corps = _heredocs(texte)
        except ValueError as e:
            self.noter(_illisible(str(e)))
        if "$(" in texte or "<(" in texte or ">(" in texte or _variable_hors_apostrophes(texte):
            self.noter(_illisible("substitution, variable ou backtick"))
        for contenu, ligne in corps:   # un heredoc donné à un shell est une commande
            if re.search(r"(^|[\s|;&(])(ba|z|da|k)?sh(\s|$)", ligne):
                self.analyser(contenu, cwd, prof + 1)
        texte = _FD_REDIRECTION.sub("", texte)
        try:
            jetons = _jetons(texte)
        except ValueError as e:
            self.noter(_illisible(f"guillemets déséquilibrés ({e})"))
        mots: list[str] = []
        pile: list[Path] = []
        i = 0
        while i < len(jetons):
            t = jetons[i]
            if t and set(t) <= _PONCTUATION:
                if "<" in t or ">" in t:
                    if t == "<<<":            # chaîne donnée en entrée : une donnée
                        i += 2
                        continue
                    if t.startswith("<<"):    # heredoc : son délimiteur suit
                        i += 2
                        continue
                    if i + 1 >= len(jetons):
                        self.noter(_illisible("redirection sans cible"))
                    cible = jetons[i + 1]
                    if not (t.endswith("&") and cible.isdigit()) and cible != "-":
                        self.noter(juger_chemin(self.cadre, cible, cwd))
                    i += 2
                    continue
                if mots:
                    cwd = self.commande(mots, cwd, prof)
                    mots = []
                for c in t:
                    if c == "(":
                        pile.append(cwd)
                    elif c == ")" and pile:
                        cwd = pile.pop()
                i += 1
                continue
            mots.append(t)
            i += 1
        if mots:
            self.commande(mots, cwd, prof)

    # -- une commande simple -----------------------------------------------------------------

    def _mots_chemins(self, mots: list[str], cwd: Path) -> None:
        """Chaque mot se juge comme un chemin depuis le dossier courant (après `realpath` : un
        lien qui sort du projet en sort) : hors projet ou noyau machine ⇒ réservé."""
        for mot in mots:
            valeurs = [mot]
            if mot.startswith("-") and "=" in mot:
                valeurs.append(mot.split("=", 1)[1])
            for v in valeurs:
                if not v or v.startswith("-") or _URL.match(v):
                    continue
                self.noter(juger_chemin(self.cadre, v, cwd))

    def commande(self, mots: list[str], cwd: Path, prof: int) -> Path:
        """Juge une commande simple ; renvoie le dossier courant après elle (`cd`)."""
        while mots and (_AFFECTATION.match(mots[0]) or mots[0] in ("!", "{", "}", "if", "then",
                                                                  "else", "elif", "fi", "do",
                                                                  "done", "while", "until")):
            mots = mots[1:]
        if not mots:
            return cwd
        self._mots_chemins(mots, cwd)
        verbe = os.path.basename(mots[0])
        args = mots[1:]
        if verbe == "cd":
            cibles = [a for a in args if not a.startswith("-")]
            if not cibles or cibles[0] == "-":
                self.noter(_reserve("hors_projet", "cd hors du projet (dossier personnel ou précédent)"))
            nouveau = Path(os.path.realpath(os.path.join(cwd, cibles[0])))
            self.noter(juger_chemin(self.cadre, cibles[0], cwd))
            return nouveau
        if verbe in VERBES_SYSTEME:
            self.noter(_reserve("systeme", f"commande système : {verbe}"))
        self.sous_commandes(verbe, args)
        if verbe in VERBES_ILLISIBLES:
            self.noter(_illisible(verbe))
        if verbe in SHELLS:
            if "-c" in args:
                k = args.index("-c")
                if k + 1 >= len(args):
                    self.noter(_illisible(f"{verbe} -c sans commande"))
                self.analyser(args[k + 1], cwd, prof + 1)
            return cwd
        if verbe == "git":
            self.git(args, cwd, prof)
            return cwd
        for nom, options_valeur, premier_seul in RESEAU:
            if verbe == nom:
                self.reseau(nom, args, options_valeur, premier_seul)
                return cwd
        if verbe == "find":
            for k, a in enumerate(args):
                if a in ("-exec", "-execdir", "-ok", "-okdir"):
                    fin = next((j for j in range(k + 1, len(args)) if args[j] in (";", "\x1f", "+")),
                               len(args))
                    self.commande(args[k + 1:fin], cwd, prof + 1)
            return cwd
        if verbe in ENVELOPPES:
            reste = args
            if verbe == "timeout":
                reste = [a for a in reste if not a.startswith("-")][1:]
            while reste and (reste[0].startswith("-") or _AFFECTATION.match(reste[0])):
                reste = reste[1:]
            if reste:
                self.commande(reste, cwd, prof + 1)
            return cwd
        for premier, second in ENVELOPPES_DOUBLES:
            if verbe == premier and args[:1] == [second]:
                options, reste = _options_enveloppe(args[1:])
                self.dependance(verbe, args, args[:1])      # `pipx run <paquet>`
                self.paquets_par_option(verbe, second, options)
                if reste:
                    self.commande(reste, cwd, prof + 1)
                return cwd
        self.dependance(verbe, args)
        return cwd

    def git(self, args: list[str], cwd: Path, prof: int = 0) -> None:
        k = 0
        while k < len(args) and args[k].startswith("-"):
            if args[k] in GIT_OPTIONS_VALEUR:
                k += 1
            k += 1
        if k >= len(args):
            return
        sub, reste = args[k], args[k + 1:]
        for nom, reservantes, liberantes, theme in GIT_RESERVE:
            if sub != nom:
                continue
            if reservantes is None:
                if not any(o in reste for o in liberantes):
                    self.noter(_reserve(theme, f"git {sub}"))
            elif any(o in reste for o in reservantes) or (
                    nom == "clean" and any(re.fullmatch(r"-[a-zA-Z]*f[a-zA-Z]*", o) for o in reste)):
                self.noter(_reserve(theme, f"git {sub} {' '.join(o for o in reste if o.startswith('-'))}"))
        if sub in GIT_RESEAU:
            self._git_reseau(sub, reste, sub == "clone")
        mots = [a for a in reste if not a.startswith("-")]
        for nom, verbes in GIT_RESEAU_SOUS_COMMANDES:
            if sub != nom or not mots:
                continue
            if mots[0] in verbes:
                self._git_reseau(f"{sub} {mots[0]}", reste[reste.index(mots[0]) + 1:], False)
            elif sub == "submodule" and mots[0] == "foreach":
                commande = reste[reste.index("foreach") + 1:]
                while commande and commande[0].startswith("-"):
                    commande = commande[1:]
                if commande:
                    self.analyser(" ".join(commande), cwd, prof + 1)

    def _git_reseau(self, libelle: str, reste: list[str], sans_hote_permis: bool) -> None:
        hotes = [h for h in (self._hote(a) for a in reste if not a.startswith("-")) if h]
        if not hotes and not sans_hote_permis:
            self.noter(_reserve("reseau", f"git {libelle} vers un dépôt distant dont l'hôte n'est pas écrit"))
        for h in hotes:
            if not self.cadre.site_permis(h):
                self.noter(_reserve("reseau", f"git {libelle} vers {h} : pas un site permis"))

    def _hote(self, mot: str) -> str | None:
        if _URL.match(mot):
            return _hote_url(mot)
        m = _SCP.match(mot)
        return m.group(1) if m else None

    def reseau(self, verbe, args, options_valeur, premier_seul) -> None:
        positionnels, k = [], 0
        while k < len(args):
            a = args[k]
            if a.startswith("-"):
                if a in options_valeur:
                    k += 1
            else:
                positionnels.append(a)
            k += 1
        if premier_seul:
            positionnels = positionnels[:1]
        if not positionnels:
            return
        boucle = verbe in RESEAU_BOUCLE_LOCALE and not any(
            a.split("=", 1)[0] in OPTIONS_DETOURNANT
            or (verbe == "curl" and re.fullmatch(r"-[A-Za-z]*x[A-Za-z]*", a))
            for a in args if a.startswith("-"))
        for p in positionnels:
            hote = self._hote(p)
            if hote is None:
                if verbe in ("scp", "rsync"):
                    continue            # sans `hôte:` ni URL, un chemin local : jugé comme chemin
                m = _HOTE_NU.match(p)
                if m is not None:
                    hote = m.group(1)
                elif _BOUCLE_IPV6.match(p):
                    hote = "::1"
                else:
                    self.noter(_reserve("reseau", f"{verbe} : hôte illisible ({p})"))
                    continue
            if boucle and est_boucle_locale(hote):
                continue
            if not self.cadre.site_permis(hote):
                self.noter(_reserve("reseau", f"{verbe} vers {hote} : pas un site permis"))

    def sous_commandes(self, verbe: str, args: list[str]) -> None:
        for nom, suite, libres, theme in SOUS_COMMANDES_RESERVEES:
            fin = _fin_suite(suite, args) if verbe == nom else None
            if fin is None:
                continue
            suivants = [a for a in args[fin:] if not a.startswith("-")]
            if suivants and suivants[0] in libres:
                continue                # une lecture : `npm config get`
            self.noter(_reserve(theme, f"{verbe} {' '.join(suite)}"))

    def _hors_projet(self, verbe: str, args: list[str]) -> None:
        for k, a in enumerate(args):
            if (a in OPTIONS_HORS_PROJET or a.split("=", 1)[0] in OPTIONS_HORS_PROJET
                    or (a == "--location" and args[k + 1:k + 2] == ["global"])
                    or (verbe in GESTIONNAIRES_JS and re.fullmatch(r"-[A-Za-z]*g[A-Za-z]*", a))):
                self.noter(_reserve("hors_projet", f"{verbe} : installation hors du projet ({a})"))

    def _sources(self, verbe: str, args: list[str]) -> None:
        """Une source explicite (index, dépôt, URL) : son hôte doit être un site permis."""
        k = 0
        while k < len(args):
            a = args[k]
            valeur = None
            if a in OPTIONS_SOURCE and k + 1 < len(args):
                valeur = args[k + 1]
                k += 1
            elif a.startswith("--") and "=" in a and a.split("=", 1)[0] in OPTIONS_SOURCE:
                valeur = a.split("=", 1)[1]
            elif a.startswith("git+") or _URL.match(a) or _SCP.match(a):
                valeur = a
            k += 1
            if valeur is None:
                continue
            hote = self._hote(valeur[4:] if valeur.startswith("git+") else valeur)
            if hote is None or not self.cadre.site_permis(hote):
                self.noter(_reserve("reseau", f"{verbe} : source explicite hors des sites permis ({valeur[:80]})"))

    def dependance(self, verbe: str, args: list[str], mots=None) -> None:
        """`mots` : où chercher la sous-commande (défaut : tous les arguments)."""
        for nom, suite in DEPENDANCES:
            if verbe != nom or not _sous_suite(suite, args if mots is None else mots):
                continue
            self._hors_projet(verbe, args)
            self._sources(verbe, args)
            self.noter(_resultat(AUTONOME, "dependance", f"ajout de dépendance : {verbe} {' '.join(suite)}".rstrip()))
            return

    def paquets_par_option(self, verbe: str, sous: str, options: list[str]) -> None:
        """`uv run --with <paquet>` : récupère le paquet, sauf si une option coupe le réseau."""
        for nom, sous_commande, avec, coupe in PAQUETS_PAR_OPTION:
            if verbe != nom or sous != sous_commande:
                continue
            if not any(a in avec or a.split("=", 1)[0] in avec for a in options):
                continue
            self._hors_projet(verbe, options)
            self._sources(verbe, options)
            if not any(a in coupe for a in options):
                self.noter(_resultat(AUTONOME, "dependance", f"paquet distant : {verbe} {sous} {avec[0]}"))
            return


def _options_enveloppe(args: list[str]) -> tuple[list[str], list[str]]:
    """(options, commande lancée) : les options d'une enveloppe, valeurs comprises."""
    k = 0
    while k < len(args) and args[k].startswith("-"):
        k += 2 if args[k] in ENVELOPPES_OPTIONS_VALEUR else 1
    return args[:k], args[k:]


def _fin_suite(suite: tuple[str, ...], args: list[str]) -> int | None:
    """Indice qui suit la dernière sous-commande trouvée dans l'ordre, None si elle manque."""
    k = 0
    for mot in suite:
        while k < len(args) and args[k] != mot:
            k += 1
        if k == len(args):
            return None
        k += 1
    return k


def _sous_suite(suite: tuple[str, ...], args: list[str]) -> bool:
    return _fin_suite(suite, args) is not None


def _classer_bash(cadre, entree, cwd) -> dict:
    commande = entree.get("command")
    if not isinstance(commande, str) or not commande.strip():
        return _illisible("commande absente")
    shell = _Shell(cadre)
    try:
        shell.analyser(commande, cwd)
    except _Verdict:
        pass
    return plus_fermee(shell.verdicts) if shell.verdicts else _resultat(
        LIBRE, "projet", "commande dans le projet")


# --- l'entrée -------------------------------------------------------------------------------

def classer_autorisation(projet, agent, outil, entree, cwd=None) -> dict:
    """`{"classe": "libre"|"autonome"|"reserve", "theme", "motif"}` d'une demande de `agent`
    pour `outil` avec `entree` (le `tool_input` du hook). `cwd` : dossier de l'agent (défaut :
    le projet). Ne lève jamais : toute erreur vaut `reserve`, thème `illisible`."""
    try:
        cadre = _Cadre(Path(projet))
        dossier = Path(os.path.realpath(cwd)) if cwd else cadre.projet
        entree = entree if isinstance(entree, dict) else {}
        if outil == OUTIL_SHELL:
            return _classer_bash(cadre, entree, dossier)
        if outil in OUTILS_ECRITURE or outil in OUTILS_LECTURE:
            return _classer_fichier(cadre, outil, entree, dossier)
        if outil in OUTILS_WEB:
            return _classer_web(cadre, outil, entree)
        return _reserve("outil_inconnu", f"outil inconnu ou MCP : {outil}")
    except Exception as e:  # dans le doute, réservé
        return _reserve("illisible", f"classement impossible : {type(e).__name__}")
