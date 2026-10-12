// Interaction (zones de clic, infobulles, gestes sur le port, jonction « scene:ouvrir ») et boucle (arrêt quand l'onglet est caché).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { construireScene } from '../../../src/cime/scene/static/modele.js';
import {
  elementSous,
  infobulle,
  cibleDe,
  cliquer,
  creerGestes,
  DELAI_PALIER_MS,
  SEUIL_DEPLACEMENT_PX,
} from '../../../src/cime/scene/static/interaction.js';
import { creerBoucle } from '../../../src/cime/scene/static/boucle.js';
import { ajuster, deplacer, ecranVersCase, mondeVersEcran, zoomer } from '../../../src/cime/scene/static/vue.js';

const ICI = dirname(fileURLToPath(import.meta.url));
const FIXTURE = join(ICI, '..', 'fixtures', 'etat-exemple.json');
const scene = () => construireScene(JSON.parse(readFileSync(FIXTURE, 'utf8')));

test('elementSous rend l’agent cliqué', () => {
  const s = scene();
  const a = s.agents.find((g) => g.id === 'coord-page');
  assert.deepEqual(elementSous(s, a.x, a.y), { type: 'agent', id: 'coord-page' });
});

test('elementSous rend l’enveloppe cliquée', () => {
  const s = scene();
  const e = s.enveloppes[0];
  assert.deepEqual(elementSous(s, e.x, e.y), { type: 'enveloppe', id: e.id });
});

test('elementSous rend null sur le décor : couloir, emplacement libre, hors de l’étage', () => {
  const s = scene();
  const c = s.couloirs[0];
  assert.equal(elementSous(s, c.x + 2, c.y + 2), null, 'le couloir n’est rien');
  assert.equal(elementSous(s, -1, -1), null);
  assert.equal(elementSous(s, s.largeur, s.hauteurEtage), null);
});

// Les pièces : un clic sur le sol d’une équipe désigne l’équipe, jamais sur un agent ni une enveloppe qui s’y trouve.
const sansAgentNiEnveloppe = (s, p) => {
  for (let y = p.y + 20; y < p.y + p.h - 4; y += 3) {
    for (let x = p.x + 8; x < p.x + p.w - 8; x += 3) {
      if (elementSous(s, x, y)?.type === 'piece') return { x, y };
    }
  }
  return null;
};

test('elementSous rend la pièce sous le point quand ni agent ni enveloppe n’y sont', () => {
  const s = scene();
  const equipes = s.pieces.filter((p) => !p.neutre);
  assert.ok(equipes.length >= 3);
  for (const p of equipes) {
    const pt = sansAgentNiEnveloppe(s, p);
    assert.ok(pt, `${p.nom} : un point libre`);
    assert.deepEqual(elementSous(s, pt.x, pt.y), { type: 'piece', id: p.nom });
  }
});

test('cibleDe : équipe, agent, message, l’utilisateur ; rien pour l’Assistant seul ni le décor', () => {
  const s = scene();
  const equipe = s.pieces.find((p) => !p.neutre);
  const pt = sansAgentNiEnveloppe(s, equipe);
  assert.deepEqual(cibleDe(s, elementSous(s, pt.x, pt.y)), { type: 'equipe', nom: equipe.nom });
  assert.deepEqual(cibleDe(s, { type: 'agent', id: 'coord-page' }), { type: 'agent', id: 'coord-page' });
  const utilisateur = s.agents.find((a) => a.role === 'utilisateur');
  assert.deepEqual(cibleDe(s, { type: 'agent', id: utilisateur.id }), { type: 'utilisateur' }, 'L’utilisateur sur son siège : sa porte, ce qui l’attend');
  assert.deepEqual(cibleDe(s, { type: 'piece', id: 'utilisateur' }), { type: 'utilisateur' }, 'la salle de l’utilisateur aussi');
  assert.deepEqual(cibleDe(s, { type: 'enveloppe', id: 'm7' }), { type: 'message', id: 'm7' });
  assert.equal(cibleDe(s, { type: 'piece', id: 'assistant' }), null);
  assert.equal(cibleDe(s, null), null);
});

test('infobulle d’une équipe : son nom et son état, avec les mots de la légende', () => {
  const s = scene();
  const p = s.pieces.find((g) => !g.neutre);
  const info = infobulle(s, 'piece', p.nom);
  assert.equal(info.titre, p.nom);
  assert.match(info.lignes[0], /^(active|au repos|bloquée|terminée|non mesuré)$/);
  assert.equal(infobulle(s, 'piece', 'assistant'), null);
});

