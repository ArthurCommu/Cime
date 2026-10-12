// modele.js — fonctions pures : évènements entre deux instantanés, trajets des enveloppes,
// et assemblage de la scène. Aucune écriture, aucun appel réseau, aucun texte libre.

import { disposition } from './plan.js';
import { animationAgent, indexer } from './animations.js';

export const ETAPE_MS = 1200; // durée d'une étape du couloir
export const DUREE_CLOS_MS = 2000; // tampon avant disparition
export const MAX_ANIMEES = 30; // enveloppes animées simultanément ; au-delà, posées sans animer
export const DUREE_FACTEUR_DORT_MS = 60000; // facteur au repos depuis ce délai → dormir
export const DUREES_EPHEMERES = Object.freeze({ arrive: 2500, fin_tache: 2500, refus: 3000 });

const NATURES_BLOQUANTES = ['autorisation', 'decision', 'donnee', 'cloture'];
const TYPES_SIRENE = ['session_disparue', 'fige', 'livraison_echouee', 'livraison_bloquee', 'assistant_sourd', 'fin_sans_suite', 'bloque_au_demarrage'];
// « bloquee » (un agent attend une réponse ou une autorisation) n'est pas un problème : rouge est réservé à l'alarme grave.
const STATUT_PIECE = { active: 'lumiere', au_repos: 'tamisee', bloquee: 'attend', terminee: 'grisee' };
const COULEUR_PIECE = { lumiere: 'normal', tamisee: 'normal', attend: 'normal', rouge: 'rouge', grisee: 'gris', hachuree: 'gris' };
const RAISON_ENVELOPPE = { inscrit: 11, livre: 12, pris_en_compte: 13, clos: 14, echec: 15, abandonne: 15 };
const ETAT_VIDE = Object.freeze({ agents: [], equipes: [], flux: [], ordres: [], alarmes: [], aretes: [], attentes_utilisateur: [], facteur: null });

// Ce qui change entre deux instantanés. Les arrivées ne sont jamais déduites d'un premier chargement.
export function evenements(precedent, etat) {
  if (!precedent) return [];
  const out = [];
  const avant = new Set((precedent.agents ?? []).map((a) => a.id));
  const tachePrec = new Map((precedent.agents ?? []).map((a) => [a.id, a.tache ?? null]));
  for (const a of etat.agents ?? []) {
    if (!avant.has(a.id)) out.push({ type: 'arrive', agent: a.id });
    else if (a.role === 'worker' && tachePrec.get(a.id) && !a.tache) out.push({ type: 'fin_tache', agent: a.id });
  }
  const ordresAvant = new Map((precedent.ordres ?? []).map((o) => [o.id, o.etat]));
  for (const o of etat.ordres ?? []) {
    if (ordresAvant.get(o.id) === o.etat) continue;
    if (o.verbe === 'terminer' && o.etat === 'execute') out.push({ type: 'fin_tache', agent: o.cible });
    if (o.verbe === 'compacter' && (o.etat === 'en_file' || o.etat === 'execute')) out.push({ type: 'sieste', agent: o.cible });
    if (o.verbe === 'lancer' && !ordresAvant.has(o.id) && !avant.has(o.cible)) out.push({ type: 'arrive', agent: o.cible });
  }
  const alarmesAvant = new Set((precedent.alarmes ?? []).map((a) => a.id));
  for (const a of etat.alarmes ?? []) {
    const cible = a.agents?.[0];
    if (a.type === 'action_refusee' && !alarmesAvant.has(a.id) && cible) out.push({ type: 'refus', agent: cible });
  }
  return out;
}

