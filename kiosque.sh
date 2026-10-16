#!/usr/bin/env bash
# ===========================================================================
#  Flux - mode kiosque pour Linux (Linux Mint, Ubuntu, Debian)
#
#  Le PC demarre directement sur Flux, en plein ecran, sans bureau ni barre des
#  taches. Flux ne peut pas etre ferme ; s'il plante ou se met a jour, il se
#  relance tout seul. L'ecran ne se met jamais en veille.
#
#  Utilisation (dans le dossier de Flux, Flux deja installe avec installer.sh) :
#     sudo bash kiosque.sh activer      active le kiosque (demande un code administrateur)
#     sudo bash kiosque.sh desactiver   remet le PC comme avant (bureau normal)
#     sudo bash kiosque.sh code         change le code administrateur
#     bash kiosque.sh etat              indique si le kiosque est actif
#
#  Options de « activer » :
#     --utilisateur NOM     compte qui fait tourner Flux (par defaut : le votre)
#     --redemarrage HEURE   redemarre le PC chaque nuit a cette heure (ex. : 4)
#     --verrouiller         bloque aussi Ctrl+Alt+F1...F6 (terminaux) : plus de sortie
#                           sans le code administrateur ou une connexion SSH
#
#  Dans le kiosque :  Ctrl+Alt+Maj+Q puis le code administrateur  ->  quitte Flux
#  et revient a l'ecran de connexion (choisissez votre session habituelle).
# ===========================================================================
set -u
cd "$(dirname "$(readlink -f "$0")")" || exit 1
RACINE="$(pwd)"

ETC=/etc/flux-kiosque
SESSION_BIN=/usr/local/bin/flux-kiosque-session
SESSION_DESKTOP=/usr/share/xsessions/flux-kiosque.desktop
LIGHTDM_CONF=/etc/lightdm/lightdm.conf.d/90-flux-kiosque.conf
GDM_CONF=/etc/gdm3/custom.conf
XORG_CONF=/etc/X11/xorg.conf.d/90-flux-kiosque.conf
CRON=/etc/cron.d/flux-kiosque
CODE=/etc/flux-kiosque.json
CIBLES_VEILLE="sleep.target suspend.target hibernate.target hybrid-sleep.target"

if [ -t 1 ]; then V=$'\e[32m'; R=$'\e[31m'; J=$'\e[33m'; B=$'\e[1m'; N=$'\e[0m'; else V=; R=; J=; B=; N=; fi
ok()     { echo "  ${V}OK${N}  $*"; }
info()   { echo "      $*"; }
alerte() { echo "  ${J}Attention :${N} $*"; }
erreur() { echo; echo "  ${R}${B}Arret :${N} $*"; echo; exit 1; }

besoin_root() {
    [ "$(id -u)" -eq 0 ] || erreur "Lancez cette commande avec sudo :  sudo bash kiosque.sh $1"
}

gestionnaire_connexion() {
    local dm=""
    [ -L /etc/systemd/system/display-manager.service ] && \
        dm="$(basename "$(readlink -f /etc/systemd/system/display-manager.service)" .service)"
    [ -z "$dm" ] && [ -f /etc/X11/default-display-manager ] && dm="$(basename "$(cat /etc/X11/default-display-manager)")"
    echo "$dm"
}

demander_code() {
    local a b
    while true; do
        read -r -s -p "      Choisissez un code administrateur (4 caracteres minimum) : " a; echo
        [ "${#a}" -ge 4 ] || { alerte "trop court."; continue; }
        read -r -s -p "      Retapez le code : " b; echo
        [ "$a" = "$b" ] && break
        alerte "les deux codes sont differents, recommencez."
    done
    # empreinte PBKDF2 : le code n'est jamais enregistre en clair
    FLUX_CODE="$a" python3 - "$CODE" <<'PY' || erreur "Impossible d'enregistrer le code (python3 est-il installe ?)."
import hashlib, json, os, sys
sel = os.urandom(16)
n = 200000
d = {"sel": sel.hex(), "iterations": n,
     "empreinte": hashlib.pbkdf2_hmac("sha256", os.environ["FLUX_CODE"].encode("utf-8"), sel, n).hex()}
with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump(d, f)
PY
    chown root:root "$CODE"; chmod 644 "$CODE"
    ok "Code administrateur enregistre (lisible par Flux, modifiable seulement avec sudo)."
}

