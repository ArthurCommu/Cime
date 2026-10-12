"""Le toast, cinq retouches, le dégradé du plateau mobile.

Même convention que test_mobile_accueil.py : analyse de texte du JS et du CSS de static/ (pas de navigateur dans pytest),
`verifier_toast_et_degrade(js)` lève AssertionError ; la table MUTATIONS prouve qu'elle échoue quand on casse chaque comportement.
`libelleEffectifs` et `joindre` sont de plus exécutées par node (si node est installé), avec leurs propres mutations.
Le toast est vérifié sur la CIBLE : les déclarations de `.toasts` sont lues une à une (pas une chaîne cherchée quelque part)
et comparées à ce que la feuille de style du navigateur pose sur `[popover]` (inset: 0, margin: auto, bordure, padding, fond Canvas) ;
sa place réelle (au-dessus de la barre d'onglets, hors des boutons de la carte actionnée) est mesurée par tests/page/outils/scenario_mobile.py.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

PAGE = Path(__file__).resolve().parents[2] / "src" / "cime" / "page"
STATIC = PAGE / "static"

# ce que la feuille de style du navigateur pose sur [popover], et que `.toasts` doit défaire une propriété après l'autre
REMISES_A_ZERO = {
    "inset": "auto", "margin": "0", "border": "0", "padding": "0", "background": "transparent", "overflow": "visible",
}
PLACE_BUREAU = "20px"
PLACE_MOBILE = "calc(64px + 12px + env(safe-area-inset-bottom))"


def _corps(texte, debut, fin):
    i = texte.find(debut)
    assert i >= 0, debut
    j = texte.find(fin, i)
    assert j >= 0, fin
    return texte[i:j]


def _declarations(css, selecteur):
    """Les déclarations de la règle dont le sélecteur est exactement `selecteur` : {propriété: valeur}. La dernière gagne."""
    m = re.search(r"(?:^|\n) *" + re.escape(selecteur) + r" \{([^}]*)\}", css)
    assert m, selecteur
    corps = re.sub(r"/\*.*?\*/", "", m.group(1), flags=re.S)
    resultat = {}
    for d in corps.split(";"):
        if d.strip():
            nom, _, valeur = d.partition(":")
            resultat[nom.strip()] = valeur.strip()
    return resultat


def _bloc_telephone(css):
    debut = css.index("@media (max-width: 760px) {")
    fin = css.index("\n}\n", debut) + 3
    return css[debut:fin], css[:debut] + css[fin:]


def verifier_toast_et_degrade(js):
    commun, rail, scene, css = js["commun.js"], js["vues/rail.js"], js["vues/scene.js"], js["style.css"]
    telephone, bureau = _bloc_telephone(css)

    # 1. le toast : un popover remis à zéro propriété par propriété, puis placé
    assert "popover: 'manual'" in commun and "pile.showPopover();" in commun  # il garde la couche supérieure (au-dessus d'un <dialog> modal)
    assert bureau.count(".toasts {") == 1 and telephone.count(".toasts {") == 1  # une règle au bureau, une seule en mobile : rien ne la surcharge
    toasts = _declarations(bureau, ".toasts")
    for propriete, valeur in REMISES_A_ZERO.items():
        assert toasts.get(propriete) == valeur, (propriete, toasts.get(propriete))
    assert toasts.get("position") == "fixed" and toasts.get("left") == "50%" and toasts.get("bottom") == PLACE_BUREAU, toasts
    assert "translateX(-50%)" in toasts.get("transform", ""), toasts
    assert "top" not in toasts and "right" not in toasts  # `inset: auto` ne laisse ni top ni right
    mobile = _declarations(telephone, ".toasts")
    assert mobile == {"bottom": PLACE_MOBILE}, mobile  # en mobile, seule la place change : au-dessus de la barre de 64 px, 12 px d'air
    assert css.index(telephone) > css.index(".toasts {")  # le bloc mobile vient après la règle de bureau : il l'emporte

    # 2. la barre d'onglets est opaque : le fond de la page, pas un rgba
    barre = _declarations(telephone, ".barre-onglets")
    assert barre.get("background") == "var(--fond)", barre
    assert "rgba" not in telephone.split(".barre-onglets {")[1].split("}")[0]

    # 3. les effectifs passent par la fonction pure ; les séparateurs par `joindre`
    resume = _corps(commun, "export function resumeAgents(etat)", "function niveauAge")
    assert "libelleEffectifs(compte)" in resume and "travaillent" not in resume and "morceaux" not in resume
    assert "export function libelleEffectifs(compte) {" in commun and "export function joindre(morceaux, sep) {" in commun
    carte = _corps(commun, "export function carteAttente(", "\n}\n")
    assert ("el('div', { class: 'attente-meta' }, joindre([\n      age(attente.depuis, 'depuis'), agentDemandeur(attente),\n"
            "      typeof attente.equipe === 'string' && attente.equipe ? ['équipe ', lienEquipe(attente.equipe)] : null,\n    ], ' · ')),") in carte
    assert "' · ', agentDemandeur" not in carte
    ligne = _corps(rail, "function ligneAgent(", "\n}\n")
    assert "joindre([avecEtat ? def.mot : null, agent.etat_depuis ? age(agent.etat_depuis, 'court') : null], ' · ')" in ligne
    assert "`${def.mot} · `" not in ligne
    assert "joindre," in _corps(rail, "import {", "} from '../commun.js'")

    # 4. un identifiant ne se coupe pas au trait d'union : il tient sur une ligne, c'est le titre qui s'abrège
    cible = _declarations(css, ".rail-cible")
    assert cible.get("white-space") == "nowrap" and cible.get("flex") == "none", cible
    titre = _declarations(css, ".rail-titre")
    assert titre.get("overflow") == "hidden" and titre.get("text-overflow") == "ellipsis" and titre.get("white-space") == "nowrap", titre
    qui = _declarations(css, ".rail-qui")
    assert qui.get("white-space") == "nowrap" and qui.get("text-overflow") == "ellipsis" and qui.get("min-width") == "0", qui
    assert _declarations(css, ".rail-qui-coince").get("display") == "flex"
    coince = _corps(rail, "function blocCoince(", "\n}\n")
    assert "class: 'rail-qui rail-qui-coince'" in coince and "el('span', { class: 'rail-titre' }, TYPES_ALARME[a.type] || a.type)" in coince
    assert "el('span', { class: 'rail-cible' }, `·\\u00A0${cible}`)" in coince  # le point reste collé à l'identifiant

    # 5. le dégradé du bord droit du plateau : mobile seulement, 28 px, sans prise sur le pointeur ; il disparaît au premier glissement
    assert _declarations(bureau, ".plateau-bord") == {"display": "none"}  # absent au bureau
    bord = _declarations(telephone, ".plateau-bord")
    assert bord.get("display") == "block" and bord.get("position") == "absolute" and bord.get("right") == "0", bord
    assert bord.get("top") == "0" and bord.get("bottom") == "0" and bord.get("width") == "28px", bord
    assert bord.get("pointer-events") == "none", bord
    assert bord.get("background") == "linear-gradient(to right, transparent, var(--fond))", bord
    assert "const SEUIL_GLISSEMENT = 8;" in scene
    assert re.search(r"^let aGlisse = false;", scene, re.M)  # variable de module : elle survit au retour sur la Scène
    assert "const bordDroit = el('div', { class: 'plateau-bord', 'aria-hidden': 'true' });" in scene
    assert "if (!aGlisse) plateau.append(bordDroit);" in scene
    assert "plateau.addEventListener('pointerdown', (ev) => { departGlissement = { x: ev.clientX, y: ev.clientY }; });" in scene
    mouvement = _corps(scene, "plateau.addEventListener('pointermove'", "\n});\n")
    assert "if (aGlisse || !departGlissement) return;" in mouvement
    assert "Math.hypot(ev.clientX - departGlissement.x, ev.clientY - departGlissement.y) > SEUIL_GLISSEMENT" in mouvement
    assert "aGlisse = true;" in mouvement and "bordDroit.remove();" in mouvement
    assert "for (const fin of ['pointerup', 'pointercancel']) plateau.addEventListener(fin, () => { departGlissement = null; });" in scene
    assert "aGlisse = false" not in scene.replace("let aGlisse = false;", "")  # une fois disparu, il reste disparu
    assert "dataset.glisse" not in scene and "'glisse'" not in scene  # jamais d'état dans le DOM
    rendre = _corps(scene, "export function rendre(ctx)", "\n}\n")
    assert "bordDroit" not in rendre and "aGlisse" not in rendre  # le retour sur la Scène ne le remet pas


# ---------------------------------------------------------------------------
# libelleEffectifs et joindre exécutées (node)
# ---------------------------------------------------------------------------
SONDE = """
const { libelleEffectifs, joindre } = await import(process.argv[2]);
const effectifs = [
  {}, { travaille: 1 }, { travaille: 2, attend: 1 }, { attend: 2, au_repos: 1 }, { au_repos: 2 }, { travaille: 3, arrete: 1, inconnu: 2 },
  { arrete: 2 }, { inconnu: 1 }, { travaille: 0, attend: 0, au_repos: 0, arrete: 0, inconnu: 0 }, { travaille: 1, au_repos: 1, attend: 1, inconnu: 1, arrete: 1 },
].map(libelleEffectifs);
const jonctions = [
  joindre(['a', null, 'b'], ' · '), joindre([null, 'b'], ' · '), joindre(['a', ''], ' · '), joindre([null, false, undefined, [], ''], ' · '),
  joindre(['a', ['x', 'y'], 'c'], '|'), joindre([0, 'a'], '|'), joindre([], '|'), joindre(['seul'], '|'),
];
console.log(JSON.stringify({ effectifs, jonctions }));
"""
NB = " "
EFFECTIFS_ATTENDUS = [
    f"0{NB}travaillent",
    f"1{NB}travaille",
    f"2{NB}travaillent · 1{NB}attend",
    f"0{NB}travaillent · 1{NB}au repos · 2{NB}attendent",
    f"0{NB}travaillent · 2{NB}au repos",
    f"3{NB}travaillent · 2{NB}inconnus · 1{NB}arrêté",
    f"0{NB}travaillent · 2{NB}arrêtés",
    f"0{NB}travaillent · 1{NB}inconnu",
    f"0{NB}travaillent",
    f"1{NB}travaille · 1{NB}au repos · 1{NB}attend · 1{NB}inconnu · 1{NB}arrêté",
]
JONCTIONS_ATTENDUES = [
    ["a", " · ", "b"], ["b"], ["a"], [], ["a", "|", ["x", "y"], "|", "c"], [0, "|", "a"], [], ["seul"],
]


def executer(dossier_static):
    sonde = dossier_static / "sonde-toast.mjs"
    sonde.write_text(SONDE, encoding="utf-8")
    res = subprocess.run(["node", str(sonde), str(dossier_static / "commun.js")], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


def verifier_fonctions_executees(dossier_static):
    r = executer(dossier_static)
    assert r["effectifs"] == EFFECTIFS_ATTENDUS, r["effectifs"]
    assert r["jonctions"] == JONCTIONS_ATTENDUES, r["jonctions"]
    for libelle in r["effectifs"]:  # coupure permise seulement après « · » : les seules espaces ordinaires sont celles du séparateur
        assert libelle.replace(" · ", "").count(" ") == libelle.count("au repos"), libelle  # « au repos » garde son espace ordinaire interne
        assert not re.search(r"\d ", libelle), libelle  # jamais d'espace ordinaire entre un nombre et son mot


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def js():
    fichiers = sorted(STATIC.glob("*.js")) + sorted((STATIC / "vues").glob("*.js")) + [STATIC / "style.css"]
    return {str(f.relative_to(STATIC)): f.read_text(encoding="utf-8") for f in fichiers}


def test_toast_et_degrade_mobile(js):
    verifier_toast_et_degrade(js)


def _remplace(fichier, ancien, nouveau):
    def mutation(js):
        assert ancien in js[fichier], ancien
        return {**js, fichier: js[fichier].replace(ancien, nouveau)}
    return mutation


CSS = "style.css"
COM = "commun.js"
RA = "vues/rail.js"
SC = "vues/scene.js"
RESET = "  inset: auto; margin: 0; border: 0; padding: 0; background: transparent; overflow: visible;\n"
BORD = ".plateau-bord { display: block; position: absolute; top: 0; right: 0; bottom: 0; z-index: 1; width: 28px; pointer-events: none; background: linear-gradient(to right, transparent, var(--fond)); }"
MUTATIONS = {
    # 1. le toast, une remise à zéro à la fois, puis sa place
    "toast : inset oublié": _remplace(CSS, "inset: auto; margin: 0;", "margin: 0;"),
    "toast : inset laissé à 0": _remplace(CSS, "inset: auto; margin: 0;", "inset: 0; margin: 0;"),
    "toast : marge automatique": _remplace(CSS, "inset: auto; margin: 0;", "inset: auto; margin: auto;"),
    "toast : marge oubliée": _remplace(CSS, "inset: auto; margin: 0;", "inset: auto;"),
    "toast : bordure oubliée": _remplace(CSS, " border: 0; padding: 0; background: transparent;", " padding: 0; background: transparent;"),
    "toast : bordure du navigateur": _remplace(CSS, " border: 0; padding: 0; background: transparent;", " border: solid; padding: 0; background: transparent;"),
    "toast : remplissage oublié": _remplace(CSS, " padding: 0; background: transparent; overflow", " background: transparent; overflow"),
    "toast : fond Canvas": _remplace(CSS, "background: transparent; overflow: visible;", "background: Canvas; overflow: visible;"),
    "toast : fond oublié": _remplace(CSS, "background: transparent; overflow: visible;", "overflow: visible;"),
    "toast : débordement caché": _remplace(CSS, "background: transparent; overflow: visible;", "background: transparent; overflow: auto;"),
    "toast : débordement oublié": _remplace(CSS, "background: transparent; overflow: visible;", "background: transparent;"),
    "toast : place du bureau": _remplace(CSS, "left: 50%; bottom: 20px; transform", "left: 50%; bottom: 40px; transform"),
    "toast : en haut au bureau": _remplace(CSS, "left: 50%; bottom: 20px; transform", "left: 50%; top: 20px; transform"),
    "toast : place mobile oubliée": _remplace(CSS, "  .toasts { bottom: calc(64px + 12px + env(safe-area-inset-bottom)); }\n", ""),
    "toast : mobile sous la barre": _remplace(CSS, "bottom: calc(64px + 12px + env(safe-area-inset-bottom)); }", "bottom: calc(12px + env(safe-area-inset-bottom)); }"),
    "toast : mobile sans zone sûre": _remplace(CSS, "bottom: calc(64px + 12px + env(safe-area-inset-bottom)); }", "bottom: calc(64px + 12px); }"),
    "toast : mobile sans air": _remplace(CSS, "bottom: calc(64px + 12px + env(safe-area-inset-bottom)); }", "bottom: calc(64px + env(safe-area-inset-bottom)); }"),
    "toast : plus un popover": _remplace(COM, "popover: 'manual'", "role: 'alert'"),
    "toast : plus en couche supérieure": _remplace(COM, "    pile.showPopover();\n", ""),
    # 2. la barre opaque
    "barre translucide": _remplace(CSS, "    background: var(--fond); border-top: 1px solid var(--bord);", "    background: rgba(20, 22, 26, 0.96); border-top: 1px solid var(--bord);"),
    "barre d'un autre fond": _remplace(CSS, "    background: var(--fond); border-top: 1px solid var(--bord);", "    background: var(--carte); border-top: 1px solid var(--bord);"),
    # 3. les séparateurs
    "attente : âge puis point codé en dur": _remplace(COM, "joindre([\n      age(attente.depuis, 'depuis'), agentDemandeur(attente),", "[age(attente.depuis, 'depuis'), ' · ', agentDemandeur(attente),"),
    "attente : séparateur différent": _remplace(COM, "    ], ' · ')),\n    el('div', { class: 'attente-actions' }", "    ], ' - ')),\n    el('div', { class: 'attente-actions' }"),
    "agent : état et point en dur": _remplace(RA, "joindre([avecEtat ? def.mot : null, agent.etat_depuis ? age(agent.etat_depuis, 'court') : null], ' · ')", "avecEtat ? `${def.mot} · ` : null, agent.etat_depuis ? age(agent.etat_depuis, 'court') : null"),
    "effectifs recomposés dans l'en-tête": _remplace(COM, "el('span', { class: 'effectifs-texte' }, phrase));\n}", "el('span', { class: 'effectifs-texte' }, `${compte.travaille || 0} travaillent`));\n}"),
    # 4. les identifiants
    "identifiant coupé au trait d'union": _remplace(CSS, ".rail-cible { flex: none; white-space: nowrap;", ".rail-cible { flex: none; white-space: normal;"),
    "identifiant rétréci": _remplace(CSS, ".rail-cible { flex: none; white-space: nowrap;", ".rail-cible { white-space: nowrap;"),
    "titre sans ellipse": _remplace(CSS, ".rail-titre { min-width: 0; overflow: hidden; text-overflow: ellipsis;", ".rail-titre { min-width: 0; overflow: hidden;"),
    "titre qui passe à la ligne": _remplace(CSS, ".rail-titre { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }", ".rail-titre { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: normal; }"),
    "ligne d'agent coupée": _remplace(CSS, ".rail-qui { font-weight: 600; color: var(--texte); min-width: 0; white-space: nowrap;", ".rail-qui { font-weight: 600; color: var(--texte); min-width: 0; white-space: normal;"),
    "alarme : titre hors de son enveloppe": _remplace(RA, "el('span', { class: 'rail-titre' }, TYPES_ALARME[a.type] || a.type)", "(TYPES_ALARME[a.type] || a.type)"),
    "alarme : point détaché de l'identifiant": _remplace(RA, "`·\\u00A0${cible}`", "`· ${cible}`"),
    "alarme : ligne qui n'est plus flex": _remplace(CSS, ".rail-qui-coince { display: flex; gap: 8px; }", ".rail-qui-coince { gap: 8px; }"),
    # 5. le dégradé du plateau mobile
    "dégradé absent": _remplace(CSS, "  " + BORD + "\n", ""),
    "dégradé visible au bureau": _remplace(CSS, ".plateau-bord { display: none; }\n", ""),
    "dégradé trop large": _remplace(CSS, "width: 28px; pointer-events: none;", "width: 40px; pointer-events: none;"),
    "dégradé qui prend le pointeur": _remplace(CSS, "width: 28px; pointer-events: none;", "width: 28px;"),
    "dégradé du mauvais côté": _remplace(CSS, "right: 0; bottom: 0; z-index: 1; width: 28px", "left: 0; bottom: 0; z-index: 1; width: 28px"),
    "dégradé vers l'autre sens": _remplace(CSS, "linear-gradient(to right, transparent, var(--fond))", "linear-gradient(to right, var(--fond), transparent)"),
    "dégradé d'une autre couleur": _remplace(CSS, "linear-gradient(to right, transparent, var(--fond))", "linear-gradient(to right, transparent, #000)"),
    "seuil de glissement à 20": _remplace(SC, "const SEUIL_GLISSEMENT = 8;", "const SEUIL_GLISSEMENT = 20;"),
    "glissement dès le premier mouvement": _remplace(SC, "ev.clientY - departGlissement.y) > SEUIL_GLISSEMENT", "ev.clientY - departGlissement.y) >= 0"),
    "glissement sans pointeur enfoncé": _remplace(SC, "if (aGlisse || !departGlissement) return;", "if (aGlisse) return;"),
    "le dégradé reste après le glissement": _remplace(SC, "    aGlisse = true;\n    bordDroit.remove();", "    aGlisse = true;"),
    "le glissement n'est pas retenu": _remplace(SC, "    aGlisse = true;\n    bordDroit.remove();", "    bordDroit.remove();"),
    "dégradé remis à chaque montage": _remplace(SC, "if (!aGlisse) plateau.append(bordDroit);", "plateau.append(bordDroit);"),
    "variable d'état dans le rendu": _remplace(SC, "export function rendre(ctx) {\n", "export function rendre(ctx) {\n  aGlisse = false;\n"),
    "état gardé dans le DOM": _remplace(SC, "    aGlisse = true;\n", "    aGlisse = true;\n    plateau.dataset.glisse = 'oui';\n"),
    "départ du glissement jamais oublié": _remplace(SC, "plateau.addEventListener(fin, () => { departGlissement = null; });", "plateau.addEventListener(fin, () => {});"),
}

MUTATIONS_EXECUTEES = {
    "0 travaillent tu": ("    mot(n('travaille'), 'travaille', 'travaillent'),", "    n('travaille') ? mot(n('travaille'), 'travaille', 'travaillent') : null,"),
    "zéro au repos dit": ("n('au_repos') ? mot(n('au_repos'), 'au repos', 'au repos') : null", "mot(n('au_repos'), 'au repos', 'au repos')"),
    "zéro attendent dit": ("n('attend') ? mot(n('attend'), 'attend', 'attendent') : null", "mot(n('attend'), 'attend', 'attendent')"),
    "zéro arrêtés dit": ("n('arrete') ? mot(n('arrete'), 'arrêté', 'arrêtés') : null", "mot(n('arrete'), 'arrêté', 'arrêtés')"),
    "zéro inconnus dit": ("n('inconnu') ? mot(n('inconnu'), 'inconnu', 'inconnus') : null", "mot(n('inconnu'), 'inconnu', 'inconnus')"),
    "0 travaille au singulier": ("nombre === 1 ? un : plusieurs", "nombre <= 1 ? un : plusieurs"),
    "2 travaille au singulier": ("nombre === 1 ? un : plusieurs", "nombre === 2 ? un : plusieurs"),
    "au repos accordé": ("mot(n('au_repos'), 'au repos', 'au repos')", "mot(n('au_repos'), 'au repos', 'aux repos')"),
    "attend sans accord": ("mot(n('attend'), 'attend', 'attendent')", "mot(n('attend'), 'attend', 'attends')"),
    "arrêtés sans accord": ("mot(n('arrete'), 'arrêté', 'arrêtés')", "mot(n('arrete'), 'arrêté', 'arrêté')"),
    "inconnus sans accord": ("mot(n('inconnu'), 'inconnu', 'inconnus')", "mot(n('inconnu'), 'inconnu', 'inconnu')"),
    "espace ordinaire entre le nombre et le mot": ("`${nombre}\\u00A0${nombre", "`${nombre} ${nombre"),
    "séparateur des effectifs": (".join(' · ')", ".join(', ')"),
    "séparateur insécable": (".join(' · ')", ".join('\\u00A0·\\u00A0')"),
    "arrêtés avant inconnus": ("""    n('inconnu') ? mot(n('inconnu'), 'inconnu', 'inconnus') : null,
    n('arrete') ? mot(n('arrete'), 'arrêté', 'arrêtés') : null,""", """    n('arrete') ? mot(n('arrete'), 'arrêté', 'arrêtés') : null,
    n('inconnu') ? mot(n('inconnu'), 'inconnu', 'inconnus') : null,"""),
    "joindre : null gardé": ("m !== null && m !== undefined && m !== false", "m !== undefined && m !== false"),
    "joindre : undefined gardé": ("m !== null && m !== undefined && m !== false", "m !== null && m !== false"),
    "joindre : false gardé": ("m !== null && m !== undefined && m !== false", "m !== null && m !== undefined"),
    "joindre : chaîne vide gardée": (" && m !== '' &&", " &&"),
    "joindre : liste vide gardée": (" && !(Array.isArray(m) && m.length === 0)", ""),
    "joindre : zéro avalé": ("m !== null && m !== undefined && m !== false && m !== '' && !(Array.isArray(m) && m.length === 0)", "Boolean(m)"),
    "joindre : séparateur après": ("(i ? [sep, m] : [m])", "[m, sep]"),
    "joindre : séparateur avant": ("(i ? [sep, m] : [m])", "[sep, m]"),
    "joindre : séparateur à l'indice du morceau absent": ("presents.flatMap((m, i)", "morceaux.flatMap((m, i)"),
}

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node n'est pas installé : libelleEffectifs et joindre ne sont pas exécutées")


@pytest.mark.parametrize("nom", MUTATIONS)
def test_mutation_detectee(nom, js):
    mutee = MUTATIONS[nom](js)  # hors du raises : la mutation doit s'appliquer, sinon le test serait faux
    with pytest.raises(AssertionError):
        verifier_toast_et_degrade(mutee)


@pytest.fixture
def copie_static(tmp_path):
    cible = tmp_path / "static"
    shutil.copytree(STATIC, cible, ignore=shutil.ignore_patterns("__pycache__"))
    return cible


@needs_node
def test_fonctions_executees(copie_static):
    verifier_fonctions_executees(copie_static)


@needs_node
@pytest.mark.parametrize("nom", MUTATIONS_EXECUTEES)
def test_mutation_executee_detectee(nom, copie_static):
    ancien, nouveau = MUTATIONS_EXECUTEES[nom]
    fichier = copie_static / "commun.js"
    texte = fichier.read_text(encoding="utf-8")
    assert ancien in texte, ancien  # la mutation doit s'appliquer
    fichier.write_text(texte.replace(ancien, nouveau), encoding="utf-8")
    with pytest.raises(AssertionError):
        verifier_fonctions_executees(copie_static)


def test_couverture_des_verifications():
    toutes = {n for n, v in globals().items() if n.startswith("verifier_") and callable(v)}
    assert toutes == {"verifier_toast_et_degrade", "verifier_fonctions_executees"} and MUTATIONS and MUTATIONS_EXECUTEES, sorted(toutes)
