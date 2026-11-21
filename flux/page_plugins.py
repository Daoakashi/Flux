"""Onglet Plugins : le gestionnaire (installer, activer, retirer) et les pages des plugins installés.

Chaque plugin actif ajoute ses propres pages dans la colonne de gauche de cet onglet : Flux garde une barre de
navigation courte, même avec beaucoup de plugins.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox,
                               QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from .theme import C
from .widgets import Bouton, Interrupteur, etiquette


class Pastille(QWidget):
    """Petit sceau « vérifié » dessiné (signature de l'éditeur contrôlée)."""

    def __init__(self, ok=True):
        super().__init__()
        self.ok = ok
        self.setFixedSize(18, 18)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QColor(C["succes"] if self.ok else C["danger"])
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawEllipse(1, 1, 16, 16)
        p.setPen(QPen(QColor("#FFFFFF"), 2))
        if self.ok:
            p.drawLine(5, 9, 8, 12)
            p.drawLine(8, 12, 13, 6)
        else:
            p.drawLine(6, 6, 12, 12)
            p.drawLine(12, 6, 6, 12)


class CartePlugin(QFrame):
    def __init__(self, page, p):
        super().__init__()
        self.setObjectName("carte")
        g = page.fen.plugins
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 14)
        v.setSpacing(6)
        h = QHBoxLayout()
        nom = QLabel(p.info.get("nom", p.id))
        nom.setWordWrap(True)
        nom.setStyleSheet("font-size: 16px; font-weight: 700;")
        h.addWidget(nom)
        version = QLabel(f"v{p.info.get('version', '?')}")
        version.setStyleSheet(f"color: {C['texte3']};")
        h.addWidget(version)
        h.addStretch(1)
        h.addWidget(QLabel("Activé"))
        bascule = Interrupteur()
        bascule.regler(g.actif(p.id))
        bascule.toggled.connect(lambda etat: page.activer(p.id, etat))
        h.addWidget(bascule)
        v.addLayout(h)
        if p.info.get("description"):
            v.addWidget(etiquette(p.info["description"]))
        h2 = QHBoxLayout()
        h2.addWidget(Pastille(True))
        h2.addWidget(etiquette(f"Signé par {p.editeur} · signature vérifiée"), 1)
        etat = "en marche" if p.objet is not None else ("erreur" if p.erreur else "désactivé")
        lab = QLabel(etat.upper())
        couleur = {"en marche": C["succes"], "erreur": C["danger"]}.get(etat, C["texte3"])
        lab.setStyleSheet(f"color: {couleur}; font-weight: 700; letter-spacing: 1px;")
        h2.addWidget(lab)
        b = Bouton("Désinstaller", "fantome")
        b.clicked.connect(lambda: page.desinstaller(p.id))
        h2.addWidget(b)
        v.addLayout(h2)
        if p.erreur:
            e = etiquette(f"Erreur : {p.erreur}")
            e.setStyleSheet(f"color: {C['danger']};")
            v.addWidget(e)


class CarteCatalogue(QFrame):
    def __init__(self, page, entree, installe):
        super().__init__()
        self.setObjectName("carte")
        h = QHBoxLayout(self)
        h.setContentsMargins(18, 12, 18, 12)
        v = QVBoxLayout()
        t = QLabel(f"{entree.get('nom', entree['id'])}  ·  v{entree.get('version', '?')}")
        t.setStyleSheet("font-weight: 700;")
        v.addWidget(t)
        if entree.get("description"):
            v.addWidget(etiquette(entree["description"]))
        h.addLayout(v, 1)
        b = Bouton("Mettre à jour" if installe else "Installer", "primaire")
        b.clicked.connect(lambda: page.installer_catalogue(entree))
        h.addWidget(b)


