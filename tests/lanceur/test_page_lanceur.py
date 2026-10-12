"""La page du lanceur (`src/cime/lanceur/page/index.html`) : cartes ouvert/fermé, fermer, rouvrir, conversations, installer.

Le `<script>` de la page est extrait et exécuté sous `node` (module `vm`) avec un faux `document`, `fetch` et `window` écrits ici.
Une seule exécution de node joue tous les scénarios ; chaque test lit sa tranche du résultat.
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

PAGE = Path(__file__).resolve().parents[2] / "src" / "cime" / "lanceur" / "page" / "index.html"
NBSP = " "
NODE = shutil.which("node") or ("/opt/homebrew/bin/node" if os.path.exists("/opt/homebrew/bin/node") else None)

SONDE = r"""
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

const html = readFileSync(process.argv[2], 'utf8');
const script = html.slice(html.indexOf('<script>') + 8, html.lastIndexOf('</script>'));

class Noeud {
  constructor(tag) {
    this.tag = tag; this.children = []; this.parent = null; this.ecouteurs = {}; this.attrs = {};
    this.className = ''; this.disabled = false; this.value = ''; this.open = false; this.type = ''; this.id = ''; this._t = '';
  }
  get textContent() { return this.tag === '#texte' ? this._t : this.children.map((c) => c.textContent).join(''); }
  set textContent(v) { this.vider(); if (v !== '' && v != null) this.ajouter(texteNoeud(String(v))); }
  get classes() { return this.className.split(/\s+/).filter(Boolean); }
  vider() { this.children.forEach((c) => { c.parent = null; }); this.children = []; }
  ajouter(n) { if (n.parent) n.parent.children = n.parent.children.filter((c) => c !== n); n.parent = this; this.children.push(n); return n; }
  appendChild(n) { return this.ajouter(n); }
  append(...xs) { xs.forEach((x) => this.ajouter(typeof x === 'string' ? texteNoeud(x) : x)); }
  replaceChildren(...xs) { this.vider(); this.append(...xs); }
  remove() { if (this.parent) { this.parent.children = this.parent.children.filter((c) => c !== this); this.parent = null; } }
  setAttribute(k, v) { this.attrs[k] = v; }
  addEventListener(t, f) { (this.ecouteurs[t] ||= []).push(f); }
  async emettre(t, ev = {}) { for (const f of this.ecouteurs[t] || []) await f({ preventDefault() {}, ...ev }); }
  clic() { return this.emettre('click'); }
}
const texteNoeud = (t) => { const n = new Noeud('#texte'); n._t = t; return n; };
const sous = (n) => n.children.flatMap((c) => [c, ...sous(c)]);
const trouver = (n, pred) => sous(n).filter((x) => x.tag !== '#texte' && pred(x));
const parClasse = (n, c) => trouver(n, (x) => x.classes.includes(c));
const parTag = (n, t) => trouver(n, (x) => x.tag === t);
const bouton = (n, libelle) => parTag(n, 'button').find((b) => b.textContent === libelle);
const lister = (n) => n.children.map((c) => ({ classes: c.classes, texte: c.textContent }));
const settle = async () => { for (let i = 0; i < 12; i++) await new Promise((r) => setImmediate(r)); };

// maintenant fixé : lundi 12 octobre 2026, 10 h 00 à Paris (TZ=Europe/Paris)
const MAINTENANT = new Date(2026, 9, 12, 10, 0, 0).getTime();

function monter(routes, { popup = true } = {}) {
  const ids = {};
  for (const id of ['liste', 'bandeau', 'n-retour', 'a-retour']) ids[id] = new Noeud('div');
  for (const id of ['n-utilisateur', 'n-parent', 'n-nom', 'n-prefixe', 'a-chemin']) ids[id] = new Noeud('input');
  for (const id of ['n-bouton', 'a-bouton']) { ids[id] = new Noeud('button'); ids[id].textContent = id; }
  for (const id of ['form-nouveau', 'form-ajouter']) ids[id] = new Noeud('form');
  const ecouteursDoc = {};
  const document = {
    visibilityState: 'visible',
    getElementById: (id) => ids[id],
    createElement: (t) => new Noeud(t),
    createRange: () => ({ selectNodeContents() {} }),
    addEventListener: (t, f) => { (ecouteursDoc[t] ||= []).push(f); },
  };
  const journal = [];  // [{route, methode, corps}] puis événements 'open'
  const compteurs = {};
  const minuteurs = [];
  const popups = [];
  const window = { open: (...a) => { journal.push({ evenement: 'open' }); if (!popup) return null; const w = { location: null, ferme: false, close() { this.ferme = true; } }; popups.push(w); return w; } };
  const fetch = async (route, opts = {}) => {
    const methode = opts.method || 'GET';
    const corps = opts.body ? JSON.parse(opts.body) : null;
    journal.push({ route, methode, corps });
    const cle = methode + ' ' + route.split('?')[0];
    compteurs[cle] = (compteurs[cle] || 0) + 1;
    let h = routes[cle];
    if (Array.isArray(h) && Array.isArray(h[0])) h = h[Math.min(compteurs[cle], h.length) - 1];
    const [statut, json] = typeof h === 'function' ? await h(corps, route) : h;
    return { status: statut, json: async () => json };
  };
  const ctx = vm.createContext({ document, window, fetch, navigator: {}, confirm: () => true, console,
    setTimeout: (f, ms) => { const m = { f, ms, annule: false }; minuteurs.push(m); return m; }, clearTimeout: (m) => { if (m) m.annule = true; } });
  vm.runInContext(script, ctx);
  vm.runInContext(`horloge = () => ${MAINTENANT}`, ctx);
  const evalue = (code) => vm.runInContext(code, ctx);
  const visible = async () => { document.visibilityState = 'visible'; for (const f of ecouteursDoc.visibilitychange || []) await f({}); await settle(); };
  const declencher = () => minuteurs.filter((m) => !m.annule && m.ms >= 1000).forEach((m) => { m.annule = true; m.f(); });
  return { ids, document, journal, compteurs, popups, evalue, visible, declencher, minuteurs, ecouteursDoc,
    appels: (cle) => journal.filter((j) => j.methode && j.methode + ' ' + j.route.split('?')[0] === cle) };
}

const ok = (j) => [200, j];
const liste = (projets, utilisateur = 'Camille') => ok({ projets, utilisateur });
const ouvert = (nom) => ({ chemin: '/p/' + nom, nom, etat: 'ouvert', conversations: null });
const ferme = (nom, n) => ({ chemin: '/p/' + nom, nom, etat: 'ferme', conversations: n });
const carte = (m, i = 0) => m.ids.liste.children[i];
const resume = (c) => ({
  nom: parClasse(c, 'nom')[0].children[0].textContent, etat: parClasse(c, 'etat')[0].textContent, etatClasses: parClasse(c, 'etat')[0].classes,
  boutons: parClasse(c, 'actions')[0].children.map((b) => b.textContent), chemin: parClasse(c, 'chemin')[0].textContent,
});
const messagesCarte = (c) => lister(parClasse(c, 'retour-carte')[0]);
const sortie = {};

