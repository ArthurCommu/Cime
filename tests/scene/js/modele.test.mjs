// Trajets d'enveloppe (animations 11 à 15), facteur (16), porte (17), sirène (21), statut des pièces (24),
// évènements (9, 10, 20 et les ordres), plafond de 30 enveloppes animées, et règle du rouge sur l'instantané d'exemple.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { disposition } from '../../../src/cime/scene/static/plan.js';
import { construireScene, creerFil, appliquerSnapshot, sceneA, evenements, MAX_ANIMEES, ETAPE_MS, DUREE_CLOS_MS } from '../../../src/cime/scene/static/modele.js';

const ICI = dirname(fileURLToPath(import.meta.url));
const FIXTURE = join(ICI, '..', 'fixtures', 'etat-exemple.json');

const etatExemple = () => JSON.parse(readFileSync(FIXTURE, 'utf8'));
const base = () => ({
  version: 2,
  agents: [
    { id: 'assistant', role: 'assistant', equipe: null, vivant: true, etat: 'travaille', tache: null, contexte: null, cout_usd_estime: null, brouillon: null },
    { id: 'coord-a', role: 'coordinateur', equipe: 'a', vivant: true, etat: 'au_repos', tache: null, contexte: null, cout_usd_estime: null, brouillon: null },
    { id: 'coord-b', role: 'coordinateur', equipe: 'b', vivant: true, etat: 'au_repos', tache: null, contexte: null, cout_usd_estime: null, brouillon: null },
    { id: 'utilisateur', role: 'utilisateur', equipe: null, vivant: null, etat: 'inconnu', tache: null, contexte: null, cout_usd_estime: null, brouillon: null },
  ],
  equipes: [{ nom: 'a', statut: 'active' }, { nom: 'b', statut: 'au_repos' }],
  flux: [],
  ordres: [],
  alarmes: [],
  aretes: [],
  attentes_utilisateur: [],
  facteur: { battement: 'x', age_s: 1, arrete: false },
});
const message = (over) => ({ id: 1, de: 'coord-a', a: 'coord-b', nature: 'question', etat: 'inscrit', transitions: [], ...over });
const enveloppe = (scene, id) => scene.enveloppes.find((e) => e.id === id);

test('animation 11 : inscrit → enveloppe née sur le bureau de l’expéditeur', () => {
  const scene = construireScene({ ...base(), flux: [message({ etat: 'inscrit' })] });
  const e = enveloppe(scene, 1);
  const bureau = disposition(base()).pointBureau('coord-a'); // le bureau, pas le personnage
  assert.equal(e.sprite, 'enveloppe.inscrit');
  assert.equal(e.raison, 11);
  assert.equal(e.x, bureau.x);
  assert.equal(e.y, bureau.y);
  assert.equal(e.animee, false);
});

test('animations 12 à 14 : livre (animé), pris en compte, puis clos (disparaît après le tampon)', () => {
  const fil = creerFil();
  const e0 = base();
  appliquerSnapshot(fil, e0, [], 0);
  const e1 = base();
  e1.flux = [message({ etat: 'livre' })];
  appliquerSnapshot(fil, e1, [{ id: 1, etat: 'livre', de: 'coord-a', a: 'coord-b' }], 1000);

  const pendant = sceneA(fil, 2000);
  assert.equal(enveloppe(pendant, 1).raison, 12);
  assert.equal(enveloppe(pendant, 1).animee, true);
  assert.equal(pendant.facteur.sprite.startsWith('perso.facteur.marche_'), true, 'le facteur marche pendant le trajet');
  assert.equal(pendant.facteur.raison, 16);

  const e2 = base();
  e2.flux = [message({ etat: 'pris_en_compte' })];
  appliquerSnapshot(fil, e2, [{ id: 1, etat: 'pris_en_compte', de: 'coord-a', a: 'coord-b' }], 1000 + 20000);
  const apres = sceneA(fil, 1000 + 20000);
  assert.equal(enveloppe(apres, 1).raison, 13);
  assert.equal(enveloppe(apres, 1).animee, false, 'posée, sans animer');

  const e3 = base();
  e3.flux = [message({ etat: 'clos' })];
  appliquerSnapshot(fil, e3, [{ id: 1, etat: 'clos', de: 'coord-a', a: 'coord-b' }], 40000);
  assert.equal(enveloppe(sceneA(fil, 40000), 1)?.raison, 14, 'tamponnée pendant le tampon');
  assert.equal(enveloppe(sceneA(fil, 40000 + DUREE_CLOS_MS), 1), undefined, 'puis disparue');
});

