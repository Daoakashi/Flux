"""Éléments d'interface de Flux : boutons, bascules, voyants, notifications, navigation et vue vidéo."""

import math
import time

import cv2
import numpy as np
from PySide6.QtCore import (QEasingCurve, QParallelAnimationGroup, QPoint, QPointF, QPropertyAnimation, QRectF, QSize,
                            Qt, QTimer, QVariantAnimation, Signal, Property)
from PySide6.QtGui import QColor, QFontMetrics, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractButton, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from .theme import C, T, couleur, dessiner_icone, dessiner_logo, melange, police
from .vision import NOMS_VEHICULES, iou


def _anim(parent, rappel, courbe=QEasingCurve.Type.OutCubic):
    a = QVariantAnimation(parent)
    a.setEasingCurve(courbe)
    a.valueChanged.connect(rappel)
    return a


def _aller(anim, depuis, vers, duree):
    anim.stop()
    anim.setDuration(T.ms(duree))
    anim.setStartValue(float(depuis))
    anim.setEndValue(float(vers))
    anim.start()


class Bouton(QPushButton):
    """Bouton à survol animé. Styles : primaire (accent), discret, danger, fantome. Icône facultative."""

    def __init__(self, texte="", style="discret", icone=None, parent=None):
        super().__init__(texte, parent)
        self._style, self._icone, self._t = style, icone, 0.0
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._a = _anim(self, self._maj)

    def definir_style(self, style):
        self._style = style
        self.update()

    def definir_icone(self, icone):
        self._icone = icone
        self.update()

    def sizeHint(self):
        h = int(36 * max(0.85, T.densite))
        larg = QFontMetrics(police(None, True)).horizontalAdvance(self.text()) + (28 if self.text() else 0)
        if self._icone:
            larg += 22 if self.text() else h
        return QSize(max(larg, h), h)

    def minimumSizeHint(self):
        return self.sizeHint()

    def _maj(self, v):
        self._t = float(v)
        self.update()

    def enterEvent(self, e):
        _aller(self._a, self._t, 1.0, 140)
        super().enterEvent(e)

    def leaveEvent(self, e):
        _aller(self._a, self._t, 0.0, 160)
        super().leaveEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        t = 0.0 if not self.isEnabled() else (1.0 if self.isDown() else self._t)
        if self._style == "primaire":
            fond = melange("accent", "accent_vif", t)
            bord, texte = fond, QColor(C["accent_texte"])
        elif self._style == "danger":
            fond = melange(couleur("danger", 0), couleur("danger", 40), t)
            bord, texte = couleur("danger", 140 + 80 * t), QColor(C["danger"])
        elif self._style == "fantome":
            fond = melange(couleur("surface2", 0), couleur("surface2", 255), t)
            bord, texte = couleur("trait", 0), QColor(C["texte"])
        else:
            fond = melange("surface", "surface2", t)
            bord, texte = melange("trait", "texte3", t * 0.6), QColor(C["texte"])
        if not self.isEnabled():
            p.setOpacity(0.45)
        p.setPen(QPen(bord, 1))
        p.setBrush(fond)
        p.drawRoundedRect(r, T.rayon, T.rayon)
        if self.hasFocus():
            p.setPen(QPen(couleur("accent", 150), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(2, 2, -2, -2), max(2, T.rayon - 2), max(2, T.rayon - 2))
        zone = QRectF(r)
        if self._icone:
            fm = QFontMetrics(police(None, True))
            largeur_texte = fm.horizontalAdvance(self.text()) if self.text() else 0
            total = 18 + (8 + largeur_texte if self.text() else 0)
            x0 = r.center().x() - total / 2
            dessiner_icone(p, self._icone, QRectF(x0, r.center().y() - 9, 18, 18), texte)
            zone = QRectF(x0 + 26, r.top(), largeur_texte + 2, r.height())
        if self.text():
            p.setPen(texte)
            p.setFont(police(None, True))
            p.drawText(zone, Qt.AlignmentFlag.AlignCenter if not self._icone else
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())


class Pastille(QAbstractButton):
    """Bascule en forme de pastille (Visages, Expressions, Plaques)."""

    def __init__(self, texte, teinte, parent=None):
        super().__init__(parent)
        self.setText(texte)
        self._teinte = teinte
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._h, self._c = 0.0, 0.0
        self._ah = _anim(self, lambda v: self._set("_h", v))
        self._ac = _anim(self, lambda v: self._set("_c", v))
        self.toggled.connect(lambda e: _aller(self._ac, self._c, 1.0 if e else 0.0, 200))

    def _set(self, nom, v):
        setattr(self, nom, float(v))
        self.update()

    def regler(self, etat):
        self.blockSignals(True)
        self.setChecked(etat)
        self.blockSignals(False)
        self._c = 1.0 if etat else 0.0
        self.update()

    def enterEvent(self, e):
        _aller(self._ah, self._h, 1.0, 140)
        super().enterEvent(e)

    def leaveEvent(self, e):
        _aller(self._ah, self._h, 0.0, 140)
        super().leaveEvent(e)

    def sizeHint(self):
        return QSize(QFontMetrics(police(None, True)).horizontalAdvance(self.text()) + 44, int(32 * max(0.85, T.densite)))

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        teinte = C[self._teinte] if self._teinte in C else self._teinte
        fond = melange(couleur("surface", 255), melange("surface", teinte, 0.22), self._c)
        fond = melange(fond, couleur("surface2"), self._h * (1 - self._c) * 0.9)
        p.setPen(QPen(melange("trait", teinte, self._c), 1))
        p.setBrush(fond)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(teinte) if getattr(self, "point_colore", False) else melange("texte3", teinte, self._c))
        p.drawEllipse(QPointF(r.left() + 15, r.center().y()), 3.5 + self._c, 3.5 + self._c)
        p.setPen(melange("texte2", "texte", self._c))
        p.setFont(police(None, True))
        p.drawText(r.adjusted(25, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())


class Interrupteur(QAbstractButton):
    """Bascule à bouton glissant."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(42, 24)
        self._pos = 0.0
        self._a = QPropertyAnimation(self, b"position", self)
        self._a.setEasingCurve(QEasingCurve.Type.OutBack)
        self.toggled.connect(self._basculer)

    def _get(self):
        return self._pos

    def _setp(self, v):
        self._pos = v
        self.update()

    position = Property(float, _get, _setp)

    def _basculer(self, etat):
        self._a.stop()
        self._a.setDuration(T.ms(220))
        self._a.setStartValue(self._pos)
        self._a.setEndValue(1.0 if etat else 0.0)
        self._a.start()

    def regler(self, etat):
        self.blockSignals(True)
        self.setChecked(etat)
        self.blockSignals(False)
        self._a.stop()
        self._pos = 1.0 if etat else 0.0
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = max(0.0, min(1.0, self._pos))
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(melange("trait", "accent", t))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = r.left() + 3 + self._pos * (r.width() - 6 - d)
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QRectF(x, r.top() + 3, d, d))
        if not self.isEnabled():
            p.fillRect(self.rect(), couleur("fond", 120))


class BoutonX(QAbstractButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(20, 20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._t = 0.0
        self._a = _anim(self, lambda v: (setattr(self, "_t", float(v)), self.update()))

    def enterEvent(self, e):
        _aller(self._a, self._t, 1.0, 120)

    def leaveEvent(self, e):
        _aller(self._a, self._t, 0.0, 120)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(couleur("danger", 60 * self._t))
        p.drawEllipse(c, 9, 9)
        p.setPen(QPen(melange("texte3", "danger", self._t), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(c.x() - 3.2, c.y() - 3.2), QPointF(c.x() + 3.2, c.y() + 3.2))
        p.drawLine(QPointF(c.x() - 3.2, c.y() + 3.2), QPointF(c.x() + 3.2, c.y() - 3.2))


class Voyant(QWidget):
    """Témoin d'état : arrêt, direct, chargement, alerte (pulsation)."""

    TEINTES = {"arret": "texte3", "direct": "succes", "alerte": "danger", "chargement": "attention"}

    def __init__(self, diametre=12, parent=None):
        super().__init__(parent)
        self._d = diametre
        self._etat = "arret"
        self.setFixedSize(diametre + 10, diametre + 10)
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self.update)

    def etat(self):
        return self._etat

    def regler(self, etat):
        if etat == self._etat:
            return
        self._etat = etat
        (self._timer.start if etat in ("alerte", "chargement") and T.animations else self._timer.stop)()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        base = C[self.TEINTES[self._etat]]
        pulse = (0.5 + 0.5 * math.sin(time.time() * (7.0 if self._etat == "alerte" else 4.0))
                 if T.animations and self._etat in ("alerte", "chargement") else 0.6)
        p.setPen(Qt.PenStyle.NoPen)
        if self._etat != "arret":
            p.setBrush(couleur(base, 40 + 70 * pulse))
            r = self._d / 2 + 2 + 2.5 * pulse
            p.drawEllipse(c, r, r)
        p.setBrush(couleur(base))
        p.drawEllipse(c, self._d / 2 - 1, self._d / 2 - 1)


