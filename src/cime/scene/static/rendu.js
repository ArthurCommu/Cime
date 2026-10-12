// rendu.js — dessine une scène sur une Surface minimale : rect(x, y, w, h, couleur),
// sprite(nom, frame, x, y) (coin haut-gauche), texte(chaine, x, y, couleur), taille().
// Un sprite absent ne plante jamais : magenta, et scene.manques est incrémenté.
//
// ORDRE DE DESSIN (z, du fond vers l'avant) :
//   1. sols : fond, couloir, plancher de chaque pièce, puis sa bordure d'état (animation 24)
//   2. murs : façades et cloisons basses (mur.haut), cloisons verticales, portes, noms de pièce, décor (plante, cafetière)
//   3. bureaux et chaises
//   4. écrans, puis personnages (comme MONTAGE : bureau, écran, perso — la tête passe devant l'écran)
//   5. halos autour du poste des seuls agents nommés par une alarme grave : rouge (alerte.halo), ou ambre (attente.halo)
//      si l'alarme dit seulement qu'on attend ; sirènes de pièce : rouge au niveau grave, ambre (attente.sirene) sinon
//   6. jauges, coûts, bulles, marques
//   7. facteur, puis enveloppes (en vol ou en pile sur leur bureau) : jamais cachées derrière un bureau
//   8. alertes : sirènes (sur la cloison de la pièce), « ? » de cause inconnue (en-tête d'une pièce rouge sans cause
//      visible), éclairs de refus
//   9. le halo ambre des pièces où quelqu'un attend l’utilisateur (il pulse), puis le contour bleu de la cible que la page
//      a sélectionnée (selectionner, scene.js) : par-dessus tout le reste de l'étage
//  10. la légende : une bande sous l'étage (legende.js), dessinée avec les mêmes sprites, la même police
//  11. infobulle : HTML, hors du canvas (app.js)
//
// RÈGLE DU ROUGE : rouge = problème, et rien d'autre. Une pièce n'est rouge que si une alarme grave nomme son
// équipe ; une équipe « bloquee » (elle attend une réponse) a un cadre neutre, et le halo ambre dit si l’utilisateur est attendu.
// RÈGLE DE CAUSE VISIBLE : une pièce rouge montre sa cause dans la pièce — causeDePiece ; sinon un « ? » rouge dans l'en-tête
// (alerte.cause_inconnue, expliqué dans la légende) : la scène ne devine pas.

import { GEOM, abreger } from './plan.js';
import { MONTAGE } from './graphismes/atlas.js';
import { MISE_EN_PAGE, COUT_EXEMPLE } from './legende.js';
import { zoneDeCible } from './interaction.js';

export const COULEURS = Object.freeze({
  normal: '#2b2620', // texte et jauges sur le sol clair de l'atlas
  ambre: '#f2a33a',
  ambre_texte: '#9a5b00', // l'ambre, assez foncé pour se lire en texte sur le sol clair du couloir (le #f2a33a n'y fait que 1,6 : 1)
  rouge: '#e5383b',
  gris: '#8a93a6',
  fond: '#6d7491', // sous tout : si quelque chose manque, c'est un gris-bleu neutre, jamais du noir
  attente: '#d3d7e0', // pièce dont l'équipe attend une réponse : un cadre clair et neutre (ni rouge, ni ambre, ni gris de « terminée »)
  lumiere: '#58a89b', // pièce active : le vert « travaille » de la page ; l'ambre est réservé à « quelqu'un attend l’utilisateur »
  tamisee: '#4d5f86',
  hachure: '#8a7f66',
  sol_grise: '#a7adbd',
  mur_clair: '#5d6582',
  mur: '#3e4560',
  mur_sombre: '#2b2f45',
  porte_ouverte: '#ddd0b3',
});

