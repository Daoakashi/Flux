"""Éditeur de réglages : liste tous les réglages du schéma, avec recherche, aperçu immédiat du style
de la fenêtre, réinitialisation individuelle, import et export."""

import os

from PySide6.QtCore import QRectF, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QScrollArea,
                               QSlider, QSpinBox, QVBoxLayout, QWidget)

from .config import CATEGORIES, CATEGORIES_CACHEES, DOSSIER_MODELES, NIVEAUX, SCHEMA, nom_modele
from .theme import C, PALETTES, T, couleur, police
from .widgets import Bouton, Interrupteur, etiquette, separateur

ACCENTS = ["#2F7BFF", "#1D4ED8", "#0EA5E9", "#3B5BDB", "#06B6D4", "#6366F1"]


class TuileTheme(QAbstractButton):
    """Aperçu miniature d'un thème, cliquable."""

    def __init__(self, cle, libelle):
        super().__init__()
        self.cle, self.libelle = cle, libelle
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(190, 128)

    def paintEvent(self, _):
        pal = PALETTES[self.cle]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        p.setPen(QPen(couleur("accent") if self.isChecked() else couleur("trait"), 2.5 if self.isChecked() else 1))
        p.setBrush(QColor(pal["fond"]))
        p.drawRoundedRect(r, T.rayon + 2, T.rayon + 2)
        # mini fenêtre : barre latérale, carte, bouton d'accent
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(pal["panneau"]))
        p.drawRoundedRect(QRectF(r.left() + 8, r.top() + 8, 36, r.height() - 40), 5, 5)
        p.setBrush(QColor(pal["surface"]))
        p.drawRoundedRect(QRectF(r.left() + 52, r.top() + 8, r.width() - 60, r.height() - 40), 5, 5)
        p.setBrush(QColor(C["accent"]))
        p.drawRoundedRect(QRectF(r.left() + 60, r.top() + 16, 46, 10), 4, 4)
        p.setBrush(QColor(pal["trait"]))
        for i in range(3):
            p.drawRoundedRect(QRectF(r.left() + 60, r.top() + 34 + i * 12, r.width() - 80 - i * 18, 6), 3, 3)
        p.setPen(QColor(pal["texte"]))
        p.setFont(police(None, True))
        p.drawText(QRectF(r.left() + 10, r.bottom() - 28, r.width() - 20, 24),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.libelle)


class Pastille_couleur(QAbstractButton):
    def __init__(self, hexa):
        super().__init__()
        self.hexa = hexa
        self.setCheckable(True)
        self.setFixedSize(30, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(hexa)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.isChecked():
            p.setPen(QPen(couleur("texte"), 2))
            p.drawEllipse(QRectF(1.5, 1.5, 27, 27))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self.hexa))
        p.drawEllipse(QRectF(5, 5, 20, 20))


class CarteNiveau(QAbstractButton):
    """Carte d'un niveau de scan, avec le nom du modèle."""

    def __init__(self, cle, n):
        super().__init__()
        self.cle, self.n = cle, n
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(118)
        self.setMinimumWidth(200)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        sel = self.isChecked()
        p.setPen(QPen(couleur("accent") if sel else couleur("trait"), 2 if sel else 1))
        p.setBrush(couleur("accent_doux") if sel else couleur("surface"))
        p.drawRoundedRect(r, T.rayon + 2, T.rayon + 2)
        # jauge de précision : 1 à 4 barres
        rang = list(NIVEAUX).index(self.cle) + 1
        for i in range(4):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(couleur("accent") if i < rang else couleur("trait"))
            h = 6 + i * 4
            p.drawRoundedRect(QRectF(r.right() - 52 + i * 10, r.top() + 30 - h, 6, h), 2, 2)
        p.setPen(couleur("texte"))
        p.setFont(police(T.taille + 3, True))
        p.drawText(QRectF(r.left() + 14, r.top() + 10, r.width() - 80, 26),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.n["nom"])
        p.setPen(couleur("accent_vif"))
        p.setFont(police(T.taille - 1, True))
        modele = nom_modele(self.n["modele"])
        p.drawText(QRectF(r.left() + 14, r.top() + 36, r.width() - 28, 20),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   f"{modele} · {self.n['taille']} px" + (" · découpage 2×2" if self.n["tuiles"] else ""))
        p.setPen(couleur("texte2"))
        p.setFont(police(T.taille - 1))
        texte = self.n["texte"].split(". ", 1)[-1]
        p.drawText(QRectF(r.left() + 14, r.top() + 58, r.width() - 28, r.height() - 64),
                   Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, texte)


