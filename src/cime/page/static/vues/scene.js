// Cime — la scène, vue d'accueil. Le plateau est créé une fois et réattaché à chaque rendu : `afficher()`
// reconstruit tout le <body> à chaque instantané, et le canvas de la scène ne doit pas l'être.
// La scène (module servi par l'hôte sous /scene/) est montée une seule fois dans ce plateau ;
// la page lui confie chaque instantané (`alimenter`), elle ne fait aucune requête elle-même.
// À droite du plateau, le rail (vues/rail.js) : les quatre blocs, ou le détail de la cible que la scène a sélectionnée.
// Sur un téléphone (≤ 760 px) le rail passe sous le plateau en trois blocs (la feuille basse) ; le détail de la cible vit alors dans
// une feuille montante (le même contenu que le rail, celui de rail.js) et la porte de l'utilisateur ouvre la feuille des attentes.

import { el, vider, duree, surTic, mesurerLargeur, definirActionsFigees, feuille } from '../commun.js';
import { rendreRail, trouverCible, detailCible } from './rail.js';
import { estTelephone, surChangementDeFormat, ouvrirFeuilleAttentes, fermerFeuilleAttentes, majFeuilleAttentes } from './mobile.js';

/** Créé une seule fois ; gardé en mémoire quand on quitte l'onglet. */
const plateau = el('div', { class: 'plateau', id: 'plateau' });
/** Créé une seule fois comme le plateau ; son contenu est redessiné à chaque instantané et à chaque sélection. */
const rail = el('aside', { class: 'rail', id: 'rail', 'aria-label': 'Ce qui compte maintenant' });

const TITRES_DETAIL = { equipe: 'Équipe', agent: 'Agent', message: 'Échange' };
const SEUIL_GLISSEMENT = 8; // px : au-delà, le pointeur enfoncé « glisse » le plateau
const DECALAGE_INFOBULLE = 12;
const MARGE_INFOBULLE = 8;
const COMMANDES_ZOOM = [
  { touche: '-', signe: '−', titre: 'Zoom arrière (−)' },
  { touche: '+', signe: '+', titre: 'Zoom avant (+)' },
  { touche: '0', signe: '⤢', titre: 'Tout voir (0)' },
];

let promesse = null; // le montage : une seule fois, quel que soit le nombre de rendus
let sourcePage = null; // la source de la page (flux interrompu, âge de la donnée)
let sourceScene = null; // la source alimentée de la scène
let dernierEtat = null; // le dernier instantané reçu, gardé tant que la scène n'est pas montée
let objetScene = null; // ce que rend monterScene
let pret = false;
let selection = null;
let abonnes = [];
let dernierFocus = null; // l'élément du plateau qui avait le focus
let contexteRendu = null; // le dernier contexte de rendu : le rail se redessine d'après lui
let actif = false; // la scène est l'écran courant
let figeRail = false; // l'état figé que le rail a pris en compte (boutons désactivés)
let clignotement = false; // le clic sur la porte de l'utilisateur : le bloc « Ce qui t'attend » clignote au prochain dessin
let vueRail = null; // ce que le rail montrait au dernier dessin : la position de défilement ne se garde que sur la même vue
let defilementRail = 0;
let feuilleDetail = null; // téléphone : la feuille montante du détail de la cible choisie
let aGlisse = false; // téléphone : le plateau a été glissé une fois ; le dégradé du bord droit ne revient plus de la session (variable de module, pas d'état dans le DOM)
let porteOuverte = false; // téléphone : la feuille des attentes a été ouverte par la porte de l'utilisateur

const silhouette = el('div', { class: 'plateau-silhouette', 'aria-hidden': 'true' });
const capsule = el('div', { class: 'capsule-figee', role: 'status', hidden: true });
const legende = el('aside', { class: 'legende', id: 'legende-plateau', 'aria-label': 'Légende', hidden: true });
const boutonLegende = el('button', { type: 'button', class: 'commande-plateau commande-legende', 'aria-expanded': 'false',
  'aria-controls': 'legende-plateau', onclick: () => basculerLegende() }, 'Légende');
const commandes = el('div', { class: 'commandes-zoom' }, COMMANDES_ZOOM.map((c) => el('button', {
  type: 'button', class: 'commande-plateau', title: c.titre, 'aria-label': c.titre, onclick: () => emettreTouche(c.touche) }, c.signe)));
let infobulle = null;

// téléphone : un dégradé sur le bord droit signale que l'étage continue (masqué au bureau par la feuille de style) ; il disparaît au premier glissement
const bordDroit = el('div', { class: 'plateau-bord', 'aria-hidden': 'true' });
plateau.append(silhouette, capsule, legende, boutonLegende, commandes);
if (!aGlisse) plateau.append(bordDroit);
let departGlissement = null;
plateau.addEventListener('pointerdown', (ev) => { departGlissement = { x: ev.clientX, y: ev.clientY }; });
plateau.addEventListener('pointermove', (ev) => {
  if (aGlisse || !departGlissement) return;
  if (Math.hypot(ev.clientX - departGlissement.x, ev.clientY - departGlissement.y) > SEUIL_GLISSEMENT) {
    aGlisse = true;
    bordDroit.remove();
  }
});
for (const fin of ['pointerup', 'pointercancel']) plateau.addEventListener(fin, () => { departGlissement = null; });
rail.addEventListener('scroll', () => { if (rail.isConnected) defilementRail = rail.scrollTop; });

