// plan.js — disposition déterministe de la scène. Même instantané, même plan, aucune donnée aléatoire.
//
// GÉOMÉTRIE — dérivée des sprites (graphismes/atlas.js : ATLAS.sprites et MONTAGE), jamais de nombres magiques.
// Un POSTE est la boîte qui contient tout ce qu'un agent peut faire apparaître autour du pivot de son bureau
// (meuble.bureau) : bureau, chaise, tous les personnages (arrive : 24×32 compris), tous les écrans, toutes les
// bulles (au bout MONTAGE.bulle), le halo (MONTAGE.halo), l'éclair de refus, puis une BANDE sous le poste :
// la jauge de contexte (jauge.cadre, plus un « ? » à droite si inconnue) et la ligne de coût (icone.cout + montant
// le plus large prévu). Aujourd'hui : BOITE_POSTE = 41×57 px (voir GEOM.poste), 4 px de marge entre deux postes.
//
// Une PIÈCE d'équipe : un en-tête de la hauteur d'une tuile de mur (≥ hauteur de la police + 6) réservé au nom,
// sans aucun poste dessous ; un plancher où les postes sont rangés en colonnes (4 au plus) puis en rangées ;
// largeur = celle des postes (et du nom, de la sirène, de la porte), arrondie à la tuile. Aucun poste ne sort de sa
// pièce, aucune boîte de poste n'en recouvre une autre (tests/scene/js/lisibilite.test.mjs).
//
// L'ÉTAGE, en BANDES empilées de haut en bas. Une bande = deux rangées de pièces d'équipe face à face (au-dessus,
// leur porte est dans leur cloison basse ; au-dessous, dans leur cloison haute) autour d'un couloir horizontal de
// deux tuiles. Au plus 8 pièces par bande : 4 en haut, 4 en bas.
// La pièce de RANG r dans noms (équipes[], puis équipes vues seulement dans agents[]) va dans la bande ⌊r/8⌋ ; rangée
// du haut si r est pair, du bas sinon (8 est pair : r mod 8 a la parité de r). Une équipe qui grandit ne fait donc
// changer ni de bande ni de rangée aucune autre pièce ; seule sa rangée s'élargit, à droite.
// L'Assistant à gauche et l’utilisateur à droite occupent toute la hauteur : ce sont les deux CAGES qui relient les bandes.
// Chaque couloir débouche sur l'une et sur l'autre (ouverture dans la cloison de la cage). La porte de l’utilisateur est au
// bout du couloir de la bande 0. Le poste de l'Assistant est centré sur la bande 0.
// Le facteur passe d'un couloir à l'autre par la cage de l'Assistant (bord gauche) : couloir → cage → couloir.
// Aucune arête ne traverse un mur (tests/scene/js/bandes.test.mjs).
// Une rangée du bas vide (dernière bande, pas assez de pièces) n'a pas de hauteur : le couloir se ferme sur la bande
// suivante, et rien ne reste au fond. La rangée la plus courte, toutes bandes confondues, est élargie (par tuiles) pour
// que l'étage soit un rectangle plein : jamais de vide noir. Mais une pièce ne s'étire pas au-delà de PIECE_W_MAX (la
// largeur d'une pièce de COLONNES_MAX postes) quand sa rangée a moins de pièces que la plus pleine de l'étage : le reste
// de la rangée est un EMPLACEMENT LIBRE (`videes` : sol de couloir, sans nom, sans porte, sans poste). Un reste de
// moins de 3 tuiles ne fait pas d'emplacement libre : dans ce cas la rangée s'élargit sans plafond.
//
// L'en-tête d'une pièce d'équipe, de droite à gauche : sirène, « ? » de cause inconnue (alerte.cause_inconnue, dessiné
// seulement si la pièce est rouge sans cause visible, voir rendu.js), compteur des arrêtés repliés (« [dossiers] +N »),
// porte (pièces du bas), nom. La LÉGENDE (legende.js) est une bande sous l'étage, de sa largeur : scene.hauteur =
// hauteurEtage + legende.h.
//
// LES ARRÊTÉS. Un agent de REPLIER arrêté (etat == "arrete") n'a ni poste, ni siège, ni bureau : il est compté dans le
// compteur d'en-tête de sa pièce. Une pièce sans poste restant garde la hauteur d'un poste et une largeur minimale
// (nom + compteur + sirène). Les agents « inconnu » ne sont jamais repliés.
// HORS ORGANIGRAMME. Un agent dont l'équipe n'est pas dans equipes[] (ni l'Assistant, ni l’utilisateur) ne crée aucune pièce :
// il est compté, avec etat.sessions_hors_organigramme, dans un compteur posé au bord gauche du couloir de la bande 0.

