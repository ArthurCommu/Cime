// Cime — point d'entrée de la page : la couche de données, la navigation par
// ancre (#/ = la scène, #/supervision, #/fil, #/journal, #/equipe/<nom>, #/archives)
// et le réaffichage à chaque nouvel instantané.

import { creerSource } from './source.js';
import { brancher, rendreSocle, demarrerTic, rendreInjoignable, nouvelInstantane, mesurerLargeur } from './commun.js';
import * as scene from './vues/scene.js';
import * as ensemble from './vues/ensemble.js';
import * as fil from './vues/fil.js';
import * as journal from './vues/journal.js';
import * as equipe from './vues/equipe.js';
import * as archives from './vues/archives.js';
import { rendreMobile } from './vues/mobile.js';

const VUES = { scene, supervision: ensemble, fil, journal, equipe, archives };

/** « #/equipe/hote » → { page: 'equipe', nom: 'hote' } ; « #/fil?agent=x » → params. */
function lireRoute() {
  const brut = location.hash.replace(/^#/, '');
  // ancre courte de l'onglet Dépendances de Supervision
  if (brut === 'dependances') return { page: 'supervision', nom: null, params: new URLSearchParams('onglet=dependances'), cle: 'supervision' };
  const [chemin, requete = ''] = brut.split('?');
  const morceaux = chemin.split('/').filter(Boolean);
  const page = morceaux[0] in VUES ? morceaux[0] : 'scene';
  let nom = null;
  if (page === 'equipe' && morceaux[1]) {
    try { nom = decodeURIComponent(morceaux[1]); } catch { nom = morceaux[1]; }
  }
  return { page, nom, params: new URLSearchParams(requete), cle: page === 'equipe' ? `equipe/${nom}` : page };
}

const source = creerSource();
let route = lireRoute();
/** Ce qu'il faut arrêter en quittant l'écran courant (lecture du terminal). */
let arreterVue = null;

/** Réaffiche le socle et l'écran courant, sans perdre la position dans la page. */
function afficher() {
  const y = window.scrollY;
  // la page garde sa hauteur le temps que le graphe se redispose : pas de saut de défilement
  document.body.style.minHeight = `${document.body.scrollHeight}px`;
  const ctx = rendreSocle({ etat: source.etat(), journal: source.journal(), page: route.page, route, source, rerendre: afficher });
  rendreMobile(ctx); // les attentes en tête d'écran et la barre du bas (masquées au bureau)
  const arret = VUES[route.page].rendre(ctx);
  if (typeof arret === 'function') arreterVue = arret;
  mesurerLargeur();
  window.scrollTo(0, y);
  requestAnimationFrame(() => requestAnimationFrame(() => { document.body.style.minHeight = ''; }));
}

addEventListener('hashchange', () => {
  const nouvelle = lireRoute();
  if (nouvelle.cle !== route.cle && arreterVue) {
    arreterVue();
    arreterVue = null;
  }
  route = nouvelle;
  afficher();
  window.scrollTo(0, 0);
});

brancher(source, afficher);
source.abonner((quoi, change) => {
  if (quoi === 'etat') {
    // la scène reste à jour en arrière-plan : elle reçoit chaque instantané, quel que soit l'onglet courant
    scene.alimenter(source.etat());
    // un nouvel instantané clôt les actions « envoyées » : il dit seul ce qui a été pris en compte
    const avaitEnvoyees = nouvelInstantane();
    if (change || avaitEnvoyees) afficher();
  } else {
    afficher();
  }
});

try {
  await source.demarrer({ injoignable: rendreInjoignable });
  demarrerTic();
  afficher();
} catch (e) {
  // l'hôte injoignable est réessayé sans fin ; ceci n'attrape qu'une erreur de démarrage imprévue
  rendreInjoignable({ essai: 1, erreur: `démarrage impossible : ${e.message}`, delai: 0 });
}
