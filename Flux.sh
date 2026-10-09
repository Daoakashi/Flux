#!/usr/bin/env bash
# Lance Flux (Linux). Double-clic sur l'icone « Flux » du bureau, ou : ./Flux.sh
cd "$(dirname "$(readlink -f "$0")")" || exit 1
export PATH="$HOME/.deno/bin:$PATH"
if [ ! -x venv/bin/python ]; then
    MSG="Flux n'est pas encore installe. Ouvrez un terminal dans ce dossier et tapez :  bash installer.sh"
    if command -v zenity >/dev/null 2>&1 && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
        zenity --warning --title="Flux" --no-markup --text="$MSG"
    else
        echo "$MSG"
    fi
    exit 1
fi
exec venv/bin/python flux.py "$@"
