"""Garde : refuse par le code les commandes Bash réservées à l'utilisateur.

`decider(entree, projet)` reçoit le JSON d'un hook `PreToolUse` et retourne un
motif (refus) ou `None`. Il ne lève jamais.
"""
import io
import sqlite3
import os
import re
import shlex
import subprocess
import tokenize
from contextlib import contextmanager
from pathlib import Path

from cime.fondation import fusions_auto, perimetre
from cime.fondation.nom import NOM, VAR_AGENT, VAR_PROJET
from cime.fondation.projet import ErreurProjet, lire_manifeste

_SUPERIEUR = "demande-le à ton supérieur"
M_PUSH = f"git push est réservé à l'utilisateur : {_SUPERIEUR}."
M_BRANCHE = ("la suppression de branche est réservée à l'utilisateur : "
             "demande-la à ton supérieur.")
M_SECURITY = ("le Trousseau macOS (`security`) est interdit à tout agent : "
              "aucun secret n'est lu. Si un jeton te manque, dis-le à ton supérieur.")
M_PROXY = ("`rtk proxy` exécute une commande brute hors de tout contrôle : interdit. "
           "Lance la commande directement.")
M_TMUX_FERME = ("tmux est fermé à tous les agents, lecture comprise : la conversation passe par "
                "le registre, et seul le facteur touche un terminal. Utilise la commande `cime` "
                "équivalente : `cime envoyer` pour écrire à un agent, `cime voir <agent>` pour "
                "lire l'écran d'un de tes subordonnés, `cime compacter` pour le compacter, "
                "`cime terminer` pour fermer un worker. (tmux lancé par xargs, parallel ou "
                "find -exec est refusé de même.)")
M_IDENTITE = ("{nom} désigne l'agent ou le projet de cette session : aucune commande ne l'affecte "
              "ni ne la retire (`VAR=… cmd`, `env -u`, `env -i`, `unset`, `export`, `declare -x`, "
              "`os.environ[…]`). La lire reste permis (`echo $CIME_AGENT`). Pour agir au nom d'un "
              "autre agent, passe par ton supérieur ; `cime lancer` pose l'identité des sessions.")
M_ACCORD_FUSION = ("la fusion de {ref} ({sha}) sur la branche de référence exige un accord "
                   "de l'utilisateur non consommé pour ce sha (`objet=fusion:<équipe>:<sha>`) : {cause}. "
                   "Demande-le avec `cime envoyer --a utilisateur --nature decision_utilisateur "
                   "--objet fusion:<équipe>:{sha_complet} \"…\"`. Un accord = une fusion, et "
                   "si la branche a avancé depuis l'accord il en faut un nouveau.")
M_AUTO_REFUSEE = (" L'option « Fusions automatiques » est active, mais la voie automatique est "
                  "refusée pour {ref} : condition {n} ({nom}) — {cause}.")
M_AUTO_ANNONCE = (" Annonce-la avec `cime envoyer --a utilisateur --nature rapport_utilisateur --objet "
                  "fusion-auto:{equipe}:{sha} \"…\"`, puis relance `git merge`.")
M_ECRITURE_RESERVEE = ("{motif} (`{verbe}` refusé sur {chemin}.) Lire reste permis (ls, cat, "
                       "grep, Read).")
M_SQLITE = ("le registre ne se lit ni ne s'écrit avec un client SQLite ({client}) : passe par "
            "`cime` (`cime reprise` pour ton état, `cime envoyer`, `cime repondre`, "
            "`cime voir <agent>`).")
M_FUSION = ("`git {sub}` sur la branche de référence ou dans le dépôt principal est "
            f"réservé à l'utilisateur : {_SUPERIEUR}. Les intégrations se font dans "
            "un worktree d'équipe (`git -C <worktree> {sub} …`).")
M_FUSION_MERGE = ("la fusion sur la branche de référence est faite par l'Assistant, avec "
                  "l'accord de l'utilisateur : demande-la-lui par le canal écrit habituel "
                  "(`git -C <worktree> merge …` reste permis dans ton worktree).")
M_FILE = ("`git {sub}` écrit la branche de référence sans passer par la file de fusion, qui lance "
          "la suite entière avant chaque fusion : utilise `cime fusionner <équipe>` (la mise à "
          "jour d'une branche d'équipe avec la référence reste `git -C <worktree> merge …`).")
M_COMMIT_FUSION = ("`git commit` pendant une fusion en cours sur la branche de référence achèverait "
                   "une fusion hors de la file : utilise `cime fusionner <équipe>`.")
M_COMMIT_REECRIT = ("`git commit --amend` sur la branche de référence en réécrit la pointe hors de "
                    "la file de fusion : fais un nouveau commit.")
M_FUSION_SANS_CIBLE = ("`git merge` sans branche donnée : l'Assistant ne fusionne qu'une "
                       "branche nommée (`git merge <branche>`), pour que le journal la trace.")
M_REF =(f"modifier la branche de référence est réservé à l'utilisateur : {_SUPERIEUR}.")
M_INCONNU = ("`git {sub}` vise un dossier que le garde ne peut pas résoudre "
             "(variable, `cd -`…) : écris le chemin en clair (`git -C /chemin {sub} …`).")
M_DETOURNE = ("`git merge` vise un dépôt désigné par GIT_DIR, GIT_WORK_TREE ou "
              "--git-dir/--work-tree, qui n'est pas le dépôt principal : refusé à tous. "
              "Écris le dossier en clair (`git -C /chemin merge …`).")
M_LANCER_WORKER = (f"tu ne lances aucun agent : `{NOM} lancer` est refusé à ton rôle. "
                   f"Si tu as besoin d'un autre worker, demande-le à ton coordinateur "
                   f"(`{NOM} envoyer`).")
M_LANCER_COORD = (f"tu ne lances que les workers de ton équipe : `{NOM} lancer worker "
                  f"<ton équipe> <tâche> --modele <modèle>`. L'Assistant et les autres "
                  f"équipes se lancent par l'Assistant, à qui tu écris par `{NOM} envoyer`.")
M_LANCER_INTEGRATION = (f"le worker d'intégration est lancé par l'Assistant seul : demande-le à l'Assistant "
                        f"(`{NOM} envoyer --a assistant --nature question --objet integration:{{equipe}}`).")
M_FUSIONNER = (f"tu ne fusionnes rien : `{NOM} fusionner` est refusé à ton rôle. La fusion se "
               f"demande à l'Assistant (`{NOM} envoyer`).")
M_CIME_OPTION = (f"option avant la sous-commande de `{NOM}` : refusée à ton rôle, on ne "
                 f"peut pas savoir si c'est un `lancer`. Forme attendue : `{NOM} <sous-commande> "
                 f"--help` (ou `{NOM} <sous-commande> <options>`).")
M_COORD_COMMIT = ("un coordinateur ne commite que dans son worktree d'équipe : `git -C {worktree} add …` "
                  "puis `git -C {worktree} commit …` ({cible}).")
M_COORD_DETOURNE = ("`git {sub}` vise un dépôt désigné par GIT_DIR, GIT_WORK_TREE ou --git-dir/--work-tree : "
                    "un coordinateur commite avec `git -C {worktree} {sub} …`, rien d'autre.")
M_COORD_HISTOIRE = ("`git {sub}` est refusé à un coordinateur, où que ce soit : il ajoute et commite dans "
                    "son worktree, il ne déplace ni ne défait rien. Pour changer de branche ou revenir "
                    "en arrière, demande-le à l'Assistant (`cime envoyer`).")
M_COORD_REECRITURE = ("`git commit {option}` est refusé à un coordinateur : pas de réécriture d'historique "
                      "et pas de commit sans les vérifications du dépôt. Fais un nouveau commit.")
M_PROFOND = "commande trop imbriquée pour être vérifiée : simplifie-la."
M_REPLI = ("commande non analysable (guillemets non fermés ?) qui ressemble à une "
           "action interdite (push, suppression de branche, Trousseau) : refusée par "
           "prudence. Réécris-la plus simplement.")

M_ERREUR = ("le garde n'a pas pu analyser cette commande (erreur interne) et elle "
            "ressemble à une action interdite (push, suppression de branche, Trousseau, "
            "rtk proxy, tmux) : refusée par prudence. Signale-le à "
            "ton supérieur.")

# Repli textuel prudent, ligne par ligne : aucun motif ne traverse une fin de ligne (« git » ici
# et « push » dans un commentaire plus bas ne font pas une commande). Une copie volontaire vit
# dans hook.py (REPLI), pour le cas où ce module est absent ; un test vérifie que les deux
# listes restent identiques.
_REPLI = [re.compile(r"\bgit\b[^;&|\n]*\bpush\b"), re.compile(r"\bsecurity\b"),
          re.compile(r"\bgit\b[^;&|\n]*\bbranch\b[^;&|\n]*[^\S\n]-(d|D|-delete)\b"),
          re.compile(r"\brtk[^\S\n]+proxy\b"),
          re.compile(r"\btmux\b")]
_SEP = "\x1f"  # remplace `\;` (séparateur tmux, fin de `find -exec`)
_PROF_MAX = 8
_INCONNU = None  # dossier courant impossible à résoudre

_AFFECTATION = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\+?=")
PROTEGEES = (VAR_AGENT, VAR_PROJET, "CLAUDECODE")  # identité et projet : jamais affectés
_ECRIT_ENVIRON = re.compile(
    r"environ\s*\[[^\]]*\]\s*(?<![=!<>])=(?!=)|environ\s*\.\s*(pop|update|setdefault|clear)\b"
    r"|\bdel\s+[\w.]*environ|\b(putenv|unsetenv|setenv)\b"
    # `env = …`, `env={…}` : un environnement fabriqué. Ni une comparaison (`env ==`), ni le
    # passage d'aucun environnement ou de celui du processus (`env=None`, `env=os.environ`).
    r"|\benv\s*=(?!=)(?!\s*(?:None|os\.environ)\s*(?:[,);\n]|$))")
