"""Affichage de l'état : consommation de jetons, sur la vue d'ensemble, la carte d'agent et la page d'équipe.

Analyse de texte du JS et du CSS de static/ (pas de navigateur dans pytest). `verifier_affichage(js)`
lève AssertionError ; la table MUTATIONS prouve qu'elle échoue quand on casse chaque comportement.
Les bornes de `jetons` (999, 1 000, 999 999, 1 000 000) sont aussi vérifiées dans un vrai navigateur
par tests/page/outils/scenario_consommation.py, puisque pytest n'exécute pas le JS.
"""
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "src" / "cime" / "page" / "static"


def _corps(texte, debut, fin):
    i = texte.index(debut)
    return texte[i:texte.index(fin, i)]


def verifier_affichage(js):
    commun, ensemble, equipe = js["commun.js"], js["vues/ensemble.js"], js["vues/equipe.js"]
    css = js["style.css"]
    # 1. libellés des deux nouvelles alarmes (sans le mot « compact » : garde-fou de la page)
    assert re.search(r"TYPES_ALARME = \{[^}]*\bgros_poste: 'Gros consommateur'", commun)
    assert re.search(r"TYPES_ALARME = \{[^}]*\bcontexte_au_repos: 'Contexte lourd au repos'", commun)
    # 2. formatage : fonctions pures, bornes strictes, troncature, virgule française, espace insécable
    jet = _corps(commun, "export function jetons(n)", "/** Une valeur de jetons")
    assert "if (typeof n !== 'number' || !Number.isFinite(n)) return null;" in jet
    assert "if (n < 1000) return String(Math.trunc(n));" in jet
    assert "if (n < 1_000_000) return `${Math.trunc(n / 1000)} k`;" in jet
    assert "return `${(Math.trunc(n / 100_000) / 10).toFixed(1).replace('.', ',')} M`;" in jet
    assert len(re.findall(r"export function jetons\(", commun)) == 1
    assert "jetons(n) ?? inconnu(null)" in commun
    pct = _corps(commun, "export function pourcent(part)", "\n}\n")
    assert "return `${Math.round(part * 100)}\\u00a0%`;" in pct
    # 3. carte d'agent : une ligne discrète, « conso inconnue » si null, rien pour l'utilisateur, dont sous-agents
    ligne = _corps(commun, "function ligneConso(agent)", "/** Page d'équipe")
    assert "if (agent.role === 'utilisateur') return null;" in ligne
    assert "if (!agent.consommation) return el('span', { class: 'conso-ligne inconnu' }, 'conso inconnue');" in ligne
    assert "'conso 15 min : ', jetonsOuInconnu(f15.lus), ' lus'" in ligne
    assert "f15.dont_sous_agents > 0 ? [' (dont ', jetonsOuInconnu(f15.dont_sous_agents), ' sous-agents)'] : null" in ligne
    assert "' · 60 min : ', jetonsOuInconnu(f60.lus), ' lus'" in ligne
    assert "source" not in ligne  # la provenance (source) reste écartée
    assert "f60.dont_sous_agents" not in ligne  # la part des sous-agents n'est dite que sur 15 min
    carte = _corps(commun, "export function carteAgent(agent, ctx, options = {})", "const PHRASE_AFFICHEE_MAX")
    assert "ligneConso(agent)," in carte
    assert "options.detail && agent.consommation ? grilleConso(agent.consommation) : null," in carte
    # 4. page d'équipe : grille à deux colonnes, écrits, tours, contexte moyen ; jamais 0 pour une valeur absente
    grille = _corps(commun, "function grilleConso(c)", "/**\n * Carte d'un agent")
    for ligne_grille in ("['écrits', (f) => jetonsOuInconnu(f.ecrits)]",
                         "['tours', (f) => (Number.isInteger(f.tours) ? String(f.tours) : inconnu(null))]",
                         "['contexte moyen', (f) => jetonsOuInconnu(f.contexte_moyen)]"):
        assert ligne_grille in grille, ligne_grille
    assert "'15 min'" in grille and "'60 min'" in grille
    assert "grid-template-columns" not in grille  # la mise en page est dans le CSS
    assert "carteAgent(a, ctx, { detail: true, equipeTerminee: terminee })" in equipe
    assert "carteAgent(a, ctx)" not in equipe
    # 5. Supervision : section après Avancement, avant les sessions hors organigramme ; un chiffre, une ligne, trois barres
    section = _corps(ensemble, "function sectionConsommation()", "// ----")
    assert "etat.consommation" in section or "const c = etat.consommation;" in section
    assert "inconnu(sourceEnEchec(etat, 'transcripts'), 'inconnue')" in section
    assert "'15 dernières min'" not in ensemble and "'60 dernières min'" not in ensemble and "Gros postes (15 min)" not in ensemble  # le détail par fenêtre est parti
    assert "'aucune consommation sur 15 min'" in ensemble
    assert "Array.isArray(c.gros_postes)" in section
    assert "enteteSection('Consommation', 'jetons lus, 15 dernières minutes')" in section
    assert "id: 'consommation'" in section
    assert "jetonsOuInconnu(f15.lus)" in section and "pluriel(f15.tours, 'tour')" in section
    assert "' sur 60 min'" in section and "jetonsOuInconnu(f60.lus)" in section
    assert "['tours : ', inconnu(null)]" in section and "['60 min : ', inconnu(null)]" in section  # une fenêtre inconnue se dit, jamais 0
    assert "ligneFenetre" not in ensemble and "ecrits" not in section  # plus de fenêtre « lus · écrits · tours » par ligne
    postes = _corps(ensemble, "function postesConso(postes)", "function sectionConsommation()")
    assert "plusGrosPostes(postes)" in postes and "largeurBarre(p.part_15min)" in postes
    assert "pourcent(p.part_15min)" in postes and "jetonsOuInconnu(p.lus_15min)" in postes
    assert "poste-plein" in postes and "rouge" not in postes and "ton-" not in postes  # barre neutre
    assert "largeur === null ? inconnu(null, 'part inconnue')" in postes  # part inconnue : « inconnue », jamais une barre à 0
    assert "agent" not in postes.replace("p.agent", "")  # le détail par agent (équipe, sous-agents) reste dans la carte de l'agent
    rendu = _corps(ensemble, "export function rendre", "\n}\n")
    assert rendu.count("sectionConsommation()") == 1 and rendu.count("sectionAlarmes()") == 1
    assert rendu.index("sectionAlarmes()") < rendu.index("sectionAvancement()") < rendu.index("sectionConsommation()") < rendu.index("sectionSessionsOrphelines()")
    # 6. couleur neutre et variables seulement dans le bloc CSS de la consommation
    bloc = css[css.index("/* Consommation : un chiffre"):css.index("/* Alarmes */")]
    assert ".poste-plein { display: block; height: 100%; background: var(--gris); }" in bloc
    assert not re.search(r"#[0-9A-Fa-f]{3,8}\b", bloc)
    assert "--rouge" not in bloc  # la barre reste neutre
    # 7. rien d'autre que l'exposition à l'action : aucun bouton dans le bloc de consommation
    assert "agir(" not in section and "button" not in section and "onclick" not in section
    assert "onclick" not in postes and "agir(" not in postes


