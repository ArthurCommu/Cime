"""La garde refuse les actions interdites, jamais le texte qui en parle.

Une action interdite reste refusée dans toutes ses enveloppes (`;`, `$( )`, `bash -c`, heredoc
vers un shell, script, alias, variable, interpréteur) ; un commentaire, un heredoc envoyé à
`cat`, un corps de message, un commentaire de script ne le sont pas. Le corpus est vérifié contre
un vrai shell dans test_garde_oracle.py.
"""
import json
from pathlib import Path

import pytest

from aide_garde_texte import REFUSEES, REFUSEES_PRUDENCE, TEXTES, poser_scripts
from cime.fondation import garde

FIXTURE = Path(__file__).parent / "fixtures" / "hooks" / "PreToolUse.json"


def entree(commande, cwd):
    """Entrée construite sur la structure de la capture réelle PreToolUse.json."""
    e = json.loads(FIXTURE.read_text())
    e["tool_name"] = "Bash"
    e["tool_input"] = {"command": commande, "description": "essai"}
    e["cwd"] = str(cwd)
    return e


def motif(commande, cwd):
    return garde.decider(entree(commande, cwd), None)


@pytest.fixture(scope="module")
def dossier(tmp_path_factory):
    """Dossier courant des commandes, avec les scripts du corpus."""
    d = tmp_path_factory.mktemp("garde-texte")
    poser_scripts(d)
    return d


def test_corpus_ecrit_a_la_main_assez_grand():
    assert len(REFUSEES) + len(REFUSEES_PRUDENCE) + len(TEXTES) >= 80


# --- les actions interdites restent refusées ------------------------------------------------

@pytest.mark.parametrize("commande", REFUSEES + REFUSEES_PRUDENCE)
def test_action_interdite_refusee(dossier, commande):
    assert motif(commande, dossier) is not None, commande


# --- le texte passe -------------------------------------------------------------------------

@pytest.mark.parametrize("commande", TEXTES)
def test_texte_laisse_passer(dossier, commande):
    assert motif(commande, dossier) is None, commande


# --- le retrait des commentaires -------------------------------------------------------------

@pytest.mark.parametrize("texte, attendu", [
    ("echo a # l'export d'Eugène", "echo a "),
    ("# l'export\ngit push", "\ngit push"),
    ("ls;# l'export\nls", "ls;\nls"),
    ("ls &# x\nls", "ls &\nls"),
    ("#!/bin/sh\n# l'export\nls", "#!/bin/sh\n\nls"),
    ("# x \\\ngit push", "\ngit push"),            # un `\` de commentaire ne continue rien
    ("echo a \\\n# b\nls", "echo a \\\n\nls"),    # continuation : `#` commence un mot
    ("cat <<'EOF'\n# corps gardé\nEOF\n# l'export", "cat <<'EOF'\n# corps gardé\nEOF\n"),
    ("# l'export\necho `x` # c\ngit push", "\necho `x` # c\ngit push"),  # doute dès la ligne
    ("# a\necho 'x # y\nz", "\necho 'x # y\nz"),  # guillemet jamais fermé : doute dès sa ligne
    ("# a\n( ls\n# l'export\nls", "\n( ls\n# l'export\nls"),  # parenthèse jamais fermée : idem
])
def test_sans_commentaires(texte, attendu):
    assert garde.sans_commentaires(texte) == attendu


@pytest.mark.parametrize("texte", [
    "echo $'a\\' # '; git push",
    "a=# ; git push",
    "echo a#b; git push",
    "echo a\\\n#b; git push",
    "echo $(echo \"x # y\"); git push",
    "echo \"x # y\"; git push",
    "echo 'x # y'; git push",
    "echo $\"it's # x\" ; git push",
    "echo `echo a # b` ; git push",
    "echo $(echo a # b\n) ; git push",
    "echo ${x#*#} ; git push",
    "echo $(( 2#101 )) ; git push",
    "ls (#i)x; git push",
    "echo \"it's # x\" ; git push",
    "echo 'it''s # x' ; git push",
    "echo \"jamais fermé # x\ngit push",
])
def test_le_retrait_ne_cache_jamais_une_commande(texte):
    """Le `#` n'ouvre pas de commentaire ici (ou la ligne est douteuse) : rien n'est retiré."""
    assert garde.sans_commentaires(texte) == texte


@pytest.mark.parametrize("ligne, lecteur", [
    ("cat <<EOF", None),
    ("cat > deploy.sh <<'EOF'", None),
    ("tee note.txt <<'EOF' >/dev/null", None),
    ("git commit -F - <<'EOF'", None),
    ("cime envoyer --a x --corps - <<'EOF'", None),
    ("cat <<'EOF' | sh", "shell"),
    ("bash -s <<EOF", "shell"),
    ("ssh hote 'bash -s' <<EOF", "shell"),
    ("eval \"$(cat <<'EOF'", "shell"),
    ("python3 - <<'EOF'", "python3"),
    (".venv/bin/python - <<'EOF'", "python"),
    ("perl <<'EOF' # l'export", "perl"),
])
def test_le_corps_d_un_heredoc_va_a_qui_le_lit(ligne, lecteur):
    assert garde._destinataire(ligne) == lecteur


