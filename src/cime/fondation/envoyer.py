"""`cime envoyer` : inscrit un message au registre, d'où le facteur le livre à son destinataire."""

import os
import re
import subprocess
import sys
from pathlib import Path

from cime.fondation.nom import VAR_PROJET
from cime.fondation.projet import (ErreurProjet, equipe_de, est_un_projet,
                                   lire_manifeste, valider_identite)
from cime.fondation.registre import CORPS_MAX, NATURES, horodatage, ouvrir

# États où un message n'est plus un envoi en cours : un envoi identique redevient permis
_TERMINES = ("clos", "abandonne", "echec")


def _tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", *args], capture_output=True, text=True)


def _erreur(message: str) -> int:
    print(f"envoyer : {message}", file=sys.stderr)
    return 1


def _refus(message: str) -> int:
    print(f"envoyer : {message}", file=sys.stderr)
    return 2


def _projet() -> Path | None:
    """Racine du projet désigné par CIME_PROJET, jamais devinée depuis le dossier courant."""
    valeur = os.environ.get(VAR_PROJET)
    if not valeur:
        return None
    racine = Path(valeur).resolve()
    return racine if est_un_projet(racine) else None


def _corps(args) -> str | None:
    corps = getattr(args, "corps", None)
    if corps is None:
        return None
    if corps == "-":
        corps = sys.stdin.read()
    if len(corps) > CORPS_MAX:
        raise ValueError(f"corps trop long : {len(corps)} caractères (max {CORPS_MAX})")
    return corps


def _doublon(conn, *, de, a, nature, objet, resume, corps, fichier) -> tuple | None:
    """Le message identique (mêmes `de`, `a`, `nature`, `objet`, `resume`, `corps`, `fichier`) inscrit il y a
    moins de `DOUBLON_FENETRE` et dont la dernière transition n'est pas terminale : (id, état, secondes), ou None.
    Un agent qui relance le même envoi pendant que le premier vit n'en crée pas un second."""
    from cime.signaux import echeances
    maintenant = echeances._lire(horodatage())
    candidats = conn.execute(
        "SELECT m.id, m.horodatage, (SELECT t.etat FROM transitions t WHERE t.message_id = m.id"
        " ORDER BY t.id DESC LIMIT 1) FROM messages m WHERE m.de IS ? AND m.a IS ? AND m.nature IS ?"
        " AND m.objet IS ? AND m.resume IS ? AND m.corps IS ? AND m.fichier IS ? ORDER BY m.id DESC",
        (de, a, nature, objet, resume, corps, fichier)).fetchall()
    for identifiant, inscrit, etat in candidats:
        age = maintenant - echeances._lire(inscrit)
        if age < echeances.DOUBLON_FENETRE and etat not in _TERMINES:
            return identifiant, etat, int(age.total_seconds())
    return None


def _envoyer(args) -> int:
    from cime.signaux import commandes, matrice
    from cime.signaux.identite import ErreurIdentite, appelant
    if getattr(args, "en_reponse_a", None) is not None:
        print("envoyer : plus d'option --en-reponse-a : utilise `cime repondre <id>`",
              file=sys.stderr)
        return 2
    try:
        de = appelant()
    except ErreurIdentite as e:
        print(f"envoyer : {e}", file=sys.stderr)
        return 2
    a = args.a
    try:
        valider_identite(de, emetteur=True)
        valider_identite(a)
    except ValueError as e:
        return _erreur(str(e))
    if args.nature not in NATURES:
        return _erreur(f"nature inconnue : {args.nature!r} (attendu : {', '.join(NATURES)})")
    attend = getattr(args, "attend", None)
    if args.nature == "consigne":
        if attend is None:
            return _refus("--attend obligatoire pour une consigne "
                          f"({', '.join(matrice.ATTENTES_CONSIGNE)})")
        if attend not in matrice.ATTENTES_CONSIGNE:
            return _refus(f"--attend {attend!r} inconnu "
                          f"({', '.join(matrice.ATTENTES_CONSIGNE)})")
    elif attend is not None:
        return _refus("--attend n'a de sens que pour une consigne")
    projet = _projet()
    if projet is None:
        return _erreur(f"{VAR_PROJET} absent (ou ne désigne pas un projet) : lance cette "
                       "commande depuis un agent lancé par `cime lancer`")
    motif = matrice.verifier(de, a, args.nature, projet)
    if motif:
        return _refus(motif)
    manifeste = lire_manifeste(projet)
    fichier = None
    if args.fichier:
        chemin = (Path.cwd() / args.fichier).resolve()  # relatif : depuis le dossier de l'appelant ; absolu : tel quel
        if not chemin.is_relative_to(projet):
            return _erreur(f"fichier hors du projet : {args.fichier}")
        if not chemin.exists():
            return _erreur(f"fichier introuvable : {args.fichier}")
        fichier = str(chemin.relative_to(projet))
    corps = _corps(args)
    equipe = getattr(args, "equipe", None)
    preuve = None
    suites = getattr(args, "suite", None)
    if suites:
        if args.nature != "travail_pret" or a != "assistant":
            return _refus("--suite n'a de sens que pour un travail_pret adressé à l'Assistant")
        from cime.signaux import suites as suites_mod
        from cime.signaux.commandes import Refus
        try:
            suites = suites_mod.valider(suites, projet)
        except Refus as e:
            return _refus(str(e))
        preuve = {"cmd": "envoyer", "pid": os.getpid(), "suites": suites}
    conn = ouvrir(projet)
    try:
        if equipe is not None:
            if equipe in manifeste.equipes_speciales:
                return _erreur(f"équipe spéciale : {equipe!r} (rien inscrit)")
            if not re.fullmatch(r"[a-z0-9-]+", equipe) \
                    or not (projet / ".orga" / "teams" / equipe).is_dir():
                return _erreur(f"équipe inexistante : {equipe!r} (rien inscrit)")
        else:
            equipe = equipe_de(projet, de) or equipe_de(projet, a)

        doublon = _doublon(conn, de=de, a=a, nature=args.nature, objet=getattr(args, "objet", None),
                           resume=args.resume, corps=corps, fichier=fichier)
        if doublon is not None:
            return _erreur(f"déjà envoyé : #{doublon[0]} ({doublon[1]}, il y a {doublon[2]} s)"
                           " — rien n'est inscrit")

        identifiant = commandes.inscrire(
            conn, de=de, a=a, nature=args.nature, resume=args.resume, fichier=fichier,
            equipe=equipe, objet=getattr(args, "objet", None), corps=corps, attend=attend,
            preuve=preuve)
        print(identifiant)
        commandes.avertir_si_facteur_arrete(conn, identifiant)
        return 0
    finally:
        conn.close()


def executer(args) -> int:
    try:
        return _envoyer(args)
    except (ErreurProjet, ValueError) as e:
        return _erreur(str(e))
