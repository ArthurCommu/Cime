// Accueil : halo ambre des pièces où quelqu'un attend l’utilisateur, sélection (contour bleu),
// noms des pièces à la résolution de l'écran, clic dans le vide, premier instantané montré sans attendre.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { ATLAS } from '../../../src/cime/scene/static/graphismes/atlas.js';
import { construireScene } from '../../../src/cime/scene/static/modele.js';
import { dessiner, SELECTION, COULEURS, PERIODE_HALO_MS, melanger } from '../../../src/cime/scene/static/rendu.js';
import { zoneDeCible, infobulle, TACHE_MAX } from '../../../src/cime/scene/static/interaction.js';
import { ecrireNoms, ecrireCompteurs, taillePolice, abregerNom } from '../../../src/cime/scene/static/noms.js';
import { PALETTE } from '../../../src/cime/scene/static/graphismes/palette.js';
import { SurfaceCanvas } from '../../../src/cime/scene/static/surface-canvas.js';
import { monterScene } from '../../../src/cime/scene/static/scene.js';
import { creerSourceAlimentee } from '../../../src/cime/scene/static/source-alimentee.js';
import { ajuster, mondeVersEcran } from '../../../src/cime/scene/static/vue.js';
import { fauxNavigateur, evt, FauxCanvas } from './faux-dom.mjs';

const ICI = dirname(fileURLToPath(import.meta.url));
const FIXTURE = join(ICI, '..', 'fixtures', 'etat-exemple.json');
const etat = () => JSON.parse(readFileSync(FIXTURE, 'utf8'));
const attente = (equipe, agent, id = `msg-${equipe}-${agent}`) => ({ id, message_id: 1, objet: null, nature: 'decision', titre: 't', bloque: 'b', depuis: '2026-10-11T09:00:00.000Z', agent, equipe, actions: ['trancher'] });
const avecAttentes = (liste) => ({ ...etat(), attentes_utilisateur: liste });
const piece = (scene, nom) => scene.pieces.find((p) => p.nom === nom);

// Une surface qui note ce qu'on y dessine.
class Espion {
  constructor() { this.rects = []; this.textes = []; }
  rect(x, y, w, h, c) { this.rects.push({ x, y, w, h, c }); }
  texte(t, x, y, c) { this.textes.push({ t, x, y, c }); }
  sprite() {}
}
const dessin = (scene, t = 0, options) => {
  const e = new Espion();
  dessiner(e, ATLAS, scene, t, { legende: false, ...options });
  return e;
};
// Le cadre de 2 px qu'un halo ou une sélection pose au ras d'un rectangle : sa barre du haut.
const barreHaut = (e, r, couleur) => e.rects.filter((q) => q.x === r.x && q.y === r.y && q.w === r.w && q.h === 2 && (!couleur || q.c === couleur));

// ---- Halo ambre ---------------------------------------------------------------------------------------------------

test('halo : une pièce compte les points qui attendent l’utilisateur, par équipe ; sinon par le siège de l’agent d’origine', () => {
  const s = construireScene(avecAttentes([attente('page', 'coord-page'), attente('page', 'coord-page', 'b'), attente(null, 'assistant'), attente('hote', 'coord-hote')]));
  assert.equal(piece(s, 'page').attentes, 2);
  assert.equal(piece(s, 'hote').attentes, 1);
  assert.equal(piece(s, 'assistant').attentes, 1, 'décision portée par l’Assistant : sa pièce');
  assert.equal(piece(s, 'scene')?.attentes ?? 0, 0);
  assert.equal(piece(s, 'utilisateur').attentes, 0, 'la salle de l’utilisateur n’est pas une pièce qui attend l’utilisateur : sa porte le dit');
  for (const p of s.pieces.filter((q) => !['page', 'hote', 'assistant'].includes(q.nom))) assert.equal(p.attentes, 0, p.nom);
});

