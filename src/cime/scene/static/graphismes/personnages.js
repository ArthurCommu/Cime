// Personnages : agents assis (vus de dos, face à leur écran), l’utilisateur et le facteur.
//
// Vue de dessus 3/4 : l'agent est assis côté couloir de son bureau, de dos,
// et regarde son écran posé au fond du bureau. C'est ce qui permet de voir
// l'écran (texte, lecture, terminal, pensée) par-dessus sa tête.
//
// Gabarits : les chiffres sont des couleurs de rôle, traduites à la fin.
//   1 cheveux clairs  2 cheveux  3 cheveux ombre
//   4 peau            5 peau ombre
//   6 vêtement        7 vêtement ombre
//   9 accessoire (casque de l'assistant, col du coordinateur, capuche du worker)

import { toile, coller, contour, figer, recolorer, hachurer, px, rect, miroir, sprite } from "./dessin.js";

const COMMUN = { 4: "s", 5: "S" };

export const ROLES = {
  // Teal, blond, casque audio : on le reconnaît à ses oreillettes.
  assistant: { 1: "l", 2: "d", 3: "B", 6: "t", 7: "T", 9: "K", ...COMMUN },
  // Violet, brun, chignon et col blanc.
  coordinateur: { 1: "B", 2: "b", 3: "K", 6: "v", 7: "V", 9: "w", ...COMMUN },
  // Bleu, cheveux noirs, sweat à capuche.
  worker: { 1: "g", 2: "K", 3: "k", 6: "u", 7: "U", 9: "U", ...COMMUN },
};

// ─── Pièces détachées (vue de dos) ──────────────────────────────────────────

const TETE_DOS = [
  "..1122..",
  ".112222.",
  "12222223",
  "22222223",
  "22222233",
  ".222233.",
  "..4445..",
];

const TORSE = [
  ".66666666.",
  "6666666677",
  "6666666677",
  "6666666677",
  "6666666677",
  "6666666677",
];

const DOSSIER = [
  ".GGGGGGGG.",
  "GggggggggK",
  "GggggggggK",
  "GggggggggK",
  ".KKKKKKKK.",
];

function chaise(t, dx = 0, dy = 0) {
  coller(t, DOSSIER, 3 + dx, 15 + dy);
  rect(t, 7 + dx, 20 + dy, 2, 1, "K");
  rect(t, 4 + dx, 21 + dy, 8, 1, "g");
  for (const x of [3, 4, 11, 12]) px(t, x + dx, 22 + dy, "K");
}

function accessoires(t, role, x, y) {
  if (role === "assistant") {
    // arceau du casque et oreillettes qui débordent de la silhouette
    for (let i = 1; i <= 6; i++) px(t, x + i, y + 1, "9");
    px(t, x, y + 2, "9");
    px(t, x + 7, y + 2, "9");
    for (const [i, j] of [[-1, 3], [0, 3], [-1, 4], [0, 4], [7, 3], [8, 3], [7, 4], [8, 4]]) px(t, x + i, y + j, "9");
  } else if (role === "coordinateur") {
    // chignon
    px(t, x + 3, y - 2, "1");
    px(t, x + 4, y - 2, "2");
    px(t, x + 3, y - 1, "2");
    px(t, x + 4, y - 1, "3");
  }
}

function accessoiresTorse(t, role, x, y) {
  if (role === "coordinateur") rect(t, x + 3, y, 4, 1, "9");
  if (role === "worker") {
    coller(t, ["..9999..", "...99..."], x + 1, y);
  }
}

// ─── Bras (côté droit ; le gauche est le miroir x → 15 - x) ─────────────────
// Chaque pose : liste de [x, y, couleur] dans la toile 16×24 au repos.

function manche(x, y0, y1) {
  const r = [];
  for (let y = y0; y <= y1; y++) r.push([x, y, "6"], [x + 1, y, "7"]);
  return r;
}

