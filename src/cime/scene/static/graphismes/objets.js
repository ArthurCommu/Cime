// Enveloppes, bulles, icônes et alertes.

import { toile, coller, contour, figer, px, rect, sprite } from "./dessin.js";

// ─── Enveloppes (12×11, pivot au centre bas) ────────────────────────────────
// Corps 8×6 ; la ligne 10 reste libre pour une ombre au sol.

function enveloppe(t, x, y, { corps = "w", pli = "h", rabat = true } = {}) {
  rect(t, x, y, 8, 6, corps);
  rect(t, x, y + 5, 8, 1, "H");
  rect(t, x + 7, y, 1, 6, "H");
  if (rabat) for (const [i, j] of [[0, 0], [1, 1], [2, 2], [3, 3], [4, 3], [5, 2], [6, 1], [7, 0]]) px(t, x + i, y + j, pli);
}

function env(dessin, ombreSol = false) {
  const t = toile(12, 11);
  dessin(t);
  contour(t);
  if (ombreSol) rect(t, 3, 10, 6, 1, "h");
  return figer(t);
}

function enveloppes() {
  const s = {};
  s["enveloppe.inscrit"] = sprite([env((t) => enveloppe(t, 2, 3))]);

  s["enveloppe.livre"] = sprite(
    [0, -1, -2, -1].map((dy) => env((t) => enveloppe(t, 2, 3 + dy), true)),
    { fps: 6 },
  );

  // pris en compte : le rabat se soulève, la lettre sort
  s["enveloppe.pris_en_compte"] = sprite(
    [
      env((t) => enveloppe(t, 2, 3)),
      env((t) => {
        // rabat à moitié levé : on voit l'intérieur sombre
        enveloppe(t, 2, 3, { rabat: false });
        rect(t, 2, 3, 8, 2, "h");
        rect(t, 3, 2, 6, 1, "H");
        rect(t, 4, 1, 4, 1, "H");
      }),
      env((t) => {
        // rabat ouvert en triangle, la lettre affleure
        coller(t, ["...HH...", "..HHHH..", ".HHHHHH."], 2, 0);
        enveloppe(t, 2, 3, { rabat: false });
        rect(t, 3, 3, 6, 1, "w");
        rect(t, 2, 4, 8, 1, "h");
      }),
      env((t) => {
        // la lettre sort
        coller(t, ["...HH...", "..HHHH..", ".HHHHHH."], 2, 1);
        rect(t, 3, 0, 6, 5, "w");
        rect(t, 4, 1, 4, 1, "h");
        rect(t, 4, 3, 3, 1, "h");
        enveloppe(t, 2, 4, { rabat: false });
        rect(t, 2, 4, 8, 1, "h");
      }),
    ],
    { fps: 6, boucle: false },
  );

  // clos : le tampon descend et laisse un rond vert
  const rond = (t) => {
    for (const [x, y] of [[5, 4], [6, 4], [4, 5], [7, 5], [4, 6], [7, 6], [5, 7], [6, 7]]) px(t, x, y, "E");
  };
  s["enveloppe.clos"] = sprite(
    [
      env((t) => enveloppe(t, 2, 3)),
      env((t) => {
        enveloppe(t, 2, 3);
        rect(t, 5, 0, 2, 2, "b");
        rect(t, 4, 2, 4, 2, "B");
      }),
      env((t) => {
        enveloppe(t, 2, 3);
        rond(t);
      }),
    ],
    { fps: 4, boucle: false },
  );

  // échec : froissée, contour rouge, déchirure rouge — rouge seulement tant qu'une alarme grave porte sur ce message ;
  // sans alarme, la même enveloppe est grise (« _gris »).
  const echec = (vif, sombre) => [
    (() => {
      const t = toile(12, 11);
      coller(t, [".wwHw.w.", "wwhwwwHw", "wHwwhwww", "wwwHwwhw", "wwhwwHww", ".wwHww.w"], 2, 3);
      for (const [x, y] of [[4, 4], [5, 5], [6, 6], [7, 7], [7, 4], [5, 7]]) px(t, x, y, vif);
      contour(t, sombre);
      return figer(t);
    })(),
  ];
  s["enveloppe.echec"] = sprite(echec("R", "r"));
  s["enveloppe.echec_gris"] = sprite(echec("i", "I"));

  // abandonné : terne, barré d'un trait rouge (gris sans alarme grave)
  const abandonne = (trait) => [
    (() => {
      const t = toile(12, 11);
      enveloppe(t, 2, 3, { corps: "H", pli: "h" });
      contour(t);
      for (let i = 0; i < 10; i++) {
        px(t, 1 + i, 9 - Math.round(i * 0.75), trait);
        px(t, 1 + i, 10 - Math.round(i * 0.75), trait);
      }
      return figer(t);
    })(),
  ];
  s["enveloppe.abandonne"] = sprite(abandonne("R"));
  s["enveloppe.abandonne_gris"] = sprite(abandonne("I"));
  return s;
}

