"""Les réponses de l'utilisateur à l'Assistant : trancher, déposer, marquer lu.

L'hôte n'écrit jamais dans le registre des messages : il range d'abord la réponse sur
disque (elle ne doit jamais être perdue), puis demande à `cime envoyer` de prévenir
l'Assistant. Si l'envoi échoue, le fichier reste et le message d'erreur le dit.
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import sqlite3
from pathlib import Path

from starlette.datastructures import UploadFile
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .journal import MSG_ABSENT, executer_action

REPONSE_MAX = 20_000
RESUME_MAX = 160
TOTAL_DEPOT_MAX = 100 * 1024 * 1024
NOM_MAX = 200
CHOIX_MAX = 200
DELAI_ENVOI_S = 15

_ATTENTE = re.compile(r"msg-([0-9]{1,9})")
_HORS_NOM = re.compile(r"[^A-Za-z0-9._-]")


def _entier_du_message(attente_id) -> int | None:
    if not isinstance(attente_id, str):
        return None
    m = _ATTENTE.fullmatch(attente_id)
    return int(m.group(1)) if m else None


def _verifier_attente(contexte, attente_id, nature: str) -> tuple[int | None, str]:
    """(numéro du message, "") si l'attente existe avec la nature voulue, sinon (None, raison)."""
    numero = _entier_du_message(attente_id)
    if numero is None:
        return None, "attente_id invalide (attendu : msg-<entier>)"
    instantane = contexte.rafraichisseur.instantane
    attentes = (instantane or {}).get("attentes_utilisateur") or []
    if not any(
        isinstance(a, dict) and a.get("id") == attente_id and a.get("nature") == nature
        for a in attentes
    ):
        return None, f"{attente_id} n'est pas une attente de nature « {nature} » en cours"
    return numero, ""


def nettoyer_nom(brut: str | None) -> str:
    """Nom de base seul, caractères [A-Za-z0-9._-], pas de point initial ; vide → `fichier`."""
    nom = (brut or "").replace("\\", "/").split("/")[-1]
    nom = _HORS_NOM.sub("_", nom).lstrip(".")[:NOM_MAX]
    return nom or "fichier"


def _ouvrir_sans_ecraser(dossier: Path, nom: str):
    """Ouvre `dossier/nom` en création exclusive ; en cas de doublon : nom-2.ext, nom-3.ext…"""
    base, point, ext = nom.rpartition(".") if "." in nom[1:] else (nom, "", "")
    n = 1
    while True:
        candidat = nom if n == 1 else f"{base}-{n}{point}{ext}"
        try:
            return candidat, open(dossier / candidat, "xb")
        except FileExistsError:
            n += 1


def _resume_trancher(reponse: str) -> str:
    debut = "L'utilisateur a tranché : "
    ligne = " ".join(reponse.split())
    place = RESUME_MAX - len(debut)
    if len(ligne) > place:
        ligne = ligne[: place - 1].rstrip() + "…"
    return debut + ligne


async def _envoyer(contexte, nature_numero: int, resume: str, fichier: str | None) -> tuple[bool, str]:
    """Lance `cime repondre <numéro>` par les gardes (le registre lie la réponse à la
    question et ferme l'obligation de l'utilisateur). (True, "") ou (False, message d'erreur)."""
    gardes = contexte.gardes()
    argv = [*gardes.repondre, str(nature_numero)]
    if fichier:
        argv += ["--fichier", fichier]
    argv.append(resume)
    env = dict(os.environ)
    env["CIME_AGENT"] = "utilisateur"
    env["CIME_PROJET"] = str(Path(contexte.projet).resolve())
    try:
        # `--fichier` est relatif au projet : lancer depuis sa racine.
        r = await gardes.aexecuter(argv, timeout=DELAI_ENVOI_S, env=env, cwd=env["CIME_PROJET"])
    except FileNotFoundError:
        return False, f"commande d'envoi introuvable : {gardes.repondre[0]}"
    except Exception as e:  # délai dépassé, OSError, commande refusée par les gardes…
        return False, f"commande d'envoi en échec ({type(e).__name__}: {e})"
    if r.returncode != 0:
        detail = (r.stderr or r.stdout or "").strip() or f"code de sortie {r.returncode}"
        return False, detail
    return True, ""


DEMANDE_MAX = 160


