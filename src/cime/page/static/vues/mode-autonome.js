// Cime — le mode autonome dans la scène : l'interrupteur (« Mode autonome »), et sous lui l'encadré qui dit l'état et ce qui reste à l'utilisateur.
// Le rail du bureau, le tiroir et la feuille « Ce qui t'attend » du téléphone dessinent les mêmes deux morceaux ; les textes et les listes
// viennent de ../autonome.js (tables de données), l'action de commun.js (`basculerMode`). Rien n'est gardé dans le DOM : seuls les
// replis choisis par l'utilisateur (la liste dépliée, un thème montré en entier) vivent ici, pour survivre au redessin du rail.

import { el, mono, age, ilYA, basculerMode, modeDemande, actionsSontFigees, PHRASE_ACTIONS_FIGEES, derniereVisite } from '../commun.js';
import {
  lireMode, listeVisible, regrouperReserves, cheminsMontres, ligneReserves, phraseInactif, heureCourte, derniereAction, parAutre,
  valeurApresClic, decisionsAVoir, resumeDecisions, DECIDE, HORS_CHEMINS, LIBELLE_MODE, LIBELLE_ENCOURS, MAX_CHEMINS_PAR_THEME, PHRASE_RECAP,
  LIBELLE_DETAIL_RECAP,
} from '../autonome.js';
import { detailDecisions, etatDecisions } from './decisions.js';
import { ligneWorkers } from './workers.js';

let listeDepliee = false; // « Restent à toi : … » est dépliée
const themesEnEntier = new Set(); // les thèmes dont l'utilisateur a demandé tous les chemins
const decisionsScene = etatDecisions(); // le détail des décisions dans la Scène : replié d'office, son propre jeu d'états (pas celui de la Supervision)

/** Remet à zéro les replis (les tests). */
export function reinitialiserReplis() {
  listeDepliee = false;
  themesEnEntier.clear();
  Object.assign(decisionsScene, etatDecisions());
}

/** « L'Assistant fusionne à ta place » : la phrase de ce que le mode fait, d'après la table DECIDE. */
const phraseDecide = () => `L’Assistant ${DECIDE.join(' et ')}`;

/** L'interrupteur : `role="switch"`, libellé à gauche de la piste, cible de 44 px, ambre quand le mode est suspendu. */
export function interrupteurMode(etat) {
  const mode = lireMode(etat);
  const demande = modeDemande();
  const fige = actionsSontFigees();
  const suspendu = mode.etat === 'suspendu';
  return el('button', {
    type: 'button', role: 'switch', class: `inter${suspendu ? ' suspendu' : ''}`,
    'aria-checked': String(mode.etat !== 'inactif'), 'aria-busy': demande ? 'true' : null,
    'aria-describedby': suspendu ? 'encadre-mode' : null,
    disabled: Boolean(demande) || fige,
    title: fige ? PHRASE_ACTIONS_FIGEES : suspendu ? 'Suspendu : la liste des chemins réservés a changé' : null,
    onclick: () => basculerMode(valeurApresClic(mode)),
  }, demande ? LIBELLE_ENCOURS[demande] : LIBELLE_MODE, el('span', { class: 'piste', 'aria-hidden': 'true' }));
}

/** Un thème : son titre et son compte, puis ses chemins en mono séparés par « · » ; un chemin ne se coupe jamais. */
function blocTheme(groupe, redessiner) {
  if (groupe.chemins === null) return el('div', { class: 'theme' }, el('h3', {}, groupe.titre));
  const tout = themesEnEntier.has(groupe.cle);
  const { montres, abrege } = cheminsMontres(groupe.chemins, tout);
  const bascule = (voir) => () => {
    if (voir) themesEnEntier.add(groupe.cle); else themesEnEntier.delete(groupe.cle);
    redessiner();
  };
  return el('div', { class: 'theme' },
    el('h3', {}, groupe.titre, el('span', {}, ` · ${groupe.chemins.length}`)),
    el('p', { class: 'chemins' },
      montres.map((c, i) => [i ? ' · ' : null, el('span', { class: 'chemin' }, c)]),
      abrege ? [' · ', el('button', { type: 'button', class: 'chemins-suite', 'aria-expanded': 'false',
        'aria-label': `Voir les ${groupe.chemins.length} chemins`, onclick: bascule(true) }, '…')] : null,
      tout && groupe.chemins.length > MAX_CHEMINS_PAR_THEME
        ? [' · ', el('button', { type: 'button', class: 'chemins-suite', 'aria-expanded': 'true', onclick: bascule(false) }, 'replier ▴')] : null));
}

/** La liste dépliable : le résumé (ligne repliée), un titre par thème, puis la ligne « hors chemins ». */
function detailsReserves(etat, mode, resume, redessiner) {
  const chemins = listeVisible(mode);
  const groupes = regrouperReserves(chemins, etat.projet ? etat.projet.nom : null);
  const corps = [groupes.map((g) => blocTheme(g, redessiner)),
    el('div', { class: 'theme' }, el('h3', {}, 'Toujours, hors chemins'), el('p', { class: 'hors-chemins' }, HORS_CHEMINS.complet))];
  return el('details', { class: 'reserves', open: listeDepliee, ontoggle: (ev) => { listeDepliee = ev.target.open; } },
    el('summary', {}, resume(groupes, chemins)), corps);
}