// ── 1. cartes ──
{
  const m = monter({ 'GET /api/projets': liste([ferme('zeta', 6), ouvert('alpha'), ferme('un', 1), ferme('zero', 0), ferme('nul', null)]) });
  await settle();
  sortie.cartes = { n: m.ids.liste.children.length, cartes: m.ids.liste.children.map(resume) };
  const v = monter({ 'GET /api/projets': liste([]) });
  await settle();
  sortie.vide = v.ids.liste.textContent;
  sortie.pures = {
    etats: [{ etat: 'ouvert', conversations: 3 }, { etat: 'ferme', conversations: 6 }, { etat: 'ferme', conversations: 1 }, { etat: 'ferme', conversations: 0 }, { etat: 'ferme', conversations: null }].map((p) => m.evalue(`libelleEtat(${JSON.stringify(p)})`)),
    noms: ['assistant', 'coord-hote', 'worker-page-x', 'worker-hote-lanceur-page', 'inconnu'].map((a) => m.evalue(`nomLisible(${JSON.stringify(a)})`)),
    dates: [new Date(2026, 9, 12, 22, 14), new Date(2026, 9, 11, 22, 14), new Date(2026, 9, 11, 0, 5), new Date(2026, 9, 10, 18, 40), new Date(2026, 8, 9, 8, 15), new Date(2026, 0, 3, 7, 0), new Date(2026, 11, 31, 23, 59)]
      .map((d) => m.evalue(`dateCourte(${JSON.stringify(d.toISOString())}, ${MAINTENANT})`)),
    dateIllisible: m.evalue(`dateCourte('pas une date', ${MAINTENANT})`),
    maintenantObjet: m.evalue(`dateCourte(${JSON.stringify(new Date(2026, 9, 12, 9, 5).toISOString())}, new Date(${MAINTENANT}))`),
    minuit: m.evalue(`dateCourte(${JSON.stringify(new Date(2026, 9, 12, 0, 0).toISOString())}, ${new Date(2026, 9, 12, 23, 59).getTime()})`),
  };
}

// ── 2. fermer : 200 ──
{
  const m = monter({
    'GET /api/projets': [liste([ouvert('a'), ouvert('b')]), liste([ferme('a', 2), ouvert('b')])],
    'POST /api/projets/fermer': ok({ resultat: 'ok', conversations: [{ agent: 'assistant', session: 's1', tmux: 't1' }, { agent: 'coord-hote', session: 's2', tmux: 't2' }], taches_en_cours: ['hote/route-x'] }),
  });
  await settle();
  const fermer = bouton(carte(m, 0), 'Fermer');
  const p = fermer.clic();
  const pendant = { texte: fermer.textContent, inactif: fermer.disabled, bandeau: m.ids.bandeau.textContent };
  await p; await settle();
  sortie.fermer200 = { pendant, appels: m.appels('POST /api/projets/fermer').map((a) => a.corps), messages: messagesCarte(carte(m, 0)), apres: resume(carte(m, 0)), autre: messagesCarte(carte(m, 1)), bandeau: m.ids.bandeau.textContent };
  const m2 = monter({
    'GET /api/projets': [liste([ouvert('a')]), liste([ferme('a', 1)])],
    'POST /api/projets/fermer': ok({ resultat: 'ok', conversations: [{ agent: 'assistant', session: 's1', tmux: 't1' }], taches_en_cours: ['hote/a', 'hote/b'] }),
  });
  await settle(); await bouton(carte(m2), 'Fermer').clic(); await settle();
  sortie.fermerSingulier = messagesCarte(carte(m2));
  const m3 = monter({ 'GET /api/projets': liste([ouvert('a')]), 'POST /api/projets/fermer': ok({ resultat: 'erreur', message: 'tmux est introuvable' }) });
  await settle(); await bouton(carte(m3), 'Fermer').clic(); await settle();
  sortie.fermerErreur = { messages: messagesCarte(carte(m3)), reactive: !bouton(carte(m3), 'Fermer').disabled };
}

// ── 3. fermer : 409 ──
async function scenario409(occupes) {
  const m = monter({
    'GET /api/projets': [liste([ouvert('a')]), liste([ferme('a', 3)])],
    'POST /api/projets/fermer': [[409, { resultat: 'refuse', occupes, message: 'occupés' }], ok({ resultat: 'ok', conversations: [{}, {}, {}], taches_en_cours: [] })],
  });
  await settle();
  const fermer = bouton(carte(m), 'Fermer');
  await fermer.clic(); await settle();
  const encart = parClasse(carte(m), 'retour-carte')[0].children[0];
  const r = { texte: encart && encart.textContent, classes: encart && encart.classes, fort: encart && parTag(encart, 'strong').map((s) => s.textContent),
    boutons: encart ? parTag(encart, 'button').map((b) => b.textContent) : [], fermerInactif: fermer.disabled, fermerTexte: fermer.textContent,
    classeQuandMeme: encart && bouton(encart, 'Fermer quand même').classes };
  return { m, fermer, encart, r };
}
{
  const t = await scenario409(['assistant', 'coord-hote', 'worker-page-x']);
  sortie.occupes3 = t.r;
  const t1 = await scenario409(['coord-hote']);
  sortie.occupes1 = t1.r;
  const t1w = await scenario409(['worker-page-x']);
  sortie.occupes1w = t1w.r.texte;
  // « Ne pas fermer » : l'encart disparaît, aucun nouvel appel, « Fermer » redevient actif
  const avant = t.m.appels('POST /api/projets/fermer').length;
  await bouton(t.encart, 'Ne pas fermer').clic(); await settle();
  sortie.nePasFermer = { appels: t.m.appels('POST /api/projets/fermer').length - avant, encart: parClasse(carte(t.m), 'retour-carte')[0].children.length, fermerInactif: t.fermer.disabled };
  // « Fermer quand même » : second appel avec forcer:true
  const u = await scenario409(['assistant', 'coord-hote']);
  await bouton(u.encart, 'Fermer quand même').clic(); await settle();
  sortie.quandMeme = { appels: u.m.appels('POST /api/projets/fermer').map((a) => a.corps), messages: messagesCarte(carte(u.m)) };
}

// ── 4. rouvrir ──
const DATE_HIER = new Date(2026, 9, 11, 22, 14).toISOString();
const repOk = (extra = {}) => ({ resultat: 'ok', url: 'http://127.0.0.1:9000/', assistant: 'p-assistant', coordinateurs: ['p-coord-hote'], equipes: ['hote', 'page'],
  conversation: { session: 'abc', date: DATE_HIER }, a_approuver: false, taches_en_cours: [], fenetre: true, commandes: ['tmux attach -t p-assistant'], ...extra });
