"""Fenêtre principale de Flux, écran de démarrage et lancement de l'application."""

import os
import queue
import sys
import time
from datetime import datetime

import shiboken6
from PySide6.QtCore import QEasingCurve, QObject, QPropertyAnimation, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QKeySequence, QLinearGradient, QPainter, QPainterPath, QShortcut
from PySide6.QtWidgets import (QApplication, QDialog, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QMainWindow,
                               QProgressBar, QStackedWidget, QStatusBar, QTextBrowser, QVBoxLayout,
                               QWidget)

from . import theme
from .base import Base
from . import config as module_config
from .config import DOSSIER_MODELES, FICHIER_BASE, RACINE, Config, identite, niveau_effectif
from .page_cameras import PageCameras
from .page_journal import PageJournal
from .page_lecteur import PageLecteur
from .page_personnes import PagePersonnes
from .page_reglages import PageReglages
from .notifications import Notifieur
from .sources import PREFIXE_MAIL_OK, Mailer, slug
from .taches import Tache
from .theme import C, T, couleur, dessiner_logo, icone_application, police, regler_logo
from .widgets import Bouton, BoutonNav, Logo, Toasts, etiquette
from . import vision

PAGES = [("cameras", "Caméras", "cameras"), ("lecteur", "Lecteur", "lecteur"), ("personnes", "Personnes", "personnes"),
         ("journal", "Journal", "journal"), ("reglages", "Réglages", "reglages")]


# ---------------------------------------------------------------------------
# Écran de démarrage
# ---------------------------------------------------------------------------
class Chargement(QObject):
    etape = Signal(str, float)
    fini = Signal(object)


class EcranDemarrage(QWidget):
    """Logo animé, nom, version et progression réelle du chargement (matériel, base, modèles)."""

    def __init__(self, ident=None):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.SplashScreen)
        self.ident = ident or identite()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(560, 340)
        self.texte = "Démarrage…"
        self.avance = 0.0
        self.cible = 0.0
        self.phase = 0.0
        self.t0 = time.time()
        self._t = QTimer(self)
        self._t.setInterval(16)
        self._t.timeout.connect(self._tic)
        self._t.start()
        ecran = QApplication.primaryScreen().availableGeometry()
        self.move(ecran.center().x() - self.width() // 2, ecran.center().y() - self.height() // 2)

    def _tic(self):
        self.phase += 0.06 if T.animations else 0
        self.avance += (self.cible - self.avance) * (0.12 if T.animations else 1)
        self.update()

    def etape(self, texte, avance):
        self.texte, self.cible = texte, avance

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(10, 10, -10, -10)
        for i in range(10, 0, -1):  # ombre douce
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 5))
            p.drawRoundedRect(r.adjusted(-i, -i + 4, i, i + 4), 22 + i, 22 + i)
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        if T.theme == "sombre":
            g.setColorAt(0, QColor("#0E1A2E"))
            g.setColorAt(1, QColor("#081120"))
        else:
            g.setColorAt(0, QColor("#FFFFFF"))
            g.setColorAt(1, QColor("#EAF1FB"))
        chemin = QPainterPath()
        chemin.addRoundedRect(r, 22, 22)
        p.fillPath(chemin, g)
        p.setPen(couleur("trait"))
        p.drawPath(chemin)
        # apparition : léger glissé du logo
        a = min(1.0, (time.time() - self.t0) / 0.6) if T.animations else 1.0
        a = 1 - (1 - a) ** 3
        logo = QRectF(r.left() + 44, r.top() + 58 + 12 * (1 - a), 92, 92)
        p.setOpacity(a)
        dessiner_logo(p, logo, self.phase)
        p.setPen(couleur("texte"))
        p.setFont(police(52 if len(self.ident["nom"]) <= 8 else max(26, 52 - 3 * (len(self.ident["nom"]) - 8)), True))
        p.drawText(QRectF(logo.right() + 26, logo.top() - 4, r.right() - logo.right() - 40, 64), Qt.AlignmentFlag.AlignLeft |
                   Qt.AlignmentFlag.AlignVCenter, self.ident["nom"])
        p.setPen(couleur("texte2"))
        p.setFont(police(15))
        p.drawText(QRectF(logo.right() + 28, logo.top() + 58, r.right() - logo.right() - 40, 30), Qt.AlignmentFlag.AlignLeft |
                   Qt.AlignmentFlag.AlignVCenter, self.ident["sous_titre"])
        p.setOpacity(1)
        # progression
        barre = QRectF(r.left() + 44, r.bottom() - 70, r.width() - 88, 4)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(couleur("trait"))
        p.drawRoundedRect(barre, 2, 2)
        p.setBrush(couleur("accent"))
        p.drawRoundedRect(QRectF(barre.left(), barre.top(), barre.width() * max(0.02, self.avance), 4), 2, 2)
        p.setPen(couleur("texte2"))
        p.setFont(police(12))
        p.drawText(QRectF(barre.left(), barre.bottom() + 10, barre.width() - 60, 22),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.texte)
        p.setPen(couleur("texte3"))
        p.drawText(QRectF(barre.left(), barre.bottom() + 10, barre.width(), 22),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self.ident["texte_version"])

    def disparaitre(self, apres=None):
        self._fondu = QPropertyAnimation(self, b"windowOpacity", self)
        self._fondu.setDuration(T.ms(320))
        self._fondu.setStartValue(1.0)
        self._fondu.setEndValue(0.0)
        self._fondu.setEasingCurve(QEasingCurve.Type.InCubic)
        self._fondu.finished.connect(lambda: (self.close(), apres and apres()))
        self._fondu.start()
        if not T.animations:
            self.close()


