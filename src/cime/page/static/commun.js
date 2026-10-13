// Cime — socle commun à tous les écrans de la page.
//
// `app.js` appelle `rendreSocle(ctx)` à chaque nouvel instantané : l'en-tête, la
// navigation sont réécrits, puis
// l'écran courant rend son contenu dans `ctx.contenu`. L'état de l'interface
// (lignes dépliées, actions envoyées…) vit ici, hors du DOM, pour survivre.
//
// Les données viennent de la couche `source.js` : ce module ne sait pas si
// elles arrivent de l'hôte.

import { lireMode, titrePastille, PASTILLE, TOASTS } from './autonome.js';

// ---------------------------------------------------------------------------
// Seuils (constantes nommées)
// ---------------------------------------------------------------------------
export const AGE_DONNEE_ROUGE_MS = 30_000;
export const CONTEXTE_CHAUD = 0.6;
/** Faute de dernière visite mémorisée, on regarde les 3 dernières heures. */
export const VISITE_PAR_DEFAUT_MS = 3 * 3600_000;

/** La clé de la dernière visite, par projet : la Supervision l'écrit à sa sortie, la Scène ne fait que la lire. */
export const cleVisite = (etat) => `cime:derniere-visite:${etat.projet ? etat.projet.nom : 'projet'}`;

/**
 * La dernière visite de ce navigateur, en lecture seule : `{ instant, memorisee }`. Sans visite mémorisée (ou stockage indisponible), les
 * 3 dernières heures de l'instantané, avec `memorisee: false`.
 */
export function derniereVisite(etat) {
  try {
    const valeur = Number(localStorage.getItem(cleVisite(etat)));
    if (valeur > 0) return { instant: valeur, memorisee: true };
  } catch { /* stockage indisponible : valeur par défaut */ }
  return { instant: Date.parse(etat.genere_a) - VISITE_PAR_DEFAUT_MS, memorisee: false };
}

// ---------------------------------------------------------------------------
// Libellés
// ---------------------------------------------------------------------------
export const ETATS_AGENT = {
  travaille: { mot: 'travaille', ton: 'vert' },
  au_repos: { mot: 'au repos', ton: 'gris' },
  // un coordinateur endormi n'est pas arrêté : sa session est fermée volontairement et rouverte au prochain message
  endormi: { mot: 'endormi', ton: 'gris' },
  attend_autorisation: { mot: 'attend une autorisation', ton: 'ambre' },
  attend_reponse: { mot: 'attend une réponse', ton: 'ambre' },
  arrete: { mot: 'à l’arrêt', ton: 'gris' },
  inconnu: { mot: 'inconnu', ton: 'gris' },
};

/** Un agent arrêté n'est un problème que si une alarme grave le cite ; son équipe ou sa tâche terminée, il est clos. */
export const ETAT_ARRETE_GRAVE = { mot: 'arrêté', ton: 'rouge' };
export const ETAT_CLOS = { mot: 'clos', ton: 'gris' };

export const STATUTS_EQUIPE = {
  active: { mot: 'active', ton: 'vert' },
  au_repos: { mot: 'au repos', ton: 'gris' },
  bloquee: { mot: 'bloquée', ton: 'rouge' },
  terminee: { mot: 'terminée', ton: 'bleu' },
};

/** Statut `null` : pas mesuré, jamais « au repos ». */
export const STATUT_NON_MESURE = { mot: 'non mesuré', ton: 'gris', inconnu: true };

export function defStatutEquipe(statut) {
  if (statut === null || statut === undefined) return STATUT_NON_MESURE;
  return STATUTS_EQUIPE[statut] || { mot: statut, ton: 'gris' };
}

/**
 * Le statut d'une équipe tel qu'on l'affiche : « bloquée » n'est rouge que si une alarme rouge cite l'équipe ;
 * bloquée par une seule attente (autorisation, question), elle est ambre — quelqu'un attend, rien n'est cassé.
 */
export function statutEquipeAffiche(equipe, alarmes) {
  const def = defStatutEquipe(equipe.statut);
  if (equipe.statut !== 'bloquee') return def;
  const rouge = Array.isArray(alarmes) && alarmes.some((a) => alarmeRouge(a) && (a.equipes || []).includes(equipe.nom));
  return rouge ? def : { ...def, ton: 'ambre' };
}

export const NATURES_ATTENTE = {
  autorisation: 'Autorisation',
  decision: 'Décision',
  donnee: 'Il me manque une donnée',
  cloture: 'Clôture à prononcer',
  rapport: 'Compte rendu à lire',
};

export const TYPES_ALARME = {
  autorisation_en_attente: 'Autorisation en attente',
  arret_apres_annonce: 'Arrêt après une annonce',
  question_sans_reponse: 'Question sans réponse',
  recouvrement: 'Deux équipes sur le même fichier',
  brouillon: 'Brouillon resté dans un terminal',
  contexte_plein: 'Contexte presque plein',
  hors_perimetre: 'Fichier hors du périmètre déclaré',
  retard_sur_base: 'Retard sur la branche de base',
  session_disparue: 'Session disparue',
  action_refusee: 'Action refusée par le garde',
  bloque_au_demarrage: 'Bloqué sur un écran de démarrage',
  fige: 'Agent figé',
  session_orpheline: 'Session hors organigramme',
  gros_poste: 'Gros consommateur',
  contexte_au_repos: 'Contexte lourd au repos',
  assistant_sourd: 'L’Assistant n’a pas pris un message',
  livraison_echouee: 'Courrier échoué',
  livraison_bloquee: 'Message en file trop longtemps',
  facteur_arrete: 'Le facteur est arrêté',
  fin_sans_suite: 'Agent arrêté avec une obligation ouverte',
};

export const GRAVITES = {
  grave: { mot: 'Grave', ton: 'rouge', rang: 0 },
  a_voir: { mot: 'À voir', ton: 'ambre', rang: 1 },
  info: { mot: 'Info', ton: 'gris', rang: 2 },
};

/**
 * Les alarmes qui disent qu'on attend quelqu'un : leur gravité mesure l'urgence et ordonne les lignes,
 * mais leur couleur est celle d'une attente, l'ambre — jamais le rouge, réservé aux problèmes.
 */
export const TYPES_ALARME_ATTENTE = ['autorisation_en_attente', 'question_sans_reponse'];

/** La couleur d'une alarme, en un seul endroit : une attente est ambre quelle que soit sa gravité ; sinon grave rouge, à voir ambre, info gris. */
export function tonAlarme(alarme) {
  if (TYPES_ALARME_ATTENTE.includes(alarme.type)) return 'ambre';
  return (GRAVITES[alarme.gravite] || GRAVITES.info).ton;
}

/** Le mot d'une alarme : « Grave » ; une attente de l'utilisateur grave se lit « À trancher » (ambre, comme toute attente). La gravité reste celle qui ordonne. */
export function motAlarme(alarme) {
  if (TYPES_ALARME_ATTENTE.includes(alarme.type) && (GRAVITES[alarme.gravite] || GRAVITES.info) === GRAVITES.grave) return 'À trancher';
  return (GRAVITES[alarme.gravite] || GRAVITES.info).mot;
}

/** Une alarme qui est un problème : celle dont la couleur est le rouge. */
export const alarmeRouge = (alarme) => tonAlarme(alarme) === 'rouge';

export const NATURES_FIL = {
  question: 'question',
  reponse: 'réponse',
  consigne: 'consigne',
  travail_pret: 'travail prêt',
  compte_rendu: 'compte rendu',
  signalement: 'signalement',
  demande_cloture: 'demande de clôture',
  decision_utilisateur: 'décision pour l’utilisateur',
  donnee_utilisateur: 'donnée pour l’utilisateur',
  rapport_utilisateur: 'rapport pour l’utilisateur',
};

/** Ce que dit l'en-tête quand une source a échoué. */
const SOURCES_EN_ECHEC = {
  structure: 'structure .orga illisible',
  registre: 'registre illisible',
  transcripts: 'transcripts illisibles',
  tmux: 'tmux injoignable',
  git: 'git injoignable',
  tarifs: 'tarifs introuvables',
};

export const PAGES = [
  { id: 'scene', href: '#/', titre: 'Scène' },
  { id: 'supervision', href: '#/supervision', titre: 'Supervision' },
  { id: 'fil', href: '#/fil', titre: 'Fil' },
];

/** Adresses des écrans (navigation par ancre). */
export const routeEquipe = (nom) => `#/equipe/${encodeURIComponent(nom)}`;
export function routeFil(filtres = {}) {
  const p = new URLSearchParams();
  for (const [cle, valeur] of Object.entries(filtres)) if (valeur) p.set(cle, valeur);
  const requete = p.toString();
  return requete ? `#/fil?${requete}` : '#/fil';
}

export const PHRASE_HIERARCHIE =
  "Cette page ne peut pas écrire aux agents. Pour leur demander quelque chose, passe par l'Assistant.";
/** L'info-bulle de l'icône « Demander à l'Assistant » : d'abord ce que fait l'icône, puis la hiérarchie. */
export const TITRE_DEMANDER = `Demander à l’Assistant : ${PHRASE_HIERARCHIE.charAt(0).toLowerCase()}${PHRASE_HIERARCHIE.slice(1)}`;

// ---------------------------------------------------------------------------
// Construction du DOM (jamais d'innerHTML sur une donnée)
// ---------------------------------------------------------------------------
/**
 * el('div', { class: 'x', onclick: f }, 'texte', autreNoeud, [liste], null)
 * Les enfants null / false sont ignorés ; les tableaux sont aplatis.
 */
export function el(balise, attributs = {}, ...enfants) {
  const noeud = document.createElement(balise);
  for (const [cle, valeur] of Object.entries(attributs || {})) {
    if (valeur === null || valeur === undefined || valeur === false) continue;
    if (cle.startsWith('on') && typeof valeur === 'function') {
      noeud.addEventListener(cle.slice(2), valeur);
    } else if (cle === 'dataset') {
      Object.assign(noeud.dataset, valeur);
    } else if (valeur === true) {
      noeud.setAttribute(cle, '');
    } else {
      noeud.setAttribute(cle, String(valeur));
    }
  }
  ajouter(noeud, enfants);
  return noeud;
}