_CLIENTS_SQLITE = {"sqlite3", "litecli", "sqlite-utils"}
_ECRIT_TOUS = {"mv", "rm", "touch", "tee", "truncate", "unlink", "shred"}
_ECRIT_DESTINATION = {"cp", "ln", "install", "rsync"}
_MOTS_CLES = {"if", "then", "else", "elif", "fi", "do", "done", "while", "until",
              "!", "{", "}", "coproc"}
_SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
_INTERPRETE = re.compile(r"^(python[\d.]*|perl|ruby|node|osascript|php)$")
_FUSION = {"merge", "pull", "rebase", "cherry-pick", "am", "reset", "checkout", "switch"}
# ce qui écrit la branche de référence : à l'Assistant, la file de fusion répond
_FUSION_PAR_LA_FILE = {"merge", "pull", "rebase", "cherry-pick", "am", "reset"}
ASSISTANT = "assistant"  # identité de l'Assistant (`cime lancer assistant`)
# options de `git merge` qui prennent une valeur au mot suivant
_MERGE_VALEUR = {"-m", "-s", "-X", "-F", "--message", "--strategy", "--strategy-option",
                 "--into-name", "--cleanup", "--file"}
_MERGE_CONTINUITE = {"--abort", "--quit"}  # ne fusionnent rien ; `--continue` achève une fusion


# descripteur collé à sa redirection (`2>&1`, `1>f`, `0<f`) : début de mot, chiffres, `>` ou `<`
_FD_REDIRECTION = re.compile(r"(?<![^\s;|&(])\d+(?=[<>])")


class _Refus(Exception):
    pass


class _Contexte:
    def __init__(self, entree: dict, projet: Path | None):
        self.texte = ""
        self.projet = None
        self.refs = {"main", "master"}
        self.assistant = None
        self.agent = os.environ.get(VAR_AGENT) or None
        self.fusions = []  # références données aux `git merge` de l'Assistant, permis
        self.accords_utilises = []  # un accord = une fusion, même dans une seule commande
        self.voies = {}  # par référence fusionnée : "accord" ou "auto" (lu par le hook)
        self.auto = {}  # par référence "auto" : équipe, sha, annonce, réglage, fichiers
        self.prefixe = None
        self.manifeste = None
        self.variables = {}  # `x=valeur` posées seules dans la commande, lues par `$x`
        self.alias = {}      # `alias nom=valeur` posés dans la commande
        if projet is not None:
            try:
                m = lire_manifeste(Path(projet))
                self.manifeste = m
                self.projet = Path(projet).resolve()
                self.refs = {m.branche_reference}
                self.prefixe = m.prefixe
                self.assistant = f"{m.prefixe}-assistant"
            except (ErreurProjet, OSError, TypeError):
                pass


def _examiner(entree: dict, projet: Path | None) -> "_Contexte | None":
    """Analyse la commande du hook. Lève `_Refus` ; None si rien à analyser."""
    if entree.get("tool_name") != "Bash":
        return None
    commande = (entree.get("tool_input") or {}).get("command")
    if not isinstance(commande, str):
        return None
    ctx = _Contexte(entree, projet)
    ctx.texte = commande
    cwd = entree.get("cwd")
    _analyser(commande, Path(cwd) if cwd else _INCONNU, ctx, 0)
    return ctx


def decider(entree: dict, projet: Path | None) -> str | None:
    try:
        _examiner(entree, projet)
    except _Refus as r:
        return str(r)
    except Exception:
        # Une erreur interne ne doit pas valoir autorisation (« un garde-fou qui se
        # calcule sur une absence certifie ») : repli textuel prudent, Bash seulement.
        try:
            commande = (entree.get("tool_input") or {}).get("command")
            if entree.get("tool_name") == "Bash" and isinstance(commande, str):
                try:
                    texte = sans_commentaires(commande)
                except Exception:
                    texte = commande  # le retrait lui-même en panne : texte entier
                if _ressemble(texte):
                    return M_ERREUR
        except Exception:
            pass
        return None
    return None


def _contexte_fusions(entree: dict, projet: Path | None) -> "_Contexte | None":
    if (os.environ.get(VAR_AGENT) or None) != ASSISTANT:
        return None
    try:
        return _examiner(entree, projet)
    except Exception:  # _Refus compris : rien n'est permis, rien n'est journalisé
        return None


def fusions_autorisees(entree: dict, projet: Path | None) -> list[str]:
    """Références que la garde laisse fusionner à l'Assistant sur le dépôt principal, dans
    l'ordre de la commande. Vide pour tout autre agent et pour toute commande sans telle
    fusion. Ne lève jamais. À n'appeler que quand `decider` n'a rien refusé."""
    ctx = _contexte_fusions(entree, projet)
    return list(ctx.fusions) if ctx else []


def fusions_detaillees(entree: dict, projet: Path | None) -> list[dict]:
    """Comme `fusions_autorisees`, avec la voie de chacune : `{"ref", "voie": "accord"|"auto"}` et,
    pour "auto", `equipe`, `sha`, `annonce`, `reglage`, `fichiers`. Ne lève jamais."""
    ctx = _contexte_fusions(entree, projet)
    if not ctx:
        return []
    return [{"ref": ref, "voie": ctx.voies.get(ref, "accord"), **ctx.auto.get(ref, {})}
            for ref in ctx.fusions]


# --- découpage -------------------------------------------------------------

def _ressemble(texte: str) -> bool:
    """Une ligne du texte ressemble-t-elle à une action interdite ? Les continuations (`\\` en
    fin de ligne) sont d'abord jointes : `git \\⏎ push` est une seule ligne pour le shell."""
    texte = texte.replace("\\\n", " ")
    return any(r.search(texte) for r in _REPLI)


def _repli(texte: str) -> None:
    if _ressemble(texte):
        raise _Refus(M_REPLI)


# --- texte d'un shell : commentaires, chaînes $'…', heredocs ------------------------------
#
# `_lire` parcourt un texte comme le shell le découpe : guillemets simples et doubles, `$'…'`,
# `\x`, `$( … )`, backticks, `${ … }`, `$(( … ))`, heredocs. Un `#` n'ouvre un commentaire que
# s'il commence un mot hors de tout guillemet. Au moindre doute (construction mal suivie,
# guillemet resté ouvert), rien n'est plus retiré à partir de la ligne en cause : retirer un
# commentaire ne doit jamais pouvoir cacher une commande que le shell exécute.

_SEPARE_MOT = " \t\n;&|("  # après l'un d'eux, ou en début de texte, un mot commence (`(#` à part)
_FIN_DELIMITEUR = " \t\n;&|<>()"  # fin du mot délimiteur d'un heredoc
# ouvertures, de la plus longue à la plus courte : (texte, contexte ouvert)
_OUVERTURES = [("$((", "(("), ("$(", "$("), ("${", "${"), ("`", "`"), ("$'", "$'"),
               ('$"', '"'), ("'", "'"), ('"', '"')]
_GUILLEMETS = {"$'", "'", '"'}


class _Heredoc:
    def __init__(self, operateur: int, substitutions: list[int], cite: bool, corps: int,
                 fin_corps: int, apres: int):
        self.operateur = operateur  # position de `<<`
        self.substitutions = substitutions  # ouvertures des `$(` et backticks qui l'entourent
        self.cite = cite            # délimiteur cité : le corps n'est pas développé
        self.corps = corps          # début du corps
        self.fin_corps = fin_corps  # début de la ligne du délimiteur
        self.apres = apres          # après la ligne du délimiteur


class _Lecture:
    """Ce que `_lire` trouve dans un texte de shell, en positions dans ce texte."""

    def __init__(self, texte: str):
        self.texte = texte
        self.commentaires = []  # (début, fin) : du `#` à la fin de sa ligne
        self.ansi = []          # (début, fin) : une chaîne `$'…'`, guillemets compris
        self.heredocs = []      # _Heredoc, dans l'ordre du texte
        self.doute = None       # début de la première ligne douteuse

    def douter(self, pos: int) -> None:
        debut = self.texte.rfind("\n", 0, pos) + 1
        if self.doute is None or debut < self.doute:
            self.doute = debut

    def retirables(self) -> list[tuple[int, int]]:
        """Les commentaires qu'on peut retirer : avant toute ligne douteuse, hors shebang."""
        return [(a, b) for a, b in self.commentaires
                if (self.doute is None or a < self.doute)
                and not (a == 0 and self.texte.startswith("#!"))]


def _ouverture(texte: str, i: int, contexte: str):
    """(contexte ouvert, longueur) si une chaîne ou une substitution s'ouvre en i."""
    for debut, genre in _OUVERTURES:
        if texte.startswith(debut, i) and not (contexte == '"' and genre in _GUILLEMETS):
            return genre, len(debut)
    return None


def _ouvrir_heredoc(texte: str, i: int, pile: list, attente: list, lu: _Lecture) -> int:
    """`<<` ou `<<-` en i : lit le mot délimiteur et met le heredoc en attente de la fin de la
    ligne. Rend la position qui suit le mot."""
    j = i + 2
    tiret = texte.startswith("-", j)
    j += tiret
    while j < len(texte) and texte[j] in " \t":
        j += 1
    mot, cite = [], False
    while j < len(texte) and texte[j] not in _FIN_DELIMITEUR:
        c = texte[j]
        if c in "'\"":
            fin = texte.find(c, j + 1)
            if fin < 0:  # délimiteur mal fermé : on ne le suit pas
                lu.douter(i)
                return j
            mot.append(texte[j + 1:fin])
            cite, j = True, fin + 1
        elif c == "\\" and j + 1 < len(texte):
            mot.append(texte[j + 1])
            cite, j = True, j + 2
        else:
            mot.append(c)
            j += 1
    if mot:
        substitutions = [p for g, p in pile if g in ("$(", "`")]
        attente.append((i, substitutions, "".join(mot), tiret, cite))
    return j


