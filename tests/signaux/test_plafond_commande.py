"""`cime plafond` : l'utilisateur règle le plafond de la machine (fichier personnel + journal), tout
agent le lit."""
import json
import os
import tomllib
from pathlib import Path

import pytest

from aide import cime
from aide_charge import battement_vieux, fichier_charge, muet, tmux  # noqa: F401
from aide_machine import (  # noqa: F401
    dossier_machine, fixer_machine, lire_journal, poser_manifeste, poser_reglages, projet_libre)
from cime.fondation import fusions_auto, plafond
from cime.signaux import facteur, ordres


@pytest.fixture
def projet(projet_libre):
    return projet_libre


def plafond_cmd(monkeypatch, agent, *args, projet=None):
    return cime(monkeypatch, agent, "plafond", *args, projet=projet)


def reglages(dossier):
    return (dossier / "reglages.toml").read_text()


def arbre(racine):
    return sorted(str(p.relative_to(racine)) for p in Path(racine).rglob("*") if p.is_file())


# --- 5. écrire ---------------------------------------------------------------------------------

def test_utilisateur_ecrit_le_fichier_et_le_journal(projet, monkeypatch, capsys, dossier_machine):  # noqa: F811
    assert plafond_cmd(monkeypatch, "utilisateur", "2", projet=projet) == 0
    imprime = capsys.readouterr().out.strip()
    assert reglages(dossier_machine) == "workers_max = 2\n"
    journal = lire_journal(dossier_machine)
    assert len(journal) == 1
    assert journal[0] == {"horodatage": imprime, "cle": "workers_max", "avant": "defaut",
                          "apres": 2, "auteur": "utilisateur"}
    assert plafond.lire_machine() == (2, "fichier")


def test_la_ligne_de_journal_porte_l_ancienne_valeur(projet, monkeypatch, dossier_machine):  # noqa: F811
    plafond_cmd(monkeypatch, "utilisateur", "2", projet=projet)
    plafond_cmd(monkeypatch, "utilisateur", "4", projet=projet)
    plafond_cmd(monkeypatch, "utilisateur", "--defaut", projet=projet)
    assert [(l["avant"], l["apres"]) for l in lire_journal(dossier_machine)] == [
        ("defaut", 2), (2, 4), (4, "defaut")]


def test_avant_vaut_defaut_quand_la_valeur_du_fichier_est_mauvaise(projet, monkeypatch, dossier_machine):  # noqa: F811
    poser_reglages(dossier_machine, "workers_max = 9\n")
    assert plafond_cmd(monkeypatch, "utilisateur", "2", projet=projet) == 0
    assert lire_journal(dossier_machine)[0]["avant"] == "defaut"
    assert reglages(dossier_machine) == "workers_max = 2\n"


@pytest.mark.parametrize("agent", ["worker-x-a", "coord-x", "assistant", "integration", None])
@pytest.mark.parametrize("argument", ["2", "--defaut", "99", "abc"])
def test_un_agent_ne_peut_rien_ecrire(projet, monkeypatch, capsys, dossier_machine, agent, argument):  # noqa: F811
    assert plafond_cmd(monkeypatch, agent, argument, projet=projet) == 1
    sortie = capsys.readouterr()
    assert "CIME_AGENT" in sortie.err and sortie.out == ""
    assert not dossier_machine.exists()                 # rien écrit, pas même le dossier


def test_un_agent_ne_modifie_pas_un_fichier_existant(projet, monkeypatch, dossier_machine):  # noqa: F811
    fixer_machine(dossier_machine, 5)
    plafond_cmd(monkeypatch, "coord-x", "2", projet=projet)
    plafond_cmd(monkeypatch, "assistant", "--defaut", projet=projet)
    assert reglages(dossier_machine) == "workers_max = 5\n" and lire_journal(dossier_machine) == []


