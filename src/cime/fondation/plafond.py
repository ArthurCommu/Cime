"""Le plafond de workers actifs : un réglage de la machine, dans un fichier personnel valable pour
tous les projets, qu'un projet peut seulement abaisser (`[charge] workers_max` du manifeste). Le
fichier est relu à chaque appel (aucun cache : le facteur voit un changement au tour suivant) ; un
fichier absent ou mauvais ne bloque jamais, il vaut le défaut.

Écrire ce réglage est la seule écriture de cime hors d'un projet : `<dossier de configuration>/cime/`
reçoit le fichier de réglages et son journal, rien d'autre."""
import json
import os
import re
import sys
import tomllib
from pathlib import Path

from cime.fondation import registre
from cime.fondation.nom import VAR_AGENT
from cime.fondation.projet import ErreurProjet, lire_manifeste, trouver_projet

CLE = "workers_max"
DEFAUT = 3
MIN, MAX = 1, 8
FICHIER, JOURNAL = "reglages.toml", "reglages.journal"
DEFAUT_SOURCE, FICHIER_SOURCE = "defaut", "fichier"
MACHINE, PROJET = "machine", "projet"

_LIGNE_CLE = re.compile(rf"^\s*{CLE}\s*=")
_ENTETE = re.compile(r"^\s*\[")


def dossier_reglages() -> Path:
    """`<XDG_CONFIG_HOME ou ~/.config>/cime`, calculé à chaque appel : une variable absente, vide
    ou non absolue retombe sur `~/.config`."""
    base = os.environ.get("XDG_CONFIG_HOME", "")
    if base and os.path.isabs(base):
        return Path(base) / "cime"
    return Path.home() / ".config" / "cime"


def valeur_valide(valeur) -> bool:
    """Un entier de MIN à MAX (ni booléen, ni flottant, ni texte)."""
    return isinstance(valeur, int) and not isinstance(valeur, bool) and MIN <= valeur <= MAX


def lire_machine() -> tuple[int, str]:
    """(plafond de la machine, source) ; source : `"fichier"` ou `"defaut"`. Ne lève jamais :
    fichier absent, illisible, TOML invalide ou valeur hors règle valent le défaut."""
    try:
        donnees = tomllib.loads((dossier_reglages() / FICHIER).read_text(encoding="utf-8"))
    except (OSError, ValueError, RuntimeError):
        return DEFAUT, DEFAUT_SOURCE
    valeur = donnees.get(CLE)
    return (valeur, FICHIER_SOURCE) if valeur_valide(valeur) else (DEFAUT, DEFAUT_SOURCE)


def plafond_projet(projet) -> int | None:
    """`[charge] workers_max` du manifeste ; None quand la clé manque (pas de limite de projet).
    Lève ErreurProjet si le manifeste est illisible."""
    return lire_manifeste(projet).workers_max


def en_vigueur(machine: int, projet: int | None) -> tuple[int, str]:
    """(plafond, source) : le plus bas des deux ; le projet n'est jamais plus haut que la machine."""
    if projet is not None and projet < machine:
        return projet, PROJET
    return machine, MACHINE


def dernier_changement(valeur: int) -> tuple[str, str] | None:
    """(horodatage, auteur) de la dernière ligne du journal quand elle a posé `valeur` ; None sinon
    (journal absent, illisible, ou fichier modifié depuis à la main)."""
    try:
        texte = (dossier_reglages() / JOURNAL).read_text(encoding="utf-8")
    except (OSError, ValueError, RuntimeError):
        return None
    derniere = None
    for ligne in texte.splitlines():
        try:
            entree = json.loads(ligne)
        except ValueError:
            continue
        if isinstance(entree, dict) and entree.get("cle") == CLE:
            derniere = entree
    if derniere is None or derniere.get("apres") != valeur:
        return None
    return derniere.get("horodatage"), derniere.get("auteur")


def _afficher(projet, manifeste, sortie_json: bool) -> int:
    from cime.signaux import ordres
    sessions = ordres._sessions_vivantes()
    if projet is None:
        machine, source = lire_machine()
        actifs = ordres.compter_workers(sessions) if sessions is not None else None
        par_projet = ordres.workers_par_projet(sessions) if sessions is not None else None
    else:
        machine, source = ordres.plafond_machine(projet, sessions)
        actifs, par_projet = ordres.workers_vus(projet, sessions)
    limite = manifeste.workers_max if manifeste is not None else None
    valeur, origine = en_vigueur(machine, limite)
    changement = dernier_changement(machine) if source == FICHIER_SOURCE else None
    depuis, par = changement if changement is not None else (None, None)
    if sortie_json:
        print(json.dumps({
            "valeur": valeur, "source": origine,
            "machine": {"valeur": machine, "source": source, "depuis": depuis, "par": par},
            "projet": limite, "workers_actifs": actifs, "par_projet": par_projet},
            ensure_ascii=False))
        return 0
    modifie = f", modifié par {par} le {depuis}" if changement is not None else ""
    nom_source = "fichier" if source == FICHIER_SOURCE else "défaut"
    print(f"plafond en vigueur : {valeur}")
    print(f"machine : {machine} ({nom_source}{modifie})")
    if projet is None:
        print("projet : hors projet")
    else:
        print(f"projet : {limite}" if limite is not None else "projet : sans limite")
    print(f"workers actifs : {'?' if actifs is None else actifs}")
    courant = manifeste.prefixe if manifeste is not None else None
    for prefixe, n in sorted((par_projet or {}).items()):
        print(f"  {prefixe} : {n}" + (" (ce projet)" if prefixe == courant else ""))
    return 0


