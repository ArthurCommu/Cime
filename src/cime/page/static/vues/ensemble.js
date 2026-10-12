// Cime — Supervision : depuis ta dernière visite, organigramme vivant et dépendances,
// ce qui coince, avancement du projet, consommation, puis les liens du pied.

import {
  el, vider, mono, inconnu, inconnuCourt, pluriel, puceStatut, pastilleEtat, routeEquipe,
  attentesOuvertes, attenteDe, sourceEnEchec, sourcesEnEchec, alarmesDe,
  mesurerLargeur, dateCourte, duree, ciblesAlarme, age, texteDepliable,
  joindre, statutEquipeAffiche, equipeALArret, STATUT_EQUIPE_A_L_ARRET, alarmeRouge, defEtatAgent, GRAVITES, TYPES_ALARME, tonAlarme, motAlarme,
  CONTEXTE_CHAUD, jetonsOuInconnu, pourcent, nomAgent, workerTermine,
  grouperAlarmes, resumeGroupeInfos, resumeGroupeProblemes, equipeEnRetrait, lienEquipe, plusGrosPostes, largeurBarre,
  cleVisite, derniereVisite,
} from '../commun.js';
import {
  lireMode, decisionsAVoir, resumeDecisions, PHRASE_RECAP, LIBELLE_DECISIONS,
} from '../autonome.js';
import { detailDecisions, etatDecisions } from './decisions.js';

/** Le graphe se redispose quand sa largeur change ; un seul observateur à la fois. */
let observateurGraphe = null;
/** « Depuis ta dernière visite » : null tant que l'utilisateur n'a pas ouvert ou replié le bloc. */
let nouveautesOuvert = null;
/** Le détail des décisions de l'Assistant : replié d'office ; ce que l'utilisateur en a ouvert reste ouvert d'un instantané à l'autre (propre à la Supervision). */
const decisionsVue = etatDecisions();
let visiteSuivie = false;
/** Le contexte du rendu en cours (instantané, journal, horloge…). */
let ctx = null;
let etat = null;

function equipesActives() {
  return Array.isArray(etat.equipes) ? etat.equipes.filter((q) => q.statut !== 'terminee') : null;
}

function enteteSection(titre, sousTitre, ...extra) {
  return el('div', { class: 'section-tete' },
    el('h2', {}, titre), sousTitre ? el('span', { class: 'sous-titre' }, sousTitre) : null, extra);
}

// ---------------------------------------------------------------------------
// 1. Depuis ta dernière visite
// ---------------------------------------------------------------------------
/** La sortie de la Supervision : c'est elle seule qui mémorise la visite (la Scène lit `derniereVisite`, sans l'écrire). */
function memoriserVisite() {
  try { localStorage.setItem(cleVisite(etat), String(Math.floor(ctx.horloge.maintenant()))); } catch { /* rien */ }
}

function lignesNouveautes(visite) {
  const apres = (iso) => iso && Date.parse(iso) > visite.instant;
  const lignes = [];

  if (!Array.isArray(etat.fil)) {
    lignes.splice(lignes.length, 0, el('li', {}, 'Échanges : ', inconnu(sourceEnEchec(etat, 'registre'))));
  } else {
    const nouveaux = etat.fil.filter((m) => apres(m.horodatage));
    const questions = nouveaux.filter((m) => m.nature === 'question' && m.en_attente).length;
    if (nouveaux.length) {
      lignes.splice(lignes.length, 0, el('li', {}, pluriel(nouveaux.length, 'échange'),
        questions ? `, dont ${pluriel(questions, 'question encore sans réponse', 'questions encore sans réponse')}` : ''));
    }
  }

  if (!Array.isArray(etat.alarmes)) {
    lignes.splice(lignes.length, 0, el('li', {}, 'Alarmes : ', inconnu(null, 'inconnues (sources en échec)')));
  } else {
    const nouvelles = etat.alarmes.filter((a) => apres(a.depuis));
    const graves = nouvelles.filter(alarmeRouge).length;
    if (nouvelles.length) {
      lignes.splice(lignes.length, 0, el('li', { class: graves ? 'rouge' : '' },
        `${pluriel(nouvelles.length, 'nouvelle alarme', 'nouvelles alarmes')}`,
        graves ? `, dont ${pluriel(graves, 'grave', 'graves')}` : ''));
    }
  }

  const arretes = (etat.agents || []).filter((a) => a.etat === 'arrete' && a.vivant === false && apres(a.etat_depuis)
    && defEtatAgent(a, etat.alarmes).ton === 'rouge');
  if (arretes.length) {
    lignes.splice(lignes.length, 0, el('li', { class: 'rouge' },
      `${pluriel(arretes.length, 'agent arrêté', 'agents arrêtés')} : `, arretes.map((a, i) => [i ? ', ' : '', mono(a.id)])));
  }

  const attentes = attentesOuvertes(etat);
  const nouvellesAttentes = attentes ? attentes.filter((a) => apres(a.depuis)).length : 0;
  if (nouvellesAttentes) {
    lignes.splice(lignes.length, 0, el('li', {},
      `${pluriel(nouvellesAttentes, 'nouveau point', 'nouveaux points')} ${nouvellesAttentes === 1 ? 't’attend' : 't’attendent'}`));
  }

  const actions = (ctx.journal || []).filter((l) => apres(l.horodatage)).length;
  if (actions) lignes.splice(lignes.length, 0, el('li', {}, `${pluriel(actions, 'action inscrite', 'actions inscrites')} au journal`));

  // le récap de ce que l'Assistant a décidé ne compte pas dans les 5 lignes : il vient en tête
  const recap = ligneRecap(visite);
  return recap ? [recap, ...lignes.slice(0, 5)] : lignes.slice(0, 5);
}

