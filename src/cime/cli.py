"""Point d'entrée de la commande `cime` : déclare les sous-commandes et les délègue à leur module."""

import argparse
import importlib
import json
import sys
import threading
import time
from pathlib import Path

from cime.fondation.nom import NOM


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=NOM)
    sub = p.add_subparsers(dest="commande", required=True)

    s = sub.add_parser("init", help="initialiser un projet")
    s.add_argument("dossier")
    s.add_argument("--utilisateur", help="requis, sauf avec --apercu")
    s.add_argument("--apercu", action="store_true",
                   help="montrer ce que `init` ferait, sans rien écrire (ni dossier, ni git init)")
    s.add_argument("--json", dest="sortie_json", action="store_true",
                   help="avec --apercu : sortie JSON")
    s.add_argument("--nom-projet")
    s.add_argument("--prefixe")
    s.add_argument("--lancer", action="store_true",
                   help="puis lancer l'Assistant du projet (comme `lancer assistant`)")
    s.add_argument("--modele", help="avec --lancer : modèle de l'Assistant")
    s.add_argument("--migrer", action="store_true",
                   help="puis retirer de .claude/settings.json les interdits réservés aux agents "
                        "d'équipe, posés par un `init` plus ancien (les règles ajoutées à la main "
                        "restent)")
    s.add_argument("--hooks-sans-cime", action="store_true",
                   help="écrire les hooks même si la commande n'est pas sur le PATH "
                        "(ils sortiront en 127 et Claude Code laissera passer les commandes)")

    s = sub.add_parser("envoyer", help="inscrire un message au registre")
    s.add_argument("--a", required=True)
    s.add_argument("--nature", required=True)
    s.add_argument("--attend", help="consigne : rien | accuse | travail_pret | reponse")
    s.add_argument("--objet", help="clé machine du message (lancer-worker:<é>:<t>, …)")
    s.add_argument("--fichier")
    s.add_argument("--corps", help="corps du message, ou - pour le lire sur stdin (≤ 4000 car.)")
    s.add_argument("--en-reponse-a", type=int, help=argparse.SUPPRESS)
    s.add_argument("--equipe", help="équipe concernée (défaut : celle de l'appelant)")
    s.add_argument("--suite", action="append", metavar="SPEC",
                   help="travail_pret : suite à exécuter après la fusion (répétable) : "
                        "recopier:<source>:<cible> | migrer")
    s.add_argument("resume")

    s = sub.add_parser("repondre", help="répondre à un message qui m'est adressé")
    s.add_argument("id", type=int)
    s.add_argument("--nature", help="reponse (défaut) | compte_rendu | travail_pret | question | "
                                "rapport_utilisateur (en réponse à une demande_cloture)")
    s.add_argument("--fichier")
    s.add_argument("--suite", action="append", metavar="SPEC",
                   help="travail_pret : suite à exécuter après la fusion (répétable) : "
                        "recopier:<source>:<cible> | migrer")
    s.add_argument("resume")

    s = sub.add_parser("accorder", help="accorder une demande d'accord")
    s.add_argument("id", type=int)
    s.add_argument("--modele", help="lancer-worker : modèle accordé (obligatoire)")
    s.add_argument("--parallele", action="store_true",
                   help="lancer-worker : autorise un second worker actif de l'équipe")

    s = sub.add_parser("refuser", help="refuser une demande d'accord")
    s.add_argument("id", type=int)
    s.add_argument("motif")

    s = sub.add_parser("suites", help="exécuter les suites d'une fusion (Assistant)")
    s.add_argument("equipe")

    s = sub.add_parser("reprise", help="imprimer ce qu'il faut savoir pour reprendre le travail")
    s.add_argument("--complet", action="store_true", help="sans le plafond de 4 000 caractères")

    s = sub.add_parser("voir", help="voir l'écran d'un subordonné")
    s.add_argument("agent")

    s = sub.add_parser("journal", help="lire ce qui s'est passé pour un agent sur une fenêtre (lecture seule)")
    s.add_argument("agent")
    s.add_argument("--depuis", help="début, ISO 8601 (défaut : les 2 dernières heures)")
    s.add_argument("--jusqu-a", help="fin, ISO 8601 (défaut : maintenant)")

    s = sub.add_parser("facteur", help="le facteur : ordres, livraison, échéances (processus du projet)")
    s.add_argument("--une-fois", action="store_true", help="un seul tour, pour les essais")

    s = sub.add_parser("terminer", help="terminer un worker (rapport requis)")
    s.add_argument("role", choices=["worker"])
    s.add_argument("equipe")
    s.add_argument("tache")
    s.add_argument("--verifie", metavar="SHA", help="Assistant : tâche finie avant le registre, SHA est dans main")
    s.add_argument("--motif", help="avec --verifie : pourquoi (journalisé)")

    s = sub.add_parser("compacter", help="faire compacter la conversation d'un agent")
    s.add_argument("identite")
    s.add_argument("consignes")

    s = sub.add_parser("hook", help="traiter un événement de hook")
    s.add_argument("evenement")

    s = sub.add_parser("lancer", help="lancer un agent")
    s.add_argument("role", choices=["assistant", "coord", "worker"])
    s.add_argument("equipe", nargs="?")
    s.add_argument("tache", nargs="?")
    s.add_argument("--modele")
    s.add_argument("--phase", help="coord : phase du chantier accordée par l'utilisateur "
                                   "(sans --reprendre)")
    s.add_argument("--reprendre", action="store_true",
                   help="coord : reprendre la dernière conversation du coordinateur")
    s.add_argument("--session", help="avec --reprendre : identifiant de la conversation")
    s.add_argument("--remplacer", action="store_true",
                   help="Assistant, coord --reprendre : fermer d'abord la session existante "
                        "(ordre exécuté par le facteur), puis reprendre")
    s.add_argument("--detache", action="store_true",
                   help="ne pas attacher le terminal (assistant, écran d'approbation)")
    s.add_argument("--essai-a-blanc", action="store_true",
                   help="affiche la commande sans lancer")

    s = sub.add_parser(
        "equipe",
        help="créer une équipe (dossier, branche, worktree)",
        description="Crée le dossier, la branche et le worktree d'une équipe, sans lancer "
                    "son coordinateur. La création d'une équipe est une décision de "
                    "l'utilisateur.")
    s.add_argument("nom")
    s.add_argument("--essai-a-blanc", action="store_true",
                   help="affiche ce qui serait fait, sans rien toucher")

    s = sub.add_parser("servir", help="servir la page d'un projet")
    s.add_argument("chemin", nargs="?",
                   help="dossier du projet (l'emporte sur $CIME_PROJET et le dossier courant)")
    s.add_argument("--port", type=int)

    s = sub.add_parser(
        "lanceur", help="lancer le lanceur (liste des projets, un par machine)",
        description="Lance la page de tous les projets. Les pages de projet qu'il ouvre "
                    "lui survivent : Ctrl-C sur le lanceur n'arrête pas celles déjà "
                    "ouvertes (voulu : un navigateur par projet). Pour en arrêter une : "
                    "`kill $(lsof -ti tcp:<port>)`, où <port> est dans "
                    "<projet>/.orga/etat/hote.port (le fichier disparaît à l'arrêt).")
    s.add_argument("--port", type=int)
    s.add_argument("--modele", help="modèle de l'Assistant des projets créés")
    s.add_argument("--plist", action="store_true",
                   help="imprimer le .plist de l'agent launchd de la machine (ne l'installe pas)")

    s = sub.add_parser(
        "ouvrir",
        help="ouvrir le lanceur dans le navigateur, et le démarrer au besoin (utilisateur seulement)")
    s.add_argument("--url", action="store_true", help="imprimer l'URL sans ouvrir le navigateur")
    s.add_argument("--json", dest="sortie_json", action="store_true")

    s = sub.add_parser(
        "fusions-auto",
        help="l'option « Fusions automatiques » : lire son état, ou (utilisateur) l'activer/désactiver")
    s.add_argument("valeur", nargs="?", choices=["active", "inactive"],
                   help="sans argument : état et liste des chemins réservés ; avec : réservé à l'utilisateur")

    s = sub.add_parser(
        "fermer",
        help="fermer un projet : noter ses conversations, fermer ses sessions et son hôte "
             "(utilisateur seulement)")
    s.add_argument("projet", help="dossier du projet (ni $CIME_PROJET ni le dossier courant)")
    s.add_argument("--forcer", action="store_true",
                   help="fermer même si des agents travaillent encore")
    s.add_argument("--json", dest="sortie_json", action="store_true")

    s = sub.add_parser(
        "rouvrir",
        help="rouvrir un projet : reprendre l'Assistant et les coordinateurs qui avaient du travail "
             "(utilisateur seulement)")
    s.add_argument("projet", help="dossier du projet (ni $CIME_PROJET ni le dossier courant)")
    s.add_argument("--session", help="conversation de l'Assistant à reprendre")
    s.add_argument("--seulement-assistant", action="store_true",
                   help="ne relancer que l'Assistant")
    s.add_argument("--json", dest="sortie_json", action="store_true")

    s = sub.add_parser(
        "conversations",
        help="lister les conversations de l'Assistant d'un projet, avec leur début "
             "(utilisateur seulement, lecture seule)")
    s.add_argument("projet", help="dossier du projet")
    s.add_argument("--json", dest="sortie_json", action="store_true")

    sub.add_parser("etat", help="imprimer l'état instantané")
    return p


