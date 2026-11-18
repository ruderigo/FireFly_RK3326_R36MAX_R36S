"""Reticulum 1.6.1 announce stamps: FireFly's own, and other nodes' as FireFly reads them.

Reticulum 1.6.1 appends a proof-of-work stamp to every announce's app data (0xC1, flags,
a 14-byte stamp, the link cost) and takes it off again on the receiving side when the stamp
meets the cost the receiver would ask (23.5 by default). Each announce here is made by
Reticulum itself and read back through Reticulum's own announce validation, as off the air.
   python3 tests/run_announce_stamps.py"""
import os, sys, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import RNS, LXMF
import RNS.vendor.umsgpack as msgpack
from firefly import lan
from firefly.paths import Paths
from firefly.settings import Settings
from firefly.core import Core, APP_TAG, reads_packed

ok = True
def check(cond, what):
    global ok
    print(("  PASS " if cond else "  FAIL ") + what, flush=True)
    ok = ok and bool(cond)

if not hasattr(RNS.Transport, "STAMP_DESTINATIONS"):
    print("  (Reticulum before 1.6.1: no announce stamps, skipped)")
    sys.exit(0)

tmp = tempfile.mkdtemp()
paths = Paths(tmp); paths.ensure()
st = Settings(paths.settings); st["radio"]["enabled"] = False; st["auto_interface"] = False
st["share_instance"] = False; st["log_level"] = 2; st["display_name"] = "R36 Stamped"; st.save()
lan.LanManager.start = lambda self: None
core = Core(paths, log=lambda *a: None); core.start()
EXT = RNS.Identity.EXTPAYLOADLENGTH


def on_air(destination, app_data):
    """An announce as Reticulum makes it (stamp included), then as a receiver's Reticulum
    reads it: (app data on the air, app data handed to apps, stamp value or None)."""
    pkt = destination.announce(app_data=app_data, send=False)
    pkt.pack()
    rx = RNS.Packet(None, pkt.raw)
    rx.unpack()
    keysize, nh, sig = RNS.Identity.KEYSIZE // 8, RNS.Identity.NAME_HASH_LENGTH // 8, RNS.Identity.SIGLENGTH // 8
    ratchet = RNS.Identity.RATCHETSIZE // 8 if rx.context_flag == RNS.Packet.FLAG_SET else 0
    raw_app = rx.data[keysize + nh + 10 + ratchet + sig:]
    valid = RNS.Identity.validate_announce(rx)
    handed = RNS.Identity.recall_app_data(destination.hash) if valid else "invalid"
    return raw_app, handed, RNS.Identity.recall_stamp_value(destination.hash)


print("FireFly's own announce stamp")
cfg = open(os.path.join(paths.rns_config_dir, "config")).read()
check("[stamps]" in cfg and "destination_value = 23.5" in cfg, "FireFly's Reticulum config asks a 23.5 stamp of its announces")
check(RNS.Transport.DESTINATION_VALUE == 23.5 and core.local.target_value == 23.5,
      f"... and Reticulum took it: {core.local.target_value} (Reticulum's default is 25)")
mine = core.router.get_announce_app_data(core.local.hash)
t0 = time.time()
raw, handed, value = on_air(core.local, mine)
print(f"     stamp made in {time.time() - t0:.1f}s (this machine, {os.cpu_count()} cores), value {value}", flush=True)
check(core.local.stamp is not None and value is not None and value >= 23.5, f"the announce carries a stamp worth {value}")
check(os.path.isfile(os.path.join(paths.rns_config_dir, "storage", "stamps", core.local.hash.hex() + ".dstamp")),
      "... kept on the card, so it's made only once per address")
check(len(raw) == len(mine) + EXT and raw[:len(mine)] == mine and raw[len(mine)] == 0xC1,
      f"on the air: LXMF's app data, then the stamp ({EXT} bytes, 0xC1 first)")
