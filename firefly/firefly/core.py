"""The messaging core: Reticulum + LXMF, independent of any UI.

Standard LXMF throughout, so FireFly talks to Sideband, NomadNet, MeshChat
and every other LXMF client, and to Stump nodes (which are LXMF peers too).

Threads: RNS and LXMF call us back from their own threads. All shared state
goes through the Store (locked) or small locked dicts here. The UI only
reads the Store and calls the public methods below.
"""
import os
import threading
import time

import RNS
import RNS.vendor.umsgpack as msgpack
import LXMF
from LXMF.LXMessage import LXMessage
from LXMF.LXMRouter import LXMRouter

from . import stump, ztext
from .rnsconfig import write_config
from .settings import Settings
from .store import Store

# How long to wait for an unknown peer's path/identity before failing. A Reticulum 1.6.1 app
# answers a path request only once its own announce stamp is made: 16 s on a fast computer the
# first time, minutes on a phone. So, as the Stump does since 1.0.0-beta.85: up to 3 minutes,
# asking again after the first 15 s and then every 30 s (each ask is airtime on LoRa).
PATH_WAIT_S = 180
PATH_ASK_AGAIN_S = (15, 30)   # first re-ask, then every
MONITOR_INTERVAL_S = 1.0

# LXMF field ids we recognise but can't render yet, described as text instead.
FIELD_NAMES = {
    LXMF.FIELD_IMAGE: "image",
    LXMF.FIELD_FILE_ATTACHMENTS: "file",
    LXMF.FIELD_TELEMETRY: "location/telemetry",
    LXMF.FIELD_EMBEDDED_LXMS: "embedded message",
}


from . import __version__ as _VERSION
APP_TAG = f"stump:firefly-rk3326/{_VERSION}"     # the announce's fourth item (Stump 1.0.0-beta.53)

# Sideband's commands (sideband/sense.py, Commands), also sent by MeshChat. FireFly answers none.
COMMAND_NAMES = {0x00: "a plugin command", 0x01: "location and telemetry", 0x02: "a ping",
                 0x03: "an echo", 0x04: "a signal report"}


def commands_asked(field):
    """FIELD_COMMANDS is a list of {command id: arguments}. -> the command ids, or []."""
    out = []
    if isinstance(field, list):
        for c in field[:16]:
            if isinstance(c, dict):
                out += [k for k in c if isinstance(k, int) and not isinstance(k, bool)]
    return sorted(set(out))


PACKS_MAX = 512           # peers remembered as reading packed text (from their announces)

STAMP_EXT_LEN = 18        # Reticulum 1.6.1's announce stamp: 0xC1, flags, 14-byte stamp, link cost


def without_stamp(app_data):
    """Announce app data that is plain text (a NomadNet node's name, an old LXMF app's name)
    without a Reticulum 1.6.1 stamp still after it. Reticulum takes the stamp off what it hands
    FireFly only when the stamp meets the cost FireFly would ask (23.5 by default), so a node
    announcing with a cheaper one arrives with 18 bytes after its name. Its marker, 0xC1, is
    never in UTF-8 text, so it can't be mistaken. Msgpack app data is left as it is: msgpack
    readers stop at the end of the list (the Stump reads stamps off the same way, beta.85)."""
    if app_data and len(app_data) >= STAMP_EXT_LEN and not ((0x90 <= app_data[0] <= 0x9f) or app_data[0] == 0xdc):
        t = app_data[-STAMP_EXT_LEN:]
        if t[0] == 0xC1 and not (t[-1] & 0x80) and (t[-1] & 0x7F) <= 100:
            return app_data[:-STAMP_EXT_LEN] or None
    return app_data


def reads_packed(app_data):
    """True when an LXMF announce says its sender reads packed text (Stump 1.0.0-beta.82,
    CLIENT_QUICKSTART "Packed text"): a fifth item, [name, cost, functions, tag, {"z": 1}]."""
    try:
        if app_data and ((0x90 <= app_data[0] <= 0x9f) or app_data[0] == 0xdc):
            d = msgpack.unpackb(app_data)
            if isinstance(d, list) and len(d) > 4 and isinstance(d[4], dict):
                z = d[4].get("z")
                return isinstance(z, int) and not isinstance(z, bool) and z >= 1
    except Exception:
        pass
    return False


def unpacked_content(content):
    """An incoming LXMF content as its text: 0xFF unpacked (ztext.py), 0xFE stripped,
    anything else as it came. A packed one that can't be read stays as it came (binary)."""
    if content and content[0] >= ztext.PLAIN:
        text = ztext.unpack(content)
        if text is not None:
            return text
    return content


def single_packet_size(text, title=""):
    """LXMF content size the way LXMessage.pack() measures it (limit 295 for one packet)."""
    payload = msgpack.packb([time.time(), title.encode(), text.encode(), {}])
    return len(payload) - LXMessage.TIMESTAMP_SIZE - LXMessage.STRUCT_OVERHEAD


