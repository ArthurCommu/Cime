"""L'en-tête ne déborde plus entre 761 et 1 280 px.

Pas de navigateur : la preuve est un calcul. Pour chaque largeur de fenêtre, `largeur_minimale` additionne les largeurs minimales des éléments visibles de
l'en-tête, lues dans le CSS de static/style.css (padding, gap, marge, min-width, `display: none` des media queries) ; les largeurs de texte sont estimées
à partir du nombre de caractères : 0,46 em par caractère en police de texte (calibré sur la seule mesure réelle dont on dispose : à 1 024 px avec le faux hôte,
l'ancien CSS demandait ≈ 1 175 px, ce que le même calcul retrouve à 1 % près), 0,60 em en police à chasse fixe (la marque « Cime »), avec tout ce que la page
montre à la fois (« En direct », « ⚠ 12 », « 12 points t’attendent »). Un élément dont le texte peut se tronquer (`min-width: 0` + ellipse)
compte pour sa seule partie fixe ; une règle `nowrap` retirée remet la largeur du texte en entier.

Même convention que test_supervision_coince_dependances.py : `verifier_entete(css, js)` lève AssertionError, la table MUTATIONS prouve qu'elle échoue quand on casse chaque règle.
"""
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "src" / "cime" / "page" / "static"
LARGEURS = (761, 800, 880, 900, 901, 920, 1000, 1024, 1100, 1200, 1280)
SEUIL_EFFECTIFS = 1240  # au-dessous (inclus), les effectifs quittent l'en-tête
SEUIL_INTERVALLES = 1280  # au-dessous (inclus), les intervalles de l'en-tête se resserrent
PLACE_EFFECTIFS = 200  # quand le texte des effectifs est visible, il lui reste au moins ce qu'il faut pour ~30 caractères avant l'ellipse
LARGEURS_NOM_LONG = (761, 780, 800, 820, 840, 880, 900, 901, 920, 1000)  # la plage où « En direct » était écrasé sous « ⚠ n », puis le nom qui devait céder au-dessus de 900 px
NOM_LONG = 40  # caractères du nom de projet long
SEUIL_NOM = 900  # au-dessous (inclus), le nom du projet est masqué ; au-dessus, il se réduit jusqu'à rien par l'ellipse
INTERVALLE_POINTS = 8  # au moins, entre le point des effectifs et celui de « En direct »
MARGE = 24  # ce qu'il reste de libre à chaque largeur du nom long, hors seuil de masquage
EM_TEXTE, EM_MONO = 0.46, 0.60
PASTILLES = {"actif": ("Autonome", "Auto"), "suspendu": ("Autonome suspendu", "Suspendu")}  # (forme longue, forme courte)
SEUIL_PASTILLE = 1100  # au-dessous (inclus), « Auto » / « Suspendu » ; au-dessus, « Autonome » / « Autonome suspendu »
LARGEURS_PASTILLE = (761, 800, 840, 880, 900, 901, 950, 1000, 1100, 1101, 1240, 1241, 1280)  # avec « Autonome suspendu », la plus large, et le compteur d'attentes à son pire


def _texte(chars, taille, mono=False):
    return chars * (EM_MONO if mono else EM_TEXTE) * taille


def _declarations(css, selecteur):
    m = re.search(r"(?:^|\n|\{) *" + re.escape(selecteur) + r" \{([^}]*)\}", css)
    assert m, selecteur
    corps = re.sub(r"/\*.*?\*/", "", m.group(1), flags=re.S)
    resultat = {}
    for d in corps.split(";"):
        if d.strip():
            nom, _, valeur = d.partition(":")
            resultat[nom.strip()] = valeur.strip()
    return resultat


def _media(css, selecteur_corps):
    """Le seuil (max-width) du bloc @media qui contient `selecteur_corps`, ou None."""
    for m in re.finditer(r"@media \(max-width: (\d+)px\) \{\n(.*?)\n\}\n", css, flags=re.S):
        if selecteur_corps in m.group(2):
            return int(m.group(1))
    return None


def _px(valeur):
    return [int(x) for x in re.findall(r"(\d+)px", valeur)]


