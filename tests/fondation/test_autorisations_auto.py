"""Mode autonome : le classement d'une demande d'autorisation.

Un test par ligne de chaque table de `autorisations_auto` (paramétré depuis la table elle-même :
une ligne ajoutée est testée d'office), puis des tests d'ensemble.
"""
import os
import textwrap
from pathlib import Path

import pytest

from conftest import exiger_jetable
from cime.fondation import autorisations_auto as aa
from cime.fondation.autorisations_auto import classer_autorisation

MANIFESTE = textwrap.dedent("""\
    nom = "Essai"
    prefixe = "essai"
    branche_reference = "main"
    branche_equipe = "equipe/{equipe}"
    worktree_equipe = "WT"
    equipes_speciales = ["assistant"]
    modele_assistant = "m"
    modele_coordinateur = "m"

    [bac_a_sable]
    sites = ["pypi.org", "*.pythonhosted.org", "github.com"]
""")
AGENT = "worker-x-t"


def fabriquer(racine: Path, worktree=".orga/worktrees/{equipe}") -> Path:
    racine = exiger_jetable(racine)
    (racine / ".orga" / "teams" / "x").mkdir(parents=True)
    (racine / ".orga" / "projet.toml").write_text(MANIFESTE.replace("WT", worktree))
    (racine / "src").mkdir()
    return racine


@pytest.fixture
def projet(tmp_path):
    racine = fabriquer(tmp_path / "depot")
    (racine / ".orga" / "worktrees" / "x").mkdir(parents=True)
    return racine


def bash(projet, commande, cwd=None):
    return classer_autorisation(projet, AGENT, "Bash", {"command": commande}, cwd=cwd or projet)


def classe(verdict):
    return verdict["classe"], verdict["theme"]


# --- outils sans commande -----------------------------------------------------------------------

@pytest.mark.parametrize("outil", aa.OUTILS_ECRITURE)
def test_ecriture_dans_le_projet_libre(projet, outil):
    cle = "notebook_path" if outil == "NotebookEdit" else "file_path"
    v = classer_autorisation(projet, AGENT, outil, {cle: str(projet / "src" / "a.py")})
    assert classe(v) == ("libre", "projet")


@pytest.mark.parametrize("outil", aa.OUTILS_ECRITURE)
def test_ecriture_hors_projet_reservee(projet, tmp_path, outil):
    cle = "notebook_path" if outil == "NotebookEdit" else "file_path"
    v = classer_autorisation(projet, AGENT, outil, {cle: str(tmp_path / "ailleurs.py")})
    assert classe(v) == ("reserve", "hors_projet")


@pytest.mark.parametrize("theme, motif", [(t, m) for t, ms in aa.NOYAU_MACHINE for m in ms])
def test_ecriture_dans_le_noyau_machine_reservee(projet, theme, motif):
    """Une ligne du noyau : à la racine du dépôt, et dans un worktree d'équipe."""
    nom = motif.replace("*", "abc").rstrip("/")
    for racine in (projet, projet / ".orga" / "worktrees" / "x"):
        chemin = racine / nom / ("f" if motif.endswith("/") else "")
        v = classer_autorisation(projet, AGENT, "Write", {"file_path": str(chemin)})
        assert classe(v) == ("reserve", theme), (racine, motif)


@pytest.mark.parametrize("chemin", ["CLAUDE.md", ".orga/socle/assistant.md", ".orga/produit/x.md",
                                    ".orga/teams/x/CLAUDE.md"])
def test_philosophie_libre_a_l_ecriture_dans_un_worktree(projet, chemin):
    v = classer_autorisation(projet, AGENT, "Edit",
                             {"file_path": str(projet / ".orga" / "worktrees" / "x" / chemin)})
    assert classe(v) == ("libre", "projet")


def test_ecriture_sans_chemin_reservee(projet):
    assert classe(classer_autorisation(projet, AGENT, "Write", {})) == ("reserve", "illisible")


@pytest.mark.parametrize("outil, cle", [("Read", "file_path"), ("Glob", "path"), ("Grep", "path")])
def test_lecture_hors_projet_reservee_et_secret_reserve(projet, tmp_path, outil, cle):
    assert classe(classer_autorisation(projet, AGENT, outil, {cle: str(tmp_path)})) \
        == ("reserve", "hors_projet")
    assert classe(classer_autorisation(projet, AGENT, outil, {cle: str(projet / ".env")})) \
        == ("reserve", "secrets")