// ─── Bulles (12×12, pivot au bout de la queue, en bas à gauche) ─────────────

function bulle(fond, symbole, couleur, queue = "pointe") {
  const t = toile(12, 12);
  rect(t, 2, 1, 8, 8, fond);
  rect(t, 1, 2, 10, 6, fond);
  if (queue === "pointe") {
    px(t, 3, 9, fond);
    px(t, 2, 10, fond);
  } else {
    px(t, 3, 10, fond);
  }
  coller(t, symbole, 3, 2, { "#": couleur });
  contour(t);
  return figer(t);
}

const SYMBOLES = {
  exclamation: ["..##..", "..##..", "..##..", "..##..", "......", "..##.."],
  question: [".####.", "....##", "...##.", "..##..", "......", "..##.."],
  pensee: ["......", "......", "......", "#.#.#.", "......", "......"],
  coche: ["......", ".....#", "....##", "#..##.", "####..", ".##..."],
};

function zzz(n) {
  const t = toile(12, 12);
  const z = [
    [["###", ".#.", "###"], 1, 8],
    [["####", "..#.", ".#..", "####"], 4, 4],
    [["#####", "...#.", "..#..", ".#...", "#####"], 6, 0],
  ];
  z.slice(0, n).forEach(([m, x, y]) => coller(t, m, x, y, { "#": "w" }));
  // contour léger, pour rester lisible sur un écran comme sur le sol
  contour(t, "G");
  return figer(t);
}

function bulles() {
  return {
    // « ! » : une autorisation qu'on attend. Une attente est ambre, pas rouge (le rouge est réservé aux problèmes).
    "bulle.exclamation": sprite([bulle("y", SYMBOLES.exclamation, "k"), bulle("Y", SYMBOLES.exclamation, "k")], {
      fps: 2,
      pivot: [2, 11],
    }),
    "bulle.question": sprite([bulle("w", SYMBOLES.question, "U")], { pivot: [2, 11] }),
    "bulle.zzz": sprite([zzz(1), zzz(2), zzz(3)], { fps: 2, pivot: [2, 11] }),
    "bulle.pensee": sprite([bulle("w", SYMBOLES.pensee, "G", "ronde")], { pivot: [3, 11] }),
    "bulle.coche": sprite([bulle("w", SYMBOLES.coche, "E")], { pivot: [2, 11] }),
  };
}

// ─── Icônes ─────────────────────────────────────────────────────────────────

function icones() {
  const piece = toile(11, 11);
  coller(piece, [".yyyyy.", "yllyyyY", "ylyYyyY", "yyyYyyY", "yyyYyyY", "yyyyyYY", ".YYYYY."], 2, 2);
  contour(piece);

  const memoire = toile(12, 11);
  rect(memoire, 2, 3, 8, 5, "g");
  rect(memoire, 2, 3, 8, 1, "G");
  rect(memoire, 3, 5, 4, 1, "q");
  for (const x of [3, 5, 7, 9]) {
    px(memoire, x - 1 + 1, 2, "H");
    px(memoire, x - 1 + 1, 8, "H");
  }
  contour(memoire);

  const jauge = toile(32, 5);
  rect(jauge, 0, 0, 32, 1, "k");
  rect(jauge, 0, 4, 32, 1, "k");
  rect(jauge, 0, 0, 1, 5, "k");
  rect(jauge, 31, 0, 1, 5, "k");

  const inconnu = toile(10, 11);
  coller(inconnu, [".####.", "##..##", "...##.", "..##..", "......", "..##.."], 2, 2, { "#": "i" });
  contour(inconnu, "I");

  return {
    "icone.cout": sprite([figer(piece)], { pivot: [5, 10] }),
    "icone.contexte": sprite([figer(memoire)], { pivot: [6, 10] }),
    "jauge.cadre": { ...sprite([figer(jauge)], { pivot: [0, 4] }), zone: [1, 1, 30, 3] },
    "icone.inconnu": sprite([figer(inconnu)], { pivot: [5, 10] }),
  };
}

// ─── Alertes (rouge) ────────────────────────────────────────────────────────