test('animation 15 : échec et abandon → tombé au sol, sans disparaître ; gris, et rouge seulement avec une alarme grave livraison_echouee', () => {
  for (const etat of ['echec', 'abandonne']) {
    const e = base();
    e.flux = [message({ etat })];
    const env = enveloppe(construireScene(e), 1);
    assert.equal(env.couleur, 'gris', etat);
    assert.equal(env.raison, 15, etat);
    e.alarmes = [{ id: 'livraison_echouee:b:msg-1', type: 'livraison_echouee', gravite: 'grave', agents: [], equipes: [] }];
    const rouge = enveloppe(construireScene(e), 1);
    assert.equal(rouge.couleur, 'rouge', `${etat} avec alarme`);
    assert.equal(rouge.raison, 15, etat);
  }
});

test('animation 16 : facteur arrêté → rouge, à son point de départ', () => {
  const e = base();
  e.facteur = { battement: null, age_s: null, arrete: true };
  const scene = construireScene(e);
  assert.equal(scene.facteur.sprite, 'perso.facteur.arrete');
  assert.equal(scene.facteur.couleur, 'rouge');
  assert.equal(scene.facteur.raison, 16);
});

test('animation 16 : facteur sans activité depuis longtemps → dormir ; sinon idle sans ligne', () => {
  const longtemps = construireScene(base(), null, { inactifDepuisMs: 120000 });
  assert.equal(longtemps.facteur.sprite, 'perso.facteur.dormir');
  const court = construireScene(base(), null, { inactifDepuisMs: 1000 });
  assert.equal(court.facteur.sprite, 'perso.facteur.idle');
  assert.equal(court.facteur.raison, null);
});

test('animation 17 : rien → fermée ; seulement des rapports → attente, neutre ; autorisation → à agir, ambre', () => {
  const e = base();
  assert.equal(construireScene(e).porte.etat, 'fermee');
  e.attentes_utilisateur = [{ id: 'msg-1', nature: 'rapport' }];
  const rapport = construireScene(e).porte;
  assert.equal(rapport.etat, 'attente');
  assert.notEqual(rapport.couleur, 'rouge', 'un rapport seul n’allume pas la porte en rouge');
  e.attentes_utilisateur.push({ id: 'perm-1', nature: 'autorisation' });
  const agir = construireScene(e).porte;
  assert.equal(agir.etat, 'agir');
  assert.equal(agir.couleur, 'ambre');
  assert.equal(agir.compteur, 1);
  assert.equal(agir.raison, 17);
});

test('porte : registre en échec (attentes null) → inconnue, grise', () => {
  const e = base();
  e.attentes_utilisateur = null;
  const p = construireScene(e).porte;
  assert.equal(p.etat, 'inconnue');
  assert.equal(p.couleur, 'gris');
});

test('animation 21 : alarme grave de session dans une pièce → sirène rouge dans cette pièce', () => {
  const e = base();
  e.alarmes = [{ id: 'session_disparue:x', type: 'session_disparue', gravite: 'grave', agents: [], equipes: ['a'] }];
  const scene = construireScene(e);
  assert.equal(scene.pieces.find((p) => p.nom === 'a').sirene, 'rouge');
  assert.ok(scene.raisons.includes(21));
});

test('animation 21 : alarme à voir d’un type de sirène → sirène ambre, jamais rouge', () => {
  const e = base();
  e.alarmes = [{ id: 'fige:x', type: 'fige', gravite: 'a_voir', agents: ['coord-a'], equipes: [] }];
  assert.equal(construireScene(e).pieces.find((p) => p.nom === 'a').sirene, 'ambre');
});

test('animation 24 : statut d’équipe → lumière, tamisée, attente (neutre, jamais rouge), grisée ; null → hachurée (non mesuré)', () => {
  const e = base();
  e.equipes = [
    { nom: 'a', statut: 'active' },
    { nom: 'b', statut: 'bloquee' },
    { nom: 'c', statut: 'terminee' },
    { nom: 'd', statut: null },
    { nom: 'e', statut: 'au_repos' },
  ];
  const par = Object.fromEntries(construireScene(e).pieces.map((p) => [p.nom, p]));
  assert.equal(par.a.statut, 'lumiere');
  assert.equal(par.b.statut, 'attend');
  assert.notEqual(par.b.couleur, 'rouge', 'bloquee n’est pas un problème : le rouge est réservé aux alarmes graves');
  assert.equal(par.c.statut, 'grisee');
  assert.equal(par.d.statut, 'hachuree');
  assert.equal(par.e.statut, 'tamisee');
});