def charger(signal_etape, cfg):
    """Préparation en arrière-plan pendant l'écran de démarrage."""
    debut = time.time()
    signal_etape("Ouverture de la base de données…", 0.15)
    base = Base(FICHIER_BASE)
    base.purger(cfg.get("base.retention"))
    signal_etape("Détection de la carte graphique…", 0.35)
    info = vision.info_appareil()  # importe PyTorch : la partie la plus longue
    signal_etape(f"Calcul sur : {info['nom']}", 0.7)
    signal_etape("Chargement du moteur de détection…", 0.8)
    try:
        import ultralytics  # noqa: F401  (préchauffe l'import, les caméras démarrent ensuite plus vite)
        vision.sans_statistiques()
    except Exception:  # noqa: BLE001
        pass
    os.makedirs(DOSSIER_MODELES, exist_ok=True)
    presents = [f for f in os.listdir(DOSSIER_MODELES) if f.endswith((".pt", ".onnx", ".engine"))]
    signal_etape(f"{len(presents)} modèle(s) prêt(s)", 0.95)
    time.sleep(0.25)
    signal_etape("Prêt", 1.0)
    reste = (cfg.get("developpeur.duree_demarrage") if cfg.get("developpeur.actif") else 0) - (time.time() - debut)
    if reste > 0:
        time.sleep(reste)
    return base, info


# ---------------------------------------------------------------------------
# Fenêtre principale
# ---------------------------------------------------------------------------
class APropos(QDialog):
    def __init__(self, fen):
        super().__init__(fen)
        self.fen = fen
        ident = identite(fen.cfg)
        self.setWindowTitle(f"À propos de {ident['nom']}")
        self.setMinimumWidth(480)
        v = QVBoxLayout(self)
        v.setContentsMargins(28, 26, 28, 22)
        v.setSpacing(8)
        h = QHBoxLayout()
        lg = Logo(64)
        h.addWidget(lg)
        h.addSpacing(12)
        b = QVBoxLayout()
        t = QLabel(ident["nom"])
        t.setObjectName("grand")
        b.addWidget(t)
        tv = ident["texte_version"]
        self.lbl_version = QLabel(f"{tv[0].upper() + tv[1:]} · {ident['sous_titre'].lower()}")
        self.lbl_version.setObjectName("soustitre")
        self.lbl_version.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lbl_version.mousePressEvent = self._clic_version
        self._clics = []
        b.addWidget(self.lbl_version)
        h.addLayout(b, 1)
        v.addLayout(h)
        v.addSpacing(10)
        info = fen.info_appareil or {}
        s = fen.base.statistiques()
        lignes = [
            ("Calcul", info.get("nom", "en cours de détection…")),
            ("PyTorch", info.get("torch") or "—"),
            ("Base", f"{s['personnes']} personnes, {s['visages']} visages, {s['actions']} actions"),
            ("Dossier", RACINE),
            ("Modèles", "YOLO26 / YOLO11 / RT-DETR (Ultralytics), YuNet et SFace (OpenCV), HSEmotion, RapidOCR"),
        ]
        for k, val in lignes:
            l = QHBoxLayout()
            a = QLabel(k)
            a.setFixedWidth(90)
            a.setObjectName("soustitre")
            l.addWidget(a)
            l.addWidget(etiquette(val, "", True), 1)
            v.addLayout(l)
        v.addSpacing(8)
        v.addWidget(etiquette("Les visages et les plaques sont des données personnelles : informez les personnes filmées "
                              "et respectez les règles de conservation applicables (RGPD)."))
        h2 = QHBoxLayout()
        bo = Bouton("Ouvrir le dossier", "discret", "dossier")
        bo.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(RACINE)))
        h2.addWidget(bo)
        bn = Bouton("Nouveautés", "discret")
        bn.clicked.connect(lambda: DialogueNouveautes(self).exec())
        h2.addWidget(bn)
        bm = Bouton("Mises à jour", "discret")
        bm.clicked.connect(lambda: fen.verifier_mises_a_jour(manuel=True))
        h2.addWidget(bm)
        from .mise_a_jour import depot
        d = depot(fen.cfg)
        if d:
            bg = Bouton("GitHub", "discret", "lien")
            bg.setToolTip(f"https://github.com/{d}")
            bg.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(f"https://github.com/{d}")))
            h2.addWidget(bg)
        h2.addStretch(1)
        bf = Bouton("Fermer", "primaire")
        bf.clicked.connect(self.accept)
        h2.addWidget(bf)
        v.addSpacing(8)
        v.addLayout(h2)


    def _clic_version(self, _e):
        """Sept clics rapides sur la version : active ou désactive le mode développeur."""
        maintenant = time.time()
        self._clics = [t for t in self._clics if maintenant - t < 3] + [maintenant]
        cfg = self.fen.cfg
        reste = 7 - len(self._clics)
        if reste <= 0:
            self._clics = []
            actif = not cfg.get("developpeur.actif")
            cfg.set("developpeur.actif", actif)
            self.fen.toast("Mode développeur activé : Réglages › Développeur." if actif
                           else "Mode développeur désactivé.", "ok")
        elif reste <= 3:
            self.fen.toast(f"Encore {reste} clic(s) pour {'quitter' if cfg.get('developpeur.actif') else 'activer'} "
                           "le mode développeur.")


