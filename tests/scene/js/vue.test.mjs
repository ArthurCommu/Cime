// Vue de la scène (vue.js) : tout voir, zoom ancré sur le curseur, bornes du déplacement, passage écran ↔ monde.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  PALIER_MAX,
  ajuster,
  borner,
  deplacer,
  ecranVersCase,
  ecranVersMonde,
  mondeVersEcran,
  reajuster,
  zoomer,
} from '../../../src/cime/scene/static/vue.js';

const MONDE = { w: 672, h: 240 }; // étage de l’état d’exemple (sans la légende)

// Le conteneur de la scène dans la page : un rectangle quelconque, que la scène remplit.
const portPour = (w, h) => ({ w, h });

test('ajuster : conteneur 1248×554 → ×1, centré', () => {
  assert.deepEqual(ajuster(MONDE, portPour(1248, 554)), { echelle: 1, x: 288, y: 157 });
});

test('ajuster : conteneur 1888×914 → étage ×2, centré', () => {
  assert.deepEqual(ajuster(MONDE, portPour(1888, 914)), { echelle: 2, x: 272, y: 217 });
});

test('ajuster : conteneurs étroits ou plats → ×1, sans crash, port nul compris', () => {
  assert.equal(ajuster(MONDE, portPour(768, 444)).echelle, 1);
  const petit = ajuster(MONDE, portPour(374, 150));
  assert.equal(petit.echelle, 1);
  assert.equal(petit.x, 0, 'plus étroit que l’étage : l’étage commence au bord gauche');
  const nul = ajuster(MONDE, portPour(0, 0));
  assert.equal(nul.echelle, 1);
  assert.equal(nul.y, 0, 'port de hauteur nulle : décalage borné à 0');
});

test('ajuster : jamais au-delà du palier max, et l’étage tient quand il tient', () => {
  const port = { w: 4000, h: 3000 };
  const petit = { w: 100, h: 50 };
  const v = ajuster(petit, port);
  assert.equal(v.echelle, PALIER_MAX);
  for (const [w, h] of [[1280, 720], [1920, 1080], [800, 600], [400, 300]]) {
    const p = portPour(w, h);
    const a = ajuster(MONDE, p);
    assert.ok(MONDE.w * a.echelle <= p.w || a.echelle === 1, 'largeur : tient, ou ×1');
    assert.ok(MONDE.h * a.echelle <= p.h || a.echelle === 1, 'hauteur : tient, ou ×1');
  }
});

test('zoomer : le point monde sous le curseur ne bouge pas (à l’arrondi près)', () => {
  const port = { w: 500, h: 200 };
  const vue = { echelle: 1, x: -100, y: -30 };
  const curseur = { x: 250, y: 100 };
  const avant = ecranVersMonde(vue, curseur.x, curseur.y);
  const apres = zoomer(vue, 1, curseur, MONDE, port);
  assert.equal(apres.echelle, 2);
  const apresMonde = ecranVersMonde(apres, curseur.x, curseur.y);
  assert.ok(Math.abs(apresMonde.x - avant.x) <= 1 / apres.echelle, `x : ${apresMonde.x} ≠ ${avant.x}`);
  assert.ok(Math.abs(apresMonde.y - avant.y) <= 1 / apres.echelle, `y : ${apresMonde.y} ≠ ${avant.y}`);
  // Second palier, même curseur : toujours ancré.
  const encore = zoomer(apres, 1, curseur, MONDE, port);
  assert.equal(encore.echelle, 3);
  const encoreMonde = ecranVersMonde(encore, curseur.x, curseur.y);
  assert.ok(Math.abs(encoreMonde.x - avant.x) <= 1 / encore.echelle);
  assert.ok(Math.abs(encoreMonde.y - avant.y) <= 1 / encore.echelle);
});

