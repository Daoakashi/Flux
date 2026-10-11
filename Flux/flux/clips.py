"""Courtes vidéos des passages : Flux garde en permanence les dernières secondes de chaque caméra en mémoire
(pré-enregistrement). Quand une alerte se déclenche, la vidéo contient donc ce qui s'est passé AVANT
l'alerte, puis continue quelques secondes après.

L'encodage se fait en H.264 (MP4) avec ffmpeg : c'est le seul format que les téléphones, WhatsApp,
Telegram et les clients mail lisent partout. Sans ffmpeg, Flux se replie sur le codec intégré d'OpenCV
(lisible sur PC, pas toujours sur téléphone).
"""

import collections
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime

import cv2


def executable_ffmpeg():
    """ffmpeg fourni par le paquet imageio-ffmpeg (toujours présent après installer.bat), sinon celui du PATH."""
    try:
        import imageio_ffmpeg
        chemin = imageio_ffmpeg.get_ffmpeg_exe()
        if chemin and os.path.isfile(chemin):
            return chemin
    except Exception:  # noqa: BLE001
        pass
    return shutil.which("ffmpeg")


def _sans_console():
    """Sous Windows, empêche ffmpeg d'ouvrir une fenêtre noire à chaque vidéo."""
    if os.name == "nt":
        return {"creationflags": 0x08000000}  # CREATE_NO_WINDOW
    return {}


