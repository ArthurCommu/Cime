"""Après une fusion : les suites déclarées par le `travail_pret` et les contrats modifiés.

Suites déclarées — `cime envoyer|repondre --nature travail_pret --suite <spec>` (répétable) range les specs dans la
preuve de la transition `inscrit` du message (clé `suites`). Quand la fusion de la branche de l'équipe
est vue (`PostToolUse`, `resultat=fusionne`), le code inscrit `cime→assistant` une `consigne`
`objet=suites:<équipe>` ; `cime suites <équipe>` (Assistant seul) vérifie par git que la branche est dans
la branche de référence, exécute les specs (idempotent) et ferme l'obligation.

Contrats modifiés — `[contrats]` du manifeste : `<contrat> = ["<équipe lectrice>", …]`. Une fusion qui touche
`.orga/contracts/<nom>.schema.md` ou `.orga/contracts/exemples/<nom>-exemple.*` signale chaque lectrice.

Liste fermée des specs : `recopier:<source>:<cible>`, `migrer`. Il n'y a pas de `reinstaller` : `cime`
est installé en mode éditable depuis le projet, la fusion suffit.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

from cime.fondation.projet import ErreurProjet, lire_manifeste
from cime.signaux import commandes, hooks, obligations
from cime.signaux.commandes import Refus

DELAI_GIT = 5
SPECS_VALIDES = "recopier:<source>:<cible> | migrer"
ATTENTE_SUITES = "action"      # ce que la consigne `suites:` attend de l'Assistant
PREFIXE_OBJET = "suites:"
CONTRATS = ".orga/contracts"


# --- les specs ------------------------------------------------------------------------------------

def _dans_le_projet(projet: Path, chemin: str, role: str) -> Path:
    brut = Path(chemin)
    if not chemin or brut.is_absolute() or ".." in brut.parts:
        raise Refus(f"recopier : {role} {chemin!r} doit être un chemin relatif au projet, sans « .. »")
    racine = Path(projet).resolve()
    resolu = (racine / brut).resolve()
    if not resolu.is_relative_to(racine):
        raise Refus(f"recopier : {role} {chemin!r} sort du projet")
    return resolu


def valider(specs, projet) -> list[str]:
    """Les specs, dans l'ordre et sans doublon ; `Refus` sur la première qui n'est pas de la liste fermée."""
    sortie: list[str] = []
    for spec in specs or []:
        morceaux = spec.split(":")
        if morceaux[0] == "migrer" and len(morceaux) == 1:
            pass
        elif morceaux[0] == "recopier" and len(morceaux) == 3:
            _dans_le_projet(projet, morceaux[1], "la source")
            _dans_le_projet(projet, morceaux[2], "la cible")
        else:
            raise Refus(f"suite inconnue : {spec!r} (specs valides : {SPECS_VALIDES})")
        if spec not in sortie:
            sortie.append(spec)
    return sortie


def _recopier(projet: Path, source: str, cible: str) -> str:
    src, dst = _dans_le_projet(projet, source, "la source"), _dans_le_projet(projet, cible, "la cible")
    if not src.is_file():
        raise Refus(f"recopier : source absente : {source}")
    if dst.is_file() and dst.read_bytes() == src.read_bytes():
        return f"recopier {source} → {cible} : déjà identique, rien à faire"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    return f"recopier {source} → {cible} : copié"


def _migrer(projet: Path) -> str:
    """`cime init --migrer` sur le projet. Idempotent : ce qui est déjà migré n'est pas touché."""
    import os
    from types import SimpleNamespace

    from cime.fondation import init
    utilisateur = os.environ.get("USER") or "utilisateur"
    rapport = init.installer(SimpleNamespace(
        dossier=str(projet), utilisateur=utilisateur, nom_projet=None, prefixe=None,
        migrer=True, hooks_sans_cime=init.executable_cime() is None))
    ajoutes, completes = len(rapport["ajouté"]), len(rapport["complété"])
    return f"migrer : init --migrer exécuté ({ajoutes} ajouté(s), {completes} complété(s))"


def executer(projet, specs) -> list[str]:
    """Exécute les specs ; un compte rendu par ligne. Lève `Refus` sur la première qui échoue."""
    lignes = []
    for spec in valider(specs, projet):
        if spec == "migrer":
            lignes.append(_migrer(Path(projet)))
        else:
            _, source, cible = spec.split(":")
            lignes.append(_recopier(Path(projet), source, cible))
    return lignes


