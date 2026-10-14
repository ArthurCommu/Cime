"""Garde-fous de la page (index.html et static/) : elle ne propose que les prérogatives de l'utilisateur.

Vérifie qu'aucun bouton retiré ne réapparaît, que la phrase de hiérarchie est présente, qu'aucune ressource externe hors
Google Fonts n'est chargée, que la page n'appelle que les routes /api/… de l'hôte, en URL relatives, et que seule la couche
de données (static/source.js) parle au réseau. Les constantes et la détection de chaînes interdites servent aussi à d'autres tests.
"""

import re
from pathlib import Path

import pytest

PAGE = Path(__file__).resolve().parents[2] / "src" / "cime" / "page"
STATIC = PAGE / "static"
EXTENSIONS = {".html", ".js", ".css"}

CHAINES_INTERDITES = [
    "pause",
    "relance",
    "compact",
    "fusion",
    "push",
    "lancer un worker",
    "effacer",
    "masquer",
    "valider",
    "à l'assistant",
    "demander une",
    "demander un",
    "envoyer",
]
PHRASE_AUTORISEE = "pour leur demander quelque chose, passe par l'assistant"
# autorisation d'un agent sans session connue : la page n'envoie rien
PHRASE_TERMINAL = "la page ne peut pas y envoyer de touche"
# « Refuser » dit sa conséquence avant d'agir (la page ne relance rien)
PHRASE_REFUS = "refuser arrête l'agent jusqu'à ce que l'assistant le relance"
# accorder une fusion ou un chantier est une prérogative de l'utilisateur ; le mot « fusion » n'est permis que dans ce bouton
# et dans le préfixe d'objet `fusion:`.
PHRASES_ACCORD = ("accorder la fusion", "fusion:")
# L'interrupteur « Mode autonome » est une prérogative de l'utilisateur ; ces phrases exactes, et seulement elles, portent le mot
# « fusion » (les phrases de l'interface, les noms des champs), et deux phrases portent « push » (« Toujours, hors chemins »).
# Aucun assouplissement général : « fusion », « fusionne », « push » seuls restent interdits.
PHRASES_MODE_AUTONOME = (
    "fusionne à ta place",  # « L'Assistant fusionne à ta place » (encadré actif, ligne inactive, toast d'activation)
    "suspendu, fusions arrêtées",  # titre de l'encadré suspendu
    "chaque fusion revient à ton accord",  # encadré suspendu, toast de désactivation
    "aucune fusion encore",  # encadré actif sans dernière action
    "push, suppression de branche",  # dernière ligne de la liste dépliée
    "push et branches",  # phrase affichée mode inactif
    "fusions_auto",  # le champ de l'état et l'action du journal
    "derniere_fusion",  # le champ `fusions_auto.derniere_fusion`
    "fusions-auto",  # la route /api/actions/fusions-auto
    "{ genre: 'fusion', un: 'fusion', plusieurs: 'fusions', verbe: 'fusionnée' }",  # la ligne « fusion » de GENRES_DECISION (le récap du matin)
)
# la page formule une demande à l'Assistant, jamais à un coordinateur.
PHRASE_DEMANDE = "demander à l'assistant"
PHRASE_OBLIGATOIRE = "ne peut pas écrire aux agents"
HOTES_AUTORISES = {"fonts.googleapis.com", "fonts.gstatic.com"}

# Les routes de l'hôte, paramètres remplacés par {}.
ROUTES_DE_L_HOTE = {
    "/api/etat",
    "/api/flux",
    "/api/journal?limite={}",
    "/api/agents/{}/terminal",
    "/api/fichier?chemin={}",
    "/api/actions/autoriser",
    "/api/actions/refuser",
    "/api/actions/accorder",
    "/api/actions/trancher",
    "/api/actions/deposer",
    "/api/actions/lu",
    "/api/actions/cloturer",
    "/api/actions/demander",
    "/api/actions/fusions-auto",  # le mode autonome, prérogative de l'utilisateur
    "/api/actions/plafond",  # le plafond de workers de la machine, prérogative de l'utilisateur
}