const BRAS = {
  bas: () => [],
  // mains sur le clavier (main en y = yh)
  clavier: (yh = 9) => [...manche(12, yh + 1, 10), [12, yh, "4"], [13, yh, "4"]],
  // geste « entrée » : la main se lève puis frappe
  entree: (yh) => [...manche(12, yh + 1, 10), [12, yh, "4"], [13, yh, "5"]],
  // main sur la souris : le bras part en diagonale vers la droite
  souris: (dy = 0) => [[12, 10, "6"], [13, 10, "7"], [13, 9, "6"], [14, 9, "7"], [14, 8 + dy, "4"], [13, 8 + dy, "4"]],
  // main levée, paume ouverte (ox : petit balancement)
  leve: (ox = 0) => [
    ...manche(12, 4, 10),
    [12 + ox, 3, "6"], [13 + ox, 3, "7"],
    [12 + ox, 1, "4"], [13 + ox, 1, "4"], [12 + ox, 2, "4"], [13 + ox, 2, "4"], [11 + ox, 2, "4"],
  ],
  // poing levé
  poing: (yh = 2) => [...manche(12, yh + 2, 10), [12, yh, "4"], [13, yh, "5"], [12, yh + 1, "4"], [13, yh + 1, "5"]],
  // bras écartés vers le haut (étirement de victoire)
  victoire: () => [...manche(13, 4, 9), [12, 10, "6"], [13, 10, "7"], [13, 2, "4"], [14, 2, "4"], [13, 3, "4"], [14, 3, "5"]],
  // main au menton, coude sorti
  menton: () => [
    [12, 11, "6"], [13, 11, "6"], [14, 11, "7"], [14, 10, "7"], [14, 9, "7"], [13, 9, "6"],
    [13, 8, "4"], [12, 8, "4"], [12, 7, "4"],
  ],
  // mains croisées derrière la nuque, coudes grands ouverts (sieste)
  nuque: () => [
    [10, 11, "6"], [11, 10, "6"], [12, 9, "6"], [13, 8, "6"], [14, 8, "7"], [14, 9, "7"],
    [14, 10, "7"], [13, 11, "7"], [13, 12, "7"], [12, 12, "6"], [12, 10, "7"], [12, 11, "7"], [13, 9, "7"], [13, 10, "7"],
  ],
  // tient la feuille de demande au-dessus de la tête
  pancarte: () => [...manche(12, 5, 10), [12, 4, "6"], [13, 4, "7"]],
};

function bras(t, points, cote, dy) {
  for (const [x, y, c] of points) px(t, cote === "d" ? x : 15 - x, y + dy, c);
}

// ─── Personnage assis ───────────────────────────────────────────────────────
// pose = { g, d : [nom, arg] des bras ; tete: {dx, dy} ; corps: dy ;
//          renverse, pancarte, oreiller, points, chaise: [dx, dy], vide }

