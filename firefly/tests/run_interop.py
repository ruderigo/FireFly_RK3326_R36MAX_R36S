"""Working with other LXMF apps: their address codes, their commands, their formatting.
   python3 tests/run_interop.py"""
import os, shutil, subprocess, sys, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy"); os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
import RNS, LXMF
from firefly import addresses, markup, lan
from firefly.paths import Paths
from firefly.settings import Settings
from firefly.core import Core, commands_asked

ok = True
def check(cond, what):
    global ok
    print(("  PASS " if cond else "  FAIL ") + what, flush=True)
    ok = ok and bool(cond)

them = RNS.Identity()
THEM = RNS.Destination.hash(them, "lxmf", "delivery").hex()
KEY = them.get_public_key()

print("address codes")
check(addresses.parse(THEM)["key"] is None, "a bare address (Sideband, NomadNet)")
check(addresses.parse(f"<{THEM.upper()}>")["address"] == THEM, "<ADDRESS> in capitals")
a = addresses.parse(f"lxma://{THEM}:{KEY.hex()}")
check(a["key"] == KEY and a["scheme"] == "lxma", "lxma://address:key (Columba, MeshChatX), key in hex")
check(addresses.parse(f"lxma://{THEM}:{addresses.b64url(KEY)}")["key"] == KEY, "...key in base64url")
a = addresses.parse(f"lxmf://{THEM}?stump=B%C3%BBche%203&key={addresses.b64url(KEY)}")
check(a["stump"] == "Bûche 3" and a["key"] == KEY, "lxmf://…?stump=…&key=… (a Stump's code, beta.52)")
a = addresses.parse(f"lxmf://{THEM}?stump=B%C3%BBche&key={addresses.b64url(KEY)}&r=1.0.0-beta.82")
check(a["release"] == "1.0.0-beta.82" and a["key"] == KEY, "…&r=<release> (beta.79): read as a hint")
check(addresses.parse(f"lxmf://{THEM}?key={addresses.b64url(KEY)}")["release"] is None, "no r=: no release")
check(addresses.parse(f"lxma://{THEM}:abcd")["key_bad"], "a key that isn't one is flagged")
check(addresses.identity_for(THEM, RNS.Identity().get_public_key()) is None, "a key that isn't this address's: refused")
check(addresses.identity_for(THEM, KEY) is not None, "...the right one: accepted")
check(addresses.is_paper_message("LXM://abc") and addresses.parse("hello") is None, "paper messages and junk told apart")
codes = addresses.codes(THEM, KEY, "Bûche")
check([c[0] for c in codes] == ["FireFly", "Columba", "Address"], "three codes, FireFly's first")
for label, _, text in codes:
    p = addresses.parse(text)
    check(p["address"] == THEM and (label == "Address" or p["key"] == KEY), f"{label} code reads back: {text[:48]}…")
check(addresses.parse(codes[0][2])["stump"] == "Bûche", "a Stump's FireFly code names it")
check(addresses.codes(THEM)[0][0] == "Address", "no key known: the bare address only")
check(codes[1][2] == f"lxma://{THEM}:{KEY.hex()}", "Columba's format exactly: lowercase hex, 32 and 128")

if shutil.which("zbarimg"):
    from firefly import qr
    import pygame
    m = qr.matrix(codes[1][2]); px = 4; n = len(m) + 8
    s = pygame.Surface((n * px, n * px)); s.fill((255, 255, 255))
    for r, row in enumerate(m):
        for c, dark in enumerate(row):
            if dark:
                pygame.draw.rect(s, (0, 0, 0), ((c + 4) * px, (r + 4) * px, px, px))
    f = os.path.join(tempfile.mkdtemp(), "q.png"); pygame.image.save(s, f)
    got = subprocess.run(["zbarimg", "-q", "--raw", f], capture_output=True, text=True).stdout.strip()
    check(got == codes[1][2], "the lxma:// QR code decodes back exactly")

