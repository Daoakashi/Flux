"""Flux — surveillance vidéo intelligente.

Lancement :  Windows : Flux.bat · Linux : Flux.sh ou l'icône « Flux » (ou : python flux.py)
"""
import os
import shutil
import subprocess
import sys
import traceback


def erreur_fatale():
    """Sans console (pythonw), une erreur au démarrage serait invisible : on l'écrit et on l'affiche."""
    texte = traceback.format_exc()
    chemin = os.path.join(os.path.dirname(os.path.abspath(__file__)), "flux_erreur.log")
    try:
        with open(chemin, "w", encoding="utf-8") as f:
            f.write(texte)
    except OSError:
        pass
    conseil = ""
    if os.name == "nt" and ("c10.dll" in texte or "WinError 126" in texte or "DLL load failed" in texte):
        conseil = ("Il manque Microsoft Visual C++ (nécessaire à PyTorch). Relancez installer.bat, qui l'installe, "
                   "ou installez https://aka.ms/vs/17/release/vc_redist.x64.exe puis redémarrez le PC.\n\n")
    message = (f"Flux n'a pas pu démarrer.\n\n{texte.strip().splitlines()[-1]}\n\n{conseil}"
               f"Détails dans flux_erreur.log. Relancer "
               f"{'installer.bat' if os.name == 'nt' else 'installer.sh'} répare la plupart des problèmes.")
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "Flux", 0x10)
            return
        except Exception:  # noqa: BLE001
            pass
    elif shutil.which("zenity"):  # Linux : boîte de dialogue si le bureau en fournit une
        try:
            subprocess.run(["zenity", "--error", "--title=Flux", "--no-markup", f"--text={message}"], timeout=600)
        except Exception:  # noqa: BLE001
            pass
    print(message, file=sys.stderr)


if __name__ == "__main__":
    try:
        from flux.fenetre import main
        main()
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        erreur_fatale()
        sys.exit(1)