class DialogueNouveautes(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Nouveautés")
        self.resize(640, 560)
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 14)
        t = QTextBrowser()
        t.setOpenExternalLinks(True)
        try:
            with open(os.path.join(RACINE, "CHANGELOG.txt"), encoding="utf-8") as f:
                texte = f.read()
        except OSError:
            texte = "Journal des modifications introuvable (CHANGELOG.txt)."
        t.setPlainText(texte)
        v.addWidget(t, 1)
        h = QHBoxLayout()
        h.addStretch(1)
        b = Bouton("Fermer", "primaire")
        b.clicked.connect(self.accept)
        h.addWidget(b)
        v.addLayout(h)


class DialogueMaj(QDialog):
    """Nouvelle version disponible : notes, installation avec progression, redémarrage."""

    def __init__(self, fen, info):
        super().__init__(fen)
        self.fen, self.info = fen, info
        self.setWindowTitle("Mise à jour disponible")
        self.resize(620, 520)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 22, 24, 16)
        v.setSpacing(10)
        t = QLabel(f"{identite(fen.cfg)['nom']} {info['libelle']} est disponible")
        t.setObjectName("titre")
        v.addWidget(t)
        v.addWidget(etiquette(f"Version installée : {module_config.libelle_version(module_config.APP_VERSION, module_config.APP_CANAL)}"
                              + (f" · publiée le {info['date'][:10]}" if info.get("date") else "")))
        notes = QTextBrowser()
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(info.get("notes") or "_Pas de notes pour cette version._")
        v.addWidget(notes, 1)
        self.barre = QProgressBar()
        self.barre.setRange(0, 1000)
        self.barre.setTextVisible(False)
        self.barre.setFixedHeight(6)
        self.barre.hide()
        v.addWidget(self.barre)
        self.etat = etiquette("Vos réglages, la base de données et les modèles sont conservés ; le code actuel est "
                              "sauvegardé avant l'installation.")
        v.addWidget(self.etat)
        h = QHBoxLayout()
        self.b_ignorer = Bouton("Ignorer cette version", "fantome")
        self.b_ignorer.clicked.connect(self._ignorer)
        h.addWidget(self.b_ignorer)
        b = Bouton("Voir sur GitHub", "discret")
        b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(info["page"])))
        h.addWidget(b)
        h.addStretch(1)
        self.b_plus_tard = Bouton("Plus tard", "discret")
        self.b_plus_tard.clicked.connect(self.reject)
        h.addWidget(self.b_plus_tard)
        self.b_installer = Bouton("Installer", "primaire")
        self.b_installer.clicked.connect(self._installer)
        h.addWidget(self.b_installer)
        v.addLayout(h)

    def _ignorer(self):
        self.fen.cfg.set("maj.ignoree", self.info["version"])
        self.reject()

    def _installer(self):
        from . import mise_a_jour
        for b in (self.b_installer, self.b_ignorer, self.b_plus_tard):
            b.setEnabled(False)
        self.barre.show()
        ch = Chargement()
        ch.etape.connect(lambda texte, a: (self.etat.setText(texte), self.barre.setValue(int(a * 1000))))
        self._ch = ch
        t = Tache(mise_a_jour.installer, self.fen.cfg, self.info, progression=ch.etape.emit)
        t.fini.connect(self._installe)
        t.echec.connect(self._echec)
        self._tache = t.lancer()

    def _echec(self, msg):
        self.etat.setText(f"Échec de la mise à jour : {msg}. Rien n'a été modifié si l'erreur est survenue avant "
                          "l'installation des fichiers ; sinon restaurez la sauvegarde du dossier « sauvegardes ».")
        self.etat.setStyleSheet(f"color: {C['danger']};")
        self.b_plus_tard.setEnabled(True)
        self.b_plus_tard.setText("Fermer")

    def _installe(self, res):
        self.b_plus_tard.setEnabled(True)
        self.b_plus_tard.setText("Redémarrer plus tard")
        texte = f"Version {res['version']} installée ({res['fichiers']} fichiers)."
        if res["dependances"]:
            texte += (" Les dépendances ont changé : fermez Flux et relancez " + module_config.INSTALLATEUR + " avant de redémarrer.")
            self.etat.setText(texte)
            self.etat.setStyleSheet(f"color: {C['attention']};")
            return
        self.etat.setText(texte + " Redémarrez Flux pour l'utiliser.")
        self.b_installer.setText("Redémarrer maintenant")
        self.b_installer.setEnabled(True)
        self.b_installer.clicked.disconnect()
        self.b_installer.clicked.connect(self.fen.redemarrer)


