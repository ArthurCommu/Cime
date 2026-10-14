// Cime — le rail de la scène : quatre blocs (« Ce qui t'attend », « Ce qui coince », « Qui travaille », « Derniers
// échanges »), ou le détail de la cible choisie dans la scène (équipe, agent, message).
// Tout est reconstruit à chaque dessin à partir de l'instantané et de la sélection : aucun état n'est gardé dans le DOM.
// La seule mémoire d'ici : les attentes déjà montrées, pour que les nouvelles arrivent en fondu.

import {
  el, vider, pluriel, joindre, nomAgent, age, inconnu, inconnuCourt, pourcent, finDePhrase, sourceEnEchec,
  GRAVITES, NATURES_FIL, TYPES_ALARME, tonAlarme, defEtatAgent, statutEquipeAffiche,
  etatAffiche, workerTermine, attentesOuvertes, carteAttente, equipeDeLAttente, puceStatut, pastilleEtat,
  phraseAttente, estNonLu, repereNonLu, libelleNature, routeEquipe, routeFil,
} from '../commun.js';
import { interrupteurMode, encadreMode, blocTiroirMode } from './mode-autonome.js';
import { ligneWorkers } from './workers.js';

export const MAX_ATTENTES = 3;
export const MAX_ALARMES = 3;
export const MAX_ECHANGES = 3;
const ETATS_QUI_TRAVAILLE = new Set(['travaille', 'attend_autorisation', 'attend_reponse']);
const LIVRAISON = {
  inscrit: 'inscrit, pas encore livré', livre: 'livré', pris_en_compte: 'pris en compte', clos: 'clos',
  echec: 'échec de livraison', abandonne: 'abandonné',
};

/** Les ids d'attentes déjà montrés ; null tant que le rail n'a rien dessiné (le premier dessin n'anime rien). */
let attentesVues = null;

const instant = (iso) => Date.parse(iso) || Number.MAX_SAFE_INTEGER;
const plusAncienDabord = (a, b) => instant(a.depuis) - instant(b.depuis);

/** Les genres d'attente, dans l'ordre où l'utilisateur les traite : ce qui bloque un agent d'abord, ce qui se lit en dernier. */
export const ORDRE_GENRES = ['autorisation', 'decision', 'donnee', 'cloture', 'rapport'];
const rangGenre = (a) => {
  const rang = ORDRE_GENRES.indexOf(a.nature);
  return rang === -1 ? ORDRE_GENRES.length : rang; // un genre inconnu passe après les autres
};

/** Les attentes dans l'ordre du rail : par genre (ORDRE_GENRES), puis la plus ancienne d'abord. Pure : le tableau reçu n'est pas modifié. */
export function trierAttentes(attentes) {
  return [...attentes].sort((a, b) => rangGenre(a) - rangGenre(b) || plusAncienDabord(a, b));
}

/** Le rail montre-t-il toute la liste des attentes ? Replié par défaut ; « n autres points ▾ » le déplie, « replier ▴ » le replie. */
let attentesDepliees = false;

/** Un bloc du rail : titre, compteur (un nombre, ou null), lien { href, texte } à droite, contenu ; `droite` : un nœud à droite du titre, sur la même ligne (l'interrupteur du mode autonome). */
export function blocRail(titre, compteur, lien, contenu, classe = '', droite = null) {
  const intitule = el('h2', {},
    titre,
    compteur ? el('span', { class: 'compte', 'aria-label': pluriel(compteur, 'point') }, String(compteur)) : null,
    lien ? el('a', { class: 'lien-bloc', href: lien.href }, lien.texte) : null);
  return el('section', { class: `bloc-rail${classe ? ` ${classe}` : ''}`, 'aria-label': titre },
    droite ? el('div', { class: 'rail-tete' }, intitule, droite) : intitule,
    contenu);
}