# ---------------------------------------------------------------------------
activer() {
    besoin_root activer
    local UTIL="${SUDO_USER:-}" HEURE="" VERROU=no
    while [ $# -gt 0 ]; do
        case "$1" in
            --utilisateur) UTIL="${2:-}"; shift ;;
            --redemarrage) HEURE="${2:-}"; shift ;;
            --verrouiller) VERROU=yes ;;
            *) erreur "Option inconnue : $1" ;;
        esac
        shift
    done
    echo
    echo "  =========================================="
    echo "   Flux : activation du mode kiosque"
    echo "  =========================================="
    [ -n "$UTIL" ] && [ "$UTIL" != root ] || erreur "Indiquez le compte qui fait tourner Flux : sudo bash kiosque.sh activer --utilisateur NOM"
    id "$UTIL" >/dev/null 2>&1 || erreur "Le compte « $UTIL » n'existe pas."
    [ -x "$RACINE/venv/bin/python" ] || erreur "Flux n'est pas installe dans $RACINE. Lancez d'abord :  bash installer.sh"
    [ -f "$RACINE/Flux.sh" ] || erreur "Flux.sh est introuvable dans $RACINE."
    runuser -u "$UTIL" -- test -r "$RACINE/flux.py" || erreur "Le compte « $UTIL » ne peut pas lire $RACINE."
    if [ -n "$HEURE" ]; then
        [[ "$HEURE" =~ ^([01]?[0-9]|2[0-3])$ ]] || erreur "--redemarrage attend une heure de 0 a 23 (ex. : 4)."
    fi
    local DM; DM="$(gestionnaire_connexion)"
    case "$DM" in
        lightdm|gdm|gdm3) ok "Compte : $UTIL - dossier : $RACINE - ecran de connexion : $DM" ;;
        *) erreur "Ecran de connexion « ${DM:-inconnu} » non pris en charge (il faut LightDM, celui de Linux Mint, ou GDM)." ;;
    esac

    # 1. Paquets : Openbox (gestionnaire de fenetres minimal) et outils d'ecran
    info "Installation des paquets (openbox, x11-xserver-utils, zenity)..."
    apt-get update -qq >/dev/null 2>&1
    for p in openbox x11-xserver-utils x11-utils zenity; do
        dpkg -s "$p" >/dev/null 2>&1 || apt-get install -y -qq "$p" >/dev/null 2>&1 || alerte "paquet $p non installe."
    done
    command -v openbox >/dev/null 2>&1 || erreur "openbox n'a pas pu etre installe (connexion Internet ?) :  sudo apt install openbox"
    ok "Paquets installes."

    # 2. Code administrateur
    if [ -f "$CODE" ]; then
        ok "Code administrateur deja defini (pour le changer :  sudo bash kiosque.sh code)."
    else
        demander_code
    fi

    # 3. Configuration d'Openbox : aucun menu, aucun raccourci, rien a part Flux
    mkdir -p "$ETC"
    cat > "$ETC/openbox.xml" <<'XML'
<?xml version="1.0" encoding="UTF-8"?>
<openbox_config xmlns="http://openbox.org/3.4/rc">
  <focus><focusNew>yes</focusNew><followMouse>no</followMouse></focus>
  <placement><policy>Smart</policy><center>yes</center></placement>
  <desktops><number>1</number></desktops>
  <keyboard></keyboard>
  <mouse>
    <context name="Frame"><mousebind button="Left" action="Press"><action name="Focus"/><action name="Raise"/></mousebind></context>
    <context name="Client"><mousebind button="Left" action="Press"><action name="Focus"/><action name="Raise"/></mousebind></context>
    <context name="Titlebar"><mousebind button="Left" action="Drag"><action name="Move"/></mousebind>
      <mousebind button="Left" action="Press"><action name="Focus"/><action name="Raise"/></mousebind></context>
  </mouse>
  <menu></menu>
  <applications>
    <application class="*"><decor>no</decor><focus>yes</focus></application>
  </applications>