/** « depuis 23 h 10 », puis « par … » si ce n'est pas l'utilisateur. */
const depuisPar = (mode) => [mode.depuis && heureCourte(mode.depuis) ? ` depuis ${heureCourte(mode.depuis)}` : null, parAutre(mode) ? ` par ${parAutre(mode)}` : null];

/** Un âge qui vit (« il y a 12 min »), déjà écrit au premier dessin : le minuteur du socle le réécrit chaque seconde. */
function ageEcrit(iso, maintenant) {
  const t = age(iso);
  t.textContent = ilYA(iso, maintenant);
  return t;
}

/** « dernière : page `f223c94`, il y a 12 min », ou « aucune fusion encore ». */
function ligneDerniere(etat, mode) {
  const d = derniereAction(mode);
  if (!d) return ' · aucune fusion encore';
  const maintenant = Date.parse(etat.genere_a) + (Number(etat.age_ms) || 0);
  return [' · dernière : ', d.equipe, d.equipe && d.sha ? ' ' : null, d.sha ? mono(d.sha) : null,
    d.horodatage ? [', ', ageEcrit(d.horodatage, maintenant)] : null];
}

/**
 * Le récap du matin dans la Scène : « L'Assistant a décidé à ta place : » suivi des comptes, sous le paragraphe ; puis « Voir le détail », qui déplie
 * la liste des décisions sur place (replié d'office, même liste que la Supervision, sans changer de page). Même donnée que « Depuis ta dernière
 * visite » (même visite, même filtre, même texte). Rien s'il n'y a rien à dire.
 */
function ligneRecapScene(etat) {
  const visite = derniereVisite(etat);
  const decisions = decisionsAVoir(lireMode(etat).decisions, visite.instant, visite.memorisee);
  if (!decisions.length) return null;
  return [el('p', { class: 'recap-scene' }, el('b', {}, PHRASE_RECAP), ` : ${resumeDecisions(decisions)}`),
    detailDecisions(decisions, decisionsScene, LIBELLE_DETAIL_RECAP)];
}

/**
 * Ce qui se lit sous la ligne de titre : inactif, une ligne discrète (et la liste qu'une activation enregistrerait) ; actif, un
 * encadré bleu pâle ; suspendu, un encadré ambre avec « Réactiver avec cette liste ». `redessiner()` redessine le rail.
 */
export function encadreMode(etat, redessiner) {
  const mode = lireMode(etat);
  const connue = listeVisible(mode) !== null;
  if (mode.etat === 'inactif') {
    return el('div', { class: 'etat-auto inactif' },
      el('p', {}, phraseInactif(connue)),
      connue ? detailsReserves(etat, mode, (g, c) => `Voir la liste · ${c.length} ${c.length === 1 ? 'chemin' : 'chemins'}`, redessiner) : null);
  }
  if (mode.etat === 'actif') {
    return el('div', { class: 'etat-auto actif', id: 'encadre-mode' },
      el('p', {}, el('b', {}, phraseDecide()), depuisPar(mode), ligneDerniere(etat, mode)),
      ligneRecapScene(etat),
      detailsReserves(etat, mode, (g, c) => ligneReserves(g, c === null ? null : c.length), redessiner));
  }
  const demande = modeDemande();
  const depuis = mode.depuis ? heureCourte(mode.depuis) : null;
  return el('div', { class: 'etat-auto suspendu', id: 'encadre-mode' },
    el('p', {}, el('b', {}, 'Suspendu, fusions arrêtées :'), ' la liste des chemins réservés a changé depuis ton activation',
      depuis ? ` (${depuis})` : null, '. Chaque fusion revient à ton accord.'),
    ligneRecapScene(etat),
    detailsReserves(etat, mode, (g, c) => (c === null ? 'Voir la liste actuelle' : `Voir la liste actuelle · ${c.length} ${c.length === 1 ? 'chemin' : 'chemins'}`), redessiner),
    el('button', { type: 'button', class: 'action', 'aria-busy': demande ? 'true' : null, disabled: Boolean(demande) || actionsSontFigees(),
      onclick: () => basculerMode('active') }, demande ? LIBELLE_ENCOURS[demande] : 'Réactiver avec cette liste'));
}

/** Le bloc du tiroir du téléphone quand rien n'attend : l'interrupteur en première ligne, puis l'encadré. */
export function blocTiroirMode(etat, redessiner) {
  const bloc = el('section', { class: 'bloc-rail bloc-mode', 'aria-label': LIBELLE_MODE },
    el('div', { class: 'rail-tete' }, interrupteurMode(etat)), encadreMode(etat, redessiner));
  bloc.append(ligneWorkers(etat, redessiner));
  return bloc;
}
