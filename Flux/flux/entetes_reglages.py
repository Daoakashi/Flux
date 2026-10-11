"""En-têtes spéciaux de l'éditeur de réglages : notifications (tests), mises à jour, mode développeur
(version.json, éditeur de config.json, publication)."""

import json
import os

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QFont, QTextCharFormat, QTextCursor, QColor
from PySide6.QtWidgets import (QComboBox, QDialog, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QMessageBox, QPlainTextEdit, QTextEdit, QVBoxLayout, QWidget)

from . import config
from .config import PAR_CLE, RACINE, libelle_version
from .notifications import CANAUX, NOMS_CANAUX, canaux_actifs, telegram_trouver_chat
from .taches import en_arriere_plan
from .theme import C
from .widgets import Bouton, etiquette


def _boite():
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(8)
    return w, v


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
def entete_notifications(page):
    fen, cfg = page.fen, page.cfg
    w, v = _boite()
    actifs = canaux_actifs(cfg)
    etat = ("Canaux actifs : " + ", ".join(NOMS_CANAUX[c] for c in actifs)) if actifs else "Aucun canal activé."
    if actifs and not cfg.get("notif.actif"):
        etat += " L'interrupteur général « Envoyer des notifications » est coupé."
    v.addWidget(etiquette(etat))
    h = QHBoxLayout()
    h.setSpacing(6)
    h.addWidget(QLabel("Tester :"))
    for canal, nom in CANAUX:
        b = Bouton(nom, "discret")
        b.setToolTip(f"Envoie une notification de test par {nom}, même si le canal est désactivé")
        b.clicked.connect(lambda _=False, c=canal: _tester(fen, c))
        h.addWidget(b)
    h.addStretch(1)
    v.addLayout(h)
    h2 = QHBoxLayout()
    b = Bouton("Trouver mon identifiant Telegram", "discret")
    b.clicked.connect(lambda: _trouver_chat(page))
    h2.addWidget(b)
    h2.addStretch(1)
    v.addLayout(h2)
    v.addWidget(etiquette(
        "Le plus simple : ntfy (gratuit, sans compte). Installez l'application ntfy sur le téléphone, abonnez-vous à "
        "un sujet, puis saisissez le même sujet ici. Telegram est gratuit et envoie aussi la photo. La liste noire "
        "est toujours notifiée immédiatement ; l'appel téléphonique est réservé à la liste noire par défaut."))
    return w


def _tester(fen, canal):
    fen.toast(f"Test {NOMS_CANAUX[canal]} en cours…")
    fen.notifieur.tester(canal, lambda ok, msg: fen.log_systeme(msg, "ok" if ok else "erreur"))


def _trouver_chat(page):
    fen, cfg = page.fen, page.cfg
    ligne = page.lignes.get("telegram.jeton")
    if ligne is not None and ligne.editeur.text().strip():
        cfg.set("telegram.jeton", ligne.editeur.text().strip())

    def recu(chats):
        if not chats:
            fen.toast("Aucun message reçu par le bot : envoyez-lui « bonjour » sur Telegram puis réessayez.", "erreur")
            return
        if len(chats) == 1:
            choix = chats[0]
        else:
            libelles = [f"{nom} ({cid})" for cid, nom in chats]
            texte, ok = QInputDialog.getItem(page, "Telegram", "Discussion qui recevra les alertes :", libelles, 0,
                                             False)
            if not ok:
                return
            choix = chats[libelles.index(texte)]
        cfg.set("telegram.chat", choix[0])
        fen.toast(f"Telegram : discussion « {choix[1]} » enregistrée.", "ok")

    page._tache_tg = en_arriere_plan(telegram_trouver_chat, recu, lambda e: fen.toast(f"Telegram : {e}", "erreur"),
                                     cfg.get("telegram.jeton"))


