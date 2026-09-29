"""Entry point.

  python3 -m firefly                  window (desktop)
  python3 -m firefly --fullscreen     on the handheld
  python3 -m firefly --headless       no screen: log + a tiny command prompt (for SSH testing)
  python3 -m firefly --window 640x480 preview another screen size
  FIREFLY_HOME=/path                  use another data folder
"""
import argparse
import os
import sys
import threading
import time

from . import __version__
from .paths import default_paths


def headless(core):
    print("FireFly headless. Commands: peers | send <hash> <text> | chat <hash> | announce | sync | net | quit")
    seen = core.store.version

    def watch():
        nonlocal seen
        last_ids = set()
        while core.running:
            if core.store.version != seen:
                seen = core.store.version
                for c in core.store.conversations():
                    for m in core.store.messages(c["peer"], 5):
                        if not m["outgoing"] and m["id"] not in last_ids and m["unread"]:
                            last_ids.add(m["id"])
                            print(f"\n<< {c['name'] or c['peer'][:8]}: {m['content']}")
            time.sleep(0.5)
    threading.Thread(target=watch, daemon=True).start()
    for line in sys.stdin:
        cmd, _, rest = line.strip().partition(" ")
        if cmd == "quit":
            break
        elif cmd == "peers":
            for p in core.store.peers("lxmf"):
                print(f"{p['hash']}  {p['name'] or '?'}  hops={core.hops(p['hash'])}{'  STUMP' if p['stump'] else ''}")
        elif cmd == "send":
            h, _, text = rest.partition(" ")
            print("queued id", core.send(h, text))
        elif cmd == "chat":
            for m in core.store.messages(rest.strip(), 20):
                print(f"{'>>' if m['outgoing'] else '<<'} [{m['state']}] {m['content']}")
        elif cmd == "announce":
            core.announce(); print("announced")
        elif cmd == "sync":
            print("syncing" if core.sync() else "no propagation node")
        elif cmd == "net":
            for i in core.interface_stats().get("interfaces", []):
                print(i.get("name"), "UP" if i.get("status") else "DOWN", i.get("rxb"), i.get("txb"),
                      {k: i.get(k) for k in ("rssi", "snr", "airtime_short", "channel_load_short") if k in i})
        elif cmd:
            print("?")


def _log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


class Splash:
    """A window opened before anything slow, so the user never stares at a black screen,
    and a place to show a startup error instead of dying silently."""

    def __init__(self, fullscreen, size, rotation):
        import pygame
        self.pg = pygame
        pygame.display.init()
        pygame.font.init()
        _log(f"video driver: {pygame.display.get_driver()}  SDL {pygame.get_sdl_version()}")
        _log(f"device: {_device_model()}")
        from .ui.display import Display
        from .ui.theme import Fonts
        self.display = Display(fullscreen, size, rotation, log=_log)
        self.surf = self.display.surf
        self.fonts = Fonts(self.surf.get_height())

    def show(self, lines, color=(0xd9, 0x7a, 0x3a)):
        pg, s, f = self.pg, self.surf, self.fonts
        s.fill((0x1b, 0x15, 0x12))
        y = s.get_height() // 3
        for i, ln in enumerate(lines):
            font = f.mono_big if i == 0 else f.mono_small
            img = font.render(ln[:90], True, color if i == 0 else (0xec, 0xdf, 0xc8))
            s.blit(img, (20, y))
            y += font.get_linesize() + 4
        self.display.present()
        pg.event.pump()

    def wait_any_button(self, secs):
        pg = self.pg
        pg.joystick.init()
        _ = [pg.joystick.Joystick(i) for i in range(pg.joystick.get_count())]
        end = time.time() + secs
        while time.time() < end:
            for e in pg.event.get():
                if e.type in (pg.KEYDOWN, pg.JOYBUTTONDOWN, pg.QUIT):
                    return
            time.sleep(0.05)


def _device_model():
    for p in ("/proc/device-tree/model", "/sys/firmware/devicetree/base/model"):
        try:
            with open(p, "rb") as f:
                return f.read().rstrip(b"\0").decode(errors="replace")
        except OSError:
            pass
    return "unknown"


def main():
    ap = argparse.ArgumentParser(prog="firefly", description="Reticulum/LXMF messenger for handhelds")
    ap.add_argument("--fullscreen", action="store_true")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--window", default="720x720")
    ap.add_argument("--home")
    ap.add_argument("--rotate", help="auto, 0, 90, 180 or 270 (clockwise); overrides the setting")
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args()

    import faulthandler
    faulthandler.enable()
    _log(f"FireFly {__version__} starting, python {sys.version.split()[0]}")
    w, _, h = args.window.partition("x")
    size = (int(w), int(h))
    splash = None
    core = None
    try:
        if not args.headless:
            from .settings import Settings
            from .paths import default_paths as _dp
            rot = args.rotate or Settings(_dp(args.home, log=lambda *a: None).settings).get("screen_rotation", "auto")
            splash = Splash(args.fullscreen, size, rot)
            splash.show(["FireFly", "Starting Reticulum and LXMF…", "(first start creates your identity)"])
        from .core import Core
        core = Core(default_paths(args.home, log=_log), log=_log)
        _log("starting core")
        core.start()
        _log("core started")
        if args.headless:
            headless(core)
        else:
            from .ui.app import App
            App(core, display=splash.display, rotate_override=args.rotate).run()
    except Exception:
        import traceback
        tb = traceback.format_exc()
        _log("FATAL\n" + tb)
        if splash:
            last = [l for l in tb.strip().splitlines() if l.strip()][-6:]
            splash.show(["FireFly could not start", *last, "", "Details: ~/firefly/launch.log",
                         "Press any button to exit"], color=(0xe0, 0x7a, 0x5a))
            splash.wait_any_button(60)
    finally:
        if core:
            core.stop()
        _log("exit")
        sys.stdout.flush()
        os._exit(0)   # RNS keeps non-daemon threads; don't hang on exit


if __name__ == "__main__":
    main()
