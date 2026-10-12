// Cime — équipes clôturées : mission, dates, avancement final, fichiers touchés.

import {
  el, mono, inconnu, puceStatut, dateCourte, sourceEnEchec, mesurerLargeur, routeEquipe,
} from '../commun.js';

let etat = null;

/** Les équipes n'ont pas de dates propres : on les lit dans le fil (premier et dernier échange). */
function datesDe(q) {
  if (!Array.isArray(etat.fil)) return null;
  const id = `coord-${q.nom}`;
  const instants = etat.fil.filter((m) => m.de === id || m.a === id).map((m) => Date.parse(m.horodatage));
  if (!instants.length) return null;
  return { debut: new Date(Math.min(...instants)).toISOString(), fin: new Date(Math.max(...instants)).toISOString() };
}

/**
 * Date de clôture : `cloturee_le` (écrit par l'hôte) ; à défaut,
 * le dernier échange de l'équipe, dit « vers le » ; sinon inconnue.
 */
function cloture(q, dates) {
  if (q.cloturee_le) return `Clôturée le ${dateCourte(q.cloturee_le)}`;
  if (dates) return `Clôturée vers le ${dateCourte(dates.fin)} (dernier échange)`;
  return inconnu(null, 'date de clôture inconnue');
}

function carte(q) {
  const a = q.avancement;
  const dates = datesDe(q);
  const fichiers = Array.isArray(q.fichiers_touches) ? q.fichiers_touches : null;
  return el('article', { class: 'arch-carte', dataset: { equipe: q.nom } },
    el('div', { class: 'arch-tete' },
      el('a', { class: 'arch-nom', href: routeEquipe(q.nom) }, q.nom),
      puceStatut('terminee')),
    el('p', { class: 'arch-mission' }, q.mission),
    el('div', { class: 'arch-faits' },
      el('span', {}, dates
        ? `Échanges du ${dateCourte(dates.debut)} au ${dateCourte(dates.fin)}`
        : inconnu(sourceEnEchec(etat, 'registre'), 'dates inconnues')),
      el('span', {}, cloture(q, dates)),
      el('span', {}, 'Avancement final : ', a
        ? `${a.faites} faites · ${a.en_cours} en cours · ${a.a_faire} à faire`
        : inconnu(sourceEnEchec(etat, 'structure'), 'inconnu')),
      el('span', {}, 'Branche : ', q.branche ? [mono(q.branche), ' · ', mono(q.commit || '?')] : inconnu(null))),
    el('div', {},
      el('div', { class: 'arch-cle' }, fichiers ? `Fichiers touchés (${fichiers.length})` : 'Fichiers touchés'),
      fichiers
        ? (fichiers.length ? el('ul', { class: 'arch-fichiers' }, fichiers.map((f) => el('li', {}, f))) : el('span', { class: 'discret' }, 'aucun'))
        : inconnu(sourceEnEchec(etat, 'git'), 'inconnus')),
    el('a', { class: 'arch-lien', href: routeEquipe(q.nom) }, 'Ouvrir le détail →'));
}

export function rendre(ctx) {
  etat = ctx.etat;
  let corps;
  if (!Array.isArray(etat.equipes)) {
    corps = el('div', { class: 'inconnu-bloc' }, 'Liste des équipes inconnue : source de la structure en échec (voir l’en-tête).');
  } else {
    const finies = etat.equipes.filter((q) => q.statut === 'terminee');
    corps = finies.length
      ? el('div', { class: 'arch-liste' }, finies.map(carte))
      : el('div', { class: 'vide-calme' }, 'Aucune équipe clôturée pour l’instant.');
  }
  ctx.contenu.append(el('section', { class: 'section' },
    el('div', { class: 'section-tete' }, el('h2', {}, 'Équipes clôturées'),
      el('span', { class: 'sous-titre' }, 'consultables, jamais modifiables : leur travail reste intact')),
    corps));
  mesurerLargeur();
}
