// Cime — couche de données : le seul module qui sait d'où viennent les données.
//
// L'instantané et le journal viennent de l'hôte local (GET /api/etat, puis le flux
// SSE /api/flux), les actions lui sont postées.
//
// Interface commune :
//   demarrer({ injoignable })   → Promise, résolue au premier instantané
//   etat()                      → l'instantané courant
//   abonner(fn)                 → fn('etat', change) à chaque instantané reçu,
//                                 fn('journal') quand le journal a changé
//   journal()                   → lignes du journal (null si jamais lu)
//   horloge.maintenant()        → l'heure de l'instantané, qui avance
//   horloge.ageDonnee()         → âge de la donnée affichée (ms)
//   fluxInterrompu()            → true si le flux est muet ou en erreur
//   agentsAvecTerminal(agents)  → ceux dont on peut lire le terminal
//   terminal(id)                → Promise<{ texte, capture_a }>
//   texte(message)              → Promise<{ paragraphes, fichier, note }>
//   agir(action, corps, trace)  → Promise<{ resultat, message }>

// ---------------------------------------------------------------------------
// Seuils (constantes nommées)
// ---------------------------------------------------------------------------
/** Sans aucun événement (`etat` ou `vivant`) depuis ce délai, le flux est dit interrompu. */
export const FLUX_MUET_MS = 25_000;
/** Le journal est relu au plus toutes les 5 s quand des instantanés arrivent. */
export const JOURNAL_PERIODE_MIN_MS = 5_000;
/** Nouvel essai de lecture de l'instantané quand l'hôte ne répond pas au chargement. */
export const HOTE_REESSAI_MS = 3_000;
/** Un EventSource fermé pour de bon (réponse non SSE) est rouvert après ce délai. */
const FLUX_REOUVERTURE_MS = 5_000;
export const JOURNAL_LIMITE = 100;

const ROUTES_ACTIONS = {
  autoriser: '/api/actions/autoriser',
  refuser: '/api/actions/refuser',
  accorder: '/api/actions/accorder',
  trancher: '/api/actions/trancher',
  deposer: '/api/actions/deposer',
  lu: '/api/actions/lu',
  cloturer: '/api/actions/cloturer',
  demander: '/api/actions/demander',
  fusions_auto: '/api/actions/fusions-auto',
};

const RESULTATS = new Set(['ok', 'refuse', 'erreur']);

export function creerSource() {
  return sourceHote();
}

/**
 * Horloge de l'instantané : « maintenant » vaut `genere_a` + âge de la donnée à
 * la réception + temps écoulé depuis. On vit ainsi à l'heure de l'hôte, quel que soit le réglage de l'horloge du navigateur.
 */
function horlogeDe(lire) {
  return {
    maintenant: () => { const h = lire(); return h.base + h.age + (performance.now() - h.recu); },
    ageDonnee: () => { const h = lire(); return h.age + (performance.now() - h.recu); },
  };
}

/** Deux instantanés qui ne diffèrent que par leur date de collecte ne réaffichent rien. */
function signature(etat) {
  const { genere_a: _g, age_ms: _a, duree_collecte_ms: _d, ...reste } = etat;
  return JSON.stringify(reste);
}

const attendre = (ms) => new Promise((r) => { setTimeout(r, ms); });

