"""Le facteur inscrit dans `charge.json` ce qu'un agent ne voit pas (le plafond de la machine et le
détail par projet) ; un agent, tmux muet, le lit tant que le facteur bat."""
import json

import pytest

from aide_charge import battement_vieux, fichier_charge, muet, poser_worker, tmux  # noqa: F401
from aide_machine import (  # noqa: F401
    dossier_machine, fixer_machine, poser_manifeste, projet_libre)
from cime.signaux import facteur, ordres, reprise


@pytest.fixture
def projet(projet_libre):
    return projet_libre


def miroir(projet):
    return json.loads(fichier_charge(projet).read_text())


def inscrire(projet, tmux, sessions):
    tmux["sessions"] = sessions
    return ordres.inscrire_charge(projet)


def agent_voit(projet, tmux, contenu, frais=True):
    """Le facteur a inscrit `contenu` ; l'agent n'a ni tmux ni accès aux réglages de la machine."""
    fichier_charge(projet).parent.mkdir(parents=True, exist_ok=True)
    fichier_charge(projet).write_text(json.dumps(contenu))
    if frais:
        facteur.battre(projet)
    else:
        battement_vieux(projet)
    muet(tmux)


# --- le facteur inscrit ------------------------------------------------------------------------

def test_le_facteur_inscrit_plafond_et_detail(projet, tmux, dossier_machine):  # noqa: F811
    fixer_machine(dossier_machine, 5)
    assert inscrire(projet, tmux, {"cc-worker-a-1", "cc-worker-b-2", "ai-worker-c-3", "cc-coord-a"})
    assert miroir(projet) == {"workers_actifs": 3, "plafond_machine": 5, "source_machine": "fichier",
                              "par_projet": {"cc": 2, "ai": 1}}


def test_sans_fichier_le_miroir_porte_le_defaut(projet, tmux):  # noqa: F811
    inscrire(projet, tmux, set())
    assert miroir(projet) == {"workers_actifs": 0, "plafond_machine": 3, "source_machine": "defaut",
                              "par_projet": {}}


def test_le_plafond_du_projet_n_entre_pas_dans_le_miroir(projet, tmux, dossier_machine):  # noqa: F811
    fixer_machine(dossier_machine, 6)
    poser_manifeste(projet, 2)
    inscrire(projet, tmux, set())
    assert miroir(projet)["plafond_machine"] == 6


@pytest.mark.parametrize("changement", [
    "le compte",
    "le plafond de la machine",
    "le fichier devient defaut",
    "le detail a total egal",
])
def test_reecrit_quand_l_une_des_valeurs_change(projet, tmux, dossier_machine, changement):  # noqa: F811
    fixer_machine(dossier_machine, 4)
    inscrire(projet, tmux, {"cc-worker-a-1"})
    avant = miroir(projet)
    sessions = {"cc-worker-a-1"}
    if changement == "le compte":
        sessions = {"cc-worker-a-1", "cc-worker-a-2"}
    elif changement == "le plafond de la machine":
        fixer_machine(dossier_machine, 6)
    elif changement == "le fichier devient defaut":
        (dossier_machine / "reglages.toml").unlink()
    else:
        sessions = {"ai-worker-a-1"}                       # même total, autre projet
    assert inscrire(projet, tmux, sessions) is True
    assert miroir(projet) != avant


def test_ne_reecrit_pas_quand_rien_ne_change(projet, tmux, dossier_machine, monkeypatch):  # noqa: F811
    fixer_machine(dossier_machine, 4)
    inscrire(projet, tmux, {"cc-worker-a-1", "ai-worker-b-2"})
    ecritures = []
    vrai = ordres.os.replace
    monkeypatch.setattr(ordres.os, "replace", lambda a, b: (ecritures.append(b), vrai(a, b)))
    assert inscrire(projet, tmux, {"ai-worker-b-2", "cc-worker-a-1"}) is False
    assert ecritures == []


def test_ecriture_atomique_du_miroir_complet(projet, tmux, dossier_machine, monkeypatch):  # noqa: F811
    fixer_machine(dossier_machine, 4)
    inscrire(projet, tmux, {"cc-worker-a-1"})
    ancien = miroir(projet)
    vus = []

    def remplacer(source, cible):
        vus.append((str(source), str(cible), json.loads(open(source).read())))
        raise OSError("coupure")

    monkeypatch.setattr(ordres.os, "replace", remplacer)
    fixer_machine(dossier_machine, 7)
    with pytest.raises(OSError):
        inscrire(projet, tmux, {"cc-worker-a-1"})
    source, cible, contenu = vus[0]
    assert source != cible
    assert contenu == {**ancien, "plafond_machine": 7}     # complet dans le fichier voisin
    assert miroir(projet) == ancien                        # l'ancien reste lisible


def test_tmux_muet_le_facteur_n_inscrit_rien(projet, tmux, dossier_machine):  # noqa: F811
    inscrire(projet, tmux, {"cc-worker-a-1"})
    avant = miroir(projet)
    fixer_machine(dossier_machine, 7)
    assert inscrire(projet, tmux, None) is False
    assert miroir(projet) == avant


# --- l'agent lit le miroir ---------------------------------------------------------------------

CONTENU = {"workers_actifs": 2, "plafond_machine": 2, "source_machine": "fichier",
           "par_projet": {"cc": 2}}


