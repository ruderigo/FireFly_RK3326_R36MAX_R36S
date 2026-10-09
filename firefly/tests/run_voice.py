"""Voice notes, checked against the "Voice notes over LXMF: Codec 2
interoperability spec" (FireFly for Android, 3 Oct 2026) and its test vector.

A peer sends, over real LXMF: the spec's test vector exactly as the spec says
(raw Codec 2 1200 frames, empty content and title), a 15 s Codec 2 2400 note,
an Opus note (Sideband), a note with a Codec 2 file header, a removed 450 mode,
and a malformed field. FireFly must decode Codec 2 byte-for-byte like Codec 2's
own c2dec, survive the bug of 0.5.0-0.5.2, copy notes to the SD card, and play
them whole.   python3 tests/run_voice.py"""
import glob, hashlib, os, subprocess, sys, tempfile, threading, time, wave
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
SD = tempfile.mkdtemp(prefix="sdcard-")
os.environ["FIREFLY_SD"] = SD                       # stands in for /roms on the handheld
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from firefly.paths import Paths
from firefly.settings import Settings
from firefly.core import Core
from firefly import voice
import LXMF

ok = True
def check(c, what):
    global ok
    print(("  PASS " if c else "  FAIL ") + what); ok = ok and bool(c)
def wait(fn, secs):
    t = time.time()
    while time.time() - t < secs:
        if fn(): return True
        time.sleep(0.3)
    return False
def pcm(wav):
    with wave.open(wav) as w:
        return w.readframes(w.getnframes())
def c2dec_reference(mode_name, data):
    """What Codec 2's own decoder makes of these bytes (named .bit, as the spec says)."""
    d = tempfile.mkdtemp()
    open(os.path.join(d, "n.bit"), "wb").write(data)
    subprocess.run(["c2dec", mode_name, os.path.join(d, "n.bit"), os.path.join(d, "n.raw")], check=True, capture_output=True)
    return open(os.path.join(d, "n.raw"), "rb").read()

here = os.path.dirname(os.path.abspath(__file__)); tmp = tempfile.mkdtemp()
VECTOR = open(os.path.join(here, "data", "kristoff_1200.bit"), "rb").read()
check(hashlib.sha256(VECTOR).hexdigest() == "7ba18f754933bab5201157faa0ffb6edf2d7cb4859418e2231f2ce30be56bd14",
      "test vector matches the spec's SHA-256")

