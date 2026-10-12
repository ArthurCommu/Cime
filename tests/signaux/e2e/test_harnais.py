"""Le harnais se prouve lui-même : chaque pièce tient son contrat avant de servir de preuve."""
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

import pytest

from e2e.banc import DATETIME_REEL, TIME_REEL
from e2e.conftest import SEAMS_TMUX

from cime.fondation import invite
from cime.fondation.registre import horodatage
from cime.fondation.projet import lire_manifeste


# --- l'horloge simulée avance TOUT -------------------------------------------------------------

def test_horloge_avance_horodatages_facteur_hooks_et_sommeils(horloge, projet):
    from cime.signaux import commandes, facteur, hooks, livraison
    avant = horodatage()
    h0, m0 = horloge.iso(), hooks._horloge()
    horloge.avance(minutes=5)
    assert horodatage() == horloge.iso() and horodatage() > avant
    assert (facteur._maintenant() - horloge.maintenant()).total_seconds() == 0
    assert hooks._horloge() - m0 == 300
    assert commandes.secondes_depuis(h0) == 300
    # un sommeil n'attend pas : il avance l'horloge
    reel = TIME_REEL.monotonic()
    livraison._dormir(120)
    hooks._dormir(30)
    assert TIME_REEL.monotonic() - reel < 1
    assert hooks._horloge() - m0 == 450 and horloge.sommeils == [120, 30]


def test_aucun_module_de_cime_ne_garde_l_horloge_reelle(horloge):
    for nom, mod in list(sys.modules.items()):
        if nom.startswith("cime") and mod is not None:
            assert getattr(mod, "datetime", None) is not DATETIME_REEL, nom
            assert getattr(mod, "time", None) is not TIME_REEL, nom


def test_sommeil_declenche_les_rappels(horloge):
    vus = []
    horloge.pendant_sommeil.append(lambda h: vus.append(h.monotonic()))
    from cime.signaux import hooks
    hooks._dormir(1.0)
    assert len(vus) == 1


# --- le faux tmux tient le protocole -----------------------------------------------------------

def test_tmux_branche_sur_tous_les_seams(tmux):
    import importlib
    for nom in SEAMS_TMUX:
        assert importlib.import_module(nom)._tmux is tmux, nom


def test_send_keys_l_puis_enter_sont_separes(tmux):
    from cime.fondation import envoyer
    tmux.repos("coord-alpha")
    envoyer._tmux("send-keys", "-t", "=es-coord-alpha:", "-l", "bonjour")
    assert tmux.invite_de("coord-alpha") == "bonjour" and tmux.entrees == []
    envoyer._tmux("send-keys", "-t", "=es-coord-alpha:", "Enter")
    assert tmux.entrees == [("es-coord-alpha", "bonjour")] and tmux.invite_de("coord-alpha") == ""
    assert [c[:1] + c[-1:] for c in tmux.commandes()] == [("send-keys", "bonjour"), ("send-keys", "Enter")]


def test_captures_brouillon_suggestion_et_tour(tmux):
    from cime.signaux import livraison
    tmux.brouillon("coord-alpha", "à moitié écrit")
    assert invite.texte_invite(livraison._capturer("es-coord-alpha")) == "à moitié écrit"
    tmux.suggestion("coord-alpha", "essaie ceci")
    brute = livraison._capturer("es-coord-alpha")
    assert "\x1b[2m" in brute and "essaie ceci" in brute
    assert invite.texte_invite(brute) == ""                      # le texte atténué n'est pas un brouillon
    plat = tmux("capture-pane", "-p", "-t", "=es-coord-alpha:").stdout
    assert "\x1b" not in plat
    tmux.tour("coord-alpha")
    assert "Réflexion" in tmux("capture-pane", "-p", "-t", "=es-coord-alpha:").stdout
    assert invite.texte_invite(livraison._capturer("es-coord-alpha")) == ""


