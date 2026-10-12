// La légende : dérivée des données (LEGENDE + ATLAS), complète, dans le cadre, rouge seulement pour les problèmes.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { ATLAS } from '../../../src/cime/scene/static/graphismes/atlas.js';
import { creerSourceRejouee } from './support/source-rejouee.mjs';
import { creerFil, appliquerSnapshot, sceneA } from '../../../src/cime/scene/static/modele.js';
import { dessiner, COULEURS } from '../../../src/cime/scene/static/rendu.js';
import { DUREE_MS } from './support/scenario.mjs';
import { NOMS_SPRITES } from '../../../src/cime/scene/static/animations.js';
import { LEGENDE, GROUPES, DECOR, NON_DESSINES, cleSigne, composer, lignes, spritesDe, disposerLegende } from '../../../src/cime/scene/static/legende.js';

const ICI = dirname(fileURLToPath(import.meta.url));
const FIXTURE = join(ICI, '..', 'fixtures', 'etat-exemple.json');

class Espion {
  constructor(l, h) { this.largeur = l; this.hauteur = h; this.boites = []; }
  taille() { return { w: this.largeur, h: this.hauteur }; }
  rect(x, y, w, h, couleur) { this.boites.push({ genre: 'rect', x, y, w, h, couleur }); }
  sprite(nom, frame, x, y) { const s = ATLAS.sprites[nom]; this.boites.push({ genre: 'sprite', nom, x, y, w: s.w, h: s.h }); }
  texte(chaine, x, y, couleur) { this.boites.push({ genre: 'texte', chaine, x, y, w: chaine.length * 6, h: 7, couleur }); }
}

// Rejoue le scénario d’essai ; rend (sans pixels) la scène toutes les 500 ms et à chaque étape.
function rejouer(pas = 500) {
  const source = creerSourceRejouee({ etatInitial: JSON.parse(readFileSync(FIXTURE, 'utf8')) });
  const fil = creerFil();
  source.abonner((etat, trs, t, { reset }) => appliquerSnapshot(fil, etat, trs, t, { reset }));
  const vues = [];
  for (let t = 0; t < DUREE_MS; t += pas) {
    source.avancerA(t);
    const scene = sceneA(fil, t);
    const e = new Espion(scene.largeur, scene.hauteur);
    dessiner(e, ATLAS, scene, t);
    vues.push({ t, scene, boites: e.boites });
  }
  return vues;
}

const dansLegende = (b, scene) => b.y >= scene.hauteurEtage;
const spritesLegende = () => {
  const noms = new Set();
  for (const e of LEGENDE) {
    for (const n of spritesDe(e)) noms.add(cleSigne(n));
  }
  return noms;
};

test('chaque sprite de signe que la scène dessine figure dans la légende (ou est du décor)', () => {
  const connus = new Set([...spritesLegende(), ...DECOR.map(cleSigne)]);
  const dessines = new Set();
  for (const { scene, boites } of rejouer()) {
    for (const b of boites) if (b.genre === 'sprite' && !dansLegende(b, scene)) dessines.add(cleSigne(b.nom));
  }
  const manquants = [...dessines].filter((n) => !connus.has(n));
  assert.deepEqual(manquants, [], `dessinés par la scène mais absents de la légende : ${manquants}`);
  for (const n of NON_DESSINES) assert.equal(dessines.has(cleSigne(n)), false, `${n} est dessiné : à mettre dans LEGENDE ou DECOR`);
});

test('chaque nom de sprite de animations.js est dans la légende, le décor ou la liste des non dessinés', () => {
  const connus = new Set([...spritesLegende(), ...DECOR.map(cleSigne), ...NON_DESSINES.map(cleSigne)]);
  const manquants = NOMS_SPRITES.filter((n) => !connus.has(cleSigne(n)));
  assert.deepEqual(manquants, []);
});

test('chaque entrée de la légende existe dans l’atlas, a un libellé en glyphes connus, et un groupe titré', () => {
  for (const e of LEGENDE) {
    assert.ok(e.sprite || e.motif, 'entrée sans signe');
    for (const nom of [e.sprite, ...(e.avec ?? []).map((o) => o.sprite)].filter(Boolean)) assert.ok(ATLAS.sprites[nom], `sprite absent : ${nom}`);
    assert.ok(GROUPES[e.groupe], `groupe inconnu : ${e.groupe}`);
    for (const l of lignes(e)) for (const ch of l) assert.ok(ATLAS.police.glyphes[ch], `glyphe absent « ${ch} » dans « ${l} »`);
    assert.ok(lignes(e).length <= 2);
  }
});

