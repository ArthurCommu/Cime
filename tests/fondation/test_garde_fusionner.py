"""`cime fusionner` côté garde : refusé aux workers et aux coordinateurs sous toutes les formes
d'appel, permis à l'Assistant et à l'utilisateur ; et `garde.juger_fusion`, les règles d'accord
d'un `git merge` offertes à une commande qui fusionne elle-même."""
import pytest

from cime.fondation import garde
from cime.fondation.garde import decider, juger_fusion
from cime.fondation.nom import VAR_AGENT
from test_garde_fusion import depot, donner_accord, identite, sha_de  # noqa: F401
from test_garde_fusions_auto import activer, annoncer, manifeste

FORMES = [
    "cime fusionner fondation",
    "cime fusionner fondation --maintenant",
    '/chemin/cime fusionner fondation --message "x"',
    "python -m cime fusionner fondation",
    "uv run cime fusionner fondation",
    'bash -c "cime fusionner fondation"',
    "env cime fusionner fondation",
    "true && cime fusionner fondation",
]


def entree(commande, cwd):
    return {"tool_name": "Bash", "tool_input": {"command": commande}, "cwd": str(cwd)}


@pytest.mark.parametrize("commande", FORMES)
@pytest.mark.parametrize("nom", ["worker-fondation-t1", "coord-fondation"])
def test_fusionner_refuse_aux_workers_et_coordinateurs(tmp_path, monkeypatch, nom, commande):
    monkeypatch.setenv(VAR_AGENT, nom)
    motif = decider(entree(commande, tmp_path), None)
    assert motif is not None and "se demande à l'Assistant" in motif


@pytest.mark.parametrize("commande", FORMES)
@pytest.mark.parametrize("nom", ["assistant", "utilisateur", None])
def test_fusionner_permis_a_l_assistant_et_a_l_utilisateur(tmp_path, monkeypatch, nom, commande):
    if nom is None:
        monkeypatch.delenv(VAR_AGENT, raising=False)
    else:
        monkeypatch.setenv(VAR_AGENT, nom)
    assert decider(entree(commande, tmp_path), None) is None


# --- juger_fusion --------------------------------------------------------------------------

def test_sans_accord_ni_option_refuse_avec_la_cause(depot):
    voie, details, motif = juger_fusion(depot, "equipe/x")
    assert voie is None and details == {}
    assert "aucun accord de l'utilisateur non consommé" in motif


def test_accord_pour_la_pointe_donne_la_voie_accord_sans_le_consommer(depot):
    ident = donner_accord(depot)
    assert juger_fusion(depot, "equipe/x") == ("accord", {}, None)
    assert juger_fusion(depot, "equipe/x")[0] == "accord"   # rien n'a été consommé
    assert garde.accords_fusion_libres(depot) == [(ident, sha_de(depot, "equipe/x"))]


def test_accord_pour_un_autre_sha_refuse(depot):
    donner_accord(depot, sha="0" * 40)
    voie, _, motif = juger_fusion(depot, "equipe/x")
    assert voie is None and "aucun accord pour ce sha" in motif


def test_voie_auto_sans_annonce_prealable(depot):
    manifeste(depot, '\n[fusions_auto]\nreserves = ["src/cime/fondation/"]\n')
    activer(depot)
    voie, details, motif = juger_fusion(depot, "equipe/x")
    assert (voie, motif) == ("auto", None)
    assert details["equipe"] == "x" and details["sha"] == sha_de(depot, "equipe/x")
    assert details["annonce"] is None and details["reglage"] == 1


def test_la_garde_refuse_le_git_merge_meme_prete_pour_la_voie_auto(depot, monkeypatch):
    manifeste(depot, '\n[fusions_auto]\nreserves = ["src/cime/fondation/"]\n')
    activer(depot)
    annoncer(depot)
    identite(monkeypatch, "assistant")
    assert juger_fusion(depot, "equipe/x")[0] == "auto"    # la file l'accepte
    motif = decider({"tool_name": "Bash", "tool_input": {"command": "git merge equipe/x"},
                     "cwd": str(depot)}, depot)
    assert motif is not None and "cime fusionner" in motif   # la main, non


def test_chemin_reserve_sans_accord_refuse_meme_en_voie_auto(depot):
    from test_garde_fusions_auto import branche
    manifeste(depot, '\n[fusions_auto]\nreserves = ["src/cime/fondation/"]\n')
    branche(depot, "equipe/r", {"src/cime/fondation/a.py": "x"})
    activer(depot)
    voie, _, motif = juger_fusion(depot, "equipe/r")
    assert voie is None and "condition 2" in motif and "src/cime/fondation/a.py" in motif


def test_projet_illisible_refuse(tmp_path):
    voie, _, motif = juger_fusion(tmp_path / "rien", "equipe/x")
    assert voie is None and motif


def avancer(depot, ref="equipe/x"):
    """Un commit de plus sur `ref`, sans quitter main ; renvoie le nouveau sha."""
    import subprocess
    ancien = sha_de(depot, ref)
    arbre = subprocess.run(["git", "-C", str(depot), "rev-parse", f"{ancien}^{{tree}}"],
                           capture_output=True, text=True).stdout.strip()
    nouveau = subprocess.run(
        ["git", "-C", str(depot), "-c", "user.name=t", "-c", "user.email=t@t", "commit-tree", arbre,
         "-p", ancien, "-m", "plus tard"], capture_output=True, text=True).stdout.strip()
    subprocess.run(["git", "-C", str(depot), "update-ref", f"refs/heads/{ref}", nouveau], check=True)
    return nouveau


def test_sha_fige_est_juge_meme_si_la_branche_a_avance(depot):
    ancien = sha_de(depot, "equipe/x")
    donner_accord(depot)
    avancer(depot)
    assert juger_fusion(depot, "equipe/x")[0] is None            # la pointe d'aujourd'hui n'a pas d'accord
    assert juger_fusion(depot, "equipe/x", ancien) == ("accord", {}, None)


def test_sha_fige_en_voie_auto(depot):
    manifeste(depot, '\n[fusions_auto]\nreserves = ["src/cime/fondation/"]\n')
    activer(depot)
    ancien = sha_de(depot, "equipe/x")
    nouveau = avancer(depot)
    voie, details, motif = juger_fusion(depot, "equipe/x", ancien)
    assert (voie, motif) == ("auto", None) and details["sha"] == ancien != nouveau
