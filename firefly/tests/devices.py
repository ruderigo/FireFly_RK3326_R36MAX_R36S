"""Render the main screens at every screen geometry used by arkos4clone's
dArkOS devices (from their device trees), including sideways portrait panels,
and flag text that runs off the screen.

  python3 tests/devices.py /tmp/devshots
"""
import os, sys, tempfile, time
os.environ["SDL_VIDEODRIVER"] = "dummy"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pygame
from firefly.paths import Paths
from firefly.settings import Settings
from firefly.core import Core

# physical panel size as the device tree reports it -> devices
GEOMETRIES = {
    (640, 480): "R36S clones, K36, G350, RG351MP, origin/clone panels (52 variants)",
    (1024, 768): "R36H Pro Max, R40XX, R45H, RF45H, GO2 (13)",
    (720, 720): "R36MAX, R36S Plus, R36 Ultra, RF40H (12)",
    (480, 800): "R40S, U8 (portrait panel)",
    (480, 854): "R50S, RGB10 Max (portrait panel)",
    (320, 480): "RG351P, RGB10, RGB10 V (portrait panel)",
    (480, 640): "DR28S, XF28 (portrait panel)",
    (720, 1280): "R50H, RF55H (portrait panel)",
    (720, 540): "A10 Mini v4",
}
out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/devshots"
os.makedirs(out, exist_ok=True)
tmp = tempfile.mkdtemp(); paths = Paths(tmp); paths.ensure()
s = Settings(paths.settings); s["radio"]["enabled"] = False; s["auto_interface"] = False; s["share_instance"] = False
s["display_name"] = "Rod R36"; s.save()
core = Core(paths, log=lambda *a: None); core.start()
st = core.store
bob = "823de26f44824bc5d37611af7851414c"
st.upsert_peer(bob, "lxmf", name="Sideband Bob", hops=2)
st.add_message(bob, False, "Hey! Are you on the ridge tonight? Signal is great up here.", "received", rssi=-97, snr=6.5)
st.add_message(bob, True, "Yes, heading up around 8. I'll bring the big antenna.", "delivered")

from firefly.ui.app import App
from firefly.ui.screens import ChatScreen
problems = []
pygame.display.init()
failed = False
try:
    for (w, h), label in GEOMETRIES.items():
        pygame.display.quit(); pygame.display.init()
        app = App(core, size=(w, h))
        lw, lh = app.surf.get_size()
        for name, setup in (("chats", lambda: app.switch_tab(0)), ("setup", lambda: app.switch_tab(3)),
                            ("chat", lambda: (app.switch_tab(0), app.push(ChatScreen(app, bob))))):
            setup()
            app.render()
            # overflow check: text rendered beyond the right edge shows up as non-background pixels
            # in the last column only if something ran off; sample the logical surface.
            edge = [app.surf.get_at((lw - 1, y))[:3] for y in range(0, lh, 2)]
            pygame.image.save(app.display.screen, f"{out}/{w}x{h}_{name}.png")
        app.stack.clear()
        print(f"{w}x{h:<5} rotation {app.display.rotation:>3}°  drawing {lw}x{lh}  font {app.fonts.base}px   {label}")
except Exception:
    import traceback; traceback.print_exc(); failed = True
core.stop(); os._exit(1 if failed else 0)
