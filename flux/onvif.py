"""ONVIF sans dépendance : recherche des caméras (WS-Discovery) et récupération de l'adresse RTSP.

Couvre ce dont Flux a besoin : GetSystemDateAndTime (décalage d'horloge), GetCapabilities,
GetProfiles et GetStreamUri du service Media (ONVIF Profile S), avec authentification
WS-UsernameToken (mot de passe condensé), comme l'exigent la plupart des caméras.
"""

import base64
import datetime as dt
import hashlib
import os
import re
import socket
import time
import urllib.error
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from urllib.parse import quote, urlparse, urlunparse

NS = {
    "s": "http://www.w3.org/2003/05/soap-envelope",
    "tds": "http://www.onvif.org/ver10/device/wsdl",
    "trt": "http://www.onvif.org/ver10/media/wsdl",
    "tt": "http://www.onvif.org/ver10/schema",
    "d": "http://schemas.xmlsoap.org/ws/2005/04/discovery",
    "a": "http://schemas.xmlsoap.org/ws/2004/08/addressing",
}
PORT_DECOUVERTE = 3702
MULTICAST = ("239.255.255.250", PORT_DECOUVERTE)


class ErreurOnvif(Exception):
    pass


# ---------------------------------------------------------------------------
# Recherche sur le réseau local
# ---------------------------------------------------------------------------
def _sonde():
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
 xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
 xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
 xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
 <e:Header>
  <w:MessageID>uuid:{uuid.uuid4()}</w:MessageID>
  <w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>
  <w:Action e:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>
 </e:Header>
 <e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body>
</e:Envelope>""".encode()


def analyser_reponse_decouverte(xml_octets, ip=None):
    """Extrait adresse(s) de service, nom et modèle d'une réponse ProbeMatch."""
    racine = ET.fromstring(xml_octets)
    sortie = []
    for m in racine.iter("{%s}ProbeMatch" % NS["d"]):
        xaddrs = (m.findtext("d:XAddrs", "", NS) or "").split()
        scopes = (m.findtext("d:Scopes", "", NS) or "").split()
        nom = modele = ""
        for s in scopes:
            if "/name/" in s:
                nom = urllib.request.unquote(s.rsplit("/name/", 1)[1])
            elif "/hardware/" in s:
                modele = urllib.request.unquote(s.rsplit("/hardware/", 1)[1])
        if not xaddrs:
            continue
        # Préférer l'adresse IPv4 qui correspond à l'émetteur
        xaddr = next((x for x in xaddrs if ip and ip in x), xaddrs[0])
        sortie.append({"ip": ip or urlparse(xaddr).hostname, "xaddr": xaddr, "nom": nom or "Caméra ONVIF",
                       "modele": modele})
    return sortie


def adresses_locales():
    """Adresses IPv4 de la machine (toutes les cartes réseau), celle de la route par défaut en premier."""
    ips = []
    try:  # carte utilisée pour sortir vers Internet (aucun paquet n'est envoyé)
        t = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        t.connect(("8.8.8.8", 80))
        ips.append(t.getsockname()[0])
        t.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.append(info[4][0])
    except OSError:
        pass
    vus, sortie = set(), []
    for ip in ips:
        if ip not in vus and not ip.startswith(("127.", "169.254.", "0.")):
            vus.add(ip)
            sortie.append(ip)
    return sortie


def _privee(ip):
    a, b = (int(x) for x in ip.split(".")[:2])
    return a == 10 or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168)


