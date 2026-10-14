"""Banc de bout en bout : commandes, préconditions, garde, git.

Les vraies commandes `cime` (en processus), les vrais hooks `PreToolUse`/`PostToolUse` (la garde),
le vrai facteur à horloge simulée (il exécute les ordres pendant que la commande attend), un dépôt
git jetable pour les fusions. Seul `lancer._lancer` est remplacé : il lancerait un vrai `claude`.
"""
import json
import sqlite3
from types import SimpleNamespace

import pytest

from e2e.aides import (ASSISTANT, COORD, COORD_B, W, accuser, envoyer, etat, minutes_apres,
                       nb_ecrits, rien_ecrit, signalements)
from e2e.banc import Banc
from e2e.conftest import _arborescence, _git

from cime.fondation import lancer
from cime.fondation.registre import chemin_registre

MODELE = "claude-haiku-5-5"
ECHELLE = "m.de = 'cime' AND (m.objet LIKE 'relance:%' OR m.objet LIKE 'escalade:%')"


# --- aides ---------------------------------------------------------------------------------------

@pytest.fixture
def faux_lancer(monkeypatch, banc):
    """Le lancement réel est remplacé : la tâche passe de todo à in-progress et la session naît
    dans le faux tmux (la commande tmux est celle de l'exécuteur, donc du facteur)."""
    appels = []

    def faux(args, projet=None):
        appels.append((args.role, args.equipe, args.tache, args.modele))
        if args.role == "worker":
            base = banc.projet / ".orga" / "teams" / args.equipe / "tasks"
            (base / "in-progress").mkdir(exist_ok=True)
            (base / "todo" / f"{args.tache}.md").rename(base / "in-progress" / f"{args.tache}.md")
            nom = f"worker-{args.equipe}-{args.tache}"
        else:
            nom = "assistant" if args.role == "assistant" else f"coord-{args.equipe}"
        banc.tmux("new-session", "-d", "-s", f"es-{nom}")
        return f"es-{nom}", 0

    monkeypatch.setattr(lancer, "_lancer", faux)
    return appels


def facteur_pendant_les_attentes(banc):
    """Le facteur vivant : pendant qu'une commande attend son ordre, il fait un tour."""
    en_cours = []

    def tour(_h):
        if not en_cours:
            en_cours.append(1)
            try:
                banc.facteur_tour()
            finally:
                en_cours.clear()
    banc.horloge.pendant_sommeil.append(tour)
    return tour


def tache(banc, nom="t1", dossier="todo"):
    chemin = banc.projet / ".orga" / "teams" / "alpha" / "tasks" / dossier / f"{nom}.md"
    chemin.write_text(f"# {nom}\n")
    return chemin


def lancer_worker(banc, nom="t1", **env):
    return banc.acteur(COORD, **env).cime("lancer", "worker", "alpha", nom, "--modele", MODELE)


def ordres(banc):
    return banc.prouve("SELECT id, verbe, cible, etat FROM ordres ORDER BY id")


def hors_facteur(banc):
    return banc.tmux.commandes("hors-facteur")


def pre(banc, agent, commande, cwd=None):
    """Le hook `PreToolUse` d'un agent pour une commande Bash : (refusée ?, résultat)."""
    r = banc.acteur(agent).hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": commande},
                                               "cwd": str(cwd or banc.projet)})
    return '"permissionDecision": "deny"' in r.stdout, r


# --- lancer un worker, sous accord -------------------------------------------------------------

def _accord_de_lancement(banc, parallele=False):
    d = envoyer(banc, COORD, ASSISTANT, "demande_accord", "lancer t1", "--objet", "lancer-worker:alpha:t1")
    r = banc.acteur(ASSISTANT).cime("accorder", str(d), "--modele", MODELE)
    assert r.code == 0, r.erreur
    return d, r.id


def test_accord_de_lancement_normal(banc, faux_lancer):
    tache(banc)
    facteur_pendant_les_attentes(banc)
    sans = lancer_worker(banc)
    assert sans.code == 2 and "aucun accord non consommé" in sans.erreur
    assert ordres(banc) == [] and faux_lancer == []                       # refus : rien n'est parti
    _, accord = _accord_de_lancement(banc)
    avec = lancer_worker(banc)
    assert avec.code == 0, avec.erreur
    assert ordres(banc) == [(1, "lancer", W, "execute")] and faux_lancer == [("worker", "alpha", "t1", MODELE)]
    assert etat(banc, accord) == "clos"                                   # consommé par l'ordre
    assert banc.prouve("SELECT json_extract(preuve, '$.par_ordre') FROM transitions WHERE message_id = ?"
                       " AND etat = 'clos'", (accord,)) == [(1,)]
    assert banc.prouve("SELECT de, a, nature FROM messages WHERE objet = 'tache:alpha:t1'"
                       ) == [(COORD, W, "consigne")]
    reutilise = lancer_worker(banc)                                       # l'accord est consommé
    assert reutilise.code == 2 and len(ordres(banc)) == 1 and len(faux_lancer) == 1


def test_accord_de_lancement_oubli(banc, faux_lancer):
    """L'Assistant ne répond pas à la demande d'accord : rien ne part, la demande monte (10 puis 20 min)."""
    tache(banc)
    d = envoyer(banc, COORD, ASSISTANT, "demande_accord", "lancer t1", "--objet", "lancer-worker:alpha:t1")
    avant = nb_ecrits(banc, ASSISTANT)
    assert banc.acteur(ASSISTANT).inerte().cime("accorder", str(d)) is None
    assert nb_ecrits(banc, ASSISTANT) == avant
    assert lancer_worker(banc).code == 2
    banc.faire_tourner(21 * 60, pas=60)
    assert ordres(banc) == [] and faux_lancer == []
    assert minutes_apres(banc, d, ECHELLE) == [(ASSISTANT, "relance", 10.0), ("utilisateur", "signalement", 20.0)]


# --- terminer un worker ---------------------------------------------------------------------------