async def demander_a_l_assistant(contexte, corps) -> object:
    """`POST /api/actions/demander` {texte} : la page formule une demande à l'Assistant.
    Un acte de coordination n'est jamais envoyé à un coordinateur : le destinataire est imposé."""
    texte = corps.get("texte") if isinstance(corps, dict) else None
    ligne = " ".join(texte.split()) if isinstance(texte, str) else ""
    details: dict = {"texte": ligne[:DEMANDE_MAX] or None}

    async def faire():
        if not ligne:
            return "refuse", "la demande est vide"
        if len(ligne) > DEMANDE_MAX:
            return "refuse", f"demande trop longue ({len(ligne)} > {DEMANDE_MAX} caractères)"
        if ligne.startswith("-"):
            return "refuse", "la demande ne peut pas commencer par un tiret"
        gardes = contexte.gardes()
        env = dict(os.environ)
        env["CIME_AGENT"] = "utilisateur"
        env["CIME_PROJET"] = str(Path(contexte.projet).resolve())
        argv = [*gardes.envoyer, "--a", "assistant", "--nature", "consigne", "--attend", "reponse",
                "--objet", "demande-page", ligne]
        try:
            r = await gardes.aexecuter(argv, timeout=DELAI_ENVOI_S, env=env, cwd=env["CIME_PROJET"])
        except FileNotFoundError:
            return "erreur", f"commande d'envoi introuvable : {gardes.envoyer[0]}"
        except Exception as e:
            return "erreur", f"commande d'envoi en échec ({type(e).__name__}: {e})"
        if r.returncode != 0:
            return "erreur", (r.stderr or r.stdout or "").strip() or f"code de sortie {r.returncode}"
        return "ok", "demande transmise à l'Assistant"

    return await executer_action(contexte.journal, "utilisateur", "demander", "assistant", details, faire)


PREFIXES_ACCORD = ("fusion:", "chantier:")
MOTIF_MAX = 160


def _decision_d_accord(contexte, attente_id) -> tuple[int | None, str | None, str]:
    """(numéro, objet, "") si `attente_id` est une `decision_utilisateur` d'objet `fusion:…` ou
    `chantier:…`, ouverte et adressée à `utilisateur` ; sinon (None, None, raison). C'est la garde de
    l'hôte : ces deux boutons n'ont pas d'autre usage, et aucun ne lance `git`. L'instantané dit
    l'attente ; le registre confirme (adressée à l'utilisateur, obligation ouverte)."""
    numero = _entier_du_message(attente_id)
    if numero is None:
        return None, None, "attente_id invalide (attendu : msg-<entier>)"
    attente = _dans_instantane(contexte, "attentes_utilisateur", attente_id)
    if attente is None or attente.get("nature") != "decision":
        return None, None, f"{attente_id} n'est pas une décision en cours"
    objet = attente.get("objet")
    if not isinstance(objet, str) or not objet.startswith(PREFIXES_ACCORD):
        return None, None, f"{attente_id} n'est pas un accord de fusion ou de chantier"
    chemin = Path(contexte.projet) / ".orga" / "etat" / "registre.sqlite"
    try:
        con = sqlite3.connect(f"{chemin.resolve().as_uri()}?mode=ro", uri=True, timeout=2)
        try:
            ligne = con.execute(
                "SELECT m.a, m.nature, m.objet, o.etat FROM messages m LEFT JOIN obligations o"
                " ON o.message_id = m.id WHERE m.id = ?", (numero,)).fetchone()
        finally:
            con.close()
    except sqlite3.Error as e:
        return None, None, f"registre illisible : {e}"
    if ligne is None or ligne[:3] != ("utilisateur", "decision_utilisateur", objet):
        return None, None, f"{attente_id} n'est pas une décision adressée à l'utilisateur pour {objet}"
    if ligne[3] != "ouverte":
        return None, None, f"{attente_id} n'a plus d'obligation ouverte (déjà traitée)"
    return numero, objet, ""


