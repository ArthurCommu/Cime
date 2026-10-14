"""Fusions automatiques : les règles de la garde permettent la fusion d'une branche d'équipe sans
accord par sha quand l'option est active et que les cinq conditions tiennent ; pour chacune, un test
où elle seule est fausse. L'Assistant ne lance plus `git merge` : ces règles sont jugées sur la
référence, comme le fait `cime fusionner`. Dépôts git jetables sous tmp_path ; `CIME_PROJET` et
`CIME_AGENT` posés dans les tests, jamais sur le vrai projet."""
import json
import os
import sqlite3
import subprocess

import pytest

from cime.fondation import fusions_auto, garde
from cime.fondation.garde import decider, fusions_autorisees
from cime.fondation.registre import inscrire_message, ouvrir
from test_garde_fusion import (MANIFESTE, _git, depot, donner_accord, entree, fusions, identite,  # noqa: F401
                               lancer, poste, sha_de)

MERGE = "git merge equipe/x"


@pytest.fixture(autouse=True)
def _assistant(depot, monkeypatch):   # après `depot`, qui efface l'identité
    identite(monkeypatch, "assistant")


def ecrire(depot, fichiers):
    for chemin, contenu in fichiers.items():
        cible = depot / chemin
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_text(contenu)


def valider(depot, message="c"):
    # sans .orga/etat (le registre) : validé sur une branche, il disparaîtrait au retour sur main
    _git("add", "-A", "--", ".", ":!.orga/etat", cwd=depot)
    _git("commit", "-q", "--allow-empty", "-m", message, cwd=depot)


def branche(depot, nom, fichiers=None, depuis="main"):
    """Une branche `nom` partant de `depuis`, un commit qui écrit `fichiers` ; on revient sur main."""
    _git("checkout", "-q", "-b", nom, depuis, cwd=depot)
    ecrire(depot, fichiers or {})
    valider(depot, nom)
    _git("checkout", "-q", "main", cwd=depot)


def manifeste(depot, extra=""):
    (depot / ".orga" / "projet.toml").write_text(MANIFESTE + extra)
    valider(depot, "manifeste")


def activer(depot):
    assert fusions_auto._ecrire(depot, "active") == 0


def annoncer(depot, equipe="x", ref=None, sha=None, de="assistant", a="utilisateur",
             nature="rapport_utilisateur", objet=None):
    conn = ouvrir(depot)
    try:
        return inscrire_message(
            conn, de=de, a=a, nature=nature, resume="annonce", equipe=equipe,
            objet=objet or f"fusion-auto:{equipe}:{sha or sha_de(depot, ref or f'equipe/{equipe}')}")
    finally:
        conn.close()


def jugement(depot, *refs):
    """Les règles de fusion appliquées à chaque référence, dans un même contexte ; renvoie le contexte
    (voies, détails de la voie auto) et le premier motif de refus (None si toutes passent)."""
    ctx = garde._Contexte({}, depot)
    ctx.agent = "assistant"
    try:
        for ref in refs:
            garde._juger_fusion(ctx, ref)
    except garde._Refus as r:
        return ctx, str(r)
    return ctx, None


def refus(depot, commande=MERGE):
    """Le motif de refus des règles pour la dernière référence de `commande`, ou None."""
    return jugement(depot, commande.split()[-1])[1]


def refus_garde(depot, commande=MERGE):
    """Le motif de la garde (le hook) pour la commande, tel que l'Assistant le reçoit."""
    return decider(entree(commande, depot), depot)


@pytest.fixture
def pret(depot):
    """Option active, branche equipe/x éligible, annonce faite : la fusion passe."""
    manifeste(depot, '\n[fusions_auto]\nreserves = ["src/cime/fondation/"]\n')
    activer(depot)
    annoncer(depot)
    return depot


# --- le cas qui passe -----------------------------------------------------------------------

