"""Essai réel du mode autonome : autorisations par classe : un dépôt jetable créé par `cime init`,
le vrai hook `cime hook PermissionRequest`, `cime accorder`, `cime fusions-auto` et une passe du moteur
d'échéances, chacun en sous-processus. `CIME_PROJET` et `CIME_AGENT` passent par l'environnement des
sous-processus (`env=`), jamais par la ligne de commande ni sur le vrai projet. Lancer avec `-s` pour voir
les sorties."""
import json
import os
import sqlite3
import subprocess
import sys
import types
from pathlib import Path

from cime.fondation import init
from cime.fondation.nom import VAR_AGENT, VAR_PROJET
from test_fusions_auto_reel import SRC, _cime, _git

FIXTURE = Path(__file__).parent / "fixtures" / "hooks" / "PermissionRequest.json"


def _demande(projet, agent, outil, tool_input):
    e = json.loads(FIXTURE.read_text())
    e.update({"tool_name": outil, "tool_input": tool_input, "cwd": str(projet),
              "hook_event_name": "PermissionRequest"})
    e.pop("permission_suggestions", None)
    r = _cime(projet, agent, "hook", "PermissionRequest", entree=json.dumps(e))
    assert r.returncode == 0, r.stderr
    return _sql(projet, "SELECT id, a, resume, corps FROM messages WHERE nature = 'signalement'"
                        " AND objet LIKE 'autorisation:%' ORDER BY id DESC LIMIT 1")[0]


def _sql(projet, requete, params=()):
    conn = sqlite3.connect(projet / ".orga" / "etat" / "registre.sqlite")
    try:
        return conn.execute(requete, params).fetchall()
    finally:
        conn.close()


