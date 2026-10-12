// source.js — interface des données de la scène. Une source expose :
//   abonner(cb, { surStatut })  — cb(etat, transitions, t, { reset }) à chaque instantané ; transitions = [{id, etat, de, a}]
//                  nouvelles depuis le précédent appel ; reset = true quand la source repart de zéro.
//                  surStatut(s) — une chaîne de statut de lecture (source directe seulement).
//   arreter()    — coupe les abonnements.
//   scenario     — true pour une source qui rejoue un scénario : elle date ses instantanés (t) ; sinon la scène les date.
//   avancerA(t)  — fait avancer une source qui rejoue un scénario (source rejouée, par exemple dans les tests) ; sans effet pour le direct.
// Source du direct : source-directe.js (l'hôte, lecture seule).
// Une source ne doit jamais écrire ni appeler un agent.

export const METHODES_SOURCE = Object.freeze(['abonner', 'arreter']);

export function sourceValide(source) {
  return METHODES_SOURCE.every((m) => typeof source?.[m] === 'function');
}
