"""Publication sur le serveur Flux (Cloudflare) : utilisé par le bouton « Publier une version ».

    python3 .github/scripts/publier_nuage.py preparer   AVANT archives.py : écrit dans le code livré l'adresse du
                                                         serveur (version.json « nuage ») et la clé publique qui vérifie
                                                         les manifestes (flux/confiance_maj.json)
    python3 .github/scripts/publier_nuage.py envoyer    APRÈS archives.py : dépose les archives sur le serveur, puis le
                                                         nouveau manifeste des versions, SIGNÉ ici

Secrets et variables du dépôt (Settings › Secrets and variables › Actions) :
    FLUX_MAJ_CLE        secret   clé privée ECDSA P-256 (PEM) qui signe les manifestes ; ne quitte jamais GitHub
    PUBLICATION_TOKEN   secret   même valeur que le secret PUBLICATION_TOKEN du serveur Flux
    FLUX_NUAGE_URL      variable adresse du serveur Flux, ex. https://flux-central.monnom.workers.dev

Sans ces réglages, rien n'est fait (la version est publiée sur GitHub seulement, comme avant).
"""
import base64
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

VERSIONS_GARDEES = 15


def configure():
    manque = [n for n in ("FLUX_MAJ_CLE", "PUBLICATION_TOKEN", "FLUX_NUAGE_URL") if not os.environ.get(n, "").strip()]
    if manque:
        print(f"Serveur Flux non configuré ({', '.join(manque)} absent) : publication sur GitHub seulement.")
        return False
    return True


def cle_privee():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    texte = os.environ["FLUX_MAJ_CLE"].strip().replace("\\n", "\n")
    k = serialization.load_pem_private_key(texte.encode(), password=None)
    if not isinstance(k, ec.EllipticCurvePrivateKey) or k.curve.name != "secp256r1":
        sys.exit("FLUX_MAJ_CLE doit être une clé privée ECDSA P-256 (créée par outils/cles_serveur_flux.py).")
    return k


def spki_b64(k):
    from cryptography.hazmat.primitives import serialization
    return base64.b64encode(k.public_key().public_bytes(serialization.Encoding.DER,
                                                        serialization.PublicFormat.SubjectPublicKeyInfo)).decode()


def adresse():
    a = os.environ["FLUX_NUAGE_URL"].strip().rstrip("/")
    if not re.fullmatch(r"https://[A-Za-z0-9.\-]+(:\d+)?|http://(localhost|127\.0\.0\.1)(:\d+)?", a):
        sys.exit(f"FLUX_NUAGE_URL invalide : « {a} » (attendu : https://nom.exemple, sans chemin).")
    return a


def preparer():
    if not configure():
        return
    k = cle_privee()
    with open("flux/confiance_maj.json", "w", encoding="utf-8") as f:
        json.dump({"cles": [spki_b64(k)], "note": "Clé publique des mises à jour (écrite par la publication)."}, f,
                  indent=2)
        f.write("\n")
    with open("version.json", encoding="utf-8") as f:
        v = json.load(f)
    v["nuage"] = adresse()
    with open("version.json", "w", encoding="utf-8") as f:
        json.dump(v, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Adresse du serveur et clé de vérification ajoutées au code livré ({adresse()}).")


def requete(methode, chemin, corps=None, type_="application/octet-stream"):
    r = urllib.request.Request(adresse() + chemin, data=corps, method=methode, headers={
        "Authorization": f"Bearer {os.environ['PUBLICATION_TOKEN'].strip()}", "Content-Type": type_,
        "User-Agent": "Flux-publication"})
    try:
        with urllib.request.urlopen(r, timeout=120) as rep:
            return rep.read()
    except urllib.error.HTTPError as e:
        if methode == "GET" and e.code == 404:
            return None
        detail = e.read(500).decode("utf-8", "replace")
        sys.exit(f"Le serveur Flux a refusé {methode} {chemin} : HTTP {e.code} {detail}")
    except urllib.error.URLError as e:
        sys.exit(f"Serveur Flux injoignable ({adresse()}) : {e.reason}")


def envoyer():
    if not configure():
        return
    spec = importlib.util.spec_from_file_location("plateformes", "flux/plateformes.py")
    plateformes = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(plateformes)
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec

    k = cle_privee()
    with open("version.json", encoding="utf-8") as f:
        v = json.load(f)
    version, canal = str(v["version"]).strip(), str(v.get("canal", "stable")).strip().lower()
    fichiers = {}
    for p in plateformes.PLATEFORMES:
        nom = plateformes.nom_archive(version, canal, p)
        with open(nom, "rb") as f:
            octets = f.read()
        requete("PUT", f"/api/maj/fichiers/{nom}", octets)
        fichiers[p] = {"nom": nom, "sha256": hashlib.sha256(octets).hexdigest(), "taille": len(octets)}
        print(f"Déposé : {nom} ({len(octets) / 1e6:.2f} Mo)")
    with open("SHA256SUMS.txt", "rb") as f:
        requete("PUT", f"/api/maj/fichiers/SHA256SUMS-{version}{'' if canal in ('', 'stable') else '-' + canal}.txt",
                f.read())

    # Manifeste actuel : gardé seulement s'il porte bien notre signature
    versions = []
    brut = requete("GET", "/api/maj/manifeste")
    if brut:
        try:
            env = json.loads(brut)
            k.public_key().verify(base64.b64decode(env["signature"]), env["manifeste"].encode(),
                                  ec.ECDSA(hashes.SHA256()))
            versions = json.loads(env["manifeste"]).get("versions", [])
        except (ValueError, KeyError, InvalidSignature):
            print("Manifeste actuel illisible ou signé par une autre clé : il est remplacé.")
    notes = ""
    if os.path.isfile("notes.md"):
        notes = open("notes.md", encoding="utf-8").read().strip().strip("`").strip()
    depot = os.environ.get("GITHUB_REPOSITORY", "")
    tag = os.environ.get("FLUX_TAG", "")
    entree = {
        "version": version, "canal": canal, "titre": os.environ.get("FLUX_TITRE", "") or f"Version {version} {canal}",
        "notes": notes, "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "fichiers": fichiers,
        "page": f"https://github.com/{depot}/releases/tag/{tag}" if depot and tag else "",
    }
    versions = [x for x in versions if not (x.get("version") == version and x.get("canal") == canal)] + [entree]
    versions = versions[-VERSIONS_GARDEES:]
    manifeste = json.dumps({"format": 1, "emis": int(time.time()), "nuage": adresse(), "versions": versions},
                           ensure_ascii=False, separators=(",", ":"))
    signature = base64.b64encode(k.sign(manifeste.encode(), ec.ECDSA(hashes.SHA256()))).decode()
    requete("PUT", "/api/maj/manifeste", json.dumps({"manifeste": manifeste, "signature": signature}).encode(),
            "application/json")
    print(f"Manifeste signé publié : {len(versions)} version(s), la plus récente {version} {canal}.")


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "preparer":
        preparer()
    elif action == "envoyer":
        envoyer()
    else:
        sys.exit("usage : publier_nuage.py preparer|envoyer")