def test_session_absente_et_window_activity(tmux, horloge):
    from cime.signaux import livraison
    tmux.repos("assistant")
    assert livraison.sessions_vivantes() == {"es-assistant"}
    assert horloge.time() - livraison._activite("es-assistant") == pytest.approx(100.0)
    tmux.activite("assistant", horloge.time())
    assert livraison._activite("es-assistant") == horloge.time()
    tmux.absente("assistant")
    assert livraison.sessions_vivantes() == set()
    assert tmux("has-session", "-t", "=es-assistant").returncode == 1
    assert tmux("send-keys", "-t", "=es-assistant:", "Enter").returncode == 1
    tmux("new-session", "-d", "-s", "es-assistant")
    assert tmux("has-session", "-t", "=es-assistant").returncode == 0
    tmux("kill-session", "-t", "=es-assistant")
    assert tmux("has-session", "-t", "=es-assistant").returncode == 1


def test_injecteur_apres_la_nieme_capture(tmux):
    from cime.signaux import livraison
    tmux.brouillon("coord-alpha", "ab")
    tmux.injecter_apres(2, "x")
    livraison._capturer("es-coord-alpha")
    assert tmux.invite_de("coord-alpha") == "ab"
    livraison._capturer("es-coord-alpha")
    assert tmux.invite_de("coord-alpha") == "abx"


def test_injecteur_apres_frappe_et_entrelace(tmux):
    tmux.repos("coord-alpha")
    tmux.injecter_apres_frappe("!")
    tmux("send-keys", "-t", "=es-coord-alpha:", "-l", "abcd")
    assert tmux.invite_de("coord-alpha") == "abcd!"
    tmux.repos("coord-alpha")
    tmux.entrelacer("#")
    tmux("send-keys", "-t", "=es-coord-alpha:", "-l", "abcd")
    assert tmux.invite_de("coord-alpha") == "ab#cd"


def test_journal_marque_l_origine_facteur(banc):
    banc.tmux.repos("coord-alpha")
    banc.acteur("coord-alpha").hook("Stop", {})             # au repos : le facteur peut livrer
    banc.horloge.avance(minutes=2)
    banc.tmux("list-sessions")                              # un appel hors facteur
    banc.acteur("assistant").cime("envoyer", "--a", "coord-alpha", "--nature", "consigne", "--attend", "rien", "Bonjour")
    banc.facteur_tour()
    assert banc.tmux.origine == "hors-facteur"
    assert banc.tmux.journal[0]["origine"] == "hors-facteur"
    du_facteur = banc.tmux.commandes("facteur")
    frappes = [c for c in du_facteur if c[0] == "send-keys"]
    assert "-l" in frappes[0] and frappes[1][-1] == "Enter"      # texte puis Enter, deux commandes
    assert banc.tmux.entrees and banc.tmux.entrees[0][0] == "es-coord-alpha"
    # la preuve : rien n'a été émis hors du facteur par les actes de l'acteur
    assert all(c[0] == "list-sessions" for c in banc.tmux.commandes("hors-facteur"))


# --- les acteurs ---------------------------------------------------------------------------------

def test_acteur_appelle_la_vraie_commande(banc):
    code, sortie, ident = banc.acteur("coord-alpha").cime(
        "envoyer", "--a", "assistant", "--nature", "question", "Une question ?")
    assert code == 0 and isinstance(ident, int)
    assert banc.prouve("SELECT de, a, nature FROM messages WHERE id = ?", (ident,)) == [
        ("coord-alpha", "assistant", "question")]


def test_acteur_restaure_l_environnement(banc):
    import os
    avant = dict(os.environ)
    banc.acteur("coord-alpha").cime("envoyer", "--a", "assistant", "--nature", "question", "q")
    banc.acteur("coord-alpha").hook("Stop", {})
    assert dict(os.environ) == avant


def test_acteur_sans_identite_claudecode_refuse(banc):
    r = banc.acteur(None).cime("envoyer", "--a", "assistant", "--nature", "question", "q")
    assert r.code != 0 and banc.prouve("SELECT COUNT(*) FROM messages") == [(0,)]


def test_acteur_appelle_le_vrai_hook(banc):
    r = banc.acteur("coord-alpha").hook("UserPromptSubmit", {"prompt": "go"})
    assert r.code == 0
    assert banc.prouve("SELECT agent, evenement FROM evenements") == [("coord-alpha", "UserPromptSubmit")]


