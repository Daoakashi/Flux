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
from .widgets import Bouton, Rangee, etiquette


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
    h = Rangee()
    h.setSpacing(6)
    h.addWidget(QLabel("Tester :"))
    for canal, nom in CANAUX:
        b = Bouton(nom, "discret")
        b.setToolTip(f"Envoie une notification de test par {nom}, même si le canal est désactivé")
        b.clicked.connect(lambda _=False, c=canal: _tester(fen, c))
        h.addWidget(b)
    h.addStretch(1)
    v.addLayout(h)
    h2 = Rangee()
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
    h = Rangee()
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
        g.addWidget(QLabel(lib), i, 0)
        g.addWidget(ch, i, 1)
    g.setColumnStretch(1, 1)
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

    h = Rangee()
    b = Bouton("Enregistrer version.json", "primaire")
    b.clicked.connect(enregistrer)
    h.addWidget(b)
    h.addStretch(1)
    v.addLayout(h)

    v.addSpacing(6)
    v.addWidget(etiquette("FICHIERS", "section"))
    h2 = Rangee()
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
        "release avec le tag v<version> (cochez « pre-release » pour alpha et beta) et joignez les deux zip du "
        "dossier « publication » (Windows et Linux). Les autres installations la proposeront au prochain démarrage."))
    return w


def _publication(fen):
    from .mise_a_jour import preparer_publication

    def fini(chemins):
        fen.toast("Archives prêtes : " + ", ".join(os.path.basename(c) for c in chemins), "ok")
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(chemins[0])))

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
    h = Rangee()
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


# ---------------------------------------------------------------------------
# Plage horaire de la détection
# ---------------------------------------------------------------------------
def entete_horaire(page):
    from PySide6.QtCore import QTime
    from PySide6.QtWidgets import QFrame, QTimeEdit
    from . import horaire as H
    from .widgets import Interrupteur, Pastille
    cfg = page.cfg
    cadre = QFrame()
    cadre.setObjectName("carte")
    v = QVBoxLayout(cadre)
    v.setContentsMargins(14, 12, 14, 12)
    v.setSpacing(8)
    h0 = QHBoxLayout()
    titre = QLabel("Plage horaire de la détection")
    titre.setObjectName("titre_section")
    h0.addWidget(titre)
    h0.addStretch(1)
    inter = Interrupteur()
    h0.addWidget(inter)
    v.addLayout(h0)
    p = H.lire(cfg)
    inter.regler(p["actif"])
    ligne = Rangee()
    ligne.setSpacing(8)
    ligne.addWidget(QLabel("De"))
    debut, fin = QTimeEdit(), QTimeEdit()
    for t, val in ((debut, p["debut"]), (fin, p["fin"])):
        t.setDisplayFormat("HH:mm")
        t.setTime(QTime.fromString(val, "HH:mm"))
        t.setFixedWidth(90)
    ligne.addWidget(debut)
    ligne.addWidget(QLabel("à"))
    ligne.addWidget(fin)
    ligne.addSpacing(10)
    modeles = QComboBox()
    ligne.addWidget(modeles)
    ligne.addStretch(1)
    v.addLayout(ligne)
    ligne_jours = Rangee()
    ligne_jours.setSpacing(6)
    pastilles = []
    for i, nom in enumerate(H.JOURS_COURTS):
        pa = Pastille(nom, C["accent"])
        pa.setChecked(i in p["jours"])
        pastilles.append(pa)
        ligne_jours.addWidget(pa)
    ligne_jours.addStretch(1)
    v.addLayout(ligne_jours)
    resume = etiquette("")
    v.addWidget(resume)

    def lire_ui():
        jours = [i for i, pa in enumerate(pastilles) if pa.isChecked()] or list(range(7))
        return {"actif": inter.isChecked(), "debut": debut.time().toString("HH:mm"), "fin": fin.time().toString("HH:mm"),
                "jours": jours}

    def maj_resume():
        x = lire_ui()
        for wdg in [debut, fin, *pastilles]:
            wdg.setEnabled(x["actif"])
        if not x["actif"]:
            resume.setText("Désactivée : la détection tourne à toute heure (selon les interrupteurs de Flux et de "
                           "chaque caméra). Réglable aussi depuis FluxLite, Flux Remote et l'interface web.")
            return
        maintenant = "en ce moment : détection active" if H.dans_plage(x) else "en ce moment : hors plage, détection en pause"
        prochain = H.prochain_changement(x)
        resume.setText(f"{H.texte(x)} — {maintenant}"
                       + (f" jusqu'à {prochain:%H:%M}" + ("" if prochain.date() == __import__('datetime').date.today()
                                                          else f" ({H.JOURS[prochain.weekday()]})") if prochain else "")
                       + ". En dehors, les images restent affichées mais rien n'est analysé (ni alerte ni vidéo).")

    def enregistrer(*_):
        H.enregistrer(cfg, lire_ui())
        maj_resume()

    MODELES = [("Modèles…", None), ("Journée : 6 h – 22 h", ("06:00", "22:00", range(7))),
               ("Nuit : 22 h – 6 h", ("22:00", "06:00", range(7))),
               ("Heures de bureau (lun-ven 8 h – 18 h)", ("08:00", "18:00", range(5))),
               ("Magasin fermé (20 h – 8 h)", ("20:00", "08:00", range(7))),
               ("Week-end, toute la journée", ("00:00", "00:00", [5, 6]))]
    for nom, _ in MODELES:
        modeles.addItem(nom)

    def appliquer_modele(i):
        m = MODELES[i][1]
        if m is None:
            return
        d, f, j = m
        for wdg in pastilles:
            wdg.blockSignals(True)
        inter.regler(True)
        debut.setTime(QTime.fromString(d, "HH:mm"))
        fin.setTime(QTime.fromString(f, "HH:mm"))
        for k, pa in enumerate(pastilles):
            pa.setChecked(k in list(j))
        for wdg in pastilles:
            wdg.blockSignals(False)
        enregistrer()
        modeles.blockSignals(True)
        modeles.setCurrentIndex(0)
        modeles.blockSignals(False)

    modeles.currentIndexChanged.connect(appliquer_modele)
    inter.toggled.connect(enregistrer)
    debut.editingFinished.connect(enregistrer)
    fin.editingFinished.connect(enregistrer)
    debut.timeChanged.connect(lambda *_: maj_resume())
    fin.timeChanged.connect(lambda *_: maj_resume())
    for pa in pastilles:
        pa.toggled.connect(enregistrer)
    maj_resume()

    def externe(cle, _v):  # changé à distance (FluxLite, Remote, web)
        if not cle.startswith("horaire."):
            return
        x = H.lire(cfg)
        inter.regler(x["actif"])
        for t, val in ((debut, x["debut"]), (fin, x["fin"])):
            t.blockSignals(True)
            t.setTime(QTime.fromString(val, "HH:mm"))
            t.blockSignals(False)
        for i, pa in enumerate(pastilles):
            pa.blockSignals(True)
            pa.setChecked(i in x["jours"])
            pa.blockSignals(False)
        maj_resume()

    if hasattr(page, "ecouteurs_entete"):
        page.ecouteurs_entete.append(externe)
    return cadre


