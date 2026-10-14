#!/bin/bash
# Installs FireFly on the handheld. Run it over SSH from the unzipped folder:
#   bash deploy/install.sh
# The first install needs internet on the handheld (Wi-Fi or USB Ethernet).
# Updating an installed FireFly does not: a zip from a Stump's /tools page
# installs off-grid when nothing new is needed from the internet.
set -e
APP="$HOME/firefly"
HERE="$(cd "$(dirname "$0")/.." && pwd)"

echo "== Checking this handheld"
if ! command -v apt-get >/dev/null; then
  echo "ERROR: no apt-get. FireFly needs a Debian-based firmware such as the dArkOS image of arkos4clone."
  exit 1
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
  echo "ERROR: Python $(python3 -V 2>&1 | cut -d" " -f2) is too old (FireFly needs 3.9 or newer)."
  echo "       This usually means an older ArkOS image; use the dArkOS image instead."
  exit 1
fi
MODEL=$( { tr -d '\0' < /proc/device-tree/model; } 2>/dev/null || echo unknown)
FB=$(cat /sys/class/graphics/fb0/virtual_size 2>/dev/null | tr , x)
echo "   device: $MODEL   screen: ${FB:-unknown}   $(. /etc/os-release 2>/dev/null; echo "$PRETTY_NAME")   Python $(python3 -V 2>&1 | cut -d" " -f2)"

echo "== 0/5 Upgrade from RetiCom (FireFly's former name), if present"
OLD_APP="$HOME/reticom"; OLD_DATA="$HOME/.reticom"; NEW_DATA="$HOME/.firefly"
if pgrep -f "python.* -m reticom" >/dev/null; then
  pkill -f "python.* -m reticom"; sleep 2; echo "   stopped RetiCom"
fi
if [ -d "$OLD_DATA" ] && [ ! -e "$NEW_DATA" ]; then
  # Same filesystem: an atomic rename, so the identity key can't be half-copied.
  mv "$OLD_DATA" "$NEW_DATA" && sync
  echo "   moved your data $OLD_DATA -> $NEW_DATA (same identity, same address)"
elif [ -d "$OLD_DATA" ]; then
  echo "   ! both $OLD_DATA and $NEW_DATA exist: keeping both, FireFly uses $NEW_DATA"
fi
for p in /roms/ports/RetiCom.sh /roms2/ports/RetiCom.sh; do
  [ -f "$p" ] && sudo rm -f "$p" && echo "   removed old launcher $p"
done
if [ -d "$OLD_APP" ] && [ "$(realpath "$OLD_APP")" != "$(realpath "$HERE")" ]; then
  rm -rf "$OLD_APP" && echo "   removed old app folder $OLD_APP (your data is not in it)"
fi

echo "== 1/5 System packages (prebuilt: no compiling, so no swap needed)"
# Needed to run at all:
NEEDED="python3-venv python3-pygame python3-cryptography python3-serial"
# Nice to have: the font, and the voice-note decoders (opus-tools: Opus, codec2: Codec 2).
OPTIONAL="fonts-dejavu-core opus-tools codec2"
missing() { for p in "$@"; do dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q "ok installed" || echo "$p"; done; }
TODO=$(missing $NEEDED $OPTIONAL | tr '\n' ' ')
if [ -z "${TODO// }" ]; then
  echo "   all present, nothing to download"
elif sudo apt-get update && sudo apt-get install -y $TODO; then
  :
else
  STILL=$(missing $NEEDED | tr '\n' ' ')
  if [ -n "${STILL// }" ]; then
    echo "ERROR: could not install $STILL (no internet?)."
    echo "       The first install needs internet once: connect Wi-Fi or USB Ethernet and run this again."
    exit 1
  fi
  echo "   ! no internet: carrying on without $(missing $OPTIONAL | tr '\n' ' ')"
  echo "     (voice notes in those formats show but won't play until you run this again online)"
fi

