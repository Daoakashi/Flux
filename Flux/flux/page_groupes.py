"""Groupes de caméras : plusieurs caméras affichées côte à côte dans un seul onglet (ou en plein écran).

Un groupe ne démarre rien de lui-même : il affiche les caméras déjà ajoutées. Il se contente de les regarder,
donc ajouter un groupe ne coûte presque rien en calcul (les vignettes sont réduites et rafraîchies plus doucement).

Une vignette peut aussi montrer une seule zone d'une caméra (« Entrée › Porte »), recadrée et agrandie : plusieurs
zones précises d'une même caméra forment un groupe sans créer de flux supplémentaire (un seul décodage, une seule
analyse).
"""

SEP = " › "


def entree(camera, zone=None):
    return f"{camera}{SEP}{zone}" if zone else camera


def analyser_entree(texte, page_cameras):
    """« Caméra » ou « Caméra › Zone » -> (page de la caméra ou None, nom de zone ou None, nom de caméra)."""
    page = page_cameras.page_par_nom(texte)
    if page is not None or SEP not in texte:
        return page, None, texte
    camera, zone = texte.rsplit(SEP, 1)
    return page_cameras.page_par_nom(camera), zone, camera

import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QComboBox, QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMenu, QVBoxLayout, QWidget)

from .theme import C
from .widgets import Bouton, Voyant, VueVideo, etiquette

CHOIX_COLONNES = [(0, "Automatique"), (1, "1 colonne"), (2, "2 colonnes"), (3, "3 colonnes"), (4, "4 colonnes"),
                  (5, "5 colonnes")]


def colonnes_auto(n):
    """2 caméras côte à côte, 3-4 en carré, 5-9 sur 3 colonnes, au-delà 4 colonnes."""
    if n <= 1:
        return 1
    if n <= 4:
        return 2
    if n <= 9:
        return 3
    return 4


