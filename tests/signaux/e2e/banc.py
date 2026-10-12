"""Le banc de preuve de bout en bout : les pièces simulées et les acteurs.

On ne simule que ce qui est hors du code de Cime : l'horloge, le terminal (`FauxTmuxE2E`) et le
modèle (`Acteur` : un script qui appelle les VRAIES commandes et les VRAIS hooks). Tout le reste
(facteur, livraison, relances, garde, SQLite, git) est le code de production.
"""
import argparse
import contextlib
import importlib
import io
import re
import json
import os
import pkgutil
import sqlite3
import subprocess
import sys
import threading
import time as temps_reel
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from faux_tmux import FauxTmux, REGLE

from cime.fondation.nom import VAR_AGENT, VAR_PROJET

DATETIME_REEL = datetime
TIME_REEL = temps_reel


# --- l'horloge simulée ------------------------------------------------------------------------------

class Horloge:
    """Une seule horloge pour tout le banc : `avance(minutes=5)` ; chaque `sleep` l'avance aussi.
    `pendant_sommeil` : fonctions(horloge) appelées à chaque sommeil (un message qui arrive
    pendant l'attente d'un hook `Stop`, par exemple)."""

    def __init__(self, debut: datetime | None = None):
        debut = debut or DATETIME_REEL.now(timezone.utc)
        self._t = debut.replace(microsecond=(debut.microsecond // 1000) * 1000)
        self._debut = self._t
        self._verrou = threading.RLock()
        self.pendant_sommeil: list = []
        self.sommeils: list[float] = []

    def now(self, tz=None) -> datetime:
        with self._verrou:
            return self._t.astimezone(tz) if tz is not None else self._t.replace(tzinfo=None)

    def maintenant(self) -> datetime:
        with self._verrou:
            return self._t

    def avance(self, **delai) -> None:
        with self._verrou:
            self._t += timedelta(**delai)

    def sleep(self, secondes: float) -> None:
        self.sommeils.append(secondes)
        self.avance(seconds=max(0.0, secondes))
        for f in list(self.pendant_sommeil):
            f(self)

    def monotonic(self) -> float:
        return 1000.0 + (self._t - self._debut).total_seconds()

    def time(self) -> float:
        return self._t.timestamp()

    def iso(self, decalage_s: float = 0.0) -> str:
        t = self._t + timedelta(seconds=decalage_s)
        return t.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _faux_datetime(horloge: Horloge):
    class DatetimeSimule(DATETIME_REEL):
        @classmethod
        def now(cls, tz=None):
            return horloge.now(tz)

        @classmethod
        def utcnow(cls):
            return horloge.now()

    return DatetimeSimule


class _FauxTime:
    """Le module `time` vu par Cime : horloge et sommeil simulés, le reste est le vrai `time`."""

    def __init__(self, horloge: Horloge):
        self._h = horloge

    def sleep(self, s):
        self._h.sleep(s)

    def monotonic(self):
        return self._h.monotonic()

    def time(self):
        return self._h.time()

    def __getattr__(self, nom):
        return getattr(TIME_REEL, nom)


def importer_tout_cime() -> None:
    """Importe tous les modules de Cime, pour que le branchement de l'horloge les atteigne tous."""
    import cime
    for info in pkgutil.walk_packages(cime.__path__, "cime."):
        try:
            importlib.import_module(info.name)
        except Exception:  # dépendance optionnelle absente : ce module n'est pas dans le banc
            continue


def brancher_horloge(horloge: Horloge, monkeypatch) -> list[str]:
    """Remplace `datetime` et `time` dans TOUS les modules de Cime qui les ont importés."""
    importer_tout_cime()
    faux_dt, faux_time, touches = _faux_datetime(horloge), _FauxTime(horloge), []
    for nom, mod in list(sys.modules.items()):
        if not nom.startswith("cime") or mod is None:
            continue
        if getattr(mod, "datetime", None) is DATETIME_REEL:
            monkeypatch.setattr(mod, "datetime", faux_dt)
            touches.append(f"{nom}.datetime")
        if getattr(mod, "time", None) is TIME_REEL:
            monkeypatch.setattr(mod, "time", faux_time)
            touches.append(f"{nom}.time")
    return touches


# --- le faux tmux -----------------------------------------------------------------------------------

class FauxTmuxE2E(FauxTmux):
    """Un écran simulé par agent. États : `repos` (invite vide), `brouillon("texte")`,
    `suggestion("texte atténué")`, `tour`, `absente`. Journal de TOUTES les commandes, avec leur
    origine (`facteur` pendant `Banc.facteur_tour`, sinon `hors-facteur`)."""

    def __init__(self, horloge: Horloge, nommer):
        super().__init__()
        self.horloge, self.nommer = horloge, nommer
        self.journal: list[dict] = []
        self.origine = "hors-facteur"
        self._frappes_a_injecter: list = []   # (caractère, entrelacé)
        self._enters_avales = 0               # nombre d'Enter que la TUI ne prendra pas
        self._apres_enter: list = []          # texte qui apparaît à l'invite juste après un Enter pris
        self._replis: list = []            # (marqueur, nombre de caractères gardés)

    # -- pilotage ------------------------------------------------------------------------------
    def _etat(self, agent) -> dict:
        nom = self.nommer(agent)
        return self.sessions.setdefault(nom, {
            "invite": "", "suggestion": "", "tour": False, "activite": self.horloge.time() - 100.0})

    def repos(self, agent):
        e = self._etat(agent)
        e.update(invite="", suggestion="", tour=False, brut=None)

    def brouillon(self, agent, texte):
        e = self._etat(agent)
        e.update(invite=texte, tour=False, activite=self.horloge.time())

    def suggestion(self, agent, texte):
        e = self._etat(agent)
        e.update(invite="", suggestion=texte, tour=False)

    def tour(self, agent):
        e = self._etat(agent)
        e["tour"] = True

    def ecran_brut(self, agent, capture):
        """L'écran est cette capture (`capture-pane -p -e` réelle), au repos."""
        e = self._etat(agent)
        e.update(invite="", suggestion="", tour=False, brut=capture)

    def absente(self, agent):
        self.sessions.pop(self.nommer(agent), None)

    def activite(self, agent, epoque=None):
        self._etat(agent)["activite"] = self.horloge.time() if epoque is None else epoque

    def invite_de(self, agent) -> str:
        return self.sessions[self.nommer(agent)]["invite"]

    def injecter_apres(self, n_capture: int, caractere: str, agent=None):
        """Course à la frappe : un caractère s'ajoute à l'invite après la `n`-ième capture."""
        def f(faux, n):
            if n == n_capture:
                cible = faux.nommer(agent) if agent else next(iter(faux.sessions))
                faux.sessions[cible]["invite"] += caractere
        self.apres_capture.append(f)

    def injecter_apres_frappe(self, caractere: str):
        """Un caractère s'ajoute juste après la prochaine frappe (`send-keys -l`)."""
        self._frappes_a_injecter.append((caractere, False))

    def entrelacer(self, caractere: str):
        """Un caractère s'insère AU MILIEU du prochain texte frappé."""
        self._frappes_a_injecter.append((caractere, True))

    def avaler_enters(self, n):
        """La TUI n'accepte pas les `n` prochains `Enter` (occupée, boîte de dialogue…) : l'invite reste."""
        self._enters_avales = n

    def saisie_apres_enter(self, texte):
        """Juste après le prochain `Enter` pris, l'invite porte ce texte (l'utilisateur tape, suggestion…)."""
        self._apres_enter.append(texte)

    def replier(self, marqueur="[Pasted text #1]", garde=0):
        """La prochaine frappe (`send-keys -l`) est repliée par la TUI : l'invite ne montre que le
        marqueur, suivi des `garde` derniers caractères du texte (ce que montre l'écran réel) ;
        `Enter` soumet le texte entier."""
        self._replis.append((marqueur, garde))

    def commandes(self, origine=None) -> list[tuple]:
        return [tuple(j["args"]) for j in self.journal if origine is None or j["origine"] == origine]

    def frapper(self, session, texte):
        self.sessions[session]["invite"] += texte
        self.sessions[session]["brut"] = None     # l'écran réel ne vaut que jusqu'à la première frappe
        self.sessions[session]["activite"] = self.horloge.time()

    # -- le protocole tmux -----------------------------------------------------------------------
    def _session(self, args):
        if "-t" not in args:
            return None
        cible = args[args.index("-t") + 1].lstrip("=").rstrip(":")
        return cible if cible in self.sessions else cible if cible else None

    def _ecran(self, session, avec_style: bool) -> str:
        e = self.sessions[session]
        if e.get("brut") is not None:
            return e["brut"] if avec_style else re.sub(r"\x1b\[[0-9;]*m", "", e["brut"])
        sug = e["suggestion"]
        if sug and avec_style:
            sug = f"\x1b[2m{sug}\x1b[0m"
        haut = ["✻ Réflexion… (12s · esc to interrupt)"] if e["tour"] else []
        return "\n".join([*haut, REGLE, f"❯\xa0{e['invite']}{sug}", REGLE]) + "\n"

    @staticmethod
    def _rc(code, sortie="", erreur=""):
        return subprocess.CompletedProcess([], code, sortie, erreur)

    def __call__(self, *args):
        self.appels.append(args)
        self.journal.append({"args": args, "origine": self.origine, "t": self.horloge.iso()})
        commande = args[0]
        if commande == "list-sessions":
            return self._rc(0, "\n".join(self.sessions) + ("\n" if self.sessions else ""))
        if commande == "new-session":
            nom = args[args.index("-s") + 1] if "-s" in args else None
            if nom in self.sessions:
                return self._rc(1, "", "duplicate session")
            self.sessions[nom] = {"invite": "", "suggestion": "", "tour": False,
                                  "activite": self.horloge.time() - 100.0}
            return self._rc(0)
        session = self._session(args)
        if session not in self.sessions:
            return self._rc(1, "", f"can't find session: {session}")
        etat = self.sessions[session]
        if commande == "has-session":
            return self._rc(0)
        if commande == "kill-session":
            del self.sessions[session]
            return self._rc(0)
        if commande == "display-message":
            return self._rc(0, f"{etat['activite']}\n")
        if commande == "capture-pane":
            sortie = self._ecran(session, "-e" in args)
            self.captures += 1
            for f in list(self.apres_capture):
                f(self, self.captures)
            return self._rc(0, sortie)
        if commande == "send-keys":
            if self.echec_send_keys:
                return self._rc(1, "", "no server")
            if "-l" in args:
                texte = args[args.index("-l") + 1]
                if self._frappes_a_injecter and self._frappes_a_injecter[0][1]:
                    car, _ = self._frappes_a_injecter.pop(0)
                    milieu = len(texte) // 2
                    texte = texte[:milieu] + car + texte[milieu:]
                if self._replis:    # la TUI replie le texte collé : marqueur (+ fin du texte, si `garde`)
                    marqueur, garde = self._replis.pop(0)
                    etat["plein"] = texte
                    texte = marqueur + (texte[max(0, len(texte) - garde):] if garde else "")
                etat["invite"] += texte
                etat["suggestion"] = ""
                etat["brut"] = None     # l'écran réel ne vaut que jusqu'à la première frappe
                etat["activite"] = self.horloge.time()
                while self._frappes_a_injecter and not self._frappes_a_injecter[0][1]:
                    etat["invite"] += self._frappes_a_injecter.pop(0)[0]
                for f in list(self.apres_frappe):
                    f(self, session, texte)
            elif "Enter" in args and self._enters_avales:
                self._enters_avales -= 1      # la TUI n'a pas pris l'Enter : l'invite est inchangée
            elif "Enter" in args:
                self.entrees.append((session, etat.pop("plein", None) or etat["invite"]))
                etat["invite"] = self._apres_enter.pop(0) if self._apres_enter else ""
            elif "BSpace" in args:
                etat["invite"] = etat["invite"][:max(0, len(etat["invite"]) - args.count("BSpace"))]
            return self._rc(0)
        return self._rc(0)


# --- les acteurs ------------------------------------------------------------------------------------

@dataclass
class Resultat:
    code: int | None
    sortie: str = ""
    erreur: str = ""
    id: int | None = None

    def __iter__(self):                     # code, sortie, id
        return iter((self.code, self.sortie, self.id))


@dataclass
class ResultatHook:
    code: int
    stderr: str
    stdout: str

    def __iter__(self):                     # code, stderr, stdout
        return iter((self.code, self.stderr, self.stdout))


_VERROU_PROCESSUS = threading.RLock()       # l'environnement et stdout sont ceux du processus


@contextlib.contextmanager
def _identite(projet, agent):
    avant = {k: os.environ.get(k) for k in (VAR_AGENT, VAR_PROJET, "CLAUDECODE")}
    os.environ[VAR_PROJET] = str(projet)
    os.environ.pop("CLAUDECODE", None)
    if agent is None:
        os.environ.pop(VAR_AGENT, None)
    else:
        os.environ[VAR_AGENT] = agent
    try:
        yield
    finally:
        for k, v in avant.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class Acteur:
    """Un agent (ou l'utilisateur, `agent=None`) : appelle les vraies commandes `cime` et les vrais hooks."""

    def __init__(self, banc, agent, **env):
        self.banc, self.agent, self.env = banc, agent, env

    def cime(self, *argv: str) -> Resultat:
        from cime import cli
        sortie, erreur = io.StringIO(), io.StringIO()
        with _VERROU_PROCESSUS, _identite(self.banc.projet, self.agent), \
                _env(self.env), contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(erreur):
            try:
                code = cli.main(list(argv))
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
        code = 0 if code is None else code
        dernier = sortie.getvalue().strip().splitlines()[-1:] or [""]
        ident = int(dernier[0]) if dernier[0].isdigit() else None
        return Resultat(code, sortie.getvalue(), erreur.getvalue(), ident)

    def hook(self, evenement: str, entree: dict | None = None) -> ResultatHook:
        from cime.fondation import hook
        sortie, erreur = io.StringIO(), io.StringIO()
        corps = json.dumps({"session_id": "s", **(entree or {})})
        ancien = sys.stdin
        with _VERROU_PROCESSUS, _identite(self.banc.projet, self.agent), _env(self.env), \
                contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(erreur):
            sys.stdin = io.StringIO(corps)
            try:
                code = hook.executer(argparse.Namespace(evenement=evenement))
            finally:
                sys.stdin = ancien
        return ResultatHook(code, erreur.getvalue(), sortie.getvalue())

    def inerte(self) -> "ActeurInerte":
        """Variante « oubli » : l'acteur ne fait pas sa part."""
        return ActeurInerte(self.agent)


class ActeurInerte:
    """Ne fait rien : ni commande, ni hook. `gestes` reste vide."""

    def __init__(self, agent):
        self.agent, self.gestes = agent, []

    def cime(self, *argv):
        return None

    def hook(self, evenement, entree=None):
        return None

    def inerte(self):
        return self


@contextlib.contextmanager
def _env(extra):
    avant = {k: os.environ.get(k) for k in extra}
    os.environ.update({k: str(v) for k, v in extra.items()})
    try:
        yield
    finally:
        for k, v in avant.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


# --- le banc ----------------------------------------------------------------------------------------

class Banc:
    """Un projet jetable + l'horloge + le faux tmux, avec de quoi agir (`acteur`), faire tourner
    le facteur (`facteur_tour`) et prouver (`prouve`)."""

    def __init__(self, projet: Path, horloge: Horloge, tmux: FauxTmuxE2E):
        self.projet, self.horloge, self.tmux = Path(projet), horloge, tmux
        from cime.signaux import livraison
        self.memoire = livraison.Memoire()

    def acteur(self, agent, **env) -> Acteur:
        return Acteur(self, agent, **env)

    def utilisateur(self) -> Acteur:
        return Acteur(self, "utilisateur")

    def en_parallele(self, acteur: Acteur, *commandes: tuple) -> list[int]:
        """Lance plusieurs `cime` d'un MÊME acteur en même temps (threads) ; rend les codes.
        (L'identité est une variable d'environnement du processus : un seul acteur à la fois.)"""
        codes = [None] * len(commandes)
        from cime import cli
        barriere = threading.Barrier(len(commandes))

        def tache(i, argv):
            barriere.wait()
            try:
                codes[i] = cli.main(list(argv))
            except SystemExit as e:
                codes[i] = e.code
        with _VERROU_PROCESSUS, _identite(self.projet, acteur.agent), _env(acteur.env):
            fils = [threading.Thread(target=tache, args=(i, c)) for i, c in enumerate(commandes)]
            [f.start() for f in fils]
            [f.join() for f in fils]
        return [0 if c is None else c for c in codes]

    def facteur_tour(self, maintenant=None, memoire=None) -> dict:
        """Un tour du VRAI facteur, à l'heure simulée ; les commandes tmux qu'il émet sont
        marquées `facteur` dans le journal du faux tmux."""
        from cime.signaux import facteur
        avant, self.tmux.origine = self.tmux.origine, "facteur"
        try:
            return facteur.tour(self.projet, maintenant or self.horloge.maintenant(),
                                memoire if memoire is not None else self.memoire)
        finally:
            self.tmux.origine = avant

    def nouveau_facteur(self) -> None:
        """Le facteur est « tué » puis relancé : il repart sans mémoire (tout est en base)."""
        from cime.signaux import livraison
        self.memoire = livraison.Memoire()

    # -- scènes d'agent : ce que Claude Code et le terminal font tout seuls ------------------------
    def au_repos(self, agent, par="Stop") -> None:
        """L'agent a fini son tour : `Stop` au registre (ou, `par="idle"`, un `idle_prompt` qui
        confirme le repos sans passer par le hook `Stop`), invite vide au terminal."""
        if par == "idle":
            self.acteur(agent).hook("Notification", {"notification_type": "idle_prompt"})
        else:
            self.acteur(agent).hook("Stop", {"stop_hook_active": False})
        self.tmux.repos(agent)

    def au_travail(self, agent) -> None:
        """L'agent est en plein tour : `UserPromptSubmit` au registre, tour affiché au terminal."""
        self.acteur(agent).hook("UserPromptSubmit", {"prompt": "continue"})
        self.tmux.tour(agent)

    def faire_tourner(self, secondes: float, pas: float = 30.0, jusqu_a=None) -> int:
        """Le facteur tourne toutes les `pas` secondes simulées pendant `secondes` (ou jusqu'à ce
        que `jusqu_a()` soit vrai) ; rend le nombre de tours faits."""
        tours, ecoule = 0, 0.0
        while ecoule < secondes:
            self.facteur_tour()
            tours += 1
            if jusqu_a is not None and jusqu_a():
                break
            self.horloge.avance(seconds=pas)
            ecoule += pas
        return tours

    def en_processus(self, *travaux: tuple) -> list:
        """Lance en même temps de VRAIS processus : travaux = (agent, argv, stdin ou None).
        Rend [(code, stdout, stderr)] ; le registre est partagé, l'horloge est celle du système."""
        env_base = {k: v for k, v in os.environ.items() if k not in (VAR_AGENT, "CLAUDECODE")}
        env_base[VAR_PROJET] = str(self.projet)
        env_base["CIME_ATTENTE_STOP"] = "0"
        env_base["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
        code = "import sys; from cime import cli; sys.exit(cli.main(sys.argv[1:]))"
        procs = []
        for agent, argv, entree in travaux:
            env = dict(env_base)
            if agent:
                env[VAR_AGENT] = agent
            procs.append(subprocess.Popen([sys.executable, "-c", code, *argv], env=env, text=True,
                                          stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE))
        # tous démarrent avant que l'un reçoive son entrée : la course est réelle
        resultats = []
        for p, (_, _, entree) in zip(procs, travaux):
            p.stdin.write(entree or "")
            p.stdin.close()
        for p in procs:
            sortie, erreur = p.stdout.read(), p.stderr.read()
            resultats.append((p.wait(), sortie, erreur))
        return resultats

    def prouve(self, sql: str, params=()) -> list:
        """Requête en LECTURE SEULE sur le registre du projet jetable ; lignes en tuples."""
        chemin = self.projet / ".orga" / "etat" / "registre.sqlite"
        conn = sqlite3.connect(f"file:{chemin}?mode=ro", uri=True, timeout=5.0)
        try:
            return [tuple(r) for r in conn.execute(sql, tuple(params)).fetchall()]
        finally:
            conn.close()
