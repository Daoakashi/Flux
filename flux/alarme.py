"""Sons d'alarme (IVS et alertes) : générés par Flux, sans fichier à télécharger.

Son de base : 5 bips, un toutes les 0,4 seconde. Autres sons au choix dans Réglages › IVS.
Les sons sont fabriqués une fois (fichiers WAV dans le dossier temporaire) puis joués par Qt Multimedia ;
sans carte son, Flux se contente du bip du système.
"""
import math
import os
import struct
import tempfile
import wave

FREQ = 44100

SONS = [
    ("base", "Base : 5 bips (0,4 s)"),
    ("sirene", "Sirène montante"),
    ("deux_tons", "Deux tons (pin-pon)"),
    ("rapide", "Bips rapides"),
    ("carillon", "Carillon (discret)"),
    ("grave", "Klaxon grave"),
    ("fichier", "Fichier personnel (.wav)"),
]


def _bip(freq, duree, volume=0.6, forme="sinus"):
    n = int(FREQ * duree)
    fondu = int(FREQ * 0.008)  # attaque et fin adoucies : pas de « clic »
    out = []
    for i in range(n):
        t = i / FREQ
        if forme == "carre":
            v = 1.0 if math.sin(2 * math.pi * freq * t) >= 0 else -1.0
            v *= 0.55
        else:
            v = math.sin(2 * math.pi * freq * t) + 0.25 * math.sin(4 * math.pi * freq * t)
            v /= 1.25
        env = min(1.0, i / fondu if fondu else 1.0, (n - i) / fondu if fondu else 1.0)
        out.append(v * env * volume)
    return out


def _silence(duree):
    return [0.0] * int(FREQ * duree)


def echantillons(nom):
    """Échantillons (-1..1) du son demandé."""
    s = []
    if nom == "sirene":
        n = int(FREQ * 2.4)
        phase = 0.0
        for i in range(n):
            t = i / FREQ
            f = 600 + 700 * (0.5 - 0.5 * math.cos(2 * math.pi * t / 1.2))
            phase += 2 * math.pi * f / FREQ
            env = min(1.0, i / 400, (n - i) / 400)
            s.append(0.55 * math.sin(phase) * env)
    elif nom == "deux_tons":
        for _ in range(3):
            s += _bip(435, 0.4, 0.55) + _bip(580, 0.4, 0.55)
    elif nom == "rapide":
        for _ in range(10):
            s += _bip(1200, 0.08, 0.55, "carre") + _silence(0.07)
    elif nom == "carillon":
        for f in (1046.5, 1318.5, 1568.0):
            note = _bip(f, 0.45, 0.5)
            k = len(note)
            s += [v * math.exp(-4.0 * i / k) for i, v in enumerate(note)]
    elif nom == "grave":
        for _ in range(3):
            s += _bip(220, 0.35, 0.6, "carre") + _silence(0.15)
    else:  # base : 5 bips, un toutes les 0,4 s (0,2 s de son, 0,2 s de silence)
        for _ in range(5):
            s += _bip(880, 0.2, 0.6) + _silence(0.2)
    return s


def ecrire_wav(chemin, ech):
    with wave.open(chemin, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(FREQ)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1.0, min(1.0, v)) * 32000)) for v in ech))


def fichier_son(nom):
    """Chemin du WAV pour ce son (créé au premier usage)."""
    dossier = os.path.join(tempfile.gettempdir(), "flux-sons")
    os.makedirs(dossier, exist_ok=True)
    chemin = os.path.join(dossier, f"{nom}-v1.wav")
    if not os.path.exists(chemin):
        tmp = chemin + ".tmp"
        ecrire_wav(tmp, echantillons(nom))
        os.replace(tmp, chemin)
    return chemin


class Alarme:
    """Joue le son choisi dans les Réglages. Une seule alarme à la fois (pas de cacophonie)."""

    def __init__(self, cfg):
        self.cfg = cfg
        self._effet = None
        self._source = None

    def _chemin(self, nom=None):
        nom = nom or self.cfg.get("ivs.son") or "base"
        if nom == "fichier":
            f = (self.cfg.get("ivs.fichier_son") or "").strip()
            if f and os.path.isfile(f) and f.lower().endswith(".wav"):
                return f
            nom = "base"
        return fichier_son(nom if nom in dict(SONS) else "base")

    def jouer(self, nom=None, repetitions=None):
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtMultimedia import QSoundEffect
        except ImportError:
            return self._bip()
        try:
            chemin = self._chemin(nom)
            if self._effet is None:
                self._effet = QSoundEffect()
            if self._effet.isPlaying():
                return True  # déjà en train de sonner
            if self._source != chemin:
                self._effet.setSource(QUrl.fromLocalFile(chemin))
                self._source = chemin
            self._effet.setVolume(max(0.0, min(1.0, (self.cfg.get("ivs.volume") or 80) / 100)))
            n = repetitions if repetitions is not None else int(self.cfg.get("ivs.repetitions") or 1)
            self._effet.setLoopCount(max(1, n))
            self._effet.play()
            return True
        except Exception:  # noqa: BLE001  — pas de carte son : bip du système
            return self._bip()

    def arreter(self):
        if self._effet is not None:
            self._effet.stop()

    @staticmethod
    def _bip():
        try:
            from PySide6.QtWidgets import QApplication
            QApplication.beep()
        except Exception:  # noqa: BLE001
            pass
        return False
