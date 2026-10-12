// Une attente est ambre, quelle que soit sa gravité ; rouge = problème et rien d'autre. Quatre éléments concernés : enveloppes du couloir, halos d'agents qui attendent,
// sirène au niveau ambre, porte de l’utilisateur et son compteur. Puis la légende.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { ATLAS } from '../../../src/cime/scene/static/graphismes/atlas.js';
import { PALETTE, ROUGES, AMBRES } from '../../../src/cime/scene/static/graphismes/palette.js';
import { construireScene } from '../../../src/cime/scene/static/modele.js';
import { dessiner, COULEURS } from '../../../src/cime/scene/static/rendu.js';
import { LEGENDE, lignes } from '../../../src/cime/scene/static/legende.js';
import { ecrireCompteurs } from '../../../src/cime/scene/static/noms.js';
import { FauxCanvas } from './faux-dom.mjs';

const ICI = dirname(fileURLToPath(import.meta.url));
const FIXTURE = join(ICI, '..', 'fixtures', 'etat-exemple.json');
const etat = () => JSON.parse(readFileSync(FIXTURE, 'utf8'));
const S = ATLAS.sprites;
const caracteres = (nom) => new Set(S[nom].frames.flatMap((img) => [...img.join('')]));
const aDuRouge = (nom) => ROUGES.some((c) => caracteres(nom).has(c));
const aDeLAmbre = (nom) => AMBRES.some((c) => caracteres(nom).has(c));

class Espion {
  constructor() { this.sprites = []; this.rects = []; this.textes = []; }
  rect(x, y, w, h, c) { this.rects.push({ x, y, w, h, c }); }
  texte(t, x, y, c) { this.textes.push({ t, x, y, c }); }
  sprite(nom, frame, x, y) { this.sprites.push({ nom, x, y }); }
}
const dessin = (scene) => {
  const e = new Espion();
  dessiner(e, ATLAS, scene, 0, { legende: false });
  return e;
};

// ---- 1. Les enveloppes échec / abandon du couloir ------------------------------------------------------------------
const avecEnvelope = (etatMsg, alarmes = []) => {
  const e = etat();
  const m = e.flux.find((q) => q.de && q.a);
  m.etat = etatMsg;
  e.alarmes = alarmes;
  return { e, m, scene: construireScene(e, null, { t: 1e9 }) };
};
const alarmeLivraison = (m, extra = {}) => ({ id: `livraison_echouee:${m.a}:msg-${m.id}`, type: 'livraison_echouee', gravite: 'grave', agents: [], equipes: [], destinataire: 'assistant', ...extra });

test('enveloppe en échec sans alarme grave : grise, jamais rouge', () => {
  for (const etatMsg of ['echec', 'abandonne']) {
    const { m, scene } = avecEnvelope(etatMsg);
    const env = scene.enveloppes.find((q) => q.id === m.id);
    assert.ok(env, `${etatMsg} : l'enveloppe reste dans le couloir`);
    assert.equal(env.couleur, 'gris', etatMsg);
    assert.equal(env.sprite, `enveloppe.${etatMsg}_gris`);
    assert.equal(aDuRouge(env.sprite), false, 'le sprite gris n’a aucun pixel rouge');
  }
});

test('enveloppe en échec que porte une alarme grave livraison_echouee : rouge', () => {
  const e = etat();
  const msg = e.flux.find((q) => q.de && q.a);
  msg.etat = 'echec';
  e.alarmes = [alarmeLivraison(msg)];
  const env = construireScene(e, null, { t: 1e9 }).enveloppes.find((q) => q.id === msg.id);
  assert.equal(env.couleur, 'rouge');
  assert.equal(env.sprite, 'enveloppe.echec');
  assert.equal(aDuRouge('enveloppe.echec'), true);
});

test('une alarme livraison_echouee sur un AUTRE message, ou qui n’est pas grave, ne rougit pas celle-ci', () => {
  const e = etat();
  const msg = e.flux.find((q) => q.de && q.a);
  msg.etat = 'echec';
  e.alarmes = [alarmeLivraison(msg, { id: `livraison_echouee:${msg.a}:msg-99999` })];
  assert.equal(construireScene(e, null, { t: 1e9 }).enveloppes.find((q) => q.id === msg.id).couleur, 'gris', 'autre message');
  e.alarmes = [alarmeLivraison(msg, { gravite: 'a_voir' })];
  assert.equal(construireScene(e, null, { t: 1e9 }).enveloppes.find((q) => q.id === msg.id).couleur, 'gris', 'pas grave');
});

