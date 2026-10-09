"""Voice notes: the standard LXMF audio field, as sent by Sideband and others.

FIELD_AUDIO holds [mode, bytes]:
  - Opus (AM_OPUS_OGG): a complete Ogg Opus file,
  - Codec2 (AM_CODEC2_700C ... AM_CODEC2_3200): raw Codec2 frames, 8 kHz mono,
    no header. Tiny: ~15 s of speech in ~2.3 KB, made for LoRa.

Decoding uses Debian's command-line decoders (`opusdec` from opus-tools,
`c2dec` from codec2), so FireFly needs no compiled audio libraries.
Playback uses pygame's mixer, falling back to `aplay`.
"""
import os
import shutil
import struct
import subprocess
import threading
import wave

import LXMF

# Codec2 mode -> (c2dec mode name, samples per frame, bytes per frame). 8 kHz.
CODEC2 = {
    LXMF.AM_CODEC2_700C: ("700C", 320, 4),
    LXMF.AM_CODEC2_1200: ("1200", 320, 6),
    LXMF.AM_CODEC2_1300: ("1300", 320, 7),
    LXMF.AM_CODEC2_1400: ("1400", 320, 7),
    LXMF.AM_CODEC2_1600: ("1600", 320, 8),
    LXMF.AM_CODEC2_2400: ("2400", 160, 6),
    LXMF.AM_CODEC2_3200: ("3200", 160, 8),
}
OPUS_OGG = LXMF.AM_OPUS_OGG

# A Codec2 *file* header (written by c2enc for .c2 files, and by some apps):
# magic C0 DE C2, version major, minor, mode, flags. LXMF voice notes from
# Sideband carry raw frames with NO header; never let c2dec guess.
C2_MAGIC = b"\xc0\xde\xc2"
C2_HEADER_LEN = 7
C2_HEADER_MODES = {0: LXMF.AM_CODEC2_3200, 1: LXMF.AM_CODEC2_2400, 2: LXMF.AM_CODEC2_1600,
                   3: LXMF.AM_CODEC2_1400, 4: LXMF.AM_CODEC2_1300, 5: LXMF.AM_CODEC2_1200,
                   8: LXMF.AM_CODEC2_700C}


MAX_AUDIO_BYTES = 64 * 1024       # the voice-note spec's cap


def parse_field(field):
    """Validate an LXMF FIELD_AUDIO value per the voice-note spec: a list of at
    least two items, an integer mode, then non-empty bytes of at most 64 KiB.
    Returns (mode, bytes) or None for an empty or malformed field."""
    if not isinstance(field, (list, tuple)) or len(field) < 2:
        return None
    mode, data = field[0], field[1]
    if isinstance(mode, bool) or not isinstance(mode, int):
        return None
    if not isinstance(data, (bytes, bytearray)) or not data or len(data) > MAX_AUDIO_BYTES:
        return None
    return mode, bytes(data)


def codec2_frames(mode, data):
    """(mode, raw frames). LXMF voice notes are raw frames with no header (the
    spec), so this only strips a Codec2 file header when it's unmistakable:
    magic, version 1.x, and a known mode. Raw speech frames can't plausibly
    start that way."""
    if (len(data) > C2_HEADER_LEN and data[:3] == C2_MAGIC and data[3] == 1
            and data[5] in C2_HEADER_MODES):
        return C2_HEADER_MODES[data[5]], data[C2_HEADER_LEN:]
    return mode, data


class VoiceError(Exception):
    pass


def describe(mode):
    if mode is None:
        return "unknown format"
    if mode in CODEC2:
        return "Codec2 " + CODEC2[mode][0]
    if mode == OPUS_OGG:
        return "Opus"
    if mode in (LXMF.AM_CODEC2_450, LXMF.AM_CODEC2_450PWB):
        return "Codec2 450"
    if LXMF.AM_OPUS_LBW <= mode <= LXMF.AM_OPUS_LOSSLESS:
        return "Opus (live-stream format)"
    return f"audio mode {mode}"


def can_play(mode, data=None):
    """Playable format; for Opus, with the bytes, also a valid single-stream mono/stereo file."""
    if mode in CODEC2:
        return True
    if mode == OPUS_OGG:
        return data is None or ogg_opus_info(data) is not None
    return False


def extension(mode):
    # Not ".c2": c2dec treats a .c2 file as having a header, and LXMF notes don't.
    return ".ogg" if mode == OPUS_OGG else ".codec2" if mode in CODEC2 else ".audio"