// ---------------------------------------------------------------------------
// Les quatre blocs
// ---------------------------------------------------------------------------
function blocAttentes(etat, nouvelles, clignote, redessiner) {
  const titre = 'Ce qui t’attend';
  const classe = clignote ? 'clignote' : '';
  const attentes = attentesOuvertes(etat);
  // le mode autonome : l'interrupteur à droite du titre, l'encadré sous lui, quoi que dise le reste du bloc (rien n'attend, inconnu…)
  const mode = interrupteurMode(etat);
  const encadre = [encadreMode(etat, redessiner), ligneWorkers(etat, redessiner)];
  if (attentes === null) {
    return blocRail(titre, null, null, [encadre, el('div', { class: 'inconnu-bloc' }, 'Ce qui t’attend : inconnu (sources en échec).')], classe, mode);
  }
  if (!attentes.length) {
    return blocRail(titre, null, null, [encadre, el('div', { class: 'rail-calme' }, '✓ Rien ne t’attend. Tout avance sans toi.')], classe, mode);
  }
  const triees = trierAttentes(attentes);
  const reste = triees.length - MAX_ATTENTES;
  const depliees = attentesDepliees && reste > 0;
  return blocRail(titre, attentes.length, null, [
    encadre,
    el('div', { class: 'attentes' }, (depliees ? triees : triees.slice(0, MAX_ATTENTES)).map((a) => cartePourRail(a, etat, nouvelles))),
    reste > 0 ? el('button', { type: 'button', class: 'lien-autres', 'aria-expanded': String(depliees),
      onclick: () => { attentesDepliees = !depliees; redessiner(); } },
    depliees ? 'replier ▴' : `${pluriel(reste, 'autre point', 'autres points')} ▾`) : null,
  ], classe, mode);
}

/** La carte d'attente de la page, avec ses boutons ; une carte qui vient d'arriver s'annonce par un fondu. */
function cartePourRail(attente, etat, nouvelles) {
  const carte = carteAttente(attente, { etat });
  if (nouvelles.has(attente.id)) carte.classList.add('arrive');
  return carte;
}

function blocCoince(etat) {
  if (!Array.isArray(etat.alarmes)) return null;
  const rang = (a) => GRAVITES[a.gravite].rang;
  const alarmes = etat.alarmes.filter((a) => a.gravite === 'grave' || a.gravite === 'a_voir').sort((a, b) => rang(a) - rang(b));
  if (!alarmes.length) return null;
  return blocRail('Ce qui coince', alarmes.length, { href: '#/supervision', texte: 'Tout voir →' },
    el('ul', { class: 'rail-liste' }, alarmes.slice(0, MAX_ALARMES).map((a) => {
      const cible = (a.agents || []).length ? nomAgent(a.agents[0]) : (a.equipes || [])[0];
      return el('li', { class: `rail-ligne ton-${tonAlarme(a)}`, title: a.mesure },
        el('span', { class: 'pastille', 'aria-hidden': 'true' }),
        el('span', { class: 'rail-qui rail-qui-coince' }, el('span', { class: 'rail-titre' }, TYPES_ALARME[a.type] || a.type),
          cible ? el('span', { class: 'rail-cible' }, `·\u00A0${cible}`) : null),
        a.depuis ? el('span', { class: 'rail-age' }, age(a.depuis, 'court')) : null);
    })), 'bloc-coince');
}

/** L'équipe de cet agent est-elle terminée ? Ses agents sont alors « clos ». */
const equipeTerminee = (agent, etat) => (etat.equipes || []).some((q) => q.nom === agent.equipe && q.statut === 'terminee');

/** Les agents qu'on montre : jamais l'utilisateur, jamais un worker terminé. */
const agentVisible = (a, etat) => a.role !== 'utilisateur' && !workerTermine(a, etat.alarmes);

/** Une ligne d'agent : pastille, id, âge, puis la tâche (sinon la dernière phrase). Un clic ouvre son détail. */
function ligneAgent(agent, etat, ouvrir, { avecEtat = false } = {}) {
  const def = defEtatAgent(agent, etat.alarmes, { equipeTerminee: equipeTerminee(agent, etat) });
  const quoi = agent.tache || (agent.derniere_phrase ? finDePhrase(agent.derniere_phrase) : null);
  return el('li', {}, el('button', { type: 'button', class: `rail-ligne ton-${def.ton}`, onclick: () => ouvrir({ type: 'agent', id: agent.id }) },
    el('span', { class: 'pastille', 'aria-hidden': 'true' }),
    el('span', { class: 'rail-qui' }, nomAgent(agent.id)),
    el('span', { class: 'rail-age' }, joindre([avecEtat ? def.mot : null, agent.etat_depuis ? age(agent.etat_depuis, 'court') : null], ' · ')),
    quoi ? el('span', { class: 'rail-quoi', title: quoi }, quoi) : null));
}

