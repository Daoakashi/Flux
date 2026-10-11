"""Base de données de Flux (SQLite) : personnes, empreintes de visage, actions.

Un seul fichier « flux.db » à côté de l'application. Utilisable depuis plusieurs fils :
toutes les écritures passent par un verrou, et le mode WAL permet de lire pendant qu'on écrit.
"""

import csv
import json
import sqlite3
import threading
import time

import cv2
import numpy as np

CATEGORIES_PERSONNE = [("connu", "Connue"), ("inconnu", "Inconnue"), ("surveille", "Surveillée"),
                       ("liste_noire", "Liste noire")]
TYPES_ACTION = {
    "apparition": "Apparition", "identification": "Identification", "zone": "Zone",
    "stationnement": "Stationnement", "depart": "Départ", "alerte": "Alerte", "liste_noire": "Liste noire",
    "plaque": "Plaque", "video": "Vidéo",
}

# Catégories du journal livrées avec Flux. Une action appartient à une catégorie quand elle respecte
# tous les critères renseignés (type d'action, catégorie de la personne, caméra, mots dans le détail).
CATEGORIES_JOURNAL_DEFAUT = [
    {"nom": "Liste noire", "couleur": "#E0245E", "notifier": False,
     "regles": {"types": ["liste_noire"], "personnes": ["liste_noire"], "cameras": [], "mots": [], "mode": "ou"}},
    {"nom": "Alertes", "couleur": "#F2554A", "notifier": False,
     "regles": {"types": ["alerte"], "personnes": [], "cameras": [], "mots": []}},
    {"nom": "Personnes surveillées", "couleur": "#F5A524", "notifier": False,
     "regles": {"types": [], "personnes": ["surveille"], "cameras": [], "mots": []}},
    {"nom": "Identifications", "couleur": "#2F7BFF", "notifier": False,
     "regles": {"types": ["identification"], "personnes": [], "cameras": [], "mots": []}},
    {"nom": "Passages", "couleur": "#22D3EE", "notifier": False,
     "regles": {"types": ["apparition", "depart"], "personnes": [], "cameras": [], "mots": []}},
    {"nom": "Zone et stationnement", "couleur": "#8B5CF6", "notifier": False,
     "regles": {"types": ["zone", "stationnement"], "personnes": [], "cameras": [], "mots": []}},
    {"nom": "Véhicules et plaques", "couleur": "#FBBF24", "notifier": False,
     "regles": {"types": ["plaque"], "personnes": [], "cameras": [], "mots": []}},
    {"nom": "Vidéos", "couleur": "#EC4899", "notifier": False,
     "regles": {"types": ["video"], "personnes": [], "cameras": [], "mots": []}},
]
NOUVELLES_CATEGORIES = {1: ["Vidéos"]}  # ajoutées automatiquement aux bases existantes


def regles_vides():
    return {"types": [], "personnes": [], "cameras": [], "mots": [], "mode": "et"}


def correspond(action, regles):
    """Vrai si l'action (dict avec type, camera, detail, categorie_personne) respecte les règles :
    tous les critères renseignés (mode « et ») ou au moins un (mode « ou »)."""
    tests = []
    if regles and regles.get("types"):
        tests.append(action.get("type") in regles["types"])
    if regles and regles.get("personnes"):
        tests.append(action.get("categorie_personne") in regles["personnes"])
    if regles and regles.get("cameras"):
        tests.append((action.get("camera") or "").lower() in [c.lower() for c in regles["cameras"]])
    if regles and regles.get("mots"):
        texte = f"{action.get('detail') or ''} {action.get('personne') or ''}".lower()
        tests.append(any(m.lower() in texte for m in regles["mots"]))
    if not tests:
        return False  # catégorie sans règle : remplie seulement par classement manuel
    return any(tests) if regles.get("mode") == "ou" else all(tests)

