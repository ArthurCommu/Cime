"""Conformité de l'instantané d'exemple (`fixtures/exemple-etat.json`) à la forme de l'état que l'hôte sert.

Chaque vérification est une fonction `verifier_*(donnees)` qui lève
AssertionError. Les tests la lancent sur les vraies données ; la table
MUTATIONS prouve, sur une copie en mémoire, qu'elle échoue si on casse la
donnée qu'elle garde.
"""
import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

EXEMPLES = Path(__file__).resolve().parent / "fixtures"

ROLES = {"utilisateur", "assistant", "coordinateur", "worker"}
ETATS = {"travaille", "au_repos", "endormi", "attend_autorisation", "attend_reponse", "arrete", "inconnu"}
STATUTS = {"active", "au_repos", "bloquee", "terminee"}
NATURES_ATTENTE = {"autorisation", "decision", "donnee", "cloture", "rapport"}
TYPES_ALARME = {
    "autorisation_en_attente", "question_sans_reponse", "recouvrement",
    "brouillon", "contexte_plein", "hors_perimetre", "retard_sur_base", "session_disparue",
    "action_refusee", "bloque_au_demarrage", "fige", "session_orpheline", "gros_poste", "contexte_au_repos",
    "assistant_sourd", "livraison_echouee", "livraison_bloquee", "facteur_arrete", "fin_sans_suite",
}
GRAVITES = {"grave", "a_voir", "info"}
ACTIONS_ATTENTE = {"autoriser", "refuser", "trancher", "deposer", "cloturer", "lu", "accorder"}
ACTIONS_JOURNAL = ACTIONS_ATTENTE
# nature d'attente -> actions permises, et nature du message du fil qui la porte
ACTIONS_PAR_NATURE = {
    "autorisation": ["autoriser", "refuser"], "decision": ["trancher"], "donnee": ["deposer"],
    "cloture": ["cloturer"], "rapport": ["lu"],
}
MESSAGE_PAR_NATURE = {
    "decision": "decision_utilisateur", "donnee": "donnee_utilisateur",
    "cloture": "rapport_utilisateur", "rapport": "rapport_utilisateur",
}
# liste fermée des natures du fil ; null pour source "hook"
NATURES_FIL = {
    "consigne", "question", "reponse", "compte_rendu", "travail_pret", "demande_cloture",
    "signalement", "rapport_utilisateur", "decision_utilisateur", "donnee_utilisateur",
}
ETAPES = [
    "Cadrage : vision, découpage et décisions de l'utilisateur",
    "Maquette complétée, validée par l'utilisateur",
    "Le registre des échanges fonctionne sur ce projet-ci",
    "La page montre l'entreprise de ce projet-ci en direct",
    "Autoriser une demande depuis la page",
    "Un nouveau projet se crée en une commande, avec un Assistant prêt à démarrer",
]
# Ce que chaque source en échec invalide : (liste, champ).
DEPENDANTS = {"tarifs": ("agents", "cout_usd_estime")}
OCCUPATIONS = {"tour", "invite", "attente_stop", None}
ETATS_LIVRAISON = {"inscrit", "livre", "pris_en_compte", "clos", "echec", "abandonne"}
SOURCES = {"structure", "registre", "transcripts", "tmux", "git", "tarifs"}
SEUIL_CONTEXTE = 0.6
FENETRE_REFUS_S = 30 * 60
SEUIL_BROUILLON_S = 60
SEUIL_DEMARRAGE_S = 120
RE_HORO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def charger(nom):
    return json.loads((EXEMPLES / nom).read_text(encoding="utf-8"))


def horo(texte):
    assert isinstance(texte, str) and RE_HORO.match(texte), f"horodatage invalide : {texte!r}"
    return datetime.strptime(texte, "%Y-%m-%dT%H:%M:%S.%fZ")


def cles(objet, attendues, contexte):
    assert isinstance(objet, dict), f"{contexte} : objet attendu"
    assert set(objet) == set(attendues), f"{contexte} : clés {sorted(objet)} != {sorted(attendues)}"


def texte_ou_none(v):
    return v is None or (isinstance(v, str) and v != "")


def ids_agents(e):
    return {a["id"] for a in e["agents"]}


def noms_equipes(e):
    return {q["nom"] for q in e["equipes"]}


# ------------------------------------------------------------------ vérifications

def verifier_racine(e):
    cles(e, ["version", "genere_a", "duree_collecte_ms", "projet", "sources", "agents",
             "equipes", "fil", "flux", "aretes", "ordres", "facteur", "attentes_utilisateur", "consommation", "alarmes",
             "sessions_hors_organigramme", "decisions_recentes", "fusions_auto"], "racine")
    assert e["version"] == 2
    horo(e["genere_a"])
    assert isinstance(e["duree_collecte_ms"], int) and 0 <= e["duree_collecte_ms"] < 2000


def verifier_projet(e):
    p = e["projet"]
    cles(p, ["nom", "racine", "prefixe", "branche_reference", "etapes"], "projet")
    assert p["nom"] == "projet-boutique" and p["prefixe"] == "cc"
    assert p["racine"].startswith("/home/exemple/")
    assert [x["nom"] for x in p["etapes"]] == ETAPES
    for i, x in enumerate(p["etapes"]):
        cles(x, ["nom", "atteinte", "date"], "etape")
        assert isinstance(x["atteinte"], bool)
        assert x["atteinte"] == (i == 0)
        assert x["date"] == ("2026-10-07" if i == 0 else None)


def verifier_sources(e):
    assert e["sources"], "sources vide"
    for s in e["sources"]:
        assert isinstance(s["nom"], str) and isinstance(s["ok"], bool)
        if s["ok"]:
            cles(s, ["nom", "ok"], "source ok")
        else:
            cles(s, ["nom", "ok", "erreur"], "source en échec")
            assert isinstance(s["erreur"], str) and s["erreur"]
    assert any(not s["ok"] for s in e["sources"]), "aucune source en échec"
    noms = [s["nom"] for s in e["sources"]]
    assert len(noms) == len(set(noms))
    assert set(noms) <= SOURCES, f"sources hors liste : {sorted(set(noms) - SOURCES)}"


def verifier_agents_forme(e):
    attendues = ["id", "role", "equipe", "parent", "session_tmux", "vivant", "etat", "etat_depuis",
                 "etat_source", "tache", "derniere_phrase", "modele", "contexte",
                 "cout_usd_estime", "consommation", "brouillon", "dettes", "file", "occupe_par"]
    ids = [a["id"] for a in e["agents"]]
    assert len(ids) == len(set(ids)), "ids d'agents en double"
    for a in e["agents"]:
        cles(a, attendues, a.get("id"))
        assert a["role"] in ROLES, a["id"]
        assert a["etat"] in ETATS, a["id"]
        assert a["vivant"] in (True, False, None)
        for k in ("equipe", "parent", "session_tmux", "etat_source", "tache", "modele"):
            assert texte_ou_none(a[k]), (a["id"], k)
        if a["etat_depuis"] is not None:
            horo(a["etat_depuis"])
        if a["derniere_phrase"] is not None:
            assert isinstance(a["derniere_phrase"], str) and len(a["derniere_phrase"]) <= 300
        if a["contexte"] is not None:
            cles(a["contexte"], ["tokens", "limite", "source"], "contexte")
            assert isinstance(a["contexte"]["tokens"], int) and isinstance(a["contexte"]["limite"], int)
            assert 0 <= a["contexte"]["tokens"] <= a["contexte"]["limite"]
        c = a["cout_usd_estime"]
        assert c is None or (isinstance(c, (int, float)) and not isinstance(c, bool) and c >= 0)
        assert a["occupe_par"] in OCCUPATIONS, a["id"]
        for d in a["dettes"]:
            cles(d, ["id", "attendu", "de", "objet", "depuis"], "dette")
            assert isinstance(d["id"], int) and d["attendu"] and d["de"]
            horo(d["depuis"])
        for f in a["file"]:
            cles(f, ["id", "de", "nature", "objet", "resume", "depuis"], "file")
            assert isinstance(f["id"], int) and f["nature"] in NATURES_FIL
            horo(f["depuis"])
        if a["brouillon"] is not None:
            cles(a["brouillon"], ["texte", "depuis"], "brouillon")
            assert a["brouillon"]["texte"]
            horo(a["brouillon"]["depuis"])
        # hiérarchie
        if a["role"] in ("utilisateur", "assistant"):
            assert a["equipe"] is None
        else:
            assert a["equipe"] is not None and a["parent"] is not None
        if a["role"] == "worker":
            assert a["parent"].startswith("coord-")
        if a["role"] == "coordinateur":
            assert a["parent"] == "assistant"
        # état cohérent avec la session
        if a["etat"] == "arrete":
            assert a["vivant"] is False, a["id"]
        if a["vivant"] is False:  # un coordinateur endormi a sa session fermée, comme un arrêté
            assert a["etat"] in ("arrete", "endormi"), a["id"]
        if a["etat"] != "inconnu" and a["role"] != "utilisateur":
            assert a["etat_source"] and a["etat_depuis"], a["id"]


def verifier_utilisateur(e):
    utilisateur = [a for a in e["agents"] if a["role"] == "utilisateur"]
    assert [a["id"] for a in utilisateur] == ["utilisateur"]
    a = utilisateur[0]
    assert a["etat"] == "inconnu"
    for k in ("vivant", "modele", "contexte", "cout_usd_estime", "consommation", "tache", "derniere_phrase", "brouillon", "occupe_par"):
        assert a[k] is None, k
    assert a["dettes"] == [] and a["file"] == []  # `cime` et l'utilisateur ne sont pas des agents de livraison


def verifier_agents_couverture(e):
    assert {a["etat"] for a in e["agents"]} == ETATS
    assert any(a["brouillon"] is not None for a in e["agents"])
    assert any(a["contexte"] and a["contexte"]["tokens"] > SEUIL_CONTEXTE * a["contexte"]["limite"]
               for a in e["agents"])
    assert {a["role"] for a in e["agents"]} == ROLES
    assert any(a["parent"] == "assistant" for a in e["agents"])


def verifier_source_en_echec(e):
    echecs = [s["nom"] for s in e["sources"] if not s["ok"]]
    couvert = [n for n in echecs if n in DEPENDANTS]
    assert couvert, "aucune source en échec ne dépend d'un champ connu"
    for nom in couvert:
        liste, champ = DEPENDANTS[nom]
        for x in e[liste]:
            assert x[champ] is None, f"{nom} en échec mais {x.get('id')}.{champ} = {x[champ]!r}"
    # une mesure réussie n'est jamais un faux zéro : un nombre ne vaut pas 0 pour un agent qui travaille
    for a in e["agents"]:
        if a["contexte"] is not None:
            assert a["contexte"]["tokens"] > 0


