"""Migration d'un ancien registre vers le format courant : idempotente, additive."""
import re
import sqlite3
from pathlib import Path

from cime.fondation.registre import chemin_registre, inscrire_transition, ouvrir
from cime.signaux import obligations

SAUVEGARDE = "registre.sqlite.avant-2.0"
_QUESTION_FICHIER = re.compile(r"pour-assistant-(.+)\.md")


def chemin_sauvegarde(projet: Path) -> Path:
    return chemin_registre(projet).with_name(SAUVEGARDE)


def sauvegarder(projet: Path) -> bool:
    """Copie le registre existant par l'API de sauvegarde SQLite, une seule fois : une
    sauvegarde déjà présente n'est jamais écrasée. True si elle vient d'être faite."""
    source, cible = chemin_registre(projet), chemin_sauvegarde(projet)
    if not source.is_file() or cible.exists():
        return False
    lecture = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    copie = sqlite3.connect(cible)
    try:
        lecture.backup(copie)
    finally:
        copie.close()
        lecture.close()
    return True


def _reponse_par_fichier(projet: Path, fichier: str | None) -> bool:
    if not fichier:
        return False
    trouve = _QUESTION_FICHIER.fullmatch(Path(fichier).name)
    if trouve is None:
        return False
    return (projet / Path(fichier).parent / f"reponse-assistant-{trouve.group(1)}.md").is_file()


def migrer(projet: Path) -> dict:
    """Crée tables et index, ferme les messages antérieurs, liste les questions restées
    sans réponse. Retourne les compteurs {sauvegarde, clos, clos_par_fichier, ouvertes}."""
    projet = Path(projet)
    stats = {"sauvegarde": sauvegarder(projet), "clos": 0, "clos_par_fichier": 0, "ouvertes": 0}
    conn = ouvrir(projet)
    try:
        sans_transition = conn.execute(
            "SELECT id, de, a, nature, resume, fichier FROM messages m"
            " WHERE NOT EXISTS (SELECT 1 FROM transitions t WHERE t.message_id = m.id)"
            " ORDER BY id").fetchall()
        with conn:
            for ident, de, a, nature, resume, fichier in sans_transition:
                repondu = nature != "question" or conn.execute(
                    "SELECT 1 FROM messages WHERE en_reponse_a = ?", (ident,)).fetchone()
                if repondu:
                    inscrire_transition(conn, ident, "clos", "cime",
                                        {"preuve": "migration-1.10"}, commit=False)
                    stats["clos"] += 1
                elif _reponse_par_fichier(projet, fichier):
                    inscrire_transition(conn, ident, "clos", "cime",
                                        {"preuve": "migration:fichier"}, commit=False)
                    stats["clos_par_fichier"] += 1
                else:
                    inscrire_transition(conn, ident, "inscrit", "cime",
                                        {"migration": "1.10"}, commit=False)
                    obligations.ouvrir_obligation(conn, ident, a, "reponse", None,
                                                  commit=False)
                    stats["ouvertes"] += 1
        stats["liste"] = _ouvertes_migrees(conn)
    finally:
        conn.close()
    _rapport(projet, stats["liste"])
    return stats


def _ouvertes_migrees(conn) -> list[tuple]:
    return conn.execute(
        "SELECT m.id, m.de, m.a, m.resume FROM messages m"
        " JOIN transitions t ON t.message_id = m.id AND t.etat = 'inscrit'"
        " AND t.preuve = '{\"migration\": \"1.10\"}'"
        " JOIN obligations o ON o.message_id = m.id"
        " WHERE m.nature = 'question' ORDER BY m.id").fetchall()


def _rapport(projet: Path, liste: list[tuple]) -> None:
    """Rapport pour l'Assistant, écrit une seule fois (jamais écrasé : idempotence)."""
    chemin = projet / ".orga" / "etat" / "migration-registre-2.0.md"
    if chemin.exists():
        return
    lignes = ["# Migration du registre vers 2.0 — questions restées sans réponse", "",
              "Ces questions n'ont ni réponse enregistrée ni fichier `reponse-assistant-*.md`. "
              "Elles restent ouvertes, sans échéance : aucune relance ne partira.", ""]
    lignes += [f"- #{i} · {de} → {a} · {resume}" for i, de, a, resume in liste] \
        or ["Aucune."]
    chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")
