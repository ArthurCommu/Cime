// surface-canvas.js — Surface Canvas 2D. Dessin à la taille logique sur un canvas hors écran,
// puis copie à l'échelle entière (imageSmoothingEnabled = false ; CSS image-rendering: pixelated).

export class SurfaceCanvas {
  constructor(doc, atlas, palette) {
    this.doc = doc;
    this.atlas = atlas;
    this.palette = palette;
    this.tampon = doc.createElement('canvas');
    this.ctx = this.tampon.getContext('2d');
    this.ctx.imageSmoothingEnabled = false;
    this.images = new Map(); // nom#frame → canvas ; glyphe#couleur → canvas
    this.largeur = 0;
    this.hauteur = 0;
  }

  dimensionner(largeur, hauteur) {
    this.largeur = largeur;
    this.hauteur = hauteur;
    this.tampon.width = largeur;
    this.tampon.height = hauteur;
    this.ctx.imageSmoothingEnabled = false;
  }

  taille() {
    return { w: this.largeur, h: this.hauteur };
  }

  rect(x, y, w, h, couleur) {
    this.ctx.fillStyle = couleur;
    this.ctx.fillRect(x, y, w, h);
  }

  sprite(nom, frame, x, y) {
    const s = this.atlas.sprites[nom];
    if (!s) return;
    const cle = `${nom}#${frame}`;
    if (!this.images.has(cle)) {
      this.images.set(cle, this.pixelsVersImage(s.frames[frame % s.frames.length], null));
    }
    this.ctx.drawImage(this.images.get(cle), x, y);
  }

  texte(chaine, x, y, couleur) {
    const { w, glyphes } = this.atlas.police;
    let cx = x;
    for (const ch of chaine) {
      const g = glyphes[ch];
      if (g) {
        const cle = `${ch}#${couleur}`;
        if (!this.images.has(cle)) this.images.set(cle, this.pixelsVersImage(g, couleur));
        this.ctx.drawImage(this.images.get(cle), cx, y);
      }
      cx += w + 1;
    }
  }

  // couleur == null : les caractères du sprite donnent leur couleur de palette ; sinon tout pixel plein prend couleur.
  pixelsVersImage(lignes, couleur) {
    const h = lignes.length;
    const w = lignes[0]?.length ?? 0;
    const c = this.doc.createElement('canvas');
    c.width = w;
    c.height = h;
    const ctx = c.getContext('2d');
    lignes.forEach((ligne, r) => {
      for (let k = 0; k < ligne.length; k++) {
        const ch = ligne[k];
        if (ch === '.') continue;
        const col = couleur ?? this.palette[ch];
        if (!col) continue;
        ctx.fillStyle = col;
        ctx.fillRect(k, r, 1, 1);
      }
    });
    return c;
  }

  // Canvas d'affichage de w × h pixels CSS, avec d pixels physiques par pixel CSS (d entier : pas de flou).
  dimensionnerEcran(ecran, w, h, d) {
    if (ecran.width !== w * d) ecran.width = w * d;
    if (ecran.height !== h * d) ecran.height = h * d;
    ecran.style.width = `${w}px`;
    ecran.style.height = `${h}px`;
  }

  // Copie la bande [sy, sy + sh) du tampon à l'échelle entière k, décalée de (x, y) pixels CSS, dans l'écran.
  // Le canvas découpe ce qui dépasse. Pixels physiques : × d.
  presenter(ecran, { k, x = 0, y = 0, d = 1, sy = 0, sh = this.hauteur }) {
    const ctx = ecran.getContext('2d');
    ctx.imageSmoothingEnabled = false;
    ctx.clearRect(0, 0, ecran.width, ecran.height);
    ctx.drawImage(this.tampon, 0, sy, this.largeur, sh, x * d, y * d, this.largeur * k * d, sh * k * d);
  }
}
