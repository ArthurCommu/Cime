// Bandes : l'étage s'allonge en hauteur, par bandes empilées (7, 15, 25 équipes ; états d'exemple).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { disposition, abreger, largeurTexte, GEOM } from '../../../src/cime/scene/static/plan.js';
import { ATLAS } from '../../../src/cime/scene/static/graphismes/atlas.js';
import { etatBandes, etatUniforme, embaucher } from './etats-bandes.mjs';

const EXEMPLE = join(dirname(fileURLToPath(import.meta.url)), '..', 'fixtures', 'etat-exemple.json');

const chevauchent = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
const dans = (r, W, H) => r.x >= 0 && r.y >= 0 && r.x + r.w <= W && r.y + r.h <= H;
// Un agent et son poste : toutes les zones d'un même étage, pièces, couloirs et emplacements libres.
const zonesDe = (plan) => [
  ...plan.pieces,
  ...plan.couloirs.map((c, k) => ({ ...c, nom: `couloir ${k}` })),
  ...plan.videes.map((v, k) => ({ ...v, nom: `emplacement libre ${k}` })),
];

for (const n of [7, 15, 25]) {
  const etat = etatBandes(n);

  test(`${n} équipes : l'étage entier tient dans le cadre`, () => {
    const plan = disposition(etat);
    for (const z of zonesDe(plan)) assert.ok(dans(z, plan.largeur, plan.hauteurEtage), `${z.nom} hors de l'étage`);
    for (const [id, s] of plan.sieges) assert.ok(dans(s.boite, plan.largeur, plan.hauteurEtage), `poste de ${id} hors de l'étage`);
  });

  test(`${n} équipes : aucun poste ni aucune pièce ne chevauche un autre, ni un couloir`, () => {
    const plan = disposition(etat);
    const zones = zonesDe(plan);
    for (let i = 0; i < zones.length; i++) {
      for (let j = i + 1; j < zones.length; j++) {
        const a = zones[i];
        const b = zones[j];
        // Les pièces se touchent sans se recouvrir : un contact n'est pas un chevauchement.
        const ouvert = a.x + a.w > b.x + 0.5 && b.x + b.w > a.x + 0.5 && a.y + a.h > b.y + 0.5 && b.y + b.h > a.y + 0.5;
        assert.equal(ouvert, false, `${a.nom} et ${b.nom} se chevauchent`);
      }
    }
    const postes = [...plan.sieges.entries()];
    for (let i = 0; i < postes.length; i++) {
      for (let j = i + 1; j < postes.length; j++) {
        assert.equal(chevauchent(postes[i][1].boite, postes[j][1].boite), false, `postes ${postes[i][0]} et ${postes[j][0]}`);
      }
      for (const c of plan.couloirs) assert.equal(chevauchent(postes[i][1].boite, c), false, `poste ${postes[i][0]} dans un couloir`);
    }
  });

  test(`${n} équipes : zéro pixel de fond, l'étage est recouvert exactement par ses pièces et couloirs`, () => {
    const plan = disposition(etat);
    const somme = zonesDe(plan).reduce((t, z) => t + z.w * z.h, 0);
    // Pas de chevauchement (test précédent) : la somme des aires égale l'aire de l'étage, donc aucun trou.
    assert.equal(somme, plan.largeur * plan.hauteurEtage);
  });

  test(`${n} équipes : chaque nom est entier, ou abrégé avec « … » dans sa zone d'en-tête`, () => {
    const plan = disposition(etat);
    for (const p of plan.pieces.filter((q) => q.haut !== null)) {
      const affiche = abreger(ATLAS.police, p.nom, p.nomZone.w);
      assert.ok(largeurTexte(ATLAS.police, affiche) <= p.nomZone.w, `${p.nom} déborde de son en-tête`);
      assert.ok(affiche === p.nom || affiche.endsWith('…'), `${p.nom} tronqué sans « … »`);
    }
  });

  test(`${n} équipes : au plus 8 pièces par bande, 4 par rangée`, () => {
    const plan = disposition(etat);
    const parBande = new Map();
    for (const p of plan.pieces.filter((q) => q.haut !== null)) {
      const k = `${p.bande}`;
      const c = parBande.get(k) ?? { haut: 0, bas: 0 };
      if (p.haut) c.haut++;
      else c.bas++;
      parBande.set(k, c);
    }
    for (const [k, c] of parBande) {
      assert.ok(c.haut <= 4 && c.bas <= 4, `bande ${k} : ${c.haut} en haut, ${c.bas} en bas`);
    }
    assert.equal(parBande.size, Math.ceil(n / GEOM.PIECES_PAR_BANDE));
  });
}