def duration(mode, data):
    """Seconds (from duration_ms). None if unknown."""
    ms = duration_ms(mode, data)
    return None if ms is None else ms / 1000.0


def ogg_opus_info(data):
    """Read an Ogg Opus file (RFC 7845) the way the voice-note spec asks.

    Pages are walked from the start; only the first logical stream counts.
    Its first packet must be OpusHead with 1 or 2 channels and mapping
    family 0. The length is (last granule position - pre-skip) / 48 in whole
    milliseconds, from the last page of that stream whose granule isn't -1.
    Returns {"ms", "channels", "pre_skip"} or None if it isn't such a file."""
    pos, serial, head, last_granule = 0, None, None, None
    n = len(data)
    while pos + 27 <= n:
        if data[pos:pos + 4] != b"OggS":
            return None                                   # not at a page boundary: malformed
        granule = struct.unpack_from("<q", data, pos + 6)[0]
        page_serial = struct.unpack_from("<I", data, pos + 14)[0]
        nseg = data[pos + 26]
        if pos + 27 + nseg > n:
            return None
        body_len = sum(data[pos + 27:pos + 27 + nseg])
        body = pos + 27 + nseg
        if body + body_len > n:
            return None
        if serial is None:
            serial = page_serial
            if data[body:body + 8] != b"OpusHead" or body_len < 19:
                return None
            channels, pre_skip, family = data[body + 9], struct.unpack_from("<H", data, body + 10)[0], data[body + 18]
            if channels not in (1, 2) or family != 0:
                return None
            head = (channels, pre_skip)
        elif page_serial == serial and granule != -1:
            last_granule = granule
        pos = body + body_len
    if head is None or last_granule is None:
        return None
    return {"ms": max(0, (last_granule - head[1]) // 48), "channels": head[0], "pre_skip": head[1]}


def duration_ms(mode, data):
    """The note's length in whole milliseconds, computed from its bytes only
    (never a timer), exactly as the voice-note spec defines it. None if unknown."""
    try:
        if mode in CODEC2:
            mode, frames = codec2_frames(mode, data)
            _, spf, bpf = CODEC2[mode]
            return (len(frames) // bpf) * (spf // 8)       # spf samples at 8 kHz = spf/8 ms
        if mode == OPUS_OGG:
            info = ogg_opus_info(data)
            return info["ms"] if info else None
    except Exception:
        pass
    return None


def row_ms(m):
    return None if m.get("audio_secs") is None else int(round(m["audio_secs"] * 1000))


def row_playable(m):
    """A stored note FireFly can play: a known Codec 2 mode, or an Opus file
    whose length could be read (i.e. a valid single-stream Ogg Opus file)."""
    mode = m.get("audio_mode")
    if mode in CODEC2:
        return True
    return mode == OPUS_OGG and m.get("audio_secs") is not None


def label(ms):
    """'5.0 s': tenths rounded half up, always a dot (the spec's label, without the ♪)."""
    if ms is None:
        return "? s"
    tenths = (ms + 50) // 100
    return f"{tenths // 10}.{tenths % 10} s"


def save(folder, name, mode, data):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name + extension(mode))
    with open(path, "wb") as f:
        f.write(data)
    return path


def decoders_available():
    return {"opus": shutil.which("opusdec") is not None, "codec2": shutil.which("c2dec") is not None}


_decode_locks = {}
_decode_locks_guard = threading.Lock()


def decode_to_wav(path, mode, expected=None):
    """Decode a saved voice note to a WAV file next to it (cached). Returns the WAV path.

    Playback and the SD-card copy may both ask for the same note at once, so
    one lock per note lets only one of them decode, and the WAV is written
    under a temporary name and renamed into place only when complete: a
    half-written file can never be mistaken for a finished one."""
    with _decode_locks_guard:
        lock = _decode_locks.setdefault(path, threading.Lock())
    with lock:
        wav = path + ".wav"
        if os.path.isfile(wav) and os.path.getsize(wav) > 44:
            if not _too_short(wav, expected):
                return wav
            os.remove(wav)      # cut short (e.g. by FireFly 0.5.1's decoding race): decode again
        tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.part.wav"   # opusdec picks its format from the extension
        try:
            _decode(path, mode, tmp)
            os.replace(tmp, wav)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        return wav


def _too_short(wav, expected):
    """A WAV clearly shorter than the length the message declares."""
    if not expected:
        return False
    try:
        return wav_seconds(wav) < expected - 0.5
    except Exception:
        return True


def _decode(path, mode, out_wav):
    if mode == OPUS_OGG:
        if not shutil.which("opusdec"):
            raise VoiceError("Opus decoder missing: sudo apt install opus-tools")
        r = subprocess.run(["opusdec", "--quiet", path, out_wav], capture_output=True, timeout=120)
        if r.returncode != 0 or not os.path.isfile(out_wav):
            raise VoiceError("could not decode this Opus voice note")
        return
    if mode in CODEC2:
        if not shutil.which("c2dec"):
            raise VoiceError("Codec2 decoder missing: sudo apt install codec2")
        raw = out_wav + ".raw"
        frames_file = out_wav + ".frames"      # neutral name: c2dec must not look for a header
        try:
            with open(path, "rb") as f:
                real_mode, frames = codec2_frames(mode, f.read())
            with open(frames_file, "wb") as f:
                f.write(frames)
            r = subprocess.run(["c2dec", CODEC2[real_mode][0], frames_file, raw], capture_output=True, timeout=120)
            if r.returncode != 0 or not os.path.isfile(raw):
                raise VoiceError("could not decode this Codec2 voice note")
            with open(raw, "rb") as f:
                pcm = f.read()
        finally:
            for f in (raw, frames_file):
                if os.path.exists(f):
                    os.remove(f)
        with wave.open(out_wav, "wb") as w:      # raw 8 kHz, 16-bit, mono -> WAV
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(pcm)
        return
    raise VoiceError(f"FireFly can't play {describe(mode)} voice notes yet")


# ---------------------------------------------------------------- SD card export
SD_FOLDER_NAME = "firefly-voice"


def export_dir(setting="auto"):
    """Where voice notes are copied: the games partition, which shows up on a
    computer when the SD card is plugged in (EASYROMS on ArkOS-family cards).
    Falls back to ~/firefly-voice if that isn't writable."""
    if setting and setting != "auto":
        return setting
    env = os.environ.get("FIREFLY_SD")
    candidates = [env] if env else []
    candidates += ["/roms2", "/roms"]
    for base in candidates:
        if base and os.path.isdir(base) and os.access(base, os.W_OK):
            return os.path.join(base, SD_FOLDER_NAME)
    return os.path.join(os.path.expanduser("~"), SD_FOLDER_NAME)


def _safe(name):
    # exFAT forbids : * ? " < > | \ /, and spaces are a nuisance in a terminal.
    out = "".join(c if c.isalnum() or c in "-_" else "-" for c in (name or "unknown"))
    return out.strip("-")[:32] or "unknown"


def wav_seconds(path):
    with wave.open(path) as w:
        return w.getnframes() / float(w.getframerate())


def export_note(note, sender, folder):
    """Copy one voice note to `folder` as a WAV anyone can play (plus the
    original file for Opus). Returns (wav_path, decoded_seconds) or raises VoiceError.
    Already-exported notes are left alone."""
    import time as _t
    stamp = _t.strftime("%Y-%m-%d_%H%M%S", _t.localtime(note["ts"]))
    base = os.path.join(folder, f"{stamp}_{_safe(sender)}_{note['id']}")
    wav_out = base + ".wav"
    expected = note.get("audio_secs")
    replacing = False
    if os.path.isfile(wav_out) and os.path.getsize(wav_out) > 44:
        if not _too_short(wav_out, expected):
            return wav_out, wav_seconds(wav_out)
        replacing = True        # an earlier copy was cut short: replace it
    os.makedirs(folder, exist_ok=True)
    wav = decode_to_wav(note["audio_path"], note["audio_mode"], expected)
    shutil.copyfile(wav, wav_out + ".part")
    os.replace(wav_out + ".part", wav_out)
    if note["audio_mode"] == OPUS_OGG:
        shutil.copyfile(note["audio_path"], base + ".ogg")
    secs = wav_seconds(wav_out)
    with open(os.path.join(folder, "voice-notes.txt"), "a", encoding="utf-8") as idx:
        claimed = f"{note['audio_secs']:.1f}s" if note.get("audio_secs") is not None else "?"
        idx.write(f"{os.path.basename(wav_out)}\tfrom {sender}\t{describe(note['audio_mode'])}\t"
                  f"{os.path.getsize(note['audio_path'])} bytes received\tlength in message {claimed}\t"
                  f"decoded {secs:.1f}s{'  (replaces a copy that was cut short)' if replacing else ''}\n")
    try:
        os.sync()        # the card may be pulled out soon after
    except AttributeError:
        pass
    return wav_out, secs


class Player:
    """Plays one voice note at a time. Decoding happens off the UI thread."""

    def __init__(self, log=print):
        self.log = log
        self.playing_id = None
        self.error = None
        self._sound = None
        self._proc = None
        self._ready = None            # decoded WAV waiting for the main thread to start it
        self._lock = threading.Lock()

    def play(self, msg_id, path, mode, expected=None):
        self.stop()
        self.error = None
        self.playing_id = msg_id
        threading.Thread(target=self._play, args=(msg_id, path, mode, expected), daemon=True).start()

    def _play(self, msg_id, path, mode, expected=None):
        try:
            wav = decode_to_wav(path, mode, expected)
            if self.playing_id != msg_id:
                return                       # stopped while decoding
            self._ready = (msg_id, wav)      # started by pump(), on the UI thread
        except VoiceError as e:
            self.error = str(e)
            self.playing_id = None
        except Exception as e:
            self.error = f"playback failed: {e}"
            self.playing_id = None

    def pump(self):
        """Call from the UI loop: starts a decoded note on the main thread,
        and notices when one finishes (to measure how long it really played)."""
        if self._ready is None and self.playing_id is not None:
            self.busy()
        ready, self._ready = self._ready, None
        if not ready or ready[0] != self.playing_id:
            return
        import time as _t
        try:
            self._started, self._wav_secs = _t.time(), wav_seconds(ready[1])
        except Exception:
            self._started, self._wav_secs = _t.time(), None
        try:
            if not self._play_pygame(ready[1]):
                self._play_aplay(ready[1])
        except VoiceError as e:
            self.error = str(e)
            self.playing_id = None

    def _play_pygame(self, wav):
        try:
            import pygame
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=48000, size=-16, channels=2)
                try:
                    from pygame._sdl2 import audio as sdl_audio
                    devices = sdl_audio.get_audio_device_names(False)
                except Exception:
                    devices = "?"
                self.log(f"audio: mixer {pygame.mixer.get_init()}, driver "
                         f"{os.environ.get('SDL_AUDIODRIVER', 'default')}, output devices {devices}")
            with self._lock:
                self._sound = pygame.mixer.Sound(wav)
                self._channel = self._sound.play()
            self.method = "pygame"
            self.log(f"playing {os.path.basename(wav)}: file {self._wav_secs:.1f} s, "
                     f"sound object {self._sound.get_length():.1f} s")
            return True
        except Exception as e:
            self.log(f"pygame audio unavailable ({e}); trying aplay")
            return False

    def _play_aplay(self, wav):
        if not shutil.which("aplay"):
            raise VoiceError("no audio output available")
        with self._lock:
            self._proc = subprocess.Popen(["aplay", "-q", wav], stderr=subprocess.PIPE)
        self.method = "aplay"

    def busy(self):
        """True while decoding or playing."""
        if self.playing_id is None:
            return False
        with self._lock:
            if self._proc is not None:
                if self._proc.poll() is None:
                    return True
                err = self._proc.stderr.read().decode(errors="replace").strip() if self._proc.stderr else ""
                self._proc = None
                if err:
                    self.log("aplay: " + err)
                self._finished()
                return False
            if self._sound is not None:
                try:
                    import pygame
                    if pygame.mixer.get_init() and pygame.mixer.get_busy():
                        return True
                except Exception:
                    pass
                self._sound = None
                self._finished()
                return False
        return self._ready is not None or self.playing_id is not None   # still decoding

    def _finished(self):
        """Compare how long it played with the file's length; the result is shown and logged."""
        import time as _t
        played = _t.time() - getattr(self, "_started", _t.time())
        total = getattr(self, "_wav_secs", None)
        self.last_result = (played, total, getattr(self, "method", "?"))
        self.log(f"played {played:.1f} s of {total if total is None else round(total, 1)} s "
                 f"via {getattr(self, 'method', '?')}")
        if total and played < total - 1.0:
            self.error = (f"Stopped after {played:.0f} s of {total:.0f} s ({self.method}): "
                          "the audio output ended early. The full note is on the SD card.")
        self.playing_id = None

    def stop(self):
        self._ready = None
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                self._proc.terminate()
            self._proc = None
            if self._sound is not None:
                try:
                    self._sound.stop()
                except Exception:
                    pass
            self._sound = None
        self.playing_id = None
