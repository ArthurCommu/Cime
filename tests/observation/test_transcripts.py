"""Lecture des transcripts : usage, contexte, coût, cache incrémental, première réponse au-dessus d'un seuil."""

import json
from pathlib import Path

from chrono import meilleur
from cime.observation import transcripts
from cime.observation.transcripts import lire_transcript, trouver_transcript

FIXTURE = Path(__file__).parent / "fixtures" / "transcript_assistant.jsonl"
SESSION = "606e443a-c058-4fd2-8007-4214998bc835"

# Calculé à la main sur les 11 réponses distinctes de la fixture (dernier usage par id) :
# entrée 22, sortie 8054, cache 1 h 47236, lecture cache 610794 ; opus 5.5 = 4/20/8/0,20 $.
COUT_ATTENDU = (22 * 4 + 8054 * 20 + 47236 * 8 + 610794 * 0.20) / 1_000_000
CONTEXTE_ATTENDU = 2 + 4122 + 68334  # dernière réponse


def _ligne(msg_id, modele="claude-opus-5-5", sidechain=False, entree=1, ecr=0, lec=0, sortie=0, ts="2026-10-07T10:00:00.000Z"):
    return json.dumps({
        "type": "assistant", "isSidechain": sidechain, "timestamp": ts,
        "message": {"id": msg_id, "model": modele, "usage": {
            "input_tokens": entree, "cache_creation_input_tokens": ecr,
            "cache_read_input_tokens": lec, "output_tokens": sortie,
            "cache_creation": {"ephemeral_1h_input_tokens": 0, "ephemeral_5m_input_tokens": ecr}}},
    }) + "\n"


def _ecrire(tmp_path, texte, nom="t.jsonl"):
    p = tmp_path / nom
    p.write_text(texte)
    return p


def test_fixture_reelle_contexte_et_cout():
    donnees, source = lire_transcript(FIXTURE)
    assert source == {"nom": "transcript", "ok": True}
    assert donnees["modele"] == "claude-opus-5-5"
    assert donnees["contexte"] == {"tokens": CONTEXTE_ATTENDU, "limite": 1_000_000, "source": "transcript"}
    assert abs(donnees["cout_usd_estime"] - COUT_ATTENDU) < 1e-9
    assert donnees["derniere_activite"] == "2026-10-07T15:33:36.298Z"


def test_deduplication_cout_identique_avec_ou_sans_doublons(tmp_path):
    lignes = FIXTURE.read_text().splitlines(keepends=True)
    vus, sans = set(), []
    for l in lignes:
        i = json.loads(l)["message"]["id"]
        if i not in vus:
            vus.add(i)
            sans.append(l)
    assert len(sans) == 11 and len(lignes) == 20
    avec, _ = lire_transcript(_ecrire(tmp_path, "".join(lignes), "avec.jsonl"))
    sans_d, _ = lire_transcript(_ecrire(tmp_path, "".join(sans), "sans.jsonl"))
    assert avec["cout_usd_estime"] == sans_d["cout_usd_estime"]
    assert avec["contexte"] == sans_d["contexte"]


def test_sidechain_exclu_du_contexte_inclus_dans_le_cout(tmp_path):
    p = _ecrire(tmp_path, _ligne("a", entree=10, lec=100, sortie=5)
                + _ligne("b", sidechain=True, entree=1_000_000, sortie=0))
    donnees, _ = lire_transcript(p)
    assert donnees["contexte"]["tokens"] == 110
    assert abs(donnees["cout_usd_estime"] - (10 * 4 + 100 * 0.20 + 5 * 20 + 1_000_000 * 4) / 1e6) < 1e-9


def test_modele_inconnu_limite_et_cout_none(tmp_path):
    donnees, source = lire_transcript(_ecrire(tmp_path, _ligne("a", modele="claude-inconnu-9", entree=7)))
    assert source["ok"] is True
    assert donnees["contexte"] == {"tokens": 7, "limite": None, "source": "transcript"}
    assert donnees["cout_usd_estime"] is None