def _ligne_delimiteur(texte: str, debut: int, delim: str, tiret: bool, cite: bool):
    """(début, après) de la ligne qui ferme le heredoc, cherchée à partir de `debut` ; None si
    elle manque. Dans un corps non cité, un `\\` final joint la ligne à la suivante."""
    k, suite = debut, False
    while True:
        fin = texte.find("\n", k)
        fin = len(texte) if fin < 0 else fin
        ligne = texte[k:fin]
        if not suite and (ligne.lstrip("\t") if tiret else ligne) == delim:
            return k, min(fin + 1, len(texte))
        suite = not cite and (len(ligne) - len(ligne.rstrip("\\"))) % 2 == 1
        if fin >= len(texte):
            return None
        k = fin + 1


def _corps_heredocs(texte: str, i: int, attente: list, lu: _Lecture) -> int:
    """Fin (texte[i] == "\\n") d'une ligne qui ouvre des heredocs : leurs corps suivent, l'un
    après l'autre. Un délimiteur absent laisse la suite lue comme du code. Rend la position
    où reprendre."""
    debut = i + 1
    for operateur, substitutions, delim, tiret, cite in attente:
        trouve = _ligne_delimiteur(texte, debut, delim, tiret, cite)
        if trouve is None:
            break
        lu.heredocs.append(_Heredoc(operateur, substitutions, cite, debut, *trouve))
        debut = trouve[1]
    attente.clear()
    return debut


def _lire(texte: str) -> _Lecture:
    lu, pile, attente = _Lecture(texte), [("code", 0)], []
    i, debut_mot = 0, True
    while i < len(texte):
        haut, c = pile[-1][0], texte[i]
        if haut == "'":
            if c == "'":
                pile.pop()
            i += 1
        elif haut in ("$'", "`") and c == "\\":
            i += 2
        elif haut == "$'":
            if c == "'":
                lu.ansi.append((pile.pop()[1], i + 1))
            i += 1
        elif haut == "`":  # quotes non suivies dans des backticks : déjà en doute
            if c == "`":
                pile.pop()
            i += 1
        elif c == "\\":
            if not (texte.startswith("\\\n", i) and haut in ("code", "(", "$(")):
                debut_mot = False  # caractère échappé ; une continuation, elle, ne coupe rien
            i += 2
        elif _ouverture(texte, i, haut):
            genre, longueur = _ouverture(texte, i, haut)
            if genre == "`" or (genre in _GUILLEMETS and haut in ("${", "((")):
                lu.douter(i)  # backticks, guillemets dans ${ } ou $(( )) : règles mal suivies
            pile.append((genre, i))
            i += longueur
            debut_mot = False
        elif haut == '"':
            if c == '"':
                pile.pop()
            i += 1
        elif haut == "${":
            if c == "}":
                pile.pop()
            elif c == "{":
                lu.douter(i)
                pile.append(("${", i))
            i += 1
        elif haut in ("((", "a("):
            if haut == "((" and texte.startswith("))", i):
                pile.pop()
                i += 2
                continue
            if c == "(":
                pile.append(("a(", i))
            elif c == ")":
                if haut == "((":
                    lu.douter(i)
                pile.pop()
            i += 1
        else:  # du code : au niveau du texte, dans ( ), dans $( )
            i, debut_mot = _lire_code(texte, i, debut_mot, pile, attente, lu)
    if len(pile) > 1:  # quelque chose reste ouvert : la suite n'est pas sûre
        lu.douter(pile[1][1])
    return lu


def _lire_code(texte, i, debut_mot, pile, attente, lu) -> tuple[int, bool]:
    """Un pas de `_lire` dans du code. Rend (position suivante, un mot commence-t-il)."""
    c, haut = texte[i], pile[-1][0]
    # `(#` n'ouvre pas de commentaire : en zsh, `ls (#i)x` est un motif, pas un commentaire
    if c == "#" and debut_mot and texte[i - 1:i] != "(":
        fin = texte.find("\n", i)
        fin = len(texte) if fin < 0 else fin
        if all(g in ("code", "(") for g, _ in pile):
            lu.commentaires.append((i, fin))
        else:  # commentaire dans $( ) : bash 3.2, bash récents et zsh ne s'y accordent pas
            lu.douter(i)
        return fin, True
    if texte.startswith("<<<", i):
        return i + 3, True
    if texte.startswith("<<", i):
        return _ouvrir_heredoc(texte, i, pile, attente, lu), False
    if texte.startswith("((", i) and debut_mot:
        pile.append(("((", i))
        return i + 2, False
    if c == "(":
        # `<(` et `>(` se lisent comme `$(` : une substitution
        pile.append(("$(" if texte[i - 1:i] in ("<", ">") else "(", i))
    elif c == ")" and haut in ("(", "$("):
        pile.pop()
    elif c == "\n" and attente:
        return _corps_heredocs(texte, i, attente, lu), True
    return i + 1, c in _SEPARE_MOT


def sans_commentaires(texte: str) -> str:
    """Le texte d'un shell sans ses commentaires ; les corps de heredoc ne sont pas touchés, la
    ligne de shebang est gardée. Au moindre doute, la ligne en cause et la suite restent."""
    morceaux, k = [], 0
    for a, b in _lire(texte).retirables():
        morceaux.append(texte[k:a])
        k = b
    morceaux.append(texte[k:])
    return "".join(morceaux)


_ECHAPPEMENT_ANSI = re.compile(
    r"\\(?:x([0-9A-Fa-f]{1,2})|u([0-9A-Fa-f]{1,4})|U([0-9A-Fa-f]{1,8})|([0-7]{1,3})|c(.)|(.))", re.S)
_ECHAPPEMENTS = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "e": "\x1b", "E": "\x1b",
                 "f": "\f", "v": "\v"}


def _decoder_ansi(m: re.Match) -> str:
    hexa = m.group(1) or m.group(2) or m.group(3)
    if hexa:
        return chr(min(int(hexa, 16), 0x10FFFF))
    if m.group(4):
        return chr(int(m.group(4), 8) & 0xFF)
    if m.group(5):
        return chr(ord(m.group(5)) & 0x1F)
    return _ECHAPPEMENTS.get(m.group(6), m.group(6))


def _ansi_c(texte: str) -> str:
    """Chaque `$'…'` récrit en la chaîne `'…'` qu'il désigne, que shlex sait lire
    (`$'\\x67it push'` est `git push`)."""
    lu = _lire(texte)
    morceaux, k = [], 0
    for a, b in lu.ansi:
        morceaux += [texte[k:a], shlex.quote(_ECHAPPEMENT_ANSI.sub(_decoder_ansi, texte[a + 2:b - 1]))]
        k = b
    morceaux.append(texte[k:])
    return "".join(morceaux)


def _fin_paren(s: str, i: int) -> int:
    prof, etat = 1, None
    while i < len(s):
        c = s[i]
        if c == "\\" and etat != "'":
            i += 2
            continue
        if etat:
            if c == etat:
                etat = None
        elif c in "'\"":
            etat = c
        elif c == "(":
            prof += 1
        elif c == ")":
            prof -= 1
            if prof == 0:
                return i
        i += 1
    raise ValueError("parenthèse non fermée")


def _substitutions(s: str, guillemets: bool = True) -> list[str]:
    """Contenus de `$( … )` et de backticks, hors guillemets simples."""
    res, i, etat = [], 0, None
    while i < len(s):
        c = s[i]
        if c == "\\" and etat != "'":
            i += 2
            continue
        if guillemets and etat is None and c in "'\"":
            etat = c
        elif guillemets and etat == c:
            etat = None
        elif etat == "'":
            pass
        elif s.startswith("$(", i):
            j = _fin_paren(s, i + 2)
            res.append(s[i + 2:j])
            i = j
        elif c == "`":
            j = i + 1
            while j < len(s) and s[j] != "`":
                j += 2 if s[j] == "\\" else 1
            if j >= len(s):
                raise ValueError("backtick non fermé")
            res.append(s[i + 1:j])
            i = j
        i += 1
    if etat:
        raise ValueError("guillemet non fermé")
    return res


def _heredocs(texte: str) -> tuple[str, list[tuple[str, str, bool, bool]]]:
    """Retire les corps de heredoc : (texte restant, [(corps, ligne qui l'ouvre, délimiteur
    cité, lu par un shell quoi qu'il arrive)]). Seul un `<<` que le shell lit comme tel ouvre
    un heredoc (ni entre guillemets, ni dans un commentaire). Un corps est lu par un shell
    quand son ouverture suit une ligne douteuse, ou quand il sort d'une substitution qui sert
    de nom de commande (`$(cat <<EOF … EOF)` : le texte produit est exécuté)."""
    lu = _lire(texte)
    reste, corps, k = [], [], 0
    for h in lu.heredocs:
        reste.append(texte[k:h.corps])
        k = h.apres
        shell = (lu.doute is not None and h.operateur >= lu.doute) or \
            any(_en_tete_de_commande(texte, p) for p in h.substitutions)
        corps.append((texte[h.corps:h.fin_corps].removesuffix("\n"), _ligne_ouvrante(texte, h),
                      h.cite, shell))
    reste.append(texte[k:])
    return "".join(reste), corps


def _en_tete_de_commande(texte: str, pos: int) -> bool:
    """La substitution ouverte en `pos` est-elle le nom d'une commande ? Pas la valeur d'une
    affectation (`x=$(…)`) ni un argument (`echo "$(…)"`)."""
    if texte[pos - 1:pos] == "=":
        return False
    avant = texte[:pos].rstrip(" \t\"'")
    if not avant or avant[-1] in ";&|(\n{":
        return True
    dernier = re.split(r"[\s;&|()]", avant)[-1]
    return dernier in _MOTS_CLES or dernier in _ENVELOPPES or bool(_AFFECTATION.match(dernier))


