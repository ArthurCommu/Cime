// Source alimentée par la page (un seul EventSource dans l'application) : que des GET, ligne de base, transitions, statuts.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { creerSourceAlimentee } from '../../../src/cime/scene/static/source-alimentee.js';

const pause = async (n = 8) => {
  for (let i = 0; i < n; i++) await new Promise((r) => setTimeout(r, 0));
};

function fauxFetch(reponse) {
  const appels = [];
  const f = async (url, opts = {}) => {
    appels.push({ url, methode: opts.method ?? 'GET' });
    const r = await reponse(url);
    if (r?.statut) return { ok: false, status: r.statut, json: async () => ({}) };
    return { ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(r)) };
  };
  return { fetch: f, appels };
}

const ETAT_1 = { version: '2', agents: [{ id: 'coord-a', etat: 'travaille' }], equipes: [], flux: [], age_ms: 3 };
const ETAT_2 = { version: '2', agents: [{ id: 'coord-a', etat: 'arrete' }], equipes: [], flux: [] };
const hote = (url) => {
  if (url === '/api/flux?depuis=') return { requetes: [], dernier_id: 7 };
  if (url === '/api/flux?depuis=7') {
    return { transitions: [{ id: 8, message_id: 'msg-1', etat: 'livre', de: 'coord-a', a: 'assistant', nature: 'x' }], dernier_id: 8 };
  }
  if (url === '/api/flux?depuis=8') return { transitions: [], dernier_id: 8 };
  throw new Error(`pas prévu : ${url}`);
};

test('premier instantané : sans age_ms, reset, aucune transition historique, statut connecte', async () => {
  const { fetch, appels } = fauxFetch(hote);
  const recus = [];
  const statuts = [];
  const source = creerSourceAlimentee({ fetch, maintenant: () => 42 });
  source.abonner((...a) => recus.push(a), { surStatut: (s) => statuts.push(s) });
  source.pousser(ETAT_1);
  await pause();
  assert.equal(recus.length, 1);
  const [etat, trs, t, opts] = recus[0];
  assert.equal('age_ms' in etat, false);
  assert.deepEqual(trs, []);
  assert.equal(t, 42);
  assert.deepEqual(opts, { reset: true });
  assert.equal(statuts.at(-1), 'connecte');
  assert.deepEqual(appels.map((a) => a.url), ['/api/flux?depuis=']);
});

test('instantanés suivants : les transitions nouvelles, dans l’ordre, sans reset', async () => {
  const { fetch, appels } = fauxFetch(hote);
  const recus = [];
  const source = creerSourceAlimentee({ fetch });
  source.abonner((...a) => recus.push(a));
  source.pousser(ETAT_1);
  source.pousser(ETAT_2);
  source.pousser(ETAT_2);
  await pause();
  assert.equal(recus.length, 3);
  assert.deepEqual(recus[1][1], [{ id: 'msg-1', etat: 'livre', de: 'coord-a', a: 'assistant' }]);
  assert.deepEqual(recus[1][3], { reset: false });
  assert.deepEqual(recus[2][1], []);
  assert.deepEqual(appels.map((a) => a.url), ['/api/flux?depuis=', '/api/flux?depuis=7', '/api/flux?depuis=8']);
});

test('lecture seule : que des GET, aucun EventSource ouvert', async () => {
  const { fetch, appels } = fauxFetch(hote);
  const source = creerSourceAlimentee({ fetch });
  source.abonner(() => {});
  source.pousser(ETAT_1);
  source.pousser(ETAT_2);
  await pause();
  assert.ok(appels.length >= 2);
  assert.ok(appels.every((a) => a.methode === 'GET'));
  assert.equal(source.avancerA(1000), undefined, 'le direct n’est pas avancé par la boucle');
});

test('instantané poussé avant l’abonnement de la scène : rejoué à l’abonnement', async () => {
  const { fetch } = fauxFetch(hote);
  const source = creerSourceAlimentee({ fetch });
  source.pousser(ETAT_1);
  const recus = [];
  source.abonner((...a) => recus.push(a));
  await pause();
  assert.equal(recus.length, 1);
  assert.deepEqual(recus[0][3], { reset: true });
});

test('ligne de base impossible : l’état de la page est montré, sans transition inventée, et le défaut est signalé', async () => {
  const { fetch } = fauxFetch(() => ({ statut: 503 }));
  const recus = [];
  const statuts = [];
  const source = creerSourceAlimentee({ fetch });
  source.abonner((...a) => recus.push(a), { surStatut: (s) => statuts.push(s) });
  source.pousser(ETAT_1);
  await pause();
  assert.equal(recus.length, 1);
  assert.deepEqual(recus[0][1], []);
  assert.equal(statuts.at(-1), 'transitions-indisponibles');
});

test('transitions illisibles : le nouvel instantané est montré quand même, le défaut est signalé', async () => {
  let n = 0;
  const { fetch } = fauxFetch((url) => (n++ === 0 ? hote(url) : { statut: 500 }));
  const recus = [];
  const statuts = [];
  const source = creerSourceAlimentee({ fetch });
  source.abonner((...a) => recus.push(a), { surStatut: (s) => statuts.push(s) });
  source.pousser(ETAT_1);
  source.pousser(ETAT_2);
  await pause();
  assert.equal(recus.length, 2);
  assert.deepEqual(recus[1][1], []);
  assert.equal(statuts.at(-1), 'transitions-indisponibles');
});

test('arreter : plus rien n’est émis, même pour une lecture en cours', async () => {
  const { fetch } = fauxFetch(hote);
  const recus = [];
  const source = creerSourceAlimentee({ fetch });
  source.abonner((...a) => recus.push(a));
  source.pousser(ETAT_1);
  source.arreter();
  source.pousser(ETAT_2);
  await pause();
  assert.deepEqual(recus, []);
});
