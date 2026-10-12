"""`cime journal` : vraies commandes, vrai registre du banc, horloge simulée."""
import hashlib
import json
import sqlite3

import pytest

from cime.signaux import journal
from e2e.aides import ASSISTANT, COORD, envoyer, etat

TABLES = ("messages", "evenements", "transitions", "courriers", "obligations", "ordres", "occupation",
          "journal", "facteur")
COORD_B = "coord-beta"
W = "worker-alpha-t1"


def _ids_evenements(banc, agent, depuis, jusqu):
    return [i for (i,) in banc.prouve("SELECT id FROM evenements WHERE agent = ? AND horodatage >= ?"
                                      " AND horodatage <= ? ORDER BY id", (agent, depuis, jusqu))]


def _ids_montres(sortie):
    """Identifiants des seules lignes d'événements (la section « événements » jusqu'aux « courriers »)."""
    section = sortie.split("événements (", 1)[1].split("courriers (", 1)[0]
    return {int(ligne.split()[0][1:]) for ligne in section.splitlines() if ligne.startswith("  #")}


def _empreinte(banc) -> str:
    h = hashlib.sha256()
    for table in TABLES:
        h.update(repr(banc.prouve(f"SELECT * FROM {table} ORDER BY 1")).encode())
    return h.hexdigest()


def test_fenetre_ne_montre_que_les_evenements_et_courriers_de_la_fenetre(banc):
    banc.au_repos(COORD)                                           # avant la fenêtre
    banc.horloge.avance(minutes=30)
    depuis = banc.horloge.iso()
    envoyer(banc, ASSISTANT, COORD, "consigne", "dans la fenêtre")
    banc.acteur(COORD).hook("Stop", {"stop_hook_active": False})   # événement et courrier hook dans la fenêtre
    banc.horloge.avance(minutes=5)
    jusqu = banc.horloge.iso()
    banc.horloge.avance(minutes=30)
    banc.au_repos(COORD)                                           # après la fenêtre
    r = banc.acteur(ASSISTANT).cime("journal", COORD, "--depuis", depuis, "--jusqu-a", jusqu)
    assert r.code == 0, r.erreur
    dedans = _ids_evenements(banc, COORD, depuis, jusqu)
    dehors = [i for (i,) in banc.prouve("SELECT id FROM evenements WHERE agent = ?", (COORD,))
              if i not in dedans]
    assert dedans and dehors
    montres = _ids_montres(r.sortie)
    assert set(dedans) <= montres and not (set(dehors) & montres)
    assert r.sortie.count("hook:Stop") == 1


def test_le_registre_n_est_pas_modifie_et_la_connexion_est_en_lecture_seule(banc):
    banc.au_repos(COORD)
    envoyer(banc, ASSISTANT, COORD, "consigne", "regarde")
    banc.acteur(COORD).hook("Stop", {"stop_hook_active": False})
    avant = _empreinte(banc)
    r = banc.acteur(ASSISTANT).cime("journal", COORD)
    assert r.code == 0, r.erreur
    assert _empreinte(banc) == avant
    conn = journal._lecture(banc.projet)
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("DELETE FROM messages")
    finally:
        conn.close()


def _equipes(banc):
    for equipe in ("alpha", "beta"):
        (banc.projet / ".orga" / "teams" / equipe).mkdir(parents=True, exist_ok=True)


def test_un_coordinateur_ne_lit_que_les_workers_de_son_equipe(banc):
    _equipes(banc)
    banc.au_repos(W)
    assert banc.acteur(COORD).cime("journal", W).code == 0              # coord-alpha → worker-alpha-t1
    refus = banc.acteur(COORD_B).cime("journal", W)                     # coord-beta → worker-alpha-t1
    assert refus.code != 0 and "peut lire le journal de" in refus.erreur
    refus = banc.acteur(COORD).cime("journal", COORD_B)                 # un coordinateur ne lit pas un pair
    assert refus.code != 0 and "peut lire le journal de" in refus.erreur


def test_l_assistant_lit_ses_coordinateurs_et_un_worker_est_refuse(banc):
    _equipes(banc)
    banc.au_repos(COORD)
    banc.au_repos(W)
    assert banc.acteur(ASSISTANT).cime("journal", COORD).code == 0
    refus = banc.acteur(ASSISTANT).cime("journal", W)
    assert refus.code != 0 and "peut lire le journal de" in refus.erreur


