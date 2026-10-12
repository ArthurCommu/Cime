// etats-bandes.mjs — états d'exemple à N équipes pour les tests de l'étage en bandes.
// Construits à partir de l'état d'exemple : mêmes rôles, mêmes statuts et états d'agents ; seuls les effectifs varient.
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const EXEMPLE = join(dirname(fileURLToPath(import.meta.url)), '..', 'fixtures', 'etat-exemple.json');
const base = JSON.parse(readFileSync(EXEMPLE, 'utf8'));

const STATUTS = [...new Set(base.equipes.map((e) => e.statut).filter(Boolean))];
const ETATS = [...new Set(base.agents.map((a) => a.etat).filter(Boolean))];
const ASSISTANT = base.agents.find((a) => a.role === 'assistant');
const UTILISATEUR = base.agents.find((a) => a.role === 'utilisateur');
const COORDINATEUR = base.agents.find((a) => a.role === 'coordinateur');
const WORKER = base.agents.find((a) => a.role === 'worker');

function agent(modele, id, equipe, etat) {
  return { ...structuredClone(modele), id, equipe, etat, parent: equipe ? `coord-${equipe}` : null, vivant: true };
}

// N équipes. Chaque équipe a de 1 à 4 agents (un coordinateur et 0 à 3 workers), statuts et états variés.
// Les noms reprennent ceux de l'état d'exemple, suffixés : ils ont des longueurs différentes (abrégés si besoin).
export function etatBandes(n) {
  const equipes = [];
  const agents = [structuredClone(ASSISTANT), structuredClone(UTILISATEUR)];
  for (let i = 0; i < n; i++) {
    const nom = `${base.equipes[i % base.equipes.length].nom}-${i}`;
    const taille = 1 + ((i * 7) % 4);
    equipes.push({ nom, statut: STATUTS[i % STATUTS.length] });
    agents.push(agent(COORDINATEUR, `coord-${nom}`, nom, ETATS[i % ETATS.length]));
    for (let k = 1; k < taille; k++) agents.push(agent(WORKER, `worker-${nom}-${k}`, nom, ETATS[(i + k) % ETATS.length]));
  }
  return { ...structuredClone(base), equipes, agents };
}

// N équipes de même effectif (un coordinateur, un worker) : la hauteur doit croître de façon linéaire en bandes.
export function etatUniforme(n) {
  const equipes = [];
  const agents = [structuredClone(ASSISTANT), structuredClone(UTILISATEUR)];
  for (let i = 0; i < n; i++) {
    const nom = `equipe-${String(i).padStart(2, '0')}`;
    equipes.push({ nom, statut: 'active' });
    agents.push(agent(COORDINATEUR, `coord-${nom}`, nom, 'travaille'));
    agents.push(agent(WORKER, `worker-${nom}-1`, nom, 'travaille'));
  }
  return { ...structuredClone(base), equipes, agents };
}

// Copie de l'état avec un worker de plus dans l'équipe.
export function embaucher(etat, equipe) {
  const copie = structuredClone(etat);
  copie.agents.push(agent(WORKER, `nouveau-${equipe}`, equipe, 'travaille'));
  return copie;
}
