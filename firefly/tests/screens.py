"""Render every screen headlessly to PNG with sample data (layout check)."""
import os, sys, tempfile, time
os.environ["SDL_VIDEODRIVER"] = "dummy"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from firefly.paths import Paths
from firefly.settings import Settings
from firefly.core import Core

size = tuple(int(x) for x in (sys.argv[1] if len(sys.argv) > 1 else "720x720").split("x"))
out = sys.argv[2] if len(sys.argv) > 2 else "/tmp/shots"
os.makedirs(out, exist_ok=True)
tmp = tempfile.mkdtemp()
paths = Paths(tmp); paths.ensure()
s = Settings(paths.settings); s["auto_interface"] = False; s["share_instance"] = False
s["display_name"] = "Rod R36"; s.save()
core = Core(paths, log=lambda *a: None); core.start()
# A simulated RNode, so NETWORK shows the radio online as it would with a real board.
sys.path.insert(0, os.path.dirname(__file__))
from fake_rnode import FakeRNode
_rnode = FakeRNode(band=(902e6, 928e6), fw=(1, 82))
core.radio.port_lister = lambda: [_rnode.port]
core.radio.search_now()
_t = time.time()
while core.radio.status.state != "online" and time.time() - _t < 20:
    time.sleep(0.2)
time.sleep(1.5)
# Staging for the README only: show a real device's port name, and the hop
# counts stored for the sample peers (there is no real network here).
core.radio.status.port = "/dev/ttyACM0"
core.hops = lambda h: (core.store.peer(h) or {}).get("hops")
core.settings["auto_interface"] = True
st = core.store
bob, stp, anon = "823de26f44824bc5d37611af7851414c", "a8e7c0e088fc474c34360e91059be857", "5b1c0de2f33a4d1e9a6b7c8d9e0f1a2b"
st.upsert_peer(bob, "lxmf", name="Sideband Bob", hops=2)
st.upsert_peer(stp, "lxmf", name="LaBuche", hops=1, stump="LaBuche", stump_ver="1.4")
core.stumps[stp] = ("LaBuche", "1.4")
from firefly import stump as _stump
core.stump_state[stp] = _stump.NodeState(); core.stump_state[stp].room = "lxmf"
st.upsert_peer(anon, "lxmf", hops=4)
st.upsert_peer("c0ffee00c0ffee00c0ffee00c0ffee00", "propagation", name="Montagne PN", hops=3, extra="on")
now = time.time()
st.add_message(bob, False, "Hey! Are you on the ridge tonight? Signal is great up here.", "received", ts=now-600, rssi=-97, snr=6.5)
st.add_message(bob, True, "Yes, heading up around 8. I'll bring the big antenna.", "delivered", ts=now-560)
st.add_message(bob, False, "Perfect ✓ see you there", "received", ts=now-500, rssi=-101, snr=3.0)
st.add_message(bob, False, "", "received", ts=now-120, rssi=-99, snr=4.5,
               audio_mode=0x04, audio_path="/nonexistent.c2", audio_secs=12.4)
st.add_message(bob, True, "Leaving now", "sent", ts=now-60)
st.add_message(bob, True, "Can you hear me?", "failed", ts=now-30).__class__
st.update_message(5, reason="not delivered")
st.add_message(anon, False, "photo from the trailhead", "received", ts=now-7200, attachments="image", verified=False, unread=True)
st.add_message(stp, False, "→ #lxmf", "received", ts=now-330, unread=True)
st.add_message(stp, False, "✓ ~Rod\n<alice> welcome, mesh friend!\n* alice waves", "received", ts=now-320, title="#lxmf", unread=True)
st.add_message(stp, False, "[DM] <bob>: psst, bring snacks", "received", ts=now-300, unread=True)
st.add_message(stp, True, "/join #vip", "delivered", ts=now-200)
st.add_message(stp, False, "⊘ #vip minted — ce salon exige une identité vérifiée -- envoyez /auth", "received", ts=now-190, unread=True)

import pygame
from firefly.ui.app import App
from firefly.ui.screens import ChatScreen
from firefly.ui.widgets import Compose, Menu
app = App(core, size=size)
def shot(name):
    app.render(); pygame.image.save(app.surf, f"{out}/{name}.png")
for i, n in enumerate(["chats", "peers", "network", "setup"]):
    app.switch_tab(i); shot(n)
app.switch_tab(0); app.push(ChatScreen(app, bob)); shot("chat_bob")
app.stack.clear(); app.push(ChatScreen(app, stp)); shot("chat_stump")
app.handle = None
app.current.handle("y"); shot("menu_stump")
app.stack.clear(); app.push(ChatScreen(app, bob))
c = Compose(app, "To Sideband Bob", lambda t: None, initial="Bonjour! On se voit au sommet à 20h ?"); app.push(c); shot("compose")
core.stop(); os._exit(0)