import { ATLAS, MONTAGE } from './graphismes/atlas.js';
import { disposerLegende } from './legende.js';

const S = ATLAS.sprites;
const POLICE = ATLAS.police;
const TUILE = ATLAS.tuile;
const ASSISTANT = 'assistant';
const UTILISATEUR = 'utilisateur';

// Rôles dont les agents arrêtés sont repliés en compteur. Les coordinateurs gardent leur poste (chaise vide : c'est la
// tête de l'équipe). Pour replier aussi les coordinateurs : ['worker', 'coordinateur'].
export const REPLIER = Object.freeze(['worker']);
const repliable = (a) => REPLIER.includes(a.role) && a.etat === 'arrete';

export function largeurTexte(police, chaine) {
  const n = [...chaine].length;
  return n === 0 ? 0 : n * (police.w + 1) - 1;
}

// Largeur d'un compteur « signe + texte » : le signe, 2 px, puis le texte (police bitmap).
const SIGNE = S['compteur.dossiers'];
export const largeurCompteur = (texte) => SIGNE.w + 2 + largeurTexte(POLICE, texte);
const libelleRepliés = (n) => `+${n}`;

// Abrège avec « … » (un glyphe) quand le nom ne tient pas dans wMax px.
export function abreger(police, chaine, wMax) {
  if (largeurTexte(police, chaine) <= wMax) return chaine;
  const lettres = [...chaine];
  while (lettres.length > 1 && largeurTexte(police, lettres.join('') + '…') > wMax) lettres.pop();
  return lettres.join('') + '…';
}

const COUT_LE_PLUS_LARGE = '99.99';
const ROLES = ['assistant', 'coordinateur', 'worker'];

// Boîte [x0, y0, x1, y1) d'un sprite posé par son pivot en (ox, oy), relative au pivot du bureau.
const boite = (nom, ox = 0, oy = 0) => {
  const s = S[nom];
  return [ox - s.pivot[0], oy - s.pivot[1], ox - s.pivot[0] + s.w, oy - s.pivot[1] + s.h];
};
const union = (boites) => [
  Math.min(...boites.map((b) => b[0])),
  Math.min(...boites.map((b) => b[1])),
  Math.max(...boites.map((b) => b[2])),
  Math.max(...boites.map((b) => b[3])),
];
const nomsPre = (prefixe) => Object.keys(S).filter((n) => n.startsWith(prefixe));

// Éclair de refus : à gauche de la bulle, à la même hauteur.
const REFUS = [MONTAGE.bulle[0] - S['bulle.question'].pivot[0] - S['alerte.refus_garde'].pivot[0], MONTAGE.bulle[1]];

const haloBoite = boite('alerte.halo', ...MONTAGE.halo);
const jaugeX = -Math.floor(S['jauge.cadre'].w / 2);
const jaugeY = haloBoite[3] + 1; // la bande commence sous le halo
const coutY = jaugeY + S['jauge.cadre'].h + 1;
const coutLargeur = S['icone.cout'].w + 1 + largeurTexte(POLICE, COUT_LE_PLUS_LARGE);
const coutX = -Math.floor(coutLargeur / 2);
const BANDE = Object.freeze({
  jauge: { x: jaugeX, y: jaugeY },
  cout: { x: coutX, y: coutY, largeur: coutLargeur },
  point: { x: jaugeX + S['jauge.cadre'].w + 1, y: jaugeY - 1 }, // « ? » d'une jauge inconnue
});

