"""Les coordinateurs au repos : fermés quand ils n'ont rien à faire, rouverts quand un message leur arrive.

Une session Claude pèse plusieurs centaines de Mo, même inactive. Un coordinateur sans dette, au
repos depuis `[charge] coordinateur_repos_minutes`, est donc fermé (sa conversation est gardée) par le
facteur, seul à toucher tmux. L'événement `CoordEndormi` est inscrit avant la fermeture : c'est lui
qui dit, ensuite, que l'absence de la session est voulue. Un coordinateur est « endormi » de ce
moment jusqu'au prochain `SessionStart` de l'agent.

Un coordinateur « tombé » (sa session a disparu sans que personne l'ait voulu, au redémarrage de la
machine) est rouvert de la même façon : l'absence de sa session n'a alors d'autre trace que l'absence
d'une fermeture voulue depuis son dernier `SessionStart`.
"""
from datetime import timedelta
from pathlib import Path

from cime.fondation import fermeture
from cime.fondation.projet import lire_manifeste
from cime.fondation.registre import ouvrir
from cime.signaux import echeances

AUTEUR = "cime"
ENDORMI = "CoordEndormi"
REVEILLE = "CoordReveille"
# raisons de `SessionEnd` d'une sortie voulue (`/exit`, déconnexion) : l'agent a quitté, il n'est pas tombé
SORTIES_VOLONTAIRES = ("prompt_input_exit", "logout")


# --- l'état « endormi », lu dans `evenements` ---------------------------------------------------

def episode(conn, agent):
    """(id de l'événement `CoordEndormi`, conversation à reprendre) du sommeil en cours de `agent`, ou
    None. Le sommeil dure jusqu'à un réveil (`CoordReveille`) ou jusqu'à un `SessionStart` de l'agent :
    une session qui vit n'est pas endormie, quelle que soit la façon dont elle est revenue."""
    dernier = conn.execute(
        "SELECT id, evenement, json_extract(details, '$.session') FROM evenements"
        " WHERE evenement IN (?, ?) AND json_extract(details, '$.agent') = ? ORDER BY id DESC LIMIT 1",
        (ENDORMI, REVEILLE, agent)).fetchone()
    if dernier is None or dernier[1] != ENDORMI:
        return None
    if conn.execute("SELECT 1 FROM evenements WHERE agent = ? AND evenement = 'SessionStart'"
                    " AND id > ? LIMIT 1", (agent, dernier[0])).fetchone():
        return None
    return dernier[0], dernier[2]


def sommeil_ou_reveil_a(conn, agent):
    """Instant du dernier sommeil ou réveil de `agent`, ou None : le repos qui précède ne compte pas
    pour une dette au repos, aucune échéance ne court pendant qu'un coordinateur dort."""
    ligne = conn.execute(
        "SELECT horodatage FROM evenements WHERE evenement IN (?, ?)"
        " AND json_extract(details, '$.agent') = ? ORDER BY id DESC LIMIT 1",
        (ENDORMI, REVEILLE, agent)).fetchone()
    return echeances._lire(ligne[0]) if ligne else None


def endormi_depuis(conn, agent, debut_id) -> bool:
    """`agent` a été mis au repos après l'événement `debut_id` (le début de sa session) : la
    disparition de cette session est voulue."""
    return conn.execute(
        "SELECT 1 FROM evenements WHERE evenement = ? AND id > ?"
        " AND json_extract(details, '$.agent') = ? LIMIT 1", (ENDORMI, debut_id, agent)).fetchone() is not None


def endormis(conn) -> dict:
    """Agent → conversation, pour chaque coordinateur actuellement endormi."""
    agents = [a for (a,) in conn.execute(
        "SELECT DISTINCT json_extract(details, '$.agent') FROM evenements WHERE evenement = ?",
        (ENDORMI,)) if a]
    en_cours = {a: episode(conn, a) for a in sorted(agents)}
    return {a: e[1] for a, e in en_cours.items() if e is not None}


# --- qui s'endort ----------------------------------------------------------------------------------

def _au_repos_depuis(conn, agent, etat):
    """Instant où l'agent est au repos (`au_repos` à l'observation), ou None. Une session ouverte
    depuis (`startup`, `resume`) fait repartir le délai : le repos se compte sur la session qui vit."""
    if not etat or etat.get("etat") != "au_repos" or not etat.get("etat_depuis"):
        return None
    depuis = echeances._lire(etat["etat_depuis"])
    ouverture = conn.execute(
        "SELECT max(horodatage) FROM evenements WHERE agent = ? AND evenement = 'SessionStart'"
        " AND json_extract(details, '$.source') IN ('startup', 'resume')", (agent,)).fetchone()[0]
    return max(depuis, echeances._lire(ouverture)) if ouverture else depuis


