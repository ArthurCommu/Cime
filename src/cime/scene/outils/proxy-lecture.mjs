#!/usr/bin/env node
// proxy-lecture.mjs — proxy de développement de la scène. Sert static/ et relaie vers l'hôte seulement
// les lectures du direct : GET /api/etat, GET /api/flux (SSE), GET /api/flux?depuis=<entier ou vide>.
// Toute autre méthode → 405 ; tout autre chemin de l'API → 404 : un POST /api/journal n'atteint jamais l'hôte.
// Écoute sur 127.0.0.1 seulement. Sans dépendance.
// Usage : node src/cime/scene/outils/proxy-lecture.mjs --hote http://127.0.0.1:<port> [--port 8791]
//   puis ouvrir http://127.0.0.1:8791/

import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { dirname, extname, join, resolve, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ICI = dirname(fileURLToPath(import.meta.url));
const STATIC = join(ICI, '..', 'static');
export const HOTE_LOCAL = '127.0.0.1';
export const PORT_DEFAUT = 8791;
const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
};

// Le chemin relayé vers l'hôte, ou null si la requête n'est pas une lecture du direct.
function cibleDuDirect(url) {
  if (url.pathname === '/api/etat' && url.search === '') return '/api/etat';
  if (url.pathname !== '/api/flux') return null;
  if (url.search === '') return '/api/flux';
  const cles = [...url.searchParams.keys()];
  const depuis = url.searchParams.get('depuis');
  if (cles.length === 1 && cles[0] === 'depuis' && /^\d*$/.test(depuis)) return `/api/flux?depuis=${depuis}`;
  return null;
}

function relayer(chemin, req, res, hote) {
  const amont = http.request(
    { hostname: hote.hostname, port: hote.port, path: chemin, method: 'GET', headers: { accept: req.headers.accept ?? '*/*' } },
    (r) => {
      res.writeHead(r.statusCode ?? 502, {
        'content-type': r.headers['content-type'] ?? 'application/json; charset=utf-8',
        'cache-control': 'no-store',
      });
      r.pipe(res);
    },
  );
  amont.on('error', () => {
    if (!res.headersSent) res.writeHead(502);
    res.end();
  });
  // Le client part (ou le SSE se ferme) : on coupe l'amont avec lui.
  res.on('close', () => amont.destroy());
  amont.end();
}

async function servirStatique(pathname, res) {
  try {
    const relatif = pathname === '/' ? 'index.html' : decodeURIComponent(pathname.slice(1));
    const chemin = resolve(STATIC, relatif);
    if (!chemin.startsWith(STATIC + sep)) throw new Error('hors de static/');
    const contenu = await readFile(chemin);
    res.writeHead(200, { 'content-type': TYPES[extname(chemin)] ?? 'application/octet-stream', 'cache-control': 'no-store' });
    res.end(contenu);
  } catch {
    res.writeHead(404);
    res.end();
  }
}

export function creerProxy({ hote }) {
  const adresse = new URL(hote);
  return http.createServer((req, res) => {
    if (req.method !== 'GET') {
      res.writeHead(405, { allow: 'GET' });
      res.end();
      return;
    }
    const url = new URL(req.url, 'http://local');
    if (url.pathname.startsWith('/api/')) {
      const cible = cibleDuDirect(url);
      if (cible === null) {
        res.writeHead(404);
        res.end();
        return;
      }
      relayer(cible, req, res, adresse);
      return;
    }
    servirStatique(url.pathname, res);
  });
}

// Démarre le proxy sur 127.0.0.1 (jamais 0.0.0.0) ; port 0 = port libre (tests).
export function demarrer({ hote, port = PORT_DEFAUT }) {
  const serveur = creerProxy({ hote });
  return new Promise((ok, ko) => {
    serveur.once('error', ko);
    serveur.listen(port, HOTE_LOCAL, () => ok(serveur));
  });
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  const args = process.argv.slice(2);
  const valeur = (nom, defaut) => (args.includes(nom) ? args[args.indexOf(nom) + 1] : defaut);
  const hote = valeur('--hote', null);
  if (!hote) {
    console.error('usage : proxy-lecture.mjs --hote http://127.0.0.1:<port> [--port 8791]');
    process.exit(2);
  }
  const port = Number(valeur('--port', PORT_DEFAUT));
  await demarrer({ hote, port });
  console.log(`proxy de lecture : http://${HOTE_LOCAL}:${port} → ${hote} (GET seulement)`);
}