# ---------------------------------------------------------------------------
# Espace disque
# ---------------------------------------------------------------------------
def entete_stockage(page):
    from PySide6.QtWidgets import QProgressBar
    from . import stockage
    fen, cfg = page.fen, page.cfg
    w, v = _boite()
    barre = QProgressBar()
    barre.setTextVisible(False)
    barre.setFixedHeight(10)
    titre = etiquette("Calcul de l'espace utilisé…")
    detail = etiquette("")
    v.addWidget(titre)
    v.addWidget(barre)
    v.addWidget(detail)

    def afficher(e):
        try:
            _afficher(e)
        except RuntimeError:  # encadré fermé entre-temps
            pass

    def _afficher(e):
        lim = float(cfg.get("stockage.limite") or 0)
        t = stockage.texte_taille
        titre.setText(f"Flux utilise {t(e['total'])}" + (f" sur {t(int(lim * stockage.GO))}" if lim else " (sans limite)")
                      + (f" · {t(e['libre'])} libres sur le disque" if e["libre"] is not None else ""))
        barre.setRange(0, 1000)
        barre.setValue(int(min(1.0, e["total"] / (lim * stockage.GO)) * 1000) if lim else 0)
        import time as _t
        ancien = _t.strftime("%d/%m/%Y", _t.localtime(e["plus_ancien"])) if e["plus_ancien"] else "—"
        detail.setText(f"Vidéos {t(e['videos'])} · photos {t(e['photos'])} · bases (actions, alertes FluxLite) "
                       f"{t(e['bases'])} · journal {t(e['journal'])} · {e['fichiers']} fichier(s), le plus ancien du {ancien}. "
                       "Au-delà de la limite, les plus anciens sont supprimés en premier ; les personnes enregistrées, "
                       "les comptes et les réglages ne sont jamais touchés.")

    def calculer():
        en_arriere_plan(lambda: stockage.etat(cfg.dossier_sortie(), fen.chemins_bases()), afficher)

    h = Rangee()
    b = Bouton("Faire le ménage maintenant", "primaire")
    b.clicked.connect(lambda: fen.menage_disque(manuel=True))
    h.addWidget(b)
    bo = Bouton("Ouvrir le dossier", "discret", "dossier")
    bo.clicked.connect(lambda: (os.makedirs(cfg.dossier_sortie(), exist_ok=True),
                                QDesktopServices.openUrl(QUrl.fromLocalFile(cfg.dossier_sortie()))))
    h.addWidget(bo)
    h.addStretch(1)
    v.addLayout(h)
    try:
        fen.signal_disque.connect(calculer)
    except (AttributeError, RuntimeError):
        pass
    calculer()
    return w


