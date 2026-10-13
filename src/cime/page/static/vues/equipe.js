// Cime — détail d'une équipe : agents, terminal en lecture seule, périmètre
// confronté aux fichiers touchés, dépendances, alarmes, échanges, clôture.

import {
  el, vider, mono, inconnu, age, pluriel, nomAgent, carteAgent, puceStatut, ligneFil, carteAlarme,
  alarmesDe, attentesOuvertes, equipeDeLAttente, sourceEnEchec, lienEquipe as lien,
  routeFil, mesurerLargeur, joindre, statutEquipeAffiche, GRAVITES, workerTermine,
  carteAttente, defEtatAgent, pastilleEtat, attenteDe, alarmeRouge,
} from '../commun.js';
import { trierAttentes } from './rail.js';

/** Le terminal affiché est relu toutes les 5 s, seulement si l'onglet du navigateur est visible. */
export const TERMINAL_PERIODE_MS = 5_000;

let ctx = null;
let etat = null;
let equipes = null;
const section = (titre, sousTitre, ...corps) => el('section', { class: 'section' },
  el('div', { class: 'section-tete' }, el('h2', {}, titre), sousTitre ? el('span', { class: 'sous-titre' }, sousTitre) : null),
  corps);

function introuvable(raison) {
  ctx.contenu.append(el('section', { class: 'section' },
    el('div', { class: 'inconnu-bloc' },
      el('h1', { style: 'margin: 0 0 6px; font-size: 20px' }, 'Équipe introuvable'),
      el('p', { style: 'margin: 0 0 10px' }, raison),
      el('a', { href: '#/supervision' }, '← Supervision'))));
  document.title = 'Équipe introuvable · Cime';
  mesurerLargeur();
}

/** Rend le détail de l'équipe `ctx.route.nom` ; renvoie la fonction qui arrête la lecture du terminal. */
export function rendre(contexte) {
  ctx = contexte;
  etat = ctx.etat;
  equipes = etat.equipes;
  terminal = null; // le rendu précédent n'est plus dans la page
  const nom = ctx.route.nom;
  const equipe = Array.isArray(equipes) && nom ? equipes.find((q) => q.nom === nom) : null;
  if (!Array.isArray(equipes)) {
    introuvable('La liste des équipes est inconnue : la source de la structure est en échec (voir l’en-tête).');
  } else if (!equipe) {
    introuvable(nom ? ['Aucune équipe ne s’appelle ', mono(nom), ' dans cet instantané.'] : 'Aucune équipe n’est indiquée dans l’adresse.');
  } else {
    monterPage(equipe);
  }
  return arreterTerminal;
}

function monterPage(q) {
  const terminee = q.statut === 'terminee';
  const def = statutEquipeAffiche(q, etat.alarmes);
  document.title = `${q.nom} · ${etat.projet ? etat.projet.nom : 'Cime'}`;
  const agents = (etat.agents || []).filter((a) => a.equipe === q.nom);

  // l'ordre est celui de ce que veut l'utilisateur : ce qui l'attend, ses agents, le terminal, ce qui s'est dit, ce qui coince ;
  // le périmètre et les dépendances (outils de contrôle de l'Assistant) viennent en dernier, repliés
  ctx.contenu.append(el('div', { class: 'fiche' }, ...[
    enTete(q, def, terminee),
    sectionAttentes(q),
    sectionAgents(q, agents, terminee),
    sectionTerminal(q, agents, terminee),
    sectionEchanges(q, agents),
    sectionAlarmes(q),
    sectionPerimetre(q),
    sectionDependances(q)].filter(Boolean)));
  ctx.tic();
  mesurerLargeur();
}