/** La sélection courante, telle que la scène la donne : { type, nom | id } ou null. */
export function selectionCourante() {
  return selection;
}

/** `rappel(selection)` est appelé à chaque changement de sélection. */
export function surSelection(rappel) {
  abonnes = [...abonnes, rappel];
  return () => { abonnes = abonnes.filter((f) => f !== rappel); };
}

/** L'image est figée : la connexion à l'hôte est perdue après le chargement. */
export function estFige() {
  return plateau.dataset.fige === 'oui';
}

function choisir(cible) {
  selection = cible ?? null;
  objetScene?.selectionner?.(selection);
  for (const f of abonnes) f(selection);
}

// ---- Le rail --------------------------------------------------------------------------------------------------------
/** Redessine le rail d'après le dernier instantané et la sélection courante ; jamais d'après le DOM. */
function dessinerRail() {
  if (!actif || !contexteRendu) return;
  const etat = contexteRendu.etat;
  if (selection && selection.type !== 'utilisateur' && !trouverCible(selection, etat)) {
    choisir(null); // la cible a disparu de l'instantané : le détail se referme, la sélection est annulée
    return;
  }
  const telephone = estTelephone();
  const vue = selection && selection.type !== 'utilisateur' ? `${selection.type}:${selection.nom ?? selection.id}` : 'blocs';
  const haut = vue === vueRail ? defilementRail : 0;
  vueRail = vue;
  rendreRail(rail, { etat, selection, fermer: () => choisir(null), ouvrir: choisir, redessiner: dessinerRail, clignote: clignotement, telephone });
  clignotement = false;
  rail.scrollTop = haut;
  defilementRail = rail.scrollTop;
  synchroniserFeuilles(etat, telephone);
  mesurerLargeur();
}

// ---- Les feuilles du téléphone ------------------------------------------------------------------------------------------
function fermerFeuilleDetail() {
  const ouverte = feuilleDetail;
  feuilleDetail = null; // d'abord : la fermeture rappelle surFermeture, qui ne doit plus rien annuler
  ouverte?.fermer();
}

/**
 * Téléphone : le détail de la cible choisie est dans une feuille montante (redessinée sur place à chaque instantané), la porte de l'utilisateur
 * ouvre la feuille des attentes ; fermer une feuille, c'est choisir `null`. Au bureau (ou hors de la scène) aucune feuille.
 */
function synchroniserFeuilles(etat, telephone) {
  const cible = telephone && selection && selection.type !== 'utilisateur' ? trouverCible(selection, etat) : null;
  if (!cible) {
    fermerFeuilleDetail();
  } else if (feuilleDetail) {
    feuilleDetail.retitrer(TITRES_DETAIL[selection.type]);
    feuilleDetail.remplacer(detailCible(cible, etat, choisir));
  } else {
    const ouverte = feuille(TITRES_DETAIL[selection.type], [detailCible(cible, etat, choisir)], {
      surFermeture: () => {
        if (feuilleDetail !== ouverte) return;
        feuilleDetail = null;
        choisir(null);
      },
    });
    feuilleDetail = ouverte;
  }
  const porte = telephone && selection !== null && selection.type === 'utilisateur';
  if (porte && !porteOuverte) {
    porteOuverte = true;
    ouvrirFeuilleAttentes({ surFermeture: () => { porteOuverte = false; if (selection && selection.type === 'utilisateur') choisir(null); } });
  } else if (!porte && porteOuverte) {
    fermerFeuilleAttentes(); // sa fermeture remet porteOuverte à faux
  }
}

surSelection((cible) => {
  clignotement = Boolean(cible && cible.type === 'utilisateur');
  dessinerRail();
});

/** Chaque instantané reçu par la page, que l'onglet courant soit la scène ou non. */
export function alimenter(etat) {
  dernierEtat = etat;
  sourceScene?.pousser(etat);
}

function emettreTouche(key) {
  // le canvas de la scène, enfant direct du plateau : la légende porte les siens (une icône par ligne)
  const canvas = plateau.querySelector(':scope > canvas');
  if (canvas) canvas.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
}

function basculerLegende(ouverte = legende.hidden) {
  legende.hidden = !ouverte;
  boutonLegende.setAttribute('aria-expanded', String(ouverte));
}