function assis(role, pose = {}) {
  const t = toile(16, 24);
  const dy = pose.corps ?? 0;
  const tdx = pose.tete?.dx ?? 0;
  const tdy = (pose.tete?.dy ?? 0) + dy;
  const [cdx, cdy] = pose.chaise ?? [0, 0];

  if (pose.vide) {
    chaise(t, cdx, cdy);
    contour(t);
    return figer(t);
  }

  if (pose.renverse) {
    // sieste : renversé en arrière contre le dossier, mains derrière la tête
    coller(t, TORSE, 3, 12 + dy);
    accessoiresTorse(t, role, 3, 12 + dy);
    coller(t, TETE_DOS, 4, 6 + dy);
    accessoires(t, role, 4, 6 + dy);
    chaise(t);
    bras(t, BRAS.nuque(), "d", dy);
    bras(t, BRAS.nuque(), "g", dy);
    rect(t, 6, 11 + dy, 4, 1, "4");
    px(t, 7, 11 + dy, "5");
  } else if (pose.oreiller) {
    // dormir : la tête posée sur les bras croisés sur le bureau
    coller(t, TORSE, 3, 10 + dy);
    chaise(t);
    rect(t, 1, 6 + dy, 14, 3, "6");
    rect(t, 1, 8 + dy, 14, 1, "7");
    px(t, 1, 7 + dy, "4");
    px(t, 14, 7 + dy, "4");
    coller(t, TETE_DOS.slice(0, 6), 4, 3 + dy);
    accessoires(t, role, 4, 3 + dy);
  } else {
    coller(t, TORSE, 3, 11 + dy);
    accessoiresTorse(t, role, 3, 11 + dy);
    coller(t, TETE_DOS, 4 + tdx, 4 + tdy);
    accessoires(t, role, 4 + tdx, 4 + tdy);
    chaise(t, cdx, cdy);
    const [ng, ag] = pose.g ?? ["bas"];
    const [nd, ad] = pose.d ?? ["bas"];
    bras(t, BRAS[ng](ag), "g", dy);
    bras(t, BRAS[nd](ad), "d", dy);
    if (pose.pancarte) {
      rect(t, 1, 0, 14, 4, "w");
      rect(t, 3, 1, 8, 1, "h");
      rect(t, 3, 2, 5, 1, "h");
      rect(t, 1, 3, 14, 1, "H");
      px(t, 2, 3, "4");
      px(t, 13, 3, "4");
    }
  }

  const image = recolorer(figer(contour(t)), ROLES[role]);
  if (pose.points) {
    // points de suspension au-dessus de la tête (sans contour : posés sur l'écran)
    const t2 = image.map((l) => [...l]);
    [4, 7, 10].slice(0, pose.points).forEach((x) => (t2[1][x] = "w"));
    return t2.map((l) => l.join(""));
  }
  if (pose.etincelle) {
    const t2 = image.map((l) => [...l]);
    for (const [x, y] of [[15, 8], [14, 6], [15, 11]]) t2[y][x] = "l";
    return t2.map((l) => l.join(""));
  }
  return image;
}

// ─── Personnage debout, vu de dos (embauche) ────────────────────────────────

function deboutDos(role, phase) {
  const t = toile(16, 20);
  // jambes (pantalon ardoise, chaussures sombres)
  const lg = phase === 1 ? -1 : 0; // jambe gauche levée
  const ld = phase === 2 ? -1 : 0;
  rect(t, 5, 13, 2, 4 + lg, "g");
  rect(t, 5, 17 + lg, 2, 1, "K");
  rect(t, 9, 13, 2, 4 + ld, "g");
  rect(t, 9, 17 + ld, 2, 1, "K");
  coller(t, TORSE, 3, 7);
  accessoiresTorse(t, role, 3, 7);
  // bras le long du corps, mains qui balancent
  const bg = phase === 1 ? 1 : phase === 2 ? -1 : 0;
  rect(t, 2, 8, 1, 4 + bg, "6");
  px(t, 2, 12 + bg, "4");
  rect(t, 13, 8, 1, 4 - bg, "7");
  px(t, 13, 12 - bg, "4");
  coller(t, TETE_DOS, 4, 0 + (phase === 0 ? 0 : 0));
  accessoires(t, role, 4, 0);
  return recolorer(figer(contour(t)), ROLES[role]);
}

// ─── Animations des agents ──────────────────────────────────────────────────

