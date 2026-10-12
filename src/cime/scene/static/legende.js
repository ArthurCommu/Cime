// legende.js — la légende de la scène : une table de données (sprite de l'ATLAS + libellé court) et sa mise en page.
// Rien n'est écrit en double : chaque signe est dessiné avec le sprite même que la scène utilise (rendu.js,
// dessinerLegende), et un test vérifie que tout signe que la scène dessine figure ici (tests/scene/js/legende.test.mjs).
//
// Une entrée : { groupe, sprite | motif, avec?, libelle, probleme? }
//   sprite   : nom d'un sprite de ATLAS.sprites, posé tel quel ;
//   avec     : sprites posés par-dessus, relativement au pivot du sprite (bulle d'un agent) ;
//   motif    : un signe que la scène peint avec des aplats (bordure de pièce, jauge, marque, brouillon, coût) ;
//   libelle  : une ligne ou deux (tableau), en français accentué, dans la police de la scène ;
//   probleme : le signe est un signe de problème. Seuls ceux-là ont le droit d'être rouges.

import { ATLAS, MONTAGE } from './graphismes/atlas.js';

const S = ATLAS.sprites;
const POLICE = ATLAS.police;
const TUILE = ATLAS.tuile;

export const GROUPES = Object.freeze({
  agent: 'Les agents',
  courrier: 'Le courrier et la porte de l’utilisateur',
  piece: 'Les pièces et les alertes',
  mesure: 'Les mesures et les marques',
});

// Une bulle posée sur un agent : relative au pivot du personnage (MONTAGE.bulle est relatif au bureau).
const BULLE = { dx: MONTAGE.bulle[0] - MONTAGE.perso[0], dy: MONTAGE.bulle[1] - MONTAGE.perso[1] };
const avecBulle = (nom) => [{ sprite: nom, ...BULLE }];

// Le halo entoure un poste : bureau, écran, personnage, posés comme dans la scène (MONTAGE, relatifs au pivot du halo).
const posteDuHalo = [
  { sprite: 'meuble.bureau', dx: 0, dy: 0 },
  { sprite: 'ecran.eteint', dx: MONTAGE.ecran[0], dy: MONTAGE.ecran[1] },
  { sprite: 'perso.worker.taper', dx: MONTAGE.perso[0], dy: MONTAGE.perso[1] },
];

