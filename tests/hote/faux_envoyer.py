"""Faux `cime envoyer` : note ses arguments et son environnement, sort 0 (ou 1 si FAUX_REFUS)."""
import json
import os
import sys
from pathlib import Path

Path(os.environ["FAUX_NOTE"]).write_text(json.dumps({
    "argv": sys.argv[1:],
    "CIME_AGENT": os.environ.get("CIME_AGENT"),
    "CIME_PROJET": os.environ.get("CIME_PROJET"),
    "cwd": os.getcwd(),
}))
if os.environ.get("FAUX_REFUS"):
    print("registre indisponible", file=sys.stderr)
    sys.exit(1)