async def _decider(contexte, argv_fin: list[str], verbe: str) -> tuple[bool, str]:
    """`cime accorder|refuser …` en tant qu'utilisateur, par les gardes ; jamais autre chose."""
    gardes = contexte.gardes()
    base = getattr(gardes, verbe) or gardes.envoyer
    env = dict(os.environ)
    env["CIME_AGENT"] = "utilisateur"
    env["CIME_PROJET"] = str(Path(contexte.projet).resolve())
    try:
        r = await gardes.aexecuter([*base, *argv_fin], timeout=DELAI_ENVOI_S, env=env, cwd=env["CIME_PROJET"])
    except FileNotFoundError:
        return False, f"commande introuvable : {base[0]}"
    except Exception as e:
        return False, f"commande en échec ({type(e).__name__}: {e})"
    if r.returncode != 0:
        return False, (r.stderr or r.stdout or "").strip() or f"code de sortie {r.returncode}"
    return True, ""


async def accorder_decision(contexte, corps) -> object:
    """`POST /api/actions/accorder` {attente_id} : « Accorder la fusion » / « Accorder le chantier »."""
    attente_id = corps.get("attente_id") if isinstance(corps, dict) else None
    details: dict = {"objet": None}

    async def faire():
        numero, objet, raison = _decision_d_accord(contexte, attente_id)
        if numero is None:
            return "refuse", raison
        details["objet"] = objet
        if await asyncio.to_thread(contexte.journal.a_reussi, "accorder", attente_id):
            return "refuse", "déjà accordé"
        ok, erreur = await _decider(contexte, [str(numero)], "accorder")
        if not ok:
            return "erreur", erreur
        return "ok", f"accord inscrit pour {objet} : l'Assistant en est prévenu"

    return await executer_action(contexte.journal, "utilisateur", "accorder", _cible(attente_id), details, faire)


async def refuser_decision(contexte, corps) -> object:
    """`POST /api/actions/refuser` {attente_id: msg-<n>, motif} : refuse un accord de fusion ou de chantier."""
    attente_id = corps.get("attente_id") if isinstance(corps, dict) else None
    motif = corps.get("motif") if isinstance(corps, dict) else None
    details: dict = {"objet": None, "motif": " ".join(motif.split())[:MOTIF_MAX] if isinstance(motif, str) else None}

    async def faire():
        numero, objet, raison = _decision_d_accord(contexte, attente_id)
        if numero is None:
            return "refuse", raison
        details["objet"] = objet
        if not isinstance(motif, str) or not motif.strip():
            return "refuse", "le motif du refus est vide"
        ligne = " ".join(motif.split())
        if len(ligne) > MOTIF_MAX:
            return "refuse", f"motif trop long ({len(ligne)} > {MOTIF_MAX} caractères)"
        if ligne.startswith("-"):
            return "refuse", "le motif ne peut pas commencer par un tiret"
        ok, erreur = await _decider(contexte, [str(numero), ligne], "refuser")
        if not ok:
            return "erreur", erreur
        return "ok", f"refus inscrit pour {objet} : l'Assistant en est prévenu"

    return await executer_action(contexte.journal, "utilisateur", "refuser", _cible(attente_id), details, faire)


def _dossier_depot(contexte, attente_id: str) -> Path:
    return Path(contexte.projet) / ".orga" / "depots" / attente_id


def _relatif(attente_id: str, *suite: str) -> str:
    return "/".join((".orga", "depots", attente_id, *suite))


def _dans_instantane(contexte, liste: str, id_) -> dict | None:
    instantane = contexte.rafraichisseur.instantane
    for e in (instantane or {}).get(liste) or []:
        if isinstance(e, dict) and e.get("id") == id_:
            return e
    return None


def _details_depot(fichiers: list[str], octets: int) -> dict:
    cle = "fichier" if len(fichiers) == 1 else "fichiers"
    return {cle: fichiers[0] if len(fichiers) == 1 else fichiers, "octets": octets}


def _cible(attente_id) -> str | None:
    return attente_id[:100] if isinstance(attente_id, str) else None


# `msg-<n>` d'un message du registre (9 chiffres au plus, comme `_ATTENTE`)
_LU_MESSAGE = re.compile(r"msg-([1-9][0-9]{0,8})")


def _numero_lu_message(attente_id) -> int | None:
    if not isinstance(attente_id, str):
        return None
    m = _LU_MESSAGE.fullmatch(attente_id)
    return int(m.group(1)) if m else None


