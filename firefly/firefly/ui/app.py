"""pygame front end. One loop, redraws only when something changed."""
import os
import sys
import time

import pygame

from . import draw as D
from . import theme as T
from .screens import ChatsTab, NetworkTab, PeersTab, SettingsTab

REPEAT_DELAY, REPEAT_RATE = 0.30, 0.07

CONTROLLER_MAP = {
    "CONTROLLER_BUTTON_DPAD_UP": "up", "CONTROLLER_BUTTON_DPAD_DOWN": "down",
    "CONTROLLER_BUTTON_DPAD_LEFT": "left", "CONTROLLER_BUTTON_DPAD_RIGHT": "right",
    "CONTROLLER_BUTTON_A": "a", "CONTROLLER_BUTTON_B": "b",
    "CONTROLLER_BUTTON_X": "x", "CONTROLLER_BUTTON_Y": "y",
    "CONTROLLER_BUTTON_LEFTSHOULDER": "l1", "CONTROLLER_BUTTON_RIGHTSHOULDER": "r1",
    "CONTROLLER_BUTTON_START": "start", "CONTROLLER_BUTTON_BACK": "select",
}
# Desktop keys (only used when no text box is open).
KEY_MAP = {
    pygame.K_UP: "up", pygame.K_DOWN: "down", pygame.K_LEFT: "left", pygame.K_RIGHT: "right",
    pygame.K_z: "a", pygame.K_RETURN: "a", pygame.K_x: "b", pygame.K_ESCAPE: "b", pygame.K_BACKSPACE: "b",
    pygame.K_s: "x", pygame.K_a: "y", pygame.K_q: "l1", pygame.K_w: "r1",
    pygame.K_SPACE: "start", pygame.K_TAB: "select",
}