def encoder(images, chemin, fps):
    """Écrit une liste d'images BGR (même taille) en MP4. Renvoie (chemin, compatible_telephone)."""
    h, w = images[0].shape[:2]
    exe = executable_ffmpeg()
    if exe:
        cmd = [exe, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
               "-r", f"{fps:.3f}", "-i", "-", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "27",
               "-pix_fmt", "yuv420p", "-movflags", "+faststart", chemin]
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                             **_sans_console())
        try:
            for img in images:
                p.stdin.write(img.tobytes())
            p.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        erreur = p.stderr.read().decode("utf-8", "replace")
        p.wait(timeout=120)
        if p.returncode == 0 and os.path.isfile(chemin) and os.path.getsize(chemin) > 0:
            return chemin, True
        raise RuntimeError(f"ffmpeg : {erreur.strip()[:200] or p.returncode}")
    ecrivain = cv2.VideoWriter(chemin, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for img in images:
        ecrivain.write(img)
    ecrivain.release()
    return chemin, False


class EnregistreurClips:
    """Un par caméra. `ajouter` reçoit les images (n'importe quel fil), `declencher` lance une vidéo,
    `fini(info)` est appelé depuis un fil d'encodage quand le fichier est prêt."""

    def __init__(self, nom, cfg, fini):
        self.nom, self.cfg, self.fini = nom, cfg, fini
        self._verrou = threading.Lock()
        self._tampon = collections.deque()
        self._dernier_ajout = 0.0
        self._en_cours = None  # dict : images, fin, raison, texte, prioritaire
        self._dernier_clip = 0.0
        self.manuel_demande = False

    # --- images --------------------------------------------------------------------------
    def ajouter(self, frame, heure, ann=None):
        if not self.cfg.get("clips.actif") and self._en_cours is None:
            return
        fps = max(2, int(self.cfg.get("clips.fps")))
        if heure - self._dernier_ajout < 1.0 / fps * 0.9:
            return  # on garde fps images par seconde, pas plus
        self._dernier_ajout = heure
        img = self._preparer(frame, ann)
        avant = float(self.cfg.get("clips.avant"))
        with self._verrou:
            self._tampon.append((heure, img))
            while self._tampon and heure - self._tampon[0][0] > avant:
                self._tampon.popleft()
            c = self._en_cours
            if c is not None:
                c["images"].append((heure, img))
                if heure >= c["fin"] or heure - c["debut"] >= float(self.cfg.get("clips.duree_max")):
                    self._en_cours = None
                    threading.Thread(target=self._terminer, args=(c,), daemon=True, name="flux-clip").start()

    def _preparer(self, frame, ann):
        if ann and self.cfg.get("clips.cadres"):
            from .sources import dessiner
            frame = dessiner(frame.copy(), ann)
        h, w = frame.shape[:2]
        largeur = int(self.cfg.get("clips.largeur"))
        if w > largeur:
            f = largeur / w
            frame = cv2.resize(frame, (largeur, int(h * f)), interpolation=cv2.INTER_AREA)
        h, w = frame.shape[:2]
        if w % 2 or h % 2:  # H.264 exige des dimensions paires
            frame = frame[:h - h % 2, :w - w % 2]
        return frame

    # --- déclenchement ----------------------------------------------------------------------
    def declencher(self, raison, texte, prioritaire=False, force=False):
        """Démarre (ou prolonge) une vidéo. Renvoie True si une vidéo est lancée ou prolongée."""
        if not force and not self.cfg.get("clips.actif"):
            return False
        maintenant = time.time()
        apres = float(self.cfg.get("clips.apres"))
        with self._verrou:
            c = self._en_cours
            if c is not None:  # déjà en cours : on prolonge (dans la limite de la durée maximale)
                c["fin"] = max(c["fin"], maintenant + apres)
                c["prioritaire"] = c["prioritaire"] or prioritaire
                if prioritaire and not c["prioritaire_texte"]:
                    c["texte"], c["prioritaire_texte"] = texte, True
                return True
            if not (force or prioritaire) and maintenant - self._dernier_clip < float(self.cfg.get("clips.delai")) * 60:
                return False
            self._dernier_clip = maintenant
            self._en_cours = {"images": list(self._tampon), "debut": maintenant, "fin": maintenant + apres,
                              "raison": raison, "texte": texte, "prioritaire": prioritaire,
                              "prioritaire_texte": prioritaire, "manuel": force}
        return True

    def en_cours(self):
        return self._en_cours is not None

    def vider(self):
        """Caméra arrêtée : termine la vidéo en cours avec ce qui a été filmé."""
        with self._verrou:
            c, self._en_cours = self._en_cours, None
            self._tampon.clear()
        if c is not None:
            threading.Thread(target=self._terminer, args=(c,), daemon=True, name="flux-clip").start()

    def _terminer(self, c):
        images = c["images"]
        if len(images) < 3:
            return
        duree = images[-1][0] - images[0][0]
        fps = max(1.0, (len(images) - 1) / duree) if duree > 0 else float(self.cfg.get("clips.fps"))
        taille = images[-1][1].shape[:2]
        cadres = [img for _, img in images if img.shape[:2] == taille]  # au cas où la résolution change
        import unicodedata
        from .sources import slug
        nom_ascii = unicodedata.normalize("NFKD", slug(self.nom)).encode("ascii", "ignore").decode() or "camera"
        dossier = os.path.join(self.cfg.dossier_sortie(), "videos")
        os.makedirs(dossier, exist_ok=True)
        chemin = os.path.join(dossier, datetime.fromtimestamp(c["debut"]).strftime("video_%Y%m%d_%H%M%S_")
                              + nom_ascii + ".mp4")
        try:
            chemin, compatible = encoder(cadres, chemin, fps)
            self.fini({"chemin": chemin, "duree": duree, "texte": c["texte"], "raison": c["raison"],
                       "prioritaire": c["prioritaire"], "manuel": c["manuel"], "compatible": compatible,
                       "taille": os.path.getsize(chemin)})
        except Exception as e:  # noqa: BLE001
            self.fini({"erreur": str(e), "texte": c["texte"]})


def purger(dossier, jours):
    """Supprime les vidéos plus anciennes que `jours` (0 = jamais)."""
    if not jours or jours <= 0 or not os.path.isdir(dossier):
        return 0
    limite, n = time.time() - jours * 86400, 0
    for f in os.listdir(dossier):
        c = os.path.join(dossier, f)
        if f.startswith("video_") and f.endswith(".mp4") and os.path.getmtime(c) < limite:
            try:
                os.remove(c)
                n += 1
            except OSError:
                pass
    return n
