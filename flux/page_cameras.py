"""Page Caméras : un onglet par flux, ajout de caméras (webcam, RTSP, fichier, lien web, ONVIF)."""

import os
from datetime import datetime

import cv2
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMenu, QMessageBox, QScrollArea, QStackedWidget, QTabBar, QVBoxLayout,
                               QWidget)

from . import onvif
from .config import NIVEAUX, niveau_effectif
from .sources import Detecteur, dessiner, est_lien_web, slug
from .page_groupes import DialogueGroupe, PageGroupe  # noqa: F401
from .taches import en_arriere_plan
from .widgets import (Bouton, BoutonX, Interrupteur, Pastille, Repliable, VueVideo, Voyant, etiquette, ligne_option,
                      separateur)

CHOIX_NIVEAUX = [("global", "Réglage global")] + [(k, v["nom"]) for k, v in NIVEAUX.items()] + [
    ("personnalise", "Personnalisé")]


def texte_niveau(cle, cfg):
    if cle == "global":
        cle = cfg.get("detection.niveau")
        prefixe = "Réglage global : "
    else:
        prefixe = ""
    if cle == "personnalise":
        m, taille, _, _ = niveau_effectif("personnalise", cfg)
        return f"{prefixe}modèle {os.path.basename(m)} · {taille} px (modifiable dans Réglages › Détection)."
    n = NIVEAUX.get(cle, NIVEAUX["equilibre"])
    return f"{prefixe}{n['nom']} — {n['texte']}"


