"""Chatting with a Stump over Wi-Fi, through its web API (CLIENT_QUICKSTART:
"The greeting", "RRC over HTTP").

When a Stump answers `STUMP?` on the network the handheld is on, FireFly
greets it with `/hello` (both sides prove who they are: the Stump signs a
one-time code with its identity, FireFly answers with the same signature
`/auth` uses), then polls `/rrc/poll` and sends with `/rrc/send`. The
conversation is the same one as over LoRa, filed under the Stump's LXMF
address: lines are stored in the line protocol's own form, so the chat screen
shows them exactly as it shows LoRa batches. Over LoRa it all keeps working
when the Wi-Fi isn't there.
"""
import json
import random
import threading
import time
import urllib.error
import urllib.request

import RNS

from . import stump as stumpproto

POLL_S = 2.0
POLL_MAX_S = 30.0
TIMEOUT_S = 8.0
MAX_BODY = 256 * 1024
VOICE_MAX = 64 * 1024

# Never through a proxy: the Stump is on the local network.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class WebError(Exception):
    def __init__(self, status, body=None):
        super().__init__(f"HTTP {status}")
        self.status, self.body = status, body or {}


def _http(method, url, body=None, ctype="text/plain; charset=utf-8", raw=False):
    req = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", ctype)
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "FireFly-RK3326")
    try:
        with _OPENER.open(req, timeout=TIMEOUT_S) as r:
            data = r.read(MAX_BODY + 1)[:MAX_BODY]
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read(8192).decode("utf-8", "replace"))
        except Exception:
            payload = {}
        raise WebError(e.code, payload)
    if raw:
        return data
    if not data.strip():
        return {}
    return json.loads(data.decode("utf-8", "replace"))


def verify_stump(card, lxmf_hex):
    """GET /hello's card: the Stump signed nonce + its LXMF address with the key whose
    LXMF address is the one we expect. True only if both hold."""
    try:
        pub = bytes.fromhex(card["pub"])
        sig = bytes.fromhex(card["sig"])
        ident = RNS.Identity(create_keys=False)
        ident.load_public_key(pub)
        if RNS.Destination.hash(ident, "lxmf", "delivery").hex() != lxmf_hex:
            return False
        return bool(ident.validate(sig, (card["nonce"] + card["lxmf"]).encode()))
    except Exception:
        return False


def to_lines(m):
    """A poll message -> (content, title) in the line protocol FireFly already shows."""
    kind, nick, body = m.get("kind"), str(m.get("nick", "")), str(m.get("body", ""))
    if kind == "dm":
        return f"[DM] <{nick}>: {body}", ""
    if kind == "action":
        return f"* {nick} {body}", ""
    if kind == "system":
        return body, ""
    return f"<{nick}> {body}", ""


