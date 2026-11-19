"""A Stump's rooms one at a time, as on its chat page and in the Android FireFly:
lines filed by room (the Stump's own "→ #room"), ←/→ between its rooms then its
private messages, one /join once the choice rests (not one per step), the
Stump's answer (there, or refused), replies to a DM, and the STUMPS tab.
   python3 tests/run_rooms.py"""
import os, sys, tempfile, time
os.environ["SDL_VIDEODRIVER"] = "dummy"; os.environ["SDL_AUDIODRIVER"] = "dummy"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from firefly.paths import Paths
from firefly.settings import Settings
from firefly.core import Core
from firefly import stump
ok = True
def check(c, w):
    global ok; print(("  PASS " if c else "  FAIL ") + w); ok = ok and bool(c)

# -- filing, without a screen ------------------------------------------------
msgs = [dict(id=1, outgoing=0, content="→ #lxmf", title=""),
        dict(id=2, outgoing=0, content="✓ ~Rod\n<alice> hi", title="#lxmf"),
        dict(id=3, outgoing=0, content="[DM] <bob>: psst", title=""),
        dict(id=4, outgoing=1, content="/join #vip", title=""),
        dict(id=5, outgoing=0, content="⊘ #vip minted — x", title=""),
        dict(id=6, outgoing=1, content="hello all", title=""),
        dict(id=7, outgoing=1, content="/msg bob ok", title=""),
        dict(id=8, outgoing=0, content="→ #jardin", title=""),
        dict(id=9, outgoing=1, content="bonjour le jardin", title=""),
        dict(id=10, outgoing=0, content="<zoe> salut", title="#jardin"),
        dict(id=11, outgoing=0, content="<alice> still here", title="#lora-mesh")]
filed = [(m["id"], r, p) for m, r, p in stump.file_messages(msgs)]
check((1, "lora-mesh", "room") in filed and (2, "lora-mesh", "room") in filed, "a room's lines and its landing line (#lxmf is #lora-mesh)")
check((3, None, "dm") in filed and (7, "lora-mesh", "dm") in filed, "DMs in, and /msg out, go to the private messages")
check((4, "lora-mesh", "room") in filed and (5, "lora-mesh", "room") in filed, "a refused /join stays where we were")
check((9, "jardin", "room") in filed and (10, "jardin", "room") in filed, "after → #jardin our lines are #jardin's")
check((11, "lora-mesh", "room") in filed, "a batch titled with another room is that room's, wherever we are")
ns = stump.NodeState()
ns.update(stump.parse_message("#main ·3 Bienvenue\n#lora-mesh ·2 [LoRa]\n#jardin ·1 potager", ""))
ns.room = "jardin"
check(stump.rooms_seen(stump.file_messages(msgs), ns) == ["main", "lora-mesh", "jardin"], "rooms: the Stump's own list, in its order")
check(ns.rooms["main"]["count"] == 3, "... with how many are in each")
ns2 = stump.NodeState(); ns2.set_rooms(["main", "quiz"])
check(ns2.room_order == ["main", "quiz"], "a Wi-Fi poll's room list")

# -- the screen ---------------------------------------------------------------
t = tempfile.mkdtemp(); p = Paths(t); p.ensure()
s = Settings(p.settings); s["radio"]["enabled"] = False; s["auto_interface"] = False; s["share_instance"] = False; s.save()
c = Core(p, log=lambda *a: None); c.start()
stp, bob, cab = "a8e7c0e088fc474c34360e91059be857", "823de26f44824bc5d37611af7851414c", "b0b0cafe00112233445566778899aabb"
c.store.upsert_peer(stp, "lxmf", name="LaBuche", hops=1, stump="LaBuche", stump_ver="1.0.0-beta.87")
c.store.upsert_peer(cab, "lxmf", name="LaBuche3", hops=3, stump="LaBuche3", stump_ver="1.0.0-beta.87")
c.store.upsert_peer(bob, "lxmf", name="Bob", hops=2)
c.stumps[stp] = ("LaBuche", "1.0.0-beta.87"); c.stumps[cab] = ("LaBuche3", "1.0.0-beta.87")
now = time.time()
for m in msgs:
    c.store.add_message(stp, bool(m["outgoing"]), m["content"], "delivered" if m["outgoing"] else "received",
                        ts=now - 1000 + m["id"] * 10, title=m["title"], unread=not m["outgoing"])
