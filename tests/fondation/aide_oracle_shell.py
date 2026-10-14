"""Oracle contre un vrai shell et générateur de commandes pour les tests de la garde.

L'oracle exécute une commande dans `/bin/bash` ou `/bin/zsh`, dans un dossier temporaire, avec
`git`, `tmux`, `security` et `rtk` remplacés par de faux programmes qui écrivent leurs arguments
dans un journal et ne font rien d'autre. Il dit si un appel interdit a réellement eu lieu.
Les commandes du corpus ne touchent que ce dossier : ni suppression, ni réseau.
"""
import os
import random
import subprocess
from pathlib import Path

from aide_garde_texte import poser_scripts

FAUX = ("git", "tmux", "security", "rtk")
SHELLS = {"bash": ["/bin/bash", "--norc", "--noprofile", "-c"], "zsh": ["/bin/zsh", "-f", "-c"]}
DELAI = 10

# Un faux programme : une ligne par appel, nom et arguments séparés par \x1f, appels par \x1e.
_FAUX_PROGRAMME = """#!/bin/sh
{ printf '%s' "${0##*/}"; for a in "$@"; do printf '\\037%s' "$a"; done; printf '\\036'; } >> "$ORACLE_JOURNAL"
"""


_OPTIONS_GIT_A_VALEUR = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}


def _git_interdit(args):
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 2 if args[i] in _OPTIONS_GIT_A_VALEUR else 1
    if i >= len(args):
        return False
    sub, reste = args[i], args[i + 1:]
    if sub in ("push", "send-pack"):
        return True
    if sub == "branch":
        for a in reste:
            if a == "--":
                break
            if a.startswith("--") and len(a) >= 3 and "--delete".startswith(a):
                return True
            if a.startswith("-") and not a.startswith("--") and ("d" in a or "D" in a):
                return True
    return False


def interdit(appel):
    """Un appel journalisé (nom, arguments…) est-il une action interdite ?"""
    nom, args = appel[0], list(appel[1:])
    if nom in ("tmux", "security"):
        return True
    if nom == "rtk":
        return args[:1] == ["proxy"]
    return nom == "git" and _git_interdit(args)


class Oracle:
    def __init__(self, racine: Path):
        self.racine = Path(racine)
        self.bin = self.racine / "bin"
        self.travail = self.racine / "travail"
        self.maison = self.racine / "maison"
        for d in (self.bin, self.travail, self.maison):
            d.mkdir(parents=True, exist_ok=True)
        for nom in FAUX:
            p = self.bin / nom
            p.write_text(_FAUX_PROGRAMME)
            p.chmod(0o755)
        poser_scripts(self.travail)
        self.journal = self.racine / "journal"

    @staticmethod
    def disponibles():
        return [n for n, argv in SHELLS.items() if os.access(argv[0], os.X_OK)]

    def appels(self, commande: str, shell: str) -> list[tuple[str, ...]]:
        """Appels des faux programmes faits par `commande` exécutée dans `shell`."""
        self.journal.write_text("")
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "HOME": str(self.maison),
               "ORACLE_JOURNAL": str(self.journal), "GIT_CEILING_DIRECTORIES": str(self.racine),
               "LANG": "C", "LC_ALL": "C"}
        try:
            subprocess.run([*SHELLS[shell], commande], cwd=self.travail, env=env,
                           stdin=subprocess.DEVNULL, capture_output=True, timeout=DELAI)
        except subprocess.TimeoutExpired:
            pass
        brut = self.journal.read_text()
        return [tuple(a.split("\x1f")) for a in brut.split("\x1e") if a]

    def interdits(self, commande: str, shell: str) -> list[tuple[str, ...]]:
        return [a for a in self.appels(commande, shell) if interdit(a)]



# --- générateur ----------------------------------------------------------------------------

PREFIXES = [
    "# l'export d'Eugène ne fait ni push ni tmux",
    "# commentaire sans apostrophe : git push",
    "echo 'git push'",
    "echo \"tmux et security\"",
    "echo $'l\\'export # git push'",
    "echo \"a # b\"",
    "echo a#b",
    "x=$(echo 'git push')",
    "echo `echo tmux`",
    "cat <<'EOF'\ngit push\n# l'export\nEOF\n",
    "cat <<EOF\ntmux ls\nEOF\n",
    "cat > note.txt <<'EOF'\nsecurity find-generic-password\nEOF\n",
    "true \\\n  && echo suite",
    "g=git",
    "shopt -s expand_aliases 2>/dev/null; alias gp='git push'\n",
    "echo \"it's\" # l'export",
    "echo $'\\''",
    "a=#",
    "x=$(cat <<'EOF'\ngit push\nEOF\n)",
    "git commit --dry-run -F - <<'EOF'\nl'export : ni push ni tmux\nEOF\n",
]
ACTIONS = [
    "git push", "git push origin main", "git -C . push", "git --no-pager push", "command git push",
    "env git push", "\\git push", "git branch -D x", "git branch --delete x", "git branch -d x",
    "tmux ls", "security find-generic-password -s x", "rtk proxy ls", "$g push", "\"$g\" push", "gp",
    "sh -c 'git push'", "bash -c \"tmux ls\"", "zsh -c 'security x'",
    "bash <<'EOF'\n# l'export\ngit push\nEOF\n", "sh <<EOF\ntmux ls\nEOF\n",
    "cat <<'EOF' | sh\ngit push\nEOF\n", "bash -s <<'EOF'\nsecurity x\nEOF\n",
    "bash s_push.sh", "sh s_push.sh", "./s_push.sh",
    "python3 -c 'import subprocess; subprocess.run([\"git\", \"push\"])'",
    "python3 - <<'EOF'\n# l'export\nimport os\nos.system('tmux ls')\nEOF\n",
    "perl -e 'system(\"git push\")'",
    "$(echo git) push", "echo $(git push)", "echo `tmux ls`", "( git push )", "{ git push; }",
    "git \\\n push",
    "$(cat <<'EOF'\ngit push\nEOF\n)",
    "cat <<EOF |\ngit push\nEOF\nsh",
]
INOFFENSIVES = ["git status", "echo ok", "ls >/dev/null", "true", "git log -1"]
JOINTS = ["; ", " && ", " || ", " | ", "\n"]


def generer(n: int, graine: int) -> list[str]:
    """`n` commandes faites de fragments contrôlés, toujours les mêmes pour une graine."""
    hasard = random.Random(graine)
    commandes = []
    for _ in range(n):
        morceaux = [hasard.choice(PREFIXES + ACTIONS + INOFFENSIVES)
                    for _ in range(hasard.randint(2, 4))]
        texte = morceaux[0]
        for m in morceaux[1:]:
            # après un heredoc ou une fin de ligne, la suite commence sur une nouvelle ligne
            joint = "" if texte.endswith("\n") else hasard.choice(JOINTS)
            texte += joint + m
        texte = texte.rstrip("\n")
        habit = hasard.random()
        if habit < 0.1 and "\n" not in texte:
            texte = f"( {texte} )"
        elif habit < 0.2 and "\n" not in texte:
            texte = f"{{ {texte}; }}"
        commandes.append(texte)
    return commandes