</openbox_config>
XML

    # 4. Session « Flux (kiosque) » : ecran toujours allume, Flux relance s'il s'arrete
    cat > "$SESSION_BIN" <<SESSION
#!/usr/bin/env bash
# Session kiosque de Flux (cree par kiosque.sh). Ne pas modifier : relancez kiosque.sh activer.
DOSSIER="$RACINE"
SESSION
    cat >> "$SESSION_BIN" <<'SESSION'
MARQUEUR="${XDG_RUNTIME_DIR:-/tmp}/flux-kiosque-quitter"
JOURNAL="$HOME/.local/state/flux-kiosque.log"
mkdir -p "$(dirname "$JOURNAL")"
[ -f "$JOURNAL" ] && [ "$(stat -c %s "$JOURNAL")" -gt 5000000 ] && mv -f "$JOURNAL" "$JOURNAL.1"
echo "=== $(date '+%F %T') demarrage de la session kiosque" >> "$JOURNAL"
xset s off; xset s noblank; xset -dpms      # jamais d'economiseur ni de mise en veille de l'ecran
xsetroot -solid "#0b1220" 2>/dev/null
openbox --config-file /etc/flux-kiosque/openbox.xml &
OB=$!
rm -f "$MARQUEUR"
rapides=0
while true; do
    debut=$(date +%s)
    bash "$DOSSIER/Flux.sh" --kiosque >> "$JOURNAL" 2>&1
    code=$?
    if [ -f "$MARQUEUR" ]; then               # Ctrl+Alt+Maj+Q + code administrateur
        rm -f "$MARQUEUR"
        echo "=== $(date '+%F %T') sortie du kiosque par l'administrateur" >> "$JOURNAL"
        break
    fi
    if [ "$code" -eq 3 ]; then                # mise a jour : relance immediate
        echo "=== $(date '+%F %T') redemarrage apres mise a jour" >> "$JOURNAL"
        sleep 1; continue
    fi
    echo "=== $(date '+%F %T') Flux s'est arrete (code $code) : relance" >> "$JOURNAL"
    if [ $(( $(date +%s) - debut )) -lt 60 ]; then rapides=$((rapides + 1)); else rapides=0; fi
    if [ "$rapides" -ge 5 ]; then             # plante au demarrage en boucle : on previent et on patiente
        zenity --error --title="Flux" --no-markup --timeout=120 --width=520 \
            --text="Flux s'arrete juste apres son demarrage. Nouvel essai dans 2 minutes.

Details : $JOURNAL et $DOSSIER/flux_erreur.log
Pour reparer : Ctrl+Alt+F2, connectez-vous, puis dans le dossier de Flux :  bash installer.sh" 2>/dev/null \
            || sleep 120
        rapides=0
    else
        sleep 3
    fi
done
kill "$OB" 2>/dev/null
SESSION
    chmod 755 "$SESSION_BIN"
    cat > "$SESSION_DESKTOP" <<'DESK'
[Desktop Entry]
Name=Flux (kiosque)
Comment=Flux seul, en plein ecran, relance automatiquement
Exec=/usr/local/bin/flux-kiosque-session
Type=Application
DesktopNames=Flux
DESK
    ok "Session « Flux (kiosque) » creee."

    # 5. Connexion automatique sur cette session au demarrage du PC
    groupadd -f autologin >/dev/null 2>&1; gpasswd -a "$UTIL" autologin >/dev/null 2>&1
    if [ "$DM" = lightdm ]; then
        mkdir -p "$(dirname "$LIGHTDM_CONF")"
        cat > "$LIGHTDM_CONF" <<CONF