function ajouter(noeud, enfants) {
  for (const enfant of enfants.flat(Infinity)) {
    if (enfant === null || enfant === undefined || enfant === false) continue;
    noeud.append(enfant instanceof Node ? enfant : document.createTextNode(String(enfant)));
  }
}

export function vider(noeud, ...enfants) {
  noeud.replaceChildren();
  ajouter(noeud, enfants);
  return noeud;
}

/** Les icônes de la page : des tracés en ligne (24×24, trait `currentColor`) ; ni police d'icônes ni bibliothèque. */
export const ICONES = {
  bulle: ['M5 4h14a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H10l-5 4v-4H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z'],
  scene: ['M3 10l9-6 9 6v10H3z', 'M9 20v-6h6v6'],
  supervision: ['M4 4h7v7H4z', 'M13 4h7v7h-7z', 'M4 13h7v7H4z', 'M13 13h7v7h-7z'],
  fil: ['M4 6h16', 'M4 12h16', 'M4 18h10'],
};

/**
 * Une icône en SVG en ligne, décorative (le libellé est porté par le bouton ou le lien qui la contient). Le balisage vient de la
 * table ICONES ci-dessus, jamais d'une donnée : l'analyseur HTML donne seul aux éléments leur espace de noms SVG.
 */
export function icone(nom, classe = '') {
  const gabarit = document.createElement('template');
  gabarit.innerHTML = `<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" `
    + `stroke-linejoin="round" aria-hidden="true" focusable="false"${classe ? ` class="${classe}"` : ''}>`
    + `${ICONES[nom].map((d) => `<path d="${d}"/>`).join('')}</svg>`;
  return gabarit.content.firstElementChild;
}

export function mono(texte) {
  return el('span', { class: 'mono' }, texte);
}

/**
 * Mention courte d'une valeur inconnue répétée sur chaque carte (« coût ? ») :
 * l'échec de la source est déjà dit dans l'en-tête, l'explication va dans le title.
 */
export function inconnuCourt(mot, source) {
  return el('span', { class: 'inconnu',
    title: source ? `${mot} inconnu : source ${source} en échec (voir l’en-tête)` : `${mot} inconnu` }, `${mot} ?`);
}

/** Valeur nulle : « inconnu », avec la source en échec. Jamais 0 ni « aucun ». */
export function inconnu(source, mot = 'inconnu') {
  return el('span', { class: 'inconnu', title: source ? `source en échec : ${source}` : null },
    source ? `${mot} (${source} en échec)` : mot);
}

// ---------------------------------------------------------------------------
// Sources en échec
// ---------------------------------------------------------------------------
export function sourcesEnEchec(etat) {
  return (etat.sources || []).filter((s) => s.ok === false);
}

export function sourceEnEchec(etat, nom) {
  return sourcesEnEchec(etat).some((s) => s.nom === nom) ? nom : null;
}

// ---------------------------------------------------------------------------
// Âges en français (l'horloge est celle de la source : heure de l'instantané)
// ---------------------------------------------------------------------------
function decomposer(ms) {
  const s = Math.max(0, Math.floor(ms / 1000));
  if (s < 60) return { court: `${s} s` };
  const min = Math.floor(s / 60);
  if (min < 60) return { court: `${min} min` };
  const h = Math.floor(min / 60);
  if (h < 24) {
    const reste = min % 60;
    return { court: reste ? `${h} h ${String(reste).padStart(2, '0')}` : `${h} h` };
  }
  return { court: `${Math.floor(h / 24)} j` };
}

/** « 3 s », « 18 min », « 2 h 10 », « 3 j ». */
export function duree(ms) {
  return decomposer(ms).court;
}

export function ilYA(iso, maintenant) {
  if (!iso) return null;
  return `il y a ${duree(maintenant - Date.parse(iso))}`;
}

export function depuis(iso, maintenant) {
  if (!iso) return null;
  return `depuis ${duree(maintenant - Date.parse(iso))}`;
}

/**
 * Un âge qui vit : l'élément porte son horodatage et le ticker du socle le
 * réécrit chaque seconde. format : 'il-y-a' | 'depuis' | 'court' (« 5 min », sans préfixe).
 */
export function age(iso, format = 'il-y-a', prefixe = '') {
  if (!iso) return null;
  return el('time', { datetime: iso, dataset: { age: format, prefixe }, title: heureLocale(iso) });
}

function rafraichirAges(racine, maintenant) {
  for (const t of racine.querySelectorAll('time[data-age]')) {
    const iso = t.getAttribute('datetime');
    const texte = t.dataset.age === 'court' ? duree(maintenant - Date.parse(iso))
      : t.dataset.age === 'depuis' ? depuis(iso, maintenant) : ilYA(iso, maintenant);
    t.textContent = (t.dataset.prefixe || '') + texte;
  }
}

export function heureLocale(iso) {
  return new Date(iso).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'medium' });
}

export function dateCourte(iso) {
  return new Date(iso).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' });
}

export function pluriel(n, singulier, plurielForme = `${singulier}s`) {
  return `${n} ${n === 1 ? singulier : plurielForme}`;
}

/** Les morceaux présents, séparés par `sep` : un séparateur n'existe qu'entre deux morceaux présents (null, false, '' et [] sont absents). */
export function joindre(morceaux, sep) {
  const presents = morceaux.filter((m) => m !== null && m !== undefined && m !== false && m !== '' && !(Array.isArray(m) && m.length === 0));
  return presents.flatMap((m, i) => (i ? [sep, m] : [m]));
}

/**
 * Les effectifs en une phrase : « 1 travaille · 2 attendent · 1 au repos ». Les zéros se taisent, sauf « 0 travaillent » ;
 * le nombre tient à son mot (espace insécable), la coupure n'est permise qu'après « · ».
 */
export function libelleEffectifs(compte) {
  const n = (cle) => compte[cle] || 0;
  const mot = (nombre, un, plusieurs) => `${nombre}\u00A0${nombre === 1 ? un : plusieurs}`;
  const morceaux = [
    mot(n('travaille'), 'travaille', 'travaillent'),
    n('au_repos') ? mot(n('au_repos'), 'au repos', 'au repos') : null,
    n('endormi') ? mot(n('endormi'), 'endormi', 'endormis') : null,
    n('attend') ? mot(n('attend'), 'attend', 'attendent') : null,
    n('a_l_arret') ? `${n('a_l_arret')}\u00A0à l’arrêt` : null,
    n('inconnu') ? mot(n('inconnu'), 'inconnu', 'inconnus') : null,
    n('arrete') ? mot(n('arrete'), 'arrêté', 'arrêtés') : null,
  ];
  return morceaux.filter(Boolean).join(' · ');
}

// ---------------------------------------------------------------------------
// Agents
// ---------------------------------------------------------------------------
export function nomAgent(id) {
  if (id === 'utilisateur') return 'Utilisateur';
  if (id === 'assistant') return 'Assistant';
  return id;
}

/**
 * L'état affiché d'un agent. « arrêté » se mesure à l'absence de session : si
 * tmux n'a pas répondu (`vivant: null`), l'état devient « inconnu ».
 */
export function etatAffiche(agent) {
  if (!agent || !agent.etat) return 'inconnu';
  if (agent.etat === 'arrete' && agent.vivant === null) return 'inconnu';
  return ETATS_AGENT[agent.etat] ? agent.etat : 'inconnu';
}

/**
 * Le mot et le ton d'un agent : `{ cle, mot, ton }`. Un agent arrêté est « à l’arrêt » (gris) ; il n'est « arrêté » (rouge) que si une
 * alarme rouge le cite ; « clos » (gris) quand son équipe est terminée ou que son travail est rendu (`workerTermine`).
 */
export function defEtatAgent(agent, alarmes, { equipeTerminee = false } = {}) {
  const cle = etatAffiche(agent);
  if (cle !== 'arrete') return { cle, ...ETATS_AGENT[cle] };
  if (equipeTerminee || workerTermine(agent, alarmes)) return { cle, ...ETAT_CLOS };
  const grave = alarmesDe(alarmes, { agent: agent.id }).some(alarmeRouge);
  return { cle, ...(grave ? ETAT_ARRETE_GRAVE : ETATS_AGENT.arrete) };
}

export function pastilleEtat(etat, def = ETATS_AGENT[etat] || ETATS_AGENT.inconnu) {
  const inconnuEtat = etat === 'inconnu';
  return el('span', { class: `etat ton-${def.ton}${inconnuEtat ? ' etat-inconnu' : ''}` },
    el('span', { class: 'pastille', 'aria-hidden': 'true' }, inconnuEtat ? '?' : null),
    def.mot);
}

export function puceStatut(statut, def = defStatutEquipe(statut)) {
  return el('span', { class: `puce-statut ton-${def.ton}${def.inconnu ? ' etat-inconnu' : ''}` },
    el('span', { class: 'pastille', 'aria-hidden': 'true' }, def.inconnu ? '?' : null), def.mot);
}

/** Qui cet agent attend-il ? Déduit des messages `en_attente` qu'il a émis. */
export function attenteDe(agentId, fil) {
  if (!Array.isArray(fil)) return null;
  const siens = fil.filter((m) => m.en_attente && m.de === agentId);
  if (!siens.length) return null;
  const plusAncien = siens.reduce((a, b) => (Date.parse(a.horodatage) <= Date.parse(b.horodatage) ? a : b));
  return { qui: plusAncien.a, depuis: plusAncien.horodatage, nombre: siens.length };
}

export function alarmesDe(alarmes, { agent, equipe }) {
  if (!Array.isArray(alarmes)) return [];
  return alarmes.filter((a) => (agent && (a.agents || []).includes(agent)) || (equipe && (a.equipes || []).includes(equipe)));
}

/**
 * Un worker terminé : arrêté, et aucune alarme ne le cite. Sa tâche est rendue, il n'y a rien à voir.
 * Un worker arrêté avec alarme reste un problème. Coordinateurs et Assistant ne sont jamais terminés.
 */
export function workerTermine(agent, alarmes) {
  // `etatAffiche` : un worker dont tmux n'a pas répondu (`vivant: null`) est « inconnu », donc jamais rangé
  if (agent.role !== 'worker' || etatAffiche(agent) !== 'arrete') return false;
  return alarmesDe(alarmes, { agent: agent.id }).length === 0;
}