/** La première ligne : ce que l'Assistant a décidé à la place de l'utilisateur depuis sa dernière visite (toutes les décisions, sans visite mémorisée). */
function ligneRecap(visite) {
  const decisions = decisionsAVoir(lireMode(etat).decisions, visite.instant, visite.memorisee);
  if (!decisions.length) return null;
  return el('li', { class: 'nouveaute-recap' },
    el('b', {}, PHRASE_RECAP), ` : ${resumeDecisions(decisions)}`, detailDecisions(decisions, decisionsVue, LIBELLE_DECISIONS, mesurerLargeur));
}

function sectionNouveautes() {
  const visite = derniereVisite(etat);
  const lignes = lignesNouveautes(visite);
  // ouvert d'office s'il y a du grave (lignes en rouge) ou des décisions de l'Assistant à lire
  const grave = lignes.some((l) => l.classList.contains('rouge') || l.classList.contains('nouveaute-recap'));
  const details = el('details', { class: 'nouveautes', open: nouveautesOuvert === null ? grave : nouveautesOuvert },
    el('summary', {},
      el('span', { class: 'nouveautes-titre' }, 'Depuis ta dernière visite'),
      el('span', { class: 'discret' },
        ` · sur ce navigateur, il y a ${duree(ctx.horloge.maintenant() - visite.instant)}`,
        visite.memorisee ? '' : ' (première visite : les 3 dernières heures)'),
      el('span', { class: 'nouveautes-nombre' },
        lignes.length ? ` · ${pluriel(lignes.length, 'changement')}` : ' · rien de nouveau')),
    lignes.length ? el('ul', { class: 'nouveautes-liste' }, lignes) : null);
  details.addEventListener('toggle', () => { nouveautesOuvert = details.open; mesurerLargeur(); });
  return details;
}

// ---------------------------------------------------------------------------
// 2a. Organigramme : la tête Utilisateur → Assistant, puis la grille des équipes
// ---------------------------------------------------------------------------
function noeudUtilisateur() {
  const attentes = attentesOuvertes(etat);
  const n = attentes ? attentes.length : null;
  return el('div', { class: 'org-utilisateur' },
    el('span', { class: 'org-nom' }, 'Utilisateur'),
    n ? el('a', { class: 'org-utilisateur-attentes', href: '#/' }, `${pluriel(n, 'point')} ${n === 1 ? 't’attend' : 't’attendent'}`)
      : el('span', { class: 'secondaire' }, n === null ? 'ce qui t’attend : inconnu' : 'rien ne t’attend'));
}

/** La jauge de contexte, fine : 56 px, verte, ambre si le contexte est lourd. */
function jaugeFine(agent) {
  const c = agent.contexte;
  if (!c || !c.limite) return el('span', { class: 'org-jauge' }, inconnuCourt('contexte', sourceEnEchec(etat, 'transcripts')));
  const part = c.tokens / c.limite;
  return el('span', { class: 'org-jauge', dataset: { chaud: part > CONTEXTE_CHAUD ? 'oui' : 'non' }, title: `contexte ${pourcent(part)}` },
    'contexte', el('i', {}, el('b', { style: `width: ${Math.min(100, Math.round(part * 100))}%` })), pourcent(part));
}

function noeudAssistant() {
  if (!Array.isArray(etat.agents)) {
    return el('div', { class: 'org-assistant' }, inconnu(sourceEnEchec(etat, 'structure'), 'Assistant inconnu'));
  }
  const a = etat.agents.find((x) => x.role === 'assistant');
  if (!a) return el('div', { class: 'org-assistant' }, inconnu(null, 'Assistant introuvable'));
  const def = defEtatAgent(a, etat.alarmes);
  const attend = attenteDe(a.id, etat.fil);
  return el('div', { class: 'org-assistant' },
    el('span', { class: 'org-nom' }, nomAgent(a.id)),
    el('span', { class: 'org-etat' }, pastilleEtat(def.cle, def),
      a.etat_depuis ? el('span', { class: 'org-etat-age' }, age(a.etat_depuis, 'court')) : null),
    attend ? el('span', { class: 'org-attend' },
      attend.qui === 'utilisateur' ? 't’attend ' : `attend ${nomAgent(attend.qui)} `, age(attend.depuis, 'depuis')) : null,
    jaugeFine(a),
    a.derniere_phrase ? el('span', { class: 'org-phrase', title: a.derniere_phrase }, a.derniere_phrase) : null);
}

function avancement(q) {
  const a = q.avancement;
  if (!a) return inconnu(sourceEnEchec(etat, 'structure'), 'avancement inconnu');
  const total = a.faites + a.en_cours + a.a_faire;
  const part = total ? Math.round((a.faites / total) * 100) : 0;
  return el('div', { class: 'org-avance' },
    el('div', { class: 'org-barre', role: 'img', 'aria-label': `${a.faites} tâches faites sur ${total}` },
      el('b', { style: `width: ${part}%` })),
    total ? el('span', {}, `${a.faites} / ${total}`) : el('span', {}, '0 tâche'));
}

