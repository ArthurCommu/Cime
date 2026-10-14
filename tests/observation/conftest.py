"""Isole chaque test de l'environnement réel : un agent peut tourner avec `CIME_PROJET` et
`CIME_AGENT` pointant sur un vrai projet, et un test ne doit jamais y écrire."""

import pytest


@pytest.fixture(autouse=True)
def _environnement_isole(monkeypatch, tmp_path_factory):
    monkeypatch.setenv("CIME_PROJET", str(tmp_path_factory.mktemp("projet-jetable")))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path_factory.mktemp("reglages-jetables")))
    monkeypatch.delenv("CIME_AGENT", raising=False)