export const LEGENDE = Object.freeze([
  { groupe: 'agent', sprite: 'perso.worker.taper', libelle: 'travaille' },
  { groupe: 'agent', sprite: 'perso.worker.ecrire', libelle: 'écrit' },
  { groupe: 'agent', sprite: 'perso.worker.lire', libelle: 'lit' },
  { groupe: 'agent', sprite: 'perso.worker.executer', libelle: 'exécute' },
  { groupe: 'agent', sprite: 'perso.worker.reflechir', libelle: 'réfléchit' },
  { groupe: 'agent', sprite: 'perso.worker.dormir', avec: avecBulle('bulle.zzz'), libelle: 'repos' },
  { groupe: 'agent', sprite: 'perso.worker.attend_reponse', avec: avecBulle('bulle.question'), libelle: ['attend', 'réponse'] },
  { groupe: 'agent', sprite: 'perso.worker.attend_autorisation', avec: avecBulle('bulle.exclamation'), libelle: ['attend', 'autorisation'] },
  { groupe: 'agent', sprite: 'meuble.bureau_vide', libelle: ['coordinateur', 'arrêté'] },
  { groupe: 'agent', sprite: 'perso.worker.inconnu', libelle: 'inconnu' },
  { groupe: 'agent', sprite: 'perso.worker.arrive', libelle: 'embauché' },
  { groupe: 'agent', sprite: 'perso.worker.fin_tache', libelle: ['tâche', 'finie'] },
  { groupe: 'agent', sprite: 'perso.worker.sieste', libelle: 'compactage' },
  { groupe: 'agent', sprite: 'perso.utilisateur.idle', libelle: 'Utilisateur' },

  { groupe: 'courrier', sprite: 'enveloppe.inscrit', libelle: 'inscrit' },
  { groupe: 'courrier', sprite: 'enveloppe.livre', libelle: 'livré' },
  { groupe: 'courrier', sprite: 'enveloppe.pris_en_compte', libelle: ['pris en', 'compte'] },
  { groupe: 'courrier', sprite: 'enveloppe.clos', libelle: 'clos' },
  { groupe: 'courrier', sprite: 'enveloppe.echec_gris', libelle: 'échec' },
  { groupe: 'courrier', sprite: 'enveloppe.abandonne_gris', libelle: 'abandon' },
  { groupe: 'courrier', sprite: 'enveloppe.echec', libelle: ['échec', 'alarme'], probleme: true },
  { groupe: 'courrier', sprite: 'enveloppe.abandonne', libelle: ['abandon', 'alarme'], probleme: true },
  { groupe: 'courrier', sprite: 'perso.facteur.marche_droite', libelle: 'facteur' },
  { groupe: 'courrier', sprite: 'perso.facteur.idle', libelle: ['facteur', 'attend'] },
  { groupe: 'courrier', sprite: 'perso.facteur.dormir', libelle: ['facteur', 'dort'] },
  { groupe: 'courrier', sprite: 'perso.facteur.arrete', libelle: ['facteur', 'arrêté'], probleme: true },
  { groupe: 'courrier', sprite: 'porte.utilisateur.fermee', libelle: ['rien pour', 'Utilisateur'] },
  { groupe: 'courrier', sprite: 'porte.utilisateur.attente', libelle: ['à lire', 'pour Utilisateur'] },
  { groupe: 'courrier', sprite: 'porte.utilisateur.agir', libelle: ['Utilisateur', 'doit agir'] },

  { groupe: 'piece', motif: 'bordure.lumiere', libelle: 'active' },
  { groupe: 'piece', motif: 'bordure.tamisee', libelle: 'au repos' },
  { groupe: 'piece', motif: 'bordure.attend', libelle: ['en', 'attente'] },
  { groupe: 'piece', motif: 'bordure.rouge', libelle: ['alarme', 'grave'], probleme: true },
  { groupe: 'piece', motif: 'bordure.grisee', libelle: 'terminée' },
  { groupe: 'piece', motif: 'halo.attente', libelle: ['attend', 'Utilisateur'] },
  { groupe: 'piece', sprite: 'porte.piece', libelle: ['porte', 'fermée'] },
  { groupe: 'piece', motif: 'bordure.hachuree', libelle: ['non', 'mesurée'] },
  { groupe: 'piece', sprite: 'alerte.cause_inconnue', libelle: ['cause', 'inconnue'], probleme: true },

  { groupe: 'piece', sprite: 'attente.halo', avec: posteDuHalo, libelle: ['agent', 'attend'] },
  { groupe: 'piece', sprite: 'alerte.halo', avec: posteDuHalo, libelle: ['agent', 'en alerte'], probleme: true },
  { groupe: 'piece', sprite: 'attente.sirene', libelle: ['alarme', 'à voir'] },
  { groupe: 'piece', sprite: 'alerte.sirene', libelle: ['alarme', 'grave'], probleme: true },
  { groupe: 'piece', sprite: 'alerte.refus_garde', libelle: ['refus du', 'garde'], probleme: true },
  { groupe: 'piece', sprite: 'compteur.dossiers', libelle: ['arrêtés', '+N'] },
  { groupe: 'piece', sprite: 'compteur.dossiers', libelle: ['hors', 'organigramme'] },
  { groupe: 'mesure', motif: 'marque', libelle: ['à', 'voir'] },
  { groupe: 'mesure', motif: 'brouillon', libelle: 'brouillon' },

  { groupe: 'mesure', motif: 'jauge.normale', libelle: 'contexte' },
  { groupe: 'mesure', motif: 'jauge.ambre', libelle: ['contexte', 'au-delà de 60 %'] },
  { groupe: 'mesure', motif: 'jauge.inconnue', libelle: ['contexte', 'non mesuré'] },
  { groupe: 'mesure', motif: 'cout', libelle: ['coût', 'estimé'] },
  { groupe: 'mesure', motif: 'cout.inconnu', libelle: ['coût', 'non mesuré'] },
]);

// Sprites que la scène dessine sans qu'ils soient un signe à expliquer : le décor et les postes.
export const DECOR = Object.freeze([
  'sol.piece', 'sol.couloir', 'mur.haut', 'plante', 'machine.cafe', 'meuble.bureau', 'meuble.chaise',
  'ecran.eteint', 'ecran.texte', 'ecran.lecture', 'ecran.terminal', 'ecran.pensee',
]);

// Sprites du catalogue que la scène ne dessine jamais aujourd'hui (un test le vérifie : dès qu'un d'eux est
// dessiné, il doit passer dans LEGENDE ou DECOR).
export const NON_DESSINES = Object.freeze([
  'perso.*.idle', 'perso.*.arrete', 'perso.utilisateur.inconnu', 'mur.cote', 'mur.angle', 'panneau.equipe',
  'bulle.pensee', 'bulle.coche', 'icone.contexte', 'icone.inconnu',
]);

// Un personnage porte les mêmes animations quel que soit son rôle ; le facteur marche dans quatre directions.
export const cleSigne = (nom) =>
  nom
    .replace(/^perso\.(assistant|coordinateur|worker)\./, 'perso.*.')
    .replace(/^(perso\.facteur\.marche)_.+$/, '$1_*');

// Les sprites que cette entrée montre : le sien, ceux posés dessus, et ceux que peint son motif.
export function spritesDe(entree) {
  const m = entree.motif ?? '';
  const duMotif = m.startsWith('jauge.') ? ['jauge.cadre'] : m.startsWith('cout') ? ['icone.cout'] : [];
  return [entree.sprite, ...(entree.avec ?? []).map((o) => o.sprite), ...duMotif].filter(Boolean);
}

export const lignes = (entree) => (Array.isArray(entree.libelle) ? entree.libelle : [entree.libelle]);

const COUT_EXEMPLE = 'x.xx';
const JAUGE_W = S['jauge.cadre'].w;
const JAUGE_H = S['jauge.cadre'].h;
const COUT_ICONE = S['icone.cout'];

