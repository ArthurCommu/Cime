// Meubles, écrans, sols, murs, portes et décor.
// Lumière haut-gauche : arêtes claires en haut/gauche, ombre portée en bas/droite.

import { toile, coller, contour, figer, px, rect, sprite } from "./dessin.js";

// Ombre portée : peint seulement là où rien n'est encore peint.
function ombre(t, x, y, w, h, c = "F") {
  for (let j = y; j < y + h; j++) for (let i = x; i < x + w; i++) if (t[j]?.[i] === ".") t[j][i] = c;
}

// ─── Bureau (32×22, pivot au centre du bord bas) ───────────────────────────

function bureau(garni) {
  const t = toile(32, 22);
  rect(t, 1, 1, 30, 12, "d"); // plateau
  rect(t, 1, 1, 30, 1, "B"); // arête du fond
  rect(t, 1, 12, 30, 1, "l"); // arête avant éclairée
  rect(t, 1, 13, 30, 4, "B"); // façade
  rect(t, 1, 16, 30, 1, "b");
  rect(t, 3, 14, 26, 1, "b"); // ligne du tiroir
  rect(t, 1, 17, 2, 2, "b"); // pieds
  rect(t, 29, 17, 2, 2, "b");
  if (garni) {
    // clavier
    rect(t, 10, 9, 12, 3, "H");
    rect(t, 10, 11, 12, 1, "h");
    for (let x = 11; x < 21; x += 2) px(t, x, 10, "h");
    // feuilles
    rect(t, 2, 4, 5, 6, "H");
    rect(t, 3, 3, 5, 6, "w");
    for (const y of [4, 6]) rect(t, 4, y, 3, 1, "h");
    // tasse
    rect(t, 25, 3, 3, 3, "w");
    rect(t, 27, 3, 1, 3, "H");
    px(t, 28, 4, "w");
    rect(t, 25, 3, 2, 1, "b");
  }
  contour(t);
  ombre(t, 3, 19, 29, 2);
  ombre(t, 31, 3, 1, 16);
  return figer(t);
}

// ─── Chaise seule (même dessin et même calage que dans perso.*) ────────────

function chaiseSeule() {
  const t = toile(16, 24);
  coller(t, [".GGGGGGGG.", "GggggggggK", "GggggggggK", "GggggggggK", ".KKKKKKKK."], 3, 15);
  rect(t, 7, 20, 2, 1, "K");
  rect(t, 4, 21, 8, 1, "g");
  for (const x of [3, 4, 11, 12]) px(t, x, 22, "K");
  return figer(contour(t));
}

// ─── Écrans (18×14, pivot au pied) ──────────────────────────────────────────
// Dalle utile : 14×7 en (2, 2).

function moniteur(dalle) {
  const t = toile(18, 14);
  rect(t, 1, 1, 16, 9, "g");
  rect(t, 1, 1, 16, 1, "G");
  rect(t, 1, 1, 1, 9, "G");
  rect(t, 7, 10, 4, 2, "g");
  rect(t, 7, 10, 1, 2, "G");
  rect(t, 5, 12, 8, 1, "g");
  coller(t, dalle, 2, 2);
  return figer(contour(t));
}

function dalle(fond) {
  return Array.from({ length: 7 }, () => fond.repeat(14));
}

function ecrans() {
  const s = {};
  const eteint = dalle("K").map((l, y) => [...l].map((c, x) => (x + y === 6 || x + y === 7 ? "g" : c)).join(""));
  s["ecran.eteint"] = sprite([moniteur(eteint)]);

  // texte : éditeur sombre, une ligne qui s'écrit, curseur clair
  const texte = (n) => {
    const t = coller(toile(14, 7), dalle("z"));
    rect(t, 1, 1, 7, 1, "q");
    rect(t, 9, 1, 3, 1, "h");
    rect(t, 2, 3, 9, 1, "h");
    rect(t, 1, 5, n, 1, "q");
    px(t, 1 + n, 5, "w");
    return figer(t);
  };
  s["ecran.texte"] = sprite([1, 3, 5, 8].map((n) => moniteur(texte(n))), { fps: 4 });

  // lecture : page claire, une bande de surlignage qui descend, ascenseur
  const lecture = (f) => {
    const t = coller(toile(14, 7), dalle("w"));
    for (let y = 0; y < 7; y++) if (y % 2 === 0) rect(t, 1, y, y === 4 ? 8 : 11, 1, "h");
    rect(t, 0, f * 2, 13, 1, "q");
    rect(t, 1, f * 2, f === 2 ? 8 : 11, 1, "G");
    rect(t, 13, 0, 1, 7, "H");
    rect(t, 13, f + 1, 1, 2, "h");
    return figer(t);
  };
  s["ecran.lecture"] = sprite([0, 1, 2, 3].map((f) => moniteur(lecture(f))), { fps: 2 });

  // terminal : fond noir, lignes vertes qui défilent vers le haut
  const LIGNES = [9, 5, 11, 3, 7, 10, 4];
  const terminal = (f) => {
    const t = coller(toile(14, 7), dalle("k"));
    for (let r = 0; r < 3; r++) {
      const n = LIGNES[(r + f) % LIGNES.length];
      px(t, 1, r * 2, "E");
      rect(t, 3, r * 2, n, 1, "e");
    }
    px(t, 1, 6, "e");
    if (f % 2 === 0) px(t, 3, 6, "w");
    return figer(t);
  };
  s["ecran.terminal"] = sprite([0, 1, 2, 3].map((f) => moniteur(terminal(f))), { fps: 4 });

  // pensée : écran calme, une ronde de points qui tourne
  const ronde = [[6, 1], [9, 2], [10, 4], [7, 5], [4, 4], [3, 2]];
  const pensee = (f) => {
    const t = coller(toile(14, 7), dalle("z"));
    ronde.forEach(([x, y], i) => {
      const d = (i - f + ronde.length) % ronde.length;
      t[y][x] = d === 0 ? "w" : d === 1 ? "q" : "G";
    });
    return figer(t);
  };
  s["ecran.pensee"] = sprite([0, 1, 2, 3, 4, 5].map((f) => moniteur(pensee(f))), { fps: 6 });
  return s;
}

