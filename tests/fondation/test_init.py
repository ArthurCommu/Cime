import json
import os
import sqlite3
import types
from pathlib import Path

import pytest

from cime.fondation import init
from cime.fondation.nom import NOM
from cime.fondation.projet import lire_manifeste
from cime.fondation.reglages import (
    INTERDITS_COORDINATEUR, EVENEMENTS, fusionner, reglages, _avec_rtk,
)


EXE = "/opt/outils/bin/cime"


@pytest.fixture(autouse=True)
def cime_installe(monkeypatch):
    """Par défaut, `cime` est « installé » à un chemin absolu connu (indépendant du PATH du test)."""
    monkeypatch.setattr(init, "executable_cime", lambda: EXE)


def args(dossier, utilisateur="Camille", nom_projet=None, prefixe=None, **autres):
    return types.SimpleNamespace(dossier=str(dossier), utilisateur=utilisateur,
                                 nom_projet=nom_projet, prefixe=prefixe, **autres)


def fichiers(racine: Path) -> set[str]:
    return {str(p.relative_to(racine)) for p in racine.rglob("*")
            if p.is_file() and ".git" not in p.relative_to(racine).parts
            and ".orga/etat" not in str(p.relative_to(racine))}


def test_dossier_vide(tmp_path):
    p = tmp_path / "mon-projet"
    assert init.executer(args(p)) == 0
    assert (p / ".git").is_dir()
    for f in ("CLAUDE.md", ".orga/projet.toml", ".orga/org-chart.md",
              ".orga/socle/assistant.md", ".orga/teams/assistant/CLAUDE.md",
              ".orga/teams/verification/mandate.md", ".orga/templates/coordinateur-CLAUDE.md"):
        assert (p / f).is_file(), f
    for sous in init.DOSSIERS_EQUIPE:
        assert (p / ".orga/teams/verification" / sous).is_dir()
        assert not (p / ".orga/teams/assistant" / sous).exists()
    # l'intégration est facultative : `init` ne la crée plus
    assert not (p / ".orga/teams/integration").exists()
    assert not (p / "VARIABLES.md").exists()
    for f in fichiers(p):
        if (p / f).suffix in (".md", ".toml", ".json"):
            assert "{{" not in (p / f).read_text(), f
    m = lire_manifeste(p)
    assert m.nom == "mon-projet" and m.prefixe == "mp"
    assert "Camille" in (p / ".orga/socle/assistant.md").read_text() or \
        "Camille" in (p / "CLAUDE.md").read_text()
    conn = sqlite3.connect(p / ".orga/etat/registre.sqlite")
    tables = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")
              if not r[0].startswith("sqlite_")}
    assert {"messages", "evenements", "journal", "courriers", "transitions",
            "obligations", "ordres", "facteur", "occupation", "reglages_projet"} == tables
    assert ".orga/etat/" in (p / ".gitignore").read_text().splitlines()
    commun = json.loads((p / ".claude/settings.json").read_text())
    agent = json.loads((p / ".claude/settings-agent.json").read_text())
    coord = json.loads((p / ".claude/settings-coordinateur.json").read_text())
    assert set(commun["hooks"]) == set(EVENEMENTS) | {"PreToolUse"}
    assert commun == reglages(p.resolve(), "main", executable=EXE)
    assert agent == reglages(p.resolve(), "main", "agent", EXE)
    assert coord == reglages(p.resolve(), "main", "coordinateur", EXE)
    assert (p / ".orga/etat/tmp").is_dir() and (p / ".orga/etat/memoire").is_dir()
    assert "sandbox" not in commun and "sandbox" not in agent and "sandbox" not in coord
    assert set(coord["permissions"]["deny"]) - set(agent["permissions"]["deny"]) == \
        set(_avec_rtk(list(INTERDITS_COORDINATEUR)))
    assert len(INTERDITS_COORDINATEUR) == 14
    assert set(agent["permissions"]["deny"]) - set(commun["permissions"]["deny"]) <= \
        set(coord["permissions"]["deny"])
    assert set(commun["permissions"]["deny"]) - set(coord["permissions"]["deny"]) == set()
    assert commun["permissions"]["allow"] == coord["permissions"]["allow"]


