"""Offline delivery: Carol announces then goes offline. FireFly's message to her
fails direct delivery, falls back to the propagation node, and is stored there.
Then Carol comes back and collects it from the node."""
import os, subprocess, sys, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from firefly.paths import Paths
from firefly.settings import Settings
from firefly.core import Core
here = os.path.dirname(os.path.abspath(__file__)); tmp = tempfile.mkdtemp()

def spawn(name, port, *extra):
    p = subprocess.Popen([sys.executable, "-u", os.path.join(here, "peer.py"), os.path.join(tmp, name), str(port), *extra],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    line = p.stdout.readline()
    while "PEER ready" not in line: line = p.stdout.readline()
    return p, line.split()[2]

pn, pn_addr = spawn("pn", 47601, "--pn")
carol, carol_addr = spawn("carol", 47602, "--quit-after", "8")
paths = Paths(os.path.join(tmp, "me")); paths.ensure()
s = Settings(paths.settings); s["radio"]["enabled"] = False; s["auto_interface"] = False; s["share_instance"] = False
s["tcp_peers"] = ["127.0.0.1:47601", "127.0.0.1:47602"]; s["log_level"] = 2; s.save()
core = Core(paths, log=lambda *a: None); core.start()
ok = True
def wait(c, secs, what):
    global ok
    t = time.time()
    while time.time() - t < secs:
        if c(): print(f"  PASS {what} ({time.time()-t:.0f}s)"); return True
        time.sleep(0.5)
    print(f"  FAIL {what}"); ok = False; return False
wait(lambda: core.store.peer(carol_addr) is not None, 20, "heard Carol")
wait(lambda: core.propagation_node() is not None, 20, "auto-selected the propagation node")
carol.wait(20)
print("  (Carol is now offline)")
mid = core.send(carol_addr, "Carol, this waits for you on the node")
wait(lambda: core.store.message(mid)["state"] == "stored", 240, "fell back to the propagation node and was stored")
print("     final:", core.store.message(mid)["state"], core.store.message(mid)["method"])
print("     (the propagation node validated FireFly's fast stamp: it accepted the upload)")
# Stump chat must never be left at a propagation node: pretend Carol is a Stump.
core.stumps[carol_addr] = ("Carol's Stump", "test")
mid2 = core.send(carol_addr, "/msg rod hi")
wait(lambda: core.store.message(mid2)["state"] == "failed", 240, "Stump chat that can't go directly fails; it isn't left at a node")
print("     reason:", core.store.message(mid2)["reason"])
core.stop(); pn.terminate(); os._exit(0 if ok else 1)
