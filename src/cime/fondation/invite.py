"""Lecture de l'invite de saisie d'une session tmux (texte tapé, texte replié, état) à partir d'une capture."""

import re
import subprocess

_SGR = re.compile(r"\x1b\[([0-9;]*)m")
_CSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_PREFIXE = "❯\xa0"
# règle pure, ou règle dont la bordure porte un libellé : `──── … ─ CONSIGNES.md review ─`
# la TUI replie un texte collé long : `[Pasted text #1]`, `[Pasted text #2 +12 lines]`
MARQUEUR = re.compile(r"\[Pasted text #\d+(?: \+\d+ lines?)?\]")
_REGLE = re.compile(r"─{10,}(?:[ \t][^─]*─)?")
_NON_BLANC = re.compile(r"\s")


def capturer(session: str) -> str:
    r = subprocess.run(["tmux", "capture-pane", "-p", "-e", "-t", session],
                       capture_output=True, text=True)
    return r.stdout


def _brut(ligne: str) -> str:
    return _CSI.sub("", ligne)


def _est_regle(ligne: str) -> bool:
    return _REGLE.fullmatch(_brut(ligne).strip()) is not None


def _bornes(lignes: list[str]) -> tuple[int, int] | None:
    """Indices de la ligne `❯` de la saisie et de la règle ─ du bas, ou None."""
    regles = [i for i, l in enumerate(lignes) if _est_regle(l)]
    for haut, bas in zip(reversed(regles[:-1]), reversed(regles[1:])):
        if bas - haut > 1 and _brut(lignes[haut + 1]).startswith(_PREFIXE):
            return haut + 1, bas
    return None


def _zone(lignes: list[str]) -> list[str] | None:
    """Lignes de saisie entre les deux règles ─ du bas, ou None."""
    bornes = _bornes(lignes)
    return None if bornes is None else lignes[bornes[0]:bornes[1]]


def _visible(texte: str, attenue: bool) -> tuple[str, bool]:
    """Texte non atténué de `texte` ; l'état d'atténuation est reporté de ligne en ligne."""
    sortie, pos = [], 0
    for m in _SGR.finditer(texte):
        if not attenue:
            sortie.append(_CSI.sub("", texte[pos:m.start()]))
        pos = m.end()
        params = [p for p in m.group(1).split(";")]
        i = 0
        while i < len(params):
            p = params[i]
            if p in ("", "0", "22"):
                attenue = False
            elif p == "2":
                attenue = True
            elif p in ("38", "48"):  # couleur étendue : 5;n ou 2;r;g;b
                i += 2 if i + 1 < len(params) and params[i + 1] == "5" else 4
            i += 1
    if not attenue:
        sortie.append(_CSI.sub("", texte[pos:]))
    return "".join(sortie), attenue


def _passe(zone: list[str]) -> list[tuple[str, int, int]]:
    """Pour chaque ligne de saisie : son texte non atténué (rogné à droite), le nombre de caractères non
    blancs gardés, le nombre de caractères non blancs écartés comme atténués."""
    sortie, attenue = [], False
    for n, ligne in enumerate(zone):
        if n == 0:  # le préfixe n'est pas du texte
            ligne = re.sub(r"^((?:\x1b\[[0-9;]*m)*)❯\xa0", r"\1", ligne, count=1)
        else:  # ligne de continuation : indentée de deux espaces
            ligne = re.sub(r"^((?:\x1b\[[0-9;]*m)*)  ", r"\1", ligne, count=1)
        texte, attenue = _visible(ligne, attenue)
        gardes = len(_NON_BLANC.sub("", texte))
        sortie.append((texte.rstrip(), gardes, len(_NON_BLANC.sub("", _brut(ligne))) - gardes))
    return sortie


def mesures_invite(capture: str) -> dict | None:
    """Mesures de la zone de saisie, en nombres seulement (jamais de texte), pour dire pourquoi
    `texte_invite` a rendu ce qu'il a rendu. None si la zone est introuvable."""
    lignes = capture.split("\n")
    bornes = _bornes(lignes)
    if bornes is None:
        return None
    haut, bas = bornes
    passe = _passe(lignes[haut:bas])
    return {
        "capture_lignes": len(lignes),
        "regles": [i for i, l in enumerate(lignes) if _est_regle(l)],
        "zone_haut": haut,
        "zone_lignes": bas - haut,
        "visible_par_ligne": [gardes for _, gardes, _ in passe],
        "attenue_perdu": sum(perdus for _, _, perdus in passe),
        "attenue_ligne0": passe[0][2],
    }


def texte_invite(capture: str) -> str | None:
    zone = _zone(capture.split("\n"))
    if zone is None:
        return None
    morceaux = [texte for texte, _, _ in _passe(zone)]
    texte = "\n".join(morceaux).strip("\n")
    # un marqueur de repli n'est jamais « vide », quels que soient ses attributs (atténué ou non)
    brut = "\n".join(_brut(l) for l in zone)
    caches = MARQUEUR.findall(brut)
    if caches and len(MARQUEUR.findall(texte)) < len(caches):
        texte = (" ".join(caches) + texte).strip("\n")
    return texte


def brouillon(session: str) -> str | None:
    return texte_invite(capturer(session))