def test_sortie_demande_d_approuver_le_dossier(tmp_path, capsys):
    p = tmp_path / "x"
    init.executer(args(p))
    sortie = capsys.readouterr().out
    assert f"cd {p.resolve()} && claude" in sortie and "approuver le dossier" in sortie

PORTRAIT = ".orga/socle/comment-travaille-l-utilisateur.md"


def test_portrait_neutre_a_l_installation(tmp_path):
    p = tmp_path / "x"
    init.executer(args(p))
    texte = (p / PORTRAIT).read_text()
    assert len(texte.splitlines()) < 30
    assert "ne pas modifier" not in texte.lower()
    assert not any(c in texte for c in '«»"“”')
    for mot in ("Arth" + "ur", "sé" + "rie"):  # mots de l'organisation d'origine
        assert mot not in texte.lower()
    assert "{{" not in texte and "Camille" in texte


def test_autres_fichiers_du_socle_gardent_l_entete(tmp_path):
    p = tmp_path / "x"
    init.executer(args(p))
    socle = [f for f in fichiers(p) if f.startswith(".orga/socle/") and f != PORTRAIT]
    assert socle
    for f in socle:
        premiere = (p / f).read_text().splitlines()[0]
        assert premiere.startswith("<!-- socle ") and "ne pas modifier" in premiere, f
    assert "<!-- socle " not in (p / PORTRAIT).read_text().splitlines()[0]


def test_portrait_enrichi_survit_a_un_second_init(tmp_path):
    p = tmp_path / "x"
    init.executer(args(p))
    enrichi = (p / PORTRAIT).read_bytes() + "\n- 2026-10-12 : préfère les réponses courtes, « une phrase ».\n".encode()
    (p / PORTRAIT).write_bytes(enrichi)
    assert init.executer(args(p)) == 0
    assert (p / PORTRAIT).read_bytes() == enrichi


def test_entete_socle(tmp_path):
    p = tmp_path / "x"
    init.executer(args(p))
    for f in fichiers(p):
        texte = (p / f).read_text(errors="ignore") if (p / f).suffix in (".md", ".toml") else None
        if f == PORTRAIT:
            continue  # seule exception : propre au projet, voir les tests du portrait
        if f.startswith(".orga/socle/"):
            assert texte.startswith("<!-- socle "), f
            assert "source : gabarits/socle/" in texte.splitlines()[0]
            assert init._version() in texte.splitlines()[0]
        elif texte is not None:
            assert not texte.startswith("<!-- socle "), f


def test_second_passage(tmp_path, capsys):
    p = tmp_path / "x"
    init.executer(args(p))
    avant = {f: (p / f).stat().st_mtime_ns for f in fichiers(p)} | \
        {f: (p / f).stat().st_mtime_ns for f in (".claude/settings.json",)}
    capsys.readouterr()
    assert init.executer(args(p)) == 0
    sortie = capsys.readouterr().out
    assert "ajouté" not in sortie and "complété" not in sortie
    assert "déjà présent" in sortie
    apres = {f: (p / f).stat().st_mtime_ns for f in avant}
    assert avant == apres


def test_gitignore_deux_lignes_sans_doublon(tmp_path):
    p = tmp_path / "mon-projet"
    rapport = init.installer(args(p))
    assert (p / ".gitignore").read_text() == ".orga/etat/\n.orga/worktrees/\n"
    assert ".gitignore (.orga/etat/)" in rapport["ajouté"]
    assert ".gitignore (.orga/worktrees/)" in rapport["ajouté"]
    assert ".orga/etat/essais" in rapport["ajouté"]
    assert ".orga/worktrees" in rapport["ajouté"]
    rapport = init.installer(args(p))
    assert (p / ".gitignore").read_text() == ".orga/etat/\n.orga/worktrees/\n"
    assert ".gitignore (.orga/etat/)" in rapport["déjà présent"]
    assert ".gitignore (.orga/worktrees/)" in rapport["déjà présent"]
    assert ".orga/etat/essais" in rapport["déjà présent"]
    assert ".orga/worktrees" in rapport["déjà présent"]


