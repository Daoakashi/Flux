"""Bouton Feedback : envoyer une idée, un problème ou une question à l'éditeur de Flux.

Deux chemins au choix, sans compte ni serveur à héberger :
- par mail : ouvre la messagerie de l'ordinateur avec un message déjà rempli ;
- sur GitHub : ouvre la page « nouveau ticket » du dépôt, déjà remplie (compte GitHub nécessaire).

Rien n'est envoyé automatiquement : la personne relit son message avant de l'envoyer. Seules la version de Flux et
celle du système sont ajoutées, jamais d'image, de réglage ni de donnée des caméras.
"""
import platform
import urllib.parse

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout

from .theme import C
from .widgets import Bouton, etiquette

MAIL = "dms.security.list@gmail.com"
GITHUB = "https://github.com/Daoakashi/Flux/issues/new"
SUJETS = ["Idée ou suggestion", "Problème (bug)", "Question", "Autre"]


def contexte(programme, version):
    return (f"Programme : {programme} {version}\n"
            f"Système : {platform.system()} {platform.release()} ({platform.machine()})\n"
            f"Python : {platform.python_version()}")


def lien_mail(programme, sujet, texte):
    return (f"mailto:{MAIL}?subject={urllib.parse.quote(f'{programme} · {sujet}')}"
            f"&body={urllib.parse.quote(texte)}")


def lien_github(sujet, texte, depot_url=GITHUB):
    return f"{depot_url}?title={urllib.parse.quote(f'[{sujet}] ')}&body={urllib.parse.quote(texte)}"


class DialogueFeedback(QDialog):
    def __init__(self, parent, programme, version, kiosque=False, depot_url=GITHUB):
        super().__init__(parent)
        self.programme, self.version, self.depot_url = programme, version, depot_url
        self.setWindowTitle("Feedback")
        self.setMinimumWidth(640)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 22, 24, 20)
        v.setSpacing(8)
        t = QLabel("Feedback")
        t.setObjectName("grand")
        v.addWidget(t)
        v.addWidget(etiquette("Une idée, un problème, une question ? Votre message aide à améliorer Flux. N'y mettez ni "
                              "mot de passe ni image des caméras : seules les versions du programme et du système sont "
                              "ajoutées."))
        v.addWidget(QLabel("Sujet"))
        self.sujet = QComboBox()
        self.sujet.addItems(SUJETS)
        v.addWidget(self.sujet)
        v.addWidget(QLabel("Message"))
        self.texte = QPlainTextEdit()
        self.texte.setPlaceholderText("Décrivez votre idée ou le problème rencontré (ce que vous faisiez, ce qui s'est "
                                      "passé, ce que vous attendiez)…")
        self.texte.setMinimumHeight(150)
        v.addWidget(self.texte, 1)
        ctx = QLabel(contexte(programme, version))
        ctx.setObjectName("soustitre")
        v.addWidget(ctx)
        if kiosque:
            # En kiosque, la messagerie et le navigateur s'ouvriraient derrière Flux : on copie le message
            lab = etiquette(f"Mode kiosque : copiez le message, puis envoyez-le depuis un autre appareil à {MAIL}.")
            lab.setStyleSheet(f"color: {C['attention']};")
            v.addWidget(lab)
        h = QHBoxLayout()
        b0 = Bouton("Annuler", "fantome")
        b0.clicked.connect(self.reject)
        h.addWidget(b0)
        h.addStretch(1)
        bc = Bouton("Copier le message", "discret")
        bc.clicked.connect(self._copier)
        h.addWidget(bc)
        if not kiosque:
            bg = Bouton("Signaler sur GitHub", "discret", "lien")
            bg.setToolTip("Ouvre un ticket public sur GitHub (compte GitHub nécessaire).")
            bg.clicked.connect(self._github)
            h.addWidget(bg)
            bm = Bouton("Envoyer par mail", "primaire", "message")
            bm.setToolTip(f"Ouvre votre messagerie avec un message pour {MAIL}.")
            bm.clicked.connect(self._mail)
            h.addWidget(bm)
        v.addLayout(h)
        self.texte.setFocus()

    def _corps(self):
        return f"{self.texte.toPlainText().strip()}\n\n---\n{contexte(self.programme, self.version)}"

    def _copier(self):
        QGuiApplication.clipboard().setText(f"À : {MAIL}\nSujet : {self.programme} · {self.sujet.currentText()}\n\n"
                                            f"{self._corps()}")
        parent = self.parent()
        if parent is not None and hasattr(parent, "toast"):
            parent.toast("Message copié.", "ok")

    def _mail(self):
        QDesktopServices.openUrl(QUrl(lien_mail(self.programme, self.sujet.currentText(), self._corps())))
        self.accept()

    def _github(self):
        QDesktopServices.openUrl(QUrl(lien_github(self.sujet.currentText(), self._corps(), self.depot_url)))
        self.accept()