def test_fusion_eligible_avec_annonce_passe(pret):
    ctx, motif = jugement(pret, "equipe/x")
    assert motif is None and ctx.voies == {"equipe/x": "auto"}
    d = ctx.auto["equipe/x"]
    assert d["equipe"] == "x" and d["sha"] == sha_de(pret, "equipe/x")
    assert d["annonce"] == 1 and d["reglage"] == 1 and d["fichiers"] == 0


def test_la_garde_refuse_le_git_merge_meme_quand_les_regles_passent(pret):
    assert refus(pret) is None
    motif = refus_garde(pret)
    assert motif is not None and "cime fusionner" in motif
    assert fusions_autorisees(entree(MERGE, pret), pret) == []


def test_annonce_avec_sha_abrege_a_sept_caracteres(depot):
    activer(depot)
    annoncer(depot, objet=f"fusion-auto:x:{sha_de(depot, 'equipe/x')[:7]}")
    assert refus(depot) is None


def test_annonce_trop_abregee_refusee(depot):
    activer(depot)
    annoncer(depot, objet=f"fusion-auto:x:{sha_de(depot, 'equipe/x')[:6]}")
    assert "condition 4" in refus(depot)


# --- option inactive : strictement l'ancien comportement ---------------------------------------

def test_option_inactive_meme_avec_annonce_il_faut_l_accord(depot):
    annoncer(depot)
    motif = refus(depot)
    assert "exige un accord de l'utilisateur non consommé" in motif
    assert "Fusions automatiques" not in motif and "condition" not in motif


def test_option_desactivee_l_annonce_ne_vaut_plus(pret):
    assert refus(pret) is None
    assert fusions_auto._ecrire(pret, "inactive") == 0
    motif = refus(pret)
    assert "exige un accord" in motif and "Fusions automatiques" not in motif


# --- les cinq conditions, chacune seule fausse ---------------------------------------------------

def test_condition_1_branche_qui_n_est_pas_une_branche_d_equipe(pret):
    branche(pret, "feature/x")
    annoncer(pret, ref="feature/x", objet=f"fusion-auto:x:{sha_de(pret, 'feature/x')}")
    motif = refus(pret, "git merge feature/x")
    assert "condition 1" in motif and "branche d'équipe" in motif
    assert "exige un accord de l'utilisateur non consommé" in motif       # l'ancien contenu reste


@pytest.mark.parametrize("nom", ["equipe/Yy", "equipe/a_b", "equipe/a/b", "xequipe/x"])
def test_condition_1_motif_exact_de_la_branche(pret, nom):
    try:
        branche(pret, nom)
    except subprocess.CalledProcessError:
        pytest.skip("git refuse ce nom de branche")
    annoncer(pret, equipe="x", objet=f"fusion-auto:x:{sha_de(pret, nom)}")
    assert "condition 1" in refus(pret, f"git merge {nom}")


def test_condition_1_un_tag_homonyme_ne_passe_pas(pret):
    branche(pret, "equipe/z", {"z.txt": "z"})
    _git("tag", "equipe/z", "main", cwd=pret)         # le tag l'emporte sur la branche pour `git merge`
    annoncer(pret, equipe="z", objet=f"fusion-auto:z:{sha_de(pret, 'refs/heads/equipe/z')}")
    assert "condition 1" in refus(pret, "git merge equipe/z")


def test_condition_2_la_branche_touche_le_noyau(pret):
    branche(pret, "equipe/y", {".claude/x": "[x]\n", "src/ok.py": "1"})
    annoncer(pret, equipe="y", ref="equipe/y")
    motif = refus(pret, "git merge equipe/y")
    assert "condition 2" in motif and ".claude/x" in motif and "chemins réservés" in motif


@pytest.mark.parametrize("chemin", ["pyproject.toml", "sous/pyproject.toml", "uv.lock",
                                    ".orga/contracts/registre.schema.md", ".orga/org-chart.md",
                                    ".orga/dependencies.md", ".orga/teams/y/mandate.md"])