def test_gitignore_ajoute_seulement_la_ligne_manquante(tmp_path):
    p = tmp_path / "mon-projet"
    (p / ".orga" / "etat").mkdir(parents=True)
    (p / ".gitignore").write_text("*.log\n.orga/etat/")
    rapport = init.installer(args(p))
    assert (p / ".gitignore").read_text() == "*.log\n.orga/etat/\n.orga/worktrees/\n"
    assert ".gitignore (.orga/etat/)" in rapport["déjà présent"]
    assert ".gitignore (.orga/worktrees/)" in rapport["complété"]


def test_projet_existant(tmp_path, capsys):
    p = tmp_path / "existant"
    (p / ".orga").mkdir(parents=True)
    (p / ".claude").mkdir()
    (p / "CLAUDE.md").write_text("le mien\n")
    (p / ".orga/org-chart.md").write_text("mon organigramme\n")
    (p / ".gitignore").write_text("*.log")
    perso = {"model": "x", "permissions": {"allow": ["Bash(ls*)"], "deny": ["Bash(rm*)"]},
             "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "mon-hook"}]}]}}
    (p / ".claude/settings.json").write_text(json.dumps(perso))
    assert init.executer(args(p)) == 0
    assert (p / "CLAUDE.md").read_text() == "le mien\n"
    assert (p / ".orga/org-chart.md").read_text() == "mon organigramme\n"
    assert (p / ".gitignore").read_text() == "*.log\n.orga/etat/\n.orga/worktrees/\n"
    r = json.loads((p / ".claude/settings.json").read_text())
    assert r["model"] == "x"
    assert r["permissions"]["allow"][0] == "Bash(ls*)" and r["permissions"]["deny"][0] == "Bash(rm*)"
    assert r["hooks"]["Stop"][0] == perso["hooks"]["Stop"][0]
    assert {"hooks": [{"type": "command", "command": f"{EXE} hook Stop",
                       "timeout": 30}]} in r["hooks"]["Stop"]
    sortie = capsys.readouterr().out
    assert "complété" in sortie and "CLAUDE.md" in sortie and "hooks.Stop" in sortie
    assert (p / ".orga/projet.toml").is_file()


def test_prefixe_par_defaut():
    assert init.prefixe_par_defaut("outil-controle") == "oc"
    assert init.prefixe_par_defaut("Mon_Super projet") == "msp"


def test_prefixe_avec_tiret_accepte(tmp_path, capsys):
    assert init.executer(args(tmp_path / "x", prefixe="mon-projet")) == 0
    assert lire_manifeste(tmp_path / "x").prefixe == "mon-projet"


def test_prefixe_invalide(tmp_path, capsys):
    assert init.executer(args(tmp_path / "x", prefixe="Mon_Projet")) == 2
    assert "préfixe invalide" in capsys.readouterr().err
    assert not (tmp_path / "x" / ".orga").exists()


def test_variable_inconnue():
    with pytest.raises(init.ErreurInit):
        init._remplacer("{{inconnue}}", {}, "g.md")


def test_fusionner_pur():
    nouveau = reglages(Path("/a/b"), "main")
    vide, ajouts = fusionner({}, nouveau)
    assert vide == nouveau and ajouts
    meme, rien = fusionner(vide, nouveau)
    assert meme == vide and rien == []
    existant = {"permissions": {"allow": ["Bash(ls*)"]}}
    copie = json.loads(json.dumps(existant))
    fusion, _ = fusionner(existant, nouveau)
    assert existant == copie
    assert fusion["permissions"]["allow"][0] == "Bash(ls*)"


def test_forme_des_regles():
    r = reglages(Path("/opt/x/projet"), "main")
    allow, deny = r["permissions"]["allow"], r["permissions"]["deny"]
    assert "Read(//opt/x/projet/**)" in allow and "Edit(//opt/x/projet/**)" in allow
    assert "Read(//opt/x/projet/.orga/worktrees/**)" in allow
    assert "Edit(//opt/x/projet/.orga/worktrees/**)" in allow
    assert not [a for a in allow if "projet-*" in a]
    assert not any(a.startswith("Write(") for a in allow)
    assert "Bash(git -C /opt/x/projet merge*)" in reglages(
        Path("/opt/x/projet"), "main", "agent")["permissions"]["deny"]
    assert "Bash(git -C /opt/x/projet/.orga/worktrees/* commit*)" in allow
    assert "Bash(git -C /opt/x/projet/.orga/worktrees/* merge*)" in allow
    assert "matcher" not in r["hooks"]["PreToolUse"][0]
    assert r["hooks"]["PermissionRequest"][0]["hooks"][0]["timeout"] >= 5


# --- hooks : un exécutable `cime` qui existe vraiment -------------------------

def _commandes_hooks(p):
    r = json.loads((p / ".claude/settings.json").read_text())
    return {e: g["hooks"][0]["command"] for e, groupes in r["hooks"].items() for g in groupes}


def test_hooks_au_chemin_absolu(tmp_path):
    p = tmp_path / "x"
    assert init.executer(args(p)) == 0
    commandes = _commandes_hooks(p)
    assert commandes["Stop"] == f"{EXE} hook Stop"
    assert commandes["PreToolUse"].endswith(f"{EXE} hook PreToolUse; c=$?; [ $c -eq 0 ] || exit 2")
    assert "exec " not in commandes["PreToolUse"]
    assert not any(c.startswith(f"{NOM} ") for c in commandes.values())


def test_sans_cime_refus_sans_rien_ecrire(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(init, "executable_cime", lambda: None)
    p = tmp_path / "x"
    assert init.executer(args(p)) == 2
    err = capsys.readouterr().err
    assert "introuvable sur le PATH" in err and "--hooks-sans-cime" in err
    assert "uv tool install" in err
    assert not (p / ".orga").exists() and not (p / ".claude").exists()


def test_sans_cime_option_explicite_ecrit_le_nom_nu_et_avertit(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(init, "executable_cime", lambda: None)
    p = tmp_path / "x"
    assert init.executer(args(p, hooks_sans_cime=True)) == 0
    assert _commandes_hooks(p)["PreToolUse"] == f"{NOM} hook PreToolUse"
    assert "avertissements" in capsys.readouterr().out


def test_avertissement_venv_local(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(init, "executable_cime", lambda: "/depot/.venv/bin/cime")
    init.executer(args(tmp_path / "x"))
    assert "venv local" in capsys.readouterr().out


def test_executable_cime_est_absolu(tmp_path, monkeypatch):
    exe = tmp_path / "bin" / NOM
    exe.parent.mkdir()
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    monkeypatch.undo()
    monkeypatch.setenv("PATH", str(exe.parent))
    assert init.executable_cime() == str(exe)
    monkeypatch.setenv("PATH", str(tmp_path / "vide"))
    assert init.executable_cime() is None


def test_garde_hook_sort_en_2_avec_message_si_l_executable_a_disparu(tmp_path):
    """Le hook PreToolUse écrit par init, exécuté par sh comme Claude Code le fait."""
    import subprocess
    commande = reglages(tmp_path, "main", executable=str(tmp_path / "disparu"))[
        "hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    r = subprocess.run(["/bin/sh", "-c", commande], capture_output=True, text=True, input="{}")
    assert r.returncode == 2 and "exécutable introuvable" in r.stderr
    assert "la garde ne peut pas s'exécuter" in r.stderr


def test_garde_hook_execute_l_executable_present(tmp_path):
    import subprocess
    exe = tmp_path / "avec espace" / NOM
    exe.parent.mkdir()
    exe.write_text('#!/bin/sh\necho "recu: $@"\n')
    exe.chmod(0o755)
    for ev in ("PreToolUse", "Stop"):
        groupes = reglages(tmp_path, "main", executable=str(exe))["hooks"][ev]
        r = subprocess.run(["/bin/sh", "-c", groupes[0]["hooks"][0]["command"]],
                           capture_output=True, text=True)
        assert r.returncode == 0 and r.stdout == f"recu: hook {ev}\n"


def test_fusion_remplace_un_hook_nom_nu_sans_le_doubler():
    ancien = reglages(Path("/p"), "main")           # nom nu (anciens projets)
    nouveau = reglages(Path("/p"), "main", executable=EXE)
    fusion, ajouts = fusionner(ancien, nouveau)
    assert fusion["hooks"] == nouveau["hooks"]
    remplaces = [a for a in ajouts if a.startswith("remplacé : hooks.")]
    assert len(remplaces) == len(EVENEMENTS) + 1
    assert any(a.startswith("remplacé : hooks.PreToolUse : cime hook PreToolUse → ")
               and "c=$?" in a for a in remplaces)
    assert not [a for a in ajouts if a.startswith("hooks")]
    _, rien = fusionner(fusion, nouveau)
    assert rien == []


def _groupe_bash(commande: str) -> dict:
    """Forme d'avant : la garde Bash, sous `matcher: Bash`."""
    return {"matcher": "Bash", "hooks": [{"type": "command", "command": commande}]}


def test_fusion_remplace_le_groupe_bash_sans_le_doubler():
    nouveau = reglages(Path("/p"), "main", executable=EXE)
    voulu = nouveau["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    ancien = {"hooks": {"PreToolUse": [_groupe_bash(voulu)]}}
    fusion, ajouts = fusionner(ancien, nouveau)
    assert fusion["hooks"]["PreToolUse"] == nouveau["hooks"]["PreToolUse"]
    assert "remplacé : hooks.PreToolUse : matcher Bash → tous les outils" in ajouts
    _, rien = fusionner(fusion, nouveau)
    assert rien == []


def test_fusion_remplace_le_groupe_bash_au_nom_nu_et_garde_le_hook_personnel():
    nouveau = reglages(Path("/p"), "main", executable=EXE)
    perso = {"type": "command", "command": "mon-script"}
    ancien = {"hooks": {"PreToolUse": [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": f"{NOM} hook PreToolUse"},
                                      perso]},
        _groupe_bash("/autre/cime hook PreToolUse"),
    ]}}
    fusion, ajouts = fusionner(ancien, nouveau)
    groupes = fusion["hooks"]["PreToolUse"]
    # le hook personnel reste, sous le même filtre que dans le projet d'origine
    assert {"matcher": "Bash", "hooks": [perso]} in groupes
    # le groupe Bash d'une autre commande (un autre `cime`) n'est pas touché
    assert _groupe_bash("/autre/cime hook PreToolUse") in groupes
    assert nouveau["hooks"]["PreToolUse"][0] in groupes
    assert sum(1 for g in groupes if g.get("matcher") == "Bash") == 2
    assert "remplacé : hooks.PreToolUse : matcher Bash → tous les outils" in ajouts
    _, rien = fusionner(fusion, nouveau)
    assert rien == []


def test_fusion_ne_touche_ni_hook_personnel_ni_autre_chemin_ni_nom_nu_voulu():
    nouveau = reglages(Path("/p"), "main", executable=EXE)
    perso = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "mon-script"}]}],
                       "SessionEnd": [{"hooks": [{"type": "command",
                                                  "command": "/autre/cime hook SessionEnd"}]}]}}
    fusion, ajouts = fusionner(perso, nouveau)
    assert perso["hooks"]["Stop"][0] in fusion["hooks"]["Stop"]
    assert fusion["hooks"]["SessionEnd"] == perso["hooks"]["SessionEnd"]
    assert not [a for a in ajouts if a.startswith("remplacé")]
    # --hooks-sans-cime : le nouveau est lui-même en nom nu, rien n'est réécrit
    ancien = reglages(Path("/p"), "main")
    fusion, ajouts = fusionner(ancien, reglages(Path("/p"), "main"))
    assert fusion == ancien and ajouts == []


