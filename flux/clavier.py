"""Clavier visuel : écrire à la souris (kiosque sans clavier, poste avec une seule souris, écran tactile).

- Trois modes (Réglages › Apparence) : désactivé, « sur demande » (un petit bouton clavier apparaît quand on clique
  dans un champ de texte, mot de passe compris), « automatique » (le clavier s'ouvre tout seul).
- Le clavier ne prend jamais le focus : les touches vont dans le champ où l'on écrivait.
- Fenêtres qui s'ouvrent par-dessus (code administrateur, mot de passe WiFi, messages) : le clavier se rattache
  à la fenêtre au premier plan, il reste donc toujours cliquable.
"""
from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QComboBox, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QPlainTextEdit, QPushButton, QSizePolicy, QTextEdit, QVBoxLayout, QWidget)

from .theme import C

DRAPEAUX = (Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus)

# Pages du clavier. Touches spéciales : ⇧ maj, ⌫ effacer, ⏎ entrée, ⇥ tabulation, ␣ espace, ← →, « ?123 », « àé », « abc »
AZERTY = [list("1234567890") + ["⌫"],
          ["⇥"] + list("azertyuiop"),
          list("qsdfghjklm") + ["⏎"],
          ["⇧"] + list("wxcvbn,.-") + ["⇧"],
          ["?123", "àé", "@", "␣", "←", "→"]]
QWERTY = [list("1234567890") + ["⌫"],
          ["⇥"] + list("qwertyuiop"),
          list("asdfghjkl'") + ["⏎"],
          ["⇧"] + list("zxcvbnm,.-") + ["⇧"],
          ["?123", "àé", "@", "␣", "←", "→"]]
SYMBOLES = [list("1234567890") + ["⌫"],
            ["⇥"] + list("!?#$%&*()="),
            list("+-_/\\:;\"'") + ["⏎"],
            list("<>[]{}|~^€£") + ["°"],
            ["abc", "àé", "@", "␣", "←", "→"]]
ACCENTS = [list("àâäéèêëîï") + ["⌫"],
           ["⇥"] + list("ôöùûüçœæÿ"),
           list("«»“”’…–·§") + ["⏎"],
           ["⇧"] + list("²µ¿¡ñß") + ["⇧"],
           ["abc", "?123", "@", "␣", "←", "→"]]
LARGE = {"⌫": 1.6, "⇥": 1.4, "⏎": 1.6, "⇧": 1.4, "␣": 5.0, "?123": 1.5, "àé": 1.3, "abc": 1.5}
TAILLES = {"petit": 40, "moyen": 50, "grand": 62}


def champ_texte(w):
    """Le widget accepte-t-il du texte au clavier ?"""
    if w is None:
        return False
    if isinstance(w, QLineEdit):
        return not w.isReadOnly()
    if isinstance(w, (QTextEdit, QPlainTextEdit)):
        return not w.isReadOnly()
    if isinstance(w, QAbstractSpinBox):
        return not w.isReadOnly()
    if isinstance(w, QComboBox):
        return w.isEditable()
    return False


class Touche(QPushButton):
    def __init__(self, texte, hauteur, largeur=1.0):
        super().__init__(texte)
        self.valeur = texte
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setObjectName("touche")
        self.setMinimumHeight(hauteur)
        self.setMinimumWidth(int(hauteur * 0.82 * largeur))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        if texte == "⌫":
            self.setAutoRepeat(True)
            self.setAutoRepeatDelay(450)
            self.setAutoRepeatInterval(60)