class Repliable(QWidget):
    """Conteneur qui se déplie en douceur."""

    def __init__(self, contenu, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(contenu)
        self._contenu = contenu
        self._ouvert = False
        self.setMaximumHeight(0)
        self._a = QPropertyAnimation(self, b"maximumHeight", self)
        self._a.setEasingCurve(QEasingCurve.Type.OutCubic)

    def ouvrir(self, ouvert, instantane=False):
        if ouvert == self._ouvert:
            return
        self._ouvert = ouvert
        self._a.stop()
        cible = self._contenu.sizeHint().height() + 4 if ouvert else 0
        if instantane or not T.animations:
            self.setMaximumHeight(cible)
            return
        self._a.setDuration(T.ms(240))
        self._a.setStartValue(self.maximumHeight())
        self._a.setEndValue(cible)
        self._a.start()


def separateur():
    f = QFrame()
    f.setObjectName("sep")
    f.setFixedHeight(1)
    return f


def etiquette(texte, nom="aide", mots=True):
    lab = QLabel(texte)
    lab.setObjectName(nom)
    lab.setWordWrap(mots)
    return lab


def ligne_option(texte, controle, aide=None):
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(2)
    h = QHBoxLayout()
    h.setContentsMargins(0, 0, 0, 0)
    lab = QLabel(texte)
    lab.setWordWrap(True)
    h.addWidget(lab, 1)
    h.addWidget(controle)
    v.addLayout(h)
    if aide:
        v.addWidget(etiquette(aide))
    return w


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
class Toast(QFrame):
    TEINTES = {"info": "accent", "ok": "succes", "erreur": "danger", "alerte": "danger"}

    def __init__(self, parent, texte, genre):
        super().__init__(parent)
        self.setObjectName("toast")
        self.genre = genre
        self.restyler()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 16, 10)
        lab = QLabel(texte)
        lab.setWordWrap(True)
        lay.addWidget(lab)
        self.setFixedWidth(380)
        self.adjustSize()
        self.eff = QGraphicsOpacityEffect(self)
        self.eff.setOpacity(0.0)
        self.setGraphicsEffect(self.eff)
        self.anims = []

    def restyler(self):
        self.setStyleSheet(f"#toast {{ background: {C['surface']}; border: 1px solid {C['trait']}; "
                           f"border-left: 4px solid {C[self.TEINTES.get(self.genre, 'accent')]}; "
                           f"border-radius: {T.rayon}px; }} #toast QLabel {{ color: {C['texte']}; }}")