// ---------------------------------------------------------------------------
function enTete(q, def, terminee) {
  const a = q.avancement;
  const total = a ? a.faites + a.en_cours + a.a_faire : 0;
  const part = (n) => (total ? `${(100 * n) / total}%` : '0');
  const base = etat.projet ? etat.projet.branche_reference : 'la base';
  let retard;
  if (q.retard_sur_base === null || q.retard_sur_base === undefined) retard = inconnu(sourceEnEchec(etat, 'git'), 'inconnu');
  else if (q.retard_sur_base === 0) retard = `à jour sur ${base}`;
  else retard = `${pluriel(q.retard_sur_base, 'commit')} de retard sur ${base}`;
  let avance;
  if (q.en_avance_sur_base === null || q.en_avance_sur_base === undefined) {
    avance = q.branche ? inconnu(sourceEnEchec(etat, 'git'), 'inconnu') : 'pas de branche';
  } else if (q.en_avance_sur_base === 0) avance = `rien d’avance sur ${base}`;
  else avance = `${pluriel(q.en_avance_sur_base, 'commit')} pas encore dans ${base}`;

  return el('header', { class: `eq-tete ton-${def.ton}` },
    el('div', { class: 'eq-titre' },
      el('h1', {}, q.nom),
      puceStatut(q.statut, def),
      q.speciale ? el('span', { class: 'discret' }, 'équipe spéciale · à la demande') : null,
      el('a', { href: '#/supervision', class: 'lien-suite' }, '← Supervision')),
    el('p', { class: 'eq-mission' }, q.mission),
    terminee ? el('div', { class: 'eq-note' }, 'Équipe clôturée : ses agents sont arrêtés, il n’y a plus de terminal à regarder. Sa branche et son travail restent intacts.') : null,
    el('div', { class: 'eq-faits' },
      el('div', { class: 'eq-fait' }, el('span', { class: 'eq-cle' }, 'Branche et commit'),
        q.branche ? el('span', {}, mono(q.branche), ' · ', mono(q.commit || 'commit inconnu')) : inconnu(null, 'branche inconnue')),
      el('div', { class: 'eq-fait' }, el('span', { class: 'eq-cle' }, 'Avancement'),
        a ? [el('span', {}, `${a.faites} faites · ${a.en_cours} en cours · ${a.a_faire} à faire`),
          el('div', { class: 'eq-barre', role: 'img', 'aria-label': `${a.faites} faites sur ${total}` },
            el('span', { class: 'faites', style: `width: ${part(a.faites)}` }),
            el('span', { class: 'en-cours', style: `width: ${part(a.en_cours)}` }))]
          : inconnu(sourceEnEchec(etat, 'structure'), 'avancement inconnu')),
      el('div', { class: 'eq-fait' }, el('span', { class: 'eq-cle' }, 'Retard sur la base'), el('span', {}, retard)),
      el('div', { class: 'eq-fait' }, el('span', { class: 'eq-cle' }, 'Avance sur la base'), el('span', {}, avance))));
}

// ---------------------------------------------------------------------------
/**
 * Les agents de l'équipe, séparés : les vivants (coordinateur d'abord), les workers terminés (le plus récent d'abord).
 * Pure : ni le tableau reçu ni les agents ne sont modifiés.
 */
export function grouperAgents(agents, alarmes) {
  const rang = (a) => (a.role === 'coordinateur' ? 0 : 1);
  const termines = agents.filter((a) => workerTermine(a, alarmes))
    .sort((x, y) => (Date.parse(y.etat_depuis) || 0) - (Date.parse(x.etat_depuis) || 0));
  const vivants = agents.filter((a) => !termines.includes(a)).sort((x, y) => rang(x) - rang(y));
  return { vivants, termines };
}

/** Le résumé du repli des workers terminés : « + 3 workers terminés ». */
export const resumeTermines = (n) => `+ ${n} ${n === 1 ? 'worker terminé' : 'workers terminés'}`;

/** Ce qui attend l'utilisateur pour cette équipe, dans l'ordre du rail ; null si les attentes sont inconnues. Une équipe spéciale ou clôturée n'a pas de clôture à prononcer. */
export function attentesDeLEquipe(etat, q) {
  const ouvertes = attentesOuvertes(etat);
  if (ouvertes === null) return null;
  return trierAttentes(ouvertes.filter((a) => equipeDeLAttente(a, etat) === q.nom
    && !(a.nature === 'cloture' && (q.speciale || q.statut === 'terminee'))));
}

function sectionAttentes(q) {
  const attentes = attentesDeLEquipe(etat, q);
  if (attentes === null) {
    return section('Attend de toi', null, el('div', { class: 'inconnu-bloc' }, 'Ce qui t’attend : inconnu (sources en échec, voir l’en-tête).'));
  }
  if (!attentes.length) return null; // rien n'attend l'utilisateur : la section n'a pas à exister
  return section('Attend de toi', pluriel(attentes.length, 'point'),
    el('div', { class: 'attentes' }, attentes.map((a) => carteAttente(a, { etat }))));
}

