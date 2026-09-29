"""A stand-in for another LXMF user (Sideband/NomadNet use the same LXMF library)
that can also pretend to be a Stump node. Used by run_integration.py.

  python3 tests/peer.py <workdir> <port> [--stump]
"""
import os, sys, time, secrets
import RNS, LXMF
import RNS.vendor.umsgpack as msgpack

work, port = sys.argv[1], int(sys.argv[2])
as_stump = "--stump" in sys.argv
as_pn = "--pn" in sys.argv
quit_after = int(sys.argv[sys.argv.index("--quit-after")+1]) if "--quit-after" in sys.argv else 600
os.makedirs(work, exist_ok=True)
with open(os.path.join(work, "config"), "w") as f:
    f.write(f"""[reticulum]
  enable_transport = Yes
  share_instance = No
[logging]
  loglevel = 2
[interfaces]
  [[TCP Server]]
    type = TCPServerInterface
    enabled = yes
    listen_ip = 127.0.0.1
    listen_port = {port}
""")
rns = RNS.Reticulum(configdir=work, loglevel=2)
ident = RNS.Identity()
router = LXMF.LXMRouter(identity=ident, storagepath=os.path.join(work, "lxmf"))
name = "LaBuche Test Stump" if as_stump else ("Test PN" if as_pn else os.path.basename(work).title())
local = router.register_delivery_identity(ident, display_name=name)
beacon = RNS.Destination(ident, RNS.Destination.IN, RNS.Destination.SINGLE, "stump", "node")
pending = {}   # source hash -> nonce

def reply(src_hash, text):
    who = RNS.Identity.recall(src_hash)
    if who is None:
        RNS.Transport.request_path(src_hash); t = time.time()
        while who is None and time.time() - t < 15:
            time.sleep(0.2); who = RNS.Identity.recall(src_hash)
    d = RNS.Destination(who, RNS.Destination.OUT, RNS.Destination.SINGLE, "lxmf", "delivery")
    router.handle_outbound(LXMF.LXMessage(d, local, text, desired_method=LXMF.LXMessage.OPPORTUNISTIC))

def on_msg(m):
    text = m.content_as_string()
    method = {1: "opportunistic", 2: "direct", 3: "propagated"}.get(m.method, m.method)
    print(f"PEER got [{method}] {text[:60]!r}", flush=True)
    if as_stump and text == "/auth":
        nonce = secrets.token_hex(16)
        pending[m.source_hash] = (nonce, time.time())
        reply(m.source_hash, f"AUTH-CHALLENGE {nonce}")
    elif as_stump and text.startswith("/auth "):
        _, pub, sig = text.split()
        nonce, t0 = pending.pop(m.source_hash, (None, 0))
        pk = RNS.Identity(create_keys=False); pk.load_public_key(bytes.fromhex(pub))
        if nonce is None: reply(m.source_hash, "AUTH-FAIL no challenge pending -- start with /auth")
        elif m.method != LXMF.LXMessage.OPPORTUNISTIC: reply(m.source_hash, "AUTH-FAIL test: answer was not a single packet")
        elif pk.validate(bytes.fromhex(sig), nonce.encode()):
            reply(m.source_hash, f"AUTH-OK {RNS.Identity.truncated_hash(bytes.fromhex(pub)).hex()}")
        else: reply(m.source_hash, "AUTH-FAIL signature does not match")
    elif as_stump:
        reply(m.source_hash, "✓ ~you\n<alice> welcome to #lxmf")
    else:
        reply(m.source_hash, "echo: " + text)

router.register_delivery_callback(on_msg)
if as_pn:
    router.enable_propagation()
print("PEER ready", local.hash.hex(), flush=True)
for i in range(quit_after):
    if i % 3 == 0:
        router.announce(local.hash)
        if as_pn: router.announce_propagation_node()
        if as_stump: beacon.announce(app_data=msgpack.packb(["stump", "test-1.0", "LaBuche Test", local.hash]))
    time.sleep(1)
