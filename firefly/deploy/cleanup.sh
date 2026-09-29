#!/bin/bash
# Removes every trace of previous FireFly installs so the next install starts clean.
# Run it from the NEW unzipped copy, outside /home/ark/firefly (see INSTALL.md):
#
#   bash deploy/cleanup.sh                  # reinstall clean, keeping your address and settings
#   bash deploy/cleanup.sh --new-identity   # ...and start with a NEW address
#   bash deploy/cleanup.sh --factory-reset  # new address AND default settings
#   bash deploy/cleanup.sh --purge-user-rns # also remove rns/lxmf from ~/.local
#
# Messages are always removed. Your identity key and settings are always
# backed up to ~/firefly-backup-<date>/ first, whatever you choose.

APP="${FIREFLY_APP:-$HOME/firefly}"
DATA="$HOME/.firefly"
KEEP_ID=1; KEEP_SETTINGS=1; PURGE_USER=0
for a in "$@"; do
  case "$a" in
    --keep-identity) KEEP_ID=1 ;;                       # the default since 0.3.1; still accepted
    --new-identity) KEEP_ID=0 ;;
    --factory-reset) KEEP_ID=0; KEEP_SETTINGS=0 ;;
    --purge-user-rns) PURGE_USER=1 ;;
    *) echo "unknown option $a"; exit 2 ;;
  esac
done

HERE="$(cd "$(dirname "$0")/.." && pwd)"
case "$HERE/" in
  "$APP"/*|"$HOME/reticom"/*) echo "Run this from a copy outside $APP (it deletes $APP)."; exit 1 ;;
esac

echo "== 1/6 Stop FireFly if it is running"
if pgrep -f "python.* -m (firefly|reticom)" >/dev/null; then
  pkill -f "python.* -m (firefly|reticom)"; sleep 2
  pkill -9 -f "python.* -m (firefly|reticom)" 2>/dev/null
  echo "   stopped"
else
  echo "   not running"
fi

echo "== 2/6 Back up the identity key"
BACKUP="$HOME/firefly-backup-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP"
found=0
OLD_DATA="$HOME/.reticom"   # FireFly's former name, RetiCom
for d in "$DATA" "$OLD_DATA"; do
  [ -d "$d" ] || continue
  sub="$BACKUP"; [ "$d" = "$OLD_DATA" ] && sub="$BACKUP/from-reticom" && mkdir -p "$sub"
  for f in "$d"/identity "$d"/identity.bak "$d"/identity.damaged-*; do
    [ -f "$f" ] && cp -p "$f" "$sub/" && found=1
  done
  [ -f "$d/settings.json" ] && cp -p "$d/settings.json" "$sub/"
done
if [ $found = 1 ]; then
  echo "   saved to $BACKUP"
  for f in "$BACKUP"/identity "$BACKUP"/identity.bak; do
    [ -f "$f" ] && echo "   $(basename "$f"): $(stat -c %s "$f") bytes (a good key is 64)"
  done
else
  echo "   no identity found"; rmdir "$BACKUP" 2>/dev/null
fi

echo "== 3/6 Remove FireFly data (messages; identity and settings are restored below unless asked otherwise)"
echo "   ... ($DATA, and $OLD_DATA from RetiCom)"
rm -rf "$DATA" "$OLD_DATA" && echo "   removed"

echo "== 4/6 Remove the app and its Python environment ($APP, and ~/reticom)"
rm -rf "$APP" "$HOME/reticom" && echo "   removed"

echo "== 5/6 Remove Ports launchers"
for p in /roms/ports/FireFly.sh /roms2/ports/FireFly.sh /roms/ports/RetiCom.sh /roms2/ports/RetiCom.sh; do
  [ -f "$p" ] && sudo rm -f "$p" && echo "   removed $p"
done

echo "== 6/6 Things FireFly doesn't own (reported, not touched unless asked)"
if pgrep -x rnsd >/dev/null || pgrep -f "bin/rnsd" >/dev/null; then
  echo "   ! rnsd is RUNNING. FireFly would attach to it and use ITS interfaces."
  echo "     Stop it for testing: pkill -f rnsd   (and check for a systemd service)"
fi
[ -d "$HOME/.reticulum" ] && echo "   ~/.reticulum exists (a separate Reticulum config). FireFly doesn't use it by default."
[ -d "$HOME/.nomadnetwork" ] && echo "   ~/.nomadnetwork exists: NomadNet is installed and uses the ~/.local rns."
USER_RNS=$(ls -d "$HOME"/.local/lib/python3*/site-packages/{rns,lxmf,RNS,LXMF}* 2>/dev/null | head -4)
if [ -n "$USER_RNS" ]; then
  if [ $PURGE_USER = 1 ]; then
    python3 -m pip uninstall -y --user --break-system-packages rns lxmf 2>/dev/null \
      || python3 -m pip uninstall -y --break-system-packages rns lxmf
    echo "   removed rns/lxmf from ~/.local"
  else
    echo "   rns/lxmf are installed in ~/.local (outside FireFly). The new installer ignores them."
    echo "     Remove them with --purge-user-rns if nothing else of yours uses them."
  fi
fi

KEY="$BACKUP/identity"; [ -f "$KEY" ] || KEY="$BACKUP/from-reticom/identity"
if [ $KEEP_ID = 1 ] && [ -f "$KEY" ]; then
  if [ "$(stat -c %s "$KEY")" = 64 ]; then
    mkdir -p "$DATA" && chmod 700 "$DATA"
    cp "$KEY" "$DATA/identity" && cp "$KEY" "$DATA/identity.bak"
    chmod 600 "$DATA"/identity*
    echo "   kept your identity (same address after reinstall)"
  else
    echo "   identity backup is damaged; a new identity will be created"
  fi
elif [ $KEEP_ID = 0 ]; then
  echo "   new identity requested: you will get a NEW address (old key is in $BACKUP)"
fi
SET="$BACKUP/settings.json"; [ -f "$SET" ] || SET="$BACKUP/from-reticom/settings.json"
if [ $KEEP_SETTINGS = 1 ] && [ -f "$SET" ]; then
  mkdir -p "$DATA" && chmod 700 "$DATA"
  cp "$SET" "$DATA/settings.json"
  echo "   kept your settings (radio, port, network links, display name)"
elif [ $KEEP_SETTINGS = 0 ]; then
  # Mark the reset so FireFly doesn't restore old settings from the backups on first start.
  mkdir -p "$DATA" && chmod 700 "$DATA"
  echo '{"restore_checked": true}' > "$DATA/settings.json"
  echo "   factory reset: settings back to defaults (old ones are in $BACKUP)"
fi
sync
echo
echo "Clean. Now run: bash $HERE/deploy/install.sh"