test('infobulle : id, état et tâche seulement, jamais de texte libre', () => {
  const s = scene();
  const info = infobulle(s, 'agent', 'coord-page');
  assert.equal(info.titre, 'coord-page');
  assert.ok(info.lignes.includes('attend une autorisation'));
  assert.equal(JSON.stringify(info).includes('brouillon'), false);
});

test('cliquer émet « scene:ouvrir » avec le type et l’id, sans rien faire d’autre', () => {
  const s = scene();
  const doc = new EventTarget();
  const recus = [];
  doc.addEventListener('scene:ouvrir', (ev) => recus.push(ev.detail));
  const a = s.agents.find((g) => g.id === 'coord-hote');
  cliquer(doc, s, a.x, a.y);
  assert.deepEqual(recus, [{ type: 'agent', id: 'coord-hote' }]);
  assert.equal(cliquer(doc, s, -1, -1), null);
  assert.equal(recus.length, 1);
});

// Faux document : visibilité et évènements contrôlables.
function fauxDoc(visibilite = 'visible') {
  const t = new EventTarget();
  t.visibilityState = visibilite;
  return t;
}

test('boucle : onglet caché au démarrage → aucune image demandée', () => {
  const doc = fauxDoc('hidden');
  let demandes = 0;
  const b = creerBoucle({ doc, rendre() {}, planifier: () => ++demandes, annuler() {} });
  b.demarrer();
  assert.equal(demandes, 0);
});

test('boucle : onglet caché pendant l’animation → annulation, aucune nouvelle image', () => {
  const doc = fauxDoc('visible');
  const demandes = [];
  const annules = [];
  let rappel = null;
  const b = creerBoucle({
    doc,
    rendre() {},
    planifier: (f) => {
      demandes.push(f);
      rappel = f;
      return demandes.length;
    },
    annuler: (id) => annules.push(id),
  });
  b.demarrer();
  assert.equal(demandes.length, 1);
  doc.visibilityState = 'hidden';
  doc.dispatchEvent(new Event('visibilitychange'));
  assert.deepEqual(annules, [1], 'l’image en attente est annulée');
  rappel(100);
  assert.equal(demandes.length, 1, 'aucune image n’est redemandée quand l’onglet est caché');
});

test('boucle : retour de l’onglet → reprise ; dt plafonné à 100 ms', () => {
  const doc = fauxDoc('visible');
  const dts = [];
  let rappel = null;
  const b = creerBoucle({
    doc,
    rendre: (t, dt) => dts.push(dt),
    planifier: (f) => {
      rappel = f;
      return 1;
    },
    annuler() {},
  });
  b.demarrer();
  rappel(1000);
  rappel(1016);
  doc.visibilityState = 'hidden';
  doc.dispatchEvent(new Event('visibilitychange'));
  doc.visibilityState = 'visible';
  doc.dispatchEvent(new Event('visibilitychange'));
  rappel(60000);
  assert.equal(dts[1], 16);
  assert.equal(dts[2], 0, 'après une reprise, pas de rattrapage du temps perdu');
  assert.ok(dts.every((d) => d <= 100));
});

// ---- Gestes sur le port -------------------------------------------------------------------------

// Évènement avec des propriétés imposées (timeStamp est un getter sous node : on le masque par une propriété propre).
function evt(type, props = {}) {
  const e = new Event(type, { cancelable: true });
  for (const [k, v] of Object.entries(props)) Object.defineProperty(e, k, { value: v });
  return e;
}

// Port de l'étage : un EventTarget dont le coin haut-gauche est à l'origine de l'écran.
function fauxPort() {
  const el = new EventTarget();
  el.getBoundingClientRect = () => ({ left: 0, top: 0 });
  return el;
}

// Enregistre les ordres reçus des gestes, sans vue réelle.
function enregistreur() {
  const ordres = { zoom: [], deplace: [], toutVoir: 0, clics: [] };
  return {
    ordres,
    gestes: {
      zoomer: (sens, p) => ordres.zoom.push([sens, p]),
      deplacer: (dx, dy) => ordres.deplace.push([dx, dy]),
      toutVoir: () => ordres.toutVoir++,
      clic: (p) => ordres.clics.push(p),
    },
  };
}

test('clic → bonne fiche à ×1, ×2 et ×3, décalage compris', () => {
  const s = scene();
  for (const echelle of [1, 2, 3]) {
    const vue = { echelle, x: 37, y: 11 };
    const port = fauxPort();
    const doc = new EventTarget();
    const recus = [];
    doc.addEventListener('scene:ouvrir', (ev) => recus.push(ev.detail.id));
    creerGestes(port, {
      zoomer() {},
      deplacer() {},
      toutVoir() {},
      clic: (p) => {
        const c = ecranVersCase(vue, p.x, p.y);
        cliquer(doc, s, c.x, c.y);
      },
    });
    for (const a of s.agents.filter((g) => g.zone)) {
      recus.length = 0;
      // Centre de la zone de l'agent, vu à travers la vue : le clic doit ouvrir la fiche de cet agent.
      const centre = mondeVersEcran(vue, a.zone.x + a.zone.w / 2, a.zone.y + a.zone.h / 2);
      port.dispatchEvent(evt('click', { clientX: centre.x, clientY: centre.y }));
      assert.deepEqual(recus, [a.id], `×${echelle} : clic sur ${a.id}`);
    }
  }
});

