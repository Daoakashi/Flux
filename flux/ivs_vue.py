"""IVS sur l'image d'une caméra : tracer, modifier et afficher les flèches de franchissement A → B."""
import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainterPath, QPen, QPolygonF

from .ivs import LARGEUR_DEFAUT, MAX_FLECHES, copie_fleche, fleches_options
from .theme import C

ORANGE = "#F97316"
ROUGE = "#EF4444"
DUREE_FLASH = 3.0


def _distance_segment(p, a, b):
    dx, dy = b.x() - a.x(), b.y() - a.y()
    l2 = dx * dx + dy * dy
    if l2 <= 0:
        return math.hypot(p.x() - a.x(), p.y() - a.y())
    t = max(0.0, min(1.0, ((p.x() - a.x()) * dx + (p.y() - a.y()) * dy) / l2))
    return math.hypot(p.x() - (a.x() + t * dx), p.y() - (a.y() + t * dy))


class EditeurFleches:
    """Rattaché à une VueVideo (vue.ivs). Mode IVS actif : glisser de A vers B trace une flèche ; tirer un bout
    la modifie, tirer le trait la déplace ; clic droit : renommer A, B, la flèche, inverser, alarme, supprimer."""

    RAYON = 10

    def __init__(self, vue):
        self.v = vue
        self.fleches = []
        self.actif = False
        self.sel = None
        self.geste = None
        self.flash = {}

    # --- données -----------------------------------------------------------------------------
    def definir(self, fleches):
        self.fleches = fleches_options({"fleches": fleches or []})
        if self.sel is not None and self.sel >= len(self.fleches):
            self.sel = None

    def liste(self):
        return [copie_fleche(f) for f in self.fleches]

    def _emettre(self):
        self.v.flechesChangees.emit(self.liste())

    def regler_actif(self, actif):
        self.actif = bool(actif)
        self.geste = None
        if not actif:
            self.selectionner(None)
        self.v.setCursor(Qt.CursorShape.CrossCursor if actif else Qt.CursorShape.ArrowCursor)
        self.v.update()

    def selectionner(self, i, emettre=True):
        i = i if i is not None and 0 <= i < len(self.fleches) else None
        if i != self.sel:
            self.sel = i
            if emettre:
                self.v.flecheSelectionnee.emit(-1 if i is None else i)

    def signaler(self, nom):
        self.flash[nom] = time.time()

    def nom_libre(self):
        noms, i = {f["nom"] for f in self.fleches}, len(self.fleches) + 1
        while f"Flèche {i}" in noms:
            i += 1
        return f"Flèche {i}"

    def modifier(self, i, **champs):
        if 0 <= i < len(self.fleches):
            self.fleches[i].update(champs)
            self._emettre()

    def supprimer(self, i):
        if 0 <= i < len(self.fleches):
            del self.fleches[i]
            self.selectionner(None)
            self._emettre()

    # --- souris --------------------------------------------------------------------------------
    def _ecran(self, pt):
        return self.v._vers_ecran(*pt)

    def sous(self, pos):
        """("a" | "b" | "trait", indice) sous le curseur, la flèche choisie passant devant les autres."""
        ordre = list(range(len(self.fleches) - 1, -1, -1))
        if self.sel is not None:
            ordre.remove(self.sel)
            ordre.insert(0, self.sel)
        for i in ordre:
            f = self.fleches[i]
            a, b = self._ecran(f["a"]), self._ecran(f["b"])
            if math.hypot(pos.x() - b.x(), pos.y() - b.y()) <= self.RAYON + 2:
                return "b", i
            if math.hypot(pos.x() - a.x(), pos.y() - a.y()) <= self.RAYON + 2:
                return "a", i
        for i in ordre:
            f = self.fleches[i]
            if _distance_segment(pos, self._ecran(f["a"]), self._ecran(f["b"])) <= 7:
                return "trait", i
        return None

    def presser(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return False
        pos = e.position()
        n = self.v._vers_norm(pos)
        cible = self.sous(pos)
        if cible:
            typ, i = cible
            self.selectionner(i)
            self.geste = {"type": typ, "i": i, "orig": copie_fleche(self.fleches[i]), "depart": n}
            self.v.setCursor(Qt.CursorShape.ClosedHandCursor if typ == "trait" else Qt.CursorShape.SizeAllCursor)
            return True
        if len(self.fleches) >= MAX_FLECHES:  # limite atteinte : on ne trace plus
            return True
        self.geste = {"type": "nouvelle", "a": n, "b": n, "pos0": QPointF(pos)}
        return True

    def bouger(self, e):
        g = self.geste
        n = self.v._vers_norm(e.position())
        if g["type"] == "nouvelle":
            g["b"] = n
        elif g["type"] in ("a", "b"):
            self.fleches[g["i"]][g["type"]] = n
        else:  # déplacer toute la flèche, sans sortir de l'image
            o = g["orig"]
            dx = n[0] - g["depart"][0]
            dy = n[1] - g["depart"][1]
            xs, ys = (o["a"][0], o["b"][0]), (o["a"][1], o["b"][1])
            dx = min(max(dx, -min(xs)), 1 - max(xs))
            dy = min(max(dy, -min(ys)), 1 - max(ys))
            f = self.fleches[g["i"]]
            f["a"] = (o["a"][0] + dx, o["a"][1] + dy)
            f["b"] = (o["b"][0] + dx, o["b"][1] + dy)

    def relacher(self, e):
        g, self.geste = self.geste, None
        self.v.setCursor(Qt.CursorShape.CrossCursor)
        if g["type"] == "nouvelle":
            a, b = self._ecran(g["a"]), self._ecran(g["b"])
            if math.hypot(b.x() - a.x(), b.y() - a.y()) < 25:  # simple clic : désélection
                self.selectionner(None)
                return
            self.fleches.append({"nom": self.nom_libre(), "a": g["a"], "b": g["b"], "nom_a": "A", "nom_b": "B",
                                 "alarme": True, "largeur": LARGEUR_DEFAUT})
            self.selectionner(len(self.fleches) - 1)
            self._emettre()
            return
        f = self.fleches[g["i"]]
        if math.hypot(f["b"][0] - f["a"][0], f["b"][1] - f["a"][1]) < 0.02:  # flèche écrasée : retour
            self.fleches[g["i"]] = g["orig"]
        elif f != g["orig"]:
            self._emettre()

    def annuler(self):
        g, self.geste = self.geste, None
        if g and "orig" in g and g["i"] < len(self.fleches):
            self.fleches[g["i"]] = g["orig"]

    def curseur(self, pos):
        cible = self.sous(pos)
        if cible is None:
            forme = Qt.CursorShape.CrossCursor
        elif cible[0] == "trait":
            forme = Qt.CursorShape.OpenHandCursor
        else:
            forme = Qt.CursorShape.SizeAllCursor
        if self.v.cursor().shape() != forme:
            self.v.setCursor(forme)

    def menu(self, e):
        from PySide6.QtWidgets import QMenu
        cible = self.sous(e.position())
        m = QMenu(self.v)
        if cible:
            i = cible[1]
            self.selectionner(i)
            f = self.fleches[i]
            m.addAction(f"Renommer « {f['nom']} »…", lambda: self.renommer(i, "nom"))
            m.addAction(f"Renommer le point A (« {f['nom_a']} »)…", lambda: self.renommer(i, "nom_a"))
            m.addAction(f"Renommer le point B (« {f['nom_b']} »)…", lambda: self.renommer(i, "nom_b"))
            m.addAction("Inverser le sens (B → A)", lambda: self.inverser(i))
            act = m.addAction("Alarme")
            act.setCheckable(True)
            act.setChecked(f["alarme"])
            act.triggered.connect(lambda c: self.modifier(i, alarme=bool(c)))
            m.addSeparator()
            m.addAction(f"Supprimer « {f['nom']} »", lambda: self.supprimer(i))
        if self.fleches:
            m.addSeparator()
            m.addAction("Effacer toutes les flèches", self.tout_effacer)
        m.addSeparator()
        m.addAction("Quitter le tracé des flèches", lambda: self.v.flecheModeQuitte.emit())
        m.exec(e.globalPosition().toPoint())

    def renommer(self, i, champ):
        from PySide6.QtWidgets import QInputDialog
        f = self.fleches[i]
        titres = {"nom": ("Renommer la flèche", "Nom de la flèche :"),
                  "nom_a": ("Renommer le point A", "Nom du point de départ (A) :"),
                  "nom_b": ("Renommer le point B", "Nom du point d'arrivée (B) :")}
        t, q = titres[champ]
        texte, ok = QInputDialog.getText(self.v, t, q, text=f[champ])
        texte = texte.strip()[:60] if ok else ""
        if not texte:
            return
        if champ == "nom" and any(x["nom"] == texte for j, x in enumerate(self.fleches) if j != i):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self.v, t, "Une autre flèche de cette caméra porte déjà ce nom.")
            return
        self.modifier(i, **{champ: texte})

    def inverser(self, i):
        f = self.fleches[i]
        self.modifier(i, a=f["b"], b=f["a"], nom_a=f["nom_b"], nom_b=f["nom_a"])

    def tout_effacer(self):
        self.fleches = []
        self.selectionner(None)
        self._emettre()

    # --- dessin --------------------------------------------------------------------------------
    def dessiner(self, p, now):
        if not self.fleches and not (self.geste and self.geste["type"] == "nouvelle"):
            return
        _, _, s = self.v._geom
        largeur_img = self.v._taille[0] * s
        p.save()
        for i, f in enumerate(self.fleches):
            t_flash = self.flash.get(f["nom"])
            flash = t_flash is not None and now - t_flash < DUREE_FLASH
            self._fleche(p, f, now, largeur_img, choisie=(i == self.sel), flash=flash)
        g = self.geste
        if g and g["type"] == "nouvelle":
            a, b = self._ecran(g["a"]), self._ecran(g["b"])
            if math.hypot(b.x() - a.x(), b.y() - a.y()) >= 4:
                self._fleche(p, {"nom": self.nom_libre(), "a": g["a"], "b": g["b"], "nom_a": "A", "nom_b": "B",
                                 "alarme": True, "largeur": LARGEUR_DEFAUT}, now, largeur_img, choisie=True, apercu=True)
        p.restore()

    def _fleche(self, p, f, now, largeur_img, choisie=False, flash=False, apercu=False):
        a, b = self._ecran(f["a"]), self._ecran(f["b"])
        dx, dy = b.x() - a.x(), b.y() - a.y()
        long_ = math.hypot(dx, dy) or 1.0
        ux, uy = dx / long_, dy / long_
        nx, ny = -uy, ux
        if flash:
            pulse = 0.5 + 0.5 * math.sin(now * 12)
            teinte = QColor(ROUGE)
            teinte.setAlphaF(0.55 + 0.45 * pulse)
        else:
            teinte = QColor(ORANGE if f["alarme"] else C.get("accent", "#2F7BFF"))
        # couloir de détection (visible pendant le tracé, ou en rouge pendant une alerte)
        if self.actif or choisie or flash:
            demi = f["largeur"] * largeur_img
            couloir = QPolygonF([QPointF(a.x() + nx * demi, a.y() + ny * demi), QPointF(b.x() + nx * demi, b.y() + ny * demi),
                                 QPointF(b.x() - nx * demi, b.y() - ny * demi), QPointF(a.x() - nx * demi, a.y() - ny * demi)])
            fond = QColor(teinte)
            fond.setAlpha(60 if flash else 26)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fond)
            p.drawPolygon(couloir)
        # trait (avec un liseré sombre pour rester lisible sur n'importe quelle image)
        epaisseur = 4.5 if (choisie or flash) else 3.2
        tete = 16.0
        fin = QPointF(b.x() - ux * tete * 0.8, b.y() - uy * tete * 0.8)
        for couleur_, e in ((QColor(0, 0, 0, 140), epaisseur + 3), (teinte, epaisseur)):
            pen = QPen(couleur_, e, Qt.PenStyle.DashLine if apercu else Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(a, fin)
        pointe = QPolygonF([b, QPointF(b.x() - ux * tete + nx * tete * 0.55, b.y() - uy * tete + ny * tete * 0.55),
                            QPointF(b.x() - ux * tete - nx * tete * 0.55, b.y() - uy * tete - ny * tete * 0.55)])
        p.setPen(QPen(QColor(0, 0, 0, 140), 2))
        p.setBrush(teinte)
        p.drawPolygon(pointe)
        # point A : rond ; B : la pointe (avec un rond de prise en mode tracé)
        p.setPen(QPen(QColor("white"), 2))
        p.setBrush(teinte)
        p.drawEllipse(a, 7, 7)
        if self.actif and choisie:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor("white"), 1.5, Qt.PenStyle.DotLine))
            p.drawEllipse(b, self.RAYON, self.RAYON)
            p.drawEllipse(a, self.RAYON, self.RAYON)
        # étiquettes
        police = QFont(p.font())
        police.setPixelSize(12)
        police.setBold(True)
        p.setFont(police)
        # noms de A et B dans le prolongement de la flèche, sans cacher la pointe
        self._etiquette(p, a, f["nom_a"], teinte, direction=(-ux, -uy))
        self._etiquette(p, b, f["nom_b"], teinte, direction=(ux, uy))
        milieu = QPointF((a.x() + b.x()) / 2 + nx * 18, (a.y() + b.y()) / 2 + ny * 18)
        texte = f["nom"] + ("" if f["alarme"] else "  (sans alarme)")
        self._etiquette(p, milieu, texte, QColor(20, 26, 38, 220), clair=True)

    @staticmethod
    def _etiquette(p, centre, texte, fond, clair=False, direction=None):
        fm = QFontMetricsF(p.font())
        w, h = fm.horizontalAdvance(texte) + 12, fm.height() + 4
        if direction is not None:  # posée à côté du point, du côté indiqué
            dx, dy = direction
            ecart = abs(dx) * w / 2 + abs(dy) * h / 2 + 12
            centre = QPointF(centre.x() + dx * ecart, centre.y() + dy * ecart)
        r = QRectF(centre.x() - w / 2, centre.y() - h / 2, w, h)
        chemin = QPainterPath()
        chemin.addRoundedRect(r, h / 2, h / 2)
        f = QColor(fond)
        if not clair:
            f.setAlpha(230)
        p.fillPath(chemin, f)
        p.setPen(QColor("white"))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, texte)
