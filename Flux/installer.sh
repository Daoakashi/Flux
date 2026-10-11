#!/usr/bin/env bash
# ===========================================================================
#  Flux - installation complete pour Linux (Linux Mint, Ubuntu, Debian)
#  Paquets systeme, Python, environnement, PyTorch (processeur ou NVIDIA),
#  dependances, modele de detection, icone et lanceur sur le bureau.
#  Peut etre relance sans risque (reparation / mise a jour).
#
#  Utilisation :  bash installer.sh          (options : --auto  --veille  --oui)
# ===========================================================================
set -u
cd "$(dirname "$(readlink -f "$0")")" || exit 1
RACINE="$(pwd)"

AUTO=ask; VEILLE=ask
for a in "$@"; do
    case "$a" in
        --auto)   AUTO=yes ;;
        --veille) VEILLE=yes ;;
        --oui)    AUTO=yes; VEILLE=yes ;;
        --non)    AUTO=no; VEILLE=no ;;
    esac
done

if [ -t 1 ]; then V=$'\e[32m'; R=$'\e[31m'; J=$'\e[33m'; B=$'\e[1m'; N=$'\e[0m'; else V=; R=; J=; B=; N=; fi
etape()  { echo; echo "${B}[$1/8]${N} $2"; }
ok()     { echo "      ${V}OK${N}  $*"; }
info()   { echo "      $*"; }
alerte() { echo "      ${J}Attention :${N} $*"; }
erreur() {
    echo; echo "  ${R}${B}L'installation s'est arretee.${N}"; echo "  $*"
    echo "  Corrigez le probleme puis relancez :  bash installer.sh"
    echo "  (le message ci-dessus indique quoi faire ; sinon copiez-le pour demander de l'aide)"
    exit 1
}
oui() { # oui "question" defaut(o|n) mode(ask|yes|no)
    case "$3" in yes) return 0 ;; no) return 1 ;; esac
    [ -t 0 ] || { [ "$2" = o ]; return; }
    local rep; read -r -p "      $1 [$( [ "$2" = o ] && echo O/n || echo o/N )] " rep
    case "${rep,,}" in o|oui|y|yes) return 0 ;; n|non|no) return 1 ;; *) [ "$2" = o ] ;; esac
}

echo
echo "  =========================================="
echo "   Installation de Flux (Linux)"
echo "  =========================================="
[ "$(id -u)" -eq 0 ] && erreur "Ne lancez pas ce script avec sudo : lancez-le avec votre compte normal (il demandera le mot de passe quand il en a besoin)."

# ---------------------------------------------------------------------------
# 1. Verifications
# ---------------------------------------------------------------------------
etape 1 "Verification de la machine..."
ARCH="$(uname -m)"
[ "$ARCH" = "x86_64" ] || [ "$ARCH" = "aarch64" ] || erreur "Processeur $ARCH non pris en charge (il faut un PC 64 bits)."
LIBRE_MO=$(df -Pm "$RACINE" | awk 'NR==2 {print $4}')
[ "${LIBRE_MO:-0}" -ge 4000 ] || erreur "Il faut au moins 4 Go libres (il reste ${LIBRE_MO} Mo)."
MEM_MO=$(awk '/MemTotal/ {printf "%d", $2/1024}' /proc/meminfo)
CPU_NOM=$(awk -F: '/model name/ {gsub(/^ +/,"",$2); print $2; exit}' /proc/cpuinfo)
ok "${CPU_NOM:-Processeur} - $(nproc) coeurs - ${MEM_MO} Mo de memoire"
[ "${MEM_MO:-0}" -ge 3500 ] || alerte "Moins de 4 Go de memoire : limitez-vous a 1 ou 2 cameras."
if [ -f /etc/os-release ]; then . /etc/os-release; info "Systeme : ${PRETTY_NAME:-Linux}"; fi

# ---------------------------------------------------------------------------
# 2. Paquets du systeme (Python, ffmpeg, bibliotheques graphiques de Qt)
# ---------------------------------------------------------------------------
etape 2 "Paquets du systeme..."
PAQUETS="python3 python3-venv python3-pip ffmpeg curl unzip zenity libgl1 libegl1 libglib2.0-0 libdbus-1-3 \
libfontconfig1 libxkbcommon0 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-xkb1 libpulse0 libsm6 libxext6 \
intel-opencl-icd"
if command -v apt-get >/dev/null 2>&1; then
    SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
    if [ -n "$SUDO" ] && ! command -v sudo >/dev/null 2>&1; then
        alerte "sudo est absent : installez a la main ces paquets : $PAQUETS"
    else
        info "Le mot de passe de votre session peut etre demande. Cette etape peut prendre quelques minutes."
        $SUDO apt-get update -qq || alerte "apt update a echoue (depots indisponibles ?), on continue."
        # paquet par paquet : un nom absent sur cette version de Linux ne bloque pas les autres
        MANQUANTS=""
        for p in $PAQUETS; do
            dpkg -s "$p" >/dev/null 2>&1 && continue
            $SUDO apt-get install -y -qq "$p" >/dev/null 2>&1 || MANQUANTS="$MANQUANTS $p"
        done
        ok "Paquets installes."
        [ -z "$MANQUANTS" ] || alerte "non installes :$MANQUANTS (pas toujours necessaire ; voir plus bas si Flux ne demarre pas)."
    fi
