"""Fréquentation : carte de chaleur (heatmap) et statistiques de présence, par caméra et par zone.

Ce qui est enregistré est anonyme et agrégé : pour chaque caméra et chaque heure, une grille de « temps passé »
(où se tiennent les personnes, en personnes × secondes), le temps d'observation, la présence cumulée, le pic de
personnes simultanées, le nombre de passages, et les mêmes chiffres par zone. Aucune image de personne, aucun
visage, aucune identité. Seule une image de fond (prise quand personne n'est à l'image) sert de décor à la carte.

Un passage = une personne confirmée par l'analyse (les animaux et silhouettes douteuses sont déjà écartés).
La position retenue est celle des pieds (bas du cadre) : c'est là que la personne se tient dans le magasin.
"""

import json
import threading
import time

import cv2
import numpy as np

GX, GY = 96, 54          # résolution de la grille (16:9)
FLUSH = 60.0             # écriture dans la base au plus toutes les 60 s
FOND_ECHANTILLON = 30.0  # une image prélevée toutes les 30 s pour composer le fond
FOND_INTERVALLE = 600.0  # fond enregistré dans la base au plus toutes les 10 min

SCHEMA = """
CREATE TABLE IF NOT EXISTS frequentation (
    camera TEXT NOT NULL,
    heure INTEGER NOT NULL,            -- début de l'heure (horodatage Unix)
    observe REAL NOT NULL DEFAULT 0,   -- secondes pendant lesquelles la caméra était analysée
    presence REAL NOT NULL DEFAULT 0,  -- personnes × secondes
    max_personnes INTEGER NOT NULL DEFAULT 0,
    passages INTEGER NOT NULL DEFAULT 0,
    grille BLOB,                       -- float32 GY × GX, personnes × secondes par case
    zones TEXT NOT NULL DEFAULT '{}',  -- {nom: [personnes × secondes, passages]}
    PRIMARY KEY (camera, heure)
);
CREATE TABLE IF NOT EXISTS frequentation_fond (
    camera TEXT PRIMARY KEY,
    jpeg BLOB,
    maj REAL
);
"""


def preparer_base(base):
    if getattr(base, "_frequentation_prete", False):
        return
    with base._lock:
        base._c.executescript(SCHEMA)
        base._c.commit()
    base._frequentation_prete = True