function carteAvecBrouillon(a, terminee) {
  return [
    carteAgent(a, ctx, { detail: true, equipeTerminee: terminee }),
    a.brouillon ? el('div', { class: 'eq-brouillon' },
      joindre([el('strong', {}, 'Brouillon resté dans le terminal'), age(a.brouillon.depuis, 'depuis')], ' · '),
      el('p', {}, a.brouillon.texte)) : null,
  ];
}

/** Un agent vivant : une ligne (nom, état, tâche, depuis quand) ; la carte complète (contexte, coût, consommation, brouillon) s'ouvre dessous. */
function ligneAgent(a, terminee) {
  const def = defEtatAgent(a, etat.alarmes, { equipeTerminee: terminee });
  const grave = alarmesDe(etat.alarmes, { agent: a.id }).some(alarmeRouge);
  const attend = attenteDe(a.id, etat.fil);
  return el('details', { class: `eq-agent ton-${def.ton}`, dataset: { agent: a.id, alarme: grave ? 'grave' : null } },
    el('summary', {},
      el('span', { class: 'agent-nom' }, nomAgent(a.id)),
      pastilleEtat(def.cle, def),
      el('span', { class: a.tache ? 'eq-agent-tache' : 'eq-agent-tache discret', title: a.tache || null }, a.tache || 'aucune tâche déclarée'),
      el('span', { class: 'eq-agent-notes' },
        attend ? el('span', { class: 'eq-agent-attend' }, attend.qui === 'utilisateur' ? 't’attend' : `attend ${nomAgent(attend.qui)}`) : null,
        a.brouillon ? el('span', { class: 'eq-agent-attend' }, 'brouillon') : null,
        a.etat_depuis ? age(a.etat_depuis, 'depuis') : null)),
    el('div', { class: 'eq-agent-corps' }, carteAvecBrouillon(a, terminee)));
}

/** Un worker terminé, une ligne : son nom, sa tâche rendue, et il y a combien de temps. */
function ligneTerminee(a) {
  return el('li', { class: 'eq-termine' },
    el('span', { class: 'eq-termine-nom' }, nomAgent(a.id)),
    el('span', { class: a.tache ? 'eq-termine-tache' : 'eq-termine-tache discret', title: a.tache || null }, a.tache || 'aucune tâche déclarée'),
    a.etat_depuis ? age(a.etat_depuis, 'il-y-a', 'terminé ') : null);
}

function sectionAgents(q, agents, terminee) {
  const { vivants, termines } = grouperAgents(agents, etat.alarmes);
  const aCoordinateur = agents.some((a) => a.role === 'coordinateur');
  let corps;
  if (!agents.length) {
    corps = el('div', { class: 'inconnu-bloc' }, q.speciale ? 'Aucune session vue.' : 'Aucun agent de cette équipe dans l’instantané.',
      q.speciale ? ' Équipe à la demande : elle n’a pas de coordinateur tant qu’on ne la lance pas.' : null);
  } else if (!vivants.length) {
    corps = el('div', { class: 'vide-calme' }, 'Aucun agent en cours.');
  } else {
    corps = el('div', { class: 'eq-agents' }, vivants.map((a) => ligneAgent(a, terminee)));
  }
  // les workers terminés quittent la liste : une seule ligne repliée, qui les compte
  const repli = termines.length ? el('details', { class: 'eq-termines' },
    el('summary', {}, resumeTermines(termines.length)),
    el('ul', { class: 'eq-termines-liste' }, termines.map(ligneTerminee))) : null;
  return section('Ses agents', terminee ? 'équipe clôturée' : null,
    corps,
    repli,
    agents.length && !aCoordinateur ? el('div', { class: 'discret' }, 'Aucune session vue pour le coordinateur.') : null);
}

// ---------------------------------------------------------------------------
// Terminal en direct : la capture vient de la source, en lecture seule.
/** Agent dont le terminal est affiché, par équipe : le choix survit aux nouveaux instantanés. */
const terminalChoisi = new Map();
/** Dernière lecture, par agent : { texte, capture_a, lu_a } ou { erreur, lu_a }. */
const captures = new Map();
/** Le terminal du rendu courant, que la lecture périodique met à jour. */
let terminal = null;
let minuteur = null;

function lireTerminal() {
  if (!terminal || document.visibilityState !== 'visible') return;
  const id = terminalChoisi.get(terminal.equipe);
  ctx.source.terminal(id).then(
    (c) => captures.set(id, { texte: c.texte, capture_a: c.capture_a, lu_a: performance.now() }),
    (e) => captures.set(id, { erreur: e.message, lu_a: performance.now() }))
    .then(() => { if (terminal && terminalChoisi.get(terminal.equipe) === id) afficherTerminal(); });
}

