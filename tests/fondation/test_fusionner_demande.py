"""`cime fusionner` pose lui-même la demande d'accord qui manque, une seule fois par sha, et n'accorde
jamais ; le worktree d'essai porte un nom de longueur fixe (le chemin de la socket des tests de
l'hôte tient sous sa limite). Même faux dépôt et mêmes doubles que `test_fusionner`."""
import re
import subprocess
from pathlib import Path

import pytest

from cime.fondation import fusionner
from cime.fondation.registre import inscrire_message, inscrire_transition, ouvrir
from test_fusionner import (avec_fichier, essais, journal_registre, lancer, lignes_journal,  # noqa: F401
                            monde, propre)
from test_garde_fusion import _git, depot, donner_accord, identite, sha_de  # noqa: F401
from test_garde_fusions_auto import activer, branche, manifeste  # noqa: F401


def messages(depot, **filtres):
    """Les lignes `messages` du registre : (id, de, a, nature, objet, resume, corps)."""
    conn = ouvrir(depot)
    try:
        lignes = conn.execute("SELECT id, de, a, nature, objet, resume, corps FROM messages"
                              " ORDER BY id").fetchall()
    finally:
        conn.close()
    cles = ("id", "de", "a", "nature", "objet", "resume", "corps")
    return [d for d in (dict(zip(cles, l)) for l in lignes)
            if all(d[k] == v for k, v in filtres.items())]


def demandes(depot, equipe="x"):
    return [m for m in messages(depot, nature="decision_utilisateur")
            if m["objet"].startswith(f"fusion:{equipe}:")]


def aucun_accord_de_la_commande(depot):
    """Le registre ne porte aucun `accord` écrit par la commande, ni transition sur un accord."""
    conn = ouvrir(depot)
    try:
        assert conn.execute("SELECT COUNT(*) FROM messages WHERE nature = 'accord' AND de != 'utilisateur'"
                            ).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM transitions t JOIN messages m ON m.id = t.message_id"
                            " WHERE m.nature = 'accord' AND t.auteur = 'cime'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM messages WHERE de = 'assistant' AND en_reponse_a IN"
                            " (SELECT id FROM messages WHERE nature = 'decision_utilisateur')"
                            ).fetchone()[0] == 0
    finally:
        conn.close()


def repondre_a(depot, numero, nature):
    """L'utilisateur répond à la demande (`accord` ou `refus`), comme `cime accorder|refuser`."""
    conn = ouvrir(depot)
    try:
        ancienne = conn.execute("SELECT objet, equipe FROM messages WHERE id = ?", (numero,)).fetchone()
        return inscrire_message(conn, de="utilisateur", a="assistant", nature=nature, resume=nature,
                                equipe=ancienne[1], objet=ancienne[0], en_reponse_a=numero)
    finally:
        conn.close()


def rien_d_essai(depot, monde):
    assert not any(a[:2] == ("worktree", "add") for a in monde.git)
    assert monde.suites == [] and essais(depot) == []


# --- la demande est posée ---------------------------------------------------------------------

def test_chemin_reserve_sans_accord_pose_la_demande(depot, monde, capsys):
    avec_fichier(depot, "CLAUDE.md", "x\n")
    sha, avant = sha_de(depot, "equipe/x"), sha_de(depot, "main")
    code, _, erreur = lancer(depot, capsys)
    [d] = demandes(depot)
    assert code == 1 and sha_de(depot, "main") == avant
    assert (d["de"], d["a"], d["nature"], d["objet"]) == ("assistant", "utilisateur",
                                                          "decision_utilisateur", f"fusion:x:{sha}")
    assert len(d["resume"]) <= 160 and "CLAUDE.md" in d["resume"] and "x" in d["resume"] and sha[:7] in d["resume"]
    assert "CLAUDE.md" in d["corps"] and len(d["corps"]) <= 4000
    assert (f"accord de l'utilisateur manquant pour x {sha[:7]} : demande #{d['id']} posée sur la page ; "
            "relance `cime fusionner x` après son accord") in erreur
    rien_d_essai(depot, monde)
    aucun_accord_de_la_commande(depot)
    propre(depot, monde)


