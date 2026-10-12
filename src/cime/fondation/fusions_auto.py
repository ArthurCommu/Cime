"""Fusions automatiques : le réglage, la liste des chemins
réservés, `cime fusions-auto`. La garde et l'hôte lisent ce réglage ; seul l'utilisateur l'écrit.

Toute lecture qui échoue vaut « inactive » : jamais un laissez-passer sur erreur."""
import hashlib
import json
import os
import re
import sqlite3
import sys
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cime.fondation.nom import VAR_AGENT
from cime.fondation.projet import ErreurProjet, trouver_projet

CLE = "fusions_auto"
ACTIVE, INACTIVE = "active", "inactive"

# Le noyau : identique pour tout projet, non retirable par le manifeste. Il ne contient que les
# barrières — droits, secrets, philosophie, réseau ; ni les contrats ni les dépendances.
NOYAU = (
    ".claude/", ".orga/etat/",
    ".env", ".env.*", "*.pem", "*.key", "id_rsa*", "id_ed25519*", ".netrc", "credentials*",
    ".orga/socle/", ".orga/produit/", "CLAUDE.md", ".orga/teams/*/CLAUDE.md", ".orga/projet.toml",
    ".gitmodules", ".github/",
)

PORTEE = 2                 # ce que couvre une activation : 2 = fusions, chantiers, contrats, autorisations
PLAFOND_DEFAUT = 5         # lancements automatiques de chantier par 24 h

# Une entrée sans `/` vaut à toute profondeur (au nom de base), sauf celles-ci : racine seulement.
_RACINE_SEULE = frozenset({"CLAUDE.md"})


def _manifeste(projet: Path) -> Path:
    return Path(projet) / ".orga" / "projet.toml"


def _table_du_manifeste(projet: Path) -> dict:
    """La table `[fusions_auto]` du manifeste ({} si absente). Lève ErreurProjet."""
    fichier = _manifeste(projet)
    try:
        with open(fichier, "rb") as f:
            donnees = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise ErreurProjet(f"manifeste illisible ({fichier}) : {e}") from None
    table = donnees.get("fusions_auto", {})
    if not isinstance(table, dict):
        raise ErreurProjet(f"[fusions_auto] doit être une table ({fichier})")
    return table


def _reserves_du_manifeste(projet: Path) -> list[str]:
    """`[fusions_auto] reserves` du manifeste ; table absente = []. Lève ErreurProjet."""
    reserves = _table_du_manifeste(projet).get("reserves", [])
    if not isinstance(reserves, list) or not all(
            isinstance(e, str) and e.strip() for e in reserves):
        raise ErreurProjet(
            f"fusions_auto.reserves doit être une liste de chaînes non vides ({_manifeste(projet)})")
    return reserves


def plafond_chantiers(projet: Path) -> int:
    """`[fusions_auto] chantiers_par_jour` : entier ≥ 0 (0 = sans plafond), 5 par défaut. Lève
    ErreurProjet si le manifeste est illisible ou la valeur n'est pas un entier ≥ 0 (un booléen n'en
    est pas un)."""
    valeur = _table_du_manifeste(Path(projet)).get("chantiers_par_jour", PLAFOND_DEFAUT)
    if isinstance(valeur, bool) or not isinstance(valeur, int) or valeur < 0:
        raise ErreurProjet("fusions_auto.chantiers_par_jour doit être un entier ≥ 0 "
                           f"({_manifeste(projet)})")
    return valeur


def chemins_reserves(projet: Path) -> list[str]:
    """Le noyau, puis les entrées du manifeste, sans doublon. Lève ErreurProjet si le manifeste
    est illisible ou mal formé."""
    liste = list(NOYAU)
    for entree in _reserves_du_manifeste(Path(projet)):
        if entree not in liste:
            liste.append(entree)
    return liste


def empreinte(liste, plafond: int) -> str:
    """sha256 de la liste triée suivie de la ligne `chantiers_par_jour=<n>` : l'activation vaut pour
    cette liste et ce plafond."""
    texte = "\n".join(sorted(liste)) + "\nchantiers_par_jour=" + str(plafond)
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


def _segment(motif: str) -> re.Pattern:
    """Un segment de chemin ; `*` = n'importe quels caractères sauf `/`. Insensible à la casse
    (un disque macOS l'est : `.Claude/` est `.claude/`)."""
    return re.compile("[^/]*".join(re.escape(p) for p in motif.split("*")), re.IGNORECASE)


def _correspond(segments: list[str], motifs: list[str]) -> bool:
    return len(segments) >= len(motifs) and all(
        _segment(m).fullmatch(s) for s, m in zip(segments, motifs))


