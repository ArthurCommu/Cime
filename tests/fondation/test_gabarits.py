import re
from pathlib import Path

GABARITS = Path(__file__).resolve().parents[2] / "src" / "cime" / "gabarits"
IMPORT = re.compile(r"^\s*@\S")


def test_aucun_import_arobase_dans_les_gabarits():
    """Un import `@` déclenche l'écran d'approbation des imports externes : jamais."""
    fichiers = [f for f in GABARITS.rglob("*") if f.is_file()]
    assert fichiers
    fautifs = [f"{f.relative_to(GABARITS)}:{n}"
               for f in fichiers
               for n, ligne in enumerate(f.read_text(encoding="utf-8").splitlines(), 1)
               if IMPORT.match(ligne)]
    assert fautifs == []


SOCLE = GABARITS / ".orga" / "socle"
# leçon du dépôt d'origine → (fichier lu par le bon rôle, passage qui la porte)
LECONS = [
    ("coordinateur.md", "ni `tmux send-keys`, ni `capture-pane`, ni\naucune autre commande `tmux`"),
    ("coordinateur.md", "`--attend` est obligatoire"),
    ("economie-de-tokens.md", "**quand la session est au repos et son invite vide**"),
    ("assistant.md", "jamais\n  pendant que {{utilisateur}} écrit"),
    ("integration.md", "part sans\n   `{{var_projet}}` ni `{{var_agent}}`"),
    ("coordinateur.md", "Haiku seulement pour les sessions\nd'essai"),
    ("assistant.md", "**faire les fusions**"),
    ("coordinateur.md", "**Aucune fusion n'est faite par toi ni par tes workers**"),
    ("gabarits/tache-worker.md", "**chemin absolu du dépôt principal"),
    ("assistant.md", "**tu n'as plus de veille à armer**"),
    ("assistant.md", "**fais une ronde**"),
]


def test_lecons_du_depot_d_origine_a_leur_place():
    absentes = [(f, p) for f, p in LECONS if p not in (SOCLE / f).read_text(encoding="utf-8")]
    assert absentes == []


def test_haiku_jamais_pour_le_travail_mecanique():
    """Haiku ne tient pas en mode auto : jamais recommandé pour un worker."""
    fichiers = [f for f in GABARITS.rglob("*.md") if f.name != "VARIABLES.md"]
    fautifs = [str(f.relative_to(GABARITS)) for f in fichiers
               if re.search(r"Haiku pour le\s+mécanique", f.read_text(encoding="utf-8"))]
    assert fautifs == []


def test_coordinateur_ne_cree_pas_de_session_tmux():
    """Le worker se lance par `lancer` ; le coordinateur n'exécute aucune session tmux."""
    texte = (SOCLE / "coordinateur.md").read_text(encoding="utf-8")
    assert "ne crée ni ne fait exécuter de session tmux" in texte
    assert "tmux new-session" not in texte
    assert "lancer worker <ton-équipe> <tâche> --modele <modèle>" in texte
