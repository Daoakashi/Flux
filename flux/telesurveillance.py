"""Télésurveillance : transmission du journal de Flux aux centrales de télésurveillance tierces.

Protocole d'alarme : SIA DC-09 (transmission d'alarmes sur IP), au format SIA (SIA-DCS) ou Contact ID (ADM-CID),
par TCP (défaut) ou UDP, avec chiffrement AES optionnel (clé fournie par la centrale), accusé de réception,
récepteur de secours, supervision (NULL) et test périodique.
Images et vidéos : déposées sur le serveur de la centrale (FTP, FTPS, SFTP, HTTP ou HTTPS) ; le message d'alarme
porte le nom du fichier (donnée étendue « V », vérification) pour que l'opérateur ouvre la bonne image.

Rien n'est perdu : un message non accusé reste dans une file d'attente sur le disque et repart dès que la
centrale répond. Les mots de passe et clés sont enregistrés chiffrés (coffre de Flux).
"""
import collections
import copy
import ftplib
import io
import json
import os
import random
import re
import secrets
import socket
import ssl
import string
import threading
import time
import unicodedata
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

from . import coffre
from .config import RACINE

DOSSIER = os.path.join(RACINE, "fluxlite", "telesurveillance")
FICHIER_CONFIG = os.path.join(DOSSIER, "configuration.json")
FICHIER_FILE = os.path.join(DOSSIER, "file_attente.json")
DOSSIER_SPOOL = os.path.join(DOSSIER, "en_attente")

# (clé, libellé, code SIA, code Contact ID, actif, image, vidéo)
TYPES = [
    ("alerte", "Alerte : personne détectée", "BA", "130", True, True, True),
    ("liste_noire", "Liste noire (personne ou plaque)", "BV", "139", True, True, True),
    ("ivs", "IVS : franchissement d'une flèche", "BA", "134", True, True, True),
    ("zone", "Entrée dans une zone", "BA", "132", False, True, False),
    ("stationnement", "Stationnement prolongé", "UA", "150", False, True, False),
    ("plaque", "Plaque lue", "UA", "150", False, True, False),
    ("identification", "Personne reconnue", "UA", "150", False, False, False),
    ("apparition", "Personne apparue", "UA", "150", False, False, False),
    ("depart", "Personne partie", "UA", "150", False, False, False),
]
LIBELLES = {t[0]: t[1] for t in TYPES}
CODE_TEST_MANUEL = ("RX", "601")
CODE_TEST_AUTO = ("RP", "602")
MAX_FILE = 5000
LIEN_VIDEO = 300            # une vidéo est rattachée à l'alarme envoyée pour la même caméra dans les 5 min
METHODES_FICHIERS = [("aucune", "Ne pas envoyer de fichier"), ("ftps", "FTPS (FTP chiffré)"), ("sftp", "SFTP (SSH)"),
                     ("https", "HTTPS (envoi direct)"), ("ftp", "FTP (non chiffré)"), ("http", "HTTP (non chiffré)")]


class ErreurTransmission(Exception):
    pass


# ---------------------------------------------------------------------------------------------
# Trames SIA DC-09
# ---------------------------------------------------------------------------------------------
def crc16(texte):
    """CRC-16 (ARC, polynôme 0x8005 réfléchi) exigé par DC-09, en 4 chiffres hexadécimaux."""
    crc = 0
    for o in texte.encode("ascii"):
        crc ^= o
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return f"{crc:04X}"


def ascii_propre(texte, maxi=200):
    """DC-09 n'accepte que l'ASCII imprimable, sans [ ] | (accents retirés : « Entrée » -> « Entree »)."""
    t = unicodedata.normalize("NFKD", str(texte or "")).encode("ascii", "ignore").decode()
    t = re.sub(r"[\[\]|\r\n\t]", " ", t)
    t = "".join(c for c in t if 32 <= ord(c) < 127)
    return re.sub(r"\s+", " ", t).strip()[:maxi]


def horodatage(decalage=0.0):
    return (datetime.now(timezone.utc) + timedelta(seconds=decalage)).strftime("_%H:%M:%S,%m-%d-%Y")


def compte_valide(compte):
    c = (compte or "").strip().upper()
    if not re.fullmatch(r"[0-9A-F]{3,16}", c):
        raise ErreurTransmission("Numéro de client : 3 à 16 caractères, chiffres 0-9 et lettres A-F seulement "
                                 "(format exigé par les protocoles SIA et Contact ID).")
    return c


