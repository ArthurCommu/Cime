"""La ligne « Workers : A actifs sur P » et le réglage du plafond de la machine.

D'abord le rendu et l'action exécutés sous node (DOM minimal de test_mode_autonome, sauté si node est absent) : la phrase et ses cas, le détail dépliant, le corps envoyé,
le contrôle désactivé pendant l'appel, les trois sortes de réponses, les trois places de la ligne ; puis le faux hôte, lancé pour de bon. La table MUTATIONS_EXECUTEES prouve
que chaque vérification échoue quand on casse la règle qu'elle garde.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_mode_autonome import DOM  # noqa: E402  (le DOM minimal)

PAGE = Path(__file__).resolve().parents[2] / "src" / "cime" / "page"
STATIC = PAGE / "static"
OUTILS = Path(__file__).resolve().parent / "outils"
EXEMPLE_ETAT = Path(__file__).resolve().parent / "fixtures" / "exemple-etat.json"
CH, WK, COM, SRC, RA, MO, MOB, CSS = "charge.js", "vues/workers.js", "commun.js", "source.js", "vues/rail.js", "vues/mode-autonome.js", "vues/mobile.js", "style.css"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node n'est pas installé : la ligne des workers n'est pas exécutée")


def _jeux():
    base = json.loads(EXEMPLE_ETAT.read_text(encoding="utf-8"))
    base["attentes_utilisateur"] = base["attentes_utilisateur"][:2]

    def avec(**champs):
        e = json.loads(json.dumps(base))
        c = e["charge"]
        for cle, v in champs.items():
            if cle.startswith("machine_"):
                c["machine"][cle[8:]] = v
            else:
                c[cle] = v
        return e

    nul = json.loads(json.dumps(base))
    nul["charge"] = None
    absent = json.loads(json.dumps(base))
    del absent["charge"]
    defaut = avec(projet=None, source="machine", workers_max=3)
    defaut["charge"]["machine"] = {"valeur": 3, "source": "defaut", "depuis": None, "par": None}
    return {
        "projet plus bas": avec(),
        "machine seule": avec(projet=None, source="machine", workers_max=6),
        "projet plus haut": avec(projet=8, source="machine", workers_max=6),
        "un actif": avec(workers_actifs=1, par_projet={"boutique": 1}),
        "actifs inconnus": avec(workers_actifs=None, par_projet=None),
        "plafond inconnu": avec(workers_max=None),
        "zero reel": avec(workers_actifs=0, par_projet={"boutique": 0}),
        "nul": nul,
        "absent": absent,
        "defaut": defaut,
        "sans date": avec(machine_depuis=None, machine_par=None),
        "par un autre": avec(machine_par="assistant"),
    }


SONDE = DOM + r"""
const racine = process.argv[2];
const jeux = JSON.parse(readFileSync(process.argv[3], 'utf8'));
const ch = await import(`${racine}/charge.js`);
const commun = await import(`${racine}/commun.js`);
const vue = await import(`${racine}/vues/workers.js`);
const rail = await import(`${racine}/vues/rail.js`);
const mobile = await import(`${racine}/vues/mobile.js`);
const sortie_ = {};
const reponses = [];
let appels = [];
const source = { mode: 'hote', horloge: { maintenant: () => Date.parse('2026-10-07T13:04:11.123Z'), ageDonnee: () => 0 }, fluxInterrompu: () => false,
  agir: (...args) => { appels.push(args); return new Promise((res) => reponses.push(res)); } };
let rendus = 0;
commun.brancher(source, () => { rendus += 1; });
const phrases = {};
for (const [nom, etat] of Object.entries(jeux)) phrases[nom] = ch.phraseWorkers(ch.lireCharge(etat));
sortie_.phrases = phrases;
sortie_.illisible = [ch.phraseWorkers(ch.lireCharge({ charge: 'x' })), ch.phraseWorkers(ch.lireCharge({ charge: { workers_actifs: '5', workers_max: -1 } })), ch.phraseWorkers(ch.lireCharge(null))];

