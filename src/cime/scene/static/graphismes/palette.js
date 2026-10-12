// Palette unique de la scène : un caractère → une couleur.
// « . » est réservé au transparent. Éclairage haut-gauche partout.
//
// Règle d'or : le rouge (ROUGES) ne dit qu'une chose, « problème ».
// Aucune autre couleur ne doit pouvoir se lire rouge : l'ambre reste
// franchement jaune-orangé, la peau et le bois restent bruns.

export const PALETTE = {
  ".": null,

  // Encres et gris bleutés (contours, murs, métal)
  k: "#1a1c2c", // contour
  K: "#2b2f45", // ombre profonde
  g: "#3e4560", // ardoise
  G: "#5d6582", // ardoise claire
  h: "#8b93ad", // gris-bleu
  H: "#c2c7d6", // gris clair
  w: "#f4f1e6", // blanc cassé

  // Peau
  s: "#f2c9a2",
  S: "#c99470",

  // Bois (et cheveux bruns / blonds)
  b: "#5e3f2c", // bois sombre, cheveux bruns
  B: "#93683f", // bois
  d: "#c89a62", // bois clair, cheveux blonds

  // Sol des pièces (moquette)
  f: "#ddd0b3",
  F: "#c6b694",

  // Vêtements des rôles
  t: "#2fa58e", // assistant
  T: "#1d6e62",
  v: "#8a63c4", // coordinateur
  V: "#5b3f8c",
  u: "#4a86d6", // worker
  U: "#2c5b9e",

  // Ambres (« à voir ») et lumière
  y: "#eabb32",
  Y: "#c48c1c",
  l: "#fbe9a6",

  // Verts (plantes, terminal, coche)
  e: "#6cb35a",
  E: "#3d7d3f",

  // Écrans
  z: "#263a5c", // fond d'éditeur
  q: "#8fd6ec", // lueur d'écran

  // Rouges : réservés aux problèmes
  R: "#e0403a",
  r: "#8e2230",

  // Gris neutres : « inconnu / non mesuré »
  i: "#a3a3a3",
  I: "#6c6c6c",
};

// Tout ce qui se lit rouge / alerte.
export const ROUGES = ["R", "r"];
// Teintes « à voir ». (« l » est une lumière neutre : reflets, lampe sous la porte.)
export const AMBRES = ["y", "Y"];
// « Inconnu / non mesuré » (gris neutres, sans teinte).
export const GRIS = ["i", "I"];

// Préfixes de sprites autorisés à contenir du rouge (et eux seuls).
export const PREFIXES_ROUGES = [
  "alerte.",
  "enveloppe.echec",
  "enveloppe.abandonne",
  "perso.facteur.arrete",
];
