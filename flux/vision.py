"""Moteur de vision de Flux : modèles partagés, niveaux de scan, basse lumière, visages, plaques, suivi.

Tout ce qui est lourd (PyTorch, ONNX) est importé à la demande dans les fils de détection,
pour que l'interface s'ouvre instantanément.
"""

import math
import os
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.request

import cv2
import numpy as np

from .config import DOSSIER_MODELES, niveau_effectif

CLASSES_VEHICULES = (2, 3, 5, 7)  # voiture, moto, bus, camion (COCO)
NOMS_VEHICULES = {2: "Voiture", 3: "Moto", 5: "Bus", 7: "Camion"}
EXPRESSIONS_FR = {
    "Anger": "Colère", "Contempt": "Mépris", "Disgust": "Dégoût", "Fear": "Peur",
    "Happiness": "Joie", "Neutral": "Neutre", "Sadness": "Tristesse", "Surprise": "Surprise",
}
URL_ZOO = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
MODELES_VISAGE = {
    "yunet": ("face_detection_yunet_2023mar.onnx", URL_ZOO + "face_detection_yunet/face_detection_yunet_2023mar.onnx"),
    "sface": ("face_recognition_sface_2021dec.onnx",
              URL_ZOO + "face_recognition_sface/face_recognition_sface_2021dec.onnx"),
}
INDICES = {
    "expressions": "pip install hsemotion-onnx onnxruntime onnx",
    "ocr": "pip install rapidocr-onnxruntime",
}


def sans_accents(texte):
    return "".join(c for c in unicodedata.normalize("NFD", texte) if unicodedata.category(c) != "Mn")


def iou(a, b):
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def nms(boites, scores, seuil):
    """Suppression des doublons sans dépendre de torch (utilisée pour fusionner passes et tuiles)."""
    if not boites:
        return []
    b = np.asarray(boites, dtype=float)
    s = np.asarray(scores, dtype=float)
    ordre = s.argsort()[::-1]
    gardes = []
    while ordre.size:
        i = ordre[0]
        gardes.append(int(i))
        if ordre.size == 1:
            break
        xx1 = np.maximum(b[i, 0], b[ordre[1:], 0])
        yy1 = np.maximum(b[i, 1], b[ordre[1:], 1])
        xx2 = np.minimum(b[i, 2], b[ordre[1:], 2])
        yy2 = np.minimum(b[i, 3], b[ordre[1:], 3])
        inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
        aire = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
        u = aire[i] + aire[ordre[1:]] - inter
        ordre = ordre[1:][inter / np.maximum(u, 1e-9) <= seuil]
    return gardes


# ---------------------------------------------------------------------------
# Matériel et modèles partagés
# ---------------------------------------------------------------------------
_LOCK = threading.Lock()
_MODELES = {}
_AUX = {}
_INFO_APPAREIL = {}


def info_appareil():
    """Décrit le matériel de calcul (importe torch : à appeler hors du fil de l'interface)."""
    if _INFO_APPAREIL:
        return dict(_INFO_APPAREIL)
    info = {"cuda": False, "nom": "Processeur (CPU)", "torch": None, "mps": False}
    try:
        import torch
        info["torch"] = torch.__version__
        if torch.cuda.is_available():
            info["cuda"] = True
            info["nom"] = torch.cuda.get_device_name(0)
            info["memoire_go"] = round(torch.cuda.get_device_properties(0).total_memory / 1e9, 1)
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            info["mps"] = True
            info["nom"] = "Apple Silicon (MPS)"
    except Exception as e:  # noqa: BLE001
        info["erreur"] = str(e)
    _INFO_APPAREIL.update(info)
    return dict(info)


_THREADS_REGLES = []


def _limiter_threads_cpu():
    """Sur processeur, PyTorch prend tous les cœurs et affame le décodage vidéo : on en laisse deux libres."""
    if _THREADS_REGLES:
        return
    _THREADS_REGLES.append(True)
    try:
        import torch
        torch.set_num_threads(max(1, (os.cpu_count() or 2) - 2))
    except Exception:  # noqa: BLE001
        pass


def appareil(choix):
    info = info_appareil()
    if choix != "cpu" and info["cuda"]:
        return "cuda:0"
    if choix == "auto" and info.get("mps"):
        return "mps"
    _limiter_threads_cpu()
    return "cpu"


def chemin_modele(nom):
    """Les modèles connus sont rangés (et téléchargés) dans le dossier « modeles »."""
    if os.path.isabs(nom) or os.path.sep in nom or "/" in nom:
        return nom
    os.makedirs(DOSSIER_MODELES, exist_ok=True)
    return os.path.join(DOSSIER_MODELES, nom)


def options_precision(demi):
    """Demi-précision (FP16) : « quantize » dans les versions récentes d'Ultralytics, « half » avant."""
    if not demi:
        return {}
    try:
        from ultralytics.cfg import DEFAULT_CFG_DICT
        if "quantize" in DEFAULT_CFG_DICT:
            return {"quantize": 16}
    except Exception:  # noqa: BLE001
        pass
    return {"half": True}


def sans_statistiques():
    """Désactive l'envoi de statistiques anonymes d'Ultralytics (en mémoire seulement : aucun fichier modifié)."""
    try:
        from ultralytics.utils import events as ev
        ev.events.enabled = False
    except Exception:  # noqa: BLE001
        pass


MODELE_OFFICIEL = re.compile(r"^(yolo(v?\d+|26)[nsmlx]?(-\w+)?|rtdetr-[lx])\.pt$", re.I)
_VERROU_TELECHARGEMENT = threading.Lock()


