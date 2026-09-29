"""Bring back settings lost to a clean reinstall.

cleanup.sh (before 0.3.1) deleted settings.json but kept a copy in
~/firefly-backup-<date>/ or ~/reticom-backup-<date>/. On its first start,
FireFly looks for those copies and restores any setting that is still at its
default here but was customised there: radio, port, network links,
propagation, display name, quick replies, button map. It never touches the
identity key, and runs once (the 'restore_checked' flag).
"""
import glob
import json
import os

from .settings import DEFAULTS

RESTORABLE = ("display_name", "announce_interval_min", "radio", "auto_interface", "tcp_peers", "rnode_hosts",
              "share_instance", "transport", "propagation_mode", "propagation_node",
              "fallback_to_propagation", "sync_interval_min", "quick_replies", "joystick_map",
              "screen_rotation")


def backup_settings_files(user_home):
    """Backup settings.json files, newest first (folder names end in a timestamp)."""
    pats = ["firefly-backup-*/settings.json", "firefly-backup-*/from-reticom/settings.json",
            "reticom-backup-*/settings.json"]
    found = []
    for pat in pats:
        for f in glob.glob(os.path.join(user_home, pat)):
            stamp = f.split("-backup-")[1].split("/")[0]
            found.append((stamp, f))
    return [f for _, f in sorted(found, reverse=True)]


def restore_from_backups(settings, user_home, log=print):
    """Returns (restored keys, source file) or ([], None)."""
    if settings.get("restore_checked"):
        return [], None
    restored, source = [], None
    for path in backup_settings_files(user_home):
        try:
            with open(path, "r", encoding="utf-8") as f:
                old = json.load(f)
        except (OSError, ValueError):
            continue
        keys = [k for k in RESTORABLE
                if k in old and settings.get(k) == DEFAULTS.get(k) and old[k] != DEFAULTS.get(k)]
        if keys:
            for k in keys:
                settings[k] = old[k]
            restored, source = keys, path
            break   # newest backup with real customisations wins
    settings["restore_checked"] = True
    try:
        settings.validate()
    except (TypeError, ValueError, KeyError):
        settings["radio"] = dict(DEFAULTS["radio"])
    settings.save()
    if restored:
        log(f"restored settings {', '.join(restored)} from {source}")
    return restored, source