const MAGENTA = '#ff00ff';
export const SELECTION = Object.freeze({ trait: '#8fb0d6', clair: '#a8c4e4', ombre: '#14161a' }); // le bleu de la page : information, sélection
export const PERIODE_HALO_MS = 2400; // le halo ambre pulse sur ce rythme
const AMBRE_SOMBRE = '#6b4a1c';
const AMBRE_PALE = '#f7c978';
const BORDURE_PIECE = {
  lumiere: COULEURS.lumiere,
  tamisee: COULEURS.tamisee,
  attend: COULEURS.attente,
  rouge: COULEURS.rouge,
  grisee: COULEURS.gris,
  hachuree: COULEURS.gris,
};
const BORD = 3; // épaisseur de la bordure d'état d'une pièce

// Ce qui explique, à l'écran, qu'une pièce est rouge. Rend 'attente' (un agent de la pièce attend, bulle visible),
// 'halo' (une alarme nomme un agent de la pièce : halo rouge), 'sirene' (sirène rouge de la pièce) ou 'inconnue'
// (rien ne l'explique : la scène le dit au lieu de le deviner) ; null si la pièce n'est pas rouge.
// Une pièce rouge parce qu'une alarme grave ne nomme que son équipe (raison 18) n'est expliquée que par sa sirène.
export function causeDePiece(piece, agents) {
  if (piece.neutre || piece.couleur !== 'rouge') return null;
  const dedans = agents.filter((a) => a.equipe === piece.nom && a.pivot);
  const parStatut = piece.raison !== 18;
  if (parStatut && dedans.some((a) => a.bulle === 'question' || a.bulle === 'exclamation')) return 'attente';
  if (parStatut && dedans.some((a) => a.halo === 'rouge')) return 'halo';
  if (piece.sirene === 'rouge') return 'sirene';
  return 'inconnue';
}

// Lumière, bordure et grisé d'une pièce : le plancher (pl) et son sol visible (s) — partagé avec la légende.
function peindreSol(surface, brut, T, statut, pl, s, neutre = false) {
  if (statut === 'grisee') {
    surface.rect(pl.x, pl.y, pl.w, pl.h, COULEURS.sol_grise); // sol éteint, sans motif
  } else {
    for (let y = pl.y; y < pl.y + pl.h; y += T) {
      for (let x = pl.x; x < pl.x + pl.w; x += T) brut('sol.piece', x, y);
    }
  }
  if (statut === 'tamisee') {
    for (let y = pl.y + 1; y < pl.y + pl.h; y += 2) surface.rect(pl.x, y, pl.w, 1, COULEURS.tamisee); // lumière baissée
  }
  if (statut === 'hachuree') {
    for (let y = pl.y + 2; y < pl.y + pl.h; y += 4) surface.rect(pl.x, y, pl.w, 1, COULEURS.hachure); // non mesuré
  }
  if (neutre) return; // l'Assistant et la salle de l’utilisateur n'ont pas de statut d'équipe
  const col = BORDURE_PIECE[statut];
  surface.rect(s.x, s.y, s.w, BORD, col);
  surface.rect(s.x, s.y + s.h - BORD, s.w, BORD, col);
  surface.rect(s.x, s.y, BORD, s.h, col);
  surface.rect(s.x + s.w - BORD, s.y, BORD, s.h, col);
}

// Petits signes à aplats, partagés entre l'agent (étage) et la légende.
const peindreMarque = (surface, x, y) => surface.rect(x, y, 3, 3, COULEURS.ambre);
const peindreBrouillon = (surface, x, y) => {
  for (let i = 0; i < 3; i++) surface.rect(x + i * 3, y, 1, 1, COULEURS.gris);
};
const COULEUR_JAUGE = { normale: COULEURS.normal, ambre: COULEURS.ambre };

