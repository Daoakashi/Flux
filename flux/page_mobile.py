"""Page FluxLite : relie les téléphones Android (application FluxLite) à ce PC.

À gauche : le serveur (marche/arrêt, adresses, clé du serveur et QR code d'appairage).
À droite : les comptes des clients (validation, entreprise, suspension, mot de passe, suppression) et les entreprises
(caméras visibles par chacune).
"""

import os
import secrets
import string
import time
from datetime import datetime

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout,
                               QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
                               QMessageBox, QScrollArea, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)

from . import mobile_serveur as ms
from .config import RACINE
from .theme import C, T, couleur
from .widgets import Bouton, Interrupteur, etiquette

DOSSIER = os.path.join(RACINE, "fluxlite")  # protégé : jamais remplacé par les mises à jour (clé du serveur)
COULEURS_STATUT = {"attente": "attention", "actif": "succes", "suspendu": "danger"}


def date_courte(t):
    if not t:
        return "—"
    d = datetime.fromtimestamp(t)
    return d.strftime("%H:%M") if d.date() == datetime.now().date() else d.strftime("%d/%m/%Y %H:%M")


def mot_de_passe_provisoire():
    alphabet = string.ascii_letters + string.digits
    while True:
        m = "".join(secrets.choice(alphabet) for _ in range(12))
        if any(c.isdigit() for c in m) and any(c.isalpha() for c in m):
            return m


# ---------------------------------------------------------------------------
# Caméras vues par le serveur
# ---------------------------------------------------------------------------
class FournisseurCameras(ms.FournisseurVide):
    """Instantané des caméras, mis à jour par le fil de l'interface et lu par les fils du serveur."""

    def __init__(self, page_cameras):
        self.pc = page_cameras
        self._liste, self._detecteurs = [], {}
        self._t = 0.0

    def publier(self, force=False):
        """Appelée par l'interface (fil principal) : copie l'état des caméras pour le serveur."""
        if not force and time.time() - self._t < 0.25:
            return
        self._t = time.time()
        liste, detecteurs = [], {}
        for p in self.pc.pages:
            d = p.detecteur
            actif = p.en_cours()
            etat, personnes, fps, res = "arret", 0, 0.0, None
            if d is not None and actif:
                ann = d.annotations or {}
                personnes = len(ann.get("personnes", []))
                fps, res = d.fps, d.resolution
                etat = "chargement" if (d.charge or d.derniere_image is None) else ("alerte" if personnes else "direct")
                detecteurs[p.nom] = d
            liste.append({"nom": p.nom, "etat": etat, "personnes": personnes, "fps": fps, "resolution": res})
        self._liste, self._detecteurs = liste, detecteurs  # remplacements atomiques

    def cameras(self):
        return list(self._liste)

    def image(self, nom):
        d = self._detecteurs.get(nom)
        if d is None:
            return None
        with d.lock:
            img, ann = d.derniere_image, d.annotations
        return img, ann


