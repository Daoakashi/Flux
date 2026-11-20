"""Serveur Flux sur Cloudflare (Flux Central) : adresse, manifeste des versions signé, relais 4G.

Adresse du serveur, par ordre de priorité :
  1. Réglages › Mises à jour › Adresse du serveur Flux (choisie à la main) ;
  2. l'adresse annoncée par le serveur lui-même dans un manifeste SIGNÉ (déménagement vers un nom de domaine : les PC
     suivent tout seuls, sans mise à jour ni réglage) ;
  3. l'adresse livrée avec Flux (version.json, écrite par le bouton « Publier une version »).

Le manifeste est signé par la publication (GitHub Actions) avec une clé ECDSA P-256 dont seule la partie publique est
livrée avec Flux (flux/confiance_maj.json). Un serveur piraté ne peut donc ni proposer une fausse version, ni rediriger
Flux ailleurs ; un vieux manifeste rejoué est refusé (date d'émission jamais en recul).
"""
import base64
import json
import os
import re
import time
import urllib.error
import urllib.request

from . import config

DOSSIER = os.path.join(config.RACINE, "fluxlite")
FICHIER = os.path.join(DOSSIER, "nuage.json")            # dernière adresse annoncée et date du dernier manifeste
FICHIER_CONFIANCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "confiance_maj.json")


class ErreurNuage(Exception):
    pass


def normaliser(texte):
    """« flux.exemple.be », « https://x.workers.dev/ » -> « https://flux.exemple.be ». http seulement en local."""
    t = str(texte or "").strip().rstrip("/")
    if not t:
        return ""
    if "://" not in t:
        t = "https://" + t
    m = re.fullmatch(r"(https?)://([A-Za-z0-9.\-]+|\[[0-9A-Fa-f:]+\])(:\d{1,5})?", t)
    if not m:
        return ""
    if m.group(1) == "http" and m.group(2) not in ("localhost", "127.0.0.1", "[::1]"):
        return ""  # jamais de mise à jour en clair sur Internet
    return t


def _etat():
    try:
        with open(FICHIER, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _ecrire_etat(d):
    os.makedirs(DOSSIER, exist_ok=True)
    tmp = FICHIER + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f)
    os.replace(tmp, FICHIER)


def adresse(cfg):
    manuelle = normaliser(cfg.get("maj.nuage") if cfg is not None else "")
    if manuelle:
        return manuelle
    annoncee = normaliser(_etat().get("adresse"))
    if annoncee:
        return annoncee
    return normaliser(config.lire_version().get("nuage"))


def adresse_relais(cfg):
    """Adresse du relais 4G de ce serveur (wss://…), ou "" sans serveur Flux."""
    a = adresse(cfg)
    if not a:
        return ""
    return ("ws://" + a[7:]) if a.startswith("http://") else ("wss://" + a[8:])


def cles_confiance():
    """Clés publiques (SPKI DER, base64) qui peuvent signer les manifestes."""
    try:
        with open(FICHIER_CONFIANCE, encoding="utf-8") as f:
            d = json.load(f)
        return [c for c in d.get("cles", []) if isinstance(c, str) and c.strip()]
    except (OSError, ValueError, AttributeError):
        return []


def disponible(cfg):
    return bool(adresse(cfg)) and bool(cles_confiance())


def verifier_signature(texte, signature_b64, cles=None):
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except ValueError:
        return False
    for c in cles if cles is not None else cles_confiance():
        try:
            pub = serialization.load_der_public_key(base64.b64decode(c))
            if not isinstance(pub, ec.EllipticCurvePublicKey):
                continue
            pub.verify(signature, texte.encode("utf-8"), ec.ECDSA(hashes.SHA256()))
            return True
        except (InvalidSignature, ValueError):
            continue
    return False


def _get(url, delai=20):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Flux-mises-a-jour"}),
                                    timeout=delai) as r:
            return r.read(2 * 1024 * 1024)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise ErreurNuage("aucune version publiée sur le serveur Flux") from None
        raise ErreurNuage(f"le serveur Flux a répondu {e.code}") from None
    except urllib.error.URLError as e:
        raise ErreurNuage(f"serveur Flux injoignable ({e.reason})") from None
    except (TimeoutError, OSError) as e:
        raise ErreurNuage(f"serveur Flux injoignable ({e})") from None


def lire_manifeste(cfg):
    """Télécharge et vérifie le manifeste. Renvoie (dict, adresse du serveur)."""
    base = adresse(cfg)
    if not base:
        raise ErreurNuage("aucun serveur Flux configuré")
    cles = cles_confiance()
    if not cles:
        raise ErreurNuage("cette copie de Flux ne contient pas la clé de vérification des mises à jour")
    try:
        enveloppe = json.loads(_get(base + "/api/maj/manifeste").decode("utf-8"))
        texte, signature = enveloppe["manifeste"], enveloppe["signature"]
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        raise ErreurNuage("réponse illisible du serveur Flux") from None
    if not verifier_signature(texte, signature, cles):
        raise ErreurNuage("signature du manifeste INVALIDE : rien n'est installé depuis ce serveur")
    try:
        m = json.loads(texte)
        emis = float(m.get("emis", 0))
        if not isinstance(m.get("versions"), list):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ErreurNuage("manifeste illisible") from None
    etat = _etat()
    if emis + 60 < float(etat.get("emis", 0)):
        raise ErreurNuage("manifeste plus ancien que le dernier reçu (rejeu refusé)")
    etat["emis"] = max(emis, float(etat.get("emis", 0)))
    nouvelle = normaliser(m.get("nuage"))
    if nouvelle and nouvelle != etat.get("adresse"):
        etat["adresse"] = nouvelle  # le serveur a déménagé : signé, donc fiable
    etat["vu"] = time.time()
    try:
        _ecrire_etat(etat)
    except OSError:
        pass
    return m, base


def candidates(cfg, plateforme):
    """Versions du manifeste pour ce système : liste de dicts au format de mise_a_jour.verifier."""
    m, base = lire_manifeste(cfg)
    sortie = []
    for v in m["versions"]:
        if not isinstance(v, dict):
            continue
        f = (v.get("fichiers") or {}).get(plateforme)
        if not isinstance(f, dict) or not re.fullmatch(r"[0-9a-fA-F]{64}", str(f.get("sha256", ""))):
            continue
        nom = str(f.get("nom", ""))
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.zip", nom):
            continue
        sortie.append({"version": str(v.get("version", "")), "canal": str(v.get("canal", "")),
                       "titre": str(v.get("titre") or ""), "notes": str(v.get("notes") or ""),
                       "date": str(v.get("date") or ""), "archive": f"{base}/api/maj/fichiers/{nom}",
                       "archive_nom": nom, "sha256": f["sha256"].lower(), "taille": int(f.get("taille") or 0),
                       "page": str(v.get("page") or base)})
    return sortie
