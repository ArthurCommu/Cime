// Encodeur PNG minimal, Node pur (node:zlib), sans dépendance.
// RGBA 8 bits par canal, sans entrelacement, filtre 0 sur chaque ligne.

import { deflateSync } from "node:zlib";
import { writeFileSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";

const SIGNATURE = Uint8Array.of(0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a);

const TABLE_CRC = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

function crc32(octets) {
  let c = 0xffffffff;
  for (let i = 0; i < octets.length; i++) c = TABLE_CRC[(c ^ octets[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function bloc(type, donnees) {
  const sortie = new Uint8Array(12 + donnees.length);
  const vue = new DataView(sortie.buffer);
  vue.setUint32(0, donnees.length);
  for (let i = 0; i < 4; i++) sortie[4 + i] = type.charCodeAt(i);
  sortie.set(donnees, 8);
  vue.setUint32(8 + donnees.length, crc32(sortie.subarray(4, 8 + donnees.length)));
  return sortie;
}

export function encoderPNG(largeur, hauteur, rgba) {
  if (!Number.isInteger(largeur) || !Number.isInteger(hauteur) || largeur <= 0 || hauteur <= 0) {
    throw new Error(`dimensions invalides : ${largeur}×${hauteur}`);
  }
  if (rgba.length !== largeur * hauteur * 4) {
    throw new Error(`rgba : ${rgba.length} octets, ${largeur * hauteur * 4} attendus`);
  }
  const ihdr = new Uint8Array(13);
  const v = new DataView(ihdr.buffer);
  v.setUint32(0, largeur);
  v.setUint32(4, hauteur);
  ihdr[8] = 8; // profondeur
  ihdr[9] = 6; // RGBA
  // compression, filtre, entrelacement : 0

  const ligne = largeur * 4;
  const brut = new Uint8Array((ligne + 1) * hauteur);
  for (let y = 0; y < hauteur; y++) {
    brut[y * (ligne + 1)] = 0;
    brut.set(rgba.subarray(y * ligne, (y + 1) * ligne), y * (ligne + 1) + 1);
  }
  const idat = new Uint8Array(deflateSync(brut, { level: 9 }));

  const morceaux = [SIGNATURE, bloc("IHDR", ihdr), bloc("IDAT", idat), bloc("IEND", new Uint8Array(0))];
  const total = morceaux.reduce((s, m) => s + m.length, 0);
  const png = new Uint8Array(total);
  let pos = 0;
  for (const m of morceaux) {
    png.set(m, pos);
    pos += m.length;
  }
  return png;
}

export function ecrirePNG(chemin, largeur, hauteur, rgba) {
  mkdirSync(dirname(chemin), { recursive: true });
  writeFileSync(chemin, encoderPNG(largeur, hauteur, rgba));
}
