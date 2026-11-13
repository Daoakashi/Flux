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


# ---------------------------------------------------------------------------------------------------------------
# Installation depuis Flux (Réglages › Mode kiosque) : lance kiosque.sh avec les droits administrateur, sans terminal
# ---------------------------------------------------------------------------------------------------------------
SESSION_KIOSQUE = "/usr/local/bin/flux-kiosque-session"
DOSSIER_ETC = "/etc/flux-kiosque"


def installable():
    """Le mode kiosque n'existe que sous Linux (LightDM ou GDM) et pas depuis une session kiosque."""
    return sys.platform.startswith("linux") and not actif()


def installe():
    return os.path.isfile(SESSION_KIOSQUE)


def _lire(nom):
    try:
        with open(os.path.join(DOSSIER_ETC, nom), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def etat():
    """{'installe', 'utilisateur', 'dossier', 'code', 'redemarrage', 'verrou'} (lisible sans droits particuliers)."""
    cron = ""
    try:
        with open("/etc/cron.d/flux-kiosque", encoding="utf-8") as f:
            for ligne in f:
                if "shutdown" in ligne and not ligne.lstrip().startswith("#"):
                    cron = ligne.split()[1]
    except OSError:
        pass
    return {"installe": installe(), "utilisateur": _lire("utilisateur"), "dossier": _lire("dossier"),
            "code": code_defini(), "redemarrage": cron, "verrou": os.path.isfile("/etc/X11/xorg.conf.d/90-flux-kiosque.conf")}


def commande_terminal(action, utilisateur="", heure="", verrouiller=False):
    """La commande équivalente à taper dans un terminal (affichée si la fenêtre d'autorisation est indisponible)."""
    c = f"sudo bash {os.path.join(_racine(), 'kiosque.sh')} {action}"
    if action == "activer":
        if utilisateur:
            c += f" --utilisateur {utilisateur}"
        if heure != "":
            c += f" --redemarrage {heure}"
        if verrouiller:
            c += " --verrouiller"
    return c


def _racine():
    from .config import RACINE
    return RACINE


def lancer(action, utilisateur="", heure="", verrouiller=False, code=None, delai=1200):
    """Exécute « kiosque.sh <action> » en administrateur. pkexec ouvre la fenêtre habituelle du système qui demande le
    mot de passe du PC ; le code administrateur du kiosque est transmis par l'entrée standard (jamais en argument,
    donc invisible dans la liste des processus). Renvoie (réussi, texte de sortie)."""
    import shutil
    import subprocess
    script = os.path.join(_racine(), "kiosque.sh")
    if not os.path.isfile(script):
        return False, "kiosque.sh est introuvable dans le dossier de Flux."
    cmd = ["bash", script, action]
    if action == "activer":
        if utilisateur:
            cmd += ["--utilisateur", utilisateur]
        if heure != "":
            cmd += ["--redemarrage", str(heure)]
        if verrouiller:
            cmd.append("--verrouiller")
    if code is not None:
        cmd.append("--code-stdin")
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        pk = shutil.which("pkexec")
        if not pk:
            return False, ("La fenêtre d'autorisation du système (pkexec) est absente. Dans un terminal :\n"
                           + commande_terminal(action, utilisateur, heure, verrouiller))
        cmd = [pk] + cmd
    try:
        r = subprocess.run(cmd, input=(code + "\n") if code is not None else "", capture_output=True, text=True,
                           timeout=delai, errors="replace")
    except subprocess.TimeoutExpired:
        return False, "L'opération a pris trop de temps (connexion Internet pour installer Openbox ?)."
    except OSError as e:
        return False, str(e)
    sortie = (r.stdout + ("\n" + r.stderr if r.stderr.strip() else "")).strip()
    if r.returncode in (126, 127) and not sortie:
        return False, "Autorisation refusée ou annulée : le mot de passe du PC est demandé pour modifier le système."
    return r.returncode == 0, sortie