async function rouvrir(rep, { popup = true } = {}) {
  const m = monter({ 'GET /api/projets': [liste([ferme('a', 2)]), liste([ouvert('a')])], 'POST /api/projets/rouvrir': ok(rep) }, { popup });
  await settle();
  await bouton(carte(m), 'Rouvrir').clic(); await settle();
  return { m, messages: messagesCarte(carte(m)), carte: carte(m) };
}
{
  const m = monter({ 'GET /api/projets': [liste([ferme('a', 2)]), liste([ouvert('a')])],
    'POST /api/projets/rouvrir': () => new Promise((res) => { globalThis.__fin = () => res(ok(repOk())); }) });
  await settle();
  const b = bouton(carte(m), 'Rouvrir');
  const p = b.clic();
  await settle();
  const pendant = { texte: b.textContent, inactif: b.disabled, ordre: m.journal.filter((j) => j.evenement || j.route.includes('rouvrir')).map((j) => j.evenement || 'fetch') };
  m.declencher(); await settle();
  pendant.ligne = messagesCarte(carte(m));
  globalThis.__fin(); await p; await settle();
  sortie.rouvrirAttente = { pendant, apres: messagesCarte(carte(m)), popup: m.popups[0].location, popupFerme: m.popups[0].ferme, etat: resume(carte(m)) };
}
{
  const plein = await rouvrir(repOk({ a_approuver: true, taches_en_cours: ['hote/route-x'] }));
  sortie.rouvrirPlein = plein.messages;
  sortie.rouvrirCorps = plein.m.appels('POST /api/projets/rouvrir').map((a) => a.corps);
  sortie.rouvrirMono = parClasse(plein.carte, 'mono').map((n) => n.textContent);
  sortie.rouvrirCoordUn = (await rouvrir(repOk({ equipes: ['hote'] }))).messages;
  sortie.rouvrirRepli = (await rouvrir({ resultat: 'ok', url: 'http://x/', a_approuver: false, taches_en_cours: [], fenetre: true, commandes: [] })).messages;
  sortie.rouvrirAujourdhui = (await rouvrir(repOk({ conversation: { session: 'x', date: new Date(2026, 9, 12, 8, 3).toISOString() }, equipes: [] }))).messages;
  sortie.rouvrirAncien = (await rouvrir(repOk({ conversation: { session: 'x', date: new Date(2026, 9, 10, 18, 40).toISOString() }, equipes: undefined }))).messages;
  const sans = await rouvrir(repOk({ fenetre: false, commandes: ['tmux attach -t p-assistant'] }));
  sortie.rouvrirSansFenetre = { messages: sans.messages, commandes: parClasse(sans.carte, 'commande').map((c) => parTag(c, 'code')[0].textContent), copier: parClasse(sans.carte, 'commande').map((c) => bouton(c, 'Copier') !== undefined) };
  const sansConf = await rouvrir(repOk({ fenetre: false, a_approuver: true }));
  sortie.rouvrirSansFenetreConfiance = sansConf.messages.map((x) => x.texte);
  const nul = await rouvrir(repOk({ url: null, avertissement: 'Le serveur de la page ne répond pas encore.' }));
  sortie.rouvrirUrlNulle = { messages: nul.messages, ferme: nul.m.popups[0].ferme, location: nul.m.popups[0].location };
  const nulSans = await rouvrir(repOk({ url: null }));
  sortie.rouvrirUrlNulleSansAvert = { n: nulSans.messages.length, ferme: nulSans.m.popups[0].ferme };
  const bloque = await rouvrir(repOk(), { popup: false });
  sortie.rouvrirBloque = bloque.messages.map((x) => x.texte).filter((t) => t.includes('bloqué'));
  const echecs = await rouvrir(repOk({ echecs: [{ agent: 'coord-page', message: 'session absente' }], taches_en_cours: ['hote/t'] }));
  sortie.rouvrirEchecs = echecs.messages;
  const erreur = await rouvrir({ resultat: 'erreur', message: 'Le projet est déjà ouvert.' });
  sortie.rouvrirErreur = { messages: erreur.messages, ferme: erreur.m.popups[0].ferme };
  sortie.toutesPhrases = [plein, sans, nul, echecs].flatMap((x) => x.messages.map((y) => y.texte)).join('\n');
}

// ── 5. conversations ──
const conv = (i, debut) => ({ session: 's' + i, date: new Date(2026, 9, 12 - Math.floor(i / 3), 20 - (i % 3), 10 + i).toISOString(), taille: 1000 + i, debut: debut === undefined ? 'message ' + i : debut });
async function conversations(rep, projets = [ferme('a', 12)]) {
  const m = monter({ 'GET /api/projets': liste(projets), 'GET /api/projets/conversations': ok(rep),
    'POST /api/projets/rouvrir': ok(repOk()) });
  await settle();
  const details = parTag(carte(m), 'details')[0];
  details.open = true; await details.emettre('toggle'); await settle();
  return { m, details, carte: carte(m) };
}
const lignes = (c) => parTag(c, 'li').map((li) => ({ quand: parClasse(li, 'quand')[0].textContent, titre: parTag(li, 'b').map((b) => b.textContent), debut: parClasse(li, 'debut')[0].textContent, debutClasses: parClasse(li, 'debut')[0].classes, bouton: parTag(li, 'button')[0].textContent }));
{
  const douze = Array.from({ length: 12 }, (_, i) => conv(i));
  const c = await conversations({ resultat: 'ok', conversations: douze, fermeture: 's7' });
  const ls = lignes(c.carte);
  sortie.conv = { resume: parTag(c.carte, 'summary')[0].textContent, n: ls.length, premiere: ls[0], deuxieme: ls[1], titres: ls.filter((l) => l.titre.length).length,
    autres: parClasse(c.carte, 'autres').map((b) => b.textContent), url: c.m.journal.find((j) => j.route.includes('conversations')).route,
    taille: c.carte.textContent.includes('1007') };
  const apres = bouton(c.carte, '… et 4 autres'); await apres.clic();
  sortie.conv.apresDeplier = { n: lignes(c.carte).length, autres: parClasse(c.carte, 'autres').length };
  // le repli ne recharge pas à la seconde ouverture
  c.details.open = false; await c.details.emettre('toggle'); c.details.open = true; await c.details.emettre('toggle'); await settle();
  sortie.conv.charges = c.m.compteurs['GET /api/projets/conversations'];
  // Reprendre : appel de rouvrir avec la session
  await parTag(parTag(c.carte, 'li')[2], 'button')[0].clic(); await settle();
  sortie.conv.reprise = c.m.appels('POST /api/projets/rouvrir').map((a) => a.corps);
  sortie.conv.reponse = messagesCarte(carte(c.m)).map((x) => x.texte);
  const huit = await conversations({ resultat: 'ok', conversations: Array.from({ length: 8 }, (_, i) => conv(i)), fermeture: null });
  sortie.conv.huit = { n: lignes(huit.carte).length, autres: parClasse(huit.carte, 'autres').length };
  const neuf = await conversations({ resultat: 'ok', conversations: Array.from({ length: 9 }, (_, i) => conv(i)), fermeture: null });
  sortie.conv.neuf = { n: lignes(neuf.carte).length, autres: parClasse(neuf.carte, 'autres').map((b) => b.textContent) };
  const vide = await conversations({ resultat: 'ok', conversations: [], fermeture: null });
  sortie.conv.vide = vide.details.textContent;
  const err = await conversations({ resultat: 'erreur', message: 'Dossier illisible.' });
  sortie.conv.erreur = err.details.textContent;
}
{
  const piege = '<img src=x onerror=alert(1)>';
  const c = await conversations({ resultat: 'ok', conversations: [conv(0, piege), conv(1, null), conv(2, 'normal')], fermeture: null });
  const toutes = [...sous(c.m.ids.liste), ...sous(c.m.ids.bandeau)];
  sortie.injection = { imgs: toutes.filter((n) => n.tag === 'img').length, tags: [...new Set(toutes.map((n) => n.tag))].sort(), texte: lignes(c.carte)[0].debut, vide: lignes(c.carte)[1] };
}
{
  // fermeture en tête même si elle n'est pas la plus récente ; une fermeture absente de la liste est ignorée
  const c = await conversations({ resultat: 'ok', conversations: [conv(0), conv(1), conv(2)], fermeture: 's2' });
  sortie.fermetureTete = lignes(c.carte).map((l) => [l.debut, l.titre]);
  const d = await conversations({ resultat: 'ok', conversations: [conv(0), conv(1)], fermeture: 'inconnue' });
  sortie.fermetureAbsente = lignes(d.carte).map((l) => [l.debut, l.titre]);
}