function quandVisible() {
  if (document.visibilityState === 'visible') lireTerminal();
}

/** Arrête la lecture périodique (on quitte le détail de l'équipe). */
function arreterTerminal() {
  clearInterval(minuteur);
  minuteur = null;
  terminal = null;
  document.removeEventListener('visibilitychange', quandVisible);
}

function afficherTerminal() {
  const { pre, horodatage, choix, equipe } = terminal;
  const id = terminalChoisi.get(equipe);
  const c = captures.get(id);
  if (!c) {
    pre.textContent = '';
    vider(horodatage, 'lecture…');
  } else if (c.erreur) {
    pre.textContent = '';
    vider(horodatage, el('span', { class: 'texte-erreur' }, `terminal illisible : ${c.erreur}`));
  } else {
    // collé en bas (les dernières lignes), sauf si l'utilisateur est remonté lire plus haut
    const enBas = !pre.textContent || pre.scrollHeight - pre.scrollTop - pre.clientHeight < 24;
    if (pre.textContent !== c.texte) pre.textContent = c.texte;
    if (enBas) pre.scrollTop = pre.scrollHeight;
    vider(horodatage, age(c.capture_a, 'il-y-a', 'capturé '));
  }
  for (const b of choix.children) b.setAttribute('aria-pressed', String(b.dataset.agent === id));
  ctx.tic();
  mesurerLargeur();
}

function sectionTerminal(q, agents, terminee) {
  if (terminee) return null;
  const avecSession = ctx.source.agentsAvecTerminal(agents);
  // les workers terminés sont déjà comptés, repliés, dans « Ses agents » : on ne les redit pas ici
  const sans = agents.filter((a) => !avecSession.includes(a) && !workerTermine(a, etat.alarmes));
  // un coordinateur endormi n'est pas illisible : sa session est fermée volontairement, elle se rouvre au prochain message
  const dorment = sans.filter((a) => a.etat === 'endormi');
  const illisibles = sans.filter((a) => a.etat !== 'endormi');
  if (!avecSession.length) {
    return section('Terminal en direct', null,
      illisibles.length || !dorment.length ? el('div', { class: 'inconnu-bloc' }, phraseSansTerminal(q, agents, illisibles)) : null,
      dorment.length ? el('div', { class: 'agent-session endormi discret' }, phraseEndormis(dorment)) : null);
  }
  if (!avecSession.some((a) => a.id === terminalChoisi.get(q.nom))) terminalChoisi.set(q.nom, avecSession[0].id);

  const choix = el('div', { class: 'terminal-choix', role: 'group', 'aria-label': 'Choisir l’agent' });
  const pre = el('pre', { class: 'terminal', tabindex: '0', 'aria-label': 'Terminal, lecture seule' });
  const horodatage = el('span', {});
  const bloc = el('div', { class: 'terminal-bloc' },
    el('div', { class: 'terminal-barre' }, avecSession.length > 1 ? choix : mono(avecSession[0].id),
      el('span', { class: 'terminal-meta' }, el('span', { class: 'terminal-lecture' }, 'lecture seule'), horodatage)),
    pre);
  for (const a of avecSession) {
    choix.append(el('button', { type: 'button', dataset: { agent: a.id }, 'aria-pressed': 'false',
      onclick: () => { terminalChoisi.set(q.nom, a.id); afficherTerminal(); lireTerminal(); } }, nomAgent(a.id)));
  }
  terminal = { equipe: q.nom, pre, horodatage, choix };
  afficherTerminal();
  // relue tout de suite seulement si la dernière lecture date de plus d'une période
  const derniere = captures.get(terminalChoisi.get(q.nom));
  if (!derniere || performance.now() - derniere.lu_a >= TERMINAL_PERIODE_MS) lireTerminal();
  if (!minuteur) {
    minuteur = setInterval(lireTerminal, TERMINAL_PERIODE_MS);
    document.addEventListener('visibilitychange', quandVisible);
  }
  return section('Terminal en direct', 'rafraîchi toutes les 5 s',
    bloc,
    illisibles.length ? el('div', { class: 'discret' }, `Pas de terminal à afficher pour ${illisibles.map((a) => nomAgent(a.id)).join(', ')} : leur session n’est pas capturée.`) : null,
    dorment.length ? el('div', { class: 'agent-session endormi discret' }, phraseEndormis(dorment)) : null);
}