// le détail : la ligne est un bouton qui déplie un panneau
const detail = {};
for (const [nom, etat] of Object.entries(jeux)) {
  vue.reinitialiserWorkers();
  const bloc = vue.ligneWorkers(etat, () => {});
  const bouton = sous(bloc).find((n) => n.tag === 'button');
  const replie = { expanded: bouton.attrs['aria-expanded'], panneaux: a(bloc, 'workers-detail').length, texte: texte(bouton), title: bouton.attrs.title ?? null };
  let redessine = 0;
  const bloc2 = vue.ligneWorkers(etat, () => { redessine += 1; });
  clic(sous(bloc2).find((n) => n.tag === 'button'));
  const ouvert = vue.ligneWorkers(etat, () => {});
  const panneau = a(ouvert, 'workers-detail')[0];
  detail[nom] = { replie, redessine, expanded: sous(ouvert).find((n) => n.tag === 'button').attrs['aria-expanded'], lignes: panneau ? panneau.children.filter((n) => n.tag === 'p').map(texte) : null,
    mono: panneau ? a(panneau, 'mono').map(texte) : null, selects: panneau ? sous(panneau).filter((n) => n.tag === 'select').length : 0 };
}
sortie_.detail = detail;

// le réglage
const choix = (etat) => { vue.reinitialiserWorkers(); const b = vue.ligneWorkers(etat, () => {}); clic(sous(b).find((n) => n.tag === 'button')); return vue.ligneWorkers(etat, () => {}); };
const select = (bloc) => sous(bloc).find((n) => n.tag === 'select');
const resumeSelect = (s) => ({ disabled: 'disabled' in s.attrs, busy: s.attrs['aria-busy'] ?? null, title: s.attrs.title ?? null, choisie: sous(s).filter((o) => 'selected' in o.attrs).map((o) => o.attrs.value),
  options: sous(s).filter((o) => o.tag === 'option').map((o) => [o.attrs.value, texte(o)]) });
const retour = (bloc) => a(bloc, 'plafond-retour').map((p) => [texte(p), p.classes.join(' ')]);
const reglage = {};
reglage.depart = { projetPlusBas: resumeSelect(select(choix(jeux['projet plus bas']))), defaut: resumeSelect(select(choix(jeux['defaut']))) };
const change = (s, valeur) => (s.ecouteurs.change || []).map((f) => f({ target: { value: valeur } }))[0];
for (const [nom, valeur, rep] of [['cinq', '5', { resultat: 'ok', message: 'plafond de workers : 5' }], ['defaut', 'defaut', { resultat: 'ok', message: 'plafond de workers : défaut (3)' }],
  ['deja', '6', { resultat: 'refuse', message: 'déjà 6' }], ['erreur', '2', { resultat: 'erreur', message: 'écriture impossible' }]]) {
  appels = []; reponses.length = 0;
  const etat = jeux['projet plus bas'];
  const promesse = change(select(choix(etat)), valeur);
  const pendant = resumeSelect(select(choix(etat)));
  const doublon = change(select(choix(etat)), '7');
  reponses[0](rep);
  await promesse; await doublon;
  const apres = choix(etat);
  reglage[nom] = { appels: appels.map((x) => [x[0], x[1]]), nb: appels.length, pendant, retour: retour(apres), select: resumeSelect(select(apres)), role: a(apres, 'plafond-retour').map((p) => p.attrs.role) };
}
// une panne réseau est une erreur
{
  const etat = jeux['projet plus bas'];
  const normal = source.agir;
  source.agir = async () => { throw new Error('hôte injoignable (réseau)'); };
  await change(select(choix(etat)), '4');
  source.agir = normal;
  reglage.reseau = retour(choix(etat));
  commun.definirActionsFigees(false);
}
// le message disparaît tout seul
{
  const vraiSetTimeout = globalThis.setTimeout;
  const minuteurs = [];
  globalThis.setTimeout = (f, ms) => { minuteurs.push([f, ms]); return 1; };
  appels = []; reponses.length = 0;
  const etat = jeux['projet plus bas'];
  const promesse = change(select(choix(etat)), '5');
  reponses[0]({ resultat: 'ok', message: 'plafond de workers : 5' });
  await promesse;
  const avant = retour(choix(etat)).length;
  const attente = minuteurs.map((m) => m[1]);
  minuteurs.forEach(([f]) => f());
  globalThis.setTimeout = vraiSetTimeout;
  reglage.disparait = { avant, apres: retour(choix(etat)).length, attente };
  // et le prochain changement l'efface aussitôt
  appels = []; reponses.length = 0;
  const p2 = change(select(choix(etat)), '2');
  reponses[0]({ resultat: 'ok', message: 'plafond de workers : 2' }); await p2;
  const avantChangement = retour(choix(etat)).length;
  const p3 = change(select(choix(etat)), '3');
  reglage.efface = [avantChangement, retour(choix(etat)).length];
  reponses[1]({ resultat: 'ok', message: 'plafond de workers : 3' }); await p3;
}
// l'hôte ne répond plus : le contrôle est désactivé, avec le même titre que l'interrupteur
{
  appels = []; commun.definirActionsFigees(true);
  const s = select(choix(jeux['projet plus bas']));
  await change(s, '5');
  reglage.fige = { select: resumeSelect(s), appels: appels.length, phrase: commun.PHRASE_ACTIONS_FIGEES };
  commun.definirActionsFigees(false);
}
sortie_.reglage = reglage;