def modele_valide(chemin):
    """Un modèle PyTorch (.pt) est une archive zip : un fichier tronqué ou corrompu ne l'est pas."""
    import zipfile
    try:
        return os.path.getsize(chemin) > 100_000 and zipfile.is_zipfile(chemin)
    except OSError:
        return False


def _tags_ultralytics():
    tags = []
    try:
        import ultralytics
        majeur, mineur = ultralytics.__version__.split(".")[:2]
        tags.append(f"v{majeur}.{mineur}.0")
    except Exception:  # noqa: BLE001
        pass
    return tags + [t for t in ("v8.4.0", "v8.3.0") if t not in tags]


def assurer_modele(nom, rappel=None):
    """Garantit qu'un modèle officiel est présent et intact dans « modeles » (supprime les fichiers tronqués
    d'un téléchargement interrompu, puis télécharge depuis zéro avec plusieurs essais)."""
    chemin = chemin_modele(nom)
    base = os.path.basename(chemin)
    if os.path.dirname(chemin) != DOSSIER_MODELES or not MODELE_OFFICIEL.match(base):
        return chemin  # modèle personnel : laissé tel quel
    with _VERROU_TELECHARGEMENT:
        if modele_valide(chemin):
            return chemin
        for reste in (chemin, chemin + ".part", chemin + ".tmp", os.path.join(os.getcwd(), base)):
            if os.path.isfile(reste) and not (reste != chemin and reste.endswith(".pt") and modele_valide(reste)):
                try:
                    os.remove(reste)  # fichier incomplet : c'est lui qui provoquait l'erreur 416
                except OSError:
                    pass
        erreurs = []
        for tag in _tags_ultralytics():
            url = f"https://github.com/ultralytics/assets/releases/download/{tag}/{base}"
            for essai in range(3):
                try:
                    telecharger(url, chemin, rappel)
                    if modele_valide(chemin):
                        return chemin
                    os.remove(chemin)
                    erreurs.append("fichier reçu incomplet")
                except urllib.error.HTTPError as e:
                    erreurs.append(f"HTTP {e.code}")
                    if e.code == 404:
                        break  # pas dans cette version des modèles : essayer la suivante
                except Exception as e:  # noqa: BLE001
                    erreurs.append(str(e))
                time.sleep(1.5 * (essai + 1))
        raise RuntimeError(f"téléchargement de {base} impossible ({erreurs[-1] if erreurs else 'erreur inconnue'}). "
                           f"Vérifiez la connexion, ou téléchargez le fichier depuis github.com/ultralytics/assets/"
                           f"releases et placez-le dans le dossier « modeles ».")


def obtenir_detecteur(nom, rappel=None):
    """Un exemplaire de chaque modèle de détection, partagé par tous les flux (avec un verrou)."""
    chemin = assurer_modele(nom, rappel)
    with _LOCK:
        if chemin not in _MODELES:
            from ultralytics import RTDETR, YOLO
            sans_statistiques()
            classe = RTDETR if os.path.basename(chemin).lower().startswith("rtdetr") else YOLO
            _MODELES[chemin] = (classe(chemin), threading.Lock())
        return _MODELES[chemin]


def telecharger(url, destination, rappel=None):
    """Téléchargement simple avec fichier temporaire (jamais de modèle à moitié écrit)."""
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    tmp = destination + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": "Flux"})  # jamais de reprise partielle (Range)
    try:
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            lu = 0
            while True:
                bloc = r.read(1 << 16)
                if not bloc:
                    break
                f.write(bloc)
                lu += len(bloc)
                if rappel and total:
                    rappel(lu / total)
        if total and lu != total:
            raise OSError(f"téléchargement interrompu ({lu // 1_000_000} Mo sur {total // 1_000_000} Mo)")
        os.replace(tmp, destination)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return destination


def fichier_visage(cle):
    nom, url = MODELES_VISAGE[cle]
    chemin = os.path.join(DOSSIER_MODELES, nom)
    if not os.path.isfile(chemin):
        telecharger(url, chemin)
    return chemin


def obtenir_reconnaisseur():
    with _LOCK:
        if "sface" not in _AUX:
            _AUX["sface"] = (cv2.FaceRecognizerSF.create(fichier_visage("sface"), ""), threading.Lock())
        return _AUX["sface"]


def obtenir_expression():
    with _LOCK:
        if "expression" not in _AUX:
            from hsemotion_onnx.facial_emotions import HSEmotionRecognizer
            _AUX["expression"] = (HSEmotionRecognizer(model_name="enet_b0_8_best_vgaf"), threading.Lock())
        return _AUX["expression"]


def obtenir_ocr():
    """RapidOCR : ancien paquet « rapidocr-onnxruntime » (Python ≤ 3.12) ou nouveau « rapidocr » (3.13+)."""
    with _LOCK:
        if "ocr" not in _AUX:
            try:
                from rapidocr_onnxruntime import RapidOCR
                _AUX["ocr"] = (RapidOCR(), threading.Lock())
            except ImportError:
                from rapidocr import RapidOCR
                moteur = RapidOCR()

                def ocr(img):  # même format de sortie que l'ancien paquet : [[boîte, texte, score], ...]
                    r = moteur(img)
                    if getattr(r, "txts", None) is None:
                        return None, None
                    return [[b, t, s] for b, t, s in zip(np.asarray(r.boxes).tolist(), r.txts, r.scores)], None

                _AUX["ocr"] = (ocr, threading.Lock())
        return _AUX["ocr"]


# ---------------------------------------------------------------------------
# Basse lumière
# ---------------------------------------------------------------------------
def luminance(img):
    petite = cv2.resize(img, (64, 36), interpolation=cv2.INTER_AREA)
    return float(cv2.cvtColor(petite, cv2.COLOR_BGR2GRAY).mean())