def test_init_annonce_le_remplacement_puis_second_passage_muet(tmp_path, capsys):
    p = tmp_path / "x"
    init.executer(args(p))
    cible = p / ".claude" / "settings.json"
    donnees = json.loads(cible.read_text())
    for ev, groupes in donnees["hooks"].items():
        for g in groupes:
            g["hooks"][0]["command"] = f"{NOM} hook {ev}"      # projet d'avant 868dda4
    cible.write_text(json.dumps(donnees))
    capsys.readouterr()
    init.executer(args(p))
    assert f"remplacé : hooks.PreToolUse : {NOM} hook PreToolUse → " in capsys.readouterr().out
    assert _commandes_hooks(p)["Stop"] == f"{EXE} hook Stop"
    capsys.readouterr()
    init.executer(args(p))
    assert "remplacé" not in capsys.readouterr().out


def test_init_remplace_le_groupe_bash_et_annonce_puis_second_passage_muet(tmp_path, capsys):
    p = tmp_path / "x"
    init.executer(args(p))
    cible = p / ".claude" / "settings.json"
    donnees = json.loads(cible.read_text())
    voulu = donnees["hooks"]["PreToolUse"][0]["hooks"]
    donnees["hooks"]["PreToolUse"] = [{"matcher": "Bash", "hooks": voulu}]   # forme d'avant
    cible.write_text(json.dumps(donnees))
    capsys.readouterr()
    init.executer(args(p))
    assert "remplacé : hooks.PreToolUse : matcher Bash → tous les outils" in \
        capsys.readouterr().out
    groupes = json.loads(cible.read_text())["hooks"]["PreToolUse"]
    assert len(groupes) == 1 and "matcher" not in groupes[0]
    init.executer(args(p))
    assert "remplacé" not in capsys.readouterr().out


