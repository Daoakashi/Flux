"""Accès à Flux depuis les autres appareils du réseau local (WiFi, câble).

- Nom sur le réseau : Flux répond au nom « flux.local » (mDNS, la même technique que les imprimantes et
  les Mac). Les PC Windows 10/11, Mac, iPhone et Linux le trouvent seuls. Écrit sans module externe.
- Redirection : « http://… » (sans s, ce que les navigateurs essaient quand on tape l'adresse à la main) est
  renvoyé vers « https://… » au lieu d'une page vide.
- Pare-feu : détection du pare-feu de Windows ou de Linux et commande pour autoriser Flux (une seule fois).
- DuckDNS : un nom de domaine gratuit peut pointer vers l'adresse locale de ce PC (mis à jour tout seul).
"""
import ipaddress
import os
import re
import select
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request

MDNS_GROUPE, MDNS_PORT = "224.0.0.251", 5353
TTL = 120


def nom_valide(texte, defaut="flux"):
    """« Flux Caisse 2 » -> « flux-caisse-2 » (étiquette DNS : lettres, chiffres, tirets)."""
    import unicodedata
    t = unicodedata.normalize("NFKD", str(texte or "")).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"\.local$", "", t.strip())
    t = re.sub(r"[^a-z0-9-]+", "-", t).strip("-")[:63]
    return t or defaut


def domaine_valide(texte):
    t = str(texte or "").strip().lower().rstrip(".")
    t = re.sub(r"^https?://", "", t).split("/")[0].split(":")[0]
    if t and re.fullmatch(r"(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{2,63}", t):
        return t
    return ""


def ip_privee(ip):
    try:
        a = ipaddress.ip_address(ip)
        return a.version == 4 and a.is_private and not a.is_loopback and not a.is_link_local
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# mDNS : répondre au nom « xxx.local »
# ---------------------------------------------------------------------------
def _encoder_nom(nom):
    return b"".join(bytes([len(p)]) + p.encode("ascii") for p in nom.strip(".").split(".")) + b"\0"


def _lire_nom(paquet, i, profondeur=0):
    morceaux = []
    while True:
        if i >= len(paquet) or profondeur > 20:
            raise ValueError("nom tronqué")
        n = paquet[i]
        if n == 0:
            return ".".join(morceaux), i + 1
        if n & 0xC0 == 0xC0:
            ptr = struct.unpack("!H", paquet[i:i + 2])[0] & 0x3FFF
            suite, _ = _lire_nom(paquet, ptr, profondeur + 1)
            if suite:
                morceaux.append(suite)
            return ".".join(morceaux), i + 2
        morceaux.append(paquet[i + 1:i + 1 + n].decode("ascii", "replace"))
        i += 1 + n


def lire_questions(paquet):
    """[(nom, type, unicast)] des questions d'une requête mDNS (vide si c'est une réponse)."""
    if len(paquet) < 12:
        return [], 0
    ident, drapeaux, qd = struct.unpack("!HHH", paquet[:6])
    if drapeaux & 0x8000:
        return [], ident
    i, l = 12, []
    for _ in range(min(qd, 32)):
        nom, i = _lire_nom(paquet, i)
        qtype, qclasse = struct.unpack("!HH", paquet[i:i + 4])
        i += 4
        l.append((nom.lower(), qtype, bool(qclasse & 0x8000)))
    return l, ident


def lire_reponses_a(paquet):
    """[(nom, ip)] des enregistrements A d'une réponse (pour voir si un autre appareil a déjà ce nom)."""
    if len(paquet) < 12:
        return []
    _, drapeaux, qd, an, ns, ar = struct.unpack("!HHHHHH", paquet[:12])
    if not drapeaux & 0x8000:
        return []
    i = 12
    for _ in range(qd):
        _, i = _lire_nom(paquet, i)
        i += 4
    l = []
    for _ in range(an + ns + ar):
        nom, i = _lire_nom(paquet, i)
        typ, _, _, lg = struct.unpack("!HHIH", paquet[i:i + 10])
        i += 10
        if typ == 1 and lg == 4:
            l.append((nom.lower(), socket.inet_ntoa(paquet[i:i + 4])))
        i += lg
    return l


def construire_reponse(nom, ips, ident=0, question=False, ttl=TTL):
    """Réponse mDNS : un enregistrement A par adresse (bit « cache-flush » : ces adresses remplacent les anciennes)."""
    n = _encoder_nom(nom)
    corps = b""
    if question:
        corps += n + struct.pack("!HH", 1, 1)
    for ip in ips:
        corps += n + struct.pack("!HHIH", 1, 0x8001 if not question else 1, ttl, 4) + socket.inet_aton(ip)
    return struct.pack("!HHHHHH", ident, 0x8400, 1 if question else 0, len(ips), 0, 0) + corps