def cle_aes(cle, format_cle="hex"):
    """Clé AES de la centrale. Deux façons de l'écrire existent selon les fabricants :
    - « hex » : 32, 48 ou 64 chiffres hexadécimaux -> 16, 24 ou 32 octets (AES-128, 192, 256) ;
    - « texte » : 16, 24 ou 32 caractères pris tels quels (courant sur les centrales et récepteurs du marché)."""
    if not cle:
        return None
    c = cle.strip().replace(" ", "")
    if format_cle == "texte":
        if len(c) not in (16, 24, 32) or not c.isascii():
            raise ErreurTransmission("Clé AES (format texte) : 16, 24 ou 32 caractères.")
        return c.encode("ascii")
    if not re.fullmatch(r"[0-9A-Fa-f]{32}|[0-9A-Fa-f]{48}|[0-9A-Fa-f]{64}", c):
        raise ErreurTransmission("Clé AES (format hexadécimal) : 32, 48 ou 64 caractères 0-9 et A-F "
                                 "(ou choisissez le format « texte » si la centrale donne 16, 24 ou 32 caractères).")
    return bytes.fromhex(c)


def _aes(cle):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    return Cipher(algorithms.AES(cle), modes.CBC(bytes(16)))  # IV nul : la norme impose un bourrage aléatoire


def chiffrer_bloc(cle, contenu):
    """Bloc chiffré DC-09 : bourrage aléatoire + « | » + contenu, multiple de 16 octets, en hexadécimal."""
    n = (16 - (len(contenu) + 1) % 16) % 16
    bourrage = "".join(random.SystemRandom().choice(string.ascii_letters + string.digits) for _ in range(n))
    clair = (bourrage + "|" + contenu).encode("ascii")
    e = _aes(cle).encryptor()
    return (e.update(clair) + e.finalize()).hex().upper()


def dechiffrer_bloc(cle, hexa):
    d = _aes(cle).decryptor()
    return (d.update(bytes.fromhex(hexa)) + d.finalize()).decode("ascii", "replace")


def donnees_evenement(protocole, compte, code_sia, code_cid, zone, zone_partition=1, retour=False):
    if protocole == "ADM-CID":
        qualif = "3" if retour else "1"
        return f"#{compte}|{qualif}{int(code_cid):03d} {int(zone_partition):02d} {int(zone):03d}"
    return f"#{compte}|Nri{int(zone_partition)}/{code_sia.upper()}{int(zone):03d}"


def trame(type_msg, seq, compte, ligne="0", recepteur="", donnees="", xdata=None, cle=None, avec_horodatage=True,
          decalage=0.0):
    """Trame complète <LF><crc><0LLL>"type"seq[R..]L..#compte[...]<CR>."""
    ts = horodatage(decalage) if (avec_horodatage or cle) else ""
    x = "".join(f"[{k}{ascii_propre(v, 250)}]" for k, v in (xdata or []) if v)
    entete = f'"{"*" if cle else ""}{type_msg}"{seq:04d}{"R" + recepteur if recepteur else ""}L{ligne or "0"}#{compte}['
    if cle:
        corps = entete + chiffrer_bloc(cle, f"{donnees}]{x}{ts}")
    else:
        corps = f"{entete}{donnees}]{x}{ts}"
    return f"\n{crc16(corps)}{len(corps):04X}{corps}\r".encode("ascii")


def analyser_reponse(brut, cle=None):
    """Réponse de la centrale -> (type, séquence, horodatage UTC ou None). Lève ErreurTransmission si illisible."""
    t = brut.decode("ascii", "replace").strip("\r\n\x00 ")
    m = re.match(r'^([0-9A-Fa-f]{4})([0-9A-Fa-f]{4})(".*)$', t, re.S)
    if not m:
        raise ErreurTransmission(f"réponse illisible ({t[:40]!r})")
    corps = m.group(3)
    if crc16(corps) != m.group(1).upper():
        raise ErreurTransmission("réponse altérée (CRC incorrect)")
    m2 = re.match(r'^"(\*?)(ACK|NAK|DUH|RSP)"(\d{4})', corps)
    if not m2:
        raise ErreurTransmission(f"réponse inconnue ({corps[:30]!r})")
    chiffre, typ, seq = m2.group(1), m2.group(2), int(m2.group(3))
    ts = None
    reste = corps[corps.find("[") + 1:] if "[" in corps else ""
    if chiffre:
        if not cle:
            raise ErreurTransmission("réponse chiffrée alors qu'aucune clé n'est réglée")
        try:
            reste = dechiffrer_bloc(cle, reste)
        except ValueError:
            # un accusé de réception qu'on ne sait pas déchiffrer peut être un faux : refusé
            raise ErreurTransmission("accusé de réception non authentique (mauvaise clé ?)") from None
        if "]" not in reste or "_" not in reste:
            raise ErreurTransmission("accusé de réception non authentique (mauvaise clé ?)")
    elif cle and typ == "ACK":
        raise ErreurTransmission("accusé de réception non chiffré refusé (la centrale doit répondre chiffré)")
    mts = re.search(r"_(\d{2}:\d{2}:\d{2}),(\d{2})-(\d{2})-(\d{4})", reste)
    if mts:
        try:
            ts = datetime.strptime(f"{mts.group(1)} {mts.group(2)}-{mts.group(3)}-{mts.group(4)}",
                                   "%H:%M:%S %m-%d-%Y").replace(tzinfo=timezone.utc)
        except ValueError:
            ts = None
    return typ, seq, ts