@pytest.mark.parametrize("outil, cle", [("Read", "file_path"), ("Glob", "path"), ("Grep", "path")])
def test_lecture_du_noyau_droits_libre(projet, outil, cle):
    """Lire `.claude/` ou `.orga/etat/` n'est pas réservé : seuls hors projet et secrets."""
    v = classer_autorisation(projet, AGENT, outil, {cle: str(projet / ".claude" / "settings.json")})
    assert classe(v) == ("libre", "projet")


def test_glob_motif_absolu_hors_projet(projet):
    v = classer_autorisation(projet, AGENT, "Glob", {"pattern": "/etc/**/*.conf"})
    assert classe(v) == ("reserve", "hors_projet")


def test_lien_symbolique_sortant_reserve(projet, tmp_path):
    dehors = tmp_path / "dehors"
    dehors.mkdir()
    (projet / "src" / "lien").symlink_to(dehors)
    v = classer_autorisation(projet, AGENT, "Edit", {"file_path": str(projet / "src" / "lien" / "a.py")})
    assert classe(v) == ("reserve", "hors_projet")
    assert classe(bash(projet, "cat src/lien/a.py")) == ("reserve", "hors_projet")


def test_worktree_hors_du_depot_est_une_racine(tmp_path):
    projet = fabriquer(tmp_path / "depot", worktree="../{depot}-{equipe}")
    (tmp_path / "depot-x").mkdir()
    v = classer_autorisation(projet, AGENT, "Write", {"file_path": str(tmp_path / "depot-x" / "a.py")})
    assert classe(v) == ("libre", "projet")
    v = classer_autorisation(projet, AGENT, "Write",
                             {"file_path": str(tmp_path / "depot-x" / ".claude" / "s.json")})
    assert classe(v) == ("reserve", "droits")


@pytest.mark.parametrize("url, attendu", [("https://pypi.org/simple/x", "libre"),
                                          ("https://files.pythonhosted.org/a", "libre"),
                                          ("https://exemple.com/", "reserve")])
def test_webfetch_selon_les_sites(projet, url, attendu):
    assert classer_autorisation(projet, AGENT, "WebFetch", {"url": url})["classe"] == attendu


def test_websearch_reserve(projet):
    assert classe(classer_autorisation(projet, AGENT, "WebSearch", {"query": "x"})) == ("reserve", "reseau")


@pytest.mark.parametrize("outil", ["Task", "Agent", "mcp__serveur__outil", "KillShell", "?"])
def test_outil_inconnu_ou_mcp_reserve(projet, outil):
    assert classe(classer_autorisation(projet, AGENT, outil, {})) == ("reserve", "outil_inconnu")


def test_ne_leve_jamais(tmp_path):
    v = classer_autorisation(tmp_path / "rien", AGENT, "Bash", {"command": "ls"})
    assert classe(v) == ("reserve", "illisible")
    v = classer_autorisation(tmp_path, AGENT, "Bash", None)
    assert v["classe"] == "reserve"


# --- Bash : une ligne de chaque table -------------------------------------------------------------

@pytest.mark.parametrize("verbe", aa.VERBES_SYSTEME)
def test_verbe_systeme_reserve(projet, verbe):
    assert classe(bash(projet, f"{verbe} quelque-chose")) == ("reserve", "systeme")


@pytest.mark.parametrize("sub, reservantes, liberantes, theme", aa.GIT_RESERVE,
                         ids=[r[0] for r in aa.GIT_RESERVE])
def test_git_reserve_par_ligne(projet, sub, reservantes, liberantes, theme):
    if reservantes is None:
        assert classe(bash(projet, f"git {sub} origin")) == ("reserve", theme)
        for o in liberantes:
            assert classe(bash(projet, f"git {sub} {o} user.name")) == ("libre", "projet"), o
    else:
        for o in reservantes:
            assert classe(bash(projet, f"git {sub} {o} b")) == ("reserve", theme), o
        assert classe(bash(projet, f"git {sub} b")) == ("libre", "projet")