/** Une équipe dont plus personne n'est en session et que rien ne cite : grise, atténuée. Ce n'est pas un problème. */
export const STATUT_EQUIPE_A_L_ARRET = { mot: 'à l’arrêt', ton: 'gris' };

/**
 * Une équipe « à l'arrêt » : tous ses agents sont arrêtés (mesuré : tmux a répondu) et aucune alarme ne cite l'équipe ni l'un d'eux.
 * Une équipe sans agent, bloquée ou clôturée ne l'est pas ; des alarmes inconnues (`alarmes` absent) ne permettent pas de l'affirmer.
 */
export function equipeALArret(equipe, agents, alarmes) {
  if (equipe.statut === 'terminee' || equipe.statut === 'bloquee' || !Array.isArray(agents) || !Array.isArray(alarmes)) return false;
  const siens = agents.filter((a) => a.equipe === equipe.nom);
  if (!siens.length || !siens.every((a) => etatAffiche(a) === 'arrete')) return false;
  return alarmesDe(alarmes, { equipe: equipe.nom }).length === 0 && siens.every((a) => alarmesDe(alarmes, { agent: a.id }).length === 0);
}

/**
 * Une équipe spéciale sans session (integration) n'a pas de carte : elle passe dans la ligne de liens sous la grille.
 * Elle reste une carte dès qu'un de ses agents a une session (ou qu'on ne sait pas) ou qu'une alarme la cite, elle ou l'un d'eux ;
 * des agents ou des alarmes inconnus ne permettent pas de l'affirmer.
 */
export function equipeEnRetrait(equipe, agents, alarmes) {
  if (!equipe.speciale || equipe.statut === 'terminee' || !Array.isArray(agents) || !Array.isArray(alarmes)) return false;
  const siens = agents.filter((a) => a.equipe === equipe.nom);
  if (!siens.every((a) => a.vivant === false && !a.session_tmux)) return false;
  return alarmesDe(alarmes, { equipe: equipe.nom }).length === 0 && siens.every((a) => alarmesDe(alarmes, { agent: a.id }).length === 0);
}

function formatTokens(n) {
  return n >= 1000 ? `${Math.round(n / 1000)} k` : String(n);
}

/**
 * Nombre de jetons en clair : « 812 », « 12 k », « 4,3 M ». Fonction pure ; null si la valeur n'est pas un
 * nombre. Milliers et millions sont tronqués, pas arrondis : 999 999 reste « 999 k ».
 */
export function jetons(n) {
  if (typeof n !== 'number' || !Number.isFinite(n)) return null;
  if (n < 1000) return String(Math.trunc(n));
  if (n < 1_000_000) return `${Math.trunc(n / 1000)} k`;
  return `${(Math.trunc(n / 100_000) / 10).toFixed(1).replace('.', ',')} M`;
}

/** Une valeur de jetons, ou « inconnu » si elle est absente : jamais 0 à la place. */
export function jetonsOuInconnu(n) {
  return jetons(n) ?? inconnu(null);
}

/** Une part entière en pour cent, avec une espace insécable : « 31 % ». */
export function pourcent(part) {
  return `${Math.round(part * 100)}\u00a0%`;
}

function jaugeContexte(contexte, etat) {
  if (!contexte) return inconnuCourt('contexte', sourceEnEchec(etat, 'transcripts'));
  const part = contexte.limite ? contexte.tokens / contexte.limite : 0;
  const pourcent = Math.round(part * 100);
  return el('div', { class: 'jauge', dataset: { chaud: part > CONTEXTE_CHAUD ? 'oui' : 'non' } },
    el('span', { class: 'jauge-texte' },
      `contexte ${formatTokens(contexte.tokens)} / ${formatTokens(contexte.limite)} · ${pourcent} %`,
      part > CONTEXTE_CHAUD ? ' · chargé' : null),
    el('div', { class: 'jauge-barre', role: 'img', 'aria-label': `contexte rempli à ${pourcent} %` },
      el('div', { class: 'jauge-plein', style: `width: ${Math.min(100, pourcent)}%` })));
}

function cout(agent, etat) {
  if (agent.cout_usd_estime === null || agent.cout_usd_estime === undefined) {
    return inconnuCourt('coût', sourceEnEchec(etat, 'tarifs'));
  }
  return el('span', { class: 'mono', title: 'estimation côté client, pas la facture' },
    `≈ ${agent.cout_usd_estime.toFixed(2)} $`);
}

/** « conso 15 min : X lus (dont Z sous-agents) · 60 min : Y lus » ; « conso inconnue » si null ; rien pour l'utilisateur. */
function ligneConso(agent) {
  if (agent.role === 'utilisateur') return null;
  if (!agent.consommation) return el('span', { class: 'conso-ligne inconnu' }, 'conso inconnue');
  const f15 = agent.consommation['15min'] || {};
  const f60 = agent.consommation['60min'] || {};
  return el('span', { class: 'conso-ligne' },
    'conso 15 min : ', jetonsOuInconnu(f15.lus), ' lus',
    f15.dont_sous_agents > 0 ? [' (dont ', jetonsOuInconnu(f15.dont_sous_agents), ' sous-agents)'] : null,
    ' · 60 min : ', jetonsOuInconnu(f60.lus), ' lus');
}

/** Page d'équipe : écrits, tours et contexte moyen pour les deux fenêtres ; une valeur absente est « inconnu ». */
function grilleConso(c) {
  const f15 = c['15min'] || {};
  const f60 = c['60min'] || {};
  const lignes = [
    ['écrits', (f) => jetonsOuInconnu(f.ecrits)],
    ['tours', (f) => (Number.isInteger(f.tours) ? String(f.tours) : inconnu(null))],
    ['contexte moyen', (f) => jetonsOuInconnu(f.contexte_moyen)],
  ];
  return el('div', { class: 'conso-grille' },
    el('span', {}),
    el('span', { class: 'discret' }, '15 min'),
    el('span', { class: 'discret' }, '60 min'),
    lignes.map(([libelle, valeur]) => [
      el('span', { class: 'discret' }, libelle),
      el('span', { class: 'mono' }, valeur(f15)),
      el('span', { class: 'mono' }, valeur(f60))]));
}

/**
 * Carte d'un agent : nom, état (pastille + mot), depuis quand, tâche, contexte,
 * coût, modèle. `ctx` = { etat } (l'instantané). `options` = { detail } : la page
 * d'équipe ajoute la grille de consommation (écrits, tours, contexte moyen).
 */
export function carteAgent(agent, ctx, options = {}) {
  const def = defEtatAgent(agent, ctx.etat.alarmes, { equipeTerminee: options.equipeTerminee });
  const etatCle = def.cle;
  const graves = alarmesDe(ctx.etat.alarmes, { agent: agent.id }).filter(alarmeRouge);
  const attend = attenteDe(agent.id, ctx.etat.fil);
  let session = null;
  if (agent.vivant === null) {
    session = inconnuCourt('session', sourceEnEchec(ctx.etat, 'tmux'));
  } else if (etatCle === 'endormi') {
    session = el('div', { class: 'agent-session endormi' }, 'pas de terminal : endormi ', age(agent.etat_depuis, 'depuis'),
      ' · il se réveille au prochain message');
  } else if (agent.vivant === false) {
    session = el('div', { class: 'agent-session absente' }, `session absente${agent.session_tmux ? ` (${agent.session_tmux})` : ''}`);
  }
  const carte = el('article', { class: `agent ton-${def.ton}`, dataset: { agent: agent.id, alarme: graves.length ? 'grave' : null } },
    el('div', { class: 'agent-tete' },
      el('span', { class: 'agent-nom' }, nomAgent(agent.id)),
      pastilleEtat(etatCle, def)),
    el('div', { class: 'agent-depuis' },
      agent.etat_depuis ? age(agent.etat_depuis, 'depuis') : inconnu(null, 'depuis : inconnu'),
      agent.etat_source ? el('span', { class: 'discret' }, ` · ${agent.etat_source}`) : null),
    agent.tache
      ? el('div', { class: 'agent-tache', title: agent.tache }, agent.tache)
      : el('div', { class: 'agent-tache discret' }, 'aucune tâche déclarée'),
    // la dernière phrase (fin du dernier Stop) ne dit l'actualité que d'un agent qui ne travaille pas
    agent.derniere_phrase && etatCle !== 'travaille'
      ? el('div', { class: 'agent-phrase', title: agent.derniere_phrase }, finDePhrase(agent.derniere_phrase))
      : null,
    attend ? el('div', { class: 'agent-attend' },
      attend.qui === 'utilisateur' ? 't’attend ' : `attend ${nomAgent(attend.qui)} `, age(attend.depuis, 'depuis'),
      attend.nombre > 1 ? ` (${attend.nombre} messages)` : null) : null,
    graves.length ? el('div', { class: 'agent-alerte' }, `⚠ ${pluriel(graves.length, 'alarme grave', 'alarmes graves')}`) : null,
    agent.vivant === false ? session : null,
    el('div', { class: 'agent-mesures' },
      agent.contexte ? jaugeContexte(agent.contexte, ctx.etat) : null,
      ligneConso(agent),
      options.detail && agent.consommation ? grilleConso(agent.consommation) : null,
      // les mesures inconnues tiennent sur une seule ligne : « session ? · contexte ? · coût ? »
      el('div', { class: 'agent-pied' },
        el('span', { class: 'agent-inconnus' },
          agent.vivant === null ? session : null,
          agent.contexte ? null : jaugeContexte(null, ctx.etat),
          cout(agent, ctx.etat)),
        agent.modele ? el('span', { class: 'agent-modele' }, agent.modele) : null)));
  return carte;
}

const PHRASE_AFFICHEE_MAX = 110;

/**
 * `derniere_phrase` est déjà la fin du message (« … » + fin). On la
 * montre telle quelle ; si elle est trop longue pour une carte, on en garde la
 * fin, avec un seul « … » devant.
 */
export function finDePhrase(phrase) {
  if (phrase.length <= PHRASE_AFFICHEE_MAX) return phrase;
  const sansPoints = phrase.replace(/^…\s*/, '');
  return `…${sansPoints.slice(-(PHRASE_AFFICHEE_MAX - 1)).trimStart()}`;
}

