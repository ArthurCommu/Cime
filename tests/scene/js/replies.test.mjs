// Arrêtés repliés (REPLIER = worker) et agents hors organigramme : rien ne disparaît sans être compté.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { ATLAS } from '../../../src/cime/scene/static/graphismes/atlas.js';
import { creerSourceRejouee } from './support/source-rejouee.mjs';
import { creerFil, appliquerSnapshot, sceneA, construireScene } from '../../../src/cime/scene/static/modele.js';
import { disposition, largeurTexte, abreger, GEOM, REPLIER, largeurCompteur } from '../../../src/cime/scene/static/plan.js';

const ICI = dirname(fileURLToPath(import.meta.url));
const FIXTURES = join(ICI, '..', 'fixtures');
const REEL = join(FIXTURES, 'etat-structure.json');
const EXEMPLE = join(FIXTURES, 'etat-exemple.json');
const lire = (f) => JSON.parse(readFileSync(f, 'utf8'));
const copie = (e) => JSON.parse(JSON.stringify(e));
const POLICE = ATLAS.police;
const SIGNE = ATLAS.sprites['compteur.dossiers'];

// Un agent de l'état : rôle, état, équipe.
const agent = (id, role, equipe, etat = 'travaille') => ({
  id, role, equipe, vivant: true, etat, tache: null, brouillon: null,
  contexte: { tokens: 50000, limite: 200000 }, cout_usd_estime: 1.2,
});

// Une équipe « abcdefghijkl » (12 lettres, rang impair : rangée du bas, porte) avec un coordinateur et n workers arrêtés.
function etatAvecArretes(n, { sessions = [], autres = [] } = {}) {
  const equipes = [{ nom: 'fondation', statut: 'active' }, { nom: 'abcdefghijkl', statut: 'active' }, { nom: 'hote', statut: 'active' }];
  const agents = [agent('assistant', 'assistant', null), { ...agent('utilisateur', 'utilisateur', null), vivant: null, etat: 'inconnu' }];
  for (const e of equipes) agents.push(agent(`coord-${e.nom}`, 'coordinateur', e.nom));
  for (let i = 0; i < n; i++) agents.push(agent(`w-${i}`, 'worker', 'abcdefghijkl', 'arrete'));
  agents.push(...autres);
  return { equipes, agents, flux: [], ordres: [], alarmes: [], aretes: [], attentes_utilisateur: [], facteur: null, sessions_hors_organigramme: sessions };
}

// Scène de l'état d'exemple à t, comme l'appli la dessine (source rejouée, fil, sceneA).
function exempleA(t) {
  const source = creerSourceRejouee({ etatInitial: lire(EXEMPLE) });
  const fil = creerFil();
  source.abonner((etat, trs, tStep, { reset }) => appliquerSnapshot(fil, etat, trs, tStep, { reset }));
  source.avancerA(t);
  return { etat: fil.etat, scene: sceneA(fil, t), fil };
}

const postesDe = (plan) => [...plan.sieges.entries()];

test('(a) réel anonymisé : postes dessinés = coordinateurs + agents non arrêtés + inconnu (sans l’utilisateur, qui n’a pas de poste)', () => {
  const etat = lire(REEL);
  const plan = disposition(etat);
  // L’utilisateur n'a pas de poste ; un agent hors organigramme (équipe absente de equipes[]) n'en a pas non plus ;
  // un worker arrêté (REPLIER) est replié. Les coordinateurs gardent leur poste, arrêtés ou non.
  const dansOrganigramme = (a) => a.role === 'assistant' || !a.equipe || etat.equipes.some((e) => e.nom === a.equipe);
  const attendu = etat.agents.filter(
    (a) => a.role !== 'utilisateur' && dansOrganigramme(a) && !(REPLIER.includes(a.role) && a.etat === 'arrete'),
  );
  assert.equal(plan.sieges.size, attendu.length, `postes : ${plan.sieges.size}, attendu ${attendu.length}`);
});

test('(a) réel anonymisé : postes + compteurs = agents de chaque pièce (rien ne disparaît sans être compté)', () => {
  const etat = lire(REEL);
  const plan = disposition(etat);
  for (const e of etat.equipes) {
    const dansEquipe = etat.agents.filter((a) => a.equipe === e.nom);
    const postes = postesDe(plan).filter(([, s]) => s.piece === e.nom).length;
    const p = plan.pieces.find((q) => q.nom === e.nom);
    const repliés = p.repliés ?? 0;
    assert.equal(postes + repliés, dansEquipe.length, `équipe ${e.nom} : ${postes} postes + ${repliés} repliés ≠ ${dansEquipe.length} agents`);
  }
});

test('(a) réel anonymisé : aucune pièce « essai », le compteur hors organigramme vaut 1 (worker-essai-tache-01) + 0 session', () => {
  const etat = lire(REEL);
  const plan = disposition(etat);
  assert.ok(!plan.pieces.some((p) => p.nom === 'essai'), 'une pièce « essai » existe encore');
  assert.ok(plan.horsOrganigramme, 'pas de compteur hors organigramme');
  assert.equal(plan.horsOrganigramme.n, 1);
  assert.equal(plan.horsOrganigramme.texte, 'hors organigramme : 1');
  assert.equal(plan.horsOrganigramme.inconnu, false);
});

