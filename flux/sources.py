"""Sources vidéo de Flux : caméras (webcam, RTSP, ONVIF, fichiers, liens web) et envoi de mails."""

import os
import queue
import re
import shutil
import smtplib
import ssl
import threading
import time
from datetime import datetime
from email.message import EmailMessage
from urllib.parse import urlparse

import cv2

from .vision import NOMS_VEHICULES, Pipeline, sans_accents

EXTENSIONS_MEDIA = (".mp4", ".mkv", ".avi", ".mov", ".webm", ".m3u8", ".ts", ".flv", ".mjpg", ".mjpeg", ".m4v",
                    ".mpd", ".wmv")
PREFIXE_MAIL_OK = "Mail envoyé"


def slug(texte):
    return "".join(c if c.isalnum() else "_" for c in texte)


# ---------------------------------------------------------------------------
# Liens web (YouTube, Instagram, ...) via yt-dlp
# ---------------------------------------------------------------------------
def est_lien_web(source):
    """Vrai pour une page web (YouTube, Instagram...) qu'il faut résoudre ; faux pour un flux direct."""
    s = source.strip().lower()
    if not s.startswith(("http://", "https://")):
        return False
    chemin = urlparse(s).path
    return not chemin.endswith(EXTENSIONS_MEDIA) and "/video.cgi" not in chemin and "mjpg" not in chemin


