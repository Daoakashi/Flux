"""Outils appelés par installer.bat / installer.sh : vérification de l'installation et création de l'icône.

    python -m flux.outils verifier
    python -m flux.outils modeles      (télécharge les modèles de détection et de visages)
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
    if not visual_cpp_ok():
        print("      ERREUR Microsoft Visual C++ absent : PyTorch ne peut pas démarrer (c10.dll).")
        print("             Relancez installer.bat, ou installez https://aka.ms/vs/17/release/vc_redist.x64.exe")
        ok = False
    for module, libelle, obligatoire in (
            ("torch", "PyTorch", True), ("ultralytics", "Ultralytics (YOLO26, RT-DETR)", True),
            ("cv2", "OpenCV", True), ("PySide6.QtWidgets", "Interface (PySide6)", True),
            ("PySide6.QtMultimedia", "Lecteur vidéo (Qt Multimedia)", False), ("onnxruntime", "ONNX Runtime", False),
            ("hsemotion_onnx", "Expressions du visage", False), ("rapidocr", "Lecture des plaques", False),
            ("yt_dlp", "Liens YouTube / Instagram", False), ("imageio_ffmpeg", "Encodeur vidéo (ffmpeg)", False),
            ("openvino", "Accélération OpenVINO (processeur, puce Intel)", False)):
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


def modeles():
    """Télécharge pendant l'installation les modèles utiles, pour que Flux démarre sans attendre ni échouer."""
    from .config import Config, niveau_effectif
    from .vision import MODELES_VISAGE, assurer_modele, expliquer_erreur_reseau, fichier_visage
    cfg = Config()
    a_prendre = ["yolo26n.pt"]
    m, *_ = niveau_effectif(cfg.get("detection.niveau"), cfg)
    if m not in a_prendre and m.endswith(".pt") and not m.startswith("rtdetr") and "x." not in m:
        a_prendre.append(m)
    ok = True
    for nom in a_prendre:
        print(f"      {nom} ...", end=" ", flush=True)
        try:
            assurer_modele(nom, lambda f: None)
            print("OK")
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"ECHEC : {e}")
    # Conversion OpenVINO dès l'installation (sinon : une minute d'attente au premier démarrage d'une caméra)
    try:
        from .vision import appareil, exporter_modele, moteur_effectif, chemin_modele, modele_valide
        moteur = moteur_effectif(cfg, appareil(cfg.get("detection.appareil")))
        if moteur != "pytorch":
            taille = niveau_effectif(cfg.get("detection.niveau"), cfg)[1]
            for nom in a_prendre:
                if modele_valide(chemin_modele(nom)):
                    print(f"      {nom} -> {moteur} ({taille} px) ...", end=" ", flush=True)
                    try:
                        exporter_modele(chemin_modele(nom), moteur, taille)
                        print("OK")
                    except Exception as e:  # noqa: BLE001
                        print(f"ignoré ({str(e)[:100]}) : PyTorch sera utilisé")
    except Exception as e:  # noqa: BLE001
        print(f"      Optimisation ignorée : {str(e)[:120]}")
    for cle in MODELES_VISAGE:
        print(f"      {MODELES_VISAGE[cle][0]} ...", end=" ", flush=True)
        try:
            fichier_visage(cle)
            print("OK")
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"ECHEC : {expliquer_erreur_reseau(e)}")
    return 0 if ok else 1


def visual_cpp_ok():
    """Windows : PyTorch a besoin du runtime Microsoft Visual C++ 2015-2022 (sinon « c10.dll » / WinError 126)."""
    if os.name != "nt":
        return True
    racine = os.environ.get("SystemRoot", r"C:\Windows")
    return all(os.path.isfile(os.path.join(racine, "System32", d)) for d in ("vcruntime140.dll", "vcruntime140_1.dll",
                                                                            "msvcp140.dll"))


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
    sys.exit(icone(sys.argv[2]) if action == "icone" else modeles() if action == "modeles" else verifier())
