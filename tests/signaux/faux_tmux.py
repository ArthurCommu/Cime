"""Un faux tmux à écran simulé, pour les tests du facteur : aucune commande réelle ne part."""
import subprocess
import time

REGLE = "─" * 40


class FauxTmux:
    def __init__(self, sessions=(), silence=100.0):
        # nom de session -> {"invite": texte tapé, "activite": époque de la dernière activité,
        #                    "ecran": écran forcé, facultatif}
        self.sessions = {nom: {"invite": "", "activite": time.time() - silence}
                         for nom in sessions}
        self.appels = []
        self.entrees = []                # (session, texte envoyé avec Enter)
        self.captures = 0
        self.apres_capture = []          # fonctions(self, n) appelées après chaque capture
        self.apres_frappe = []           # fonctions(self, session, texte) après un `-l`
        self.echec_send_keys = False
        self.kills = []                  # sessions fermées par `kill-session`
        self.avant_kill = []             # fonctions(session) appelées juste avant une fermeture

    def __call__(self, *args):
        self.appels.append(args)
        commande = args[0]
        if commande == "list-sessions":
            return self._ok("\n".join(self.sessions) + "\n")
        if commande == "kill-session":
            nom = args[args.index("-t") + 1].lstrip("=")
            for f in list(self.avant_kill):
                f(nom)
            self.kills.append(nom)
            self.sessions.pop(nom, None)
            return self._ok("")
        session = self._session(args)
        if commande == "display-message":
            if "#{pane_width} #{pane_height}" in args:      # largeur et hauteur du pane : 78 colonnes, 45 lignes
                return self._ok("78 45\n")
            return self._ok(f"{self.sessions[session]['activite']}\n")
        if commande == "capture-pane":
            etat = self.sessions[session]
            # `ecran` forcé : `capture-pane` le rend tel quel (une fenêtre, un écran étranger)
            sortie = etat["ecran"] if "ecran" in etat else f"{REGLE}\n❯\xa0{etat['invite']}\n{REGLE}\n"
            self.captures += 1
            resultat = self._ok(sortie)
            for f in list(self.apres_capture):
                f(self, self.captures)
            return resultat
        if commande == "send-keys":
            if self.echec_send_keys:
                return subprocess.CompletedProcess(args, 1, "", "no server")
            etat = self.sessions[session]
            if "-l" in args:
                texte = args[args.index("-l") + 1]
                etat["invite"] += texte
                for f in list(self.apres_frappe):
                    f(self, session, texte)
            elif "Enter" in args:
                self.entrees.append((session, etat["invite"]))
                etat["invite"] = ""
            elif "BSpace" in args:
                n = args.count("BSpace")
                etat["invite"] = etat["invite"][:max(0, len(etat["invite"]) - n)]
            return self._ok("")
        return self._ok("")

    def _session(self, args):
        if "-t" not in args:
            return None
        cible = args[args.index("-t") + 1].lstrip("=").rstrip(":")
        return cible if cible in self.sessions else None

    @staticmethod
    def _ok(sortie):
        return subprocess.CompletedProcess([], 0, sortie, "")

    def frapper(self, session, texte):
        """L'utilisateur tape au clavier."""
        self.sessions[session]["invite"] += texte
        self.sessions[session]["activite"] = time.time()

    def forcer_ecran(self, session, ecran):
        """La session montre `ecran` à toute capture, quoi qu'on tape (None : retour à l'invite simulée)."""
        if ecran is None:
            self.sessions[session].pop("ecran", None)
        else:
            self.sessions[session]["ecran"] = ecran
