"""Serveur FluxLite : relie l'application Android FluxLite à ce PC.

Chaque PC qui fait tourner Flux sert aussi de petit serveur privé pour les comptes de ses clients :

    Entreprise A ── Client 1A, Client 2A
    Entreprise B ── Client 1B, Client 2B

Une entreprise voit seulement les caméras que vous lui attribuez (page FluxLite de Flux).

Sécurité
--------
* Tout passe en HTTPS (TLS 1.2 minimum). Le certificat est créé une seule fois, au premier démarrage, avec une clé
  privée qui ne quitte jamais ce PC.
* La « clé du serveur » affichée dans Flux est l'empreinte de cette clé publique. Le téléphone la demande une fois
  et refuse ensuite tout serveur qui ne présente pas exactement la même clé : impossible d'intercepter ou de
  détourner la connexion, même sur un Wi-Fi public, même avec un faux certificat.
* La clé est rangée dans le dossier « fluxlite » à côté de Flux, que les mises à jour ne touchent jamais : elle ne
  change pas d'une version à l'autre.
* Mots de passe : jamais stockés, seulement leur empreinte scrypt salée. Jetons de session : 256 bits, stockés
  sous forme d'empreinte, révocables, expirés automatiquement.
* Trop d'essais de connexion ratés : l'adresse et le compte sont bloqués 15 minutes.

Ce module n'utilise pas Qt : il tourne dans ses propres fils et lit les caméras par un « fournisseur » (voir
FournisseurVide) que l'interface met à jour.
"""

import base64
import hashlib
import hmac
import json
import os
import queue
import re
import secrets
import socket
import sqlite3
import ssl
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION_API = 1
VERSION_CGU = "2026-10"   # à changer quand les conditions d'utilisation de l'application changent
PORT_DEFAUT = 47810
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # base32 de Crockford : pas de I, L, O, U (aucune confusion)
TAILLE_CORPS_MAX = 64 * 1024
ESSAIS_MAX = 5
BLOCAGE = 15 * 60
NIVEAUX_JOURNAL = ("alerte", "action", "video")
RE_MAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,24}$")


class ErreurServeur(Exception):
    pass


# ---------------------------------------------------------------------------
# Outils
# ---------------------------------------------------------------------------
def base32_crockford(octets):
    bits, n, sortie = 0, 0, []
    for o in octets:
        n = (n << 8) | o
        bits += 8
        while bits >= 5:
            bits -= 5
            sortie.append(ALPHABET[(n >> bits) & 31])
    if bits:
        sortie.append(ALPHABET[(n << (5 - bits)) & 31])
    return "".join(sortie)


def normaliser_cle(texte):
    """« fx7k-2m… » -> « FX7K2M… » (tolère espaces, tirets, minuscules, O pour 0, I et L pour 1)."""
    t = re.sub(r"[\s\-_.]", "", str(texte or "")).upper()
    return t.translate(str.maketrans({"O": "0", "I": "1", "L": "1", "U": "V"}))


def formater_cle(cle):
    return "-".join(cle[i:i + 4] for i in range(0, len(cle), 4))


def id_camera(nom):
    """Identifiant d'URL d'une caméra (le nom encodé : stable tant que la caméra n'est pas renommée)."""
    return base64.urlsafe_b64encode(nom.encode("utf-8")).decode().rstrip("=")


def nom_depuis_id(ident):
    try:
        return base64.urlsafe_b64decode(ident + "=" * (-len(ident) % 4)).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None


def hacher_mot_de_passe(mdp):
    sel = secrets.token_bytes(16)
    h = hashlib.scrypt(mdp.encode("utf-8"), salt=sel, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt$14$8$1${base64.b64encode(sel).decode()}${base64.b64encode(h).decode()}"


def verifier_mot_de_passe(mdp, stocke):
    try:
        _, ln, r, p, sel, h = stocke.split("$")
        calcule = hashlib.scrypt(mdp.encode("utf-8"), salt=base64.b64decode(sel), n=2 ** int(ln), r=int(r),
                                 p=int(p), dklen=32)
        return hmac.compare_digest(calcule, base64.b64decode(h))
    except (ValueError, TypeError):
        return False


_HACHE_LEURRE = hacher_mot_de_passe(secrets.token_hex(8))  # même durée de calcul quand le compte n'existe pas


def mot_de_passe_valide(mdp):
    if len(mdp or "") < 10:
        return "Le mot de passe doit faire au moins 10 caractères."
    if not re.search(r"[A-Za-zÀ-ÿ]", mdp) or not re.search(r"\d", mdp):
        return "Le mot de passe doit contenir au moins une lettre et un chiffre."
    if len(mdp) > 200:
        return "Mot de passe trop long."
    return None


def empreinte_jeton(jeton):
    return hashlib.sha256(jeton.encode()).hexdigest()


def adresses_locales():
    """Adresses IPv4 de ce PC sur le réseau local (pour les afficher à côté de la clé)."""
    vues = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))  # aucun paquet envoyé : sert seulement à choisir la bonne carte réseau
        vues.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in vues and not ip.startswith("127."):
                vues.append(ip)
    except OSError:
        pass
    return vues or ["127.0.0.1"]