test('glisser ≠ clic : un déplacement au-delà du seuil ne déclenche jamais de clic', () => {
  const port = fauxPort();
  const { ordres, gestes } = enregistreur();
  creerGestes(port, gestes);
  port.dispatchEvent(evt('pointerdown', { pointerId: 1, clientX: 100, clientY: 100 }));
  port.dispatchEvent(evt('pointermove', { pointerId: 1, clientX: 120, clientY: 100 }));
  port.dispatchEvent(evt('pointerup', { pointerId: 1, clientX: 120, clientY: 100 }));
  port.dispatchEvent(evt('click', { clientX: 120, clientY: 100 }));
  assert.deepEqual(ordres.deplace, [[20, 0]], 'le glisser déplace l’étage du trajet entier');
  assert.deepEqual(ordres.clics, [], 'aucun clic après un glisser');
  // Le clic suivant, sans glisser, redevient un clic.
  port.dispatchEvent(evt('pointerdown', { pointerId: 2, clientX: 50, clientY: 50 }));
  port.dispatchEvent(evt('pointerup', { pointerId: 2, clientX: 50, clientY: 50 }));
  port.dispatchEvent(evt('click', { clientX: 50, clientY: 50 }));
  assert.equal(ordres.clics.length, 1);
});

test('un tremblement sous le seuil reste un clic', () => {
  const port = fauxPort();
  const { ordres, gestes } = enregistreur();
  creerGestes(port, gestes);
  port.dispatchEvent(evt('pointerdown', { pointerId: 1, clientX: 100, clientY: 100 }));
  port.dispatchEvent(evt('pointermove', { pointerId: 1, clientX: 100 + SEUIL_DEPLACEMENT_PX, clientY: 100 }));
  port.dispatchEvent(evt('pointerup', { pointerId: 1, clientX: 100 + SEUIL_DEPLACEMENT_PX, clientY: 100 }));
  port.dispatchEvent(evt('click', { clientX: 100, clientY: 100 }));
  assert.deepEqual(ordres.deplace, []);
  assert.equal(ordres.clics.length, 1);
});

test('molette : un palier par cran, pas deux paliers à moins du délai', () => {
  const port = fauxPort();
  const { ordres, gestes } = enregistreur();
  creerGestes(port, gestes);
  const roue = (t, deltaY) => port.dispatchEvent(evt('wheel', { timeStamp: t, deltaY, ctrlKey: false, clientX: 10, clientY: 20 }));
  // Quatre crans de 30 : un seul palier (cumul 120 ≥ 100), vers le bas → dézoom.
  [0, 16, 32, 48].forEach((t) => roue(t, 30));
  assert.deepEqual(ordres.zoom, [[-1, { x: 10, y: 20 }]]);
  // Rafale juste après : ignorée tant que le délai n’est pas écoulé.
  [64, 80, 96, 112].forEach((t) => roue(t, 30));
  assert.equal(ordres.zoom.length, 1);
  // Après le délai, molette vers le haut : zoom avant.
  roue(48 + DELAI_PALIER_MS + 100, -150);
  assert.equal(ordres.zoom.at(-1)[0], 1);
});

test('trackpad : une longue traînée ne fait pas enchaîner les paliers', () => {
  const port = fauxPort();
  const { ordres, gestes } = enregistreur();
  creerGestes(port, gestes);
  let t = 0;
  for (let i = 0; i < 1000; i++) {
    t += 16;
    port.dispatchEvent(evt('wheel', { timeStamp: t, deltaY: -3, ctrlKey: false, clientX: 0, clientY: 0 }));
  }
  assert.ok(ordres.zoom.length <= Math.ceil(t / DELAI_PALIER_MS) + 1, `${ordres.zoom.length} paliers en ${t} ms`);
  assert.ok(ordres.zoom.length >= 1);
});

