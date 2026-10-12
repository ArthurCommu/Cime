// Source du direct (faux fetch, faux EventSource) : lecture seule, ligne de base, transitions, statuts, arrêt.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { creerSourceDirecte } from '../../../src/cime/scene/static/source-directe.js';

const tick = () => new Promise((r) => setTimeout(r, 0));
const pause = async (n = 8) => {
  for (let i = 0; i < n; i++) await tick();
};

// Faux fetch : `reponse(url)` rend le corps, ou lance une erreur (réseau), ou rend { statut } (ex. 503).
// Toutes les méthodes sont consignées : le test de lecture seule échoue sur toute autre chose que GET.
function fauxFetch(reponse) {
  const appels = [];
  const f = async (url, opts = {}) => {
    const methode = opts.method ?? 'GET';
    appels.push({ url, methode });
    const r = await reponse(url, methode);
    if (r?.statut) return { ok: false, status: r.statut, json: async () => ({}) };
    return { ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(r)) };
  };
  return { fetch: f, appels };
}

// Faux EventSource : les instances sont gardées, les évènements se déclenchent à la main.
function fauxEventSource() {
  const instances = [];
  class FauxES {
    constructor(url) {
      this.url = url;
      this.ecoute = {};
      this.fermee = false;
      this.onopen = null;
      this.onerror = null;
      instances.push(this);
    }
    addEventListener(type, fn) {
      (this.ecoute[type] ??= []).push(fn);
    }
    emettre(type, data) {
      for (const fn of this.ecoute[type] ?? []) fn({ data });
    }
    close() {
      this.fermee = true;
    }
  }
  return { EventSource: FauxES, instances };
}

// Planificateur contrôlé : la reprise ne part que si le test la déclenche.
function fauxPlanificateur() {
  const attente = [];
  return {
    planifier: (f) => {
      attente.push(f);
      return attente.length;
    },
    annuler: (id) => {
      attente[id - 1] = null;
    },
    declencher() {
      const f = attente.find(Boolean);
      attente.splice(attente.indexOf(f), 1, null);
      f?.();
    },
    attente,
  };
}

const ETAT_1 = { version: '2', agents: [{ id: 'coord-a', etat: 'travaille' }], equipes: [], flux: [], age_ms: 3 };
const ETAT_2 = { version: '2', agents: [{ id: 'coord-a', etat: 'arrete' }], equipes: [], flux: [] };
const ETAT_3 = { version: '2', agents: [], equipes: [], flux: [] };

// Faux hôte de base : baseline à 7, une transition au premier événement, aucune au second.
function hoteNormal() {
  return (url) => {
    if (url === '/api/flux?depuis=') return { requetes: [], dernier_id: 7 };
    if (url === '/api/etat') return ETAT_1;
    if (url === '/api/flux?depuis=7') {
      return {
        transitions: [{ id: 8, message_id: 'msg-1', etat: 'livre', horodatage: 'x', voie: null, auteur: 'coord-a', de: 'coord-a', a: 'assistant', nature: 'compte_rendu', objet: null }],
        dernier_id: 8,
      };
    }
    if (url === '/api/flux?depuis=8') return { transitions: [], dernier_id: 8 };
    throw new Error(`pas prévu : ${url}`);
  };
}

test('ligne de base : instantané sans age_ms, reset, aucune transition historique, statut connecte', async () => {
  const { fetch, appels } = fauxFetch(hoteNormal());
  const { EventSource, instances } = fauxEventSource();
  const recus = [];
  const statuts = [];
  const source = creerSourceDirecte({ fetch, EventSource, maintenant: () => 42 });
  source.abonner((...args) => recus.push(args), { surStatut: (s) => statuts.push(s) });
  await pause();
  assert.equal(recus.length, 1);
  const [etat, trs, t, opts] = recus[0];
  assert.deepEqual(etat, { version: '2', agents: [{ id: 'coord-a', etat: 'travaille' }], equipes: [], flux: [] });
  assert.equal('age_ms' in etat, false);
  assert.deepEqual(trs, []);
  assert.equal(t, 42);
  assert.deepEqual(opts, { reset: true });
  assert.equal(statuts.at(-1), 'connecte');
  assert.equal(instances.length, 1);
  assert.equal(instances[0].url, '/api/flux');
  assert.ok(appels.some((a) => a.url === '/api/flux?depuis='));
  assert.ok(appels.some((a) => a.url === '/api/etat'));
});