test('zoomer : palier ±1, plancher ×1, plafond ×6, pas d’effet hors bornes', () => {
  const port = { w: 500, h: 200 };
  const milieu = { x: 250, y: 100 };
  assert.equal(zoomer({ echelle: 1, x: 0, y: 0 }, -1, milieu, MONDE, port).echelle, 1);
  assert.equal(zoomer({ echelle: PALIER_MAX, x: 0, y: 0 }, 1, milieu, MONDE, port).echelle, PALIER_MAX);
  assert.equal(zoomer({ echelle: 3, x: 0, y: 0 }, -1, milieu, MONDE, port).echelle, 2);
});

test('deplacer : borné quand l’étage dépasse le port, jamais de vide', () => {
  const port = { w: 500, h: 200 };
  const vue = { echelle: 2, x: 0, y: 0 };
  const loin = deplacer(vue, 10000, 10000, MONDE, port);
  assert.deepEqual(loin, { echelle: 2, x: 0, y: 0 }, 'bord gauche et haut ne s’écartent pas du port');
  const tout = deplacer(vue, -10000, -10000, MONDE, port);
  assert.deepEqual(tout, { echelle: 2, x: 500 - 1344, y: 200 - 480 }, 'bord droit et bas restent au port');
});

test('deplacer : centré quand l’étage tient', () => {
  const port = { w: 1000, h: 600 };
  const vue = { echelle: 1, x: 0, y: 0 };
  assert.deepEqual(deplacer(vue, 300, 300, MONDE, port), { echelle: 1, x: 164, y: 180 });
});

test('borner : entiers, échelle ramenée au palier', () => {
  const v = borner({ echelle: 9.4, x: 3.6, y: -2.2 }, MONDE, { w: 4000, h: 3000 });
  assert.equal(v.echelle, PALIER_MAX);
  for (const c of [v.x, v.y, v.echelle]) assert.ok(Number.isInteger(c));
});

test('aller-retour écran ↔ monde', () => {
  const vue = { echelle: 3, x: 37, y: 11 };
  for (const [px, py] of [[0, 0], [37, 11], [400, 300], [1279, 719]]) {
    const m = ecranVersMonde(vue, px, py);
    const r = mondeVersEcran(vue, m.x, m.y);
    assert.ok(Math.abs(r.x - px) < 1e-9 && Math.abs(r.y - py) < 1e-9, `${px},${py}`);
  }
});

test('ecranVersCase : tient compte du décalage et de l’échelle', () => {
  const vue = { echelle: 3, x: 10, y: 5 };
  assert.deepEqual(ecranVersCase(vue, 10 + 3 * 7 + 1, 5 + 3 * 4 + 2), { x: 7, y: 4 });
  assert.deepEqual(ecranVersCase(vue, 10 + 3 * 7 - 1, 5 + 3 * 4), { x: 6, y: 4 });
});

// Le conteneur change de taille (fenêtre redimensionnée, onglet qui s'affiche) : tant que la personne n'a ni zoomé ni
// déplacé, l'étage reste « tout voir » ; sinon son échelle est gardée et seules les bornes sont rejouées.
test('reajuster : en auto, l’étage suit le conteneur (grand puis petit)', () => {
  const grand = { w: 1408, h: MONDE.h * 8 };
  const final = { w: 1408, h: MONDE.h + 1 };
  const vue0 = reajuster(null, true, MONDE, grand);
  assert.ok(vue0.echelle > ajuster(MONDE, final).echelle, 'le cas : première échelle trop grande pour le conteneur final');
  const vue1 = reajuster(vue0, true, MONDE, final);
  assert.deepEqual(vue1, ajuster(MONDE, final));
  assert.ok(MONDE.w * vue1.echelle <= final.w && MONDE.h * vue1.echelle <= final.h, 'étage entier dans le conteneur');
});

test('reajuster : après un zoom ou un déplacement (auto = faux), l’échelle choisie est gardée', () => {
  const garde = reajuster({ echelle: 3, x: -100, y: 0 }, false, { w: 288, h: 128 }, { w: 1408, h: 224 });
  assert.equal(garde.echelle, 3);
});
