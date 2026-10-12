// noms.js — les noms des pièces, écrits à la résolution de l'écran.
// La police pixel de l'étage (5×7) ne donne, à ×1 ou ×2, que des lettres de 5 à 14 px de large qu'on ne lit pas d'un coup
// d'œil. Le nom est donc écrit par-dessus l'étage, dans la police de la page (theme.police), à la taille qui convient à
// l'échelle de la vue : l'étage garde ses pixels nets, le texte a les siens. La zone est celle du nom pixel (plan.js).
// Rien d'autre n'est écrit : pas d'état, pas de texte libre ; le nom d'une équipe est une clé du registre.

import { ATLAS } from './graphismes/atlas.js';
import { COULEURS } from './rendu.js';

export const POLICE_PAR_DEFAUT = 'system-ui, sans-serif';

// Taille de la police en pixels écran : 11 px à ×1 (la bande d'en-tête fait 16 px), 13 à ×2, 15 à ×3, 16 au-delà.
export const taillePolice = (echelle) => Math.min(16, 9 + 2 * echelle);

// Nom tronqué par « … » pour tenir dans `largeur` pixels écran (mesure : ctx.measureText).
export function abregerNom(ctx, nom, largeur) {
  if (ctx.measureText(nom).width <= largeur) return nom;
  const lettres = [...nom];
  while (lettres.length > 1 && ctx.measureText(`${lettres.join('')}…`).width > largeur) lettres.pop();
  return `${lettres.join('')}…`;
}

// Pose le contexte pour écrire : repère en pixels CSS, police de la page à la taille de la vue.
function preparer(ctx, vue, d, police, couleur) {
  ctx.save();
  ctx.setTransform(d, 0, 0, d, 0, 0);
  ctx.font = `600 ${taillePolice(vue.echelle)}px ${police}`;
  ctx.textBaseline = 'middle';
  ctx.textAlign = 'left';
  ctx.fillStyle = couleur;
}

// Écrit les noms des pièces de `scene` sur `ctx` (le contexte du canvas d'affichage), pour la vue {echelle, x, y} ;
// d = pixels physiques par pixel CSS. Les coordonnées sont en pixels CSS.
export function ecrireNoms(ctx, scene, vue, { d = 1, police = POLICE_PAR_DEFAUT, couleur = '#2b2620' } = {}) {
  preparer(ctx, vue, d, police, couleur);
  for (const p of scene.pieces) {
    const z = p.nomZone;
    if (!z) continue;
    const x = vue.x + z.x * vue.echelle;
    const milieu = vue.y + (p.entete.y + p.entete.h / 2) * vue.echelle;
    ctx.fillText(abregerNom(ctx, p.libelle, z.w * vue.echelle), x, milieu + 0.5);
  }
  ctx.restore();
}

// Les compteurs écrits par la scène en police pixel (5×7) : « [dossiers] +N » dans l'en-tête d'une pièce (arrêtés repliés),
// « hors organigramme : N » dans le couloir, et le nombre posé sur la porte de l’utilisateur quand il doit agir. Même police que les
// noms, à la résolution de l'écran ; seul le chiffre de la porte garde sa couleur : ambre (l’utilisateur doit agir, une attente).
export function ecrireCompteurs(ctx, scene, vue, { d = 1, police = POLICE_PAR_DEFAUT, couleur = '#2b2620', ambre = COULEURS.ambre_texte } = {}) {
  const icone = ATLAS.sprites['compteur.dossiers'].w;
  const k = vue.echelle;
  // (x, y) : coin haut-gauche qu'aurait eu le texte en police pixel (7 px de haut) ; on l'écrit centré sur la même ligne.
  const ecrire = (texte, x, y, c) => {
    ctx.fillStyle = c;
    ctx.fillText(texte, vue.x + x * k, vue.y + (y + 3.5) * k + 0.5);
  };
  preparer(ctx, vue, d, police, couleur);
  for (const p of scene.pieces) if (p.compteur) ecrire(p.compteur.texte, p.compteur.x + icone + 2, p.compteur.y + 1, couleur);
  if (scene.horsOrganigramme) ecrire(scene.horsOrganigramme.texte, scene.horsOrganigramme.x + icone + 2, scene.horsOrganigramme.y + 1, couleur);
  if (scene.porte.etat === 'agir') ecrire(String(scene.porte.compteur), scene.porte.x - 12, scene.porte.y - 20, ambre);
  ctx.restore();
}
