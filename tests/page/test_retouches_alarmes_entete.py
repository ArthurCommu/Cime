"""Sept retouches ciblées de la Supervision et de l'en-tête.

1. le nom du projet au téléphone : calcul à 320–360 px (pire cas : « ⚠ n », « Suspendu », « En direct », « Demander »). Il ne tient pas : le nom reste masqué ;
2. les lignes groupées de « Ce qui coince » : même titre que les lignes simples, plus un chevron ;
3. au téléphone, les groupes et « Info ×n » ont les retraits des lignes simples (bloc 760 px) ;
4. « Quoi faire » : seul le libellé est en gras dans une info dépliée ;
5. « À trancher » (ambre) à la place de « Grave » pour une attente grave de l'utilisateur, partout où le mot s'affiche ;
6. libellés en français clair pour les types sans libellé : tout type d'alarme connu en a un, de 40 caractères au plus ;
7. un trait entre le point des effectifs et « En direct » sous 1 240 px (la largeur du trait est comptée dans test_entete_largeur).

Même convention que test_supervision_coince_dependances.py : `verifier_retouches(...)` lève AssertionError ; la table MUTATIONS prouve qu'elle échoue quand on casse chaque retouche.
Node sert à exécuter `motAlarme` (sauté s'il est absent).
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))  # pour réutiliser le calcul de largeur de test_entete_largeur
from test_entete_largeur import _px, _regles_a, _texte  # noqa: E402

RACINE = Path(__file__).resolve().parents[2]
STATIC = RACINE / "src" / "cime" / "page" / "static"
# Tous les types d'alarme que l'hôte peut émettre.
TYPES_ALARME = (
    "autorisation_en_attente|question_sans_reponse|recouvrement|brouillon|contexte_plein|hors_perimetre|retard_sur_base|session_disparue|"
    "action_refusee|bloque_au_demarrage|fige|session_orpheline|gros_poste|contexte_au_repos|assistant_sourd|livraison_echouee|"
    "livraison_bloquee|facteur_arrete|fin_sans_suite"
)

NOM_MINI = 48  # px libres pour le nom du projet (« / », cinq caractères et l'ellipse) : en dessous il ne se lit pas
TELEPHONE = (320, 360)  # le plus étroit des téléphones, puis le seuil de la décision
LIBELLE_MAX = 40  # caractères, pour un libellé d'alarme

SONDE = r"""
import { pathToFileURL } from 'node:url';
const m = await import(pathToFileURL(process.argv[2]).href);
const cas = [
  { gravite: 'grave', type: 'autorisation_en_attente' },
  { gravite: 'grave', type: 'question_sans_reponse' },
  { gravite: 'grave', type: 'recouvrement' },
  { gravite: 'a_voir', type: 'autorisation_en_attente' },
  { gravite: 'info', type: 'fige' },
];
console.log(JSON.stringify(cas.map((a) => m.motAlarme(a))));
"""


def _bloc(texte, debut):
    """Le texte de `debut` jusqu'à la prochaine accolade fermante, comprise."""
    i = texte.find(debut)
    assert i >= 0, debut
    return texte[i:texte.index("}", i) + 1]


def _libelles(js):
    corps = js[js.index("export const TYPES_ALARME = {"):]
    corps = corps[:corps.index("\n};")]
    return dict(re.findall(r"(\w+): '([^']+)'", corps))


def espace_telephone(css, largeur, mode="suspendu", sources=True):
    """(largeur des éléments fixes de l'en-tête, place restante pour le nom du projet s'il était affiché) — pire cas au téléphone."""
    d = _regles_a(css, largeur)
    assert ".entete-etat .pilule:not(.age-donnee) { display: none; }" in css, "le point des effectifs doit être masqué au téléphone"
    padding = _px(d(".entete")["padding"])[-1] * 2
    gap_entete = _px(d(".entete")["gap"])[-1]
    gap_pilule = _px(d(".pilule")["gap"])[-1]
    etat_gap = _px(d(".entete-etat")["gap"])[-1]
    elements = [_texte(9, 13) + 8 + gap_pilule]  # « En direct » et son pouls (le point des effectifs est masqué, le compteur aussi)
    if sources:  # « ⚠ 2 », nowrap
        elements.append(_px(d(".sources-echec")["padding"])[-1] * 2 + 2 + _texte(4, 12))
    if mode:  # « Auto » ou « Suspendu » : la forme courte, sous 1 100 px
        mots = {"actif": "Auto", "suspendu": "Suspendu"}[mode]
        elements.append(_px(d(".pastille-auto")["padding"])[-1] * 2 + 2 + _texte(len(mots), 12))
    elements.append(_px(d(".demander")["width"])[0])  # l'icône seule, 40 px
    etat = sum(elements) + etat_gap * (len(elements) - 1)
    marque = _texte(4, 18, mono=True) + _px(d(".entete-titres")["gap"])[0]  # le nom, s'il était là, est séparé de « Cime » par le gap de la marque
    fixes = padding + marque + gap_entete + etat
    return fixes, largeur - fixes