const boitePoste = union([
  boite('meuble.bureau'),
  boite('meuble.chaise', ...MONTAGE.perso),
  ...ROLES.flatMap((r) => nomsPre(`perso.${r}.`).map((n) => boite(n, ...MONTAGE.perso))),
  ...nomsPre('ecran.').map((n) => boite(n, ...MONTAGE.ecran)),
  ...nomsPre('bulle.').map((n) => boite(n, ...MONTAGE.bulle)),
  haloBoite,
  boite('alerte.refus_garde', ...REFUS),
  [BANDE.jauge.x, jaugeY, BANDE.point.x + POLICE.w, jaugeY + S['jauge.cadre'].h],
  [coutX, coutY, coutX + coutLargeur, coutY + S['icone.cout'].h],
]);

const PAS = 4; // marge entre deux postes
const PAD = 8; // marge entre le plancher d'une pièce et ses postes
const MUR = 3; // demi-épaisseur d'une cloison (6 px, à cheval sur la limite entre deux pièces)
const COLONNES_MAX = 4;
const POSTE_W = boitePoste[2] - boitePoste[0];

export const GEOM = Object.freeze({
  poste: Object.freeze({ x: boitePoste[0], y: boitePoste[1], w: POSTE_W, h: boitePoste[3] - boitePoste[1] }),
  BANDE,
  REFUS,
  PAS,
  PAD,
  MUR,
  COLONNES_MAX,
  PIECES_PAR_BANDE: 8, // 4 pièces au-dessus du couloir, 4 au-dessous
  PIECE_W_MAX: Math.ceil((2 * (MUR + PAD) + COLONNES_MAX * POSTE_W + (COLONNES_MAX - 1) * PAS) / TUILE) * TUILE, // une pièce de COLONNES_MAX postes : 208 px
  COULOIR_H: 2 * TUILE,
  ENTETE_H: Math.max(TUILE, POLICE.h + 6), // une tuile de mur : le nom est écrit sur le mur, sans poste dessous
  SIGNE_W: SIGNE.w, // le signe du compteur (arrêtés repliés, hors organigramme)
  SIGNE_H: SIGNE.h,
  SIRENE_W: S['alerte.sirene'].w,
  CAUSE_W: S['alerte.cause_inconnue'].w, // le « ? » rouge, à gauche de la sirène (1 px d'écart)
  CAUSE_H: S['alerte.cause_inconnue'].h,
  PORTE_W: S['porte.piece'].w,
  NOM_MAX: 12, // lettres que la pièce garde la place d'écrire en entier
  ASSISTANT_W: 6 * TUILE,
  UTILISATEUR_W: 3 * TUILE,
});

let memo = { cle: null, plan: null };

// Même instantané d'organigramme = même plan : on ne recalcule qu'au changement de structure.
export function disposition(etat) {
  const cle = JSON.stringify([
    (etat.equipes ?? []).map((e) => e.nom),
    (etat.agents ?? []).map((a) => [a.id, a.role, a.equipe ?? null, repliable(a) ? 1 : 0]),
    etat.sessions_hors_organigramme ?? null,
  ]);
  if (memo.cle !== cle) memo = { cle, plan: calculer(etat) };
  return memo.plan;
}

const auPlusHaut = (x) => Math.ceil(x / TUILE) * TUILE;