def _ligne_ouvrante(texte: str, h: _Heredoc) -> str:
    """La ligne du `<<` ; si elle finit par `|`, la commande qui suit le corps lit aussi."""
    debut = texte.rfind("\n", 0, h.operateur) + 1
    fin = texte.find("\n", h.operateur)
    ligne = texte[debut:fin if fin >= 0 else len(texte)]
    if ligne.rstrip().endswith("|"):
        suite = texte.find("\n", h.apres)
        ligne += " " + texte[h.apres:suite if suite >= 0 else len(texte)]
    return ligne


_LECTEURS_SHELL = _SHELLS | {"eval", "source"}  # un heredoc qu'ils lisent est du shell


def _destinataire(ligne: str) -> str | None:
    """Ce que devient le corps d'un heredoc ouvert sur `ligne` : "shell" s'il y a un shell (ou
    `eval`, `source`) parmi ses mots, le nom de l'interpréteur s'il y en a un, None sinon (du
    texte : `cat`, `tee`, `git commit -F -`, `cime`…)."""
    try:
        mots = _jetons(_ansi_c(sans_commentaires(ligne)))
    except ValueError:  # ligne qu'on ne sait pas découper : tous ses mots comptent
        mots = re.findall(r"[^\s;&|<>()'\"`$]+", ligne)
    noms = [_base(p) for m in mots for p in m.split()]  # `ssh h 'bash -s'` : bash compte
    if any(n in _LECTEURS_SHELL for n in noms):
        return "shell"
    return next((n for n in noms if _INTERPRETE.match(n)), None)


def _python_sans_commentaires(code: str) -> str:
    """Code Python sans ses commentaires (tokenize) ; le texte entier s'il ne se découpe pas."""
    try:
        coupes = {t.start[0]: t.start[1] for t in tokenize.generate_tokens(io.StringIO(code).readline)
                  if t.type == tokenize.COMMENT}
    except (tokenize.TokenError, SyntaxError, ValueError):
        return code
    return "\n".join(ligne[:coupes[k + 1]] if k + 1 in coupes else ligne
                     for k, ligne in enumerate(code.split("\n")))


def _code_sans_commentaires(interprete: str, code: str) -> str:
    """Les commentaires du langage retirés : Python par tokenize, perl et ruby comme un shell
    (`#` en début de mot, hors chaîne). Les chaînes restent : `run("git push")` se voit."""
    if interprete.startswith("python"):
        return _python_sans_commentaires(code)
    if interprete in ("perl", "ruby"):
        return sans_commentaires(code)
    return code


def _verifier_code(interprete: str, code: str) -> None:
    """Code d'un interpréteur (`-c`, `-e`, heredoc) : repli ligne par ligne et identité."""
    code = _code_sans_commentaires(interprete, code)
    _repli(code)
    _identite_code(code)


def _jetons(texte: str) -> list[str]:
    lex = shlex.shlex(texte, posix=True, punctuation_chars="();<>|&\n")
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    lex.commenters = ""
    return list(lex)


def _analyser(texte: str, cwd, ctx: _Contexte, prof: int) -> None:
    if prof > _PROF_MAX:
        raise _Refus(M_PROFOND)
    # les commentaires d'abord : un `\` qui finit un commentaire ne continue pas la ligne
    texte = sans_commentaires(texte)
    texte = texte.replace("\\\n", " ").replace("\\;", _SEP)
    texte = re.sub(r"(?<!\S)(['\"]);\1(?!\S)", _SEP, texte)  # `';'` : séparateur tmux
    texte, corps = _heredocs(texte)
    for contenu, ligne, cite, shell in corps:
        # le corps va à qui le lit : un shell l'exécute, un interpréteur aussi ; pour les
        # autres (`cat`, `tee`, `cime`…) c'est du texte.
        lecteur = "shell" if shell else _destinataire(ligne)
        if lecteur == "shell":
            _analyser(contenu, cwd, ctx, prof + 1)
        elif lecteur:
            _verifier_code(lecteur, contenu)
        if not cite:
            for s in _substitutions(contenu, guillemets=False):
                _analyser(s, _INCONNU, ctx, prof + 1)
    texte = _FD_REDIRECTION.sub("", texte)  # `2>&1`, `1>f` : le chiffre est un descripteur, pas un mot
    texte = _ansi_c(texte)
    try:
        subs = _substitutions(texte)
        jetons = _jetons(texte)
    except ValueError:
        _repli(texte)
        return
    for s in subs:
        _analyser(s, _INCONNU, ctx, prof + 1)

    pile, mots = [], []
    i = 0
    while i < len(jetons):
        t = jetons[i]
        if t and set(t) <= set("();<>|&\n"):
            if (set(t) <= set("<>&") and ("<" in t or ">" in t)) or \
                    (t.startswith(">") and set(t) <= set(">|&")):
                if t == "<<<":
                    mots.append(t)
                else:
                    if ">" in t and i + 1 < len(jetons):
                        _ecrit(">", [jetons[i + 1]], cwd)
                    i += 1  # cible de la redirection
                i += 1
                continue
            if mots:
                cwd = _commande(mots, cwd, ctx, prof)
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
        _commande(mots, cwd, ctx, prof)
    _noms_inconnus(texte, ctx)


# --- noms de commande qu'on ne lit pas -----------------------------------------------------

_ENVELOPPES = {"command", "builtin", "exec", "nohup", "env", "sudo", "doas", "time", "nice",
               "caffeinate", "xargs", "timeout", "stdbuf"}


def _sans_substitutions(s: str) -> str:
    """Chaque `$( … )` et chaque backtick hors guillemets simples remplacé par `$_` : une
    valeur qu'on ne connaît pas, à sa place dans le mot."""
    res, i, etat = [], 0, None
    while i < len(s):
        c = s[i]
        if c == "\\" and etat != "'":
            res.append(s[i:i + 2])
            i += 2
            continue
        if etat is None and c in "'\"" or etat == c:
            etat = None if etat else c
        elif etat != "'" and s.startswith("$(", i):
            res.append("$_")
            i = _fin_paren(s, i + 2) + 1
            continue
        elif etat != "'" and c == "`":
            fin = s.find("`", i + 1)
            if fin < 0:
                raise ValueError("backtick non fermé")
            res.append("$_")
            i = fin + 1
            continue
        res.append(c)
        i += 1
    return "".join(res)


def _noms_inconnus(texte: str, ctx: _Contexte) -> None:
    """Une commande dont le nom ne se lit pas (`$(echo git) push`, `$x push` où x n'est pas
    posé dans la commande) est jugée sur ses arguments : ceux d'un push, d'une suppression de
    branche ou de `rtk proxy` sont refusés comme tels."""
    try:
        jetons = _jetons(_sans_substitutions(texte))
    except ValueError:
        return
    mots = []
    for t in jetons + [";"]:
        if not (t and set(t) <= set("();<>|&\n")):
            mots.append(t)
            continue
        while mots and (_AFFECTATION.match(mots[0]) or mots[0] in _MOTS_CLES
                        or _base(mots[0]) in _ENVELOPPES or mots[0].startswith("-")):
            mots = mots[1:]
        if mots and any(c in _developper_mot(mots[0], ctx) for c in "$`"):
            _arguments_interdits(mots[1:])
        mots = []


def _arguments_interdits(args: list[str]) -> None:
    if "push" in args or "send-pack" in args:
        raise _Refus(M_PUSH)
    if "branch" in args and _supprime_une_branche(args[args.index("branch") + 1:]):
        raise _Refus(M_BRANCHE)
    if args[:1] == ["proxy"]:
        raise _Refus(M_PROXY)


# --- variables et alias posés dans la commande ------------------------------------------------

_VARIABLE = re.compile(r"\$(?:\{([A-Za-z_]\w*)\}|([A-Za-z_]\w*))")


def _developper_mot(mot: str, ctx: _Contexte) -> str:
    """`$x` et `${x}` remplacés par la valeur posée plus tôt dans la commande (`x=git`) ; une
    variable inconnue reste telle quelle."""
    return _VARIABLE.sub(lambda m: ctx.variables.get(m.group(1) or m.group(2), m.group(0)), mot)


def _developper(mots: list[str], ctx: _Contexte) -> list[str]:
    """Les mots de la commande, variables connues remplacées ; un nom de commande qui en
    devient plusieurs mots est coupé comme le shell le coupe (`G="git push"; $G`)."""
    mots = [_developper_mot(m, ctx) for m in mots]
    return (mots[0].split() or mots[:1]) + mots[1:]


def _alias(args: list[str], ctx: _Contexte) -> None:
    for a in args:
        nom, egal, valeur = a.partition("=")
        if egal and nom:
            ctx.alias[nom] = valeur


# --- commande simple -------------------------------------------------------

def _base(mot: str) -> str:
    return mot.rsplit("/", 1)[-1]


def _resoudre(base, d: str):
    if any(c in d for c in "$`*?"):
        return _INCONNU
    d = os.path.expanduser(d)
    if os.path.isabs(d):
        return Path(os.path.normpath(d))
    if base is _INCONNU:
        return _INCONNU
    return Path(os.path.normpath(os.path.join(base, d)))


def _sauter_options(mots: list[str], avec_valeur: set[str]) -> list[str]:
    i = 0
    while i < len(mots) and mots[i].startswith("-") and mots[i] != "-":
        if mots[i] == "--":
            return mots[i + 1:]
        i += 2 if mots[i] in avec_valeur else 1
    return mots[i:]


