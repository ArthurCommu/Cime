"""Consommation de jetons (fenêtres 15/60 min, sous-agents, repli par cwd, alarmes)."""

import importlib
import json
from datetime import timedelta

import pytest

from cime.observation import alarmes, transcripts
from test_alarmes import _agent, _calculer
from test_instantane import Faux, W, _orga, base, faux, snap  # noqa: F401
from test_registre import MAINTENANT, iso

inst = importlib.import_module("cime.observation.instantane")


def _ligne(msg_id, minutes, *, lec=0, sortie=0, entree=0, sidechain=False):
    return json.dumps({
        "type": "assistant", "isSidechain": sidechain, "timestamp": iso(minutes),
        "message": {"id": msg_id, "model": "claude-opus-5-5", "usage": {
            "input_tokens": entree, "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": lec, "output_tokens": sortie}}}) + "\n"


def _ecrire(chemin, *lignes):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text("".join(lignes))
    return chemin


def test_fenetres_15_et_60_minutes(tmp_path):
    p = _ecrire(tmp_path / "s.jsonl", _ligne("a", 10, lec=100, sortie=1), _ligne("b", 30, lec=200, sortie=2),
                _ligne("c", 120, lec=400, sortie=4))
    c = transcripts.consommation(p, MAINTENANT)
    assert c["source"] == "transcript"
    assert (c["15min"]["lus"], c["15min"]["ecrits"], c["15min"]["tours"]) == (100, 1, 1)
    assert (c["60min"]["lus"], c["60min"]["ecrits"], c["60min"]["tours"]) == (300, 3, 2)


def test_illisible_renvoie_none(tmp_path):
    assert transcripts.consommation(tmp_path / "absent.jsonl", MAINTENANT) is None


def test_sous_agents_comptes(tmp_path):
    p = _ecrire(tmp_path / "s.jsonl", _ligne("a", 5, lec=100))
    assert transcripts.sous_agents(p) == []
    _ecrire(tmp_path / "s" / "subagents" / "agent-2.jsonl", _ligne("y", 5, lec=30, sidechain=True))
    _ecrire(tmp_path / "s" / "subagents" / "agent-1.jsonl", _ligne("x", 5, lec=20, sidechain=True),
            _ligne("z", 90, lec=999, sidechain=True))
    assert [f.name for f in transcripts.sous_agents(p)] == ["agent-1.jsonl", "agent-2.jsonl"]
    c = transcripts.consommation(p, MAINTENANT)
    assert c["15min"]["lus"] == 150 and c["15min"]["tours"] == 3 and c["15min"]["dont_sous_agents"] == 50
    assert c["60min"]["dont_sous_agents"] == 50 and c["60min"]["contexte_moyen"] == 100


def test_contexte_moyen_sans_les_sidechains(tmp_path):
    p = _ecrire(tmp_path / "s.jsonl", _ligne("a", 5, lec=100), _ligne("b", 4, lec=300),
                _ligne("c", 3, lec=10_000, sidechain=True))
    c = transcripts.consommation(p, MAINTENANT)["15min"]
    assert c["contexte_moyen"] == 200 and c["lus"] == 10_400 and c["tours"] == 3
    seul = _ecrire(tmp_path / "t.jsonl", _ligne("c", 3, lec=10_000, sidechain=True))
    assert transcripts.consommation(seul, MAINTENANT)["15min"]["contexte_moyen"] is None


def test_deduplication_par_message_id(tmp_path):
    p = _ecrire(tmp_path / "s.jsonl", _ligne("a", 5, lec=100, sortie=1), _ligne("a", 5, lec=100, sortie=7))
    c = transcripts.consommation(p, MAINTENANT)["15min"]
    assert (c["lus"], c["ecrits"], c["tours"]) == (100, 7, 1)


def test_trouver_par_cwd(tmp_path):
    dossier = tmp_path / "-home-exemple-projet"
    vieux = _ecrire(dossier / "vieux.jsonl", "{}\n")
    recent = _ecrire(dossier / "recent.jsonl", "{}\n")
    _ecrire(dossier / "sous" / "plus-recent.jsonl", "{}\n")
    import os
    os.utime(vieux, (1, 1))
    assert transcripts.trouver_par_cwd("/home/exemple/projet", tmp_path) == recent
    assert transcripts.trouver_par_cwd("/inconnu", tmp_path) is None
    assert transcripts.trouver_par_cwd("", tmp_path) is None


def _repli(faux, monkeypatch, tmp_path, cwds):
    """Chaque cwd -> un transcript de 100 jetons lus ; renvoie rien."""
    fichiers = {}
    for i, cwd in enumerate(sorted(set(cwds.values()))):
        fichiers[cwd] = _ecrire(tmp_path / f"t{i}.jsonl", _ligne(f"m{i}", 5, lec=100 * (i + 1), sortie=3))
    monkeypatch.setattr(transcripts, "trouver_par_cwd", lambda cwd, *a, **k: fichiers.get(cwd))
    for aid, cwd in cwds.items():
        faux.sessions[f"cc-{aid}"]["cwd"] = cwd