function animsAgent(role) {
  const A = (pose) => assis(role, pose);
  const clavier = (g, d) => ({ g: ["clavier", g], d: ["clavier", d] });
  const s = {};

  // idle : quasi immobile ; de dos, le « clignement » est un léger hochement de tête.
  const repos = A({});
  s.idle = sprite([repos, repos, repos, repos, repos, A({ tete: { dx: 0, dy: 1 } })], { fps: 2 });

  // taper : mains sur le clavier, rythme lent
  s.taper = sprite([A(clavier(9, 8)), A(clavier(8, 9))], { fps: 3 });

  // écrire : mains rapides, tête un peu penchée
  s.ecrire = sprite(
    [
      A({ ...clavier(9, 8), tete: { dy: 1 } }),
      A({ ...clavier(8, 9), tete: { dy: 1 } }),
      A({ ...clavier(9, 9), tete: { dy: 1 } }),
      A({ ...clavier(8, 8), tete: { dy: 1 } }),
    ],
    { fps: 8 },
  );

  // lire : la tête balaie la page, la main fait défiler à la souris
  s.lire = sprite(
    [
      A({ d: ["souris", 0], tete: { dx: -1 } }),
      A({ d: ["souris", 0], tete: { dx: 0 } }),
      A({ d: ["souris", 1], tete: { dx: 1 } }),
      A({ d: ["souris", 0], tete: { dx: 0 } }),
    ],
    { fps: 2 },
  );

  // exécuter : la main gauche attend, la droite arme puis frappe « entrée »
  s.executer = sprite(
    [
      A({ g: ["clavier", 9], d: ["entree", 9] }),
      A({ g: ["clavier", 9], d: ["entree", 6] }),
      A({ g: ["clavier", 9], d: ["entree", 5] }),
      A({ g: ["clavier", 9], d: ["entree", 9], etincelle: true }),
    ],
    { fps: 4 },
  );

  // réfléchir : main au menton, coude sorti, points de suspension
  const pense = (n) => A({ d: ["menton"], tete: { dx: 0 }, points: n });
  s.reflechir = sprite([pense(0), pense(1), pense(2), pense(3)], { fps: 2 });

  // dormir (au repos) : tête sur les bras, respiration lente.
  // Pas de zzz intégré : le moteur peut poser bulle.zzz (MONTAGE.bulle).
  s.dormir = sprite([A({ oreiller: true }), A({ oreiller: true, corps: 1 })], { fps: 1 });

  // sieste (compactage) : renversé contre le dossier, mains derrière la tête, coudes ouverts.
  // Pas de zzz intégré : le moteur pose bulle.zzz au-dessus (MONTAGE.bulle).
  s.sieste = sprite([A({ renverse: true }), A({ renverse: true, corps: 1 })], { fps: 1 });

  // attend une autorisation : brandit la feuille de demande, immobile (bloqué).
  // Le halo rouge est le sprite alerte.halo, posé par le moteur.
  s.attend_autorisation = sprite(
    [A({ g: ["pancarte"], d: ["pancarte"], pancarte: true }), A({ g: ["pancarte"], d: ["pancarte"], pancarte: true, corps: 0, tete: { dy: 1 } })],
    { fps: 1 },
  );

  // attend une réponse : main levée qui s'agite doucement
  s.attend_reponse = sprite([A({ d: ["leve", 0] }), A({ d: ["leve", 1] })], { fps: 3 });

  // arrêté : la chaise vide, poussée en arrière
  s.arrete = sprite([A({ vide: true, chaise: [1, 1] })]);

  // inconnu : silhouette grise hachurée
  s.inconnu = sprite([hachurer(repos)]);

  // fin de tâche : s'étire, lève le poing, se rassoit
  s.fin_tache = sprite(
    [
      A(clavier(9, 9)),
      A({ g: ["victoire"], d: ["victoire"] }),
      A({ g: ["victoire"], d: ["victoire"], corps: -1 }),
      A({ d: ["poing", 2] }),
      A({ d: ["poing", 3] }),
      repos,
    ],
    { fps: 5, boucle: false },
  );

  // arrivée (embauche) : entre par le bas, tire la chaise, s'assoit.
  const frames = [];
  const chaiseVide = assis(role, { vide: true, chaise: [1, 1] });
  const chaiseRangee = assis(role, { vide: true });
  const cadre = (fond, debout, x, y) => {
    const t = toile(24, 32);
    if (fond) coller(t, fond, 4, 0);
    if (debout) coller(t, debout, x, y);
    return t;
  };
  frames.push(figer(cadre(chaiseVide, deboutDos(role, 1), 8, 12)));
  frames.push(figer(cadre(chaiseVide, deboutDos(role, 2), 7, 9)));
  frames.push(figer(cadre(chaiseVide, deboutDos(role, 1), 5, 6)));
  {
    // debout entre la chaise et le bureau : la chaise passe devant ses jambes
    const t = cadre(null, deboutDos(role, 0), 4, 2);
    coller(t, chaiseRangee, 4, 0);
    frames.push(figer(t));
  }
  frames.push(figer(cadre(A({ corps: -2 }), null)));
  frames.push(figer(cadre(repos, null)));
  frames.push(figer(cadre(A(clavier(9, 9)), null)));
  s.arrive = sprite(frames, { fps: 6, boucle: false, pivot: [12, 23] });

  return s;
}