test('(a) réel anonymisé : le hors organigramme se compte aussi avec des sessions (N = agents + len(sessions))', () => {
  const etat = lire(REEL);
  etat.sessions_hors_organigramme = [{ nom: 'cc-essai-tmux' }, { nom: 'cc-bac' }];
  const plan = disposition(etat);
  assert.equal(plan.horsOrganigramme.n, 3);
  assert.equal(plan.horsOrganigramme.texte, 'hors organigramme : 3');
});

test('(b) sessions null (tmux en échec) : « N+? », jamais un zéro', () => {
  const etat = lire(REEL);
  etat.sessions_hors_organigramme = null;
  const plan = disposition(etat);
  assert.equal(plan.horsOrganigramme.texte, 'hors organigramme : 1+?');
  assert.equal(plan.horsOrganigramme.inconnu, true);
});

test('(b) sessions null sans aucun agent hors organigramme : le compteur reste, « 0+? » (jamais un zéro seul)', () => {
  const etat = etatAvecArretes(0);
  etat.sessions_hors_organigramme = null;
  const plan = disposition(etat);
  assert.equal(plan.horsOrganigramme.texte, 'hors organigramme : 0+?');
});

test('pas de compteur hors organigramme quand rien à compter et sessions = []', () => {
  assert.equal(disposition(etatAvecArretes(2)).horsOrganigramme, null);
});

test('hors organigramme : aucune pièce pour l’équipe absente, et aucun siège pour ses agents', () => {
  const etat = etatAvecArretes(0, { autres: [agent('w-essai', 'worker', 'essai')] });
  const plan = disposition(etat);
  assert.ok(!plan.pieces.some((p) => p.nom === 'essai'));
  assert.ok(!plan.sieges.has('w-essai'));
  assert.equal(plan.horsOrganigramme.n, 1);
});

test('un worker « inconnu » n’est jamais replié : silhouette grise, à son poste', () => {
  const etat = etatAvecArretes(0, { autres: [agent('w-inconnu', 'worker', 'abcdefghijkl', 'inconnu')] });
  const plan = disposition(etat);
  assert.ok(plan.sieges.has('w-inconnu'));
  assert.equal(plan.pieces.find((p) => p.nom === 'abcdefghijkl').repliés ?? 0, 0);
});

test('un coordinateur arrêté garde son poste (chaise vide)', () => {
  const etat = etatAvecArretes(0);
  etat.agents.find((a) => a.id === 'coord-hote').etat = 'arrete';
  const plan = disposition(etat);
  assert.ok(plan.sieges.has('coord-hote'));
});

test('(c) en-tête : nom entier, compteur et sirène sans recouvrement, à 0, 1, 9, 10 et 99 arrêtés', () => {
  for (const n of [0, 1, 9, 10, 99]) {
    const plan = disposition(etatAvecArretes(n));
    const p = plan.pieces.find((q) => q.nom === 'abcdefghijkl');
    const z = p.nomZone;
    assert.equal(abreger(POLICE, p.nom, z.w), p.nom, `${n} : le nom n’entre pas en entier`);
    const sireneGauche = p.sireneAncre.x - ATLAS.sprites['alerte.sirene'].pivot[0];
    if (n === 0) {
      assert.equal(p.compteur, null, '0 arrêté : pas de compteur');
      continue;
    }
    const c = p.compteur;
    assert.equal(c.n, n);
    assert.equal(c.texte, `+${n}`);
    assert.ok(z.x + z.w <= c.x, `${n} : le compteur couvre le nom`);
    assert.ok(c.x + c.w <= p.causeAncre.x, `${n} : le compteur recouvre le « ? »`);
    assert.ok(p.causeAncre.x + GEOM.CAUSE_W < sireneGauche, `${n} : le « ? » recouvre la sirène`);
    assert.equal(c.w, largeurCompteur(`+${n}`));
    assert.ok(c.y >= p.y && c.y + SIGNE.h <= p.y + GEOM.ENTETE_H, `${n} : le compteur sort de l’en-tête`);
    if (p.porteSprite) assert.ok(p.porteSprite.x + GEOM.PORTE_W <= c.x, `${n} : la porte recouvre le compteur`);
  }
});

test('(c) une pièce sans aucun poste restant garde une largeur minimale (nom + compteur + sirène) et la hauteur d’un poste', () => {
  const etat = etatAvecArretes(3);
  etat.agents = etat.agents.filter((a) => a.id !== 'coord-abcdefghijkl'); // plus aucun poste dans cette pièce
  const plan = disposition(etat);
  const p = plan.pieces.find((q) => q.nom === 'abcdefghijkl');
  assert.equal(postesDe(plan).filter(([, s]) => s.piece === p.nom).length, 0, 'il reste des postes');
  assert.ok(p.w >= 2 * GEOM.MUR + largeurTexte(POLICE, p.nom) + GEOM.CAUSE_W + GEOM.SIRENE_W + largeurCompteur('+3'), `largeur ${p.w}`);
  assert.ok(p.h >= GEOM.ENTETE_H + 2 * GEOM.PAD + GEOM.poste.h, `hauteur ${p.h}`);
});