def test_condition_2_les_chemins_sortis_du_noyau_passent_la_voie_auto(pret, chemin):
    """Dépendances, contrats, organigramme et mandats ne sont pas des barrières."""
    branche(pret, "equipe/y", {chemin: "x\n"})
    annoncer(pret, equipe="y", ref="equipe/y")
    assert refus(pret, "git merge equipe/y") is None


@pytest.mark.parametrize("chemin", [".claude/x", "sous/dossier/.env",
                                    ".orga/projet.toml", ".orga/socle/a.md", "CLAUDE.md"])
def test_condition_2_les_chemins_restants_du_noyau_refusent(pret, chemin):
    branche(pret, "equipe/y", {chemin: "x\n"})
    annoncer(pret, equipe="y", ref="equipe/y")
    assert "condition 2" in refus(pret, "git merge equipe/y")


def test_condition_5_le_plafond_modifie_apres_l_activation_suspend(pret):
    """Le plafond fait partie de l'empreinte : le changer dans le manifeste suspend."""
    manifeste(pret, '\n[fusions_auto]\nreserves = ["src/cime/fondation/"]\nchantiers_par_jour = 9\n')
    assert "condition 5" in refus(pret)


def test_condition_5_une_activation_sans_portee_suspend(depot):
    conn = ouvrir(depot)
    reserves = fusions_auto.chemins_reserves(depot)
    with conn:
        conn.execute("INSERT INTO reglages_projet (horodatage, cle, valeur, auteur, details)"
                     " VALUES ('2026-10-12T00:00:00.000Z', 'fusions_auto', 'active', 'utilisateur', ?)",
                     (json.dumps({"reserves": reserves, "empreinte": fusions_auto.empreinte(
                         reserves, fusions_auto.plafond_chantiers(depot))}),))
    conn.close()
    annoncer(depot)
    assert "condition 5" in refus(depot)


def test_condition_2_la_branche_touche_un_chemin_du_manifeste(pret):
    branche(pret, "equipe/y", {"src/cime/fondation/garde.py": "x = 1\n"})
    annoncer(pret, equipe="y", ref="equipe/y")
    motif = refus(pret, "git merge equipe/y")
    assert "condition 2" in motif and "src/cime/fondation/garde.py" in motif


def test_condition_2_un_chemin_voisin_n_est_pas_reserve(pret):
    branche(pret, "equipe/y", {"src/cime/fondation2/x.py": "1", "src/neuf.py": "2"})
    annoncer(pret, equipe="y", ref="equipe/y")
    assert refus(pret, "git merge equipe/y") is None
    assert jugement(pret, "equipe/y")[0].auto["equipe/y"]["fichiers"] == 2


def test_condition_2_une_suppression_et_un_renommage_comptent(pret):
    _git("checkout", "-q", "-b", "equipe/y", "main", cwd=pret)
    ecrire(pret, {"src/a.py": "contenu assez long pour que git y voie un renommage\n" * 5})
    valider(pret, "a")
    _git("checkout", "-q", "main", cwd=pret)
    _git("merge", "-q", "equipe/y", cwd=pret)
    _git("checkout", "-q", "-b", "equipe/r", "main", cwd=pret)
    _git("mv", "src/a.py", ".env", cwd=pret)          # renommer VERS un chemin réservé
    valider(pret, "r")
    _git("checkout", "-q", "main", cwd=pret)
    annoncer(pret, equipe="r", ref="equipe/r")
    assert ".env" in refus(pret, "git merge equipe/r")


def test_condition_2_la_liste_enregistree_s_ajoute_a_l_actuelle(pret, monkeypatch):
    """Même si la liste actuelle ne contient plus l'entrée, celle de l'activation compte aussi."""
    branche(pret, "equipe/y", {"src/vieux/a.py": "1"})
    annoncer(pret, equipe="y", ref="equipe/y")
    vrai = fusions_auto.etat_courant
    monkeypatch.setattr(fusions_auto, "etat_courant", lambda p: {**vrai(p), "reserves": ["src/vieux/"]})
    assert "condition 2" in refus(pret, "git merge equipe/y")