test('halo : ni attentes_utilisateur (null, absent, vide) ni agent inconnu ne donnent de halo', () => {
  for (const attentes of [null, [], undefined]) {
    const s = construireScene({ ...etat(), attentes_utilisateur: attentes });
    assert.ok(s.pieces.every((p) => p.attentes === 0));
  }
  const s = construireScene(avecAttentes([attente(null, 'fantome')]));
  assert.ok(s.pieces.every((p) => p.attentes === 0));
});

test('halo : le cadre ambre n’est posé que sur les pièces qui attendent', () => {
  const s = construireScene(avecAttentes([attente('page', 'coord-page')]));
  const e = dessin(s, 0);
  assert.equal(barreHaut(e, piece(s, 'page')).length, 1, 'la pièce page a son halo');
  for (const p of s.pieces.filter((q) => q.nom !== 'page')) assert.equal(barreHaut(e, p).length, 0, `${p.nom} n’en a pas`);
  const sans = dessin(construireScene(avecAttentes([])), 0);
  for (const p of s.pieces) assert.equal(barreHaut(sans, p).length, 0, `${p.nom} sans attente`);
});

test('halo : il respire sur 2,4 s ; fixe quand le mouvement est réduit ; jamais rouge', () => {
  const s = construireScene(avecAttentes([attente('page', 'coord-page')]));
  const p = piece(s, 'page');
  const couleurA = (t, options) => barreHaut(dessin(s, t, options), p)[0].c;
  assert.notEqual(couleurA(0), couleurA(PERIODE_HALO_MS / 2), 'creux puis sommet');
  assert.equal(couleurA(0), couleurA(PERIODE_HALO_MS), 'une période plus tard : le même ambre');
  assert.equal(couleurA(0, { pulsation: false }), couleurA(PERIODE_HALO_MS / 2, { pulsation: false }), 'pulsation coupée : fixe');
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(couleurA(PERIODE_HALO_MS / 2).slice(i, i + 2), 16));
  assert.ok(r > g && g > b && r > 200, `au sommet, l’ambre de la scène : ${couleurA(PERIODE_HALO_MS / 2)}`);
});

test('melanger : bornes et milieu', () => {
  assert.equal(melanger('#000000', '#ffffff', 0), '#000000');
  assert.equal(melanger('#000000', '#ffffff', 1), '#ffffff');
  assert.equal(melanger('#000000', '#fe0000', 0.5), '#7f0000');
});

test('info-bulle d’une pièce : dit combien de points attendent l’utilisateur, sans texte libre', () => {
  const s = construireScene(avecAttentes([attente('page', 'coord-page'), attente('page', 'coord-page', 'b'), attente('hote', 'coord-hote')]));
  assert.deepEqual(infobulle(s, 'piece', 'page').lignes.at(-1), '2 points attendent l’utilisateur');
  assert.deepEqual(infobulle(s, 'piece', 'hote').lignes.at(-1), '1 point attend l’utilisateur');
  assert.ok(infobulle(s, 'piece', 'observation').lignes.every((l) => !/l’utilisateur/.test(l)));
});

// ---- Sélection ----------------------------------------------------------------------------------------------------

test('zoneDeCible : la pièce d’une équipe, la salle de l’utilisateur, un agent, une enveloppe ; null si absente', () => {
  const s = construireScene(etat());
  assert.deepEqual(zoneDeCible(s, { type: 'equipe', nom: 'page' }), piece(s, 'page'));
  assert.deepEqual(zoneDeCible(s, { type: 'utilisateur' }), piece(s, 'utilisateur'));
  assert.deepEqual(zoneDeCible(s, { type: 'agent', id: 'coord-page' }), s.agents.find((a) => a.id === 'coord-page').zone);
  const env = s.enveloppes[0];
  assert.deepEqual(zoneDeCible(s, { type: 'message', id: env.id }), env.zone);
  for (const c of [null, undefined, { type: 'equipe', nom: 'nulle-part' }, { type: 'agent', id: 'x' }, { type: 'message', id: 'x' }, { type: 'inconnu' }]) {
    assert.equal(zoneDeCible(s, c), null);
  }
});

