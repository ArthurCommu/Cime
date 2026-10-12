"""La fiche équipe : ce qui attend l'utilisateur d'abord, ses agents, le terminal dans le premier écran, ses échanges,
ses alarmes, puis le périmètre et les dépendances repliés ; les workers terminés en un seul repli « + n workers terminés ».

Quatre vérifications, chacune avec sa table de mutations (la vérification doit échouer quand on casse chaque comportement) :
  - `verifier_ordre` : analyse de texte du JS et du CSS (l'ordre dans `monterPage`, les replis fermés, le terminal d'au moins 12 lignes) ;
  - `verifier_fonctions` : les fonctions pures de equipe.js exécutées par node (groupement des workers, résumés des replis, attentes de l'équipe) ;
  - `verifier_rendu` : la fiche rendue par node (DOM minimal) pour une équipe active, clôturée, sans agent, une source en échec, avec et sans attente ;
  - `verifier_hauteurs` : un calcul de hauteurs (le terminal et 12 lignes de sa zone dans les 900 px de 1 440 × 900, son haut avant la fin de 390 × 844),
    à partir des valeurs du CSS ; la mesure dans un vrai navigateur est dans outils/scenario_equipe.py (à lancer dans un navigateur).
Sautées si node est absent (les deux dernières n'en ont pas besoin pour le calcul).
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from test_supervision_coince_dependances import DOM, _agent, _alarme, _equipe, _exemple  # noqa: F401  (le DOM minimal et les fabriques d'état)

PAGE = Path(__file__).resolve().parents[2] / "src" / "cime" / "page"
STATIC = PAGE / "static"
EQ, CSS = "vues/equipe.js", "equipe.css"
FEUILLES = ["style.css", "equipe.css", "archives.css", "pages-fil.css"]


def _corps(texte, debut, fin):
    i = texte.index(debut)
    return texte[i:texte.index(fin, i)]


def _declarations(css, selecteur):
    """Les déclarations de la règle `selecteur` (texte exact du sélecteur), hors @media."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    m = re.search(r"(?:^|\})\s*" + re.escape(selecteur) + r"\s*\{([^{}]*)\}", css)
    assert m, selecteur
    return dict((k.strip(), v.strip()) for k, v in (d.split(":", 1) for d in m.group(1).split(";") if ":" in d))


# ---------------------------------------------------------------------------
# 1. Texte : l'ordre, les replis, le terminal
# ---------------------------------------------------------------------------
ORDRE = ["enTete(q, def, terminee)", "sectionAttentes(q)", "sectionAgents(q, agents, terminee)", "sectionTerminal(q, agents, terminee)",
         "sectionEchanges(q, agents)", "sectionAlarmes(q)", "sectionPerimetre(q)", "sectionDependances(q)"]


def verifier_ordre(js):
    equipe, css = js[EQ], js[CSS]
    # l'ordre des sections : en-tête, attentes de l'utilisateur, agents, terminal, échanges, alarmes, périmètre, dépendances
    montage = _corps(equipe, "function monterPage(q)", "function enTete")
    positions = [montage.index(s) for s in ORDRE]
    assert positions == sorted(positions), positions
    assert "ctx.contenu.append(el('div', { class: 'fiche' }, ...[" in montage
    # les attentes : les mêmes cartes que le rail, absentes sans attente, inconnues si la source est en échec
    sec = _corps(equipe, "function sectionAttentes(q)", "function carteAvecBrouillon")
    assert "carteAttente(a, { etat })" in sec and "if (!attentes.length) return null;" in sec
    assert "if (attentes === null) {" in sec and "Ce qui t’attend : inconnu" in sec
    att = _corps(equipe, "export function attentesDeLEquipe(etat, q)", "function sectionAttentes")
    assert "if (ouvertes === null) return null;" in att and "equipeDeLAttente(a, etat) === q.nom" in att
    assert "!(a.nature === 'cloture' && (q.speciale || q.statut === 'terminee'))" in att  # jamais de clôture pour une équipe spéciale ou déjà clôturée
    assert "trierAttentes(" in att
    # les replis : repliés par défaut, un titre h2 dont le résumé tient sur une ligne
    repli = _corps(equipe, "const repli = (classe, resume, ...corps)", "/** Les fichiers touchés")
    assert "el('details', { class: `eq-repli ${classe}` }," in repli and "open" not in repli
    assert "el('summary', {}, el('h2', {}, resume))" in repli
    assert "repli('eq-perimetre', resumePerimetre(q)," in equipe and "repli('eq-dependances', resumeDependances(q, equipes)," in equipe
    assert "Perim" + "ètre et fichiers touchés'" not in equipe  # plus de grande section : le résumé fait le titre
    # les workers terminés : un seul repli, « + n workers terminés » ; plus de ligne « Sans session capturée » en mono
    assert "Sans session capturée" not in equipe and "Historique" not in equipe
    assert "export const resumeTermines = (n) => `+ ${n} ${n === 1 ? 'worker terminé' : 'workers terminés'}`;" in equipe
    assert "!avecSession.includes(a) && !workerTermine(a, etat.alarmes)" in equipe  # le terminal ne redit pas les terminés
    ligne = _corps(equipe, "function ligneTerminee(a)", "function sectionAgents")
    assert "mono(" not in ligne and "age(a.etat_depuis, 'il-y-a', 'terminé ')" in ligne and "el('li', { class: 'eq-termine' }," in ligne
    # aucun texte de développement dans les sous-titres
    assert "'rafraîchi toutes les 5 s'" in equipe and "ce que l’agent a à l’écran" not in equipe
    # la hiérarchie ne change pas : la fiche n'écrit jamais à un coordinateur
    assert "dialogueDemander" not in equipe and "'demander'" not in equipe
    # le terminal : une zone d'au moins 12 lignes (12 × 18,75 px + 2 × 14 px de marge = 253 px), jamais plus de 340 px
    terminal = _declarations(css, ".terminal")
    assert terminal["min-height"] == "253px" and terminal["max-height"] == "340px"
    assert terminal["font-size"] == "12.5px" and terminal["line-height"] == "1.5" and terminal["padding"] == "14px"
    # les agents vivants : des lignes de 44 px ; les repliés ne portent aucun rouge de plus
    assert _declarations(css, ".eq-agent > summary")["min-height"] == "44px"
    assert _declarations(css, ".fiche")["gap"] == "18px"
    assert "--rouge" not in _corps(css, ".eq-agent {", "/* Terminal */")


