"""Le champ `fusions_auto` de l'instantané : toujours présent, inactif par défaut,
actif avec la liste enregistrée après `cime fusions-auto active`, `derniere_fusion` tirée du journal.
Registre jetable ; `CIME_PROJET` et `CIME_AGENT` posés dans le test, jamais sur le vrai projet."""
import json
import sqlite3
from datetime import timedelta

import pytest

from cime import cli
from cime.fondation.nom import VAR_AGENT, VAR_PROJET
from cime.fondation.registre import ouvrir
from cime.observation import instantane as module
from cime.observation.instantane import instantane
from test_instantane import CLES, Faux, _orga
from test_registre import MAINTENANT

INACTIF = {"active": False, "suspendue": False, "depuis": None, "par": None, "reserves": [],
           "derniere_fusion": None, "portee": None, "chantiers_24h": 0, "chantiers_max": 5,
           "decisions": []}


@pytest.fixture
def faux(monkeypatch):
    return Faux(monkeypatch)


@pytest.fixture
def racine(tmp_path, monkeypatch):
    _orga(tmp_path)
    monkeypatch.setenv(VAR_PROJET, str(tmp_path))
    monkeypatch.setenv(VAR_AGENT, "utilisateur")
    conn = ouvrir(tmp_path)          # le vrai schéma du registre, table reglages_projet comprise
    conn.close()
    return tmp_path


def champ(racine):
    return instantane(racine, MAINTENANT + timedelta(minutes=0))["fusions_auto"]


def attendu_inactif(racine):
    """Le champ quand l'option n'est pas active : `reserves_proposees` = noyau + manifeste de `racine`."""
    from cime.fondation import fusions_auto
    return dict(INACTIF, reserves_proposees=fusions_auto.chemins_reserves(racine))


def test_present_et_inactif_par_defaut(racine, faux):
    assert champ(racine) == attendu_inactif(racine)


def test_present_sans_registre(tmp_path, faux):
    _orga(tmp_path)
    d = instantane(tmp_path, MAINTENANT)
    assert d["fusions_auto"] == attendu_inactif(tmp_path)


def test_present_quand_le_registre_est_illisible(tmp_path, faux):
    _orga(tmp_path)
    (tmp_path / ".orga" / "etat").mkdir()
    (tmp_path / ".orga" / "etat" / "registre.sqlite").write_text("rien de sqlite" * 40)
    assert instantane(tmp_path, MAINTENANT)["fusions_auto"] == attendu_inactif(tmp_path)


def test_present_quand_la_table_manque(tmp_path, faux):
    _orga(tmp_path)
    (tmp_path / ".orga" / "etat").mkdir()
    conn = sqlite3.connect(tmp_path / ".orga" / "etat" / "registre.sqlite")
    conn.execute("CREATE TABLE journal (id INTEGER PRIMARY KEY, horodatage TEXT, auteur TEXT, action TEXT,"
                 " cible TEXT, details TEXT, resultat TEXT)")
    conn.commit()
    conn.close()
    assert champ(tmp_path) == attendu_inactif(tmp_path)


def test_reserves_proposees_jamais_activee_noyau_et_manifeste(racine, faux):
    c = champ(racine)
    assert c["active"] is False and c["reserves"] == []
    assert ".orga/socle/" in c["reserves_proposees"] and "CLAUDE.md" in c["reserves_proposees"]
    assert ".orga/contracts/" not in c["reserves_proposees"]
    assert c["reserves_proposees"] == attendu_inactif(racine)["reserves_proposees"]


def test_reserves_proposees_reprend_le_manifeste(racine, faux):
    manifeste = racine / ".orga" / "projet.toml"
    manifeste.write_text(manifeste.read_text() + '\n[fusions_auto]\nreserves = ["x/"]\n')
    c = champ(racine)
    assert c["active"] is False and "x/" in c["reserves_proposees"]