echo "== 2/5 App files -> $APP (btrfs home, not exFAT /roms)"
if [ ! -f "$HERE/firefly/core.py" ]; then
  echo "ERROR: $HERE/firefly (the Python package folder) is missing."
  echo "Copy the inner 'firefly' folder from the zip back into $HERE and run this again."
  exit 1
fi
mkdir -p "$APP"
if [ "$(realpath "$HERE")" != "$(realpath "$APP")" ]; then
  # Installing from somewhere else (e.g. a copy on the SD card): replace the app files.
  rm -rf "$APP/firefly" "$APP/deploy"
  cp -r "$HERE/firefly" "$HERE/deploy" "$APP/"
else
  echo "   already in place ($APP), nothing to copy"
fi

echo "== 3/5 Reticulum + LXMF in a private environment"
# PYTHONNOUSERSITE: ignore any rns/lxmf in ~/.local so the app always uses its own copy.
export PYTHONNOUSERSITE=1
[ -d "$APP/venv" ] || python3 -m venv --system-site-packages "$APP/venv"
# Exactly the versions this FireFly release was tested with.
RNS_V=1.5.6; LXMF_V=1.2.0
have() { "$APP/venv/bin/python" -c "import importlib.metadata as m, sys; sys.exit(0 if m.version('$1') == '$2' else 1)" 2>/dev/null; }
if have rns "$RNS_V" && have lxmf "$LXMF_V"; then
  echo "   rns $RNS_V and lxmf $LXMF_V already installed, nothing to download"
elif ls "$HERE"/wheels/rns-"$RNS_V"-*.whl "$HERE"/wheels/lxmf-"$LXMF_V"-*.whl >/dev/null 2>&1; then
  echo "   installing from the wheels/ folder (no internet needed)"
  "$APP/venv/bin/pip" install --no-index --find-links "$HERE/wheels" "rns==$RNS_V" "lxmf==$LXMF_V"
elif ! "$APP/venv/bin/pip" install --upgrade "rns==$RNS_V" "lxmf==$LXMF_V"; then
  echo "ERROR: could not download Reticulum $RNS_V and LXMF $LXMF_V (no internet?)."
  echo "       Connect Wi-Fi or USB Ethernet and run this again, or put rns-$RNS_V-py3-none-any.whl and"
  echo "       lxmf-$LXMF_V-py3-none-any.whl in a 'wheels' folder next to 'deploy' (see INSTALL.md)."
  exit 1
fi

echo "== 4/5 Serial port access for the LoRa radio"
sudo usermod -aG dialout "$USER" || true

echo "== 5/5 Ports menu entry"
PORTS=/roms/ports
[ -d /roms2/ports ] && PORTS=/roms2/ports
sudo mkdir -p "$PORTS"
sudo cp "$APP/deploy/FireFly.sh" "$PORTS/FireFly.sh"
echo "   added $PORTS/FireFly.sh"

echo
echo "Radio check (plug the RNode into the USB hub first):"
ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || echo "  no USB serial device found yet"
lsmod | grep -E "cp210x|ch341|cdc_acm|ftdi_sio" || echo "  (no USB-serial driver module listed; it may be built into the kernel)"
"$APP/venv/bin/python" -c "import pygame, sys; sys.exit(0 if pygame.version.vernum >= (2, 0) else 1)" || {
  echo "ERROR: pygame 2 is required; this firmware provides $("$APP/venv/bin/python" -c 'import pygame; print(pygame.version.ver)' 2>/dev/null)."; exit 1; }
"$APP/venv/bin/python" -c "import RNS, LXMF, pygame; print('Reticulum', RNS.__version__, 'from', RNS.__file__.rsplit('/RNS/',1)[0]); print('LXMF', LXMF.__version__, '/ pygame', pygame.version.ver)"
sync
echo
echo "Done. Reboot or restart EmulationStation, then open Ports > FireFly."
echo "(A reboot is also what applies the new serial-port permission.)"