// ── 6. installer ──
const apercu = (extra = {}) => ({ nom: 'vieux-site', commit: true, cree: ['.orga/', 'CLAUDE.md', '.gitignore-cime', 'a', 'b', 'c', 'd', 'e', 'f'], complete: ['.claude/settings.json', '.gitignore'], garde: [], ...extra });
async function ajouter(utilisateur, routes = {}, ap = apercu()) {
  const m = monter({ 'GET /api/projets': liste([], utilisateur), 'POST /api/projets/ajouter': [409, { resultat: 'refuse', installable: true, apercu: ap, message: 'pas de Cime' }],
    'POST /api/projets/installer': ok({ resultat: 'ok', chemin: '/d/vieux-site', prefixe: 'p-vieux', a_approuver: true, fenetre: true, commandes: ['tmux attach -t p-vieux-assistant'], message: 'ok' }), ...routes });
  await settle();
  m.ids['a-chemin'].value = '/d/vieux-site';
  await m.ids['form-ajouter'].emettre('submit'); await settle();
  return { m, encart: parClasse(m.ids['a-retour'], 'apercu')[0] };
}
{
  // les chemins de l'aperçu sont du texte parfois annoté par `cime` : affichés tels quels, la glose suit le chemin seul
  const a = await ajouter('Camille', {}, apercu({ cree: ['.orga/ (nouveau)', 'x (+3)'], complete: ['.claude/settings.json (+44)'], garde: ['CLAUDE.md (gardé)'] }));
  const dl = parTag(a.encart, 'dl')[0];
  const rub = {};
  for (let i = 0; i < dl.children.length; i += 2) rub[dl.children[i].textContent] = dl.children[i + 1].children.map((s) => s.textContent);
  sortie.annote = rub;
}
{
  const a = await ajouter('Camille');
  const dl = parTag(a.encart, 'dl')[0];
  const rub = {};
  for (let i = 0; i < dl.children.length; i += 2) rub[dl.children[i].textContent] = dl.children[i + 1].children.map((s) => s.textContent);
  sortie.installer = { titre: parTag(a.encart, 'h3')[0].textContent, phrases: parTag(a.encart, 'p').map((p) => p.textContent), fort: parTag(a.encart, 'strong').map((s) => s.textContent),
    rubriques: rub, boutons: parTag(a.encart, 'button').map((b) => b.textContent), ajouterInactif: a.m.ids['a-bouton'].disabled, champ: parTag(a.encart, 'input').length,
    appels: a.m.appels('POST /api/projets/ajouter').map((x) => x.corps), sansCommit: null };
  await bouton(a.encart, 'Annuler').clic(); await settle();
  sortie.annuler = { encart: parClasse(a.m.ids['a-retour'], 'apercu').length, ajouterInactif: a.m.ids['a-bouton'].disabled, installer: a.m.appels('POST /api/projets/installer').length };
  const b = await ajouter('Camille');
  await bouton(b.encart, 'Installer Cime ici').clic(); await settle();
  sortie.installerConnu = { corps: b.m.appels('POST /api/projets/installer').map((x) => x.corps), messages: lister(b.m.ids['a-retour']), chemin: b.m.ids['a-chemin'].value, ajouterInactif: b.m.ids['a-bouton'].disabled, listeRelue: b.m.compteurs['GET /api/projets'] };
  const c = await ajouter(null);
  sortie.prenom = { champs: parTag(c.encart, 'input').length, label: parTag(c.encart, 'label').map((l) => l.textContent) };
  await bouton(c.encart, 'Installer Cime ici').clic(); await settle();
  sortie.prenomVide = { appels: c.m.appels('POST /api/projets/installer').length, erreur: c.encart.textContent.includes('Ton prénom est obligatoire.') };
  parTag(c.encart, 'input')[0].value = '  Camille ';
  await bouton(c.encart, 'Installer Cime ici').clic(); await settle();
  sortie.prenomSaisi = c.m.appels('POST /api/projets/installer').map((x) => x.corps);
  const d = await ajouter('Camille', { 'POST /api/projets/installer': ok({ resultat: 'erreur', message: 'init a échoué' }) });
  await bouton(d.encart, 'Installer Cime ici').clic(); await settle();
  sortie.installerErreur = { texte: d.encart.textContent.includes('init a échoué'), reactive: !bouton(d.encart, 'Installer Cime ici').disabled, encartOuvert: parClasse(d.m.ids['a-retour'], 'apercu').length };
  const e = await ajouter('Camille', {}, apercu({ commit: false, cree: ['.orga/'], complete: [], garde: ['CLAUDE.md', 'src/'] }));
  const dle = parTag(e.encart, 'dl')[0];
  sortie.installerAlt = { phrases: parTag(e.encart, 'p').map((p) => p.textContent), labels: dle.children.filter((n) => n.tag === 'dt').map((n) => n.textContent), garde: dle.children[dle.children.length - 1].children.map((s) => s.textContent) };
  const f = await ajouter('Camille', { 'POST /api/projets/installer': ok({ resultat: 'ok', chemin: '/d/x', prefixe: 'p-x', a_approuver: false, fenetre: false, commandes: ['tmux attach -t p-x-assistant'] }) });
  await bouton(f.encart, 'Installer Cime ici').clic(); await settle();
  sortie.installerSansFenetre = lister(f.m.ids['a-retour']);
  // un dossier non installable : erreur simple, pas d'encart
  const g = monter({ 'GET /api/projets': liste([]), 'POST /api/projets/ajouter': [400, { resultat: 'erreur', message: 'Ce dossier n’existe pas.' }] });
  await settle(); g.ids['a-chemin'].value = '/nope'; await g.ids['form-ajouter'].emettre('submit'); await settle();
  sortie.nonInstallable = { messages: lister(g.ids['a-retour']), ajouterInactif: g.ids['a-bouton'].disabled };
  const h = monter({ 'GET /api/projets': liste([]), 'POST /api/projets/ajouter': [409, { resultat: 'refuse', installable: false, message: 'Pas un dossier.' }] });
  await settle(); h.ids['a-chemin'].value = '/nope'; await h.ids['form-ajouter'].emettre('submit'); await settle();
  sortie.nonInstallable2 = { messages: lister(h.ids['a-retour']), ajouterInactif: h.ids['a-bouton'].disabled };
}

// ── 7. visibilitychange ──
{
  const m = monter({ 'GET /api/projets': [liste([ouvert('a')]), liste([ouvert('a')]), liste([ferme('a', 2), ouvert('b')])] });
  await settle();
  const avant = m.compteurs['GET /api/projets'];
  const c0 = carte(m);
  await m.visible();
  const apresIdentique = { relu: m.compteurs['GET /api/projets'] - avant, memeCarte: carte(m) === c0 };
  await m.visible();
  sortie.visibilite = { auvisite: m.ecouteursDoc.visibilitychange.length, apresIdentique, relu2: m.compteurs['GET /api/projets'] - avant, noms: m.ids.liste.children.map((c) => resume(c).nom), etats: m.ids.liste.children.map((c) => resume(c).etat) };
  m.document.visibilityState = 'hidden';
  for (const f of m.ecouteursDoc.visibilitychange) await f({}); await settle();
  sortie.visibilite.masque = m.compteurs['GET /api/projets'] - avant;
}

