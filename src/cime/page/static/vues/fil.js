// Cime — fil des échanges : qui parle à qui, ce qui attend une réponse, texte
// complet au clic, filtres par équipe, agent ou attentes.

import {
  el, vider, pluriel, nomAgent, sourcesEnEchec, routeFil,
  mesurerLargeur, ligneFil, phraseAttente, pourUtilisateur, niveauRetard,
} from '../commun.js';

// Filtres lus dans l'ancre (#/fil?agent=…&equipe=…&attentes=1) à chaque rendu.
let ctx = null;
let etat = null;
let horloge = null;
let filtre = null;
let zone = null;
let attentesOuvertes_ = null; // choix de l'utilisateur une fois qu'il a ouvert ou replié le bloc

let agentsParId = new Map();
const equipeDe = (id) => (agentsParId.get(id) || {}).equipe || null;
const equipesDuMessage = (m) => [equipeDe(m.de), equipeDe(m.a)].filter(Boolean);



/** Sans horodatage, un message passe en fin de liste. */
const instant = (m) => (m.horodatage ? Date.parse(m.horodatage) : -Infinity);

const retenu = (m) =>
  (!filtre.agent || m.de === filtre.agent || m.a === filtre.agent) &&
  (!filtre.equipe || equipesDuMessage(m).includes(filtre.equipe)) &&
  (!filtre.attentes || m.en_attente);

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
function rendreListe() {
  const fil = etat.fil;
  if (fil === null || fil === undefined) {
    const sources = sourcesEnEchec(etat).map((s) => s.nom);
    vider(zone, el('p', { class: 'fil-indispo', role: 'status' },
      `Fil indisponible : ${sources.length ? sources.join(', ') : 'source inconnue'} en échec.`));
    return;
  }
  const trie = [...fil].sort((a, b) => instant(b) - instant(a));
  const visibles = trie.filter(retenu);
  const attentes = trie.filter((m) => m.en_attente && retenu(m)).sort((a, b) => instant(a) - instant(b));

  vider(zone,
    attentes.length ? blocAttentes(attentes) : null,
    visibles.length
      ? el('ol', { class: 'fil' }, visibles.map(ligneFil))
      : el('p', { class: 'vide-calme' }, 'Aucun échange ne correspond à ces filtres.'));
  ctx.tic();
  mesurerLargeur();
}

function titre(total) {
  return el('div', { class: 'section-tete' },
    el('h2', {}, 'Fil des échanges'),
    total === null ? null : el('span', { class: 'sous-titre' }, `${pluriel(total, 'message')}, du plus récent au plus ancien`));
}

function blocAttentes(liste) {
  const entreAgents = liste.filter((m) => !pourUtilisateur(m));
  const utilisateur = liste.filter(pourUtilisateur);
  const rouge = entreAgents.some((m) => niveauRetard(m, horloge.maintenant()) === 'rouge');
  const ouvert = attentesOuvertes_ === null ? rouge : attentesOuvertes_;
  const groupe = (titre, items, extra) => items.length ? el('div', { class: 'attentes-groupe' },
    el('h4', {}, titre, extra),
    el('ul', {}, items.map((m) => el('li', { class: 'attente-fil' },
      phraseAttente(m), el('span', { class: 'discret attente-resume' }, m.resume))))) : null;
  const details = el('details', { class: `attentes-fil${rouge ? ' a-rouge' : ''}`, open: ouvert },
    el('summary', {},
      pluriel(liste.length, 'message'), ' sans réponse',
      el('span', { class: 'discret' }, ` · ${entreAgents.length} entre agents · ${utilisateur.length} pour toi`)),
    groupe('Entre agents', entreAgents),
    groupe("T'attendent", utilisateur, [' ', el('a', { href: '#/' }, 'voir dans Ce qui t’attend')]));
  details.addEventListener('toggle', () => { attentesOuvertes_ = details.open; mesurerLargeur(); });
  return details;
}

function barreFiltres() {
  const equipes = (etat.equipes || []).map((q) => q.nom);
  const agents = (etat.agents || []).map((a) => a.id);
  const choix = (nom, valeurs, etiquette, courant, majAgent) => el('label', { class: 'filtre' },
    el('span', {}, etiquette),
    el('select', {
      onchange: (ev) => { filtre[nom] = ev.target.value; maj(); },
    }, el('option', { value: '' }, 'Tous'),
    valeurs.map((v) => el('option', { value: v, selected: v === courant }, majAgent ? nomAgent(v) : v))));
  return el('div', { class: 'filtres' },
    choix('equipe', equipes, 'Équipe', filtre.equipe, false),
    choix('agent', agents, 'Agent', filtre.agent, true),
    el('label', { class: 'filtre filtre-case' },
      el('input', { type: 'checkbox', checked: filtre.attentes, onchange: (ev) => { filtre.attentes = ev.target.checked; maj(); } }),
      el('span', {}, 'Seulement les attentes')));
}

function maj() {
  const adresse = routeFil({ agent: filtre.agent, equipe: filtre.equipe, attentes: filtre.attentes ? '1' : '' });
  history.replaceState(null, '', adresse);
  // les filtres restent ceux-là quand le prochain instantané réaffiche l'écran
  ctx.route.params = new URLSearchParams(adresse.split('?')[1] || '');
  rendreListe();
}

export function rendre(contexte) {
  ctx = contexte;
  ({ etat, horloge } = ctx);
  const params = ctx.route.params;
  filtre = {
    agent: params.get('agent') || '',
    equipe: params.get('equipe') || '',
    attentes: params.get('attentes') === '1',
  };
  agentsParId = new Map((etat.agents || []).map((a) => [a.id, a]));
  zone = el('div', { class: 'fil-zone' });
  vider(ctx.contenu, el('section', { class: 'section fil-page' },
    titre(Array.isArray(etat.fil) ? etat.fil.length : null),
    Array.isArray(etat.fil) ? barreFiltres() : null, zone));
  rendreListe();
}