def _worker_a_terminer(banc):
    tache(banc, dossier="in-progress")
    banc.tmux.repos(W)
    r = banc.acteur(W).cime("envoyer", "--a", COORD, "--nature", "travail_pret", "lot terminé")
    assert r.code == 0, r.erreur
    return r.id


def _terminer(banc):
    return banc.acteur(COORD).cime("terminer", "worker", "alpha", "t1")


def test_fin_sans_terminer_normal(banc):
    tp = _worker_a_terminer(banc)
    facteur_pendant_les_attentes(banc)
    sans_rapport = _terminer(banc)
    assert sans_rapport.code == 2 and "aucun rapport" in sans_rapport.erreur
    (banc.projet / ".orga/teams/alpha/reports" / f"{W}-2026-10-10.md").write_text("rapport\n")
    sans_synthese = _terminer(banc)
    assert sans_synthese.code == 2 and "aucune synthèse" in sans_synthese.erreur
    assert ordres(banc) == [] and f"es-{W}" in banc.tmux.sessions        # rien n'a été fermé
    (banc.projet / ".orga/teams/alpha/conversations/t1-synthese.md").write_text("synthèse\n")
    complet = _terminer(banc)
    assert complet.code == 0, complet.erreur
    assert ordres(banc) == [(1, "fermer", W, "execute")]
    assert f"es-{W}" not in banc.tmux.sessions
    assert (banc.projet / ".orga/teams/alpha/tasks/done/t1.md").exists()
    assert banc.prouve("SELECT etat FROM obligations WHERE message_id = ?", (tp,)) == [("satisfaite",)]
    assert banc.prouve("SELECT etat FROM transitions WHERE message_id = (SELECT max(id) FROM messages"
                       " WHERE resume LIKE 'fin de tâche t1 — rapport accepté%') ORDER BY id DESC LIMIT 1"
                       ) == [("clos",)]
    banc.faire_tourner(15 * 60, pas=60)                                             # `terminer` a rangé la tâche : rien à signaler
    assert banc.prouve("SELECT count(*) FROM messages WHERE objet LIKE 'fin-sans-terminer:%'") == [(0,)]


def test_fin_sans_terminer_oubli(banc):
    """Le worker rend son travail puis finit sans que `terminer` ne soit lancé : signalement au coordinateur."""
    _worker_a_terminer(banc)
    assert banc.acteur(COORD).inerte().cime("terminer", "worker", "alpha", "t1") is None
    assert rien_ecrit(banc, COORD)
    banc.acteur(W).hook("SessionStart", {"source": "startup"})
    banc.acteur(W).hook("SessionEnd", {"reason": "other"})
    banc.tmux.absente(W)
    fin = banc.prouve("SELECT max(id) FROM evenements WHERE evenement = 'SessionEnd'")[0][0]
    banc.faire_tourner(9 * 60, pas=30)
    fins = lambda: [x for x in signalements(banc) if x[1].startswith(("fin-sans-terminer", "session-disparue"))]  # noqa: E731
    assert fins() == []                                                              # pas avant 10 min
    banc.faire_tourner(2 * 60, pas=30)
    assert fins() == [(COORD, f"fin-sans-terminer:{W}")]
    (s,) = banc.prouve("SELECT id FROM messages WHERE objet = ?", (f"fin-sans-terminer:{W}",))[0]
    assert banc.prouve("SELECT round((julianday(m.horodatage) - julianday(e.horodatage)) * 1440)"
                       " FROM messages m, evenements e WHERE m.id = ? AND e.id = ?", (s, fin)) == [(10.0,)]
    banc.faire_tourner(40 * 60, pas=60)
    assert banc.prouve("SELECT count(*) FROM messages WHERE objet = ?", (f"fin-sans-terminer:{W}",)) == [(1,)]
    assert (banc.projet / ".orga/teams/alpha/tasks/in-progress/t1.md").exists()


# --- la garde ferme tmux à tous les rôles ----------------------------------------------------------

TMUX = ("tmux send-keys -t es-coord-alpha -l bonjour", "tmux kill-session -t es-assistant",
        "tmux capture-pane -p -t es-coord-alpha", "tmux has-session -t es-worker-alpha-t1")
DEGUISES = ("bash -c 'tmux kill-session -t es-assistant'", "env tmux send-keys -t es-assistant x",
            "/opt/homebrew/bin/tmux list-sessions", "command tmux has-session -t es-assistant",
            "sh -c \"echo ok; tmux capture-pane -p\"")


def _refus_garde(banc, agent, commandes):
    for commande in commandes:
        refuse, r = pre(banc, agent, commande)
        assert refuse, (agent, commande, r.stdout)


def test_tmux_refuse_par_la_garde_normal(banc):
    for agent in (W, COORD, ASSISTANT):
        _refus_garde(banc, agent, TMUX)
        assert banc.prouve("SELECT count(*) FROM evenements WHERE evenement = 'PreToolUse' AND agent = ?"
                           " AND json_extract(details, '$.motif') LIKE '%tmux%'", (agent,)) == [(4,)]
    # le supérieur direct est prévenu, sauf pour l'Assistant (il voit son refus)
    assert banc.prouve("SELECT a, count(*) FROM messages WHERE objet LIKE 'refus-garde:%' GROUP BY a ORDER BY a"
                       ) == [(ASSISTANT, 4), (COORD, 4)]
    assert hors_facteur(banc) == []                                       # aucune commande n'a atteint tmux


def test_tmux_refuse_par_la_garde_oubli(banc):
    """L'agent insiste, déguisé (bash -c, env, chemin absolu…) : chaque détour est refusé et signalé."""
    for agent in (W, COORD, ASSISTANT):
        _refus_garde(banc, agent, DEGUISES)
    assert banc.prouve("SELECT count(*) FROM evenements WHERE evenement = 'PreToolUse'") == [(15,)]
    assert banc.prouve("SELECT a, count(*) FROM messages WHERE objet LIKE 'refus-garde:%' GROUP BY a ORDER BY a"
                       ) == [(ASSISTANT, 5), (COORD, 5)]
    assert hors_facteur(banc) == []


