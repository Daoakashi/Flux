"""Thèmes de Flux (clair et sombre, en bleu), feuille de style, polices, icônes et logo.

`C` est un dictionnaire de couleurs modifié en place lors d'un changement de thème : tous les
éléments dessinés à la main relisent `C` à chaque dessin, il suffit donc de les redessiner.
"""

import math
import os
import tempfile

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QApplication

PALETTES = {
    "sombre": {
        "fond": "#0A1220", "panneau": "#0E1829", "surface": "#132137", "surface2": "#1A2B47", "trait": "#233957",
        "texte": "#E7EEF8", "texte2": "#93A6C2", "texte3": "#5F7596", "video": "#050B15",
        "succes": "#2BD07A", "danger": "#F2554A", "attention": "#F5A524", "liste_noire": "#FF2E7A",
        "o_personne": "#22D3EE", "o_visage": "#B79CFF", "o_vehicule": "#F472B6", "o_plaque": "#FBBF24",
        "ombre": "#000000",
    },
    "clair": {
        "fond": "#EEF3FA", "panneau": "#F7FAFE", "surface": "#FFFFFF", "surface2": "#E7EEF8", "trait": "#D2DDEB",
        "texte": "#0E1A2B", "texte2": "#51627B", "texte3": "#8695AB", "video": "#0B1424",
        "succes": "#12A150", "danger": "#D92D20", "attention": "#C77700", "liste_noire": "#C2185B",
        "o_personne": "#22D3EE", "o_visage": "#B79CFF", "o_vehicule": "#F472B6", "o_plaque": "#FBBF24",
        "ombre": "#1B2A44",
    },
}

C = dict(PALETTES["sombre"])


class T:
    """Paramètres de forme et de mouvement courants (lus par les éléments dessinés à la main)."""
    theme = "sombre"
    rayon = 10
    taille = 13
    densite = 1.0
    animations = True
    vitesse = 1.0
    famille = ["Segoe UI Variable Text", "Segoe UI", "Inter", "DejaVu Sans"]
    fleche = ""

    @staticmethod
    def ms(n):
        return int(n * T.vitesse) if T.animations else 0


def couleur(nom, alpha=255):
    c = QColor(C.get(nom, nom))
    c.setAlpha(max(0, min(255, int(alpha))))
    return c


def melange(c1, c2, t):
    a, b = QColor(C.get(c1, c1) if isinstance(c1, str) else c1), QColor(C.get(c2, c2) if isinstance(c2, str) else c2)
    t = max(0.0, min(1.0, t))
    return QColor(int(a.red() + (b.red() - a.red()) * t), int(a.green() + (b.green() - a.green()) * t),
                  int(a.blue() + (b.blue() - a.blue()) * t), int(a.alpha() + (b.alpha() - a.alpha()) * t))


def police(taille=None, gras=False, poids=None):
    f = QFont()
    f.setFamilies(T.famille)
    f.setPixelSize(int(taille or T.taille))
    f.setWeight(poids or (QFont.Weight.DemiBold if gras else QFont.Weight.Normal))
    return f


def appliquer(cfg, app=None):
    """Recalcule palette, formes et feuille de style à partir des réglages, puis redessine tout."""
    app = app or QApplication.instance()
    theme = cfg.get("apparence.theme")
    T.theme = theme if theme in PALETTES else "sombre"
    C.clear()
    C.update(PALETTES[T.theme])
    accent = QColor(cfg.get("apparence.accent"))
    C["accent"] = accent.name()
    C["accent_vif"] = accent.lighter(118).name() if T.theme == "sombre" else accent.darker(112).name()
    C["accent_doux"] = melange(C["surface"], accent, 0.16 if T.theme == "sombre" else 0.10).name()
    C["accent_texte"] = "#FFFFFF" if accent.lightnessF() < 0.62 else "#0B1220"
    C["selection"] = melange(C["surface"], accent, 0.26).name()
    T.rayon = int(cfg.get("apparence.arrondi"))
    T.taille = int(cfg.get("apparence.taille_police"))
    T.densite = {"compacte": 0.75, "normale": 1.0, "aeree": 1.3}.get(cfg.get("apparence.densite"), 1.0)
    T.animations = bool(cfg.get("apparence.animations"))
    T.vitesse = float(cfg.get("apparence.vitesse_animations"))
    famille = cfg.get("apparence.police")
    T.famille = (["Segoe UI Variable Text", "Segoe UI", "Inter", "DejaVu Sans"] if famille == "systeme"
                 else [famille, "Segoe UI", "DejaVu Sans"])
    _fleche()
    if app is not None:
        app.setPalette(palette_qt())
        app.setFont(police())
        app.setStyleSheet(feuille_de_style())
        for w in app.allWidgets():
            w.update()


