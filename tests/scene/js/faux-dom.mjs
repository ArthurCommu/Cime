// faux-dom.mjs — le strict nécessaire d'un navigateur pour monter la scène sous node : un document, des canvas qui
// enregistrent leurs appels de dessin, un conteneur dont on fixe la taille, un temps d'image que le test avance.

class FauxContexte {
  constructor() {
    this.appels = [];
    this.couleursTexte = []; // fillStyle au moment de chaque fillText
    this.couleurs = []; // fillStyle au moment de chaque fillRect, dans le même ordre que les fillRect de appels
    this.imageSmoothingEnabled = true;
  }
  fillRect(...a) {
    this.appels.push(['fillRect', ...a]);
    this.couleurs.push(this.fillStyle);
  }
  clearRect(...a) {
    this.appels.push(['clearRect', ...a]);
  }
  drawImage(...a) {
    this.appels.push(['drawImage', ...a]);
  }
  save() {
    this.appels.push(['save']);
  }
  restore() {
    this.appels.push(['restore']);
  }
  setTransform(...a) {
    this.appels.push(['setTransform', ...a]);
  }
  // Largeur d'un texte : 6 px par lettre, quelle que soit la police (le test ne mesure pas une vraie police).
  measureText(texte) {
    return { width: [...texte].length * 6 };
  }
  fillText(...a) {
    this.appels.push(['fillText', ...a]);
    this.couleursTexte.push(this.fillStyle);
  }
}

export class FauxCanvas extends EventTarget {
  constructor(doc) {
    super();
    this.ownerDocument = doc;
    this.style = {};
    this.attributs = {};
    this.width = 300;
    this.height = 150;
    this.parent = null;
    this.ctx = new FauxContexte();
  }
  getContext() {
    return this.ctx;
  }
  setAttribute(k, v) {
    this.attributs[k] = v;
  }
  getBoundingClientRect() {
    return { left: 0, top: 0 };
  }
  remove() {
    if (this.parent) this.parent.enfants = this.parent.enfants.filter((e) => e !== this);
    this.parent = null;
  }
  // Dernière copie de l'étage à l'écran : [tampon, sx, sy, sw, sh, dx, dy, dw, dh].
  derniereCopie() {
    return this.ctx.appels.filter((a) => a[0] === 'drawImage').at(-1)?.slice(1) ?? null;
  }
}

export function fauxNavigateur({ w = 1888, h = 914, ratio = 1, positionConteneur = 'static' } = {}) {
  const rappels = new Map();
  let numero = 0;
  const fenetre = {
    devicePixelRatio: ratio,
    ResizeObserver: class {
      constructor(f) {
        this.f = f;
        fenetre.observateurs.push(this);
      }
      observe() {}
      disconnect() {
        this.coupe = true;
      }
    },
    observateurs: [],
    getComputedStyle: () => ({ position: positionConteneur }),
    requestAnimationFrame: (f) => {
      rappels.set(++numero, f);
      return numero;
    },
    cancelAnimationFrame: (id) => rappels.delete(id),
  };
  const canvases = []; // dans l'ordre de création : [canvas d'affichage, tampon de l'étage, images de sprites…]
  const doc = Object.assign(new EventTarget(), {
    visibilityState: 'visible',
    defaultView: fenetre,
    createElement: () => {
      const c = new FauxCanvas(doc);
      canvases.push(c);
      return c;
    },
  });
  const conteneur = Object.assign(new EventTarget(), {
    ownerDocument: doc,
    style: {},
    clientWidth: w,
    clientHeight: h,
    enfants: [],
    appendChild(c) {
      c.parent = this;
      this.enfants.push(c);
    },
  });
  let t = 1000;
  return {
    doc,
    fenetre,
    conteneur,
    canvases,
    imagesEnAttente: () => rappels.size,
    // Une image du navigateur, 16 ms après la précédente.
    image() {
      t += 16;
      const attendus = [...rappels];
      rappels.clear();
      for (const [, f] of attendus) f(t);
      return t;
    },
    redimensionner(nw, nh) {
      conteneur.clientWidth = nw;
      conteneur.clientHeight = nh;
      fenetre.observateurs.forEach((o) => o.f([{}]));
    },
  };
}

// Évènement avec des propriétés imposées.
export function evt(type, props = {}) {
  const e = new Event(type, { cancelable: true });
  for (const [k, v] of Object.entries(props)) Object.defineProperty(e, k, { value: v });
  return e;
}