_COMMANDES_SIGNAUX = {
    "repondre": ("cime.signaux.commandes", "repondre"),
    "accorder": ("cime.signaux.commandes", "accorder"),
    "refuser": ("cime.signaux.commandes", "refuser"),
    "reprise": ("cime.signaux.reprise", "executer"),
    "voir": ("cime.signaux.ordres", "voir"),
    "journal": ("cime.signaux.journal", "journal"),
    "suites": ("cime.signaux.suites", "suites"),
    "facteur": ("cime.signaux.facteur", "executer"),
    # le tiret n'est pas un nom de module : `cime.fondation.<commande>` ne se résout pas
    "fusions-auto": ("cime.fondation.fusions_auto", "executer"),
    # deux points d'entrée dans un même module ; ni l'un ni l'autre ne lit $CIME_PROJET
    "fermer": ("cime.fondation.fermeture", "executer_fermer"),
    "rouvrir": ("cime.fondation.fermeture", "executer_rouvrir"),
    "ouvrir": ("cime.lanceur.ouvrir", "executer"),
}


def _module_appele(args) -> int:
    if args.commande in _COMMANDES_SIGNAUX:
        module, fonction = _COMMANDES_SIGNAUX[args.commande]
        return getattr(importlib.import_module(module), fonction)(args)
    nom_module = f"cime.fondation.{args.commande}"
    try:
        module = importlib.import_module(nom_module)
    except ModuleNotFoundError as e:
        if e.name != nom_module:
            raise
        print(f"{args.commande} : pas encore livrée dans cette version",
              file=sys.stderr)
        return 2
    return module.executer(args)