test('deux évènements SSE : transitions lues depuis la ligne de base, puis depuis le dernier id rendu', async () => {
  const { fetch, appels } = fauxFetch(hoteNormal());
  const { EventSource, instances } = fauxEventSource();
  const recus = [];
  const source = creerSourceDirecte({ fetch, EventSource });
  source.abonner((...args) => recus.push(args));
  await pause();
  instances[0].emettre('etat', JSON.stringify(ETAT_2));
  await pause();
  instances[0].emettre('etat', JSON.stringify(ETAT_3));
  await pause();

  assert.equal(recus.length, 3);
  assert.deepEqual(recus[1][1], [{ id: 'msg-1', etat: 'livre', de: 'coord-a', a: 'assistant' }]);
  assert.deepEqual(recus[1][3], { reset: false });
  assert.deepEqual(recus[2][1], []);
  assert.deepEqual(recus[2][3], { reset: false });
  // Pas d'historique : la première lecture de transitions part de la ligne de base (7), pas de 0 ni d'une absence.
  const depuis = appels.filter((a) => a.url.startsWith('/api/flux?depuis=')).map((a) => a.url);
  assert.deepEqual(depuis, ['/api/flux?depuis=', '/api/flux?depuis=7', '/api/flux?depuis=8']);
});

test('les lectures de transitions se font une à la fois, dans l’ordre (le second évènement attend le premier)', async () => {
  let liberer = null;
  const { fetch, appels } = fauxFetch(async (url) => {
    if (url === '/api/flux?depuis=7') {
      await new Promise((r) => (liberer = r));
      return { transitions: [], dernier_id: 9 };
    }
    return hoteNormal()(url);
  });
  const { EventSource, instances } = fauxEventSource();
  const source = creerSourceDirecte({ fetch, EventSource });
  source.abonner(() => {});
  await pause();
  instances[0].emettre('etat', JSON.stringify(ETAT_2));
  instances[0].emettre('etat', JSON.stringify(ETAT_3));
  await pause();
  assert.equal(appels.filter((a) => a.url === '/api/flux?depuis=8').length, 0, 'pas encore : la première lecture est en cours');
  liberer();
  await pause();
  assert.ok(appels.some((a) => a.url === '/api/flux?depuis=9'), 'la seconde part du dernier id rendu');
});

test('transitions illisibles : cb(etat, []) avec le statut transitions-indisponibles, jamais « zéro transition » inventée', async () => {
  const { fetch, appels } = fauxFetch((url) => {
    if (url === '/api/flux?depuis=7') return { statut: 503 };
    return hoteNormal()(url);
  });
  const { EventSource, instances } = fauxEventSource();
  const recus = [];
  const statuts = [];
  const source = creerSourceDirecte({ fetch, EventSource });
  source.abonner((...args) => recus.push(args), { surStatut: (s) => statuts.push(s) });
  await pause();
  instances[0].emettre('etat', JSON.stringify(ETAT_2));
  await pause();
  assert.equal(recus.length, 2);
  assert.deepEqual(recus[1][0], { version: '2', agents: [{ id: 'coord-a', etat: 'arrete' }], equipes: [], flux: [] });
  assert.deepEqual(recus[1][1], []);
  assert.deepEqual(recus[1][3], { reset: false });
  assert.equal(statuts.at(-1), 'transitions-indisponibles');
  // La ligne de base n'a pas avancé : le prochain évènement relit depuis 7.
  instances[0].emettre('etat', JSON.stringify(ETAT_3));
  await pause();
  assert.equal(appels.filter((a) => a.url === '/api/flux?depuis=7').length, 2);
});

test('évènement SSE illisible : ignoré, statut evenement-illisible, puis retour à connecte', async () => {
  const { fetch } = fauxFetch(hoteNormal());
  const { EventSource, instances } = fauxEventSource();
  const recus = [];
  const statuts = [];
  const source = creerSourceDirecte({ fetch, EventSource });
  source.abonner((...args) => recus.push(args), { surStatut: (s) => statuts.push(s) });
  await pause();
  instances[0].emettre('etat', '{pas du json');
  await pause();
  assert.equal(recus.length, 1, 'rien de nouveau après un événement illisible');
  assert.equal(statuts.at(-1), 'evenement-illisible');
  instances[0].emettre('etat', JSON.stringify(ETAT_2));
  await pause();
  assert.equal(statuts.at(-1), 'connecte');
});

