"""Coffre à secrets : mots de passe et clés enregistrés chiffrés sur le disque (AES-256-GCM).

La clé du coffre est créée au premier usage dans le dossier protégé de Flux (conservé par les mises à jour) :
- Windows : elle est elle-même protégée par le système (DPAPI, liée au compte Windows) ;
- Linux et macOS : fichier lisible par ce compte seulement (droits 600).
Un fichier de configuration copié ailleurs ne livre donc aucun mot de passe en clair.
"""
import base64
import os
import secrets
import sys

from .config import RACINE

DOSSIER = os.path.join(RACINE, "fluxlite")
FICHIER_CLE = os.path.join(DOSSIER, "coffre.cle")
PREFIXE = "coffre1:"

_cle = None


def _dpapi(donnees, proteger):
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    tampon = ctypes.create_string_buffer(donnees, len(donnees))
    entree = BLOB(len(donnees), tampon)
    sortie = BLOB()
    crypt32 = ctypes.windll.crypt32
    f = crypt32.CryptProtectData if proteger else crypt32.CryptUnprotectData
    if not f(ctypes.byref(entree), None, None, None, None, 0x01, ctypes.byref(sortie)):  # 0x01 : sans interface
        raise OSError("DPAPI indisponible")
    try:
        return ctypes.string_at(sortie.pbData, sortie.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(sortie.pbData)


def _lire_cle():
    with open(FICHIER_CLE, "rb") as f:
        brut = f.read()
    if brut.startswith(b"dpapi:"):
        return _dpapi(base64.b64decode(brut[6:]), False)
    return base64.b64decode(brut)


def _creer_cle():
    cle = secrets.token_bytes(32)
    os.makedirs(DOSSIER, exist_ok=True)
    contenu = base64.b64encode(cle)
    if sys.platform.startswith("win"):
        try:
            contenu = b"dpapi:" + base64.b64encode(_dpapi(cle, True))
        except OSError:
            pass
    tmp = FICHIER_CLE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(contenu)
    os.replace(tmp, FICHIER_CLE)
    return cle


def cle():
    global _cle
    if _cle is None:
        try:
            _cle = _lire_cle()
        except (OSError, ValueError):
            _cle = _creer_cle()
    return _cle


def chiffrer(texte, contexte="flux"):
    """Texte -> « coffre1:… » (vide reste vide)."""
    if not texte:
        return ""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    iv = secrets.token_bytes(12)
    c = AESGCM(cle()).encrypt(iv, texte.encode(), contexte.encode())
    return PREFIXE + base64.urlsafe_b64encode(iv + c).decode()


def dechiffrer(valeur, contexte="flux"):
    """« coffre1:… » -> texte. Une valeur illisible (clé perdue, fichier copié d'un autre PC) donne ""."""
    if not valeur:
        return ""
    if not valeur.startswith(PREFIXE):
        return valeur  # ancienne valeur en clair : acceptée, rechiffrée au prochain enregistrement
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    try:
        brut = base64.urlsafe_b64decode(valeur[len(PREFIXE):])
        return AESGCM(cle()).decrypt(brut[:12], brut[12:], contexte.encode()).decode()
    except (InvalidTag, ValueError):
        return ""