# ---------------------------------------------------------------------------
# 2. Les fonctions pures, exécutées par node
# ---------------------------------------------------------------------------
SONDE_PURE = r"""
const e = await import(process.argv[2] + '/vues/equipe.js');
const t = (h) => `2026-10-11T${h}:00.000Z`;
const ag = (id, role, etat, depuis, extra = {}) => ({ id, role, equipe: 'x', etat, vivant: etat !== 'arrete', session_tmux: etat === 'arrete' ? null : 'cc-' + id, etat_depuis: depuis, ...extra });
const A = (id, agents) => ({ id, type: 'fige', gravite: 'grave', agents, equipes: [] });
const agents = [
  ag('w-vieux', 'worker', 'arrete', t('08:00')), ag('w-recent', 'worker', 'arrete', t('10:00')), ag('w-marche', 'worker', 'travaille', t('09:00')),
  ag('coord-x', 'coordinateur', 'au_repos', t('07:00')), ag('w-alarme', 'worker', 'arrete', t('09:30')), ag('coord-arrete', 'coordinateur', 'arrete', t('06:00')),
  ag('w-inconnu', 'worker', 'arrete', t('09:45'), { vivant: null }),
];
const avant = JSON.stringify(agents);
const g = e.grouperAgents(agents, [A(1, ['w-alarme'])]);
const q = (extra) => ({ nom: 'x', ...extra });
const eqs = [q({ depend_de: ['a', 'b'] }), { nom: 'a', depend_de: ['x'] }, { nom: 'b', depend_de: [] }, { nom: 'c', depend_de: null }, { nom: 'd', depend_de: ['x', 'a'] }];
const att = (id, nature, equipe, depuis, agent = 'coord-x') => ({ id, nature, titre: 't' + id, equipe, depuis, agent });
const etatAtt = (attentes, equipes = []) => ({ attentes_utilisateur: attentes, agents: [ag('coord-x', 'coordinateur', 'au_repos', t('07:00'))], equipes });
const ouvertes = [att('r1', 'rapport', 'x', t('09:00')), att('d1', 'decision', 'x', t('11:00')), att('d0', 'decision', 'x', t('10:00')), att('ailleurs', 'decision', 'y', t('08:00'), 'coord-y'),
  att('c1', 'cloture', 'x', t('12:00')), att('a1', 'autorisation', 'x', t('13:00'))];
console.log(JSON.stringify({
  vivants: g.vivants.map((a) => a.id), termines: g.termines.map((a) => a.id), inchange: JSON.stringify(agents) === avant,
  groupeVide: e.grouperAgents([], []),
  resumesTermines: [e.resumeTermines(1), e.resumeTermines(2), e.resumeTermines(10)],
  perimetre: [
    e.resumePerimetre(q({ perimetre_declare: ['a/', 'b/'], fichiers_touches: ['a/1', 'b/2', 'c/3'], hors_perimetre: ['c/3'] })),
    e.resumePerimetre(q({ perimetre_declare: ['a/'], fichiers_touches: ['a/1'], hors_perimetre: [] })),
    e.resumePerimetre(q({ perimetre_declare: [], fichiers_touches: [], hors_perimetre: [] })),
    e.resumePerimetre(q({ perimetre_declare: ['a/'], fichiers_touches: ['a/1'], hors_perimetre: ['z/9'] })),
    e.resumePerimetre(q({ perimetre_declare: ['a/'], fichiers_touches: null })),
    e.resumePerimetre(q({ perimetre_declare: null, fichiers_touches: [] })),
    e.resumePerimetre(q({ perimetre_declare: ['a/'], fichiers_touches: ['a/1'] })),
  ],
  fichiers: e.fichiersDe(q({ fichiers_touches: ['a/1', 'c/3'], hors_perimetre: ['c/3', 'z/9'] })).fichiers,
  dependances: [e.resumeDependances(eqs[0], eqs), e.resumeDependances(q({ depend_de: [] }), [q({ depend_de: [] })]), e.resumeDependances(q({ depend_de: null }), eqs), e.resumeDependances(q({ depend_de: ['a'] }), [q({ depend_de: ['a'] })])],
  liens: e.dependancesDe(eqs[0], eqs),
  attentes: e.attentesDeLEquipe(etatAtt(ouvertes), q({})).map((a) => a.id),
  attentesSpeciale: e.attentesDeLEquipe(etatAtt(ouvertes), q({ speciale: true })).map((a) => a.id),
  attentesTerminee: e.attentesDeLEquipe(etatAtt(ouvertes), q({ statut: 'terminee' })).map((a) => a.id),
  attentesAucune: e.attentesDeLEquipe(etatAtt([]), q({})),
  attentesInconnues: e.attentesDeLEquipe({ attentes_utilisateur: null, agents: [] }, q({})),
  sansTerminal: [e.phraseSansTerminal(q({}), [], []), e.phraseSansTerminal(q({ speciale: true }), [], []), e.phraseSansTerminal(q({}), [{ id: 'w' }], []), e.phraseSansTerminal(q({}), [{ id: 'w' }], [{ id: 'w' }])],
}));
"""