// Dernière bande incomplète : la pièce seule de la rangée ne s'étire pas sur l'étage, le reste est un emplacement libre.
for (const n of [9, 17, 25]) {
  const etat = etatBandes(n);

  test(`${n} équipes : la pièce seule d'une rangée n'est pas plus large que la plus large des autres pièces`, () => {
    const plan = disposition(etat);
    const pieces = plan.pieces.filter((q) => q.haut !== null);
    const rangees = new Map();
    for (const p of pieces) {
      const k = `${p.bande}-${p.haut}`;
      rangees.set(k, [...(rangees.get(k) ?? []), p]);
    }
    const seules = [...rangees.values()].filter((r) => r.length === 1 && pieces.length > 1);
    assert.ok(seules.length >= 1, 'pas de rangée à une pièce : le cas testé n’existe pas');
    for (const [seule] of seules) {
      const autres = pieces.filter((q) => q !== seule);
      assert.ok(seule.w <= GEOM.PIECE_W_MAX, `${seule.nom} fait ${seule.w} px, plus qu'une pièce (${GEOM.PIECE_W_MAX})`);
      assert.ok(seule.w <= Math.max(...autres.map((q) => q.w)), `${seule.nom} plus large que les autres pièces`);
    }
  });

  test(`${n} équipes : l'emplacement libre n'a ni nom, ni porte, ni agent, ni point du facteur`, () => {
    const plan = disposition(etat);
    assert.ok(plan.videes.length >= 1, 'pas d’emplacement libre');
    for (const v of plan.videes) {
      assert.equal(v.nom, undefined, 'emplacement libre nommé');
      assert.equal(v.porte, undefined, 'emplacement libre avec une porte');
      for (const [id, s] of plan.sieges) assert.equal(chevauchent(s.boite, v), false, `poste de ${id} dans un emplacement libre`);
      for (const [noeud, pt] of plan.noeuds) {
        const dedans = pt.x >= v.x && pt.x <= v.x + v.w && pt.y >= v.y && pt.y <= v.y + v.h;
        assert.equal(dedans, false, `${noeud} dans un emplacement libre`);
      }
    }
  });
}

// Reste de moins de 3 tuiles (48 px) : pas de plafond, donc pas d'emplacement libre (3 équipes : 2 en haut, 1 en bas).
test('3 équipes : reste de moins de 48 px, pas d’emplacement libre, la pièce du bas garde la largeur de la rangée', () => {
  const plan = disposition(etatUniforme(3));
  assert.equal(plan.videes.length, 0);
  assert.deepEqual(plan.pieces.filter((p) => p.haut !== null).map((p) => p.w), [112, 112, 224]);
});

// 672 sans repli. Les workers arrêtés étant repliés (REPLIER = worker), la fixture a deux workers arrêtés, sans poste :
// worker-hote-api (hote) et worker-observation-git (observation). Les rangées les plus pleines font 480 px, pas 576.
// À t = 30 000, worker-verification-rapport s'arrête aussi : 656 px (tests/scene/js/replies.test.mjs).
test('état d’exemple : l’étage fait 624×240 à t = 0 (2 workers arrêtés repliés), une seule bande', () => {
  const plan = disposition(JSON.parse(readFileSync(EXEMPLE, 'utf8')));
  assert.equal(plan.largeur, 624);
  assert.equal(plan.hauteurEtage, 240);
  assert.equal(plan.couloirs.length, 1);
});

test('hauteur linéaire en bandes : 8, 16, 24, 32 équipes de même effectif = 1, 2, 3, 4 bandes', () => {
  const h = (n) => disposition(etatUniforme(n)).hauteurEtage;
  const h8 = h(8);
  assert.equal(h(16), 2 * h8);
  assert.equal(h(24), 3 * h8);
  assert.equal(h(32), 4 * h8);
});

test('hauteur croissante : ajouter une équipe ne réduit jamais l’étage (1 à 33 équipes)', () => {
  let precedente = 0;
  for (let n = 1; n <= 33; n++) {
    const h = disposition(etatUniforme(n)).hauteurEtage;
    assert.ok(h >= precedente, `${n} équipes : ${h} < ${precedente}`);
    precedente = h;
  }
});

// Stabilité : embaucher un worker dans chaque équipe, tour à tour, ne change ni la bande ni la rangée d'aucune pièce.
test('stabilité 25 équipes : embaucher un worker ne change ni la bande ni la rangée d’aucune pièce', () => {
  const etat = etatBandes(25);
  const situation = (plan) => new Map(plan.pieces.filter((p) => p.haut !== null).map((p) => [p.nom, { bande: p.bande, haut: p.haut }]));
  const avant = situation(disposition(etat));
  for (const { nom } of etat.equipes) {
    const apres = situation(disposition(embaucher(etat, nom)));
    assert.deepEqual([...apres], [...avant], `embauche dans ${nom}`);
  }
});

// Chemins du facteur : pour chaque paire d'agents, chaque point et chaque pas entre deux points sont dans un couloir
// ou dans une cage (la pièce de l'Assistant ou celle de l’utilisateur). Un segment qui coupe une cloison fait échouer le test.
test('chemins 25 équipes : chaque paire d’agents a un chemin dans les couloirs et les cages, de longueur finie', () => {
  const plan = disposition(etatBandes(25));
  const lieux = [...plan.couloirs, ...plan.pieces.filter((p) => p.haut === null)];
  const dansUnLieu = (x, y) => lieux.some((r) => x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h);
  const ids = [...plan.sieges.keys(), 'assistant', 'utilisateur'];
  let longueurTotale = 0;
  for (const de of ids) {
    for (const a of ids) {
      const pts = plan.points(plan.cheminFacteur(plan.noeudDeAgent(de), plan.noeudDeAgent(a)));
      assert.ok(pts.length >= 1, `${de}→${a} : chemin vide`);
      for (let i = 0; i < pts.length; i++) {
        assert.ok(dansUnLieu(pts[i].x, pts[i].y), `${de}→${a} : point ${i} hors couloir et cage`);
        if (i === 0) continue;
        const p = pts[i - 1];
        const q = pts[i];
        const pas = Math.max(1, Math.ceil(Math.hypot(q.x - p.x, q.y - p.y)));
        for (let s = 0; s <= pas; s++) {
          const t = s / pas;
          assert.ok(dansUnLieu(p.x + (q.x - p.x) * t, p.y + (q.y - p.y) * t), `${de}→${a} : segment ${i - 1}-${i} traverse un mur`);
        }
        longueurTotale += Math.hypot(q.x - p.x, q.y - p.y);
      }
    }
  }
  assert.ok(Number.isFinite(longueurTotale) && longueurTotale > 0);
});
