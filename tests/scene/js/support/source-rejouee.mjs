// source-rejouee.mjs — rejoue un scénario d'essai pour les tests, en boucle.
// Aucun réseau. Le temps est absolu (ms) ; la boucle recommence à chaque multiple de la durée,
// en repartant de l'instantané initial (cb reçoit reset = true).
// Une étape du scénario est appliquée à une copie ; chaque transition est reportée dans flux[].

import { DUREE_MS, PAS } from './scenario.mjs';

function fusionner(etat, tr) {
  etat.flux ??= [];
  let it = etat.flux.find((f) => f.id === tr.message_id);
  if (!it) {
    it = { id: tr.message_id, de: tr.de, a: tr.a, nature: tr.nature ?? null, objet: tr.objet ?? null, resume: null, etat: tr.etat, debiteur: null, echeance: null, transitions: [] };
    etat.flux.push(it);
  }
  it.transitions.push({ etat: tr.etat, horodatage: null, voie: tr.voie ?? null, auteur: tr.auteur ?? 'cime' });
  it.etat = tr.etat;
  if ('debiteur' in tr) it.debiteur = tr.debiteur;
  if ('echeance' in tr) it.echeance = tr.echeance;
  return { id: tr.message_id, etat: tr.etat, de: it.de, a: it.a };
}

export function creerSourceRejouee({ etatInitial, duree = DUREE_MS, pas = PAS }) {
  const ordonnes = [...pas].sort((a, b) => a.t - b.t);
  let cb = null;
  let arrete = false;
  let base = null;
  let etat = null;
  let suivant = 0;

  function emettre(trs, t, reset) {
    if (cb && !arrete) cb(structuredClone(etat), trs, t, { reset });
  }

  function repartir(tBase) {
    base = tBase;
    etat = structuredClone(etatInitial);
    suivant = 0;
    emettre([], tBase, true);
  }

  return {
    duree,
    scenario: true, // rejoue un scénario : ses instantanés portent leur propre date (scene.js)
    abonner(c) {
      cb = c;
      if (base === null) repartir(0);
      else emettre([], base, true);
    },
    arreter() {
      arrete = true;
      cb = null;
    },
    // Avance le scénario jusqu'à tAbs (ms absolues) ; émet chaque étape franchie, dans l'ordre.
    avancerA(tAbs) {
      if (arrete) return;
      const b = Math.floor(tAbs / duree) * duree;
      if (base !== b) repartir(b);
      const local = tAbs - base;
      while (suivant < ordonnes.length && ordonnes[suivant].t <= local) {
        const p = ordonnes[suivant++];
        if (p.patch) p.patch(etat);
        const trs = (p.transitions ?? []).map((tr) => fusionner(etat, tr));
        emettre(trs, base + p.t, false);
      }
    },
  };
}