// ---- 2. Les halos d'agents ------------------------------------------------------------------------------------------
const agentX = (o = {}) => ({ id: 'coord-x', role: 'coordinateur', equipe: 'x', vivant: true, etat: 'travaille', contexte: null, ...o });
const etatX = (agent, alarmes = []) => ({ equipes: [{ nom: 'x', statut: 'active' }], agents: [agentX(agent)], alarmes, attentes_utilisateur: [] });
const grave = (type, extra = {}) => ({ id: `${type}:coord-x:1`, type, gravite: 'grave', agents: ['coord-x'], equipes: ['x'], ...extra });
const haloDe = (scene) => scene.agents.find((a) => a.id === 'coord-x');

test('un agent qui attend une autorisation : halo ambre, pas rouge', () => {
  const scene = construireScene(etatX({ etat: 'attend_autorisation' }), null, { t: 0 });
  const a = haloDe(scene);
  assert.equal(a.halo, 'ambre');
  assert.notEqual(a.couleur, 'rouge');
  assert.equal(a.bulle, 'exclamation');
});

test('autorisation_en_attente et question_sans_reponse, même graves : halo ambre', () => {
  for (const type of ['autorisation_en_attente', 'question_sans_reponse']) {
    const a = haloDe(construireScene(etatX({}, [grave(type)]), null, { t: 0 }));
    assert.equal(a.halo, 'ambre', type);
    assert.notEqual(a.couleur, 'rouge', type);
  }
});

test('toute autre alarme grave nommant l’agent : halo rouge ; le rouge l’emporte sur l’ambre', () => {
  assert.equal(haloDe(construireScene(etatX({}, [grave('recouvrement')]), null, { t: 0 })).halo, 'rouge');
  const mixte = haloDe(construireScene(etatX({ etat: 'attend_autorisation' }, [grave('autorisation_en_attente'), grave('session_disparue')]), null, { t: 0 }));
  assert.equal(mixte.halo, 'rouge');
  assert.equal(mixte.couleur, 'rouge');
});

test('les deux halos se dessinent avec leur sprite : attente.halo (ambre) et alerte.halo (rouge)', () => {
  const ambre = dessin(construireScene(etatX({ etat: 'attend_autorisation' }), null, { t: 0 }));
  assert.equal(ambre.sprites.filter((s) => s.nom === 'attente.halo').length, 1);
  assert.equal(ambre.sprites.some((s) => s.nom === 'alerte.halo'), false);
  const rouge = dessin(construireScene(etatX({}, [grave('recouvrement')]), null, { t: 0 }));
  assert.equal(rouge.sprites.filter((s) => s.nom === 'alerte.halo').length, 1);
  assert.equal(rouge.sprites.some((s) => s.nom === 'attente.halo'), false);
  assert.equal(aDuRouge('attente.halo'), false);
  assert.equal(aDeLAmbre('attente.halo'), true);
  assert.deepEqual([S['attente.halo'].w, S['attente.halo'].h, S['attente.halo'].frames.length], [S['alerte.halo'].w, S['alerte.halo'].h, S['alerte.halo'].frames.length], 'même place, même taille');
});

test('la bulle « ! » d’une autorisation attendue est ambre : plus aucun rouge dans bulle.exclamation', () => {
  assert.equal(aDuRouge('bulle.exclamation'), false);
  assert.equal(aDeLAmbre('bulle.exclamation'), true);
});

// ---- 3. La sirène ---------------------------------------------------------------------------------------------------
test('sirène : rouge pour une alarme grave, ambre (sprite à part) pour une alarme à voir', () => {
  const e = etatX({}, [{ id: 'f', type: 'fige', gravite: 'a_voir', agents: [], equipes: ['x'] }]);
  const ambre = construireScene(e, null, { t: 0 });
  assert.equal(ambre.pieces.find((p) => p.nom === 'x').sirene, 'ambre');
  const d = dessin(ambre);
  assert.equal(d.sprites.filter((s) => s.nom === 'attente.sirene').length, 1);
  assert.equal(d.sprites.some((s) => s.nom === 'alerte.sirene'), false, 'pas de sirène rouge au niveau ambre');
  const r = dessin(construireScene(etatX({}, [{ id: 'f', type: 'fige', gravite: 'grave', agents: [], equipes: ['x'] }]), null, { t: 0 }));
  assert.equal(r.sprites.filter((s) => s.nom === 'alerte.sirene').length, 1);
  assert.equal(r.sprites.some((s) => s.nom === 'attente.sirene'), false);
  assert.equal(aDuRouge('attente.sirene'), false);
  assert.equal(aDeLAmbre('attente.sirene'), true);
  assert.deepEqual([S['attente.sirene'].w, S['attente.sirene'].h, S['attente.sirene'].frames.length], [S['alerte.sirene'].w, S['alerte.sirene'].h, S['alerte.sirene'].frames.length]);
});