# --- les fusions ---------------------------------------------------------------------------

def sha(depot, ref):
    import subprocess
    return subprocess.run(["git", "rev-parse", ref], cwd=depot, capture_output=True, text=True,
                          check=True).stdout.strip()


def accord_de_fusion(banc, depot, equipe="alpha", ref=None):
    """L'Assistant demande, l'utilisateur accorde (à la main, hors Claude Code) : un `accord fusion:<é>:<sha>`."""
    pointe = sha(depot, ref or f"equipe/{equipe}")
    d = envoyer(banc, ASSISTANT, "utilisateur", "decision_utilisateur", f"fusionner {equipe} ?",
                "--objet", f"fusion:{equipe}:{pointe}")
    r = banc.acteur(None).cime("accorder", str(d))
    assert r.code == 0, r.erreur
    return r.id


@pytest.fixture(autouse=True)
def _file_de_fusion_sans_suite_ni_installation(monkeypatch):
    """`cime fusionner` en processus : la suite entière, la réinstallation et l'arrêt du facteur sont
    remplacés (le reste, git compris, est réel)."""
    from cime.fondation import fusionner as file
    monkeypatch.setattr(file, "_suite", lambda projet, dossier: (0, "2 passed in 0.10s\n"))
    monkeypatch.setattr(file, "_workers_actifs", lambda projet: 0)
    monkeypatch.setattr(file, "_reinstaller", lambda projet: (True, ""))
    monkeypatch.setattr(file, "_arreter_facteur", lambda projet: "facteur arrêté")


def fusionner(banc, depot, equipe="alpha"):
    """La fusion de l'Assistant : `cime fusionner <équipe>` (la garde refuse `git merge`) ; renvoie
    (fusionné ?, résultat dont `.stdout` porte tout ce que la commande a dit)."""
    r = banc.acteur(ASSISTANT).cime("fusionner", equipe, "--maintenant")
    return r.code == 0, SimpleNamespace(stdout=r.sortie + r.erreur)


def journal_fusions(depot):
    chemin = depot / ".orga" / "etat" / "fusions.log"
    return chemin.read_text().splitlines() if chemin.exists() else []


def travail_pret_avec_suites(banc, *suites):
    args = [x for s in suites for x in ("--suite", s)]
    r = banc.acteur(COORD).cime("envoyer", "--a", ASSISTANT, "--nature", "travail_pret", *args,
                                "lot alpha prêt à fusionner")
    assert r.code == 0, r.erreur
    return r.id


def test_decision_de_fusion_sans_reponse_normal(banc_depot, depot):
    banc = banc_depot
    travail_pret_avec_suites(banc, "recopier:src/alpha.txt:src/copie.txt")
    main_avant = sha(depot, "main")
    fait, r = fusionner(banc, depot)                                      # sans accord
    assert not fait and "accord" in r.stdout and sha(depot, "main") == main_avant
    assert all(l.endswith("resultat=refuse-accord") for l in journal_fusions(depot))   # le refus se journalise
    accord = accord_de_fusion(banc, depot)                                # avec accord
    fait, _ = fusionner(banc, depot)
    assert fait and sha(depot, "main") != main_avant
    _git("merge-base", "--is-ancestor", "equipe/alpha", "main", cwd=depot)     # la branche est dans main
    assert [l.split()[-1] for l in journal_fusions(depot)][-1] == "resultat=fusionne"
    assert etat(banc, accord) == "clos"                                   # consommé
    assert banc.prouve("SELECT json_extract(preuve, '$.par_commande') FROM transitions"
                       " WHERE message_id = ? AND etat = 'clos'", (accord,)) == [("fusionner",)]
    (s, a), = banc.prouve("SELECT m.id, m.a FROM messages m JOIN obligations o ON o.message_id = m.id"
                          " WHERE m.objet = 'suites:alpha' AND o.etat = 'ouverte'")
    assert a == ASSISTANT                                                 # l'obligation « suites »


def test_decision_de_fusion_sans_reponse_oubli(banc_depot, depot):
    """L'utilisateur n'accorde rien : aucune fusion, et sa décision en attente est relancée à 2 h."""
    banc = banc_depot
    d = envoyer(banc, ASSISTANT, "utilisateur", "decision_utilisateur", "fusionner alpha ?",
                "--objet", f"fusion:alpha:{sha(depot, 'equipe/alpha')}")
    assert banc.acteur(None).inerte().cime("accorder", str(d)) is None
    assert rien_ecrit(banc, "utilisateur")
    main_avant = sha(depot, "main")
    for _ in range(2):
        fait, r = fusionner(banc, depot)
        assert not fait and "accord" in r.stdout
    assert sha(depot, "main") == main_avant
    assert all(l.endswith("resultat=refuse-accord") for l in journal_fusions(depot))
    banc.faire_tourner(121 * 60, pas=300)
    assert minutes_apres(banc, d, ECHELLE) == [("utilisateur", "relance", 120.0)]
    assert etat(banc, d) == "inscrit" and banc.prouve("SELECT etat FROM obligations WHERE message_id = ?",
                                                       (d,)) == [("ouverte",)]


