"""Le rail de l'accueil et le détail au clic.

Analyse de texte du JS et du CSS de static/ (pas de navigateur dans pytest). `verifier_rail_accueil(js)` lève
AssertionError ; la table MUTATIONS prouve qu'elle échoue quand on casse chaque comportement. Le rendu réel (les quatre
blocs, un clic sur chacune des 8 pièces, sur un agent, une enveloppe, la porte de l'utilisateur, « ← Retour » et Échap, aucune
barre de défilement de page à 1440×900, les captures) est vérifié dans un vrai navigateur par
tests/page/outils/scenario_rail.py.
"""
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "src" / "cime" / "page" / "static"

TAILLES_PERMISES = {"11", "12", "13", "14", "16", "20"}


def _corps(texte, debut, fin):
    i = texte.find(debut)
    assert i >= 0, debut
    j = texte.find(fin, i)
    assert j >= 0, fin
    return texte[i:j]


def _regle(css, selecteur):
    """Le corps de la règle CSS dont le sélecteur est exactement `selecteur`."""
    m = re.search(r"(?:^|\n)" + re.escape(selecteur) + r" \{([^}]*)\}", css)
    assert m, selecteur
    return m.group(1)


def verifier_rail_accueil(js):
    commun, app, scene, rail, fil, css = (js[n] for n in ("commun.js", "app.js", "vues/scene.js", "vues/rail.js", "vues/fil.js", "style.css"))

    # 1. la disposition : plateau | rail de 344 px, gouttières de 20 px, hauteur 100vh − 56 px, le rail défile seul
    grille = _regle(css, ".accueil")
    assert "display: grid" in grille and "grid-template-columns: minmax(0, 1fr) 344px" in grille and "gap: 20px" in grille
    colonne = _regle(css, ".rail")
    assert "height: calc(100vh - 56px - 40px)" in colonne and "overflow-y: auto" in colonne
    assert "flex-direction: column" in colonne and "gap: 20px" in colonne
    assert "ctx.contenu.append(el('section', { class: 'accueil' }, plateau, rail));" in scene
    assert "const rail = el('aside', { class: 'rail', id: 'rail'," in scene
    mobile = _corps(css, "@media (max-width: 760px) {\n  :root", "\n}\n")
    assert "  .accueil { grid-template-columns: minmax(0, 1fr); gap: 0; }" in mobile
    assert "  .rail { height: auto; overflow: visible; gap: 20px; padding: 0 16px; }" in mobile

    # 2. le composant blocRail(titre, compteur, lien, contenu) : un titre, un compteur, un lien à droite, le contenu
    bloc = _corps(rail, "export function blocRail(", "\n}\n")
    assert "export function blocRail(titre, compteur, lien, contenu, classe = '', droite = null)" in bloc
    assert "droite ? el('div', { class: 'rail-tete' }, intitule, droite) : intitule," in bloc  # l'interrupteur du mode autonome, à droite du titre
    assert "el('h2', {}," in bloc and "class: 'compte'" in bloc and "class: 'lien-bloc', href: lien.href" in bloc
    assert "compteur ? el(" in bloc and "lien ? el(" in bloc
    assert "class: `bloc-rail${classe ? ` ${classe}` : ''}`" in bloc

    # 3. « Ce qui t'attend » : les 3 plus anciennes, cartes de la page, lien « n autres points → », vide, inconnu
    assert "export const MAX_ATTENTES = 3;" in rail
    attentes = _corps(rail, "function blocAttentes(", "\n}\n")
    assert "const titre = 'Ce qui t’attend';" in attentes
    assert "const attentes = attentesOuvertes(etat);" in attentes
    assert "const mode = interrupteurMode(etat);" in attentes and "const encadre = encadreMode(etat, redessiner);" in attentes  # le mode autonome reste dessiné, même sans attente
    assert attentes.count("classe, mode)") == 3, "l'interrupteur est à droite du titre dans les trois cas : inconnu, rien n'attend, des attentes"
    assert "if (attentes === null) {" in attentes
    assert "'Ce qui t’attend : inconnu (sources en échec).'" in attentes and "class: 'inconnu-bloc'" in attentes
    assert "if (!attentes.length) {" in attentes
    assert "el('div', { class: 'rail-calme' }, '✓ Rien ne t’attend. Tout avance sans toi.')" in attentes
    assert "const triees = trierAttentes(attentes);" in attentes
    assert "(depliees ? triees : triees.slice(0, MAX_ATTENTES)).map((a) => cartePourRail(a, etat, nouvelles))" in attentes
    assert "const reste = triees.length - MAX_ATTENTES;" in attentes and "reste > 0 ?" in attentes
    assert "const depliees = attentesDepliees && reste > 0;" in attentes
    assert "el('button', { type: 'button', class: 'lien-autres', 'aria-expanded': String(depliees)," in attentes
    assert "onclick: () => { attentesDepliees = !depliees; redessiner(); } }," in attentes
    assert "depliees ? 'replier ▴' : `${pluriel(reste, 'autre point', 'autres points')} ▾`" in attentes
    assert "let attentesDepliees = false;" in rail
    assert "[...attentes].sort((a, b) => rangGenre(a) - rangGenre(b) || plusAncienDabord(a, b))" in _corps(rail, "export function trierAttentes(", "\n}\n")
    assert "blocRail(titre, attentes.length, null," in attentes
    assert "const plusAncienDabord = (a, b) => instant(a.depuis) - instant(b.depuis);" in rail
    assert "const instant = (iso) => Date.parse(iso) || Number.MAX_SAFE_INTEGER;" in rail
    assert "background: var(--vert-fond)" in _regle(css, ".rail-calme") and "color: var(--vert-clair)" in _regle(css, ".rail-calme")

    # 4. les cartes et leurs boutons sont ceux de la page : exportés par commun.js, jamais recopiés
    assert "export function carteAttente(attente, ctx)" in commun and "function actionsAttente(" in commun
    assert "carteAttente(attente, { etat })" in _corps(rail, "function cartePourRail(", "\n}\n")
    for mot in ("Autoriser", "Refuser", "Accorder", "Trancher", "Clôturer", "Déposer", "bouton-vert", "bouton-principal", "agir("):
        assert mot not in rail, mot
    assert "carteAttente" in _corps(rail, "import {", "} from")

    # 5. « Ce qui coince » : grave puis à voir, trois au plus, jamais info, absent sans alarme
    assert "export const MAX_ALARMES = 3;" in rail
    coince = _corps(rail, "function blocCoince(", "\n}\n")
    assert "if (!Array.isArray(etat.alarmes)) return null;" in coince
    assert "filter((a) => a.gravite === 'grave' || a.gravite === 'a_voir')" in coince and "'info'" not in coince
    assert "const rang = (a) => GRAVITES[a.gravite].rang;" in coince and "sort((a, b) => rang(a) - rang(b))" in coince
    assert "if (!alarmes.length) return null;" in coince
    assert "alarmes.slice(0, MAX_ALARMES)" in coince
    assert "blocRail('Ce qui coince', alarmes.length, { href: '#/supervision', texte: 'Tout voir →' }," in coince
    assert "`rail-ligne ton-${tonAlarme(a)}`" in coince and "class: 'pastille'" in coince
    assert "el('span', { class: 'rail-titre' }, TYPES_ALARME[a.type] || a.type)" in coince and "class: 'rail-cible'" in coince and "age(a.depuis, 'court')" in coince
    assert "'bloc-coince'" in coince and "background: var(--gris-fond)" in _regle(css, ".bloc-coince .compte")
    assert "grave: { mot: 'Grave', ton: 'rouge', rang: 0 }" in commun and "a_voir: { mot: 'À voir', ton: 'ambre', rang: 1 }" in commun

    # 6. « Qui travaille » : les trois états, jamais un worker terminé, tâche sinon dernière phrase, un clic ouvre l'agent
    assert "const ETATS_QUI_TRAVAILLE = new Set(['travaille', 'attend_autorisation', 'attend_reponse']);" in rail
    assert "const agentVisible = (a, etat) => a.role !== 'utilisateur' && !workerTermine(a, etat.alarmes);" in rail
    travaille = _corps(rail, "function blocTravaille(", "\n}\n")
    assert "etat.agents.filter((a) => agentVisible(a, etat) && ETATS_QUI_TRAVAILLE.has(etatAffiche(a)))" in travaille
    assert "'Personne ne travaille en ce moment.'" in travaille and "if (!Array.isArray(etat.agents))" in travaille
    ligne = _corps(rail, "function ligneAgent(", "\n}\n")
    assert "const quoi = agent.tache || (agent.derniere_phrase ? finDePhrase(agent.derniere_phrase) : null);" in ligne
    assert "onclick: () => ouvrir({ type: 'agent', id: agent.id })" in ligne
    assert "class: 'rail-qui' }, nomAgent(agent.id)" in ligne and "age(agent.etat_depuis, 'court')" in ligne
    assert "`rail-ligne ton-${def.ton}`" in ligne and "joindre([avecEtat ? def.mot : null, agent.etat_depuis ? age(agent.etat_depuis, 'court') : null], ' · ')" in ligne
    assert "font-weight: 600" in _regle(css, ".rail-qui")

    # 7. « Derniers échanges » : les trois derniers, de → à, attente en ambre, cime grisé, non lu gardé, vide
    assert "export const MAX_ECHANGES = 3;" in rail
    echanges = _corps(rail, "function blocEchanges(", "\n}\n")
    assert "const lien = { href: '#/fil', texte: 'Tout le fil →' };" in echanges
    assert "sort((a, b) => (Date.parse(b.horodatage) || 0) - (Date.parse(a.horodatage) || 0)).slice(0, MAX_ECHANGES)" in echanges
    assert "`${nomAgent(m.de)} → ${nomAgent(m.a)}`" in echanges and "age(m.horodatage, 'court')" in echanges
    assert "class: 'echange-resume', title: m.resume }, m.resume)," in echanges
    assert "m.en_attente ? el('span', { class: 'echange-attend' }, phraseAttente(m, true)) : null" in echanges
    assert "m.de === 'cime' || m.a === 'cime' ? 'echange-cime' : null" in echanges
    assert "estNonLu(m) ? repereNonLu(m) : null" in echanges
    assert "onclick: () => ouvrir({ type: 'message', id: m.id })" in echanges
    assert "'Aucun échange récent.'" in echanges and "if (!Array.isArray(etat.fil))" in echanges
    assert "color: var(--discret)" in _regle(css, ".echange-cime .echange-qui, .echange-cime .echange-resume")
    assert "color: var(--ambre)" in _regle(css, ".echange-attend")
    assert "export function repereNonLu(m)" in commun and "'Marquer comme lu'" in _corps(commun, "export function repereNonLu(m)", "\n}\n")

    # 8. le détail d'une équipe : nom, statut, mission, deux chiffres, ses attentes avec boutons, ses agents, la fiche
    equipe = _corps(rail, "function detailEquipe(", "\n}\n")
    assert "el('h2', {}, q.nom), puceStatut(q.statut, statutEquipeAffiche(q, etat.alarmes))" in equipe
    assert "q.mission ? el('p', { class: 'detail-texte' }, q.mission) : null" in equipe
    assert "chiffre(`${av.faites} / ${total}`, 'tâches faites'," in equipe and "class: 'jauge-barre'" in equipe and "class: 'jauge-plein'" in equipe
    assert "const retard = q.retard_sur_base;" in equipe
    assert "if (retard === null || retard === undefined) chiffreRetard = chiffre(inconnu(sourceEnEchec(etat, 'git')), `retard sur ${base}`);" in equipe
    assert "else if (retard === 0) chiffreRetard = chiffre('à jour', `retard sur ${base}`);" in equipe
    assert "else chiffreRetard = chiffre(String(retard)," in equipe
    assert "filter((a) => equipeDeLAttente(a, etat) === q.nom).sort(plusAncienDabord)" in equipe
    assert "section('Attend de toi', el('div', { class: 'attentes' }, attentes.map((a) => cartePourRail(a, etat, nouvelles))))" in equipe
    assert "filter((a) => a.equipe === q.nom && agentVisible(a, etat))" in equipe
    assert "ligneAgent(a, etat, ouvrir, { avecEtat: true })" in equipe
    assert "lienBouton(routeEquipe(q.nom), 'Ouvrir la fiche complète →')" in equipe
    assert "font-family: var(--mono); font-size: 20px; font-weight: 600" in _regle(css, ".detail-tete h2")

    # 9. le détail d'un agent : statut, tâche, dernière phrase, contexte en %, modèle, dettes, file, fiche de l'équipe
    agent = _corps(rail, "function detailAgent(", "\n}\n")
    assert "el('h2', {}, nomAgent(agent.id)), pastilleEtat(def.cle, def)" in agent
    assert "fait('Tâche', agent.tache ||" in agent and "fait('Dernière phrase', finDePhrase(agent.derniere_phrase))" in agent
    assert "pourcent(agent.contexte.tokens / agent.contexte.limite)" in agent and "fait('Contexte', contexte)" in agent
    assert "fait('Modèle', agent.modele ||" in agent
    assert "const dettes = agent.dettes;" in agent and "section('Dettes', Array.isArray(dettes)" in agent
    assert "`${d.attendu} de ${nomAgent(d.de)}`" in agent and "'Aucune dette ouverte.'" in agent
    assert "const file = agent.file;" in agent and "section('File', Array.isArray(file)" in agent
    assert "`${nomAgent(m.de)} · ${NATURES_FIL[m.nature] || m.nature || 'message'} — ${m.resume}`" in agent and "'Rien en file.'" in agent
    assert "lienBouton(routeEquipe(agent.equipe), 'Ouvrir la fiche de l’équipe →')" in agent

    # 10. le détail d'un message : de → à, nature, résumé entier, état de livraison, « Voir dans le fil → »
    message = _corps(rail, "function detailMessage(", "\n}\n")
    assert "el('h2', {}, `${nomAgent(m.de)} → ${nomAgent(m.a)}`)" in message
    assert "fait('Nature', libelleNature(m))" in message
    assert "el('p', { class: 'detail-texte' }, m.resume)" in message and "slice" not in message and "finDePhrase" not in message
    assert "fait('Livraison', m.etat_livraison ? (LIVRAISON[m.etat_livraison] || m.etat_livraison) : 'sans suivi de livraison')" in message
    assert "lienBouton(routeFil({ agent: agentDuFil }), 'Voir dans le fil →')" in message
    assert "id !== 'utilisateur' && id !== 'cime'" in message
    assert "pris_en_compte: 'pris en compte'" in rail and "export const libelleNature" in commun

    # 11. L'utilisateur : pas de détail, le rail revient aux blocs et « Ce qui t'attend » clignote une fois
    dessin = _corps(rail, "export function rendreRail(", "\n}\n")
    assert "const trouve = !telephone && selection && selection.type !== 'utilisateur' ? trouverCible(selection, etat) : null;" in dessin
    assert "  } else {\n    vider(conteneur, blocAttentes(" in dessin
    assert "vider(conteneur, blocAttentes(etat, nouvelles, clignote, redessiner), blocCoince(etat), blocTravaille(etat, ouvrir), blocEchanges(etat, ouvrir));" in dessin
    assert "const classe = clignote ? 'clignote' : '';" in attentes
    assert "clignotement = Boolean(cible && cible.type === 'utilisateur');" in scene
    assert "redessiner: dessinerRail, clignote: clignotement, telephone });\n  clignotement = false;" in scene
    assert "animation: clignote 0.8s ease-in-out 1" in _regle(css, ".bloc-rail.clignote")
    assert "@keyframes clignote { 0%, 100% { background: transparent; } 50% { background: var(--ambre-fond); } }" in css

    # 12. fermeture : « ← Retour », Échap (focus partout), clic dans le vide, cible disparue ; sélection annulée
    assert "el('button', { type: 'button', class: 'retour', onclick: fermer }, '← Retour')" in dessin
    assert "vider(conteneur, el('section', { class: 'detail-rail', 'aria-label': 'Détail' }, retour, detailCible(trouve, etat, ouvrir, nouvelles)));" in dessin
    assert "fermer: () => choisir(null)" in scene and "surVide: () => { basculerLegende(false); choisir(null); }," in scene
    echap = _corps(scene, "// Échap ferme aussi le détail", "\n});\n")
    assert "ev.key !== 'Escape' || !actif || plateau.contains(ev.target) || document.querySelector('dialog[open]')" in echap
    assert "if (selection) choisir(null);" in echap
    assert "document.addEventListener('keydown'" in echap
    dessiner = _corps(scene, "function dessinerRail()", "\n}\n")
    assert "if (!actif || !contexteRendu) return;" in dessiner
    assert "if (selection && selection.type !== 'utilisateur' && !trouverCible(selection, etat)) {\n    choisir(null);" in dessiner
    assert "    return;\n  }" in dessiner
    choix = _corps(scene, "function choisir(cible)", "\n}\n")
    assert "selection = cible ?? null;" in choix and "objetScene?.selectionner?.(selection);" in choix
    assert "for (const f of abonnes) f(selection);" in choix
    trouver = _corps(rail, "export function trouverCible(", "\n}\n")
    for type_, liste, recherche in (("equipe", "equipes", "etat.equipes.find((q) => q.nom === cible.nom)"),
                                    ("agent", "agents", "etat.agents.find((a) => a.id === cible.id)"),
                                    ("message", "fil", "etat.fil.find((m) => m.id === cible.id)")):
        assert f"cible.type === '{type_}' && Array.isArray(etat.{liste})" in trouver
        assert recherche in trouver
    assert trouver.rstrip().endswith("return null;")

    # 13. le détail se met à jour sur place : tout vient de la sélection et de l'instantané, rien du DOM ; défilement gardé
    assert "querySelector" not in rail and ".dataset" not in rail and "getAttribute" not in rail and "scrollTop" not in rail
    assert "rendreRail(rail, { etat, selection," in dessiner and "const etat = contexteRendu.etat;" in dessiner
    assert "const haut = vue === vueRail ? defilementRail : 0;" in dessiner
    assert "rail.scrollTop = haut;" in dessiner and "defilementRail = rail.scrollTop;" in dessiner
    assert "rail.addEventListener('scroll', () => { if (rail.isConnected) defilementRail = rail.scrollTop; });" in scene
    assert "  contexteRendu = ctx;\n  actif = true;\n  dessinerRail();\n" in _corps(scene, "export function rendre(ctx)", "\n}\n")
    assert "return () => { actif = false; fermerFeuilleDetail(); fermerFeuilleAttentes(); };" in scene
    assert "surSelection((cible) => {" in scene and "  dessinerRail();\n});" in scene
    assert "export function surSelection(rappel)" in scene

    # 14. le bandeau a disparu partout ; le compteur de l'en-tête dit ce qui attend l'utilisateur, en clair
    for nom in ("commun.js", "vues/fil.js", "vues/scene.js", "vues/rail.js", "vues/ensemble.js", "vues/equipe.js", "app.js"):
        assert "bandeau" not in js[nom].lower(), nom
    assert not re.search(r"\.bandeau(?![-\w])", css)  # l'ancien bandeau « Ce qui t'attend » : seul le bandeau du téléphone (.bandeau-attentes) existe
    assert "voirDansBandeau" not in fil and ".click()" not in fil
    assert "href: '#/' }, 'voir dans Ce qui t’attend'" in fil
    compteur = _corps(commun, "function compteurAttentes(etat)", "\n}\n")
    assert "const phrase = `${pluriel(attentes.length, 'point')} ${attentes.length === 1 ? 't’attend' : 't’attendent'}`;" in compteur
    assert "if (!attentes || !attentes.length) return null;" in compteur
    assert "el('a', { class: 'compteur-attentes', href: '#/'," in compteur and "}, phrase);" in compteur
    assert "color: var(--ambre)" in _regle(css, ".compteur-attentes") and "rouge" not in _regle(css, ".compteur-attentes")
    assert "n ? el('a', { class: 'org-utilisateur-attentes', href: '#/' }," in js["vues/ensemble.js"]

    # 15. image figée : les boutons d'action du rail et du détail sont désactivés, avec leur explication
    assert "let actionsFigees = false;" in commun
    assert "export const PHRASE_ACTIONS_FIGEES = 'L’hôte ne répond plus';" in commun
    assert "export function definirActionsFigees(fige) {\n  actionsFigees = Boolean(fige);\n}" in commun
    actions = _corps(commun, "function actionsAttente(", "\n}\n")
    assert "const occupe = enCours.has(attente.id) || actionsFigees;" in actions
    assert "const titre = actionsFigees ? PHRASE_ACTIONS_FIGEES : null;" in actions
    assert actions.count("disabled: occupe") == 8 and actions.count("title: titre") == 9  # 8 boutons ou champs, et l'étiquette du dépôt
    assert "actionsFigees ? PHRASE_ACTIONS_FIGEES : null" in _corps(commun, "export function repereNonLu(m)", "\n}\n")
    figer = _corps(scene, "function majFige()", "\n}\n")
    assert "if (fige !== figeRail) {\n    figeRail = fige;\n    definirActionsFigees(fige);" in figer and "\n    dessinerRail();\n    if (dernierEtat) majFeuilleAttentes(dernierEtat);" in figer
    assert "definirActionsFigees" in _corps(scene, "import {", "} from '../commun.js'")

    # 16. une attente qui arrive : les ids déjà vus en variable de module, fondu de 200 ms, coupé en mouvement réduit
    assert "let attentesVues = null;" in rail
    assert "const nouvelles = new Set(attentesVues && ids ? ids.filter((id) => !attentesVues.has(id)) : []);" in dessin
    assert "if (ids) attentesVues = new Set(ids);" in dessin
    assert "const ids = Array.isArray(etat.attentes_utilisateur) ? etat.attentes_utilisateur.map((a) => a.id) : null;" in dessin
    assert "if (nouvelles.has(attente.id)) carte.classList.add('arrive');" in rail
    assert "animation: arrivee 200ms ease-out" in _regle(css, ".attente.arrive")
    assert "@keyframes arrivee { from { opacity: 0; } to { opacity: 1; } }" in css
    assert "@media (prefers-reduced-motion: reduce) { .attente.arrive, .bloc-rail.clignote { animation: none; } }" in css
    assert "halo" not in rail.lower() and "halo" not in scene.lower()  # le halo ambre est dessiné par la scène

    # 17. le CSS du rail n'emploie que l'existant : variables, tailles, graisses, rayons ; rien de rouge sans alarme grave
    region = _corps(css, "/* ---------- Le rail de la scène", "/* ---------- L'hôte ne répond pas")
    cartes = _corps(css, "/* ---------- Les attentes de l'utilisateur", ".bouton {\n")
    for ajoute in (region, cartes):
        assert not re.findall(r"#[0-9A-Fa-f]{3,8}\b", ajoute)
        assert set(re.findall(r"font-size: (\d+)px", ajoute)) <= TAILLES_PERMISES
        assert set(re.findall(r"font-weight: (\d+)", ajoute)) <= {"400", "500", "600"}
        assert "box-shadow" not in ajoute
        assert set(re.findall(r"border-radius: ([^;]+);", ajoute)) <= {"var(--rayon)", "var(--rayon-petit)", "50%", "999px"}
        assert set(re.findall(r"(?<![\w-])(?:gap|padding|margin)(?:-[a-z]+)?: ([^;]+);", ajoute)) <= ESPACES
        assert "rouge" not in ajoute
    assert "'rouge'" not in rail and "ton-rouge" not in rail
    assert "font-family: var(--mono)" not in cartes
    assert "color: var(--ambre)" in _regle(css, ".etiquette")
    assert "color: var(--bleu-clair)" in _corps(cartes, '.attente[data-nature="cloture"] .etiquette', "}")
    assert "border-left-color: var(--bleu)" in cartes and "-webkit-line-clamp: 2" in _regle(css, ".attente-texte")