@pytest.mark.parametrize("mauvais", ["0", "9", "-1", "abc", "3.0", "", "01x", "٣"])
def test_hors_bornes_code_2(projet, monkeypatch, capsys, dossier_machine, mauvais):  # noqa: F811
    assert plafond_cmd(monkeypatch, "utilisateur", mauvais, projet=projet) == 2
    assert "plafond : un entier de 1 à 8" in capsys.readouterr().err
    assert not dossier_machine.exists()


def test_bornes_ecrites(projet, monkeypatch, dossier_machine):  # noqa: F811
    assert plafond_cmd(monkeypatch, "utilisateur", "1", projet=projet) == 0
    assert plafond.lire_machine() == (1, "fichier")
    assert plafond_cmd(monkeypatch, "utilisateur", "8", projet=projet) == 0
    assert plafond.lire_machine() == (8, "fichier")


def test_deja_n_code_1_rien_d_ecrit(projet, monkeypatch, capsys, dossier_machine):  # noqa: F811
    plafond_cmd(monkeypatch, "utilisateur", "2", projet=projet)
    capsys.readouterr()
    avant = (reglages(dossier_machine), lire_journal(dossier_machine))
    assert plafond_cmd(monkeypatch, "utilisateur", "2", projet=projet) == 1
    sortie = capsys.readouterr()
    assert sortie.err.strip() == "plafond : déjà 2" and sortie.out == ""
    assert (reglages(dossier_machine), lire_journal(dossier_machine)) == avant


def test_ecrire_le_defaut_de_3_quand_la_cle_manque_est_ecrit(projet, monkeypatch, dossier_machine):  # noqa: F811
    assert plafond_cmd(monkeypatch, "utilisateur", "3", projet=projet) == 0
    assert plafond.lire_machine() == (3, "fichier")


def test_defaut_retire_la_cle_puis_deja(projet, monkeypatch, capsys, dossier_machine):  # noqa: F811
    plafond_cmd(monkeypatch, "utilisateur", "2", projet=projet)
    capsys.readouterr()
    assert plafond_cmd(monkeypatch, "utilisateur", "--defaut", projet=projet) == 0
    assert capsys.readouterr().out.strip() == lire_journal(dossier_machine)[1]["horodatage"]
    assert plafond.lire_machine() == (3, "defaut")
    assert reglages(dossier_machine) == ""              # le fichier reste, vide
    assert plafond_cmd(monkeypatch, "utilisateur", "--defaut", projet=projet) == 1
    assert capsys.readouterr().err.strip() == "plafond : déjà au défaut"
    assert len(lire_journal(dossier_machine)) == 2


def test_defaut_sans_fichier_est_deja(projet, monkeypatch, capsys, dossier_machine):  # noqa: F811
    assert plafond_cmd(monkeypatch, "utilisateur", "--defaut", projet=projet) == 1
    assert "plafond : déjà au défaut" in capsys.readouterr().err
    assert not dossier_machine.exists()


def test_defaut_avec_une_valeur_mauvaise_retire_la_ligne(projet, monkeypatch, dossier_machine):  # noqa: F811
    poser_reglages(dossier_machine, "workers_max = 9\n")
    assert plafond_cmd(monkeypatch, "utilisateur", "--defaut", projet=projet) == 0
    assert reglages(dossier_machine) == ""


def test_valeur_et_defaut_ensemble_refuses(projet, monkeypatch, dossier_machine):  # noqa: F811
    with pytest.raises(SystemExit):
        plafond_cmd(monkeypatch, "utilisateur", "2", "--defaut", projet=projet)
    assert not dossier_machine.exists()


# --- les autres lignes du fichier sont conservées ----------------------------------------------

AUTRES = '# mes réglages\ntheme = "sombre"\n'


