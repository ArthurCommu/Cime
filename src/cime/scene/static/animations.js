// animations.js — la table « fait → animation » (donnée exportée) et animationAgent (fonction pure)
// qui l'applique à un agent. Règle de sincérité : une animation n'existe que si un fait la motive.
// Le champ agents[].activite est facultatif : sans lui, un agent qui travaille tape simplement.

export const SEUIL_CONTEXTE_AMBRE = 0.6;
// Les alarmes graves qui disent seulement qu'on attend quelqu'un : halo ambre ; toute autre alarme grave est un problème (rouge).
export const TYPES_ATTENTE = Object.freeze(['autorisation_en_attente', 'question_sans_reponse']);
export const ETATS_AGENT = ['travaille', 'au_repos', 'attend_autorisation', 'attend_reponse', 'arrete'];
export const ACTIVITES = Object.freeze({
  ecrire: { anim: 'ecrire', ecran: 'ecran.texte' },
  lire: { anim: 'lire', ecran: 'ecran.lecture' },
  executer: { anim: 'executer', ecran: 'ecran.terminal' },
  reflechir: { anim: 'reflechir', ecran: 'ecran.pensee' },
});

// Numéro de l'animation, ce qu'on voit, déclencheur lisible, champ de l'état qui la motive, condition, couleur.
export const TABLE = Object.freeze([
  { id: 1, animation: 'assis, taper', declencheur: 'agent travaille, sans activité connue (hypothèse : champ absent)', champ: 'agents[].etat', condition: 'etat == "travaille" et activite absent', couleur: 'normal' },
  { id: 2, animation: 'ecrire / lire / executer / reflechir, écran du bureau correspondant', declencheur: 'agent travaille avec une activité connue (champ facultatif)', champ: 'agents[].etat + agents[].activite', condition: 'etat == "travaille" et activite ∈ {ecrire, lire, executer, reflechir}', couleur: 'normal' },
  { id: 3, animation: 'dormir + bulle zzz', declencheur: 'agent au repos', champ: 'agents[].etat', condition: 'etat == "au_repos"', couleur: 'normal' },
  { id: 4, animation: 'attend_reponse + bulle question ; enveloppe de la question visible vers le destinataire', declencheur: 'agent qui attend une réponse ; arête ouverte', champ: 'agents[].etat, aretes[]', condition: 'etat == "attend_reponse"', couleur: 'normal' },
  { id: 5, animation: 'attend_autorisation + bulle exclamation ambre + halo ambre', declencheur: 'agent qui attend une autorisation', champ: 'agents[].etat', condition: 'etat == "attend_autorisation"', couleur: 'ambre' },
  { id: 6, animation: 'coordinateur arrêté : chaise vide, bureau vide (un worker arrêté n’a pas de poste : voir 27)', declencheur: 'agent arrêté, coordinateur', champ: 'agents[].role, agents[].etat', condition: 'etat == "arrete" et role == "coordinateur"', couleur: 'gris' },
  { id: 7, animation: 'silhouette grise, jauges grises « ? »', declencheur: 'agent inconnu, non mesuré ou donnée absente', champ: 'agents[].etat, agents[].vivant', condition: 'etat == "inconnu" ou vivant == null ou etat absent', couleur: 'gris' },
  { id: 8, animation: 'sieste ; icône de refus rouge si l’ordre a échoué', declencheur: 'ordre de compactage en cours ou en échec', champ: 'ordres[]', condition: 'verbe == "compacter", cible == agent.id, etat ∈ {en_file, execute} ; etat == "echec" → refus rouge', couleur: 'rouge' },
  { id: 9, animation: 'arrive (embauche) puis bureau occupé', declencheur: 'agent apparu entre deux instantanés, ou ordre lancer vers lui', champ: 'agents[].id, ordres[]', condition: 'id absent de l’instantané précédent (fenêtre de 2,5 s)', couleur: 'normal' },
  { id: 10, animation: 'fin_tache puis le bureau se vide', declencheur: 'ordre terminer exécuté, ou tâche rendue', champ: 'ordres[], agents[].tache', condition: 'verbe == "terminer", etat == "execute", cible == agent.id', couleur: 'normal' },
  { id: 11, animation: 'enveloppe inscrite, née sur le bureau de l’expéditeur', declencheur: 'transition inscrit', champ: 'flux[].transitions', condition: 'dernière transition etat == "inscrit"', couleur: 'normal' },
  { id: 12, animation: 'enveloppe livrée : le facteur la porte par le couloir jusqu’au bureau du destinataire', declencheur: 'transition livre', champ: 'flux[].transitions', condition: 'dernière transition etat == "livre"', couleur: 'normal' },
  { id: 13, animation: 'enveloppe prise en compte : ouverte chez le destinataire', declencheur: 'transition pris_en_compte', champ: 'flux[].transitions', condition: 'dernière transition etat == "pris_en_compte"', couleur: 'normal' },
  { id: 14, animation: 'enveloppe tamponnée puis disparue', declencheur: 'transition clos', champ: 'flux[].transitions', condition: 'dernière transition etat == "clos"', couleur: 'normal' },
  { id: 15, animation: 'enveloppe tombée au sol du couloir : rouge si une alarme grave livraison_echouee porte sur ce message, sinon grise', declencheur: 'transition echec ou abandonne', champ: 'flux[].transitions, alarmes[]', condition: 'dernière transition etat ∈ {echec, abandonne} ; rouge seulement avec alarmes[] type == "livraison_echouee", gravite == "grave", id finissant par msg-<id>', couleur: 'gris' },
  { id: 16, animation: 'facteur qui marche (4 directions) pendant qu’il porte ; idle ; dormir ; arrêté en rouge', declencheur: 'transition livre en cours ; facteur sans activité ; facteur arrêté', champ: 'facteur.arrete, flux[].transitions', condition: 'facteur.arrete == true → arrete (rouge)', couleur: 'rouge' },
  { id: 17, animation: 'porte de l’utilisateur : fermée / à lire (neutre) / à agir (ambre) avec compteur ambre', declencheur: 'attentes de l’utilisateur', champ: 'attentes_utilisateur[].nature', condition: 'agir si autorisation, decision, donnee ou cloture ; à lire si seulement des rapport', couleur: 'ambre' },
  { id: 18, animation: 'halo autour du poste de l’agent nommé : ambre si l’alarme dit seulement qu’on attend (autorisation_en_attente, question_sans_reponse), rouge pour toute autre alarme grave ; bordure rouge de la pièce si l’alarme ne nomme que l’équipe', declencheur: 'alarme grave qui nomme l’agent, ou seulement son équipe', champ: 'alarmes[]', condition: 'gravite == "grave" et agent ∈ agents[] (halo) ; agents[] vide et équipe ∈ equipes[] (bordure de la pièce)', couleur: 'rouge' },
  { id: 19, animation: 'marque ambre sur l’agent (pas rouge)', declencheur: 'alarme à voir qui concerne l’agent', champ: 'alarmes[]', condition: 'gravite == "a_voir" et agent ∈ agents[]', couleur: 'ambre' },
  { id: 20, animation: 'éclair de refus au-dessus de l’agent, ~3 s', declencheur: 'nouvelle alarme action_refusee pour l’agent', champ: 'alarmes[]', condition: 'type == "action_refusee" (fenêtre de 3 s)', couleur: 'ambre' },
  { id: 21, animation: 'sirène dans la pièce (rouge si grave, ambre sinon)', declencheur: 'alarmes de session, figeage ou livraison', champ: 'alarmes[]', condition: 'type ∈ {session_disparue, fige, livraison_echouee, livraison_bloquee, assistant_sourd, fin_sans_suite, bloque_au_demarrage}', couleur: 'rouge' },
  { id: 22, animation: 'jauge de contexte : remplissage = tokens / limite ; ambre au-delà de 60 % ; grise « ? » si absente', declencheur: 'contexte de l’agent', champ: 'agents[].contexte', condition: 'contexte.tokens / contexte.limite ; null → gris', couleur: 'ambre' },
  { id: 23, animation: 'compteur de coût (pièce et montant) ; « ? » gris si null', declencheur: 'coût estimé de l’agent', champ: 'agents[].cout_usd_estime', condition: 'nombre → montant ; null → « ? »', couleur: 'normal' },
  { id: 24, animation: 'pièce (bordure et sol) : lumière normale, tamisée, cadre clair neutre (l’équipe attend une réponse), rouge (alarme grave sur l’équipe seule), grisée (porte fermée), hachurée (non mesuré) ; pièce rouge sans cause visible : « ? » rouge dans l’en-tête', declencheur: 'statut de l’équipe ; alarme grave', champ: 'equipes[].statut, alarmes[]', condition: 'active / au_repos / bloquee / terminee / null ; bloquee n’est PAS rouge (cadre neutre : le halo ambre dit si l’utilisateur est attendu) ; rouge seulement par la ligne 18', couleur: 'normal' },
  { id: 25, animation: 'bulle « brouillon » : points de saisie, sans texte', declencheur: 'brouillon présent', champ: 'agents[].brouillon', condition: 'brouillon != null (le texte n’est jamais lu)', couleur: 'normal' },
  { id: 26, animation: 'rien — aucune animation, aucun texte', declencheur: 'conversation privée utilisateur ↔ Assistant', champ: 'resume, objet, derniere_phrase, brouillon.texte', condition: 'jamais lu par la scène', couleur: 'normal' },
  { id: 27, animation: 'worker arrêté : aucun poste ; signe de dossiers + « +N » dans l’en-tête de sa pièce (N = ses arrêtés) ; pas de compteur si N = 0', declencheur: 'worker arrêté d’une équipe de equipes[] (REPLIER = worker) ; il garde son poste 2,5 s après une fin de tâche', champ: 'agents[].role, agents[].etat, agents[].equipe, equipes[].nom', condition: 'role ∈ REPLIER et etat == "arrete" et equipe ∈ equipes[] ; inconnu jamais replié', couleur: 'gris' },
  { id: 28, animation: 'signe de dossiers + « hors organigramme : N » au bord gauche du couloir de la bande 0 ; « N+? » si les sessions sont inconnues', declencheur: 'agent d’une équipe absente de equipes[] (ni Assistant, ni l’utilisateur), ou session hors organigramme', champ: 'agents[].equipe, equipes[].nom, sessions_hors_organigramme', condition: 'N = agents hors organigramme + len(sessions_hors_organigramme) ; sessions null → « N+? » ; rien à compter et [] → aucun compteur', couleur: 'normal' },
]);