@pytest.fixture(scope="module")
def js():
    fichiers = sorted(STATIC.glob("*.js")) + sorted((STATIC / "vues").glob("*.js")) + [STATIC / "style.css"]
    return {str(f.relative_to(STATIC)): f.read_text(encoding="utf-8") for f in fichiers}


def test_affichage(js):
    verifier_affichage(js)


def _remplace(fichier, ancien, nouveau):
    def mutation(js):
        assert ancien in js[fichier], ancien
        return {**js, fichier: js[fichier].replace(ancien, nouveau)}
    return mutation


NIV = "commun.js"
EN = "vues/ensemble.js"
MUTATIONS = {
    "libellé gros_poste absent": _remplace(NIV, "gros_poste: 'Gros consommateur',", ""),
    "libellé contexte_au_repos absent": _remplace(NIV, "contexte_au_repos: 'Contexte lourd au repos',", ""),
    "borne 1 000 incluse en k": _remplace(NIV, "if (n < 1000) return String(Math.trunc(n));", "if (n <= 1000) return String(Math.trunc(n));"),
    "borne 999 999 en M": _remplace(NIV, "if (n < 1_000_000) return `${Math.trunc(n / 1000)} k`;", "if (n <= 1_000_000) return `${Math.trunc(n / 1000)} k`;"),
    "arrondi au lieu de troncature (k)": _remplace(NIV, "`${Math.trunc(n / 1000)} k`", "`${Math.round(n / 1000)} k`"),
    "point décimal au lieu de la virgule": _remplace(NIV, ".replace('.', ',')", ""),
    "jetons null transformé en 0": _remplace(NIV, "if (typeof n !== 'number' || !Number.isFinite(n)) return null;", "if (typeof n !== 'number') return '0';"),
    "pourcentage sans espace insécable": _remplace(NIV, "`${Math.round(part * 100)}\\u00a0%`", "`${Math.round(part * 100)} %`"),
    "pourcentage décimal": _remplace(NIV, "`${Math.round(part * 100)}\\u00a0%`", "`${(part * 100).toFixed(1)}\\u00a0%`"),
    "utilisateur affiche une conso": _remplace(NIV, "if (agent.role === 'utilisateur') return null;", ""),
    "conso null remplacée par 0": _remplace(NIV, "return el('span', { class: 'conso-ligne inconnu' }, 'conso inconnue');", "return el('span', { class: 'conso-ligne' }, 'conso 15 min : 0 lus');"),
    "sous-agents toujours montrés": _remplace(NIV, "f15.dont_sous_agents > 0 ?", "f15.dont_sous_agents >= 0 ?"),
    "sous-agents jamais montrés": _remplace(NIV, "f15.dont_sous_agents > 0 ? [' (dont ', jetonsOuInconnu(f15.dont_sous_agents), ' sous-agents)'] : null", "null"),
    "sous-agents aussi sur 60 min": _remplace(NIV, "' · 60 min : ', jetonsOuInconnu(f60.lus), ' lus');",
                                              "' · 60 min : ', jetonsOuInconnu(f60.lus), ' lus', f60.dont_sous_agents > 0 ? ' (dont sous-agents)' : '');"),
    "provenance affichée": _remplace(NIV, "' · 60 min : ', jetonsOuInconnu(f60.lus), ' lus');", "' · 60 min : ', jetonsOuInconnu(f60.lus), ' lus · ', c.source);"),
    "grille sans contexte moyen": _remplace(NIV, "['contexte moyen', (f) => jetonsOuInconnu(f.contexte_moyen)],", ""),
    "tours inconnus comptés 0": _remplace(NIV, "(Number.isInteger(f.tours) ? String(f.tours) : inconnu(null))", "(Number.isInteger(f.tours) ? String(f.tours) : '0')"),
    "grille sur la vue d'ensemble": _remplace(NIV, "options.detail && agent.consommation ? grilleConso", "agent.consommation ? grilleConso"),
    "page d'équipe sans carte détaillée": _remplace("vues/equipe.js", "carteAgent(a, ctx, { detail: true, equipeTerminee: terminee })", "carteAgent(a, ctx)"),
    "section absente de la vue": _remplace(EN, "    sectionConsommation(),\n", ""),
    "section avant les alarmes": _remplace(EN, "    sectionAlarmes(),\n    sectionAvancement(),\n    sectionConsommation(),", "    sectionConsommation(),\n    sectionAlarmes(),\n    sectionAvancement(),"),
    "section avant l'avancement": _remplace(EN, "    sectionAvancement(),\n    sectionConsommation(),", "    sectionConsommation(),\n    sectionAvancement(),"),
    "racine null muette": _remplace(EN, "inconnu(sourceEnEchec(etat, 'transcripts'), 'inconnue')", "''"),
    "racine null sans source": _remplace(EN, "inconnu(sourceEnEchec(etat, 'transcripts'), 'inconnue')", "inconnu(null, 'inconnue')"),
    "liste de postes vide muette": _remplace(EN, "'aucune consommation sur 15 min'", "''"),
    "fenêtre de 15 min : retour de la ligne détaillée": _remplace(EN, "el('div', { class: 'conso-grand' }", "el('p', {}, '15 dernières min : ', jetonsOuInconnu(f15.ecrits)), el('div', { class: 'conso-grand' }"),
    "sous-titre de la section effacé": _remplace(EN, "'jetons lus, 15 dernières minutes'", "'jetons lus et écrits, agents et sous-agents'"),
    "grand chiffre sans valeur inconnue": _remplace(EN, "jetonsOuInconnu(f15.lus)), el('div', { class: 'conso-petit' }", "String(f15.lus ?? 0)), el('div', { class: 'conso-petit' }"),
    "tours inconnus comptés 0 sur la vue": _remplace(EN, "['tours : ', inconnu(null)]", "'0 tour'"),
    "fenêtre de 60 min inconnue comptée 0": _remplace(EN, "['60 min : ', inconnu(null)]", "'0 sur 60 min'"),
    "barre sans part inconnue dite": _remplace(EN, "largeur === null ? inconnu(null, 'part inconnue')", "largeur === null ? ''"),
    "pourcentage hors de la barre": _remplace(EN, "`${pourcent(p.part_15min)} des jetons lus du projet`", "'une part'"),
    "barre rouge": _remplace(EN, "class: 'poste-plein'", "class: 'poste-plein rouge'"),
    "barre avec ton d'alarme": _remplace(EN, "class: 'poste-plein'", "class: 'poste-plein ton-rouge'"),
    "bouton sur un gros poste": _remplace(EN, "el('span', { class: 'mono poste-valeur' }, jetonsOuInconnu(p.lus_15min)));", "el('span', { class: 'mono poste-valeur' }, jetonsOuInconnu(p.lus_15min)), el('button', { onclick: () => {} }, 'agir'));"),
    "couleur en dur dans la barre": _remplace("style.css", ".poste-plein { display: block; height: 100%; background: var(--gris); }", ".poste-plein { display: block; height: 100%; background: #8C8880; }"),
    "barre rouge en CSS": _remplace("style.css", ".poste-plein { display: block; height: 100%; background: var(--gris); }", ".poste-plein { display: block; height: 100%; background: var(--rouge); }"),
}


@pytest.mark.parametrize("nom", MUTATIONS)
def test_mutation_detectee(nom, js):
    with pytest.raises(AssertionError):
        verifier_affichage(MUTATIONS[nom](js))


def test_couverture_des_verifications():
    toutes = {n for n, v in globals().items() if n.startswith("verifier_") and callable(v)}
    assert toutes == {"verifier_affichage"} and MUTATIONS, sorted(toutes)
