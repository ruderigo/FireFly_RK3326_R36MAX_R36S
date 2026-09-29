"""Reusable overlay screens: menus, the on-screen keyboard, number editor, info panel.

Every screen implements:
    handle(action)          action in up/down/left/right/a/b/x/y/l1/r1/start/select
    text_input(s)           optional: typed text from a physical keyboard
    draw(surf, fonts)
    hints                   list of (button, label) shown in the bottom bar
"""
import pygame

from . import draw as D
from . import theme as T
from ..core import single_packet_size
from ..stump import SINGLE_PACKET_LIMIT


class Screen:
    hints = []
    title = ""

    def __init__(self, app):
        self.app = app

    def handle(self, action):
        if action == "b":
            self.app.pop()

    def text_input(self, s):
        pass

    def draw(self, surf, f):
        pass


# ======================================================================== menu
class Menu(Screen):
    """A vertical list of (label, callback) items. Callback may be None for a heading."""
    hints = [("A", "select"), ("B", "back")]

    def __init__(self, app, title, items, subtitle=None):
        super().__init__(app)
        self.title = title
        self.subtitle = subtitle
        self.items = items
        self.sel = next((i for i, it in enumerate(items) if it[1]), 0)

    def handle(self, action):
        n = len(self.items)
        if action in ("up", "down") and n:
            step = -1 if action == "up" else 1
            for _ in range(n):
                self.sel = (self.sel + step) % n
                if self.items[self.sel][1]:
                    break
        elif action == "a" and self.items and self.items[self.sel][1]:
            cb = self.items[self.sel][1]
            self.app.pop()
            cb()
        elif action == "b":
            self.app.pop()

    def draw(self, surf, f):
        W, H = surf.get_size()
        w = min(W - 40, f.base * 26)
        rows = len(self.items) + (2 if self.subtitle else 1)
        h = min(H - 40, (rows + 1) * f.line + 20)
        r = pygame.Rect((W - w) // 2, (H - h) // 2, w, h)
        D.box(surf, r, T.PANEL, 8, T.BORDER)
        y = r.y + 10
        D.text(surf, f.mono_big, self.title, (r.x + 14, y), T.EMBER)
        y += f.line + 6
        if self.subtitle:
            D.text(surf, f.mono_small, D.ellipsize(f.mono_small, self.subtitle, w - 28), (r.x + 14, y), T.MUTED)
            y += f.line
        visible = max(1, (r.bottom - y - 8) // f.line)
        top = max(0, min(self.sel - visible // 2, len(self.items) - visible))
        for i, (label, cb) in enumerate(self.items[top:top + visible], start=top):
            if i == self.sel:
                D.box(surf, pygame.Rect(r.x + 6, y - 2, w - 12, f.line + 2), T.ROW_HOVER, 4)
            color = T.EMBER_BRIGHT if i == self.sel else (T.TEXT if cb else T.DIM)
            D.text(surf, f.mono, D.ellipsize(f.mono, label, w - 36), (r.x + 16, y), color)
            y += f.line


# ======================================================================== keyboard
PAGES = {
    "abc": ["1234567890", "qwertyuiop", "asdfghjkl'", "zxcvbnm,.?"],
    "sym": ["!@#$%&*()-", "_=+/\\:;\"<>", "[]{}~`|^€£", "°±×÷…«»¿¡·"],
    "àé": ["àâäçéèêëîï", "ôöùûüÿœæñß", "ÀÂÇÉÈÊÎÔÙÛ", "✓✗→←↑↓♥☺★—"],
    "hex": ["0123456789", "abcdef"],
}
SPECIALS = ["⇧", "PAGE", "SPACE", "⌫", "SEND"]


class Compose(Screen):
    """On-screen keyboard. Works with the D-pad, and with any USB keyboard at the same time."""

    def __init__(self, app, title, on_done, initial="", mode="text", send_label="SEND", max_len=2000,
                 show_packet_meter=True):
        super().__init__(app)
        self.title = title
        self.on_done = on_done
        self.buf = initial
        self.mode = mode
        self.pages = ["hex"] if mode == "hex" else ["abc", "sym", "àé"]
        self.page = 0
        self.shift = False
        self.row, self.col = 1 if mode == "text" else 0, 0
        self.send_label = send_label
        self.max_len = max_len
        self.meter = show_packet_meter and mode == "text"

    @property
    def hints(self):
        if self.mode == "hex":
            return [("A", "key"), ("B", "del"), ("START", "ok"), ("SELECT", "cancel")]
        return [("A", "key"), ("B", "del"), ("X", "space"), ("Y", "shift"), ("L/R", "page"),
                ("START", self.send_label.lower()), ("SEL", "cancel")]

    def _rows(self):
        rows = [list(r) for r in PAGES[self.pages[self.page]]]
        rows.append(["⌫", "OK"] if self.mode == "hex" else SPECIALS[:4] + [self.send_label])
        return rows

    def _type(self, s):
        if len(self.buf) + len(s) <= self.max_len:
            self.buf += s

    def _press(self, key):
        if key == "⌫":
            self.buf = self.buf[:-1]
        elif key == "SPACE":
            self._type(" ")
        elif key == "⇧":
            self.shift = not self.shift
        elif key == "PAGE":
            self.page = (self.page + 1) % len(self.pages)
        elif key in ("SEND", "OK", self.send_label):
            self._finish()
        else:
            self._type(key.upper() if self.shift else key)
            self.shift = False

    def _finish(self):
        text = self.buf.strip()
        self.app.pop()
        if text:
            self.on_done(text)

    def handle(self, action):
        rows = self._rows()
        if action == "up":
            self.row = (self.row - 1) % len(rows)
        elif action == "down":
            self.row = (self.row + 1) % len(rows)
        elif action == "left":
            self.col -= 1
        elif action == "right":
            self.col += 1
        elif action == "a":
            r = rows[self.row]
            self._press(r[self.col % len(r)])
        elif action == "b":
            self.buf = self.buf[:-1]
        elif action == "x" and self.mode == "text":
            self._type(" ")
        elif action == "y" and self.mode == "text":
            self.shift = not self.shift
        elif action in ("l1", "r1") and len(self.pages) > 1:
            self.page = (self.page + (1 if action == "r1" else -1)) % len(self.pages)
        elif action == "start":
            self._finish()
        elif action == "select":
            self.app.pop()
        r = self._rows()[self.row]
        self.col %= len(r)

    def text_input(self, s):
        self._type(s)

    def key(self, k):
        """Physical keyboard editing keys."""
        if k == pygame.K_BACKSPACE:
            self.buf = self.buf[:-1]
        elif k in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._finish()
        elif k == pygame.K_ESCAPE:
            self.app.pop()

    def draw(self, surf, f):
        W, H = surf.get_size()
        surf.fill(T.BG)
        D.text(surf, f.mono_big, self.title, (14, 8), T.EMBER)
        # Text area
        area = pygame.Rect(10, 14 + f.line, W - 20, H * 2 // 5 - f.line)
        D.box(surf, area, T.PANEL, 8, T.BORDER)
        lines = D.wrap(f.body, self.buf + "▏", area.w - 20)
        maxl = max(1, (area.h - 12) // f.body.get_linesize())
        y = area.y + 6
        for ln in lines[-maxl:]:
            D.text(surf, f.body, ln, (area.x + 10, y))
            y += f.body.get_linesize()
        if self.meter:
            size = single_packet_size(self.buf)
            one = size <= SINGLE_PACKET_LIMIT
            label = f"{size}/{SINGLE_PACKET_LIMIT} B · {'1 LoRa packet' if one else 'too big for 1 packet: uses a link'}"
            D.text(surf, f.mono_small, label, (area.right - 8, area.bottom + 4), T.MUTED if one else T.EMBER, right=True)
        # Keys
        rows = self._rows()
        kb_top = area.bottom + f.line + 8
        kb_h = H - kb_top - f.line - 16
        rh = kb_h // len(rows)
        for ri, row in enumerate(rows):
            kw = (W - 20) / len(row)
            for ci, key in enumerate(row):
                label = key.upper() if (self.shift and len(key) == 1) else key
                rect = pygame.Rect(int(10 + ci * kw) + 2, kb_top + ri * rh + 2, int(kw) - 4, rh - 4)
                sel = ri == self.row and ci == self.col
                D.box(surf, rect, T.EMBER if sel else T.PANEL, 6, None if sel else T.BORDER)
                font = f.mono if len(label) == 1 else f.mono_small
                img = font.render(label, True, T.BG if sel else T.TEXT)
                surf.blit(img, (rect.centerx - img.get_width() // 2, rect.centery - img.get_height() // 2))
        page = self.pages[self.page].upper()
        D.text(surf, f.mono_small, f"{page}{'  ⇧' if self.shift else ''}", (14, area.bottom + 4), T.MUTED)


# ======================================================================== number editor
class NumberEditor(Screen):
    hints = [("←→", "step"), ("L/R", "big step"), ("A", "ok"), ("B", "cancel")]

    def __init__(self, app, title, value, step, big_step, lo, hi, fmt, on_done, note=None):
        super().__init__(app)
        self.title, self.value, self.step, self.big = title, value, step, big_step
        self.lo, self.hi, self.fmt, self.on_done, self.note = lo, hi, fmt, on_done, note

    def handle(self, action):
        d = {"left": -self.step, "right": self.step, "down": -self.step, "up": self.step,
             "l1": -self.big, "r1": self.big}.get(action)
        if d is not None:
            self.value = max(self.lo, min(self.hi, self.value + d))
        elif action == "a":
            self.app.pop()
            self.on_done(self.value)
        elif action == "b":
            self.app.pop()

    def draw(self, surf, f):
        W, H = surf.get_size()
        r = pygame.Rect(W // 8, H // 3, W * 3 // 4, f.line * 5)
        D.box(surf, r, T.PANEL, 8, T.BORDER)
        D.text(surf, f.mono, self.title, (r.x + 14, r.y + 10), T.MUTED)
        D.text(surf, f.mono_big, "◀  " + self.fmt(self.value) + "  ▶", (r.centerx, r.y + 14 + f.line), T.EMBER,
               center=True)
        if self.note:
            D.text(surf, f.mono_small, self.note, (r.centerx, r.bottom - f.line - 4), T.MUTED, center=True)


# ======================================================================== info
class Info(Screen):
    hints = [("↑↓", "scroll"), ("B", "back")]

    def __init__(self, app, title, lines):
        super().__init__(app)
        self.title = title
        self.lines = lines
        self.top = 0

    def handle(self, action):
        if action == "up":
            self.top = max(0, self.top - 1)
        elif action == "down":
            self.top += 1
        elif action in ("b", "a"):
            self.app.pop()

    def draw(self, surf, f):
        W, H = surf.get_size()
        r = pygame.Rect(16, 16, W - 32, H - 32 - f.line)
        D.box(surf, r, T.PANEL, 8, T.BORDER)
        D.text(surf, f.mono_big, self.title, (r.x + 14, r.y + 10), T.EMBER)
        wrapped = []
        for ln in self.lines:
            wrapped += D.wrap(f.mono, ln, r.w - 28) or [""]
        visible = (r.h - f.line * 2) // f.line
        self.top = min(self.top, max(0, len(wrapped) - visible))
        y = r.y + 16 + f.line
        for ln in wrapped[self.top:self.top + visible]:
            D.text(surf, f.mono, ln, (r.x + 14, y))
            y += f.line