def ameliorer_basse_lumiere(img, debruitage=10, contraste=1.8, fine=False):
    """Éclaircit par un gamma adapté à la luminosité, débruite, puis renforce le contraste local.

    fine=False : une passe de débruitage sur une copie réduite à 640 px (~0,25 s sur processeur).
    fine=True  : débruitage avant et après l'éclaircissement, à 960 px (plus lent, nettement meilleur dans
                 le noir quasi total ; utilisé par les niveaux Précis et Maximum).
    Le résultat garde la taille d'origine, pour que les coordonnées des détections restent valables."""
    h, w = img.shape[:2]
    f = min(1.0, (960.0 if fine else 640.0) / max(h, w))
    x = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA) if f < 1 else img
    lum = max(luminance(x), 1.0) / 255.0
    gamma = float(np.clip(np.log(lum) / np.log(0.42), 1.0, 5.0))
    if debruitage and fine:
        x = cv2.fastNlMeansDenoisingColored(x, None, debruitage * 0.4, debruitage * 0.4, 5, 15)
    x = cv2.LUT(x, ((np.arange(256) / 255.0) ** (1 / gamma) * 255).astype(np.uint8))
    if debruitage:
        x = cv2.fastNlMeansDenoisingColored(x, None, debruitage, debruitage, 7 if fine else 5, 21 if fine else 11)
    if contraste > 0:
        l, a, b = cv2.split(cv2.cvtColor(x, cv2.COLOR_BGR2LAB))
        x = cv2.cvtColor(cv2.merge((cv2.createCLAHE(contraste, (8, 8)).apply(l), a, b)), cv2.COLOR_LAB2BGR)
    return cv2.resize(x, (w, h), interpolation=cv2.INTER_LINEAR) if f < 1 else x