def test_un_accord_une_fusion_normal(banc_depot, depot):
    """Un accord = une fusion : sans accord ; avec ; le même accord une deuxième fois ; accord puis la branche avance."""
    banc = banc_depot
    assert not fusionner(banc, depot)[0]                                  # 1. refus
    accord = accord_de_fusion(banc, depot)
    assert fusionner(banc, depot)[0] and etat(banc, accord) == "clos"     # 2. succès + consommé
    assert any("resultat=fusionne" in l for l in journal_fusions(depot))
    fait, r = fusionner(banc, depot)                                      # 3. même accord
    assert not fait and "aucun accord de l'utilisateur non consommé" in r.stdout
    accord2 = accord_de_fusion(banc, depot)                               # 4. accord puis la branche avance
    travail = depot / ".orga" / "worktrees" / "alpha"
    (travail / "src" / "suite.txt").write_text("suite\n")
    _git("add", "src/suite.txt", cwd=travail)
    _git("commit", "-q", "-m", "suite", cwd=travail)
    nouveau = sha(depot, "equipe/alpha")
    fait, r = fusionner(banc, depot)
    # le sha est nouveau : la commande pose la demande d'accord, le motif des règles est dans son corps
    assert not fait and "demande #" in r.stdout and "posée" in r.stdout
    (demande, corps), = banc.prouve("SELECT id, corps FROM messages WHERE nature = 'decision_utilisateur'"
                                    " AND objet = ?", (f"fusion:alpha:{nouveau}",))
    assert f"demande #{demande} posée" in r.stdout and "aucun accord pour ce sha" in corps
    assert etat(banc, accord2) != "clos"                                  # jamais consommé


def test_un_accord_une_fusion_oubli(banc_depot, depot):
    """L'Assistant ne lance pas `cime fusionner` : rien n'est journalisé, l'accord reste libre ; et un
    `git merge` à la main est refusé, il ne laisse aucune trace non plus."""
    banc = banc_depot
    accord = accord_de_fusion(banc, depot)
    entree = {"tool_name": "Bash", "tool_input": {"command": "git merge equipe/alpha"}, "cwd": str(depot)}
    avant = banc.acteur(ASSISTANT).hook("PreToolUse", entree)
    assert '"deny"' in avant.stdout and "cime fusionner" in avant.stdout
    assert banc.acteur(ASSISTANT).inerte().cime("fusionner", "alpha") is None
    assert journal_fusions(depot) == []
    assert banc.prouve("SELECT count(*) FROM transitions WHERE etat = 'clos' AND message_id = ?", (accord,)
                       ) == [(0,)]


def _alpha_touche_le_contrat(depot):
    travail = depot / ".orga" / "worktrees" / "alpha"
    (travail / ".orga" / "contracts").mkdir(parents=True, exist_ok=True)
    (travail / ".orga" / "contracts" / "etat.schema.md").write_text("# etat 2\n")
    _git("add", ".orga/contracts/etat.schema.md", cwd=travail)
    _git("commit", "-q", "-m", "contrat etat", cwd=travail)


def test_contrat_modifie_par_fusion_normal(banc_depot, depot):
    banc = banc_depot
    _alpha_touche_le_contrat(depot)
    travail_pret_avec_suites(banc, "recopier:src/alpha.txt:src/copie.txt", "migrer")
    accord_de_fusion(banc, depot)
    fait, _ = fusionner(banc, depot)
    assert fait
    # une seule consigne suites:, adressée à l'Assistant, qui attend une action
    assert banc.prouve("SELECT m.a, o.attendu FROM messages m JOIN obligations o ON o.message_id = m.id"
                       " WHERE m.objet = 'suites:alpha'") == [(ASSISTANT, "action")]
    # le contrat touché signale sa seule lectrice déclarée
    assert banc.prouve("SELECT a FROM messages WHERE objet = 'contrat:etat'") == [(COORD,)]
    r = banc.acteur(ASSISTANT).cime("suites", "alpha")
    assert r.code == 0, r.erreur
    assert (depot / "src" / "copie.txt").read_text() == "alpha\n"
    assert banc.prouve("SELECT o.etat FROM obligations o JOIN messages m ON m.id = o.message_id"
                       " WHERE m.objet = 'suites:alpha'") == [("satisfaite",)]
    assert banc.acteur(ASSISTANT).cime("suites", "alpha").code == 0           # idempotent


def test_contrat_modifie_par_fusion_oubli(banc_depot, depot):
    """L'Assistant n'exécute pas les suites : relance à 10 min, l'utilisateur à 30."""
    banc = banc_depot
    _alpha_touche_le_contrat(depot)
    travail_pret_avec_suites(banc, "recopier:src/alpha.txt:src/copie.txt")
    accord_de_fusion(banc, depot)
    assert fusionner(banc, depot)[0]
    assert banc.acteur(ASSISTANT).inerte().cime("suites", "alpha") is None
    s = banc.prouve("SELECT id FROM messages WHERE objet = 'suites:alpha'")[0][0]
    banc.faire_tourner(31 * 60, pas=60)
    assert minutes_apres(banc, s, ECHELLE) == [(ASSISTANT, "relance", 10.0), ("utilisateur", "signalement", 30.0)]
    assert not (depot / "src" / "copie.txt").exists()
    assert banc.prouve("SELECT a FROM messages WHERE objet = 'contrat:etat'") == [(COORD,)]


# --- les ordres passent par le facteur seul -------------------------------------------------------

def _trois_commandes(banc, faux, **env):
    """lancer, compacter, terminer, par le coordinateur : rend leurs résultats."""
    tache(banc, "t2")
    tache(banc, dossier="in-progress")
    banc.tmux.repos(W)
    (banc.projet / ".orga/teams/alpha/reports" / f"{W}-2026-10-10.md").write_text("rapport\n")
    (banc.projet / ".orga/teams/alpha/conversations/t1-synthese.md").write_text("synthèse\n")
    envoyer(banc, W, COORD, "travail_pret", "lot terminé")
    envoyer(banc, COORD, ASSISTANT, "demande_accord", "lancer t2", "--objet", "lancer-worker:alpha:t2")
    banc.acteur(ASSISTANT).cime("accorder", "2", "--modele", MODELE, "--parallele")
    c = banc.acteur(COORD, **env)
    return [c.cime("lancer", "worker", "alpha", "t2", "--modele", MODELE),
            c.cime("compacter", W, "garde les décisions"),
            c.cime("terminer", "worker", "alpha", "t1")]


