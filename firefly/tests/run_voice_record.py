"""Recording and sending voice notes: the mic chosen as Ember does (a USB mic or
headset first), up to 15 s, Codec 2 1200 (LoRa) or Opus (a Stump's Wi-Fi),
sent in the LXMF audio field to a person, or through a Stump as /msg <name>
(LoRa) or POST /rrc/voice (Wi-Fi); a Stump's refusal isn't retried over LoRa.
A stand-in arecord speaks a tone; c2enc and opusenc are the real ones.
   python3 tests/run_voice_record.py"""
import math, os, shutil, struct, sys, tempfile, time
os.environ["SDL_VIDEODRIVER"] = "dummy"; os.environ["SDL_AUDIODRIVER"] = "dummy"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import LXMF
from firefly import voice
ok = True
def check(c, w):
    global ok; print(("  PASS " if c else "  FAIL ") + w); ok = ok and bool(c)

if not (shutil.which("c2enc") and shutil.which("opusenc")):
    print("SKIP: needs c2enc (codec2) and opusenc (opus-tools)"); os._exit(0)

t = tempfile.mkdtemp()
# -- the mic, as Ember picks it ---------------------------------------------------
asound = os.path.join(t, "asound"); os.makedirs(asound)
with open(os.path.join(asound, "cards"), "w") as f:
    f.write(" 0 [rockchiprk817 ]: rk817-codec - rockchip,rk817-codec\n"
            " 1 [Device         ]: USB-Audio - USB-C Headset\n")
for d in ("card0/pcm0p", "card0/pcm0c", "card1/pcm0p", "card1/pcm0c"):
    os.makedirs(os.path.join(asound, d))
check(voice.pick_mic(asound) == ("plughw:1,0", "USB: USB-C Headset"), "a USB headset's mic first")
shutil.rmtree(os.path.join(asound, "card1", "pcm0c"))
check(voice.pick_mic(asound) == (None, "built-in"), "headphones without a mic: the built-in mic")
os.environ["FIREFLY_MIC"] = "plughw:2,0"
check(voice.pick_mic(asound)[0] == "plughw:2,0", "FIREFLY_MIC fixes it")
del os.environ["FIREFLY_MIC"]

# -- a stand-in arecord: 16 kHz mono 16-bit, a wobbling tone, as long as asked ----
bindir = os.path.join(t, "bin"); os.makedirs(bindir)
tone = os.path.join(t, "tone.raw")
with open(tone, "wb") as f:
    f.write(b"".join(struct.pack("<h", int(9000 * math.sin(2 * math.pi * (200 + 60 * math.sin(i / 2000)) * i / 16000)))
                     for i in range(16000 * 20)))
with open(os.path.join(bindir, "arecord"), "w") as f:
    f.write("#!/bin/sh\necho \"$@\" > %s/arecord.args\n"
            "python3 -c 'import sys,time\nd=open(sys.argv[1],\"rb\").read()\nfor i in range(0,len(d),3200):\n"
            " sys.stdout.buffer.write(d[i:i+3200]); sys.stdout.flush(); time.sleep(float(sys.argv[2]))' %s ${FAKE_PACE:-0.01}\n"
            % (t, tone))
os.chmod(os.path.join(bindir, "arecord"), 0o755)
os.environ["PATH"] = bindir + os.pathsep + os.environ["PATH"]

r = voice.Recorder(log=lambda *a: None)
check(r.start() and r.recording, "recording starts")
time.sleep(0.4)
check(r.level > 0.1, f"the mic's level is read while recording ({r.level:.2f})")
secs = r.stop()
check(0.5 < secs < 15 and not r.recording, f"stopped by hand: {secs:.1f} s")
check("-r 16000" in open(os.path.join(t, "arecord.args")).read(), "recorded at 16 kHz mono")
r2 = voice.Recorder(log=lambda *a: None); r2.start()
for _ in range(400):
    if not r2.recording:
        break
    time.sleep(0.05)
check(not r2.recording and abs(r2.seconds - 15.0) < 0.01, f"it stops itself at 15 s ({r2.seconds:.2f} s)")
c2 = voice.encode(r2.pcm, voice.SEND_CODEC2)
check(voice.duration_ms(voice.SEND_CODEC2, c2) == 15000 and len(c2) == 2250, f"Codec 2 1200: 15 s in {len(c2)} bytes")
op = voice.encode(r2.pcm, voice.OPUS_OGG, voice.STUMP_MAX_BYTES)
check(abs(voice.duration_ms(voice.OPUS_OGG, op) - 15000) <= 100 and len(op) <= voice.STUMP_MAX_BYTES,
      f"Opus: 15 s in {len(op)} bytes, under a Stump's 16 KB")
wav = voice.decode_to_wav(voice.save(t, "c2back", voice.SEND_CODEC2, c2), voice.SEND_CODEC2, 15.0)
check(abs(voice.wav_seconds(wav) - 15.0) < 0.1, "... and our own Codec 2 note plays back whole")

# -- sending ---------------------------------------------------------------------
from firefly.paths import Paths
from firefly.settings import Settings
from firefly.core import Core
p = Paths(os.path.join(t, "ff")); p.ensure()
s = Settings(p.settings); s["radio"]["enabled"] = False; s["auto_interface"] = False; s["share_instance"] = False; s.save()
c = Core(p, log=lambda *a: None); c.start()
bob, stp = "823de26f44824bc5d37611af7851414c", "a8e7c0e088fc474c34360e91059be857"
c.store.upsert_peer(bob, "lxmf", name="Bob", hops=2)
c.store.upsert_peer(stp, "lxmf", name="LaBuche", hops=1, stump="LaBuche", stump_ver="1.0.0-beta.87")
c.stumps[stp] = ("LaBuche", "1.0.0-beta.87")
lora = []
c._send_worker = lambda msg_id, peer, text, method, title, fields=None: lora.append((peer, text, fields))
check(c.voice_mode_for(bob) == voice.SEND_CODEC2, "to a person over LoRa: Codec 2, LoRa-sized")
mid = c.send_voice(bob, voice.SEND_CODEC2, c2); time.sleep(0.3)
check(lora and lora[-1][0] == bob and lora[-1][1] == "" and lora[-1][2] == {LXMF.FIELD_AUDIO: [voice.SEND_CODEC2, c2]},
      "to Bob: the LXMF audio field [mode, bytes], as Sideband sends")