// ─── l’utilisateur, debout devant sa porte (de face) ───────────────────────────────

const UTILISATEUR = [
  "................",
  "......bbbb......",
  ".....bBBbbb.....",
  "....bBbbbbbb....",
  "....bsssssSb....",
  "....sskssksS....",
  "....ssssssSS....",
  ".....ssSSss.....",
  "...GggwyywggK...",
  "..GGgggyygggKK..",
  "..GGgggyygggKK..",
  "..GGgggyygggKww.",
  "..ssgggggggKsww.",
  "....KKKKKKKK....",
  "....KKK..KKK....",
  "....KKK..KKK....",
  "....KKK..KKK....",
  "...bbbb..bbbb...",
  "................",
];

function utilisateur() {
  const ouvert = figer(contour(coller(toile(16, 19), UTILISATEUR)));
  const t = coller(toile(16, 19), UTILISATEUR);
  rect(t, 6, 5, 1, 1, "s");
  rect(t, 9, 5, 1, 1, "s");
  rect(t, 6, 6, 1, 1, "S");
  rect(t, 9, 6, 1, 1, "S");
  const ferme = figer(contour(t));
  return {
    idle: sprite([ouvert, ouvert, ouvert, ouvert, ouvert, ferme], { fps: 2 }),
    inconnu: sprite([hachurer(ouvert)]),
  };
}

// ─── Le facteur ─────────────────────────────────────────────────────────────
// Casquette bleue, veste jaune, sacoche de cuir en bandoulière.

const FACTEUR_TETE = {
  bas: ["..UUUU..", ".UuuUUU.", "KKKKKKKK", "bssssssb", "sskssksS", "ssssssSS", ".ssSSss."],
  haut: ["..UUUU..", ".UuUUUU.", "UUUUUUUU", "bbbbbbbb", "bbbbbbbb", ".bbbbbb.", "..ssss.."],
  gauche: ["..UUUU..", ".UuUUUU.", "KKKUUUUU", ".ssssbbb", ".kssbbbb", ".ssssbb.", "..ssss.."],
};

const FACTEUR_CORPS = {
  bas: [
    "..lyyyyyyY..",
    ".lyybyyyyYY.",
    ".lyyybyyyYY.",
    ".lyyyybyBBB.",
    ".sYyyyybBbBs",
    "...YYYYBBB..",
  ],
  haut: [
    "..lyyyyyyY..",
    ".lyyyyyyyYY.",
    ".lyyyyybyYY.",
    ".BBByybyyYY.",
    "sBbByyyyyYs.",
    "..BBBYYYY...",
  ],
  gauche: [
    "...lyyyY....",
    "...lyyyYY...",
    "..BBByyYY...",
    "..BbByyY....",
    "..BBBsYY....",
    "....YYYY....",
  ],
};

