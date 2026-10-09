# Test data

`kristoff_1200.bit` is the test vector from the *Voice notes over LXMF: Codec 2
interoperability spec* (FireFly for Android, 3 Oct 2026): raw Codec 2 1200
frames, no header, 750 bytes = 125 frames = 5.00 s.

- SHA-256: `7ba18f754933bab5201157faa0ffb6edf2d7cb4859418e2231f2ce30be56bd14`
- Made with `c2enc 1200` (Codec 2 1.2.0) from `raw/kristoff.raw` in the
  [Codec 2 repository](https://github.com/drowe67/codec2) at tag 1.2.0
  (SHA-256 `d1a955308fd4fc08157e19a20322cd51074c74542b9184c6f49394d5e8bc87d7`).
  Codec 2 is LGPL-2.1.

Decoding it must give exactly 40,000 samples (5.00 s) of speech.