# ---------------------------------------------------------------------------
# IVS et alarme sonore
# ---------------------------------------------------------------------------
def entete_ivs(page):
    fen = page.fen
    w, v = _boite()
    v.addWidget(etiquette(
        "Les flèches IVS se tracent dans l'onglet de chaque caméra (section IVS, entre les options et les zones) : "
        "une personne qui va de A vers B en suivant la flèche est signalée. Le sens inverse ne déclenche rien. "
        "Avec l'alarme cochée, c'est une alerte (notifications, mail, FluxLite) et ce PC joue le son choisi ici."))
    h = Rangee()
    b = Bouton("Écouter le son", "primaire", "lecture")
    b.clicked.connect(lambda: fen.alarme.jouer(repetitions=1))
    h.addWidget(b)
    bs = Bouton("Arrêter", "discret")
    bs.clicked.connect(lambda: fen.alarme.arreter())
    h.addWidget(bs)
    bf = Bouton("Choisir un fichier .wav…", "discret", "dossier")

    def choisir():
        from PySide6.QtWidgets import QFileDialog
        f, _ = QFileDialog.getOpenFileName(page, "Son de l'alarme", "", "Sons WAV (*.wav)")
        if f:
            page.cfg.set("ivs.fichier_son", f)
            page.cfg.set("ivs.son", "fichier")
    bf.clicked.connect(choisir)
    h.addWidget(bf)
    v.addLayout(h)
    return w


# ---------------------------------------------------------------------------
# Supervision centrale (Flux Central)
# ---------------------------------------------------------------------------
def entete_central(page):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QLineEdit
    from .central import ErreurCentrale
    from .taches import en_arriere_plan
    fen = page.fen
    agent = fen.central
    w, v = _boite()
    v.addWidget(etiquette(
        "Relie ce PC à la console de supervision de votre prestataire (Flux Central) : elle voit si Flux tourne, "
        "l'état des caméras et du disque, et reçoit le type et l'heure des alertes, sans photo ni donnée "
        "biométrique. Elle peut aussi piloter la détection comme FluxLite. Chaque échange est chiffré et signé."))
    etat = etiquette(agent.texte_etat())
    v.addWidget(etat)
    zone_relier = QWidget()
    vr = QVBoxLayout(zone_relier)
    vr.setContentsMargins(0, 0, 0, 0)
    adresse = QLineEdit()
    adresse.setPlaceholderText("https://console.exemple.be")
    code = QLineEdit()
    code.setPlaceholderText("Code d'inscription (ex. ABCD-EFGH-JKLM)")
    code.setMaxLength(20)
    vr.addWidget(adresse)
    vr.addWidget(code)
    h = Rangee()
    b_relier = Bouton("Relier ce PC", "primaire", "lien")
    h.addWidget(b_relier)
    vr.addLayout(h)
    v.addWidget(zone_relier)
    h2 = Rangee()
    b_delier = Bouton("Délier ce PC", "danger")
    h2.addWidget(b_delier)
    v.addLayout(h2)

    def maj():
        try:
            etat.setText(agent.texte_etat())
        except RuntimeError:
            return
        zone_relier.setVisible(not agent.relie())
        b_delier.setVisible(agent.relie())

    def relier():
        b_relier.setEnabled(False)
        etat.setText("Connexion à la console…")

        def fini(d):
            b_relier.setEnabled(True)
            code.clear()
            page.cfg.set("central.actif", True)
            fen.toast(f"Relié à la console ({d.get('organisation', '')}).", "ok")
            fen.log_systeme(f"Supervision centrale : PC relié à « {d.get('organisation', '')} ».", "ok")
            maj()

        def erreur(e):
            b_relier.setEnabled(True)
            etat.setText(f"Impossible de relier ce PC : {e}" if isinstance(e, ErreurCentrale) else f"Erreur : {e}")
        en_arriere_plan(lambda: agent.relier(adresse.text(), code.text()), fini, erreur)

    def delier():
        from PySide6.QtWidgets import QMessageBox
        if QMessageBox.question(page, "Délier ce PC", "Ce PC n'enverra plus rien à la console. Pour le relier à "
                                "nouveau, il faudra un nouveau code d'inscription. Continuer ?") == QMessageBox.StandardButton.Yes:
            agent.delier()
            fen.log_systeme("Supervision centrale : PC délié de la console.", "info")
            maj()

    b_relier.clicked.connect(relier)
    code.returnPressed.connect(relier)
    b_delier.clicked.connect(delier)
    minuterie = QTimer(w)
    minuterie.timeout.connect(maj)
    minuterie.start(2000)
    maj()
    return w