def verifier_retouches(css, js, ens, types, dossier=None):
    # 1. le nom reste masqué au téléphone : à 320 et 360 px (pire cas), l'en-tête n'a pas NOM_MINI px pour lui
    for largeur in TELEPHONE:
        d = _regles_a(css, largeur)
        assert d(".entete h1").get("display") == "none", f"{largeur} px : le nom du projet est affiché au téléphone"
        _, place = espace_telephone(css, largeur)
        assert place < NOM_MINI, f"{largeur} px : {place:.0f} px pour le nom, il tiendrait : revoir la décision"
    # 2. les groupes ont un chevron au bout de leur titre, pointe à droite replié, en bas déplié
    assert ".alarme-groupe > summary .al-quoi, .alarme-groupe > summary .groupe-resume { color: var(--texte); font-weight: 500; }" in css
    assert ".alarme-groupe > summary .al-quoi { font-size: 14px; }" in css
    chevron = _bloc(css, ".alarme-groupe > summary .al-quoi::after, .alarme-groupe > summary .groupe-resume::after {")
    assert "border-right: 2px solid currentColor; border-bottom: 2px solid currentColor;" in chevron
    assert "content: ''; display: inline-block; width: 6px; height: 6px;" in chevron and "transform: rotate(-45deg);" in chevron
    assert ".alarme-groupe[open] > summary .al-quoi::after, .alarme-groupe[open] > summary .groupe-resume::after { transform: rotate(45deg); }" in css
    # 3. au téléphone : le groupe ne garde pas le retrait de .al, et « Info ×n » a le retrait des lignes simples
    tel = css[css.index("@media (max-width: 760px)"):]
    simple = ".al, .alarme-groupe > summary { grid-template-columns: minmax(0, 1fr) auto; padding: 12px 14px; }"
    cadre = ".alarme-groupe { padding: 0; }"
    info = ".alarme-groupe:not(.groupe-probleme) > summary { padding: 12px 14px; }"
    assert simple in tel and cadre in tel and info in tel, "une règle mobile des groupes manque"
    assert tel.index(simple) < tel.index(cadre) < tel.index(info), "les règles mobiles des groupes sont dans le désordre"
    # 4. « Quoi faire » : seul le libellé est en gras, pas le texte d'une info dépliée
    assert ".groupe-alarme .alarme-quoi { font-weight: 400; }" in css
    # 5. « À trancher » pour une attente grave ; le mot passe par motAlarme partout où « Grave » s'affichait
    corps = _bloc(js, "export function motAlarme(alarme) {")
    assert "if (TYPES_ALARME_ATTENTE.includes(alarme.type) && (GRAVITES[alarme.gravite] || GRAVITES.info) === GRAVITES.grave) return 'À trancher';" in corps, corps
    assert "return (GRAVITES[alarme.gravite] || GRAVITES.info).mot;" in corps
    assert "el('span', { class: 'alarme-gravite' }, motAlarme(a))" in js, "la fiche équipe n'utilise pas motAlarme"
    assert "el('span', { class: 'probleme-mot' }, motAlarme(a))" in ens, "la Supervision n'utilise pas motAlarme"
    if dossier is not None and shutil.which("node"):
        assert executer_motalarme(js, dossier) == ["À trancher", "À trancher", "Grave", "À voir", "Info"]
    # 6. un libellé pour chaque type d'alarme, de LIBELLE_MAX caractères au plus
    libelles = _libelles(js)
    manquants = [t for t in types.split("|") if t not in libelles]
    assert not manquants, f"types sans libellé : {manquants}"
    trop_longs = {t: v for t, v in libelles.items() if len(v) > LIBELLE_MAX}
    assert not trop_longs, trop_longs
    # 7. un trait de 1 px et 14 px entre le point des effectifs et « En direct », sous 1 240 px, et rien au-dessus
    trait = '.entete-etat .pilule[role="img"]::after { content: \'\'; width: 1px; height: 14px; background: var(--discret); }'
    assert trait in css
    assert _regles_a(css, 1240)('.entete-etat .pilule[role="img"]::after', optionnel=True).get("width") == "1px"
    assert _regles_a(css, 1241)('.entete-etat .pilule[role="img"]::after', optionnel=True).get("width") is None