def verifier_equipes(e):
    attendues = ["nom", "mission", "speciale", "statut", "cloturee_le", "branche", "commit", "worktree", "avancement",
                 "fichiers_touches", "perimetre_declare", "hors_perimetre", "retard_sur_base",
                 "en_avance_sur_base", "depend_de"]
    noms = [q["nom"] for q in e["equipes"]]
    assert len(noms) == len(set(noms))
    for q in e["equipes"]:
        cles(q, attendues, q.get("nom"))
        assert q["statut"] in STATUTS
        # date de clôture écrite par l'hôte, présente si et seulement si terminee
        if q["statut"] == "terminee":
            horo(q["cloturee_le"])
        else:
            assert q["cloturee_le"] is None, q["nom"]
        assert isinstance(q["speciale"], bool)
        assert q["mission"] and q["branche"] == f"equipe/{q['nom']}"
        assert re.fullmatch(r"[0-9a-f]{7}", q["commit"])
        assert q["worktree"].startswith("/home/exemple/")
        cles(q["avancement"], ["faites", "en_cours", "a_faire"], "avancement")
        assert all(isinstance(v, int) and v >= 0 for v in q["avancement"].values())
        for k in ("fichiers_touches", "perimetre_declare", "hors_perimetre"):
            assert isinstance(q[k], list) and all(isinstance(x, str) for x in q[k])
        assert isinstance(q["retard_sur_base"], int) and q["retard_sur_base"] >= 0
        # commits non fusionnés ; null sans branche
        assert q["en_avance_sur_base"] is None or (
            isinstance(q["en_avance_sur_base"], int) and not isinstance(q["en_avance_sur_base"], bool)
            and q["en_avance_sur_base"] >= 0), q["nom"]
        assert isinstance(q["depend_de"], list)
        # hors_perimetre = fichiers touchés hors de tout préfixe du périmètre
        calcule = [f for f in q["fichiers_touches"]
                   if not any(f.startswith(p) for p in q["perimetre_declare"])]
        assert sorted(calcule) == sorted(q["hors_perimetre"]), q["nom"]


def _statut_attendu(e, equipe):  # évaluée dans l'ordre
    if equipe["statut"] == "terminee":  # CLOTUREE absent de l'instantané : accepté tel quel
        return "terminee"
    agents = [a for a in e["agents"] if a["equipe"] == equipe["nom"]]
    ids = {a["id"] for a in agents}
    if any(a["etat"] in ("attend_autorisation", "attend_reponse") for a in agents) or \
            any(al["type"] == "bloque_au_demarrage" and ids & set(al["agents"]) for al in e["alarmes"]):
        return "bloquee"
    if any(a["etat"] == "travaille" or (a["role"] == "worker" and a["vivant"] is True) for a in agents):
        return "active"
    if agents and all(a["etat"] in ("au_repos", "endormi", "arrete") for a in agents):
        return "au_repos"
    return None


def verifier_statuts_equipes(e):
    for q in e["equipes"]:
        attendu = _statut_attendu(e, q)
        assert attendu is None or q["statut"] == attendu, (q["nom"], q["statut"], attendu)


def verifier_equipes_couverture(e):
    assert {q["statut"] for q in e["equipes"]} == STATUTS
    assert any(q["speciale"] for q in e["equipes"])
    assert any(q["hors_perimetre"] for q in e["equipes"])
    noms = noms_equipes(e)
    for q in e["equipes"]:
        assert q["depend_de"] is not None, q["nom"]
        assert set(q["depend_de"]) <= noms and q["nom"] not in q["depend_de"], q["nom"]
    dep = {q["nom"]: set(q["depend_de"]) for q in e["equipes"]}
    assert "fondation" in dep["observation"]
    assert {"observation", "fondation"} <= dep["hote"]
    assert "hote" in dep["page"]
    for a in e["agents"]:
        if a["equipe"]:
            assert a["equipe"] in noms


def verifier_fil_forme(e):
    attendues = ["id", "horodatage", "de", "a", "nature", "resume", "fichier", "en_attente", "source", "etat_livraison", "non_lu", "preuve"]
    fil = e["fil"]
    assert len(fil) >= 25
    ids = [m["id"] for m in fil]
    assert len(ids) == len(set(ids)), "ids du fil en double"
    for m in fil:
        cles(m, attendues, m.get("id"))
        assert isinstance(m["id"], str)
        assert isinstance(m["en_attente"], bool)
        assert isinstance(m["resume"], str) and m["resume"]
        horo(m["horodatage"])
        assert m["fichier"] is None or (isinstance(m["fichier"], str) and m["fichier"].startswith(".orga/"))
        if m["source"] == "hook":
            assert re.fullmatch(r"evt-\d+", m["id"]), m["id"]
            assert m["nature"] is None
            assert len(m["resume"]) <= 160, m["id"]
            assert {m["de"], m["a"]} == {"utilisateur", "assistant"}
        else:
            assert m["source"] == "registre", m["id"]
        if m["source"] == "hook":
            assert m["etat_livraison"] is None and m["preuve"] is None, m["id"]
        else:  # l'état de livraison est celui de la dernière transition
            assert m["etat_livraison"] in ETATS_LIVRAISON, m["id"]
            assert m["preuve"] is None or isinstance(m["preuve"], dict), m["id"]
        if m["source"] == "registre":
            assert re.fullmatch(r"msg-\d+", m["id"]), m["id"]
            assert m["nature"] in NATURES_FIL, f"{m['id']} : nature {m['nature']!r} inconnue"
            if m["nature"] in ("rapport_utilisateur", "decision_utilisateur", "donnee_utilisateur"):
                assert (m["de"], m["a"]) == ("assistant", "utilisateur"), m["id"]


def verifier_fil_couverture(e):
    fil = e["fil"]
    assert any(m["de"] == "utilisateur" and m["a"] == "assistant" and m["source"] == "hook" for m in fil)
    assert any(m["de"] == "assistant" and m["a"] == "utilisateur" and m["source"] == "hook" for m in fil)
    attente = [m for m in fil if m["en_attente"]]
    assert len(attente) >= 2
    roles = {a["id"]: a["role"] for a in e["agents"]}
    assert any(roles[m["de"]] == "worker" and roles[m["a"]] == "coordinateur" for m in attente)
    assert any(roles[m["de"]] == "coordinateur" and m["a"] == "assistant" for m in attente)
    assert len({m["nature"] for m in fil if m["nature"]}) >= 6
    natures = {m["nature"] for m in fil}
    assert {"travail_pret", "signalement"} <= natures
    assert any(m["nature"] == "signalement" and m["de"] == "coord-verification" and m["a"] == "assistant"
               for m in fil)
    assert sum(1 for m in fil if m["fichier"]) >= 3


def verifier_fil_tri(e):
    h = [horo(m["horodatage"]) for m in e["fil"]]
    assert h == sorted(h, reverse=True)


def verifier_fil_non_lu(e):  # non_lu vaut true si et seulement si…
    for m in e["fil"]:
        assert isinstance(m["non_lu"], bool), m["id"]
        attendu = (m["a"] == "utilisateur" and m["etat_livraison"] == "livre" and m["en_attente"] is False
                   and not m["resume"].startswith("autorisation:"))
        assert m["non_lu"] is attendu, f"{m['id']} : non_lu {m['non_lu']} ≠ {attendu}"


def verifier_attentes(e):
    attendues = ["id", "message_id", "objet", "nature", "titre", "bloque", "depuis", "agent", "equipe", "actions"]
    fil = {m["id"]: m for m in e["fil"]}
    equipes = {q["nom"]: q for q in e["equipes"]}
    agents = {a["id"]: a for a in e["agents"]}
    assert {x["nature"] for x in e["attentes_utilisateur"]} == NATURES_ATTENTE
    ids = [x["id"] for x in e["attentes_utilisateur"]]
    assert len(ids) == len(set(ids))
    for x in e["attentes_utilisateur"]:
        cles(x, attendues, x.get("id"))
        assert x["nature"] in NATURES_ATTENTE
        assert x["titre"] and x["bloque"]
        horo(x["depuis"])
        assert x["agent"] in agents
        # obligatoire pour cloture, sinon l'équipe de l'agent d'origine ou null
        assert x["equipe"] is None or x["equipe"] in equipes, x["id"]
        if x["nature"] == "cloture":
            assert x["equipe"], x["id"]
        elif agents[x["agent"]]["equipe"]:
            assert x["equipe"] == agents[x["agent"]]["equipe"], x["id"]
        accord = x["nature"] == "decision" and (x["objet"] or "").startswith(("fusion:", "chantier:"))
        assert x["actions"] == (["accorder", "refuser"] if accord else ACTIONS_PAR_NATURE[x["nature"]]), x["id"]
        assert x["objet"] is None or isinstance(x["objet"], str), x["id"]
        if x["nature"] == "autorisation":
            assert re.fullmatch(r"perm-[A-Za-z0-9]+", x["id"]) and x["message_id"] is None
        else:
            assert x["message_id"] == int(x["id"].split("-")[1]), x["id"]
            assert x["id"] in fil, f"{x['id']} n'est pas un message du fil"
            assert re.fullmatch(r"msg-\d+", x["id"])
            m = fil[x["id"]]
            assert m["source"] == "registre" and (m["de"], m["a"]) == ("assistant", "utilisateur")
            assert m["nature"] == MESSAGE_PAR_NATURE[x["nature"]], x["id"]
            assert x["depuis"] == fil[x["id"]]["horodatage"]
        if x["nature"] in ("decision", "donnee", "rapport"):  # l'Assistant les porte
            assert x["agent"] == "assistant", x["id"]
        else:
            assert agents[x["agent"]]["role"] in ("coordinateur", "worker"), x["id"]
        if x["nature"] == "autorisation":
            assert agents[x["agent"]]["etat"] == "attend_autorisation"
        if x["nature"] == "cloture":
            assert "demande_cloture" in fil[x["id"]]["resume"]
            eq = agents[x["agent"]]["equipe"]
            assert eq and not equipes[eq]["speciale"], "clôture d'une équipe spéciale"


