"""Crée les deux archives d'une version de Flux : Flux-<version>-windows.zip et Flux-<version>-linux.zip.

Seuls les fichiers suivis par git sont pris (jamais de données, réglages ou environnement), sans le dossier .github.
Chaque archive ne contient que les scripts de son système (voir flux/plateformes.py).
"""
import hashlib
import importlib.util
import json
import subprocess
import sys
import zipfile

spec = importlib.util.spec_from_file_location("plateformes", "flux/plateformes.py")
plateformes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plateformes)

with open("version.json", encoding="utf-8") as f:
    v = json.load(f)
version, canal = str(v["version"]).strip(), str(v.get("canal", "stable")).strip().lower()
fichiers = [f for f in subprocess.check_output(["git", "ls-files", "-z"]).decode("utf-8").split("\0") if f]
fichiers = [f for f in fichiers if not f.startswith((".github/", ".git")) and f not in (".gitattributes", ".gitignore")]
for p in plateformes.PLATEFORMES:
    nom = plateformes.nom_archive(version, canal, p)
    with zipfile.ZipFile(nom, "w", zipfile.ZIP_DEFLATED) as z:
        n = 0
        for f in fichiers:
            if not plateformes.pour(f, p):
                continue
            info = zipfile.ZipInfo.from_file(f, "Flux/" + f)
            info.compress_type = zipfile.ZIP_DEFLATED
            if f in plateformes.EXECUTABLES:
                info.external_attr = 0o100755 << 16
            with open(f, "rb") as src:
                z.writestr(info, src.read())
            n += 1
    print(f"{nom} : {n} fichiers")
# Empreintes vérifiées par les mises à jour de Flux avant l'installation
with open("SHA256SUMS.txt", "w", encoding="utf-8") as f:
    for p in plateformes.PLATEFORMES:
        nom = plateformes.nom_archive(version, canal, p)
        with open(nom, "rb") as a:
            f.write(f"{hashlib.sha256(a.read()).hexdigest()}  {nom}\n")
print(open("SHA256SUMS.txt", encoding="utf-8").read())
sys.exit(0)
