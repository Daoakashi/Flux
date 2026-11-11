"""Onglet « Télésurveillance » : envoi du journal de Flux aux centrales de télésurveillance tierces
(SIA DC-09 : SIA ou Contact ID ; images et vidéos par FTP, FTPS, SFTP, HTTP ou HTTPS)."""
import copy
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QFormLayout, QFrame, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QScrollArea, QSpinBox,
                               QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from . import coffre
from . import telesurveillance as ts
from .taches import en_arriere_plan
from .theme import C
from .widgets import Bouton, Interrupteur, Rangee, etiquette, separateur

ETATS = {"ok": ("Liaison OK", "#22C55E"), "erreur": ("Erreur", "#EF4444"), "attente": ("En attente", "#F59E0B"),
         "inactive": ("Désactivée", "#64748B")}


def carte():
    f = QFrame()
    f.setObjectName("carte")
    return f


def pastille_etat(texte, couleur):
    lb = QLabel(texte)
    lb.setStyleSheet(f"background: {couleur}26; color: {couleur}; border-radius: 10px; padding: 2px 10px; font-weight: 700;")
    return lb


# ---------------------------------------------------------------------------------------------
# Fiche d'une centrale
# ---------------------------------------------------------------------------------------------
class DialogueCentrale(QDialog):
    def __init__(self, page, c=None):
        super().__init__(page)
        self.page = page
        self.nouvelle = c is None
        self.c = copy.deepcopy(c) if c else ts.centrale_defaut()
        self.c.setdefault("fichiers", ts.centrale_defaut()["fichiers"])
        self.setWindowTitle("Nouvelle centrale" if self.nouvelle else f"Centrale « {self.c['nom']} »")
        self.resize(640, 640)
        v = QVBoxLayout(self)
        onglets = QTabWidget()
        v.addWidget(onglets)
        f = self.c["fichiers"]

        # --- connexion ---
        w1, f1 = self._onglet(onglets, "Connexion")
        self.nom = QLineEdit(self.c["nom"])
        self.actif = QCheckBox("Transmettre à cette centrale")
        self.actif.setChecked(self.c.get("actif", True))
        self.hote = QLineEdit(self.c.get("hote", ""))
        self.hote.setPlaceholderText("Adresse IP ou nom, ex. 203.0.113.10")
        self.port = QSpinBox()
        self.port.setRange(0, 65535)
        self.port.setValue(int(self.c.get("port") or 0))
        self.port.setSpecialValueText("—")
        self.transport = self._choix([("tcp", "TCP (recommandé)"), ("udp", "UDP")], self.c.get("transport", "tcp"))
        self.protocole = self._choix([("SIA-DCS", "SIA (SIA-DCS)"), ("ADM-CID", "Contact ID (Ademco, ADM-CID)")],
                                     self.c.get("protocole", "SIA-DCS"))
        self.compte = QLineEdit(self.c.get("compte", ""))
        self.compte.setPlaceholderText("Numéro de client donné par la centrale, ex. 1234")
        self.compte.setMaxLength(16)
        self.cle = QLineEdit(coffre.dechiffrer(self.c.get("cle_aes") or "", "telesurveillance"))
        self.cle.setEchoMode(QLineEdit.EchoMode.Password)
        self.cle.setPlaceholderText("Vide : sans chiffrement")
        voir = QCheckBox("Afficher")
        voir.toggled.connect(lambda x: self.cle.setEchoMode(QLineEdit.EchoMode.Normal if x else QLineEdit.EchoMode.Password))
        lc = QHBoxLayout()
        lc.addWidget(self.cle, 1)
        lc.addWidget(voir)
        self.format_cle = self._choix([("hex", "Hexadécimale (32, 48 ou 64 caractères 0-9 A-F)"),
                                       ("texte", "Texte (16, 24 ou 32 caractères tels quels)")],
                                      self.c.get("format_cle", "hex"))
        self.recepteur = QLineEdit(self.c.get("recepteur", ""))
        self.recepteur.setPlaceholderText("Vide si non demandé")
        self.ligne = QLineEdit(self.c.get("ligne", "0") or "0")
        self.partition = QSpinBox()
        self.partition.setRange(0, 99)
        self.partition.setValue(int(self.c.get("partition", 1)))
        for lib, w in (("Nom", self.nom), ("", self.actif), ("Adresse du récepteur", self.hote), ("Port", self.port),
                       ("Transport", self.transport), ("Protocole", self.protocole), ("Numéro de client", self.compte),
                       ("Clé de chiffrement AES", lc), ("Format de la clé", self.format_cle),
                       ("Préfixe récepteur (R)", self.recepteur), ("Préfixe ligne (L)", self.ligne),
                       ("Secteur / partition", self.partition)):
            f1.addRow(lib, w)
        self.avert_cle = etiquette("")
        self.avert_cle.setStyleSheet(f"color: {C['attention'] if 'attention' in C else '#F59E0B'};")
        f1.addRow("", self.avert_cle)
        self.cle.textChanged.connect(self._avertissements)

        # --- secours et supervision ---
        w2, f2 = self._onglet(onglets, "Secours et supervision")
        self.secours_hote = QLineEdit(self.c.get("secours_hote", ""))
        self.secours_hote.setPlaceholderText("Facultatif : utilisé si le récepteur principal ne répond pas")
        self.secours_port = QSpinBox()
        self.secours_port.setRange(0, 65535)
        self.secours_port.setValue(int(self.c.get("secours_port") or 0))
        self.secours_port.setSpecialValueText("—")
        self.supervision = QSpinBox()
        self.supervision.setRange(0, 86400)
        self.supervision.setSuffix(" s")
        self.supervision.setSpecialValueText("Désactivée")
        self.supervision.setValue(int(self.c.get("supervision") or 0))
        self.test_h = QSpinBox()
        self.test_h.setRange(0, 168)
        self.test_h.setSuffix(" h")
        self.test_h.setSpecialValueText("Désactivé")
        self.test_h.setValue(int(self.c.get("test_heures") or 0))
        self.delai = QSpinBox()
        self.delai.setRange(2, 60)
        self.delai.setSuffix(" s")
        self.delai.setValue(int(self.c.get("delai") or 10))
        self.xdata = QCheckBox("Données étendues : texte de l'alarme, caméra, site, nom du fichier image")
        self.xdata.setChecked(self.c.get("xdata", True))
        self.horo = QCheckBox("Horodatage dans chaque message (obligatoire avec le chiffrement)")
        self.horo.setChecked(self.c.get("horodatage", True))
        for lib, w in (("Récepteur de secours", self.secours_hote), ("Port de secours", self.secours_port),
                       ("Supervision (message NULL) toutes les", self.supervision),
                       ("Test automatique (RP / 602) toutes les", self.test_h), ("Attente de l'accusé", self.delai),
                       ("", self.xdata), ("", self.horo)):
            f2.addRow(lib, w)
        f2.addRow("", etiquette("Désactivez les données étendues ou l'horodatage seulement si un ancien récepteur "
                                "refuse les messages (réponse « DUH »)."))

        # --- événements ---
        w3, f3 = self._onglet(onglets, "Événements reçus")
        f3.addRow(etiquette("Types d'événements envoyés à cette centrale (les codes se règlent dans l'onglet "
                            "Télésurveillance, pour toutes les centrales)."))
        self.cases_types = {}
        for t in ts.TYPES:
            cb = QCheckBox(t[1])
            cb.setChecked(t[0] in self.c.get("types", [x[0] for x in ts.TYPES]))
            self.cases_types[t[0]] = cb
            f3.addRow(cb)

        # --- images et vidéos ---
        w4, f4 = self._onglet(onglets, "Images et vidéos")
        self.methode = self._choix(ts.METHODES_FICHIERS, f.get("methode", "aucune"))
        self.f_hote = QLineEdit(f.get("hote", ""))
        self.f_port = QSpinBox()
        self.f_port.setRange(0, 65535)
        self.f_port.setSpecialValueText("Par défaut")
        self.f_port.setValue(int(f.get("port") or 0))
        self.f_url = QLineEdit(f.get("url", ""))
        self.f_url.setPlaceholderText("https://reception.centrale.be/alarmes")
        self.f_util = QLineEdit(f.get("utilisateur", ""))
        self.f_mdp = QLineEdit(coffre.dechiffrer(f.get("mdp") or "", "telesurveillance"))
        self.f_mdp.setEchoMode(QLineEdit.EchoMode.Password)
        self.f_dossier = QLineEdit(f.get("dossier", ""))
        self.f_dossier.setPlaceholderText("ex. alarmes/flux")
        self.f_modele = QLineEdit(f.get("modele") or "{compte}_{date}_{heure}_{camera}_{code}")
        self.f_verif = QCheckBox("Vérifier le certificat du serveur (recommandé)")
        self.f_verif.setChecked(f.get("verifier", True))
        self.f_passif = QCheckBox("Mode passif (FTP)")
        self.f_passif.setChecked(f.get("passif", True))
        self.empreinte = f.get("empreinte_sftp", "")
        self.b_oublier = Bouton("Oublier la clé SFTP enregistrée", "discret")
        self.b_oublier.clicked.connect(self._oublier_sftp)
        self.avert_f = etiquette("")
        self.lignes_f = {}
        for cle_l, lib, w in (("m", "Envoi", self.methode), ("h", "Serveur", self.f_hote), ("p", "Port", self.f_port),
                              ("u", "Adresse d'envoi (URL)", self.f_url), ("i", "Identifiant", self.f_util),
                              ("w", "Mot de passe", self.f_mdp), ("d", "Dossier", self.f_dossier),
                              ("n", "Nom des fichiers", self.f_modele), ("v", "", self.f_verif),
                              ("a", "", self.f_passif), ("s", "", self.b_oublier)):
            f4.addRow(lib, w)
            self.lignes_f[cle_l] = w
        f4.addRow("", etiquette("Nom des fichiers : {compte} {date} {heure} {camera} {code} {type} {zone}. "
                                "Le même nom est indiqué dans l'alarme (donnée « V ») pour que l'opérateur ouvre "
                                "la bonne image."))
        f4.addRow("", self.avert_f)
        self.methode.currentIndexChanged.connect(self._avertissements)
        self.protocole.currentIndexChanged.connect(self._avertissements)

        h = QHBoxLayout()
        h.addStretch(1)
        b_annuler = Bouton("Annuler", "discret")
        b_annuler.clicked.connect(self.reject)
        b_ok = Bouton("Enregistrer", "primaire")
        b_ok.clicked.connect(self._valider)
        h.addWidget(b_annuler)
        h.addWidget(b_ok)
        v.addLayout(h)
        self._avertissements()

    @staticmethod
    def _onglet(onglets, titre):
        defil = QScrollArea()
        defil.setWidgetResizable(True)
        defil.setFrameShape(QFrame.Shape.NoFrame)
        w = QWidget()
        f = QFormLayout(w)
        f.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        f.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        defil.setWidget(w)
        onglets.addTab(defil, titre)
        return w, f

    @staticmethod
    def _choix(options, valeur):
        cb = QComboBox()
        for k, lib in options:
            cb.addItem(lib, k)
        i = cb.findData(valeur)
        cb.setCurrentIndex(max(0, i))
        return cb

    def _oublier_sftp(self):
        self.empreinte = ""
        self.b_oublier.setEnabled(False)
        self.b_oublier.setText("Clé oubliée : elle sera relevée au prochain envoi")

    def _avertissements(self):
        m = self.methode.currentData()
        visibles = {"aucune": "m", "ftp": "mhpiwdna", "ftps": "mhpiwdnva", "sftp": "mhpiwdns", "http": "muiwn",
                    "https": "muiwnv"}[m]
        for k, w in self.lignes_f.items():
            w.setVisible(k in visibles)
            lab = self.lignes_f[k].parentWidget().layout().labelForField(w) if w.parentWidget() else None
            if lab is not None:
                lab.setVisible(k in visibles)
        self.b_oublier.setVisible(m == "sftp" and bool(self.empreinte))
        self.avert_f.setText("⚠ FTP et HTTP ne sont pas chiffrés : quelqu'un qui intercepte la liaison pourrait voir "
                             "les images. Préférez FTPS, SFTP ou HTTPS si la centrale les accepte." if m in ("ftp", "http") else "")
        self.avert_f.setStyleSheet("color: #F59E0B;")
        self.avert_cle.setText("⚠ Sans clé AES, les alarmes circulent en clair. Demandez une clé à la centrale."
                               if not self.cle.text().strip() else "")
        self.avert_cle.setStyleSheet("color: #F59E0B;")

    def _valider(self):
        c = self.c
        c.update({
            "nom": self.nom.text().strip() or "Centrale", "actif": self.actif.isChecked(),
            "hote": self.hote.text().strip(), "port": self.port.value() or "", "transport": self.transport.currentData(),
            "protocole": self.protocole.currentData(), "compte": self.compte.text().strip().upper(),
            "format_cle": self.format_cle.currentData(),
            "cle_aes": coffre.chiffrer(self.cle.text().strip(), "telesurveillance"),
            "recepteur": self.recepteur.text().strip().upper(), "ligne": self.ligne.text().strip().upper() or "0",
            "partition": self.partition.value(), "secours_hote": self.secours_hote.text().strip(),
            "secours_port": self.secours_port.value() or "", "supervision": self.supervision.value(),
            "test_heures": self.test_h.value(), "delai": self.delai.value(), "xdata": self.xdata.isChecked(),
            "horodatage": self.horo.isChecked() or bool(self.cle.text().strip()),
            "types": [k for k, cb in self.cases_types.items() if cb.isChecked()],
        })
        c["fichiers"].update({
            "methode": self.methode.currentData(), "hote": self.f_hote.text().strip(), "port": self.f_port.value() or "",
            "url": self.f_url.text().strip(), "utilisateur": self.f_util.text().strip(),
            "mdp": coffre.chiffrer(self.f_mdp.text(), "telesurveillance"), "dossier": self.f_dossier.text().strip(),
            "modele": self.f_modele.text().strip(), "verifier": self.f_verif.isChecked(),
            "passif": self.f_passif.isChecked(), "empreinte_sftp": self.empreinte,
        })
        erreurs = []
        if not c["hote"] or not c["port"]:
            erreurs.append("l'adresse et le port du récepteur sont obligatoires")
        if c["recepteur"] and not all(x in "0123456789ABCDEF" for x in c["recepteur"]):
            erreurs.append("préfixe récepteur : chiffres hexadécimaux seulement")
        if not all(x in "0123456789ABCDEF" for x in c["ligne"]):
            erreurs.append("préfixe ligne : chiffres hexadécimaux seulement")
        m = c["fichiers"]["methode"]
        if m in ("ftp", "ftps", "sftp") and not c["fichiers"]["hote"]:
            erreurs.append("serveur de fichiers manquant")
        if m in ("http", "https") and not c["fichiers"]["url"].lower().startswith(m + "://"):
            erreurs.append(f"l'adresse d'envoi doit commencer par {m}://")
        try:
            ts.compte_valide(c["compte"])
            ts.cle_aes(self.cle.text().strip(), c["format_cle"])
        except ts.ErreurTransmission as e:
            erreurs.append(str(e))
        if erreurs:
            QMessageBox.warning(self, "Centrale", "À corriger :\n• " + "\n• ".join(erreurs))
            return
        self.page.gestion.enregistrer_centrale(c)
        self.accept()