class App:
    def __init__(self, core, fullscreen=False, size=(720, 720), display=None, rotate_override=None):
        self.core = core
        os.environ.setdefault("SDL_VIDEO_CENTERED", "1")
        # Only the subsystems we need: no audio device is opened.
        pygame.display.init()
        pygame.font.init()
        pygame.display.set_caption("FireFly")
        from .display import Display
        self.display = display or Display(fullscreen, size, rotate_override or core.settings["screen_rotation"],
                                          log=lambda *a: None)
        self.rotate_override = rotate_override
        self.surf = self.display.surf
        pygame.mouse.set_visible(False)
        pygame.key.start_text_input()
        self.fonts = T.Fonts(self.surf.get_height())
        self.tabs = [ChatsTab(self), PeersTab(self), NetworkTab(self), SettingsTab(self)]
        self.tab = 0
        self.stack = []
        self.running = True
        self.toast_text, self.toast_until = "", 0
        self.held = {}
        self.select_held = False
        self.controllers = []
        self._init_controllers()
        self.joy_map = {int(k): v for k, v in core.settings["joystick_map"].items()}
        from ..voice import Player
        self.player = Player(log=core.log)
        self.last_version = -1
        self.next_refresh = 0

    # ------------------------------------------------ geometry
    @property
    def screen_w(self): return self.surf.get_width()

    @property
    def content_top(self):
        # Tabs start right under the header; pushed screens get a title line.
        return self.fonts.line * (2 if self.stack else 1) + (18 if self.stack else 20)

    # ------------------------------------------------ navigation
    @property
    def current(self): return self.stack[-1] if self.stack else self.tabs[self.tab]

    def push(self, screen): self.stack.append(screen)

    def pop(self):
        if self.stack:
            self.stack.pop()

    def switch_tab(self, i):
        self.stack.clear()
        self.tab = i % len(self.tabs)

    def toast(self, text, secs=2.5):
        self.toast_text, self.toast_until = text, time.time() + secs

    def quit(self): self.running = False

    def copy_voice_to_sd(self):
        import threading

        def job():
            copied, folder, errors = self.core.export_voice_notes()
            if errors:
                self.toast(f"Copy failed: {errors[-1]}", 5)
            else:
                where = folder.replace("/roms2/", "SD card (2nd) /").replace("/roms/", "SD card /")
                self.toast(f"{copied} new voice note(s) copied to {where}", 5)
        self.toast("Copying voice notes to the SD card…")
        threading.Thread(target=job, daemon=True).start()

    def confirm(self, title, detail, action_label, on_yes):
        """A yes/no question with Cancel first (the default), so a quick double
        press of A can never delete or block anything."""
        from .widgets import Menu
        self.push(Menu(self, title, [("Cancel", lambda: None), (action_label, on_yes)], subtitle=detail))

    def close_peer(self, peer):
        """Leave any open chat with this peer (after deleting or blocking it)."""
        from .screens import ChatScreen
        self.stack = [sc for sc in self.stack if not (isinstance(sc, ChatScreen) and sc.peer == peer)]

    def set_rotation(self, value):
        """Apply a rotation setting (auto/0/90/180/270) live and remember it."""
        self.display.set_rotation(value)
        self.core.settings["screen_rotation"] = value
        self.core.settings.save()
        self.surf = self.display.surf
        self.fonts = T.Fonts(self.surf.get_height())

    def cycle_rotation(self):
        """Select + R1: rotate the picture 90° clockwise."""
        from .display import ROTATIONS
        nxt = ROTATIONS[(ROTATIONS.index(self.display.rotation) + 1) % len(ROTATIONS)]
        self.set_rotation(nxt)
        self.toast(f"Screen rotation {nxt}°  (Select+R1 again to change)")

    def restart(self):
        self.core.stop()
        pygame.quit()
        os.execv(sys.executable, [sys.executable, "-m", "firefly"] + sys.argv[1:])

    # ------------------------------------------------ input
    def _init_controllers(self):
        try:
            from pygame._sdl2 import controller
            controller.init()
            self._ctl_mod = controller
            for i in range(controller.get_count()):
                if controller.is_controller(i):
                    self.controllers.append(controller.Controller(i))
        except Exception:
            self._ctl_mod = None
        pygame.joystick.init()
        self.joysticks = [pygame.joystick.Joystick(i) for i in range(pygame.joystick.get_count())]
        self.ctl_map = {getattr(pygame, k): v for k, v in CONTROLLER_MAP.items() if hasattr(pygame, k)}

    def _is_mapped_controller(self, instance_id):
        return any(getattr(c, "id", None) == instance_id for c in self.controllers) or bool(self.controllers)

    def action(self, a):
        self._activity = True
        if a == "select":
            self.select_held = True
        if self.select_held and a == "start":
            self.running = False
            return
        if self.select_held and a == "r1":
            self.cycle_rotation()
            return
        if a in ("l1", "r1") and not self.stack:
            self.switch_tab(self.tab + (1 if a == "r1" else -1))
            return
        self.current.handle(a)

    def _press(self, a):
        if a is None:
            return
        self.held[a] = time.time() + REPEAT_DELAY
        self.action(a)

    def _release(self, a):
        self.held.pop(a, None)
        if a == "select":
            self.select_held = False

    def events(self):
        typing = hasattr(self.current, "key")
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                self.running = False
            elif e.type == pygame.VIDEORESIZE:
                self.fonts = T.Fonts(e.h)
            elif e.type == getattr(pygame, "CONTROLLERDEVICEADDED", -1) and self._ctl_mod:
                try:
                    self.controllers.append(self._ctl_mod.Controller(e.device_index))
                except Exception:
                    pass
            elif e.type == getattr(pygame, "CONTROLLERBUTTONDOWN", -1):
                self._press(self.ctl_map.get(e.button))
            elif e.type == getattr(pygame, "CONTROLLERBUTTONUP", -1):
                self._release(self.ctl_map.get(e.button))
            elif e.type == pygame.JOYBUTTONDOWN and not self.controllers:
                a = self.joy_map.get(e.button)
                if a is None:
                    print(f"Unmapped joystick button {e.button} (add it to joystick_map in settings.json)")
                self._press(a)
            elif e.type == pygame.JOYBUTTONUP and not self.controllers:
                self._release(self.joy_map.get(e.button))
            elif e.type == pygame.JOYHATMOTION and not self.controllers:
                x, y = e.value
                for a in ("up", "down", "left", "right"):
                    self._release(a)
                self._press({(0, 1): "up", (0, -1): "down", (-1, 0): "left", (1, 0): "right"}.get((x, y)))
            elif e.type == pygame.TEXTINPUT and typing:
                self._activity = True
                self.current.text_input(e.text)
            elif e.type == pygame.KEYDOWN:
                if typing and e.key in (pygame.K_BACKSPACE, pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_ESCAPE):
                    self._activity = True
                    self.current.key(e.key)
                elif typing and e.unicode and e.unicode.isprintable() and e.key not in (
                        pygame.K_UP, pygame.K_DOWN, pygame.K_LEFT, pygame.K_RIGHT):
                    pass  # comes through TEXTINPUT
                else:
                    self._press(KEY_MAP.get(e.key))
            elif e.type == pygame.KEYUP:
                self._release(KEY_MAP.get(e.key))
        # Auto-repeat for held directions
        now = time.time()
        for a in ("up", "down", "left", "right"):
            t = self.held.get(a)
            if t and now >= t:
                self.held[a] = now + REPEAT_RATE
                self.action(a)

    # ------------------------------------------------ drawing
    def draw_header(self, surf, f):
        W = surf.get_width()
        pygame.draw.rect(surf, T.SIDEBAR, (0, 0, W, f.line + 12))
        D.text(surf, f.mono_big, "FireFly", (12, 4), T.EMBER)
        x = 12 + f.mono_big.size("FireFly  ")[0]
        unread = self.core.store.unread_total()
        for i, tab in enumerate(self.tabs):
            label = tab.title + (f" {unread}" if i == 0 and unread else "")
            active = i == self.tab and not self.stack
            w = f.mono.size(label)[0] + 16
            if i == self.tab:
                D.box(surf, pygame.Rect(x, 4, w, f.line + 4), T.EMBER if active else T.PANEL, 4)
            D.text(surf, f.mono, label, (x + 8, 6), T.BG if active else (T.TEXT if i == self.tab else T.MUTED))
            x += w + 4
        title = self.current.title if self.stack else ""
        if title:
            D.text(surf, f.mono, D.ellipsize(f.mono, "› " + title, W - 24), (12, f.line + 16), T.TEXT)
        # link indicator, refreshed every 3 s
        if time.time() > getattr(self, "_link_checked", 0) + 3:
            self._link_checked = time.time()
            self._link_up = any(i.get("status") and "Shared Instance" not in i.get("name", "")
                                for i in self.core.interface_stats().get("interfaces", []))
        up = self._link_up
        D.text(surf, f.mono_small, "● link" if up else "○ no link", (W - 10, 8), T.OK_GREEN if up else T.ERROR,
               right=True)

    def draw_hints(self, surf, f):
        W, H = surf.get_size()
        y = H - f.line - 8
        pygame.draw.rect(surf, T.SIDEBAR, (0, y - 4, W, f.line + 12))
        x = 10
        for btn, label in self.current.hints:
            w = f.mono_small.size(btn)[0] + 10
            D.box(surf, pygame.Rect(x, y, w, f.line - 2), T.BORDER, 4)
            D.text(surf, f.mono_small, btn, (x + 5, y + 1), T.TEXT)
            x += w + 4
            x += D.text(surf, f.mono_small, label, (x, y + 1), T.MUTED) + 12
            if x > W - 40:
                break

    def render(self):
        f, s = self.fonts, self.surf
        s.fill(T.BG)
        cur = self.current
        from .widgets import Compose
        if isinstance(cur, Compose):
            cur.draw(s, f)
        else:
            # Draw the base (tab or chat) and then overlays on top of it
            base_i = max((i for i, sc in enumerate(self.stack) if not _is_overlay(sc)), default=-1)
            base = self.stack[base_i] if base_i >= 0 else self.tabs[self.tab]
            self.draw_header(s, f)
            base.draw(s, f)
            for sc in self.stack[base_i + 1:]:
                shade = pygame.Surface(s.get_size(), pygame.SRCALPHA)
                shade.fill((0, 0, 0, 140))
                s.blit(shade, (0, 0))
                sc.draw(s, f)
        self.draw_hints(s, f)
        if time.time() < self.toast_until:
            w = f.mono.size(self.toast_text)[0] + 24
            r = pygame.Rect((s.get_width() - w) // 2, s.get_height() // 2 - f.line, w, f.line + 14)
            D.box(s, r, T.PANEL, 8, T.EMBER)
            D.text(s, f.mono, self.toast_text, (r.x + 12, r.y + 7))
        if f.missing:
            D.text(s, f.mono_small, "fonts-dejavu-core missing: symbols may not show", (10, s.get_height() - 2 * f.line - 10), T.ERROR)
        self.display.present()

    # ------------------------------------------------ loop
    def run(self):
        clock = pygame.time.Clock()
        while self.running:
            self._activity = False
            self.events()
            self.player.pump()
            if self.player.error:
                self.toast(self.player.error, 6)
                self.player.error = None
            now = time.time()
            if (self._activity or self.core.store.version != self.last_version or now >= self.next_refresh
                    or now < self.toast_until + 0.1):
                self.last_version = self.core.store.version
                self.next_refresh = now + 1.0
                self.render()
            clock.tick(30)
        self.player.stop()
        pygame.quit()


def _is_overlay(sc):
    from .widgets import Info, Menu, NumberEditor
    return isinstance(sc, (Menu, NumberEditor, Info))