# ---------------------------------------------------------------------------
# Mode kiosque (Linux) : activer / désactiver sans terminal
# ---------------------------------------------------------------------------
class DialogueCodeKiosque(QDialog):
    """Choix du code administrateur du kiosque (saisi deux fois ; le clavier visuel peut servir)."""

    def __init__(self, parent, titre="Code administrateur du kiosque"):
        super().__init__(parent)
        self.setWindowTitle(titre)
        self.setMinimumWidth(420)
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 18)
        v.setSpacing(10)
        t = QLabel(titre)
        t.setObjectName("titre")
        v.addWidget(t)
        v.addWidget(etiquette("Ce code sert à quitter le kiosque (Ctrl+Alt+Maj+Q, bouton ⏻) et à modifier le réseau ou "
                              "la télésurveillance en kiosque. 4 caractères minimum. Il n'est jamais enregistré en clair."))
        self.a = QLineEdit()
        self.b = QLineEdit()
        for champ, texte in ((self.a, "Code administrateur"), (self.b, "Retapez le code")):
            champ.setEchoMode(QLineEdit.EchoMode.Password)
            champ.setPlaceholderText(texte)
            v.addWidget(champ)
        self.lbl = etiquette("")
        self.lbl.setStyleSheet(f"color: {C['danger']};")
        v.addWidget(self.lbl)
        h = QHBoxLayout()
        h.addStretch(1)
        b0 = Bouton("Annuler")
        b0.setAutoDefault(False)
        b0.clicked.connect(self.reject)
        b1 = Bouton("Continuer", "primaire")
        b1.setDefault(True)
        b1.clicked.connect(self._ok)
        h.addWidget(b0)
        h.addWidget(b1)
        v.addLayout(h)
        self.a.setFocus()

    def code(self):
        return self.a.text()

    def _ok(self):
        if len(self.a.text()) < 4:
            self.lbl.setText("Trop court : 4 caractères minimum.")
        elif self.a.text() != self.b.text():
            self.lbl.setText("Les deux codes sont différents.")
        else:
            self.accept()


