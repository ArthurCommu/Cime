"""Aucune échéance ne court pendant le sommeil d'un coordinateur : le repos qui précède son sommeil ne
compte pas pour la dette au repos. Les échéances propres d'un message, elles, courent depuis son
inscription, endormi ou non."""
from aide import lignes
from aide_repos import (
    ASSISTANT, COORD, CONVERSATION, dans, evt_a, evt_sans_agent_a, poster, projet,  # noqa: F401
)
from cime.signaux import relances


def minutes(n):
    return dans(n)


def sommeil_depuis_une_heure(projet):
    """Un coordinateur au repos depuis 60 min, endormi depuis 40 min."""
    evt_a(projet, COORD, "SessionStart", minutes(-61), source="startup")
    evt_a(projet, COORD, "Stop", minutes(-60))
    evt_sans_agent_a(projet, "CoordEndormi", minutes(-40),
                     {"agent": COORD, "session": CONVERSATION, "repos_minutes": 20})


def reveil(projet, quand):
    evt_sans_agent_a(projet, "CoordReveille", minutes(quand),
                     {"agent": COORD, "session": CONVERSATION, "par_ordre": 1})
    evt_a(projet, COORD, "SessionStart", minutes(quand), session_id="conv-x-2", source="resume")


def dettes(projet):
    return [o for (o,) in lignes(projet, "SELECT objet FROM messages WHERE objet LIKE 'dette:%'"
                                         " ORDER BY id")]


def donner_une_dette(projet):
    return poster(projet, ASSISTANT, COORD, nature="question", attend="reponse",
                  resume="où en es-tu")


def test_sans_sommeil_un_coordinateur_au_repos_avec_une_dette_est_relance_comme_avant(projet):
    evt_a(projet, COORD, "SessionStart", minutes(-61), source="startup")
    evt_a(projet, COORD, "Stop", minutes(-60))
    donner_une_dette(projet)
    relances.executer(projet, minutes(10))
    assert len(dettes(projet)) == 1 and dettes(projet)[0].endswith(":0")


def test_pendant_son_sommeil_un_coordinateur_ne_doit_rien_a_personne_au_repos(projet):
    sommeil_depuis_une_heure(projet)
    donner_une_dette(projet)
    for decalage in (1, 10, 40, 600):
        relances.executer(projet, minutes(decalage))
    assert dettes(projet) == []


def test_juste_apres_son_reveil_le_repos_d_avant_ne_compte_pas(projet):
    sommeil_depuis_une_heure(projet)
    donner_une_dette(projet)
    reveil(projet, 1)
    relances.executer(projet, minutes(1.5))
    relances.executer(projet, minutes(5))
    assert dettes(projet) == []


def test_reveille_et_toujours_au_repos_avec_sa_dette_il_est_relance_cinq_minutes_apres_son_reveil(projet):
    sommeil_depuis_une_heure(projet)
    donner_une_dette(projet)
    reveil(projet, 1)
    relances.executer(projet, minutes(7))
    assert len(dettes(projet)) == 1 and dettes(projet)[0].endswith(":0")
    relances.executer(projet, minutes(17))                       # 16 min après le réveil : le signalement
    assert [d[-1] for d in dettes(projet)] == ["0", "1"]


def test_le_sommeil_d_un_coordinateur_ne_change_pas_la_dette_d_un_autre(projet):
    sommeil_depuis_une_heure(projet)
    reveil(projet, 9)                                            # coord-x vient de se réveiller
    evt_a(projet, "coord-y", "SessionStart", minutes(-61), source="startup")
    evt_a(projet, "coord-y", "Stop", minutes(-60))
    poster(projet, ASSISTANT, "coord-y", nature="question", attend="reponse", resume="et toi")
    relances.executer(projet, minutes(10))
    assert [d.split(":")[1] for d in dettes(projet)] == ["coord-y"]


def test_les_echeances_propres_d_un_message_courent_depuis_son_inscription(projet):
    sommeil_depuis_une_heure(projet)
    question = donner_une_dette(projet)
    reveil(projet, 1)
    relances.executer(projet, minutes(10))                       # avant les 15 minutes de la question
    assert lignes(projet, "SELECT 1 FROM messages WHERE nature = 'relance' AND en_reponse_a = ?"
                          " AND objet NOT LIKE 'dette:%'", (question,)) == []
    relances.executer(projet, minutes(16))
    assert len(lignes(projet, "SELECT 1 FROM messages WHERE nature = 'relance' AND en_reponse_a = ?"
                              " AND objet NOT LIKE 'dette:%'", (question,))) == 1
