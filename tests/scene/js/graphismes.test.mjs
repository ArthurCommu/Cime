// Tests des graphismes de la scène : node --test tests/scene/js/graphismes.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { inflateSync } from "node:zlib";

const RACINE = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const G = join(RACINE, "src", "cime", "scene", "static", "graphismes");
const imp = (f) => import(pathToFileURL(join(G, f)).href);

const { PALETTE, ROUGES, AMBRES, GRIS, PREFIXES_ROUGES } = await imp("palette.js");
const { ATLAS, MONTAGE } = await imp("atlas.js");
const { CATALOGUE } = await imp("catalogue.js");
const { encoderPNG } = await import(pathToFileURL(join(RACINE, "src", "cime", "scene", "outils", "png.mjs")).href);

const S = ATLAS.sprites;
const ROLES = ["assistant", "coordinateur", "worker"];
const ANIMS = [
  "idle", "taper", "ecrire", "lire", "executer", "reflechir", "dormir", "sieste",
  "attend_autorisation", "attend_reponse", "arrete", "inconnu", "arrive", "fin_tache",
];

const caracteres = (sp) => new Set(sp.frames.flat().join(""));
const masque = (img) => img.map((l) => l.replace(/[^.]/g, "#")).join("\n");

function teinte(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const d = max - min;
  let h = 0;
  if (d) {
    if (max === r) h = 60 * (((g - b) / d) % 6);
    else if (max === g) h = 60 * ((b - r) / d + 2);
    else h = 60 * ((r - g) / d + 4);
  }
  return { h: (h + 360) % 360, s: max ? d / max : 0, v: max };
}
const seLitRouge = (hex) => {
  const { h, s, v } = teinte(hex);
  return (h >= 340 || h <= 18) && s >= 0.5 && v >= 0.3;
};

// ─── Catalogue ──────────────────────────────────────────────────────────────

test("le catalogue contient exactement les noms obligatoires", () => {
  const attendus = [
    ...ROLES.flatMap((r) => ANIMS.map((a) => `perso.${r}.${a}`)),
    "perso.utilisateur.idle", "perso.utilisateur.inconnu",
    ...["marche_haut", "marche_bas", "marche_gauche", "marche_droite", "idle", "dormir", "arrete"].map((a) => `perso.facteur.${a}`),
    "meuble.bureau", "meuble.bureau_vide", "meuble.chaise",
    "ecran.eteint", "ecran.texte", "ecran.lecture", "ecran.terminal", "ecran.pensee",
    "sol.piece", "sol.couloir", "mur.haut", "mur.cote", "mur.angle", "porte.piece",
    "porte.utilisateur.fermee", "porte.utilisateur.attente", "porte.utilisateur.agir",
    "plante", "panneau.equipe", "machine.cafe",
    "enveloppe.inscrit", "enveloppe.livre", "enveloppe.pris_en_compte", "enveloppe.clos", "enveloppe.echec", "enveloppe.abandonne", "enveloppe.echec_gris", "enveloppe.abandonne_gris",
    "bulle.exclamation", "bulle.question", "bulle.zzz", "bulle.pensee", "bulle.coche",
    "icone.cout", "icone.contexte", "jauge.cadre", "icone.inconnu",
    "alerte.halo", "alerte.refus_garde", "alerte.sirene", "alerte.cause_inconnue", "attente.halo", "attente.sirene",
    "compteur.dossiers",
  ];
  assert.deepEqual([...CATALOGUE].sort(), [...attendus].sort());
  assert.equal(new Set(CATALOGUE).size, CATALOGUE.length, "doublon dans le catalogue");
});

test("chaque nom du catalogue existe dans ATLAS.sprites", () => {
  const manquants = CATALOGUE.filter((n) => !(n in S));
  assert.deepEqual(manquants, []);
});

test("l'atlas est de la donnée pure (sérialisable sans perte)", () => {
  assert.deepEqual(JSON.parse(JSON.stringify(ATLAS)), ATLAS);
  assert.equal(ATLAS.tuile, 16);
});

// ─── Formats ────────────────────────────────────────────────────────────────