# Cree par kiosque.sh (Flux). Supprime par :  sudo bash kiosque.sh desactiver
[Seat:*]
autologin-user=$UTIL
autologin-user-timeout=0
autologin-session=flux-kiosque
CONF
        # une connexion automatique reglee ailleurs (Fenetre de connexion de Mint) passerait avant : on la met de cote
        if [ -f /etc/lightdm/lightdm.conf ] && grep -qE '^[[:space:]]*autologin-(user|session)' /etc/lightdm/lightdm.conf; then
            [ -f "$ETC/lightdm.conf.avant-kiosque" ] || cp -a /etc/lightdm/lightdm.conf "$ETC/lightdm.conf.avant-kiosque"
            sed -i -E 's/^([[:space:]]*autologin-(user|session|user-timeout).*)$/# (kiosque Flux) \1/' /etc/lightdm/lightdm.conf
        fi
        ok "Connexion automatique de « $UTIL » sur Flux (LightDM)."
    else
        [ -f "$ETC/gdm-custom.conf.avant-kiosque" ] || cp -a "$GDM_CONF" "$ETC/gdm-custom.conf.avant-kiosque" 2>/dev/null
        python3 - "$GDM_CONF" "$UTIL" <<'PY'
import configparser, sys
c = configparser.ConfigParser(interpolation=None); c.optionxform = str
c.read(sys.argv[1])
c.setdefault("daemon", {})
c["daemon"]["AutomaticLoginEnable"] = "true"; c["daemon"]["AutomaticLogin"] = sys.argv[2]; c["daemon"]["WaylandEnable"] = "false"
with open(sys.argv[1], "w") as f: c.write(f)
PY
        local AS="/var/lib/AccountsService/users/$UTIL"
        mkdir -p "$(dirname "$AS")"
        [ -f "$ETC/accountsservice.avant-kiosque" ] || { [ -f "$AS" ] && cp -a "$AS" "$ETC/accountsservice.avant-kiosque" || touch "$ETC/accountsservice.absent"; }
        python3 - "$AS" <<'PY'
import configparser, sys
c = configparser.ConfigParser(interpolation=None); c.optionxform = str
c.read(sys.argv[1]); c.setdefault("User", {})
c["User"]["XSession"] = "flux-kiosque"; c["User"]["Session"] = "flux-kiosque"
with open(sys.argv[1], "w") as f: c.write(f)
PY
        ok "Connexion automatique de « $UTIL » sur Flux (GDM)."
    fi

    # 6. Jamais de mise en veille du PC (on note ce qui etait deja bloque pour le remettre comme avant)
    if [ ! -f "$ETC/veille.avant-kiosque" ]; then
        for c in $CIBLES_VEILLE; do
            [ "$(systemctl is-enabled "$c" 2>/dev/null)" = masked ] && echo "$c"
        done > "$ETC/veille.avant-kiosque"
    fi
    systemctl mask $CIBLES_VEILLE >/dev/null 2>&1 && ok "Mise en veille du PC desactivee."

    # 7. Options
    if [ -n "$HEURE" ]; then
        printf '# Cree par kiosque.sh (Flux) : redemarrage quotidien\n0 %s * * * root /sbin/shutdown -r now "Redemarrage quotidien du kiosque Flux"\n' "$HEURE" > "$CRON"
        chmod 644 "$CRON"
        ok "Redemarrage automatique chaque jour a ${HEURE} h."
    else
        rm -f "$CRON"
    fi
    if [ "$VERROU" = yes ]; then
        mkdir -p "$(dirname "$XORG_CONF")"
        printf '# Cree par kiosque.sh (Flux)\nSection "ServerFlags"\n    Option "DontVTSwitch" "true"\n    Option "DontZap" "true"\nEndSection\n' > "$XORG_CONF"
        ok "Terminaux Ctrl+Alt+F1...F6 bloques."
        alerte "pour sortir : Ctrl+Alt+Maj+Q + code administrateur (ou une connexion SSH)."
    else
        rm -f "$XORG_CONF"
    fi
    echo "$UTIL" > "$ETC/utilisateur"
    echo "$RACINE" > "$ETC/dossier"

    echo
    echo "  ${V}${B}Mode kiosque active.${N}"
    info "Au prochain demarrage, le PC ouvre Flux directement, en plein ecran."
    info "Quitter le kiosque : Ctrl+Alt+Maj+Q, puis le code administrateur."
    info "Desactiver pour de bon :  sudo bash kiosque.sh desactiver"
    info "Conseil : dans le BIOS du PC, reglez « Restore on AC Power Loss » sur « Power On »"
    info "pour qu'il redemarre tout seul apres une coupure de courant."
    echo
    if [ -t 0 ]; then
        local rep; read -r -p "      Redemarrer maintenant pour essayer ? [o/N] " rep
        case "${rep,,}" in o|oui|y|yes) systemctl reboot ;; esac
    fi
}