def test_la_ligne_est_remplacee_le_reste_intact(projet, monkeypatch, dossier_machine):  # noqa: F811
    poser_reglages(dossier_machine, AUTRES + "workers_max = 5\n\n[autre]\nworkers_max = 9\nz = 1\n")
    plafond_cmd(monkeypatch, "utilisateur", "2", projet=projet)
    assert reglages(dossier_machine) == \
        AUTRES + "workers_max = 2\n\n[autre]\nworkers_max = 9\nz = 1\n"


def test_defaut_retire_seulement_la_ligne(projet, monkeypatch, dossier_machine):  # noqa: F811
    poser_reglages(dossier_machine, AUTRES + "workers_max = 5\n[autre]\nz = 1\n")
    plafond_cmd(monkeypatch, "utilisateur", "--defaut", projet=projet)
    assert reglages(dossier_machine) == AUTRES + "[autre]\nz = 1\n"


def test_la_cle_est_ajoutee_a_la_racine_avant_les_tables(projet, monkeypatch, dossier_machine):  # noqa: F811
    poser_reglages(dossier_machine, AUTRES + "\n[autre]\nz = 1\n")
    plafond_cmd(monkeypatch, "utilisateur", "4", projet=projet)
    lu = tomllib.loads(reglages(dossier_machine))
    assert lu == {"theme": "sombre", "workers_max": 4, "autre": {"z": 1}}
    assert plafond.lire_machine() == (4, "fichier")


def test_la_cle_est_ajoutee_a_la_fin_sans_retour_a_la_ligne(projet, monkeypatch, dossier_machine):  # noqa: F811
    poser_reglages(dossier_machine, 'theme = "sombre"')
    plafond_cmd(monkeypatch, "utilisateur", "4", projet=projet)
    assert reglages(dossier_machine) == 'theme = "sombre"\nworkers_max = 4\n'


def test_fichier_toml_invalide_refuse_sans_rien_changer(projet, monkeypatch, capsys, dossier_machine):  # noqa: F811
    poser_reglages(dossier_machine, "ceci n'est pas [du toml\n")
    assert plafond_cmd(monkeypatch, "utilisateur", "2", projet=projet) == 1
    assert "illisible" in capsys.readouterr().err
    assert reglages(dossier_machine) == "ceci n'est pas [du toml\n"
    assert lire_journal(dossier_machine) == []


def test_fichier_illisible_refuse(projet, monkeypatch, capsys, dossier_machine):  # noqa: F811
    dossier_machine.mkdir(parents=True)
    (dossier_machine / "reglages.toml").mkdir()
    assert plafond_cmd(monkeypatch, "utilisateur", "2", projet=projet) == 1
    assert lire_journal(dossier_machine) == []


# --- le journal d'abord ------------------------------------------------------------------------

def test_le_journal_est_ecrit_avant_le_remplacement(projet, monkeypatch, dossier_machine):  # noqa: F811
    vus = []
    vrai = plafond.os.replace

    def remplacer(source, cible):
        vus.append(lire_journal(dossier_machine))
        return vrai(source, cible)

    monkeypatch.setattr(plafond.os, "replace", remplacer)
    assert plafond_cmd(monkeypatch, "utilisateur", "2", projet=projet) == 0
    assert len(vus) == 1 and len(vus[0]) == 1 and vus[0][0]["apres"] == 2


def test_journal_impossible_rien_n_est_change(projet, monkeypatch, capsys, dossier_machine):  # noqa: F811
    fixer_machine(dossier_machine, 5)
    (dossier_machine / "reglages.journal").mkdir()      # le journal ne peut pas s'écrire
    assert plafond_cmd(monkeypatch, "utilisateur", "2", projet=projet) == 1
    assert "journal" in capsys.readouterr().err
    assert reglages(dossier_machine) == "workers_max = 5\n"
    assert plafond.lire_machine() == (5, "fichier")