// Tous les noms de sprites que ces animations peuvent référencer (et seulement ceux-là).
const ANIMS_PERSO = ['idle', 'taper', 'ecrire', 'lire', 'executer', 'reflechir', 'dormir', 'sieste', 'attend_autorisation', 'attend_reponse', 'arrete', 'inconnu', 'arrive', 'fin_tache'];
const ROLES_PERSO = ['assistant', 'coordinateur', 'worker'];
export const NOMS_SPRITES = Object.freeze([
  ...ROLES_PERSO.flatMap((r) => ANIMS_PERSO.map((a) => `perso.${r}.${a}`)),
  'perso.utilisateur.idle', 'perso.utilisateur.inconnu',
  'perso.facteur.marche_haut', 'perso.facteur.marche_bas', 'perso.facteur.marche_gauche', 'perso.facteur.marche_droite',
  'perso.facteur.idle', 'perso.facteur.dormir', 'perso.facteur.arrete',
  'meuble.bureau', 'meuble.bureau_vide', 'meuble.chaise',
  'ecran.eteint', 'ecran.texte', 'ecran.lecture', 'ecran.terminal', 'ecran.pensee',
  'sol.piece', 'sol.couloir', 'mur.haut', 'mur.cote', 'mur.angle', 'porte.piece',
  'porte.utilisateur.fermee', 'porte.utilisateur.attente', 'porte.utilisateur.agir',
  'plante', 'panneau.equipe', 'machine.cafe',
  'enveloppe.inscrit', 'enveloppe.livre', 'enveloppe.pris_en_compte', 'enveloppe.clos', 'enveloppe.echec', 'enveloppe.abandonne', 'enveloppe.echec_gris', 'enveloppe.abandonne_gris',
  'bulle.exclamation', 'bulle.question', 'bulle.zzz', 'bulle.pensee', 'bulle.coche',
  'icone.cout', 'icone.contexte', 'icone.inconnu', 'jauge.cadre',
  'alerte.halo', 'alerte.refus_garde', 'alerte.sirene', 'alerte.cause_inconnue', 'attente.halo', 'attente.sirene',
]);

