"""La scène dans le plateau : montage, source, légende, commandes, états.

Analyse de texte du JS et du CSS de static/ (pas de navigateur dans pytest). `verifier_plateau_scene(js)` lève
AssertionError ; la table MUTATIONS prouve qu'elle échoue quand on casse chaque comportement. Le rendu réel
(le canvas dessine, les clics, la légende, le zoom, la coupure de l'hôte, les captures) est vérifié dans un vrai
navigateur par tests/page/outils/scenario_plateau.py.
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


def _dans_l_ordre(texte, morceaux):
    assert all(m in texte for m in morceaux), morceaux
    positions = [texte.index(m) for m in morceaux]
    assert positions == sorted(positions), morceaux


def _regle(css, selecteur):
    """Le corps de la règle CSS dont le sélecteur est exactement `selecteur`."""
    m = re.search(r"(?:^|\n)" + re.escape(selecteur) + r" \{([^}]*)\}", css)
    assert m, selecteur
    return m.group(1)


def verifier_plateau_scene(js):
    commun, app, scene, css = (js[n] for n in ("commun.js", "app.js", "vues/scene.js", "style.css"))
    rendu = _corps(scene, "export function rendre(ctx)", "\n}\n")
    monter = _corps(scene, "async function monter()", "\n}\n")

    # 1. le montage : une seule fois (une promesse de module), au premier rendu, jamais arrêté en changeant d'onglet
    assert "let promesse = null;" in scene
    assert "  if (!promesse) {\n    dernierEtat ??= ctx.etat;\n    promesse = monter();\n  }\n" in rendu
    assert scene.count("monter()") == 1 + 1  # la déclaration et l'unique appel
    assert "arreter" not in scene
    assert "objetScene?.redimensionner();" in rendu

    # 2. import dynamique des deux modules de la scène, même origine ; aucun import statique, aucun réseau
    assert "await Promise.all([import('/scene/scene.js'), import('/scene/source-alimentee.js')])" in monter
    assert not re.search(r"^import .*/scene/", scene, re.MULTILINE) and "from '/scene" not in scene
    assert not re.search(r"\b(fetch|EventSource|XMLHttpRequest|WebSocket|sendBeacon)\s*\(", scene)
    assert "/api/" not in scene

    # 3. le repli : une phrase, rien d'autre, aucune erreur non attrapée
    assert "  } catch {\n    repli();\n    return;\n  }\n" in monter
    repli = _corps(scene, "function repli()", "\n}\n")
    assert scene.count("La scène n’est pas disponible ici.") == 1
    assert "vider(plateau, el('p', { class: 'plateau-calme' }, 'La scène n’est pas disponible ici.'));" in repli
    assert repli.count("el(") == 1
    assert "} catch {\n    sourceScene = null;\n    repli();\n  }" in monter
    assert "position: absolute; inset: 0;" in _regle(css, ".plateau-calme")

    # 4. la source : alimentée par la page, instantané gardé avant le montage, poussé dès que la source existe
    assert "creerSourceAlimentee({ maintenant: () => performance.now() })" in monter
    _dans_l_ordre(monter, ["creerSourceAlimentee(", "if (dernierEtat) sourceScene.pousser(dernierEtat);", "monterScene(plateau,"])
    alim = _corps(scene, "export function alimenter(etat)", "\n}\n")
    assert "  dernierEtat = etat;\n  sourceScene?.pousser(etat);" in alim
    branche = _corps(app, "if (quoi === 'etat') {", "const avaitEnvoyees")
    assert "scene.alimenter(source.etat());" in branche  # avant tout test sur l'onglet ou sur le changement
    assert "if (quoi === 'etat') {\n    // la scène reste à jour en arrière-plan : elle reçoit chaque instantané, quel que soit l'onglet courant\n    scene.alimenter(" in app
    assert "import * as scene from './vues/scene.js';" in app
    assert "if (change" not in branche and "route" not in branche

    # 5. les options de monterScene, le fond transparent (le plateau porte le fond)
    options = _corps(monter, "monterScene(plateau, {", "    });")
    for option in ("source: sourceScene,", "surClic: (cible) => { basculerLegende(false); choisir(cible); },",
                   "surVide: () => { basculerLegende(false); choisir(null); },",
                   "surSurvol: survol,", "surStatut: () => {},", "surPret: () => { pret = true; silhouette.remove(); majFige(); },",
                   "theme: { fond: 'transparent' },"):
        assert option in options, option
    assert "background: radial-gradient" not in options and "position: relative;" in _regle(css, ".plateau")

    # 6. la sélection : variable de module, scène prévenue (optionnel tant que la fusion n'est pas faite), Échap
    assert "let selection = null;" in scene
    choisir = _corps(scene, "function choisir(cible)", "\n}\n")
    assert "selection = cible ?? null;" in choisir and "objetScene?.selectionner?.(selection);" in choisir
    assert "for (const f of abonnes) f(selection);" in choisir
    assert "return selection;" in _corps(scene, "export function selectionCourante()", "\n}\n")
    abonner = _corps(scene, "export function surSelection(rappel)", "\n}\n")
    assert "abonnes = [...abonnes, rappel];" in abonner and "return () => {" in abonner
    assert "export function estFige()" in scene and "return plateau.dataset.fige === 'oui';" in scene
    clavier = _corps(scene, "plateau.addEventListener('keydown'", "\n});")
    assert "ev.key !== 'Escape'" in clavier
    assert "if (!legende.hidden) basculerLegende(false);\n  else if (selection) choisir(null);" in clavier
    for interdit in ("location", "hash", "navigat", "aside"):
        assert interdit not in choisir + clavier  # aucune navigation ni panneau à cette étape
    assert "location" not in scene and "hashchange" not in scene

    # 7. l'info-bulle de la page : role, position décalée de 12 px et gardée dans le plateau, rien d'autre que titre et lignes
    survol = _corps(scene, "function survol(cible", "\n}\n")
    assert "const DECALAGE_INFOBULLE = 12;" in scene
    assert "infobulle?.remove();\n  infobulle = null;\n  if (!cible) return;" in survol
    assert "el('div', { class: 'infobulle-plateau', role: 'tooltip' }," in survol
    assert "el('div', { class: 'infobulle-titre' }, titre)," in survol
    assert "lignes.map((l) => el('div', { class: 'infobulle-ligne' }, l)));" in survol
    assert "x + DECALAGE_INFOBULLE" in survol and "y + DECALAGE_INFOBULLE" in survol
    assert "plateau.clientWidth - infobulle.offsetWidth - MARGE_INFOBULLE" in survol
    assert "plateau.clientHeight - infobulle.offsetHeight - MARGE_INFOBULLE" in survol
    assert "infobulle.style.left = `${Math.max(MARGE_INFOBULLE, gauche)}px`;" in survol
    assert "infobulle.style.top = `${Math.max(MARGE_INFOBULLE, haut)}px`;" in survol
    assert len(re.findall(r"'[^']*'", survol)) == 8  # balises, classes, role, titre par défaut vide : aucune phrase en dur
    bulle = _regle(css, ".infobulle-plateau")
    assert "background: var(--carte)" in bulle and "border: 1px solid var(--bord)" in bulle
    assert "box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4)" in bulle and "position: absolute" in bulle and "pointer-events: none" in bulle
    assert "font-size: 13px; font-weight: 600" in _regle(css, ".infobulle-titre")
    assert "font-size: 12px" in _regle(css, ".infobulle-ligne")

    # 8. les commandes : Légende en bas à gauche, trois boutons de 32 px en bas à droite, touches que la scène écoute
    assert "{ touche: '-', signe: '−', titre: 'Zoom arrière (−)' }," in scene
    assert "{ touche: '+', signe: '+', titre: 'Zoom avant (+)' }," in scene
    assert "{ touche: '0', signe: '⤢', titre: 'Tout voir (0)' }," in scene
    assert "type: 'button', class: 'commande-plateau', title: c.titre, 'aria-label': c.titre, onclick: () => emettreTouche(c.touche) }, c.signe)));" in scene
    touche = _corps(scene, "function emettreTouche(key)", "\n}\n")
    assert "plateau.querySelector(':scope > canvas')" in touche  # jamais un canvas de la légende (47 icônes, avant celui de la scène)
    assert "querySelector('canvas')" not in touche
    assert "canvas.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));" in touche
    assert "const commandes = el('div', { class: 'commandes-zoom' }," in scene
    assert "class: 'commande-plateau commande-legende', 'aria-expanded': 'false'" in scene
    assert "'aria-controls': 'legende-plateau', onclick: () => basculerLegende() }, 'Légende');" in scene
    assert "plateau.append(silhouette, capsule, legende, boutonLegende, commandes);" in scene
    bascule = _corps(scene, "function basculerLegende(", "\n}\n")
    assert "ouverte = legende.hidden" in bascule and "legende.hidden = !ouverte;" in bascule
    assert "boutonLegende.setAttribute('aria-expanded', String(ouverte));" in bascule
    assert "molette" not in scene and "pincement" not in scene
    bouton = _regle(css, ".commande-plateau")
    assert "min-width: 32px; height: 32px" in bouton and "background: var(--carte)" in bouton
    assert "left: 16px; bottom: 16px" in _regle(css, ".commande-legende")
    zoom = _regle(css, ".commandes-zoom")
    assert "right: 16px; bottom: 16px" in zoom and "gap: 8px" in zoom

    # 9. la légende : lue dans LEGENDE, une icône par ligne, groupée, le rouge pour les seuls signes de problème
    assert "const { monterScene, LEGENDE, dessinerIcone } = module.scene;" in monter
    assert "if (LEGENDE && dessinerIcone) remplirLegende(LEGENDE, dessinerIcone);" in monter
    assert "const legende = el('aside', { class: 'legende', id: 'legende-plateau', 'aria-label': 'Légende', hidden: true });" in scene
    remplir = _corps(scene, "function remplirLegende(", "\n}\n")
    assert "groupes.set(e.groupe, [...(groupes.get(e.groupe) ?? []), e]);" in remplir
    assert "el('h3', {}, nom)," in remplir
    assert "const icone = el('canvas', { width: 32, height: 32 });" in remplir
    assert "dessinerIcone(icone, e.sprite, { echelle: 2 });" in remplir
    assert "el('span', { class: e.probleme ? 'legende-libelle legende-probleme' : 'legende-libelle' }, e.libelle));" in remplir
    assert "libelle:" not in scene and "sprite:" not in scene  # aucune entrée de légende en dur dans la page
    panneau = _regle(css, ".legende")
    assert "width: 300px" in panneau and "overflow-y: auto" in panneau and "bottom: 56px" in panneau and "left: 16px" in panneau
    assert "text-transform: uppercase" in _regle(css, ".legende-groupe h3") and "font-size: 11px" in _regle(css, ".legende-groupe h3")
    assert "width: 32px; height: 32px" in _regle(css, ".legende-icone")
    assert "font-size: 13px" in _regle(css, ".legende-libelle")
    assert "color: var(--rouge-clair)" in _regle(css, ".legende-probleme")
    lignes_css = [l for l in css.splitlines() if l.startswith(".legende") or l.startswith(".commande") or l.startswith(".plateau")]
    assert not [l for l in lignes_css if "rouge" in l and not l.startswith(".legende-probleme")]

    # 10. chargement : la silhouette de l'étage pulse sans texte, disparaît au surPret, coupée si l'on réduit les animations
    assert "const silhouette = el('div', { class: 'plateau-silhouette', 'aria-hidden': 'true' });" in scene
    assert "connexion…" not in scene
    forme = _regle(css, ".plateau-silhouette")
    assert "width: min(672px, calc(100% - 40px)); height: min(480px, calc(100% - 40px))" in forme
    assert "background: var(--carte)" in forme and "border-radius: var(--rayon)" in forme
    assert "top: 50%; left: 50%; transform: translate(-50%, -50%)" in forme
    assert "animation: silhouette 1.6s ease-in-out infinite" in forme
    assert "@keyframes silhouette { 0%, 100% { opacity: 0.6; } 50% { opacity: 1; } }" in css
    assert "@media (prefers-reduced-motion: reduce) { .plateau-silhouette { animation: none; } }" in css

    # 11. connexion perdue après chargement : figé, désaturé, capsule rouge à l'âge de la donnée, accrochée à tic
    figer = _corps(scene, "function majFige()", "\n}\n")
    assert "const fige = Boolean(pret && sourcePage && sourcePage.fluxInterrompu());" in figer
    assert "plateau.dataset.fige = 'oui';" in figer and "delete plateau.dataset.fige;" in figer
    assert "`Image figée depuis ${duree(sourcePage.horloge.ageDonnee())} — l’hôte ne répond plus`" in figer
    assert "capsule.hidden = !fige;" in figer
    assert "surTic(majFige);" in scene and "  majFige();\n  ctx.tic();" in rendu
    assert "setInterval" not in scene and "setTimeout" not in scene
    assert "sourcePage = ctx.source;" in rendu
    assert "filter: grayscale(85%) brightness(70%)" in _regle(css, '.plateau[data-fige="oui"] > canvas')
    capsule = _regle(css, ".capsule-figee")
    assert "background: var(--rouge-fond)" in capsule and "color: var(--rouge-clair)" in capsule and "border: 1px solid var(--rouge-bord)" in capsule
    assert "top: 16px; left: 50%; transform: translateX(-50%)" in capsule and "border-radius: 999px" in capsule
    assert "role: 'status'" in scene
    assert "const rappelsTic = new Set();" in commun and "rappelsTic.add(rappel);" in commun
    assert "  for (const rappel of rappelsTic) rappel();\n}" in _corps(commun, "export function tic()", "\n}\n") + "\n}"

    # 12. le focus du canvas, perdu quand la page reconstruit son <body>, lui est rendu
    assert "document.addEventListener('focusin', (ev) => { dernierFocus = plateau.contains(ev.target) ? ev.target : null; });" in scene
    assert "  dernierFocus?.focus({ preventScroll: true });" in rendu

    # 13. l'hôte injoignable au premier chargement : en-tête de la page sans onglets, une carte, un décompte
    inj = _corps(commun, "export function rendreInjoignable(", "\n}\n")
    assert "el('header', { class: 'entete' }," in inj and "el('span', { class: 'entete-appli' }, 'Cime')" in inj
    assert "nav" not in inj and "PAGES" not in inj and "el('h1'" not in inj
    assert "el('span', { class: 'pilule age-donnee', dataset: { niveau: 'rouge' } }, el('span', { class: 'pouls', 'aria-hidden': 'true' }), 'Hôte injoignable')" in inj
    assert "el('p', { class: 'injoignable-phrase' }, 'Cime n’arrive pas à joindre l’hôte.')," in inj
    assert "vider(reste, `Nouvel essai dans ${secondes} s.`);" in inj
    assert "Math.max(0, Math.ceil((fin - performance.now()) / 1000))" in inj
    assert "const fin = performance.now() + (delai || 0);" in inj
    assert "minuteurInjoignable = setInterval(decompter, 1000);" in inj and "clearInterval(minuteurInjoignable);" in inj
    assert "  if (delai) {\n    decompter();" in inj and "delai ? reste : null" in inj
    assert "title: `Rien n’est affiché tant que l’hôte ne répond pas : une page vide ne prouverait pas que tout va bien.${" in inj
    assert "role: 'alert'" in inj and "injoignable-icone" in inj
    assert "minuteurInjoignable" in _corps(commun, "export function rendreSocle(ctx)", "\n  etatCourant")  # le décompte s'arrête
    carte = _regle(css, ".injoignable-carte")
    assert "max-width: 360px" in carte and "padding: 32px" in carte and "background: var(--carte)" in carte
    assert "border: 2px solid var(--rouge)" in _regle(css, ".injoignable-icone")
    assert "rotate(45deg)" in _regle(css, ".injoignable-icone::after")
    assert "font-size: 16px; font-weight: 600" in _regle(css, ".injoignable-phrase")
    assert "min-height: calc(100vh - 56px)" in _regle(css, ".injoignable")

    # 14. le CSS ajouté n'emploie que l'existant : variables, tailles et graisses permises, une seule ombre
    ajoute = _corps(css, "/* ---------- La scène : le plateau, où la scène est montée", "/* ---------- Sections ---------- */")
    assert not re.findall(r"#[0-9A-Fa-f]{3,8}\b", ajoute.replace("#1C2029", "").replace("#121418", ""))
    assert set(re.findall(r"font-size: (\d+)px", ajoute)) <= TAILLES_PERMISES
    assert set(re.findall(r"font-weight: (\d+)", ajoute)) <= {"400", "500", "600"}
    assert set(re.findall(r"box-shadow: ([^;]+);", ajoute)) == {"0 8px 24px rgba(0, 0, 0, 0.4)"}
    assert set(re.findall(r"border-radius: ([^;]+);", ajoute)) <= {"var(--rayon)", "var(--rayon-petit)", "50%", "999px"}
    assert "overflow: hidden;" in _regle(css, ".plateau") and "setInterval" not in css


@pytest.fixture(scope="module")
def js():
    fichiers = sorted(STATIC.glob("*.js")) + sorted((STATIC / "vues").glob("*.js")) + [STATIC / "style.css"]
    return {str(f.relative_to(STATIC)): f.read_text(encoding="utf-8") for f in fichiers}


def test_plateau_scene(js):
    verifier_plateau_scene(js)


def _remplace(fichier, ancien, nouveau):
    def mutation(js):
        assert ancien in js[fichier], ancien
        return {**js, fichier: js[fichier].replace(ancien, nouveau)}
    return mutation


COM = "commun.js"
APP = "app.js"
SC = "vues/scene.js"
CSS = "style.css"
MUTATIONS = {
    # montage
    "montage à chaque rendu": _remplace(SC, "  if (!promesse) {\n    dernierEtat ??= ctx.etat;\n    promesse = monter();\n  }\n",
                                        "  dernierEtat ??= ctx.etat;\n  promesse = monter();\n"),
    "promesse jamais gardée": _remplace(SC, "    promesse = monter();\n", "    monter();\n"),
    "scène arrêtée au changement d'onglet": _remplace(SC, "  objetScene?.redimensionner();\n", "  objetScene?.redimensionner();\n  objetScene?.arreter();\n"),
    "plateau non redimensionné": _remplace(SC, "  objetScene?.redimensionner();\n", ""),
    # imports
    "import statique de la scène": lambda js: {**js, SC: "import { monterScene } from '/scene/scene.js';\n" + js[SC]},
    "import de scene.js manquant": _remplace(SC, "import('/scene/scene.js'), ", ""),
    "import de la source manquant": _remplace(SC, ", import('/scene/source-alimentee.js')", ""),
    "chemin relatif vers la scène": _remplace(SC, "import('/scene/scene.js')", "import('../../scene/scene.js')"),
    "imports l'un après l'autre": _remplace(SC, "await Promise.all([import('/scene/scene.js'), import('/scene/source-alimentee.js')])",
                                            "[await import('/scene/scene.js'), await import('/scene/source-alimentee.js')]"),
    "requête réseau dans la page": _remplace(SC, "function emettreTouche(key) {", "function emettreTouche(key) {\n  fetch('/x');"),
    "route de l'API dans la scène": _remplace(SC, "let promesse = null;", "let promesse = null; const LIRE = '/api/flux';"),
    # repli
    "import raté non attrapé": _remplace(SC, "  } catch {\n    repli();\n    return;\n  }\n", "  } finally {\n    repli();\n  }\n"),
    "repli : phrase changée": _remplace(SC, "'La scène n’est pas disponible ici.'", "'Scène indisponible.'"),
    "repli : deux éléments": _remplace(SC, "vider(plateau, el('p', { class: 'plateau-calme' }, 'La scène n’est pas disponible ici.'));",
                                       "vider(plateau, el('p', { class: 'plateau-calme' }, 'La scène n’est pas disponible ici.'), el('p', {}, 'détail'));"),
    "repli : le montage qui échoue n'est pas attrapé": _remplace(SC, "  } catch {\n    sourceScene = null;\n    repli();\n  }", "  } catch {\n    sourceScene = null;\n  }"),
    "repli : plateau-calme sans mise en forme": _remplace(CSS, ".plateau-calme { position: absolute; inset: 0;", ".plateau-calme { position: static;"),
    # source
    "source sans maintenant": _remplace(SC, "creerSourceAlimentee({ maintenant: () => performance.now() })", "creerSourceAlimentee()"),
    "instantané gardé non poussé": _remplace(SC, "  if (dernierEtat) sourceScene.pousser(dernierEtat); // le premier instantané, reçu avant le montage\n", ""),
    "instantané poussé après le montage": lambda js: {**js, SC: js[SC].replace(
        "  if (dernierEtat) sourceScene.pousser(dernierEtat); // le premier instantané, reçu avant le montage\n", "").replace(
        "  } catch {\n    sourceScene = null;", "    sourceScene.pousser(dernierEtat);\n  } catch {\n    sourceScene = null;")},
    "alimenter ne pousse pas": _remplace(SC, "  sourceScene?.pousser(etat);\n", ""),
    "alimenter ne garde pas": _remplace(SC, "  dernierEtat = etat;\n  sourceScene?.pousser(etat);", "  sourceScene?.pousser(etat);"),
    "app : alimenter jamais appelé": _remplace(APP, "    scene.alimenter(source.etat());\n", ""),
    "app : alimenter seulement si l'instantané change": _remplace(
        APP, "    scene.alimenter(source.etat());\n    // un nouvel instantané clôt les actions « envoyées » : il dit seul ce qui a été pris en compte\n    const avaitEnvoyees = nouvelInstantane();\n",
        "    // un nouvel instantané clôt les actions « envoyées » : il dit seul ce qui a été pris en compte\n    const avaitEnvoyees = nouvelInstantane();\n    if (change) scene.alimenter(source.etat());\n"),
    "app : alimenter seulement sur la scène": _remplace(APP, "    scene.alimenter(source.etat());\n", "    if (route.page === 'scene') scene.alimenter(source.etat());\n"),
    "app : alimenter pour tout événement": lambda js: {**js, APP: js[APP].replace("    scene.alimenter(source.etat());\n", "").replace(
        "  if (quoi === 'etat') {\n", "  scene.alimenter(source.etat());\n  if (quoi === 'etat') {\n")},
    # options
    "fond opaque": _remplace(SC, "theme: { fond: 'transparent' },", "theme: { fond: '#14161A' },"),
    "pas de thème": _remplace(SC, "      theme: { fond: 'transparent' },\n", ""),
    "surClic oublié": _remplace(SC, "      surClic: (cible) => { basculerLegende(false); choisir(cible); }, // un clic dans la scène referme la légende\n", ""),
    "surVide oublié": _remplace(SC, "      surVide: () => { basculerLegende(false); choisir(null); },\n", ""),
    "surSurvol oublié": _remplace(SC, "      surSurvol: survol,\n", ""),
    "surStatut oublié": _remplace(SC, "      surStatut: () => {},\n", ""),
    "surPret oublié": _remplace(SC, "      surPret: () => { pret = true; silhouette.remove(); majFige(); },\n", ""),
    "surPret sans retirer la silhouette": _remplace(SC, "pret = true; silhouette.remove(); majFige();", "pret = true; majFige();"),
    "plateau sans repère de position": _remplace(CSS, "  position: relative;\n  height: calc(100vh - 56px - 40px);", "  height: calc(100vh - 56px - 40px);"),
    # sélection
    "sélection non gardée": _remplace(SC, "  selection = cible ?? null;\n", ""),
    "scène non prévenue de la sélection": _remplace(SC, "  objetScene?.selectionner?.(selection);\n", ""),
    "sélection : méthode non optionnelle": _remplace(SC, "objetScene?.selectionner?.(selection);", "objetScene.selectionner(selection);"),
    "sélection : abonnés non prévenus": _remplace(SC, "  for (const f of abonnes) f(selection);\n", ""),
    "selectionCourante change de nom": _remplace(SC, "export function selectionCourante()", "export function selectionActuelle()"),
    "surSelection sans désabonnement": _remplace(SC, "  return () => { abonnes = abonnes.filter((f) => f !== rappel); };\n", ""),
    "Échap ne désélectionne pas": _remplace(SC, "  else if (selection) choisir(null);", ""),
    "Échap sur une autre touche": _remplace(SC, "ev.key !== 'Escape'", "ev.key !== 'Enter'"),
    "Échap ne ferme pas la légende": _remplace(SC, "  if (!legende.hidden) basculerLegende(false);\n  else if", "  if"),
    "clic qui navigue": _remplace(SC, "surClic: (cible) => { basculerLegende(false); choisir(cible); },", "surClic: (cible) => { choisir(cible); location.hash = '#/equipe/x'; },"),
    "estFige absent": _remplace(SC, "export function estFige()", "function estFige()"),
    # info-bulle
    "info-bulle sans role": _remplace(SC, "{ class: 'infobulle-plateau', role: 'tooltip' }", "{ class: 'infobulle-plateau' }"),
    "info-bulle jamais retirée": _remplace(SC, "  infobulle?.remove();\n  infobulle = null;\n  if (!cible) return;", "  if (!cible) return;"),
    "info-bulle conservée sur null": _remplace(SC, "  infobulle?.remove();\n  infobulle = null;\n  if (!cible) return;", "  if (!cible) return;\n  infobulle?.remove();\n  infobulle = null;"),
    "info-bulle décalée de 20 px": _remplace(SC, "const DECALAGE_INFOBULLE = 12;", "const DECALAGE_INFOBULLE = 20;"),
    "info-bulle sans le décalage en y": _remplace(SC, "y + DECALAGE_INFOBULLE", "y"),
    "info-bulle qui sort du plateau": _remplace(SC, "plateau.clientWidth - infobulle.offsetWidth - MARGE_INFOBULLE", "plateau.clientWidth"),
    "info-bulle qui sort par le bas": _remplace(SC, "plateau.clientHeight - infobulle.offsetHeight - MARGE_INFOBULLE", "plateau.clientHeight"),
    "info-bulle sans titre": _remplace(SC, "    el('div', { class: 'infobulle-titre' }, titre),\n", ""),
    "info-bulle sans lignes": _remplace(SC, "    lignes.map((l) => el('div', { class: 'infobulle-ligne' }, l)));", "    null);"),
    "info-bulle avec un texte de la page": _remplace(SC, "    lignes.map((l) => el('div', { class: 'infobulle-ligne' }, l)));",
                                                     "    lignes.map((l) => el('div', { class: 'infobulle-ligne' }, l)), el('div', {}, 'cliquer pour ouvrir'));"),
    "info-bulle qui capte la souris": _remplace(CSS, "max-width: 280px; padding: 8px 16px; pointer-events: none;", "max-width: 280px; padding: 8px 16px;"),
    "info-bulle sans ombre": _remplace(CSS, "  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);\n}\n.infobulle-titre", "}\n.infobulle-titre"),
    "info-bulle : titre à 14 px": _remplace(CSS, ".infobulle-titre { font-size: 13px;", ".infobulle-titre { font-size: 14px;"),
    "info-bulle : lignes à 13 px": _remplace(CSS, ".infobulle-ligne { font-size: 12px;", ".infobulle-ligne { font-size: 13px;"),
    "info-bulle sur fond transparent": _remplace(CSS, "  background: var(--carte); border: 1px solid var(--bord); border-radius: var(--rayon-petit);\n  box-shadow",
                                                 "  background: transparent; border: 1px solid var(--bord); border-radius: var(--rayon-petit);\n  box-shadow"),
    # commandes
    "zoom arrière sans la bonne touche": _remplace(SC, "{ touche: '-', signe: '−'", "{ touche: '_', signe: '−'"),
    "zoom avant sans la bonne touche": _remplace(SC, "{ touche: '+', signe: '+'", "{ touche: '=', signe: '+'"),
    "tout voir sans la bonne touche": _remplace(SC, "{ touche: '0', signe: '⤢'", "{ touche: '9', signe: '⤢'"),
    "zoom arrière sans info-bulle": _remplace(SC, "titre: 'Zoom arrière (−)'", "titre: 'Zoom arrière'"),
    "zoom avant sans info-bulle": _remplace(SC, "titre: 'Zoom avant (+)'", "titre: 'Zoom'"),
    "tout voir sans info-bulle": _remplace(SC, "titre: 'Tout voir (0)'", "titre: 'Tout voir'"),
    "boutons sans aria-label": _remplace(SC, " title: c.titre, 'aria-label': c.titre,", " title: c.titre,"),
    "boutons sans action": _remplace(SC, " onclick: () => emettreTouche(c.touche) }, c.signe)));", " }, c.signe)));"),
    "touche sans remonter": _remplace(SC, "{ key, bubbles: true }", "{ key }"),
    "touche envoyée à la page": _remplace(SC, "  if (canvas) canvas.dispatchEvent(", "  if (canvas) document.dispatchEvent("),
    "touche sur un autre type d'événement": _remplace(SC, "new KeyboardEvent('keydown',", "new KeyboardEvent('keyup',"),
    "canvas cherché hors du plateau": _remplace(SC, "const canvas = plateau.querySelector(':scope > canvas');", "const canvas = document.querySelector('canvas');"),
    "touche envoyée à une icône de la légende": _remplace(SC, "const canvas = plateau.querySelector(':scope > canvas');", "const canvas = plateau.querySelector('canvas');"),
    "touche envoyée au canvas de la légende": _remplace(SC, "const canvas = plateau.querySelector(':scope > canvas');", "const canvas = legende.querySelector('canvas');"),
    "aide à la molette de retour": _remplace(SC, "'Légende');", "'Légende'); const AIDE = 'molette ou pincement : zoom';"),
    "bouton Légende sans aria-expanded": _remplace(SC, "'aria-expanded': 'false',\n  'aria-controls'", "'aria-controls'"),
    "bouton Légende sans aria-controls": _remplace(SC, "'aria-controls': 'legende-plateau', onclick", "onclick"),
    "bouton Légende renommé": _remplace(SC, "basculerLegende() }, 'Légende');", "basculerLegende() }, 'Aide');"),
    "second clic qui n'inverse pas": _remplace(SC, "legende.hidden = !ouverte;", "legende.hidden = false;"),
    "aria-expanded jamais mis à jour": _remplace(SC, "  boutonLegende.setAttribute('aria-expanded', String(ouverte));\n", ""),
    "commandes hors du plateau": _remplace(SC, "plateau.append(silhouette, capsule, legende, boutonLegende, commandes);", "plateau.append(silhouette, capsule, legende);"),
    "boutons de 28 px": _remplace(CSS, "min-width: 32px; height: 32px; padding: 0 8px;", "min-width: 28px; height: 28px; padding: 0 8px;"),
    "légende en bas à droite": _remplace(CSS, ".commande-legende { position: absolute; left: 16px; bottom: 16px;", ".commande-legende { position: absolute; right: 16px; bottom: 16px;"),
    "zoom en haut": _remplace(CSS, ".commandes-zoom { position: absolute; right: 16px; bottom: 16px;", ".commandes-zoom { position: absolute; right: 16px; top: 16px;"),
    "zoom sans espacement": _remplace(CSS, "z-index: 2; display: flex; gap: 8px; }", "z-index: 2; display: flex; }"),
    # légende
    "légende non lue dans la scène": _remplace(SC, "const { monterScene, LEGENDE, dessinerIcone } = module.scene;", "const { monterScene, dessinerIcone } = module.scene; const LEGENDE = [];"),
    "légende jamais remplie": _remplace(SC, "    if (LEGENDE && dessinerIcone) remplirLegende(LEGENDE, dessinerIcone);\n", ""),
    "légende : panneau en div": _remplace(SC, "const legende = el('aside', {", "const legende = el('div', {"),
    "légende ouverte au départ": _remplace(SC, "'aria-label': 'Légende', hidden: true });", "'aria-label': 'Légende' });"),
    "légende sans groupes": _remplace(SC, "    groupes.set(e.groupe, [...(groupes.get(e.groupe) ?? []), e]);", "    groupes.set('tout', [...(groupes.get('tout') ?? []), e]);"),
    "légende sans intitulés": _remplace(SC, "    el('h3', {}, nom),\n", ""),
    "légende sans icônes": _remplace(SC, "      dessinerIcone(icone, e.sprite, { echelle: 2 });\n", ""),
    "icônes à l'échelle 1": _remplace(SC, "dessinerIcone(icone, e.sprite, { echelle: 2 })", "dessinerIcone(icone, e.sprite, { echelle: 1 })"),
    "icônes dans un canvas de 24 px": _remplace(SC, "el('canvas', { width: 32, height: 32 })", "el('canvas', { width: 24, height: 24 })"),
    "légende : libellé en dur": _remplace(SC, "}, e.libelle));", "}, e.sprite));"),
    "légende : rien ne distingue les problèmes": _remplace(SC, "e.probleme ? 'legende-libelle legende-probleme' : 'legende-libelle'", "'legende-libelle'"),
    "légende : tout en rouge": _remplace(SC, "e.probleme ? 'legende-libelle legende-probleme' : 'legende-libelle'", "'legende-libelle legende-probleme'"),
    "légende : entrée en dur": _remplace(SC, "function remplirLegende(entrees, dessinerIcone) {", "function remplirLegende(entrees, dessinerIcone) {\n  entrees = [...entrees, { libelle: 'x', sprite: 'y' }];"),
    "légende de 360 px": _remplace(CSS, "z-index: 2; width: 300px;", "z-index: 2; width: 360px;"),
    "légende sous le bouton": _remplace(CSS, "left: 16px; bottom: 56px; z-index: 2; width: 300px;", "left: 16px; bottom: 8px; z-index: 2; width: 300px;"),
    "légende qui ne défile pas": _remplace(CSS, "  overflow-y: auto; padding: 16px;", "  padding: 16px;"),
    "intitulés en minuscules": _remplace(CSS, "letter-spacing: 0.06em; text-transform: uppercase;", "letter-spacing: 0.06em;"),
    "intitulés à 13 px": _remplace(CSS, ".legende-groupe h3 { margin: 0 0 8px; font-size: 11px;", ".legende-groupe h3 { margin: 0 0 8px; font-size: 13px;"),
    "cases d'icône de 24 px": _remplace(CSS, ".legende-icone { flex: none; width: 32px; height: 32px;", ".legende-icone { flex: none; width: 24px; height: 24px;"),
    "libellés à 14 px": _remplace(CSS, ".legende-libelle { font-size: 13px;", ".legende-libelle { font-size: 14px;"),
    "problème en ambre": _remplace(CSS, ".legende-probleme { color: var(--rouge-clair); }", ".legende-probleme { color: var(--ambre); }"),
    "second rouge dans la légende": _remplace(CSS, ".legende-libelle { font-size: 13px; font-weight: 400; color: var(--texte-doux); }",
                                              ".legende-libelle { font-size: 13px; font-weight: 400; color: var(--rouge); }"),
    "bouton Légende en rouge": _remplace(CSS, ".commande-legende[aria-expanded=\"true\"] { border-color: var(--bleu-bord); color: var(--bleu-clair); }",
                                         ".commande-legende[aria-expanded=\"true\"] { border-color: var(--rouge-bord); color: var(--rouge-clair); }"),
    # chargement
    "silhouette absente": _remplace(SC, "plateau.append(silhouette, capsule,", "plateau.append(capsule,"),
    "silhouette lue par les lecteurs d'écran": _remplace(SC, "{ class: 'plateau-silhouette', 'aria-hidden': 'true' }", "{ class: 'plateau-silhouette' }"),
    "texte « connexion… »": _remplace(SC, "el('div', { class: 'plateau-silhouette', 'aria-hidden': 'true' })", "el('div', { class: 'plateau-silhouette', 'aria-hidden': 'true' }, 'connexion…')"),
    "silhouette trop grande": _remplace(CSS, "width: min(672px, calc(100% - 40px)); height: min(480px, calc(100% - 40px));", "width: min(800px, calc(100% - 40px)); height: min(480px, calc(100% - 40px));"),
    "silhouette non centrée": _remplace(CSS, "top: 50%; left: 50%; transform: translate(-50%, -50%);", "top: 0; left: 0;"),
    "silhouette sans couleur de carte": _remplace(CSS, "  background: var(--carte); border-radius: var(--rayon);\n  animation: silhouette", "  background: var(--bord); border-radius: var(--rayon);\n  animation: silhouette"),
    "silhouette qui ne pulse pas": _remplace(CSS, "animation: silhouette 1.6s ease-in-out infinite;", ""),
    "silhouette trop lente": _remplace(CSS, "animation: silhouette 1.6s", "animation: silhouette 3s"),
    "pulsation de 0,3 à 1": _remplace(CSS, "0%, 100% { opacity: 0.6; }", "0%, 100% { opacity: 0.3; }"),
    "animation non coupée": _remplace(CSS, "@media (prefers-reduced-motion: reduce) { .plateau-silhouette { animation: none; } }", ""),
    # figé
    "figé sans flux interrompu": _remplace(SC, "Boolean(pret && sourcePage && sourcePage.fluxInterrompu())", "Boolean(pret && sourcePage)"),
    "figé avant le chargement": _remplace(SC, "Boolean(pret && sourcePage && sourcePage.fluxInterrompu())", "Boolean(sourcePage && sourcePage.fluxInterrompu())"),
    "figé sans marque sur le plateau": _remplace(SC, "    plateau.dataset.fige = 'oui';\n", ""),
    "figé jamais levé": _remplace(SC, "    delete plateau.dataset.fige;\n", ""),
    "capsule sans durée": _remplace(SC, "`Image figée depuis ${duree(sourcePage.horloge.ageDonnee())} — l’hôte ne répond plus`", "'Image figée — l’hôte ne répond plus'"),
    "capsule : phrase changée": _remplace(SC, "— l’hôte ne répond plus`", "— hôte absent`"),
    "capsule : âge d'une autre horloge": _remplace(SC, "duree(sourcePage.horloge.ageDonnee())", "duree(sourcePage.horloge.maintenant())"),
    "capsule toujours visible": _remplace(SC, "  capsule.hidden = !fige;\n", ""),
    "capsule sans role": _remplace(SC, "{ class: 'capsule-figee', role: 'status', hidden: true }", "{ class: 'capsule-figee', hidden: true }"),
    "figé non accroché à tic": _remplace(SC, "surTic(majFige);\n", ""),
    "figé non réévalué au rendu": _remplace(SC, "  majFige();\n  ctx.tic();", "  ctx.tic();"),
    "minuteur propre à la scène": _remplace(SC, "surTic(majFige);\n", "setInterval(majFige, 1000);\n"),
    "tic n'appelle pas les rappels": _remplace(COM, "  for (const rappel of rappelsTic) rappel();\n", ""),
    "surTic n'enregistre rien": _remplace(COM, "  rappelsTic.add(rappel);\n", ""),
    "source de la page oubliée": _remplace(SC, "  sourcePage = ctx.source;\n", ""),
    "canvas sans filtre": _remplace(CSS, "filter: grayscale(85%) brightness(70%)", "filter: none"),
    "filtre trop léger": _remplace(CSS, "grayscale(85%)", "grayscale(30%)"),
    "filtre sur le plateau entier": _remplace(CSS, '.plateau[data-fige="oui"] > canvas {', '.plateau[data-fige="oui"] {'),
    "capsule sans fond rouge": _remplace(CSS, "background: var(--rouge-fond); color: var(--rouge-clair); border: 1px solid var(--rouge-bord);",
                                         "background: var(--ambre-fond); color: var(--rouge-clair); border: 1px solid var(--rouge-bord);"),
    "capsule en ambre": _remplace(CSS, "background: var(--rouge-fond); color: var(--rouge-clair); border: 1px solid var(--rouge-bord);",
                                  "background: var(--rouge-fond); color: var(--ambre); border: 1px solid var(--rouge-bord);"),
    "capsule non centrée": _remplace(CSS, "top: 16px; left: 50%; transform: translateX(-50%);", "top: 16px; left: 16px;"),
    "capsule carrée": _remplace(CSS, "border: 1px solid var(--rouge-bord); border-radius: 999px;", "border: 1px solid var(--rouge-bord); border-radius: 0;"),
    "focus non rendu": _remplace(SC, "  dernierFocus?.focus({ preventScroll: true });\n", ""),
    "focus jamais noté": _remplace(SC, "dernierFocus = plateau.contains(ev.target) ? ev.target : null;", "dernierFocus = null;"),
    # hôte injoignable
    "injoignable : onglets": _remplace(COM, "el('div', { class: 'entete-titres' }, el('span', { class: 'entete-appli' }, 'Cime')),",
                                       "el('div', { class: 'entete-titres' }, el('span', { class: 'entete-appli' }, 'Cime')),\n      el('nav', { class: 'nav' }, PAGES.map((p) => el('a', { href: p.href }, p.titre))),"),
    "injoignable : titre de projet": _remplace(COM, "el('span', { class: 'entete-appli' }, 'Cime')),\n      el('div', { class: 'entete-etat' },\n        el('span', { class: 'pilule age-donnee', dataset: { niveau: 'rouge' } }",
                                               "el('span', { class: 'entete-appli' }, 'Cime'), el('h1', {}, 'Hôte injoignable')),\n      el('div', { class: 'entete-etat' },\n        el('span', { class: 'pilule age-donnee', dataset: { niveau: 'rouge' } }"),
    "injoignable : sans marque": _remplace(COM, "el('span', { class: 'entete-appli' }, 'Cime')),\n      el('div', { class: 'entete-etat' },\n        el('span', { class: 'pilule age-donnee', dataset: { niveau: 'rouge' } }",
                                           "el('span', { class: 'entete-appli' }, 'Centre')),\n      el('div', { class: 'entete-etat' },\n        el('span', { class: 'pilule age-donnee', dataset: { niveau: 'rouge' } }"),
    "injoignable : pastille pas rouge": _remplace(COM, "dataset: { niveau: 'rouge' } }, el('span', { class: 'pouls'", "dataset: { niveau: 'ambre' } }, el('span', { class: 'pouls'"),
    "injoignable : pastille « aucune donnée »": _remplace(COM, "'Hôte injoignable')", "'aucune donnée')"),
    "injoignable : phrase changée": _remplace(COM, "'Cime n’arrive pas à joindre l’hôte.'", "'Erreur.'"),
    "injoignable : pas de décompte": _remplace(COM, "        delai ? reste : null))));", "        null))));"),
    "injoignable : décompte figé": _remplace(COM, "    minuteurInjoignable = setInterval(decompter, 1000);\n", ""),
    "injoignable : décompte aux 2 s": _remplace(COM, "setInterval(decompter, 1000)", "setInterval(decompter, 2000)"),
    "injoignable : décompte en négatif": _remplace(COM, "Math.max(0, Math.ceil(", "(Math.ceil("),
    "injoignable : décompte jamais commencé": _remplace(COM, "  if (delai) {\n    decompter();\n", "  if (delai) {\n"),
    "injoignable : phrase du décompte changée": _remplace(COM, "`Nouvel essai dans ${secondes} s.`", "`Essai dans ${secondes} s.`"),
    "injoignable : minuteurs qui s'empilent": _remplace(COM, "export function rendreInjoignable({ essai, erreur, delai }) {\n  clearInterval(minuteurInjoignable);\n",
                                                        "export function rendreInjoignable({ essai, erreur, delai }) {\n"),
    "injoignable : minuteur jamais arrêté": _remplace(COM, "export function rendreSocle(ctx) {\n  clearInterval(minuteurInjoignable);\n", "export function rendreSocle(ctx) {\n"),
    "injoignable : phrase de l'info-bulle perdue": _remplace(COM, "Rien n’est affiché tant que l’hôte ne répond pas : une page vide ne prouverait pas que tout va bien.${",
                                                            "Hôte absent.${"),
    "injoignable : carte sans alerte": _remplace(COM, "el('div', { class: 'injoignable-carte', role: 'alert',", "el('div', { class: 'injoignable-carte',"),
    "injoignable : sans icône": _remplace(COM, "        el('span', { class: 'injoignable-icone', 'aria-hidden': 'true' }),\n", ""),
    "injoignable : carte trop large": _remplace(CSS, ".injoignable-carte {\n  width: 100%; max-width: 360px;", ".injoignable-carte {\n  width: 100%; max-width: 720px;"),
    "injoignable : carte sans marge": _remplace(CSS, "max-width: 360px; padding: 32px;", "max-width: 360px; padding: 4px;"),
    "injoignable : icône sans cercle": _remplace(CSS, "border: 2px solid var(--rouge); border-radius: 50%; }", "border-radius: 50%; }"),
    "injoignable : icône non barrée": _remplace(CSS, "transform: rotate(45deg);", "transform: none;"),
    "injoignable : phrase à 13 px": _remplace(CSS, ".injoignable-phrase { margin: 0; font-size: 16px;", ".injoignable-phrase { margin: 0; font-size: 13px;"),
    "injoignable : carte en haut": _remplace(CSS, ".injoignable { min-height: calc(100vh - 56px);", ".injoignable { min-height: 0;"),
    # CSS ajouté
    "couleur en dur": _remplace(CSS, ".legende-probleme { color: var(--rouge-clair); }", ".legende-probleme { color: var(--rouge-clair); }\n.legende-x { color: #FF0000; }"),
    "taille de police hors échelle": _remplace(CSS, ".legende-libelle { font-size: 13px;", ".legende-libelle { font-size: 15px;"),
    "graisse hors échelle": _remplace(CSS, ".infobulle-titre { font-size: 13px; font-weight: 600;", ".infobulle-titre { font-size: 13px; font-weight: 700;"),
    "seconde ombre": _remplace(CSS, ".legende {\n  position: absolute; left: 16px; bottom: 56px; z-index: 2; width: 300px; max-width: calc(100% - 32px); max-height: calc(100% - 72px);\n  overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 16px;\n  background: var(--carte); border: 1px solid var(--bord); border-radius: var(--rayon);\n  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);",
                               ".legende {\n  position: absolute; left: 16px; bottom: 56px; z-index: 2; width: 300px; max-width: calc(100% - 32px); max-height: calc(100% - 72px);\n  overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 16px;\n  background: var(--carte); border: 1px solid var(--bord); border-radius: var(--rayon);\n  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.3);"),
    "rayon hors échelle": _remplace(CSS, ".legende {\n  position: absolute; left: 16px; bottom: 56px; z-index: 2; width: 300px; max-width: calc(100% - 32px); max-height: calc(100% - 72px);\n  overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 16px;\n  background: var(--carte); border: 1px solid var(--bord); border-radius: var(--rayon);",
                                     ".legende {\n  position: absolute; left: 16px; bottom: 56px; z-index: 2; width: 300px; max-width: calc(100% - 32px); max-height: calc(100% - 72px);\n  overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 16px;\n  background: var(--carte); border: 1px solid var(--bord); border-radius: 14px;"),
    "plateau qui défile": _remplace(CSS, "  border: 1px solid var(--bord); border-radius: var(--rayon);\n  overflow: hidden;\n}", "  border: 1px solid var(--bord); border-radius: var(--rayon);\n  overflow: auto;\n}"),
}


@pytest.mark.parametrize("nom", MUTATIONS)
def test_mutation_detectee(nom, js):
    mutee = MUTATIONS[nom](js)  # hors du raises : la mutation doit s'appliquer, sinon le test serait faux
    with pytest.raises(AssertionError):
        verifier_plateau_scene(mutee)


def test_couverture_des_verifications():
    toutes = {n for n, v in globals().items() if n.startswith("verifier_") and callable(v)}
    assert toutes == {"verifier_plateau_scene"} and MUTATIONS, sorted(toutes)