// Mélange deux couleurs #rrggbb (k = 0 : a, k = 1 : b) : le halo pulse sans transparence, donc sur toute surface.
export function melanger(a, b, k) {
  const c = (x, i) => parseInt(x.slice(1 + 2 * i, 3 + 2 * i), 16);
  const hex = (i) => Math.round(c(a, i) + (c(b, i) - c(a, i)) * k).toString(16).padStart(2, '0');
  return `#${hex(0)}${hex(1)}${hex(2)}`;
}

// Un cadre de `e` pixels d'épaisseur, posé dans le rectangle r.
function cadre(surface, r, e, couleur) {
  surface.rect(r.x, r.y, r.w, e, couleur);
  surface.rect(r.x, r.y + r.h - e, r.w, e, couleur);
  surface.rect(r.x, r.y, e, r.h, couleur);
  surface.rect(r.x + r.w - e, r.y, e, r.h, couleur);
}

// Le halo ambre d'une pièce : un filet de 2 px au ras des murs et un second, plus clair, à l'intérieur. r : 0 → 1.
function peindreHalo(surface, zone, r) {
  cadre(surface, zone, 2, melanger(AMBRE_SOMBRE, COULEURS.ambre, 0.2 + 0.8 * r));
  cadre(surface, { x: zone.x + 2, y: zone.y + 2, w: zone.w - 4, h: zone.h - 4 }, 1, melanger(AMBRE_SOMBRE, AMBRE_PALE, r));
}

