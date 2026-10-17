"""Éléments d'interface de Flux : boutons, bascules, voyants, notifications, navigation et vue vidéo."""

import math
import time

import cv2
import numpy as np
from PySide6.QtCore import (QEasingCurve, QParallelAnimationGroup, QPoint, QPointF, QPropertyAnimation, QRectF, QSize,
                            Qt, QTimer, QVariantAnimation, Signal, Property)
from PySide6.QtGui import QColor, QFontMetrics, QImage, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from .theme import C, T, couleur, dessiner_icone, dessiner_logo, melange, police
from .vision import NOMS_VEHICULES, boite_points, contour_zone, copie_zone, iou, normaliser_zone, point_dans_zone


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


class LabelElide(QLabel):
    """Texte qui se raccourcit avec « … » quand la place manque, au lieu de déborder ou de pousser les voisins."""

    def __init__(self, texte="", parent=None):
        super().__init__(parent)
        self._plein = ""
        self.setMinimumWidth(40)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(texte)

    def setText(self, texte):
        self._plein = str(texte or "")
        self.setToolTip(self._plein)
        self._elider()

    def text(self):
        return self._plein

    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self._plein) + 6, super().sizeHint().height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._elider()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() in (e.Type.FontChange, e.Type.StyleChange):
            self._elider()

    def _elider(self):
        QLabel.setText(self, self.fontMetrics().elidedText(self._plein, Qt.TextElideMode.ElideRight,
                                                           max(12, self.width())))


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
    zonesChangees = Signal(object)   # liste de zones {"nom", "rect": (x1, y1, x2, y2)[, "points"]} normalisés
    zoneSelectionnee = Signal(int)   # zone choisie sur l'image (-1 : aucune)
    outilChange = Signal(str)
    doubleClique = Signal()
    OUTILS = (("rect", "Rectangle"), ("forme", "Déformable"), ("lasso", "Lasso"))
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
        self._action = None   # geste en cours : tracé (rectangle, forme, lasso), point déplacé, zone déplacée
        self._sel = None      # zone sélectionnée : ses poignées sont affichées
        self._survol = None   # poignée sous la souris
        self.outil = "rect"
        self.setCursor(Qt.CursorShape.ArrowCursor)
        if zone_active:
            self.setMouseTracking(True)
            self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._etat, self._statut, self._compteurs, self._fps = "arret", "Aucun flux", [], 0.0
        self._badges = []
        self._geom = (0.0, 0.0, 1.0)
        self._t_dernier = time.time()
        self.message_vide = "Aucune image"
        self._timer = QTimer(self)
        self._timer.setInterval(66 if compact else 33)
        self._timer.timeout.connect(self.update)
        self._timer.start()

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
        self._zones = [n for n in (normaliser_zone(z, i) for i, z in enumerate(zones or [])) if n]
        self._action = self._survol = None
        if self._sel is not None and self._sel >= len(self._zones):
            self._sel = None

    def zones(self):
        return [copie_zone(z) for z in self._zones]

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

    # --- zones : outils de dessin et d'édition ------------------------------------------------
    # Rectangle : glisser pour tracer. Les coins redimensionnent ; les poignées du milieu des côtés ajoutent un
    # point, et le rectangle devient une forme libre.
    # Déformable : glisser pour tracer un carré à 4 points, puis déplacer chaque point librement ; tirer une
    # poignée de milieu (ou double-cliquer sur un côté) ajoute un point.
    # Lasso : dessiner le contour à main levée ; il est simplifié en forme libre au relâchement.
    # Partout : clic sur une zone pour la sélectionner, Maj + glisser pour la déplacer, clic droit pour le menu,
    # Suppr pour retirer le point survolé (ou la zone sélectionnée), Échap pour annuler.
    def regler_outil(self, outil):
        if outil in dict(self.OUTILS) and outil != self.outil:
            self.outil = outil
            self._action = None
            self.outilChange.emit(outil)

    def selectionner_zone(self, i):
        """Sélection venant de l'extérieur (liste des zones) : sans renvoyer le signal."""
        self._selectionner(i if i is not None and i >= 0 else None, emettre=False)

    def _selectionner(self, i, emettre=True):
        i = i if i is not None and 0 <= i < len(self._zones) else None
        if i != self._sel:
            self._sel = i
            if emettre:
                self.zoneSelectionnee.emit(-1 if i is None else i)

    def _vers_norm(self, pos):
        ox, oy, s = self._geom
        iw, ih = self._taille
        return (min(max((pos.x() - ox) / s / iw, 0.0), 1.0), min(max((pos.y() - oy) / s / ih, 0.0), 1.0))

    def _vers_ecran(self, x, y):
        ox, oy, s = self._geom
        iw, ih = self._taille
        return QPointF(ox + x * iw * s, oy + y * ih * s)

    def _zone_sous(self, pos):
        x, y = self._vers_norm(pos)
        if self._sel is not None and point_dans_zone(x, y, self._zones[self._sel]):
            return self._sel  # la zone sélectionnée passe devant les autres
        for i in range(len(self._zones) - 1, -1, -1):
            if point_dans_zone(x, y, self._zones[i]):
                return i
        return None

    def _fixer_points(self, i, pts):
        z = self._zones[i]
        z["points"] = [tuple(p) for p in pts]
        z["rect"] = boite_points(z["points"])

    def _poignees(self, i):
        """Poignées de la zone i : [(type, k, point écran)]. type : « sommet » (forme libre), « coin » (rectangle)
        ou « milieu » (ajoute un point au milieu du côté k ; masquée sur les côtés trop courts)."""
        z = self._zones[i]
        pts = contour_zone(z)
        typ = "sommet" if z.get("points") else "coin"
        ecran = [self._vers_ecran(*p) for p in pts]
        sortie = [(typ, k, q) for k, q in enumerate(ecran)]
        for k, q in enumerate(ecran):
            r = ecran[(k + 1) % len(ecran)]
            if math.hypot(r.x() - q.x(), r.y() - q.y()) >= 30:
                sortie.append(("milieu", k, QPointF((q.x() + r.x()) / 2, (q.y() + r.y()) / 2)))
        return sortie

    def _poignee_sous(self, pos):
        if not self.zone_active or self._sel is None or self._sel >= len(self._zones):
            return None
        poignees = self._poignees(self._sel)
        for cherche, rayon in ((("sommet", "coin"), 9.0), (("milieu",), 7.0)):
            proches = [(math.hypot(q.x() - pos.x(), q.y() - pos.y()), typ, k) for typ, k, q in poignees
                       if typ in cherche]
            proches = [c for c in proches if c[0] <= rayon]
            if proches:
                _, typ, k = min(proches)
                return typ, k
        return None

    def _arete_sous(self, pos, rayon=7.0):
        """Côté de la zone sélectionnée sous la souris (index du premier point), ou None."""
        if self._sel is None or self._sel >= len(self._zones):
            return None
        ecran = [self._vers_ecran(*p) for p in contour_zone(self._zones[self._sel])]
        meilleur = None
        for k, a in enumerate(ecran):
            b = ecran[(k + 1) % len(ecran)]
            dx, dy = b.x() - a.x(), b.y() - a.y()
            t = max(0.0, min(1.0, ((pos.x() - a.x()) * dx + (pos.y() - a.y()) * dy) / ((dx * dx + dy * dy) or 1e-9)))
            d = math.hypot(a.x() + t * dx - pos.x(), a.y() + t * dy - pos.y())
            if d <= rayon and (meilleur is None or d < meilleur[0]):
                meilleur = (d, k)
        return meilleur[1] if meilleur else None

    def _copie(self, z):
        c = dict(z)
        if z.get("points"):
            c["points"] = list(z["points"])
        return c

    def mousePressEvent(self, e):
        if self._image is None or not self.zone_active:
            return
        pos = e.position()
        if e.button() == Qt.MouseButton.RightButton:
            self._annuler_geste()
            self._menu_zones(e)
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        poignee = self._poignee_sous(pos)
        if poignee:
            typ, k = poignee
            i = self._sel
            orig = self._copie(self._zones[i])
            if typ == "milieu":  # ajoute un point au milieu du côté, puis le fait suivre la souris
                pts = contour_zone(self._zones[i])
                a, b = pts[k], pts[(k + 1) % len(pts)]
                pts.insert(k + 1, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
                self._fixer_points(i, pts)
                typ, k = "sommet", k + 1
            action = {"type": typ, "i": i, "k": k, "orig": orig}
            if typ == "coin":
                action["fixe"] = contour_zone(orig)[(k + 2) % 4]  # le coin opposé ne bouge pas
            self._action = action
            return
        n = self._vers_norm(pos)
        i = self._zone_sous(pos)
        if e.modifiers() & Qt.KeyboardModifier.ShiftModifier and i is not None:
            self._selectionner(i)
            self._action = {"type": "deplacer", "i": i, "depart": n, "orig": self._copie(self._zones[i])}
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        self._action = {"type": self.outil, "depart": n, "pos0": QPointF(pos), "sous": i, "pts": [n], "boite": None,
                        "loin": 0.0}

    def mouseMoveEvent(self, e):
        pos = e.position()
        a = self._action
        if a is None:
            self._maj_curseur(pos, e.modifiers())
            return
        n = self._vers_norm(pos)
        t = a["type"]
        if "pos0" in a:  # plus grande distance au point de départ (un lasso fermé revient à son départ)
            a["loin"] = max(a["loin"], math.hypot(pos.x() - a["pos0"].x(), pos.y() - a["pos0"].y()))
        if t == "sommet":
            pts = list(self._zones[a["i"]]["points"])
            pts[a["k"]] = n
            self._fixer_points(a["i"], pts)
        elif t == "coin":
            fx, fy = a["fixe"]
            self._zones[a["i"]]["rect"] = (min(fx, n[0]), min(fy, n[1]), max(fx, n[0]), max(fy, n[1]))
        elif t == "deplacer":
            o = a["orig"]
            x1, y1, x2, y2 = o["rect"]
            dx = min(max(n[0] - a["depart"][0], -x1), 1 - x2)  # la zone reste dans l'image
            dy = min(max(n[1] - a["depart"][1], -y1), 1 - y2)
            z = self._zones[a["i"]]
            z["rect"] = (x1 + dx, y1 + dy, x2 + dx, y2 + dy)
            if o.get("points"):
                z["points"] = [(x + dx, y + dy) for x, y in o["points"]]
        elif t == "lasso":
            d = self._vers_ecran(*a["pts"][-1])
            if math.hypot(pos.x() - d.x(), pos.y() - d.y()) >= 3:
                a["pts"].append(n)
        else:  # rectangle ou carré déformable
            x1, y1 = a["depart"]
            a["boite"] = (min(x1, n[0]), min(y1, n[1]), max(x1, n[0]), max(y1, n[1]))

    def mouseReleaseEvent(self, e):
        a, self._action = self._action, None
        if a is None:
            return
        t = a["type"]
        if t in ("sommet", "coin", "deplacer"):
            x1, y1, x2, y2 = self._zones[a["i"]]["rect"]
            if x2 - x1 < 0.01 or y2 - y1 < 0.01:  # forme écrasée : retour à l'état d'avant
                self._zones[a["i"]] = a["orig"]
            if self._zones[a["i"]] != a["orig"]:
                self._emettre_zones()
            self._maj_curseur(e.position(), e.modifiers())
            return
        if max(a["loin"], math.hypot(e.position().x() - a["pos0"].x(), e.position().y() - a["pos0"].y())) < 5:
            self._selectionner(a["sous"])  # simple clic : choisit la zone (ou aucune)
            return
        if t == "lasso":
            zone = self._zone_lasso(a["pts"])
        else:
            b, zone = a["boite"], None
            if b and b[2] - b[0] >= 0.02 and b[3] - b[1] >= 0.02:
                zone = {"rect": b} if t == "rect" else {"rect": b, "points": contour_zone({"rect": b})}
        if zone is None:
            return
        zone["nom"] = self._nom_libre()
        self._zones.append(zone)
        self._selectionner(len(self._zones) - 1)
        self._emettre_zones()

    def _zone_lasso(self, pts):
        """Contour à main levée -> forme libre simplifiée (au plus 80 points), ou None si trop petite."""
        if len(pts) < 3:
            return None
        _, _, s = self._geom
        iw, ih = self._taille
        lx, ly = iw * s, ih * s
        ecran = np.array([[x * lx, y * ly] for x, y in pts], np.float32).reshape(-1, 1, 2)
        eps = 1.5
        approx = cv2.approxPolyDP(ecran, eps, True)
        while len(approx) > 80:
            eps *= 1.5
            approx = cv2.approxPolyDP(ecran, eps, True)
        forme = [(min(max(float(q[0][0]) / lx, 0.0), 1.0), min(max(float(q[0][1]) / ly, 0.0), 1.0)) for q in approx]
        if len(forme) < 3:
            return None
        b = boite_points(forme)
        if b[2] - b[0] < 0.02 or b[3] - b[1] < 0.02 or abs(cv2.contourArea(np.array(forme, np.float32))) < 0.0004:
            return None
        return {"rect": b, "points": forme}

    def mouseDoubleClickEvent(self, e):
        if self.zone_active and self._image is not None and e.button() == Qt.MouseButton.LeftButton:
            k = self._arete_sous(e.position())
            if k is not None:  # double-clic sur un côté de la zone sélectionnée : nouveau point
                self._action = None
                pts = contour_zone(self._zones[self._sel])
                pts.insert(k + 1, self._vers_norm(e.position()))
                self._fixer_points(self._sel, pts)
                self._emettre_zones()
                return
        self.doubleClique.emit()

    def keyPressEvent(self, e):
        if not self.zone_active:
            return super().keyPressEvent(e)
        if e.key() == Qt.Key.Key_Escape:
            if self._action is not None:
                self._annuler_geste()
            else:
                self._selectionner(None)
        elif e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self._action is None:
            poignee = self._survol
            if poignee and poignee[0] == "sommet" and self._sel is not None:
                self._supprimer_point(self._sel, poignee[1])
            elif self._sel is not None:
                self._supprimer_zone(self._sel)
        else:
            super().keyPressEvent(e)

    def leaveEvent(self, e):
        self._survol = None
        super().leaveEvent(e)

    def _annuler_geste(self):
        a, self._action = self._action, None
        if a and "orig" in a and a.get("i") is not None and a["i"] < len(self._zones):
            self._zones[a["i"]] = a["orig"]

    def _maj_curseur(self, pos, mods):
        if not self.zone_active or self._image is None:
            return
        poignee = self._poignee_sous(pos)
        if poignee:
            forme = Qt.CursorShape.PointingHandCursor if poignee[0] == "milieu" else Qt.CursorShape.SizeAllCursor
        elif mods & Qt.KeyboardModifier.ShiftModifier and self._zone_sous(pos) is not None:
            forme = Qt.CursorShape.OpenHandCursor
        else:
            forme = Qt.CursorShape.CrossCursor
        self._survol = poignee
        if self.cursor().shape() != forme:
            self.setCursor(forme)

    def _supprimer_point(self, i, k):
        pts = contour_zone(self._zones[i])
        if len(pts) > 3:
            del pts[k]
            self._fixer_points(i, pts)
            self._survol = None
            self._emettre_zones()

    def _supprimer_zone(self, i):
        del self._zones[i]
        self._sel = None
        self.zoneSelectionnee.emit(-1)
        self._emettre_zones()

    def _en_forme(self, i):
        self._fixer_points(i, contour_zone(self._zones[i]))
        self._selectionner(i)
        self._emettre_zones()

    def _en_rectangle(self, i):
        self._zones[i].pop("points", None)
        self._emettre_zones()

    def _menu_zones(self, e):
        from PySide6.QtWidgets import QInputDialog, QMenu
        pos = e.position()
        poignee = self._poignee_sous(pos)
        i = self._sel if poignee else self._zone_sous(pos)
        if i is not None:
            self._selectionner(i)
        m = QMenu(self)
        if poignee and poignee[0] == "sommet" and len(self._zones[i]["points"]) > 3:
            m.addAction("Supprimer ce point", lambda k=poignee[1]: self._supprimer_point(i, k))
            m.addSeparator()
        if i is not None:
            z = self._zones[i]
            nom = z["nom"]

            def renommer():
                nouveau, ok = QInputDialog.getText(self, "Renommer la zone", "Nom de la zone :", text=nom)
                if ok and nouveau.strip():
                    self._zones[i]["nom"] = nouveau.strip()
                    self._emettre_zones()
            m.addAction(f"Renommer « {nom} »…", renommer)
            if z.get("points"):
                m.addAction("Revenir à un rectangle", lambda: self._en_rectangle(i))
            else:
                m.addAction("Rendre déformable (points libres)", lambda: self._en_forme(i))
            m.addAction(f"Supprimer « {nom} »", lambda: self._supprimer_zone(i))
        if self._zones:
            m.addSeparator()

            def tout_effacer():
                self._zones.clear()
                self._selectionner(None)
                self._emettre_zones()
            m.addAction("Effacer toutes les zones", tout_effacer)
        m.addSeparator()
        for cle, libelle in self.OUTILS:
            act = m.addAction(f"Outil : {libelle}")
            act.setCheckable(True)
            act.setChecked(cle == self.outil)
            act.triggered.connect(lambda _=False, c=cle: self.regler_outil(c))
        m.exec(e.globalPosition().toPoint())

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

    def _chemin_zone(self, z):
        ch = QPainterPath()
        if z.get("points"):
            ch.addPolygon(QPolygonF([self._vers_ecran(*q) for q in z["points"]]))
            ch.closeSubpath()
        else:
            x1, y1, x2, y2 = z["rect"]
            ch.addRoundedRect(QRectF(self._vers_ecran(x1, y1), self._vers_ecran(x2, y2)), 4, 4)
        return ch

    def _apercu(self):
        """Tracé en cours (rectangle, carré déformable ou lasso) : (chemin, points à marquer) ou None."""
        a = self._action
        if not a or a["type"] not in ("rect", "forme", "lasso"):
            return None
        if a["type"] == "lasso":
            if len(a["pts"]) < 2:
                return None
            ch = QPainterPath()
            ch.addPolygon(QPolygonF([self._vers_ecran(*q) for q in a["pts"]]))
            ch.closeSubpath()
            return ch, []
        if not a["boite"]:
            return None
        z = {"rect": a["boite"]}
        return self._chemin_zone(z), ([self._vers_ecran(*q) for q in contour_zone(z)] if a["type"] == "forme" else [])

    def _dessiner_zone(self, p, now, rect_img):
        apercu = self._apercu()
        if not self._zones and apercu is None:
            return
        chemins = [self._chemin_zone(z) for z in self._zones]
        trous = QPainterPath()
        for ch in chemins + ([apercu[0]] if apercu else []):
            trous = trous.united(ch)
        sombre = QPainterPath()
        sombre.addRect(rect_img)
        p.fillPath(sombre.subtracted(trous), QColor(0, 0, 0, 120))
        pen = QPen(couleur("o_plaque"), 1.8, Qt.PenStyle.CustomDashLine)
        pen.setDashPattern([5, 4])
        pen.setDashOffset((now * 14) % 9 if T.animations else 0)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        sel = self._sel if self.zone_active else None
        for i, ch in enumerate(chemins):
            if i == sel:
                p.setPen(QPen(couleur("o_plaque"), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                              Qt.PenJoinStyle.RoundJoin))
                p.setBrush(couleur("o_plaque", 30))
            else:
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(ch)
        if apercu:
            p.setPen(pen)
            p.setBrush(couleur("o_plaque", 22))
            p.drawPath(apercu[0])
            for q in apercu[1]:
                self._poignee(p, "sommet", q, False)
        p.setFont(police(max(9, T.taille - 3), True))
        fm = QFontMetrics(p.font())
        for z, ch in zip(self._zones, chemins):
            boite = ch.boundingRect()
            if not z["nom"] or boite.width() <= 30:
                continue
            if z.get("points"):  # étiquette sous le point le plus haut de la forme
                haut = min((self._vers_ecran(*q) for q in z["points"]), key=lambda q: (q.y(), q.x()))
                x, y = haut.x() - 10, haut.y() + 6
            else:
                x, y = boite.left() + 4, boite.top() + 4
            texte = fm.elidedText(z["nom"], Qt.TextElideMode.ElideRight, int(boite.width()) - 8)
            r = QRectF(x, y, fm.horizontalAdvance(texte) + 12, fm.height() + 4)
            if z.get("points"):
                r.moveCenter(QPointF(haut.x(), haut.y() + 12 + r.height() / 2))
            r.moveLeft(min(max(r.left(), rect_img.left() + 2), rect_img.right() - r.width() - 2))
            r.moveTop(min(max(r.top(), rect_img.top() + 2), rect_img.bottom() - r.height() - 2))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(couleur("o_plaque", 225))
            p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
            p.setPen(QColor(8, 14, 26))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, texte)
        if sel is not None and sel < len(self._zones):
            for typ, k, q in self._poignees(sel):
                self._poignee(p, typ, q, self._survol == (typ, k))

    @staticmethod
    def _poignee(p, typ, q, survol):
        if typ == "milieu":  # « + » discret : tirer pour ajouter un point
            r = 6.0 if survol else 4.6
            p.setPen(QPen(QColor(255, 255, 255, 240 if survol else 200), 1.3))
            p.setBrush(couleur("o_plaque", 235 if survol else 160))
            p.drawEllipse(q, r, r)
            p.setPen(QPen(QColor(8, 14, 26), 1.3))
            p.drawLine(QPointF(q.x() - r + 2, q.y()), QPointF(q.x() + r - 2, q.y()))
            p.drawLine(QPointF(q.x(), q.y() - r + 2), QPointF(q.x(), q.y() + r - 2))
            return
        r = 6.0 if survol else 4.6
        p.setPen(QPen(couleur("o_plaque"), 2))
        p.setBrush(QColor(255, 255, 255))
        if typ == "coin":  # rectangle : coins carrés
            p.drawRoundedRect(QRectF(q.x() - r, q.y() - r, 2 * r, 2 * r), 1.5, 1.5)
        else:  # forme libre : points ronds
            p.drawEllipse(q, r, r)

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