def est_reserve(chemin: str, liste) -> bool:
    """`chemin` (relatif à la racine, séparateur `/`) est réservé s'il est égal à une entrée de
    `liste`, ou sous une entrée terminée par `/` ; `*` = un segment ; une entrée sans `/` vaut à
    toute profondeur (au nom de base), sauf `CLAUDE.md` (racine seulement). Un chemin qui ne se
    lit pas comme relatif et net (absolu, `..`, vide) est réservé : dans le doute, oui."""
    segments = [s for s in chemin.split("/") if s not in ("", ".")]
    if not segments or chemin.startswith("/") or ".." in segments:
        return True
    for entree in liste:
        motifs = [m for m in entree.split("/") if m]
        if not motifs:
            continue
        if entree.endswith("/"):      # un dossier : lui-même et tout ce qu'il contient
            if _correspond(segments, motifs):
                return True
        elif "/" not in entree and entree not in _RACINE_SEULE:   # un nom, à toute profondeur
            if _segment(entree).fullmatch(segments[-1]):
                return True
        elif len(segments) == len(motifs) and _correspond(segments, motifs):
            return True
    return False


_INACTIF = {"active": False, "suspendue": False, "depuis": None, "par": None,
            "reserves": [], "empreinte": None, "reglage_id": None, "portee": None, "plafond": None}


def _plafond_lisible(projet: Path):
    """Le plafond du manifeste, ou None s'il ne se lit pas."""
    try:
        return plafond_chantiers(projet)
    except Exception:
        return None


def _inactif(projet: Path) -> dict:
    return dict(_INACTIF, reserves=[], plafond=_plafond_lisible(projet))


def _derniere_ligne(projet: Path):
    chemin = Path(projet) / ".orga" / "etat" / "registre.sqlite"
    if not chemin.exists():
        return None
    conn = sqlite3.connect(f"{chemin.resolve().as_uri()}?mode=ro", uri=True, timeout=2)
    try:
        return conn.execute(
            "SELECT id, horodatage, valeur, auteur, details FROM reglages_projet"
            " WHERE cle = ? ORDER BY id DESC LIMIT 1", (CLE,)).fetchone()
    finally:
        conn.close()


def _portee_lue(details: dict):
    """La portée enregistrée, ou None si elle manque ou n'est pas un entier (un booléen n'en est pas un)."""
    portee = details.get("portee")
    return portee if isinstance(portee, int) and not isinstance(portee, bool) else None


def etat_courant(projet: Path) -> dict:
    """{"active", "suspendue", "depuis", "par", "reserves", "empreinte", "reglage_id", "portee",
    "plafond"}. `reserves`, `empreinte` et `portee` sont ceux **enregistrés** à l'activation ;
    `plafond` est celui du manifeste maintenant (None s'il ne se lit pas). Une activation dont la
    portée manque ou est inférieure à `PORTEE` est suspendue, même à empreinte identique. Ne lève
    jamais : toute erreur de lecture donne l'option inactive."""
    try:
        ligne = _derniere_ligne(projet)
        if ligne is None or ligne[2] != ACTIVE:
            return _inactif(projet)
        ident, depuis, _, par, brut = ligne
        details = json.loads(brut) if brut else {}
        reserves = details.get("reserves")
        enregistree = details.get("empreinte")
        if not (isinstance(reserves, list) and all(isinstance(e, str) for e in reserves)
                and isinstance(enregistree, str)):
            return _inactif(projet)
        portee = _portee_lue(details)
        suspendue = portee is None or portee < PORTEE
        try:
            suspendue = suspendue or empreinte(
                chemins_reserves(projet), plafond_chantiers(projet)) != enregistree
        except Exception:   # liste ou plafond actuels illisibles : on ne peut pas dire qu'ils sont ceux de l'utilisateur
            suspendue = True
        return {"active": True, "suspendue": suspendue, "depuis": depuis, "par": par,
                "reserves": list(reserves), "empreinte": enregistree, "reglage_id": ident,
                "portee": portee, "plafond": _plafond_lisible(projet)}
    except Exception:
        return _inactif(projet)


_PREFIXE_CHANTIER = "chantier-auto:"
_FENETRE = timedelta(hours=24)