function blocTravaille(etat, ouvrir) {
  const titre = 'Qui travaille';
  if (!Array.isArray(etat.agents)) {
    return blocRail(titre, null, null, el('p', { class: 'rail-vide' }, inconnu(sourceEnEchec(etat, 'structure'), 'Qui travaille : inconnu')));
  }
  const agents = etat.agents.filter((a) => agentVisible(a, etat) && ETATS_QUI_TRAVAILLE.has(etatAffiche(a)));
  return blocRail(titre, null, null, agents.length
    ? el('ul', { class: 'rail-liste' }, agents.map((a) => ligneAgent(a, etat, ouvrir)))
    : el('p', { class: 'rail-vide' }, 'Personne ne travaille en ce moment.'));
}

function blocEchanges(etat, ouvrir) {
  const titre = 'Derniers échanges';
  const lien = { href: '#/fil', texte: 'Tout le fil →' };
  if (!Array.isArray(etat.fil)) return blocRail(titre, null, lien, el('p', { class: 'rail-vide' }, inconnu(sourceEnEchec(etat, 'registre'), 'Fil : inconnu')));
  const recents = [...etat.fil].sort((a, b) => (Date.parse(b.horodatage) || 0) - (Date.parse(a.horodatage) || 0)).slice(0, MAX_ECHANGES);
  return blocRail(titre, null, lien, recents.length
    ? el('ul', { class: 'rail-liste' }, recents.map((m) => el('li', { class: m.de === 'cime' || m.a === 'cime' ? 'echange-cime' : null },
      el('button', { type: 'button', class: 'echange', onclick: () => ouvrir({ type: 'message', id: m.id }) },
        el('span', { class: 'echange-tete' },
          el('span', { class: 'echange-qui' }, `${nomAgent(m.de)} → ${nomAgent(m.a)}`),
          el('span', { class: 'rail-age' }, m.horodatage ? age(m.horodatage, 'court') : inconnu(null, 'âge inconnu'))),
        el('span', { class: 'echange-resume', title: m.resume }, m.resume),
        m.en_attente ? el('span', { class: 'echange-attend' }, phraseAttente(m, true)) : null),
      estNonLu(m) ? repereNonLu(m) : null)))
    : el('p', { class: 'rail-vide' }, 'Aucun échange récent.'));
}

// ---------------------------------------------------------------------------
// Le détail d'une cible
// ---------------------------------------------------------------------------
/**
 * La cible choisie dans la scène, retrouvée dans l'instantané : { equipe } | { agent } | { message }, ou null si elle a
 * disparu (équipe, agent ou message retiré) ou si sa liste est inconnue. `{ type: 'utilisateur' }` n'a pas de détail.
 */
export function trouverCible(cible, etat) {
  if (cible.type === 'equipe' && Array.isArray(etat.equipes)) {
    const equipe = etat.equipes.find((q) => q.nom === cible.nom);
    return equipe ? { equipe } : null;
  }
  if (cible.type === 'agent' && Array.isArray(etat.agents)) {
    const agent = etat.agents.find((a) => a.id === cible.id);
    return agent ? { agent } : null;
  }
  if (cible.type === 'message' && Array.isArray(etat.fil)) {
    const message = etat.fil.find((m) => m.id === cible.id);
    return message ? { message } : null;
  }
  return null;
}

const lienBouton = (href, texte) => el('a', { class: 'bouton bouton-lien', href }, texte);
const section = (titre, ...corps) => el('section', { class: 'detail-section' }, el('h3', {}, titre), corps);
const fait = (cle, valeur) => [el('dt', {}, cle), el('dd', {}, valeur)];

function chiffre(valeur, libelle, barre) {
  return el('div', { class: 'detail-chiffre' },
    el('div', { class: 'detail-valeur' }, valeur), el('div', { class: 'detail-libelle' }, libelle), barre);
}

