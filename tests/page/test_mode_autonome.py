"""L'interrupteur « Mode autonome » dans la Scène : pilote le champ `fusions_auto` et l'action `/api/actions/fusions-auto`.

Même convention que test_supervision_coince_dependances.py : d'abord l'analyse de texte du JS, du CSS et de l'exemple (`verifier_mode_autonome` lève AssertionError, la table
MUTATIONS prouve qu'elle échoue quand on casse chaque règle) ; puis node (sauté s'il est absent) pour les fonctions pures (`verifier_fonctions`) et pour le
rendu avec un DOM minimal (`verifier_rendu` : les cinq états, le rail, le tiroir et la feuille du téléphone, l'en-tête, l'action, chaque vue),
chacun avec ses mutations exécutées.
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

PAGE = Path(__file__).resolve().parents[2] / "src" / "cime" / "page"
STATIC = PAGE / "static"
AU, COM, SRC, MO, RA, MOB, JOU, CSS = ("autonome.js", "commun.js", "source.js", "vues/mode-autonome.js", "vues/rail.js", "vues/mobile.js",
                                       "vues/journal.js", "style.css")
EXE = "exemple-etat.json"
EXEMPLE_ETAT = Path(__file__).resolve().parent / "fixtures" / EXE
FICHIERS = [AU, COM, SRC, MO, RA, MOB, JOU, CSS]


def _corps(texte, debut, fin):
    i = texte.find(debut)
    assert i >= 0, debut
    j = texte.find(fin, i + len(debut))
    assert j >= 0, fin
    return texte[i:j]


def _regle(css, selecteur):
    m = re.search(r"(?:^|\n) *" + re.escape(selecteur) + r" \{([^}]*)\}", css)
    assert m, selecteur
    return re.sub(r"/\*.*?\*/", "", m.group(1), flags=re.S)


def _ordre(texte, *morceaux):
    positions = []
    for m in morceaux:
        assert m in texte, m
        positions.append(texte.index(m))
    assert positions == sorted(positions), morceaux


# ---------------------------------------------------------------------------
# Les chemins de l'exemple : les 43 chemins réservés proposés par l'hôte, regroupés par thème
# ---------------------------------------------------------------------------
COMPTES = {"architecture": 9, "fondation": 2, "droits": 1, "reseau": 14, "secrets": 8, "projet": 9}


def verifier_exemple(exemple):
    etat = json.loads(exemple)
    f = etat["fusions_auto"]
    assert set(f) == {"active", "suspendue", "depuis", "par", "reserves", "reserves_proposees", "derniere_fusion", "portee", "chantiers_24h", "chantiers_max", "decisions"}, sorted(f)
    assert f["active"] is False and f["suspendue"] is False and f["reserves"] == [] and f["derniere_fusion"] is None  # l'exemple est inactif : l'hôte réel relevé
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", f["depuis"]) and f["par"] == "utilisateur"
    assert len(f["reserves_proposees"]) == sum(COMPTES.values()) == 43 and len(set(f["reserves_proposees"])) == 43
    assert ".orga/contracts/" in f["reserves_proposees"] and ".orga/etat/reglages/" in f["reserves_proposees"] and "src/cime/fondation/" in f["reserves_proposees"]


# ---------------------------------------------------------------------------
# Analyse de texte
# ---------------------------------------------------------------------------
def verifier_mode_autonome(js):
    au, com, src, mo, ra, mob, jou, css = (js[n] for n in (AU, COM, SRC, MO, RA, MOB, JOU, CSS))

    # 1. les tables de données : ce que l'Assistant décide (DECIDE), les thèmes qui restent à l'utilisateur, dans l'ordre de l'hôte
    assert "export const DECIDE = ['fusionne à ta place'];" in au
    assert "export const HORS_CHEMINS = { complet: 'push, suppression de branche', court: 'push et branches' };" in au
    themes = _corps(au, "export const THEMES = [", "\n];\n")
    _ordre(themes, "cle: 'architecture'", "cle: 'fondation'", "cle: 'droits'", "cle: 'reseau'", "cle: 'secrets'")
    for dossier in ("src\\/cime", "tests\\/", "signaux", "gabarits", "hote"):  # un produit ne connaît aucun dossier d'un projet donné
        assert dossier not in themes, dossier
    for titre in ("Architecture et contrats", "Fondation : registre, garde, hooks", "Droits", "Réseau et dépendances", "Secrets"):
        assert f"titre: '{titre}'" in themes, titre
    assert "export const MAX_CHEMINS_PAR_THEME = 5;" in au
    assert "export const PHRASE_PROJET = 'les chemins propres au projet';" in au and "PHRASE_PLUS_PROJET" not in au + mo  # plus de fragment après le point
    assert "export const phraseRepli = () => `Restent à toi : ${[...THEMES.map((t) => t.phrase), PHRASE_PROJET, HORS_CHEMINS.court].join(', ')}.`;" in au
    assert "if (total === null) return phraseRepli();" in au and "export function phraseInactif(connue = true)" in au and "phraseRepli()" in au
    assert "Mode autonome activé : l’Assistant ${DECIDE.join(' et ')}, hors chemins réservés." in au
    assert "'Mode autonome désactivé : chaque fusion revient à ton accord.'" in au
    assert "export const LIBELLE_MODE = 'Mode autonome';" in au
    assert "{ active: 'Activation…', inactive: 'Désactivation…' }" in au
    assert "`Activé, l’Assistant ${DECIDE.join(' et ')}. ${reste}`" in au  # la phrase se construit sur les tables, elle s'allonge avec elles
    assert "[...THEMES.map((t) => t.phrase), HORS_CHEMINS.court].join(', ')" in au
    assert "if (chemins === null) return THEMES.map(" in au and "Propres à ${nomProjet}" in au
    assert "mode.etat === 'inactif' ? 'active' : 'inactive'" in au  # un mode suspendu se désactive par l'interrupteur ; « Réactiver » envoie `active`
    assert "lecture.derniere_fusion && typeof lecture.derniere_fusion === 'object'" in au
    assert "import " not in au  # le module des données n'importe rien : aucun DOM, importable partout

    # 2. l'interrupteur : un vrai interrupteur, libellé à gauche de la piste, désactivé et occupé pendant la requête
    inter = _corps(mo, "export function interrupteurMode(", "\n}\n")
    for morceau in ("role: 'switch'", "'aria-checked': String(mode.etat !== 'inactif')", "'aria-busy': demande ? 'true' : null",
                    "disabled: Boolean(demande) || fige", "title: fige ? PHRASE_ACTIONS_FIGEES", "onclick: () => basculerMode(valeurApresClic(mode))",
                    "class: `inter${suspendu ? ' suspendu' : ''}`", "'aria-describedby': suspendu ? 'encadre-mode' : null"):
        assert morceau in inter, morceau
    assert "demande ? LIBELLE_ENCOURS[demande] : LIBELLE_MODE, el('span', { class: 'piste', 'aria-hidden': 'true' })" in inter  # le libellé avant la piste
    assert "type: 'button'" in inter

    # 3. l'encadré : une ligne discrète inactif, un encadré bleu pâle actif, un encadré ambre suspendu avec « Réactiver avec cette liste »
    enc = _corps(mo, "export function encadreMode(", "\n}\n")
    assert "class: 'etat-auto inactif'" in enc and "class: 'etat-auto actif', id: 'encadre-mode'" in enc and "class: 'etat-auto suspendu', id: 'encadre-mode'" in enc
    assert "el('p', {}, phraseInactif(connue))," in enc
    assert "el('b', {}, 'Suspendu, fusions arrêtées :')" in enc and "' la liste des chemins réservés a changé depuis ton activation'" in enc
    assert "'. Chaque fusion revient à ton accord.'" in enc
    assert "    el('button', { type: 'button', class: 'action'," in enc  # le bouton est dessiné
    assert "      connue ? detailsReserves(etat, mode, (g, c) => `Voir la liste" in enc  # la liste proposée se lit avant l'activation
    assert "depuis ? ` (${depuis})` : null" in enc
    assert "'Voir la liste actuelle'" in enc and "`Voir la liste actuelle · ${c.length} ${c.length === 1 ? 'chemin' : 'chemins'}`" in enc
    assert "onclick: () => basculerMode('active') }, demande ? LIBELLE_ENCOURS[demande] : 'Réactiver avec cette liste')" in enc  # pas de désactivation puis activation
    assert "ligneReserves(g, c === null ? null : c.length)" in enc  # le nombre vient de la liste, jamais inventé
    assert "el('b', {}, phraseDecide())" in enc and "depuisPar(mode)" in enc and "ligneDerniere(etat, mode)" in enc
    assert "return ' · aucune fusion encore';" in mo
    assert "parAutre(mode) ? ` par ${parAutre(mode)}` : null" in mo
    assert "const phraseDecide = () => `L’Assistant ${DECIDE.join(' et ')}`;" in mo
    assert "ouvrirDialogue" not in mo and "ouvrirDialogue" not in _corps(com, "export async function basculerMode(", "\n}\n")  # pas de confirmation
    assert "Voir la liste · ${c.length}" in enc

    # 4. les réserves : un titre par thème et son compte, des chemins en mono qui ne se coupent pas, « … » au-delà de 5, la dernière ligne sans chemins
    theme = _corps(mo, "function blocTheme(", "\n}\n")
    assert "el('h3', {}, groupe.titre, el('span', {}, ` · ${groupe.chemins.length}`))" in theme
    assert "el('span', { class: 'chemin' }, c)" in theme and "i ? ' · ' : null" in theme
    assert "const tout = themesEnEntier.has(groupe.cle);" in theme and "abrege ? [' · ', el('button'" in theme and "onclick: bascule(true) }, '…')" in theme
    assert "cheminsMontres(groupe.chemins, tout)" in theme and "'…'" in theme and "'replier ▴'" in theme
    assert "themesEnEntier.add(groupe.cle)" in theme and "redessiner();" in theme
    assert "el('h3', {}, 'Toujours, hors chemins'), el('p', { class: 'hors-chemins' }, HORS_CHEMINS.complet)" in mo
    assert "ontoggle: (ev) => { listeDepliee = ev.target.open; }" in mo and "open: listeDepliee" in mo  # le repli survit au redessin du rail
    assert "regrouperReserves(chemins, etat.projet ? etat.projet.nom : null)" in mo
    assert "white-space: nowrap" in _regle(css, ".chemin") and "var(--mono)" in _regle(css, ".theme .chemins")

    # 5. l'action : la même voie que les autres (source.agir, journal, figée si l'hôte est injoignable), la raison de l'hôte en cas de refus
    basc = _corps(com, "export async function basculerMode(", "\n}\n")
    assert "if (modeEnCours || actionsFigees) return;" in basc
    assert "source.agir('fusions_auto', { valeur }, { cible: 'projet', details: { valeur } })" in basc
    assert "annoncer(TOASTS[valeur]);" in basc
    assert "annoncer(phraseEchec(reponse), reponse.resultat === 'refuse' ? 'ambre' : 'rouge');" in basc
    assert "modeEnCours = null;\n    annoncer(phraseEchec" in basc  # refus ou échec : l'interrupteur reprend sa position
    assert "demande.requete = false;" in basc and "setTimeout(() => { if (modeEnCours === demande) { modeEnCours = null; rerendre();" in basc and "ATTENTE_MODE_MS" in basc
    assert "focusAMode = avaitLeFocus;" in basc and "if (focusAMode) {\n      focusAMode = false;\n      requestAnimationFrame(retrouverFocusMode);" in com and "rerendre(); retrouverFocusMode(); } }, ATTENTE_MODE_MS)" in basc
    assert basc.endswith("  rerendre();\n  retrouverFocusMode();")  # le clavier retrouve l'interrupteur redessiné
    assert "if (actif && actif !== document.body && !(actif.classList && actif.classList.contains('inter'))) return;" in com  # sans voler un focus allé ailleurs
    assert "retrouverFocusMode();" in basc and "inters[inters.length - 1].focus()" in _corps(com, "function retrouverFocusMode(", "\n}\n")
    assert "rapprocherMode(ctx.etat);" in _corps(com, "export function rendreSocle(", "\n}\n")
    assert "if (modeEnCours && !modeEnCours.requete && modeAtteint(modeEnCours.valeur, etat)) {\n    modeEnCours = null;" in com
    assert "fusions_auto: '/api/actions/fusions-auto'," in _corps(src, "const ROUTES_ACTIONS = {", "};")
    assert "export const actionsSontFigees = () => actionsFigees;" in com
    assert "fusions_auto: 'mode autonome'," in jou
    assert "export function annoncer(texte, ton = 'ok')" in com and "poserToast(t, reponse.resultat === 'ok' ? 5000 : 10000);" in com

    # 6. la pastille d'en-tête : seulement quand actif ou suspendu, juste avant le compteur d'attentes, un clic mène à la scène
    pastille = _corps(com, "export function pastilleAutonome(", "\n}\n")
    assert "if (mode.etat === 'inactif') return null;" in pastille
    assert "class: `pastille-auto ${mode.etat}`, href: '#/', title: titrePastille(mode)" in pastille
    assert "el('span', { class: 'pastille-long' }, mots.long), el('span', { class: 'pastille-court' }, mots.court)" in pastille
    _ordre(_corps(com, "function entete(ctx)", "\n}\n"), "iconeSources(ctx.etat)", "pastilleAutonome(ctx.etat)", "compteurAttentes(ctx.etat)")
    assert "actif: { long: 'Autonome', court: 'Auto' }" in au and "suspendu: { long: 'Autonome suspendu', court: 'Suspendu' }" in au
    assert "`Mode autonome : l’Assistant ${DECIDE.join(' et ')}${depuis ? ` depuis ${depuis}` : ''}`" in au
    corps_pastille = _regle(css, ".pastille-auto")
    assert "white-space: nowrap" in corps_pastille and "flex: none" in corps_pastille
    assert "var(--bleu-fond)" in _regle(css, ".pastille-auto.actif") and "var(--ambre-fond)" in _regle(css, ".pastille-auto.suspendu")

    # 7. le rail : l'interrupteur à droite du titre « Ce qui t'attend », dessiné aussi quand rien n'attend ; le tiroir du téléphone ; la feuille
    assert "const mode = interrupteurMode(etat);" in ra and ra.count("classe, mode)") == 3
    assert "const rienNAttend = Array.isArray(etat.attentes_utilisateur) && etat.attentes_utilisateur.length === 0;" in ra
    assert "rienNAttend ? blocTiroirMode(etat, redessiner) : null" in ra
    assert "const modeDansLaFeuille = (etat) => { const a = attentesOuvertes(etat); return a === null || a.length > 0; };" in mob
    # l'interrupteur n'est pas dans la tête de la feuille (elle tient en une ligne à 320 px) : première ligne du contenu, puis les effectifs, puis l'encadré
    contenu = _corps(mob, "function contenuAttentes(", "\n}\n")
    assert "modeDansLaFeuille(etat) ? el('div', { class: 'feuille-mode' }, interrupteurMode(etat)) : null," in contenu
    _ordre(contenu, "interrupteurMode(etat)", "class: 'feuille-effectifs'", "encadreMode(etat, () => majFeuilleAttentes(dernierEtat))")
    assert "modeDansLaFeuille(etat) ? encadreMode(etat, () => majFeuilleAttentes(dernierEtat)) : null" in mob
    for mort in ("enTete", "remplacerTete", "teteAttentes"):
        assert mort not in mob and mort not in com, mort  # plus d'emplacement dans la tête : un seul emplacement pour l'interrupteur au téléphone
    assert "feuille-tete-extra" not in css and "feuille-tete-extra" not in com
    assert "el('header', { class: 'feuille-tete' }, intitule,\n      el('button', { type: 'button', class: 'bouton feuille-fermer', onclick: fermer }, 'Fermer'))," in com  # titre + « Fermer », rien entre
    assert "display: flex" in _regle(css, ".feuille-mode")

    # 8. le CSS : une cible de 44 px, bleu actif, ambre suspendu, gris éteint, jamais rouge ni vert ; l'anneau de focus du socle n'est pas retiré
    region = _corps(css, "/* ---------- Le mode autonome", "\n.bouton {") if "/* ---------- Le mode autonome" in css else None
    assert region is not None
    inter_css = _regle(css, ".inter")
    assert "height: 44px" in inter_css and "outline" not in inter_css and "outline: none" not in css
    assert re.search(r"(?:^|\n):focus-visible \{ outline: 2px solid", css)
    assert "var(--gris-fond)" in _regle(css, ".piste")
    assert "var(--bleu)" in _regle(css, '.inter[aria-checked="true"] .piste') and "var(--bleu-clair)" in _regle(css, '.inter[aria-checked="true"]')
    assert "var(--ambre)" in _regle(css, ".inter.suspendu .piste") and "var(--ambre)" in _regle(css, ".inter.suspendu")
    assert "left: 16px" in _regle(css, '.inter[aria-checked="true"] .piste::after')
    mode_css = _corps(css, "/* ---------- Le mode autonome", "/* ---------- ")
    # le marqueur de « Voir la liste » est un chevron de 12 px à la couleur du texte (plus de triangle minuscule gris)
    marqueur = _regle(css, ".reserves > summary::before")
    assert "content: ''" in marqueur and "currentColor" in marqueur and "transform: rotate(-45deg)" in marqueur and "var(--discret)" not in marqueur and "▸" not in css
    assert "rotate(45deg)" in _regle(css, ".reserves[open] > summary::before")
    assert "width: 6px" in marqueur and "height: 6px" in marqueur and "border-right: 2px" in marqueur  # 6 + 2 px de bordure = 8 px, tourné : ≈ 12 px de large
    assert "rouge" not in mode_css and "vert" not in mode_css, "le mode autonome n'est jamais rouge ni vert"
    assert "cursor: progress" in _regle(css, ".inter:disabled")
    assert "var(--bleu-fond)" in _regle(css, ".etat-auto.actif") and "var(--ambre-fond)" in _regle(css, ".etat-auto.suspendu")
    assert "font-size: 12px" in _regle(css, ".etat-auto") and "var(--discret)" in _regle(css, ".etat-auto.inactif")
    assert "min-height: 44px" in _regle(css, ".rail-tete")
    # la tête de la feuille : « Fermer » ne se coupe jamais, le titre s'abrège par une ellipse (test_entete_feuille.py mesure les largeurs)
    fermer = _regle(css, ".feuille-fermer")
    assert "flex: none" in fermer and "white-space: nowrap" in fermer
    titre = _regle(css, ".feuille-tete h2")
    assert all(d in titre for d in ("white-space: nowrap", "overflow: hidden", "text-overflow: ellipsis", "min-width: 0"))


@pytest.fixture(scope="module")
def js():
    return {**{n: (STATIC / n).read_text(encoding="utf-8") for n in FICHIERS}, EXE: EXEMPLE_ETAT.read_text(encoding="utf-8")}


def test_mode_autonome(js):
    verifier_mode_autonome(js)


def test_exemple_du_mode_autonome(js):
    verifier_exemple(js[EXE])


def _remplace(fichier, ancien, nouveau):
    def mutation(js):
        assert ancien in js[fichier], ancien
        return {**js, fichier: js[fichier].replace(ancien, nouveau, 1)}
    return mutation


MUTATIONS = {
    # 1. les tables
    "DECIDE vidée": _remplace(AU, "export const DECIDE = ['fusionne à ta place'];", "export const DECIDE = [];"),
    "ligne « hors chemins » courte changée": _remplace(AU, "court: 'push et branches'", "court: 'push'"),
    "thèmes dans le désordre": _remplace(AU, "    cle: 'fondation', titre", "    cle: 'zz', titre"),
    "dossier du projet dans THEMES": _remplace(AU, "motifs: [/^\\.orga\\/etat\\/?$/, /^\\.claude\\/?$/],", "motifs: [/^\\.orga\\/etat\\/?$/, /^\\.claude\\/?$/, /^(src\\/cime|tests)\\/(fondation|signaux|gabarits|hote)(\\/|$)/],"),
    "titre de thème changé": _remplace(AU, "titre: 'Droits'", "titre: 'Droit'"),
    "plafond de chemins changé": _remplace(AU, "MAX_CHEMINS_PAR_THEME = 5", "MAX_CHEMINS_PAR_THEME = 8"),
    "toast d'activation changé": _remplace(AU, "hors chemins réservés.`", "sauf secrets.`"),
    "toast de désactivation changé": _remplace(AU, "chaque fusion revient à ton accord.'", "plus rien ne se fait.'"),
    "libellé changé": _remplace(AU, "LIBELLE_MODE = 'Mode autonome'", "LIBELLE_MODE = 'Fusions auto'"),
    "libellé de la requête changé": _remplace(AU, "{ active: 'Activation…', inactive: 'Désactivation…' }", "{ active: 'Un instant…', inactive: 'Un instant…' }"),
    "phrase inactive figée dans le rendu": _remplace(AU, "`Activé, l’Assistant ${DECIDE.join(' et ')}. ${reste}`", "'Activé, l’Assistant fusionne à ta place.'"),
    "phrase inactive sans la table des thèmes": _remplace(AU, "[...THEMES.map((t) => t.phrase), HORS_CHEMINS.court].join(', ')", "'tout'"),
    "liste inconnue : pas de thèmes du noyau": _remplace(AU, "if (chemins === null) return THEMES.map(", "if (chemins === null) return [].map("),
    "chemins propres sans nom de projet": _remplace(AU, "Propres à ${nomProjet}", "Propres au projet"),
    "interrupteur qui ne réactive pas": _remplace(AU, "mode.etat === 'inactif' ? 'active' : 'inactive'", "mode.etat !== 'actif' ? 'active' : 'inactive'"),
    "dernière action illisible": _remplace(AU, "lecture.derniere_fusion && typeof lecture.derniere_fusion === 'object'", "false"),
    "module de données avec un import": _remplace(AU, "// Cime — le mode autonome : données", "import { el } from './commun.js';\n// Cime — le mode autonome : données"),
    # 2. l'interrupteur
    "interrupteur sans rôle switch": _remplace(MO, "role: 'switch', ", ""),
    "interrupteur sans aria-checked": _remplace(MO, "'aria-checked': String(mode.etat !== 'inactif'), ", ""),
    "suspendu non coché": _remplace(MO, "String(mode.etat !== 'inactif')", "String(mode.etat === 'actif')"),
    "interrupteur sans aria-busy": _remplace(MO, "'aria-busy': demande ? 'true' : null,\n    'aria-describedby'", "'aria-describedby'"),
    "interrupteur actif pendant la requête": _remplace(MO, "disabled: Boolean(demande) || fige,", "disabled: fige,"),
    "interrupteur actif quand l'hôte ne répond plus": _remplace(MO, "disabled: Boolean(demande) || fige,", "disabled: Boolean(demande),"),
    "interrupteur sans libellé de requête": _remplace(MO, "demande ? LIBELLE_ENCOURS[demande] : LIBELLE_MODE, el('span', { class: 'piste'", "LIBELLE_MODE, el('span', { class: 'piste'"),
    "libellé après la piste": _remplace(MO, "demande ? LIBELLE_ENCOURS[demande] : LIBELLE_MODE, el('span', { class: 'piste', 'aria-hidden': 'true' })", "el('span', { class: 'piste', 'aria-hidden': 'true' }), demande ? LIBELLE_ENCOURS[demande] : LIBELLE_MODE"),
    "interrupteur suspendu non ambre": _remplace(MO, "class: `inter${suspendu ? ' suspendu' : ''}`", "class: 'inter'"),
    "interrupteur qui envoie toujours active": _remplace(MO, "onclick: () => basculerMode(valeurApresClic(mode)),", "onclick: () => basculerMode('active'),"),
    # 3. l'encadré
    "encadré suspendu sans bouton": _remplace(MO, "    el('button', { type: 'button', class: 'action',", "    null && el('button', { type: 'button', class: 'action',"),
    "bouton qui désactive avant de réactiver": _remplace(MO, "onclick: () => basculerMode('active') }, demande", "onclick: () => basculerMode('inactive') }, demande"),
    "titre suspendu changé": _remplace(MO, "'Suspendu, fusions arrêtées :'", "'Suspendu :'"),
    "encadré suspendu sans l'heure d'activation": _remplace(MO, "      depuis ? ` (${depuis})` : null,", "      null,"),
    "confirmation retapée": _remplace(MO, "onclick: () => basculerMode('active') }, demande", "onclick: () => ouvrirDialogue('Réactiver', () => []) }, demande"),
    "encadré actif sans « par »": _remplace(MO, "parAutre(mode) ? ` par ${parAutre(mode)}` : null", "null"),
    "« par » même pour utilisateur": _remplace(MO, "parAutre(mode) ? ` par ${parAutre(mode)}` : null", "mode.par ? ` par ${mode.par}` : null"),
    "aucune dernière action : rien": _remplace(MO, "return ' · aucune fusion encore';", "return null;"),
    "encadré actif sans phrase d'action": _remplace(MO, "el('b', {}, phraseDecide()), ", ""),
    "nombre de chemins inventé": _remplace(MO, "ligneReserves(g, c === null ? null : c.length)", "ligneReserves(g, c === null ? 44 : c.length)"),
    "liste actuelle sans compte": _remplace(MO, "`Voir la liste actuelle · ${c.length} ${c.length === 1 ? 'chemin' : 'chemins'}`", "'Voir la liste actuelle'"),
    "liste inactive sans compte": _remplace(MO, "`Voir la liste · ${c.length} ${c.length === 1 ? 'chemin' : 'chemins'}`", "'Voir la liste'"),
    "inactif sans la liste proposée": _remplace(MO, "      connue ? detailsReserves(etat, mode, (g, c) => `Voir la liste", "      null && detailsReserves(etat, mode, (g, c) => `Voir la liste"),
    "inactif sans la phrase de repli": _remplace(MO, "el('p', {}, phraseInactif(connue)),", "el('p', {}, phraseInactif()),"),
    "repli : fragment après le point": _remplace(AU, "PHRASE_PROJET, HORS_CHEMINS.court].join(', ')}.`;", "HORS_CHEMINS.court].join(', ')}. + ${PHRASE_PROJET}`;"),
    "repli : projet après ce qui est hors chemins": _remplace(AU, "[...THEMES.map((t) => t.phrase), PHRASE_PROJET, HORS_CHEMINS.court].join(', ')}.`;", "[...THEMES.map((t) => t.phrase), HORS_CHEMINS.court, PHRASE_PROJET].join(', ')}.`;"),
    "repli : phrase figée": _remplace(AU, "export const phraseRepli = () => `Restent à toi : ${[...THEMES.map((t) => t.phrase), PHRASE_PROJET, HORS_CHEMINS.court].join(', ')}.`;", "export const phraseRepli = () => 'Restent à toi : architecture et contrats, fondation, droits, réseau, secrets, les chemins propres au projet, push et branches.';"),
    "ligne repliée inconnue sans la phrase de repli": _remplace(AU, "if (total === null) return phraseRepli();", "if (total === null) return `Restent à toi : ${mots}.`;"),
    # 4. les réserves
    "thème sans compte": _remplace(MO, "el('h3', {}, groupe.titre, el('span', {}, ` · ${groupe.chemins.length}`))", "el('h3', {}, groupe.titre)"),
    "chemins sans séparateur": _remplace(MO, "i ? ' · ' : null", "null"),
    "chemin sans insécable": _remplace(MO, "el('span', { class: 'chemin' }, c)", "c"),
    "plus de « … »": _remplace(MO, "abrege ? [' · ', el('button'", "false ? [' · ', el('button'"),
    "« … » sans effet": _remplace(MO, "onclick: bascule(true) }, '…')", "}, '…')"),
    "tout sans « replier »": _remplace(MO, "'replier ▴')", "'')"),
    "thème toujours en entier": _remplace(MO, "const tout = themesEnEntier.has(groupe.cle);", "const tout = true;"),
    "dernière ligne sans chemins perdue": _remplace(MO, "el('div', { class: 'theme' }, el('h3', {}, 'Toujours, hors chemins'), el('p', { class: 'hors-chemins' }, HORS_CHEMINS.complet))", "null"),
    "repli oublié au redessin": _remplace(MO, "ontoggle: (ev) => { listeDepliee = ev.target.open; }", "ontoggle: () => {}"),
    "liste dépliée d'office": _remplace(MO, "open: listeDepliee", "open: true"),
    "liste mal regroupée (sans le nom du projet)": _remplace(MO, "regrouperReserves(chemins, etat.projet ? etat.projet.nom : null)", "regrouperReserves(chemins, null)"),
    # 5. l'action
    "action sans garde des actions figées": _remplace(COM, "if (modeEnCours || actionsFigees) return;", "if (modeEnCours) return;"),
    "action sans garde de requête": _remplace(COM, "if (modeEnCours || actionsFigees) return;", "if (actionsFigees) return;"),
    "action vers une autre route": _remplace(COM, "source.agir('fusions_auto', { valeur }", "source.agir('autoriser', { valeur }"),
    "action sans journal": _remplace(COM, "{ cible: 'projet', details: { valeur } }", "{}"),
    "toast d'activation oublié": _remplace(COM, "annoncer(TOASTS[valeur]);", ""),
    "refus sans la raison": _remplace(COM, "annoncer(phraseEchec(reponse), reponse.resultat === 'refuse' ? 'ambre' : 'rouge');", "annoncer('Refusé.', 'ambre');"),
    "interrupteur resté en attente après un refus": _remplace(COM, "    modeEnCours = null;\n    annoncer(phraseEchec", "    annoncer(phraseEchec"),
    "attente de l'instantané oubliée": _remplace(COM, "    demande.requete = false; // l'interrupteur attend l'instantané qui montre le réglage\n", ""),
    "attente sans fin": _remplace(COM, "    setTimeout(() => { if (modeEnCours === demande) { modeEnCours = null; rerendre(); retrouverFocusMode(); } }, ATTENTE_MODE_MS);\n", ""),
    "instantané sans effet sur l'attente": _remplace(COM, "  rapprocherMode(ctx.etat);\n", ""),
    "focus perdu": _remplace(COM, "  rerendre();\n  retrouverFocusMode();\n}", "  rerendre();\n}"),
    "focus jamais rendu après l'attente": _remplace(COM, "      requestAnimationFrame(retrouverFocusMode); // après le dessin de la page\n", ""),
    "focus volé": _remplace(COM, "  if (actif && actif !== document.body && !(actif.classList && actif.classList.contains('inter'))) return;\n", ""),
    "route absente de la couche de données": _remplace(SRC, "  fusions_auto: '/api/actions/fusions-auto',\n", ""),
    "journal sans libellé": _remplace(JOU, "  fusions_auto: 'mode autonome',\n", ""),
    # 6. la pastille
    "pastille aussi quand inactif": _remplace(COM, "if (mode.etat === 'inactif') return null;\n  const mots", "const mots = PASTILLE[mode.etat] || PASTILLE.actif;\n  const mots2"),
    "pastille sans lien vers la scène": _remplace(COM, "href: '#/', title: titrePastille(mode)", "href: '#/supervision', title: titrePastille(mode)"),
    "pastille sans info-bulle": _remplace(COM, "href: '#/', title: titrePastille(mode)", "href: '#/'"),
    "pastille sans forme courte": _remplace(COM, ", el('span', { class: 'pastille-court' }, mots.court)", ""),
    "pastille après le compteur": _remplace(COM, "      pastille" + "Autonome(ctx.etat),\n      compteurAttentes(ctx.etat),", "      compteurAttentes(ctx.etat),\n      pastille" + "Autonome(ctx.etat),"),
    "pastille actif écrite autrement": _remplace(AU, "actif: { long: 'Autonome', court: 'Auto' }", "actif: { long: 'Fusions auto', court: 'Auto' }"),
    "pastille suspendu écrite autrement": _remplace(AU, "suspendu: { long: 'Autonome suspendu', court: 'Suspendu' }", "suspendu: { long: 'Autonome suspendu', court: 'Pause' }"),
    "info-bulle sans l'heure": _remplace(AU, "${depuis ? ` depuis ${depuis}` : ''}`;\n}", "`;\n}"),
    # 7. le rail, le tiroir, la feuille
    "tiroir sans le mode quand rien n'attend": _remplace(RA, "rienNAttend ? blocTiroirMode(etat, redessiner) : null", "null"),
    "tiroir avec le mode même quand des attentes": _remplace(RA, "rienNAttend ? blocTiroirMode(etat, redessiner) : null", "blocTiroirMode(etat, redessiner)"),
    "feuille sans le mode en première ligne": _remplace(MOB, "    modeDansLaFeuille(etat) ? el('div', { class: 'feuille-mode' }, interrupteurMode(etat)) : null,", "    null,"),
    "feuille avec le mode après les effectifs": _remplace(MOB, "    modeDansLaFeuille(etat) ? el('div', { class: 'feuille-mode' }, interrupteurMode(etat)) : null, // première ligne : la tête reste titre + « Fermer »\n    el('div', { class: 'feuille-effectifs' }, resumeAgents(etat)),\n", "    el('div', { class: 'feuille-effectifs' }, resumeAgents(etat)),\n    modeDansLaFeuille(etat) ? el('div', { class: 'feuille-mode' }, interrupteurMode(etat)) : null,\n"),
    "interrupteur remis dans la tête": _remplace(MOB, "    pleinEcran: true,\n", "    pleinEcran: true,\n    enTete: [interrupteurMode(etat)],\n"),
    "emplacement de tête rouvert": _remplace(COM, "    el('header', { class: 'feuille-tete' }, intitule,\n", "    el('header', { class: 'feuille-tete' }, intitule, extra,\n"),
    "feuille avec le mode même sans attente": _remplace(MOB, "const modeDansLaFeuille = (etat) => { const a = attentesOuvertes(etat); return a === null || a.length > 0; };", "const modeDansLaFeuille = () => true;"),
    "feuille sans encadré": _remplace(MOB, "modeDansLaFeuille(etat) ? encadreMode(etat, () => majFeuilleAttentes(dernierEtat)) : null", "null"),
    # 8. le CSS
    "cible de 30 px": _remplace(CSS, "display: inline-flex; align-items: center; gap: 8px; height: 44px; padding: 0;", "display: inline-flex; align-items: center; gap: 8px; height: 30px; padding: 0;"),
    "anneau de focus retiré": _remplace(CSS, "  background: none; border: 0; border-radius: var(--rayon-petit); color: var(--secondaire); font: 500 13px var(--police); white-space: nowrap; cursor: pointer;", "  background: none; border: 0; outline: none; border-radius: var(--rayon-petit); color: var(--secondaire); font: 500 13px var(--police); white-space: nowrap; cursor: pointer;"),
    "actif vert": _remplace(CSS, ".inter[aria-checked=\"true\"] .piste { background: var(--bleu); }", ".inter[aria-checked=\"true\"] .piste { background: var(--vert); }"),
    "suspendu rouge": _remplace(CSS, ".inter.suspendu .piste { background: var(--ambre); }", ".inter.suspendu .piste { background: var(--rouge); }"),
    "éteint non gris": _remplace(CSS, "background: var(--gris-fond); transition: background 0.15s; }", "background: var(--bleu); transition: background 0.15s; }"),
    "bouton glissé à gauche": _remplace(CSS, '.inter[aria-checked="true"] .piste::after { left: 16px;', '.inter[aria-checked="true"] .piste::after { left: 2px;'),
    "encadré actif non bleu": _remplace(CSS, ".etat-auto.actif { background: var(--bleu-fond);", ".etat-auto.actif { background: var(--ambre-fond);"),
    "ligne inactive en 14 px": _remplace(CSS, ".etat-auto { margin: 0; font-size: 12px;", ".etat-auto { margin: 0; font-size: 14px;"),
    "chemin qui se coupe": _remplace(CSS, ".chemin { white-space: nowrap; }", ".chemin { white-space: normal; }"),
    "ligne de titre trop basse": _remplace(CSS, ".rail-tete { display: flex; align-items: center; gap: 8px; min-height: 44px; }", ".rail-tete { display: flex; align-items: center; gap: 8px; min-height: 20px; }"),
    "état du mode en rouge": _remplace(CSS, ".etat-auto.suspendu { background: var(--ambre-fond); border-color: var(--ambre-bord); }", ".etat-auto.suspendu { background: var(--ambre-fond); border-color: var(--rouge-bord); }"),
    "pastille bleue suspendue": _remplace(CSS, ".pastille-auto.suspendu { background: var(--ambre-fond);", ".pastille-auto.suspendu { background: var(--bleu-fond);"),
    "marqueur en triangle gris": _remplace(CSS, "content: ''; display: inline-block; position: relative; top: -1px;", "content: '▸ '; color: var(--discret); display: inline-block; position: relative; top: -1px;"),
    "marqueur d'un autre ton": _remplace(CSS, "border-right: 2px solid currentColor; border-bottom: 2px solid currentColor; transform: rotate(-45deg);", "border-right: 2px solid var(--discret); border-bottom: 2px solid var(--discret); transform: rotate(-45deg);"),
    "Fermer qui se coupe": _remplace(CSS, ".feuille-fermer { flex: none; white-space: nowrap;", ".feuille-fermer { white-space: normal;"),
    "Fermer qui se comprime": _remplace(CSS, ".feuille-fermer { flex: none; white-space: nowrap;", ".feuille-fermer { white-space: nowrap;"),
    "titre de feuille sur deux lignes": _remplace(CSS, "text-overflow: ellipsis; white-space: nowrap; font-size: 16px; font-weight: 600; }", "text-overflow: ellipsis; font-size: 16px; font-weight: 600; }"),
    "titre de feuille sans ellipse": _remplace(CSS, ".feuille-tete h2 { margin: 0; min-width: 0; overflow: hidden; text-overflow: ellipsis;", ".feuille-tete h2 { margin: 0; min-width: 0;"),
    "interrupteur de feuille collé à gauche": _remplace(CSS, ".feuille-mode { flex: none; display: flex; }", ".feuille-mode { flex: none; }"),
}


@pytest.mark.parametrize("nom", MUTATIONS)
def test_mutation_detectee(nom, js):
    mutee = MUTATIONS[nom](js)  # hors du raises : la mutation doit s'appliquer, sinon le test serait faux
    with pytest.raises(AssertionError):
        verifier_mode_autonome(mutee)


def test_exemple_alteree_detectee(js):
    verifier_exemple(js[EXE])
    etat = json.loads(js[EXE])
    for casse in (lambda f: f.pop("reserves_proposees"), lambda f: f.update(active=True), lambda f: f.update(reserves_proposees=f["reserves_proposees"][:-1]),
                  lambda f: f.update(reserves_proposees=f["reserves_proposees"] + [f["reserves_proposees"][0]]), lambda f: f.update(depuis="hier")):
        copie = json.loads(json.dumps(etat))
        casse(copie["fusions_auto"])
        texte = json.dumps(copie, indent=2, ensure_ascii=False) + "\n"
        with pytest.raises((AssertionError, KeyError)):
            verifier_exemple(texte)


# ---------------------------------------------------------------------------
# node : les fonctions pures et le rendu avec un DOM minimal
# ---------------------------------------------------------------------------
DOM = r"""
import { readFileSync } from 'node:fs';
class Node {}
class Txt extends Node { constructor(t) { super(); this.data = t; } }
class Elt extends Node {
  constructor(tag) { super(); this.tag = tag; this.attrs = {}; this.children = []; this.dataset = {}; this.style = {}; this.ecouteurs = {}; this.focus_recu = 0;
    this.classList = { contains: (c) => this.classes.includes(c), toggle() {}, add: (c) => { this.attrs.class = `${this.attrs.class || ''} ${c}`; }, remove() {} }; }
  setAttribute(k, v) { this.attrs[k] = v; }
  getAttribute(k) { return this.attrs[k] ?? null; }
  addEventListener(t, f) { (this.ecouteurs[t] ||= []).push(f); }
  removeEventListener() {}
  append(...n) { this.children.push(...n); }
  prepend(...n) { this.children.unshift(...n); }
  querySelectorAll() { return []; }
  querySelector() { return null; }
  remove() {}
  focus() { if (!('disabled' in this.attrs)) this.focus_recu += 1; }  // un bouton désactivé ne prend pas le focus
  showModal() { this.open = true; }
  close() { this.open = false; (this.ecouteurs.close || []).forEach((f) => f({})); }
  replaceChildren(...n) { this.children = n; }
  set textContent(v) { this.children = [new Txt(String(v))]; }
  set innerHTML(v) { this.content = { firstElementChild: new Elt('svg') }; }
  get classes() { return (this.attrs.class || '').split(/\s+/).filter(Boolean); }
}
globalThis.Node = Node;
globalThis.document = { createElement: (t) => new Elt(t), createTextNode: (t) => new Txt(t), documentElement: new Elt('html'), body: new Elt('body'),
  querySelector: () => null, querySelectorAll: () => [], addEventListener() {}, removeEventListener() {}, visibilityState: 'hidden', title: '' };
