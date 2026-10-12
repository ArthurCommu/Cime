"""Commandes qui n'inscrivent que des lignes au registre : repondre, accorder, refuser.

Aucune ne touche un terminal. Codes de sortie : 0 ok, 2 refus de précondition, 1 erreur.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from cime.fondation.nom import VAR_PROJET
from cime.fondation.projet import ErreurProjet, equipe_de
from cime.fondation.registre import (horodatage, inscrire_message,
                                     inscrire_transition, ouvrir)
from cime.signaux import autorisations, echeances, matrice, obligations
from cime.signaux.identite import ErreurIdentite, appelant

PEREMPTION_BATTEMENT_S = 30
NATURES_REPONSE = ("reponse", "compte_rendu", "travail_pret", "question", "rapport_utilisateur")


class Refus(Exception):
    def __init__(self, message: str, code: int = 2):
        super().__init__(message)
        self.code = code


def projet_courant():
    from cime.fondation.envoyer import _projet
    projet = _projet()
    if projet is None:
        raise Refus(f"{VAR_PROJET} absent (ou ne désigne pas un projet) : lance cette "
                    "commande depuis un agent lancé par `cime lancer`", 1)
    return projet


def identite_appelant() -> str:
    try:
        return appelant()
    except ErreurIdentite as e:
        raise Refus(str(e)) from None


def lancer_commande(nom: str, fonction, args) -> int:
    try:
        return fonction(args)
    except Refus as e:
        print(f"{nom} : {e}", file=sys.stderr)
        return e.code
    except (ErreurProjet, ValueError) as e:
        print(f"{nom} : {e}", file=sys.stderr)
        return 1


def secondes_depuis(iso: str) -> float:
    lu = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - lu).total_seconds()


def facteur_arrete(conn) -> int | None | bool:
    """False si le facteur bat ; sinon le nombre de secondes depuis son dernier battement,
    ou None s'il n'a jamais battu."""
    ligne = conn.execute("SELECT battement FROM facteur WHERE id = 1").fetchone()
    if ligne is None:
        return None
    age = int(secondes_depuis(ligne[0]))
    return age if age > PEREMPTION_BATTEMENT_S else False


def avertir_si_facteur_arrete(conn, identifiant: int) -> None:
    etat = facteur_arrete(conn)
    if etat is False:
        return
    depuis = "depuis toujours" if etat is None else f"depuis {etat} s"
    print(f"FACTEUR ARRÊTÉ {depuis} — message #{identifiant} en file", file=sys.stderr)


def inscrire(conn, *, de, a, nature, resume, fichier=None, en_reponse_a=None,
             equipe=None, objet=None, corps=None, attend=None, auteur=None,
             preuve=None, dans_transaction=None) -> int:
    """Une transaction : message + obligation (selon la matrice) + transition `inscrit`."""
    with conn:
        identifiant = inscrire_sans_commit(
            conn, de=de, a=a, nature=nature, resume=resume, fichier=fichier,
            en_reponse_a=en_reponse_a, equipe=equipe, objet=objet, corps=corps, attend=attend,
            auteur=auteur, preuve=preuve)
        if dans_transaction is not None:
            dans_transaction(identifiant)
    return identifiant


def inscrire_sans_commit(conn, *, de, a, nature, resume, fichier=None, en_reponse_a=None,
                         equipe=None, objet=None, corps=None, attend=None, auteur=None,
                         preuve=None) -> int:
    """Comme `inscrire`, dans la transaction de l'appelant (qui la valide ou l'annule)."""
    identifiant = inscrire_message(
        conn, de=de, a=a, nature=nature, resume=resume, fichier=fichier,
        en_reponse_a=en_reponse_a, equipe=equipe, objet=objet, corps=corps,
        commit=False)
    regle = matrice.obligation(nature, a, objet, attend)
    if regle is not None:
        debiteur, attendu = regle
        h = conn.execute("SELECT horodatage FROM messages WHERE id = ?",
                         (identifiant,)).fetchone()[0]
        obligations.ouvrir_obligation(
            conn, identifiant, debiteur, attendu,
            echeances.echeance(h, echeances.delai(nature, attendu, debiteur, objet, corps)),
            commit=False)
    inscrire_transition(
        conn, identifiant, "inscrit", auteur or de,
        preuve or {"cmd": "envoyer", "pid": os.getpid()}, commit=False)
    return identifiant


def _message(conn, identifiant: int):
    ligne = conn.execute(
        "SELECT id, de, a, nature, resume, equipe, objet, corps, horodatage"
        " FROM messages WHERE id = ?", (identifiant,)).fetchone()
    if ligne is None:
        raise Refus(f"aucun message n°{identifiant}")
    cles = ("id", "de", "a", "nature", "resume", "equipe", "objet", "corps", "horodatage")
    return dict(zip(cles, ligne))


def _fichier_relatif(projet, fichier):
    if not fichier:
        return None
    chemin = (Path.cwd() / fichier).resolve()  # relatif : depuis le dossier de l'appelant
    if not chemin.is_relative_to(projet):
        raise Refus(f"fichier hors du projet : {fichier}", 1)
    if not chemin.exists():
        raise Refus(f"fichier introuvable : {fichier}", 1)
    return str(chemin.relative_to(projet))


def _exiger_ouverte(conn, cible, moi):
    if cible["a"] != moi:
        raise Refus(f"le message #{cible['id']} n'est pas adressé à {moi} "
                    f"(destinataire : {cible['a']})")
    ouverte = obligations.ouverte_pour(conn, cible["id"])
    if ouverte is None:
        raise Refus(f"le message #{cible['id']} n'a plus d'obligation ouverte "
                    "(déjà satisfaite)")
    return ouverte


def _repondre(args) -> int:
    moi = identite_appelant()
    projet = projet_courant()
    nature = args.nature or "reponse"
    if nature not in NATURES_REPONSE:
        raise Refus(f"nature {nature!r} impossible avec repondre "
                    f"(permises : {', '.join(NATURES_REPONSE)})")
    suites = getattr(args, "suite", None)
    if suites and nature != "travail_pret":
        raise Refus("--suite n'a de sens que pour un travail_pret")
    conn = ouvrir(projet)
    try:
        cible = _message(conn, args.id)
        if cible["de"] == "cime":
            raise Refus(f"le message #{cible['id']} vient de cime : une réponse ne pourrait jamais "
                        "lui être livrée. L'accusé suffit (le tour de l'agent accuse réception) ; "
                        "pour rendre compte, écris à ton supérieur : "
                        "`cime envoyer --a <supérieur> …`")
        origine = _exiger_ouverte(conn, cible, moi)
        a = cible["de"]
        if nature == "rapport_utilisateur":
            if cible["nature"] != "demande_cloture":
                raise Refus("rapport_utilisateur ne répond qu'à une demande_cloture "
                            "(sinon : `cime envoyer --a utilisateur --nature rapport_utilisateur`)")
            a = "utilisateur"
        motif = matrice.verifier(moi, a, nature, projet, via_repondre=True)
        if motif:
            raise Refus(motif)
        preuve = {"cmd": "repondre", "pid": os.getpid()}
        if suites:
            if a != "assistant":
                raise Refus("--suite n'a de sens que pour un travail_pret adressé à l'Assistant")
            from cime.signaux import suites as suites_mod
            preuve["suites"] = suites_mod.valider(suites, projet)
        fichier = _fichier_relatif(projet, args.fichier)
        equipe = cible["equipe"] or equipe_de(projet, moi) or equipe_de(projet, a)

        def clore(nouveau: int) -> None:
            if nature == "compte_rendu":
                debiteur, attendu, _ = origine
                delai = echeances.delai(cible["nature"], attendu, debiteur, cible["objet"],
                                        cible["corps"])
                obligations.repousser(
                    conn, cible["id"],
                    echeances.echeance(horodatage(), delai), commit=False)
                return
            obligations.satisfaire(conn, cible["id"], nouveau, commit=False)
            inscrire_transition(conn, cible["id"], "clos", moi,
                                {"par_message": nouveau}, commit=False)

        identifiant = inscrire(conn, de=moi, a=a, nature=nature, resume=args.resume,
                               fichier=fichier, en_reponse_a=cible["id"], equipe=equipe,
                               preuve=preuve, dans_transaction=clore)
        print(identifiant)
        avertir_si_facteur_arrete(conn, identifiant)
        return 0
    finally:
        conn.close()


def repondre(args) -> int:
    return lancer_commande("repondre", _repondre, args)


def _exiger_autorisation(conn, projet, cible, moi, nature) -> str | None:
    """Qui peut répondre à une demande d'autorisation, selon sa classe (lue
    dans le `corps` ; illisible ⇒ `reserve`). Le code décide, pas le jugement. `refuser` : le
    débiteur de l'obligation, jamais refusé pour une raison de classe. `accorder` : l'utilisateur, toute
    demande encore en attente ; les autres selon la classe. Renvoie la classe."""
    classe, theme = autorisations.classe_de(cible["corps"])
    demande_id = (cible["objet"] or "")[len(autorisations.PREFIXE):]
    if nature == "accord" and moi == "utilisateur":
        if autorisations.tranchee(conn, demande_id, cible["horodatage"]) \
                and obligations.ouverte_pour(conn, cible["id"]) is None:
            raise Refus(f"la demande {demande_id} est déjà tranchée")
        return classe
    if nature == "accord":
        if classe == "reserve":
            raise Refus(f"réservé à l'utilisateur : {theme}")
        if classe == "autonome":
            if moi != "assistant":
                raise Refus("une demande autonome est accordée par l'utilisateur, ou par l'Assistant "
                            "en mode autonome")
            if not autorisations.mode_actif(projet):
                raise Refus("le mode autonome n'est plus actif : l'accord est à l'utilisateur")
            if cible["a"] != moi:   # adressée à l'utilisateur quand le mode était coupé
                if autorisations.tranchee(conn, demande_id, cible["horodatage"]):
                    raise Refus(f"la demande {demande_id} est déjà tranchée")
                return classe
    _exiger_ouverte(conn, cible, moi)
    return classe


def _annonce_autorisation(conn, cible, accord: int) -> int:
    """L'accord d'une demande `autonome` par l'Assistant s'annonce à l'utilisateur, dans la
    transaction de l'accord. Aucune obligation (matrice)."""
    demande_id = cible["objet"][len(autorisations.PREFIXE):]
    donnees = echeances.corps_autorisation(cible["corps"]) or {}
    agent = autorisations.agent_de(conn, demande_id) or (cible["resume"] or "?").split(" ", 1)[0]
    fin = ", accordé"
    resume = autorisations.tronquer(
        f"{agent} : {donnees.get('outil') or '?'} {donnees.get('cible') or ''}".rstrip(),
        autorisations.RESUME_MAX - len(fin)) + fin
    return inscrire_sans_commit(
        conn, de="assistant", a="utilisateur", nature="rapport_utilisateur", resume=resume,
        en_reponse_a=None, equipe=cible["equipe"],
        objet=f"{autorisations.PREFIXE_ANNONCE}{demande_id}",
        preuve={"cmd": "accorder", "pid": os.getpid(), "accord": accord})


