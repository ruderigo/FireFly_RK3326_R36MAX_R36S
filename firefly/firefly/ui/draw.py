"""Small drawing helpers."""
import pygame
from . import theme as T


def text(surf, font, s, pos, color=T.TEXT, right=False, center=False):
    img = font.render(s, True, color)
    x, y = pos
    if right:
        x -= img.get_width()
    if center:
        x -= img.get_width() // 2
    surf.blit(img, (x, y))
    return img.get_width()


def box(surf, rect, color, radius=6, border=None):
    pygame.draw.rect(surf, color, rect, border_radius=radius)
    if border:
        pygame.draw.rect(surf, border, rect, width=1, border_radius=radius)


def wrap(font, s, width):
    """Word-wrap to pixel width; hard-breaks words longer than a line."""
    out = []
    for para in s.split("\n"):
        line = ""
        for word in para.split(" "):
            cand = word if not line else line + " " + word
            if font.size(cand)[0] <= width:
                line = cand
                continue
            if line:
                out.append(line)
            while font.size(word)[0] > width and len(word) > 1:
                cut = len(word)
                while cut > 1 and font.size(word[:cut])[0] > width:
                    cut -= 1
                out.append(word[:cut])
                word = word[cut:]
            line = word
        out.append(line)
    return out


def ellipsize(font, s, width):
    if font.size(s)[0] <= width:
        return s
    while s and font.size(s + "…")[0] > width:
        s = s[:-1]
    return s + "…"


def ago(ts, now):
    if not ts:
        return "never"
    d = max(0, now - ts)
    if d < 60:
        return "now"
    if d < 3600:
        return f"{int(d // 60)}m"
    if d < 86400:
        return f"{int(d // 3600)}h"
    return f"{int(d // 86400)}d"


def short_hash(h):
    return f"<{h[:8]}…{h[-4:]}>" if h else "?"


def spaced_hash(h):
    return " ".join(h[i:i + 8] for i in range(0, len(h), 8))