def options_ytdlp(cfg, telechargement=False, dossier=None, progression=None, analyse=False):
    qualite = cfg.get("lecteur.qualite")
    h = "" if qualite == "max" else f"[height<=?{qualite}]"
    video = "[vcodec!=?none][vcodec!=?images][ext!=?mhtml]"  # « ? » : accepte un codec inconnu  # jamais les planches d'aperçu (storyboards)
    if analyse:  # caméra : l'analyse n'a besoin que de l'image, le son est inutile
        fmt = f"bv*{h}{video}/bv*{video}/b{video}/b"
    elif telechargement and shutil.which("ffmpeg"):
        fmt = f"bv*{h}+ba/b{h}/b"  # meilleure image + meilleur son, fusionnés par ffmpeg
    elif telechargement:
        fmt = f"b{h}{video}[acodec!=?none]/b{video}[acodec!=?none]/b"  # sans ffmpeg : fichier unique
    else:  # une seule URL avec image ET son si possible ; sinon l'image seule (lecture sans son)
        fmt = f"b{h}{video}[acodec!=?none]/b{video}[acodec!=?none]/bv*{h}{video}/bv*{video}/b"
    o = {"quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True, "format": fmt, "socket_timeout": 20}
    navigateur = cfg.get("lecteur.cookies")
    if navigateur and navigateur != "aucun":
        o["cookiesfrombrowser"] = (navigateur,)
    if telechargement:
        o["outtmpl"] = os.path.join(dossier, "%(title).80s [%(id)s].%(ext)s")
        if shutil.which("ffmpeg"):
            o["merge_output_format"] = "mp4"
        if progression:
            o["progress_hooks"] = [progression]
    return o


ANSI = re.compile(r"\x1b\[[0-9;]*m")


def conseil_youtube(msg):
    """YouTube exige désormais un moteur JavaScript (Deno) et les composants yt-dlp-ejs."""
    m = msg.lower()
    if any(x in m for x in ("format is not available", "javascript runtime", "js runtime", "sign in to confirm",
                            "challenge", "n challenge", "only images are available")):
        manque = [] if shutil.which("deno") else ["Deno (winget install DenoLand.Deno, puis redémarrer Flux)"]
        manque.append('yt-dlp à jour avec ses composants : pip install -U "yt-dlp[default]"')
        return " — YouTube a besoin de : " + " ; ".join(manque) + "."
    return ""


def resoudre_lien(url, cfg, telecharger_dans=None, progression=None, analyse=False):
    """Retourne {titre, url, direct, duree, fichier, extracteur}. Lève une exception claire en cas d'échec."""
    try:
        import yt_dlp
    except ImportError as e:
        raise RuntimeError("Le module yt-dlp n'est pas installé (pip install yt-dlp).") from e
    telecharger = telecharger_dans is not None
    with yt_dlp.YoutubeDL(options_ytdlp(cfg, telecharger, telecharger_dans, progression, analyse)) as y:
        try:
            info = y.extract_info(url, download=False)
            if info.get("_type") == "playlist" and info.get("entries"):
                info = next(e for e in info["entries"] if e)
            en_direct = bool(info.get("is_live")) or info.get("live_status") == "is_live" or (
                not info.get("duration") and "m3u8" in str(info.get("protocol", "")))  # HLS sans durée = direct
            if info.get("live_status") == "is_upcoming":
                raise RuntimeError("Ce direct n'a pas encore commencé. Réessayez à l'heure prévue.")
            if telecharger and not en_direct:  # un direct ne se télécharge pas : il ne finirait jamais
                info = y.process_ie_result(info, download=True)
            else:
                telecharger = False
        except yt_dlp.utils.DownloadError as e:
            msg = ANSI.sub("", str(e)).replace("ERROR: ", "").strip()
            if any(x in msg.lower() for x in ("will begin", "premieres in", "is upcoming", "live event will")):
                raise RuntimeError("Ce direct n'a pas encore commencé. Réessayez à l'heure prévue.") from e
            if "youtu" in url.lower():
                msg += conseil_youtube(msg)
            if "login" in msg.lower() or "cookies" in msg.lower() or "instagram" in url.lower():
                msg += " — Pour Instagram et les vidéos privées, choisissez votre navigateur dans " \
                       "Réglages › Lecteur vidéo › Cookies du navigateur."
            raise RuntimeError(msg) from e
        fichier = None
        if telecharger:
            fichier = info.get("requested_downloads", [{}])[0].get("filepath") or y.prepare_filename(info)
        flux = info.get("url")
        if not flux and info.get("requested_formats"):
            flux = info["requested_formats"][0].get("url")
        sans_son = (info.get("acodec") == "none" or (info.get("requested_formats") and len(info["requested_formats"]) == 1
                    and info["requested_formats"][0].get("acodec") == "none"))
        return {"titre": info.get("title") or url, "sans_son": bool(sans_son and not telecharger), "url": fichier or flux, "direct": en_direct,
                "duree": info.get("duration"), "fichier": fichier, "extracteur": info.get("extractor_key", "")}


# ---------------------------------------------------------------------------
# Mails (dans un fil dédié : l'interface ne se fige jamais)
# ---------------------------------------------------------------------------
class Mailer(threading.Thread):
    def __init__(self, cfg, log):
        super().__init__(daemon=True)
        self.file = queue.Queue()
        self.cfg = cfg
        self.log = log  # log(texte, niveau)

    def envoyer(self, sujet, corps, pieces=None, au_succes=None):
        self.file.put((sujet, corps, pieces or [], au_succes))

    def run(self):
        while True:
            sujet, corps, pieces, au_succes = self.file.get()
            try:
                self._envoi(sujet, corps, pieces)
            except Exception as e:  # noqa: BLE001
                self.log(f"Échec d'envoi du mail : {e}", "erreur")
                continue
            if au_succes:
                au_succes()
            self.log(f"{PREFIXE_MAIL_OK} : {sujet}", "ok")

    def _envoi(self, sujet, corps, pieces):
        m = self.cfg.section("mail")
        if not m["serveur"] or not m["destinataire"]:
            raise ValueError("paramètres mail incomplets (serveur ou destinataire)")
        msg = EmailMessage()
        msg["Subject"] = sujet
        msg["From"] = m["expediteur"] or m["utilisateur"]
        msg["To"] = m["destinataire"]
        msg.set_content(corps)
        for nom, octets in pieces:
            if nom.lower().endswith(".mp4"):
                msg.add_attachment(octets, maintype="video", subtype="mp4", filename=nom)
            else:
                msg.add_attachment(octets, maintype="image", subtype="jpeg", filename=nom)
        contexte = ssl.create_default_context()
        if m["securite"] == "SSL":
            with smtplib.SMTP_SSL(m["serveur"], int(m["port"]), timeout=30, context=contexte) as s:
                self._login_envoi(s, m, msg)
        else:
            with smtplib.SMTP(m["serveur"], int(m["port"]), timeout=30) as s:
                if m["securite"] == "STARTTLS":
                    s.starttls(context=contexte)
                self._login_envoi(s, m, msg)

    @staticmethod
    def _login_envoi(s, m, msg):
        if m["utilisateur"]:
            s.login(m["utilisateur"], m["mot_de_passe"])
        s.send_message(msg)


# ---------------------------------------------------------------------------
# Dessin des détections sur les photos (alertes, enregistrements)
# ---------------------------------------------------------------------------
COULEURS_PHOTO = {"personne": (255, 170, 47), "visage": (250, 139, 167), "vehicule": (244, 114, 182),
                  "plaque": (36, 165, 245), "zone": (36, 165, 245)}


def dessiner(img, ann):
    h, w = img.shape[:2]
    if ann.get("zone"):
        x1, y1, x2, y2 = ann["zone"]
        cv2.rectangle(img, (int(x1 * w), int(y1 * h)), (int(x2 * w), int(y2 * h)), COULEURS_PHOTO["zone"], 2)

    def cadre(box, c, texte):
        x1, y1, x2, y2 = (int(v) for v in box[:4])
        cv2.rectangle(img, (x1, y1), (x2, y2), c, 2)
        if texte:
            cv2.putText(img, sans_accents(texte), (x1, max(15, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, c, 2)

    noms = {p["id"]: p["personne"][1] for p in ann.get("pistes", []) if p.get("personne")}
    pistes = ann.get("pistes", [])
    for p in ann.get("personnes", []):
        nom = next((noms.get(t["id"]) for t in pistes if list(t["box"]) == list(p[:4])), None)
        cadre(p, COULEURS_PHOTO["personne"], nom or f"personne {p[4]:.0%}")
    for v in ann.get("vehicules", []):
        cadre(v, COULEURS_PHOTO["vehicule"], NOMS_VEHICULES.get(v[5], "vehicule").lower())
    for pl in ann.get("plaques", []):
        cadre(pl, COULEURS_PHOTO["plaque"], pl[4] or "plaque")
    for f in ann.get("visages", []):
        t = f["personne"][1] if f.get("personne") else ""
        if f.get("expression"):
            t = f"{t} {f['expression'].lower()}".strip()
        cadre(f["box"], COULEURS_PHOTO["visage"], t or "visage")
    return img


# ---------------------------------------------------------------------------
# Lecture continue des sources en direct
# ---------------------------------------------------------------------------
SCHEMAS_DIRECTS = ("rtsp", "rtsps", "rtmp", "rtmps", "udp", "rtp", "srt")
_VERROU_OUVERTURE = threading.Lock()  # les options FFmpeg passent par une variable d'environnement globale


def options_ffmpeg(cfg, schema):
    """Options FFmpeg d'OpenCV : RTSP en TCP et mode faible latence (pas de mémoire tampon réseau)."""
    o = []
    if schema in ("rtsp", "rtsps") and cfg.get("systeme.tcp_rtsp"):
        o.append("rtsp_transport;tcp")
    if cfg.get("systeme.faible_latence") and schema in SCHEMAS_DIRECTS:
        o += ["fflags;nobuffer", "flags;low_delay"]
    return "|".join(o)


def ouvrir_capture(src, cfg):
    """cv2.VideoCapture avec les bonnes options. Webcams : pilote par défaut de Windows (comme avant 0.3.2),
    DirectShow seulement en repli ou si choisi dans les réglages (certaines webcams y donnent une image brouillée)."""
    if src.isdigit():
        index = int(src)
        choix = cfg.get("systeme.webcam")
        if os.name == "nt":
            ordre = {"dshow": [cv2.CAP_DSHOW], "msmf": [cv2.CAP_MSMF]}.get(choix, [cv2.CAP_ANY, cv2.CAP_DSHOW])
        else:
            ordre = [cv2.CAP_ANY]
        cap = None
        for api in ordre:
            cap = cv2.VideoCapture(index, api)
            if cap.isOpened():
                break
        return cap  # pas de réglage de mémoire tampon : LectureContinue jette déjà les images en retard
    if "://" not in src:
        return cv2.VideoCapture(src)
    schema = src.split("://", 1)[0].lower()
    with _VERROU_OUVERTURE:
        ancien = os.environ.get("OPENCV_FFMPEG_CAPTURE_OPTIONS")
        opts = options_ffmpeg(cfg, schema)
        if opts:
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = opts
        else:
            os.environ.pop("OPENCV_FFMPEG_CAPTURE_OPTIONS", None)
        try:
            cap = cv2.VideoCapture(src, cv2.CAP_FFMPEG)
        finally:
            if ancien is None:
                os.environ.pop("OPENCV_FFMPEG_CAPTURE_OPTIONS", None)
            else:
                os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = ancien
    return cap


class LectureContinue:
    """Lit une source en direct sans arrêt dans un fil dédié et ne garde que l'image la plus récente.

    Sans cela, quand l'analyse est plus lente que la caméra, les images s'empilent dans la mémoire tampon
    et l'affichage prend de plus en plus de retard sur le direct (RTSP, YouTube en direct, webcam)."""

    def __init__(self, cap, delai_coupure=12.0, rappel=None):
        self.cap = cap
        self.delai_coupure = delai_coupure
        self.rappel = rappel  # rappel(image, heure) à chaque image reçue : affichage immédiat, sans attendre l'analyse
        self.heure = 0.0
        self._cond = threading.Condition()
        self._image = None
        self._n = 0
        self._lu = 0
        self.ignorees = 0
        self.fin = False
        self._fil = threading.Thread(target=self._boucle, daemon=True, name="flux-lecture")
        self._fil.start()

    def _boucle(self):
        echecs = 0
        while not self.fin:
            ok, image = self.cap.read()
            if ok and self.rappel is not None:
                try:
                    self.rappel(image, time.time())
                except Exception:  # noqa: BLE001
                    pass
            with self._cond:
                if ok:
                    echecs = 0
                    self.heure = time.time()
                    if self._n > self._lu:
                        self.ignorees += 1  # l'image précédente n'a pas été analysée : on la remplace
                    self._image = image
                    self._n += 1
                else:
                    echecs += 1
                    if echecs >= 25:  # flux coupé
                        self.fin = True
                self._cond.notify_all()
            if not ok:
                time.sleep(0.05)

    def read(self):
        limite = time.time() + self.delai_coupure
        with self._cond:
            while self._n == self._lu and not self.fin:
                reste = limite - time.time()
                if reste <= 0:
                    return False, None
                self._cond.wait(reste)
            if self._n == self._lu:
                return False, None
            self._lu = self._n
            return True, self._image

    def isOpened(self):
        return self.cap.isOpened()

    def get(self, propriete):
        return self.cap.get(propriete)

    def release(self):
        self.fin = True
        self._fil.join(timeout=3)
        self.cap.release()


# ---------------------------------------------------------------------------
# Fil de capture et d'analyse d'une caméra
# ---------------------------------------------------------------------------
class Detecteur(threading.Thread):
    """Lit une source, l'analyse et publie la dernière image + ses détections pour l'interface."""

    def __init__(self, nom, source, options, cfg, base, file_evenements):
        super().__init__(daemon=True, name=f"flux-{nom}")
        self.nom, self.source, self.o, self.cfg, self.base = nom, source, options, cfg, base
        self.evenements = file_evenements
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.derniere_image = None
        self.annotations = None
        self.fps = 0.0
        self.statut = "Préparation…"
        self.charge = True
        self.writer = None
        self.titre_source = None
        self._en_attente = []
        self.heure_image = 0.0  # heure de réception de l'image affichée (mesure du délai d'affichage)
        self.fps_analyse = 0.0
        self._image_amelioree = False  # l'analyse fournit l'image éclaircie à afficher (basse lumière)
        self._t_directe = 0.0
        self.pipeline = Pipeline(nom, cfg, options, self._recevoir, base)
        from .clips import EnregistreurClips
        self.clips = EnregistreurClips(nom, cfg, self._clip_fini)

    def _clip_fini(self, info):
        """Appelée depuis le fil d'encodage quand une vidéo est prête."""
        heure = datetime.now().strftime("%H:%M:%S")
        if "erreur" in info:
            self.evenements.put({"heure": heure, "source": self.nom, "texte": f"Vidéo non enregistrée : {info['erreur']}",
                                 "niveau": "erreur", "chemin": None, "jpeg": None, "personne_id": None})
            return
        nom = os.path.basename(info["chemin"])
        poids = f"{info['taille'] / 1e6:.1f} Mo" if info["taille"] >= 1e6 else f"{info['taille'] / 1e3:.0f} Ko"
        texte = f"Vidéo enregistrée ({info['duree']:.0f} s, {poids}) : {nom}"
        if self.base is not None and self.cfg.get("base.actions"):
            try:
                self.base.ajouter_action(self.nom, "video", f"{info['texte']} — {nom}")
            except Exception:  # noqa: BLE001
                pass
        self.evenements.put({"heure": heure, "source": self.nom, "texte": texte, "niveau": "video", "chemin": None,
                             "jpeg": None, "personne_id": None, "prioritaire": info["prioritaire"], "video": info})

    def _declencher_clip(self, niveau, texte, extra):
        choix = self.cfg.get("clips.declencheur")
        prioritaire = bool(extra.get("prioritaire"))
        if niveau == "alerte" and (choix in ("alertes", "passages") or prioritaire):
            self.clips.declencher("alerte", texte, prioritaire)
        elif choix == "passages" and niveau == "action" and extra.get("type_action") == "apparition":
            self.clips.declencher("passage", texte)

    def _image_directe(self, image, heure):
        """Appelée par le fil de lecture pour chaque image d'un direct : affichage immédiat."""
        if self._image_amelioree or self.stop_event.is_set():
            return
        with self.lock:
            self.derniere_image = image
            self.heure_image = heure
            if self._t_directe:
                fps = 1.0 / max(heure - self._t_directe, 1e-6)
                self.fps = 0.9 * self.fps + 0.1 * fps if self.fps else fps
            self._t_directe = heure
            ann = self.annotations
        self.clips.ajouter(image, heure, ann)

    # --- événements venant du pipeline -------------------------------------------
    def _recevoir(self, texte, niveau, image=None, **extra):
        self._en_attente.append((texte, niveau, image, extra))

    def _publier(self, texte, niveau="info", image=None, ann=None, **extra):
        chemin = octets = None
        if image is not None and niveau == "alerte":
            photo = dessiner(image.copy(), ann) if ann else image
            ok, buf = cv2.imencode(".jpg", photo, [cv2.IMWRITE_JPEG_QUALITY, 85])
            octets = buf.tobytes() if ok else None
            if octets and self.cfg.get("alertes.photo"):
                try:
                    dossier = self.cfg.dossier_sortie()
                    os.makedirs(dossier, exist_ok=True)
                    chemin = os.path.join(dossier, datetime.now().strftime("alerte_%Y%m%d_%H%M%S_")
                                          + slug(self.nom) + ".jpg")
                    with open(chemin, "wb") as f:
                        f.write(octets)
                except OSError:
                    chemin = None
        try:
            self._declencher_clip(niveau, texte, extra)
        except Exception:  # noqa: BLE001
            pass
        try:
            self._enregistrer_base(texte, niveau, image, extra)
        except Exception as e:  # noqa: BLE001  — la base ne doit jamais arrêter une caméra
            if str(e) != getattr(self, "_erreur_base", None):
                self._erreur_base = str(e)
                self.evenements.put({"heure": datetime.now().strftime("%H:%M:%S"), "source": self.nom,
                                     "texte": f"Base de données : {e} (la caméra continue)", "niveau": "erreur",
                                     "chemin": None, "jpeg": None, "personne_id": None})
        self.evenements.put({"heure": datetime.now().strftime("%H:%M:%S"), "source": self.nom, "texte": texte,
                             "niveau": niveau, "chemin": chemin, "jpeg": octets,
                             "personne_id": extra.get("personne_id"), "prioritaire": bool(extra.get("prioritaire")),
                             "type_action": extra.get("type_action"), "detail": extra.get("detail", texte)})


    def _enregistrer_base(self, texte, niveau, image, extra):
        if self.base is not None and extra.get("enregistrer") and niveau == "action":
            self.base.ajouter_action(self.nom, extra.get("type_action", "info"), extra.get("detail", texte),
                                     extra.get("personne_id"), extra.get("piste"),
                                     image if self.cfg.get("base.miniatures") else None)
        if self.base is not None and niveau == "alerte" and self.cfg.get("base.actions"):
            self.base.ajouter_action(self.nom, "liste_noire" if extra.get("type_action") == "liste_noire" else "alerte",
                                     texte, extra.get("personne_id"), None,
                                     image if self.cfg.get("base.miniatures") else None)
        if self.base is not None and extra.get("type_action") == "plaque" and self.cfg.get("base.actions"):
            self.base.ajouter_action(self.nom, "plaque", extra.get("detail", texte), None, None,
                                     image if self.cfg.get("base.miniatures") else None)

    def _vider_attente(self, frame=None, ann=None):
        attente, self._en_attente = self._en_attente, []
        for texte, niveau, image, extra in attente:
            self._publier(texte, niveau, image, ann, **extra)

    # --- ouverture de la source --------------------------------------------------------
    def _ouvrir(self):
        src = self.source.strip()
        if src.isdigit():
            cap = ouvrir_capture(src, self.cfg)
            self.est_direct = True
            return LectureContinue(cap, rappel=self._image_directe) if cap.isOpened() else cap
        direct = False
        if est_lien_web(src):
            self.statut = "Résolution du lien…"
            info = resoudre_lien(src, self.cfg, analyse=True)
            self.titre_source = info["titre"]
            if info["direct"] != getattr(self, "_annonce_direct", None):
                self._annonce_direct = info["direct"]
                self._publier(f"Lien résolu : {info['titre']}" + (" · en direct" if info["direct"] else ""))
            self.est_direct_web = info["direct"]
            direct = info["direct"]
            src = info["url"]
        cap = ouvrir_capture(src, self.cfg)
        if cap.isOpened() and "://" in src and not direct:
            # Une vidéo en ligne annonce sa durée ; un direct (caméra, HLS, flux MJPEG…) non.
            schema = src.split("://", 1)[0].lower()
            direct = schema in SCHEMAS_DIRECTS or cap.get(cv2.CAP_PROP_FRAME_COUNT) <= 0
        self.est_direct = direct
        # Sources en direct : lecture continue, chaque image est affichée dès sa réception ; l'analyse prend
        # la plus récente quand elle est libre. Vidéos : lecture image par image au rythme de la vidéo.
        return LectureContinue(cap, rappel=self._image_directe) if (direct and cap.isOpened()) else cap

    def _gerer_enregistrement(self, image, fps_source):
        if self.o.get("enregistrer") and image is not None and self.writer is None:
            dossier = self.cfg.dossier_sortie()
            os.makedirs(dossier, exist_ok=True)
            nom = os.path.join(dossier, datetime.now().strftime("enreg_%Y%m%d_%H%M%S_") + slug(self.nom) + ".mp4")
            h, w = image.shape[:2]
            self.writer = cv2.VideoWriter(nom, cv2.VideoWriter_fourcc(*"mp4v"), fps_source or 20, (w, h))
            self._publier(f"Enregistrement démarré : {os.path.basename(nom)}")
        if self.o.get("enregistrer") and image is not None and self.writer is not None:
            self.writer.write(image)
        if not self.o.get("enregistrer") and self.writer is not None:
            self.writer.release()
            self.writer = None
            self._publier("Enregistrement arrêté")

    # --- boucle ----------------------------------------------------------------------------
    def run(self):
        try:
            self._boucle()
        except Exception as e:  # noqa: BLE001
            self.statut = f"Erreur : {e}"
            self._publier(self.statut, "erreur")
        finally:
            self.charge = False
            self.clips.vider()
            if self.writer is not None:
                self.writer.release()
                self.writer = None

    def _boucle(self):
        self.statut = "Chargement du modèle…"
        self._publier("Chargement de l'analyse (la première fois, les modèles se téléchargent)…")
        ok = self.pipeline.preparer()
        self._vider_attente()
        if not ok:
            self.statut = "Modèle indisponible"
            return
        self.statut = "Connexion au flux…"
        try:
            cap = self._ouvrir()
        except Exception as e:  # noqa: BLE001
            self.statut = "Lien impossible à lire"
            self._publier(f"{e}", "erreur")
            return
        if not cap.isOpened():
            self.statut = "Impossible d'ouvrir le flux"
            self._publier("Impossible d'ouvrir le flux : vérifiez l'adresse, le réseau et les identifiants.", "erreur")
            return

        src = self.source.strip()
        est_fichier = not isinstance(cap, LectureContinue)  # fichier ou vidéo en ligne : rythme de la vidéo
        fps_source = cap.get(cv2.CAP_PROP_FPS) or 20
        if fps_source > 120:
            fps_source = 25
        self.statut = "En cours"
        self.charge = False
        self._publier("Flux démarré", "ok")

        n = 0
        ann = None
        perdu = False
        dernier = time.time()
        while not self.stop_event.is_set():
            debut = time.time()
            ok, frame = cap.read()
            if not ok:
                if est_fichier:
                    self.statut = "Fin de la vidéo"
                    self._publier(self.statut)
                    break
                if not perdu:
                    perdu = True
                    self._publier("Flux perdu, reconnexion…", "erreur")
                self.statut = "Flux perdu, reconnexion…"
                self.charge = True
                cap.release()
                self.stop_event.wait(5 if est_lien_web(src) else 2)  # un lien web est re-résolu : pas trop vite
                try:
                    cap = self._ouvrir()
                except Exception:  # noqa: BLE001
                    pass
                continue
            if perdu:
                perdu = False
                self.charge = False
                self._publier("Flux rétabli", "ok")
            self.statut = "En cours"
            n += 1
            if n % max(1, int(self.cfg.get("detection.une_image_sur"))) == 0 or n == 1 or ann is None:
                ann = self.pipeline.analyser(frame)
                self._vider_attente(frame, ann)
            elif ann is not None:
                ann = dict(ann, image_affichee=None)

            if self.o.get("enregistrer"):
                self._gerer_enregistrement(dessiner(frame.copy(), ann), fps_source)
            else:
                self._gerer_enregistrement(None, fps_source)

            maintenant = time.time()
            fps = 1.0 / max(maintenant - dernier, 1e-6)
            dernier = maintenant
            ameliore = ann.get("image_affichee") is not None
            direct_continu = isinstance(cap, LectureContinue)
            self._image_amelioree = ameliore
            with self.lock:
                self.annotations = ann
                self.fps_analyse = 0.9 * self.fps_analyse + 0.1 * fps if self.fps_analyse else fps
                if not direct_continu or ameliore:
                    # vidéo (rythme de la vidéo) ou image éclaircie : affichée avec son analyse
                    self.derniere_image = ann["image_affichee"] if ameliore else frame
                    self.heure_image = getattr(cap, "heure", 0.0) or debut
                    self.fps = self.fps_analyse
            if not direct_continu or ameliore:
                self.clips.ajouter(self.derniere_image, time.time(), None if ameliore else ann)
            if est_fichier:
                reste = 1.0 / fps_source - (time.time() - debut)
                if reste > 0:
                    time.sleep(reste)
        cap.release()

    def arreter(self):
        self.stop_event.set()


class Analyseur(threading.Thread):
    """Analyse les images du lecteur vidéo : ne traite que la plus récente, jamais de retard qui s'accumule."""

    def __init__(self, nom, options, cfg, base, file_evenements):
        super().__init__(daemon=True, name="flux-lecteur")
        self.nom = nom
        self.cfg, self.base, self.evenements = cfg, base, file_evenements
        self.o = options
        self.stop_event = threading.Event()
        self._cond = threading.Condition()
        self._image = None
        self.lock = threading.Lock()
        self.annotations = None
        self.statut = "Préparation…"
        self.pret = False
        self._det = Detecteur(nom, "", options, cfg, base, file_evenements)  # réutilise publication et photos
        self._det.pipeline.nom = nom

    def soumettre(self, frame):
        with self._cond:
            self._image = frame
            self._cond.notify()

    def run(self):
        d = self._det
        try:
            d._publier("Chargement de l'analyse vidéo…")
            ok = d.pipeline.preparer()
            d._vider_attente()
            if not ok:
                self.statut = "Modèle indisponible"
                return
            self.pret = True
            self.statut = "Analyse active"
            while not self.stop_event.is_set():
                with self._cond:
                    while self._image is None and not self.stop_event.is_set():
                        self._cond.wait(0.2)
                    frame, self._image = self._image, None
                if frame is None:
                    continue
                ann = d.pipeline.analyser(frame)
                d._vider_attente(frame, ann)
                with self.lock:
                    self.annotations = ann
        except Exception as e:  # noqa: BLE001
            self.statut = f"Erreur : {e}"
            d._publier(self.statut, "erreur")

    def arreter(self):
        self.stop_event.set()
        with self._cond:
            self._cond.notify()

    @property
    def pipeline(self):
        return self._det.pipeline

    def renommer(self, nom):
        self.nom = nom
        self._det.nom = nom
        self._det.pipeline.nom = nom