/** Ce qui est dit sous un agent : l'alarme grave qui le cite, sinon l'attente (ambre), sinon une alarme à voir, sinon sa tâche — jamais une info. */
function quoiAgent(a) {
  const alarmes = alarmesDe(etat.alarmes, { agent: a.id }).sort((x, y) => (GRAVITES[x.gravite] || GRAVITES.info).rang - (GRAVITES[y.gravite] || GRAVITES.info).rang);
  const alarme = alarmes.find(alarmeRouge);
  const autre = alarmes.find((x) => x.gravite !== 'info'); // jamais une info : la ligne dirait « Retard sur la branche de base » au lieu de la tâche
  const attend = attenteDe(a.id, etat.fil);
  if (alarme) return el('span', { class: `ag-quoi ton-${tonAlarme(alarme)}`, title: alarme.mesure }, TYPES_ALARME[alarme.type] || alarme.type);
  if (attend) {
    return el('span', { class: 'ag-quoi ton-ambre' },
      attend.qui === 'utilisateur' ? 't’attend ' : `attend ${nomAgent(attend.qui)} `, age(attend.depuis, 'depuis'));
  }
  if (autre) return el('span', { class: `ag-quoi ton-${tonAlarme(autre)}`, title: autre.mesure }, TYPES_ALARME[autre.type] || autre.type);
  return a.tache ? el('span', { class: 'ag-quoi', title: a.tache }, a.tache) : null;
}

/** Une ligne par agent vivant : puce d'état, identifiant, âge, et dessous la tâche ou l'alarme qui le cite. */
function ligneAgent(a, q) {
  const def = defEtatAgent(a, etat.alarmes, { equipeTerminee: q.statut === 'terminee' });
  return el('div', { class: `ag ton-${def.ton}${def.cle === 'inconnu' ? ' etat-inconnu' : ''}`, dataset: { agent: a.id, etat: def.cle } },
    el('span', { class: 'pastille', 'aria-hidden': 'true' }, def.cle === 'inconnu' ? '?' : null),
    el('span', { class: 'ag-id', title: `${a.id} · ${def.mot}` }, a.id),
    el('span', { class: 'ag-age' }, a.etat_depuis ? age(a.etat_depuis, 'court') : inconnu(null, '?')),
    quoiAgent(a));
}

function agentsEquipe(q) {
  if (!Array.isArray(etat.agents)) return { vivants: null, termines: 0 };
  const siens = etat.agents.filter((a) => a.equipe === q.nom);
  const termines = siens.filter((a) => workerTermine(a, etat.alarmes));
  const vivants = siens.filter((a) => !termines.includes(a));
  return { vivants: [...vivants.filter((a) => a.role === 'coordinateur'), ...vivants.filter((a) => a.role !== 'coordinateur')], termines: termines.length };
}

function blocEquipe(q) {
  const { vivants, termines } = agentsEquipe(q);
  const graves = alarmesDe(etat.alarmes, { equipe: q.nom }).filter(alarmeRouge);
  const arret = equipeALArret(q, etat.agents, etat.alarmes);
  const def = arret ? STATUT_EQUIPE_A_L_ARRET : statutEquipeAffiche(q, etat.alarmes);
  return el('a', { class: `org-equipe ton-${def.ton}${arret ? ' a-l-arret' : ''}`, href: routeEquipe(q.nom), dataset: { alarme: graves.length ? 'grave' : null } },
    el('div', { class: 'org-equipe-tete' },
      el('span', { class: 'org-equipe-nom' }, q.nom, q.speciale ? el('span', { class: 'org-speciale' }, ' · spéciale') : null),
      puceStatut(q.statut, def)),
    el('p', { class: 'org-equipe-mission', title: q.mission }, q.mission),
    avancement(q),
    graves.length ? el('div', { class: 'agent-alerte' }, `⚠ ${pluriel(graves.length, 'alarme grave', 'alarmes graves')}`) : null,
    el('div', { class: 'org-agents' },
      vivants === null ? inconnu(sourceEnEchec(etat, 'structure'), 'agents inconnus')
        : vivants.length ? vivants.map((a) => ligneAgent(a, q)) : el('span', { class: 'discret' }, 'aucun agent en cours')),
    termines ? el('span', { class: 'org-termines' }, `+ ${termines} ${termines === 1 ? 'worker terminé' : 'workers terminés'}`) : null);
}

/** La ligne sous la grille : les équipes spéciales sans session, puis le seul lien vers les équipes clôturées, avec leur compte. */
function ligneLiens(retraits) {
  const cloturees = Array.isArray(etat.equipes) ? etat.equipes.filter((q) => q.statut === 'terminee').length : null;
  return el('p', { class: 'org-liens' },
    joindre([
      retraits.map((q, i) => [i ? ', ' : '', lienEquipe(q.nom), ' (spéciale, sans session)']),
      el('a', { href: '#/archives' }, cloturees === null ? 'Équipes clôturées →' : `${pluriel(cloturees, 'équipe clôturée', 'équipes clôturées')} →`),
    ], ' · '));
}

function organigramme() {
  const actives = equipesActives();
  const retraits = actives ? actives.filter((q) => equipeEnRetrait(q, etat.agents, etat.alarmes)) : [];
  const cartes = actives ? actives.filter((q) => !retraits.includes(q)) : [];
  return el('div', { class: 'organigramme' },
    el('div', { class: 'org-tete' }, noeudUtilisateur(), noeudAssistant()),
    actives === null
      ? el('div', { class: 'inconnu-bloc' }, 'Équipes : ', inconnu(sourceEnEchec(etat, 'structure'), 'inconnues'))
      : cartes.length ? el('div', { class: 'org-equipes' }, cartes.map(blocEquipe))
        : retraits.length ? null : el('p', { class: 'vide-calme' }, 'Aucune équipe pour l’instant.'),
    ligneLiens(retraits));
}

// ---------------------------------------------------------------------------
// 2b. Dépendances (traits en éléments HTML positionnés)
// ---------------------------------------------------------------------------
const BOITE_LARGEUR_MAX = 220;
const ECART_X = 28;
const ECART_RANGEE = 72;
const COULOIR = 18;
const PAS_HORIZONTAL = 9;

