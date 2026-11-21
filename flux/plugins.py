"""Plugins de Flux : format .fluxplug, vérification, chargement et gestion.

Format d'un fichier .fluxplug (binaire, lisible seulement par Flux) :

    b"FLUXPLUG" | version (1 octet) | longueur de l'en-tête (4 octets) | en-tête JSON
               | longueur de la signature (2 octets) | signature ECDSA P-256 (DER) | contenu chiffré

- l'en-tête (JSON, lisible) décrit le plugin : id, nom, version, éditeur, description, version minimale de Flux ;
- le contenu (une archive zip : plugin.py et ses fichiers) est chiffré en AES-256-GCM, l'en-tête servant de données
  authentifiées : on ne peut ni lire le code avec un outil ordinaire, ni changer le nom ou la version ;
- la signature (par la clé de l'éditeur) couvre l'en-tête et le contenu chiffré. Flux refuse tout plugin dont la
  signature n'est pas celle d'un éditeur de confiance : aujourd'hui DMS Security (la même clé que les mises à jour),
  plus tard des partenaires ajoutés dans flux/confiance_plugins.json.

La vraie protection est la SIGNATURE (personne ne peut fabriquer ou modifier un plugin) ; le chiffrement empêche la
lecture et la copie faciles du code, mais la clé de lecture est forcément dans Flux.

Le code d'un plugin n'est jamais écrit en clair sur le disque : il est déchiffré en mémoire et importé de là.
"""
import base64
import hashlib
import importlib.abc
import importlib.util
import io
import json
import os
import struct
import sys
import time
import traceback
import zipfile

from . import config

MAGIE = b"FLUXPLUG"
VERSION_FORMAT = 1
API = 1                                     # version de l'interface des plugins (flux/plugin_api.py)
EXTENSION = ".fluxplug"
DOSSIER = os.path.join(config.RACINE, "fluxlite", "plugins")
DOSSIER_DONNEES = os.path.join(DOSSIER, "donnees")
FICHIER_ETAT = os.path.join(DOSSIER, "etat.json")
FICHIER_CONFIANCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "confiance_plugins.json")
TAILLE_MAX = 30 * 1024 * 1024
# Clé de lecture (voir plus haut : le chiffrement protège de la lecture facile, la signature protège réellement)
_LECTURE = bytes.fromhex("8a1f3c6e27d94b05c3e8a7712bd06f94e15c2a8b73d0469f58b2e1c7a90d3f64")


class ErreurPlugin(Exception):
    pass


# ---------------------------------------------------------------------------------------------------------------
# Format
def _cle_contenu(ident):
    return hashlib.sha256(_LECTURE + b"|" + ident.encode("utf-8")).digest()


def _id_cle(spki):
    return hashlib.sha256(spki).hexdigest()[:16]


def editeurs_confiance():
    """[(nom, spki DER)] : la clé des mises à jour de Flux (DMS Security) et les partenaires autorisés."""
    sortie = []
    from . import nuage
    for c in nuage.cles_confiance():
        try:
            sortie.append(("DMS Security", base64.b64decode(c)))
        except ValueError:
            pass
    try:
        with open(FICHIER_CONFIANCE, encoding="utf-8") as f:
            for e in json.load(f).get("editeurs", []):
                try:
                    sortie.append((str(e["nom"]), base64.b64decode(e["cle"])))
                except (KeyError, ValueError, TypeError):
                    pass
    except (OSError, ValueError, AttributeError):
        pass
    return sortie


