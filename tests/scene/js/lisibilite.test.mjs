// Lisibilité de la scène : ce que le rendu montre, vérifié sans navigateur (surface espion + surface PNG).
// Deux étages : l’état d’exemple (7 équipes, 16 agents) à t = 0 et t = 30 000 ms, et un étage synthétique 10 équipes / 20 agents.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { ATLAS } from '../../../src/cime/scene/static/graphismes/atlas.js';
import { PALETTE } from '../../../src/cime/scene/static/graphismes/palette.js';
import { creerSourceRejouee } from './support/source-rejouee.mjs';
import { creerFil, appliquerSnapshot, sceneA, construireScene } from '../../../src/cime/scene/static/modele.js';
import { dessiner, COULEURS } from '../../../src/cime/scene/static/rendu.js';
import { SurfacePNG } from '../../../src/cime/scene/static/surface-png.mjs';
import { abreger, largeurTexte, disposition, GEOM } from '../../../src/cime/scene/static/plan.js';

const ICI = dirname(fileURLToPath(import.meta.url));
const FIXTURE = join(ICI, '..', 'fixtures', 'etat-exemple.json');

// Surface espion : enregistre la boîte de chaque sprite, rect et texte (même interface que les vraies surfaces).
class Espion {
  constructor(largeur, hauteur) {
    this.largeur = largeur;
    this.hauteur = hauteur;
    this.boites = [];
  }
  taille() {
    return { w: this.largeur, h: this.hauteur };
  }
  rect(x, y, w, h, couleur) {
    this.boites.push({ genre: 'rect', x, y, w, h, couleur });
  }
  sprite(nom, frame, x, y) {
    const s = ATLAS.sprites[nom];
    this.boites.push({ genre: 'sprite', nom, x, y, w: s.w, h: s.h });
  }
  texte(chaine, x, y, couleur) {
    this.boites.push({ genre: 'texte', chaine, x, y, w: largeurTexte(ATLAS.police, chaine), h: ATLAS.police.h, couleur });
  }
}

const exemple = (t) => {
  const etatInitial = JSON.parse(readFileSync(FIXTURE, 'utf8'));
  const source = creerSourceRejouee({ etatInitial });
  const fil = creerFil();
  source.abonner((etat, trs, tStep, { reset }) => appliquerSnapshot(fil, etat, trs, tStep, { reset }));
  source.avancerA(t);
  return { etat: fil.etat, scene: sceneA(fil, t), t };
};

function synthetique() {
  const equipes = Array.from({ length: 10 }, (_, i) => ({ nom: `equipe${i}`, statut: ['active', 'au_repos', 'bloquee', 'terminee', null][i % 5] }));
  const agent = (id, role, equipe, over = {}) => ({
    id, role, equipe, vivant: true, etat: 'travaille', tache: null, brouillon: null,
    contexte: { tokens: 40000 + 7000 * id.length, limite: 200000 }, cout_usd_estime: 1.5 + id.length / 10, ...over,
  });
  const agents = [agent('assistant', 'assistant', null), { ...agent('utilisateur', 'utilisateur', null), vivant: null, etat: 'inconnu' }];
  for (let i = 0; i < 10; i++) {
    agents.push(agent(`coord-equipe${i}`, 'coordinateur', `equipe${i}`, i === 3 ? { etat: 'attend_reponse' } : {}));
    if (i < 9) agents.push(agent(`worker-equipe${i}-a`, 'worker', `equipe${i}`, i === 5 ? { etat: 'au_repos' } : {}));
  }
  const alarme = (id, type, gravite, ags, eqs) => ({ id, type, gravite, agents: ags, equipes: eqs, depuis: '2026-10-07T12:00:00Z', mesure: '', quoi_faire: '', destinataire: 'utilisateur' });
  return {
    version: 2,
    agents,
    equipes,
    alarmes: [
      alarme('a1', 'recouvrement', 'grave', ['worker-equipe1-a'], ['equipe1']),
      alarme('a2', 'recouvrement', 'grave', [], ['equipe7']), // seulement une équipe : bordure rouge, aucun halo
      alarme('a3', 'fige', 'a_voir', ['coord-equipe4'], ['equipe4']),
    ],
    flux: [
      { id: 1, de: 'coord-equipe0', a: 'coord-equipe9', nature: 'question', etat: 'inscrit', transitions: [] },
      { id: 2, de: 'coord-equipe0', a: 'coord-equipe9', nature: 'question', etat: 'inscrit', transitions: [] },
      { id: 3, de: 'coord-equipe2', a: 'assistant', nature: 'rapport', etat: 'pris_en_compte', transitions: [] },
    ],
    ordres: [],
    aretes: [],
    attentes_utilisateur: [],
    facteur: { battement: 'x', age_s: 1, arrete: false },
  };
}