globalThis.window = globalThis;
globalThis.addEventListener = () => {};
globalThis.matchMedia = () => ({ matches: false, addEventListener() {} });
globalThis.localStorage = { getItem: () => null, setItem() {} };
globalThis.ResizeObserver = class { observe() {} disconnect() {} };
globalThis.requestAnimationFrame = (f) => f();
globalThis.history = { replaceState() {} };
globalThis.location = { hash: '' };
const texte = (n) => (n instanceof Txt ? n.data : (n.children || []).map(texte).join(''));
const sous = (n) => (n instanceof Elt ? [n, ...n.children.flatMap(sous)] : []);
const a = (n, c) => sous(n).filter((m) => m.classes.includes(c));
const clic = (n) => (n.ecouteurs.click || []).map((f) => f({ target: n }));
const sortie = (objet) => process.stdout.write(JSON.stringify(objet) + '\n', () => process.exit(0));
"""

SONDE_PURE = DOM + r"""
const racine = process.argv[2];
const au = await import(`${racine}/autonome.js`);
const commun = await import(`${racine}/commun.js`);
const exemple = JSON.parse(readFileSync(process.argv[3], 'utf8'));
const proposees = exemple.fusions_auto.reserves_proposees;
const avec = (f) => ({ fusions_auto: f });
const mode = (f) => au.lireMode(avec(f));
const etats = [undefined, null, 'x', {}, { active: false }, { active: true }, { active: true, suspendue: false }, { active: true, suspendue: true },
  { active: false, suspendue: true }, { active: 'oui' }].map((f) => au.lireMode(f === undefined ? {} : avec(f)).etat);