# --- retrouver ce que le travail_pret a déclaré -----------------------------------------------------

def specs_du_message(conn, message_id) -> list[str]:
    ligne = conn.execute(
        "SELECT preuve FROM transitions WHERE message_id = ? AND etat = 'inscrit' ORDER BY id LIMIT 1",
        (message_id,)).fetchone()
    try:
        preuve = json.loads(ligne[0]) if ligne else {}
    except (TypeError, ValueError):
        return []
    suites = preuve.get("suites") if isinstance(preuve, dict) else None
    return [s for s in suites if isinstance(s, str)] if isinstance(suites, list) else []


def travail_pret_avec_suites(conn, equipe) -> list[tuple[int, list[str]]]:
    """(id, specs) des `travail_pret` d'une équipe à l'Assistant qui portent des suites, du plus récent
    au plus ancien."""
    sortie = []
    for (ident,) in conn.execute(
            "SELECT id FROM messages WHERE nature = 'travail_pret' AND a = 'assistant' AND equipe = ?"
            " ORDER BY id DESC", (equipe,)).fetchall():
        specs = specs_du_message(conn, ident)
        if specs:
            sortie.append((ident, specs))
    return sortie


# --- git --------------------------------------------------------------------------------------------

def _git(projet, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(projet), *args], capture_output=True, text=True,
                          timeout=DELAI_GIT)