const CAS = () => {
  const m0 = exemple(0);
  const m30 = exemple(30000);
  const syn = synthetique();
  return [
    { nom: 'exemple t=0', etat: m0.etat, scene: m0.scene, t: 0 },
    { nom: 'exemple t=30000', etat: m30.etat, scene: m30.scene, t: 30000 },
    { nom: 'synthétique 10 équipes / 20 agents', etat: syn, scene: construireScene(syn, null, { t: 0 }), t: 0 },
  ];
};

const espionner = ({ scene, t }) => {
  const espion = new Espion(scene.largeur, scene.hauteur);
  dessiner(espion, ATLAS, scene, t);
  return espion.boites.filter((b) => b.y < scene.hauteurEtage); // l'étage seulement : la légende a ses propres tests (legende.test.mjs)
};
const croise = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
const dedans = (a, z) => a.x >= z.x && a.y >= z.y && a.x + a.w <= z.x + z.w && a.y + a.h <= z.y + z.h;

for (const cas of CAS()) {
  const { nom, scene, etat } = cas;
  const plan = disposition(etat);

  test(`${nom} : aucune boîte de poste n'en recouvre une autre, chacune est entièrement dans sa pièce`, () => {
    const postes = [...plan.sieges.entries()];
    // 12 à t = 0 : 14 postes sans repli, moins les 2 workers arrêtés (hote, observation) repliés en compteur
    assert.ok(postes.length >= 12);
    for (let i = 0; i < postes.length; i++) {
      const [id, s] = postes[i];
      assert.equal(s.boite.w, GEOM.poste.w, 'la boîte est celle que les sprites dictent');
      for (let j = i + 1; j < postes.length; j++) {
        assert.equal(croise(s.boite, postes[j][1].boite), false, `postes ${id} et ${postes[j][0]} se recouvrent`);
      }
      const p = scene.pieces.find((q) => q.nom === s.piece);
      assert.ok(dedans(s.boite, p), `${id} sort de la pièce ${p.nom}`);
      if (p.sol) assert.ok(dedans(s.boite, p.sol), `${id} mord sur la bordure ou la cloison de ${p.nom}`);
    }
  });

  test(`${nom} : pièces, postes, enveloppes et textes dessinés restent dans l'étage`, () => {
    const boites = espionner(cas);
    assert.ok(boites.length > 100);
    const etage = { x: 0, y: 0, w: scene.largeur, h: scene.hauteur };
    for (const b of boites) assert.ok(dedans(b, etage), `hors de l'étage : ${JSON.stringify(b)}`);
    for (const p of scene.pieces) assert.ok(dedans(p, etage), `pièce ${p.nom} hors de l'étage`);
  });

  test(`${nom} : le nom de chaque pièce est dessiné entier (ou abrégé par « … ») dans l'en-tête, que rien ne recouvre`, () => {
    const boites = espionner(cas);
    for (const p of scene.pieces) {
      const z = p.nomZone;
      const zone = { x: z.x, y: z.y, w: z.w, h: ATLAS.police.h };
      const texte = boites.find((b) => b.genre === 'texte' && b.x === z.x && b.y === z.y);
      assert.ok(texte, `nom de ${p.nom} non dessiné`);
      const ok = texte.chaine === p.libelle || (texte.chaine.endsWith('…') && p.libelle.startsWith(texte.chaine.slice(0, -1)));
      assert.ok(ok, `« ${texte.chaine} » n'est ni ${p.libelle} ni son abréviation`);
      assert.equal(texte.chaine, abreger(ATLAS.police, p.libelle, z.w));
      assert.ok(dedans(texte, p.entete), `nom de ${p.nom} hors de l'en-tête`);
      assert.ok(texte.w <= z.w, `nom de ${p.nom} déborde de sa zone`);
      assert.ok(p.entete.h >= ATLAS.police.h + 6, 'bande assez haute pour le nom');
      // Rien ne recouvre le nom : ni sprite (hors le mur lui-même) ni aplat dessiné après le texte.
      const i = boites.indexOf(texte);
      boites.forEach((b, k) => {
        if (b.genre === 'sprite' && b.nom !== 'mur.haut') assert.equal(croise(b, zone), false, `${b.nom} recouvre le nom de ${p.nom}`);
        if (k > i && b.genre === 'rect') assert.equal(croise(b, zone), false, `un aplat recouvre le nom de ${p.nom}`);
      });
      for (const a of scene.agents) {
        const s = plan.sieges.get(a.id);
        if (s) assert.equal(croise(s.boite, p.entete), false, `un poste mord sur l'en-tête de ${p.nom}`);
      }
    }
  });

  test(`${nom} : le couloir est libre de tout poste, meuble ou plante`, () => {
    const boites = espionner(cas);
    const MOBILIER = /^(meuble|ecran|bulle|jauge|icone|plante|machine|perso\.(assistant|coordinateur|worker|utilisateur))/;
    for (const c of scene.couloirs) {
      for (const b of boites) {
        if (b.genre === 'sprite' && MOBILIER.test(b.nom)) assert.equal(croise(b, c), false, `${b.nom} dans le couloir`);
      }
      for (const [id, s] of plan.sieges) assert.equal(croise(s.boite, c), false, `poste de ${id} dans le couloir`);
    }
  });

  test(`${nom} : un halo par agent qu'une alarme grave nomme (rouge) ou qui attend (ambre : autorisation, animation 5), centré sur son poste, aucun autre`, () => {
    const TYPES_ATTENTE = ['autorisation_en_attente', 'question_sans_reponse'];
    const rouges = new Set();
    const ambres = new Set();
    for (const a of etat.alarmes ?? []) {
      if (a.gravite !== 'grave') continue;
      for (const id of a.agents ?? []) if (plan.sieges.has(id)) (TYPES_ATTENTE.includes(a.type) ? ambres : rouges).add(id);
    }
    for (const a of etat.agents) if (a.etat === 'attend_autorisation' && plan.sieges.has(a.id)) ambres.add(a.id);
    for (const id of rouges) ambres.delete(id); // le rouge l'emporte
    const tous = espionner(cas);
    for (const [sprite, attendus] of [['alerte.halo', rouges], ['attente.halo', ambres]]) {
      const boites = tous.filter((b) => b.nom === sprite);
      assert.equal(boites.length, attendus.size, `nombre de halos ${sprite}`);
      const centres = new Set(boites.map((b) => `${b.x + b.w / 2},${b.y}`));
      for (const id of attendus) {
        const { pivot } = plan.sieges.get(id);
        const h = ATLAS.sprites[sprite];
        assert.ok(centres.has(`${pivot.x - h.pivot[0] + h.w / 2},${pivot.y - h.pivot[1]}`), `halo ${sprite} de ${id} mal centré ou absent`);
      }
    }
    for (const a of scene.agents) assert.equal(a.halo, rouges.has(a.id) ? 'rouge' : ambres.has(a.id) ? 'ambre' : null, `halo de ${a.id}`);
  });
}