def verifier_alarmes_forme(e):
    attendues = ["id", "type", "gravite", "destinataire", "agents", "equipes", "depuis", "mesure", "quoi_faire"]
    ids = [a["id"] for a in e["alarmes"]]
    assert len(ids) == len(set(ids))
    for a in e["alarmes"]:
        cles(a, attendues, a.get("id"))
        assert a["type"] in TYPES_ALARME and a["gravite"] in GRAVITES
        assert isinstance(a["agents"], list) and isinstance(a["equipes"], list)
        horo(a["depuis"])
        assert a["mesure"] and a["quoi_faire"]
        assert a["destinataire"] == "utilisateur" or a["destinataire"] in {x["id"] for x in e["agents"]}, a["id"]
        assert a["agents"] or a["equipes"] or a["type"] in ("session_orpheline", "facteur_arrete")  # ni agent ni équipe
    assert {a["type"] for a in e["alarmes"]} == TYPES_ALARME
    assert {a["gravite"] for a in e["alarmes"]} == GRAVITES


def verifier_alarmes_gravite(e):
    grave = {"autorisation_en_attente", "recouvrement", "session_disparue",
             "bloque_au_demarrage", "assistant_sourd", "livraison_echouee", "facteur_arrete"}
    a_voir = {"brouillon", "contexte_plein", "livraison_bloquee", "fin_sans_suite", "hors_perimetre", "action_refusee", "fige",
              "session_orpheline", "gros_poste", "contexte_au_repos"}
    for a in e["alarmes"]:
        if a["type"] == "question_sans_reponse":  # lue dans une obligation de réponse ouverte (> 15 min)
            assert re.fullmatch(r"msg-\d+", a["id"].split(":")[2]) and a["gravite"] == "grave", a["id"]
            continue
        attendue = "grave" if a["type"] in grave else "a_voir" if a["type"] in a_voir else "info"
        assert a["gravite"] == attendue, a["id"]


def verifier_alarmes_id(e):
    agents, equipes = ids_agents(e), noms_equipes(e)
    ids = [a["id"] for a in e["alarmes"]]
    assert len(ids) == len(set(ids))
    for a in e["alarmes"]:
        segments = a["id"].split(":")
        # gros_poste n'a pas de discriminant, les autres en ont un
        attendus = 2 if a["type"] == "gros_poste" else 3
        assert len(segments) == attendus and all(segments), a["id"]
        assert segments[0] == a["type"], a["id"]
        if a["type"] == "recouvrement":  # <équipe A>+<équipe B>, ordre alphabétique
            paire = segments[1].split("+")
            assert len(paire) == 2 and paire == sorted(paire), a["id"]
            assert set(paire) <= equipes and set(paire) == set(a["equipes"]), a["id"]
        elif a["type"] == "session_orpheline":  # <session>:<création epoch>, sans agent ni équipe
            assert segments[1] in {x["nom"] for x in e["sessions_hors_organigramme"]}, a["id"]
            assert a["agents"] == [] and a["equipes"] == [], a["id"]
        elif a["type"] == "facteur_arrete":  # le facteur n'est pas un agent
            assert segments[1] == "facteur" and a["agents"] == [] and a["equipes"] == [], a["id"]
            assert segments[2].isdigit(), a["id"]
        else:
            assert segments[1] in agents | equipes, a["id"]
            assert segments[1] in a["agents"] + a["equipes"], a["id"]
        if attendus == 3:
            _controler_discriminant(e, a, segments[1], segments[2])


def _controler_discriminant(e, a, sujet, disc):
    agents = {x["id"]: x for x in e["agents"]}
    equipes = {q["nom"]: q for q in e["equipes"]}
    t = a["type"]
    if t == "hors_perimetre":
        assert disc in equipes[sujet]["hors_perimetre"], a["id"]  # chemin complet
    elif t == "recouvrement":
        A, B = sujet.split("+")
        assert disc in equipes[A]["fichiers_touches"] and disc in equipes[B]["fichiers_touches"], a["id"]
    elif t == "contexte_plein":
        assert disc == agents[sujet]["modele"], a["id"]
    elif t in ("brouillon", "bloque_au_demarrage"):
        assert disc.isdigit(), a["id"]  # #{window_activity} tmux, secondes epoch
        assert int(disc) == int(horo(a["depuis"]).replace(tzinfo=timezone.utc).timestamp()), a["id"]
        assert horo(a["depuis"]).microsecond == 0, a["id"]
    elif t == "fige":  # #{window_activity} ou dernier événement, secondes epoch
        assert disc.isdigit() and abs(int(disc) - int(horo(a["depuis"]).replace(tzinfo=timezone.utc).timestamp())) <= 1, a["id"]
    elif t == "session_orpheline":  # création de la session, secondes epoch
        assert disc.isdigit() and int(disc) == int(horo(a["depuis"]).replace(tzinfo=timezone.utc).timestamp()), a["id"]
    elif t == "retard_sur_base":
        assert disc == e["projet"]["branche_reference"], a["id"]
    elif t == "session_disparue":
        assert disc == agents[sujet]["session_tmux"], a["id"]
    elif t == "contexte_au_repos":  # début du repos, secondes epoch
        assert disc.isdigit() and int(disc) == int(horo(a["depuis"]).replace(tzinfo=timezone.utc).timestamp()), a["id"]


def verifier_action_refusee(e):
    genere = horo(e["genere_a"])
    refus = [a for a in e["alarmes"] if a["type"] == "action_refusee"]
    assert refus
    for a in refus:
        assert a["gravite"] == "a_voir"
        assert re.fullmatch(r"action_refusee:[a-z0-9-]+:\d+", a["id"]), a["id"]
        assert a["id"].split(":")[1] == a["agents"][0]
        age = (genere - horo(a["depuis"])).total_seconds()
        assert 0 <= age < FENETRE_REFUS_S, a["id"]


def verifier_alarmes_coherence(e):
    agents = {a["id"]: a for a in e["agents"]}
    equipes = {q["nom"]: q for q in e["equipes"]}
    par_type = lambda t: [a for a in e["alarmes"] if a["type"] == t]
    # recouvrement : deux équipes, une arête du graphe
    assert any(x["agent"] == "assistant" for x in e["attentes_utilisateur"])
    assert any(len(a["equipes"]) == 2 for a in par_type("recouvrement"))
    for a in par_type("recouvrement"):
        assert len(a["equipes"]) == 2
    # contexte_plein ⇔ contexte > 60 %
    pleins = {a["id"] for a in agents.values()
              if a["contexte"] and a["contexte"]["tokens"] > SEUIL_CONTEXTE * a["contexte"]["limite"]}
    assert {x for a in par_type("contexte_plein") for x in a["agents"]} == pleins
    # brouillon : dernière activité à plus de 60 s
    for a in par_type("brouillon"):
        assert (horo(e["genere_a"]) - horo(a["depuis"])).total_seconds() > SEUIL_BROUILLON_S, a["id"]
    # bloque_au_demarrage : worker sans événement depuis plus de 2 min, écran au pied de confirmation
    for a in par_type("bloque_au_demarrage"):
        assert (horo(e["genere_a"]) - horo(a["depuis"])).total_seconds() > SEUIL_DEMARRAGE_S, a["id"]
        assert "Enter to confirm · Esc to cancel" in a["mesure"], a["id"]
        for x in a["agents"]:
            assert agents[x]["etat"] == "inconnu" and agents[x]["etat_source"] == "aucun_evenement", x
    # brouillon ⇔ brouillon non nul
    assert {x for a in par_type("brouillon") for x in a["agents"]} == \
        {a["id"] for a in agents.values() if a["brouillon"]}
    # hors_perimetre ⇔ équipe avec hors_perimetre non vide
    assert {x for a in par_type("hors_perimetre") for x in a["equipes"]} == \
        {q["nom"] for q in equipes.values() if q["hors_perimetre"]}
    # retard_sur_base ⇔ retard > 0
    assert {x for a in par_type("retard_sur_base") for x in a["equipes"]} == \
        {q["nom"] for q in equipes.values() if q["retard_sur_base"] > 0}
    # autorisation_en_attente ⇔ attente de nature autorisation, agent en attend_autorisation
    for a in par_type("autorisation_en_attente"):
        assert all(agents[x]["etat"] == "attend_autorisation" for x in a["agents"])
    assert {x for a in par_type("autorisation_en_attente") for x in a["agents"]} == \
        {x["agent"] for x in e["attentes_utilisateur"] if x["nature"] == "autorisation"}
    # session_disparue : agent arrêté d'une équipe non terminée
    for a in par_type("session_disparue"):
        for x in a["agents"]:
            assert agents[x]["etat"] == "arrete" and agents[x]["tache"]
        assert all(equipes[q]["statut"] != "terminee" for q in a["equipes"])
    # fin_sans_suite : le worker nommé existe et n'est pas à l'arrêt déclaré
    for a in par_type("fin_sans_suite"):
        assert all(agents[x]["role"] == "worker" for x in a["agents"]), a["id"]
    # facteur_arrete : l'alarme et le battement disent la même chose
    assert bool(par_type("facteur_arrete")) == e["facteur"]["arrete"]
    # question_sans_reponse : un message en attente cité dans l'id
    fil = {m["id"]: m for m in e["fil"]}
    for a in par_type("question_sans_reponse"):
        m = fil[a["id"].split(":")[2]]
        assert m["en_attente"] and m["nature"] == "question" and m["de"] in a["agents"]
        assert m["horodatage"] == a["depuis"]
        assert any(f["id"] == m["id"] for f in [{"id": "msg-%d" % d["id"]} for ag in e["agents"] for d in ag["dettes"]]), a["id"]
    # fige : agent « travaille », sans signe de vie depuis plus de 15 min
    for a in par_type("fige"):
        assert len(a["agents"]) == 1 and agents[a["agents"][0]]["etat"] == "travaille", a["id"]
        assert (horo(e["genere_a"]) - horo(a["depuis"])).total_seconds() > 15 * 60, a["id"]
        assert horo(agents[a["agents"][0]]["etat_depuis"]) <= horo(a["depuis"]), a["id"]
    # session_orpheline : une session listée, ouverte depuis plus de 60 min
    for a in par_type("session_orpheline"):
        session = next(x for x in e["sessions_hors_organigramme"] if x["nom"] == a["id"].split(":")[1])
        assert session["depuis"] == a["depuis"], a["id"]
        assert (horo(e["genere_a"]) - horo(a["depuis"])).total_seconds() > 60 * 60, a["id"]
    # aucune alarme sur une équipe terminée
    for a in e["alarmes"]:
        assert all(equipes[q]["statut"] != "terminee" for q in a["equipes"])