class PageFlux(QWidget):
    """Une caméra : vidéo, détections, réglages propres."""

    def __init__(self, page, nom, source, params=None):
        super().__init__()
        self.page, self.fen = page, page.fen
        self.cfg, self.base = self.fen.cfg, self.fen.base
        p = params or {}
        self.nom = nom
        self.cle = f"flux-{id(self)}"
        self.detecteur = None
        self._img_ref = None
        self._titre = None
        self.voyant_onglet = Voyant(10)
        self.onvif = p.get("onvif")
        self.o = {"niveau": p.get("niveau", "global"), "visages": bool(p.get("visages", False)),
                  "expressions": bool(p.get("expressions", False)), "plaques": bool(p.get("plaques", False)),
                  "lire_plaques": bool(p.get("lire_plaques", False)), "enregistrer": False,
                  "zone": tuple(p["zone"]) if p.get("zone") else None}
        self._construire(source)

    # --- construction -----------------------------------------------------------
    def _construire(self, source):
        racine = QHBoxLayout(self)
        racine.setContentsMargins(0, 10, 0, 0)
        racine.setSpacing(18)

        gauche = QVBoxLayout()
        gauche.setSpacing(12)
        entete = QHBoxLayout()
        entete.setSpacing(10)
        self.voyant = Voyant(14)
        entete.addWidget(self.voyant)
        bloc = QVBoxLayout()
        bloc.setSpacing(0)
        self.titre = QLabel(self.nom)
        self.titre.setObjectName("titre")
        self.sous_titre = QLabel("Arrêté")
        self.sous_titre.setObjectName("soustitre")
        bloc.addWidget(self.titre)
        bloc.addWidget(self.sous_titre)
        entete.addLayout(bloc)
        entete.addStretch(1)
        self.p_visages = Pastille("Visages", "o_visage")
        self.p_expr = Pastille("Expressions", "o_visage")
        self.p_plaques = Pastille("Plaques", "o_plaque")
        self.p_visages.setToolTip("Détecter les visages et reconnaître les personnes de la base")
        self.p_expr.setToolTip("Reconnaître l'expression de chaque visage (active aussi les visages)")
        self.p_plaques.setToolTip("Détecter les véhicules et leurs plaques d'immatriculation")
        for w in (self.p_visages, self.p_expr, self.p_plaques):
            entete.addWidget(w)
        b_capture = Bouton("", "discret", "capture")
        b_capture.setToolTip("Enregistrer une capture d'écran annotée")
        b_capture.clicked.connect(self._capture)
        entete.addWidget(b_capture)
        b_clip = Bouton("", "discret", "video")
        b_clip.setToolTip("Enregistrer une courte vidéo maintenant (avec les secondes précédentes)")
        b_clip.clicked.connect(self._clip)
        entete.addWidget(b_clip)
        gauche.addLayout(entete)
        self.video = VueVideo()
        self.video.message_vide = "Flux arrêté"
        self.video.definir_zone(self.o["zone"])
        self.video.zoneChangee.connect(self._zone_changee)
        gauche.addWidget(self.video, 1)
        racine.addLayout(gauche, 1)

        defil = QScrollArea()
        defil.setWidgetResizable(True)
        defil.setFixedWidth(330)
        defil.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        contenu = QWidget()
        col = QVBoxLayout(contenu)
        col.setContentsMargins(0, 0, 12, 8)
        col.setSpacing(10)

        col.addWidget(etiquette("SOURCE", "section"))
        ligne = QHBoxLayout()
        self.champ_source = QLineEdit(source)
        self.champ_source.setPlaceholderText("0, rtsp://…, lien YouTube, fichier")
        b_parcourir = Bouton("", "discret", "dossier")
        b_parcourir.clicked.connect(self._parcourir)
        ligne.addWidget(self.champ_source, 1)
        ligne.addWidget(b_parcourir)
        col.addLayout(ligne)
        if self.onvif:
            col.addWidget(etiquette(f"Caméra ONVIF · {self.onvif.get('xaddr', '')}"))
        self.b_marche = Bouton("Démarrer", "primaire", "lecture")
        self.b_marche.clicked.connect(self._basculer_marche)
        col.addWidget(self.b_marche)

        col.addSpacing(4)
        col.addWidget(separateur())
        col.addWidget(etiquette("NIVEAU DE SCAN", "section"))
        self.combo_niveau = QComboBox()
        for k, lib in CHOIX_NIVEAUX:
            self.combo_niveau.addItem(lib, k)
        i = self.combo_niveau.findData(self.o["niveau"])
        self.combo_niveau.setCurrentIndex(max(0, i))
        col.addWidget(self.combo_niveau)
        self.lbl_niveau = etiquette("")
        col.addWidget(self.lbl_niveau)

        col.addSpacing(4)
        col.addWidget(separateur())
        col.addWidget(etiquette("OPTIONS", "section"))
        self.i_lire = Interrupteur()
        self.rep_lire = Repliable(ligne_option("Lire le texte des plaques", self.i_lire,
                                               "Reconnaissance optique. Les plaques sont des données personnelles."))
        col.addWidget(self.rep_lire)
        self.i_enreg = Interrupteur()
        col.addWidget(ligne_option("Enregistrer la vidéo annotée", self.i_enreg))

        col.addSpacing(4)
        col.addWidget(separateur())
        col.addWidget(etiquette("ZONE", "section"))
        col.addWidget(etiquette("Dessinez un rectangle sur l'image pour limiter la détection et suivre les entrées et "
                                "sorties. Clic droit pour l'effacer."))
        b_zone = Bouton("Effacer la zone")
        b_zone.clicked.connect(lambda: (self.video.definir_zone(None), self._zone_changee(None)))
        col.addWidget(b_zone)
        col.addStretch(1)
        defil.setWidget(contenu)
        droite = QVBoxLayout()
        droite.addWidget(defil, 1)
        b_fermer = Bouton("Fermer cette caméra", "danger")
        b_fermer.clicked.connect(lambda: self.page.fermer(self))
        droite.addWidget(b_fermer)
        racine.addLayout(droite)

        self.p_visages.regler(self.o["visages"])
        self.p_expr.regler(self.o["expressions"])
        self.p_plaques.regler(self.o["plaques"])
        self.i_lire.regler(self.o["lire_plaques"])
        self.rep_lire.ouvrir(self.o["plaques"], instantane=True)
        for w in (self.p_visages, self.p_expr, self.p_plaques, self.i_lire, self.i_enreg):
            w.toggled.connect(self._sync)
        self.p_plaques.toggled.connect(self.rep_lire.ouvrir)
        self.combo_niveau.currentIndexChanged.connect(self._niveau_change)
        self._sync()

    # --- actions ----------------------------------------------------------------------
    def _parcourir(self):
        chemin, _ = QFileDialog.getOpenFileName(self, "Choisir une vidéo", "",
                                                "Vidéos (*.mp4 *.avi *.mkv *.mov *.webm);;Tous les fichiers (*.*)")
        if chemin:
            self.champ_source.setText(chemin)

    def _basculer_marche(self):
        self.arreter() if self.en_cours() else self.demarrer()

    def demarrer(self):
        self.arreter(sauver=False)
        source = self.champ_source.text().strip()
        if not source:
            self.fen.toast("Indiquez une source.", "erreur")
            return
        self._sync()
        self.video.effacer()
        self._img_ref = None
        self.detecteur = Detecteur(self.nom, source, self.o, self.cfg, self.base, self.fen.evenements)
        self.detecteur.start()
        self.b_marche.setText("Arrêter")
        self.b_marche.definir_style("discret")
        self.b_marche.definir_icone("pause")
        self.page.sauver()

    def arreter(self, sauver=True):
        if self.detecteur is not None:
            self.detecteur.arreter()
            self.detecteur = None
            self.video.effacer()
            self._img_ref = None
            self.b_marche.setText("Démarrer")
            self.b_marche.definir_style("primaire")
            self.b_marche.definir_icone("lecture")
            if sauver:
                self.page.sauver()

    def en_cours(self):
        return self.detecteur is not None and self.detecteur.is_alive()

    def _niveau_change(self):
        self.o["niveau"] = self.combo_niveau.currentData()
        self.lbl_niveau.setText(texte_niveau(self.o["niveau"], self.cfg))
        if self.en_cours():  # le modèle change : on relance proprement
            self.demarrer()
        else:
            self.page.sauver()

    def maj_niveau(self):
        self.lbl_niveau.setText(texte_niveau(self.combo_niveau.currentData(), self.cfg))

    def _capture(self):
        d = self.detecteur
        if d is None or d.derniere_image is None:
            self.fen.toast("Démarrez la caméra pour faire une capture.")
            return
        with d.lock:
            img, ann = d.derniere_image.copy(), d.annotations
        dossier = self.cfg.dossier_sortie()
        os.makedirs(dossier, exist_ok=True)
        chemin = os.path.join(dossier, datetime.now().strftime("capture_%Y%m%d_%H%M%S_") + slug(self.nom) + ".jpg")
        cv2.imwrite(chemin, dessiner(img, ann) if ann else img)
        self.fen.toast(f"Capture enregistrée : {os.path.basename(chemin)}", "ok")

    def _clip(self):
        d = self.detecteur
        if d is None or not self.en_cours() or d.derniere_image is None:
            self.fen.toast("Démarrez la caméra pour enregistrer une vidéo.")
            return
        d.clips.declencher("manuel", "Vidéo enregistrée à la main", force=True)
        avant, apres = self.cfg.get("clips.avant"), self.cfg.get("clips.apres")
        self.fen.toast(f"Enregistrement d'une vidéo ({avant:g} s avant + {apres:g} s après)…")

    def _zone_changee(self, zone):
        self.o["zone"] = zone
        self.page.sauver()

    def _sync(self, *_):
        self.o["expressions"] = self.p_expr.isChecked()
        self.o["visages"] = self.p_visages.isChecked() or self.o["expressions"]
        self.o["plaques"] = self.p_plaques.isChecked()
        self.o["lire_plaques"] = self.i_lire.isChecked() and self.o["plaques"]
        self.o["enregistrer"] = self.i_enreg.isChecked()
        self.lbl_niveau.setText(texte_niveau(self.combo_niveau.currentData(), self.cfg))
        self.page.sauver()

    def exporter(self):
        return {"nom": self.nom, "source": self.champ_source.text().strip(), "niveau": self.o["niveau"],
                "visages": self.p_visages.isChecked(), "expressions": self.o["expressions"],
                "plaques": self.o["plaques"], "lire_plaques": self.i_lire.isChecked(),
                "zone": list(self.o["zone"]) if self.o["zone"] else None, "actif": self.en_cours(),
                "onvif": self.onvif}

    # --- rafraîchissement ----------------------------------------------------------------
    def alimenter_vue(self, vue):
        """Envoie l'image courante dans une vignette de mur vidéo (VueVideo compacte). Renvoie l'état."""
        d = self.detecteur
        if d is None:
            if vue._image is not None:
                vue.effacer()
            vue._ref_img = vue._ref_ann = None
            vue.regler_etat("arret", "", [], 0.0, [self.nom])
            return "arret"
        actif = self.en_cours()
        with d.lock:
            img, ann, fps, heure = d.derniere_image, d.annotations, d.fps, d.heure_image
        nb_p = len((ann or {}).get("personnes", []))
        if not actif:
            etat, statut = "arret", d.statut
        elif d.charge or img is None:
            etat, statut = "chargement", d.statut
        elif nb_p:
            etat, statut = "alerte", f"{nb_p} personne{'s' if nb_p > 1 else ''}"
        else:
            etat, statut = "direct", "En direct"
        if img is not None and img is not getattr(vue, "_ref_img", None):
            vue._ref_img, vue._ref_ann = img, d.annotations
            vue.definir_image(img, ann or {}, heure)
        elif d.annotations is not None and d.annotations is not getattr(vue, "_ref_ann", None):
            vue._ref_ann = d.annotations
            vue.definir_annotations(ann or {})
        vue.regler_etat(etat, statut if etat != "arret" else "", [], fps, [self.nom])
        return etat

    def mise_a_jour(self, visible):
        d = self.detecteur
        actif = self.en_cours()
        etat, statut, nb_p = "arret", "Arrêté", 0
        compteurs, badges, fps = [], [], 0.0
        if d is not None:
            with d.lock:
                img, ann, fps, heure = d.derniere_image, d.annotations, d.fps, d.heure_image
            ann = ann or {}
            nb_p = len(ann.get("personnes", []))
            if actif:
                if d.charge or img is None:
                    etat, statut = "chargement", d.statut
                elif nb_p:
                    etat, statut = "alerte", f"{nb_p} personne{'s' if nb_p > 1 else ''}"
                else:
                    etat, statut = "direct", "En direct"
            else:
                statut = d.statut
            compteurs = [("Personnes", nb_p, "o_personne")]
            if self.o["visages"]:
                compteurs.append(("Visages", len(ann.get("visages", [])), "o_visage"))
                connus = sum(1 for p in ann.get("pistes", []) if p.get("personne") and p["personne"][2] != "inconnu")
                if connus:
                    compteurs.append(("Reconnues", connus, "succes"))
            if self.o["plaques"]:
                compteurs += [("Véhicules", len(ann.get("vehicules", [])), "o_vehicule"),
                              ("Plaques", len(ann.get("plaques", [])), "o_plaque")]
            if actif and d.pipeline.libelle_niveau:
                badges.append(d.pipeline.libelle_niveau)
            if ann.get("basse_lumiere"):
                badges.append("Basse lumière")
            if visible and img is not None and img is not self._img_ref:
                self._img_ref = img
                self._ann_ref = d.annotations
                self.video.definir_image(img, ann, heure)
            elif visible and d.annotations is not None and d.annotations is not getattr(self, "_ann_ref", None):
                self._ann_ref = d.annotations
                self.video.definir_annotations(ann)
        self.voyant_onglet.regler(etat)
        self.voyant.regler(etat)
        if visible:
            self.video.regler_etat(etat, statut if etat != "arret" else "", compteurs, fps, badges)
            if etat in ("direct", "alerte") and d is not None:
                delai = getattr(self.video, "delai_affichage", 0.0)
                self.sous_titre.setText(f"{statut} · {fps:.0f} images/s · délai d'affichage {delai * 1000:.0f} ms · "
                                        f"analyse {d.pipeline.temps_analyse * 1000:.0f} ms "
                                        f"({d.fps_analyse:.0f}/s)")
            else:
                self.sous_titre.setText(statut)
        titre = self.nom + (f"  ·  {nb_p}" if actif and nb_p else "")
        if titre != self._titre:
            self._titre = titre
            self.page.titre_onglet(self, titre)
        return etat