def test_git_clean_f_groupe(projet):
    assert classe(bash(projet, "git clean -xdf")) == ("reserve", "branches")
    assert classe(bash(projet, "git clean -n")) == ("libre", "projet")


@pytest.mark.parametrize("sub", aa.GIT_RESEAU)
def test_git_reseau_par_ligne(projet, sub):
    assert classe(bash(projet, f"git {sub} https://gitlab.com/a/b.git")) == ("reserve", "reseau")
    assert bash(projet, f"git {sub} https://github.com/a/b.git")["classe"] == "libre"
    assert classe(bash(projet, f"git {sub} git@gitlab.com:a/b.git")) == ("reserve", "reseau")


def test_git_fetch_sans_hote_ecrit_reserve(projet):
    assert classe(bash(projet, "git fetch origin")) == ("reserve", "reseau")


def test_git_local_libre(projet):
    for c in ("git status", "git log --oneline -5", "git diff HEAD~1", "git commit -m 'msg'",
              "git -C src status", "git branch nouvelle", "git reset --soft HEAD~1"):
        assert classe(bash(projet, c)) == ("libre", "projet"), c


@pytest.mark.parametrize("verbe, options, premier_seul", aa.RESEAU, ids=[r[0] for r in aa.RESEAU])
def test_reseau_par_ligne(projet, verbe, options, premier_seul):
    hote = "exemple.com:/x" if verbe in ("scp", "rsync") else "exemple.com"   # scp/rsync : `hôte:`
    assert classe(bash(projet, f"{verbe} {hote}")) == ("reserve", "reseau")
    if verbe in ("curl", "wget"):
        assert bash(projet, f"{verbe} {options[0]} sortie.txt https://pypi.org/x")["classe"] == "libre"
    elif verbe in ("scp", "rsync"):
        assert classe(bash(projet, f"{verbe} a.txt moi@exemple.com:/x")) == ("reserve", "reseau")
        assert bash(projet, f"{verbe} a.txt b.txt")["classe"] == "libre"
    else:
        assert bash(projet, f"{verbe} github.com")["classe"] == "libre"


def test_hote_non_ecrit_dans_une_url_mais_user_at(projet):
    assert classe(bash(projet, "ssh moi@exemple.com ls")) == ("reserve", "reseau")


@pytest.mark.parametrize("verbe, suite", aa.DEPENDANCES, ids=[" ".join((r[0],) + r[1]) for r in aa.DEPENDANCES])
def test_dependance_autonome_par_ligne(projet, verbe, suite):
    assert classe(bash(projet, f"{verbe} {' '.join(suite)} httpx")) == ("autonome", "dependance")


@pytest.mark.parametrize("option", aa.OPTIONS_SOURCE)
def test_source_explicite_hors_liste_reservee(projet, option):
    assert classe(bash(projet, f"uv add {option} https://exemple.com/simple httpx")) == ("reserve", "reseau")
    assert classe(bash(projet, f"uv add {option} https://pypi.org/simple httpx")) == ("autonome", "dependance")


@pytest.mark.parametrize("source", ["git+https://gitlab.com/a/b.git", "https://exemple.com/x.whl",
                                    "--index-url=https://exemple.com/simple"])
def test_dependance_url_ou_git_hors_liste_reservee(projet, source):
    assert classe(bash(projet, f"pip install {source}")) == ("reserve", "reseau")


def test_dependance_git_vers_site_permis_autonome(projet):
    assert classe(bash(projet, "uv add git+https://github.com/a/b.git")) == ("autonome", "dependance")


@pytest.mark.parametrize("verbe", aa.VERBES_ILLISIBLES)
def test_verbe_illisible_reserve(projet, verbe):
    assert classe(bash(projet, f"{verbe} ls")) == ("reserve", "illisible")


@pytest.mark.parametrize("shell", aa.SHELLS)
def test_shell_c_decoupe(projet, shell):
    assert classe(bash(projet, f"{shell} -c 'git push'")) == ("reserve", "push")
    assert classe(bash(projet, f"{shell} -c 'ls src'")) == ("libre", "projet")
    assert classe(bash(projet, f"{shell} -c")) == ("reserve", "illisible")


@pytest.mark.parametrize("enveloppe", aa.ENVELOPPES)
def test_enveloppe_juge_la_commande_qui_suit(projet, enveloppe):
    prefixe = f"{enveloppe} 5" if enveloppe == "timeout" else enveloppe
    assert classe(bash(projet, f"{prefixe} git push")) == ("reserve", "push")


