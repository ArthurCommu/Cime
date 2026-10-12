"""Registre SQLite du projet : messages, transitions d'état et événements."""

import json
from contextlib import nullcontext
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

NATURES = (
    "consigne", "question", "reponse", "compte_rendu", "travail_pret",
    "demande_cloture", "signalement", "rapport_utilisateur", "decision_utilisateur",
    "donnee_utilisateur", "demande_accord", "accord", "refus", "relance",
)

CORPS_MAX = 4000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY, horodatage TEXT NOT NULL, de TEXT NOT NULL, a TEXT NOT NULL,
  nature TEXT NOT NULL, resume TEXT NOT NULL, fichier TEXT, en_reponse_a INTEGER,
  equipe TEXT);
CREATE TABLE IF NOT EXISTS evenements (
  id INTEGER PRIMARY KEY, horodatage TEXT NOT NULL, agent TEXT, session_id TEXT,
  evenement TEXT NOT NULL, details TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS journal (
  id INTEGER PRIMARY KEY, horodatage TEXT NOT NULL, auteur TEXT NOT NULL,
  action TEXT NOT NULL, cible TEXT, details TEXT, resultat TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS evenements_agent_evenement ON evenements(agent, evenement, horodatage, id);
CREATE INDEX IF NOT EXISTS evenements_agent ON evenements(agent, horodatage, id);
CREATE INDEX IF NOT EXISTS evenements_evenement ON evenements(evenement, horodatage, id);
CREATE INDEX IF NOT EXISTS messages_horodatage ON messages(horodatage, id);
CREATE INDEX IF NOT EXISTS messages_reponse ON messages(en_reponse_a, nature);
CREATE INDEX IF NOT EXISTS messages_nature ON messages(nature, horodatage, id);
CREATE TABLE IF NOT EXISTS courriers (
  id INTEGER PRIMARY KEY, a TEXT NOT NULL, voie TEXT NOT NULL,
  cree TEXT NOT NULL, expire TEXT NOT NULL,
  etat TEXT NOT NULL CHECK (etat IN ('ouvert','acquitte','echoue')),
  tentative INTEGER NOT NULL DEFAULT 1);
CREATE UNIQUE INDEX IF NOT EXISTS courrier_ouvert ON courriers(a) WHERE etat = 'ouvert';
CREATE TABLE IF NOT EXISTS transitions (
  id INTEGER PRIMARY KEY, horodatage TEXT NOT NULL, message_id INTEGER NOT NULL,
  etat TEXT NOT NULL CHECK (etat IN ('inscrit','livre','pris_en_compte','clos','echec','abandonne')),
  courrier_id INTEGER, auteur TEXT NOT NULL, preuve TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS transitions_message ON transitions(message_id, id);
CREATE TABLE IF NOT EXISTS obligations (
  id INTEGER PRIMARY KEY, message_id INTEGER NOT NULL UNIQUE, debiteur TEXT NOT NULL,
  attendu TEXT NOT NULL, echeance TEXT,
  etat TEXT NOT NULL CHECK (etat IN ('ouverte','satisfaite','abandonnee')),
  relances INTEGER NOT NULL DEFAULT 0, prochaine TEXT, ferme_par INTEGER);
CREATE INDEX IF NOT EXISTS obligations_debiteur ON obligations(debiteur, etat);
CREATE TABLE IF NOT EXISTS ordres (
  id INTEGER PRIMARY KEY, horodatage TEXT NOT NULL, auteur TEXT NOT NULL,
  verbe TEXT NOT NULL CHECK (verbe IN ('lancer','fermer','compacter','capturer')),
  cible TEXT NOT NULL, parametres TEXT NOT NULL,
  etat TEXT NOT NULL CHECK (etat IN ('en_file','execute','refuse','echec')),
  resultat TEXT, fini TEXT);
CREATE TABLE IF NOT EXISTS facteur (
  id INTEGER PRIMARY KEY CHECK (id = 1), battement TEXT NOT NULL, version TEXT);
CREATE TABLE IF NOT EXISTS occupation (
  agent TEXT PRIMARY KEY, occupe_par TEXT, maj TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reglages_projet (
  id INTEGER PRIMARY KEY, horodatage TEXT NOT NULL, cle TEXT NOT NULL,
  valeur TEXT NOT NULL, auteur TEXT NOT NULL, details TEXT);
"""

# Index sur les colonnes ajoutées à `messages` : créés après les ALTER TABLE.
_INDEX_MESSAGES_2_0 = """
CREATE INDEX IF NOT EXISTS messages_a ON messages(a, id);
CREATE INDEX IF NOT EXISTS messages_objet ON messages(objet);
"""


def horodatage() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def chemin_registre(projet: Path) -> Path:
    return Path(projet) / ".orga" / "etat" / "registre.sqlite"


def ouvrir(projet: Path) -> sqlite3.Connection:
    chemin = chemin_registre(projet)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(chemin, timeout=2)
    conn.execute("PRAGMA busy_timeout=2000")
    conn.execute("PRAGMA journal_mode=WAL")
    for instruction in _SCHEMA.split(";"):
        if instruction.strip():
            conn.execute(instruction)
    colonnes = {ligne[1] for ligne in conn.execute("PRAGMA table_info(messages)")}
    for colonne in ("objet", "corps"):
        if colonne not in colonnes:
            conn.execute(f"ALTER TABLE messages ADD COLUMN {colonne} TEXT")
    for instruction in _INDEX_MESSAGES_2_0.split(";"):
        if instruction.strip():
            conn.execute(instruction)
    conn.commit()
    return conn


def inscrire_message(conn, *, de, a, nature, resume, fichier=None,
                     en_reponse_a=None, equipe=None, objet=None, corps=None, commit=True) -> int:
    if nature not in NATURES:
        raise ValueError(f"nature inconnue : {nature!r} (attendu : {', '.join(NATURES)})")
    if "\n" in resume or "\r" in resume:
        raise ValueError("le résumé tient sur une seule ligne")
    if len(resume) > 160:
        raise ValueError(f"résumé trop long : {len(resume)} caractères (max 160)")
    if corps is not None and len(corps) > CORPS_MAX:
        raise ValueError(f"corps trop long : {len(corps)} caractères (max {CORPS_MAX})")
    if en_reponse_a is not None and conn.execute(
        "SELECT 1 FROM messages WHERE id = ?", (en_reponse_a,)
    ).fetchone() is None:
        raise ValueError(f"en_reponse_a : aucun message n°{en_reponse_a}")
    with (conn if commit else nullcontext()):
        cur = conn.execute(
            "INSERT INTO messages (horodatage, de, a, nature, resume, fichier,"
            " en_reponse_a, equipe, objet, corps) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (horodatage(), de, a, nature, resume, fichier, en_reponse_a, equipe,
             objet, corps),
        )
    return cur.lastrowid


def inscrire_evenement(conn, *, agent, session_id, evenement, details: dict) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO evenements (horodatage, agent, session_id, evenement,"
            " details) VALUES (?, ?, ?, ?, ?)",
            (horodatage(), agent, session_id, evenement,
             json.dumps(details, ensure_ascii=False)),
        )
    return cur.lastrowid


def inscrire_transition(conn, message_id, etat, auteur, preuve: dict,
                        courrier_id=None, commit=True) -> int:
    with (conn if commit else nullcontext()):
        cur = conn.execute(
            "INSERT INTO transitions (horodatage, message_id, etat, courrier_id,"
            " auteur, preuve) VALUES (?, ?, ?, ?, ?, ?)",
            (horodatage(), message_id, etat, courrier_id, auteur,
             json.dumps(preuve, ensure_ascii=False)),
        )
    return cur.lastrowid


def etat_message(conn, id) -> str | None:
    ligne = conn.execute(
        "SELECT etat FROM transitions WHERE message_id = ? ORDER BY id DESC LIMIT 1",
        (id,)).fetchone()
    return ligne[0] if ligne else None
