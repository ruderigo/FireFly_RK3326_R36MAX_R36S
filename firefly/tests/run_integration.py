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
         for n, p, x in (("bob", 47501, []), ("stump", 47502, ["--stump"]))]
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
print("     method:", core.store.message(mid)["method"])
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