def _regles_a(css, largeur):
    """decl(selecteur) : les déclarations de base, recouvertes par celles des blocs `@media (max-width: N)` que `largeur` atteint (N ≥ largeur, dont le bloc du téléphone), dans l'ordre du fichier."""
    blocs = [(int(m.start()), int(m.group(1)), m.group(2)) for m in re.finditer(r"@media \(max-width: (\d+)px\) \{\n(.*?)\n\}\n", css, flags=re.S)]

    def decl(selecteur, optionnel=False):
        if optionnel:  # une règle qui n'existe que dans un bloc @media : la base, c'est le CSS sans ses blocs @media
            hors_media = re.sub(r"@media \(max-width: \d+px\) \{\n.*?\n\}\n", "", css, flags=re.S)
            resultat = _declarations(hors_media, selecteur) if re.search(r"(?:^|\n|\{) *" + re.escape(selecteur) + r" \{", hors_media) else {}
        else:
            resultat = _declarations(css, selecteur)
        for _, seuil, corps in blocs:
            if largeur <= seuil:
                for m in re.finditer(r"(?:^|\n) *" + re.escape(selecteur) + r" \{([^}]*)\}", corps):  # toutes les règles du bloc, dans l'ordre
                    for dd in re.sub(r"/\*.*?\*/", "", m.group(1), flags=re.S).split(";"):
                        if dd.strip():
                            nom, _, valeur = dd.partition(":")
                            resultat[nom.strip()] = valeur.strip()
        return resultat
    return decl


def largeur_minimale(css, largeur, nom_long=False, mode_auto=None):
    """(somme des largeurs minimales, place restante pour le texte des effectifs s'il est visible sinon None).

    `nom_long` : le nom du projet fait NOM_LONG caractères. Masqué (`display: none`), il compte pour 0 et l'intervalle de la marque aussi ; sinon, s'il peut céder
    sa place par ellipse il compte pour 0, sinon entier. Il ne cède que si le bloc d'état ne se réduit pas lui-même (sinon les enfants de l'état débordent).
    `mode_auto` : 'actif' ou 'suspendu', la pastille « Autonome » / « Autonome suspendu » de l'en-tête est là (écrite « Auto » / « Suspendu » quand le CSS cache la forme longue).
    """
    d = _regles_a(css, largeur)
    seuil_effectifs = _media(css, ".entete .effectifs-texte { display: none; }")
    effectifs_visibles = seuil_effectifs is None or largeur > seuil_effectifs
    entete = d(".entete")
    gap_entete = _px(entete["gap"])[1]
    padding = _px(entete["padding"])[-1] * 2
    # la marque : « Cime » en police fixe, le nom du projet peut se réduire à rien (min-width: 0 + ellipse), la marge la sépare des onglets
    titres = d(".entete-titres")
    h1 = d(".entete h1")
    masque = h1.get("display") == "none"
    etat_decl = d(".entete-etat")
    cede = (h1.get("min-width") == "0" and h1.get("overflow") == "hidden" and "ellipsis" in h1.get("text-overflow", "")
            and (etat_decl.get("flex") == "none" or effectifs_visibles))
    if masque:
        nom_projet, gap_nom = 0, 0
    else:
        nom_projet, gap_nom = (0 if cede else _texte(NOM_LONG if nom_long else 18, 13)), _px(titres["gap"])[0]
    marque = _texte(4, 18, mono=True) + gap_nom + nom_projet + (_px(titres.get("margin-right", "0"))[0:1] or [0])[0]
    # les onglets : 3 liens à 14 px (Scène, Supervision, Fil), chacun avec son padding horizontal, séparés par le gap de .nav
    nav = d(".nav")
    pad_lien = _px(d(".nav a")["padding"])[-1] * 2
    onglets = sum(_texte(n, 14) + pad_lien for n in (5, 11, 3)) + (_px(nav["gap"]) or [0])[0] * 2
    # le bloc d'état
    etat = d(".entete-etat")
    gap_etat = _px(etat["gap"])[1]
    pastille = 10  # le point coloré (8 px, 14 px à l'état inconnu) et sa marge
    effectifs_texte = d(".effectifs-texte")
    texte_effectifs = _texte(64, 13)  # « 4 travaillent · 3 au repos · 5 attendent · 1 à l’arrêt · 1 arrêté »
    tronquable = (etat.get("min-width") == "0" and effectifs_texte.get("min-width") == "0" and "ellipsis" in effectifs_texte.get("text-overflow", "")
                  and d(".entete-etat .pilule").get("min-width") == "0" and d(".entete-etat .pilule").get("flex") != "none")
    effectifs_fixe = pastille + (8 if effectifs_visibles else 0)
    effectifs_total = effectifs_fixe + (0 if (not effectifs_visibles or tronquable) else texte_effectifs)
    trait = d('.entete-etat .pilule[role="img"]::after', optionnel=True)  # le trait entre le point des effectifs et « En direct » : sans texte, il reste à côté du point
    if not effectifs_visibles and trait.get("width"):
        effectifs_total += _px(trait["width"])[0] + _px(d(".pilule")["gap"])[-1]
    elements = [effectifs_total]
    elements.append(_texte(9, 13) + 8 + 8)  # « En direct » + le pouls et son espace (nowrap : .nav a, .pilule)
    sources = d(".sources-echec")  # « ⚠ 12 »
    elements.append((_px(sources["padding"])[-1] * 2 + 2) + (_texte(4, 12) if "nowrap" in sources.get("white-space", "") else _texte(1, 12)))
    if mode_auto:  # le mode autonome est actif : sa pastille, sans réduction possible (flex: none) ni coupure (nowrap)
        mode = d(".pastille-auto")
        longue = d(".pastille-long").get("display") != "none"
        mots = PASTILLES[mode_auto][0 if longue else 1]
        elements.append((_px(mode["padding"])[-1] * 2 + 2) + (_texte(len(mots), 12) if "nowrap" in mode.get("white-space", "") else _texte(max(len(m) for m in mots.split()), 12)))
    compteur = d(".compteur-attentes")  # « 12 points t’attendent »
    elements.append((_px(compteur["padding"])[-1] * 2 + 2) + (_texte(22, 12) if "nowrap" in compteur.get("white-space", "") else _texte(8, 12)))
    bouton = d(".bouton")  # « Demander à l’Assistant »
    icone_seule = d(".entete .demander-texte", optionnel=True).get("display") == "none"  # sous 900 px « Demander à l'Assistant » n'est que son icône
    if icone_seule:
        elements.append(_px(d(".entete .demander", optionnel=True).get("width", "0px"))[0])
    else:
        elements.append((_px(bouton["padding"])[-1] * 2 + 2) + (_texte(22, 13) if "nowrap" in d(".demander").get("white-space", "") else _texte(10, 13)))
    bloc_etat = sum(elements) + gap_etat * (len(elements) - 1)
    total = padding + marque + onglets + bloc_etat + gap_entete * 2
    place = None
    if effectifs_visibles:
        place = largeur - (total - effectifs_total + effectifs_fixe)
    return total, place


