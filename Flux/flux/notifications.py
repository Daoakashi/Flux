"""Notifications vers le téléphone et les messageries : Telegram, WhatsApp (CallMeBot ou Twilio), SMS et appel
(Twilio), notification push (ntfy), Discord et webhook générique.

Uniquement la bibliothèque standard (urllib) : rien à installer. Les envois partent d'un fil dédié pour ne jamais
ralentir les caméras ni l'interface.
"""

import base64
import json
import queue
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from xml.sax.saxutils import escape

DELAI_RESEAU = 20
CANAUX = [("telegram", "Telegram"), ("whatsapp", "WhatsApp"), ("sms", "SMS"), ("appel", "Appel"),
          ("ntfy", "Push (ntfy)"), ("discord", "Discord"), ("webhook", "Webhook")]
NOMS_CANAUX = dict(CANAUX)


class ErreurNotification(Exception):
    pass


def numeros(texte):
    return [n.strip().replace(" ", "") for n in str(texte or "").replace(";", ",").split(",") if n.strip()]


def _requete(url, donnees=None, entetes=None, methode=None, delai=DELAI_RESEAU):
    """Envoie une requête HTTP et renvoie le corps (texte). Lève ErreurNotification avec un message lisible."""
    req = urllib.request.Request(url, data=donnees, headers=entetes or {}, method=methode)
    req.add_header("User-Agent", "Flux-surveillance")
    try:
        with urllib.request.urlopen(req, timeout=delai) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        corps = e.read().decode("utf-8", "replace")[:300]
        try:
            j = json.loads(corps)
            corps = j.get("description") or j.get("message") or j.get("error") or corps
        except ValueError:
            pass
        raise ErreurNotification(f"HTTP {e.code} : {corps.strip() or e.reason}") from None
    except urllib.error.URLError as e:
        raise ErreurNotification(f"connexion impossible ({e.reason})") from None
    except TimeoutError:
        raise ErreurNotification("pas de réponse du serveur") from None


