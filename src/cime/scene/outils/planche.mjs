// Planche de contact : dessine tout le catalogue dans un PNG.
//
//   node src/cime/scene/outils/planche.mjs <sortie.png> [--echelle 4] [--filtre perso.worker,ecran] [--sans-postes]
//
// 1. chaque sprite, toutes ses images côte à côte, étiqueté avec la police bitmap ;
// 2. une rangée « à ×1 » (première image de chaque sprite, taille réelle) ;
// 3. des postes composés (bureau + écran + perso, MONTAGE) pour juger l'ensemble.

import { ATLAS, MONTAGE } from "../static/graphismes/atlas.js";
import { CATALOGUE } from "../static/graphismes/catalogue.js";
import { PALETTE } from "../static/graphismes/palette.js";
import { ecrirePNG } from "./png.mjs";

const args = process.argv.slice(2);
const sortie = args.find((a, i) => !a.startsWith("--") && !args[i - 1]?.startsWith("--"));
const option = (nom, defaut) => {
  const i = args.indexOf(nom);
  return i >= 0 ? args[i + 1] : defaut;
};
if (!sortie) {
  console.error("usage : planche.mjs <sortie.png> [--echelle 4] [--filtre préfixe,…] [--sans-postes]");
  process.exit(2);
}
const E = Number(option("--echelle", "4"));
const filtres = option("--filtre", "")
  .split(",")
  .filter(Boolean);
const avecPostes = !args.includes("--sans-postes");
const noms = CATALOGUE.filter((n) => !filtres.length || filtres.some((f) => n.startsWith(f)));

const LARGEUR = Number(option("--largeur", "1800"));
const FOND = [0x7a, 0x7e, 0x8c];
const FOND_SOL = [0xdd, 0xd0, 0xb3];
const ENCRE = [0xf4, 0xf1, 0xe6];
const MARGE = 12;

const rgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
const COULEURS = Object.fromEntries(Object.entries(PALETTE).map(([c, h]) => [c, h && rgb(h)]));

// ─── Mise en page en deux passes : on mesure, puis on dessine ───────────────
const ops = [];
let curX = MARGE;
let curY = MARGE;
let hauteurRangee = 0;

function place(w, h) {
  if (curX + w > LARGEUR - MARGE && curX > MARGE) {
    curX = MARGE;
    curY += hauteurRangee + MARGE;
    hauteurRangee = 0;
  }
  const p = [curX, curY];
  curX += w + MARGE;
  hauteurRangee = Math.max(hauteurRangee, h);
  return p;
}
function nouvelleRangee(espace = MARGE) {
  if (curX > MARGE) {
    curX = MARGE;
    curY += hauteurRangee + espace;
    hauteurRangee = 0;
  }
}

const largeurTexte = (s, e) => [...s].length * (ATLAS.police.w + ATLAS.police.espacement) * e;
const ET = 2; // échelle des étiquettes
const HT = (ATLAS.police.h + 3) * ET;

function titre(s) {
  nouvelleRangee(MARGE * 2);
  const [x, y] = place(largeurTexte(s, 3), (ATLAS.police.h + 3) * 3);
  ops.push(["texte", s, x, y, 3, ENCRE]);
  nouvelleRangee();
}

// 1. Le catalogue
titre(`CATALOGUE ×${E}`);
for (const nom of noms) {
  const s = ATLAS.sprites[nom];
  const wImgs = s.frames.length * (s.w * E + 4) - 4;
  const etiquette = s.frames.length > 1 ? `${nom} ${s.frames.length}i ${s.fps}fps${s.boucle ? "" : " 1x"}` : nom;
  const w = Math.max(wImgs, largeurTexte(etiquette, ET));
  const [x, y] = place(w, HT + s.h * E);
  ops.push(["texte", etiquette, x, y, ET, ENCRE]);
  s.frames.forEach((img, i) => ops.push(["image", img, x + i * (s.w * E + 4), y + HT, E, s]));
}

// 2. À ×1, sur fond neutre puis sur moquette
for (const [libelle, fond] of [["A x1, fond neutre", null], ["A x1, sur la moquette", FOND_SOL]]) {
  titre(libelle);
  const debut = curY;
  for (const nom of noms) {
    const s = ATLAS.sprites[nom];
    const [x, y] = place(s.w, s.h);
    ops.push(["image", s.frames[0], x, y, 1, s, fond]);
  }
  if (fond) ops.push(["fond", fond, 0, debut - 4, LARGEUR, curY + hauteurRangee - debut + 8]);
}

