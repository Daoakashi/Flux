"""Flux — surveillance vidéo intelligente."""
import os as _os

# Outils installés à côté de Flux par installer.bat / installer.sh (deno, ffmpeg) : trouvés sans toucher au PATH
# de Windows, donc sans redémarrer la session.
_OUTILS = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "outils")
if _os.path.isdir(_OUTILS) and _OUTILS not in _os.environ.get("PATH", "").split(_os.pathsep):
    _os.environ["PATH"] = _OUTILS + _os.pathsep + _os.environ.get("PATH", "")
_DENO_UTILISATEUR = _os.path.join(_os.path.expanduser("~"), ".deno", "bin")
if _os.path.isdir(_DENO_UTILISATEUR) and _DENO_UTILISATEUR not in _os.environ.get("PATH", ""):
    _os.environ["PATH"] = _os.environ["PATH"] + _os.pathsep + _DENO_UTILISATEUR