m = [x for x in c.store.messages(bob) if x["id"] == mid][0]
check(m["outgoing"] and m["audio_mode"] == voice.SEND_CODEC2 and abs(m["audio_secs"] - 15.0) < 0.01
      and os.path.isfile(m["audio_path"]), "kept in the chat, playable, with its length")
try:
    c.send_voice(stp, voice.SEND_CODEC2, c2); check(False, "a Stump needs a name")
except voice.VoiceError:
    check(True, "through a Stump without a name: refused (a note there is a DM)")
lora.clear(); c.send_voice(stp, voice.SEND_CODEC2, c2, "zoe"); time.sleep(0.3)
check(lora and lora[-1][1] == "/msg zoe" and lora[-1][2][LXMF.FIELD_AUDIO][0] == voice.SEND_CODEC2,
      "through a Stump over LoRa: '/msg zoe' with the note attached")

class FakeWeb:
    online, name, lxmf = True, "LaBuche", stp
    def __init__(self, answer): self.answer, self.got = answer, []
    def send_voice(self, to, mode, data):
        self.got.append((to, mode, len(data)))
        from firefly.stumpweb import Refused
        if not self.answer.startswith("[DM]"):
            raise Refused(self.answer)
        return [self.answer]
c.web[stp] = FakeWeb("[DM] <r36max>: ♪ 15.0 s")
check(c.voice_mode_for(stp) == voice.OPUS_OGG, "through a Stump on its Wi-Fi: Opus")
lora.clear(); mid = c.send_voice(stp, voice.OPUS_OGG, op, "zoe"); time.sleep(0.3)
check(c.web[stp].got == [("zoe", voice.OPUS_OGG, len(op))] and not lora, "over its Wi-Fi: POST /rrc/voice to zoe")
check([x for x in c.store.messages(stp) if x["id"] == mid][0]["state"] == "delivered", "... delivered")
c.web[stp] = FakeWeb("⊖ nobody by that name")
lora.clear(); mid = c.send_voice(stp, voice.OPUS_OGG, op, "nobody"); time.sleep(0.3)
row = [x for x in c.store.messages(stp) if x["id"] == mid][0]
check(row["state"] == "failed" and "nobody" in (row["reason"] or "") and not lora,
      "refused by the Stump: failed with its reason, not retried over LoRa")
c.settings["voice_send"] = "codec2"
check(c.voice_mode_for(stp) == voice.SEND_CODEC2, "SETUP 'Send as' Codec 2 wins")
c.settings["voice_send"] = "auto"

# -- the screen --------------------------------------------------------------------
import pygame
from firefly.ui.app import App
from firefly.ui.screens import ChatScreen, RecordScreen
del c.web[stp]
app = App(c, size=(640, 480))
app.push(ChatScreen(app, bob)); app.current.handle("y")
labels = [l for l, _ in app.current.items]
check(labels[0] == "Record a voice note", "a person's chat menu: Record a voice note")
app.current.items[0][1](); scr = app.current
check(isinstance(scr, RecordScreen) and scr.mode == voice.SEND_CODEC2, "the recorder opens, Codec 2 for LoRa")
os.environ["FAKE_PACE"] = "0.005"
scr.handle("a"); app.render()
check(scr.state == "recording" and ("A", "stop") in scr.hints, "A records")
time.sleep(0.5); app.render(); scr.handle("a")
for _ in range(100):
    if scr.state == "recorded":
        break
    time.sleep(0.05)
app.render()
check(scr.state == "recorded" and scr.data and ("X", "listen") in scr.hints, "A stops; it's encoded, ready to listen or send")
scr.handle("y")
for _ in range(100):
    if scr.state == "recorded" and scr.mode == voice.OPUS_OGG:
        break
    time.sleep(0.05)
check(scr.mode == voice.OPUS_OGG and scr.data[:4] == b"OggS", "Y switches to Opus (encoded again)")
lora.clear(); scr.handle("a"); time.sleep(0.3)
check(lora and lora[-1][2][LXMF.FIELD_AUDIO][0] == voice.OPUS_OGG and not isinstance(app.current, RecordScreen),
      "A sends it, and the recorder closes")
app.stack.clear(); chat = ChatScreen(app, stp); app.push(chat); app.render(); chat.handle("y")
check(any(l.startswith("Voice note to someone on this Stump") for l, _ in app.current.items),
      "a Stump's menu: a voice note to someone on it")
app.pop()
os.environ["FAKE_PACE"] = "0.1"                  # the stand-in mic at real speed
app.push(RecordScreen(app, bob)); scr = app.current
scr.handle("a"); time.sleep(0.3); scr.handle("a"); app.render()
check(scr.state == "ready" and "Too short" in (scr.error or ""), "under 0.6 s: too short, not sent")
for size in ((640, 480), (720, 720)):
    a2 = App(c, size=size); a2.push(RecordScreen(a2, stp, "zoe")); a2.render()
check(True, "draws at 640x480 and 720x720")
c.stop()
print("all passed" if ok else "FAILURES")
os._exit(0 if ok else 1)