// ---------------------------------------------------------------------------
// Fil des échanges : une ligne dense par message (Vue d'ensemble, équipe, Fil)
// ---------------------------------------------------------------------------
/** Au-delà, une question entre agents restée sans réponse est « en retard » (alarme question_sans_reponse) : ambre appuyé, une attente n'est pas un problème. */
export const SEUIL_QUESTION_MS = 15 * 60_000;
/** Question déposée en fichier : ambre au-delà de 30 min, rouge au-delà de 2 h. */
export const SEUIL_QUESTION_ECRITE_MS = 30 * 60_000;
export const SEUIL_QUESTION_ECRITE_GRAVE_MS = 2 * 3600_000;

/** Un message en attente dont le destinataire est l'utilisateur : un point qui t’attend, jamais « en retard ». */
export const pourUtilisateur = (m) => m.en_attente && m.a === 'utilisateur';
/** Seule une question entre agents a un seuil. */
export const aSeuil = (m) => m.en_attente && !pourUtilisateur(m) && m.nature === 'question';

const estConversation = (m) => m.nature === null && m.source === 'hook';
/** Question déposée en fichier (`fic-…`, source « structure ») : une question ordinaire, repérée comme telle. */
export const estQuestionEcrite = (m) => m.source === 'structure' && m.nature === 'question';
export const libelleNature = (m) => (estConversation(m) ? 'conversation' : estQuestionEcrite(m) ? 'question écrite' : (NATURES_FIL[m.nature] || m.nature || 'nature inconnue'));

/**
 * Le retard d'une attente entre agents : `null`, `'ambre'` ou `'rouge'` (bornes exclues).
 * Question écrite : ambre au-delà de 30 min, rouge au-delà de 2 h ; autre question : rouge au-delà de 15 min.
 */
export function niveauRetard(m, maintenantMs) {
  if (!aSeuil(m) || !m.horodatage) return null;
  const attente = maintenantMs - Date.parse(m.horodatage);
  if (estQuestionEcrite(m)) {
    return attente > SEUIL_QUESTION_ECRITE_GRAVE_MS ? 'rouge' : attente > SEUIL_QUESTION_ECRITE_MS ? 'ambre' : null;
  }
  return attente > SEUIL_QUESTION_MS ? 'rouge' : null;
}

/** Le message derrière chaque phrase d'attente affichée, pour que `colorierAttentes` la recolore sans le relire du DOM. */
const messagesDesPhrases = new WeakMap();

/** « X attend Y depuis … » ; quand l'utilisateur est concerné : « X t'attend » / « tu attends Y ». */
export function phraseAttente(m, court = false) {
  const duree = m.horodatage ? age(m.horodatage, 'depuis') : ['depuis ', inconnu(null)];
  let debut;
  if (pourUtilisateur(m)) debut = court ? 't’attend ' : [el('strong', {}, nomAgent(m.de)), ' t’attend '];
  else if (m.de === 'utilisateur') debut = court ? 'tu attends ' : ['Tu attends ', el('strong', {}, nomAgent(m.a)), ' '];
  else debut = court ? 'attend ' : [el('strong', {}, nomAgent(m.de)), ' attend ', el('strong', {}, nomAgent(m.a)), ' '];
  const phrase = el('span', {
    class: `attend-phrase ${court ? 'attend-court' : 'attend-long'}${estQuestionEcrite(m) ? ' ecrite' : ''}`,
    dataset: { depuis: m.horodatage || '', seuil: aSeuil(m) ? '1' : '' },
  }, debut, duree, el('span', { class: 'attend-mot' }));
  messagesDesPhrases.set(phrase, m);
  return phrase;
}

const MOTS_RETARD = { ambre: ' · sans réponse', rouge: ' · en retard' };

/** Colore les questions entre agents selon `niveauRetard` : `a-voir` (ambre, « sans réponse »), `tard` (ambre appuyé, « en retard »). */
export function colorierAttentes() {
  const maintenant = source.horloge.maintenant();
  for (const n of document.querySelectorAll('[data-seuil]')) {
    const m = messagesDesPhrases.get(n);
    const niveau = m ? niveauRetard(m, maintenant) : null;
    n.classList.toggle('a-voir', niveau === 'ambre');
    n.classList.toggle('tard', niveau === 'rouge');
    const mot = n.querySelector('.attend-mot');
    if (mot) mot.textContent = MOTS_RETARD[niveau] || '';
    const ligneParente = n.closest('.fil-ligne');
    if (ligneParente) {
      ligneParente.classList.toggle('a-voir', niveau === 'ambre');
      ligneParente.classList.toggle('tard', niveau === 'rouge');
    }
  }
}

/** Lignes du fil dépliées (par id de message) : elles le restent quand l'instantané change. */
const filOuverts = new Set();
/** Textes complets déjà lus, le temps que la ligne reste dépliée. */
const textesLus = new Map();

/**
 * Le texte complet d'un message ou d'un compte rendu, tel que la source le
 * donne : { avant, paragraphes, contenu, fichier, note }.
 */
export function rendreTexte(t) {
  return [
    t.avant ? el('p', { class: 'discret' }, t.avant, t.fichier ? [' dans ', mono(t.fichier)] : null, '.') : null,
    (t.paragraphes || []).filter(Boolean).map((p) => el('p', {}, p)),
    typeof t.contenu === 'string' ? el('div', { class: 'texte-fichier' }, t.contenu) : null,
    !t.avant && t.fichier ? el('p', { class: 'mono' }, `Fichier : ${t.fichier}`) : null,
    t.note ? el('p', { class: 'discret' }, t.note) : null,
  ];
}

/** `seulContenu` : le contenu du fichier et rien d'autre (ni résumé, ni mention du fichier, ni note). */
function remplirPanneau(panneau, m, seulContenu = false) {
  const lu = textesLus.get(m.id);
  if (!lu) {
    vider(panneau, el('p', { class: 'discret' }, 'Lecture du texte complet…'));
    const promesse = source.texte(m).then((t) => ({ t }), (e) => ({ erreur: e.message }));
    textesLus.set(m.id, promesse);
    promesse.then((r) => { textesLus.set(m.id, r); if (panneau.isConnected) remplirPanneau(panneau, m, seulContenu); });
    return;
  }
  if (lu instanceof Promise) return;
  if (seulContenu) {
    vider(panneau, lu.erreur
      ? el('p', { class: 'texte-erreur' }, `Texte complet illisible : ${lu.erreur}.`)
      : typeof lu.t.contenu === 'string' ? el('div', { class: 'texte-fichier' }, lu.t.contenu)
        : el('p', { class: 'discret' }, 'Contenu du fichier indisponible.'));
    mesurerLargeur();
    return;
  }
  vider(panneau, lu.erreur
    ? [el('p', {}, m.resume), el('p', { class: 'texte-erreur' }, `Texte complet illisible : ${lu.erreur}.`),
      m.fichier ? el('p', { class: 'mono' }, `Fichier : ${m.fichier}`) : null]
    : rendreTexte(lu.t));
  mesurerLargeur();
}

/** Un bouton qui déplie le texte complet d'un message ou d'un fichier ({ id, resume, fichier }) dans son panneau. */
export function texteDepliable(m, classeBouton, contenu, { seulContenu = false } = {}) {
  const ouvert = filOuverts.has(m.id);
  const panneau = el('div', { class: 'fil-texte', hidden: !ouvert });
  if (ouvert) remplirPanneau(panneau, m, seulContenu);
  const bouton = el('button', { type: 'button', class: classeBouton, 'aria-expanded': String(ouvert) }, contenu);
  bouton.addEventListener('click', () => {
    const etaitOuvert = bouton.getAttribute('aria-expanded') === 'true';
    bouton.setAttribute('aria-expanded', String(!etaitOuvert));
    panneau.hidden = etaitOuvert;
    if (etaitOuvert) {
      filOuverts.delete(m.id);
      textesLus.delete(m.id); // relu au prochain dépliage : le fichier a pu changer
    } else {
      filOuverts.add(m.id);
      remplirPanneau(panneau, m, seulContenu);
    }
    mesurerLargeur();
  });
  return { bouton, panneau };
}

/** Un message adressé à l'utilisateur sans rien lui demander (`fil[].non_lu`). */
export function estNonLu(m) {
  return m.non_lu === true;
}

/** Le repère « non lu » et « Marquer comme lu », frères du bouton de dépliage (jamais dedans). */
export function repereNonLu(m) {
  const repere = el('span', { class: 'fil-non-lu' }, 'non lu');
  if (attenteEnvoyee(m.id)) return el('div', { class: 'fil-lu' }, repere, el('p', { class: 'attente-envoyee' }, MOT_ENVOYEE));
  return el('div', { class: 'fil-lu' }, repere,
    el('button', { type: 'button', class: 'bouton', disabled: attenteEnCours(m.id) || actionsFigees, title: actionsFigees ? PHRASE_ACTIONS_FIGEES : null,
      onclick: () => agir({ action: 'lu', attente: m, corps: { attente_id: m.id }, cible: m.id, details: { message: m.id } }) },
    'Marquer comme lu'));
}

/** Une ligne du fil : un clic déplie le texte complet. */
export function ligneFil(m) {
  const { bouton, panneau } = texteDepliable(m, 'fil-ouvrir', [
    el('span', { class: 'fil-age discret' }, m.horodatage ? age(m.horodatage) : inconnu(null, 'âge inconnu')),
    el('span', { class: 'mono fil-qui' }, `${nomAgent(m.de)} → ${nomAgent(m.a)}`),
    el('span', { class: 'fil-nature' }, libelleNature(m)),
    el('span', { class: 'fil-resume' }, m.resume),
    m.en_attente ? phraseAttente(m) : null,
    m.en_attente ? phraseAttente(m, true) : null]);
  const ligne = el('li', {
    class: `fil-ligne${estConversation(m) ? ' conversation' : ''}${m.en_attente ? ' attend' : ''}${m.en_attente && estQuestionEcrite(m) ? ' ecrite' : ''}`,
    dataset: { id: m.id },
  }, bouton, panneau, estNonLu(m) ? repereNonLu(m) : null);
  return ligne;
}

// ---------------------------------------------------------------------------
// Alarmes
// ---------------------------------------------------------------------------
export const lienEquipe = (n) => el('a', { href: routeEquipe(n), class: 'mono' }, n);