def endormables(projet, conn, manifeste, sessions, maintenant) -> list[dict]:
    """Les coordinateurs à fermer : `{agent, tmux, session}`, dans l'ordre des noms. `sessions` :
    sessions tmux vivantes. Un coordinateur est endormable s'il n'a aucune dette (la règle de
    `fermeture.raisons_de_garder`), n'est pas occupé (`fermeture.occupes`), est au repos depuis au
    moins `coordinateur_repos_minutes`, a une conversation connue au registre, et n'est pas déjà
    endormi. Jamais l'Assistant."""
    vivants = fermeture.identites_vivantes(manifeste.prefixe, sessions)
    coordinateurs = sorted(i for i in vivants if i.startswith("coord-"))
    if not coordinateurs:
        return []
    conversations = fermeture._dernieres_sessions(conn)
    gardes = fermeture.raisons_de_garder(
        vivants=vivants, equipes_connues=fermeture.equipes_connues(projet),
        coordinables=[c[len("coord-"):] for c in coordinateurs],
        taches=fermeture.taches_en_cours(projet), debiteurs=fermeture._debiteurs(conn),
        en_attente=fermeture._agents_en_attente(conn))
    candidats = [c for c in coordinateurs
                 if c not in gardes and conversations.get(c) and episode(conn, c) is None]
    if not candidats:
        return []
    from cime.observation.registre import lire_registre
    donnees, _ = lire_registre(Path(projet), maintenant)
    etats = (donnees or {}).get("agents") or {}
    occupes = set(fermeture.occupes(projet, conn, donnees or {}))
    delai = timedelta(minutes=manifeste.coordinateur_repos_minutes)
    retenus = []
    for agent in candidats:
        depuis = _au_repos_depuis(conn, agent, etats.get(agent))
        if agent not in occupes and depuis is not None and maintenant - depuis >= delai:
            retenus.append({"agent": agent, "tmux": vivants[agent], "session": conversations[agent]})
    return retenus


def endormir(projet, maintenant) -> list[str]:
    """Ferme les coordinateurs endormables ; renvoie leurs identités. Pour chacun, l'événement
    `CoordEndormi` et la ligne de journal d'abord, la fermeture de la session ensuite. En cas de doute
    (tmux muet, observation illisible), personne n'est fermé."""
    manifeste = lire_manifeste(projet)
    minutes = manifeste.coordinateur_repos_minutes
    if minutes <= 0 or fermeture.est_ferme(projet):
        return []
    conn = ouvrir(projet)
    try:
        if conn.execute("SELECT 1 FROM evenements WHERE agent LIKE 'coord-%' LIMIT 1").fetchone() is None:
            return []                   # aucun coordinateur n'a jamais vécu : pas même un appel à tmux
        sessions = fermeture.sessions_vivantes()
        faits = []
        for cible in endormables(projet, conn, manifeste, sessions, maintenant):
            fermeture._noter(projet, ENDORMI, "coord_endormir",
                             {"agent": cible["agent"], "session": cible["session"],
                              "repos_minutes": minutes}, conn, auteur=AUTEUR)
            fermeture._fermer_session(cible["tmux"])
            faits.append(cible["agent"])
        return faits
    finally:
        conn.close()


# --- le coordinateur tombé -----------------------------------------------------------------------

def fermeture_ordonnee(conn, agent, debut_id) -> bool:
    """Un ordre `fermer` de cet agent (ou un `lancer … --remplacer`, qui ferme avant de reprendre),
    en file ou exécuté, posé depuis le démarrage de la session (`SessionStart` n° debut_id) :
    sa disparition est la fermeture propre, pas une panne."""
    return conn.execute(
        "SELECT 1 FROM ordres o, evenements e WHERE e.id = ? AND o.cible = ?"
        " AND (o.verbe = 'fermer' OR (o.verbe = 'lancer' AND json_extract(o.parametres, '$.remplacer') = 1))"
        " AND o.etat IN ('en_file', 'execute') AND o.horodatage >= e.horodatage LIMIT 1",
        (debut_id, agent)).fetchone() is not None


def projet_ferme_apres(conn, evenement_id) -> bool:
    """Un `ProjetFerme` suit cet événement : la session a été fermée avec le projet, pas perdue
    (même statut que `fermeture_ordonnee`)."""
    return conn.execute("SELECT 1 FROM evenements WHERE evenement = 'ProjetFerme' AND id > ? LIMIT 1",
                        (evenement_id,)).fetchone() is not None


def _sortie_volontaire_apres(conn, agent, debut_id) -> bool:
    """`agent` a déclaré une sortie voulue (`SORTIES_VOLONTAIRES`) depuis le démarrage `debut_id`. Toute
    autre fin déclarée, ou aucune, est une chute : un redémarrage de la machine laisse l'une ou l'autre."""
    marques = ",".join("?" for _ in SORTIES_VOLONTAIRES)
    return conn.execute(
        "SELECT 1 FROM evenements WHERE agent = ? AND evenement = 'SessionEnd' AND id > ?"
        f" AND json_extract(details, '$.reason') IN ({marques}) LIMIT 1",
        (agent, debut_id, *SORTIES_VOLONTAIRES)).fetchone() is not None


