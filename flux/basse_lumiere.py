"""Amélioration des images de nuit : pour l'analyse (détection) et pour l'affichage.

Deux traitements distincts :
- ameliorer(...)            : image destinée à la détection. Débruitage puis éclaircissement, sur une copie
                              réduite (le modèle travaille de toute façon en 640 px). Quelques dizaines de ms.
- AmelioreurAffichage       : image montrée à l'écran, en pleine résolution, sans débruitage destructeur,
                              assez rapide (quelques ms) pour suivre chaque image de la caméra.

Les caméras infrarouges filment la nuit en noir et blanc : l'image est alors traitée en niveaux de gris
(plus rapide, et sans les taches de couleur du débruitage couleur), avec un contraste plus doux pour ne pas
gonfler le grain du capteur ni brûler le ciel.
"""

import threading

import cv2
import numpy as np

CIBLE = 0.40  # luminosité moyenne visée (0-1) après éclaircissement


def est_monochrome(img):
    """Vrai pour une image en noir et blanc (caméra en mode infrarouge), même stockée en couleur."""
    if img.ndim == 2 or img.shape[2] == 1:
        return True
    petite = cv2.resize(img, (80, 45), interpolation=cv2.INTER_AREA).astype(np.int16)
    b, g, r = petite[..., 0], petite[..., 1], petite[..., 2]
    return float(np.abs(b - g).mean() + np.abs(g - r).mean()) < 6.0


def _luminance_canal(img, mono):
    """Canal de luminosité (niveaux de gris ou L de LAB) et de quoi reconstruire l'image."""
    if mono:
        gris = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return gris, None
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    return l, (a, b)


def _reconstruire(y, reste, mono):
    if mono:
        return cv2.cvtColor(y, cv2.COLOR_GRAY2BGR)
    return cv2.cvtColor(cv2.merge((y, *reste)), cv2.COLOR_LAB2BGR)


def gamma_pour(moyenne, gamma_max):
    """Gamma qui amène la luminosité moyenne vers CIBLE, borné pour ne jamais délaver l'image."""
    m = min(max(moyenne / 255.0, 1e-3), 0.999)
    if m >= CIBLE:
        return 1.0
    return float(np.clip(np.log(m) / np.log(CIBLE), 1.0, gamma_max))


_LUTS = {}


def lut_gamma(gamma):
    cle = round(gamma, 2)
    t = _LUTS.get(cle)
    if t is None:
        t = ((np.arange(256) / 255.0) ** (1.0 / cle) * 255.0 + 0.5).clip(0, 255).astype(np.uint8)
        if len(_LUTS) > 400:
            _LUTS.clear()
        _LUTS[cle] = t
    return t


_CLAHE = threading.local()


def clahe(limite, tuiles=8):
    cle = (round(limite, 2), tuiles)
    cache = getattr(_CLAHE, "cache", None)
    if cache is None:
        cache = _CLAHE.cache = {}
    if cle not in cache:
        cache[cle] = cv2.createCLAHE(clipLimit=max(0.1, limite), tileGridSize=(tuiles, tuiles))
    return cache[cle]


def niveau_bruit(y):
    """Écart-type approximatif du bruit (méthode de Immerkær), sur une copie réduite."""
    petite = cv2.resize(y, (min(320, y.shape[1]), min(180, y.shape[0])), interpolation=cv2.INTER_AREA)
    noyau = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], np.float32)
    lap = cv2.filter2D(petite.astype(np.float32), -1, noyau)
    h, w = petite.shape[:2]
    return float(np.sqrt(np.pi / 2.0) * np.abs(lap).sum() / (6.0 * max(1, (w - 2) * (h - 2))))


def ameliorer(img, debruitage=10, contraste=1.8, fine=False):
    """Image éclaircie pour la détection. Garde la taille d'origine (coordonnées des détections valables)."""
    h, w = img.shape[:2]
    f = min(1.0, (960.0 if fine else 640.0) / max(h, w))
    x = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA) if f < 1 else img
    mono = est_monochrome(x)
    y, reste = _luminance_canal(x, mono)
    # 1) débruiter AVANT d'éclaircir (sinon on éclaircit le grain), avec une force adaptée au bruit réel
    if debruitage:
        sigma = niveau_bruit(y)
        force = float(min(debruitage, max(3.0, 1.3 * sigma)))
        if sigma > 1.5:
            y = cv2.fastNlMeansDenoising(y, None, force, 5, 15 if fine else 11)
            if reste is not None and fine:
                reste = tuple(cv2.GaussianBlur(c, (5, 5), 0) for c in reste)  # chrominance : simple lissage
    # 2) éclaircir
    y = cv2.LUT(y, lut_gamma(gamma_pour(float(y.mean()), 3.0 if fine else 2.6)))
    # 3) contraste local, plus doux en infrarouge (grain et ciel)
    if contraste > 0:
        y = clahe(contraste * (0.75 if mono else 1.0)).apply(y)
    sortie = _reconstruire(y, reste, mono)
    return cv2.resize(sortie, (w, h), interpolation=cv2.INTER_LINEAR) if f < 1 else sortie


class AmelioreurAffichage:
    """Éclaircit chaque image affichée, en pleine résolution, en quelques millisecondes.

    Pas de débruitage lourd (c'est lui qui donnait l'effet « peinture » baveux) : un gamma lissé dans le temps
    (pas de scintillement d'une image à l'autre) et un contraste local modéré."""

    def __init__(self):
        self._gamma = None
        self._mono = None
        self._n = 0

    def appliquer(self, img, contraste=1.8):
        if img is None or img.size == 0:
            return img
        if self._mono is None or self._n % 50 == 0:  # le passage jour/nuit change le mode de la caméra
            self._mono = est_monochrome(img)
        self._n += 1
        y, reste = _luminance_canal(img, self._mono)
        petite = cv2.resize(y, (160, 90), interpolation=cv2.INTER_AREA)
        g = gamma_pour(float(petite.mean()), 2.2)
        self._gamma = g if self._gamma is None else 0.9 * self._gamma + 0.1 * g
        y = cv2.LUT(y, lut_gamma(self._gamma))
        if contraste > 0:
            # léger lissage avant le contraste local : évite que le grain du capteur soit renforcé
            y = clahe(min(contraste, 2.0) * (0.6 if self._mono else 0.8)).apply(cv2.GaussianBlur(y, (3, 3), 0))
        return _reconstruire(y, reste, self._mono)