peer = subprocess.Popen([sys.executable, "-u", os.path.join(here, "peer.py"), os.path.join(tmp, "bob"), "47801"],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
line = peer.stdout.readline()
while "PEER ready" not in line: line = peer.stdout.readline()
bob = line.split()[2]
paths = Paths(os.path.join(tmp, "me")); paths.ensure()
s = Settings(paths.settings); s["radio"]["enabled"] = False; s["auto_interface"] = False; s["share_instance"] = False
s["tcp_peers"] = ["127.0.0.1:47801"]; s["log_level"] = 2; s.save()
core = Core(paths, log=lambda *a: None); core.start()
wait(lambda: (core.store.peer(bob) or {}).get("name"), 20)
core.send(bob, "voice?")
check(wait(lambda: len(core.store.voice_notes(bob)) >= 5, 90), "received five voice notes")
check(wait(lambda: any(m["content"] == "malformed field" for m in core.store.messages(bob)), 30),
      "a message with a malformed audio field arrives as text, without a voice note")
mal = [m for m in core.store.messages(bob) if m["content"] == "malformed field"]
check(mal and mal[0]["audio_mode"] is None, "  ...its malformed field ([mode, 750]) is ignored, not turned into silence")

notes = core.store.voice_notes(bob, 50)
vec = [m for m in notes if m["audio_mode"] == LXMF.AM_CODEC2_1200][0]
c24 = [m for m in notes if m["audio_mode"] == LXMF.AM_CODEC2_2400][0]
ogg = [m for m in notes if m["audio_mode"] == LXMF.AM_OPUS_OGG][0]
hdr = [m for m in notes if m["audio_mode"] == LXMF.AM_CODEC2_1300][0]
odd = [m for m in notes if m["audio_mode"] == LXMF.AM_CODEC2_450][0]

# --- the spec's test vector
check(open(vec["audio_path"], "rb").read() == VECTOR, "test vector stored byte-for-byte (750 bytes)")
check(vec["audio_secs"] == 5.0, f"duration before decoding: {vec['audio_secs']:.2f} s (spec: 125 frames = 5.00 s)")
check(vec["content"] == "" and vec["title"] == "", "empty content and title, as the spec sends it")
got = pcm(voice.decode_to_wav(vec["audio_path"], vec["audio_mode"], vec["audio_secs"]))
check(len(got) // 2 == 40000, f"decodes to {len(got)//2} samples (spec: 40,000)")
check(got == c2dec_reference("1200", VECTOR), "decoded audio identical to Codec 2's own c2dec, byte for byte")

# --- the bug of 0.5.0-0.5.2, on a note stored then: raw frames under a .c2 name, garbled WAV cached
legacy = vec["audio_path"].rsplit(".", 1)[0] + ".c2"
open(legacy, "wb").write(VECTOR)
subprocess.run(["c2dec", "1200", legacy, legacy + ".raw"], capture_output=True)
bad = open(legacy + ".raw", "rb").read()
with wave.open(legacy + ".wav", "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000); w.writeframes(bad)
print(f"     0.5.x made {len(bad)//2/8000:.1f} s of noise out of this 5.0 s note")
fixed = pcm(voice.decode_to_wav(legacy, LXMF.AM_CODEC2_1200, 5.0))
check(fixed == c2dec_reference("1200", VECTOR), "a note stored by 0.5.x is decoded again, correctly")

# --- other formats
check(c24["audio_secs"] == 15.0, f"Codec 2 2400 (20 ms frames): {c24['audio_secs']:.2f} s")
check(pcm(voice.decode_to_wav(c24["audio_path"], c24["audio_mode"], 15.0)) ==
      c2dec_reference("2400", open(c24["audio_path"], "rb").read()), "  ...decoded byte-for-byte like c2dec")
check(hdr["audio_secs"] == 15.0, "a Codec 2 file header is recognised (its mode, 2400, overrides the field's 1300)")
h_frames = open(hdr["audio_path"], "rb").read()[7:]
check(pcm(voice.decode_to_wav(hdr["audio_path"], hdr["audio_mode"], 15.0)) == c2dec_reference("2400", h_frames),
      "  ...and decoded correctly")
check(abs(ogg["audio_secs"] - 15.0) < 0.1 and ogg["content"] == "listen to this", "Opus (Sideband): 15 s, text kept")
check(abs(voice.wav_seconds(voice.decode_to_wav(ogg["audio_path"], ogg["audio_mode"])) - 15.0) < 0.1, "  ...decodes to 15 s")
check(not voice.row_playable(odd), f"removed 450 mode shown as unsupported: '{voice.describe(odd['audio_mode'])}'")

# --- Opus the spec's way (FireFly's default now): 16 kHz mono, 8 kbit/s constrained VBR, 60 ms frames
spec_ogg = open(os.path.join(here, "data", "kristoff_opusenc_8k.ogg"), "rb").read()
info = voice.ogg_opus_info(spec_ogg)
check(info and info["ms"] == 5000 and info["pre_skip"] == 312 and info["channels"] == 1,
      f"spec-style Opus note: {info['ms']} ms, pre-skip {info['pre_skip']} (spec: 5,000 ms, 312)")
check(voice.label(info["ms"]) == "5.0 s", "labelled '5.0 s', like a Stump's '♪ 5.0 s'")
check([voice.label(x) for x in (2250, 2249, 15050)] == ["2.3 s", "2.2 s", "15.1 s"], "labels round tenths half up")
check([voice.duration_ms(m, b"x" * n) for m, n in ((LXMF.AM_CODEC2_1200, 751), (LXMF.AM_CODEC2_1200, 270),
       (LXMF.AM_CODEC2_3200, 2000), (LXMF.AM_CODEC2_700C, 31))] == [5000, 1800, 5000, 280], "Codec 2 lengths match the spec's table")
# not a valid Opus note: stereo-plus mapping, wrong magic, truncated
bad_head = bytearray(spec_ogg); i = bad_head.find(b"OpusHead"); bad_head[i + 18] = 1          # mapping family 1
check(voice.ogg_opus_info(bytes(bad_head)) is None and voice.ogg_opus_info(spec_ogg[:200]) is None
      and voice.ogg_opus_info(b"OggS" + b"\0" * 60) is None, "invalid Opus files are recognised as unplayable")
d = tempfile.mkdtemp(); pth = voice.save(d, "spec", LXMF.AM_OPUS_OGG, spec_ogg)
check(abs(voice.wav_seconds(voice.decode_to_wav(pth, LXMF.AM_OPUS_OGG, 5.0)) - 5.0) < 0.01, "  ...and decodes to 5.00 s")

# --- one decode at a time per note (the 0.5.1 race)
for m in (vec, ogg):
    for f in glob.glob(m["audio_path"] + ".wav*"):
        os.remove(f)
    results = []
    th = [threading.Thread(target=lambda m=m: results.append(
        len(pcm(voice.decode_to_wav(m["audio_path"], m["audio_mode"], m["audio_secs"]))))) for _ in range(6)]
    [t.start() for t in th]; [t.join() for t in th]
    check(len(set(results)) == 1 and results[0] == len(pcm(m["audio_path"] + ".wav")),
          f"{voice.describe(m['audio_mode'])}: 6 decodes at once all get the complete note")

# --- SD card copies
folder = os.path.join(SD, "firefly-voice")
check(wait(lambda: os.path.isdir(folder) and len(glob.glob(os.path.join(folder, "*.wav"))) == 4, 30),
      "all four playable notes copied to the SD card as WAV, automatically")
idx = open(os.path.join(folder, "voice-notes.txt")).read()
check("Codec2 1200\t750 bytes received\tlength in message 5.0s\tdecoded 5.0s" in idx, "index line for the vector is right")
vec_sd = glob.glob(os.path.join(folder, "*_%d.wav" % vec["id"]))[0]
check(pcm(vec_sd) == c2dec_reference("1200", VECTOR), "the WAV on the card is the correct audio")
with wave.open(vec_sd, "wb") as w:                    # a cut-short copy, as 0.5.x could leave
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000); w.writeframes(bad[:16000])
core.export_voice_notes()
check(pcm(vec_sd) == c2dec_reference("1200", VECTOR) and "replaces a copy that was cut short" in
      open(os.path.join(folder, "voice-notes.txt")).read(), "a bad copy on the card is replaced, and the index says so")
copied, _, errors = core.export_voice_notes()
check(copied == 0 and not errors, "copying again changes nothing")

# --- playback, whole
import pygame
pygame.display.init(); pygame.display.set_mode((100, 100))
p = voice.Player(log=lambda *a: None)
p.play(vec["id"], vec["audio_path"], vec["audio_mode"], vec["audio_secs"])
t = time.time()
while p.playing_id is not None and time.time() - t < 15:
    p.pump(); time.sleep(0.05)
played, total, how = p.last_result
print(f"     played {played:.1f} s of {total:.1f} s via {how}")
check(total == 5.0 and played > total - 1.0 and p.error is None, "plays the whole note")
core.stop(); peer.terminate()
print("ALL PASSED" if ok else "SOME FAILED"); sys.stdout.flush(); os._exit(0 if ok else 1)
