#!/bin/bash
# Prints what FireFly needs to know about this handheld. Paste the output into
# a GitHub issue when reporting a problem or a newly tested device.
#   bash ~/firefly/deploy/device_report.sh
APP="${HOME:-/home/ark}/firefly"
echo "### FireFly device report ($(date +%F))"
echo "- model: $( { tr -d '\0' < /proc/device-tree/model; } 2>/dev/null || echo unknown)"
echo "- compatible: $( { tr '\0' ' ' < /proc/device-tree/compatible; } 2>/dev/null)"
echo "- screen (framebuffer): $(cat /sys/class/graphics/fb0/virtual_size 2>/dev/null | tr , x)"
echo "- system: $(. /etc/os-release 2>/dev/null; echo "$PRETTY_NAME"), kernel $(uname -r), $(uname -m)"
echo "- python: $(python3 -V 2>&1 | cut -d' ' -f2)"
[ -x "$APP/venv/bin/python" ] && echo "- firefly: $(cd "$APP" && "$APP/venv/bin/python" -c 'import firefly, RNS, LXMF, pygame; print(firefly.__version__, "/ rns", RNS.__version__, "/ lxmf", LXMF.__version__, "/ pygame", pygame.version.ver, "SDL", ".".join(map(str, pygame.get_sdl_version())))' 2>&1 | grep -v -i "hello from\|^pygame ")"
echo "- controllers:"; grep -E '^N: Name=' /proc/bus/input/devices 2>/dev/null | sed 's/^N: Name=/    /'
echo "- USB serial devices: $(ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null | tr '\n' ' ')"
echo "- USB serial drivers: $(lsmod 2>/dev/null | grep -oE '^(cp210x|ch341|cdc_acm|ftdi_sio)' | tr '\n' ' ')"
echo "- groups: $(id -Gn)"
if [ -f "$APP/launch.log" ]; then
  echo "- last launch:"; grep -E "video driver|device:|display reports|screen |rotation|FATAL|Error|core started|Unmapped" "$APP/launch.log" | tail -12 | sed 's/^/    /'
fi