def decouvrir(delai=3.0, cible=MULTICAST, balayage=True):
    """Recherche WS-Discovery sur chaque carte réseau (multicast puis diffusion), puis, si rien ne répond,
    sonde directement chaque adresse du réseau local. Une carte en erreur (VPN, carte virtuelle, Wi-Fi sans
    multicast : WinError 10065 « hôte inaccessible ») est ignorée au lieu d'arrêter la recherche."""
    import select
    trouvees, prises, erreurs = {}, [], []
    sonde = _sonde()
    locales = adresses_locales()

    def ouvrir(ip_locale):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 4)
        if ip_locale:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip_locale))
        s.bind((ip_locale or "", 0))
        s.settimeout(0.02)  # envoi bloquant très court : un balayage rapide ne sature pas la mémoire d'envoi
        return s

    for ip in locales or [""]:
        try:
            prises.append((ip, ouvrir(ip)))
        except OSError as e:
            erreurs.append(f"{ip or 'carte par défaut'} : {e}")
    if not prises:
        try:
            prises.append(("", ouvrir("")))
        except OSError as e:
            erreurs.append(str(e))

    def envoyer(destination):
        reussis = 0
        for ip, s in prises:
            try:
                s.sendto(sonde, destination)
                reussis += 1
            except OSError as e:  # WinError 10065, 10051… : cette carte ne mène pas là, on passe à la suivante
                if len(erreurs) < 20:
                    erreurs.append(f"{ip or 'carte par défaut'} → {destination[0]} : {e}")
        return reussis

    def recevoir(jusqua):
        while time.time() < jusqua:
            pretes, _, _ = select.select([s for _, s in prises], [], [], max(0.0, min(0.25, jusqua - time.time())))
            for s in pretes:
                try:
                    donnees, (ip, _) = s.recvfrom(65535)
                except OSError:
                    continue
                try:
                    for c in analyser_reponse_decouverte(donnees, ip):
                        trouvees[c["xaddr"]] = c
                except ET.ParseError:
                    pass

    try:
        envoyes = 0
        fin = time.time() + delai
        for _ in range(3):  # UDP : sonde répétée, certaines caméras ratent la première
            envoyes += envoyer(cible)
            if cible == MULTICAST:
                envoyes += envoyer(("255.255.255.255", PORT_DECOUVERTE))
            recevoir(min(fin, time.time() + 0.4))
        recevoir(fin if trouvees else min(fin, time.time() + 0.8))
        if not trouvees and balayage and cible == MULTICAST:
            # Repli : sonde directe (unicast) de chaque adresse des réseaux locaux en /24
            reseaux = sorted({ip.rsplit(".", 1)[0] for ip in locales if _privee(ip)})
            limite = time.time() + 5.0  # balayage plafonné à 5 s
            for reseau in reseaux[:4]:
                for n in range(1, 255):
                    if time.time() > limite:
                        break
                    envoyes += envoyer((f"{reseau}.{n}", PORT_DECOUVERTE))
                    if n % 32 == 0:
                        recevoir(time.time() + 0.03)  # petites pauses : réponses lues au fil de l'eau
            recevoir(time.time() + max(1.5, delai / 2))
    finally:
        for _, s in prises:
            s.close()
    if not trouvees and envoyes == 0:
        raise ErreurOnvif("aucune carte réseau ne permet d'envoyer la recherche "
                          f"({erreurs[0] if erreurs else 'réseau indisponible'}). Désactivez un éventuel VPN, "
                          "vérifiez que le PC est sur le même réseau que les caméras, ou saisissez l'adresse IP "
                          "de la caméra à la main.")
    return sorted(trouvees.values(), key=lambda c: tuple(int(x) for x in c["ip"].split(".")) if
                  c["ip"].count(".") == 3 and c["ip"].replace(".", "").isdigit() else (999, c["ip"]))


# ---------------------------------------------------------------------------
# Client SOAP minimal
# ---------------------------------------------------------------------------
def adresse_service(texte):
    """Accepte « 192.168.1.20 », « 192.168.1.20:8080 » ou une URL complète du service."""
    t = texte.strip()
    if t.startswith(("http://", "https://")):
        return t if urlparse(t).path not in ("", "/") else t.rstrip("/") + "/onvif/device_service"
    return f"http://{t}/onvif/device_service"