function lienAgent(id) {
  return el('a', { href: routeFil({ agent: id }), class: 'mono' }, nomAgent(id));
}

/** Les cibles d'une alarme : agents → fil filtré, équipes → page de l'équipe ; null si elle n'en a pas. */
export function ciblesAlarme(a) {
  const agents = a.agents || [];
  const equipes = a.equipes || [];
  if (!agents.length && !equipes.length) return null;
  return el('div', { class: 'alarme-cibles secondaire' },
    agents.length ? ['agents : ', agents.map((id, i) => [i ? ', ' : '', lienAgent(id)])] : null,
    agents.length && equipes.length ? ' · ' : null,
    equipes.length ? ['équipes : ', equipes.map((n, i) => [i ? ', ' : '', lienEquipe(n)])] : null);
}

/** Une carte d'alarme : agents → fil filtré, équipes → page de l'équipe. */
export function carteAlarme(a) {
  return el('article', { class: `alarme ton-${tonAlarme(a)}`, dataset: { gravite: a.gravite } },
    el('span', { class: 'alarme-gravite' }, motAlarme(a)),
    el('div', { class: 'alarme-corps' },
      el('div', { class: 'alarme-tete' },
        el('span', { class: 'alarme-type' }, TYPES_ALARME[a.type] || a.type),
        el('span', { class: 'discret' }, a.depuis ? age(a.depuis, 'depuis') : inconnu(null, 'depuis : inconnu'))),
      ciblesAlarme(a),
      el('p', { class: 'alarme-ligne' }, el('span', { class: 'alarme-cle' }, 'Mesure'), a.mesure),
      el('p', { class: 'alarme-ligne alarme-quoi' }, el('span', { class: 'alarme-cle' }, 'Quoi faire'), a.quoi_faire)));
}

/**
 * Les alarmes `info` rangées par type, dans l'ordre où chaque type apparaît : une ligne par type plutôt qu'une carte par alarme.
 * `ton` est ambre si l'une d'elles est une attente (tonAlarme), gris sinon.
 */
export function grouperInfos(alarmes) {
  const infos = alarmes.filter((a) => a.gravite === 'info');
  return [...new Set(infos.map((a) => a.type))].map((type) => {
    const siennes = infos.filter((a) => a.type === type);
    return { type, alarmes: siennes, ton: siennes.some((a) => tonAlarme(a) === 'ambre') ? 'ambre' : 'gris' };
  });
}

/** La ligne repliée d'un groupe : « Info ×8 », le type, puis les cibles sans doublon (équipes, sinon agents), dans l'ordre. */
export function resumeGroupeInfos(groupe) {
  const cibles = [...new Set(groupe.alarmes.flatMap((a) => ((a.equipes || []).length ? a.equipes : (a.agents || []).map(nomAgent))))];
  return { mot: `Info ×${groupe.alarmes.length}`, type: TYPES_ALARME[groupe.type] || groupe.type, cibles };
}

/** Les plus anciennes d'abord ; `depuis: null` en fin de leur gravité. */
const ordreDepuis = (a) => (a.depuis ? Date.parse(a.depuis) : Infinity);
export const comparerDepuis = (x, y) => (ordreDepuis(x) === ordreDepuis(y) ? 0 : ordreDepuis(x) < ordreDepuis(y) ? -1 : 1);

/**
 * « Ce qui coince » : les alarmes rangées en lignes, dans l'ordre grave → à voir → autre → info, la plus ancienne d'abord.
 * Une alarme grave est toujours seule (un problème = une ligne) ; les alarmes `a_voir` d'un même type forment un groupe
 * quand elles sont plusieurs (une seule reste une ligne ordinaire) ; les infos forment toujours un groupe par type.
 * Chaque élément : { genre: 'seule' | 'groupe', gravite, type, alarmes (la plus ancienne d'abord), ton }.
 */
export function grouperAlarmes(alarmes) {
  const rang = (a) => (GRAVITES[a.gravite] || GRAVITES.info).rang;
  const triees = [...alarmes].sort((x, y) => rang(x) - rang(y) || comparerDepuis(x, y));
  const seule = (a) => ({ genre: 'seule', gravite: a.gravite, type: a.type, alarmes: [a], ton: tonAlarme(a) });
  const aVoir = triees.filter((a) => a.gravite === 'a_voir');
  return [
    ...triees.filter((a) => rang(a) === GRAVITES.grave.rang && a.gravite in GRAVITES).map(seule),
    ...[...new Set(aVoir.map((a) => a.type))].map((type) => {
      const siennes = aVoir.filter((a) => a.type === type);
      return siennes.length === 1 ? seule(siennes[0])
        : { genre: 'groupe', gravite: 'a_voir', type, alarmes: siennes, ton: tonAlarme(siennes[0]) };
    }),
    ...triees.filter((a) => !['grave', 'a_voir', 'info'].includes(a.gravite)).map(seule),
    ...grouperInfos(triees).map((g) => ({ genre: 'groupe', gravite: 'info', type: g.type, alarmes: g.alarmes, ton: g.ton })),
  ];
}

/** La ligne d'un groupe à voir : « Contexte lourd au repos ×3 · coord-livraison, Assistant » ; cibles sans doublon (agents, sinon équipes), dans l'ordre. */
export function resumeGroupeProblemes(groupe) {
  const cibles = [...new Set(groupe.alarmes.flatMap((a) => ((a.agents || []).length ? a.agents.map(nomAgent) : (a.equipes || []))))];
  const type = TYPES_ALARME[groupe.type] || groupe.type;
  return { mot: (GRAVITES[groupe.gravite] || GRAVITES.info).mot, type, nombre: groupe.alarmes.length, cibles,
    ligne: `${type} ×${groupe.alarmes.length}${cibles.length ? ` · ${cibles.join(', ')}` : ''}` };
}

/** Les `n` plus gros postes de consommation, du plus gros au plus petit ; un poste sans part connue passe après les autres. */
export function plusGrosPostes(postes, n = 3) {
  const part = (p) => (typeof p.part_15min === 'number' ? p.part_15min : -1);
  return postes.map((p, i) => ({ p, i })).sort((x, y) => part(y.p) - part(x.p) || x.i - y.i).slice(0, n).map((x) => x.p);
}

/** La largeur de la barre d'un poste en pour cent, bornée à 0–100 ; null si la part est inconnue (pas de barre, jamais 0). */
export function largeurBarre(part) {
  return typeof part === 'number' && Number.isFinite(part) ? Math.min(100, Math.max(0, part * 100)) : null;
}

// ---------------------------------------------------------------------------
// Source, état courant et actions
// ---------------------------------------------------------------------------
let source = null;
let etatCourant = null;
let rerendre = () => {};

/** Branche le socle sur la couche de données et sur la fonction qui réaffiche l'écran. */
export function brancher(src, reafficher) {
  source = src;
  rerendre = reafficher;
}

/** Attentes dont l'action est en cours d'appel : leurs boutons restent désactivés. */
const enCours = new Set();
/** L'image est figée (l'hôte ne répond plus) : les boutons d'action sont désactivés. La scène le met à jour. */
let actionsFigees = false;
export const PHRASE_ACTIONS_FIGEES = 'L’hôte ne répond plus';
export const actionsSontFigees = () => actionsFigees;
export function definirActionsFigees(fige) {
  actionsFigees = Boolean(fige);
}
/** Attentes dont l'action a reçu « ok » : « envoyé » jusqu'au prochain instantané. */
const envoyees = new Set();

/** Un nouvel instantané est arrivé : c'est lui qui dit ce qui a été pris en compte. */
export function nouvelInstantane() {
  const avait = envoyees.size > 0;
  envoyees.clear();
  return avait;
}

/** Les attentes de l'instantané (null si inconnues). L'hôte retire lui-même celles qui sont traitées. */
export function attentesOuvertes(etat) {
  return Array.isArray(etat.attentes_utilisateur) ? etat.attentes_utilisateur : null;
}

export const attenteEnvoyee = (id) => envoyees.has(id);
export const attenteEnCours = (id) => enCours.has(id);
export const MOT_ENVOYEE = 'envoyé, en attente de confirmation';

/**
 * Exécute une prérogative de l'utilisateur. `ok` → toast, l'attente reste affichée
 * « envoyé, en attente de confirmation » jusqu'au prochain instantané ;
 * `refuse` → toast ambre ; `erreur` ou échec réseau → toast rouge, l'attente
 * reste et on peut réessayer. Renvoie la réponse { resultat, message }.
 */
export async function agir({ action, attente, corps, cible, details = {} }) {
  if (enCours.has(attente.id) || envoyees.has(attente.id)) return { resultat: 'erreur', message: 'action déjà en cours' };
  enCours.add(attente.id);
  rerendre();
  let reponse;
  try {
    reponse = await source.agir(action, corps, { cible, details: { attente: attente.id, ...details } });
  } catch (e) {
    reponse = { resultat: 'erreur', message: e.message };
  }
  enCours.delete(attente.id);
  if (reponse.resultat === 'ok') envoyees.add(attente.id);
  toast(action, cible, reponse);
  rerendre();
  return reponse;
}

// ---------------------------------------------------------------------------
// Le mode autonome : une prérogative de l'utilisateur, exécutée sans confirmation
// ---------------------------------------------------------------------------
/** Au-delà, l'interrupteur cesse d'attendre l'instantané qui montrera le nouveau réglage et revient à ce que dit l'état. */
export const ATTENTE_MODE_MS = 15_000;
let modeEnCours = null; // { valeur: 'active' | 'inactive', requete: vrai tant que l'hôte n'a pas répondu }
let focusAMode = false; // le clavier était sur l'interrupteur : il y revient quand l'attente prend fin (un bouton désactivé perd le focus)

/** La valeur en cours d'envoi (ou d'attente de l'instantané), ou null : l'interrupteur est alors désactivé. */
export const modeDemande = () => (modeEnCours ? modeEnCours.valeur : null);

/** Le réglage demandé figure-t-il dans l'instantané ? (Réactiver un mode suspendu : actif et plus suspendu.) */
const modeAtteint = (valeur, etat) => lireMode(etat).etat === (valeur === 'active' ? 'actif' : 'inactif');

