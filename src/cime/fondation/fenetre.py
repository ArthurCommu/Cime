"""Reconnaissance d'une fenêtre de choix de Claude Code, à partir d'une capture de tmux.

Une fenêtre de choix (demande d'autorisation, écran de confiance, question à choix…) prend la place
de l'invite de saisie et attend une réponse que seul un humain donne. Elle se reconnaît à sa
structure, jamais au texte d'un outil : des options dont l'une porte le curseur `❯`, un pied de
fenêtre qui dit comment annuler, et pas de zone de saisie. Une capture où la zone de saisie existe
n'est jamais une fenêtre : ce qui s'y tape est une saisie.

Module pur : une capture en entrée, rien d'écrit, rien de tapé.
"""
import re

from cime.fondation import invite

LONGUEUR_QUESTION = 300
# pied de fenêtre : `Esc to cancel`, ou `(esc)` au bout de la dernière option (« 3. No, and tell Claude
# what to do differently (esc) » : certaines demandes n'ont pas de ligne de pied)
_PIED = re.compile(r"Esc to (?:cancel|exit)|\(esc\)\s*$")
_DERNIERES_LIGNES = 6
_OPTION = re.compile(r"^\s*(?P<curseur>❯[ \xa0]+)?(?:(?P<n>\d+)\.[ \xa0]+)?(?P<texte>\S.*)$")
_NUMEROTEE = re.compile(r"^\s*(?:❯[ \xa0]+)?(\d+)\.[ \xa0]+(\S.*)$")
_CURSEUR = re.compile(r"^\s*❯[ \xa0]+\S")
_REGLE_PLEINE = re.compile(r"[─━]{10,}")
_BORDURES = re.compile(r"[─╌│━]")
# un marqueur de l'historique de la conversation : ce qui le précède n'est pas dans la fenêtre
_HISTORIQUE = ("⏺", "⎿", "✻", "❯")


def _lignes(capture: str) -> list[str]:
    return [invite._brut(ligne).rstrip() for ligne in capture.split("\n")]


def _pied(lignes: list[str]) -> int | None:
    """Indice du pied de fenêtre (`Esc to cancel`/`Esc to exit`, ou option terminée par `(esc)`) parmi les
    dernières lignes non vides."""
    non_vides = [i for i, ligne in enumerate(lignes) if ligne.strip()]
    for i in reversed(non_vides[-_DERNIERES_LIGNES:]):
        if _PIED.search(lignes[i]):
            return i
    return None


def _options_numerotees(lignes: list[str], pied: int) -> list[int]:
    """Indices de la dernière série `1.`, `2.`… avant le pied ; vide s'il n'y en a pas au moins deux."""
    serie: list[int] = []
    for i in range(pied):
        m = _NUMEROTEE.match(lignes[i])
        if m is None:
            continue
        if int(m.group(1)) == 1:
            serie = [i]
        elif serie and int(m.group(1)) == len(serie) + 1:
            serie.append(i)
    return serie if len(serie) >= 2 else []


def _options_sans_numero(lignes: list[str], pied: int) -> list[int]:
    """Indices du bloc de lignes contiguës, au moins deux, qui contient la dernière ligne à curseur
    (les écrans de confiance et d'imports listent leurs choix sans numéro)."""
    curseur = [i for i in range(pied) if _CURSEUR.match(lignes[i]) and not _NUMEROTEE.match(lignes[i])]
    if not curseur:
        return []
    haut = bas = curseur[-1]
    while haut > 0 and lignes[haut - 1].strip() and not _REGLE_PLEINE.fullmatch(lignes[haut - 1].strip()):
        haut -= 1
    while bas + 1 < pied and lignes[bas + 1].strip():
        bas += 1
    return list(range(haut, bas + 1)) if bas > haut else []


def _libelle(ligne: str) -> str:
    m = _OPTION.match(ligne)
    return re.sub(r"\s+", " ", m.group("texte")).strip() if m else ligne.strip()


def _debut_de_fenetre(lignes: list[str], premiere: int) -> int:
    """Première ligne de la fenêtre : après la dernière règle pleine ou le dernier marqueur d'historique
    qui précèdent la première option."""
    for i in range(premiere - 1, -1, -1):
        brut = lignes[i].strip()
        if _REGLE_PLEINE.fullmatch(brut):
            return i + 1
        if brut.startswith(_HISTORIQUE):
            return i + 1
    return 0


def _question(lignes: list[str], debut: int, premiere: int) -> str:
    morceaux = []
    for ligne in lignes[debut:premiere]:
        texte = re.sub(r"\s+", " ", _BORDURES.sub(" ", ligne)).strip()
        if texte:
            morceaux.append(texte)
    return " ".join(morceaux)[:LONGUEUR_QUESTION]


def _genre(texte: str) -> str:
    if "Do you want to" in texte or "Tab to amend" in texte:
        return "permission"
    if "Quick safety check" in texte or "trust this folder" in texte:
        return "confiance"
    if "Allow external CLAUDE.md file imports" in texte:
        return "imports"
    if "knows your environment" in texte or "about your environment" in texte:
        return "offre-mode-auto"
    return "choix"


def lire(capture: str) -> dict | None:
    """`{"genre", "question", "options"}` si la capture montre une fenêtre de choix, sinon None."""
    if not capture or not capture.strip():
        return None
    lignes = _lignes(capture)
    if invite._bornes(capture.split("\n")) is not None:
        return None
    pied = _pied(lignes)
    if pied is None:
        return None
    fin = pied + 1 if lignes[pied].rstrip().endswith("(esc)") else pied   # le pied est alors une option
    indices = _options_numerotees(lignes, fin) or _options_sans_numero(lignes, fin)
    if not indices or not any(_CURSEUR.match(lignes[i]) for i in indices):
        return None
    debut = _debut_de_fenetre(lignes, indices[0])
    texte_fenetre = "\n".join(lignes[debut:])
    return {"genre": _genre(texte_fenetre),
            "question": _question(lignes, debut, indices[0]),
            "options": [_libelle(lignes[i]) for i in indices]}