def test_la_demande_est_inscrite_par_cime_avec_sa_preuve(depot, monde, capsys):
    lancer(depot, capsys)
    [d] = demandes(depot)
    conn = ouvrir(depot)
    try:
        auteur, preuve = conn.execute("SELECT auteur, preuve FROM transitions WHERE message_id = ?"
                                      " AND etat = 'inscrit'", (d["id"],)).fetchone()
        assert conn.execute("SELECT etat FROM obligations WHERE message_id = ?", (d["id"],)).fetchone()[0] == "ouverte"
    finally:
        conn.close()
    assert auteur == "cime" and '"cmd": "fusionner"' in preuve and '"pid"' in preuve


def test_le_resume_nomme_trois_fichiers_au_plus(depot, monde, capsys):
    branche(depot, "equipe/r", {f".orga/socle/f{i}.md": "x" for i in range(5)})
    lancer(depot, capsys, equipe="r")
    [d] = demandes(depot, "r")
    assert d["resume"].count(".orga/socle/f") == 3 and d["resume"].endswith("…")
    assert len(d["resume"]) <= 160
    assert all(f".orga/socle/f{i}.md" in d["corps"] for i in range(5))


def test_le_resume_reste_sous_la_limite_avec_de_longs_noms(depot, monde, capsys):
    longs = {f".orga/socle/{'n' * 80}{i}.md": "x" for i in range(3)}
    branche(depot, "equipe/r", longs)
    lancer(depot, capsys, equipe="r")
    [d] = demandes(depot, "r")
    assert len(d["resume"]) == 160


def test_aucun_reserve_option_inactive_le_resume_le_dit(depot, monde, capsys):
    avec_fichier(depot)    # a.txt : pas réservé
    lancer(depot, capsys)
    [d] = demandes(depot)
    assert "accord requis : mode autonome inactif" in d["resume"]


def test_option_suspendue_sans_reserve_le_resume_le_dit(depot, monde, capsys):
    avec_fichier(depot)
    activer(depot)
    manifeste(depot, '\n[fusions_auto]\nreserves = ["autre/"]\n')    # la liste change : suspendue
    _git("branch", "-f", "equipe/x", "equipe/x", cwd=depot)
    lancer(depot, capsys)
    [d] = demandes(depot)
    assert "mode autonome inactif" in d["resume"]


def test_le_refus_journalise_porte_l_id_de_la_demande(depot, monde, capsys):
    lancer(depot, capsys)
    [d] = demandes(depot)
    [(auteur, cible, details, resultat)] = journal_registre(depot, "fusion_refusee")
    assert resultat == "refuse-accord" and f'"demande": {d["id"]}' in details
    assert LIGNE_JOURNAL_REFUS.match(lignes_journal(depot)[-1])


LIGNE_JOURNAL_REFUS = re.compile(r".* resultat=refuse-accord$")


# --- une seule fois par sha --------------------------------------------------------------------

def test_relance_sans_accord_ne_repose_pas(depot, monde, capsys):
    lancer(depot, capsys)
    [d] = demandes(depot)
    avant = len(messages(depot))
    code, _, erreur = lancer(depot, capsys)
    assert code == 1 and len(demandes(depot)) == 1 and len(messages(depot)) == avant
    assert f"demande #{d['id']} déjà posée pour ce sha (en attente) : attends l'accord de l'utilisateur" in erreur
    code, _, erreur = lancer(depot, capsys)
    assert code == 1 and len(demandes(depot)) == 1
    aucun_accord_de_la_commande(depot)


def test_demande_close_n_est_pas_reposee(depot, monde, capsys):
    lancer(depot, capsys)
    [d] = demandes(depot)
    conn = ouvrir(depot)
    try:
        inscrire_transition(conn, d["id"], "clos", "utilisateur", {})
    finally:
        conn.close()
    code, _, erreur = lancer(depot, capsys)
    assert code == 1 and len(demandes(depot)) == 1 and "déjà posée" in erreur