def _iso(instant: datetime) -> str:
    return instant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def lancements_auto_24h_strict(projet: Path, maintenant: datetime | None = None) -> int:
    """Nombre de lancements automatiques de chantier des dernières 24 h : les `rapport_utilisateur` de
    l'Assistant à l'utilisateur dont l'`objet` commence par `chantier-auto:` et qui ont une transition
    `clos` d'auteur `cime` dans la fenêtre (le lancement consomme l'annonce). **Lève ErreurProjet**
    si le registre est absent ou illisible : l'ordre de lancement en fait un refus."""
    chemin = Path(projet) / ".orga" / "etat" / "registre.sqlite"
    depuis = _iso((maintenant or datetime.now(timezone.utc)) - _FENETRE)
    try:
        if not chemin.exists():
            raise ErreurProjet(f"registre absent ({chemin})")
        conn = sqlite3.connect(f"{chemin.resolve().as_uri()}?mode=ro", uri=True, timeout=2)
        try:
            return conn.execute(
                "SELECT COUNT(DISTINCT m.id) FROM messages m JOIN transitions t ON t.message_id = m.id"
                " WHERE m.de = 'assistant' AND m.a = 'utilisateur' AND m.nature = 'rapport_utilisateur'"
                " AND substr(m.objet, 1, ?) = ? AND t.etat = 'clos' AND t.auteur = 'cime'"
                " AND t.horodatage >= ?",
                (len(_PREFIXE_CHANTIER), _PREFIXE_CHANTIER, depuis)).fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error as e:
        raise ErreurProjet(f"registre illisible ({chemin}) : {e}") from None


def lancements_auto_24h(projet: Path, maintenant: datetime | None = None) -> int:
    """Comme `lancements_auto_24h_strict`, pour l'affichage : ne lève jamais, 0 sur erreur de lecture.
    Jamais pour décider d'un lancement."""
    try:
        return lancements_auto_24h_strict(projet, maintenant)
    except Exception:
        return 0


def _afficher(projet: Path) -> None:
    etat = etat_courant(projet)
    if not etat["active"]:
        libelle, liste = "inactive", None
        try:
            liste = chemins_reserves(projet)
        except ErreurProjet as e:
            print(f"(liste des chemins réservés illisible : {e})", file=sys.stderr)
    else:
        libelle = "active mais suspendue" if etat["suspendue"] else "active"
        liste = etat["reserves"]
    print(f"fusions automatiques : {libelle}")
    if etat["active"]:
        print(f"depuis : {etat['depuis']} par {etat['par']}")
        print(f"portée : {etat['portee'] if etat['portee'] is not None else 'absente'}"
              f" (requise : {PORTEE})")
        if etat["suspendue"]:
            if etat["portee"] is None or etat["portee"] < PORTEE:
                print(f"l'activation ne couvre pas la portée {PORTEE} (fusions, chantiers, contrats, "
                      "autorisations) : l'accord de l'utilisateur s'applique tant qu'il n'a pas réactivé l'option.")
            else:
                print("la liste des chemins réservés ou le plafond a changé depuis l'activation : "
                      "l'accord de l'utilisateur s'applique tant qu'il n'a pas réactivé l'option.")
    n, plafond = lancements_auto_24h(projet), etat["plafond"]
    if plafond is None:
        suite = f"{n} (plafond du manifeste illisible)"
    elif plafond == 0:
        suite = f"{n} (sans plafond)"
    else:
        suite = f"{n} sur {plafond}"
    print(f"lancements automatiques de chantier : {suite}")
    if liste is not None:
        titre = "enregistrée à l'activation" if etat["active"] else "actuelle"
        print(f"chemins réservés, liste {titre} ({len(liste)}) :")
        for entree in liste:
            print(f"  {entree}")


def _ecrire(projet: Path, valeur: str) -> int:
    from cime.fondation import registre
    avant = etat_courant(projet)
    if valeur == ACTIVE and avant["active"] and not avant["suspendue"]:
        print("fusions-auto : déjà actif", file=sys.stderr)
        return 1
    if valeur == INACTIVE and not avant["active"]:
        print("fusions-auto : déjà inactif", file=sys.stderr)
        return 1
    if valeur == ACTIVE:
        reserves, plafond = chemins_reserves(projet), plafond_chantiers(projet)
        details = {"reserves": reserves, "empreinte": empreinte(reserves, plafond),
                   "portee": PORTEE, "chantiers_par_jour": plafond}
    conn = registre.ouvrir(projet)
    try:
        if valeur == INACTIVE:
            precedente = conn.execute(
                "SELECT MAX(id) FROM reglages_projet WHERE cle = ?", (CLE,)).fetchone()[0]
            details = {"avant": precedente}
        with conn:
            ident = conn.execute(
                "INSERT INTO reglages_projet (horodatage, cle, valeur, auteur, details)"
                " VALUES (?, ?, ?, 'utilisateur', ?)",
                (registre.horodatage(), CLE, valeur,
                 json.dumps(details, ensure_ascii=False))).lastrowid
    finally:
        conn.close()
    print(ident)
    return 0


def executer(args) -> int:
    projet = trouver_projet()
    valeur = getattr(args, "valeur", None)
    if valeur is None:
        _afficher(projet)
        return 0
    if (os.environ.get(VAR_AGENT) or None) != "utilisateur":
        print("fusions-auto : seul l'utilisateur active ou désactive les fusions automatiques "
              f"({VAR_AGENT} doit valoir utilisateur)", file=sys.stderr)
        return 1
    return _ecrire(projet, valeur)