// Trajet d'une enveloppe : points du couloir et durée d'animation. Une enveloppe sans trajet
// en cours est posée à son point final (pris en compte chez le destinataire, échec au sol...).
export function trajet(tr, plan) {
  const pDe = plan.pointBureau(tr.de);
  const pA = plan.pointBureau(tr.a);
  const chemin = plan.points(plan.cheminFacteur(plan.noeudDeAgent(tr.de), plan.noeudDeAgent(tr.a)));
  switch (tr.etat) {
    case 'inscrit':
      return { pts: [pDe], duree: 0 };
    case 'livre': {
      const pts = [pDe, ...chemin, pA];
      return { pts, duree: (pts.length - 1) * ETAPE_MS };
    }
    case 'pris_en_compte':
      return { pts: [pA], duree: 0 };
    case 'clos':
      return { pts: [pA], duree: DUREE_CLOS_MS };
    case 'echec':
    case 'abandonne': {
      const complet = [pDe, ...chemin];
      const pts = complet.slice(0, Math.max(2, Math.ceil(complet.length / 2)));
      return { pts, duree: (pts.length - 1) * ETAPE_MS };
    }
    default:
      return null;
  }
}

function direction(dx, dy) {
  if (dx === 0 && dy === 0) return null;
  if (Math.abs(dx) >= Math.abs(dy)) return dx > 0 ? 'droite' : 'gauche';
  return dy > 0 ? 'bas' : 'haut';
}

// Position le long des points après « age » ms. Au-delà de la durée, le dernier point.
export function positionA(pts, age) {
  const n = pts.length - 1;
  if (n <= 0 || age >= n * ETAPE_MS) {
    const p = pts[pts.length - 1];
    return { x: p.x, y: p.y, dir: null };
  }
  const seg = Math.floor(age / ETAPE_MS);
  const f = (age - seg * ETAPE_MS) / ETAPE_MS;
  const a = pts[seg];
  const b = pts[seg + 1];
  return { x: a.x + (b.x - a.x) * f, y: a.y + (b.y - a.y) * f, dir: direction(b.x - a.x, b.y - a.y) };
}

// Le fil : applique les instantanés et les transitions au fil du temps.
export function creerFil() {
  return { etat: null, precedent: null, evenements: [], ephemeres: new Map(), mouvements: new Map(), dernierLivre: null };
}

export function appliquerSnapshot(fil, etat, transitions = [], t = 0, { reset = false } = {}) {
  if (reset) Object.assign(fil, creerFil());
  const evts = evenements(fil.etat, etat);
  for (const ev of evts) {
    if (DUREES_EPHEMERES[ev.type]) fil.ephemeres.set(ev.agent, { type: ev.type, debut: t });
  }
  fil.precedent = fil.etat;
  fil.etat = etat;
  fil.evenements = evts;
  for (const tr of transitions) {
    fil.mouvements.set(tr.id, { etat: tr.etat, debut: t });
    if (tr.etat === 'livre') fil.dernierLivre = t;
  }
  for (const [agent, v] of fil.ephemeres) {
    if (t - v.debut >= DUREES_EPHEMERES[v.type]) fil.ephemeres.delete(agent);
  }
  return fil;
}

// Les messages qu'une alarme grave de livraison (livraison_echouee:<agent>:msg-<n>) porte : seuls leurs échecs sont rouges.
function messagesEnAlarme(etat) {
  const ids = new Set();
  for (const a of etat.alarmes ?? []) {
    const m = a.gravite === 'grave' && a.type === 'livraison_echouee' ? /msg-(\d+)$/.exec(String(a.id)) : null;
    if (m) ids.add(m[1]);
  }
  return ids;
}

// Un échec ou un abandon n'est rouge que tant qu'une alarme grave porte sur ce message ; sinon il reste visible, en gris.
function aspectEnveloppe(it, enAlarme) {
  if (it.etat !== 'echec' && it.etat !== 'abandonne') return { sprite: `enveloppe.${it.etat}`, couleur: 'normal' };
  return enAlarme.has(String(it.id)) ? { sprite: `enveloppe.${it.etat}`, couleur: 'rouge' } : { sprite: `enveloppe.${it.etat}_gris`, couleur: 'gris' };
}