test('pincement à deux doigts : un palier quand l’écartement change d’un facteur 1,25', () => {
  const port = fauxPort();
  const { ordres, gestes } = enregistreur();
  creerGestes(port, gestes);
  port.dispatchEvent(evt('pointerdown', { pointerId: 1, clientX: 100, clientY: 100 }));
  port.dispatchEvent(evt('pointerdown', { pointerId: 2, clientX: 200, clientY: 100 })); // écart 100
  port.dispatchEvent(evt('pointermove', { pointerId: 2, clientX: 210, clientY: 100 })); // écart 110 : rien
  assert.equal(ordres.zoom.length, 0);
  port.dispatchEvent(evt('pointermove', { pointerId: 2, clientX: 230, clientY: 100 })); // écart 130 ≥ 125 : un palier
  assert.equal(ordres.zoom.length, 1);
  assert.equal(ordres.zoom[0][0], 1);
  assert.deepEqual(ordres.zoom[0][1], { x: 165, y: 100 }, 'ancre : milieu des deux doigts');
  port.dispatchEvent(evt('pointerup', { pointerId: 1, clientX: 100, clientY: 100 }));
  port.dispatchEvent(evt('pointerup', { pointerId: 2, clientX: 230, clientY: 100 }));
  port.dispatchEvent(evt('click', { clientX: 165, clientY: 100 }));
  assert.equal(ordres.clics.length, 0, 'un pincement n’est pas un clic');
});

test('double-clic : tout voir, et une seule fiche (le second clic, detail 2, est ignoré)', () => {
  const port = fauxPort();
  const { ordres, gestes } = enregistreur();
  creerGestes(port, gestes);
  port.dispatchEvent(evt('click', { detail: 1, clientX: 50, clientY: 50 }));
  port.dispatchEvent(evt('click', { detail: 2, clientX: 50, clientY: 50 }));
  port.dispatchEvent(evt('dblclick', { detail: 2, clientX: 50, clientY: 50 }));
  assert.equal(ordres.clics.length, 1, 'une seule fiche');
  assert.equal(ordres.toutVoir, 1, 'double-clic = tout voir');
});

test('suite aléatoire à graine fixe : l’échelle reste un entier de 1 à 6, la vue reste bornée', () => {
  // Même câblage que app.js : les gestes modifient une vue réelle (vue.js).
  let graine = 20261011;
  const hasard = () => {
    graine = (graine * 1103515245 + 12345) & 0x7fffffff;
    return graine / 0x7fffffff;
  };
  const monde = { w: 672, h: 240 };
  const port = { w: 900, h: 500 };
  let vue = ajuster(monde, port);
  const port$ = fauxPort();
  creerGestes(port$, {
    zoomer: (sens, p) => (vue = zoomer(vue, sens, p, monde, port)),
    deplacer: (dx, dy) => (vue = deplacer(vue, dx, dy, monde, port)),
    toutVoir: () => (vue = ajuster(monde, port)),
    clic: () => {},
  });
  let t = 0;
  for (let i = 0; i < 4000; i++) {
    t += Math.floor(hasard() * 300);
    const id = 1 + Math.floor(hasard() * 2);
    const x = Math.floor(hasard() * 1300) - 50;
    const y = Math.floor(hasard() * 800) - 50;
    const r = hasard();
    if (r < 0.2) {
      port$.dispatchEvent(evt('pointerdown', { pointerId: id, clientX: x, clientY: y }));
    } else if (r < 0.5) {
      port$.dispatchEvent(evt('pointermove', { pointerId: id, clientX: x, clientY: y }));
    } else if (r < 0.6) {
      port$.dispatchEvent(evt('pointerup', { pointerId: id, clientX: x, clientY: y }));
    } else if (r < 0.8) {
      const deltaY = Math.floor(hasard() * 400) - 200;
      port$.dispatchEvent(evt('wheel', { timeStamp: t, deltaY, ctrlKey: hasard() < 0.3, clientX: x, clientY: y }));
    } else if (r < 0.9) {
      port$.dispatchEvent(evt('click', { clientX: x, clientY: y }));
    } else if (r < 0.95) {
      port$.dispatchEvent(evt('dblclick', { clientX: x, clientY: y }));
    } else {
      port$.dispatchEvent(evt('pointercancel', { pointerId: id, clientX: x, clientY: y }));
    }
    assert.ok(Number.isInteger(vue.echelle) && vue.echelle >= 1 && vue.echelle <= 6, `échelle ${vue.echelle} à l’évènement ${i}`);
    assert.ok(Number.isInteger(vue.x) && Number.isInteger(vue.y), `décalage non entier à l’évènement ${i}`);
    if (monde.w * vue.echelle > port.w) {
      assert.ok(vue.x <= 0 && vue.x >= port.w - monde.w * vue.echelle, `étage sorti du port en x à l’évènement ${i}`);
    }
    if (monde.h * vue.echelle > port.h) {
      assert.ok(vue.y <= 0 && vue.y >= port.h - monde.h * vue.echelle, `étage sorti du port en y à l’évènement ${i}`);
    }
  }
});