def verifier_sessions_et_decisions(e):
    """Sessions hors organigramme et décisions récentes."""
    sessions = e["sessions_hors_organigramme"]
    assert isinstance(sessions, list) and len(sessions) == 2
    for x in sessions:
        cles(x, ["nom", "depuis", "activite"], "session")
        assert x["nom"].startswith(e["projet"]["prefixe"] + "-")
        horo(x["depuis"]), horo(x["activite"])
        assert horo(x["depuis"]) <= horo(x["activite"]) <= horo(e["genere_a"])
        assert x["nom"] not in {a["session_tmux"] for a in e["agents"]}
    assert sum(1 for a in e["alarmes"] if a["type"] == "session_orpheline") == 1
    decisions = e["decisions_recentes"]
    assert isinstance(decisions, list) and 5 <= len(decisions) <= 10
    for d in decisions:
        cles(d, ["date", "titre"], "décision")
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", d["date"]) and d["titre"]
    assert [d["date"] for d in decisions] == sorted((d["date"] for d in decisions), reverse=True)


def verifier_flux(e):
    """Flux, arêtes, ordres, facteur."""
    ids = [r["id"] for r in e["flux"]]
    assert ids == sorted(ids) and len(ids) == len(set(ids)), "flux : de la plus ancienne à la plus récente"
    agents = ids_agents(e)
    for r in e["flux"]:
        cles(r, ["id", "de", "a", "nature", "objet", "resume", "transitions", "etat", "debiteur", "echeance"], r.get("id"))
        assert isinstance(r["id"], int) and r["de"] in agents and r["a"] in agents and r["nature"] in NATURES_FIL
        assert r["transitions"] and r["etat"] == r["transitions"][-1]["etat"] and r["etat"] in ETATS_LIVRAISON
        for t in r["transitions"]:
            cles(t, ["etat", "horodatage", "voie", "auteur"], "transition")
            assert t["etat"] in ETATS_LIVRAISON
            horo(t["horodatage"])
        assert r["transitions"][0]["etat"] == "inscrit" and r["transitions"][0]["auteur"] == r["de"]
        assert (r["debiteur"] is None) == (r["echeance"] is None)
        if r["echeance"]:
            horo(r["echeance"])
    for x in e["aretes"]:
        cles(x, ["de", "a", "en_file", "livre", "ouvertes", "total_15min"], "arête")
        assert x["de"] in agents and x["a"] in agents
        assert all(isinstance(x[k], int) and x[k] >= 0 for k in ("en_file", "livre", "ouvertes", "total_15min"))
        assert x["en_file"] + x["livre"] + x["ouvertes"] + x["total_15min"] > 0, "couple sans activité omis"
    assert len({(x["de"], x["a"]) for x in e["aretes"]}) == len(e["aretes"])
    for o in e["ordres"]:
        cles(o, ["id", "auteur", "verbe", "cible", "etat"], "ordre")
        assert o["verbe"] in ("lancer", "terminer", "compacter", "capturer") and o["etat"] in ("en_file", "execute", "echec")
    f = e["facteur"]
    cles(f, ["battement", "age_s", "arrete"], "facteur")
    assert isinstance(f["arrete"], bool)
    if f["battement"] is None:
        assert f["age_s"] is None and f["arrete"]
    else:
        horo(f["battement"])
        assert f["arrete"] == (f["age_s"] > 30), "seuil = PEREMPTION_BATTEMENT (30 s)"
    assert "cime" not in agents


def verifier_consommation(e):
    """Consommation de jetons (agents, racine, gros postes) et ses deux alarmes."""
    racine = e["consommation"]
    cles(racine, ["15min", "60min", "gros_postes"], "consommation")
    for f in ("15min", "60min"):
        cles(racine[f], ["lus", "ecrits", "tours"], f"consommation.{f}")
    agents = {a["id"]: a for a in e["agents"]}
    mesures = {}
    for a in e["agents"]:
        c = a["consommation"]
        if a["role"] == "utilisateur":
            assert c is None, "utilisateur : consommation null"
        if c is None:
            continue
        cles(c, ["15min", "60min", "source"], f"consommation de {a['id']}")
        assert c["source"] in ("transcript", "transcript:cwd"), a["id"]
        for f in ("15min", "60min"):
            cles(c[f], ["lus", "ecrits", "tours", "contexte_moyen", "dont_sous_agents"], f"{a['id']}.{f}")
            for k in ("lus", "ecrits", "tours", "dont_sous_agents"):
                assert isinstance(c[f][k], int) and c[f][k] >= 0, (a["id"], f, k)
            assert c[f]["dont_sous_agents"] <= c[f]["lus"], (a["id"], f)
            if c[f]["tours"] == 0:  # pas de réponse principale : pas de contexte moyen, jamais 0
                assert c[f]["contexte_moyen"] is None, (a["id"], f)
            else:
                assert isinstance(c[f]["contexte_moyen"], int) and c[f]["contexte_moyen"] >= 0, (a["id"], f)
        mesures[a["id"]] = c
    assert any(c["15min"]["dont_sous_agents"] > 0 for c in mesures.values())  # au moins un agent avec sous-agents
    assert any(a["consommation"] is None and a["role"] != "utilisateur" for a in e["agents"])  # sans transcript
    # la racine est la somme des agents mesurés
    for f in ("15min", "60min"):
        for k in ("lus", "ecrits", "tours"):
            assert racine[f][k] == sum(c[f][k] for c in mesures.values()), (f, k)
    total = racine["15min"]["lus"]
    # gros postes : les 5 plus gros par lus_15min, parts cohérentes avec les lus
    postes = racine["gros_postes"]
    assert 1 <= len(postes) <= 5
    attendus = sorted(((aid, c["15min"]["lus"]) for aid, c in mesures.items() if c["15min"]["lus"] > 0),
                      key=lambda x: -x[1])[:5]
    assert [(p["agent"], p["lus_15min"]) for p in postes] == attendus
    for p in postes:
        cles(p, ["agent", "lus_15min", "part_15min"], "gros poste")
        assert p["part_15min"] == round(p["lus_15min"] / total, 3), p["agent"]
    # alarme gros_poste : plus de 5 M lus en 15 min, ou plus de 40 % avec au moins 1 M du projet
    attendus_gros = {aid for aid, c in mesures.items()
                     if c["15min"]["lus"] > 5_000_000 or (c["15min"]["lus"] / total > 0.40 and total >= 1_000_000)}
    gros = [a for a in e["alarmes"] if a["type"] == "gros_poste"]
    assert {a["agents"][0] for a in gros} == attendus_gros
    assert all(a["gravite"] == "a_voir" and a["id"] == f"gros_poste:{a['agents'][0]}" for a in gros)
    # alarme contexte_au_repos : au repos depuis plus de 10 min, contexte au-dessus de 150 k
    genere = horo(e["genere_a"])
    attendus_repos = {a["id"] for a in e["agents"] if a["etat"] == "au_repos" and a["contexte"]
                      and a["contexte"]["tokens"] > 150_000
                      and (genere - horo(a["etat_depuis"])).total_seconds() > 10 * 60}
    repos = [a for a in e["alarmes"] if a["type"] == "contexte_au_repos"]
    assert {a["agents"][0] for a in repos} == attendus_repos and attendus_repos
    for a in repos:
        assert a["gravite"] == "a_voir" and a["quoi_faire"] == "À compacter avant son prochain tour.", a["id"]
        assert a["depuis"] == agents[a["agents"][0]]["etat_depuis"], a["id"]


def verifier_references(e):
    agents, equipes = ids_agents(e), noms_equipes(e)
    for a in e["agents"]:
        assert a["parent"] is None or a["parent"] in agents
        assert a["equipe"] is None or a["equipe"] in equipes
    for m in e["fil"]:
        assert m["de"] in agents and m["a"] in agents
    for x in e["attentes_utilisateur"]:
        assert x["agent"] in agents
    for al in e["alarmes"]:
        assert set(al["agents"]) <= agents and set(al["equipes"]) <= equipes
    for q in e["equipes"]:
        assert set(q["depend_de"]) <= equipes


def verifier_horodatages(e):
    genere = horo(e["genere_a"])

    def parcourir(v):
        if isinstance(v, dict):
            for cle, val in v.items():
                if cle in ("horodatage", "depuis", "etat_depuis", "capture_a") and isinstance(val, str):
                    assert horo(val) <= genere, f"{cle}={val} postérieur à genere_a"
                parcourir(val)
        elif isinstance(v, list):
            for x in v:
                parcourir(x)

    parcourir(e)


def verifier_confidentialite(donnees):
    brut = json.dumps(donnees, ensure_ascii=False)
    assert "@" not in brut
    for m in re.finditer(r"/(?:Users|home)/[^/\s\"']*", brut):
        assert m.group(0) == "/home/exemple", m.group(0)
    assert "lorem" not in brut.lower()


def verifier_journal(j):  # api 1.6 : {"lignes": [...]}, du plus récent au plus ancien
    assert isinstance(j, dict) and list(j) == ["lignes"], "journal : {\"lignes\": [...]} attendu"
    lignes = j["lignes"]
    assert isinstance(lignes, list) and 8 <= len(lignes) <= 12
    ids = [x["id"] for x in lignes]
    assert all(type(i) is int for i in ids), "id entier attendu"
    assert len(ids) == len(set(ids))
    dates = [horo(x["horodatage"]) for x in lignes]
    assert dates == sorted(dates, reverse=True), "journal : du plus récent au plus ancien"
    for x in lignes:
        cles(x, ["id", "horodatage", "auteur", "action", "cible", "details", "resultat"], x.get("id"))
        assert x["auteur"] in ("utilisateur", "assistant")
        assert x["action"] in ACTIONS_JOURNAL
        assert isinstance(x["cible"], str) and re.fullmatch(r"perm-[A-Za-z0-9-]+|msg-\d+|equipe:[a-z0-9-]+", x["cible"]), x["cible"]
        assert isinstance(x["details"], dict)
        assert x["resultat"] in ("ok", "refuse") or re.fullmatch(r"erreur: .+", x["resultat"])
    assert any(x["resultat"] == "refuse" for x in lignes)
    assert any(x["resultat"].startswith("erreur: ") for x in lignes)


def verifier_journal_lu(j, e):
    lus = [x for x in j["lignes"] if x["action"] == "lu"]
    assert lus, "aucune ligne « lu »"
    fil = {m["id"]: m for m in e["fil"]}
    attendus = {x["id"] for x in e["attentes_utilisateur"]}
    for x in lus:
        assert x["cible"] in fil and fil[x["cible"]]["nature"] == "rapport_utilisateur", x["cible"]
        assert x["cible"] not in attendus, "un rapport lu ne doit plus être une attente"