def test_repli_ligne_par_ligne():
    assert garde._ressemble("git status\n# Ni push") is False
    assert garde._ressemble("git log\n" + "x\n" * 30 + "# push") is False
    assert garde._ressemble("tmux") is True
    assert garde._ressemble("git \\\npush") is True  # continuation jointe
    assert garde._ressemble("git branch x\n-d") is False
    assert garde._ressemble("rtk\nproxy") is False


@pytest.mark.parametrize("commande", ["git status\n# l'export\n# Ni push", "ls\n# tmux"])
def test_erreur_interne_repli_sans_commentaires(monkeypatch, commande):
    def panne(*a, **k):
        raise RuntimeError("panne simulée")
    monkeypatch.setattr(garde, "_analyser", panne)
    assert garde.decider(entree(commande, "/"), None) is None


@pytest.mark.parametrize("commande", ["# l'export\ngit push", "git \\\n push", "echo 'x\ntmux"])
def test_erreur_interne_repli_refuse_encore(monkeypatch, commande):
    def panne(*a, **k):
        raise RuntimeError("panne simulée")
    monkeypatch.setattr(garde, "_analyser", panne)
    assert garde.decider(entree(commande, "/"), None) == garde.M_ERREUR


def test_guillemet_vraiment_non_ferme_repli_par_ligne(dossier):
    """Analyse impossible sans commentaire en cause : le repli juge chaque ligne."""
    assert motif("echo 'non fermé\ngit status", dossier) is None
    assert motif("echo 'non fermé\ngit push", dossier) == garde.M_REPLI
    assert motif("echo 'non fermé ; tmux ls", dossier) == garde.M_REPLI


# --- l'identité dans le code : après `-m` ou `-c`, il n'y a pas de script ---------------------

CODE_IDENTITE = "import os\nenv = dict(os.environ)\nenv.pop('CLAUDECODE', None)\n"


@pytest.fixture
def depot_de_test(tmp_path):
    """Un fichier de test qui fabrique un environnement sans CLAUDECODE (ce que font les tests)."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(CODE_IDENTITE)
    return tmp_path


@pytest.mark.parametrize("commande", [
    ".venv/bin/python -m pytest tests/test_x.py",
    ".venv/bin/python -m pytest tests/test_x.py -q -k garde",
    "python3 -mpytest tests/test_x.py",
    "python3 -B -m pytest tests/test_x.py",
    "python3 -Bm pytest tests/test_x.py",
    "sed -i '' -e 's/a/b/' -e 's/c/d/' tests/test_x.py && .venv/bin/python -m pytest tests -k x",
    "python3 -c 'import sys; print(sys.argv)' tests/test_x.py",
    "perl -e 'print 1' tests/test_x.py",
    "python3 -c 'import os, subprocess; print(os.environ.get(\"CLAUDECODE\")); "
    "subprocess.run([\"ls\"], env=None)'",
    "python3 -c 'import os, subprocess; v = os.environ.get(\"CLAUDECODE\"); "
    "subprocess.run([\"ls\"], env=os.environ)'",
    "python3 -c 'import os; env = None; print(env == os.environ.get(\"CLAUDECODE\"))'",
])
def test_module_ou_code_lance_n_est_pas_un_script(depot_de_test, commande):
    assert motif(commande, depot_de_test) is None, commande


@pytest.mark.parametrize("commande", [
    "python3 tests/test_x.py",
    "python3 -B tests/test_x.py",
    "python3 -W ignore tests/test_x.py",
    "python3 -Wignore tests/test_x.py",
    "python3 -c 'import os; os.environ[\"CIME_AGENT\"] = \"x\"'",
    "python3 -c \"import subprocess; subprocess.run(['cime'], env={'CIME_AGENT': 'a'})\"",
    "python3 -c 'import os; env = os.environ.copy(); env[\"CLAUDECODE\"] = \"0\"'",
    "python3 -c 'import os; env = dict(os.environ); env.pop(\"CLAUDECODE\")'",
    "python3 -c 'import os, subprocess; e = {**os.environ, \"CIME_AGENT\": \"x\"}; "
    "subprocess.run([\"ls\"], env=e)'",
    "python3 - <<'EOF'\nimport os\nos.environ['CIME_AGENT'] = 'x'\nEOF",
    "CIME_AGENT=x ls",
    "env -u CIME_AGENT ls",
    "export CIME_PROJET=/x",
    "unset CLAUDECODE",
])
def test_ecrire_l_identite_reste_refuse(depot_de_test, commande):
    assert motif(commande, depot_de_test) is not None, commande