# ---------------------------------------------------------------------------
# Identité du serveur : clé privée, certificat, clé d'appairage (créés une seule fois)
# ---------------------------------------------------------------------------
class Identite:
    def __init__(self, dossier):
        self.dossier = dossier
        os.makedirs(dossier, exist_ok=True)
        self.chemin_cle = os.path.join(dossier, "serveur_cle_privee.pem")
        self.chemin_cert = os.path.join(dossier, "serveur_certificat.pem")
        self.chemin_info = os.path.join(dossier, "serveur.json")
        if not (os.path.isfile(self.chemin_cle) and os.path.isfile(self.chemin_cert)):
            self._creer()
        self.info = self._lire_info()
        self.cle = self._calculer_cle()

    def _creer(self):
        try:
            from cryptography import x509
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import ec
            from cryptography.x509.oid import NameOID
        except ImportError:
            raise ErreurServeur("le module « cryptography » manque : relancez l'installateur de Flux "
                                "(ou : pip install cryptography)") from None
        import datetime
        prive = ec.generate_private_key(ec.SECP256R1())
        ident = secrets.token_hex(6)
        nom = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"Flux {ident}"),
                         x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Flux - FluxLite")])
        maintenant = datetime.datetime.now(datetime.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(nom).issuer_name(nom).public_key(prive.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(maintenant - datetime.timedelta(days=1))
                .not_valid_after(maintenant + datetime.timedelta(days=365 * 30))
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .sign(prive, hashes.SHA256()))
        octets_cle = prive.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption())
        # Écriture atomique, droits restreints au compte de l'utilisateur
        for chemin, octets, prive_ in ((self.chemin_cle, octets_cle, True),
                                       (self.chemin_cert, cert.public_bytes(serialization.Encoding.PEM), False)):
            tmp = chemin + ".tmp"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if prive_ else 0o644)
            with os.fdopen(fd, "wb") as f:
                f.write(octets)
            os.replace(tmp, chemin)
        self._ecrire_info({"id": ident, "cree_le": time.time()})

    def _lire_info(self):
        try:
            with open(self.chemin_info, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and d.get("id"):
                return d
        except (OSError, ValueError):
            pass
        d = {"id": secrets.token_hex(6), "cree_le": time.time()}
        self._ecrire_info(d)
        return d

    def _ecrire_info(self, d):
        tmp = self.chemin_info + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
        os.replace(tmp, self.chemin_info)

    def spki_der(self):
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization
        with open(self.chemin_cert, "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read())
        return cert.public_key().public_bytes(serialization.Encoding.DER,
                                              serialization.PublicFormat.SubjectPublicKeyInfo)

    def _calculer_cle(self):
        """32 caractères = 160 bits de l'empreinte SHA-256 de la clé publique (ce que le téléphone vérifie)."""
        return base32_crockford(hashlib.sha256(self.spki_der()).digest()[:20])

    @property
    def cle_affichee(self):
        return formater_cle(self.cle)

    def contexte_tls(self):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(self.chemin_cert, self.chemin_cle)
        try:
            ctx.set_ciphers("ECDHE+AESGCM:ECDHE+CHACHA20")
        except ssl.SSLError:
            pass
        return ctx

    def lien_appairage(self, adresses, port, nom):
        """Contenu du QR code : ouvre FluxLite avec l'adresse et la clé déjà remplies."""
        q = urllib.parse.urlencode({"h": ",".join(adresses), "p": port, "k": self.cle, "n": nom})
        return f"fluxlite://appairer?{q}"


# ---------------------------------------------------------------------------
# Base des comptes
# ---------------------------------------------------------------------------
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS entreprises (
    id INTEGER PRIMARY KEY, nom TEXT NOT NULL UNIQUE COLLATE NOCASE, cameras TEXT NOT NULL DEFAULT '[]',
    toutes INTEGER NOT NULL DEFAULT 0, cree_le REAL NOT NULL);
CREATE TABLE IF NOT EXISTS comptes (
    id INTEGER PRIMARY KEY, mail TEXT NOT NULL UNIQUE COLLATE NOCASE, nom TEXT NOT NULL, prenom TEXT NOT NULL,
    societe TEXT NOT NULL DEFAULT '', entreprise_id INTEGER REFERENCES entreprises(id) ON DELETE SET NULL,
    statut TEXT NOT NULL DEFAULT 'attente', hash TEXT NOT NULL, cree_le REAL NOT NULL, derniere_connexion REAL,
    derniere_ip TEXT, appareil TEXT, version_app TEXT, cgu_version TEXT, cgu_le REAL);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY, compte_id INTEGER NOT NULL REFERENCES comptes(id) ON DELETE CASCADE,
    jeton TEXT NOT NULL UNIQUE, cree_le REAL NOT NULL, expire_le REAL NOT NULL, activite REAL NOT NULL,
    appareil TEXT, ip TEXT);
CREATE TABLE IF NOT EXISTS journal (
    id INTEGER PRIMARY KEY, heure REAL NOT NULL, camera TEXT NOT NULL, texte TEXT NOT NULL, niveau TEXT NOT NULL,
    prioritaire INTEGER NOT NULL DEFAULT 0, photo BLOB);
CREATE INDEX IF NOT EXISTS journal_camera ON journal(camera, id);
CREATE INDEX IF NOT EXISTS sessions_compte ON sessions(compte_id);
"""
STATUTS = {"attente": "En attente", "actif": "Actif", "suspendu": "Suspendu"}


class Comptes:
    def __init__(self, chemin):
        self._c = sqlite3.connect(chemin, check_same_thread=False, timeout=30)
        self._c.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._c.execute("PRAGMA journal_mode=WAL")
            self._c.execute("PRAGMA foreign_keys=ON")
            self._c.executescript(SCHEMA_SQL)
            self._c.commit()

    def _x(self, sql, args=(), commit=True):
        with self._lock:
            cur = self._c.execute(sql, args)
            if commit:
                self._c.commit()
            return cur

    def _un(self, sql, args=()):
        with self._lock:
            r = self._c.execute(sql, args).fetchone()
            return dict(r) if r else None

    def _tous(self, sql, args=()):
        with self._lock:
            return [dict(r) for r in self._c.execute(sql, args).fetchall()]

    # --- entreprises -------------------------------------------------------------
    def entreprises(self):
        lignes = self._tous("SELECT e.*, (SELECT COUNT(*) FROM comptes c WHERE c.entreprise_id = e.id) AS nb "
                            "FROM entreprises e ORDER BY e.nom COLLATE NOCASE")
        for e in lignes:
            e["cameras"] = json.loads(e["cameras"] or "[]")
            e["toutes"] = bool(e["toutes"])
        return lignes

    def entreprise(self, eid):
        e = self._un("SELECT * FROM entreprises WHERE id = ?", (eid,))
        if e:
            e["cameras"] = json.loads(e["cameras"] or "[]")
            e["toutes"] = bool(e["toutes"])
        return e

    def creer_entreprise(self, nom, cameras=(), toutes=False):
        nom = nom.strip()
        if not nom:
            raise ErreurServeur("nom d'entreprise vide")
        try:
            return self._x("INSERT INTO entreprises (nom, cameras, toutes, cree_le) VALUES (?, ?, ?, ?)",
                           (nom[:80], json.dumps(list(cameras)), int(toutes), time.time())).lastrowid
        except sqlite3.IntegrityError:
            raise ErreurServeur(f"l'entreprise « {nom} » existe déjà") from None

    def modifier_entreprise(self, eid, nom=None, cameras=None, toutes=None):
        e = self.entreprise(eid)
        if not e:
            return
        try:
            self._x("UPDATE entreprises SET nom = ?, cameras = ?, toutes = ? WHERE id = ?",
                    ((nom or e["nom"]).strip()[:80], json.dumps(list(e["cameras"] if cameras is None else cameras)),
                     int(e["toutes"] if toutes is None else toutes), eid))
        except sqlite3.IntegrityError:
            raise ErreurServeur(f"l'entreprise « {nom} » existe déjà") from None

    def supprimer_entreprise(self, eid):
        self._x("DELETE FROM entreprises WHERE id = ?", (eid,))

    def camera_renommee(self, ancien, nouveau):
        for e in self.entreprises():
            if ancien in e["cameras"]:
                self.modifier_entreprise(e["id"], cameras=[nouveau if c == ancien else c for c in e["cameras"]])
        self._x("UPDATE journal SET camera = ? WHERE camera = ?", (nouveau, ancien))

    # --- comptes -----------------------------------------------------------------
    def comptes(self):
        return self._tous("SELECT c.id, c.mail, c.nom, c.prenom, c.societe, c.entreprise_id, c.statut, c.cree_le, "
                          "c.derniere_connexion, c.derniere_ip, c.appareil, c.version_app, c.cgu_version, c.cgu_le, "
                          "e.nom AS entreprise, (SELECT COUNT(*) FROM sessions s WHERE s.compte_id = c.id "
                          "AND s.expire_le > ?) AS sessions "
                          "FROM comptes c LEFT JOIN entreprises e ON e.id = c.entreprise_id "
                          "ORDER BY c.statut = 'attente' DESC, c.nom COLLATE NOCASE, c.prenom COLLATE NOCASE",
                          (time.time(),))

    def compte(self, cid):
        return self._un("SELECT c.*, e.nom AS entreprise FROM comptes c LEFT JOIN entreprises e "
                        "ON e.id = c.entreprise_id WHERE c.id = ?", (cid,))

    def compte_par_mail(self, mail):
        return self._un("SELECT * FROM comptes WHERE mail = ?", (mail.strip(),))

    def creer_compte(self, mail, mdp, nom, prenom, societe="", statut="attente", entreprise_id=None, appareil="",
                     version_app="", cgu_version=None):
        try:
            return self._x("INSERT INTO comptes (mail, nom, prenom, societe, entreprise_id, statut, hash, cree_le, "
                           "appareil, version_app, cgu_version, cgu_le) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                           (mail.strip()[:254], nom.strip()[:60], prenom.strip()[:60], societe.strip()[:80],
                            entreprise_id, statut, hacher_mot_de_passe(mdp), time.time(), appareil[:120],
                            version_app[:40], cgu_version, time.time() if cgu_version else None)).lastrowid
        except sqlite3.IntegrityError:
            raise ErreurServeur("un compte existe déjà avec cette adresse mail") from None

    def modifier_compte(self, cid, **champs):
        permis = {"nom", "prenom", "statut", "entreprise_id", "societe", "derniere_connexion", "derniere_ip",
                  "appareil", "version_app", "cgu_version", "cgu_le"}
        champs = {k: v for k, v in champs.items() if k in permis}
        if champs:
            self._x(f"UPDATE comptes SET {', '.join(k + ' = ?' for k in champs)} WHERE id = ?",
                    (*champs.values(), cid))
        if champs.get("statut") == "suspendu":
            self.revoquer_sessions(cid)

    def changer_mot_de_passe(self, cid, mdp):
        self._x("UPDATE comptes SET hash = ? WHERE id = ?", (hacher_mot_de_passe(mdp), cid))

    def supprimer_compte(self, cid):
        self._x("DELETE FROM sessions WHERE compte_id = ?", (cid,), commit=False)
        self._x("DELETE FROM comptes WHERE id = ?", (cid,))

    # --- sessions ------------------------------------------------------------------
    def ouvrir_session(self, cid, duree_jours, appareil, ip):
        jeton = secrets.token_urlsafe(32)
        t = time.time()
        self._x("INSERT INTO sessions (compte_id, jeton, cree_le, expire_le, activite, appareil, ip) "
                "VALUES (?,?,?,?,?,?,?)", (cid, empreinte_jeton(jeton), t, t + duree_jours * 86400, t,
                                           appareil[:120], ip))
        return jeton

    def session(self, jeton):
        if not jeton or len(jeton) > 100:
            return None
        s = self._un("SELECT * FROM sessions WHERE jeton = ? AND expire_le > ?", (empreinte_jeton(jeton), time.time()))
        if s and time.time() - s["activite"] > 60:
            self._x("UPDATE sessions SET activite = ? WHERE id = ?", (time.time(), s["id"]))
        return s

    def sessions(self, cid):
        return self._tous("SELECT id, cree_le, expire_le, activite, appareil, ip FROM sessions "
                          "WHERE compte_id = ? AND expire_le > ? ORDER BY activite DESC", (cid, time.time()))

    def revoquer_session(self, sid, cid=None):
        if cid is None:
            self._x("DELETE FROM sessions WHERE id = ?", (sid,))
        else:
            self._x("DELETE FROM sessions WHERE id = ? AND compte_id = ?", (sid, cid))

    def revoquer_sessions(self, cid, sauf=None):
        self._x("DELETE FROM sessions WHERE compte_id = ? AND id != ?", (cid, sauf or -1))

    # --- journal ---------------------------------------------------------------------
    def ajouter_journal(self, heure, camera, texte, niveau, prioritaire, photo):
        return self._x("INSERT INTO journal (heure, camera, texte, niveau, prioritaire, photo) VALUES (?,?,?,?,?,?)",
                       (heure, camera, texte[:500], niveau, int(prioritaire), photo)).lastrowid

    def journal(self, cameras, avant=None, apres=None, limite=50, camera=None):
        if not cameras:
            return []
        if camera is not None:
            cameras = [c for c in cameras if c == camera]
            if not cameras:
                return []
        cond, args = [f"camera IN ({','.join('?' * len(cameras))})"], list(cameras)
        if avant:
            cond.append("id < ?")
            args.append(int(avant))
        if apres is not None:
            cond.append("id > ?")
            args.append(int(apres))
        ordre = "ASC" if apres is not None else "DESC"
        return self._tous(f"SELECT id, heure, camera, texte, niveau, prioritaire, photo IS NOT NULL AS photo "
                          f"FROM journal WHERE {' AND '.join(cond)} ORDER BY id {ordre} LIMIT ?",
                          (*args, max(1, min(200, int(limite)))))

    def photo_journal(self, jid):
        r = self._un("SELECT camera, photo FROM journal WHERE id = ?", (jid,))
        return r

    def dernier_journal(self):
        r = self._un("SELECT MAX(id) AS m FROM journal")
        return (r or {}).get("m") or 0

    def purger(self, jours_journal):
        t = time.time()
        self._x("DELETE FROM sessions WHERE expire_le < ?", (t,), commit=False)
        if jours_journal > 0:
            self._x("DELETE FROM journal WHERE heure < ?", (t - jours_journal * 86400,), commit=False)
        with self._lock:
            self._c.commit()

    def fermer(self):
        with self._lock:
            self._c.close()


# ---------------------------------------------------------------------------
# Caméras : ce que l'interface publie pour le serveur
# ---------------------------------------------------------------------------
class FournisseurVide:
    """Interface attendue par le serveur (l'interface de Flux en fournit une version branchée sur les caméras)."""

    def cameras(self):
        """[{nom, etat ('direct', 'alerte', 'chargement', 'arret'), personnes, resolution (l, h) ou None, fps}]"""
        return []

    def image(self, nom):
        """(image BGR numpy, annotations dict ou None) de la dernière image de la caméra, ou None."""
        return None


class CacheImages:
    """Encode en JPEG une seule fois par image et par taille, quel que soit le nombre de téléphones connectés."""

    def __init__(self, dessiner=None):
        self.dessiner = dessiner
        self._cache = {}
        self._lock = threading.Lock()

    def jpeg(self, fournisseur, nom, largeur, qualite, cadres):
        res = fournisseur.image(nom)
        if res is None:
            return None, None
        img, ann = res
        if img is None:
            return None, None
        cle = (nom, largeur, qualite, cadres)
        with self._lock:
            c = self._cache.get(cle)
            if c and c[0] is img:
                return c[1], id(img)
        import cv2
        h, w = img.shape[:2]
        sortie = img
        if cadres and ann and self.dessiner is not None:
            sortie = self.dessiner(img.copy(), ann)
        if w > largeur:
            sortie = cv2.resize(sortie, (largeur, max(2, int(h * largeur / w))), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", sortie, [cv2.IMWRITE_JPEG_QUALITY, int(qualite)])
        if not ok:
            return None, None
        octets = buf.tobytes()
        with self._lock:
            self._cache[cle] = (img, octets)
        return octets, id(img)


def miniature(jpeg, largeur=360):
    if not jpeg:
        return None
    try:
        import cv2
        import numpy as np
        img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return None
        h, w = img.shape[:2]
        if w > largeur:
            img = cv2.resize(img, (largeur, int(h * largeur / w)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 72])
        return buf.tobytes() if ok else None
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Serveur
# ---------------------------------------------------------------------------
class ServeurFluxLite:
    """Démarre et arrête le serveur HTTPS ; garde comptes, sessions et journal.

    reglages : objet avec get(cle) (la Config de Flux), clés « fluxlite.* ».
    rappel(texte, niveau) : événements à afficher dans Flux (nouveau compte, erreurs…), appelé depuis n'importe
    quel fil.
    """

    def __init__(self, dossier, reglages, fournisseur=None, rappel=None, dessiner=None, version_flux=""):
        self.dossier = dossier
        self.reglages = reglages
        self.fournisseur = fournisseur or FournisseurVide()
        self.rappel = rappel or (lambda texte, niveau="info": None)
        self.version_flux = version_flux
        self.identite = Identite(dossier)
        self.comptes = Comptes(os.path.join(dossier, "comptes.db"))
        self.images = CacheImages(dessiner)
        self._httpd = None
        self._fil = None
        self.erreur = ""
        self.port_actif = None
        self._nouveau = threading.Condition()
        self._dernier_id = self.comptes.dernier_journal()
        self._echecs = {}       # clé (ip ou mail) -> [heures des échecs]
        self._echecs_lock = threading.Lock()
        self.flux_ouverts = {}  # compte_id -> nombre de flux vidéo ouverts
        self._flux_lock = threading.Lock()
        self.connectes = {}     # compte_id -> heure de la dernière requête
        self._file_journal = queue.Queue()
        threading.Thread(target=self._boucle_journal, daemon=True, name="fluxlite-journal").start()

    # --- réglages --------------------------------------------------------------------
    def r(self, cle, defaut=None):
        try:
            v = self.reglages.get(f"fluxlite.{cle}")
        except Exception:  # noqa: BLE001
            v = None
        return defaut if v is None else v

    @property
    def nom(self):
        return (self.r("nom", "") or "").strip() or f"Flux {self.identite.info['id'][:4].upper()}"

    # --- démarrage ----------------------------------------------------------------------
    def en_marche(self):
        return self._httpd is not None

    def demarrer(self):
        self.arreter()
        port = int(self.r("port", PORT_DEFAUT))
        try:
            ctx = self.identite.contexte_tls()
            httpd = _ServeurHTTPS(("0.0.0.0", port), _Gestionnaire, ctx, self)
        except OSError as e:
            self.erreur = (f"le port {port} est déjà utilisé : choisissez-en un autre (Réglages › FluxLite)"
                           if getattr(e, "errno", None) in (98, 10048) else str(e))
            raise ErreurServeur(self.erreur) from None
        self._httpd = httpd
        self.port_actif = port
        self.erreur = ""
        self._fil = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.5}, daemon=True,
                                     name="fluxlite-serveur")
        self._fil.start()
        self.comptes.purger(int(self.r("conservation_journal", 7)))
        return port

    def arreter(self):
        h, self._httpd = self._httpd, None
        self.port_actif = None
        if h is not None:
            h.arret = True
            with self._nouveau:
                self._nouveau.notify_all()
            h.shutdown()
            h.server_close()

    def fermer(self):
        self.arreter()
        self._file_journal.put(None)

    # --- journal (appelé depuis l'interface) -------------------------------------------------
    def evenement(self, e):
        """Reçoit un événement du journal de Flux. Seules les alertes, actions et vidéos des caméras partent."""
        if e.get("niveau") not in NIVEAUX_JOURNAL or e.get("source") in (None, "", "Système"):
            return
        if e["niveau"] == "action" and not self.r("actions", False):
            return
        self._file_journal.put(e)

    def _boucle_journal(self):
        while True:
            e = self._file_journal.get()
            if e is None:
                return
            try:
                photo = miniature(e.get("jpeg")) if e["niveau"] == "alerte" else None
                jid = self.comptes.ajouter_journal(time.time(), e["source"], e.get("texte", ""), e["niveau"],
                                                   bool(e.get("prioritaire")), photo)
                with self._nouveau:
                    self._dernier_id = jid
                    self._nouveau.notify_all()
            except Exception as ex:  # noqa: BLE001
                self.rappel(f"Journal non enregistré ({ex})", "erreur")

    def attendre(self, depuis, delai):
        """Attend un événement plus récent que `depuis` (au plus `delai` secondes)."""
        fin = time.time() + delai
        with self._nouveau:
            while self._dernier_id <= depuis and self._httpd is not None:
                reste = fin - time.time()
                if reste <= 0:
                    break
                self._nouveau.wait(min(reste, 5))
            return self._dernier_id

    # --- caméras d'un compte ----------------------------------------------------------------
    def cameras_autorisees(self, compte):
        noms = [c["nom"] for c in self.fournisseur.cameras()]
        if not compte.get("entreprise_id"):
            return []
        e = self.comptes.entreprise(compte["entreprise_id"])
        if not e:
            return []
        if e["toutes"]:
            return noms
        return [n for n in noms if n in e["cameras"]]

    def noms_autorises_journal(self, compte):
        """Pour le journal : aussi les caméras attribuées mais fermées (leurs anciennes alertes restent lisibles)."""
        e = self.comptes.entreprise(compte["entreprise_id"]) if compte.get("entreprise_id") else None
        if not e:
            return []
        if e["toutes"]:
            return list({c["nom"] for c in self.fournisseur.cameras()} |
                        {r["camera"] for r in self.comptes._tous("SELECT DISTINCT camera FROM journal")})
        return list(e["cameras"])

    # --- anti-force brute ---------------------------------------------------------------------
    def bloque(self, *cles):
        t = time.time()
        with self._echecs_lock:
            for c in cles:
                vus = [x for x in self._echecs.get(c, []) if t - x < BLOCAGE]
                self._echecs[c] = vus
                if len(vus) >= ESSAIS_MAX:
                    return int(BLOCAGE - (t - vus[0])) + 1
        return 0

    def echec(self, *cles):
        with self._echecs_lock:
            for c in cles:
                self._echecs.setdefault(c, []).append(time.time())

    def reussite(self, *cles):
        with self._echecs_lock:
            for c in cles:
                self._echecs.pop(c, None)


class _ServeurHTTPS(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 32

    def __init__(self, adresse, gestionnaire, ctx, appli):
        self.ctx, self.appli, self.arret = ctx, appli, False
        super().__init__(adresse, gestionnaire)

    def finish_request(self, request, client_address):
        # La poignée de main TLS a lieu ici, dans le fil de la requête : un client lent ne bloque pas les autres.
        request.settimeout(20)
        try:
            tls = self.ctx.wrap_socket(request, server_side=True)
        except (ssl.SSLError, OSError):
            return
        tls.settimeout(75)
        try:
            self.RequestHandlerClass(tls, client_address, self)
        finally:
            try:
                tls.close()
            except OSError:
                pass

    def handle_error(self, request, client_address):
        pass  # connexions coupées par le téléphone : normal, rien à signaler


class _Gestionnaire(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "FluxLite"
    sys_version = ""

    def log_message(self, *_):
        pass

    # --- réponses ------------------------------------------------------------------------
    @property
    def appli(self):
        return self.server.appli

    def _envoyer(self, code, corps, type_="application/json; charset=utf-8", entetes=None):
        self.send_response(code)
        self.send_header("Content-Type", type_)
        self.send_header("Content-Length", str(len(corps)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (entetes or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(corps)

    def json(self, donnees, code=200):
        self._envoyer(code, json.dumps(donnees, ensure_ascii=False).encode("utf-8"))

    def erreur(self, code, message, **extra):
        self.json({"erreur": message, **extra}, code)

    def corps(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > TAILLE_CORPS_MAX:
            raise ErreurServeur("requête trop grande")
        if n == 0:
            return {}
        try:
            d = json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ErreurServeur("requête illisible") from None
        if not isinstance(d, dict):
            raise ErreurServeur("requête illisible")
        return d

    @property
    def ip(self):
        return self.client_address[0]

    def compte_connecte(self):
        """Renvoie (compte, session) ou envoie 401 et renvoie (None, None)."""
        auth = self.headers.get("Authorization", "")
        jeton = auth[7:].strip() if auth.startswith("Bearer ") else ""
        s = self.appli.comptes.session(jeton)
        if not s:
            self.erreur(401, "Session expirée : reconnectez-vous.")
            return None, None
        c = self.appli.comptes.compte(s["compte_id"])
        if not c or c["statut"] != "actif":
            self.appli.comptes.revoquer_session(s["id"])
            self.erreur(401, "Ce compte n'est plus actif. Contactez votre responsable.")
            return None, None
        self.appli.connectes[c["id"]] = time.time()
        return c, s

    # --- routage --------------------------------------------------------------------------
    def do_GET(self):
        self._router("GET")

    def do_POST(self):
        self._router("POST")

    def do_PATCH(self):
        self._router("PATCH")

    def do_DELETE(self):
        self._router("DELETE")

    def _router(self, methode):
        url = urllib.parse.urlsplit(self.path)
        chemin = url.path.rstrip("/")
        self.q = {k: v[-1] for k, v in urllib.parse.parse_qs(url.query).items()}
        p = chemin.split("/")
        try:
            if not chemin.startswith("/api/v1"):
                return self.erreur(404, "Adresse inconnue.")
            route = "/".join(p[3:])
            if methode == "GET" and route == "info":
                return self.info()
            if methode == "POST" and route == "inscription":
                return self.inscription()
            if methode == "POST" and route == "connexion":
                return self.connexion()
            compte, session = self.compte_connecte()
            if compte is None:
                return
            if route == "deconnexion" and methode == "POST":
                self.appli.comptes.revoquer_session(session["id"])
                return self.json({"ok": True})
            if route == "compte":
                if methode == "GET":
                    return self.json(self._profil(compte, session))
                if methode == "PATCH":
                    return self.modifier_profil(compte, session)
                if methode == "DELETE":
                    return self.supprimer_compte(compte)
            if route == "compte/mot_de_passe" and methode == "POST":
                return self.changer_mdp(compte, session)
            if route == "compte/sessions/revoquer" and methode == "POST":
                d = self.corps()
                if d.get("id") == "autres":
                    self.appli.comptes.revoquer_sessions(compte["id"], sauf=session["id"])
                else:
                    self.appli.comptes.revoquer_session(int(d.get("id", 0)), compte["id"])
                return self.json(self._profil(compte, session))
            if route == "compte/export" and methode == "GET":
                return self.exporter(compte)
            if route == "cameras" and methode == "GET":
                return self.cameras(compte)
            if len(p) == 6 and p[3] == "cameras" and methode == "GET":
                nom = nom_depuis_id(p[4])
                if nom is None or nom not in self.appli.cameras_autorisees(compte):
                    return self.erreur(404, "Caméra introuvable ou non autorisée.")
                if p[5] == "image":
                    return self.image(nom)
                if p[5] == "flux":
                    return self.flux(compte, nom)
            if route == "journal" and methode == "GET":
                return self.journal(compte)
            if len(p) == 6 and p[3] == "journal" and p[5] == "photo" and methode == "GET":
                return self.photo(compte, p[4])
            if route == "alertes/attente" and methode == "GET":
                return self.attente(compte)
            return self.erreur(404, "Adresse inconnue.")
        except ErreurServeur as e:
            self.erreur(400, str(e))
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError, TimeoutError):
            self.close_connection = True
        except (ValueError, TypeError, KeyError):
            self.erreur(400, "Requête invalide.")

    # --- routes publiques ---------------------------------------------------------------------
    def info(self):
        a = self.appli
        self.json({"application": "Flux", "nom": a.nom, "api": VERSION_API, "version_flux": a.version_flux,
                   "inscription": bool(a.r("inscription", True)),
                   "validation_manuelle": bool(a.r("validation_manuelle", True)), "cgu_version": VERSION_CGU,
                   "responsable": (a.r("responsable", "") or "").strip(), "contact": (a.r("contact", "") or "").strip(),
                   "conservation_journal": int(a.r("conservation_journal", 7))})

    def inscription(self):
        a = self.appli
        if not a.r("inscription", True):
            return self.erreur(403, "Les inscriptions sont fermées sur ce serveur. Demandez un compte à votre "
                                    "responsable.")
        attente = a.bloque("insc:" + self.ip)
        if attente:
            return self.erreur(429, f"Trop de tentatives. Réessayez dans {-(-attente // 60)} min.")
        d = self.corps()
        mail, mdp = str(d.get("mail", "")).strip(), str(d.get("mot_de_passe", ""))
        nom, prenom = str(d.get("nom", "")).strip(), str(d.get("prenom", "")).strip()
        if not RE_MAIL.match(mail):
            return self.erreur(400, "Adresse mail invalide.")
        if not nom or not prenom:
            return self.erreur(400, "Indiquez votre nom et votre prénom.")
        probleme = mot_de_passe_valide(mdp)
        if probleme:
            return self.erreur(400, probleme)
        if d.get("cgu_version") != VERSION_CGU:
            return self.erreur(400, "Vous devez accepter les conditions d'utilisation en vigueur.",
                               cgu_version=VERSION_CGU)
        a.echec("insc:" + self.ip)  # compte aussi les inscriptions réussies : 5 par quart d'heure et par adresse
        societe = str(d.get("societe", "")).strip()
        statut, eid = "attente", None
        if not a.r("validation_manuelle", True):
            e = next((x for x in a.comptes.entreprises() if x["nom"].lower() == societe.lower()), None) \
                if societe else None
            if e:
                statut, eid = "actif", e["id"]
        a.comptes.creer_compte(mail, mdp, nom, prenom, societe, statut, eid, str(d.get("appareil", "")),
                               str(d.get("version_app", "")), VERSION_CGU)
        if statut == "attente":
            a.rappel(f"Nouveau compte à valider — {prenom} {nom} ({mail}"
                     f"{', ' + societe if societe else ''}).", "alerte_compte")
        else:
            a.rappel(f"Nouveau compte {prenom} {nom} ({mail}) ajouté à « {societe} ».", "info")
        self.json({"ok": True, "statut": statut,
                   "message": "Compte créé." if statut == "actif" else
                   "Compte créé. Il sera utilisable dès que votre responsable l'aura validé sur le PC Flux."}, 201)

    def connexion(self):
        a = self.appli
        d = self.corps()
        mail, mdp = str(d.get("mail", "")).strip().lower(), str(d.get("mot_de_passe", ""))
        attente = a.bloque("ip:" + self.ip, "mail:" + mail)
        if attente:
            return self.erreur(429, f"Trop d'essais ratés. Réessayez dans {-(-attente // 60)} min.")
        c = a.comptes.compte_par_mail(mail) if mail else None
        if not verifier_mot_de_passe(mdp, c["hash"] if c else _HACHE_LEURRE) or not c:
            a.echec("ip:" + self.ip, "mail:" + mail)
            return self.erreur(401, "Adresse mail ou mot de passe incorrect.")
        a.reussite("ip:" + self.ip, "mail:" + mail)
        if c["statut"] == "attente":
            return self.erreur(403, "Votre compte attend la validation de votre responsable.", statut="attente")
        if c["statut"] == "suspendu":
            return self.erreur(403, "Ce compte est suspendu. Contactez votre responsable.", statut="suspendu")
        appareil = str(d.get("appareil", ""))[:120]
        jeton = a.comptes.ouvrir_session(c["id"], int(a.r("duree_session", 30)), appareil, self.ip)
        a.comptes.modifier_compte(c["id"], derniere_connexion=time.time(), derniere_ip=self.ip, appareil=appareil,
                                  version_app=str(d.get("version_app", ""))[:40])
        s = a.comptes.session(jeton)
        self.json({"jeton": jeton, "compte": self._profil(a.comptes.compte(c["id"]), s)})

    # --- compte ------------------------------------------------------------------------------
    def _profil(self, c, session):
        a = self.appli
        e = a.comptes.entreprise(c["entreprise_id"]) if c.get("entreprise_id") else None
        sessions = [{**s, "courante": s["id"] == session["id"]} for s in a.comptes.sessions(c["id"])]
        return {"id": c["id"], "mail": c["mail"], "nom": c["nom"], "prenom": c["prenom"], "societe": c["societe"],
                "entreprise": e["nom"] if e else None, "statut": c["statut"], "cree_le": c["cree_le"],
                "derniere_connexion": c["derniere_connexion"], "cgu_version": c["cgu_version"],
                "cgu_a_jour": c["cgu_version"] == VERSION_CGU, "sessions": sessions, "serveur": a.nom}

    def modifier_profil(self, c, s):
        d = self.corps()
        champs = {}
        for k in ("nom", "prenom"):
            if k in d:
                v = str(d[k]).strip()
                if not v:
                    return self.erreur(400, "Le nom et le prénom ne peuvent pas être vides.")
                champs[k] = v[:60]
        if d.get("cgu_version") == VERSION_CGU:
            champs.update(cgu_version=VERSION_CGU, cgu_le=time.time())
        self.appli.comptes.modifier_compte(c["id"], **champs)
        self.json(self._profil(self.appli.comptes.compte(c["id"]), s))

    def changer_mdp(self, c, s):
        d = self.corps()
        a = self.appli
        if a.bloque("mail:" + c["mail"].lower()):
            return self.erreur(429, "Trop d'essais ratés. Réessayez plus tard.")
        complet = a.comptes.compte_par_mail(c["mail"])
        if not verifier_mot_de_passe(str(d.get("ancien", "")), complet["hash"]):
            a.echec("mail:" + c["mail"].lower())
            return self.erreur(403, "Mot de passe actuel incorrect.")
        nouveau = str(d.get("nouveau", ""))
        probleme = mot_de_passe_valide(nouveau)
        if probleme:
            return self.erreur(400, probleme)
        a.comptes.changer_mot_de_passe(c["id"], nouveau)
        a.comptes.revoquer_sessions(c["id"], sauf=s["id"])  # les autres appareils doivent se reconnecter
        self.json({"ok": True, "message": "Mot de passe changé. Vos autres appareils ont été déconnectés."})

    def supprimer_compte(self, c):
        d = self.corps()
        complet = self.appli.comptes.compte_par_mail(c["mail"])
        if not verifier_mot_de_passe(str(d.get("mot_de_passe", "")), complet["hash"]):
            self.appli.echec("mail:" + c["mail"].lower())
            return self.erreur(403, "Mot de passe incorrect.")
        self.appli.comptes.supprimer_compte(c["id"])
        self.appli.rappel(f"{c['prenom']} {c['nom']} ({c['mail']}) a supprimé son compte.", "info")
        self.json({"ok": True, "message": "Votre compte et vos données ont été supprimés de ce serveur."})

    def exporter(self, c):
        """Droit d'accès et à la portabilité (RGPD, articles 15 et 20) : tout ce que ce serveur sait du compte."""
        a = self.appli
        complet = dict(a.comptes.compte(c["id"]))
        complet.pop("hash", None)
        donnees = {"export": "FluxLite", "date": time.time(), "serveur": a.nom, "compte": complet,
                   "sessions": a.comptes.sessions(c["id"]),
                   "note": "Le mot de passe n'est jamais stocké : seule son empreinte chiffrée l'est. Les alertes "
                           "des caméras ne sont pas des données de votre compte ; elles sont effacées après "
                           f"{int(a.r('conservation_journal', 7))} jour(s)."}
        self._envoyer(200, json.dumps(donnees, ensure_ascii=False, indent=2).encode("utf-8"),
                      entetes={"Content-Disposition": "attachment; filename=fluxlite-mes-donnees.json"})

    # --- caméras -------------------------------------------------------------------------------
    def cameras(self, c):
        autorisees = set(self.appli.cameras_autorisees(c))
        liste = []
        for cam in self.appli.fournisseur.cameras():
            if cam["nom"] in autorisees:
                res = cam.get("resolution")
                liste.append({"id": id_camera(cam["nom"]), "nom": cam["nom"], "etat": cam.get("etat", "arret"),
                              "personnes": int(cam.get("personnes", 0)), "fps": round(float(cam.get("fps", 0)), 1),
                              "resolution": f"{res[0]}×{res[1]}" if res else None})
        self.json({"cameras": liste, "serveur": self.appli.nom, "entreprise": bool(c.get("entreprise_id"))})

    def _jpeg(self, nom, largeur=None):
        a = self.appli
        largeur = max(240, min(1920, int(largeur or a.r("largeur", 960))))
        return a.images.jpeg(a.fournisseur, nom, largeur, int(a.r("qualite", 70)), bool(a.r("cadres", True)))

    def image(self, nom):
        octets, _ = self._jpeg(nom, self.q.get("largeur"))
        if octets is None:
            return self.erreur(503, "Caméra arrêtée ou image pas encore disponible.")
        self._envoyer(200, octets, "image/jpeg")

    def flux(self, c, nom):
        """Flux vidéo MJPEG (une image JPEG après l'autre) jusqu'à ce que le téléphone coupe."""
        a = self.appli
        limite = int(a.r("flux_par_compte", 6))
        with a._flux_lock:
            if a.flux_ouverts.get(c["id"], 0) >= limite:
                return self.erreur(429, f"Trop de vidéos ouvertes en même temps (maximum {limite}).")
            a.flux_ouverts[c["id"]] = a.flux_ouverts.get(c["id"], 0) + 1
        try:
            fps = max(1.0, min(float(self.q.get("fps", a.r("fps", 8))), float(a.r("fps", 8))))
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=fluxlite")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            dernier, t_verif, jeton = None, time.time(), self.headers.get("Authorization", "")[7:].strip()
            while not self.server.arret:
                debut = time.time()
                if debut - t_verif > 10:  # compte suspendu, session révoquée ou caméra retirée : on coupe
                    t_verif = debut
                    if not a.comptes.session(jeton) or nom not in a.cameras_autorisees(a.comptes.compte(c["id"]) or {}):
                        break
                octets, ident = self._jpeg(nom, self.q.get("largeur"))
                if octets is not None and ident != dernier:
                    dernier = ident
                    personnes = next((x.get("personnes", 0) for x in a.fournisseur.cameras() if x["nom"] == nom), 0)
                    self.wfile.write(b"--fluxlite\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                     + str(len(octets)).encode() + b"\r\nX-Personnes: " + str(personnes).encode()
                                     + b"\r\n\r\n" + octets + b"\r\n")
                    self.wfile.flush()
                time.sleep(max(0.01, 1.0 / fps - (time.time() - debut)))
        finally:
            with a._flux_lock:
                a.flux_ouverts[c["id"]] = max(0, a.flux_ouverts.get(c["id"], 1) - 1)

    # --- journal ---------------------------------------------------------------------------------
    def journal(self, c):
        noms = self.appli.noms_autorises_journal(c)
        camera = nom_depuis_id(self.q["camera"]) if self.q.get("camera") else None
        lignes = self.appli.comptes.journal(noms, self.q.get("avant"), None, self.q.get("limite", 50), camera)
        for l_ in lignes:
            l_["camera_id"] = id_camera(l_["camera"])
            l_["prioritaire"], l_["photo"] = bool(l_["prioritaire"]), bool(l_["photo"])
        self.json({"journal": lignes, "dernier": self.appli.comptes.dernier_journal()})

    def photo(self, c, jid):
        r = self.appli.comptes.photo_journal(int(jid))
        if not r or not r["photo"] or r["camera"] not in self.appli.noms_autorises_journal(c):
            return self.erreur(404, "Photo introuvable.")
        self._envoyer(200, bytes(r["photo"]), "image/jpeg", {"Cache-Control": "private, max-age=86400"})

    def attente(self, c):
        """Attente longue (jusqu'à 50 s) des nouvelles alertes : utilisée par le service de notifications du
        téléphone. Renvoie les événements plus récents que « depuis »."""
        delai = max(0, min(50, int(self.q.get("delai", 40))))
        if "depuis" not in self.q:  # premier appel : on renvoie seulement le point de départ
            return self.json({"evenements": [], "dernier": self.appli.comptes.dernier_journal()})
        depuis = max(0, int(self.q["depuis"]))
        noms = self.appli.noms_autorises_journal(c)
        fin = time.time() + delai
        while True:
            lignes = self.appli.comptes.journal(noms, None, depuis, 50) if noms else []
            if lignes or time.time() >= fin or self.server.arret:
                break
            self.appli.attendre(max(depuis, self.appli._dernier_id), fin - time.time())
            if time.time() >= fin:
                lignes = self.appli.comptes.journal(noms, None, depuis, 50) if noms else []
                break
        for l_ in lignes:
            l_["camera_id"] = id_camera(l_["camera"])
            l_["prioritaire"], l_["photo"] = bool(l_["prioritaire"]), bool(l_["photo"])
        dernier = lignes[-1]["id"] if lignes else depuis
        self.json({"evenements": lignes, "dernier": dernier})