def verifier_journal_horodatage(j, e):
    genere = horo(e["genere_a"])
    assert all(horo(x["horodatage"]) <= genere for x in j["lignes"])


def verifier_terminaux(t, e):
    attendus = {a["id"] for a in e["agents"] if a["session_tmux"]}
    assert set(t) == attendus
    genere = horo(e["genere_a"])
    etats = {a["id"]: a["etat"] for a in e["agents"]}
    for cle, v in t.items():
        cles(v, ["texte", "capture_a"], cle)
        assert 20 <= len(v["texte"].splitlines()) <= 40, cle
        assert horo(v["capture_a"]) <= genere
        if etats[cle] == "attend_autorisation":
            assert "Do you want to proceed?" in v["texte"]
    for al in e["alarmes"]:  # la dernière ligne non vide de l'écran est le pied
        if al["type"] == "bloque_au_demarrage":
            for x in al["agents"]:
                dernieres = [l for l in t[x]["texte"].splitlines() if l.strip()]
                assert dernieres[-1].strip() == "Enter to confirm · Esc to cancel", x


# ------------------------------------------------------------------ tests sur les vraies données

@pytest.fixture(scope="module")
def etat():
    return charger("exemple-etat.json")


@pytest.fixture(scope="module")
def journal():
    return charger("exemple-journal.json")


@pytest.fixture(scope="module")
def terminaux():
    return charger("exemple-terminaux.json")


def test_racine(etat): verifier_racine(etat)
def test_projet(etat): verifier_projet(etat)
def test_sources(etat): verifier_sources(etat)
def test_agents_forme(etat): verifier_agents_forme(etat)
def test_agents_couverture(etat): verifier_agents_couverture(etat)
def test_source_en_echec_donne_null(etat): verifier_source_en_echec(etat)
def test_equipes(etat): verifier_equipes(etat)
def test_equipes_couverture(etat): verifier_equipes_couverture(etat)
def test_fil_forme(etat): verifier_fil_forme(etat)
def test_fil_couverture(etat): verifier_fil_couverture(etat)
def test_fil_trie_du_plus_recent_au_plus_ancien(etat): verifier_fil_tri(etat)
def test_fil_non_lu(etat): verifier_fil_non_lu(etat)
def test_attentes(etat): verifier_attentes(etat)
def test_alarmes_forme(etat): verifier_alarmes_forme(etat)
def test_alarmes_gravite(etat): verifier_alarmes_gravite(etat)
def test_alarmes_id(etat): verifier_alarmes_id(etat)
def test_utilisateur(etat): verifier_utilisateur(etat)
def test_action_refusee(etat): verifier_action_refusee(etat)
def test_alarmes_coherence(etat): verifier_alarmes_coherence(etat)
def test_sessions_et_decisions(etat): verifier_sessions_et_decisions(etat)
def test_flux(etat): verifier_flux(etat)
def test_references(etat): verifier_references(etat)
def test_horodatages(etat): verifier_horodatages(etat)
def test_confidentialite_etat(etat): verifier_confidentialite(etat)
def test_confidentialite_journal(journal): verifier_confidentialite(journal)
def test_confidentialite_terminaux(terminaux): verifier_confidentialite(terminaux)
def test_journal(journal): verifier_journal(journal)
def test_journal_horodatage(journal, etat): verifier_journal_horodatage(journal, etat)
def test_journal_lu(journal, etat): verifier_journal_lu(journal, etat)
def test_terminaux(terminaux, etat): verifier_terminaux(terminaux, etat)


# ------------------------------------------------------------------ preuve par mutation
# (nom, vérification, jeu de données, mutation appliquée à une copie en mémoire)

def agent(e, i): return next(a for a in e["agents"] if a["id"] == i)
def equipe(e, n): return next(q for q in e["equipes"] if q["nom"] == n)
def alarme(e, t): return next(a for a in e["alarmes"] if a["type"] == t)
def attente(e, n): return next(x for x in e["attentes_utilisateur"] if x["nature"] == n)


def _fil_hook(e): return next(m for m in e["fil"] if m["source"] == "hook")
def _fil_registre(e): return next(m for m in e["fil"] if m["source"] == "registre")


def _sans_alarme(type_):
    def f(e):
        e["alarmes"] = [a for a in e["alarmes"] if a["type"] != type_]
    return f


def _set(getter, cle, valeur):
    def f(e):
        getter(e)[cle] = valeur
    return f


def _fil_trie_casse(e):
    e["fil"][0], e["fil"][-1] = e["fil"][-1], e["fil"][0]


def _perimetre_ignore(e):
    equipe(e, "hote")["hors_perimetre"] = []


def _tous_au_repos(e):
    for a in e["agents"]:
        if a["etat"] == "attend_reponse":
            a["etat"] = "au_repos"


def _plus_de_brouillon(e):
    agent(e, "coord-page")["brouillon"] = None


def _contexte_bas(e):
    agent(e, "assistant")["contexte"]["tokens"] = 100000


def _fil_en_attente_efface(e):
    for m in e["fil"]:
        m["en_attente"] = False


def _fil_court(e):
    e["fil"] = e["fil"][:10]


def _id_fil_entier(e):
    _fil_registre(e)["id"] = 42


def _id_fil_en_double(e):
    e["fil"][1]["id"] = e["fil"][0]["id"]


def _resume_long(e):
    _fil_hook(e)["resume"] = "x" * 161


def _hook_avec_nature(e):
    _fil_hook(e)["nature"] = "question"


def _registre_sans_nature(e):
    _fil_registre(e)["nature"] = None


def _fichier_absolu(e):
    next(m for m in e["fil"] if m["fichier"])["fichier"] = "/home/exemple/x.md"


def _cloture_speciale(e):
    attente(e, "cloture")["agent"] = "coord-verification"


def _attente_id_inconnu(e):
    attente(e, "decision")["id"] = "msg-9999"


def _perm_mal_nomme(e):
    attente(e, "autorisation")["id"] = "msg-41"


def _attente_manquante(e):
    e["attentes_utilisateur"] = [x for x in e["attentes_utilisateur"] if x["nature"] != "rapport"]


def _refus_ancien(e):
    alarme(e, "action_refusee")["depuis"] = "2026-10-07T12:00:00.000Z"


def _refus_id(e):
    alarme(e, "action_refusee")["id"] = "refus-1"


def _refus_grave(e):
    alarme(e, "action_refusee")["gravite"] = "grave"


def _recouvrement_une_equipe(e):
    alarme(e, "recouvrement")["equipes"] = ["hote"]


def _alarme_sans_quoi_faire(e):
    alarme(e, "brouillon")["quoi_faire"] = ""


def _alarme_inconnue(e):
    alarme(e, "brouillon")["type"] = "inventee"


def _un_statut_en_moins(e):
    equipe(e, "cadrage")["statut"] = "active"


def _cloturee_le_absente(e):
    equipe(e, "cadrage")["cloturee_le"] = None


def _cloturee_le_sur_active(e):
    equipe(e, "page")["cloturee_le"] = "2026-10-07T06:58:11.123Z"


def _depend_inconnu(e):
    equipe(e, "page")["depend_de"] = ["nulle-part"]


def _depend_null(e):
    equipe(e, "page")["depend_de"] = None


def _parent_inconnu(e):
    agent(e, "worker-page-donnees")["parent"] = "coord-fantome"


def _de_inconnu(e):
    e["fil"][3]["de"] = "fantome"


def _alarme_agent_inconnu(e):
    alarme(e, "brouillon")["agents"] = ["fantome"]


def _alarme_equipe_inconnue(e):
    alarme(e, "recouvrement")["equipes"] = ["hote", "fantome"]


def _futur(e):
    e["fil"][0]["horodatage"] = "2026-10-07T14:00:00.000Z"


def _horo_sans_z(e):
    e["fil"][0]["horodatage"] = "2026-10-07T13:00:00"


def _email(e):
    agent(e, "assistant")["derniere_phrase"] = "Écris à quelqu'un@exemple.fr"


def _chemin_perso(e):
    equipe(e, "page")["worktree"] = "/home/personne/projet-boutique-page"


def _cout_zero(e):
    agent(e, "assistant")["cout_usd_estime"] = 0


def _cout_faux(e):
    agent(e, "coord-page")["cout_usd_estime"] = False


def _toutes_sources_ok(e):
    for s in e["sources"]:
        s["ok"] = True
        s.pop("erreur", None)


def _source_sans_erreur(e):
    next(s for s in e["sources"] if not s["ok"]).pop("erreur")


def _vivant_false_mais_repos(e):
    agent(e, "worker-observation-git")["vivant"] = True


def _cle_en_trop(e):
    e["agents"][0]["intrus"] = 1


def _version(e):
    e["version"] = 1


def _duree_trop_longue(e):
    e["duree_collecte_ms"] = 2500


def _etape_cochee(e):
    e["projet"]["etapes"][1]["atteinte"] = True


def _etape_renommee(e):
    e["projet"]["etapes"][2]["nom"] = "Autre chose"


def _etat_inconnu(e):
    agent(e, "assistant")["etat"] = "dort"


def _role_inconnu(e):
    agent(e, "assistant")["role"] = "stagiaire"


def _phrase_longue(e):
    agent(e, "assistant")["derniere_phrase"] = "x" * 301


def _contexte_depasse(e):
    agent(e, "assistant")["contexte"]["tokens"] = 2000000


def _hors_perimetre_faux(e):
    equipe(e, "page")["hors_perimetre"] = ["src/cime/page/x.py"]


def _commit_mal_forme(e):
    equipe(e, "page")["commit"] = "zzz"


def _alarme_terminee(e):
    alarme(e, "retard_sur_base")["equipes"] = ["cadrage"]


def _disparue_vivant(e):
    agent(e, "worker-observation-git")["etat"] = "au_repos"
    agent(e, "worker-observation-git")["vivant"] = None


def _question_non_en_attente(e):
    for m in e["fil"]:
        if m["de"] == "worker-observation-tmux":
            m["en_attente"] = False


def _journal_sans_refus(j):
    for x in j["lignes"]:
        if x["resultat"] == "refuse":
            x["resultat"] = "ok"


def _journal_sans_erreur(j):
    for x in j["lignes"]:
        if x["resultat"].startswith("erreur"):
            x["resultat"] = "ok"