test('évènements : arrivée, fin de tâche, sieste, refus ; aucun évènement au premier chargement', () => {
  assert.deepEqual(evenements(null, base()), []);
  const avant = base();
  const apres = base();
  apres.agents.push({ id: 'worker-neuf', role: 'worker', equipe: 'a', vivant: true, etat: 'travaille', tache: 'x' });
  apres.ordres = [{ id: 9, verbe: 'terminer', etat: 'execute', cible: 'coord-a' }, { id: 10, verbe: 'compacter', etat: 'en_file', cible: 'coord-b' }];
  apres.alarmes = [{ id: 'action_refusee:coord-a:5', type: 'action_refusee', agents: ['coord-a'] }];
  const types = evenements(avant, apres).map((ev) => `${ev.type}:${ev.agent}`);
  assert.ok(types.includes('arrive:worker-neuf'));
  assert.ok(types.includes('fin_tache:coord-a'));
  assert.ok(types.includes('sieste:coord-b'));
  assert.ok(types.includes('refus:coord-a'));
});

test('évènement de fin de tâche : un ouvrier dont la tâche est rendue', () => {
  const avant = base();
  avant.agents.push({ id: 'worker-q', role: 'worker', equipe: 'a', vivant: true, etat: 'travaille', tache: 'x' });
  const apres = structuredClone(avant);
  apres.agents.find((a) => a.id === 'worker-q').tache = null;
  assert.ok(evenements(avant, apres).some((ev) => ev.type === 'fin_tache' && ev.agent === 'worker-q'));
});

test(`plafond : au plus ${MAX_ANIMEES} enveloppes animées ; les autres sont posées sans animer`, () => {
  const fil = creerFil();
  const e0 = base();
  appliquerSnapshot(fil, e0, [], 0);
  const e1 = base();
  e1.flux = Array.from({ length: 40 }, (_, i) => message({ id: 100 + i, de: 'coord-a', a: 'coord-b', etat: 'livre' }));
  appliquerSnapshot(fil, e1, e1.flux.map((m) => ({ id: m.id, etat: 'livre', de: m.de, a: m.a })), 500);
  const scene = sceneA(fil, 900);
  const animees = scene.enveloppes.filter((e) => e.animee).length;
  assert.ok(animees <= MAX_ANIMEES, `animées : ${animees}`);
  assert.equal(animees, MAX_ANIMEES);
  assert.equal(scene.enveloppes.length, 40, 'toutes restent visibles');
});

test('trajet : une enveloppe livrée part du bureau de l’expéditeur et arrive au bureau du destinataire', () => {
  const fil = creerFil();
  appliquerSnapshot(fil, base(), [], 0);
  const e1 = base();
  e1.flux = [message({ etat: 'livre' })];
  appliquerSnapshot(fil, e1, [{ id: 1, etat: 'livre', de: 'coord-a', a: 'coord-b' }], 0);
  const depart = enveloppe(sceneA(fil, 0), 1);
  const plan = disposition(base());
  assert.equal(depart.x, plan.pointBureau('coord-a').x, 'au départ, sur le bureau de l’expéditeur');
  const fin = enveloppe(sceneA(fil, 60 * ETAPE_MS), 1);
  assert.equal(fin.x, plan.pointBureau('coord-b').x);
  assert.equal(fin.y, plan.pointBureau('coord-b').y);
});

test('règle du rouge : sur l’instantané d’exemple, chaque élément rouge a une raison de problème', () => {
  const PROBLEMES = new Set([5, 8, 15, 16, 17, 18, 21, 24]);
  const sources = [etatExemple()];
  for (const etat of sources) {
    const scene = construireScene(etat);
    const rouges = [
      ...scene.agents.filter((a) => a.couleur === 'rouge' || a.halo === 'rouge'),
      ...scene.pieces.filter((p) => p.couleur === 'rouge'),
      ...scene.enveloppes.filter((e) => e.couleur === 'rouge'),
    ];
    if (scene.porte.couleur === 'rouge') rouges.push(scene.porte);
    if (scene.facteur.couleur === 'rouge') rouges.push(scene.facteur);
    assert.ok(rouges.length > 0, 'l’exemple a des problèmes à montrer');
    for (const r of rouges) {
      const raisons = r.raisons ?? [r.raison];
      assert.ok(raisons.some((n) => PROBLEMES.has(n)), `rouge sans problème : ${JSON.stringify(r).slice(0, 120)}`);
    }
  }
});
