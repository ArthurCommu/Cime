// boucle.js — boucle d'animation. Onglet caché : arrêt complet (aucune image demandée), reprise au retour.
// dt plafonné à 100 ms : un onglet resté longtemps caché ne rejoue pas le temps perdu.

const PLAFOND_DT_MS = 100;

export function creerBoucle({
  doc,
  rendre,
  planifier = (f) => globalThis.requestAnimationFrame(f),
  annuler = (id) => globalThis.cancelAnimationFrame(id),
}) {
  let id = null;
  let dernier = null;
  let actif = false;
  const visible = () => doc.visibilityState !== 'hidden';
  const mesure = { fps: 0, images: 0, fenetreDebut: null };

  function pas(t) {
    id = null;
    if (!actif || !visible()) return;
    const dt = dernier === null ? 0 : Math.min(t - dernier, PLAFOND_DT_MS);
    dernier = t;
    if (mesure.fenetreDebut === null) mesure.fenetreDebut = t;
    mesure.images += 1;
    if (t - mesure.fenetreDebut >= 1000) {
      mesure.fps = (mesure.images * 1000) / (t - mesure.fenetreDebut);
      mesure.images = 0;
      mesure.fenetreDebut = t;
    }
    rendre(t, dt);
    id = planifier(pas);
  }

  function auChangementDeVisibilite() {
    if (!visible()) {
      if (id !== null) annuler(id);
      id = null;
      dernier = null;
    } else if (actif && id === null) {
      dernier = null;
      id = planifier(pas);
    }
  }

  return {
    mesure,
    demarrer() {
      if (actif) return;
      actif = true;
      doc.addEventListener('visibilitychange', auChangementDeVisibilite);
      if (visible()) id = planifier(pas);
    },
    arreter() {
      actif = false;
      doc.removeEventListener('visibilitychange', auChangementDeVisibilite);
      if (id !== null) annuler(id);
      id = null;
    },
  };
}