def test_un_agent_lit_le_plafond_inscrit_quand_le_facteur_bat(projet, tmux, dossier_machine):  # noqa: F811
    fixer_machine(dossier_machine, 6)                      # ce que l'agent ne peut pas lire
    agent_voit(projet, tmux, CONTENU)
    assert ordres.plafond_machine(projet, None) == (2, "fichier")
    assert ordres.charge_machine(projet) == (2, 2, "facteur")
    assert ordres.plafond_en_vigueur(projet) == (2, "machine")


def test_un_agent_lit_aussi_la_source_inscrite(projet, tmux, dossier_machine):  # noqa: F811
    fixer_machine(dossier_machine, 6)
    agent_voit(projet, tmux, {**CONTENU, "source_machine": "defaut", "plafond_machine": 3})
    assert ordres.plafond_machine(projet, None) == (3, "defaut")


def test_battement_perime_le_miroir_ne_sert_pas(projet, tmux, dossier_machine):  # noqa: F811
    fixer_machine(dossier_machine, 6)
    agent_voit(projet, tmux, CONTENU, frais=False)
    assert ordres.plafond_machine(projet, None) == (6, "fichier")      # lecture directe
    assert ordres.charge_machine(projet) == (None, 6, None)


def test_battement_perime_et_fichier_illisible_le_defaut(projet, tmux):  # noqa: F811
    agent_voit(projet, tmux, CONTENU, frais=False)
    assert ordres.plafond_machine(projet, None) == (3, "defaut")


def test_miroir_sans_plafond_machine_lecture_directe(projet, tmux, dossier_machine):  # noqa: F811
    fixer_machine(dossier_machine, 5)
    agent_voit(projet, tmux, {"workers_actifs": 1})                    # un ancien charge.json
    assert ordres.plafond_machine(projet, None) == (5, "fichier")
    assert ordres.charge_machine(projet) == (1, 5, "facteur")          # le compte, lui, sert


def test_miroir_sans_plafond_machine_ni_fichier_le_defaut(projet, tmux):  # noqa: F811
    agent_voit(projet, tmux, {"workers_actifs": 1})
    assert ordres.plafond_machine(projet, None) == (3, "defaut")


@pytest.mark.parametrize("mauvais", [
    {"plafond_machine": "2", "source_machine": "fichier"},
    {"plafond_machine": 0, "source_machine": "fichier"},
    {"plafond_machine": 9, "source_machine": "fichier"},
    {"plafond_machine": True, "source_machine": "fichier"},
    {"plafond_machine": 2.5, "source_machine": "fichier"},
    {"plafond_machine": None, "source_machine": "fichier"},
    {"plafond_machine": 2, "source_machine": "ailleurs"},
    {"plafond_machine": 2},
])
def test_miroir_mal_forme_inutilisable(projet, tmux, dossier_machine, mauvais):  # noqa: F811
    fixer_machine(dossier_machine, 6)
    agent_voit(projet, tmux, {"workers_actifs": 1, **mauvais})
    assert ordres.plafond_machine(projet, None) == (6, "fichier")


def test_miroir_illisible_lecture_directe(projet, tmux, dossier_machine):  # noqa: F811
    fixer_machine(dossier_machine, 6)
    facteur.battre(projet)
    muet(tmux)
    fichier_charge(projet).write_text("{pas du json")
    assert ordres.plafond_machine(projet, None) == (6, "fichier")
    fichier_charge(projet).write_text("[1, 2]")
    assert ordres.plafond_machine(projet, None) == (6, "fichier")


def test_qui_voit_tmux_lit_le_fichier_pas_le_miroir(projet, tmux, dossier_machine):  # noqa: F811
    agent_voit(projet, tmux, CONTENU)
    fixer_machine(dossier_machine, 6)
    tmux["sessions"] = set()                                # tmux répond
    assert ordres.plafond_machine(projet, set()) == (6, "fichier")
    assert ordres.plafond_en_vigueur(projet) == (6, "machine")


def test_l_agent_combine_le_miroir_et_le_projet(projet, tmux):  # noqa: F811
    agent_voit(projet, tmux, {**CONTENU, "plafond_machine": 5})
    poser_manifeste(projet, 3)
    assert ordres.plafond_en_vigueur(projet) == (3, "projet")


# --- _issue et reprise depuis un agent ---------------------------------------------------------

def test_issue_depuis_un_agent_dit_le_plafond_inscrit(projet, tmux, dossier_machine, capsys):  # noqa: F811
    fixer_machine(dossier_machine, 6)
    agent_voit(projet, tmux, CONTENU)
    identifiant = poser_worker(projet)
    assert ordres._issue(identifiant, None, projet) == ordres.CODE_EN_FILE
    assert (f"ordre #{identifiant} en file : 2 workers actifs sur la machine (plafond 2)"
            in capsys.readouterr().out)


def test_issue_sous_le_plafond_inscrit_le_facteur_est_actif(projet, tmux, dossier_machine, capsys):  # noqa: F811
    fixer_machine(dossier_machine, 1)
    agent_voit(projet, tmux, {**CONTENU, "workers_actifs": 2, "plafond_machine": 5})
    identifiant = poser_worker(projet)
    ordres._issue(identifiant, None, projet)
    assert "le facteur est actif, il partira à son tour" in capsys.readouterr().out


def test_reprise_depuis_un_agent_dit_le_plafond_inscrit(projet, tmux, dossier_machine):  # noqa: F811
    fixer_machine(dossier_machine, 6)
    agent_voit(projet, tmux, CONTENU)
    poser_worker(projet)
    assert ("(g) File de lancements : 1 en attente (plafond 2, actifs 2) : worker-x-a"
            in reprise.texte_reprise(projet, "coord-x"))