test("format de chaque sprite : tailles, images, cadence, pivot", () => {
  for (const [nom, sp] of Object.entries(S)) {
    const { w, h, fps, boucle, pivot, frames } = sp;
    assert.ok(Number.isInteger(w) && w > 0 && Number.isInteger(h) && h > 0, `${nom} : w/h`);
    assert.ok(Array.isArray(frames) && frames.length >= 1, `${nom} : frames`);
    frames.forEach((img, i) => {
      assert.equal(img.length, h, `${nom}[${i}] : ${img.length} lignes au lieu de ${h}`);
      img.forEach((l, j) => {
        assert.equal(typeof l, "string");
        assert.equal([...l].length, w, `${nom}[${i}] ligne ${j} : largeur ${[...l].length} au lieu de ${w}`);
        for (const c of l) assert.ok(c in PALETTE, `${nom}[${i}] : caractère hors palette « ${c} »`);
      });
      assert.ok(img.some((l) => /[^.]/.test(l)), `${nom}[${i}] : image vide`);
    });
    assert.equal(typeof boucle, "boolean", `${nom} : boucle`);
    assert.ok(typeof fps === "number" && fps >= 0, `${nom} : fps`);
    if (frames.length > 1) assert.ok(fps > 0, `${nom} : ${frames.length} images mais fps = 0`);
    assert.ok(Array.isArray(pivot) && pivot.length === 2 && pivot.every(Number.isInteger), `${nom} : pivot`);
    assert.ok(pivot[0] >= 0 && pivot[0] < w && pivot[1] >= 0 && pivot[1] < h, `${nom} : pivot ${pivot} hors de ${w}×${h}`);
    if (sp.zone) {
      const [x, y, zw, zh] = sp.zone;
      assert.ok(x >= 0 && y >= 0 && x + zw <= w && y + zh <= h, `${nom} : zone hors du sprite`);
    }
  }
});

test("animations à jouer une fois et nombres d'images imposés", () => {
  for (const r of ROLES) {
    const arrive = S[`perso.${r}.arrive`];
    assert.equal(arrive.boucle, false);
    assert.ok(arrive.frames.length >= 6 && arrive.frames.length <= 8, `${r}.arrive : 6 à 8 images`);
    assert.equal(S[`perso.${r}.fin_tache`].boucle, false);
  }
  for (const d of ["haut", "bas", "gauche", "droite"]) assert.equal(S[`perso.facteur.marche_${d}`].frames.length, 4);
  assert.equal(S["enveloppe.pris_en_compte"].frames.length, 4);
  assert.equal(S["enveloppe.pris_en_compte"].boucle, false);
  assert.equal(S["enveloppe.clos"].frames.length, 3);
  assert.equal(S["bulle.zzz"].frames.length, 3);
  assert.equal(S["alerte.halo"].frames.length, 4);
  assert.equal(S["machine.cafe"].frames.length, 2);
});

test("cohérence des tailles : agents calés pareil, écrans pareils, tuiles 16×16", () => {
  for (const r of ROLES) {
    const ref = S[`perso.${r}.idle`];
    for (const a of ANIMS.filter((a) => a !== "arrive")) {
      const sp = S[`perso.${r}.${a}`];
      assert.deepEqual([sp.w, sp.h, sp.pivot], [ref.w, ref.h, ref.pivot], `${r}.${a} n'est pas calé comme ${r}.idle`);
    }
    // l'arrivée finit assise exactement à la place de idle
    const arrive = S[`perso.${r}.arrive`];
    assert.equal(arrive.pivot[1], ref.pivot[1]);
  }
  const ecrans = CATALOGUE.filter((n) => n.startsWith("ecran."));
  for (const n of ecrans) assert.deepEqual([S[n].w, S[n].h, S[n].pivot], [S["ecran.eteint"].w, S["ecran.eteint"].h, S["ecran.eteint"].pivot]);
  for (const n of ["sol.piece", "sol.couloir", "mur.haut", "mur.cote", "mur.angle", "porte.piece"]) {
    assert.deepEqual([S[n].w, S[n].h], [ATLAS.tuile, ATLAS.tuile], n);
  }
  for (const d of ["haut", "bas", "gauche", "droite"]) {
    assert.deepEqual([S[`perso.facteur.marche_${d}`].w, S[`perso.facteur.marche_${d}`].h], [S["perso.facteur.idle"].w, S["perso.facteur.idle"].h]);
  }
  assert.deepEqual(S["meuble.bureau"].pivot, S["meuble.bureau_vide"].pivot);
  assert.deepEqual(S["meuble.chaise"].pivot, S["perso.worker.idle"].pivot);
  for (const k of ["ecran", "perso", "bulle", "halo"]) assert.equal(MONTAGE[k].length, 2);
});

// ─── Palette et rouge réservé ───────────────────────────────────────────────