def test_acteur_inerte_n_ecrit_rien(banc):
    inerte = banc.acteur("coord-alpha").inerte()
    assert inerte.cime("envoyer", "--a", "assistant", "--nature", "question", "q") is None
    assert inerte.hook("Stop", {}) is None
    assert banc.prouve("SELECT COUNT(*) FROM messages WHERE de = 'coord-alpha'") == [(0,)]
    assert banc.prouve("SELECT COUNT(*) FROM evenements") == [(0,)]


def test_envois_en_parallele_d_un_meme_acteur(banc):
    codes = banc.en_parallele(banc.acteur("coord-alpha"),
                              ("envoyer", "--a", "assistant", "--nature", "question", "un"),
                              ("envoyer", "--a", "assistant", "--nature", "compte_rendu", "deux"))
    assert codes == [0, 0]
    assert banc.prouve("SELECT COUNT(*) FROM messages WHERE de = 'coord-alpha'") == [(2,)]


# --- prouve et les fabriques ---------------------------------------------------------------------

def test_prouve_est_en_lecture_seule(banc):
    assert banc.prouve("SELECT COUNT(*) FROM messages") == [(0,)]
    with pytest.raises(sqlite3.OperationalError):
        banc.prouve("INSERT INTO evenements (agent, evenement, horodatage) VALUES ('x', 'y', 'z')")


def test_projet_jetable_complet(projet, banc):
    m = lire_manifeste(projet)
    assert m.prefixe == "es" and m.contrats == {"etat": ["alpha"]}
    for e in ("alpha", "beta"):
        for sous in ("tasks", "reports", "conversations"):
            assert (projet / ".orga" / "teams" / e / sous).is_dir()
    assert not (projet / ".git").exists()
    assert str(projet).startswith(str(projet.parents[0]))
    import os
    assert os.environ["CIME_PROJET"] == str(projet)


def test_depot_jetable_avec_main_branche_et_worktree(depot):
    def git(*a, cwd=depot):
        return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()
    assert git("rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert git("rev-list", "--count", "main..equipe/alpha") == "1"
    assert (depot / ".orga" / "worktrees" / "alpha" / "src" / "alpha.txt").is_file()
    assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=depot / ".orga" / "worktrees" / "alpha") == "equipe/alpha"
    assert "alpha.txt" not in git("ls-files")
    assert "worktrees/alpha" in git("worktree", "list")


def test_les_fabriques_refusent_un_dossier_non_jetable():
    from aide import DEPOT, exiger_jetable
    with pytest.raises(ValueError):
        exiger_jetable(DEPOT)


# --- les scènes d'agent et les processus parallèles --------------------------------------------------

def test_scenes_au_repos_et_au_travail(banc):
    from cime.signaux import livraison
    from cime.fondation.registre import ouvrir
    banc.au_travail("coord-alpha")
    conn = ouvrir(banc.projet)
    assert livraison.etat_agent(conn, "coord-alpha", banc.horloge.maintenant()) == "tour"
    banc.au_repos("coord-alpha")
    assert livraison.etat_agent(conn, "coord-alpha", banc.horloge.maintenant()) == "repos"
    banc.au_travail("coord-beta")
    banc.au_repos("coord-beta", par="idle")
    assert livraison.etat_agent(conn, "coord-beta", banc.horloge.maintenant()) == "repos"
    conn.close()


def test_faire_tourner_avance_l_horloge_et_s_arrete_sur_condition(banc):
    debut = banc.horloge.maintenant()
    assert banc.faire_tourner(90) == 3
    assert (banc.horloge.maintenant() - debut).total_seconds() == 90
    assert banc.faire_tourner(600, jusqu_a=lambda: True) == 1
    assert banc.prouve("SELECT count(*) FROM facteur") == [(1,)]


def test_en_processus_lance_de_vrais_processus_avec_l_identite(banc):
    sorties = banc.en_processus(
        ("assistant", ("envoyer", "--a", "coord-alpha", "--nature", "consigne", "--attend", "rien", "un"), None),
        ("assistant", ("envoyer", "--a", "coord-beta", "--nature", "consigne", "--attend", "rien", "deux"), None))
    assert [s[0] for s in sorties] == [0, 0]
    assert banc.prouve("SELECT de, a FROM messages ORDER BY a") == [
        ("assistant", "coord-alpha"), ("assistant", "coord-beta")]