def feuille_de_style():
    r, d, t = T.rayon, T.densite, T.taille
    pv, ph = max(3, int(6 * d)), max(6, int(10 * d))
    fam = ", ".join(f'"{f}"' for f in T.famille)
    return f"""
    * {{ font-family: {fam}; font-size: {t}px; }}
    QWidget {{ color: {C['texte']}; }}
    QMainWindow, QDialog, #fond {{ background: {C['fond']}; }}
    QStackedWidget, #page {{ background: transparent; }}
    #panneau {{ background: {C['panneau']}; border-right: 1px solid {C['trait']}; }}
    #carte {{ background: {C['surface']}; border: 1px solid {C['trait']}; border-radius: {r + 2}px; }}
    QLabel {{ background: transparent; }}
    QLabel#titre {{ font-size: {t + 9}px; font-weight: 600; }}
    QLabel#titre_page {{ font-size: {t + 13}px; font-weight: 650; }}
    QLabel#soustitre {{ color: {C['texte2']}; }}
    QLabel#aide {{ color: {C['texte2']}; font-size: {max(10, t - 1)}px; }}
    QLabel#section {{ color: {C['texte3']}; font-size: {max(10, t - 2)}px; font-weight: 700; letter-spacing: 0.6px; }}
    QLabel#valeur {{ color: {C['accent_vif']}; font-weight: 600; }}
    QLabel#grand {{ font-size: {t + 15}px; font-weight: 650; }}
    QLabel#badge {{ background: {C['accent_doux']}; color: {C['accent_vif']}; border-radius: 8px; padding: 2px 8px;
        font-size: {max(10, t - 2)}px; font-weight: 600; }}
    QFrame#sep {{ background: {C['trait']}; max-height: 1px; min-height: 1px; border: none; }}
    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{
        background: {C['surface']}; border: 1px solid {C['trait']}; border-radius: {max(4, r - 1)}px;
        padding: {pv}px {ph}px; selection-background-color: {C['accent']}; selection-color: {C['accent_texte']}; }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ min-height: {int(22 * d)}px; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus {{
        border-color: {C['accent']}; }}
    QLineEdit:disabled, QComboBox:disabled {{ color: {C['texte3']}; }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
    QComboBox::down-arrow {{ image: url("{T.fleche}"); width: 10px; height: 10px; margin-right: 8px; }}
    QComboBox QAbstractItemView {{ background: {C['surface']}; border: 1px solid {C['trait']}; padding: 4px;
        selection-background-color: {C['selection']}; selection-color: {C['texte']}; outline: 0; }}
    QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle {{ background: {C['trait']}; border-radius: 4px; min-height: 28px; min-width: 28px; }}
    QScrollBar::handle:hover {{ background: {C['texte3']}; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; width: 0;
        background: none; }}
    QSlider::groove:horizontal {{ height: 4px; background: {C['trait']}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {C['accent']}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ background: {C['surface']}; border: 2px solid {C['accent']}; width: 12px; height: 12px;
        margin: -6px 0; border-radius: 8px; }}
    QTabBar {{ background: transparent; }}
    QTabBar::tab {{ background: transparent; color: {C['texte2']}; padding: {int(8 * d)}px 8px {int(8 * d)}px 6px;
        margin-right: 4px; border-radius: {r}px; min-width: 70px; }}
    QTabBar::tab:selected {{ background: {C['surface']}; color: {C['texte']}; }}
    QTabBar::tab:hover:!selected {{ background: {C['surface2']}; }}
    QTabWidget::pane {{ border: none; }}
    QListWidget, QTableWidget, QTreeWidget {{ background: {C['surface']}; border: 1px solid {C['trait']};
        border-radius: {r}px; outline: 0; alternate-background-color: {C['panneau']}; gridline-color: {C['trait']}; }}
    QListWidget::item {{ border-radius: {max(4, r - 2)}px; padding: {pv}px; margin: 1px 4px; }}
    QListWidget::item:selected, QTableWidget::item:selected {{ background: {C['selection']}; color: {C['texte']}; }}
    QListWidget::item:hover:!selected {{ background: {C['surface2']}; }}
    QHeaderView::section {{ background: {C['panneau']}; color: {C['texte2']}; border: none;
        border-bottom: 1px solid {C['trait']}; padding: {pv}px {ph}px; font-weight: 600; }}
    QTableCornerButton::section {{ background: {C['panneau']}; border: none; }}
    QMenu {{ background: {C['surface']}; border: 1px solid {C['trait']}; border-radius: {r}px; padding: 6px; }}
    QMenu::item {{ padding: 7px 22px 7px 14px; border-radius: {max(4, r - 4)}px; }}
    QMenu::item:selected {{ background: {C['selection']}; }}
    QMenu::separator {{ height: 1px; background: {C['trait']}; margin: 5px 8px; }}
    QToolTip {{ background: {C['surface2']}; color: {C['texte']}; border: 1px solid {C['trait']}; padding: 6px;
        border-radius: 6px; }}
    QStatusBar {{ background: {C['panneau']}; border-top: 1px solid {C['trait']}; color: {C['texte2']}; }}
    QStatusBar QLabel {{ color: {C['texte2']}; padding: 0 10px; font-size: {max(10, t - 1)}px; }}
    QProgressBar {{ background: {C['surface2']}; border: none; border-radius: 3px; max-height: 6px; text-align: center;
        color: transparent; }}
    QProgressBar::chunk {{ background: {C['accent']}; border-radius: 3px; }}
    QMessageBox, QInputDialog {{ background: {C['fond']}; }}
    QCheckBox {{ spacing: 8px; }}
    """


