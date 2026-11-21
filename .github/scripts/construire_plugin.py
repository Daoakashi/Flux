"""Fabrique un plugin signé (.fluxplug) : python3 construire_plugin.py <dossier du plugin> [dossier de sortie]

La clé de signature vient de la variable d'environnement FLUX_MAJ_CLE (clé privée PEM de DMS Security, la même que
pour les mises à jour). Utilisé par le dépôt privé des plugins (GitHub Actions).
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from flux import plugins  # noqa: E402

if len(sys.argv) < 2:
    sys.exit(__doc__)
cle = os.environ.get("FLUX_MAJ_CLE", "").strip().replace("\\n", "\n")
if not cle:
    sys.exit("FLUX_MAJ_CLE absent : impossible de signer le plugin.")
sortie = sys.argv[2] if len(sys.argv) > 2 else "."
os.makedirs(sortie, exist_ok=True)
import json  # noqa: E402
info = json.load(open(os.path.join(sys.argv[1], "plugin.json"), encoding="utf-8"))
chemin = plugins.construire(sys.argv[1], cle, os.path.join(sortie, f"{info['id']}-{info['version']}.fluxplug"))
print(f"Plugin signé : {chemin} ({os.path.getsize(chemin) / 1024:.1f} Ko)")