def test_demande_refusee_par_l_utilisateur_n_est_pas_reposee_et_le_dit(depot, monde, capsys):
    lancer(depot, capsys)
    [d] = demandes(depot)
    repondre_a(depot, d["id"], "refus")
    code, _, erreur = lancer(depot, capsys)
    assert code == 1 and len(demandes(depot)) == 1
    assert f"demande #{d['id']} refusée par l'utilisateur" in erreur and "pas reposée" in erreur
    rien_d_essai(depot, monde)
    aucun_accord_de_la_commande(depot)


def test_la_branche_qui_avance_donne_une_nouvelle_demande(depot, monde, capsys):
    lancer(depot, capsys)
    ancien = sha_de(depot, "equipe/x")
    avec_fichier(depot, "b.txt", "b\n")
    nouveau = sha_de(depot, "equipe/x")
    code, _, erreur = lancer(depot, capsys)
    assert code == 1 and [d["objet"] for d in demandes(depot)] == [f"fusion:x:{ancien}", f"fusion:x:{nouveau}"]
    assert f"demande #{demandes(depot)[1]['id']} posée" in erreur


def _accord_consomme(depot, numero):
    """L'utilisateur accorde la demande, puis la fusion consomme l'accord."""
    accord = repondre_a(depot, numero, "accord")
    conn = ouvrir(depot)
    try:
        for etat in ("livre", "pris_en_compte", "clos"):
            inscrire_transition(conn, accord, etat, "utilisateur", {})
    finally:
        conn.close()
    return accord


def test_demande_accordee_et_consommee_le_dit(depot, monde, capsys):
    lancer(depot, capsys)
    [d] = demandes(depot)
    _accord_consomme(depot, d["id"])
    avant = len(messages(depot))
    code, _, erreur = lancer(depot, capsys)
    assert code == 1 and len(messages(depot)) == avant
    assert (f"demande #{d['id']} déjà accordée pour ce sha et consommée : rien à refaire ; "
            "si la branche a avancé, c'est un nouveau sha") in erreur
    assert "en attente" not in erreur and "attends l'accord" not in erreur


def test_branche_deja_dans_la_reference_ne_pose_aucune_demande(depot, monde, capsys):
    avec_fichier(depot)
    donner_accord(depot, clos=True)
    _git("merge", "-q", "--ff-only", "equipe/x", cwd=depot)    # la branche est déjà dans main
    avant = len([m for m in messages(depot) if m["objet"].startswith("fusion:")])
    code, _, erreur = lancer(depot, capsys)
    assert code == 1 and "aucun accord de l'utilisateur non consommé" in erreur
    assert "demande #" not in erreur
    assert len([m for m in messages(depot) if m["objet"].startswith("fusion:")]) == avant
    assert demandes(depot) == []


def test_branche_deja_dans_la_reference_ne_reprend_pas_une_demande_en_attente(depot, monde, capsys):
    lancer(depot, capsys)                                      # la demande est posée, sans réponse
    _git("merge", "-q", "--ff-only", "equipe/x", cwd=depot)    # la branche entre dans main par ailleurs
    code, _, erreur = lancer(depot, capsys)
    assert code == 1 and "déjà posée" not in erreur and "en attente" not in erreur
    assert len(demandes(depot)) == 1


def test_apres_une_fusion_le_nouveau_sha_a_sa_propre_demande(depot, monde, capsys):
    avec_fichier(depot)
    donner_accord(depot)
    assert lancer(depot, capsys)[0] == 0
    avec_fichier(depot, "b.txt", "b\n")                        # la branche avance
    nouveau = sha_de(depot, "equipe/x")
    code, _, erreur = lancer(depot, capsys)
    [d] = demandes(depot)
    assert code == 1 and d["objet"] == f"fusion:x:{nouveau}" and f"demande #{d['id']} posée" in erreur


def test_l_objet_porte_le_sha_complet(depot, monde, capsys):
    lancer(depot, capsys)
    [d] = demandes(depot)
    assert re.fullmatch(r"fusion:x:[0-9a-f]{40}", d["objet"])


# --- l'utilisateur accorde, la commande fusionne -----------------------------------------------