def verifier_entete(css, commun):
    # 1. effectifs masqués jusqu'à 1 240 px, le point garde le texte en title et aria-label
    seuil = _media(css, ".entete .effectifs-texte { display: none; }")
    assert seuil is not None and seuil >= SEUIL_EFFECTIFS, seuil
    assert css.count(".entete .effectifs-texte { display: none; }") == 1
    resume = commun[commun.index("export function resumeAgents(etat)"):commun.index("function niveauAge")]
    assert "title: phrase" in resume and "'aria-label': phrase" in resume and "role: 'img'" in resume, "le point doit redire les effectifs"
    assert "const phrase = libelleEffectifs(compte)" in resume and "}, phrase)" in resume
    # 2. nowrap sur la pastille d'alarmes, le compteur et le bouton
    for sel in (".sources-echec", ".compteur-attentes", ".demander"):
        assert "nowrap" in _declarations(css, sel).get("white-space", ""), sel
    # 3. un espace fixe entre la marque et les onglets, indépendant du nom du projet
    marge = _declarations(css, ".entete-titres").get("margin-right", "")
    assert _px(marge) and _px(marge)[0] >= 16, marge
    assert "margin-right: 0" in css[css.index("@media (max-width: 760px)"):]  # le bloc mobile reste seul et inchangé
    # 4. le bloc d'état se réduit et tronque les effectifs ; l'intervalle se resserre jusqu'à 1 280 px
    assert _declarations(css, ".entete-etat").get("min-width") == "0"
    assert _declarations(css, ".entete-etat .pilule").get("min-width") == "0"
    # 4b. sous 1 240 px la pilule des effectifs n'est que son point : elle ne se réduit pas en dessous, et un intervalle d'au moins 8 px la sépare de « En direct »
    for largeur in (761, 880, 901, 1000, 1240):
        d = _regles_a(css, largeur)
        assert d(".entete-etat .pilule").get("flex") == "none", f"{largeur} px : la pilule des effectifs se réduit sous son point"
        assert d(".entete-etat").get("flex") == "none", f"{largeur} px : le bloc d'état se réduit au lieu de laisser le nom céder"
        assert _px(d(".entete-etat")["gap"])[1] >= INTERVALLE_POINTS, largeur
    assert _regles_a(css, 1241)(".entete-etat .pilule").get("flex") != "none"  # au-dessus, l'ellipse du texte des effectifs joue
    assert _regles_a(css, 1241)(".entete-etat").get("flex") != "none"
    # 4c. sous 900 px le nom du projet est masqué (il reste dans document.title), au-dessus l'ellipse
    assert _regles_a(css, SEUIL_NOM)(".entete h1").get("display") == "none"
    assert _regles_a(css, SEUIL_NOM + 1)(".entete h1").get("display") != "none"
    assert _media(css, ".entete h1 { display: none; }") == SEUIL_NOM
    assert "document.title = `${ctx.etat.projet.nom} · Cime`" in commun
    ell = _declarations(css, ".effectifs-texte")
    assert ell.get("min-width") == "0" and ell.get("overflow") == "hidden" and ell.get("text-overflow") == "ellipsis" and "nowrap" in ell.get("white-space", ""), ell
    gap = _media(css, ".entete { gap: 8px 16px; }")
    assert gap is not None and gap >= SEUIL_INTERVALLES, gap
    assert css.count("@media (max-width: 1280px)") == 1 and css.count("@media (max-width: 1240px)") == 1 and css.count("@media (max-width: 900px)") == 1
    # au-dessus de 1 280 px rien ne change : les intervalles de base restent 8 px 32 px
    assert _declarations(css, ".entete")["gap"] == "8px 32px"
    # 5. le calcul : tout tient dans la fenêtre à chaque largeur de la plage
    for largeur in LARGEURS:
        total, place = largeur_minimale(css, largeur)
        assert total <= largeur, f"{largeur} px : l'en-tête demande {total:.0f} px"
        assert place is None or place >= PLACE_EFFECTIFS, f"{largeur} px : {place:.0f} px pour les effectifs"
    # 6. nom de projet long : la pastille « En direct » ne se réduit ni ne se coupe, et tout tient, le nom étant masqué sous 900 px et s'abrégeant par ellipse au-dessus
    h1 = _declarations(css, ".entete h1")
    assert h1.get("min-width") == "0" and h1.get("overflow") == "hidden" and "ellipsis" in h1.get("text-overflow", ""), h1
    pastille = _declarations(css, ".age-donnee")
    assert pastille.get("flex") == "none" and "nowrap" in pastille.get("white-space", ""), pastille
    for largeur in LARGEURS_NOM_LONG:
        total, _ = largeur_minimale(css, largeur, nom_long=True)
        assert total <= largeur, f"nom long, {largeur} px : l'en-tête demande {total:.0f} px"
        if largeur > SEUIL_NOM:
            assert total <= largeur - MARGE, f"nom long, {largeur} px : l'en-tête demande {total:.0f} px, moins de {MARGE} px de marge"
    # 7. la pastille du mode autonome : ni coupée ni réduite, « Autonome suspendu » (la plus large) avec le compteur d'attentes à son pire,
    # écrite « Auto » / « Suspendu » jusqu'à 1 100 px ; sous 900 px « Demander à l'Assistant » n'est que son icône
    mode = _declarations(css, ".pastille-auto")
    assert "nowrap" in mode.get("white-space", "") and mode.get("flex") == "none", mode
    assert _regles_a(css, SEUIL_PASTILLE)(".pastille-long", optionnel=True).get("display") == "none"
    assert _regles_a(css, SEUIL_PASTILLE)(".pastille-court", optionnel=True).get("display") == "inline"
    assert _regles_a(css, SEUIL_PASTILLE + 1)(".pastille-long", optionnel=True).get("display") != "none"  # au-dessus, la forme longue
    assert _regles_a(css, SEUIL_PASTILLE + 1)(".pastille-court", optionnel=True).get("display") == "none"
    assert _media(css, ".pastille-long { display: none; }") == SEUIL_PASTILLE
    assert _regles_a(css, SEUIL_NOM)(".entete .demander-texte", optionnel=True).get("display") == "none"
    assert _regles_a(css, SEUIL_NOM + 1)(".entete .demander-texte", optionnel=True).get("display") != "none"
    assert _regles_a(css, SEUIL_NOM)(".entete .demander", optionnel=True).get("width") == "40px"
    assert _regles_a(css, SEUIL_NOM)(".entete .demander-icone", optionnel=True).get("display") == "block"  # l'icône prend la place du texte
    for etat_mode in ("actif", "suspendu"):
        for largeur in LARGEURS_PASTILLE:
            for nom_long in (False, True):
                total, place = largeur_minimale(css, largeur, nom_long=nom_long, mode_auto=etat_mode)
                assert total <= largeur, f"pastille {etat_mode}, nom long {nom_long}, {largeur} px : l'en-tête demande {total:.0f} px"
                assert place is None or place >= PLACE_EFFECTIFS, f"pastille {etat_mode}, {largeur} px : {place:.0f} px pour les effectifs"
    # le calcul compte bien : sans les règles, une largeur échoue (garde de la garde)
    assert largeur_minimale(css, 1280)[0] > largeur_minimale(css, 761)[0]


