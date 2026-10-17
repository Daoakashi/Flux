"""Prépare la publication d'une version de Flux sur GitHub (utilisé par le bouton « Publier une version »).

Lit version.json et le premier bloc de CHANGELOG.txt, vérifie que les deux correspondent, puis écrit :
  notes.md              notes de version (texte du CHANGELOG)
  sortie GitHub         tag (v0.9.0-alpha), titre (Beta Version 0.9.0 alpha), pré-version oui/non
Les archives Windows et Linux sont créées ensuite par archives.py.
"""
import json
import os
import re
import sys

with open("version.json", encoding="utf-8") as f:
    v = json.load(f)
version, canal = str(v["version"]).strip(), str(v.get("canal", "stable")).strip().lower()
suffixe = "" if canal in ("", "stable") else f"-{canal}"
tag = f"v{version}{suffixe}"
titre = f"Beta Version {version} {canal}" if canal not in ("", "stable") else f"Version {version}"

with open("CHANGELOG.txt", encoding="utf-8") as f:
    texte = f.read()
blocs = re.split(r"\n(?=\S[^\n]*\d+\.\d+)", texte.strip())
premier = blocs[0].strip() if blocs else ""
entete = premier.splitlines()[0] if premier else ""
if version not in entete:
    sys.exit(f"Le CHANGELOG commence par « {entete} » mais version.json indique {version}. "
             "Ajoutez d'abord les notes de cette version en haut de CHANGELOG.txt.")
notes = "\n".join(premier.splitlines()[1:]).strip() or "Nouvelle version."
with open("notes.md", "w", encoding="utf-8") as f:
    f.write("```\n" + notes + "\n```\n")

sortie = os.environ.get("GITHUB_OUTPUT")
lignes = [f"tag={tag}", f"titre={titre}",
          f"prerelease={'--prerelease' if suffixe else ''}"]
if sortie:
    with open(sortie, "a", encoding="utf-8") as f:
        f.write("\n".join(lignes) + "\n")
print("\n".join(lignes))
