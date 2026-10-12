// Cime — le mode autonome : données et fonctions pures (aucun DOM, aucun import).
//
// Le mode autonome pilote aujourd'hui le champ `fusions_auto` de l'état et la route `/api/actions/fusions-auto` ;
// il sera étendu (autorisations, créations d'équipe). Ce que l'Assistant décide à la place de l'utilisateur (`DECIDE`) et ce qui reste à
// l'utilisateur (`THEMES`, `HORS_CHEMINS`) sont donc des tables de données : une extension y ajoute des lignes, le rendu n'est pas réécrit.

/** Ce que l'Assistant décide à la place de l'utilisateur quand le mode est actif : des fins de phrase, après « l'Assistant ». */
export const DECIDE = ['fusionne à ta place'];

/** Ce qui reste à l'utilisateur sans qu'aucun chemin ne le dise, deux formes : la phrase complète et la forme courte de la ligne d'état. */
export const HORS_CHEMINS = { complet: 'push, suppression de branche', court: 'push et branches' };

/**
 * Les thèmes des chemins réservés, dans l'ordre où l'hôte les liste. `court` : le mot de la ligne repliée ; `phrase` : le mot de la
 * phrase affichée mode inactif ; `motifs` : les entrées de la liste que le thème reconnaît (l'entrée entière, jamais un préfixe).
 * Une entrée qu'aucun thème ne reconnaît est un chemin propre au projet : la page ne connaît aucun dossier d'un projet donné.
 */
export const THEMES = [
  {
    cle: 'architecture', titre: 'Architecture et contrats', court: 'architecture', phrase: 'architecture et contrats',
    motifs: [
      /^\.orga\/(contracts|socle|produit)\/?$/, /^\.orga\/(projet\.toml|org-chart\.md|dependencies\.md)$/,
      /^CLAUDE\.md$/, /^\.orga\/teams\/(\*|[^/]+)\/(CLAUDE|mandate)\.md$/,
    ],
  },
  {
    cle: 'fondation', titre: 'Fondation : registre, garde, hooks', court: 'fondation', phrase: 'fondation',
    motifs: [/^\.orga\/etat\/?$/, /^\.claude\/?$/],
  },
  { cle: 'droits', titre: 'Droits', court: 'droits', phrase: 'droits', motifs: [/^\.orga\/etat\/reglages\/?$/] },
  {
    cle: 'reseau', titre: 'Réseau et dépendances', court: 'réseau', phrase: 'réseau',
    motifs: [
      /^(pyproject\.toml|uv\.lock|package\.json|package-lock\.json|pnpm-lock\.yaml|yarn\.lock|Cargo\.toml|Cargo\.lock|go\.mod|go\.sum)$/,
      /^(requirements\*\.txt|Pipfile\*|\.github\/?|\.gitmodules)$/,
    ],
  },
  {
    cle: 'secrets', titre: 'Secrets', court: 'secrets', phrase: 'secrets',
    motifs: [/^(\*\*\/)?(\.env|\.env\.\*|\*\.pem|\*\.key|id_rsa\*|id_ed25519\*|\.netrc|credentials\*)$/],
  },
];

/** Au-delà de ce nombre de chemins, un thème s'abrège par « … » (tout est visible au clic). */
export const MAX_CHEMINS_PAR_THEME = 5;

export const LIBELLE_PROJET = 'propres au projet';
/** Le thème « propres au projet » dans la phrase de repli : un élément de l'énumération, entre les thèmes du noyau et ce qui est hors chemins. */
export const PHRASE_PROJET = 'les chemins propres au projet';

/** « Mode autonome » : le libellé unique, écrit à gauche de la piste. */
export const LIBELLE_MODE = 'Mode autonome';
export const LIBELLE_ENCOURS = { active: 'Activation…', inactive: 'Désactivation…' };

/** Les phrases des toasts (pas de confirmation, un seul mot du résultat). */
export const TOASTS = {
  active: `Mode autonome activé : l’Assistant ${DECIDE.join(' et ')}, hors chemins réservés.`,
  inactive: 'Mode autonome désactivé : chaque fusion revient à ton accord.',
};

/**
 * Ce que l'Assistant a décidé à la place de l'utilisateur, par genre (`fusions_auto.decisions[].genre`) : le compte au singulier et au pluriel, et le verbe de la
 * ligne détaillée. Une ligne par genre, dans l'ordre d'affichage ; un genre que la table ne connaît pas s'écrit tel quel.
 */
export const GENRES_DECISION = [
  { genre: 'fusion', un: 'fusion', plusieurs: 'fusions', verbe: 'fusionnée' },
  { genre: 'chantier', un: 'chantier lancé', plusieurs: 'chantiers lancés', verbe: 'lancé' },
  { genre: 'contrat', un: 'contrat modifié', plusieurs: 'contrats modifiés', verbe: 'modifié' },
  { genre: 'autorisation', un: 'autorisation accordée', plusieurs: 'autorisations accordées', verbe: 'accordée' },
];