@pytest.fixture(scope="module")
def sources():
    return (STATIC / "style.css").read_text(encoding="utf-8"), (STATIC / "commun.js").read_text(encoding="utf-8")


def test_entete_largeur(sources):
    verifier_entete(*sources)


def test_les_largeurs_utiles(sources):
    totaux = {w: largeur_minimale(sources[0], w) for w in LARGEURS}
    assert all(t <= w for w, (t, _) in totaux.items()), totaux


def _css(ancien, nouveau):
    def mutation(s):
        assert ancien in s[0], ancien
        return s[0].replace(ancien, nouveau, 1), s[1]
    return mutation


def _js(ancien, nouveau):
    def mutation(s):
        assert ancien in s[1], ancien
        return s[0], s[1].replace(ancien, nouveau, 1)
    return mutation


MUTATIONS = {
    "seuil des effectifs à 1 000": _css("@media (max-width: 1240px)", "@media (max-width: 1000px)"),
    "seuil des effectifs à 1 100": _css("@media (max-width: 1240px)", "@media (max-width: 1100px)"),
    "effectifs jamais masqués": _css("  .entete .effectifs-texte { display: none; }", "  .entete .effectifs-texte { display: inline; }"),
    "intervalles resserrés seulement à 1 000": _css("@media (max-width: 1280px)", "@media (max-width: 1000px)"),
    "bloc 900 px retiré": _css("@media (max-width: 900px) {\n  .entete { gap: 8px 8px; padding: 0 12px; }", "@media (max-width: 500px) {\n  .entete { gap: 8px 8px; padding: 0 12px; }"),
    "pastille ⚠ sans nowrap": _css("font-size: 12px; font-weight: 600; white-space: nowrap; flex: none;\n}\n.compteur", "font-size: 12px; font-weight: 600; flex: none;\n}\n.compteur"),
    "compteur sans nowrap": _css("padding: 0 12px; white-space: nowrap;\n  background: var(--ambre-fond)", "padding: 0 12px;\n  background: var(--ambre-fond)"),
    "bouton sans nowrap": _css(".demander { white-space: nowrap; flex: none; }", ".demander { flex: none; }"),
    "marque collée aux onglets": _css(" margin-right: 16px; white-space: nowrap; }", " white-space: nowrap; }"),
    "marge de la marque trop courte": _css("min-width: 0; margin-right: 16px;", "min-width: 0; margin-right: 4px;"),
    "marge de la marque aussi au mobile": _css("  .entete-titres { flex: 1; min-width: 0; margin-right: 0; }", "  .entete-titres { flex: 1; min-width: 0; }"),
    "bloc d'état qui ne se réduit pas": _css(".entete-etat { margin-left: auto; min-width: 0;", ".entete-etat { margin-left: auto;"),
    "pastille d'effectifs qui ne se réduit pas": _css(".entete-etat .pilule { min-width: 0; }\n", ""),
    "nom du projet non masqué sous 900 px": _css("  .entete h1 { display: none; }", "  .entete h1 { display: block; }"),
    "masquage du nom retiré": _css("  .entete h1 { display: none; } /* le nom", "  /* le nom"),
    "pastille des effectifs qui se réduit sous 1 240 px": _css("  .entete-etat .pilule { flex: none; }", "  .entete-etat .pilule { flex: 0 1 auto; }"),
    "bloc d'état qui se réduit sous 1 240 px": _css("  .entete-etat { flex: none; } /* le bloc", "  .entete-etat { flex: 0 1 auto; } /* le bloc"),
    "nom non réductible (min-width)": _css(".entete h1 { margin: 0; min-width: 0; overflow", ".entete h1 { margin: 0; overflow"),
    "nom non réductible (overflow)": _css("min-width: 0; overflow: hidden; text-overflow: ellipsis; font-size: 13px", "min-width: 0; text-overflow: ellipsis; font-size: 13px"),
    "titre de l'onglet sans le nom": _js("document.title = `${ctx.etat.projet.nom} · Cime`", "document.title = 'Cime'"),
    "intervalle des points trop court": _css("  .entete-etat { gap: 8px 10px; }", "  .entete-etat { gap: 8px 4px; }"),
    "effectifs sans ellipse": _css(".effectifs-texte { min-width: 0; overflow: hidden; text-overflow: ellipsis;", ".effectifs-texte { min-width: 0; overflow: hidden;"),
    "effectifs sans min-width: 0": _css(".effectifs-texte { min-width: 0; overflow", ".effectifs-texte { overflow"),
    "intervalle de base changé": _css("display: flex; align-items: center; gap: 8px 32px;\n  padding: 0 20px;", "display: flex; align-items: center; gap: 8px 24px;\n  padding: 0 20px;"),
    "title des effectifs perdu": _js("role: 'img', title: phrase, 'aria-label': phrase", "role: 'img', 'aria-label': phrase"),
    "aria-label des effectifs perdu": _js("role: 'img', title: phrase, 'aria-label': phrase", "role: 'img', title: phrase"),
    "role du point perdu": _js("role: 'img', title: phrase, 'aria-label': phrase", "title: phrase, 'aria-label': phrase"),
    "pastille « En direct » qui se réduit": _css(".age-donnee { font-weight: 500; white-space: nowrap; flex: none; }", ".age-donnee { font-weight: 500; white-space: nowrap; }"),
    "pastille « En direct » sans nowrap": _css(".age-donnee { font-weight: 500; white-space: nowrap; flex: none; }", ".age-donnee { font-weight: 500; flex: none; }"),
    "pastille du mode autonome sans nowrap": _css("align-items: center; height: 28px; padding: 0 10px; white-space: nowrap; flex: none;\n  border: 1px solid;", "align-items: center; height: 28px; padding: 0 10px; flex: none;\n  border: 1px solid;"),
    "pastille du mode autonome qui se réduit": _css("align-items: center; height: 28px; padding: 0 10px; white-space: nowrap; flex: none;\n  border: 1px solid;", "align-items: center; height: 28px; padding: 0 10px; white-space: nowrap;\n  border: 1px solid;"),
    "forme longue gardée sous 1 100 px": _css("  .pastille-long { display: none; }\n", "  .pastille-long { display: inline; }\n"),
    "forme courte absente sous 1 100 px": _css("  .pastille-court { display: inline; }\n", ""),
    "forme courte seulement sous 950 px": _css("@media (max-width: 1100px) {\n  .entete-etat", "@media (max-width: 950px) {\n  .entete-etat"),
    "intervalles de l'état non resserrés à 1 100 px": _css("  .entete-etat { gap: 8px 10px; }\n  .pastille-auto", "  .pastille-auto"),
    "Demander garde son texte sous 900 px": _css("  .entete .demander-texte { display: none; }\n", ""),
    "Demander sans largeur sous 900 px": _css("  .entete .demander { width: 40px; height: 40px;", "  .entete .demander { height: 40px;"),
    "icône de Demander cachée sous 900 px": _css("  .entete .demander-icone { display: block; }\n", ""),
    "nom de projet sans ellipse": _css(".entete h1 { margin: 0; min-width: 0; overflow: hidden; text-overflow: ellipsis;", ".entete h1 { margin: 0; min-width: 0; overflow: hidden;"),
}


@pytest.mark.parametrize("nom", MUTATIONS)
def test_mutation_detectee(nom, sources):
    mutee = MUTATIONS[nom](sources)  # hors du raises : la mutation doit s'appliquer, sinon le test serait faux
    with pytest.raises(AssertionError):
        verifier_entete(*mutee)


def test_couverture_des_verifications():
    toutes = {n for n, v in globals().items() if n.startswith("verifier_") and callable(v)}
    assert toutes == {"verifier_entete"} and MUTATIONS, sorted(toutes)