def _fleche():
    """Chevron des listes déroulantes, aux couleurs du thème (fichier temporaire lu par la feuille de style)."""
    pix = QPixmap(40, 40)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor(C["texte2"]), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    chemin = QPainterPath()
    chemin.moveTo(8, 15)
    chemin.lineTo(20, 27)
    chemin.lineTo(32, 15)
    p.drawPath(chemin)
    p.end()
    T.fleche = os.path.join(tempfile.gettempdir(), f"flux_fleche_{T.theme}.png").replace("\\", "/")
    pix.save(T.fleche)


def palette_qt():
    """Palette Qt assortie : utilisée par les fenêtres système (couleurs, confirmations, fichiers)."""
    pal = QPalette()
    for role, cle in ((QPalette.ColorRole.Window, "fond"), (QPalette.ColorRole.WindowText, "texte"),
                      (QPalette.ColorRole.Base, "surface"), (QPalette.ColorRole.AlternateBase, "panneau"),
                      (QPalette.ColorRole.Text, "texte"), (QPalette.ColorRole.Button, "surface"),
                      (QPalette.ColorRole.ButtonText, "texte"), (QPalette.ColorRole.ToolTipBase, "surface2"),
                      (QPalette.ColorRole.ToolTipText, "texte"), (QPalette.ColorRole.PlaceholderText, "texte3"),
                      (QPalette.ColorRole.Highlight, "accent"), (QPalette.ColorRole.HighlightedText, "accent_texte"),
                      (QPalette.ColorRole.Link, "accent_vif"), (QPalette.ColorRole.Mid, "trait")):
        pal.setColor(role, QColor(C[cle]))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(C["texte3"]))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(C["texte3"]))
    return pal


# ---------------------------------------------------------------------------
# Logo et icônes (vectoriels, aux couleurs du thème)
# ---------------------------------------------------------------------------
LOGO_PERSONNALISE = {"chemin": "", "pix": None}


def regler_logo(chemin):
    """Logo personnalisé (mode développeur) ; chemin vide = logo Flux dessiné."""
    chemin = (chemin or "").strip()
    if chemin == LOGO_PERSONNALISE["chemin"]:
        return
    pix = QPixmap(chemin) if chemin and os.path.isfile(chemin) else None
    LOGO_PERSONNALISE.update(chemin=chemin, pix=pix if pix is not None and not pix.isNull() else None)