class FenetrePrincipale(QMainWindow):
    def __init__(self, cfg, base, info=None):
        super().__init__()
        self.cfg, self.base = cfg, base
        self.info_appareil = info or {}
        self.setWindowIcon(icone_application())
        self.setMinimumSize(1100, 700)
        self.evenements = queue.Queue()
        self.mailer = Mailer(cfg, self.log_systeme)
        self.mailer.start()
        self.notifieur = Notifieur(cfg, self.log_systeme)
        self.notifieur.start()
        self.cats_notifier = []
        self.categories_changees()
        self.etat_maj = ""
        self.cameras_au_redemarrage = False
        self.dernier_mail, self.supprimees = {}, {}
        self.index_journal_envoye = 0
        self.dernier_envoi_journal = time.time()
        self._derniere_erreur = None
        self._anims_pages = {}
        self._alertes_non_vues = 0
        self._application_prevue = False

        self._construire()
        self.toasts = Toasts(self.centralWidget())
        self.page_cameras.restaurer()
        self.aller("cameras")
        self._geometrie()
        self.setWindowOpacity(cfg.get("apparence.opacite") / 100)
        cfg.abonner(self._reglage_change)
        self._raccourcis()
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._rafraichir)
        self._timer.start()
        self._timer_stats = QTimer(self)
        self._timer_stats.setInterval(2000)
        self._timer_stats.timeout.connect(self._maj_barre_etat)
        self._timer_stats.start()
        self._maj_barre_etat()
        self.appliquer_identite()
        if cfg.get("maj.auto"):
            QTimer.singleShot(4000, lambda: self.verifier_mises_a_jour(manuel=False))
        from . import clips
        self._tache_purge = Tache(clips.purger, os.path.join(cfg.dossier_sortie(), "videos"),
                                  cfg.get("clips.conservation")).lancer()
        m = cfg.section("mail")
        if m["actif"] and m["utilisateur"] and not m["mot_de_passe"]:
            self.log_systeme("Mails activés, mais le mot de passe n'est pas mémorisé : ressaisissez-le dans "
                             "Réglages › Alertes et mail.", "erreur")
        if int(__import__("cv2").__version__.split(".")[0]) >= 5:
            self.log_systeme("OpenCV 5 détecté : certaines fonctions ne sont pas encore compatibles. Installez la "
                             "version 4 avec : pip install \"opencv-python>=4.10,<5\"", "erreur")
        if not self.info_appareil:
            t = Tache(vision.info_appareil)
            t.fini.connect(self._info_recue)
            self._tache_info = t.lancer()

    # --- construction --------------------------------------------------------------
    def _construire(self):
        central = QWidget()
        central.setObjectName("fond")
        self.setCentralWidget(central)
        h = QHBoxLayout(central)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        self.barre = QWidget()
        self.barre.setObjectName("panneau")
        bv = QVBoxLayout(self.barre)
        bv.setContentsMargins(10, 16, 10, 14)
        bv.setSpacing(4)
        marque = QHBoxLayout()
        marque.setContentsMargins(8, 0, 0, 0)
        self.logo = Logo(34)
        marque.addWidget(self.logo)
        self.lbl_marque = QLabel(identite(self.cfg)["nom"])
        self.lbl_marque.setStyleSheet(f"font-size: {T.taille + 9}px; font-weight: 700;")
        marque.addWidget(self.lbl_marque)
        marque.addStretch(1)
        bv.addLayout(marque)
        bv.addSpacing(18)
        self.nav = {}
        for cle, lib, ic in PAGES:
            b = BoutonNav(lib, ic)
            b.clicked.connect(lambda _=False, k=cle: self.aller(k))
            bv.addWidget(b)
            self.nav[cle] = b
        bv.addStretch(1)
        self.b_theme = BoutonNav("Thème clair" if T.theme == "sombre" else "Thème sombre", "theme")
        self.b_theme.setCheckable(False)
        self.b_theme.clicked.connect(lambda: self.cfg.set("apparence.theme",
                                                          "clair" if self.cfg.get("apparence.theme") == "sombre" else "sombre"))
        bv.addWidget(self.b_theme)
        b_info = BoutonNav("À propos", "info")
        b_info.setCheckable(False)
        b_info.clicked.connect(lambda: APropos(self).exec())
        bv.addWidget(b_info)
        self.boutons_bas = [self.b_theme, b_info]
        h.addWidget(self.barre)

        zone = QWidget()
        zv = QVBoxLayout(zone)
        zv.setContentsMargins(26, 18, 26, 14)
        self.pile = QStackedWidget()
        self.page_cameras = PageCameras(self)
        self.page_lecteur = PageLecteur(self)
        self.page_personnes = PagePersonnes(self)
        self.page_journal = PageJournal(self)
        self.page_reglages = PageReglages(self)
        self.pages = {"cameras": self.page_cameras, "lecteur": self.page_lecteur, "personnes": self.page_personnes,
                      "journal": self.page_journal, "reglages": self.page_reglages}
        for p in self.pages.values():
            self.pile.addWidget(p)
        zv.addWidget(self.pile)
        h.addWidget(zone, 1)

        sb = QStatusBar()
        self.setStatusBar(sb)
        self.st_appareil = QLabel("Calcul : détection…")
        self.st_niveau = QLabel("")
        self.st_cameras = QLabel("")
        self.st_base = QLabel("")
        self.st_mail = QLabel("")
        self.st_notif = QLabel("")
        self.st_dev = QLabel("DEV")
        self.st_dev.setToolTip("Mode développeur actif")
        self.st_maj = QLabel("")
        self.st_maj.setCursor(Qt.CursorShape.PointingHandCursor)
        self.st_maj.mousePressEvent = lambda _e: self.info_maj and DialogueMaj(self, self.info_maj).exec()
        self.st_maj.hide()
        self.info_maj = None
        for w in (self.st_appareil, self.st_niveau, self.st_cameras, self.st_base):
            sb.addWidget(w)
        sb.addPermanentWidget(self.st_maj)
        sb.addPermanentWidget(self.st_notif)
        sb.addPermanentWidget(self.st_mail)
        sb.addPermanentWidget(self.st_dev)
        self._compacter()

    def _compacter(self):
        compact = bool(self.cfg.get("apparence.barre_compacte"))
        for b in list(self.nav.values()) + self.boutons_bas:
            b.compact = compact
            b.updateGeometry()
        self.lbl_marque.setVisible(not compact)
        self.barre.setFixedWidth(76 if compact else 224)

    def _raccourcis(self):
        for seq, f in (("Ctrl+N", lambda: (self.aller("cameras"), self.page_cameras.nouvelle())),
                       ("Ctrl+O", lambda: (self.aller("lecteur"), self.page_lecteur.ouvrir_fichier())),
                       ("Ctrl+,", lambda: self.aller("reglages")),
                       ("F11", lambda: self.showNormal() if self.isFullScreen() else self.showFullScreen()),
                       ("Ctrl+F", lambda: (self.aller("personnes"), self.page_personnes.recherche.setFocus()))):
            QShortcut(QKeySequence(seq), self, activated=f)
        for i, (cle, _, _) in enumerate(PAGES):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self, activated=lambda k=cle: self.aller(k))
        QShortcut(QKeySequence(Qt.Key.Key_Space), self.page_lecteur, activated=self.page_lecteur.basculer)

    def _geometrie(self):
        g = self.cfg.fenetre
        if g.get("largeur"):
            self.resize(g["largeur"], g["hauteur"])
            if "x" in g:
                self.move(g["x"], g["y"])
        else:
            self.resize(1440, 900)

    # --- navigation ---------------------------------------------------------------------
    def aller(self, cle):
        for k, b in self.nav.items():
            if b.isChecked() != (k == cle):
                b.setChecked(k == cle)
        page = self.pages[cle]
        if self.pile.currentWidget() is not page:
            self.pile.setCurrentWidget(page)
            self.fondu(page)
        if cle == "personnes":
            self.page_personnes.rafraichir(force=True)
        elif cle == "journal":
            self._alertes_non_vues = 0
            self.nav["journal"].compteur = 0
            self.nav["journal"].update()
            self.page_journal.rafraichir()

    def fondu(self, widget):
        """Fondu d'apparition d'une page. Sûr même si l'on change de page très vite."""
        if not T.animations:
            return
        precedente = self._anims_pages.pop(id(widget), None)
        if precedente is not None and shiboken6.isValid(precedente):
            precedente.stop()
        eff = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(eff)  # remplace (et détruit) l'effet précédent
        a = QPropertyAnimation(eff, b"opacity", eff)  # l'animation vit et meurt avec son effet
        a.setDuration(T.ms(220))
        a.setStartValue(0.0)
        a.setEndValue(1.0)
        a.setEasingCurve(QEasingCurve.Type.OutCubic)

        def fin():
            self._anims_pages.pop(id(widget), None)
            if shiboken6.isValid(widget) and shiboken6.isValid(eff) and widget.graphicsEffect() is eff:
                widget.setGraphicsEffect(None)

        a.finished.connect(fin)
        self._anims_pages[id(widget)] = a
        a.start()

    def toast(self, texte, genre="info"):
        self.toasts.montrer(texte, genre)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "toasts"):
            self.toasts.replacer()

    # --- réglages -----------------------------------------------------------------------
    def _reglage_change(self, cle, valeur):
        if cle.startswith("apparence."):
            if cle == "apparence.opacite":
                self.setWindowOpacity(valeur / 100)
            elif cle == "apparence.barre_compacte":
                self._compacter()
            elif not self._application_prevue:  # regrouper les changements rapprochés (curseurs)
                self._application_prevue = True
                QTimer.singleShot(0, self.appliquer_apparence)
        if cle.startswith("detection.") or cle == "systeme.tcp_rtsp":
            self.page_cameras_niveaux()
        if cle in ("detection.moteur", "detection.appareil"):  # nouveau moteur : relancer les caméras en marche
            actives = [p for p in self.page_cameras.pages if p.en_cours()]
            for p in actives:
                p.demarrer()
            if actives:
                self.toast(f"Moteur d'analyse changé : {len(actives)} caméra(s) relancée(s).")
        if cle.startswith(("mail.", "notif.", "telegram.", "whatsapp.", "sms.", "appel.", "ntfy.", "discord.",
                           "webhook.")):
            self._maj_barre_etat()
        if cle.startswith("developpeur."):
            self.appliquer_identite()

    def appliquer_identite(self):
        """Nom, titre, version et logo (personnalisables en mode développeur)."""
        ident = identite(self.cfg)
        regler_logo(ident["logo"])
        self.setWindowTitle(ident["titre"])
        self.lbl_marque.setText(ident["nom"])
        QApplication.setApplicationName(ident["nom"])
        self.setWindowIcon(icone_application())
        self.logo.update()
        dev = bool(self.cfg.get("developpeur.actif"))
        self.st_dev.setVisible(dev and bool(self.cfg.get("developpeur.badge")))
        self.st_dev.setStyleSheet(f"color: {C['attention']}; font-weight: 700; padding: 0 6px;")

    # --- catégories du journal et notifications ------------------------------------------
    def categories_changees(self):
        self.cats_notifier = [c for c in self.base.categories_journal() if c["notifier"]]

    def _notifier(self, e):
        """Décide si un événement part en notification (alerte, liste noire, catégorie marquée)."""
        cfg = self.cfg
        if not cfg.get("notif.actif"):
            return
        quand = cfg.get("notif.quand")
        prioritaire = e.get("prioritaire", False)
        if e["niveau"] == "alerte" and (prioritaire or quand == "alertes"):
            self.notifieur.notifier(e["source"], e["texte"], e.get("jpeg"), prioritaire)
            return
        if not self.cats_notifier or e["niveau"] not in ("action", "alerte"):
            return
        pid = e.get("personne_id")
        fiche = self.base.personne(pid) if pid else None
        action = {"type": e.get("type_action") or ("alerte" if e["niveau"] == "alerte" else ""),
                  "camera": e["source"], "detail": e.get("detail") or e["texte"],
                  "personne": fiche["nom"] if fiche else None, "categorie_personne": fiche["categorie"] if fiche else None}
        from .base import correspond
        noms = [c["nom"] for c in self.cats_notifier if correspond(action, c["regles"])]
        if noms:
            self.notifieur.notifier(e["source"], e["texte"], e.get("jpeg"), False,
                                    {"categories": noms})

    # --- vidéos des passages ------------------------------------------------------------------
    def _video_prete(self, e):
        info = e["video"]
        if info.get("manuel"):
            self.toast(f"{e['source']} · {e['texte']}", "ok")
            return  # vidéo demandée à la main : gardée sur le PC, pas envoyée
        if not self.cfg.get("clips.envoyer"):
            return
        texte = info["texte"]
        if not info.get("compatible"):
            self.log_systeme("Vidéo encodée sans ffmpeg : elle peut être illisible sur téléphone. Relancez "
                             f"{module_config.INSTALLATEUR} pour installer l'encodeur vidéo.", "erreur")
        canaux = self.notifieur.video(e["source"], texte, info["chemin"], info.get("prioritaire", False))
        if self.cfg.get("mail.actif") and self.cfg.get("clips.mail"):
            if info["taille"] > 20_000_000:
                self.log_systeme(f"Vidéo trop lourde pour un mail ({info['taille'] / 1e6:.0f} Mo).", "erreur")
            else:
                try:
                    with open(info["chemin"], "rb") as f:
                        octets = f.read()
                    corps = (f"{texte}\nCaméra : {e['source']}\nDate : {datetime.now():%d/%m/%Y à %H:%M:%S}\n"
                             f"Durée : {info['duree']:.0f} s\n")
                    self.mailer.envoyer(f"[{identite(self.cfg)['nom']}] Vidéo : {texte} - {e['source']}", corps,
                                        [(os.path.basename(info["chemin"]), octets)])
                except OSError as ex:
                    self.log_systeme(f"Vidéo illisible : {ex}", "erreur")
        if canaux:
            self.log_systeme(f"Vidéo envoyée par {', '.join(canaux)}", "info", e["source"])

    # --- mises à jour ----------------------------------------------------------------------
    def verifier_mises_a_jour(self, manuel=False):
        from . import mise_a_jour
        if getattr(self, "_verif_maj", None) is not None:
            return
        if manuel:
            self.toast("Recherche de mise à jour…")

        def fini(info):
            self._verif_maj = None
            self.info_maj = info
            if info is None:
                self.etat_maj = f"À jour (vérifié à {datetime.now():%H:%M})."
                self.st_maj.hide()
                if manuel:
                    self.toast("Flux est à jour.", "ok")
            else:
                self.etat_maj = f"Version {info['libelle']} disponible."
                self.st_maj.setText(f"⬆ Mise à jour {info['libelle']}")
                self.st_maj.setStyleSheet(f"color: {C['accent_vif']}; font-weight: 600; padding: 0 6px;")
                self.st_maj.show()
                if manuel or info["version"] != self.cfg.get("maj.ignoree"):
                    DialogueMaj(self, info).exec()
            lbl = getattr(self.page_reglages, "lbl_maj", None)
            if lbl is not None:
                try:
                    lbl.setText(self.etat_maj)
                except RuntimeError:
                    pass

        def echec(msg):
            self._verif_maj = None
            self.etat_maj = f"Vérification impossible : {msg}"
            if manuel:
                self.toast(f"Mises à jour : {msg}", "erreur")

        if not mise_a_jour.depot(self.cfg):
            if manuel:
                self.toast("Indiquez le dépôt GitHub dans Réglages › Mises à jour.", "erreur")
                self.aller("reglages")
                self.page_reglages.aller("maj")
            return
        t = Tache(mise_a_jour.verifier, self.cfg)
        t.fini.connect(fini)
        t.echec.connect(echec)
        self._verif_maj = t.lancer()

    def redemarrer(self):
        import subprocess
        self.arret_propre()
        script = os.path.join(RACINE, "flux.py")
        executable = sys.executable
        if os.name == "nt" and executable.lower().endswith("python.exe"):
            pythonw = executable[:-10] + "pythonw.exe"
            executable = pythonw if os.path.isfile(pythonw) else executable
        subprocess.Popen([executable, script], cwd=RACINE, close_fds=True)
        QApplication.quit()

    def appliquer_apparence(self):
        self._application_prevue = False
        theme.appliquer(self.cfg)
        self.toasts.restyler()
        self.b_theme.setText("Thème clair" if T.theme == "sombre" else "Thème sombre")
        self.lbl_marque.setStyleSheet(f"font-size: {T.taille + 9}px; font-weight: 700;")
        self.page_personnes.nom.setStyleSheet(f"font-size: {T.taille + 6}px; font-weight: 600;")
        self.page_personnes.rafraichir(force=True)
        for w in self.findChildren(QWidget):
            w.updateGeometry()

    def page_cameras_niveaux(self):
        for p in self.page_cameras.pages:
            p.maj_niveau()
        self.page_lecteur.maj_niveau()
        self._maj_barre_etat()

    def _info_recue(self, info):
        self.info_appareil = info
        self._maj_barre_etat()

    def _maj_barre_etat(self):
        i = self.info_appareil
        if i:
            from .vision import NOMS_MOTEURS, moteur_effectif
            app = "cuda" if i.get("cuda") and self.cfg.get("detection.appareil") not in ("cpu", "intel_gpu") else "cpu"
            moteur = NOMS_MOTEURS.get(moteur_effectif(self.cfg, app), "PyTorch")
            nom = "Puce graphique Intel" if (app == "cpu" and moteur == "OpenVINO"
                                             and self.cfg.get("detection.appareil") == "intel_gpu") else i["nom"]
            self.st_appareil.setText(f"Calcul : {nom} · {moteur}" + ("" if i.get("cuda") or i.get("mps") else
                                                                    " (pas de carte NVIDIA)"))
        _, _, _, lib = niveau_effectif(self.cfg.get("detection.niveau"), self.cfg)
        self.st_niveau.setText(f"Niveau : {lib}")
        actives = sum(1 for p in self.page_cameras.pages if p.en_cours())
        self.st_cameras.setText(f"{actives}/{len(self.page_cameras.pages)} caméra(s) active(s)")
        s = self.base.statistiques()
        self.st_base.setText(f"Base : {s['personnes']} personnes · {s['aujourdhui']} actions aujourd'hui")
        self.st_mail.setText(f"Mails → {self.cfg.get('mail.destinataire') or '(sans destinataire)'}"
                             if self.cfg.get("mail.actif") else "Mails désactivés")
        from .notifications import NOMS_CANAUX, canaux_actifs
        canaux = canaux_actifs(self.cfg) if self.cfg.get("notif.actif") else []
        self.st_notif.setText(("Notifications : " + ", ".join(NOMS_CANAUX[c] for c in canaux)) if canaux else "")

    # --- journal et mails ------------------------------------------------------------------
    def log_systeme(self, texte, niveau="info", source="Système"):
        """Utilisable depuis n'importe quel fil."""
        self.evenements.put({"heure": datetime.now().strftime("%H:%M:%S"), "source": source, "texte": texte,
                             "niveau": niveau, "chemin": None, "jpeg": None})

    def _journaliser(self, e):
        texte = e["texte"] + (f" (photo : {os.path.basename(e['chemin'])})" if e.get("chemin") else "")
        self.page_journal.ajouter(e["heure"], e["source"], texte, e["niveau"])
        if e["source"] == "Système" and texte.startswith(PREFIXE_MAIL_OK):
            return
        lignes = self.page_journal.lignes
        lignes.append(f"[{datetime.now():%d/%m %H:%M:%S}] [{e['source']}] {texte}")
        if len(lignes) > 20000:
            del lignes[:10000]
            self.index_journal_envoye = max(0, self.index_journal_envoye - 10000)
        try:
            dossier = self.cfg.dossier_sortie()
            os.makedirs(dossier, exist_ok=True)
            with open(os.path.join(dossier, "journal.log"), "a", encoding="utf-8") as f:
                f.write(lignes[-1] + "\n")
        except OSError:
            pass

    def envoyer_journal(self, auto):
        lignes = self.page_journal.lignes[self.index_journal_envoye:]
        if not lignes:
            if not auto:
                self.toast("Journal : rien de nouveau à envoyer.")
            return
        corps = "\n".join(lignes[-1000:])
        if len(lignes) > 1000:
            corps = f"({len(lignes) - 1000} lignes plus anciennes non incluses)\n" + corps
        fin = len(self.page_journal.lignes)

        def marquer():
            self.index_journal_envoye = max(self.index_journal_envoye, fin)

        self.mailer.envoyer(f"[{identite(self.cfg)['nom']}] Journal ({len(lignes)} ligne(s))", corps, au_succes=marquer)
        if not auto:
            self.toast("Envoi du journal en cours…")

    def _alerte_mail(self, source, texte, jpeg, prioritaire=False):
        if not self.cfg.get("mail.actif"):
            return
        maintenant = time.time()
        if prioritaire or maintenant - self.dernier_mail.get(source, 0) >= self.cfg.get("mail.delai") * 60:
            ignorees = self.supprimees.pop(source, 0)
            corps = f"{texte}\nCaméra : {source}\nDate : {datetime.now():%d/%m/%Y à %H:%M:%S}\n"
            if ignorees:
                corps += (f"\n{ignorees} autre(s) alerte(s) pendant le délai d'attente "
                          f"({self.cfg.get('mail.delai'):g} min) n'ont pas déclenché de mail.\n")
            pieces = [(f"{slug(source)}_{datetime.now():%H%M%S}.jpg", jpeg)] if jpeg and self.cfg.get("mail.photo") else []
            self.mailer.envoyer(f"[{identite(self.cfg)['nom']}] {texte} - {source}", corps, pieces)
            self.dernier_mail[source] = maintenant
        else:
            self.supprimees[source] = self.supprimees.get(source, 0) + 1

    # --- boucle d'affichage -------------------------------------------------------------------
    def _rafraichir(self):
        try:
            self._cycle()
        except Exception as e:  # noqa: BLE001  — une erreur ne doit jamais figer l'interface
            if str(e) != self._derniere_erreur:
                self._derniere_erreur = str(e)
                self.log_systeme(f"Erreur interne : {e}", "erreur")

    def _cycle(self):
        for _ in range(200):
            try:
                e = self.evenements.get_nowait()
            except queue.Empty:
                break
            self._journaliser(e)
            try:
                self._notifier(e)
            except Exception as ex:  # noqa: BLE001
                self.log_systeme(f"Notification : {ex}", "erreur")
            if e["niveau"] == "alerte":
                self.toast(f"{e['source']} · {e['texte']}", "alerte")
                self._alerte_mail(e["source"], e["texte"], e.get("jpeg"), e.get("prioritaire", False))
                if self.pile.currentWidget() is not self.page_journal:
                    self._alertes_non_vues += 1
                    self.nav["journal"].compteur = self._alertes_non_vues
                    self.nav["journal"].update()
            elif e["niveau"] == "video":
                self._video_prete(e)
            elif e["niveau"] == "erreur" or (e["niveau"] == "ok" and not e["texte"].startswith(PREFIXE_MAIL_OK)):
                self.toast(e["texte"] if e["source"] == "Système" else f"{e['source']} · {e['texte']}", e["niveau"])

        page = self.pile.currentWidget()
        etats = self.page_cameras.mise_a_jour(page is self.page_cameras)
        self.page_lecteur.mise_a_jour(page is self.page_lecteur)
        self.logo.animer(any(x in ("direct", "alerte") for x in etats))
        if page is self.page_personnes:
            self.page_personnes.rafraichir()

        intervalle = self.cfg.get("mail.journal_auto") * 60
        if self.cfg.get("mail.actif") and intervalle > 0 and time.time() - self.dernier_envoi_journal >= intervalle:
            self.dernier_envoi_journal = time.time()
            self.envoyer_journal(auto=True)

    # --- fermeture ------------------------------------------------------------------------------
    def closeEvent(self, e):
        self.arret_propre()
        e.accept()

    def arret_propre(self):
        self._timer.stop()
        self._timer_stats.stop()
        if not self.isFullScreen() and not self.isMaximized():
            self.cfg.fenetre = {"largeur": self.width(), "hauteur": self.height(), "x": self.x(), "y": self.y()}
        if self.cameras_au_redemarrage:  # config.json modifié à la main : garder sa liste de caméras
            flux, groupes = list(self.cfg.flux), list(self.cfg.groupes)
            self.page_cameras.sauver()
            self.cfg.flux, self.cfg.groupes = flux, groupes
        else:
            self.page_cameras.sauver()  # avant l'arrêt, pour mémoriser les caméras actives
        self.page_lecteur.arreter()
        self.page_cameras.tout_arreter()
        self.cfg.sauver()


