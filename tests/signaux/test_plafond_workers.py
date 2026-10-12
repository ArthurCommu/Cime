"""Plafond de workers actifs sur la machine : les lancements en trop attendent leur tour."""
import pytest

from aide import cime, fabriquer_projet, lignes
from cime.signaux import ordres, reprise

WORKER = {"role": "worker", "equipe": "x", "modele": "m"}


@pytest.fixture
def projet(tmp_path, monkeypatch):
    racine = fabriquer_projet(tmp_path / "depot")
    monkeypatch.setenv("CIME_PROJET", str(racine))
    return racine


def regler(projet, workers_max):
    fichier = projet / ".orga" / "projet.toml"
    fichier.write_text(fichier.read_text() + f"\n[charge]\nworkers_max = {workers_max}\n")


@pytest.fixture
def machine(monkeypatch):
    """Sessions tmux vivantes de la machine (modifiable) ; chaque ordre exécuté est noté, et un
    lancement de worker crée sa session, comme le vrai lancement."""
    etat = {"vivantes": set(), "executes": []}
    monkeypatch.setattr(ordres, "_sessions_vivantes", lambda: set(etat["vivantes"]))

    def executer(projet, ordre):
        etat["executes"].append(ordre["id"])
        if ordre["verbe"] == "lancer" and ordre["parametres"].get("role") == "worker":
            etat["vivantes"].add(f"essai-{ordre['cible']}")
        return "execute", 0, ""

    monkeypatch.setattr(ordres, "executer", executer)
    return etat


def poser(projet, tache, auteur="coord-x", verbe="lancer", **parametres):
    cible = f"worker-x-{tache}"
    return ordres.demander(projet, auteur, verbe, cible,
                           {**WORKER, "tache": tache, **parametres} if verbe == "lancer"
                           else parametres)


def etats(projet):
    return [e for (e,) in lignes(projet, "SELECT etat FROM ordres ORDER BY id")]


# --- compter_workers -------------------------------------------------------------------------

def test_compter_workers_tous_prefixes_et_rien_d_autre():
    sessions = {"essai-worker-x-t", "autre-worker-y-u", "essai-worker-integration-r",
                "essai-assistant", "essai-coord-x", "essai-coord-worker", "bureau", "worker-x-t"}
    assert ordres.compter_workers(sessions) == 3


def test_compter_workers_vide():
    assert ordres.compter_workers(set()) == 0


# --- le plafond retient les lancements de worker ---------------------------------------------

def test_plafond_atteint_l_ordre_reste_en_file(projet, machine):
    machine["vivantes"] = {"autre-worker-y-z"}
    poser(projet, "a")
    assert ordres.facteur_une_fois(projet) == 1
    assert etats(projet) == ["en_file"]
    assert lignes(projet, "SELECT resultat, fini FROM ordres") == [(None, None)]
    assert machine["executes"] == []


def test_place_libre_l_ordre_part(projet, machine):
    poser(projet, "a")
    ordres.facteur_une_fois(projet)
    assert etats(projet) == ["execute"] and machine["executes"] == [1]


def test_plafond_atteint_par_le_facteur_continu(projet, machine):
    from cime.signaux import facteur
    machine["vivantes"] = {"autre-worker-y-z"}
    poser(projet, "a")
    assert facteur._etape_ordres(projet, None, type("M", (), {"demarre": True})()) == 0
    assert etats(projet) == ["en_file"]


# --- FIFO et recompte avant chaque ordre -----------------------------------------------------

def test_une_place_le_plus_ancien_part_puis_le_second_apres_liberation(projet, machine):
    poser(projet, "a")
    poser(projet, "b")
    ordres.facteur_une_fois(projet)
    assert etats(projet) == ["execute", "en_file"] and machine["executes"] == [1]
    ordres.facteur_une_fois(projet)
    assert etats(projet) == ["execute", "en_file"]      # toujours pleine : le second attend
    machine["vivantes"].clear()
    ordres.facteur_une_fois(projet)
    assert etats(projet) == ["execute", "execute"] and machine["executes"] == [1, 2]


def test_workers_max_2_deux_partent_le_troisieme_attend(projet, machine):
    regler(projet, 2)
    for tache in "abc":
        poser(projet, tache)
    ordres.facteur_une_fois(projet)
    assert etats(projet) == ["execute", "execute", "en_file"]


# --- ce que le plafond ne retient jamais -----------------------------------------------------

@pytest.mark.parametrize("verbe,cible,auteur,parametres", [
    ("fermer", "worker-x-a", "coord-x", {}),
    ("compacter", "worker-x-a", "coord-x", {}),
    ("capturer", "worker-x-a", "coord-x", {}),
    ("lancer", "coord-x", "assistant", {"role": "coord", "equipe": "x"}),
    ("lancer", "assistant", "utilisateur", {"role": "assistant"}),
    ("lancer", "worker-x-a", "utilisateur", {"role": "worker", "equipe": "x", "tache": "a"}),
])
def test_jamais_retenu_meme_plafond_atteint(projet, machine, verbe, cible, auteur, parametres):
    machine["vivantes"] = {"autre-worker-y-z"}
    ordres.demander(projet, auteur, verbe, cible, parametres)
    ordres.facteur_une_fois(projet)
    assert etats(projet) == ["execute"]


