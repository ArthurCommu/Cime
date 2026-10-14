"""Le bloc `charge` de l'instantané : le plafond de workers actifs en vigueur, d'où il vient, et les
workers actifs, lus comme `cime plafond` les lit. Lecture seule."""

from pathlib import Path


def lire_charge(racine) -> tuple[dict | None, dict]:
    """(bloc `charge`, source). Le bloc vaut None quand la lecture lève : l'appelant en fait un
    échec de source, sans toucher aux autres blocs."""
    from cime.fondation import plafond
    from cime.fondation.projet import ErreurProjet
    from cime.signaux import livraison, ordres

    racine = Path(racine)
    sessions = livraison.sonde_sessions()
    machine, source_machine = ordres.plafond_machine(racine, sessions)
    try:
        limite = plafond.plafond_projet(racine)
    except ErreurProjet:
        limite = None
    valeur, origine = plafond.en_vigueur(machine, limite)
    changement = plafond.dernier_changement(machine) if source_machine == plafond.FICHIER_SOURCE else None
    depuis, par = changement if changement is not None else (None, None)
    actifs, par_projet = ordres.workers_vus(racine, sessions)
    bloc = {
        "workers_max": valeur, "source": origine,
        "machine": {"valeur": machine, "source": source_machine, "depuis": depuis, "par": par},
        "projet": limite, "workers_actifs": actifs, "par_projet": par_projet}
    return bloc, {"nom": "charge", "ok": True}