def test_condition_2_la_liste_actuelle_du_manifeste_compte_aussi(pret):
    """Une entrée ajoutée au manifeste après l'activation : la branche qui la touche est refusée par
    la condition 2 (la liste courante), avant même la 5 (suspension)."""
    manifeste(pret, '\n[fusions_auto]\nreserves = ["src/cime/fondation/", "src/neuf/"]\n')
    branche(pret, "equipe/y", {"src/neuf/a.py": "1"})
    annoncer(pret, equipe="y", ref="equipe/y")
    motif = refus(pret, "git merge equipe/y")
    assert "condition 2" in motif and "src/neuf/a.py" in motif


def test_condition_3_conflit(pret):
    ecrire(pret, {"src/app.py": "a\n"})
    valider(pret, "app")
    branche(pret, "equipe/y", {"src/app.py": "b\n"}, depuis="main~1")
    annoncer(pret, equipe="y", ref="equipe/y")
    motif = refus(pret, "git merge equipe/y")
    assert "condition 3" in motif and "conflit" in motif


def test_condition_3_depot_principal_pas_sur_la_branche_de_reference(pret):
    _git("checkout", "-q", "-b", "autre", cwd=pret)
    motif = refus(pret)
    assert "condition 3" in motif and "n'est pas sur main" in motif


@pytest.mark.parametrize("variante", ["aucune", "autre_sha", "autre_auteur", "autre_nature",
                                      "autre_destinataire", "autre_equipe", "objet_autre_famille"])
def test_condition_4_annonce_absente_ou_inexacte(depot, variante):
    activer(depot)
    sha = sha_de(depot, "equipe/x")
    if variante == "autre_sha":
        annoncer(depot, sha="0" * 40)
    elif variante == "autre_auteur":
        annoncer(depot, de="coord-x")
    elif variante == "autre_nature":
        annoncer(depot, nature="signalement")
    elif variante == "autre_destinataire":
        annoncer(depot, a="assistant")
    elif variante == "autre_equipe":
        annoncer(depot, objet=f"fusion-auto:y:{sha}")
    elif variante == "objet_autre_famille":
        annoncer(depot, objet=f"fusion:x:{sha}")
    motif = refus(depot)
    assert "condition 4" in motif and "annonce" in motif
    assert f"fusion-auto:x:{sha[:10]}" in motif and "cime envoyer" in motif
    assert "exige un accord de l'utilisateur non consommé" in motif


def test_condition_4_la_branche_a_avance_depuis_l_annonce(pret):
    _git("checkout", "-q", "equipe/x", cwd=pret)
    valider(pret, "encore")
    _git("checkout", "-q", "main", cwd=pret)
    assert "condition 4" in refus(pret)
    annoncer(pret)                                                   # annonce pour la nouvelle pointe
    assert refus(pret) is None


def test_condition_4_une_annonce_ne_vaut_que_pour_sa_pointe_pas_pour_une_autre_branche(pret):
    branche(pret, "equipe/y", {"src/y.py": "1"})
    assert "condition 4" in refus(pret, "git merge equipe/y")


def test_condition_5_manifeste_modifie_apres_l_activation(pret):
    manifeste(pret, '\n[fusions_auto]\nreserves = ["src/cime/fondation/", "src/neuf/"]\n')
    motif = refus(pret)
    assert "condition 5" in motif and "réactiver" in motif
    assert "exige un accord de l'utilisateur non consommé" in motif
    assert fusions_auto._ecrire(pret, "active") == 0              # l'utilisateur revalide : ça passe
    assert refus(pret) is None


