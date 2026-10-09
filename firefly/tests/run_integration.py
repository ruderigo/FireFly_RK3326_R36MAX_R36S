"""End-to-end: FireFly's Core talks LXMF to an ordinary LXMF peer and to a fake
Stump node, over TCP on localhost (a stand-in for the LoRa link).

  python3 tests/run_integration.py
"""
import os, shutil, subprocess, sys, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from firefly.paths import Paths
from firefly.settings import Settings
from firefly.core import Core
from firefly import stump

here = os.path.dirname(os.path.abspath(__file__))
tmp = tempfile.mkdtemp(prefix="firefly-it-")
peers = [subprocess.Popen([sys.executable, os.path.join(here, "peer.py"), os.path.join(tmp, n), str(p)] + x,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
         for n, p, x in (("bob", 47501, []), ("stump", 47502, ["--stump", "--quiet-pn"]))]
addrs = []
for p in peers:
    line = p.stdout.readline()
    while "PEER ready" not in line:
        line = p.stdout.readline()
    addrs.append(line.split()[2])
bob, node = addrs
print("bob", bob, "stump", node)

paths = Paths(os.path.join(tmp, "me"))
paths.ensure()
s = Settings(paths.settings)
s["radio"]["enabled"] = False
s["auto_interface"] = False
s["share_instance"] = False
s["tcp_peers"] = ["127.0.0.1:47501", "127.0.0.1:47502"]
s["display_name"] = "R36 Tester"
s["log_level"] = 2
s.save()

core = Core(paths)
core.start()
ok = True

def wait(cond, secs, what):
    global ok
    t = time.time()
    while time.time() - t < secs:
        if cond():
            print(f"  PASS {what} ({time.time()-t:.1f}s)")
            return True
        time.sleep(0.2)
    print(f"  FAIL {what}")
    ok = False
    return False

wait(lambda: (core.store.peer(bob) or {}).get("name") == "Bob", 20, "heard Bob's announce with display name")
wait(lambda: core.is_stump(node), 20, "recognised the Stump node from its stump.node beacon")
mid = core.send(bob, "Hello from the R36MAX ✓ ça marche")
wait(lambda: core.store.message(mid)["state"] == "delivered", 30, "message to Bob delivered (proof received)")
print("     method:", core.store.message(mid)["method"], "state:", core.store.message(mid)["state"], "reason:", core.store.message(mid)["reason"])
wait(lambda: any(m["content"].startswith("echo: Hello") for m in core.store.messages(bob) if not m["outgoing"]),
     30, "received Bob's reply")
wait(lambda: core.store.unread_total() >= 1, 5, "reply counted as unread")
wait(lambda: len(core.store.conversations()) >= 1, 5, "conversation list populated")

core.start_stump_auth(node)
wait(lambda: core.auth_state(node).state == stump.AuthSession.OK, 45, "Stump /auth handshake -> AUTH-OK")
sess = core.auth_state(node)
print("     node says identity:", sess.identity_hash, " ours:", core.identity.hash.hex(),
      " challenge RTT %.1fs" % (sess.rtt or -1))
if sess.identity_hash != core.identity.hash.hex():
    print("  FAIL identity hash mismatch"); ok = False

# Stump protocol: landing room, titled room batches, reply tokens
core.send(node, "hello room")
wait(lambda: (core.stump_state.get(node) and core.stump_state[node].room) == "lxmf", 30,
     "Stump: '→ #lxmf' tells FireFly which room it landed in")
wait(lambda: any(m["title"] == "#lxmf" for m in core.store.messages(node) if not m["outgoing"]), 20,
     "Stump: room batch carries its room as the LXMF title")
core.send(node, "/join #vip")
wait(lambda: core.stump_state[node].refused and core.stump_state[node].refused[:2] == ("vip", "minted"), 30,
     "Stump: tier refusal '⊘ #vip minted' understood (sentence in French)")
core.send(node, "/frob")
wait(lambda: any("? /frob" in m["content"] for m in core.store.messages(node) if not m["outgoing"]), 30,
     "Stump: unknown-command token received")
from firefly import stump as _st
print("     parsed:", [i["kind"] for m in core.store.messages(node) if not m["outgoing"]
                        for i in _st.parse_message(m["content"], m["title"] or "")])

# Voice DM relayed by the Stump: '[DM] <bob>: ♪ 5.0 s' with an Opus note attached
core.send(node, "voice dm?")
wait(lambda: any(m["audio_mode"] == 16 for m in core.store.messages(node)), 30, "Stump voice DM arrives with its note")
vdm = [m for m in core.store.messages(node) if m["audio_mode"] == 16][0]
from firefly import voice as _v
print("     voice DM:", vdm["content"], "| length", _v.label(_v.row_ms(vdm)))
check_items = _st.parse_message(vdm["content"])
wait(lambda: check_items and check_items[0].get("voice") == "5.0 s" and _v.label(_v.row_ms(vdm)) == "5.0 s", 1,
     "  ...understood as a voice DM from bob, 5.0 s, matching the node's own label")
wait(lambda: any(i["kind"] == "too_fast" for m in core.store.messages(node) if not m["outgoing"]
                 for i in _st.parse_message(m["content"])), 20, "Stump '⧗' (too fast) token understood")

# The Stump's propagation node: on, never announced. FireFly computes its address and asks.
pn_hex = [h for h in core.stump_pn][0] if core.stump_pn else None
wait(lambda: bool(core.stump_pn), 15, "Stump's propagation-node address computed from its identity")
wait(lambda: any(p["stump"] for p in core.store.peers("propagation")), 30,
     "  ...its path requested and the node found without waiting for an announce")
wait(lambda: core.propagation_node() in core.stump_pn, 20, "  ...and chosen as this FireFly's propagation node")

big = "x" * 600   # too big for one packet: LXMF must switch to a link by itself
mid2 = core.send(bob, big)
wait(lambda: core.store.message(mid2)["state"] == "delivered", 40, "600-char message delivered over a link")
print("     method:", core.store.message(mid2)["method"])

bogus = "00" * 16
mid3 = core.send(bogus, "nobody home")
wait(lambda: core.store.message(mid3)["state"] == "failed", 40, "message to unknown address fails cleanly")
print("     reason:", core.store.message(mid3)["reason"])

core.stop()
for p in peers:
    p.terminate()
    out = p.stdout.read()
    print("---", " ".join(l for l in out.splitlines() if l.startswith("PEER got"))[:600])
shutil.rmtree(tmp, ignore_errors=True)
print("ALL PASSED" if ok else "SOME FAILED")
sys.stdout.flush(); os._exit(0 if ok else 1)
