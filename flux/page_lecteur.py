"""Lecteur vidéo universel : fichiers, liens directs, YouTube, Instagram et tout site pris en charge par yt-dlp.

La lecture (image + son) est assurée par Qt Multimedia ; chaque image est aussi transmise au fil
d'analyse, qui ne traite que la plus récente : la lecture n'est jamais ralentie par l'analyse.
"""

import os
import subprocess
import sys

import numpy as np
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QProgressBar, QSlider,
                               QVBoxLayout, QWidget)

from .page_cameras import CHOIX_NIVEAUX, texte_niveau
from .sources import Analyseur, est_lien_web, resoudre_lien
from .taches import Tache
from .widgets import Bouton, Interrupteur, Pastille, VueVideo, etiquette

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
    MULTIMEDIA = True
except ImportError:  # PySide6-Essentials seul : pas de lecteur
    MULTIMEDIA = False


def audio_disponible():
    """Vrai si une sortie audio existe. Sous Linux, Qt plante (et emporte Flux) s'il n'y a aucun serveur son
    (ni PulseAudio ni PipeWire) : on le vérifie dans un processus à part, le lecteur jouera alors sans son."""
    if not sys.platform.startswith("linux"):
        return True
    code = ("from PySide6.QtCore import QCoreApplication\n"
            "from PySide6.QtMultimedia import QMediaDevices\n"
            "a = QCoreApplication([])\n"
            "raise SystemExit(0 if QMediaDevices.audioOutputs() else 3)\n")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    try:
        return subprocess.run([sys.executable, "-I", "-c", code], env=env, timeout=15, capture_output=True
                              ).returncode == 0
    except Exception:  # noqa: BLE001
        return False