def test_apres_l_accord_de_l_utilisateur_la_relance_fusionne(depot, monde, capsys):
    avec_fichier(depot)
    lancer(depot, capsys)
    [d] = demandes(depot)
    sha = sha_de(depot, "equipe/x")
    accord = repondre_a(depot, d["id"], "accord")
    conn = ouvrir(depot)
    try:
        for etat in ("livre", "pris_en_compte"):
            inscrire_transition(conn, accord, etat, "utilisateur", {})
    finally:
        conn.close()
    code, sortie, _ = lancer(depot, capsys)
    assert code == 0, sortie
    assert subprocess.run(["git", "-C", str(depot), "merge-base", "--is-ancestor", sha, "main"]).returncode == 0
    assert len(demandes(depot)) == 1
    assert [m["de"] for m in messages(depot, nature="accord")] == ["utilisateur"]


# --- les autres refus ne posent rien ------------------------------------------------------------

def test_conflit_ne_pose_aucune_demande(depot, monde, capsys):
    from test_garde_fusions_auto import ecrire, valider
    ecrire(depot, {"f.txt": "base\n"})
    valider(depot, "base")
    _git("branch", "-f", "equipe/x", "main", cwd=depot)
    avec_fichier(depot, "f.txt", "equipe\n")
    ecrire(depot, {"f.txt": "main\n"})
    valider(depot, "main change f")
    donner_accord(depot)
    code, _, erreur = lancer(depot, capsys)
    assert code == 1 and "conflits" in erreur and demandes(depot) == []
    aucun_accord_de_la_commande(depot)


def test_suite_en_echec_ne_pose_aucune_demande(depot, monde, capsys):
    donner_accord(depot)
    monde.suite = lambda p, d: (1, "FAILED tests/a.py::t\n1 failed in 0.1s\n")
    code, _, _ = lancer(depot, capsys)
    assert code == 1 and demandes(depot) == []


def test_verrou_pris_ne_pose_aucune_demande(depot, monde, capsys):
    donner_accord(depot)
    detenteur = fusionner._Verrou(depot, "y", "a" * 40)
    detenteur.prendre()
    try:
        code, _, _ = lancer(depot, capsys)
    finally:
        detenteur.liberer()
    assert code == 2 and demandes(depot) == []


def test_identite_refusee_ne_pose_aucune_demande(depot, monde, capsys, monkeypatch):
    identite(monkeypatch, "coord-x")
    code, _, _ = lancer(depot, capsys)
    assert code == 1 and demandes(depot) == []


def test_charge_trop_longue_ne_pose_aucune_demande(depot, monde, capsys, monkeypatch):
    donner_accord(depot)
    monde.workers = 2
    horloge = iter(range(0, 10 ** 6, 600))
    monkeypatch.setattr(fusionner, "_horloge", lambda: next(horloge))
    monkeypatch.setattr(fusionner, "_dormir", lambda s: None)
    code, _, _ = lancer(depot, capsys)
    assert code == 2 and demandes(depot) == []


def test_branche_qui_n_est_pas_une_branche_d_equipe_ne_pose_rien(depot, monde, capsys, monkeypatch):
    # les règles refusent pour une autre raison : le manifeste ne fait pas de `equipe/x` une branche d'équipe
    monkeypatch.setattr(fusionner, "_regles", lambda p, b, s: (_ for _ in ()).throw(
        fusionner._Refus("fusion non permise : x n'est pas une branche d'équipe")))
    monkeypatch.setattr(fusionner, "_demande_requise", lambda p, r, s: None)
    code, _, _ = lancer(depot, capsys)
    assert code == 1 and demandes(depot) == []


def test_voie_automatique_ouverte_ne_demande_rien(depot, monde, capsys):
    avec_fichier(depot)    # a.txt : rien de réservé
    activer(depot)
    code, sortie, erreur = lancer(depot, capsys)
    assert code == 0, erreur
    assert demandes(depot) == []
    aucun_accord_de_la_commande(depot)