test('sélection : contour bleu au ras de la pièce, un cran dehors pour un agent ; rien sans cible', () => {
  const s = construireScene(etat());
  const p = piece(s, 'page');
  assert.equal(barreHaut(dessin(s, 0, { selection: { type: 'equipe', nom: 'page' } }), p, SELECTION.trait).length, 1);
  assert.equal(dessin(s, 0, { selection: null }).rects.filter((q) => q.c === SELECTION.trait).length, 0);
  assert.equal(dessin(s, 0, { selection: { type: 'equipe', nom: 'nulle-part' } }).rects.filter((q) => q.c === SELECTION.trait).length, 0);
  const z = s.agents.find((a) => a.id === 'coord-page').zone;
  const cadreAgent = { x: z.x - 2, y: z.y - 2, w: z.w + 4, h: z.h + 4 };
  assert.equal(barreHaut(dessin(s, 0, { selection: { type: 'agent', id: 'coord-page' } }), cadreAgent, SELECTION.trait).length, 1);
});

test('sélection : par-dessus le halo, qui reste visible en dedans', () => {
  const s = construireScene(avecAttentes([attente('page', 'coord-page')]));
  const p = piece(s, 'page');
  const e = dessin(s, 0, { selection: { type: 'equipe', nom: 'page' } });
  const iHalo = e.rects.findIndex((q) => q.x === p.x && q.y === p.y && q.w === p.w && q.h === 2 && q.c !== SELECTION.trait);
  const iSel = e.rects.findIndex((q) => q.x === p.x && q.y === p.y && q.w === p.w && q.h === 2 && q.c === SELECTION.trait);
  assert.ok(iHalo >= 0 && iSel > iHalo, 'la sélection est dessinée après le halo');
  assert.ok(e.rects.some((q) => q.x === p.x + 2 && q.y === p.y + 2 && q.w === p.w - 4 && q.h === 1), 'le filet intérieur ambre du halo reste');
});

test('le bleu de la sélection n’est pas le rouge des problèmes ni l’ambre des attentes', () => {
  assert.notEqual(SELECTION.trait, COULEURS.rouge);
  assert.notEqual(SELECTION.trait, COULEURS.ambre);
});

// ---- Noms des pièces ----------------------------------------------------------------------------------------------

test('noms : la police pixel ne les écrit plus quand la page les écrit à la résolution de l’écran', () => {
  const s = construireScene(etat());
  const pixel = dessin(s, 0).textes.map((t) => t.t);
  assert.ok(pixel.includes('page'), 'par défaut : en police pixel');
  const sans = dessin(s, 0, { noms: false }).textes.map((t) => t.t);
  assert.equal(sans.includes('page'), false);
});

test('noms : taille de police selon l’échelle, 11 px à ×1 (bande de 16 px), 16 px au plus', () => {
  assert.deepEqual([1, 2, 3, 4, 6].map(taillePolice), [11, 13, 15, 16, 16]);
});

test('noms : un par pièce, dans sa zone, tronqué par « … » quand ça ne tient pas', () => {
  const s = construireScene(etat());
  const ctx = new FauxCanvas({}).getContext();
  ecrireNoms(ctx, s, { echelle: 2, x: 10, y: 20 }, { d: 2, police: "'IBM Plex Sans', sans-serif" });
  const ecrits = ctx.appels.filter((a) => a[0] === 'fillText');
  assert.equal(ecrits.length, s.pieces.length);
  assert.deepEqual(ctx.appels.find((a) => a[0] === 'setTransform'), ['setTransform', 2, 0, 0, 2, 0, 0]);
  assert.equal(ctx.font, "600 13px 'IBM Plex Sans', sans-serif");
  const p = piece(s, 'page');
  const [, texte, x, y] = ecrits.find((a) => a[1].startsWith('pag') || a[1] === 'page');
  assert.equal(x, 10 + p.nomZone.x * 2);
  assert.equal(y, 20 + (p.entete.y + p.entete.h / 2) * 2 + 0.5);
  for (const [, t, , ] of ecrits) {
    const z = s.pieces.find((q) => q.libelle === t || t.endsWith('…'))?.nomZone;
    assert.ok(z && [...t].length * 6 <= z.w * 2 + 6 * 0, `${t} tient dans sa zone`);
  }
  assert.equal(ctx.appels.at(-1)[0], 'restore', 'le contexte est rendu tel qu’on l’a reçu');
  assert.equal(abregerNom({ measureText: (t) => ({ width: [...t].length * 6 }) }, 'verification', 40), 'verif…');
  assert.equal(abregerNom({ measureText: (t) => ({ width: [...t].length * 6 }) }, 'page', 40), 'page');
});