/** Pourquoi il n'y a pas de terminal : une phrase, selon ce qu'on sait de l'équipe. */
export function phraseSansTerminal(q, agents, sans) {
  if (!agents.length) return q.speciale ? 'Équipe à la demande, sans session : il n’y a pas de terminal tant qu’on ne la lance pas.' : 'Aucun agent vu pour cette équipe : il n’y a pas de terminal.';
  if (!sans.length) return 'Tous les agents de cette équipe ont terminé : il n’y a plus de session à regarder.';
  return 'Aucune session capturée en ce moment : les agents de cette équipe n’ont pas de session tmux lisible.';
}

/** Des coordinateurs endormis : ni illisibles ni en panne, leur session est fermée volontairement. Chacun dit depuis quand il dort. */
export function phraseEndormis(dorment) {
  const dort = dorment.map((a) => el('span', {}, nomAgent(a.id), ' dort', a.etat_depuis ? ' ' : '', age(a.etat_depuis, 'depuis')));
  return el('span', {}, joindre(dort, ' · '),
    dorment.length > 1 ? ' : ils se réveillent au prochain message.' : ' : il se réveille au prochain message.');
}

// ---------------------------------------------------------------------------
/** Un repli : un titre de même niveau que les autres sections, dont la ligne de résumé dit l'essentiel sans l'ouvrir. */
const repli = (classe, resume, ...corps) => el('details', { class: `eq-repli ${classe}` },
  el('summary', {}, el('h2', {}, resume)),
  el('div', { class: 'eq-repli-corps' }, corps));

/** Les fichiers touchés (hors périmètre compris) et combien sont hors du périmètre. Pure. */
export function fichiersDe(q) {
  const hors = new Set(q.hors_perimetre || []);
  const touches = q.fichiers_touches || [];
  const fichiers = [...touches, ...[...hors].filter((f) => !touches.includes(f))];
  return { fichiers, hors, nbHors: fichiers.filter((f) => hors.has(f)).length };
}

/** La ligne du repli « Périmètre » : « Périmètre : 2 chemins · 3 fichiers touchés » (au singulier : « 1 chemin · 1 fichier touché ») (+ « · 1 hors périmètre »). Pure. */
export function resumePerimetre(q) {
  if (!Array.isArray(q.fichiers_touches) || !Array.isArray(q.perimetre_declare)) return 'Périmètre : inconnu';
  const { fichiers, nbHors } = fichiersDe(q);
  const ligne = `Périmètre : ${pluriel(q.perimetre_declare.length, 'chemin')} · ${pluriel(fichiers.length, 'fichier touché', 'fichiers touchés')}`;
  return nbHors ? `${ligne} · ${nbHors} hors périmètre` : ligne;
}

function sectionPerimetre(q) {
  const declare = q.perimetre_declare;
  const touches = q.fichiers_touches;
  if (!Array.isArray(touches) || !Array.isArray(declare)) {
    return repli('eq-perimetre', resumePerimetre(q),
      el('div', { class: 'inconnu-bloc' }, 'Périmètre ou fichiers touchés inconnus : ', inconnu(sourceEnEchec(etat, 'git'), 'source en échec'), '.'));
  }
  const { fichiers, hors, nbHors } = fichiersDe(q);
  return repli('eq-perimetre', resumePerimetre(q),
    el('p', { class: 'discret' }, 'Ce que l’équipe a le droit de toucher, face à ce qu’elle a touché.'),
    nbHors
      ? el('div', { class: 'perim-alerte', role: 'alert' }, `⚠ ${pluriel(nbHors, 'fichier touché hors du périmètre déclaré', 'fichiers touchés hors du périmètre déclaré')}`)
      : el('div', { class: 'perim-ok' }, fichiers.length ? '✓ Tous les fichiers touchés sont dans le périmètre déclaré.' : 'Aucun fichier touché pour l’instant.'),
    el('div', { class: 'perim' },
      el('div', { class: 'perim-carte' }, el('h3', {}, 'Périmètre déclaré'),
        declare.length ? el('ul', { class: 'perim-liste' }, declare.map((p) => el('li', {}, p))) : el('span', { class: 'discret' }, 'aucun périmètre déclaré')),
      el('div', { class: 'perim-carte' }, el('h3', {}, `Fichiers touchés (${fichiers.length})`),
        fichiers.length ? el('ul', { class: 'perim-liste' }, fichiers.map((f) => {
          const h = hors.has(f);
          return el('li', { class: 'fichier', dataset: { hors: h ? 'oui' : 'non' } },
            el('span', { class: 'fichier-nom' }, f),
            el('span', { class: 'fichier-marque' }, h ? 'hors périmètre' : '✓ dans le périmètre'));
        })) : el('span', { class: 'discret' }, 'aucun fichier touché'))));
}