@pytest.mark.parametrize("premier, second", aa.ENVELOPPES_DOUBLES)
def test_enveloppe_double(projet, premier, second):
    assert classe(bash(projet, f"{premier} {second} git push")) == ("reserve", "push")
    # `pipx run <paquet>` récupère le paquet : autonome ; les autres enveloppes, libre
    attendu = ("autonome", "dependance") if (premier, second) == ("pipx", "run") else ("libre", "projet")
    assert classe(bash(projet, f"{premier} {second} pytest -q")) == attendu


@pytest.mark.parametrize("neutre", aa.CHEMINS_NEUTRES)
def test_chemins_neutres(projet, neutre):
    assert classe(bash(projet, f"ls > {neutre}")) == ("libre", "projet")


# --- Bash : ensemble ----------------------------------------------------------------------------

@pytest.mark.parametrize("commande", ["ls && git push", "git push && ls", "ls | git push",
                                      "ls; git push", "ls || git push", "(git push)", "{ git push; }"])
def test_commande_composee_la_plus_fermee_gagne(projet, commande):
    assert classe(bash(projet, commande)) == ("reserve", "push")


def test_reserve_l_emporte_sur_autonome(projet):
    assert classe(bash(projet, "uv add httpx && git push")) == ("reserve", "push")
    assert classe(bash(projet, "git push && uv add httpx")) == ("reserve", "push")


def test_autonome_l_emporte_sur_libre(projet):
    assert classe(bash(projet, "ls && uv add httpx && pytest")) == ("autonome", "dependance")


def test_plus_fermee_pure():
    l, a, r = ({"classe": c, "theme": c, "motif": c} for c in ("libre", "autonome", "reserve"))
    assert aa.plus_fermee([l, r, a])["classe"] == "reserve"
    assert aa.plus_fermee([r, l])["classe"] == "reserve"
    assert aa.plus_fermee([l, a, l])["classe"] == "autonome"
    assert aa.plus_fermee([])["classe"] == "libre"


def test_cd_dossier_puis_push(projet):
    assert classe(bash(projet, "cd src && git push")) == ("reserve", "push")


def test_cd_hors_projet_puis_relatif(projet, tmp_path):
    assert classe(bash(projet, f"cd {tmp_path} && ls")) == ("reserve", "hors_projet")
    assert classe(bash(projet, "cd && ls")) == ("reserve", "hors_projet")


def test_cd_dans_le_worktree_puis_claude(projet):
    """`.claude/` se juge relativement au worktree où l'on est."""
    assert classe(bash(projet, "cd .orga/worktrees/x && rm -rf .claude")) == ("reserve", "droits")


@pytest.mark.parametrize("commande", ["ls $HOME", "cat ${HOME}/x", "echo \"$HOME\"", "rm -rf $DOSSIER"])
def test_variable_illisible(projet, commande):
    assert classe(bash(projet, commande)) == ("reserve", "illisible")


def test_variable_entre_apostrophes_est_une_donnee(projet):
    assert classe(bash(projet, "echo '$HOME'")) == ("libre", "projet")


@pytest.mark.parametrize("commande", ["echo $(git push)", "ls `pwd`", "diff <(ls) <(ls src)",
                                      "echo \"$(ls)\""])
def test_substitution_illisible(projet, commande):
    assert classe(bash(projet, commande)) == ("reserve", "illisible")


def test_guillemets_desequilibres_illisible(projet):
    assert classe(bash(projet, "echo 'pas fermé")) == ("reserve", "illisible")


@pytest.mark.parametrize("commande", ["cat ../../etc/passwd", "ls ..", "cp a.txt ../a.txt",
                                      "cat src/../../x"])
def test_chemin_relatif_qui_remonte(projet, commande):
    assert classe(bash(projet, commande)) == ("reserve", "hors_projet")


def test_chemin_relatif_qui_remonte_mais_reste_dans_le_projet(projet):
    assert classe(bash(projet, "cat src/../note.md", cwd=projet)) == ("libre", "projet")


@pytest.mark.parametrize("commande", ["cat /etc/hosts", "ls ~", "cat ~/.zshrc", "touch /tmp/x",
                                      "ls --dir=/etc"])