def sha_de(projet, ref) -> str | None:
    try:
        r = _git(projet, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() or None if r.returncode == 0 else None


def branche_dans_la_reference(projet, equipe) -> bool | None:
    """`True` si la branche de l'équipe est un ancêtre de la branche de référence, `False` si elle ne
    l'est pas, `None` si git ne répond pas (branche absente, délai dépassé)."""
    m = lire_manifeste(projet)
    branche = m.branche_equipe.format(equipe=equipe)
    try:
        r = _git(projet, "merge-base", "--is-ancestor", branche, m.branche_reference)
    except (OSError, subprocess.SubprocessError):
        return None
    return {0: True, 1: False}.get(r.returncode)


# --- suites déclarées : après la fusion --------------------------------------------------------------------------

def _consigne_deja_inscrite(conn, equipe, sha) -> bool:
    return conn.execute(
        "SELECT 1 FROM messages m JOIN transitions t ON t.message_id = m.id AND t.etat = 'inscrit'"
        " WHERE m.de = 'cime' AND m.a = 'assistant' AND m.nature = 'consigne' AND m.objet = ?"
        " AND json_extract(t.preuve, '$.cle') = ? LIMIT 1", (f"{PREFIXE_OBJET}{equipe}", sha)).fetchone() is not None


def apres_fusion_suites(conn, projet, fusions, evenement_id) -> list[int]:
    """`fusions` : [(ref, sha, resultat)]. Pour chaque fusion faite dont la branche est celle d'un
    `travail_pret` portant des suites : `cime→assistant` `consigne --attend action objet=suites:<é>`,
    une seule par équipe et par fusion. Renvoie les messages inscrits."""
    m = lire_manifeste(projet)
    inscrits: list[int] = []
    equipes = [r[0] for r in conn.execute(
        "SELECT DISTINCT equipe FROM messages WHERE nature = 'travail_pret' AND a = 'assistant'"
        " AND equipe IS NOT NULL").fetchall()]
    for ref, sha, resultat in fusions:
        if resultat != "fusionne" or sha == "inconnu":
            continue
        for equipe in equipes:
            branche = m.branche_equipe.format(equipe=equipe)
            if ref not in (branche, f"refs/heads/{branche}") and sha_de(projet, branche) != sha:
                continue
            candidats = travail_pret_avec_suites(conn, equipe)
            if not candidats or _consigne_deja_inscrite(conn, equipe, sha):
                continue
            ident, specs = candidats[0]
            inscrits.append(commandes.inscrire(
                conn, de="cime", a="assistant", nature="consigne",
                resume=(f"{equipe} est fusionnée ({sha[:7]}) : lance `cime suites {equipe}` "
                        f"({', '.join(specs)})")[:160],
                objet=f"{PREFIXE_OBJET}{equipe}", equipe=equipe, attend=ATTENTE_SUITES,
                corps="\n".join(specs),
                preuve={"cmd": "hook", "cle": sha, "travail_pret": ident, "evenement": evenement_id}))
    return inscrits


# --- cime suites <équipe> -------------------------------------------------------------------------------

def _obligation_ouverte(conn, equipe):
    return conn.execute(
        "SELECT m.id FROM messages m JOIN obligations o ON o.message_id = m.id AND o.etat = 'ouverte'"
        " WHERE m.de = 'cime' AND m.a = 'assistant' AND m.objet = ? ORDER BY m.id DESC LIMIT 1",
        (f"{PREFIXE_OBJET}{equipe}",)).fetchone()


def _suites(args) -> int:
    moi = commandes.identite_appelant()
    if moi != "assistant":
        raise Refus("`cime suites` est réservé à l'Assistant")
    projet = commandes.projet_courant()
    equipe = args.equipe
    from cime.fondation.registre import inscrire_transition, ouvrir
    conn = ouvrir(projet)
    try:
        declarees = travail_pret_avec_suites(conn, equipe)
        if not declarees:
            raise Refus(f"aucun travail_pret de {equipe} ne déclare de suite (--suite)")
        dans = branche_dans_la_reference(projet, equipe)
        if dans is None:
            raise Refus(f"git ne répond pas pour la branche de {equipe} (absente ou délai dépassé)")
        if not dans:
            raise Refus(f"la branche de {equipe} n'est pas encore dans la branche de référence : "
                        "les suites s'exécutent après la fusion")
        for ligne in executer(projet, declarees[0][1]):
            print(ligne)
        ouverte = _obligation_ouverte(conn, equipe)
        if ouverte is not None:
            with conn:
                obligations.satisfaire(conn, ouverte[0], None, commit=False)
                inscrire_transition(conn, ouverte[0], "clos", "assistant",
                                    {"par_commande": "suites"}, commit=False)
            print(f"suites de {equipe} : obligation #{ouverte[0]} fermée")
        else:
            print(f"suites de {equipe} : aucune obligation ouverte (déjà fermée)")
        return 0
    finally:
        conn.close()


def suites(args) -> int:
    return commandes.lancer_commande("suites", _suites, args)


# --- contrats modifiés par une fusion ------------------------------------------------------------

def nom_du_contrat(chemin: str) -> str | None:
    """`.orga/contracts/<nom>.schema.md` → `<nom>` ; `.orga/contracts/exemples/<nom>-exemple.<ext>` → `<nom>`."""
    p = Path(chemin)
    if chemin.startswith(f"{CONTRATS}/exemples/") and len(p.parts) == 4:
        racine = p.name.rsplit(".", 1)[0]
        return racine[:-len("-exemple")] if racine.endswith("-exemple") else racine
    if p.parent == Path(CONTRATS) and p.name.endswith(".schema.md"):
        return p.name[:-len(".schema.md")]
    return None


def fichiers_touches(projet, avant, apres) -> list[str]:
    try:
        r = _git(projet, "diff", "--name-only", f"{avant}..{apres}")
    except (OSError, subprocess.SubprocessError):
        return []
    return r.stdout.split("\n") if r.returncode == 0 and r.stdout.strip() else []


def apres_fusion_contrats(conn, projet, avant, apres) -> list[int]:
    """Pour chaque contrat touché par la fusion (`avant..après`), un `signalement contrat:<nom>` à
    `coord-<lectrice>` de chaque équipe lectrice de `[contrats]`, unique par (contrat, sha). Un contrat
    sans entrée dans `[contrats]` ne signale personne."""
    if not avant or not apres or avant == apres:
        return []
    table = lire_manifeste(projet).contrats
    if not table:
        return []
    inscrits: list[int] = []
    vus: dict[str, list[str]] = {}
    for fichier in fichiers_touches(projet, avant, apres):
        nom = nom_du_contrat(fichier)
        if nom is not None and nom in table:
            vus.setdefault(nom, []).append(fichier)
    for nom, fichiers in vus.items():
        for equipe in table[nom]:
            ident = hooks.signaler_une_fois(
                conn, projet, a=f"coord-{equipe}", objet=f"contrat:{nom}", cle=apres[:12],
                resume=f"le contrat {nom} a changé ({', '.join(f.removeprefix(CONTRATS + '/') for f in fichiers)}) "
                       f"à {apres[:7]} : relis-le"[:160])
            if ident is not None:
                inscrits.append(ident)
    return inscrits