test('(d) stabilité : un worker qui passe à arrêté ne change ni la bande ni la rangée d’aucune pièce', () => {
  const avant = exempleA(0).etat;
  const rang = (plan) => new Map(plan.pieces.map((p) => [p.nom, `${p.bande}:${p.haut}`]));
  const de = rang(disposition(avant));
  for (const a of avant.agents.filter((x) => x.role === 'worker' && x.etat === 'travaille')) {
    const apres = copie(avant);
    apres.agents.find((x) => x.id === a.id).etat = 'arrete';
    const plan = disposition(apres);
    for (const [nom, place] of rang(plan)) assert.equal(place, de.get(nom), `${a.id} arrêté déplace ${nom}`);
  }
});

test('(d) stabilité : un worker rouvert (arrêté → travaille) ne change ni la bande ni la rangée d’aucune pièce', () => {
  const arrete = exempleA(0).etat; // à t = 0 : worker-hote-api et worker-observation-git sont arrêtés
  const rang = (plan) => new Map(plan.pieces.map((p) => [p.nom, `${p.bande}:${p.haut}`]));
  const de = rang(disposition(arrete));
  for (const a of arrete.agents.filter((x) => x.role === 'worker' && x.etat === 'arrete')) {
    const rouvert = copie(arrete);
    rouvert.agents.find((x) => x.id === a.id).etat = 'travaille';
    for (const [nom, place] of rang(disposition(rouvert))) assert.equal(place, de.get(nom), `${a.id} rouvert déplace ${nom}`);
  }
});

test('(e) fixture d’exemple sans aucun arrêté : 672×240, aucun arrêté replié', () => {
  const etat = lire(EXEMPLE);
  for (const a of etat.agents) if (a.etat === 'arrete') a.etat = 'travaille';
  const plan = disposition(etat);
  assert.equal(plan.largeur, 672);
  assert.equal(plan.hauteurEtage, 240);
});

test('(e) fixture d’exemple, à t = 0 : seuls worker-hote-api et worker-observation-git sont repliés (coord-cadrage garde sa chaise)', () => {
  const { etat, scene } = exempleA(0);
  const repliés = etat.agents.filter((a) => a.etat === 'arrete' && REPLIER.includes(a.role)).map((a) => a.id).sort();
  assert.deepEqual(repliés, ['worker-hote-api', 'worker-observation-git']);
  assert.ok(scene.agents.some((a) => a.id === 'coord-cadrage'), 'le coordinateur arrêté a disparu');
  assert.ok(!scene.agents.some((a) => repliés.includes(a.id)), 'un worker replié est encore dessiné');
});

test('compteur hors organigramme : dans le couloir de la bande 0, à gauche, au-dessus du chemin du facteur', () => {
  const etat = lire(REEL);
  const plan = disposition(etat);
  const h = plan.horsOrganigramme;
  const pieds = plan.noeuds.get('assistant').y; // le facteur marche à la hauteur des pieds (yMarche de la bande 0)
  assert.ok(h.x >= plan.couloirs[0].x, 'hors du couloir');
  assert.ok(h.y >= plan.couloirs[0].y && h.y + SIGNE.h <= plan.couloirs[0].y + plan.couloirs[0].h, 'hors de la hauteur du couloir');
  assert.ok(h.y + SIGNE.h < pieds, 'le compteur touche le chemin du facteur');
  assert.ok(h.x + h.w <= plan.largeur - GEOM.UTILISATEUR_W - GEOM.MUR, 'le compteur entre dans la cage de l’utilisateur');
});

test('fin de tâche : un worker arrêté joue sa fin de tâche, puis disparaît dans le compteur', () => {
  const etat = etatAvecArretes(2);
  etat.agents.push(agent('w-fin', 'worker', 'abcdefghijkl', 'arrete'));
  const ephemeres = new Map([['w-fin', { type: 'fin_tache', debut: 0 }]]);
  const pendant = construireScene(etat, null, { t: 1000, ephemeres });
  const apres = construireScene(etat, null, { t: 3000, ephemeres });
  assert.ok(pendant.agents.some((a) => a.id === 'w-fin' && a.sprite === 'perso.worker.fin_tache'), 'pas de fin de tâche pendant 2,5 s');
  assert.ok(!apres.agents.some((a) => a.id === 'w-fin'), 'le worker ne se replie pas après sa fin de tâche');
  assert.equal(apres.pieces.find((p) => p.nom === 'abcdefghijkl').compteur.n, 3, 'il manque au compteur après repli');
});

test('l’état d’exemple se dessine : le compteur d’un replié est bien dans la scène', () => {
  const { scene } = exempleA(0);
  const p = scene.pieces.find((q) => q.nom === 'observation');
  assert.equal(p.compteur.texte, '+1');
  assert.ok(scene.horsOrganigramme.texte.startsWith('hors organigramme : '));
});
