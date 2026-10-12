// scene.js — la scène, montée dans un élément de la page. Sans effet de bord à l'import.
//
//   monterScene(conteneur, { source, surClic, surVide, surSurvol, surStatut, surPret, theme }) → { arreter(), redimensionner(), selectionner(cible | null) }
//   LEGENDE        — les signes de la scène, en données : { sprite, libelle, groupe, probleme }
//   dessinerIcone  — dessine un de ces signes dans un canvas de la page
//
// La scène crée un canvas dans le conteneur et rien d'autre : ni titre, ni aide, ni légende. Elle ne navigue jamais :
// un clic est nommé à la page (surClic), qui ouvre la fiche. Lecture seule : aucune écriture, aucun appel à un agent.

import { ATLAS } from './graphismes/atlas.js';
import { PALETTE } from './graphismes/palette.js';
import { creerFil, appliquerSnapshot, sceneA } from './modele.js';
import { dessiner, dessinerSigne } from './rendu.js';
import { SurfaceCanvas } from './surface-canvas.js';
import { creerBoucle } from './boucle.js';
import { elementSous, infobulle, cibleDe, creerGestes } from './interaction.js';
import { ecrireNoms, ecrireCompteurs } from './noms.js';
import { ajuster, zoomer, deplacer, ecranVersCase, reajuster } from './vue.js';
import { sourceValide } from './source.js';
import { LEGENDE as ENTREES, GROUPES, composer, lignes } from './legende.js';

// ---- Légende : des données, que la page met en forme ------------------------------------------------------------
// sprite  : de quoi dessiner le signe avec dessinerIcone (nom d'un sprite de l'atlas, ou nom d'un motif) ;
// libelle : une phrase courte ; groupe : l'intitulé de sa section ; probleme : signe de problème (le seul rouge permis).
const cle = (e) => e.sprite ?? e.motif;
export const LEGENDE = Object.freeze(
  ENTREES.map((e) => Object.freeze({ sprite: cle(e), libelle: lignes(e).join(' '), groupe: GROUPES[e.groupe], probleme: Boolean(e.probleme) })),
);

const ratioEntier = (doc) => Math.max(1, Math.round(doc.defaultView?.devicePixelRatio || 1));

// Dessine le signe `sprite` (un `sprite` de LEGENDE, ou tout sprite de l'atlas) dans `canvas`, à l'échelle entière
// `echelle` (pixels nets, écrans haute densité compris). Rend false si le signe est inconnu.
export function dessinerIcone(canvas, sprite, { echelle = 2 } = {}) {
  const entree = ENTREES.find((e) => cle(e) === sprite) ?? (ATLAS.sprites[sprite] ? { sprite } : null);
  if (!entree) return false;
  const signe = composer(entree);
  const doc = canvas.ownerDocument;
  const surface = new SurfaceCanvas(doc, ATLAS, PALETTE);
  surface.dimensionner(signe.w, signe.h);
  dessinerSigne(surface, ATLAS, signe, 0, 0);
  const k = Math.max(1, Math.round(echelle));
  const d = ratioEntier(doc);
  surface.dimensionnerEcran(canvas, signe.w * k, signe.h * k, d);
  canvas.style.imageRendering = 'pixelated';
  surface.presenter(canvas, { k, d });
  return true;
}

// ---- La scène dans le conteneur ---------------------------------------------------------------------------------
// Une source qui rejoue un scénario (source rejouée, par exemple dans les tests : `scenario: true`) date ses instantanés elle-même ; le direct est daté
// par la scène, sur sa propre horloge : la date que la source croit juste n'est pas celle de la boucle.
export const dateDeInstantane = (source, t, tScene) => (source.scenario === true && Number.isFinite(t) ? t : tScene);

const DEPLACEMENT_CLAVIER_PX = 64;
const LIBELLE_CANVAS = 'Plan de l’étage : une pièce par équipe, le couloir et la porte de l’utilisateur. Plus et moins zooment, les flèches déplacent, zéro montre tout.';

