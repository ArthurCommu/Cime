"""Essai réel du mode autonome : trous du classement : un dépôt jetable créé par `cime init` et le
vrai hook `cime hook PermissionRequest` en sous-processus, avec des commandes qui sortaient `libre` ou
`autonome` à tort avant la correction du classement. `CIME_PROJET` et `CIME_AGENT` passent par l'environnement des sous-processus,
jamais sur le vrai projet. Lancer avec `-s` pour voir les sorties."""
import json
import types

import pytest

from cime.fondation import init
from test_fusions_auto_reel import _git
from test_mode_autonome_autorisations_reel import _demande

# (commande, classe, thème, destinataire immédiat d'une demande de worker-x-t, mode inactif)
CAS = (
    ("npx cowsay hi", "autonome", "dependance", "utilisateur"),
    ("brew install jq", "reserve", "systeme", "utilisateur"),
    ("npm install -g typescript", "reserve", "hors_projet", "utilisateur"),
    ("git submodule update --init", "reserve", "reseau", "utilisateur"),
    ("curl localhost:8000/x", "libre", "projet", "coord-x"),
    ("uv run --offline --with httpx pytest -q", "libre", "projet", "coord-x"),
    ("curl http://localhost.evil.com", "reserve", "reseau", "utilisateur"),
)


def test_essai_reel_mode_autonome_classement(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(init, "executable_cime", lambda: "/opt/outils/bin/cime")
    projet = tmp_path / "essai"
    assert init.executer(types.SimpleNamespace(dossier=str(projet), utilisateur="Camille",
                                               nom_projet=None, prefixe=None)) == 0
    _git("add", "-A", cwd=projet)
    _git("commit", "-q", "-m", "init", cwd=projet)
    (projet / ".orga" / "teams" / "x").mkdir(parents=True, exist_ok=True)
    (projet / "src").mkdir()
    sorties = []
    for commande, classe, theme, destinataire in CAS:
        mid, a, resume, corps = _demande(projet, "worker-x-t", "Bash", {"command": commande})
        corps = json.loads(corps)
        sorties.append(f"#{mid} → {a} : {resume}   corps {json.dumps(corps, ensure_ascii=False)}")
        assert (corps["classe"], corps["theme"], a) == (classe, theme, destinataire), commande
    with capsys.disabled():
        print("\n--- essai réel du classement (hook PermissionRequest en sous-processus)\n" + "\n".join(sorties))
