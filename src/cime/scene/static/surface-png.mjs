// surface-png.mjs — Surface en mémoire (RGBA), pour les tests de rendu sans navigateur.
// Même interface que surface-canvas.js : rect, sprite, texte, taille.

function rgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export class SurfacePNG {
  constructor(largeur, hauteur, atlas, palette) {
    this.largeur = largeur;
    this.hauteur = hauteur;
    this.atlas = atlas;
    this.palette = palette;
    this.pixels = new Uint8Array(largeur * hauteur * 4);
    this.couleursPalette = new Map(); // caractère → [r, g, b], lu une fois
  }

  taille() {
    return { w: this.largeur, h: this.hauteur };
  }

  pixel(x, y, [r, g, b]) {
    if (x < 0 || y < 0 || x >= this.largeur || y >= this.hauteur) return;
    const i = (y * this.largeur + x) * 4;
    this.pixels[i] = r;
    this.pixels[i + 1] = g;
    this.pixels[i + 2] = b;
    this.pixels[i + 3] = 255;
  }

  rect(x, y, w, h, couleur) {
    const [r, g, b] = rgb(couleur);
    const x0 = Math.max(0, x);
    const x1 = Math.min(this.largeur, x + w);
    const px = this.pixels;
    for (let yy = Math.max(0, y); yy < Math.min(this.hauteur, y + h); yy++) {
      for (let i = (yy * this.largeur + x0) * 4, fin = (yy * this.largeur + x1) * 4; i < fin; i += 4) {
        px[i] = r;
        px[i + 1] = g;
        px[i + 2] = b;
        px[i + 3] = 255;
      }
    }
  }

  // Image décodée une fois : liste des pixels pleins [dx, dy, r, g, b] à plat.
  decoder(nom, frame, lignes) {
    const cle = `${nom}#${frame}`;
    let d = this.decodes?.get(cle);
    if (d) return d;
    const plein = [];
    lignes.forEach((ligne, r) => {
      for (let c = 0; c < ligne.length; c++) {
        const ch = ligne[c];
        if (ch === '.' || !this.palette[ch]) continue;
        if (!this.couleursPalette.has(ch)) this.couleursPalette.set(ch, rgb(this.palette[ch]));
        const [R, G, B] = this.couleursPalette.get(ch);
        plein.push(c, r, R, G, B);
      }
    });
    d = Int16Array.from(plein);
    (this.decodes ??= new Map()).set(cle, d);
    return d;
  }

  // Convention des sprites et des glyphes : '.' est transparent, tout autre caractère est une couleur de palette.
  sprite(nom, frame, x, y) {
    const s = this.atlas.sprites[nom];
    if (!s) return;
    const f = frame % s.frames.length;
    const d = this.decoder(nom, f, s.frames[f]);
    const px = this.pixels;
    const W = this.largeur;
    const H = this.hauteur;
    for (let k = 0; k < d.length; k += 5) {
      const xx = x + d[k];
      const yy = y + d[k + 1];
      if (xx < 0 || yy < 0 || xx >= W || yy >= H) continue;
      const i = (yy * W + xx) * 4;
      px[i] = d[k + 2];
      px[i + 1] = d[k + 3];
      px[i + 2] = d[k + 4];
      px[i + 3] = 255;
    }
  }

  // Un glyphe absent est sauté (le texte reste lisible pour les caractères connus).
  texte(chaine, x, y, couleur) {
    const { w, glyphes } = this.atlas.police;
    const c = rgb(couleur);
    let cx = x;
    for (const ch of chaine) {
      const g = glyphes[ch];
      if (g) {
        g.forEach((ligne, r) => {
          for (let k = 0; k < ligne.length; k++) if (ligne[k] !== '.') this.pixel(cx + k, y + r, c);
        });
      }
      cx += w + 1;
    }
  }

  // Les pixels RGBA, ligne après ligne.
  rgba() {
    return this.pixels;
  }
}