// options : noms (le nom de chaque pièce en police pixel ; faux quand la page l'écrit à la résolution de l'écran, noms.js),
// legende (bande sous l'étage), selection (cible nommée à la page, entourée en bleu), pulsation (le halo ambre
// pulse ; faux = fixe, pour qui préfère moins de mouvement).
export function dessiner(surface, atlas, scene, tempsMs = 0, { legende = true, selection = null, pulsation = true, noms = true } = {}) {
  scene.manques = 0;
  const sprites = atlas.sprites;
  const police = atlas.police;
  const T = atlas.tuile ?? 16;

  // Numéro d'image : un sprite qui boucle suit le temps global ; un sprite unique suit son âge.
  const image = (s, age) => {
    const n = s.frames.length;
    const fps = s.fps ?? 4;
    if (s.boucle === false) return Math.min(Math.floor((age * fps) / 1000), n - 1);
    return Math.floor((tempsMs * fps) / 1000) % n;
  };
  const manque = (x, y) => {
    scene.manques += 1;
    surface.rect(x - 4, y - 4, 8, 8, MAGENTA);
  };
  // Dessin par coin haut-gauche.
  const brut = (nom, x, y, age = 0) => {
    const s = sprites[nom];
    if (!s) return manque(x, y);
    surface.sprite(nom, image(s, age), x, y);
  };
  // Dessin par point d'ancrage (pivot du sprite).
  const ancre = (nom, x, y, age = 0) => {
    const s = sprites[nom];
    if (!s) return manque(x, y);
    const [px, py] = s.pivot ?? [0, 0];
    surface.sprite(nom, image(s, age), x - px, y - py);
  };

  const etage = scene.etage ?? { murs: [], cloisons: [], decors: [] };

  // 1. SOLS ---------------------------------------------------------------------------------------------
  surface.rect(0, 0, scene.largeur, scene.hauteurEtage ?? scene.hauteur, COULEURS.fond);

  // Les emplacements libres (reste d'une rangée trop courte) ont le sol d'un couloir, et rien d'autre.
  for (const c of [...scene.couloirs, ...(scene.videes ?? [])]) {
    for (let y = c.y; y < c.y + c.h; y += T) {
      for (let x = c.x; x < c.x + c.w; x += T) brut('sol.couloir', x, y);
    }
  }

  for (const p of scene.pieces) peindreSol(surface, brut, T, p.statut, p.plancher, p.sol, p.neutre);

  // 2. MURS ---------------------------------------------------------------------------------------------
  for (const m of etage.murs) brut(m.sprite, m.x, m.y);
  for (const k of etage.cloisons) {
    if (k.type === 'milieu') {
      surface.rect(k.x, k.y, 1, k.h, COULEURS.mur_clair);
      surface.rect(k.x + 1, k.y, 4, k.h, COULEURS.mur);
      surface.rect(k.x + 5, k.y, 1, k.h, COULEURS.mur_sombre);
    } else if (k.type === 'gauche') {
      surface.rect(k.x, k.y, 2, k.h, COULEURS.mur);
      surface.rect(k.x + 2, k.y, 1, k.h, COULEURS.mur_sombre);
    } else {
      surface.rect(k.x, k.y, 1, k.h, COULEURS.mur_sombre);
      surface.rect(k.x + 1, k.y, 2, k.h, COULEURS.mur);
    }
  }
  const hEtage = scene.hauteurEtage ?? scene.hauteur;
  surface.rect(0, hEtage - 3, scene.largeur, 3, COULEURS.mur_sombre);

  for (const p of scene.pieces) {
    if (p.porteSprite) {
      const { x, y } = p.porteSprite;
      if (p.statut === 'grisee') brut('porte.piece', x, y); // pièce terminée : porte fermée
      else {
        surface.rect(x, y, 16, 16, COULEURS.mur_sombre); // porte ouverte : l'embrasure laisse voir le sol
        surface.rect(x + 2, y + 3, 12, 13, COULEURS.porte_ouverte);
      }
    }
    // Nom de la pièce : sur la bande d'en-tête (mur clair), écrit entier ou abrégé par « … ».
    const z = p.nomZone;
    if (noms) surface.texte(abreger(police, p.libelle, z.w), z.x, z.y, COULEURS.normal);
    // Arrêtés repliés : « [dossiers] +N », encre normale (lisible ; le gris est réservé au « non mesuré »), jamais rouge
    if (p.compteur) {
      brut('compteur.dossiers', p.compteur.x, p.compteur.y);
      if (noms) surface.texte(p.compteur.texte, p.compteur.x + sprites['compteur.dossiers'].w + 2, p.compteur.y + 1, COULEURS.normal);
    }
  }
  // Hors organigramme : un compteur dans le couloir de la bande 0 (« N+? » si les sessions sont inconnues)
  if (scene.horsOrganigramme) {
    const h = scene.horsOrganigramme;
    brut('compteur.dossiers', h.x, h.y);
    if (noms) surface.texte(h.texte, h.x + sprites['compteur.dossiers'].w + 2, h.y + 1, COULEURS.normal);
  }
  for (const d of etage.decors) ancre(d.sprite, d.x, d.y);

  const porte = scene.porte;
  const etatPorte = porte.etat === 'inconnue' ? 'fermee' : porte.etat;
  ancre(`porte.utilisateur.${etatPorte}`, porte.x, porte.y);
  if (porte.etat === 'inconnue') surface.texte('?', porte.x - 4, porte.y - 20, COULEURS.gris);
  if (porte.etat === 'agir' && noms) surface.texte(String(porte.compteur), porte.x - 12, porte.y - 20, COULEURS.ambre_texte);

  // 3. BUREAUX ET CHAISES -------------------------------------------------------------------------------
  for (const a of scene.agents) {
    const b = a.bureauRect;
    if (!b) continue;
    brut(a.bureau === 'vide' ? 'meuble.bureau_vide' : 'meuble.bureau', b.x, b.y);
    ancre('meuble.chaise', a.pivot.x + MONTAGE.perso[0], a.pivot.y + MONTAGE.perso[1]);
  }

  // 4. ÉCRANS PUIS PERSONNAGES (l’utilisateur est dans sa pièce, derrière sa porte) ----------------------------
  for (const a of scene.agents) {
    if (a.pivot && a.ecran) ancre(a.ecran, a.pivot.x + MONTAGE.ecran[0], a.pivot.y + MONTAGE.ecran[1]);
  }
  for (const a of [...scene.agents].sort((p, q) => p.y - q.y)) {
    if (a.sprite) ancre(a.sprite, a.x, a.y, a.age);
  }

  // 5. HALOS : centrés sur le poste de l'agent concerné, seulement lui -----------------------------------
  for (const a of scene.agents) {
    if (a.pivot && a.halo) ancre(a.halo === 'rouge' ? 'alerte.halo' : 'attente.halo', a.pivot.x + MONTAGE.halo[0], a.pivot.y + MONTAGE.halo[1]);
  }

  // 6. JAUGES, COÛTS, BULLES ----------------------------------------------------------------------------
  const { BANDE } = GEOM;
  for (const a of scene.agents) {
    if (!a.pivot) continue;
    const { x: px, y: py } = a.pivot;
    if (a.marque) peindreMarque(surface, px + 12, py - 14);
    if (a.brouillon) peindreBrouillon(surface, px + 6, py - 22);
    if (a.bulle) ancre(`bulle.${a.bulle}`, px + MONTAGE.bulle[0], py + MONTAGE.bulle[1]);
    if (a.jauge) {
      const jx = px + BANDE.jauge.x;
      const jy = py + BANDE.jauge.y;
      brut('jauge.cadre', jx, jy);
      if (a.jauge.inconnu) surface.texte('?', px + BANDE.point.x, py + BANDE.point.y, COULEURS.gris);
      else surface.rect(jx + 1, jy + 1, Math.round(30 * a.jauge.niveau), 3, COULEURS[a.jauge.couleur]);
    }
    if (a.cout) {
      let texte = a.cout.texte;
      const ic = sprites['icone.cout'];
      const place = BANDE.cout.largeur - (ic ? ic.w : 11) - 1;
      if (abreger(police, texte, place) !== texte) texte = String(Math.round(Number(texte)));
      const x0 = px + BANDE.cout.x;
      const y0 = py + BANDE.cout.y;
      brut('icone.cout', x0, y0);
      surface.texte(texte, x0 + (ic ? ic.w : 11) + 1, y0 + 2, COULEURS[a.cout.couleur]);
    }
  }

  // 7. FACTEUR PUIS ENVELOPPES ---------------------------------------------------------------------------
  const f = scene.facteur;
  ancre(f.sprite, f.x, f.y, f.age);
  for (const e of scene.enveloppes) ancre(e.sprite, e.x, e.y, e.age);

  // 8. ALERTES : une sirène par pièce concernée, sur sa cloison ; éclairs de refus -----------------------
  for (const p of scene.pieces) {
    if (p.sirene) ancre(p.sirene === 'rouge' ? 'alerte.sirene' : 'attente.sirene', p.sireneAncre.x, p.sireneAncre.y);
  }
  for (const p of scene.pieces) {
    if (causeDePiece(p, scene.agents) === 'inconnue') brut('alerte.cause_inconnue', p.causeAncre.x, p.causeAncre.y);
  }
  for (const a of scene.agents) {
    if (a.pivot && a.alerte) ancre('alerte.refus_garde', a.pivot.x + GEOM.REFUS[0], a.pivot.y + GEOM.REFUS[1], a.age);
  }

  // 9. HALO AMBRE ET SÉLECTION : par-dessus l'étage ------------------------------------------------------
  // Ambre = quelqu'un attend l’utilisateur (jamais un problème : le rouge reste aux alarmes). Deux filets qui respirent.
  const respiration = pulsation ? 0.5 - 0.5 * Math.cos((2 * Math.PI * tempsMs) / PERIODE_HALO_MS) : 1;
  for (const p of scene.pieces) {
    if (!p.attentes) continue;
    peindreHalo(surface, p, respiration);
  }
  const cible = zoneDeCible(scene, selection);
  if (cible) {
    const marge = cible.nom === undefined ? 2 : 0; // une pièce est entourée au ras de ses murs ; un agent ou une enveloppe, un cran dehors
    const r = { x: cible.x - marge, y: cible.y - marge, w: cible.w + 2 * marge, h: cible.h + 2 * marge };
    cadre(surface, { x: r.x - 1, y: r.y - 1, w: r.w + 2, h: r.h + 2 }, 1, SELECTION.ombre);
    cadre(surface, r, 2, SELECTION.trait);
    cadre(surface, { x: r.x + 2, y: r.y + 2, w: r.w - 4, h: r.h - 4 }, 1, SELECTION.clair); // second filet, clair, en dedans : lisible même à ×1
  }

  // 10. LÉGENDE ------------------------------------------------------------------------------------------
  if (legende && scene.legende) dessinerLegende(surface, atlas, scene.legende, scene.largeur, (s) => image(s, 0));

  return scene.manques;
}