def test_fichier_absent(tmp_path):
    donnees, source = lire_transcript(tmp_path / "absent.jsonl")
    assert donnees is None
    assert source["nom"] == "transcript" and source["ok"] is False and source["erreur"]


def test_ligne_tronquee_en_fin_ignoree_puis_reprise(tmp_path):
    complet = _ligne("a", entree=3) + _ligne("b", entree=4)
    p = _ecrire(tmp_path, _ligne("a", entree=3) + complet[len(_ligne("a", entree=3)):][:40])
    donnees, source = lire_transcript(p)
    assert source["ok"] is True
    assert donnees["contexte"]["tokens"] == 3
    p.write_text(complet)  # l'écriture se termine : la ligne est relue
    donnees, _ = lire_transcript(p)
    assert donnees["contexte"]["tokens"] == 4


def test_ajout_incremental_equivaut_a_relecture_complete(tmp_path):
    p = _ecrire(tmp_path, _ligne("a", entree=1, sortie=10))
    lire_transcript(p)
    with open(p, "a") as f:
        f.write(_ligne("a", entree=1, sortie=20) + _ligne("b", entree=5, sortie=1))
    incremental, _ = lire_transcript(p)
    transcripts._CACHE.clear()
    complet, _ = lire_transcript(p)
    assert incremental == complet


def test_trouver_transcript(tmp_path):
    (tmp_path / "-proj").mkdir()
    cible = tmp_path / "-proj" / "abc.jsonl"
    cible.write_text("")
    assert trouver_transcript("abc", tmp_path) == cible
    assert trouver_transcript("zzz", tmp_path) is None
    assert trouver_transcript("../abc", tmp_path) is None
    assert trouver_transcript("abc", tmp_path / "nexiste-pas") is None


def test_gros_transcript_second_appel_rapide(tmp_path):
    bloc = _ligne("m", entree=1, ecr=100, lec=5000, sortie=50) * 1
    n = 52_428_800 // len(bloc.encode()) + 1
    p = tmp_path / "gros.jsonl"
    with open(p, "w") as f:
        for i in range(n):
            f.write(bloc.replace('"id": "m"', f'"id": "m{i}"'))
    assert p.stat().st_size >= 50 * 1024 * 1024
    premier, _ = lire_transcript(p)
    duree, (second, _) = meilleur(lambda: lire_transcript(p), 5)
    assert duree < 0.020
    assert second == premier


# --- première réponse au-dessus d'un seuil ----------

def _serie(*contextes, debut=0):
    return "".join(_ligne(f"m{debut + i}", lec=c, entree=0, ts=f"2026-10-07T10:{debut + i:02d}:00.000Z")
                   for i, c in enumerate(contextes))


def test_premiere_reponse_au_dessus_du_seuil(tmp_path):
    p = _ecrire(tmp_path, _serie(100, 700, 650, 800))
    assert transcripts.premiere_reponse_au_dessus(p, 600) == "2026-10-07T10:01:00.000Z"


def test_retour_sous_le_seuil_apres_compact_puis_nouvelle_serie(tmp_path):
    p = _ecrire(tmp_path, _serie(700, 900, 50))  # /compact : le contexte retombe
    assert transcripts.premiere_reponse_au_dessus(p, 600) is None
    with open(p, "a") as f:  # le transcript grandit : relu par le cache incrémental
        f.write(_serie(300, 650, 700, debut=3))
    assert transcripts.premiere_reponse_au_dessus(p, 600) == "2026-10-07T10:04:00.000Z"


def test_sidechain_ignoree_et_fichier_absent(tmp_path):
    texte = _serie(700) + _ligne("s1", sidechain=True, lec=10, entree=0, ts="2026-10-07T10:05:00.000Z")
    assert transcripts.premiere_reponse_au_dessus(_ecrire(tmp_path, texte), 600) == "2026-10-07T10:00:00.000Z"
    assert transcripts.premiere_reponse_au_dessus(tmp_path / "absent.jsonl", 600) is None
