"""Page Journal : actions enregistrées dans la base, réparties en catégories (prédéfinies ou créées par
l'utilisateur), filtres, photos, export CSV, et événements en direct."""

import html
import os
import time

import numpy as np
from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QImage, QPainter, QPixmap, QTextCursor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QDialog, QFileDialog,
                               QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget,
                               QLayout, QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QStackedWidget,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .base import CATEGORIES_PERSONNE, TYPES_ACTION, Base, correspond, depuis_jpeg
from .theme import C
from .widgets import Bouton, Interrupteur, Pastille, etiquette

COULEURS_CATEGORIES = ["#E0245E", "#F2554A", "#F5A524", "#FBBF24", "#2BD07A", "#22D3EE", "#2F7BFF", "#8B5CF6",
                       "#EC4899", "#94A3B8"]
LIMITE_CALCUL = 20000  # actions examinées pour les compteurs des catégories


class FlowLayout(QLayout):
    """Disposition qui passe à la ligne quand la place manque (pastilles des catégories)."""

    def __init__(self, parent=None, espace=8):
        super().__init__(parent)
        self._items, self._espace = [], espace
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, largeur):
        return self._placer(QRect(0, 0, largeur, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._placer(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        return s

    def _placer(self, rect, simulation):
        x, y, haut_ligne = rect.x(), rect.y(), 0
        for it in self._items:
            t = it.sizeHint()
            if x + t.width() > rect.right() + 1 and haut_ligne > 0:
                x, y, haut_ligne = rect.x(), y + haut_ligne + self._espace, 0
            if not simulation:
                it.setGeometry(QRect(QPoint(x, y), t))
            x += t.width() + self._espace
            haut_ligne = max(haut_ligne, t.height())
        return y + haut_ligne - rect.y()


def icone_couleur(hexa, taille=14):
    pix = QPixmap(taille, taille)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(hexa))
    p.drawEllipse(1, 1, taille - 2, taille - 2)
    p.end()
    return QIcon(pix)

PERIODES = [("Aujourd'hui", 1), ("7 derniers jours", 7), ("30 derniers jours", 30), ("Tout", 0)]


class PageJournal(QWidget):
    def __init__(self, fen):
        super().__init__()
        self.fen, self.base = fen, fen.base
        self.lignes = []  # journal texte (aussi envoyé par mail)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        haut = QHBoxLayout()
        t = QLabel("Journal")
        t.setObjectName("titre_page")
        haut.addWidget(t)
        haut.addSpacing(16)
        self.o_actions = Pastille("Actions", "accent")
        self.o_evts = Pastille("Événements en direct", "accent")
        self.o_actions.regler(True)
        self.o_actions.clicked.connect(lambda: self._vue(0))
        self.o_evts.clicked.connect(lambda: self._vue(1))
        haut.addWidget(self.o_actions)
        haut.addWidget(self.o_evts)
        haut.addStretch(1)
        b_mail = Bouton("Envoyer le journal par mail", "discret")
        b_mail.clicked.connect(lambda: self.fen.envoyer_journal(auto=False))
        haut.addWidget(b_mail)
        v.addLayout(haut)
        self.pile = QStackedWidget()
        self.pile.addWidget(self._vue_actions())
        self.texte = QPlainTextEdit()
        self.texte.setReadOnly(True)
        self.texte.document().setMaximumBlockCount(3000)
        self.texte.setStyleSheet('font-family: "Cascadia Mono", "Consolas", "DejaVu Sans Mono", monospace;')
        self.pile.addWidget(self.texte)
        v.addWidget(self.pile, 1)
        self._minuteur = QTimer(self)
        self._minuteur.setSingleShot(True)
        self._minuteur.setInterval(300)
        self._minuteur.timeout.connect(self.rafraichir)

    def _vue(self, i):
        self.pile.setCurrentIndex(i)
        self.o_actions.regler(i == 0)
        self.o_evts.regler(i == 1)
        if i == 0:
            self.rafraichir()

    def _vue_actions(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        f = QHBoxLayout()
        self.f_texte = QLineEdit()
        self.f_texte.setPlaceholderText("Rechercher (nom, plaque, détail…)")
        self.f_camera = QComboBox()
        self.f_type = QComboBox()
        self.f_type.addItem("Toutes les actions", None)
        for k, lib in TYPES_ACTION.items():
            self.f_type.addItem(lib, k)
        self.f_periode = QComboBox()
        for lib, j in PERIODES:
            self.f_periode.addItem(lib, j)
        self.f_periode.setCurrentIndex(1)
        f.addWidget(self.f_texte, 2)
        f.addWidget(self.f_camera, 1)
        f.addWidget(self.f_type, 1)
        f.addWidget(self.f_periode, 1)
        b_csv = Bouton("Exporter en CSV", "discret")
        b_csv.clicked.connect(self.exporter)
        f.addWidget(b_csv)
        v.addLayout(f)
        # Barre des catégories : « Toutes » + chaque catégorie avec son nombre d'actions
        barre = QHBoxLayout()
        barre.setSpacing(8)
        self.zone_cats = QWidget()
        self.flow_cats = FlowLayout(self.zone_cats)
        barre.addWidget(self.zone_cats, 1)
        b_cats = Bouton("Catégories…", "discret")
        b_cats.setToolTip("Créer, modifier et ordonner les catégories du journal")
        b_cats.clicked.connect(lambda: self.gerer_categories())
        barre.addWidget(b_cats, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(barre)
        self.categorie_choisie = None  # None = toutes
        self.pastilles_cats = {}
        self.f_texte.textChanged.connect(lambda: self._minuteur.start())
        for c in (self.f_camera, self.f_type, self.f_periode):
            c.currentIndexChanged.connect(lambda *_: self._minuteur.start())
        corps = QHBoxLayout()
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Date", "Caméra", "Personne", "Action", "Catégorie", "Détail"])
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.itemSelectionChanged.connect(self._apercu)
        self.table.cellDoubleClicked.connect(self._ouvrir_personne)
        corps.addWidget(self.table, 1)
        droite = QVBoxLayout()
        self.apercu = QLabel("Sélectionnez une action pour voir sa photo")
        self.apercu.setObjectName("soustitre")
        self.apercu.setWordWrap(True)
        self.apercu.setFixedSize(260, 260)
        self.apercu.setAlignment(Qt.AlignmentFlag.AlignCenter)
        droite.addWidget(self.apercu)
        self.lbl_compte = QLabel("")
        self.lbl_compte.setObjectName("soustitre")
        droite.addWidget(self.lbl_compte)
        droite.addStretch(1)
        corps.addLayout(droite)
        v.addLayout(corps, 1)
        return w

    def _filtres(self):
        j = self.f_periode.currentData()
        return {"camera": self.f_camera.currentData(), "type_": self.f_type.currentData(),
                "texte": self.f_texte.text().strip(), "depuis": time.time() - j * 86400 if j else None}

    def rafraichir(self):
        cam = self.f_camera.currentData()
        self.f_camera.blockSignals(True)
        self.f_camera.clear()
        self.f_camera.addItem("Toutes les caméras", None)
        for c in self.base.cameras():
            self.f_camera.addItem(c, c)
        self.f_camera.setCurrentIndex(max(0, self.f_camera.findData(cam)))
        self.f_camera.blockSignals(False)
        self.cats = self.base.categories_journal()
        par_id = {c["id"]: c for c in self.cats}
        if self.categorie_choisie is not None and self.categorie_choisie not in par_id:
            self.categorie_choisie = None
        toutes = self.base.actions(limite=LIMITE_CALCUL, **self._filtres())
        comptes = {c["id"]: 0 for c in self.cats}
        for a in toutes:
            a["cats"] = [i for i in Base.classer(a, self.cats) if i in par_id]
            for i in a["cats"]:
                comptes[i] += 1
        self._barre_categories(len(toutes), comptes)
        actions = toutes if self.categorie_choisie is None else [a for a in toutes if self.categorie_choisie in a["cats"]]
        self.actions_affichees = actions
        affichees = actions[:2000]
        self.table.setRowCount(len(affichees))
        for i, a in enumerate(affichees):
            noms = [par_id[c]["nom"] for c in a["cats"]]
            vals = [time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(a["ts"])), a["camera"], a["personne"] or "—",
                    TYPES_ACTION.get(a["type"], a["type"]), ", ".join(noms) + (" ✎" if a.get("categorie_id") else ""),
                    a["detail"]]
            for j, val in enumerate(vals):
                it = QTableWidgetItem(val)
                it.setData(Qt.ItemDataRole.UserRole, (a["id"], a["personne_id"]))
                if j == 4 and a["cats"]:
                    it.setIcon(icone_couleur(par_id[a["cats"][0]]["couleur"]))
                    if a.get("categorie_id"):
                        it.setToolTip("Classée à la main (clic droit › Classement automatique pour annuler)")
                if a["type"] == "liste_noire" or a.get("categorie_personne") == "liste_noire":
                    it.setForeground(QColor(C["liste_noire"]))
                self.table.setItem(i, j, it)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        txt = f"{len(actions)} action(s)"
        if len(actions) > 2000:
            txt += " (2 000 plus récentes affichées)"
        if len(toutes) >= LIMITE_CALCUL:
            txt += f"\nCompteurs calculés sur les {LIMITE_CALCUL:,} plus récentes".replace(",", " ")
        self.lbl_compte.setText(txt)

    def _barre_categories(self, total, comptes):
        while self.flow_cats.count():
            it = self.flow_cats.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        h = self.flow_cats
        self.pastilles_cats = {}
        entrees = [(None, f"Toutes · {total}", "accent")] + [
            (c["id"], f"{c['nom']} · {comptes.get(c['id'], 0)}" + ("  🔔" if c["notifier"] else ""), c["couleur"])
            for c in self.cats]
        for cid, texte, teinte in entrees:
            pa = Pastille(texte, teinte)
            pa.point_colore = cid is not None
            pa.regler(cid == self.categorie_choisie)
            pa.clicked.connect(lambda _=False, k=cid: self._choisir_categorie(k))
            if cid is not None:
                pa.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                pa.customContextMenuRequested.connect(lambda _pos, k=cid: self.gerer_categories(k))
                pa.setToolTip("Clic droit : modifier cette catégorie")
            h.addWidget(pa)
            self.pastilles_cats[cid] = pa
        self.zone_cats.updateGeometry()

    def _choisir_categorie(self, cid):
        self.categorie_choisie = cid
        self.rafraichir()

    def _menu(self, pos):
        lignes = sorted({i.row() for i in self.table.selectedItems()})
        it = self.table.itemAt(pos)
        if it is not None and it.row() not in lignes:
            self.table.selectRow(it.row())
            lignes = [it.row()]
        if not lignes:
            return
        ids = [self.table.item(r, 0).data(Qt.ItemDataRole.UserRole)[0] for r in lignes]
        m = QMenu(self)
        classer = m.addMenu("Classer dans" + (f" ({len(ids)} actions)" if len(ids) > 1 else ""))
        for c in self.cats:
            a = QAction(icone_couleur(c["couleur"]), c["nom"], classer)
            a.triggered.connect(lambda _=False, k=c["id"]: self._classer(ids, k))
            classer.addAction(a)
        classer.addSeparator()
        nouvelle = classer.addAction("Nouvelle catégorie…")
        nouvelle.triggered.connect(lambda: self._classer_nouvelle(ids))
        auto = m.addAction("Classement automatique")
        auto.setToolTip("Retire le classement manuel : les règles des catégories s'appliquent de nouveau")
        auto.triggered.connect(lambda: self._classer(ids, None))
        if len(ids) == 1 and self.table.item(lignes[0], 3).text() == TYPES_ACTION["video"]:
            m.addSeparator()
            m.addAction("Ouvrir la vidéo").triggered.connect(lambda: self._ouvrir_video(lignes[0]))
        pid = self.table.item(lignes[0], 0).data(Qt.ItemDataRole.UserRole)[1]
        if pid and len(ids) == 1:
            m.addSeparator()
            m.addAction("Ouvrir la fiche de la personne").triggered.connect(lambda: self._ouvrir_personne(lignes[0], 0))
        m.exec(self.table.viewport().mapToGlobal(pos))

    def _classer(self, ids, cid):
        for aid in ids:
            self.base.classer_action(aid, cid)
        self.rafraichir()

    def _classer_nouvelle(self, ids):
        nom, ok = QInputDialog.getText(self, "Nouvelle catégorie", "Nom de la catégorie :")
        if ok and nom.strip():
            couleur = COULEURS_CATEGORIES[len(self.cats) % len(COULEURS_CATEGORIES)]
            cid = self.base.enregistrer_categorie(nom.strip(), couleur)
            self._classer(ids, cid)
            self.fen.toast(f"Catégorie « {nom.strip()} » créée.", "ok")

    def gerer_categories(self, cid=None):
        DialogueCategories(self.fen, cid).exec()
        self.fen.categories_changees()
        self.rafraichir()

    def _apercu(self):
        items = self.table.selectedItems()
        if not items:
            return
        img = depuis_jpeg(self.base.miniature_action(items[0].data(Qt.ItemDataRole.UserRole)[0]))
        if img is None:
            self.apercu.setPixmap(QPixmap())
            self.apercu.setText("Pas de photo pour cette action")
            return
        img = np.ascontiguousarray(img)
        h, w = img.shape[:2]
        pix = QPixmap.fromImage(QImage(img.data, w, h, img.strides[0], QImage.Format.Format_BGR888).copy())
        self.apercu.setPixmap(pix.scaled(260, 260, Qt.AspectRatioMode.KeepAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation))

    def _chemin_video(self, ligne):
        import re
        it = self.table.item(ligne, 5)
        m = re.search(r"(video_\S+\.mp4)", it.text()) if it else None
        if not m:
            return None
        chemin = os.path.join(self.fen.cfg.dossier_sortie(), "videos", m.group(1))
        return chemin if os.path.isfile(chemin) else None

    def _ouvrir_video(self, ligne):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        chemin = self._chemin_video(ligne)
        if chemin:
            QDesktopServices.openUrl(QUrl.fromLocalFile(chemin))
        else:
            self.fen.toast("Vidéo introuvable (supprimée ou dossier déplacé).", "erreur")

    def _ouvrir_personne(self, ligne, _col):
        it3 = self.table.item(ligne, 3)
        if it3 is not None and it3.text() == TYPES_ACTION["video"]:
            self._ouvrir_video(ligne)
            return
        it = self.table.item(ligne, 0)
        pid = it.data(Qt.ItemDataRole.UserRole)[1] if it else None
        if pid:
            self.fen.aller("personnes")
            self.fen.page_personnes.pid = pid
            self.fen.page_personnes.rafraichir(force=True)

    def exporter(self):
        chemin, _ = QFileDialog.getSaveFileName(self, "Exporter les actions", os.path.join(
            self.fen.cfg.dossier_sortie(), f"actions_{time.strftime('%Y%m%d')}.csv"), "CSV (*.csv)")
        if chemin:
            n = self.base.exporter_csv(chemin, lignes=getattr(self, "actions_affichees", None), **self._filtres())
            self.fen.toast(f"{n} action(s) exportée(s) : {os.path.basename(chemin)}", "ok")

    # --- événements en direct ------------------------------------------------------------
    def ajouter(self, heure, source, texte, niveau):
        teinte = {"alerte": C["danger"], "erreur": C["danger"], "ok": C["succes"], "action": C["accent_vif"],
                  "video": "#EC4899"}.get(
            niveau, C["texte"])
        self.texte.appendHtml(f'<span style="color:{C["texte3"]}">{heure}</span> '
                              f'<span style="color:{C["accent_vif"]}">{html.escape(source)}</span> '
                              f'<span style="color:{teinte}">{html.escape(texte)}</span>')
        self.texte.moveCursor(QTextCursor.MoveOperation.End)


class DialogueCategories(QDialog):
    """Gestion des catégories du journal : nom, couleur, règles de classement automatique, notification."""

    def __init__(self, fen, cid=None):
        super().__init__(fen)
        self.fen, self.base = fen, fen.base
        self.setWindowTitle("Catégories du journal")
        self.resize(860, 600)
        self._charge = False
        self._minuteur = QTimer(self)
        self._minuteur.setSingleShot(True)
        self._minuteur.setInterval(350)
        self._minuteur.timeout.connect(self._enregistrer)
        racine = QHBoxLayout(self)
        racine.setContentsMargins(20, 20, 20, 16)
        racine.setSpacing(18)

        gauche = QVBoxLayout()
        self.liste = QListWidget()
        self.liste.setFixedWidth(250)
        self.liste.currentRowChanged.connect(self._afficher)
        gauche.addWidget(self.liste, 1)
        h = QHBoxLayout()
        for texte, f, tip in (("↑", lambda: self._deplacer(-1), "Monter"), ("↓", lambda: self._deplacer(1), "Descendre")):
            b = Bouton(texte, "discret")
            b.setToolTip(tip)
            b.clicked.connect(f)
            h.addWidget(b)
        b = Bouton("Nouvelle", "primaire")
        b.clicked.connect(self._nouvelle)
        h.addWidget(b, 1)
        gauche.addLayout(h)
        h2 = QHBoxLayout()
        self.b_suppr = Bouton("Supprimer", "danger")
        self.b_suppr.clicked.connect(self._supprimer)
        h2.addWidget(self.b_suppr)
        b = Bouton("Prédéfinies", "discret")
        b.setToolTip("Recrée les catégories livrées avec Flux qui ont été supprimées")
        b.clicked.connect(self._restaurer)
        h2.addWidget(b)
        gauche.addLayout(h2)
        racine.addLayout(gauche)

        self.droite = QWidget()
        d = QVBoxLayout(self.droite)
        d.setContentsMargins(0, 0, 0, 0)
        d.setSpacing(10)
        g = QGridLayout()
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(10)
        g.addWidget(QLabel("Nom"), 0, 0)
        self.nom = QLineEdit()
        self.nom.textEdited.connect(self._modifie)
        g.addWidget(self.nom, 0, 1)
        g.addWidget(QLabel("Couleur"), 1, 0)
        hc = QHBoxLayout()
        self.couleurs = []
        from .page_reglages import Pastille_couleur
        for hexa in COULEURS_CATEGORIES:
            b = Pastille_couleur(hexa)
            b.clicked.connect(lambda _=False, x=hexa: self._couleur(x))
            hc.addWidget(b)
            self.couleurs.append((hexa, b))
        autre = Bouton("Autre…", "discret")
        autre.clicked.connect(self._autre_couleur)
        hc.addWidget(autre)
        hc.addStretch(1)
        g.addLayout(hc, 1, 1)
        g.addWidget(QLabel("Notifier"), 2, 0)
        hn = QHBoxLayout()
        self.notifier = Interrupteur()
        self.notifier.toggled.connect(self._modifie)
        hn.addWidget(self.notifier)
        hn.addWidget(etiquette("Envoie une notification (Réglages › Notifications) pour chaque nouvelle action de "
                               "cette catégorie."), 1)
        g.addLayout(hn, 2, 1)
        g.setColumnStretch(1, 1)
        d.addLayout(g)

        titre = QLabel("Classement automatique")
        titre.setObjectName("titre")
        d.addSpacing(4)
        d.addWidget(titre)
        hm = QHBoxLayout()
        hm.addWidget(QLabel("Une action entre dans la catégorie si elle respecte"))
        self.mode = QComboBox()
        self.mode.addItem("tous les critères cochés", "et")
        self.mode.addItem("au moins un critère", "ou")
        self.mode.currentIndexChanged.connect(self._modifie)
        hm.addWidget(self.mode)
        hm.addStretch(1)
        d.addLayout(hm)
        d.addWidget(etiquette("TYPE D'ACTION", "section"))
        gt = QGridLayout()
        self.cases_types = {}
        for i, (k, lib) in enumerate(TYPES_ACTION.items()):
            c = QCheckBox(lib)
            c.toggled.connect(self._modifie)
            gt.addWidget(c, i // 4, i % 4)
            self.cases_types[k] = c
        d.addLayout(gt)
        d.addWidget(etiquette("CATÉGORIE DE LA PERSONNE", "section"))
        hp = QHBoxLayout()
        self.cases_personnes = {}
        for k, lib in CATEGORIES_PERSONNE:
            c = QCheckBox(lib)
            c.toggled.connect(self._modifie)
            hp.addWidget(c)
            self.cases_personnes[k] = c
        hp.addStretch(1)
        d.addLayout(hp)
        g2 = QGridLayout()
        g2.setHorizontalSpacing(14)
        g2.addWidget(QLabel("Caméras"), 0, 0)
        self.cameras = QLineEdit()
        cams = self.base.cameras()
        self.cameras.setPlaceholderText("Toutes" + (f" — ex. {', '.join(cams[:2])}" if cams else ""))
        self.cameras.textEdited.connect(self._modifie)
        g2.addWidget(self.cameras, 0, 1)
        g2.addWidget(QLabel("Mots-clés"), 1, 0)
        self.mots = QLineEdit()
        self.mots.setPlaceholderText("Dans le détail ou le nom, séparés par des virgules (ex. 1-ABC-234, livreur)")
        self.mots.textEdited.connect(self._modifie)
        g2.addWidget(self.mots, 1, 1)
        g2.setColumnStretch(1, 1)
        d.addLayout(g2)
        self.apercu = etiquette("")
        d.addWidget(self.apercu)
        d.addWidget(etiquette("Sans aucun critère, la catégorie ne se remplit que par classement manuel "
                              "(clic droit sur une action › Classer dans)."))
        d.addStretch(1)
        hb = QHBoxLayout()
        hb.addStretch(1)
        b = Bouton("Fermer", "primaire")
        b.clicked.connect(self.accept)
        hb.addWidget(b)
        d.addLayout(hb)
        racine.addWidget(self.droite, 1)
        self._remplir(cid)

    # --- liste ---------------------------------------------------------------------
    def _remplir(self, choisir=None):
        self.cats = self.base.categories_journal()
        self.liste.blockSignals(True)
        self.liste.clear()
        for c in self.cats:
            it = QListWidgetItem(icone_couleur(c["couleur"]), c["nom"] + ("  🔔" if c["notifier"] else ""))
            it.setData(Qt.ItemDataRole.UserRole, c["id"])
            self.liste.addItem(it)
        self.liste.blockSignals(False)
        ids = [c["id"] for c in self.cats]
        self.liste.setCurrentRow(ids.index(choisir) if choisir in ids else (0 if ids else -1))
        if not ids:
            self._afficher(-1)

    def _courante(self):
        r = self.liste.currentRow()
        return self.cats[r] if 0 <= r < len(self.cats) else None

    def _afficher(self, _r):
        c = self._courante()
        self.droite.setEnabled(c is not None)
        self.b_suppr.setEnabled(c is not None)
        if c is None:
            return
        self._charge = True
        self.nom.setText(c["nom"])
        self._couleur_actuelle = c["couleur"]
        for hexa, b in self.couleurs:
            b.setChecked(hexa.upper() == c["couleur"].upper())
        self.notifier.regler(c["notifier"])
        r = c["regles"]
        self.mode.setCurrentIndex(1 if r.get("mode") == "ou" else 0)
        for k, case in self.cases_types.items():
            case.setChecked(k in r.get("types", []))
        for k, case in self.cases_personnes.items():
            case.setChecked(k in r.get("personnes", []))
        self.cameras.setText(", ".join(r.get("cameras", [])))
        self.mots.setText(", ".join(r.get("mots", [])))
        self._charge = False
        self._maj_apercu()

    def _regles(self):
        decouper = lambda t: [x.strip() for x in t.split(",") if x.strip()]  # noqa: E731
        return {"types": [k for k, c in self.cases_types.items() if c.isChecked()],
                "personnes": [k for k, c in self.cases_personnes.items() if c.isChecked()],
                "cameras": decouper(self.cameras.text()), "mots": decouper(self.mots.text()),
                "mode": self.mode.currentData()}

    def _modifie(self, *_):
        if not self._charge:
            self._minuteur.start()
            self._maj_apercu()

    def _maj_apercu(self):
        regles = self._regles()
        actions = self.base.actions(limite=5000, depuis=time.time() - 30 * 86400)
        n = sum(1 for a in actions if correspond(a, regles))
        self.apercu.setText(f"Aperçu : {n} action(s) des 30 derniers jours correspondent à ces règles.")

    def _enregistrer(self):
        c = self._courante()
        if c is None:
            return
        nom = self.nom.text().strip() or c["nom"]
        self.base.enregistrer_categorie(nom, self._couleur_actuelle, self._regles(), self.notifier.isChecked(), c["id"])
        it = self.liste.currentItem()
        c.update(nom=nom, couleur=self._couleur_actuelle, notifier=self.notifier.isChecked(), regles=self._regles())
        it.setText(nom + ("  🔔" if c["notifier"] else ""))
        it.setIcon(icone_couleur(self._couleur_actuelle))

    def _couleur(self, hexa):
        self._couleur_actuelle = hexa
        for x, b in self.couleurs:
            b.setChecked(x.upper() == hexa.upper())
        self._modifie()

    def _autre_couleur(self):
        c = QColorDialog.getColor(QColor(getattr(self, "_couleur_actuelle", "#2F7BFF")), self, "Couleur")
        if c.isValid():
            self._couleur(c.name().upper())

    def _nouvelle(self):
        self._minuteur.stop()
        self._enregistrer()
        cid = self.base.enregistrer_categorie("Nouvelle catégorie",
                                              COULEURS_CATEGORIES[len(self.cats) % len(COULEURS_CATEGORIES)])
        self._remplir(cid)
        self.nom.setFocus()
        self.nom.selectAll()

    def _supprimer(self):
        c = self._courante()
        if c and QMessageBox.question(self, "Supprimer", f"Supprimer la catégorie « {c['nom']} » ? Les actions sont "
                                                         "conservées.") == QMessageBox.StandardButton.Yes:
            self._minuteur.stop()
            self.base.supprimer_categorie(c["id"])
            self._remplir()

    def _deplacer(self, sens):
        c = self._courante()
        if c:
            self._minuteur.stop()
            self._enregistrer()
            self.base.deplacer_categorie(c["id"], sens)
            self._remplir(c["id"])

    def _restaurer(self):
        self._minuteur.stop()
        self._enregistrer()
        n = self.base.restaurer_categories()
        self._remplir()
        self.fen.toast(f"{n} catégorie(s) prédéfinie(s) recréée(s)." if n else "Toutes les catégories prédéfinies "
                       "sont déjà présentes.", "ok" if n else "info")

    def done(self, r):
        if self._minuteur.isActive():
            self._minuteur.stop()
            self._enregistrer()
        super().done(r)