// les trois places : le rail du bureau, le tiroir du téléphone, la feuille du téléphone
const places = {};
const nb = (n) => a(n, 'workers').length;
for (const [cas, attentes] of [['attentes', jeux['projet plus bas'].attentes_utilisateur], ['rien', []], ['inconnu', null]]) {
  for (const telephone of [false, true]) {
    const e = { ...jeux['projet plus bas'], attentes_utilisateur: attentes };
    const conteneur = new Elt('aside');
    rail.rendreRail(conteneur, { etat: e, selection: null, fermer() {}, ouvrir() {}, redessiner() {}, telephone });
    places[`${cas}|${telephone ? 'tiroir' : 'bureau'}`] = nb(conteneur);
  }
  document.body.children.length = 0;
  mobile.majFeuilleAttentes({ ...jeux['projet plus bas'], attentes_utilisateur: attentes });
  mobile.ouvrirFeuilleAttentes();
  const dialogue = document.body.children.find((n) => n.tag === 'dialog');
  places[`${cas}|feuille`] = nb(dialogue);
  mobile.fermerFeuilleAttentes();
}
sortie_.places = places;
sortie(sortie_);
"""


def _lancer(dossier_static, jeux):
    (dossier_static / "jeux-workers.json").write_text(json.dumps(jeux), encoding="utf-8")
    fichier = dossier_static / "sonde-workers.mjs"
    fichier.write_text(SONDE, encoding="utf-8")
    res = subprocess.run(["node", str(fichier), str(dossier_static), str(dossier_static / "jeux-workers.json")], capture_output=True, text=True, timeout=120,
                         env={**os.environ, "TZ": "Europe/Paris"})
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


def verifier_phrase(static):
    r = _lancer(static, _jeux())
    p = r["phrases"]
    assert p["projet plus bas"] == "Workers : 5 actifs sur 4"
    assert p["un actif"] == "Workers : 1 actif sur 4"  # le singulier
    assert p["actifs inconnus"] == "Workers : ? actifs sur 4"  # un nombre inconnu s'écrit « ? »
    assert p["plafond inconnu"] == "Workers : 5 actifs sur ?"
    assert p["zero reel"] == "Workers : 0 actifs sur 4"  # un zéro mesuré reste un zéro
    assert p["nul"] == "Workers : inconnu" and p["absent"] == "Workers : inconnu"
    assert r["illisible"] == ["Workers : inconnu", "Workers : inconnu", "Workers : inconnu"], r["illisible"]  # jamais de faux zéro
    assert all("0" not in v for k, v in p.items() if k in ("nul", "absent", "actifs inconnus"))


def verifier_detail(static):
    d = _lancer(static, _jeux())["detail"]
    pb = d["projet plus bas"]
    assert pb["replie"]["expanded"] == "false" and pb["replie"]["panneaux"] == 0 and pb["replie"]["texte"].startswith("Workers : 5 actifs sur 4")
    assert pb["redessine"] == 1 and pb["expanded"] == "true"  # le clic ouvre et redessine
    assert pb["lignes"][0] == "Plafond de la machine : 6 · modifié par l’utilisateur le 7 oct. 2026", pb["lignes"]
    assert pb["lignes"][1] == "Plafond du projet : 4" and pb["lignes"][2] == "Par projet : blog 1 · boutique 4"
    assert pb["mono"] == ["blog", "boutique"] and pb["selects"] == 1
    assert "Plafond de la machine : 6" in pb["replie"]["title"] and "Plafond du projet : 4" in pb["replie"]["title"] and "Par projet : blog 1 · boutique 4" in pb["replie"]["title"]
    # le plafond du projet n'est dit que s'il est plus bas que celui de la machine
    for nom in ("machine seule", "projet plus haut"):
        assert not any("Plafond du projet" in x for x in d[nom]["lignes"]), nom
    # « modifié … » seulement si la date est connue ; un autre auteur est nommé
    assert d["sans date"]["lignes"][0] == "Plafond de la machine : 6", d["sans date"]["lignes"]
    assert d["par un autre"]["lignes"][0].endswith("modifié par assistant le 7 oct. 2026"), d["par un autre"]["lignes"]
    assert d["defaut"]["lignes"][0] == "Plafond de la machine : par défaut (3)", d["defaut"]["lignes"]
    assert not any(x.startswith("Par projet") for x in d["actifs inconnus"]["lignes"])
    assert d["nul"]["lignes"] == ["La charge de la machine est inconnue pour le moment."] and d["nul"]["selects"] == 0


def verifier_reglage(static):
    g = _lancer(static, _jeux())["reglage"]
    options = [[str(i), str(i)] for i in range(1, 9)] + [["defaut", "par défaut (3)"]]
    assert g["depart"]["projetPlusBas"]["options"] == options
    assert g["depart"]["projetPlusBas"]["choisie"] == ["6"], "au départ : le plafond de la machine, pas celui en vigueur"
    assert g["depart"]["defaut"]["choisie"] == ["defaut"]
    # le corps envoyé
    assert g["cinq"]["appels"] == [["plafond", {"valeur": 5}]], g["cinq"]["appels"]
    assert g["defaut"]["appels"] == [["plafond", {"valeur": "defaut"}]], g["defaut"]["appels"]
    # désactivé et occupé pendant l'appel : un second changement n'envoie rien
    assert g["cinq"]["pendant"]["disabled"] and g["cinq"]["pendant"]["busy"] == "true" and g["cinq"]["nb"] == 1
    assert not g["depart"]["projetPlusBas"]["disabled"] and g["depart"]["projetPlusBas"]["busy"] is None
    # le message de l'hôte, près du contrôle : neutre pour ok et « déjà », rouge doux pour l'erreur seulement
    assert g["cinq"]["retour"] == [["plafond de workers : 5", "plafond-retour"]] and g["cinq"]["select"]["choisie"] == ["5"]
    assert g["defaut"]["retour"] == [["plafond de workers : défaut (3)", "plafond-retour"]]
    assert g["deja"]["retour"] == [["déjà 6", "plafond-retour"]]
    assert g["erreur"]["retour"] == [["écriture impossible", "plafond-retour texte-erreur"]]
    assert g["reseau"] == [["hôte injoignable (réseau)", "plafond-retour texte-erreur"]]
    assert g["erreur"]["select"]["choisie"] == ["6"], "après une erreur, le choix revient à ce que dit l'état"
    assert not any(g[k]["select"]["disabled"] for k in ("cinq", "defaut", "deja", "erreur"))
    assert g["cinq"]["role"] == ["status"]
    # le message disparaît tout seul, ou au prochain changement
    assert g["disparait"]["avant"] == 1 and g["disparait"]["apres"] == 0 and 8000 in g["disparait"]["attente"], g["disparait"]
    assert g["efface"] == [1, 0], g["efface"]
    # l'hôte injoignable : désactivé, même titre que l'interrupteur, rien d'envoyé
    assert g["fige"]["select"]["disabled"] and g["fige"]["select"]["title"] == g["fige"]["phrase"] and g["fige"]["appels"] == 0


def verifier_places(static):
    p = _lancer(static, _jeux())["places"]
    # au bureau : dans « Ce qui t'attend », quel que soit le contenu du bloc ; au téléphone : dans la feuille, ou dans le tiroir quand rien n'attend
    assert p == {"attentes|bureau": 1, "attentes|tiroir": 0, "attentes|feuille": 1, "rien|bureau": 1, "rien|tiroir": 1, "rien|feuille": 0,
                 "inconnu|bureau": 1, "inconnu|tiroir": 0, "inconnu|feuille": 1}, p


@pytest.fixture
def copie_static(tmp_path):
    cible = tmp_path / "static"
    shutil.copytree(STATIC, cible, ignore=shutil.ignore_patterns("__pycache__"))
    return cible


@needs_node
def test_phrase(copie_static): verifier_phrase(copie_static)
@needs_node
def test_detail(copie_static): verifier_detail(copie_static)
@needs_node
def test_reglage(copie_static): verifier_reglage(copie_static)
@needs_node
def test_places(copie_static): verifier_places(copie_static)


def verifier_route_et_style(source_js, css):
    assert "plafond: '/api/actions/plafond'," in source_js
    assert "@media (pointer: coarse), (max-width: 760px) {\n  .workers-ligne, .plafond-reglage, .plafond-choix { min-height: 44px; }" in css  # cible de 44 px au téléphone


def test_route_et_style():
    verifier_route_et_style((STATIC / SRC).read_text(encoding="utf-8"), (STATIC / CSS).read_text(encoding="utf-8"))


@pytest.mark.parametrize("nom, fichier, ancien, nouveau", [
    ("route perdue", SRC, "plafond: '/api/actions/plafond',", ""),
    ("route fausse", SRC, "plafond: '/api/actions/plafond',", "plafond: '/api/actions/fusions-auto',"),
    ("cible du téléphone perdue", CSS, ".workers-ligne, .plafond-reglage, .plafond-choix { min-height: 44px; }", ".plafond-choix { min-height: 44px; }"),
])
def test_mutation_route_et_style_detectee(nom, fichier, ancien, nouveau):
    textes = {SRC: (STATIC / SRC).read_text(encoding="utf-8"), CSS: (STATIC / CSS).read_text(encoding="utf-8")}
    assert ancien in textes[fichier]
    textes[fichier] = textes[fichier].replace(ancien, nouveau, 1)
    with pytest.raises(AssertionError):
        verifier_route_et_style(textes[SRC], textes[CSS])


# mutations : (fichier, ancien, nouveau, vérification qui doit échouer)
MUTATIONS_EXECUTEES = {
    "singulier perdu": (CH, "charge.actifs === 1 ? 'actif' : 'actifs'", "'actifs'", verifier_phrase),
    "inconnu lu comme zéro": (CH, "v >= 0 ? v : null)", "v >= 0 ? v : 0)", verifier_phrase),
    "« ? » perdu pour le plafond": (CH, "charge.max === null ? '?' : charge.max", "charge.max", verifier_phrase),
    "« ? » perdu pour les actifs": (CH, "charge.actifs === null ? '?' : charge.actifs", "charge.actifs", verifier_phrase),
    "charge nul : un faux zéro": (CH, "return 'Workers : inconnu';", "return 'Workers : 0 actifs sur 0';", verifier_phrase),
    "plafond du projet toujours dit": (CH, "Boolean(charge && charge.source === 'projet' && charge.projet !== null)", "Boolean(charge && charge.projet !== null)", verifier_detail),
    "date dite même inconnue": (WK, "${date ? ` · modifié par ${qui || 'inconnu'} le ${date}` : ''}", "${` · modifié par ${qui || 'inconnu'} le ${date}`}", verifier_detail),
    "auteur toujours l'utilisateur": (WK, "m.par === 'utilisateur' ? 'l’utilisateur' : m.par", "'l’utilisateur'", verifier_detail),
    "défaut non dit": (WK, "m.defaut ? `par défaut (${PLAFOND_DEFAUT})` : String(m.valeur)", "String(m.valeur)", verifier_detail),
    "noms de projets pas en mono": (WK, "mono(nom)", "nom", verifier_detail),
    "panneau toujours ouvert": (WK, "const ouvert = deplie;", "const ouvert = true;", verifier_detail),
    "aria-expanded figé": (WK, "'aria-expanded': String(ouvert)", "'aria-expanded': 'false'", verifier_detail),
    "survol sans le projet": (WK, "projetPlusBas(charge) ? `Plafond du projet : ${charge.projet}` : null,\n    charge.parProjet ? `Par", "charge.parProjet ? `Par", verifier_detail),
    "départ : le plafond en vigueur": (CH, "String(charge.machine.valeur)", "String(charge.max)", verifier_reglage),
    "défaut non choisi au départ": (CH, "charge.machine.defaut ? 'defaut' :", "false ? 'defaut' :", verifier_reglage),
    "valeur envoyée en texte": (COM, "valeur === 'defaut' ? 'defaut' : Number(valeur)", "String(valeur)", verifier_reglage),
    "défaut envoyé en nombre": (COM, "valeur === 'defaut' ? 'defaut' : Number(valeur)", "valeur === 'defaut' ? 3 : Number(valeur)", verifier_reglage),
    "contrôle actif pendant l'appel": (WK, "disabled: Boolean(demande) || fige,", "disabled: fige,", verifier_reglage),
    "contrôle pas occupé": (WK, "'aria-busy': demande ? 'true' : null, disabled", "disabled", verifier_reglage),
    "second appel permis": (COM, "if (plafondEnCours || actionsFigees) return;", "if (actionsFigees) return;", verifier_reglage),
    "figé : appel permis": (COM, "if (plafondEnCours || actionsFigees) return;", "if (plafondEnCours) return;", verifier_reglage),
    "figé : contrôle actif": (WK, "disabled: Boolean(demande) || fige,", "disabled: Boolean(demande),", verifier_reglage),
    "figé : titre perdu": (WK, "title: fige ? PHRASE_ACTIONS_FIGEES : null, onchange", "onchange", verifier_reglage),
    "« déjà » en rouge": (WK, "r.resultat === 'erreur' ? ' texte-erreur'", "r.resultat !== 'ok' ? ' texte-erreur'", verifier_reglage),
    "erreur en neutre": (WK, "r.resultat === 'erreur' ? ' texte-erreur' : ''", "''", verifier_reglage),
    "message de l'hôte perdu": (WK, "if (!r || !r.message) return null;", "return null;", verifier_reglage),
    "message qui ne disparaît pas": (COM, "plafondMinuteur = setTimeout(() => { plafondRetour = null; rerendre(); }, RETOUR_PLAFOND_MS);", "", verifier_reglage),
    "ancien message gardé": (COM, "  clearTimeout(plafondMinuteur);\n  plafondRetour = null;\n", "", verifier_reglage),
    "choix qui garde l'échec": (WK, "retour.resultat !== 'erreur' ? retour.valeur : null", "retour.valeur", verifier_reglage),
    "absente du bureau": (RA, "const encadre = [encadreMode(etat, redessiner), ligneWorkers(etat, redessiner)];", "const encadre = encadreMode(etat, redessiner);", verifier_places),
    "absente du tiroir": (MO, "  bloc.append(ligneWorkers(etat, redessiner));\n", "", verifier_places),
    "absente de la feuille": (MOB, "    modeDansLaFeuille(etat) ? ligneWorkers(etat, () => majFeuilleAttentes(dernierEtat)) : null,\n", "", verifier_places),
    "dans la feuille quand rien n'attend aussi": (MOB, "modeDansLaFeuille(etat) ? ligneWorkers(", "ligneWorkers(", verifier_places),
}


@needs_node
@pytest.mark.parametrize("nom", MUTATIONS_EXECUTEES)
def test_mutation_executee_detectee(nom, copie_static):
    fichier, ancien, nouveau, verification = MUTATIONS_EXECUTEES[nom]
    cible = copie_static / fichier
    texte = cible.read_text(encoding="utf-8")
    assert ancien in texte, ancien  # la mutation doit s'appliquer
    cible.write_text(texte.replace(ancien, nouveau, 1), encoding="utf-8")
    with pytest.raises((AssertionError, KeyError, StopIteration, ValueError, IndexError, TypeError)):
        verification(copie_static)


# ---------------------------------------------------------------- le faux hôte, lancé pour de bon
def _port_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _requete(port, chemin, corps=None):
    donnees = None if corps is None else json.dumps(corps).encode()
    r = urllib.request.Request(f"http://127.0.0.1:{port}{chemin}", data=donnees, headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port}"} if donnees else {})
    with urllib.request.urlopen(r, timeout=10) as rep:
        return json.loads(rep.read())


def verifier_faux_hote(dossier_outils):
    port = _port_libre()
    proc = subprocess.Popen([sys.executable, str(dossier_outils / "hote_factice.py"), str(PAGE), str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        for _ in range(100):
            try:
                _requete(port, "/api/etat")
                break
            except Exception:
                time.sleep(0.1)
        etat = lambda: _requete(port, "/api/etat")["charge"]
        regler = lambda **r: _requete(port, "/test/regler?" + "&".join(f"{k}={v}" for k, v in r.items()))
        plafond = lambda v: _requete(port, "/api/actions/plafond", {"valeur": v})
        c = etat()
        assert c["machine"]["valeur"] == 6 and c["projet"] is None and c["workers_max"] == 6 and c["source"] == "machine"
        assert plafond(5) == {"resultat": "ok", "message": "plafond de workers : 5"}
        c = etat()
        assert c["machine"]["valeur"] == 5 and c["machine"]["par"] == "utilisateur" and c["machine"]["depuis"] and c["workers_max"] == 5
        assert plafond(5) == {"resultat": "refuse", "message": "déjà 5"}
        assert plafond("defaut") == {"resultat": "ok", "message": "plafond de workers : défaut (3)"}
        assert etat()["machine"]["source"] == "defaut" and etat()["workers_max"] == 3
        assert plafond("defaut") == {"resultat": "refuse", "message": "déjà au défaut"}
        for faux in (0, 9, "5", None, True, 2.5):
            r = plafond(faux)
            assert r["resultat"] == "refuse" and r["message"].startswith("valeur attendue : "), faux
        regler(charge="projet_plus_bas")
        c = etat()
        assert c["projet"] == 4 and c["workers_max"] == 4 and c["source"] == "projet" and c["machine"]["valeur"] == 6
        assert plafond(8)["resultat"] == "ok"
        c = etat()
        assert c["machine"]["valeur"] == 8 and c["source"] == "projet" and c["workers_max"] == 4, "le plafond du projet s'applique tant qu'il est plus bas"
        assert plafond(3)["resultat"] == "ok" and etat()["source"] == "machine" and etat()["workers_max"] == 3  # le projet n'est plus plus bas
        regler(charge="inconnu")
        assert etat() is None
        regler(charge="defaut")
        assert etat()["machine"]["source"] == "defaut" and etat()["projet"] is None
        regler(charge="un_actif")
        assert etat()["workers_actifs"] == 1
        assert _requete(port, "/api/etat")["charge"]["par_projet"] == {"boutique": 1}
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_faux_hote():
    verifier_faux_hote(OUTILS)


MUTATIONS_HOTE = {
    "« déjà N » perdu": ('f"déjà {valeur}"', 'f"deja {valeur}"'),
    "« déjà au défaut » perdu": ('"déjà au défaut"', '"deja"'),
    "message du défaut": ('f"plafond de workers : défaut ({PLAFOND_DEFAUT})"', '"plafond de workers : 3"'),
    "borne haute": ("1 <= valeur <= 8", "1 <= valeur <= 9"),
    "écran qui ne suit pas": ('charge["machine"] = nouveau', "pass"),
    "plafond du projet ignoré": ('charge["source"] = "projet" if projet is not None and projet < nouveau["valeur"] else "machine"', 'charge["source"] = "machine"'),
    "charge inconnu perdu": ('    if nom == "inconnu":\n        return None\n', ""),
    "un actif perdu": ('base.update(workers_actifs=1, par_projet={"boutique": 1})', "pass"),
}


@pytest.mark.parametrize("nom", MUTATIONS_HOTE)
def test_mutation_faux_hote_detectee(nom, tmp_path):
    ancien, nouveau = MUTATIONS_HOTE[nom]
    copie = tmp_path / "outils"
    copie.mkdir()
    texte = (OUTILS / "hote_factice.py").read_text(encoding="utf-8")
    assert ancien in texte, ancien
    (copie / "hote_factice.py").write_text(texte.replace(ancien, nouveau, 1), encoding="utf-8")
    # la copie lit ses fixtures à côté d'elle : on lui redonne les mêmes
    (tmp_path / "fixtures").symlink_to(EXEMPLE_ETAT.parent)
    with pytest.raises((AssertionError, KeyError, TypeError, Exception)):
        verifier_faux_hote(copie)