def test_chemin_absolu_ou_tilde_hors_projet(projet, commande):
    assert classe(bash(projet, commande)) == ("reserve", "hors_projet")


def test_chemin_absolu_dans_le_projet_libre(projet):
    assert classe(bash(projet, f"cat {projet}/src/a.py")) == ("libre", "projet")


@pytest.mark.parametrize("commande, theme", [("cat .env", "secrets"), ("rm -rf .claude", "droits"),
                                             ("cp x .orga/etat/registre.sqlite", "droits"),
                                             ("echo x > .orga/projet.toml", "droits"),
                                             ("ls .git", "droits"), ("cat config/prod.pem", "secrets")])
def test_chemin_du_projet_dans_le_noyau(projet, commande, theme):
    assert classe(bash(projet, commande)) == ("reserve", theme)


def test_redirection_hors_projet(projet):
    assert classe(bash(projet, "ls > /tmp/sortie")) == ("reserve", "hors_projet")
    assert classe(bash(projet, "ls 2>&1 | head")) == ("libre", "projet")


def test_heredoc_vers_un_shell_juge(projet):
    assert classe(bash(projet, "bash <<EOF\ngit push\nEOF")) == ("reserve", "push")
    assert classe(bash(projet, "cat > src/n.txt <<'EOF'\ngit push $HOME\nEOF")) == ("libre", "projet")


def test_find_exec(projet):
    assert classe(bash(projet, "find . -name '*.py' -exec chmod +x {} ;")) == ("reserve", "systeme")


def test_commande_ordinaire_libre(projet):
    for c in ("pytest -q tests", "uv run pytest -q", "ls -la src", "grep -rn motif src",
              "python -m pytest", "mkdir -p src/nouveau && touch src/nouveau/a.py"):
        assert classe(bash(projet, c)) == ("libre", "projet"), c


def test_commande_absente_illisible(projet):
    assert classe(classer_autorisation(projet, AGENT, "Bash", {})) == ("reserve", "illisible")


def test_cwd_par_defaut_le_projet(projet):
    v = classer_autorisation(projet, AGENT, "Bash", {"command": "cat .env"})
    assert classe(v) == ("reserve", "secrets")


def test_fonction_pure_n_ecrit_rien(projet):
    avant = sorted(str(p) for p in projet.rglob("*"))
    bash(projet, "git push && uv add httpx")
    classer_autorisation(projet, AGENT, "Write", {"file_path": str(projet / "src" / "z.py")})
    assert sorted(str(p) for p in projet.rglob("*")) == avant


# === les trous du classement relevés par sondage ==========================================
# Un test par verbe ajouté, un par forme d'option.

DEP = ("autonome", "dependance")
RES = ("reserve", "reseau")
HORS = ("reserve", "hors_projet")
SYS = ("reserve", "systeme")


# --- 1. récupération et exécution d'un paquet distant -------------------------------------------

@pytest.mark.parametrize("commande", [
    "npx cowsay hi", "uvx ruff check", "pnpm dlx create-vite", "bunx tsc", "pipx install black",
    "pipx run black .", "uv tool install ruff", "uv tool run ruff", "pip download httpx",
    "pip3 download httpx", "python -m pip download httpx", "python3 -m pip download httpx",
    "yarn dlx create-vite", "npm exec cowsay", "pipx upgrade black", "pipx upgrade-all",
    "pipx inject black pkg", "uv tool upgrade ruff", "uv lock", "uv pip sync req.txt",
    "npm update", "pnpm update", "yarn upgrade", "bun add x", "bun install", "bun i",
    "cargo fetch", "cargo update", "go mod download", "go mod tidy",
])
def test_paquet_distant_autonome(projet, commande):
    assert classe(bash(projet, commande)) == DEP, commande


@pytest.mark.parametrize("commande", ["pip install -r requirements.txt", "pip install -e .",
                                      "pip install ./dist/x.whl", "uv pip install -r req.txt"])
def test_pip_install_local_reste_autonome(projet, commande):
    assert classe(bash(projet, commande)) == DEP


