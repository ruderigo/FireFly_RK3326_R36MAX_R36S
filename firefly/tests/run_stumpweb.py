"""Chat with a Stump over Wi-Fi, against a small fake of its web API (the real one:
tests/run_real_stump.py).   python3 tests/run_stumpweb.py"""
import json, os, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import RNS
from firefly import stumpweb, stump
from firefly.paths import Paths
from firefly.settings import Settings
from firefly.core import Core

ok = True
def check(cond, what):
    global ok
    print(("  PASS " if cond else "  FAIL ") + what, flush=True)
    ok = ok and bool(cond)
def wait(fn, secs):
    t = time.time()
    while time.time() - t < secs:
        if fn(): return True
        time.sleep(0.1)
    return False

node_id = RNS.Identity()
NODE_LX = RNS.Destination.hash(node_id, "lxmf", "delivery").hex()
state = {"nonce": None, "greeted": False, "msgs": [], "next": 10, "sent": [], "lie": False, "down": False}

class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _json(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if state["down"]:
            return self._json(500, {})
        if self.path.startswith("/hello"):
            state["nonce"] = os.urandom(16).hex()
            signer = RNS.Identity() if state["lie"] else node_id
            return self._json(200, {"stump": "Fake", "lxmf": NODE_LX, "nonce": state["nonce"], "hello": "required",
                                    "pub": signer.get_public_key().hex(),
                                    "sig": signer.sign((state["nonce"] + NODE_LX).encode()).hex()})
        if self.path.startswith("/rrc/poll"):
            if not state["greeted"]:
                return self._json(200, {"hello": "required"})
            since = int(self.path.split("since=")[1].split("&")[0])
            return self._json(200, {"room": "lora-mesh", "nick": "R36-Tester", "hello": "done",
                                    "messages": [m for m in state["msgs"] if m["id"] > since and m["kind"] != "dm"],
                                    "dms": [m for m in state["msgs"] if m["id"] > since and m["kind"] == "dm"]})
        self._json(404, {})
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        if self.path == "/hello":
            d = json.loads(body)
            ident = RNS.Identity(create_keys=False); ident.load_public_key(bytes.fromhex(d["pub"]))
            if not ident.validate(bytes.fromhex(d["sig"]), state["nonce"].encode()):
                return self._json(403, {"hello": "required", "error": "auth"})
            state["greeted"] = True
            return self._json(200, {"hello": "done", "nick": d["name"], "lxmf": "x", "prefer": d["prefer"]})
        if self.path == "/rrc/send":
            if not state["greeted"]:
                return self._json(403, {"error": "hello_required"})
            line = body.decode()
            state["sent"].append(line)
            if line.startswith("/join"):
                return self._json(200, {"replies": ["→ #" + line.split("#")[1]], "room": line.split("#")[1]})
            return self._json(200, {"replies": [], "room": None})
        self._json(404, {})

srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}/"

def add(kind, nick, body):
    state["next"] += 1
    state["msgs"].append({"id": state["next"], "ts": time.time(), "nick": nick, "body": body, "kind": kind})

add("msg", "alice", "old scrollback line")
add("dm", "bob", "a DM waiting for you")

print("pieces")
card = {"lxmf": NODE_LX, "nonce": "ab" * 16}
card.update(pub=node_id.get_public_key().hex(), sig=node_id.sign((card["nonce"] + NODE_LX).encode()).hex())
check(stumpweb.verify_stump(card, NODE_LX), "a Stump's signed card is accepted")
check(not stumpweb.verify_stump(card, "00" * 16), "...not for another address")
check(not stumpweb.verify_stump({**card, "sig": "00" * 64}, NODE_LX), "...not with a bad signature")
check(stumpweb.to_lines({"kind": "dm", "nick": "bob", "body": "hi"}) == ("[DM] <bob>: hi", ""), "DM in the line form")
check(stumpweb.to_lines({"kind": "msg", "nick": "rod@B", "body": "yo"})[0] == "<rod@B> yo", "room line in the line form")

print("a session")
tmp = tempfile.mkdtemp(); paths = Paths(tmp); paths.ensure()
s = Settings(paths.settings); s["auto_interface"] = False; s["share_instance"] = False; s["log_level"] = 2
s["display_name"] = "R36 Tester"; s.save()
from firefly import lan
lan.LanManager.start = lambda self: None            # we hand it the Stump ourselves
core = Core(paths, log=lambda *a: None); core.start()
info = {"name": "Fake", "lxmf": NODE_LX, "release": "1.0.0-beta.51", "http": [base], "here": base, "seen": time.time()}
core.sync_web({NODE_LX: info})
check(core.is_stump(NODE_LX), "a Stump met only on the network counts as a Stump")
w = core.web[NODE_LX]
check(wait(lambda: w.online, 15), "greeted (/hello both ways)")
check(wait(lambda: any("a DM waiting for you" in m["content"] for m in core.store.messages(NODE_LX)), 10),
      "a DM waiting at the Stump arrives on the first poll")
