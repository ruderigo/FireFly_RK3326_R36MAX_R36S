"""A simulated RNode on a pseudo-terminal, speaking the RNode KISS protocol.

    r = FakeRNode(band=(863e6, 870e6), fw=(1, 82))
    r.port      # e.g. /dev/pts/5, give it to FireFly as a serial port
    r.unplug()  # closes the device, like pulling the USB cable
"""
import os, pty, threading, time, tty

FEND, FESC, TFEND, TFESC = 0xC0, 0xDB, 0xDC, 0xDD
CMD = dict(DATA=0x00, FREQ=0x01, BW=0x02, TXP=0x03, SF=0x04, CR=0x05, STATE=0x06, DETECT=0x08,
           LEAVE=0x0A, ST_ALOCK=0x0B, LT_ALOCK=0x0C, PLATFORM=0x48, MCU=0x49, FW=0x50)


def esc(data):
    out = bytearray()
    for b in data:
        if b == FEND: out += bytes([FESC, TFEND])
        elif b == FESC: out += bytes([FESC, TFESC])
        else: out.append(b)
    return bytes(out)


class FakeRNode:
    def __init__(self, band=(137e6, 1020e6), fw=(1, 82), answers=True, max_txp=22, boot_s=0.0):
        self.master, slave = pty.openpty()
        tty.setraw(self.master)
        tty.setraw(slave)
        self.port = os.ttyname(slave)
        self._slave = slave
        self.band, self.fw, self.answers, self.max_txp = band, fw, answers, max_txp
        self.freq = int(band[0]); self.bw = 125000; self.txp = 0; self.sf = 7; self.cr = 5; self.state = 0
        self.set_log = []
        # boot_s: like an ESP32 that resets when the port opens and needs boot_s seconds
        # before it answers. Reticulum waits 2 s after opening before its first byte,
        # so the board counts as reset 2 s before the first detect request of a session.
        self.boot_s = boot_s
        self.last_rx = 0.0
        self.booted_at = 0.0
        self.ignored = 0
        self.alive = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _send(self, cmd, payload):
        try:
            os.write(self.master, bytes([FEND, cmd]) + esc(payload) + bytes([FEND]))
        except OSError:
            pass

    def _handle(self, cmd, data):
        if not self.answers:
            return
        now = time.time()
        if cmd == CMD["DETECT"] and self.boot_s and now - self.last_rx > 1.5:
            self.booted_at = now - 2.0 + self.boot_s      # a new session: the port was just (re)opened
        if cmd == CMD["DETECT"]:
            self.last_rx = now
        if now < self.booted_at:
            self.ignored += 1             # still booting: bytes are lost, as on the real board
            return
        if cmd == CMD["DETECT"] and data[:1] == b"\x73":
            self._send(CMD["DETECT"], b"\x46")
        elif cmd == CMD["FW"]:
            self._send(CMD["FW"], bytes(self.fw))
        elif cmd == CMD["PLATFORM"]:
            self._send(CMD["PLATFORM"], b"\x80")
        elif cmd == CMD["MCU"]:
            self._send(CMD["MCU"], b"\x81")
        elif cmd == CMD["FREQ"] and len(data) == 4:
            f = int.from_bytes(data, "big")
            if self.band[0] <= f <= self.band[1]:
                self.freq = f
            self.set_log.append(("freq", f))
            self._send(CMD["FREQ"], self.freq.to_bytes(4, "big"))   # reports what it actually uses
        elif cmd == CMD["BW"] and len(data) == 4:
            self.bw = int.from_bytes(data, "big"); self._send(CMD["BW"], data)
        elif cmd == CMD["TXP"] and len(data) == 1:
            self.txp = min(data[0], self.max_txp); self._send(CMD["TXP"], bytes([self.txp]))
        elif cmd == CMD["SF"] and len(data) == 1:
            self.sf = data[0]; self._send(CMD["SF"], data)
        elif cmd == CMD["CR"] and len(data) == 1:
            self.cr = data[0]; self._send(CMD["CR"], data)
        elif cmd == CMD["STATE"] and len(data) == 1:
            self.state = data[0]; self._send(CMD["STATE"], data)

    def _loop(self):
        buf, in_frame, escape = bytearray(), False, False
        while self.alive:
            try:
                chunk = os.read(self.master, 256)
            except OSError:
                break
            for b in chunk:
                if b == FEND:
                    if in_frame and buf:
                        self._handle(buf[0], bytes(buf[1:]))
                    buf, in_frame = bytearray(), True
                elif in_frame:
                    if b == FESC:
                        escape = True
                        continue
                    if escape:
                        b = FEND if b == TFEND else FESC if b == TFESC else b
                        escape = False
                    buf.append(b)

    def unplug(self):
        self.alive = False
        for fd in (self.master, self._slave):
            try:
                os.close(fd)
            except OSError:
                pass