@pytest.mark.parametrize("commande", [
    "npx --registry https://exemple.com/ cowsay", "uvx --index-url https://exemple.com/simple ruff",
    "uvx --from git+https://gitlab.com/a/b ruff", "pipx install git+https://gitlab.com/a/b",
    "pipx run --index-url=https://exemple.com/simple black", "pnpm dlx --registry https://exemple.com x",
    "pip download https://exemple.com/x.whl", "uv tool install --index-url https://exemple.com/s ruff",
    "uv run --with httpx --index-url https://exemple.com/simple pytest",
    "uv run --with git+https://gitlab.com/a/b pytest",
])
def test_paquet_distant_hote_hors_liste_reserve(projet, commande):
    assert classe(bash(projet, commande)) == RES, commande


@pytest.mark.parametrize("commande", ["uvx --from git+https://github.com/a/b ruff",
                                      "pipx install --index-url https://pypi.org/simple black"])
def test_paquet_distant_site_permis_autonome(projet, commande):
    assert classe(bash(projet, commande)) == DEP


@pytest.mark.parametrize("commande", ["uv run --with httpx python x.py", "uv run --with=httpx pytest",
                                      "uv run --with-requirements r.txt pytest",
                                      "uv run --with-editable ./lib pytest",
                                      "uv run --python 3.12 --with httpx pytest"])
def test_uv_run_with_sans_offline_autonome(projet, commande):
    assert classe(bash(projet, commande)) == DEP, commande


@pytest.mark.parametrize("commande", ["uv run --offline --with httpx pytest",
                                      "uv run --with httpx --offline pytest",
                                      "uv run --no-index --with httpx pytest",
                                      "uv run --with-requirements r.txt --offline bash nav.sh"])
def test_uv_run_with_hors_ligne_libre(projet, commande):
    """Le cas de `nav.sh` d'ergonomie : rien n'est récupéré."""
    assert classe(bash(projet, commande)) == ("libre", "projet"), commande


def test_uv_run_offline_apres_la_commande_ne_libere_pas(projet):
    """`--offline` est ici un argument du programme lancé, pas de `uv`."""
    assert classe(bash(projet, "uv run --with httpx pytest --offline")) == DEP


def test_uv_run_juge_la_commande_lancee_apres_les_options_a_valeur(projet):
    assert classe(bash(projet, "uv run --with httpx git push")) == ("reserve", "push")
    assert classe(bash(projet, "uv run --python 3.12 git push")) == ("reserve", "push")
    assert classe(bash(projet, "uv run --offline --with httpx git push")) == ("reserve", "push")


# --- 2. installation hors du projet -----------------------------------------------------------

@pytest.mark.parametrize("option", ["-g", "--global", "--system", "--user", "--break-system-packages"])
@pytest.mark.parametrize("commande", ["pip install {o} httpx", "uv pip install {o} httpx",
                                      "npm install {o} x", "pnpm add {o} x", "yarn add {o} x",
                                      "uv add {o} httpx", "npx {o} cowsay"])
def test_dependance_hors_projet_par_option(projet, commande, option):
    assert classe(bash(projet, commande.format(o=option))) == HORS


@pytest.mark.parametrize("commande", [
    "npm install -g typescript", "npm i -gD typescript", "npm install -Dg typescript",
    "pnpm add --global x", "npm install --location=global x", "npm install --location global x",
    "yarn global add x", "uv pip install --system httpx", "pip install --user httpx",
    "pip install --break-system-packages httpx", "pip install --target /opt/x httpx",
    "pip install --target=/opt/x httpx", "pip install -t ../vendor httpx",
    "pip install --target ~/lib httpx", "npm install --prefix /opt/x x", "pip install --root /opt/x x",
    "cargo install ripgrep", "go install x@latest", "npm link", "npm unlink x",
    "uvx --user ruff", "pipx install --global black",
])
def test_installation_hors_du_projet_reservee(projet, commande):
    assert classe(bash(projet, commande)) == HORS, commande


@pytest.mark.parametrize("commande", ["pip install --target ./vendor httpx",
                                      "pip install --target=vendor httpx", "npm install --prefix src x",
                                      "uv add --group dev pytest", "npm install --global-style x",
                                      "uv pip install -r req.txt"])
def test_installation_dans_le_projet_reste_autonome(projet, commande):
    assert classe(bash(projet, commande)) == DEP, commande


# --- 3. gestionnaires et conteneurs système -----------------------------------------------------