# ---------------------------------------------------------------------------------------------
# Onglet
# ---------------------------------------------------------------------------------------------
class PageTelesurveillance(QWidget):
    def __init__(self, fen):
        super().__init__()
        self.fen = fen
        self.gestion = fen.telesurveillance
        self._version_journal = -1
        racine = QVBoxLayout(self)
        racine.setContentsMargins(0, 0, 0, 0)
        defil = QScrollArea()
        defil.setWidgetResizable(True)
        defil.setFrameShape(QFrame.Shape.NoFrame)
        racine.addWidget(defil)
        contenu = QWidget()
        defil.setWidget(contenu)
        v = QVBoxLayout(contenu)
        v.setContentsMargins(28, 22, 28, 28)
        v.setSpacing(14)

        haut = QHBoxLayout()
        t = QLabel("Télésurveillance")
        t.setObjectName("titre_page")
        haut.addWidget(t)
        haut.addStretch(1)
        boutons = QWidget()
        rb = Rangee(boutons, droite=True)
        rb.addWidget(QLabel("Transmission active"))
        self.i_actif = Interrupteur()
        self.i_actif.regler(bool(self.gestion.config.get("actif", True)))
        self.i_actif.toggled.connect(self._actif)
        rb.addWidget(self.i_actif)
        b = Bouton("Ajouter une centrale", "primaire", "plus")
        b.clicked.connect(lambda: self._modifier(None))
        rb.addWidget(b)
        haut.addWidget(boutons, 1)
        v.addLayout(haut)
        v.addWidget(etiquette(
            "Transmet en temps réel le journal de Flux aux centrales de télésurveillance (protocole SIA DC-09, au "
            "format SIA ou Contact ID, compatible avec les logiciels de réception d'alarmes du marché). Les images "
            "et vidéos sont déposées sur le serveur de la centrale. Alarmes chiffrées (AES) si la centrale fournit "
            "une clé ; rien n'est perdu pendant une coupure : les envois attendent et repartent tout seuls."))

        # centrales
        v.addWidget(etiquette("CENTRALES", "section"))
        self.zone_centrales = QVBoxLayout()
        self.zone_centrales.setSpacing(10)
        v.addLayout(self.zone_centrales)

        # nom du site
        ls = QHBoxLayout()
        ls.addWidget(QLabel("Nom du site envoyé aux centrales"))
        self.site = QLineEdit(self.gestion.config.get("site", ""))
        self.site.setPlaceholderText("ex. Hypermarché Nord — Bruxelles")
        self.site.setMaxLength(120)
        self.site.editingFinished.connect(self._site)
        ls.addWidget(self.site, 1)
        v.addLayout(ls)

        # événements et codes
        v.addSpacing(6)
        v.addWidget(separateur())
        v.addWidget(etiquette("ÉVÉNEMENTS TRANSMIS ET CODES", "section"))
        v.addWidget(etiquette("Les codes par défaut suivent les usages des centrales (BA / 130 : intrusion, BV / 139 : "
                              "intrusion vérifiée…). Adaptez-les à la grille de votre centrale si elle en impose une."))
        self.table = QTableWidget(len(ts.TYPES), 6)
        self.table.setHorizontalHeaderLabels(["Événement", "Envoyer", "Code SIA", "Code Contact ID", "Image", "Vidéo"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, 6):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self.cellules = {}
        for r, t_ in enumerate(ts.TYPES):
            reg = self.gestion.config["evenements"][t_[0]]
            it = QTableWidgetItem(t_[1])
            it.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r, 0, it)
            env = self._case(reg.get("actif"))
            sia = QLineEdit(reg.get("sia", ""))
            sia.setMaxLength(2)
            sia.setFixedWidth(60)
            cid = QLineEdit(reg.get("cid", ""))
            cid.setMaxLength(3)
            cid.setFixedWidth(70)
            cid.setInputMask("999")
            img, vid = self._case(reg.get("image")), self._case(reg.get("video"))
            for col, w in ((1, env), (2, sia), (3, cid), (4, img), (5, vid)):
                self.table.setCellWidget(r, col, self._centrer(w))
            self.cellules[t_[0]] = (env, sia, cid, img, vid)
            for w in (env, img, vid):
                w.toggled.connect(self._evenements)
            for w in (sia, cid):
                w.editingFinished.connect(self._evenements)
        self.table.resizeRowsToContents()
        self.table.setMinimumHeight(self.table.verticalHeader().length() + self.table.horizontalHeader().height() + 6)
        v.addWidget(self.table)

        # zones
        v.addSpacing(6)
        v.addWidget(separateur())
        v.addWidget(etiquette("NUMÉROS DE ZONE DES CAMÉRAS", "section"))
        v.addWidget(etiquette("Chaque caméra est une « zone » pour la centrale (par défaut : son ordre dans Flux)."))
        self.zones = QGridLayout()
        self.zones.setHorizontalSpacing(12)
        v.addLayout(self.zones)

        # journal d'envoi
        v.addSpacing(6)
        v.addWidget(separateur())
        v.addWidget(etiquette("JOURNAL D'ENVOI", "section"))
        self.journal = QTableWidget(0, 5)
        self.journal.setHorizontalHeaderLabels(["Heure", "Centrale", "Événement", "État", "Détail"])
        self.journal.verticalHeader().setVisible(False)
        self.journal.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        jh = self.journal.horizontalHeader()
        for i in range(4):
            jh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        jh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.journal.setMinimumHeight(220)
        v.addWidget(self.journal)
        v.addStretch(1)

        self.cartes = {}
        self._remplir_centrales()
        self._remplir_zones()
        self.minuterie = QTimer(self)
        self.minuterie.timeout.connect(self.rafraichir)
        self.minuterie.start(1000)

    # --- petits outils --------------------------------------------------------------------------
    @staticmethod
    def _case(etat):
        cb = QCheckBox()
        cb.setChecked(bool(etat))
        return cb

    @staticmethod
    def _centrer(w):
        c = QWidget()
        h = QHBoxLayout(c)
        h.setContentsMargins(6, 2, 6, 2)
        h.addWidget(w, 0, Qt.AlignmentFlag.AlignCenter)
        return c

    def _actif(self, etat):
        self.gestion.config["actif"] = bool(etat)
        self.gestion.sauver_config()
        for ce in self.gestion.centrales.values():
            ce.reveil.set()
        self.fen.log_systeme(f"Télésurveillance : transmission {'activée' if etat else 'suspendue'}.", "info")

    def _site(self):
        self.gestion.config["site"] = self.site.text().strip()
        self.gestion.sauver_config()

    def _evenements(self):
        for k, (env, sia, cid, img, vid) in self.cellules.items():
            code_sia = "".join(ch for ch in sia.text().upper() if ch.isalpha())[:2]
            if len(code_sia) != 2:
                code_sia = self.gestion.config["evenements"][k].get("sia", "UA")
            sia.setText(code_sia)
            code_cid = cid.text().strip()
            if not (code_cid.isdigit() and len(code_cid) == 3):
                code_cid = self.gestion.config["evenements"][k].get("cid", "150")
                cid.setText(code_cid)
            self.gestion.config["evenements"][k] = {"actif": env.isChecked(), "sia": code_sia, "cid": code_cid,
                                                    "image": img.isChecked(), "video": vid.isChecked()}
        self.gestion.sauver_config()

    def _remplir_zones(self):
        while self.zones.count():
            w = self.zones.takeAt(0).widget()
            if w:
                w.deleteLater()
        cams = [p.nom for p in self.fen.page_cameras.pages]
        if not cams:
            self.zones.addWidget(etiquette("Aucune caméra ouverte."), 0, 0)
            return
        for i, nom in enumerate(cams):
            sp = QSpinBox()
            sp.setRange(1, 999)
            sp.setValue(self.gestion.zone(nom))
            sp.valueChanged.connect(lambda val, n=nom: self._zone(n, val))
            self.zones.addWidget(QLabel(nom), i // 3, (i % 3) * 2)
            self.zones.addWidget(sp, i // 3, (i % 3) * 2 + 1)

    def _zone(self, nom, val):
        self.gestion.config.setdefault("zones", {})[nom] = int(val)
        self.gestion.sauver_config()

    # --- centrales ------------------------------------------------------------------------------
    def _remplir_centrales(self):
        while self.zone_centrales.count():
            w = self.zone_centrales.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.cartes = {}
        if not self.gestion.config["centrales"]:
            vide = carte()
            lv = QVBoxLayout(vide)
            lv.setContentsMargins(18, 16, 18, 16)
            lv.addWidget(etiquette("Aucune centrale. Demandez à la centrale de télésurveillance : l'adresse IP et le "
                                   "port de son récepteur, le protocole (SIA ou Contact ID), votre numéro de client et, "
                                   "si possible, une clé de chiffrement AES et un accès FTPS/SFTP/HTTPS pour les images."))
            self.zone_centrales.addWidget(vide)
            return
        for c in self.gestion.config["centrales"]:
            fr = carte()
            g = QGridLayout(fr)
            g.setContentsMargins(18, 14, 18, 14)
            nom = QLabel(c["nom"])
            nom.setStyleSheet("font-size: 15px; font-weight: 700;")
            g.addWidget(nom, 0, 0)
            etat = pastille_etat("…", "#64748B")
            g.addWidget(etat, 0, 1, Qt.AlignmentFlag.AlignRight)
            chiffre = "chiffré AES" if c.get("cle_aes") else "non chiffré"
            fm = dict(ts.METHODES_FICHIERS).get((c.get("fichiers") or {}).get("methode", "aucune"), "")
            details = etiquette(f"{c.get('hote')}:{c.get('port')} · {c.get('transport', 'tcp').upper()} · "
                                f"{'Contact ID' if c.get('protocole') == 'ADM-CID' else 'SIA'} · client {c.get('compte')} · "
                                f"{chiffre} · fichiers : {fm.split(' (')[0] if fm else '—'}")
            g.addWidget(details, 1, 0, 1, 2)
            info = etiquette("")
            g.addWidget(info, 2, 0, 1, 2)
            rb = Rangee()
            bt = Bouton("Tester", "discret", "lecture")
            bt.clicked.connect(lambda _=False, i=c["id"], b=bt: self._tester(i, b))
            bm = Bouton("Modifier", "discret")
            bm.clicked.connect(lambda _=False, x=c: self._modifier(x))
            bs = Bouton("Supprimer", "danger")
            bs.clicked.connect(lambda _=False, x=c: self._supprimer(x))
            for w in (bt, bm, bs):
                rb.addWidget(w)
            g.addLayout(rb, 3, 0, 1, 2)
            g.setColumnStretch(0, 1)
            self.zone_centrales.addWidget(fr)
            self.cartes[c["id"]] = (etat, info)
        self.rafraichir()

    def _modifier(self, c):
        if self.fen.kiosque and not self.fen.demander_code_kiosque("Modifier la télésurveillance"):
            return
        d = DialogueCentrale(self, c)
        if d.exec():
            self.fen.log_systeme(f"Télésurveillance : centrale « {d.c['nom']} » "
                                 f"{'ajoutée' if d.nouvelle else 'modifiée'}.", "info")
            self._remplir_centrales()

    def _supprimer(self, c):
        if self.fen.kiosque and not self.fen.demander_code_kiosque("Modifier la télésurveillance"):
            return
        n = self.gestion.en_attente(c["id"])
        texte = f"Supprimer la centrale « {c['nom']} » ?"
        if n:
            texte += f"\n\n{n} envoi(s) en attente pour elle seront abandonnés."
        if QMessageBox.question(self, "Télésurveillance", texte) != QMessageBox.StandardButton.Yes:
            return
        self.gestion.supprimer_centrale(c["id"])
        self.fen.log_systeme(f"Télésurveillance : centrale « {c['nom']} » supprimée.", "info")
        self._remplir_centrales()

    def _tester(self, ident, bouton):
        bouton.setEnabled(False)
        bouton.setText("Test en cours…")

        def fin(r):
            bouton.setEnabled(True)
            bouton.setText("Tester")
            QMessageBox.information(self, "Test de transmission", r)

        def erreur(e):
            bouton.setEnabled(True)
            bouton.setText("Tester")
            QMessageBox.warning(self, "Test de transmission", f"Échec : {e}")
        en_arriere_plan(lambda: self.gestion.test(ident), fin, erreur)

    # --- rafraîchissement -----------------------------------------------------------------------
    def rafraichir(self):
        if not self.isVisible():
            return
        for ident, (etat, info) in self.cartes.items():
            ce = self.gestion.centrales.get(ident)
            if ce is None:
                continue
            lib, coul = ETATS.get(ce.etat, ETATS["attente"])
            etat.setText(lib)
            etat.setStyleSheet(f"background: {coul}26; color: {coul}; border-radius: 10px; padding: 2px 10px; font-weight: 700;")
            n = self.gestion.en_attente(ident)
            morceaux = []
            if ce.dernier_ack:
                morceaux.append(f"dernier accusé de réception il y a {int(time.time() - ce.dernier_ack)} s")
            if n:
                morceaux.append(f"{n} envoi(s) en attente")
            if ce.etat == "erreur" and ce.message:
                morceaux.append(ce.message)
            info.setText(" · ".join(morceaux) or "Aucun envoi pour l'instant.")
        if self.gestion.version_journal != self._version_journal:
            self._version_journal = self.gestion.version_journal
            lignes = list(self.gestion.journal)[:200]
            self.journal.setRowCount(len(lignes))
            for r, j in enumerate(lignes):
                for col, cle in enumerate(("heure", "centrale", "evenement", "etat", "detail")):
                    val = {"ok": "Envoyé", "erreur": "Erreur"}.get(j[cle], j[cle]) if cle == "etat" else j[cle]
                    it = QTableWidgetItem(str(val))
                    if cle == "etat":
                        it.setForeground(Qt.GlobalColor.green if j["etat"] == "ok" else Qt.GlobalColor.red)
                    self.journal.setItem(r, col, it)

    def showEvent(self, e):
        super().showEvent(e)
        self._remplir_zones()
        self.rafraichir()
