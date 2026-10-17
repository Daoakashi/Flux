"""Page « Fréquentation » : carte de chaleur et statistiques de présence (où les gens se tiennent, combien,
à quelle heure, dans quelle zone). Données anonymes et agrégées (voir flux/frequentation.py)."""

import math
import os
import time
from datetime import datetime

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFontMetrics, QImage, QPainter, QPen
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

from . import frequentation as F
from .theme import C, couleur, police
from .widgets import Bouton, Interrupteur, Pastille, etiquette

PERIODES = [("jour", "Aujourd'hui"), ("hier", "Hier"), ("7j", "7 jours"), ("30j", "30 jours"), ("tout", "Tout")]


def bornes(periode):
    maintenant = time.time()
    minuit = time.mktime(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timetuple())
    return {"jour": (minuit, maintenant + 1), "hier": (minuit - 86400, minuit),
            "7j": (minuit - 6 * 86400, maintenant + 1), "30j": (minuit - 29 * 86400, maintenant + 1),
            "tout": (0, maintenant + 1)}[periode]


def nombre(v, decimales=1):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    return f"{v:.{decimales}f}".replace(".", ",")


def duree(secondes):
    s = int(round(secondes))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min {s % 60:02d} s" if s % 60 else f"{s // 60} min"
    return f"{s // 3600} h {(s % 3600) // 60:02d}"


def carte_widget():
    f = QFrame()
    f.setObjectName("carte")
    return f


# ---------------------------------------------------------------------------
# Carte de chaleur
# ---------------------------------------------------------------------------
class VueCarte(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(300, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._img = None
        self._nd = None
        self.message = ""

    def definir(self, bgr):
        if bgr is None:
            self._img = self._nd = None
        else:
            self._nd = np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
            h, w = self._nd.shape[:2]
            self._img = QImage(self._nd.data, w, h, self._nd.strides[0], QImage.Format.Format_RGB888)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect())
        legende_h = 34
        zone = r.adjusted(0, 0, 0, -legende_h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(couleur("video"))
        p.drawRoundedRect(zone, 10, 10)
        if self._img is not None:
            iw, ih = self._img.width(), self._img.height()
            s = min(zone.width() / iw, zone.height() / ih)
            cible = QRectF(zone.center().x() - iw * s / 2, zone.center().y() - ih * s / 2, iw * s, ih * s)
            p.drawImage(cible, self._img)
        else:
            p.setPen(couleur("texte2"))
            p.setFont(police(None))
            p.drawText(zone.adjusted(30, 0, -30, 0), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                       self.message)
        # légende : du moins au plus fréquenté
        y = r.bottom() - legende_h + 12
        p.setFont(police(max(9, 11)))
        fm = QFontMetrics(p.font())
        g_txt, d_txt = "Peu de monde", "Beaucoup de monde"
        x0 = r.left() + fm.horizontalAdvance(g_txt) + 12
        x1 = r.right() - fm.horizontalAdvance(d_txt) - 12
        p.setPen(couleur("texte2"))
        p.drawText(QRectF(r.left(), y - 2, x0 - r.left() - 8, 16), Qt.AlignmentFlag.AlignVCenter, g_txt)
        p.drawText(QRectF(x1 + 4, y - 2, r.right() - x1 - 4, 16),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, d_txt)
        cols = F.couleurs_legende(24)
        larg = (x1 - x0) / len(cols)
        p.setPen(Qt.PenStyle.NoPen)
        for i, c in enumerate(cols):
            p.setBrush(QColor(*c))
            p.drawRect(QRectF(x0 + i * larg, y + 1, larg + 0.6, 10))


# ---------------------------------------------------------------------------
# Graphique en barres (par heure, par jour)
# ---------------------------------------------------------------------------
class Barres(QWidget):
    """Barres simples aux couleurs de Flux. La barre la plus haute est mise en avant ; infobulle au survol."""

    def __init__(self, unite="", decimales=1):
        super().__init__()
        self.decimales = decimales
        self.setMinimumHeight(150)
        self.setMouseTracking(True)
        self.valeurs, self.etiquettes, self.textes = [], [], []
        self.unite = unite
        self._survol = -1

    def definir(self, valeurs, etiquettes, textes=None):
        self.valeurs = [None if (v is None or (isinstance(v, float) and math.isnan(v))) else float(v) for v in valeurs]
        self.etiquettes = etiquettes
        self.textes = textes or [""] * len(valeurs)
        self.update()

    def _geometrie(self):
        r = QRectF(self.rect()).adjusted(4, 8, -4, -22)
        n = max(1, len(self.valeurs))
        pas = r.width() / n
        return r, pas

    def mouseMoveEvent(self, e):
        r, pas = self._geometrie()
        i = int((e.position().x() - r.left()) // pas) if pas else -1
        i = i if 0 <= i < len(self.valeurs) else -1
        if i != self._survol:
            self._survol = i
            self.setToolTip(self.textes[i] if i >= 0 else "")
            self.update()

    def leaveEvent(self, e):
        self._survol = -1
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r, pas = self._geometrie()
        vals = [v for v in self.valeurs if v is not None]
        haut = max(vals) if vals else 0
        p.setPen(QPen(couleur("trait"), 1))
        p.drawLine(QPointF(r.left(), r.bottom() + 0.5), QPointF(r.right(), r.bottom() + 0.5))
        if not vals or haut <= 0:
            p.setPen(couleur("texte3"))
            p.setFont(police(None))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, "Pas encore de données")
            return
        i_max = self.valeurs.index(haut)
        largeur = max(2.0, pas * 0.68)
        for i, v in enumerate(self.valeurs):
            x = r.left() + i * pas + (pas - largeur) / 2
            if v is None:
                continue
            h = max(1.5, r.height() * v / haut)
            teinte = couleur("accent") if i == i_max else couleur("accent", 120)
            if i == self._survol:
                teinte = couleur("accent_vif")
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(teinte)
            p.drawRoundedRect(QRectF(x, r.bottom() - h, largeur, h), min(3, largeur / 2), min(3, largeur / 2))
        # valeur du pic
        p.setPen(couleur("texte"))
        p.setFont(police(10, True))
        x = r.left() + i_max * pas + pas / 2
        txt = nombre(haut, self.decimales) + self.unite
        p.drawText(QRectF(min(max(r.left(), x - 40), r.right() - 80), r.top() - 8, 80, 14), Qt.AlignmentFlag.AlignCenter,
                   txt)
        # étiquettes de l'axe
        p.setPen(couleur("texte3"))
        p.setFont(police(9))
        n = len(self.etiquettes)
        tous = max(1, math.ceil(n / max(1, int(r.width() // 34))))
        for i, t in enumerate(self.etiquettes):
            if i == i_max or (i % tous == 0 and abs(i - i_max) >= max(2, tous)):
                p.setPen(couleur("texte") if i == i_max else couleur("texte3"))
                p.drawText(QRectF(r.left() + i * pas - 10, r.bottom() + 4, pas + 20, 16), Qt.AlignmentFlag.AlignHCenter, t)


# ---------------------------------------------------------------------------
# Une ligne par zone
# ---------------------------------------------------------------------------
class ListeZones(QWidget):
    def __init__(self):
        super().__init__()
        self.lignes = []
        self.setMinimumHeight(40)

    def definir(self, zones):
        """zones : liste (nom, part 0-1, passages, temps moyen en s)."""
        self.lignes = zones
        self.setMinimumHeight(max(40, 64 * len(zones)))
        self.updateGeometry()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.lignes:
            p.setPen(couleur("texte3"))
            p.setFont(police(None))
            p.drawText(QRectF(self.rect()), Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap,
                       "Dessinez des zones sur l'image de la caméra (rayons, caisse, entrée…) pour comparer leur "
                       "fréquentation.")
            return
        w = self.width()
        for i, (nom, part, passages, moyen) in enumerate(self.lignes):
            y = i * 64
            p.setFont(police(None, True))
            p.setPen(couleur("texte"))
            m = p.fontMetrics()
            p.drawText(QRectF(0, y, w - 60, 20), Qt.AlignmentFlag.AlignVCenter,
                       m.elidedText(nom, Qt.TextElideMode.ElideRight, int(w - 60)))
            p.drawText(QRectF(w - 60, y, 60, 20), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                       f"{nombre(100 * part, 0)} %")
            fond = QRectF(0, y + 24, w, 8)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(couleur("surface2"))
            p.drawRoundedRect(fond, 4, 4)
            p.setBrush(couleur("accent"))
            p.drawRoundedRect(QRectF(0, y + 24, max(8.0, w * part), 8), 4, 4)
            p.setFont(police(9))
            p.setPen(couleur("texte2"))
            detail = f"{passages} passage{'s' if passages > 1 else ''}" + (f" · {duree(moyen)} en moyenne" if moyen else "")
            p.drawText(QRectF(0, y + 36, w, 18), Qt.AlignmentFlag.AlignVCenter,
                       p.fontMetrics().elidedText(detail, Qt.TextElideMode.ElideRight, int(w)))


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
class Tuile(QFrame):
    def __init__(self, titre):
        super().__init__()
        self.setObjectName("carte")
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 10)
        v.setSpacing(2)
        t = QLabel(titre.upper())
        t.setObjectName("section")
        self.valeur = QLabel("—")
        self.valeur.setStyleSheet(f"font-size: 22px; font-weight: 650;")
        self.detail = etiquette("", "aide")
        v.addWidget(t)
        v.addWidget(self.valeur)
        v.addWidget(self.detail)

    def regler(self, valeur, detail=""):
        self.valeur.setText(valeur)
        self.detail.setText(detail)


class PageFrequentation(QWidget):
    def __init__(self, fen):
        super().__init__()
        self.fen, self.cfg, self.base = fen, fen.cfg, fen.base
        self.periode = "jour"
        self.stats = None
        self.image = None
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        haut = QHBoxLayout()
        t = QLabel("Fréquentation")
        t.setObjectName("titre_page")
        haut.addWidget(t)
        haut.addSpacing(16)
        self.combo = QComboBox()
        self.combo.setMinimumWidth(200)
        self.combo.currentIndexChanged.connect(lambda _i: self.rafraichir())
        haut.addWidget(self.combo)
        haut.addStretch(1)
        b_img = Bouton("Exporter l'image", "discret", "capture")
        b_img.clicked.connect(self._exporter_image)
        b_csv = Bouton("Exporter en CSV", "discret")
        b_csv.clicked.connect(self._exporter_csv)
        haut.addWidget(b_img)
        haut.addWidget(b_csv)
        v.addLayout(haut)
        ligne_p = QHBoxLayout()
        ligne_p.setSpacing(8)
        self.pastilles = {}
        for cle, lib in PERIODES:
            b = Pastille(lib, "accent")
            b.clicked.connect(lambda _=False, k=cle: self._periode(k))
            self.pastilles[cle] = b
            ligne_p.addWidget(b)
        self.pastilles[self.periode].regler(True)
        ligne_p.addStretch(1)
        v.addLayout(ligne_p)
        v.addWidget(etiquette("Où les personnes se tiennent et combien elles sont, heure par heure. Données anonymes : "
                              "seules des positions et des comptages sont enregistrés, jamais d'image de personne ni "
                              "d'identité.", "soustitre"))

        corps = QHBoxLayout()
        corps.setSpacing(14)
        gauche = carte_widget()
        gv = QVBoxLayout(gauche)
        gv.setContentsMargins(14, 12, 14, 10)
        gv.setSpacing(8)
        lg = QHBoxLayout()
        lab = QLabel("Carte de chaleur")
        lab.setObjectName("titre")
        lg.addWidget(lab)
        lg.addStretch(1)
        lg.addWidget(etiquette("Zones", "aide"))
        self.i_zones = Interrupteur()
        self.i_zones.regler(True)
        self.i_zones.toggled.connect(lambda _e: self._rendre())
        lg.addWidget(self.i_zones)
        gv.addLayout(lg)
        self.carte = VueCarte()
        gv.addWidget(self.carte, 1)
        corps.addWidget(gauche, 1)

        defil = QScrollArea()
        defil.setWidgetResizable(True)
        defil.setMinimumWidth(300)
        defil.setMaximumWidth(420)
        defil.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        droite = QWidget()
        dv = QVBoxLayout(droite)
        dv.setContentsMargins(0, 0, 8, 0)
        dv.setSpacing(12)
        grille = QGridLayout()
        grille.setSpacing(10)
        self.t_passages = Tuile("Passages")
        self.t_moyenne = Tuile("Présence moyenne")
        self.t_pic = Tuile("Pic")
        self.t_pointe = Tuile("Heure de pointe")
        for i, tu in enumerate((self.t_passages, self.t_moyenne, self.t_pic, self.t_pointe)):
            grille.addWidget(tu, i // 2, i % 2)
        dv.addLayout(grille)

        c1 = carte_widget()
        c1v = QVBoxLayout(c1)
        c1v.setContentsMargins(14, 12, 14, 12)
        l1 = QLabel("Par heure de la journée")
        l1.setObjectName("titre")
        c1v.addWidget(l1)
        c1v.addWidget(etiquette("Nombre moyen de personnes présentes en même temps.", "aide"))
        self.barres_heure = Barres()
        c1v.addWidget(self.barres_heure)
        dv.addWidget(c1)

        self.c_jours = carte_widget()
        c2v = QVBoxLayout(self.c_jours)
        c2v.setContentsMargins(14, 12, 14, 12)
        l2 = QLabel("Par jour")
        l2.setObjectName("titre")
        c2v.addWidget(l2)
        c2v.addWidget(etiquette("Nombre de passages.", "aide"))
        self.barres_jour = Barres(decimales=0)
        c2v.addWidget(self.barres_jour)
        dv.addWidget(self.c_jours)

        c3 = carte_widget()
        c3v = QVBoxLayout(c3)
        c3v.setContentsMargins(14, 12, 14, 12)
        l3 = QLabel("Par zone")
        l3.setObjectName("titre")
        c3v.addWidget(l3)
        c3v.addWidget(etiquette("Part du temps de présence passé dans chaque zone.", "aide"))
        self.zones = ListeZones()
        c3v.addWidget(self.zones)
        dv.addWidget(c3)
        dv.addStretch(1)
        self.lbl_obs = etiquette("", "aide")
        dv.addWidget(self.lbl_obs)
        defil.setWidget(droite)
        corps.addWidget(defil)
        v.addLayout(corps, 1)

        try:  # ménage : statistiques plus anciennes que la durée de conservation
            F.purger(self.base, int(self.cfg.get("frequentation.conservation")))
        except Exception:  # noqa: BLE001
            pass
        self._minuteur = QTimer(self)
        self._minuteur.setInterval(30000)
        self._minuteur.timeout.connect(lambda: self.isVisible() and self.rafraichir())
        self._minuteur.start()

    # --- données -----------------------------------------------------------------------
    def _cameras(self):
        noms = []
        try:
            noms = [p.nom for p in self.fen.page_cameras.pages]
        except Exception:  # noqa: BLE001
            pass
        try:
            noms += [n for n in F.cameras(self.base) if n not in noms]
        except Exception:  # noqa: BLE001
            pass
        return noms

    def _zones_camera(self, nom):
        try:
            from .vision import zones_options
            page = next((p for p in self.fen.page_cameras.pages if p.nom == nom), None)
            return zones_options(page.o) if page is not None else []
        except Exception:  # noqa: BLE001
            return []

    def actualiser_liste(self):
        actuel = self.combo.currentText()
        noms = self._cameras()
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItems(noms)
        if actuel in noms:
            self.combo.setCurrentText(actuel)
        self.combo.blockSignals(False)

    def _periode(self, cle):
        self.periode = cle
        for k, b in self.pastilles.items():
            b.regler(k == cle)
        self.rafraichir()

    def rafraichir(self):
        if self.combo.count() == 0:
            self.actualiser_liste()
        camera = self.combo.currentText()
        if not camera:
            self.stats = None
            self.carte.message = ("Aucune caméra. Ajoutez une caméra et laissez-la tourner avec la détection : la carte "
                                  "de chaleur et les statistiques se remplissent toutes seules.")
            self.carte.definir(None)
            return
        # les mesures en cours (moins d'une minute) sont écrites avant l'affichage
        try:
            page = next((p for p in self.fen.page_cameras.pages if p.nom == camera), None)
            if page is not None and page.detecteur is not None:
                page.detecteur.frequentation.vider()
        except Exception:  # noqa: BLE001
            pass
        debut, fin = bornes(self.periode)
        self.stats = F.charger(self.base, camera, debut, fin)
        self._remplir(camera)
        self._rendre()

    def _remplir(self, camera):
        s = self.stats
        if not s["lignes"]:
            for t in (self.t_passages, self.t_moyenne, self.t_pic, self.t_pointe):
                t.regler("—")
            self.barres_heure.definir([], [])
            self.barres_jour.definir([], [])
            self.zones.definir([])
            self.lbl_obs.setText("")
            return
        self.t_passages.regler(f"{s['passages']}", "personnes différentes")
        self.t_moyenne.regler(nombre(s["moyenne"]), "personnes en même temps")
        quand = ""
        if s["heure_max"]:
            lt = time.localtime(s["heure_max"])
            quand = f"vers {lt.tm_hour} h" + ("" if self.periode in ("jour", "hier") else f" le {lt.tm_mday:02d}/{lt.tm_mon:02d}")
        self.t_pic.regler(f"{s['max_personnes']}", f"personnes {quand}".strip())
        ph = s["par_heure"]
        if np.all(np.isnan(ph)):
            self.t_pointe.regler("—")
        else:
            h = int(np.nanargmax(ph))
            self.t_pointe.regler(f"{h} h – {h + 1} h", f"{nombre(ph[h])} personnes en moyenne")
        self.barres_heure.definir(list(ph), [f"{h}h" for h in range(24)],
                                  [f"{h} h – {h + 1} h : " + ("pas de mesure" if np.isnan(v) else
                                                             f"{nombre(v)} personne(s) en moyenne")
                                   for h, v in enumerate(ph)])
        jours = sorted(s["par_jour"].items())
        self.c_jours.setVisible(len(jours) > 1)
        self.barres_jour.definir([j[1][0] for j in jours], [j[0][8:10] + "/" + j[0][5:7] for j in jours],
                                 [f"{j[0][8:10]}/{j[0][5:7]} : {j[1][0]} passage(s)" for j in jours])
        total = sum(v[0] for v in s["zones"].values()) or 1
        self.zones.definir([(n, v[0] / total, v[1], v[0] / v[1] if v[1] else 0)
                            for n, v in sorted(s["zones"].items(), key=lambda x: -x[1][0])])
        self.lbl_obs.setText(f"Temps observé : {duree(s['observe'])} · temps de présence cumulé : "
                             f"{duree(s['presence'])}.")

    def _rendre(self):
        camera = self.combo.currentText()
        if not camera or self.stats is None:
            return
        fond = F.fond(self.base, camera)
        if fond is None:
            try:
                page = next((p for p in self.fen.page_cameras.pages if p.nom == camera), None)
                if page is not None and page.detecteur is not None and page.detecteur.derniere_image is not None:
                    fond = page.detecteur.derniere_image.copy()
            except Exception:  # noqa: BLE001
                fond = None
        zones = self._zones_camera(camera) if self.i_zones.isChecked() else []
        if not self.stats["lignes"]:
            self.image = None
            self.carte.message = (f"Pas encore de mesure pour « {camera} » sur cette période. Laissez la caméra tourner "
                                  f"avec la détection active : la carte se remplit toute seule.")
            self.carte.definir(None)
            return
        self.image = F.rendre(fond, self.stats["grille"], self.cfg.get("frequentation.opacite") / 100, zones)
        self.carte.definir(self.image)

    # --- export ------------------------------------------------------------------------
    def _nom_fichier(self, ext):
        camera = self.combo.currentText() or "camera"
        return os.path.join(self.cfg.dossier_sortie(),
                            f"frequentation_{camera}_{self.periode}_{datetime.now():%Y%m%d_%H%M}.{ext}")

    def _exporter_image(self):
        if self.image is None:
            self.fen.toast("Rien à exporter pour l'instant.")
            return
        chemin, _ = QFileDialog.getSaveFileName(self, "Exporter la carte de chaleur", self._nom_fichier("png"),
                                                "Image PNG (*.png)")
        if chemin:
            ok, buf = cv2.imencode(".png", self.image)
            if ok:
                with open(chemin, "wb") as f:
                    f.write(buf.tobytes())
                self.fen.toast(f"Carte exportée : {os.path.basename(chemin)}", "ok")

    def _exporter_csv(self):
        if self.stats is None or not self.stats["lignes"]:
            self.fen.toast("Rien à exporter pour l'instant.")
            return
        chemin, _ = QFileDialog.getSaveFileName(self, "Exporter les statistiques", self._nom_fichier("csv"),
                                                "Tableur CSV (*.csv)")
        if chemin:
            F.exporter_csv(chemin, self.combo.currentText(), self.stats)
            self.fen.toast(f"Statistiques exportées : {os.path.basename(chemin)}", "ok")
