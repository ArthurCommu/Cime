// Une ligne de test par ligne de la table « fait → animation », plus la sincérité et le rouge réservé aux problèmes.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { TABLE, ETATS_AGENT, animationAgent, indexer } from '../../../src/cime/scene/static/animations.js';
import { construireScene } from '../../../src/cime/scene/static/modele.js';
import { infobulle } from '../../../src/cime/scene/static/interaction.js';

const scene0 = (over = {}) => ({
  version: 2, agents: [], equipes: [], flux: [], ordres: [], alarmes: [], aretes: [], attentes_utilisateur: [],
  facteur: { battement: 'x', age_s: 1, arrete: false }, ...over,
});

const agent = (over = {}) => ({
  id: 'coord-x', role: 'coordinateur', equipe: 'x', parent: 'assistant', vivant: true, etat: 'travaille',
  tache: null, contexte: { tokens: 10, limite: 100 }, cout_usd_estime: 1.5, brouillon: null, ...over,
});
const anim = (ag, etat = {}, eph = new Map()) =>
  animationAgent(ag, { idx: indexer({ alarmes: [], ordres: [], ...etat }), ephemere: eph });
const alarme = (over) => ({ id: 'a', type: 'fige', gravite: 'a_voir', agents: [], equipes: [], ...over });
const ordre = (over) => ({ id: 1, auteur: 'assistant', verbe: 'compacter', cible: 'coord-x', etat: 'execute', ...over });

test('la table couvre les lignes 1 à 28, sans trou', () => {
  assert.deepEqual(TABLE.map((r) => r.id), Array.from({ length: 28 }, (_, i) => i + 1));
});

test('animation 1 : travaille sans activité → taper', () => {
  const a = anim(agent());
  assert.equal(a.sprite, 'perso.coordinateur.taper');
  assert.equal(a.raison, 1);
  assert.equal(a.couleur, 'normal');
});

for (const [activite, anim2, ecran] of [
  ['ecrire', 'ecrire', 'ecran.texte'],
  ['lire', 'lire', 'ecran.lecture'],
  ['executer', 'executer', 'ecran.terminal'],
  ['reflechir', 'reflechir', 'ecran.pensee'],
]) {
  test(`animation 2 : activité « ${activite} » → ${anim2} et son écran`, () => {
    const a = anim(agent({ activite }));
    assert.equal(a.sprite, `perso.coordinateur.${anim2}`);
    assert.equal(a.ecran, ecran);
    assert.equal(a.raison, 2);
  });
}

test('animation 2 : une activité inconnue retombe sur taper, jamais une activité devinée', () => {
  const a = anim(agent({ activite: 'danser' }));
  assert.equal(a.sprite, 'perso.coordinateur.taper');
  assert.equal(a.raison, 1);
});

test('animation 3 : au repos → dormir et bulle zzz', () => {
  const a = anim(agent({ etat: 'au_repos' }));
  assert.equal(a.sprite, 'perso.coordinateur.dormir');
  assert.equal(a.bulle, 'zzz');
  assert.equal(a.raison, 3);
});

test('animation 4 : attend une réponse → attend_reponse et bulle question', () => {
  const a = anim(agent({ etat: 'attend_reponse' }));
  assert.equal(a.sprite, 'perso.coordinateur.attend_reponse');
  assert.equal(a.bulle, 'question');
  assert.equal(a.raison, 4);
  assert.equal(a.couleur, 'normal');
});

test('animation 5 : attend une autorisation → exclamation, halo ambre, couleur ambre (une attente n’est pas un problème)', () => {
  const a = anim(agent({ etat: 'attend_autorisation' }));
  assert.equal(a.sprite, 'perso.coordinateur.attend_autorisation');
  assert.equal(a.bulle, 'exclamation');
  assert.equal(a.halo, 'ambre');
  assert.equal(a.couleur, 'ambre');
  assert.equal(a.raison, 5);
});

test('animation 6 : arrêté → pas de personnage, chaise et bureau vides', () => {
  const a = anim(agent({ etat: 'arrete', vivant: false }));
  assert.equal(a.sprite, null);
  assert.equal(a.chaise, 'vide');
  assert.equal(a.bureau, 'vide');
  assert.equal(a.raison, 6);
  assert.equal(a.couleur, 'gris');
});

test('animation 7 : état inconnu → silhouette grise, jauge et coût « ? »', () => {
  const a = anim(agent({ etat: 'inconnu' }));
  assert.equal(a.sprite, 'perso.coordinateur.inconnu');
  assert.equal(a.raison, 7);
  assert.equal(a.jauge.inconnu, true);
  assert.equal(a.jauge.couleur, 'gris');
  assert.deepEqual(a.cout, { texte: '?', couleur: 'gris' });
});

