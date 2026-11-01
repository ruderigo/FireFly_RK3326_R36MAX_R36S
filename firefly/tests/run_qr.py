"""QR codes for addresses: the vendored encoder alone, and a decode with zbarimg when installed.
   python3 tests/run_qr.py"""
import os, shutil, subprocess, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from firefly import qr

ok = True
def check(cond, what):
    global ok
    print(("  PASS " if cond else "  FAIL ") + what)
    ok = ok and bool(cond)

addr = "53d91d2f0a1b2c3d4e5f60718293a4b5"
m = qr.matrix(addr)
check(21 <= len(m) <= 33 and all(len(r) == len(m) for r in m), f"a 32-hex address is a small square QR: {len(m)}x{len(m)}")
check(m[0][:7] == [True] * 7, "finder pattern in the corner")
import importlib.util
if importlib.util.find_spec("qrcode") is None or "vendor" in (importlib.util.find_spec("qrcode").origin or ""):
    check(qr._qrcode().__file__.startswith(qr._VENDOR), "no qrcode installed: the vendored copy is used")
else:
    print("  (a system qrcode is installed: it is used, the vendored copy is the fallback)")
if shutil.which("zbarimg"):
    try:
        import pygame
        px = 6
        n = len(m) + 8
        s = pygame.Surface((n * px, n * px)); s.fill((255, 255, 255))
        for r, row in enumerate(m):
            for c, dark in enumerate(row):
                if dark:
                    pygame.draw.rect(s, (0, 0, 0), ((c + 4) * px, (r + 4) * px, px, px))
        f = os.path.join(tempfile.mkdtemp(), "qr.png"); pygame.image.save(s, f)
        got = subprocess.run(["zbarimg", "-q", "--raw", f], capture_output=True, text=True).stdout.strip()
        check(got == addr, "zbarimg reads the address back")
    except Exception as e:
        check(False, f"decode check: {e}")
else:
    print("  (zbarimg not installed: decode check skipped)")
print("ALL PASSED" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