// ---- Dans la scène montée -----------------------------------------------------------------------------------------

function monter(options = {}) {
  const navigateur = fauxNavigateur(options.navigateur);
  if (options.mouvementReduit) navigateur.fenetre.matchMedia = (q) => ({ matches: /reduce/.test(q) });
  const appels = { clics: [], vides: 0, prets: 0 };
  const source = {
    abonner: (cb) => cb(structuredClone(options.etat ?? etat()), [], 5, { reset: true }),
    arreter() {},
  };
  const scene = monterScene(navigateur.conteneur, {
    source,
    surClic: (c) => appels.clics.push(c),
    surVide: () => appels.vides++,
    surPret: () => appels.prets++,
    theme: options.theme,
  });
  navigateur.image();
  return { navigateur, scene, canvas: navigateur.conteneur.enfants[0], appels };
}
const MONDE_EXEMPLE = (() => { const s = construireScene(etat()); return { w: s.largeur, h: s.hauteurEtage }; })();
const ecranDe = (nav, zone) => {
  const vue = ajuster(MONDE_EXEMPLE, { w: nav.conteneur.clientWidth, h: nav.conteneur.clientHeight });
  return mondeVersEcran(vue, zone.x + zone.w / 2, zone.y + zone.h / 2);
};
const cliquer = (canvas, p) => canvas.dispatchEvent(evt('click', { clientX: p.x, clientY: p.y, detail: 1 }));
const fillRects = (nav) => nav.canvases[1].ctx.couleurs;

test('premier instantané : dessiné, nommé et annoncé prêt dès la première image', () => {
  const { appels, canvas } = monter({ theme: { police: 'Plex' } });
  assert.equal(appels.prets, 1);
  const textes = canvas.getContext().appels.filter((a) => a[0] === 'fillText').map((a) => a[1]);
  assert.ok(textes.includes('page') && textes.includes('hote'), `noms écrits : ${textes.join(' ')}`);
  assert.ok(textes.some((t) => /^hors organigramme : \d+/.test(t)), `compteur du couloir écrit : ${textes.join(' | ')}`);
});

test('la scène n’écrit pas les noms deux fois : l’étage sans police pixel, les noms par-dessus', () => {
  const { navigateur } = monter();
  const dessins = (noms) => {
    const surface = new SurfaceCanvas(fauxNavigateur().doc, ATLAS, PALETTE);
    const sc = construireScene(etat());
    surface.dimensionner(sc.largeur, sc.hauteurEtage);
    dessiner(surface, ATLAS, sc, 0, { legende: false, noms });
    return surface.ctx.appels.filter((a) => a[0] === 'drawImage').length;
  };
  const dansLaScene = navigateur.canvases[1].ctx.appels.filter((a) => a[0] === 'drawImage').length;
  assert.ok(dessins(true) > dessins(false), 'le cas : les lettres pixel sont des images de plus');
  assert.equal(dansLaScene, dessins(false));
});

