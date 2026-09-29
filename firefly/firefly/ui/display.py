"""The physical screen, with optional rotation.

Many RK3326 handhelds use a portrait LCD panel mounted sideways (480x854,
480x800, 320x480, 720x1280...). If the firmware's SDL already rotates, the
display reports a landscape size and nothing happens here. If it reports
portrait, FireFly draws on a landscape surface and rotates it on the way
out. Rotation is a setting: auto | 0 | 90 | 180 | 270 (clockwise), and
Select + R1 cycles it live, so a sideways or upside-down screen can be fixed
without being able to read it.
"""
import pygame

ROTATIONS = (0, 90, 180, 270)


class Display:
    def __init__(self, fullscreen, window_size, rotation="auto", log=print):
        info = pygame.display.Info()
        log(f"display reports {info.current_w}x{info.current_h}")
        flags = pygame.FULLSCREEN if fullscreen else 0
        try:
            self.screen = pygame.display.set_mode((0, 0) if fullscreen else window_size, flags)
        except pygame.error as e:
            log(f"set_mode failed ({e}); retrying with {info.current_w}x{info.current_h}")
            self.screen = pygame.display.set_mode((info.current_w or window_size[0],
                                                   info.current_h or window_size[1]), flags)
        self.log = log
        self.set_rotation(rotation)

    @staticmethod
    def resolve(rotation, w, h):
        if rotation == "auto":
            return 90 if h > w else 0      # portrait panel: turn it into landscape
        try:
            r = int(rotation)
        except (TypeError, ValueError):
            return 0
        return r if r in ROTATIONS else 0

    def set_rotation(self, rotation):
        self.setting = rotation
        pw, ph = self.screen.get_size()
        self.rotation = self.resolve(rotation, pw, ph)
        if self.rotation == 0:
            self.surf = self.screen
        elif self.rotation == 180:
            self.surf = pygame.Surface((pw, ph)).convert()
        else:
            self.surf = pygame.Surface((ph, pw)).convert()
        self.log(f"screen {pw}x{ph}, rotation {self.rotation} (setting {rotation}), drawing at "
                 f"{self.surf.get_width()}x{self.surf.get_height()}")

    def present(self):
        if self.rotation:
            # pygame rotates counter-clockwise; our setting is clockwise.
            self.screen.blit(pygame.transform.rotate(self.surf, -self.rotation), (0, 0))
        pygame.display.flip()