test('alarme grave qui ne nomme qu\'une équipe : bordure rouge de la pièce, aucun halo', () => {
  const etat = synthetique();
  etat.alarmes = [{ id: 'g', type: 'recouvrement', gravite: 'grave', agents: [], equipes: ['equipe7'], destinataire: 'utilisateur' }];
  const scene = construireScene(etat, null, { t: 0 });
  assert.equal(scene.agents.filter((a) => a.halo === 'rouge').length, 0);
  assert.equal(scene.pieces.find((p) => p.nom === 'equipe7').statut, 'rouge');
  const boites = espionner({ scene, t: 0 });
  assert.equal(boites.filter((b) => b.nom === 'alerte.halo').length, 0);
  const p = scene.pieces.find((q) => q.nom === 'equipe7');
  assert.ok(boites.some((b) => b.genre === 'rect' && b.couleur === COULEURS.rouge && dedans(b, p)), 'bordure rouge dessinée');
  assert.equal(scene.pieces.find((q) => q.nom === 'equipe6').statut !== 'rouge', true);
});

test('rouge réservé : au plus un élément rouge de plus que les causes de la table', () => {
  for (const cas of CAS()) {
    const { scene, etat } = cas;
    const causes =
      (etat.alarmes ?? []).filter((a) => a.gravite === 'grave').length +
      etat.agents.filter((a) => a.etat === 'attend_autorisation').length +
      (etat.ordres ?? []).filter((o) => o.verbe === 'compacter' && o.etat === 'echec').length +
      (etat.flux ?? []).filter((m) => m.etat === 'echec' || m.etat === 'abandonne').length +
      (etat.facteur?.arrete ? 1 : 0) +
      (scene.porte.couleur === 'rouge' ? 1 : 0) +
      (etat.equipes ?? []).filter((e) => e.statut === 'bloquee').length;
    const rouges = [
      ...scene.agents.filter((a) => a.couleur === 'rouge' || a.halo === 'rouge'),
      ...scene.pieces.filter((p) => p.couleur === 'rouge'),
      ...scene.enveloppes.filter((e) => e.couleur === 'rouge'),
    ];
    if (scene.porte.couleur === 'rouge') rouges.push(scene.porte);
    if (scene.facteur.couleur === 'rouge') rouges.push(scene.facteur);
    assert.ok(rouges.length <= causes + 1, `${cas.nom} : ${rouges.length} éléments rouges pour ${causes} causes`);
    // Côté dessin : les aplats rouges de bordure ne sont posés que sur des pièces rouges.
    const rects = espionner(cas).filter((b) => b.genre === 'rect' && b.couleur === COULEURS.rouge);
    for (const r of rects) {
      assert.ok(scene.pieces.some((p) => p.couleur === 'rouge' && dedans(r, p)), `aplat rouge hors d'une pièce rouge : ${JSON.stringify(r)}`);
    }
  }
});