/** Active ou désactive le mode autonome. Refus ou échec : un toast avec la raison de l'hôte, l'interrupteur reprend sa position. */
export async function basculerMode(valeur) {
  if (modeEnCours || actionsFigees) return;
  const demande = { valeur, requete: true };
  const avaitLeFocus = Boolean(document.activeElement && document.activeElement.classList && document.activeElement.classList.contains('inter'));
  modeEnCours = demande;
  rerendre();
  let reponse;
  try {
    reponse = await source.agir('fusions_auto', { valeur }, { cible: 'projet', details: { valeur } });
  } catch (e) {
    reponse = { resultat: 'erreur', message: e.message };
  }
  if (reponse.resultat === 'ok') {
    demande.requete = false; // l'interrupteur attend l'instantané qui montre le réglage
    focusAMode = avaitLeFocus;
    annoncer(TOASTS[valeur]);
    setTimeout(() => { if (modeEnCours === demande) { modeEnCours = null; rerendre(); retrouverFocusMode(); } }, ATTENTE_MODE_MS);
  } else {
    modeEnCours = null;
    annoncer(phraseEchec(reponse), reponse.resultat === 'refuse' ? 'ambre' : 'rouge');
  }
  rerendre();
  retrouverFocusMode();
}

/** Le rail se redessine : l'interrupteur touché y est un nouvel élément, le clavier doit le retrouver (sauf s'il est allé ailleurs entre-temps). */
function retrouverFocusMode() {
  const actif = document.activeElement;
  if (actif && actif !== document.body && !(actif.classList && actif.classList.contains('inter'))) return;
  const inters = [...document.querySelectorAll('.inter')];
  if (inters.length) inters[inters.length - 1].focus();
}

/** Un instantané qui montre le réglage demandé met fin à l'attente. */
function rapprocherMode(etat) {
  if (modeEnCours && !modeEnCours.requete && modeAtteint(modeEnCours.valeur, etat)) {
    modeEnCours = null;
    if (focusAMode) {
      focusAMode = false;
      requestAnimationFrame(retrouverFocusMode); // après le dessin de la page
    }
  }
}

/** Ce qu'un dialogue affiche quand l'action n'a pas abouti. */
function phraseEchec(r) {
  return r.resultat === 'refuse'
    ? `Refusé : ${r.message || 'sans motif donné'}.`
    : `Échec : ${r.message || 'erreur inconnue'}. Rien n’a changé, tu peux réessayer.`;
}

/** Un toast d'une phrase (le mode autonome) : `ton` 'ok' | 'ambre' | 'rouge'. */
export function annoncer(texte, ton = 'ok') {
  poserToast(el('div', { class: ton === 'ok' ? 'toast' : `toast toast-${ton}` }, texte), ton === 'ok' ? 5000 : 10000);
}

function toast(action, cible, reponse) {
  let t;
  if (reponse.resultat === 'ok') {
    const heure = new Date(source.horloge.maintenant()).toLocaleTimeString('fr-FR', { hour12: false });
    t = el('div', { class: 'toast' },
      'Inscrit au journal · ', el('span', { class: 'mono' }, `${heure} · utilisateur · ${action} · ${cible} · ok`));
  } else {
    t = el('div', { class: `toast toast-${reponse.resultat === 'refuse' ? 'ambre' : 'rouge'}` }, phraseEchec(reponse));
  }
  poserToast(t, reponse.resultat === 'ok' ? 5000 : 10000);
}

function poserToast(t, dureeMs) {
  let pile = document.querySelector('.toasts');
  if (!pile) {
    pile = el('div', { class: 'toasts', role: 'status', 'aria-live': 'polite', popover: 'manual' });
    document.body.append(pile);
  }
  // en couche supérieure, comme les feuilles : un toast ne passe jamais dessous (re-montré, il repasse au-dessus)
  try {
    if (pile.matches(':popover-open')) pile.hidePopover();
    pile.showPopover();
  } catch { /* navigateur sans popover : le toast reste dans la page */ }
  pile.append(t);
  setTimeout(() => t.remove(), dureeMs);
}

// ---------------------------------------------------------------------------
// Dialogues
// ---------------------------------------------------------------------------
/** Ouvre un dialogue modal ; `contenu(fermer)` renvoie ses nœuds. */
export function ouvrirDialogue(titre, contenu) {
  const dialogue = el('dialog', { 'aria-label': titre });
  const fermer = () => dialogue.close();
  dialogue.addEventListener('close', () => dialogue.remove());
  dialogue.append(el('div', { class: 'dialogue' }, el('h2', {}, titre), contenu(fermer)));
  document.body.append(dialogue);
  dialogue.showModal();
  return dialogue;
}

/**
 * Une feuille : un <dialog> modal qui monte du bas de l'écran (70 % de la hauteur) ou le couvre (`pleinEcran`). Elle se ferme par
 * sa poignée, son bouton « Fermer », Échap (le <dialog> s'en charge) et un clic sur le voile ; `surFermeture()` est appelée
 * dans tous les cas. `contenu` : des nœuds. Renvoie { dialogue, fermer, remplacer(...noeuds), retitrer(texte) } : un contenu
 * qui vit (les attentes, un détail) se remplace sur place sans fermer la feuille. La tête est toujours le titre et « Fermer ».
 */
export function feuille(titre, contenu, { pleinEcran = false, surFermeture = null } = {}) {
  const corps = el('div', { class: 'feuille-contenu' }, contenu);
  const intitule = el('h2', {}, titre);
  const dialogue = el('dialog', { class: `feuille ${pleinEcran ? 'feuille-plein' : 'feuille-montante'}`, 'aria-label': titre, 'aria-modal': 'true' });
  const fermer = () => { if (dialogue.open) dialogue.close(); };
  dialogue.addEventListener('close', () => {
    dialogue.remove();
    if (surFermeture) surFermeture();
  });
  dialogue.addEventListener('click', (ev) => { if (ev.target === dialogue) fermer(); }); // le voile : hors du cadre
  dialogue.append(el('div', { class: 'feuille-cadre' },
    el('button', { type: 'button', class: 'feuille-poignee', 'aria-label': 'Fermer', onclick: fermer },
      el('span', { class: 'feuille-barre', 'aria-hidden': 'true' })),
    el('header', { class: 'feuille-tete' }, intitule,
      el('button', { type: 'button', class: 'bouton feuille-fermer', onclick: fermer }, 'Fermer')),
    corps));
  document.body.append(dialogue);
  dialogue.showModal();
  return {
    dialogue,
    fermer,
    remplacer: (...noeuds) => vider(corps, ...noeuds),
    retitrer: (texte) => { vider(intitule, texte); dialogue.setAttribute('aria-label', texte); },
  };
}

// ---------------------------------------------------------------------------
// Les attentes de l'utilisateur : leurs cartes et leurs boutons (le rail de la scène les montre)
// ---------------------------------------------------------------------------
function agentDemandeur(attente) {
  return el('span', {}, 'demandé par ', mono(nomAgent(attente.agent)));
}

function actionsAttente(attente, ctx) {
  if (envoyees.has(attente.id)) return [el('p', { class: 'attente-envoyee' }, MOT_ENVOYEE)];
  const occupe = enCours.has(attente.id) || actionsFigees;
  const titre = actionsFigees ? PHRASE_ACTIONS_FIGEES : null;
  const corps = { attente_id: attente.id };
  switch (attente.nature) {
    case 'autorisation': {
      const agent = ((ctx.etat && ctx.etat.agents) || []).find((a) => a.id === attente.agent);
      if (!agent || !agent.session_tmux) {
        return [el('p', { class: 'attente-terminal' }, 'Réponds dans son terminal : la page ne peut pas y envoyer de touche.')];
      }
      const details = { agent: attente.agent, demande: attente.titre };
      return [
        el('button', { type: 'button', class: 'bouton bouton-vert', disabled: occupe, title: titre,
          onclick: () => agir({ action: 'autoriser', attente, corps, cible: attente.id, details }) }, 'Autoriser'),
        el('button', { type: 'button', class: 'bouton', disabled: occupe, title: titre,
          onclick: () => dialogueRefuser(attente, () => agir({ action: 'refuser', attente, corps, cible: attente.id, details })) }, 'Refuser'),
      ];
    }
    case 'decision': {
      const accord = accordDe(attente);
      if (accord) {
        return [
          el('button', { type: 'button', class: 'bouton bouton-principal', disabled: occupe, title: titre, onclick: () => dialogueAccorder(attente, accord) }, accord.bouton),
          el('button', { type: 'button', class: 'bouton', disabled: occupe, title: titre, onclick: () => dialogueRefuserAccord(attente, accord) }, 'Refuser'),
        ];
      }
      return [el('button', { type: 'button', class: 'bouton bouton-principal', disabled: occupe, title: titre, onclick: () => dialogueTrancher(attente) }, 'Trancher')];
    }
    case 'donnee': {
      const champ = el('input', { type: 'file', multiple: true, disabled: occupe, title: titre, 'aria-label': `Déposer des fichiers : ${attente.titre}` });
      champ.addEventListener('change', () => {
        const fichiers = [...champ.files];
        if (fichiers.length) {
          agir({ action: 'deposer', attente, corps: { attente_id: attente.id, fichiers }, cible: attente.id,
            details: { fichiers: fichiers.map((f) => f.name) } });
        }
      });
      return [el('label', { class: `bouton bouton-principal bouton-fichier${occupe ? ' occupe' : ''}`, title: titre }, 'Déposer des fichiers', champ)];
    }
    case 'cloture':
      return [el('button', { type: 'button', class: 'bouton', disabled: occupe, title: titre, onclick: () => dialogueCloturer(attente) }, 'Clôturer…')];
    case 'rapport':
      return [el('button', { type: 'button', class: 'bouton', disabled: occupe, title: titre, onclick: () => dialogueLire(attente, ctx) }, 'Lire')];
    default:
      return [];
  }
}

/** Refuser arrête l'agent : la page le dit avant d'agir (« Autoriser » reste en un clic). */
export const PHRASE_REFUS = 'Refuser arrête l’agent jusqu’à ce que l’Assistant le relance. Confirmer ?';

function dialogueRefuser(attente, refuser) {
  ouvrirDialogue(attente.titre, (fermer) => [
    el('p', {}, PHRASE_REFUS),
    el('div', { class: 'dialogue-actions' },
      el('button', { type: 'button', class: 'bouton', onclick: fermer }, 'Annuler'),
      el('button', { type: 'button', class: 'bouton bouton-danger', onclick: () => { refuser(); fermer(); } }, 'Refuser')),
  ]);
}