class Core:
    def __init__(self, paths, log=print):
        self.paths = paths
        self.paths.ensure()
        self.log = log
        self.settings = Settings(paths.settings)
        from .restore import restore_from_backups
        restored, src = restore_from_backups(self.settings, os.path.dirname(os.path.abspath(paths.home)), log)
        self.store = Store(paths.database)
        self.lock = threading.RLock()
        self.outbound = {}          # message id -> LXMessage in flight
        self.auth = {}              # node hash hex -> stump.AuthSession
        self.stump_state = {}       # node hash hex -> stump.NodeState (current room, last refusal)
        self._sync_waiting = False  # a sync was started and its result not yet seen
        self._sync_rounds = 0
        self._written_to = set()     # peers messaged this session
        self.stump_pn = {}           # propagation-node hash hex -> Stump name
        self._sync_retry_at = 0.0
        self._sync_failures = 0
        self.stumps = {}            # lxmf hash hex -> (name, version)
        self.packs = {}             # lxmf hash hex -> its latest announce says it reads packed text
        self.running = False
        self.radio = None
        self.lan = None
        self.web = {}               # Stump lxmf hex -> stumpweb.StumpWeb (chat over Wi-Fi)
        self._declined = {}         # peer -> when FireFly last declined their commands
        self.voice_export_status = None   # (folder, copied, last error)
        self._blocked = set()
        self.started_at = time.time()
        self.last_announce = 0.0
        self.last_sync = 0.0
        self.sync_state = "idle"
        self.status_note = ""
        if restored:
            what = "radio settings" if "radio" in restored else "settings"
            self.status_note = f"Restored your {what} from {os.path.basename(os.path.dirname(src))}"
        # radio.json from a Stump technician (the provisioner's Heltec profile), applied once per file.
        self.radio_json_note = ""
        try:
            from . import radiojson
            applied, msg, path = radiojson.auto_import(self.settings, home=paths.home)
            if path and msg and msg != "already applied":
                log(msg)
                self.radio_json_note = msg if applied else "radio.json not used: " + msg
        except Exception as e:      # a stray file must never stop the app
            log(f"radio.json: {e}")

    # ================================================================ lifecycle
    def start(self):
        s = self.settings
        configdir = None
        if s["managed_config"]:
            write_config(s, self.paths.rns_config_dir)
            configdir = self.paths.rns_config_dir
        self.reticulum = RNS.Reticulum(configdir=configdir, loglevel=int(s["log_level"]),
                                       logdest=RNS.LOG_FILE if configdir else None)
        self.identity = self._load_identity()
        from . import stamps
        stamps.install()          # same valid stamps as LXMF, ~150x less hashing
        self.router = LXMRouter(identity=self.identity, storagepath=self.paths.lxmf_storage)
        self.local = self.router.register_delivery_identity(self.identity, display_name=s["display_name"])
        self.router.register_delivery_callback(self._on_message)
        self._tag_announces()
        self._blocked = {b["hash"] for b in self.store.blocked()}
        for h in self._blocked:                     # LXMF's ignore list lives in memory only
            self.router.ignore_destination(bytes.fromhex(h))

        RNS.Transport.register_announce_handler(_DeliveryAnnounces(self))
        RNS.Transport.register_announce_handler(_PropagationAnnounces(self))
        RNS.Transport.register_announce_handler(_NomadNodeAnnounces(self))
        RNS.Transport.register_announce_handler(stump.BeaconHandler(self._on_stump_beacon))

        for p in self.store.peers("lxmf"):   # remember which saved peers are Stumps
            if p["stump"]:
                self.stumps[p["hash"]] = (p["stump"], p["stump_ver"])
        if not self.settings.get("stump_times_repaired"):
            n = self.store.repair_stump_times(list(self.stumps))
            if n:
                self.log(f"put {n} Stump line(s) back in the order they arrived")
            self.settings["stump_times_repaired"] = True
            self.settings.save()
        self._apply_propagation_setting()
        # Messages that were in flight when the app closed can't be resumed.
        for m in self.store.pending_outgoing():
            self.store.update_message(m["id"], state="failed", reason="app closed before delivery")

        self.running = True
        threading.Thread(target=self._housekeeping, daemon=True, name="firefly-housekeeping").start()
        # Voice notes received before this version (or while exporting was off) go to the SD card too.
        if self.settings.get("voice_to_sd", True):
            threading.Thread(target=self.export_voice_notes, daemon=True).start()
        # The radio comes up after everything else, in the background.
        from .radio import RadioManager
        self.radio = RadioManager(self)
        self.radio.start()
        # The handheld's own network (as EmulationStation set it up), followed live.
        from .lan import LanManager
        self.lan = LanManager(self)
        self.lan.start()
        self.log(f"FireFly address {self.address}  identity {self.identity.hash.hex()}")

    def stop(self):
        self.running = False
        radio = getattr(self, "radio", None)
        if radio:
            radio.stop()
        lan = getattr(self, "lan", None)
        if lan:
            lan.stop()
        for w in list(getattr(self, "web", {}).values()):
            w.stop()
        try:
            self.router.exit_handler()
        except Exception:
            pass
        try:
            RNS.Transport.exit_handler()   # persist path tables etc. cleanly
        except Exception:
            pass
        os.sync()                          # flush everything to the SD card before we exit

    def _load_identity(self):
        """Load the identity key, never silently replacing a damaged one.

        The key IS the user's address. It is written with fsync plus a backup
        copy, because handhelds are often switched off by cutting power, and a
        freshly written file that was never synced can come back empty."""
        path, backup = self.paths.identity, self.paths.identity + ".bak"
        for candidate in (path, backup):
            if _plausible_key(candidate):
                ident = RNS.Identity.from_file(candidate)
                if ident:
                    if candidate == backup:
                        self.log("identity key was damaged; restored from backup")
                        self.status_note = "Identity key was damaged and restored from backup"
                    self._write_identity(ident)
                    return ident
        if os.path.exists(path):
            # Unreadable and no good backup: keep the damaged file for inspection.
            damaged = f"{path}.damaged-{int(time.time())}"
            os.replace(path, damaged)
            self.log(f"identity key unreadable, kept as {damaged}; creating a new identity")
            self.status_note = "Identity key was unreadable: a NEW address was created"
        ident = RNS.Identity()
        self._write_identity(ident)
        return ident

    def _write_identity(self, ident):
        key = ident.get_private_key()
        for target in (self.paths.identity, self.paths.identity + ".bak"):
            if os.path.isfile(target) and os.path.getsize(target) == 64:
                with open(target, "rb") as f:
                    if f.read() == key:
                        continue
            tmp = target + ".tmp"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                os.write(fd, key)
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(tmp, target)
        _fsync_dir(os.path.dirname(self.paths.identity))

    @property
    def address(self):
        return self.local.hash.hex()

    @property
    def shared_instance(self):
        return bool(getattr(self.reticulum, "is_connected_to_shared_instance", False))

    # ================================================================ announces
    def on_interface_online(self):
        """A new link came up: announce (at most every 15 s) and collect messages."""
        if time.time() - self.last_announce > 15:
            self.announce()
        self.request_sync()

    def _tag_announces(self):
        """Say "I'm a Stump app" in every LXMF announce (Stump 1.0.0-beta.53, CLIENT_QUICKSTART
        "Saying you're a Stump app"): a fourth app-data item, "stump:firefly-rk3326/<version>".
        Stumps then never reword their lines for FireFly, from the first message, over LoRa too.
        Then (Stump 1.0.0-beta.82, "Packed text") a fifth, {"z": 1}: FireFly reads packed text.
        LXMF 1.3.1 announces four items: its fourth is the fractional stamp cost, None when no
        stamp is asked (FireFly asks none), and readers fall back to the second when it isn't a
        number. The tag takes that place, as Stumps put None there in their own announces.
        Reticulum 1.6.1 adds its announce stamp after all this (it isn't part of the app data
        LXMF builds here) and takes it off again on the receiving side."""
        orig = self.router.get_announce_app_data

        def app_data(destination_hash):
            data = orig(destination_hash)
            try:
                items = msgpack.unpackb(data) if data else None
                if isinstance(items, list) and len(items) in (3, 4):
                    return msgpack.packb(items[:3] + [APP_TAG] + ([{"z": 1}] if self.packed_text_on() else []))
            except Exception:
                pass
            return data
        self.router.get_announce_app_data = app_data

    def announce(self):
        self.local.display_name = self.settings["display_name"]
        self.router.announce(self.local.hash)
        self.last_announce = time.time()

    def announce_stamp_pending(self):
        """True while Reticulum 1.6.1 is still making this address's announce stamp (once per
        address, kept afterwards). Until then it sends no announce and answers no path request."""
        local = getattr(self, "local", None)
        return bool(getattr(RNS.Transport, "STAMP_DESTINATIONS", False)) and local is not None \
            and getattr(local, "stamp", True) is None

    def set_display_name(self, name):
        name = name.strip()[:64] or "R36 Operator"
        self.settings["display_name"] = name
        self.settings.save()
        # LXMF builds announce app data from the router's delivery destination.
        self.local.display_name = name
        self.announce()

    def _on_delivery_announce(self, dest_hash, identity, app_data):
        if dest_hash == self.local.hash or dest_hash.hex() in self._blocked:
            return
        app_data = without_stamp(app_data)
        self._note_packs(dest_hash.hex(), app_data)
        name = LXMF.display_name_from_app_data(app_data) if app_data else None
        hops = RNS.Transport.hops_to(dest_hash)
        self.store.upsert_peer(dest_hash.hex(), "lxmf", name=name, hops=hops,
                               stamp_cost=LXMF.stamp_cost_from_app_data(app_data) if app_data else None)
        # Is it a Stump? Asking is faster than waiting up to 30 min for a beacon.
        h = dest_hash.hex()
        if identity and h not in self.stumps and not self._asked_beacon(h):
            RNS.Transport.request_path(stump.beacon_hash_for(identity))

    # ---------------------------------------------------------------- packed text (ztext.py)
    def packed_text_on(self):
        """Packed text is said in the announce, and sent: settings "packed_text" (on by default)."""
        return bool(self.settings.get("packed_text", True)) and ztext.available()

    def _note_packs(self, peer_hex, app_data):
        """What the latest announce of this address says: packed text or not."""
        with self.lock:
            self.packs.pop(peer_hex, None)
            if len(self.packs) >= PACKS_MAX:
                self.packs.pop(next(iter(self.packs)))
            self.packs[peer_hex] = reads_packed(app_data)

    def packs_for(self, peer_hex):
        """True when text to this address goes packed: its latest announce said {"z": 1}.
        Not heard this session: the announce Reticulum keeps (known destinations)."""
        if not self.packed_text_on():
            return False
        v = self.packs.get(peer_hex)
        if v is None:
            try:
                v = reads_packed(RNS.Identity.recall_app_data(bytes.fromhex(peer_hex)))
            except Exception:
                v = False
        return v

    def outgoing_content(self, peer_hex, text):
        """A message's content as it goes to this address: packed (bytes) when it reads packed
        text and that is shorter (ztext.pack: never longer, short lines as they are), else the text."""
        if not self.packs_for(peer_hex):
            return text
        return ztext.pack(text.encode("utf-8"))

    _beacon_asked = set()

    def _asked_beacon(self, h):
        if h in self._beacon_asked:
            return True
        self._beacon_asked.add(h)
        return False

    def _on_stump_beacon(self, lxmf_hex, name, version):
        self.stumps[lxmf_hex] = (name, version)
        self.store.upsert_peer(lxmf_hex, "lxmf", heard=False, stump=name, stump_ver=version)
        # Its propagation node, if switched on, lives on the same identity. It announces
        # rarely, so compute its address and ask for its path now.
        ident = RNS.Identity.recall(bytes.fromhex(lxmf_hex))
        if ident is not None:
            pn = RNS.Destination.hash(ident, "lxmf", "propagation")
            if pn.hex() not in self.stump_pn:
                self.stump_pn[pn.hex()] = name
                RNS.Transport.request_path(pn)

    def _on_stump_signal(self, peer_hex):
        """A peer whose messages only a Stump sends (a room batch title, '→ #room',
        a reply token, an AUTH-CHALLENGE): treat it as a Stump even though its beacon
        never reached us (a computer Stump behind a chain, say), and ask for the beacon
        again so its name and release fill in."""
        p = self.store.peer(peer_hex) or {}
        name = p.get("name") or "Stump"
        self.log(f"{peer_hex[:8]} talks like a Stump (no beacon heard yet): marking it as one")
        self._on_stump_beacon(peer_hex, name, "beacon not heard")
        self._beacon_asked.discard(peer_hex)
        ident = RNS.Identity.recall(bytes.fromhex(peer_hex))
        if ident is not None:
            RNS.Transport.request_path(stump.beacon_hash_for(ident))

    def is_stump(self, peer_hex):
        return peer_hex in self.stumps

    def _on_propagation_announce(self, dest_hash, app_data, identity=None):
        if not LXMF.pn_announce_data_is_valid(app_data):
            return
        try:
            enabled = bool(msgpack.unpackb(app_data)[2])
        except Exception:
            enabled = False
        name = None
        try:
            name = LXMF.pn_name_from_app_data(app_data)
        except Exception:
            pass
        self.store.upsert_peer(dest_hash.hex(), "propagation", name=name or "Propagation node",
                               hops=RNS.Transport.hops_to(dest_hash), extra="on" if enabled else "off")
        stump_name = self.stump_pn.get(dest_hash.hex())
        if identity is not None and not stump_name:   # same identity as a known Stump?
            lxmf_hex = RNS.Destination.hash(identity, "lxmf", "delivery").hex()
            if lxmf_hex in self.stumps:
                stump_name = self.stumps[lxmf_hex][0]
                self.stump_pn[dest_hash.hex()] = stump_name
        if stump_name:
            self.store.upsert_peer(dest_hash.hex(), "propagation", heard=False, stump=stump_name)
        if self.settings["propagation_mode"] == "auto" and enabled:
            self._auto_pick_propagation()

    def _on_nomad_announce(self, dest_hash, app_data):
        app_data = without_stamp(app_data)
        try:
            name = app_data.decode("utf-8") if app_data else None
        except Exception:
            name = None
        self.store.upsert_peer(dest_hash.hex(), "nomadnode", name=name, hops=RNS.Transport.hops_to(dest_hash))

    # ================================================================ propagation
    def _apply_propagation_setting(self):
        mode = self.settings["propagation_mode"]
        if mode == "manual" and self.settings["propagation_node"]:
            try:
                self.router.set_outbound_propagation_node(bytes.fromhex(self.settings["propagation_node"]))
            except ValueError:
                pass
        elif mode == "auto":
            self._auto_pick_propagation()

    def _auto_pick_propagation(self):
        """A Stump's node first (Stump nodes don't peer yet, so everyone near one
        should use the same), otherwise the nearest enabled node heard in the last day."""
        best = None
        for p in self.store.peers("propagation"):
            if p["extra"] != "on" or not p["last_heard"] or time.time() - p["last_heard"] > 86400:
                continue
            rank = (0 if p["stump"] else 1, p["hops"] if p["hops"] is not None else 99)
            if best is None or rank < best[0]:
                best = (rank, p)
        best = best[1] if best else None
        if best:
            current = self.router.get_outbound_propagation_node()
            if current is None or current.hex() != best["hash"]:
                self.router.set_outbound_propagation_node(bytes.fromhex(best["hash"]))
                self.request_sync()          # a node was chosen: collect from it

    def propagation_node(self):
        node = self.router.get_outbound_propagation_node()
        return node.hex() if node else None

    def request_sync(self, min_gap=120):
        """Sync soon, unless one ran within min_gap seconds (or is running)."""
        if time.time() - self.last_sync >= min_gap:
            self._sync_wanted = True

    def sync(self):
        """Fetch messages waiting for us on the propagation node."""
        if not self.propagation_node():
            self.sync_state = "no propagation node"
            return False
        self.last_sync = time.time()
        self._sync_waiting = True
        self.router.request_messages_from_propagation_node(self.identity)
        return True

    def sync_status(self):
        st = self.router.propagation_transfer_state
        names = {
            LXMRouter.PR_IDLE: "idle", LXMRouter.PR_PATH_REQUESTED: "finding node",
            LXMRouter.PR_LINK_ESTABLISHING: "connecting", LXMRouter.PR_LINK_ESTABLISHED: "connected",
            LXMRouter.PR_REQUEST_SENT: "requesting", LXMRouter.PR_RECEIVING: "receiving",
            LXMRouter.PR_RESPONSE_RECEIVED: "received", LXMRouter.PR_COMPLETE: "done",
            LXMRouter.PR_NO_PATH: "no path to node", LXMRouter.PR_LINK_FAILED: "link failed",
            LXMRouter.PR_TRANSFER_FAILED: "transfer failed", LXMRouter.PR_NO_IDENTITY_RCVD: "node needs identity",
            LXMRouter.PR_NO_ACCESS: "no access",
        }
        return names.get(st, "failed")

    # ================================================================ sending
    def send(self, peer_hex, text, method="auto", title=""):
        """Queue a message. Returns the message id; state updates arrive in the Store."""
        text = text.rstrip()
        if not text:
            return None
        if peer_hex in self.stumps:
            text, title = stump.safe_for_stump(text, title)
        web = self.web.get(peer_hex)
        if web is not None and web.online and method != "propagated" and self.settings.get("stump_wifi", True):
            msg_id = self.store.add_message(peer_hex, True, text, "sending", title=title, method="wifi")
            threading.Thread(target=self._send_web, args=(web, msg_id, peer_hex, text, title), daemon=True).start()
            return msg_id
        msg_id = self.store.add_message(peer_hex, True, text, "pending", title=title)
        threading.Thread(target=self._send_worker, args=(msg_id, peer_hex, text, method, title),
                         daemon=True).start()
        return msg_id

    def _recall(self, dest_hash, wait=None, on_slow=None):
        """The peer's identity, asking the network for its path when it isn't known yet.
        on_slow() is called once, when the first answer is late (the message says why it waits)."""
        wait = PATH_WAIT_S if wait is None else wait
        ident = RNS.Identity.recall(dest_hash)
        if ident is None:
            RNS.Transport.request_path(dest_hash)
            start = time.time()
            next_ask = start + PATH_ASK_AGAIN_S[0]
            while ident is None and time.time() < start + wait and self.running:
                time.sleep(0.5)
                ident = RNS.Identity.recall(dest_hash)
                if ident is None and time.time() >= next_ask:
                    if on_slow is not None and next_ask == start + PATH_ASK_AGAIN_S[0]:
                        on_slow()
                    RNS.Transport.request_path(dest_hash)
                    next_ask += PATH_ASK_AGAIN_S[1]
        return ident

    def _send_web(self, web, msg_id, peer_hex, text, title):
        """Stump chat over the local network; LoRa (LXMF, directly) if that fails."""
        try:
            web.send(text)
            self.store.update_message(msg_id, state="delivered", method="wifi")
        except Exception as e:
            self.log(f"Wi-Fi send to {web.name} failed ({e}); trying LoRa")
            self.store.update_message(msg_id, state="pending", method=None, reason="Wi-Fi failed: trying LoRa")
            self._send_worker(msg_id, peer_hex, text, "auto", title)

    def sync_web(self, lan_stumps):
        """The Stumps on the local network now: start or stop their Wi-Fi sessions."""
        from .stumpweb import StumpWeb
        want = {k: v for k, v in lan_stumps.items() if self.settings.get("stump_wifi", True)}
        for k in list(self.web):
            if k not in want or self.web[k].base != (want[k].get("here") or (want[k].get("http") or [""])[0]).rstrip("/"):
                self.web.pop(k).stop()
        for k, info in want.items():
            if k not in self.web and (info.get("here") or info.get("http")):
                if k not in self.stumps:          # met on the network first: it's a Stump all the same
                    self._on_stump_beacon(k, info["name"], info.get("release") or "on this network")
                w = StumpWeb(self, info)
                self.web[k] = w
                w.start()

    def _send_worker(self, msg_id, peer_hex, text, method, title):
        dest_hash = bytes.fromhex(peer_hex)
        # First message to someone this session: announce first (unless just done),
        # so they hold our key and can verify the signature.
        with self.lock:
            first = peer_hex not in self._written_to
            self._written_to.add(peer_hex)
        if first and time.time() - self.last_announce > 30:
            self.announce()
        slow = []
        def on_slow():
            slow.append(1)
            self.store.update_message(msg_id, reason="waiting for their path (up to 3 min: "
                                                     "a new Reticulum app answers once ready)")
        ident = self._recall(dest_hash, on_slow=on_slow)
        if ident is not None and slow:
            self.store.update_message(msg_id, reason=None)
        if ident is None:
            self.store.update_message(msg_id, state="failed",
                                      reason="unknown peer: no announce or path heard yet")
            return
        dest = RNS.Destination(ident, RNS.Destination.OUT, RNS.Destination.SINGLE, "lxmf", "delivery")
        if method == "propagated" and self.propagation_node() and not self.is_stump(peer_hex):
            desired = LXMessage.PROPAGATED
        elif method == "direct":
            desired = LXMessage.DIRECT
        else:
            # LoRa-friendly default: one packet, no link setup. LXMF falls back
            # to a link by itself when the message is too big for one packet.
            desired = LXMessage.OPPORTUNISTIC
        lxm = LXMessage(dest, self.local, self.outgoing_content(peer_hex, text), title=title, desired_method=desired)
        lxm.register_delivery_callback(lambda m, i=msg_id: self._on_delivered(i, m))
        lxm.register_failed_callback(lambda m, i=msg_id: self._on_failed(i, m, peer_hex, text, title))
        with self.lock:
            self.outbound[msg_id] = lxm
        try:
            self.router.handle_outbound(lxm)
        except Exception as e:
            self.store.update_message(msg_id, state="failed", reason=str(e))
            with self.lock:
                self.outbound.pop(msg_id, None)
            return
        self.store.update_message(msg_id, lxm_hash=lxm.hash.hex() if lxm.hash else None,
                                  method=_method_name(lxm.method))

    def _on_delivered(self, msg_id, lxm):
        state = "stored" if lxm.method == LXMessage.PROPAGATED else "delivered"
        with self.lock:
            self.outbound.pop(msg_id, None)
            self.store.update_message(msg_id, state=state, method=_method_name(lxm.method))

    def _on_failed(self, msg_id, lxm, peer_hex, text, title):
        with self.lock:
            self.outbound.pop(msg_id, None)
        if (lxm.method != LXMessage.PROPAGATED and self.settings["fallback_to_propagation"]
                and self.propagation_node() and not self.is_stump(peer_hex)):
            # Peer unreachable right now: hand it to the propagation node instead.
            self.store.update_message(msg_id, state="pending", reason="retrying via propagation node")
            threading.Thread(target=self._send_worker, args=(msg_id, peer_hex, text, "propagated", title),
                             daemon=True).start()
            return
        reason = "not delivered"
        if self.is_stump(peer_hex):
            # A Stump ignores chat that reaches it late through a propagation node: send again later.
            reason = "not delivered (Stump chat only goes directly)"
        self.store.update_message(msg_id, state="failed", reason=reason)

    # Progress only moves forward, and a final state (delivered, stored, failed)
    # is never overwritten: the delivery proof can arrive between the moment
    # this monitor reads a message and the moment it writes.
    _PROGRESS = {"pending": 0, "stamping": 1, "sending": 2, "sent": 3}

    def _monitor_outbound(self):
        names = {LXMessage.GENERATING: "stamping", LXMessage.OUTBOUND: "pending",
                 LXMessage.SENDING: "sending", LXMessage.SENT: "sent"}
        with self.lock:
            items = list(self.outbound.items())
        for msg_id, lxm in items:
            st = names.get(lxm.state)
            if not st:
                continue
            with self.lock:
                if msg_id not in self.outbound:      # finished meanwhile
                    continue
                row = self.store.message(msg_id)
                if not row or row["state"] not in self._PROGRESS:
                    continue
                if self._PROGRESS[st] > self._PROGRESS[row["state"]]:
                    self.store.update_message(msg_id, state=st)

    # ================================================================ receiving
    def _on_message(self, lxm):
        peer = lxm.source_hash.hex()
        if peer in self._blocked:
            return
        lxm_hash = lxm.hash.hex() if lxm.hash else None
        if lxm_hash and self.store.has_message(lxm_hash):
            return  # duplicate (e.g. delivered directly and again via propagation node)
        if lxm.content:
            lxm.content = unpacked_content(lxm.content)     # packed text (Stump 1.0.0-beta.82)
        content = lxm.content_as_string() if lxm.content else ""
        if content is None:     # not UTF-8 (binary, or packed and unreadable): a note, not a crash
            content = f"⊘ {len(lxm.content)} bytes FireFly can't read as text"
        attachments = []
        for fid, label in FIELD_NAMES.items():
            if lxm.fields and fid in lxm.fields:
                attachments.append(label)
        audio = {}
        if lxm.fields and LXMF.FIELD_AUDIO in lxm.fields:
            audio = self._save_voice(lxm.fields[LXMF.FIELD_AUDIO], lxm_hash or str(time.time()))
        verified = bool(getattr(lxm, "signature_validated", False))
        if not verified:
            # Unknown sender identity: ask for their path so we learn who they are.
            RNS.Transport.request_path(lxm.source_hash)
        self.store.upsert_peer(peer, "lxmf", heard=True)
        fields = lxm.fields if isinstance(lxm.fields, dict) else {}
        renderer = fields.get(LXMF.FIELD_RENDERER)
        renderer = renderer if isinstance(renderer, int) and not isinstance(renderer, bool) else None
        asked = commands_asked(fields.get(LXMF.FIELD_COMMANDS))
        if asked:
            self._decline_commands(peer, asked)
            if not content.strip() and not audio and not attachments:
                # Only a request (Sideband asks for telemetry this way): a short note, no empty bubble.
                content = ("⊘ Asked for " + " and ".join(COMMAND_NAMES.get(c, "a command") for c in asked)
                           + ": declined (FireFly doesn't share it)")
        # A Stump's lines are filed by when they arrive: its clock may be unset (a CAM
        # has no battery clock) and its chat is never stored and forwarded.
        ts = time.time() if peer in self.stumps else (lxm.timestamp or time.time())
        self.store.add_message(peer, False, content, "received", ts=ts,
                               title=lxm.title_as_string() if lxm.title else "",
                               method=_method_name(lxm.method), lxm_hash=lxm_hash,
                               rssi=getattr(lxm, "rssi", None), snr=getattr(lxm, "snr", None),
                               verified=verified, attachments=", ".join(attachments) or None,
                               unread=not (asked and content.startswith("⊘ Asked for ")), renderer=renderer, **audio)
        title0 = lxm.title_as_string() if lxm.title else ""
        if peer not in self.stumps and stump.looks_like_stump(content, title0):
            self._on_stump_signal(peer)
        if peer in self.stumps:
            title = lxm.title_as_string() if lxm.title else ""
            items = stump.parse_message(content, title)
            self.stump_state.setdefault(peer, stump.NodeState()).update(items)
        if peer in self.auth:
            self._feed_auth(peer, content)

    DECLINE_EVERY_S = 3600

    def _decline_commands(self, peer, asked):
        """Sideband and MeshChat can ask another app for its location, telemetry, a ping or
        a signal report (LXMF FIELD_COMMANDS). FireFly shares none of that: it says so, once
        an hour per contact, in a line any LXMF app shows. Never to a Stump."""
        if peer in self.stumps or peer in self._blocked:
            return
        now = time.time()
        last = self._declined.get(peer, 0)
        if now - last < self.DECLINE_EVERY_S:
            return
        self._declined[peer] = now
        what = " or ".join(sorted({COMMAND_NAMES.get(c, "commands") for c in asked}))
        self.log(f"{peer[:8]} asked for {what}: declining")
        self.send(peer, f"FireFly (handheld) doesn't share location, telemetry or signal reports, so your "
                        f"request for {what} was declined. Text and voice notes work as usual.")

    def _save_voice(self, field, name):
        """Keep a received voice note on disk; the message row points at it."""
        from . import voice
        parsed = voice.parse_field(field)
        if parsed is None:
            self.log("ignored a malformed or oversized voice-note field")
            return {}
        mode, data = parsed
        try:
            path = voice.save(self.paths.audio, name, mode, data)
        except OSError as e:
            self.log(f"could not save voice note: {e}")
            return {}
        ms = voice.duration_ms(mode, data)
        secs = None if ms is None else ms / 1000.0
        self.log(f"voice note received: {voice.describe(mode)}, {len(data)} bytes, {voice.label(ms)}")
        if self.settings.get("voice_to_sd", True):
            threading.Thread(target=self.export_voice_notes, daemon=True).start()
        return {"audio_mode": mode, "audio_path": path, "audio_secs": secs}

    def export_voice_notes(self):
        """Copy voice notes not yet on the SD card. Returns (copied, folder, errors)."""
        from . import voice
        time.sleep(0.5)          # let the message row be written first
        folder = voice.export_dir(self.settings.get("voice_export_dir", "auto"))
        copied, errors = 0, []
        with self.lock:
            if getattr(self, "_exporting", False):
                return 0, folder, []
            self._exporting = True
        try:
            for c in self.store.conversations():
                p = self.store.peer(c["peer"]) or {}
                sender = p.get("name") or c["peer"][:8]
                for note in self.store.voice_notes(c["peer"], 500):
                    if not voice.row_playable(note) or not note["audio_path"] \
                            or not os.path.isfile(note["audio_path"]):
                        continue
                    try:
                        before = len(os.listdir(folder)) if os.path.isdir(folder) else 0
                        path, secs = voice.export_note(note, sender, folder)
                        if len(os.listdir(folder)) != before:
                            copied += 1
                            self.log(f"voice note copied to {path} ({secs:.1f} s decoded)")
                    except (voice.VoiceError, OSError) as e:
                        errors.append(str(e))
        finally:
            self._exporting = False
        self.voice_export_status = (folder, copied, errors[-1] if errors else None)
        return copied, folder, errors

    # ================================================================ Stump /auth
    def start_stump_auth(self, peer_hex):
        """Run the /auth handshake with a Stump node. Returns False if one is already running."""
        with self.lock:
            sess = self.auth.get(peer_hex)
            if sess and sess.busy and time.time() - sess.started < stump.AUTH_WINDOW_S + 30:
                return False
            sess = stump.AuthSession(peer_hex)
            self.auth[peer_hex] = sess
            line = sess.start()
        self._send_stump_control(peer_hex, line)
        return True

    def auth_state(self, peer_hex):
        return self.auth.get(peer_hex)

    def _feed_auth(self, peer_hex, content):
        sess = self.auth[peer_hex]
        for parsed in stump.parse_message(content):
            reply = sess.on_line(parsed, self.identity)
            if reply:
                self._send_stump_control(peer_hex, reply)

    def _send_stump_control(self, peer_hex, line):
        # Must stay one packet: empty title, no fields, opportunistic, never propagated.
        assert single_packet_size(line) <= stump.SINGLE_PACKET_LIMIT
        self.send(peer_hex, line, method="opportunistic")

    # ================================================================ network info
    def interface_stats(self):
        try:
            return self.reticulum.get_interface_stats() or {}
        except Exception:
            return {}

    def request_path(self, peer_hex):
        RNS.Transport.request_path(bytes.fromhex(peer_hex))

    def hops(self, peer_hex):
        try:
            h = RNS.Transport.hops_to(bytes.fromhex(peer_hex))
            return None if h == RNS.Transport.PATHFINDER_M else h
        except Exception:
            return None

    def add_contact(self, text):
        """An address typed or pasted, bare or as a link (addresses.py). -> (hex, how): how is
        "key" (its key checked and handed to Reticulum: writable now), "stump" or "plain"."""
        from . import addresses
        if addresses.is_paper_message(text):
            raise ValueError("that's a paper message (lxm://), not an address")
        a = addresses.parse(text)
        if a is None:
            raise ValueError("an LXMF address is 32 hex characters (or an lxma:// / lxmf:// link)")
        h = a["address"]
        if a["key_bad"]:
            raise ValueError("not trusted: the link's key isn't a Reticulum key")
        ident = None
        if a["key"] is not None:
            ident = addresses.identity_for(h, a["key"])
            if ident is None:
                raise ValueError("not trusted: the link's key doesn't match its address")
        if h == self.address:
            raise ValueError("that's your own address")
        if h in self._blocked:
            raise ValueError("that address is blocked: unblock it in SETUP first")
        self.store.upsert_peer(h, "lxmf", heard=False, saved=1)
        how = "plain"
        if ident is not None:
            if RNS.Identity.recall(bytes.fromhex(h)) is None:
                RNS.Identity.remember(None, bytes.fromhex(h), ident.get_public_key(), None)
            how = "key"
        if a["stump"] is not None:
            # Its release from the link (r=, Stump 1.0.0-beta.79) is shown as a hint until its beacon says.
            label = f"{a['release']} (from its QR code)" if a.get("release") else "from its QR code"
            self._on_stump_beacon(h, a["stump"] or "Stump", label)
            how = "stump"
        self.request_path(h)
        return h, how

    def address_codes(self, peer_hex):
        """QR codes for an address (ours or a contact's): with the key when we know it."""
        from . import addresses
        if peer_hex == self.address:
            key, name = self.identity.get_public_key(), None
        else:
            ident = RNS.Identity.recall(bytes.fromhex(peer_hex))
            key = ident.get_public_key() if ident is not None else None
            name = self.stumps.get(peer_hex, (None,))[0]
        return addresses.codes(peer_hex, key, name)

    # ================================================================ deleting and blocking
    # Both are local: nothing is sent, and the other side isn't told.
    def _remove_audio(self, paths):
        import glob
        for p in paths:
            for f in [p] + glob.glob(p + ".wav*"):
                try:
                    os.remove(f)
                except OSError:
                    pass

    def delete_message(self, msg_id):
        with self.lock:
            self.outbound.pop(msg_id, None)
        self._remove_audio(self.store.delete_message(msg_id))

    def delete_conversation(self, peer_hex):
        """Removes the conversation and the contact. They come back as new
        if they announce or write again."""
        with self.lock:
            for mid in [i for i, _ in self.outbound.items() if (self.store.message(i) or {}).get("peer") == peer_hex]:
                self.outbound.pop(mid, None)
            self.auth.pop(peer_hex, None)
            self.stump_state.pop(peer_hex, None)
            self._written_to.discard(peer_hex)
        self._remove_audio(self.store.delete_conversation(peer_hex))

    def block(self, peer_hex):
        """Delete, then ignore this address's announces and messages from now on,
        including in LXMF's own ignore list. Works for an address never heard again."""
        name = (self.store.peer(peer_hex) or {}).get("name")
        self.delete_conversation(peer_hex)
        self.store.block(peer_hex, name)
        self._blocked.add(peer_hex)
        self.router.ignore_destination(bytes.fromhex(peer_hex))

    def unblock(self, peer_hex):
        self.store.unblock(peer_hex)
        self._blocked.discard(peer_hex)
        self.router.unignore_destination(bytes.fromhex(peer_hex))

    def is_blocked(self, peer_hex):
        return peer_hex in self._blocked

    # ================================================================ background jobs
    def _housekeeping(self):
        time.sleep(3)
        if self.settings["announce_interval_min"] > 0:
            self.announce()
        first_sync_done = False
        while self.running:
            now = time.time()
            self._monitor_outbound()
            ai = self.settings["announce_interval_min"] * 60
            if ai and now - self.last_announce > ai:
                self.announce()
            si = self.settings["sync_interval_min"] * 60
            idle = not self._sync_waiting
            due = (getattr(self, "_sync_wanted", False) or (not first_sync_done and now - self.started_at > 20)
                   or (si and now - self.last_sync > si)
                   or (self._sync_retry_at and now >= self._sync_retry_at))
            if self.propagation_node() and idle and due:
                first_sync_done = True
                self._sync_wanted = False
                self._sync_retry_at = 0.0
                self.sync()
            self._follow_up_sync()
            self.sync_state = self.sync_status()
            time.sleep(MONITOR_INTERVAL_S)

    def _follow_up_sync(self):
        """A node may hold more than one sync reply carries (Stump: ~16 KB per
        reply). If a sync brought messages, ask again, up to 5 rounds."""
        st = self.router.propagation_transfer_state
        if not self._sync_waiting or st not in (LXMRouter.PR_COMPLETE, LXMRouter.PR_NO_PATH,
                                                LXMRouter.PR_LINK_FAILED, LXMRouter.PR_TRANSFER_FAILED,
                                                LXMRouter.PR_NO_IDENTITY_RCVD, LXMRouter.PR_NO_ACCESS):
            return
        self._sync_waiting = False
        if st != LXMRouter.PR_COMPLETE:
            # A failed round is retried after 10 s, then 30 s, then left to the timer.
            self._sync_failures += 1
            if self._sync_failures <= 2:
                self._sync_retry_at = time.time() + (10 if self._sync_failures == 1 else 30)
            self._sync_rounds = 0
            return
        self._sync_failures = 0
        got = self.router.propagation_transfer_last_result or 0
        if got > 0 and self._sync_rounds < 4:      # up to 5 rounds while they bring messages
            self._sync_rounds += 1
            self.sync()
        else:
            self._sync_rounds = 0


