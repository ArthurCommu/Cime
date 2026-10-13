"""`cime reprise [--complet]` : ce qu'un agent doit savoir pour reprendre, lu dans le registre."""
import re
from pathlib import Path

from cime.fondation.registre import ouvrir
from cime.signaux import commandes, obligations, ordres, repos
from cime.signaux.commandes import facteur_arrete, secondes_depuis

PLAFOND = 4000
NOTE_TRONQUE = "\n… (tronqué à 4 000 caractères : `cime reprise --complet`)"
MAX_LIGNES = 12  # par section, sans --complet
_TITRE = re.compile(r"^## (\d{4}-\d\d-\d\d — .+)$")


def age(iso: str) -> str:
    s = int(secondes_depuis(iso))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min"
    if s < 86400:
        return f"{s // 3600} h"
    return f"{s // 86400} j"


def _section(titre: str, lignes: list[str], complet: bool, vide: str = "aucune") -> str:
    if not lignes:
        return f"{titre}\n  {vide}"
    montrees = lignes if complet else lignes[:MAX_LIGNES]
    reste = len(lignes) - len(montrees)
    if reste:
        montrees = [*montrees, f"… et {reste} de plus (`cime reprise --complet`)"]
    return f"{titre}\n" + "\n".join(f"  {ligne}" for ligne in montrees)


def _court(texte: str, n: int = 90) -> str:
    return texte if len(texte) <= n else texte[:n - 1] + "…"


def _equipes(projet: Path, endormis=()) -> list[str]:
    dossier = projet / ".orga" / "teams"
    lignes = []
    for equipe in sorted(d for d in dossier.iterdir() if d.is_dir()) if dossier.is_dir() else []:
        en_cours = sorted(f.stem for f in (equipe / "tasks" / "in-progress").glob("*.md"))
        note = " (clôturée)" if (equipe / "CLOTUREE").exists() else ""
        note += " (coordinateur endormi)" if f"coord-{equipe.name}" in endormis else ""
        lignes.append(f"{equipe.name}{note} : " + (", ".join(en_cours) if en_cours else "rien en cours"))
    return lignes


def _decisions(projet: Path) -> list[str]:
    fichier = projet / ".orga" / "contracts" / "CHANGELOG.md"
    if not fichier.is_file():
        return []
    titres = [m.group(1) for ligne in fichier.read_text(encoding="utf-8").splitlines()
              if (m := _TITRE.match(ligne))]
    return titres[:5]


def texte_reprise(projet: Path, moi: str, complet: bool = False) -> str:
    conn = ouvrir(projet)
    try:
        arret = facteur_arrete(conn)
        dettes = obligations.ouvertes_de(conn, moi)
        demandes = conn.execute(
            "SELECT m.id, m.nature, m.a, m.resume, m.horodatage, o.debiteur, o.attendu"
            " FROM messages m JOIN obligations o ON o.message_id = m.id"
            " WHERE m.de = ? AND o.etat = 'ouverte' ORDER BY m.id", (moi,)).fetchall()
        courrier = conn.execute(
            "SELECT m.id, m.de, m.nature, m.resume, m.horodatage FROM messages m"
            " WHERE m.a = ? AND NOT EXISTS (SELECT 1 FROM transitions t"
            " WHERE t.message_id = m.id AND t.etat = 'clos') ORDER BY m.id", (moi,)).fetchall()
        utilisateur = obligations.ouvertes_de(conn, "utilisateur") if moi == "assistant" else []
        endormis = repos.endormis(conn)
    finally:
        conn.close()
    blocs = []
    if arret is not False:
        depuis = "depuis toujours" if arret is None else f"depuis {arret} s"
        blocs.append(f"FACTEUR ARRÊTÉ {depuis} : rien n'est livré ni exécuté tant qu'il est arrêté.")
    blocs.append(f"Reprise de {moi}")
    blocs.append(_section(
        f"(a) Ce que je dois ({len(dettes)})",
        [f"#{d['message_id']} {d['attendu']} à {d['de']} ({d['nature']}, {age(d['horodatage'])}) : "
         f"{_court(d['resume'])}" for d in dettes], complet))
    blocs.append(_section(
        f"(b) Ce que j'ai demandé et qui attend ({len(demandes)})",
        [f"#{i} {nature} → {a} ({age(h)}, {attendu} attendu de {deb}) : {_court(resume)}"
         for i, nature, a, resume, h, deb, attendu in demandes], complet))
    blocs.append(_section(
        f"(c) Courrier à mon adresse non clos ({len(courrier)})",
        [f"#{i} de {de} ({nature}, {age(h)}) : {_court(resume)}"
         for i, de, nature, resume, h in courrier], complet))
    blocs.append(_section("(d) Équipes et tâches en cours", _equipes(projet, endormis), complet,
                          vide="aucune équipe"))
    if moi == "assistant":
        blocs.append(_section(
            f"(e) Attentes de l'utilisateur ouvertes ({len(utilisateur)})",
            [f"#{o['message_id']} {o['attendu']} ({o['nature']}, {age(o['horodatage'])}) : "
             f"{_court(o['resume'])}" for o in utilisateur], complet))
    blocs.append(_section("(f) Dernières décisions (CHANGELOG des contrats)",
                          _decisions(projet), complet))
    retenus, actifs, plafond = ordres.lancements_retenus(projet)
    if retenus:
        actifs = "?" if actifs is None else actifs
        noms = retenus if complet else retenus[:MAX_LIGNES]
        reste = len(retenus) - len(noms)
        suite = f", … et {reste} de plus" if reste else ""
        blocs.append(f"(g) File de lancements : {len(retenus)} en attente "
                     f"(plafond {plafond}, actifs {actifs}) : {', '.join(noms)}{suite}")
    texte = "\n\n".join(blocs)
    if not complet and len(texte) > PLAFOND:
        texte = texte[:PLAFOND - len(NOTE_TRONQUE)].rstrip() + NOTE_TRONQUE
    return texte


def _reprise(args) -> int:
    moi = commandes.identite_appelant()
    projet = commandes.projet_courant()
    print(texte_reprise(projet, moi, complet=getattr(args, "complet", False)))
    return 0


def executer(args) -> int:
    return commandes.lancer_commande("reprise", _reprise, args)