# ---------------------------------------------------------------------------
# QR code d'appairage
# ---------------------------------------------------------------------------
class CodeQR(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.matrice = None
        self.setFixedSize(188, 188)

    def definir(self, texte):
        try:
            import segno
            q = segno.make(texte, error="m", micro=False)
            self.matrice = [list(r) for r in q.matrix]
        except Exception:  # noqa: BLE001  — segno absent : on affiche seulement la clé en texte
            self.matrice = None
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        r = QRectF(self.rect())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        p.drawRoundedRect(r, T.rayon, T.rayon)
        if not self.matrice:
            p.setPen(couleur("texte3"))
            p.drawText(r.adjusted(12, 12, -12, -12), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                       "QR code indisponible (module « segno » manquant). Saisissez la clé à la main.")
            return
        n = len(self.matrice)
        marge = 4
        cote = (min(r.width(), r.height()) - 2 * 10) / (n + 2 * marge)
        x0 = r.center().x() - cote * (n + 2 * marge) / 2 + cote * marge
        y0 = r.center().y() - cote * (n + 2 * marge) / 2 + cote * marge
        p.setBrush(QColor("#0A1220"))
        for y, ligne in enumerate(self.matrice):
            for x, v in enumerate(ligne):
                if v:
                    p.drawRect(QRectF(x0 + x * cote, y0 + y * cote, cote + 0.4, cote + 0.4))


# ---------------------------------------------------------------------------
# Dialogues
# ---------------------------------------------------------------------------
class DialogueCompte(QDialog):
    """Création d'un compte par le responsable (sans passer par le téléphone)."""

    def __init__(self, parent, entreprises):
        super().__init__(parent)
        self.setWindowTitle("Nouveau compte FluxLite")
        self.setMinimumWidth(420)
        v = QVBoxLayout(self)
        f = QFormLayout()
        self.prenom, self.nom, self.mail = QLineEdit(), QLineEdit(), QLineEdit()
        self.entreprise = QComboBox()
        self.entreprise.addItem("Aucune (aucune caméra visible)", None)
        for e in entreprises:
            self.entreprise.addItem(e["nom"], e["id"])
        self.mdp = QLineEdit(mot_de_passe_provisoire())
        f.addRow("Prénom", self.prenom)
        f.addRow("Nom", self.nom)
        f.addRow("Mail", self.mail)
        f.addRow("Entreprise", self.entreprise)
        f.addRow("Mot de passe provisoire", self.mdp)
        v.addLayout(f)
        v.addWidget(etiquette("Communiquez ce mot de passe à la personne : elle pourra le changer depuis l'onglet "
                              "Compte de FluxLite. Le compte est actif tout de suite."))
        self.lbl = etiquette("", "aide")
        self.lbl.setStyleSheet(f"color: {C['danger']};")
        v.addWidget(self.lbl)
        h = QHBoxLayout()
        h.addStretch(1)
        b0 = Bouton("Annuler")
        b0.clicked.connect(self.reject)
        b1 = Bouton("Créer le compte", "primaire")
        b1.clicked.connect(self._ok)
        h.addWidget(b0)
        h.addWidget(b1)
        v.addLayout(h)
        self.resultat = None

    def _ok(self):
        mail, mdp = self.mail.text().strip(), self.mdp.text()
        if not self.prenom.text().strip() or not self.nom.text().strip():
            self.lbl.setText("Indiquez le prénom et le nom.")
        elif not ms.RE_MAIL.match(mail):
            self.lbl.setText("Adresse mail invalide.")
        elif ms.mot_de_passe_valide(mdp):
            self.lbl.setText(ms.mot_de_passe_valide(mdp))
        else:
            self.resultat = (mail, mdp, self.nom.text().strip(), self.prenom.text().strip(),
                             self.entreprise.currentData())
            self.accept()


class DialogueValidation(QDialog):
    def __init__(self, parent, compte, entreprises):
        super().__init__(parent)
        self.setWindowTitle("Valider le compte")
        self.setMinimumWidth(420)
        v = QVBoxLayout(self)
        t = QLabel(f"{compte['prenom']} {compte['nom']}")
        t.setObjectName("titre")
        v.addWidget(t)
        v.addWidget(etiquette(f"{compte['mail']}"
                              f"{' · société indiquée : ' + compte['societe'] if compte['societe'] else ''}"
                              f"\nInscrit le {date_courte(compte['cree_le'])}"
                              f"{' depuis ' + compte['appareil'] if compte.get('appareil') else ''}", "soustitre"))
        v.addSpacing(8)
        v.addWidget(QLabel("Rattacher à l'entreprise :"))
        self.combo = QComboBox()
        for e in entreprises:
            self.combo.addItem(e["nom"], e["id"])
        self.combo.addItem("➕ Nouvelle entreprise…", "nouvelle")
        if compte["societe"]:
            i = self.combo.findText(compte["societe"], Qt.MatchFlag.MatchFixedString)
            if i >= 0:
                self.combo.setCurrentIndex(i)
            elif not entreprises:
                self.combo.setCurrentIndex(self.combo.count() - 1)
        v.addWidget(self.combo)
        self.nouvelle = QLineEdit(compte["societe"])
        self.nouvelle.setPlaceholderText("Nom de la nouvelle entreprise")
        v.addWidget(self.nouvelle)
        self.combo.currentIndexChanged.connect(lambda *_: self.nouvelle.setVisible(self.combo.currentData() == "nouvelle"))
        self.nouvelle.setVisible(self.combo.currentData() == "nouvelle")
        v.addWidget(etiquette("Le compte verra seulement les caméras attribuées à cette entreprise (onglet "
                              "Entreprises)."))
        h = QHBoxLayout()
        h.addStretch(1)
        b0 = Bouton("Annuler")
        b0.clicked.connect(self.reject)
        b1 = Bouton("Valider le compte", "primaire")
        b1.clicked.connect(self.accept)
        h.addWidget(b0)
        h.addWidget(b1)
        v.addLayout(h)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
class PageFluxLite(QWidget):
    def __init__(self, fen):
        super().__init__()
        self.fen, self.cfg = fen, fen.cfg
        self.serveur = None
        self.erreur_init = ""
        self.fournisseur = FournisseurCameras(fen.page_cameras)
        self._entreprise_courante = None
        self._maj_bloquee = False
        self._construire()
        self._timer = QTimer(self)
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self._rafraichir_etat)
        self._timer.start()

    # --- serveur ---------------------------------------------------------------------
    def initialiser(self):
        """Crée l'identité (clé, certificat) au premier lancement et démarre le serveur s'il est activé."""
        try:
            from .config import APP_VERSION
            from .sources import dessiner
            self.serveur = ms.ServeurFluxLite(DOSSIER, self.cfg, self.fournisseur, self._rappel, dessiner,
                                              APP_VERSION)
        except Exception as e:  # noqa: BLE001
            self.erreur_init = str(e)
            self.fen.log_systeme(f"FluxLite indisponible : {e}", "erreur")
            self._rafraichir_etat()
            return
        self.fournisseur.publier(force=True)
        if self.cfg.get("fluxlite.actif"):
            self.demarrer()
        self._rafraichir_identite()
        self.recharger()

    def _rappel(self, texte, niveau="info"):
        """Depuis les fils du serveur : vers le journal de Flux (et une notification à l'écran)."""
        if niveau == "alerte_compte":
            self.fen.log_systeme(texte, "ok", "FluxLite")
            QTimer.singleShot(0, self.recharger)
        else:
            self.fen.log_systeme(texte, niveau if niveau in ("info", "ok", "erreur") else "info", "FluxLite")

    def demarrer(self):
        if self.serveur is None:
            return
        try:
            port = self.serveur.demarrer()
            self.fen.log_systeme(f"Serveur FluxLite démarré (port {port}).", "info", "FluxLite")
        except ms.ErreurServeur as e:
            self.fen.log_systeme(str(e), "erreur", "FluxLite")
        self._rafraichir_etat()
        self._rafraichir_identite()

    def arreter(self):
        if self.serveur is not None and self.serveur.en_marche():
            self.serveur.arreter()
            self.fen.log_systeme("Serveur FluxLite arrêté.", "info", "FluxLite")
        self._rafraichir_etat()

    def fermer(self):
        if self.serveur is not None:
            self.serveur.fermer()

    def reglage_change(self, cle):
        if self.serveur is None or not cle.startswith("fluxlite."):
            return
        if cle == "fluxlite.actif":
            self.demarrer() if self.cfg.get(cle) else self.arreter()
            self.inter.blockSignals(True)
            self.inter.regler(bool(self.cfg.get(cle)))
            self.inter.blockSignals(False)
        elif cle == "fluxlite.port" and self.serveur.en_marche():
            self.demarrer()
        elif cle in ("fluxlite.nom",):
            self._rafraichir_identite()

    # --- appelé à chaque cycle de l'interface -----------------------------------------------
    def evenement(self, e):
        if self.serveur is not None:
            self.serveur.evenement(e)

    def cycle(self):
        if self.serveur is not None and self.serveur.en_marche():
            self.fournisseur.publier()

    def camera_renommee(self, ancien, nouveau):
        if self.serveur is not None:
            self.serveur.comptes.camera_renommee(ancien, nouveau)
            self.recharger()

    # --- construction -------------------------------------------------------------------
    def _construire(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        haut = QHBoxLayout()
        t = QLabel("FluxLite")
        t.setObjectName("titre_page")
        haut.addWidget(t)
        haut.addSpacing(12)
        self.lbl_etat = QLabel("")
        haut.addWidget(self.lbl_etat)
        haut.addStretch(1)
        v.addLayout(haut)
        v.addWidget(etiquette("Vos clients voient les caméras et reçoivent les alertes sur leur téléphone Android, "
                              "avec l'application FluxLite. Les échanges sont chiffrés de bout en bout et liés à la "
                              "clé de ce PC.", "soustitre"))

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)

        # --- colonne serveur -------------------------------------------------
        gauche = QWidget()
        gauche.setObjectName("carte")
        gv = QVBoxLayout(gauche)
        gv.setContentsMargins(18, 16, 18, 16)
        gv.setSpacing(8)
        ligne = QHBoxLayout()
        lab = QLabel("Serveur FluxLite")
        lab.setObjectName("titre")
        ligne.addWidget(lab, 1)
        self.inter = Interrupteur()
        self.inter.regler(bool(self.cfg.get("fluxlite.actif")))
        self.inter.toggled.connect(lambda etat: self.cfg.set("fluxlite.actif", bool(etat)))
        ligne.addWidget(self.inter)
        gv.addLayout(ligne)
        self.lbl_serveur = etiquette("", "aide")
        gv.addWidget(self.lbl_serveur)
        gv.addSpacing(4)
        s = QLabel("CLÉ DU SERVEUR")
        s.setObjectName("section")
        gv.addWidget(s)
        self.lbl_cle = QLabel("—")
        f = QFont("Consolas")
        f.setStyleHint(QFont.StyleHint.Monospace)
        f.setPixelSize(T.taille + 4)
        f.setBold(True)
        self.lbl_cle.setFont(f)
        self.lbl_cle.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_cle.setWordWrap(True)
        self.lbl_cle.setStyleSheet(f"color: {C['accent_vif']}; letter-spacing: 1px;")
        gv.addWidget(self.lbl_cle)
        gv.addWidget(etiquette("Créée une seule fois sur ce PC et conservée par les mises à jour. Le téléphone la "
                               "vérifie à chaque connexion : un autre ordinateur ne peut pas se faire passer pour "
                               "celui-ci."))
        hb = QHBoxLayout()
        b = Bouton("Copier la clé")
        b.clicked.connect(lambda: self._copier(self.serveur.identite.cle_affichee if self.serveur else ""))
        hb.addWidget(b)
        b = Bouton("Copier l'adresse")
        b.clicked.connect(lambda: self._copier(self._adresse()))
        hb.addWidget(b)
        hb.addStretch(1)
        gv.addLayout(hb)
        gv.addSpacing(6)
        s = QLabel("APPAIRER UN TÉLÉPHONE")
        s.setObjectName("section")
        gv.addWidget(s)
        hq = QHBoxLayout()
        self.qr = CodeQR()
        hq.addWidget(self.qr)
        hq.addSpacing(8)
        self.lbl_adresses = etiquette("", "aide")
        hq.addWidget(self.lbl_adresses, 1)
        gv.addLayout(hq)
        gv.addWidget(etiquette("Dans FluxLite, touchez « Scanner le QR code ». Hors de votre "
                               "réseau (4G, autre site), ouvrez le port dans votre box ou utilisez un VPN "
                               "(Tailscale, WireGuard), puis saisissez l'adresse publique."))
        gv.addStretch(1)
        b = Bouton("Réglages FluxLite…", "fantome", "reglages")
        b.clicked.connect(lambda: (self.fen.aller("reglages"), self.fen.page_reglages.aller("fluxlite")))
        gv.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
        defil = QScrollArea()
        defil.setWidgetResizable(True)
        defil.setFrameShape(QScrollArea.Shape.NoFrame)
        defil.setWidget(gauche)
        defil.setMinimumWidth(360)
        defil.setMaximumWidth(460)
        split.addWidget(defil)

        # --- colonne comptes / entreprises ------------------------------------------
        self.onglets = QTabWidget()
        self.onglets.addTab(self._onglet_comptes(), "Comptes")
        self.onglets.addTab(self._onglet_entreprises(), "Entreprises")
        split.addWidget(self.onglets)
        split.setStretchFactor(1, 1)
        v.addWidget(split, 1)

    def _onglet_comptes(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 8, 0, 0)
        h = QHBoxLayout()
        self.filtre = QLineEdit()
        self.filtre.setPlaceholderText("Rechercher un nom, un mail, une entreprise…")
        self.filtre.textChanged.connect(self._remplir_comptes)
        h.addWidget(self.filtre, 1)
        self.b_valider = Bouton("Valider", "primaire")
        self.b_valider.clicked.connect(self._valider)
        h.addWidget(self.b_valider)
        b = Bouton("Nouveau compte", "discret", "plus")
        b.clicked.connect(self._nouveau_compte)
        h.addWidget(b)
        v.addLayout(h)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["Statut", "Prénom", "Nom", "Mail", "Entreprise", "Société indiquée",
                                              "Dernière connexion", "Appareil"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu_compte)
        self.table.cellDoubleClicked.connect(lambda *_: self._menu_compte(None))
        self.table.itemSelectionChanged.connect(self._selection_compte)
        v.addWidget(self.table, 1)
        self.lbl_comptes = etiquette("Clic droit sur un compte : valider, changer d'entreprise, suspendre, "
                                     "réinitialiser le mot de passe, déconnecter, supprimer.")
        v.addWidget(self.lbl_comptes)
        return w

    def _onglet_entreprises(self):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 8, 0, 0)
        g = QVBoxLayout()
        self.liste_ent = QListWidget()
        self.liste_ent.setMaximumWidth(280)
        self.liste_ent.currentItemChanged.connect(lambda *_: self._entreprise_choisie())
        g.addWidget(self.liste_ent, 1)
        hb = QHBoxLayout()
        b = Bouton("Nouvelle", "primaire", "plus")
        b.clicked.connect(self._nouvelle_entreprise)
        hb.addWidget(b)
        self.b_ren_ent = Bouton("Renommer")
        self.b_ren_ent.clicked.connect(self._renommer_entreprise)
        hb.addWidget(self.b_ren_ent)
        self.b_sup_ent = Bouton("Supprimer", "danger")
        self.b_sup_ent.clicked.connect(self._supprimer_entreprise)
        hb.addWidget(self.b_sup_ent)
        g.addLayout(hb)
        h.addLayout(g)
        d = QVBoxLayout()
        self.lbl_ent = QLabel("Choisissez une entreprise")
        self.lbl_ent.setObjectName("titre")
        d.addWidget(self.lbl_ent)
        self.lbl_ent_info = etiquette("", "soustitre")
        d.addWidget(self.lbl_ent_info)
        self.chk_toutes = QCheckBox("Toutes les caméras, y compris celles ajoutées plus tard")
        self.chk_toutes.toggled.connect(self._cameras_entreprise_changees)
        d.addWidget(self.chk_toutes)
        s = QLabel("CAMÉRAS VISIBLES")
        s.setObjectName("section")
        d.addWidget(s)
        self.liste_cam = QListWidget()
        self.liste_cam.itemChanged.connect(lambda *_: self._cameras_entreprise_changees())
        d.addWidget(self.liste_cam, 1)
        d.addWidget(etiquette("Les comptes de l'entreprise voient ces caméras et reçoivent leurs alertes. Le "
                              "changement s'applique tout de suite, y compris aux vidéos déjà ouvertes."))
        h.addLayout(d, 1)
        return w

    # --- état ------------------------------------------------------------------------------
    def _adresse(self):
        port = self.cfg.get("fluxlite.port")
        return f"{ms.adresses_locales()[0]}:{port}"

    def _rafraichir_identite(self):
        if self.serveur is None:
            return
        port = self.cfg.get("fluxlite.port")
        adresses = ms.adresses_locales()
        self.lbl_cle.setText(self.serveur.identite.cle_affichee)
        self.qr.definir(self.serveur.identite.lien_appairage(adresses, port, self.serveur.nom))
        self.lbl_adresses.setText(f"Nom : {self.serveur.nom}\n\nAdresse sur ce réseau :\n"
                                  + "\n".join(f"{a}:{port}" for a in adresses))

    def _rafraichir_etat(self):
        if self.serveur is None:
            texte, c = (f"Indisponible : {self.erreur_init}" if self.erreur_init else "Préparation…"), "danger"
        elif self.serveur.en_marche():
            n = sum(1 for t in self.serveur.connectes.values() if time.time() - t < 120)
            flux = sum(self.serveur.flux_ouverts.values())
            texte = f"● En marche · {n} téléphone(s) actif(s)" + (f" · {flux} vidéo(s) ouverte(s)" if flux else "")
            c = "succes"
        elif self.serveur.erreur:
            texte, c = f"● Erreur : {self.serveur.erreur}", "danger"
        else:
            texte, c = "● Arrêté", "texte3"
        self.lbl_etat.setText(texte)
        self.lbl_etat.setStyleSheet(f"color: {C[c]}; font-weight: 600;")
        self.lbl_serveur.setText("Les téléphones peuvent se connecter." if self.serveur and self.serveur.en_marche()
                                 else "Activez le serveur pour que les téléphones puissent se connecter.")
        if self.isVisible() and self.serveur is not None and not self.table.hasFocus():
            self._remplir_comptes()

    def showEvent(self, e):
        super().showEvent(e)
        self.recharger()

    def recharger(self):
        if self.serveur is None:
            return
        self._remplir_comptes()
        self._remplir_entreprises()
        if hasattr(self.fen, "maj_badge_fluxlite") and hasattr(self.fen, "nav"):
            self.fen.maj_badge_fluxlite()

    def nb_en_attente(self):
        if self.serveur is None:
            return 0
        return sum(1 for c in self.serveur.comptes.comptes() if c["statut"] == "attente")

    # --- comptes ---------------------------------------------------------------------------
    def _remplir_comptes(self):
        if self.serveur is None:
            return
        selection = self._compte_selectionne()
        filtre = self.filtre.text().strip().lower()
        comptes = self.serveur.comptes.comptes()
        actifs = {cid for cid, t in self.serveur.connectes.items() if time.time() - t < 120}
        lignes = [c for c in comptes if not filtre or filtre in " ".join(
            str(c.get(k) or "") for k in ("prenom", "nom", "mail", "entreprise", "societe")).lower()]
        self.table.setRowCount(len(lignes))
        for i, c in enumerate(lignes):
            statut = ms.STATUTS.get(c["statut"], c["statut"]) + (" · en ligne" if c["id"] in actifs else "")
            valeurs = [statut, c["prenom"], c["nom"], c["mail"], c["entreprise"] or "—", c["societe"] or "—",
                       date_courte(c["derniere_connexion"]),
                       " · ".join(x for x in (c.get("appareil"), c.get("version_app")) if x) or "—"]
            for j, val in enumerate(valeurs):
                it = QTableWidgetItem(val)
                it.setData(Qt.ItemDataRole.UserRole, c["id"])
                if j == 0:
                    it.setForeground(QColor(C[COULEURS_STATUT.get(c["statut"], "texte2")]))
                self.table.setItem(i, j, it)
            if c["id"] == selection:
                self.table.selectRow(i)
        attente = sum(1 for c in comptes if c["statut"] == "attente")
        self.onglets.setTabText(0, f"Comptes ({len(comptes)})" + (f" · {attente} à valider" if attente else ""))
        self._selection_compte()

    def _compte_selectionne(self):
        r = self.table.currentRow()
        it = self.table.item(r, 0) if r >= 0 else None
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def _selection_compte(self):
        cid = self._compte_selectionne()
        c = self.serveur.comptes.compte(cid) if (cid and self.serveur) else None
        self.b_valider.setEnabled(bool(c and c["statut"] == "attente"))

    def _menu_compte(self, pos):
        cid = self._compte_selectionne()
        if cid is None or self.serveur is None:
            return
        c = self.serveur.comptes.compte(cid)
        m = QMenu(self)
        if c["statut"] == "attente":
            m.addAction("Valider le compte…", self._valider)
        sous = m.addMenu("Entreprise")
        for e in self.serveur.comptes.entreprises():
            a = sous.addAction(e["nom"], lambda eid=e["id"]: self._changer_entreprise(cid, eid))
            a.setCheckable(True)
            a.setChecked(e["id"] == c["entreprise_id"])
        sous.addSeparator()
        sous.addAction("Aucune", lambda: self._changer_entreprise(cid, None))
        if c["statut"] == "actif":
            m.addAction("Suspendre le compte", lambda: self._statut(cid, "suspendu"))
        elif c["statut"] == "suspendu":
            m.addAction("Réactiver le compte", lambda: self._statut(cid, "actif"))
        m.addSeparator()
        m.addAction("Réinitialiser le mot de passe…", lambda: self._reinitialiser(c))
        m.addAction("Déconnecter tous ses appareils", lambda: self._deconnecter(c))
        m.addAction("Détails…", lambda: self._details(c))
        m.addSeparator()
        m.addAction("Supprimer le compte…", lambda: self._supprimer_compte(c))
        m.exec(self.table.viewport().mapToGlobal(pos) if pos is not None else self.cursor().pos())

    def _valider(self):
        cid = self._compte_selectionne()
        if cid is None:
            return
        c = self.serveur.comptes.compte(cid)
        d = DialogueValidation(self, c, self.serveur.comptes.entreprises())
        if d.exec() != QDialog.DialogCode.Accepted:
            return
        eid = d.combo.currentData()
        try:
            if eid == "nouvelle":
                eid = self.serveur.comptes.creer_entreprise(d.nouvelle.text())
            self.serveur.comptes.modifier_compte(cid, statut="actif", entreprise_id=eid)
        except ms.ErreurServeur as e:
            self.fen.toast(str(e), "erreur")
            return
        self.fen.toast(f"Compte de {c['prenom']} {c['nom']} validé.", "ok")
        self.recharger()
        if eid and not self.serveur.comptes.entreprise(eid)["cameras"] and \
                not self.serveur.comptes.entreprise(eid)["toutes"]:
            self.fen.toast("Cette entreprise n'a encore aucune caméra : choisissez-les dans l'onglet Entreprises.")

    def _changer_entreprise(self, cid, eid):
        self.serveur.comptes.modifier_compte(cid, entreprise_id=eid)
        self.recharger()

    def _statut(self, cid, statut):
        self.serveur.comptes.modifier_compte(cid, statut=statut)
        self.recharger()

    def _reinitialiser(self, c):
        mdp = mot_de_passe_provisoire()
        if QMessageBox.question(self, "Réinitialiser le mot de passe",
                                f"Créer un nouveau mot de passe pour {c['prenom']} {c['nom']} ?\nSes appareils "
                                "seront déconnectés.") != QMessageBox.StandardButton.Yes:
            return
        self.serveur.comptes.changer_mot_de_passe(c["id"], mdp)
        self.serveur.comptes.revoquer_sessions(c["id"])
        QGuiApplication.clipboard().setText(mdp)
        QMessageBox.information(self, "Nouveau mot de passe",
                                f"Nouveau mot de passe provisoire (copié dans le presse-papiers) :\n\n{mdp}\n\n"
                                "Transmettez-le à la personne par un moyen sûr. Il ne sera plus affiché.")

    def _deconnecter(self, c):
        self.serveur.comptes.revoquer_sessions(c["id"])
        self.fen.toast(f"{c['prenom']} {c['nom']} : tous les appareils sont déconnectés.", "ok")

    def _details(self, c):
        sessions = self.serveur.comptes.sessions(c["id"])
        texte = (f"{c['prenom']} {c['nom']} — {c['mail']}\nStatut : {ms.STATUTS.get(c['statut'])}\n"
                 f"Entreprise : {c['entreprise'] or 'aucune'} (société indiquée : {c['societe'] or '—'})\n"
                 f"Créé le : {date_courte(c['cree_le'])}\n"
                 f"Conditions d'utilisation acceptées : version {c['cgu_version'] or '—'} le {date_courte(c['cgu_le'])}\n"
                 f"Dernière connexion : {date_courte(c['derniere_connexion'])} depuis {c['derniere_ip'] or '—'}\n"
                 f"Appareil : {c['appareil'] or '—'} · FluxLite {c['version_app'] or '—'}\n\n"
                 f"Sessions ouvertes : {len(sessions)}\n" +
                 "\n".join(f"  • {s['appareil'] or 'Appareil'} — {s['ip']} — actif {date_courte(s['activite'])}"
                           for s in sessions))
        QMessageBox.information(self, "Compte FluxLite", texte)

    def _supprimer_compte(self, c):
        if QMessageBox.question(self, "Supprimer le compte",
                                f"Supprimer définitivement le compte de {c['prenom']} {c['nom']} ({c['mail']}) ?") \
                != QMessageBox.StandardButton.Yes:
            return
        self.serveur.comptes.supprimer_compte(c["id"])
        self.recharger()

    def _nouveau_compte(self):
        if self.serveur is None:
            return
        d = DialogueCompte(self, self.serveur.comptes.entreprises())
        if d.exec() != QDialog.DialogCode.Accepted or not d.resultat:
            return
        mail, mdp, nom, prenom, eid = d.resultat
        try:
            self.serveur.comptes.creer_compte(mail, mdp, nom, prenom, "", "actif", eid)
        except ms.ErreurServeur as e:
            self.fen.toast(str(e), "erreur")
            return
        QGuiApplication.clipboard().setText(mdp)
        self.fen.toast(f"Compte créé pour {prenom} {nom}. Mot de passe copié dans le presse-papiers.", "ok")
        self.recharger()

    # --- entreprises ---------------------------------------------------------------------
    def _remplir_entreprises(self):
        courante = self._entreprise_courante
        self.liste_ent.blockSignals(True)
        self.liste_ent.clear()
        for e in self.serveur.comptes.entreprises():
            it = QListWidgetItem(f"{e['nom']}  ·  {e['nb']} compte{'s' if e['nb'] > 1 else ''}")
            it.setData(Qt.ItemDataRole.UserRole, e["id"])
            self.liste_ent.addItem(it)
            if e["id"] == courante:
                self.liste_ent.setCurrentItem(it)
        self.liste_ent.blockSignals(False)
        if self.liste_ent.currentItem() is None and self.liste_ent.count():
            self.liste_ent.setCurrentRow(0)
        self._entreprise_choisie()

    def _entreprise_choisie(self):
        it = self.liste_ent.currentItem()
        e = self.serveur.comptes.entreprise(it.data(Qt.ItemDataRole.UserRole)) if it and self.serveur else None
        self._entreprise_courante = e["id"] if e else None
        for w in (self.b_ren_ent, self.b_sup_ent, self.chk_toutes, self.liste_cam):
            w.setEnabled(e is not None)
        self._maj_bloquee = True
        self.liste_cam.clear()
        if e is None:
            self.lbl_ent.setText("Aucune entreprise" if not self.liste_ent.count() else "Choisissez une entreprise")
            self.lbl_ent_info.setText("Créez une entreprise pour chaque client (ex. « Magasin Centre »), puis "
                                      "choisissez les caméras qu'elle peut voir.")
            self.chk_toutes.setChecked(False)
            self._maj_bloquee = False
            return
        self.lbl_ent.setText(e["nom"])
        membres = [c for c in self.serveur.comptes.comptes() if c["entreprise_id"] == e["id"]]
        self.lbl_ent_info.setText(", ".join(f"{c['prenom']} {c['nom']}" for c in membres) or "Aucun compte pour "
                                  "l'instant.")
        self.chk_toutes.setChecked(e["toutes"])
        noms = self.fen.page_cameras.noms_cameras()
        for nom in noms + [n for n in e["cameras"] if n not in noms]:
            it = QListWidgetItem(nom if nom in noms else f"{nom} (caméra fermée)")
            it.setData(Qt.ItemDataRole.UserRole, nom)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if (e["toutes"] or nom in e["cameras"]) else Qt.CheckState.Unchecked)
            if e["toutes"]:
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.liste_cam.addItem(it)
        self._maj_bloquee = False

    def _cameras_entreprise_changees(self):
        if self._maj_bloquee or self._entreprise_courante is None:
            return
        cams = [self.liste_cam.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.liste_cam.count())
                if self.liste_cam.item(i).checkState() == Qt.CheckState.Checked]
        toutes = self.chk_toutes.isChecked()
        e = self.serveur.comptes.entreprise(self._entreprise_courante)
        if toutes and not e["toutes"]:
            cams = e["cameras"]  # garder la sélection précédente si on décoche « toutes » plus tard
        self.serveur.comptes.modifier_entreprise(self._entreprise_courante, cameras=cams, toutes=toutes)
        if toutes != e["toutes"]:
            self._entreprise_choisie()

    def _nouvelle_entreprise(self):
        nom, ok = QInputDialog.getText(self, "Nouvelle entreprise", "Nom de l'entreprise (client) :")
        if not ok or not nom.strip():
            return
        try:
            self._entreprise_courante = self.serveur.comptes.creer_entreprise(nom)
        except ms.ErreurServeur as e:
            self.fen.toast(str(e), "erreur")
            return
        self.recharger()

    def _renommer_entreprise(self):
        e = self.serveur.comptes.entreprise(self._entreprise_courante) if self._entreprise_courante else None
        if not e:
            return
        nom, ok = QInputDialog.getText(self, "Renommer l'entreprise", "Nouveau nom :", text=e["nom"])
        if ok and nom.strip():
            try:
                self.serveur.comptes.modifier_entreprise(e["id"], nom=nom)
            except ms.ErreurServeur as ex:
                self.fen.toast(str(ex), "erreur")
            self.recharger()

    def _supprimer_entreprise(self):
        e = self.serveur.comptes.entreprise(self._entreprise_courante) if self._entreprise_courante else None
        if not e:
            return
        if QMessageBox.question(self, "Supprimer l'entreprise",
                                f"Supprimer « {e['nom']} » ? Ses comptes sont gardés mais ne verront plus aucune "
                                "caméra.") != QMessageBox.StandardButton.Yes:
            return
        self.serveur.comptes.supprimer_entreprise(e["id"])
        self._entreprise_courante = None
        self.recharger()

    def _copier(self, texte):
        if texte:
            QGuiApplication.clipboard().setText(texte)
            self.fen.toast("Copié dans le presse-papiers.", "ok")