/**
 * Formulaire de dialogue qui attend la réponse : fermé sur `ok`, sinon il reste
 * ouvert avec le motif (la saisie n'est pas perdue) et l'on peut réessayer.
 */
function formulaireAction({ fermer, bouton, valide, executer }, ...contenu) {
  const echec = el('p', { class: 'texte-erreur', role: 'alert', hidden: true });
  return el('form', { method: 'dialog', class: 'dialogue', style: 'padding: 0',
    onsubmit: async (e) => {
      e.preventDefault();
      if (!valide()) return;
      bouton.disabled = true;
      const r = await executer();
      if (r.resultat === 'ok') { fermer(); return; }
      echec.textContent = phraseEchec(r);
      echec.hidden = false;
      bouton.disabled = !valide();
    } },
  contenu, echec);
}

/**
 * Les accords que l’Assistant demande à l'utilisateur (prérogative de l’utilisateur, jamais d’un agent) : une décision
 * dont l’objet est `fusion:<équipe>:<commit>` ou `chantier:<équipe>:<phase>`. La page inscrit l’accord
 * ou le refus ; elle ne touche à aucune branche, l’Assistant coordonne la suite.
 */
const ACCORDS = [
  { prefixe: 'fusion:', bouton: 'Accorder la fusion', detail: 'Commit' },
  { prefixe: 'chantier:', bouton: 'Accorder le chantier', detail: 'Phase' },
];

export function accordDe(attente) {
  if (attente.nature !== 'decision' || typeof attente.objet !== 'string') return null;
  if (!Array.isArray(attente.actions) || !attente.actions.includes('accorder')) return null;
  const accord = ACCORDS.find((a) => attente.objet.startsWith(a.prefixe));
  if (!accord) return null;
  const [, equipe = '?', reste = '?'] = attente.objet.split(':');
  return { ...accord, equipe, reste };
}

function dialogueAccorder(attente, accord) {
  ouvrirDialogue(attente.titre, (fermer) => {
    const bouton = el('button', { type: 'submit', class: 'bouton bouton-principal' }, accord.bouton);
    return formulaireAction({ fermer, bouton,
      valide: () => true,
      executer: () => agir({ action: 'accorder', attente, corps: { attente_id: attente.id },
        cible: attente.id, details: { objet: attente.objet } }) },
    el('p', {}, 'Équipe ', mono(accord.equipe), ' · ', accord.detail, ' ', mono(accord.reste)),
    el('p', {}, 'Ton accord est inscrit au registre, en ton nom. Cette page ne touche à aucune branche : l’Assistant coordonne la suite.'),
    el('div', { class: 'dialogue-actions' },
      el('button', { type: 'button', class: 'bouton', onclick: fermer }, 'Annuler'), bouton));
  });
}

function dialogueRefuserAccord(attente, accord) {
  ouvrirDialogue(attente.titre, (fermer) => {
    const champ = el('input', { type: 'text', required: true, maxlength: '160', autocomplete: 'off',
      placeholder: 'Pourquoi, en une ligne' });
    const bouton = el('button', { type: 'submit', class: 'bouton bouton-danger', disabled: true }, 'Refuser');
    champ.addEventListener('input', () => { bouton.disabled = !champ.value.trim(); });
    return formulaireAction({ fermer, bouton,
      valide: () => Boolean(champ.value.trim()),
      executer: () => agir({ action: 'refuser', attente, corps: { attente_id: attente.id, motif: champ.value.trim() },
        cible: attente.id, details: { objet: attente.objet, motif: champ.value.trim() } }) },
    el('p', {}, 'Équipe ', mono(accord.equipe), ' · ', accord.detail, ' ', mono(accord.reste)),
    el('label', {}, 'Motif du refus', champ),
    el('div', { class: 'dialogue-actions' },
      el('button', { type: 'button', class: 'bouton', onclick: fermer }, 'Annuler'), bouton));
  });
}

function dialogueTrancher(attente) {
  ouvrirDialogue(attente.titre, (fermer) => {
    const champ = el('textarea', { required: true, placeholder: 'Ta décision, en une ou deux phrases' });
    const bouton = el('button', { type: 'submit', class: 'bouton bouton-principal', disabled: true }, 'Trancher');
    champ.addEventListener('input', () => { bouton.disabled = !champ.value.trim(); });
    return formulaireAction({ fermer, bouton,
      valide: () => Boolean(champ.value.trim()),
      executer: () => agir({ action: 'trancher', attente, corps: { attente_id: attente.id, reponse: champ.value.trim() },
        cible: attente.id, details: { question: attente.titre, choix: champ.value.trim() } }) },
    attente.bloque ? el('p', {}, 'Bloque : ', attente.bloque) : null,
    el('label', {}, 'Ta décision', champ),
    el('div', { class: 'dialogue-actions' },
      el('button', { type: 'button', class: 'bouton', onclick: fermer }, 'Annuler'), bouton));
  });
}

/**
 * L'équipe qu'une attente vise : celle que l'hôte donne (`attente.equipe`) quand elle est
 * connue, rien d'autre. Repli pour un instantané plus ancien ou une valeur nulle : l'équipe de l'agent
 * demandeur, sinon celle que le titre nomme.
 */
export function equipeDeLAttente(attente, etat = etatCourant) {
  if (typeof attente.equipe === 'string' && attente.equipe) return attente.equipe;
  const agent = ((etat && etat.agents) || []).find((a) => a.id === attente.agent);
  if (agent && agent.equipe) return agent.equipe;
  const trouve = /équipe\s+(\S+)/i.exec(attente.titre || '');
  return trouve ? trouve[1] : null;
}

/** Dialogue de clôture, commun au rail de la scène et à la page d'une équipe : retaper le nom de l'équipe. */
export function dialogueCloturer(attente) {
  const equipe = equipeDeLAttente(attente);
  ouvrirDialogue(attente.titre, (fermer) => {
    const champ = el('input', { type: 'text', autocomplete: 'off', spellcheck: 'false' });
    const bouton = el('button', { type: 'submit', class: 'bouton bouton-danger', disabled: true }, 'Clôturer l’équipe');
    champ.addEventListener('input', () => { bouton.disabled = champ.value !== equipe; });
    return formulaireAction({ fermer, bouton,
      valide: () => Boolean(equipe) && champ.value === equipe,
      executer: () => agir({ action: 'cloturer', attente, corps: { equipe, confirmation: champ.value },
        cible: `equipe:${equipe}`, details: { demande: attente.id } }) },
    el('p', {}, 'L’équipe ', mono(equipe || '?'), ' quittera le tableau des équipes actives et rejoindra les archives. Sa branche et son travail restent intacts.'),
    el('label', {}, el('span', {}, 'Pour confirmer, retape le nom de l’équipe : ', mono(equipe || '?')), champ),
    el('div', { class: 'dialogue-actions' },
      el('button', { type: 'button', class: 'bouton', onclick: fermer }, 'Annuler'), bouton));
  });
}

/**
 * Une demande de l’utilisateur pour l’Assistant : la seule conversation que la page héberge.
 * Un acte de coordination ne part jamais ailleurs que chez lui : l’hôte impose le destinataire.
 */
export function dialogueDemander() {
  ouvrirDialogue('Demander à l’Assistant', (fermer) => {
    const champ = el('input', { type: 'text', required: true, maxlength: '160', autocomplete: 'off',
      placeholder: 'Ta demande, en une ligne' });
    const bouton = el('button', { type: 'submit', class: 'bouton bouton-principal', disabled: true }, 'Demander à l’Assistant');
    champ.addEventListener('input', () => { bouton.disabled = !champ.value.trim(); });
    return formulaireAction({ fermer, bouton,
      valide: () => Boolean(champ.value.trim()),
      executer: async () => {
        const texte = champ.value.trim();
        let reponse;
        try {
          reponse = await source.agir('demander', { texte }, { cible: 'assistant', details: { texte } });
        } catch (e) {
          reponse = { resultat: 'erreur', message: e.message };
        }
        toast('demander', 'assistant', reponse);
        return reponse;
      } },
    el('label', {}, 'Ta demande', champ),
    el('div', { class: 'dialogue-actions' },
      el('button', { type: 'button', class: 'bouton', onclick: fermer }, 'Annuler'), bouton));
  });
}

function dialogueLire(attente, ctx) {
  const message = Array.isArray(ctx.etat.fil) ? ctx.etat.fil.find((m) => m.id === attente.id) : null;
  ouvrirDialogue(attente.titre, (fermer) => {
    const zone = el('div', { class: 'rapport-texte' }, el('p', { class: 'discret' }, 'Lecture du compte rendu…'));
    source.texteRapport(message).then(
      (t) => vider(zone, rendreTexte(t)),
      (e) => vider(zone, el('p', { class: 'texte-erreur' }, `Compte rendu illisible : ${e.message}.`)));
    return [
      zone,
      el('div', { class: 'dialogue-actions' },
        el('button', { type: 'button', class: 'bouton', onclick: fermer }, 'Fermer'),
        el('button', { type: 'button', class: 'bouton bouton-principal',
          onclick: () => {
            agir({ action: 'lu', attente, corps: { attente_id: attente.id }, cible: attente.id,
              details: { rapport: message && message.fichier } });
            fermer();
          } }, 'Marquer comme lu')),
    ];
  });
}

/** Une attente : une carte resserrée (genre, titre, âge et demandeur, boutons). */
export function carteAttente(attente, ctx) {
  const complet = attente.bloque ? `${attente.titre} — bloque : ${attente.bloque}` : attente.titre;
  return el('article', { class: 'attente', dataset: { nature: attente.nature, attente: attente.id, envoyee: envoyees.has(attente.id) ? 'oui' : null } },
    el('div', { class: 'etiquette' }, NATURES_ATTENTE[attente.nature] || attente.nature),
    el('div', { class: 'attente-texte', title: complet },
      el('span', { class: 'attente-titre' }, attente.titre),
      attente.bloque ? el('span', { class: 'attente-bloque' }, ' bloque : ', attente.bloque) : null),
    el('div', { class: 'attente-meta' }, joindre([
      age(attente.depuis, 'depuis'), agentDemandeur(attente),
      typeof attente.equipe === 'string' && attente.equipe ? ['équipe ', lienEquipe(attente.equipe)] : null,
    ], ' · ')),
    el('div', { class: 'attente-actions' }, actionsAttente(attente, ctx)));
}