RE_URL = re.compile(r"""(?:https?:)?//([a-z0-9.-]+\.[a-z]{2,})""", re.IGNORECASE)
RE_ROUTE = re.compile(r"""(['"`])(/api/[^'"`]*)\1""")
RE_PARAMETRE = re.compile(r"\$\{[^}]*\}")
RE_RESEAU = re.compile(r"\b(fetch|EventSource|XMLHttpRequest|WebSocket|sendBeacon)\s*\(")
RE_IMPORT = re.compile(r"""^import\s.*?from\s+'([^']+)';""", re.MULTILINE | re.DOTALL)


def normaliser(texte: str) -> str:
    return texte.lower().replace("’", "'")


def chaines_interdites(texte: str) -> list[str]:
    propre = normaliser(texte)
    for phrase in (PHRASE_AUTORISEE, PHRASE_TERMINAL, PHRASE_REFUS, PHRASE_DEMANDE, *PHRASES_ACCORD, *PHRASES_MODE_AUTONOME):
        propre = propre.replace(phrase, "")
    return [c for c in CHAINES_INTERDITES if c in propre]


def hotes_externes(texte: str) -> list[str]:
    return [h for h in RE_URL.findall(texte) if h.lower() not in HOTES_AUTORISES]


def routes_appelees(texte: str) -> set[str]:
    return {RE_PARAMETRE.sub("{}", m.group(2)) for m in RE_ROUTE.finditer(texte)}


def fichiers():
    return sorted([PAGE / "index.html"] + [p for p in STATIC.rglob("*") if p.suffix in EXTENSIONS])


@pytest.fixture(scope="module")
def sources():
    trouves = {str(p.relative_to(PAGE)): p.read_text(encoding="utf-8") for p in fichiers()}
    assert {"index.html", "static/app.js", "static/source.js", "static/commun.js", "static/style.css"} <= set(trouves)
    return trouves


def js(sources):
    return {n: t for n, t in sources.items() if n.endswith(".js")}


def test_aucune_chaine_interdite(sources):
    fautes = {nom: chaines_interdites(t) for nom, t in sources.items()}
    assert not {n: f for n, f in fautes.items() if f}


def test_phrase_de_hierarchie_presente(sources):
    assert PHRASE_OBLIGATOIRE in normaliser(sources["static/commun.js"])
    assert PHRASE_OBLIGATOIRE in normaliser(sources["index.html"])  # <noscript>


def test_aucune_url_externe_hors_google_fonts(sources):
    fautes = {nom: hotes_externes(t) for nom, t in sources.items()}
    assert not {n: f for n, f in fautes.items() if f}


def test_aucune_url_absolue_dans_le_js(sources):
    assert not {n: RE_URL.findall(t) for n, t in js(sources).items() if RE_URL.findall(t)}


def test_aucun_chemin_personnel(sources):
    assert not [nom for nom, t in sources.items() if re.search(r"/(?:Users|home)/", t)]


def test_seules_les_routes_de_l_hote_sont_appelees(sources):
    appelees = set().union(*(routes_appelees(t) for t in js(sources).values()))
    assert appelees == ROUTES_DE_L_HOTE


def test_seule_la_couche_de_donnees_parle_au_reseau(sources):
    assert {n for n, t in js(sources).items() if RE_RESEAU.search(t)} == {"static/source.js"}
    assert "XMLHttpRequest" not in sources["static/source.js"]


def test_ressources_relatives_dans_index(sources):
    # servi à « / » par l'hôte : static/… relatif → /static/…, rien d'autre
    liens = re.findall(r'(?:href|src)="([^"]+)"', sources["index.html"])
    # icône vide en ligne : l'hôte ne sert pas /favicon.ico, le navigateur ne le demande plus
    locaux = [l for l in liens if not l.startswith("https://fonts.") and l != "data:,"]
    assert locaux and all(l.startswith("static/") for l in locaux), locaux