def test_condition_5_aucune_autre_condition_ne_masque_la_suspension(depot):
    """Branche éligible, annonce faite, seul le manifeste a bougé depuis l'activation."""
    activer(depot)
    annoncer(depot)
    assert refus(depot) is None
    manifeste(depot, '\n[fusions_auto]\nreserves = ["src/x/"]\n')
    assert "condition 5" in refus(depot)


def test_le_message_nomme_la_premiere_condition_fausse_dans_l_ordre(pret):
    branche(pret, "equipe/y", {".claude/x": "x"})                # 2 fausse ; 4 aussi (pas d'annonce)
    assert "condition 2" in refus(pret, "git merge equipe/y")


# --- l'accord par sha reste, et passe en premier ------------------------------------------------

def test_l_accord_passe_en_premier_meme_quand_l_option_est_active(pret):
    branche(pret, "equipe/y", {".claude/x": "x"})                # inéligible à la voie auto
    donner_accord(pret, "equipe/y", equipe="y")
    ctx, motif = jugement(pret, "equipe/y")
    assert motif is None and ctx.voies == {"equipe/y": "accord"}


def test_un_accord_et_une_annonce_pour_la_meme_pointe_prennent_la_voie_accord(pret):
    donner_accord(pret)
    assert jugement(pret, "equipe/x")[0].voies == {"equipe/x": "accord"}


def test_chaque_reference_est_jugee_separement_et_une_seule_refusee_refuse_tout(pret):
    branche(pret, "equipe/y", {"src/y.py": "1"})                  # éligible mais sans annonce
    ctx, motif = jugement(pret, "equipe/x", "equipe/y")
    assert motif is not None and "equipe/y" in motif and "condition 4" in motif
    annoncer(pret, equipe="y", ref="equipe/y")
    ctx, motif = jugement(pret, "equipe/x", "equipe/y")
    assert motif is None and ctx.voies == {"equipe/x": "auto", "equipe/y": "auto"}


def test_une_ref_par_accord_et_une_par_annonce(pret):
    branche(pret, "equipe/y", {".claude/x": "x"})
    donner_accord(pret, "equipe/y", equipe="y")
    ctx, motif = jugement(pret, "equipe/x", "equipe/y")
    assert motif is None and ctx.voies == {"equipe/x": "auto", "equipe/y": "accord"}


# --- les autres rôles et lieux : comportement actuel inchangé ---------------------------------

@pytest.mark.parametrize("nom", ["coord-fondation", "worker-fondation-x"])
def test_coordinateur_et_worker_toujours_refuses_option_active(pret, monkeypatch, nom):
    identite(monkeypatch, nom)
    motif = refus_garde(pret)
    assert "faite par l'Assistant" in motif


def test_sans_identite_toujours_refuse_option_active(pret, monkeypatch):
    identite(monkeypatch, None)
    assert "réservé à l'utilisateur" in refus_garde(pret)


def test_assistant_hors_depot_principal_inchange(pret, tmp_path):
    autre = tmp_path / "autre"
    autre.mkdir()
    _git("init", "-q", "-b", "feature", cwd=autre)
    _git("commit", "-q", "--allow-empty", "-m", "i", cwd=autre)
    _git("branch", "equipe/x", cwd=autre)
    e = entree("git merge equipe/x", autre)
    assert decider(e, pret) is None
    assert fusions_autorisees(e, pret) == []        # hors dépôt principal : rien de journalisé, comme avant


def test_push_et_suppression_de_branche_toujours_refuses_option_active(pret):
    for cmd in ("git push", "git push origin main", "git branch -D equipe/x", "git rebase main",
                "git merge", "git reset --hard HEAD~1", "git update-ref refs/heads/main equipe/x"):
        assert refus_garde(pret, cmd) is not None, cmd


# --- erreurs : jamais un laissez-passer ------------------------------------------------------

