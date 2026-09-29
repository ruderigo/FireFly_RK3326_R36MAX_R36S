"""Colours and fonts. Palette: the Stump ecosystem's default 'Amber' theme,
so FireFly feels at home next to Stump nodes (and it reads well on a small
LCD). Fonts: DejaVu (Debian package fonts-dejavu-core), which covers the
symbols Stump uses (✓ ✗ ✎ → ⊖) and accented text."""
import os
import pygame

BG = (0x1b, 0x15, 0x12)
PANEL = (0x2a, 0x21, 0x19)
SIDEBAR = (0x22, 0x1b, 0x15)
ROW_HOVER = (0x2f, 0x27, 0x1e)
BORDER = (0x49, 0x3c, 0x2e)
EMBER = (0xd9, 0x7a, 0x3a)
EMBER_BRIGHT = (0xf0, 0xa0, 0x50)
TEXT = (0xec, 0xdf, 0xc8)
MUTED = (0x9c, 0x8d, 0x76)
DIM = (0x7d, 0x71, 0x5f)
ACTION = (0xc8, 0xb4, 0x8f)
DM_BODY = (0xc8, 0xa2, 0xc8)
DM_NICK = (0xd8, 0xb4, 0xd8)
ERROR = (0xe0, 0x7a, 0x5a)     # the only red: it always means "something went wrong"
OK_GREEN = (0x9c, 0xb8, 0x76)  # delivered / link up, kept muted to stay in the family

FONT_DIRS = ["/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu", "/usr/share/fonts/TTF",
             os.path.join(os.path.dirname(__file__), "fonts")]


def _find(name):
    for d in FONT_DIRS:
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
    return None


class Fonts:
    def __init__(self, screen_h):
        base = max(13, screen_h // 30)
        self.base = base
        # Body text uses DejaVu Sans: DejaVu Serif lacks some of the symbols Stump sends (✓).
        mono, body = _find("DejaVuSansMono.ttf"), _find("DejaVuSans.ttf")
        self.missing = mono is None
        self.mono = pygame.font.Font(mono, base)
        self.mono_small = pygame.font.Font(mono, max(11, base * 4 // 5))
        self.mono_big = pygame.font.Font(_find("DejaVuSansMono-Bold.ttf") or mono, base * 5 // 4)
        self.body = pygame.font.Font(body or mono, base)
        self.line = self.mono.get_linesize()
