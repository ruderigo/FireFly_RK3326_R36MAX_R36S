"""The radio manager against simulated RNodes: start-up without a radio,
finding any RNode among other devices, live retuning, a board that refuses
the band, old firmware (must not crash the app), unplug and a different
board plugged in.   python3 tests/run_radio.py"""
import os, sys, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from fake_rnode import FakeRNode
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

tmp = tempfile.mkdtemp(); paths = Paths(tmp); paths.ensure()
s = Settings(paths.settings); s["auto_interface"] = False; s["share_instance"] = False; s["log_level"] = 2; s.save()

devices = []                       # what "USB" currently shows
t0 = time.time()
core = Core(paths, log=lambda *a: None); core.start()
check(time.time() - t0 < 5, f"starts without any radio ({time.time()-t0:.1f}s)")
core.radio.port_lister = lambda: [d.port for d in devices]
check(wait(lambda: core.radio.status.state == RS.NO_DEVICES, 5), "reports 'no devices' when nothing is plugged in")

gps = FakeRNode(answers=False)                     # some other USB serial device
board = FakeRNode(band=(902e6, 928e6))             # a 915 MHz RNode
devices += [gps, board]
core.radio.search_now()
check(wait(lambda: core.radio.status.state == RS.ONLINE, 20), "finds the RNode among other serial devices")
check(core.radio.status.port == board.port, "  ...on the right port")
st = core.radio.status
print("     board:", st.board)
names = [i.get("name", "") for i in core.interface_stats().get("interfaces", [])]
check(any("RNode" in n for n in names), "RNode interface is live in Reticulum")
check(board.freq == 915_000_000 and board.sf == 8 and board.txp == 7, "radio tuned to the settings (915 MHz, SF8, 7 dBm)")

core.settings["radio"]["spreading_factor"] = 10
core.settings["radio"]["frequency"] = 920_000_000
core.radio.request_apply(delay=0.5)
check(wait(lambda: board.sf == 10 and board.freq == 920_000_000 and core.radio.status.state == RS.ONLINE, 20),
      "retunes live, no restart (920 MHz, SF10)")

core.settings["radio"]["frequency"] = 868_000_000   # outside this board's band
core.radio.request_apply(delay=0.2)
check(wait(lambda: core.radio.status.state == RS.REFUSED, 20), "a board refusing the band is reported, not hidden")
print("     says:", core.radio.status.detail)

core.settings["radio"]["frequency"] = 915_000_000
core.radio.request_apply(delay=0.2)
check(wait(lambda: core.radio.status.state == RS.ONLINE, 20), "back online once the settings fit the board")

board.unplug(); devices.remove(board)
check(wait(lambda: core.radio.status.state in (RS.SEARCHING, RS.NO_DEVICES), 20), "notices the RNode was unplugged")

old = FakeRNode(band=(902e6, 928e6), fw=(1, 40))
devices.append(old); core.radio.search_now()
check(wait(lambda: core.radio.status.state == RS.REFUSED, 20), "old firmware: reported, and the app is still running")
print("     says:", core.radio.status.detail)

other = FakeRNode(band=(902e6, 928e6), fw=(1, 85))  # a different board on a different port
devices.append(other); core.radio.search_now()
check(wait(lambda: core.radio.status.state == RS.ONLINE and core.radio.status.port == other.port, 25),
      "a different RNode plugged in is picked up automatically")

core.settings["radio"]["enabled"] = False; core.radio.request_apply(delay=0)
check(wait(lambda: core.radio.status.state == RS.OFF, 10), "radio can be switched off live")
core.stop()
print("ALL PASSED" if ok else "SOME FAILED")
sys.stdout.flush(); os._exit(0 if ok else 1)