function pairesRecouvrement() {
  if (!Array.isArray(etat.alarmes)) return [];
  return etat.alarmes.filter((a) => a.type === 'recouvrement' && (a.equipes || []).length >= 2).map((a) => a.equipes);
}

function memeFichier(a, b) {
  return pairesRecouvrement().some((p) => p.includes(a) && p.includes(b));
}

/** Niveaux : les équipes sans dépendance en haut ; A dépend de B → A sous B. */
function calculerGraphe(equipes) {
  const noms = new Set(equipes.map((q) => q.nom));
  const deps = new Map(equipes.map((q) => [q.nom,
    Array.isArray(q.depend_de) ? q.depend_de.filter((n) => noms.has(n) && n !== q.nom) : []]));
  const niveau = new Map();
  const calcul = (nom, pile = new Set()) => {
    if (niveau.has(nom)) return niveau.get(nom);
    if (pile.has(nom)) return 0; // cycle : on coupe
    pile.add(nom);
    const n = deps.get(nom).reduce((m, d) => Math.max(m, calcul(d, pile) + 1), 0);
    pile.delete(nom);
    niveau.set(nom, n);
    return n;
  };
  equipes.forEach((q) => calcul(q.nom));
  const aretes = [];
  for (const q of equipes) {
    for (const d of deps.get(q.nom)) {
      aretes.splice(aretes.length, 0, { de: d, vers: q.nom, rouge: memeFichier(d, q.nom) });
    }
  }
  return { niveau, aretes };
}

function boiteEquipe(q) {
  const graves = alarmesDe(etat.alarmes, { equipe: q.nom }).filter(alarmeRouge);
  const def = statutEquipeAffiche(q, etat.alarmes);
  const ton = def.ton;
  const a = q.avancement;
  const total = a ? a.faites + a.en_cours + a.a_faire : 0;
  return el('a', { class: `graphe-boite ton-${ton}`, href: routeEquipe(q.nom),
    dataset: { equipe: q.nom, alarme: graves.length ? 'grave' : null } },
    el('span', { class: 'mono graphe-nom' }, q.nom),
    el('span', { class: 'graphe-statut' }, def.mot,
      a ? el('span', { class: 'discret' }, ` · ${a.faites}/${total} faites`) : null),
    a ? el('span', { class: 'jauge-barre' }, el('span', { class: 'jauge-plein', style: `display: block; width: ${total ? Math.round((a.faites / total) * 100) : 0}%` })) : null,
    graves.length ? el('span', { class: 'graphe-alerte' }, `⚠ ${pluriel(graves.length, 'alarme grave', 'alarmes graves')}`) : null,
    q.depend_de === null ? el('span', { class: 'inconnu', style: 'font-size: 11px' }, `dépendances inconnues (${sourceEnEchec(etat, 'structure') || 'source'} en échec)`) : null);
}

function segment(zone, x, y, largeur, hauteur, rouge) {
  zone.append(el('div', { class: `arete${rouge ? ' rouge' : ''}`,
    style: `left: ${x}px; top: ${y}px; width: ${Math.max(2, largeur)}px; height: ${Math.max(2, hauteur)}px` }));
}

function fleche(zone, x, y, sens, rouge) {
  zone.append(el('div', { class: `fleche-${sens}${rouge ? ' rouge' : ''}`, style: `left: ${x}px; top: ${y}px` }));
}

function etiquetteMemeFichier(zone, x, y) {
  zone.append(el('div', { class: 'arete-etiquette', style: `left: ${x}px; top: ${y}px` }, 'même fichier'));
}