def construire_question(nom):
    return struct.pack("!HHHHHH", 0, 0, 1, 0, 0, 0) + _encoder_nom(nom) + struct.pack("!HH", 1, 0x8001)


def adresses_lan():
    from .mobile_serveur import adresses_locales
    l = [ip for ip in adresses_locales() if ip_privee(ip)]
    return l or [ip for ip in adresses_locales() if not ip.startswith("127.")]


class RepondeurMDNS(threading.Thread):
    """Répond « je suis xxx.local » aux appareils du réseau. Fonctionne à côté d'Avahi (Linux) et du service mDNS
    de Windows : chacun répond pour ses propres noms."""

    def __init__(self, nom, journal=None):
        super().__init__(daemon=True, name="flux-mdns")
        self.voulu = nom_valide(nom) + ".local"
        self.nom = self.voulu
        self.journal = journal or (lambda texte, niveau="info": None)
        self.arret = threading.Event()
        self.erreur = ""
        self.ips = []
        self._s = None
        self._rejoints = set()
        self._ident = "%04x" % (os.getpid() & 0xFFFF)

    def _ouvrir(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        s.bind(("", MDNS_PORT))
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
        self._s = s

    def _rejoindre(self):
        self.ips = adresses_lan()
        for ip in self.ips:
            if ip in self._rejoints:
                continue
            try:
                self._s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                                   socket.inet_aton(MDNS_GROUPE) + socket.inet_aton(ip))
                self._rejoints.add(ip)
            except OSError:
                pass
        if not self._rejoints:
            try:
                self._s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                                   socket.inet_aton(MDNS_GROUPE) + socket.inet_aton("0.0.0.0"))
                self._rejoints.add("0.0.0.0")
            except OSError:
                pass

    def _envoyer_multicast(self, paquet):
        for ip in self.ips or ["0.0.0.0"]:
            try:
                self._s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
                self._s.sendto(paquet, (MDNS_GROUPE, MDNS_PORT))
            except OSError:
                pass

    def _ips_pour(self, adresse):
        """L'adresse de ce PC sur le même réseau que celui qui demande (sinon toutes)."""
        try:
            a = ipaddress.ip_address(adresse)
            memes = [ip for ip in self.ips if a in ipaddress.ip_network(ip + "/24", strict=False)]
            return memes or self.ips
        except ValueError:
            return self.ips

    def _nom_pris(self, nom):
        """Un autre appareil répond-il déjà à ce nom ? (trois questions, 250 ms chacune)"""
        q = construire_question(nom)
        fin = time.time() + 0.8
        prochaine = 0
        while time.time() < fin:
            if time.time() >= prochaine:
                self._envoyer_multicast(q)
                prochaine = time.time() + 0.25
            r, _, _ = select.select([self._s], [], [], 0.05)
            if not r:
                continue
            try:
                paquet, (ip, _) = self._s.recvfrom(9000)
            except OSError:
                continue
            for n, a in lire_reponses_a(paquet):
                if n == nom and a not in self.ips and ip not in self.ips:
                    return True
        return False

    def run(self):
        try:
            self._ouvrir()
            self._rejoindre()
        except OSError as e:
            self.erreur = f"nom sur le réseau indisponible ({e.strerror or e})"
            self.journal(f"Réseau local : {self.erreur}. L'adresse IP reste utilisable.", "erreur")
            return
        if self._nom_pris(self.nom):
            base = self.nom[:-6]
            self.nom = f"{base}-{self._ident[:4]}.local"
            self.journal(f"Réseau local : le nom {self.voulu} est déjà pris par un autre appareil, Flux utilise "
                         f"{self.nom}. Choisissez un nom unique (Réglages › Développeur).", "erreur")
        for _ in range(2):  # annonce : les appareils qui ont gardé une ancienne adresse la remplacent
            self._envoyer_multicast(construire_reponse(self.nom, self.ips))
            time.sleep(1)
        t_ips = time.time()
        while not self.arret.is_set():
            if time.time() - t_ips > 60:  # changement d'adresse (DHCP), nouvelle carte réseau
                t_ips = time.time()
                avant = list(self.ips)
                self._rejoindre()
                if self.ips != avant:
                    self._envoyer_multicast(construire_reponse(self.nom, self.ips))
            try:
                r, _, _ = select.select([self._s], [], [], 1.0)
            except (OSError, ValueError):
                break
            if not r:
                continue
            try:
                paquet, (ip, port) = self._s.recvfrom(9000)
                questions, ident = lire_questions(paquet)
            except (OSError, ValueError, struct.error):
                continue
            for nom, qtype, unicast in questions:
                if nom != self.nom or qtype not in (1, 255) or not self.ips:
                    continue
                ips = self._ips_pour(ip)
                try:
                    if port != MDNS_PORT:  # requête « classique » (nslookup, certains Android) : réponse directe
                        self._s.sendto(construire_reponse(self.nom, ips, ident, question=True, ttl=10), (ip, port))
                    elif unicast:
                        self._s.sendto(construire_reponse(self.nom, ips), (ip, port))
                    else:
                        self._envoyer_multicast(construire_reponse(self.nom, ips))
                except OSError:
                    pass
        try:
            self._envoyer_multicast(construire_reponse(self.nom, self.ips, ttl=0))  # « je pars »
            self._s.close()
        except OSError:
            pass

    def arreter(self):
        self.arret.set()