def test_hooks_sans_cime_ne_reecrit_rien(tmp_path, monkeypatch, capsys):
    p = tmp_path / "x"
    init.executer(args(p))
    avant = (p / ".claude" / "settings.json").read_text()
    monkeypatch.setattr(init, "executable_cime", lambda: None)
    init.executer(args(p, hooks_sans_cime=True))
    assert (p / ".claude" / "settings.json").read_text() == avant
    assert "remplacé" not in capsys.readouterr().out


LECTURES = ("git status*", "git log*", "git diff*", "git show*", "git worktree list*")


@pytest.mark.parametrize("role", ["commun", "coordinateur"])
def test_jumelles_rtk(role):
    r = reglages(Path("/opt/x/projet"), "main", role)
    allow, deny = r["permissions"]["allow"], r["permissions"]["deny"]
    for lecture in LECTURES:
        assert f"Bash({lecture})" in allow and f"Bash(rtk {lecture})" in allow
    assert [a for a in allow if a.startswith("Bash(rtk ")] == [f"Bash(rtk {l})" for l in LECTURES]
    for regle in deny:
        if regle.startswith("Bash(") and not regle.startswith("Bash(rtk "):
            assert f"Bash(rtk {regle[5:]}" in deny, regle
    if role == "coordinateur":
        for regle in INTERDITS_COORDINATEUR:
            assert f"Bash(rtk {regle[5:]}" in deny