class FenetreClavier(QFrame):
    """Le clavier complet, ou réduit à un bouton « clavier »."""

    def __init__(self, gestion):
        super().__init__(None, DRAPEAUX)
        self.g = gestion
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setObjectName("clavier_visuel")
        self.page = "lettres"
        self.maj = False
        self.verr = False
        self.reduit = False
        self._glisse = None
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(8, 6, 8, 8)
        self.v.setSpacing(6)
        # barre du haut : poignée pour déplacer, taille, réduire, fermer
        self.barre = QWidget()
        hb = QHBoxLayout(self.barre)
        hb.setContentsMargins(4, 0, 0, 0)
        self.titre = QLabel("Clavier visuel — glissez ici pour déplacer")
        self.titre.setObjectName("aide")
        hb.addWidget(self.titre, 1)
        for txt, info, f in (("A−", "Plus petit", lambda: self.g.taille(-1)), ("A+", "Plus grand", lambda: self.g.taille(1)),
                             ("▾", "Réduire", self.reduire), ("✕", "Fermer", self.g.fermer)):
            b = QPushButton(txt)
            b.setToolTip(info)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setObjectName("touche_barre")
            b.setFixedSize(36, 28)
            b.clicked.connect(f)
            hb.addWidget(b)
        self.v.addWidget(self.barre)
        self.zone = QWidget()
        self.grille = QVBoxLayout(self.zone)
        self.grille.setContentsMargins(0, 0, 0, 0)
        self.grille.setSpacing(5)
        self.v.addWidget(self.zone)
        # bouton réduit
        self.bouton_reduit = QPushButton("⌨  Clavier")
        self.bouton_reduit.setObjectName("clavier_reduit")
        self.bouton_reduit.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.bouton_reduit.setToolTip("Ouvrir le clavier visuel")
        self.bouton_reduit.setFixedHeight(44)
        self.bouton_reduit.clicked.connect(self.deplier)
        self.v.addWidget(self.bouton_reduit)
        self.bouton_reduit.hide()
        self.appliquer_style()
        self.construire()

    def appliquer_style(self):
        self.setStyleSheet(f"""
            QFrame#clavier_visuel {{ background: {C['panneau']}; border: 1px solid {C['trait']}; border-radius: 14px; }}
            QPushButton#touche {{ background: {C['surface']}; color: {C['texte']}; border: 1px solid {C['trait']};
                border-radius: 9px; font-size: 17px; font-weight: 600; padding: 0 4px; }}
            QPushButton#touche:hover {{ border-color: {C['accent']}; }}
            QPushButton#touche:pressed {{ background: {C['accent']}; color: white; }}
            QPushButton#touche[special="true"] {{ background: {C['surface2']}; font-size: 15px; }}
            QPushButton#touche[actif="true"] {{ background: {C['accent']}; color: white; border-color: {C['accent']}; }}
            QPushButton#touche_barre {{ background: transparent; color: {C['texte2']}; border: 1px solid {C['trait']};
                border-radius: 7px; font-weight: 700; }}
            QPushButton#touche_barre:hover {{ color: {C['texte']}; border-color: {C['accent']}; }}
            QPushButton#clavier_reduit {{ background: {C['accent']}; color: white; border: 0; border-radius: 10px;
                font-weight: 700; font-size: 15px; padding: 0 16px; }}
        """)

    def construire(self):
        while self.grille.count():
            it = self.grille.takeAt(0)
            if it.widget() is not None:
                it.widget().hide()
                it.widget().deleteLater()
            elif it.layout() is not None:
                lay = it.layout()
                while lay.count():
                    w = lay.takeAt(0).widget()
                    if w is not None:
                        w.hide()
                        w.deleteLater()
        h = TAILLES.get(self.g.taille_nom, 50)
        pages = {"lettres": QWERTY if self.g.disposition == "qwerty" else AZERTY, "symboles": SYMBOLES, "accents": ACCENTS}
        for rangee in pages[self.page]:
            lr = QHBoxLayout()
            lr.setSpacing(5)
            for t in rangee:
                k = Touche(self._etiquette(t), h, LARGE.get(t, 1.0))
                k.valeur = t
                speciale = t in LARGE or t in ("←", "→")
                k.setProperty("special", speciale)
                if t == "⇧":
                    k.setProperty("actif", self.maj or self.verr)
                if (t == "?123" and self.page == "symboles") or (t == "àé" and self.page == "accents"):
                    k.setProperty("actif", True)
                lr.addWidget(k, int(LARGE.get(t, 1.0) * 10))
                # ⌫ a la répétition automatique : « clicked » est émis en boucle tant qu'on garde le bouton enfoncé
                k.clicked.connect(lambda _c=False, t=t: self.appui(t))
            self.grille.addLayout(lr)
        self.titre.setText("Clavier visuel" + (" — MAJUSCULES" if self.verr else "") + " — glissez ici pour déplacer")
        self.adjustSize()

    def _etiquette(self, t):
        if t == "␣":
            return "espace"
        if len(t) == 1 and t.isalpha() and (self.maj or self.verr):
            return t.upper()
        if t == "⇧" and self.verr:
            return "⇪"
        return t

    def appui(self, t):
        if t == "⇧":
            if self.maj and not self.verr:
                self.verr, self.maj = True, False  # deux appuis : verrouillage des majuscules
            elif self.verr:
                self.verr = False
            else:
                self.maj = True
            self.construire()
            return
        if t in ("?123", "àé", "abc"):
            self.page = {"?123": "symboles", "àé": "accents", "abc": "lettres"}[t]
            self.construire()
            return
        texte = t
        if len(t) == 1 and t.isalpha() and (self.maj or self.verr):
            texte = t.upper()
        self.g.touche(texte)
        if self.maj and len(t) == 1:
            self.maj = False
            self.construire()

    def reduire(self):
        self.reduit = True
        self.barre.hide()
        self.zone.hide()
        self.bouton_reduit.show()
        self.v.setContentsMargins(0, 0, 0, 0)
        self.adjustSize()
        self.g.placer()

    def deplier(self):
        self.reduit = False
        self.bouton_reduit.hide()
        self.barre.show()
        self.zone.show()
        self.v.setContentsMargins(8, 6, 8, 8)
        self.adjustSize()
        self.g.manuel = True
        self.g.placer()

    def event(self, e):
        # Certains gestionnaires de fenêtres ignorent « ne prend pas le focus » : si le clavier devient la fenêtre
        # active, on rend la main tout de suite à la fenêtre où l'on écrit (sinon le champ perdrait le focus).
        if e.type() == QEvent.Type.WindowActivate:
            QTimer.singleShot(0, self.g.rendre_focus)
        return super().event(e)

    # déplacer à la souris (barre du haut)
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and not self.reduit:
            self._glisse = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._glisse is not None:
            self.move(e.globalPosition().toPoint() - self._glisse)
            self.g.position = self.pos()

    def mouseReleaseEvent(self, _e):
        self._glisse = None


