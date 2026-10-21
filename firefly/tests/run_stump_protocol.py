"""Stump 1.0.0-beta.34 line protocol, as a FireFly over LXMF sees it.
   python3 tests/run_stump_protocol.py"""
import os, sys, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import RNS.vendor.umsgpack as msgpack
from firefly import stump
from firefly.paths import Paths
from firefly.settings import Settings
from firefly.core import Core

ok = True
def check(cond, what):
    global ok
    print(("  PASS " if cond else "  FAIL ") + what)
    ok = ok and bool(cond)

P = stump.parse_line
h = bytes(range(16))
check(stump.parse_beacon(msgpack.packb(["stump", "Beta A", "LaBuche", h])) == (h.hex(), "LaBuche", "Beta A"),
      "beacon with four items (older Stumps)")
check(stump.parse_beacon(msgpack.packb(["stump", "Beta A", "LaBuche", h, ["http://192.168.0.176/"]]))
      == (h.hex(), "LaBuche", "Beta A"), "beacon with a fifth item, the web addresses (beta.21+)")
check(P("→ #lora-mesh") == {"kind": "moved", "room": "lora-mesh"}, "landing in #lora-mesh")
check(P("→ #lxmf")["room"] == "lora-mesh", "the old name #lxmf is read as #lora-mesh")
check(P("= #lora-mesh — vous êtes déjà dans #lora-mesh")["room"] == "lora-mesh", "already in #lora-mesh")
r = P("⊘ #lora-mesh LoRa — salon réservé à la radio")
check(r["kind"] == "refused" and r["room"] == "lora-mesh" and r["tier"] == "LoRa", "refused by the new [LoRa] tier")
r = P("#lora-mesh ·3 [LoRa] radio room")
check(r["kind"] == "room" and r["tier"] == "LoRa" and r["topic"] == "radio room", "/rooms line with a [LoRa] tag")
r = P("#vip ·1 [minted] invite only")
check(r["tier"] == "minted", "/rooms line with [minted], as before")
r = P("<rod@LaBuche> salut")
check(r == {"kind": "msg", "nick": "rod@LaBuche", "text": "salut"}, "a line from another Stump's person (nick@stump)")
r = P("[DM] <rod@LaBuche>: psst")
check(r["kind"] == "dm" and r["author"] == "rod@LaBuche", "a DM across Stumps")
check(P("⧗ — ralentis : 3 lignes d'un coup, puis une toutes les 2 s")["kind"] == "too_fast", "⧗ for lines too fast")
items = stump.parse_message("<alice> hi", "#lxmf")
check(items[0]["room"] == "lora-mesh", "a batch titled #lxmf is filed under #lora-mesh")
items = stump.parse_message("<rod@B> yo", "#wifi-mesh")
check(items[0]["room"] == "wifi-mesh", "a #wifi-mesh batch (chained Stumps)")
check(stump.safe_for_stump("hello", "#lora-mesh") == ("hello", ""), "never sends a #lora-mesh title to a Stump")
check(stump.safe_for_stump("hi", "#WIFI-MESH")[1] == "", "...nor #wifi-mesh")
t, _ = stump.safe_for_stump("[DM>rod] <me> x")
check(not t.startswith("[DM>") and t.endswith("[DM>rod] <me> x"), "a line starting [DM> is defused")

print("⧗ marks the line the Stump didn't pass on")
tmp = tempfile.mkdtemp(); paths = Paths(tmp); paths.ensure()
s = Settings(paths.settings); s.save()
core = Core(paths, log=lambda *a: None)
node = "ab" * 16
core.stumps[node] = ("LaBuche", "Beta A")
old = core.store.add_message(node, True, "an hour ago", "delivered", ts=time.time() - 3600)
mid = core.store.add_message(node, True, "too fast", "delivered", ts=time.time() - 5)
core._mark_too_fast(node)
row = core.store.message(mid)
check(row["state"] == "failed" and "send it again" in row["reason"], f"newest line marked: {row['reason']!r}")
check(core.store.message(old)["state"] == "delivered", "older lines untouched")

class L:   # the delivery proof arriving after the ⧗
    method = 0
core._on_delivered(mid, L())
check(core.store.message(mid)["state"] == "failed", "a late delivery proof doesn't hide the ⧗")
print("ALL PASSED" if ok else "SOME FAILED")
sys.stdout.flush(); os._exit(0 if ok else 1)