SCHEMA = """
CREATE TABLE IF NOT EXISTS personnes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nom TEXT NOT NULL,
    categorie TEXT NOT NULL DEFAULT 'connu',
    notes TEXT NOT NULL DEFAULT '',
    cree REAL NOT NULL,
    vu_dernier REAL,
    passages INTEGER NOT NULL DEFAULT 0,
    miniature BLOB
);
CREATE TABLE IF NOT EXISTS visages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    personne_id INTEGER NOT NULL REFERENCES personnes(id) ON DELETE CASCADE,
    empreinte BLOB NOT NULL,
    miniature BLOB,
    source TEXT NOT NULL DEFAULT '',
    cree REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    camera TEXT NOT NULL,
    personne_id INTEGER REFERENCES personnes(id) ON DELETE SET NULL,
    piste INTEGER,
    type TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    miniature BLOB
);
CREATE TABLE IF NOT EXISTS categories_journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nom TEXT NOT NULL,
    couleur TEXT NOT NULL DEFAULT '#2F7BFF',
    regles TEXT NOT NULL DEFAULT '{}',
    notifier INTEGER NOT NULL DEFAULT 0,
    ordre INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS i_actions_ts ON actions(ts);
CREATE INDEX IF NOT EXISTS i_actions_personne ON actions(personne_id);
CREATE INDEX IF NOT EXISTS i_visages_personne ON visages(personne_id);
"""


def jpeg(image, cote=160, qualite=82):
    """Encode une petite miniature JPEG (côté max `cote`)."""
    if image is None or not getattr(image, "size", 0):
        return None
    h, w = image.shape[:2]
    f = min(1.0, cote / max(h, w))
    if f < 1:
        image = cv2.resize(image, (max(1, int(w * f)), max(1, int(h * f))), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, qualite])
    return buf.tobytes() if ok else None


def depuis_jpeg(octets):
    if not octets:
        return None
    return cv2.imdecode(np.frombuffer(octets, np.uint8), cv2.IMREAD_COLOR)


