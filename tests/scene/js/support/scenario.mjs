// scenario.mjs — rejoue un scénario d'essai pour les tests : jeu scripté, rejoué en boucle (90 s).
// Chaque étape : { t (ms), commentaire (animation de la table illustrée, voir animations.js), patch?(etat) , transitions? }.
// patch modifie une copie de l'instantané ; transitions sont reportées dans flux[] (source-rejouee.mjs).
// Un message ne passe que dans l'ordre du registre : inscrit → livre → pris_en_compte → clos, ou echec / abandonne.
// Les étapes ne créent aucune activité qui ne soit pas un fait de l'instantané.

export const DUREE_MS = 90000;

const trouver = (e, id) => e.agents.find((a) => a.id === id);

function nouvelOuvrier(id, equipe, parent, etat, extra = {}) {
  return {
    id,
    role: 'worker',
    equipe,
    parent,
    session_tmux: `cc-${id}`,
    vivant: true,
    etat,
    etat_depuis: '2026-10-11T09:00:00.000Z',
    etat_source: 'hook:PostToolUse',
    tache: null,
    derniere_phrase: null,
    modele: 'claude-sonnet-5-5',
    contexte: { tokens: 40000, limite: 200000, source: 'transcript' },
    cout_usd_estime: null,
    consommation: null,
    brouillon: null,
    dettes: [],
    file: [],
    occupe_par: 'tour',
    ...extra,
  };
}

const retirerAttentes = (e, ids) => {
  e.attentes_utilisateur = e.attentes_utilisateur.filter((a) => !ids.includes(a.id));
};
const retirerAlarme = (e, id) => {
  e.alarmes = e.alarmes.filter((a) => a.id !== id);
};

// Statut d'une équipe, recalculé dans cet ordre :
// terminee (cloturee_le présent) ; bloquee (un agent attend_autorisation / attend_reponse, ou une alarme
// bloque_au_demarrage) ; active (un agent travaille, ou un worker vivant) ; au_repos (tous au_repos / arrete,
// aucun worker vivant) ; sinon null (non mesuré).
export function statutEquipe(e, equipe) {
  if (equipe.cloturee_le) return 'terminee';
  const agents = e.agents.filter((a) => a.equipe === equipe.nom);
  const bloque =
    agents.some((a) => a.etat === 'attend_autorisation' || a.etat === 'attend_reponse') ||
    e.alarmes.some((a) => a.type === 'bloque_au_demarrage' && (a.equipes ?? []).includes(equipe.nom));
  if (bloque) return 'bloquee';
  if (agents.some((a) => a.etat === 'travaille') || agents.some((a) => a.role === 'worker' && a.vivant)) return 'active';
  if (agents.length && agents.every((a) => a.etat === 'au_repos' || a.etat === 'arrete')) return 'au_repos';
  return null;
}

// Le statut de l'équipe suit ses agents : chaque fois qu'un pas change un agent, le scénario recalcule
// equipes[].statut. Sans cela, une équipe resterait « bloquee » après la fin de l'attente, et sa pièce
// passerait au rouge sans aucun signe qui l'explique.
const suivreStatuts = (e) => {
  for (const eq of e.equipes) eq.statut = statutEquipe(e, eq);
};