test('selectionner : la cible est entourée en bleu à l’image suivante, null retire le contour', () => {
  const { navigateur, scene } = monter();
  const bleus = () => fillRects(navigateur).filter((c) => c === SELECTION.trait).length;
  assert.equal(bleus(), 0);
  scene.selectionner({ type: 'equipe', nom: 'page' });
  navigateur.image();
  const avec = bleus();
  assert.ok(avec >= 4, `quatre côtés au moins : ${avec}`);
  navigateur.image();
  assert.equal(bleus() - avec, avec, 'toujours là à l’image suivante');
  scene.selectionner(null);
  const avant = bleus();
  navigateur.image();
  assert.equal(bleus(), avant, 'plus de contour');
  scene.selectionner(undefined);
  scene.selectionner({ type: 'equipe', nom: 'nulle-part' });
  navigateur.image();
  assert.equal(bleus(), avant, 'une cible absente n’entoure rien et ne plante pas');
});

test('selectionner : ne déclenche ni surClic ni surVide (la page sélectionne, la scène n’appelle pas en retour)', () => {
  const { scene, navigateur, appels } = monter();
  scene.selectionner({ type: 'utilisateur' });
  navigateur.image();
  assert.deepEqual([appels.clics.length, appels.vides], [0, 0]);
});

test('clic dans le vide : surVide ; clic sur une cible : surClic seulement', () => {
  const { navigateur, canvas, appels } = monter();
  const s = construireScene(etat());
  const p = piece(s, 'page');
  const dansLaPiece = ecranDe(navigateur, { x: p.x + 2, y: p.y + p.h - 4, w: 1, h: 1 });
  cliquer(canvas, dansLaPiece);
  assert.equal(appels.clics.length, 1);
  assert.equal(appels.vides, 0);
  cliquer(canvas, { x: 2, y: 2 });
  assert.equal(appels.vides, 1, 'hors de l’étage');
  assert.equal(appels.clics.length, 1);
});

test('mouvement réduit demandé par le système : le halo reste fixe', () => {
  const att = avecAttentes([attente('page', 'coord-page')]);
  const couleursHalo = (options) => {
    const { navigateur } = monter({ etat: att, ...options });
    const p = piece(construireScene(att), 'page');
    const vus = new Set();
    const ctx = navigateur.canvases[1].ctx;
    let deja = 0; // fillRect déjà examinés (couleurs est parallèle aux seuls fillRect de appels)
    for (let i = 0; i < 160; i++) { // plus d'une période (2,4 s à 16 ms l'image)
      navigateur.image();
      const rects = ctx.appels.filter((a) => a[0] === 'fillRect');
      rects.slice(deja).forEach((a, k) => {
        if (a[1] === p.x && a[2] === p.y && a[3] === p.w && a[4] === 2) vus.add(ctx.couleurs[deja + k]);
      });
      deja = rects.length;
    }
    return vus;
  };
  assert.ok(couleursHalo({}).size > 3, 'le halo change de teinte au fil des images');
  assert.equal(couleursHalo({ mouvementReduit: true }).size, 1, 'une seule teinte');
});

// ---- Source de la page --------------------------------------------------------------------------------------------

test('source alimentée : le premier instantané est montré sans attendre la ligne de base, même si l’hôte ne répond pas', async () => {
  const recus = [];
  const fetch = () => new Promise(() => {}); // ne répond jamais
  const source = creerSourceAlimentee({ fetch });
  source.abonner((...a) => recus.push(a));
  source.pousser({ version: '2', agents: [], equipes: [], flux: [] });
  await new Promise((r) => setTimeout(r, 5));
  assert.equal(recus.length, 1);
  assert.deepEqual(recus[0][3], { reset: true });
});

// ---- Info-bulles, confidentialité et réserves de lisibilité --------------------------------------------------------