def _verifier_lu(conn, n: int) -> tuple[str, str]:
    """Les gardes de « lu », relues sur la base (et non sur l'instantané) dans la transaction."""
    from cime.fondation.registre import etat_message
    ligne = conn.execute("SELECT a, objet FROM messages WHERE id = ?", (n,)).fetchone()
    if ligne is None:
        return "refuse", f"message n°{n} inexistant"
    a, objet = ligne
    if a != "utilisateur":
        return "refuse", "ce message n'est pas adressé à l'utilisateur"
    if objet is not None and objet.startswith("autorisation:"):
        return "refuse", "demande d'autorisation : elle se tranche, elle ne se marque pas lu"
    if conn.execute(
        "SELECT 1 FROM obligations WHERE message_id = ? AND etat = 'ouverte'", (n,)
    ).fetchone() is not None:
        return "refuse", "ce message attend une décision ou une réponse : il ne se marque pas lu"
    etat = etat_message(conn, n)
    if etat == "clos":
        return "refuse", "déjà lu"
    if etat != "livre":
        return "refuse", f"message pas encore livré (dernier état : {etat or 'aucun'})"
    return "ok", ""


def _marquer_lu(projet, n: int, id_ligne: int) -> tuple[str, str]:
    """Clôt le message n. Contrôle et écriture sont dans une même transaction `BEGIN IMMEDIATE` :
    de deux appels simultanés, un seul clôt, l'autre lit `clos` et est refusé. Synchrone (SQLite)."""
    from cime.fondation.registre import chemin_registre, inscrire_transition, ouvrir
    if not chemin_registre(projet).is_file():
        return "erreur", MSG_ABSENT  # `ouvrir` créerait un registre vide : on vérifie d'abord
    conn = ouvrir(projet)
    try:
        conn.execute("BEGIN IMMEDIATE")
        resultat, motif = _verifier_lu(conn, n)
        if resultat != "ok":
            conn.rollback()
            return "refuse", motif
        inscrire_transition(conn, n, "clos", "utilisateur",
                            {"lu_par": "utilisateur", "journal_id": id_ligne}, commit=False)
        conn.commit()
        return "ok", "marqué lu"
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()