# ---------------------------------------------------------------------------
# Fenêtres d'ajout
# ---------------------------------------------------------------------------
class DialogueFlux(QDialog):
    def __init__(self, parent, nom_defaut):
        super().__init__(parent)
        self.setWindowTitle("Ajouter une caméra")
        self.setMinimumWidth(500)
        self.resultat = None
        v = QVBoxLayout(self)
        v.setContentsMargins(26, 24, 26, 22)
        v.setSpacing(10)
        t = QLabel("Ajouter une caméra")
        t.setObjectName("grand")
        v.addWidget(t)
        v.addWidget(etiquette("Webcam, caméra réseau (RTSP/HTTP), fichier vidéo ou lien web (YouTube en direct…). "
                              "Pour une caméra ONVIF, utilisez plutôt « Caméra ONVIF »."))
        v.addSpacing(6)
        v.addWidget(QLabel("Nom"))
        self.nom = QLineEdit(nom_defaut)
        v.addWidget(self.nom)
        v.addWidget(QLabel("Source"))
        h = QHBoxLayout()
        self.source = QLineEdit("0")
        self.source.setPlaceholderText("0, rtsp://utilisateur:mdp@192.168.1.20:554/stream1, fichier, lien…")
        b = Bouton("Parcourir…", "discret", "dossier")
        b.clicked.connect(self._parcourir)
        h.addWidget(self.source, 1)
        h.addWidget(b)
        v.addLayout(h)
        self.indice = etiquette("")
        v.addWidget(self.indice)
        self.source.textChanged.connect(self._indice)
        self._indice()
        v.addSpacing(10)
        h2 = QHBoxLayout()
        h2.addStretch(1)
        b_annuler = Bouton("Annuler")
        b_annuler.clicked.connect(self.reject)
        b_ok = Bouton("Ajouter et démarrer", "primaire")
        b_ok.clicked.connect(self._ok)
        b_ok.setDefault(True)
        h2.addWidget(b_annuler)
        h2.addWidget(b_ok)
        v.addLayout(h2)

    def _indice(self):
        s = self.source.text().strip()
        if s.isdigit():
            t = f"Webcam n° {s} de cet ordinateur."
        elif s.lower().startswith("rtsp"):
            t = "Flux RTSP d'une caméra réseau."
        elif est_lien_web(s):
            t = "Lien web : la vidéo sera trouvée automatiquement (yt-dlp)."
        elif os.path.isfile(s):
            t = "Fichier vidéo."
        else:
            t = "Adresse directe d'un flux vidéo." if "://" in s else ""
        self.indice.setText(t)

    def _parcourir(self):
        chemin, _ = QFileDialog.getOpenFileName(self, "Choisir une vidéo", "",
                                                "Vidéos (*.mp4 *.avi *.mkv *.mov *.webm);;Tous les fichiers (*.*)")
        if chemin:
            self.source.setText(chemin)

    def _ok(self):
        source = self.source.text().strip()
        if not source:
            self.source.setFocus()
            return
        self.resultat = (self.nom.text().strip() or "Caméra", source, {})
        self.accept()


