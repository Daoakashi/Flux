"""Exécuter un travail lent hors du fil de l'interface et récupérer le résultat dans l'interface."""

import threading

from PySide6.QtCore import QObject, Signal

_EN_COURS = set()


class Tache(QObject):
    fini = Signal(object)
    echec = Signal(str)
    progression = Signal(float)

    def __init__(self, fonction, *args, **kwargs):
        super().__init__()
        self._f, self._a, self._k = fonction, args, kwargs

    def lancer(self):
        _EN_COURS.add(self)  # garder une référence tant que le travail tourne
        threading.Thread(target=self._executer, daemon=True).start()
        return self

    def _executer(self):
        try:
            r = self._f(*self._a, **self._k)
        except Exception as e:  # noqa: BLE001
            self.echec.emit(str(e) or e.__class__.__name__)
        else:
            self.fini.emit(r)
        finally:
            _EN_COURS.discard(self)


def en_arriere_plan(fonction, succes=None, erreur=None, *args, **kwargs):
    t = Tache(fonction, *args, **kwargs)
    if succes:
        t.fini.connect(succes)
    if erreur:
        t.echec.connect(erreur)
    return t.lancer()