# --- init --lancer ------------------------------------------------------------

@pytest.fixture
def lancement(monkeypatch):
    appels = []

    def faux(projet, modele=None):
        appels.append((projet, modele))
        return faux.retour
    faux.retour = ("neuf-assistant", 0)
    monkeypatch.setattr(init.lancer, "lancer_assistant", faux)
    return types.SimpleNamespace(appels=appels, retour=lambda r: setattr(faux, "retour", r))


def test_sans_lancer_rien_ne_change(tmp_path, lancement, capsys):
    assert init.executer(args(tmp_path / "x")) == 0
    assert lancement.appels == []
    assert "lancer assistant" in capsys.readouterr().out


def test_lancer_assistant_lance_apres_init_sur_le_chemin_reel(tmp_path, lancement, capsys):
    vrai = tmp_path / "vrai"
    vrai.mkdir()
    (tmp_path / "lien").symlink_to(vrai)
    assert init.executer(args(tmp_path / "lien" / "neuf", lancer=True, modele="m")) == 0
    assert lancement.appels == [(vrai.resolve() / "neuf", "m")]
    assert (vrai / "neuf" / ".orga/projet.toml").is_file()
    assert "tmux attach -t neuf-assistant" in capsys.readouterr().out


def test_lancer_ecran_a_approuver_code_3(tmp_path, lancement, capsys):
    lancement.retour(("neuf-assistant", 3))
    assert init.executer(args(tmp_path / "neuf", lancer=True)) == 3
    sortie = capsys.readouterr().out
    assert "attend que tu approuves le dossier" in sortie
    assert "tmux attach -t neuf-assistant" in sortie