function disposer(zone, equipes, graphe) {
  zone.querySelectorAll('.arete, .arete-etiquette, [class^="fleche-"]').forEach((n) => n.remove());
  const largeur = zone.clientWidth;
  if (!largeur) return;
  const rangees = [];
  for (const q of equipes) {
    const n = graphe.niveau.get(q.nom);
    rangees[n] = [...(rangees[n] || []), q.nom];
  }
  // ordre dans une rangée : barycentre des fournisseurs déjà placés
  const ordre = new Map();
  rangees.forEach((rangee, r) => {
    if (!rangee) return;
    const poids = (nom) => {
      const sources = graphe.aretes.filter((a) => a.vers === nom).map((a) => ordre.get(a.de)).filter((v) => v !== undefined);
      return sources.length ? sources.reduce((s, v) => s + v, 0) / sources.length : rangee.indexOf(nom);
    };
    rangee.sort((a, b) => poids(a) - poids(b)).forEach((nom, i) => ordre.set(nom, i));
    rangees[r] = rangee;
  });

  // les plus courtes des longues arêtes prennent les couloirs les plus proches
  const portee = (a) => graphe.niveau.get(a.vers) - graphe.niveau.get(a.de);
  const longues = graphe.aretes.filter((a) => portee(a) > 1)
    .sort((a, b) => portee(a) - portee(b) || graphe.niveau.get(a.de) - graphe.niveau.get(b.de));
  const zoneCouloirs = longues.length ? longues.length * COULOIR + 24 : 0;
  const maxParRangee = Math.max(...rangees.map((r) => (r ? r.length : 0)));
  const boiteL = Math.min(BOITE_LARGEUR_MAX, (largeur - zoneCouloirs - (maxParRangee - 1) * ECART_X) / maxParRangee);
  const largeurBoites = maxParRangee * boiteL + (maxParRangee - 1) * ECART_X;
  // boîtes et couloirs forment un bloc centré
  const marge = Math.max(0, (largeur - largeurBoites - zoneCouloirs) / 2);
  const utile = marge + largeurBoites;

  const boites = new Map([...zone.querySelectorAll('.graphe-boite')].map((b) => [b.dataset.equipe, b]));
  const pos = new Map();
  let haut = 0;
  const basRangee = [];
  const hautRangee = [];
  rangees.forEach((rangee, r) => {
    if (!rangee) return;
    const total = rangee.length * boiteL + (rangee.length - 1) * ECART_X;
    let x = marge + (largeurBoites - total) / 2;
    let hMax = 0;
    for (const nom of rangee) {
      const b = boites.get(nom);
      b.style.width = `${boiteL}px`;
      b.style.left = `${x}px`;
      b.style.top = `${haut}px`;
      const h = b.offsetHeight;
      pos.set(nom, { x, y: haut, l: boiteL, h, r });
      hMax = Math.max(hMax, h);
      x += boiteL + ECART_X;
    }
    hautRangee[r] = haut;
    basRangee[r] = haut + hMax;
    haut += hMax + ECART_RANGEE;
  });
  zone.style.height = `${haut - ECART_RANGEE + 8}px`;

  // arêtes courtes : sortie en bas de la source, entrée en haut de la cible
  const courtes = graphe.aretes.filter((a) => !longues.includes(a) && graphe.niveau.get(a.vers) > graphe.niveau.get(a.de));
  const repartir = (liste, cle, autre) => {
    const groupes = new Map();
    for (const a of liste) groupes.set(a[cle], [...(groupes.get(a[cle]) || []), a]);
    const places = new Map();
    for (const [nom, aretes] of groupes) {
      const p = pos.get(nom);
      aretes.sort((a, b) => pos.get(a[autre]).x - pos.get(b[autre]).x)
        .forEach((a, i) => places.set(a, p.x + (p.l * (i + 1)) / (aretes.length + 1)));
    }
    return places;
  };
  const sorties = repartir(courtes, 'de', 'vers');
  const entrees = repartir(courtes, 'vers', 'de');
  const parInterstice = new Map();
  courtes.forEach((a) => {
    const r = pos.get(a.de).r;
    const rang = parInterstice.get(r) || 0;
    parInterstice.set(r, rang + 1);
    const s = pos.get(a.de);
    const c = pos.get(a.vers);
    const x1 = sorties.get(a);
    const x2 = entrees.get(a);
    const yMilieu = Math.min(basRangee[r] + 14 + rang * PAS_HORIZONTAL, c.y - 16);
    segment(zone, x1 - 1, s.y + s.h, 2, yMilieu - (s.y + s.h), a.rouge);
    if (Math.abs(x1 - x2) > 1) segment(zone, Math.min(x1, x2) - 1, yMilieu - 1, Math.abs(x1 - x2) + 2, 2, a.rouge);
    segment(zone, x2 - 1, yMilieu, 2, c.y - yMilieu - 6, a.rouge);
    fleche(zone, x2 - 5, c.y - 7, 'bas', a.rouge);
    if (a.rouge) etiquetteMemeFichier(zone, x2 + 8, (yMilieu + c.y) / 2 - 9);
  });

  // arêtes longues : par un couloir à droite, de flanc à flanc
  const decalage = (liste, a, cle) => {
    const freres = liste.filter((b) => b[cle] === a[cle]);
    return (freres.indexOf(a) - (freres.length - 1) / 2) * 8;
  };
  longues.forEach((a, k) => {
    const s = pos.get(a.de);
    const c = pos.get(a.vers);
    const xc = utile + 18 + k * COULOIR;
    const y1 = s.y + s.h / 2 + decalage(longues, a, 'de');
    const y2 = c.y + c.h / 2 + decalage(longues, a, 'vers');
    segment(zone, s.x + s.l, y1 - 1, xc - (s.x + s.l), 2, a.rouge);
    segment(zone, xc - 1, y1 - 1, 2, y2 - y1 + 2, a.rouge);
    segment(zone, c.x + c.l + 6, y2 - 1, xc - (c.x + c.l + 6), 2, a.rouge);
    fleche(zone, c.x + c.l, y2 - 5, 'gauche', a.rouge);
    if (a.rouge) etiquetteMemeFichier(zone, Math.max(0, xc - 90), (y1 + y2) / 2 - 9);
  });
  mesurerLargeur();
}

function listeDependances(equipes) {
  return el('ul', { class: 'graphe-liste' }, equipes.map((q) => {
    let deps;
    if (q.depend_de === null) deps = inconnu(sourceEnEchec(etat, 'structure'), 'dépendances inconnues');
    else if (!q.depend_de.length) deps = el('span', { class: 'secondaire' }, 'aucune');
    else deps = q.depend_de.map((d, i) => [i ? ', ' : '', lienEquipe(d)]);
    const memes = pairesRecouvrement().filter((p) => p.includes(q.nom)).flatMap((p) => p.filter((n) => n !== q.nom));
    const def = statutEquipeAffiche(q, etat.alarmes);
    const ton = def.ton;
    return el('li', { class: `ton-${ton}` },
      el('div', { class: 'graphe-liste-tete' }, lienEquipe(q.nom), puceStatut(q.statut, def)),
      el('div', { class: 'secondaire' }, 'dépend de : ', deps),
      memes.length ? el('div', { class: 'agent-alerte' }, '⚠ même fichier que ', memes.map((n, i) => [i ? ', ' : '', mono(n)])) : null);
  }));
}

