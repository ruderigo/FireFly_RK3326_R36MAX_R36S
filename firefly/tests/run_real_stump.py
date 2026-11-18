"""FireFly against a real, unmodified Stump (SandBox_Stump_On on a computer), over a
simulated LoRa channel: FireFly's RNode on a pseudo-terminal and the Stump's
"Heltec over Wi-Fi" on TCP 7633 hear each other.

Set up the Stump once (from a SandBox_Stump_On checkout):
    python3 provisioner.py --pc --answers-template > a.json
    # in a.json: "the heltec": "Over Wi-Fi", "start ... when you log in": false
    python3 provisioner.py --pc /path/to/Stump --answers a.json
    # in /path/to/Stump/config.py: the Heltec Bridge's target_host -> '127.0.0.1'
Then:
    STUMP_DIR=/path/to/Stump python3 tests/run_real_stump.py

Skipped (exit 0) when STUMP_DIR isn't set.
"""
import os, subprocess, sys, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

STUMP_DIR = os.environ.get("STUMP_DIR")
if not STUMP_DIR:
    print("  (STUMP_DIR not set: no real Stump to test against, skipped)")
    sys.exit(0)

from fake_rnode import FakeRNode, TcpRNode, link
from firefly.paths import Paths
from firefly.settings import Settings
from firefly.core import Core
from firefly.radio import RadioStatus as RS
from firefly import stump

ok = True
def check(cond, what):
    global ok
    print(("  PASS " if cond else "  FAIL ") + what, flush=True)
    ok = ok and bool(cond)
def wait(fn, secs):
    t = time.time()
    while time.time() - t < secs:
        try:
            if fn():
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False

band = (902e6, 928e6)
stump_radio = TcpRNode(7633, band=band)          # the Stump's Heltec
ff_radio = FakeRNode(band=band, fw=(1, 86))       # FireFly's Heltec
link(stump_radio, ff_radio)

py = os.path.join(STUMP_DIR, "venv", "bin", "python")
log = open(os.path.join(tempfile.mkdtemp(), "stump.log"), "w")
node = subprocess.Popen([py if os.path.exists(py) else sys.executable, "stump_pc.py"], cwd=STUMP_DIR,
                        stdout=log, stderr=subprocess.STDOUT)
print("Stump started, log:", log.name, flush=True)

