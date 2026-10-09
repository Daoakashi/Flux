"""Outils appelés par installer.bat / installer.sh : vérification de l'installation et création de l'icône.

    python -m flux.outils verifier
    python -m flux.outils icone chemin/flux.ico   (ou flux.png)
"""

import importlib
import os
import shutil
import sys


def verifier():
    ok = True
    from .config import APP_CANAL, APP_VERSION, libelle_version
    print(f"      Flux {libelle_version(APP_VERSION, APP_CANAL)} · Python {sys.version.split()[0]}")
    for module, libelle, obligatoire in (
            ("torch", "PyTorch", True), ("ultralytics", "Ultralytics (YOLO26, RT-DETR)", True),
            ("cv2", "OpenCV", True), ("PySide6.QtWidgets", "Interface (PySide6)", True),
            ("PySide6.QtMultimedia", "Lecteur vidéo (Qt Multimedia)", False), ("onnxruntime", "ONNX Runtime", False),
            ("hsemotion_onnx", "Expressions du visage", False), ("rapidocr", "Lecture des plaques", False),
            ("yt_dlp", "Liens YouTube / Instagram", False), ("imageio_ffmpeg", "Encodeur vidéo (ffmpeg)", False)):
        try:
            m = importlib.import_module(module)
            v = getattr(m, "__version__", "")
            if module == "yt_dlp":
                v = m.version.__version__
            print(f"      OK   {libelle} {v}")
        except Exception as e:  # noqa: BLE001
            print(f"      {'ERREUR' if obligatoire else 'absent'} {libelle} : {e}")
            ok = ok and not obligatoire
    try:
        import cv2
        if int(cv2.__version__.split(".")[0]) >= 5:
            print("      ERREUR OpenCV 5 installé : Flux a besoin d'OpenCV 4")
            ok = False
    except Exception:  # noqa: BLE001
        pass
    try:
        import torch
        if torch.cuda.is_available():
            print(f"      OK   Carte graphique : {torch.cuda.get_device_name(0)} (CUDA {torch.version.cuda})")
        else:
            print("      --   Pas de carte graphique utilisable : calcul sur processeur (niveaux Rapide/Équilibré conseillés)")
    except Exception:  # noqa: BLE001
        pass
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/cpuinfo", encoding="utf-8") as f:
                ligne = next((l for l in f if l.startswith("flags")), "")
            modele = next((l.split(":", 1)[1].strip() for l in open("/proc/cpuinfo", encoding="utf-8")
                           if l.startswith("model name")), "?")
            drapeaux = set(ligne.split(":", 1)[-1].split())
            print(f"      --   Processeur : {modele} · {os.cpu_count()} cœurs · AVX {'oui' if 'avx' in drapeaux else 'non'}"
                  f" · AVX2 {'oui' if 'avx2' in drapeaux else 'non'}")
        except Exception:  # noqa: BLE001
            pass
    for prog, usage in (("deno", "YouTube"), ("ffmpeg", "téléchargement avec le son")):
        trouve = shutil.which(prog) or os.path.isfile(os.path.join(os.path.expanduser("~"), ".deno", "bin", prog))
        print(f"      {'OK  ' if trouve else '--  '} {prog} ({usage})"
              + ("" if trouve else " : absent (seul YouTube / le son des vidéos téléchargées en dépend)"))
    return 0 if ok else 1


def icone(chemin):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841
    from .theme import C, icone_application
    C.setdefault("accent", "#2F7BFF")
    pix = icone_application(256).pixmap(256, 256)
    return 0 if pix.save(chemin, "ICO" if chemin.lower().endswith(".ico") else "PNG") else 1


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "verifier"
    sys.exit(icone(sys.argv[2]) if action == "icone" else verifier())
