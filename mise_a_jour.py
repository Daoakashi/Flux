"""Mises à jour de Flux depuis GitHub.

Recherche : les « releases » du dépôt (avec leurs notes), ou à défaut le fichier version.json de la branche
principale. Installation : télécharge l'archive, sauvegarde le code actuel dans « sauvegardes », puis remplace
uniquement le code. Réglages, base de données, modèles, détections et environnement Python sont conservés.
"""

import hashlib
import io
import json
import os
import re
import shutil
import time
import urllib.error
import urllib.request
import zipfile

from . import config

API = os.environ.get("FLUX_GITHUB_API", "https://api.github.com")
BRUT = os.environ.get("FLUX_GITHUB_BRUT", "https://raw.githubusercontent.com")

# Jamais remplacés ni sauvegardés : données de l'utilisateur
PROTEGES = {"config.json", "flux.db", "flux.db-wal", "flux.db-shm", "plaques.pt", "flux.ico", "flux.png", "flux_erreur.log"}
# « fluxlite » : clé du serveur FluxLite, comptes des clients. Jamais remplacé : la clé ne change pas.
DOSSIERS_PROTEGES = {"venv", ".venv", "outils", "modeles", "detections", "sauvegardes", "publication", "fluxlite", ".git",
                     "__pycache__"}
RANG_CANAL = {"alpha": 0, "a": 0, "beta": 1, "b": 1, "rc": 2, "stable": 3, "": 3}


class ErreurMaj(Exception):
    pass


def analyser_version(texte):
    """« v0.3.1-beta », « Beta Version 0.3 alpha », « 1.2 » -> ((0,3,1), rang_canal)."""
    t = str(texte or "").lower()
    m = re.search(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", t)
    if not m:
        return (0, 0, 0), 3
    nums = tuple(int(x or 0) for x in m.groups())

    def canal(morceau):
        c = re.search(r"(alpha|beta|rc)", morceau)
        return RANG_CANAL[c.group(1)] if c else None

    # « Beta Version 0.3 alpha » : le mot placé après le numéro l'emporte
    rang = canal(t[m.end():])
    if rang is None:
        rang = canal(t[:m.start()])
    return nums, 3 if rang is None else rang


def cle_version(version, canal=""):
    nums, rang = analyser_version(version)
    if canal and rang == 3:
        rang = RANG_CANAL.get(canal.lower(), 3)
    return nums + (rang,)


def plus_recente(a, b):
    """Vrai si la version a (texte ou (version, canal)) est plus récente que b."""
    ka = cle_version(*a) if isinstance(a, tuple) else cle_version(a)
    kb = cle_version(*b) if isinstance(b, tuple) else cle_version(b)
    return ka > kb


def depot(cfg):
    d = (cfg.get("maj.depot") or "").strip() or config.lire_version().get("depot", "").strip()
    d = re.sub(r"^(https?://)?(www\.)?github\.com/", "", d).strip("/")
    d = d[:-4] if d.endswith(".git") else d
    return d if re.fullmatch(r"[\w.-]+/[\w.-]+", d) else ""


def _get(url, cfg, binaire=False, delai=20, progression=None):
    entetes = {"User-Agent": "Flux-mises-a-jour", "Accept": "application/vnd.github+json"}
    if (cfg.get("maj.jeton") or "").strip():
        entetes["Authorization"] = f"Bearer {cfg.get('maj.jeton').strip()}"
    if binaire:
        entetes["Accept"] = "application/octet-stream"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=entetes), timeout=delai) as r:
            if not binaire:
                return r.read().decode("utf-8")
            total = int(r.headers.get("Content-Length") or 0)
            morceaux, lu = [], 0
            while True:
                bloc = r.read(256 * 1024)
                if not bloc:
                    break
                morceaux.append(bloc)
                lu += len(bloc)
                if progression:
                    progression(lu, total)
            return b"".join(morceaux)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise ErreurMaj("dépôt introuvable (nom incorrect, ou dépôt privé sans jeton)") from None
        if e.code == 403:
            raise ErreurMaj("GitHub limite les requêtes : réessayez dans une heure") from None
        raise ErreurMaj(f"GitHub a répondu {e.code}") from None
    except urllib.error.URLError as e:
        raise ErreurMaj(f"pas de connexion à GitHub ({e.reason})") from None
    except TimeoutError:
        raise ErreurMaj("GitHub ne répond pas") from None