ATTENDU = {
    "vivants": ["coord-x", "coord-arrete", "w-marche", "w-alarme", "w-inconnu"],  # coordinateurs d'abord ; un arrêté avec alarme ou inconnu reste vivant
    "termines": ["w-recent", "w-vieux"],  # le plus récent d'abord
    "resumesTermines": ["+ 1 worker terminé", "+ 2 workers terminés", "+ 10 workers terminés"],
    "perimetre": [
        "Périmètre : 2 chemins · 3 fichiers touchés · 1 hors périmètre",
        "Périmètre : 1 chemin · 1 fichier touché",
        "Périmètre : 0 chemins · 0 fichiers touchés",
        "Périmètre : 1 chemin · 2 fichiers touchés · 1 hors périmètre",  # un fichier hors périmètre compte même s'il n'est pas dans les fichiers touchés
        "Périmètre : inconnu",
        "Périmètre : inconnu",
        "Périmètre : 1 chemin · 1 fichier touché",  # sans `hors_perimetre` : aucun fichier hors périmètre
    ],
    "fichiers": ["a/1", "c/3", "z/9"],
    "dependances": ["Dépendances : 4", "Dépendances : 0", "Dépendances : inconnues", "Dépendances : 1"],  # dépend de 2 + alimentée par 2 (a, d)
    "liens": {"dependDe": ["a", "b"], "alimente": ["a", "d"], "incertaines": ["c"]},
    "attentes": ["a1", "d0", "d1", "c1", "r1"],  # l'ordre du rail : par genre, puis la plus ancienne d'abord ; aucune attente d'une autre équipe
    "attentesSpeciale": ["a1", "d0", "d1", "r1"],
    "attentesTerminee": ["a1", "d0", "d1", "r1"],
    "attentesAucune": [],
    "attentesInconnues": None,
}
SANS_TERMINAL = ["Aucun agent vu pour cette équipe : il n’y a pas de terminal.",
                 "Équipe à la demande, sans session : il n’y a pas de terminal tant qu’on ne la lance pas.",
                 "Tous les agents de cette équipe ont terminé : il n’y a plus de session à regarder.",
                 "Aucune session capturée en ce moment : les agents de cette équipe n’ont pas de session tmux lisible."]