// ─── Sols et murs (tuiles 16×16) ────────────────────────────────────────────

function solPiece() {
  const t = toile(16, 16, "f");
  for (const [x, y] of [[2, 2], [10, 3], [6, 7], [14, 9], [3, 12], [11, 13], [7, 15]]) px(t, x, y, "F");
  return figer(t);
}

function solCouloir() {
  const t = toile(16, 16, "H");
  rect(t, 0, 0, 16, 1, "h");
  rect(t, 0, 8, 16, 1, "h");
  rect(t, 0, 0, 1, 16, "h");
  rect(t, 8, 0, 1, 16, "h");
  for (const [x, y] of [[1, 1], [9, 9]]) {
    rect(t, x, y, 3, 1, "w");
    px(t, x, y + 1, "w");
  }
  return figer(t);
}

// Crête du mur (vue d'en haut), sur 4 lignes.
function crete(t, x, w) {
  rect(t, x, 0, w, 1, "G");
  rect(t, x, 1, w, 2, "g");
  rect(t, x, 3, w, 1, "K");
}

// Façade du mur, lignes 4 à 15.
function facade(t, x, w) {
  rect(t, x, 4, w, 10, "H");
  rect(t, x, 4, w, 1, "h");
  rect(t, x, 10, w, 1, "h");
  rect(t, x, 14, w, 1, "B");
  rect(t, x, 15, w, 1, "b");
}

function murHaut() {
  const t = toile(16, 16);
  crete(t, 0, 16);
  facade(t, 0, 16);
  return figer(t);
}

// Mur vu en coupe (côtés gauche et droit d'une pièce) : une crête verticale
// centrée (colonnes 5 à 10), le reste transparent.
function murCote() {
  const t = toile(16, 16);
  rect(t, 5, 0, 1, 16, "G");
  rect(t, 6, 0, 4, 16, "g");
  rect(t, 10, 0, 1, 16, "K");
  return figer(t);
}

// Angle haut-gauche : la crête verticale (colonnes 5-10) rejoint la crête
// horizontale (lignes 0-3) ; la façade apparaît à droite.
function murAngle() {
  const t = toile(16, 16);
  crete(t, 5, 11);
  facade(t, 11, 5);
  rect(t, 5, 0, 1, 16, "G");
  rect(t, 6, 1, 4, 15, "g");
  rect(t, 10, 3, 1, 13, "K");
  return figer(t);
}

function portePiece() {
  const t = toile(16, 16);
  crete(t, 0, 16);
  facade(t, 0, 16);
  rect(t, 3, 4, 10, 12, "b");
  rect(t, 4, 5, 8, 11, "B");
  rect(t, 4, 5, 1, 11, "d");
  rect(t, 5, 7, 6, 3, "d");
  rect(t, 6, 8, 4, 1, "B");
  px(t, 10, 11, "y");
  return figer(t);
}