function calculer(etat) {
  const { PAS, PAD, MUR, COLONNES_MAX, COULOIR_H, ENTETE_H, SIRENE_W, CAUSE_W, CAUSE_H, PORTE_W, NOM_MAX, ASSISTANT_W, UTILISATEUR_W, PIECES_PAR_BANDE } = GEOM;
  const { x: bx, y: by, w: BW, h: BH } = GEOM.poste;

  // Les pièces sont celles de equipes[] : un agent d'une équipe absente de equipes[] n'en crée pas (hors organigramme).
  const noms = [];
  for (const e of etat.equipes ?? []) if (!noms.includes(e.nom)) noms.push(e.nom);
  const deAssistant = [];
  const parEquipe = new Map();
  const repliesDe = new Map(); // équipe → nombre d'agents arrêtés repliés (compteur d'en-tête)
  let nHorsOrganigramme = 0;
  for (const a of etat.agents ?? []) {
    if (a.role === UTILISATEUR) continue;
    if (a.role === 'assistant' || !a.equipe) {
      deAssistant.push(a);
      continue;
    }
    if (!noms.includes(a.equipe)) {
      nHorsOrganigramme++;
      continue;
    }
    if (repliable(a)) {
      repliesDe.set(a.equipe, (repliesDe.get(a.equipe) ?? 0) + 1);
      continue;
    }
    if (!parEquipe.has(a.equipe)) parEquipe.set(a.equipe, []);
    parEquipe.get(a.equipe).push(a);
  }
  const trier = (liste) =>
    [...liste].sort((x, y) => (x.role === 'coordinateur' ? 0 : 1) - (y.role === 'coordinateur' ? 0 : 1) || x.id.localeCompare(y.id));

  // Dimensions voulues de chaque pièce d'équipe.
  const salles = noms.map((nom) => {
    const agents = trier(parEquipe.get(nom) ?? []);
    const repliés = repliesDe.get(nom) ?? 0;
    const colonnes = Math.max(1, Math.min(COLONNES_MAX, agents.length));
    // Plus aucun poste visible mais des arrêtés repliés : la pièce garde la hauteur d'un poste.
    const rangees = agents.length ? Math.ceil(agents.length / colonnes) : repliés ? 1 : 0;
    const blocW = agents.length ? colonnes * BW + (colonnes - 1) * PAS : 0;
    const nomW = largeurTexte(POLICE, [...nom].slice(0, NOM_MAX).join(''));
    const cW = repliés ? largeurCompteur(libelleRepliés(repliés)) + 2 : 0; // 2 px d'écart avant le compteur
    const entete = (porte) => 2 * MUR + 4 + nomW + 2 + CAUSE_W + 1 + SIRENE_W + 2 + (porte ? 2 + PORTE_W : 0) + cW;
    const base = 2 * (MUR + PAD) + blocW;
    return {
      nom,
      agents,
      repliés,
      colonnes,
      rangees,
      blocW,
      wHaut: auPlusHaut(Math.max(base, entete(false))),
      wBas: auPlusHaut(Math.max(base, entete(true))),
    };
  });

  // Bandes : la pièce de rang r va dans la bande ⌊r/8⌋, rangée du haut si r est pair, du bas sinon.
  // Ne dépend jamais des largeurs ni des effectifs : un agent embauché ne fait changer de bande ni de rangée aucune pièce.
  const bandes = [];
  salles.forEach((s, rang) => {
    const k = Math.floor(rang / PIECES_PAR_BANDE);
    if (!bandes[k]) bandes[k] = { haut: [], bas: [] };
    (rang % 2 === 0 ? bandes[k].haut : bandes[k].bas).push(s);
  });
  if (!bandes.length) bandes.push({ haut: [], bas: [] }); // aucune équipe : l'étage garde son couloir

  for (const b of bandes) {
    b.haut.forEach((s) => (s.w = s.wHaut));
    b.bas.forEach((s) => (s.w = s.wBas));
  }
  // La rangée la plus courte est élargie, tuile par tuile, en commençant par ses pièces les plus étroites, sans qu'une
  // pièce dépasse `plafond`. Le reste de la rangée n'est pas étiré : il devient un emplacement libre (rangeeDe).
  // Renvoie le reste non comblé (ce qui reste à remplir par un emplacement libre).
  const elargir = (rangee, cible, plafond) => {
    if (!rangee.length) return 0;
    let reste = cible - rangee.reduce((t, s) => t + s.w, 0);
    while (reste >= TUILE) {
      const eligibles = rangee.filter((s) => s.w < plafond);
      if (!eligibles.length) break;
      const etroite = eligibles.reduce((m, s) => (s.w < m.w ? s : m), eligibles[0]);
      etroite.w += TUILE;
      reste -= TUILE;
    }
    return reste;
  };
  const rangeesDe = bandes.flatMap((b) => [b.haut, b.bas]);
  const cibleW = Math.max(4 * TUILE, ...rangeesDe.map((r) => r.reduce((t, s) => t + s.w, 0)));
  // Une rangée qui a moins de pièces que la plus pleine de l'étage ne peut pas étirer une pièce au-delà d'une pièce.
  // Si le reste libre est inférieur à 3 tuiles (48 px), pas d'emplacement libre : la rangée s'élargit sans plafond.
  const pleine = Math.max(...rangeesDe.map((r) => r.length));
  for (const r of rangeesDe) {
    const courte = r.length < pleine;
    const largeurs = r.map((s) => s.w);
    const reste = elargir(r, cibleW, courte ? GEOM.PIECE_W_MAX : Infinity);
    if (courte && reste < 3 * TUILE) {
      r.forEach((s, i) => (s.w = largeurs[i]));
      elargir(r, cibleW, Infinity);
    }
  }
  const largeurMilieu = cibleW;

  // Hauteurs des bandes, empilées : la bande k commence où finit la bande k-1.
  const hauteurRangee = (rangee, mur) =>
    auPlusHaut(ENTETE_H + PAD + Math.max(...rangee.map((s) => s.rangees * BH + Math.max(0, s.rangees - 1) * PAS)) + PAD + mur);
  let yBande = 0;
  for (const b of bandes) {
    b.hHaut = b.haut.length ? hauteurRangee(b.haut, TUILE) : TUILE; // sous les postes : la cloison basse, côté couloir
    b.hBas = b.bas.length ? hauteurRangee(b.bas, MUR) : 0; // rangée du bas vide : rien (pas de pixel de fond)
    b.y = yBande;
    b.yCouloir = yBande + b.hHaut;
    b.hauteur = b.hHaut + COULOIR_H + b.hBas;
    yBande += b.hauteur;
  }
  const hauteur = yBande;
  const largeur = ASSISTANT_W + largeurMilieu + UTILISATEUR_W;
  const xUtilisateur = largeur - UTILISATEUR_W;
  const b0 = bandes[0];
  const yMarche = (b) => b.yCouloir + COULOIR_H - 10; // pieds du facteur dans le couloir
  const cageNom = (k) => (k === 0 ? ASSISTANT : `cage:${k}`);
  const CAGE_X = ASSISTANT_W - 12; // dans la pièce de l'Assistant : là où le facteur monte d'une bande à l'autre

  const sieges = new Map();
  const noeuds = new Map();
  const pieces = [];
  const videes = []; // emplacements libres : le reste d'une rangée trop courte (sol de couloir, rien d'autre)
  const murs = new Map();
  const mur = (x, y) => murs.set(`${x},${y}`, { sprite: 'mur.haut', x, y });
  const bandeMur = (x0, x1, y) => {
    for (let x = x0; x < x1; x += TUILE) mur(x, y);
  };
  const cloisons = [{ x: 0, y: 0, h: hauteur, type: 'gauche' }, { x: largeur - MUR, y: 0, h: hauteur, type: 'droite' }];
  const decors = [];
  const couloirs = bandes.map((b) => ({ x: ASSISTANT_W, y: b.yCouloir, w: largeurMilieu, h: COULOIR_H }));

  // Cloison d'une cage (Assistant à gauche, l’utilisateur à droite) : pleine, sauf l'ouverture de chaque couloir.
  const cloisonCage = (x) => {
    for (const b of bandes) {
      if (b.hHaut) cloisons.push({ x, y: b.y, h: b.hHaut, type: 'milieu' });
      if (b.hBas) cloisons.push({ x, y: b.yCouloir + COULOIR_H, h: b.hBas, type: 'milieu' });
    }
  };

  // Pose les postes d'une liste d'agents dans une pièce ; le bloc est centré dans la place libre.
  const placer = (s, piece, bas_) => {
    const bas2 = bas_ ? MUR : TUILE;
    const libreW = piece.w - 2 * (MUR + PAD);
    const libreH = piece.h - ENTETE_H - 2 * PAD - bas2;
    const blocH = s.rangees * BH + Math.max(0, s.rangees - 1) * PAS;
    const x0 = piece.x + MUR + PAD + Math.floor((libreW - s.blocW) / 2);
    const y0 = piece.y + ENTETE_H + PAD + Math.max(0, Math.floor((libreH - blocH) / 2));
    s.agents.forEach((a, k) => {
      const r = Math.floor(k / s.colonnes);
      const c = k % s.colonnes;
      const caseX = x0 + c * (BW + PAS);
      const caseY = y0 + r * (BH + PAS);
      const px = caseX - bx; // pivot du bureau
      const py = caseY - by;
      const sb = S['meuble.bureau'];
      sieges.set(a.id, {
        piece: piece.nom,
        pivot: { x: px, y: py },
        siege: { x: px + MONTAGE.perso[0], y: py + MONTAGE.perso[1] }, // pivot du personnage
        bureau: { x: px - sb.pivot[0], y: py - sb.pivot[1], w: sb.w, h: sb.h },
        boite: { x: caseX, y: caseY, w: BW, h: BH },
      });
    });
    return { x0, libreW, y0, blocH };
  };

  const entetePiece = (p) => {
    const cW = p.repliés ? largeurCompteur(libelleRepliés(p.repliés)) : 0;
    const cause = { x: p.x + p.w - MUR - 2 - SIRENE_W - 1 - CAUSE_W, y: p.y + Math.floor((ENTETE_H - CAUSE_H) / 2) };
    return {
      entete: { x: p.x, y: p.y, w: p.w, h: ENTETE_H },
      // la salle de l’utilisateur n'a ni sirène ni porte dans son en-tête : tout le mur est pour son nom
      nomZone:
        p.nom === UTILISATEUR
          ? { x: p.x + MUR + 3, y: p.y + 5, w: p.w - 2 * MUR - 6 }
          : p.haut === null
            ? { x: p.x + MUR + 4, y: p.y + 5, w: p.w - 2 * MUR - 8 - SIRENE_W - 4 }
            : {
                x: p.x + MUR + 4,
                y: p.y + 5,
                w: p.w - 2 * MUR - 4 - 2 - CAUSE_W - 1 - SIRENE_W - 2 - (p.haut === false ? PORTE_W + 2 : 0) - (cW ? cW + 2 : 0),
              },
      sireneAncre: { x: p.x + p.w - MUR - 2 - SIRENE_W / 2, y: p.y + ENTETE_H - 1 },
      // le « ? » de cause inconnue : coin haut-gauche, juste à gauche de la sirène (les pièces d'équipe seulement)
      causeAncre: cause,
      // le compteur des arrêtés repliés : juste à gauche du « ? » (2 px d'écart), jamais sur le nom
      compteur: cW
        ? { n: p.repliés, texte: libelleRepliés(p.repliés), x: cause.x - 2 - cW, y: p.y + Math.floor((ENTETE_H - SIGNE.h) / 2), w: cW }
        : null,
    };
  };

  // Pièce de l'Assistant : sur toute la hauteur, à gauche des couloirs.
  const pAss = { nom: ASSISTANT, x: 0, y: 0, w: ASSISTANT_W, h: hauteur, haut: null, neutre: true };
  Object.assign(pAss, entetePiece(pAss), { plancher: { x: 0, y: ENTETE_H, w: ASSISTANT_W, h: hauteur - ENTETE_H } });
  const sAss = { agents: trier(deAssistant), colonnes: 1, rangees: Math.max(1, deAssistant.length), blocW: BW };
  placer(sAss, { ...pAss, h: b0.hauteur }, false);
  const piedHaut = ENTETE_H + PAD + 24; // décor du haut : au-dessus du poste, qui est centré sur le couloir de la bande 0
  decors.push({ sprite: 'machine.cafe', x: ASSISTANT_W - MUR - PAD - 8, y: piedHaut });
  decors.push({ sprite: 'plante', x: MUR + PAD + 9, y: piedHaut });
  decors.push({ sprite: 'plante', x: MUR + PAD + 9, y: hauteur - MUR - PAD - 2 });
  decors.push({ sprite: 'plante', x: ASSISTANT_W - MUR - PAD - 9, y: hauteur - MUR - PAD - 2 });
  pieces.push({ ...pAss, porte: null });
  cloisonCage(ASSISTANT_W - MUR);

  const rangeeDe = (rangee, estHaut, b, k) => {
    const y = estHaut ? b.y : b.yCouloir + COULOIR_H;
    const h = estHaut ? b.hHaut : b.hBas;
    let x = ASSISTANT_W;
    for (const s of rangee) {
      const p = { nom: s.nom, x, y, w: s.w, h, haut: estHaut, bande: k, repliés: s.repliés };
      Object.assign(p, entetePiece(p), {
        plancher: { x, y: y + ENTETE_H, w: s.w, h: h - ENTETE_H },
        // plancher visible (sans la cloison basse des pièces du haut)
        sol: { x: x + MUR, y: y + ENTETE_H, w: s.w - 2 * MUR, h: h - ENTETE_H - (estHaut ? TUILE : MUR) },
      });
      const bloc = placer(s, p, !estHaut);
      const gauche = bloc.x0 - (x + MUR + PAD);
      const droite = x + s.w - MUR - PAD - (bloc.x0 + s.blocW);
      const piedY = y + h - (estHaut ? TUILE : 0) - PAD + 2;
      if (!s.agents.length) {
        decors.push({ sprite: 'plante', x: x + MUR + PAD + 9, y: piedY });
        decors.push({ sprite: 'machine.cafe', x: x + s.w - MUR - PAD - 8, y: piedY });
      } else {
        if (gauche >= 20) decors.push({ sprite: 'plante', x: x + MUR + PAD + 9, y: piedY });
        if (droite >= 20) decors.push({ sprite: 'plante', x: x + s.w - MUR - PAD - 9, y: piedY });
      }
      // porte des pièces du bas : à gauche du compteur s'il y en a un, sinon à gauche du « ? »
      const porteGauche = estHaut ? x + Math.floor(s.w / 2) - PORTE_W / 2 : (p.compteur ?? p.causeAncre).x - 2 - PORTE_W;
      const porteY = estHaut ? y + h - TUILE : y;
      p.porteSprite = { x: porteGauche, y: porteY };
      p.porte = { x: porteGauche + PORTE_W / 2, y: yMarche(b) };
      noeuds.set(`piece:${s.nom}`, p.porte);
      bandeNoeuds[k].push(`piece:${s.nom}`);
      pieces.push(p);
      x += s.w;
      if (x < ASSISTANT_W + largeurMilieu) {
        cloisons.push({ x: x - MUR, y, h, type: 'milieu' });
      }
    }
    // Le reste d'une rangée non vide : un emplacement libre, sans nom ni porte ni poste. Ses murs sont ceux de la rangée
    // (façade ou cloison de bande, posés sur toute la largeur de l'étage).
    if (rangee.length && x < ASSISTANT_W + largeurMilieu) {
      videes.push({ x, y, w: ASSISTANT_W + largeurMilieu - x, h, bande: k, haut: estHaut });
    }
  };

  // Chaque noeud du facteur par bande : les portes de ses pièces, puis (bande 0) la porte de l’utilisateur.
  const bandeNoeuds = bandes.map(() => []);
  bandes.forEach((b, k) => {
    if (k === 0) bandeMur(0, largeur, 0); // façade du haut : l'en-tête des pièces du haut de la bande 0
    else bandeMur(ASSISTANT_W, ASSISTANT_W + largeurMilieu, b.y); // en-tête des pièces du haut : mur entre deux bandes
    rangeeDe(b.haut, true, b, k);
    rangeeDe(b.bas, false, b, k);
    bandeMur(ASSISTANT_W, ASSISTANT_W + largeurMilieu, b.yCouloir - TUILE); // cloisons basses des pièces du haut
    if (b.bas.length) bandeMur(ASSISTANT_W, ASSISTANT_W + largeurMilieu, b.yCouloir + COULOIR_H); // en-tête des pièces du bas
  });

  // Pièce de l’utilisateur : courte, derrière sa porte, sur toute la hauteur pour que l'étage reste un rectangle plein.
  const pArt = { nom: UTILISATEUR, x: xUtilisateur, y: 0, w: UTILISATEUR_W, h: hauteur, haut: null, neutre: true };
  Object.assign(pArt, entetePiece(pArt), { plancher: { x: xUtilisateur, y: ENTETE_H, w: UTILISATEUR_W, h: hauteur - ENTETE_H } });
  pieces.push({ ...pArt, porte: null });
  cloisonCage(xUtilisateur - MUR);
  decors.push({ sprite: 'plante', x: xUtilisateur + MUR + PAD + 9, y: ENTETE_H + PAD + 20 });
  decors.push({ sprite: 'plante', x: largeur - MUR - PAD - 9, y: hauteur - MUR - PAD - 2 });
  const porteUtilisateur = { x: xUtilisateur, y: yMarche(b0), w: UTILISATEUR_W, h: hauteur, porte: { x: xUtilisateur, y: yMarche(b0) } };
  const posteUtilisateur = { x: xUtilisateur + 28, y: yMarche(b0) };

  // Hors organigramme : un compteur au bord gauche du couloir de la bande 0, près de la cage de l'Assistant. Le facteur
  // marche aux pieds (yMarche), en bas du couloir : le compteur reste dans le haut. N = agents hors organigramme
  // + sessions hors organigramme. Sessions inconnues (null) : « N+? », jamais un zéro. Rien à compter : pas de compteur.
  const sessions = etat.sessions_hors_organigramme;
  const sessionsInconnues = !Array.isArray(sessions);
  const nSessions = sessionsInconnues ? 0 : sessions.length;
  let horsCompteur = null;
  if (nHorsOrganigramme || sessionsInconnues || nSessions) {
    const nombre = nHorsOrganigramme + nSessions;
    const texte = `hors organigramme : ${sessionsInconnues ? `${nombre}+?` : nombre}`;
    horsCompteur = {
      n: nombre,
      texte,
      inconnu: sessionsInconnues,
      x: ASSISTANT_W + 4,
      y: b0.yCouloir + 3,
      w: largeurCompteur(texte),
    };
  }

  // Graphe du facteur : dans chaque couloir, les noeuds dans l'ordre des abscisses, la cage à gauche ; deux bandes
  // voisines se rejoignent par leurs cages (l'Assistant, puis « cage:k »). l’utilisateur, au bout du couloir de la bande 0.
  noeuds.set(UTILISATEUR, { x: xUtilisateur - 14, y: yMarche(b0) });
  bandeNoeuds[0].push(UTILISATEUR);
  bandes.forEach((b, k) => noeuds.set(cageNom(k), { x: CAGE_X, y: yMarche(b) }));
  const aretes = [];
  const voisins = new Map([...noeuds.keys()].map((n) => [n, []]));
  const relier = (p, q) => {
    aretes.push([p, q]);
    voisins.get(p).push(q);
    voisins.get(q).push(p);
  };
  bandes.forEach((b, k) => {
    const ligne = [cageNom(k), ...bandeNoeuds[k]].sort((p, q) => noeuds.get(p).x - noeuds.get(q).x || p.localeCompare(q));
    ligne.slice(1).forEach((n, i) => relier(ligne[i], n));
    if (k > 0) relier(cageNom(k - 1), cageNom(k));
  });

  // Plus court chemin dans l'arbre des noeuds (unique : le graphe n'a pas de cycle). Vide si un noeud est inconnu.
  function cheminFacteur(de, a) {
    if (!voisins.has(de) || !voisins.has(a)) return [];
    const parent = new Map([[de, null]]);
    const file = [de];
    for (let i = 0; i < file.length && !parent.has(a); i++) {
      for (const v of voisins.get(file[i])) {
        if (!parent.has(v)) {
          parent.set(v, file[i]);
          file.push(v);
        }
      }
    }
    if (!parent.has(a)) return [];
    const chemin = [];
    for (let n = a; n !== null; n = parent.get(n)) chemin.unshift(n);
    return chemin;
  }

  // Un agent sans place connue part de la porte de l'Assistant (jamais de point inventé).
  function noeudDeAgent(id) {
    if (id === UTILISATEUR) return UTILISATEUR;
    const s = sieges.get(id);
    if (!s) return ASSISTANT;
    return s.piece === ASSISTANT ? ASSISTANT : `piece:${s.piece}`;
  }

  // Les enveloppes naissent et attendent sur le bureau : devant l'écran, à gauche du centre.
  function pointBureau(id) {
    if (id === UTILISATEUR) return noeuds.get(UTILISATEUR);
    const s = sieges.get(id);
    return s ? { x: s.pivot.x - 8, y: s.pivot.y - 6 } : noeuds.get(ASSISTANT);
  }

  // La légende : une bande sous l'étage, de sa largeur. Elle compte dans la taille de la scène.
  const legende = disposerLegende(largeur, hauteur);

  return {
    largeur,
    hauteur: hauteur + legende.h,
    hauteurEtage: hauteur,
    legende,
    couloirs,
    pieces,
    videes,
    etage: { murs: [...murs.values()], cloisons, decors },
    porteUtilisateur,
    posteUtilisateur,
    horsOrganigramme: horsCompteur,
    sieges,
    noeuds,
    aretes,
    cheminFacteur,
    points: (chemin) => chemin.map((n) => noeuds.get(n)),
    noeudDeAgent,
    pointBureau,
  };
}
