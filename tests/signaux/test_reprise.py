import sqlite3

import pytest

from aide import cime, fabriquer_projet
from cime.fondation.registre import horodatage, ouvrir
from cime.signaux import reprise


@pytest.fixture
def projet(tmp_path, monkeypatch):
    racine = fabriquer_projet(tmp_path / "depot")
    monkeypatch.setenv("CIME_PROJET", str(racine))
    monkeypatch.delenv("CLAUDECODE", raising=False)
    (racine / ".orga/teams/x/tasks/in-progress/travail.md").write_text("t")
    (racine / ".orga/contracts").mkdir()
    titres = [f"## 2026-10-0{i} — décision {i}" for i in range(9, 2, -1)]
    (racine / ".orga/contracts/CHANGELOG.md").write_text("# Historique\n\n" + "\n\n".join(
        f"{t}\n\n- détail" for t in titres))
    return racine


def envoyer(monkeypatch, de, a, nature, *extra, resume="r"):
    return cime(monkeypatch, de, "envoyer", "--a", a, "--nature", nature, *extra, resume)


def test_reprise_sur_un_registre_fabrique(projet, monkeypatch, capsys):
    envoyer(monkeypatch, "worker-x-t", "coord-x", "question", resume="quelle API ?")
    envoyer(monkeypatch, "coord-x", "assistant", "demande_accord", "--objet", "fusion:x:abc",
            resume="fusionner x")
    envoyer(monkeypatch, "assistant", "utilisateur", "decision_utilisateur", "--objet", "chantier:x:2",
            resume="ouvrir la phase 2 ?")
    envoyer(monkeypatch, "assistant", "coord-x", "consigne", "--attend", "reponse",
            resume="rends-moi la liste")
    capsys.readouterr()
    assert cime(monkeypatch, "coord-x", "reprise", projet=projet) == 0
    texte = capsys.readouterr().out
    assert "FACTEUR ARRÊTÉ depuis toujours" in texte.splitlines()[0]
    assert "Reprise de coord-x" in texte
    assert "#1 reponse à worker-x-t" in texte and "quelle API ?" in texte   # (a)
    assert "#2 demande_accord → assistant" in texte and "accord attendu de assistant" in texte                          # (b)
    assert "#1 de worker-x-t (question" in texte and "#4 de assistant (consigne" in texte  # (c)
    assert "x : travail" in texte and "y : rien en cours" in texte             # (d)
    assert "(e)" not in texte                                                  # pas l'Assistant
    assert "décision 9" in texte and "décision 5" in texte and "décision 4" not in texte
    assert cime(monkeypatch, "assistant", "reprise") == 0
    texte = capsys.readouterr().out
    assert "(e) Attentes de l'utilisateur ouvertes (1)" in texte and "ouvrir la phase 2 ?" in texte


def test_facteur_qui_bat_pas_d_avertissement(projet, monkeypatch, capsys):
    conn = ouvrir(projet)
    conn.execute("INSERT INTO facteur (id, battement) VALUES (1, ?)", (horodatage(),))
    conn.commit()
    cime(monkeypatch, "coord-x", "reprise", projet=projet)
    assert "FACTEUR" not in capsys.readouterr().out
    conn.execute("UPDATE facteur SET battement = '2020-01-01T00:00:00.000Z'")
    conn.commit()
    cime(monkeypatch, "coord-x", "reprise")
    assert capsys.readouterr().out.startswith("FACTEUR ARRÊTÉ depuis ")


def test_plafond_de_4000_caracteres_et_complet(projet, monkeypatch, capsys):
    conn = ouvrir(projet)
    with conn:
        for i in range(200):
            conn.execute("INSERT INTO messages (horodatage,de,a,nature,resume)"
                         " VALUES (?, 'assistant', 'coord-x', 'consigne', ?)",
                         (horodatage(), f"message numéro {i} " + "x" * 120))
    conn.close()
    cime(monkeypatch, "coord-x", "reprise", projet=projet)
    court = capsys.readouterr().out
    assert len(court.rstrip("\n")) <= reprise.PLAFOND
    assert "--complet" in court
    cime(monkeypatch, "coord-x", "reprise", "--complet")
    assert len(capsys.readouterr().out) > reprise.PLAFOND


def test_message_clos_absent_du_courrier(projet, monkeypatch, capsys):
    envoyer(monkeypatch, "assistant", "coord-x", "consigne", "--attend", "rien", resume="vu")
    capsys.readouterr()
    conn = ouvrir(projet)
    conn.execute("INSERT INTO transitions (horodatage,message_id,etat,auteur,preuve)"
                 " VALUES (?,1,'clos','cime','{}')", (horodatage(),))
    conn.commit()
    cime(monkeypatch, "coord-x", "reprise", projet=projet)
    assert "(c) Courrier à mon adresse non clos (0)" in capsys.readouterr().out


def test_agent_sans_identite(projet, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDECODE", "1")
    assert cime(monkeypatch, None, "reprise", projet=projet) == 2
