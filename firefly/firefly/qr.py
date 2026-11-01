"""QR codes for LXMF addresses, drawn by FireFly itself.

Uses the system's `qrcode` if installed, else the copy in firefly/vendor
(qrcode 8.2, BSD licence, pure Python), so it works offline with no new
package on the handheld.
"""
import os
import sys

_VENDOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor")


def _qrcode():
    try:
        import qrcode
        return qrcode
    except ImportError:
        if _VENDOR not in sys.path:
            sys.path.append(_VENDOR)
        import qrcode
        return qrcode


def matrix(text):
    """List of rows of booleans (True = dark), no quiet zone."""
    qrcode = _qrcode()
    q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=0)
    q.add_data(text)
    q.make(fit=True)
    return q.get_matrix()
