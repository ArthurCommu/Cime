// Couleurs et états : le rouge signifie un problème et rien d'autre.
// Une pièce dont l'équipe est « bloquee » (un agent attend une réponse ou une autorisation) n'est plus rouge pour autant :
// rouge seulement si l'équipe porte une alarme grave ; sinon neutre (le halo ambre dit déjà « l’utilisateur attend »).
// Et aucune info-bulle ne montre une valeur brute du registre.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ATLAS } from '../../../src/cime/scene/static/graphismes/atlas.js';
import { construireScene } from '../../../src/cime/scene/static/modele.js';
import { dessiner, causeDePiece, COULEURS } from '../../../src/cime/scene/static/rendu.js';
import { infobulle } from '../../../src/cime/scene/static/interaction.js';
import { LEGENDE, lignes } from '../../../src/cime/scene/static/legende.js';
import { ETATS_AGENT } from '../../../src/cime/scene/static/animations.js';

const agent = (i, o = {}) => ({ id: `coord-x${i}`, role: 'coordinateur', equipe: 'x', vivant: true, etat: 'travaille', contexte: null, ...o });
const etatBloque = ({ agents = [agent(0, { etat: 'attend_reponse' })], alarmes = [], attentes = [], statut = 'bloquee' } = {}) => ({
  equipes: [{ nom: 'x', statut }],
  agents,
  alarmes,
  attentes_utilisateur: attentes,
});
const piece = (scene, nom = 'x') => scene.pieces.find((p) => p.nom === nom);
const grave = (extra = {}) => ({ id: 'g', type: 'recouvrement', gravite: 'grave', agents: [], equipes: ['x'], ...extra });

class Espion {
  constructor() { this.rects = []; }
  rect(x, y, w, h, c) { this.rects.push({ x, y, w, h, c }); }
  texte() {}
  sprite() {}
}
const dedans = (r, z) => r.x >= z.x && r.y >= z.y && r.x + r.w <= z.x + z.w && r.y + r.h <= z.y + z.h;
const rougesDans = (scene, z) => {
  const e = new Espion();
  dessiner(e, ATLAS, scene, 0, { legende: false });
  return e.rects.filter((r) => r.c === COULEURS.rouge && dedans(r, z));
};

test('une équipe « bloquee » dont un agent attend, sans alarme grave : la pièce n’est pas rouge', () => {
  const scene = construireScene(etatBloque(), null, { t: 0 });
  const p = piece(scene);
  assert.notEqual(p.statut, 'rouge');
  assert.notEqual(p.couleur, 'rouge');
  assert.equal(p.statut, 'attend', 'un statut à elle : ni active, ni au repos, ni terminée');
  assert.equal(causeDePiece(p, scene.agents), null, 'pas de pièce rouge : pas de cause à montrer, pas de « ? »');
  assert.equal(rougesDans(scene, p).length, 0, 'aucun aplat rouge dans la pièce');
});

test('pièce « bloquee » sans cause visible : plus de bordure rouge ni de « ? » deviné', () => {
  const scene = construireScene(etatBloque({ agents: [agent(0)] }), null, { t: 0 });
  const p = piece(scene);
  assert.notEqual(p.couleur, 'rouge');
  assert.equal(causeDePiece(p, scene.agents), null);
});

test('une alarme grave qui nomme l’équipe rend la pièce rouge, quel que soit son statut', () => {
  for (const statut of ['bloquee', 'active', 'au_repos']) {
    const scene = construireScene(etatBloque({ statut, alarmes: [grave()] }), null, { t: 0 });
    const p = piece(scene);
    assert.equal(p.statut, 'rouge', statut);
    assert.equal(p.couleur, 'rouge', statut);
    assert.ok(rougesDans(scene, p).length > 0, `${statut} : le cadre rouge est dessiné`);
  }
});

test('une alarme « à voir » ne met pas la pièce en rouge', () => {
  const scene = construireScene(etatBloque({ alarmes: [grave({ gravite: 'a_voir' })] }), null, { t: 0 });
  assert.notEqual(piece(scene).couleur, 'rouge');
});