class MurVideo(QWidget):
    """La grille de vignettes. Utilisée dans l'onglet du groupe et dans la fenêtre plein écran."""

    ouvrir = Signal(str)    # demande d'ouvrir la page d'une caméra
    retirer = Signal(str)   # demande de retirer une caméra du groupe

    def __init__(self, page_cameras, parent=None):
        super().__init__(parent)
        self.pc = page_cameras
        self.noms, self.colonnes, self.agrandi = [], 0, None
        self.vues = {}
        self.grille = QGridLayout(self)
        self.grille.setContentsMargins(0, 0, 0, 0)
        self.grille.setSpacing(8)

    def definir(self, noms, colonnes):
        self.noms, self.colonnes = list(noms), int(colonnes)
        if self.agrandi not in self.noms:
            self.agrandi = None
        for nom in [n for n in self.vues if n not in self.noms]:
            v = self.vues.pop(nom)
            self.grille.removeWidget(v)
            v.deleteLater()
        for nom in self.noms:
            if nom not in self.vues:
                v = VueVideo(self, zone_active=False, compact=True)
                v.message_vide = "Caméra arrêtée"
                v.doubleClique.connect(lambda n=nom: self.basculer_zoom(n))
                v.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                v.customContextMenuRequested.connect(lambda pos, n=nom, w=v: self._menu(n, w.mapToGlobal(pos)))
                self.vues[nom] = v
        self._disposer()

    def _disposer(self):
        for v in self.vues.values():
            self.grille.removeWidget(v)
            v.hide()
        visibles = [self.agrandi] if self.agrandi else self.noms
        cols = 1 if self.agrandi else (self.colonnes or colonnes_auto(len(visibles)))
        cols = max(1, min(cols, len(visibles) or 1))
        lignes = math.ceil(len(visibles) / cols) if visibles else 1
        for i in range(max(cols, self.grille.columnCount()) + 1):
            self.grille.setColumnStretch(i, 1 if i < cols else 0)
        for i in range(max(lignes, self.grille.rowCount()) + 1):
            self.grille.setRowStretch(i, 1 if i < lignes else 0)
        for i, nom in enumerate(visibles):
            self.grille.addWidget(self.vues[nom], i // cols, i % cols)
            self.vues[nom].show()

    def basculer_zoom(self, nom):
        self.agrandi = None if self.agrandi == nom else nom
        self._disposer()

    def _menu(self, nom, pos):
        page, _zone, camera = analyser_entree(nom, self.pc)
        m = QMenu(self)
        m.addAction("Réduire" if self.agrandi == nom else "Agrandir dans le groupe", lambda: self.basculer_zoom(nom))
        if page is not None:
            m.addAction("Ouvrir la page de cette caméra", lambda: self.ouvrir.emit(camera))
            m.addAction("Arrêter cette caméra" if page.en_cours() else "Démarrer cette caméra",
                        page._basculer_marche)
        m.addSeparator()
        m.addAction("Retirer du groupe", lambda: self.retirer.emit(nom))
        m.exec(pos)

    def rafraichir(self):
        """Met à jour les vignettes affichées. Renvoie {nom: état} des caméras du groupe."""
        etats = {}
        for nom, v in self.vues.items():
            page, zone, _camera = analyser_entree(nom, self.pc)
            if page is None:
                if v._image is not None:
                    v.effacer()
                v.message_vide = "Caméra introuvable"
                v.regler_etat("arret", "", [], 0.0, [nom])
                etats[nom] = "arret"
            elif v.isVisible():
                etats[nom] = page.alimenter_vue(v, zone=zone, titre=nom)
        return etats


class FenetreMur(QWidget):
    """Le groupe en plein écran (Échap pour quitter, double-clic sur une vignette pour l'agrandir)."""

    fermee = Signal()

    def __init__(self, page_cameras, titre):
        super().__init__(None, Qt.WindowType.Window)
        self.setWindowTitle(f"Flux · {titre}")
        self.setStyleSheet(f"FenetreMur {{ background: {C['fond']}; }}")
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        self.mur = MurVideo(page_cameras, self)
        v.addWidget(self.mur, 1)
        for touche in ("Escape", "F11"):
            QShortcut(QKeySequence(touche), self, activated=self.close)

    def closeEvent(self, e):
        self.fermee.emit()
        e.accept()


class PageGroupe(QWidget):
    """Un onglet « groupe » : une grille de caméras."""

    def __init__(self, page_cameras, nom, cameras, colonnes=0):
        super().__init__()
        self.page, self.fen = page_cameras, page_cameras.fen
        self.nom, self.cameras, self.colonnes = nom, list(cameras), int(colonnes)
        self.cle = f"groupe-{id(self)}"
        self.voyant_onglet = Voyant(10)
        self.plein_ecran = None
        self._titre = None

        racine = QVBoxLayout(self)
        racine.setContentsMargins(0, 10, 0, 0)
        racine.setSpacing(12)
        entete = QHBoxLayout()
        entete.setSpacing(10)
        self.voyant = Voyant(14)
        entete.addWidget(self.voyant)
        bloc = QVBoxLayout()
        bloc.setSpacing(0)
        self.titre = QLabel(nom)
        self.titre.setObjectName("titre")
        self.sous_titre = QLabel("")
        self.sous_titre.setObjectName("soustitre")
        bloc.addWidget(self.titre)
        bloc.addWidget(self.sous_titre)
        entete.addLayout(bloc)
        entete.addStretch(1)
        b_tout = Bouton("Tout démarrer", "discret", "lecture")
        b_tout.setToolTip("Démarre toutes les caméras de ce groupe")
        b_tout.clicked.connect(self._tout_demarrer)
        b_stop = Bouton("Tout arrêter", "discret", "pause")
        b_stop.clicked.connect(self._tout_arreter)
        b_modif = Bouton("Modifier…", "discret", "reglages")
        b_modif.setToolTip("Changer le nom, les caméras ou le nombre de colonnes")
        b_modif.clicked.connect(self.modifier)
        b_plein = Bouton("Plein écran", "primaire", "plein_ecran")
        b_plein.setToolTip("Afficher ce groupe en plein écran (Échap pour revenir)")
        b_plein.clicked.connect(self.ouvrir_plein_ecran)
        b_suppr = Bouton("Supprimer le groupe", "danger")
        b_suppr.clicked.connect(lambda: self.page.supprimer_groupe(self))
        for b in (b_tout, b_stop, b_modif, b_plein, b_suppr):
            entete.addWidget(b)
        racine.addLayout(entete)

        self.mur = MurVideo(page_cameras, self)
        self.mur.ouvrir.connect(self.page.ouvrir_camera)
        self.mur.retirer.connect(self._retirer)
        racine.addWidget(self.mur, 1)
        racine.addWidget(etiquette("Double-clic sur une vignette pour l'agrandir · clic droit pour plus d'options."))
        self.mur.definir(self.cameras, self.colonnes)

    # --- contenu -----------------------------------------------------------------------
    def appliquer(self, nom, cameras, colonnes):
        self.nom, self.cameras, self.colonnes = nom, list(cameras), int(colonnes)
        self.titre.setText(nom)
        self.mur.definir(self.cameras, self.colonnes)
        if self.plein_ecran is not None:
            self.plein_ecran.mur.definir(self.cameras, self.colonnes)
        self._titre = None
        self.page.sauver()

    def modifier(self):
        d = DialogueGroupe(self, self.page.entrees_disponibles(), self.nom, self.cameras, self.colonnes)
        if d.exec() == QDialog.DialogCode.Accepted and d.resultat:
            self.appliquer(*d.resultat)

    def _retirer(self, nom):
        if nom in self.cameras:
            self.appliquer(self.nom, [c for c in self.cameras if c != nom], self.colonnes)

    def camera_supprimee(self, nom):
        reste = [c for c in self.cameras if c != nom and not c.startswith(nom + SEP)]
        if reste != self.cameras:
            self.appliquer(self.nom, reste, self.colonnes)

    def camera_renommee(self, ancien, nouveau):
        def renommer(c):
            if c == ancien:
                return nouveau
            if c.startswith(ancien + SEP):
                return nouveau + c[len(ancien):]
            return c
        nouvelles = [renommer(c) for c in self.cameras]
        if nouvelles != self.cameras:
            self.appliquer(self.nom, nouvelles, self.colonnes)

    def zone_renommee(self, camera, ancien, nouveau):
        nouvelles = [entree(camera, nouveau) if c == entree(camera, ancien) else c for c in self.cameras]
        if nouvelles != self.cameras:
            self.appliquer(self.nom, nouvelles, self.colonnes)

    def zone_supprimee(self, camera, zone):
        if entree(camera, zone) in self.cameras:
            self.appliquer(self.nom, [c for c in self.cameras if c != entree(camera, zone)], self.colonnes)

    def _pages(self):
        pages = []
        for n in self.cameras:
            p = analyser_entree(n, self.page)[0]
            if p is not None and p not in pages:
                pages.append(p)
        return pages

    def _tout_demarrer(self):
        for p in self._pages():
            if not p.en_cours():
                p.demarrer()

    def _tout_arreter(self):
        for p in self._pages():
            p.arreter()

    # --- plein écran -------------------------------------------------------------------
    def ouvrir_plein_ecran(self):
        if self.plein_ecran is not None:
            self.plein_ecran.activateWindow()
            return
        f = FenetreMur(self.page, self.nom)
        f.mur.definir(self.cameras, self.colonnes)
        f.mur.ouvrir.connect(lambda n: (f.close(), self.page.ouvrir_camera(n)))
        f.mur.retirer.connect(self._retirer)
        f.fermee.connect(self._plein_ecran_ferme)
        self.plein_ecran = f
        f.showFullScreen()

    def _plein_ecran_ferme(self):
        f, self.plein_ecran = self.plein_ecran, None
        if f is not None:
            f.deleteLater()

    def fermer_fenetres(self):
        if self.plein_ecran is not None:
            self.plein_ecran.close()

    # --- rafraîchissement ------------------------------------------------------------------
    def mise_a_jour(self, visible):
        etats = {}
        if visible:
            etats = self.mur.rafraichir()
        if self.plein_ecran is not None:
            etats = self.plein_ecran.mur.rafraichir() or etats
        if not etats:  # ni onglet visible ni plein écran : on lit juste l'état des caméras
            etats = {n: self.page.etat_camera(analyser_entree(n, self.page)[2]) for n in self.cameras}
        valeurs = list(etats.values())
        etat = ("alerte" if "alerte" in valeurs else "direct" if "direct" in valeurs
                else "chargement" if "chargement" in valeurs else "arret")
        self.voyant.regler(etat)
        self.voyant_onglet.regler(etat)
        actives = sum(1 for e in valeurs if e in ("direct", "alerte", "chargement"))
        n_zones = sum(1 for c in self.cameras if analyser_entree(c, self.page)[1])
        n_cam = len(self.cameras) - n_zones
        morceaux = ([f"{n_cam} caméra{'s' if n_cam > 1 else ''}"] if n_cam else []) + (
            [f"{n_zones} zone{'s' if n_zones > 1 else ''}"] if n_zones else [])
        texte = " + ".join(morceaux or ["vide"]) + f" · {actives} vue{'s' if actives > 1 else ''} en marche"
        if texte != self.sous_titre.text():
            self.sous_titre.setText(texte)
        titre = self.nom + "  ▦"
        if titre != self._titre:
            self._titre = titre
            self.page.titre_onglet(self, titre)
        return etat


class DialogueGroupe(QDialog):
    """Créer ou modifier un groupe : nom, caméras (cochées, dans l'ordre d'affichage), colonnes."""

    def __init__(self, parent, noms_disponibles, nom="", selection=(), colonnes=0):
        super().__init__(parent)
        self.setWindowTitle("Groupe de caméras")
        self.setMinimumWidth(480)
        self.resultat = None
        v = QVBoxLayout(self)
        v.setContentsMargins(26, 24, 26, 22)
        v.setSpacing(10)
        t = QLabel("Groupe de caméras")
        t.setObjectName("grand")
        v.addWidget(t)
        v.addWidget(etiquette("Un groupe affiche plusieurs vues dans une seule fenêtre. Cochez des caméras entières ou "
                              "des zones précises (« Caméra › Zone ») : une zone s'affiche seule, agrandie, sans créer "
                              "de flux en plus. Dessinez les zones sur l'image d'une caméra. L'ordre de la liste est "
                              "celui de l'écran."))
        v.addSpacing(4)
        v.addWidget(QLabel("Nom du groupe"))
        self.nom = QLineEdit(nom)
        self.nom.setPlaceholderText("Ex. : Extérieur, Rez-de-chaussée…")
        v.addWidget(self.nom)
        v.addWidget(QLabel("Caméras"))
        h = QHBoxLayout()
        self.liste = QListWidget()
        self.liste.setMinimumHeight(180)
        # d'abord celles du groupe (dans leur ordre), puis les autres
        for n in list(selection) + [n for n in noms_disponibles if n not in selection]:
            if n not in noms_disponibles:
                continue
            it = QListWidgetItem(("      ▸ " + n.split(SEP, 1)[1] + "   (" + n.split(SEP, 1)[0] + ")") if SEP in n else n)
            it.setData(Qt.ItemDataRole.UserRole, n)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if n in selection else Qt.CheckState.Unchecked)
            self.liste.addItem(it)
        h.addWidget(self.liste, 1)
        col = QVBoxLayout()
        b_haut = Bouton("Monter", "discret")
        b_bas = Bouton("Descendre", "discret")
        b_haut.clicked.connect(lambda: self._deplacer(-1))
        b_bas.clicked.connect(lambda: self._deplacer(1))
        col.addWidget(b_haut)
        col.addWidget(b_bas)
        col.addStretch(1)
        h.addLayout(col)
        v.addLayout(h)
        v.addWidget(QLabel("Disposition"))
        self.colonnes = QComboBox()
        for k, lib in CHOIX_COLONNES:
            self.colonnes.addItem(lib, k)
        self.colonnes.setCurrentIndex(max(0, self.colonnes.findData(int(colonnes))))
        v.addWidget(self.colonnes)
        self.erreur = etiquette("")
        v.addWidget(self.erreur)
        v.addSpacing(8)
        h2 = QHBoxLayout()
        h2.addStretch(1)
        b_annuler = Bouton("Annuler")
        b_annuler.clicked.connect(self.reject)
        b_ok = Bouton("Enregistrer", "primaire")
        b_ok.clicked.connect(self._ok)
        b_ok.setDefault(True)
        h2.addWidget(b_annuler)
        h2.addWidget(b_ok)
        v.addLayout(h2)

    def _deplacer(self, sens):
        i = self.liste.currentRow()
        j = i + sens
        if i < 0 or not 0 <= j < self.liste.count():
            return
        it = self.liste.takeItem(i)
        self.liste.insertItem(j, it)
        self.liste.setCurrentRow(j)

    def _ok(self):
        choisies = [self.liste.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.liste.count())
                    if self.liste.item(i).checkState() == Qt.CheckState.Checked]
        if not choisies:
            self.erreur.setText("Cochez au moins une caméra ou une zone.")
            return
        self.resultat = (self.nom.text().strip() or "Groupe", choisies, self.colonnes.currentData())
        self.accept()