def dessiner_logo(p, rect, decalage=0.0, couleur_fond=None):
    """Le logo Flux : trois courants qui ondulent dans un carré arrondi bleu."""
    if LOGO_PERSONNALISE["pix"] is not None:
        p.save()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(rect)
        pix = LOGO_PERSONNALISE["pix"].scaled(int(r.width() * 2), int(r.height() * 2),
                                               Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation)
        cible = QRectF(0, 0, pix.width() / 2, pix.height() / 2)
        cible.moveCenter(r.center())
        p.drawPixmap(cible, pix, QRectF(pix.rect()))
        p.restore()
        return
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r = QRectF(rect)
    g = QLinearGradient(r.topLeft(), r.bottomRight())
    accent = QColor(C.get("accent", "#2F7BFF"))
    g.setColorAt(0, accent.lighter(135))
    g.setColorAt(1, accent.darker(125))
    chemin = QPainterPath()
    chemin.addRoundedRect(r, r.width() * 0.26, r.width() * 0.26)
    p.fillPath(chemin, couleur_fond or g)
    p.setClipPath(chemin)
    largeur = r.width()
    for i, (y, ep, a) in enumerate(((0.33, 0.085, 255), (0.52, 0.085, 210), (0.71, 0.085, 160))):
        onde = QPainterPath()
        pas = largeur / 40
        for k in range(43):
            x = r.left() - pas + k * pas
            yy = r.top() + r.height() * y + math.sin((k * pas / largeur) * 2 * math.pi * 1.1 + decalage + i * 0.9) * (
                r.height() * 0.06)
            onde.moveTo(x, yy) if k == 0 else onde.lineTo(x, yy)
        p.setPen(QPen(QColor(255, 255, 255, a), r.height() * ep, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPath(onde)
    p.restore()


def icone_application(taille=256):
    pix = QPixmap(taille, taille)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    dessiner_logo(p, QRectF(taille * 0.06, taille * 0.06, taille * 0.88, taille * 0.88))
    p.end()
    return QIcon(pix)


def dessiner_icone(p, nom, rect, couleur_, epaisseur=1.7):
    """Icônes au trait, dessinées dans un carré `rect`."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    s = min(w, h) / 24.0
    p.translate(x + (w - 24 * s) / 2, y + (h - 24 * s) / 2)
    p.scale(s, s)
    pen = QPen(couleur_, epaisseur, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    pp = QPainterPath()
    if nom == "cameras":
        pp.addRoundedRect(QRectF(3, 6.5, 13, 11), 2.5, 2.5)
        pp.moveTo(16, 10.5)
        pp.lineTo(21, 7.5)
        pp.lineTo(21, 16.5)
        pp.lineTo(16, 13.5)
    elif nom == "lecteur":
        pp.addRoundedRect(QRectF(3, 4.5, 18, 15), 3, 3)
        pp.moveTo(10, 8.8)
        pp.lineTo(15.5, 12)
        pp.lineTo(10, 15.2)
        pp.closeSubpath()
    elif nom == "personnes":
        pp.addEllipse(QRectF(8.5, 3.5, 7, 7))
        pp.moveTo(4.5, 20.5)
        pp.cubicTo(4.5, 15.5, 8, 13.2, 12, 13.2)
        pp.cubicTo(16, 13.2, 19.5, 15.5, 19.5, 20.5)
    elif nom == "journal":
        pp.addRoundedRect(QRectF(4.5, 3.5, 15, 17), 2.5, 2.5)
        for yy in (8.5, 12, 15.5):
            pp.moveTo(8, yy)
            pp.lineTo(16, yy)
    elif nom == "reglages":
        for yy, xx in ((6.5, 9), (12, 15), (17.5, 7)):
            pp.moveTo(4, yy)
            pp.lineTo(20, yy)
            pp.addEllipse(QPointF(xx, yy), 2.2, 2.2)
    elif nom == "info":
        pp.addEllipse(QRectF(3.5, 3.5, 17, 17))
        pp.moveTo(12, 11)
        pp.lineTo(12, 16.5)
        pp.moveTo(12, 7.8)
        pp.lineTo(12, 8)
    elif nom == "plus":
        pp.moveTo(12, 5)
        pp.lineTo(12, 19)
        pp.moveTo(5, 12)
        pp.lineTo(19, 12)
    elif nom == "lecture":
        p.setBrush(couleur_)
        pp.moveTo(8, 5.5)
        pp.lineTo(18.5, 12)
        pp.lineTo(8, 18.5)
        pp.closeSubpath()
    elif nom == "pause":
        p.setBrush(couleur_)
        pp.addRoundedRect(QRectF(7, 5.5, 3.5, 13), 1, 1)
        pp.addRoundedRect(QRectF(13.5, 5.5, 3.5, 13), 1, 1)
    elif nom == "volume":
        pp.moveTo(4, 9.5)
        pp.lineTo(7.5, 9.5)
        pp.lineTo(12, 5.5)
        pp.lineTo(12, 18.5)
        pp.lineTo(7.5, 14.5)
        pp.lineTo(4, 14.5)
        pp.closeSubpath()
        pp.moveTo(15.5, 9)
        pp.cubicTo(17, 10.5, 17, 13.5, 15.5, 15)
        pp.moveTo(18, 6.5)
        pp.cubicTo(21, 9.5, 21, 14.5, 18, 17.5)
    elif nom == "muet":
        pp.moveTo(4, 9.5)
        pp.lineTo(7.5, 9.5)
        pp.lineTo(12, 5.5)
        pp.lineTo(12, 18.5)
        pp.lineTo(7.5, 14.5)
        pp.lineTo(4, 14.5)
        pp.closeSubpath()
        pp.moveTo(15.5, 9.5)
        pp.lineTo(20.5, 14.5)
        pp.moveTo(20.5, 9.5)
        pp.lineTo(15.5, 14.5)
    elif nom == "reseau":
        pp.addRoundedRect(QRectF(8.5, 3, 7, 5.5), 1.5, 1.5)
        pp.addRoundedRect(QRectF(2.5, 15.5, 7, 5.5), 1.5, 1.5)
        pp.addRoundedRect(QRectF(14.5, 15.5, 7, 5.5), 1.5, 1.5)
        pp.moveTo(12, 8.5)
        pp.lineTo(12, 12)
        pp.moveTo(6, 15.5)
        pp.lineTo(6, 12)
        pp.lineTo(18, 12)
        pp.lineTo(18, 15.5)
    elif nom == "capture":
        pp.addRoundedRect(QRectF(3, 6.5, 18, 13), 2.5, 2.5)
        pp.addEllipse(QPointF(12, 13), 3.5, 3.5)
        pp.moveTo(8.5, 6.5)
        pp.lineTo(10, 4.5)
        pp.lineTo(14, 4.5)
        pp.lineTo(15.5, 6.5)
    elif nom == "video":
        pp.addRoundedRect(QRectF(2.5, 6.5, 13, 11), 2.5, 2.5)
        pp.moveTo(15.5, 10.5)
        pp.lineTo(21, 7.5)
        pp.lineTo(21, 16.5)
        pp.lineTo(15.5, 13.5)
    elif nom == "lien":
        pp.moveTo(10, 14)
        pp.lineTo(14, 10)
        pp.addRoundedRect(QRectF(3.3, 11.3, 9, 6.5), 3.2, 3.2)
        pp.addRoundedRect(QRectF(11.7, 6.2, 9, 6.5), 3.2, 3.2)
    elif nom == "dossier":
        pp.moveTo(3.5, 7)
        pp.lineTo(9.5, 7)
        pp.lineTo(11.5, 9)
        pp.lineTo(20.5, 9)
        pp.lineTo(20.5, 18.5)
        pp.lineTo(3.5, 18.5)
        pp.closeSubpath()
    elif nom == "grille":
        for gx in (3.5, 13.5):
            for gy in (3.5, 13.5):
                pp.addRoundedRect(QRectF(gx, gy, 7, 7), 1.8, 1.8)
    elif nom == "plein_ecran":
        for cx, cy, dx, dy in ((4, 4, 1, 1), (20, 4, -1, 1), (4, 20, 1, -1), (20, 20, -1, -1)):
            pp.moveTo(cx + dx * 5.5, cy)
            pp.lineTo(cx, cy)
            pp.lineTo(cx, cy + dy * 5.5)
    elif nom == "retour":
        pp.moveTo(9, 6)
        pp.lineTo(4.5, 10.5)
        pp.lineTo(9, 15)
        pp.moveTo(4.5, 10.5)
        pp.lineTo(14, 10.5)
        pp.cubicTo(18, 10.5, 19.5, 13, 19.5, 15)
        pp.cubicTo(19.5, 17.5, 17.5, 19, 15, 19)
    elif nom == "recherche":
        pp.addEllipse(QRectF(4, 4, 12, 12))
        pp.moveTo(14.5, 14.5)
        pp.lineTo(20, 20)
    elif nom == "theme":
        pp.addEllipse(QRectF(4, 4, 16, 16))
        p.drawPath(pp)
        pp = QPainterPath()
        p.setBrush(couleur_)
        pp.moveTo(12, 4)
        pp.arcTo(QRectF(4, 4, 16, 16), 90, 180)
        pp.closeSubpath()
    p.drawPath(pp)
    p.restore()


def pixmap_icone(nom, couleur_, taille=18):
    ratio = 2
    pix = QPixmap(taille * ratio, taille * ratio)
    pix.setDevicePixelRatio(ratio)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    dessiner_icone(p, nom, QRectF(0, 0, taille, taille), QColor(couleur_))
    p.end()
    return pix