def test_repli_cwd_unique_alimente_les_champs(base, faux, monkeypatch, tmp_path):
    _repli(faux, monkeypatch, tmp_path, {"coord-page": "/p", "coord-observation": "/o", W: "/w"})
    d = snap(base.racine)
    a = next(x for x in d["agents"] if x["id"] == "coord-page")
    assert a["modele"] == "claude-opus-5-5" and a["cout_usd_estime"] is not None
    assert a["contexte"]["source"] == "transcript:cwd" and a["consommation"]["source"] == "transcript:cwd"
    assert a["consommation"]["15min"]["tours"] == 1
    assert next(x for x in d["agents"] if x["id"] == "utilisateur")["consommation"] is None
    assert next(x for x in d["agents"] if x["id"] == "assistant")["consommation"] is None
    mesures = [x["consommation"]["15min"]["lus"] for x in d["agents"] if x["consommation"]]
    assert d["consommation"]["15min"]["lus"] == sum(mesures) == 600
    assert d["consommation"]["15min"]["tours"] == 3


def test_repli_refuse_si_cwd_partage(base, faux, monkeypatch, tmp_path):
    _repli(faux, monkeypatch, tmp_path, {"coord-page": "/p", "coord-observation": "/p", W: "/w"})
    d = snap(base.racine)
    par_id = {x["id"]: x for x in d["agents"]}
    assert par_id["coord-page"]["consommation"] is None and par_id["coord-page"]["contexte"] is None
    assert par_id["coord-observation"]["consommation"] is None
    assert par_id[W]["consommation"] is not None
    assert [g["agent"] for g in d["consommation"]["gros_postes"]] == [W]


def test_aucun_agent_mesure_cle_racine_nulle(base, faux):
    assert snap(base.racine)["consommation"] is None


def test_gros_postes_ordre_et_limite_a_cinq():
    def ag(aid, lus):
        f = {"lus": lus, "ecrits": 1, "tours": 1, "contexte_moyen": None, "dont_sous_agents": 0}
        return {"id": aid, "consommation": {"15min": f, "60min": f, "source": "transcript"}}
    agents = [ag(f"a{i}", n) for i, n in enumerate([10, 70, 0, 30, 50, 20, 40, 60])]
    r = inst._consommation_projet(agents)
    assert [g["agent"] for g in r["gros_postes"]] == ["a1", "a7", "a4", "a6", "a3"]
    assert r["gros_postes"][0] == {"agent": "a1", "lus_15min": 70, "part_15min": round(70 / 280, 3)}
    assert r["15min"] == {"lus": 280, "ecrits": 8, "tours": 8}


def _conso(lus):
    f = {"lus": lus, "ecrits": 0, "tours": 1, "contexte_moyen": None, "dont_sous_agents": 0}
    return {"15min": f, "60min": f, "source": "transcript"}


def _gros(*lus_par_agent):
    agents = [_agent(f"coord-a{i}", consommation=_conso(n)) for i, n in enumerate(lus_par_agent)]
    return [a for a in _calculer(agents) if a["type"] == "gros_poste"]


def test_gros_poste_seuil_de_part():
    assert _gros(410_000, 589_999) == []                 # sous le plancher du projet
    al = _gros(400_000, 600_000, 1)                       # 60 % d'un projet à 1 M : sonne
    assert [a["id"] for a in al] == ["gros_poste:coord-a1"] and al[0]["gravite"] == "a_voir"
    assert al[0]["depuis"].endswith("Z") and "60 %" in al[0]["mesure"]
    assert _gros(1_000_000, 700_000, 700_000, 700_000) == []   # 1/3,5 = 28,6 % < 40 %


def test_gros_poste_plancher():
    assert _gros(500_000) == []                           # seul à 100 %, sous le plancher
    assert [a["id"] for a in _gros(1_000_000)] == ["gros_poste:coord-a0"]
    assert _gros(999_999) == []


def test_gros_poste_seuil_absolu():
    # quatre agents autour de 5 M : aucune part > 40 %, seul le seuil absolu compte (strict)
    assert [a["id"] for a in _gros(5_000_000, 5_000_001, 5_000_000, 5_000_000)] == ["gros_poste:coord-a1"]


def _repos(tokens, minutes):
    a = _agent(etat="au_repos", etat_depuis=iso(minutes),
               contexte={"tokens": tokens, "limite": 1_000_000, "source": "transcript"})
    return [x for x in _calculer([a]) if x["type"] == "contexte_au_repos"]


def test_contexte_au_repos_se_declenche():
    al = _repos(200_000, 11)
    epoch = int((MAINTENANT - timedelta(minutes=11)).timestamp())
    assert [a["id"] for a in al] == [f"contexte_au_repos:coord-page:{epoch}"]
    assert al[0]["quoi_faire"] == "À compacter avant son prochain tour." and al[0]["gravite"] == "a_voir"


def test_contexte_au_repos_pas_sous_10_minutes():
    assert _repos(200_000, 9) == []


def test_contexte_au_repos_pas_sous_150k():
    assert _repos(150_000, 30) == []


def test_contexte_au_repos_seulement_au_repos():
    a = _agent(etat="travaille", contexte={"tokens": 900_000, "limite": 2_000_000, "source": "transcript"})
    assert [x for x in _calculer([a]) if x["type"] == "contexte_au_repos"] == []