def test_ordres_en_file_normal(banc, faux_lancer):
    facteur_pendant_les_attentes(banc)
    resultats = _trois_commandes(banc, faux_lancer)
    assert [r.code for r in resultats] == [0, 0, 0], [r.erreur for r in resultats]
    assert [(o[1], o[3]) for o in ordres(banc)] == [("lancer", "execute"), ("compacter", "execute"),
                                                    ("fermer", "execute")]
    assert hors_facteur(banc) == [] and banc.tmux.commandes("facteur")       # tout est venu du facteur
    assert banc.prouve("SELECT count(*) FROM ordres WHERE etat = 'en_file'") == [(0,)]


def test_ordres_en_file_oubli(banc, faux_lancer):
    """Facteur arrêté et l'agent ne revient pas : « ordre #n en file » (code 4), exécutés une fois au retour, dans l'ordre."""
    banc.facteur_tour()
    banc.horloge.avance(seconds=60)
    resultats = _trois_commandes(banc, faux_lancer, CIME_ATTENTE_ORDRE="0")
    assert [r.code for r in resultats] == [4, 4, 4]
    assert all(f"ordre #{i + 1} en file, facteur arrêté" in r.sortie for i, r in enumerate(resultats))
    assert [o[3] for o in ordres(banc)] == ["en_file"] * 3 and hors_facteur(banc) == []
    banc.facteur_tour()
    assert [(o[0], o[3]) for o in ordres(banc)] == [(1, "execute"), (2, "execute"), (3, "execute")]
    assert banc.prouve("SELECT id FROM ordres ORDER BY fini, id") == [(1,), (2,), (3,)]
    assert hors_facteur(banc) == [] and len(faux_lancer) == 1
    fini = banc.prouve("SELECT fini FROM ordres ORDER BY id")
    banc.facteur_tour()
    assert banc.prouve("SELECT fini FROM ordres ORDER BY id") == fini and len(faux_lancer) == 1


# --- l'identité -----------------------------------------------------------------------------------

def test_agent_sans_identite_normal(banc):
    # 1. commande lancée depuis Claude Code sans CIME_AGENT : agent sans identité
    r = banc.acteur(None, CLAUDECODE="1").cime("envoyer", "--a", ASSISTANT, "--nature", "consigne",
                                               "--attend", "rien", "x")
    assert r.code == 2 and "agent sans identité" in r.erreur
    # 2 et 3. les détours par la ligne de commande sont refusés par la garde
    assert pre(banc, COORD, "CIME_AGENT=utilisateur cime envoyer --a assistant --nature consigne --attend rien x")[0]
    assert pre(banc, COORD, "env -u CLAUDECODE cime envoyer --a assistant --nature consigne --attend rien x")[0]
    # 4. à la main, hors Claude Code : exécution directe, sous le nom de l'utilisateur
    direct = banc.acteur(None).cime("envoyer", "--a", ASSISTANT, "--nature", "consigne", "--attend", "rien", "x")
    assert direct.code == 0, direct.erreur
    assert banc.prouve("SELECT de, a FROM messages WHERE de != 'cime'") == [("utilisateur", ASSISTANT)]


def test_agent_sans_identite_oubli(banc, faux_lancer):
    """L'agent a perdu CIME_AGENT : aucune famille de commande ne passe, le registre reste intact."""
    sans = banc.acteur(None, CLAUDECODE="1")
    familles = [("envoyer", "--a", ASSISTANT, "--nature", "consigne", "--attend", "rien", "x"),
                ("repondre", "1", "x"), ("accorder", "1"), ("refuser", "1", "non"),
                ("terminer", "worker", "alpha", "t1"), ("compacter", W, "x"),
                ("lancer", "worker", "alpha", "t1", "--modele", MODELE), ("voir", W)]
    for argv in familles:
        r = sans.cime(*argv)
        assert r.code != 0 and "sans identité" in r.erreur, (argv, r)
    assert banc.prouve("SELECT count(*) FROM messages") == [(0,)]
    assert banc.prouve("SELECT count(*) FROM ordres") == [(0,)] and faux_lancer == []


# --- plus d'accès tmux, `cime voir` par l'ordre `capturer` -----------------------------------------

def test_terminaux_prives_normal(banc):
    banc.tmux.brouillon(W, "travail en cours sur le module A")
    for agent in (W, COORD):
        _refus_garde(banc, agent, TMUX + DEGUISES[:2])
    facteur_pendant_les_attentes(banc)
    r = banc.acteur(COORD).cime("voir", W)
    assert r.code == 0, r.erreur
    assert "travail en cours sur le module A" in r.sortie                       # l'écran du faux tmux
    assert ordres(banc) == [(1, "capturer", W, "execute")]
    assert hors_facteur(banc) == []
    assert any(c[0] == "capture-pane" for c in banc.tmux.commandes("facteur"))


def test_terminaux_prives_oubli(banc):
    """Le coordinateur regarde où il ne le doit pas : l'Assistant est privé, un autre worker n'est pas le sien."""
    banc.tmux.brouillon(ASSISTANT, "secret de l'utilisateur")
    banc.tmux.repos("worker-beta-x")
    facteur_pendant_les_attentes(banc)
    prive = banc.acteur(COORD).cime("voir", ASSISTANT)
    assert prive.code == 2 and "privée" in prive.erreur and "secret" not in prive.sortie
    autre = banc.acteur(COORD).cime("voir", "worker-beta-x")
    assert autre.code == 2 and "supérieur direct" in autre.erreur
    assert banc.acteur(W).cime("voir", COORD).code == 2                        # un worker ne regarde pas son coordinateur
    assert ordres(banc) == [] and hors_facteur(banc) == []


# --- migration d'un ancien registre -----------------------------------------------------------------

ANCIEN = """
CREATE TABLE messages (
  id INTEGER PRIMARY KEY, horodatage TEXT NOT NULL, de TEXT NOT NULL, a TEXT NOT NULL,
  nature TEXT NOT NULL, resume TEXT NOT NULL, fichier TEXT, en_reponse_a INTEGER,
  equipe TEXT);
CREATE TABLE evenements (id INTEGER PRIMARY KEY, horodatage TEXT NOT NULL, agent TEXT,
  session_id TEXT, evenement TEXT NOT NULL, details TEXT NOT NULL);
CREATE TABLE journal (id INTEGER PRIMARY KEY, horodatage TEXT NOT NULL, auteur TEXT NOT NULL,
  action TEXT NOT NULL, cible TEXT, details TEXT, resultat TEXT NOT NULL);
"""