class Base:
    def __init__(self, chemin):
        self.chemin = chemin
        self._lock = threading.RLock()
        self._c = sqlite3.connect(chemin, check_same_thread=False, timeout=30)
        self._c.row_factory = sqlite3.Row
        self._c.execute("PRAGMA journal_mode=WAL")
        self._c.execute("PRAGMA foreign_keys=ON")
        self._c.executescript(SCHEMA)
        self._migrer()
        self._c.commit()
        self.version = 0  # incrémentée à chaque changement des personnes ou des visages
        self._abonnes = []
        self.fusions = {}  # ancienne fiche -> fiche qui l'a absorbée (pour les caméras qui la suivent encore)

    def _migrer(self):
        colonnes = {r[1] for r in self._c.execute("PRAGMA table_info(actions)")}
        if "categorie_id" not in colonnes:  # classement manuel d'une action (version 0.3)
            self._c.execute("ALTER TABLE actions ADD COLUMN categorie_id INTEGER "
                            "REFERENCES categories_journal(id) ON DELETE SET NULL")
        version = self._c.execute("PRAGMA user_version").fetchone()[0]
        if not self._c.execute("SELECT COUNT(*) FROM categories_journal").fetchone()[0]:
            self._inserer_categories_defaut()
        else:
            for v, noms in NOUVELLES_CATEGORIES.items():
                if version < v:
                    self._inserer_categories_defaut(seulement=noms)
        self._c.execute(f"PRAGMA user_version = {max(NOUVELLES_CATEGORIES)}")

    def _inserer_categories_defaut(self, seulement=None):
        debut = (self._c.execute("SELECT COALESCE(MAX(ordre), -1) FROM categories_journal").fetchone()[0] or 0) + 1
        noms = {r[0] for r in self._c.execute("SELECT nom FROM categories_journal")}
        n = 0
        for i, c in enumerate(CATEGORIES_JOURNAL_DEFAUT):
            if c["nom"] in noms or (seulement is not None and c["nom"] not in seulement):
                continue
            self._c.execute("INSERT INTO categories_journal(nom, couleur, regles, notifier, ordre) VALUES (?,?,?,?,?)",
                            (c["nom"], c["couleur"], json.dumps(c["regles"]), int(c["notifier"]), debut + i))
            n += 1
        return n

    def abonner(self, fonction):
        """fonction() est appelée (depuis n'importe quel fil) quand les personnes changent."""
        self._abonnes.append(fonction)

    def _change(self):
        self.version += 1
        for f in list(self._abonnes):
            try:
                f()
            except Exception:  # noqa: BLE001
                pass

    def _ecrire(self, sql, params=()):
        with self._lock:
            cur = self._c.execute(sql, params)
            self._c.commit()
            return cur

    def _lire(self, sql, params=()):
        with self._lock:
            return self._c.execute(sql, params).fetchall()

    def fermer(self):
        with self._lock:
            self._c.close()

    # --- personnes ---------------------------------------------------------------
    def creer_personne(self, nom, categorie="connu", miniature=None):
        cur = self._ecrire("INSERT INTO personnes(nom, categorie, cree, miniature) VALUES (?,?,?,?)",
                           (nom, categorie, time.time(), jpeg(miniature)))
        self._change()
        return cur.lastrowid

    def creer_inconnu(self, empreinte, miniature):
        with self._lock:
            n = self._c.execute("SELECT COUNT(*) FROM personnes WHERE nom LIKE 'Inconnu %'").fetchone()[0] + 1
            noms = {r[0] for r in self._c.execute("SELECT nom FROM personnes")}
            while f"Inconnu {n}" in noms:
                n += 1
            nom = f"Inconnu {n}"
            pid = self._c.execute("INSERT INTO personnes(nom, categorie, cree, vu_dernier, passages, miniature) "
                                  "VALUES (?,?,?,?,1,?)",
                                  (nom, "inconnu", time.time(), time.time(), jpeg(miniature))).lastrowid
            self._c.execute("INSERT INTO visages(personne_id, empreinte, miniature, source, cree) VALUES (?,?,?,?,?)",
                            (pid, self._normaliser(empreinte).tobytes(), jpeg(miniature, 112), "auto", time.time()))
            self._c.commit()
        self._change()
        return pid, nom

    def modifier_personne(self, pid, nom=None, categorie=None, notes=None):
        champs, params = [], []
        for col, val in (("nom", nom), ("categorie", categorie), ("notes", notes)):
            if val is not None:
                champs.append(f"{col}=?")
                params.append(val)
        if champs:
            self._ecrire(f"UPDATE personnes SET {', '.join(champs)} WHERE id=?", (*params, pid))
            self._change()

    def supprimer_personne(self, pid):
        self._ecrire("DELETE FROM personnes WHERE id=?", (pid,))
        self._change()

    def resoudre(self, pid):
        """Identifiant valide d'une personne : suit les fusions ; None si la fiche a été supprimée."""
        vus = set()
        while pid in self.fusions and pid not in vus:
            vus.add(pid)
            pid = self.fusions[pid]
        if pid is None:
            return None
        with self._lock:
            return pid if self._c.execute("SELECT 1 FROM personnes WHERE id=?", (pid,)).fetchone() else None

    def fusionner(self, source, cible):
        """Rattache visages et actions de `source` à `cible`, puis supprime `source`."""
        if source == cible:
            return
        self.fusions[source] = cible
        with self._lock:
            self._c.execute("UPDATE visages SET personne_id=? WHERE personne_id=?", (cible, source))
            self._c.execute("UPDATE actions SET personne_id=? WHERE personne_id=?", (cible, source))
            p = self._c.execute("SELECT passages, vu_dernier FROM personnes WHERE id=?", (source,)).fetchone()
            if p:
                self._c.execute("UPDATE personnes SET passages = passages + ?, vu_dernier = MAX(COALESCE(vu_dernier,0), ?)"
                                " WHERE id=?", (p["passages"], p["vu_dernier"] or 0, cible))
            self._c.execute("DELETE FROM personnes WHERE id=?", (source,))
            self._c.commit()
        self._change()

    def vue(self, pid):
        pid = self.resoudre(pid)
        if pid is None:
            return
        self._ecrire("UPDATE personnes SET vu_dernier=?, passages=passages+1 WHERE id=?", (time.time(), pid))

    def personne(self, pid):
        r = self._lire("SELECT * FROM personnes WHERE id=?", (pid,))
        return dict(r[0]) if r else None

    def personnes(self, filtre="", categorie=None):
        sql = ("SELECT p.*, (SELECT COUNT(*) FROM visages v WHERE v.personne_id=p.id) AS nb_visages, "
               "(SELECT COUNT(*) FROM actions a WHERE a.personne_id=p.id) AS nb_actions FROM personnes p WHERE 1=1")
        params = []
        if filtre:
            sql += " AND (p.nom LIKE ? OR p.notes LIKE ?)"
            params += [f"%{filtre}%", f"%{filtre}%"]
        if categorie:
            sql += " AND p.categorie=?"
            params.append(categorie)
        sql += " ORDER BY COALESCE(p.vu_dernier, p.cree) DESC"
        return [dict(r) for r in self._lire(sql, params)]

    # --- visages ----------------------------------------------------------------
    @staticmethod
    def _normaliser(e):
        e = np.asarray(e, dtype=np.float32).reshape(-1)
        return e / (np.linalg.norm(e) + 1e-9)

    def ajouter_visage(self, pid, empreinte, miniature=None, maximum=50, source="manuel"):
        pid = self.resoudre(pid)
        if pid is None:  # fiche supprimée entre-temps
            return None
        with self._lock:
            n = self._c.execute("SELECT COUNT(*) FROM visages WHERE personne_id=?", (pid,)).fetchone()[0]
            if n >= maximum:
                return None
            vid = self._c.execute("INSERT INTO visages(personne_id, empreinte, miniature, source, cree) "
                                  "VALUES (?,?,?,?,?)",
                                  (pid, self._normaliser(empreinte).tobytes(), jpeg(miniature, 112), source,
                                   time.time())).lastrowid
            if miniature is not None:
                self._c.execute("UPDATE personnes SET miniature=COALESCE(miniature, ?) WHERE id=?",
                                (jpeg(miniature), pid))
            self._c.commit()
        self._change()
        return vid

    def visages(self, pid):
        return [dict(r) for r in self._lire("SELECT id, miniature, source, cree FROM visages WHERE personne_id=? "
                                            "ORDER BY cree DESC", (pid,))]

    def supprimer_visage(self, vid):
        self._ecrire("DELETE FROM visages WHERE id=?", (vid,))
        self._change()

    def matrice_empreintes(self):
        """(matrice N×128 normalisée, liste des personne_id, {id: (nom, categorie)}) pour la reconnaissance."""
        lignes = self._lire("SELECT v.personne_id, v.empreinte FROM visages v")
        infos = {r["id"]: (r["nom"], r["categorie"]) for r in self._lire("SELECT id, nom, categorie FROM personnes")}
        if not lignes:
            return None, [], infos
        m = np.stack([np.frombuffer(r["empreinte"], dtype=np.float32) for r in lignes])
        return m, [r["personne_id"] for r in lignes], infos

    # --- actions -----------------------------------------------------------------
    def ajouter_action(self, camera, type_, detail="", personne_id=None, piste=None, miniature=None, ts=None):
        if personne_id is not None:
            personne_id = self.resoudre(personne_id)  # fiche fusionnée ou supprimée pendant le suivi
        cur = self._ecrire("INSERT INTO actions(ts, camera, personne_id, piste, type, detail, miniature) "
                           "VALUES (?,?,?,?,?,?,?)",
                           (ts or time.time(), camera, personne_id, piste, type_, detail, jpeg(miniature, 200)))
        return cur.lastrowid

    def actions(self, personne_id=None, camera=None, type_=None, texte="", depuis=None, limite=500):
        sql = ("SELECT a.id, a.ts, a.camera, a.personne_id, a.piste, a.type, a.detail, a.categorie_id, "
               "(a.miniature IS NOT NULL) AS a_photo, p.nom AS personne, p.categorie AS categorie_personne "
               "FROM actions a "
               "LEFT JOIN personnes p ON p.id = a.personne_id WHERE 1=1")
        params = []
        if personne_id is not None:
            sql += " AND a.personne_id=?"
            params.append(personne_id)
        if camera:
            sql += " AND a.camera=?"
            params.append(camera)
        if type_:
            sql += " AND a.type=?"
            params.append(type_)
        if texte:
            sql += " AND (a.detail LIKE ? OR p.nom LIKE ? OR a.camera LIKE ?)"
            params += [f"%{texte}%"] * 3
        if depuis:
            sql += " AND a.ts>=?"
            params.append(depuis)
        sql += " ORDER BY a.ts DESC LIMIT ?"
        params.append(limite)
        return [dict(r) for r in self._lire(sql, params)]

    def miniature_action(self, aid):
        r = self._lire("SELECT miniature FROM actions WHERE id=?", (aid,))
        return r[0]["miniature"] if r else None

    def cameras(self):
        return [r[0] for r in self._lire("SELECT DISTINCT camera FROM actions ORDER BY camera")]

    def purger(self, jours):
        if jours and jours > 0:
            self._ecrire("DELETE FROM actions WHERE ts < ?", (time.time() - jours * 86400,))

    def exporter_csv(self, chemin, categorie=None, lignes=None, **filtres):
        if lignes is None:
            lignes = self.actions(limite=1_000_000, **filtres)
        cats = self.categories_journal()
        if categorie is not None:
            lignes = [a for a in lignes if categorie in self.classer(a, cats)]
        noms = {c["id"]: c["nom"] for c in cats}
        with open(chemin, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Date", "Caméra", "Personne", "Action", "Catégories", "Détail"])
            for a in lignes:
                w.writerow([time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(a["ts"])), a["camera"],
                            a["personne"] or "", TYPES_ACTION.get(a["type"], a["type"]),
                            ", ".join(noms[i] for i in self.classer(a, cats) if i in noms), a["detail"]])
        return len(lignes)

    # --- catégories du journal ----------------------------------------------------------
    def categories_journal(self):
        res = []
        for r in self._lire("SELECT * FROM categories_journal ORDER BY ordre, id"):
            d = dict(r)
            try:
                d["regles"] = {**regles_vides(), **json.loads(d["regles"] or "{}")}
            except ValueError:
                d["regles"] = regles_vides()
            d["notifier"] = bool(d["notifier"])
            res.append(d)
        return res

    def enregistrer_categorie(self, nom, couleur="#2F7BFF", regles=None, notifier=False, cid=None):
        regles = json.dumps({**regles_vides(), **(regles or {})}, ensure_ascii=False)
        if cid is None:
            with self._lock:
                ordre = self._c.execute("SELECT COALESCE(MAX(ordre), 0) + 1 FROM categories_journal").fetchone()[0]
            return self._ecrire("INSERT INTO categories_journal(nom, couleur, regles, notifier, ordre) "
                                "VALUES (?,?,?,?,?)", (nom, couleur, regles, int(notifier), ordre)).lastrowid
        self._ecrire("UPDATE categories_journal SET nom=?, couleur=?, regles=?, notifier=? WHERE id=?",
                     (nom, couleur, regles, int(notifier), cid))
        return cid

    def supprimer_categorie(self, cid):
        self._ecrire("DELETE FROM categories_journal WHERE id=?", (cid,))

    def deplacer_categorie(self, cid, sens):
        cats = self.categories_journal()
        ids = [c["id"] for c in cats]
        if cid not in ids:
            return
        i = ids.index(cid)
        j = max(0, min(len(ids) - 1, i + sens))
        ids[i], ids[j] = ids[j], ids[i]
        with self._lock:
            for k, x in enumerate(ids):
                self._c.execute("UPDATE categories_journal SET ordre=? WHERE id=?", (k, x))
            self._c.commit()

    def restaurer_categories(self):
        with self._lock:
            n = self._inserer_categories_defaut()
            self._c.commit()
        return n

    def classer_action(self, aid, cid):
        """Classement manuel d'une action (cid=None : retour au classement automatique)."""
        self._ecrire("UPDATE actions SET categorie_id=? WHERE id=?", (cid, aid))

    @staticmethod
    def classer(action, categories):
        """Identifiants des catégories d'une action. Un classement manuel remplace les règles."""
        if action.get("categorie_id"):
            return [action["categorie_id"]]
        return [c["id"] for c in categories if correspond(action, c["regles"])]

    def statistiques(self):
        with self._lock:
            return {
                "personnes": self._c.execute("SELECT COUNT(*) FROM personnes").fetchone()[0],
                "visages": self._c.execute("SELECT COUNT(*) FROM visages").fetchone()[0],
                "actions": self._c.execute("SELECT COUNT(*) FROM actions").fetchone()[0],
                "aujourdhui": self._c.execute("SELECT COUNT(*) FROM actions WHERE ts>=?",
                                              (time.time() - time.time() % 86400,)).fetchone()[0],
            }