tmp = tempfile.mkdtemp(); paths = Paths(tmp); paths.ensure()
s = Settings(paths.settings); s["auto_interface"] = False; s["share_instance"] = False
s["display_name"] = "R36 Tester"; s["log_level"] = 2; s.save()
core = Core(paths, log=lambda *a: None)
# What LXMF hands FireFly and what FireFly hands LXMF, as on the air (packed text, beta.82).
wire_in, wire_out = [], []
_on_message = core._on_message
core._on_message = lambda lxm: (wire_in.append((time.time(), bytes(lxm.content or b""))), _on_message(lxm))
core.start()
_handle_outbound = core.router.handle_outbound
core.router.handle_outbound = lambda lxm: (wire_out.append(bytes(lxm.content or b"")), _handle_outbound(lxm))
core.radio.port_lister = lambda: [ff_radio.port]
core.radio.search_now()
try:
    check(wait(lambda: core.radio.status.state == RS.ONLINE, 30), "FireFly's radio online on the simulated channel")
    check(wait(lambda: stump_radio.conn is not None, 60), "the Stump connected to its Heltec (TCP 7633)")
    core.announce()
    check(wait(lambda: bool(core.stumps), 120), "the Stump recognised from its own stump.node beacon")
    if not core.stumps:
        raise SystemExit
    node_hex, (name, version) = next(iter(core.stumps.items()))
    print(f"     {name}  {version}  {node_hex}", flush=True)
    check(version.startswith("1.0.0-beta."), f"its release read from the beacon's sixth item ({version})")

    def lines():
        return [it for m in core.store.messages(node_hex) if not m["outgoing"]
                for it in stump.parse_message(m["content"], m["title"] or "")]

    core.announce()
    time.sleep(3)
    core.send(node_hex, "hello from FireFly")
    check(wait(lambda: core.stump_state.get(node_hex) and core.stump_state[node_hex].room == "lora-mesh", 90),
          "landed in #lora-mesh ('→ #lora-mesh')")
    core.send(node_hex, "/rooms")
    check(wait(lambda: any(it["kind"] == "room" for it in lines()), 90), "/rooms answered with room lines")
    core.send(node_hex, "/post FireFly test | posted over LoRa by the sandbox test")
    check(wait(lambda: any(it["kind"] == "posted" for it in lines()), 90), "/post answered '✓ #id'")
    core.send(node_hex, "/board")
    check(wait(lambda: any(it["kind"] == "notice" and "FireFly test" in it["title"] for it in lines()), 90),
          "/board lists the notice just posted")
    print("packed text (Stump 1.0.0-beta.82)", flush=True)
    from firefly import ztext
    import RNS.vendor.umsgpack as _mp
    mine = _mp.unpackb(core.router.get_announce_app_data(core.local.hash))
    check(len(mine) == 5 and mine[4] == {"z": 1}, f"FireFly announces it reads packed text: {mine[3:]}")
    check(wait(lambda: core.packs_for(node_hex), 60), "the Stump's own announce says z: FireFly will pack for it")
    core.announce()
    time.sleep(3)
    t0 = time.time()
    core.send(node_hex, "/help")
    def help_in():
        return [c for t, c in wire_in if t >= t0 and c[:1] == b"\xff" and len(ztext.unpack(c) or b"") > 295]
    check(wait(lambda: help_in(), 120), "the Stump's /help reply arrives packed (first byte 0xFF on the wire)")
    if help_in():
        c = help_in()[0]
        text = ztext.unpack(c).decode()
        print(f"     /help: {len(c)} bytes on the wire for {len(text.encode())} bytes of text", flush=True)
        check(len(c) <= 295 and any(text.split("\n")[0][:40] in m["content"] for m in core.store.messages(node_hex)
                                    if not m["outgoing"]), "... one packet, and FireFly shows it as text")
    n_out = len(wire_out)
    core.send(node_hex, "/join #packed-test")
    check(wait(lambda: core.stump_state[node_hex].room == "packed-test", 90)
          and any(c[:1] == b"\xff" for c in wire_out[n_out:]),
          "a line FireFly sends packed (/join #packed-test) is read by the Stump: '→ #packed-test'")
    core.send(node_hex, "/join #lora-mesh")
    wait(lambda: core.stump_state[node_hex].room == "lora-mesh", 60)
    from firefly import lan
    found = lan.find_stumps(["127.0.0.1", "255.255.255.255"], wait=2.0)
    check(node_hex in found, f"the same Stump answers STUMP? on the LAN: {found.get(node_hex, {}).get('name')} "
                             f"{found.get(node_hex, {}).get('http')}")
    print("chat over Wi-Fi (the Stump's web API)", flush=True)
    core.lan.poke()
    check(wait(lambda: core.web.get(node_hex) is not None and core.web[node_hex].online, 60),
          "greeted the Stump over Wi-Fi (/hello, both sides signed)")
    web = core.web.get(node_hex)
    if web is not None and web.online:
        print(f"     FireFly is {web.nick} at {web.base}", flush=True)
        mid = core.send(node_hex, "hello over Wi-Fi")
        check(wait(lambda: core.store.message(mid)["state"] == "delivered" and core.store.message(mid)["method"] == "wifi", 20),
              "a line sent over Wi-Fi: delivered, method wifi")
        # A person on the Stump's own web chat (a browser: it keeps the Stump's cookie).
        import http.cookiejar, urllib.request, json as _json
        jar = http.cookiejar.CookieJar()
        guest = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar))
        gbase = web.base.replace(web.base.split("//")[1].split("/")[0].split(":")[0], "127.0.0.1")
        guest.open(gbase + "/", timeout=8).read()
        guest.open(gbase + "/rrc/poll?room=main&since=0", timeout=8).read()
        gnick = _json.loads(guest.open(gbase + "/rrc/poll?room=main&since=0", timeout=8).read())["nick"]
        print(f"     web guest is {gnick}", flush=True)
        req = urllib.request.Request(gbase + "/rrc/send", data=f"/msg {web.nick} hi from the web chat".encode(), method="POST")
        guest.open(req, timeout=8).read()
        check(wait(lambda: any("hi from the web chat" in m["content"] and m["method"] == "wifi"
                                for m in core.store.messages(node_hex) if not m["outgoing"]), 20),
              "a DM from a web-chat user arrives over Wi-Fi as [DM] <guest>: …")
        core.send(node_hex, f"/msg {gnick} hi back from FireFly")
        def guest_got():
            d = _json.loads(guest.open(gbase + "/rrc/poll?room=main&since=0", timeout=8).read())
            return any("hi back from FireFly" in str(x.get("body")) for x in d.get("dms", []))
        check(wait(guest_got, 20), "FireFly's DM reaches the web-chat user")
        core.send(node_hex, "/join #wifitest")
        check(wait(lambda: core.stump_state[node_hex].room == "wifitest", 20), "/join over Wi-Fi moves FireFly's room")
    if web is not None:
        import re as _re, urllib.request as _u, html as _h
        page = _u.build_opener(_u.ProxyHandler({})).open(web.base + "/address", timeout=8).read().decode("utf-8", "replace")
        links = sorted(set(_h.unescape(x) for x in _re.findall(r"(lxm[af]://[^\s\"'<]+)", page)))
        from firefly import addresses as _a
        good = [l for l in links if (lambda p: p and p["address"] == node_hex and p["key"] is not None
                                      and _a.identity_for(node_hex, p["key"]) is not None)(_a.parse(l))]
        # The page shows its lxmf:// link as text; its lxma:// code is only in the QR picture.
        check(len(good) >= 1 and _a.parse(good[0])["stump"], f"the Stump's /address link reads, names it a Stump, "
                                                             f"and its key checks out: {good[0][:60] if good else None}…")
        check(good and _a.parse(good[0])["release"] == version,
              f"... and its r= (beta.79) is the beacon's release: {_a.parse(good[0])['release'] if good else None}")
    core.start_stump_auth(node_hex)
    check(wait(lambda: core.auth_state(node_hex).state == stump.AuthSession.OK, 120), "/auth handshake: AUTH-OK")
finally:
    print("--- last Stump-side lines seen by FireFly:")
    for m in core.store.messages(node_hex if core.stumps else "00" * 16)[-12:]:
        print("   ", "<" if not m["outgoing"] else ">", (m["title"] or "") + " " + m["content"].replace("\n", " | ")[:150])
    core.stop()
    node.terminate()
    try:
        node.wait(10)
    except Exception:
        node.kill()
    print("ALL PASSED" if ok else "SOME FAILED", flush=True)
    sys.stdout.flush()
    os._exit(0 if ok else 1)