# les espacements du système (8 / 16 / 20 / 32 px), sous toutes les formes de raccourci que le rail emploie
ESPACES = {"0", "8px", "16px", "20px", "32px", "0 8px", "8px 0", "8px 16px", "8px 0 0", "0 0 8px", "auto"}


@pytest.fixture(scope="module")
def js():
    fichiers = sorted(STATIC.glob("*.js")) + sorted((STATIC / "vues").glob("*.js")) + [STATIC / "style.css"]
    return {str(f.relative_to(STATIC)): f.read_text(encoding="utf-8") for f in fichiers}


def test_rail_accueil(js):
    verifier_rail_accueil(js)


def _remplace(fichier, ancien, nouveau):
    def mutation(js):
        assert ancien in js[fichier], ancien
        return {**js, fichier: js[fichier].replace(ancien, nouveau)}
    return mutation


NIV = "commun.js"
SC = "vues/scene.js"
RA = "vues/rail.js"
FIL = "vues/fil.js"
CSS = "style.css"
MUTATIONS = {
    # disposition
    "rail à 360 px": _remplace(CSS, "grid-template-columns: minmax(0, 1fr) 344px; gap: 20px;", "grid-template-columns: minmax(0, 1fr) 360px; gap: 20px;"),
    "gouttière de 16 px": _remplace(CSS, "344px; gap: 20px; align-items: start; }", "344px; gap: 16px; align-items: start; }"),
    "accueil sans grille": _remplace(CSS, ".accueil { display: grid;", ".accueil { display: block;"),
    "rail sans défilement": _remplace(CSS, "min-height: 0; overflow-y: auto;\n  display: flex;", "min-height: 0; overflow-y: visible;\n  display: flex;"),
    "rail de hauteur libre": _remplace(CSS, "height: calc(100vh - 56px - 40px); min-height: 0;", "height: auto; min-height: 0;"),
    "rail de 100 vh": _remplace(CSS, "height: calc(100vh - 56px - 40px); min-height: 0;", "height: 100vh; min-height: 0;"),
    "rail en ligne": _remplace(CSS, "overflow-y: auto;\n  display: flex; flex-direction: column; gap: 20px;", "overflow-y: auto;\n  display: flex; flex-direction: row; gap: 20px;"),
    "blocs collés": _remplace(CSS, "overflow-y: auto;\n  display: flex; flex-direction: column; gap: 20px;", "overflow-y: auto;\n  display: flex; flex-direction: column; gap: 8px;"),
    "rail non attaché": _remplace(SC, "{ class: 'accueil' }, plateau, rail)", "{ class: 'accueil' }, plateau)"),
    "rail sous une autre classe": _remplace(SC, "el('aside', { class: 'rail', id: 'rail',", "el('aside', { class: 'colonne', id: 'rail',"),
    "mobile : deux colonnes": _remplace(CSS, "  .accueil { grid-template-columns: minmax(0, 1fr); gap: 0; }", "  .accueil { grid-template-columns: minmax(0, 1fr) 344px; gap: 0; }"),
    "mobile : rail de hauteur fixe": _remplace(CSS, "  .rail { height: auto; overflow: visible; gap: 20px;", "  .rail { height: calc(100vh - 96px); overflow: visible; gap: 20px;"),
    "mobile : rail qui défile": _remplace(CSS, "  .rail { height: auto; overflow: visible; gap: 20px;", "  .rail { height: auto; overflow: auto; gap: 20px;"),
    # blocRail
    "bloc sans compteur": _remplace(RA, "    compteur ? el('span', { class: 'compte', 'aria-label': pluriel(compteur, 'point') }, String(compteur)) : null,\n", ""),
    "bloc sans lien": _remplace(RA, "    lien ? el('a', { class: 'lien-bloc', href: lien.href }, lien.texte) : null);", "    null);"),
    "bloc : arguments permutés": _remplace(RA, "export function blocRail(titre, compteur, lien, contenu, classe = '', droite = null)", "export function blocRail(titre, lien, compteur, contenu, classe = '', droite = null)"),
    "bloc sans h2": _remplace(RA, "  const intitule = el('h2', {},\n    titre,", "  const intitule = el('h3', {},\n    titre,"),
    "bloc : droite ignorée": _remplace(RA, "droite ? el('div', { class: 'rail-tete' }, intitule, droite) : intitule,", "intitule,"),
    "bloc : interrupteur sous le titre": _remplace(RA, "droite ? el('div', { class: 'rail-tete' }, intitule, droite) : intitule,", "intitule, droite,"),
    "attentes : interrupteur absent quand rien n'attend": _remplace(RA, "'✓ Rien ne t’attend. Tout avance sans toi.')], classe, mode);", "'✓ Rien ne t’attend. Tout avance sans toi.')], classe);"),
    "attentes : interrupteur absent quand inconnu": _remplace(RA, "'Ce qui t’attend : inconnu (sources en échec).')], classe, mode);", "'Ce qui t’attend : inconnu (sources en échec).')], classe);"),
    "attentes : interrupteur absent avec des attentes": _remplace(RA, "  ], classe, mode);", "  ], classe);"),
    "bloc sans classe d'état": _remplace(RA, "class: `bloc-rail${classe ? ` ${classe}` : ''}`", "class: 'bloc-rail'"),
    # Ce qui t'attend
    "plafond de 4 attentes": _remplace(RA, "export const MAX_ATTENTES = 3;", "export const MAX_ATTENTES = 4;"),
    "attentes les plus récentes d'abord": _remplace(RA, "rangGenre(a) - rangGenre(b) || plusAncienDabord(a, b)", "rangGenre(a) - rangGenre(b) || plusAncienDabord(b, a)"),
    "attentes non triées": _remplace(RA, "const triees = trierAttentes(attentes);", "const triees = [...attentes];"),
    "attente sans date en tête": _remplace(RA, "Date.parse(iso) || Number.MAX_SAFE_INTEGER", "Date.parse(iso) || 0"),
    "autres points : lien au lieu du bouton": _remplace(RA, "el('button', { type: 'button', class: 'lien-autres', 'aria-expanded': String(depliees),", "el('a', { href: '#/supervision', class: 'lien-autres', 'aria-expanded': String(depliees),"),
    "autres points : ne déplie pas": _remplace(RA, "onclick: () => { attentesDepliees = !depliees; redessiner(); } },", "onclick: () => { redessiner(); } },"),
    "autres points : replié pour toujours": _remplace(RA, "const depliees = attentesDepliees && reste > 0;", "const depliees = false;"),
    "autres points : déplié d'office": _remplace(RA, "let attentesDepliees = false;", "let attentesDepliees = true;"),
    "autres points : pas de retour au repli": _remplace(RA, "depliees ? 'replier ▴' :", "depliees ? 'tout voir' :"),
    "lien des autres points toujours là": _remplace(RA, "reste > 0 ?", "true ?"),
    "reste mal compté": _remplace(RA, "const reste = triees.length - MAX_ATTENTES;", "const reste = triees.length;"),
    "autres points sans pluriel": _remplace(RA, "pluriel(reste, 'autre point', 'autres points')} ▾", "pluriel(reste, 'point')} ▾"),
    "autres points sans flèche": _remplace(RA, "'autres points')} ▾`", "'autres points')}`"),
    "vide : phrase changée": _remplace(RA, "'✓ Rien ne t’attend. Tout avance sans toi.'", "'Rien.'"),
    "vide en carte pleine": _remplace(RA, "el('div', { class: 'rail-calme' }, '✓", "el('div', { class: 'vide-calme' }, '✓"),
    "vide : bandeau pas vert": _remplace(CSS, "background: var(--vert-fond); color: var(--vert-clair); font-size: 14px", "background: var(--ambre-fond); color: var(--ambre); font-size: 14px"),
    "inconnu : phrase changée": _remplace(RA, "'Ce qui t’attend : inconnu (sources en échec).'", "'Rien.'"),
    "inconnu : jamais testé": _remplace(RA, "if (attentes === null) {", "if (attentes === undefined) {"),
    "vide : jamais testé": _remplace(RA, "if (!attentes.length) {", "if (attentes.length > 99) {"),
    "inconnu : titre changé": _remplace(RA, "const titre = 'Ce qui t’attend';", "const titre = 'À faire';"),
    "attentes : compteur absent": _remplace(RA, "blocRail(titre, attentes.length, null,", "blocRail(titre, null, null,"),
    "attentes : instantané ignoré": _remplace(RA, "const attentes = attentesOuvertes(etat);\n  // le mode autonome", "const attentes = etat.autre;\n  // le mode autonome"),
    "carte recopiée": _remplace(RA, "const carte = carteAttente(attente, { etat });", "const carte = el('article', { class: 'attente' }, 'Autoriser');"),
    "carte non exportée": _remplace(NIV, "export function carteAttente(attente, ctx)", "function carteAttente(attente, ctx)"),
    "bouton recopié dans le rail": _remplace(RA, "  return carte;\n}", "  carte.append(el('button', {}, 'Autoriser'));\n  return carte;\n}"),
    # Ce qui coince
    "info dans ce qui coince": _remplace(RA, "a.gravite === 'grave' || a.gravite === 'a_voir')", "a.gravite !== 'info' || a.gravite === 'info')"),
    "à voir avant grave": _remplace(RA, "sort((a, b) => rang(a) - rang(b))", "sort((a, b) => rang(b) - rang(a))"),
    "alarmes non triées": _remplace(RA, ".sort((a, b) => rang(a) - rang(b))", ""),
    "plafond de 5 alarmes": _remplace(RA, "export const MAX_ALARMES = 3;", "export const MAX_ALARMES = 5;"),
    "alarmes non plafonnées": _remplace(RA, "alarmes.slice(0, MAX_ALARMES)", "alarmes"),
    "bloc affiché sans alarme": _remplace(RA, "  if (!alarmes.length) return null;\n", ""),
    "alarmes inconnues : bloc vide": _remplace(RA, "  if (!Array.isArray(etat.alarmes)) return null;\n", "  if (!etat.alarmes) return null;\n"),
    "lien Tout voir changé": _remplace(RA, "texte: 'Tout voir →'", "texte: 'Voir →'"),
    "lien Tout voir vers le fil": _remplace(RA, "{ href: '#/supervision', texte: 'Tout voir →' }", "{ href: '#/fil', texte: 'Tout voir →' }"),
    "pastille toujours rouge": _remplace(RA, "`rail-ligne ton-${tonAlarme(a)}`", "`rail-ligne ton-rouge`"),
    "pastille toujours ambre": _remplace(RA, "`rail-ligne ton-${tonAlarme(a)}`", "`rail-ligne ton-ambre`"),
    "alarme sans âge": _remplace(RA, "        a.depuis ? el('span', { class: 'rail-age' }, age(a.depuis, 'court')) : null);\n    })), 'bloc-coince');", "        null);\n    })), 'bloc-coince');"),
    "alarme sans agent": _remplace(RA, "cible ? el('span', { class: 'rail-cible' }, `·\\u00A0${cible}`) : null", "null"),
    "alarme sans type lisible": _remplace(RA, "el('span', { class: 'rail-titre' }, TYPES_ALARME[a.type] || a.type)", "el('span', { class: 'rail-titre' }, a.type)"),
    "compteur de l'alarme absent": _remplace(RA, "blocRail('Ce qui coince', alarmes.length,", "blocRail('Ce qui coince', null,"),
    "compteur de l'alarme ambre": _remplace(RA, ")), 'bloc-coince');", ")), '');"),
    "compteur de l'alarme en ambre (CSS)": _remplace(CSS, ".bloc-coince .compte { background: var(--gris-fond);", ".bloc-coince .compte { background: var(--ambre);"),
    "coince après qui travaille": _remplace(RA, "blocCoince(etat), blocTravaille(etat, ouvrir)", "blocTravaille(etat, ouvrir), blocCoince(etat)"),
    "coince avant ce qui t'attend": _remplace(RA, "blocAttentes(etat, nouvelles, clignote, redessiner), blocCoince(etat)", "blocCoince(etat), blocAttentes(etat, nouvelles, clignote, redessiner)"),
    "à voir en rouge": _remplace(NIV, "a_voir: { mot: 'À voir', ton: 'ambre', rang: 1 }", "a_voir: { mot: 'À voir', ton: 'rouge', rang: 1 }"),
    "grave en ambre": _remplace(NIV, "grave: { mot: 'Grave', ton: 'rouge', rang: 0 }", "grave: { mot: 'Grave', ton: 'ambre', rang: 0 }"),
    # Qui travaille
    "au repos parmi ceux qui travaillent": _remplace(RA, "new Set(['travaille', 'attend_autorisation', 'attend_reponse'])", "new Set(['travaille', 'attend_autorisation', 'attend_reponse', 'au_repos'])"),
    "attente de réponse oubliée": _remplace(RA, "new Set(['travaille', 'attend_autorisation', 'attend_reponse'])", "new Set(['travaille', 'attend_autorisation'])"),
    "attente d'autorisation oubliée": _remplace(RA, "new Set(['travaille', 'attend_autorisation', 'attend_reponse'])", "new Set(['travaille', 'attend_reponse'])"),
    "worker terminé montré": _remplace(RA, "a.role !== 'utilisateur' && !workerTermine(a, etat.alarmes)", "a.role !== 'utilisateur'"),
    "L'utilisateur parmi les agents": _remplace(RA, "a.role !== 'utilisateur' && !workerTermine(a, etat.alarmes)", "!workerTermine(a, etat.alarmes)"),
    "état de l'agent ignoré": _remplace(RA, "agentVisible(a, etat) && ETATS_QUI_TRAVAILLE.has(etatAffiche(a))", "agentVisible(a, etat)"),
    "personne ne travaille : phrase changée": _remplace(RA, "'Personne ne travaille en ce moment.'", "'Rien.'"),
    "agents inconnus : pas de repli": _remplace(RA, "  if (!Array.isArray(etat.agents)) {\n    return blocRail(titre, null, null, el('p', { class: 'rail-vide' }, inconnu(sourceEnEchec(etat, 'structure'), 'Qui travaille : inconnu')));\n  }\n", ""),
    "tâche ignorée": _remplace(RA, "agent.tache || (agent.derniere_phrase ?", "(agent.derniere_phrase ?"),
    "dernière phrase ignorée": _remplace(RA, "agent.tache || (agent.derniere_phrase ? finDePhrase(agent.derniere_phrase) : null)", "agent.tache || null"),
    "dernière phrase non tronquée": _remplace(RA, "finDePhrase(agent.derniere_phrase) : null);\n  return el('li', {}, el('button'", "agent.derniere_phrase : null);\n  return el('li', {}, el('button'"),
    "clic agent : mauvaise cible": _remplace(RA, "ouvrir({ type: 'agent', id: agent.id })", "ouvrir({ type: 'equipe', nom: agent.equipe })"),
    "clic agent sans action": _remplace(RA, " onclick: () => ouvrir({ type: 'agent', id: agent.id }) },", " },"),
    "agent sans âge": _remplace(RA, "agent.etat_depuis ? age(agent.etat_depuis, 'court') : null", "null"),
    "agent sans id": _remplace(RA, "el('span', { class: 'rail-qui' }, nomAgent(agent.id)),", "el('span', { class: 'rail-qui' }, ''),"),
    "id d'agent en 500": _remplace(CSS, ".rail-qui { font-weight: 600;", ".rail-qui { font-weight: 500;"),
    "pastille d'agent sans ton": _remplace(RA, "class: `rail-ligne ton-${def.ton}` }, onclick", "class: 'rail-ligne' }, onclick") if False else _remplace(RA, "type: 'button', class: `rail-ligne ton-${def.ton}`", "type: 'button', class: 'rail-ligne'"),
    # Derniers échanges
    "plafond de 5 échanges": _remplace(RA, "export const MAX_ECHANGES = 3;", "export const MAX_ECHANGES = 5;"),
    "échanges les plus anciens": _remplace(RA, "(Date.parse(b.horodatage) || 0) - (Date.parse(a.horodatage) || 0)", "(Date.parse(a.horodatage) || 0) - (Date.parse(b.horodatage) || 0)"),
    "échanges non triés": _remplace(RA, ".sort((a, b) => (Date.parse(b.horodatage) || 0) - (Date.parse(a.horodatage) || 0))", ""),
    "échange sans destinataire": _remplace(RA, "`${nomAgent(m.de)} → ${nomAgent(m.a)}`),\n          el('span', { class: 'rail-age' }", "`${nomAgent(m.de)}`),\n          el('span', { class: 'rail-age' }"),
    "échange sans âge": _remplace(RA, "m.horodatage ? age(m.horodatage, 'court') : inconnu(null, 'âge inconnu')", "null"),
    "âge de l'échange en clair long": _remplace(RA, "age(m.horodatage, 'court')", "age(m.horodatage)"),
    "résumé tronqué": _remplace(RA, "class: 'echange-resume', title: m.resume }, m.resume),", "class: 'echange-resume', title: m.resume }, m.resume.slice(0, 40)),"),
    "attente sans phrase": _remplace(RA, "m.en_attente ? el('span', { class: 'echange-attend' }, phraseAttente(m, true)) : null", "null"),
    "phrase d'attente longue": _remplace(RA, "phraseAttente(m, true)) : null,\n        ", "phraseAttente(m)) : null,\n        ") if False else _remplace(RA, "{ class: 'echange-attend' }, phraseAttente(m, true))", "{ class: 'echange-attend' }, phraseAttente(m))"),
    "cime non grisé": _remplace(RA, "m.de === 'cime' || m.a === 'cime' ? 'echange-cime' : null", "null"),
    "cime grisé seulement en émetteur": _remplace(RA, "m.de === 'cime' || m.a === 'cime' ? 'echange-cime' : null", "m.de === 'cime' ? 'echange-cime' : null"),
    "cime non grisé (CSS)": _remplace(CSS, ".echange-cime .echange-qui, .echange-cime .echange-resume { color: var(--discret); }", ".echange-cime .echange-qui, .echange-cime .echange-resume { color: var(--texte); }"),
    "non lu perdu": _remplace(RA, "estNonLu(m) ? repereNonLu(m) : null", "null"),
    "repère non lu non exporté": _remplace(NIV, "export function repereNonLu(m)", "function repereNonLu(m)"),
    "échange sans clic": _remplace(RA, " onclick: () => ouvrir({ type: 'message', id: m.id }) },", " },"),
    "échange : mauvaise cible": _remplace(RA, "ouvrir({ type: 'message', id: m.id })", "ouvrir({ type: 'agent', id: m.de })"),
    "échanges vides : phrase changée": _remplace(RA, "'Aucun échange récent.'", "'Rien.'"),
    "fil inconnu : pas de repli": _remplace(RA, "  if (!Array.isArray(etat.fil)) return blocRail", "  if (false) return blocRail"),
    "lien du fil vers supervision": _remplace(RA, "href: '#/fil', texte: 'Tout le fil →'", "href: '#/supervision', texte: 'Tout le fil →'"),
    "lien du fil changé": _remplace(RA, "texte: 'Tout le fil →'", "texte: 'Fil →'"),
    "attente d'échange en rouge": _remplace(CSS, ".echange-attend { font-size: 12px; color: var(--ambre); }", ".echange-attend { font-size: 12px; color: var(--rouge-clair); }"),
    "attente d'échange au ton du fil": _remplace(CSS, ".echange-attend { font-size: 12px; color: var(--ambre); }", ".echange-attend { font-size: 12px; color: var(--secondaire); }"),
    "libellés de nature non exportés": _remplace(NIV, "export const libelleNature", "const libelleNature"),
    # détail d'une équipe
    "équipe sans nom": _remplace(RA, "el('h2', {}, q.nom), puceStatut(q.statut, statutEquipeAffiche(q, etat.alarmes))", "el('h2', {}, ''), puceStatut(q.statut, statutEquipeAffiche(q, etat.alarmes))"),
    "équipe sans statut": _remplace(RA, "el('h2', {}, q.nom), puceStatut(q.statut, statutEquipeAffiche(q, etat.alarmes))", "el('h2', {}, q.nom)"),
    "équipe sans mission": _remplace(RA, "q.mission ? el('p', { class: 'detail-texte' }, q.mission) : null", "null"),
    "tâches sans total": _remplace(RA, "chiffre(`${av.faites} / ${total}`, 'tâches faites',", "chiffre(`${av.faites}`, 'tâches faites',"),
    "tâches sans barre": _remplace(RA, "el('div', { class: 'jauge-plein', style:", "el('div', { class: 'x', style:"),
    "tâches : libellé changé": _remplace(RA, "'tâches faites',\n", "'tâches',\n") if False else _remplace(RA, "`${av.faites} / ${total}`, 'tâches faites',", "`${av.faites} / ${total}`, 'tâches',"),
    "retard à jour affiché 0": _remplace(RA, "else if (retard === 0) chiffreRetard = chiffre('à jour',", "else if (retard === 0) chiffreRetard = chiffre('0',"),
    "retard inconnu affiché à jour": _remplace(RA, "if (retard === null || retard === undefined) chiffreRetard = chiffre(inconnu(", "if (false) chiffreRetard = chiffre(inconnu("),
    "retard sans valeur": _remplace(RA, "chiffre(String(retard),", "chiffre('?',"),
    "retard sans la base": _remplace(RA, "`retard sur ${base}`);\n  else if", "'retard');\n  else if"),
    "attentes de toutes les équipes": _remplace(RA, ".filter((a) => equipeDeLAttente(a, etat) === q.nom).sort(plusAncienDabord)", ".sort(plusAncienDabord)"),
    "attentes de l'équipe sans boutons": _remplace(RA, "attentes.map((a) => cartePourRail(a, etat, nouvelles))))", "attentes.map((a) => el('p', {}, a.titre))))"),
    "attentes de l'équipe : section changée": _remplace(RA, "section('Attend de toi',", "section('Rien',"),
    "agents d'une autre équipe": _remplace(RA, "filter((a) => a.equipe === q.nom && agentVisible(a, etat))", "filter((a) => agentVisible(a, etat))"),
    "agents terminés de l'équipe": _remplace(RA, "filter((a) => a.equipe === q.nom && agentVisible(a, etat))", "filter((a) => a.equipe === q.nom)"),
    "agents de l'équipe sans état": _remplace(RA, "ligneAgent(a, etat, ouvrir, { avecEtat: true })", "ligneAgent(a, etat, ouvrir)"),
    "fiche complète vers le fil": _remplace(RA, "lienBouton(routeEquipe(q.nom), 'Ouvrir la fiche complète →')", "lienBouton(routeFil({ equipe: q.nom }), 'Ouvrir la fiche complète →')"),
    "fiche complète : libellé changé": _remplace(RA, "'Ouvrir la fiche complète →'", "'Fiche →'"),
    "nom d'équipe pas en mono": _remplace(CSS, "font-family: var(--mono); font-size: 20px; font-weight: 600; overflow-wrap", "font-family: var(--police); font-size: 20px; font-weight: 600; overflow-wrap"),
    "nom d'équipe en 16 px": _remplace(CSS, "font-family: var(--mono); font-size: 20px; font-weight: 600; overflow-wrap", "font-family: var(--mono); font-size: 16px; font-weight: 600; overflow-wrap"),
    # détail d'un agent
    "agent sans nom": _remplace(RA, "el('h2', {}, nomAgent(agent.id)), pastilleEtat(def.cle, def)", "el('h2', {}, ''), pastilleEtat(def.cle, def)"),
    "agent sans statut": _remplace(RA, "el('h2', {}, nomAgent(agent.id)), pastilleEtat(def.cle, def)", "el('h2', {}, nomAgent(agent.id))"),
    "agent sans tâche": _remplace(RA, "fait('Tâche', agent.tache ||", "fait('Tâche', null ||"),
    "agent sans dernière phrase": _remplace(RA, "agent.derniere_phrase ? fait('Dernière phrase', finDePhrase(agent.derniere_phrase)) : null", "null"),
    "contexte en jetons": _remplace(RA, "pourcent(agent.contexte.tokens / agent.contexte.limite)", "String(agent.contexte.tokens)"),
    "contexte absent": _remplace(RA, "fait('Contexte', contexte),", ""),
    "agent sans modèle": _remplace(RA, "fait('Modèle', agent.modele || inconnuCourt('modèle', null))", "fait('Modèle', '')"),
    "agent sans dettes": _remplace(RA, "section('Dettes', Array.isArray(dettes)", "section('Dettes', false"),
    "dettes sans débiteur": _remplace(RA, "`${d.attendu} de ${nomAgent(d.de)}`", "`${d.attendu}`"),
    "dettes vides : phrase changée": _remplace(RA, "'Aucune dette ouverte.'", "'Rien.'"),
    "agent sans file": _remplace(RA, "section('File', Array.isArray(file)", "section('File', false"),
    "file sans nature": _remplace(RA, "`${nomAgent(m.de)} · ${NATURES_FIL[m.nature] || m.nature || 'message'} — ${m.resume}`", "`${nomAgent(m.de)} — ${m.resume}`"),
    "file vide : phrase changée": _remplace(RA, "'Rien en file.'", "'Rien.'"),
    "fiche de l'équipe de l'agent changée": _remplace(RA, "'Ouvrir la fiche de l’équipe →'", "'Fiche →'"),
    "fiche de l'agent vers le fil": _remplace(RA, "lienBouton(routeEquipe(agent.equipe), 'Ouvrir la fiche de l’équipe →')", "lienBouton(routeFil({ agent: agent.id }), 'Ouvrir la fiche de l’équipe →')"),
    # détail d'un message
    "message sans de → à": _remplace(RA, "el('h2', {}, `${nomAgent(m.de)} → ${nomAgent(m.a)}`)", "el('h2', {}, `${nomAgent(m.de)}`)"),
    "message sans nature": _remplace(RA, "fait('Nature', libelleNature(m)),", ""),
    "résumé tronqué dans le détail": _remplace(RA, "el('p', { class: 'detail-texte' }, m.resume)", "el('p', { class: 'detail-texte' }, finDePhrase(m.resume))"),
    "message sans livraison": _remplace(RA, "      fait('Livraison', m.etat_livraison ? (LIVRAISON[m.etat_livraison] || m.etat_livraison) : 'sans suivi de livraison'),\n", ""),
    "livraison brute": _remplace(RA, "(LIVRAISON[m.etat_livraison] || m.etat_livraison)", "m.etat_livraison"),
    "livraison : libellé pris en compte perdu": _remplace(RA, "pris_en_compte: 'pris en compte'", "pris_en_compte: 'pris_en_compte'"),
    "message : lien sans filtre": _remplace(RA, "routeFil({ agent: agentDuFil })", "routeFil()"),
    "message : lien changé": _remplace(RA, "'Voir dans le fil →'", "'Fil →'"),
    "message : filtre sur l'utilisateur": _remplace(RA, "id !== 'utilisateur' && id !== 'cime'", "id !== 'cime'"),
    "message : filtre sur cime": _remplace(RA, "id !== 'utilisateur' && id !== 'cime'", "id !== 'utilisateur'"),
    # l'utilisateur
    "L'utilisateur ouvre un détail": _remplace(RA, "const trouve = !telephone && selection && selection.type !== 'utilisateur' ? trouverCible(selection, etat) : null;", "const trouve = !telephone && selection ? trouverCible(selection, etat) : null;"),
    "pas de clignotement": _remplace(RA, "const classe = clignote ? 'clignote' : '';", "const classe = '';"),
    "clignote à chaque sélection": _remplace(SC, "clignotement = Boolean(cible && cible.type === 'utilisateur');", "clignotement = Boolean(cible);"),
    "clignote à chaque instantané": _remplace(SC, "redessiner: dessinerRail, clignote: clignotement, telephone });\n  clignotement = false;", "redessiner: dessinerRail, clignote: clignotement, telephone });"),
    "clignote trois fois": _remplace(CSS, "animation: clignote 0.8s ease-in-out 1;", "animation: clignote 0.8s ease-in-out 3;"),
    "clignote en 2 s": _remplace(CSS, "animation: clignote 0.8s ease-in-out 1;", "animation: clignote 2s ease-in-out 1;"),
    "clignote en rouge": _remplace(CSS, "50% { background: var(--ambre-fond); } }", "50% { background: var(--rouge-fond); } }"),
    "détail sans suite : clignotement non annulé": _remplace(SC, "clignotement = Boolean(cible && cible.type === 'utilisateur');\n  dessinerRail();", "clignotement = Boolean(cible && cible.type === 'utilisateur');\n  setTimeout(dessinerRail);") if False else _remplace(SC, "  clignotement = Boolean(cible && cible.type === 'utilisateur');\n  dessinerRail();\n});", "  clignotement = Boolean(cible && cible.type === 'utilisateur');\n});"),
    # fermeture
    "retour sans action": _remplace(RA, "class: 'retour', onclick: fermer }", "class: 'retour' }"),
    "retour : libellé changé": _remplace(RA, "'← Retour'", "'Fermer'"),
    "détail sans retour": _remplace(RA, "'aria-label': 'Détail' }, retour, detailCible(", "'aria-label': 'Détail' }, detailCible("),
    "détail qui garde les blocs": _remplace(RA, "vider(conteneur, el('section', { class: 'detail-rail', 'aria-label': 'Détail' }, retour, detailCible(", "conteneur.append(el('section', { class: 'detail-rail', 'aria-label': 'Détail' }, retour, detailCible("),
    "retour ne ferme pas": _remplace(SC, "fermer: () => choisir(null)", "fermer: () => {}"),
    "Échap ignoré hors du plateau": _remplace(SC, "if (ev.key !== 'Escape' || !actif ||", "if (ev.key !== 'Enter' || !actif ||"),
    "Échap sous un dialogue": _remplace(SC, " || document.querySelector('dialog[open]')) return;", ") return;"),
    "Échap ne ferme pas": _remplace(SC, "document.querySelector('dialog[open]')) return;\n  if (selection) choisir(null);", "document.querySelector('dialog[open]')) return;\n  if (selection) selection = null;"),
    "Échap hors de la scène": _remplace(SC, "!actif || plateau.contains(ev.target)", "plateau.contains(ev.target)"),
    "Échap en double": _remplace(SC, " || plateau.contains(ev.target) || document.querySelector", " || document.querySelector"),
    "Échap sans écouteur global": _remplace(SC, "document.addEventListener('keydown', (ev) => {\n  if (ev.key !== 'Escape' || !actif", "plateau.addEventListener('keydown', (ev) => {\n  if (ev.key !== 'Escape' || !actif"),
    "vide sans effet": _remplace(SC, "surVide: () => { basculerLegende(false); choisir(null); },", "surVide: () => {},"),
    "cible disparue : détail gardé": _remplace(SC, "!trouverCible(selection, etat)) {\n    choisir(null);", "!trouverCible(selection, etat)) {\n    selection = null;"),
    "cible disparue : détail redessiné": _remplace(SC, "    return;\n  }\n  const telephone", "  }\n  const telephone"),
    "cible disparue jamais cherchée": _remplace(SC, "selection.type !== 'utilisateur' && !trouverCible(selection, etat)) {", "selection.type !== 'utilisateur' && false) {"),
    "dessin sans contexte": _remplace(SC, "if (!actif || !contexteRendu) return;", "if (!contexteRendu) return;"),
    "équipe cherchée au hasard": _remplace(RA, "etat.equipes.find((q) => q.nom === cible.nom)", "etat.equipes[0]"),
    "agent cherché par nom": _remplace(RA, "etat.agents.find((a) => a.id === cible.id)", "etat.agents.find((a) => a.nom === cible.id)"),
    "message cherché par agent": _remplace(RA, "etat.fil.find((m) => m.id === cible.id)", "etat.fil.find((m) => m.de === cible.id)"),
    "cible inconnue : détail vide": _remplace(RA, "    return message ? { message } : null;\n  }\n  return null;", "    return message ? { message } : null;\n  }\n  return {};"),
    "équipe : liste inconnue ignorée": _remplace(RA, "cible.type === 'equipe' && Array.isArray(etat.equipes)", "cible.type === 'equipe'"),
    "sélection non annulée": _remplace(SC, "selection = cible ?? null;\n  objetScene", "selection = cible;\n  objetScene"),
    "scène non informée de la sélection": _remplace(SC, "  objetScene?.selectionner?.(selection);\n", ""),
    "abonnés non prévenus": _remplace(SC, "  for (const f of abonnes) f(selection);\n}", "}"),
    # mise à jour sur place
    "état gardé dans le DOM": _remplace(RA, "  if (ids) attentesVues = new Set(ids);\n}", "  conteneur.dataset.vue = selection ? 'detail' : 'blocs';\n  if (ids) attentesVues = new Set(ids);\n}"),
    "rail qui lit le DOM": _remplace(RA, "  const ids = Array.isArray(", "  const avant = conteneur.querySelector('.detail-rail');\n  const ids = Array.isArray("),
    "rail qui lit le défilement": _remplace(RA, "  if (ids) attentesVues = new Set(ids);\n}", "  conteneur.scrollTop = 0;\n  if (ids) attentesVues = new Set(ids);\n}"),
    "rail dessiné d'un autre instantané": _remplace(SC, "const etat = contexteRendu.etat;", "const etat = dernierEtat;"),
    "défilement perdu": _remplace(SC, "const haut = vue === vueRail ? defilementRail : 0;", "const haut = 0;"),
    "défilement gardé d'une vue à l'autre": _remplace(SC, "const haut = vue === vueRail ? defilementRail : 0;", "const haut = defilementRail;"),
    "défilement jamais mesuré": _remplace(SC, "rail.addEventListener('scroll', () => { if (rail.isConnected) defilementRail = rail.scrollTop; });\n", ""),
    "défilement mesuré hors page": _remplace(SC, "if (rail.isConnected) defilementRail = rail.scrollTop;", "defilementRail = rail.scrollTop;"),
    "défilement jamais rétabli": _remplace(SC, "  rail.scrollTop = haut;\n", ""),
    "défilement jamais relu": _remplace(SC, "  defilementRail = rail.scrollTop;\n  synchroniserFeuilles(etat, telephone);", "  synchroniserFeuilles(etat, telephone);"),
    "rail non dessiné au rendu": _remplace(SC, "  contexteRendu = ctx;\n  actif = true;\n  dessinerRail();\n", "  contexteRendu = ctx;\n  actif = true;\n"),
    "contexte non mémorisé": _remplace(SC, "  contexteRendu = ctx;\n  actif = true;", "  actif = true;"),
    "écran quitté, rail encore actif": _remplace(SC, "return () => { actif = false; fermerFeuilleDetail(); fermerFeuilleAttentes(); };", "return () => {};"),
    "sélection sans redessin": _remplace(SC, "  clignotement = Boolean(cible && cible.type === 'utilisateur');\n  dessinerRail();\n});", "  clignotement = Boolean(cible && cible.type === 'utilisateur');\n  setTimeout(() => {});\n});"),
    "rail sans abonnement": _remplace(SC, "surSelection((cible) => {\n  clignotement", "(() => {\n  clignotement"),
    # le bandeau a disparu
    "bandeau dans le fil": _remplace(FIL, "function titre(total) {", "// bandeau\nfunction titre(total) {"),
    "bandeau dans la feuille de style": _remplace(CSS, ".demander { white-space: nowrap; flex: none; }", ".demander { white-space: nowrap; flex: none; }\n.bandeau { display: flex; }"),
    "bandeau dans le socle": _remplace(NIV, "// Les attentes de l'utilisateur", "// Bandeau\n// Les attentes de l'utilisateur"),
    "bandeau dans la scène": _remplace(SC, "const rail = el(", "const bandeau = null;\nconst rail = el("),
    "bandeau dans Supervision": _remplace("vues/ensemble.js", "let visiteSuivie = false;", "let visiteSuivie = false;\nlet bandeau = null;"),
    "le fil déplie encore": _remplace(FIL, "{ href: '#/' }, 'voir dans Ce qui t’attend'", "{ href: '#' }, 'voir dans Ce qui t’attend'"),
    "le fil clique encore": _remplace(FIL, "function titre(total) {", "const replier = () => document.querySelector('.x')?.click();\nfunction titre(total) {"),
    "compteur : pastille nue": _remplace(NIV, "}, phrase);", "}, String(attentes.length));"),
    "compteur : toujours au pluriel": _remplace(NIV, "${attentes.length === 1 ? 't’attend' : 't’attendent'}`;", "${'t’attendent'}`;"),
    "compteur : sans pluriel du mot point": _remplace(NIV, "${pluriel(attentes.length, 'point')} ${attentes.length", "${attentes.length} point ${attentes.length"),
    "compteur affiché à 0": _remplace(NIV, "if (!attentes || !attentes.length) return null;\n  const phrase", "if (!attentes) return null;\n  const phrase"),
    "compteur vers Supervision": _remplace(NIV, "{ class: 'compteur-attentes', href: '#/',", "{ class: 'compteur-attentes', href: '#/supervision',"),
    "compteur en rouge": _remplace(CSS, "white-space: nowrap;\n  background: var(--ambre-fond); color: var(--ambre);", "white-space: nowrap;\n  background: var(--ambre-fond); color: var(--rouge-clair);"),
    "Supervision : lien des points perdu": _remplace("vues/ensemble.js", "n ? el('a', { class: 'org-utilisateur-attentes', href: '#/' },", "n ? el('span', { class: 'org-utilisateur-attentes' },"),
    # image figée
    "boutons jamais désactivés": _remplace(NIV, "const occupe = enCours.has(attente.id) || actionsFigees;", "const occupe = enCours.has(attente.id);"),
    "figé sans explication": _remplace(NIV, "const titre = actionsFigees ? PHRASE_ACTIONS_FIGEES : null;", "const titre = null;"),
    "explication changée": _remplace(NIV, "export const PHRASE_ACTIONS_FIGEES = 'L’hôte ne répond plus';", "export const PHRASE_ACTIONS_FIGEES = 'Indisponible';"),
    "dépôt non désactivé": _remplace(NIV, "multiple: true, disabled: occupe, title: titre,", "multiple: true, title: titre,"),
    "lecture non désactivée": _remplace(NIV, "disabled: occupe, title: titre, onclick: () => dialogueLire(attente, ctx)", "title: titre, onclick: () => dialogueLire(attente, ctx)"),
    "clôture non désactivée": _remplace(NIV, "disabled: occupe, title: titre, onclick: () => dialogueCloturer(attente)", "title: titre, onclick: () => dialogueCloturer(attente)"),
    "marquer comme lu sans explication": _remplace(NIV, "title: actionsFigees ? PHRASE_ACTIONS_FIGEES : null,", "title: null,"),
    "variable de figé inerte": _remplace(NIV, "  actionsFigees = Boolean(fige);\n", "  actionsFigees = false;\n"),
    "variable de figé jamais mise à jour": _remplace(SC, "    definirActionsFigees(fige); // les boutons d'action du rail se désactivent (ou se réactivent)\n", ""),
    "rail non redessiné au figé": _remplace(SC, "    definirActionsFigees(fige); // les boutons d'action du rail se désactivent (ou se réactivent)\n    dessinerRail();\n", "    definirActionsFigees(fige); // les boutons d'action du rail se désactivent (ou se réactivent)\n"),
    "figé jamais mémorisé": _remplace(SC, "    figeRail = fige;\n", ""),
    "figé non importé": _remplace(SC, "mesurerLargeur, definirActionsFigees, feuille }", "mesurerLargeur, feuille }"),
    # une attente qui arrive
    "attentes vues jamais gardées": _remplace(RA, "  if (ids) attentesVues = new Set(ids);\n", ""),
    "tout est nouveau": _remplace(RA, "attentesVues && ids ? ids.filter", "ids ? ids.filter"),
    "ids oubliés": _remplace(RA, "map((a) => a.id) : null;\n  const nouvelles", "map((a) => a.nom) : null;\n  const nouvelles"),
    "fondu absent": _remplace(RA, "carte.classList.add('arrive')", "carte.classList.add('x')"),
    "fondu de 600 ms": _remplace(CSS, "animation: arrivee 200ms ease-out;", "animation: arrivee 600ms ease-out;"),
    "fondu sans animation": _remplace(CSS, ".attente.arrive { animation: arrivee 200ms ease-out; }", ".attente.arrive { }"),
    "fondu jamais coupé": _remplace(CSS, "@media (prefers-reduced-motion: reduce) { .attente.arrive, .bloc-rail.clignote { animation: none; } }", ""),
    "clignotement jamais coupé": _remplace(CSS, "@media (prefers-reduced-motion: reduce) { .attente.arrive, .bloc-rail.clignote { animation: none; } }", "@media (prefers-reduced-motion: reduce) { .attente.arrive { animation: none; } }"),
    "fondu : images clés perdues": _remplace(CSS, "@keyframes arrivee { from { opacity: 0; } to { opacity: 1; } }", ""),
    "halo dessiné par la page": _remplace(RA, "export const MAX_ATTENTES = 3;", "export const MAX_ATTENTES = 3; // halo ambre"),
    "halo dans la scène de la page": _remplace(SC, "let defilementRail = 0;", "let defilementRail = 0;\nconst halo = null;"),
    # CSS du rail
    "couleur en dur": _remplace(CSS, ".rail-vide { margin: 0;", ".rail-x { color: #FF0000; }\n.rail-vide { margin: 0;"),
    "taille hors échelle": _remplace(CSS, ".rail-vide { margin: 0; font-size: 13px;", ".rail-vide { margin: 0; font-size: 15px;"),
    "taille hors échelle (carte)": _remplace(CSS, ".attente-meta { font-size: 12px;", ".attente-meta { font-size: 10px;"),
    "graisse hors échelle": _remplace(CSS, ".rail-qui { font-weight: 600;", ".rail-qui { font-weight: 700;"),
    "ombre dans le rail": _remplace(CSS, ".lien-autres { font-size: 13px; }", ".lien-autres { font-size: 13px; box-shadow: 0 2px 6px rgba(0, 0, 0, 0.3); }"),
    "rayon hors échelle": _remplace(CSS, ".bloc-rail { display: flex; flex-direction: column; gap: 8px; border-radius: var(--rayon); }", ".bloc-rail { display: flex; flex-direction: column; gap: 8px; border-radius: 14px; }"),
    "rouge dans le rail": _remplace(CSS, ".rail-vide { margin: 0;", ".rail-y { color: var(--rouge); }\n.rail-vide { margin: 0;"),
    "rouge dans le rail (JS)": _remplace(RA, "`rail-ligne ton-${def.ton}`", "`rail-ligne ton-rouge`"),
    "espacement hors système": _remplace(CSS, "display: flex; align-items: center; gap: 8px; padding: 16px; border-radius: var(--rayon);\n  background: var(--vert-fond)", "display: flex; align-items: center; gap: 8px; padding: 12px; border-radius: var(--rayon);\n  background: var(--vert-fond)"),
    "espacement hors système (carte)": _remplace(CSS, "border-radius: var(--rayon); padding: 16px; min-width: 0;", "border-radius: var(--rayon); padding: 14px; min-width: 0;"),
    "genre de carte en rouge": _remplace(CSS, "text-transform: uppercase; color: var(--ambre);\n}\n.attente[data-nature", "text-transform: uppercase; color: var(--rouge);\n}\n.attente[data-nature"),
    "genre de carte pas ambre": _remplace(CSS, "text-transform: uppercase; color: var(--ambre);\n}\n.attente[data-nature", "text-transform: uppercase; color: var(--vert);\n}\n.attente[data-nature"),
    "compte rendu pas bleu": _remplace(CSS, '.attente[data-nature="rapport"] { border-left-color: var(--bleu); }', '.attente[data-nature="rapport"] { border-left-color: var(--ambre); }'),
    "genre du compte rendu pas bleu": _remplace(CSS, '.attente[data-nature="rapport"] .etiquette { color: var(--bleu-clair); }', '.attente[data-nature="rapport"] .etiquette { color: var(--ambre); }'),
    "titre de carte sur 3 lignes": _remplace(CSS, "-webkit-line-clamp: 2;", "-webkit-line-clamp: 3;"),
    "titre de carte non limité": _remplace(CSS, "display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;", ""),
    "monospace dans les cartes": _remplace(CSS, ".attente-meta { font-size: 12px;", ".attente-meta { font-family: var(--mono); font-size: 12px;"),
    "bloc : compteur 0 affiché": _remplace(RA, "compteur ? el(", "compteur !== undefined ? el("),
    "bloc : lien toujours rendu": _remplace(RA, "lien ? el(", "lien !== undefined ? el("),
    "attentes non plafonnées": _remplace(RA, "(depliees ? triees : triees.slice(0, MAX_ATTENTES)).map(", "triees.map("),
    "tri sur une autre date": _remplace(RA, "instant(a.depuis) - instant(b.depuis)", "instant(a.depuis) - instant(b.horodatage)"),
    "cartes de la page non importées": _remplace(RA, "attentesOuvertes, carteAttente, equipeDeLAttente", "attentesOuvertes, equipeDeLAttente"),
    "retard lu du mauvais champ": _remplace(RA, "const retard = q.retard_sur_base;", "const retard = q.en_avance_sur_base;"),
    "blocs toujours dessinés sous le détail": _remplace(RA, "  } else {\n    vider(conteneur, blocAttentes(", "  }\n  {\n    vider(conteneur, blocAttentes("),
    "surSelection non exportée": _remplace(SC, "export function surSelection(rappel)", "function surSelection(rappel)"),
    "figé dès le départ": _remplace(NIV, "let actionsFigees = false;", "let actionsFigees = true;"),
    "premier dessin animé": _remplace(RA, "let attentesVues = null;", "let attentesVues = new Set();"),
    "graisse hors échelle (retour)": _remplace(CSS, "font-size: 13px; font-weight: 500; color: var(--secondaire);\n}\n.retour:hover", "font-size: 13px; font-weight: 700; color: var(--secondaire);\n}\n.retour:hover"),
    "rouge dans le rail (constante)": _remplace(RA, "export const MAX_ALARMES = 3;", "export const MAX_ALARMES = 3;\nconst COULEUR = 'rouge';"),
}


@pytest.mark.parametrize("nom", MUTATIONS)
def test_mutation_detectee(nom, js):
    mutee = MUTATIONS[nom](js)  # hors du raises : la mutation doit s'appliquer, sinon le test serait faux
    with pytest.raises(AssertionError):
        verifier_rail_accueil(mutee)


def test_couverture_des_verifications():
    toutes = {n for n, v in globals().items() if n.startswith("verifier_") and callable(v)}
    assert toutes == {"verifier_rail_accueil"} and MUTATIONS, sorted(toutes)