test('info-bulle d’un agent : états en mots (jamais attend_reponse), tâche tronquée, pause sans alarme', () => {
  const e = etat();
  e.alarmes = []; // l'état d'exemple nomme presque tous les agents dans une alarme grave
  const ag = e.agents.find((a) => a.id === 'coord-page');
  ag.etat = 'attend_reponse';
  ag.tache = 'x'.repeat(200);
  e.agents.find((a) => a.id === 'coord-hote').etat = 'arrete';
  const s = construireScene(e);
  const info = infobulle(s, 'agent', 'coord-page');
  assert.equal(info.lignes[0], 'attend une réponse');
  assert.equal([...info.lignes[1]].length, TACHE_MAX);
  assert.ok(info.lignes[1].endsWith('…'));
  assert.equal(infobulle(s, 'agent', 'coord-hote').lignes[0], 'en pause', 'arrêté sans alarme : en pause, pas « arrete »');
  for (const a of s.agents) assert.ok(!infobulle(s, 'agent', a.id).lignes.some((l) => /_/.test(l) && l !== a.tache), `valeur brute : ${a.id}`);
  assert.deepEqual(infobulle(s, 'agent', 'utilisateur'), { titre: 'Utilisateur', lignes: [] });
});

test('info-bulle d’un agent arrêté avec une alarme grave : « arrêté »', () => {
  const e = etat();
  e.agents.find((a) => a.id === 'coord-hote').etat = 'arrete';
  e.alarmes = [{ id: 'g', type: 'session_disparue', gravite: 'grave', agents: ['coord-hote'], equipes: ['hote'], destinataire: 'utilisateur' }];
  assert.equal(infobulle(construireScene(e), 'agent', 'coord-hote').lignes[0], 'arrêté');
});

test('info-bulle d’un message : « de → à », genre, état en mots ; jamais le résumé', () => {
  const e = etat();
  e.flux = [{ id: 759, de: 'assistant', a: 'coord-b', nature: 'consigne', objet: null, resume: 'SECRET-PRIVE-7f3a', etat: 'pris_en_compte', debiteur: null, echeance: null, transitions: [] },
    { id: 760, de: 'coord-page', a: 'assistant', nature: 'travail_pret', objet: null, resume: 'SECRET-PRIVE-7f3a', etat: 'livre', debiteur: null, echeance: null, transitions: [] }];
  const s = construireScene(e);
  assert.deepEqual(infobulle(s, 'enveloppe', 759), { titre: 'Assistant → coord-b', lignes: ['consigne', 'pris en compte'] });
  assert.deepEqual(infobulle(s, 'enveloppe', 760), { titre: 'coord-page → Assistant', lignes: ['travail prêt', 'livré'] });
  assert.equal(JSON.stringify([infobulle(s, 'enveloppe', 759), infobulle(s, 'enveloppe', 760)]).includes('SECRET'), false);
  assert.equal(infobulle({ ...s, enveloppes: [{ id: 5, etat: 'clos', de: null, a: null }] }, 'enveloppe', 5).titre, 'message 5', 'sans expéditeur : le repli d’avant');
});

test('liseré « active » : vert, jamais de l’ambre du halo « on attend l’utilisateur »', () => {
  assert.notEqual(COULEURS.lumiere, COULEURS.ambre);
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(COULEURS.lumiere.slice(i, i + 2), 16));
  assert.ok(g > r && g > b - 30, `un vert : ${COULEURS.lumiere}`);
});

test('contour de sélection : 2 px pleins, un filet clair en dedans, un filet sombre dehors', () => {
  const s = construireScene(etat());
  const p = piece(s, 'page');
  const e = dessin(s, 0, { selection: { type: 'equipe', nom: 'page' } });
  assert.equal(barreHaut(e, p, SELECTION.trait).length, 1);
  assert.ok(e.rects.some((q) => q.c === SELECTION.clair && q.x === p.x + 2 && q.y === p.y + 2 && q.w === p.w - 4 && q.h === 1), 'filet clair');
  assert.ok(e.rects.some((q) => q.c === SELECTION.ombre && q.x === p.x - 1 && q.y === p.y - 1 && q.w === p.w + 2 && q.h === 1), 'filet sombre');
});

