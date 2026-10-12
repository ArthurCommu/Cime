// Le rouge d'une pièce a toujours sa cause visible (rendu.js, causeDePiece) ; sinon « ? » rouge. Le scénario d’essai dérive le statut d'une équipe comme le fait l'hôte.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { ATLAS } from '../../../src/cime/scene/static/graphismes/atlas.js';
import { creerSourceRejouee } from './support/source-rejouee.mjs';
import { creerFil, appliquerSnapshot, sceneA, construireScene } from '../../../src/cime/scene/static/modele.js';
import { dessiner, causeDePiece } from '../../../src/cime/scene/static/rendu.js';
import { DUREE_MS, PAS, statutEquipe } from './support/scenario.mjs';

const ICI = dirname(fileURLToPath(import.meta.url));
const FIXTURE = join(ICI, '..', 'fixtures', 'etat-exemple.json');
const initial = () => JSON.parse(readFileSync(FIXTURE, 'utf8'));

class Espion {
  constructor() { this.boites = []; }
  rect() {}
  texte() {}
  sprite(nom, frame, x, y) { this.boites.push({ nom, x, y }); }
}
const dessinee = (scene, t = 0) => {
  const e = new Espion();
  dessiner(e, ATLAS, scene, t);
  // hors de la légende, qui montre elle-même ce signe
  return e.boites.filter((b) => b.nom === 'alerte.cause_inconnue' && b.y < scene.hauteurEtage);
};

// Chaque instantané du scénario, à chaque étape et toutes les 500 ms : état + scène.
function boucle() {
  const source = creerSourceRejouee({ etatInitial: initial() });
  const fil = creerFil();
  source.abonner((etat, trs, t, { reset }) => appliquerSnapshot(fil, etat, trs, t, { reset }));
  const temps = new Set([...PAS.map((p) => p.t), ...PAS.map((p) => p.t + 1)]);
  for (let t = 0; t < DUREE_MS; t += 500) temps.add(t);
  const vues = [];
  for (const t of [...temps].sort((a, b) => a - b)) {
    source.avancerA(t);
    vues.push({ t, etat: fil.etat, scene: sceneA(fil, t) });
  }
  return vues;
}

test('à chaque étape du scénario, le statut de chaque équipe est celui qui se dérive de ses agents', () => {
  for (const { t, etat } of boucle()) {
    for (const eq of etat.equipes) assert.equal(eq.statut, statutEquipe(etat, eq), `t=${t} : équipe ${eq.nom}`);
  }
});

test('sur toute la boucle : une pièce n’est rouge que si une alarme grave nomme son équipe ; « bloquee » reste neutre', () => {
  let bloquees = 0;
  for (const { t, etat, scene } of boucle()) {
    for (const p of scene.pieces.filter((q) => q.couleur === 'rouge')) {
      assert.ok(etat.alarmes.some((a) => a.gravite === 'grave' && (a.equipes ?? []).includes(p.nom)), `t=${t} : la pièce « ${p.nom} » est rouge sans alarme grave`);
      assert.ok(['attente', 'halo', 'sirene', 'inconnue'].includes(causeDePiece(p, scene.agents)));
    }
    for (const eq of etat.equipes.filter((q) => q.statut === 'bloquee')) {
      const p = scene.pieces.find((q) => q.nom === eq.nom);
      if (p.statut !== 'rouge') {
        bloquees++;
        assert.equal(p.statut, 'attend', `t=${t} : ${eq.nom}`);
      }
    }
  }
  assert.ok(bloquees > 0, 'le scénario doit montrer des équipes en attente');
});

test('la pièce « page » n’est plus rouge sans cause à 30 s et 60 s', () => {
  const vues = boucle();
  for (const t of [30000, 60000]) {
    const { scene } = vues.find((v) => v.t === t);
    const page = scene.pieces.find((p) => p.nom === 'page');
    assert.notEqual(page.statut, 'rouge', `t=${t}`);
  }
  const { scene } = vues.find((v) => v.t === 36000);
  void scene;
});