export function nomSprite(role, anim) {
  return `perso.${role}.${anim}`;
}

// Index construit une fois par instantané : évite de rebalayer les listes pour chaque agent.
export function indexer(etat) {
  const idx = { alarmesPar: new Map(), alarmesEquipe: new Map(), ordres: new Map() };
  const pousser = (carte, cle, valeur) => {
    if (!carte.has(cle)) carte.set(cle, []);
    carte.get(cle).push(valeur);
  };
  for (const a of etat.alarmes ?? []) {
    for (const id of a.agents ?? []) pousser(idx.alarmesPar, id, a);
    for (const e of a.equipes ?? []) pousser(idx.alarmesEquipe, e, a);
  }
  for (const o of etat.ordres ?? []) pousser(idx.ordres, o.cible, o);
  return idx;
}

// Alarmes qui concernent l'agent : directement (agents[]) ou par son équipe (equipes[]).
function alarmesDe(idx, agent) {
  const directes = idx.alarmesPar.get(agent.id) ?? [];
  const parEquipe = agent.equipe ? idx.alarmesEquipe.get(agent.equipe) ?? [] : [];
  return [...new Set([...directes, ...parEquipe])];
}

export function jauge(contexte, inconnu = false) {
  if (inconnu || !contexte || contexte.tokens == null || !contexte.limite) {
    return { niveau: null, couleur: 'gris', inconnu: true };
  }
  const niveau = Math.min(1, contexte.tokens / contexte.limite);
  return { niveau, couleur: niveau > SEUIL_CONTEXTE_AMBRE ? 'ambre' : 'normal', inconnu: false };
}

