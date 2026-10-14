"""Le journal des actions : « aucune action non journalisée ».

La table `journal` est créée par `cime init` ; l'hôte y écrit seulement. Une action
suit un protocole en deux temps (ouvrir la ligne, exécuter, clore la ligne) : elle ne
peut donc jamais avoir lieu sans trace, même si le processus meurt au milieu.

Forme des lignes (`GET /api/journal?limite=N` → `{"lignes": [...]}`, récent d'abord) :

| action               | cible              | details                                   |
|----------------------|--------------------|-------------------------------------------|
| autoriser / refuser  | `perm-<demande_id>`| `{agent, outil, commande}` ou `{agent, outil, chemin}` (`commande: null` si inconnue ; tronqué à 200) |
| trancher             | `msg-<id>`         | `{question, choix}` (question : titre de l'attente, null si absente ; choix tronqué à 200) |
| deposer              | `msg-<id>`         | `{fichier, octets}` ou `{fichiers, octets}` (chemins relatifs au projet) |
| lu                   | `msg-<id>`         | `{rapport}` (champ `fichier` du message, null si introuvable) ; `{message}` pour un message du registre clos |
| demander             | `assistant`        | `{texte}` (la demande, une ligne, ≤ 160 caractères) |
| cloturer             | `equipe:<nom>`     | `{demande}` (`msg-<id>` de la demande retenue, null si refus avant) |
| fusions_auto         | `projet`           | `{valeur, avant, reglage_id}` (`avant` : `active`/`inactive` lu avant la commande, null si la valeur est refusée ; `reglage_id` : entier imprimé par la commande, null sinon) |
| plafond              | `machine`          | `{valeur, avant, horodatage}` (`avant` : plafond de la machine lu avant la commande, entier, null si la valeur est refusée ; `horodatage` : imprimé par la commande, null sinon) |

Les valeurs connues seulement après l'action (chemins rangés, demande retenue) sont
ajoutées par `faire` en modifiant le dict `details` : `executer_action` le réécrit
(`completer_details`) avant de clore la ligne, qui existe donc toujours avant l'action.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Awaitable, Callable
from contextlib import closing
from datetime import datetime
from pathlib import Path

from starlette.responses import JSONResponse

AUTEURS = ("utilisateur", "assistant")
EN_COURS = "erreur: en cours"
MSG_ABSENT = "registre absent : lancez cime init"
MSG_INCOMPLET = "registre absent ou incomplet : lance `cime init`"


class RegistreAbsent(RuntimeError):
    pass


def _verifier_auteur(auteur: str) -> None:
    if auteur not in AUTEURS:
        raise ValueError(f"auteur inconnu : {auteur!r} (attendu : {' ou '.join(AUTEURS)})")


class Journal:
    def __init__(self, chemin_registre: Path, horloge: Callable[[], datetime]):
        self.chemin = Path(chemin_registre)
        self.horloge = horloge

    def _connexion(self) -> sqlite3.Connection:
        # Une connexion par opération : aucun état partagé entre threads.
        # mode=rw : l'hôte démarre même sans registre lisible ; il ne doit jamais en créer un.
        con = sqlite3.connect(f"{self.chemin.resolve().as_uri()}?mode=rw", uri=True, timeout=5)
        con.execute("PRAGMA busy_timeout=5000")
        con.execute("PRAGMA journal_mode=WAL")
        return con

    def preparer(self) -> None:
        """Vérifie le fichier et la table `journal`. Ne crée jamais rien."""
        if not self.chemin.is_file():
            raise RegistreAbsent(MSG_ABSENT)
        try:
            # mode=ro : sqlite3.connect créerait sinon un fichier absent.
            with closing(sqlite3.connect(f"{self.chemin.resolve().as_uri()}?mode=ro", uri=True, timeout=5)) as con:
                trouve = con.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='journal'"
                ).fetchone()
        except sqlite3.Error as e:
            raise RegistreAbsent(MSG_INCOMPLET) from e
        if trouve is None:
            raise RegistreAbsent(MSG_INCOMPLET)

    def _horodatage(self) -> str:
        t = self.horloge()
        return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"

    def ouvrir_ligne(self, auteur: str, action: str, cible: str | None, details: object) -> int:
        _verifier_auteur(auteur)
        with closing(self._connexion()) as con:
            with con:
                cur = con.execute(
                    "INSERT INTO journal(horodatage, auteur, action, cible, details, resultat)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        self._horodatage(),
                        auteur,
                        action,
                        cible,
                        json.dumps(details, ensure_ascii=False),
                        EN_COURS,
                    ),
                )
            return cur.lastrowid

    def completer_details(self, id: int, details: object) -> None:
        with closing(self._connexion()) as con:
            with con:
                cur = con.execute(
                    "UPDATE journal SET details=? WHERE id=?",
                    (json.dumps(details, ensure_ascii=False), id),
                )
            if cur.rowcount != 1:
                raise RuntimeError(f"ligne de journal {id} introuvable")

    def clore_ligne(self, id: int, resultat: str) -> None:
        with closing(self._connexion()) as con:
            with con:
                cur = con.execute("UPDATE journal SET resultat=? WHERE id=?", (resultat, id))
            if cur.rowcount != 1:
                raise RuntimeError(f"ligne de journal {id} introuvable")

    def a_reussi(self, action: str, cible: str | None) -> bool:
        """Vrai si le journal contient une ligne `ok` pour cette action et cette cible."""
        with closing(self._connexion()) as con:
            ligne = con.execute(
                "SELECT 1 FROM journal WHERE action = ? AND cible IS ? AND resultat = 'ok' LIMIT 1",
                (action, cible),
            ).fetchone()
        return ligne is not None

    def dernieres(self, limite: int) -> list[dict]:
        with closing(self._connexion()) as con:
            con.row_factory = sqlite3.Row
            lignes = con.execute(
                "SELECT id, horodatage, auteur, action, cible, details, resultat"
                " FROM journal ORDER BY id DESC LIMIT ?",
                (limite,),
            ).fetchall()
        sortie = []
        for l in lignes:
            d = dict(l)
            if d["details"] is not None:
                try:
                    d["details"] = json.loads(d["details"])
                except ValueError:
                    pass  # texte non JSON écrit par un autre outil : rendu tel quel
            sortie.append(d)
        return sortie


async def executer_action(
    journal: Journal,
    auteur: str,
    action: str,
    cible: str | None,
    details: object,
    faire: Callable[..., Awaitable[tuple[str, str]]],
    avec_id: bool = False,
) -> JSONResponse:
    """`avec_id` : `faire` reçoit en argument l'id de la ligne de journal (elle existe déjà)."""
    _verifier_auteur(auteur)
    initial = json.dumps(details, ensure_ascii=False)
    # 1. la trace d'abord : si elle échoue, l'action n'a pas lieu.
    try:
        id_ligne = await asyncio.to_thread(journal.ouvrir_ligne, auteur, action, cible, details)
    except Exception:
        return JSONResponse(
            {"resultat": "erreur", "message": "journal indisponible, action non exécutée"},
            status_code=503,
        )
    # 2. l'action
    try:
        resultat, message = await (faire(id_ligne) if avec_id else faire())
        if resultat not in ("ok", "refuse", "erreur"):
            resultat, message = "erreur", f"résultat d'action invalide : {resultat!r}"
    except Exception as e:
        resultat, message = "erreur", f"{type(e).__name__}: {e}"
    # 3. la clôture (après avoir complété `details` si `faire` y a ajouté des valeurs)
    if json.dumps(details, ensure_ascii=False) != initial:
        try:
            await asyncio.to_thread(journal.completer_details, id_ligne, details)
        except Exception:
            pass  # la ligne garde ses details d'ouverture ; le résultat est noté quand même
    note = resultat if resultat != "erreur" else f"erreur: {message}"
    try:
        await asyncio.to_thread(journal.clore_ligne, id_ligne, note)
    except Exception:
        return JSONResponse(
            {
                "resultat": "erreur",
                "message": "l'action a été exécutée (" + f"{resultat}: {message}" + ") mais son résultat "
                "n'a pas pu être noté au journal ; la ligne « en cours » reste comme trace",
            }
        )
    return JSONResponse({"resultat": resultat, "message": message})