class Toasts:
    """Empile les notifications en bas à droite d'un widget hôte."""

    def __init__(self, hote):
        self.hote = hote
        self.liste = []

    def montrer(self, texte, genre="info", duree=4200):
        if len(self.liste) >= 5:
            self.retirer(self.liste[0])
        t = Toast(self.hote, texte, genre)
        self.liste.append(t)
        t.show()
        t.raise_()
        self._placer(nouveau=t)
        QTimer.singleShot(duree, lambda: self.retirer(t))

    def _cible(self, rang, hauteurs):
        y = self.hote.height() - 24 - sum(hauteurs[:rang + 1]) - rang * 10
        return QPoint(self.hote.width() - 380 - 24, y)

    def _placer(self, nouveau=None):
        hauteurs = [t.height() for t in reversed(self.liste)]
        for rang, t in enumerate(reversed(self.liste)):
            cible = self._cible(rang, hauteurs)
            if t is nouveau:
                t.move(cible + QPoint(0, 16) if T.animations else cible)
                g = QParallelAnimationGroup(t)
                a1 = QPropertyAnimation(t, b"pos")
                a1.setDuration(T.ms(260))
                a1.setStartValue(t.pos())
                a1.setEndValue(cible)
                a1.setEasingCurve(QEasingCurve.Type.OutCubic)
                a2 = QPropertyAnimation(t.eff, b"opacity")
                a2.setDuration(T.ms(220))
                a2.setStartValue(0.0 if T.animations else 1.0)
                a2.setEndValue(1.0)
                g.addAnimation(a1)
                g.addAnimation(a2)
                g.start()
                t.anims.append(g)
                if not T.animations:
                    t.eff.setOpacity(1.0)
            else:
                a = QPropertyAnimation(t, b"pos")
                a.setDuration(T.ms(200))
                a.setStartValue(t.pos())
                a.setEndValue(cible)
                a.setEasingCurve(QEasingCurve.Type.OutCubic)
                a.start()
                t.anims.append(a)

    def retirer(self, t):
        if t not in self.liste:
            return
        self.liste.remove(t)
        a = QPropertyAnimation(t.eff, b"opacity", t)
        a.setDuration(T.ms(220))
        a.setStartValue(t.eff.opacity())
        a.setEndValue(0.0)
        a.finished.connect(t.deleteLater)
        a.start()
        t.anims.append(a)
        if not T.animations:
            t.deleteLater()
        self._placer()

    def restyler(self):
        for t in self.liste:
            t.restyler()

    def replacer(self):
        hauteurs = [t.height() for t in reversed(self.liste)]
        for rang, t in enumerate(reversed(self.liste)):
            t.move(self._cible(rang, hauteurs))