/** Au plus autant de décisions que l'hôte en envoie, et autant de lignes visibles avant « … et n autres ». */
export const MAX_DECISIONS = 50;
export const DECISIONS_VISIBLES = 10;
export const PHRASE_RECAP = 'L’Assistant a décidé à ta place';
export const LIBELLE_DECISIONS = 'Voir les décisions';
/** Le résumé du détail dans la Scène : il déplie la liste sur place, sans changer de page. */
export const LIBELLE_DETAIL_RECAP = 'Voir le détail';

/** Le champ `fusions_auto` de l'état, lu : absent ou illisible = inactif. */
export function lireMode(etat) {
  const f = etat && typeof etat === 'object' ? etat.fusions_auto : null;
  const lecture = f && typeof f === 'object' ? f : {};
  const actif = lecture.active === true;
  const liste = (v) => (Array.isArray(v) ? v.filter((c) => typeof c === 'string' && c) : null);
  const nombre = (v) => (typeof v === 'number' && Number.isFinite(v) && v >= 0 ? v : null);
  return {
    etat: !actif ? 'inactif' : lecture.suspendue === true ? 'suspendu' : 'actif',
    depuis: typeof lecture.depuis === 'string' ? lecture.depuis : null,
    par: typeof lecture.par === 'string' && lecture.par ? lecture.par : null,
    reserves: liste(lecture.reserves),
    proposees: liste(lecture.reserves_proposees),
    derniere: lecture.derniere_fusion && typeof lecture.derniere_fusion === 'object' ? lecture.derniere_fusion : null,
    // lus tels quels (la page ne calcule rien) : absents d'un vieil hôte ou mode inactif = vides
    portee: actif ? nombre(lecture.portee) : null,
    chantiers_24h: actif ? nombre(lecture.chantiers_24h) ?? 0 : 0,
    chantiers_max: actif ? nombre(lecture.chantiers_max) : null,
    decisions: actif ? lireDecisions(lecture.decisions) : [],
  };
}

/** Les décisions bien formées (genre écrit, clé écrite, horodatage lisible), dans l'ordre reçu, 50 au plus ; les autres sont écartées. */
function lireDecisions(v) {
  if (!Array.isArray(v)) return [];
  return v.filter((d) => d && typeof d === 'object' && typeof d.genre === 'string' && d.genre && typeof d.cle === 'string' && d.cle
    && typeof d.horodatage === 'string' && !Number.isNaN(Date.parse(d.horodatage)))
    .map((d) => ({ genre: d.genre, cle: d.cle, horodatage: d.horodatage, message: Number.isFinite(d.message) ? d.message : null }))
    .slice(0, MAX_DECISIONS);
}

/** Les décisions à dire : celles d'après la dernière visite ; sans visite mémorisée sur ce navigateur, toutes (c'est le matin). */
export const decisionsAVoir = (decisions, visite, memorisee) => (memorisee ? decisions.filter((d) => Date.parse(d.horodatage) > visite) : decisions);

/** Les comptes par genre, dans l'ordre de la table puis les genres inconnus dans l'ordre d'apparition ; un genre à 0 n'y est pas. */
export function comptesDecisions(decisions) {
  const genres = [...GENRES_DECISION.map((g) => g.genre), ...new Set(decisions.map((d) => d.genre))];
  return [...new Set(genres)].map((genre) => ({ genre, n: decisions.filter((d) => d.genre === genre).length }))
    .filter((c) => c.n > 0)
    .map((c) => {
      const ligne = GENRES_DECISION.find((g) => g.genre === c.genre);
      return { ...c, texte: `${c.n} ${ligne ? (c.n === 1 ? ligne.un : ligne.plusieurs) : c.genre}` };
    });
}

/** Le récap en une ligne (les comptes par genre, séparés par « · ») : le même texte dans « Depuis ta dernière visite » et dans le rail de la Scène. */
export const resumeDecisions = (decisions) => comptesDecisions(decisions).map((c) => c.texte).join(' · ');

/** Le mot d'une ligne détaillée : le verbe de la table, ou le genre tel quel. */
export const verbeDecision = (genre) => (GENRES_DECISION.find((g) => g.genre === genre) || { verbe: genre }).verbe;

/**
 * La liste de chemins à montrer, ou null quand on n'en connaît pas (la page n'invente alors aucun nombre : elle montre les thèmes
 * du noyau, les chemins propres au projet et ce qui est hors chemins, dans une phrase de repli). Actif : la liste enregistrée à l'activation ; suspendu ou inactif : celle
 * qu'une activation enregistrerait maintenant (`reserves_proposees`).
 */
export function listeVisible(mode) {
  const choix = mode.etat === 'actif' ? mode.reserves : mode.proposees;
  return choix && choix.length ? [...new Set(choix)] : null;
}

/** Le thème (clé) d'un chemin de la liste : celui dont un motif reconnaît l'entrée, sinon `projet`. */
export function themeDe(chemin) {
  const theme = THEMES.find((t) => t.motifs.some((m) => m.test(chemin)));
  return theme ? theme.cle : 'projet';
}