export function monterScene(conteneur, { source, surClic, surVide, surSurvol, surStatut, surPret, theme } = {}) {
  if (!sourceValide(source)) throw new TypeError('monterScene : la source doit exposer abonner() et arreter()');
  const doc = conteneur.ownerDocument;
  const fenetre = doc.defaultView;

  // Le canvas remplit exactement le conteneur ; il lui faut un repère.
  const positionAvant = conteneur.style.position;
  if (fenetre.getComputedStyle(conteneur).position === 'static') conteneur.style.position = 'relative';
  const canvas = doc.createElement('canvas');
  canvas.setAttribute('aria-label', LIBELLE_CANVAS);
  canvas.tabIndex = 0;
  Object.assign(canvas.style, {
    position: 'absolute',
    left: '0',
    top: '0',
    display: 'block',
    imageRendering: 'pixelated',
    touchAction: 'none', // le pincement sert au zoom de la scène, pas à zoomer la page
    cursor: 'grab',
    background: theme?.fond ?? 'transparent', // le pourtour de l'étage se fond dans la page
  });
  conteneur.appendChild(canvas);

  const surface = new SurfaceCanvas(doc, ATLAS, PALETTE);
  const fil = creerFil();
  let tCourant = 0; // temps relatif de la dernière image : l'horloge des lectures du direct
  let t0 = null;
  let scene = null;
  let vue = null;
  let monde = null;
  let auto = true; // vue ajustée (« tout voir ») tant que ni zoom ni déplacement
  let taille = { w: 0, h: 0 };
  let pret = false;
  let arrete = false;
  let cibleSurvolee = null;
  let selection = null; // la cible que la page a choisie (selectionner) : entourée en bleu tant qu'elle est à l'écran
  // Moins de mouvement demandé au système : le halo ambre reste fixe (le reste de la scène vit de ses animations).
  const pulsation = !fenetre.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;

  const mesurer = () => {
    taille = { w: conteneur.clientWidth, h: conteneur.clientHeight };
  };
  mesurer();
  const observateur = typeof fenetre.ResizeObserver === 'function' ? new fenetre.ResizeObserver(mesurer) : null;
  observateur?.observe(conteneur);

  source.abonner(
    (etat, transitions, t, options = {}) => appliquerSnapshot(fil, etat, transitions, dateDeInstantane(source, t, tCourant), options),
    { surStatut, maintenant: () => tCourant },
  );

  // Les gestes ne modifient la vue qu'une fois la première image dessinée.
  const agir = (f, garderAuto = false) => {
    if (!vue || !monde) return;
    vue = f(vue);
    auto = garderAuto;
  };
  creerGestes(canvas, {
    zoomer: (sens, p) => agir((v) => zoomer(v, sens, p, monde, taille)),
    deplacer: (dx, dy) => agir((v) => deplacer(v, dx, dy, monde, taille)),
    toutVoir: () => agir(() => ajuster(monde, taille), true),
    clic: (p) => {
      const cible = cibleSous(p.x, p.y);
      if (cible) surClic?.(cible.cible);
      else if (scene && vue) surVide?.(); // un clic dans le vide : la page referme son détail
    },
  });

  function cibleSous(px, py) {
    if (!scene || !vue) return null;
    const c = ecranVersCase(vue, px, py);
    const el = elementSous(scene, c.x, c.y);
    const cible = cibleDe(scene, el);
    return cible ? { cible, el } : null;
  }

  canvas.addEventListener('pointermove', (ev) => {
    if (ev.pointerType === 'touch' || ev.buttons) return; // pas de survol au doigt, ni pendant un glisser
    const r = canvas.getBoundingClientRect();
    const x = ev.clientX - r.left;
    const y = ev.clientY - r.top;
    const sous = cibleSous(x, y);
    canvas.style.cursor = sous ? 'pointer' : 'grab';
    const marque = sous ? JSON.stringify(sous.cible) : null;
    if (marque === cibleSurvolee) return;
    cibleSurvolee = marque;
    if (!surSurvol) return;
    if (!sous) return surSurvol(null);
    // L'info-bulle est celle de la scène (état, tâche : jamais de texte libre) ; la page la met en forme à sa façon.
    surSurvol(sous.cible, { x, y, ...(infobulle(scene, sous.el.type, sous.el.id) ?? {}) });
  });
  canvas.addEventListener('pointerleave', () => {
    canvas.style.cursor = 'grab';
    if (cibleSurvolee !== null) {
      cibleSurvolee = null;
      surSurvol?.(null);
    }
  });

  // Clavier, sur la scène seule (le reste de la page garde ses touches) : 0 tout voir, + / − zoom, flèches déplacent.
  canvas.addEventListener('keydown', (ev) => {
    if (ev.ctrlKey || ev.metaKey || ev.altKey || !monde) return;
    const centre = { x: taille.w / 2, y: taille.h / 2 };
    const fleches = { ArrowLeft: [DEPLACEMENT_CLAVIER_PX, 0], ArrowRight: [-DEPLACEMENT_CLAVIER_PX, 0], ArrowUp: [0, DEPLACEMENT_CLAVIER_PX], ArrowDown: [0, -DEPLACEMENT_CLAVIER_PX] };
    if (ev.key === '0') agir(() => ajuster(monde, taille), true);
    else if (ev.key === '+' || ev.key === '=') agir((v) => zoomer(v, 1, centre, monde, taille));
    else if (ev.key === '-') agir((v) => zoomer(v, -1, centre, monde, taille));
    else if (fleches[ev.key]) agir((v) => deplacer(v, ...fleches[ev.key], monde, taille));
    else return;
    ev.preventDefault();
  });

  const boucle = creerBoucle({
    doc,
    planifier: (f) => fenetre.requestAnimationFrame(f),
    annuler: (id) => fenetre.cancelAnimationFrame(id),
    rendre(t) {
      if (t0 === null) t0 = t;
      const tRel = t - t0;
      tCourant = tRel;
      source.avancerA?.(tRel);
      // Sans instantané (direct, hôte pas encore lu) ou conteneur sans taille (onglet masqué) : rien à dessiner.
      if (fil.etat === null || !taille.w || !taille.h) return;
      scene = sceneA(fil, tRel);
      if (surface.largeur !== scene.largeur || surface.hauteur !== scene.hauteurEtage) surface.dimensionner(scene.largeur, scene.hauteurEtage);
      monde = { w: scene.largeur, h: scene.hauteurEtage };
      vue = reajuster(vue, auto, monde, taille);
      const d = ratioEntier(doc);
      dessiner(surface, ATLAS, scene, tRel, { legende: false, selection, pulsation, noms: false });
      surface.dimensionnerEcran(canvas, taille.w, taille.h, d);
      surface.presenter(canvas, { k: vue.echelle, x: vue.x, y: vue.y, d, sy: 0, sh: scene.hauteurEtage });
      const ctxEcran = canvas.getContext('2d');
      ecrireNoms(ctxEcran, scene, vue, { d, police: theme?.police });
      ecrireCompteurs(ctxEcran, scene, vue, { d, police: theme?.police });
      if (!pret) {
        pret = true;
        surPret?.();
      }
    },
  });
  boucle.demarrer();

  return {
    // Le conteneur a changé de taille sans que le navigateur le dise (onglet qui s'affiche, mise en page de la page).
    redimensionner() {
      mesurer();
    },
    // La page nomme la cible dont elle montre le détail (même forme que surClic) ; null retire l'entourage.
    selectionner(cible) {
      selection = cible ?? null;
    },
    arreter() {
      if (arrete) return;
      arrete = true;
      boucle.arreter();
      observateur?.disconnect();
      source.arreter();
      canvas.remove();
      conteneur.style.position = positionAvant;
    },
  };
}