check(not any("old scrollback" in m["content"] for m in core.store.messages(NODE_LX)), "the room's scrollback isn't imported")
add("msg", "carol", "new room line")
state["msgs"][-1]["ts"] = 86400.0                      # a Stump whose clock isn't set (1970)
add("msg", "R36-Tester", "my own line echoed")
check(wait(lambda: any(m["content"] == "<carol> new room line" and m["title"] == "#lora-mesh"
                       for m in core.store.messages(NODE_LX)), 10), "new room lines arrive, filed under their room")
check(not any("my own line echoed" in m["content"] for m in core.store.messages(NODE_LX)), "own lines aren't shown twice")
carol = [m for m in core.store.messages(NODE_LX) if "new room line" in m["content"]][0]
check(time.time() - carol["ts"] < 60, "filed by arrival, not by the Stump's unset clock")
check(core.store.messages(NODE_LX)[-1]["id"] == carol["id"], "...so it is the newest line in the chat")
mid = core.send(NODE_LX, "hello over Wi-Fi")
check(wait(lambda: core.store.message(mid)["state"] == "delivered", 10) and "hello over Wi-Fi" in state["sent"],
      "sending goes over Wi-Fi")
core.send(NODE_LX, "/join #cafe")
check(wait(lambda: core.stump_state[NODE_LX].room == "cafe", 10), "/join's answer moves the room")
n = len(core.store.messages(NODE_LX)); time.sleep(5)
check(len(core.store.messages(NODE_LX)) == n, "nothing duplicated across polls")

print("when it goes wrong")
state["greeted"] = False
mid = core.send(NODE_LX, "after the Stump restarted")
check(wait(lambda: core.store.message(mid)["state"] == "delivered", 15), "the Stump forgot us: greeted again, then sent")
state["down"] = True
w.state = w.LOST
mid = core.send(NODE_LX, "while the Wi-Fi is down")
time.sleep(1)
check(core.store.message(mid)["method"] != "wifi", "Wi-Fi lost: the line goes the LoRa way instead")
state["down"] = False
core.sync_web({})
check(NODE_LX not in core.web, "the Stump left the network: its session stops")
state["lie"] = True; state["greeted"] = False
core.sync_web({NODE_LX: info})
w2 = core.web[NODE_LX]
check(wait(lambda: w2.state == w2.REFUSED, 10) and not state["greeted"],
      f"a Stump that can't prove who it is gets nothing ({w2.detail})")
print("old rows from 0.9.1, and how the chat shows a room")
P2 = "ef" * 16
a = core.store.add_message(P2, False, "<x> first", "received", ts=time.time() - 50, title="#lora-mesh")
b2 = core.store.add_message(P2, False, "<x> second (Stump clock off)", "received", ts=1000.0, title="#lora-mesh")
c = core.store.add_message(P2, False, "<x> third (Stump clock off)", "received", ts=1001.0, title="#lora-mesh")
check(core.store.repair_stump_times([P2]) == 2, "two misfiled lines found")
order = [m["id"] for m in core.store.messages(P2)]
check(order == [a, b2, c], "back in the order they arrived")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
from firefly.ui.app import App
from firefly.ui import screens
core.stumps[P2] = ("X", "1")
core.store.add_message(P2, False, "<y> in main", "received", title="#main")
core.store.add_message(P2, False, "<y> lora again", "received", title="#lxmf")
app = App(core, size=(640, 480))
seen = []
orig = screens.ChatScreen._layout
screens.ChatScreen._layout = lambda self, m, f, maxw, is_stump, room_label=True, part=None: (
    seen.append((m["content"], room_label)), orig(self, m, f, maxw, is_stump, room_label, part))[1]
chat = screens.ChatScreen(app, P2); app.push(chat); app.render()
check(seen == [("<y> in main", False)], f"one room at a time (#main, no room labels needed): {seen}")
seen.clear(); chat.view = "lora-mesh"; app.render()
screens.ChatScreen._layout = orig
check([t for t, _ in seen] == ["<x> first", "<x> second (Stump clock off)", "<x> third (Stump clock off)",
                               "<y> lora again"], f"#lora-mesh's lines, #lxmf's included, in order: {seen}")
core.stop(); srv.shutdown()
print("ALL PASSED" if ok else "SOME FAILED")
sys.stdout.flush(); os._exit(0 if ok else 1)
