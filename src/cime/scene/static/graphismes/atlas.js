// L'atlas de la scène : toutes les images, en données pures.
//
// ATLAS.sprites["<nom>"] = { w, h, fps, boucle, pivot: [x, y], frames }
//   frames : tableau d'images ; une image = h chaînes de w caractères de PALETTE.
//   Champ facultatif `zone: [x, y, w, h]` : rectangle que le moteur remplit
//   (texte de panneau.equipe, barre de jauge.cadre).
// ATLAS.police : police bitmap 5×7 (voir police.js).
//
// Les images sont générées au chargement par les modules voisins (pas de DOM) ;
// le résultat est un objet complet, énumérable, figé.

import { spritesPersonnages } from "./personnages.js";
import { spritesDecor } from "./decor.js";
import { spritesObjets, halo } from "./objets.js";
import { sprite } from "./dessin.js";
import { POLICE } from "./police.js";

const base = { ...spritesPersonnages(), ...spritesDecor(), ...spritesObjets() };

// Composition d'un poste de travail, relative au pivot de meuble.bureau.
// Ordre de dessin : bureau, écran, perso (puis bulle, puis halo par-dessus).
export const MONTAGE = {
  ecran: [0, -16], // pivot de l'écran
  perso: [0, 5], // pivot du personnage (pied de la chaise)
  bulle: [5, -13], // bout de la queue d'une bulle : au-dessus de la tête, à droite
  halo: [0, 0], // pivot de alerte.halo (calé pour entourer le poste)
  // écran à poser selon l'animation ; toute autre animation : ecran.eteint
  ecranPourAnim: {
    taper: "ecran.texte",
    ecrire: "ecran.texte",
    lire: "ecran.lecture",
    executer: "ecran.terminal",
    reflechir: "ecran.pensee",
    attend_autorisation: "ecran.texte",
    attend_reponse: "ecran.texte",
  },
};

// Le halo entoure exactement le poste (bureau + écran + perso), 2 px de marge.
function bornesPoste() {
  const boites = [
    [base["meuble.bureau"], [0, 0]],
    [base["ecran.eteint"], MONTAGE.ecran],
    [base["perso.worker.idle"], MONTAGE.perso],
  ].map(([s, [ox, oy]]) => [ox - s.pivot[0], oy - s.pivot[1], ox - s.pivot[0] + s.w, oy - s.pivot[1] + s.h]);
  return [
    Math.min(...boites.map((b) => b[0])),
    Math.min(...boites.map((b) => b[1])),
    Math.max(...boites.map((b) => b[2])),
    Math.max(...boites.map((b) => b[3])),
  ];
}
const [x0, y0, x1, y1] = bornesPoste();
const MARGE = 2;
const haloSprite = sprite(halo(x1 - x0 + 2 * MARGE, y1 - y0 + 2 * MARGE), {
  fps: 4,
  pivot: [-x0 + MARGE, -y0 + MARGE],
});

// Le même halo en ambre : un agent qui attend (autorisation, réponse) n'est pas un problème.
const haloAttente = sprite(halo(x1 - x0 + 2 * MARGE, y1 - y0 + 2 * MARGE, "ambre"), {
  fps: 4,
  pivot: [-x0 + MARGE, -y0 + MARGE],
});

export const ATLAS = {
  tuile: 16,
  sprites: { ...base, "alerte.halo": haloSprite, "attente.halo": haloAttente },
  police: POLICE,
};