function detailEquipe(q, etat, ouvrir, nouvelles) {
  const base = etat.projet ? etat.projet.branche_reference : 'la base';
  const av = q.avancement;
  const total = av ? av.faites + av.en_cours + av.a_faire : 0;
  const faites = av
    ? chiffre(`${av.faites} / ${total}`, 'tâches faites', el('div', { class: 'jauge-barre', role: 'img', 'aria-label': `${av.faites} tâches faites sur ${total}` },
      el('div', { class: 'jauge-plein', style: `width: ${total ? Math.round((av.faites / total) * 100) : 0}%` })))
    : chiffre(inconnu(sourceEnEchec(etat, 'structure')), 'tâches faites');
  const retard = q.retard_sur_base;
  let chiffreRetard;
  if (retard === null || retard === undefined) chiffreRetard = chiffre(inconnu(sourceEnEchec(etat, 'git')), `retard sur ${base}`);
  else if (retard === 0) chiffreRetard = chiffre('à jour', `retard sur ${base}`);
  else chiffreRetard = chiffre(String(retard), `${retard === 1 ? 'commit' : 'commits'} de retard sur ${base}`);
  const attentes = (attentesOuvertes(etat) || []).filter((a) => equipeDeLAttente(a, etat) === q.nom).sort(plusAncienDabord);
  const agents = (Array.isArray(etat.agents) ? etat.agents : []).filter((a) => a.equipe === q.nom && agentVisible(a, etat));
  return [
    el('div', { class: 'detail-tete' }, el('h2', {}, q.nom), puceStatut(q.statut, statutEquipeAffiche(q, etat.alarmes))),
    q.mission ? el('p', { class: 'detail-texte' }, q.mission) : null,
    el('div', { class: 'detail-chiffres' }, faites, chiffreRetard),
    attentes.length ? section('Attend de toi', el('div', { class: 'attentes' }, attentes.map((a) => cartePourRail(a, etat, nouvelles)))) : null,
    section('Agents', agents.length
      ? el('ul', { class: 'rail-liste' }, agents.map((a) => ligneAgent(a, etat, ouvrir, { avecEtat: true })))
      : el('p', { class: 'rail-vide' }, 'Aucun agent en activité.')),
    lienBouton(routeEquipe(q.nom), 'Ouvrir la fiche complète →'),
  ];
}

function detailAgent(agent, etat) {
  const def = defEtatAgent(agent, etat.alarmes, { equipeTerminee: equipeTerminee(agent, etat) });
  const contexte = agent.contexte && agent.contexte.limite
    ? el('span', {}, pourcent(agent.contexte.tokens / agent.contexte.limite))
    : inconnuCourt('contexte', sourceEnEchec(etat, 'transcripts'));
  const dettes = agent.dettes;
  const file = agent.file;
  return [
    el('div', { class: 'detail-tete' }, el('h2', {}, nomAgent(agent.id)), pastilleEtat(def.cle, def)),
    el('dl', { class: 'detail-faits' },
      fait('Tâche', agent.tache || el('span', { class: 'discret' }, 'aucune tâche déclarée')),
      agent.derniere_phrase ? fait('Dernière phrase', finDePhrase(agent.derniere_phrase)) : null,
      fait('Contexte', contexte),
      fait('Modèle', agent.modele || inconnuCourt('modèle', null))),
    section('Dettes', Array.isArray(dettes)
      ? (dettes.length
        ? el('ul', { class: 'detail-liste' }, dettes.map((d) => el('li', {},
          `${d.attendu} de ${nomAgent(d.de)}`, d.objet ? ` — ${d.objet}` : null, d.depuis ? [' · ', age(d.depuis, 'depuis')] : null)))
        : el('p', { class: 'rail-vide' }, 'Aucune dette ouverte.'))
      : el('p', { class: 'rail-vide' }, inconnu(sourceEnEchec(etat, 'registre')))),
    section('File', Array.isArray(file)
      ? (file.length
        ? el('ul', { class: 'detail-liste' }, file.map((m) => el('li', {},
          `${nomAgent(m.de)} · ${NATURES_FIL[m.nature] || m.nature || 'message'} — ${m.resume}`, m.depuis ? [' · ', age(m.depuis, 'depuis')] : null)))
        : el('p', { class: 'rail-vide' }, 'Rien en file.'))
      : el('p', { class: 'rail-vide' }, inconnu(sourceEnEchec(etat, 'registre')))),
    agent.equipe ? lienBouton(routeEquipe(agent.equipe), 'Ouvrir la fiche de l’équipe →') : lienBouton(routeFil({ agent: agent.id }), 'Voir ses échanges →'),
  ];
}

