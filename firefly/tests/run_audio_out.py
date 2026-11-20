"""Voice notes follow a USB sound device, as Ember does (its PR #4): USB-C
headphones when plugged in (a USB MIDI keyboard, which has no playback, is
skipped), the built-in card otherwise, FIREFLY_OUT to fix it; a USB device
that fails falls back to the built-in card. With a pretend /proc/asound and a
stand-in aplay.   python3 tests/run_audio_out.py"""
import os, sys, tempfile, time, wave
os.environ["SDL_VIDEODRIVER"] = "dummy"; os.environ["SDL_AUDIODRIVER"] = "dummy"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from firefly import voice
ok = True
def check(c, w):
    global ok; print(("  PASS " if c else "  FAIL ") + w); ok = ok and bool(c)

t = tempfile.mkdtemp()
asound = os.path.join(t, "asound")
def cards(*entries):
    """entries: (number, driver, name, playback pcms)"""
    import shutil
    shutil.rmtree(asound, True); os.makedirs(asound)
    with open(os.path.join(asound, "cards"), "w") as f:
        for n, drv, name, pcms in entries:
            f.write(" %d [%-15s]: %s - %s\n                      %s\n" % (n, name[:15], drv, name, name))
            os.makedirs(os.path.join(asound, "card%d" % n))
            for p in pcms:
                os.makedirs(os.path.join(asound, "card%d" % n, p))
BUILTIN = (0, "rk817-codec", "rockchip,rk817-codec", ["pcm0p", "pcm0c"])
MIDI = (1, "USB-Audio", "Arturia MiniLab mkII", [])
PHONES = (2, "USB-Audio", "USB-C to 3.5mm Headphone Jack Adapter", ["pcm0c", "pcm0p"])

cards(BUILTIN)
check(voice.pick_output(asound) == (None, "built-in"), "nothing plugged in: the built-in card")
cards(BUILTIN, MIDI)
check(voice.pick_output(asound) == (None, "built-in"), "a USB MIDI keyboard (no playback) isn't a sound device")
cards(BUILTIN, MIDI, PHONES)
check(voice.pick_output(asound) == ("plughw:2,0", "USB: USB-C to 3.5mm Headphone Jack Adapter"),
      "USB-C headphones plugged in: played on them")
os.environ["FIREFLY_OUT"] = "plughw:0,0"
check(voice.pick_output(asound) == ("plughw:0,0", "plughw:0,0"), "FIREFLY_OUT fixes the output")
del os.environ["FIREFLY_OUT"]
check(voice.find_usb_output(os.path.join(t, "none")) is None, "no /proc/asound (a desktop without ALSA): built-in")

# -- the player, with a stand-in aplay ------------------------------------------
bindir = os.path.join(t, "bin"); os.makedirs(bindir)
log_path = os.path.join(t, "aplay.log")
with open(os.path.join(bindir, "aplay"), "w") as f:
    f.write("#!/bin/sh\necho \"$@\" >> %s\ncase \"$*\" in *plughw:9,0*) echo 'cannot open plughw:9,0' >&2; exit 1;; esac\n"
            "sleep 0.3\n" % log_path)
os.chmod(os.path.join(bindir, "aplay"), 0o755)
os.environ["PATH"] = bindir + os.pathsep + os.environ["PATH"]
wav = os.path.join(t, "note.wav")
with wave.open(wav, "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000); w.writeframes(b"\0\0" * 8000)
voice.decode_to_wav = lambda path, mode, expected=None: wav       # (decoding is run_voice.py's)
voice.ASOUND = asound
vp = voice.pick_output
voice.pick_output = lambda asound=None: vp(voice.ASOUND)

def play(p, i):
    p.play(i, wav, voice.OPUS_OGG)
    for _ in range(200):
        p.pump()
        if getattr(p, "_started", None):
            break
        time.sleep(0.01)
    for _ in range(300):
        if not p.busy():
            break
        time.sleep(0.01)

logs = []
p = voice.Player(log=logs.append)
cards(BUILTIN, PHONES)
check(p.output == "USB: USB-C to 3.5mm Headphone Jack Adapter", "SETUP shows where notes play")
play(p, 1)
check(open(log_path).read().split()[:3] == ["-q", "-D", "plughw:2,0"], "a note plays on the headphones (aplay -D plughw:2,0)")
check(p.method == "aplay plughw:2,0" and p.last_result[2] == "aplay plughw:2,0", "... and says so")
open(log_path, "w").close(); del p._started
cards(BUILTIN)                        # unplugged between notes
play(p, 2)
check("-D" not in open(log_path).read(), "unplugged: the next note plays on the built-in card")
check(p.output == "built-in", "... and SETUP says built-in")
open(log_path, "w").close(); del p._started
cards(BUILTIN, (9, "USB-Audio", "Flaky DAC", ["pcm0p"]))
play(p, 3)
check("plughw:9,0" in open(log_path).read(), "a USB device that fails ...")
check(p.output == "built-in" and any("failed; playing on the built-in card" in l for l in logs),
      "... falls back to the built-in card, as Ember does")
check(p.error is None or "Stopped after" not in (p.error or ""), "no error for the note")
print("all passed" if ok else "FAILURES")
os._exit(0 if ok else 1)
