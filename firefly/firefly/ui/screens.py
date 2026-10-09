"""The four tabs (CHATS, PEERS, NETWORK, SETUP) and the chat thread view."""
import os
import time

import pygame

from . import draw as D
from . import theme as T
from .widgets import Compose, Info, Menu, NumberEditor, Screen
from .. import stump
from ..rnsconfig import serial_ports
from ..settings import BANDWIDTHS, STUMP_RADIO

STATE_MARK = {
    "pending": ("…", T.MUTED), "stamping": ("⚙", T.MUTED), "sending": ("↑", T.MUTED),
    "sent": ("✓", T.MUTED), "delivered": ("✓✓", T.OK_GREEN), "stored": ("✓ node", T.ACTION),
    "failed": ("✗", T.ERROR),
}


def peer_label(p, h):
    if p and p.get("name"):
        return p["name"]
    return D.short_hash(h)


class ListScreen(Screen):
    """Scrollable list with a selection; subclasses provide rows()."""

    def __init__(self, app):
        super().__init__(app)
        self.sel = 0

    def rows(self):
        return []

    def move(self, action, n):
        if n == 0:
            self.sel = 0
        elif action == "up":
            self.sel = (self.sel - 1) % n
        elif action == "down":
            self.sel = (self.sel + 1) % n
        self.sel = min(self.sel, max(0, n - 1))

    def draw_list(self, surf, f, rows, top_y, render_row, row_h):
        W, H = surf.get_size()
        self.sel = min(self.sel, max(0, len(rows) - 1))
        visible = max(1, (H - top_y - f.line - 12) // row_h)
        start = max(0, min(self.sel - visible // 2, len(rows) - visible))
        y = top_y
        for i, row in enumerate(rows[start:start + visible], start=start):
            rect = pygame.Rect(8, y, W - 16, row_h - 4)
            D.box(surf, rect, T.ROW_HOVER if i == self.sel else T.SIDEBAR, 6,
                  T.EMBER if i == self.sel else None)
            render_row(surf, f, rect, row, i == self.sel)
            y += row_h
        if not rows:
            D.text(surf, f.mono, self.empty_text(), (W // 2, top_y + f.line * 2), T.MUTED, center=True)

    def empty_text(self):
        return "nothing here yet"


# ======================================================================== CHATS
class ChatsTab(ListScreen):
    title = "CHATS"
    hints = [("A", "open"), ("X", "new"), ("Y", "menu"), ("L/R", "tabs")]

    def rows(self):
        return self.app.core.store.conversations()

    def empty_text(self):
        return "No conversations. X to start one."

    def handle(self, action):
        rows = self.rows()
        self.sel = min(self.sel, max(0, len(rows) - 1))   # the list may have shrunk (deleted, blocked)
        if action in ("up", "down"):
            self.move(action, len(rows))
        elif action == "a" and rows:
            self.app.push(ChatScreen(self.app, rows[self.sel]["peer"]))
        elif action == "x":
            self.app.switch_tab(1)
        elif action == "y" and rows:
            peer = rows[self.sel]["peer"]
            self.app.push(Menu(self.app, "Conversation", [
                ("Open", lambda: self.app.push(ChatScreen(self.app, peer))),
                ("Mark read", lambda: self.app.core.store.mark_read(peer)),
            ] + PeerActions(self.app, peer).items()))

    def draw(self, surf, f):
        now = time.time()

        def row(s, f, rect, c, sel):
            name = c["name"] or D.short_hash(c["peer"])
            if c["stump"]:
                name += "  ⌂"
            D.text(s, f.mono, D.ellipsize(f.mono, name, rect.w - 120), (rect.x + 10, rect.y + 4),
                   T.EMBER_BRIGHT if sel else T.TEXT)
            D.text(s, f.mono_small, D.ago(c["ts"], now), (rect.right - 10, rect.y + 6), T.MUTED, right=True)
            prefix = "you: " if c["outgoing"] else ""
            preview = prefix + (c["content"].replace("\n", " ") or ("♪ voice note" if c.get("audio_mode") is not None
                                                                    else ""))
            D.text(s, f.mono_small, D.ellipsize(f.mono_small, preview, rect.w - 70),
                   (rect.x + 10, rect.y + 6 + f.line), T.MUTED)
            if c["unread"]:
                badge = pygame.Rect(rect.right - 44, rect.y + 6 + f.line, 34, f.line - 4)
                D.box(s, badge, T.EMBER, 8)
                D.text(s, f.mono_small, str(c["unread"]), badge.center[0:1] + (badge.y,), T.BG, center=True)

        self.draw_list(surf, f, self.rows(), self.app.content_top, row, f.line * 2 + 12)


# ======================================================================== chat thread
def _clock(secs):
    """The voice-note spec's label: '5.0 s', tenths rounded half up."""
    from .. import voice
    return voice.label(None if secs is None else int(round(secs * 1000)))


class ChatScreen(Screen):
    """A conversation. The D-pad selects a message (starting on the newest);
    A acts on it: play or stop a voice note, or show a message's details."""

    def __init__(self, app, peer):
        super().__init__(app)
        self.peer = peer
        self.sel_id = None        # selected message id; None = follow the newest
        self.offset = 0           # pixels the view is scrolled up from the bottom

    @property
    def title(self):
        return peer_label(self.app.core.store.peer(self.peer), self.peer)

    # ------------------------------------------------ selection
    def _messages(self):
        return self.app.core.store.messages(self.peer)

    def _selected(self, msgs):
        if not msgs:
            return None
        if self.sel_id is not None:
            for m in msgs:
                if m["id"] == self.sel_id:
                    return m
        return msgs[-1]

    def _move(self, msgs, delta):
        if not msgs:
            return
        cur = self._selected(msgs)
        i = next(i for i, m in enumerate(msgs) if m["id"] == cur["id"])
        j = max(0, min(len(msgs) - 1, i + delta))
        self.sel_id = None if j == len(msgs) - 1 else msgs[j]["id"]   # at the newest: follow new ones

    @property
    def hints(self):
        msgs = self._messages()
        m = self._selected(msgs)
        h = [("↑↓", "select")]
        if m is not None and m.get("audio_mode") is not None:
            playing = self.app.player.busy() and self.app.player.playing_id == m["id"]
            h.append(("A", "stop" if playing else "play"))
        elif m is not None:
            h.append(("A", "details"))
        h += [("START", "write"), ("X", "quick"), ("Y", "menu"), ("B", "back")]
        return h

    def play(self, m):
        from .. import voice
        if self.app.player.busy() and self.app.player.playing_id == m["id"]:
            self.app.player.stop()
            return
        if not voice.row_playable(m):
            self.app.toast(f"Can't play this {voice.describe(m['audio_mode'])} voice note")
            return
        if not m["audio_path"] or not os.path.isfile(m["audio_path"]):
            self.app.toast("This voice note's file is missing")
            return
        self.app.player.play(m["id"], m["audio_path"], m["audio_mode"], m.get("audio_secs"))

    def handle(self, action):
        core = self.app.core
        msgs = self._messages()
        if action == "up":
            self._move(msgs, -1)
        elif action == "down":
            self._move(msgs, +1)
        elif action == "l1":
            self._move(msgs, -5)
        elif action == "r1":
            self.sel_id = None
        elif action == "a":
            m = self._selected(msgs)
            if m is None:
                self.app.push(Compose(self.app, "To " + self.title, lambda t: self._send(t)))
            elif m.get("audio_mode") is not None:
                self.play(m)
            else:
                self.app.push(Info(self.app, "Message", _message_details(core, m)))
        elif action == "start":
            self.app.push(Compose(self.app, "To " + self.title, lambda t: self._send(t)))
        elif action == "x":
            items = [(q, (lambda q=q: self._send(q))) for q in core.settings["quick_replies"]]
            self.app.push(Menu(self.app, "Quick reply", items))
        elif action == "y":
            items = PeerActions(self.app, self.peer).items(in_chat=True)
            m = self._selected(msgs)
            if m is not None:
                items = [("Details of the selected message", lambda m=m: self.app.push(
                    Info(self.app, "Message", _message_details(core, m)))),
                         ("Delete the selected message", lambda m=m: self._delete_message(m))] + items
            if core.store.voice_notes(self.peer, 1):     # before the destructive ones, which stay last
                i = next((k for k, (l, _) in enumerate(items) if l.startswith("Delete conversation")), len(items))
                items.insert(i, ("Copy voice notes to the SD card", lambda: self.app.copy_voice_to_sd()))
            self.app.push(Menu(self.app, self.title, items))
        elif action == "b":
            self.app.pop()

    def _send(self, text):
        self.app.core.send(self.peer, text)
        self.sel_id = None

    def _delete_message(self, m):
        preview = (m["content"] or ("voice note " + _clock(m["audio_secs"]) if m.get("audio_mode") is not None
                                    else "message")).replace("\n", " ")

        def go():
            msgs = self._messages()
            i = next((k for k, x in enumerate(msgs) if x["id"] == m["id"]), None)
            if self.app.player.playing_id == m["id"]:
                self.app.player.stop()
            self.app.core.delete_message(m["id"])
            # keep the selection on the neighbour (older one if there is one)
            rest = self._messages()
            if not rest or i is None or i >= len(rest):
                self.sel_id = None
            else:
                self.sel_id = rest[max(0, i - 1)]["id"]
            self.app.toast("Message deleted")
        self.app.confirm("Delete this message?", D.ellipsize(self.app.fonts.mono_small, preview, 380),
                         "Delete", go)

    # ------------------------------------------------ drawing
    def draw(self, surf, f):
        core = self.app.core
        core.store.mark_read(self.peer)
        W, H = surf.get_size()
        p = core.store.peer(self.peer)
        top = self.app.content_top
        hops = core.hops(self.peer)
        info = [f"{hops} hop{'s' if hops != 1 else ''}" if hops is not None else "no path yet"]
        if core.is_stump(self.peer):
            info.append("Stump node " + (p or {}).get("stump", ""))
            ns = core.stump_state.get(self.peer)
            if ns and ns.room:
                info.append("in #" + ns.room)
            a = core.auth_state(self.peer)
            if a:
                info.append({a.OK: "verified ✓", a.FAILED: "verify failed"}.get(a.state, "verifying…"))
        top += f.line + 4

        msgs = self._messages()
        if not msgs:
            D.text(surf, f.mono, "Say hello: press START to write, X for quick replies.", (W // 2, H // 2),
                   T.MUTED, center=True)
        else:
            sel = self._selected(msgs)
            maxw = W * 3 // 4
            blocks = [(m, *self._layout(m, f, maxw, core.is_stump(self.peer))) for m in msgs]
            # Virtual column, newest at the bottom: y measured upward from the bottom edge.
            bottom = H - f.line - 16
            view_h = bottom - top
            below = 0
            spans = []
            for m, h, painter in reversed(blocks):
                spans.append((m, h, painter, below))      # this block occupies [below, below + h)
                below += h
            total = below
            for m, h, painter, b in spans:                 # keep the selection fully in view
                if m["id"] == sel["id"]:
                    if b < self.offset:
                        self.offset = b
                    elif b + h > self.offset + view_h:
                        self.offset = b + h - view_h
            self.offset = max(0, min(self.offset, max(0, total - view_h)))
            surf.set_clip(pygame.Rect(0, top, W, view_h))     # bubbles stay inside the conversation area
            for m, h, painter, b in spans:
                y = bottom - (b - self.offset) - h
                if y + h < top:
                    break
                if y < bottom:
                    painter(surf, y, m["id"] == sel["id"])
            surf.set_clip(None)
        # Header strip drawn last, over any bubble that slid under it
        pygame.draw.rect(surf, T.BG, (0, 0, W, top - 2))
        self.app.draw_header(surf, f)
        D.text(surf, f.mono_small, " · ".join(info) + "   " + D.short_hash(self.peer),
               (14, self.app.content_top), T.MUTED)
        if msgs and self.offset > 0:
            D.text(surf, f.mono_small, "▼ newer below (R1)", (W - 12, self.app.content_top), T.EMBER, right=True)

    def _layout(self, m, f, maxw, is_stump):
        """Returns (height, painter) for one message bubble."""
        W = self.app.screen_w
        out = m["outgoing"]
        lines = []   # (font, text, color)
        if is_stump and not out:
            if m["title"] and m["title"].startswith("#"):
                lines.append((f.mono_small, m["title"], T.EMBER))     # the room this batch belongs to
            for parsed in stump.parse_message(m["content"], m["title"] or ""):
                lines += [(f.body, ln, c) for ln, c in _stump_render(parsed, f, maxw - 20)]
        elif m["content"]:
            lines = [(f.body, ln, T.TEXT) for ln in D.wrap(f.body, m["content"], maxw - 20)]
        if m.get("audio_mode") is not None:
            from .. import voice
            if self.app.player.playing_id == m["id"] and self.app.player.busy():
                lines.append((f.mono, f"■ playing  {_clock(m['audio_secs'])}  (A to stop)", T.EMBER_BRIGHT))
            elif voice.row_playable(m):
                lines.append((f.mono, f"▶ voice note  {_clock(m['audio_secs'])}  · {voice.describe(m['audio_mode'])}",
                              T.EMBER))
            else:
                lines.append((f.mono_small, f"♪ voice note ({voice.describe(m['audio_mode'])}): "
                                            "can't play this format yet", T.MUTED))
        if m["attachments"]:
            lines.append((f.mono_small, f"[{m['attachments']} — not shown on this device]", T.MUTED))
        if not m["verified"] and not out:
            lines.append((f.mono_small, "⚠ sender signature not verified", T.ERROR))
        meta = time.strftime("%H:%M", time.localtime(m["ts"]))
        if out:
            mark, mcol = STATE_MARK.get(m["state"], (m["state"], T.MUTED))
            if m["state"] == "failed" and m["reason"]:
                mark += " " + m["reason"]
            elif m["reason"] and m["state"] == "pending":
                mark += " " + m["reason"]
        else:
            mark, mcol = "", T.MUTED
            if m["rssi"] is not None:
                meta += f"  {m['rssi']:.0f} dBm"
            if m["snr"] is not None:
                meta += f"  SNR {m['snr']:.1f}"
        lh = f.body.get_linesize()
        body_h = sum(fn.get_linesize() for fn, _, _ in lines)
        h = body_h + f.mono_small.get_linesize() + 18
        widths = [fn.size(t)[0] for fn, t, _ in lines] + [f.mono_small.size(meta + "  " + mark)[0]]
        bw = min(maxw, max(widths) + 22)

        def paint(surf, y, selected=False):
            x = W - bw - 10 if out else 10
            rect = pygame.Rect(x, y + 2, bw, h - 8)
            D.box(surf, rect, T.PANEL if out else T.SIDEBAR, 8, T.EMBER if out else T.BORDER)
            if selected:
                pygame.draw.rect(surf, T.EMBER_BRIGHT, rect.inflate(4, 4), width=3, border_radius=10)
            yy = rect.y + 6
            for fn, t, c in lines:
                D.text(surf, fn, t, (rect.x + 11, yy), c)
                yy += fn.get_linesize()
            D.text(surf, f.mono_small, meta, (rect.x + 11, yy), T.DIM)
            if mark:
                D.text(surf, f.mono_small, mark, (rect.right - 10, yy), mcol, right=True)
        _ = lh
        return h, paint


def _message_details(core, m):
    """What there is to know about one message, for the details panel."""
    from .. import voice
    out = ["Sent" if m["outgoing"] else "Received",
           time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(m["ts"])), ""]
    if m["outgoing"]:
        out.append(f"Status: {m['state']}" + (f" ({m['method']})" if m["method"] else ""))
        if m["reason"]:
            out.append(f"Reason: {m['reason']}")
    else:
        out.append("Signature verified" if m["verified"] else "Signature NOT verified")
        if m["rssi"] is not None or m["snr"] is not None:
            out.append("Signal: " + "  ".join(x for x in (
                f"{m['rssi']:.0f} dBm" if m["rssi"] is not None else "",
                f"SNR {m['snr']:.1f} dB" if m["snr"] is not None else "") if x))
        if m["method"]:
            out.append(f"Delivered: {m['method']}")
    if m.get("audio_mode") is not None:
        out += ["", f"Voice note: {voice.describe(m['audio_mode'])}, {_clock(m['audio_secs'])}"]
        if m["audio_path"] and os.path.isfile(m["audio_path"]):
            out.append(f"{os.path.getsize(m['audio_path'])} bytes")
    if m["title"]:
        out.append(f"Title: {m['title']}")
    if m["attachments"]:
        out.append(f"Also attached: {m['attachments']}")
    if m["content"]:
        out += ["", m["content"]]
    if m["lxm_hash"]:
        out += ["", "Message ID:", m["lxm_hash"]]
    return out


def _stump_render(p, f, width):
    """Colour Stump lines by meaning (DMs purple, activity dim)."""
    k = p["kind"]
    if k == "dm" and p.get("voice"):
        return [(ln, T.DM_BODY) for ln in D.wrap(f.body, f"[DM] {p['author']}: ♪ voice note", width)]
    if k == "dm":
        return [(ln, T.DM_BODY) for ln in D.wrap(f.body, f"[DM] {p['author']}: {p['text']}", width)]
    if k == "too_fast":
        return [(ln, T.ERROR) for ln in D.wrap(f.body, "⧗ too many voice notes too fast", width)]
    if k in ("join", "part", "rename", "topic", "moved", "names", "room", "no_such_nick"):
        return [(ln, T.DIM) for ln in D.wrap(f.body, _stump_text(p), width)]
    if k == "action":
        return [(ln, T.ACTION) for ln in D.wrap(f.body, f"* {p['nick']} {p['text']}", width)]
    if k == "refused":
        hint = "  (Y → verify my identity)" if p["tier"] == "minted" else ""
        return ([(ln, T.ERROR) for ln in D.wrap(f.body, f"⊘ #{p['room']} is {p['tier']}{hint}", width)] +
                [(ln, T.DIM) for ln in D.wrap(f.body, p["text"], width)])
    if k in ("already_in", "unknown_command"):
        head = f"= already in #{p['room']}" if k == "already_in" else f"? unknown command {p['command']}"
        return [(ln, T.DIM) for ln in D.wrap(f.body, head, width)]
    if k in ("auth_challenge", "auth_ok", "auth_fail"):
        return [(ln, T.ERROR if k == "auth_fail" else T.DIM)
                for ln in D.wrap(f.body, k.upper().replace("_", "-") + " " + p["arg"], width)]
    if k == "msg":
        return [(ln, T.TEXT) for ln in D.wrap(f.body, f"<{p['nick']}> {p['text']}", width)]
    return [(ln, T.TEXT) for ln in D.wrap(f.body, p.get("text", ""), width)]


def _stump_text(p):
    k = p["kind"]
    return {"join": lambda: f"✓ {p['nick']} joined", "part": lambda: f"✗ {p['nick']} left",
            "rename": lambda: f"✎ {p['old']} is now {p['new']}", "topic": lambda: f"✎ #{p['room']}: {p['topic']}",
            "moved": lambda: f"→ you are in #{p['room']}", "no_such_nick": lambda: f"⊖ no one called {p['nick']}",
            "names": lambda: f"#{p['room']}: {', '.join(p['names'])}",
            "room": lambda: f"#{p['room']} ·{p['count']} {'[' + p['tier'] + '] ' if p['tier'] != 'open' else ''}"
                            f"{p['topic']}"}[k]()


class PeerActions:
    def __init__(self, app, peer):
        self.app, self.peer = app, peer

    def items(self, in_chat=False):
        core, peer = self.app.core, self.peer
        p = core.store.peer(peer) or {}
        items = []
        if not in_chat:
            items.append(("Open chat", lambda: self.app.push(ChatScreen(self.app, peer))))
        items.append(("Unsave contact" if p.get("saved") else "Save contact",
                      lambda: core.store.set_saved(peer, not p.get("saved"))))
        items.append(("Find path (ask the network)", lambda: (core.request_path(peer),
                                                              self.app.toast("Path request sent"))))
        if not core.is_stump(peer):   # Stump chat must go directly
            items.append(("Send via propagation node", lambda: self.app.push(
                Compose(self.app, "Via node to " + peer_label(p, peer), lambda t: core.send(peer, t, "propagated")))))
        if core.is_stump(peer):
            items.append(("Stump: verify my identity (/auth)", lambda: self._auth()))
            items.append(("Stump: list rooms (/rooms)", lambda: core.send(peer, "/rooms", "opportunistic")))
            items.append(("Stump: join a room…", lambda: self.app.push(Compose(
                self.app, "Join a room on " + peer_label(p, peer), lambda t: core.send(peer, t, "opportunistic"),
                initial="/join #", send_label="JOIN"))))
            items.append(("Stump: leave this room (/part)", lambda: core.send(peer, "/part", "opportunistic")))
            items.append(("Stump: who is here (/names)", lambda: core.send(peer, "/names", "opportunistic")))
        items.append(("Show address", lambda: self.app.push(Info(self.app, peer_label(p, peer), [
            "LXMF address:", D.spaced_hash(peer), "",
            f"Hops: {core.hops(peer) if core.hops(peer) is not None else 'unknown'}",
            f"Last heard: {D.ago(p.get('last_heard'), time.time())} ago" if p.get("last_heard") else "Never heard",
            f"Stump node: {p.get('stump')} ({p.get('stump_ver')})" if p.get("stump") else "",
        ]))))
        items.append(("Delete conversation and contact", lambda: self._delete()))
        items.append(("Block", lambda: self._block()))
        return items

    def _delete(self):
        core, peer = self.app.core, self.peer
        name = peer_label(core.store.peer(peer) or {}, peer)
        n = len(core.store.messages(peer, 100000))

        def go():
            if self.app.player.playing_id is not None:
                self.app.player.stop()
            core.delete_conversation(peer)
            self.app.close_peer(peer)
            self.app.toast(f"Deleted {name}")
        self.app.confirm(f"Delete {name}?", f"{n} message(s) and the contact. They come back if they write. "
                         "Copies on the SD card stay.", "Delete", go)

    def _block(self):
        core, peer = self.app.core, self.peer
        name = peer_label(core.store.peer(peer) or {}, peer)

        def go():
            if self.app.player.playing_id is not None:
                self.app.player.stop()
            core.block(peer)
            self.app.close_peer(peer)
            self.app.toast(f"Blocked {name}. Undo in SETUP > Blocked.")
        self.app.confirm(f"Block {name}?", "Deletes the conversation and ignores their messages and announces. "
                         "They aren't told.", "Block", go)

    def _auth(self):
        if self.app.core.start_stump_auth(self.peer):
            self.app.toast("Verifying identity (one LoRa round trip)…")
        else:
            self.app.toast("Already verifying, please wait")


# ======================================================================== PEERS
class PeersTab(ListScreen):
    title = "PEERS"
    hints = [("A", "chat"), ("X", "save"), ("Y", "menu"), ("L/R", "tabs")]

    def rows(self):
        return [{"add": True}] + self.app.core.store.peers("lxmf")

    def handle(self, action):
        rows = self.rows()
        self.sel = min(self.sel, max(0, len(rows) - 1))   # the list may have shrunk (deleted, blocked)
        if action in ("up", "down"):
            self.move(action, len(rows))
            return
        row = rows[self.sel]
        if row.get("add"):
            if action == "a":
                self.app.push(Compose(self.app, "LXMF address (32 hex)", self._add, mode="hex", max_len=32))
            return
        if action == "a":
            self.app.push(ChatScreen(self.app, row["hash"]))
        elif action == "x":
            self.app.core.store.set_saved(row["hash"], not row["saved"])
        elif action == "y":
            self.app.push(Menu(self.app, peer_label(row, row["hash"]), PeerActions(self.app, row["hash"]).items()))

    def _add(self, text):
        try:
            h = self.app.core.add_contact(text)
            self.app.toast("Added. Asking the network for a path…")
            self.app.push(ChatScreen(self.app, h))
        except ValueError as e:
            self.app.toast(str(e))

    def draw(self, surf, f):
        now = time.time()

        def row(s, f, rect, p, sel):
            if p.get("add"):
                D.text(s, f.mono, "+ Add contact by address", (rect.x + 10, rect.y + 4 + f.line // 2),
                       T.EMBER_BRIGHT if sel else T.EMBER)
                return
            name = peer_label(p, p["hash"])
            tags = ("★ " if p["saved"] else "") + ("⌂ STUMP " if p["stump"] else "")
            D.text(s, f.mono, D.ellipsize(f.mono, tags + name, rect.w - 150), (rect.x + 10, rect.y + 4),
                   T.EMBER_BRIGHT if sel else T.TEXT)
            hops = self.app.core.hops(p["hash"])
            if hops is not None:
                right = f"{hops} hop{'s' if hops != 1 else ''}"
            elif p["hops"] is not None:
                right = f"was {p['hops']} hop{'s' if p['hops'] != 1 else ''}"
            else:
                right = "no path"
            D.text(s, f.mono_small, right, (rect.right - 10, rect.y + 6), T.MUTED, right=True)
            D.text(s, f.mono_small, f"{D.short_hash(p['hash'])}  heard {D.ago(p['last_heard'], now)}",
                   (rect.x + 10, rect.y + 6 + f.line), T.MUTED)

        self.draw_list(surf, f, self.rows(), self.app.content_top, row, f.line * 2 + 12)


# ======================================================================== NETWORK
class NetworkTab(Screen):
    title = "NETWORK"
    hints = [("A", "announce"), ("X", "sync"), ("Y", "more"), ("↑↓", "scroll"), ("L/R", "tabs")]

    def __init__(self, app):
        super().__init__(app)
        self.top = 0
        self._stats, self._stats_at = {}, 0

    def handle(self, action):
        core = self.app.core
        if action == "a":
            core.announce()
            self.app.toast("Announced")
        elif action == "x":
            self.app.toast("Syncing from propagation node" if core.sync() else "No propagation node known yet")
        elif action == "y":
            self.app.push(Menu(self.app, "Network", [
                ("Search for RNodes now", lambda: (core.radio and core.radio.search_now(),
                                                   self.app.toast("Searching for RNodes…"))),
                ("Nomad Network nodes heard", lambda: self.app.push(Info(self.app, "Nomad nodes", [
                    f"{p['name'] or '?'}  {D.short_hash(p['hash'])}" for p in core.store.peers("nomadnode")]
                    or ["None heard yet."]))),
                ("Propagation nodes heard", lambda: self.app.push(Info(self.app, "Propagation nodes", [
                    f"{p['name'] or '?'}  {D.short_hash(p['hash'])}  {p['extra']}  hops {p['hops']}"
                    for p in core.store.peers("propagation")] or ["None heard yet."]))),
                ("Show Reticulum log (last 40 lines)", lambda: self.app.push(Info(
                    self.app, "Reticulum log", _log_tail(core.paths.rns_config_dir + "/logfile", 40)))),
                ("Where are my files?", lambda: self.app.push(Info(self.app, "Files", [
                    "Data folder: " + core.paths.home, "Identity key: " + core.paths.identity,
                    "Reticulum config: " + core.paths.rns_config_dir + "/config",
                    "Back up the identity key: it IS your address."]))),
            ]))
        elif action == "up":
            self.top = max(0, self.top - 1)
        elif action == "down":
            self.top += 1

    def lines(self):
        core = self.app.core
        now = time.time()
        if now - self._stats_at > 2:
            self._stats, self._stats_at = core.interface_stats(), now
        out = [("h", "YOUR ADDRESS"), ("big", D.spaced_hash(core.address)),
               ("m", f"name: {core.settings['display_name']}   announced {D.ago(core.last_announce, now)} ago"),
               ("", ""), ("h", "INTERFACES")]
        if core.shared_instance:
            out.append(("m", "Using a shared Reticulum instance (rnsd): its config decides the interfaces."))
        if core.status_note:
            out.append(("err", core.status_note))
        for i in self._stats.get("interfaces", []):
            up = i.get("status")
            if not up and "RNode" in i.get("name", "") and core.shared_instance:
                out.append(("err", "LoRa radio not responding."))
                reason = _last_rnode_error(core.paths.rns_config_dir + "/logfile")
                if reason:
                    out.append(("m", "Reticulum says: " + reason))
            name = i.get("short_name") or i.get("name", "?")
            out.append(("ok" if up else "err", f"{'●' if up else '○'} {name}"))
            det = f"   rx {_bytes(i.get('rxb', 0))}  tx {_bytes(i.get('txb', 0))}"
            if i.get("clients") is not None:
                det += f"  peers {i['clients']}"
            out.append(("m", det))
            radio = []
            for key, label, fmt in (("rssi", "RSSI", "{:.0f} dBm"), ("snr", "SNR", "{:.1f} dB"),
                                    ("noise_floor", "noise", "{:.0f} dBm"),
                                    ("airtime_short", "airtime", "{:.1f}%"), ("channel_load_short", "load", "{:.1f}%"),
                                    ("battery_percent", "radio batt", "{:.0f}%")):
                v = i.get(key)
                if key == "battery_percent" and not v:
                    continue          # boards without a battery report 0
                if isinstance(v, (int, float)):
                    radio.append(f"{label} {fmt.format(v)}")
            if radio:
                out.append(("m", "   " + "  ".join(radio)))
        if not self._stats.get("interfaces"):
            out.append(("m", "No interface statistics available."))
        out += [("", ""), ("h", "PROPAGATION (store & forward)")]
        pn = core.propagation_node()
        if pn:
            p = core.store.peer(pn) or {}
            out.append(("m", f"node: {p.get('name') or D.short_hash(pn)}  {D.short_hash(pn)}"))
            out.append(("m", f"sync: {core.sync_state}, last {D.ago(core.last_sync, now)} ago"))
        else:
            out.append(("m", "No propagation node yet. Messages to offline peers can't be stored."))
        ves = core.voice_export_status
        if ves:
            folder, copied, err = ves
            out += [("", ""), ("h", "VOICE NOTES ON THE SD CARD"), ("m", folder)]
            if err:
                out.append(("err", err))
        out += [("", ""), ("h", "LORA RADIO")]
        rs = core.radio.status if core.radio else None
        if rs:
            label = {"online": "● online", "connecting": "… connecting", "searching": "○ searching",
                     "no devices": "○ no radio plugged in", "refused": "✗ RNode refused",
                     "off": "○ switched off", "shared": "managed by rnsd"}.get(rs.state, rs.state)
            where = f" on {rs.port}" if rs.port else ""
            kind = "ok" if rs.state == "online" else ("err" if rs.state == "refused" else "m")
            out.append((kind, label + where + (f"  ({rs.board})" if rs.board else "")))
            if rs.detail:
                out.append(("m", rs.detail))
        out.append(("m", _radio_summary(core.settings["radio"])))
        return out

    def draw(self, surf, f):
        W, H = surf.get_size()
        y = self.app.content_top
        lines = self.lines()
        visible = (H - y - f.line - 12) // f.line
        self.top = min(self.top, max(0, len(lines) - visible))
        colors = {"h": T.EMBER, "m": T.MUTED, "ok": T.OK_GREEN, "err": T.ERROR, "big": T.TEXT, "": T.TEXT}
        wrapped = []
        for kind, s in lines:
            font = f.mono_big if kind == "big" else (f.mono_small if kind == "m" else f.mono)
            for part in (D.wrap(font, s, W - 28) if kind in ("m", "err", "ok") else [D.ellipsize(font, s, W - 28)]):
                wrapped.append((kind, font, part))
        self.top = min(self.top, max(0, len(wrapped) - visible))
        for kind, font, s in wrapped[self.top:self.top + visible]:
            D.text(surf, font, s, (14, y), colors[kind])
            y += font.get_linesize() + 2


def _last_rnode_error(path):
    """The most recent RNode-related error or warning in the Reticulum log."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()[-400:]
    except OSError:
        return None
    for line in reversed(lines):
        if ("RNode" in line or "serial" in line.lower()) and ("[Error]" in line or "[Warning]" in line):
            return line.split("]", 2)[-1].strip()[:200]
    return None


def _log_tail(path, n):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return [l.rstrip() for l in fh.readlines()[-n:]] or ["(empty)"]
    except OSError:
        return ["No log file (using a shared instance or system config?)"]


def _bytes(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _radio_summary(r):
    state = "on" if r["enabled"] else "off"
    return (f"LoRa {state}: {r['frequency'] / 1e6:.3f} MHz  BW {r['bandwidth'] / 1000:g} kHz  "
            f"SF{r['spreading_factor']}  CR 4/{r['coding_rate']}  {r['tx_power']} dBm")


# ======================================================================== SETUP
class SettingsTab(ListScreen):
    title = "SETUP"
    hints = [("A", "edit"), ("←→", "change"), ("L/R", "tabs")]

    def __init__(self, app):
        super().__init__(app)
        self.dirty_network = False

    def rows(self):
        s = self.app.core.settings
        r = s["radio"]
        pn = self.app.core.propagation_node()
        return [
            ("head", "YOU", None),
            ("name", "Display name", s["display_name"]),
            ("interval", "Announce every", f"{s['announce_interval_min']} min" if s["announce_interval_min"] else "off"),
            ("head", "LORA RADIO (applies live; must match the other nodes)", None),
            ("radio_on", "Radio", "on" if r["enabled"] else "off"),
            ("port", "Which RNode", "any (auto)" if r["port"] == "auto" else r["port"]),
            ("rhosts", "Wi-Fi RNodes", f"{len(s.get('rnode_hosts', []))} configured"),
            ("preset", "Load Stump defaults", "915/125k/SF8"),
            ("freq", "Frequency", f"{r['frequency'] / 1e6:.3f} MHz"),
            ("bw", "Bandwidth", f"{r['bandwidth'] / 1000:g} kHz"),
            ("sf", "Spreading factor", f"SF{r['spreading_factor']}"),
            ("cr", "Coding rate", f"4/{r['coding_rate']}"),
            ("txp", "TX power", f"{r['tx_power']} dBm"),
            ("head", "OTHER LINKS", None),
            ("auto", "Wi-Fi/LAN discovery", "on" if s["auto_interface"] else "off"),
            ("tcp", "Internet/TCP peers", f"{len(s['tcp_peers'])} configured"),
            ("transport", "Relay for others (transport)", "on" if s["transport"] else "off"),
            ("head", "OFFLINE DELIVERY", None),
            ("pmode", "Propagation node", s["propagation_mode"] + (f" ({pn[:8]})" if pn else "")),
            ("fallback", "If peer unreachable, use node", "yes" if s["fallback_to_propagation"] else "no"),
            ("sync", "Fetch messages every",
             f"{s['sync_interval_min']} min" if s["sync_interval_min"] else "manual"),
            ("head", "PRIVACY", None),
            ("blocked", "Blocked", f"{len(self.app.core.store.blocked())}"),
            ("head", "VOICE NOTES", None),
            ("voicesd", "Copy to SD card (as WAV)", "on" if s.get("voice_to_sd", True) else "off"),
            ("voicesdnow", "Copy all now", ""),
            ("head", "SCREEN", None),
            ("rotation", "Screen rotation", _rot_label(s.get("screen_rotation", "auto"), self.app.display.rotation)),
            ("head", "", None),
            ("apply", "Apply link changes (restarts FireFly)" + (" ●" if self.dirty_network else ""), ""),
            ("quit", "Quit FireFly", ""),
        ]

    def handle(self, action):
        rows = self.rows()
        if action in ("up", "down"):
            n = len(rows)
            for _ in range(n):
                self.move(action, n)
                if rows[self.sel][0] != "head":
                    break
            return
        key = rows[self.sel][0]
        if action in ("left", "right"):
            self._cycle(key, -1 if action == "left" else 1)
        elif action == "a":
            self._edit(key)

    # --- helpers
    def _radio(self):
        """Radio settings apply live: the radio manager retunes after a short pause."""
        self.app.core.settings.validate()
        self.app.core.settings.save()
        if self.app.core.radio:
            self.app.core.radio.request_apply()

    def _net(self):
        self.dirty_network = True
        self.app.core.settings.validate()
        self.app.core.settings.save()

    def _cycle(self, key, d):
        s = self.app.core.settings
        r = s["radio"]
        if key == "interval":
            opts = [0, 15, 30, 45, 55]
            s["announce_interval_min"] = _step(opts, s["announce_interval_min"], d)
            s.save()
        elif key == "sync":
            opts = [0, 15, 30, 60, 120, 360]
            s["sync_interval_min"] = _step(opts, s["sync_interval_min"], d)
            s.save()
        elif key == "bw":
            r["bandwidth"] = _step(BANDWIDTHS, r["bandwidth"], d); self._radio()
        elif key == "sf":
            r["spreading_factor"] = max(5, min(12, r["spreading_factor"] + d)); self._radio()
        elif key == "cr":
            r["coding_rate"] = max(5, min(8, r["coding_rate"] + d)); self._radio()
        elif key == "txp":
            r["tx_power"] = max(0, min(22, r["tx_power"] + d)); self._radio()
        elif key == "freq":
            r["frequency"] += d * 25_000; self._radio()
        elif key in ("radio_on", "auto", "transport", "fallback", "voicesd"):
            self._edit(key)
        elif key == "port":
            opts = ["auto"] + serial_ports()
            r["port"] = _step(opts, r["port"] if r["port"] in opts else "auto", d); self._radio()
        elif key == "pmode":
            s["propagation_mode"] = _step(["auto", "manual", "off"], s["propagation_mode"], d); self._net()
        elif key == "rotation":
            self.app.set_rotation(_step(["auto", 0, 90, 180, 270], s.get("screen_rotation", "auto"), d))

    def _edit(self, key):
        app, core = self.app, self.app.core
        s = core.settings
        r = s["radio"]
        if key == "name":
            app.push(Compose(app, "Display name", self._set_name, initial=s["display_name"], send_label="OK",
                             max_len=40, show_packet_meter=False))
        elif key == "radio_on":
            r["enabled"] = not r["enabled"]; self._radio()
        elif key == "auto":
            s["auto_interface"] = not s["auto_interface"]; self._net()
        elif key == "transport":
            s["transport"] = not s["transport"]; self._net()
        elif key == "fallback":
            s["fallback_to_propagation"] = not s["fallback_to_propagation"]; s.save()
        elif key == "voicesd":
            s["voice_to_sd"] = not s.get("voice_to_sd", True); s.save()
        elif key == "voicesdnow":
            app.copy_voice_to_sd()
        elif key == "blocked":
            rows = core.store.blocked()
            if not rows:
                app.toast("Nobody is blocked")
                return
            items = [(f"Unblock {b['name'] or D.short_hash(b['hash'])}  ({time.strftime('%Y-%m-%d', time.localtime(b['ts']))})",
                      (lambda h=b["hash"], n=b["name"]: (core.unblock(h), app.toast(f"Unblocked {n or 'address'}"))))
                     for b in rows]
            app.push(Menu(app, "Blocked", items, subtitle="Their messages and announces are ignored until unblocked"))
        elif key == "preset":
            r.update(STUMP_RADIO); self._radio()
            app.toast("Stump network defaults loaded")
        elif key == "freq":
            app.push(NumberEditor(app, "Frequency", r["frequency"], 25_000, 1_000_000, 137_000_000, 1_020_000_000,
                                  lambda v: f"{v / 1e6:.3f} MHz", self._set_freq,
                                  note="Use only frequencies licence-free where you are."))
        elif key == "port":
            app.push(Menu(app, "Which RNode", [("Any RNode found (auto)", lambda: self._set_port("auto"))] +
                          [(p, (lambda p=p: self._set_port(p))) for p in serial_ports()],
                          subtitle="Auto uses the first RNode that answers, USB or Wi-Fi"))
        elif key == "rhosts":
            items = [("+ Add a Wi-Fi RNode (IP or hostname)", lambda: app.push(Compose(
                app, "Wi-Fi RNode address", self._add_rhost, send_label="OK", max_len=80, show_packet_meter=False)))]
            items += [(f"Remove {h}", (lambda h=h: self._remove_rhost(h))) for h in s.get("rnode_hosts", [])]
            app.push(Menu(app, "Wi-Fi RNodes", items, subtitle="RNodes in Wi-Fi mode, reached on TCP port 7633"))
        elif key == "tcp":
            items = [("+ Add host:port", lambda: app.push(Compose(app, "host:port", self._add_tcp, send_label="OK",
                                                                  max_len=80, show_packet_meter=False)))]
            items += [(f"Remove {t}", (lambda t=t: self._remove_tcp(t))) for t in s["tcp_peers"]]
            app.push(Menu(app, "TCP peers", items))
        elif key == "pmode":
            nodes = core.store.peers("propagation")
            items = [("Auto (nearest heard)", lambda: self._set_pn("auto", None)),
                     ("Off", lambda: self._set_pn("off", None))]
            items += [(f"{p['name'] or '?'} ({p['hash'][:8]}, {p['hops']} hops)",
                       (lambda h=p["hash"]: self._set_pn("manual", h))) for p in nodes]
            app.push(Menu(app, "Propagation node", items))
        elif key == "apply":
            app.restart()
        elif key == "quit":
            app.quit()
        elif key in ("interval", "sync", "bw", "sf", "cr", "txp", "rotation"):
            self._cycle(key, 1)

    def _set_name(self, name):
        self.app.core.set_display_name(name)
        nick = stump.clean_nick(name)
        self.app.toast("Announced as " + name + ("" if nick == name[:16] else f"  (Stump nick: {nick})"))

    def _set_freq(self, v):
        self.app.core.settings["radio"]["frequency"] = v
        self._radio()

    def _set_port(self, p):
        self.app.core.settings["radio"]["port"] = p
        self._radio()

    def _add_rhost(self, t):
        host = t.strip().replace("tcp://", "").split("/")[0]
        if not host:
            return
        self.app.core.settings.data.setdefault("rnode_hosts", []).append(host)
        self._radio()

    def _remove_rhost(self, h):
        self.app.core.settings["rnode_hosts"].remove(h)
        self._radio()

    def _add_tcp(self, t):
        host, _, port = t.strip().rpartition(":")
        if not host or not port.isdigit():
            self.app.toast("Use host:port, e.g. rns.example.org:4242")
            return
        self.app.core.settings["tcp_peers"].append(t.strip())
        self._net()

    def _remove_tcp(self, t):
        self.app.core.settings["tcp_peers"].remove(t)
        self._net()

    def _set_pn(self, mode, h):
        s = self.app.core.settings
        s["propagation_mode"] = mode
        s["propagation_node"] = h
        s.save()
        if h:
            self.app.core.router.set_outbound_propagation_node(bytes.fromhex(h))
        elif mode == "auto":
            self.app.core._auto_pick_propagation()

    def draw(self, surf, f):
        W, _ = surf.get_size()

        def row(s, f, rect, r, sel):
            key, label, value = r
            if key == "head":
                D.text(s, f.mono_small, label, (rect.x + 4, rect.y + 6), T.EMBER)
                return
            D.text(s, f.mono, label, (rect.x + 10, rect.y + 3), T.EMBER_BRIGHT if sel else T.TEXT)
            if value:
                D.text(s, f.mono, D.ellipsize(f.mono, str(value), rect.w // 2 - 10), (rect.right - 10, rect.y + 3),
                       T.MUTED, right=True)

        rows = self.rows()
        orig = self.draw_list

        def draw_list(surf, f, rows, top_y, render_row, row_h):
            # headings are drawn flat (no box)
            H = surf.get_height()
            visible = max(1, (H - top_y - f.line - 12) // row_h)
            start = max(0, min(self.sel - visible // 2, len(rows) - visible))
            y = top_y
            for i, rr in enumerate(rows[start:start + visible], start=start):
                rect = pygame.Rect(8, y, W - 16, row_h - 4)
                if rr[0] != "head":
                    D.box(surf, rect, T.ROW_HOVER if i == self.sel else T.SIDEBAR, 6,
                          T.EMBER if i == self.sel else None)
                render_row(surf, f, rect, rr, i == self.sel)
                y += row_h
        _ = orig
        if rows[self.sel][0] == "head":
            self.sel += 1
        draw_list(surf, f, rows, self.app.content_top, row, f.line + 8)


def _rot_label(setting, actual):
    return f"auto ({actual}°)" if setting == "auto" else f"{setting}°"


def _step(opts, cur, d):
    i = opts.index(cur) if cur in opts else 0
    return opts[(i + d) % len(opts)]
