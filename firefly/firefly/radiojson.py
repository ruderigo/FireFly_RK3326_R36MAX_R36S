"""radio.json: radio settings handed over by a Stump technician.

When the Stump provisioner sets up a Heltec V3 as the RNode for a handheld,
it saves the radio settings it flashed as `radio.json` and tells the
technician to copy that file onto the handheld. FireFly looks for it in a
few places on the SD card and applies it, so the radio matches the mesh
without anyone typing frequencies with a D-pad.

The provisioner's format (all numbers in Hz / dBm, as rnodeconf takes them):

    {"frequency": 915000000, "bandwidth": 125000, "txpower": 7,
     "spreadingfactor": 8, "codingrate": 5,
     "boundary_mode": "internal", "ifac": "optional passphrase"}

FireFly's own spellings (spreading_factor, tx_power, …) and "ifac_netname"
are accepted too. A file is applied once: it is remembered by its SHA-256,
so changing the settings by hand afterwards sticks until the file changes.
"""
import hashlib
import json
import os

from .settings import BANDWIDTHS

NAME = "radio.json"
MAX_BYTES = 4096


def candidates(home=None):
    """Where a technician may have put it, most specific first."""
    out = []
    if home:
        out.append(os.path.join(home, NAME))
    for root in ("/roms2", "/roms"):
        out += [f"{root}/firefly/{NAME}",
                f"{root}/ports/firefly/{NAME}",
                f"{root}/ports/meshcommandermax/{NAME}",   # where the Stump provisioner says to copy it
                f"{root}/{NAME}"]
    return out


def find(home=None, paths=None):
    for p in (paths if paths is not None else candidates(home)):
        try:
            if os.path.isfile(p) and os.path.getsize(p) <= MAX_BYTES:
                return p
        except OSError:
            continue
    return None


def _pick(d, *names):
    for n in names:
        if n in d and d[n] is not None and d[n] != "":
            return d[n]
    return None


def parse(raw):
    """bytes -> (radio dict with FireFly's keys, list of problems). Raises ValueError if unusable."""
    try:
        d = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as e:
        raise ValueError(f"not valid JSON ({e})")
    if not isinstance(d, dict):
        raise ValueError("not a JSON object")
    if isinstance(d.get("radio"), dict):           # a whole provisioner profile works too
        inner = dict(d["radio"])
        for k in ("ifac", "ifac_netname", "ifac_passphrase"):
            if k in d and k not in inner:
                inner[k] = d[k]
        d = inner

    out, problems = {}, []

    def num(key, *names, lo, hi):
        v = _pick(d, *names)
        if v is None:
            return
        try:
            v = int(float(v))
        except (TypeError, ValueError):
            problems.append(f"{names[0]} is not a number")
            return
        if not lo <= v <= hi:
            problems.append(f"{names[0]} {v} is out of range")
            return
        out[key] = v

    freq = _pick(d, "frequency", "freq")
    if freq is not None:
        try:
            f = float(freq)
            if f < 10_000:              # given in MHz (e.g. 915.0)
                f *= 1e6
            freq = int(round(f))
        except (TypeError, ValueError):
            freq = None
        if freq is None or not 137_000_000 <= freq <= 1_020_000_000:
            problems.append("frequency is out of range")
        else:
            out["frequency"] = freq

    bw = _pick(d, "bandwidth", "bw")
    if bw is not None:
        try:
            b = float(bw)
            if b < 1_000:               # given in kHz (e.g. 125)
                b *= 1000
            b = int(round(b))
        except (TypeError, ValueError):
            b = None
        match = [x for x in BANDWIDTHS if b is not None and abs(x - b) <= 100]
        if match:
            out["bandwidth"] = match[0]
        else:
            problems.append(f"bandwidth {bw} is not a LoRa bandwidth")

    num("spreading_factor", "spreadingfactor", "spreading_factor", "sf", lo=5, hi=12)
    num("coding_rate", "codingrate", "coding_rate", "cr", lo=5, hi=8)
    num("tx_power", "txpower", "tx_power", "txp", lo=0, hi=22)

    for key, names in (("ifac_passphrase", ("ifac", "ifac_passphrase", "passphrase", "ifac_netkey")),
                       ("ifac_netname", ("ifac_netname", "network_name"))):
        v = _pick(d, *names)
        if v is not None:
            out[key] = str(v)[:128 if key == "ifac_passphrase" else 64]

    if not any(k in out for k in ("frequency", "bandwidth", "spreading_factor", "coding_rate", "tx_power")):
        raise ValueError("no radio settings in it" + (f" ({'; '.join(problems)})" if problems else ""))
    return out, problems


def describe(r):
    parts = []
    if "frequency" in r:
        parts.append(f"{r['frequency'] / 1e6:.3f} MHz")
    if "bandwidth" in r:
        parts.append(f"{r['bandwidth'] / 1000:g} kHz")
    if "spreading_factor" in r:
        parts.append(f"SF{r['spreading_factor']}")
    if "coding_rate" in r:
        parts.append(f"CR 4/{r['coding_rate']}")
    if "tx_power" in r:
        parts.append(f"{r['tx_power']} dBm")
    if r.get("ifac_passphrase") or r.get("ifac_netname"):
        parts.append("with passphrase")
    return " ".join(parts)


def apply(settings, path, force=False):
    """Apply the file at `path` to settings, once per file content (or always if force).
    Returns (applied: bool, message: str)."""
    try:
        with open(path, "rb") as f:
            raw = f.read(MAX_BYTES + 1)
    except OSError as e:
        return False, f"could not read {path}: {e.strerror or e}"
    digest = hashlib.sha256(raw).hexdigest()
    if not force and settings.get("radio_json_imported") == digest:
        return False, "already applied"
    try:
        radio, problems = parse(raw)
    except ValueError as e:
        settings["radio_json_imported"] = digest      # don't complain about the same bad file every start
        settings.save()
        return False, f"{path}: {e}"
    settings["radio"].update(radio)
    settings["radio_json_imported"] = digest
    settings.validate()
    settings.save()
    msg = f"Radio settings from {path}: {describe(radio)}"
    if problems:
        msg += " (ignored: " + "; ".join(problems) + ")"
    return True, msg


def auto_import(settings, home=None, paths=None):
    """At start: apply a radio.json found on the card if it is new. (applied, message, path)"""
    p = find(home, paths)
    if not p:
        return False, "", None
    ok, msg = apply(settings, p)
    return ok, msg, p