const nu = au.lireMode(null).etat;
const liste = (f) => au.listeVisible(mode(f));
const theme = (c) => au.themeDe(c);
const groupes = au.regrouperReserves(proposees, 'projet-boutique');
const mini = au.regrouperReserves(['src/cime/scene/x.py', 'CLAUDE.md', 'tests/scene/', 'tests/hote/t.py', 'a'], null);
const montre = (n, tout) => { const r = au.cheminsMontres(Array.from({ length: n }, (_, i) => `c${i}`), tout); return [r.montres.length, r.abrege, r.reste]; };
const tz = (iso) => au.heureCourte(iso);
sortie({
  etats, nu,
  listes: [
    liste({ active: true, reserves: ['a', 'b', 'a'], reserves_proposees: ['z'] }), liste({ active: true, reserves: [], reserves_proposees: ['z'] }), liste({ active: true }),
    liste({ active: false, reserves: [], reserves_proposees: ['z', 'y'] }), liste({ active: false, reserves: [] }), liste({ active: true, suspendue: true, reserves: ['x'], reserves_proposees: ['z'] }),
    liste({ active: true, suspendue: true, reserves: ['x'] }), liste({ active: false, reserves_proposees: [] }), liste({ active: false, reserves_proposees: 'z' }), liste({ active: true, reserves: [1, null, 'k'] }),
  ],
  themes: {
    comptes: Object.fromEntries(groupes.map((g) => [g.cle, g.chemins.length])), ordre: groupes.map((g) => g.cle), titres: groupes.map((g) => g.titre), courts: groupes.map((g) => g.court),
    droits: theme('.orga/etat/reglages/'), etat: theme('.orga/etat/'), claude: theme('.claude/'), hote: theme('src/cime/hote/gardes.py'), testsHote: theme('tests/hote/t.py'),
    scene: theme('src/cime/scene/'), testsScene: theme('tests/scene/'), claudeMd: theme('CLAUDE.md'), equipes: theme('.orga/teams/*/mandate.md'), envJoker: theme('.env.*'), env: theme('**/.env'),
    cle: theme('id_rsa*'), lock: theme('uv.lock'), github: theme('.github/'), inconnu: theme('autre/chose'), serveur: theme('src/app/serveur.py'), docs: theme('docs/'),
  },
  mini: mini.map((g) => [g.cle, g.titre, g.court, g.chemins]),
  noyau: au.regrouperReserves(null, 'x').map((g) => [g.cle, g.chemins]),
  vide: au.regrouperReserves([], 'x'),
  montres: [montre(3, false), montre(5, false), montre(6, false), montre(6, true), montre(12, false), montre(12, true)],
  lignes: [au.ligneReserves(groupes, 43), au.ligneReserves(groupes, 1), au.ligneReserves(au.regrouperReserves(null), null), au.ligneReserves(mini, 5)],
  inactif: au.phraseInactif(),
  heures: [tz('2026-10-06T21:10:00.000Z'), tz('2026-10-06T21:05:00.000Z'), tz('2026-10-06T05:00:00.000Z'), tz('2026-10-06T22:00:00.000Z'), tz('pas une date'), tz(null), tz('')],
  derniere: [au.derniereAction(mode({ active: true, derniere_fusion: { equipe: 'page', sha: 'f223c94abcdef', horodatage: 'h' } })), au.derniereAction(mode({ active: true, derniere_fusion: null })),
    au.derniereAction(mode({ active: true })), au.derniereAction(mode({ active: true, derniere_fusion: { equipe: 3 } }))],
  par: [au.parAutre(mode({ active: true, par: 'utilisateur' })), au.parAutre(mode({ active: true, par: 'assistant' })), au.parAutre(mode({ active: true })), au.parAutre(mode({ active: true, par: '' }))],
  valeurs: [au.valeurApresClic(mode(undefined)), au.valeurApresClic(mode({ active: true })), au.valeurApresClic(mode({ active: true, suspendue: true }))],
  titres: [au.titrePastille(mode({ active: true, depuis: '2026-10-06T21:10:00.000Z' })), au.titrePastille(mode({ active: true })),
    au.titrePastille(mode({ active: true, suspendue: true, depuis: '2026-10-06T21:10:00.000Z' })), au.titrePastille(mode({ active: true, suspendue: true }))],
  toasts: au.TOASTS,
  age: commun.ilYA('2026-10-07T12:52:11.123Z', Date.parse('2026-10-07T13:04:11.123Z')),
  pastilles: au.PASTILLE,
});
"""

ETATS_ATTENDUS = ["inactif", "inactif", "inactif", "inactif", "inactif", "actif", "actif", "suspendu", "inactif", "inactif"]
LISTES_ATTENDUES = [["a", "b"], None, None, ["z", "y"], None, ["z"], None, None, None, ["k"]]
ORDRE_ATTENDU = ["architecture", "fondation", "droits", "reseau", "secrets"]
TITRES_ATTENDUS = ["Architecture et contrats", "Fondation : registre, garde, hooks", "Droits", "Réseau et dépendances", "Secrets"]
COURTS_ATTENDUS = ["architecture", "fondation", "droits", "réseau", "secrets"]
REPLI = "Restent à toi : architecture et contrats, fondation, droits, réseau, secrets, les chemins propres au projet, push et branches."  # la phrase de repli (liste inconnue), d'un seul tenant, sans nombre
INACTIF_ATTENDU = ("Activé, l’Assistant fusionne à ta place. Restent à toi : architecture et contrats, fondation, droits, réseau, secrets, push et branches.")


def verifier_fonctions(static, exemple):
    r = _lancer_sonde(static, SONDE_PURE, [static, exemple])
    assert r["etats"] == ETATS_ATTENDUS, r["etats"]  # absent, null, illisible : inactif ; suspendu seulement si actif
    assert r["nu"] == "inactif"
    assert r["listes"] == LISTES_ATTENDUES, r["listes"]  # actif : la liste enregistrée ; sinon la liste proposée ; inconnue : null (jamais un nombre inventé) ; sans doublon
    t = r["themes"]
    assert t["comptes"] == COMPTES and t["ordre"] == ORDRE_ATTENDU + ["projet"] and t["titres"] == TITRES_ATTENDUS + ["Propres à projet-boutique"] and t["courts"] == COURTS_ATTENDUS + ["propres à projet-boutique"], t
    assert (t["droits"], t["etat"], t["claude"], t["hote"], t["testsHote"], t["scene"], t["testsScene"]) == ("droits", "fondation", "fondation", "projet", "projet", "projet", "projet")
    assert (t["claudeMd"], t["equipes"], t["envJoker"], t["env"], t["cle"], t["lock"], t["github"], t["inconnu"], t["serveur"], t["docs"]) == (
        "architecture", "architecture", "secrets", "secrets", "secrets", "reseau", "reseau", "projet", "projet", "projet")
    assert r["mini"] == [["architecture", "Architecture et contrats", "architecture", ["CLAUDE.md"]],  # l'ordre des thèmes, puis les chemins propres au projet
                         ["projet", "Propres au projet", "propres au projet", ["src/cime/scene/x.py", "tests/scene/", "tests/hote/t.py", "a"]]], r["mini"]
    assert r["noyau"] == [[c, None] for c in ORDRE_ATTENDU] and r["vide"] == []
    assert r["montres"] == [[3, False, 0], [5, False, 0], [5, True, 1], [6, False, 0], [5, True, 7], [12, False, 0]], r["montres"]
    assert r["lignes"] == ["Restent à toi : architecture, fondation, droits, réseau, secrets, propres à projet-boutique · 43 chemins", "Restent à toi : architecture, fondation, droits, réseau, secrets, propres à projet-boutique · 1 chemin",
                           "Restent à toi : architecture et contrats, fondation, droits, réseau, secrets, les chemins propres au projet, push et branches.",
                           "Restent à toi : architecture, propres au projet · 5 chemins"], r["lignes"]
    assert r["inactif"] == INACTIF_ATTENDU
    assert r["heures"] == ["23 h 10", "23 h 05", "7 h", "0 h", None, None, None], r["heures"]  # l'heure locale (TZ=Europe/Paris, été)
    assert r["derniere"] == [{"equipe": "page", "sha": "f223c94", "horodatage": "h"}, None, None, {"equipe": None, "sha": None, "horodatage": None}], r["derniere"]
    assert r["par"] == [None, "assistant", None, None] and r["valeurs"] == ["active", "inactive", "inactive"]
    assert r["titres"] == ["Mode autonome : l’Assistant fusionne à ta place depuis 23 h 10", "Mode autonome : l’Assistant fusionne à ta place",
                           "Mode autonome suspendu : la liste des chemins réservés a changé depuis ton activation (23 h 10)", "Mode autonome suspendu : la liste des chemins réservés a changé"], r["titres"]
    assert r["toasts"] == {"active": "Mode autonome activé : l’Assistant fusionne à ta place, hors chemins réservés.",
                           "inactive": "Mode autonome désactivé : chaque fusion revient à ton accord."}
    assert r["age"] == "il y a 12 min"
    assert r["pastilles"] == {"actif": {"long": "Autonome", "court": "Auto"}, "suspendu": {"long": "Autonome suspendu", "court": "Suspendu"}}


# --- le rendu ---------------------------------------------------------------------------------------------------------
SONDE_RENDU = DOM + r"""
const racine = process.argv[2];
const jeux = JSON.parse(readFileSync(process.argv[3], 'utf8'));
const commun = await import(`${racine}/commun.js`);
const vue = await import(`${racine}/vues/mode-autonome.js`);
const rail = await import(`${racine}/vues/rail.js`);
const mobile = await import(`${racine}/vues/mobile.js`);
const sortie_ = {};
const resume = (n) => ({ tag: n.tag, classes: n.classes, texte: texte(n), attrs: n.attrs });
const reponses = [];
let appels = [];
let rendus = 0;
const attendre = () => new Promise((r) => setTimeout(r, 0));
const source = { mode: 'hote', horloge: { maintenant: () => Date.parse('2026-10-07T13:04:11.123Z'), ageDonnee: () => 0 }, fluxInterrompu: () => false,
  agir: (...args) => { appels.push(args); return new Promise((res) => reponses.push(res)); } };