@pytest.fixture
def banc_ancien_registre(tmp_path, monkeypatch, horloge, tmux):
    """Un projet jetable dont le registre est un ancien registre fabriqué : une question répondue, une répondue par
    fichier `reponse-assistant-<h>.md`, une toujours ouverte, une consigne ordinaire."""
    from aide import exiger_jetable
    racine = exiger_jetable(tmp_path / "ancien")
    racine.mkdir()
    _arborescence(racine)
    teams = racine / ".orga" / "teams" / "alpha"
    (teams / "pour-assistant-20261001.md").write_text("q")
    (teams / "reponse-assistant-20261001.md").write_text("r")
    (racine / ".orga" / "etat").mkdir(parents=True)
    conn = sqlite3.connect(chemin_registre(racine))
    conn.executescript(ANCIEN)
    lignes = [("coord-alpha", "assistant", "question", "répondue par fichier",
               ".orga/teams/alpha/pour-assistant-20261001.md", None),
              ("coord-alpha", "assistant", "question", "toujours ouverte",
               ".orga/teams/alpha/pour-assistant-20261002.md", None),
              ("coord-alpha", "assistant", "question", "répondue", None, None),
              ("assistant", "coord-alpha", "reponse", "voilà", None, 3),
              ("assistant", "coord-alpha", "consigne", "ordinaire", None, None)]
    for de, a, nature, resume, fichier, rep in lignes:
        conn.execute("INSERT INTO messages (horodatage,de,a,nature,resume,fichier,en_reponse_a)"
                     " VALUES ('2026-10-01T10:00:00.000Z',?,?,?,?,?,?)", (de, a, nature, resume, fichier, rep))
    conn.commit()
    conn.close()
    return Banc(racine, horloge, tmux)


def _migrer(banc):
    from cime.signaux import migration
    return migration.migrer(banc.projet)


def test_migration_ancien_registre_normal(banc_ancien_registre, monkeypatch, tmp_path):
    banc = banc_ancien_registre
    stats = _migrer(banc)
    assert stats["sauvegarde"] and stats["clos_par_fichier"] == 1 and stats["ouvertes"] == 1
    # les questions fantômes sont closes, la preuve dit pourquoi ; seule la vraie reste ouverte
    assert banc.prouve("SELECT message_id, etat, preuve FROM transitions ORDER BY message_id") == [
        (1, "clos", '{"preuve": "migration:fichier"}'), (2, "inscrit", '{"migration": "1.10"}'),
        (3, "clos", '{"preuve": "migration-1.10"}'), (4, "clos", '{"preuve": "migration-1.10"}'),
        (5, "clos", '{"preuve": "migration-1.10"}')]
    assert banc.prouve("SELECT message_id, debiteur, attendu, echeance, etat FROM obligations"
                       ) == [(2, ASSISTANT, "reponse", None, "ouverte")]
    rapport = (banc.projet / ".orga/etat/migration-registre-2.0.md").read_text()
    assert "#2 · coord-alpha → assistant · toujours ouverte" in rapport and "#1" not in rapport
    assert _migrer(banc)["clos"] == 0                                           # idempotente
    # l'état 2.0 se lit sans erreur sur ce registre migré
    monkeypatch.setenv("HOME", str(tmp_path / "maison"))
    (tmp_path / "maison").mkdir()
    import importlib
    fiche = importlib.import_module("cime.observation.instantane").instantane(
        banc.projet, banc.horloge.maintenant())
    assert isinstance(fiche, dict) and fiche


def test_migration_ancien_registre_oubli(banc_ancien_registre):
    """Personne ne lit le rapport de migration : la question ouverte reste ouverte, sans échéance, sans relance."""
    banc = banc_ancien_registre
    avant = nb_ecrits(banc, ASSISTANT)
    assert banc.acteur(ASSISTANT).inerte().cime("repondre", "2", "x") is None
    assert nb_ecrits(banc, ASSISTANT) == avant
    _migrer(banc)
    banc.faire_tourner(3 * 3600, pas=600)
    assert banc.prouve("SELECT count(*) FROM messages WHERE de = 'cime' AND (objet LIKE 'relance:%'"
                       " OR objet LIKE 'escalade:%' OR objet LIKE 'dette:%')") == [(0,)]   # pas de rafale
    assert banc.prouve("SELECT etat, echeance FROM obligations WHERE message_id = 2") == [("ouverte", None)]


# --- `cime terminer` propre n'est pas une disparition --------------------------------------------

def test_terminer_propre_aucune_session_disparue(banc):
    banc.acteur(W).hook("SessionStart", {"source": "startup"})
    _worker_a_terminer(banc)
    facteur_pendant_les_attentes(banc)
    (banc.projet / ".orga/teams/alpha/reports" / f"{W}-2026-10-10.md").write_text("rapport\n")
    (banc.projet / ".orga/teams/alpha/conversations/t1-synthese.md").write_text("synthèse\n")
    assert _terminer(banc).code == 0
    assert ordres(banc) == [(1, "fermer", W, "execute")] and f"es-{W}" not in banc.tmux.sessions
    banc.faire_tourner(40 * 60, pas=60)
    assert banc.prouve("SELECT count(*) FROM messages WHERE objet = ?", (f"session-disparue:{W}",)) == [(0,)]


def test_session_tuee_sans_ordre_signale_toujours(banc):
    banc.acteur(W).hook("SessionStart", {"source": "startup"})
    banc.tmux.repos(W)
    banc.facteur_tour()
    banc.tmux.absente(W)
    banc.faire_tourner(15 * 60, pas=60)
    assert banc.prouve("SELECT a, count(*) FROM messages WHERE objet = ? GROUP BY a",
                       (f"session-disparue:{W}",)) == [(COORD, 1)]


