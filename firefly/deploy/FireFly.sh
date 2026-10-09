#!/bin/bash
# FireFly launcher for ArkOS-family firmware (EmulationStation "Ports").
# The app lives in /home/ark/firefly; this script only starts it, so it can
# sit on the exFAT /roms partition. Output goes to /home/ark/firefly/launch.log.

APP="${HOME:-/home/ark}/firefly"
[ -d "$APP" ] || APP="/home/ark/firefly"
LOG="$APP/launch.log"
cd "$APP" || exit 1

# A copy left running (or an old RetiCom) would hold the radio's serial port.
if pgrep -f "python.* -m (firefly|reticom)" >/dev/null; then
  pkill -f "python.* -m (firefly|reticom)"; sleep 2
  echo "closed a FireFly/RetiCom copy that was still running" >> "$LOG.pre"
fi

{
  echo "=== $(date)  user=$(id -un) groups=$(id -Gn)"
  echo "tty: $(tty 2>/dev/null)  DISPLAY=${DISPLAY:-none}  SDL_VIDEODRIVER=${SDL_VIDEODRIVER:-unset}"
  ls -l /dev/dri/ 2>&1 | sed 's/^/  /'
} > "$LOG"
[ -f "$LOG.pre" ] && cat "$LOG.pre" >> "$LOG" && rm -f "$LOG.pre"

# Use the firmware's controller database if it ships one.
for db in /opt/inttools/gamecontrollerdb.txt /usr/share/gamecontrollerdb.txt; do
  [ -f "$db" ] && export SDL_GAMECONTROLLERCONFIG_FILE="$db" && echo "controller db: $db" >> "$LOG" && break
done
export PYTHONUNBUFFERED=1
export PYTHONNOUSERSITE=1       # use the app's own rns/lxmf, not ~/.local

./venv/bin/python -X faulthandler -m firefly --fullscreen >> "$LOG" 2>&1
echo "=== exit code $?" >> "$LOG"
sync
printf "\033c" > /dev/tty1 2>/dev/null