class DialogueOnvif(QDialog):
    """Recherche les caméras ONVIF du réseau, se connecte et choisit le profil vidéo."""

    def __init__(self, parent, cfg, nom_defaut):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("Caméra ONVIF")
        self.setMinimumWidth(560)
        self.resultat = None
        self.client = None
        self.profils = []
        v = QVBoxLayout(self)
        v.setContentsMargins(26, 24, 26, 22)
        v.setSpacing(10)
        t = QLabel("Caméra ONVIF")
        t.setObjectName("grand")
        v.addWidget(t)
        v.addWidget(etiquette("Recherchez les caméras de votre réseau ou saisissez leur adresse, puis connectez-vous "
                              "avec l'identifiant de la caméra."))
        h = QHBoxLayout()
        self.b_rechercher = Bouton("Rechercher sur le réseau", "discret", "reseau")
        self.b_rechercher.clicked.connect(self._rechercher)
        h.addWidget(self.b_rechercher)
        self.lbl_recherche = etiquette("", "soustitre")
        h.addWidget(self.lbl_recherche, 1)
        v.addLayout(h)
        self.liste = QListWidget()
        self.liste.setMaximumHeight(130)
        self.liste.itemClicked.connect(lambda it: self.adresse.setText(it.data(Qt.ItemDataRole.UserRole)))
        v.addWidget(self.liste)
        v.addWidget(QLabel("Adresse de la caméra"))
        self.adresse = QLineEdit()
        self.adresse.setPlaceholderText("192.168.1.20  ou  192.168.1.20:8080  ou  http://…/onvif/device_service")
        v.addWidget(self.adresse)
        h2 = QHBoxLayout()
        c1, c2 = QVBoxLayout(), QVBoxLayout()
        c1.addWidget(QLabel("Identifiant"))
        self.user = QLineEdit("admin")
        c1.addWidget(self.user)
        c2.addWidget(QLabel("Mot de passe"))
        self.mdp = QLineEdit()
        self.mdp.setEchoMode(QLineEdit.EchoMode.Password)
        c2.addWidget(self.mdp)
        h2.addLayout(c1)
        h2.addLayout(c2)
        v.addLayout(h2)
        self.b_connecter = Bouton("Se connecter", "discret")
        self.b_connecter.clicked.connect(self._connecter)
        v.addWidget(self.b_connecter)
        self.etat = etiquette("")
        v.addWidget(self.etat)
        v.addWidget(QLabel("Profil vidéo"))
        self.combo_profil = QComboBox()
        self.combo_profil.setEnabled(False)
        v.addWidget(self.combo_profil)
        v.addWidget(QLabel("Nom dans Flux"))
        self.nom = QLineEdit(nom_defaut)
        v.addWidget(self.nom)
        v.addSpacing(8)
        h3 = QHBoxLayout()
        h3.addStretch(1)
        b_annuler = Bouton("Annuler")
        b_annuler.clicked.connect(self.reject)
        self.b_ok = Bouton("Ajouter et démarrer", "primaire")
        self.b_ok.setEnabled(False)
        self.b_ok.clicked.connect(self._ok)
        h3.addWidget(b_annuler)
        h3.addWidget(self.b_ok)
        v.addLayout(h3)

    def _rechercher(self):
        self.b_rechercher.setEnabled(False)
        self.lbl_recherche.setText("Recherche en cours…")
        self.liste.clear()
        en_arriere_plan(onvif.decouvrir, self._trouvees, self._erreur_recherche, self.cfg.get("onvif.delai_recherche"))

    def _trouvees(self, cameras):
        self.b_rechercher.setEnabled(True)
        self.lbl_recherche.setText(f"{len(cameras)} caméra(s) trouvée(s)" if cameras else
                                   "Aucune caméra n'a répondu. Vérifiez qu'elle est sur le même réseau et que l'ONVIF "
                                   "est activé dans ses réglages.")
        for c in cameras:
            it = QListWidgetItem(f"{c['nom']}   ·   {c['ip']}" + (f"   ·   {c['modele']}" if c["modele"] else ""))
            it.setData(Qt.ItemDataRole.UserRole, c["xaddr"])
            self.liste.addItem(it)
        if len(cameras) == 1:
            self.adresse.setText(cameras[0]["xaddr"])
            if self.nom.text().startswith("Caméra"):
                self.nom.setText(cameras[0]["nom"])

    def _erreur_recherche(self, msg):
        self.b_rechercher.setEnabled(True)
        self.lbl_recherche.setText(f"Recherche impossible : {msg}")

    def _connecter(self):
        if not self.adresse.text().strip():
            self.adresse.setFocus()
            return
        self.client = onvif.ClientOnvif(self.adresse.text(), self.user.text().strip(), self.mdp.text())
        self.b_connecter.setEnabled(False)
        self.etat.setText("Connexion…")
        en_arriere_plan(self.client.connecter, self._connecte, self._erreur_connexion)

    def _connecte(self, profils):
        self.b_connecter.setEnabled(True)
        self.profils = profils
        self.combo_profil.clear()
        for p in profils:
            self.combo_profil.addItem(f"{p['nom']} · {p['largeur']}×{p['hauteur']} · {p['encodage']}", p["jeton"])
        choix = onvif.choisir_profil(profils, self.cfg.get("onvif.profil"))
        self.combo_profil.setCurrentIndex(self.combo_profil.findData(choix["jeton"]))
        self.combo_profil.setEnabled(True)
        self.b_ok.setEnabled(True)
        self.etat.setText(f"Connecté · {len(profils)} profil(s) vidéo.")

    def _erreur_connexion(self, msg):
        self.b_connecter.setEnabled(True)
        self.etat.setText(f"Échec : {msg}")

    def _ok(self):
        self.b_ok.setEnabled(False)
        self.etat.setText("Récupération de l'adresse du flux…")
        en_arriere_plan(self.client.adresse_flux, self._uri, self._erreur_connexion, self.combo_profil.currentData())

    def _uri(self, uri):
        self.resultat = (self.nom.text().strip() or "Caméra ONVIF", uri,
                         {"onvif": {"xaddr": self.client.xaddr, "utilisateur": self.client.utilisateur,
                                    "profil": self.combo_profil.currentData()}})
        self.accept()


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
class PageCameras(QWidget):
    def __init__(self, fen):
        super().__init__()
        self.fen, self.cfg = fen, fen.cfg
        self.pages = []
        self.groupes = []
        self._restauration = True
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        haut = QHBoxLayout()
        titre = QLabel("Caméras")
        titre.setObjectName("titre_page")
        haut.addWidget(titre)
        haut.addSpacing(16)
        self.barre = QTabBar()
        self.barre.setMovable(True)
        self.barre.setExpanding(False)
        self.barre.setDrawBase(False)
        self.barre.setUsesScrollButtons(True)
        self.barre.setElideMode(Qt.TextElideMode.ElideRight)
        self.barre.currentChanged.connect(self._onglet_change)
        self.barre.tabMoved.connect(lambda *_: self.sauver())
        haut.addWidget(self.barre, 1)
        self.b_ajouter = Bouton("Ajouter", "primaire", "plus")
        menu = QMenu(self)
        menu.addAction("Caméra, fichier ou lien…", self.nouvelle)
        menu.addAction("Caméra ONVIF…", self.nouvelle_onvif)
        menu.addSeparator()
        menu.addAction("Groupe de caméras (plusieurs vues)…", self.nouveau_groupe)
        self.b_ajouter.clicked.connect(lambda: menu.exec(self.b_ajouter.mapToGlobal(self.b_ajouter.rect().bottomLeft())))
        haut.addWidget(self.b_ajouter)
        v.addLayout(haut)
        self.pile = QStackedWidget()
        self.vide = self._page_vide()
        self.pile.addWidget(self.vide)
        v.addWidget(self.pile, 1)

    def _page_vide(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addStretch(2)
        t = QLabel("Aucune caméra")
        t.setObjectName("grand")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        s = etiquette("Ajoutez une webcam, une caméra réseau, une caméra ONVIF, un fichier ou un lien vidéo.",
                      "soustitre")
        s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h = QHBoxLayout()
        h.addStretch(1)
        b1 = Bouton("Caméra, fichier ou lien", "primaire", "plus")
        b1.clicked.connect(self.nouvelle)
        b2 = Bouton("Caméra ONVIF", "discret", "reseau")
        b2.clicked.connect(self.nouvelle_onvif)
        h.addWidget(b1)
        h.addWidget(b2)
        h.addStretch(1)
        v.addWidget(t)
        v.addWidget(s)
        v.addSpacing(12)
        v.addLayout(h)
        v.addStretch(3)
        return w

    def restaurer(self):
        for p in self.cfg.flux:
            self.ajouter(p.get("nom", "Caméra"), p.get("source", "0"), p, demarrer=p.get("actif", False))
        for g in self.cfg.groupes:
            self._ajouter_groupe(g.get("nom", "Groupe"), [str(n) for n in g.get("cameras", [])],
                                 g.get("colonnes", 0))
        self._restauration = False
        if self.pages or self.groupes:
            self.barre.setCurrentIndex(0)
        else:
            self.pile.setCurrentWidget(self.vide)

    # --- onglets -------------------------------------------------------------------
    def _page(self, cle):
        return next((p for p in self.pages + self.groupes if p.cle == cle), None)

    def page_par_nom(self, nom):
        """La caméra (PageFlux) portant ce nom, ou None."""
        return next((p for p in self.pages if p.nom == nom), None)

    def noms_cameras(self):
        return [p.nom for p in self.ordonnees() if isinstance(p, PageFlux)]

    def etat_camera(self, nom):
        p = self.page_par_nom(nom)
        d = p.detecteur if p is not None else None
        if d is None or not p.en_cours():
            return "arret"
        return "chargement" if d.charge or d.derniere_image is None else "direct"

    def ouvrir_camera(self, nom):
        p = self.page_par_nom(nom)
        if p is not None:
            self.fen.aller("cameras")
            self.barre.setCurrentIndex(self._index(p))

    def _index(self, page):
        for i in range(self.barre.count()):
            if self.barre.tabData(i) == page.cle:
                return i
        return -1

    def ordonnees(self):
        """Caméras et groupes, dans l'ordre des onglets."""
        return [p for p in (self._page(self.barre.tabData(i)) for i in range(self.barre.count())) if p]

    def titre_onglet(self, page, titre):
        i = self._index(page)
        if i >= 0:
            self.barre.setTabText(i, titre)

    def _onglet_change(self, i):
        page = self._page(self.barre.tabData(i)) if i >= 0 else None
        if page is not None:
            self.pile.setCurrentWidget(page)
            self.fen.fondu(page)

    def _nom_unique(self, nom):
        noms = {p.nom for p in self.pages}
        if nom not in noms:
            return nom
        i = 2
        while f"{nom} {i}" in noms:
            i += 1
        return f"{nom} {i}"

    def nouvelle(self):
        d = DialogueFlux(self, f"Caméra {len(self.pages) + 1}")
        if d.exec() == QDialog.DialogCode.Accepted and d.resultat:
            nom, source, params = d.resultat
            page = self.ajouter(nom, source, params, demarrer=True)
            self.barre.setCurrentIndex(self._index(page))

    # --- groupes -------------------------------------------------------------------
    def nouveau_groupe(self):
        noms = self.noms_cameras()
        if not noms:
            self.fen.toast("Ajoutez d'abord au moins une caméra, puis créez un groupe.")
            return
        d = DialogueGroupe(self, noms, f"Groupe {len(self.groupes) + 1}", noms, 0)
        if d.exec() == QDialog.DialogCode.Accepted and d.resultat:
            nom, cameras, colonnes = d.resultat
            g = self._ajouter_groupe(nom, cameras, colonnes)
            self.barre.setCurrentIndex(self._index(g))
            self.sauver()

    def _ajouter_groupe(self, nom, cameras, colonnes):
        g = PageGroupe(self, nom, cameras, colonnes)
        self.groupes.append(g)
        self.pile.addWidget(g)
        self.barre.blockSignals(True)
        i = self.barre.addTab(g.nom)
        self.barre.setTabData(i, g.cle)
        self.barre.setTabButton(i, QTabBar.ButtonPosition.LeftSide, g.voyant_onglet)
        bx = BoutonX()
        bx.clicked.connect(lambda: self.supprimer_groupe(g))
        self.barre.setTabButton(i, QTabBar.ButtonPosition.RightSide, bx)
        self.barre.blockSignals(False)
        if self.barre.currentIndex() == i:
            self._onglet_change(i)
        return g

    def supprimer_groupe(self, g, confirmer=True):
        if confirmer and QMessageBox.question(
                self, "Supprimer le groupe", f"Supprimer le groupe « {g.nom} » ?\nLes caméras ne sont pas arrêtées.") != \
                QMessageBox.StandardButton.Yes:
            return
        g.fermer_fenetres()
        i = self._index(g)
        self.groupes.remove(g)
        if i >= 0:
            self.barre.removeTab(i)
        self.pile.removeWidget(g)
        g.deleteLater()
        if not self.pages and not self.groupes:
            self.pile.setCurrentWidget(self.vide)
        self.sauver()

    def nouvelle_onvif(self):
        d = DialogueOnvif(self, self.cfg, f"Caméra {len(self.pages) + 1}")
        if d.exec() == QDialog.DialogCode.Accepted and d.resultat:
            nom, source, params = d.resultat
            page = self.ajouter(nom, source, params, demarrer=True)
            self.barre.setCurrentIndex(self._index(page))

    def ajouter(self, nom, source, params=None, demarrer=False):
        page = PageFlux(self, self._nom_unique(nom), source, params)
        self.pages.append(page)
        self.pile.addWidget(page)
        self.barre.blockSignals(True)
        i = self.barre.addTab(page.nom)
        self.barre.setTabData(i, page.cle)
        self.barre.setTabButton(i, QTabBar.ButtonPosition.LeftSide, page.voyant_onglet)
        bx = BoutonX()
        bx.clicked.connect(lambda: self.fermer(page))
        self.barre.setTabButton(i, QTabBar.ButtonPosition.RightSide, bx)
        self.barre.blockSignals(False)
        if self.barre.currentIndex() == i:
            self._onglet_change(i)
        if demarrer:
            page.demarrer()
        self.sauver()
        return page

    def fermer(self, page, confirmer=True):
        if confirmer and QMessageBox.question(self, "Fermer la caméra", f"Fermer « {page.nom} » ?") != \
                QMessageBox.StandardButton.Yes:
            return
        page.arreter(sauver=False)
        for g in self.groupes:
            g.camera_supprimee(page.nom)
        i = self._index(page)
        self.pages.remove(page)
        if i >= 0:
            self.barre.removeTab(i)
        self.pile.removeWidget(page)
        page.deleteLater()
        if not self.pages and not self.groupes:
            self.pile.setCurrentWidget(self.vide)
        self.sauver()

    def sauver(self):
        if self._restauration:
            return
        ordre = self.ordonnees()
        self.cfg.flux = [p.exporter() for p in ordre if isinstance(p, PageFlux)]
        self.cfg.groupes = [{"nom": g.nom, "cameras": list(g.cameras), "colonnes": g.colonnes}
                            for g in ordre if isinstance(g, PageGroupe)]
        self.cfg.sauver()

    def mise_a_jour(self, page_visible):
        courante = self.pile.currentWidget()
        etats = [p.mise_a_jour(page_visible and p is courante) for p in self.pages]
        for g in self.groupes:
            g.mise_a_jour(page_visible and g is courante)
        return etats

    def tout_arreter(self):
        for g in self.groupes:
            g.fermer_fenetres()
        detecteurs = [p.detecteur for p in self.pages if p.detecteur is not None]
        for p in self.pages:
            p.arreter(sauver=False)
        for d in detecteurs:
            d.join(timeout=3)