# --- les messages restés `inscrit` pour un worker fermé ------------------------------------------

def test_message_inscrit_au_worker_abandonne_a_la_fermeture(banc):
    _worker_a_terminer(banc)
    banc.au_travail(W)                                   # le worker ne lit rien : ses messages restent inscrits
    banc.au_travail(COORD)
    pour_w = envoyer(banc, COORD, W, "consigne", "pour le worker")
    pour_coord = envoyer(banc, ASSISTANT, COORD, "consigne", "pour le coordinateur")
    assert etat(banc, pour_w) == "inscrit" and etat(banc, pour_coord) == "inscrit"
    facteur_pendant_les_attentes(banc)
    (banc.projet / ".orga/teams/alpha/reports" / f"{W}-2026-10-10.md").write_text("rapport\n")
    (banc.projet / ".orga/teams/alpha/conversations/t1-synthese.md").write_text("synthèse\n")
    assert _terminer(banc).code == 0
    assert ordres(banc) == [(1, "fermer", W, "execute")]
    assert etat(banc, pour_w) == "abandonne"
    assert banc.prouve("SELECT preuve FROM transitions WHERE message_id = ? AND etat = 'abandonne'",
                       (pour_w,)) == [('{"cause": "fermer"}',)]
    assert etat(banc, pour_coord) == "inscrit"           # un autre agent : intact
    banc.faire_tourner(40 * 60, pas=60)
    assert banc.prouve("SELECT count(*) FROM messages WHERE objet = ?", (f"session-absente:{W}",)) == [(0,)]
    assert banc.prouve("SELECT count(*) FROM obligations WHERE debiteur = ? AND etat = 'ouverte'",
                       (W,)) == [(0,)]


# --- lancer coord --reprendre --remplacer (Assistant) : fermeture par le facteur, puis reprise -----------

def _coord_vivant_avec_dette(banc):
    banc.acteur(COORD).hook("SessionStart", {"source": "startup"})
    banc.tmux.repos(COORD)
    envoyer(banc, W, COORD, "question", "quelle branche ?")        # une obligation ouverte du coordinateur


def test_remplacer_ferme_par_le_facteur_puis_reprend(banc, faux_lancer, monkeypatch):
    monkeypatch.setattr(lancer, "processus_claude_dans", lambda dossier: [])
    _coord_vivant_avec_dette(banc)
    facteur_pendant_les_attentes(banc)
    r = banc.acteur(ASSISTANT).cime("lancer", "coord", "alpha", "--reprendre", "--remplacer")
    assert r.code == 0, r.erreur
    assert ordres(banc) == [(1, "lancer", COORD, "execute")]
    kills = [c for c in banc.tmux.commandes() if c[0] == "kill-session"]
    assert len(kills) == 1 and kills[0] in banc.tmux.commandes("facteur")       # le facteur seul
    assert not [c for c in hors_facteur(banc) if c[0] == "kill-session"]
    assert faux_lancer == [("coord", "alpha", None, None)]                     # puis la reprise
    assert banc.prouve("SELECT de, a, nature FROM messages WHERE objet = 'ouverture'"
                       ) == [("cime", COORD, "consigne")]
    banc.acteur(COORD).hook("SessionEnd", {"reason": "other"})                 # la disparition causée par l'ordre
    banc.faire_tourner(40 * 60, pas=60)
    assert banc.prouve("SELECT count(*) FROM messages WHERE objet = ?",
                       (f"session-disparue:{COORD}",)) == [(0,)]


def test_remplacer_sans_session_existante_se_reduit_a_reprendre(banc, faux_lancer):
    banc.tmux.absente(COORD)
    facteur_pendant_les_attentes(banc)
    r = banc.acteur(ASSISTANT).cime("lancer", "coord", "alpha", "--reprendre", "--remplacer")
    assert r.code == 0, r.erreur
    assert not [c for c in banc.tmux.commandes() if c[0] == "kill-session"]
    assert faux_lancer == [("coord", "alpha", None, None)]


@pytest.mark.parametrize("qui", [COORD, W, COORD_B])
def test_remplacer_refuse_hors_assistant(banc, faux_lancer, qui):
    banc.tmux.repos(COORD)
    facteur_pendant_les_attentes(banc)
    r = banc.acteur(qui).cime("lancer", "coord", "alpha", "--reprendre", "--remplacer")
    assert r.code == 2 and "--remplacer est réservé à l'Assistant" in r.erreur
    assert ordres(banc) == [] and faux_lancer == []
    assert COORD_session(banc) in banc.tmux.sessions


def COORD_session(banc):
    return banc.tmux.nommer(COORD)


def test_remplacer_sans_reprendre_refuse(banc, faux_lancer):
    banc.tmux.repos(COORD)
    facteur_pendant_les_attentes(banc)
    r = banc.acteur(ASSISTANT).cime("lancer", "coord", "alpha", "--remplacer", "--phase", "p1")
    assert r.code == 2 and "--reprendre" in r.erreur
    assert ordres(banc) == [] and COORD_session(banc) in banc.tmux.sessions


def test_remplacer_facteur_arrete_ordre_en_file(banc, faux_lancer, monkeypatch):
    monkeypatch.setattr(lancer, "processus_claude_dans", lambda dossier: [])
    banc.tmux.repos(COORD)
    r = banc.acteur(ASSISTANT).cime("lancer", "coord", "alpha", "--reprendre", "--remplacer")
    assert r.code == 4 and "ordre #1 en file, facteur arrêté" in r.sortie
    assert ordres(banc) == [(1, "lancer", COORD, "en_file")]
    assert COORD_session(banc) in banc.tmux.sessions                            # rien n'a bougé sans facteur
    banc.facteur_tour()
    assert ordres(banc) == [(1, "lancer", COORD, "execute")]


# --- repondre à un message de cime : refusé, l'accusé suffit ----------------------------------------------

