// Scénario : rejoué en entier sur la surface PNG, il déclenche chaque animation 1 à 25 de la table ;
// aucun sprite manquant ; chaque message suit l’ordre du registre. Mesure de performance imprimée.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { TABLE } from '../../../src/cime/scene/static/animations.js';
import { creerSourceRejouee } from './support/source-rejouee.mjs';
import { creerFil, appliquerSnapshot, sceneA } from '../../../src/cime/scene/static/modele.js';
import { dessiner } from '../../../src/cime/scene/static/rendu.js';
import { SurfacePNG } from '../../../src/cime/scene/static/surface-png.mjs';
import { DUREE_MS, PAS } from './support/scenario.mjs';
import { ATLAS_FACTICE, PALETTE_FACTICE } from './atlas-factice.mjs';
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ICI = dirname(fileURLToPath(import.meta.url));
const FIXTURE = join(ICI, '..', 'fixtures', 'etat-exemple.json');
const ORDRE_REGISTRE = ['inscrit', 'livre', 'pris_en_compte', 'clos'];
const TERMINAUX = ['echec', 'abandonne'];

// Rejoue le scénario à pas de 100 ms, comme la boucle, et récolte les observations.
function rejouer() {
  const etatInitial = JSON.parse(readFileSync(FIXTURE, 'utf8'));
  const source = creerSourceRejouee({ etatInitial });
  const fil = creerFil();
  const sequences = new Map();
  source.abonner((etat, trs, t, { reset }) => {
    appliquerSnapshot(fil, etat, trs, t, { reset });
    for (const tr of trs) {
      if (!sequences.has(tr.id)) sequences.set(tr.id, []);
      sequences.get(tr.id).push(tr.etat);
    }
  });
  const raisons = new Set();
  let manquesMax = 0;
  let agentsMax = 0;
  for (let t = 0; t < DUREE_MS; t += 100) {
    source.avancerA(t);
    const scene = sceneA(fil, t);
    scene.raisons.forEach((r) => raisons.add(r));
    const surface = new SurfacePNG(scene.largeur, scene.hauteur, ATLAS_FACTICE, PALETTE_FACTICE);
    manquesMax = Math.max(manquesMax, dessiner(surface, ATLAS_FACTICE, scene, t));
    // visibles + repliés : un worker arrêté n'a plus de poste, mais il compte toujours dans l'équipe
    agentsMax = Math.max(agentsMax, scene.agents.length + scene.pieces.reduce((t, p) => t + (p.compteur?.n ?? 0), 0));
  }
  return { raisons, sequences, manquesMax, agentsMax };
}

test('la table décrit les lignes 1 à 28 ; le scénario déclenche les lignes 1 à 25', () => {
  const { raisons } = rejouer();
  const manquent = Array.from({ length: 25 }, (_, i) => i + 1).filter((n) => !raisons.has(n));
  assert.deepEqual(manquent, [], `lignes jamais déclenchées : ${manquent}`);
  assert.equal(TABLE.length, 28);
});

test('aucun sprite manquant sur tout le scénario (scene.manques == 0)', () => {
  assert.equal(rejouer().manquesMax, 0);
});

test('le scénario garde au moins 15 agents, visibles ou repliés (fixture à 15, plus l’ouvrier embauché)', () => {
  assert.ok(rejouer().agentsMax >= 15);
});

test('chaque message suit l’ordre du registre : inscrit → livre → pris_en_compte → clos, ou échec / abandon', () => {
  const { sequences } = rejouer();
  assert.ok(sequences.size >= 5);
  for (const [id, seq] of sequences) {
    const finaux = seq.filter((e) => TERMINAUX.includes(e));
    if (finaux.length) {
      assert.equal(seq.at(-1), finaux[0], `message ${id} : après un terminal`);
      continue;
    }
    const indices = seq.map((e) => ORDRE_REGISTRE.indexOf(e));
    assert.ok(indices.every((i) => i >= 0), `message ${id} : état inconnu ${seq}`);
    assert.ok(indices.every((i, k) => k === 0 || i > indices[k - 1]), `message ${id} : désordre ${seq}`);
  }
});

test('le scénario ne contient aucun texte libre dans les transitions', () => {
  for (const pas of PAS) {
    for (const tr of pas.transitions ?? []) {
      assert.equal(tr.resume, undefined, `étape ${pas.t} : résumé dans une transition`);
      assert.equal(tr.objet, undefined, `étape ${pas.t} : objet dans une transition`);
    }
  }
});

test('chaque étape du scénario porte un commentaire qui cite une animation de la table', () => {
  for (const pas of PAS) {
    assert.match(pas.commentaire, /animation \d+|fin de boucle/, `étape ${pas.t}`);
  }
});