function detailMessage(m) {
  const agentDuFil = [m.de, m.a].find((id) => id !== 'utilisateur' && id !== 'cime');
  return [
    el('div', { class: 'detail-tete' }, el('h2', {}, `${nomAgent(m.de)} → ${nomAgent(m.a)}`)),
    el('dl', { class: 'detail-faits' },
      fait('Nature', libelleNature(m)),
      fait('Envoyé', m.horodatage ? age(m.horodatage) : inconnu(null, 'inconnu')),
      fait('Livraison', m.etat_livraison ? (LIVRAISON[m.etat_livraison] || m.etat_livraison) : 'sans suivi de livraison'),
      m.en_attente ? fait('Réponse', phraseAttente(m, true)) : null),
    el('p', { class: 'detail-texte' }, m.resume),
    lienBouton(routeFil({ agent: agentDuFil }), 'Voir dans le fil →'),
  ];
}

// ---------------------------------------------------------------------------
// Le dessin
// ---------------------------------------------------------------------------
/** Le contenu du détail d'une cible trouvée (`trouverCible`) : le même dans le rail du bureau et dans la feuille du téléphone. */
export function detailCible(trouve, etat, ouvrir, nouvelles = new Set()) {
  if (trouve.equipe) return detailEquipe(trouve.equipe, etat, ouvrir, nouvelles);
  return trouve.agent ? detailAgent(trouve.agent, etat) : detailMessage(trouve.message);
}

/**
 * Redessine le rail. `selection` : la cible choisie dans la scène (ou null) ; `fermer()` la retire ; `ouvrir(cible)` en choisit
 * une ; `clignote` : le bloc « Ce qui t'attend » clignote une fois (clic sur la porte de l'utilisateur) ; `telephone` : trois blocs
 * seulement (la feuille basse), sans « Ce qui t'attend » ni détail ; `redessiner()` : « n autres points ▾ » vient de changer
 * l'état du rail, à l'appelant de le redessiner (il garde la position de défilement, que le rail ne connaît pas).
 */
export function rendreRail(conteneur, { etat, selection, fermer, ouvrir, redessiner, clignote = false, telephone = false }) {
  const ids = Array.isArray(etat.attentes_utilisateur) ? etat.attentes_utilisateur.map((a) => a.id) : null;
  const nouvelles = new Set(attentesVues && ids ? ids.filter((id) => !attentesVues.has(id)) : []);
  const trouve = !telephone && selection && selection.type !== 'utilisateur' ? trouverCible(selection, etat) : null;
  if (trouve) {
    const retour = el('button', { type: 'button', class: 'retour', onclick: fermer }, '← Retour');
    vider(conteneur, el('section', { class: 'detail-rail', 'aria-label': 'Détail' }, retour, detailCible(trouve, etat, ouvrir, nouvelles)));
  } else if (telephone) {
    // sur le téléphone, « Ce qui t'attend » est dans la feuille des attentes et le détail dans la feuille de détail ; quand rien n'attend,
    // le mode autonome ouvre le tiroir (sinon il est dans la tête de la feuille)
    const rienNAttend = Array.isArray(etat.attentes_utilisateur) && etat.attentes_utilisateur.length === 0;
    vider(conteneur, rienNAttend ? blocTiroirMode(etat, redessiner) : null, blocCoince(etat), blocTravaille(etat, ouvrir), blocEchanges(etat, ouvrir));
  } else {
    vider(conteneur, blocAttentes(etat, nouvelles, clignote, redessiner), blocCoince(etat), blocTravaille(etat, ouvrir), blocEchanges(etat, ouvrir));
  }
  if (ids) attentesVues = new Set(ids);
}