def _message_de_cime(banc, nature, objet, attend=None):
    from cime.fondation.registre import ouvrir
    from cime.signaux import commandes
    conn = ouvrir(banc.projet)
    try:
        return commandes.inscrire(conn, de="cime", a=COORD, nature=nature, resume=f"cime : {objet}",
                                  equipe="alpha", objet=objet, attend=attend,
                                  preuve={"cmd": "essai", "pid": 1})
    finally:
        conn.close()


@pytest.mark.parametrize("nature, objet, attend", [
    ("signalement", "session-disparue:worker-alpha-t1", None),
    ("relance", "relance:12", None),
    ("consigne", "ouverture", "accuse"),
])
def test_repondre_a_cime_refuse(banc, nature, objet, attend):
    identifiant = _message_de_cime(banc, nature, objet, attend)
    avant = banc.prouve("SELECT count(*) FROM messages")
    r = banc.acteur(COORD).cime("repondre", str(identifiant), "bien reçu")
    assert r.code != 0 and "accusé" in r.erreur
    assert banc.prouve("SELECT count(*) FROM messages") == avant


def test_repondre_a_un_agent_comme_avant(banc):
    q = envoyer(banc, W, COORD, "question", "quelle branche ?")
    r = banc.acteur(COORD).cime("repondre", str(q), "la branche x")
    assert r.code == 0, r.erreur
    assert banc.prouve("SELECT de, a, nature FROM messages WHERE id = ?", (r.id,)) == [(COORD, W, "reponse")]


# --- terminer --verifie : tâche finie avant le registre (sans travail_pret) ---------------------------

def _worker_d_avant_2_0(banc):
    """Tâche in-progress, session vivante, rapport et synthèse présents, aucun travail_pret."""
    tache(banc, dossier="in-progress")
    banc.tmux.repos(W)
    (banc.projet / ".orga/teams/alpha/reports" / f"{W}-2026-10-08.md").write_text("rapport\n")
    (banc.projet / ".orga/teams/alpha/conversations/t1-synthese.md").write_text("synthèse\n")
    assert banc.prouve("SELECT count(*) FROM messages WHERE nature = 'travail_pret'") == [(0,)]


def _verifie(banc, qui, sha_, *motif):
    return banc.acteur(qui).cime("terminer", "worker", "alpha", "t1", "--verifie", sha_, *motif)


def test_verifie_assistant_sha_de_main_inscrit_le_travail_pret_et_range(banc_depot, depot):
    banc = banc_depot
    _worker_d_avant_2_0(banc)
    sans = banc.acteur(COORD).cime("terminer", "worker", "alpha", "t1")
    assert sans.code == 2 and "aucun travail_pret" in sans.erreur             # le chemin normal, inchangé
    facteur_pendant_les_attentes(banc)
    r = _verifie(banc, ASSISTANT, sha(depot, "main"), "--motif", "livré avant le registre (1a2b3c4)")
    assert r.code == 0, r.erreur
    (ligne,) = banc.prouve("SELECT de, a, resume FROM messages WHERE nature = 'travail_pret'")
    assert ligne[:2] == (W, COORD) and "livré avant le registre" in ligne[2]
    assert banc.prouve("SELECT json_extract(preuve, '$.verifie'), json_extract(preuve, '$.cmd') FROM transitions"
                       " WHERE etat = 'inscrit' AND message_id = (SELECT id FROM messages"
                       " WHERE nature = 'travail_pret')") == [(sha(depot, "main"), "terminer")]
    assert (banc.projet / ".orga/teams/alpha/tasks/done/t1.md").exists()
    assert f"es-{W}" not in banc.tmux.sessions
    assert banc.prouve("SELECT etat FROM obligations WHERE message_id = (SELECT id FROM messages"
                       " WHERE nature = 'travail_pret')") == [("satisfaite",)]


@pytest.mark.parametrize("qui", [COORD, W])
def test_verifie_refuse_a_tout_autre_que_l_assistant(banc_depot, depot, qui):
    banc = banc_depot
    _worker_d_avant_2_0(banc)
    r = _verifie(banc, qui, sha(depot, "main"), "--motif", "x")
    assert r.code == 2 and "réservé à l'Assistant" in r.erreur
    assert banc.prouve("SELECT count(*) FROM messages WHERE nature = 'travail_pret'") == [(0,)]
    assert (banc.projet / ".orga/teams/alpha/tasks/in-progress/t1.md").exists()


def test_verifie_refuse_un_sha_hors_main_ou_inconnu(banc_depot, depot):
    banc = banc_depot
    _worker_d_avant_2_0(banc)
    for faux in (sha(depot, "equipe/alpha"), "0" * 40, "pas-un-sha"):
        r = _verifie(banc, ASSISTANT, faux, "--motif", "x")
        assert r.code == 2 and "pas dans main" in r.erreur
    assert banc.prouve("SELECT count(*) FROM messages WHERE nature = 'travail_pret'") == [(0,)]
    assert (banc.projet / ".orga/teams/alpha/tasks/in-progress/t1.md").exists()


def test_verifie_sans_motif_est_refuse(banc_depot, depot):
    banc = banc_depot
    _worker_d_avant_2_0(banc)
    r = _verifie(banc, ASSISTANT, sha(depot, "main"))
    assert r.code == 2 and "--motif" in r.erreur
    assert banc.prouve("SELECT count(*) FROM messages WHERE nature = 'travail_pret'") == [(0,)]
    assert (banc.projet / ".orga/teams/alpha/tasks/in-progress/t1.md").exists()


def test_verifie_ne_dispense_pas_du_rapport(banc_depot, depot):
    banc = banc_depot
    tache(banc, dossier="in-progress")
    banc.tmux.repos(W)
    r = _verifie(banc, ASSISTANT, sha(depot, "main"), "--motif", "x")
    assert r.code == 2 and "aucun rapport" in r.erreur
    assert banc.prouve("SELECT count(*) FROM messages WHERE nature = 'travail_pret'") == [(0,)]
