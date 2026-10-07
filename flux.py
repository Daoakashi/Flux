"""Flux — surveillance vidéo intelligente.

Lancement :  double-cliquer sur Flux.bat  (ou : python flux.py)
"""
import os
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
    message = (f"Flux n'a pas pu démarrer.\n\n{texte.strip().splitlines()[-1]}\n\n"
               f"Détails dans flux_erreur.log. Relancer installer.bat répare la plupart des problèmes.")
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "Flux", 0x10)
            return
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