check(handed == mine, "a Reticulum 1.6.1 receiver hands its apps the app data without the stamp")
items = msgpack.unpackb(handed)
check(LXMF.display_name_from_app_data(handed) == "R36 Stamped", "its name reads right")
check(len(items) == 5 and items[3] == APP_TAG and items[4] == {"z": 1}, f"the app tag and z read right: {items[3:]}")
check(reads_packed(handed) and LXMF.stamp_cost_from_app_data(handed) is None, "packed text read, no message stamp asked")
def stump_app_tag_in(app_data):          # the Stump's own check (rrc.app_tag_in)
    d = msgpack.unpackb(app_data)
    t = d[3] if isinstance(d, list) and len(d) > 3 else None
    return isinstance(t, str) and t.startswith("stump")
check(stump_app_tag_in(handed) and stump_app_tag_in(raw) and reads_packed(raw),
      "a Stump reads the tag and z with or without the stamp (msgpack stops at the list's end)")
t0 = time.time()
raw2, handed2, _ = on_air(core.local, mine)
check(time.time() - t0 < 2 and raw2[-EXT:] == raw[-EXT:], "the next announce reuses the stamp (no new work)")
RNS.Transport.STAMPS_ENFORCED = True
try:
    _, handed3, _ = on_air(core.local, mine)
    check(handed3 == mine, "a node that enforces stamps (asking 23.5) takes FireFly's announce")
finally:
    RNS.Transport.STAMPS_ENFORCED = False

print("other nodes' announces")
peer = RNS.Identity()
lx = RNS.Destination(peer, RNS.Destination.IN, RNS.Destination.SINGLE, "lxmf", "delivery")
ad = msgpack.packb([b"Stamped Peer", None, [0], None, {"z": 1}])
raw, handed, value = on_air(lx, ad)
check(value is not None and handed == ad, f"a 1.6.1 LXMF app (stamp {value}): app data handed without the stamp")
core._on_delivery_announce(lx.hash, peer, handed)
p = core.store.peer(lx.hash.hex()) or {}
check(p.get("name") == "Stamped Peer" and core.packs_for(lx.hash.hex()), f"FireFly lists it by name ({p.get('name')!r}), packed text on")

# A node whose stamp is cheaper than FireFly's Reticulum asks (8 < 23.5): Reticulum hands
# the app data with the stamp still on, as Team Stump's test apps do ("a cheap stamp so they
# never hang").
cheap = RNS.Identity()
default_value = RNS.Transport.DESTINATION_VALUE
RNS.Transport.DESTINATION_VALUE = 8
try:
    nn = RNS.Destination(cheap, RNS.Destination.IN, RNS.Destination.SINGLE, "nomadnetwork", "node")
    raw, handed, value = on_air(nn, "Cheap Node".encode())
    lc = RNS.Destination(cheap, RNS.Destination.IN, RNS.Destination.SINGLE, "lxmf", "delivery")
    raw_l, handed_l, _ = on_air(lc, msgpack.packb([b"Cheap Peer", None, [0], None, {"z": 1}]))
finally:
    RNS.Transport.DESTINATION_VALUE = default_value
check(handed == "Cheap Node".encode() + raw[-EXT:], "a cheaply stamped NomadNet node: Reticulum leaves the stamp on")
core._on_nomad_announce(nn.hash, handed)
check((core.store.peer(nn.hash.hex()) or {}).get("name") == "Cheap Node", "FireFly still reads its name, without the stamp")
core._on_delivery_announce(lc.hash, cheap, handed_l)
p = core.store.peer(lc.hash.hex()) or {}
check(p.get("name") == "Cheap Peer" and core.packs_for(lc.hash.hex()), "... and a cheaply stamped LXMF app's name and z")
legacy = RNS.Identity()
RNS.Transport.DESTINATION_VALUE = 8
try:
    lg = RNS.Destination(legacy, RNS.Destination.IN, RNS.Destination.SINGLE, "lxmf", "delivery")
    _, handed, _ = on_air(lg, "Old App".encode())
finally:
    RNS.Transport.DESTINATION_VALUE = default_value
core._on_delivery_announce(lg.hash, legacy, handed)
check((core.store.peer(lg.hash.hex()) or {}).get("name") == "Old App", "... and an old LXMF app's plain-text name")

core.stop()
print("ALL PASSED" if ok else "SOME FAILED")
sys.stdout.flush(); os._exit(0 if ok else 1)
