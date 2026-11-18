"""Packed text (Stump 1.0.0-beta.82): the format, FireFly's announce flag, who gets it.
   python3 tests/run_packed_text.py

The fixed messages and the tables' hash are Team Stump's (tests/mp/ztext.py):
every FireFly and Stump packs them to the same bytes."""
import hashlib, os, sys, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy"); os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
import RNS, LXMF
import RNS.vendor.umsgpack as msgpack
from LXMF.LXMessage import LXMessage
from firefly import ztext, lan, addresses
from firefly.paths import Paths
from firefly.settings import Settings
from firefly.core import Core, APP_TAG, reads_packed, unpacked_content

ok = True
def check(cond, what):
    global ok
    print(("  PASS " if cond else "  FAIL ") + what, flush=True)
    ok = ok and bool(cond)
def wait(fn, secs):
    t = time.time()
    while time.time() - t < secs:
        if fn():
            return True
        time.sleep(0.2)
    return False

print("the format (version 1)")
h = hashlib.sha256(ztext._DICT + ztext._LL.encode() + ztext._DL.encode() + ztext._HEAD).hexdigest()
check(h == "6ef2028f82238d884eae1b29f9fd270f3c2a036fae07421835d5427d4c120bd5", "the tables are version 1's")
check(ztext.available(), "this Python reads it (zlib)")
VECTORS = [
    ('<alice> hey is anyone around the north trail tonight?',
     "ff09ab44ce53c2a5860a878def14caf7987e4fc38a763b75c301"),
    ("<Rod@LaBuche> on se rejoint au camp à 18h, apporte les piles et de l'eau\n<Luc@Camp2> oui bien reçu, 5 sur 5",
     "ffc958159b19bb69f3194fd11c79f0c605829b85a55cbc40abd76611b1a6f1380abd6d043e7665f00a67f6fb2699cd37b758dd0c525256047ef12813d1655fe15c76"),
    ('<maria> hola, ¿alguien me copia? estoy cerca del campamento',
     "ff49cdb460a987b4885efcfa69aac5f63682dde8a827906981e4734aa10e"),
    ('[NAMES] Rod alice bob guest-3f2a maria Luc@Camp2 jean-guy mesh-fd92',
     "ffcbc31fab825885459faa69f7abac950314645a30ca6cbeb9c5ea6640879cc9fe819d87dfb32cd6070e"),
    ('→ #lora-mesh', "fffee79d5e2007"),
]
for text, packed in VECTORS:
    z = bytes.fromhex(packed)
    check(unpacked_content(z) == text.encode(), f"a Stump's packed line reads: {text[:30]!r}")
    check(ztext.pack(text.encode()) == z, "... and FireFly packs it to the same bytes")
check(unpacked_content(b"\xfe\xff\x01") == b"\xff\x01", "0xFE: the rest as it stands")
check(unpacked_content(b"plain text") == b"plain text", "plain: as it came")
check(unpacked_content(b"\xff\x00\x01 not packed") == b"\xff\x00\x01 not packed", "packed but unreadable: as it came")
z = bytes.fromhex(VECTORS[0][1])
check(all(unpacked_content(z[:n]) == z[:n] for n in range(1, len(z) - 1)), "cut short: as it came, no exception")
check(ztext.pack(b"/help") == b"/help", "a line under MIN goes as it is")
rnd = bytes(b & 0x7f for b in os.urandom(300))
check(ztext.pack(rnd) == rnd, "what doesn't pack goes as it is (never longer)")
big = b"a line said again and again. " * 200
check(ztext.pack(big) == big, "longer than MAX: as it is")

print("who says they read it (announces)")
check(reads_packed(msgpack.packb([b"Rod", None, [], "stump:firefly-android/0.6.3.b.74", {"z": 1}])), "an app's with z")
check(reads_packed(msgpack.packb([b"Stump", None, [], None, {"z": 1}])), "a Stump's (null where the app tag would be)")
for odd in (b"Rod", msgpack.packb([b"Rod", None, [0]]), msgpack.packb([b"Rod", None, [], "stump:x"]),
            msgpack.packb([b"Rod", None, [], None, "z"]), msgpack.packb([b"Rod", None, [], None, {"z": True}]),
            msgpack.packb([b"Rod", None, [], None, {"z": 0}]), b"", b"\x95", None):
    check(not reads_packed(odd), f"not a z announce: {odd[:12] if odd else odd!r}")

