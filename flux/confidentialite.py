"""Confidentialité : floutage des têtes sur tout ce que Flux enregistre ou envoie.

Quand l'option est cochée (Réglages › Confidentialité), les têtes sont floutées AVANT d'être écrites sur le
disque ou envoyées : captures, photos d'alerte (mail, Telegram, ntfy…), miniatures du journal, vidéos des
passages et enregistrements. En option, l'image en direct (écran et FluxLite) est floutée aussi.

Aucune dépendance en plus : OpenCV (Apache-2.0) et le détecteur de visages YuNet (MIT) déjà utilisés par Flux,
deux licences qui autorisent la vente.

Ce qui est flouté :
  - chaque visage trouvé par l'analyse (si « Visages » est actif sur la caméra) ;
  - la tête de chaque personne détectée (haut de la silhouette), même de dos ou trop loin pour un visage ;
  - pour les photos, une recherche de visages supplémentaire sur l'image elle-même (YuNet), pour ne rien
    laisser passer même si l'analyse ne cherchait pas les visages.
"""

import threading

import cv2
import numpy as np

_LOCAL = threading.local()


def actif(cfg):
    return bool(cfg.get("confidentialite.flouter"))


def actif_ecran(cfg):
    return actif(cfg) and bool(cfg.get("confidentialite.ecran"))


# ---------------------------------------------------------------------------
# Où sont les têtes ?
# ---------------------------------------------------------------------------
def _yunet():
    """Un détecteur YuNet par fil (il n'est pas prévu pour être partagé entre fils)."""
    d = getattr(_LOCAL, "yunet", None)
    if d is None and not getattr(_LOCAL, "yunet_indispo", False):
        try:
            from .vision import fichier_visage
            d = cv2.FaceDetectorYN.create(fichier_visage("yunet"), "", (320, 320), 0.55, 0.3, 5000)
            _LOCAL.yunet = d
        except Exception:  # noqa: BLE001  — sans YuNet, on floute quand même les têtes des silhouettes
            _LOCAL.yunet_indispo = True
            return None
    return d


def detecter_visages(img):
    """Cadres [x1, y1, x2, y2] des visages de l'image (recherche dédiée, seuil bas : mieux vaut trop flouter)."""
    d = _yunet()
    if d is None:
        return []
    h, w = img.shape[:2]
    f = min(1.0, 960.0 / max(h, w))
    petite = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA) if f < 1 else img
    try:
        d.setInputSize((petite.shape[1], petite.shape[0]))
        _, res = d.detect(petite)
    except Exception:  # noqa: BLE001
        return []
    sortie = []
    for r in ([] if res is None else res):
        x, y, fw, fh = (float(v) / f for v in r[:4])
        sortie.append([x, y, x + fw, y + fh])
    return sortie


def _ann_valides(img, ann):
    """Les annotations décrivent-elles bien cette image (même taille) ?"""
    if not ann:
        return False
    h, w = img.shape[:2]
    aw, ah = ann.get("w"), ann.get("h")
    return not aw or not ah or (abs(aw - w) <= 2 and abs(ah - h) <= 2)


def boites_tetes(img, ann=None, cible="tetes", detecter=True):
    boites = []
    if _ann_valides(img, ann):
        for v in ann.get("visages", []) or []:
            boites.append(list(v["box"][:4]))
        if cible == "tetes":
            for p in ann.get("personnes", []) or []:
                x1, y1, x2, y2 = (float(v) for v in p[:4])
                bw, bh = x2 - x1, y2 - y1
                if bw <= 2 or bh <= 2:
                    continue
                largeur = bw * 0.6
                hauteur = min(bh * 0.24, largeur * 1.35)
                cx = (x1 + x2) / 2
                boites.append([cx - largeur / 2, y1 - 0.03 * bh, cx + largeur / 2, y1 + hauteur])
    if detecter:
        boites += detecter_visages(img)
    return boites


# ---------------------------------------------------------------------------
# Floutage
# ---------------------------------------------------------------------------
def _brouiller(roi, style):
    h, w = roi.shape[:2]
    if style == "noir":
        return np.zeros_like(roi)
    if style == "pixels":
        n = max(3, min(w, h) // 5)  # environ 5 gros pixels par visage
        petit = cv2.resize(roi, (max(1, w // n), max(1, h // n)), interpolation=cv2.INTER_AREA)
        return cv2.resize(petit, (w, h), interpolation=cv2.INTER_NEAREST)
    # flou fort et irréversible : réduction puis flou gaussien (rien de récupérable par « défloutage »)
    # (3 à 4 « pixels » par visage seulement : plus aucun trait reconnaissable, même sur un petit visage)
    petit = cv2.resize(roi, (max(2, min(4, w // 6)), max(2, min(5, h // 6))), interpolation=cv2.INTER_AREA)
    grand = cv2.resize(petit, (w, h), interpolation=cv2.INTER_LINEAR)
    k = max(3, (min(w, h) // 2) | 1)
    return cv2.GaussianBlur(grand, (k, k), 0)


def flouter(img, boites, style="flou", marge=0.25):
    """Copie de l'image avec chaque cadre flouté (ovale, avec une marge). L'image d'origine n'est pas modifiée."""
    if img is None or not boites:
        return img
    sortie = img.copy()
    H, W = img.shape[:2]
    for b in boites:
        x1, y1, x2, y2 = b[:4]
        mx, my = (x2 - x1) * marge, (y2 - y1) * marge
        x1, y1 = int(max(0, x1 - mx)), int(max(0, y1 - my))
        x2, y2 = int(min(W, x2 + mx)), int(min(H, y2 + my))
        if x2 - x1 < 4 or y2 - y1 < 4:
            continue
        roi = sortie[y1:y2, x1:x2]
        masque = np.zeros(roi.shape[:2], np.uint8)
        cv2.ellipse(masque, ((x2 - x1) // 2, (y2 - y1) // 2), ((x2 - x1) // 2, (y2 - y1) // 2), 0, 0, 360, 255, -1)
        brouille = _brouiller(roi, style)
        roi[masque > 0] = brouille[masque > 0]
    return sortie


def proteger(img, ann, cfg, detecter=True, marge=0.25):
    """Image prête à être enregistrée ou envoyée : têtes floutées si l'option est cochée, sinon inchangée.

    detecter=True (photos) : recherche de visages en plus sur l'image. Pour la vidéo (chaque image), on s'appuie
    sur la dernière analyse avec une marge plus large, car les personnes ont pu bouger depuis."""
    if img is None or not actif(cfg):
        return img
    try:
        boites = boites_tetes(img, ann, cfg.get("confidentialite.cible"), detecter)
        return flouter(img, boites, cfg.get("confidentialite.style"), marge)
    except Exception:  # noqa: BLE001
        # en cas d'erreur imprévue, on préfère une image entièrement floutée à une image avec des visages
        return cv2.GaussianBlur(img, (0, 0), 25)