function dependances() {
  const equipes = equipesActives();
  if (equipes === null) {
    return el('div', { class: 'inconnu-bloc' }, 'Dépendances : ', inconnu(sourceEnEchec(etat, 'structure'), 'inconnues'));
  }
  const graphe = calculerGraphe(equipes);
  const zone = el('div', { class: 'graphe-zone' }, equipes.map(boiteEquipe));
  const sansArete = pairesRecouvrement().filter(([a, b]) => !graphe.aretes.some((x) => (x.de === a && x.vers === b) || (x.de === b && x.vers === a)));
  if (observateurGraphe) observateurGraphe.disconnect();
  let largeurPrecedente = 0;
  observateurGraphe = new ResizeObserver(() => {
    if (zone.clientWidth === largeurPrecedente) return;
    largeurPrecedente = zone.clientWidth;
    requestAnimationFrame(() => disposer(zone, equipes, graphe));
  });
  observateurGraphe.observe(zone);
  return el('div', { class: 'graphe' },
    el('p', { class: 'secondaire', style: 'margin: 0' },
      'Qui alimente qui : la flèche part de l’équipe qui fournit et va vers celle qui en dépend. ',
      el('span', { class: 'rouge' }, 'Trait rouge : les deux équipes modifient le même fichier.')),
    zone,
    listeDependances(equipes),
    sansArete.map(([a, b]) => el('p', { class: 'agent-alerte', style: 'margin: 0' },
      '⚠ ', mono(a), ' et ', mono(b), ' modifient le même fichier sans dépendre l’une de l’autre.')));
}

// ---------------------------------------------------------------------------
// 2. Onglets
// ---------------------------------------------------------------------------
const ONGLETS = [
  { id: 'organigramme', titre: 'Organigramme', rendu: organigramme },
  { id: 'dependances', titre: 'Dépendances', rendu: dependances },
];

function ongletCourant() {
  return ctx.route.params.get('onglet') === 'dependances' ? 'dependances' : 'organigramme';
}

function sectionOnglets() {
  const panneau = el('div', { class: 'onglet-panneau', role: 'tabpanel' });
  const barre = el('div', { class: 'onglets', role: 'tablist', 'aria-label': 'Vue de l’entreprise' });
  const afficher = (id) => {
    for (const b of barre.children) b.setAttribute('aria-selected', String(b.dataset.onglet === id));
    vider(panneau, ONGLETS.find((o) => o.id === id).rendu());
    ctx.tic();
    mesurerLargeur();
  };
  for (const o of ONGLETS) {
    barre.append(el('button', { type: 'button', role: 'tab', class: 'onglet', dataset: { onglet: o.id },
      onclick: () => {
        history.replaceState(null, '', o.id === 'dependances' ? '#/supervision?onglet=dependances' : '#/supervision');
        ctx.route.params.set('onglet', o.id);
        afficher(o.id);
      } }, o.titre));
  }
  afficher(ongletCourant());
  return el('section', { class: 'section' }, barre, panneau);
}

// ---------------------------------------------------------------------------
// 3. Ce qui coince
// ---------------------------------------------------------------------------
/** L'âge d'une alarme, ou « depuis : inconnu ». */
const ageAlarme = (a) => (a.depuis ? age(a.depuis, 'depuis') : inconnu(null, 'depuis : inconnu'));

/** Une ligne de « Quoi faire » : le libellé en gras, puis le texte, puis le lien « Détail » qui déplie la mesure. */
function ligneFaire(a) {
  return el('details', { class: 'alarme-detail', ontoggle: () => mesurerLargeur() },
    el('summary', {}, el('span', { class: 'al-faire' }, el('b', {}, 'Quoi faire :'), ` ${a.quoi_faire} `, el('span', { class: 'al-lien' }, 'Détail'))),
    el('p', { class: 'alarme-ligne' }, a.mesure));
}

/** Une alarme grave (ou seule de son type) : une ligne — gravité, type, cibles, âge — puis « Quoi faire » et « Détail ». */
function ligneProbleme(a) {
  return el('article', { class: `al probleme ton-${tonAlarme(a)}`, dataset: { gravite: a.gravite } },
    el('span', { class: 'probleme-mot' }, motAlarme(a)),
    el('div', { class: 'al-quoi' }, el('span', { class: 'alarme-type' }, TYPES_ALARME[a.type] || a.type), ciblesAlarme(a)),
    el('span', { class: 'al-age discret' }, ageAlarme(a)),
    ligneFaire(a));
}

/** Les alarmes à voir d'un même type : une ligne dépliable, « Quoi faire » écrit une fois ; le dépliage montre chaque alarme avec son âge. */
function groupeProblemes(groupe) {
  const r = resumeGroupeProblemes(groupe);
  const faire = groupe.alarmes[0].quoi_faire;
  return el('details', { class: `al alarme-groupe groupe-probleme ton-${groupe.ton}`, dataset: { type: groupe.type, gravite: groupe.gravite }, ontoggle: () => mesurerLargeur() },
    el('summary', {},
      el('span', { class: 'probleme-mot' }, r.mot),
      el('span', { class: 'al-quoi alarme-type' }, r.ligne),
      el('span', { class: 'al-age discret' }, ageAlarme(groupe.alarmes[0])),
      el('span', { class: 'al-faire' }, el('b', {}, 'Quoi faire :'), ` ${faire}`)),
    el('ul', { class: 'groupe-liste' }, groupe.alarmes.map((a) => el('li', { class: 'groupe-alarme' },
      el('div', { class: 'alarme-tete' }, ciblesAlarme(a) || el('span', { class: 'secondaire' }, 'sans cible'), el('span', { class: 'discret' }, ageAlarme(a))),
      el('p', { class: 'alarme-ligne' }, a.mesure),
      a.quoi_faire !== faire ? el('p', { class: 'alarme-ligne' }, el('b', {}, 'Quoi faire :'), ` ${a.quoi_faire}`) : null))));
}