def _journal_action(j):
    j["lignes"][0]["action"] = "pousser"


def _journal_court(j):
    del j["lignes"][3:]


def _journal_futur(j):
    j["lignes"][0]["horodatage"] = "2026-10-08T00:00:00.000Z"


def _journal_resultat(j):
    j["lignes"][0]["resultat"] = "erreur:"


def _journal_liste_nue(j):
    j["lignes"], nue = None, j["lignes"]
    j.clear()
    j["liste"] = nue


def _journal_croissant(j):
    j["lignes"].reverse()


def _journal_id_texte(j):
    j["lignes"][0]["id"] = "j-12"


def _journal_id_double(j):
    j["lignes"][1]["id"] = j["lignes"][0]["id"]


def _journal_cible_hors_format(j):
    j["lignes"][0]["cible"] = "etapes.md"


def _terminal_court(t):
    k = next(iter(t))
    t[k]["texte"] = "une ligne"


def _terminal_manquant(t):
    del t["assistant"]


def _terminal_sans_demande(t):
    t["coord-page"]["texte"] = "\n".join(["ligne"] * 25)


def _terminal_sans_pied(t):
    t["worker-hote-tests"]["texte"] += "\n> "


def _terminal_futur(t):
    t["assistant"]["capture_a"] = "2026-10-08T00:00:00.000Z"


def _terminal_pii(t):
    t["assistant"]["texte"] += "\n/home/personne/secret"


def _nature_hors_liste(e):
    _fil_registre(e)["nature"] = "tache"


def _nature_rapport(e):
    _fil_registre(e)["nature"] = "rapport"


def _plus_de_signalement(e):
    for m in e["fil"]:
        if m["nature"] == "signalement":
            m["nature"] = "compte_rendu"


def _plus_de_travail_pret(e):
    for m in e["fil"]:
        if m["nature"] == "travail_pret":
            m["nature"] = "compte_rendu"


def _rapport_utilisateur_mal_dirige(e):
    next(m for m in e["fil"] if m["nature"] == "rapport_utilisateur")["de"] = "coord-page"


def _actions_rapport(e):
    attente(e, "rapport")["actions"] = []


def _actions_decision(e):
    attente(e, "decision")["actions"] = ["autoriser"]


def _actions_cloture(e):
    attente(e, "cloture")["actions"] = ["cloturer", "refuser"]


def _attente_message_mauvaise_nature(e):
    m = next(m for m in e["fil"] if m["id"] == attente(e, "donnee")["id"])
    m["nature"] = "rapport_utilisateur"


def _attente_message_mal_dirige(e):
    m = next(m for m in e["fil"] if m["id"] == attente(e, "decision")["id"])
    m["de"], m["a"] = "coord-hote", "assistant"


def _source_hooks(e):
    e["sources"][1]["nom"] = "hooks"


def _source_en_double(e):
    e["sources"][1]["nom"] = "structure"


def _utilisateur_modele(e):
    agent(e, "utilisateur")["modele"] = "claude-opus-5-5"


def _utilisateur_vivant_false(e):
    agent(e, "utilisateur")["vivant"] = False


def _utilisateur_etat(e):
    agent(e, "utilisateur")["etat"] = "au_repos"


def _utilisateur_contexte(e):
    agent(e, "utilisateur")["contexte"] = {"tokens": 0, "limite": 1, "source": "transcript"}


def _decision_agent_coord(e):
    attente(e, "decision")["agent"] = "coord-hote"


def _cloture_agent_assistant(e):
    attente(e, "cloture")["agent"] = "assistant"


def _aucune_attente_assistant(e):
    for x in e["attentes_utilisateur"]:
        if x["agent"] == "assistant":
            x["agent"] = "coord-verification"


def _alarme_id_court(e):
    alarme(e, "brouillon")["id"] = "brouillon:coord-page"


def _alarme_id_type(e):
    alarme(e, "brouillon")["id"] = "contexte_plein:coord-page:1"


def _alarme_id_inconnu(e):
    alarme(e, "brouillon")["id"] = "brouillon:fantome:1"


def _alarme_id_double(e):
    alarme(e, "contexte_plein")["id"] = alarme(e, "brouillon")["id"].replace("brouillon:coord-page", "contexte_plein:assistant")
    alarme(e, "contexte_plein")["id"] = alarme(e, "retard_sur_base")["id"]


def _alarme_id_hors_alarme(e):
    alarme(e, "brouillon")["id"] = "brouillon:assistant:1"


def _id_recouvrement_desordre(e):
    alarme(e, "recouvrement")["id"] = "recouvrement:observation+hote:src/cime/observation/tmux.py"


def _id_hors_perimetre_nom_court(e):
    alarme(e, "hors_perimetre")["id"] = "hors_perimetre:hote:tmux.py"


def _id_contexte_seuil(e):
    alarme(e, "contexte_plein")["id"] = "contexte_plein:assistant:seuil-60"


def _id_brouillon_horodatage(e):
    alarme(e, "brouillon")["id"] = "brouillon:coord-page:2026-10-07T125511Z"


def _statut_contraire(e):
    equipe(e, "observation")["statut"] = "active"


def _statut_repos_a_tort(e):
    equipe(e, "verification")["statut"] = "au_repos"


def _demarrage_sans_agent_bloque(e):
    agent(e, "worker-hote-tests")["etat"] = "travaille"


def _brouillon_recent(e):
    a = alarme(e, "brouillon")
    a["depuis"] = "2026-10-07T13:03:41.000Z"
    agent(e, "coord-page")["brouillon"]["depuis"] = a["depuis"]


def _demarrage_recent(e):
    alarme(e, "bloque_au_demarrage")["depuis"] = "2026-10-07T13:03:00.000Z"


def _demarrage_sans_pied(e):
    alarme(e, "bloque_au_demarrage")["mesure"] = "Aucun événement depuis 23 min."


def _demarrage_gravite(e):
    alarme(e, "bloque_au_demarrage")["gravite"] = "a_voir"


def _demarrage_id_epoch(e):
    a = alarme(e, "bloque_au_demarrage")
    a["id"] = "bloque_au_demarrage:worker-hote-tests:1791376861"


def _demarrage_id_texte(e):
    alarme(e, "bloque_au_demarrage")["id"] = "bloque_au_demarrage:worker-hote-tests:2026-10-07"


# équipe d'une attente, questions écrites, agent figé, avance sur la base
def _cloture_sans_equipe(e): next(x for x in e["attentes_utilisateur"] if x["nature"] == "cloture")["equipe"] = None
def _attente_equipe_inconnue(e): e["attentes_utilisateur"][0]["equipe"] = "inexistante"
def _avance_negative(e): equipe(e, "page")["en_avance_sur_base"] = -1
def _avance_texte(e): equipe(e, "page")["en_avance_sur_base"] = "3"
def _fige_agent_au_repos(e): agent(e, "coord-verification")["etat"] = "au_repos"
def _fige_recent(e):
    a = next(a for a in e["alarmes"] if a["type"] == "fige")
    a["depuis"] = e["genere_a"]
def _fige_grave(e): next(a for a in e["alarmes"] if a["type"] == "fige")["gravite"] = "grave"
def _fige_id_texte(e): next(a for a in e["alarmes"] if a["type"] == "fige")["id"] = "fige:coord-verification:hier"

def _session_une_seule(e): del e["sessions_hors_organigramme"][1]
def _session_hors_prefixe(e): e["sessions_hors_organigramme"][0]["nom"] = "autre-essai"
def _session_connue(e): e["sessions_hors_organigramme"][0]["nom"] = "cc-assistant"
def _orpheline_avec_agent(e): next(a for a in e["alarmes"] if a["type"] == "session_orpheline")["agents"] = ["assistant"]
def _orpheline_recente(e): next(a for a in e["alarmes"] if a["type"] == "session_orpheline")["depuis"] = e["genere_a"]
def _orpheline_gravite(e): next(a for a in e["alarmes"] if a["type"] == "session_orpheline")["gravite"] = "grave"
def _orpheline_id_epoch(e): next(a for a in e["alarmes"] if a["type"] == "session_orpheline")["id"] = "session_orpheline:cc-essai-tmux:hier"
def _decisions_desordre(e): e["decisions_recentes"].reverse()
def _decisions_date_texte(e): e["decisions_recentes"][0]["date"] = "hier"
def _decisions_nulles(e): e["decisions_recentes"] = None


def _cle_retiree(cle):
    def f(e):
        del agent(e, "assistant")[cle]
    return f


def _utilisateur_consommation(e): agent(e, "utilisateur")["consommation"] = copy.deepcopy(agent(e, "assistant")["consommation"])
def _racine_sans_postes(e): del e["consommation"]["gros_postes"]
def _fenetre_sans_tours(e): del e["consommation"]["60min"]["tours"]
def _racine_somme_fausse(e): e["consommation"]["15min"]["lus"] += 1


def _sous_agents_trop(e):
    c = agent(e, "coord-observation")["consommation"]["15min"]
    c["dont_sous_agents"] = c["lus"] + 1


def _aucun_sous_agent(e):
    for a in e["agents"]:
        if a["consommation"]:
            a["consommation"]["15min"]["dont_sous_agents"] = 0


def _source_conso_inconnue(e): agent(e, "assistant")["consommation"]["source"] = "cache"


def _contexte_sans_tours(e): agent(e, "coord-fondation")["consommation"]["15min"]["contexte_moyen"] = 100


def _six_gros_postes(e): e["consommation"]["gros_postes"] = e["consommation"]["gros_postes"] * 2


def _gros_postes_desordre(e): e["consommation"]["gros_postes"].reverse()


def _part_fausse(e): e["consommation"]["gros_postes"][0]["part_15min"] = 0.9


def _gros_poste_zero(e):
    e["consommation"]["gros_postes"].append({"agent": "coord-cadrage", "lus_15min": 0, "part_15min": 0.0})


def _gros_poste_faux(e):
    alarme(e, "gros_poste")["agents"] = ["assistant"]
    alarme(e, "gros_poste")["id"] = "gros_poste:assistant"


def _repos_sans_contexte(e): agent(e, "coord-fondation")["contexte"] = None


def _gros_poste_grave(e): alarme(e, "gros_poste")["gravite"] = "grave"
def _gros_poste_id_disc(e): alarme(e, "gros_poste")["id"] = "gros_poste:coord-observation:1"
def _repos_id_epoch(e): alarme(e, "contexte_au_repos")["id"] = "contexte_au_repos:coord-fondation:hier"