def _commande(mots: list[str], cwd, ctx: _Contexte, prof: int, indirect=False, developpe=False):
    env = {}
    while mots:
        w, b = mots[0], _base(mots[0])
        if _AFFECTATION.match(w):
            nom, _, val = w.partition("=")
            _exiger_hors_identite(nom.rstrip("+"))
            env[nom] = val
            mots = mots[1:]
        elif w in _MOTS_CLES:
            mots = mots[1:]
        elif b == "env":
            mots, i = mots[1:], 0
            while mots and mots[0].startswith("-"):
                _option_env(mots)
                if mots[0] in ("-S", "--split-string") and len(mots) > 1:
                    _analyser(" ".join(mots[1:]), cwd, ctx, prof + 1)
                    return cwd
                if mots[0] == "-C" and len(mots) > 1:
                    cwd = _resoudre(cwd, mots[1])
                mots = mots[2:] if mots[0] in ("-u", "-C", "-P") else mots[1:]
        elif b in ("sudo", "doas"):
            mots = _sauter_options(mots[1:], {"-u", "-g", "-h", "-p", "-C", "-D",
                                              "-r", "-t", "-U", "-T"})
        elif b in ("command", "builtin", "nohup", "exec", "caffeinate", "stdbuf",
                   "unbuffer", "chronic", "nice", "time", "watch"):
            if b == "exec" and any(a.startswith("-") and not a.startswith("--") and "c" in a
                                   for a in mots[1:2]):
                _exiger_hors_identite(VAR_AGENT)  # `exec -c` vide tout l'environnement
            mots = _sauter_options(mots[1:], {"-a", "-n", "-w", "-t", "-o"})
        elif b == "timeout":
            mots = _sauter_options(mots[1:], {"-s", "-k", "--signal", "--kill-after"})[1:]
        elif b == "parallel":
            if any(_base(x) == "tmux" for x in mots[1:]):
                raise _Refus(M_TMUX_FERME)
            break
        elif b == "xargs":
            indirect = True
            mots = _sauter_options(mots[1:], {"-I", "-L", "-n", "-P", "-s", "-E",
                                              "-d", "-a", "-R", "-S"})
        elif b == "rtk":
            mots = mots[1:]
            if mots and mots[0] == "proxy":
                raise _Refus(M_PROXY)
            if len(mots) > 1:  # `rtk err git push` : sous-commande rtk qui lance une commande
                _commande(mots[1:], cwd, ctx, prof)
        else:
            break
    if not mots:
        ctx.variables.update(env)  # `g=git` seul : la variable vaut pour la suite de la commande
        return cwd
    if not developpe:
        large = _developper(mots, ctx)
        if large != mots:  # jugée aussi avec ses variables remplacées (`g=git; $g push`)
            _commande(large, cwd, ctx, prof, indirect, developpe=True)
    if mots[0] in ctx.alias:  # `alias g=git` puis `g push` : jugée comme `git push`
        nom = mots[0]
        valeur = ctx.alias.pop(nom)  # un alias ne se développe pas dans lui-même
        try:
            _analyser(" ".join([valeur] + [shlex.quote(m) for m in mots[1:]]), cwd, ctx, prof + 1)
        finally:
            ctx.alias[nom] = valeur
        return cwd
    b, args = _base(mots[0]), mots[1:]

    for k, w in enumerate(mots[:-1]):
        if _INTERPRETE.match(_base(w)) and mots[k + 1] in ("-c", "-e", "-E", "-r") \
                and k + 2 < len(mots):
            _verifier_code(_base(w), mots[k + 2])
        if _INTERPRETE.match(_base(w)) and mots[k + 1] == "-m" and k + 2 < len(mots) \
                and mots[k + 2] in _CLIENTS_SQLITE:
            raise _Refus(M_SQLITE.format(client=f"{_base(w)} -m {mots[k + 2]}"))
    if _INTERPRETE.match(b):
        _script_interprete(args, cwd)
    if b in _CLIENTS_SQLITE or (b in _LANCEURS_CIME and any(
            _base(a) in _CLIENTS_SQLITE for a in args[:3])):
        raise _Refus(M_SQLITE.format(client=b))
    _verifier_identite_builtin(b, args)
    _ecritures(b, args, cwd)

    for appel in _appels_cime(b, args):
        _verifier_cime(appel, ctx)
    if b in ("cd", "pushd"):
        cible = [a for a in args if not a.startswith("-")]
        if not cible:
            return Path.home() if not args else _INCONNU
        return _resoudre(cwd, cible[0])
    if b == "popd":
        return _INCONNU
    if b == "security":
        raise _Refus(M_SECURITY)
    if b == "alias":
        _alias(args, ctx)
    elif b in _SHELLS:
        _shell(args, cwd, ctx, prof)
    elif b in ("source", "."):
        if args:
            _script(args[0], cwd, ctx, prof)
    elif b == "eval":
        _analyser(" ".join(args), cwd, ctx, prof + 1)
    elif b == "git":
        _git(args, cwd, env, ctx, prof)
    elif b == "tmux":
        raise _Refus(M_TMUX_FERME)
    elif b == "find":
        racines = []
        for a in args:
            if a.startswith(("-", "(", "!")):
                break
            racines.append(a)
        if "-delete" in args:
            _ecrit("find -delete", racines, cwd)
        for k, a in enumerate(args):
            if a in ("-exec", "-execdir", "-ok", "-okdir") and k + 1 < len(args) \
                    and (_base(args[k + 1]) in _ECRIT_TOUS | _ECRIT_DESTINATION):
                _ecrit(f"find -exec {_base(args[k + 1])}", racines, cwd)
        for k, a in enumerate(args):
            if a in ("-exec", "-execdir", "-ok", "-okdir"):
                fin = next((j for j in range(k + 1, len(args))
                            if args[j] in (";", _SEP, "+")), len(args))
                if fin > k + 1:
                    _commande(args[k + 1:fin], cwd, ctx, prof, indirect=True)
    elif "/" in mots[0]:
        _script(mots[0], cwd, ctx, prof, shebang=True)
    return cwd


def _shell(args, cwd, ctx, prof):
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-o", "+o", "-O", "+O"):
            i += 2
            continue
        if a.startswith("-") and not a.startswith("--") and "c" in a[1:]:
            reste = [x for x in args[i + 1:] if not x.startswith("-")]
            if reste:
                _analyser(reste[0], cwd, ctx, prof + 1)
            return
        if a == "<<<" and i + 1 < len(args):
            _analyser(args[i + 1], cwd, ctx, prof + 1)
            return
        if not a.startswith(("-", "+")):
            _script(a, cwd, ctx, prof)
            return
        i += 1
    _repli(_lu_par_un_shell(ctx.texte))  # le shell lit son entrée : on ne voit que le texte


def _lu_par_un_shell(texte: str) -> str:
    """Tout ce qu'un shell qui lit son entrée pourrait exécuter : la commande et chacun de ses
    corps de heredoc, lus comme du shell, sans leurs commentaires."""
    reste, corps = _heredocs(sans_commentaires(texte))
    return "\n".join([reste] + [sans_commentaires(c) for c, *_ in corps])


def _script(chemin, cwd, ctx, prof, shebang=False):
    p = _resoudre(cwd, chemin)
    try:
        if p is _INCONNU or not p.is_file() or p.stat().st_size > 256_000:
            return
        texte = p.read_text(errors="replace")
    except OSError:
        return
    if shebang and not re.match(r"#!.*\b(ba|z|da|k)?sh\b", texte):
        return
    _analyser(texte, cwd, ctx, prof + 1)


# --- git -------------------------------------------------------------------

def _git(args, cwd, env, ctx, prof):
    opts_git, alias = [], {}
    i = 0
    while i < len(args):
        a = args[i]
        if a == "-C" and i + 1 < len(args):
            cwd = _resoudre(cwd, args[i + 1])
            i += 2
        elif a == "-c" and i + 1 < len(args):
            cle, _, val = args[i + 1].partition("=")
            if cle.lower().startswith("alias."):
                alias[cle[6:]] = val
            i += 2
        elif a in ("--git-dir", "--work-tree") and i + 1 < len(args):
            opts_git.append(f"{a}={args[i + 1]}")
            i += 2
        elif a in ("--namespace", "--super-prefix", "--config-env"):
            i += 2
        elif a.startswith(("--git-dir=", "--work-tree=")):
            opts_git.append(a)
            i += 1
        elif a.startswith("-"):
            i += 1
        else:
            break
    if i >= len(args):
        return
    sub, reste = args[i], args[i + 1:]
    if sub in alias:
        val = alias[sub]
        if val.startswith("!"):
            _analyser(val[1:], cwd, ctx, prof + 1)
            return
        mots = shlex.split(val)
        if not mots:
            return
        sub, reste = mots[0], mots[1:] + reste
    _git_sous_commande(sub, reste, cwd, env, opts_git, ctx, prof)


def _positionnels(reste):
    return [a for a in reste if not a.startswith("-")]


def _supprime_une_branche(reste: list[str]) -> bool:
    """Les arguments de `git branch` demandent-ils une suppression (`-d`, `-D`, `--delete`) ?"""
    for a in reste:
        if a == "--":
            break
        if a.startswith("--"):
            if len(a) >= 3 and "--delete".startswith(a):
                return True
        elif a.startswith("-") and ("d" in a or "D" in a):
            return True
    return False


def _options_branch(reste: list[str]) -> tuple[bool, bool]:
    """(force, déplace) de `git branch` : `-f`, `-M`, `-C` (groupés ou non) et `--force` (abrégé) écrasent
    une branche ; `-m`, `-M` et `--move` (abrégé) la renomment."""
    force = deplace = False
    for a in reste:
        if a == "--":
            break
        if a.startswith("--"):
            nom = a.split("=", 1)[0]
            force = force or (len(nom) >= 3 and "--force".startswith(nom))
            deplace = deplace or (len(nom) >= 4 and "--move".startswith(nom))
        elif a.startswith("-") and a != "-":
            force = force or any(c in "fMC" for c in a[1:])
            deplace = deplace or any(c in "mM" for c in a[1:])
    return force, deplace