def canal_accepte(cfg, rang):
    choix = cfg.get("maj.canal")
    return choix == "toutes" or (choix == "beta" and rang >= 1) or (choix == "stables" and rang == 3)


def verifier(cfg):
    """Cherche une version plus récente. Renvoie None (à jour) ou un dict décrivant la nouvelle version."""
    d = depot(cfg)
    if not d:
        raise ErreurMaj("aucun dépôt GitHub configuré (Réglages › Mises à jour)")
    actuelle = (config.APP_VERSION, config.APP_CANAL)
    candidates = []
    try:
        releases = json.loads(_get(f"{API}/repos/{d}/releases?per_page=30", cfg))
    except ErreurMaj as e:
        if "introuvable" in str(e):
            raise
        releases = []
    for r in releases if isinstance(releases, list) else []:
        if r.get("draft"):
            continue
        nom = r.get("tag_name") or r.get("name") or ""
        cle = cle_version(nom)
        if r.get("prerelease") and cle[3] == 3:
            cle = cle[:3] + (1,)  # pré-version sans canal dans le nom : traitée comme beta
        if not canal_accepte(cfg, cle[3]):
            continue
        archive = next((a for a in r.get("assets", []) if a.get("name", "").lower().endswith(".zip")), None)
        candidates.append({
            "cle": cle, "version": nom.lstrip("vV"), "titre": r.get("name") or nom, "notes": r.get("body") or "",
            "page": r.get("html_url") or f"https://github.com/{d}/releases",
            "archive": (archive or {}).get("url") if archive else r.get("zipball_url"),
            "archive_nom": (archive or {}).get("name", ""), "date": r.get("published_at") or "",
        })
    if not candidates:  # pas de release : version.json de la branche principale
        try:
            v = json.loads(_get(f"{BRUT}/{d}/HEAD/version.json", cfg))
        except (ErreurMaj, ValueError):
            v = None
        if v and v.get("version"):
            cle = cle_version(v["version"], v.get("canal", ""))
            if canal_accepte(cfg, cle[3]):
                candidates.append({
                    "cle": cle, "version": v["version"], "titre": f"Version {config.libelle_version(v['version'], v.get('canal', ''))}",
                    "notes": v.get("notes", ""), "page": f"https://github.com/{d}",
                    "archive": f"{API}/repos/{d}/zipball", "archive_nom": "", "date": v.get("date", "")})
    if not candidates:
        return None
    meilleure = max(candidates, key=lambda c: c["cle"])
    if meilleure["cle"] <= cle_version(*actuelle):
        return None
    meilleure["libelle"] = config.libelle_version(*_version_et_canal(meilleure["cle"], meilleure["version"]))
    meilleure["depot"] = d
    return meilleure


def _version_et_canal(cle, texte):
    nom_canal = {0: "alpha", 1: "beta", 2: "rc", 3: ""}[cle[3]]
    return ".".join(str(x) for x in cle[:3]), nom_canal


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------
def _racine_archive(z):
    """Dossier de l'archive qui contient flux.py et flux/ (les zips GitHub ont un dossier racine)."""
    noms = z.namelist()
    for n in sorted(noms, key=len):
        if n.endswith("flux.py") and not n.endswith("/flux/flux.py"):
            prefixe = n[:-len("flux.py")]
            if any(x.startswith(prefixe + "flux/") for x in noms):
                return prefixe
    raise ErreurMaj("l'archive ne contient pas Flux (flux.py et le dossier flux/ sont introuvables)")


def _protege(rel):
    parties = rel.replace("\\", "/").split("/")
    return parties[0] in DOSSIERS_PROTEGES or "__pycache__" in parties or (len(parties) == 1 and parties[0] in PROTEGES)


