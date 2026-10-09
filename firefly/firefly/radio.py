"""Radio manager: finds and runs an RNode at runtime, outside the boot sequence.

Reticulum starts without any radio. This manager, running in its own thread,
looks for an RNode on every USB serial port (and on any Wi-Fi RNodes listed
in the settings), attaches the first one that answers, retunes it live when
the radio settings change, and starts searching again if it disappears.
Any RNode works: nothing is tied to one board or one port.
"""
import threading
import time

import RNS
from RNS.Interfaces.RNodeInterface import KISS, RNodeInterface

from .rnsconfig import serial_ports

APPLY_DELAY_S = 1.5        # wait for the user to finish changing settings
IDLE_POLL_S = 3.0
RETRY_NOT_RNODE_S = 30.0   # a port that didn't answer as an RNode
RETRY_REFUSED_S = 60.0     # an RNode that refused the settings (retried at once if settings change)

PLATFORMS = {KISS.PLATFORM_ESP32: "ESP32", KISS.PLATFORM_NRF52: "nRF52", KISS.PLATFORM_AVR: "AVR"}


class FireFlyRNode(RNodeInterface):
    """RNodeInterface that reports old firmware instead of shutting the app down."""
    firmware_too_old = False

    def validate_firmware(self):
        ok = (self.maj_version > self.REQUIRED_FW_VER_MAJ or
              (self.maj_version == self.REQUIRED_FW_VER_MAJ and self.min_version >= self.REQUIRED_FW_VER_MIN))
        self.firmware_ok = ok
        self.firmware_too_old = not ok


class RadioStatus:
    OFF, SHARED, SEARCHING, CONNECTING, ONLINE, REFUSED, NO_DEVICES = (
        "off", "shared", "searching", "connecting", "online", "refused", "no devices")

    def __init__(self):
        self.state = self.OFF
        self.port = None
        self.detail = ""
        self.board = None       # e.g. "ESP32, firmware 1.82"
        self.since = time.time()

    def set(self, state, port=None, detail="", board=None):
        self.state, self.port, self.detail, self.board = state, port, detail, board
        self.since = time.time()