# ---------------------------------------------------------------------------
# Mises à jour
# ---------------------------------------------------------------------------
def entete_maj(page):
    from .mise_a_jour import depot
    fen, cfg = page.fen, page.cfg
    w, v = _boite()
    d = depot(cfg)
    v.addWidget(etiquette(f"Version installée : {libelle_version(config.APP_VERSION, config.APP_CANAL)}"
                          + (f" · dépôt : github.com/{d}" if d else " · aucun dépôt GitHub configuré")))
    h = QHBoxLayout()
    b = Bouton("Rechercher maintenant", "primaire")
    b.clicked.connect(lambda: fen.verifier_mises_a_jour(manuel=True))
    h.addWidget(b)
    if d:
        b2 = Bouton("Ouvrir la page GitHub", "discret")
        b2.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(f"https://github.com/{d}/releases")))
        h.addWidget(b2)
    h.addStretch(1)
    v.addLayout(h)
    page.lbl_maj = etiquette(getattr(fen, "etat_maj", ""))
    v.addWidget(page.lbl_maj)
    v.addWidget(etiquette(
        "Avant d'installer, Flux sauvegarde le code actuel dans le dossier « sauvegardes ». Vos réglages, la base, "
        "les modèles et l'environnement Python ne sont jamais touchés."))
    return w


# ---------------------------------------------------------------------------
# Développeur
# ---------------------------------------------------------------------------
def entete_developpeur(page):
    fen = page.fen
    w, v = _boite()
    v.addWidget(etiquette("VERSION DU PROGRAMME (version.json)", "section"))
    g = QGridLayout()
    g.setHorizontalSpacing(12)
    vv = config.lire_version()
    ch_version = QLineEdit(vv["version"])
    ch_version.setPlaceholderText("0.3.0")
    ch_canal = QComboBox()
    for c in ("alpha", "beta", "rc", "stable"):
        ch_canal.addItem(c, c)
    ch_canal.setCurrentIndex(max(0, ch_canal.findData(vv["canal"])))
    ch_depot = QLineEdit(vv["depot"])
    ch_depot.setPlaceholderText("propriétaire/dépôt")
    ch_date = QLineEdit(vv["date"])
    ch_date.setPlaceholderText("2026-10-07")
    for i, (lib, ch) in enumerate((("Version", ch_version), ("Canal", ch_canal), ("Dépôt GitHub", ch_depot),
                                   ("Date", ch_date))):
        g.addWidget(QLabel(lib), i // 2, (i % 2) * 2)
        g.addWidget(ch, i // 2, (i % 2) * 2 + 1)
    g.setColumnStretch(1, 1)
    g.setColumnStretch(3, 1)
    v.addLayout(g)
    apercu = etiquette("")

    def maj_apercu():
        apercu.setText(f"Affichée : « {libelle_version(ch_version.text().strip() or '0', ch_canal.currentData())} ». "
                       "C'est ce numéro que les mises à jour comparent : augmentez-le avant chaque publication.")

    ch_version.textChanged.connect(maj_apercu)
    ch_canal.currentIndexChanged.connect(maj_apercu)
    maj_apercu()
    v.addWidget(apercu)

    def enregistrer():
        from .mise_a_jour import analyser_version
        texte = ch_version.text().strip()
        if analyser_version(texte)[0] == (0, 0, 0) and not texte.startswith("0.0"):
            fen.toast("Version invalide : utilisez un numéro comme 0.3.0", "erreur")
            return
        config.ecrire_version({"version": texte, "canal": ch_canal.currentData(), "depot": ch_depot.text().strip(),
                               "date": ch_date.text().strip()})
        fen.appliquer_identite()
        fen.toast("version.json enregistré.", "ok")

    h = QHBoxLayout()
    b = Bouton("Enregistrer version.json", "primaire")
    b.clicked.connect(enregistrer)
    h.addWidget(b)
    h.addStretch(1)
    v.addLayout(h)

    v.addSpacing(6)
    v.addWidget(etiquette("FICHIERS", "section"))
    h2 = QHBoxLayout()
    for texte, f in (("Modifier config.json…", lambda: DialogueJson(fen).exec()),
                     ("Ouvrir le dossier de Flux", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(RACINE))),
                     ("Préparer une publication (.zip)", lambda: _publication(fen))):
        b = Bouton(texte, "discret")
        b.clicked.connect(f)
        h2.addWidget(b)
    h2.addStretch(1)
    v.addLayout(h2)
    v.addWidget(etiquette(
        "Publication : augmentez la version, cliquez « Préparer une publication », puis sur GitHub créez une "
        "release avec le tag v<version> (cochez « pre-release » pour alpha et beta) et joignez le zip du dossier "
        "« publication ». Les autres installations la proposeront au prochain démarrage."))
    return w


def _publication(fen):
    from .mise_a_jour import preparer_publication

    def fini(chemin):
        fen.toast(f"Archive prête : {os.path.basename(chemin)}", "ok")
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(chemin)))

    fen._tache_pub = en_arriere_plan(preparer_publication, fini, lambda e: fen.toast(f"Publication : {e}", "erreur"))