def _empreinte(chemin):
    try:
        with open(chemin, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def sauvegarder_code(racine, nom):
    """Zip du code actuel (sans les données) dans racine/sauvegardes. Renvoie le chemin."""
    dossier = os.path.join(racine, "sauvegardes")
    os.makedirs(dossier, exist_ok=True)
    chemin = os.path.join(dossier, nom)
    with zipfile.ZipFile(chemin, "w", zipfile.ZIP_DEFLATED) as z:
        for d, sous, fichiers in os.walk(racine):
            rel_d = os.path.relpath(d, racine)
            sous[:] = [s for s in sous if not _protege(os.path.normpath(os.path.join(rel_d, s)))]
            for f in fichiers:
                rel = os.path.normpath(os.path.join(rel_d, f))
                if not _protege(rel) and not f.endswith(".log"):
                    z.write(os.path.join(d, f), rel)
    return chemin


def installer(cfg, info, racine=config.RACINE, progression=None):
    """Télécharge et installe la version `info` (résultat de verifier). Renvoie un résumé."""
    def etape(texte, avance):
        if progression:
            progression(texte, avance)

    etape("Téléchargement…", 0.05)
    octets = _get(info["archive"], cfg, binaire=True, delai=60,
                  progression=lambda lu, total: etape(
                      f"Téléchargement… {lu / 1e6:.1f} Mo" + (f" / {total / 1e6:.1f} Mo" if total else ""),
                      0.05 + 0.55 * (lu / total if total else 0.3)))
    try:
        z = zipfile.ZipFile(io.BytesIO(octets))
    except zipfile.BadZipFile:
        raise ErreurMaj("l'archive téléchargée est illisible") from None
    prefixe = _racine_archive(z)
    a_copier = []
    for n in z.namelist():
        if not n.startswith(prefixe) or n.endswith("/"):
            continue
        rel = os.path.normpath(n[len(prefixe):])
        if rel.startswith("..") or os.path.isabs(rel) or ":" in rel:
            raise ErreurMaj(f"chemin dangereux dans l'archive : {n}")
        if not _protege(rel):
            a_copier.append((n, rel))

    etape("Sauvegarde de la version actuelle…", 0.65)
    req_avant = _empreinte(os.path.join(racine, "requirements.txt"))
    sauvegarde = sauvegarder_code(racine, f"avant_{config.APP_VERSION}_{time.strftime('%Y%m%d_%H%M%S')}.zip")

    etape("Installation des fichiers…", 0.75)
    for i, (n, rel) in enumerate(a_copier):
        dest = os.path.join(racine, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        tmp = dest + ".maj"
        with z.open(n) as src, open(tmp, "wb") as f:
            shutil.copyfileobj(src, f)
        os.replace(tmp, dest)
        if rel.endswith(".sh"):  # Linux : les scripts doivent rester exécutables
            try:
                os.chmod(dest, 0o755)
            except OSError:
                pass
        etape("Installation des fichiers…", 0.75 + 0.2 * (i + 1) / max(1, len(a_copier)))
    req_change = _empreinte(os.path.join(racine, "requirements.txt")) != req_avant
    etape("Terminé", 1.0)
    return {"fichiers": len(a_copier), "sauvegarde": sauvegarde, "dependances": req_change,
            "version": info.get("libelle") or info.get("version")}


def preparer_publication(racine=config.RACINE):
    """Crée publication/Flux-<version>.zip prêt à joindre à une release GitHub (sans données ni environnement)."""
    v = config.lire_version()
    dossier = os.path.join(racine, "publication")
    os.makedirs(dossier, exist_ok=True)
    chemin = os.path.join(dossier, f"Flux-{v['version']}{'-' + v['canal'] if v['canal'] != 'stable' else ''}.zip")
    with zipfile.ZipFile(chemin, "w", zipfile.ZIP_DEFLATED) as z:
        for d, sous, fichiers in os.walk(racine):
            rel_d = os.path.relpath(d, racine)
            sous[:] = [s for s in sous if not _protege(os.path.normpath(os.path.join(rel_d, s)))]
            for f in fichiers:
                rel = os.path.normpath(os.path.join(rel_d, f))
                if not _protege(rel) and not f.endswith((".log", ".pyc", ".tmp")):
                    z.write(os.path.join(d, f), os.path.join("Flux", rel))
    return chemin