function enveloppesDe(etat, plan, t, mouvements) {
  const enAlarme = messagesEnAlarme(etat);
  const candidats = [];
  for (const it of etat.flux ?? []) {
    if (!Object.hasOwn(RAISON_ENVELOPPE, it.etat)) continue;
    const tj = trajet({ etat: it.etat, de: it.de, a: it.a }, plan);
    if (!tj) continue;
    const m = mouvements.get(it.id);
    const age = m && m.etat === it.etat ? t - m.debut : Infinity;
    candidats.push({ it, tj, age, debut: m?.debut ?? -Infinity });
  }
  // Animable : une durée non nulle (trajet, ou tampon d'une enveloppe clos) et pas encore écoulée.
  const animables = candidats
    .filter((c) => c.age < c.tj.duree)
    .sort((a, b) => b.debut - a.debut)
    .slice(0, MAX_ANIMEES);
  const animes = new Set(animables.map((c) => c.it.id));

  const out = [];
  for (const c of candidats) {
    const animee = animes.has(c.it.id);
    const age = animee ? c.age : Infinity;
    if (c.it.etat === 'clos' && age >= DUREE_CLOS_MS) continue; // tamponnée puis disparue
    const p = positionA(c.tj.pts, age);
    out.push({
      id: c.it.id,
      etat: c.it.etat,
      de: c.it.de ?? null, // l'info-bulle dit qui écrit à qui et de quel genre : jamais le résumé
      a: c.it.a ?? null,
      nature: c.it.nature ?? null,
      x: p.x,
      y: p.y,
      dir: animee ? p.dir : null,
      animee,
      porteur: animee && c.it.etat === 'livre',
      ...aspectEnveloppe(c.it, enAlarme),
      raison: RAISON_ENVELOPPE[c.it.etat],
      age: animee ? age : 0,
    });
  }
  // Enveloppes posées au même endroit : décalées pour rester lisibles.
  const vus = new Map();
  for (const e of out) {
    if (e.animee) continue;
    const cle = `${e.x},${e.y}`;
    const k = vus.get(cle) ?? 0;
    vus.set(cle, k + 1);
    e.x += k * 4;
  }
  return out;
}

function facteurDe(etat, plan, envs, inactifDepuisMs) {
  const home = plan.noeuds.get('assistant');
  const f = etat.facteur;
  if (!f) return { x: home.x, y: home.y, sprite: 'perso.facteur.idle', couleur: 'gris', raison: null, age: 0 };
  if (f.arrete) return { x: home.x, y: home.y, sprite: 'perso.facteur.arrete', couleur: 'rouge', raison: 16, age: 0 };
  const porteur = envs.find((e) => e.porteur);
  if (porteur) {
    const sprite = porteur.dir ? `perso.facteur.marche_${porteur.dir}` : 'perso.facteur.idle';
    return { x: porteur.x, y: porteur.y, sprite, couleur: 'normal', raison: porteur.dir ? 16 : null, age: 0 };
  }
  if (inactifDepuisMs > DUREE_FACTEUR_DORT_MS) {
    return { x: home.x, y: home.y, sprite: 'perso.facteur.dormir', couleur: 'normal', raison: 16, age: 0 };
  }
  return { x: home.x, y: home.y, sprite: 'perso.facteur.idle', couleur: 'normal', raison: null, age: 0 };
}

function porteDe(etat, plan) {
  const { x, y } = plan.porteUtilisateur.porte;
  const att = etat.attentes_utilisateur;
  if (!Array.isArray(att)) return { x, y, etat: 'inconnue', couleur: 'gris', compteur: 0, raison: null };
  const bloquantes = att.filter((a) => NATURES_BLOQUANTES.includes(a.nature)).length;
  // L’utilisateur doit agir : c'est l'attente par excellence, donc ambre (le rouge est réservé aux problèmes).
  if (bloquantes) return { x, y, etat: 'agir', couleur: 'ambre', compteur: bloquantes, raison: 17 };
  if (att.length) return { x, y, etat: 'attente', couleur: 'normal', compteur: att.length, raison: 17 };
  return { x, y, etat: 'fermee', couleur: 'normal', compteur: 0, raison: null };
}