test('animation 7 : vivant == null (non mesuré) → inconnu, jamais zéro', () => {
  const a = anim(agent({ vivant: null, etat: 'travaille' }));
  assert.equal(a.sprite, 'perso.coordinateur.inconnu');
  assert.equal(a.raison, 7);
});

test('animation 8 : compactage en cours → sieste', () => {
  const a = anim(agent(), { ordres: [ordre({ etat: 'execute' })] });
  assert.equal(a.sprite, 'perso.coordinateur.sieste');
  assert.equal(a.raison, 8);
});

test('animation 8 : compactage en échec → icône de refus rouge', () => {
  const a = anim(agent(), { ordres: [ordre({ etat: 'echec' })] });
  assert.equal(a.alerte.couleur, 'rouge');
  assert.equal(a.couleur, 'rouge');
  assert.ok(a.raisons.includes(8));
});

test('animation 9 : arrivée d’un agent → arrive', () => {
  const eph = new Map([['coord-x', { type: 'arrive', debut: 0 }]]);
  const a = anim(agent(), {}, eph);
  assert.equal(a.sprite, 'perso.coordinateur.arrive');
  assert.equal(a.raison, 9);
});

test('animation 10 : ordre terminer exécuté → fin_tache', () => {
  const a = anim(agent({ role: 'worker' }), { ordres: [ordre({ verbe: 'terminer', etat: 'execute' })] });
  assert.equal(a.sprite, 'perso.worker.fin_tache');
  assert.equal(a.raison, 10);
});

test('animation 18 : alarme grave sur l’agent → halo rouge', () => {
  const a = anim(agent(), { alarmes: [alarme({ gravite: 'grave', agents: ['coord-x'] })] });
  assert.equal(a.halo, 'rouge');
  assert.equal(a.couleur, 'rouge');
  assert.ok(a.raisons.includes(18));
});

test('animation 18 : alarme grave qui ne nomme que l’équipe → aucun halo (la bordure de la pièce passe au rouge)', () => {
  const a = anim(agent(), { alarmes: [alarme({ gravite: 'grave', agents: [], equipes: ['x'] })] });
  assert.equal(a.halo, null);
});

test('animation 19 : alarme à voir → marque ambre, jamais rouge', () => {
  const a = anim(agent(), { alarmes: [alarme({ gravite: 'a_voir', agents: ['coord-x'] })] });
  assert.equal(a.marque, 'ambre');
  assert.equal(a.couleur, 'ambre');
  assert.equal(a.halo, null);
  assert.ok(a.raisons.includes(19));
});

test('animation 20 : refus du garde pendant 3 s → éclair', () => {
  const eph = new Map([['coord-x', { type: 'refus', debut: 0 }]]);
  const a = anim(agent(), {}, eph);
  assert.equal(a.alerte.couleur, 'ambre');
  assert.ok(a.raisons.includes(20));
  assert.notEqual(a.couleur, 'rouge');
});

test('animation 22 : contexte à 70 % → jauge ambre ; à 30 % → normale', () => {
  const haut = anim(agent({ contexte: { tokens: 70, limite: 100 } }));
  assert.equal(haut.jauge.couleur, 'ambre');
  assert.equal(haut.jauge.niveau, 0.7);
  const bas = anim(agent({ contexte: { tokens: 30, limite: 100 } }));
  assert.equal(bas.jauge.couleur, 'normal');
});

test('animation 22 : contexte null → jauge grise « ? »', () => {
  const a = anim(agent({ contexte: null }));
  assert.equal(a.jauge.inconnu, true);
  assert.equal(a.jauge.couleur, 'gris');
  assert.equal(a.jauge.niveau, null);
});

test('animation 23 : coût estimé → montant à deux décimales ; null → « ? » gris', () => {
  assert.deepEqual(anim(agent({ cout_usd_estime: 1.5 })).cout, { texte: '1.50', couleur: 'normal' });
  assert.deepEqual(anim(agent({ cout_usd_estime: null })).cout, { texte: '?', couleur: 'gris' });
});

test('animation 25 : brouillon présent → bulle de saisie, sans texte', () => {
  const a = anim(agent({ brouillon: { texte: 'secret', depuis: 'x' } }));
  assert.equal(a.brouillon, true);
  assert.ok(a.raisons.includes(25));
  assert.equal(JSON.stringify(a).includes('secret'), false);
});

test('sincérité : au repos, jamais d’animation de travail', () => {
  const a = anim(agent({ etat: 'au_repos', activite: 'ecrire' }));
  assert.equal(a.sprite, 'perso.coordinateur.dormir');
  assert.equal(a.ecran, null);
});

test('sincérité : une activité présente sur un agent qui n’est pas travaille est ignorée', () => {
  const a = anim(agent({ etat: 'attend_reponse', activite: 'ecrire' }));
  assert.equal(a.sprite, 'perso.coordinateur.attend_reponse');
});

