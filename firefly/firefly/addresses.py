"""LXMF addresses as other apps write them, read and written.

Every LXMF app's "address" is the same 16-byte hash (32 hex characters) of
an identity's `lxmf.delivery` destination, but apps share it differently:

  bare `<32 hex>`                        Sideband, NomadNet, Skywave (no key: wait for an announce)
  `lxma://<address>:<public key>`        Columba, MeshChatX, the T-Deck LXMF Messenger;
                                         Stump's second QR code (1.0.0-beta.53)
  `lxmf://<address>?key=<key>`           FireFly; with `stump=<name>`, a Stump's own code
                                         (Stump 1.0.0-beta.52)

A link that carries the public key lets FireFly write to the contact at
once, before any announce, once the key is checked against the address
(anyone can print a QR code). Same rules as FireFly for Android
(firefly/stump.py: parse_address_link, identity_for) and the Stump's
CLIENT_QUICKSTART ("/address").
"""
import base64
import re
from urllib.parse import parse_qs, quote, unquote

import RNS

_ADDRESS_TEXT = re.compile(r"^(?:[a-z][a-z0-9+.-]*://)?<?([0-9a-f]{32})>?(?:[:/?#].*)?$")


def key_bytes(k):
    """A 64-byte Reticulum public key written as hex (128) or base64url (86, padding optional)."""
    k = (k or "").strip()
    try:
        if len(k) == 128 and all(c in "0123456789abcdefABCDEF" for c in k):
            return bytes.fromhex(k)
        key = base64.urlsafe_b64decode(k + "=" * (-len(k) % 4))
        return key if len(key) == 64 else None
    except Exception:
        return None


def parse(text):
    """-> None (not an address), or {"address", "scheme", "stump" (name or None), "key" (64 bytes
    or None), "key_bad" (a key was there but isn't one), "release" (a Stump's `r=`, Stump
    1.0.0-beta.79: a hint only, the signed beacon has the last word; or None)}."""
    raw = "".join(str(text or "").split())
    m = _ADDRESS_TEXT.match(raw.lower())
    if not m:
        return None
    addr = m.group(1)
    out = {"address": addr, "scheme": raw.split("://", 1)[0].lower() if "://" in raw else None,
           "stump": None, "key": None, "key_bad": False, "release": None}
    rest = raw.split("://", 1)[1] if "://" in raw else raw
    i = rest.lower().find(addr)
    after = rest[i + 32:] if i >= 0 else ""
    if after.startswith(":"):                        # lxma://<address>:<key>
        k = re.split(r"[?#/]", after[1:], maxsplit=1)[0]
        key = key_bytes(k)
        if key is not None:
            out["key"] = key
        elif k:
            out["key_bad"] = True
    q = raw.split("?", 1)[1].split("#", 1)[0] if "?" in raw else ""
    if q:
        try:
            params = parse_qs(q, keep_blank_values=True)
        except Exception:
            params = {}
        if "stump" in params:
            name = unquote(params["stump"][0]).strip()
            out["stump"] = "".join(ch for ch in name if ch.isprintable())[:40]
        if "r" in params:
            rel = unquote(params["r"][0]).strip()
            if 0 < len(rel) <= 32 and rel.isprintable():
                out["release"] = rel
        if "key" in params:
            key = key_bytes(params["key"][0])
            if key is not None:
                out["key"] = key
            else:
                out["key_bad"] = True
    return out


def identity_for(address_hex, key):
    """The key's identity if its lxmf.delivery address is `address_hex`, else None."""
    try:
        ident = RNS.Identity(create_keys=False)
        ident.load_public_key(bytes(key))
        return ident if RNS.Destination.hash(ident, "lxmf", "delivery").hex() == address_hex else None
    except Exception:
        return None


def is_paper_message(text):
    """An LXMF paper message (lxm://…): a whole message, not an address."""
    return "".join(str(text or "").split()).lower().startswith("lxm://")


def b64url(key):
    return base64.urlsafe_b64encode(bytes(key)).decode().rstrip("=")


def codes(address_hex, key=None, stump_name=None):
    """The ways to show an address as a QR code, best first: [(label, who reads it, text)].
    Without a key only the bare address can be shown."""
    out = []
    if key is not None and len(key) == 64:
        link = f"lxmf://{address_hex}?"
        if stump_name:
            link += f"stump={quote(stump_name, safe='')}&"
        out.append(("FireFly", "FireFly apps and Stumps", link + "key=" + b64url(key)))
        out.append(("Columba", "Columba, MeshChatX, T-Deck LXMF", f"lxma://{address_hex}:{bytes(key).hex()}"))
    out.append(("Address", "Sideband, NomadNet, any LXMF app", address_hex))
    return out