def _plausible_key(path):
    """64 bytes and not blank: power loss can leave a file zero-filled, which
    would otherwise load as a valid but different key."""
    try:
        if os.path.getsize(path) != 64:
            return False
        with open(path, "rb") as f:
            data = f.read()
        return len(set(data)) > 8
    except OSError:
        return False


def _fsync_dir(d):
    try:
        fd = os.open(d, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def _method_name(m):
    return {LXMessage.OPPORTUNISTIC: "opportunistic", LXMessage.DIRECT: "direct",
            LXMessage.PROPAGATED: "propagated", LXMessage.PAPER: "paper"}.get(m)


class _DeliveryAnnounces:
    aspect_filter = "lxmf.delivery"
    receive_path_responses = True

    def __init__(self, core): self.core = core

    def received_announce(self, destination_hash, announced_identity, app_data):
        self.core._on_delivery_announce(destination_hash, announced_identity, app_data)


class _PropagationAnnounces:
    aspect_filter = "lxmf.propagation"
    receive_path_responses = True

    def __init__(self, core): self.core = core

    def received_announce(self, destination_hash, announced_identity, app_data):
        self.core._on_propagation_announce(destination_hash, app_data, announced_identity)


class _NomadNodeAnnounces:
    aspect_filter = "nomadnetwork.node"
    receive_path_responses = False

    def __init__(self, core): self.core = core

    def received_announce(self, destination_hash, announced_identity, app_data):
        self.core._on_nomad_announce(destination_hash, app_data)