# ---------------------------------------------------------------------------
# http:// -> https://
# ---------------------------------------------------------------------------
def reponse_redirection(requete, port_https):
    """Réponse HTTP 301 vers la même adresse en https (requete : octets reçus en clair)."""
    try:
        texte = requete.decode("latin-1")
        ligne = texte.split("\r\n", 1)[0].split(" ")
        chemin = ligne[1] if len(ligne) > 1 and ligne[1].startswith("/") else "/"
        hote = ""
        for l in texte.split("\r\n")[1:]:
            if l.lower().startswith("host:"):
                hote = l.split(":", 1)[1].strip()
                break
    except (UnicodeDecodeError, IndexError):
        chemin, hote = "/", ""
    if hote.startswith("["):
        nom = hote.split("]")[0] + "]"
    else:
        nom = hote.split(":")[0]
    if not re.fullmatch(r"[A-Za-z0-9.\-\[\]:]{1,255}", nom or ""):
        nom = adresses_lan()[0] if adresses_lan() else "localhost"
    cible = f"https://{nom}{'' if port_https == 443 else f':{port_https}'}{chemin}"
    corps = f"<!doctype html><meta charset=utf-8><a href=\"{cible}\">{cible}</a>".encode()
    return (f"HTTP/1.1 301 Moved Permanently\r\nLocation: {cible}\r\nContent-Type: text/html; charset=utf-8\r\n"
            f"Content-Length: {len(corps)}\r\nConnection: close\r\nCache-Control: no-store\r\n\r\n").encode() + corps


def lire_requete_claire(sock, limite=8192, delai=5):
    sock.settimeout(delai)
    donnees = b""
    try:
        while b"\r\n\r\n" not in donnees and len(donnees) < limite:
            morceau = sock.recv(2048)
            if not morceau:
                break
            donnees += morceau
    except OSError:
        pass
    return donnees


# ---------------------------------------------------------------------------
# Pare-feu
# ---------------------------------------------------------------------------
def _sans_console():
    if sys.platform == "win32":
        return {"creationflags": 0x08000000}
    return {}


def _executer(cmd, delai=8):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=delai, **_sans_console())
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.SubprocessError) as e:
        return -1, str(e)


def etat_pare_feu(ports):
    """{"systeme", "actif", "regle", "texte"} : regle = True si Flux est déjà autorisé (None si inconnu)."""
    ports = sorted(set(int(p) for p in ports))
    if sys.platform == "win32":
        code, sortie = _executer(["netsh", "advfirewall", "firewall", "show", "rule", "name=Flux"])
        regle = code == 0 and all(str(p) in sortie for p in ports)
        code2, s2 = _executer(["netsh", "advfirewall", "show", "allprofiles", "state"])
        actif = None if code2 != 0 else ("ON" in s2.upper() or "ACTIV" in s2.upper())
        return {"systeme": "Windows", "actif": actif, "regle": regle,
                "texte": "Pare-feu Windows : Flux est autorisé." if regle else
                "Pare-feu Windows : si un autre appareil n'arrive pas à ouvrir Flux, autorisez-le (une seule fois, "
                "Windows demande la confirmation d'un administrateur)."}
    if sys.platform.startswith("linux"):
        try:
            with open("/etc/ufw/ufw.conf", encoding="utf-8") as f:
                ufw = re.search(r"^\s*ENABLED\s*=\s*yes", f.read(), re.M | re.I) is not None
        except OSError:
            ufw = False
        if ufw:
            return {"systeme": "ufw", "actif": True, "regle": None,
                    "texte": "Pare-feu ufw actif : autorisez les ports de Flux pour les autres appareils."}
        code, sortie = _executer(["firewall-cmd", "--state"], 4)
        if code == 0 and "running" in sortie:
            return {"systeme": "firewalld", "actif": True, "regle": None,
                    "texte": "Pare-feu firewalld actif : autorisez les ports de Flux pour les autres appareils."}
        return {"systeme": "linux", "actif": False, "regle": True,
                "texte": "Aucun pare-feu actif sur ce PC : rien à autoriser."}
    return {"systeme": sys.platform, "actif": None, "regle": None, "texte": ""}