def test_manifeste_illisible_donne_reserves_proposees_vide(racine, faux):
    (racine / ".orga" / "projet.toml").write_text("ceci n'est pas du [ toml")
    d = instantane(racine, MAINTENANT)            # l'instantané entier tient
    assert d["fusions_auto"]["reserves_proposees"] == []
    assert d["fusions_auto"]["active"] is False


def test_registre_absent_garde_la_cle(tmp_path, faux):
    _orga(tmp_path)
    c = instantane(tmp_path, MAINTENANT)["fusions_auto"]
    assert isinstance(c["reserves_proposees"], list) and c["reserves_proposees"]


def test_apres_activation_active_avec_la_liste(racine, faux, capsys):
    assert cli.main(["fusions-auto", "active"]) == 0
    c = champ(racine)
    assert c["active"] is True and c["suspendue"] is False and c["par"] == "utilisateur"
    assert c["depuis"].endswith("Z") and c["derniere_fusion"] is None
    from cime.fondation import fusions_auto
    assert c["reserves"] == fusions_auto.chemins_reserves(racine)
    assert c["reserves_proposees"] == c["reserves"]          # non suspendue : même liste
    assert ".orga/socle/" in c["reserves"]
    assert c["portee"] == 2 and c["chantiers_max"] == 5 and c["chantiers_24h"] == 0
    assert c["decisions"] == []
    assert json.dumps(c)


def test_apres_desactivation_inactive(racine, faux):
    cli.main(["fusions-auto", "active"])
    cli.main(["fusions-auto", "inactive"])
    c = champ(racine)
    assert c["active"] is False and c["suspendue"] is False and c["reserves"] == []
    assert c["reserves_proposees"] == attendu_inactif(racine)["reserves_proposees"]


def test_suspendue_quand_le_manifeste_change_apres_l_activation(racine, faux):
    cli.main(["fusions-auto", "active"])
    avant = champ(racine)["reserves"]
    manifeste = racine / ".orga" / "projet.toml"
    manifeste.write_text(manifeste.read_text() + '\n[fusions_auto]\nreserves = ["src/neuf/"]\n')
    c = champ(racine)
    assert c["active"] is True and c["suspendue"] is True
    assert c["reserves"] == avant                      # la liste enregistrée, pas la recalculée
    assert c["reserves_proposees"] != c["reserves"]    # la liste qu'une réactivation enregistrerait
    assert "src/neuf/" in c["reserves_proposees"]


def test_suspendue_manifeste_illisible_reserves_proposees_vide(racine, faux):
    cli.main(["fusions-auto", "active"])
    (racine / ".orga" / "projet.toml").write_text("ceci n'est pas du [ toml")
    c = champ(racine)
    assert c["active"] is True and c["suspendue"] is True
    assert c["reserves_proposees"] == []