# ---------------------------------------------------------------------------
# Choix de l'outil de dessin des zones (relié à une VueVideo)
# ---------------------------------------------------------------------------
AIDES_OUTILS = {
    "rect": "Rectangle : glissez sur l'image pour tracer une zone.\nTirez un coin pour la redimensionner, ou le "
            "« + » au milieu d'un côté pour ajouter un point et la déformer.",
    "forme": "Carré déformable : glissez pour tracer un carré, puis déplacez chaque point librement.\nTirez un « + » "
             "ou double-cliquez sur un côté pour ajouter un point. Suppr (ou clic droit) retire le point survolé.",
    "lasso": "Lasso : dessinez le contour de la zone à main levée, maintenez le clic jusqu'à la fin.\nLa forme reste "
             "modifiable ensuite, point par point.",
}


class BoutonOutil(QAbstractButton):
    """Bouton d'outil : icône au-dessus d'un libellé court, coché = outil actif."""

    def __init__(self, texte, icone, parent=None):
        super().__init__(parent)
        self.setText(texte)
        self._icone = icone
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._h, self._c = 0.0, 0.0
        self._ah = _anim(self, lambda v: self._set("_h", v))
        self._ac = _anim(self, lambda v: self._set("_c", v))
        self.toggled.connect(lambda e: _aller(self._ac, self._c, 1.0 if e else 0.0, 180))

    def _set(self, nom, v):
        setattr(self, nom, float(v))
        self.update()

    def enterEvent(self, e):
        _aller(self._ah, self._h, 1.0, 140)
        super().enterEvent(e)

    def leaveEvent(self, e):
        _aller(self._ah, self._h, 0.0, 140)
        super().leaveEvent(e)

    def sizeHint(self):
        fm = QFontMetrics(police(max(9, T.taille - 2), True))
        return QSize(max(64, fm.horizontalAdvance(self.text()) + 18), int(56 * max(0.85, T.densite)))

    def minimumSizeHint(self):
        return QSize(56, self.sizeHint().height())

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        teinte = C["o_plaque"]
        fond = melange(couleur("surface", 255), melange("surface", teinte, 0.2), self._c)
        fond = melange(fond, couleur("surface2"), self._h * (1 - self._c) * 0.9)
        p.setPen(QPen(melange("trait", teinte, self._c), 1.2 if self._c > 0.5 else 1))
        p.setBrush(fond)
        p.drawRoundedRect(r, T.rayon, T.rayon)
        if self.hasFocus():
            p.setPen(QPen(couleur("accent", 150), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(2, 2, -2, -2), max(2, T.rayon - 2), max(2, T.rayon - 2))
        texte = melange("texte2", "texte", self._c)
        dessiner_icone(p, self._icone, QRectF(r.center().x() - 10, r.top() + 8, 20, 20),
                       melange("texte2", teinte, self._c))
        p.setPen(texte)
        p.setFont(police(max(9, T.taille - 2), True))
        p.drawText(QRectF(r.left() + 4, r.top() + 30, r.width() - 8, r.height() - 34),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self.text())


class OutilsZone(QWidget):
    """Rectangle · Déformable · Lasso : choisit l'outil de dessin des zones de la vue vidéo."""

    def __init__(self, video, parent=None):
        super().__init__(parent)
        self.video = video
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self._groupe = QButtonGroup(self)
        self._groupe.setExclusive(True)
        self._boutons = {}
        for cle, libelle in VueVideo.OUTILS:
            b = BoutonOutil(libelle, f"outil_{cle}")
            b.setToolTip(AIDES_OUTILS[cle])
            b.clicked.connect(lambda _=False, c=cle: self.video.regler_outil(c))
            self._groupe.addButton(b)
            lay.addWidget(b, 1)
            self._boutons[cle] = b
        video.outilChange.connect(self._maj)
        self._maj(video.outil)

    def _maj(self, cle):
        for c, b in self._boutons.items():
            if b.isChecked() != (c == cle):
                b.setChecked(c == cle)
