"""Limite d'espace disque : quand les photos, vidéos et bases de Flux dépassent la limite choisie (ou que le disque
se remplit), les plus anciens enregistrements sont supprimés en premier. Les plus récents sont toujours gardés.

Concerné : photos d'alerte et captures, vidéos des passages et enregistrements (dossier des détections), actions
de la base (avec leur photo), alertes envoyées aux téléphones (avec leur photo), et le fichier journal.log.
Jamais concerné : les personnes enregistrées et leurs visages, les comptes, les réglages, les exports CSV.
"""
import os
import shutil
import time

GO = 1_000_000_000
AGE_MIN = 10 * 60          # un fichier de moins de 10 minutes n'est jamais supprimé (envoi en cours)
JOURNAL_MAX = 50_000_000   # journal.log : au-delà de 50 Mo, on garde les 10 derniers Mo
JOURNAL_GARDE = 10_000_000
PREFIXES = ("alerte_", "capture_", "enreg_", "video_")
EXTENSIONS = (".jpg", ".jpeg", ".png", ".mp4", ".avi", ".mkv", ".webm")


def medias(dossier):
    """[(chemin, taille, date)] des photos et vidéos de Flux, du plus ancien au plus récent."""
    l = []
    for sous in ("", "videos"):
        d = os.path.join(dossier, sous)
        try:
            noms = os.listdir(d)
        except OSError:
            continue
        for n in noms:
            if not n.startswith(PREFIXES) or not n.lower().endswith(EXTENSIONS):
                continue
            c = os.path.join(d, n)
            try:
                s = os.stat(c)
            except OSError:
                continue
            if os.path.isfile(c):
                l.append((c, s.st_size, s.st_mtime))
    l.sort(key=lambda x: x[2])
    return l


def taille_fichiers(*chemins):
    t = 0
    for c in chemins:
        for x in (c, c + "-wal", c + "-shm"):
            try:
                t += os.path.getsize(x)
            except OSError:
                pass
    return t


def etat(dossier, bases=()):
    """Espace utilisé par Flux et espace libre du disque (pour l'affichage)."""
    m = medias(dossier)
    videos = sum(t for c, t, _ in m if c.lower().endswith((".mp4", ".avi", ".mkv", ".webm")))
    photos = sum(t for _, t, _ in m) - videos
    journal = taille_fichiers(os.path.join(dossier, "journal.log"))
    b = taille_fichiers(*bases)
    try:
        libre = shutil.disk_usage(dossier if os.path.isdir(dossier) else os.path.dirname(dossier) or ".").free
    except OSError:
        libre = None
    return {"videos": videos, "photos": photos, "journal": journal, "bases": b, "total": videos + photos + journal + b,
            "fichiers": len(m), "plus_ancien": m[0][2] if m else None, "libre": libre}


def _raccourcir_journal(chemin):
    try:
        if os.path.getsize(chemin) <= JOURNAL_MAX:
            return 0
        avant = os.path.getsize(chemin)
        with open(chemin, "rb") as f:
            f.seek(-JOURNAL_GARDE, os.SEEK_END)
            reste = f.read()
        reste = reste[reste.find(b"\n") + 1:]
        tmp = chemin + ".tmp"
        with open(tmp, "wb") as f:
            f.write(reste)
        os.replace(tmp, chemin)
        return avant - len(reste)
    except OSError:
        return 0


def menage(dossier, limite_go=0.0, libre_min_go=0.0, base=None, comptes=None, chemins_bases=(), maintenant=None):
    """Supprime les plus anciens enregistrements jusqu'à repasser sous la limite. Renvoie un résumé (dict).

    base : objet avec purger_avant(ts) et supprimer_plus_anciennes(n) (base des actions de Flux).
    comptes : objet avec purger_journal_avant(ts) (alertes envoyées à FluxLite)."""
    maintenant = maintenant or time.time()
    res = {"photos": 0, "videos": 0, "octets": 0, "actions": 0, "avant": None, "depassement": 0}
    res["octets"] += _raccourcir_journal(os.path.join(dossier, "journal.log"))
    e = etat(dossier, chemins_bases)
    trop = 0
    if limite_go and limite_go > 0:
        trop = max(trop, e["total"] - int(limite_go * GO))
    if libre_min_go and libre_min_go > 0 and e["libre"] is not None:
        trop = max(trop, int(libre_min_go * GO) - e["libre"])
    res["depassement"] = max(0, trop)
    if trop <= 0:
        return res
    objectif = int(trop * 1.05) + 1  # 5 % de marge : pas de ménage à chaque nouvelle vidéo
    libere, coupe = 0, None
    for c, t, date in medias(dossier):
        if libere >= objectif:
            break
        if maintenant - date < AGE_MIN:
            break  # tout ce qui suit est plus récent
        try:
            os.remove(c)
        except OSError:
            continue
        libere += t
        coupe = date
        if c.lower().endswith((".jpg", ".jpeg", ".png")):
            res["photos"] += 1
        else:
            res["videos"] += 1
    # Les entrées des bases plus anciennes que le dernier fichier supprimé partent aussi : elles montraient
    # ces photos et vidéos.
    if coupe is not None:
        res["avant"] = coupe
        if base is not None:
            try:
                res["actions"] += base.purger_avant(coupe) or 0
            except Exception:  # noqa: BLE001
                pass
        if comptes is not None:
            try:
                comptes.purger_journal_avant(coupe)
            except Exception:  # noqa: BLE001
                pass
    # Plus aucun fichier à supprimer et toujours trop plein : les actions les plus anciennes (avec leur photo).
    if libere < objectif and base is not None:
        try:
            avant = taille_fichiers(*chemins_bases)
            n = base.supprimer_plus_anciennes(fraction=0.2)
            res["actions"] += n or 0
            libere += max(0, avant - taille_fichiers(*chemins_bases))
        except Exception:  # noqa: BLE001
            pass
    res["octets"] += libere
    return res


def texte_taille(o):
    if o is None:
        return "?"
    if o >= GO:
        return f"{o / GO:.1f} Go".replace(".", ",")
    if o >= 1_000_000:
        return f"{o / 1_000_000:.0f} Mo"
    return f"{max(1, round(o / 1000))} Ko" if o else "0 Mo"


def texte_resume(r):
    morceaux = []
    if r["videos"]:
        morceaux.append(f"{r['videos']} vidéo(s)")
    if r["photos"]:
        morceaux.append(f"{r['photos']} photo(s)")
    if r["actions"]:
        morceaux.append(f"{r['actions']} action(s) du journal")
    if not morceaux and not r["octets"]:
        return ""
    quand = ""
    if r.get("avant"):
        quand = " antérieures au " + time.strftime("%d/%m/%Y %H:%M", time.localtime(r["avant"]))
    return (f"Espace disque : {texte_taille(r['octets'])} libérés"
            + (f" ({', '.join(morceaux)}{quand})" if morceaux else "") + ". Les plus récents sont gardés.")