test('sincérité : une alarme à voir n’est jamais rouge, même isolée', () => {
  for (const type of ['fige', 'brouillon', 'contexte_plein']) {
    const a = anim(agent({ etat: 'au_repos' }), { alarmes: [alarme({ type, gravite: 'a_voir', agents: ['coord-x'] })] });
    assert.notEqual(a.couleur, 'rouge', type);
    assert.equal(a.halo, null, type);
  }
});

test('sincérité : un agent non mesuré n’a jamais d’animation de travail', () => {
  const a = anim(agent({ contexte: null, vivant: null, etat: 'travaille', activite: 'ecrire' }));
  assert.equal(a.sprite, 'perso.coordinateur.inconnu');
  assert.equal(a.ecran, null);
});

// Coordinateur endormi (repos, sans dette) : il se dessine comme au repos, ni inconnu ni arrêté.
test('endormi : connu, ni inconnu ni arrêté, vivant: false compris', () => {
  assert.ok(ETATS_AGENT.includes('endormi'));
  const a = anim(agent({ etat: 'endormi', vivant: false, session_tmux: null }));
  assert.notEqual(a.sprite, 'perso.coordinateur.inconnu');
  assert.notEqual(a.raison, 6);
  assert.notEqual(a.chaise, 'vide');
});

test('endormi : sprite dormir, bulle zzz, couleur normal, ligne 3', () => {
  const a = anim(agent({ etat: 'endormi', vivant: false }));
  assert.equal(a.sprite, 'perso.coordinateur.dormir');
  assert.equal(a.bulle, 'zzz');
  assert.equal(a.couleur, 'normal');
  assert.equal(a.raison, 3);
  assert.ok(a.raisons.includes(3));
  assert.equal(a.ecran, null);
});

test('endormi : dessiné exactement comme au repos', () => {
  const repos = anim(agent({ etat: 'au_repos' }));
  const endormi = anim(agent({ etat: 'endormi', vivant: false }));
  assert.deepEqual(endormi, repos);
});

test('endormi : aucun halo, rouge ni gris, même avec les alarmes de sa pièce à voir', () => {
  const a = anim(agent({ etat: 'endormi', vivant: false }));
  assert.equal(a.halo, null);
  assert.equal(a.alerte, null);
  assert.notEqual(a.couleur, 'rouge');
  assert.notEqual(a.couleur, 'gris');
  assert.equal(a.marque, null);
});

test('endormi : une alarme grave qui le nomme donne le halo rouge, comme pour tout agent (pas de cas particulier)', () => {
  const a = anim(agent({ etat: 'endormi', vivant: false }), { alarmes: [alarme({ type: 'fige', gravite: 'grave', agents: ['coord-x'] })] });
  assert.equal(a.halo, 'rouge');
});

test('endormi : garde son bureau et sa chaise', () => {
  const a = anim(agent({ etat: 'endormi', vivant: false }));
  assert.equal(a.bureau, 'plein');
  assert.equal(a.chaise, 'occupee');
});

test('endormi : l’info-bulle dit « au repos », jamais la valeur brute', () => {
  const scene = construireScene(scene0({
    agents: [{ id: 'coord-x', role: 'coordinateur', equipe: 'x', vivant: false, etat: 'endormi', session_tmux: null, tache: null, contexte: null, cout_usd_estime: null, brouillon: null }],
    equipes: [{ nom: 'x', statut: 'au_repos' }],
  }), null, { t: 0 });
  const info = infobulle(scene, 'agent', 'coord-x');
  assert.equal(info.lignes[0], 'au repos');
  assert.equal(JSON.stringify(info).includes('endormi'), false);
});

test('endormi : dans la scène, le coordinateur n’est pas replié et garde son poste', () => {
  const scene = construireScene(scene0({
    agents: [{ id: 'coord-x', role: 'coordinateur', equipe: 'x', vivant: false, etat: 'endormi', session_tmux: null, tache: null, contexte: null, cout_usd_estime: null, brouillon: null }],
    equipes: [{ nom: 'x', statut: 'au_repos' }],
  }), null, { t: 0 });
  const a = scene.agents.find((g) => g.id === 'coord-x');
  assert.ok(a, 'le coordinateur est dessiné');
  assert.ok(a.bureauRect, 'il garde son bureau');
  assert.equal(a.sprite, 'perso.coordinateur.dormir');
  assert.equal(a.halo, null);
  const piece = scene.pieces.find((p) => p.nom === 'x');
  assert.ok(piece, 'la pièce de l’équipe existe');
  assert.equal(piece.compteur ?? null, null, 'aucun compteur de repli');
  assert.notEqual(piece.couleur, 'rouge');
});
