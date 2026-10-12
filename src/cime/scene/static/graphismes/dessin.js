// Petits outils de dessin sur grille de caractères (sans DOM).
// Une « toile » est un tableau de lignes, chaque ligne un tableau de caractères.
// Une « image » (ce que contient l'atlas) est un tableau de chaînes.

export function toile(w, h, fond = ".") {
  return Array.from({ length: h }, () => Array(w).fill(fond));
}

export function depuis(image) {
  return image.map((l) => [...l]);
}

export function figer(t) {
  return t.map((l) => l.join(""));
}

export function px(t, x, y, c) {
  if (y >= 0 && y < t.length && x >= 0 && x < t[0].length) t[y][x] = c;
}

export function rect(t, x, y, w, h, c) {
  for (let j = y; j < y + h; j++) for (let i = x; i < x + w; i++) px(t, i, j, c);
}

// Colle un motif (tableau de chaînes) en (x, y). « . » ne peint pas.
// `table` traduit des caractères du motif (gabarits de couleur).
export function coller(t, motif, x = 0, y = 0, table = {}) {
  motif.forEach((ligne, j) => {
    [...ligne].forEach((c, i) => {
      if (c === "." || c === " ") return;
      px(t, x + i, y + j, table[c] ?? c);
    });
  });
  return t;
}

// Contour d'un pixel autour de tout ce qui est peint (voisinage 4).
export function contour(t, c = "k", sauf = []) {
  const h = t.length;
  const w = t[0].length;
  const plein = (x, y) => x >= 0 && y >= 0 && x < w && y < h && t[y][x] !== "." && !sauf.includes(t[y][x]);
  const a = [];
  for (let y = 0; y < h; y++)
    for (let x = 0; x < w; x++)
      if (t[y][x] === "." && (plein(x - 1, y) || plein(x + 1, y) || plein(x, y - 1) || plein(x, y + 1))) a.push([x, y]);
  for (const [x, y] of a) t[y][x] = c;
  return t;
}

export function miroir(image) {
  return image.map((l) => [...l].reverse().join(""));
}

export function recolorer(image, table) {
  return image.map((l) => [...l].map((c) => table[c] ?? c).join(""));
}

// Grise et hache une image : « état non mesuré ».
export function hachurer(image, clair = "i", fonce = "I") {
  return image.map((l, y) =>
    [...l].map((c, x) => (c === "." ? "." : c === "k" ? fonce : (x + y) % 3 === 0 ? fonce : clair)).join(""),
  );
}

export function decaler(image, dx, dy) {
  const h = image.length;
  const w = image[0].length;
  const t = toile(w, h);
  coller(t, image, dx, dy);
  return figer(t);
}

// Agrandit une image à une largeur/hauteur données (le motif reste en haut à gauche + décalage).
export function cadrer(image, w, h, dx = 0, dy = 0) {
  const t = toile(w, h);
  coller(t, image, dx, dy);
  return figer(t);
}

export function sprite(frames, { fps = 0, boucle = true, pivot } = {}) {
  const h = frames[0].length;
  const w = frames[0][0].length;
  return { w, h, fps, boucle, pivot: pivot ?? [Math.floor(w / 2), h - 1], frames };
}