def _entier(texte: str) -> int | None:
    """L'entier de MIN à MAX que `texte` écrit en chiffres ASCII, sinon None."""
    if not (texte.isascii() and texte.isdigit()):
        return None
    n = int(texte)
    return n if valeur_valide(n) else None


def _nouveau_texte(texte: str, valeur: int | None) -> str:
    """`texte` avec la ligne `workers_max` de la racine remplacée par `valeur`, ajoutée ou, pour
    None, retirée ; toutes les autres lignes sont conservées telles quelles."""
    lignes = texte.splitlines(keepends=True)
    fin_racine = next((i for i, ligne in enumerate(lignes) if _ENTETE.match(ligne)), len(lignes))
    place = next((i for i in range(fin_racine) if _LIGNE_CLE.match(lignes[i])), None)
    neuve = None if valeur is None else f"{CLE} = {valeur}\n"
    if place is not None:
        if neuve is None:
            del lignes[place]
        else:
            lignes[place] = neuve
    elif neuve is not None:
        if fin_racine and not lignes[fin_racine - 1].endswith("\n"):
            lignes[fin_racine - 1] += "\n"
        if fin_racine < len(lignes) and lignes[fin_racine].strip():
            neuve += "\n"
        lignes.insert(fin_racine, neuve)
    return "".join(lignes)


def _ecrire(valeur: int | None) -> int:
    """Pose `valeur` (None = revenir au défaut, la clé est retirée) dans le fichier de la machine,
    sauf si le fichier la dit déjà ; imprime l'horodatage de la ligne de journal écrite. La ligne de
    journal est ajoutée avant le remplacement du fichier : si le journal ne s'écrit pas, rien ne
    change."""
    dossier = dossier_reglages()
    chemin = dossier / FICHIER
    try:
        texte = chemin.read_text(encoding="utf-8")
        donnees = tomllib.loads(texte)
    except FileNotFoundError:
        texte, donnees = "", {}
    except (OSError, ValueError) as e:
        print(f"plafond : {chemin} est illisible, rien n'est changé ({e})", file=sys.stderr)
        return 1
    ancienne = donnees.get(CLE)
    if valeur is None and CLE not in donnees:
        print("plafond : déjà au défaut", file=sys.stderr)
        return 1
    if valeur is not None and ancienne == valeur and valeur_valide(ancienne):
        print(f"plafond : déjà {valeur}", file=sys.stderr)
        return 1
    neuf = _nouveau_texte(texte, valeur)
    attendu = {c: v for c, v in donnees.items() if c != CLE}
    if valeur is not None:
        attendu[CLE] = valeur
    try:
        if tomllib.loads(neuf) != attendu:
            raise ValueError("la ligne n'est pas à la racine du fichier")
    except ValueError as e:
        print(f"plafond : {chemin} ne se modifie pas proprement, rien n'est changé ({e})",
              file=sys.stderr)
        return 1
    ligne = {"horodatage": registre.horodatage(), "cle": CLE,
             "avant": ancienne if valeur_valide(ancienne) else DEFAUT_SOURCE,
             "apres": valeur if valeur is not None else DEFAUT_SOURCE, "auteur": "utilisateur"}
    try:
        dossier.mkdir(parents=True, exist_ok=True)
        with open(dossier / JOURNAL, "a", encoding="utf-8") as journal:
            journal.write(json.dumps(ligne, ensure_ascii=False) + "\n")
            journal.flush()
            os.fsync(journal.fileno())
    except OSError as e:
        print(f"plafond : le journal ne s'écrit pas, rien n'est changé ({e})", file=sys.stderr)
        return 1
    temporaire = chemin.with_name(chemin.name + ".tmp")
    try:
        temporaire.write_text(neuf, encoding="utf-8")
        os.replace(temporaire, chemin)
    except OSError as e:
        temporaire.unlink(missing_ok=True)
        print(f"plafond : {chemin} ne s'écrit pas ({e})", file=sys.stderr)
        return 1
    print(ligne["horodatage"])
    return 0


def executer(args) -> int:
    valeur = getattr(args, "valeur", None)
    defaut = getattr(args, "defaut", False)
    if valeur is None and not defaut:
        try:
            projet = trouver_projet()
        except ErreurProjet:
            projet = None
        manifeste = lire_manifeste(projet) if projet is not None else None
        return _afficher(projet, manifeste, getattr(args, "sortie_json", False))
    if (os.environ.get(VAR_AGENT) or None) != "utilisateur":
        print("plafond : seul l'utilisateur règle le plafond de workers "
              f"({VAR_AGENT} doit valoir utilisateur)", file=sys.stderr)
        return 1
    if defaut:
        return _ecrire(None)
    entier = _entier(valeur)
    if entier is None:
        print(f"plafond : un entier de {MIN} à {MAX}", file=sys.stderr)
        return 2
    return _ecrire(entier)