print("FireFly's own announce")
tmp = tempfile.mkdtemp(); paths = Paths(tmp); paths.ensure()
st = Settings(paths.settings); st["auto_interface"] = False; st["share_instance"] = False; st["log_level"] = 2
st["display_name"] = "R36 Tester"; st.save()
lan.LanManager.start = lambda self: None
core = Core(paths, log=lambda *a: None); core.start()
try:
    ad = core.router.get_announce_app_data(core.local.hash)
    items = msgpack.unpackb(ad)
    check(items[:3] == [b"R36 Tester", None, [LXMF.SF_COMPRESSION]] and items[3] == APP_TAG and items[4] == {"z": 1},
          f"LXMF's three items, the app tag, then {{'z': 1}}: {items}")
    check(reads_packed(ad), "... read as a z announce")
    check(LXMF.display_name_from_app_data(ad) == "R36 Tester" and LXMF.stamp_cost_from_app_data(ad) is None
          and LXMF.compression_support_from_app_data(ad) is True,
          "upstream LXMF still reads its name, stamp cost and compression support")
    sent = []
    core.router.delivery_destinations[core.local.hash].announce = lambda app_data=None, **k: sent.append(app_data)
    core.announce()
    check(sent and reads_packed(sent[-1]), "the announce actually sent carries it")
    core.settings["packed_text"] = False
    check(len(msgpack.unpackb(core.router.get_announce_app_data(core.local.hash))) == 4,
          "packed_text off: the app tag only, as before")
    core.settings["packed_text"] = True

    print("who gets packed text")
    z_id, plain_id, kept_id = RNS.Identity(), RNS.Identity(), RNS.Identity()
    Z = RNS.Destination.hash(z_id, "lxmf", "delivery")
    P = RNS.Destination.hash(plain_id, "lxmf", "delivery")
    K = RNS.Destination.hash(kept_id, "lxmf", "delivery")
    z_ad = msgpack.packb([b"Rod", None, [], "stump:firefly-android/0.6.3.b.74", {"z": 1}])
    RNS.Identity.remember(os.urandom(32), Z, z_id.get_public_key(), z_ad)
    RNS.Identity.remember(os.urandom(32), P, plain_id.get_public_key(), msgpack.packb([b"Sideband", None, [0]]))
    core._on_delivery_announce(Z, z_id, z_ad)
    core._on_delivery_announce(P, plain_id, msgpack.packb([b"Sideband", None, [0]]))
    text = VECTORS[1][0]
    out = core.outgoing_content(Z.hex(), text)
    check(isinstance(out, bytes) and out[0] == ztext.PACKED and len(out) < len(text.encode())
          and ztext.unpack(out) == text.encode(), f"to an address that announced z: packed ({len(text.encode())} -> {len(out)} B)")
    check(core.outgoing_content(P.hex(), text) == text, "to one that didn't: the text as before")
    check(core.outgoing_content(Z.hex(), "ok") == b"ok", "a short line, even to z: as it is")
    check(core.outgoing_content(os.urandom(16).hex(), text) == text, "to an address never heard: the text")
    RNS.Identity.remember(os.urandom(32), K, kept_id.get_public_key(), z_ad)
    check(core.packs_for(K.hex()), "not heard this session, but Reticulum kept its z announce: packed")
    core._on_delivery_announce(Z, z_id, msgpack.packb([b"Rod", None, [], "stump:firefly-android/0.6.2.b.73"]))
    check(not core.packs_for(Z.hex()), "its latest announce without z (an older build): plain again")
    core._on_delivery_announce(Z, z_id, z_ad)
    core.settings["packed_text"] = False
    check(core.outgoing_content(Z.hex(), text) == text, "packed_text off: plain to everyone")
    core.settings["packed_text"] = True

    # What goes into LXMF for a real send.
    seen = []
    core.router.handle_outbound = lambda lxm: seen.append(lxm)
    core.last_announce = time.time()
    core.send(Z.hex(), text)
    core.send(P.hex(), text)
    check(wait(lambda: len(seen) == 2, 10), "both messages handed to LXMF")
    by = {m.destination_hash: m for m in seen}
    check(Z in by and by[Z].content[:1] == b"\xff" and ztext.unpack(by[Z].content) == text.encode(),
          "the LXMF message to the z address: content packed")
    check(P in by and by[P].content == text.encode(), "the one to the other app: plain")
    rows = [m for m in core.store.messages(Z.hex()) if m["outgoing"]]
    check(rows and rows[-1]["content"] == text, "FireFly's own copy keeps the text")

    print("packed messages coming in")
    them = RNS.Destination(z_id, RNS.Destination.OUT, RNS.Destination.SINGLE, "lxmf", "delivery")
    me = RNS.Destination(core.identity, RNS.Destination.OUT, RNS.Destination.SINGLE, "lxmf", "delivery")

    def incoming(content):
        m = LXMessage(me, them, content, desired_method=LXMessage.DIRECT)
        m.pack()
        return LXMessage.unpack_from_bytes(m.packed)
    got = lambda: [m["content"] for m in core.store.messages(Z.hex()) if not m["outgoing"]]
    for text_in, packed in VECTORS[:3]:
        core._on_message(incoming(bytes.fromhex(packed)))
        check(got()[-1] == text_in, f"a packed message from the network, stored as its text: {text_in[:28]!r}")
    core._on_message(incoming(b"\xfe\xffodd"))
    check(got()[-1] == "⊘ 4 bytes FireFly can't read as text", "0xFE stripped; the rest isn't text: a note, no crash")
    core._on_message(incoming(b"\xff\x00\x01 not packed"))
    check(got()[-1] == "⊘ 14 bytes FireFly can't read as text", "packed and unreadable: kept as binary, a note")
    core._on_message(incoming(b"\xfe" + "→ #main".encode()))
    check(got()[-1] == "→ #main", "0xFE then text: the text")
    core._on_message(incoming("plain, as ever".encode()))
    check(got()[-1] == "plain, as ever", "a plain message: as before")
    m = incoming(bytes.fromhex(VECTORS[0][1]))
    h0 = m.hash
    core._on_message(m)
    check(m.hash == h0, "its id stays that of what was sent")
finally:
    core.stop()
print("ALL PASSED" if ok else "SOME FAILED")
sys.stdout.flush(); os._exit(0 if ok else 1)
