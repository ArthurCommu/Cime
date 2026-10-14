// Cime — la ligne « Workers : A actifs sur P », près du mode autonome : une ligne qui se déplie sur le détail du plafond de la machine
// et sur son réglage (le réglage est une prérogative de l'utilisateur : la page l'exécute, `reglerPlafond` de ../commun.js).
// Seul le repli choisi par l'utilisateur vit ici, pour survivre au redessin du rail.

import { el, mono, dateCourte, reglerPlafond, plafondDemande, retourPlafond, actionsSontFigees, PHRASE_ACTIONS_FIGEES } from '../commun.js';
import { lireCharge, phraseWorkers, projetPlusBas, valeurChoisie, optionsPlafond, PLAFOND_DEFAUT } from '../charge.js';

let deplie = false;

/** Remet à zéro le repli (les tests). */
export function reinitialiserWorkers() {
  deplie = false;
}

/** « Plafond de la machine : 6 », ou « par défaut (3) », puis « modifié par l'utilisateur le 7 oct. 2026 » si la date est connue. */
function ligneMachine(charge) {
  const m = charge.machine;
  if (!m) return 'Plafond de la machine : inconnu';
  const valeur = m.defaut ? `par défaut (${PLAFOND_DEFAUT})` : String(m.valeur);
  const date = m.depuis && !Number.isNaN(new Date(m.depuis).getTime()) ? dateCourte(m.depuis) : null;
  const qui = m.par === 'utilisateur' ? 'l’utilisateur' : m.par;
  return `Plafond de la machine : ${valeur}${date ? ` · modifié par ${qui || 'inconnu'} le ${date}` : ''}`;
}

/** Ce que l'infobulle répète pour la souris. */
function titreDetail(charge) {
  const lignes = [phraseWorkers(charge), charge.machine ? ligneMachine(charge) : null,
    projetPlusBas(charge) ? `Plafond du projet : ${charge.projet}` : null,
    charge.parProjet ? `Par projet : ${charge.parProjet.map(([nom, n]) => `${nom} ${n}`).join(' · ')}` : null];
  return lignes.filter(Boolean).join('\n');
}

/** Le choix de 1 à 8 ou « par défaut » : un `select` natif, désactivé pendant l'appel et quand l'hôte ne répond plus. */
function choixPlafond(charge) {
  const demande = plafondDemande();
  const retour = retourPlafond();
  const fige = actionsSontFigees();
  // l'hôte a dit ok : le choix garde la valeur posée jusqu'à l'instantané qui la montre ; sinon, ce que dit l'état
  const courante = demande || (retour && retour.resultat !== 'erreur' ? retour.valeur : null) || valeurChoisie(charge);
  return el('select', { class: 'plafond-choix', 'aria-busy': demande ? 'true' : null, disabled: Boolean(demande) || fige,
    title: fige ? PHRASE_ACTIONS_FIGEES : null, onchange: (ev) => reglerPlafond(ev.target.value) },
  optionsPlafond().map((o) => el('option', { value: o.valeur, selected: o.valeur === courante }, o.libelle)));
}

/** La réponse de l'hôte, en texte discret près du choix : rouge doux seulement pour une panne, jamais pour « déjà … ». */
function retourDuReglage() {
  const r = retourPlafond();
  if (!r || !r.message) return null;
  return el('p', { class: `plafond-retour${r.resultat === 'erreur' ? ' texte-erreur' : ''}`, role: 'status' }, r.message);
}

/** La ligne dépliante et son panneau. `redessiner()` redessine le rail ou la feuille. */
export function ligneWorkers(etat, redessiner) {
  const charge = lireCharge(etat);
  const ouvert = deplie;
  const bouton = el('button', { type: 'button', class: 'workers-ligne', 'aria-expanded': String(ouvert),
    title: charge ? titreDetail(charge) : 'La charge de la machine est inconnue',
    onclick: () => { deplie = !deplie; redessiner(); } },
  el('span', {}, phraseWorkers(charge)), el('span', { class: 'workers-fleche', 'aria-hidden': 'true' }, ouvert ? '▴' : '▾'));
  const panneau = ouvert ? el('div', { class: 'workers-detail' },
    charge ? [
      el('p', {}, ligneMachine(charge)),
      projetPlusBas(charge) ? el('p', {}, `Plafond du projet : ${charge.projet}`) : null,
      charge.parProjet ? el('p', {}, 'Par projet : ', charge.parProjet.map(([nom, n], i) => [i ? ' · ' : null, mono(nom), ` ${n}`])) : null,
      el('label', { class: 'plafond-reglage' }, el('span', {}, 'Régler le plafond'), choixPlafond(charge)),
      retourDuReglage(),
    ] : el('p', {}, 'La charge de la machine est inconnue pour le moment.')) : null;
  return el('div', { class: 'workers' }, bouton, panneau);
}