print("adding contacts from codes")
tmp = tempfile.mkdtemp(); paths = Paths(tmp); paths.ensure()
st = Settings(paths.settings); st["auto_interface"] = False; st["share_instance"] = False; st["log_level"] = 2; st.save()
lan.LanManager.start = lambda self: None
core = Core(paths, log=lambda *a: None); core.start()
h, how = core.add_contact(f"lxma://{THEM}:{KEY.hex()}")
check(how == "key" and RNS.Identity.recall(bytes.fromhex(h)) is not None, "an lxma:// contact can be written to at once")
try:
    other = RNS.Destination.hash(RNS.Identity(), "lxmf", "delivery").hex()
    core.add_contact(f"lxma://{other}:{KEY.hex()}"); check(False, "a forged code is refused")
except ValueError as e:
    check("not trusted" in str(e), f"a forged code is refused: {e}")
s2 = RNS.Identity(); S2 = RNS.Destination.hash(s2, "lxmf", "delivery").hex()
h, how = core.add_contact(f"lxmf://{S2}?stump=Laptop&key={addresses.b64url(s2.get_public_key())}")
check(how == "stump" and core.is_stump(S2), "a Stump's code adds a Stump")
check(core.add_contact(RNS.Destination.hash(RNS.Identity(), "lxmf", "delivery").hex())[1] == "plain", "a bare address, as before")
check([c[0] for c in core.address_codes(core.address)] == ["FireFly", "Columba", "Address"], "our own QR codes carry our key")

print("saying FireFly is a Stump app (Stump 1.0.0-beta.53)")
import RNS.vendor.umsgpack as _mp
from firefly.core import APP_TAG
data = core.router.get_announce_app_data(core.local.hash)
items = _mp.unpackb(data)
check(len(items) >= 4 and items[3] == APP_TAG and APP_TAG.startswith("stump:firefly-rk3326/"), f"fourth item: {items[3]!r}")
check(LXMF.display_name_from_app_data(data) == core.settings["display_name"], "upstream LXMF still reads the name")
def stump_app_tag_in(app_data):          # the Stump's own check (rrc.app_tag_in, beta.53 packs branch)
    b0 = app_data[0]
    if not ((0x90 <= b0 <= 0x9f) or b0 == 0xdc):
        return False
    d = _mp.unpackb(app_data)
    t = d[3] if isinstance(d, list) and len(d) > 3 else None
    t = t.decode("utf-8", "ignore") if isinstance(t, bytes) else t
    return isinstance(t, str) and t.startswith("stump")
check(stump_app_tag_in(data), "a Stump's own check recognises FireFly from the announce alone")
check(LXMF.stamp_cost_from_app_data(data) is None, "...and the stamp cost (none asked)")
seen = []
class H:
    aspect_filter = "lxmf.delivery"
    def received_announce(self, destination_hash, announced_identity, app_data):
        seen.append(app_data)
RNS.Transport.register_announce_handler(H())
core.announce(); time.sleep(0.5)
check(core.router.get_announce_app_data(core.local.hash) == data, "the same app data on every announce")

print("commands from Sideband and MeshChat")
check(commands_asked([{0x01: [0, False]}]) == [1] and commands_asked("junk") == [] and commands_asked([{True: 1}]) == [],
      "FIELD_COMMANDS read safely")
sent = []
core.send = lambda peer, text, *a, **k: sent.append((peer, text))

class FakeLXM:
    def __init__(self, src, content, fields, n):
        self.source_hash = bytes.fromhex(src); self.hash = bytes([n]) * 32; self.content = content.encode()
        self.fields = fields; self.title = b""; self.timestamp = time.time(); self.method = LXMF.LXMessage.DIRECT
        self.signature_validated = True
    def content_as_string(self): return self.content.decode()
    def title_as_string(self): return ""

core._on_message(FakeLXM(THEM, "", {LXMF.FIELD_COMMANDS: [{0x01: [0, False]}]}, 1))
row = core.store.messages(THEM)[-1]
check(row["content"].startswith("⊘ Asked for location and telemetry: declined") and not row["unread"],
      f"a telemetry request shows as a note, not an empty bubble: {row['content']!r}")
