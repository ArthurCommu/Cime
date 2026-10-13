"""Depuis le bac à sable d'un agent, `_issue` lit le compte du facteur et ne l'accuse pas à tort."""
from cime.signaux import facteur, ordres
from aide_charge import (  # noqa: F401
    WORKER, battement_vieux, compte_inscrit, fichier_charge, muet, poser_worker, projet, tmux)


def sortie_de_issue(projet, capsys):
    identifiant = poser_worker(projet)
    code = ordres._issue(identifiant, None, projet)
    return identifiant, code, capsys.readouterr().out.strip()


# --- 2 à 5. _issue ---------------------------------------------------------------------------

def test_depuis_un_agent_le_compte_du_facteur_dit_le_plafond(projet, tmux, capsys):
    tmux["sessions"] = {"p-worker-y-z"}
    facteur._etape_charge(projet, None, None)
    facteur.battre(projet)
    muet(tmux)
    identifiant, code, sortie = sortie_de_issue(projet, capsys)
    assert code == ordres.CODE_EN_FILE
    assert f"ordre #{identifiant} en file : 1 workers actifs sur la machine (plafond 1)" in sortie
    assert "il partira quand une place se libère" in sortie
    assert "facteur arrêté" not in sortie


def test_compte_inconnu_facteur_qui_bat(projet, tmux, capsys):
    facteur.battre(projet)
    muet(tmux)
    identifiant, code, sortie = sortie_de_issue(projet, capsys)
    assert code == ordres.CODE_EN_FILE
    assert sortie == f"ordre #{identifiant} en file : le facteur est actif, il partira à son tour"


def test_compte_present_sous_le_plafond_facteur_qui_bat(projet, tmux, capsys):
    tmux["sessions"] = set()
    facteur._etape_charge(projet, None, None)
    facteur.battre(projet)
    muet(tmux)
    _, code, sortie = sortie_de_issue(projet, capsys)
    assert code == ordres.CODE_EN_FILE and "le facteur est actif, il partira à son tour" in sortie


def test_facteur_qui_ne_bat_pas_le_compte_perime_ne_sert_pas(projet, tmux, capsys):
    tmux["sessions"] = {"p-worker-y-z"}
    facteur._etape_charge(projet, None, None)
    battement_vieux(projet)
    muet(tmux)
    identifiant, code, sortie = sortie_de_issue(projet, capsys)
    assert code == ordres.CODE_EN_FILE
    assert sortie == f"ordre #{identifiant} en file, facteur arrêté"


def test_facteur_jamais_battu(projet, tmux, capsys):
    muet(tmux)
    identifiant, _, sortie = sortie_de_issue(projet, capsys)
    assert sortie == f"ordre #{identifiant} en file, facteur arrêté"


def test_tmux_visible_le_compte_vient_de_tmux(projet, tmux, capsys):
    tmux["sessions"] = {"p-worker-y-z"}     # aucun fichier, aucun battement : tmux suffit
    assert ordres.charge_machine(projet) == (1, 1, "tmux")
    _, _, sortie = sortie_de_issue(projet, capsys)
    assert "1 workers actifs sur la machine (plafond 1)" in sortie


def test_tmux_visible_a_la_place_du_fichier(projet, tmux):
    tmux["sessions"] = {"p-worker-y-z"}
    facteur._etape_charge(projet, None, None)
    facteur.battre(projet)
    tmux["sessions"] = set()                # le vrai compte prime sur le fichier
    assert ordres.charge_machine(projet) == (0, 1, "tmux")


def test_charge_machine_lit_le_fichier_quand_le_facteur_bat(projet, tmux):
    tmux["sessions"] = {"p-worker-y-z"}
    facteur._etape_charge(projet, None, None)
    facteur.battre(projet)
    muet(tmux)
    assert ordres.charge_machine(projet) == (1, 1, "facteur")


def test_charge_machine_inconnue(projet, tmux):
    muet(tmux)
    assert ordres.charge_machine(projet) == (None, 1, None)          # ni fichier ni battement
    facteur.battre(projet)
    assert ordres.charge_machine(projet) == (None, 1, None)          # il bat, fichier absent
    tmux["sessions"] = {"p-worker-y-z"}
    facteur._etape_charge(projet, None, None)
    muet(tmux)
    battement_vieux(projet)
    assert ordres.charge_machine(projet) == (None, 1, None)          # fichier présent, facteur arrêté


def test_fichier_illisible_compte_inconnu(projet, tmux):
    facteur.battre(projet)
    muet(tmux)
    fichier_charge(projet).write_text("{pas du json")
    assert ordres.charge_machine(projet) == (None, 1, None)
    fichier_charge(projet).write_text('{"workers_actifs": "beaucoup"}')
    assert ordres.charge_machine(projet) == (None, 1, None)


def test_le_chemin_du_compte_est_calcule_en_un_seul_endroit():
    import pathlib
    racine = pathlib.Path(ordres.__file__).parent.parent
    ecrits = [str(p.relative_to(racine)) for p in racine.rglob("*.py")
              if "charge.json" in p.read_text()]
    assert ecrits == ["signaux/ordres.py"]
