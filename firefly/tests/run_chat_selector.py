"""The chat selector: reach and play any voice note (not only the newest),
message details, the view following the selection, and new arrivals.
   python3 tests/run_chat_selector.py"""
import os, sys, tempfile, time
os.environ["SDL_VIDEODRIVER"] = "dummy"; os.environ["SDL_AUDIODRIVER"] = "dummy"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..")); sys.path.insert(0, os.path.dirname(__file__))
from firefly.paths import Paths
from firefly.settings import Settings
from firefly.core import Core
from firefly import voice
import LXMF, pygame
ok = True
def check(c, w):
    global ok; print(("  PASS " if c else "  FAIL ") + w); ok = ok and bool(c)
t = tempfile.mkdtemp(); p = Paths(t); p.ensure()
s = Settings(p.settings); s["radio"]["enabled"] = False; s["auto_interface"] = False; s["share_instance"] = False; s.save()
c = Core(p, log=lambda *a: None); c.start()
bob = "823de26f44824bc5d37611af7851414c"
c.store.upsert_peer(bob, "lxmf", name="Bob", hops=1)
vec = open(os.path.join(os.path.dirname(__file__), "data", "kristoff_1200.bit"), "rb").read()
ogg = open(os.path.join(os.path.dirname(__file__), "data", "kristoff_opusenc_8k.ogg"), "rb").read()
now = time.time(); ids = {}
def note(name, mode, data, ts):
    path = voice.save(p.audio, name, mode, data)
    return c.store.add_message(bob, False, "", "received", ts=ts, audio_mode=mode, audio_path=path,
                               audio_secs=voice.duration(mode, data))
ids["oldest_note"] = note("n1", LXMF.AM_CODEC2_1200, vec, now - 900)
for i in range(6):
    c.store.add_message(bob, i % 2 == 0, f"message number {i} with some words to wrap across the bubble width", "delivered" if i % 2 == 0 else "received", ts=now - 800 + i * 60)
ids["middle_note"] = note("n2", LXMF.AM_OPUS_OGG, ogg, now - 300)
ids["failed"] = c.store.add_message(bob, True, "Can you hear me?", "failed", ts=now - 200)
c.store.update_message(ids["failed"], reason="not delivered", method="opportunistic")
ids["newest_note"] = note("n3", LXMF.AM_CODEC2_1200, vec, now - 100)

from firefly.ui.app import App
from firefly.ui.screens import ChatScreen
app = App(c, size=(640, 480))
chat = ChatScreen(app, bob); app.push(chat); app.render()
check(chat._selected(chat._messages())["id"] == ids["newest_note"], "starts on the newest message")
check(("A", "play") in chat.hints, "hint shows A = play on a voice note")
for _ in range(9): app.action("up")
app.render()
check(chat._selected(chat._messages())["id"] == ids["oldest_note"], "↑ reaches the oldest voice note")
check(chat.offset > 0, f"the view followed the selection up ({chat.offset}px)")
pygame.image.save(app.surf, "/tmp/sel_oldest.png")
app.action("a")
deadline = time.time() + 10
while app.player._ready is None and app.player.playing_id is not None and time.time() < deadline: time.sleep(0.05)
app.player.pump()
check(app.player.playing_id == ids["oldest_note"] and app.player.busy(), "A plays the oldest note (not just the newest)")
app.render(); pygame.image.save(app.surf, "/tmp/sel_playing.png")
app.action("a")
check(not app.player.busy(), "A again stops it")
for _ in range(7): app.action("down")
check(chat._selected(chat._messages())["id"] == ids["middle_note"], "↓ moves to the Opus note in the middle")
app.action("down"); app.action("a")
check(type(app.current).__name__ == "Info", "A on a text message opens its details")
details = "\n".join(app.current.lines)
check("Status: failed (opportunistic)" in details and "Reason: not delivered" in details, "details show status and reason")
app.render(); pygame.image.save(app.surf, "/tmp/sel_details.png")
app.action("b"); app.action("r1")
check(chat.sel_id is None and chat._selected(chat._messages())["id"] == ids["newest_note"], "R1 jumps back to the newest")
newer = c.store.add_message(bob, False, "a new one arrives", "received")
app.render()
check(chat._selected(chat._messages())["id"] == newer, "at the newest, a new message becomes the selection")
for _ in range(2): app.action("up")
c.store.add_message(bob, False, "and another", "received"); app.render()
check(chat._selected(chat._messages())["id"] != newer and chat.sel_id is not None, "reading older ones, a new arrival doesn't move you")
c.stop()
print("ALL PASSED" if ok else "SOME FAILED"); sys.stdout.flush(); os._exit(0)
