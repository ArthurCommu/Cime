// source-directe.js — source du direct : l'hôte, en lecture seule.
//   GET /api/flux?depuis=        → ligne de base : dernier_id. L'historique n'est pas animé.
//   GET /api/etat                → l'instantané de départ (sans age_ms).
//   EventSource /api/flux        → un événement « etat » par instantané (données complètes).
//   GET /api/flux?depuis=<id>    → les transitions nouvelles depuis le précédent instantané.
// Que des GET et un EventSource : aucune écriture, aucun appel à un agent.
// Une mesure ratée n'est jamais « zéro transition » : elle est signalée par le statut.

const DELAI_REPRISE_MS = 5000;

function sansAge({ age_ms: _age, ...etat }) {
  return etat;
}

export function creerSourceDirecte({
  base = '',
  fetch = globalThis.fetch,
  EventSource = globalThis.EventSource,
  maintenant = () => 0,
  planifier = (f, ms) => globalThis.setTimeout(f, ms),
  annuler = (id) => globalThis.clearTimeout(id),
} = {}) {
  let cb = null;
  let surStatut = () => {};
  let flux = null; // EventSource ouvert après la ligne de base
  let dernierId = null; // id de la dernière transition rendue
  let demarree = false;
  let arrete = false;
  let reprise = null;
  let file = Promise.resolve(); // une lecture à la fois : les transitions restent dans l'ordre

  const enFile = (tache) => {
    file = file.then(tache).catch(() => {});
  };
  const statut = (s) => {
    if (!arrete) surStatut(s);
  };
  const emettre = (...args) => {
    if (!arrete && cb) cb(...args);
  };
  const lire = async (chemin) => {
    const r = await fetch(`${base}${chemin}`, { method: 'GET', headers: { accept: 'application/json' } });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  };

  // Ligne de base : rien n'est affiché tant qu'elle n'a pas réussi.
  async function synchroniser() {
    statut('connexion');
    try {
      const [fil, corps] = await Promise.all([lire('/api/flux?depuis='), lire('/api/etat')]);
      if (arrete) return false;
      if (!Number.isInteger(fil.dernier_id)) throw new Error('dernier_id absent');
      dernierId = fil.dernier_id;
      emettre(sansAge(corps), [], maintenant(), { reset: true });
      statut('connecte');
      return true;
    } catch {
      statut('hote-injoignable');
      return false;
    }
  }

  async function surEtat(donnees) {
    let etat;
    try {
      etat = sansAge(JSON.parse(donnees));
    } catch {
      statut('evenement-illisible');
      return;
    }
    let transitions = [];
    try {
      const corps = await lire(`/api/flux?depuis=${dernierId}`);
      transitions = corps.transitions.map((tr) => ({ id: tr.message_id, etat: tr.etat, de: tr.de, a: tr.a }));
      dernierId = corps.dernier_id;
      emettre(etat, transitions, maintenant(), { reset: false });
      statut('connecte');
    } catch {
      // Snapshot montré, transitions non inventées : la mesure ratée est signalée.
      emettre(etat, [], maintenant(), { reset: false });
      statut('transitions-indisponibles');
    }
  }

  function ouvrirFlux() {
    flux = new EventSource(`${base}/api/flux`);
    flux.addEventListener('etat', (ev) => enFile(() => surEtat(ev.data)));
    flux.onopen = () => statut('connecte');
    flux.onerror = () => statut('reconnexion'); // EventSource se reconnecte seul
  }

  async function demarrer() {
    if (arrete) return;
    if (await synchroniser()) {
      if (!arrete && flux === null) ouvrirFlux();
    } else if (!arrete) {
      reprise = planifier(() => {
        reprise = null;
        enFile(demarrer);
      }, DELAI_REPRISE_MS);
    }
  }

  return {
    abonner(c, { surStatut: s } = {}) {
      cb = c;
      surStatut = s ?? (() => {});
      if (!demarree) {
        demarree = true;
        enFile(demarrer);
      }
    },
    arreter() {
      arrete = true;
      cb = null;
      if (flux !== null) flux.close();
      flux = null;
      if (reprise !== null) annuler(reprise);
      reprise = null;
    },
    // Le direct ne se cale pas sur le temps de la boucle : il avance quand l'hôte le dit.
    avancerA() {},
  };
}