// Taille d'un signe en pixels et position de ses éléments, relative à son coin haut-gauche.
// Un élément : { sprite, x, y } | { motif, x, y }.
export function composer(entree) {
  if (entree.sprite) {
    const s = S[entree.sprite];
    const elements = [{ sprite: entree.sprite, x: 0, y: 0 }];
    for (const o of entree.avec ?? []) {
      const b = S[o.sprite];
      elements.push({ sprite: o.sprite, x: s.pivot[0] + o.dx - b.pivot[0], y: s.pivot[1] + o.dy - b.pivot[1] });
    }
    const x0 = Math.min(...elements.map((e) => e.x));
    const y0 = Math.min(...elements.map((e) => e.y));
    const x1 = Math.max(...elements.map((e) => e.x + S[e.sprite].w));
    const y1 = Math.max(...elements.map((e) => e.y + S[e.sprite].h));
    return { w: x1 - x0, h: y1 - y0, elements: elements.map((e) => ({ ...e, x: e.x - x0, y: e.y - y0 })) };
  }
  const m = entree.motif;
  const taille = m.startsWith('bordure.') || m === 'halo.attente'
    ? [TUILE, TUILE]
    : m.startsWith('jauge.')
      ? [m === 'jauge.inconnue' ? JAUGE_W + 1 + POLICE.w : JAUGE_W, JAUGE_H]
      : m === 'cout'
        ? [COUT_ICONE.w + 1 + COUT_EXEMPLE.length * (POLICE.w + 1) - 1, COUT_ICONE.h]
        : m === 'cout.inconnu'
          ? [COUT_ICONE.w + 1 + POLICE.w, COUT_ICONE.h]
          : m === 'marque'
            ? [3, 3]
            : [7, 1]; // brouillon : trois points
  return { w: taille[0], h: taille[1], elements: [{ motif: m, x: 0, y: 0 }] };
}
export { COUT_EXEMPLE };

const largeurTexte = (chaine) => ([...chaine].length ? [...chaine].length * (POLICE.w + 1) - 1 : 0);

export const MISE_EN_PAGE = Object.freeze({
  PAD: 6, // marge de la bande
  ENTRE: 6, // espace entre deux signes
  TITRE_H: POLICE.h + 4, // hauteur de la ligne de titre d'un groupe
  LIGNE_H: POLICE.h + 1, // hauteur d'une ligne de libellé
  BANDE_MUR: 3, // mur sombre au-dessus de la légende
});

// Dispose la légende dans une bande de la largeur de l'étage, à partir de l'ordonnée oy. Déterministe.
// Retour : { y, h, titres: [{ texte, x, y, trait: {x, y, w} }], cellules: [{ entree, x, y, w, h, signe, libelle: [{texte, x, y}] }] }
export function disposerLegende(largeur, oy) {
  const { PAD, ENTRE, TITRE_H, LIGNE_H, BANDE_MUR } = MISE_EN_PAGE;
  const xMin = PAD;
  const xMax = largeur - PAD;
  const titres = [];
  const cellules = [];
  let y = oy + BANDE_MUR + PAD;

  for (const groupe of Object.keys(GROUPES)) {
    const entrees = LEGENDE.filter((e) => e.groupe === groupe);
    if (!entrees.length) continue;
    titres.push({ texte: GROUPES[groupe], x: xMin, y, trait: { x: xMin + largeurTexte(GROUPES[groupe]) + 4, y: y + 3, w: xMax - xMin - largeurTexte(GROUPES[groupe]) - 4 } });
    y += TITRE_H;

    // Remplit des rangées : un signe garde la place de son libellé, centré dessous.
    const rangees = [[]];
    let x = xMin;
    for (const entree of entrees) {
      const signe = composer(entree);
      const texte = lignes(entree);
      const w = Math.max(signe.w, ...texte.map(largeurTexte));
      if (x > xMin && x + w > xMax) {
        rangees.push([]);
        x = xMin;
      }
      rangees.at(-1).push({ entree, signe, texte, w, x });
      x += w + ENTRE;
    }
    for (const rangee of rangees) {
      const hSigne = Math.max(...rangee.map((c) => c.signe.h));
      const nLignes = Math.max(...rangee.map((c) => c.texte.length));
      for (const c of rangee) {
        const sx = c.x + Math.floor((c.w - c.signe.w) / 2);
        const sy = y + hSigne - c.signe.h; // signes alignés par le bas, libellés alignés par le haut
        cellules.push({
          entree: c.entree,
          x: c.x,
          y,
          w: c.w,
          h: hSigne + 2 + nLignes * LIGNE_H,
          signe: { ...c.signe, x: sx, y: sy },
          libelle: c.texte.map((t, i) => ({ texte: t, x: c.x + Math.floor((c.w - largeurTexte(t)) / 2), y: y + hSigne + 2 + i * LIGNE_H })),
        });
      }
      y += hSigne + 2 + nLignes * LIGNE_H + 4;
    }
  }
  return { y: oy, h: y - oy + PAD - 4, titres, cellules };
}