def test_lancer_echec_garde_le_code(tmp_path, lancement, capsys):
    lancement.retour(("", 1))
    assert init.executer(args(tmp_path / "neuf", lancer=True)) == 1
    assert "a échoué (code 1)" in capsys.readouterr().out


def test_init_refuse_donc_pas_de_lancement(tmp_path, lancement, monkeypatch):
    monkeypatch.setattr(init, "executable_cime", lambda: None)
    assert init.executer(args(tmp_path / "neuf", lancer=True)) == 2
    assert lancement.appels == []


# --- cime etat : la conversation privée reste masquée -----

def test_etat_appelle_instantane_sans_complet_et_sans_option_pour_le_lever(
        tmp_path, monkeypatch, capsys):
    from cime import cli, observation
    from cime.fondation.nom import VAR_PROJET
    p = tmp_path / "x"
    init.executer(args(p))
    appels = []
    monkeypatch.setattr(observation, "instantane",
                        lambda *a, **k: appels.append((a, k)) or {"ok": 1})
    monkeypatch.setenv(VAR_PROJET, str(p))
    assert cli.main(["etat"]) == 0
    assert appels == [((p,), {})]
    sous = cli._parser()._subparsers._group_actions[0].choices["etat"]
    options = {o for a in sous._actions for o in a.option_strings}
    assert options == {"-h", "--help"}
    with pytest.raises(SystemExit):
        cli._parser().parse_args(["etat", "--complet"])


def test_servir_laisse_le_systeme_choisir_le_port(tmp_path, monkeypatch):
    from cime import cli, hote
    from cime.fondation.nom import VAR_PROJET
    p = tmp_path / "x"
    init.executer(args(p))
    appels = []
    monkeypatch.setattr(hote, "servir", lambda projet, port: appels.append((projet, port)))
    monkeypatch.setenv(VAR_PROJET, str(p))
    assert cli.main(["servir"]) == 0
    assert cli.main(["servir", "--port", "8123"]) == 0
    assert [port for _, port in appels] == [0, 8123]
    assert not hasattr(cli, "_port_libre")


