// Cime — la liste des décisions de l'Assistant, rendue une seule fois pour la Supervision (« Depuis ta dernière visite ») et la Scène (le rail) :
// une ligne par décision, la plus récente d'abord ; au-delà de DECISIONS_VISIBLES, « … et n autres » déplie le reste sur place.
// Les replis (détail ouvert, tout montré) vivent dans un jeu d'états par vue, créé par `etatDecisions()`, pour que l'une n'ouvre pas l'autre.

import { el, vider, mono } from '../commun.js';
import { heureCourte, verbeDecision, DECISIONS_VISIBLES } from '../autonome.js';

/** Un jeu d'états pour une vue : « détail ouvert » et « tout montré », gardés d'un instantané à l'autre (jamais dans le stockage). */
export const etatDecisions = () => ({ ouvert: false, toutes: false });

/** Une ligne par décision : heure courte · verbe · clé en mono ; le n° du message n'est qu'en info-bulle. */
function ligneDecision(d) {
  return el('li', { title: d.message === null ? null : `message n° ${d.message}` },
    el('span', { class: 'decision-heure' }, heureCourte(d.horodatage)), el('span', {}, verbeDecision(d.genre)), el('span', { class: 'decision-cle' }, mono(d.cle)));
}

/**
 * La liste, sans son repli : la plus récente d'abord, 10 lignes puis « … et n autres » qui déplie le reste sur place (`vue.toutes` le retient).
 * `apres()` : ce que la vue fait après un dépliage (la Supervision remesure sa largeur).
 */
export function listeDecisions(decisions, vue, apres = () => {}) {
  const triees = [...decisions].sort((a, b) => Date.parse(b.horodatage) - Date.parse(a.horodatage));
  const reste = triees.length - DECISIONS_VISIBLES;
  const enveloppe = el('div', {});
  const montrer = (lignes) => vider(enveloppe, el('ul', { class: 'decisions-liste' }, lignes.map(ligneDecision)));
  if (reste <= 0 || vue.toutes) {
    montrer(triees);
    return enveloppe;
  }
  montrer(triees.slice(0, DECISIONS_VISIBLES));
  const autres = el('button', { type: 'button', class: 'lien-autres' }, `… et ${reste} ${reste === 1 ? 'autre' : 'autres'}`);
  autres.addEventListener('click', () => { vue.toutes = true; montrer(triees); apres(); });
  enveloppe.append(autres);
  return enveloppe;
}

/** Le détail replié : `<details class="decisions">`, son résumé (`libelle`), la liste. Le dépliage est gardé dans `vue.ouvert`. */
export function detailDecisions(decisions, vue, libelle, apres = () => {}) {
  const detail = el('details', { class: 'decisions', open: vue.ouvert }, el('summary', {}, libelle), listeDecisions(decisions, vue, apres));
  detail.addEventListener('toggle', () => { vue.ouvert = detail.open; apres(); });
  return detail;
}
