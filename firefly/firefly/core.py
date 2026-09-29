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

from . import stump
from .rnsconfig import write_config
from .settings import Settings
from .store import Store

PATH_WAIT_S = 20          # how long to wait for an unknown peer's path/identity before failing
MONITOR_INTERVAL_S = 1.0

# LXMF field ids we recognise but can't render yet, described as text instead.
FIELD_NAMES = {
    LXMF.FIELD_IMAGE: "image",
    LXMF.FIELD_AUDIO: "voice message",
    LXMF.FIELD_FILE_ATTACHMENTS: "file",
    LXMF.FIELD_TELEMETRY: "location/telemetry",
    LXMF.FIELD_EMBEDDED_LXMS: "embedded message",
}


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
        self.stumps = {}            # lxmf hash hex -> (name, version)
        self.running = False
        self.radio = None
        self.started_at = time.time()
        self.last_announce = 0.0
        self.last_sync = 0.0
        self.sync_state = "idle"
        self.status_note = ""
        if restored:
            what = "radio settings" if "radio" in restored else "settings"
            self.status_note = f"Restored your {what} from {os.path.basename(os.path.dirname(src))}"

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
        self.router = LXMRouter(identity=self.identity, storagepath=self.paths.lxmf_storage)
        self.local = self.router.register_delivery_identity(self.identity, display_name=s["display_name"])
        self.router.register_delivery_callback(self._on_message)

        RNS.Transport.register_announce_handler(_DeliveryAnnounces(self))
        RNS.Transport.register_announce_handler(_PropagationAnnounces(self))
        RNS.Transport.register_announce_handler(_NomadNodeAnnounces(self))
        RNS.Transport.register_announce_handler(stump.BeaconHandler(self._on_stump_beacon))

        for p in self.store.peers("lxmf"):   # remember which saved peers are Stumps
            if p["stump"]:
                self.stumps[p["hash"]] = (p["stump"], p["stump_ver"])
        self._apply_propagation_setting()
        # Messages that were in flight when the app closed can't be resumed.
        for m in self.store.pending_outgoing():
            self.store.update_message(m["id"], state="failed", reason="app closed before delivery")

        self.running = True
        threading.Thread(target=self._housekeeping, daemon=True, name="firefly-housekeeping").start()
        # The radio comes up after everything else, in the background.
        from .radio import RadioManager
        self.radio = RadioManager(self)
        self.radio.start()
        self.log(f"FireFly address {self.address}  identity {self.identity.hash.hex()}")

    def stop(self):
        self.running = False
        radio = getattr(self, "radio", None)
        if radio:
            radio.stop()
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
    def announce(self):
        self.local.display_name = self.settings["display_name"]
        self.router.announce(self.local.hash)
        self.last_announce = time.time()

    def set_display_name(self, name):
        name = name.strip()[:64] or "R36 Operator"
        self.settings["display_name"] = name
        self.settings.save()
        # LXMF builds announce app data from the router's delivery destination.
        self.local.display_name = name
        self.announce()

    def _on_delivery_announce(self, dest_hash, identity, app_data):
        if dest_hash == self.local.hash:
            return
        name = LXMF.display_name_from_app_data(app_data) if app_data else None
        hops = RNS.Transport.hops_to(dest_hash)
        self.store.upsert_peer(dest_hash.hex(), "lxmf", name=name, hops=hops,
                               stamp_cost=LXMF.stamp_cost_from_app_data(app_data) if app_data else None)
        # Is it a Stump? Asking is faster than waiting up to 30 min for a beacon.
        h = dest_hash.hex()
        if identity and h not in self.stumps and not self._asked_beacon(h):
            RNS.Transport.request_path(stump.beacon_hash_for(identity))

    _beacon_asked = set()

    def _asked_beacon(self, h):
        if h in self._beacon_asked:
            return True
        self._beacon_asked.add(h)
        return False

    def _on_stump_beacon(self, lxmf_hex, name, version):
        self.stumps[lxmf_hex] = (name, version)
        self.store.upsert_peer(lxmf_hex, "lxmf", heard=False, stump=name, stump_ver=version)

    def is_stump(self, peer_hex):
        return peer_hex in self.stumps

    def _on_propagation_announce(self, dest_hash, app_data):
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
        if self.settings["propagation_mode"] == "auto" and enabled:
            self._auto_pick_propagation()

    def _on_nomad_announce(self, dest_hash, app_data):
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
        """Nearest enabled propagation node we've heard in the last day."""
        best = None
        for p in self.store.peers("propagation"):
            if p["extra"] != "on" or not p["last_heard"] or time.time() - p["last_heard"] > 86400:
                continue
            if best is None or (p["hops"] or 99) < (best["hops"] or 99):
                best = p
        if best:
            current = self.router.get_outbound_propagation_node()
            if current is None or current.hex() != best["hash"]:
                self.router.set_outbound_propagation_node(bytes.fromhex(best["hash"]))

    def propagation_node(self):
        node = self.router.get_outbound_propagation_node()
        return node.hex() if node else None

    def sync(self):
        """Fetch messages waiting for us on the propagation node."""
        if not self.propagation_node():
            self.sync_state = "no propagation node"
            return False
        self.last_sync = time.time()
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
        msg_id = self.store.add_message(peer_hex, True, text, "pending", title=title)
        threading.Thread(target=self._send_worker, args=(msg_id, peer_hex, text, method, title),
                         daemon=True).start()
        return msg_id

    def _recall(self, dest_hash, wait=PATH_WAIT_S):
        ident = RNS.Identity.recall(dest_hash)
        if ident is None:
            RNS.Transport.request_path(dest_hash)
            deadline = time.time() + wait
            while ident is None and time.time() < deadline and self.running:
                time.sleep(0.5)
                ident = RNS.Identity.recall(dest_hash)
        return ident

    def _send_worker(self, msg_id, peer_hex, text, method, title):
        dest_hash = bytes.fromhex(peer_hex)
        ident = self._recall(dest_hash)
        if ident is None:
            self.store.update_message(msg_id, state="failed",
                                      reason="unknown peer: no announce or path heard yet")
            return
        dest = RNS.Destination(ident, RNS.Destination.OUT, RNS.Destination.SINGLE, "lxmf", "delivery")
        if method == "propagated" and self.propagation_node():
            desired = LXMessage.PROPAGATED
        elif method == "direct":
            desired = LXMessage.DIRECT
        else:
            # LoRa-friendly default: one packet, no link setup. LXMF falls back
            # to a link by itself when the message is too big for one packet.
            desired = LXMessage.OPPORTUNISTIC
        lxm = LXMessage(dest, self.local, text, title=title, desired_method=desired)
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
        self.store.update_message(msg_id, state=state, method=_method_name(lxm.method))
        with self.lock:
            self.outbound.pop(msg_id, None)

    def _on_failed(self, msg_id, lxm, peer_hex, text, title):
        with self.lock:
            self.outbound.pop(msg_id, None)
        if (lxm.method != LXMessage.PROPAGATED and self.settings["fallback_to_propagation"]
                and self.propagation_node()):
            # Peer unreachable right now: hand it to the propagation node instead.
            self.store.update_message(msg_id, state="pending", reason="retrying via propagation node")
            threading.Thread(target=self._send_worker, args=(msg_id, peer_hex, text, "propagated", title),
                             daemon=True).start()
            return
        self.store.update_message(msg_id, state="failed", reason="not delivered")

    def _monitor_outbound(self):
        names = {LXMessage.GENERATING: "stamping", LXMessage.OUTBOUND: "pending",
                 LXMessage.SENDING: "sending", LXMessage.SENT: "sent"}
        with self.lock:
            items = list(self.outbound.items())
        for msg_id, lxm in items:
            st = names.get(lxm.state)
            if st:
                row = self.store.message(msg_id)
                if row and row["state"] != st:
                    self.store.update_message(msg_id, state=st)

    # ================================================================ receiving
    def _on_message(self, lxm):
        peer = lxm.source_hash.hex()
        lxm_hash = lxm.hash.hex() if lxm.hash else None
        if lxm_hash and self.store.has_message(lxm_hash):
            return  # duplicate (e.g. delivered directly and again via propagation node)
        content = lxm.content_as_string() if lxm.content else ""
        attachments = []
        for fid, label in FIELD_NAMES.items():
            if lxm.fields and fid in lxm.fields:
                attachments.append(label)
        verified = bool(getattr(lxm, "signature_validated", False))
        if not verified:
            # Unknown sender identity: ask for their path so we learn who they are.
            RNS.Transport.request_path(lxm.source_hash)
        self.store.upsert_peer(peer, "lxmf", heard=True)
        self.store.add_message(peer, False, content, "received", ts=lxm.timestamp or time.time(),
                               title=lxm.title_as_string() if lxm.title else "",
                               method=_method_name(lxm.method), lxm_hash=lxm_hash,
                               rssi=getattr(lxm, "rssi", None), snr=getattr(lxm, "snr", None),
                               verified=verified, attachments=", ".join(attachments) or None, unread=True)
        if peer in self.auth:
            self._feed_auth(peer, content)

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

    def add_contact(self, hex_addr):
        hex_addr = hex_addr.strip().lower().replace("<", "").replace(">", "").replace(":", "")
        if len(hex_addr) != 32 or any(c not in "0123456789abcdef" for c in hex_addr):
            raise ValueError("an LXMF address is 32 hex characters")
        self.store.upsert_peer(hex_addr, "lxmf", heard=False, saved=1)
        self.request_path(hex_addr)
        return hex_addr

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
            if self.propagation_node() and self.router.propagation_transfer_state in (
                    LXMRouter.PR_IDLE, LXMRouter.PR_COMPLETE) and (
                    (not first_sync_done and now - self.started_at > 60) or (si and now - self.last_sync > si)):
                first_sync_done = True
                self.sync()
            self.sync_state = self.sync_status()
            time.sleep(MONITOR_INTERVAL_S)


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
        self.core._on_propagation_announce(destination_hash, app_data)


class _NomadNodeAnnounces:
    aspect_filter = "nomadnetwork.node"
    receive_path_responses = False

    def __init__(self, core): self.core = core

    def received_announce(self, destination_hash, announced_identity, app_data):
        self.core._on_nomad_announce(destination_hash, app_data)