commun.brancher(source, () => { rendus += 1; });

// 1. les cinq états : l'interrupteur et l'encadré
const etats = {};
for (const [nom, etat] of Object.entries(jeux)) {
  vue.reinitialiserReplis();
  const redessins = [];
  const inter = vue.interrupteurMode(etat);
  const enc = vue.encadreMode(etat, () => redessins.push(1));
  etats[nom] = { inter: resume(inter), piste: a(inter, 'piste').map(resume), encadre: enc ? { ...resume(enc), id: enc.attrs.id ?? null, details: a(enc, 'reserves').map((d) => ({ ouvert: 'open' in d.attrs, resume: texte(d.children[0]) })),
    themes: a(enc, 'theme').map((t) => [texte(t.children[0]), t.children[1] ? texte(t.children[1]) : null]), chemins: a(enc, 'chemin').length,
    boutons: sous(enc).filter((n) => n.tag === 'button').map((b) => ({ texte: texte(b), classes: b.classes, disabled: 'disabled' in b.attrs, busy: b.attrs['aria-busy'] ?? null })),
    gras: sous(enc).filter((n) => n.tag === 'b').map(texte), temps: sous(enc).filter((n) => n.tag === 'time').map((n) => [n.attrs.datetime, texte(n)]), mono: a(enc, 'mono').map(texte) } : null };
}
sortie_.etats = etats;