function piecesDe(etat, plan) {
  const equipes = new Map((etat.equipes ?? []).map((e) => [e.nom, e]));
  const sirenes = new Map();
  for (const a of etat.alarmes ?? []) {
    if (!TYPES_SIRENE.includes(a.type)) continue;
    const lieux = new Set([...(a.equipes ?? []), ...(a.agents ?? []).map((id) => plan.sieges.get(id)?.piece).filter(Boolean)]);
    for (const lieu of lieux) {
      const niveau = a.gravite === 'grave' || sirenes.get(lieu) === 'rouge' ? 'rouge' : 'ambre';
      sirenes.set(lieu, niveau);
    }
  }
  // Animation 18 : une alarme grave qui ne nomme que des équipes met la bordure de leur pièce en rouge
  // (le halo, lui, n'entoure que les agents listés dans alarmes[].agents).
  const piecesGraves = new Set();
  for (const a of etat.alarmes ?? []) {
    if (a.gravite === 'grave' && !(a.agents ?? []).length) for (const e of a.equipes ?? []) piecesGraves.add(e);
  }
  // Combien de points d'attentes_utilisateur reviennent à chaque pièce : l'équipe de l'attente, sinon la pièce du siège de son
  // agent d'origine (l'Assistant qui porte une décision). Ni le registre ni `etat` n'y ajoutent rien.
  const attentes = new Map();
  for (const a of Array.isArray(etat.attentes_utilisateur) ? etat.attentes_utilisateur : []) {
    const lieu = a.equipe ?? plan.sieges.get(a.agent)?.piece;
    if (lieu) attentes.set(lieu, (attentes.get(lieu) ?? 0) + 1);
  }
  // L'Assistant et la salle de l’utilisateur ne sont pas des équipes : pas de statut, donc pas d'animation 24.
  return plan.pieces.map((p) => {
    const sansEquipe = p.nom === 'assistant' || p.nom === 'utilisateur';
    const grave = !sansEquipe && piecesGraves.has(p.nom);
    const statut = sansEquipe ? 'lumiere' : grave ? 'rouge' : STATUT_PIECE[equipes.get(p.nom)?.statut] ?? 'hachuree';
    return {
      ...p,
      // Texte affiché : « toi » pour la salle de l’utilisateur ; p.nom reste l’id (clics, tables).
      libelle: p.nom === 'utilisateur' ? 'toi' : p.nom,
      statut,
      couleur: COULEUR_PIECE[statut],
      raison: sansEquipe ? null : grave ? 18 : 24,
      sirene: sirenes.get(p.nom) ?? null,
      attentes: p.nom === 'utilisateur' ? 0 : attentes.get(p.nom) ?? 0, // halo ambre : quelqu'un attend l’utilisateur ici
    };
  });
}

// Assemble la scène. suivi = { t, ephemeres: Map id → {type, debut}, mouvements: Map message → {etat, debut},
// inactifDepuisMs, evenements }. Tout est dérivé de l'instantané et de ces entrées.
// Un worker arrêté qui finit sa tâche garde son poste le temps de sa fin de tâche (DUREES_EPHEMERES), puis se replie :
// le plan le voit encore au travail pendant ce temps. Ni la scène ni le plan ne changent d'autre donnée.
function etatPourPlan(etat, ephemeres, t) {
  const gardes = new Set(
    (etat.agents ?? [])
      .filter((a) => a.etat === 'arrete' && ephemeres.get(a.id)?.type === 'fin_tache' && t - ephemeres.get(a.id).debut < DUREES_EPHEMERES.fin_tache)
      .map((a) => a.id),
  );
  if (!gardes.size) return etat;
  return { ...etat, agents: etat.agents.map((a) => (gardes.has(a.id) ? { ...a, etat: 'au_repos' } : a)) };
}