# ---------------------------------------------------------------------------
# Plaques
# ---------------------------------------------------------------------------
def trouver_plaque_classique(crop):
    """Localise une plaque dans l'image d'un véhicule : rectangle clair, de proportions typiques,
    contenant du texte sombre (beaucoup de contours verticaux). Retourne (x1, y1, x2, y2, score)."""
    h, w = crop.shape[:2]
    if w < 60 or h < 40:
        return None
    echelle = 480.0 / w if w > 480 else 1.0
    img = cv2.resize(crop, None, fx=echelle, fy=echelle, interpolation=cv2.INTER_AREA) if echelle != 1.0 else crop
    H, W = img.shape[:2]
    y0 = int(H * 0.25)
    gris = cv2.GaussianBlur(cv2.cvtColor(img[y0:], cv2.COLOR_BGR2GRAY), (3, 3), 0)
    sx = np.absolute(cv2.Sobel(gris, cv2.CV_32F, 1, 0, ksize=3))
    sy = np.absolute(cv2.Sobel(gris, cv2.CV_32F, 0, 1, ksize=3))
    p98 = float(np.percentile(gris, 98))
    if p98 < 90:
        return None
    meilleur = None
    for f in (0.85, 0.72, 0.60):
        clair = (gris > f * p98).astype("uint8") * 255
        k = max(3, W // 100)
        clair = cv2.morphologyEx(clair, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
        clair = cv2.morphologyEx(clair, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
        for c in cv2.findContours(clair, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
            if cv2.contourArea(c) < 0.004 * W * H:
                continue
            (_, _), (rw, rh), _ = cv2.minAreaRect(c)
            rw, rh = max(rw, rh), max(1.0, min(rw, rh))
            ar = rw / rh
            if not 1.8 <= ar <= 6.8 or not 0.10 * W <= rw <= 0.80 * W:
                continue
            remplissage = cv2.contourArea(c) / (rw * rh)
            if remplissage < 0.60:
                continue
            x, y, cw, ch = cv2.boundingRect(c)
            zone = gris[y:y + ch, x:x + cw]
            fond = float(np.percentile(zone, 85))
            encre = float((zone < 0.65 * fond).mean())
            if not 0.06 <= encre <= 0.55:
                continue
            tx = float(sx[y:y + ch, x:x + cw].mean()) / 255.0
            ty = float(sy[y:y + ch, x:x + cw].mean()) / 255.0
            if tx < 0.05:
                continue
            score = remplissage * min(1.0, tx * 6) * min(1.0, (tx / max(ty, 1e-3)) / 1.1) * (
                1.0 if 3.0 <= ar <= 5.6 else 0.75)
            if meilleur is None or score > meilleur[0]:
                meilleur = (score, x, y, cw, ch)
    if meilleur is None or meilleur[0] < 0.44:
        return None
    score, x, y, cw, ch = meilleur
    mx_, my_ = int(0.02 * cw), int(0.05 * ch)
    return (max(0, int((x - mx_) / echelle)), max(0, int((y + y0 - my_) / echelle)),
            min(w, int((x + cw + mx_) / echelle)), min(h, int((y + y0 + ch + my_) / echelle)), score)


def normaliser_plaque(texte):
    t = re.sub(r"[^A-Z0-9]", "", sans_accents(texte).upper())
    if 4 <= len(t) <= 9 and any(c.isdigit() for c in t) and any(c.isalpha() for c in t):
        return t
    return None


def lire_plaque(crop, ocr, confiance_min=0.6):
    h, w = crop.shape[:2]
    if w < 8 or h < 4:
        return None
    if w < 240:
        f = 240.0 / w
        crop = cv2.resize(crop, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    crop = cv2.copyMakeBorder(crop, 12, 12, 12, 12, cv2.BORDER_REPLICATE)
    resultat, _ = ocr(crop)
    if not resultat:
        return None
    morceaux = sorted(resultat, key=lambda r: min(p[0] for p in r[0]))
    texte = normaliser_plaque("".join(str(r[1]) for r in morceaux))
    confiance = sum(float(r[2]) for r in morceaux) / len(morceaux)
    return (texte, confiance) if texte and confiance >= confiance_min else None


# ---------------------------------------------------------------------------
# Suivi des personnes (un traqueur par source)
# ---------------------------------------------------------------------------
class Piste:
    _compteur = 0

    def __init__(self, box, conf, t):
        Piste._compteur += 1
        self.id = Piste._compteur
        self.box = list(box)
        self.conf = conf
        self.debut = t
        self.vue = t
        self.vues = 1
        self.confirmee = False
        self.centres = [((box[0] + box[2]) / 2, (box[1] + box[3]) / 2, t)]
        self.votes = {}  # personne_id -> score cumulé
        self.personne = None  # (id, nom, categorie) une fois identifiée
        self.expr_votes = {}
        self.dans_zone = None
        self.immobile_depuis = t
        self.stationnement_signale = False
        self.alerte_envoyee = False
        self.alerte_liste_noire = None  # id de la fiche déjà signalée (liste noire)
        self.meilleur_visage = None  # (taille, embedding, miniature)
        self.inconnu_cree = False

    def distance(self):
        d = 0.0
        for (x1, y1, _), (x2, y2, _) in zip(self.centres, self.centres[1:]):
            d += math.hypot(x2 - x1, y2 - y1)
        return d

    def expression_dominante(self):
        return max(self.expr_votes, key=self.expr_votes.get) if self.expr_votes else None


class Traqueur:
    """Associe les détections d'une analyse à l'autre (IoU puis distance des centres)."""

    def __init__(self):
        self.pistes = []

    def mettre_a_jour(self, detections, t, delai_perte):
        libres = list(range(len(self.pistes)))
        associees = []
        for (x1, y1, x2, y2, conf) in sorted(detections, key=lambda d: -d[4]):
            box = (x1, y1, x2, y2)
            meilleur, score_max = None, 0.2
            cx, cy, diag = (x1 + x2) / 2, (y1 + y2) / 2, math.hypot(x2 - x1, y2 - y1)
            for i in libres:
                p = self.pistes[i]
                s = iou(box, p.box)
                if s < 0.2:  # repli : proximité des centres (déplacements rapides, analyse espacée)
                    px, py = (p.box[0] + p.box[2]) / 2, (p.box[1] + p.box[3]) / 2
                    d = math.hypot(cx - px, cy - py)
                    s = 0.21 * max(0.0, 1 - d / max(diag * 0.6, 1)) if d < diag * 0.6 else 0
                if s > score_max:
                    score_max, meilleur = s, i
            if meilleur is not None:
                libres.remove(meilleur)
                p = self.pistes[meilleur]
                if math.hypot(cx - (p.box[0] + p.box[2]) / 2, cy - (p.box[1] + p.box[3]) / 2) > diag * 0.08:
                    p.immobile_depuis = t
                    p.stationnement_signale = False
                p.box, p.conf, p.vue = list(box), conf, t
                p.vues += 1
                p.centres.append((cx, cy, t))
                if len(p.centres) > 300:
                    p.centres = p.centres[::2]
                associees.append(p)
            else:
                p = Piste(box, conf, t)
                self.pistes.append(p)
                associees.append(p)
        perdues = [p for p in self.pistes if t - p.vue > delai_perte]
        self.pistes = [p for p in self.pistes if t - p.vue <= delai_perte]
        return associees, perdues


# ---------------------------------------------------------------------------
# Pipeline d'analyse (un par source : caméra ou lecteur)
# ---------------------------------------------------------------------------
class Pipeline:
    """Analyse une image : personnes, véhicules, plaques, visages, identité, expressions, suivi.

    `emettre(texte, niveau, image=None, **extra)` remonte les événements (journal, alertes) ;
    `base` (facultative) enregistre personnes et actions.
    """

    def __init__(self, nom, cfg, options, emettre, base=None):
        self.nom = nom
        self.cfg = cfg
        self.o = options  # réglages propres à la source (niveau, visages, plaques, zone...)
        self.emettre = emettre
        self.base = base
        self.traqueur = Traqueur()
        self._pret = {}
        self._indispo = set()
        self._cache_plaques = []
        self._plaques_vues = {}
        self._yunet = None
        self._haar = None
        self._version_base = -1
        self._matrice = None
        self._ids = []
        self._infos = {}
        self.basse_lumiere_active = False
        self.libelle_niveau = ""
        self.appareil = "cpu"
        self.temps_analyse = 0.0
        self.erreur_modele = None
        self.amelioration_fine = False

    # --- ressources -------------------------------------------------------------
    def _ressource(self, cle, fabrique, libelle):
        if cle in self._indispo:
            return None
        if cle not in self._pret:
            self.emettre(f"Chargement du module « {libelle} »…", "info")
            try:
                self._pret[cle] = fabrique()
            except Exception as e:  # noqa: BLE001
                self._indispo.add(cle)
                indice = INDICES.get(cle)
                self.emettre(f"« {libelle} » indisponible : {e}" + (f". Essayez : {indice}" if indice else ""),
                             "erreur")
                return None
        return self._pret[cle]

    def preparer(self):
        """Charge le modèle de détection du niveau choisi. Retourne False en cas d'échec."""
        niveau = self.o.get("niveau") or self.cfg.get("detection.niveau")
        if niveau == "global":
            niveau = self.cfg.get("detection.niveau")
        fichier, self.taille, self.tuiles, self.libelle_niveau = niveau_effectif(niveau, self.cfg)
        qualite = self.cfg.get("basse_lumiere.qualite")
        self.amelioration_fine = qualite == "fine" or (qualite == "auto" and niveau in ("precis", "maximum"))
        self.appareil = appareil(self.cfg.get("detection.appareil"))
        t0 = time.time()
        if not modele_valide(chemin_modele(fichier)) and MODELE_OFFICIEL.match(os.path.basename(fichier)):
            self.emettre(f"Téléchargement du modèle {os.path.basename(fichier)}… (une seule fois)", "info")
        paliers = set()

        def progression(f):
            palier = int(f * 4)  # 25 %, 50 %, 75 %
            if 0 < palier < 4 and palier not in paliers:
                paliers.add(palier)
                self.emettre(f"Téléchargement de {os.path.basename(fichier)} : {palier * 25} %", "info")

        try:
            self.modele, self.verrou = obtenir_detecteur(fichier, progression)
        except Exception as e:  # noqa: BLE001
            self.erreur_modele = str(e)
            self.emettre(f"Impossible de charger le modèle {fichier} : {e}", "erreur")
            return False
        self.emettre(f"Niveau {self.libelle_niveau} prêt ({time.time() - t0:.0f} s) · calcul sur "
                     f"{'carte graphique' if self.appareil.startswith('cuda') else self.appareil.upper()}", "info")
        return True

    # --- outils -----------------------------------------------------------------------
    def _dans_zone(self, box, w, h):
        zone = self.o.get("zone")
        if not zone:
            return True
        x1, y1, x2, y2 = zone
        cx, cy = (box[0] + box[2]) / 2 / w, (box[1] + box[3]) / 2 / h
        return x1 <= cx <= x2 and y1 <= cy <= y2

    def _predire(self, images, classes):
        demi = self.appareil.startswith("cuda") and self.cfg.get("detection.demi_precision")
        with self.verrou:
            return self.modele(images, conf=self.cfg.get("detection.confiance"), iou=self.cfg.get("detection.iou"),
                               classes=classes, imgsz=self.taille, device=self.appareil, verbose=False,
                               **options_precision(demi))

    def _detecter(self, img, classes):
        """Détection sur l'image entière, plus des tuiles 2×2 au niveau Maximum."""
        H, W = img.shape[:2]
        regions = [(0, 0, W, H)]
        if self.tuiles and W >= 400 and H >= 300:
            tw, th = int(W * 0.6), int(H * 0.6)
            regions += [(x, y, x + tw, y + th) for y in (0, H - th) for x in (0, W - tw)]
        resultats = self._predire([img[y1:y2, x1:x2] for (x1, y1, x2, y2) in regions], classes)
        boites, scores, cls = [], [], []
        for (x1, y1, _, _), r in zip(regions, resultats):
            for b, c, k in zip(r.boxes.xyxy.tolist(), r.boxes.conf.tolist(), r.boxes.cls.tolist()):
                boites.append([b[0] + x1, b[1] + y1, b[2] + x1, b[3] + y1])
                scores.append(c)
                cls.append(int(k))
        return boites, scores, cls

    # --- analyse principale --------------------------------------------------------------
    def analyser(self, frame, t=None):
        t = time.time() if t is None else t
        debut = time.time()
        h, w = frame.shape[:2]
        veut_plaques = bool(self.o.get("plaques"))
        classes = [0] + (list(CLASSES_VEHICULES) if veut_plaques else [])

        # Basse lumière
        mode = self.cfg.get("basse_lumiere.mode")
        lum = luminance(frame)
        sombre = mode == "toujours" or (mode == "auto" and lum < self.cfg.get("basse_lumiere.seuil"))
        amelioree = None
        if sombre:
            amelioree = ameliorer_basse_lumiere(frame, self.cfg.get("basse_lumiere.debruitage"),
                                                self.cfg.get("basse_lumiere.contraste"), fine=self.amelioration_fine)
        if sombre != self.basse_lumiere_active:
            self.basse_lumiere_active = sombre
            self.emettre("Mode basse lumière activé" if sombre else "Mode basse lumière désactivé", "info")

        if amelioree is not None and self.cfg.get("basse_lumiere.double_passe"):
            b1, s1, c1 = self._detecter(frame, classes)
            b2, s2, c2 = self._detecter(amelioree, classes)
            boites, scores, cls = b1 + b2, s1 + s2, c1 + c2
        else:
            boites, scores, cls = self._detecter(amelioree if amelioree is not None else frame, classes)

        personnes, vehicules = [], []
        seuil_iou = self.cfg.get("detection.iou")
        for groupe in (0, *CLASSES_VEHICULES):
            idx = [i for i, k in enumerate(cls) if k == groupe]
            for j in nms([boites[i] for i in idx], [scores[i] for i in idx], seuil_iou):
                i = idx[j]
                x1, y1, x2, y2 = (int(v) for v in boites[i])
                if not self._dans_zone((x1, y1, x2, y2), w, h):
                    continue
                if groupe == 0:
                    personnes.append((x1, y1, x2, y2, float(scores[i])))
                elif veut_plaques:
                    vehicules.append((x1, y1, x2, y2, float(scores[i]), groupe))

        source_visages = amelioree if amelioree is not None else frame
        visages = self._analyser_visages(source_visages, w, h) if (
            self.o.get("visages") or self.o.get("expressions")) else []
        plaques = self._analyser_plaques(frame, vehicules, t) if veut_plaques else []

        pistes = self._suivre(personnes, visages, frame, t)
        # Un « visage » qui n'appartient à aucune personne détectée est souvent un faux positif (main, flou) :
        # on ne le garde que s'il est très net.
        if personnes:
            visages = [v for v in visages if v.get("piste") is not None or v["score"] >= 0.92]
        self.temps_analyse = time.time() - debut
        affichee = amelioree if (amelioree is not None and self.cfg.get("basse_lumiere.afficher")) else None
        return {"w": w, "h": h, "personnes": personnes, "vehicules": vehicules, "plaques": plaques,
                "visages": visages, "pistes": pistes, "zone": self.o.get("zone"), "basse_lumiere": sombre,
                "luminance": lum, "image_affichee": affichee}

    # --- visages ------------------------------------------------------------------------
    def _detecter_visages(self, img, w, h):
        taille_min = self.cfg.get("visages.taille_min")
        if self.cfg.get("visages.detecteur") == "yunet" and "yunet" not in self._indispo:
            if self._yunet is None:
                try:
                    self._yunet = cv2.FaceDetectorYN.create(fichier_visage("yunet"), "", (320, 320),
                                                            self.cfg.get("visages.score_min"), 0.3, 5000)
                except Exception as e:  # noqa: BLE001
                    self._indispo.add("yunet")
                    self.emettre(f"YuNet indisponible ({e}) : détecteur Haar utilisé.", "erreur")
            if self._yunet is not None:
                # YuNet est plus rapide et aussi précis sur une image réduite à ~960 px
                f = min(1.0, 960.0 / max(w, h))
                petite = cv2.resize(img, None, fx=f, fy=f) if f < 1 else img
                self._yunet.setInputSize((petite.shape[1], petite.shape[0]))
                self._yunet.setScoreThreshold(self.cfg.get("visages.score_min"))
                _, res = self._yunet.detect(petite)
                sortie = []
                for r in ([] if res is None else res):
                    r = r.copy()
                    r[:14] /= f
                    x, y, fw, fh = r[:4]
                    if fw >= taille_min:
                        sortie.append(r)
                return sortie
        if "haar" in self._indispo:
            return []
        if self._haar is None:
            if not hasattr(cv2, "CascadeClassifier"):  # absent d'OpenCV 5
                self._indispo.add("haar")
                self.emettre("Détecteur Haar indisponible avec OpenCV 5 : installez opencv-python<5 ou utilisez YuNet.",
                             "erreur")
                return []
            self._haar = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_alt2.xml")
        gris = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return [np.array([x, y, fw, fh] + [0] * 10 + [0.9], dtype=np.float32)
                for (x, y, fw, fh) in self._haar.detectMultiScale(gris, 1.1, 6, minSize=(taille_min, taille_min))]

    def _base_a_jour(self):
        if self.base is None:
            return
        v = self.base.version
        if v != self._version_base:
            self._version_base = v
            self._matrice, self._ids, self._infos = self.base.matrice_empreintes()
            self._revalider_pistes()

    def _revalider_pistes(self):
        """Après un renommage, une fusion ou une suppression dans la page Personnes : met à jour les personnes suivies."""
        for p in self.traqueur.pistes:
            if p.votes:
                votes = {}
                for pid, s in p.votes.items():
                    nouveau = self.base.resoudre(pid)
                    if nouveau is not None:
                        votes[nouveau] = votes.get(nouveau, 0) + s
                p.votes = votes
            if p.personne is None:
                continue
            pid = self.base.resoudre(p.personne[0])
            if pid is None:
                p.personne = None  # fiche supprimée : la personne redevient anonyme pour ce passage
            else:
                p.personne = (pid, *self._infos.get(pid, p.personne[1:]))

    def identifier(self, empreinte):
        """Retourne (personne_id, similarité) de la personne la plus proche, ou (None, meilleure similarité)."""
        self._base_a_jour()
        if self._matrice is None or not len(self._ids):
            return None, 0.0
        e = empreinte.reshape(-1).astype(np.float32)
        e = e / (np.linalg.norm(e) + 1e-9)
        sims = self._matrice @ e
        i = int(np.argmax(sims))
        s = float(sims[i])
        return (self._ids[i], s) if s >= self.cfg.get("visages.seuil") else (None, s)

    def _analyser_visages(self, img, w, h):
        brut = [r for r in self._detecter_visages(img, w, h) if self._dans_zone(
            (r[0], r[1], r[0] + r[2], r[1] + r[3]), w, h)]
        brut.sort(key=lambda r: -r[2])
        brut = brut[:8]
        sortie = []
        reco = None
        if self.cfg.get("visages.reconnaissance") and brut and brut[0][4:14].any():
            reco = self._ressource("sface", obtenir_reconnaisseur, "Reconnaissance des visages")
        fer = self._ressource("expressions", obtenir_expression, "Expressions du visage") if (
            self.o.get("expressions") and brut) else None
        for r in brut:
            x, y, fw, fh = (float(v) for v in r[:4])
            box = [int(x), int(y), int(x + fw), int(y + fh)]
            v = {"box": box, "score": float(r[14]), "personne": None, "similarite": 0.0, "expression": None,
                 "proba": 0.0, "empreinte": None, "miniature": None}
            if reco is not None and r[4:14].any():
                modele, verrou = reco
                try:
                    with verrou:
                        aligne = modele.alignCrop(img, r)
                        emp = modele.feature(aligne)
                    v["empreinte"] = emp.reshape(-1).astype(np.float32)
                    v["miniature"] = aligne
                    pid, s = self.identifier(v["empreinte"])
                    v["similarite"] = s
                    if pid is not None:
                        v["personne"] = (pid, *self._infos.get(pid, ("?", "connu")))
                except Exception:  # noqa: BLE001
                    pass
            if fer is not None:
                modele, verrou = fer
                m = int(0.15 * fw)
                crop = img[max(0, int(y) - m):int(y + fh) + m, max(0, int(x) - m):int(x + fw) + m]
                if crop.size:
                    try:
                        with verrou:
                            emo, scores = modele.predict_emotions(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB), logits=False)
                        k = int(np.argmax(scores))
                        nom = modele.idx_to_class[k]
                        v["expression"], v["proba"] = EXPRESSIONS_FR.get(nom, nom), float(scores[k])
                    except Exception:  # noqa: BLE001
                        pass
            sortie.append(v)
        return sortie

    # --- plaques ----------------------------------------------------------------------
    def _analyser_plaques(self, frame, vehicules, t):
        h, w = frame.shape[:2]
        plaques = []
        if "plaques_pt" not in self._pret:
            from .config import RACINE
            chemin = os.path.join(RACINE, "plaques.pt")
            self._pret["plaques_pt"] = None
            if os.path.isfile(chemin):
                try:
                    self._pret["plaques_pt"] = obtenir_detecteur(chemin)
                    self.emettre("Modèle de plaques « plaques.pt » chargé", "info")
                except Exception as e:  # noqa: BLE001
                    self.emettre(f"plaques.pt illisible : {e}", "erreur")
        pm = self._pret["plaques_pt"]
        if pm is not None:
            modele, verrou = pm
            with verrou:
                res = modele(frame, conf=max(0.25, self.cfg.get("detection.confiance") * 0.6), device=self.appareil,
                             verbose=False)[0]
            for b in res.boxes:
                x1, y1, x2, y2 = map(int, b.xyxy[0].tolist())
                if self._dans_zone((x1, y1, x2, y2), w, h):
                    plaques.append([x1, y1, x2, y2, None])
        else:
            for v in sorted(vehicules, key=lambda v: -(v[2] - v[0]) * (v[3] - v[1]))[:6]:
                x1, y1, x2, y2 = (max(0, v[0]), max(0, v[1]), min(w, v[2]), min(h, v[3]))
                trouve = trouver_plaque_classique(frame[y1:y2, x1:x2])
                if trouve:
                    plaques.append([x1 + trouve[0], y1 + trouve[1], x1 + trouve[2], y1 + trouve[3], None])

        if self.o.get("lire_plaques") and plaques:
            res = self._ressource("ocr", obtenir_ocr, "Lecture des plaques")
            if res is not None:
                ocr, verrou = res
                relecture = self.cfg.get("plaques.relecture")
                self._cache_plaques[:] = [c for c in self._cache_plaques if t - c[2] < relecture]
                lectures = 0
                for p in plaques:
                    deja = next((c for c in self._cache_plaques if iou(p[:4], c[0]) > 0.3), None)
                    if deja is not None:
                        p[4] = deja[1]
                        deja[0], deja[2] = p[:4], t
                    elif lectures < 1:  # une lecture par analyse : l'OCR est coûteux
                        lectures += 1
                        crop = frame[max(0, p[1]):p[3], max(0, p[0]):p[2]]
                        with verrou:
                            lu = lire_plaque(crop, ocr, self.cfg.get("plaques.confiance_lecture")) if crop.size else None
                        if lu:
                            p[4] = lu[0]
                            self._cache_plaques.append([p[:4], lu[0], t])
                            if t - self._plaques_vues.get(lu[0], 0) > 60:
                                self._plaques_vues[lu[0]] = t
                                self.emettre(f"Plaque lue : {lu[0]}", "info", type_action="plaque", detail=lu[0],
                                             image=crop)
                                if lu[0] in self.plaques_interdites() and self.cfg.get("alertes.liste_noire"):
                                    self.emettre(f"LISTE NOIRE : plaque {lu[0]} détectée", "alerte", image=frame,
                                                 prioritaire=True, type_action="liste_noire", plaque=lu[0])
        return [tuple(p) for p in plaques]

    # --- suivi, identité et actions -----------------------------------------------------
    def _suivre(self, personnes, visages, frame, t):
        self._base_a_jour()
        delai = self.cfg.get("detection.delai_absence")
        pistes, perdues = self.traqueur.mettre_a_jour(personnes, t, delai)
        h, w = frame.shape[:2]
        zone = self.o.get("zone")
        confirmation = self.cfg.get("detection.confirmation")
        enregistrer = self.base is not None and self.cfg.get("base.actions")

        # Rattacher chaque visage à la personne qui le contient (haut du corps)
        for v in visages:
            cx, cy = (v["box"][0] + v["box"][2]) / 2, (v["box"][1] + v["box"][3]) / 2
            meilleure = None
            for p in pistes:
                x1, y1, x2, y2 = p.box
                if x1 <= cx <= x2 and y1 <= cy <= y1 + 0.6 * (y2 - y1):
                    if meilleure is None or (x2 - x1) < (meilleure.box[2] - meilleure.box[0]):
                        meilleure = p
            v["piste"] = meilleure.id if meilleure else None
            if meilleure is None:
                continue
            if v["expression"]:
                meilleure.expr_votes[v["expression"]] = meilleure.expr_votes.get(v["expression"], 0) + v["proba"]
            if v["personne"]:
                pid = v["personne"][0]
                meilleure.votes[pid] = meilleure.votes.get(pid, 0) + v["similarite"]
            taille = v["box"][2] - v["box"][0]
            if v["empreinte"] is not None and (meilleure.meilleur_visage is None or taille > meilleure.meilleur_visage[0]):
                meilleure.meilleur_visage = (taille, v["empreinte"], v["miniature"], v["similarite"])

        for p in pistes:
            if not p.confirmee and p.vues >= confirmation:
                p.confirmee = True
                self._action(p, "apparition", "Apparition", frame, enregistrer)
            if not p.confirmee:
                continue
            self._resoudre_identite(p, frame, enregistrer, t)
            if zone:
                dedans = self._dans_zone(p.box, w, h)
                if p.dans_zone is not None and dedans != p.dans_zone:
                    self._action(p, "zone", "Entrée dans la zone" if dedans else "Sortie de la zone", frame, enregistrer)
                p.dans_zone = dedans
            if not p.stationnement_signale and t - p.immobile_depuis >= self.cfg.get("base.stationnement"):
                p.stationnement_signale = True
                self._action(p, "stationnement", f"Immobile depuis {t - p.immobile_depuis:.0f} s", frame, enregistrer)
            if (p.personne is not None and p.personne[2] == "liste_noire" and p.alerte_liste_noire != p.personne[0]
                    and self.cfg.get("alertes.liste_noire")):
                p.alerte_liste_noire = p.personne[0]
                self._alerter(p, frame, liste_noire=True)
            declencheur = self.cfg.get("alertes.declencheur")
            identifiee = p.personne is not None and p.personne[2] != "inconnu"
            delai_ecoule = t - p.debut >= self.cfg.get("alertes.delai_identification")
            if not p.alerte_envoyee and declencheur == "toutes" and (identifiee or delai_ecoule or not (
                    self.o.get("visages") and self.cfg.get("visages.reconnaissance"))):
                self._alerter(p, frame)  # attend la reconnaissance pour donner le nom dans l'alerte
            if not p.alerte_envoyee and declencheur == "inconnues" and (
                    t - p.debut >= self.cfg.get("alertes.delai_identification")) and (
                    p.personne is None or p.personne[2] == "inconnu"):
                self._alerter(p, frame)

        for p in perdues:
            if p.confirmee:
                duree = p.vue - p.debut
                detail = f"Présence {duree:.0f} s, déplacement {p.distance() / max(w, 1) * 100:.0f} % de l'image"
                if p.expression_dominante():
                    detail += f", expression dominante : {p.expression_dominante()}"
                self._action(p, "depart", detail, None, enregistrer)

        sortie = []
        for p in pistes:
            if p.confirmee:
                sortie.append({"id": p.id, "box": p.box, "personne": p.personne})
        return sortie

    def _resoudre_identite(self, p, frame, enregistrer, t):
        if not p.votes and self.base is not None and p.meilleur_visage is not None and not p.inconnu_cree and (
                self.cfg.get("visages.inconnus_auto") and p.personne is None and t - p.debut >= 1.0):
            taille, emp, mini, sim = p.meilleur_visage
            if taille >= self.cfg.get("visages.taille_enrolement"):
                pid, nom = self.base.creer_inconnu(emp, mini)
                p.inconnu_cree = True
                p.personne = (pid, nom, "inconnu")
                self._base_a_jour()
                self._action(p, "identification", f"Nouveau visage enregistré : {nom}", frame, enregistrer)
                return
        if not p.votes:
            return
        pid = max(p.votes, key=p.votes.get)
        if p.votes[pid] < 0.8:  # au moins ~2 visages concordants
            return
        if p.personne is None or p.personne[0] != pid:
            nom, categorie = self._infos.get(pid, ("?", "connu"))
            p.personne = (pid, nom, categorie)
            if self.base is not None:
                self.base.vue(pid)
            self._action(p, "identification", f"Identifiée : {nom}", frame, enregistrer)
            if categorie == "surveille" and self.cfg.get("alertes.declencheur") == "surveillees":
                self._alerter(p, frame)
            # Enrichir la base avec un bon visage (variété d'angles et d'éclairages), sans dériver
            if self.base is not None and p.meilleur_visage is not None:
                taille, emp, mini, sim = p.meilleur_visage
                if taille >= self.cfg.get("visages.taille_enrolement") and sim < 0.75:
                    self.base.ajouter_visage(pid, emp, mini, self.cfg.get("visages.max_par_personne"),
                                             source=self.nom)

    def _nom_piste(self, p):
        return p.personne[1] if p.personne else f"Personne #{p.id}"

    def _action(self, p, type_, detail, frame, enregistrer):
        texte = f"{self._nom_piste(p)} · {detail}" if type_ != "apparition" else f"{self._nom_piste(p)} apparaît"
        mini = None
        if frame is not None:
            x1, y1, x2, y2 = (max(0, int(v)) for v in p.box)
            mini = frame[y1:y2, x1:x2]
        self.emettre(texte, "action", type_action=type_, detail=detail, image=mini,
                     personne_id=p.personne[0] if p.personne else None, piste=p.id, enregistrer=enregistrer)

    def _alerter(self, p, frame, liste_noire=False):
        p.alerte_envoyee = True
        qui = self._nom_piste(p)
        if liste_noire:
            self.emettre(f"LISTE NOIRE : {qui} détecté(e)", "alerte", image=frame, prioritaire=True,
                         type_action="liste_noire", personne_id=p.personne[0] if p.personne else None)
            return
        self.emettre(f"Alerte : {qui} détecté(e)", "alerte", image=frame, personne_id=p.personne[0] if p.personne else None)

    def plaques_interdites(self):
        brut = self.cfg.get("plaques.liste_noire") or ""
        return {n for n in (normaliser_plaque(x) for x in re.split(r"[,;\s]+", brut)) if n}