def main():
    cfg = Config()
    if os.name == "nt":  # icône correcte dans la barre des tâches Windows
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Flux.Surveillance.2")
        except Exception:  # noqa: BLE001
            pass
    app = QApplication(sys.argv)
    ident = identite(cfg)
    regler_logo(ident["logo"])
    app.setApplicationName(ident["nom"])
    app.setApplicationVersion(module_config.APP_VERSION)
    app.setStyle("Fusion")
    app.setWindowIcon(icone_application())
    theme.appliquer(cfg, app)
    garde = {}

    def ouvrir(base, info):
        fen = FenetrePrincipale(cfg, base, info)
        garde["fenetre"] = fen
        fen.show()
        return fen

    if cfg.get("apparence.ecran_demarrage"):
        ecran = EcranDemarrage(ident)
        ecran.show()
        ch = Chargement()
        ch.etape.connect(ecran.etape)

        def termine(resultat):
            base, info = resultat
            fen = ouvrir(base, info)
            fen.raise_()
            ecran.disparaitre()

        def echec(msg):
            ecran.etape(f"Erreur : {msg}", 1.0)
            QTimer.singleShot(2500, lambda: ouvrir(Base(FICHIER_BASE), {}))

        t = Tache(charger, ch.etape.emit, cfg)
        t.fini.connect(lambda r: QTimer.singleShot(150, lambda: termine(r)))
        t.echec.connect(echec)
        garde["tache"], garde["chargement"], garde["ecran"] = t.lancer(), ch, ecran
    else:
        ouvrir(Base(FICHIER_BASE), {})
    sys.exit(app.exec())
