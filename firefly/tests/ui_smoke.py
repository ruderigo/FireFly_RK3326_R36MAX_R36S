"""Drive every screen with thousands of random button presses; any exception fails."""
import os, random, sys, tempfile, time, traceback
os.environ["SDL_VIDEODRIVER"] = "dummy"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from firefly.paths import Paths
from firefly.settings import Settings
from firefly.core import Core
tmp = tempfile.mkdtemp(); paths = Paths(tmp); paths.ensure()
s = Settings(paths.settings); s["radio"]["enabled"] = False; s["auto_interface"] = False; s["share_instance"] = False; s.save()
core = Core(paths, log=lambda *a: None); core.start()
core.store.upsert_peer("823de26f44824bc5d37611af7851414c", "lxmf", name="Bob", hops=1)
core.store.upsert_peer("a8e7c0e088fc474c34360e91059be857", "lxmf", name="Stump", stump="LaBuche")
core.stumps["a8e7c0e088fc474c34360e91059be857"] = ("LaBuche", "1")
core.store.add_message("823de26f44824bc5d37611af7851414c", False, "hi", "received", unread=True)
from firefly.ui.app import App
app = App(core, size=(640, 480))
app.restart = lambda: app.toast("restart (stubbed)")
app.quit = lambda: None
acts = ["up", "down", "left", "right", "a", "b", "x", "y", "l1", "r1", "start"]
random.seed(1)
n = 0
failed = False
try:
    for i in range(6000):
        a = random.choice(acts)
        app.action(a); app.select_held = False
        if i % 7 == 0:
            app.current.text_input("é✓x") if hasattr(app.current, "text_input") else None
        if i % 25 == 0:
            app.render()
        n += 1
    print("OK", n, "actions; sent messages:", sum(1 for c in core.store.conversations() for m in core.store.messages(c["peer"]) if m["outgoing"]))
except Exception:
    traceback.print_exc(); print("FAILED after", n, "actions, screen", type(app.current).__name__)
    failed = True
core.stop(); os._exit(1 if failed else 0)