def _sans_valeur_de_m(reste: list[str]) -> list[str]:
    """`reste` sans la valeur qui suit `-m` (le message de `git update-ref -m <msg> <ref> …`)."""
    return [a for k, a in enumerate(reste) if not (k and reste[k - 1] == "-m")]


def _git_sous_commande(sub, reste, cwd, env, opts_git, ctx, prof):
    if sub in ("push", "send-pack") or (sub in ("subtree", "lfs") and "push" in reste):
        raise _Refus(M_PUSH)
    if sub == "branch":
        if _supprime_une_branche(reste):
            raise _Refus(M_BRANCHE)
        pos = _positionnels(reste)
        force, deplace = _options_branch(reste)
        if force and set(pos) & ctx.refs:
            raise _Refus(M_REF)
        if deplace and (pos[:1] and pos[0] in ctx.refs or
                        len(pos) == 1 and _depot_principal(cwd, env, opts_git, ctx)):
            raise _Refus(M_REF)   # renommer la référence libère son nom pour une création ordinaire
    elif sub == "update-ref":
        pos = _positionnels(_sans_valeur_de_m(reste))
        if "--stdin" in reste:
            raise _Refus(M_BRANCHE)
        if "-d" in reste and any(p.startswith("refs/heads/") for p in pos):
            raise _Refus(M_BRANCHE)
        if pos and pos[0] in {f"refs/heads/{r}" for r in ctx.refs}:
            raise _Refus(M_REF)
        if pos and pos[0] == "HEAD" and _depot_principal(cwd, env, opts_git, ctx):
            raise _Refus(M_REF)
    elif sub == "fetch":
        for p in _positionnels(reste):
            dst = p.partition(":")[2].removeprefix("refs/heads/")
            if dst in ctx.refs:
                raise _Refus(M_REF)
    elif sub == "config":
        pos = _positionnels(reste)
        if len(pos) >= 2 and pos[0].lower().startswith("alias."):
            val = pos[1]
            if val.startswith("!"):
                _analyser(val[1:], cwd, ctx, prof + 1)
            else:
                mots = shlex.split(val)
                if mots:
                    _git_sous_commande(mots[0], mots[1:], cwd, env, opts_git, ctx, prof)
    elif sub == "submodule" and "foreach" in reste:
        k = reste.index("foreach")
        _analyser(" ".join(_sauter_options(reste[k + 1:], set())), cwd, ctx, prof + 1)
    elif sub == "bisect" and reste[:1] == ["run"]:
        _commande(reste[1:], cwd, ctx, prof)
    if sub in ("mv", "rm"):
        _ecrit(f"git {sub}", _positionnels(reste), cwd)
    if sub == "rebase":
        for k, a in enumerate(reste[:-1]):
            if a in ("-x", "--exec"):
                _analyser(reste[k + 1], cwd, ctx, prof + 1)
    if sub in _FUSION:
        _fusion(sub, reste, cwd, env, opts_git, ctx)
    if sub == "commit":
        _commit(reste, cwd, env, opts_git, ctx)
    if (ctx.agent or "").startswith("coord-"):
        _coordinateur(sub, reste, cwd, env, opts_git, ctx)


def _fusion(sub, reste, cwd, env, opts_git, ctx):
    if sub in ("checkout", "switch") and not set(_positionnels(reste)) & ctx.refs:
        return
    if cwd is _INCONNU and not opts_git:
        raise _Refus(M_INCONNU.format(sub=sub))
    if sub == "merge":
        env = _env_effectif(env)
        _cible_merge(cwd, env, opts_git, ctx)
    if not _depot_principal(cwd, env, opts_git, ctx):
        return
    if sub == "merge" and ctx.agent == ASSISTANT and _MERGE_CONTINUITE & set(reste):
        return   # abandonner une fusion ne fusionne rien
    if ctx.agent == ASSISTANT and sub in _FUSION_PAR_LA_FILE:
        raise _Refus(M_FILE.format(sub=sub))
    if sub == "merge" and _role(ctx):
        raise _Refus(M_FUSION_MERGE)
    raise _Refus(M_FUSION.format(sub=sub))


def _commit(reste, cwd, env, opts_git, ctx) -> None:
    """`git commit` dans le dépôt principal : ordinaire permis ; refusé s'il réécrit la pointe de la
    référence (`--amend`) ou s'il achève une fusion en cours (`MERGE_HEAD`)."""
    amende = _option_commit_interdite(reste, ("--amend",)) is not None
    if cwd is _INCONNU and not opts_git:
        if amende:
            raise _Refus(M_INCONNU.format(sub="commit"))
        return
    gitdir, branche = _etat_depot(cwd, _env_effectif(env), opts_git)
    if gitdir is None:
        if amende:
            raise _Refus(M_INCONNU.format(sub="commit"))
        return
    if not _depot_principal(cwd, env, opts_git, ctx):
        return
    if amende and branche in ctx.refs:
        raise _Refus(M_COMMIT_REECRIT)
    if (gitdir / "MERGE_HEAD").exists():
        raise _Refus(M_COMMIT_FUSION)


def _juger_fusion(ctx, ref: str, sans_annonce: bool = False, sha: str | None = None) -> None:
    """La voie de la fusion de `ref` (inscrite dans `ctx.voies`, et `ctx.auto` pour "auto"), ou
    `_Refus` avec ce qui manque. `sha` : la pointe déjà figée par l'appelant, jugée à la place de
    celle que `ref` désigne maintenant."""
    motif = _motif_accord_fusion(ctx, ref, sha)
    if motif is None:
        ctx.voies[ref] = "accord"
        return
    auto, complement = _voie_auto(ctx, ref, sans_annonce, sha)
    if auto is None:
        raise _Refus(motif + complement)
    ctx.voies[ref] = "auto"
    ctx.auto[ref] = auto


def juger_fusion(projet: Path, ref: str, sha: str | None = None) -> tuple[str | None, dict, str | None]:
    """Les règles qui s'appliquent à un `git merge <ref>` de l'Assistant, pour une commande qui
    fusionne elle-même : `(voie, détails, None)` si la fusion est permise, `(None, {}, motif)` sinon.
    `voie` : "accord" (un accord de l'utilisateur non consommé vise la pointe) ou "auto" (option
    « Fusions automatiques ») ; pour "auto", `détails` porte `equipe`, `sha`, `reglage`, `fichiers`
    et `annonce` à None : la commande l'inscrit elle-même, juste avant de fusionner. `sha` : la
    pointe de `ref` figée par l'appelant, jugée même si la branche a avancé depuis. Ne consomme
    rien. Ne lève jamais : toute erreur de lecture est un refus."""
    try:
        ctx = _Contexte({}, projet)
        ctx.agent = ASSISTANT
        if ctx.projet is None:
            return None, {}, "le projet n'est pas lisible"
        _juger_fusion(ctx, ref, sans_annonce=True, sha=sha)
        return ctx.voies[ref], dict(ctx.auto.get(ref, {})), None
    except _Refus as r:
        return None, {}, str(r)
    except Exception as e:
        return None, {}, f"les règles de fusion ne se lisent pas ({type(e).__name__} : {e})"


_HISTOIRE_COORD = {"checkout", "switch", "stash", "restore", "reset"}
# options courtes de `git commit` dont la valeur suit (ou est collée) : on ne cherche plus `-n` après
_COMMIT_VALEUR = set("mFcCtSu")


def _option_commit_interdite(reste: list[str],
                             cherche: tuple = ("--amend", "--no-verify")) -> str | None:
    """`--amend` ou `--no-verify` (sous toutes leurs abréviations, `-n` compris) dans un `git commit` ;
    `cherche` restreint aux options demandées."""
    for a in reste:
        if a == "--":
            break
        if a.startswith("--"):
            nom = a.split("=", 1)[0]
            if "--amend" in cherche and len(nom) >= 4 and "--amend".startswith(nom):
                return "--amend"
            if "--no-verify" in cherche and len(nom) >= 6 and "--no-verify".startswith(nom):
                return "--no-verify"
        elif a.startswith("-") and a != "-":
            for c in a[1:]:
                if c == "n" and "--no-verify" in cherche:
                    return "--no-verify"
                if c in _COMMIT_VALEUR:
                    break
    return None


def _worktree_de_l_equipe(ctx):
    """Le worktree de l'équipe du coordinateur (`coord-<équipe>`), ou None s'il ne se calcule pas."""
    if ctx.manifeste is None or ctx.projet is None:
        return None
    from cime.fondation.projet import worktree_equipe
    return worktree_equipe(ctx.projet, ctx.manifeste, ctx.agent[len("coord-"):])


def _coordinateur(sub, reste, cwd, env, opts_git, ctx):
    """Le droit de commit d'un coordinateur : `git add` et `git commit` dans le worktree de SON
    équipe, jamais ailleurs (dépôt principal, worktree d'une autre équipe, `cd` ailleurs) ; ni
    `--amend` ni `--no-verify` ; ni checkout, switch, stash, restore, reset, où que ce soit."""
    if sub in _HISTOIRE_COORD:
        raise _Refus(M_COORD_HISTOIRE.format(sub=sub))
    if sub not in ("add", "commit"):
        return
    if sub == "commit":
        option = _option_commit_interdite(reste)
        if option:
            raise _Refus(M_COORD_REECRITURE.format(option=option))
    worktree = _worktree_de_l_equipe(ctx)
    if worktree is None:   # projet inconnu : rien à comparer, la décision n'est pas la garde du périmètre
        return
    env = _env_effectif(env)
    if opts_git or any(k in env for k in ("GIT_DIR", "GIT_WORK_TREE")):
        raise _Refus(M_COORD_DETOURNE.format(sub=sub, worktree=worktree))
    if cwd is _INCONNU:
        raise _Refus(M_INCONNU.format(sub=sub))
    try:
        dedans = Path(cwd).resolve().is_relative_to(worktree.resolve())
    except OSError:
        dedans = False
    if not dedans:
        raise _Refus(M_COORD_COMMIT.format(worktree=worktree, cible=f"visé : {cwd}"))