def test_dossier_impossible_a_creer_rien_n_est_change(projet, monkeypatch, capsys, tmp_path):  # noqa: F811
    config = tmp_path / "config-fichier"
    config.write_text("x")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    assert plafond_cmd(monkeypatch, "utilisateur", "2", projet=projet) == 1
    assert capsys.readouterr().err != ""
    assert config.read_text() == "x"


def test_le_remplacement_echoue_le_fichier_reste_et_aucun_temporaire(projet, monkeypatch, capsys, dossier_machine):  # noqa: F811
    fixer_machine(dossier_machine, 5)

    def remplacer(source, cible):
        assert json.loads(json.dumps(Path(source).read_text())) == "workers_max = 2\n"   # complet
        raise OSError("coupure")

    monkeypatch.setattr(plafond.os, "replace", remplacer)
    assert plafond_cmd(monkeypatch, "utilisateur", "2", projet=projet) == 1
    assert reglages(dossier_machine) == "workers_max = 5\n"
    assert arbre(dossier_machine) == ["reglages.journal", "reglages.toml"]
    assert "coupure" in capsys.readouterr().err


def test_l_ecriture_passe_par_un_fichier_voisin(projet, monkeypatch, dossier_machine):  # noqa: F811
    vus = []
    vrai = plafond.os.replace
    monkeypatch.setattr(plafond.os, "replace",
                        lambda a, b: (vus.append((Path(a), Path(b))), vrai(a, b)))
    plafond_cmd(monkeypatch, "utilisateur", "2", projet=projet)
    source, cible = vus[0]
    assert source.parent == cible.parent == dossier_machine and source != cible


# --- un réglage de la machine : pas de projet, pas de registre ---------------------------------

def test_l_ecriture_marche_hors_projet(monkeypatch, capsys, dossier_machine, tmp_path):  # noqa: F811
    monkeypatch.chdir(tmp_path)
    assert plafond_cmd(monkeypatch, "utilisateur", "2") == 0
    assert plafond.lire_machine() == (2, "fichier")


def test_l_ecriture_ne_cherche_pas_le_projet(monkeypatch, dossier_machine):  # noqa: F811
    def interdit(*a, **k):
        raise AssertionError("projet cherché")

    monkeypatch.setattr(plafond, "trouver_projet", interdit)
    assert plafond_cmd(monkeypatch, "utilisateur", "2") == 0


def test_l_ecriture_n_ouvre_pas_le_registre(projet, monkeypatch, dossier_machine):  # noqa: F811
    plafond_cmd(monkeypatch, "utilisateur", "2", projet=projet)
    assert not (projet / ".orga" / "etat").exists()


def test_seuls_deux_fichiers_sous_cime_sont_ecrits(projet, monkeypatch, dossier_machine):  # noqa: F811
    plafond_cmd(monkeypatch, "utilisateur", "2", projet=projet)
    plafond_cmd(monkeypatch, "utilisateur", "--defaut", projet=projet)
    assert arbre(os.environ["XDG_CONFIG_HOME"]) == ["cime/reglages.journal", "cime/reglages.toml"]
    assert arbre(os.environ["HOME"]) == []
    assert not any(p.endswith("registre.sqlite") for p in arbre(projet))


def test_sans_xdg_l_ecriture_va_sous_home_config(projet, monkeypatch):  # noqa: F811
    monkeypatch.delenv("XDG_CONFIG_HOME")
    plafond_cmd(monkeypatch, "utilisateur", "2", projet=projet)
    assert arbre(os.environ["HOME"]) == [".config/cime/reglages.journal", ".config/cime/reglages.toml"]


# --- 6. lire -----------------------------------------------------------------------------------

SESSIONS = {"essai-worker-x-a", "essai-worker-x-c", "ai-worker-y-b", "essai-coord-x"}