# ---------------------------------------------------------------------------------------------
# Envoi des fichiers (images et vidéos)
# ---------------------------------------------------------------------------------------------
def nom_fichier(modele, valeurs, extension):
    nom = modele or "{compte}_{date}_{heure}_{camera}_{code}"
    try:
        nom = nom.format(**valeurs)
    except (KeyError, IndexError, ValueError):
        nom = "{compte}_{date}_{heure}_{camera}_{code}".format(**valeurs)
    nom = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_propre(nom, 150)).strip("._") or "flux"
    return f"{nom}.{extension}"


def _contexte_tls(verifier):
    ctx = ssl.create_default_context()
    if not verifier:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _ftp_dossier(ftp, dossier):
    for partie in [p for p in (dossier or "").replace("\\", "/").split("/") if p]:
        try:
            ftp.cwd(partie)
        except ftplib.error_perm:
            ftp.mkd(partie)
            ftp.cwd(partie)


def deposer_fichier(f, nom, contenu, valeurs, delai=30, empreinte_sftp=None):
    """Dépose un fichier chez la centrale. Renvoie l'empreinte SFTP vue (pour l'épingler au premier contact)."""
    methode = f.get("methode", "aucune")
    hote = (f.get("hote") or "").strip()
    utilisateur = f.get("utilisateur") or ""
    mdp = coffre.dechiffrer(f.get("mdp") or "", "telesurveillance")
    dossier = f.get("dossier") or ""
    if methode in ("ftp", "ftps"):
        port = int(f.get("port") or 21)
        ftp = ftplib.FTP_TLS(context=_contexte_tls(f.get("verifier", True)), timeout=delai) if methode == "ftps" \
            else ftplib.FTP(timeout=delai)
        try:
            ftp.connect(hote, port)
            if methode == "ftps":
                ftp.auth()
            ftp.login(utilisateur or "anonymous", mdp)
            if methode == "ftps":
                ftp.prot_p()  # données chiffrées aussi, pas seulement le mot de passe
            ftp.set_pasv(bool(f.get("passif", True)))
            _ftp_dossier(ftp, dossier)
            ftp.storbinary(f"STOR {nom}", io.BytesIO(contenu))
        finally:
            try:
                ftp.quit()
            except (OSError, EOFError, ftplib.Error):
                ftp.close()
        return None
    if methode == "sftp":
        try:
            import paramiko
        except ImportError:
            raise ErreurTransmission("SFTP : module « paramiko » absent (pip install paramiko)") from None
        port = int(f.get("port") or 22)
        sock = socket.create_connection((hote, port), timeout=delai)
        tr = paramiko.Transport(sock)
        try:
            tr.start_client(timeout=delai)
            cle = tr.get_remote_server_key()
            vue = f"{cle.get_name()} {cle.get_base64()}"
            if empreinte_sftp and vue != empreinte_sftp:
                raise ErreurTransmission("SFTP : la clé du serveur a changé depuis le premier contact (possible "
                                         "usurpation). Vérifiez avec la centrale puis « Oublier la clé SFTP ».")
            tr.auth_password(utilisateur, mdp)
            sftp = paramiko.SFTPClient.from_transport(tr)
            chemin = ""
            for partie in [p for p in dossier.replace("\\", "/").split("/") if p]:
                chemin = f"{chemin}/{partie}" if chemin else (f"/{partie}" if dossier.startswith("/") else partie)
                try:
                    sftp.stat(chemin)
                except OSError:
                    sftp.mkdir(chemin)
            sftp.putfo(io.BytesIO(contenu), f"{chemin}/{nom}" if chemin else nom)
            sftp.close()
            return vue
        except paramiko.SSHException as e:
            raise ErreurTransmission(f"SFTP : {e}") from None
        finally:
            tr.close()
    if methode in ("http", "https"):
        url = (f.get("url") or "").strip()
        if not url.lower().startswith(methode + "://"):
            raise ErreurTransmission(f"L'adresse d'envoi doit commencer par {methode}://")
        frontiere = "----flux" + secrets.token_hex(12)
        champs = {k: str(v) for k, v in valeurs.items()}
        corps = io.BytesIO()
        for k, v in champs.items():
            corps.write(f"--{frontiere}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
        type_mime = "video/mp4" if nom.endswith(".mp4") else "image/jpeg"
        corps.write(f"--{frontiere}\r\nContent-Disposition: form-data; name=\"fichier\"; filename=\"{nom}\"\r\n"
                    f"Content-Type: {type_mime}\r\n\r\n".encode())
        corps.write(contenu)
        corps.write(f"\r\n--{frontiere}--\r\n".encode())
        req = urllib.request.Request(url, data=corps.getvalue(), method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={frontiere}",
                                              "User-Agent": "Flux"})
        if utilisateur:
            import base64
            req.add_header("Authorization", "Basic " + base64.b64encode(f"{utilisateur}:{mdp}".encode()).decode())
        try:
            ctx = _contexte_tls(f.get("verifier", True)) if methode == "https" else None
            with urllib.request.urlopen(req, timeout=delai, context=ctx) as r:
                r.read(1024)
        except urllib.error.HTTPError as e:
            raise ErreurTransmission(f"{methode.upper()} : le serveur a répondu {e.code}") from None
        except (urllib.error.URLError, OSError) as e:
            raise ErreurTransmission(f"{methode.upper()} : {getattr(e, 'reason', e)}") from None
        return None
    return None


