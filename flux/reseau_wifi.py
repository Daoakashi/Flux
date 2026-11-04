"""Connexion au réseau (WiFi) depuis Flux, sans passer par le bureau du système.

Indispensable en mode kiosque : la barre des tâches de Linux Mint n'est pas accessible, Flux doit donc savoir
choisir un réseau WiFi, taper son mot de passe, s'en déconnecter ou l'oublier.

Linux : NetworkManager (commande nmcli, présente sur Linux Mint, Ubuntu, Debian de bureau).
Windows : commande netsh wlan.
Toutes les fonctions sont bloquantes (quelques secondes) : à appeler dans un fil à part.
"""
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from xml.sax.saxutils import escape

WINDOWS = sys.platform == "win32"


class ErreurReseau(Exception):
    pass


def _env():
    e = dict(os.environ)
    e["LC_ALL"] = "C"  # messages de nmcli en anglais : plus faciles à reconnaître
    e["LANG"] = "C"
    return e


def _cmd(args, delai=20):
    opts = {"capture_output": True, "text": True, "timeout": delai}
    if WINDOWS:
        opts["creationflags"] = 0x08000000
        opts["encoding"] = "utf-8"
        opts["errors"] = "replace"
        args = ["cmd", "/c", "chcp 65001 >nul & " + subprocess.list2cmdline(args)]
    else:
        opts["env"] = _env()
    try:
        r = subprocess.run(args, **opts)
    except FileNotFoundError as e:
        raise ErreurReseau("outil réseau introuvable") from e
    except subprocess.TimeoutExpired as e:
        raise ErreurReseau("le système ne répond pas (délai dépassé)") from e
    return r.returncode, (r.stdout or ""), (r.stderr or "")


def disponible():
    """(oui/non, explication)"""
    if WINDOWS:
        return True, ""
    if sys.platform.startswith("linux"):
        if shutil.which("nmcli"):
            return True, ""
        return False, "NetworkManager (nmcli) est introuvable : installez-le avec « sudo apt install network-manager »."
    return False, "La gestion du réseau depuis Flux n'est disponible que sous Linux et Windows."


# ---------------------------------------------------------------------------
# Linux : nmcli
# ---------------------------------------------------------------------------
def _champs(ligne):
    """Ligne de « nmcli -t » : champs séparés par « : », avec « \\: » à l'intérieur d'un champ."""
    return [c.replace("\\:", ":").replace("\\\\", "\\") for c in re.split(r"(?<!\\):", ligne)]


def _nm(args, delai=20):
    code, out, err = _cmd(["nmcli", *args], delai)
    return code, out, (err or out).strip()


def _message_nm(texte):
    t = texte.lower()
    if "secrets were required" in t or "802-1x" in t or "wrong password" in t or "psk: property is invalid" in t \
            or "invalid passphrase" in t or "no secrets" in t:
        return "mot de passe refusé par le réseau"
    if "no network with ssid" in t:
        return "réseau introuvable (trop loin, ou nom mal écrit)"
    if "not authorized" in t or "insufficient privileges" in t or "permission" in t:
        return "autorisation refusée par le système"
    if "timeout" in t or "timed out" in t:
        return "le réseau ne répond pas (délai dépassé)"
    if "no wi-fi device" in t or "no suitable device" in t:
        return "aucune carte WiFi trouvée"
    return texte.splitlines()[-1][:200] if texte.strip() else "erreur inconnue"


def _carte_wifi():
    code, out, _ = _nm(["-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"])
    wifi = cable = None
    for l in out.splitlines():
        c = _champs(l)
        if len(c) < 4:
            continue
        if c[1] == "wifi" and wifi is None:
            wifi = {"appareil": c[0], "etat": c[2], "connexion": c[3]}
        if c[1] == "ethernet" and c[2] == "connected":
            cable = {"appareil": c[0], "connexion": c[3]}
    return wifi, cable


def _ip(appareil):
    if not appareil:
        return ""
    _, out, _ = _nm(["-t", "-f", "IP4.ADDRESS", "device", "show", appareil])
    for l in out.splitlines():
        m = re.search(r"(\d+\.\d+\.\d+\.\d+)", l)
        if m:
            return m.group(1)
    return ""


