// vue.js — vue de la scène : zoom par paliers entiers, déplacement borné, passage écran ↔ monde.
// Module pur (sans DOM) : testable sous node. Lecture seule : rien n'est écrit dans l'état de l'entreprise.
//
// Une vue = { echelle, x, y } : echelle est un entier entre 1 et PALIER_MAX (pixels écran par pixel de l'étage),
// x et y sont le décalage de l'origine de l'étage dans le port, en pixels écran. L'étage n'est jamais dessiné
// à une échelle fractionnaire : pixels nets.

export const PALIER_MAX = 6;

const borne = (v, min, max) => Math.min(max, Math.max(min, v));
const echelleValide = (e) => borne(Math.round(e), 1, PALIER_MAX);

// Un axe : centré quand l'étage tient dans le port ; sinon le décalage reste entre « l'étage couvre le port »
// et « l'origine de l'étage est au bord du port ». Jamais de vide entre l'étage et le port.
function axe(d, taille, portTaille) {
  if (taille <= portTaille) return Math.floor((portTaille - taille) / 2);
  return borne(Math.round(d), portTaille - taille, 0);
}

// Ramène une vue dans les bornes du port pour un étage de taille monde (w, h, en pixels de l'étage).
export function borner(vue, monde, port) {
  const echelle = echelleValide(vue.echelle);
  return {
    echelle,
    x: axe(vue.x, monde.w * echelle, port.w),
    y: axe(vue.y, monde.h * echelle, port.h),
  };
}

// « Tout voir » : le plus grand entier (≤ PALIER_MAX, ≥ 1) tel que l'étage entier tient dans le port, centré.
export function ajuster(monde, port) {
  const k = Math.floor(Math.min(port.w / monde.w, port.h / monde.h));
  return borner({ echelle: Math.max(1, k), x: 0, y: 0 }, monde, port);
}

// Vue de chaque image. Tant que la personne n'a ni zoomé ni déplacé (« auto »), l'étage reste ajusté : si le port ou
// l'étage change (légende dimensionnée après coup, fenêtre redimensionnée, pièce qui apparaît), « tout voir » est
// rejoué. Sinon l'échelle choisie est gardée et seules les bornes sont rejouées.
export function reajuster(vue, auto, monde, port) {
  return auto || vue === null ? ajuster(monde, port) : borner(vue, monde, port);
}

// Un palier (sens > 0 : zoom avant ; sens < 0 : zoom arrière), centré sur le point écran donné.
// Le point de l'étage sous le curseur reste sous le curseur (à l'arrondi du décalage près) sauf aux bornes.
export function zoomer(vue, sens, point, monde, port) {
  const pas = Math.sign(sens);
  const echelle = echelleValide(vue.echelle + pas);
  if (!pas || echelle === vue.echelle) return borner(vue, monde, port);
  const sous = ecranVersMonde(vue, point.x, point.y);

  return borner(
    { echelle, x: Math.round(point.x - sous.x * echelle), y: Math.round(point.y - sous.y * echelle) },
    monde,
    port,
  );
}

// Déplacement en pixels écran, borné.
export function deplacer(vue, dx, dy, monde, port) {
  return borner({ echelle: vue.echelle, x: vue.x + dx, y: vue.y + dy }, monde, port);
}

export const ecranVersMonde = (vue, px, py) => ({ x: (px - vue.x) / vue.echelle, y: (py - vue.y) / vue.echelle });
export const mondeVersEcran = (vue, x, y) => ({ x: vue.x + x * vue.echelle, y: vue.y + y * vue.echelle });

// Case de l'étage (entiers) sous un point écran : c'est elle que cherche un clic.
export function ecranVersCase(vue, px, py) {
  const m = ecranVersMonde(vue, px, py);
  return { x: Math.floor(m.x), y: Math.floor(m.y) };
}