export function construireScene(etatBrut, precedent = null, suivi = {}) {
  const etat = etatBrut ?? ETAT_VIDE;
  const t = suivi.t ?? 0;
  const ephemeres = suivi.ephemeres ?? new Map();
  const plan = disposition(etatPourPlan(etat, ephemeres, t));
  const idx = indexer(etat);
  const raisons = new Set();

  const agents = [];
  for (const ag of etat.agents ?? []) {
    const estUtilisateur = ag.role === 'utilisateur';
    const place = plan.sieges.get(ag.id);
    const ancre = estUtilisateur ? plan.posteUtilisateur : place?.siege; // L’utilisateur : dans sa pièce, derrière la porte
    if (!ancre) continue;
    const anim = animationAgent(ag, { idx, ephemere: ephemeres });
    anim.raisons.forEach((r) => raisons.add(r));
    const eph = ephemeres.get(ag.id);
    agents.push({
      id: ag.id,
      role: ag.role,
      equipe: ag.equipe ?? null,
      etat: ag.etat ?? null,
      tache: ag.tache ?? null,
      x: ancre.x,
      y: ancre.y,
      bureauRect: estUtilisateur ? null : place.bureau,
      pivot: estUtilisateur ? null : place.pivot,
      zone: estUtilisateur ? { x: ancre.x - 8, y: ancre.y - 18, w: 16, h: 19 } : { x: place.pivot.x - 16, y: place.pivot.y - 29, w: 32, h: 35 },
      age: eph ? t - eph.debut : 0,
      ...anim,
    });
  }

  const enveloppes = enveloppesDe(etat, plan, t, suivi.mouvements ?? new Map()).map((e) => ({
    ...e,
    zone: { x: e.x - 2, y: e.y - 2, w: 10, h: 8 },
  }));
  enveloppes.forEach((e) => e.raison && raisons.add(e.raison));

  const facteur = facteurDe(etat, plan, enveloppes, suivi.inactifDepuisMs ?? Infinity);
  if (facteur.raison) raisons.add(facteur.raison);

  const porte = porteDe(etat, plan);
  if (porte.raison) raisons.add(porte.raison);

  const pieces = piecesDe(etat, plan);
  for (const p of pieces) {
    if (p.raison) raisons.add(p.raison);
    if (p.sirene) raisons.add(21);
    if (p.compteur) raisons.add(27); // arrêtés repliés dans l'en-tête
  }
  if (plan.horsOrganigramme) raisons.add(28); // hors organigramme : compteur du couloir

  return {
    largeur: plan.largeur,
    hauteur: plan.hauteur,
    hauteurEtage: plan.hauteurEtage,
    legende: plan.legende,
    couloirs: plan.couloirs,
    videes: plan.videes,
    etage: plan.etage,
    horsOrganigramme: plan.horsOrganigramme,
    pieces,
    agents,
    enveloppes,
    facteur,
    porte,
    evenements: suivi.evenements ?? evenements(precedent, etat),
    raisons: [...raisons].sort((a, b) => a - b),
    manques: 0,
    t,
  };
}

// Scène à l'instant t d'un fil (sans avancer le fil).
export function sceneA(fil, t) {
  const ephemeres = new Map([...fil.ephemeres].filter(([, v]) => t - v.debut < DUREES_EPHEMERES[v.type]));
  const inactifDepuisMs = fil.dernierLivre == null ? Infinity : t - fil.dernierLivre;
  return construireScene(fil.etat, fil.precedent, {
    t,
    ephemeres,
    mouvements: fil.mouvements,
    inactifDepuisMs,
    evenements: fil.evenements,
  });
}