class GestionClavier(QObject):
    """Suit le champ de texte actif et la fenêtre au premier plan ; envoie les touches."""

    def __init__(self, app, cfg, fen=None):
        super().__init__(app)
        self.app, self.cfg, self.fen = app, cfg, fen
        self.dernier = None      # dernier champ de texte (les clics sur le clavier ne déplacent pas le focus)
        self.manuel = False      # ouvert à la main : reste ouvert jusqu'à « fermer »
        self.position = None
        self.taille_nom = cfg.get("clavier.taille") or "moyen"
        self.disposition = cfg.get("clavier.disposition") or "azerty"
        self.fk = FenetreClavier(self)
        self._parent = None
        self._minuterie = QTimer(self)
        self._minuterie.setSingleShot(True)
        self._minuterie.timeout.connect(self._verifier_focus)
        app.focusChanged.connect(self._focus)
        app.installEventFilter(self)

    @property
    def mode(self):
        return self.cfg.get("clavier.mode") or "non"

    # --- fenêtre parente : toujours celle au premier plan (sinon une fenêtre modale bloquerait le clavier) ---
    def _fenetre_cible(self):
        m = QApplication.activeModalWidget()
        if m is not None and m.isVisible():
            return m
        w = QApplication.activeWindow()
        if w is not None and w is not self.fk and w.isVisible() and not (w.windowFlags() & Qt.WindowType.Popup) == Qt.WindowType.Popup:
            return w
        return self.fen

    def _rattacher(self, cible=None):
        cible = cible or self._fenetre_cible()
        if cible is None or cible is self._parent or cible is self.fk:
            return
        visible = self.fk.isVisible()
        pos = self.fk.pos()
        self.fk.setParent(cible, DRAPEAUX)
        self._parent = cible
        cible.installEventFilter(self)
        if visible:
            self.fk.move(pos)
            self.fk.show()
            self.fk.raise_()

    def eventFilter(self, obj, ev):
        t = ev.type()
        # la fenêtre qui porte le clavier se ferme : il passe à la suivante avant qu'elle ne soit détruite
        if obj is self._parent and t in (QEvent.Type.Hide, QEvent.Type.Close):
            suivante = None
            p = obj.parentWidget()
            if p is not None and p.window().isVisible():
                suivante = p.window()  # en général la fenêtre qui a ouvert celle-ci
            else:
                m = QApplication.activeModalWidget()
                if m is not None and m is not obj and m.isVisible():
                    suivante = m
            self._parent = None
            cible = suivante or (self.fen if obj is not self.fen else None)
            if cible is not None:
                self._rattacher(cible)
                f = cible.focusWidget()
                if champ_texte(f):
                    self.dernier = f
            else:
                self.fk.setParent(None, DRAPEAUX)
            return False
        if t == QEvent.Type.Show and obj is not self.fk and isinstance(obj, QWidget) and obj.isWindow() \
                and self.fk.isVisible() and obj.isModal():
            QTimer.singleShot(0, lambda o=obj: (self._rattacher(o), self.placer()))
        return False

    # --- focus ---------------------------------------------------------------------------------------
    def _dans_clavier(self, w):
        return w is not None and (w is self.fk or self.fk.isAncestorOf(w))

    def rendre_focus(self):
        """Le clavier a pris la main : la rendre à la fenêtre et au champ où l'on écrivait."""
        try:
            c = self.dernier if self.dernier is not None and self.dernier.isVisible() else None
        except RuntimeError:
            c = self.dernier = None
        fenetre = c.window() if c is not None else (self._parent or self.fen)
        if fenetre is not None and fenetre.isVisible():
            fenetre.activateWindow()
        if c is not None:
            c.setFocus(Qt.FocusReason.OtherFocusReason)

    def _focus(self, _ancien, nouveau):
        if self.mode == "non" and not self.manuel:
            return
        if nouveau is None or self._dans_clavier(nouveau) or QApplication.activeWindow() is self.fk:
            return  # clic sur le clavier : on ne change rien
        if champ_texte(nouveau):
            self.dernier = nouveau
            self._minuterie.stop()
            self._rattacher(nouveau.window())
            if self.mode == "auto" or self.manuel:
                if self.fk.reduit or not self.fk.isVisible():
                    self.ouvrir(reduit=False, manuel=self.manuel)
            elif not self.fk.isVisible():
                self.ouvrir(reduit=True)
        elif nouveau is not None and not self.manuel:
            self._minuterie.start(900)

    def _verifier_focus(self):
        if self.manuel or QApplication.activeWindow() is self.fk:
            return
        if not champ_texte(QApplication.focusWidget()):
            self.fk.hide()

    # --- affichage ---------------------------------------------------------------------------------
    def ouvrir(self, reduit=False, manuel=False):
        self.manuel = self.manuel or manuel
        self._rattacher()
        if reduit:
            self.fk.reduire()
        else:
            if self.fk.reduit:
                self.fk.reduit = False
                self.fk.bouton_reduit.hide()
                self.fk.barre.show()
                self.fk.zone.show()
                self.fk.v.setContentsMargins(8, 6, 8, 8)
            self.fk.construire()
        self.fk.show()
        self.fk.raise_()
        self.placer()

    def basculer(self):
        if self.fk.isVisible() and not self.fk.reduit:
            self.fermer()
        else:
            self.ouvrir(manuel=True)

    def fermer(self):
        self.manuel = False
        self.fk.hide()

    def taille(self, sens):
        noms = list(TAILLES)
        i = max(0, min(len(noms) - 1, noms.index(self.taille_nom) + sens))
        self.taille_nom = noms[i]
        self.cfg.set("clavier.taille", self.taille_nom)
        self.fk.construire()
        self.placer()

    def placer(self):
        self.fk.adjustSize()
        ecran = (self.fk.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        if self.fk.reduit:
            # petit bouton : coin bas droit de la fenêtre active
            ref = (self._parent or self.fen)
            r = ref.frameGeometry() if ref is not None else ecran
            self.fk.move(min(r.right(), ecran.right()) - self.fk.width() - 18, min(r.bottom(), ecran.bottom()) - self.fk.height() - 18)
            return
        largeur = min(ecran.width() - 20, max(self.fk.sizeHint().width(), int(ecran.width() * 0.62)))
        self.fk.resize(largeur, self.fk.sizeHint().height())
        if self.position is not None and ecran.contains(self.position):
            self.fk.move(self.position)
            return
        x = ecran.x() + (ecran.width() - self.fk.width()) // 2
        y = ecran.bottom() - self.fk.height() - 12
        # ne pas cacher le champ où l'on écrit : le clavier passe en haut si besoin
        c = self.dernier
        try:
            if c is not None and c.isVisible():
                bas_champ = c.mapToGlobal(QPoint(0, c.height())).y()
                if bas_champ > y - 8:
                    y = ecran.y() + 12
        except RuntimeError:
            pass
        self.fk.move(x, y)

    # --- envoi des touches ---------------------------------------------------------------------------
    def _cible(self):
        w = QApplication.focusWidget()
        if champ_texte(w) and not self._dans_clavier(w):
            return w
        try:
            if self.dernier is not None and self.dernier.isVisible() and champ_texte(self.dernier):
                self.dernier.setFocus(Qt.FocusReason.OtherFocusReason)
                return self.dernier
        except RuntimeError:
            self.dernier = None
        return None

    def touche(self, t):
        w = self._cible()
        if w is None:
            return
        cles = {"⌫": (Qt.Key.Key_Backspace, ""), "⏎": (Qt.Key.Key_Return, "\r"), "⇥": (Qt.Key.Key_Tab, "\t"),
                "←": (Qt.Key.Key_Left, ""), "→": (Qt.Key.Key_Right, ""), "␣": (Qt.Key.Key_Space, " ")}
        if t == "⇥":
            w.focusNextChild() if hasattr(w, "focusNextChild") else None
            nouveau = QApplication.focusWidget()
            if champ_texte(nouveau):
                self.dernier = nouveau
            return
        if t in cles:
            code, texte = cles[t]
        else:
            texte = t
            code = Qt.Key(ord(t.upper())) if len(t) == 1 and t.isascii() and t.isalnum() else Qt.Key.Key_unknown
        for typ in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            QApplication.sendEvent(w, QKeyEvent(typ, code, Qt.KeyboardModifier.NoModifier, texte))

    def reglages_changes(self):
        self.taille_nom = self.cfg.get("clavier.taille") or "moyen"
        self.disposition = self.cfg.get("clavier.disposition") or "azerty"
        self.fk.appliquer_style()
        if self.fk.isVisible():
            self.fk.construire()
            self.placer()
        if self.mode == "non" and not self.manuel:
            self.fk.hide()