def _flux_desordre(e): e["flux"].reverse()
def _flux_etat_incoherent(e): e["flux"][0]["etat"] = "abandonne"
def _flux_sans_inscrit(e): del e["flux"][0]["transitions"][0]
def _flux_echeance_seule(e): e["flux"][-1]["echeance"] = None if e["flux"][-1]["echeance"] else "2026-10-07T13:00:00.000Z"
def _arete_vide(e): e["aretes"].append({"de": "utilisateur", "a": "assistant", "en_file": 0, "livre": 0, "ouvertes": 0, "total_15min": 0})
def _ordre_verbe(e): e["ordres"][0]["verbe"] = "ecrire"
def _facteur_incoherent(e): e["facteur"]["arrete"] = not e["facteur"]["arrete"]
def _facteur_jamais_battu(e): e["facteur"] = {"battement": None, "age_s": 3, "arrete": True}
def _cime_agent(e): e["agents"].append({**e["agents"][0], "id": "cime"})
def _action_accord_perdue(e): next(x for x in e["attentes_utilisateur"] if x["objet"] == "fusion:page:abc1234")["actions"] = ["trancher"]
def _fil_etat_livraison_inconnu(e): _fil_registre(e)["etat_livraison"] = "perdu"
def _fil_hook_avec_preuve(e): _fil_hook(e)["preuve"] = {"voie": "tmux"}
def _alarme_sans_destinataire(e): e["alarmes"][0]["destinataire"] = "personne"
def _facteur_alarme_sans_arret(e): e["facteur"]["arrete"] = False
def _non_lu_sur_autorisation(e): next(m for m in e["fil"] if m["id"] == "msg-67")["non_lu"] = True
def _non_lu_efface(e): next(m for m in e["fil"] if m["id"] == "msg-66")["non_lu"] = False
def _non_lu_absent(e): e["fil"][0].pop("non_lu")
def _non_lu_chaine(e): e["fil"][0]["non_lu"] = "true"


ETAT_MUTATIONS = [
    ("flux: dans le désordre", verifier_flux, _flux_desordre),
    ("flux: état ≠ dernière transition", verifier_flux, _flux_etat_incoherent),
    ("flux: sans transition inscrit", verifier_flux, _flux_sans_inscrit),
    ("flux: débiteur sans échéance", verifier_flux, _flux_echeance_seule),
    ("flux: arête sans activité", verifier_flux, _arete_vide),
    ("flux: verbe d'ordre inconnu", verifier_flux, _ordre_verbe),
    ("flux: facteur arrêté à tort", verifier_flux, _facteur_incoherent),
    ("flux: facteur jamais battu mais âgé", verifier_flux, _facteur_jamais_battu),
    ("flux: cime est un agent", verifier_flux, _cime_agent),
    ("attentes: accord de fusion sans accorder", verifier_attentes, _action_accord_perdue),
    ("fil: état de livraison inconnu", verifier_fil_forme, _fil_etat_livraison_inconnu),
    ("fil: non_lu sur une autorisation", verifier_fil_non_lu, _non_lu_sur_autorisation),
    ("fil: non_lu absent d'une entrée", verifier_fil_forme, _non_lu_absent),
    ("fil: non_lu faux sur un message à lire", verifier_fil_non_lu, _non_lu_efface),
    ("fil: non_lu non booléen", verifier_fil_non_lu, _non_lu_chaine),
    ("fil: hook avec une preuve", verifier_fil_forme, _fil_hook_avec_preuve),
    ("alarmes: destinataire inconnu", verifier_alarmes_forme, _alarme_sans_destinataire),
    ("alarmes: facteur_arrete sans facteur arrêté", verifier_alarmes_coherence, _facteur_alarme_sans_arret),
    ("1.23: une seule session hors organigramme", verifier_sessions_et_decisions, _session_une_seule),
    ("1.23: session hors du préfixe", verifier_sessions_et_decisions, _session_hors_prefixe),
    ("1.23: session déjà connue de l'organigramme", verifier_sessions_et_decisions, _session_connue),
    ("1.23: décisions dans le désordre", verifier_sessions_et_decisions, _decisions_desordre),
    ("1.23: décision sans date", verifier_sessions_et_decisions, _decisions_date_texte),
    ("1.23: décisions nulles", verifier_sessions_et_decisions, _decisions_nulles),
    ("alarmes: session_orpheline avec un agent", verifier_alarmes_id, _orpheline_avec_agent),
    ("alarmes: session_orpheline de moins de 60 min", verifier_alarmes_coherence, _orpheline_recente),
    ("alarmes: session_orpheline grave", verifier_alarmes_gravite, _orpheline_gravite),
    ("alarmes id: session_orpheline sans epoch", verifier_alarmes_id, _orpheline_id_epoch),
    ("alarmes: plus de session_orpheline", verifier_alarmes_forme, _sans_alarme("session_orpheline")),
    ("statuts: observation active malgré une attente", verifier_statuts_equipes, _statut_contraire),
    ("statuts: équipe qui travaille au repos", verifier_statuts_equipes, _statut_repos_a_tort),
    ("alarmes: bloque_au_demarrage manquante", verifier_alarmes_forme, _sans_alarme("bloque_au_demarrage")),
    ("alarmes: bloque_au_demarrage sur un worker qui travaille", verifier_alarmes_coherence, _demarrage_sans_agent_bloque),
    ("alarmes: bloque_au_demarrage depuis moins de 2 min", verifier_alarmes_coherence, _demarrage_recent),
    ("alarmes: bloque_au_demarrage sans le pied de confirmation", verifier_alarmes_coherence, _demarrage_sans_pied),
    ("alarmes: bloque_au_demarrage non grave", verifier_alarmes_gravite, _demarrage_gravite),
    ("alarmes id: bloque_au_demarrage epoch ≠ depuis", verifier_alarmes_id, _demarrage_id_epoch),
    ("alarmes id: bloque_au_demarrage sans epoch", verifier_alarmes_id, _demarrage_id_texte),
    ("alarmes: brouillon de moins de 60 s", verifier_alarmes_coherence, _brouillon_recent),

    ("attentes: clôture sans équipe", verifier_attentes, _cloture_sans_equipe),
    ("attentes: équipe inconnue", verifier_attentes, _attente_equipe_inconnue),
    ("équipes: en_avance_sur_base négatif", verifier_equipes, _avance_negative),
    ("équipes: en_avance_sur_base texte", verifier_equipes, _avance_texte),
    ("alarmes: fige sur un agent au repos", verifier_alarmes_coherence, _fige_agent_au_repos),
    ("alarmes: fige depuis moins de 15 min", verifier_alarmes_coherence, _fige_recent),
    ("alarmes: fige en grave à 23 min", verifier_alarmes_gravite, _fige_grave),
    ("alarmes id: fige sans epoch", verifier_alarmes_id, _fige_id_texte),
    ("sources: nom hors liste (hooks)", verifier_sources, _source_hooks),
    ("sources: nom en double", verifier_sources, _source_en_double),
    ("utilisateur: modele renseigné", verifier_utilisateur, _utilisateur_modele),
    ("utilisateur: vivant false", verifier_utilisateur, _utilisateur_vivant_false),
    ("utilisateur: etat autre qu'inconnu", verifier_utilisateur, _utilisateur_etat),
    ("utilisateur: contexte renseigné", verifier_utilisateur, _utilisateur_contexte),
    ("attentes: decision d'un coordinateur", verifier_attentes, _decision_agent_coord),
    ("attentes: clôture portée par l'Assistant", verifier_attentes, _cloture_agent_assistant),
    ("attentes: aucune attente de l'Assistant", verifier_alarmes_coherence, _aucune_attente_assistant),
    ("alarmes id: deux segments", verifier_alarmes_id, _alarme_id_court),
    ("alarmes id: premier segment ≠ type", verifier_alarmes_id, _alarme_id_type),
    ("alarmes id: second segment inconnu", verifier_alarmes_id, _alarme_id_inconnu),
    ("alarmes id: en double", verifier_alarmes_id, _alarme_id_double),
    ("alarmes id: second segment étranger à l'alarme", verifier_alarmes_id, _alarme_id_hors_alarme),
    ("alarmes id: recouvrement hors ordre alphabétique", verifier_alarmes_id, _id_recouvrement_desordre),
    ("alarmes id: hors_perimetre sans chemin complet", verifier_alarmes_id, _id_hors_perimetre_nom_court),
    ("alarmes id: contexte_plein sans modèle", verifier_alarmes_id, _id_contexte_seuil),
    ("alarmes id: brouillon sans window_activity", verifier_alarmes_id, _id_brouillon_horodatage),
    ("fil: nature hors liste (tache)", verifier_fil_forme, _nature_hors_liste),
    ("fil: nature hors liste (rapport)", verifier_fil_forme, _nature_rapport),
    ("fil: rapport_utilisateur mal dirigé", verifier_fil_forme, _rapport_utilisateur_mal_dirige),
    ("fil: plus de signalement", verifier_fil_couverture, _plus_de_signalement),
    ("fil: plus de travail_pret", verifier_fil_couverture, _plus_de_travail_pret),
    ("attentes: rapport sans lu", verifier_attentes, _actions_rapport),
    ("attentes: decision avec autoriser", verifier_attentes, _actions_decision),
    ("attentes: cloture avec refuser", verifier_attentes, _actions_cloture),
    ("attentes: message de mauvaise nature", verifier_attentes, _attente_message_mauvaise_nature),
    ("attentes: message pas de l'Assistant à l'utilisateur", verifier_attentes, _attente_message_mal_dirige),
    ("racine: version", verifier_racine, _version),
    ("racine: collecte trop lente", verifier_racine, _duree_trop_longue),
    ("projet: étape cochée à tort", verifier_projet, _etape_cochee),
    ("projet: étape renommée", verifier_projet, _etape_renommee),
    ("sources: aucune en échec", verifier_sources, _toutes_sources_ok),
    ("sources: échec sans erreur", verifier_sources, _source_sans_erreur),
    ("agents: clé en trop", verifier_agents_forme, _cle_en_trop),
    ("agents: état inconnu", verifier_agents_forme, _etat_inconnu),
    ("agents: rôle inconnu", verifier_agents_forme, _role_inconnu),
    ("agents: phrase > 300", verifier_agents_forme, _phrase_longue),
    ("agents: contexte > limite", verifier_agents_forme, _contexte_depasse),
    ("agents: vivant incohérent avec arrete", verifier_agents_forme, _vivant_false_mais_repos),
    ("agents: parent inconnu", verifier_references, _parent_inconnu),
    ("agents: plus d'attend_reponse", verifier_agents_couverture, _tous_au_repos),
    ("agents: plus de brouillon", verifier_agents_couverture, _plus_de_brouillon),
    ("agents: plus de contexte > 60 %", verifier_agents_couverture, _contexte_bas),
    ("source en échec: coût à 0", verifier_source_en_echec, _cout_zero),
    ("source en échec: coût à false", verifier_source_en_echec, _cout_faux),
    ("équipes: statut manquant", verifier_equipes_couverture, _un_statut_en_moins),
    ("équipes: cloturee_le absente d'une équipe terminée", verifier_equipes, _cloturee_le_absente),
    ("équipes: cloturee_le sur une équipe active", verifier_equipes, _cloturee_le_sur_active),
    ("équipes: depend_de inconnu", verifier_equipes_couverture, _depend_inconnu),
    ("équipes: depend_de null", verifier_equipes_couverture, _depend_null),
    ("équipes: hors_perimetre non calculé", verifier_equipes, _perimetre_ignore),
    ("équipes: hors_perimetre inventé", verifier_equipes, _hors_perimetre_faux),
    ("équipes: commit mal formé", verifier_equipes, _commit_mal_forme),
    ("fil: trop court", verifier_fil_forme, _fil_court),
    ("fil: id entier", verifier_fil_forme, _id_fil_entier),
    ("fil: id en double", verifier_fil_forme, _id_fil_en_double),
    ("fil: résumé hook > 160", verifier_fil_forme, _resume_long),
    ("fil: hook avec nature", verifier_fil_forme, _hook_avec_nature),
    ("fil: registre sans nature", verifier_fil_forme, _registre_sans_nature),
    ("fil: fichier absolu", verifier_fil_forme, _fichier_absolu),
    ("fil: plus de en_attente", verifier_fil_couverture, _fil_en_attente_efface),
    ("fil: mal trié", verifier_fil_tri, _fil_trie_casse),
    ("attentes: clôture d'équipe spéciale", verifier_attentes, _cloture_speciale),
    ("attentes: id absent du fil", verifier_attentes, _attente_id_inconnu),
    ("attentes: perm mal nommé", verifier_attentes, _perm_mal_nomme),
    ("attentes: nature manquante", verifier_attentes, _attente_manquante),
    ("alarmes: type inconnu", verifier_alarmes_forme, _alarme_inconnue),
    ("alarmes: sans quoi_faire", verifier_alarmes_forme, _alarme_sans_quoi_faire),
    ("action_refusee: trop ancienne", verifier_action_refusee, _refus_ancien),
    ("action_refusee: id mal formé", verifier_action_refusee, _refus_id),
    ("action_refusee: gravité", verifier_action_refusee, _refus_grave),
    ("alarmes: recouvrement à une équipe", verifier_alarmes_coherence, _recouvrement_une_equipe),
    ("alarmes: contexte_plein manquante", verifier_alarmes_coherence, _sans_alarme("contexte_plein")),
    ("alarmes: brouillon manquante", verifier_alarmes_coherence, _sans_alarme("brouillon")),
    ("alarmes: hors_perimetre manquante", verifier_alarmes_coherence, _sans_alarme("hors_perimetre")),
    ("alarmes: retard_sur_base manquante", verifier_alarmes_coherence, _sans_alarme("retard_sur_base")),
    ("alarmes: sur équipe terminée", verifier_alarmes_coherence, _alarme_terminee),
    ("alarmes: session_disparue sur agent vivant", verifier_alarmes_coherence, _disparue_vivant),
    ("alarmes: question déjà répondue", verifier_alarmes_coherence, _question_non_en_attente),
    ("alarmes: plus de type action_refusee", verifier_alarmes_forme, _sans_alarme("action_refusee")),
    ("1.24: alarme contexte_au_repos absente", verifier_alarmes_forme, _sans_alarme("contexte_au_repos")),
    ("1.24: consommation absente d'un agent", verifier_agents_forme, _cle_retiree("consommation")),
    ("1.24: consommation de l'utilisateur non nulle", verifier_utilisateur, _utilisateur_consommation),
    ("1.24: racine sans clé gros_postes", verifier_consommation, _racine_sans_postes),
    ("1.24: racine : fenêtre sans tours", verifier_consommation, _fenetre_sans_tours),
    ("1.24: racine : 15 min différente de la somme", verifier_consommation, _racine_somme_fausse),
    ("1.24: sous-agents plus que les lus", verifier_consommation, _sous_agents_trop),
    ("1.24: aucun agent avec sous-agents", verifier_consommation, _aucun_sous_agent),
    ("1.24: source inconnue", verifier_consommation, _source_conso_inconnue),
    ("1.24: contexte moyen sans réponse principale", verifier_consommation, _contexte_sans_tours),
    ("1.24: six gros postes", verifier_consommation, _six_gros_postes),
    ("1.24: gros postes dans le désordre", verifier_consommation, _gros_postes_desordre),
    ("1.24: part de gros poste fausse", verifier_consommation, _part_fausse),
    ("1.24: gros poste à 0 lus", verifier_consommation, _gros_poste_zero),
    ("1.24: alarme gros_poste absente", verifier_consommation, _sans_alarme("gros_poste")),
    ("1.24: alarme gros_poste sur un agent sous le seuil", verifier_consommation, _gros_poste_faux),
    ("1.24: alarme contexte_au_repos sans contexte", verifier_consommation, _repos_sans_contexte),
    ("1.24: alarme gros_poste grave", verifier_alarmes_gravite, _gros_poste_grave),
    ("1.24: id gros_poste avec discriminant", verifier_alarmes_id, _gros_poste_id_disc),
    ("1.24: id contexte_au_repos avec mauvais epoch", verifier_alarmes_id, _repos_id_epoch),
    ("références: fil.de inconnu", verifier_references, _de_inconnu),
    ("références: alarme.agents inconnu", verifier_references, _alarme_agent_inconnu),
    ("références: alarme.equipes inconnue", verifier_references, _alarme_equipe_inconnue),
    ("horodatages: postérieur à genere_a", verifier_horodatages, _futur),
    ("horodatages: format sans Z", verifier_fil_forme, _horo_sans_z),
    ("confidentialité: e-mail", verifier_confidentialite, _email),
    ("confidentialité: chemin personnel", verifier_confidentialite, _chemin_perso),
]