test('la légende compte dans la taille de l’étage et ne sort pas du cadre', () => {
  const { scene } = rejouer(30000)[0];
  console.log(`étage + légende : ${scene.largeur}×${scene.hauteur} px logiques (étage ${scene.largeur}×${scene.hauteurEtage}, légende ${scene.legende.h})`);
  assert.equal(scene.hauteur, scene.hauteurEtage + scene.legende.h);
  assert.equal(scene.legende.y, scene.hauteurEtage);
  for (const c of scene.legende.cellules) {
    assert.ok(c.x >= 0 && c.x + c.w <= scene.largeur, `cellule hors de la largeur : ${c.libelle[0].texte}`);
    assert.ok(c.y >= scene.hauteurEtage && c.y + c.h <= scene.hauteur, `cellule hors de la bande : ${c.libelle[0].texte}`);
    assert.ok(c.signe.x >= c.x && c.signe.x + c.signe.w <= c.x + c.w);
  }
  for (const [i, a] of scene.legende.cellules.entries()) {
    for (const b of scene.legende.cellules.slice(i + 1)) {
      const separes = a.x + a.w <= b.x || b.x + b.w <= a.x || a.y + a.h <= b.y || b.y + b.h <= a.y;
      assert.ok(separes, `cellules qui se recouvrent : ${a.libelle[0].texte} / ${b.libelle[0].texte}`);
    }
  }
});

test('le rouge de la légende est réservé aux signes de problème', () => {
  const rougeSprite = (nom) => ATLAS.sprites[nom].frames.some((f) => f.some((l) => /[Rr]/.test(l)));
  for (const e of LEGENDE) {
    const noms = [e.sprite, ...(e.avec ?? []).map((o) => o.sprite)].filter(Boolean);
    const rouge = noms.some(rougeSprite) || e.motif === 'bordure.rouge';
    if (e.sprite === 'alerte.halo') continue; // le halo est rouge ; le poste dessiné dedans ne l'est pas
    assert.equal(!!e.probleme, rouge, `${e.sprite ?? e.motif} : drapeau « probleme » ≠ présence de rouge`);
  }
  const halo = LEGENDE.find((e) => e.sprite === 'alerte.halo');
  assert.ok(halo.probleme);
  // côté dessin : tout aplat rouge de la bande est dans le signe d'une entrée « probleme », et le texte n'est jamais rouge
  const { scene, boites } = rejouer(30000)[0];
  const cellulesRouges = scene.legende.cellules.filter((c) => c.entree.probleme);
  for (const b of boites.filter((q) => dansLegende(q, scene))) {
    if (b.genre === 'texte') assert.notEqual(b.couleur, COULEURS.rouge, `texte rouge : ${b.chaine}`);
    if (b.genre === 'rect' && b.couleur === COULEURS.rouge) {
      assert.ok(cellulesRouges.some((c) => b.x >= c.signe.x && b.x + b.w <= c.signe.x + c.signe.w && b.y >= c.signe.y && b.y + b.h <= c.signe.y + c.signe.h), 'aplat rouge hors d’un signe de problème');
    }
  }
});

// La légende suit la largeur de l'étage, et elle seule : un worker qui se replie (ou se rouvre) change la largeur de
// l'étage (624 ↔ 656 px sur l’état d’exemple), donc la mise en page de la légende. Elle n'est donc pas la même à tout
// instant : c'est la mise en page de la largeur courante.
test('la légende est la mise en page de la largeur de l’étage, à chaque instant', () => {
  const vues = rejouer(30000);
  for (const { scene } of vues) {
    const attendu = disposerLegende(scene.largeur, scene.hauteurEtage).cellules.map((c) => [c.x, c.y]);
    assert.deepEqual(scene.legende.cellules.map((c) => [c.x, c.y]), attendu);
  }
});

test('composer : un signe avec bulle englobe la bulle', () => {
  const c = composer(LEGENDE.find((e) => e.avec?.some((o) => o.sprite === 'bulle.question')));
  assert.ok(c.h > ATLAS.sprites['perso.worker.attend_reponse'].h);
});

test('la place du « ? » de cause inconnue ne coûte aucun nom abrégé : toute pièce garde la place de son nom entier (12 lettres)', () => {
  const { scene } = rejouer(30000)[0];
  for (const p of scene.pieces.filter((q) => !q.neutre)) {
    assert.ok(p.nomZone.w >= p.nom.length * 6 - 1, `« ${p.nom} » abrégé : zone ${p.nomZone.w}`);
    const s = ATLAS.sprites['alerte.cause_inconnue'];
    assert.ok(p.causeAncre.x >= p.nomZone.x + p.nomZone.w, 'le « ? » ne recouvre pas le nom');
    assert.ok(p.causeAncre.x + s.w <= p.sireneAncre.x - ATLAS.sprites['alerte.sirene'].pivot[0], 'le « ? » ne recouvre pas la sirène');
  }
});