// ---------------------------------------------------------------------------
// Source « hôte »
// ---------------------------------------------------------------------------
function sourceHote() {
  let etat = null;
  let sig = '';
  let journal = null;
  let temps = { base: 0, age: 0, recu: performance.now() };
  let dernierEvenement = performance.now();
  let enErreur = false;
  let journalLuA = -Infinity;
  let journalPrevu = null;
  const abonnes = new Set();
  const prevenir = (...quoi) => abonnes.forEach((fn) => fn(...quoi));

  function recevoir(instantane) {
    temps = { base: Date.parse(instantane.genere_a), age: Number(instantane.age_ms) || 0, recu: performance.now() };
    const nouvelle = signature(instantane);
    const change = nouvelle !== sig;
    etat = instantane;
    sig = nouvelle;
    return change;
  }

  async function lireJson(url) {
    const r = await fetch(url, { headers: { Accept: 'application/json' } });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  }

  async function relireJournal() {
    journalLuA = performance.now();
    try {
      const donnees = await lireJson(`/api/journal?limite=${JOURNAL_LIMITE}`);
      const lignes = Array.isArray(donnees.lignes) ? donnees.lignes : [];
      if (journal && JSON.stringify(lignes) === JSON.stringify(journal)) return;
      journal = lignes;
      prevenir('journal');
    } catch { /* on garde le dernier journal lu */ }
  }

  /** Après un nouvel instantané : relire le journal, au plus toutes les 5 s. */
  function journalApresInstantane() {
    if (journalPrevu) return;
    const reste = JOURNAL_PERIODE_MIN_MS - (performance.now() - journalLuA);
    if (reste <= 0) { relireJournal(); return; }
    journalPrevu = setTimeout(() => { journalPrevu = null; relireJournal(); }, reste);
  }

  function ouvrirFlux() {
    const flux = new EventSource('/api/flux');
    const vivant = () => { dernierEvenement = performance.now(); enErreur = false; };
    flux.addEventListener('etat', (ev) => {
      vivant();
      let instantane;
      try { instantane = JSON.parse(ev.data); } catch { return; }
      // toujours prévenir, même sans changement : un nouvel instantané clôt les actions envoyées
      prevenir('etat', recevoir(instantane));
      journalApresInstantane();
    });
    flux.addEventListener('vivant', vivant);
    flux.addEventListener('error', () => {
      enErreur = true;
      // EventSource se reconnecte seul, sauf s'il est fermé pour de bon
      if (flux.readyState === EventSource.CLOSED) {
        setTimeout(ouvrirFlux, FLUX_REOUVERTURE_MS);
      }
    });
  }

  async function poster(action, corps) {
    const route = ROUTES_ACTIONS[action];
    let init;
    if (action === 'deposer') {
      const formulaire = new FormData();
      formulaire.append('attente_id', corps.attente_id);
      for (const f of corps.fichiers) formulaire.append('fichier', f, f.name);
      init = { method: 'POST', body: formulaire };
    } else {
      init = { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(corps) };
    }
    let reponse;
    try {
      reponse = await fetch(route, init);
    } catch (e) {
      return { resultat: 'erreur', message: `hôte injoignable (${e.message})` };
    }
    let donnees = null;
    try { donnees = await reponse.json(); } catch { /* corps illisible */ }
    relireJournal();
    if (donnees && RESULTATS.has(donnees.resultat)) {
      return { resultat: donnees.resultat, message: String(donnees.message || '') };
    }
    return { resultat: 'erreur', message: `réponse inattendue de l’hôte (HTTP ${reponse.status})` };
  }

  return {
    async demarrer({ injoignable }) {
      for (let essai = 1; ; essai += 1) {
        try {
          recevoir(await lireJson('/api/etat'));
          break;
        } catch (e) {
          injoignable({ essai, erreur: e.message, delai: HOTE_REESSAI_MS });
          await attendre(HOTE_REESSAI_MS);
        }
      }
      dernierEvenement = performance.now();
      ouvrirFlux();
      relireJournal();
    },
    etat: () => etat,
    abonner: (fn) => abonnes.add(fn),
    journal: () => journal,
    horloge: horlogeDe(() => temps),
    fluxInterrompu: () => enErreur || performance.now() - dernierEvenement > FLUX_MUET_MS,
    agentsAvecTerminal: (agents) => agents.filter((a) => a.session_tmux && a.vivant !== false),
    async terminal(id) {
      const r = await fetch(`/api/agents/${encodeURIComponent(id)}/terminal`);
      if (r.status === 404) throw new Error('aucune capture pour cet agent');
      if (!r.ok) throw new Error(`capture illisible (HTTP ${r.status})`);
      return r.json();
    },
    async texte(message) {
      if (!message.fichier) return { paragraphes: [message.resume], fichier: null };
      const r = await fetch(`/api/fichier?chemin=${encodeURIComponent(message.fichier)}`);
      if (r.status === 403) throw new Error('l’hôte refuse de lire ce fichier : il n’est pas sous .orga/');
      if (r.status === 404) throw new Error('fichier introuvable : il a peut-être été déplacé ou supprimé');
      if (!r.ok) throw new Error(`lecture impossible (HTTP ${r.status})`);
      return { paragraphes: [message.resume], contenu: await r.text(), fichier: message.fichier };
    },
    async texteRapport(message) {
      if (!message || !message.fichier) throw new Error('aucun fichier n’accompagne ce compte rendu dans le fil');
      return this.texte(message);
    },
    agir: (action, corps) => poster(action, corps),
  };
}