// ── 8. erreurs : jamais le JSON brut à l'écran (phraseErreur, sur chaque écran d'erreur) ──
const BRUT = '{"resultat":"erreur","code":1,"message":"cime fermer : le registre est verrouillé"}';
const erreurBrute = { resultat: 'erreur', code: 1, message: BRUT };
const affiches = (m) => ['liste', 'bandeau', 'a-retour', 'n-retour'].flatMap((id) => parClasse(m.ids[id], 'message').map((x) => x.textContent));
{
  const p = monter({ 'GET /api/projets': liste([]) });
  await settle();
  // une erreur de script ne fait tomber que son cas, pas toute la sonde
  const essai = (code) => { try { return p.evalue(code); } catch (e) { return 'ERREUR : ' + e.message; } };
  sortie.phrases = {
    garde: essai(`phraseErreur({ resultat: 'erreur', message: 'tmux est introuvable' }, 'G')`),
    json: essai(`phraseErreur(${JSON.stringify(erreurBrute)}, 'G')`),
    absent: essai(`phraseErreur({ resultat: 'erreur' }, 'G')`),
    blanc: essai(`phraseErreur({ resultat: 'erreur', message: '   ' }, 'G')`),
    crochet: essai(`phraseErreur({ message: '[1, 2]' }, 'G')`),
    citation: essai(`phraseErreur({ message: 'le champ "resultat" manque' }, 'G')`),
  };
}
{
  const m = monter({ 'GET /api/projets': ok(erreurBrute) });
  await settle();
  sortie.brut = { liste: affiches(m) };
}
{
  const m = monter({ 'GET /api/projets': liste([ouvert('a')]), 'POST /api/projets/fermer': ok(erreurBrute) });
  await settle(); await bouton(carte(m), 'Fermer').clic(); await settle();
  sortie.brut.fermer = affiches(m);
}
{
  const m = monter({ 'GET /api/projets': liste([ferme('a', 2)]), 'POST /api/projets/rouvrir': ok(erreurBrute) });
  await settle(); await bouton(carte(m), 'Rouvrir').clic(); await settle();
  sortie.brut.rouvrir = affiches(m);
}
{
  const m = monter({ 'GET /api/projets': liste([ferme('a', 2)]), 'GET /api/projets/conversations': ok(erreurBrute) });
  await settle();
  const details = parTag(carte(m), 'details')[0];
  details.open = true; await details.emettre('toggle'); await settle();
  sortie.brut.conversations = affiches(m);
}
{
  const m = monter({ 'GET /api/projets': liste([]), 'POST /api/projets/ajouter': ok(erreurBrute) });
  await settle();
  m.ids['a-chemin'].value = '/d/x'; await m.ids['form-ajouter'].emettre('submit'); await settle();
  sortie.brut.ajouter = affiches(m);
  const r = monter({ 'GET /api/projets': liste([]), 'POST /api/projets/ajouter': [409, { resultat: 'refuse', installable: false, message: BRUT }] });
  await settle();
  r.ids['a-chemin'].value = '/d/x'; await r.ids['form-ajouter'].emettre('submit'); await settle();
  sortie.brut.ajouterRefus = affiches(r);
}
{
  const a = await ajouter('Camille', { 'POST /api/projets/installer': ok(erreurBrute) });
  await bouton(a.encart, 'Installer Cime ici').clic(); await settle();
  sortie.brut.installer = affiches(a.m);
}
{
  const m = monter({ 'GET /api/projets': liste([ouvert('a')]), 'POST /api/projets/ouvrir': ok(erreurBrute) });
  await settle(); await bouton(carte(m), 'Ouvrir').clic(); await settle();
  sortie.brut.ouvrir = affiches(m);
}
{
  const m = monter({ 'GET /api/projets': liste([ferme('a', 2)]), 'POST /api/projets/oublier': ok(erreurBrute) });
  await settle(); await bouton(carte(m), 'Oublier').clic(); await settle();
  sortie.brut.oublier = affiches(m);
}
{
  const m = monter({ 'GET /api/projets': liste([]), 'POST /api/projets/nouveau': ok(erreurBrute) });
  await settle();
  m.ids['n-parent'].value = '/d'; m.ids['n-nom'].value = 'nouveau';
  await m.ids['form-nouveau'].emettre('submit'); await settle();
  sortie.brut.creation = affiches(m);
}