class Gestion(QWidget):
    """Page « Gestionnaire » : liste des plugins installés et installation d'un fichier .fluxplug."""

    def __init__(self, page):
        super().__init__()
        self.page = page
        racine = QVBoxLayout(self)
        racine.setContentsMargins(0, 0, 0, 0)
        defil = QScrollArea()
        defil.setWidgetResizable(True)
        defil.setFrameShape(QFrame.Shape.NoFrame)
        racine.addWidget(defil)
        contenu = QWidget()
        defil.setWidget(contenu)
        self.v = QVBoxLayout(contenu)
        self.v.setContentsMargins(4, 4, 8, 8)
        self.v.setSpacing(12)

    def rafraichir(self):
        while self.v.count():
            it = self.v.takeAt(0)
            w = it.widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        h = QHBoxLayout()
        t = QLabel("Gestionnaire de plugins")
        t.setStyleSheet("font-size: 18px; font-weight: 700;")
        h.addWidget(t)
        h.addStretch(1)
        b = Bouton("Installer un plugin…", "primaire", "plus")
        b.clicked.connect(self.page.installer)
        h.addWidget(b)
        conteneur = QWidget()
        conteneur.setLayout(h)
        self.v.addWidget(conteneur)
        self.v.addWidget(etiquette(
            "Les plugins ajoutent des fonctions de surveillance avancées à Flux. Ils arrivent sous forme de fichier "
            ".fluxplug, lisible seulement par Flux : Flux vérifie la signature de l'éditeur avant d'installer quoi que "
            "ce soit et refuse tout plugin modifié ou d'origine inconnue."))
        plugins = list(self.page.fen.plugins.plugins.values())
        if not plugins:
            vide = QFrame()
            vide.setObjectName("carte")
            vv = QVBoxLayout(vide)
            vv.setContentsMargins(24, 28, 24, 28)
            lab = QLabel("Aucun plugin installé")
            lab.setStyleSheet("font-size: 15px; font-weight: 600;")
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            vv.addWidget(lab)
            aide = etiquette("Cliquez sur « Installer un plugin… » et choisissez un fichier .fluxplug fourni par "
                             "DMS Security.")
            aide.setAlignment(Qt.AlignmentFlag.AlignCenter)
            vv.addWidget(aide)
            self.v.addWidget(vide)
        for p in sorted(plugins, key=lambda x: x.info.get("nom", x.id).lower()):
            self.v.addWidget(CartePlugin(self.page, p))
        # catalogue du serveur Flux
        ligne = QHBoxLayout()
        ligne.addWidget(etiquette("CATALOGUE DMS SECURITY", "section"), 1)
        b = Bouton("Actualiser", "fantome")
        b.clicked.connect(self.page.charger_catalogue)
        ligne.addWidget(b)
        conteneur = QWidget()
        conteneur.setLayout(ligne)
        self.v.addWidget(conteneur)
        cat = self.page.catalogue
        if cat is None:
            self.v.addWidget(etiquette(self.page.etat_catalogue or "Cliquez sur « Actualiser » pour voir les plugins "
                                                                   "proposés par le serveur Flux."))
        else:
            dispo = [e for e in cat if self.page.fen.plugins.plus_recent(e)]
            if not dispo:
                self.v.addWidget(etiquette("Tous les plugins du catalogue sont installés et à jour."))
            for e in dispo:
                self.v.addWidget(CarteCatalogue(self.page, e, e.get("id") in self.page.fen.plugins.plugins))
        self.v.addStretch(1)