# ---------------------------------------------------------------------------
# Navigation latérale
# ---------------------------------------------------------------------------
class BoutonNav(QAbstractButton):
    def __init__(self, texte, icone, parent=None):
        super().__init__(parent)
        self.setText(texte)
        self._icone = icone
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._h, self._c = 0.0, 0.0
        self._ah = _anim(self, lambda v: (setattr(self, "_h", float(v)), self.update()))
        self._ac = _anim(self, lambda v: (setattr(self, "_c", float(v)), self.update()))
        self.toggled.connect(lambda e: _aller(self._ac, self._c, 1.0 if e else 0.0, 220))
        self.compact = False
        self.compteur = 0
        self.setToolTip(texte)

    def sizeHint(self):
        return QSize(44 if self.compact else 200, int(42 * max(0.85, T.densite)))

    def enterEvent(self, e):
        _aller(self._ah, self._h, 1.0, 120)

    def leaveEvent(self, e):
        _aller(self._ah, self._h, 0.0, 160)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(6, 2, -6, -2)
        fond = melange(couleur("surface2", 0), couleur("surface2"), self._h * (1 - self._c))
        fond = melange(fond, "accent_doux", self._c)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fond)
        p.drawRoundedRect(r, T.rayon, T.rayon)
        if self._c > 0.01:  # barre d'accent qui pousse depuis le centre
            hb = (r.height() - 16) * self._c
            p.setBrush(couleur("accent"))
            p.drawRoundedRect(QRectF(r.left() - 6, r.center().y() - hb / 2, 3, hb), 1.5, 1.5)
        teinte = melange("texte2", "accent_vif", self._c)
        ic = QRectF(r.left() + (r.width() - 20) / 2 if self.compact else r.left() + 12, r.center().y() - 10, 20, 20)
        dessiner_icone(p, self._icone, ic, teinte)
        if not self.compact:
            p.setPen(melange("texte2", "texte", max(self._c, self._h * 0.6)))
            p.setFont(police(None, self._c > 0.5))
            p.drawText(r.adjusted(44, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())
        if self.compteur:
            t = str(self.compteur) if self.compteur < 100 else "99+"
            p.setFont(police(max(9, T.taille - 3), True))
            w = QFontMetrics(p.font()).horizontalAdvance(t) + 10
            b = QRectF(r.right() - w - 8, r.center().y() - 9, w, 18) if not self.compact else QRectF(
                r.right() - w + 2, r.top() + 1, w, 16)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(couleur("danger"))
            p.drawRoundedRect(b, 9, 9)
            p.setPen(QColor("#FFFFFF"))
            p.drawText(b, Qt.AlignmentFlag.AlignCenter, t)


class Logo(QWidget):
    """Logo animé (les courants ondulent doucement quand une caméra est en direct)."""

    def __init__(self, taille=34, parent=None):
        super().__init__(parent)
        self.setFixedSize(taille, taille)
        self.phase = 0.0
        self.actif = False
        self._t = QTimer(self)
        self._t.setInterval(50)
        self._t.timeout.connect(self._tic)

    def animer(self, actif):
        self.actif = actif
        (self._t.start if actif and T.animations else self._t.stop)()

    def _tic(self):
        self.phase += 0.12
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        dessiner_logo(p, QRectF(1, 1, self.width() - 2, self.height() - 2), self.phase)


# ---------------------------------------------------------------------------
# Vue vidéo : image + repères de cadrage animés + zone d'intérêt
# ---------------------------------------------------------------------------
class VueVideo(QWidget):
    zoneChangee = Signal(object)     # ancienne API (une seule zone) : première zone ou None
    zonesChangees = Signal(object)   # liste de zones {"nom", "rect": (x1, y1, x2, y2) normalisés}
    doubleClique = Signal()
    CATEGORIES = (("vehicules", "o_vehicule"), ("personnes", "o_personne"), ("visages", "o_visage"),
                  ("plaques", "o_plaque"))

    def __init__(self, parent=None, zone_active=True, compact=False):
        super().__init__(parent)
        # compact : petite vignette d'un mur vidéo (image réduite, rafraîchissement plus calme, bandeau allégé)
        self.compact = compact
        self.setMinimumSize(*((160, 100) if compact else (380, 240)))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.zone_active = zone_active
        self._nd = None
        self._image = None
        self._cache = None
        self._taille = (1, 1)
        self._boites = {c: [] for c, _ in self.CATEGORIES}
        self._zones = []
        self._trace = None  # rectangle en cours de dessin
        self._glisse = None
        self._etat, self._statut, self._compteurs, self._fps = "arret", "Aucun flux", [], 0.0
        self._badges = []
        self._geom = (0.0, 0.0, 1.0)
        self._t_dernier = time.time()
        self.message_vide = "Aucune image"
        self._timer = QTimer(self)
        self._timer.setInterval(66 if compact else 33)
        self._timer.timeout.connect(self.update)
        self._timer.start()

    def mouseDoubleClickEvent(self, e):
        self.doubleClique.emit()

    # --- données ---------------------------------------------------------------
    def definir_image(self, frame, ann=None, heure=0.0):
        h, w = frame.shape[:2]
        if self.compact:  # vignette : inutile de garder 1080p en mémoire pour l'afficher en 480 px
            cible = int(self.width() * self.devicePixelRatioF()) + 2
            if cible > 40 and w > cible * 1.3:
                frame = cv2.resize(frame, (cible, max(1, int(h * cible / w))), interpolation=cv2.INTER_AREA)
        self._nd = np.ascontiguousarray(frame)
        self._image = QImage(self._nd.data, self._nd.shape[1], self._nd.shape[0], self._nd.strides[0],
                             QImage.Format.Format_BGR888)
        self._taille = (w, h)  # taille d'origine : les cadres de détection sont exprimés dans ce repère
        self._cache = None  # image redimensionnée : recalculée une seule fois par nouvelle image
        if heure:
            delai = max(0.0, time.time() - heure)
            self.delai_affichage = delai if not getattr(self, "delai_affichage", 0) else \
                0.85 * self.delai_affichage + 0.15 * delai
        if ann is not None:
            self._maj_boites(ann)

    def _image_a_taille(self, w_, h_):
        """Redimensionne une seule fois par image (et non à chaque rafraîchissement de l'écran)."""
        cle = (int(w_), int(h_))
        if self._cache is None or self._cache[0] != cle:
            iw, ih = self._image.width(), self._image.height()
            if abs(iw - cle[0]) <= 1 and abs(ih - cle[1]) <= 1:
                img = self._image
            else:
                img = self._image.scaled(cle[0], cle[1], Qt.AspectRatioMode.IgnoreAspectRatio,
                                         Qt.TransformationMode.FastTransformation if self.compact
                                         else Qt.TransformationMode.SmoothTransformation)
            self._cache = (cle, img)
        return self._cache[1]

    def definir_annotations(self, ann):
        if ann is not None:
            self._maj_boites(ann)

    def effacer(self):
        self._image = self._nd = None
        for c in self._boites:
            self._boites[c] = []

    def definir_zone(self, zone):
        self.definir_zones([{"nom": "Zone 1", "rect": tuple(zone)}] if zone else [])

    def definir_zones(self, zones):
        self._zones = [{"nom": str(z.get("nom") or f"Zone {i + 1}"), "rect": tuple(z["rect"])}
                       for i, z in enumerate(zones or []) if z and z.get("rect")]

    def zones(self):
        return [dict(z, rect=list(z["rect"])) for z in self._zones]

    def _emettre_zones(self):
        self.zonesChangees.emit(self.zones())
        self.zoneChangee.emit(tuple(self._zones[0]["rect"]) if self._zones else None)

    def _nom_libre(self):
        noms, i = {z["nom"] for z in self._zones}, len(self._zones) + 1
        while f"Zone {i}" in noms:
            i += 1
        return f"Zone {i}"

    def regler_etat(self, etat, statut, compteurs=(), fps=0.0, badges=()):
        self._etat, self._statut, self._compteurs, self._fps, self._badges = etat, statut, list(compteurs), fps, list(badges)

    @staticmethod
    def _cle(cat, n):
        if cat == "visages":
            return list(n["box"]), n
        return list(n[:4]), n

    def _maj_boites(self, ann):
        t = time.time()
        noms_pistes = {}
        for p in ann.get("pistes", []):
            noms_pistes[tuple(p["box"])] = p
        for cat, _ in self.CATEGORIES:
            existantes = self._boites[cat]
            utilisees, ajoutees = set(), []
            for n in ann.get(cat, []):
                box, data = self._cle(cat, n)
                if cat == "personnes":
                    data = (n, noms_pistes.get(tuple(n[:4])))
                meilleur, mi = None, 0.25
                for i, e in enumerate(existantes):
                    if i in utilisees or e["mort"] is not None:
                        continue
                    v = iou(box, e["cible"])
                    if v > mi:
                        mi, meilleur = v, i
                if meilleur is not None:
                    e = existantes[meilleur]
                    utilisees.add(meilleur)
                    e["cible"], e["data"] = box, data
                else:
                    ajoutees.append({"cur": list(box), "cible": box, "data": data, "t0": t, "mort": None})
            for i, e in enumerate(existantes):
                if i not in utilisees and e["mort"] is None:
                    e["mort"] = t
            existantes.extend(ajoutees)

    # --- zone d'intérêt -------------------------------------------------------------
    def _vers_norm(self, pos):
        ox, oy, s = self._geom
        iw, ih = self._taille
        return (min(max((pos.x() - ox) / s / iw, 0.0), 1.0), min(max((pos.y() - oy) / s / ih, 0.0), 1.0))

    def _zone_sous(self, pos):
        x, y = self._vers_norm(pos)
        for i in range(len(self._zones) - 1, -1, -1):
            x1, y1, x2, y2 = self._zones[i]["rect"]
            if x1 <= x <= x2 and y1 <= y <= y2:
                return i
        return None

    def mousePressEvent(self, e):
        if self._image is None or not self.zone_active:
            return
        if e.button() == Qt.MouseButton.RightButton:
            self._menu_zones(e)
        elif e.button() == Qt.MouseButton.LeftButton:
            self._glisse = self._vers_norm(e.position())

    def _menu_zones(self, e):
        from PySide6.QtWidgets import QInputDialog, QMenu
        i = self._zone_sous(e.position())
        m = QMenu(self)
        if i is not None:
            nom = self._zones[i]["nom"]

            def renommer():
                nouveau, ok = QInputDialog.getText(self, "Renommer la zone", "Nom de la zone :", text=nom)
                if ok and nouveau.strip():
                    self._zones[i]["nom"] = nouveau.strip()
                    self._emettre_zones()

            def supprimer():
                del self._zones[i]
                self._emettre_zones()
            m.addAction(f"Renommer « {nom} »…", renommer)
            m.addAction(f"Supprimer « {nom} »", supprimer)
        if self._zones:
            m.addSeparator()
            m.addAction("Effacer toutes les zones", lambda: (self._zones.clear(), self._emettre_zones()))
        if not m.isEmpty():
            m.exec(e.globalPosition().toPoint())

    def mouseMoveEvent(self, e):
        if self._glisse is not None:
            x1, y1 = self._glisse
            x2, y2 = self._vers_norm(e.position())
            self._trace = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))

    def mouseReleaseEvent(self, e):
        if self._glisse is None:
            return
        self._glisse = None
        z, self._trace = self._trace, None
        if z is not None and z[2] - z[0] >= 0.02 and z[3] - z[1] >= 0.02:
            self._zones.append({"nom": self._nom_libre(), "rect": z})
            self._emettre_zones()

    # --- dessin -------------------------------------------------------------------------
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing if self.compact else
                         QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
                         | QPainter.RenderHint.TextAntialiasing)
        now = time.time()
        dt = min(0.1, now - self._t_dernier)
        self._t_dernier = now
        cadre = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        chemin = QPainterPath()
        chemin.addRoundedRect(cadre, T.rayon + 4, T.rayon + 4)
        p.fillPath(chemin, QColor(C["video"]))
        p.setClipPath(chemin)
        if self._image is not None:
            iw, ih = self._taille
            s = min(cadre.width() / iw, cadre.height() / ih)
            w_, h_ = iw * s, ih * s
            ox, oy = cadre.left() + (cadre.width() - w_) / 2, cadre.top() + (cadre.height() - h_) / 2
            self._geom = (ox, oy, s)
            p.drawImage(QRectF(ox, oy, w_, h_), self._image_a_taille(w_ * self.devicePixelRatioF(),
                                                                     h_ * self.devicePixelRatioF()))
            self._dessiner_zone(p, now, QRectF(ox, oy, w_, h_))
            self._dessiner_reperes(p, now, dt)
            self.setCursor(Qt.CursorShape.CrossCursor if self.zone_active else Qt.CursorShape.ArrowCursor)
        else:
            self._dessiner_attente(p, cadre, now)
        self._dessiner_hud(p, cadre, now)
        if self._etat == "alerte":
            pulse = 0.5 + 0.5 * math.sin(now * 5.5) if T.animations else 0.7
            p.setPen(QPen(couleur("danger", 70 + 150 * pulse), 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(cadre.adjusted(1.5, 1.5, -1.5, -1.5), T.rayon + 3, T.rayon + 3)
        p.setClipping(False)
        p.setPen(QPen(couleur("trait"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(chemin)

    def _dessiner_attente(self, p, cadre, now):
        c = cadre.center()
        p.setBrush(Qt.BrushStyle.NoBrush)
        blanc = QColor(255, 255, 255)
        if self._etat == "chargement":
            p.setPen(QPen(QColor(255, 255, 255, 30), 4))
            p.drawEllipse(c, 26, 26)
            angle = (now * 300 if T.animations else 0) % 360
            p.setPen(QPen(couleur("accent"), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(QRectF(c.x() - 26, c.y() - 26, 52, 52), int(-angle * 16), 100 * 16)
        else:
            for r, a in ((46, 26), (32, 40), (18, 60)):
                blanc.setAlpha(a)
                p.setPen(QPen(blanc, 2))
                p.drawEllipse(c, r, r)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 50))
            p.drawEllipse(c, 6, 6)
        p.setPen(QColor(255, 255, 255, 150))
        p.setFont(police(T.taille + 1))
        p.drawText(QRectF(cadre.left() + 20, c.y() + 62, cadre.width() - 40, 44),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                   self._statut if self._etat != "arret" or self._statut else self.message_vide)

    def _dessiner_zone(self, p, now, rect_img):
        rects = [(z["nom"], z["rect"]) for z in self._zones] + ([("", self._trace)] if self._trace else [])
        if not rects:
            return
        ox, oy, s = self._geom
        iw, ih = self._taille
        geo = [(nom, QRectF(ox + x1 * iw * s, oy + y1 * ih * s, (x2 - x1) * iw * s, (y2 - y1) * ih * s))
               for nom, (x1, y1, x2, y2) in rects]
        sombre = QPainterPath()
        sombre.addRect(rect_img)
        trous = QPainterPath()
        for _, zr in geo:
            trous.addRect(zr)
        p.fillPath(sombre.subtracted(trous.simplified()), QColor(0, 0, 0, 120))
        pen = QPen(couleur("o_plaque"), 1.8, Qt.PenStyle.CustomDashLine)
        pen.setDashPattern([5, 4])
        pen.setDashOffset((now * 14) % 9 if T.animations else 0)
        p.setFont(police(max(9, T.taille - 3), True))
        fm = QFontMetrics(p.font())
        for nom, zr in geo:
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(zr, 4, 4)
            if nom and zr.width() > 30:
                texte = fm.elidedText(nom, Qt.TextElideMode.ElideRight, int(zr.width()) - 8)
                r = QRectF(zr.left() + 4, zr.top() + 4, fm.horizontalAdvance(texte) + 12, fm.height() + 4)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(couleur("o_plaque", 225))
                p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
                p.setPen(QColor(8, 14, 26))
                p.drawText(r, Qt.AlignmentFlag.AlignCenter, texte)

    @staticmethod
    def _crochets(p, rect, couleur_, longueur, epaisseur):
        fin = QColor(couleur_)
        fin.setAlpha(int(couleur_.alpha() * 0.3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(fin, 1))
        p.drawRoundedRect(rect, 3, 3)
        p.setPen(QPen(couleur_, epaisseur, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        l = min(longueur, rect.width() / 2.2, rect.height() / 2.2)
        for cx, cy, dx, dy in ((rect.left(), rect.top(), 1, 1), (rect.right(), rect.top(), -1, 1),
                               (rect.left(), rect.bottom(), 1, -1), (rect.right(), rect.bottom(), -1, -1)):
            ch = QPainterPath(QPointF(cx + dx * l, cy))
            ch.lineTo(cx, cy)
            ch.lineTo(cx, cy + dy * l)
            p.drawPath(ch)

    @staticmethod
    def _libelle(cat, data):
        if cat == "personnes":
            n, piste = data
            if piste and piste.get("personne"):
                return piste["personne"][1]
            return f"Personne  {n[4]:.0%}"
        if cat == "vehicules":
            return f"{NOMS_VEHICULES.get(data[5], 'Véhicule')}  {data[4]:.0%}"
        if cat == "visages":
            nom = data["personne"][1] if data.get("personne") else ""
            if data.get("expression"):
                return f"{nom} · {data['expression']}" if nom else f"{data['expression']}  {data['proba']:.0%}"
            return nom or "Visage"
        return data[4] or "Plaque"

    def _teinte_personne(self, data, defaut):
        n, piste = data
        if piste and piste.get("personne"):
            cat = piste["personne"][2]
            return {"surveille": "danger", "inconnu": "attention", "liste_noire": "liste_noire"}.get(cat, "succes")
        return defaut

    def _dessiner_reperes(self, p, now, dt):
        ox, oy, s = self._geom
        k = 1.0 if not T.animations else 1 - math.exp(-dt * 16)
        for cat, teinte_defaut in self.CATEGORIES:
            vivantes = []
            for b in self._boites[cat]:
                if b["mort"] is not None and (not T.animations or now - b["mort"] > 0.3):
                    continue
                vivantes.append(b)
                b["cur"] = [c + (t - c) * k for c, t in zip(b["cur"], b["cible"])]
                a = (1 - (1 - min(1.0, (now - b["t0"]) / 0.25)) ** 3) if T.animations else 1.0
                if b["mort"] is not None:
                    a *= max(0.0, 1 - (now - b["mort"]) / 0.25)
                if a <= 0.02:
                    continue
                x1, y1, x2, y2 = (ox + b["cur"][0] * s, oy + b["cur"][1] * s, ox + b["cur"][2] * s, oy + b["cur"][3] * s)
                sc = 0.94 + 0.06 * a
                w, h = (x2 - x1) * sc, (y2 - y1) * sc
                rect = QRectF((x1 + x2) / 2 - w / 2, (y1 + y2) / 2 - h / 2, w, h)
                teinte = self._teinte_personne(b["data"], teinte_defaut) if cat == "personnes" else teinte_defaut
                grand = cat in ("personnes", "vehicules")
                self._crochets(p, rect, couleur(teinte, 255 * a), min(w, h) * (0.22 if grand else 0.28) + 4,
                               2.8 if grand else 2.3)
                self._pastille(p, rect, self._libelle(cat, b["data"]), teinte, a)
            self._boites[cat] = vivantes

    def _pastille(self, p, rect, texte, teinte, a):
        p.setFont(police(max(10, T.taille - 2), True))
        fm = QFontMetrics(p.font())
        w, h = fm.horizontalAdvance(texte) + 14, fm.height() + 4
        x = max(2.0, min(rect.left(), self.width() - w - 2))
        y = rect.top() - h - 3
        if y < 2:
            y = rect.top() + 3
        r = QRectF(x, y, w, h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(couleur(teinte, 235 * a))
        p.drawRoundedRect(r, h / 2, h / 2)
        p.setPen(QColor(8, 14, 26, int(255 * a)))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, texte)

    def _capsule(self, p, x, y, texte, teinte=None, puce=True):
        p.setFont(police(max(10, T.taille - 1), True))
        fm = QFontMetrics(p.font())
        w = fm.horizontalAdvance(texte) + (34 if puce else 22)
        r = QRectF(x, y, w, 28)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(6, 12, 24, 200))
        p.drawRoundedRect(r, 14, 14)
        if puce:
            p.setBrush(teinte or couleur("texte3"))
            p.drawEllipse(QPointF(r.left() + 14, r.center().y()), 4, 4)
        p.setPen(QColor(235, 242, 252))
        p.drawText(QRectF(r.left() + (25 if puce else 11), r.top(), w - (25 if puce else 11), r.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, texte)
        return w

    def _dessiner_hud_compact(self, p, cadre, now):
        """Vignette : nom de la caméra + état à gauche, nombre de personnes en bas. Rien d'autre."""
        teinte = couleur(Voyant.TEINTES.get(self._etat, "texte3"))
        if self._etat in ("alerte", "chargement") and T.animations:
            teinte.setAlpha(int(120 + 135 * (0.5 + 0.5 * math.sin(now * (7 if self._etat == "alerte" else 4)))))
        p.setFont(police(max(9, T.taille - 3), True))
        nom = self._badges[0] if self._badges else ""
        fm = QFontMetrics(p.font())
        texte = fm.elidedText(nom, Qt.TextElideMode.ElideRight, int(cadre.width()) - 44)
        w = fm.horizontalAdvance(texte) + 30
        r = QRectF(cadre.left() + 8, cadre.top() + 8, w, 22)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(6, 12, 24, 190))
        p.drawRoundedRect(r, 11, 11)
        p.setBrush(teinte)
        p.drawEllipse(QPointF(r.left() + 11, r.center().y()), 4, 4)
        p.setPen(QColor(235, 242, 252))
        p.drawText(QRectF(r.left() + 21, r.top(), w - 24, r.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, texte)
        if len(self._badges) > 1 and cadre.width() - w > 120:  # résolution, en haut à droite
            p.setFont(police(max(9, T.taille - 3)))
            p.setPen(QColor(235, 242, 252, 200))
            p.drawText(QRectF(cadre.right() - 110, cadre.top() + 8, 100, 22),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, self._badges[1])
        if self._etat in ("alerte", "chargement") and self._statut and cadre.width() > 230:
            p.setFont(police(max(9, T.taille - 3)))
            p.setPen(QColor(235, 242, 252, 220))
            p.drawText(QRectF(cadre.left() + 8, cadre.bottom() - 28, cadre.width() - 16, 20),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._statut)

    def _dessiner_hud(self, p, cadre, now):
        if self.compact:
            return self._dessiner_hud_compact(p, cadre, now)
        teinte = couleur(Voyant.TEINTES.get(self._etat, "texte3"))
        if self._etat in ("alerte", "chargement") and T.animations:
            teinte.setAlpha(int(120 + 135 * (0.5 + 0.5 * math.sin(now * (7 if self._etat == "alerte" else 4)))))
        if self._statut:
            x = cadre.left() + 12 + self._capsule(p, cadre.left() + 12, cadre.top() + 12, self._statut, teinte) + 8
        else:
            x = cadre.left() + 12
        for b in self._badges:
            x += self._capsule(p, x, cadre.top() + 12, b, puce=False) + 8
        if self._fps > 0 and self._etat in ("direct", "alerte"):
            p.setFont(police(max(10, T.taille - 2)))
            p.setPen(QColor(235, 242, 252, 190))
            p.drawText(QRectF(cadre.right() - 132, cadre.top() + 12, 120, 28),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{self._fps:.0f} images/s")
        x = cadre.left() + 12
        for libelle, valeur, teinte_c in self._compteurs:
            c = couleur(teinte_c, 255 if valeur else 90)
            x += self._capsule(p, x, cadre.bottom() - 40, f"{libelle}  {valeur}", c) + 8