// 2. un repli choisi par l'utilisateur survit au redessin ; « … » montre tout et redessine
{
  const actif = jeux['actif'];
  vue.reinitialiserReplis();
  const redessine = [];
  let enc = vue.encadreMode(actif, () => redessine.push(1));
  const details = a(enc, 'reserves')[0];
  details.ecouteurs.toggle.forEach((f) => f({ target: { open: true } }));
  enc = vue.encadreMode(actif, () => redessine.push(1));
  const ouvert = 'open' in a(enc, 'reserves')[0].attrs;
  const projet = a(enc, 'theme')[5];
  const avant = a(projet, 'chemin').length;
  const suite = sous(projet).filter((n) => n.classes.includes('chemins-suite'));
  clic(suite[0]);
  enc = vue.encadreMode(actif, () => redessine.push(1));
  const apres = a(a(enc, 'theme')[5], 'chemin').length;
  const replier = sous(a(enc, 'theme')[5]).filter((n) => n.classes.includes('chemins-suite')).map(texte);
  sortie_.replis = { ouvert, avant, suite: suite.map((n) => [texte(n), n.attrs['aria-label']]), redessine: redessine.length, apres, replier,
    droits: a(a(enc, 'theme')[2], 'chemins-suite').length };
  vue.reinitialiserReplis();
  sortie_.apresReinit = 'open' in a(vue.encadreMode(actif, () => {}), 'reserves')[0].attrs;
}

// 3. l'en-tête (rendreSocle) : la pastille
const entetes = {};
for (const [nom, etat] of Object.entries(jeux)) {
  const ctx = commun.rendreSocle({ etat, page: 'scene', journal: [], route: {}, source });
  const racinePage = document.body.children[0];
  const entete = racinePage.children[0];
  const etatBloc = a(entete, 'entete-etat')[0];
  entetes[nom] = { ordre: etatBloc.children.map((n) => n.classes.join(' ') || n.tag), pastille: a(entete, 'pastille-auto').map((p) => ({ ...resume(p), href: p.attrs.href, title: p.attrs.title,
    longue: texte(a(p, 'pastille-long')[0]), courte: texte(a(p, 'pastille-court')[0]) })) };
}
sortie_.entetes = entetes;

// 4. le rail : l'interrupteur à droite du titre, trois cas (des attentes, rien, inconnu), et le téléphone
const rails = {};
const exemple = jeux['actif'];
for (const [cas, attentes] of [['attentes', exemple.attentes_utilisateur], ['rien', []], ['inconnu', null]]) {
  for (const telephone of [false, true]) {
    const e = { ...exemple, attentes_utilisateur: attentes };
    const conteneur = new Elt('aside');
    rail.rendreRail(conteneur, { etat: e, selection: null, fermer() {}, ouvrir() {}, redessiner() {}, telephone });
    const blocs = conteneur.children.filter((n) => n instanceof Elt);
    const premier = blocs[0];
    rails[`${cas}|${telephone ? 'telephone' : 'bureau'}`] = {
      blocs: blocs.map((b) => b.attrs['aria-label']),
      inters: sous(conteneur).filter((n) => n.classes.includes('inter')).length,
      tete: premier ? a(premier, 'rail-tete').map((t) => t.children.map((c) => c.tag + '.' + (c.classes[0] ?? ''))) : null,
      titre: premier ? texte(sous(premier).find((n) => n.tag === 'h2') ?? new Txt('')) : null,
      encadres: sous(conteneur).filter((n) => n.classes.includes('etat-auto')).length,
      ordre: premier ? premier.children.map((c) => c.classes[0] ?? c.tag) : null,
      aSousTitre: premier ? sous(premier).filter((n) => n.classes.includes('rail-calme')).length : 0,
      inconnuBloc: premier ? sous(premier).filter((n) => n.classes.includes('inconnu-bloc')).length : 0,
      cartes: sous(conteneur).filter((n) => n.classes.includes('attente')).length,
    };
  }
}
sortie_.rails = rails;

// 5. la feuille « Ce qui t'attend » du téléphone : la tête est le titre et « Fermer » ; l'interrupteur est la première ligne du contenu quand des attentes
const feuilles = {};
for (const [cas, attentes] of [['attentes', exemple.attentes_utilisateur], ['rien', []], ['inconnu', null]]) {
  document.body.children.length = 0;
  mobile.majFeuilleAttentes({ ...exemple, attentes_utilisateur: attentes });
  mobile.ouvrirFeuilleAttentes();
  const dialogue = document.body.children.find((n) => n.tag === 'dialog');
  const tete = a(dialogue, 'feuille-tete')[0];
  const compter = () => sous(dialogue).filter((n) => n.classes.includes('inter')).length;
  feuilles[cas] = { tete: tete.children.map((c) => c.classes[0] ?? c.tag), intersDansTete: sous(tete).filter((n) => n.classes.includes('inter')).length,
    contenu: a(dialogue, 'feuille-contenu')[0].children.map((c) => c.classes[0] ?? c.tag),
    mode: a(dialogue, 'feuille-mode').map((m) => m.children.map((n) => [n.tag, n.attrs.role ?? null])),
    encadres: sous(dialogue).filter((n) => n.classes.includes('etat-auto')).length, inters: compter() };
  // un nouvel instantané remplace le contenu sur place : l'interrupteur apparaît ou disparaît avec les attentes
  const autre = cas === 'rien' ? exemple.attentes_utilisateur : [];
  mobile.majFeuilleAttentes({ ...exemple, attentes_utilisateur: autre });
  feuilles[cas].apres = compter();
  mobile.fermerFeuilleAttentes();
}
sortie_.feuilles = feuilles;

// 6 bis. le focus : l'interrupteur touché au clavier le retrouve après le redessin ; un focus allé ailleurs n'est pas volé
const focus = {};
{
  const nouveau = new Elt('button'); nouveau.attrs.class = 'inter';
  const ancien = new Elt('button'); ancien.attrs.class = 'inter';
  document.querySelectorAll = (sel) => (sel === '.inter' ? [nouveau] : []);
  const essai = async (nom, reponse, ailleurs, avant = ancien) => {
    nouveau.focus_recu = 0; appels = []; reponses.length = 0;
    document.activeElement = avant;
    const promesse = commun.basculerMode('active');
    document.activeElement = ailleurs === undefined ? null : ailleurs; // le bouton désactivé perd le focus
    if (reponse.resultat === 'ok') nouveau.attrs.disabled = ''; // le nouvel interrupteur attend l'instantané : désactivé
    else delete nouveau.attrs.disabled;
    reponses[0](reponse);
    await promesse;
    const apres_reponse = nouveau.focus_recu;
    delete nouveau.attrs.disabled;
    commun.rendreSocle({ etat: jeux[reponse.resultat === 'ok' ? 'actif' : 'inactif'], page: 'scene', journal: [], route: {}, source });
    focus[nom] = [apres_reponse, nouveau.focus_recu];
  };
  await essai('refus', { resultat: 'refuse', message: 'x' });
  await essai('ok', { resultat: 'ok', message: '' });
  await essai('ok, focus ailleurs', { resultat: 'ok', message: '' }, new Elt('input'));
  await essai('ok, à la souris', { resultat: 'ok', message: '' }, undefined, null);
  document.activeElement = undefined;
  document.querySelectorAll = () => [];
}
sortie_.focus = focus;

// 6. l'action : le clic, la requête (désactivé, occupé), la réponse (ok, refus, erreur), l'hôte qui ne répond plus
const actions = {};
const toasts = () => document.body.children.filter((n) => n.classes.includes('toasts')).flatMap((p) => p.children).map((t) => [t.classes.join(' '), texte(t)]);
const etatInactif = jeux['inactif'];
const interCourant = (etat) => vue.interrupteurMode(etat);
{
  document.body.children.length = 0; appels = []; rendus = 0; reponses.length = 0;
  const inter = interCourant(etatInactif);
  const promesse = clic(inter)[0];
  const pendant = interCourant(etatInactif);
  const boutonPendant = vue.encadreMode(jeux['suspendu'], () => {});
  const doubleClic = clic(interCourant(etatInactif))[0];
  actions.pendant = { resume: resume(pendant), appels: appels.length, appel: appels[0], demande: commun.modeDemande(), rendus, reactiver: sous(boutonPendant).filter((n) => n.classes.includes('action')).map((b) => [texte(b), 'disabled' in b.attrs, b.attrs['aria-busy'] ?? null]) };
  reponses[0]({ resultat: 'ok', message: '' });
  await promesse; await doubleClic;
  actions.apres_ok = { demande: commun.modeDemande(), toasts: toasts(), appels: appels.length, rendus, focus: 0, interrupteur: resume(interCourant(etatInactif)) };
  // l'instantané qui montre le réglage met fin à l'attente (rendreSocle le constate)
  commun.rendreSocle({ etat: jeux['inactif'], page: 'scene', journal: [], route: {}, source });
  actions.encore_inactif = commun.modeDemande();
  commun.rendreSocle({ etat: jeux['actif'], page: 'scene', journal: [], route: {}, source });
  actions.atteint = commun.modeDemande();
}
for (const [nom, reponse, depart] of [['refus', { resultat: 'refuse', message: 'déjà actif' }, 'inactif'], ['erreur', { resultat: 'erreur', message: 'hôte injoignable (réseau)' }, 'inactif'],
  ['desactive', { resultat: 'ok', message: '' }, 'actif'], ['reactive', { resultat: 'ok', message: '' }, 'suspendu']]) {
  document.body.children.length = 0; appels = []; reponses.length = 0;
  const etat = jeux[depart];
  const promesse = clic(depart === 'suspendu' ? sous(vue.encadreMode(etat, () => {})).find((n) => n.classes.includes('action')) : vue.interrupteurMode(etat))[0];
  reponses[0](reponse);
  await promesse;
  actions[nom] = { appels: appels.map((x) => [x[0], x[1], x[2].cible]), demande: commun.modeDemande(), toasts: toasts() };
  commun.rendreSocle({ etat: jeux[depart === 'actif' ? 'inactif' : 'actif'], page: 'scene', journal: [], route: {}, source }); // met fin à l'attente d'un ok
}
{
  commun.rendreSocle({ etat: jeux['inactif'], page: 'scene', journal: [], route: {}, source });
  document.body.children.length = 0; appels = [];
  commun.definirActionsFigees(true);
  const fige = vue.interrupteurMode(etatInactif);
  await clic(fige)[0];
  actions.fige = { appels: appels.length, disabled: 'disabled' in fige.attrs, title: fige.attrs.title ?? null, reactiver: sous(vue.encadreMode(jeux['suspendu'], () => {})).filter((n) => n.classes.includes('action')).map((b) => 'disabled' in b.attrs) };
  commun.definirActionsFigees(false);
}
sortie_.actions = actions;