class PagePlugins(QWidget):
    def __init__(self, fen):
        super().__init__()
        self.fen = fen
        self._pages = []        # widgets de plugins actuellement montés (non détruits : ils appartiennent au plugin)
        self.catalogue = None
        self.etat_catalogue = ""
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(18)
        gauche = QVBoxLayout()
        t = QLabel("Plugins")
        t.setObjectName("titre_page")
        gauche.addWidget(t)
        self.liste = QListWidget()
        self.liste.setFixedWidth(180)
        self.liste.setFrameShape(QFrame.Shape.NoFrame)
        self.liste.setStyleSheet(
            f"QListWidget {{ background: transparent; outline: none; }}"
            f"QListWidget::item {{ padding: 9px 12px; border-radius: 8px; margin: 1px 0; color: {C['texte2']}; }}"
            f"QListWidget::item:selected {{ background: {C['surface2']}; color: {C['texte']}; font-weight: 600; }}")
        self.liste.currentRowChanged.connect(lambda i: self.pile.setCurrentIndex(max(0, i)))
        gauche.addWidget(self.liste, 1)
        h.addLayout(gauche)
        self.pile = QStackedWidget()
        h.addWidget(self.pile, 1)
        self.gestion = Gestion(self)
        fen.plugins.rappels.append(self.rafraichir)
        self.rafraichir()

    def rafraichir(self):
        courant = self.liste.currentItem().text() if self.liste.currentItem() else None
        self.liste.blockSignals(True)
        self.liste.clear()
        for w in self._pages:
            self.pile.removeWidget(w)
            w.setParent(None)
        self._pages = []
        while self.pile.count():
            self.pile.removeWidget(self.pile.widget(0))
        self.gestion.rafraichir()
        self.pile.addWidget(self.gestion)
        self.liste.addItem(QListWidgetItem("Gestionnaire"))
        for _ident, titre, w in self.fen.plugins.pages():
            self.liste.addItem(QListWidgetItem(titre))
            self.pile.addWidget(w)
            self._pages.append(w)
        self.liste.blockSignals(False)
        lignes = [self.liste.item(i).text() for i in range(self.liste.count())]
        self.liste.setCurrentRow(lignes.index(courant) if courant in lignes else (1 if len(lignes) > 1 else 0))

    def aller_page(self, titre):
        for i in range(self.liste.count()):
            if self.liste.item(i).text() == titre:
                self.liste.setCurrentRow(i)

    # --- actions ---------------------------------------------------------------------------------------
    def _autorise(self, titre):
        if getattr(self.fen, "kiosque", False):
            return self.fen.demander_code_kiosque(titre)
        return True

    def installer(self):
        from . import plugins
        if not self._autorise("Installer un plugin"):
            return
        chemin, _ = QFileDialog.getOpenFileName(self, "Installer un plugin", "", "Plugins Flux (*.fluxplug)")
        if not chemin:
            return
        try:
            info = self.fen.plugins.installer(chemin)
        except (plugins.ErreurPlugin, OSError) as e:
            QMessageBox.warning(self, "Plugin refusé", f"Ce plugin n'a pas été installé :\n{e}")
            return
        self.fen.toast(f"Plugin « {info['nom']} » {info['version']} installé.", "ok")
        self.aller_page(info["nom"])

    def charger_catalogue(self):
        from .taches import en_arriere_plan
        self.etat_catalogue = "Chargement du catalogue…"
        self.catalogue = None
        self.gestion.rafraichir()

        def fini(liste):
            self.catalogue = liste
            self.gestion.rafraichir()

        def echec(e):
            self.etat_catalogue = f"Catalogue indisponible : {e}"
            self.gestion.rafraichir()
        en_arriere_plan(lambda: self.fen.plugins.catalogue(self.fen.cfg), fini, echec)

    def installer_catalogue(self, entree):
        from . import plugins
        from .taches import en_arriere_plan
        if not self._autorise("Installer un plugin"):
            return
        self.fen.toast(f"Téléchargement de « {entree.get('nom')} »…", "info")

        def fini(chemin):
            import os
            try:
                info = self.fen.plugins.installer(chemin)
            except (plugins.ErreurPlugin, OSError) as e:
                QMessageBox.warning(self, "Plugin refusé", f"Ce plugin n'a pas été installé :\n{e}")
                return
            finally:
                try:
                    os.remove(chemin)
                except OSError:
                    pass
            self.fen.toast(f"Plugin « {info['nom']} » {info['version']} installé.", "ok")
            self.aller_page(info["nom"])

        en_arriere_plan(lambda: self.fen.plugins.telecharger(self.fen.cfg, entree), fini,
                        lambda e: QMessageBox.warning(self, "Téléchargement", f"Téléchargement impossible : {e}"))

    def activer(self, ident, etat):
        if not self._autorise("Activer ou désactiver un plugin"):
            self.rafraichir()
            return
        self.fen.plugins.activer(ident, etat)

    def desinstaller(self, ident):
        p = self.fen.plugins.plugins.get(ident)
        if p is None or not self._autorise("Désinstaller un plugin"):
            return
        r = QMessageBox.question(self, "Désinstaller", f"Désinstaller « {p.info.get('nom', ident)} » ?\n"
                                 "Ses réglages sont conservés : une réinstallation les retrouve.")
        if r == QMessageBox.StandardButton.Yes:
            self.fen.plugins.desinstaller(ident)
