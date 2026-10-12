// scene.js — l'interface publique : monterScene(conteneur, { source, surClic, surSurvol, surPret, theme }), LEGENDE,
// dessinerIcone. Sous node, avec un faux navigateur (faux-dom.mjs) : le canvas, les clics, la fin.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { monterScene, dateDeInstantane, LEGENDE, dessinerIcone } from '../../../src/cime/scene/static/scene.js';
import { LEGENDE as ENTREES } from '../../../src/cime/scene/static/legende.js';
import { construireScene } from '../../../src/cime/scene/static/modele.js';
import { ajuster, mondeVersEcran } from '../../../src/cime/scene/static/vue.js';
import { fauxNavigateur, evt, FauxCanvas } from './faux-dom.mjs';

const ICI = dirname(fileURLToPath(import.meta.url));
const ETAT = JSON.parse(readFileSync(join(ICI, '..', 'fixtures', 'etat-exemple.json'), 'utf8'));
const PLAN = construireScene(ETAT);
const MONDE = { w: PLAN.largeur, h: PLAN.hauteurEtage };

// Une source du direct : donne un instantané dès qu'on s'abonne, sans avancerA.
function sourceDirecte(etat = ETAT) {
  const s = {
    abonnements: [],
    arrets: 0,
    abonner(cb, options) {
      s.abonnements.push(options);
      cb(structuredClone(etat), [], 123456, { reset: true });
    },
    arreter() {
      s.arrets++;
    },
  };
  return s;
}

function monter(options = {}, navigateur = fauxNavigateur(options.navigateur)) {
  const appels = { clics: [], survols: [], prets: 0 };
  const source = options.source ?? sourceDirecte();
  const scene = monterScene(navigateur.conteneur, {
    source,
    surClic: (c) => appels.clics.push(c),
    surSurvol: (c, info) => appels.survols.push([c, info]),
    surPret: () => appels.prets++,
    theme: options.theme,
  });
  navigateur.image();
  const canvas = navigateur.conteneur.enfants[0];
  return { navigateur, scene, canvas, appels, source };
}

// Position écran du centre d'une zone du monde, pour une vue « tout voir » dans le conteneur.
const ecranDe = (nav, zone) => {
  const vue = ajuster(MONDE, { w: nav.conteneur.clientWidth, h: nav.conteneur.clientHeight });
  return mondeVersEcran(vue, zone.x + zone.w / 2, zone.y + zone.h / 2);
};
const cliquerEn = (canvas, p) => canvas.dispatchEvent(evt('click', { clientX: p.x, clientY: p.y, detail: 1 }));

test('sans effet de bord à l’import : aucun document ni minuteur requis', () => {
  assert.equal(typeof monterScene, 'function');
  assert.equal(typeof dessinerIcone, 'function');
  assert.ok(LEGENDE.length > 0);
});

test('la source doit avoir abonner() et arreter()', () => {
  const nav = fauxNavigateur();
  assert.throws(() => monterScene(nav.conteneur, { source: {} }), TypeError);
  assert.throws(() => monterScene(nav.conteneur, {}), TypeError);
  assert.equal(nav.conteneur.enfants.length, 0);
});

test('la scène crée un canvas dans le conteneur et rien d’autre, de la taille du conteneur', () => {
  const { navigateur, canvas, appels } = monter({ theme: { fond: '#f4f1ea' } });
  assert.equal(navigateur.conteneur.enfants.length, 1);
  assert.ok(canvas instanceof FauxCanvas);
  assert.equal(canvas.style.width, '1888px');
  assert.equal(canvas.style.height, '914px');
  assert.equal(canvas.style.background, '#f4f1ea', 'le pourtour se fond dans le fond de la page');
  assert.equal(navigateur.conteneur.style.position, 'relative', 'le conteneur sert de repère au canvas');
  assert.equal(canvas.tabIndex, 0);
  assert.ok(canvas.attributs['aria-label']);
  assert.equal(appels.prets, 1, 'surPret une seule fois, à la première image');
  navigateur.image();
  assert.equal(appels.prets, 1);
});

test('un conteneur déjà positionné n’est pas touché', () => {
  const nav = fauxNavigateur({ positionConteneur: 'absolute' });
  monter({}, nav);
  assert.equal(nav.conteneur.style.position, undefined);
});

test('rien n’est dessiné tant que l’hôte n’a pas répondu', () => {
  const nav = fauxNavigateur();
  const muette = { abonner() {}, arreter() {} };
  const { appels, canvas } = monter({ source: muette }, nav);
  assert.equal(canvas.derniereCopie(), null);
  assert.equal(appels.prets, 0);
});

