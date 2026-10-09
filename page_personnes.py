"""Page Personnes : la base des visages reconnus, leurs fiches et l'historique de leurs actions."""

import time

import cv2
import numpy as np
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QInputDialog,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit,
                               QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from . import vision
from .base import CATEGORIES_PERSONNE, TYPES_ACTION, depuis_jpeg
from .theme import C, T, couleur, police
from .widgets import Bouton, etiquette, separateur

NOMS_CATEGORIES = dict(CATEGORIES_PERSONNE)
TEINTES_CATEGORIES = {"connu": "succes", "inconnu": "attention", "surveille": "danger", "liste_noire": "liste_noire"}


def date_relative(ts):
    if not ts:
        return "jamais"
    d = time.time() - ts
    if d < 60:
        return "à l'instant"
    if d < 3600:
        return f"il y a {int(d // 60)} min"
    if d < 86400:
        return f"il y a {int(d // 3600)} h"
    return time.strftime("%d/%m/%Y %H:%M", time.localtime(ts))


def pixmap_jpeg(octets, cote, rond=False):
    img = depuis_jpeg(octets)
    pix = QPixmap(cote, cote)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    chemin = QPainterPath()
    if rond:
        chemin.addEllipse(0, 0, cote, cote)
    else:
        chemin.addRoundedRect(0, 0, cote, cote, T.rayon, T.rayon)
    p.setClipPath(chemin)
    if img is None:
        p.fillPath(chemin, couleur("surface2"))
        p.setPen(couleur("texte3"))
        p.setFont(police(cote // 3, True))
        p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "?")
    else:
        h, w = img.shape[:2]
        s = min(h, w)
        carre = np.ascontiguousarray(img[(h - s) // 2:(h - s) // 2 + s, (w - s) // 2:(w - s) // 2 + s])
        q = QImage(carre.data, s, s, carre.strides[0], QImage.Format.Format_BGR888)
        p.drawImage(pix.rect(), q)
    p.end()
    return pix


class PagePersonnes(QWidget):
    def __init__(self, fen):
        super().__init__()
        self.fen, self.base, self.cfg = fen, fen.base, fen.cfg
        self.pid = None
        self._version_vue = -1
        self._construire()

    def _construire(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        haut = QHBoxLayout()
        t = QLabel("Personnes")
        t.setObjectName("titre_page")
        haut.addWidget(t)
        self.lbl_stats = QLabel("")
        self.lbl_stats.setObjectName("soustitre")
        haut.addSpacing(12)
        haut.addWidget(self.lbl_stats)
        haut.addStretch(1)
        b_nouv = Bouton("Ajouter depuis une photo", "primaire", "plus")
        b_nouv.clicked.connect(self.nouvelle_depuis_photo)
        haut.addWidget(b_nouv)
        v.addLayout(haut)

        sep = QSplitter(Qt.Orientation.Horizontal)
        sep.setChildrenCollapsible(False)
        sep.setHandleWidth(14)
        # liste
        g = QWidget()
        gl = QVBoxLayout(g)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(8)
        self.recherche = QLineEdit()
        self.recherche.setPlaceholderText("Rechercher un nom ou une note…")
        self.recherche.textChanged.connect(lambda: self.rafraichir(force=True))
        gl.addWidget(self.recherche)
        self.filtre = QComboBox()
        self.filtre.addItem("Toutes les personnes", None)
        for k, lib in CATEGORIES_PERSONNE:
            self.filtre.addItem({"connu": "Connues", "inconnu": "Inconnues", "surveille": "Surveillées", "liste_noire": "Liste noire"}[k], k)
        self.filtre.currentIndexChanged.connect(lambda: self.rafraichir(force=True))
        gl.addWidget(self.filtre)
        self.liste = QListWidget()
        self.liste.setIconSize(QSize(44, 44))
        self.liste.currentItemChanged.connect(self._selection)
        self.liste.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.liste.customContextMenuRequested.connect(self._menu_liste)
        gl.addWidget(self.liste, 1)
        g.setMinimumWidth(270)
        sep.addWidget(g)

        # fiche
        self.pile = QStackedWidget()
        vide = QWidget()
        vl = QVBoxLayout(vide)
        vl.addStretch(1)
        lv = QLabel("Sélectionnez une personne")
        lv.setObjectName("grand")
        lv.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vl.addWidget(lv)
        lv2 = etiquette("Les visages vus par les caméras apparaissent ici automatiquement (« Inconnu 1 », « Inconnu 2 »…). "
                        "Renommez-les pour qu'ils soient reconnus par leur nom, ou fusionnez deux fiches de la même "
                        "personne.", "soustitre")
        lv2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vl.addWidget(lv2)
        vl.addStretch(2)
        self.pile.addWidget(vide)
        self.fiche = self._fiche()
        self.pile.addWidget(self.fiche)
        sep.addWidget(self.pile)
        sep.setStretchFactor(1, 1)
        sep.setSizes([300, 900])
        v.addWidget(sep, 1)

    def _fiche(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        haut = QHBoxLayout()
        haut.setSpacing(16)
        self.photo = QLabel()
        self.photo.setFixedSize(112, 112)
        haut.addWidget(self.photo, 0, Qt.AlignmentFlag.AlignTop)
        infos = QVBoxLayout()
        infos.setSpacing(8)
        self.nom = QLineEdit()
        self.nom.setPlaceholderText("Nom")
        self.nom.setStyleSheet(f"font-size: {T.taille + 6}px; font-weight: 600;")
        self.nom.editingFinished.connect(self._enregistrer)
        infos.addWidget(self.nom)
        lig = QHBoxLayout()
        self.categorie = QComboBox()
        for k, lib in CATEGORIES_PERSONNE:
            self.categorie.addItem(lib, k)
        self.categorie.setToolTip("Surveillée : peut déclencher une alerte dédiée (Réglages › Alertes).\n"
                                  "Liste noire : alerte prioritaire immédiate, par mail et notification.")
        self.categorie.currentIndexChanged.connect(self._enregistrer)
        lig.addWidget(self.categorie)
        self.lbl_meta = QLabel("")
        self.lbl_meta.setObjectName("soustitre")
        lig.addWidget(self.lbl_meta, 1)
        infos.addLayout(lig)
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Notes (rôle, véhicule habituel, horaires…)")
        self.notes.setMaximumHeight(70)
        self._minuteur_notes = QTimer(self)
        self._minuteur_notes.setSingleShot(True)
        self._minuteur_notes.setInterval(700)
        self._minuteur_notes.timeout.connect(self._enregistrer)
        self.notes.textChanged.connect(self._minuteur_notes.start)
        infos.addWidget(self.notes)
        haut.addLayout(infos, 1)
        boutons = QVBoxLayout()
        b1 = Bouton("Ajouter une photo", "discret", "capture")
        b1.clicked.connect(self.ajouter_photo)
        b2 = Bouton("Fusionner avec…", "discret", "personnes")
        b2.clicked.connect(self.fusionner)
        b3 = Bouton("Supprimer", "danger")
        b3.clicked.connect(self.supprimer)
        for b in (b1, b2, b3):
            boutons.addWidget(b)
        boutons.addStretch(1)
        haut.addLayout(boutons)
        v.addLayout(haut)
        v.addWidget(separateur())
        v.addWidget(etiquette("VISAGES MÉMORISÉS", "section"))
        self.visages = QListWidget()
        self.visages.setViewMode(QListWidget.ViewMode.IconMode)
        self.visages.setIconSize(QSize(72, 72))
        self.visages.setFixedHeight(104)
        self.visages.setFlow(QListWidget.Flow.LeftToRight)
        self.visages.setWrapping(False)
        self.visages.setMovement(QListWidget.Movement.Static)
        self.visages.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.visages.customContextMenuRequested.connect(self._menu_visage)
        self.visages.setToolTip("Clic droit pour retirer un visage mal attribué")
        v.addWidget(self.visages)
        v.addWidget(etiquette("HISTORIQUE DES ACTIONS", "section"))
        bas = QHBoxLayout()
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Date", "Caméra", "Action", "Détail"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._apercu_action)
        bas.addWidget(self.table, 1)
        self.apercu = QLabel()
        self.apercu.setFixedSize(220, 220)
        self.apercu.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.apercu.setObjectName("soustitre")
        self.apercu.setText("Photo de l'action")
        bas.addWidget(self.apercu, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(bas, 1)
        return w

    # --- liste -------------------------------------------------------------------------
    def rafraichir(self, force=False):
        if not force and self.base.version == self._version_vue:
            return
        self._version_vue = self.base.version
        s = self.base.statistiques()
        self.lbl_stats.setText(f"{s['personnes']} personnes · {s['visages']} visages · {s['actions']} actions")
        courant = self.pid
        self.liste.blockSignals(True)
        self.liste.clear()
        for p in self.base.personnes(self.recherche.text().strip(), self.filtre.currentData()):
            it = QListWidgetItem(QIcon(pixmap_jpeg(p["miniature"], 44, rond=True)),
                                 f"{p['nom']}\n{NOMS_CATEGORIES.get(p['categorie'], '')} · vu {date_relative(p['vu_dernier'])}")
            it.setData(Qt.ItemDataRole.UserRole, p["id"])
            it.setForeground(QColor(C["texte"]))
            it.setSizeHint(QSize(0, 56))
            self.liste.addItem(it)
            if p["id"] == courant:
                self.liste.setCurrentItem(it)
        self.liste.blockSignals(False)
        if courant is not None and self.base.personne(courant):
            self.afficher(courant)
        else:
            self.pid = None
            self.pile.setCurrentIndex(0)

    def _selection(self, it, _=None):
        if it is not None:
            self.afficher(it.data(Qt.ItemDataRole.UserRole))

    def afficher(self, pid):
        p = self.base.personne(pid)
        if p is None:
            return
        self.pid = pid
        self.pile.setCurrentIndex(1)
        for w in (self.nom, self.categorie, self.notes):
            w.blockSignals(True)
        self.nom.setText(p["nom"])
        self.categorie.setCurrentIndex(self.categorie.findData(p["categorie"]))
        if self.notes.toPlainText() != p["notes"]:
            self.notes.setPlainText(p["notes"])
        for w in (self.nom, self.categorie, self.notes):
            w.blockSignals(False)
        self.photo.setPixmap(pixmap_jpeg(p["miniature"], 112))
        self.lbl_meta.setText(f"Créée le {time.strftime('%d/%m/%Y', time.localtime(p['cree']))} · "
                              f"{p['passages']} passage(s) · vue {date_relative(p['vu_dernier'])}")
        self.visages.clear()
        for f in self.base.visages(pid):
            it = QListWidgetItem(QIcon(pixmap_jpeg(f["miniature"], 72)), "")
            it.setData(Qt.ItemDataRole.UserRole, f["id"])
            it.setToolTip(f"Source : {f['source']} · {time.strftime('%d/%m/%Y %H:%M', time.localtime(f['cree']))}")
            self.visages.addItem(it)
        actions = self.base.actions(personne_id=pid, limite=300)
        self.table.setRowCount(len(actions))
        for i, a in enumerate(actions):
            valeurs = [time.strftime("%d/%m %H:%M:%S", time.localtime(a["ts"])), a["camera"],
                       TYPES_ACTION.get(a["type"], a["type"]), a["detail"]]
            for j, val in enumerate(valeurs):
                it = QTableWidgetItem(val)
                it.setData(Qt.ItemDataRole.UserRole, a["id"])
                self.table.setItem(i, j, it)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.apercu.setPixmap(QPixmap())
        self.apercu.setText("Photo de l'action")

    def _apercu_action(self):
        items = self.table.selectedItems()
        if not items:
            return
        octets = self.base.miniature_action(items[0].data(Qt.ItemDataRole.UserRole))
        img = depuis_jpeg(octets)
        if img is None:
            self.apercu.setPixmap(QPixmap())
            self.apercu.setText("Pas de photo")
            return
        h, w = img.shape[:2]
        img = np.ascontiguousarray(img)
        pix = QPixmap.fromImage(QImage(img.data, w, h, img.strides[0], QImage.Format.Format_BGR888).copy())
        self.apercu.setPixmap(pix.scaled(220, 220, Qt.AspectRatioMode.KeepAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation))

    # --- édition -----------------------------------------------------------------------------
    def _enregistrer(self):
        if self.pid is None:
            return
        nom = self.nom.text().strip() or "Sans nom"
        cat = self.categorie.currentData()
        if cat == "inconnu" and not nom.startswith("Inconnu"):
            cat = "connu"  # une personne nommée devient « connue »
            self.categorie.blockSignals(True)
            self.categorie.setCurrentIndex(self.categorie.findData("connu"))
            self.categorie.blockSignals(False)
        self.base.modifier_personne(self.pid, nom=nom, categorie=cat, notes=self.notes.toPlainText())

    def _menu_liste(self, pos):
        it = self.liste.itemAt(pos)
        if it is None:
            return
        self.liste.setCurrentItem(it)
        m = QMenu(self)
        m.addAction("Fusionner avec…", self.fusionner)
        m.addAction("Supprimer", self.supprimer)
        m.exec(self.liste.mapToGlobal(pos))

    def _menu_visage(self, pos):
        it = self.visages.itemAt(pos)
        if it is None:
            return
        m = QMenu(self)
        m.addAction("Retirer ce visage", lambda: (self.base.supprimer_visage(it.data(Qt.ItemDataRole.UserRole)),
                                                  self.rafraichir(force=True)))
        m.exec(self.visages.mapToGlobal(pos))

    def fusionner(self):
        if self.pid is None:
            return
        autres = [p for p in self.base.personnes() if p["id"] != self.pid]
        if not autres:
            self.fen.toast("Aucune autre personne avec qui fusionner.")
            return
        noms = [f"{p['nom']}  (#{p['id']})" for p in autres]
        choix, ok = QInputDialog.getItem(self, "Fusionner", f"« {self.nom.text()} » est en fait :", noms, 0, False)
        if not ok:
            return
        cible = autres[noms.index(choix)]["id"]
        self.base.fusionner(self.pid, cible)
        self.pid = cible
        self.fen.toast("Fiches fusionnées : les visages et l'historique sont regroupés.", "ok")
        self.rafraichir(force=True)

    def supprimer(self):
        if self.pid is None:
            return
        if QMessageBox.question(self, "Supprimer", f"Supprimer « {self.nom.text()} » et ses visages ? "
                                                   "L'historique est conservé sans nom.") != QMessageBox.StandardButton.Yes:
            return
        self.base.supprimer_personne(self.pid)
        self.pid = None
        self.rafraichir(force=True)

    # --- photos -----------------------------------------------------------------------------
    def _visages_photo(self, chemin):
        img = cv2.imdecode(np.fromfile(chemin, dtype=np.uint8), cv2.IMREAD_COLOR)  # chemins accentués sous Windows
        if img is None:
            raise ValueError("Image illisible.")
        h, w = img.shape[:2]
        det = cv2.FaceDetectorYN.create(vision.fichier_visage("yunet"), "", (w, h), 0.7, 0.3, 5000)
        _, res = det.detect(img)
        if res is None or not len(res):
            raise ValueError("Aucun visage trouvé sur cette photo.")
        reco, verrou = vision.obtenir_reconnaisseur()
        r = max(res, key=lambda x: x[2] * x[3])  # le plus grand visage
        with verrou:
            aligne = reco.alignCrop(img, r)
            emp = reco.feature(aligne)
        return emp, aligne, len(res)

    def _choisir_photo(self):
        chemin, _ = QFileDialog.getOpenFileName(self, "Choisir une photo", "", "Images (*.jpg *.jpeg *.png *.bmp *.webp)")
        return chemin

    def nouvelle_depuis_photo(self, chemin=None, nom=None):
        chemin = chemin or self._choisir_photo()
        if not chemin:
            return None
        try:
            emp, mini, n = self._visages_photo(chemin)
        except Exception as e:  # noqa: BLE001
            self.fen.toast(f"Impossible d'ajouter : {e}", "erreur")
            return None
        if nom is None:
            nom, ok = QInputDialog.getText(self, "Nouvelle personne", "Nom :")
            if not ok or not nom.strip():
                return None
        pid = self.base.creer_personne(nom.strip(), "connu", mini)
        self.base.ajouter_visage(pid, emp, mini, source="photo")
        self.pid = pid
        self.rafraichir(force=True)
        self.fen.toast(f"{nom.strip()} ajouté(e)" + (" (le plus grand des visages de la photo a été pris)" if n > 1 else ""),
                       "ok")
        return pid

    def ajouter_photo(self, chemin=None):
        if self.pid is None:
            return
        chemin = chemin or self._choisir_photo()
        if not chemin:
            return
        try:
            emp, mini, _ = self._visages_photo(chemin)
        except Exception as e:  # noqa: BLE001
            self.fen.toast(f"Impossible d'ajouter : {e}", "erreur")
            return
        if self.base.ajouter_visage(self.pid, emp, mini, self.cfg.get("visages.max_par_personne"), "photo") is None:
            self.fen.toast("Nombre maximal de visages atteint pour cette personne (Réglages › Visages).", "erreur")
        self.rafraichir(force=True)