// Porte de l’utilisateur : 16×24, pivot au seuil (8, 15). Lignes 16-23 : le sol devant.
function porteUtilisateur(etat, f = 0) {
  const t = toile(16, 24);
  crete(t, 0, 16);
  facade(t, 0, 16);
  rect(t, 2, 4, 12, 12, "K");
  rect(t, 3, 5, 10, 10, "b");
  rect(t, 3, 5, 1, 10, "B");
  rect(t, 5, 7, 6, 2, "B"); // plaque
  rect(t, 6, 7, 4, 1, etat === "agir" ? "w" : "d");
  rect(t, 5, 10, 6, 4, "B");
  rect(t, 6, 11, 4, 2, "b");
  px(t, 11, 11, etat === "agir" ? "w" : "y");
  // lumière sous la porte
  const lumiere = { fermee: "K", attente: "l", agir: "y" }[etat];
  rect(t, 3, 15, 10, 1, lumiere);
  if (etat !== "fermee") {
    const halo = etat === "agir" ? (f === 0 ? "y" : "Y") : "l";
    for (let x = 4; x < 12; x += 2) px(t, x + (f % 2), 16, halo);
    // la pile de papiers qui attend devant la porte
    const p = toile(16, 24);
    rect(p, 5, 18, 7, 2, "H");
    rect(p, 4, 19, 7, 2, "w");
    rect(p, 6, 17, 6, 2, "w");
    rect(p, 6, 18, 5, 1, "h");
    rect(p, 5, 20, 5, 1, "h");
    if (etat === "agir") {
      rect(p, 10, 16, 2, 2, "y");
      px(p, 11, 15, "y");
    }
    contour(p);
    for (let y = 16; y < 24; y++) for (let x = 0; x < 16; x++) if (p[y][x] !== ".") t[y][x] = p[y][x];
    if (etat === "agir") for (let y = 15; y < 16; y++) for (let x = 0; x < 16; x++) if (p[y][x] === "y") t[y][x] = "y";
  }
  return figer(t);
}

// ─── Décor ──────────────────────────────────────────────────────────────────

const PLANTE = [
  "........E.......",
  ".......eE.......",
  "...E...eE...e...",
  "..eeE..eE..eeE..",
  "..eeEE.eE.eeE...",
  "...eeEeeEeeE....",
  ".EE..eeeeeE.....",
  "eeeEE.eeeE..EE..",
  ".eeeeEeeeEeeeeE.",
  "...eeeeeeeeeE...",
  "......eeeE......",
  "....dddddddd....",
  "....BBBBBBBb....",
  ".....BBBBBb.....",
  ".....BBBBBb.....",
  "......bbbb......",
];

function plante() {
  const t = toile(18, 20);
  coller(t, PLANTE, 1, 1);
  contour(t);
  ombre(t, 9, 18, 7, 1);
  return figer(t);
}

function panneau() {
  const t = toile(78, 13);
  rect(t, 1, 1, 76, 11, "B");
  rect(t, 2, 11, 75, 1, "b");
  rect(t, 76, 2, 1, 10, "b");
  rect(t, 2, 2, 74, 9, "w");
  px(t, 1, 1, "d");
  contour(t);
  return figer(t);
}

function machineCafe(f) {
  const t = toile(16, 22);
  rect(t, 3, 5, 10, 15, "g");
  rect(t, 3, 5, 10, 1, "G");
  rect(t, 3, 5, 1, 15, "G");
  rect(t, 5, 7, 6, 3, "H");
  rect(t, 6, 8, 2, 1, "h");
  px(t, 9, 8, "e");
  rect(t, 5, 11, 6, 6, "K");
  rect(t, 7, 11, 2, 1, "g");
  rect(t, 7, 14, 2, 2, "w");
  rect(t, 5, 16, 6, 1, "h");
  rect(t, 3, 19, 10, 1, "K");
  // tasse posée sur le dessus, qui fume
  rect(t, 9, 3, 3, 2, "w");
  px(t, 11, 3, "H");
  contour(t);
  const fumee = f === 0 ? [[9, 1], [10, 0]] : [[10, 1], [9, 0]];
  for (const [x, y] of fumee) t[y][x] = "H";
  const vapeur = f === 0 ? [[7, 12]] : [[8, 12]];
  for (const [x, y] of vapeur) t[y][x] = "h";
  ombre(t, 5, 21, 11, 1);
  return figer(t);
}

export function spritesDecor() {
  return {
    "meuble.bureau": sprite([bureau(true)], { pivot: [16, 21] }),
    "meuble.bureau_vide": sprite([bureau(false)], { pivot: [16, 21] }),
    "meuble.chaise": sprite([chaiseSeule()], { pivot: [8, 23] }),
    ...ecrans(),
    "sol.piece": sprite([solPiece()], { pivot: [0, 0] }),
    "sol.couloir": sprite([solCouloir()], { pivot: [0, 0] }),
    "mur.haut": sprite([murHaut()], { pivot: [0, 0] }),
    "mur.cote": sprite([murCote()], { pivot: [0, 0] }),
    "mur.angle": sprite([murAngle()], { pivot: [0, 0] }),
    "porte.piece": sprite([portePiece()], { pivot: [0, 0] }),
    "porte.utilisateur.fermee": sprite([porteUtilisateur("fermee")], { pivot: [8, 15] }),
    "porte.utilisateur.attente": sprite([porteUtilisateur("attente")], { pivot: [8, 15] }),
    "porte.utilisateur.agir": sprite([porteUtilisateur("agir", 0), porteUtilisateur("agir", 1)], { fps: 2, pivot: [8, 15] }),
    plante: sprite([plante()], { pivot: [9, 18] }),
    "panneau.equipe": { ...sprite([panneau()], { pivot: [39, 12] }), zone: [3, 3, 72, 7] },
    "machine.cafe": sprite([machineCafe(0), machineCafe(1)], { fps: 2, pivot: [8, 21] }),
  };
}
