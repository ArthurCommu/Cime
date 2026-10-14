"""Un courrier de l'utilisateur à l'Assistant est tapé par le facteur (« Utilisateur : … ») et accusé
par le `UserPromptSubmit` qui porte ce texte. Le préfixe reconnu doit suivre le format livré."""
from e2e.aides import ASSISTANT, accuser, envoyer, etat

from cime.fondation.registre import ouvrir
from cime.signaux import hooks

UTILISATEUR = "utilisateur"


def test_courrier_de_l_utilisateur_tape_puis_accuse_par_son_prompt(banc):
    banc.au_repos(ASSISTANT)
    i = envoyer(banc, UTILISATEUR, ASSISTANT, "consigne", "oui, on fusionne")
    banc.facteur_tour()
    attendu = f"Utilisateur : oui, on fusionne (#{i})"
    assert banc.tmux.entrees == [("es-assistant", attendu)]          # entier, une seule frappe
    assert accuser(banc, ASSISTANT, attendu).code == 0
    assert banc.prouve("SELECT json_extract(preuve, '$.evenement') FROM transitions"
                       " WHERE message_id = ? AND etat = 'pris_en_compte'", (i,)) == [
        ("UserPromptSubmit",)]
    assert etat(banc, i) == "clos"
    # le texte accusé est exactement le texte livré
    assert banc.prouve("SELECT json_extract(details, '$.prompt') FROM evenements"
                       " WHERE evenement = 'UserPromptSubmit' AND agent = ?", (ASSISTANT,)) == [(attendu,)]


def test_lot_utilisateur_et_cime_accuse_par_un_seul_prompt(banc):
    banc.au_repos(ASSISTANT)
    a = envoyer(banc, UTILISATEUR, ASSISTANT, "consigne", "oui")
    conn = ouvrir(banc.projet)
    try:
        b = hooks.signaler(conn, banc.projet, a=ASSISTANT, objet="bilan:test", resume="bilan")
    finally:
        conn.close()
    banc.facteur_tour()
    attendu = f"Utilisateur : oui (#{a}) ‖ Cime : bilan (#{b})"
    assert banc.tmux.entrees == [("es-assistant", attendu)]
    assert accuser(banc, ASSISTANT, attendu).code == 0
    assert etat(banc, a) == etat(banc, b) == "clos"