def routes(contexte) -> list[Route]:
    async def trancher(request: Request) -> JSONResponse:
        try:
            corps = await request.json()
        except ValueError:
            corps = None
        if not isinstance(corps, dict):
            corps = {}
        attente_id, reponse = corps.get("attente_id"), corps.get("reponse")

        async def faire():
            numero, raison = _verifier_attente(contexte, attente_id, "decision")
            if numero is None:
                return "refuse", raison
            if not isinstance(reponse, str) or not reponse.strip():
                return "refuse", "la réponse est vide"
            if len(reponse) > REPONSE_MAX:
                return "refuse", f"réponse trop longue ({len(reponse)} > {REPONSE_MAX} caractères)"
            # Nouvel essai permis tant qu'aucun `trancher` n'a réussi.
            if await asyncio.to_thread(contexte.journal.a_reussi, "trancher", attente_id):
                return "refuse", "déjà répondu (réponse transmise à l'Assistant)"
            dossier = _dossier_depot(contexte, attente_id)
            chemin = dossier / "reponse.md"

            def ecrire() -> None:
                dossier.mkdir(parents=True, exist_ok=True)
                if chemin.exists():  # essai précédent non transmis : on le garde de côté
                    n = 1
                    while (dossier / f"reponse-{n}.md").exists():
                        n += 1
                    chemin.rename(dossier / f"reponse-{n}.md")
                with open(chemin, "x", encoding="utf-8") as f:
                    f.write(reponse)

            await asyncio.to_thread(ecrire)
            relatif = _relatif(attente_id, "reponse.md")
            ok, erreur = await _envoyer(contexte, numero, _resume_trancher(reponse), relatif)
            if not ok:
                return "erreur", f"{erreur} — réponse conservée dans {relatif}"
            return "ok", "réponse transmise à l'Assistant"

        attente = _dans_instantane(contexte, "attentes_utilisateur", attente_id)
        titre = attente.get("titre") if attente else None
        details = {
            "question": titre if isinstance(titre, str) else None,
            "choix": " ".join(reponse.split())[:CHOIX_MAX] if isinstance(reponse, str) else None,
        }
        return await executer_action(
            contexte.journal, "utilisateur", "trancher", _cible(attente_id), details, faire,
        )

    async def deposer(request: Request) -> JSONResponse:
        try:
            form = await request.form()
        except Exception:
            form = None
        try:
            attente_id = form.get("attente_id") if form is not None else None
            if not isinstance(attente_id, str):
                attente_id = None
            envois = (
                [v for _, v in form.multi_items() if isinstance(v, UploadFile)]
                if form is not None else []
            )
            noms_bruts = [v.filename for v in envois]
            octets = sum(v.size or 0 for v in envois)
            details = _details_depot(noms_bruts, octets)

            async def faire():
                if form is None:
                    return "refuse", "formulaire multipart illisible"
                numero, raison = _verifier_attente(contexte, attente_id, "donnee")
                if numero is None:
                    return "refuse", raison
                if not envois:
                    return "refuse", "aucun fichier déposé"
                # Nouvel essai permis tant qu'aucun `deposer` n'a réussi.
                if await asyncio.to_thread(contexte.journal.a_reussi, "deposer", attente_id):
                    return "refuse", "déjà répondu (dépôt transmis à l'Assistant)"
                total = sum(v.size or 0 for v in envois)
                if total > TOTAL_DEPOT_MAX:
                    return "refuse", (
                        f"dépôt trop volumineux ({total} octets > {TOTAL_DEPOT_MAX}) ; rien n'a été écrit"
                    )
                dossier = _dossier_depot(contexte, attente_id)

                def ranger() -> list[str]:
                    dossier.mkdir(parents=True, exist_ok=True)
                    rangés = []
                    for v in envois:
                        nom, sortie = _ouvrir_sans_ecraser(dossier, nettoyer_nom(v.filename))
                        with sortie:
                            v.file.seek(0)
                            shutil.copyfileobj(v.file, sortie)
                        rangés.append(nom)
                    return rangés

                rangés = await asyncio.to_thread(ranger)
                chemins = [_relatif(attente_id, n) for n in rangés]
                details.clear()
                details.update(_details_depot(chemins, total))
                relatif = _relatif(attente_id) + "/"
                ok, erreur = await _envoyer(
                    contexte, numero,
                    f"L'utilisateur a déposé {len(rangés)} fichier(s) dans {relatif}", None,
                )
                if not ok:
                    return "erreur", f"{erreur} — fichiers conservés dans {relatif}"
                return "ok", f"{len(rangés)} fichier(s) déposé(s) : {', '.join(rangés)}"

            return await executer_action(
                contexte.journal, "utilisateur", "deposer", _cible(attente_id),
                details, faire,
            )
        finally:
            if form is not None:
                await form.close()

    async def lu(request: Request) -> JSONResponse:
        try:
            corps = await request.json()
        except ValueError:
            corps = None
        attente_id = corps.get("attente_id") if isinstance(corps, dict) else None

        # une attente « rapport » a aussi la forme msg-<n> : elle garde le chemin existant
        numero = _numero_lu_message(attente_id)
        if numero is not None and _verifier_attente(contexte, attente_id, "rapport")[0] is None:
            async def faire_message(id_ligne: int):
                return await asyncio.to_thread(_marquer_lu, contexte.projet, numero, id_ligne)

            return await executer_action(
                contexte.journal, "utilisateur", "lu", _cible(attente_id), {"message": str(numero)},
                faire_message, avec_id=True,
            )

        message = _dans_instantane(contexte, "fil", attente_id)
        fichier = message.get("fichier") if message else None
        details = {"rapport": fichier if isinstance(fichier, str) else None}

        async def faire():
            numero, raison = _verifier_attente(contexte, attente_id, "rapport")
            if numero is None:
                return "refuse", raison
            return "ok", "marqué lu (journal seulement, personne n'est prévenu)"

        return await executer_action(
            contexte.journal, "utilisateur", "lu", _cible(attente_id), details, faire,
        )

    async def accorder(request: Request) -> JSONResponse:
        try:
            corps = await request.json()
        except ValueError:
            corps = None
        return await accorder_decision(contexte, corps)

    async def demander(request: Request) -> JSONResponse:
        try:
            corps = await request.json()
        except ValueError:
            corps = None
        return await demander_a_l_assistant(contexte, corps)

    return [
        Route("/api/actions/demander", demander, methods=["POST"]),
        Route("/api/actions/accorder", accorder, methods=["POST"]),
        Route("/api/actions/trancher", trancher, methods=["POST"]),
        Route("/api/actions/deposer", deposer, methods=["POST"]),
        Route("/api/actions/lu", lu, methods=["POST"]),
    ]