/** Les infos d'un même type : une ligne repliée, dépliable pour voir chaque alarme. */
function groupeInfos(groupe) {
  const r = resumeGroupeInfos(groupe);
  return el('details', { class: `al alarme-groupe ton-${groupe.ton}`, dataset: { type: groupe.type }, ontoggle: () => mesurerLargeur() },
    el('summary', {},
      el('span', { class: 'groupe-mot' }, r.mot),
      el('span', { class: 'groupe-resume' }, r.type, r.cibles.length ? ` : ${r.cibles.join(', ')}` : '')),
    el('ul', { class: 'groupe-liste' }, groupe.alarmes.map((a) => el('li', { class: 'groupe-alarme' },
      el('div', { class: 'alarme-tete' },
        el('span', { class: 'alarme-type' }, TYPES_ALARME[a.type] || a.type),
        el('span', { class: 'discret' }, ageAlarme(a))),
      ciblesAlarme(a),
      el('p', { class: 'alarme-ligne' }, a.mesure),
      el('p', { class: 'alarme-ligne alarme-quoi' }, el('b', {}, 'Quoi faire : '), a.quoi_faire)))));
}

const ligneAlarme = (item) => (item.genre === 'seule' ? ligneProbleme(item.alarmes[0])
  : item.gravite === 'info' ? groupeInfos(item) : groupeProblemes(item));

function sectionAlarmes() {
  let corps;
  let sous = 'calculées, pas déclarées';
  if (!Array.isArray(etat.alarmes)) {
    const echecs = sourcesEnEchec(etat).map((s) => s.nom).join(', ');
    corps = el('div', { class: 'inconnu-bloc' }, 'Alarmes ', inconnu(echecs || null, 'inconnues'),
      ' — l’absence d’alarme ne peut pas être affirmée.');
    sous = null;
  } else if (!etat.alarmes.length) {
    corps = el('div', { class: 'vide-calme' }, 'Aucune alarme.');
  } else {
    const n = (grav) => etat.alarmes.filter((a) => a.gravite === grav).length;
    sous = [n('grave') && `${n('grave')} grave${n('grave') > 1 ? 's' : ''}`, n('a_voir') && `${n('a_voir')} à voir`, n('info') && `${n('info')} info`]
      .filter(Boolean).join(' · ');
    corps = el('div', { class: 'alarmes alarmes-cadre' }, grouperAlarmes(etat.alarmes).map(ligneAlarme));
  }
  return el('section', { class: 'section', id: 'alarmes' }, enteteSection('Ce qui coince', sous), corps);
}

// ---------------------------------------------------------------------------
// 4. Avancement du projet
// ---------------------------------------------------------------------------
function sectionAvancement() {
  const etapes = etat.projet && etat.projet.etapes;
  let corps;
  if (!Array.isArray(etapes)) corps = el('div', { class: 'inconnu-bloc' }, inconnu(sourceEnEchec(etat, 'structure'), 'étapes inconnues'));
  else {
    const prochaine = etapes.findIndex((e) => !e.atteinte);
    corps = el('ol', { class: 'etapes' }, etapes.map((e, i) => el('li', {
      class: `etape${e.atteinte ? ' faite' : ''}${i === prochaine ? ' prochaine' : ''}` },
      el('span', { class: 'etape-quand' },
        e.atteinte ? 'faite' : i === prochaine ? 'prochaine' : 'à venir',
        e.date ? ` · ${dateCourte(e.date)}` : ''),
      el('span', { class: 'etape-nom' }, e.nom))));
  }
  const faites = Array.isArray(etapes) ? etapes.filter((e) => e.atteinte).length : null;
  return el('section', { class: 'section', id: 'avancement' },
    enteteSection('Avancement du projet', faites === null ? null : `${pluriel(faites, 'étape faite', 'étapes faites')} sur ${etapes.length}`),
    corps);
}

// ---------------------------------------------------------------------------
// 5. Consommation de jetons : un chiffre, une ligne, trois barres
// ---------------------------------------------------------------------------
/** Les trois plus gros postes ; la barre dit la part, en couleur neutre (jamais rouge). */
function postesConso(postes) {
  if (!postes.length) return el('div', { class: 'vide-calme' }, 'aucune consommation sur 15 min');
  return el('ul', { class: 'postes' }, plusGrosPostes(postes).map((p) => {
    const largeur = largeurBarre(p.part_15min);
    return el('li', { class: 'poste' },
      el('span', { class: 'mono poste-nom' }, nomAgent(p.agent)),
      largeur === null ? inconnu(null, 'part inconnue')
        : el('span', { class: 'poste-barre', role: 'img', 'aria-label': `${pourcent(p.part_15min)} des jetons lus du projet` },
          el('span', { class: 'poste-plein', style: `width: ${largeur}%` })),
      el('span', { class: 'poste-valeur' }, jetonsOuInconnu(p.lus_15min)));
  }));
}

function sectionConsommation() {
  const c = etat.consommation;
  let corps;
  if (!c) {
    corps = el('div', { class: 'inconnu-bloc' }, 'Consommation ', inconnu(sourceEnEchec(etat, 'transcripts'), 'inconnue'));
  } else {
    const f15 = c['15min'] || {};
    const f60 = c['60min'] || {};
    corps = el('div', { class: 'conso' },
      el('div', { class: 'conso-total' },
        el('div', { class: 'conso-grand' }, jetonsOuInconnu(f15.lus)),
        el('div', { class: 'conso-petit' }, joindre([
          Number.isInteger(f15.tours) ? pluriel(f15.tours, 'tour') : ['tours : ', inconnu(null)],
          typeof f60.lus === 'number' ? [jetonsOuInconnu(f60.lus), ' sur 60 min'] : ['60 min : ', inconnu(null)],
        ], ' · '))),
      Array.isArray(c.gros_postes) ? postesConso(c.gros_postes) : el('div', { class: 'inconnu-bloc' }, 'Gros postes ', inconnu(null)));
  }
  return el('section', { class: 'section', id: 'consommation' },
    enteteSection('Consommation', 'jetons lus, 15 dernières minutes'), corps);
}