# ---------------------------------------------------------------------------
# Collecte (dans le fil de chaque caméra)
# ---------------------------------------------------------------------------
class Collecteur:
    def __init__(self, camera, base, cfg):
        self.camera, self.base, self.cfg = camera, base, cfg
        self._t = None
        self._heure = None
        self._vus_heure = set()      # personnes déjà comptées comme passage dans l'heure en cours
        self._vus_zones = {}         # nom de zone -> personnes déjà comptées dans cette zone, cette heure
        self._raz()
        self._dernier_flush = time.time()
        self._dernier_fond = 0.0
        self._dernier_echantillon = 0.0
        self._echantillons = []      # petites images, personnes gommées : leur médiane donne un fond sans personne
        self._lock = threading.Lock()

    def _raz(self):
        self.grille = np.zeros((GY, GX), np.float32)
        self.observe = 0.0
        self.presence = 0.0
        self.max_personnes = 0
        self.passages = 0
        self.zones = {}      # nom -> [personnes × secondes, nouveaux passages]

    def ajouter(self, ann, frame=None, t=None):
        """Appelée à chaque image traitée par la caméra, avec la dernière analyse."""
        if not self.cfg.get("frequentation.actif") or ann is None:
            return
        t = time.time() if t is None else t
        dt = 0.0 if self._t is None else min(2.0, max(0.0, t - self._t))
        self._t = t
        heure = int(t // 3600 * 3600)
        with self._lock:
            if self._heure is not None and heure != self._heure:
                self._ecrire()
                self._vus_heure, self._vus_zones = set(), {}
            self._heure = heure
            if ann.get("detection_coupee"):
                return  # détection désactivée : rien n'est compté, ni observé
            w, h = ann.get("w") or 1, ann.get("h") or 1
            pistes = ann.get("pistes") or []
            self.observe += dt
            self.max_personnes = max(self.max_personnes, len(pistes))
            zones = ann.get("zones") or []
            for p in pistes:
                x1, y1, x2, y2 = p["box"][:4]
                fx, fy = min(max((x1 + x2) / 2 / w, 0.0), 0.999), min(max(y2 / h, 0.0), 0.999)
                self.grille[int(fy * GY), int(fx * GX)] += dt
                self.presence += dt
                if p["id"] not in self._vus_heure:
                    self._vus_heure.add(p["id"])
                    self.passages += 1
                for z in zones:
                    if _dans(fx, fy, z):
                        e = self.zones.setdefault(z["nom"], [0.0, 0])
                        e[0] += dt
                        vus = self._vus_zones.setdefault(z["nom"], set())
                        if p["id"] not in vus:
                            vus.add(p["id"])
                            e[1] += 1
            if frame is not None and t - self._dernier_echantillon >= FOND_ECHANTILLON:
                self._dernier_echantillon = t
                self._echantillonner(frame, ann)
                if (self._dernier_fond == 0.0 and len(self._echantillons) >= 2) or t - self._dernier_fond > FOND_INTERVALLE:
                    self._dernier_fond = t
                    self._enregistrer_fond()
            if time.time() - self._dernier_flush >= FLUSH:
                self._ecrire()

    def vider(self):
        with self._lock:
            self._ecrire()
            if self._echantillons and time.time() - self._dernier_fond > 60:
                self._dernier_fond = time.time()
                self._enregistrer_fond()

    def _ecrire(self):
        self._dernier_flush = time.time()
        if self.base is None or self._heure is None or (self.observe <= 0 and not self.passages):
            self._raz()
            return
        try:
            ajouter_heure(self.base, self.camera, self._heure, self.observe, self.presence, self.max_personnes,
                          self.passages, self.grille, dict(self.zones))
        except Exception:  # noqa: BLE001  — les statistiques ne doivent jamais arrêter une caméra
            pass
        self._raz()

    def _echantillonner(self, frame, ann):
        """Garde une petite copie de l'image où chaque personne détectée est gommée (fortement floutée)."""
        h, w = frame.shape[:2]
        f = min(1.0, 960.0 / w)
        img = cv2.resize(frame, (int(w * f), int(h * f)), interpolation=cv2.INTER_AREA) if f < 1 else frame.copy()
        aw, ah = ann.get("w") or w, ann.get("h") or h
        sx, sy = img.shape[1] / aw, img.shape[0] / ah
        masque = np.zeros(img.shape[:2], np.uint8)
        for p in (ann.get("personnes") or []):
            x1, y1, x2, y2 = p[:4]
            mx, my = (x2 - x1) * 0.15, (y2 - y1) * 0.08
            a, b = int(max(0, (x1 - mx) * sx)), int(max(0, (y1 - my) * sy))
            c, d = int(min(img.shape[1], (x2 + mx) * sx)), int(min(img.shape[0], (y2 + my) * sy))
            if c - a > 2 and d - b > 2:
                masque[b:d, a:c] = 255
        if masque.any():
            # retouche à basse résolution (rapide), puis remise à l'échelle : la personne est remplacée par le décor
            k = 4
            petit = cv2.resize(img, (img.shape[1] // k, img.shape[0] // k), interpolation=cv2.INTER_AREA)
            pm = cv2.resize(masque, (petit.shape[1], petit.shape[0]), interpolation=cv2.INTER_NEAREST)
            rep = cv2.inpaint(petit, pm, 5, cv2.INPAINT_TELEA)
            rep = cv2.GaussianBlur(cv2.resize(rep, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_LINEAR), (0, 0), 3)
            img[masque > 0] = rep[masque > 0]
        self._echantillons.append(img)
        self._echantillons = self._echantillons[-9:]

    def _enregistrer_fond(self):
        """Fond de la carte : médiane des dernières images (les personnes qui passent disparaissent), personnes
        immobiles gommées, et têtes floutées en plus si la confidentialité est cochée. Jamais d'image brute."""
        if self.base is None or not self._echantillons:
            return
        try:
            pile = [e for e in self._echantillons if e.shape == self._echantillons[-1].shape]
            img = np.median(np.stack(pile), axis=0).astype(np.uint8) if len(pile) >= 3 else pile[-1]
            ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                preparer_base(self.base)
                self.base._ecrire("INSERT OR REPLACE INTO frequentation_fond(camera, jpeg, maj) VALUES (?,?,?)",
                                  (self.camera, buf.tobytes(), time.time()))
        except Exception:  # noqa: BLE001
            pass


def _dans(x, y, z):
    try:
        from .vision import point_dans_zone
        return point_dans_zone(x, y, z)
    except Exception:  # noqa: BLE001
        x1, y1, x2, y2 = z["rect"]
        return x1 <= x <= x2 and y1 <= y <= y2


# ---------------------------------------------------------------------------
# Base de données
# ---------------------------------------------------------------------------
def ajouter_heure(base, camera, heure, observe, presence, max_p, passages, grille, zones):
    """Ajoute (cumule) une tranche de mesures dans la ligne de l'heure correspondante."""
    preparer_base(base)
    with base._lock:
        r = base._c.execute("SELECT observe, presence, max_personnes, passages, grille, zones FROM frequentation "
                            "WHERE camera=? AND heure=?", (camera, heure)).fetchone()
        g = grille.astype(np.float32)
        z = {n: [float(v[0]), int(v[1])] for n, v in zones.items()}
        if r is not None:
            if r["grille"]:
                g = g + np.frombuffer(r["grille"], np.float32).reshape(GY, GX)
            ancien = json.loads(r["zones"] or "{}")
            for n, (s, k) in ancien.items():
                e = z.setdefault(n, [0.0, 0])
                e[0] += s
                e[1] += k
            observe += r["observe"]
            presence += r["presence"]
            max_p = max(max_p, r["max_personnes"])
            passages += r["passages"]
        base._c.execute("INSERT OR REPLACE INTO frequentation(camera, heure, observe, presence, max_personnes, "
                        "passages, grille, zones) VALUES (?,?,?,?,?,?,?,?)",
                        (camera, heure, observe, presence, int(max_p), int(passages), g.tobytes(), json.dumps(z)))
        base._c.commit()


def cameras(base):
    preparer_base(base)
    return [r[0] for r in base._lire("SELECT DISTINCT camera FROM frequentation ORDER BY camera")]


def fond(base, camera):
    preparer_base(base)
    r = base._lire("SELECT jpeg FROM frequentation_fond WHERE camera=?", (camera,))
    if r and r[0][0]:
        return cv2.imdecode(np.frombuffer(r[0][0], np.uint8), cv2.IMREAD_COLOR)
    return None


def purger(base, jours):
    if not jours or jours <= 0:
        return 0
    preparer_base(base)
    return base._ecrire("DELETE FROM frequentation WHERE heure < ?", (time.time() - jours * 86400,)).rowcount


def charger(base, camera, debut, fin):
    """Statistiques cumulées d'une caméra entre deux horodatages."""
    preparer_base(base)
    lignes = base._lire("SELECT * FROM frequentation WHERE camera=? AND heure>=? AND heure<? ORDER BY heure",
                        (camera, int(debut // 3600 * 3600), fin))
    grille = np.zeros((GY, GX), np.float32)
    observe = presence = 0.0
    max_p, passages, heure_max = 0, 0, None
    par_heure_obs, par_heure_pres = np.zeros(24), np.zeros(24)
    par_jour = {}
    zones = {}
    for r in lignes:
        if r["grille"]:
            grille += np.frombuffer(r["grille"], np.float32).reshape(GY, GX)
        observe += r["observe"]
        presence += r["presence"]
        passages += r["passages"]
        if r["max_personnes"] > max_p:
            max_p, heure_max = r["max_personnes"], r["heure"]
        lt = time.localtime(r["heure"])
        par_heure_obs[lt.tm_hour] += r["observe"]
        par_heure_pres[lt.tm_hour] += r["presence"]
        jour = time.strftime("%Y-%m-%d", lt)
        j = par_jour.setdefault(jour, [0, 0.0, 0.0])
        j[0] += r["passages"]
        j[1] += r["presence"]
        j[2] += r["observe"]
        for n, (s, k) in json.loads(r["zones"] or "{}").items():
            e = zones.setdefault(n, [0.0, 0])
            e[0] += s
            e[1] += k
    with np.errstate(divide="ignore", invalid="ignore"):
        moyenne_heure = np.where(par_heure_obs > 0, par_heure_pres / np.maximum(par_heure_obs, 1e-9), np.nan)
    return {"grille": grille, "observe": observe, "presence": presence, "passages": passages,
            "max_personnes": max_p, "heure_max": heure_max, "moyenne": presence / observe if observe else 0.0,
            "par_heure": moyenne_heure, "par_jour": par_jour, "zones": zones, "lignes": len(lignes)}


# ---------------------------------------------------------------------------
# Rendu de la carte de chaleur
# ---------------------------------------------------------------------------
def _palette():
    """Rampe séquentielle : bleu nuit transparent → cyan → jaune → orange → rouge (plus c'est chaud, plus il y a
    de monde). Les zones vides restent transparentes : on voit le magasin dessous."""
    reperes = [(0.00, (40, 20, 10)), (0.25, (200, 160, 40)), (0.50, (60, 230, 250)), (0.75, (20, 140, 255)),
               (1.00, (40, 30, 230))]  # BGR
    lut = np.zeros((256, 3), np.float32)
    for i in range(256):
        v = i / 255.0
        for (a, ca), (b, cb) in zip(reperes, reperes[1:]):
            if a <= v <= b:
                k = (v - a) / (b - a)
                lut[i] = np.array(ca) * (1 - k) + np.array(cb) * k
                break
    return lut


_LUT = _palette()


def densite(grille, taille, lissage=1.6):
    """Grille -> carte de densité 0-1 à la taille de l'image (lissée, normalisée sur le 99e centile)."""
    w, h = taille
    g = cv2.GaussianBlur(grille.astype(np.float32), (0, 0), lissage)
    haut = float(np.percentile(g[g > 0], 99)) if np.any(g > 0) else 0.0
    if haut <= 0:
        return np.zeros((h, w), np.float32)
    g = np.clip(g / haut, 0, 1)
    return cv2.resize(g, (w, h), interpolation=cv2.INTER_CUBIC).clip(0, 1)


def rendre(fond_img, grille, opacite=0.75, zones=None, taille=(1280, 720)):
    """Image BGR : la carte de chaleur posée sur l'image de fond de la caméra (ou sur un fond neutre)."""
    if fond_img is None:
        w, h = taille
        base = np.full((h, w, 3), (38, 30, 26), np.uint8)
    else:
        base = fond_img.copy()
        h, w = base.shape[:2]
        # fond légèrement assombri et désaturé : la chaleur ressort mieux
        gris = cv2.cvtColor(cv2.cvtColor(base, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
        base = cv2.addWeighted(base, 0.35, gris, 0.65, -25)
    d = densite(grille, (w, h))
    couleur = _LUT[(d * 255).astype(np.uint8)]
    alpha = (np.power(d, 0.65) * opacite)[..., None]
    alpha[d < 0.03] = 0
    sortie = (base.astype(np.float32) * (1 - alpha) + couleur * alpha).clip(0, 255).astype(np.uint8)
    for z in zones or []:
        _dessiner_zone(sortie, z)
    return sortie


def _dessiner_zone(img, z):
    h, w = img.shape[:2]
    if z.get("points"):
        pts = np.array([[int(x * w), int(y * h)] for x, y in z["points"]], np.int32)
    else:
        x1, y1, x2, y2 = z["rect"]
        pts = np.array([[x1 * w, y1 * h], [x2 * w, y1 * h], [x2 * w, y2 * h], [x1 * w, y2 * h]], np.int32)
    cv2.polylines(img, [pts], True, (255, 255, 255), 2, cv2.LINE_AA)
    x, y = pts[:, 0].min(), pts[:, 1].min()
    nom = z.get("nom", "")
    try:
        from .sources import sans_accents
        nom = sans_accents(nom)
    except Exception:  # noqa: BLE001
        pass
    (tw, th), _ = cv2.getTextSize(nom, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
    cv2.rectangle(img, (int(x), int(y)), (int(x) + tw + 10, int(y) + th + 10), (255, 255, 255), -1)
    cv2.putText(img, nom, (int(x) + 5, int(y) + th + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (30, 20, 10), 1, cv2.LINE_AA)


def couleurs_legende(n=6):
    """Couleurs RVB de la légende, du moins au plus fréquenté."""
    return [tuple(int(c) for c in _LUT[int(i * 255 / (n - 1))][::-1]) for i in range(n)]


def exporter_csv(chemin, camera, stats):
    import csv
    with open(chemin, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Caméra", camera])
        w.writerow(["Passages", stats["passages"]])
        w.writerow(["Présence moyenne (personnes)", f"{stats['moyenne']:.2f}".replace(".", ",")])
        w.writerow(["Pic (personnes simultanées)", stats["max_personnes"]])
        w.writerow(["Temps observé (heures)", f"{stats['observe'] / 3600:.1f}".replace(".", ",")])
        w.writerow([])
        w.writerow(["Heure", "Présence moyenne (personnes)"])
        for h, v in enumerate(stats["par_heure"]):
            w.writerow([f"{h:02d}h", "" if np.isnan(v) else f"{v:.2f}".replace(".", ",")])
        w.writerow([])
        w.writerow(["Jour", "Passages", "Présence moyenne (personnes)"])
        for j, (p, pres, obs) in sorted(stats["par_jour"].items()):
            w.writerow([j, p, f"{pres / obs:.2f}".replace(".", ",") if obs else ""])
        w.writerow([])
        w.writerow(["Zone", "Part du temps de présence (%)", "Passages"])
        total = sum(v[0] for v in stats["zones"].values()) or 1
        for n, (s, k) in sorted(stats["zones"].items(), key=lambda x: -x[1][0]):
            w.writerow([n, f"{100 * s / total:.1f}".replace(".", ","), k])