def test_un_ordre_retenu_ne_bloque_pas_le_fermer_qui_le_suit(projet, machine):
    machine["vivantes"] = {"autre-worker-y-z"}
    poser(projet, "a")
    ordres.demander(projet, "coord-x", "fermer", "worker-x-b", {})
    ordres.facteur_une_fois(projet)
    assert etats(projet) == ["en_file", "execute"]


def test_les_workers_de_l_utilisateur_comptent_pour_les_autres(projet, machine):
    ordres.demander(projet, "utilisateur", "lancer", "worker-x-a", {**WORKER, "tache": "a"})
    poser(projet, "b")
    ordres.facteur_une_fois(projet)
    assert etats(projet) == ["execute", "en_file"]


# --- le message de l'attente -----------------------------------------------------------------

def lancer_worker_en_attente(monkeypatch, projet):
    monkeypatch.setenv("CIME_ATTENTE_ORDRE", "0")
    return ordres.poser_et_attendre(projet, "coord-x", "lancer", "worker-x-a",
                                    {**WORKER, "tache": "a"})


def test_message_plafond_atteint(projet, machine, monkeypatch, capsys):
    machine["vivantes"] = {"autre-worker-y-z"}
    identifiant, resultat = lancer_worker_en_attente(monkeypatch, projet)
    assert ordres._issue(identifiant, resultat, projet) == ordres.CODE_EN_FILE
    sortie = capsys.readouterr().out
    assert "plafond 1" in sortie and "1 workers actifs" in sortie
    assert "une place se libère" in sortie and "facteur arrêté" not in sortie


def test_message_facteur_arrete_sans_plafond(projet, machine, monkeypatch, capsys):
    identifiant, resultat = lancer_worker_en_attente(monkeypatch, projet)
    assert ordres._issue(identifiant, resultat, projet) == ordres.CODE_EN_FILE
    assert capsys.readouterr().out.strip() == f"ordre #{identifiant} en file, facteur arrêté"


def test_message_facteur_arrete_pour_un_autre_verbe_meme_plafond_atteint(
        projet, machine, monkeypatch, capsys):
    machine["vivantes"] = {"autre-worker-y-z"}
    monkeypatch.setenv("CIME_ATTENTE_ORDRE", "0")
    identifiant, resultat = ordres.poser_et_attendre(projet, "coord-x", "fermer", "worker-x-a", {})
    ordres._issue(identifiant, resultat, projet)
    assert "facteur arrêté" in capsys.readouterr().out


def test_plafond_atteint_donne_atteint_actifs_plafond(projet, machine):
    regler(projet, 2)
    machine["vivantes"] = {"p-worker-a-b"}
    assert ordres.plafond_atteint(projet) == (False, 1, 2)
    machine["vivantes"] = {"p-worker-a-b", "q-worker-c-d"}
    assert ordres.plafond_atteint(projet) == (True, 2, 2)


# --- cime reprise ----------------------------------------------------------------------------

def test_reprise_sans_ordre_retenu_pas_de_section(projet, machine, monkeypatch):
    machine["vivantes"] = {"autre-worker-y-z"}
    ordres.demander(projet, "coord-x", "fermer", "worker-x-a", {})
    for moi in ("assistant", "coord-x"):
        assert "(g)" not in reprise.texte_reprise(projet, moi)


def test_reprise_place_libre_pas_de_section(projet, machine):
    poser(projet, "a")          # en file, mais le facteur le fera partir : rien n'est retenu
    assert "(g)" not in reprise.texte_reprise(projet, "assistant")


def test_reprise_avec_ordres_retenus_les_nomme(projet, machine):
    machine["vivantes"] = {"autre-worker-y-z"}
    poser(projet, "a")
    poser(projet, "b")
    for moi in ("assistant", "coord-x"):
        texte = reprise.texte_reprise(projet, moi)
        assert ("(g) File de lancements : 2 en attente (plafond 1, actifs 1) : "
                "worker-x-a, worker-x-b") in texte


def test_reprise_reste_sous_le_plafond_de_caracteres(projet, machine):
    machine["vivantes"] = {"autre-worker-y-z"}
    for n in range(60):
        poser(projet, f"tache-{n}")
    texte = reprise.texte_reprise(projet, "assistant")
    assert "(g)" in texte and len(texte) <= reprise.PLAFOND
    assert "(g) File de lancements : 60 en attente" in texte and "… et 48 de plus" in texte
    assert "worker-x-tache-11" in texte and "worker-x-tache-12" not in texte
