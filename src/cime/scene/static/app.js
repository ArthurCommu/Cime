// app.js — page de développement de la scène (/scene/) : monte la scène dans un conteneur, comme le fait la page de Cime,
// avec le direct de l'hôte. Lecture seule : aucun stockage, aucune écriture.

import { creerSourceDirecte } from './source-directe.js';
import { monterScene, LEGENDE, dessinerIcone } from './scene.js';

const doc = document;
const portEl = doc.getElementById('port');
const legendeEl = doc.getElementById('legende');
const infoEl = doc.getElementById('infobulle');
const ouvertureEl = doc.getElementById('ouverture');
const statutEl = doc.getElementById('statut');

// Statut de la lecture du direct, affiché discrètement. « connecte » ne s'affiche pas.
const LIBELLES_STATUT = {
  connexion: 'connexion…',
  reconnexion: 'reconnexion…',
  'hote-injoignable': 'hôte injoignable : rien n’est affiché tant qu’il ne répond pas',
  'transitions-indisponibles': 'transitions indisponibles : les déplacements ne sont pas animés',
  'evenement-illisible': 'un événement illisible a été ignoré',
};
function afficherStatut(s) {
  const libelle = LIBELLES_STATUT[s];
  statutEl.textContent = libelle ?? '';
  statutEl.hidden = !libelle;
}

// Ce que la page ferait d'un clic : ici, seulement le dire.
const DECRIT_CIBLE = {
  equipe: (c) => `ouvrirait la fiche de l’équipe ${c.nom}`,
  agent: (c) => `ouvrirait la fiche de ${c.id}`,
  message: (c) => `ouvrirait le message ${c.id}`,
  utilisateur: () => 'ouvrirait « Ce qui t’attend »',
};

// La légende, comme la page la met en forme : les données de LEGENDE, une icône dessinée par signe.
function monterLegende() {
  const groupes = [...new Set(LEGENDE.map((e) => e.groupe))];
  for (const groupe of groupes) {
    const section = doc.createElement('section');
    const titre = doc.createElement('h2');
    titre.textContent = groupe;
    const liste = doc.createElement('ul');
    for (const e of LEGENDE.filter((x) => x.groupe === groupe)) {
      const li = doc.createElement('li');
      const icone = doc.createElement('canvas');
      icone.setAttribute('aria-hidden', 'true');
      dessinerIcone(icone, e.sprite);
      const libelle = doc.createElement('span');
      libelle.textContent = e.libelle;
      li.append(icone, libelle);
      liste.append(li);
    }
    section.append(titre, liste);
    legendeEl.append(section);
  }
}

async function demarrer() {
  const source = creerSourceDirecte();
  const style = getComputedStyle(doc.documentElement);

  monterLegende();
  const scene = monterScene(portEl, {
    source,
    theme: {
      fond: style.getPropertyValue('--fond').trim(),
      texte: style.getPropertyValue('--texte').trim(),
      police: getComputedStyle(doc.body).fontFamily,
    },
    surStatut: afficherStatut,
    // Comme la page : le clic nomme une cible, la page la montre et demande à la scène de l'entourer.
    surClic: (cible) => {
      ouvertureEl.hidden = false;
      ouvertureEl.textContent = DECRIT_CIBLE[cible.type](cible);
      scene.selectionner(cible);
    },
    surVide: () => {
      ouvertureEl.hidden = true;
      scene.selectionner(null);
    },
    surSurvol: (cible, info) => {
      infoEl.textContent = cible && info?.titre ? [info.titre, ...(info.lignes ?? [])].join(' — ') : '';
    },
  });
}

demarrer();
