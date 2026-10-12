// Cime — journal des actions, tel que la source le donne (l'hôte), du plus récent au plus ancien.

import {
  el, vider, mono, pluriel, nomAgent, heureLocale, mesurerLargeur,
} from '../commun.js';

const ACTIONS = {
  autoriser: 'autorisation accordée',
  refuser: 'autorisation refusée',
  accorder: 'accord donné',
  trancher: 'décision tranchée',
  deposer: 'fichier déposé',
  cloturer: 'équipe clôturée',
  lu: 'compte rendu lu',
  fusions_auto: 'mode autonome',
};

/** Refuser un accord (ses détails portent l’objet) n’est pas refuser une autorisation (agent, outil). */
function libelleAction(l) {
  if (l.action === 'refuser' && l.details && typeof l.details.objet === 'string') return 'accord refusé';
  return ACTIONS[l.action] || l.action;
}

/** Un résumé court des détails : leurs valeurs, dans l'ordre où le journal les donne. */
function resume(details) {
  return Object.values(details || {}).filter((v) => v !== null && v !== undefined).join(' · ');
}

function resultat(r) {
  if (r === 'ok') return el('span', { class: 'res res-ok' }, 'ok');
  if (r === 'refuse') return el('span', { class: 'res res-refuse' }, 'refusé');
  if (typeof r === 'string' && r.startsWith('erreur')) {
    return el('span', { class: 'res res-erreur' }, r);
  }
  return el('span', { class: 'res' }, r === null || r === undefined ? 'inconnu' : String(r));
}

function ligne(l) {
  const quand = Date.parse(l.horodatage);
  const date = Number.isNaN(quand) ? 'inconnue' : heureLocale(l.horodatage);
  return el('li', { class: `journal-ligne${String(l.resultat).startsWith('erreur') ? ' erreur' : ''}${l.resultat === 'refuse' ? ' refuse' : ''}` },
    el('div', { class: 'journal-meta' },
      el('span', { class: 'journal-heure mono' }, date),
      el('span', { class: 'journal-auteur mono' }, nomAgent(l.auteur)),
      resultat(l.resultat)),
    el('div', { class: 'journal-action' },
      el('strong', {}, libelleAction(l)), ' ', mono(l.cible),
      resume(l.details) ? el('span', { class: 'discret journal-details' }, ` — ${resume(l.details)}`) : null));
}

export function rendre(ctx) {
  const racine = el('section', { class: 'section journal-page' });
  vider(ctx.contenu, racine);
  if (!Array.isArray(ctx.journal)) {
    vider(racine,
      el('div', { class: 'section-tete' }, el('h2', {}, 'Journal')),
      el('div', { class: 'inconnu-bloc' }, 'Journal pas encore lu auprès de l’hôte : il s’affichera dès qu’il répondra.'));
    mesurerLargeur();
    return;
  }
  const lignes = [...ctx.journal]
    .sort((a, b) => Date.parse(b.horodatage) - Date.parse(a.horodatage));
  vider(racine,
    el('div', { class: 'section-tete' },
      el('h2', {}, 'Journal'),
      el('span', { class: 'sous-titre' }, `${pluriel(lignes.length, 'action')}, de la plus récente à la plus ancienne`)),
    el('p', { class: 'journal-rappel' },
      'Toute action faite depuis cette page est inscrite ici, avec son auteur et son heure.'),
    lignes.length
      ? el('ol', { class: 'journal' }, lignes.map(ligne))
      : el('p', { class: 'vide-calme' }, 'Aucune action inscrite pour le moment.'));
  mesurerLargeur();
}