test('halo d’agent rouge : un cadre plein de 2 px, plus de pointillé', () => {
  const lignes = ATLAS.sprites['alerte.halo'].frames[0];
  const h = lignes.length;
  const w = lignes[0].length;
  for (const f of ATLAS.sprites['alerte.halo'].frames) {
    for (let x = 2; x < w - 2; x++) {
      assert.ok(/[Rr]/.test(f[0][x]) && /[Rr]/.test(f[h - 1][x]) && /[Rr]/.test(f[1][x]) && /[Rr]/.test(f[h - 2][x]), `côtés haut et bas pleins, colonne ${x}`);
    }
    for (let y = 2; y < h - 2; y++) assert.ok(/[Rr]/.test(f[y][0]) && /[Rr]/.test(f[y][w - 1]), `côtés gauche et droit pleins, ligne ${y}`);
  }
});

test('compteurs : « +N », « hors organigramme : N » et le nombre de la porte sont écrits à la résolution de l’écran', () => {
  const e = etat();
  e.attentes_utilisateur = [attente('page', 'coord-page')];
  const s = construireScene(e);
  assert.ok(s.porte.etat === 'agir' && s.horsOrganigramme && s.pieces.some((p) => p.compteur), 'le cas : les trois compteurs existent');
  const ctx = new FauxCanvas({}).getContext();
  ecrireCompteurs(ctx, s, { echelle: 1, x: 0, y: 0 }, { d: 1, police: 'Plex' });
  const ecrits = ctx.appels.filter((a) => a[0] === 'fillText').map((a) => a[1]);
  assert.ok(ecrits.includes(s.horsOrganigramme.texte));
  assert.ok(ecrits.includes(String(s.porte.compteur)));
  for (const p of s.pieces.filter((q) => q.compteur)) assert.ok(ecrits.includes(p.compteur.texte));
  assert.equal(ctx.appels.at(-1)[0], 'restore');
  // …et la police pixel ne les écrit plus
  const pixel = dessin(s, 0, { noms: false }).textes.map((t) => t.t);
  assert.equal(pixel.includes(s.horsOrganigramme.texte), false);
  assert.equal(pixel.includes(String(s.porte.compteur)), false, 'le nombre de la porte aussi');
  assert.equal(pixel.includes(s.pieces.find((p) => p.compteur).compteur.texte), false);
  assert.ok(dessin(s, 0).textes.some((t) => t.t === s.horsOrganigramme.texte), 'par défaut : en police pixel');
});

test('confidentialité du texte écrit à l’écran : des noms, des nombres, rien d’autre', () => {
  const e = etat();
  const a = e.agents.find((g) => g.id === 'assistant');
  Object.assign(a, { derniere_phrase: 'SECRET-PRIVE-7f3a', brouillon: { texte: 'SECRET-PRIVE-7f3a', depuis: '2026-10-11T09:00:00.000Z' } });
  e.flux.forEach((f) => Object.assign(f, { resume: 'SECRET-PRIVE-7f3a', objet: 'SECRET-PRIVE-7f3a' }));
  e.attentes_utilisateur = [{ ...attente('page', 'coord-page'), titre: 'SECRET-PRIVE-7f3a', bloque: 'SECRET-PRIVE-7f3a' }];
  const s = construireScene(e);
  const ctx = new FauxCanvas({}).getContext();
  ecrireNoms(ctx, s, { echelle: 1, x: 0, y: 0 });
  ecrireCompteurs(ctx, s, { echelle: 1, x: 0, y: 0 });
  const ecrits = ctx.appels.filter((x) => x[0] === 'fillText').map((x) => x[1]);
  assert.ok(ecrits.length > s.pieces.length);
  for (const t of ecrits) assert.ok(/^[a-z0-9?.\-…]*$/i.test(t) || /^\+\d+$/.test(t) || /^hors organigramme : \d+(\+\?)?$/.test(t), `texte inattendu : « ${t} »`);
});