def _decision(args, nature: str) -> int:
    moi = identite_appelant()
    projet = projet_courant()
    conn = ouvrir(projet)
    try:
        cible = _message(conn, args.id)
        objet = cible["objet"] or ""
        classe = None
        if cible["nature"] == "signalement" and objet.startswith(autorisations.PREFIXE):
            # on inscrit seulement l'accord/le refus : l'hôte relit l'écran et tape la touche
            classe = _exiger_autorisation(conn, projet, cible, moi, nature)
        elif cible["nature"] == "demande_accord":
            _exiger_ouverte(conn, cible, moi)
        elif cible["nature"] == "decision_utilisateur" and objet.startswith(("chantier:", "fusion:")):
            if moi != "utilisateur":
                raise Refus(f"l'accord pour {objet} est celui de l'utilisateur seul")
            _exiger_ouverte(conn, cible, moi)
        else:
            raise Refus(f"le message #{cible['id']} ({cible['nature']}) n'est pas une "
                        "demande d'accord")
        annoncer = nature == "accord" and classe == "autonome" and moi == "assistant"
        corps = None
        if nature == "accord":
            donnees = {}
            if objet.startswith("lancer-worker:"):
                if not getattr(args, "modele", None):
                    raise Refus(f"--modele obligatoire pour accorder {objet}")
                donnees["modele"] = args.modele
            elif getattr(args, "modele", None):
                donnees["modele"] = args.modele
            if getattr(args, "parallele", False):
                donnees["parallele"] = True
            corps = json.dumps(donnees, ensure_ascii=False) if donnees else None
            resume = f"accord : {objet or cible['resume']}"[:160]
        else:
            resume = args.motif
        cmd = "accorder" if nature == "accord" else "refuser"

        def clore(nouveau: int) -> None:
            obligations.satisfaire(conn, cible["id"], nouveau, commit=False)
            inscrire_transition(conn, cible["id"], "clos", moi,
                                {"par_message": nouveau}, commit=False)
            if annoncer:
                _annonce_autorisation(conn, cible, nouveau)

        identifiant = inscrire(conn, de=moi, a=cible["de"], nature=nature, resume=resume,
                               en_reponse_a=cible["id"], equipe=cible["equipe"],
                               objet=cible["objet"], corps=corps,
                               preuve={"cmd": cmd, "pid": os.getpid()},
                               dans_transaction=clore)
        print(identifiant)
        avertir_si_facteur_arrete(conn, identifiant)
        return 0
    finally:
        conn.close()


def accorder(args) -> int:
    return lancer_commande("accorder", lambda a: _decision(a, "accord"), args)


def refuser(args) -> int:
    return lancer_commande("refuser", lambda a: _decision(a, "refus"), args)
