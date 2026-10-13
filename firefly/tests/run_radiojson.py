"""radio.json from the Stump provisioner, and the network passphrase (IFAC).
   python3 tests/run_radiojson.py"""
import json, os, sys, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from fake_rnode import FakeRNode
from firefly import radiojson
from firefly.paths import Paths
from firefly.settings import Settings
from firefly.core import Core
from firefly.radio import RadioStatus as RS

ok = True
def check(cond, what):
    global ok
    print(("  PASS " if cond else "  FAIL ") + what)
    ok = ok and bool(cond)
def wait(fn, secs):
    t = time.time()
    while time.time() - t < secs:
        if fn(): return True
        time.sleep(0.2)
    return False

print("parsing")
# Exactly what provisioner.py push_config_to_board() writes for a "heltec" board.
prov = {"frequency": 915000000, "bandwidth": 125000, "txpower": 7, "spreadingfactor": 8, "codingrate": 5,
        "boundary_mode": "internal", "ifac": "labuche-mesh"}
r, probs = radiojson.parse(json.dumps(prov, indent=2).encode())
check(r == {"frequency": 915_000_000, "bandwidth": 125_000, "tx_power": 7, "spreading_factor": 8,
            "coding_rate": 5, "ifac_passphrase": "labuche-mesh"} and not probs, "provisioner's radio.json, as written")
r, _ = radiojson.parse(json.dumps({k: v for k, v in prov.items() if k != "ifac"}).encode())
check("ifac_passphrase" not in r, "no 'ifac' key: no passphrase")
r, _ = radiojson.parse(b'{"frequency": 868.1, "bandwidth": 250, "spreading_factor": 9, "coding_rate": 6, "tx_power": 14}')
check(r["frequency"] == 868_100_000 and r["bandwidth"] == 250_000 and r["spreading_factor"] == 9,
      "MHz / kHz and FireFly's own key names")
r, _ = radiojson.parse(json.dumps({"node_name": "x", "board_type": "heltec", "radio": prov,
                                   "ifac": "outer"}).encode())
check(r["frequency"] == 915_000_000 and r["ifac_passphrase"] == "labuche-mesh", "a whole provisioner profile")
r, probs = radiojson.parse(b'{"frequency": 915000000, "spreadingfactor": 40, "bandwidth": 123}')
check(r == {"frequency": 915_000_000} and len(probs) == 2, f"bad values skipped and reported ({'; '.join(probs)})")
for bad, why in ((b"not json", "garbage"), (b"[1,2]", "a list"), (b'{"name": "x"}', "no radio keys"),
                 (b'\xef\xbb\xbf{"frequency": "abc"}', "BOM + a non-number")):
    try:
        radiojson.parse(bad); check(False, f"refuses {why}")
    except ValueError as e:
        check(True, f"refuses {why}: {e}")

print("applying at start")
tmp = tempfile.mkdtemp(); paths = Paths(tmp); paths.ensure()
s = Settings(paths.settings); s["auto_interface"] = False; s["share_instance"] = False; s["log_level"] = 2; s.save()
rj = os.path.join(tmp, "radio.json")
with open(rj, "w") as f:
    json.dump({**prov, "frequency": 914875000, "spreadingfactor": 9}, f)
core = Core(paths, log=lambda *a: None)
rr = core.settings["radio"]
check(rr["frequency"] == 914_875_000 and rr["spreading_factor"] == 9 and rr["ifac_passphrase"] == "labuche-mesh",
      "radio.json found and applied before the radio starts")
check("914.875 MHz" in core.radio_json_note and "passphrase" in core.radio_json_note,
      f"user is told: {core.radio_json_note!r}")
rr["spreading_factor"] = 8; core.settings.save()
core2 = Core(paths, log=lambda *a: None)
check(core2.settings["radio"]["spreading_factor"] == 8 and not core2.radio_json_note,
      "applied once: a later change by hand sticks while the file is unchanged")
with open(rj, "w") as f:
    json.dump({**prov, "spreadingfactor": 10}, f)
core3 = Core(paths, log=lambda *a: None)
check(core3.settings["radio"]["spreading_factor"] == 10, "a new radio.json is applied again")
with open(rj, "w") as f:
    f.write("{oops")
core4 = Core(paths, log=lambda *a: None)
check(core4.settings["radio"]["spreading_factor"] == 10 and core4.radio_json_note.startswith("radio.json not used"),
      f"a broken file changes nothing and says why: {core4.radio_json_note!r}")
core5 = Core(paths, log=lambda *a: None)
check(not core5.radio_json_note, "...and doesn't nag again on the next start")
os.remove(rj)

print("passphrase on the radio interface")
core = Core(paths, log=lambda *a: None)
core.settings["radio"].update(frequency=915_000_000, spreading_factor=8, ifac_passphrase="labuche-mesh",
                              ifac_netname="")
core.settings.save()
core.start()
devices = []
core.radio.port_lister = lambda: [d.port for d in devices]
board = FakeRNode(band=(902e6, 928e6)); devices.append(board); core.radio.search_now()
check(wait(lambda: core.radio.status.state == RS.ONLINE, 20), "RNode online with a passphrase set")
iface = core.radio.iface
key1 = getattr(iface, "ifac_key", None)
check(key1 is not None and iface.ifac_netkey == "labuche-mesh" and iface.ifac_size == 8,
      "IFAC key derived on the interface (RNode default size 8)")
core.settings["radio"]["ifac_passphrase"] = "another"; core.radio.request_apply(delay=0.2)
check(wait(lambda: core.radio.iface is not None and core.radio.iface is not iface
           and getattr(core.radio.iface, "ifac_key", None) not in (None, key1), 20),
      "changing the passphrase reconnects live with the new key")
iface = core.radio.iface
core.settings["radio"]["ifac_passphrase"] = ""; core.radio.request_apply(delay=0.2)
check(wait(lambda: core.radio.iface is not None and core.radio.iface is not iface
           and getattr(core.radio.iface, "ifac_key", None) is None, 20), "clearing it: open mesh again")
check(board.freq == 915_000_000 and board.sf == 8, "radio settings unchanged by the passphrase")
core.stop()
print("ALL PASSED" if ok else "SOME FAILED")
sys.stdout.flush(); os._exit(0 if ok else 1)