test('hôte injoignable à la ligne de base : aucun instantané, statut hote-injoignable, pas de SSE ; reprise planifiée', async () => {
  let panne = true;
  const { fetch } = fauxFetch((url) => {
    if (panne) throw new Error('ECONNREFUSED');
    return hoteNormal()(url);
  });
  const { EventSource, instances } = fauxEventSource();
  const plan = fauxPlanificateur();
  const recus = [];
  const statuts = [];
  const source = creerSourceDirecte({ fetch, EventSource, planifier: plan.planifier, annuler: plan.annuler });
  source.abonner((...args) => recus.push(args), { surStatut: (s) => statuts.push(s) });
  await pause();
  assert.equal(recus.length, 0, 'aucun faux étage');
  assert.equal(instances.length, 0);
  assert.equal(statuts.at(-1), 'hote-injoignable');
  assert.equal(plan.attente.filter(Boolean).length, 1, 'une reprise est prévue');

  panne = false;
  plan.declencher();
  await pause();
  assert.equal(recus.length, 1);
  assert.equal(instances.length, 1);
  assert.equal(statuts.at(-1), 'connecte');
});

test('erreur SSE → reconnexion ; réouverture → connecte (EventSource se reconnecte seul)', async () => {
  const { fetch } = fauxFetch(hoteNormal());
  const { EventSource, instances } = fauxEventSource();
  const statuts = [];
  const source = creerSourceDirecte({ fetch, EventSource });
  source.abonner(() => {}, { surStatut: (s) => statuts.push(s) });
  await pause();
  instances[0].onerror();
  assert.equal(statuts.at(-1), 'reconnexion');
  instances[0].onopen();
  assert.equal(statuts.at(-1), 'connecte');
  assert.equal(instances.length, 1, 'pas de second EventSource : le même se reconnecte');
});

test('arreter() ferme l’EventSource, annule la reprise, et plus aucun évènement n’est émis', async () => {
  const { fetch } = fauxFetch(hoteNormal());
  const { EventSource, instances } = fauxEventSource();
  const recus = [];
  const source = creerSourceDirecte({ fetch, EventSource });
  source.abonner((...args) => recus.push(args));
  await pause();
  source.arreter();
  assert.equal(instances[0].fermee, true);
  instances[0].emettre('etat', JSON.stringify(ETAT_2));
  await pause();
  assert.equal(recus.length, 1);
});

test('arreter() pendant une lecture en vol : la réponse tardive n’est pas émise', async () => {
  let liberer = null;
  const { fetch } = fauxFetch(async (url) => {
    if (url === '/api/etat') {
      await new Promise((r) => (liberer = r));
      return ETAT_1;
    }
    return hoteNormal()(url);
  });
  const { EventSource, instances } = fauxEventSource();
  const recus = [];
  const source = creerSourceDirecte({ fetch, EventSource });
  source.abonner((...args) => recus.push(args));
  await pause();
  source.arreter();
  liberer();
  await pause();
  assert.equal(recus.length, 0);
  assert.equal(instances.length, 0);
});

test('arreter() annule une reprise planifiée', async () => {
  const { fetch } = fauxFetch(() => {
    throw new Error('ECONNREFUSED');
  });
  const plan = fauxPlanificateur();
  const source = creerSourceDirecte({ fetch, EventSource: class {}, planifier: plan.planifier, annuler: plan.annuler });
  source.abonner(() => {});
  await pause();
  source.arreter();
  assert.equal(plan.attente.filter(Boolean).length, 0);
});

test('toutes les requêtes sont des GET (le faux fetch consigne la méthode)', async () => {
  const { fetch, appels } = fauxFetch((url) => {
    if (url.startsWith('/api/flux?depuis=7')) return { statut: 503 };
    return hoteNormal()(url);
  });
  const { EventSource, instances } = fauxEventSource();
  const source = creerSourceDirecte({ fetch, EventSource });
  source.abonner(() => {}, { surStatut: () => {} });
  await pause();
  instances[0].emettre('etat', JSON.stringify(ETAT_2));
  instances[0].emettre('etat', JSON.stringify(ETAT_3));
  await pause();
  instances[0].onerror();
  source.arreter();
  assert.ok(appels.length >= 4, 'le scénario a bien fait des requêtes');
  const autres = appels.filter((a) => a.methode !== 'GET');
  assert.deepEqual(autres, [], 'aucune écriture');
  const chemins = appels.map((a) => a.url.split('?')[0]);
  assert.ok(chemins.every((c) => c === '/api/etat' || c === '/api/flux'), `chemins hors lecture : ${chemins}`);
});

test('avancerA ne fait rien pour le direct', async () => {
  const { fetch, appels } = fauxFetch(hoteNormal());
  const { EventSource } = fauxEventSource();
  const recus = [];
  const source = creerSourceDirecte({ fetch, EventSource });
  source.abonner((...args) => recus.push(args));
  await pause();
  const avant = appels.length;
  source.avancerA(123456);
  await pause();
  assert.equal(appels.length, avant);
  assert.equal(recus.length, 1);
});