def test_voie_automatique_ouverte_mais_conflit_ne_demande_rien(depot, monde, capsys):
    from test_garde_fusions_auto import ecrire, valider
    ecrire(depot, {"f.txt": "base\n"})
    valider(depot, "base")
    _git("branch", "-f", "equipe/x", "main", cwd=depot)
    avec_fichier(depot, "f.txt", "equipe\n")
    ecrire(depot, {"f.txt": "main\n"})
    valider(depot, "main change f")
    activer(depot)
    code, _, erreur = lancer(depot, capsys)
    assert code == 1 and demandes(depot) == []


def test_accord_present_ne_demande_rien(depot, monde, capsys):
    donner_accord(depot)
    code, _, _ = lancer(depot, capsys)
    assert code == 0 and demandes(depot) == []


def test_registre_illisible_ne_pose_rien_et_refuse_quand_meme(depot, monde, capsys, monkeypatch):
    from cime.fondation import garde

    def casse(projet):
        raise OSError("illisible")
    monkeypatch.setattr(garde, "accords_fusion_libres", casse)
    code, _, erreur = lancer(depot, capsys)
    assert code == 1 and demandes(depot) == []


def test_inscription_impossible_refuse_quand_meme(depot, monde, capsys, monkeypatch):
    monkeypatch.setattr(fusionner, "_poser_la_demande",
                        lambda *a: (_ for _ in ()).throw(OSError("disque plein")))
    code, _, erreur = lancer(depot, capsys)
    assert code == 1 and "demande d'accord non inscrite" in erreur and "OSError" in erreur
    rien_d_essai(depot, monde)


# --- le worktree d'essai a un nom de longueur fixe ----------------------------------------------

LIMITE_SOCKET = 100


def _socket_de_l_hote() -> str:
    """Le chemin de la socket d'essai de `tests/hote/conftest.py`, relatif à la racine du worktree,
    lu depuis ce conftest."""
    source = (Path(__file__).resolve().parents[1] / "hote" / "conftest.py").read_text(encoding="utf-8")
    dossier = re.search(r'^DOSSIER_ESSAI = RACINE / "([^"]+)"', source, re.M).group(1)
    socket = re.search(r'^SOCKET_ESSAI = str\(DOSSIER_ESSAI / "([^"]+)"\)', source, re.M).group(1)
    return f"{dossier}/{socket}"


def _racine_du_projet() -> Path:
    """La racine du dépôt (le checkout principal, même depuis un worktree)."""
    commun = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            cwd=Path(__file__).resolve().parent, capture_output=True, text=True, check=True)
    return Path(commun.stdout.strip()).parent


def _longueur_socket(racine: Path, nom: str) -> int:
    return len(str(racine / ".orga" / "etat" / "tmp" / nom / _socket_de_l_hote()))


def test_le_chemin_d_essai_garde_la_socket_de_l_hote_sous_la_limite():
    sha, equipe = "a" * 40, "e" * 40
    racine = _racine_du_projet()
    assert _longueur_socket(racine, fusionner.nom_essai(sha)) <= LIMITE_SOCKET
    assert _longueur_socket(racine, fusionner.nom_essai(sha)) == _longueur_socket(
        racine, fusionner.nom_essai("b" * 40))    # indépendant de l'équipe et du sha : longueur fixe
    # la mutation : l'ancien nom, long d'un nom d'équipe de 40 caractères, ne tient pas
    assert _longueur_socket(racine, f"fusion-essai-{equipe}-{sha[:7]}") > LIMITE_SOCKET


def test_le_dossier_d_essai_porte_le_nom_calcule_et_un_reste_est_reconnu(depot, monde, capsys):
    avec_fichier(depot)
    sha = sha_de(depot, "equipe/x")
    reste = depot / ".orga" / "etat" / "tmp" / fusionner.nom_essai(sha)
    _git("worktree", "add", "--detach", str(reste), "main", cwd=depot)    # un essai interrompu
    donner_accord(depot)
    code, sortie, erreur = lancer(depot, capsys)
    assert code == 0, erreur
    assert monde.suites == [reste]
    propre(depot, monde)


@pytest.mark.parametrize("sha", ["0123456789abcdef" * 2 + "01234567", "f" * 40])
def test_nom_essai_dependant_du_sha_seulement(sha):
    assert fusionner.nom_essai(sha) == f"fe-{sha[:7]}"