def _lancer(dossier_static, sonde, *arguments):
    fichier = dossier_static / "sonde-fiche.mjs"
    fichier.write_text(sonde, encoding="utf-8")
    res = subprocess.run(["node", str(fichier), str(dossier_static), *arguments], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


def verifier_fonctions(dossier_static):
    # la sonde importe equipe.js, qui a besoin du DOM minimal (commun.js touche document à l'import)
    r = _lancer(dossier_static, DOM + SONDE_PURE)
    assert r.pop("inchange") is True  # l'entrée n'est pas modifiée par le tri
    assert r.pop("groupeVide") == {"vivants": [], "termines": []}
    assert r.pop("sansTerminal") == SANS_TERMINAL
    assert r == ATTENDU, r


# ---------------------------------------------------------------------------
# 3. Le rendu de la fiche, exécuté par node (DOM minimal)
# ---------------------------------------------------------------------------
SONDE_RENDU = DOM + r"""
const e = await import(process.argv[2] + '/vues/equipe.js');
const commun = await import(process.argv[2] + '/commun.js');
const jeux = JSON.parse(readFileSync(process.argv[3], 'utf8'));
const decrire = (n) => {
  const sommaire = n.children.find((m) => m.tag === 'summary');
  const h2 = sous(n).find((m) => m.tag === 'h2');
  const type = n.tag === 'header' ? 'entete' : n.tag === 'details' ? 'repli' : 'section';
  return { type, titre: type === 'entete' ? null : texte(sommaire || h2), ouvert: 'open' in n.attrs, classes: n.classes };
};
const sortie = {};
for (const [nom, jeu] of Object.entries(jeux)) {
  const etat = jeu.etat;
  const c = new Elt('main');
  const source = { terminal: async () => ({ texte: 'ok', capture_a: etat.genere_a }), agentsAvecTerminal: (agents) => agents.filter((x) => x.session_tmux && x.vivant !== false) };
  let arret;
  try {
    arret = e.rendre({ etat, contenu: c, route: { page: 'equipe', nom: jeu.equipe, params: new URLSearchParams('') }, horloge: { maintenant: () => Date.parse(etat.genere_a) }, journal: [], tic() {}, source, rerendre() {} });
  } catch (err) { sortie[nom] = { erreur: `${err.name}: ${err.message}` }; continue; }
  const fiche = c.children[0].classes.includes('fiche') ? c.children[0] : new Elt('x');
  const termines = sous(fiche).find((n) => n.classes.includes('eq-termines'));
  const attentes = a(fiche, 'attente');
  const equipe = (etat.equipes || []).find((q) => q.nom === jeu.equipe);
  const ouvertes = commun.attentesOuvertes(etat) || [];
  const refs = ouvertes.filter((x) => commun.equipeDeLAttente(x, etat) === jeu.equipe).map((x) => commun.carteAttente(x, { etat }));
  const lignes = a(fiche, 'eq-agent');
  sortie[nom] = {
    racine: [c.children.length, fiche.classes],
    enfants: fiche.children.map(decrire),
    termines: termines ? {
      resume: texte(termines.children.find((m) => m.tag === 'summary')), ouvert: 'open' in termines.attrs,
      lignes: a(termines, 'eq-termine').map((li) => ({ nom: texte(a(li, 'eq-termine-nom')[0]), tache: texte(a(li, 'eq-termine-tache')[0]), age: sous(li).filter((m) => m.tag === 'time').length })),
      monoReplie: sous(termines).filter((n) => n.classes.includes('mono') || n.classes.includes('agent-nom')).length,
    } : null,
    nbTermines: termines ? a(termines, 'eq-termine').length : 0,
    historique: sous(fiche).filter((n) => n.classes.includes('historique')).length,
    attentes: attentes.map((n) => ({ nature: n.dataset.nature, texte: texte(n), boutons: sous(n).filter((m) => m.tag === 'button' || m.tag === 'label').map(texte) })),
    attentesRef: refs.map((n) => ({ nature: n.dataset.nature, texte: texte(n), boutons: sous(n).filter((m) => m.tag === 'button' || m.tag === 'label').map(texte) })),
    agents: lignes.map((n) => ({ id: n.dataset.agent, ouvert: 'open' in n.attrs, resume: texte(n.children[0]), cartes: a(n, 'agent').length })),
    terminal: a(fiche, 'terminal').length, barreTerminal: a(fiche, 'terminal-barre').map(texte),
    vides: [...a(fiche, 'vide-calme'), ...a(fiche, 'inconnu-bloc')].map(texte),
    discrets: a(fiche, 'discret').map(texte),
    texte: texte(fiche),
    clotureNote: a(fiche, 'eq-note').map(texte),
    boutonsDemander: sous(fiche).filter((n) => n.tag === 'button' && /Demander/.test(texte(n))).length,
    titres: sous(fiche).filter((n) => n.tag === 'h2').map(texte),
  };
  arret();
}
console.log(JSON.stringify(sortie));
"""


def _copie(v):
    return json.loads(json.dumps(v))


def _jeux():
    base = _exemple()
    jeux = {}

    def jeu(nom, equipe, modifier=None):
        v = _copie(base)
        if modifier:
            modifier(v)
        jeux[nom] = {"equipe": equipe, "etat": v}

    jeu("active", "hote")  # l'équipe de l'exemple qui a le plus de workers : sans attente à elle, un worker terminé, un perimetre hors limites
    jeu("avec attente", "page")  # une autorisation attend l'utilisateur pour cette équipe
    jeu("sans attente", "page", lambda v: v.update(attentes_utilisateur=[]))
    jeu("attentes inconnues", "page", lambda v: v.update(attentes_utilisateur=None))
    jeu("cloturee", "cadrage")

    def sans_agent(v):
        v["agents"] = [a for a in v["agents"] if a["equipe"] != "fondation"]
    jeu("sans agent", "fondation", sans_agent)

    def speciale_sans_agent(v):
        v["agents"] = [a for a in v["agents"] if a["equipe"] != "verification"]
    jeu("speciale sans agent", "verification", speciale_sans_agent)

    def tous_termines(v):
        v["agents"] = [a for a in v["agents"] if a["id"] != "coord-hote"]  # plus de coordinateur : il ne reste que les workers
        for a in v["agents"]:
            if a["equipe"] == "hote":
                a.update(etat="arrete", vivant=False, session_tmux=None)
        v["alarmes"] = [x for x in v["alarmes"] if not set(x["agents"]) & {a["id"] for a in v["agents"] if a["equipe"] == "hote"}]
    jeu("tous arretes", "hote", tous_termines)

    def sans_alarme_ni_echange(v):
        v.update(alarmes=[], fil=[])
    jeu("sans alarme ni echange", "hote", sans_alarme_ni_echange)

    def source_en_echec(v):
        v.update(alarmes=None, fil=None, attentes_utilisateur=None)
        for q in v["equipes"]:
            q.update(fichiers_touches=None, perimetre_declare=None, depend_de=None, avancement=None, retard_sur_base=None, en_avance_sur_base=None)
    jeu("source en echec", "hote", source_en_echec)
    jeu("equipe inconnue", "nulle part")
    return jeux


def _rendu(dossier_static):
    (dossier_static / "jeux-fiche.json").write_text(json.dumps(_jeux()), encoding="utf-8")
    return _lancer(dossier_static, SONDE_RENDU, str(dossier_static / "jeux-fiche.json"))


def _types(jeu):
    return [(e["type"], e["titre"]) for e in jeu["enfants"]]


def verifier_rendu(dossier_static):
    r = _rendu(dossier_static)
    for nom, jeu in r.items():
        assert "erreur" not in jeu or nom == "equipe inconnue", (nom, jeu)  # aucun état, vide ou en échec, ne lève d'erreur
        if nom != "equipe inconnue":
            assert jeu["racine"] == [1, ["fiche"]], (nom, jeu["racine"])  # une seule racine : la fiche
            assert jeu["historique"] == 0 and jeu["boutonsDemander"] == 0, nom  # pas de second repli, jamais d'écriture à un coordinateur
            # tout repli est fermé, les titres sont de même niveau (des h2) ; pas un seul texte de développement
            assert all(not e["ouvert"] for e in jeu["enfants"]), nom
            assert "TODO" not in jeu["texte"] and "undefined" not in jeu["texte"] and "null" not in jeu["texte"] and "NaN" not in jeu["texte"], nom
            assert "Sans session capturée" not in jeu["texte"], nom

    # 1. une équipe active : l'ordre complet, périmètre et dépendances repliés avec leur résumé
    hote = r["active"]
    assert _types(hote) == [("entete", None), ("section", "Ses agents"), ("section", "Terminal en direct"), ("section", "Ses derniers échanges"),
                            ("section", "Ses alarmes"), ("repli", "Périmètre : 2 chemins · 2 fichiers touchés · 1 hors périmètre"),
                            ("repli", "Dépendances : 4")], _types(hote)
    assert hote["attentes"] == [] and hote["terminal"] == 1
    # les agents : une ligne par agent vivant, repliée, la carte complète dessous ; les terminés : un seul repli
    assert [a["id"] for a in hote["agents"]] == ["coord-hote", "worker-hote-serveur", "worker-hote-tests"] and all(not a["ouvert"] and a["cartes"] == 1 for a in hote["agents"])
    assert hote["termines"]["resume"] == "+ 1 worker terminé" and not hote["termines"]["ouvert"]
    assert hote["termines"]["lignes"] == [{"nom": "worker-hote-schema", "tache": "Figer le schéma de l'instantané (version 1.23)", "age": 1}], hote["termines"]
    assert hote["termines"]["monoReplie"] == 0
    assert hote["titres"] == ["Ses agents", "Terminal en direct", "Ses derniers échanges", "Ses alarmes", "Périmètre : 2 chemins · 2 fichiers touchés · 1 hors périmètre", "Dépendances : 4"], hote["titres"]

    # 2. avec une attente pour l'utilisateur : elle passe en premier, avec les mêmes boutons que dans le rail ; sans attente, la section n'existe pas
    avec = r["avec attente"]
    assert _types(avec)[:3] == [("entete", None), ("section", "Attend de toi"), ("section", "Ses agents")], _types(avec)
    assert avec["attentes"] == avec["attentesRef"] and [a["nature"] for a in avec["attentes"]] == ["autorisation", "decision"], avec["attentes"]
    assert [a["boutons"] for a in avec["attentes"]] == [["Autoriser", "Refuser"], ["Accorder la fusion", "Refuser"]]  # ceux du rail
    for nom in ("sans attente", "active", "cloturee"):
        assert "Attend de toi" not in r[nom]["titres"], nom
    assert [t for t in _types(r["sans attente"]) if t[0] == "section"][0] == ("section", "Ses agents")
    inconnues = r["attentes inconnues"]
    assert _types(inconnues)[1] == ("section", "Attend de toi") and any("inconnu" in v for v in inconnues["vides"]) and inconnues["attentes"] == []

    # 3. une équipe clôturée : sa note de clôture, ses sections lisibles, pas de terminal
    cloturee = r["cloturee"]
    assert cloturee["clotureNote"] and "Équipe clôturée" in cloturee["clotureNote"][0] and cloturee["terminal"] == 0
    assert ("section", "Ses agents") in _types(cloturee) and ("section", "Ses alarmes") in _types(cloturee) and ("section", "Terminal en direct") not in _types(cloturee)

    # 4. sans agent : une phrase qui dit pourquoi, pour les agents comme pour le terminal
    sans = r["sans agent"]
    assert "Aucun agent de cette équipe dans l’instantané." in sans["vides"] and sans["terminal"] == 0 and sans["termines"] is None
    assert any(v.startswith("Aucun agent vu pour cette équipe") for v in sans["vides"]), sans["vides"]
    speciale = r["speciale sans agent"]
    assert any("Équipe à la demande" in v for v in speciale["vides"]), speciale["vides"]
    arretes = r["tous arretes"]
    assert "Aucun agent en cours." in arretes["vides"] and arretes["agents"] == [] and arretes["terminal"] == 0
    assert arretes["termines"]["resume"] == "+ 3 workers terminés" and any(v.startswith("Tous les agents de cette équipe ont terminé") for v in arretes["vides"]), arretes["vides"]

    # 5. sans alarme ni échange : une phrase calme pour chacun
    calme = r["sans alarme ni echange"]
    assert "Aucune alarme pour cette équipe." in calme["vides"] and "Aucun échange avec cette équipe." in calme["vides"]

    # 6. une source en échec : l'inconnu est dit, jamais un zéro inventé
    echec = r["source en echec"]
    assert [t[1] for t in _types(echec)[1:]] == ["Attend de toi", "Ses agents", "Terminal en direct", "Ses derniers échanges", "Ses alarmes", "Périmètre : inconnu", "Dépendances : inconnues"], _types(echec)
    assert any("Alarmes inconnues" in v for v in echec["vides"]) and any("Échanges inconnus" in v for v in echec["vides"])

    # 7. une équipe qui n'existe pas : un message, pas une fiche
    inconnue = r["equipe inconnue"]
    assert "erreur" not in inconnue and inconnue["enfants"] == [] and inconnue["titres"] == []


# ---------------------------------------------------------------------------
# 4. Les hauteurs : le terminal dans le premier écran
# ---------------------------------------------------------------------------
LIGNE_TERMINAL_PX = 12.5 * 1.5  # 18,75 px : corps 12,5 px, interligne 1,5
BARRE_TERMINAL_PX = 53  # barre du terminal : 8 + 36 (boutons de choix) + 8 + 1 de bordure
TETE_SECTION_PX = 24 + 14  # titre h2 de 17 px (24 px de ligne) + intervalle de la section
ENTETE_PX = 56  # l'en-tête collant de la page (style.css : « En-tête unique : 56 px »)
ATTENTE_PX = {"bureau": 124, "mobile": 176}  # une carte d'attente : étiquette, titre sur 2 lignes, âge, boutons (estimation haute)
ENTETE_EQUIPE_PX = {"bureau": 146, "mobile": 236}  # cadre de l'équipe : titre, mission (2 lignes), 4 faits en une ou deux colonnes (estimation haute)
LIGNE_AGENT_PX = {"bureau": 44, "mobile": 64}  # une ligne d'agent : 44 px au bureau ; sur mobile deux lignes (nom et état ; tâche et notes)
TERMINES_PX = 36  # la ligne repliée « + n workers terminés »


def _px(declarations, cle):
    return int(re.fullmatch(r"(\d+)px", declarations[cle]).group(1))


def _equipe_de(attente, etat):
    """L'équipe d'une attente, comme `equipeDeLAttente` : celle que l'hôte donne, sinon celle de l'agent demandeur, sinon celle que le titre nomme."""
    if attente["equipe"]:
        return attente["equipe"]
    agent = next((a for a in etat["agents"] if a["id"] == attente["agent"]), None)
    if agent and agent["equipe"]:
        return agent["equipe"]
    m = re.search(r"équipe\s+(\S+)", attente["titre"], flags=re.I)
    return m.group(1) if m else None


def hauteur_avant_terminal(css, vivants, attentes, termines, ecran):
    """Le haut du terminal (px depuis le haut de la page), d'après les valeurs du CSS et les hauteurs estimées ci-dessus."""
    mobile = ecran == "mobile"
    fiche = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    gap = int(re.search(r"@media \(max-width: 760px\) \{.*?\.fiche \{ gap: (\d+)px", fiche, flags=re.S).group(1)) if mobile else _px(_declarations(css, ".fiche"), "gap")
    padding_haut = 16 if mobile else 22  # `.page-corps` (style.css : 22 px au bureau, 16 px sur mobile)
    corps = padding_haut + ENTETE_EQUIPE_PX[ecran]
    if attentes:
        corps += gap + TETE_SECTION_PX + attentes * ATTENTE_PX[ecran] + (attentes - 1) * 8
    ligne = LIGNE_AGENT_PX[ecran] if mobile else _px(_declarations(css, ".eq-agent > summary"), "min-height")
    agents = vivants * ligne + (vivants - 1) * 6 + (TERMINES_PX if termines else 0) + (6 if termines else 0)
    corps += gap + TETE_SECTION_PX + agents
    corps += gap + TETE_SECTION_PX
    return ENTETE_PX + corps


def zone_terminal(css):
    """La hauteur minimale de la zone du terminal : la barre et le `min-height` du CSS."""
    return BARRE_TERMINAL_PX + _px(_declarations(css, ".terminal"), "min-height")


def verifier_hauteurs(js):
    css = js[CSS]
    exemple = _exemple()
    nb = lambda q, f: sum(1 for a in exemple["agents"] if a["equipe"] == q and f(a))  # noqa: E731
    # les équipes de l'exemple, avec leurs agents vivants (les workers arrêtés sans alarme sont repliés) et leurs attentes
    terminés = {a["id"] for a in exemple["agents"] if a["role"] == "worker" and a["etat"] == "arrete" and not any(a["id"] in x["agents"] for x in exemple["alarmes"])}
    plus = {}
    for q in exemple["equipes"]:
        if q["statut"] == "terminee":
            continue
        vivants = nb(q["nom"], lambda a: a["id"] not in terminés)
        attentes = sum(1 for x in exemple["attentes_utilisateur"] if _equipe_de(x, exemple) == q["nom"] and x["nature"] != "cloture")
        plus.setdefault(vivants, []).append(q["nom"])
        for ecran, (largeur, hauteur) in {"bureau": (1440, 900), "mobile": (390, 844)}.items():
            haut = hauteur_avant_terminal(css, vivants, attentes, nb(q["nom"], lambda a: a["id"] in terminés), ecran)
            if attentes == 0 and ecran == "mobile":
                assert haut < hauteur, (q["nom"], ecran, haut)  # le terminal commence avant la fin du premier écran
            elif attentes == 0:
                # le haut du terminal et au moins 12 lignes de sa zone sont dans le premier écran
                assert haut + zone_terminal(css) <= hauteur, (q["nom"], ecran, haut, zone_terminal(css))
            elif ecran == "bureau":
                assert haut < hauteur, (q["nom"], ecran, haut)  # ce qui attend l'utilisateur passe avant (c'est voulu) : au bureau, le haut du terminal reste visible
            # sur mobile, une équipe qui a des attentes pousse le terminal sous le premier écran : le rapport le dit
    assert max(plus) == 3 and {"hote", "observation"} <= set(plus[3]), plus  # les équipes qui ont le plus d'agents : les plus défavorables
    assert zone_terminal(css) == 53 + 12 * LIGNE_TERMINAL_PX + 28  # 12 lignes de 18,75 px, les marges et la barre
    assert _px(_declarations(css, ".terminal"), "min-height") == 12 * LIGNE_TERMINAL_PX + 28
    # sans le repli du périmètre et des dépendances au-dessus du terminal, la marge est faible mais réelle : les deux sections sont après
    assert hauteur_avant_terminal(css, 3, 0, 1, "bureau") + zone_terminal(css) <= 900


# ---------------------------------------------------------------------------
# Les tests et les mutations
# ---------------------------------------------------------------------------
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node n'est pas installé : le rendu n'est pas exécuté")


@pytest.fixture(scope="module")
def js():
    fichiers = sorted(STATIC.glob("*.js")) + sorted((STATIC / "vues").glob("*.js")) + [STATIC / f for f in FEUILLES]
    return {str(f.relative_to(STATIC)): f.read_text(encoding="utf-8") for f in fichiers}


@pytest.fixture
def copie_static(tmp_path):
    cible = tmp_path / "static"
    shutil.copytree(STATIC, cible, ignore=shutil.ignore_patterns("__pycache__"))
    return cible


def test_ordre(js):
    verifier_ordre(js)


def test_hauteurs(js):
    verifier_hauteurs(js)


@needs_node
def test_fonctions_executees(copie_static):
    verifier_fonctions(copie_static)


@needs_node
def test_rendu_execute(copie_static):
    verifier_rendu(copie_static)


def _remplace(fichier, ancien, nouveau):
    def mutation(js):
        assert ancien in js[fichier], ancien  # la mutation doit s'appliquer, sinon le test serait faux
        return {**js, fichier: js[fichier].replace(ancien, nouveau, 1)}
    return mutation


MUTATIONS = {
    "attentes après les agents": _remplace(EQ, "    sectionAttentes(q),\n    sectionAgents(q, agents, terminee),", "    sectionAgents(q, agents, terminee),\n    sectionAttentes(q),"),
    "périmètre avant les agents": _remplace(EQ, "    sectionAttentes(q),\n    sectionAgents(q, agents, terminee),", "    sectionAttentes(q),\n    sectionPerimetre(q),\n    sectionAgents(q, agents, terminee),"),
    "alarmes avant les échanges": _remplace(EQ, "    sectionEchanges(q, agents),\n    sectionAlarmes(q),", "    sectionAlarmes(q),\n    sectionEchanges(q, agents),"),
    "terminal avant les agents": _remplace(EQ, "    sectionAgents(q, agents, terminee),\n    sectionTerminal(q, agents, terminee),", "    sectionTerminal(q, agents, terminee),\n    sectionAgents(q, agents, terminee),"),
    "repli ouvert d'office": _remplace(EQ, "el('details', { class: `eq-repli ${classe}` },", "el('details', { open: true, class: `eq-repli ${classe}` },"),
    "repli sans h2": _remplace(EQ, "el('summary', {}, el('h2', {}, resume))", "el('summary', {}, resume)"),
    "clôture d'une équipe spéciale": _remplace(EQ, "!(a.nature === 'cloture' && (q.speciale || q.statut === 'terminee'))", "true"),
    "attentes absentes montrées vides": _remplace(EQ, "if (!attentes.length) return null;", ""),
    "ligne « Sans session capturée » rétablie": _remplace(EQ, "`Pas de terminal à afficher pour ", "`Sans session capturée : "),
    "terminés redits sous le terminal": _remplace(EQ, "!avecSession.includes(a) && !workerTermine(a, etat.alarmes)", "!avecSession.includes(a)"),
    "terminés en mono": _remplace(EQ, "el('span', { class: 'eq-termine-nom' }, nomAgent(a.id)),", "el('span', { class: 'eq-termine-nom' }, mono(a.id)),"),
    "terminal sans 12 lignes": _remplace(CSS, "min-height: 253px; max-height: 340px", "min-height: 120px; max-height: 340px"),
    "terminal trop haut": _remplace(CSS, "max-height: 340px", "max-height: 500px"),
    "lignes d'agent trop hautes": _remplace(CSS, "min-height: 44px; padding: 6px 14px; cursor: pointer; list-style: none;", "min-height: 80px; padding: 6px 14px; cursor: pointer; list-style: none;"),
    "intervalle des sections trop grand": _remplace(CSS, ".fiche { display: flex; flex-direction: column; gap: 18px; }", ".fiche { display: flex; flex-direction: column; gap: 40px; }"),
    "rouge dans les lignes d'agent": _remplace(CSS, ".eq-agent-attend { color: var(--ambre); }", ".eq-agent-attend { color: var(--rouge); }"),
    "sous-titre de développement": _remplace(EQ, "'rafraîchi toutes les 5 s'", "'ce que l’agent a à l’écran, rafraîchi toutes les 5 s'"),
    "demande à l'Assistant dans la fiche": _remplace(EQ, "import { trierAttentes } from './rail.js';", "import { trierAttentes } from './rail.js';\nconst dialogueDemander = null;"),
}


@pytest.mark.parametrize("nom", MUTATIONS)
def test_mutation_detectee(nom, js):
    mutee = MUTATIONS[nom](js)
    with pytest.raises(AssertionError):
        verifier_ordre(mutee)
        verifier_hauteurs(mutee)


# mutations qui ne se voient qu'à l'exécution : (fichier, ancien, nouveau, vérification qui doit échouer)
MUTATIONS_EXECUTEES = {
    "terminés non triés": (EQ, ".sort((x, y) => (Date.parse(y.etat_depuis) || 0) - (Date.parse(x.etat_depuis) || 0));", ";", verifier_fonctions),
    "coordinateurs derrière": (EQ, ".sort((x, y) => rang(x) - rang(y));", ";", verifier_fonctions),
    "vivants dans les terminés": (EQ, "const termines = agents.filter((a) => workerTermine(a, alarmes))", "const termines = agents.filter((a) => a.etat === 'arrete')", verifier_fonctions),
    "tableau reçu trié": (EQ, "const termines = agents.filter(", "agents.reverse(); const termines = agents.filter(", verifier_fonctions),
    "pluriel du repli": (EQ, "n === 1 ? 'worker terminé' : 'workers terminés'", "'workers terminés'", verifier_fonctions),
    "périmètre sans le hors périmètre": (EQ, "return nbHors ? `${ligne} · ${nbHors} hors périmètre` : ligne;", "return ligne;", verifier_fonctions),
    "périmètre inconnu dit zéro": (EQ, "return 'Périmètre : inconnu';", "return 'Périmètre : 0 chemins · 0 fichiers touchés';", verifier_fonctions),
    "hors périmètre perdu dans les fichiers": (EQ, "const fichiers = [...touches, ...[...hors].filter((f) => !touches.includes(f))];", "const fichiers = [...touches];", verifier_fonctions),
    "dépendances sans ce que l'équipe alimente": (EQ, "dependDe.length + alimente.length", "dependDe.length", verifier_fonctions),
    "dépendances inconnues dites zéro": (EQ, "dependDe === null ? 'Dépendances : inconnues'", "false ? 'Dépendances : inconnues'", verifier_fonctions),
    "attentes d'une autre équipe": (EQ, "equipeDeLAttente(a, etat) === q.nom", "true", verifier_fonctions),
    "attentes sans tri du rail": (EQ, "return trierAttentes(ouvertes.filter(", "return (ouvertes.filter(", verifier_fonctions),
    "attentes inconnues dites vides": (EQ, "if (ouvertes === null) return null;", "if (ouvertes === null) return [];", verifier_fonctions),
    "phrase sans terminal confondue": (EQ, "if (!sans.length) return 'Tous les agents de cette équipe ont terminé", "if (false) return 'Tous les agents de cette équipe ont terminé", verifier_fonctions),
    # le rendu
    "attentes sans leurs cartes": (EQ, "carteAttente(a, { etat })", "el('span', {}, a.titre)", verifier_rendu),
    "attentes inconnues sans phrase": (EQ, "    return section('Attend de toi', null, el('div', { class: 'inconnu-bloc' }, 'Ce qui t’attend : inconnu (sources en échec, voir l’en-tête).'));", "    return null;", verifier_rendu),
    "section d'attentes toujours là": (EQ, "if (!attentes.length) return null;", "", verifier_rendu),
    "agents vivants sans ligne": (EQ, "vivants.map((a) => ligneAgent(a, terminee))", "vivants.map((a) => el('div', { class: 'eq-agent', dataset: { agent: a.id } }))", verifier_rendu),
    "carte complète perdue sous la ligne": (EQ, "el('div', { class: 'eq-agent-corps' }, carteAvecBrouillon(a, terminee)));", "el('div', { class: 'eq-agent-corps' }));", verifier_rendu),
    "ligne d'agent ouverte": (EQ, "return el('details', { class: `eq-agent ton-${def.ton}`,", "return el('details', { open: true, class: `eq-agent ton-${def.ton}`,", verifier_rendu),
    "repli des terminés ouvert": (EQ, "el('details', { class: 'eq-termines' },", "el('details', { open: true, class: 'eq-termines' },", verifier_rendu),
    "terminés sans âge": (EQ, "    a.etat_depuis ? age(a.etat_depuis, 'il-y-a', 'terminé ') : null);", "    null);", verifier_rendu),
    "terminés sans tâche": (EQ, "el('span', { class: a.tache ? 'eq-termine-tache' : 'eq-termine-tache discret', title: a.tache || null }, a.tache || 'aucune tâche déclarée'),\n    a.etat_depuis", "el('span', { class: 'eq-termine-tache' }, ''),\n    a.etat_depuis", verifier_rendu),
    "double repli (historique)": (EQ, "const repli = termines.length ? el('details', { class: 'eq-termines' },", "const repli = termines.length ? el('details', { class: 'historique' }, el('summary', {}, 'Historique'), el('details', { class: 'eq-termines' },", verifier_rendu),
    "périmètre sans résumé": (EQ, "return repli('eq-perimetre', resumePerimetre(q),\n    el('p'", "return repli('eq-perimetre', 'Périmètre et fichiers touchés',\n    el('p'", verifier_rendu),
    "dépendances sans résumé": (EQ, "repli('eq-dependances', resumeDependances(q, equipes),", "repli('eq-dependances', 'Dépendances',", verifier_rendu),
    "terminal sans phrase si pas de session": (EQ, "if (!avecSession.length) return section('Terminal en direct', null, el('div', { class: 'inconnu-bloc' }, phraseSansTerminal(q, agents, sans)));", "if (!avecSession.length) return null;", verifier_rendu),
    "agents vides sans phrase": (EQ, "} else if (!vivants.length) {\n    corps = el('div', { class: 'vide-calme' }, 'Aucun agent en cours.');", "} else if (!vivants.length) {\n    corps = null;", verifier_rendu),
    "fiche sans racine": (EQ, "ctx.contenu.append(el('div', { class: 'fiche' }, ...[", "ctx.contenu.append(...[", verifier_rendu),
}


@needs_node
@pytest.mark.parametrize("nom", MUTATIONS_EXECUTEES)
def test_mutation_executee_detectee(nom, copie_static):
    fichier, ancien, nouveau, verification = MUTATIONS_EXECUTEES[nom]
    cible = copie_static / fichier
    texte = cible.read_text(encoding="utf-8")
    assert ancien in texte, ancien  # la mutation doit s'appliquer
    cible.write_text(texte.replace(ancien, nouveau, 1), encoding="utf-8")
    with pytest.raises((AssertionError, KeyError, StopIteration, ValueError, TypeError)):
        verification(copie_static)


def test_couverture_des_verifications():
    toutes = {n for n, v in globals().items() if n.startswith("verifier_") and callable(v)}
    assert toutes == {"verifier_ordre", "verifier_hauteurs", "verifier_fonctions", "verifier_rendu"} and MUTATIONS and MUTATIONS_EXECUTEES, sorted(toutes)
    assert {v[3] for v in MUTATIONS_EXECUTEES.values()} == {verifier_fonctions, verifier_rendu}