class StumpWeb:
    """One Stump, reached over the local network."""

    OFF, GREETING, ONLINE, LOST, REFUSED = "off", "greeting", "online", "lost", "refused"

    def __init__(self, core, info):
        self.core = core
        self.lxmf = info["lxmf"]
        self.name = info["name"]
        self.base = (info.get("here") or (info.get("http") or [""])[0]).rstrip("/")
        self.state = self.OFF
        self.detail = ""
        self.nick = None
        self.room = None
        self.since = None          # None until the first poll sets the baseline
        self.fails = 0
        self.running = False
        self.lock = threading.Lock()

    # ------------------------------------------------------------------ lifecycle
    def start(self):
        self.running = True
        threading.Thread(target=self._run, daemon=True, name=f"firefly-web-{self.lxmf[:6]}").start()

    def stop(self):
        self.running = False
        self.state = self.OFF

    @property
    def online(self):
        return self.state == self.ONLINE

    def _run(self):
        delay = POLL_S
        while self.running:
            try:
                if self.state != self.ONLINE:
                    self._greet()
                self._poll()
                self.fails, delay = 0, POLL_S
            except WebError as e:
                if e.body.get("hello") == "required" or e.body.get("error") == "hello_required":
                    self.state = self.GREETING           # the Stump forgot us (restart, new address)
                    continue
                self._failed(f"the Stump answered {e.status}")
                delay = min(POLL_MAX_S, delay * 2)
            except Exception as e:
                self._failed(str(e) or e.__class__.__name__)
                delay = min(POLL_MAX_S, delay * 2)
            if self.state == self.REFUSED:
                delay = POLL_MAX_S
            time.sleep(delay * (1 + random.random() * 0.3))

    def _failed(self, why):
        self.fails += 1
        if self.state == self.REFUSED:
            return                         # keep the reason it was refused
        self.state = self.LOST if self.fails >= 2 else self.state
        self.detail = why

    # ------------------------------------------------------------------ the greeting
    def _greet(self):
        self.state = self.GREETING
        card = _http("GET", self.base + "/hello")
        if card.get("hello") == "off":
            self.state, self.detail = self.REFUSED, "this Stump doesn't greet apps (APP_HELLO off)"
            raise WebError(503, card)
        if card.get("lxmf") != self.lxmf or not verify_stump(card, self.lxmf):
            self.state, self.detail = self.REFUSED, "the Stump at this address couldn't prove who it is"
            raise WebError(0, {})
        line = stumpproto.auth_answer(self.core.identity, card["nonce"])     # "/auth <pub> <sig>"
        _, pub, sig = line.split(" ")
        name = stumpproto.clean_nick(self.core.settings["display_name"])
        body = json.dumps({"pub": pub, "sig": sig, "name": name,
                           "prefer": self.core.settings.get("stump_prefer", "wifi")}).encode()
        try:
            out = _http("POST", self.base + "/hello", body, ctype="application/json")
        except WebError as e:
            if e.status == 403:
                self.state, self.detail = self.REFUSED, "the Stump refused the greeting"
            raise
        self.nick = out.get("nick") or name
        self.state, self.detail = self.ONLINE, ""
        if out.get("error") == "name":
            self.detail = f"name taken here, you are {self.nick}"
        RNS.log(f"Stump {self.name} over Wi-Fi at {self.base}: greeted, you are {self.nick}")

    # ------------------------------------------------------------------ polling
    def _poll(self):
        ns = self.core.stump_state.setdefault(self.lxmf, stumpproto.NodeState())
        room = ns.room or ""
        q = f"/rrc/poll?room={urllib.request.quote(room)}&since={self.since or 0}"
        d = _http("GET", self.base + q)
        if d.get("hello") == "required":
            raise WebError(403, {"hello": "required"})
        if d.get("room"):
            ns.room = stumpproto.room_name(d["room"])
            self.room = ns.room
        if d.get("nick"):
            self.nick = d["nick"]
        if isinstance(d.get("rooms"), list):
            ns.set_rooms(d["rooms"])
        msgs = sorted((d.get("messages") or []) + (d.get("dms") or []), key=lambda m: m.get("id", 0))
        first = self.since is None
        top = self.since or 0
        for m in msgs:
            mid = int(m.get("id", 0))
            top = max(top, mid)
            if first and m.get("kind") != "dm":
                continue                      # the room's scrollback: not news
            if str(m.get("nick", "")) == self.nick:
                continue                      # our own line, already in the chat
            self._store(m)
        self.since = top

    def _store(self, m):
        key = f"web:{self.lxmf[:8]}:{m.get('id')}"
        if self.core.store.has_message(key):
            return
        content, title = to_lines(m)
        if m.get("kind") in ("msg", "action", "system") and self.room:
            title = "#" + self.room
        audio = {}
        v = m.get("voice")
        if isinstance(v, dict) and m.get("kind") == "dm":
            audio = self._fetch_voice(m.get("id"), v)
        self.core.store.upsert_peer(self.lxmf, "lxmf", heard=True)
        # Arrival time, not the Stump's clock: a Stump's clock may be unset or off
        # (a CAM has no battery clock), which put new lines among yesterday's.
        self.core.store.add_message(self.lxmf, False, content, "received", ts=time.time(),
                                    title=title, method="wifi", lxm_hash=key, verified=True, unread=True, **audio)

    def _fetch_voice(self, mid, v):
        try:
            mode = int(v.get("mode"))
            data = _http("GET", f"{self.base}/rrc/voice?id={mid}", raw=True)
            if not data or len(data) > VOICE_MAX:
                return {}
            return self.core._save_voice([mode, data], f"web-{self.lxmf[:8]}-{mid}")
        except Exception as e:
            RNS.log(f"voice note over Wi-Fi not fetched: {e}", RNS.LOG_WARNING)
            return {}

    # ------------------------------------------------------------------ sending
    def send(self, text):
        """POST /rrc/send. Returns (replies, room) or raises."""
        with self.lock:
            try:
                d = _http("POST", self.base + "/rrc/send", text.encode("utf-8"))
            except WebError as e:
                if e.body.get("error") == "hello_required" or e.body.get("hello") == "required":
                    self._greet()
                    d = _http("POST", self.base + "/rrc/send", text.encode("utf-8"))
                else:
                    raise
        replies = [str(r) for r in (d.get("replies") or [])]
        room = d.get("room")
        if room:
            ns = self.core.stump_state.setdefault(self.lxmf, stumpproto.NodeState())
            ns.room = stumpproto.room_name(room)
            self.room = ns.room
        if replies:
            self.core.stump_state.setdefault(self.lxmf, stumpproto.NodeState()).update(
                stumpproto.parse_message("\n".join(replies)))
            self.core.store.add_message(self.lxmf, False, "\n".join(replies), "received", method="wifi",
                                        lxm_hash=f"web:{self.lxmf[:8]}:r{time.time():.6f}", unread=False)
            if self.lxmf in self.core.auth:           # /auth over Wi-Fi: its challenge comes back here
                threading.Thread(target=self.core._feed_auth, args=(self.lxmf, "\n".join(replies)),
                                 daemon=True).start()
        return replies, room