// 3. Postes composés
function poste(role, anim, f) {
  const couches = [];
  const ecran = MONTAGE.ecranPourAnim[anim] ?? "ecran.eteint";
  const perso = ATLAS.sprites[`perso.${role}.${anim}`];
  const ecr = ATLAS.sprites[ecran];
  couches.push([ATLAS.sprites["meuble.bureau"], 0, [0, 0]]);
  couches.push([ecr, f % ecr.frames.length, MONTAGE.ecran]);
  couches.push([perso, f % perso.frames.length, MONTAGE.perso]);
  if (anim === "attend_autorisation") couches.push([ATLAS.sprites["alerte.halo"], f % 4, MONTAGE.halo]);
  if (anim === "sieste" || anim === "dormir") couches.push([ATLAS.sprites["bulle.zzz"], f % 3, MONTAGE.bulle]);
  if (anim === "attend_reponse") couches.push([ATLAS.sprites["bulle.question"], 0, MONTAGE.bulle]);
  if (anim === "fin_tache") couches.push([ATLAS.sprites["bulle.coche"], 0, MONTAGE.bulle]);
  return couches;
}
if (avecPostes) {
  const EP = Math.max(2, E - 1);
  const anims = Object.keys(ATLAS.sprites)
    .filter((n) => n.startsWith("perso.worker."))
    .map((n) => n.slice("perso.worker.".length));
  const roles = ["assistant", "coordinateur", "worker"].filter(
    (r) => !filtres.length || filtres.some((f) => `perso.${r}`.startsWith(f) || f.startsWith(`perso.${r}`) || f === "poste"),
  );
  if (roles.length) titre(`POSTES ×${EP} (MONTAGE)`);
  const boite = ATLAS.sprites["alerte.halo"];
  for (const role of roles) {
    for (const anim of anims) {
      const n = Math.max(ATLAS.sprites[`perso.${role}.${anim}`].frames.length, 1);
      const nb = Math.min(n, 4);
      const w = Math.max(nb * (boite.w * EP + 4), largeurTexte(`${role}.${anim}`, ET));
      const [x, y] = place(w, HT + boite.h * EP);
      ops.push(["texte", `${role}.${anim}`, x, y, ET, ENCRE]);
      for (let f = 0; f < nb; f++) {
        const fr = n > 4 ? Math.round((f * (n - 1)) / 3) : f;
        const ox = x + f * (boite.w * EP + 4) + boite.pivot[0] * EP;
        const oy = y + HT + boite.pivot[1] * EP;
        ops.push(["fond", FOND_SOL, x + f * (boite.w * EP + 4), y + HT, boite.w * EP, boite.h * EP]);
        for (const [s, i, [dx, dy]] of poste(role, anim, fr)) {
          ops.push(["image", s.frames[i], ox + (dx - s.pivot[0]) * EP, oy + (dy - s.pivot[1]) * EP, EP, s]);
        }
      }
    }
  }
}

// Police complète
titre("POLICE");
const glyphes = Object.keys(ATLAS.police.glyphes).join("");
for (let i = 0; i < glyphes.length; i += 48) {
  const ligne = [...glyphes].slice(i, i + 48).join("");
  const [x, y] = place(largeurTexte(ligne, 3), (ATLAS.police.h + 2) * 3);
  ops.push(["texte", ligne, x, y, 3, ENCRE]);
  nouvelleRangee(4);
}
{
  const phrase = "Équipe scène : 3 agents, 12 % de contexte, coût 0,42 $ — « déjà vu » ? Œuvre, Ça, où, être.";
  const [x, y] = place(largeurTexte(phrase, 2), 20);
  ops.push(["texte", phrase, x, y, 2, ENCRE]);
  nouvelleRangee();
  const [x1, y1] = place(largeurTexte(phrase, 1), 10);
  ops.push(["texte", phrase, x1, y1, 1, ENCRE]);
}

const HAUTEUR = curY + hauteurRangee + MARGE;

// ─── Rendu ──────────────────────────────────────────────────────────────────
const rgba = new Uint8Array(LARGEUR * HAUTEUR * 4);
function point(x, y, [r, g, b]) {
  if (x < 0 || y < 0 || x >= LARGEUR || y >= HAUTEUR) return;
  const o = (y * LARGEUR + x) * 4;
  rgba[o] = r;
  rgba[o + 1] = g;
  rgba[o + 2] = b;
  rgba[o + 3] = 255;
}
function pave(x, y, w, h, c) {
  for (let j = y; j < y + h; j++) for (let i = x; i < x + w; i++) point(i, j, c);
}
pave(0, 0, LARGEUR, HAUTEUR, FOND);

for (const op of ops.filter((o) => o[0] === "fond")) pave(op[2], op[3], op[4], op[5], op[1]);
for (const op of ops) {
  if (op[0] === "image") {
    const [, img, x, y, e] = op;
    img.forEach((ligne, j) =>
      [...ligne].forEach((c, i) => {
        const col = COULEURS[c];
        if (col === undefined) throw new Error(`caractère hors palette : « ${c} »`);
        if (col) pave(x + i * e, y + j * e, e, e, col);
      }),
    );
  } else if (op[0] === "texte") {
    const [, s, x, y, e, col] = op;
    const { w, espacement, glyphes: G } = ATLAS.police;
    [...s].forEach((ch, k) => {
      const g = G[ch] ?? G["?"];
      g.forEach((l, j) =>
        [...l].forEach((p, i) => {
          if (p === "#") pave(x + (k * (w + espacement) + i) * e, y + j * e, e, e, col);
        }),
      );
    });
  }
}

ecrirePNG(sortie, LARGEUR, HAUTEUR, rgba);
console.log(`${sortie} : ${LARGEUR}×${HAUTEUR}, ${noms.length} sprites`);