def test_affichage_complet(projet, monkeypatch, capsys, tmux, dossier_machine):  # noqa: F811
    tmux["sessions"] = SESSIONS
    fixer_machine(dossier_machine, 5)
    poser_manifeste(projet, 2)
    assert plafond_cmd(monkeypatch, "assistant", projet=projet) == 0
    assert capsys.readouterr().out.splitlines() == [
        "plafond en vigueur : 2",
        "machine : 5 (fichier)",
        "projet : 2",
        "workers actifs : 3",
        "  ai : 1",
        "  essai : 2 (ce projet)"]


def test_affichage_defaut_sans_limite_de_projet(projet, monkeypatch, capsys, tmux):  # noqa: F811
    tmux["sessions"] = set()
    assert plafond_cmd(monkeypatch, "worker-x-a", projet=projet) == 0
    assert capsys.readouterr().out.splitlines() == [
        "plafond en vigueur : 3",
        "machine : 3 (défaut)",
        "projet : sans limite",
        "workers actifs : 0"]


def test_affichage_dit_qui_a_modifie_et_quand(projet, monkeypatch, capsys, tmux, dossier_machine):  # noqa: F811
    tmux["sessions"] = set()
    plafond_cmd(monkeypatch, "utilisateur", "4", projet=projet)
    heure = lire_journal(dossier_machine)[0]["horodatage"]
    capsys.readouterr()
    plafond_cmd(monkeypatch, "coord-x", projet=projet)
    assert capsys.readouterr().out.splitlines()[1] == \
        f"machine : 4 (fichier, modifié par utilisateur le {heure})"


def test_le_journal_ne_parle_pas_d_un_fichier_modifie_a_la_main(projet, monkeypatch, capsys, tmux, dossier_machine):  # noqa: F811
    tmux["sessions"] = set()
    plafond_cmd(monkeypatch, "utilisateur", "4", projet=projet)
    fixer_machine(dossier_machine, 6)                   # édité à la main
    capsys.readouterr()
    plafond_cmd(monkeypatch, "assistant", "--json", projet=projet)
    machine = json.loads(capsys.readouterr().out)["machine"]
    assert machine == {"valeur": 6, "source": "fichier", "depuis": None, "par": None}


def test_le_journal_ne_parle_pas_du_defaut(projet, monkeypatch, capsys, tmux, dossier_machine):  # noqa: F811
    tmux["sessions"] = set()
    plafond_cmd(monkeypatch, "utilisateur", "4", projet=projet)
    plafond_cmd(monkeypatch, "utilisateur", "--defaut", projet=projet)
    capsys.readouterr()
    plafond_cmd(monkeypatch, "assistant", projet=projet)
    assert capsys.readouterr().out.splitlines()[1] == "machine : 3 (défaut)"


def test_un_journal_abime_ne_casse_pas_la_lecture(projet, monkeypatch, capsys, tmux, dossier_machine):  # noqa: F811
    tmux["sessions"] = set()
    fixer_machine(dossier_machine, 4)
    (dossier_machine / "reglages.journal").write_text("pas du json\n[1]\n\n")
    assert plafond_cmd(monkeypatch, "assistant", projet=projet) == 0
    assert capsys.readouterr().out.splitlines()[1] == "machine : 4 (fichier)"


def test_affichage_compte_inconnu(projet, monkeypatch, capsys, tmux):  # noqa: F811
    muet(tmux)
    assert plafond_cmd(monkeypatch, "coord-x", projet=projet) == 0
    assert capsys.readouterr().out.splitlines() == [
        "plafond en vigueur : 3", "machine : 3 (défaut)", "projet : sans limite",
        "workers actifs : ?"]


def test_affichage_hors_projet(monkeypatch, capsys, tmux, dossier_machine, tmp_path):  # noqa: F811
    monkeypatch.chdir(tmp_path)
    tmux["sessions"] = SESSIONS
    fixer_machine(dossier_machine, 5)
    assert plafond_cmd(monkeypatch, "assistant") == 0
    assert capsys.readouterr().out.splitlines() == [
        "plafond en vigueur : 5",
        "machine : 5 (fichier)",
        "projet : hors projet",
        "workers actifs : 3",
        "  ai : 1",
        "  essai : 2"]


