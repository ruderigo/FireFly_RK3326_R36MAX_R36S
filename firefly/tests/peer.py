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
quiet_pn = "--quiet-pn" in sys.argv     # propagation node on, but never announced (like a Stump's)
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

landed = set()

def reply(src_hash, text, title=""):
    who = RNS.Identity.recall(src_hash)
    if who is None:
        RNS.Transport.request_path(src_hash); t = time.time()
        while who is None and time.time() - t < 15:
            time.sleep(0.2); who = RNS.Identity.recall(src_hash)
    d = RNS.Destination(who, RNS.Destination.OUT, RNS.Destination.SINGLE, "lxmf", "delivery")
    router.handle_outbound(LXMF.LXMessage(d, local, text, title=title, desired_method=LXMF.LXMessage.OPPORTUNISTIC))

def voice_samples():
    """A 15-second rising tone, encoded the way Sideband sends voice notes:
    raw Codec2 1200 frames (NO file header: pycodec2 output), an Ogg Opus
    file, and, as some other apps do, Codec2 with a file header."""
    import math, struct, subprocess, tempfile, wave
    d = tempfile.mkdtemp()
    n = 8000 * 15
    pcm = b"".join(struct.pack("<h", int(9000 * math.sin(2 * math.pi * (300 + 200 * i / n) * i / 8000)))
                   for i in range(n))
    raw, wav = os.path.join(d, "v.raw"), os.path.join(d, "v.wav")
    open(raw, "wb").write(pcm)
    with wave.open(wav, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000); w.writeframes(pcm)
    subprocess.run(["c2enc", "2400", raw, raw + ".frames"], check=True, capture_output=True)   # raw frames
    subprocess.run(["c2enc", "2400", raw, raw + ".c2"], check=True, capture_output=True)       # with a file header
    subprocess.run(["opusenc", "--quiet", "--bitrate", "8", wav, wav + ".ogg"], check=True, capture_output=True)
    return (open(raw + ".frames", "rb").read(), open(wav + ".ogg", "rb").read(), open(raw + ".c2", "rb").read())

def send_fields(src_hash, text, fields):
    who = RNS.Identity.recall(src_hash)
    d = RNS.Destination(who, RNS.Destination.OUT, RNS.Destination.SINGLE, "lxmf", "delivery")
    router.handle_outbound(LXMF.LXMessage(d, local, text, fields=fields, desired_method=LXMF.LXMessage.DIRECT))

def on_msg(m):
    text = m.content_as_string()
    method = {1: "opportunistic", 2: "direct", 3: "propagated"}.get(m.method, m.method)
    print(f"PEER got [{method}] {text[:60]!r}", flush=True)
    if text == "voice?":
        c2, ogg, c2h = voice_samples()
        vector = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "kristoff_1200.bit"), "rb").read()
        print(f"PEER sending voice notes: spec vector {len(vector)} B, codec2 {len(c2)} B, opus {len(ogg)} B", flush=True)
        # Exactly as the spec (and FireFly for Android) sends it: empty content and title.
        send_fields(m.source_hash, "", {LXMF.FIELD_AUDIO: [LXMF.AM_CODEC2_1200, vector]})
        send_fields(m.source_hash, "", {LXMF.FIELD_AUDIO: [LXMF.AM_CODEC2_2400, c2]})
        send_fields(m.source_hash, "malformed field", {LXMF.FIELD_AUDIO: [LXMF.AM_CODEC2_1200, 750]})
        # A file header (outside the spec, but some tools add one): header says 2400, field says 1300.
        send_fields(m.source_hash, "with header", {LXMF.FIELD_AUDIO: [LXMF.AM_CODEC2_1300, c2h]})
        send_fields(m.source_hash, "listen to this", {LXMF.FIELD_AUDIO: [LXMF.AM_OPUS_OGG, ogg]})
        send_fields(m.source_hash, "", {LXMF.FIELD_AUDIO: [LXMF.AM_CODEC2_450, b"\x00" * 40]})
        return
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
    elif as_stump and text == "voice dm?":
        vec = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "kristoff_opusenc_8k.ogg"), "rb").read()
        send_fields(m.source_hash, "[DM] <bob>: ♪ 5.0 s", {LXMF.FIELD_AUDIO: [LXMF.AM_OPUS_OGG, vec]})
        reply(m.source_hash, "⧗ — trop de notes vocales, ralentissez")
    elif as_stump and text.startswith("/join"):
        room = text.split()[1].lstrip("#") if len(text.split()) > 1 else ""
        if room == "vip":
            reply(m.source_hash, "⊘ #vip minted — ce salon exige une identité vérifiée -- envoyez /auth")
        elif room == "lxmf":
            reply(m.source_hash, "= #lxmf — vous êtes déjà dans #lxmf")
    elif as_stump and text.startswith("/") and not text.startswith("/rooms"):
        reply(m.source_hash, text.split()[0] and f"? {text.split()[0]} — commande inconnue")
    elif as_stump:
        if m.source_hash not in landed:          # the node says where it put you, before anything else
            landed.add(m.source_hash)
            reply(m.source_hash, "→ #lxmf")
        reply(m.source_hash, "✓ ~you\n<alice> welcome to #lxmf", title="#lxmf")
    else:
        reply(m.source_hash, "echo: " + text)

router.register_delivery_callback(on_msg)
if as_pn or quiet_pn:
    router.enable_propagation()
print("PEER ready", local.hash.hex(), flush=True)
for i in range(quit_after):
    if i % 3 == 0:
        router.announce(local.hash)
        if as_pn: router.announce_propagation_node()
        if as_stump: beacon.announce(app_data=msgpack.packb(["stump", "test-1.0", "LaBuche Test", local.hash]))
    time.sleep(1)