process.stdout.write('\n' + JSON.stringify(sortie));
"""


@pytest.fixture(scope="module")
def r(tmp_path_factory):
    if NODE is None:
        pytest.skip("node introuvable (ni dans le PATH ni /opt/homebrew/bin/node) : les tests de la page du lanceur exécutent son script sous node")
    sonde = tmp_path_factory.mktemp("sonde") / "sonde-lanceur.mjs"
    sonde.write_text(SONDE, encoding="utf-8")
    res = subprocess.run([NODE, str(sonde), str(PAGE)], capture_output=True, text=True, timeout=120, env={**os.environ, "TZ": "Europe/Paris"})
    assert res.returncode == 0, res.stderr[-3000:]
    return json.loads(res.stdout.strip().splitlines()[-1])


def textes(liste):
    return [m["texte"] for m in liste]


# ── cartes ─────────────────────────────────────────────────────────────────────────────

def test_cartes_etats_boutons_et_ordre_du_serveur(r):
    c = r["cartes"]["cartes"]
    assert [x["nom"] for x in c] == ["zeta", "alpha", "un", "zero", "nul"]  # l'ordre du serveur, jamais celui de l'état
    assert (c[1]["etat"], c[1]["boutons"], c[1]["etatClasses"]) == ("Ouvert", ["Ouvrir", "Fermer"], ["etat", "ouvert"])
    assert (c[0]["etat"], c[0]["boutons"], c[0]["etatClasses"]) == ("Fermé · 6 conversations gardées", ["Rouvrir", "Oublier"], ["etat"])
    assert c[2]["etat"] == "Fermé · 1 conversation gardée"
    assert c[3]["etat"] == "Fermé" and c[4]["etat"] == "Fermé"
    assert c[0]["chemin"] == "/p/zeta"
    assert r["pures"]["etats"] == ["Ouvert", "Fermé · 6 conversations gardées", "Fermé · 1 conversation gardée", "Fermé", "Fermé"]


def test_liste_vide_tutoie(r):
    assert r["vide"] == "Aucun projet pour l'instant. Crée-en un ci-dessous, ou ajoute un dossier existant."


def test_noms_lisibles(r):
    assert r["pures"]["noms"] == ["l'Assistant", "le coordinateur hote", "un worker de page", "un worker de hote", "inconnu"]


# ── dateCourte ─────────────────────────────────────────────────────────────────────────

def test_date_courte(r):
    p = r["pures"]
    assert p["dates"] == ["aujourd'hui, 22 h 14", "hier, 22 h 14", "hier, 00 h 05", "10 oct., 18 h 40", "9 sept., 08 h 15", "3 janv., 07 h 00", "31 déc., 23 h 59"]
    assert p["dateIllisible"] == "" and p["maintenantObjet"] == "aujourd'hui, 09 h 05"
    assert p["minuit"] == "aujourd'hui, 00 h 00"  # même jour civil, même à 23 h 59


# ── fermer ─────────────────────────────────────────────────────────────────────────────

def test_fermer_200_message_vert_et_taches(r):
    f = r["fermer200"]
    assert f["pendant"] == {"texte": "Fermeture…", "inactif": True, "bandeau": ""}
    assert f["appels"] == [{"chemin": "/p/a"}]  # pas de confirmation, pas de forcer
    assert f["messages"] == [{"classes": ["message", "ok"], "texte": "Fermé · 2 conversations gardées."},
                             {"classes": ["message", "avert"], "texte": f"1 tâche de worker restera en cours{NBSP}: hote/route-x"}]
    assert f["apres"]["etat"] == "Fermé · 2 conversations gardées" and f["apres"]["boutons"] == ["Rouvrir", "Oublier"]
    assert f["autre"] == [] and f["bandeau"] == ""  # le retour est dans la carte, pas dans le bandeau
    assert textes(r["fermerSingulier"]) == ["Fermé · 1 conversation gardée.", f"2 tâches de worker resteront en cours{NBSP}: hote/a, hote/b"]


def test_fermer_erreur_dans_la_carte(r):
    assert r["fermerErreur"]["messages"] == [{"classes": ["message", "erreur"], "texte": "tmux est introuvable"}] and r["fermerErreur"]["reactive"]


def test_fermer_409_encart_noms_lisibles_et_pluriel(r):
    e = r["occupes3"]
    assert e["texte"] == (f"3 agents travaillent encore{NBSP}: l'Assistant, le coordinateur hote, un worker de page."
                          f"Fermer maintenant coupe leur tour en cours. Leurs conversations sont gardées{NBSP}; la tâche du worker restera «{NBSP}en cours{NBSP}».Ne pas fermerFermer quand même")
    assert e["classes"] == ["message", "avert"] and e["fort"] == [f"3 agents travaillent encore{NBSP}:"]
    assert e["boutons"] == ["Ne pas fermer", "Fermer quand même"] and e["classeQuandMeme"] == ["btn", "avert"]
    assert e["fermerInactif"] is True and e["fermerTexte"] == "Fermer"
    assert r["occupes1"]["fort"] == [f"1 agent travaille encore{NBSP}:"]
    assert "coord-hote" not in r["occupes3"]["texte"] and "worker-page-x" not in r["occupes3"]["texte"]
    assert r["occupes1"]["texte"].startswith(f"1 agent travaille encore{NBSP}: le coordinateur hote.Fermer maintenant coupe son tour en cours. Sa conversation est gardée.")
    assert "la tâche du worker restera" not in r["occupes1"]["texte"]  # pas de worker occupé : pas de phrase sur sa tâche
    assert f"Sa conversation est gardée{NBSP}; la tâche du worker restera" in r["occupes1w"]


def test_ne_pas_fermer_ferme_l_encart_sans_appel(r):
    assert r["nePasFermer"] == {"appels": 0, "encart": 0, "fermerInactif": False}


def test_fermer_quand_meme_rappelle_avec_forcer(r):
    q = r["quandMeme"]
    assert q["appels"] == [{"chemin": "/p/a"}, {"chemin": "/p/a", "forcer": True}]
    assert textes(q["messages"]) == ["Fermé · 3 conversations gardées."]


# ── rouvrir ────────────────────────────────────────────────────────────────────────────

def test_rouvrir_onglet_avant_l_attente_et_ligne_apres_2_secondes(r):
    a = r["rouvrirAttente"]
    assert a["pendant"]["ordre"] == ["open", "fetch"]  # l'onglet s'ouvre au clic, avant l'await
    assert a["pendant"]["texte"] == "Réouverture…" and a["pendant"]["inactif"] is True
    assert a["pendant"]["ligne"] == [{"classes": ["message", "avert"], "texte": "L'Assistant reprend sa conversation…"}]
    assert a["popup"] == "http://127.0.0.1:9000/" and a["popupFerme"] is False
    assert a["etat"]["boutons"] == ["Ouvrir", "Fermer"]  # la liste est relue : le projet est ouvert


def test_rouvrir_ordre_confiance_resultat_taches(r):
    m = r["rouvrirPlein"]
    assert [x["classes"][1] for x in m] == ["avert", "ok", "avert"]
    assert m[0]["texte"] == (f"Claude Code demande s'il peut faire confiance à ce dossier. Dans la fenêtre de terminal qui vient de s'ouvrir, accepte avec Entrée{NBSP}: l'Assistant démarre ensuite.")
    assert m[1]["texte"] == f"L'Assistant a repris sa conversation d'hier, 22 h 14, dans une fenêtre de terminal. Coordinateurs relancés{NBSP}: hote, page."
    assert m[2]["texte"] == f"1 tâche de worker est restée en cours{NBSP}: hote/route-x. L'Assistant le sait{NBSP}; c'est lui qui décide de la relancer."
    assert r["rouvrirMono"] == ["hote/route-x"] and r["rouvrirCorps"] == [{"chemin": "/p/a"}]


def test_rouvrir_variantes_du_texte_de_resultat(r):
    assert textes(r["rouvrirCoordUn"]) == [f"L'Assistant a repris sa conversation d'hier, 22 h 14, dans une fenêtre de terminal. Coordinateur relancé{NBSP}: hote."]
    assert textes(r["rouvrirRepli"]) == ["L'Assistant a repris sa dernière conversation, dans une fenêtre de terminal."]  # ni date ni équipes
    assert textes(r["rouvrirAujourdhui"]) == ["L'Assistant a repris sa conversation d'aujourd'hui, 08 h 03, dans une fenêtre de terminal."]
    assert textes(r["rouvrirAncien"]) == ["L'Assistant a repris sa conversation du 10 oct., 18 h 40, dans une fenêtre de terminal."]


def test_rouvrir_sans_fenetre_commande_copiable(r):
    s = r["rouvrirSansFenetre"]
    assert s["messages"] == [{"classes": ["message", "avert"], "texte": f"L'Assistant a repris sa conversation d'hier, 22 h 14, mais la fenêtre de terminal n'a pas pu s'ouvrir. Pour le rejoindre{NBSP}:tmux attach -t p-assistantCopier"}]
    assert s["commandes"] == ["tmux attach -t p-assistant"] and s["copier"] == [True]
    c = r["rouvrirSansFenetreConfiance"]
    assert c[0].startswith("Claude Code demande s'il peut faire confiance à ce dossier. Rejoins la session de l'Assistant avec la commande ci-dessous") and "fenêtre de terminal qui vient" not in c[0]


def test_rouvrir_url_nulle_avertissement_et_onglet_ferme(r):
    u = r["rouvrirUrlNulle"]
    assert u["ferme"] is True and u["location"] is None
    assert [x["classes"][1] for x in u["messages"]] == ["ok", "avert"]
    assert u["messages"][1]["texte"] == "Le serveur de la page ne répond pas encore."
    assert r["rouvrirUrlNulleSansAvert"] == {"n": 1, "ferme": True}
    assert r["rouvrirBloque"] == [f"Le navigateur a bloqué l'onglet. Adresse du projet{NBSP}: http://127.0.0.1:9000/"]


def test_rouvrir_echecs_et_erreur(r):
    e = r["rouvrirEchecs"]
    assert [x["classes"][1] for x in e] == ["ok", "avert", "avert"]  # résultat, tâches, puis échecs
    assert e[2]["texte"] == f"Relance impossible pour le coordinateur page{NBSP}: session absente"
    assert r["rouvrirErreur"] == {"messages": [{"classes": ["message", "erreur"], "texte": "Le projet est déjà ouvert."}], "ferme": True}


def test_jamais_iterm_dans_les_textes(r):
    assert "iTerm" not in r["toutesPhrases"] and "terminal" in r["toutesPhrases"]
    assert "iTerm" not in PAGE.read_text(encoding="utf-8")


# ── conversations ──────────────────────────────────────────────────────────────────────

def test_conversations_fermeture_en_tete_plafond_et_depli(r):
    c = r["conv"]
    assert c["resume"] == "Reprendre une autre conversation de l'Assistant"
    assert c["n"] == 8 and c["autres"] == ["… et 4 autres"] and c["titres"] == 1
    assert c["premiere"]["titre"] == ["À LA FERMETURE"] and c["premiere"]["debut"] == "message 7"  # s7 est la 8e, pas la plus récente
    assert c["deuxieme"]["titre"] == [] and c["deuxieme"]["debut"] == "message 0" and c["deuxieme"]["bouton"] == "Reprendre"
    assert re.fullmatch(r"À LA FERMETURE(hier|aujourd'hui|\d+ [^,]+), \d\d h \d\d", c["premiere"]["quand"]), c["premiere"]["quand"]
    assert c["url"] == "/api/projets/conversations?chemin=%2Fp%2Fa" and not c["taille"]  # la taille n'est pas affichée
    assert c["apresDeplier"] == {"n": 12, "autres": 0} and c["charges"] == 1
    assert c["huit"] == {"n": 8, "autres": 0} and c["neuf"] == {"n": 8, "autres": ["… et 1 autre"]}
    assert "Aucune conversation" in c["vide"] and c["erreur"].endswith("Dossier illisible.")


def test_reprendre_appelle_rouvrir_avec_la_session(r):
    assert r["conv"]["reprise"] == [{"chemin": "/p/a", "session": "s1"}]
    assert r["conv"]["reponse"][0].startswith("L'Assistant a repris sa conversation d'hier")


def test_debut_est_du_texte_jamais_du_html(r):
    i = r["injection"]
    assert i["imgs"] == 0 and "img" not in i["tags"]
    assert i["texte"] == "<img src=x onerror=alert(1)>"
    assert i["vide"]["debut"] == "Aucun message de toi dans cette conversation" and i["vide"]["debutClasses"] == ["debut", "sans"]


def test_fermeture_en_tete_meme_non_recente(r):
    assert r["fermetureTete"] == [["message 2", ["À LA FERMETURE"]], ["message 0", []], ["message 1", []]]
    assert r["fermetureAbsente"] == [["message 0", []], ["message 1", []]]


# ── installer ──────────────────────────────────────────────────────────────────────────

def test_installer_chemins_annotes_tels_quels_glose_sur_le_chemin(r):
    a = r["annote"]
    assert a["Ajoutera"] == [".orga/ (nouveau) équipes, registre, socle", "x (+3)"]   # texte intact, glose sur « .orga/ »
    assert a["Complétera"] == [".claude/settings.json (+44) règles de Cime ajoutées, les tiennes gardées"]
    assert a["Ne touchera pas"] == ["CLAUDE.md (gardé)"]   # pas de glose dans cette rubrique


def test_installer_encart_trois_rubriques(r):
    i = r["installer"]
    assert i["titre"] == "Cime n'est pas encore installé dans ce dossier."
    assert i["phrases"][0] == "Il sera ajouté sous le nom vieux-site, et l'Assistant démarrera dans une fenêtre de terminal."
    assert i["phrases"][1] == "Cime fera un commit pour enregistrer ces ajouts." and i["fort"] == ["vieux-site"]
    assert list(i["rubriques"]) == ["Ajoutera", "Complétera", "Ne touchera pas"]
    assert i["rubriques"]["Ajoutera"] == [".orga/ équipes, registre, socle", "CLAUDE.md s'il n'existe pas", ".gitignore-cime", "a", "b", "c", "… et 3 autres"]  # 6 chemins puis le reste
    assert i["rubriques"]["Complétera"] == [".claude/settings.json règles de Cime ajoutées, les tiennes gardées", ".gitignore"]
    assert i["rubriques"]["Ne touchera pas"] == ["ton CLAUDE.md, ton code, tes branches, tes conversations"]
    assert i["boutons"] == ["Installer Cime ici", "Annuler"] and i["ajouterInactif"] is True and i["champ"] == 0
    assert i["appels"] == [{"chemin": "/d/vieux-site"}]
    a = r["installerAlt"]
    assert a["phrases"][1] == f"Cime ne fera aucun commit{NBSP}: les fichiers ajoutés resteront à valider par toi."
    assert a["labels"] == ["Ajoutera", "Ne touchera pas"] and a["garde"] == ["CLAUDE.md", "src/"]


def test_annuler_sans_appel(r):
    assert r["annuler"] == {"encart": 0, "ajouterInactif": False, "installer": 0}


def test_installer_prenom_seulement_si_vide(r):
    assert r["prenom"] == {"champs": 1, "label": ["Ton prénom"]}
    assert r["prenomVide"] == {"appels": 0, "erreur": True}
    assert r["prenomSaisi"] == [{"chemin": "/d/vieux-site", "utilisateur": "Camille"}]
    assert r["installerConnu"]["corps"] == [{"chemin": "/d/vieux-site"}]


def test_installer_puis_deroule_de_rouvrir(r):
    k = r["installerConnu"]
    assert [m["classes"][1] for m in k["messages"]] == ["avert", "ok"]  # la confiance d'abord, puis le résultat
    assert k["messages"][0]["texte"].startswith("Claude Code demande s'il peut faire confiance à ce dossier. Dans la fenêtre de terminal")
    assert k["messages"][1]["texte"] == "Cime est installé dans ce dossier. L'Assistant démarre dans une fenêtre de terminal."
    assert k["chemin"] == "" and k["ajouterInactif"] is False and k["listeRelue"] == 2
    s = r["installerSansFenetre"]
    assert [m["classes"][1] for m in s] == ["avert"] and "n'a pas pu s'ouvrir" in s[0]["texte"] and "tmux attach -t p-x-assistant" in s[0]["texte"]


def test_installer_erreur_garde_l_encart(r):
    assert r["installerErreur"] == {"texte": True, "reactive": True, "encartOuvert": 1}


def test_ajouter_non_installable_erreur_simple(r):
    assert r["nonInstallable"] == {"messages": [{"classes": ["message", "erreur"], "texte": "Ce dossier n’existe pas."}], "ajouterInactif": False}
    assert r["nonInstallable2"]["messages"] == [{"classes": ["message", "erreur"], "texte": "Pas un dossier."}] and r["nonInstallable2"]["ajouterInactif"] is False


# ── visibilitychange ───────────────────────────────────────────────────────────────────

def test_visibilitychange_relit_la_liste(r):
    v = r["visibilite"]
    assert v["auvisite"] == 1
    assert v["apresIdentique"] == {"relu": 1, "memeCarte": True}  # relue, mais rien de redessiné si rien n'a changé
    assert v["relu2"] == 2 and v["noms"] == ["a", "b"] and v["etats"] == ["Fermé · 2 conversations gardées", "Ouvert"]
    assert v["masque"] == 2  # onglet masqué : aucune lecture


# ── analyse de texte de index.html : tutoiement, espaces insécables ────────────────────

def chaines_visibles(html: str) -> list[str]:
    """Textes du HTML (hors script et style, attributs placeholder/title/aria-label inclus) et chaînes entre guillemets du script."""
    script = html[html.index("<script>") + 8:html.rindex("</script>")]
    hors = re.sub(r"<script>.*?</script>|<style>.*?</style>|<head>.*?</head>", " ", html, flags=re.S)
    attributs = re.findall(r'(?:placeholder|title|aria-label|alt)="([^"]*)"', hors)
    texte_html = re.sub(r"<[^>]+>", "\n", hors)
    sans_commentaires = re.sub(r"(^|\s)//[^\n]*", r"\1", script)
    # `"…" + NBSP + "…"` : l'espace insécable est une constante du script ; on la remet dans les chaînes avant de les lire
    sans_commentaires = re.sub(r'"\s*\+\s*NBSP\s*\+\s*"', r"\\u00a0", sans_commentaires)
    sans_commentaires = re.sub(r'"\s*\+\s*NBSP\s*\+\s*(?=[^"\s])', r'\\u00a0" + ', sans_commentaires)
    sans_commentaires = re.sub(r'([+=(,])\s*NBSP\s*\+\s*"', r'\1 "\\u00a0', sans_commentaires)
    litteraux = []
    for m in re.finditer(r'"((?:[^"\\\n]|\\.)*)"', sans_commentaires):
        try:
            litteraux.append(json.loads('"' + m.group(1) + '"'))
        except json.JSONDecodeError:
            pytest.fail("chaîne illisible dans le script : " + m.group(1))
    return [t for t in [*texte_html.split("\n"), *attributs, *litteraux] if t.strip()]


# verbes à l'impératif en -ez / mots en -ez qui ne sont pas des impératifs : liste fermée de ce que le fichier contient
IMPERATIF_EZ = re.compile(r"\b[a-zàâçéèêëîïôûù]+ez\b(?:-[a-z]+)?", re.I)
AUTORISES_EZ: set[str] = set()


def fautes_de_tutoiement(html: str) -> list[str]:
    fautes = []
    for t in chaines_visibles(html):
        if re.search(r"\b(vous|votre|vos)\b", t, re.I):
            fautes.append("vouvoiement : " + t)
        for m in IMPERATIF_EZ.finditer(t):
            if m.group(0).lower() not in AUTORISES_EZ:
                fautes.append("impératif en -ez : " + m.group(0) + " dans " + t)
    return fautes


def fautes_de_typographie(html: str) -> list[str]:
    fautes = []
    for t in chaines_visibles(html):
        if re.search(r" [;:?!]", t):
            fautes.append("espace ordinaire avant la ponctuation : " + t)
        if re.search(r"« | »", t):
            fautes.append("espace ordinaire autour des guillemets : " + t)
    return fautes


def test_tutoiement_partout():
    html = PAGE.read_text(encoding="utf-8")
    assert fautes_de_tutoiement(html) == []
    assert any("Ton prénom" in t for t in chaines_visibles(html))  # l'analyse voit bien les textes du HTML
    assert any("Crée-en un" in t for t in chaines_visibles(html))  # ... et ceux du script


@pytest.mark.parametrize("ancien,nouveau", [("Ton prénom", "Votre prénom"), ("Crée-en un", "Créez-en un"), ("ouvre-la", "ouvrez-la"), ("ajoute un dossier", "ajoutez un dossier"),
                                             ("Rejoins la session", "Vos amis rejoignent la session")])
def test_tutoiement_mutation(ancien, nouveau):
    html = PAGE.read_text(encoding="utf-8")
    assert ancien in html
    assert fautes_de_tutoiement(html.replace(ancien, nouveau, 1)) != []


def test_espaces_insecables_avant_la_ponctuation_double():
    html = PAGE.read_text(encoding="utf-8")
    assert fautes_de_typographie(html) == []
    assert any(NBSP + ":" in t for t in chaines_visibles(html))


def test_espaces_insecables_mutation():
    html = PAGE.read_text(encoding="utf-8")
    mutations = [
        ('"Projet créé" + NBSP + ":"', '"Projet créé :"'),
        ('suite += NBSP + "; " + (workers', 'suite += " ; " + (workers'),
        ('"Oublier le projet «" + NBSP + p.nom + NBSP + "»"', '"Oublier le projet « " + p.nom + " »"'),
        ('"»" + NBSP + "?\\n\\nIl', '"» ?\\n\\nIl'),
    ]
    for ancien, nouveau in mutations:
        assert ancien in html, ancien
        assert fautes_de_typographie(html.replace(ancien, nouveau, 1)) != [], ancien
    assert fautes_de_typographie(html.replace("Ouvert", "Ouvert !", 1)) != []


def test_aucune_dependance_externe_de_plus():
    html = PAGE.read_text(encoding="utf-8")
    assert re.findall(r'(?:src|href)="(https?://[^"]+)"', html) == ["https://fonts.googleapis.com", "https://fonts.gstatic.com",
                                                                          "https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap"]
    assert not re.search(r"<script[^>]+src=", html)


def test_aucun_debordement_a_360px_par_construction():
    css = PAGE.read_text(encoding="utf-8")
    for regle in ("overflow-wrap: anywhere", "minmax(0, 1fr)", "min-width: 0", "flex-wrap: wrap"):
        assert regle in css, regle


# ── erreurs en phrase : jamais le JSON brut à l'écran ──────────────────────────────────

GENERIQUES = {
    "liste": "Liste des projets indisponible.",
    "fermer": "Fermeture impossible.",
    "rouvrir": "Réouverture impossible.",
    "conversations": "Conversations indisponibles.",
    "ajouter": "Ajout impossible.",
    "ajouterRefus": "Ajout impossible.",
    "installer": "Installation impossible.",
    "ouvrir": "Ouverture impossible.",
    "oublier": "Échec.",
    "creation": "Création impossible.",
}


def test_phrase_erreur_garde_le_message_normal(r):
    assert r["phrases"]["garde"] == "tmux est introuvable"


@pytest.mark.parametrize("cas", ["json", "absent", "blanc", "crochet", "citation"])
def test_phrase_erreur_jamais_du_json(r, cas):
    assert r["phrases"][cas] == "G"


@pytest.mark.parametrize("ecran", list(GENERIQUES))
def test_chaque_ecran_d_erreur_affiche_une_phrase(r, ecran):
    affiche = r["brut"][ecran]
    assert affiche == [GENERIQUES[ecran]], affiche
    assert not any("{" in t or "resultat" in t for t in affiche)


# ── dateCourte : la date ne se coupe jamais dans l'heure ───────────────────────────────

def test_date_courte_insecables_dans_l_heure(r):
    for s in r["pures"]["dates"]:
        assert re.search(r"\d h \d\d$", s), s          # l'heure : espaces insécables
        assert s.count(" ") == 1 and s.index(" ") == s.index(",") + 1, s   # seule espace : après la virgule


def test_colonne_de_la_date_150px_et_plus_112():
    css = PAGE.read_text(encoding="utf-8")
    assert "grid-template-columns: 150px minmax(0, 1fr) auto" in css
    assert "112px" not in css