export function cout(montant, inconnu = false) {
  if (inconnu || typeof montant !== 'number') return { texte: '?', couleur: 'gris' };
  return { texte: montant.toFixed(2), couleur: 'normal' };
}

// contexte = { idx (de indexer), ephemere: Map id → { type, debut } }
// Retour : ce qu'il faut dessiner pour l'agent. raisons = ids des lignes de la table déclenchées ;
// raison = la principale (celle qui explique le sprite).
export function animationAgent(agent, contexte = {}) {
  const idx = contexte.idx ?? indexer({});
  const eph = contexte.ephemere?.get(agent.id)?.type ?? null;
  const raisons = [];
  const retenir = (n) => {
    if (!raisons.includes(n)) raisons.push(n);
  };
  const out = {
    sprite: null, ecran: null, bulle: null, halo: null, jauge: null, cout: null,
    couleur: 'normal', marque: null, alerte: null, brouillon: false,
    bureau: 'plein', chaise: 'occupee', raison: null, raisons,
  };

  if (agent.role === 'utilisateur') {
    out.sprite = 'perso.utilisateur.idle';
    return out;
  }
  const role = agent.role;
  const inconnu = agent.vivant == null || agent.etat === 'inconnu' || !ETATS_AGENT.includes(agent.etat);
  const ordres = idx.ordres.get(agent.id) ?? [];
  const alarmes = alarmesDe(idx, agent);
  const alarmesDirectes = idx.alarmesPar.get(agent.id) ?? [];

  // Ligne principale : évènement éphémère, ordre, puis état.
  let ligneSprite = null;
  let spriteAnim = null;

  if (inconnu) {
    ligneSprite = 7;
    spriteAnim = 'inconnu';
    out.couleur = 'gris';
    out.jauge = jauge(null, true);
    out.cout = cout(null, true);
  } else {
    const compacter = ordres.find((o) => o.verbe === 'compacter' && (o.etat === 'en_file' || o.etat === 'execute'));
    const echecCompacter = ordres.find((o) => o.verbe === 'compacter' && o.etat === 'echec');
    const fin = ordres.find((o) => o.verbe === 'terminer' && o.etat === 'execute');

    switch (agent.etat) {
      case 'travaille':
        if (ACTIVITES[agent.activite]) {
          ligneSprite = 2;
          spriteAnim = ACTIVITES[agent.activite].anim;
          out.ecran = ACTIVITES[agent.activite].ecran;
        } else {
          ligneSprite = 1; // hypothèse : absence d'activité → taper, jamais une activité devinée
          spriteAnim = 'taper';
          out.ecran = 'ecran.eteint';
        }
        break;
      case 'au_repos':
        ligneSprite = 3;
        spriteAnim = 'dormir';
        out.bulle = 'zzz';
        break;
      case 'attend_reponse':
        ligneSprite = 4;
        spriteAnim = 'attend_reponse';
        out.bulle = 'question';
        break;
      case 'attend_autorisation':
        ligneSprite = 5;
        spriteAnim = 'attend_autorisation';
        out.bulle = 'exclamation';
        out.halo = 'ambre'; // une autorisation attendue n'est pas un problème : ambre
        retenir(5);
        out.couleur = 'ambre';
        break;
      case 'arrete':
        ligneSprite = 6;
        out.bureau = 'vide';
        out.chaise = 'vide';
        out.couleur = 'gris';
        break;
    }

    // Évènements : arrivée (9), fin de tâche (10), sieste (8) — ils priment sur l'état pour le sprite.
    if (eph === 'arrive') {
      ligneSprite = 9;
      spriteAnim = 'arrive';
    } else if (eph === 'fin_tache' || fin) {
      ligneSprite = 10;
      spriteAnim = 'fin_tache';
    } else if (compacter) {
      ligneSprite = 8;
      spriteAnim = 'sieste';
    }
    if (spriteAnim && ['arrive', 'fin_tache', 'sieste'].includes(spriteAnim)) {
      out.bureau = 'plein';
      out.chaise = 'occupee';
    }
    if (ligneSprite !== null) retenir(ligneSprite);
    if (echecCompacter) {
      out.alerte = { couleur: 'rouge' };
      retenir(8);
      out.couleur = 'rouge';
    }

    // 22 et 23 : jauge et coût, toujours montrés (grisés si la donnée manque).
    out.jauge = jauge(agent.contexte);
    out.cout = cout(agent.cout_usd_estime);
    retenir(22);
    retenir(23);
  }

  // Sprite : un agent arrêté sans évènement n'a aucun personnage (chaise vide).
  if (inconnu) {
    retenir(7);
    out.sprite = nomSprite(role, 'inconnu');
  } else if (spriteAnim) {
    out.sprite = nomSprite(role, spriteAnim);
  }
  // Raison principale : la ligne qui explique le sprite affiché.
  out.raison = ligneSprite ?? raisons[0] ?? null;

  // 18 : alarme grave qui NOMME l'agent (alarmes[].agents) → halo rouge. Une alarme grave qui ne nomme que son
  // équipe ne donne aucun halo : c'est la bordure de la pièce qui passe au rouge (modele.js, piecesDe).
  // Une alarme grave de type « on attend » (autorisation, réponse) donne le halo ambre ; les autres, le halo rouge, qui l'emporte.
  const graves = alarmesDirectes.filter((a) => a.gravite === 'grave');
  if (graves.length) {
    retenir(18);
    if (graves.some((a) => !TYPES_ATTENTE.includes(a.type))) {
      out.halo = 'rouge';
      out.couleur = 'rouge';
    } else {
      out.halo = 'ambre';
      if (out.couleur === 'normal' || out.couleur === 'gris') out.couleur = 'ambre';
    }
  }
  // 19 : alarme à voir sur l'agent → marque ambre (jamais rouge).
  if (alarmesDirectes.some((a) => a.gravite === 'a_voir')) {
    out.marque = 'ambre';
    retenir(19);
    if (out.couleur === 'normal' || out.couleur === 'gris') out.couleur = 'ambre';
  }
  // 20 : éclair de refus pendant 3 s après l'arrivée de l'alarme.
  if (eph === 'refus') {
    out.alerte = out.alerte ?? { couleur: 'ambre' };
    retenir(20);
  }
  // 25 : brouillon présent — la scène n'en lit jamais le texte.
  if (agent.brouillon != null) {
    out.brouillon = true;
    retenir(25);
  }
  return out;
}
