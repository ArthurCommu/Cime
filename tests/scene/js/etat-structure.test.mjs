// Instantané réel anonymisé (fixtures/etat-structure.json) : même structure que l'hôte, aucun texte libre.
// Les identifiants (agents, équipes, états, dates, nombres) sont gardés ; toute chaîne libre est vide ou null.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ICI = dirname(fileURLToPath(import.meta.url));
const FICHIER = join(ICI, '..', 'fixtures', 'etat-structure.json');
const etat = JSON.parse(readFileSync(FICHIER, 'utf8'));

// Clés dont la valeur chaîne est un identifiant, un état, une date ou un nom de type (pas du texte).
const IDENTIFIANTS = new Set([
  'id', 'role', 'equipe', 'parent', 'session_tmux', 'etat', 'etat_depuis', 'etat_source', 'modele', 'occupe_par',
  'de', 'a', 'nature', 'auteur', 'voie', 'attendu', 'branche', 'commit', 'statut', 'date', 'horodatage', 'depuis',
  'genere_a', 'battement', 'echeance', 'debiteur', 'type', 'gravite', 'agents', 'equipes', 'depend_de', 'verbe',
  'cible', 'message_id', 'prefixe', 'branche_reference', 'version', 'source', 'agent', 'cloturee_le', 'ok', 'arrete',
  'vivant', 'speciale', 'en_attente',
]);
// Champs de texte libre de l'hôte (phrases, résumés, objets, titres, chemins) : jamais une valeur non vide.
const TEXTE_LIBRE = [
  'resume', 'derniere_phrase', 'objet', 'titre', 'mesure', 'quoi_faire', 'mission', 'tache', 'brouillon', 'bloque',
  'erreur', 'fichier', 'racine', 'worktree', 'texte', 'fichiers_touches', 'perimetre_declare', 'hors_perimetre',
];

// Parcourt tout l'arbre : renvoie chaque chaîne avec la clé qui la porte et la clé de son conteneur.
function chaines(v, cle = '', contexte = '', acc = []) {
  if (typeof v === 'string') acc.push({ valeur: v, cle, contexte });
  else if (Array.isArray(v)) v.forEach((x) => chaines(x, cle, contexte, acc));
  else if (v && typeof v === 'object') for (const [k, c] of Object.entries(v)) chaines(c, k, cle, acc);
  return acc;
}

test('aucun champ de texte libre ne reste : chaque chaîne est vide ou un identifiant gardé', () => {
  const fuites = chaines(etat).filter(({ valeur, cle, contexte }) => {
    if (valeur === '') return false;
    if (IDENTIFIANTS.has(cle)) return false;
    if (cle === 'nom' && (contexte === 'equipes' || contexte === 'sources')) return false;
    return true;
  });
  assert.deepEqual(fuites, [], 'texte libre restant');
});

test('aucun champ texte connu de l’hôte ne porte une valeur', () => {
  const restes = chaines(etat).filter(({ cle, valeur }) => TEXTE_LIBRE.includes(cle) && valeur !== '');
  assert.deepEqual(restes, []);
});

test('aucun chemin personnel ni adresse dans le fichier', () => {
  const brut = readFileSync(FICHIER, 'utf8');
  assert.equal(/\/Users\//.test(brut), false, 'chemin utilisateur');
  assert.equal(/\/home\/|Projets/.test(brut), false, 'chemin du projet');
  assert.equal(/https?:\/\//.test(brut), false, 'adresse');
  assert.equal(/@/.test(brut), false, 'adresse de courriel');
});

test('même structure que l’hôte : 9 équipes, 42 agents (38 arrêtés), 200 requêtes, 8 alarmes', () => {
  assert.equal(etat.version, 2);
  assert.equal(etat.equipes.length, 9);
  const integration = etat.equipes.find((e) => e.nom === 'integration');
  assert.equal(integration.statut, null);
  assert.equal(etat.equipes.find((e) => e.nom === 'signaux').statut, 'terminee');
  assert.equal(etat.agents.length, 42);
  assert.equal(etat.agents.filter((a) => a.etat === 'arrete').length, 38);
  assert.equal(etat.flux.length, 200);
  assert.equal(etat.alarmes.length, 8);
});
