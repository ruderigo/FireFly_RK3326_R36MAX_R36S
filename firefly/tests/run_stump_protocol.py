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

print("Stump 1.0.0-beta.35 to beta.46")
import RNS
real = RNS.Identity()
real_lxmf = RNS.Destination.hash(real, "lxmf", "delivery")
caps = {"p": 2, "r": "1.0.0-beta.46", "m": "hybrid", "rad": True, "b": "x1"}
info = stump.parse_beacon(msgpack.packb(["stump", "Beta A", "LaBuche", real_lxmf, [], caps]))
check(info == (real_lxmf.hex(), "LaBuche", "1.0.0-beta.46"), "sixth item: the release is shown instead of the label")
check(stump.parse_beacon(msgpack.packb(["stump", "Beta A", "X", real_lxmf, [], {"r": 5}]))[2] == "Beta A",
      "a capabilities map with odd values is ignored")
seen = []
hd = stump.BeaconHandler(lambda *a: seen.append(a))
hd.received_announce(b"", real, msgpack.packb(["stump", "Beta A", "LaBuche", real_lxmf]))
check(len(seen) == 1, "a beacon naming its own identity's address is taken")
hd.received_announce(b"", RNS.Identity(), msgpack.packb(["stump", "Beta A", "Fake", real_lxmf]))
check(len(seen) == 1, "a forged beacon (someone else's address) is ignored")
check(P("#482193 Marché samedi") == {"kind": "notice", "id": "482193", "title": "Marché samedi"}, "/board line")
check(P("#482193 Vente: vélo")["kind"] == "notice", "a notice title with ': ' isn't taken for a /names line")
check(P("✓ #482193") == {"kind": "posted", "id": "482193"}, "/post answer")
check(P("✓ rod")["kind"] == "join", "'✓ nick' is still a join")
r = P("⧗ — the radio has been down for 3 min: your message will go out when it's back (kept up to an hour)")
check(r["kind"] == "too_fast" and "kept up to an hour" in r["text"], "⧗ radio-down keeps its sentence for the screen")

print("⧗ no longer fails a line (it may only be waiting for the radio)")
tmp = tempfile.mkdtemp(); paths = Paths(tmp); paths.ensure()
s = Settings(paths.settings); s.save()
core = Core(paths, log=lambda *a: None)
check(not hasattr(core, "_mark_too_fast"), "no automatic 'send it again'")
print("ALL PASSED" if ok else "SOME FAILED")
sys.stdout.flush(); os._exit(0 if ok else 1)