function facteurFrame(dir, phase, bob = 0) {
  const t = toile(16, 21);
  const d = dir === "droite" ? "gauche" : dir;
  const y0 = 1 + bob;
  // jambes
  if (d === "gauche") {
    // de profil : les jambes se croisent
    const ecart = phase === 0 ? 2 : phase === 2 ? -2 : 0;
    rect(t, 7 - (ecart > 0 ? 1 : 0), 14 + y0 - 1, 2, 4, "g");
    if (ecart !== 0) {
      rect(t, 6, 17 + y0 - 1, 2, 1, "K");
      rect(t, 9, 16 + y0 - 1, 1, 2, "g");
      rect(t, 9, 17 + y0 - 1, 2, 1, "K");
    } else {
      rect(t, 6, 17 + y0 - 1, 3, 1, "K");
    }
  } else {
    const lg = phase === 0 ? 1 : 0;
    const ld = phase === 2 ? 1 : 0;
    rect(t, 5, 13 + y0, 2, 3 + lg, "g");
    rect(t, 5, 16 + y0 + lg, 2, 1, "K");
    rect(t, 9, 13 + y0, 2, 3 + ld, "g");
    rect(t, 9, 16 + y0 + ld, 2, 1, "K");
  }
  coller(t, FACTEUR_CORPS[d], 2, 7 + y0);
  coller(t, FACTEUR_TETE[d], 4, y0);
  contour(t);
  const image = figer(t);
  return dir === "droite" ? miroir(image) : image;
}

function facteur() {
  const s = {};
  for (const dir of ["haut", "bas", "gauche", "droite"]) {
    s[`marche_${dir}`] = sprite(
      [facteurFrame(dir, 0, 0), facteurFrame(dir, 1, -1), facteurFrame(dir, 2, 0), facteurFrame(dir, 1, -1)],
      { fps: 6 },
    );
  }
  const face = facteurFrame("bas", 1, 0);
  const cligne = face.map((l, y) => (y === 5 ? l.replaceAll("k", "s") : l));
  s.idle = sprite([face, face, face, face, cligne], { fps: 2 });

  // dormir : assis par terre contre sa sacoche, la casquette sur les yeux
  const dort = (souffle) => {
    const t = toile(16, 21);
    rect(t, 3, 17, 10, 2, "g"); // jambes allongées
    rect(t, 2, 18, 2, 1, "K");
    rect(t, 12, 18, 2, 1, "K");
    coller(t, FACTEUR_CORPS.bas.slice(0, 5), 2, 11 + souffle);
    coller(t, ["..UUUU..", ".UuuUUU.", "UUUUUUUU", "KKKKKKKK", "ssssssSS", ".ssSSss."], 4, 5 + souffle * 0 + 1);
    rect(t, 11, 15, 4, 3, "B");
    rect(t, 11, 15, 4, 1, "b");
    return figer(contour(t));
  };
  s.dormir = sprite([dort(0), dort(1)], { fps: 1 });

  // arrêté (problème) : tombé à plat ventre, sacoche vide, lettres éparpillées
  const tombe = (etoiles) => {
    const t = toile(24, 14);
    // corps allongé, tête à gauche
    coller(t, ["..UUU.", ".UuUUU", "KUUUUU", ".bbbbb", "..sss."], 1, 5);
    rect(t, 7, 6, 8, 4, "y");
    rect(t, 7, 9, 8, 1, "Y");
    rect(t, 15, 7, 5, 2, "g");
    rect(t, 20, 7, 2, 2, "K");
    // sacoche ouverte, vide
    coller(t, ["BBBB", "b..b", "bbbb"], 9, 10);
    contour(t, "r");
    // lettres échappées
    coller(t, ["wwh", "hww"], 18, 1);
    coller(t, ["www", "hhw"], 2, 11);
    if (etoiles) {
      for (const [x, y] of [[1, 2], [4, 1], [7, 3]]) px(t, x, y, "R");
    } else {
      for (const [x, y] of [[2, 1], [5, 3], [7, 1]]) px(t, x, y, "R");
    }
    return figer(t);
  };
  s.arrete = sprite([tombe(true), tombe(false)], { fps: 2 });
  return s;
}

// ─── Assemblage ─────────────────────────────────────────────────────────────

export function spritesPersonnages() {
  const r = {};
  for (const role of Object.keys(ROLES)) {
    for (const [anim, sp] of Object.entries(animsAgent(role))) r[`perso.${role}.${anim}`] = sp;
  }
  for (const [anim, sp] of Object.entries(utilisateur())) r[`perso.utilisateur.${anim}`] = sp;
  for (const [anim, sp] of Object.entries(facteur())) r[`perso.facteur.${anim}`] = sp;
  return r;
}
