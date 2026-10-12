"""L'identité technique de l'utilisateur est `utilisateur`.

Un nom de personne n'a aucun traitement particulier : il est refusé comme toute
identité (ou nature) inconnue, avec la liste des valeurs valides. Le nom refusé
figure ici construit et non en littéral, pour que le balayage des sources reste vide.
"""
import re
from pathlib import Path

import pytest

from cime.fondation import registre
from cime.fondation.projet import valider_identite
from cime.signaux.identite import appelant

ANCIEN = "".join(["art", "hur"])
RACINE = Path(__file__).resolve().parents[2] / "src" / "cime"
DOSSIERS_SCRUTES = (RACINE / "fondation", RACINE / "signaux", RACINE / "gabarits")
SUFFIXES_TEXTE = {".py", ".md", ".toml", ".json", ".html", ".txt", ".css", ".js", ".yaml",
                  ".yml", ".cfg", ".ini", ".sh", ".sql"}
EXCEPTIONS: tuple[str, ...] = ()


def test_appelant_humain_au_clavier_est_utilisateur():
    assert appelant({}) == "utilisateur"


def test_identite_utilisateur_est_valide():
    assert valider_identite("utilisateur") == "utilisateur"
    assert valider_identite("utilisateur", emetteur=True) == "utilisateur"


def test_ancienne_identite_refusee_avec_la_liste_des_identites_valides():
    with pytest.raises(ValueError) as e:
        valider_identite(ANCIEN)
    message = str(e.value)
    for valide in ("assistant", "utilisateur", "coord-", "worker-"):
        assert valide in message
    # le seul endroit où l'ancien mot paraît est l'écho de la valeur refusée
    assert message.replace(repr(ANCIEN), "").lower().count(ANCIEN) == 0


def test_ancienne_identite_en_variable_d_environnement_refusee_comme_toute_inconnue():
    from cime.signaux.identite import ErreurIdentite
    with pytest.raises(ErreurIdentite) as e:
        appelant({"CIME_AGENT": ANCIEN})
    assert "utilisateur" in str(e.value)
    assert str(e.value).replace(repr(ANCIEN), "").lower().count(ANCIEN) == 0


@pytest.mark.parametrize("suffixe", ["rapport", "decision", "donnee"])
def test_natures_de_l_utilisateur_inscriptibles(tmp_path, suffixe):
    conn = registre.ouvrir(tmp_path / "registre.sqlite")
    nature = f"{suffixe}_utilisateur"
    assert nature in registre.NATURES
    registre.inscrire_message(conn, de="assistant", a="utilisateur", nature=nature,
                              resume="à lire")
    assert conn.execute("SELECT COUNT(*) FROM messages WHERE nature = ?", (nature,)
                        ).fetchone()[0] == 1


@pytest.mark.parametrize("suffixe", ["rapport", "decision", "donnee"])
def test_ancienne_nature_refusee_avec_la_liste_des_natures_valides(tmp_path, suffixe):
    conn = registre.ouvrir(tmp_path / "registre.sqlite")
    ancienne = f"{suffixe}_{ANCIEN}"
    with pytest.raises(ValueError) as e:
        registre.inscrire_message(conn, de="assistant", a="utilisateur", nature=ancienne,
                                  resume="x")
    message = str(e.value)
    for nature in registre.NATURES:
        assert nature in message
    assert message.replace(repr(ancienne), "").lower().count(ANCIEN) == 0


def _fichiers_scrutes():
    for dossier in DOSSIERS_SCRUTES:
        for chemin in sorted(dossier.rglob("*")):
            if chemin.is_file() and "__pycache__" not in chemin.parts:
                yield chemin


def test_aucune_mention_de_l_ancienne_identite_dans_le_produit():
    """Aucune exception : ni valeur, ni compatibilité, ni message, ni nom de fichier."""
    motif = re.compile(ANCIEN, re.IGNORECASE)
    trouves = []
    for chemin in _fichiers_scrutes():
        relatif = str(chemin.relative_to(RACINE))
        if relatif in EXCEPTIONS:
            continue
        if motif.search(relatif):
            trouves.append(f"{relatif} (nom du fichier)")
        if chemin.suffix not in SUFFIXES_TEXTE and chemin.suffix != "":
            continue
        try:
            texte = chemin.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for numero, ligne in enumerate(texte.splitlines(), 1):
            if motif.search(ligne):
                trouves.append(f"{relatif}:{numero}")
    assert trouves == []


def test_la_liste_d_exceptions_est_vide():
    assert EXCEPTIONS == ()


def test_le_parcours_voit_bien_des_fichiers_de_chaque_dossier():
    vus = {d.name: 0 for d in DOSSIERS_SCRUTES}
    for chemin in _fichiers_scrutes():
        for d in DOSSIERS_SCRUTES:
            if d in chemin.parents:
                vus[d.name] += 1
    assert all(n > 5 for n in vus.values()), vus