def construire(dossier_source, cle_privee_pem, sortie=None, editeur="DMS Security"):
    """Fabrique un .fluxplug à partir d'un dossier (plugin.json + plugin.py + autres fichiers). Renvoie le chemin."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    with open(os.path.join(dossier_source, "plugin.json"), encoding="utf-8") as f:
        info = json.load(f)
    for champ in ("id", "nom", "version"):
        if not str(info.get(champ, "")).strip():
            raise ErreurPlugin(f"plugin.json : champ « {champ} » manquant")
    if not all(c.isalnum() or c in "-_" for c in info["id"]):
        raise ErreurPlugin("plugin.json : l'id ne doit contenir que lettres, chiffres, - et _")
    if not os.path.isfile(os.path.join(dossier_source, "plugin.py")):
        raise ErreurPlugin("plugin.py manquant")
    k = serialization.load_pem_private_key(cle_privee_pem if isinstance(cle_privee_pem, bytes)
                                           else cle_privee_pem.encode(), password=None)
    spki = k.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as z:
        for racine, dossiers, fichiers in os.walk(dossier_source):
            dossiers[:] = sorted(d for d in dossiers if d not in ("__pycache__",) and not d.startswith("."))
            for nom in sorted(fichiers):
                if nom.endswith((".pyc",)) or nom.startswith("."):
                    continue
                chemin = os.path.join(racine, nom)
                z.write(chemin, os.path.relpath(chemin, dossier_source).replace(os.sep, "/"))
    entete = json.dumps({
        "format": VERSION_FORMAT, "api": int(info.get("api", API)), "id": info["id"], "nom": info["nom"],
        "version": str(info["version"]), "editeur": editeur, "cle": _id_cle(spki),
        "description": info.get("description", ""), "flux_min": info.get("flux_min", "0.13.0"),
        "icone": info.get("icone", "plugin"), "construit": int(time.time()),
    }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    nonce = os.urandom(12)
    chiffre = nonce + AESGCM(_cle_contenu(info["id"])).encrypt(nonce, tampon.getvalue(), entete)
    signature = k.sign(MAGIE + bytes([VERSION_FORMAT]) + entete + chiffre, ec.ECDSA(hashes.SHA256()))
    donnees = MAGIE + bytes([VERSION_FORMAT]) + struct.pack(">I", len(entete)) + entete \
        + struct.pack(">H", len(signature)) + signature + chiffre
    sortie = sortie or f"{info['id']}-{info['version']}{EXTENSION}"
    with open(sortie, "wb") as f:
        f.write(donnees)
    return sortie


def lire(donnees, editeurs=None):
    """Vérifie un .fluxplug (octets) et renvoie (en-tête, {chemin: octets}, nom de l'éditeur vérifié)."""
    from cryptography.exceptions import InvalidSignature, InvalidTag
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if len(donnees) > TAILLE_MAX:
        raise ErreurPlugin("fichier trop volumineux")
    if not donnees.startswith(MAGIE) or len(donnees) < 16:
        raise ErreurPlugin("ce n'est pas un plugin Flux (.fluxplug)")
    if donnees[8] != VERSION_FORMAT:
        raise ErreurPlugin("format de plugin trop récent : mettez Flux à jour")
    try:
        (n,) = struct.unpack(">I", donnees[9:13])
        entete = donnees[13:13 + n]
        (ns,) = struct.unpack(">H", donnees[13 + n:15 + n])
        signature = donnees[15 + n:15 + n + ns]
        chiffre = donnees[15 + n + ns:]
        info = json.loads(entete.decode("utf-8"))
    except (struct.error, ValueError, UnicodeDecodeError):
        raise ErreurPlugin("fichier de plugin abîmé") from None
    editeur = None
    for nom, spki in (editeurs if editeurs is not None else editeurs_confiance()):
        try:
            pub = serialization.load_der_public_key(spki)
            pub.verify(signature, MAGIE + bytes([VERSION_FORMAT]) + entete + chiffre, ec.ECDSA(hashes.SHA256()))
            editeur = nom
            break
        except (InvalidSignature, ValueError, TypeError):
            continue
    if editeur is None:
        raise ErreurPlugin("signature refusée : ce plugin ne vient pas d'un éditeur de confiance (ou il a été modifié)")
    if int(info.get("api", 1)) > API:
        raise ErreurPlugin(f"ce plugin demande une version plus récente de Flux ({info.get('flux_min', '?')})")
    try:
        brut = AESGCM(_cle_contenu(str(info["id"]))).decrypt(chiffre[:12], chiffre[12:], entete)
    except (InvalidTag, KeyError, ValueError):
        raise ErreurPlugin("contenu du plugin illisible") from None
    fichiers = {}
    with zipfile.ZipFile(io.BytesIO(brut)) as z:
        for nom in z.namelist():
            if nom.endswith("/") or ".." in nom.split("/") or nom.startswith("/"):
                continue
            fichiers[nom] = z.read(nom)
    if "plugin.py" not in fichiers:
        raise ErreurPlugin("plugin.py absent du plugin")
    return info, fichiers, editeur


def _version(v):
    try:
        return tuple(int(x) for x in str(v).split(".")[:3])
    except ValueError:
        return (0,)


# ---------------------------------------------------------------------------------------------------------------
# Import depuis la mémoire
class _Importeur(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Importe les modules d'un plugin depuis ses fichiers déchiffrés en mémoire (paquet fluxplugins.<id>)."""

    def __init__(self, paquet, fichiers):
        self.paquet = paquet
        self.fichiers = fichiers

    def _chemin(self, nom):
        if nom == self.paquet:
            return "__init__.py", True
        if not nom.startswith(self.paquet + "."):
            return None, False
        rel = nom[len(self.paquet) + 1:].replace(".", "/")
        if rel + ".py" in self.fichiers:
            return rel + ".py", False
        if rel + "/__init__.py" in self.fichiers:
            return rel + "/__init__.py", True
        return None, False

    def find_spec(self, nom, chemin=None, cible=None):
        f, paquet = self._chemin(nom)
        if f is None:
            return None
        return importlib.util.spec_from_loader(nom, self, is_package=paquet)

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        f, paquet = self._chemin(module.__name__)
        if paquet:
            module.__path__ = []
        source = self.fichiers.get(f, b"")
        module.__file__ = f"<plugin {self.paquet}>/{f}"
        exec(compile(source, module.__file__, "exec"), module.__dict__)  # noqa: S102 - code signé par l'éditeur


# ---------------------------------------------------------------------------------------------------------------
# Gestionnaire
class PluginCharge:
    def __init__(self, fichier, info, editeur):
        self.fichier = fichier
        self.info = info
        self.editeur = editeur
        self.objet = None
        self.erreur = ""
        self.importeur = None

    @property
    def id(self):
        return self.info["id"]


class Gestionnaire:
    """Installe, vérifie, charge et arrête les plugins. Un plugin qui plante ne fait jamais tomber Flux."""

    def __init__(self, fen=None):
        self.fen = fen
        self.plugins = {}     # id -> PluginCharge
        self.etat = self._lire_etat()
        self.rappels = []     # fonctions appelées quand la liste change (page Plugins)

    # --- état ---------------------------------------------------------------------------------------------
    def _lire_etat(self):
        try:
            with open(FICHIER_ETAT, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _sauver_etat(self):
        os.makedirs(DOSSIER, exist_ok=True)
        tmp = FICHIER_ETAT + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.etat, f, indent=2)
        os.replace(tmp, FICHIER_ETAT)

    def actif(self, ident):
        return self.etat.get(ident, {}).get("actif", True)

    def _signaler(self):
        for r in list(self.rappels):
            try:
                r()
            except Exception:  # noqa: BLE001
                pass

    def _log(self, texte, niveau="info"):
        if self.fen is not None and hasattr(self.fen, "log_systeme"):
            self.fen.log_systeme(f"Plugins : {texte}", niveau)
        else:
            print(f"[Flux] Plugins : {texte}", flush=True)

    # --- chargement ---------------------------------------------------------------------------------------
    def charger_tous(self):
        if not os.path.isdir(DOSSIER):
            return
        for nom in sorted(os.listdir(DOSSIER)):
            if nom.endswith(EXTENSION):
                try:
                    self._charger_fichier(os.path.join(DOSSIER, nom))
                except ErreurPlugin as e:
                    self._log(f"{nom} refusé : {e}", "erreur")
        self._signaler()

    def _charger_fichier(self, chemin):
        with open(chemin, "rb") as f:
            info, fichiers, editeur = lire(f.read())
        if _version(info.get("flux_min", "0")) > _version(config.APP_VERSION):
            raise ErreurPlugin(f"demande Flux {info['flux_min']} ou plus récent")
        if info["id"] in self.plugins:
            self.arreter(info["id"])
        p = PluginCharge(chemin, info, editeur)
        p.fichiers = fichiers
        self.plugins[p.id] = p
        if self.actif(p.id):
            self.demarrer(p.id)
        return p

    def demarrer(self, ident):
        p = self.plugins[ident]
        if p.objet is not None:
            return
        from .plugin_api import Contexte
        paquet = "fluxplugins." + ident.replace("-", "_")
        if "fluxplugins" not in sys.modules:
            racine = importlib.util.module_from_spec(importlib.util.spec_from_loader("fluxplugins", loader=None,
                                                                                     is_package=True))
            racine.__path__ = []
            sys.modules["fluxplugins"] = racine
        for nom in [m for m in sys.modules if m == paquet or m.startswith(paquet + ".")]:
            del sys.modules[nom]
        if p.importeur in sys.meta_path:
            sys.meta_path.remove(p.importeur)
        fichiers = dict(p.fichiers)
        fichiers.setdefault("__init__.py", b"")
        p.importeur = _Importeur(paquet, fichiers)
        sys.meta_path.insert(0, p.importeur)
        try:
            module = importlib.import_module(paquet + ".plugin")
            p.objet = module.Plugin(Contexte(self, p))
            p.objet.demarrer()
            p.erreur = ""
            self._log(f"« {p.info['nom']} » {p.info['version']} démarré ({p.editeur})", "ok")
        except Exception as e:  # noqa: BLE001 - un plugin défaillant est mis de côté
            p.objet = None
            p.erreur = f"{type(e).__name__} : {e}"
            self._log(f"« {p.info['nom']} » n'a pas pu démarrer : {p.erreur}", "erreur")
            traceback.print_exc()

    def arreter(self, ident):
        p = self.plugins.get(ident)
        if p is None or p.objet is None:
            return
        try:
            p.objet.arreter()
        except Exception as e:  # noqa: BLE001
            self._log(f"« {p.info['nom']} » : erreur à l'arrêt ({e})", "erreur")
        p.objet = None

    def arreter_tous(self):
        for ident in list(self.plugins):
            self.arreter(ident)

    # --- gestion ------------------------------------------------------------------------------------------
    def installer(self, chemin_source):
        """Vérifie puis installe (ou met à jour) un .fluxplug. Renvoie l'en-tête du plugin."""
        with open(chemin_source, "rb") as f:
            donnees = f.read()
        info, _fichiers, _editeur = lire(donnees)  # refuse avant de copier quoi que ce soit
        if _version(info.get("flux_min", "0")) > _version(config.APP_VERSION):
            raise ErreurPlugin(f"ce plugin demande Flux {info['flux_min']} ou plus récent")
        os.makedirs(DOSSIER, exist_ok=True)
        ancien = self.plugins.get(info["id"])
        if ancien is not None:
            self.arreter(info["id"])
            if os.path.abspath(ancien.fichier) != os.path.abspath(os.path.join(DOSSIER, info["id"] + EXTENSION)):
                try:
                    os.remove(ancien.fichier)
                except OSError:
                    pass
        cible = os.path.join(DOSSIER, info["id"] + EXTENSION)
        tmp = cible + ".tmp"
        with open(tmp, "wb") as f:
            f.write(donnees)
        os.replace(tmp, cible)
        self.etat.setdefault(info["id"], {})["actif"] = True
        self._sauver_etat()
        self._charger_fichier(cible)
        self._signaler()
        return info

    def activer(self, ident, actif):
        self.etat.setdefault(ident, {})["actif"] = bool(actif)
        self._sauver_etat()
        if actif:
            self.demarrer(ident)
        else:
            self.arreter(ident)
        self._signaler()

    def desinstaller(self, ident, garder_donnees=True):
        p = self.plugins.pop(ident, None)
        if p is None:
            return
        if p.objet is not None:
            try:
                p.objet.arreter()
            except Exception:  # noqa: BLE001
                pass
        if p.importeur in sys.meta_path:
            sys.meta_path.remove(p.importeur)
        try:
            os.remove(p.fichier)
        except OSError:
            pass
        if not garder_donnees:
            try:
                os.remove(os.path.join(DOSSIER_DONNEES, ident + ".json"))
            except OSError:
                pass
        self.etat.pop(ident, None)
        self._sauver_etat()
        self._signaler()

    # --- catalogue du serveur Flux --------------------------------------------------------------------------
    def catalogue(self, cfg):
        """Plugins proposés par le serveur Flux : [{id, nom, version, description, fichier, taille}]."""
        import urllib.request
        from . import nuage
        base = nuage.adresse(cfg)
        if not base:
            raise ErreurPlugin("aucun serveur Flux configuré")
        try:
            with urllib.request.urlopen(urllib.request.Request(base + "/api/maj/fichiers/plugins.json",
                                                               headers={"User-Agent": "Flux-plugins"}), timeout=20) as r:
                d = json.loads(r.read(1024 * 1024).decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            if "404" in str(e):
                return []
            raise ErreurPlugin(f"catalogue indisponible ({e})") from None
        sortie = []
        for p in d.get("plugins", []) if isinstance(d, dict) else []:
            if isinstance(p, dict) and str(p.get("fichier", "")).endswith(EXTENSION) and "/" not in p["fichier"]:
                sortie.append(p)
        return sortie

    def telecharger(self, cfg, entree):
        """Télécharge un plugin du catalogue dans un fichier temporaire (vérifié ensuite par installer())."""
        import tempfile
        import urllib.request
        from . import nuage
        with urllib.request.urlopen(urllib.request.Request(f"{nuage.adresse(cfg)}/api/maj/fichiers/{entree['fichier']}",
                                                           headers={"User-Agent": "Flux-plugins"}), timeout=120) as r:
            donnees = r.read(TAILLE_MAX + 1)
        fd, chemin = tempfile.mkstemp(suffix=EXTENSION)
        with os.fdopen(fd, "wb") as f:
            f.write(donnees)
        return chemin

    def plus_recent(self, entree):
        p = self.plugins.get(entree.get("id"))
        return p is None or _version(entree.get("version")) > _version(p.info.get("version"))

    # --- crochets appelés par Flux ------------------------------------------------------------------------
    def filtrer(self, e):
        """Chaque événement passe par les plugins actifs avant le journal, les alertes et la télésurveillance.
        Un plugin peut le modifier ou le supprimer (None)."""
        for p in list(self.plugins.values()):
            if p.objet is None:
                continue
            try:
                e = p.objet.filtrer(e)
            except Exception as ex:  # noqa: BLE001
                self._log(f"« {p.info['nom']} » : erreur sur un événement ({ex})", "erreur")
            if e is None:
                return None
        return e

    def pages(self):
        """[(id du plugin, titre, widget)] des plugins actifs."""
        sortie = []
        for p in self.plugins.values():
            if p.objet is None:
                continue
            try:
                for titre, w in p.objet.pages():
                    sortie.append((p.id, titre, w))
            except Exception as ex:  # noqa: BLE001
                self._log(f"« {p.info['nom']} » : page indisponible ({ex})", "erreur")
        return sortie
