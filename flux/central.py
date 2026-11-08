"""Supervision centrale : relie ce PC à une console Flux Central (programme mère).

- Inscription avec l'adresse de la console et un code à usage unique (créé dans la console).
- Toutes les 30 s (réglable dans la console) : état technique de ce PC (caméras, détection, disque, version).
- Alertes, actions et vidéos : type, caméra et heure seulement ; le texte n'est envoyé que si la console le
  demande. Jamais de photo, de visage ni de plaque.
- Commandes de la console (détection, niveau, plage horaire, caméras…) : mêmes vérifications que le pilotage
  depuis FluxLite, inscrites au journal.
- Licence : signée par la console, vérifiée ici avec la clé reçue à l'inscription.
Chaque requête est signée (HMAC-SHA256, horodatage, nonce) : impossible à rejouer ou à falsifier.
"""
import base64
import hashlib
import hmac
import json
import os
import platform
import queue
import secrets
import ssl
import threading
import time
import urllib.error
import urllib.request

from .config import APP_VERSION, RACINE

FICHIER = os.path.join(RACINE, "fluxlite", "central.json")  # dossier protégé, conservé par les mises à jour
COMMANDES = {"detection.actif", "detection.niveau", "horaire", "notif.actif", "mail.actif", "notif.delai",
             "mail.delai", "camera.detection", "camera.marche", "camera.clip"}
INTERVALLE_DISQUE = 300


def b64url(o):
    return base64.urlsafe_b64encode(o).rstrip(b"=").decode()


def deb64url(t):
    return base64.urlsafe_b64decode(t + "=" * (-len(t) % 4))


class ErreurCentrale(Exception):
    pass


def adresse_valide(adresse):
    a = (adresse or "").strip().rstrip("/")
    if a.startswith("https://"):
        return a
    hote = a.split("://", 1)[-1].split("/")[0].split(":")[0]
    if a.startswith("http://") and hote in ("localhost", "127.0.0.1"):  # essais en local uniquement
        return a
    raise ErreurCentrale("L'adresse de la console doit commencer par https://")


def lire_identifiants():
    try:
        with open(FICHIER, encoding="utf-8") as f:
            d = json.load(f)
        return d if d.get("serveur") and d.get("secret") else None
    except (OSError, ValueError):
        return None


def ecrire_identifiants(d):
    os.makedirs(os.path.dirname(FICHIER), exist_ok=True)
    tmp = FICHIER + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # lisible par ce compte seulement
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(d, f)
    os.replace(tmp, FICHIER)


def effacer_identifiants():
    try:
        os.remove(FICHIER)
    except OSError:
        pass


def _requete(url, corps, entetes=None, delai=15):
    donnees = json.dumps(corps).encode()
    h = {"Content-Type": "application/json", "User-Agent": f"Flux/{APP_VERSION}"}
    h.update(entetes or {})
    req = urllib.request.Request(url, data=donnees, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=delai, context=ssl.create_default_context()) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            d = json.loads(e.read().decode())
        except ValueError:
            d = {}
        err = ErreurCentrale(d.get("erreur") or f"erreur {e.code}")
        err.code = d.get("code")
        err.statut = e.code
        raise err from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise ErreurCentrale(f"console injoignable ({getattr(e, 'reason', e)})") from None


def inscrire(adresse, code):
    """Échange le code contre les identifiants de ce PC. Renvoie le nom de l'organisation."""
    a = adresse_valide(adresse)
    d = _requete(f"{a}/api/agent/inscription", {"code": code.strip(), "version": APP_VERSION,
                                                "machine": platform.node()[:60]})
    if not d.get("serveur") or not d.get("secret") or not d.get("cle_licence"):
        raise ErreurCentrale("réponse inattendue de la console")
    ecrire_identifiants({"adresse": a, "serveur": d["serveur"], "secret": d["secret"], "nom": d.get("nom", ""),
                         "organisation": d.get("organisation", ""), "cle_licence": d["cle_licence"],
                         "intervalle": d.get("intervalle", 30), "inscrit_le": time.time()})
    return d


def verifier_licence(cle_publique_b64, licence):
    """Vérifie la signature ECDSA P-256 (r||s) de la console. Renvoie les données de licence ou None."""
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
        cle = serialization.load_der_public_key(deb64url(cle_publique_b64))
        sig = deb64url(licence["signature"])
        if len(sig) != 64:
            return None
        der = encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big"))
        cle.verify(der, licence["donnees"].encode(), ec.ECDSA(hashes.SHA256()))
        return json.loads(licence["donnees"])
    except (InvalidSignature, KeyError, TypeError, ValueError):
        return None
    except ImportError:
        return None


