// Cime — le téléphone (≤ 760 px) : ce qui remplace l'en-tête à onglets du bureau. Un bandeau d'attentes sous l'en-tête, une barre
// d'onglets fixe en bas, et la feuille des attentes (plein écran) que le bandeau et la porte de l'utilisateur ouvrent.
// Le bureau a ses onglets dans l'en-tête et le compteur d'attentes à côté : ces éléments-ci y sont dessinés mais masqués
// (le CSS les montre dans le seul bloc @media (max-width: 760px)). Rien ici ne parle à un coordinateur : les boutons des
// cartes sont ceux de la page.

import { el, icone, feuille, pluriel, attentesOuvertes, carteAttente, resumeAgents, PAGES } from '../commun.js';
import { trierAttentes } from './rail.js';
import { interrupteurMode, encadreMode } from './mode-autonome.js';

/** La largeur en deçà de laquelle l'écran est un téléphone : la même que dans style.css. */
export const POINT_DE_RUPTURE = 760;
const formatTelephone = window.matchMedia(`(max-width: ${POINT_DE_RUPTURE}px)`);
export const estTelephone = () => formatTelephone.matches;

/** Le bandeau : vert « Rien ne t'attend » sur la Scène seulement, ambre « n points t'attendent » partout, rien sinon. */
export function bandeauAttentes(ctx) {
  const attentes = attentesOuvertes(ctx.etat);
  if (attentes === null) return null; // inconnues (sources en échec) : ne rien affirmer
  const n = attentes.length;
  if (n === 0 && ctx.page !== 'scene') return null;
  const phrase = n === 0 ? '✓ Rien ne t’attend' : `${pluriel(n, 'point')} ${n === 1 ? 't’attend' : 't’attendent'}`;
  return el('button', { type: 'button', class: `bandeau-attentes ${n === 0 ? 'bandeau-calme' : 'bandeau-ambre'}`,
    'aria-haspopup': 'dialog', onclick: () => ouvrirFeuilleAttentes() },
  el('span', { class: 'bandeau-phrase' }, phrase), el('span', { class: 'bandeau-fleche', 'aria-hidden': 'true' }, '›'));
}

/** La barre du bas : Scène · Supervision · Fil (le Journal reste un lien en pied de Supervision). */
export function barreOnglets(ctx) {
  return el('nav', { class: 'barre-onglets', 'aria-label': 'Pages' },
    PAGES.map((p) => el('a', { href: p.href, 'aria-current': p.id === ctx.page ? 'page' : null }, icone(p.id), el('span', {}, p.titre))));
}

// ---------------------------------------------------------------------------
// La feuille des attentes
// ---------------------------------------------------------------------------
let ouverte = null; // { feuille } tant que la feuille des attentes est à l'écran
let dernierEtat = null; // le dernier instantané reçu : la feuille s'ouvre et se redessine d'après lui
let aFermer = []; // les rappels à appeler quand elle se ferme (la scène y retire la porte de l'utilisateur de la sélection)

/** Rien n'attend : le mode autonome est dans le tiroir sous le plateau (le rail), pas dans la feuille ; sinon il est la première ligne de la feuille. */
const modeDansLaFeuille = (etat) => { const a = attentesOuvertes(etat); return a === null || a.length > 0; };

function contenuAttentes(etat) {
  const attentes = attentesOuvertes(etat);
  return [
    modeDansLaFeuille(etat) ? el('div', { class: 'feuille-mode' }, interrupteurMode(etat)) : null, // première ligne : la tête reste titre + « Fermer »
    el('div', { class: 'feuille-effectifs' }, resumeAgents(etat)),
    modeDansLaFeuille(etat) ? encadreMode(etat, () => majFeuilleAttentes(dernierEtat)) : null,
    attentes === null
      ? el('div', { class: 'inconnu-bloc' }, 'Ce qui t’attend : inconnu (sources en échec).')
      : attentes.length
        ? el('div', { class: 'attentes' }, trierAttentes(attentes).map((a) => carteAttente(a, { etat })))
        : el('div', { class: 'rail-calme' }, '✓ Rien ne t’attend. Tout avance sans toi.'),
  ];
}

/** Ouvre la feuille des attentes (plein écran) : toutes les cartes, avec leurs boutons ; `surFermeture` y accroche un rappel. */
export function ouvrirFeuilleAttentes({ surFermeture = null } = {}) {
  if (surFermeture) aFermer = [...aFermer, surFermeture];
  if (ouverte) return;
  const etat = dernierEtat;
  if (!etat) return;
  const f = feuille('Ce qui t’attend', contenuAttentes(etat), {
    pleinEcran: true,
    surFermeture: () => {
      ouverte = null;
      const rappels = aFermer;
      aFermer = [];
      for (const r of rappels) r();
    },
  });
  ouverte = { feuille: f };
}

export function fermerFeuilleAttentes() {
  ouverte?.feuille.fermer();
}

export const feuilleAttentesOuverte = () => ouverte !== null;

/** Redessine la feuille d'après l'instantané : les cartes vivent (envoyé, retirée, boutons désactivés) sans qu'elle se ferme. */
export function majFeuilleAttentes(etat) {
  dernierEtat = etat;
  if (ouverte) {
    ouverte.feuille.remplacer(...contenuAttentes(etat));
  }
}

/** À chaque rendu de la page : pose le bandeau et la barre, et met la feuille à jour. */
export function rendreMobile(ctx) {
  const page = document.querySelector('.page');
  const entete = page.querySelector('.entete');
  const bandeau = bandeauAttentes(ctx);
  if (bandeau) entete.after(bandeau);
  page.append(barreOnglets(ctx));
  majFeuilleAttentes(ctx.etat);
}

/** `rappel()` est appelé quand l'écran passe du bureau au téléphone, ou l'inverse (rotation, fenêtre redimensionnée). */
export function surChangementDeFormat(rappel) {
  formatTelephone.addEventListener('change', rappel);
}

// Repasser au bureau ferme la feuille des attentes (le rail du bureau montre déjà ces cartes) ; naviguer aussi (un lien d'une carte).
surChangementDeFormat(() => { if (!formatTelephone.matches) fermerFeuilleAttentes(); });
addEventListener('hashchange', fermerFeuilleAttentes);