def test_affichage_hors_projet_sans_tmux(monkeypatch, capsys, tmux, tmp_path):  # noqa: F811
    monkeypatch.chdir(tmp_path)
    muet(tmux)
    assert plafond_cmd(monkeypatch, "assistant") == 0
    assert capsys.readouterr().out.splitlines()[2:] == ["projet : hors projet", "workers actifs : ?"]


def test_affichage_manifeste_illisible_est_une_erreur(projet, monkeypatch, capsys, tmux):  # noqa: F811
    tmux["sessions"] = set()
    poser_manifeste(projet, 0)
    assert plafond_cmd(monkeypatch, "assistant", projet=projet) == 1
    assert "workers_max" in capsys.readouterr().err


def test_affichage_sans_agent_lit_aussi(projet, monkeypatch, capsys, tmux):  # noqa: F811
    tmux["sessions"] = set()
    assert plafond_cmd(monkeypatch, None, projet=projet) == 0
    assert capsys.readouterr().out.startswith("plafond en vigueur : 3\n")


def test_json(projet, monkeypatch, capsys, tmux, dossier_machine):  # noqa: F811
    tmux["sessions"] = SESSIONS
    plafond_cmd(monkeypatch, "utilisateur", "5", projet=projet)
    heure = lire_journal(dossier_machine)[0]["horodatage"]
    poser_manifeste(projet, 2)
    capsys.readouterr()
    assert plafond_cmd(monkeypatch, "assistant", "--json", projet=projet) == 0
    assert json.loads(capsys.readouterr().out) == {
        "valeur": 2, "source": "projet",
        "machine": {"valeur": 5, "source": "fichier", "depuis": heure, "par": "utilisateur"},
        "projet": 2, "workers_actifs": 3, "par_projet": {"ai": 1, "essai": 2}}


def test_json_machine_seule(projet, monkeypatch, capsys, tmux):  # noqa: F811
    tmux["sessions"] = set()
    plafond_cmd(monkeypatch, "assistant", "--json", projet=projet)
    assert json.loads(capsys.readouterr().out) == {
        "valeur": 3, "source": "machine",
        "machine": {"valeur": 3, "source": "defaut", "depuis": None, "par": None},
        "projet": None, "workers_actifs": 0, "par_projet": {}}


def test_json_compte_inconnu(projet, monkeypatch, capsys, tmux):  # noqa: F811
    muet(tmux)
    plafond_cmd(monkeypatch, "assistant", "--json", projet=projet)
    objet = json.loads(capsys.readouterr().out)
    assert objet["workers_actifs"] is None and objet["par_projet"] is None


def test_json_hors_projet(monkeypatch, capsys, tmux, tmp_path):  # noqa: F811
    monkeypatch.chdir(tmp_path)
    tmux["sessions"] = {"cc-worker-a-1"}
    plafond_cmd(monkeypatch, "assistant", "--json")
    objet = json.loads(capsys.readouterr().out)
    assert objet["projet"] is None and objet["source"] == "machine"
    assert objet["par_projet"] == {"cc": 1}


def test_un_agent_lit_le_miroir_du_facteur(projet, monkeypatch, capsys, tmux, dossier_machine):  # noqa: F811
    tmux["sessions"] = {"essai-worker-x-a", "ai-worker-y-b"}
    fixer_machine(dossier_machine, 2)
    ordres.inscrire_charge(projet)
    facteur.battre(projet)
    fixer_machine(dossier_machine, 7)                   # ce que l'agent ne peut pas lire
    muet(tmux)
    assert plafond_cmd(monkeypatch, "worker-x-a", projet=projet) == 0
    assert capsys.readouterr().out.splitlines() == [
        "plafond en vigueur : 2",
        "machine : 2 (fichier)",
        "projet : sans limite",
        "workers actifs : 2",
        "  ai : 1",
        "  essai : 1 (ce projet)"]