class DialogueJson(QDialog):
    """Éditeur brut de config.json avec vérification avant d'appliquer."""

    def __init__(self, fen):
        super().__init__(fen)
        self.fen, self.cfg = fen, fen.cfg
        self.setWindowTitle("config.json — éditeur développeur")
        self.resize(900, 680)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 18, 18, 14)
        v.addWidget(etiquette(f"{self.cfg.chemin} — les valeurs hors limites sont corrigées automatiquement, les clés "
                              "inconnues sont ignorées. Les changements de caméras (« flux ») s'appliquent au prochain "
                              "démarrage."))
        self.editeur = QPlainTextEdit()
        f = QFont("Cascadia Mono")
        f.setStyleHint(QFont.StyleHint.Monospace)
        self.editeur.setFont(f)
        self.editeur.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.page_fen = fen
        fen.page_cameras.sauver()
        self.cfg.sauver()
        try:
            with open(self.cfg.chemin, encoding="utf-8") as fi:
                self.original = fi.read()
        except OSError:
            self.original = json.dumps(self.cfg.exporter_dict(), indent=2, ensure_ascii=False)
        self.editeur.setPlainText(self.original)
        v.addWidget(self.editeur, 1)
        self.etat = etiquette("")
        v.addWidget(self.etat)
        h = QHBoxLayout()
        b = Bouton("Vérifier", "discret")
        b.clicked.connect(self.verifier)
        h.addWidget(b)
        b = Bouton("Annuler les modifications", "discret")
        b.clicked.connect(lambda: self.editeur.setPlainText(self.original))
        h.addWidget(b)
        h.addStretch(1)
        b = Bouton("Fermer", "discret")
        b.clicked.connect(self.reject)
        h.addWidget(b)
        b = Bouton("Enregistrer et appliquer", "primaire")
        b.clicked.connect(self.enregistrer)
        h.addWidget(b)
        v.addLayout(h)

    def _surligner(self, ligne):
        sel = QTextEdit.ExtraSelection()
        fond = QColor(C["danger"])
        fond.setAlpha(70)
        sel.format.setBackground(fond)
        sel.format.setProperty(QTextCharFormat.Property.FullWidthSelection, True)
        bloc = self.editeur.document().findBlockByNumber(max(0, ligne - 1))
        sel.cursor = QTextCursor(bloc)
        self.editeur.setExtraSelections([sel])
        self.editeur.setTextCursor(QTextCursor(bloc))

    def verifier(self):
        """Renvoie (données, remarques) ou None si le JSON est invalide."""
        self.editeur.setExtraSelections([])
        try:
            d = json.loads(self.editeur.toPlainText())
        except json.JSONDecodeError as e:
            self._surligner(e.lineno)
            self.etat.setText(f"JSON invalide ligne {e.lineno}, colonne {e.colno} : {e.msg}")
            self.etat.setStyleSheet(f"color: {C['danger']};")
            return None
        if not isinstance(d, dict) or not isinstance(d.get("reglages", {}), dict):
            self.etat.setText("Structure inattendue : il faut un objet avec une section « reglages ».")
            self.etat.setStyleSheet(f"color: {C['danger']};")
            return None
        remarques = []
        for cle, val in d.get("reglages", {}).items():
            r = PAR_CLE.get(cle)
            if r is None:
                remarques.append(f"clé inconnue ignorée : {cle}")
            elif r.valider(val) != val and not (r.type == "float" and isinstance(val, int) and float(val) == r.valider(val)):
                remarques.append(f"{cle} : {val!r} corrigé en {r.valider(val)!r}")
        self.etat.setText("JSON valide." + (" " + " · ".join(remarques[:6]) if remarques else "")
                          + (f" (+{len(remarques) - 6})" if len(remarques) > 6 else ""))
        self.etat.setStyleSheet(f"color: {C['attention'] if remarques else C['succes']};")
        return d, remarques

    def enregistrer(self):
        res = self.verifier()
        if res is None:
            return
        d, _ = res
        flux_change = d.get("flux") != self.cfg.flux or d.get("groupes", []) != self.cfg.groupes
        tmp = self.cfg.chemin + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(self.editeur.toPlainText())
        os.replace(tmp, self.cfg.chemin)
        changes = self.cfg.recharger()
        self.fen.appliquer_apparence()
        self.fen.appliquer_identite()
        self.fen.page_reglages._construire_droite()
        self.original = self.editeur.toPlainText()
        if flux_change:
            self.fen.cameras_au_redemarrage = True
            QMessageBox.information(self, "Caméras", "La liste des caméras a changé : redémarrez Flux pour l'appliquer. "
                                    "Ne modifiez pas les caméras dans l'application d'ici là.")
        self.fen.toast(f"config.json appliqué ({len(changes)} réglage(s) modifié(s)).", "ok")


