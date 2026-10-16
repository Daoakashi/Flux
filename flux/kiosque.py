"""Mode kiosque (Linux) : Flux tourne seul, en plein écran, sans bureau, et redémarre tout seul.

Le mode est activé par le script kiosque.sh, qui lance Flux avec l'option --kiosque. Dans ce mode :
- la fenêtre reste en plein écran et ne peut pas être fermée (Alt+F4, F11 et la croix sont bloqués) ;
- Ctrl+Alt+Maj+Q demande le code administrateur, puis quitte le kiosque (retour à l'écran de connexion) ;
- une mise à jour ou un plantage relance Flux automatiquement (c'est la session kiosque qui s'en charge).

Le code administrateur est enregistré par kiosque.sh dans /etc/flux-kiosque.json, sous forme d'empreinte
(jamais en clair). Ce fichier appartient à root : on ne peut pas le modifier depuis Flux.
"""
import hashlib
import hmac
import json
import os
import sys
import tempfile

FICHIER_CODE = "/etc/flux-kiosque.json"
CODE_REDEMARRER = 3  # code de sortie : « relancez-moi » (mise à jour), compris par la session kiosque


def actif():
    return "--kiosque" in sys.argv


def fichier_sortie():
    """Fichier témoin : sa présence dit à la session kiosque que l'administrateur a voulu quitter."""
    dossier = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    return os.path.join(dossier, "flux-kiosque-quitter")


def code_defini():
    try:
        with open(FICHIER_CODE, encoding="utf-8") as f:
            d = json.load(f)
        return bool(d.get("sel") and d.get("empreinte"))
    except (OSError, ValueError):
        return False


def verifier(code):
    """Compare le code tapé à l'empreinte enregistrée (PBKDF2-SHA256)."""
    try:
        with open(FICHIER_CODE, encoding="utf-8") as f:
            d = json.load(f)
        calcule = hashlib.pbkdf2_hmac("sha256", code.encode("utf-8"), bytes.fromhex(d["sel"]),
                                      int(d.get("iterations", 200000))).hex()
        return hmac.compare_digest(calcule, d["empreinte"])
    except (OSError, ValueError, KeyError, TypeError):
        return False


def marquer_sortie():
    try:
        with open(fichier_sortie(), "w", encoding="utf-8") as f:
            f.write("1")
    except OSError:
        pass