VERBES_GESTIONNAIRES = ("brew", "port", "apt", "apt-get", "yum", "dnf", "docker", "podman",
                        "colima", "corepack", "softwareupdate", "mas", "systemctl", "service")
VERBES_GESTIONNAIRES_PLUS = ("aptitude", "dpkg", "rpm", "zypper", "pacman", "apk", "snap", "flatpak",
                             "nix", "nix-env", "docker-compose", "podman-compose", "buildah",
                             "nerdctl", "limactl", "kubectl", "scutil", "dscl", "sysctl", "shutdown",
                             "reboot", "halt", "hdiutil", "tmutil", "spctl", "csrutil", "mount",
                             "umount", "visudo", "passwd")


@pytest.mark.parametrize("verbe", VERBES_GESTIONNAIRES + VERBES_GESTIONNAIRES_PLUS)
def test_gestionnaire_systeme_reserve(projet, verbe):
    assert classe(bash(projet, f"{verbe} install x")) == SYS
    assert classe(bash(projet, f"ls && {verbe} list")) == SYS


@pytest.mark.parametrize("commande", [
    "npm config set registry https://exemple.com", "npm config delete registry", "npm config edit",
    "npm set registry https://exemple.com", "pnpm config set x y", "yarn config set x y",
    "pip config set global.index-url https://exemple.com", "pip config unset x", "pip config edit",
    "pip3 config set x y", "python -m pip config set x y", "python3 -m pip config unset x",
    "uv tool uninstall ruff", "pipx uninstall black", "pipx uninstall-all",
])
def test_ecriture_de_configuration_ou_desinstallation_reservee(projet, commande):
    assert classe(bash(projet, commande)) == SYS, commande


@pytest.mark.parametrize("commande", ["npm config get registry", "npm config list", "npm config ls",
                                      "pnpm config get x", "yarn config list", "pip config list",
                                      "pip config get global.index-url", "pip config debug",
                                      "python -m pip config list"])
def test_lecture_de_configuration_libre(projet, commande):
    assert classe(bash(projet, commande)) == ("libre", "projet"), commande


def test_config_lue_puis_ecrite_est_reservee(projet):
    assert classe(bash(projet, "npm config get registry && npm config set registry x")) == SYS


@pytest.mark.parametrize("commande", ["npm publish", "pnpm publish", "yarn publish", "cargo publish",
                                      "uv publish", "twine upload dist/*", "npm login", "npm adduser",
                                      "npm token create", "cargo login"])
def test_publication_reservee(projet, commande):
    assert classe(bash(projet, commande)) == ("reserve", "push"), commande


# --- 4. git submodule --------------------------------------------------------------------------

@pytest.mark.parametrize("sub", ["add", "update", "init", "sync"])
def test_git_submodule_sans_hote_ecrit_reserve(projet, sub):
    assert classe(bash(projet, f"git submodule {sub}")) == RES
    assert classe(bash(projet, f"git submodule --quiet {sub}")) == RES
    assert classe(bash(projet, f"git -C src submodule {sub} --recursive")) == RES


@pytest.mark.parametrize("sub", ["add", "update", "init", "sync"])
def test_git_submodule_hote_hors_liste_reserve(projet, sub):
    assert classe(bash(projet, f"git submodule {sub} https://exemple.com/a/b.git lib")) == RES
    assert classe(bash(projet, f"git submodule {sub} git@exemple.com:a/b.git lib")) == RES


@pytest.mark.parametrize("sub", ["add", "update", "init", "sync"])
def test_git_submodule_hote_permis_libre(projet, sub):
    assert classe(bash(projet, f"git submodule {sub} https://github.com/a/b.git lib")) == ("libre", "projet")
    assert classe(bash(projet, f"git submodule {sub} -b main git@github.com:a/b.git lib")) == ("libre", "projet")


def test_git_submodule_lecture_libre_et_foreach_jugee(projet):
    assert classe(bash(projet, "git submodule status")) == ("libre", "projet")
    assert classe(bash(projet, "git submodule foreach ls")) == ("libre", "projet")
    assert classe(bash(projet, "git submodule foreach git push")) == ("reserve", "push")
    assert classe(bash(projet, "git submodule foreach --recursive 'git push'")) == ("reserve", "push")