def test_fusion_sur_un_settings_1_10_ajoute_stopfailure_et_le_timeout_de_stop():
    from cime.fondation.reglages import fusionner, reglages
    voulu = reglages(Path("/p"), "main", "agent", "/usr/bin/cime")
    ancien = {"hooks": {"Stop": [{"hooks": [{"type": "command",
                                             "command": "/usr/bin/cime hook Stop"}]}],
                        "PostToolUse": [{"hooks": [{"type": "command",
                                                    "command": "/usr/bin/cime hook PostToolUse"}]}]},
              "model": "x"}
    fusion, ajouts = fusionner(ancien, voulu)
    stop = fusion["hooks"]["Stop"]
    assert len(stop) == 1 and stop[0]["hooks"][0]["timeout"] == 150
    assert "hooks.StopFailure : /usr/bin/cime hook StopFailure" in ajouts
    assert "hooks.Stop : timeout 150" in ajouts
    assert "timeout" not in fusion["hooks"]["PostToolUse"][0]["hooks"][0]
    assert fusion["model"] == "x"
    # idempotent
    encore, rien = fusionner(fusion, voulu)
    assert encore == fusion and rien == []
    # un timeout déjà choisi n'est pas changé
    perso = {"hooks": {"Stop": [{"hooks": [{"type": "command",
                                            "command": "/usr/bin/cime hook Stop", "timeout": 7}]}]}}
    assert fusionner(perso, voulu)[0]["hooks"]["Stop"][0]["hooks"][0]["timeout"] == 7


# --- init et dépôts git imbriqués (défaut de l'essai réel) -----------------------------------

def _git(dossier, *a):
    import subprocess
    return subprocess.run(["git", "-C", str(dossier), *a], capture_output=True, text=True, check=True).stdout


def _depot_parent(tmp_path):
    parent = tmp_path / "parent"
    parent.mkdir()
    _git(parent, "init", "-b", "main")
    (parent / "a.txt").write_text("a\n")
    _git(parent, "add", "a.txt")
    _git(parent, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "x")
    return parent


def test_init_a_la_racine_d_un_depot_ne_cree_pas_de_git(tmp_path):
    p = tmp_path / "depot"
    p.mkdir()
    _git(p, "init", "-b", "main")
    rapport = init.installer(args(p))
    assert not any(l.startswith(".git ") for l in rapport["ajouté"])


def test_init_dans_un_sous_dossier_cree_un_depot_propre(tmp_path):
    parent = _depot_parent(tmp_path)
    avant = (_git(parent, "rev-parse", "HEAD"), _git(parent, "status", "--porcelain", "-uno"),
             _git(parent, "ls-files"))
    p = parent / "sous" / "projet"
    rapport = init.installer(args(p))
    assert (p / ".git").is_dir()
    assert Path(_git(p, "rev-parse", "--show-toplevel").strip()).resolve() == p.resolve()
    assert any(l.startswith(".git (dépôt propre : le dossier est dans le dépôt")
               and str(parent.resolve()) in l for l in rapport["ajouté"])
    assert (_git(parent, "rev-parse", "HEAD"), _git(parent, "status", "--porcelain", "-uno"),
            _git(parent, "ls-files")) == avant
    again = init.installer(args(p))                                     # idempotence
    assert not any(l.startswith(".git ") for l in again["ajouté"])


def test_init_hors_de_tout_depot_comme_avant(tmp_path):
    p = tmp_path / "libre"
    rapport = init.installer(args(p))
    assert ".git (branche main)" in rapport["ajouté"] and (p / ".git").is_dir()


def test_init_cree_les_tickets_et_ne_les_ecrase_pas(tmp_path):
    dossier = tmp_path / "p"
    init.installer(args(dossier))
    lisezmoi = dossier / ".orga" / "tickets" / "LISEZMOI.md"
    texte = lisezmoi.read_text(encoding="utf-8")
    assert texte.startswith("# Tickets — signalements sur Cime venus d'ailleurs")
    assert "Un ticket traité reste ici : c'est l'historique." in texte
    lisezmoi.write_text("modifié par l'utilisateur\n", encoding="utf-8")
    rapport = init.installer(args(dossier))
    assert lisezmoi.read_text(encoding="utf-8") == "modifié par l'utilisateur\n"
    assert ".orga/tickets/LISEZMOI.md" in rapport["déjà présent"]
