// Libellé « toi » : la salle de l’utilisateur s’écrit « toi » à l’écran ; son id (p.nom) et sa cible de clic ne changent pas.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { construireScene } from '../../../src/cime/scene/static/modele.js';
import { ecrireNoms } from '../../../src/cime/scene/static/noms.js';
import { cibleDe } from '../../../src/cime/scene/static/interaction.js';

const ICI = dirname(fileURLToPath(import.meta.url));
const FIXTURE = join(ICI, '..', 'fixtures', 'etat-exemple.json');
const scene = () => construireScene(JSON.parse(readFileSync(FIXTURE, 'utf8')));

// Un contexte qui note ce qu'on écrit ; mesure : 6 px par caractère.
function ctxEspion() {
  const ecrits = [];
  const ctx = {
    font: '', fillStyle: '', textBaseline: '', textAlign: '',
    save() {}, restore() {}, setTransform() {},
    measureText: (t) => ({ width: [...t].length * 6 }),
    fillText: (t, x, y) => ecrits.push({ t, x, y }),
  };
  return { ctx, ecrits };
}

test('libellé : la pièce de l’utilisateur porte « toi », les autres pièces portent leur nom', () => {
  const s = scene();
  assert.equal(s.pieces.find((p) => p.nom === 'utilisateur').libelle, 'toi');
  for (const p of s.pieces.filter((q) => q.nom !== 'utilisateur')) assert.equal(p.libelle, p.nom, p.nom);
});

test('libellé : p.nom reste « utilisateur » et la cible de clic reste la salle de l’utilisateur', () => {
  const s = scene();
  assert.equal(s.pieces.find((p) => p.nom === 'utilisateur').nom, 'utilisateur');
  assert.deepEqual(cibleDe(s, { type: 'piece', id: 'utilisateur' }), { type: 'utilisateur' });
});

test('libellé : l’en-tête écrit « toi » pour l’utilisateur, et jamais « utilisateur »', () => {
  const s = scene();
  const { ctx, ecrits } = ctxEspion();
  ecrireNoms(ctx, s, { echelle: 2, x: 0, y: 0 });
  const textes = ecrits.map((e) => e.t);
  assert.ok(textes.includes('toi'), `« toi » absent : ${textes.join(', ')}`);
  assert.equal(textes.includes('utilisateur'), false);
  assert.ok(textes.includes('page'), 'les autres pièces gardent leur nom');
});
