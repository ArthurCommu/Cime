"""Exécute un scénario Playwright de la page (tests/page/outils/scenario_*.py) avec un vrai navigateur.

sh tests/page/outils/nav.sh tests/page/outils/lancer_scenario.py <scenario.py> <dossier-captures>

Les scénarios lancent le Chrome du système et ouvrent plusieurs contextes dans un même navigateur.
Ici, Chromium headless de Playwright en --single-process seulement, où un second contexte ne s'ouvre pas et où
fermer un contexte ferme tout : on remplace `sync_playwright` par une enveloppe dont `chromium.launch` rend un
faux navigateur qui ouvre un vrai navigateur par contexte ; chaque contexte (1) bloque toute requête autre que
GET/HEAD, sauf celles qui vont au faux hôte (127.0.0.1 ou localhost, port CIME_PORT_TEST) quand
CIME_HOTE_FACTICE=oui (par défaut) ; (2) ne se ferme pas ; tous les navigateurs se ferment à la fin.
Le scénario lui-même n'est pas modifié (avec ou sans `main(sorties)`). Le faux hôte doit tourner déjà
(voir LISEZMOI-hote-test.md).
"""
import importlib.util
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

import playwright.sync_api

FAUX_HOTE = os.environ.get("CIME_HOTE_FACTICE", "oui") == "oui"
PORT_TEST = os.environ.get("CIME_PORT_TEST", "8791")
ORIGINE = playwright.sync_api.sync_playwright


def proxy():
    """Le proxy de l'environnement (HTTPS_PROXY) ; None sans proxy."""
    brut = os.environ.get("HTTPS_PROXY")
    if not brut:
        return None
    u = urlsplit(brut)
    return {"server": f"http://{u.hostname}:{u.port}", "username": u.username or "",
            "password": u.password or "", "bypass": "localhost,127.0.0.1"}


def vers_faux_hote(url):
    u = urlsplit(url)
    return u.hostname in ("127.0.0.1", "localhost") and str(u.port) == PORT_TEST


def garde(route):
    if route.request.method in ("GET", "HEAD") or (FAUX_HOTE and vers_faux_hote(route.request.url)):
        return route.fallback()
    print("BLOQUÉ", route.request.method, route.request.url, file=sys.stderr)
    return route.abort()


class Nav:
    """Un navigateur réel par contexte."""
    def __init__(self, lancer):
        self.lancer = lancer

    def new_context(self, **kw):
        ctx = self.lancer().new_context(**kw)
        ctx.route("**/*", garde)
        ctx.close = lambda: None
        return ctx

    def new_page(self, **kw):
        return self.new_context(**kw).new_page()

    def close(self):
        pass


class Enveloppe:
    def __init__(self):
        self.vrais = []

    def __enter__(self):
        self.cm = ORIGINE()
        p = self.cm.__enter__()
        lancer = p.chromium.launch

        def un_navigateur():
            n = lancer(headless=True, args=["--single-process"], proxy=proxy())
            self.vrais.append(n)
            return n

        p.chromium.launch = lambda **_: Nav(un_navigateur)
        return p

    def __exit__(self, *a):
        for n in self.vrais:
            try:
                n.close()
            except Exception:  # noqa: BLE001
                pass
        return self.cm.__exit__(*a)


def main():
    chemin, sorties = Path(sys.argv[1]), Path(sys.argv[2])
    sorties.mkdir(parents=True, exist_ok=True)
    playwright.sync_api.sync_playwright = Enveloppe
    sys.argv = [str(chemin), str(sorties)]
    spec = importlib.util.spec_from_file_location("scenario", chemin)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # un scénario sans main() s'exécute ici
    if hasattr(mod, "main"):
        # main(sorties) ou main() qui lit sys.argv[1]
        sys.exit(mod.main(sorties) if mod.main.__code__.co_argcount else mod.main())


if __name__ == "__main__":
    main()