test('une équipe bloquée qui attend l’utilisateur : cadre neutre et halo ambre (jamais rouge)', () => {
  const att = { id: 'a1', message_id: 1, objet: null, nature: 'decision', titre: 't', bloque: 'b', depuis: '2026-10-11T09:00:00.000Z', agent: 'coord-x0', equipe: 'x', actions: ['trancher'] };
  const scene = construireScene(etatBloque({ attentes: [att] }), null, { t: 0 });
  const p = piece(scene);
  assert.equal(p.attentes, 1);
  assert.equal(p.couleur !== 'rouge', true);
  assert.equal(rougesDans(scene, p).length, 0);
});

test('une pièce neutre « en attente » se distingue d’une pièce terminée ou non mesurée', () => {
  const e = etatBloque();
  e.equipes.push({ nom: 'y', statut: 'terminee' }, { nom: 'z', statut: null });
  const scene = construireScene(e, null, { t: 0 });
  const statuts = new Set(['x', 'y', 'z'].map((n) => piece(scene, n)?.statut).filter(Boolean));
  assert.equal(statuts.size, 3, 'trois statuts différents');
});

test('légende : « bloquée » rouge disparaît ; le rouge de pièce dit « alarme grave », le neutre « en attente »', () => {
  const bordures = LEGENDE.filter((e) => e.motif?.startsWith('bordure.'));
  const rouge = bordures.find((e) => e.motif === 'bordure.rouge');
  const attend = bordures.find((e) => e.motif === 'bordure.attend');
  assert.ok(rouge && attend, 'les deux bordures existent');
  assert.equal(rouge.probleme, true);
  assert.deepEqual(lignes(rouge), ['alarme', 'grave']);
  assert.notEqual(attend.probleme, true, 'le neutre n’est pas un signe de problème');
  assert.deepEqual(lignes(attend), ['en', 'attente']);
  assert.equal(LEGENDE.some((e) => /bloqu/i.test(e.libelle)), false, 'plus de « bloquée » dans la légende');
});

test('la couleur d’une pièce en attente n’est ni le rouge, ni l’ambre du halo', () => {
  assert.ok(COULEURS.attente);
  assert.notEqual(COULEURS.attente, COULEURS.rouge);
  assert.notEqual(COULEURS.attente, COULEURS.ambre);
  assert.notEqual(COULEURS.attente, COULEURS.gris);
});

test('info-bulle : jamais une valeur brute du registre (pas de « _ », pas de préfixe « état : »)', () => {
  const brut = /_|état\s*:|etat\s*:/i;
  const agents = [...ETATS_AGENT, 'inconnu', undefined, null].map((etat, i) => agent(i, { etat, tache: 'une tâche' }));
  const e = etatBloque({ agents });
  e.equipes.push(...['active', 'au_repos', 'bloquee', 'terminee', null].map((s, i) => ({ nom: `q${i}`, statut: s })));
  const scene = construireScene(e, null, { t: 0 });
  for (const a of scene.agents) {
    const info = infobulle(scene, 'agent', a.id);
    assert.ok(info, a.id);
    for (const l of [info.titre.replace(/^coord-/, ''), ...info.lignes.filter((l) => l !== a.tache)]) assert.doesNotMatch(l, brut, `${a.id} : ${l}`);
  }
  for (const p of scene.pieces.filter((q) => q.nom !== 'assistant')) {
    const info = infobulle(scene, 'piece', p.nom);
    for (const l of info.lignes) assert.doesNotMatch(l, brut, `${p.nom} : ${l}`);
  }
  assert.deepEqual(infobulle(scene, 'agent', 'coord-x1').lignes.slice(0, 1), ['au repos']);
  assert.equal(infobulle(scene, 'piece', 'x').lignes[0], 'en attente');
  assert.equal(infobulle(construireScene(etatBloque({ alarmes: [grave()] }), null, { t: 0 }), 'piece', 'x').lignes[0], 'alarme grave');
});