// La légende : une bande sous l'étage. Mêmes sprites, même police ; le rouge n'y est que sur les signes de problème.
function dessinerLegende(surface, atlas, legende, largeur, image) {
  surface.rect(0, legende.y, largeur, legende.h, COULEURS.porte_ouverte);
  surface.rect(0, legende.y, largeur, MISE_EN_PAGE.BANDE_MUR, COULEURS.mur_sombre);
  for (const t of legende.titres) {
    surface.texte(t.texte, t.x, t.y, COULEURS.normal);
    surface.rect(t.trait.x, t.trait.y, t.trait.w, 1, COULEURS.mur_clair);
  }
  for (const c of legende.cellules) {
    dessinerSigne(surface, atlas, c.signe, c.signe.x, c.signe.y, image);
    for (const l of c.libelle) surface.texte(l.texte, l.x, l.y, COULEURS.normal);
  }
}

// Un signe de la légende (legende.js, composer) posé par son coin haut-gauche : ses sprites, ses motifs. Première image.
// Sert la bande de légende et les icônes que la page dessine (scene.js, dessinerIcone).
// image(sprite) → numéro d'image à poser (la légende anime comme la scène ; une icône reste sur la première).
export function dessinerSigne(surface, atlas, signe, x0, y0, image = () => 0) {
  const T = atlas.tuile ?? 16;
  const brut = (nom, x, y) => {
    const s = atlas.sprites[nom];
    if (s) surface.sprite(nom, image(s), x, y);
  };
  for (const e of signe.elements) {
    if (e.sprite) brut(e.sprite, x0 + e.x, y0 + e.y);
    else peindreMotif(surface, brut, T, e.motif, x0 + e.x, y0 + e.y);
  }
}