// ---------------------------------------------------------------------------
// 6. Sessions hors organigramme, sous la consommation, seulement s'il y en a
// ---------------------------------------------------------------------------
function sectionSessionsOrphelines() {
  const sessions = etat.sessions_hors_organigramme;
  if (Array.isArray(sessions) && !sessions.length) return null;
  const corps = !Array.isArray(sessions)
    ? el('div', { class: 'inconnu-bloc' }, 'Sessions hors organigramme ', inconnu(sourceEnEchec(etat, 'tmux'), 'inconnues'))
    : el('ul', { class: 'liste-lignes' }, sessions.map((x) => el('li', { class: 'ligne-simple' },
      mono(x.nom),
      el('span', { class: 'secondaire' }, 'ouverte ', x.depuis ? age(x.depuis) : inconnu(null)),
      el('span', { class: 'secondaire' }, 'activité ', x.activite ? age(x.activite) : inconnu(null)))));
  return el('section', { class: 'section', id: 'sessions-orphelines' },
    enteteSection('Sessions hors organigramme', 'des sessions tmux au préfixe du projet que l’organigramme ne connaît pas'),
    corps);
}

// ---------------------------------------------------------------------------
// 7. Vérifications d'intégration, sous la consommation, seulement s'il y a un rapport ou une requête
// ---------------------------------------------------------------------------
const VERDICTS = { PASS: { mot: 'PASS', ton: 'vert' }, FAIL: { mot: 'FAIL', ton: 'rouge' } };
const ETATS_REQUETE = { todo: 'à traiter', 'in-progress': 'en cours' };

function dernierRapport(rapport) {
  if (!rapport) return el('p', { class: 'vide-calme' }, 'aucun rapport');
  const v = VERDICTS[rapport.verdict] || { mot: 'verdict non lu', ton: 'gris' };
  const { bouton, panneau } = texteDepliable(
    { id: `integration:${rapport.fichier}`, resume: rapport.ligne, fichier: rapport.fichier }, 'fichier-ouvrir', mono(rapport.fichier), { seulContenu: true });
  return el('div', { class: 'rapport' },
    el('div', { class: 'ligne-simple' },
      el('span', { class: `puce-statut ton-${v.ton}`, dataset: { verdict: rapport.verdict || '' } }, el('span', { class: 'pastille' }), v.mot),
      el('span', { class: 'secondaire' }, rapport.date ? joindre([age(rapport.date), dateCourte(rapport.date)], ' · ') : inconnu(null)),
      bouton),
    rapport.ligne ? el('p', { class: 'rapport-ligne' }, rapport.ligne) : null,
    panneau);
}

function requetesEnCours(requetes) {
  if (!requetes.length) return el('p', { class: 'vide-calme' }, 'aucune requête en cours');
  return el('ul', { class: 'liste-lignes' }, requetes.map((r) => el('li', { class: 'ligne-simple' },
    mono(r.fichier),
    el('span', {}, ETATS_REQUETE[r.etat] || r.etat),
    el('span', { class: 'secondaire' }, r.depuis ? age(r.depuis, 'depuis') : inconnu(null)))));
}

function sectionIntegration() {
  const integration = etat.integration;
  if (!integration) {
    // structure en échec : « inconnu » ; sinon il n'y a simplement pas d'équipe intégration
    if (!sourceEnEchec(etat, 'structure')) return null;
    return el('section', { class: 'section', id: 'integration' },
      enteteSection('Vérifications d’intégration', 'dernier rapport et requêtes en cours'),
      el('div', { class: 'inconnu-bloc' }, inconnu(sourceEnEchec(etat, 'structure'), 'inconnues')));
  }
  // ni rapport ni requête : rien à montrer
  if (!integration.dernier_rapport && !(integration.requetes || []).length) return null;
  return el('section', { class: 'section', id: 'integration' },
    enteteSection('Vérifications d’intégration', 'dernier rapport et requêtes en cours'),
    el('h3', { class: 'sous-section' }, 'Dernier rapport'),
    dernierRapport(integration.dernier_rapport),
    el('h3', { class: 'sous-section' }, 'Requêtes en cours'),
    requetesEnCours(integration.requetes || []));
}

// ---------------------------------------------------------------------------
// 8. Pied : le journal, qui n'est plus un onglet (le lien des équipes clôturées est sous la grille)
// ---------------------------------------------------------------------------
function piedSupervision() {
  return el('nav', { class: 'pied-supervision', 'aria-label': 'Autres écrans' },
    el('a', { href: '#/journal' }, 'Journal des actions'));
}

// ---------------------------------------------------------------------------
export function rendre(contexte) {
  ctx = contexte;
  etat = ctx.etat;
  // la visite est enregistrée quand on quitte la page, pas au chargement
  if (!visiteSuivie) { visiteSuivie = true; addEventListener('pagehide', memoriserVisite); }
  vider(ctx.contenu,
    sectionNouveautes(),
    sectionOnglets(),
    sectionAlarmes(),
    sectionAvancement(),
    sectionConsommation(),
    sectionSessionsOrphelines(),
    sectionIntegration(),
    piedSupervision());
  ctx.tic();
  mesurerLargeur();
}