def _env_effectif(env: dict) -> dict:
    """Variables GIT_DIR / GIT_WORK_TREE qui s'appliqueront au `git` : celles que la commande
    pose elle-même, sinon celles de l'environnement de l'agent (que le hook reçoit aussi)."""
    base = {k: os.environ[k] for k in ("GIT_DIR", "GIT_WORK_TREE") if k in os.environ}
    return {**base, **env}


def _cible_merge(cwd, env, opts_git, ctx) -> None:
    """Un `git merge` dont le dépôt ne se résout pas est refusé à tous. Un dépôt désigné
    autrement que par son dossier (GIT_DIR, GIT_WORK_TREE, --git-dir, --work-tree) n'est
    permis que s'il s'agit du dépôt principal : le garde ne juge pas les autres."""
    gitdir, _ = _etat_depot(cwd, env, opts_git)
    if gitdir is None:
        raise _Refus(M_INCONNU.format(sub="merge"))
    detourne = any(k in env for k in ("GIT_DIR", "GIT_WORK_TREE")) or \
        any(o.startswith(("--git-dir", "--work-tree")) for o in opts_git)
    if detourne and (ctx.projet is None or gitdir != (ctx.projet / ".git").resolve()):
        raise _Refus(M_DETOURNE)


def _depot_principal(cwd, env, opts_git, ctx) -> bool:
    """Vrai si la commande vise le dépôt principal (dossier, branche de référence ou .git)."""
    if ctx.projet is not None and cwd is not _INCONNU and not opts_git:
        try:
            if Path(cwd).resolve() == ctx.projet:
                return True
        except OSError:
            pass
    gitdir, branche = _etat_depot(cwd, env, opts_git)
    if branche in ctx.refs:
        return True
    return ctx.projet is not None and gitdir is not None and \
        gitdir == (ctx.projet / ".git").resolve()


def _refs_merge(reste: list[str]) -> list[str]:
    """Branches nommées par `git merge` (options à valeur sautées). Vide pour --abort,
    --continue, --quit. Sans branche nommée, la fusion n'est pas permise à l'Assistant."""
    if _MERGE_CONTINUITE & set(reste):
        return []
    refs, i = [], 0
    while i < len(reste):
        a = reste[i]
        i += 1
        if a == "--":
            refs += reste[i:]
            break
        if a in _MERGE_VALEUR:
            i += 1
        elif a.startswith("-") and a != "-":
            continue
        else:
            refs.append(a)
    if not refs:
        raise _Refus(M_FUSION_SANS_CIBLE)
    return refs


def _etat_depot(cwd, env, opts_git):
    """(dossier git absolu, branche courante) du dépôt visé : un seul sous-processus."""
    env_proc = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for k in ("GIT_DIR", "GIT_WORK_TREE"):
        if k in env:
            env_proc[k] = env[k]
    try:
        r = subprocess.run(
            ["git", *opts_git, "rev-parse", "--absolute-git-dir", "--abbrev-ref", "HEAD"],
            cwd=cwd if cwd is not _INCONNU else None, env=env_proc,
            capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return None, None
    lignes = r.stdout.split("\n")
    if r.returncode != 0 or len(lignes) < 2:
        return None, None
    return Path(lignes[0]).resolve(), lignes[1]


# --- identité : variables que nulle commande ne touche ----------------------------------

def _exiger_hors_identite(nom: str) -> None:
    if nom in PROTEGEES:
        raise _Refus(M_IDENTITE.format(nom=nom))


def _option_env(mots: list[str]) -> None:
    """Option d'`env` qui retire une variable protégée ou vide tout l'environnement."""
    o = mots[0]
    suivant = mots[1] if len(mots) > 1 else ""
    if o in ("-i", "--ignore-environment", "-") or \
            (not o.startswith("--") and o[1:2] not in ("S", "C", "P", "u") and "i" in o[1:]):
        raise _Refus(M_IDENTITE.format(nom="l'environnement (env -i)"))
    if o == "-u" or o == "--unset":
        _exiger_hors_identite(suivant)
    elif o.startswith("--unset="):
        _exiger_hors_identite(o.partition("=")[2])
    elif o.startswith("-u") and len(o) > 2:
        _exiger_hors_identite(o[2:])


def _verifier_identite_builtin(b: str, args: list[str]) -> None:
    """`unset`, `export`, `declare`… nommant une variable protégée ; `-p` (affichage) permis."""
    if b == "unset":
        for a in args:
            _exiger_hors_identite(a)
    elif b in ("export", "declare", "typeset", "local", "readonly"):
        if any(a.startswith("-") and not a.startswith("--") and "p" in a for a in args):
            return
        for a in args:
            if not a.startswith("-"):
                _exiger_hors_identite(a.partition("=")[0].rstrip("+"))
    elif b == "read":
        for a in args:
            _exiger_hors_identite(a)
    elif b == "printf":
        for k, a in enumerate(args[:-1]):
            if a == "-v":
                _exiger_hors_identite(args[k + 1])


def _identite_code(code: str) -> None:
    """Code d'un interpréteur (`python -c`, script, heredoc) qui écrit l'environnement en
    nommant une variable protégée. Lire `os.environ["CIME_AGENT"]` reste permis."""
    if any(nom in code for nom in PROTEGEES) and _ECRIT_ENVIRON.search(code):
        raise _Refus(M_IDENTITE.format(nom=next(n for n in PROTEGEES if n in code)))


_CODE_OU_MODULE = set("mceE")  # `-m pytest`, `-c code`, `-e code` : la suite leur appartient
_OPTION_A_VALEUR = set("WXr")   # `-W ignore`, `-X dev`, `-r json` : valeur collée ou au mot suivant


def _script_interprete(args: list[str], cwd) -> None:
    """`python script.py` : le script est lu avec la même règle d'identité. Après `-m <module>`, `-c <code>` ou `-e <code>`, les mots qui suivent sont les
    arguments du module ou du code (`python -m pytest tests/x.py`) : aucun script à lire."""
    k = 0
    while k < len(args):
        a = args[k]
        if a.startswith("-") and not a.startswith("--") and len(a) > 1:
            for j, lettre in enumerate(a[1:]):  # options courtes groupées : `-Bm`, `-Wignore`
                if lettre in _CODE_OU_MODULE:
                    return
                if lettre in _OPTION_A_VALEUR:
                    k += j == len(a) - 2  # valeur au mot suivant
                    break
            k += 1
        elif a.startswith("-"):
            k += 1
        else:
            p = _resoudre(cwd, a)
            try:
                if p is not _INCONNU and p.is_file() and p.stat().st_size <= 256_000:
                    _identite_code(p.read_text(errors="replace"))
            except OSError:
                pass
            return


# --- fusion sous accord de l'utilisateur --------------------------------------------------

def _sha_pointe(ctx, ref: str) -> str | None:
    if ref.startswith("-") or ctx.projet is None:
        return None
    try:
        r = subprocess.run(["git", "-C", str(ctx.projet), "rev-parse", "--verify",
                            f"{ref}^{{commit}}"], capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return None
    sha = r.stdout.strip()
    return sha if r.returncode == 0 and sha else None


def accords_fusion_libres(projet: Path) -> list[tuple[int, str]]:
    """(id, sha) des `accord` de l'utilisateur →Assistant `objet=fusion:<é>:<sha>` non consommés
    (sans transition `clos`). Lève en cas de registre illisible."""
    chemin = Path(projet) / ".orga" / "etat" / "registre.sqlite"
    if not chemin.exists():  # pas encore de registre : aucun accord, et rien à consommer
        return []
    conn = sqlite3.connect(f"{chemin.resolve().as_uri()}?mode=ro", uri=True, timeout=2)
    try:
        lignes = conn.execute(
            "SELECT m.id, m.objet FROM messages m WHERE m.nature = 'accord' AND m.de = 'utilisateur'"
            " AND m.a = 'assistant' AND m.objet LIKE 'fusion:%' AND NOT EXISTS ("
            "SELECT 1 FROM transitions t WHERE t.message_id = m.id AND t.etat = 'clos')"
            " ORDER BY m.id").fetchall()
    finally:
        conn.close()
    return [(i, objet.rsplit(":", 1)[-1]) for i, objet in lignes]


def accord_pour(sha: str, libres: list[tuple[int, str]]) -> int | None:
    """Premier accord libre qui vise exactement cette pointe (sha complet ou abrégé ≥ 7)."""
    return next((i for i, a in libres if len(a) >= 7 and sha.startswith(a)), None)


def _motif_accord_fusion(ctx, ref: str, sha_fige: str | None = None) -> str | None:
    """None si un accord de l'utilisateur non consommé vise la pointe actuelle de `ref` (ou
    `sha_fige`, quand l'appelant l'a figée)."""
    sha = sha_fige or _sha_pointe(ctx, ref)
    if sha is None:
        return M_ACCORD_FUSION.format(ref=ref, sha="?", sha_complet="<sha>",
                                      cause="la branche ne se résout pas dans le dépôt principal")
    if ctx.projet is None:
        return M_ACCORD_FUSION.format(ref=ref, sha=sha[:10], sha_complet=sha,
                                      cause="le projet n'est pas lisible")
    try:
        libres = accords_fusion_libres(ctx.projet)
    except Exception:
        return M_ACCORD_FUSION.format(ref=ref, sha=sha[:10], sha_complet=sha,
                                      cause="le registre est illisible")
    accord = accord_pour(sha, [(i, a) for i, a in libres if i not in ctx.accords_utilises])
    if accord is not None:
        ctx.accords_utilises.append(accord)
        return None
    cause = ("aucun accord pour ce sha (la branche a avancé depuis l'accord ?)" if libres
             else "aucun accord de l'utilisateur non consommé")
    return M_ACCORD_FUSION.format(ref=ref, sha=sha[:10], sha_complet=sha, cause=cause)


# --- fusion automatique (option de l'utilisateur) ---------------------------

_DELAI_GIT = 5
_CONDITIONS = {1: "branche d'équipe", 2: "chemins réservés", 3: "fusion sans conflit",
               4: "annonce de l'Assistant", 5: "liste des chemins réservés inchangée"}


class _EchecAuto(Exception):
    def __init__(self, n: int, cause: str):
        super().__init__(cause)
        self.n, self.cause = n, cause


@contextmanager
def _condition(n: int):
    """Toute erreur de lecture (git, registre, manifeste, délai) fait échouer la condition."""
    try:
        yield
    except _EchecAuto:
        raise
    except Exception as e:
        raise _EchecAuto(n, f"lecture impossible ({type(e).__name__} : {e})") from None


def _git_auto(ctx, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ctx.projet), *args], capture_output=True,
                          text=True, timeout=_DELAI_GIT)