def commande_pare_feu(systeme, ports):
    ports = sorted(set(int(p) for p in ports))
    liste = ",".join(map(str, ports))
    if systeme == "Windows":
        interne = (f"netsh advfirewall firewall delete rule name=Flux & netsh advfirewall firewall delete rule "
                   f"name=Flux-mDNS & netsh advfirewall firewall add rule name=Flux dir=in action=allow protocol=TCP "
                   f"localport={liste} profile=any & netsh advfirewall firewall add rule name=Flux-mDNS dir=in "
                   f"action=allow protocol=UDP localport=5353 profile=any")
        return ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command",
                f"Start-Process cmd -Verb RunAs -WindowStyle Hidden -Wait -ArgumentList '/c {interne}'"]
    if systeme == "ufw":
        return ["pkexec", "sh", "-c", " && ".join([f"ufw allow {p}/tcp" for p in ports] + ["ufw allow 5353/udp"])]
    if systeme == "firewalld":
        return ["pkexec", "sh", "-c", " && ".join([f"firewall-cmd --permanent --add-port={p}/tcp" for p in ports]
                                                   + ["firewall-cmd --permanent --add-service=mdns",
                                                      "firewall-cmd --reload"])]
    return None


def autoriser_pare_feu(systeme, ports):
    """Ouvre la fenêtre d'autorisation du système. Renvoie (ok, message)."""
    cmd = commande_pare_feu(systeme, ports)
    if not cmd:
        return False, "Rien à faire sur ce système."
    code, sortie = _executer(cmd, 120)
    if code == 0:
        return True, "Flux est autorisé dans le pare-feu."
    if systeme != "Windows":
        return False, f"Autorisation refusée. Dans un terminal : sudo sh -c \"{cmd[3]}\""
    return False, f"Le pare-feu n'a pas été modifié ({sortie.strip()[:200] or code})."


# ---------------------------------------------------------------------------
# Ports 80 et 443 sous Linux (réservés à l'administrateur par défaut)
# ---------------------------------------------------------------------------
def premier_port_libre_linux():
    try:
        with open("/proc/sys/net/ipv4/ip_unprivileged_port_start", encoding="ascii") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


COMMANDE_PORTS_LINUX = ["pkexec", "sh", "-c",
                        "echo 'net.ipv4.ip_unprivileged_port_start=80' > /etc/sysctl.d/60-flux.conf && "
                        "sysctl -w net.ipv4.ip_unprivileged_port_start=80"]


def autoriser_ports_linux():
    code, sortie = _executer(COMMANDE_PORTS_LINUX, 120)
    if code == 0:
        return True, "Les ports 80 et 443 sont autorisés : redémarrez le serveur FluxLite."
    return False, ("Autorisation refusée. Dans un terminal : sudo sh -c \"echo "
                   "'net.ipv4.ip_unprivileged_port_start=80' > /etc/sysctl.d/60-flux.conf && sysctl -w "
                   "net.ipv4.ip_unprivileged_port_start=80\"")


# ---------------------------------------------------------------------------
# DuckDNS : nom de domaine gratuit pointant vers l'adresse locale
# ---------------------------------------------------------------------------
def maj_duckdns(domaine, jeton, ip):
    """Inscrit ip pour monnom.duckdns.org. Renvoie (ok, message)."""
    d = domaine_valide(domaine)
    if not d.endswith(".duckdns.org") or not jeton:
        return False, "nom DuckDNS ou jeton manquant"
    sous = d[:-len(".duckdns.org")].split(".")[-1]
    url = "https://www.duckdns.org/update?" + urllib.parse.urlencode({"domains": sous, "token": jeton.strip(), "ip": ip})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Flux"}), timeout=15) as r:
            texte = r.read(64).decode("ascii", "replace").strip()
    except OSError as e:
        return False, f"DuckDNS injoignable ({e})"
    return (texte.startswith("OK"), "adresse inscrite" if texte.startswith("OK") else "jeton ou nom refusé par DuckDNS")