// ---- 4. La porte de l’utilisateur et son compteur --------------------------------------------------------------------------
test('porte de l’utilisateur : quand il doit agir, ambre (sprite, compteur), jamais rouge', () => {
  const scene = construireScene(etat(), null, { t: 0 });
  assert.equal(scene.porte.etat, 'agir');
  assert.equal(scene.porte.couleur, 'ambre');
  assert.equal(aDuRouge('porte.utilisateur.agir'), false);
  assert.equal(aDeLAmbre('porte.utilisateur.agir'), true);
  const d = dessin(scene);
  assert.ok(d.sprites.some((s) => s.nom === 'porte.utilisateur.agir'));
  const compteur = d.textes.find((t) => t.t === String(scene.porte.compteur) && t.x === scene.porte.x - 12);
  assert.ok(compteur, 'le compteur de la porte est écrit (police pixel)');
  assert.equal(compteur.c, COULEURS.ambre_texte);
});

test('compteur de la porte écrit à la résolution de l’écran : ambre, jamais rouge', () => {
  const scene = construireScene(etat(), null, { t: 0 });
  const ctx = new FauxCanvas({}).getContext();
  ecrireCompteurs(ctx, scene, { x: 0, y: 0, echelle: 2 }, { d: 1 });
  const textes = ctx.appels.filter((a) => a[0] === 'fillText');
  const i = textes.findIndex((a) => a[1] === String(scene.porte.compteur));
  assert.ok(i >= 0, 'le compteur est écrit');
  assert.equal(ctx.couleursTexte[i], COULEURS.ambre_texte);
  const [, v, b] = [0, 1, 2].map((k) => parseInt(COULEURS.ambre_texte.slice(1 + 2 * k, 3 + 2 * k), 16));
  assert.ok(v > b * 2 && v > 0x30, 'une teinte ambre (jaune-orangé), jamais un rouge');
});

test('porte : seulement des rapports → à lire (neutre), les autres attentes → à agir (ambre) ; la palette ne la dit plus alerte', () => {
  const e = etat();
  e.attentes_utilisateur = e.attentes_utilisateur.filter((a) => a.nature === 'rapport_utilisateur');
  const calme = construireScene(e, null, { t: 0 }).porte;
  assert.ok(['attente', 'fermee'].includes(calme.etat));
  assert.notEqual(calme.couleur, 'rouge');
  assert.equal(S['porte.utilisateur.alerte'], undefined, 'plus de sprite de porte « alerte » (rouge)');
});

// ---- 5. La légende --------------------------------------------------------------------------------------------------
test('légende : « attend autorisation », « l’utilisateur doit agir » et la sirène ambre ne sont plus des problèmes', () => {
  const par = (cle) => LEGENDE.find((e) => (e.sprite ?? e.motif) === cle);
  assert.equal(par('perso.worker.attend_autorisation')?.probleme, undefined);
  assert.notEqual(par('porte.utilisateur.agir')?.probleme, true);
  assert.ok(par('porte.utilisateur.agir'), 'entrée « l’utilisateur doit agir »');
  assert.deepEqual(lignes(par('porte.utilisateur.agir')), ['Utilisateur', 'doit agir']);
  assert.ok(par('attente.sirene'), 'entrée sirène ambre');
  assert.notEqual(par('attente.sirene').probleme, true);
  assert.equal(par('alerte.sirene').probleme, true, 'la sirène rouge reste un problème');
  assert.ok(par('attente.halo'), 'entrée halo d’agent ambre');
  assert.notEqual(par('attente.halo').probleme, true);
  assert.equal(par('alerte.halo').probleme, true);
});

test('légende : les enveloppes grises (échec, abandon sans alarme) et les rouges (avec alarme) ont chacune leur entrée', () => {
  const par = (cle) => LEGENDE.find((e) => (e.sprite ?? e.motif) === cle);
  for (const n of ['enveloppe.echec_gris', 'enveloppe.abandonne_gris']) {
    assert.ok(par(n), n);
    assert.notEqual(par(n).probleme, true, n);
  }
  for (const n of ['enveloppe.echec', 'enveloppe.abandonne']) assert.equal(par(n).probleme, true, n);
});

test('aucun rouge de pièce, d’agent ni de porte sur un état d’exemple sans alarme grave', () => {
  const e = etat();
  e.alarmes = e.alarmes.filter((a) => a.gravite !== 'grave');
  const scene = construireScene(e, null, { t: 1e9 });
  assert.equal(scene.agents.some((a) => a.halo === 'rouge' || a.couleur === 'rouge'), false);
  assert.equal(scene.pieces.some((p) => p.couleur === 'rouge'), false);
  assert.notEqual(scene.porte.couleur, 'rouge');
  assert.equal(scene.enveloppes.some((q) => q.couleur === 'rouge'), false);
  void PALETTE;
});