class LigneReglage(QWidget):
    """Une ligne de l'éditeur : libellé, description, éditeur adapté au type, bouton de réinitialisation."""

    def __init__(self, page, r):
        super().__init__()
        self.page, self.r, self.cfg = page, r, page.cfg
        g = QGridLayout(self)
        g.setContentsMargins(4, 8, 4, 8)
        g.setHorizontalSpacing(16)
        g.setVerticalSpacing(2)
        lib = QLabel(r.libelle)
        lib.setStyleSheet("font-weight: 600;")
        g.addWidget(lib, 0, 0)
        if r.description:
            d = etiquette(r.description)
            g.addWidget(d, 1, 0)
        self.editeur = self._editeur()
        g.addWidget(self.editeur, 0, 1, 2, 1, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        self.b_reset = Bouton("", "fantome", "retour")
        self.b_reset.setToolTip(f"Revenir à la valeur par défaut ({self._texte_defaut()})")
        self.b_reset.clicked.connect(lambda: self.cfg.set(r.cle, r.defaut))
        g.addWidget(self.b_reset, 0, 2, 2, 1, Qt.AlignmentFlag.AlignVCenter)
        g.setColumnStretch(0, 1)
        self.actualiser()

    def _texte_defaut(self):
        r = self.r
        if r.type == "bool":
            return "activé" if r.defaut else "désactivé"
        if r.type == "choix":
            return dict(r.choix).get(r.defaut, r.defaut)
        if r.type == "mdp":
            return "vide"
        return f"{r.defaut}{r.suffixe}" if r.defaut != "" else "vide"

    def _editeur(self):
        r, cfg = self.r, self.cfg
        if r.type == "bool":
            w = Interrupteur()
            w.toggled.connect(lambda v: cfg.set(r.cle, v))
            return w
        if r.type == "choix":
            w = QComboBox()
            w.setMinimumWidth(210)
            for k, lib in r.choix:
                w.addItem(lib, k)
            w.currentIndexChanged.connect(lambda: cfg.set(r.cle, w.currentData()))
            return w
        if r.type in ("texte", "mdp"):
            w = QLineEdit()
            w.setMinimumWidth(260)
            if r.type == "mdp":
                w.setEchoMode(QLineEdit.EchoMode.Password)
            w.editingFinished.connect(lambda: cfg.set(r.cle, w.text()))
            return w
        if r.type == "couleur":
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            w.pastille = Pastille_couleur(cfg.get(r.cle))
            w.pastille.setChecked(True)
            w.pastille.clicked.connect(self._choisir_couleur)
            w.code = QLineEdit()
            w.code.setFixedWidth(100)
            w.code.editingFinished.connect(lambda: cfg.set(r.cle, w.code.text()))
            b = Bouton("Choisir…", "discret")
            b.clicked.connect(self._choisir_couleur)
            h.addWidget(w.pastille)
            h.addWidget(w.code)
            h.addWidget(b)
            return w
        # nombres : curseur + champ précis
        conteneur = QWidget()
        h = QHBoxLayout(conteneur)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)
        echelle = 1 if r.type == "int" else round(1 / (r.pas or 0.01))
        self._echelle = echelle
        s = QSlider(Qt.Orientation.Horizontal)
        s.setFixedWidth(170)
        s.setRange(int(round(r.min * echelle)), int(round(r.max * echelle)))
        s.setSingleStep(max(1, int(round((r.pas or 1) * echelle))))
        if r.type == "int":
            sp = QSpinBox()
            sp.setRange(int(r.min), int(r.max))
        else:
            sp = QDoubleSpinBox()
            sp.setRange(r.min, r.max)
            sp.setDecimals(2 if (r.pas or 0.01) < 0.1 else 1)
            sp.setSingleStep(r.pas or 0.01)
        sp.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        sp.setSuffix(r.suffixe)
        sp.setFixedWidth(96)
        sp.setAlignment(Qt.AlignmentFlag.AlignRight)
        s.valueChanged.connect(lambda v: sp.setValue(v / echelle if r.type != "int" else v))
        s.sliderReleased.connect(lambda: cfg.set(r.cle, sp.value()))
        s.valueChanged.connect(lambda v: (not s.isSliderDown()) and cfg.set(r.cle, v / echelle if r.type != "int" else v))
        sp.editingFinished.connect(lambda: cfg.set(r.cle, sp.value()))
        h.addWidget(s)
        h.addWidget(sp)
        conteneur.curseur, conteneur.champ = s, sp
        return conteneur

    def _choisir_couleur(self):
        c = QColorDialog.getColor(QColor(self.cfg.get(self.r.cle)), self, self.r.libelle)
        if c.isValid():
            self.cfg.set(self.r.cle, c.name())

    def actualiser(self):
        r, v, w = self.r, self.cfg.get(self.r.cle), self.editeur
        if r.type == "bool":
            if w.isChecked() != bool(v):
                w.regler(bool(v))
        elif r.type == "choix":
            w.blockSignals(True)
            w.setCurrentIndex(max(0, w.findData(v)))
            w.blockSignals(False)
        elif r.type in ("texte", "mdp"):
            if not w.hasFocus():
                w.setText(str(v))
        elif r.type == "couleur":
            w.pastille.hexa = v
            w.pastille.setChecked(True)
            w.pastille.update()
            if not w.code.hasFocus():
                w.code.setText(v)
        else:
            w.curseur.blockSignals(True)
            w.champ.blockSignals(True)
            w.curseur.setValue(int(round(v * (1 if r.type == "int" else self._echelle))))
            w.champ.setValue(v)
            w.curseur.blockSignals(False)
            w.champ.blockSignals(False)
        self.b_reset.setVisible(self.cfg.est_modifie(r.cle))