def test_active_mais_calcul_impossible_vaut_suspendue(racine, faux, monkeypatch):
    cli.main(["fusions-auto", "active"])
    import cime.fondation.fusions_auto as fa
    monkeypatch.setattr(fa, "etat_courant", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    c = champ(racine)
    assert c["active"] is True and c["suspendue"] is True


def test_derniere_fusion_tiree_de_la_derniere_ligne_fusion_auto(racine, faux):
    sha1, sha2 = "a" * 40, "b" * 40
    conn = ouvrir(racine)
    with conn:
        for h, cible, action in (("2026-10-11T10:00:00.000Z", f"fusion:page:{sha1}", "fusion_auto"),
                                 ("2026-10-11T11:00:00.000Z", f"fusion:scene:{sha2}", "fusion_auto"),
                                 ("2026-10-11T12:00:00.000Z", f"fusion:hote:{'c' * 40}", "autre_action")):
            conn.execute("INSERT INTO journal (horodatage, auteur, action, cible, details, resultat)"
                         " VALUES (?, 'assistant', ?, ?, '{}', 'ok')", (h, action, cible))
    conn.close()
    assert champ(racine)["derniere_fusion"] == {
        "equipe": "scene", "sha": sha2, "horodatage": "2026-10-11T11:00:00.000Z"}


def test_cible_mal_formee_ne_casse_rien(racine, faux):
    conn = ouvrir(racine)
    with conn:
        conn.execute("INSERT INTO journal (horodatage, auteur, action, cible, details, resultat)"
                     " VALUES ('h', 'assistant', 'fusion_auto', 'n importe quoi', '{}', 'ok')")
    conn.close()
    assert champ(racine)["derniere_fusion"] is None


def test_la_forme_de_la_racine_gagne_la_cle_et_aucune_autre(racine, faux):
    """Le test de forme de test_instantane.py ne tourne pas sous le bac à sable (il lit ~/.claude) :
    on le rejoue ici sur un registre sans transcripts."""
    d = instantane(racine, MAINTENANT)
    assert set(d) == CLES["racine"]
    assert set(d["fusions_auto"]) == {"active", "suspendue", "depuis", "par", "reserves",
                                      "reserves_proposees", "derniere_fusion", "portee",
                                      "chantiers_24h", "chantiers_max", "decisions"}


# --- portée, chantiers, décisions annoncées -----------------------------------------

def _annonce(racine, objet, horodatage, *, de="assistant", a="utilisateur", nature="rapport_utilisateur",
             clos_par=None, clos_a=None):
    conn = ouvrir(racine)
    with conn:
        ident = conn.execute(
            "INSERT INTO messages (horodatage, de, a, nature, resume, objet) VALUES (?, ?, ?, ?, 'r', ?)",
            (horodatage, de, a, nature, objet)).lastrowid
        if clos_par:
            conn.execute("INSERT INTO transitions (horodatage, message_id, etat, auteur, preuve)"
                         " VALUES (?, ?, 'clos', ?, '{}')", (clos_a or horodatage, ident, clos_par))
    conn.close()
    return ident


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _activer_a(racine, horodatage):
    """Active, puis date la ligne du réglage de `horodatage` (pour fixer `depuis`)."""
    assert cli.main(["fusions-auto", "active"]) == 0
    conn = ouvrir(racine)
    with conn:
        conn.execute("UPDATE reglages_projet SET horodatage = ?", (horodatage,))
    conn.close()


AVANT = _iso(MAINTENANT - timedelta(hours=10))
ACTIVATION = _iso(MAINTENANT - timedelta(hours=5))
APRES = [_iso(MAINTENANT - timedelta(hours=h)) for h in (4, 3, 2, 1)]


def test_portee_et_plafond_apres_activation(racine, faux):
    cli.main(["fusions-auto", "active"])
    c = champ(racine)
    assert c["portee"] == 2 and c["chantiers_max"] == 5 and c["suspendue"] is False


def test_chantiers_max_suit_le_manifeste(racine, faux):
    manifeste = racine / ".orga" / "projet.toml"
    manifeste.write_text(manifeste.read_text() + '\n[fusions_auto]\nchantiers_par_jour = 0\n')
    assert champ(racine)["chantiers_max"] == 0
    manifeste.write_text(manifeste.read_text().replace("chantiers_par_jour = 0", "chantiers_par_jour = 7"))
    assert champ(racine)["chantiers_max"] == 7


def test_chantiers_max_vaut_5_quand_le_manifeste_est_illisible_ou_le_plafond_invalide(racine, faux):
    manifeste = racine / ".orga" / "projet.toml"
    original = manifeste.read_text()
    manifeste.write_text(original + '\n[fusions_auto]\nchantiers_par_jour = "x"\n')
    assert champ(racine)["chantiers_max"] == 5
    manifeste.write_text("ceci n'est pas du [ toml")
    assert champ(racine)["chantiers_max"] == 5


def test_chantiers_24h_compte_les_annonces_consommees_dans_la_fenetre(racine, faux):
    _annonce(racine, "chantier-auto:a:1", AVANT, clos_par="cime", clos_a=_iso(MAINTENANT - timedelta(hours=2)))
    _annonce(racine, "chantier-auto:b:1", AVANT, clos_par="cime", clos_a=_iso(MAINTENANT - timedelta(hours=30)))
    _annonce(racine, "chantier-auto:c:1", AVANT)                                   # non consommée
    assert champ(racine)["chantiers_24h"] == 1


def test_chantiers_24h_est_relatif_au_maintenant_de_l_instantane(racine, faux):
    _annonce(racine, "chantier-auto:a:1", AVANT, clos_par="cime", clos_a=_iso(MAINTENANT - timedelta(hours=2)))
    assert instantane(racine, MAINTENANT)["fusions_auto"]["chantiers_24h"] == 1
    assert instantane(racine, MAINTENANT + timedelta(hours=23))["fusions_auto"]["chantiers_24h"] == 0


def test_decisions_apres_activation_du_plus_recent_au_plus_ancien(racine, faux):
    _activer_a(racine, ACTIVATION)
    sha = "a" * 40
    ids = [_annonce(racine, objet, h) for objet, h in zip(
        (f"fusion-auto:page:{sha}", "chantier-auto:scene:2", "contrat-auto:registre",
         "autorisation-auto:17"), APRES)]
    d = champ(racine)["decisions"]
    assert d == [
        {"genre": "autorisation", "cle": "17", "horodatage": APRES[3], "message": ids[3]},
        {"genre": "contrat", "cle": "registre", "horodatage": APRES[2], "message": ids[2]},
        {"genre": "chantier", "cle": "scene:2", "horodatage": APRES[1], "message": ids[1]},
        {"genre": "fusion", "cle": f"page:{sha}", "horodatage": APRES[0], "message": ids[0]},
    ]


def test_decisions_exclut_ce_qui_precede_l_activation_courante(racine, faux):
    """Le filtre « après l'activation » : une annonce d'avant (ou du même instant) n'y est pas."""
    _activer_a(racine, ACTIVATION)
    _annonce(racine, "chantier-auto:vieux:1", AVANT)
    _annonce(racine, "chantier-auto:pile:1", ACTIVATION)
    nouveau = _annonce(racine, "chantier-auto:neuf:1", APRES[0])
    assert [x["message"] for x in champ(racine)["decisions"]] == [nouveau]


def test_decisions_repart_a_la_reactivation(racine, faux):
    _activer_a(racine, AVANT)
    _annonce(racine, "chantier-auto:a:1", ACTIVATION)
    conn = ouvrir(racine)
    with conn:    # une réactivation datée après l'annonce
        conn.execute("INSERT INTO reglages_projet (horodatage, cle, valeur, auteur, details)"
                     " SELECT ?, cle, valeur, auteur, details FROM reglages_projet", (APRES[0],))
    conn.close()
    assert champ(racine)["decisions"] == []


def test_decisions_ne_prend_que_les_rapports_de_l_assistant_a_utilisateur_aux_objets_connus(racine, faux):
    _activer_a(racine, ACTIVATION)
    sha = "b" * 40
    _annonce(racine, f"fusion-auto:x:{sha}", APRES[0], de="coord-x")                 # pas l'Assistant
    _annonce(racine, f"fusion-auto:x:{sha}", APRES[0], a="coord-x")                  # pas à l'utilisateur
    _annonce(racine, f"fusion-auto:x:{sha}", APRES[0], nature="signalement")         # pas un rapport
    _annonce(racine, "inconnu-auto:x", APRES[1])                                     # genre inconnu
    _annonce(racine, "chantier:x:1", APRES[1])                                       # pas une annonce -auto
    _annonce(racine, "Chantier-auto:x:1", APRES[1])
    _annonce(racine, None, APRES[1])
    bon = _annonce(racine, "contrat-auto:api", APRES[2])
    assert [x["message"] for x in champ(racine)["decisions"]] == [bon]


def test_decisions_cle_est_ce_qui_suit_le_premier_deux_points(racine, faux):
    _activer_a(racine, ACTIVATION)
    _annonce(racine, "autorisation-auto:a:b:c", APRES[0])
    assert champ(racine)["decisions"][0]["cle"] == "a:b:c"


def test_decisions_50_au_plus_les_plus_recentes(racine, faux):
    _activer_a(racine, ACTIVATION)
    base = MAINTENANT - timedelta(hours=4)
    ids = [_annonce(racine, f"contrat-auto:n{i}", _iso(base + timedelta(minutes=i))) for i in range(60)]
    d = champ(racine)["decisions"]
    assert len(d) == 50
    assert d[0]["message"] == ids[-1] and d[-1]["message"] == ids[10]


def test_decisions_vide_quand_inactif_meme_avec_des_annonces(racine, faux):
    _annonce(racine, "chantier-auto:a:1", APRES[0])
    c = champ(racine)
    assert c["active"] is False and c["decisions"] == [] and c["portee"] is None


def test_decisions_vide_apres_desactivation(racine, faux):
    _activer_a(racine, ACTIVATION)
    _annonce(racine, "chantier-auto:a:1", APRES[0])
    assert len(champ(racine)["decisions"]) == 1
    cli.main(["fusions-auto", "inactive"])
    conn = ouvrir(racine)
    with conn:    # la désactivation date d'avant l'annonce : seul le mode, pas la date, vide la liste
        conn.execute("UPDATE reglages_projet SET horodatage = ?", (ACTIVATION,))
    conn.close()
    c = champ(racine)
    assert c["decisions"] == [] and c["portee"] is None


def test_suspendue_aussi_quand_la_portee_est_inferieure_a_2(racine, faux):
    conn = ouvrir(racine)
    from cime.fondation import fusions_auto as fa
    reserves = fa.chemins_reserves(racine)
    with conn:
        conn.execute("INSERT INTO reglages_projet (horodatage, cle, valeur, auteur, details)"
                     " VALUES (?, 'fusions_auto', 'active', 'utilisateur', ?)",
                     (ACTIVATION, json.dumps({"reserves": reserves, "portee": 1,
                                              "empreinte": fa.empreinte(reserves, 5)})))
    conn.close()
    c = champ(racine)
    assert c["active"] is True and c["suspendue"] is True and c["portee"] == 1


def test_activation_sans_portee_donne_portee_null_et_suspendue(racine, faux):
    conn = ouvrir(racine)
    from cime.fondation import fusions_auto as fa
    reserves = fa.chemins_reserves(racine)
    with conn:
        conn.execute("INSERT INTO reglages_projet (horodatage, cle, valeur, auteur, details)"
                     " VALUES (?, 'fusions_auto', 'active', 'utilisateur', ?)",
                     (ACTIVATION, json.dumps({"reserves": reserves,
                                              "empreinte": fa.empreinte(reserves, 5)})))
    conn.close()
    c = champ(racine)
    assert c["active"] is True and c["suspendue"] is True and c["portee"] is None


def test_les_quatre_champs_toujours_presents_registre_absent_ou_illisible(tmp_path, faux):
    _orga(tmp_path)
    c = instantane(tmp_path, MAINTENANT)["fusions_auto"]
    assert (c["portee"], c["chantiers_24h"], c["chantiers_max"], c["decisions"]) == (None, 0, 5, [])
    (tmp_path / ".orga" / "etat").mkdir()
    (tmp_path / ".orga" / "etat" / "registre.sqlite").write_text("rien de sqlite" * 40)
    c = instantane(tmp_path, MAINTENANT)["fusions_auto"]
    assert (c["portee"], c["chantiers_24h"], c["chantiers_max"], c["decisions"]) == (None, 0, 5, [])


def test_registre_sans_la_table_des_messages_ne_casse_rien(tmp_path, faux):
    _orga(tmp_path)
    (tmp_path / ".orga" / "etat").mkdir()
    conn = sqlite3.connect(tmp_path / ".orga" / "etat" / "registre.sqlite")
    conn.execute("CREATE TABLE reglages_projet (id INTEGER PRIMARY KEY, horodatage TEXT, cle TEXT,"
                 " valeur TEXT, auteur TEXT, details TEXT)")
    conn.commit()
    conn.close()
    c = champ(tmp_path)
    assert c["decisions"] == [] and c["chantiers_24h"] == 0