def _passe(projet, minutes):
    """Une passe du moteur d'échéances, horloge simulée à +`minutes` de maintenant, en sous-processus."""
    code = ("import sys; from datetime import datetime, timedelta, timezone; from pathlib import Path;"
            "from cime.signaux import relances;"
            "print(relances.executer(Path(sys.argv[1]), datetime.now(timezone.utc)"
            " + timedelta(minutes=float(sys.argv[2]))))")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CIME_", "GIT_"))}
    env.update({VAR_PROJET: str(projet), "PYTHONPATH": str(SRC)})
    r = subprocess.run([sys.executable, "-c", code, str(projet), str(minutes)], env=env, cwd=projet,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return int(r.stdout.strip())


def _escalades(projet, mid):
    return _sql(projet, "SELECT a, nature, objet FROM messages WHERE en_reponse_a = ? AND de = 'cime'"
                        " AND (objet LIKE 'relance:%' OR objet LIKE 'escalade:%') ORDER BY id", (mid,))


def test_essai_reel_mode_autonome_autorisations(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(init, "executable_cime", lambda: "/opt/outils/bin/cime")
    projet = tmp_path / "essai"
    assert init.executer(types.SimpleNamespace(dossier=str(projet), utilisateur="Camille",
                                               nom_projet=None, prefixe=None)) == 0
    _git("add", "-A", cwd=projet)
    _git("commit", "-q", "-m", "init", cwd=projet)
    (projet / ".orga" / "teams" / "x").mkdir(parents=True, exist_ok=True)
    (projet / "src").mkdir()
    sorties = []

    def noter(titre, texte):
        sorties.append(f"--- {titre}\n{texte}")

    # (a) une demande `libre` d'un worker arrive chez son coordinateur, pas chez l'Assistant
    mid, a, resume, corps = _demande(projet, "worker-x-t", "Bash", {"command": "ls src"})
    assert a == "coord-x" and json.loads(corps)["classe"] == "libre"
    assert _sql(projet, "SELECT count(*) FROM messages WHERE a = 'assistant'") == [(0,)]
    noter("(a) libre, worker", f"#{mid} → {a} : {resume}\ncorps {corps}")

    # (b) le coordinateur l'accorde : l'accord part à `cime`
    r = _cime(projet, "coord-x", "accorder", str(mid))
    assert r.returncode == 0, r.stderr
    accord = _sql(projet, "SELECT id, de, a, nature, objet FROM messages WHERE nature = 'accord'")
    assert accord[0][1:3] == ("coord-x", "cime")
    noter("(b) cime accorder (coord-x)", f"code {r.returncode}, sortie {r.stdout.strip()} ; {accord}")

    # (c) `reserve` (Edit hors projet) : coordinateur et Assistant refusés, l'utilisateur passe
    mid, a, resume, corps = _demande(projet, "worker-x-t", "Edit", {"file_path": "/etc/hosts"})
    info = _sql(projet, "SELECT a, objet FROM messages WHERE objet LIKE 'autorisation-reservee:%'")
    assert a == "utilisateur" and info[0][0] == "coord-x"
    texte = [f"#{mid} → {a} : {resume} ; information {info}"]
    for qui in ("coord-x", "assistant"):
        r = _cime(projet, qui, "accorder", str(mid))
        assert r.returncode == 2 and "réservé à l'utilisateur : hors_projet" in r.stderr
        texte.append(f"{qui} : code {r.returncode} — {r.stderr.strip()}")
    r = _cime(projet, "utilisateur", "accorder", str(mid))
    assert r.returncode == 0, r.stderr
    texte.append(f"utilisateur : code {r.returncode}, accord #{r.stdout.strip()}")
    noter("(c) reserve", "\n".join(texte))

    # (d) `autonome` (uv add httpx) : mode inactif ⇒ l'utilisateur, l'Assistant refusé
    mid, a, resume, corps = _demande(projet, "worker-x-t", "Bash", {"command": "uv add httpx"})
    assert a == "utilisateur"
    r = _cime(projet, "assistant", "accorder", str(mid))
    assert r.returncode == 2 and "le mode autonome n'est plus actif" in r.stderr
    texte = [f"inactif : #{mid} → {a} : {resume}", f"assistant : code {r.returncode} — {r.stderr.strip()}"]
    r = _cime(projet, "utilisateur", "fusions-auto", "active")
    assert r.returncode == 0, r.stderr
    d2, a2, resume2, _ = _demande(projet, "worker-x-t", "Bash", {"command": "uv add httpx"})
    d3, a3, _, _ = _demande(projet, "worker-x-t", "Bash", {"command": "uv add rich"})
    assert a2 == a3 == "assistant"
    r = _cime(projet, "assistant", "accorder", str(d2))
    assert r.returncode == 0, r.stderr
    annonce = _sql(projet, "SELECT id, de, a, nature, objet, resume FROM messages"
                           " WHERE objet LIKE 'autorisation-auto:%'")
    assert len(annonce) == 1 and annonce[0][1:4] == ("assistant", "utilisateur", "rapport_utilisateur")
    assert _sql(projet, "SELECT count(*) FROM obligations WHERE message_id = ?", (annonce[0][0],)) == [(0,)]
    texte += [f"actif : #{d2} → {a2} : {resume2}", f"assistant accorde #{d2} : code 0 ; annonce {annonce}",
              "obligations de l'annonce : 0"]
    r = _cime(projet, "utilisateur", "fusions-auto", "inactive")
    assert r.returncode == 0, r.stderr
    r = _cime(projet, "assistant", "accorder", str(d3))
    assert r.returncode == 2 and "le mode autonome n'est plus actif" in r.stderr
    texte.append(f"mode coupé, assistant accorde #{d3} : code {r.returncode} — {r.stderr.strip()}")
    noter("(d) autonome", "\n".join(texte))

    # (e) l'échéance 2 min puis 4 min d'une demande `libre` de worker, mode actif puis inactif
    texte = []
    for valeur in ("active", "inactive"):
        r = _cime(projet, "utilisateur", "fusions-auto", valeur)
        assert r.returncode == 0, r.stderr
        mid, a, _, _ = _demande(projet, "worker-x-t", "Bash", {"command": f"pytest -q {valeur}"})
        assert a == "coord-x"
        _passe(projet, 0)      # le facteur passe toutes les 2 s : l'étape immédiate est faite à t0
        n2 = _passe(projet, 2.1)
        apres2 = _escalades(projet, mid)
        n4 = _passe(projet, 4.2)
        apres4 = _escalades(projet, mid)[len(apres2):]
        texte.append(f"mode {valeur}, #{mid} : +2 min → {n2} message(s) {apres2} ; +4 min → {apres4}")
        assert [x[:2] for x in apres2[-2:]] == [("coord-x", "relance"), ("assistant", "signalement")]
        attendu = ("assistant", "relance") if valeur == "active" else ("utilisateur", "signalement")
        assert [x[:2] for x in apres4] == [attendu]
        _cime(projet, "coord-x", "refuser", str(mid), "fin de l'essai")
    noter("(e) échéances simulées", "\n".join(texte))

    with capsys.disabled():
        print("\n" + "\n".join(sorties))