# ---------------------------------------------------------------------------------------------
# Une centrale : file d'attente, envoi, supervision
# ---------------------------------------------------------------------------------------------
class Centrale:
    def __init__(self, gestion, c):
        self.g = gestion
        self.c = c
        self.etat = "attente"   # attente, ok, erreur, inactive
        self.message = ""
        self.dernier_ack = None
        self.dernier_envoi = 0.0
        self.dernier_test = time.time()
        self.decalage = 0.0     # écart d'horloge appris d'un refus (NAK) de la centrale
        self.reveil = threading.Event()
        self.arret = threading.Event()
        self.fil = threading.Thread(target=self._boucle, name=f"telesurveillance-{c['id']}", daemon=True)

    @property
    def id(self):
        return self.c["id"]

    def demarrer(self):
        self.fil.start()

    def arreter(self):
        self.arret.set()
        self.reveil.set()

    # --- réseau --------------------------------------------------------------------------------
    def _echanger(self, hote, port, donnees):
        delai = max(2, int(self.c.get("delai") or 10))
        if self.c.get("transport") == "udp":
            infos = socket.getaddrinfo(hote, port, type=socket.SOCK_DGRAM)
            s = socket.socket(infos[0][0], socket.SOCK_DGRAM)
            try:
                s.settimeout(delai)
                s.sendto(donnees, infos[0][4])
                return s.recvfrom(2048)[0]
            finally:
                s.close()
        with socket.create_connection((hote, port), timeout=delai) as s:
            s.settimeout(delai)
            s.sendall(donnees)
            recu = b""
            fin = time.time() + delai
            while b"\r" not in recu and time.time() < fin and len(recu) < 4096:
                bloc = s.recv(1024)
                if not bloc:
                    break
                recu += bloc
            if not recu:
                raise ErreurTransmission("aucune réponse (pas d'accusé de réception)")
            return recu

    def _destinations(self):
        d = [((self.c.get("hote") or "").strip(), int(self.c.get("port") or 0))]
        if (self.c.get("secours_hote") or "").strip() and int(self.c.get("secours_port") or 0):
            d.append((self.c["secours_hote"].strip(), int(self.c["secours_port"])))
        return [x for x in d if x[0] and x[1]]

    def envoyer_trame(self, type_msg, donnees, xdata=None, seq=None):
        """Envoie une trame et attend l'accusé de réception. Renvoie (séquence, destination)."""
        cle = cle_aes(coffre.dechiffrer(self.c.get("cle_aes") or "", "telesurveillance"), self.c.get("format_cle", "hex"))
        compte = compte_valide(self.c.get("compte"))
        seq = seq or self.g.sequence_suivante(self.id)
        erreurs = []
        dests = self._destinations()
        if not dests:
            raise ErreurTransmission("adresse ou port de la centrale manquant")
        for hote, port in dests:
            for essai in range(2):  # 2e essai seulement après un refus d'horloge (NAK)
                t = trame(type_msg, seq, compte, ligne=self.c.get("ligne") or "0", recepteur=self.c.get("recepteur") or "",
                          donnees=donnees, xdata=xdata if self.c.get("xdata", True) else None, cle=cle,
                          avec_horodatage=self.c.get("horodatage", True), decalage=self.decalage)
                try:
                    typ, seq_r, ts = analyser_reponse(self._echanger(hote, port, t), cle)
                except (OSError, ErreurTransmission) as e:
                    erreurs.append(f"{hote}:{port} : {e}")
                    break
                if typ in ("ACK", "RSP") and seq_r in (seq, 0):
                    return seq, f"{hote}:{port}"
                if typ == "NAK" and ts is not None and essai == 0:
                    self.decalage = (ts - datetime.now(timezone.utc)).total_seconds()  # horloge de la centrale
                    continue
                if typ == "DUH":
                    raise ErreurTransmission(f"{hote}:{port} : message refusé par la centrale (format ou code non "
                                             f"reconnu : vérifiez le protocole et les codes)")
                erreurs.append(f"{hote}:{port} : réponse {typ}")
                break
        raise ErreurTransmission(" ; ".join(erreurs))

    # --- éléments de la file -------------------------------------------------------------------
    def _traiter(self, el):
        """Envoie un élément de la file (alarme puis fichiers). True si terminé."""
        if el["etape"] == "alarme":
            proto = self.c.get("protocole", "SIA-DCS")
            compte = compte_valide(self.c.get("compte"))
            donnees = donnees_evenement(proto, compte, el["sia"], el["cid"], el["zone"], self.c.get("partition", 1))
            fichier = el.get("fichier_image") or el.get("fichier_video")
            if proto == "ADM-CID":
                # beaucoup de récepteurs Contact ID n'acceptent qu'un bloc de données étendues : le plus utile
                xdata = [("V", fichier)] if fichier else [("I", el.get("texte"))]
            else:
                xdata = [("I", el.get("texte")), ("L", el.get("camera")), ("S", self.g.config.get("site")),
                         ("V", fichier)]
            if not el.get("seq"):  # une nouvelle tentative garde le même numéro (exigé par la norme)
                el["seq"] = self.g.sequence_suivante(self.id)
                self.g.sauver_file()
            seq, dest = self.envoyer_trame(proto, donnees, xdata, seq=el["seq"])
            self.g.noter(self, el, "ok", f"accusé par {dest} (séquence {seq:04d})")
            el["etape"] = "fichiers"
            self.g.sauver_file()
        if el["etape"] == "fichiers":
            f = self.c.get("fichiers") or {}
            if f.get("methode", "aucune") != "aucune":
                for cle_f in ("image", "video"):
                    chemin = el.get(f"spool_{cle_f}")
                    if not chemin:
                        continue
                    try:
                        with open(chemin, "rb") as fh:
                            contenu = fh.read()
                    except OSError:
                        el[f"spool_{cle_f}"] = None
                        continue
                    vue = deposer_fichier(f, el[f"fichier_{cle_f}"], contenu, el["valeurs"],
                                          empreinte_sftp=f.get("empreinte_sftp"))
                    if vue and not f.get("empreinte_sftp"):
                        self.g.epingler_sftp(self.id, vue)
                    self.g.noter(self, el, "ok", f"{'image' if cle_f == 'image' else 'vidéo'} déposée : "
                                                 f"{el[f'fichier_{cle_f}']}")
                    el[f"spool_{cle_f}"] = None
                    self.g.liberer(chemin)
                    self.g.sauver_file()
            return True
        return True

    def _boucle(self):
        attente = 0.5
        echecs = 0
        while not self.arret.is_set():
            self.reveil.wait(attente)
            self.reveil.clear()
            if self.arret.is_set():
                break
            if not self.c.get("actif", True) or not self.g.config.get("actif", True):
                self.etat, attente = "inactive", 5
                continue
            el = self.g.prochain(self.id)
            try:
                if el is not None:
                    if self._traiter(el):
                        self.g.retirer(el)
                    self.dernier_envoi = time.time()
                    self.etat, self.message, self.dernier_ack, echecs = "ok", "", time.time(), 0
                    attente = 0.05
                    continue
                maintenant = time.time()
                sup = int(self.c.get("supervision") or 0)
                if sup and maintenant - self.dernier_envoi >= sup:
                    self.envoyer_trame("NULL", "")
                    self.dernier_envoi = maintenant
                    self.etat, self.message, self.dernier_ack, echecs = "ok", "", maintenant, 0
                th = float(self.c.get("test_heures") or 0)
                if th and maintenant - self.dernier_test >= th * 3600:
                    self.dernier_test = maintenant
                    self.g.test(self.id, auto=True)
                attente = 1.0
            except Exception as e:  # noqa: BLE001  — coupure, serveur qui raccroche… : le fil ne doit jamais s'arrêter
                if not isinstance(e, (ErreurTransmission, OSError, ftplib.Error, ValueError)):
                    e = ErreurTransmission(f"{type(e).__name__} : {e}" if str(e) else "connexion interrompue")
                echecs += 1
                self.etat, self.message = "erreur", str(e)
                if el is not None:
                    el["essais"] = el.get("essais", 0) + 1
                    el["erreur"] = str(e)
                    if echecs == 1:
                        self.g.noter(self, el, "erreur", f"{e} (nouvel essai automatique)")
                    self.g.sauver_file()
                attente = min(60, 3 * echecs)