test('l’étage est ajusté au conteneur, à une échelle entière, et suit ses changements de taille', () => {
  const { navigateur, canvas } = monter();
  const k = ajuster(MONDE, { w: 1888, h: 914 }).echelle;
  assert.ok(k >= 2);
  const copie = canvas.derniereCopie();
  assert.equal(copie[7], MONDE.w * k, 'largeur copiée = étage × échelle entière');
  navigateur.redimensionner(640, 400);
  navigateur.image();
  assert.equal(canvas.style.width, '640px');
  assert.equal(canvas.style.height, '400px');
  assert.equal(canvas.derniereCopie()[7], MONDE.w * ajuster(MONDE, { w: 640, h: 400 }).echelle);
  navigateur.redimensionner(0, 0);
  const avant = canvas.ctx.appels.length;
  navigateur.image();
  assert.equal(canvas.ctx.appels.length, avant, 'conteneur masqué : rien à dessiner');
});

test('écran haute densité : le canvas a d pixels physiques par pixel CSS, entier', () => {
  const { canvas } = monter({ navigateur: { ratio: 2 } });
  assert.equal(canvas.width, 1888 * 2);
  assert.equal(canvas.style.width, '1888px');
});

test('clic sur une équipe, un agent ou l’utilisateur : surClic nomme la cible, la scène ne navigue pas', () => {
  const { navigateur, canvas, appels } = monter();
  const equipe = PLAN.pieces.find((p) => !p.neutre);
  // un point libre de la pièce : ni agent ni enveloppe
  let pt = null;
  for (let y = equipe.y + 20; y < equipe.y + equipe.h - 4 && !pt; y += 3) {
    for (let x = equipe.x + 8; x < equipe.x + equipe.w - 8 && !pt; x += 3) {
      if (!PLAN.agents.some((a) => x >= a.zone.x && x < a.zone.x + a.zone.w && y >= a.zone.y && y < a.zone.y + a.zone.h)) pt = { x, y, w: 1, h: 1 };
    }
  }
  cliquerEn(canvas, ecranDe(navigateur, pt));
  assert.deepEqual(appels.clics.at(-1), { type: 'equipe', nom: equipe.nom });

  const agent = PLAN.agents.find((a) => a.id === 'coord-page');
  cliquerEn(canvas, ecranDe(navigateur, agent.zone));
  assert.deepEqual(appels.clics.at(-1), { type: 'agent', id: 'coord-page' });

  const utilisateur = PLAN.pieces.find((p) => p.nom === 'utilisateur');
  cliquerEn(canvas, ecranDe(navigateur, { x: utilisateur.x + 6, y: utilisateur.y + utilisateur.h - 20, w: 1, h: 1 }));
  assert.deepEqual(appels.clics.at(-1), { type: 'utilisateur' });
  assert.equal(appels.clics.length, 3);
});

test('clic dans le couloir ou sur l’Assistant seul : aucun appel', () => {
  const { navigateur, canvas, appels } = monter();
  const c = PLAN.couloirs[0];
  cliquerEn(canvas, ecranDe(navigateur, { x: c.x + 4, y: c.y + 2, w: 1, h: 1 }));
  assert.deepEqual(appels.clics, []);
  const assistant = PLAN.pieces.find((p) => p.nom === 'assistant');
  cliquerEn(canvas, ecranDe(navigateur, { x: assistant.x + 3, y: assistant.y + assistant.h - 3, w: 1, h: 1 }));
  assert.deepEqual(appels.clics, []);
});

test('glisser n’est pas cliquer : aucun surClic après un déplacement', () => {
  const { navigateur, canvas, appels } = monter();
  const agent = PLAN.agents.find((a) => a.id === 'coord-page');
  const p = ecranDe(navigateur, agent.zone);
  canvas.dispatchEvent(evt('pointerdown', { pointerId: 1, clientX: p.x, clientY: p.y }));
  canvas.dispatchEvent(evt('pointermove', { pointerId: 1, clientX: p.x + 30, clientY: p.y, buttons: 1 }));
  canvas.dispatchEvent(evt('pointerup', { pointerId: 1, clientX: p.x + 30, clientY: p.y }));
  cliquerEn(canvas, { x: p.x + 30, y: p.y });
  assert.deepEqual(appels.clics, []);
});

test('survol : curseur main et surSurvol(cible, info) une fois par cible, null en sortant', () => {
  const { navigateur, canvas, appels } = monter();
  const agent = PLAN.agents.find((a) => a.id === 'coord-page');
  const p = ecranDe(navigateur, agent.zone);
  canvas.dispatchEvent(evt('pointermove', { clientX: p.x, clientY: p.y, buttons: 0, pointerType: 'mouse' }));
  canvas.dispatchEvent(evt('pointermove', { clientX: p.x + 1, clientY: p.y, buttons: 0, pointerType: 'mouse' }));
  assert.equal(canvas.style.cursor, 'pointer');
  assert.equal(appels.survols.length, 1, 'pas de rappel tant que la cible ne change pas');
  const [cible, info] = appels.survols[0];
  assert.deepEqual(cible, { type: 'agent', id: 'coord-page' });
  assert.equal(info.titre, 'coord-page');
  assert.ok(info.lignes.includes('attend une autorisation'), `libellé humain : ${info.lignes}`);
  assert.equal(JSON.stringify(info).includes('brouillon'), false, 'jamais de texte libre');
  canvas.dispatchEvent(evt('pointerleave'));
  assert.deepEqual(appels.survols.at(-1), [null, undefined]);
  assert.equal(canvas.style.cursor, 'grab');
});