test('les états de pièce se distinguent (bordure et sol) ; « bloquee » est neutre (jamais rouge) ; terminée : porte fermée', () => {
  const etat = synthetique();
  etat.alarmes = [];
  const scene = construireScene(etat, null, { t: 0 });
  const boites = espionner({ scene, t: 0 });
  const signature = (p) => {
    const dans = boites.filter((b) => b.genre === 'rect' && dedans(b, p));
    const couleurs = new Set(dans.map((b) => b.couleur));
    const sprites = boites.filter((b) => b.genre === 'sprite' && b.nom === 'sol.piece' && dedans(b, p)).length;
    return `${[...couleurs].sort().join('|')}#${sprites > 0}`;
  };
  const parStatut = new Map();
  for (const p of scene.pieces.filter((q) => !q.neutre)) {
    const sig = signature(p);
    if (!parStatut.has(p.statut)) parStatut.set(p.statut, new Set());
    parStatut.get(p.statut).add(sig);
  }
  const signatures = [...parStatut.entries()].map(([s, v]) => [s, [...v][0]]);
  assert.equal(new Set(signatures.map(([, v]) => v)).size, signatures.length, `états indiscernables : ${JSON.stringify(signatures)}`);
  for (const p of scene.pieces) {
    assert.equal(p.couleur === 'rouge', false, `${p.nom} : sans alarme grave, aucune pièce rouge`);
    assert.equal(p.statut === 'attend', etat.equipes.find((e) => e.nom === p.nom)?.statut === 'bloquee');
  }
  const grisee = scene.pieces.find((p) => p.statut === 'grisee');
  assert.ok(boites.some((b) => b.nom === 'porte.piece' && dedans(b, grisee)), 'porte fermée (sprite) sur la pièce terminée');
  const active = scene.pieces.find((p) => p.statut === 'lumiere' && !p.neutre);
  assert.equal(boites.some((b) => b.nom === 'porte.piece' && dedans(b, active)), false, 'porte ouverte sur une pièce active');
});

