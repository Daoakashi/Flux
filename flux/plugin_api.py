"""Interface des plugins de Flux (version 1).

Un plugin est un dossier avec plugin.json (id, nom, version, description, flux_min) et plugin.py, qui définit :

    from flux.plugin_api import Plugin as Base

    class Plugin(Base):
        def demarrer(self): ...                 # au chargement (le contexte est self.ctx)
        def pages(self): return [("Titre", widget)]   # onglets affichés dans Flux › Plugins
        def filtrer(self, e): return e          # chaque événement de Flux (modifier, ou None pour le supprimer)
        def arreter(self): ...                  # à la désactivation ou à la fermeture de Flux

Le contexte (self.ctx) donne accès à Flux sans toucher à ses détails internes :
    ctx.cameras()                       noms des caméras
    ctx.emettre(texte, niveau, ...)     ajoute un événement (journal, alertes, télésurveillance, FluxLite)
    ctx.alarme(son=None) / ctx.couper_alarme()
    ctx.toast(texte, niveau)
    ctx.donnees() / ctx.enregistrer(d)  réglages du plugin (JSON, dans le dossier protégé de Flux)
    ctx.chiffrer(t) / ctx.dechiffrer(t) secrets (coffre de Flux)
    ctx.kiosque / ctx.demander_code_admin(parent)
    ctx.fen                             la fenêtre de Flux (usage avancé)

Niveaux d'événement : "info", "action", "alerte", "ok", "erreur". Un événement peut porter
    tele={"type": "intrusion", "sia": "BA", "cid": "130", "zone": 3}
pour partir vers la télésurveillance avec ces codes, quel que soit son niveau (ex. alarme silencieuse).
"""
import json
import os
import time


class Plugin:
    def __init__(self, ctx):
        self.ctx = ctx

    def demarrer(self):
        pass

    def pages(self):
        return []

    def filtrer(self, e):
        return e

    def arreter(self):
        pass


class Contexte:
    def __init__(self, gestionnaire, charge):
        self._g = gestionnaire
        self._p = charge
        self.id = charge.id
        self.info = dict(charge.info)

    @property
    def fen(self):
        return self._g.fen

    @property
    def kiosque(self):
        return bool(getattr(self._g.fen, "kiosque", False))

    # --- caméras ---------------------------------------------------------------------------------------
    def cameras(self):
        fen = self._g.fen
        try:
            return list(fen.page_cameras.noms_cameras())
        except AttributeError:
            return []

    # --- événements ------------------------------------------------------------------------------------
    def emettre(self, texte, niveau="info", source=None, type_action=None, tele=None, alarme=False, jpeg=None,
                silencieux=False, prioritaire=False):
        e = {"heure": time.strftime("%H:%M:%S"), "source": source or self.info.get("nom", self.id), "texte": texte,
             "niveau": niveau, "chemin": None, "jpeg": jpeg, "personne_id": None, "type_action": type_action,
             "detail": "", "alarme": alarme, "prioritaire": prioritaire, "plugin": self.id}
        if tele:
            e["tele"] = dict(tele)
        if silencieux:
            e["silencieux"] = True
        fen = self._g.fen
        if fen is not None and hasattr(fen, "evenements"):
            fen.evenements.put(e)
        return e

    def alarme(self, son=None):
        fen = self._g.fen
        if fen is not None and hasattr(fen, "alarme"):
            fen.alarme.jouer(son)

    def couper_alarme(self):
        fen = self._g.fen
        if fen is not None and hasattr(fen, "alarme"):
            fen.alarme.arreter()

    def toast(self, texte, niveau="info"):
        fen = self._g.fen
        if fen is not None and hasattr(fen, "toast"):
            fen.toast(texte, niveau)

    def demander_code_admin(self, titre="Modification protégée"):
        """En kiosque : demande le code administrateur (True si correct). Hors kiosque : True."""
        fen = self._g.fen
        if not self.kiosque or fen is None:
            return True
        return bool(fen.demander_code_kiosque(titre))

    # --- données ---------------------------------------------------------------------------------------
    def _chemin(self):
        from .plugins import DOSSIER_DONNEES
        return os.path.join(DOSSIER_DONNEES, self.id + ".json")

    def donnees(self, defaut=None):
        try:
            with open(self._chemin(), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return defaut if defaut is not None else {}

    def enregistrer(self, d):
        chemin = self._chemin()
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
        tmp = chemin + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1, ensure_ascii=False)
        os.replace(tmp, chemin)

    def chiffrer(self, texte):
        from . import coffre
        return coffre.chiffrer(texte, "plugin:" + self.id)

    def dechiffrer(self, valeur):
        from . import coffre
        return coffre.dechiffrer(valeur, "plugin:" + self.id)