check(len(sent) == 1 and sent[0][0] == THEM and "doesn't share location" in sent[0][1], "...and is politely declined")
core._on_message(FakeLXM(THEM, "", {LXMF.FIELD_COMMANDS: [{0x02: []}]}, 2))
check(len(sent) == 1, "declined at most once an hour per contact")
core._on_message(FakeLXM(S2, "", {LXMF.FIELD_COMMANDS: [{0x01: []}]}, 3))
check(len(sent) == 1, "never sent to a Stump")
core._on_message(FakeLXM(THEM, "hi, where are you?", {LXMF.FIELD_COMMANDS: [{0x01: []}]}, 4))
check(core.store.messages(THEM)[-1]["content"] == "hi, where are you?", "text sent with a request is shown as it is")

print("formatted messages")
md = ("# Title\n\nSome **bold** and _italic_ and `code` and ***both*** and ~~gone~~.\n\n- one\n- [x] done\n"
      "> quoted\n\n---\n```\nx = 1\n```\n[site](https://example.org)\nsnake_case and 2*3*4 stay as they are")
r = markup.render(md, markup.MARKDOWN)
P = lambda line: markup.plain(line[1])
def flags_of(line, word):
    return next((fl for fl, t in line[1] if word in t), None)
check(r[0][0] == "h1" and P(r[0]) == "Title", "Markdown heading")
body = next(l for l in r if "bold" in P(l))
check(P(body) == "Some bold and italic and code and both and gone.", "inline marks taken out of the words")
check(flags_of(body, "bold") == {"b"} and flags_of(body, "italic") == {"i"} and flags_of(body, "code") == {"code"}
      and flags_of(body, "both") == {"b", "i"} and flags_of(body, "gone") == {"s"},
      "...and kept as styles: bold, italic, code, bold italic, strikethrough")
check(any(P(l) == "• one" for l in r) and any(P(l) == "☑ done" for l in r), "lists and tasks")
check(any(l[0] == "quote" for l in r) and any(l[0] == "rule" for l in r) and ("code", [(frozenset({"code"}), "x = 1")]) in r,
      "quote, divider, code block")
link = next(l for l in r if "site" in P(l))
check(P(link) == "site (https://example.org)" and flags_of(link, "site") == {"link"}, "links: styled text, address kept")
check(any(P(l) == "snake_case and 2*3*4 stay as they are" and all(not fl for fl, _ in l[1]) for l in r),
      "underscores inside words and lone stars are left alone")
mi = "> Section\n`!Bold`! and `*it`* `Ff00red`f\n`[Home`:/page/index.mu]\n# a comment\n-"
r = markup.render(mi, markup.MICRON)
check(r[0][0] == "h1" and P(r[0]) == "Section" and P(r[1]) == "Bold and it red", f"Micron heading and tags")
check(flags_of(r[1], "Bold") == {"b"} and flags_of(r[1], "it") == {"i"}, "Micron bold and italic kept as styles")
check(P(r[2]) == "Home (:/page/index.mu)" and ("rule", []) in r and not any("comment" in P(l) for l in r),
      "Micron links, dividers, comments")
r = markup.render("[b]x[/b] [i]y[/i] [url=http://a]here[/url]", markup.BBCODE)
check(P(r[0]) == "x y here (http://a)" and flags_of(r[0], "x") == {"b"} and flags_of(r[0], "y") == {"i"}, "BBCode")
check(P(markup.render("*not markdown*", markup.PLAIN)[0]) == "*not markdown*", "plain text left alone")
mid = core.store.add_message(THEM, False, md, "received", renderer=2)
check(core.store.message(mid)["renderer"] == 2, "the renderer is kept with the message")

from firefly.ui.app import App
from firefly.ui import screens
import pygame
app = App(core, size=(720, 720))
app.push(screens.ChatScreen(app, THEM)); app.render()
pygame.image.save(app.display.screen, os.path.join(tempfile.gettempdir(), "interop_chat.png"))
check(True, "a chat with a formatted message draws")
core.stop()
print("ALL PASSED" if ok else "SOME FAILED")
sys.stdout.flush(); os._exit(0 if ok else 1)