class AgentCentral:
    """Fil de fond qui parle à la console. Tout ce qui touche l'interface passe par le pilote (fil principal)."""

    def __init__(self, fen):
        self.fen = fen
        self.cfg = fen.cfg
        self.ids = lire_identifiants()
        self.file = queue.Queue(maxsize=2000)
        self.resultats = []
        self.etat = "inactif"       # inactif, connecte, erreur
        self.message = ""
        self.dernier_contact = None
        self.licence = None
        self.licence_ok = None
        self.details = "minimal"
        self._disque = (0.0, None)
        self._arret = threading.Event()
        self._reveil = threading.Event()
        self._fil = None
        self.demarre_le = time.time()

    # --- cycle de vie --------------------------------------------------------------------------
    def demarrer(self):
        if self._fil is not None and self._fil.is_alive():
            self._reveil.set()
            return
        self._arret.clear()
        self._fil = threading.Thread(target=self._boucle, name="flux-central", daemon=True)
        self._fil.start()

    def arreter(self):
        self._arret.set()
        self._reveil.set()

    def relie(self):
        return self.ids is not None

    def relier(self, adresse, code):
        d = inscrire(adresse, code)
        self.ids = lire_identifiants()
        self.etat, self.message = "connecte", "Relié, premier contact en cours…"
        self.demarrer()
        return d

    def delier(self):
        effacer_identifiants()
        self.ids = None
        self.etat, self.message, self.licence, self.licence_ok = "inactif", "", None, None

    def actif(self):
        return self.ids is not None and bool(self.cfg.get("central.actif"))

    # --- événements (fil de l'interface) -------------------------------------------------------
    def evenement(self, e):
        if not self.actif() or e.get("niveau") not in ("alerte", "action", "video"):
            return
        if e.get("source") in (None, "", "Système", "FluxLite"):
            return
        ev = {"ref": secrets.token_hex(12), "heure": time.time(), "niveau": e["niveau"],
              "camera": str(e.get("source") or "")[:120], "prioritaire": bool(e.get("prioritaire")),
              "texte": str(e.get("texte") or "")[:300]}
        try:
            self.file.put_nowait(ev)
        except queue.Full:  # console injoignable depuis longtemps : les plus anciens sont abandonnés
            try:
                self.file.get_nowait()
                self.file.put_nowait(ev)
            except (queue.Empty, queue.Full):
                pass

    # --- échanges signés -----------------------------------------------------------------------
    def _signe(self, chemin, corps):
        ids = self.ids
        brut = json.dumps(corps).encode()
        ts, nonce = str(int(time.time())), secrets.token_urlsafe(18)
        empreinte = b64url(hashlib.sha256(brut).digest())
        msg = f"POST\n{chemin}\n{ts}\n{nonce}\n{empreinte}".encode()
        sig = b64url(hmac.new(deb64url(ids["secret"]), msg, hashlib.sha256).digest())
        req = urllib.request.Request(ids["adresse"] + chemin, data=brut, method="POST", headers={
            "Content-Type": "application/json", "User-Agent": f"Flux/{APP_VERSION}", "X-FC-Serveur": str(ids["serveur"]),
            "X-FC-Horodatage": ts, "X-FC-Nonce": nonce, "X-FC-Signature": sig})
        try:
            with urllib.request.urlopen(req, timeout=20, context=ssl.create_default_context()) as r:
                return json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            try:
                d = json.loads(e.read().decode())
            except ValueError:
                d = {}
            err = ErreurCentrale(d.get("erreur") or f"erreur {e.code}")
            err.code = d.get("code")
            raise err from None
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise ErreurCentrale(f"console injoignable ({getattr(e, 'reason', e)})") from None

    def _dans_interface(self, f):
        """Exécute f() dans le fil de l'interface (via le pilote de FluxLite) et renvoie son résultat."""
        return self.fen.page_mobile.pilote.demander("executer", f=f)

    def _collecter(self):
        """Fil de l'interface : état des caméras et réglages pilotables."""
        pm = self.fen.page_mobile
        pm.fournisseur.publier(force=True)
        pages = {p.nom: p for p in self.fen.page_cameras.pages}
        base = pm.pilote.etat(list(pages))
        en_direct = {c["nom"]: c for c in pm.fournisseur.cameras()}
        cams = []
        for c in base["cameras"]:
            d = en_direct.get(c["nom"], {})
            cams.append({"nom": c["nom"], "detection": c["detection"], "en_marche": c["en_marche"],
                         "etat": d.get("etat", "arret"), "personnes": d.get("personnes", 0), "fps": d.get("fps") or None})
        base["cameras"] = cams
        return base

    def _disque_info(self):
        t, d = self._disque
        if d is None or time.time() - t > INTERVALLE_DISQUE:
            try:
                from . import stockage
                e = stockage.etat(self.cfg.dossier_sortie(), self.fen.chemins_bases())
                limite = float(self.cfg.get("stockage.limite") or 0) * 1e9
                d = {"utilise": e.get("total"), "limite": limite or None, "libre": e.get("libre"), "total": None}
            except Exception:  # noqa: BLE001
                d = None
            self._disque = (time.time(), d)
        return d

    def _executer(self, c):
        from . import mobile_serveur as ms
        cle = c.get("cle")
        if cle not in COMMANDES:
            raise ms.ErreurServeur("commande non autorisée sur ce PC")
        valeur = c.get("valeur") if cle.startswith("camera.") else ms.valeur_pilotage(cle, c.get("valeur"))
        if cle.startswith("camera.") and not isinstance(valeur, bool):
            raise ms.ErreurServeur("valeur invalide")
        self.fen.page_mobile.pilote.demander("regler", cle=cle, valeur=valeur, camera=c.get("camera"),
                                             auteur="Flux Central", cameras=[])

    def _battement(self):
        try:
            etat = self._dans_interface(self._collecter)
        except Exception as e:  # noqa: BLE001 — fenêtre occupée : état minimal
            etat = {"cameras": [], "erreur_etat": str(e)[:100]}
        etat.update({"version": APP_VERSION, "demarre_le": self.demarre_le, "systeme": f"{platform.system()} {platform.release()}"[:80],
                     "disque": self._disque_info(), "licence_ok": self.licence_ok, "resultats": self.resultats[:50]})
        r = self._signe("/api/agent/battement", etat)
        self.resultats = self.resultats[50:]
        self.details = "texte" if r.get("details") == "texte" else "minimal"
        if r.get("licence"):
            donnees = verifier_licence(self.ids["cle_licence"], r["licence"])
            self.licence_ok = donnees is not None and donnees.get("serveur") == self.ids["serveur"]
            self.licence = donnees if self.licence_ok else None
        for c in r.get("commandes") or []:
            try:
                self._executer(c)
                self.resultats.append({"id": c.get("id"), "ok": True, "message": "Appliquée"})
            except Exception as e:  # noqa: BLE001
                self.resultats.append({"id": c.get("id"), "ok": False, "message": str(e)[:200]})
        if r.get("commandes"):
            self._reveil.set()  # renvoyer les résultats sans attendre l'intervalle complet
        try:
            inter = int(r.get("intervalle") or 30)
        except (TypeError, ValueError):
            inter = 30
        return max(10, min(600, inter))

    def _envoyer_evenements(self):
        lot = []
        while len(lot) < 200:
            try:
                lot.append(self.file.get_nowait())
            except queue.Empty:
                break
        if not lot:
            return
        if self.details != "texte":
            for e in lot:
                e.pop("texte", None)
        try:
            self._signe("/api/agent/evenements", {"evenements": lot})
        except ErreurCentrale:
            for e in lot:  # renvoyés au prochain essai (la console ignore les doublons)
                try:
                    self.file.put_nowait(e)
                except queue.Full:
                    break
            raise

    def _boucle(self):
        attente = 1
        erreurs = 0
        while not self._arret.is_set():
            self._reveil.wait(attente)
            self._reveil.clear()
            if self._arret.is_set():
                break
            if not self.actif():
                self.etat = "inactif"
                attente = 5
                continue
            try:
                attente = self._battement()
                self._envoyer_evenements()
                if self.etat != "connecte" or erreurs:
                    self.fen.log_systeme("Supervision centrale : connecté à la console.", "ok")
                self.etat, self.message, self.dernier_contact, erreurs = "connecte", "", time.time(), 0
            except ErreurCentrale as e:
                erreurs += 1
                code = getattr(e, "code", None)
                if code == "revoque":
                    self.fen.log_systeme("Supervision centrale : ce PC a été retiré de la console.", "erreur")
                    self.delier()
                    continue
                if erreurs == 1:
                    self.fen.log_systeme(f"Supervision centrale : {e}", "erreur")
                self.etat, self.message = "erreur", str(e)
                attente = min(300, 15 * erreurs)
            except Exception as e:  # noqa: BLE001
                self.etat, self.message = "erreur", f"erreur interne ({e})"
                attente = 60

    def texte_etat(self):
        if not self.ids:
            return "Non relié à une console."
        base = f"Relié à « {self.ids.get('organisation', '')} » ({self.ids.get('adresse', '')}) sous le nom « {self.ids.get('nom', '')} »."
        if not self.cfg.get("central.actif"):
            return base + " Envoi en pause."
        if self.etat == "erreur":
            return base + f" Dernier essai : {self.message}"
        if self.dernier_contact:
            s = int(time.time() - self.dernier_contact)
            base += f" Dernier contact il y a {s} s."
        if self.licence_ok and self.licence:
            exp = self.licence.get("expire_le")
            fin = time.strftime("%d/%m/%Y", time.localtime(exp)) if exp else "sans limite"
            base += f" Licence {self.licence.get('formule')} vérifiée ({self.licence.get('cameras_max')} caméras, {fin})."
        elif self.licence_ok is False:
            base += " Licence : signature invalide."
        return base
