// source-alimentee.js — source de la scène pour la page : UN SEUL EventSource dans toute l'application (celui de la page).
// La page reçoit les instantanés et les confie à pousser(etat) ; cette source n'ouvre aucun flux, elle ne fait que des GET :
//   GET /api/flux?depuis=        → ligne de base : dernier_id (l'historique n'est pas animé) ;
//   GET /api/flux?depuis=<id>    → les transitions nouvelles depuis le précédent instantané (les enveloppes se déplacent).
// Même forme que source-directe.js : abonner(cb, { surStatut }) / arreter(), cb(etat, transitions, t, { reset }).
// Lecture seule : aucune écriture, aucun appel à un agent. Une mesure ratée n'est jamais « zéro transition » : statut.

const DELAI_LECTURE_MS = 5000;

function sansAge({ age_ms: _age, ...etat }) {
  return etat;
}

export function creerSourceAlimentee({ base = '', fetch = globalThis.fetch, maintenant = () => 0 } = {}) {
  let cb = null;
  let surStatut = () => {};
  let dernierId = null; // id de la dernière transition rendue ; null tant que la ligne de base manque
  let dernier = null; // dernier instantané poussé (la page peut pousser avant que la scène s'abonne)
  let arrete = false;
  let file = Promise.resolve(); // une lecture à la fois : les transitions restent dans l'ordre

  const statut = (s) => {
    if (!arrete) surStatut(s);
  };
  const emettre = (...args) => {
    if (!arrete && cb) cb(...args);
  };
  const lire = async (chemin) => {
    // Une lecture qui ne répond pas ne doit pas figer la file : les instantanés suivants passeraient derrière elle.
    const signal = globalThis.AbortSignal?.timeout?.(DELAI_LECTURE_MS);
    const r = await fetch(`${base}${chemin}`, { method: 'GET', headers: { accept: 'application/json' }, ...(signal ? { signal } : {}) });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  };

  async function traiter(etat) {
    if (arrete) return;
    if (dernierId === null) {
      // Le premier instantané est montré tout de suite : la ligne de base ne sert qu'aux transitions suivantes,
      // elle ne retarde pas l'image et, si elle échoue, l'état est montré tel quel, sans transition inventée.
      emettre(etat, [], maintenant(), { reset: true });
      try {
        const fil = await lire('/api/flux?depuis=');
        if (!Number.isInteger(fil.dernier_id)) throw new Error('dernier_id absent');
        dernierId = fil.dernier_id;
        statut('connecte');
      } catch {
        statut('transitions-indisponibles');
      }
      return;
    }
    try {
      const corps = await lire(`/api/flux?depuis=${dernierId}`);
      const transitions = corps.transitions.map((tr) => ({ id: tr.message_id, etat: tr.etat, de: tr.de, a: tr.a }));
      dernierId = corps.dernier_id;
      emettre(etat, transitions, maintenant(), { reset: false });
      statut('connecte');
    } catch {
      emettre(etat, [], maintenant(), { reset: false });
      statut('transitions-indisponibles');
    }
  }

  const enFile = (etat) => {
    file = file.then(() => traiter(etat)).catch(() => {});
  };

  return {
    abonner(c, { surStatut: s } = {}) {
      cb = c;
      surStatut = s ?? (() => {});
      if (dernier !== null) enFile(dernier);
    },
    // La page confie ici chaque instantané qu'elle reçoit (le premier compris).
    pousser(etat) {
      if (arrete) return;
      dernier = sansAge(etat);
      if (cb) enFile(dernier);
    },
    arreter() {
      arrete = true;
      cb = null;
    },
    // Le direct avance quand l'hôte le dit, pas au rythme de la boucle.
    avancerA() {},
  };
}