test('clavier sur la scène : + et − zooment, 0 remet tout voir', () => {
  const { navigateur, canvas } = monter();
  const k0 = ajuster(MONDE, { w: 1888, h: 914 }).echelle;
  const echelle = () => canvas.derniereCopie()[7] / MONDE.w;
  assert.equal(echelle(), k0);
  const touche = (key) => {
    const e = evt('keydown', { key });
    canvas.dispatchEvent(e);
    navigateur.image();
    return e;
  };
  assert.ok(touche('+').defaultPrevented);
  assert.equal(echelle(), k0 + 1);
  touche('-');
  touche('-');
  assert.equal(echelle(), k0 - 1);
  touche('0');
  assert.equal(echelle(), k0);
  assert.equal(touche('a').defaultPrevented, false, 'les autres touches restent à la page');
});

test('une source de scénario rejoué est avancée au temps de la boucle', () => {
  const vus = [];
  const scenario = { ...sourceDirecte(), scenario: true, avancerA: (t) => vus.push(t) };
  const nav = fauxNavigateur();
  monter({ source: scenario }, nav);
  nav.image();
  assert.equal(vus[0], 0);
  assert.ok(vus[1] > 0 && vus[1] <= 100);
});

test('arreter : canvas retiré, source et boucle arrêtées, conteneur rendu comme il était ; deux fois sans mal', () => {
  const { navigateur, scene, source } = monter();
  scene.arreter();
  assert.equal(navigateur.conteneur.enfants.length, 0);
  assert.equal(source.arrets, 1);
  assert.equal(navigateur.imagesEnAttente(), 0, 'plus aucune image demandée');
  assert.equal(navigateur.fenetre.observateurs[0].coupe, true);
  assert.equal(navigateur.conteneur.style.position, undefined);
  scene.arreter();
  assert.equal(source.arrets, 1);
});

test('redimensionner() relit la taille du conteneur', () => {
  const { navigateur, scene, canvas } = monter();
  navigateur.conteneur.clientWidth = 700;
  navigateur.conteneur.clientHeight = 300;
  scene.redimensionner();
  navigateur.image();
  assert.equal(canvas.style.width, '700px');
});

// ---- La légende, en données ------------------------------------------------------------------------------------
test('LEGENDE : chaque entrée a un sprite, un libellé, un groupe ; les signes de problème sont marqués', () => {
  assert.equal(LEGENDE.length, ENTREES.length);
  for (const e of LEGENDE) {
    assert.ok(typeof e.sprite === 'string' && e.sprite);
    assert.ok(typeof e.libelle === 'string' && e.libelle.trim());
    assert.ok(typeof e.groupe === 'string' && e.groupe);
    assert.equal(typeof e.probleme, 'boolean');
  }
  assert.equal(LEGENDE.filter((e) => e.probleme).length, ENTREES.filter((e) => e.probleme).length);
  assert.ok(Object.isFrozen(LEGENDE));
});

test('dessinerIcone : dessine chaque signe de la légende dans le canvas de la page, à l’échelle entière demandée', () => {
  const nav = fauxNavigateur({ ratio: 2 });
  for (const e of LEGENDE) {
    const c = new FauxCanvas(nav.doc);
    assert.equal(dessinerIcone(c, e.sprite, { echelle: 3 }), true, e.sprite);
    assert.ok(c.width > 0 && c.width % (3 * 2) === 0, `${e.sprite} : largeur physique = largeur × 3 × 2`);
    assert.ok(c.style.width.endsWith('px') && Number.parseInt(c.style.width) % 3 === 0);
    assert.ok(c.derniereCopie(), `${e.sprite} : copié dans le canvas`);
    assert.equal(c.style.imageRendering, 'pixelated');
  }
  assert.equal(dessinerIcone(new FauxCanvas(nav.doc), 'sprite.inconnu'), false);
});

// La date d'un instantané : une source de scénario date elle-même (le scénario est son horloge) ; le direct est daté
// par la scène, quelle que soit l'horloge de la page (999999999 est une date que la source croit juste).
test('dateDeInstantane : le direct est daté par la scène, le scénario par sa source', () => {
  assert.equal(dateDeInstantane({ scenario: false }, 999999999, 4200), 4200);
  assert.equal(dateDeInstantane({}, 999999999, 4200), 4200);
  assert.equal(dateDeInstantane({ scenario: true }, 15000, 4200), 15000);
  assert.equal(dateDeInstantane({ scenario: true }, undefined, 4200), 4200, 'un scénario sans date : celle de la scène');
});
