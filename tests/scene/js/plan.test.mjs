// Plan : aucun chevauchement de bureaux ni de pièces avec 10 équipes et 20 agents ; le chemin du facteur relie tout.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { disposition } from '../../../src/cime/scene/static/plan.js';

function grand() {
  const equipes = Array.from({ length: 10 }, (_, i) => ({ nom: `equipe${i}`, statut: 'active' }));
  const agents = [
    { id: 'assistant', role: 'assistant', equipe: null },
    { id: 'utilisateur', role: 'utilisateur', equipe: null },
  ];
  for (let i = 0; i < 10; i++) {
    agents.push({ id: `coord-equipe${i}`, role: 'coordinateur', equipe: `equipe${i}` });
    if (i < 9) agents.push({ id: `worker-equipe${i}-a`, role: 'worker', equipe: `equipe${i}` });
  }
  return { equipes, agents };
}

const chevauchent = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

test('10 équipes, 20 agents : aucun bureau ne chevauche un autre bureau', () => {
  const plan = disposition(grand());
  const bureaux = [...plan.sieges.values()].map((s) => s.bureau);
  assert.equal(bureaux.length, 20, 'assistant + 10 coordinateurs + 9 workers');
  for (let i = 0; i < bureaux.length; i++) {
    for (let j = i + 1; j < bureaux.length; j++) {
      assert.equal(chevauchent(bureaux[i], bureaux[j]), false, `bureaux ${i} et ${j}`);
    }
  }
});

test('10 équipes : aucune pièce ne chevauche une autre pièce ni le couloir', () => {
  const plan = disposition(grand());
  const zones = [...plan.pieces.map((p) => ({ ...p, nom: p.nom })), ...plan.couloirs.map((c, k) => ({ ...c, nom: `couloir ${k}` }))];
  for (let i = 0; i < zones.length; i++) {
    for (let j = i + 1; j < zones.length; j++) {
      const z = zones[i];
      const w = zones[j];
      // Les pièces sont posées côte à côte ou au bord du couloir : un contact n'est pas un chevauchement.
      const ouvert = z.x + z.w > w.x + 0.5 && w.x + w.w > z.x + 0.5 && z.y + z.h > w.y + 0.5 && w.y + w.h > z.y + 0.5;
      assert.equal(ouvert, false, `${z.nom} et ${w.nom} se chevauchent`);
    }
  }
});

test('chaque bureau est dans sa pièce', () => {
  const plan = disposition(grand());
  for (const [id, s] of plan.sieges) {
    const p = plan.pieces.find((q) => q.nom === s.piece);
    assert.ok(p, `pièce de ${id}`);
    assert.ok(s.bureau.x >= p.x && s.bureau.x + s.bureau.w <= p.x + p.w, `${id} hors de sa pièce (x)`);
    assert.ok(s.bureau.y >= p.y && s.bureau.y + s.bureau.h <= p.y + p.h, `${id} hors de sa pièce (y)`);
  }
});

test('le chemin du facteur relie chaque pièce à chaque autre et à la porte de l’utilisateur', () => {
  const plan = disposition(grand());
  const noeuds = [...plan.noeuds.keys()];
  assert.ok(noeuds.includes('utilisateur'));
  const arete = new Set(plan.aretes.map(([a, b]) => `${a}|${b}`));
  for (const de of noeuds) {
    for (const a of noeuds) {
      const chemin = plan.cheminFacteur(de, a);
      assert.equal(chemin[0], de, `${de}→${a} commence mal`);
      assert.equal(chemin.at(-1), a, `${de}→${a} finit mal`);
      for (let i = 1; i < chemin.length; i++) {
        const lien = arete.has(`${chemin[i - 1]}|${chemin[i]}`) || arete.has(`${chemin[i]}|${chemin[i - 1]}`);
        assert.ok(lien, `${de}→${a} : pas d’arête entre ${chemin[i - 1]} et ${chemin[i]}`);
      }
    }
  }
});

test('disposition déterministe : même instantané, même plan', () => {
  const a = disposition(grand());
  const b = disposition(grand());
  assert.deepEqual([...a.sieges], [...b.sieges]);
  assert.equal(a.largeur, b.largeur);
});

test('un agent dont la place est inconnue part de la porte de l’Assistant, sans point inventé', () => {
  const plan = disposition(grand());
  assert.equal(plan.noeudDeAgent('fantome'), 'assistant');
});

// Ordre stable : embaucher un worker dans une équipe ne fait changer de rangée aucune autre pièce.
// Pour chaque équipe tour à tour, on ajoute un worker (copie de l'état) et on compare, rangée par rangée, la suite
// des pièces. Le y absolu ne sert pas de critère : la rangée du bas descend quand celle du haut grandit en hauteur
// (plus de rangées de postes), ce qui ne change la rangée de personne.
const FIXTURE = join(dirname(fileURLToPath(import.meta.url)), '..', 'fixtures', 'etat-exemple.json');
const etatExemple = () => JSON.parse(readFileSync(FIXTURE, 'utf8'));

// { haut: [noms dans l'ordre], bas: [noms dans l'ordre] } : la rangée et l'ordre de chaque pièce.
function rangees(plan) {
  const r = { haut: [], bas: [] };
  for (const p of plan.pieces) if (p.haut !== null) (p.haut ? r.haut : r.bas).push(p.nom);
  return r;
}

function embaucher(etat, equipe) {
  const copie = structuredClone(etat);
  copie.agents.push({ id: `nouveau-${equipe}`, role: 'worker', equipe, vivant: true, etat: 'travaille', tache: null, brouillon: null, contexte: { tokens: 40000, limite: 200000 }, cout_usd_estime: 1.5 });
  return copie;
}

for (const [nom, etat] of [['exemple', etatExemple()], ['10 équipes', grand()]]) {
  test(`ordre stable (${nom}) : embaucher un worker dans une équipe ne déplace aucune pièce d'une rangée à l'autre`, () => {
    const avant = rangees(disposition(etat));
    const equipes = [...new Set([...(etat.equipes ?? []).map((e) => e.nom), ...(etat.agents ?? []).filter((a) => a.equipe).map((a) => a.equipe)])];
    assert.ok(equipes.length >= 7, `au moins 7 équipes dans ${nom}`);
    for (const equipe of equipes) {
      const apres = rangees(disposition(embaucher(etat, equipe)));
      assert.deepEqual(apres.haut, avant.haut, `rangée du haut changée après embauche dans ${equipe}`);
      assert.deepEqual(apres.bas, avant.bas, `rangée du bas changée après embauche dans ${equipe}`);
    }
  });
}