class PageReglages(QWidget):
    def __init__(self, fen):
        super().__init__()
        self.fen, self.cfg = fen, fen.cfg
        self.lignes = {}
        self.avance = False
        racine = QVBoxLayout(self)
        racine.setContentsMargins(0, 0, 0, 0)
        racine.setSpacing(12)
        haut = QHBoxLayout()
        t = QLabel("Réglages")
        t.setObjectName("titre_page")
        haut.addWidget(t)
        haut.addStretch(1)
        self.i_avance = Interrupteur()
        self.i_avance.toggled.connect(self._avance)
        haut.addWidget(QLabel("Réglages avancés"))
        haut.addWidget(self.i_avance)
        haut.addSpacing(12)
        for texte, f in (("Importer…", self.importer), ("Exporter…", self.exporter)):
            b = Bouton(texte, "discret")
            b.clicked.connect(f)
            haut.addWidget(b)
        b = Bouton("Tout réinitialiser", "danger")
        b.clicked.connect(self.tout_reinitialiser)
        haut.addWidget(b)
        racine.addLayout(haut)

        corps = QHBoxLayout()
        corps.setSpacing(18)
        gauche = QVBoxLayout()
        self.recherche = QLineEdit()
        self.recherche.setPlaceholderText("Rechercher un réglage…")
        self.recherche.textChanged.connect(self._construire_droite)
        gauche.addWidget(self.recherche)
        self.categories = QListWidget()
        self.categories.setFixedWidth(240)
        self._remplir_categories()
        self.categories.currentRowChanged.connect(lambda _: self._construire_droite())
        gauche.addWidget(self.categories, 1)
        corps.addLayout(gauche)
        self.defil = QScrollArea()
        self.defil.setWidgetResizable(True)
        corps.addWidget(self.defil, 1)
        racine.addLayout(corps, 1)
        self.categories.setCurrentRow(0)
        self.cfg.abonner(self._change)

    def _categories_visibles(self):
        dev = self.cfg.get("developpeur.actif")
        return [(c, l) for c, l in CATEGORIES if dev or c not in CATEGORIES_CACHEES]

    def _remplir_categories(self):
        actuelle = self.categories.currentItem().data(Qt.ItemDataRole.UserRole) if self.categories.currentItem() else None
        self.categories.blockSignals(True)
        self.categories.clear()
        for cle, lib in self._categories_visibles():
            it = QListWidgetItem(lib)
            it.setData(Qt.ItemDataRole.UserRole, cle)
            self.categories.addItem(it)
        self.categories.blockSignals(False)
        if actuelle:
            self.aller(actuelle)
            if self.categories.currentRow() < 0:
                self.categories.setCurrentRow(0)

    def _avance(self, v):
        self.avance = v
        self._construire_droite()

    def aller(self, categorie):
        for i in range(self.categories.count()):
            if self.categories.item(i).data(Qt.ItemDataRole.UserRole) == categorie:
                self.categories.setCurrentRow(i)

    def _construire_droite(self, *_):
        texte = self.recherche.text().strip().lower()
        it = self.categories.currentItem()
        cat = it.data(Qt.ItemDataRole.UserRole) if it else "apparence"
        contenu = QWidget()
        col = QVBoxLayout(contenu)
        col.setContentsMargins(4, 0, 16, 16)
        col.setSpacing(4)
        self.lignes = {}
        visibles = {c for c, _ in self._categories_visibles()}
        if texte:
            reglages = [r for r in SCHEMA if r.categorie in visibles and
                        texte in (r.libelle + " " + r.description + " " + r.cle).lower()]
            titre = QLabel(f"{len(reglages)} résultat(s) pour « {self.recherche.text().strip()} »")
            titre.setObjectName("titre")
            col.addWidget(titre)
        else:
            reglages = [r for r in SCHEMA if r.categorie == cat and (self.avance or not r.avance)]
            titre = QLabel(dict(CATEGORIES)[cat])
            titre.setObjectName("titre")
            col.addWidget(titre)
            entete = self._entete(cat)
            if entete is not None:
                col.addSpacing(8)
                col.addWidget(entete)
            caches = sum(1 for r in SCHEMA if r.categorie == cat and r.avance and not self.avance)
            if caches:
                col.addWidget(etiquette(f"{caches} réglage(s) avancé(s) masqué(s) — activez « Réglages avancés » en haut."))
        col.addSpacing(6)
        precedente = None
        for r in reglages:
            if texte and r.categorie != precedente:
                precedente = r.categorie
                col.addSpacing(8)
                col.addWidget(etiquette(dict(CATEGORIES)[r.categorie].upper(), "section"))
            elif not texte and r.groupe:
                col.addSpacing(14)
                col.addWidget(etiquette(r.groupe.upper(), "section"))
            ligne = LigneReglage(self, r)
            self.lignes[r.cle] = ligne
            col.addWidget(ligne)
            col.addWidget(separateur())
        col.addStretch(1)
        self.defil.setWidget(contenu)

    def _entete(self, cat):
        if cat == "apparence":
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(10)
            h = QHBoxLayout()
            self.tuiles = []
            for cle, lib in (("sombre", "Sombre"), ("clair", "Clair")):
                tu = TuileTheme(cle, lib)
                tu.setChecked(self.cfg.get("apparence.theme") == cle)
                tu.clicked.connect(lambda _=False, k=cle: self.cfg.set("apparence.theme", k))
                h.addWidget(tu)
                self.tuiles.append(tu)
            h.addStretch(1)
            v.addLayout(h)
            h2 = QHBoxLayout()
            h2.addWidget(QLabel("Bleu d'accent"))
            h2.addSpacing(8)
            self.pastilles = []
            for hexa in ACCENTS:
                pc = Pastille_couleur(hexa)
                pc.setChecked(self.cfg.get("apparence.accent").upper() == hexa.upper())
                pc.clicked.connect(lambda _=False, x=hexa: self.cfg.set("apparence.accent", x))
                h2.addWidget(pc)
                self.pastilles.append(pc)
            h2.addStretch(1)
            v.addLayout(h2)
            v.addWidget(etiquette("Les changements s'appliquent immédiatement à toute la fenêtre."))
            return w
        if cat == "detection":
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 0)
            g = QGridLayout()
            g.setSpacing(10)
            self.cartes = []
            for i, (cle, n) in enumerate(NIVEAUX.items()):
                c = CarteNiveau(cle, n)
                c.setChecked(self.cfg.get("detection.niveau") == cle)
                c.clicked.connect(lambda _=False, k=cle: self.cfg.set("detection.niveau", k))
                g.addWidget(c, i // 2, i % 2)
                self.cartes.append(c)
            v.addLayout(g)
            info = self.fen.info_appareil
            if info:
                txt = (f"Calcul : {info['nom']}" + (f" · {info.get('memoire_go')} Go" if info.get("memoire_go") else "")
                       + ("" if info.get("cuda") else " — sans carte NVIDIA détectée, préférez Rapide ou Équilibré. "
                          "Installez PyTorch avec CUDA pour utiliser votre carte graphique."))
                v.addWidget(etiquette(txt))
            h = QHBoxLayout()
            b = Bouton("Ouvrir le dossier des modèles", "discret", "dossier")
            b.clicked.connect(lambda: (os.makedirs(DOSSIER_MODELES, exist_ok=True),
                                       QDesktopServices.openUrl(QUrl.fromLocalFile(DOSSIER_MODELES))))
            h.addWidget(b)
            h.addStretch(1)
            v.addLayout(h)
            v.addWidget(etiquette("Les modèles se téléchargent automatiquement à la première utilisation d'un niveau. "
                                  "Vous pouvez aussi déposer vos propres modèles (.pt, .onnx, .engine) dans ce dossier "
                                  "et les choisir avec le niveau Personnalisé."))
            return w
        if cat == "notifications":
            from .entetes_reglages import entete_notifications
            return entete_notifications(self)
        if cat == "clips":
            from .entetes_reglages import entete_clips
            return entete_clips(page=self)
        if cat == "maj":
            from .entetes_reglages import entete_maj
            return entete_maj(self)
        if cat == "developpeur":
            from .entetes_reglages import entete_developpeur
            return entete_developpeur(self)
        return None

    def _change(self, cle, _v):
        ligne = self.lignes.get(cle)
        if ligne is not None:
            ligne.actualiser()
        if cle == "apparence.theme":
            for tu in getattr(self, "tuiles", []):
                tu.setChecked(tu.cle == _v)
        if cle == "apparence.accent":
            for pc in getattr(self, "pastilles", []):
                pc.setChecked(pc.hexa.upper() == str(_v).upper())
        if cle == "detection.niveau":
            for c in getattr(self, "cartes", []):
                c.setChecked(c.cle == _v)
        if cle == "developpeur.actif":
            self._remplir_categories()

    def importer(self):
        chemin, _ = QFileDialog.getOpenFileName(self, "Importer des réglages", "", "Réglages Flux (*.json)")
        if chemin:
            try:
                n = self.cfg.importer_fichier(chemin)
                self.fen.appliquer_apparence()
                self._construire_droite()
                self.fen.toast(f"{n} réglage(s) importé(s).", "ok")
            except Exception as e:  # noqa: BLE001
                self.fen.toast(f"Fichier illisible : {e}", "erreur")

    def exporter(self):
        chemin, _ = QFileDialog.getSaveFileName(self, "Exporter les réglages", "reglages_flux.json", "JSON (*.json)")
        if chemin:
            import json
            d = self.cfg.exporter_dict(pour_partage=True)
            d.pop("flux", None)
            d.pop("fenetre", None)
            with open(chemin, "w", encoding="utf-8") as f:
                json.dump(d, f, indent=2, ensure_ascii=False)
            self.fen.toast("Réglages exportés (sans mots de passe ni jetons).", "ok")

    def tout_reinitialiser(self):
        if QMessageBox.question(self, "Tout réinitialiser", "Remettre tous les réglages à leur valeur par défaut ? "
                                                              "Vos caméras et la base de données sont conservées.") \
                != QMessageBox.StandardButton.Yes:
            return
        self.cfg.reinitialiser()
        self.fen.appliquer_apparence()
        self._construire_droite()
        self.fen.toast("Réglages réinitialisés.", "ok")
