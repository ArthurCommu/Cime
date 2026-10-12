// Performance : construireScene + dessiner (surface PNG) avec 20 agents, moyenne sur 200 images. Seuil large (8 ms).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { construireScene, creerFil, appliquerSnapshot, sceneA } from '../../../src/cime/scene/static/modele.js';
import { dessiner } from '../../../src/cime/scene/static/rendu.js';
import { SurfacePNG } from '../../../src/cime/scene/static/surface-png.mjs';
import { ATLAS_FACTICE, PALETTE_FACTICE } from './atlas-factice.mjs';

const ICI = dirname(fileURLToPath(import.meta.url));
const FIXTURE = join(ICI, '..', 'fixtures', 'etat-exemple.json');

function vingtAgents() {
  const etat = JSON.parse(readFileSync(FIXTURE, 'utf8'));
  const modeles = etat.agents.filter((a) => a.role === 'worker' && a.equipe === 'page');
  for (let i = 0; etat.agents.filter((a) => a.role !== 'utilisateur').length < 20; i++) {
    const copie = structuredClone(modeles[i % modeles.length]);
    copie.id = `worker-page-essai-${i}`;
    copie.session_tmux = `cc-${copie.id}`;
    etat.agents.push(copie);
  }
  return etat;
}

test('20 agents : construireScene + dessiner en moyenne sous 8 ms (200 images)', () => {
  const etat = vingtAgents();
  assert.equal(etat.agents.filter((a) => a.role !== 'utilisateur').length, 20);
  const fil = creerFil();
  appliquerSnapshot(fil, etat, [], 0);
  const images = 200;
  const debut = performance.now();
  for (let i = 0; i < images; i++) {
    const t = i * 16;
    const scene = sceneA(fil, t);
    const surface = new SurfacePNG(scene.largeur, scene.hauteur, ATLAS_FACTICE, PALETTE_FACTICE);
    dessiner(surface, ATLAS_FACTICE, scene, t);
  }
  const moyenne = (performance.now() - debut) / images;
  console.log(`performance : ${moyenne.toFixed(2)} ms par image (20 agents, surface PNG, ${images} images)`);
  assert.ok(moyenne < 8, `moyenne ${moyenne.toFixed(2)} ms`);
});

test('construireScene seul, 20 agents : mesure imprimée', () => {
  const etat = vingtAgents();
  const debut = performance.now();
  for (let i = 0; i < 200; i++) construireScene(etat, null, { t: i * 16 });
  const moyenne = (performance.now() - debut) / 200;
  console.log(`construireScene : ${moyenne.toFixed(3)} ms par image`);
  assert.ok(moyenne < 8);
});