def test_aucun_chemin_de_transcript_ni_contenu_de_tour_dans_la_sortie(banc):
    banc.acteur(COORD).hook("SessionStart", {"source": "startup",
                                             "transcript_path": "/home/exemple/secret/transcript-x.jsonl",
                                             "cwd": "/home/exemple/secret/projet"})
    banc.acteur(COORD).hook("Stop", {"last_assistant_message": "contenu-du-dernier-message " * 40})
    assert "/home/exemple/secret" in str(banc.prouve("SELECT details FROM evenements WHERE agent = ?", (COORD,)))
    r = banc.acteur(ASSISTANT).cime("journal", COORD)
    assert r.code == 0, r.erreur
    assert "transcript" not in r.sortie and "/home/exemple/secret" not in r.sortie
    assert "contenu-du-dernier-message" not in r.sortie
    assert all(len(ligne) <= 260 for ligne in r.sortie.splitlines())


def test_date_illisible_refusee_sans_rien_lire(banc):
    r = banc.acteur(ASSISTANT).cime("journal", COORD, "--depuis", "hier")
    assert r.code != 0 and "date illisible" in r.erreur


def test_un_agent_lit_son_propre_journal(banc):
    _equipes(banc)
    banc.au_repos(COORD)
    banc.au_repos(W)
    assert banc.acteur(COORD).cime("journal", COORD).code == 0          # un coordinateur lit le sien
    assert banc.acteur(W).cime("journal", W).code == 0                  # un worker lit le sien
    assert banc.acteur(ASSISTANT).cime("journal", ASSISTANT).code == 0  # l'Assistant lit le sien
    refus = banc.acteur(W).cime("journal", "worker-alpha-t2")           # un worker ne lit pas celui d'un autre
    assert refus.code != 0 and "peut lire le journal de worker-alpha-t2" in refus.erreur


def _remettre_par_le_hook(banc, texte):
    """Un message remis par le hook `Stop` : courrier `hook:Stop` ouvert, message `livre` par ce courrier."""
    m = envoyer(banc, ASSISTANT, COORD, "consigne", texte)
    r = banc.acteur(COORD).hook("Stop", {"stop_hook_active": False})
    assert r.code == 2 and texte in r.stderr
    return m


def _ligne_courrier(sortie, cid) -> str:
    section = sortie.split("courriers (", 1)[1]
    return next(ligne for ligne in section.splitlines() if ligne.startswith(f"  #{cid}  "))


def test_courrier_acquitte_montre_l_heure_de_son_dernier_accuse(banc):
    banc.au_repos(COORD)
    banc.facteur_tour()
    _remettre_par_le_hook(banc, "une consigne")
    banc.horloge.avance(seconds=5)
    banc.acteur(COORD).hook("PostToolUse", {"tool_name": "Bash"})          # l'accusé : un outil après la remise
    [(cid, fermeture)] = banc.prouve(
        "SELECT c.id, (SELECT max(horodatage) FROM transitions t WHERE t.courrier_id = c.id"
        " AND t.etat = 'pris_en_compte') FROM courriers c WHERE c.a = ? AND c.etat = 'acquitte'", (COORD,))
    r = banc.acteur(ASSISTANT).cime("journal", COORD)
    assert r.code == 0, r.erreur
    assert _ligne_courrier(r.sortie, cid).endswith(f"état acquitte  tentative 1  fermé {fermeture}")


def test_courrier_echoue_montre_l_heure_de_sa_reprise(banc):
    banc.au_repos(COORD)
    banc.facteur_tour()     # facteur en régime établi : son premier passage ferme les courriers expirés (reprise)
    _remettre_par_le_hook(banc, "première consigne")
    banc.tmux.repos(COORD)
    m2 = envoyer(banc, ASSISTANT, COORD, "consigne", "deuxième consigne")
    banc.horloge.avance(seconds=320)
    banc.faire_tourner(320, pas=10, jusqu_a=lambda: etat(banc, m2) == "livre")
    [(cid, reprise)] = banc.prouve(
        "SELECT c.id, (SELECT min(t.horodatage) FROM transitions t WHERE t.etat = 'inscrit'"
        " AND json_extract(t.preuve, '$.reprise') = c.id) FROM courriers c"
        " WHERE c.a = ? AND c.etat = 'echoue'", (COORD,))
    assert reprise is not None
    r = banc.acteur(ASSISTANT).cime("journal", COORD)
    assert r.code == 0, r.erreur
    assert _ligne_courrier(r.sortie, cid).endswith(f"état echoue  tentative 1  fermé {reprise}")


