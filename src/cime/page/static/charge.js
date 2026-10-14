// Cime — la charge de la machine : combien de workers tournent, sous quel plafond. Fonctions pures sur le champ `charge` de l'état ;
// l'affichage est dans vues/workers.js, l'action dans commun.js (`reglerPlafond`).

/** Le plafond par défaut de la machine, et les bornes du réglage. */
export const PLAFOND_DEFAUT = 3;
export const PLAFOND_MIN = 1;
export const PLAFOND_MAX = 8;

const entier = (v) => (Number.isInteger(v) && v >= 0 ? v : null);

/**
 * Le champ `charge`, lu sans rien inventer : un nombre absent ou illisible vaut null (jamais zéro).
 * { actifs, max, source, machine: { valeur, defaut, depuis, par } | null, projet, parProjet: [[nom, n]] | null }
 */
export function lireCharge(etat) {
  const c = etat && typeof etat === 'object' ? etat.charge : null;
  if (!c || typeof c !== 'object') return null;
  const m = c.machine && typeof c.machine === 'object' ? c.machine : null;
  const par = c.par_projet && typeof c.par_projet === 'object' && !Array.isArray(c.par_projet)
    ? Object.entries(c.par_projet).filter(([, n]) => entier(n) !== null) : null;
  return {
    actifs: entier(c.workers_actifs),
    max: entier(c.workers_max),
    source: c.source === 'projet' ? 'projet' : 'machine',
    machine: m && entier(m.valeur) !== null
      ? { valeur: m.valeur, defaut: m.source === 'defaut', depuis: typeof m.depuis === 'string' ? m.depuis : null, par: typeof m.par === 'string' && m.par ? m.par : null }
      : null,
    projet: entier(c.projet),
    parProjet: par && par.length ? par : null,
  };
}

/** « Workers : 5 actifs sur 4 », « Workers : 1 actif sur ? », « Workers : inconnu » : un nombre inconnu s'écrit « ? ». */
export function phraseWorkers(charge) {
  if (!charge || (charge.actifs === null && charge.max === null)) return 'Workers : inconnu';
  const a = charge.actifs === null ? '?' : charge.actifs;
  return `Workers : ${a} ${charge.actifs === 1 ? 'actif' : 'actifs'} sur ${charge.max === null ? '?' : charge.max}`;
}

/** Le plafond du projet n'est dit que s'il est plus bas que celui de la machine (c'est lui qui s'applique). */
export const projetPlusBas = (charge) => Boolean(charge && charge.source === 'projet' && charge.projet !== null);

/** La valeur à poser dans le choix : le plafond de la machine, « defaut » quand c'est le défaut, null quand on ne le sait pas. */
export function valeurChoisie(charge) {
  if (!charge || !charge.machine) return null;
  return charge.machine.defaut ? 'defaut' : String(charge.machine.valeur);
}

/** Les options du choix : 1 à 8, puis « par défaut (3) ». */
export function optionsPlafond() {
  const n = Array.from({ length: PLAFOND_MAX - PLAFOND_MIN + 1 }, (_, i) => ({ valeur: String(PLAFOND_MIN + i), libelle: String(PLAFOND_MIN + i) }));
  return [...n, { valeur: 'defaut', libelle: `par défaut (${PLAFOND_DEFAUT})` }];
}