test("palette : 16 à 32 couleurs #rrggbb, « . » transparent", () => {
  assert.equal(PALETTE["."], null);
  const couleurs = Object.entries(PALETTE).filter(([c]) => c !== ".");
  assert.ok(couleurs.length >= 16 && couleurs.length <= 32, `${couleurs.length} couleurs`);
  for (const [c, hex] of couleurs) {
    assert.equal([...c].length, 1);
    assert.match(hex, /^#[0-9a-f]{6}$/, c);
  }
  assert.equal(new Set(couleurs.map(([, h]) => h)).size, couleurs.length, "deux caractères pour une même couleur");
  for (const c of [...ROUGES, ...AMBRES, ...GRIS]) assert.ok(PALETTE[c], `${c} absent de la palette`);
});

test("les ROUGES se lisent rouge, et aucune autre couleur ne se lit rouge", () => {
  for (const c of ROUGES) assert.ok(seLitRouge(PALETTE[c]), `${c} = ${PALETTE[c]} ne se lit pas rouge`);
  for (const [c, hex] of Object.entries(PALETTE)) {
    if (!hex || ROUGES.includes(c)) continue;
    assert.ok(!seLitRouge(hex), `${c} = ${hex} se lit rouge mais n'est pas dans ROUGES`);
  }
  // l'ambre reste franchement jaune-orangé
  for (const c of AMBRES) assert.ok(teinte(PALETTE[c]).h >= 35 && teinte(PALETTE[c]).h <= 60, `${c} : ambre trop rouge`);
  // les gris « inconnu » n'ont pas de teinte
  for (const c of GRIS) assert.ok(teinte(PALETTE[c]).s < 0.05, `${c} : gris teinté`);
});

test("le rouge n'apparaît que dans les sprites d'alerte", () => {
  const fautifs = [];
  for (const [nom, sp] of Object.entries(S)) {
    if (PREFIXES_ROUGES.some((p) => nom.startsWith(p))) continue;
    const rouges = [...caracteres(sp)].filter((c) => ROUGES.includes(c));
    if (rouges.length) fautifs.push(`${nom} (${rouges.join("")})`);
  }
  assert.deepEqual(fautifs, []);
});

test("les sprites d'alerte sont bien rouges", () => {
  const doivent = CATALOGUE.filter((n) => PREFIXES_ROUGES.some((p) => n.startsWith(p)) && !n.endsWith("_gris"));
  assert.ok(doivent.length >= 7);
  for (const n of doivent) {
    for (const [i, img] of S[n].frames.entries()) {
      assert.ok(ROUGES.some((c) => img.join("").includes(c)), `${n}[${i}] sans rouge`);
    }
  }
  // et les états neutres voisins ne le sont pas
  // une attente est ambre : la porte à agir, la bulle « ! », les halos et la sirène ambre, les enveloppes grises n'ont aucun rouge
  for (const n of ["porte.utilisateur.attente", "porte.utilisateur.fermee", "porte.utilisateur.agir", "bulle.question", "bulle.exclamation", "enveloppe.inscrit", "enveloppe.echec_gris", "enveloppe.abandonne_gris", "attente.halo", "attente.sirene", "perso.facteur.idle"]) {
    assert.ok(!ROUGES.some((c) => caracteres(S[n]).has(c)), n);
  }
});

// ─── Lisibilité (ce qui se mécanise) ────────────────────────────────────────

test("les trois rôles se distinguent par la couleur et la silhouette", () => {
  const vetement = { assistant: "t", coordinateur: "v", worker: "u" };
  for (const r of ROLES) {
    const cs = caracteres(S[`perso.${r}.idle`]);
    assert.ok(cs.has(vetement[r]), `${r} sans sa couleur`);
    for (const autre of ROLES.filter((x) => x !== r)) assert.ok(!cs.has(vetement[autre]), `${r} porte la couleur de ${autre}`);
  }
  const silhouettes = ROLES.map((r) => masque(S[`perso.${r}.idle`].frames[0]));
  assert.equal(new Set(silhouettes).size, 3, "deux rôles ont la même silhouette");
});

test("activités, repos et états se distinguent par la silhouette", () => {
  for (const r of ROLES) {
    for (const groupe of [
      ["ecrire", "lire", "executer", "reflechir"],
      ["dormir", "sieste", "arrete", "inconnu"],
      ["idle", "taper", "attend_autorisation", "attend_reponse"],
    ]) {
      const masques = groupe.map((a) => masque(S[`perso.${r}.${a}`].frames[0]));
      assert.equal(new Set(masques).size, groupe.length, `${r} : ${groupe.join("/")} se confondent`);
    }
  }
});

test("arrêté = chaise vide ; inconnu = gris seulement", () => {
  for (const r of ROLES) {
    const vide = caracteres(S[`perso.${r}.arrete`]);
    for (const c of ["s", "t", "v", "u"]) assert.ok(!vide.has(c), `${r}.arrete : un personnage est encore là`);
    const inconnu = [...caracteres(S[`perso.${r}.inconnu`])].filter((c) => c !== ".");
    assert.deepEqual([...new Set(inconnu)].sort(), [...GRIS].sort(), `${r}.inconnu`);
  }
  assert.ok([...caracteres(S["perso.utilisateur.inconnu"])].every((c) => c === "." || GRIS.includes(c)));
  assert.ok([...caracteres(S["icone.inconnu"])].every((c) => c === "." || GRIS.includes(c)));
});

test("le panneau et la jauge laissent une zone à remplir", () => {
  const [, , zw, zh] = S["panneau.equipe"].zone;
  assert.ok(zh >= ATLAS.police.h, "le texte ne tient pas dans le panneau");
  assert.ok(zw >= 10 * (ATLAS.police.w + ATLAS.police.espacement), "panneau trop étroit pour 10 caractères");
  const [x, y, w, h] = S["jauge.cadre"].zone;
  const img = S["jauge.cadre"].frames[0];
  for (let j = y; j < y + h; j++) assert.equal(img[j].slice(x, x + w), ".".repeat(w), "l'intérieur de la jauge doit être transparent");
});

// ─── Police ─────────────────────────────────────────────────────────────────

test("police : 5×7, complète, accents du français compris", () => {
  const P = ATLAS.police;
  assert.equal(P.w, 5);
  assert.equal(P.h, 7);
  const requis = [
    ..."0123456789",
    ..."ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    ..."abcdefghijklmnopqrstuvwxyz",
    " ",
    ...".,:;!?-_/()%+#'\"$",
    ..."éèêëàâäôöîïûùüÿçœ",
    ..."ÉÈÊËÀÂÄÔÖÎÏÛÙÜŸÇŒ",
  ];
  const manquants = requis.filter((c) => !(c in P.glyphes));
  assert.deepEqual(manquants, []);
  for (const [c, g] of Object.entries(P.glyphes)) {
    assert.equal(g.length, P.h, `« ${c} » : ${g.length} lignes`);
    for (const l of g) assert.match(l, /^[#.]{5}$/, `« ${c} »`);
    if (c !== " ") assert.ok(g.some((l) => l.includes("#")), `« ${c} » est vide`);
  }
  // un accent se voit
  const pairs = { é: "e", è: "e", ê: "e", à: "a", ç: "c", ù: "u", É: "E", À: "A", Ç: "C", ô: "o", î: "i", ï: "i" };
  for (const [a, b] of Object.entries(pairs)) assert.notDeepEqual(P.glyphes[a], P.glyphes[b], `${a} = ${b}`);
  // deux lettres ou chiffres différents ne se dessinent jamais pareil
  // (seule tolérance : Ô/ô et Ö/ö, même lettre, qui ne tiennent pas en 5×7)
  const vus = new Map();
  for (const c of [...requis].filter((c) => /[\p{L}\p{N}]/u.test(c))) {
    const k = P.glyphes[c].join("");
    const autre = vus.get(k);
    assert.ok(!autre || autre.toLowerCase() === c.toLowerCase(), `« ${c} » et « ${autre} » sont identiques`);
    vus.set(k, c);
  }
});

// ─── Outils ─────────────────────────────────────────────────────────────────

test("encoderPNG produit un PNG valide", () => {
  const rgba = new Uint8Array(3 * 2 * 4).map((_, i) => (i * 37) % 256);
  const png = encoderPNG(3, 2, rgba);
  assert.deepEqual([...png.slice(0, 8)], [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  const v = new DataView(png.buffer, png.byteOffset);
  assert.equal(String.fromCharCode(...png.slice(12, 16)), "IHDR");
  assert.equal(v.getUint32(16), 3);
  assert.equal(v.getUint32(20), 2);
  const longueur = v.getUint32(33);
  assert.equal(String.fromCharCode(...png.slice(37, 41)), "IDAT");
  const brut = inflateSync(png.slice(41, 41 + longueur));
  assert.equal(brut.length, 2 * (1 + 3 * 4));
  assert.deepEqual([...brut.slice(1, 13)], [...rgba.slice(0, 12)]);
  assert.throws(() => encoderPNG(2, 2, new Uint8Array(3)));
});

test("la planche de contact se génère", () => {
  const sortie = join(mkdtempSync(join(tmpdir(), "planche-")), "p.png");
  execFileSync(process.execPath, [join(RACINE, "src", "cime", "scene", "outils", "planche.mjs"), sortie, "--echelle", "2"], {
    stdio: "pipe",
  });
  const png = readFileSync(sortie);
  assert.equal(png.slice(1, 4).toString(), "PNG");
});