test('une sirène au plus par pièce, posée sur la cloison (jamais sur un poste)', () => {
  for (const cas of CAS()) {
    const plan = disposition(cas.etat);
    const sirenes = espionner(cas).filter((b) => b.nom === 'alerte.sirene');
    const parPiece = new Map();
    for (const s of sirenes) {
      const p = cas.scene.pieces.find((q) => dedans(s, q.entete));
      assert.ok(p, 'sirène hors de la cloison d\'en-tête');
      parPiece.set(p.nom, (parPiece.get(p.nom) ?? 0) + 1);
      for (const [, siege] of plan.sieges) assert.equal(croise(s, siege.boite), false);
    }
    for (const n of parPiece.values()) assert.equal(n, 1);
  }
});

test('enveloppes : au-dessus des postes dans l\'ordre de dessin, en pile ordonnée sur le bureau de l\'expéditeur', () => {
  for (const cas of CAS()) {
    const boites = espionner(cas);
    const dernierPoste = Math.max(...boites.map((b, i) => (b.genre === 'sprite' && /^(meuble|ecran|perso\.(assistant|coordinateur|worker)|alerte\.halo|jauge)/.test(b.nom) ? i : -1)));
    boites.forEach((b, i) => {
      if (b.genre === 'sprite' && b.nom.startsWith('enveloppe.')) assert.ok(i > dernierPoste, `${b.nom} dessinée avant un poste`);
    });
  }
  const { scene } = CAS()[2];
  const posees = scene.enveloppes.filter((e) => e.etat === 'inscrit');
  assert.equal(posees.length, 2);
  assert.notEqual(`${posees[0].x},${posees[0].y}`, `${posees[1].x},${posees[1].y}`, 'pas au même pixel');
});

test('le fond « vide » reste sous 15 % de l\'étage (exemple, t = 0 et t = 30 000 ms)', () => {
  for (const t of [0, 30000]) {
    const { scene } = exemple(t);
    const surface = new SurfacePNG(scene.largeur, scene.hauteur, ATLAS, PALETTE);
    dessiner(surface, ATLAS, scene, t);
    const fond = parseInt(COULEURS.fond.slice(1), 16);
    const px = surface.rgba();
    let vides = 0;
    for (let i = 0; i < px.length; i += 4) if (((px[i] << 16) | (px[i + 1] << 8) | px[i + 2]) === fond) vides++;
    const part = vides / (scene.largeur * scene.hauteur);
    assert.ok(part <= 0.15, `t=${t} : ${(part * 100).toFixed(1)} % de fond vide`);
  }
});

// 672 et non 640 : depuis la règle de rangée par rang (plan.js, ordre stable), la fixture a 4 pièces en haut et 3 en bas,
// et chaque rangée fait 528 px (96 + 208 + 112 + 112 ; 176 × 3). La limite de largeur est donc relevée.
// Conséquence : à ×2, l'étage fait 1344 px de large, soit 64 px de plus qu'une fenêtre 1280 px (défilement horizontal).
// À surveiller si une pièce s'élargit encore.
// 527 et non 489 : les deux compteurs (arrêtés repliés, hors organigramme) ajoutent une rangée à la légende (38 px) ;
// 558 et non 527 : le halo ambre « attend l’utilisateur » en ajoute une autre (31 px). La légende de la page est un panneau
// HTML : cette bande pixel ne sert plus qu'aux tests de rendu.
// 609 et non 558 : une attente n'est plus rouge, donc la légende distingue les signes d'attente (ambre :
// halo d'agent, sirène « à voir ») et les enveloppes grises des signes de problème (rouge) : quatre signes de plus.
test('l\'étage de l’état d’exemple tient dans 672×360 logiques ; avec la légende : 672×609 (×1 = 609 px de haut)', () => {
  const { scene } = exemple(0);
  console.log(`étage de l’état d’exemple : ${scene.largeur}×${scene.hauteurEtage} px logiques ; avec la légende ${scene.largeur}×${scene.hauteur}`);
  assert.ok(scene.largeur <= 672 && scene.hauteurEtage <= 360, `${scene.largeur}×${scene.hauteurEtage}`);
  assert.ok(scene.hauteur <= 609, `avec la légende : ${scene.hauteur}`);
});