// ---- L'info-bulle de la page -------------------------------------------------------------------------------------
function survol(cible, { x = 0, y = 0, titre = '', lignes = [] } = {}) {
  infobulle?.remove();
  infobulle = null;
  if (!cible) return;
  infobulle = el('div', { class: 'infobulle-plateau', role: 'tooltip' },
    el('div', { class: 'infobulle-titre' }, titre),
    lignes.map((l) => el('div', { class: 'infobulle-ligne' }, l)));
  plateau.append(infobulle);
  const gauche = Math.min(x + DECALAGE_INFOBULLE, plateau.clientWidth - infobulle.offsetWidth - MARGE_INFOBULLE);
  const haut = Math.min(y + DECALAGE_INFOBULLE, plateau.clientHeight - infobulle.offsetHeight - MARGE_INFOBULLE);
  infobulle.style.left = `${Math.max(MARGE_INFOBULLE, gauche)}px`;
  infobulle.style.top = `${Math.max(MARGE_INFOBULLE, haut)}px`;
}

// ---- La légende, lue dans les données de la scène ----------------------------------------------------------------
function remplirLegende(entrees, dessinerIcone) {
  const groupes = new Map();
  for (const e of entrees) {
    groupes.set(e.groupe, [...(groupes.get(e.groupe) ?? []), e]);
  }
  vider(legende, [...groupes].map(([nom, lignes]) => el('section', { class: 'legende-groupe' },
    el('h3', {}, nom),
    lignes.map((e) => {
      const icone = el('canvas', { width: 32, height: 32 });
      dessinerIcone(icone, e.sprite, { echelle: 2 });
      return el('div', { class: 'legende-ligne' },
        el('span', { class: 'legende-icone' }, icone),
        el('span', { class: e.probleme ? 'legende-libelle legende-probleme' : 'legende-libelle' }, e.libelle));
    }))));
}

// ---- L'état figé : la connexion est perdue après le chargement -----------------------------------------------------
function majFige() {
  const fige = Boolean(pret && sourcePage && sourcePage.fluxInterrompu());
  if (fige !== figeRail) {
    figeRail = fige;
    definirActionsFigees(fige); // les boutons d'action du rail se désactivent (ou se réactivent)
    dessinerRail();
    if (dernierEtat) majFeuilleAttentes(dernierEtat); // et ceux de la feuille des attentes, si elle est ouverte
  }
  if (fige) {
    plateau.dataset.fige = 'oui';
    vider(capsule, `Image figée depuis ${duree(sourcePage.horloge.ageDonnee())} — l’hôte ne répond plus`);
  } else {
    delete plateau.dataset.fige;
  }
  capsule.hidden = !fige;
}

// ---- Le montage ----------------------------------------------------------------------------------------------------
function repli() {
  vider(plateau, el('p', { class: 'plateau-calme' }, 'La scène n’est pas disponible ici.'));
}

async function monter() {
  let module;
  try {
    const [scene, alimentee] = await Promise.all([import('/scene/scene.js'), import('/scene/source-alimentee.js')]);
    module = { scene, alimentee };
  } catch {
    repli();
    return;
  }
  const { monterScene, LEGENDE, dessinerIcone } = module.scene;
  sourceScene = module.alimentee.creerSourceAlimentee({ maintenant: () => performance.now() });
  if (dernierEtat) sourceScene.pousser(dernierEtat); // le premier instantané, reçu avant le montage
  try {
    objetScene = monterScene(plateau, {
      source: sourceScene,
      surClic: (cible) => { basculerLegende(false); choisir(cible); }, // un clic dans la scène referme la légende
      surVide: () => { basculerLegende(false); choisir(null); },
      surSurvol: survol,
      surStatut: () => {},
      surPret: () => { pret = true; silhouette.remove(); majFige(); },
      theme: { fond: 'transparent' },
    });
    if (LEGENDE && dessinerIcone) remplirLegende(LEGENDE, dessinerIcone);
  } catch {
    sourceScene = null;
    repli();
  }
}

plateau.addEventListener('keydown', (ev) => {
  if (ev.key !== 'Escape') return;
  if (!legende.hidden) basculerLegende(false);
  else if (selection) choisir(null);
});
// Échap ferme aussi le détail quand le focus est ailleurs (dans le rail, ou nulle part) ; le plateau a son propre écouteur
document.addEventListener('keydown', (ev) => {
  if (ev.key !== 'Escape' || !actif || plateau.contains(ev.target) || document.querySelector('dialog[open]')) return;
  if (selection) choisir(null);
});
// Le focus du canvas se perd quand la page reconstruit son <body> : on le rend à la scène au rendu suivant.
document.addEventListener('focusin', (ev) => { dernierFocus = plateau.contains(ev.target) ? ev.target : null; });
surTic(majFige);
// passer du bureau au téléphone (rotation, fenêtre redimensionnée) change la forme du rail et des feuilles
surChangementDeFormat(dessinerRail);

export function rendre(ctx) {
  sourcePage = ctx.source;
  // appendChild d'un nœud existant le déplace sans le détruire
  ctx.contenu.append(el('section', { class: 'accueil' }, plateau, rail));
  contexteRendu = ctx;
  actif = true;
  dessinerRail();
  if (!promesse) {
    dernierEtat ??= ctx.etat;
    promesse = monter();
  }
  objetScene?.redimensionner();
  dernierFocus?.focus({ preventScroll: true });
  majFige();
  ctx.tic();
  mesurerLargeur();
  return () => { actif = false; fermerFeuilleDetail(); fermerFeuilleAttentes(); };
}
