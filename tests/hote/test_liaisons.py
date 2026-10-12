"""Liaisons de l'hôte : observateurs d'instantané, gardes du contexte, modules d'actions séparés."""
import asyncio
from pathlib import Path

import pytest

from cime.hote.dependances import Dependances
from cime.hote.gardes import Gardes
from cime.hote.rafraichisseur import Rafraichisseur
from cime.hote.serveur import Contexte


def test_observateurs_appeles_et_isoles(tmp_path):
    vus = []

    async def scenario():
        deps = Dependances(instantane=lambda p: {"n": len(vus)}, intervalle_s=0.01)
        r = Rafraichisseur(tmp_path, deps)

        def casse(inst):
            raise ValueError("observateur cassé")

        async def note(inst):
            vus.append(inst)

        r.ajouter_observateur(casse)
        r.ajouter_observateur(note)
        r.demarrer()
        for _ in range(100):
            if len(vus) >= 3:
                break
            await asyncio.sleep(0.01)
        await r.arreter()

    asyncio.run(scenario())
    assert len(vus) >= 3  # l'observateur cassé n'arrête ni la boucle ni les suivants


def _contexte(projet, **deps):
    return Contexte(projet, Dependances(**deps), 0, None, None)


def test_gardes_prefixe_du_manifeste(tmp_path):
    (tmp_path / ".orga").mkdir()
    (tmp_path / ".orga" / "projet.toml").write_text('prefixe = "cc-essai"\n')
    g = _contexte(tmp_path).gardes()
    assert isinstance(g, Gardes)
    g.autoriser_commande(["tmux", "has-session", "-t", "cc-essai-x"])


def test_gardes_prefixe_injecte_prioritaire(tmp_path):
    g = _contexte(tmp_path, prefixe="cc-essai").gardes()
    g.autoriser_commande(["tmux", "has-session", "-t", "cc-essai-x"])


def test_gardes_sans_prefixe_erreur_explicite(tmp_path):
    with pytest.raises(RuntimeError, match="prefixe"):
        _contexte(tmp_path).gardes()