def entete_kiosque(page):
    import getpass
    from PySide6.QtWidgets import QCheckBox, QSpinBox
    from . import kiosque
    fen = page.fen
    w, v = _boite()
    if kiosque.actif():
        v.addWidget(etiquette("Le mode kiosque est actif sur ce PC. Pour le désactiver ou changer son code, quittez "
                              "d'abord le kiosque (bouton ⏻ du clavier visuel ou « ⏻ Quitter » en bas de la fenêtre), "
                              "puis ouvrez cette page depuis votre session habituelle."))
        return w
    v.addWidget(etiquette(
        "Le PC démarre directement sur Flux, en plein écran, sans bureau ni barre des tâches ; Flux se relance tout "
        "seul et l'écran ne se met jamais en veille. Une fenêtre du système demandera le mot de passe de ce PC "
        "(administrateur) : aucun terminal n'est nécessaire. Linux Mint, Ubuntu ou Debian (écran de connexion "
        "LightDM ou GDM) ; Flux doit être installé avec installer.sh."))
    etat = etiquette("")
    v.addWidget(etat)
    # options
    ligne = Rangee()
    c_redem = QCheckBox("Redémarrer le PC chaque nuit à")
    h_redem = QSpinBox()
    h_redem.setRange(0, 23)
    h_redem.setValue(4)
    h_redem.setSuffix(" h")
    c_verrou = QCheckBox("Bloquer les terminaux (Ctrl+Alt+F1…F6)")
    ligne.addWidget(c_redem)
    ligne.addWidget(h_redem)
    v.addLayout(ligne)
    v.addWidget(c_verrou)
    v.addWidget(etiquette("Avec les terminaux bloqués, la seule sortie est Ctrl+Alt+Maj+Q (ou ⏻) puis le code."))
    boutons = Rangee()
    b_act = Bouton("Activer le mode kiosque", "primaire")
    b_code = Bouton("Changer le code", "discret")
    b_des = Bouton("Désactiver", "danger")
    for b in (b_act, b_code, b_des):
        boutons.addWidget(b)
    v.addLayout(boutons)
    sortie = QPlainTextEdit()
    sortie.setReadOnly(True)
    sortie.setMaximumHeight(170)
    sortie.setVisible(False)
    v.addWidget(sortie)

    def maj():
        e = kiosque.etat()
        if e["installe"]:
            txt = (f"Mode kiosque ACTIF — compte : {e['utilisateur'] or '?'} · code : "
                   f"{'défini' if e['code'] else 'absent'}"
                   + (f" · redémarrage chaque nuit à {e['redemarrage']} h" if e["redemarrage"] else "")
                   + (" · terminaux bloqués" if e["verrou"] else ""))
        else:
            txt = "Mode kiosque inactif."
        etat.setText(txt)
        b_act.setText("Réappliquer les options" if e["installe"] else "Activer le mode kiosque")
        b_code.setVisible(e["installe"])
        b_des.setVisible(e["installe"])
        h_redem.setEnabled(c_redem.isChecked())

    def lancer(action, code=None, fini_message=""):
        for b in (b_act, b_code, b_des):
            b.setEnabled(False)
        sortie.setVisible(True)
        sortie.setPlainText("Autorisez l'opération dans la fenêtre du système (mot de passe de ce PC)…\n"
                            "L'installation d'Openbox peut prendre une minute.")
        heure = str(h_redem.value()) if c_redem.isChecked() else ""

        def travail():
            return kiosque.lancer(action, utilisateur=getpass.getuser(), heure=heure,
                                  verrouiller=c_verrou.isChecked(), code=code)

        def fin(res):
            try:
                for b in (b_act, b_code, b_des):
                    b.setEnabled(True)
                ok, texte = res
                sortie.setPlainText(texte or ("Terminé." if ok else "Échec."))
                maj()
            except RuntimeError:
                return
            if not ok:
                fen.toast("Le kiosque n'a pas été modifié (détails dans le cadre sous les boutons).", "erreur")
                return
            fen.cfg_journal_kiosque(fini_message)
            if action == "activer":
                r = QMessageBox.question(page, "Mode kiosque activé",
                                         "Le mode kiosque est activé. Redémarrer le PC maintenant pour l'essayer ?")
                if r == QMessageBox.StandardButton.Yes:
                    import subprocess
                    try:
                        subprocess.Popen(["systemctl", "reboot"])
                    except OSError:
                        fen.toast("Redémarrage impossible : redémarrez le PC à la main.", "erreur")
            else:
                fen.toast(fini_message, "ok")

        en_arriere_plan(travail, fin, lambda e: fin((False, e)))

    def activer():
        code = None
        if not kiosque.etat()["code"]:
            d = DialogueCodeKiosque(page)
            if d.exec() != QDialog.DialogCode.Accepted:
                return
            code = d.code()
        lancer("activer", code, "Mode kiosque activé depuis Flux")

    def changer_code():
        d = DialogueCodeKiosque(page, "Nouveau code administrateur")
        if d.exec() == QDialog.DialogCode.Accepted:
            lancer("code", d.code(), "Code administrateur du kiosque changé")

    def desactiver():
        r = QMessageBox.question(page, "Désactiver le kiosque",
                                 "Au prochain démarrage, le PC reviendra à l'écran de connexion habituel. Continuer ?")
        if r == QMessageBox.StandardButton.Yes:
            lancer("desactiver", None, "Mode kiosque désactivé depuis Flux")

    c_redem.toggled.connect(lambda _c: maj())
    b_act.clicked.connect(activer)
    b_code.clicked.connect(changer_code)
    b_des.clicked.connect(desactiver)
    maj()
    return w