@pytest.mark.parametrize("sub", ["add", "pull", "push"])
def test_git_subtree_est_du_reseau(projet, sub):
    assert classe(bash(projet, f"git subtree {sub} --prefix=lib")) == RES
    assert classe(bash(projet, f"git subtree {sub} --prefix=lib https://exemple.com/a main")) == RES
    assert classe(bash(projet, f"git subtree {sub} --prefix=lib https://github.com/a main")) == ("libre", "projet")


# --- 5. hôtes de boucle locale ------------------------------------------------------------------

@pytest.mark.parametrize("commande", [
    "curl localhost:8000/x", "curl http://127.0.0.1:8000", "curl http://localhost:8000/x",
    "curl http://[::1]:8000/x", "curl [::1]:8000/x", "curl ::1", "curl 127.0.0.1:8000",
    "wget localhost:8000/x", "wget http://127.0.0.1:8000/x -O sortie.txt",
    "curl -s -o sortie.txt http://localhost:8000", "curl -d @src/a.json localhost:8000/x",
    "curl LOCALHOST:8000", "curl http://user@localhost:8000",
])
def test_boucle_locale_libre(projet, commande):
    assert classe(bash(projet, commande)) == ("libre", "projet"), commande


@pytest.mark.parametrize("url", ["http://localhost:8000", "http://127.0.0.1:8000/x",
                                 "http://[::1]:8000", "http://localhost/"])
def test_webfetch_boucle_locale_libre(projet, url):
    v = classer_autorisation(projet, AGENT, "WebFetch", {"url": url})
    assert classe(v) == ("libre", "projet"), url


@pytest.mark.parametrize("commande", [
    "curl http://localhost.evil.com", "curl localhost.evil.com", "curl http://127.0.0.1.evil.com",
    "curl http://localhost@evil.com/", "curl http://evil.com/localhost", "wget http://localhost.evil.com",
    "curl http://127.0.0.2:8000", "curl http://0.0.0.0:8000",
])
def test_faux_hotes_de_boucle_locale_restent_reserves(projet, commande):
    assert classe(bash(projet, commande)) == RES, commande


@pytest.mark.parametrize("url", ["http://localhost.evil.com", "http://localhost@evil.com/",
                                 "http://127.0.0.1.evil.com/x", "http://evil.com/localhost"])
def test_webfetch_faux_hotes_reserves(projet, url):
    assert classe(classer_autorisation(projet, AGENT, "WebFetch", {"url": url})) == RES, url


@pytest.mark.parametrize("commande, attendu", [
    ("curl http://localhost:8000 https://exemple.com", RES),
    ("curl http://localhost:8000 -o /etc/x", HORS),
    ("curl http://localhost:8000 && git push", ("reserve", "push")),
    ("curl -x http://exemple.com:3128 http://localhost:8000", RES),
    ("curl --proxy http://exemple.com:3128 http://localhost:8000", RES),
    ("curl --connect-to localhost:80:exemple.com:80 http://localhost", RES),
    ("curl --resolve localhost:80:1.2.3.4 http://localhost", RES),
    ("curl -sx http://exemple.com:3128 http://localhost:8000", RES),
    ("curl -sx github.com:3128 http://localhost:8000", RES),
    ("curl -x github.com:3128 http://localhost:8000", RES),
    ("ssh localhost ls", RES), ("nc localhost 80", RES), ("scp a.txt localhost:/x", RES),
])
def test_boucle_locale_n_ouvre_rien_d_autre(projet, commande, attendu):
    assert classe(bash(projet, commande)) == attendu, commande


# --- 6. un interpréteur lancé sur du code : opaque, donc libre (documenté, pas changé) -------------

@pytest.mark.parametrize("commande", ["python script.py", "python3 script.py", "python -c 'print(1)'",
                                      "python -c 'import os; os.system(\"echo\")'", "bash script.sh",
                                      "sh script.sh", "zsh script.sh", "node x.js", "node -e 'x()'",
                                      "ruby x.rb", "perl x.pl"])
def test_interpreteur_opaque_reste_libre(projet, commande):
    """Le contenu d'un script est opaque au classement : le bac à sable et la garde le bornent. Le
    changer est une décision (voir le commentaire de tête des tables), pas un accident."""
    assert classe(bash(projet, commande)) == ("libre", "projet"), commande