def _multipart(champs, fichiers):
    """Corps multipart/form-data. fichiers : [(champ, nom_fichier, octets, type_mime)]."""
    limite = uuid.uuid4().hex
    corps = bytearray()
    for k, v in champs.items():
        corps += (f"--{limite}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode("utf-8")
    for champ, nom, octets, mime in fichiers:
        corps += (f"--{limite}\r\nContent-Disposition: form-data; name=\"{champ}\"; filename=\"{nom}\"\r\n"
                  f"Content-Type: {mime}\r\n\r\n").encode("utf-8")
        corps += octets + b"\r\n"
    corps += f"--{limite}--\r\n".encode()
    return bytes(corps), f"multipart/form-data; boundary={limite}"


def _entete_utf8(texte):
    """Valeur d'en-tête HTTP sûre pour les accents (RFC 2047, compris par ntfy)."""
    try:
        texte.encode("ascii")
        return texte
    except UnicodeEncodeError:
        return "=?UTF-8?B?" + base64.b64encode(texte.encode("utf-8")).decode() + "?="


# ---------------------------------------------------------------------------
# Canaux
# ---------------------------------------------------------------------------
API_TELEGRAM = "https://api.telegram.org"
API_TWILIO = "https://api.twilio.com"
API_CALLMEBOT = "https://api.callmebot.com"


def telegram(cfg, titre, texte, photo=None):
    jeton, chat = cfg.get("telegram.jeton").strip(), cfg.get("telegram.chat").strip()
    if not jeton or not chat:
        raise ErreurNotification("jeton du bot ou identifiant de discussion manquant")
    message = f"{titre}\n{texte}".strip()
    if photo:
        corps, type_ = _multipart({"chat_id": chat, "caption": message[:1000]},
                                  [("photo", "alerte.jpg", photo, "image/jpeg")])
        _requete(f"{API_TELEGRAM}/bot{jeton}/sendPhoto", corps, {"Content-Type": type_})
    else:
        donnees = urllib.parse.urlencode({"chat_id": chat, "text": message[:4000]}).encode()
        _requete(f"{API_TELEGRAM}/bot{jeton}/sendMessage", donnees,
                 {"Content-Type": "application/x-www-form-urlencoded"})


def telegram_trouver_chat(jeton):
    """Renvoie [(identifiant, nom)] des discussions qui ont écrit récemment au bot."""
    if not jeton.strip():
        raise ErreurNotification("indiquez d'abord le jeton du bot")
    rep = json.loads(_requete(f"{API_TELEGRAM}/bot{jeton.strip()}/getUpdates"))
    vus = {}
    for u in rep.get("result", []):
        m = u.get("message") or u.get("channel_post") or u.get("my_chat_member") or {}
        c = m.get("chat") or {}
        if "id" in c:
            vus[str(c["id"])] = c.get("title") or " ".join(x for x in (c.get("first_name"), c.get("last_name")) if x) \
                or c.get("username") or str(c["id"])
    return list(vus.items())


def _twilio(cfg, ressource, champs):
    sid, jeton = cfg.get("twilio.sid").strip(), cfg.get("twilio.jeton").strip()
    if not sid or not jeton:
        raise ErreurNotification("identifiants Twilio manquants (Account SID et Auth Token)")
    auth = base64.b64encode(f"{sid}:{jeton}".encode()).decode()
    _requete(f"{API_TWILIO}/2010-04-01/Accounts/{sid}/{ressource}.json", urllib.parse.urlencode(champs).encode(),
             {"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"})


def whatsapp(cfg, titre, texte, photo=None):
    nums = numeros(cfg.get("whatsapp.numero"))
    if not nums:
        raise ErreurNotification("numéro WhatsApp manquant")
    message = f"*{titre}*\n{texte}".strip()
    if cfg.get("whatsapp.service") == "twilio":
        expediteur = cfg.get("twilio.numero").strip()
        if not expediteur:
            raise ErreurNotification("numéro d'envoi Twilio manquant")
        for n in nums:
            _twilio(cfg, "Messages", {"From": f"whatsapp:{expediteur.replace('whatsapp:', '')}",
                                      "To": f"whatsapp:{n}", "Body": message[:1500]})
        return
    cle = cfg.get("whatsapp.cle").strip()
    if not cle:
        raise ErreurNotification("clé CallMeBot manquante")
    for n in nums:
        rep = _requete(f"{API_CALLMEBOT}/whatsapp.php?" + urllib.parse.urlencode(
            {"phone": n, "text": message[:1000], "apikey": cle}))
        if "APIKey is invalid" in rep or "ERROR" in rep.upper()[:200]:
            raise ErreurNotification("CallMeBot a refusé l'envoi (clé ou numéro incorrect)")


def sms(cfg, titre, texte, photo=None):
    nums, expediteur = numeros(cfg.get("sms.numero")), cfg.get("twilio.numero").strip()
    if not nums:
        raise ErreurNotification("numéro SMS manquant")
    if not expediteur:
        raise ErreurNotification("numéro d'envoi Twilio manquant")
    for n in nums:
        _twilio(cfg, "Messages", {"From": expediteur, "To": n, "Body": f"{titre}\n{texte}"[:600]})


def appel(cfg, titre, texte, photo=None):
    num, expediteur = cfg.get("appel.numero").strip(), cfg.get("twilio.numero").strip()
    if not num or not expediteur:
        raise ErreurNotification("numéro à appeler ou numéro d'envoi Twilio manquant")
    phrase = escape(f"{titre}. {texte}"[:400])
    twiml = (f'<Response><Say language="fr-FR">{phrase}</Say><Pause length="1"/>'
             f'<Say language="fr-FR">{phrase}</Say></Response>')
    _twilio(cfg, "Calls", {"From": expediteur, "To": num, "Twiml": twiml})


def ntfy(cfg, titre, texte, photo=None, prioritaire=False):
    sujet = cfg.get("ntfy.sujet").strip().strip("/")
    if not sujet:
        raise ErreurNotification("sujet ntfy manquant")
    url = f"{(cfg.get('ntfy.serveur').strip() or 'https://ntfy.sh').rstrip('/')}/{urllib.parse.quote(sujet)}"
    entetes = {"Title": _entete_utf8(titre), "Priority": "urgent" if prioritaire else "high",
               "Tags": "rotating_light" if prioritaire else "warning"}
    if cfg.get("ntfy.jeton").strip():
        entetes["Authorization"] = f"Bearer {cfg.get('ntfy.jeton').strip()}"
    if photo:
        entetes.update({"Filename": "alerte.jpg", "Message": _entete_utf8(texte)})
        _requete(url, photo, entetes, "PUT")
    else:
        _requete(url, texte.encode("utf-8"), entetes, "POST")


def discord(cfg, titre, texte, photo=None, prioritaire=False):
    url = cfg.get("discord.webhook").strip()
    if not url.startswith("http"):
        raise ErreurNotification("adresse du webhook Discord manquante")
    contenu = {"content": f"{'🚨' if prioritaire else '⚠️'} **{titre}**\n{texte}"[:1900]}
    if photo:
        corps, type_ = _multipart({"payload_json": json.dumps(contenu)}, [("file", "alerte.jpg", photo, "image/jpeg")])
        _requete(url, corps, {"Content-Type": type_})
    else:
        _requete(url, json.dumps(contenu).encode(), {"Content-Type": "application/json"})


def webhook(cfg, titre, texte, photo=None, prioritaire=False, extra=None):
    url = cfg.get("webhook.url").strip()
    if not url.startswith("http"):
        raise ErreurNotification("adresse du webhook manquante")
    d = {"application": "Flux", "titre": titre, "texte": texte, "prioritaire": prioritaire, "date": time.time(),
         **(extra or {})}
    if photo:
        d["photo_jpeg_base64"] = base64.b64encode(photo).decode()
    _requete(url, json.dumps(d, ensure_ascii=False).encode(), {"Content-Type": "application/json"})


# ---------------------------------------------------------------------------
# Vidéos (Telegram, ntfy, Discord, webhook). WhatsApp et SMS ne peuvent recevoir une vidéo que si elle est
# hébergée sur Internet : Flux ne publie jamais vos vidéos, ces canaux reçoivent seulement le texte d'alerte.
# ---------------------------------------------------------------------------
LIMITES_VIDEO = {"telegram": 49_000_000, "ntfy": 15_000_000, "discord": 10_000_000, "webhook": 10_000_000}


def telegram_video(cfg, titre, texte, video, nom):
    jeton, chat = cfg.get("telegram.jeton").strip(), cfg.get("telegram.chat").strip()
    if not jeton or not chat:
        raise ErreurNotification("jeton du bot ou identifiant de discussion manquant")
    corps, type_ = _multipart({"chat_id": chat, "caption": f"{titre}\n{texte}"[:1000], "supports_streaming": "true"},
                              [("video", nom, video, "video/mp4")])
    _requete(f"{API_TELEGRAM}/bot{jeton}/sendVideo", corps, {"Content-Type": type_}, delai=120)


def ntfy_video(cfg, titre, texte, video, nom, prioritaire=False):
    sujet = cfg.get("ntfy.sujet").strip().strip("/")
    if not sujet:
        raise ErreurNotification("sujet ntfy manquant")
    url = f"{(cfg.get('ntfy.serveur').strip() or 'https://ntfy.sh').rstrip('/')}/{urllib.parse.quote(sujet)}"
    entetes = {"Title": _entete_utf8(titre), "Message": _entete_utf8(texte), "Filename": nom,
               "Content-Type": "video/mp4",
               "Priority": "urgent" if prioritaire else "high", "Tags": "movie_camera"}
    if cfg.get("ntfy.jeton").strip():
        entetes["Authorization"] = f"Bearer {cfg.get('ntfy.jeton').strip()}"
    _requete(url, video, entetes, "PUT", delai=120)


def discord_video(cfg, titre, texte, video, nom, prioritaire=False):
    url = cfg.get("discord.webhook").strip()
    if not url.startswith("http"):
        raise ErreurNotification("adresse du webhook Discord manquante")
    contenu = {"content": f"🎥 **{titre}**\n{texte}"[:1900]}
    corps, type_ = _multipart({"payload_json": json.dumps(contenu)}, [("file", nom, video, "video/mp4")])
    _requete(url, corps, {"Content-Type": type_}, delai=120)


def webhook_video(cfg, titre, texte, video, nom, prioritaire=False, extra=None):
    url = cfg.get("webhook.url").strip()
    if not url.startswith("http"):
        raise ErreurNotification("adresse du webhook manquante")
    d = {"application": "Flux", "type": "video", "titre": titre, "texte": texte, "prioritaire": prioritaire,
         "date": time.time(), "video_nom": nom, "video_mp4_base64": base64.b64encode(video).decode(), **(extra or {})}
    _requete(url, json.dumps(d, ensure_ascii=False).encode(), {"Content-Type": "application/json"}, delai=120)


ENVOIS_VIDEO = {"telegram": telegram_video, "ntfy": ntfy_video, "discord": discord_video, "webhook": webhook_video}


def envoyer_video_canal(canal, cfg, titre, texte, video, nom, prioritaire=False, extra=None):
    if len(video) > LIMITES_VIDEO[canal]:
        raise ErreurNotification(f"vidéo trop lourde ({len(video) / 1e6:.0f} Mo, maximum "
                                 f"{LIMITES_VIDEO[canal] / 1e6:.0f} Mo) : réduisez la durée ou la largeur")
    f = ENVOIS_VIDEO[canal]
    if canal == "telegram":
        return f(cfg, titre, texte, video, nom)
    if canal == "webhook":
        return f(cfg, titre, texte, video, nom, prioritaire, extra)
    return f(cfg, titre, texte, video, nom, prioritaire)


ENVOIS = {"telegram": telegram, "whatsapp": whatsapp, "sms": sms, "appel": appel, "ntfy": ntfy, "discord": discord,
          "webhook": webhook}
AVEC_PRIORITE = {"ntfy", "discord", "webhook"}


def canaux_actifs(cfg):
    return [c for c, _ in CANAUX if cfg.get(f"{c}.actif")]


def envoyer_canal(canal, cfg, titre, texte, photo=None, prioritaire=False, extra=None):
    f = ENVOIS[canal]
    if canal == "webhook":
        return f(cfg, titre, texte, photo, prioritaire, extra)
    if canal in AVEC_PRIORITE:
        return f(cfg, titre, texte, photo, prioritaire)
    return f(cfg, titre, texte, photo)


# ---------------------------------------------------------------------------
# Fil d'envoi
# ---------------------------------------------------------------------------
class Notifieur(threading.Thread):
    """File d'envoi des notifications. `log(texte, niveau)` remonte succès et erreurs dans le journal."""

    def __init__(self, cfg, log):
        super().__init__(daemon=True, name="flux-notifications")
        self.cfg, self.log = cfg, log
        self.file = queue.Queue()
        self.derniers = {}  # caméra -> heure du dernier envoi
        self.ignorees = {}  # caméra -> notifications retenues par le délai
        self._erreurs = {}

    def notifier(self, source, texte, photo=None, prioritaire=False, extra=None):
        """Appelée depuis l'interface pour une alerte. Applique l'interrupteur général et l'anti-spam."""
        cfg = self.cfg
        if not cfg.get("notif.actif") or not canaux_actifs(cfg):
            return False
        maintenant = time.time()
        if not prioritaire and maintenant - self.derniers.get(source, 0) < cfg.get("notif.delai") * 60:
            self.ignorees[source] = self.ignorees.get(source, 0) + 1
            return False
        self.derniers[source] = maintenant
        n = self.ignorees.pop(source, 0)
        corps = f"{texte}\nCaméra : {source}\n{time.strftime('%d/%m/%Y %H:%M:%S')}"
        if n:
            corps += f"\n(+{n} autre(s) pendant le délai)"
        from .config import identite
        sujet = "LISTE NOIRE" if prioritaire else ", ".join((extra or {}).get("categories") or []) or "Alerte"
        titre = f"{identite(cfg)['nom']} · {sujet}"
        self.file.put((titre, corps, photo if cfg.get("notif.photo") else None, prioritaire, None,
                       {"camera": source, **(extra or {})}))
        return True

    def tester(self, canal, rappel):
        """Envoi de test sur un canal, même désactivé. rappel(ok: bool, message) depuis le fil d'envoi."""
        from .config import identite
        self.file.put((f"{identite(self.cfg)['nom']} · Test", "Ceci est une notification de test : ce canal fonctionne.",
                       None, False, (canal, rappel), {"camera": "Test"}))

    def video(self, source, texte, chemin, prioritaire=False):
        """Envoie une vidéo de passage sur les canaux qui acceptent les vidéos. Renvoie la liste des canaux."""
        cfg = self.cfg
        if not cfg.get("notif.actif"):
            return []
        canaux = [c for c in canaux_actifs(cfg) if c in ENVOIS_VIDEO]
        if canaux:
            from .config import identite
            titre = f"{identite(cfg)['nom']} · Vidéo{' LISTE NOIRE' if prioritaire else ''}"
            corps = f"{texte}\nCaméra : {source}\n{time.strftime('%d/%m/%Y %H:%M:%S')}"
            self.file.put(("__video__", titre, corps, chemin, prioritaire, canaux, {"camera": source}))
        return canaux

    def _envoyer_video(self, titre, corps, chemin, prioritaire, canaux, extra):
        import os
        try:
            with open(chemin, "rb") as f:
                video = f.read()
        except OSError as e:
            self.log(f"Vidéo introuvable : {e}", "erreur")
            return
        for canal in canaux:
            try:
                envoyer_video_canal(canal, self.cfg, titre, corps, video, os.path.basename(chemin), prioritaire, extra)
                self._erreurs.pop(f"video-{canal}", None)
            except Exception as e:  # noqa: BLE001
                if self._erreurs.get(f"video-{canal}") != str(e):
                    self._erreurs[f"video-{canal}"] = str(e)
                    self.log(f"Vidéo {NOMS_CANAUX[canal]} non envoyée : {e}", "erreur")

    def run(self):
        while True:
            element = self.file.get()
            if element[0] == "__video__":
                self._envoyer_video(*element[1:])
                continue
            titre, texte, photo, prioritaire, test, extra = element
            if test:
                canal, rappel = test
                try:
                    envoyer_canal(canal, self.cfg, titre, texte, None, False, extra)
                    rappel(True, f"{NOMS_CANAUX[canal]} : notification de test envoyée.")
                except Exception as e:  # noqa: BLE001
                    rappel(False, f"{NOMS_CANAUX[canal]} : {e}")
                continue
            for canal in canaux_actifs(self.cfg):
                if canal == "appel" and self.cfg.get("appel.liste_noire_seulement") and not prioritaire:
                    continue
                try:
                    envoyer_canal(canal, self.cfg, titre, texte, photo, prioritaire, extra)
                    self._erreurs.pop(canal, None)
                except Exception as e:  # noqa: BLE001
                    if self._erreurs.get(canal) != str(e):  # même erreur : signalée une seule fois
                        self._erreurs[canal] = str(e)
                        self.log(f"Notification {NOMS_CANAUX[canal]} non envoyée : {e}", "erreur")