# ---------------------------------------------------------------------------
# Vidéos des passages
# ---------------------------------------------------------------------------
def entete_clips(page):
    from .clips import executable_ffmpeg
    from .notifications import ENVOIS_VIDEO
    cfg = page.cfg
    w, v = _boite()
    exe = executable_ffmpeg()
    v.addWidget(etiquette("Encodeur vidéo : ffmpeg trouvé — vidéos H.264 lisibles sur tous les téléphones." if exe else
                          f"Encodeur vidéo absent : relancez {config.INSTALLATEUR}. En attendant, les vidéos utilisent le codec "
                          "d'OpenCV (lisibles sur PC, pas toujours sur téléphone)."))
    actifs = [NOMS_CANAUX[c] for c in canaux_actifs(cfg) if c in ENVOIS_VIDEO] if cfg.get("notif.actif") else []
    v.addWidget(etiquette(("Les vidéos partent par : " + ", ".join(actifs) +
                           (" et mail" if cfg.get("mail.actif") and cfg.get("clips.mail") else "")) if actifs or
                          (cfg.get("mail.actif") and cfg.get("clips.mail")) else
                          "Aucun canal ne reçoit les vidéos : activez Telegram, ntfy ou Discord (Notifications) ou les "
                          "mails. Elles restent enregistrées sur le PC."))
    h = QHBoxLayout()
    b = Bouton("Ouvrir le dossier des vidéos", "discret", "dossier")

    def ouvrir():
        d = os.path.join(cfg.dossier_sortie(), "videos")
        os.makedirs(d, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(d))

    b.clicked.connect(ouvrir)
    h.addWidget(b)
    h.addStretch(1)
    v.addLayout(h)
    v.addWidget(etiquette("Bouton caméra (à côté de la capture) : enregistre une vidéo à la main. Double-clic sur une "
                          "action « Vidéo » du journal pour la regarder."))
    return w