def _equipe_de_la_branche(ctx, ref: str) -> str | None:
    motif = re.escape(ctx.manifeste.branche_equipe).replace(r"\{equipe\}", "(?P<equipe>[a-z0-9-]+)")
    m = re.fullmatch(motif, ref)
    return m.group("equipe") if m and "equipe" in m.groupdict() else None


def _annonce(ctx, equipe: str, sha: str) -> int | None:
    chemin = ctx.projet / ".orga" / "etat" / "registre.sqlite"
    if not chemin.exists():
        return None
    conn = sqlite3.connect(f"{chemin.resolve().as_uri()}?mode=ro", uri=True, timeout=2)
    try:
        lignes = conn.execute(
            "SELECT id, objet FROM messages WHERE nature = 'rapport_utilisateur' AND de = 'assistant'"
            " AND a = 'utilisateur' AND objet LIKE 'fusion-auto:%' ORDER BY id DESC").fetchall()
    finally:
        conn.close()
    for ident, objet in lignes:
        morceaux = objet.split(":")
        if len(morceaux) == 3 and morceaux[1] == equipe and len(morceaux[2]) >= 7 \
                and sha.startswith(morceaux[2]):
            return ident
    return None


def _voie_auto(ctx, ref: str, sans_annonce: bool = False,
               sha_fige: str | None = None) -> tuple[dict | None, str]:
    """(détails, "") si la fusion de `ref` passe par l'option « Fusions automatiques » ; sinon
    (None, complément du message de refus) — "" quand l'option n'est pas active. Jamais de
    laissez-passer sur erreur. `sans_annonce` : la condition 4 est laissée à l'appelant, qui
    annonce lui-même la fusion juste avant de la faire (`annonce` vaut alors None). `sha_fige` :
    la pointe jugée, à la place de celle de la branche d'aujourd'hui."""
    if ctx.projet is None or ctx.manifeste is None:
        return None, ""
    etat = fusions_auto.etat_courant(ctx.projet)
    if not etat["active"]:
        return None, ""
    sha, equipe = None, None
    try:
        with _condition(1):
            equipe = _equipe_de_la_branche(ctx, ref)
            if equipe is None:
                raise _EchecAuto(1, f"{ref} n'est pas une branche d'équipe "
                                    f"({ctx.manifeste.branche_equipe})")
            sha = _sha_pointe(ctx, f"refs/heads/{ref}")
            if sha is None or (sha_fige is None and sha != _sha_pointe(ctx, ref)):
                raise _EchecAuto(1, f"{ref} ne désigne pas, sans ambiguïté, la branche de ce nom")
            sha = sha_fige or sha
            cible = sha_fige or ref
        with _condition(2):
            actuelle = fusions_auto.chemins_reserves(ctx.projet)
            liste = actuelle + [e for e in etat["reserves"] if e not in actuelle]
            reference = ctx.manifeste.branche_reference
            base = _git_auto(ctx, "merge-base", reference, cible)
            if base.returncode != 0 or not base.stdout.strip():
                raise _EchecAuto(2, "aucune base commune avec la branche de référence")
            diff = _git_auto(ctx, "diff", "--name-only", "--no-renames", "-z",
                             base.stdout.strip(), cible)
            if diff.returncode != 0:
                raise _EchecAuto(2, "la différence ne se calcule pas")
            fichiers = [c for c in diff.stdout.split("\0") if c]
            touches = [c for c in fichiers if fusions_auto.est_reserve(c, liste)]
            if touches:
                raise _EchecAuto(2, "la branche touche " + ", ".join(touches[:3])
                                 + (" …" if len(touches) > 3 else ""))
        with _condition(3):
            tete = _git_auto(ctx, "symbolic-ref", "--short", "HEAD")
            if tete.returncode != 0 or tete.stdout.strip() != reference:
                raise _EchecAuto(3, f"le dépôt principal n'est pas sur {reference}")
            essai = _git_auto(ctx, "merge-tree", "--write-tree", reference, cible)
            if essai.returncode != 0:
                raise _EchecAuto(3, "la fusion a des conflits (ou l'essai échoue)")
        with _condition(4):
            annonce = None if sans_annonce else _annonce(ctx, equipe, sha)
            if annonce is None and not sans_annonce:
                raise _EchecAuto(4, f"aucun rapport_utilisateur de l'Assistant "
                                    f"`fusion-auto:{equipe}:{sha[:10]}` pour cette pointe")
        with _condition(5):
            if etat["suspendue"]:
                raise _EchecAuto(5, "la liste des chemins réservés a changé depuis l'activation ; "
                                    "L'utilisateur doit réactiver l'option")
    except _EchecAuto as e:
        complement = M_AUTO_REFUSEE.format(ref=ref, n=e.n, nom=_CONDITIONS[e.n], cause=e.cause)
        if e.n == 4:
            complement += M_AUTO_ANNONCE.format(equipe=equipe, sha=sha)
        return None, complement
    return {"equipe": equipe, "sha": sha, "annonce": annonce, "reglage": etat["reglage_id"],
            "fichiers": len(fichiers)}, ""


# --- fichiers d'état réservés aux commandes ------------------------------------------------

def _ecrit(verbe: str, chemins: list[str], cwd) -> None:
    """Refuse l'écriture d'un fichier réservé (CLOTUREE, tasks/in-progress/, tasks/done/,
    registre.sqlite). La lecture n'est jamais passée ici."""
    for brut in chemins:
        if not brut or brut == "-" or brut.startswith(("&", "/dev/")):
            continue
        candidats = [os.path.normpath(os.path.expanduser(brut))]
        resolu = _resoudre(cwd, brut)
        if resolu is not _INCONNU:
            candidats.append(os.path.realpath(resolu))
        for c in candidats:
            motif = perimetre.motif_reserve(c)
            if motif:
                raise _Refus(M_ECRITURE_RESERVEE.format(motif=motif, verbe=verbe, chemin=brut))


def _ecritures(b: str, args: list[str], cwd) -> None:
    pos = [a for a in args if not a.startswith("-") or a == "-"]
    if b in _ECRIT_TOUS:
        _ecrit(b, pos, cwd)
    elif b in _ECRIT_DESTINATION:
        cibles = pos[-1:]
        for k, a in enumerate(args):
            if a in ("-t", "--target-directory") and k + 1 < len(args):
                cibles.append(args[k + 1])
            elif a.startswith("--target-directory="):
                cibles.append(a.partition("=")[2])
        _ecrit(b, cibles, cwd)
    elif b == "dd":
        _ecrit(b, [a[3:] for a in args if a.startswith("of=")], cwd)
    elif b == "sed" and any((a.startswith("-") and not a.startswith("--") and "i" in a)
                            or a.startswith("--in-place") for a in args):
        _ecrit("sed -i", pos, cwd)


# --- cime ------------------------------------------------------------------

_LANCEURS_CIME = {"uv", "uvx", "parallel"}  # `uv run cime`, `uvx cime`, `parallel cime`


def _appels_cime(b: str, args: list[str]) -> list[list[str]]:
    """Arguments qui suivent chaque `cime` que la commande invoque : nom de base, chemin
    (`/chemin/cime`), derrière un lanceur (`python -m cime`, `uv run cime`). Une commande
    qui ne le désigne pas n'a pas d'appel."""
    if b == NOM:
        return [args]
    if b in _LANCEURS_CIME or _INTERPRETE.match(b):
        return [args[k + 1:] for k, a in enumerate(args) if _base(a) == NOM]
    return []


def _verifier_cime(args: list[str], ctx) -> None:
    """Un worker ne lance aucun agent ; un coordinateur ne lance que les workers de son équipe.
    Les autres sous-commandes de cime ne sont pas touchées ici."""
    role = _role(ctx)
    if role is None or not args:
        return
    if args[0].startswith("-"):  # sous-commande pas trouvée avec certitude
        raise _Refus(M_CIME_OPTION)
    if args[0] == "fusionner":
        raise _Refus(M_FUSIONNER)
    if args[0] != "lancer":
        return
    if role == "worker":
        raise _Refus(M_LANCER_WORKER)
    equipe = ctx.agent[len("coord-"):]
    if args[1:3] == ["worker", "integration"]:   # lancer.EQUIPE_INTEGRATION, sans importer lancer ici
        raise _Refus(M_LANCER_INTEGRATION.format(equipe=equipe))
    if args[1:3] != ["worker", equipe]:
        raise _Refus(M_LANCER_COORD)


def _role(ctx) -> str | None:
    """Rôle soumis à la liste fermée tmux : `worker` ou `coord`, sinon None."""
    for role in ("worker", "coord"):
        if (ctx.agent or "").startswith(f"{role}-"):
            return role
    return None
