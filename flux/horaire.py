"""Plage horaire de la détection : par exemple de 6 h à 22 h, ou la nuit seulement (22 h à 6 h), certains jours.

En dehors de la plage, les caméras restent affichées mais rien n'est analysé : ni alerte, ni vidéo, ni action.
Réglable dans Flux (Réglages › Détection) et à distance depuis FluxLite, Flux Remote et l'interface web.
"""
import re
import time
from datetime import datetime, timedelta

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
JOURS_COURTS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
_RE_HEURE = re.compile(r"^([01]?\d|2[0-3])[:hH.]([0-5]\d)$")


def heure_valide(texte):
    """« 6:00 », « 06h00 », « 6.30 » -> « 06:00 », ou None."""
    m = _RE_HEURE.match(str(texte or "").strip())
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


def _minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def jours_depuis_texte(texte):
    """« 12345 » (1 = lundi) -> [0, 1, 2, 3, 4]."""
    return sorted({int(c) - 1 for c in str(texte or "") if c in "1234567"})


def texte_depuis_jours(jours):
    return "".join(str(j + 1) for j in sorted(set(jours)) if 0 <= j <= 6)


def lire(cfg):
    """Plage enregistrée dans les réglages de Flux, toujours valide."""
    jours = jours_depuis_texte(cfg.get("horaire.jours"))
    return {"actif": bool(cfg.get("horaire.actif")),
            "debut": heure_valide(cfg.get("horaire.debut")) or "06:00",
            "fin": heure_valide(cfg.get("horaire.fin")) or "22:00",
            "jours": jours if jours else list(range(7))}


def valider(v):
    """Plage reçue d'une application (pilotage à distance). Lève ValueError si elle est invalide."""
    if not isinstance(v, dict):
        raise ValueError("plage horaire invalide")
    debut, fin = heure_valide(v.get("debut")), heure_valide(v.get("fin"))
    if not debut or not fin:
        raise ValueError("heure invalide (format 06:00)")
    jours = v.get("jours", list(range(7)))
    if not isinstance(jours, list) or not all(isinstance(j, int) and not isinstance(j, bool) and 0 <= j <= 6 for j in jours):
        raise ValueError("jours invalides (0 = lundi … 6 = dimanche)")
    if not jours:
        raise ValueError("choisissez au moins un jour")
    actif = v.get("actif", True)
    if not isinstance(actif, bool):
        raise ValueError("« actif » doit valoir vrai ou faux")
    return {"actif": actif, "debut": debut, "fin": fin, "jours": sorted(set(jours))}


def enregistrer(cfg, h):
    cfg.set("horaire.actif", bool(h["actif"]))
    cfg.set("horaire.debut", h["debut"])
    cfg.set("horaire.fin", h["fin"])
    cfg.set("horaire.jours", texte_depuis_jours(h["jours"]))


def dans_plage(h, maintenant=None):
    """La détection doit-elle tourner maintenant ? Une plage qui passe minuit (22:00 → 06:00) compte pour le jour
    où elle commence : « vendredi de 22 h à 6 h » couvre aussi la nuit du vendredi au samedi."""
    if not h["actif"]:
        return True
    t = maintenant or datetime.now()
    m, jour = t.hour * 60 + t.minute, t.weekday()
    d, f = _minutes(h["debut"]), _minutes(h["fin"])
    if d == f:  # toute la journée, les jours choisis
        return jour in h["jours"]
    if d < f:
        return jour in h["jours"] and d <= m < f
    return (m >= d and jour in h["jours"]) or (m < f and (jour - 1) % 7 in h["jours"])


def prochain_changement(h, maintenant=None):
    """Heure du prochain début ou de la prochaine fin de plage (pour l'affichage), ou None."""
    if not h["actif"]:
        return None
    t = (maintenant or datetime.now()).replace(second=0, microsecond=0)
    etat = dans_plage(h, t)
    for i in range(1, 8 * 24 * 60 + 1):
        u = t + timedelta(minutes=i)
        if dans_plage(h, u) != etat:
            return u
    return None


def texte(h):
    """« De 06:00 à 22:00, du lundi au vendredi » (pour le journal et les applications)."""
    if not h["actif"]:
        return "Toujours (pas de plage horaire)"
    j = sorted(h["jours"])
    if j == list(range(7)):
        jours = "tous les jours"
    elif j == list(range(5)):
        jours = "du lundi au vendredi"
    elif j == [5, 6]:
        jours = "le week-end"
    elif j == list(range(6)):
        jours = "du lundi au samedi"
    elif len(j) > 2 and j == list(range(j[0], j[-1] + 1)):
        jours = f"du {JOURS[j[0]]} au {JOURS[j[-1]]}"
    else:
        noms = [JOURS[x] for x in j]
        jours = "le " + (", ".join(noms[:-1]) + " et " + noms[-1] if len(noms) > 1 else noms[0])
    if h["debut"] == h["fin"]:
        return f"Toute la journée, {jours}"
    nuit = " (la nuit)" if _minutes(h["debut"]) > _minutes(h["fin"]) else ""
    return f"De {h['debut']} à {h['fin']}{nuit}, {jours}"


class Etat:
    """Réponse mise en cache 5 secondes : appelée pour chaque image de chaque caméra."""
    def __init__(self, cfg):
        self.cfg = cfg
        self._t = 0.0
        self._val = True

    def actif(self):
        now = time.monotonic()
        if now - self._t > 5:
            self._t = now
            try:
                self._val = dans_plage(lire(self.cfg))
            except Exception:  # noqa: BLE001 — réglage illisible : on ne coupe jamais la surveillance par erreur
                self._val = True
        return self._val


_ETATS = {}


def actif_maintenant(cfg):
    """La plage horaire autorise-t-elle la détection en ce moment ? (mis en cache, sûr entre fils)"""
    e = _ETATS.get(id(cfg))
    if e is None or e.cfg is not cfg:
        e = _ETATS[id(cfg)] = Etat(cfg)
    return e.actif()


def oublier_cache():
    """Après un changement de la plage : la réponse est recalculée tout de suite."""
    for e in _ETATS.values():
        e._t = 0.0