// 7. chaque vue se rend sans erreur dans chaque état du mode autonome
const vues = {};
for (const nom of ['ensemble', 'equipe', 'fil', 'journal', 'archives']) {
  const mod = await import(`${racine}/vues/${nom}.js`);
  for (const [etatNom, etat] of Object.entries(jeux)) {
    const c = new Elt('main');
    try {
      mod.rendre({ etat, contenu: c, route: { page: nom, nom: 'hote', params: new URLSearchParams('') }, horloge: { maintenant: () => Date.parse(etat.genere_a) },
        journal: [{ id: 1, horodatage: etat.genere_a, auteur: 'utilisateur', action: 'fusions_auto', cible: 'projet', details: { valeur: 'active' }, resultat: 'ok' }],
        tic() {}, source: { terminal: async () => null, agentsAvecTerminal: () => [] }, rerendre() {} });
      vues[`${nom}|${etatNom}`] = c.children.length > 0 ? 'ok' : 'vide';
    } catch (e) { vues[`${nom}|${etatNom}`] = `${e.name}: ${e.message}`; }
  }
}
sortie_.vues = vues;
sortie(sortie_);
"""


def _exemple():
    return json.loads(EXEMPLE_ETAT.read_text(encoding="utf-8"))


def _jeux_rendu():
    base = _exemple()
    proposees = base["fusions_auto"]["reserves_proposees"]
    depuis = "2026-10-06T21:10:00.000Z"  # 23 h 10 à Paris, en été
    derniere = {"equipe": "page", "sha": "f223c94abcdef", "horodatage": "2026-10-07T12:52:11.123Z"}  # 12 min avant genere_a

    def variante(champ):
        v = json.loads(json.dumps(base))
        if champ is None:
            v.pop("fusions_auto")
        else:
            v["fusions_auto"] = champ
        return v

    return {
        "inactif": variante(base["fusions_auto"]),
        "inactif sans liste": variante({k: x for k, x in base["fusions_auto"].items() if k != "reserves_proposees"}),
        "actif": variante({"active": True, "suspendue": False, "depuis": depuis, "par": "utilisateur", "reserves": proposees, "reserves_proposees": proposees, "derniere_fusion": derniere}),
        "actif propres": variante({"active": True, "suspendue": False, "depuis": depuis, "par": "utilisateur", "derniere_fusion": derniere,
                                   "reserves": proposees + ["src/cime/scene/", "src/cime/page/x.py"], "reserves_proposees": proposees}),
        "actif sans derniere": variante({"active": True, "suspendue": False, "depuis": depuis, "par": "assistant", "reserves": proposees, "reserves_proposees": proposees, "derniere_fusion": None}),
        "actif sans liste": variante({"active": True, "suspendue": False, "depuis": depuis, "par": "utilisateur", "reserves": [], "derniere_fusion": derniere}),
        "suspendu": variante({"active": True, "suspendue": True, "depuis": depuis, "par": "utilisateur", "reserves": proposees[1:], "reserves_proposees": proposees, "derniere_fusion": None}),
        "suspendu sans liste": variante({"active": True, "suspendue": True, "depuis": depuis, "par": "utilisateur", "reserves": proposees[1:], "derniere_fusion": None}),
        "absent": variante(None),
    }


def _lancer_sonde(dossier_static, sonde, arguments):
    fichier = dossier_static / "sonde-mode.mjs"
    fichier.write_text(sonde, encoding="utf-8")
    res = subprocess.run(["node", str(fichier), *[str(x) for x in arguments]], capture_output=True, text=True, timeout=120, env={**os.environ, "TZ": "Europe/Paris"})
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


def _ecrire_jeux(dossier_static):
    chemin = dossier_static / "jeux-mode.json"
    chemin.write_text(json.dumps(_jeux_rendu()), encoding="utf-8")
    return chemin


def _textes(etat):
    return etat["encadre"]["texte"]


def verifier_rendu(static):
    r = _lancer_sonde(static, SONDE_RENDU, [static, _ecrire_jeux(static)])
    e = r["etats"]

    # 1. inactif : interrupteur gris, libellé écrit, phrase discrète et liste visible avant l'activation
    i = e["inactif"]
    assert i["inter"]["tag"] == "button" and i["inter"]["attrs"]["role"] == "switch" and i["inter"]["attrs"]["aria-checked"] == "false"
    assert i["inter"]["texte"] == "Mode autonome" and i["inter"]["classes"] == ["inter"] and i["inter"]["attrs"]["type"] == "button"
    assert "disabled" not in i["inter"]["attrs"] and "aria-busy" not in i["inter"]["attrs"] and len(i["piste"]) == 1 and i["piste"][0]["attrs"]["aria-hidden"] == "true"
    assert i["encadre"]["classes"] == ["etat-auto", "inactif"] and i["encadre"]["texte"].startswith(INACTIF_ATTENDU)
    assert i["encadre"]["details"] == [{"ouvert": False, "resume": "Voir la liste · 43 chemins"}]
    assert [t[0] for t in i["encadre"]["themes"]] == ["Architecture et contrats · 9", "Fondation : registre, garde, hooks · 2", "Droits · 1", "Réseau et dépendances · 14", "Secrets · 8", "Propres à projet-boutique · 9",
                                                      "Toujours, hors chemins"]
    assert i["encadre"]["themes"][-1][1] == "push, suppression de branche"
    assert i["encadre"]["id"] is None
    # sans la liste proposée (un hôte plus ancien) : les thèmes du noyau seulement, « + les chemins propres au projet », aucun nombre
    s = e["inactif sans liste"]["encadre"]
    assert s["texte"] == "Activé, l’Assistant fusionne à ta place. " + REPLI and s["details"] == [] and not re.search(r"\d", s["texte"])
    # le champ absent : inactif, comme l'hôte qui ne le sert pas
    assert e["absent"]["inter"]["attrs"]["aria-checked"] == "false" and e["absent"]["encadre"]["texte"] == s["texte"]

    # 2. actif : bleu, « L'Assistant fusionne à ta place depuis 23 h 10 · dernière : page f223c94, il y a 12 min », la ligne repliée avec le nombre de chemins
    a_ = e["actif"]
    assert a_["inter"]["attrs"]["aria-checked"] == "true" and a_["inter"]["classes"] == ["inter"] and "aria-describedby" not in a_["inter"]["attrs"]
    assert a_["encadre"]["classes"] == ["etat-auto", "actif"] and a_["encadre"]["gras"] == ["L’Assistant fusionne à ta place"]
    assert a_["encadre"]["texte"].startswith("L’Assistant fusionne à ta place depuis 23 h 10 · dernière : page f223c94, il y a 12 min")
    assert a_["encadre"]["mono"] == ["f223c94"] and a_["encadre"]["temps"] == [["2026-10-07T12:52:11.123Z", "il y a 12 min"]]  # seul le sha est en mono, l'âge vit
    assert a_["encadre"]["details"] == [{"ouvert": False, "resume": "Restent à toi : architecture, fondation, droits, réseau, secrets, propres à projet-boutique · 43 chemins"}]
    assert "par utilisateur" not in a_["encadre"]["texte"] and a_["encadre"]["id"] == "encadre-mode"
    # « par » seulement s'il ≠ utilisateur ; sans dernière action : « aucune fusion encore »
    n = e["actif sans derniere"]["encadre"]["texte"]
    assert n.startswith("L’Assistant fusionne à ta place depuis 23 h 10 par assistant · aucune fusion encore") and "dernière" not in n
    # liste enregistrée vide (mode actif d'un hôte ancien) : les thèmes du noyau, sans nombre
    v = e["actif sans liste"]["encadre"]
    assert v["details"] == [{"ouvert": False, "resume": REPLI}], v["details"]
    assert all(t[1] is None for t in v["themes"][:-1]) and v["themes"][-1][0] == "Toujours, hors chemins" and v["chemins"] == 0

    # 3. suspendu : ambre, l'interrupteur reste en position actif avec le même libellé, l'explication, la liste actuelle, « Réactiver avec cette liste »
    d = e["suspendu"]
    assert d["inter"]["classes"] == ["inter", "suspendu"] and d["inter"]["attrs"]["aria-checked"] == "true" and d["inter"]["texte"] == "Mode autonome"
    assert d["inter"]["attrs"]["aria-describedby"] == d["encadre"]["id"] == "encadre-mode"
    assert d["encadre"]["classes"] == ["etat-auto", "suspendu"]
    assert d["encadre"]["texte"].startswith("Suspendu, fusions arrêtées : la liste des chemins réservés a changé depuis ton activation (23 h 10). Chaque fusion revient à ton accord.")
    assert d["encadre"]["details"] == [{"ouvert": False, "resume": "Voir la liste actuelle · 43 chemins"}]
    assert [b for b in d["encadre"]["boutons"] if "action" in b["classes"]] == [{"texte": "Réactiver avec cette liste", "classes": ["action"], "disabled": False, "busy": None}]
    assert e["suspendu sans liste"]["encadre"]["details"][0]["resume"] == "Voir la liste actuelle" and "43" not in e["suspendu sans liste"]["encadre"]["texte"]

    # les chemins propres au projet qui ne relèvent pas de la fondation : un thème « Propres à <projet> », en dernier, avec son compte
    pr = e["actif propres"]["encadre"]
    assert pr["details"][0]["resume"] == "Restent à toi : architecture, fondation, droits, réseau, secrets, propres à projet-boutique · 45 chemins", pr["details"]
    assert [t[0] for t in pr["themes"]][-2:] == ["Propres à projet-boutique · 11", "Toujours, hors chemins"]
    assert pr["themes"][-2][1] == "src/cime/fondation/ · src/cime/signaux/ · src/cime/gabarits/ · src/cime/hote/actions_*.py · src/cime/hote/gardes.py · …", pr["themes"][-2][1]

    # 4. les réserves dépliées : un titre et son compte par thème, au plus 5 chemins, « … » au-delà ; jamais un chemin coupé
    th = a_["encadre"]["themes"]
    assert th[0][1].endswith("· …") and th[0][1].count(" · ") == 5 and th[1][1] == ".orga/etat/ · .claude/" and th[2][1] == ".orga/etat/reglages/" and th[3][1].endswith("· …")
    assert th[4][1].endswith("· …") and th[5][1].endswith("· …")
    assert a_["encadre"]["chemins"] == 5 + 2 + 1 + 5 + 5 + 5

    # 5. les replis choisis par l'utilisateur survivent au redessin ; « … » montre tout et redessine ; « replier » le rend
    p = r["replis"]
    assert p["ouvert"] is True and p["avant"] == 5 and p["suite"] == [["…", "Voir les 9 chemins"]] and p["redessine"] == 1 and p["apres"] == 9 and p["replier"] == ["replier ▴"] and p["droits"] == 0
    assert r["apresReinit"] is False

    # 6. l'en-tête : la pastille seulement quand actif (bleu) ou suspendu (ambre), juste avant le compteur d'attentes ; un clic mène à la scène
    h = r["entetes"]
    for nom in ("inactif", "inactif sans liste", "absent"):
        assert h[nom]["pastille"] == [], nom
    for nom in ("actif", "actif sans derniere", "actif sans liste"):
        pa = h[nom]["pastille"]
        assert len(pa) == 1 and pa[0]["classes"] == ["pastille-auto", "actif"] and pa[0]["longue"] == "Autonome" and pa[0]["courte"] == "Auto" and pa[0]["href"] == "#/"
        assert pa[0]["title"] == "Mode autonome : l’Assistant fusionne à ta place depuis 23 h 10"
    for nom in ("suspendu", "suspendu sans liste"):
        pa = h[nom]["pastille"]
        assert len(pa) == 1 and pa[0]["classes"] == ["pastille-auto", "suspendu"] and pa[0]["longue"] == "Autonome suspendu" and pa[0]["courte"] == "Suspendu" and pa[0]["href"] == "#/"
        assert pa[0]["title"].startswith("Mode autonome suspendu : la liste des chemins réservés a changé")
    ordre = h["actif"]["ordre"]

    def rang(mot, liste):
        return next(i for i, c in enumerate(liste) if mot in c.split())
    assert rang("pastille-auto", ordre) == rang("compteur-attentes", ordre) - 1 and rang("pastille-auto", ordre) > rang("age-donnee", ordre), ordre  # juste avant le compteur
    assert not any("pastille-auto" in c for c in h["inactif"]["ordre"])

    # 7. le rail : l'interrupteur à droite de « Ce qui t'attend », dessiné aussi quand rien n'attend ou quand c'est inconnu ; au téléphone, dans le tiroir quand rien n'attend
    rails = r["rails"]
    for cas in ("attentes", "rien", "inconnu"):
        b = rails[f"{cas}|bureau"]
        assert b["blocs"][0] == "Ce qui t’attend" and b["inters"] == 1 and b["tete"] == [["h2.", "button.inter"]], (cas, b)
        assert b["encadres"] == 1  # l'encadré, sous la ligne de titre
        assert b["ordre"][0] == "rail-tete" and b["ordre"][1] == "etat-auto", (cas, b["ordre"])
    assert rails["rien|bureau"]["aSousTitre"] == 1 and rails["inconnu|bureau"]["inconnuBloc"] == 1 and rails["attentes|bureau"]["cartes"] > 0
    assert rails["attentes|bureau"]["titre"].startswith("Ce qui t’attend") and "Mode autonome" not in rails["attentes|bureau"]["titre"]  # le titre n'est pas pollué par l'interrupteur
    t = rails["rien|telephone"]
    assert t["blocs"][0] == "Mode autonome" and t["inters"] == 1 and t["tete"] == [["button.inter"]] and t["encadres"] == 1, t  # en première ligne du tiroir
    for cas in ("attentes", "inconnu"):
        assert rails[f"{cas}|telephone"]["inters"] == 0 and rails[f"{cas}|telephone"]["blocs"][0] != "Mode autonome", cas  # il est dans la feuille

    # 8. la feuille du téléphone : la tête est le titre et « Fermer », jamais l'interrupteur ; il est la première ligne du contenu (puis les effectifs,
    # puis l'encadré) quand des attentes ; rien n'attend : pas d'interrupteur dans la feuille (il est dans le tiroir) ; le contenu vit
    f = r["feuilles"]
    for cas in ("attentes", "rien", "inconnu"):
        assert f[cas]["tete"] == ["h2", "bouton"] and f[cas]["intersDansTete"] == 0, (cas, f[cas])
    assert f["attentes"]["contenu"][:3] == ["feuille-mode", "feuille-effectifs", "etat-auto"], f["attentes"]
    assert f["attentes"]["mode"] == [[["button", "switch"]]] and f["attentes"]["encadres"] == 1 and f["attentes"]["inters"] == 1
    assert f["attentes"]["apres"] == 0  # plus aucune attente : l'interrupteur passe au tiroir, un seul emplacement à la fois
    assert f["rien"]["mode"] == [] and f["rien"]["encadres"] == 0 and f["rien"]["inters"] == 0 and f["rien"]["apres"] == 1
    assert f["rien"]["contenu"][0] == "feuille-effectifs", f["rien"]
    assert f["inconnu"]["contenu"][:3] == ["feuille-mode", "feuille-effectifs", "etat-auto"] and f["inconnu"]["inters"] == 1 and f["inconnu"]["encadres"] == 1

    # 9. l'action
    x = r["actions"]
    assert x["pendant"]["appels"] == 1 and x["pendant"]["appel"] == ["fusions_auto", {"valeur": "active"}, {"cible": "projet", "details": {"valeur": "active"}}]  # un seul envoi malgré le second clic
    assert x["pendant"]["demande"] == "active" and x["pendant"]["rendus"] >= 1
    pe = x["pendant"]["resume"]
    assert pe["texte"] == "Activation…" and pe["attrs"]["aria-busy"] == "true" and "disabled" in pe["attrs"]
    assert x["pendant"]["reactiver"] == [["Activation…", True, "true"]]
    assert x["apres_ok"]["toasts"] == [["toast", "Mode autonome activé : l’Assistant fusionne à ta place, hors chemins réservés."]] and x["apres_ok"]["appels"] == 1
    assert x["apres_ok"]["demande"] == "active"  # l'interrupteur attend l'instantané qui montre le réglage
    assert x["apres_ok"]["interrupteur"]["texte"] == "Activation…" and x["encore_inactif"] == "active" and x["atteint"] is None
    assert x["refus"]["toasts"] == [["toast toast-ambre", "Refusé : déjà actif."]] and x["refus"]["demande"] is None  # la raison de l'hôte, l'interrupteur revient
    assert x["erreur"]["toasts"] == [["toast toast-rouge", "Échec : hôte injoignable (réseau). Rien n’a changé, tu peux réessayer."]] and x["erreur"]["demande"] is None
    assert x["desactive"]["appels"] == [["fusions_auto", {"valeur": "inactive"}, "projet"]]
    assert x["desactive"]["toasts"] == [["toast", "Mode autonome désactivé : chaque fusion revient à ton accord."]]
    assert x["reactive"]["appels"] == [["fusions_auto", {"valeur": "active"}, "projet"]]  # « Réactiver » envoie simplement active, en un seul appel
    assert x["reactive"]["toasts"] == [["toast", "Mode autonome activé : l’Assistant fusionne à ta place, hors chemins réservés."]]
    assert x["fige"]["appels"] == 0 and x["fige"]["disabled"] is True and x["fige"]["title"] == "L’hôte ne répond plus" and x["fige"]["reactiver"] == [True]

    # 9 bis. le focus : retrouvé tout de suite après un refus ; après un ok, quand l'instantané met fin à l'attente ; jamais volé
    assert r["focus"] == {"refus": [1, 1], "ok": [0, 1], "ok, focus ailleurs": [0, 0], "ok, à la souris": [0, 0]}, r["focus"]

    # 10. chaque vue se rend sans erreur, dans chaque état
    assert len(r["vues"]) == 5 * len(e) and all(v == "ok" for v in r["vues"].values()), {k: v for k, v in r["vues"].items() if v != "ok"}


@pytest.fixture
def copie_static(tmp_path):
    cible = tmp_path / "static"
    shutil.copytree(STATIC, cible, ignore=shutil.ignore_patterns("__pycache__"))
    return cible


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node n'est pas installé : le rendu du mode autonome n'est pas exécuté")


@needs_node
def test_fonctions_executees(copie_static):
    verifier_fonctions(copie_static, EXEMPLE_ETAT)


@needs_node
def test_rendu_execute(copie_static):
    verifier_rendu(copie_static)


# mutations qui ne se voient qu'à l'exécution : (fichier, ancien, nouveau, vérification qui doit échouer)
def _f(static):
    verifier_fonctions(static, EXEMPLE_ETAT)


MUTATIONS_EXECUTEES = {
    # les fonctions pures
    "suspendu sans actif": (AU, "etat: !actif ? 'inactif' : lecture.suspendue === true ? 'suspendu' : 'actif'", "etat: lecture.suspendue === true ? 'suspendu' : actif ? 'actif' : 'inactif'", _f),
    "actif lu comme truthy": (AU, "const actif = lecture.active === true;", "const actif = Boolean(lecture.active);", _f),
    "suspendu jamais": (AU, "lecture.suspendue === true ? 'suspendu'", "false ? 'suspendu'", _f),
    "champ absent plante": (AU, "const f = etat && typeof etat === 'object' ? etat.fusions_auto : null;", "const f = etat.fusions_auto;", _f),
    "liste inactive : l'enregistrée": (AU, "const choix = mode.etat === 'actif' ? mode.reserves : mode.proposees;", "const choix = mode.reserves;", _f),
    "liste active : la proposée": (AU, "const choix = mode.etat === 'actif' ? mode.reserves : mode.proposees;", "const choix = mode.proposees;", _f),
    "liste vide acceptée": (AU, "return choix && choix.length ? [...new Set(choix)] : null;", "return choix ? [...new Set(choix)] : null;", _f),
    "doublons gardés": (AU, "return choix && choix.length ? [...new Set(choix)] : null;", "return choix && choix.length ? choix : null;", _f),
    "chemins illisibles gardés": (AU, "filter((c) => typeof c === 'string' && c)", "filter(() => true)", _f),
    "droits classés en fondation": (AU, "motifs: [/^\\.orga\\/etat\\/?$/, /^\\.claude\\/?$/],", "motifs: [/^\\.orga\\/etat\\//, /^\\.claude\\/?$/],", _f),
    "motif d'un dossier du projet remis": (AU, "motifs: [/^\\.orga\\/etat\\/?$/, /^\\.claude\\/?$/],", "motifs: [/^\\.orga\\/etat\\/?$/, /^\\.claude\\/?$/, /^(src\\/cime|tests)\\/(fondation|signaux|gabarits|hote)(\\/|$)/],", _f),
    "secrets en joker non reconnus": (AU, "\\.env|\\.env\\.\\*|", "\\.env|", _f),
    "mandats d'équipe non reconnus": (AU, "/^\\.orga\\/teams\\/(\\*|[^/]+)\\/(CLAUDE|mandate)\\.md$/", "/^\\.orga\\/teams\\/zz$/", _f),
    "réseau incomplet": (AU, "|go\\.mod|go\\.sum)$/,", ")$/,", _f),
    "ordre des thèmes": (AU, "{ cle: 'droits', titre: 'Droits', court: 'droits', phrase: 'droits', motifs: [/^\\.orga\\/etat\\/reglages\\/?$/] },\n", "", _f),
    "thème inconnu perdu": (AU, "return theme ? theme.cle : 'projet';", "return theme ? theme.cle : 'secrets';", _f),
    "chemins propres sans classement": (AU, "const groupe = groupes.find((g) => g.cle === themeDe(c));", "const groupe = groupes[0];", _f),
    "thèmes vides gardés": (AU, "return groupes.filter((g) => g.chemins.length > 0);", "return groupes;", _f),
    "liste inconnue sans noyau": (AU, "if (chemins === null) return THEMES.map((t) => ({ cle: t.cle, titre: t.titre, court: t.court, chemins: null }));", "if (chemins === null) return [];", _f),
    "plafond de 3": (AU, "MAX_CHEMINS_PAR_THEME = 5", "MAX_CHEMINS_PAR_THEME = 3", _f),
    "plafond ignoré": (AU, "const abrege = !tout && chemins.length > MAX_CHEMINS_PAR_THEME;", "const abrege = chemins.length > MAX_CHEMINS_PAR_THEME;", _f),
    "reste mal compté": (AU, "reste: abrege ? chemins.length - MAX_CHEMINS_PAR_THEME : 0", "reste: abrege ? chemins.length : 0", _f),
    "pluriel du compte": (AU, "${total === 1 ? 'chemin' : 'chemins'}", "chemins", _f),
    "ligne sans nombre": (AU, "return `Restent à toi : ${mots} · ${total} ${total === 1 ? 'chemin' : 'chemins'}`;", "return `Restent à toi : ${mots}`;", _f),
    "ligne inconnue avec un nombre": (AU, "if (total === null) return phraseRepli();", "if (total === null) return `Restent à toi : ${mots} · 0 chemin`;", _f),
    "heure sans minutes zéro": (AU, "String(m).padStart(2, '0')", "m", _f),
    "heure sans h": (AU, "`${d.getHours()} h ${String(m).padStart(2, '0')}`", "`${d.getHours()}:${String(m).padStart(2, '0')}`", _f),
    "heure illisible acceptée": (AU, "if (!iso || Number.isNaN(d.getTime())) return null;", "", _f),
    "sha entier": (AU, "sha: typeof d.sha === 'string' ? d.sha.slice(0, 7) : null", "sha: typeof d.sha === 'string' ? d.sha : null", _f),
    "par utilisateur affiché": (AU, "(mode.par && mode.par !== 'utilisateur' ? mode.par : null)", "(mode.par ? mode.par : null)", _f),
    "valeur après clic inversée": (AU, "mode.etat === 'inactif' ? 'active' : 'inactive'", "mode.etat === 'inactif' ? 'inactive' : 'active'", _f),
    "info-bulle suspendue sans heure": (AU, "${depuis ? ` depuis ton activation (${depuis})` : ''}", "", _f),
    # le rendu
    "inactif sans la phrase": (MO, "el('p', {}, phraseInactif(connue)),", "el('p', {}, null),", verifier_rendu),
    "liste inactive repliée absente": (MO, "      connue ? detailsReserves(etat, mode, (g, c) => `Voir la liste", "      false ? detailsReserves(etat, mode, (g, c) => `Voir la liste", verifier_rendu),
    "heure de l'activation perdue": (MO, "const depuisPar = (mode) => [mode.depuis && heureCourte(mode.depuis) ? ` depuis ${heureCourte(mode.depuis)}` : null,", "const depuisPar = (mode) => [null,", verifier_rendu),
    "âge de la dernière action perdu": (MO, "d.horodatage ? [', ', ageEcrit(d.horodatage, maintenant)] : null]", "null]", verifier_rendu),
    "âge mal calculé": (MO, "const maintenant = Date.parse(etat.genere_a) + (Number(etat.age_ms) || 0);", "const maintenant = Date.parse(etat.genere_a) + 3600000;", verifier_rendu),
    "sha non mono": (MO, "d.sha ? mono(d.sha) : null", "d.sha", verifier_rendu),
    "équipe de la dernière action perdue": (MO, "return [' · dernière : ', d.equipe, d.equipe && d.sha ? ' ' : null,", "return [' · dernière : ', null, null,", verifier_rendu),
    "encadré actif sans id": (MO, "class: 'etat-auto actif', id: 'encadre-mode' }", "class: 'etat-auto actif' }", verifier_rendu),
    "encadré suspendu sans id": (MO, "class: 'etat-auto suspendu', id: 'encadre-mode' }", "class: 'etat-auto suspendu' }", verifier_rendu),
    "bouton Réactiver désactivé à tort": (MO, "disabled: Boolean(demande) || actionsSontFigees(),", "disabled: true,", verifier_rendu),
    "bouton Réactiver actif pendant la requête": (MO, "disabled: Boolean(demande) || actionsSontFigees(),", "disabled: actionsSontFigees(),", verifier_rendu),
    "bouton Réactiver sans libellé de requête": (MO, "demande ? LIBELLE_ENCOURS[demande] : 'Réactiver avec cette liste'", "'Réactiver avec cette liste'", verifier_rendu),
    "bouton Réactiver qui désactive": (MO, "onclick: () => basculerMode('active') }, demande", "onclick: () => basculerMode('inactive') }, demande", verifier_rendu),
    "repli oublié": (MO, "ontoggle: (ev) => { listeDepliee = ev.target.open; }", "ontoggle: () => {}", verifier_rendu),
    "« … » sans redessin": (MO, "    if (voir) themesEnEntier.add(groupe.cle); else themesEnEntier.delete(groupe.cle);\n    redessiner();", "    if (voir) themesEnEntier.add(groupe.cle); else themesEnEntier.delete(groupe.cle);", verifier_rendu),
    "« … » sans effet": (MO, "if (voir) themesEnEntier.add(groupe.cle); else", "if (false) themesEnEntier.add(groupe.cle); else", verifier_rendu),
    "tout sans « replier »": (MO, "tout && groupe.chemins.length > MAX_CHEMINS_PAR_THEME", "false", verifier_rendu),
    "nom du projet perdu": (MO, "regrouperReserves(chemins, etat.projet ? etat.projet.nom : null)", "regrouperReserves(chemins, null)", verifier_rendu),
    "interrupteur sans piste": (MO, ", el('span', { class: 'piste', 'aria-hidden': 'true' }));\n}", ");\n}", verifier_rendu),
    "piste lue par les lecteurs d'écran": (MO, "el('span', { class: 'piste', 'aria-hidden': 'true' })", "el('span', { class: 'piste' })", verifier_rendu),
    "interrupteur sans type": (MO, "type: 'button', role: 'switch',", "role: 'switch',", verifier_rendu),
    "suspendu non décrit": (MO, "'aria-describedby': suspendu ? 'encadre-mode' : null,", "", verifier_rendu),
    "interrupteur en cours sans libellé": (MO, "demande ? LIBELLE_ENCOURS[demande] : LIBELLE_MODE, el('span'", "LIBELLE_MODE, el('span'", verifier_rendu),
    "interrupteur sans aria-busy": (MO, "'aria-busy': demande ? 'true' : null,\n    'aria-describedby'", "'aria-describedby'", verifier_rendu),
    "interrupteur jamais désactivé": (MO, "disabled: Boolean(demande) || fige,", "disabled: false,", verifier_rendu),
    "figé sans info-bulle": (MO, "title: fige ? PHRASE_ACTIONS_FIGEES : suspendu", "title: suspendu", verifier_rendu),
    "pastille aussi inactif": (COM, "if (mode.etat === 'inactif') return null;\n  const mots = PASTILLE[mode.etat];", "const mots = PASTILLE[mode.etat] || PASTILLE.actif;", verifier_rendu),
    "pastille sans classe d'état": (COM, "class: `pastille-auto ${mode.etat}`", "class: 'pastille-auto'", verifier_rendu),
    "pastille sans lien": (COM, "class: `pastille-auto ${mode.etat}`, href: '#/',", "class: `pastille-auto ${mode.etat}`,", verifier_rendu),
    "pastille sans forme longue": (COM, "el('span', { class: 'pastille-long' }, mots.long), ", "", verifier_rendu),
    "pastille sans forme courte": (COM, ", el('span', { class: 'pastille-court' }, mots.court)", "", verifier_rendu),
    "pastille après le compteur": (COM, "      pastilleAutonome(ctx.etat),\n      compteurAttentes(ctx.etat),", "      compteurAttentes(ctx.etat),\n      pastilleAutonome(ctx.etat),", verifier_rendu),
    "pastille avant la pastille d'âge": (COM, "      pastilleAutonome(ctx.etat),\n      compteurAttentes(ctx.etat),", "      compteurAttentes(ctx.etat),", verifier_rendu),
    "rail sans l'interrupteur (des attentes)": (RA, "  ], classe, mode);", "  ], classe);", verifier_rendu),
    "rail sans l'interrupteur (rien)": (RA, "'✓ Rien ne t’attend. Tout avance sans toi.')], classe, mode);", "'✓ Rien ne t’attend. Tout avance sans toi.')], classe);", verifier_rendu),
    "rail sans l'interrupteur (inconnu)": (RA, "'Ce qui t’attend : inconnu (sources en échec).')], classe, mode);", "'Ce qui t’attend : inconnu (sources en échec).')], classe);", verifier_rendu),
    "rail sans encadré": (RA, "    encadre,\n    el('div', { class: 'attentes' }", "    el('div', { class: 'attentes' }", verifier_rendu),
    "interrupteur sous le titre": (RA, "droite ? el('div', { class: 'rail-tete' }, intitule, droite) : intitule,", "[intitule, droite],", verifier_rendu),
    "tiroir sans le mode": (RA, "rienNAttend ? blocTiroirMode(etat, redessiner) : null", "null", verifier_rendu),
    "tiroir avec le mode malgré les attentes": (RA, "rienNAttend ? blocTiroirMode(etat, redessiner) : null", "blocTiroirMode(etat, redessiner)", verifier_rendu),
    "tiroir sans encadré": (MO, "el('div', { class: 'rail-tete' }, interrupteurMode(etat)), encadreMode(etat, redessiner));", "el('div', { class: 'rail-tete' }, interrupteurMode(etat)));", verifier_rendu),
    "feuille sans le mode": (MOB, "modeDansLaFeuille(etat) ? el('div', { class: 'feuille-mode' }, interrupteurMode(etat)) : null, // première ligne : la tête reste titre + « Fermer »\n", "", verifier_rendu),
    "interrupteur après les effectifs de la feuille": (MOB, "    modeDansLaFeuille(etat) ? el('div', { class: 'feuille-mode' }, interrupteurMode(etat)) : null, // première ligne : la tête reste titre + « Fermer »\n    el('div', { class: 'feuille-effectifs' }, resumeAgents(etat)),\n", "    el('div', { class: 'feuille-effectifs' }, resumeAgents(etat)),\n    modeDansLaFeuille(etat) ? el('div', { class: 'feuille-mode' }, interrupteurMode(etat)) : null,\n", verifier_rendu),
    "feuille avec le mode sans attente": (MOB, "return a === null || a.length > 0; };", "return true; };", verifier_rendu),
    "contenu de la feuille figé": (MOB, "    ouverte.feuille.remplacer(...contenuAttentes(etat));\n", "", verifier_rendu),
    "tête de la feuille avec un intrus": (COM, "el('header', { class: 'feuille-tete' }, intitule,\n", "el('header', { class: 'feuille-tete' }, intitule, el('span', { class: 'intrus' }),\n", verifier_rendu),
    "action sans clic": (COM, "if (modeEnCours || actionsFigees) return;\n  const demande", "return;\n  const demande", verifier_rendu),
    "double envoi": (COM, "if (modeEnCours || actionsFigees) return;", "if (actionsFigees) return;", verifier_rendu),
    "figé : l'action part": (COM, "if (modeEnCours || actionsFigees) return;", "if (modeEnCours) return;", verifier_rendu),
    "route de l'action changée": (COM, "source.agir('fusions_auto', { valeur }", "source.agir('autoriser', { valeur }", verifier_rendu),
    "cible du journal changée": (COM, "{ cible: 'projet', details: { valeur } }", "{ cible: 'equipe', details: { valeur } }", verifier_rendu),
    "valeur de l'action changée": (COM, "{ valeur }, { cible: 'projet'", "{ valeur: 'active' }, { cible: 'projet'", verifier_rendu),
    "focus perdu après un refus": (COM, "  rerendre();\n  retrouverFocusMode();\n}", "  rerendre();\n}", verifier_rendu),
    "focus jamais rendu après l'attente (rendu)": (COM, "      requestAnimationFrame(retrouverFocusMode); // après le dessin de la page\n", "", verifier_rendu),
    "focus volé (rendu)": (COM, "  if (actif && actif !== document.body && !(actif.classList && actif.classList.contains('inter'))) return;\n", "", verifier_rendu),
    "focus rendu sans l'avoir eu": (COM, "    focusAMode = avaitLeFocus;\n", "    focusAMode = true;\n", verifier_rendu),
    "toast d'activation absent": (COM, "annoncer(TOASTS[valeur]);", "", verifier_rendu),
    "toast de refus sans la raison": (COM, "annoncer(phraseEchec(reponse), reponse.resultat === 'refuse' ? 'ambre' : 'rouge');", "annoncer('Refusé', 'ambre');", verifier_rendu),
    "refus en rouge": (COM, "reponse.resultat === 'refuse' ? 'ambre' : 'rouge');", "'rouge');", verifier_rendu),
    "refus : l'interrupteur reste occupé": (COM, "    modeEnCours = null;\n    annoncer(phraseEchec", "    annoncer(phraseEchec", verifier_rendu),
    "ok : plus d'attente de l'instantané": (COM, "    demande.requete = false; // l'interrupteur attend l'instantané qui montre le réglage\n", "    modeEnCours = null;\n", verifier_rendu),
    "instantané sans effet": (COM, "  rapprocherMode(ctx.etat);\n", "", verifier_rendu),
    "instantané qui ne montre pas le réglage met fin à l'attente": (COM, "if (modeEnCours && !modeEnCours.requete && modeAtteint(modeEnCours.valeur, etat)) {", "if (modeEnCours && !modeEnCours.requete) {", verifier_rendu),
    "réglage atteint mal lu": (COM, "lireMode(etat).etat === (valeur === 'active' ? 'actif' : 'inactif')", "lireMode(etat).etat !== 'inactif'", verifier_rendu),
    "vue qui plante sans le champ": (AU, "const f = etat && typeof etat === 'object' ? etat.fusions_auto : null;", "const f = etat.fusions_auto; f.active;", verifier_rendu),
}


@needs_node
@pytest.mark.parametrize("nom", MUTATIONS_EXECUTEES)
def test_mutation_executee_detectee(nom, copie_static):
    fichier, ancien, nouveau, verification = MUTATIONS_EXECUTEES[nom]
    cible = copie_static / fichier
    texte = cible.read_text(encoding="utf-8")
    assert ancien in texte, ancien  # la mutation doit s'appliquer
    cible.write_text(texte.replace(ancien, nouveau, 1), encoding="utf-8")
    with pytest.raises((AssertionError, KeyError, StopIteration, ValueError, IndexError, TypeError)):
        verification(copie_static)


def test_couverture_des_verifications():
    toutes = {n for n, v in globals().items() if n.startswith("verifier_") and callable(v)}
    assert toutes == {"verifier_mode_autonome", "verifier_exemple", "verifier_fonctions", "verifier_rendu"} and MUTATIONS and MUTATIONS_EXECUTEES, sorted(toutes)
    assert {v[3] for v in MUTATIONS_EXECUTEES.values()} == {_f, verifier_rendu}  # chacune des vérifications exécutées a ses mutations
