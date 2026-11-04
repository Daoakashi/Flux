"""Fenêtre « Réseau » : choisir un WiFi, taper son mot de passe, se déconnecter, oublier un réseau.

Ouverte par le bouton « Réseau » (en bas de la barre de gauche) ou l'indicateur réseau de la barre d'état.
En mode kiosque, modifier le réseau demande le code administrateur (une fois par ouverture).
"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QVBoxLayout, QWidget)

from . import reseau_wifi as rw
from .taches import en_arriere_plan
from .theme import C
from .widgets import Bouton, Interrupteur, etiquette


def texte_etat(e, internet=None):
    if e is None:
        return "Lecture de l'état du réseau…"
    morceaux = []
    if e.get("ssid"):
        sig = e.get("signal")
        morceaux.append(f"WiFi « {e['ssid']} »" + (f" · signal {rw.barres(sig)} {sig} %" if sig is not None else "")
                        + (f" · {e['ip']}" if e.get("ip") else ""))
    if e.get("cable"):
        morceaux.append("Câble réseau branché" + (f" · {e['ip_cable']}" if e.get("ip_cable") else ""))
    if not morceaux:
        morceaux.append("WiFi désactivé" if e.get("wifi_present") and not e.get("wifi_actif") else
                        "Aucune carte WiFi trouvée" if not e.get("wifi_present") and not e.get("cable") else
                        "Pas connecté")
    if internet is not None:
        morceaux.append("Internet : OK" if internet else "Internet : ne répond pas")
    return " — ".join(morceaux)


class DialogueReseau(QDialog):
    def __init__(self, fen):
        super().__init__(fen)
        self.fen = fen
        self.setWindowTitle("Réseau")
        self.setMinimumSize(700, 580)
        self.autorise = not (getattr(fen, "kiosque", False) and self._code_kiosque())
        self.etat = None
        self.liste_reseaux = []
        self.occupe = False
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 18)
        v.setSpacing(10)
        h = QHBoxLayout()
        t = QLabel("Réseau")
        t.setObjectName("titre")
        h.addWidget(t)
        h.addStretch(1)
        h.addWidget(QLabel("WiFi"))
        self.inter = Interrupteur()
        self.inter.toggled.connect(self._radio)
        h.addWidget(self.inter)
        v.addLayout(h)
        self.lbl_etat = etiquette("Lecture de l'état du réseau…")
        self.lbl_etat.setStyleSheet("font-weight: 600;")
        v.addWidget(self.lbl_etat)

        self.liste = QListWidget()
        self.liste.setMinimumHeight(220)
        self.liste.itemSelectionChanged.connect(self._selection)
        self.liste.itemDoubleClicked.connect(lambda _i: self._connecter())
        v.addWidget(self.liste, 1)

        # mot de passe (réseau sécurisé pas encore enregistré, ou mot de passe changé)
        self.zone_mdp = QWidget()
        zm = QHBoxLayout(self.zone_mdp)
        zm.setContentsMargins(0, 0, 0, 0)
        self.mdp = QLineEdit()
        self.mdp.setEchoMode(QLineEdit.EchoMode.Password)
        self.mdp.setPlaceholderText("Mot de passe du WiFi")
        self.mdp.returnPressed.connect(self._connecter)
        zm.addWidget(self.mdp, 1)
        voir = QCheckBox("Afficher")
        voir.toggled.connect(lambda x: self.mdp.setEchoMode(QLineEdit.EchoMode.Normal if x else QLineEdit.EchoMode.Password))
        zm.addWidget(voir)
        self.zone_mdp.hide()
        v.addWidget(self.zone_mdp)

        self.lbl_info = etiquette("", "aide")
        v.addWidget(self.lbl_info)

        hb = QHBoxLayout()
        self.b_connecter = Bouton("Se connecter", "primaire", "wifi")
        self.b_connecter.clicked.connect(self._connecter)
        self.b_deconnecter = Bouton("Déconnecter", "discret")
        self.b_deconnecter.clicked.connect(self._deconnecter)
        self.b_oublier = Bouton("Oublier", "discret")
        self.b_oublier.setToolTip("Supprime le mot de passe enregistré pour ce réseau")
        self.b_oublier.clicked.connect(self._oublier)
        self.b_cache = Bouton("Réseau caché…", "discret")
        self.b_cache.clicked.connect(self._cache)
        self.b_actualiser = Bouton("Actualiser", "discret")
        self.b_actualiser.clicked.connect(lambda: self.actualiser(True))
        for b in (self.b_connecter, self.b_deconnecter, self.b_oublier, self.b_cache, self.b_actualiser):
            hb.addWidget(b)
        hb.addStretch(1)
        fermer = Bouton("Fermer")
        fermer.clicked.connect(self.accept)
        hb.addWidget(fermer)
        v.addLayout(hb)

        ok, pourquoi = rw.disponible()
        if not ok:
            self.lbl_etat.setText(pourquoi)
            for b in (self.b_connecter, self.b_deconnecter, self.b_oublier, self.b_cache, self.b_actualiser, self.inter):
                b.setEnabled(False)
            return
        self._minuterie = QTimer(self)
        self._minuterie.timeout.connect(lambda: self.actualiser(False) if not self.occupe else None)
        self._minuterie.start(15000)
        QTimer.singleShot(50, lambda: self.actualiser(True))

    # --- code administrateur (kiosque) ---------------------------------------------------------
    @staticmethod
    def _code_kiosque():
        try:
            from . import kiosque
            return kiosque.code_defini()
        except Exception:  # noqa: BLE001
            return False

    def _autoriser(self):
        if self.autorise:
            return True
        from .fenetre import DialogueKiosque
        d = DialogueKiosque(self, "Modifier le réseau", "Mode kiosque : tapez le code administrateur pour changer de "
                                                          "réseau WiFi.", "Valider")
        if d.exec() == QDialog.DialogCode.Accepted:
            self.autorise = True
            return True
        return False

    # --- lecture ----------------------------------------------------------------------------------
    def actualiser(self, balayer=True):
        if self.occupe:
            return
        self._occupe(True, "Recherche des réseaux WiFi…" if balayer else "")

        def lire():
            e = rw.etat()
            l = rw.reseaux(balayer) if e.get("wifi_present") and e.get("wifi_actif") else []
            return e, l, rw.internet(3)

        en_arriere_plan(lire, self._afficher, self._erreur_lecture)

    def _afficher(self, r):
        if not self.isVisible():
            return
        e, l, internet = r
        self.etat, self.liste_reseaux = e, l
        self._occupe(False, "")
        self.inter.regler(bool(e.get("wifi_actif")))
        self.inter.setEnabled(bool(e.get("wifi_present")) and not rw.WINDOWS)
        self.lbl_etat.setText(texte_etat(e, internet))
        self.lbl_etat.setStyleSheet(f"font-weight: 600; color: {C['succes'] if internet else C['attention']};")
        choisi = self._ssid_choisi()
        self.liste.clear()
        for x in l:
            details = []
            if x["actif"]:
                details.append("connecté")
            elif x["connu"]:
                details.append("enregistré")
            details.append("sécurisé" if x["securise"] else "ouvert, non chiffré")
            it = QListWidgetItem(f"{rw.barres(x['signal'])}   {x['ssid']}      {x['signal']} % · {', '.join(details)}")
            it.setData(Qt.ItemDataRole.UserRole, x)
            if x["actif"]:
                f = it.font()
                f.setBold(True)
                it.setFont(f)
            self.liste.addItem(it)
            if x["ssid"] == choisi:
                it.setSelected(True)
                self.liste.setCurrentItem(it)
        if not l:
            msg = ("Le WiFi est désactivé : activez-le avec l'interrupteur en haut." if e.get("wifi_present") and not e.get("wifi_actif")
                   else "Aucun réseau WiFi à portée." if e.get("wifi_present") else "Aucune carte WiFi sur ce PC.")
            it = QListWidgetItem(msg)
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.liste.addItem(it)
        self._selection()

    def _erreur_lecture(self, e):
        self._occupe(False, f"Lecture du réseau impossible : {e}")

    # --- actions ------------------------------------------------------------------------------------
    def _ssid_choisi(self):
        it = self.liste.currentItem()
        x = it.data(Qt.ItemDataRole.UserRole) if it is not None else None
        return x["ssid"] if x else None

    def _reseau_choisi(self):
        it = self.liste.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it is not None else None

    def _selection(self):
        x = self._reseau_choisi()
        besoin_mdp = bool(x and x["securise"] and not x["connu"])
        self.zone_mdp.setVisible(besoin_mdp)
        if besoin_mdp:
            self.mdp.setFocus()
        self.b_connecter.setEnabled(bool(x) and not self.occupe and not (x and x["actif"]))
        self.b_oublier.setEnabled(bool(x and x["connu"]) and not self.occupe)
        self.b_deconnecter.setEnabled(bool(self.etat and self.etat.get("ssid")) and not self.occupe)
        if x and x["connu"] and x["securise"] and not x["actif"]:
            self.lbl_info.setText("Réseau enregistré : Flux utilise le mot de passe déjà connu. S'il a changé, "
                                  "choisissez « Oublier » puis reconnectez-vous.")
        elif x and not x["securise"]:
            self.lbl_info.setText("Réseau ouvert : les échanges ne sont pas chiffrés par le WiFi (ceux de Flux le "
                                  "restent). Préférez un réseau protégé par mot de passe.")
        elif not self.occupe:
            self.lbl_info.setText("")

    def _occupe(self, oui, texte):
        self.occupe = oui
        if oui:
            self.lbl_info.setStyleSheet("")
        for b in (self.b_connecter, self.b_deconnecter, self.b_oublier, self.b_cache, self.b_actualiser):
            b.setEnabled(not oui)
        if not oui:
            self._selection()
        if texte or not oui:
            self.lbl_info.setText(texte or self.lbl_info.text())

    def _executer(self, attente, fonction, succes_texte, *args):
        if not self._autoriser():
            return
        self._occupe(True, attente)

        def fini(_r):
            self.lbl_info.setStyleSheet("")
            self._occupe(False, succes_texte[:1].upper() + succes_texte[1:] + ".")
            self.fen.toast(succes_texte, "ok")
            self.fen.log_systeme(f"Réseau : {succes_texte}", "info")
            self.mdp.clear()
            QTimer.singleShot(1500, lambda: self.actualiser(False))
            if hasattr(self.fen, "maj_reseau"):
                QTimer.singleShot(3000, self.fen.maj_reseau)

        def echec(e):
            self._occupe(False, f"Impossible : {e}.")
            self.lbl_info.setStyleSheet(f"color: {C['danger']};")
            QTimer.singleShot(6000, lambda: self.lbl_info.setStyleSheet(""))

        en_arriere_plan(fonction, fini, echec, *args)

    def _connecter(self):
        x = self._reseau_choisi()
        if not x or x["actif"]:
            return
        mdp = self.mdp.text() if self.zone_mdp.isVisible() else None
        if x["securise"] and not x["connu"] and not mdp:
            self.lbl_info.setText("Tapez le mot de passe du WiFi.")
            self.mdp.setFocus()
            return
        self._executer(f"Connexion à « {x['ssid']} »… (jusqu'à 40 secondes)", rw.connecter,
                       f"connecté au WiFi « {x['ssid']} »", x["ssid"], mdp)

    def _deconnecter(self):
        if not self.etat or not self.etat.get("ssid"):
            return
        from PySide6.QtWidgets import QMessageBox
        if QMessageBox.question(self, "Se déconnecter ?", f"Flux ne recevra plus rien par « {self.etat['ssid']} » : "
                                "plus d'alertes sur les téléphones ni d'accès à distance tant qu'aucun autre réseau "
                                "n'est connecté. Continuer ?") != QMessageBox.StandardButton.Yes:
            return
        self._executer("Déconnexion…", rw.deconnecter, f"déconnecté de « {self.etat['ssid']} »")

    def _oublier(self):
        x = self._reseau_choisi()
        if not x or not x["connu"]:
            return
        self._executer("Suppression du réseau enregistré…", rw.oublier, f"réseau « {x['ssid']} » oublié", x["ssid"])

    def _cache(self):
        from PySide6.QtWidgets import QInputDialog
        ssid, ok = QInputDialog.getText(self, "Réseau caché", "Nom exact du réseau (SSID) :")
        if not ok or not ssid.strip():
            return
        mdp, ok = QInputDialog.getText(self, "Réseau caché", "Mot de passe (vide si le réseau est ouvert) :",
                                       QLineEdit.EchoMode.Password)
        if not ok:
            return
        self._executer(f"Connexion à « {ssid.strip()} »…", rw.connecter, f"connecté au WiFi « {ssid.strip()} »",
                       ssid.strip(), mdp or None, True)

    def _radio(self, actif):
        if not self._autoriser():
            self.inter.regler(not actif)
            return
        self._executer("Activation du WiFi…" if actif else "Désactivation du WiFi…", rw.radio,
                       "WiFi activé" if actif else "WiFi désactivé", actif)