def _connus_linux():
    """{ssid: nom de la connexion enregistrée}"""
    _, out, _ = _nm(["-t", "-f", "NAME,TYPE", "connection", "show"])
    noms = [_champs(l)[0] for l in out.splitlines() if len(_champs(l)) >= 2 and _champs(l)[1] in ("802-11-wireless", "wifi")]
    connus = {}
    for n in noms:
        code, ssid, _ = _nm(["-g", "802-11-wireless.ssid", "connection", "show", "id", n], 8)
        connus[(ssid.strip() or n)] = n
    return connus


def _etat_linux():
    code, radio, _ = _nm(["-t", "-f", "WIFI", "radio"])
    wifi, cable = _carte_wifi()
    e = {"wifi_present": wifi is not None, "wifi_actif": radio.strip() == "enabled", "ssid": "", "signal": None, "ip": "",
         "cable": bool(cable), "ip_cable": _ip(cable["appareil"]) if cable else "", "appareil": wifi and wifi["appareil"]}
    if wifi and wifi["etat"] == "connected":
        _, out, _ = _nm(["-t", "-f", "ACTIVE,SSID,SIGNAL", "device", "wifi", "list", "--rescan", "no"])
        for l in out.splitlines():
            c = _champs(l)
            if len(c) >= 3 and c[0] == "yes":
                e["ssid"], e["signal"] = c[1], int(c[2]) if c[2].isdigit() else None
                break
        e["ssid"] = e["ssid"] or wifi["connexion"]
        e["ip"] = _ip(wifi["appareil"])
    return e


def _reseaux_linux(balayer=True):
    args = ["-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "yes" if balayer else "no"]
    code, out, err = _nm(args, 30)
    if code != 0 and balayer:  # balayage refusé ou trop fréquent : liste en mémoire
        code, out, err = _nm(args[:-1] + ["no"], 15)
    if code != 0:
        raise ErreurReseau(_message_nm(err))
    connus = _connus_linux()
    vus = {}
    for l in out.splitlines():
        c = _champs(l)
        if len(c) < 4 or not c[1]:
            continue
        ssid = c[1]
        signal = int(c[2]) if c[2].isdigit() else 0
        r = {"ssid": ssid, "signal": signal, "securise": bool(c[3].strip()) and c[3].strip() != "--",
             "securite": c[3].strip(), "actif": c[0].strip() == "*", "connu": ssid in connus}
        p = vus.get(ssid)
        if p is None or (r["actif"] and not p["actif"]) or (r["actif"] == p["actif"] and signal > p["signal"]):
            vus[ssid] = r
    return sorted(vus.values(), key=lambda r: (not r["actif"], -r["signal"]))


def _connecter_linux(ssid, mdp=None, cache=False):
    connus = _connus_linux()
    if ssid in connus and not mdp:
        code, out, err = _nm(["--wait", "40", "connection", "up", "id", connus[ssid]], 50)
        if code == 0:
            return "connecté"
        raise ErreurReseau(_message_nm(err))
    if ssid in connus and mdp:  # nouveau mot de passe : on repart d'une connexion propre
        _nm(["connection", "delete", "id", connus[ssid]], 15)
    args = ["--wait", "40", "device", "wifi", "connect", ssid]
    if mdp:
        args += ["password", mdp]
    if cache:
        args += ["hidden", "yes"]
    code, out, err = _nm(args, 50)
    if code == 0:
        return "connecté"
    msg = _message_nm(err)
    if msg != "autorisation refusée par le système":
        raise ErreurReseau(msg)
    # Session sans fenêtre d'autorisation (kiosque) : connexion réservée à ce compte, autorisée sans mot de passe
    # administrateur par NetworkManager.
    import getpass
    nom = f"Flux {ssid}"[:60]
    _nm(["connection", "delete", "id", nom], 10)
    ajout = ["connection", "add", "type", "wifi", "con-name", nom, "ssid", ssid,
             "connection.permissions", f"user:{getpass.getuser()}"]
    if cache:
        ajout += ["802-11-wireless.hidden", "yes"]
    if mdp:
        ajout += ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", mdp, "wifi-sec.psk-flags", "0"]
    code, out, err = _nm(ajout, 15)
    if code != 0:
        raise ErreurReseau(_message_nm(err) + ". Relancez « sudo bash kiosque.sh activer » pour autoriser Flux à "
                                              "gérer le réseau.")
    code, out, err = _nm(["--wait", "40", "connection", "up", "id", nom], 50)
    if code != 0:
        _nm(["connection", "delete", "id", nom], 10)
        raise ErreurReseau(_message_nm(err))
    return "connecté"


def _deconnecter_linux():
    wifi, _ = _carte_wifi()
    if not wifi:
        raise ErreurReseau("aucune carte WiFi trouvée")
    code, out, err = _nm(["device", "disconnect", wifi["appareil"]], 20)
    if code != 0:
        raise ErreurReseau(_message_nm(err))


def _oublier_linux(ssid):
    n = _connus_linux().get(ssid)
    if not n:
        raise ErreurReseau("ce réseau n'est pas enregistré")
    code, out, err = _nm(["connection", "delete", "id", n], 20)
    if code != 0:
        raise ErreurReseau(_message_nm(err))


def _radio_linux(actif):
    code, out, err = _nm(["radio", "wifi", "on" if actif else "off"], 15)
    if code != 0:
        raise ErreurReseau(_message_nm(err))


# ---------------------------------------------------------------------------
# Windows : netsh wlan
# ---------------------------------------------------------------------------
def _valeur(texte, *cles):
    for l in texte.splitlines():
        m = re.match(r"^\s*([^:]+?)\s*:\s(.*)$", l)
        if m and m.group(1).strip().lower() in cles:
            return m.group(2).strip()
    return ""


def _etat_windows():
    _, out, _ = _cmd(["netsh", "wlan", "show", "interfaces"])
    ssid = _valeur(out, "ssid")
    sig = _valeur(out, "signal")
    m = re.search(r"\d+", sig)
    return {"wifi_present": "ssid" in out.lower() or "interface" in out.lower(), "wifi_actif": True, "ssid": ssid,
            "signal": int(m.group()) if m else None, "ip": _ip_windows() if ssid else "", "cable": False, "ip_cable": "",
            "appareil": _valeur(out, "name", "nom")}


def _ip_windows():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 9))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return ""