# ---------------------------------------------------------------------------------------------
# Gestion de toutes les centrales
# ---------------------------------------------------------------------------------------------
def centrale_defaut():
    return {"id": uuid.uuid4().hex[:10], "nom": "Centrale", "actif": True, "hote": "", "port": "", "transport": "tcp",
            "protocole": "SIA-DCS", "compte": "", "recepteur": "", "ligne": "0", "partition": 1, "cle_aes": "", "format_cle": "hex",
            "secours_hote": "", "secours_port": "", "xdata": True, "horodatage": True, "supervision": 0,
            "test_heures": 0, "delai": 10, "types": [t[0] for t in TYPES],
            "fichiers": {"methode": "aucune", "hote": "", "port": "", "utilisateur": "", "mdp": "", "dossier": "",
                         "url": "", "modele": "{compte}_{date}_{heure}_{camera}_{code}", "verifier": True,
                         "passif": True, "empreinte_sftp": ""}}


def config_defaut():
    return {"actif": True, "site": "", "centrales": [], "zones": {},
            "evenements": {t[0]: {"actif": t[4], "sia": t[2], "cid": t[3], "image": t[5], "video": t[6]} for t in TYPES}}


def classer(e):
    """Événement du journal de Flux -> type de télésurveillance (ou None)."""
    niveau, ta = e.get("niveau"), e.get("type_action")
    if niveau == "alerte":
        return ta if ta in ("liste_noire", "ivs") else "alerte"
    if niveau == "action" and ta in LIBELLES:
        return ta
    if niveau == "info" and ta == "plaque":
        return "plaque"
    return None