// ---------------------------------------------------------------------------
/** Les liens de l'équipe : de qui elle dépend (null si inconnu), qui elle alimente, et les équipes dont on ne sait rien. Pure. */
export function dependancesDe(q, equipesTout) {
  const autres = equipesTout.filter((x) => x.nom !== q.nom);
  return {
    dependDe: Array.isArray(q.depend_de) ? q.depend_de : null,
    alimente: autres.filter((x) => Array.isArray(x.depend_de) && x.depend_de.includes(q.nom)).map((x) => x.nom),
    incertaines: autres.filter((x) => !Array.isArray(x.depend_de)).map((x) => x.nom),
  };
}

/** La ligne du repli « Dépendances » : « Dépendances : 3 » (de qui elle dépend et qui elle alimente), « inconnues » sans la structure. Pure. */
export function resumeDependances(q, equipesTout) {
  const { dependDe, alimente } = dependancesDe(q, equipesTout);
  return dependDe === null ? 'Dépendances : inconnues' : `Dépendances : ${dependDe.length + alimente.length}`;
}

function sectionDependances(q) {
  const { dependDe, alimente, incertaines } = dependancesDe(q, equipes);
  const liste = (noms) => (noms.length ? el('ul', {}, noms.map((n) => el('li', {}, lien(n)))) : el('p', { class: 'discret', style: 'margin: 6px 0 0' }, 'aucune'));
  return repli('eq-dependances', resumeDependances(q, equipes), el('div', { class: 'liens-dep' },
    el('div', { class: 'perim-carte' }, el('h3', {}, 'Dépend de'),
      dependDe === null ? inconnu(sourceEnEchec(etat, 'structure'), 'inconnu') : liste(dependDe)),
    el('div', { class: 'perim-carte' }, el('h3', {}, 'Alimente'), liste(alimente),
      incertaines.length ? el('p', { class: 'discret', style: 'margin: 6px 0 0' }, 'Dépendances inconnues pour : ', incertaines.map((n, i) => [i ? ', ' : '', lien(n)])) : null)));
}

// ---------------------------------------------------------------------------
function sectionAlarmes(q) {
  if (!Array.isArray(etat.alarmes)) {
    return section('Ses alarmes', null, el('div', { class: 'inconnu-bloc' }, 'Alarmes inconnues : sources en échec (voir l’en-tête).'));
  }
  const rang = (a) => (GRAVITES[a.gravite] || GRAVITES.info).rang;
  const siennes = alarmesDe(etat.alarmes, { equipe: q.nom }).sort((x, y) => rang(x) - rang(y));
  return section('Ses alarmes', siennes.length ? pluriel(siennes.length, 'alarme') : null,
    siennes.length ? el('div', { class: 'alarmes' }, siennes.map(carteAlarme)) : el('div', { class: 'vide-calme' }, 'Aucune alarme pour cette équipe.'));
}

// ---------------------------------------------------------------------------
function sectionEchanges(q, agents) {
  const lienFil = el('a', { href: routeFil({ equipe: q.nom }), class: 'lien-suite' }, 'Tout le fil de cette équipe →');
  if (!Array.isArray(etat.fil)) {
    return section('Ses derniers échanges', null, el('div', { class: 'inconnu-bloc' }, 'Échanges inconnus : ', inconnu(sourceEnEchec(etat, 'registre'), 'registre en échec'), '.'), lienFil);
  }
  const ids = new Set(agents.map((a) => a.id));
  ids.add(`coord-${q.nom}`);
  const siens = etat.fil.filter((m) => ids.has(m.de) || ids.has(m.a))
    .sort((x, y) => Date.parse(y.horodatage) - Date.parse(x.horodatage)).slice(0, 10);
  return section('Ses derniers échanges', siens.length ? `${siens.length} derniers` : null,
    siens.length ? el('ol', { class: 'fil' }, siens.map(ligneFil)) : el('div', { class: 'vide-calme' }, 'Aucun échange avec cette équipe.'),
    lienFil);
}