def test_aucun_lien_vers_une_autre_page_html(sources):
    # une seule page HTML : la navigation passe par l'ancre (#/fil, #/equipe/…)
    assert not {n for n, t in js(sources).items() if re.search(r"\b\w+\.html\b", t)}


def test_les_imports_existent(sources):
    for nom, texte in js(sources).items():
        for cible in RE_IMPORT.findall(texte):
            assert (PAGE / nom).parent.joinpath(cible).resolve().is_file(), (nom, cible)


def test_confirmation_de_refus_dans_la_page():
    phrase = "Refuser arrête l’agent jusqu’à ce que l’Assistant le relance. Confirmer ?"
    assert phrase in (STATIC / "commun.js").read_text(encoding="utf-8")


# --- le garde-fou lui-même détecte bien ce qu'il doit détecter ---

@pytest.mark.parametrize("fragment, attendu", [
    ("fetch('/api/etat')", {"/api/etat"}),
    ("fetch(`/api/agents/${encodeURIComponent(id)}/terminal`)", {"/api/agents/{}/terminal"}),
    ("fetch(`/api/journal?limite=${N}`)", {"/api/journal?limite={}"}),
    ("fetch('/api/actions/pause')", {"/api/actions/pause"}),
    ("const x = 'rien';", set()),
])
def test_extraction_des_routes(fragment, attendu):
    assert routes_appelees(fragment) == attendu


def test_une_route_hors_de_l_hote_serait_vue():
    assert not routes_appelees("fetch('/api/agents/x/ecrire')") <= ROUTES_DE_L_HOTE


@pytest.mark.parametrize("fragment", [
    '<button type="button">Mettre en pause</button>',
    "el('button', {}, 'Demander une relance')",
    "<button>Envoyer à l’Assistant</button>",
    "liste.push(x)",
    "<button>Valider</button>",
])
def test_le_garde_fou_attrape(fragment):
    assert chaines_interdites(fragment)


def test_la_confirmation_de_refus_reste_autorisee():
    assert not chaines_interdites("Refuser arrête l’agent jusqu’à ce que l’Assistant le relance. Confirmer ?")
    assert chaines_interdites("<button>Relancer l’agent</button>")


@pytest.mark.parametrize("phrase", [
    "L’Assistant fusionne à ta place, hors chemins réservés.",
    "Suspendu, fusions arrêtées : la liste a changé. Chaque fusion revient à ton accord.",
    "· aucune fusion encore",
    "Toujours, hors chemins : push, suppression de branche",
    "secrets, push et branches.",
    "etat.fusions_auto.derniere_fusion",
    "fetch('/api/actions/fusions-auto')",
])
def test_les_phrases_du_mode_autonome_sont_autorisees(phrase):
    assert not chaines_interdites(phrase)


@pytest.mark.parametrize("fragment", [
    "Fusionner la branche",  # pas d'assouplissement général de « fusion »
    "<button>Fusion</button>",
    "L’Assistant fusionne seul",  # la phrase exacte seulement
    "Mettre en pause le mode autonome",
    "liste.push(x)",
    "push seul",
    "Le mode compacte la liste",
    "Dire à l'Assistant de relancer",
])
def test_le_mode_autonome_n_assouplit_pas_le_reste(fragment):
    assert chaines_interdites(fragment)


def test_la_phrase_obligatoire_reste_autorisee():
    assert not chaines_interdites(
        "Cette page ne peut pas écrire aux agents. Pour leur demander quelque chose, passe par l’Assistant.")


@pytest.mark.parametrize("fragment, attendu", [
    ("<script src='https://cdn.example.com/x.js'></script>", ["cdn.example.com"]),
    ("@import url(//evil.example.org/a.css);", ["evil.example.org"]),
    ('<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans">', []),
])
def test_detection_des_url(fragment, attendu):
    assert hotes_externes(fragment) == attendu
