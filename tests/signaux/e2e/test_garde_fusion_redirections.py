"""La garde de fusion ne prend plus une redirection (`2>&1`) ni un séparateur (`|`, `&&`)
pour une seconde branche. Chemin réel : hook PreToolUse de l'Assistant, accord lié au sha."""
import pytest

from e2e.aides import ASSISTANT, etat
from e2e.conftest import _git
from e2e.test_commandes_garde_git import accord_de_fusion, pre

M = 'git merge --no-ff equipe/alpha -m "m"'
PERMISES = [
    M,
    M + " 2>&1",
    M + " 2>&1 | tail -4",
    "git merge --no-ff equipe/alpha -m m > /dev/null 2>&1",
    M + " && echo ok",
    M + " ; echo ok",
    M + " || echo ko",
    M + " &> /dev/null",
    M + " 2>>/tmp/x.log",
    'git merge --no-ff equipe/alpha -m "titre\n\ncorps sur\nplusieurs lignes"',
    'git merge --no-ff equipe/alpha -m "titre\n\ncorps" 2>&1 | tail -4',
]


def _pre_depot(banc, depot, commande):
    refuse, r = pre(banc, ASSISTANT, commande, cwd=depot)
    return refuse, r


@pytest.mark.parametrize("commande", PERMISES)
def test_permise_avec_accord(banc_depot, depot, commande):
    accord_de_fusion(banc_depot, depot)
    refuse, r = _pre_depot(banc_depot, depot, commande)
    assert not refuse, r.stdout


def test_git_C_permis_avec_accord(banc_depot, depot):
    accord_de_fusion(banc_depot, depot)
    refuse, r = _pre_depot(banc_depot, depot, f"git -C {depot} merge --no-ff equipe/alpha -m m 2>&1 | tail -4")
    assert not refuse, r.stdout


@pytest.mark.parametrize("commande", PERMISES + [f"git -C DEPOT merge equipe/alpha -m m 2>&1"])
def test_refusee_sans_accord(banc_depot, depot, commande):
    refuse, r = _pre_depot(banc_depot, depot, commande.replace("DEPOT", str(depot)))
    assert refuse and "accord" in r.stdout


def test_un_refus_ne_consomme_pas_l_accord(banc_depot, depot):
    accord = accord_de_fusion(banc_depot, depot)
    _git("branch", "equipe/beta", "main", cwd=depot)
    refuse, _ = _pre_depot(banc_depot, depot, "git merge equipe/alpha extra 2>&1")
    assert refuse
    refuse, _ = _pre_depot(banc_depot, depot, "git merge equipe/beta -m m 2>&1 | tail -4")
    assert refuse
    assert etat(banc_depot, accord) != "clos"


def test_autre_branche_refusee_meme_avec_redirection(banc_depot, depot):
    accord_de_fusion(banc_depot, depot)                                   # accord pour alpha
    _git("branch", "equipe/beta", "main", cwd=depot)
    for commande in ("git merge equipe/beta 2>&1", "git merge equipe/beta -m m 2>&1 | tail -4",
                     "git merge equipe/beta > /dev/null 2>&1 && echo ok"):
        refuse, r = _pre_depot(banc_depot, depot, commande)
        assert refuse, commande


def test_octopus_toujours_refusee(banc_depot, depot):
    accord_de_fusion(banc_depot, depot)
    _git("branch", "equipe/beta", "main", cwd=depot)
    for commande in ("git merge equipe/alpha equipe/beta", "git merge equipe/alpha equipe/beta 2>&1",
                     "git merge equipe/alpha equipe/beta 2>&1 | tail -4"):
        refuse, _ = _pre_depot(banc_depot, depot, commande)
        assert refuse, commande


def test_branche_nommee_comme_un_descripteur_n_est_pas_masquee(banc_depot, depot):
    """`git merge 2 >f` : « 2 » est ici une branche (séparée de `>`), donc jugée comme telle."""
    accord_de_fusion(banc_depot, depot)
    refuse, _ = _pre_depot(banc_depot, depot, "git merge equipe/alpha 2 > /dev/null")
    assert refuse


def test_seconde_commande_dangereuse_apres_separateur_reste_refusee(banc_depot, depot):
    accord_de_fusion(banc_depot, depot)
    for commande in (M + " 2>&1 && git reset --hard HEAD~1",
                     M + " | tail -4 ; git merge main",
                     M + " && git merge equipe/zeta 2>&1"):
        refuse, _ = _pre_depot(banc_depot, depot, commande)
        assert refuse, commande
