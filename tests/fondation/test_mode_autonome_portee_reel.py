"""Essai réel du mode autonome : portée, plafond et noyau : un dépôt jetable créé par `cime init`,
le vrai hook `cime hook PreToolUse` et les commandes `cime fusions-auto`, `cime envoyer`, `cime etat` en
sous-processus. `CIME_PROJET` et `CIME_AGENT` passent par l'environnement des sous-processus (`env=`),
jamais par la ligne de commande ni sur le vrai projet. Lancer avec `-s` pour voir les sorties."""
import json
import sqlite3
import types

from cime.fondation import init
from test_fusions_auto_reel import _cime, _decision, _evenement, _git


def _lignes_reglage(projet):
    conn = sqlite3.connect(projet / ".orga" / "etat" / "registre.sqlite")
    try:
        return conn.execute("SELECT id, valeur, auteur, details FROM reglages_projet ORDER BY id").fetchall()
    finally:
        conn.close()


def _branche(projet, nom, fichier):
    _git("checkout", "-q", "-b", nom, "main", cwd=projet)
    cible = projet / fichier
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_text("x\n")
    _git("add", "-A", cwd=projet)
    _git("commit", "-q", "-m", nom, cwd=projet)
    _git("checkout", "-q", "main", cwd=projet)
    return _git("rev-parse", nom, cwd=projet)


def test_essai_reel_mode_autonome_portee(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(init, "executable_cime", lambda: "/opt/outils/bin/cime")
    projet = tmp_path / "essai"
    assert init.executer(types.SimpleNamespace(dossier=str(projet), utilisateur="Camille",
                                               nom_projet=None, prefixe=None)) == 0
    _git("add", "-A", cwd=projet)
    _git("commit", "-q", "-m", "init", cwd=projet)
    assert _git("rev-parse", "--abbrev-ref", "HEAD", cwd=projet) == "main" \
        or _git("branch", "-m", "main", cwd=projet) == ""
    sha_dep = _branche(projet, "equipe/dep", "pyproject.toml")
    sha_sec = _branche(projet, "equipe/sec", ".claude/x")
    etapes = []

    def pre(equipe):
        r = _cime(projet, "assistant", "hook", "PreToolUse",
                  entree=_evenement(projet, f"git merge --no-ff -m x equipe/{equipe}", "PreToolUse"))
        assert r.returncode == 0, r.stderr
        return r.stdout

    def lecture():
        r = _cime(projet, "assistant", "fusions-auto")
        assert r.returncode == 0, r.stderr
        return r.stdout

    # 1. inactif : plafond du manifeste et 0 lancement quand même
    sortie = lecture()
    assert "fusions automatiques : inactive" in sortie
    assert "lancements automatiques de chantier : 0 sur 5" in sortie
    etapes.append(("1. `cime fusions-auto`, inactif", "\n".join(sortie.splitlines()[:3])))

    # 2. L'utilisateur active : la ligne `reglages_projet` porte portée, plafond, empreinte
    r = _cime(projet, "utilisateur", "fusions-auto", "active")
    assert r.returncode == 0 and r.stdout.strip() == "1", r.stderr
    [(ident, valeur, auteur, details)] = _lignes_reglage(projet)
    d = json.loads(details)
    assert (ident, valeur, auteur) == (1, "active", "utilisateur")
    assert d["portee"] == 2 and d["chantiers_par_jour"] == 5 and len(d["empreinte"]) == 64
    etapes.append(("2. ligne `reglages_projet`", f"id {ident} {valeur} {auteur} "
                   + json.dumps({k: v for k, v in d.items() if k != "reserves"})
                   + f" ({len(d['reserves'])} chemins réservés)"))
    sortie = lecture()
    assert "fusions automatiques : active\n" in sortie and "portée : 2" in sortie
    assert "lancements automatiques de chantier : 0 sur 5" in sortie
    etapes.append(("2b. `cime fusions-auto`, actif", "\n".join(sortie.splitlines()[:5])))

    # 3. le plafond change dans le manifeste : suspendue
    manifeste = projet / ".orga" / "projet.toml"
    original = manifeste.read_text()
    manifeste.write_text(original.replace("chantiers_par_jour = 5", "chantiers_par_jour = 7"))
    sortie = lecture()
    assert "active mais suspendue" in sortie and "lancements automatiques de chantier : 0 sur 7" in sortie
    etapes.append(("3. plafond 5 → 7 dans le manifeste", "\n".join(sortie.splitlines()[:5])))

    # 4. réactivation : revalide
    r = _cime(projet, "utilisateur", "fusions-auto", "active")
    assert r.returncode == 0 and r.stdout.strip() == "2", r.stderr
    sortie = lecture()
    assert "fusions automatiques : active\n" in sortie
    assert json.loads(_lignes_reglage(projet)[-1][3])["chantiers_par_jour"] == 7
    etapes.append(("4. réactivation", f"id 2 ; {sortie.splitlines()[0]}"))

    # 5. une activation écrite à la main sans portée : suspendue, liste et plafond identiques
    conn = sqlite3.connect(projet / ".orga" / "etat" / "registre.sqlite")
    with conn:
        sans = {k: v for k, v in json.loads(_lignes_reglage(projet)[-1][3]).items()
                if k not in ("portee", "chantiers_par_jour")}
        conn.execute("INSERT INTO reglages_projet (horodatage, cle, valeur, auteur, details)"
                     " VALUES ('2026-10-12T00:00:00.000Z', 'fusions_auto', 'active', 'utilisateur', ?)",
                     (json.dumps(sans),))
    conn.close()
    sortie = lecture()
    assert "active mais suspendue" in sortie and "portée : absente" in sortie
    etapes.append(("5. activation à la main sans `portee`", "\n".join(sortie.splitlines()[:4])))
    r = _cime(projet, "utilisateur", "fusions-auto", "active")
    assert r.returncode == 0, r.stderr
    assert "fusions automatiques : active\n" in lecture()

    # 6. annonces ; pyproject.toml passe, .claude/x est refusée (condition 2)
    for equipe, sha in (("dep", sha_dep), ("sec", sha_sec)):
        r = _cime(projet, "assistant", "envoyer", "--a", "utilisateur", "--nature", "rapport_utilisateur",
                  "--objet", f"fusion-auto:{equipe}:{sha}", f"{equipe} {sha[:7]} : essai ; vérifié : essai réel")
        assert r.returncode == 0, r.stderr
    sortie = pre("dep")
    assert sortie == ""
    etapes.append(("6a. fusion qui touche `pyproject.toml`", _decision(sortie)))
    sortie = pre("sec")
    assert "condition 2" in sortie and ".claude/x" in sortie
    etapes.append(("6b. fusion qui touche `.claude/x`", _decision(sortie)))

    # 7. `cime etat`
    etat = json.loads(_cime(projet, "assistant", "etat").stdout)["fusions_auto"]
    assert etat["active"] and not etat["suspendue"] and etat["portee"] == 2
    assert etat["chantiers_24h"] == 0 and etat["chantiers_max"] == 7
    assert [(x["genre"], x["cle"]) for x in etat["decisions"]] == [
        ("fusion", f"sec:{sha_sec}"), ("fusion", f"dep:{sha_dep}")]
    etapes.append(("7. `cime etat` → fusions_auto", json.dumps(
        {k: v for k, v in etat.items() if k not in ("reserves", "reserves_proposees")})))

    with capsys.disabled():
        print()
        for titre, sortie in etapes:
            print(f"--- {titre}\n{sortie}")