class RadioManager:
    def __init__(self, core, port_lister=serial_ports):
        self.core = core
        self.port_lister = port_lister
        self.status = RadioStatus()
        self.iface = None
        self.active_params = None
        self.backoff = {}               # port -> time before which we don't probe it again
        self.refusals = {}              # port -> (detail, board) for RNodes that refused
        self.found_by_listing = False   # the active port came from the USB device list
        self.apply_at = 0.0
        self.wake = threading.Event()
        self.lock = threading.Lock()
        self.running = False

    # ------------------------------------------------ public
    def start(self):
        self.running = True
        threading.Thread(target=self._run, daemon=True, name="firefly-radio").start()

    def stop(self):
        self.running = False
        self.wake.set()
        self._detach()

    def request_apply(self, delay=APPLY_DELAY_S):
        """Settings changed: retune (or search again) after `delay` seconds of quiet."""
        self.apply_at = time.time() + delay
        self.backoff.clear()
        self.refusals.clear()
        self.wake.set()

    def search_now(self):
        self.backoff.clear()
        self.refusals.clear()
        self.apply_at = 0.0
        self.wake.set()

    # ------------------------------------------------ loop
    def _run(self):
        while self.running:
            try:
                if time.time() >= self.apply_at:
                    self._tick()
            except Exception as e:           # the radio must never take the app down
                RNS.log(f"Radio manager error: {e}", RNS.LOG_ERROR)
            wait = IDLE_POLL_S
            if self.apply_at > time.time():
                wait = max(0.1, self.apply_at - time.time())
            self.wake.wait(wait)
            self.wake.clear()

    def _params(self):
        r = self.core.settings["radio"]
        return (int(r["frequency"]), int(r["bandwidth"]), int(r["tx_power"]),
                int(r["spreading_factor"]), int(r["coding_rate"]))

    def _tick(self):
        s = self.core.settings
        if self.core.shared_instance:
            self.status.set(RadioStatus.SHARED, detail="the shared Reticulum instance (rnsd) runs the radio")
            return
        if not s["radio"]["enabled"]:
            if self.iface:
                self._detach()
            if self.status.state != RadioStatus.OFF:
                self.status.set(RadioStatus.OFF)
            return

        params = self._params()
        listed = self.port_lister()
        if self.iface:
            port = self.status.port
            vanished = self.found_by_listing and port not in listed
            if vanished or not self.iface.online:
                self._detach()
                self.status.set(RadioStatus.SEARCHING, detail=f"lost the RNode on {port}; searching")
                self.backoff.pop(port, None)
            elif params != self.active_params:
                self.status.set(RadioStatus.CONNECTING, port=port, detail="retuning")
                self._detach()
                self._try(port, params, prefer=True)
                if self.iface:
                    return
            else:
                return

        now = time.time()
        candidates = self._candidates(listed)
        if not candidates:
            self.status.set(RadioStatus.NO_DEVICES, detail="plug an RNode into USB, or add a Wi-Fi RNode in SETUP")
            return
        tried = 0
        for port in candidates:
            if self.backoff.get(port, 0) > now:
                continue
            tried += 1
            if self._try(port, params):
                return
        refused = [(p, self.refusals[p]) for p in candidates if p in self.refusals]
        if refused:
            port, (detail, board) = refused[0]
            self.status.set(RadioStatus.REFUSED, port=port, board=board, detail=detail)
        else:
            self.status.set(RadioStatus.SEARCHING,
                            detail=f"{len(candidates)} device(s) checked, none answered as an RNode; retrying")

    def _candidates(self, usb):
        r = self.core.settings["radio"]
        preferred = r.get("port") or "auto"
        ports = []
        if preferred != "auto":
            ports.append(preferred)             # the user's pick first, then anything else
        ports += [p for p in usb if p not in ports]
        ports += ["tcp://" + h.strip() for h in self.core.settings.get("rnode_hosts", []) if h.strip()]
        return ports

    def _try(self, port, params, prefer=False):
        freq, bw, txp, sf, cr = params
        self.status.set(RadioStatus.CONNECTING, port=port, detail="asking the device if it is an RNode")
        cfg = {"name": "RNode LoRa", "port": port, "frequency": freq, "bandwidth": bw, "txpower": txp,
               "spreadingfactor": sf, "codingrate": cr}
        iface = None
        try:
            iface = FireFlyRNode(RNS.Transport, cfg)
        except Exception as e:
            RNS.log(f"RNode on {port} could not start: {e}", RNS.LOG_WARNING)
        board = _board(iface) if iface else None
        too_old = iface is not None and iface.detected and iface.firmware_too_old

        if iface is not None and iface.online and not too_old:
            try:
                self.core.reticulum._add_interface(iface)
            except Exception as e:
                RNS.log(f"Could not register RNode interface: {e}", RNS.LOG_ERROR)
                _quiet_detach(iface)
                return False
            with self.lock:
                self.iface = iface
                self.active_params = params
            self.backoff.pop(port, None)
            self.refusals.pop(port, None)
            self.found_by_listing = port in self.port_lister()
            self.status.set(RadioStatus.ONLINE, port=port, board=board)
            if port.startswith("/dev/"):
                self._remember_port(port)
            RNS.log(f"RNode online on {port} ({board})")
            try:
                self.core.on_interface_online()
            except Exception:
                pass
            return True

        if iface is not None and iface.detected:
            if iface.firmware_too_old:
                why = (f"firmware {iface.maj_version}.{iface.min_version} is too old "
                       f"(needs {iface.REQUIRED_FW_VER_MAJ}.{iface.REQUIRED_FW_VER_MIN}+): update it with rnodeconf")
            else:
                why = ("it refused these radio settings. Check the frequency is in this board's band, "
                       "and the TX power is within its limit")
            self.status.set(RadioStatus.REFUSED, port=port, board=board, detail=why)
            self.refusals[port] = (why, board)
            self.backoff[port] = time.time() + RETRY_REFUSED_S
        else:
            self.refusals.pop(port, None)
            self.backoff[port] = time.time() + RETRY_NOT_RNODE_S
        if iface is not None:
            _quiet_detach(iface)
        return False

    def _detach(self):
        with self.lock:
            iface, self.iface, self.active_params = self.iface, None, None
        if iface is None:
            return
        try:
            RNS.Transport.remove_interface(iface)
        except Exception:
            pass
        _quiet_detach(iface)

    def _remember_port(self, port):
        """Nothing to remember when on 'auto'; the manager finds the radio again anywhere."""
        return


def _board(iface):
    parts = [PLATFORMS.get(iface.platform, "unknown chip")]
    if iface.maj_version:
        parts.append(f"firmware {iface.maj_version}.{iface.min_version}")
    return ", ".join(parts)


def _quiet_detach(iface):
    try:
        iface.detached = True        # stops Reticulum's own reconnect loop
        iface.online = False
        if iface.serial is not None and getattr(iface.serial, "is_open", False):
            iface.detach()
            iface.serial.close()
    except Exception:
        pass
