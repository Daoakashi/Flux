"""Garde-fous d'affichage appliqués à toute l'application.

Sur Linux, les polices par défaut (DejaVu Sans, Noto Sans, Ubuntu) sont plus larges que Segoe UI et l'échelle
de l'écran est souvent différente : un titre ou une liste déroulante trop large poussait alors toute la page
vers la droite (texte coupé ou caché). Ce filtre s'applique à chaque élément au moment de son premier affichage :
- les titres (« titre », « titre_section », « grand ») passent à la ligne au lieu d'élargir la page ;
- les listes déroulantes ne s'élargissent plus au libellé le plus long (le texte est raccourci dans le champ,
  la liste ouverte reste complète) ;
- les zones de défilement ne défilent jamais horizontalement (la page s'adapte à la largeur).
"""
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QComboBox, QLabel, QScrollArea

TITRES = {"titre", "titre_section", "grand"}


class GardeAffichage(QObject):
    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Polish:
            try:
                ajuster(obj)
            except RuntimeError:  # élément détruit entre-temps
                pass
        return False


def ajuster(w):
    if isinstance(w, QLabel):
        if w.objectName() in TITRES and not w.wordWrap():
            w.setWordWrap(True)
    elif isinstance(w, QComboBox):
        if w.sizeAdjustPolicy() == QComboBox.SizeAdjustPolicy.AdjustToContentsOnFirstShow:
            w.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            w.setMinimumContentsLength(12)
        # la liste ouverte reste à la largeur des libellés (Qt l'élargit déjà d'office)
    elif isinstance(w, QScrollArea) and w.widgetResizable():
        if w.property("defilement_horizontal") is not True:  # exception possible, au cas par cas
            w.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)


_garde = None


def installer(app):
    """À appeler une fois, juste après la création de QApplication."""
    global _garde
    if _garde is None:
        _garde = GardeAffichage(app)
        app.installEventFilter(_garde)
    return _garde