def _connus_windows():
    _, out, _ = _cmd(["netsh", "wlan", "show", "profiles"])
    connus = {}
    for l in out.splitlines():
        m = re.match(r"^\s{2,}.+?\s:\s(.+)$", l)
        if m:
            connus[m.group(1).strip()] = m.group(1).strip()
    return connus


def _reseaux_windows(balayer=True):
    code, out, err = _cmd(["netsh", "wlan", "show", "networks", "mode=bssid"], 20)
    if code != 0:
        raise ErreurReseau((err or out).strip()[:200] or "WiFi indisponible")
    actif = _etat_windows()["ssid"]
    connus = _connus_windows()
    vus, courant = {}, None
    for l in out.splitlines():
        m = re.match(r"^SSID \d+\s*:\s(.*)$", l.strip())
        if m:
            courant = {"ssid": m.group(1).strip(), "signal": 0, "securise": True, "securite": "", "actif": False, "connu": False}
            if courant["ssid"]:
                vus.setdefault(courant["ssid"], courant)
                courant = vus[courant["ssid"]]
            continue
        if courant is None:
            continue
        m = re.match(r"^\s*(Authentication|Authentification)\s*:\s(.*)$", l)
        if m:
            courant["securite"] = m.group(2).strip()
            courant["securise"] = not re.search(r"open|ouvert", m.group(2), re.I)
        m = re.match(r"^\s*Signal\s*:\s*(\d+)", l)
        if m:
            courant["signal"] = max(courant["signal"], int(m.group(1)))
    for r in vus.values():
        r["actif"] = r["ssid"] == actif
        r["connu"] = r["ssid"] in connus
    return sorted(vus.values(), key=lambda r: (not r["actif"], -r["signal"]))