c.store.add_message(bob, False, "hi from Bob", "received", ts=now - 50, unread=True)
c.stump_state[stp] = ns
c.hops = lambda h: (c.store.peer(h) or {}).get("hops")      # (no network here: the stored hop counts)
sent = []
c.send = lambda peer, text, method="auto", title="": sent.append((peer, text))

import pygame
from firefly.ui.app import App
from firefly.ui.screens import ChatScreen, ChatsTab, StumpsTab
from firefly.ui.widgets import Compose
app = App(c, size=(640, 480))
check([type(x).__name__ for x in app.tabs][:2] == ["ChatsTab", "StumpsTab"], "a STUMPS tab after CHATS")
check([r["peer"] for r in app.tabs[0].rows()] == [bob], "CHATS: people only")
rows = app.tabs[1].rows()
check({r["peer"] for r in rows} == {stp, cab}, "STUMPS: every Stump known")
r = next(r for r in rows if r["peer"] == stp)
check(r["room"] == "jardin" and r["hops"] == 1 and r["unread"] > 0, "... with its room, hops and what's new")
check(app.tabs[0].badge() == 1 and app.tabs[1].badge() == r["unread"], "each tab counts its own unread")
app.switch_tab(1); app.render()

chat = ChatScreen(app, stp); app.push(chat); app.render()
ids = lambda: [m["id"] for m in chat._messages()]
check(chat.shown_view() == "jardin", "opens on the room the Stump has us in")
check(ids() == [8, 9, 10], "... and shows only that room's lines")
check(("←→", "rooms") in chat.hints, "hint: ←/→ for rooms")
check(chat.rooms() == ["main", "lora-mesh", "jardin", stump.DM_VIEW], "pills: its rooms, then the private messages")
chat.handle("left")
check(chat.shown_view() == "lora-mesh" and sorted(ids()) == [1, 2, 4, 5, 6, 11], "← shows #lora-mesh's lines at once")
chat.handle("left")
check(chat.shown_view() == "main" and not sent, "← again: #main, and nothing sent while choosing")
chat.pending = (chat.pending[0], time.time() - 2); app.render()
check(sent == [(stp, "/join #main")], "one /join once the choice rests")
check(chat.joining and chat.joining[0] == "main", "... waiting for the Stump's word")
ns.update(stump.parse_message("→ #main", ""))
app.render()
check(chat.joining is None and chat.view is None and chat.shown_view() == "main", "the Stump has us in #main: done")
sent.clear()
chat.handle("right"); chat.pending = (chat.pending[0], time.time() - 2); app.render()
ns.update(stump.parse_message("⊘ #lora-mesh minted — verified identity first", ""))
app.render()
check(chat.shown_view() == "main" and "verified identity first" in app.toast_text, "refused: back where it has us, and why")
chat.handle("left")
check(chat.shown_view() == stump.DM_VIEW and sorted(ids()) == [3, 7], "← from the first room: the private messages")
chat.pending = None
check(("A", "reply") in chat.hints, "hint: A replies to a DM")
chat.sel_id = 3; chat.handle("a")
check(isinstance(app.current, Compose) and "bob" in app.current.title, "A on bob's DM: write to bob")
sent.clear(); app.current.on_done("on my way"); app.pop()
check(sent == [(stp, "/msg bob on my way")], "... sent as /msg bob")
chat.handle("right")
check(chat.shown_view() == "main", "→ from the private messages: back to the first room")
for size in ((640, 480), (720, 720)):
    a2 = App(c, size=size); a2.push(ChatScreen(a2, stp)); a2.render(); a2.switch_tab(1); a2.render()
check(True, "draws at 640x480 and 720x720")
c.stop()
print("all passed" if ok else "FAILURES")
os._exit(0 if ok else 1)
