// interaction.js — zones de clic, infobulles et évènement de jonction avec la page.
// Aucune action : un clic émet « scene:ouvrir » sur document, la page décidera.
// L'infobulle n'affiche jamais de texte libre privé (ni résumé, ni brouillon, ni dernière phrase).

const dedans = (z, x, y) => x >= z.x && x < z.x + z.w && y >= z.y && y < z.y + z.h;

export function elementSous(scene, x, y) {
  for (let i = scene.enveloppes.length - 1; i >= 0; i--) {
    const e = scene.enveloppes[i];
    if (dedans(e.zone, x, y)) return { type: 'enveloppe', id: e.id };
  }
  for (let i = scene.agents.length - 1; i >= 0; i--) {
    const a = scene.agents[i];
    if (dedans(a.zone, x, y)) return { type: 'agent', id: a.id };
  }
  // Ni enveloppe ni agent : la pièce sous le point (équipe, Assistant, l’utilisateur). Le couloir et les emplacements libres : rien.
  for (const p of scene.pieces ?? []) {
    if (dedans(p, x, y)) return { type: 'piece', id: p.nom };
  }
  return null;
}

// Ce que la scène désigne à la page : { type: 'equipe', nom } | { type: 'agent', id } | { type: 'message', id } | { type: 'utilisateur' },
// ou null (décor, salle de l'Assistant). La scène ne navigue jamais : elle nomme, la page ouvre.
export function cibleDe(scene, el) {
  if (!el) return null;
  if (el.type === 'enveloppe') return { type: 'message', id: el.id };
  if (el.type === 'agent') {
    return scene.agents.find((a) => a.id === el.id)?.role === 'utilisateur' ? { type: 'utilisateur' } : { type: 'agent', id: el.id };
  }
  if (el.type === 'piece') {
    if (el.id === 'utilisateur') return { type: 'utilisateur' };
    if (el.id === 'assistant') return null;
    return { type: 'equipe', nom: el.id };
  }
  return null;
}

// Le rectangle (en pixels de l'étage) que la scène entoure pour une cible sélectionnée par la page, ou null si la cible
// n'est pas (ou plus) à l'écran. Même vocabulaire que cibleDe : equipe, agent, message, utilisateur.
export function zoneDeCible(scene, cible) {
  if (!cible) return null;
  const piece = (nom) => scene.pieces?.find((p) => p.nom === nom);
  if (cible.type === 'equipe') return piece(cible.nom) ?? null;
  if (cible.type === 'utilisateur') return piece('utilisateur') ?? null;
  if (cible.type === 'agent') return scene.agents.find((a) => a.id === cible.id)?.zone ?? null;
  if (cible.type === 'message') return scene.enveloppes.find((e) => e.id === cible.id)?.zone ?? null;
  return null;
}

// Les mots de la scène pour une info-bulle : ceux de la légende, jamais une valeur brute du registre.
const LIBELLE_STATUT_PIECE = { lumiere: 'active', tamisee: 'au repos', attend: 'en attente', rouge: 'alarme grave', grisee: 'terminée', hachuree: 'non mesuré' };
const LIBELLE_ETAT_AGENT = {
  travaille: 'travaille',
  au_repos: 'au repos',
  endormi: 'au repos',
  attend_reponse: 'attend une réponse',
  attend_autorisation: 'attend une autorisation',
  inconnu: 'non mesuré',
};
const LIBELLE_ETAT_MESSAGE = { inscrit: 'inscrit', livre: 'livré', pris_en_compte: 'pris en compte', clos: 'clos', echec: 'échec', abandonne: 'abandonné' };
const LIBELLE_NATURE = {
  travail_pret: 'travail prêt',
  reponse: 'réponse',
  decision_utilisateur: 'décision',
  donnee_utilisateur: 'donnée',
  rapport_utilisateur: 'compte rendu',
};
export const TACHE_MAX = 80; // la tâche d'un agent peut faire deux cents caractères : l'info-bulle n'en montre que le début

const nomAffiche = (id) => (id === 'assistant' ? 'Assistant' : id === 'utilisateur' ? 'Utilisateur' : id);
const tronquer = (texte, max) => ([...texte].length <= max ? texte : `${[...texte].slice(0, max - 1).join('').trimEnd()}…`);

export function infobulle(scene, type, id) {
  if (type === 'agent') {
    const a = scene.agents.find((g) => g.id === id);
    if (!a) return null;
    if (a.role === 'utilisateur') return { titre: 'Utilisateur', lignes: [] };
    // Un agent arrêté sans alarme grave est en pause (le choix des coordinateurs au repos), pas en défaut.
    const etat = a.etat === 'arrete' ? (a.halo === 'rouge' ? 'arrêté' : 'en pause') : LIBELLE_ETAT_AGENT[a.etat] ?? 'non mesuré';
    const lignes = [etat];
    if (a.tache) lignes.push(tronquer(a.tache, TACHE_MAX));
    return { titre: a.id, lignes };
  }
  if (type === 'enveloppe') {
    const e = scene.enveloppes.find((g) => g.id === id);
    if (!e) return null;
    const etat = LIBELLE_ETAT_MESSAGE[e.etat] ?? e.etat;
    if (!e.de || !e.a) return { titre: `message ${e.id}`, lignes: [etat] };
    const nature = e.nature ? [LIBELLE_NATURE[e.nature] ?? e.nature.replace(/_/g, ' ')] : [];
    return { titre: `${nomAffiche(e.de)} → ${nomAffiche(e.a)}`, lignes: [...nature, etat] };
  }
  if (type === 'piece') {
    const p = scene.pieces.find((g) => g.nom === id);
    if (!p || p.nom === 'assistant') return null;
    if (p.nom === 'utilisateur') return { titre: 'Utilisateur', lignes: [] };
    const lignes = [LIBELLE_STATUT_PIECE[p.statut] ?? 'non mesuré'];
    if (p.attentes) lignes.push(p.attentes === 1 ? '1 point attend l’utilisateur' : `${p.attentes} points attendent l’utilisateur`);
    return { titre: p.libelle, lignes };
  }
  return null;
}