def _connecter_windows(ssid, mdp=None, cache=False):
    if mdp or ssid not in _connus_windows():
        s = escape(ssid)
        if mdp:
            secu = (f"<authEncryption><authentication>WPA2PSK</authentication><encryption>AES</encryption>"
                    f"<useOneX>false</useOneX></authEncryption><sharedKey><keyType>passPhrase</keyType>"
                    f"<protected>false</protected><keyMaterial>{escape(mdp)}</keyMaterial></sharedKey>")
        else:
            secu = "<authEncryption><authentication>open</authentication><encryption>none</encryption><useOneX>false</useOneX></authEncryption>"
        xml = (f'<?xml version="1.0"?><WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">'
               f"<name>{s}</name><SSIDConfig><SSID><name>{s}</name></SSID><nonBroadcast>{'true' if cache else 'false'}"
               f"</nonBroadcast></SSIDConfig><connectionType>ESS</connectionType><connectionMode>auto</connectionMode>"
               f"<MSM><security>{secu}</security></MSM></WLANProfile>")
        f = tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-8")
        try:
            f.write(xml)
            f.close()
            code, out, err = _cmd(["netsh", "wlan", "add", "profile", f"filename={f.name}", "user=all"], 20)
            if code != 0:
                code, out, err = _cmd(["netsh", "wlan", "add", "profile", f"filename={f.name}", "user=current"], 20)
            if code != 0:
                raise ErreurReseau((err or out).strip()[:200])
        finally:
            try:
                os.remove(f.name)
            except OSError:
                pass
    code, out, err = _cmd(["netsh", "wlan", "connect", f"name={ssid}", f"ssid={ssid}"], 20)
    if code != 0:
        raise ErreurReseau((err or out).strip()[:200])
    for _ in range(20):  # la connexion est asynchrone sous Windows
        time.sleep(1)
        if _etat_windows()["ssid"] == ssid:
            return "connecté"
    raise ErreurReseau("pas de connexion après 20 secondes (mot de passe ?)")


def _deconnecter_windows():
    code, out, err = _cmd(["netsh", "wlan", "disconnect"], 15)
    if code != 0:
        raise ErreurReseau((err or out).strip()[:200])


def _oublier_windows(ssid):
    code, out, err = _cmd(["netsh", "wlan", "delete", "profile", f"name={ssid}"], 15)
    if code != 0:
        raise ErreurReseau((err or out).strip()[:200])


# ---------------------------------------------------------------------------
# Interface commune
# ---------------------------------------------------------------------------
def etat():
    """{"wifi_present", "wifi_actif", "ssid", "signal", "ip", "cable", "ip_cable", "appareil"}"""
    return _etat_windows() if WINDOWS else _etat_linux()


def reseaux(balayer=True):
    """Réseaux WiFi à portée : [{"ssid", "signal", "securise", "securite", "actif", "connu"}]"""
    return _reseaux_windows(balayer) if WINDOWS else _reseaux_linux(balayer)


def connecter(ssid, mdp=None, cache=False):
    if not ssid:
        raise ErreurReseau("nom du réseau manquant")
    if mdp is not None and mdp != "" and not (8 <= len(mdp) <= 63):
        raise ErreurReseau("un mot de passe WiFi compte de 8 à 63 caractères")
    return _connecter_windows(ssid, mdp or None, cache) if WINDOWS else _connecter_linux(ssid, mdp or None, cache)


def deconnecter():
    return _deconnecter_windows() if WINDOWS else _deconnecter_linux()


def oublier(ssid):
    return _oublier_windows(ssid) if WINDOWS else _oublier_linux(ssid)


def radio(actif):
    if WINDOWS:
        raise ErreurReseau("sous Windows, activez le WiFi depuis la barre des tâches")
    return _radio_linux(actif)


def internet(delai=4):
    """Internet répond-il ? (connexion à des serveurs DNS publics, sans rien envoyer)"""
    for hote in (("1.1.1.1", 443), ("8.8.8.8", 443), ("9.9.9.9", 443)):
        try:
            socket.create_connection(hote, timeout=delai).close()
            return True
        except OSError:
            continue
    return False


def barres(signal):
    """Petit indicateur de force du signal : ▂▄▆█"""
    if signal is None:
        return ""
    n = 1 if signal < 30 else 2 if signal < 55 else 3 if signal < 75 else 4
    return "▂▄▆█"[:n] + "·" * (4 - n)