def casser_git(monkeypatch, sous_commande, erreur):
    vrai = subprocess.run

    def faux(cmd, *a, **k):
        if sous_commande in cmd:
            raise erreur
        return vrai(cmd, *a, **k)

    monkeypatch.setattr(garde.subprocess, "run", faux)


@pytest.mark.parametrize("sous_commande,condition", [("merge-base", 2), ("diff", 2),
                                                      ("symbolic-ref", 3), ("merge-tree", 3)])
@pytest.mark.parametrize("erreur", [FileNotFoundError("git"), subprocess.TimeoutExpired("git", 5),
                                    OSError("boum")])
def test_git_qui_echoue_ou_depasse_le_delai_vaut_refus(pret, monkeypatch, sous_commande, condition, erreur):
    assert refus(pret) is None
    casser_git(monkeypatch, sous_commande, erreur)
    motif = refus(pret)
    assert f"condition {condition}" in motif and "lecture impossible" in motif
    assert fusions_autorisees(entree(MERGE, pret), pret) == []


@pytest.mark.parametrize("sous_commande,condition", [("merge-base", 2), ("diff", 2), ("merge-tree", 3)])
def test_git_qui_sort_en_erreur_vaut_refus(pret, monkeypatch, sous_commande, condition):
    vrai = subprocess.run

    def faux(cmd, *a, **k):
        r = vrai(cmd, *a, **k)
        if sous_commande in cmd:
            return subprocess.CompletedProcess(cmd, 128, "", "fatal")
        return r

    monkeypatch.setattr(garde.subprocess, "run", faux)
    assert f"condition {condition}" in refus(pret)


def test_git_introuvable_du_tout_vaut_refus(pret, monkeypatch):
    monkeypatch.setenv("PATH", str(pret / "rien"))
    assert refus(pret) is not None


def test_registre_absent_vaut_refus(pret):
    for f in (pret / ".orga" / "etat").glob("registre.sqlite*"):
        f.unlink()
    motif = refus(pret)
    assert motif is not None and "condition" not in motif       # option vue inactive : l'ancien refus seul


def test_registre_illisible_vaut_refus(pret):
    for f in (pret / ".orga" / "etat").glob("registre.sqlite*"):
        f.unlink()
    (pret / ".orga" / "etat" / "registre.sqlite").write_text("pas du sqlite" * 80)
    assert refus(pret) is not None


def test_table_reglages_absente_vaut_refus(pret):
    chemin = pret / ".orga" / "etat" / "registre.sqlite"
    for f in chemin.parent.glob("registre.sqlite*"):
        f.unlink()
    conn = sqlite3.connect(chemin)
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, nature TEXT, de TEXT, a TEXT, objet TEXT)")
    conn.execute("INSERT INTO messages (nature, de, a, objet) VALUES ('rapport_utilisateur', 'assistant', 'utilisateur', ?)",
                 (f"fusion-auto:x:{sha_de(pret, 'equipe/x')}",))
    conn.commit()
    conn.close()
    motif = refus(pret)
    assert motif is not None and "exige un accord" in motif and "condition" not in motif


def test_table_messages_absente_vaut_refus_condition_4(pret):
    conn = ouvrir(pret)
    with conn:
        conn.execute("ALTER TABLE messages RENAME TO messages_ancienne")
    conn.close()
    assert refus(pret) is not None


def test_manifeste_invalide_vaut_refus(pret):
    (pret / ".orga" / "projet.toml").write_text("[pas du toml")
    assert refus(pret) is not None


def test_liste_du_manifeste_mal_formee_vaut_refus_condition_2(pret):
    (pret / ".orga" / "projet.toml").write_text(MANIFESTE + '\n[fusions_auto]\nreserves = "src/"\n')
    motif = refus(pret)
    assert motif is not None
    assert "condition 2" in motif or "condition 5" in motif


def test_ref_qui_ne_se_resout_pas_vaut_refus(pret):
    assert refus(pret, "git merge equipe/fantome") is not None