// État minimal : une équipe « bloquee » dont aucun agent n'attend.
const bloqueeSans = (agents, alarmes = []) => ({
  equipes: [{ nom: 'x', statut: 'bloquee' }],
  agents: agents.map((a, i) => ({ id: `coord-x${i}`, role: 'coordinateur', equipe: 'x', vivant: true, etat: 'travaille', contexte: null, ...a })),
  alarmes,
});

test('une pièce rouge par une alarme grave dont rien ne dit la cause : « ? » rouge dans l’en-tête, sans rien deviner', () => {
  const scene = construireScene({ ...bloqueeSans([{}], [{ id: 'g', type: 'recouvrement', gravite: 'grave', agents: [], equipes: ['x'] }]), equipes: [{ nom: 'x', statut: 'active' }] }, null, { t: 0 });
  const p = scene.pieces.find((q) => q.nom === 'x');
  assert.equal(p.statut, 'rouge');
  assert.equal(causeDePiece(p, scene.agents), 'inconnue');
  const signes = dessinee(scene);
  assert.equal(signes.length, 1);
  const s = ATLAS.sprites['alerte.cause_inconnue'];
  assert.ok(signes[0].x >= p.entete.x && signes[0].x + s.w <= p.entete.x + p.entete.w && signes[0].y >= p.entete.y && signes[0].y + s.h <= p.entete.y + p.entete.h, 'dans l’en-tête de la pièce');
  assert.equal(scene.agents.some((a) => a.halo || a.bulle === 'exclamation' || a.bulle === 'question'), false, 'aucune cause inventée');
});

test('une équipe bloquée : ni pièce rouge ni « ? » ; une alarme grave qui nomme un agent donne un halo à l’agent, pas à la pièce', () => {
  const attente = construireScene(bloqueeSans([{ etat: 'attend_reponse' }]), null, { t: 0 });
  assert.equal(causeDePiece(attente.pieces.find((q) => q.nom === 'x'), attente.agents), null);
  assert.equal(dessinee(attente).length, 0);

  const halo = construireScene(
    bloqueeSans([{}], [{ id: 'a', type: 'bloque_au_demarrage', gravite: 'grave', agents: ['coord-x0'], equipes: ['x'] }]),
    null,
    { t: 0 },
  );
  assert.equal(halo.agents[0].halo, 'rouge');
  assert.notEqual(halo.pieces.find((q) => q.nom === 'x').couleur, 'rouge');
  assert.equal(dessinee(halo).length, 0);
});

test('une pièce rouge par une alarme grave qui ne nomme que l’équipe : expliquée par sa seule sirène', () => {
  const sans = construireScene({ ...bloqueeSans([{ etat: 'attend_reponse' }]), equipes: [{ nom: 'x', statut: 'active' }], alarmes: [{ id: 'g', type: 'recouvrement', gravite: 'grave', agents: [], equipes: ['x'] }] }, null, { t: 0 });
  const p = sans.pieces.find((q) => q.nom === 'x');
  assert.equal(p.statut, 'rouge');
  assert.equal(causeDePiece(p, sans.agents), 'inconnue', 'la bulle d’attente n’explique pas cette alarme');
  const avec = construireScene({ ...bloqueeSans([{}]), equipes: [{ nom: 'x', statut: 'active' }], alarmes: [{ id: 'g', type: 'livraison_echouee', gravite: 'grave', agents: [], equipes: ['x'] }] }, null, { t: 0 });
  assert.equal(causeDePiece(avec.pieces.find((q) => q.nom === 'x'), avec.agents), 'sirene');
});

test('une pièce qui n’est pas rouge n’a pas de cause à montrer', () => {
  const scene = construireScene({ equipes: [{ nom: 'x', statut: 'active' }], agents: [{ id: 'coord-x', role: 'coordinateur', equipe: 'x', vivant: true, etat: 'travaille' }], alarmes: [] }, null, { t: 0 });
  assert.equal(causeDePiece(scene.pieces.find((q) => q.nom === 'x'), scene.agents), null);
});
