"""FireFly: a gamepad-driven Reticulum / LXMF messenger for RK3326 handhelds."""
__version__ = "0.8.1"
CHANNEL = "sandbox"          # "stable" in FireFly_RK3326_R36MAX_R36S, "sandbox" in SandBox_FireFly_RK3326
try:                         # written by the release workflow: the commit and date the zip was built from
    from ._build import COMMIT, DATE
except ImportError:          # running from a checkout, not a release zip
    COMMIT, DATE = "dev", ""
BUILD = f"{CHANNEL} {COMMIT}" + (f" {DATE}" if DATE else "")
VERSION_LABEL = f"{__version__} ({BUILD})"
APP_NAME = "FireFly"