export function cliquer(doc, scene, x, y) {
  const el = elementSous(scene, x, y);
  if (!el) return null;
  doc.dispatchEvent(new CustomEvent('scene:ouvrir', { detail: el }));
  return el;
}

// Gestes sur le port de l'étage. Chaque geste rend un ordre (zoom d'un palier, déplacement, tout voir, clic)
// et ne touche pas à la vue : c'est l'appelant qui la recalcule (vue.js).
export const SEUIL_DEPLACEMENT_PX = 4; // pointeur appuyé qui bouge au-delà : c'est un glisser, jamais un clic
export const SEUIL_MOLETTE = 100; // deltaY cumulé pour un palier à la molette
export const SEUIL_PINCEMENT_MOLETTE = 24; // pincement du trackpad (molette avec ctrlKey) : petits deltas
export const DELAI_PALIER_MS = 180; // pas deux paliers à moins de ce délai (trackpad qui n'en finit pas)
export const FACTEUR_PINCEMENT = 1.25; // un palier pour un écartement des doigts multiplié ou divisé par ce facteur

export function creerGestes(el, { zoomer, deplacer, toutVoir, clic }) {
  const pointeurs = new Map(); // identifiant de pointeur → position relative à el
  let appui = null; // premier appui du geste en cours
  let dernier = null; // dernière position connue d'un pointeur seul
  let glisse = false; // le geste en cours a bougé : son relâchement ne déclenche pas de clic
  let ecartement = null; // écart des deux doigts au dernier palier de pincement
  const molette = { acc: 0, t: -Infinity };

  const relatif = (ev) => {
    const r = el.getBoundingClientRect();
    return { x: ev.clientX - r.left, y: ev.clientY - r.top };
  };
  const ecart = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);

  el.addEventListener('pointerdown', (ev) => {
    pointeurs.set(ev.pointerId, relatif(ev));
    if (pointeurs.size === 1) {
      appui = dernier = pointeurs.get(ev.pointerId);
      glisse = false;
      ecartement = null;
    } else if (pointeurs.size === 2) {
      glisse = true;
      const [a, b] = pointeurs.values();
      ecartement = ecart(a, b);
    }
  });

  el.addEventListener('pointermove', (ev) => {
    if (!pointeurs.has(ev.pointerId)) return;
    const p = relatif(ev);
    pointeurs.set(ev.pointerId, p);
    if (pointeurs.size === 1) {
      if (!glisse) {
        if (ecart(p, appui) <= SEUIL_DEPLACEMENT_PX) return;
        glisse = true;
        deplacer(p.x - appui.x, p.y - appui.y);
      } else {
        deplacer(p.x - dernier.x, p.y - dernier.y);
      }
      dernier = p;
    } else if (pointeurs.size === 2 && ecartement > 0) {
      const [a, b] = pointeurs.values();
      const e = ecart(a, b);
      if (e <= 0) return;
      const milieu = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
      if (e >= ecartement * FACTEUR_PINCEMENT) {
        zoomer(1, milieu);
        ecartement = e;
      } else if (e * FACTEUR_PINCEMENT <= ecartement) {
        zoomer(-1, milieu);
        ecartement = e;
      }
    }
  });

  const relache = (ev) => {
    if (!pointeurs.delete(ev.pointerId)) return;
    if (pointeurs.size === 1) dernier = pointeurs.values().next().value;
    if (pointeurs.size < 2) ecartement = null;
  };
  el.addEventListener('pointerup', relache);
  el.addEventListener('pointercancel', relache);

  el.addEventListener('click', (ev) => {
    if (glisse) {
      glisse = false;
      return;
    }
    if (ev.detail >= 2) return; // deuxième clic d'un double-clic : c'est « tout voir », pas une deuxième fiche
    clic(relatif(ev));
  });

  el.addEventListener('dblclick', () => toutVoir());

  el.addEventListener(
    'wheel',
    (ev) => {
      ev.preventDefault();
      const seuil = ev.ctrlKey ? SEUIL_PINCEMENT_MOLETTE : SEUIL_MOLETTE;
      if (Math.sign(molette.acc) !== Math.sign(ev.deltaY)) molette.acc = 0;
      molette.acc += ev.deltaY;
      if (Math.abs(molette.acc) < seuil) return;
      const sens = molette.acc < 0 ? 1 : -1; // molette vers le haut : zoom avant
      molette.acc = 0;
      const t = ev.timeStamp ?? 0;
      if (t - molette.t < DELAI_PALIER_MS) return;
      molette.t = t;
      zoomer(sens, relatif(ev));
    },
    { passive: false },
  );
}