// Halo : cadre plein de 2 px autour d'un rectangle (w×h), coins arrondis d'un pixel ; il respire (quatre images).
// Filet extérieur vif, filet intérieur plus sombre qui s'allume à la moitié du cycle : une lueur franche, pas un
// pointillé de débogage. Rouge (R, r) pour un problème ; ambre (y, Y) pour une attente (attente.halo).
export function halo(w, h, teinte = "rouge") {
  const [vif, sombre] = teinte === "ambre" ? ["y", "Y"] : ["R", "r"];
  const cadre = (t, inset, couleur) => {
    for (let x = inset + 1; x < w - inset - 1; x++) {
      t[inset][x] = couleur;
      t[h - 1 - inset][x] = couleur;
    }
    for (let y = inset + 1; y < h - inset - 1; y++) {
      t[y][inset] = couleur;
      t[y][w - 1 - inset] = couleur;
    }
  };
  const cycle = [[vif, sombre], [vif, vif], [vif, sombre], [sombre, sombre]]; // [filet extérieur, filet intérieur] à chaque image
  return cycle.map(([dehors, dedans]) => {
    const t = toile(w, h);
    cadre(t, 0, dehors);
    cadre(t, 1, dedans);
    return figer(t);
  });
}

function stop(fond) {
  const t = toile(14, 14);
  coller(
    t,
    [
      "...######...",
      "..#WWWWWW#..",
      ".#W######W#.",
      "#W########W#",
      "#W########W#",
      "#W#WWWWWW#W#",
      "#W#WWWWWW#W#",
      "#W########W#",
      "#W########W#",
      ".#W######W#.",
      "..#WWWWWW#..",
      "...######...",
    ],
    1,
    1,
    { "#": fond, W: "w" },
  );
  contour(t);
  return figer(t);
}

// Rouge pour une alarme grave (alerte.sirene) ; ambre pour une alarme « à voir » (attente.sirene).
function sirene(f, [vif, sombre] = ["R", "r"]) {
  const t = toile(18, 14);
  rect(t, 6, 4, 6, 6, vif);
  rect(t, 7, 3, 4, 1, vif);
  rect(t, 7, 4, 1, 3, "w");
  rect(t, 8, 4, 1, 1, "w");
  rect(t, 6, 9, 6, 1, sombre);
  rect(t, 4, 10, 10, 2, "g");
  rect(t, 4, 10, 10, 1, "G");
  contour(t);
  const rayons = {
    0: [[3, 4], [2, 3], [1, 2], [3, 6], [1, 6]],
    1: [[9, 0], [9, 1], [5, 1], [13, 1]],
    2: [[14, 4], [15, 3], [16, 2], [14, 6], [16, 6]],
  }[f];
  for (const [x, y] of rayons) t[y][x] = vif;
  return figer(t);
}

// « ? » rouge : la donnée dit que la pièce est bloquée, mais aucune cause n'est visible dans la pièce.
// 8×8 avec son contour ; il tient à gauche de la sirène, dans l'en-tête de la pièce.
function causeInconnue(fond) {
  const t = toile(8, 8);
  coller(t, [".####.", "##..##", "...##.", "..##..", "......", "..##.."], 1, 1, { "#": fond });
  contour(t);
  return figer(t);
}

// Compteur de postes repliés et d'agents hors organigramme : une pile de dossiers gris, 10×9 avec son contour.
// Gris neutre (pas de rouge, pas d'ambre) : ce sont des agents arrêtés, pas des problèmes.
function dossiers() {
  const t = toile(10, 9);
  rect(t, 4, 1, 5, 4, "G"); // dossier du fond
  rect(t, 4, 1, 3, 1, "h"); // onglet
  rect(t, 1, 3, 6, 5, "H"); // dossier de devant
  rect(t, 1, 3, 6, 1, "w"); // bord clair
  rect(t, 1, 7, 6, 1, "h"); // ombre basse
  contour(t);
  return figer(t);
}

export function spritesObjets() {
  return {
    ...enveloppes(),
    ...bulles(),
    ...icones(),
    "compteur.dossiers": sprite([dossiers()], { pivot: [0, 0] }),
    "alerte.refus_garde": sprite([stop("R"), stop("r")], { fps: 2, pivot: [7, 13] }),
    "alerte.cause_inconnue": sprite([causeInconnue("R"), causeInconnue("r")], { fps: 2, pivot: [0, 0] }),
    "alerte.sirene": sprite([sirene(0), sirene(1), sirene(2), sirene(1)], { fps: 6, pivot: [9, 13] }),
    "attente.sirene": sprite([sirene(0, ["y", "Y"]), sirene(1, ["y", "Y"]), sirene(2, ["y", "Y"]), sirene(1, ["y", "Y"])], { fps: 6, pivot: [9, 13] }),
  };
}