/**
 * Les chemins regroupés par thème, dans l'ordre des THEMES, puis les chemins propres au projet ; un thème sans chemin n'y est pas.
 * `chemins` null (liste inconnue) : les thèmes du noyau, sans chemins (`chemins: null`).
 */
export function regrouperReserves(chemins, nomProjet = null) {
  if (chemins === null) return THEMES.map((t) => ({ cle: t.cle, titre: t.titre, court: t.court, chemins: null }));
  const groupes = [...THEMES.map((t) => ({ cle: t.cle, titre: t.titre, court: t.court, chemins: [] })),
    { cle: 'projet', titre: nomProjet ? `Propres à ${nomProjet}` : 'Propres au projet', court: nomProjet ? `propres à ${nomProjet}` : LIBELLE_PROJET, chemins: [] }];
  for (const c of chemins) {
    const groupe = groupes.find((g) => g.cle === themeDe(c));
    groupe.chemins = [...groupe.chemins, c];
  }
  return groupes.filter((g) => g.chemins.length > 0);
}

/** Les chemins montrés d'un thème : les 5 premiers et « … » au-delà, sauf `tout`. */
export function cheminsMontres(chemins, tout) {
  const abrege = !tout && chemins.length > MAX_CHEMINS_PAR_THEME;
  return { montres: abrege ? chemins.slice(0, MAX_CHEMINS_PAR_THEME) : chemins, abrege, reste: abrege ? chemins.length - MAX_CHEMINS_PAR_THEME : 0 };
}

/**
 * La phrase de repli, d'un seul tenant, quand la liste est inconnue (aucun nombre) : les thèmes du noyau, les chemins propres au
 * projet, puis ce qui est hors chemins. Elle se construit sur les tables THEMES et HORS_CHEMINS.
 */
export const phraseRepli = () => `Restent à toi : ${[...THEMES.map((t) => t.phrase), PHRASE_PROJET, HORS_CHEMINS.court].join(', ')}.`;

/** La ligne repliée : « Restent à toi : architecture, fondation, droits, réseau, secrets · 44 chemins » (liste inconnue : la phrase de repli). */
export function ligneReserves(groupes, total) {
  const mots = groupes.map((g) => g.court).join(', ');
  if (total === null) return phraseRepli();
  return `Restent à toi : ${mots} · ${total} ${total === 1 ? 'chemin' : 'chemins'}`;
}

/**
 * La phrase de l'état inactif : ce que le clic ferait, et ce qui reste à l'utilisateur. Elle s'allonge avec DECIDE et THEMES. `connue` faux
 * (liste inconnue) : la fin est la phrase de repli, d'un seul tenant.
 */
export function phraseInactif(connue = true) {
  const reste = connue ? `Restent à toi : ${[...THEMES.map((t) => t.phrase), HORS_CHEMINS.court].join(', ')}.` : phraseRepli();
  return `Activé, l’Assistant ${DECIDE.join(' et ')}. ${reste}`;
}

/** « 23 h 10 », « 7 h » : l'heure locale d'un horodatage ISO ; null s'il est illisible. */
export function heureCourte(iso) {
  const d = new Date(iso);
  if (!iso || Number.isNaN(d.getTime())) return null;
  const m = d.getMinutes();
  return m ? `${d.getHours()} h ${String(m).padStart(2, '0')}` : `${d.getHours()} h`;
}

/** La dernière action du mode, pour l'encadré actif : { equipe, sha (7 caractères), horodatage } ou null (« aucune … encore »). */
export function derniereAction(mode) {
  const d = mode.derniere;
  if (!d) return null;
  return { equipe: typeof d.equipe === 'string' ? d.equipe : null, sha: typeof d.sha === 'string' ? d.sha.slice(0, 7) : null,
    horodatage: typeof d.horodatage === 'string' ? d.horodatage : null };
}

/** « par … » n'est dit que si ce n'est pas l'utilisateur qui a activé le mode. */
export const parAutre = (mode) => (mode.par && mode.par !== 'utilisateur' ? mode.par : null);

/** Le texte de l'info-bulle de la pastille d'en-tête. */
export function titrePastille(mode) {
  const depuis = mode.depuis ? heureCourte(mode.depuis) : null;
  if (mode.etat === 'suspendu') {
    return `Mode autonome suspendu : la liste des chemins réservés a changé${depuis ? ` depuis ton activation (${depuis})` : ''}`;
  }
  return `Mode autonome : l’Assistant ${DECIDE.join(' et ')}${depuis ? ` depuis ${depuis}` : ''}`;
}

/** Les deux écritures de la pastille : « Autonome » (« Auto » quand la place manque) et « Autonome suspendu » (« Suspendu »). */
export const PASTILLE = {
  actif: { long: 'Autonome', court: 'Auto' },
  suspendu: { long: 'Autonome suspendu', court: 'Suspendu' },
};

/** La valeur que porte la requête quand on touche l'interrupteur (ou le bouton « Réactiver ») : un mode suspendu se réactive par `active`. */
export function valeurApresClic(mode) {
  return mode.etat === 'inactif' ? 'active' : 'inactive';
}
