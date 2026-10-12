// Confidentialité : la scène ne dessine jamais resume, derniere_phrase ni brouillon.texte.
// Une surface espionne enregistre chaque appel de dessin ; on y cherche des textes piégés.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { construireScene } from '../../../src/cime/scene/static/modele.js';
import { dessiner } from '../../../src/cime/scene/static/rendu.js';
import { LEGENDE, GROUPES, lignes } from '../../../src/cime/scene/static/legende.js';
import { ATLAS_FACTICE } from './atlas-factice.mjs';

const ICI = dirname(fileURLToPath(import.meta.url));
const FIXTURE = join(ICI, '..', 'fixtures', 'etat-exemple.json');
const PIEGE = 'SECRET-PRIVE-7f3a';

function espion() {
  const appels = [];
  return {
    appels,
    rect: (...a) => appels.push(['rect', ...a]),
    sprite: (...a) => appels.push(['sprite', ...a]),
    texte: (...a) => appels.push(['texte', ...a]),
    taille: () => ({ w: 0, h: 0 }),
  };
}

// Les appels de dessin de l'étage seulement ; la légende (libellés constants de legende.js) est vérifiée à part.
const hauteurDe = { texte: 3, sprite: 4, rect: 2 };
const etage = (appels, scene) => appels.filter(([g, ...a]) => a[hauteurDe[g] - 1] < scene.hauteurEtage);

function piege(etat) {
  const a = etat.agents.find((g) => g.id === 'assistant');
  a.derniere_phrase = `${PIEGE} phrase`;
  a.brouillon = { texte: `${PIEGE} brouillon`, depuis: '2026-10-11T09:00:00.000Z' };
  etat.flux.forEach((f) => {
    f.resume = `${PIEGE} résumé`;
    f.objet = `${PIEGE} objet`;
  });
  return etat;
}

test('texte libre privé rempli : la scène ne le dessine jamais', () => {
  const etat = piege(JSON.parse(readFileSync(FIXTURE, 'utf8')));
  const surface = espion();
  const scene = construireScene(etat);
  dessiner(surface, ATLAS_FACTICE, scene, 1000);
  const tout = JSON.stringify(etage(surface.appels, scene));
  assert.equal(tout.includes(PIEGE), false);
  assert.equal(tout.includes('phrase'), false);
  assert.equal(tout.includes('brouillon'), false);
});

// Les seuls textes à nombre variable : le « +N » des arrêtés repliés et le compteur hors organigramme (legende, rendu.js).
// Un nombre et rien d'autre ; aucun texte d'instantané n'y passe.
const GABARITS_COMPTEUR = [/^\+\d+$/, /^hors organigramme : \d+(\+\?)?$/];

test('conversation privée à null (instantané par défaut) : rien de texte libre n’apparaît', () => {
  const etat = JSON.parse(readFileSync(FIXTURE, 'utf8'));
  const assistant = etat.agents.find((g) => g.id === 'assistant');
  Object.assign(assistant, { derniere_phrase: null, brouillon: null });
  etat.flux.forEach((f) => Object.assign(f, { resume: null, objet: null }));
  const surface = espion();
  const scene = construireScene(etat);
  dessiner(surface, ATLAS_FACTICE, scene, 0);
  for (const [genre, ...args] of etage(surface.appels, scene)) {
    if (genre !== 'texte') continue;
    const chaine = args[0];
    assert.ok(/^[a-z0-9?.\-]*$/i.test(chaine) || GABARITS_COMPTEUR.some((g) => g.test(chaine)), `texte inattendu : « ${chaine} »`);
  }
});

test('les textes dessinés sont des identifiants, des états ou des compteurs', () => {
  const etat = piege(JSON.parse(readFileSync(FIXTURE, 'utf8')));
  const surface = espion();
  const scene = construireScene(etat);
  dessiner(surface, ATLAS_FACTICE, scene, 0);
  const textes = etage(surface.appels, scene).filter(([g]) => g === 'texte').map((a) => a[1]);
  assert.ok(textes.length > 0);
  for (const t of textes) assert.ok(!t.includes(' ') || t === ' ' || GABARITS_COMPTEUR.some((g) => g.test(t)), `texte libre possible : « ${t} »`);
});

test('la légende n\'écrit que ses libellés constants (aucune donnée de l\'instantané)', () => {
  const etat = piege(JSON.parse(readFileSync(FIXTURE, 'utf8')));
  const surface = espion();
  const scene = construireScene(etat);
  dessiner(surface, ATLAS_FACTICE, scene, 0);
  const permis = new Set([...Object.values(GROUPES), ...LEGENDE.flatMap(lignes), '?', 'x.xx']);
  const textes = surface.appels.filter(([g, ...a]) => g === 'texte' && a[2] >= scene.hauteurEtage).map((a) => a[1]);
  assert.ok(textes.length > 20);
  for (const t of textes) assert.ok(permis.has(t), `texte de légende inattendu : « ${t} »`);
});
