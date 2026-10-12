// atlas-factice.mjs — atlas de test : rectangles pleins aux bons noms et aux bonnes tailles.
// La liste des noms est écrite ici à la main (et non lue dans le code),
// pour que le test croisé « noms référencés ⊆ atlas » ait un sens.
// PALETTE_FACTICE mappe '#' (et 'o') vers une couleur ; toutes les images sont pleines.

const rect = (w, h, n = 1) => Array.from({ length: n }, () => Array.from({ length: h }, () => '#'.repeat(w)));

const PERSO_ANIMS = ['idle', 'taper', 'ecrire', 'lire', 'executer', 'reflechir', 'dormir', 'sieste', 'attend_autorisation', 'attend_reponse', 'arrete', 'inconnu', 'arrive', 'fin_tache'];
const PERSO_NONBOUCLE = new Set(['arrive', 'fin_tache']);

function sprite(w, h, { frames = 1, fps = 4, boucle = true, pivot = [0, 0] } = {}) {
  return { w, h, fps, boucle, pivot, frames: rect(w, h, frames) };
}

const sprites = {};
for (const role of ['assistant', 'coordinateur', 'worker']) {
  for (const anim of PERSO_ANIMS) {
    sprites[`perso.${role}.${anim}`] = sprite(8, 10, {
      frames: 2,
      boucle: !PERSO_NONBOUCLE.has(anim),
      pivot: [4, 9],
    });
  }
}
sprites['perso.utilisateur.idle'] = sprite(8, 10, { frames: 2, pivot: [4, 9] });
sprites['perso.utilisateur.inconnu'] = sprite(8, 10, { pivot: [4, 9] });
for (const d of ['marche_haut', 'marche_bas', 'marche_gauche', 'marche_droite']) {
  sprites[`perso.facteur.${d}`] = sprite(8, 10, { frames: 2, pivot: [4, 9] });
}
for (const a of ['idle', 'dormir', 'arrete']) sprites[`perso.facteur.${a}`] = sprite(8, 10, { pivot: [4, 9] });

for (const n of ['meuble.bureau', 'meuble.bureau_vide']) sprites[n] = sprite(16, 8);
sprites['meuble.chaise'] = sprite(8, 8);
for (const n of ['eteint', 'texte', 'lecture', 'terminal', 'pensee']) sprites[`ecran.${n}`] = sprite(8, 4);
sprites['sol.piece'] = sprite(16, 16);
sprites['sol.couloir'] = sprite(16, 16);
for (const n of ['mur.haut', 'mur.cote', 'mur.angle', 'porte.piece']) sprites[n] = sprite(16, 16);
for (const n of ['fermee', 'attente', 'agir']) sprites[`porte.utilisateur.${n}`] = sprite(16, 16);
sprites.plante = sprite(8, 8);
sprites['panneau.equipe'] = sprite(16, 8);
sprites['machine.cafe'] = sprite(8, 8);
for (const n of ['inscrit', 'livre', 'pris_en_compte', 'clos', 'echec', 'abandonne', 'echec_gris', 'abandonne_gris']) {
  sprites[`enveloppe.${n}`] = sprite(8, 6, { pivot: [4, 3] });
}
for (const n of ['exclamation', 'question', 'zzz', 'pensee', 'coche']) sprites[`bulle.${n}`] = sprite(8, 8);
for (const n of ['cout', 'contexte', 'inconnu']) sprites[`icone.${n}`] = sprite(8, 8);
sprites['compteur.dossiers'] = sprite(10, 9, { pivot: [0, 0] });
sprites['jauge.cadre'] = sprite(12, 3);
sprites['alerte.halo'] = sprite(16, 16, { frames: 2, pivot: [8, 8] });
sprites['alerte.refus_garde'] = sprite(8, 8, { boucle: false });
sprites['alerte.sirene'] = sprite(8, 8, { frames: 2 });
sprites['alerte.cause_inconnue'] = sprite(8, 8, { frames: 2 });
sprites['attente.halo'] = sprite(16, 16, { frames: 2, pivot: [8, 8] });
sprites['attente.sirene'] = sprite(8, 8, { frames: 2 });

// Police 5 × 7 : chaque glyphe est un bloc plein (les tests ne lisent pas la forme des lettres).
const CARACTERES = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789?.-:· ';
const glyphes = {};
for (const ch of CARACTERES) glyphes[ch] = ch === ' ' ? rect(5, 7)[0].map(() => '.....') : rect(5, 7)[0];

// Une couleur par famille, pour que le rendu reste lisible : perso, meuble, sol, porte, enveloppe, bulle, alerte, décor.
const FAMILLES = [
  [/^perso\./, 'p'],
  [/^(meuble|ecran)\./, 'm'],
  [/^(sol|mur)\./, 's'],
  [/^porte\./, 'd'],
  [/^enveloppe\./, 'e'],
  [/^(bulle|icone|jauge)\./, 'b'],
  [/^(alerte|attente)\./, 'a'],
];
for (const [nom, s] of Object.entries(sprites)) {
  const lettre = FAMILLES.find(([motif]) => motif.test(nom))?.[1] ?? 'o';
  s.frames = s.frames.map((ligne) => ligne.map((r) => r.replaceAll('#', lettre)));
}

export const ATLAS_FACTICE = Object.freeze({ tuile: 16, sprites, police: { w: 5, h: 7, glyphes } });
export const PALETTE_FACTICE = Object.freeze({
  p: '#3d6fd1', m: '#8b5a2b', s: '#b0b0b0', d: '#7a4f9a', e: '#ffffff', b: '#ffd23f', a: '#ff2d2d', o: '#2ea043',
});
export const NOMS_FACTICE = Object.freeze(Object.keys(sprites));