def executer_motalarme(js, dossier):
    """motAlarme exécuté par node, sur une copie de static/ dont commun.js est `js`."""
    copie = dossier / "static-motalarme"
    if copie.exists():
        shutil.rmtree(copie)
    shutil.copytree(STATIC, copie)
    (copie / "commun.js").write_text(js, encoding="utf-8")
    sonde = copie / "sonde-retouches.mjs"
    sonde.write_text(SONDE, encoding="utf-8")
    res = subprocess.run(["node", str(sonde), str(copie / "commun.js")], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def sources():
    return (
        (STATIC / "style.css").read_text(encoding="utf-8"),
        (STATIC / "commun.js").read_text(encoding="utf-8"),
        (STATIC / "vues" / "ensemble.js").read_text(encoding="utf-8"),
        TYPES_ALARME,
    )


def test_retouches_alarmes_entete(sources, tmp_path):
    verifier_retouches(*sources, dossier=tmp_path)


def test_le_nom_au_telephone_ne_tient_pas(sources):
    # la décision : à 320 px le pire cas laisse moins de NOM_MINI px ; à 360 px aussi. Le nom reste donc masqué.
    fixes, place = espace_telephone(sources[0], 320)
    assert place < NOM_MINI and fixes > 300, (fixes, place)


def _css(ancien, nouveau):
    def mutation(s):
        assert ancien in s[0], ancien
        return (s[0].replace(ancien, nouveau, 1),) + tuple(s[1:])
    return mutation


def _js(ancien, nouveau):
    def mutation(s):
        assert ancien in s[1], ancien
        return (s[0], s[1].replace(ancien, nouveau, 1)) + tuple(s[2:])
    return mutation


def _ens(ancien, nouveau):
    def mutation(s):
        assert ancien in s[2], ancien
        return s[:2] + (s[2].replace(ancien, nouveau, 1),) + tuple(s[3:])
    return mutation


def _types(ancien, nouveau):
    def mutation(s):
        assert ancien in s[3], ancien
        return s[:3] + (s[3].replace(ancien, nouveau, 1),)
    return mutation


MUTATIONS = {
    "nom affiché au téléphone": _css("  .entete h1::before { margin-right: 6px; }", "  .entete h1 { display: block; }\n  .entete h1::before { margin-right: 6px; }"),
    "chevron des groupes absent": _css(".alarme-groupe > summary .al-quoi::after, .alarme-groupe > summary .groupe-resume::after {\n  content: '';", ".alarme-groupe > summary .al-quoi::after, .alarme-groupe > summary .groupe-resume::after {\n  content: none;"),
    "chevron replié vers le bas": _css("transform: rotate(-45deg);\n}\n.alarme-groupe[open]", "transform: rotate(45deg);\n}\n.alarme-groupe[open]"),
    "chevron déplié non tourné": _css(".alarme-groupe[open] > summary .al-quoi::after, .alarme-groupe[open] > summary .groupe-resume::after { transform: rotate(45deg); }", ""),
    "titre des groupes éteint": _css(".alarme-groupe > summary .al-quoi, .alarme-groupe > summary .groupe-resume { color: var(--texte); font-weight: 500; }", ".alarme-groupe > summary .al-quoi, .alarme-groupe > summary .groupe-resume { font-weight: 500; }"),
    "retrait doublé au téléphone": _css("  .alarme-groupe { padding: 0; }\n", ""),
    "« Info ×n » sans les retraits des lignes simples": _css("  .alarme-groupe:not(.groupe-probleme) > summary { padding: 12px 14px; }\n", ""),
    "texte de « Quoi faire » en gras": _css(".groupe-alarme .alarme-quoi { font-weight: 400; }", ""),
    "« Grave » écrit pour une attente": _js("return 'À trancher';", "return 'Grave';"),
    "fiche équipe avec « Grave » en dur": _js("el('span', { class: 'alarme-gravite' }, motAlarme(a))", "el('span', { class: 'alarme-gravite' }, GRAVITES[a.gravite].mot)"),
    "Supervision avec « Grave » en dur": _ens("el('span', { class: 'probleme-mot' }, motAlarme(a))", "el('span', { class: 'probleme-mot' }, GRAVITES[a.gravite].mot)"),
    "libellé de fin_sans_suite absent": _js("  fin_sans_suite: 'Agent arrêté avec une obligation ouverte',\n", ""),
    "libellé trop long": _js("livraison_echouee: 'Courrier échoué'", "livraison_echouee: 'Courrier qui n’a pas pu être remis à son destinataire'"),
    "trait des effectifs retiré": _css(".entete-etat .pilule[role=\"img\"]::after { content: ''; width: 1px; height: 14px; background: var(--discret); }", ""),
    "type d'alarme sans libellé": _types("|fin_sans_suite", "|fin_sans_suite|type_inconnu"),
}


@pytest.mark.parametrize("nom", MUTATIONS)
def test_mutation_detectee(nom, sources, tmp_path):
    mutee = MUTATIONS[nom](sources)  # hors du raises : la mutation doit s'appliquer, sinon le test serait faux
    with pytest.raises(AssertionError):
        verifier_retouches(*mutee, dossier=tmp_path)


def test_couverture_des_verifications():
    toutes = {n for n, v in globals().items() if n.startswith("verifier_") and callable(v)}
    assert toutes == {"verifier_retouches"} and MUTATIONS, sorted(toutes)