class ClientOnvif:
    def __init__(self, xaddr, utilisateur="", mot_de_passe="", delai=8.0):
        self.xaddr = adresse_service(xaddr)
        self.utilisateur = utilisateur
        self.mot_de_passe = mot_de_passe
        self.delai = delai
        self.decalage = 0.0  # horloge caméra - horloge locale (sinon le jeton est refusé)
        self.media = None

    # --- transport ------------------------------------------------------------------
    def _securite(self):
        if not self.utilisateur:
            return ""
        nonce = os.urandom(16)
        cree = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=self.decalage)).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z")
        digest = base64.b64encode(hashlib.sha1(nonce + cree.encode() + self.mot_de_passe.encode()).digest()).decode()
        return f"""<s:Header><Security s:mustUnderstand="1" xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">
<UsernameToken><Username>{_echapper(self.utilisateur)}</Username>
<Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">{digest}</Password>
<Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">{base64.b64encode(nonce).decode()}</Nonce>
<Created xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">{cree}</Created>
</UsernameToken></Security></s:Header>"""

    def _appel(self, url, corps, authentifie=True):
        enveloppe = (f'<?xml version="1.0" encoding="UTF-8"?><s:Envelope xmlns:s="{NS["s"]}" '
                     f'xmlns:tds="{NS["tds"]}" xmlns:trt="{NS["trt"]}" xmlns:tt="{NS["tt"]}">'
                     f'{self._securite() if authentifie else ""}<s:Body>{corps}</s:Body></s:Envelope>').encode()
        req = urllib.request.Request(url, data=enveloppe, headers={
            "Content-Type": "application/soap+xml; charset=utf-8"})
        try:
            with urllib.request.urlopen(req, timeout=self.delai) as r:
                return ET.fromstring(r.read())
        except urllib.error.HTTPError as e:
            texte = e.read().decode("utf-8", "replace")
            if e.code in (400, 401, 500) and ("NotAuthorized" in texte or "Sender" in texte or e.code == 401):
                raise ErreurOnvif("Identifiant ou mot de passe refusé par la caméra.") from e
            raise ErreurOnvif(f"La caméra a répondu une erreur HTTP {e.code}.") from e
        except (urllib.error.URLError, socket.timeout, ConnectionError) as e:
            raise ErreurOnvif(f"Caméra injoignable à {url} ({getattr(e, 'reason', e)}).") from e
        except ET.ParseError as e:
            raise ErreurOnvif("Réponse illisible : ce n'est probablement pas un service ONVIF.") from e

    # --- opérations -----------------------------------------------------------------------
    def synchroniser_horloge(self):
        try:
            r = self._appel(self.xaddr, "<tds:GetSystemDateAndTime/>", authentifie=False)
            u = r.find(".//tt:UTCDateTime", NS)
            if u is not None:
                d, h = u.find("tt:Date", NS), u.find("tt:Time", NS)
                cam = dt.datetime(int(d.findtext("tt:Year", "", NS)), int(d.findtext("tt:Month", "", NS)),
                                  int(d.findtext("tt:Day", "", NS)), int(h.findtext("tt:Hour", "", NS)),
                                  int(h.findtext("tt:Minute", "", NS)), int(h.findtext("tt:Second", "", NS)),
                                  tzinfo=dt.timezone.utc)
                self.decalage = (cam - dt.datetime.now(dt.timezone.utc)).total_seconds()
        except (ErreurOnvif, ValueError, TypeError, AttributeError):
            self.decalage = 0.0

    def informations(self):
        r = self._appel(self.xaddr, "<tds:GetDeviceInformation/>")
        i = r.find(".//tds:GetDeviceInformationResponse", NS)
        if i is None:
            return {}
        return {k: i.findtext(f"tds:{k}", "", NS) for k in ("Manufacturer", "Model", "FirmwareVersion", "SerialNumber")}

    def service_media(self):
        if self.media:
            return self.media
        r = self._appel(self.xaddr, "<tds:GetCapabilities><tds:Category>Media</tds:Category></tds:GetCapabilities>")
        x = r.findtext(".//tt:Media/tt:XAddr", "", NS)
        if not x:
            raise ErreurOnvif("La caméra ne propose pas de service vidéo ONVIF (Media).")
        # Certaines caméras renvoient une adresse interne : on garde l'hôte qui a répondu
        u, d = urlparse(x), urlparse(self.xaddr)
        self.media = urlunparse(u._replace(netloc=d.netloc)) if u.hostname != d.hostname else x
        return self.media

    def profils(self):
        r = self._appel(self.service_media(), "<trt:GetProfiles/>")
        sortie = []
        for p in r.iter("{%s}Profiles" % NS["trt"]):
            v = p.find("tt:VideoEncoderConfiguration", NS)
            larg = haut = 0
            enc = ""
            if v is not None:
                enc = v.findtext("tt:Encoding", "", NS)
                larg = int(v.findtext("tt:Resolution/tt:Width", "0", NS) or 0)
                haut = int(v.findtext("tt:Resolution/tt:Height", "0", NS) or 0)
            sortie.append({"jeton": p.get("token"), "nom": p.findtext("tt:Name", "", NS) or p.get("token"),
                           "encodage": enc, "largeur": larg, "hauteur": haut})
        if not sortie:
            raise ErreurOnvif("Aucun profil vidéo trouvé sur la caméra.")
        return sortie

    def adresse_flux(self, jeton, avec_identifiants=True):
        corps = (f"<trt:GetStreamUri><trt:StreamSetup><tt:Stream>RTP-Unicast</tt:Stream><tt:Transport>"
                 f"<tt:Protocol>RTSP</tt:Protocol></tt:Transport></trt:StreamSetup>"
                 f"<trt:ProfileToken>{_echapper(jeton)}</trt:ProfileToken></trt:GetStreamUri>")
        r = self._appel(self.service_media(), corps)
        uri = r.findtext(".//tt:Uri", "", NS).strip()
        if not uri:
            raise ErreurOnvif("La caméra n'a pas donné d'adresse de flux.")
        if avec_identifiants and self.utilisateur:
            u = urlparse(uri)
            hote = u.hostname + (f":{u.port}" if u.port else "")
            uri = urlunparse(u._replace(netloc=f"{quote(self.utilisateur, safe='')}:{quote(self.mot_de_passe, safe='')}@{hote}"))
        return uri

    def connecter(self):
        """Enchaîne horloge, capacités et profils. Retourne la liste des profils."""
        self.synchroniser_horloge()
        return self.profils()


def choisir_profil(profils, preference="principal"):
    tries = sorted(profils, key=lambda p: -(p["largeur"] * p["hauteur"]))
    return tries[-1] if preference == "secondaire" and len(tries) > 1 else tries[0]


def _echapper(t):
    return re.sub(r"[<>&'\"]", lambda m: {"<": "&lt;", ">": "&gt;", "&": "&amp;", "'": "&apos;", '"': "&quot;"}[m.group()],
                  str(t))