else
    alerte "Ce script sait installer les paquets avec apt (Mint, Ubuntu, Debian)."
    info "Sur une autre distribution, installez : python3 (3.10 a 3.13) avec venv, ffmpeg, libxcb-cursor, libgl, libegl."
fi

# ---------------------------------------------------------------------------
# 3. Python 3.10 a 3.13 (3.12 de preference)
# ---------------------------------------------------------------------------
etape 3 "Python..."
PY=""
for v in 3.12 3.11 3.13 3.10; do
    command -v "python$v" >/dev/null 2>&1 && "python$v" -c "import venv, ensurepip" >/dev/null 2>&1 && { PY="python$v"; break; }
done
if [ -z "$PY" ] && command -v python3 >/dev/null 2>&1 && \
   python3 -c "import sys, venv, ensurepip; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,13) else 1)" >/dev/null 2>&1; then
    PY=python3
fi
[ -n "$PY" ] || erreur "Python 3.10 a 3.13 (avec le module venv) est introuvable. Sur Mint / Ubuntu : sudo apt install python3 python3-venv"
ok "$($PY --version 2>&1)"

# ---------------------------------------------------------------------------
# 4. Environnement virtuel (recree s'il est casse)
# ---------------------------------------------------------------------------
etape 4 "Environnement Python..."
if [ -x venv/bin/python ] && ! venv/bin/python -c "import sys" >/dev/null 2>&1; then
    info "Environnement existant casse : recreation..."; rm -rf venv
fi
if [ ! -x venv/bin/python ]; then
    [ -d venv ] && rm -rf venv
    $PY -m venv venv || erreur "Impossible de creer l'environnement. Sur Mint / Ubuntu : sudo apt install python3-venv"
else
    info "Environnement existant conserve."
fi
VPY="$RACINE/venv/bin/python"
"$VPY" -m pip install --upgrade pip --quiet --disable-pip-version-check || erreur "pip n'a pas pu se mettre a jour (connexion Internet ?)."
ok "Environnement pret."

# ---------------------------------------------------------------------------
# 5. PyTorch : version NVIDIA si une carte est presente, sinon version processeur (bien plus legere)
# ---------------------------------------------------------------------------
etape 5 "PyTorch..."
if "$VPY" -c "import torch" >/dev/null 2>&1; then
    ok "PyTorch deja installe."
elif command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
    info "Carte NVIDIA detectee : installation de PyTorch avec CUDA (plusieurs Go, patientez)..."
    "$VPY" -m pip install torch torchvision --disable-pip-version-check || erreur "Installation de PyTorch impossible."
else
    info "Pas de carte NVIDIA : installation de PyTorch pour processeur (environ 200 Mo)..."
    "$VPY" -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu --disable-pip-version-check \
        || erreur "Installation de PyTorch impossible (connexion Internet ?)."
fi

# ---------------------------------------------------------------------------
# 6. Dependances de Flux
# ---------------------------------------------------------------------------
etape 6 "Dependances de Flux (quelques minutes)..."
"$VPY" -m pip install -r requirements.txt --disable-pip-version-check || erreur "Installation des dependances impossible."
"$VPY" -m pip install --upgrade "yt-dlp[default]" --quiet --disable-pip-version-check >/dev/null 2>&1
# OpenCV « headless » : la version normale embarque son propre Qt qui empeche l'interface de s'ouvrir sous Linux
if ! "$VPY" -m pip show opencv-python-headless >/dev/null 2>&1 || "$VPY" -m pip show opencv-python >/dev/null 2>&1 \
   || "$VPY" -m pip show opencv-contrib-python >/dev/null 2>&1; then
    info "Reglage d'OpenCV pour Linux..."
    "$VPY" -m pip uninstall -y opencv-python opencv-contrib-python opencv-python-headless --quiet >/dev/null 2>&1
    "$VPY" -m pip install "opencv-python-headless>=4.10,<5" --quiet --disable-pip-version-check \
        || erreur "Installation d'OpenCV impossible."