def test_envois_montrent_l_empreinte_sans_le_texte(banc):
    a = envoyer(banc, COORD, ASSISTANT, "question", "texte-secret-du-resume")
    banc.horloge.avance(minutes=11)        # au-delà de DOUBLON_FENETRE : l'envoi identique est permis
    b = envoyer(banc, COORD, ASSISTANT, "question", "texte-secret-du-resume")
    c = envoyer(banc, COORD, ASSISTANT, "question", "autre texte")
    r = banc.acteur(ASSISTANT).cime("journal", COORD)
    assert r.code == 0, r.erreur
    section = r.sortie.split("envois (", 1)[1]
    lignes = {int(ligne.split()[0][1:]): ligne for ligne in section.splitlines() if ligne.startswith("  #")}
    assert set(lignes) == {a, b, c}
    assert all(f"→ {ASSISTANT}  question" in lignes[i] for i in lignes)

    def empreinte(i):
        return lignes[i].split("empreinte ")[1]
    attendue = hashlib.sha1("texte-secret-du-resume\n".encode("utf-8")).hexdigest()[:8]
    assert empreinte(a) == empreinte(b) == attendue
    assert empreinte(c) != attendue
    assert "texte-secret-du-resume" not in r.sortie and "autre texte" not in r.sortie


def _cause_sous(sortie, cid) -> str:
    """La ligne qui suit l'en-tête du courrier `cid` dans la section « courriers »."""
    section = sortie.split("courriers (", 1)[1].splitlines()
    return section[next(n for n, ligne in enumerate(section) if ligne.startswith(f"  #{cid}  ")) + 1]


def test_courrier_echoue_pour_collision_montre_la_cause_sans_le_texte(banc):
    banc.au_repos(COORD)
    banc.tmux.injecter_apres_frappe("Z")                       # l'utilisateur tape pendant la frappe
    envoyer(banc, ASSISTANT, COORD, "consigne", "regarde ceci")
    banc.facteur_tour()
    [(cid,)] = banc.prouve("SELECT id FROM courriers WHERE a = ? AND etat = 'echoue'", (COORD,))
    [(preuve,)] = banc.prouve("SELECT preuve FROM transitions WHERE etat = 'inscrit'"
                              " AND json_extract(preuve, '$.reprise') = ?", (cid,))
    ecran = json.loads(preuve)["ecran"]
    r = banc.acteur(ASSISTANT).cime("journal", COORD)
    assert r.code == 0, r.erreur
    cause = _cause_sous(r.sortie, cid)
    assert cause.startswith(
        f"    cause : collision, efface non, écran contient vu {ecran['vu_len']}/{ecran['texte_len']}"
        f" écart {ecran['ecart']} lignes {ecran['lignes']}, zone ligne0 attenue 0 / total 0, par ligne ")
    assert cause.endswith(", règles 0,2, haut 1/4")
    assert "regarde" not in r.sortie and "Assistant" not in r.sortie


def test_cause_sans_accuse_est_affichee(banc):
    banc.au_repos(COORD)
    banc.facteur_tour()
    envoyer(banc, ASSISTANT, COORD, "consigne", "regarde ceci")
    banc.faire_tourner(60, pas=10)                             # l'accusé ne vient pas : sans_accuse à 30 s
    [(cid,)] = banc.prouve("SELECT id FROM courriers WHERE a = ? AND etat = 'echoue'", (COORD,))
    r = banc.acteur(ASSISTANT).cime("journal", COORD)
    assert r.code == 0, r.erreur
    assert _cause_sous(r.sortie, cid) == "    cause : sans accusé"


def test_cause_sans_cle_connue_n_affiche_rien():
    assert journal._cause_rendue({"reprise": 3, "tentative": 2}) is None
    assert journal._cause_rendue(None) is None
    assert journal._cause_rendue({"reprise": 3, "inconnue": "x"}) is None


def test_cause_montre_la_zone_et_le_pane_en_nombres_seulement():
    preuve = {"collision": True, "efface": False,
              "ecran": {"texte_len": 5, "vu_len": 3, "relation": "contient", "ecart": 1, "lignes": 1},
              "zone": {"capture_lignes": 9, "regles": [0, 2, 4], "zone_haut": 1, "zone_lignes": 1,
                       "visible_par_ligne": [5, 0], "attenue_perdu": 7, "attenue_ligne0": 7, "texte": "secret"},
              "pane": [78, 45]}
    assert journal._cause_rendue(preuve) == (
        "collision, efface non, écran contient vu 3/5 écart 1 lignes 1, "
        "zone ligne0 attenue 7 / total 7, par ligne 5,0, règles 0,2,4, haut 1/9, pane 78x45")
    assert "secret" not in journal._cause_rendue(preuve)


def test_cause_pane_seul_et_pane_mal_forme():
    assert journal._cause_rendue({"reprise": 3, "pane": [78, 45]}) == "pane 78x45"
    assert journal._cause_rendue({"reprise": 3, "pane": "78x45"}) is None
    assert journal._cause_rendue({"reprise": 3, "pane": [78]}) is None