class Telesurveillance:
    def __init__(self, fen=None):
        self.fen = fen
        self.verrou = threading.RLock()
        self.config = self._lire(FICHIER_CONFIG, config_defaut())
        for k, v in config_defaut()["evenements"].items():
            self.config["evenements"].setdefault(k, v)
        self.file = self._lire(FICHIER_FILE, {"elements": [], "sequences": {}})
        self.journal = collections.deque(maxlen=300)
        self.version_journal = 0
        self.centrales = {}
        self._derniers = {}  # caméra -> dernier élément d'alarme (pour y rattacher la vidéo)

    # --- fichiers ------------------------------------------------------------------------------
    @staticmethod
    def _lire(chemin, defaut):
        try:
            with open(chemin, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else defaut
        except (OSError, ValueError):
            return defaut

    @staticmethod
    def _ecrire(chemin, d):
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
        tmp = chemin + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, chemin)

    def sauver_config(self):
        with self.verrou:
            self._ecrire(FICHIER_CONFIG, self.config)

    def sauver_file(self):
        with self.verrou:
            self._ecrire(FICHIER_FILE, self.file)

    # --- cycle de vie --------------------------------------------------------------------------
    def demarrer(self):
        with self.verrou:
            for c in self.config["centrales"]:
                if c["id"] not in self.centrales:
                    ce = Centrale(self, c)
                    self.centrales[c["id"]] = ce
                    ce.demarrer()

    def arreter(self):
        for ce in self.centrales.values():
            ce.arreter()

    def enregistrer_centrale(self, c):
        """Ajoute ou met à jour une centrale (secrets déjà chiffrés par l'appelant)."""
        compte_valide(c.get("compte"))
        cle_aes(coffre.dechiffrer(c.get("cle_aes") or "", "telesurveillance"), c.get("format_cle", "hex"))
        with self.verrou:
            liste = self.config["centrales"]
            for i, x in enumerate(liste):
                if x["id"] == c["id"]:
                    liste[i] = c
                    break
            else:
                liste.append(c)
            self.sauver_config()
            ce = self.centrales.get(c["id"])
            if ce is not None:
                ce.c = c
                ce.reveil.set()
            else:
                ce = Centrale(self, c)
                self.centrales[c["id"]] = ce
                ce.demarrer()

    def supprimer_centrale(self, ident):
        with self.verrou:
            self.config["centrales"] = [c for c in self.config["centrales"] if c["id"] != ident]
            ce = self.centrales.pop(ident, None)
            if ce:
                ce.arreter()
            for el in [e for e in self.file["elements"] if e["centrale"] == ident]:
                self.retirer(el)
            self.sauver_config()

    def epingler_sftp(self, ident, empreinte):
        with self.verrou:
            for c in self.config["centrales"]:
                if c["id"] == ident:
                    c.setdefault("fichiers", {})["empreinte_sftp"] = empreinte
            self.sauver_config()

    def sequence_suivante(self, ident):
        with self.verrou:
            n = int(self.file["sequences"].get(ident, 0)) % 9999 + 1
            self.file["sequences"][ident] = n
            self.sauver_file()
            return n

    # --- file d'attente --------------------------------------------------------------------------
    def prochain(self, ident):
        with self.verrou:
            for el in self.file["elements"]:
                if el["centrale"] == ident:
                    return el
        return None

    def retirer(self, el):
        with self.verrou:
            try:
                self.file["elements"].remove(el)
            except ValueError:
                pass
            for k in ("spool_image", "spool_video"):
                self.liberer(el.get(k))
            self.sauver_file()

    def liberer(self, chemin):
        """Efface un fichier temporaire dès qu'aucun envoi en attente ne l'utilise plus."""
        with self.verrou:
            if chemin and not any(chemin in (x.get("spool_image"), x.get("spool_video")) for x in self.file["elements"]):
                try:
                    os.remove(chemin)
                except OSError:
                    pass

    def en_attente(self, ident=None):
        with self.verrou:
            return sum(1 for e in self.file["elements"] if ident is None or e["centrale"] == ident)

    def noter(self, centrale, el, etat, detail):
        nom = centrale.c.get("nom") if centrale else ""
        quoi = LIBELLES.get(el.get("type"), el.get("type", "")) if el else ""
        with self.verrou:
            self.journal.appendleft({"heure": time.strftime("%H:%M:%S"), "centrale": nom, "evenement": quoi,
                                     "camera": (el or {}).get("camera", ""), "etat": etat, "detail": detail})
            self.version_journal += 1

    def zone(self, camera):
        z = self.config.get("zones", {}).get(camera)
        if z:
            return int(z)
        cams = [p.nom for p in self.fen.page_cameras.pages] if self.fen is not None else []
        return cams.index(camera) + 1 if camera in cams else 1

    def _spool(self, contenu, extension):
        os.makedirs(DOSSIER_SPOOL, exist_ok=True)
        chemin = os.path.join(DOSSIER_SPOOL, f"{uuid.uuid4().hex}.{extension}")
        fd = os.open(chemin, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(contenu)
        return chemin

    # --- arrivée des événements (fil de l'interface) -------------------------------------------
    def evenement(self, e):
        if not self.config.get("actif", True) or not self.config["centrales"]:
            return
        if e.get("niveau") == "video" and e.get("video"):
            return self._video(e)
        typ = classer(e)
        if typ is None:
            return
        reglage = self.config["evenements"].get(typ) or {}
        if not reglage.get("actif"):
            return
        camera = str(e.get("source") or "")
        maintenant = datetime.now()
        spool_image = None
        if reglage.get("image") and e.get("jpeg"):
            try:
                spool_image = self._spool(e["jpeg"], "jpg")
            except OSError:
                spool_image = None
        ajoutes = []
        with self.verrou:
            for c in self.config["centrales"]:
                if not c.get("actif", True) or typ not in c.get("types", [t[0] for t in TYPES]):
                    continue
                code = reglage.get("sia") if c.get("protocole") != "ADM-CID" else reglage.get("cid")
                valeurs = {"compte": (c.get("compte") or "").upper(), "date": maintenant.strftime("%Y%m%d"),
                           "heure": maintenant.strftime("%H%M%S"), "camera": ascii_propre(camera, 40) or "camera",
                           "code": code, "type": typ, "zone": f"{self.zone(camera):03d}"}
                avec_fichiers = (c.get("fichiers") or {}).get("methode", "aucune") != "aucune"
                el = {"id": uuid.uuid4().hex, "centrale": c["id"], "type": typ, "etape": "alarme", "essais": 0,
                      "cree": time.time(), "sia": reglage.get("sia") or "UA", "cid": reglage.get("cid") or "150",
                      "zone": self.zone(camera), "camera": camera, "texte": e.get("texte", ""), "valeurs": valeurs,
                      "fichier_image": nom_fichier((c.get("fichiers") or {}).get("modele"), valeurs, "jpg")
                      if spool_image and avec_fichiers else None,
                      "spool_image": spool_image if avec_fichiers else None,
                      "fichier_video": None, "spool_video": None, "video_attendue": bool(reglage.get("video")) and avec_fichiers}
                self.file["elements"].append(el)
                ajoutes.append(el)
            if len(self.file["elements"]) > MAX_FILE:  # centrale injoignable depuis très longtemps
                for el in self.file["elements"][:len(self.file["elements"]) - MAX_FILE]:
                    self.retirer(el)
            if ajoutes:
                self._derniers[camera] = (time.time(), ajoutes)
            self.sauver_file()
        if spool_image and not any(el.get("spool_image") for el in ajoutes):
            try:
                os.remove(spool_image)
            except OSError:
                pass
        for el in ajoutes:
            ce = self.centrales.get(el["centrale"])
            if ce:
                ce.reveil.set()

    def _video(self, e):
        camera = str(e.get("source") or "")
        info = e.get("video") or {}
        t, els = self._derniers.get(camera, (0, []))
        if time.time() - t > LIEN_VIDEO or not info.get("chemin"):
            return
        cibles = [el for el in els if el.get("video_attendue")]
        if not cibles:
            return
        try:
            with open(info["chemin"], "rb") as f:
                spool = self._spool(f.read(), "mp4")
        except OSError:
            return
        with self.verrou:
            for el in cibles:
                c = next((x for x in self.config["centrales"] if x["id"] == el["centrale"]), None)
                if c is None:
                    continue
                v = dict(el["valeurs"])
                nouvel = {**copy.deepcopy(el), "id": uuid.uuid4().hex, "etape": "fichiers", "spool_image": None,
                          "fichier_image": None, "spool_video": spool, "essais": 0,
                          "fichier_video": nom_fichier((c.get("fichiers") or {}).get("modele"), v, "mp4")}
                self.file["elements"].append(nouvel)
                el["video_attendue"] = False
                ce = self.centrales.get(el["centrale"])
                if ce:
                    ce.reveil.set()
            self.sauver_file()

    # --- test ------------------------------------------------------------------------------------
    def test(self, ident, auto=False):
        """Message de test (RX/601 manuel, RP/602 automatique) envoyé tout de suite ; renvoie le compte rendu."""
        ce = self.centrales.get(ident)
        if ce is None:
            raise ErreurTransmission("centrale inconnue")
        sia, cid = CODE_TEST_AUTO if auto else CODE_TEST_MANUEL
        proto = ce.c.get("protocole", "SIA-DCS")
        compte = compte_valide(ce.c.get("compte"))
        el = {"type": "test", "camera": ""}
        try:
            xdata = [("I", "Test de transmission Flux")] + ([] if proto == "ADM-CID" else [("S", self.config.get("site"))])
            seq, dest = ce.envoyer_trame(proto, donnees_evenement(proto, compte, sia, cid, 0, ce.c.get("partition", 1)), xdata)
        except ErreurTransmission as e:
            self.noter(ce, el, "erreur", f"test {'automatique' if auto else 'manuel'} : {e}")
            raise
        ce.dernier_ack, ce.etat, ce.message = time.time(), "ok", ""
        compte_rendu = f"Alarme de test accusée par {dest} (séquence {seq:04d})."
        f = ce.c.get("fichiers") or {}
        if not auto and f.get("methode", "aucune") != "aucune":
            valeurs = {"compte": compte, "date": time.strftime("%Y%m%d"), "heure": time.strftime("%H%M%S"),
                       "camera": "test", "code": sia if proto != "ADM-CID" else cid, "type": "test", "zone": "000"}
            nom = nom_fichier(f.get("modele"), valeurs, "jpg")
            try:
                vue = deposer_fichier(f, nom, _image_test(), valeurs, empreinte_sftp=f.get("empreinte_sftp"))
                if vue and not f.get("empreinte_sftp"):
                    self.epingler_sftp(ident, vue)
                compte_rendu += f" Image de test déposée : {nom}."
            except Exception as e:  # noqa: BLE001
                e = e if str(e) else ErreurTransmission("connexion interrompue")
                self.noter(ce, el, "erreur", f"test : alarme OK, fichier refusé : {e}")
                raise ErreurTransmission(f"{compte_rendu} Mais l'envoi du fichier a échoué : {e}") from None
        self.noter(ce, el, "ok", compte_rendu)
        return compte_rendu


def _image_test():
    try:
        import cv2
        import numpy as np
        img = np.full((240, 427, 3), (60, 40, 20), np.uint8)
        cv2.putText(img, "FLUX - TEST", (60, 110), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 200, 80), 2)
        cv2.putText(img, time.strftime("%d/%m/%Y %H:%M:%S"), (80, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (230, 230, 230), 1)
        ok, buf = cv2.imencode(".jpg", img)
        if ok:
            return buf.tobytes()
    except ImportError:
        pass
    return b"\xff\xd8\xff\xd9"