def temps(ms):
    s = max(0, int(ms // 1000))
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def image_vers_numpy(qimg):
    """QImage -> tableau BGR (copie indépendante)."""
    img = qimg.convertToFormat(QImage.Format.Format_BGR888)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    tampon = np.frombuffer(img.constBits(), dtype=np.uint8, count=bpl * h).reshape(h, bpl)
    return tampon[:, :w * 3].reshape(h, w, 3).copy()


class PageLecteur(QWidget):
    def __init__(self, fen):
        super().__init__()
        self.fen, self.cfg, self.base = fen, fen.cfg, fen.base
        self.analyseur = None
        self.en_direct = False
        self.titre_media = "Lecteur"
        self._glisse = False
        self._tache = None
        self.o = {"niveau": "global", "visages": True, "expressions": False, "plaques": False, "lire_plaques": False,
                  "zone": None}
        self._construire()
        if MULTIMEDIA:
            self.lecteur = QMediaPlayer(self)
            self.sortie_son = None
            if audio_disponible():
                self.sortie_son = QAudioOutput(self)
                self.sortie_son.setVolume(self.cfg.get("lecteur.volume") / 100)
                self.lecteur.setAudioOutput(self.sortie_son)
            else:
                self.b_son.setEnabled(False)
                self.b_son.setToolTip("Aucune sortie audio détectée : lecture sans son")
            self.puits = QVideoSink(self)
            self.lecteur.setVideoSink(self.puits)
            self.puits.videoFrameChanged.connect(self._image)
            self.lecteur.durationChanged.connect(self._duree)
            self.lecteur.positionChanged.connect(self._position)
            self.lecteur.playbackStateChanged.connect(self._etat)
            self.lecteur.errorOccurred.connect(lambda e, m: self._statut(f"Lecture impossible : {m}", True))
            self.lecteur.mediaStatusChanged.connect(self._statut_media)
        else:
            self._statut("Le lecteur nécessite le paquet PySide6 complet : pip install PySide6", True)
            for w in (self.b_ouvrir, self.b_fichier, self.b_lecture):
                w.setEnabled(False)

    # --- construction ---------------------------------------------------------------
    def _construire(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        haut = QHBoxLayout()
        titre = QLabel("Lecteur")
        titre.setObjectName("titre_page")
        haut.addWidget(titre)
        haut.addSpacing(16)
        self.champ = QLineEdit()
        self.champ.setPlaceholderText("Collez un lien YouTube, Instagram, TikTok, Vimeo, un flux .m3u8… ou ouvrez un fichier")
        self.champ.returnPressed.connect(self.ouvrir_lien)
        haut.addWidget(self.champ, 1)
        self.b_ouvrir = Bouton("Lire", "primaire", "lien")
        self.b_ouvrir.clicked.connect(self.ouvrir_lien)
        self.b_fichier = Bouton("Fichier…", "discret", "dossier")
        self.b_fichier.clicked.connect(self.ouvrir_fichier)
        haut.addWidget(self.b_ouvrir)
        haut.addWidget(self.b_fichier)
        v.addLayout(haut)

        etat = QHBoxLayout()
        self.lbl_titre = QLabel("Aucune vidéo")
        self.lbl_titre.setObjectName("soustitre")
        etat.addWidget(self.lbl_titre, 1)
        self.barre_prog = QProgressBar()
        self.barre_prog.setFixedWidth(200)
        self.barre_prog.setVisible(False)
        etat.addWidget(self.barre_prog)
        v.addLayout(etat)

        corps = QHBoxLayout()
        corps.setSpacing(18)
        gauche = QVBoxLayout()
        self.video = VueVideo(zone_active=True)
        self.video.message_vide = "Collez un lien ou ouvrez un fichier"
        self.video.zoneChangee.connect(lambda z: self.o.__setitem__("zone", z))
        gauche.addWidget(self.video, 1)

        ctl = QHBoxLayout()
        ctl.setSpacing(10)
        self.b_lecture = Bouton("", "primaire", "lecture")
        self.b_lecture.setToolTip("Lecture / pause (Espace)")
        self.b_lecture.clicked.connect(self.basculer)
        ctl.addWidget(self.b_lecture)
        self.lbl_temps = QLabel("0:00 / 0:00")
        self.lbl_temps.setObjectName("soustitre")
        self.lbl_temps.setMinimumWidth(110)
        ctl.addWidget(self.lbl_temps)
        self.curseur = QSlider(Qt.Orientation.Horizontal)
        self.curseur.setRange(0, 0)
        self.curseur.sliderPressed.connect(lambda: setattr(self, "_glisse", True))
        self.curseur.sliderReleased.connect(self._fin_glisse)
        ctl.addWidget(self.curseur, 1)
        self.combo_vitesse = QComboBox()
        for x in (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 4.0):
            self.combo_vitesse.addItem(f"{x:g}×", x)
        self.combo_vitesse.setCurrentIndex(3)
        self.combo_vitesse.currentIndexChanged.connect(
            lambda: MULTIMEDIA and self.lecteur.setPlaybackRate(self.combo_vitesse.currentData()))
        ctl.addWidget(self.combo_vitesse)
        self.b_son = Bouton("", "fantome", "volume")
        self.b_son.clicked.connect(self._muet)
        ctl.addWidget(self.b_son)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setFixedWidth(100)
        self.volume.setValue(self.cfg.get("lecteur.volume"))
        self.volume.valueChanged.connect(self._volume)
        ctl.addWidget(self.volume)
        gauche.addLayout(ctl)
        corps.addLayout(gauche, 1)

        col_w = QWidget()
        col_w.setFixedWidth(300)
        col = QVBoxLayout(col_w)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(10)
        col.addWidget(etiquette("ANALYSE", "section"))
        self.i_analyse = Interrupteur()
        self.i_analyse.regler(self.cfg.get("lecteur.analyse"))
        self.i_analyse.toggled.connect(self._analyse_basculee)
        h = QHBoxLayout()
        h.addWidget(QLabel("Analyser la vidéo"), 1)
        h.addWidget(self.i_analyse)
        col.addLayout(h)
        lig = QHBoxLayout()
        self.p_visages = Pastille("Visages", "o_visage")
        self.p_expr = Pastille("Expressions", "o_visage")
        lig.addWidget(self.p_visages)
        lig.addWidget(self.p_expr)
        lig.addStretch(1)
        col.addLayout(lig)
        lig2 = QHBoxLayout()
        self.p_plaques = Pastille("Plaques", "o_plaque")
        lig2.addWidget(self.p_plaques)
        lig2.addStretch(1)
        col.addLayout(lig2)
        self.p_visages.regler(True)
        for p in (self.p_visages, self.p_expr, self.p_plaques):
            p.toggled.connect(self._sync)
        col.addWidget(etiquette("NIVEAU DE SCAN", "section"))
        self.combo_niveau = QComboBox()
        for k, lib in CHOIX_NIVEAUX:
            self.combo_niveau.addItem(lib, k)
        self.combo_niveau.currentIndexChanged.connect(self._niveau_change)
        col.addWidget(self.combo_niveau)
        self.lbl_niveau = etiquette(texte_niveau("global", self.cfg))
        col.addWidget(self.lbl_niveau)
        col.addWidget(etiquette("Les personnes vues dans la vidéo sont reconnues et enregistrées dans la base comme "
                                "pour une caméra. Dessinez une zone sur l'image pour limiter l'analyse."))
        col.addStretch(1)
        self.lbl_analyse = etiquette("", "soustitre")
        col.addWidget(self.lbl_analyse)
        corps.addWidget(col_w)
        v.addLayout(corps, 1)

    # --- ouverture ------------------------------------------------------------------------
    def _statut(self, texte, erreur=False):
        self.lbl_titre.setText(texte)
        if erreur:
            self.fen.toast(texte, "erreur")
            self.video.regler_etat("arret", "")

    def ouvrir_fichier(self):
        chemin, _ = QFileDialog.getOpenFileName(self, "Ouvrir une vidéo", "",
                                                "Vidéos (*.mp4 *.mkv *.avi *.mov *.webm *.m4v *.ts);;Tous (*.*)")
        if chemin:
            self.champ.setText(chemin)
            self.ouvrir(chemin)

    def ouvrir_lien(self):
        t = self.champ.text().strip().strip('"')
        if t:
            self.ouvrir(t)

    def ouvrir(self, source):
        if not MULTIMEDIA:
            return
        if os.path.isfile(source):
            self._lire(QUrl.fromLocalFile(os.path.abspath(source)), os.path.basename(source))
            return
        if not est_lien_web(source):
            self._lire(QUrl(source), source)
            return
        telecharger = self.cfg.get("lecteur.mode") == "telecharger"
        self._statut("Recherche de la vidéo…" if not telecharger else "Téléchargement…")
        self.video.regler_etat("chargement", "Recherche de la vidéo…")
        self.b_ouvrir.setEnabled(False)
        dossier = os.path.join(self.cfg.dossier_sortie(), "videos") if telecharger else None
        if dossier:
            os.makedirs(dossier, exist_ok=True)
            self.barre_prog.setVisible(True)
            self.barre_prog.setValue(0)
        tache = Tache(resoudre_lien, source, self.cfg, dossier,
                      (lambda d: tache.progression.emit(
                          d.get("downloaded_bytes", 0) / max(1, d.get("total_bytes") or d.get("total_bytes_estimate")
                                                             or 1))) if dossier else None)
        tache.fini.connect(self._resolu)
        tache.echec.connect(self._echec)
        tache.progression.connect(lambda x: self.barre_prog.setValue(int(x * 100)))
        self._tache = tache.lancer()

    def _resolu(self, info):
        self.b_ouvrir.setEnabled(True)
        self.barre_prog.setVisible(False)
        url = QUrl.fromLocalFile(info["fichier"]) if info.get("fichier") else QUrl(info["url"])
        if info.get("sans_son"):
            self.fen.toast("Aucun format avec son pour cette vidéo : lecture de l'image seule. Le mode « Télécharger "
                           "puis lire » (avec ffmpeg) récupère le son.")
        self._lire(url, info["titre"], direct=bool(info.get("direct")))

    def _echec(self, msg):
        self.b_ouvrir.setEnabled(True)
        self.barre_prog.setVisible(False)
        self._statut(f"Vidéo introuvable : {msg[:300]}", True)

    def _lire(self, url, titre, direct=False):
        self.titre_media = titre
        self.en_direct = direct
        self.lbl_titre.setText(titre + ("  ·  en direct" if direct else ""))
        # Un direct n'a ni durée ni vitesse réglable : on désactive ces commandes
        self.curseur.setEnabled(not direct)
        self.combo_vitesse.setEnabled(not direct)
        if direct:
            self.combo_vitesse.setCurrentIndex(self.combo_vitesse.findData(1.0))
        self.video.effacer()
        self.lecteur.setSource(url)
        self.lecteur.setPlaybackRate(self.combo_vitesse.currentData())
        self.lecteur.play()
        self._demarrer_analyse()

    # --- analyse ----------------------------------------------------------------------------
    def _nom_source(self):
        return f"Lecteur · {self.titre_media[:40]}"

    def _demarrer_analyse(self):
        if not self.i_analyse.isChecked():
            return
        if self.analyseur is None or not self.analyseur.is_alive():
            self._sync()
            self.analyseur = Analyseur(self._nom_source(), self.o, self.cfg, self.base, self.fen.evenements)
            self.analyseur.start()
        else:
            self.analyseur.renommer(self._nom_source())

    def _arreter_analyse(self):
        if self.analyseur is not None:
            self.analyseur.arreter()
            self.analyseur = None
        self.video.definir_annotations({})

    def _analyse_basculee(self, actif):
        self.cfg.set("lecteur.analyse", actif)
        if actif and MULTIMEDIA and self.lecteur.source().isValid():
            self._demarrer_analyse()
        elif not actif:
            self._arreter_analyse()

    def _niveau_change(self):
        self.o["niveau"] = self.combo_niveau.currentData()
        self.lbl_niveau.setText(texte_niveau(self.o["niveau"], self.cfg))
        if self.analyseur is not None:
            self._arreter_analyse()
            self._demarrer_analyse()

    def maj_niveau(self):
        self.lbl_niveau.setText(texte_niveau(self.combo_niveau.currentData(), self.cfg))

    def _sync(self, *_):
        self.o["expressions"] = self.p_expr.isChecked()
        self.o["visages"] = self.p_visages.isChecked() or self.o["expressions"]
        self.o["plaques"] = self.p_plaques.isChecked()
        self.o["lire_plaques"] = self.o["plaques"]

    def _image(self, trame):
        if not trame.isValid():
            return
        img = trame.toImage()
        if img.isNull():
            return
        frame = image_vers_numpy(img)
        ann = None
        if self.analyseur is not None:
            self.analyseur.soumettre(frame)
            with self.analyseur.lock:
                ann = self.analyseur.annotations
        self.video.definir_image(frame, ann if ann is not None else {})

    # --- commandes --------------------------------------------------------------------------
    def basculer(self):
        if not MULTIMEDIA:
            return
        if self.lecteur.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.lecteur.pause()
        elif self.lecteur.source().isValid():
            self.lecteur.play()

    def _etat(self, etat):
        joue = etat == QMediaPlayer.PlaybackState.PlayingState
        self.b_lecture.definir_icone("pause" if joue else "lecture")

    def _statut_media(self, s):
        if s == QMediaPlayer.MediaStatus.LoadingMedia:
            self.video.regler_etat("chargement", "Chargement…")
        elif s == QMediaPlayer.MediaStatus.EndOfMedia:
            self.video.regler_etat("arret", "Fin de la vidéo")

    def _duree(self, d):
        self.curseur.setRange(0, max(0, int(d)))
        self._position(self.lecteur.position())

    def _position(self, p):
        if not self._glisse:
            self.curseur.setValue(int(p))
        if getattr(self, "en_direct", False):
            self.lbl_temps.setText(f"En direct · {temps(p)}")
        else:
            self.lbl_temps.setText(f"{temps(p)} / {temps(self.lecteur.duration())}")

    def _fin_glisse(self):
        self._glisse = False
        self.lecteur.setPosition(self.curseur.value())

    def _volume(self, v):
        if MULTIMEDIA and self.sortie_son is not None:
            self.sortie_son.setVolume(v / 100)
            self.sortie_son.setMuted(False)
        self.b_son.definir_icone("volume" if v else "muet")
        self.cfg.set("lecteur.volume", v)

    def _muet(self):
        if MULTIMEDIA and self.sortie_son is not None:
            m = not self.sortie_son.isMuted()
            self.sortie_son.setMuted(m)
            self.b_son.definir_icone("muet" if m else "volume")

    def mise_a_jour(self, visible):
        if not visible or not MULTIMEDIA:
            return
        joue = self.lecteur.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        a = self.analyseur
        badges = []
        if a is not None:
            if not a.pret:
                self.lbl_analyse.setText(a.statut)
            else:
                pl = a.pipeline
                self.lbl_analyse.setText(f"{pl.libelle_niveau} · analyse {pl.temps_analyse * 1000:.0f} ms par image")
                badges.append(pl.libelle_niveau)
                if pl.basse_lumiere_active:
                    badges.append("Basse lumière")
        else:
            self.lbl_analyse.setText("Analyse désactivée")
        ann = (a.annotations if a is not None else None) or {}
        nb = len(ann.get("personnes", []))
        compteurs = [("Personnes", nb, "o_personne")]
        if self.o["visages"]:
            compteurs.append(("Visages", len(ann.get("visages", [])), "o_visage"))
        if getattr(self, "en_direct", False):
            badges.insert(0, "En direct")
        if joue:
            self.video.regler_etat("alerte" if nb else "direct", "Lecture" if not nb else f"{nb} personne(s)",
                                   compteurs, 0, badges)
        elif self.lecteur.source().isValid() and self.lecteur.mediaStatus() not in (
                QMediaPlayer.MediaStatus.LoadingMedia,):
            self.video.regler_etat("arret", "En pause", compteurs, 0, badges)

    def arreter(self):
        if MULTIMEDIA:
            self.lecteur.stop()
        self._arreter_analyse()
