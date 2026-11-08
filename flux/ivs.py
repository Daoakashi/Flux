"""IVS (analyse vidéo intelligente) : flèches de franchissement.

Une flèche va d'un point A à un point B (coordonnées 0-1 de l'image). Une personne dont le cadre touche le
couloir de la flèche et qui la suit dans ce sens (du côté de A jusqu'au bout B) déclenche un « franchissement » :
inscrit au journal, et, si l'alarme de la flèche est cochée, une alerte avec un son sur le PC.
Le sens inverse (B vers A) ne déclenche rien : c'est le passage non désiré qu'on surveille
(ex. A « Rayon » → B « Sortie de secours »).
"""
import math

MAX_FLECHES = 12
LARGEUR_DEFAUT = 0.12   # demi-largeur du couloir, en part de la largeur de l'image
DEBUT, FIN = 0.33, 0.67  # « côté A » : premier tiers de la flèche ; « arrivé à B » : dernier tiers


def _point(v):
    try:
        x, y = float(v[0]), float(v[1])
    except (TypeError, ValueError, IndexError):
        return None
    if math.isnan(x) or math.isnan(y):
        return None
    return (min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0))


def normaliser_fleche(f, i=0):
    """Flèche propre {"nom", "a", "b", "nom_a", "nom_b", "alarme", "largeur"} ou None si invalide."""
    if not isinstance(f, dict):
        return None
    a, b = _point(f.get("a")), _point(f.get("b"))
    if a is None or b is None or math.hypot(b[0] - a[0], b[1] - a[1]) < 0.02:
        return None
    try:
        largeur = float(f.get("largeur", LARGEUR_DEFAUT))
    except (TypeError, ValueError):
        largeur = LARGEUR_DEFAUT
    return {
        "nom": (str(f.get("nom") or "").strip() or f"Flèche {i + 1}")[:60],
        "a": a, "b": b,
        "nom_a": (str(f.get("nom_a") or "").strip() or "A")[:40],
        "nom_b": (str(f.get("nom_b") or "").strip() or "B")[:40],
        "alarme": bool(f.get("alarme", True)),
        "largeur": min(max(largeur, 0.02), 0.5),
    }


def fleches_options(o):
    fl = o.get("fleches") or []
    sortie = []
    for i, f in enumerate(fl[:MAX_FLECHES]):
        n = normaliser_fleche(f, i)
        if n:
            sortie.append(n)
    return sortie


def copie_fleche(f):
    c = dict(f)
    c["a"], c["b"] = tuple(f["a"]), tuple(f["b"])
    return c


def position(f, x, y, w=1.0, h=1.0):
    """Position d'un point (0-1) par rapport à la flèche : t (0 = A, 1 = B) et distance au trait,
    en part de la largeur de l'image (calcul en pixels pour respecter les proportions)."""
    ax, ay = f["a"][0] * w, f["a"][1] * h
    bx, by = f["b"][0] * w, f["b"][1] * h
    px, py = x * w, y * h
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 <= 0:
        return 0.0, float("inf")
    t = ((px - ax) * dx + (py - ay) * dy) / l2
    d = abs((px - ax) * dy - (py - ay) * dx) / math.sqrt(l2)
    return t, d / max(w, 1e-9)


def distance_cadre(f, box, w=1.0, h=1.0):
    """Distance entre le trait de la flèche (droite AB) et le cadre d'une personne, en part de la largeur de
    l'image : 0 si la droite traverse le cadre. On regarde tout le corps, pas seulement les pieds : une flèche
    tracée à hauteur de table ou de porte fonctionne aussi."""
    x1, y1, x2, y2 = box
    ds = []
    for x, y in ((x1, y1), (x2, y1), (x1, y2), (x2, y2)):
        ax, ay = f["a"][0] * w, f["a"][1] * h
        bx, by = f["b"][0] * w, f["b"][1] * h
        dx, dy = bx - ax, by - ay
        lg = math.hypot(dx, dy) or 1e-9
        ds.append(((x * w - ax) * dy - (y * h - ay) * dx) / lg)
    if min(ds) <= 0 <= max(ds):
        return 0.0
    return min(abs(d) for d in ds) / max(w, 1e-9)


class SuiviFleches:
    """État de chaque personne suivie vis-à-vis de chaque flèche (dans le fil d'analyse d'une caméra)."""

    def __init__(self):
        self.etats = {}  # (piste, nom de flèche) -> "A" (vue près de A) ou "fait" (franchissement signalé)

    def mettre_a_jour(self, piste_id, box, fleches, w, h):
        """box : cadre de la personne (x1, y1, x2, y2 en 0-1). Renvoie les flèches franchies à cet instant."""
        franchies = []
        x, y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        for f in fleches:
            cle = (piste_id, f["nom"])
            etat = self.etats.get(cle)
            if etat == "fait":
                continue
            t, _ = position(f, x, y, w, h)  # avancement le long de la flèche : centre du cadre
            if distance_cadre(f, box, w, h) > f["largeur"]:
                continue  # hors du couloir : rien ne change (l'analyse peut sauter quelques images)
            if t <= DEBUT:
                self.etats[cle] = "A"
            elif t >= FIN and etat == "A":
                self.etats[cle] = "fait"
                franchies.append(f)
        return franchies

    def oublier(self, pistes_actives):
        actives = set(pistes_actives)
        self.etats = {k: v for k, v in self.etats.items() if k[0] in actives}
