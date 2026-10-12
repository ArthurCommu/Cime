// Test croisé : tout nom de sprite que le scénario d’essai peut référencer existe dans l’atlas.
// Contre l’atlas factice, puis contre l’atlas des graphismes.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { join, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { readFileSync } from 'node:fs';
import { NOMS_SPRITES } from '../../../src/cime/scene/static/animations.js';
import { creerSourceRejouee } from './support/source-rejouee.mjs';
import { creerFil, appliquerSnapshot, sceneA } from '../../../src/cime/scene/static/modele.js';
import { dessiner } from '../../../src/cime/scene/static/rendu.js';
import { SurfacePNG } from '../../../src/cime/scene/static/surface-png.mjs';
import { DUREE_MS, PAS } from './support/scenario.mjs';
import { NOMS_FACTICE } from './atlas-factice.mjs';

const ICI = dirname(fileURLToPath(import.meta.url));
const STATIC = join(ICI, '..', '..', '..', 'src', 'cime', 'scene', 'static');
const ATLAS_REEL = join(STATIC, 'graphismes', 'atlas.js');
const PALETTE_REELLE = join(STATIC, 'graphismes', 'palette.js');

test('tout nom référencé par le scénario d’essai existe dans l’atlas factice', () => {
  const manquent = NOMS_SPRITES.filter((n) => !NOMS_FACTICE.includes(n));
  assert.deepEqual(manquent, []);
});

test('tout nom référencé par le scénario d’essai existe dans l’atlas réel des graphismes', () => {
  return import(pathToFileURL(ATLAS_REEL).href).then(({ ATLAS }) => {
    const manquent = NOMS_SPRITES.filter((n) => !ATLAS.sprites[n]);
    assert.deepEqual(manquent, [], 'sprites référencés et absents de l’atlas réel');
  });
});

test('scénario complet avec l’atlas réel : scene.manques == 0 à chaque image', async () => {
  const { ATLAS } = await import(pathToFileURL(ATLAS_REEL).href);
  const { PALETTE } = await import(pathToFileURL(PALETTE_REELLE).href);
  const etatInitial = JSON.parse(readFileSync(join(ICI, '..', 'fixtures', 'etat-exemple.json'), 'utf8'));
  const source = creerSourceRejouee({ etatInitial, duree: DUREE_MS, pas: PAS });
  const fil = creerFil();
  source.abonner((etat, trs, tStep, { reset }) => appliquerSnapshot(fil, etat, trs, tStep, { reset }));
  let manques = 0;
  for (let tm = 0; tm < DUREE_MS; tm += 250) {
    source.avancerA(tm);
    const scene = sceneA(fil, tm);
    const surface = new SurfacePNG(scene.largeur, scene.hauteur, ATLAS, PALETTE);
    manques = Math.max(manques, dessiner(surface, ATLAS, scene, tm));
  }
  assert.equal(manques, 0);
});