def test_un_agent_facteur_arrete_ne_voit_pas_le_detail(projet, monkeypatch, capsys, tmux, dossier_machine):  # noqa: F811
    tmux["sessions"] = {"essai-worker-x-a"}
    ordres.inscrire_charge(projet)
    battement_vieux(projet)
    muet(tmux)
    fixer_machine(dossier_machine, 4)
    plafond_cmd(monkeypatch, "worker-x-a", "--json", projet=projet)
    objet = json.loads(capsys.readouterr().out)
    assert objet["workers_actifs"] is None and objet["par_projet"] is None
    assert objet["machine"]["valeur"] == 4


def test_un_miroir_au_detail_mal_forme_est_ignore(projet, monkeypatch, capsys, tmux):  # noqa: F811
    facteur.battre(projet)
    fichier_charge(projet).parent.mkdir(parents=True, exist_ok=True)
    fichier_charge(projet).write_text(json.dumps(
        {"workers_actifs": 1, "plafond_machine": 2, "source_machine": "fichier",
         "par_projet": {"cc": "beaucoup"}}))
    muet(tmux)
    plafond_cmd(monkeypatch, "worker-x-a", "--json", projet=projet)
    objet = json.loads(capsys.readouterr().out)
    assert objet["workers_actifs"] == 1 and objet["par_projet"] is None


def test_l_aide_dit_ce_qu_il_faut_savoir(capsys):
    from cime import cli
    with pytest.raises(SystemExit):
        cli.main(["plafond", "--help"])
    aide = " ".join(capsys.readouterr().out.split())
    assert "ne tue aucun worker" in aide and "attendent" in aide
    assert "tous les projets" in aide and "plus bas" in aide
    assert "hors de tmux" in aide and "…-worker-…" in aide


# --- 8. les fusions automatiques n'en savent rien ----------------------------------------------

def test_changer_le_plafond_ne_suspend_pas_les_fusions(projet, monkeypatch, dossier_machine):  # noqa: F811
    assert cime(monkeypatch, "utilisateur", "fusions-auto", "active", projet=projet) == 0
    assert fusions_auto.etat_courant(projet)["active"]
    plafond_cmd(monkeypatch, "utilisateur", "4", projet=projet)
    etat = fusions_auto.etat_courant(projet)
    assert etat["active"] and not etat["suspendue"]
    plafond_cmd(monkeypatch, "utilisateur", "--defaut", projet=projet)
    poser_manifeste(projet, 6)
    etat = fusions_auto.etat_courant(projet)
    assert etat["active"] and not etat["suspendue"]


def test_la_cle_d_une_table_n_est_pas_celle_de_la_racine(projet, monkeypatch, dossier_machine):  # noqa: F811
    poser_reglages(dossier_machine, AUTRES + "[autre]\nworkers_max = 9\n")
    plafond_cmd(monkeypatch, "utilisateur", "2", projet=projet)
    assert tomllib.loads(reglages(dossier_machine)) == {
        "theme": "sombre", "workers_max": 2, "autre": {"workers_max": 9}}
    plafond_cmd(monkeypatch, "utilisateur", "--defaut", projet=projet)
    assert tomllib.loads(reglages(dossier_machine)) == {
        "theme": "sombre", "autre": {"workers_max": 9}}


def test_le_detail_est_en_ordre_alphabetique(projet, monkeypatch, capsys, tmux):  # noqa: F811
    tmux["sessions"] = {f"{p}-worker-x-t" for p in ("d", "b", "e", "a", "c", "f")}
    plafond_cmd(monkeypatch, "assistant", projet=projet)
    lignes = capsys.readouterr().out.splitlines()[4:]
    assert lignes == [f"  {p} : 1" for p in "abcdef"]