@pytest.mark.parametrize("nom,verif,mutation", ETAT_MUTATIONS, ids=[m[0] for m in ETAT_MUTATIONS])
def test_mutation_etat(etat, nom, verif, mutation):
    verif(etat)  # la donnée saine passe
    cassee = copy.deepcopy(etat)
    mutation(cassee)
    with pytest.raises(AssertionError):
        verif(cassee)


def _journal_sans_lu(j):
    for x in j["lignes"]:
        if x["action"] == "lu":
            x["action"] = "deposer"


JOURNAL_MUTATIONS = [
    ("journal: plus de refus", verifier_journal, _journal_sans_refus),
    ("journal: plus d'erreur", verifier_journal, _journal_sans_erreur),
    ("journal: action inconnue", verifier_journal, _journal_action),
    ("journal: trop court", verifier_journal, _journal_court),
    ("journal: résultat mal formé", verifier_journal, _journal_resultat),
    ("journal: liste nue", verifier_journal, _journal_liste_nue),
    ("journal: ordre croissant", verifier_journal, _journal_croissant),
    ("journal: id texte", verifier_journal, _journal_id_texte),
    ("journal: id en double", verifier_journal, _journal_id_double),
    ("journal: cible hors format", verifier_journal, _journal_cible_hors_format),
]


@pytest.mark.parametrize("nom,verif,mutation", JOURNAL_MUTATIONS, ids=[m[0] for m in JOURNAL_MUTATIONS])
def test_mutation_journal(journal, nom, verif, mutation):
    verif(journal)
    cassee = copy.deepcopy(journal)
    mutation(cassee)
    with pytest.raises(AssertionError):
        verif(cassee)


def test_mutation_journal_lu(journal, etat):
    verifier_journal_lu(journal, etat)
    sans = copy.deepcopy(journal)
    _journal_sans_lu(sans)
    with pytest.raises(AssertionError):
        verifier_journal_lu(sans, etat)
    sur_attente = copy.deepcopy(journal)
    for x in sur_attente["lignes"]:
        if x["action"] == "lu":
            x["cible"] = attente(etat, "rapport")["id"]
    with pytest.raises(AssertionError):
        verifier_journal_lu(sur_attente, etat)
    inconnu = copy.deepcopy(journal)
    for x in inconnu["lignes"]:
        if x["action"] == "lu":
            x["cible"] = "msg-9999"
    with pytest.raises(AssertionError):
        verifier_journal_lu(inconnu, etat)


def test_mutation_journal_futur(journal, etat):
    cassee = copy.deepcopy(journal)
    _journal_futur(cassee)
    with pytest.raises(AssertionError):
        verifier_journal_horodatage(cassee, etat)


TERMINAUX_MUTATIONS = [
    ("terminaux: texte trop court", _terminal_court),
    ("terminaux: agent manquant", _terminal_manquant),
    ("terminaux: demande d'autorisation absente", _terminal_sans_demande),
    ("terminaux: capture dans le futur", _terminal_futur),
    ("terminaux: bloqué au démarrage sans pied de confirmation", _terminal_sans_pied),
]


@pytest.mark.parametrize("nom,mutation", TERMINAUX_MUTATIONS, ids=[m[0] for m in TERMINAUX_MUTATIONS])
def test_mutation_terminaux(terminaux, etat, nom, mutation):
    cassee = copy.deepcopy(terminaux)
    mutation(cassee)
    with pytest.raises(AssertionError):
        verifier_terminaux(cassee, etat)


def test_mutation_confidentialite_terminaux(terminaux):
    cassee = copy.deepcopy(terminaux)
    _terminal_pii(cassee)
    with pytest.raises(AssertionError):
        verifier_confidentialite(cassee)


def test_couverture_des_verifications():
    """Chaque vérification est éprouvée par au moins une mutation."""
    eprouvees = {m[1] for m in ETAT_MUTATIONS} | {m[1] for m in JOURNAL_MUTATIONS}
    eprouvees |= {verifier_journal_horodatage, verifier_journal_lu, verifier_terminaux}
    toutes = {v for n, v in globals().items() if n.startswith("verifier_") and callable(v)}
    assert toutes <= eprouvees, sorted(v.__name__ for v in toutes - eprouvees)
