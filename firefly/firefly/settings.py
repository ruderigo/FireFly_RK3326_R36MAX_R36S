"""User settings, stored as JSON. Unknown keys are kept; missing keys get defaults."""
import copy
import json
import os
import tempfile

# The provisioner defaults of the Stump network. Radio settings MUST match the
# other nodes exactly: a mismatched radio doesn't error, it just hears nothing.
STUMP_RADIO = {
    "frequency": 915_000_000,
    "bandwidth": 125_000,
    "spreading_factor": 8,
    "coding_rate": 5,
    "tx_power": 7,
}

BANDWIDTHS = [7_800, 10_400, 15_600, 20_800, 31_250, 41_700, 62_500, 125_000, 250_000, 500_000]

DEFAULTS = {
    "display_name": "R36 Operator",
    "announce_interval_min": 30,     # Stump needs < 60 to keep you DM-reachable
    "radio": dict(enabled=True, port="auto", **STUMP_RADIO),
    "auto_interface": True,          # zero-conf discovery on Wi-Fi / Ethernet
    "tcp_peers": [],                 # ["host:port", ...] internet or LAN entrypoints
    "rnode_hosts": [],               # Wi-Fi RNodes by host/IP (RNode TCP port 7633)
    "managed_config": True,          # False = use the system ~/.reticulum config instead
    "share_instance": True,          # let rnsh / NomadNet on the device use our stack
    "transport": False,              # route traffic for others (costs airtime + battery)
    "propagation_mode": "auto",      # auto | manual | off
    "propagation_node": None,        # hex hash when manual
    "fallback_to_propagation": True,
    "sync_interval_min": 30,         # 0 = manual only
    "quick_replies": [
        "OK", "Yes", "No", "On my way", "Where are you?", "Can't talk now",
        "All good here", "Need help", "Copy that", "Thanks!",
    ],
    "voice_to_sd": True,             # copy every voice note to the SD card as a WAV
    "voice_export_dir": "auto",      # auto = /roms(2)/firefly-voice, visible on a computer
    "screen_rotation": "auto",       # auto | 0 | 90 | 180 | 270 (clockwise); Select+R1 cycles it
    "joystick_map": {},              # raw button index -> action, for pads without a mapping
    "log_level": 3,
}


def _merge(base, override):
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class Settings:
    def __init__(self, path):
        self.path = path
        self.data = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self.data = _merge(DEFAULTS, json.load(f))
        except FileNotFoundError:
            self.save()
        except (ValueError, OSError):
            # Keep a copy of the broken file and start from defaults.
            try:
                os.replace(self.path, self.path + ".broken")
            except OSError:
                pass
            self.data = copy.deepcopy(DEFAULTS)
            self.save()
        # 0.5.x stored the old default (60 min); FireFly now collects every 30.
        if self.data.get("sync_interval_min") == 60 and not self.data.get("sync_default_v2"):
            self.data["sync_interval_min"] = 30
        self.data["sync_default_v2"] = True
        try:
            self.validate()
        except (TypeError, ValueError, KeyError):
            # A hand-edited value that isn't a number: fall back to defaults for the radio.
            self.data["radio"] = copy.deepcopy(DEFAULTS["radio"])
            self.validate()
            self.save()

    def validate(self):
        r = self.data["radio"]
        r["frequency"] = int(min(max(int(r["frequency"]), 137_000_000), 1_020_000_000))
        if r["bandwidth"] not in BANDWIDTHS:
            r["bandwidth"] = 125_000
        r["spreading_factor"] = int(min(max(int(r["spreading_factor"]), 5), 12))
        r["coding_rate"] = int(min(max(int(r["coding_rate"]), 5), 8))
        r["tx_power"] = int(min(max(int(r["tx_power"]), 0), 22))
        self.data["announce_interval_min"] = max(0, int(self.data["announce_interval_min"]))
        self.data["sync_interval_min"] = max(0, int(self.data["sync_interval_min"]))
        if self.data["propagation_mode"] not in ("auto", "manual", "off"):
            self.data["propagation_mode"] = "auto"

    def save(self):
        d = os.path.dirname(self.path) or "."
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".settings")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)  # atomic: never leaves a half-written file

    def __getitem__(self, k): return self.data[k]
    def __setitem__(self, k, v): self.data[k] = v
    def get(self, k, default=None): return self.data.get(k, default)
