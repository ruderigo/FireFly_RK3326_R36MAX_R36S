"""Where FireFly keeps its data.

Everything lives under one directory (default ~/.firefly, override with
FIREFLY_HOME). On ArkOS-family handhelds that is /home/ark/.firefly, on the
btrfs root, which supports file permissions. /roms is exFAT and ignores
them, so the identity key must NOT live there.
"""
import os
from dataclasses import dataclass


@dataclass
class Paths:
    home: str

    @property
    def settings(self): return os.path.join(self.home, "settings.json")
    @property
    def identity(self): return os.path.join(self.home, "identity")
    @property
    def database(self): return os.path.join(self.home, "firefly.db")
    @property
    def rns_config_dir(self): return os.path.join(self.home, "reticulum")
    @property
    def lxmf_storage(self): return os.path.join(self.home, "lxmf")
    @property
    def log(self): return os.path.join(self.home, "firefly.log")
    @property
    def audio(self): return os.path.join(self.home, "audio")

    def ensure(self):
        for d in (self.home, self.rns_config_dir, self.lxmf_storage):
            os.makedirs(d, exist_ok=True)
        try:
            os.chmod(self.home, 0o700)
        except OSError:
            pass


LEGACY_HOME = ".reticom"   # FireFly was called RetiCom up to v0.1.3


def default_paths(override=None, log=print):
    explicit = override or os.environ.get("FIREFLY_HOME")
    home = explicit or os.path.join(os.path.expanduser("~"), ".firefly")
    if not explicit:
        migrate_legacy(home, log)
    rename_legacy_files(home, log)
    return Paths(home)


def rename_legacy_files(home, log=print):
    """Inside the data folder, RetiCom's message database had its own name."""
    for suffix in ("", "-wal", "-shm"):
        old = os.path.join(home, "reticom.db" + suffix)
        new = os.path.join(home, "firefly.db" + suffix)
        if os.path.exists(old) and not os.path.exists(new):
            os.rename(old, new)
            if suffix == "":
                log("renamed message database reticom.db -> firefly.db")


def migrate_legacy(home, log=print):
    """Move a RetiCom data folder to FireFly's name, keeping identity, contacts and messages.

    A rename on the same filesystem is atomic: the identity key is never copied
    half-way. Does nothing if FireFly already has data."""
    legacy = os.path.join(os.path.dirname(home), LEGACY_HOME)
    if os.path.isdir(legacy) and not os.path.exists(home):
        os.rename(legacy, home)
        try:
            fd = os.open(os.path.dirname(home), os.O_RDONLY)
            os.fsync(fd)
            os.close(fd)
        except OSError:
            pass
        log(f"moved RetiCom data {legacy} -> {home} (same identity and address)")
        return True
    return False