function peindreMotif(surface, brut, T, motif, x, y) {
  if (motif.startsWith('bordure.')) {
    const zone = { x, y, w: T, h: T };
    peindreSol(surface, brut, T, motif.slice('bordure.'.length), zone, zone);
  } else if (motif === 'halo.attente') {
    // Le halo d'une pièce où quelqu'un attend l’utilisateur, figé à mi-respiration : un sol, deux filets ambre.
    brut('sol.piece', x, y);
    peindreHalo(surface, { x, y, w: T, h: T }, 0.5);
  } else if (motif.startsWith('jauge.')) {
    brut('jauge.cadre', x, y);
    const v = motif.slice('jauge.'.length);
    if (v === 'inconnue') surface.texte('?', x + 33, y - 1, COULEURS.gris);
    else surface.rect(x + 1, y + 1, v === 'ambre' ? 24 : 12, 3, COULEUR_JAUGE[v]);
  } else if (motif === 'cout') {
    brut('icone.cout', x, y);
    surface.texte(COUT_EXEMPLE, x + 12, y + 2, COULEURS.normal);
  } else if (motif === 'cout.inconnu') {
    brut('icone.cout', x, y);
    surface.texte('?', x + 12, y + 2, COULEURS.gris);
  } else if (motif === 'marque') {
    peindreMarque(surface, x, y);
  } else if (motif === 'brouillon') {
    peindreBrouillon(surface, x, y);
  }
}