def tombe(projet, conn, agent):
    """(id du dernier `SessionStart`, conversation à reprendre) si le coordinateur `agent`, dont la session
    tmux est absente (à l'appelant de le vérifier), est tombé ; None sinon. Il est tombé si sa
    conversation est connue, si son dernier `SessionStart` n'a été suivi d'aucune fermeture voulue (ordre
    `fermer` ou `lancer … remplacer`, `ProjetFerme`, `CoordEndormi`, sortie volontaire), si le projet n'est
    pas fermé et si son équipe n'est pas clôturée. Jamais l'Assistant."""
    if not agent.startswith("coord-") or fermeture.est_ferme(projet):
        return None
    if (Path(projet) / ".orga" / "teams" / agent[len("coord-"):] / "CLOTUREE").exists():
        return None
    conversation = fermeture._dernieres_sessions(conn).get(agent)
    debut = conn.execute("SELECT max(id) FROM evenements WHERE agent = ? AND evenement = 'SessionStart'",
                         (agent,)).fetchone()[0]
    if not conversation or debut is None:
        return None
    if fermeture_ordonnee(conn, agent, debut) or projet_ferme_apres(conn, debut) \
            or endormi_depuis(conn, agent, debut) or _sortie_volontaire_apres(conn, agent, debut):
        return None
    return debut, conversation


# --- le réveil ------------------------------------------------------------------------------------

def _etats_des_reveils(conn, agent, episode_id) -> set:
    """États des ordres de réveil de `agent` posés depuis l'événement `episode_id`, début de l'épisode."""
    return {etat for (etat,) in conn.execute(
        "SELECT o.etat FROM ordres o, evenements e WHERE e.id = ? AND o.verbe = 'lancer'"
        " AND o.cible = ? AND json_extract(o.parametres, '$.reveil') = 1"
        " AND o.horodatage >= e.horodatage", (episode_id, agent))}


def _lancement_en_file(conn, agent) -> bool:
    """Un ordre `lancer` de `agent`, quel qu'en soit l'auteur, attend déjà : il le fera vivre."""
    return conn.execute("SELECT 1 FROM ordres WHERE verbe = 'lancer' AND cible = ? AND etat = 'en_file'"
                        " LIMIT 1", (agent,)).fetchone() is not None


def _a_reveiller(projet, conn, agent):
    """(événement qui ouvre l'épisode, conversation à reprendre) : le sommeil en cours de `agent`, sinon sa
    chute (`tombe`), sinon None. L'épisode finit au `SessionStart` suivant."""
    return episode(conn, agent) or tombe(projet, conn, agent)


def reveil_echoue(projet, conn, agent) -> bool:
    """L'épisode en cours de `agent` (sommeil ou chute) a déjà vu un ordre de réveil refusé ou en échec."""
    ouvert = _a_reveiller(projet, conn, agent)
    return ouvert is not None and bool(_etats_des_reveils(conn, agent, ouvert[0]) & {"echec", "refuse"})


def absence_attendue(projet, conn, agent) -> bool:
    """La session de `agent` manque et c'est attendu : il dort ou il est tombé, et on le réveille au
    prochain message. C'est le seul endroit qui le dit. Faux dès qu'il a vécu depuis, ou qu'un réveil a
    échoué (les alarmes reprennent alors comme pour tout absent)."""
    return _a_reveiller(projet, conn, agent) is not None and not reveil_echoue(projet, conn, agent)


def reveiller(projet, conn, agent) -> bool:
    """Un message attend `agent`, dont la session est absente : s'il dort ou s'il est tombé, un ordre
    `lancer … reveil` le reprend sur sa conversation. Un seul ordre par épisode : aucun tant qu'un est en
    file, ni après un échec. Renvoie vrai si l'agent est à réveiller et que son réveil est posé ou attendu ;
    faux sinon (ni endormi ni tombé, ou son réveil a échoué)."""
    ouvert = _a_reveiller(projet, conn, agent)
    if ouvert is None:
        return False
    etats = _etats_des_reveils(conn, agent, ouvert[0])
    if etats & {"echec", "refuse"}:
        return False
    if not etats and not _lancement_en_file(conn, agent):
        from cime.signaux import ordres
        ordres.demander(projet, AUTEUR, "lancer", agent,
                        {"role": "coord", "equipe": agent[len("coord-"):], "reprendre": True,
                         "session": ouvert[1], "reveil": True, "modele": None})
    return True


def noter_reveil(projet, conn, agent, session, ordre_id) -> None:
    """Le coordinateur dort encore, mais plus pour longtemps : l'ordre de réveil a abouti."""
    fermeture._noter(projet, REVEILLE, "coord_reveiller",
                     {"agent": agent, "session": session, "par_ordre": ordre_id}, conn, auteur=AUTEUR)