const BRUT = [
  // Enveloppes (animations 11 à 15) : chaque message suit le registre.
  { t: 2000, commentaire: 'animation 11 : enveloppe inscrite, née sur le bureau de coord-page', transitions: [{ message_id: 70, etat: 'inscrit', de: 'coord-page', a: 'assistant', nature: 'compte_rendu' }] },
  { t: 4000, commentaire: 'animation 12 : le facteur porte la 70 par le couloir jusqu’à l’Assistant', transitions: [{ message_id: 70, etat: 'livre', voie: 'hote', auteur: 'cime' }] },
  { t: 12000, commentaire: 'animation 13 : enveloppe prise en compte chez l’Assistant', transitions: [{ message_id: 70, etat: 'pris_en_compte', voie: 'hook:UserPromptSubmit', auteur: 'assistant' }] },
  { t: 15000, commentaire: 'animation 14 : enveloppe tamponnée puis disparue', transitions: [{ message_id: 70, etat: 'clos', auteur: 'assistant' }] },
  { t: 16000, commentaire: 'animation 11 : question de coord-observation à coord-hote', transitions: [{ message_id: 71, etat: 'inscrit', de: 'coord-observation', a: 'coord-hote', nature: 'question' }] },
  { t: 18000, commentaire: 'animation 12 : la question est livrée à coord-hote', transitions: [{ message_id: 71, etat: 'livre', voie: 'tmux', auteur: 'cime' }] },
  { t: 24000, commentaire: 'animation 15 : échec, enveloppe rouge tombée au sol du couloir', transitions: [{ message_id: 71, etat: 'echec', voie: 'tmux', auteur: 'cime' }] },
  { t: 30000, commentaire: 'animation 11 : signalement né chez coord-verification', transitions: [{ message_id: 72, etat: 'inscrit', de: 'coord-verification', a: 'coord-hote', nature: 'signalement' }] },
  { t: 32000, commentaire: 'animation 12 : signalement livré', transitions: [{ message_id: 72, etat: 'livre', voie: 'tmux', auteur: 'cime' }] },
  { t: 42000, commentaire: 'animation 15 : abandonnée, enveloppe rouge au sol', transitions: [{ message_id: 72, etat: 'abandonne', voie: 'tmux', auteur: 'cime' }] },
  { t: 54000, commentaire: 'animation 11 : réponse née chez coord-hote', transitions: [{ message_id: 73, etat: 'inscrit', de: 'coord-hote', a: 'coord-verification', nature: 'reponse' }] },
  { t: 56000, commentaire: 'animation 12 : réponse livrée', transitions: [{ message_id: 73, etat: 'livre', voie: 'tmux', auteur: 'cime' }] },
  { t: 64000, commentaire: 'animation 13 : réponse prise en compte', transitions: [{ message_id: 73, etat: 'pris_en_compte', voie: 'hook:UserPromptSubmit', auteur: 'coord-verification' }] },
  { t: 67000, commentaire: 'animation 14 : réponse tamponnée puis disparue', transitions: [{ message_id: 73, etat: 'clos', auteur: 'coord-verification' }] },
  { t: 76000, commentaire: 'animation 11 : question de coord-page à coord-fondation', transitions: [{ message_id: 74, etat: 'inscrit', de: 'coord-page', a: 'coord-fondation', nature: 'question' }] },
  { t: 78000, commentaire: 'animation 12 : question livrée, elle reste visible chez le destinataire', transitions: [{ message_id: 74, etat: 'livre', voie: 'tmux', auteur: 'cime' }] },

  // Embauche et fin de tâche (animations 9 et 10).
  {
    t: 6000,
    commentaire: 'animation 9 : worker-page-revue arrive (ordre lancer, nouvel agent)',
    patch(e) {
      e.agents.push(nouvelOuvrier('worker-page-revue', 'page', 'coord-page', 'travaille', { activite: 'ecrire', tache: 'Relire la page' }));
      e.ordres.push({ id: 6, auteur: 'coord-page', verbe: 'lancer', cible: 'worker-page-revue', etat: 'execute' });
    },
  },
  {
    t: 20000,
    commentaire: 'animation 10 : fin de tâche de worker-verification-rapport (ordre terminer exécuté)',
    patch(e) {
      e.ordres.push({ id: 7, auteur: 'coord-verification', verbe: 'terminer', cible: 'worker-verification-rapport', etat: 'execute' });
    },
  },
  {
    t: 26000,
    commentaire: 'animation 10 (suite) : la tâche est rendue, le bureau se vide',
    patch(e) {
      const w = trouver(e, 'worker-verification-rapport');
      Object.assign(w, { etat: 'arrete', vivant: false, tache: null, session_tmux: null, etat_source: 'tmux:session_absente' });
      e.ordres = e.ordres.filter((o) => o.id !== 7);
    },
  },

  // Compactage (animation 8) et jauge de contexte (animation 22).
  {
    t: 24000,
    commentaire: 'animation 22 : le contexte de l’Assistant monte au-dessus de 60 %',
    patch(e) {
      trouver(e, 'assistant').contexte = { tokens: 820000, limite: 1000000, source: 'transcript' };
    },
  },
  {
    t: 28000,
    commentaire: 'animation 8 : ordre de compactage en file pour l’Assistant (sieste)',
    patch(e) {
      e.ordres.push({ id: 8, auteur: 'coord-observation', verbe: 'compacter', cible: 'assistant', etat: 'en_file' });
    },
  },
  {
    t: 30000,
    commentaire: 'animation 8 : compactage exécuté',
    patch(e) {
      e.ordres.find((o) => o.id === 8).etat = 'execute';
    },
  },
  {
    t: 36000,
    commentaire: 'animation 22 : compactage fini, la jauge retombe ; l’ordre n’est plus en cours',
    patch(e) {
      e.ordres.find((o) => o.id === 8).etat = 'fini';
      trouver(e, 'assistant').contexte = { tokens: 250000, limite: 1000000, source: 'transcript' };
    },
  },

  // Attentes de l’utilisateur (animations 3 et 5, porte : animation 17) et autorisations (animations 5, 17, 18).
  {
    t: 12000,
    commentaire: 'animation 5 (fin) : autorisation de coord-page accordée, décisions et donnée tranchées ; reste un rapport → porte en attente',
    patch(e) {
      const c = trouver(e, 'coord-page');
      Object.assign(c, { etat: 'travaille', activite: 'ecrire', tache: 'Valider la page statique contre le schéma' });
      retirerAttentes(e, ['perm-d41', 'msg-59', 'msg-60', 'msg-62']);
      retirerAlarme(e, 'autorisation_en_attente:coord-page:perm-d41');
    },
  },
  {
    t: 22000,
    commentaire: 'animation 17 : le rapport est lu, la porte revient fermée',
    patch(e) {
      retirerAttentes(e, ['msg-58']);
    },
  },
  {
    t: 34000,
    commentaire: 'animation 5, 17 et 18 : nouvelle autorisation → coord-page attend, halo rouge, porte en alerte',
    patch(e) {
      const c = trouver(e, 'coord-page');
      Object.assign(c, { etat: 'attend_autorisation', etat_source: 'hook:PermissionRequest', derniere_phrase: null });
      e.attentes_utilisateur.push({ id: 'perm-d52', nature: 'autorisation', titre: 'Exécuter : uv run --with pytest pytest tests/page -q', bloque: 'La validation de la page', depuis: '2026-10-11T09:34:00.000Z', agent: 'coord-page', equipe: 'page', actions: ['autoriser', 'refuser'], message_id: null, objet: null });
      e.alarmes.push({ id: 'autorisation_en_attente:coord-page:perm-d52', type: 'autorisation_en_attente', gravite: 'grave', agents: ['coord-page'], equipes: ['page'], destinataire: 'utilisateur', depuis: '2026-10-11T09:34:00.000Z', mesure: 'PermissionRequest reçue, sans Stop ni PostToolUse depuis.', quoi_faire: 'Autoriser ou refuser la commande dans « Ce qui t’attend ».' });
    },
  },
  {
    t: 52000,
    commentaire: 'animation 5 (fin) : autorisation accordée, l’agent reprend, halo éteint',
    patch(e) {
      const c = trouver(e, 'coord-page');
      Object.assign(c, { etat: 'travaille', etat_source: 'hook:PostToolUse' });
      retirerAttentes(e, ['perm-d52']);
      retirerAlarme(e, 'autorisation_en_attente:coord-page:perm-d52');
    },
  },

  // Facteur (animation 16).
  { t: 40000, commentaire: 'animation 16 : le facteur s’arrête, rouge', patch(e) { e.facteur = { battement: '2026-10-11T09:39:50.000Z', age_s: 40, arrete: true }; } },
  { t: 46000, commentaire: 'animation 16 : le facteur repart', patch(e) { e.facteur = { battement: '2026-10-11T09:40:00.000Z', age_s: 0, arrete: false }; } },

  // Refus du garde (animation 20), au repos d'un worker (animation 3) et reprise (animation 2).
  {
    t: 44000,
    commentaire: 'animation 20 : le garde refuse une écriture de coord-hote (éclair 3 s)',
    patch(e) {
      e.alarmes.push({ id: 'action_refusee:coord-hote:5130', type: 'action_refusee', gravite: 'a_voir', agents: ['coord-hote'], equipes: ['hote'], destinataire: 'assistant', depuis: '2026-10-11T09:38:00.000Z', mesure: 'Le garde a refusé une écriture (PreToolUse, événement 5130).', quoi_faire: 'Lire le refus dans le terminal.' });
    },
  },
  { t: 48000, commentaire: 'animation 3 : worker-page-donnees se met au repos', patch(e) { Object.assign(trouver(e, 'worker-page-donnees'), { etat: 'au_repos', etat_source: 'hook:Stop' }); } },
  { t: 56000, commentaire: 'animation 2 : worker-page-donnees reprend, activité « lire » (activité facultative)', patch(e) { Object.assign(trouver(e, 'worker-page-donnees'), { etat: 'travaille', activite: 'lire', etat_source: 'hook:UserPromptSubmit' }); } },

  // Coûts (animation 23) : le fichier des tarifs est déposé, les coûts apparaissent.
  {
    t: 70000,
    commentaire: 'animation 23 : fichier des tarifs déposé par l’utilisateur, les coûts estimés apparaissent',
    patch(e) {
      const tarifs = e.sources.find((s) => s.nom === 'tarifs');
      tarifs.ok = true;
      delete tarifs.erreur;
      const couts = { assistant: 1.84, 'coord-observation': 3.12, 'coord-page': 1.05, 'coord-verification': 0.42, 'coord-hote': 0.77 };
      for (const [id, c] of Object.entries(couts)) trouver(e, id).cout_usd_estime = c;
    },
  },

  // Fin de boucle : l'ouvrier embauché repart, la boucle recommence depuis l'instantané initial.
  {
    t: 85000,
    commentaire: 'fin de boucle : worker-page-revue est rendu (le cycle repart de l’instantané initial)',
    patch(e) {
      e.agents = e.agents.filter((a) => a.id !== 'worker-page-revue');
      e.ordres = e.ordres.filter((o) => o.id !== 6);
    },
  },
];

export const PAS = BRUT.map((pas) => {
  if (!pas.patch) return pas;
  return {
    ...pas,
    patch(e) {
      pas.patch(e);
      suivreStatuts(e);
    },
  };
});