// ---------------------------------------------------------------------------
// En-tête unique (56 px, tous les écrans)
// ---------------------------------------------------------------------------
export function resumeAgents(etat) {
  if (!Array.isArray(etat.agents)) return inconnu(sourceEnEchec(etat, 'structure'), 'agents inconnus');
  const terminees = new Set((etat.equipes || []).filter((q) => q.statut === 'terminee').map((q) => q.nom));
  const compte = {};
  for (const a of etat.agents) {
    if (a.role === 'utilisateur' || terminees.has(a.equipe) || workerTermine(a, etat.alarmes)) continue;
    const def = defEtatAgent(a, etat.alarmes);
    const famille = def.cle.startsWith('attend') ? 'attend' : def.cle === 'arrete' ? (def.ton === 'rouge' ? 'arrete' : 'a_l_arret') : def.cle;
    compte[famille] = (compte[famille] || 0) + 1;
  }
  const ton = compte.arrete ? 'rouge' : compte.attend ? 'ambre' : 'vert';
  const phrase = libelleEffectifs(compte); // le texte est masqué sous 1 240 px : le point le redit en title et aria-label
  return el('span', { class: `pilule ton-${ton}`, role: 'img', title: phrase, 'aria-label': phrase },
    el('span', { class: 'etat' }, el('span', { class: 'pastille', 'aria-hidden': 'true' })),
    el('span', { class: 'effectifs-texte' }, phrase));
}

function niveauAge(ms) {
  return ms > AGE_DONNEE_ROUGE_MS ? 'rouge' : 'ok';
}

/**
 * L'âge de la donnée affichée. Un flux muet ou en erreur passe au rouge même
 * si le dernier instantané reçu était frais : il ne sera plus remplacé.
 */
function rafraichirAgeDonnee(noeud) {
  const ms = source.horloge.ageDonnee();
  const interrompu = source.fluxInterrompu();
  const niveau = interrompu ? 'rouge' : niveauAge(ms);
  noeud.dataset.niveau = niveau;
  noeud.dataset.flux = interrompu ? 'interrompu' : 'ok';
  const age = `instantané reçu il y a ${duree(ms)}`;
  const version = etatCourant ? ` · instantané v${etatCourant.version} · collecté en ${etatCourant.duree_collecte_ms} ms` : '';
  noeud.title = interrompu ? `plus aucune nouvelle de l’hôte : la page se reconnecte seule · ${age}${version}` : `${age}${version}`;
  const mot = { ok: 'En direct', rouge: 'Figé' }[niveau];
  vider(noeud, el('span', { class: 'pouls', 'aria-hidden': 'true' }), mot,
    niveau === 'ok' ? null : [' · ', el('span', { class: 'chiffres' }, duree(ms))]);
}

/** ⚠ n : les sources en échec, regroupées ; leurs libellés sont dans l'info-bulle. */
function iconeSources(etat) {
  const echecs = sourcesEnEchec(etat);
  if (!echecs.length) return null;
  const libelles = echecs.map((s) => SOURCES_EN_ECHEC[s.nom] || `${s.nom} en échec`).join(' · ');
  return el('button', { type: 'button', class: 'sources-echec', title: `${pluriel(echecs.length, 'source dégradée', 'sources dégradées')} : ${libelles}`,
    'aria-label': pluriel(echecs.length, 'source en échec', 'sources en échec') }, `⚠ ${echecs.length}`);
}

/** « n point(s) t'attend(ent) » en clair, renvoie à la scène où ils sont tous ; absent s'il n'y en a pas. */
function compteurAttentes(etat) {
  const attentes = attentesOuvertes(etat);
  if (!attentes || !attentes.length) return null;
  const phrase = `${pluriel(attentes.length, 'point')} ${attentes.length === 1 ? 't’attend' : 't’attendent'}`;
  return el('a', { class: 'compteur-attentes', href: '#/', title: 'Voir ce qui t’attend sur la scène' }, phrase);
}

/** « Autonome » (bleu) ou « Autonome suspendu » (ambre), seulement quand le mode est actif ; « Auto » / « Suspendu » quand la place manque. Un clic mène à la scène. */
export function pastilleAutonome(etat) {
  const mode = lireMode(etat);
  if (mode.etat === 'inactif') return null;
  const mots = PASTILLE[mode.etat];
  return el('a', { class: `pastille-auto ${mode.etat}`, href: '#/', title: titrePastille(mode),
    onclick: () => { if (location.hash === '#/' || location.hash === '') document.querySelector('.rail')?.scrollIntoView?.({ block: 'start' }); } },
  el('span', { class: 'pastille-long' }, mots.long), el('span', { class: 'pastille-court' }, mots.court));
}

/** L'en-tête unique : marque et projet · onglets · état (effectifs, direct, sources, attentes) · bouton de la demande. */
function entete(ctx) {
  return el('header', { class: 'entete' },
    el('div', { class: 'entete-titres' },
      el('span', { class: 'entete-appli' }, 'Cime'),
      el('h1', {}, ctx.etat.projet ? ctx.etat.projet.nom : 'projet inconnu')),
    el('nav', { class: 'nav', 'aria-label': 'Pages' },
      PAGES.map((p) => el('a', { href: p.href, 'aria-current': p.id === ctx.page ? 'page' : null }, p.titre))),
    el('div', { class: 'entete-etat' },
      resumeAgents(ctx.etat),
      el('span', { class: 'pilule age-donnee' }),
      iconeSources(ctx.etat),
      pastilleAutonome(ctx.etat),
      compteurAttentes(ctx.etat),
      el('button', { type: 'button', class: 'bouton demander', title: TITRE_DEMANDER, 'aria-label': 'Demander à l’Assistant', onclick: dialogueDemander },
        icone('bulle', 'demander-icone'), el('span', { class: 'demander-texte' }, 'Demander à l’Assistant'))));
}

// ---------------------------------------------------------------------------
// Largeur (vérification du débordement horizontal)
// ---------------------------------------------------------------------------
export function mesurerLargeur() {
  requestAnimationFrame(() => {
    document.documentElement.dataset.largeur = String(document.documentElement.scrollWidth);
  });
}

// ---------------------------------------------------------------------------
// Montage
// ---------------------------------------------------------------------------
/**
 * Rend le socle d'un écran dans <body>. `ctx` = { etat, page } ; le complète
 * de `horloge`, `contenu` (l'élément <main> où l'écran rend son propre contenu)
 * et `tic`. `page` : 'scene' | 'supervision' | 'fil' | 'journal' | 'archives' | 'equipe'.
 */
export function rendreSocle(ctx) {
  clearInterval(minuteurInjoignable);
  etatCourant = ctx.etat;
  rapprocherMode(ctx.etat);
  ctx.horloge = source.horloge;
  ctx.tic = tic;
  if (ctx.etat.projet) document.title = `${ctx.etat.projet.nom} · Cime`;

  const contenu = el('main', { class: 'page-contenu', style: 'display: contents' });
  const racine = el('div', { class: 'page' }, entete(ctx),
    el('div', { class: `page-corps${ctx.page === 'scene' ? ' sur-scene' : ''}` }, contenu));
  // un dialogue ouvert (saisie en cours) et les toasts survivent au nouvel instantané
  for (const n of [...document.body.children]) {
    if (n.tagName !== 'DIALOG' && !n.classList.contains('toasts')) n.remove();
  }
  document.body.prepend(racine);
  ctx.contenu = contenu;
  return ctx;
}

const rappelsTic = new Set();
/** Un écran qui vit à la seconde (l'image figée de la scène) s'accroche ici plutôt que d'ouvrir son propre minuteur. */
export function surTic(rappel) {
  rappelsTic.add(rappel);
}

/** Chaque seconde : l'âge de la donnée, les âges de la page, les attentes en retard. */
export function tic() {
  const noeud = document.querySelector('.age-donnee');
  if (noeud && source) rafraichirAgeDonnee(noeud);
  if (source) rafraichirAges(document.body, source.horloge.maintenant());
  colorierAttentes();
  for (const rappel of rappelsTic) rappel();
}

export function demarrerTic() {
  tic();
  setInterval(tic, 1000);
  window.addEventListener('resize', mesurerLargeur);
  if (document.fonts) document.fonts.ready.then(mesurerLargeur);
}

let minuteurInjoignable = null;

/**
 * Au chargement, si l'hôte ne répond pas : une page lisible, jamais une page blanche. Même en-tête que le reste
 * de la page (sans onglets), une carte, le décompte jusqu'au prochain essai.
 */
export function rendreInjoignable({ essai, erreur, delai }) {
  clearInterval(minuteurInjoignable);
  document.title = 'Hôte injoignable · Cime';
  const reste = el('p', { class: 'injoignable-reessai' });
  const fin = performance.now() + (delai || 0);
  const decompter = () => {
    const secondes = Math.max(0, Math.ceil((fin - performance.now()) / 1000));
    vider(reste, `Nouvel essai dans ${secondes} s.`);
  };
  vider(document.body, el('div', { class: 'page' },
    el('header', { class: 'entete' },
      el('div', { class: 'entete-titres' }, el('span', { class: 'entete-appli' }, 'Cime')),
      el('div', { class: 'entete-etat' },
        el('span', { class: 'pilule age-donnee', dataset: { niveau: 'rouge' } }, el('span', { class: 'pouls', 'aria-hidden': 'true' }), 'Hôte injoignable'))),
    el('main', { class: 'injoignable' },
      el('div', { class: 'injoignable-carte', role: 'alert',
        title: `Rien n’est affiché tant que l’hôte ne répond pas : une page vide ne prouverait pas que tout va bien.${erreur ? ` (essai n° ${essai} : ${erreur})` : ''}` },
        el('span', { class: 'injoignable-icone', 'aria-hidden': 'true' }),
        el('p', { class: 'injoignable-phrase' }, 'Cime n’arrive pas à joindre l’hôte.'),
        delai ? reste : null))));
  if (delai) {
    decompter();
    minuteurInjoignable = setInterval(decompter, 1000);
  }
  mesurerLargeur();
}