def _importer_optionnel(module: str, nom: str, commande: str, libelle: str):
    try:
        return getattr(importlib.import_module(module), nom)
    except ModuleNotFoundError as e:
        if e.name != module:
            raise
        print(f"{commande} : le module {libelle} ({module}) "
              "n'est pas présent dans cette installation", file=sys.stderr)
        return None


ATTENTE_URL_S = 10.0


def _annoncer_url(fichier: Path, debut: float, attente_s: float = ATTENTE_URL_S,
                  pas_s: float = 0.05) -> None:
    """Imprime l'URL dès que l'hôte écrit un hote.port plus récent que `debut`."""
    fin = time.monotonic() + attente_s
    while time.monotonic() < fin:
        try:
            if fichier.stat().st_mtime >= debut:
                port = int(fichier.read_text().strip())
                print(f"http://127.0.0.1:{port}/", flush=True)
                return
        except (OSError, ValueError):
            pass  # absent, ancien ou à moitié écrit : on réessaie
        time.sleep(pas_s)
    print(f"servir : port de l'hôte non annoncé après {attente_s:g} s "
          f"({fichier} introuvable ou ancien) ; le serveur continue", file=sys.stderr, flush=True)


def _servir(args) -> int:
    from cime.fondation.projet import trouver_projet
    if args.chemin:
        projet = Path(args.chemin).expanduser().resolve()
        if not (projet / ".orga" / "projet.toml").is_file():
            print(f"servir : {projet} n'est pas un projet "
                  "(.orga/projet.toml introuvable)", file=sys.stderr)
            return 2
    else:
        projet = trouver_projet()
    servir = _importer_optionnel("cime.hote", "servir", "servir", "hôte")
    if servir is None:
        return 1
    threading.Thread(
        target=_annoncer_url,
        args=(projet / ".orga" / "etat" / "hote.port", time.time()),
        daemon=True).start()
    servir(projet, args.port or 0)
    return 0


def _lanceur(args) -> int:
    if getattr(args, "plist", False):
        from cime.lanceur import garder_port, launchd, port_voulu
        port = args.port if args.port is not None else port_voulu()
        if not 1 <= port <= 65535:
            print("lanceur --plist : --port doit être entre 1 et 65535", file=sys.stderr)
            return 2
        garder_port(port)                       # le réglage suit le plist : `cime ouvrir` le lit
        print(launchd.plist(port=port))
        print(launchd.INSTALLATION, file=sys.stderr, end="")
        return 0
    servir = _importer_optionnel("cime.lanceur", "servir", "lanceur", "lanceur")
    if servir is None:
        return 1
    from cime.lanceur import port_voulu
    port = args.port if args.port is not None else port_voulu()
    servir(port, modele=args.modele)
    return 0


def _etat(args) -> int:
    from cime.fondation.projet import trouver_projet
    projet = trouver_projet()
    instantane = _importer_optionnel("cime.observation", "instantane", "etat", "d'observation")
    if instantane is None:
        return 1
    print(json.dumps(instantane(projet), ensure_ascii=False, indent=2))
    return 0


def _executer(args) -> int:
    if args.commande == "servir":
        return _servir(args)
    if args.commande == "lanceur":
        return _lanceur(args)
    if args.commande == "etat":
        return _etat(args)
    return _module_appele(args)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and argv[0] == "hook":
        try:
            args = _parser().parse_args(argv)
            try:
                from cime.fondation import hook
            except ModuleNotFoundError:
                _executer(args)  # explique que la commande manque ; jamais d'échec côté agent
                return 0
            return int(hook.executer(args) or 0)  # 0, ou 2 : texte rendu sur stderr
        except BaseException:
            return 0
    from cime.fondation.projet import ErreurProjet
    args = _parser().parse_args(argv)
    try:
        return _executer(args)
    except ErreurProjet as e:
        print(f"{NOM} : {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