# ---------------------------------------------------------------------------
desactiver() {
    besoin_root desactiver
    local UTIL=""; [ -f "$ETC/utilisateur" ] && UTIL="$(cat "$ETC/utilisateur")"
    rm -f "$LIGHTDM_CONF" "$XORG_CONF" "$CRON" "$SESSION_DESKTOP" "$SESSION_BIN"
    if [ -f "$ETC/lightdm.conf.avant-kiosque" ]; then
        cp -a "$ETC/lightdm.conf.avant-kiosque" /etc/lightdm/lightdm.conf
    fi
    if [ -f "$ETC/gdm-custom.conf.avant-kiosque" ]; then
        cp -a "$ETC/gdm-custom.conf.avant-kiosque" "$GDM_CONF"
    fi
    if [ -n "$UTIL" ]; then
        local AS="/var/lib/AccountsService/users/$UTIL"
        if [ -f "$ETC/accountsservice.avant-kiosque" ]; then cp -a "$ETC/accountsservice.avant-kiosque" "$AS"
        elif [ -f "$ETC/accountsservice.absent" ]; then rm -f "$AS"; fi
    fi
    # veille : on ne debloque que ce que le kiosque avait bloque
    for c in $CIBLES_VEILLE; do
        grep -qx "$c" "$ETC/veille.avant-kiosque" 2>/dev/null || systemctl unmask "$c" >/dev/null 2>&1
    done
    rm -f "$CODE"
    rm -rf "$ETC"
    ok "Mode kiosque desactive : au prochain demarrage, le PC revient a l'ecran de connexion habituel."
    info "(Flux reste installe ; Openbox aussi, il ne derange pas.)"
}

etat() {
    if [ -f "$SESSION_BIN" ] && { [ -f "$LIGHTDM_CONF" ] || grep -qs "flux-kiosque" /var/lib/AccountsService/users/*; }; then
        echo "  ${V}Mode kiosque ACTIF${N} - compte : $(cat "$ETC/utilisateur" 2>/dev/null) - dossier : $(cat "$ETC/dossier" 2>/dev/null)"
        [ -f "$CRON" ] && echo "      Redemarrage quotidien : $(awk '/shutdown/ {print $2 " h"}' "$CRON")"
        [ -f "$XORG_CONF" ] && echo "      Terminaux Ctrl+Alt+F1...F6 bloques"
        [ -f "$CODE" ] && echo "      Code administrateur : defini" || echo "      ${J}Code administrateur : absent${N} (sudo bash kiosque.sh code)"
    else
        echo "  Mode kiosque inactif. Pour l'activer :  sudo bash kiosque.sh activer"
    fi
}

case "${1:-}" in
    activer)    shift; activer "$@" ;;
    desactiver) desactiver ;;
    code)       besoin_root code; mkdir -p "$ETC"; demander_code ;;
    etat)       etat ;;
    *)
        echo "Utilisation :"
        echo "  sudo bash kiosque.sh activer [--redemarrage 4] [--verrouiller] [--utilisateur NOM]"
        echo "  sudo bash kiosque.sh desactiver"
        echo "  sudo bash kiosque.sh code"
        echo "  bash kiosque.sh etat"
        exit 1 ;;
esac