fi
# Deno : necessaire seulement pour YouTube
if ! command -v deno >/dev/null 2>&1 && [ ! -x "$HOME/.deno/bin/deno" ]; then
    info "Installation de Deno (YouTube)..."
    DENO_SH="$(mktemp)"
    if curl -fsSL https://deno.land/install.sh -o "$DENO_SH" 2>/dev/null && sh "$DENO_SH" -y >/dev/null 2>&1 \
       && [ -x "$HOME/.deno/bin/deno" ]; then
        ok "Deno installe."
    else
        alerte "Deno n'a pas pu etre installe : seul YouTube en sera affecte (relancez installer.sh plus tard)."
    fi
    rm -f "$DENO_SH"
fi

# ---------------------------------------------------------------------------
# 7. Verification + modele de detection
# ---------------------------------------------------------------------------
etape 7 "Verification..."
"$VPY" -I -c "
import numpy, torch, cv2
a = torch.ones(128, 128); (a @ a).sum().item()
cv2.GaussianBlur(numpy.zeros((64, 64, 3), 'uint8'), (5, 5), 0)
import onnxruntime
" >/dev/null 2>&1
CODE=$?
if [ "$CODE" -ge 128 ]; then
    erreur "Le processeur de cette machine ne gere pas une instruction que PyTorch / OpenCV / ONNX utilise (code $CODE). Indiquez le modele de processeur affiche plus haut pour obtenir une version adaptee."
elif [ "$CODE" -ne 0 ]; then
    alerte "Un module ne se charge pas correctement ; details ci-dessous."
fi
"$VPY" -m flux.outils verifier || erreur "La verification a trouve une erreur (voir ci-dessus)."
info "Telechargement des modeles de detection et de visages (une seule fois)..."
if "$VPY" -m flux.outils modeles; then ok "Modeles prets."
else alerte "Un modele n'a pas pu etre telecharge (raison ci-dessus) : Flux reessaiera au demarrage."; fi

# ---------------------------------------------------------------------------
# 8. Icone, lanceur, options
# ---------------------------------------------------------------------------
etape 8 "Lanceur et icone..."
chmod +x Flux.sh installer.sh 2>/dev/null
"$VPY" -m flux.outils icone "$RACINE/flux.png" >/dev/null 2>&1
BUREAU="$(xdg-user-dir DESKTOP 2>/dev/null)"; [ -d "$BUREAU" ] || BUREAU="$HOME/Desktop"
ecrire_lanceur() {
    cat > "$1" <<EOF
[Desktop Entry]
Type=Application
Name=Flux
Comment=Flux - surveillance video intelligente
Exec="$RACINE/Flux.sh"
Path=$RACINE
Icon=$RACINE/flux.png
Terminal=false
Categories=AudioVideo;Video;Security;
StartupWMClass=flux.py
EOF
    chmod +x "$1"
}
mkdir -p "$HOME/.local/share/applications"
ecrire_lanceur "$HOME/.local/share/applications/flux.desktop"
ok "Flux ajoute au menu des applications."
if [ -d "$BUREAU" ]; then
    ecrire_lanceur "$BUREAU/Flux.desktop"
    command -v gio >/dev/null 2>&1 && gio set "$BUREAU/Flux.desktop" metadata::trusted true >/dev/null 2>&1
    ok "Icone Flux sur le bureau."
fi
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1

echo
if oui "Lancer Flux automatiquement a l'ouverture de session (utile pour une surveillance permanente) ?" n "$AUTO"; then
    mkdir -p "$HOME/.config/autostart"
    ecrire_lanceur "$HOME/.config/autostart/flux.desktop"
    echo "X-GNOME-Autostart-delay=10" >> "$HOME/.config/autostart/flux.desktop"
    ok "Demarrage automatique active (pour l'enlever : supprimez ~/.config/autostart/flux.desktop)."
fi
if oui "Empecher la mise en veille de l'ecran et de l'ordinateur (conseille pour une surveillance 24h/24) ?" n "$VEILLE"; then
    if command -v gsettings >/dev/null 2>&1; then
        gsettings set org.cinnamon.desktop.session idle-delay 0 2>/dev/null
        gsettings set org.cinnamon.settings-daemon.plugins.power sleep-inactive-ac-timeout 0 2>/dev/null
        gsettings set org.cinnamon.settings-daemon.plugins.power sleep-display-ac 0 2>/dev/null
        gsettings set org.cinnamon.desktop.screensaver lock-enabled false 2>/dev/null
        gsettings set org.gnome.desktop.session idle-delay 0 2>/dev/null
        gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'nothing' 2>/dev/null
        ok "Mise en veille desactivee (a retablir dans Parametres > Gestion de l'energie)."
    else
        alerte "gsettings absent : reglez la mise en veille dans les parametres de votre bureau."
    fi
fi

echo
echo "  =========================================="
echo "   ${V}${B}Installation terminee.${N}"
echo "   Lancez Flux avec l'icone « Flux » du bureau,"
echo "   depuis le menu des applications,"
echo "   ou avec :  ./Flux.sh"
echo "  =========================================="
echo
