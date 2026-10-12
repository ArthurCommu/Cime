// Proxy de lecture (outils/proxy-lecture.mjs) devant un faux hôte : relais des GET, SSE, refus du reste, écoute sur 127.0.0.1.
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { demarrer } from '../../../src/cime/scene/outils/proxy-lecture.mjs';

const ICI = dirname(fileURLToPath(import.meta.url));
const SOURCE_PROXY = join(ICI, '..', '..', '..', 'src', 'cime', 'scene', 'outils', 'proxy-lecture.mjs');

const recus = []; // ce que l'hôte a vraiment reçu
let hote;
let proxy;
let baseProxy;
let sseOuvert = null;

function requeteBrute(base, { methode = 'GET', chemin }) {
  return new Promise((ok, ko) => {
    const u = new URL(chemin, base);
    const req = http.request(u, { method: methode }, (res) => {
      let corps = '';
      res.on('data', (d) => (corps += d));
      res.on('end', () => ok({ statut: res.statusCode, type: res.headers['content-type'], corps }));
    });
    req.on('error', ko);
    req.end();
  });
}

before(async () => {
  hote = http.createServer((req, res) => {
    recus.push(`${req.method} ${req.url}`);
    if (req.method === 'GET' && req.url === '/api/etat') {
      res.writeHead(200, { 'content-type': 'application/json' });
      return res.end(JSON.stringify({ version: '2', age_ms: 9 }));
    }
    if (req.method === 'GET' && req.url === '/api/flux') {
      res.writeHead(200, { 'content-type': 'text/event-stream' });
      res.write('event: etat\ndata: {"version":"2"}\n\n');
      sseOuvert = res;
      return;
    }
    if (req.method === 'GET' && req.url === '/api/flux?depuis=3') {
      res.writeHead(200, { 'content-type': 'application/json' });
      return res.end(JSON.stringify({ transitions: [], dernier_id: 3 }));
    }
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end('{}');
  });
  await new Promise((r) => hote.listen(0, '127.0.0.1', r));
  const adresseHote = `http://127.0.0.1:${hote.address().port}`;
  proxy = await demarrer({ hote: adresseHote, port: 0 });
  baseProxy = `http://127.0.0.1:${proxy.address().port}`;
});

after(async () => {
  sseOuvert?.end();
  await new Promise((r) => proxy.close(r));
  await new Promise((r) => hote.close(r));
});

test('le proxy n’écoute que sur 127.0.0.1 (jamais 0.0.0.0)', () => {
  assert.equal(proxy.address().address, '127.0.0.1');
  const code = readFileSync(SOURCE_PROXY, 'utf8')
    .split('\n')
    .filter((l) => !l.trim().startsWith('//'))
    .join('\n');
  assert.equal(code.includes('0.0.0.0'), false, 'aucune adresse « toutes interfaces » dans le code');
  assert.equal(code.includes("'::'"), false);
  assert.match(code, /serveur\.listen\(port, HOTE_LOCAL,/, 'listen reçoit toujours 127.0.0.1 explicitement');
});

test('GET /api/etat est relayé tel quel', async () => {
  const r = await requeteBrute(baseProxy, { chemin: '/api/etat' });
  assert.equal(r.statut, 200);
  assert.deepEqual(JSON.parse(r.corps), { version: '2', age_ms: 9 });
  assert.ok(recus.includes('GET /api/etat'));
});

test('GET /api/flux (SSE) est relayé : le premier évènement arrive', async () => {
  const corps = await new Promise((ok, ko) => {
    const req = http.get(new URL('/api/flux', baseProxy), (res) => {
      assert.equal(res.headers['content-type'], 'text/event-stream');
      let tampon = '';
      res.on('data', (d) => {
        tampon += d;
        if (tampon.includes('\n\n')) {
          req.destroy();
          ok(tampon);
        }
      });
    });
    req.on('error', (e) => {
      if (e.code !== 'ECONNRESET') ko(e);
    });
  });
  assert.match(corps, /event: etat/);
  assert.ok(recus.includes('GET /api/flux'));
});

test('GET /api/flux?depuis=<entier> est relayé', async () => {
  const r = await requeteBrute(baseProxy, { chemin: '/api/flux?depuis=3' });
  assert.equal(r.statut, 200);
  assert.equal(JSON.parse(r.corps).dernier_id, 3);
  assert.ok(recus.includes('GET /api/flux?depuis=3'));
});

test('GET /api/flux?depuis= (vide) est relayé à l’hôte sous la même forme', async () => {
  const avant = recus.length;
  await requeteBrute(baseProxy, { chemin: '/api/flux?depuis=' });
  assert.ok(recus.slice(avant).includes('GET /api/flux?depuis='));
});

test('méthodes autres que GET → 405, et l’hôte ne reçoit rien', async () => {
  const avant = recus.length;
  for (const [methode, chemin] of [
    ['POST', '/api/etat'],
    ['DELETE', '/api/flux'],
    ['POST', '/api/journal?limite=1'],
    ['PUT', '/api/flux?depuis=3'],
    ['POST', '/'],
  ]) {
    const r = await requeteBrute(baseProxy, { methode, chemin });
    assert.equal(r.statut, 405, `${methode} ${chemin}`);
  }
  assert.deepEqual(recus.slice(avant), []);
});

test('chemins hors lecture du direct → 404, et l’hôte ne les voit pas', async () => {
  const avant = recus.length;
  for (const chemin of ['/api/journal?limite=100', '/api/agents/coord-a/terminal', '/api/fichier?chemin=x', '/api/flux?depuis=3&x=1', '/api/flux?depuis=abc', '/api/etat?x=1']) {
    const r = await requeteBrute(baseProxy, { chemin });
    assert.equal(r.statut, 404, chemin);
  }
  assert.deepEqual(recus.slice(avant), []);
});

test('la page statique est servie, et rien hors de static/ ne l’est (traversée de chemin)', async () => {
  const page = await requeteBrute(baseProxy, { chemin: '/' });
  assert.equal(page.statut, 200);
  assert.match(page.corps, /<!doctype html>/i);
  assert.match(page.type, /text\/html/);
  const hors = await requeteBrute(baseProxy, { chemin: '/..%2Foutils%2Fproxy-lecture.mjs' });
  assert.equal(hors.statut, 404);
  assert.equal(hors.corps.includes('creerProxy'), false);
});
