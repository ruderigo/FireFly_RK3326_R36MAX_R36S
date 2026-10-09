# Changelog

## 0.6.2
Everything since 0.4.0. Versions 0.5.0 to 0.6.1 only shipped inside Project
Stump's tools folder, not here.

- **Voice notes.** Notes sent from Sideband, FireFly for Android and other
  LXMF apps are played on the handheld: Opus, and every Codec 2 mode in the
  LXMF voice spec (700C to 3200), decoded byte-for-byte like Codec 2's own
  `c2dec`. Pick any note in a chat, not only the newest, and play it whole.
  Each note is also copied to the SD card as a WAV (`firefly-voice` next to
  your ROMs, so you can get it off on a computer). Recording and sending
  aren't supported yet.
- **The installer adds `opus-tools` and `codec2`** for decoding, and installs
  exactly Reticulum 1.5.6 and LXMF 1.2.0, the versions this release was
  tested with, instead of the newest. `device_report.sh` shows whether both
  decoders and an audio device are present.
- **Delete and block.** Delete a single message (a voice note's audio files
  go with it) or a whole conversation and contact; Cancel is the default.
  Blocked contacts' messages and announces are ignored, including after a
  restart (LXMF's own ignore list is rebuilt at start-up).
- **Chat view**: a selector to move through messages, see a message's
  details, and follow new arrivals.
- **Offline delivery**: a propagation node is found from its announces and
  messages waiting for you are collected sooner after a radio or network link
  comes up, with a minimum gap between syncs. Messages are collected every
  30 minutes by default (was 60); a setting still at the old default moves
  to 30, a chosen interval is kept.
- Fixed the Codec 2 decoding bug of 0.5.0 to 0.5.2.

## 0.4.0
- **The radio is no longer part of start-up.** Reticulum starts with the
  Wi-Fi/LAN and TCP links only; a background radio manager attaches the RNode
  afterwards. A missing or faulty radio can't delay or break start-up.
- **Any RNode, on any port.** Every USB serial device is probed for an RNode,
  plus Wi-Fi RNodes listed in SETUP (TCP port 7633). The first that answers is
  used. Unplugging is detected; a different board is picked up automatically.
- **Radio settings apply live**: no restart after changing frequency,
  bandwidth, spreading factor, coding rate, TX power, or the radio on/off.
- **Radio status on NETWORK**: online (chip and firmware), no radio, searching,
  or refused with the reason.
- An RNode with outdated firmware is reported instead of shutting FireFly
  down (Reticulum's default reaction).
- `tests/run_radio.py`: the radio manager tested against simulated RNodes.

## 0.3.1
- **Clean reinstalls keep your settings.** `cleanup.sh` now puts your
  identity and settings back by default; `--new-identity` and
  `--factory-reset` are there when you want them.
- **Settings lost to an earlier clean reinstall are restored automatically**
  on first start, from the newest `~/firefly-backup-*` or
  `~/reticom-backup-*` folder, without overwriting anything you've changed
  since. The NETWORK tab says what came back.
- If the saved radio port no longer exists (a replug can turn ttyACM0 into
  ttyACM1), FireFly uses the USB serial device it finds instead.
- NETWORK shows Reticulum's actual reason when the LoRa radio doesn't respond.
- The Ports launcher closes a FireFly or RetiCom copy still holding the radio.

## 0.3.0
- **Multi-device support** for every RK3326 handheld in arkos4clone's
  dArkOS image (91 variants), grouped by screen size in the README.
- **Screen rotation** for portrait panels mounted sideways: automatic,
  adjustable with Select + R1 or SETUP → Screen rotation, and saved.
- Layout checked at every supported geometry, from 480×320 to 1280×720
  (`tests/devices.py`).
- Installer checks the firmware first (apt, Python 3.9+, pygame 2) and
  explains what's wrong instead of failing midway.
- `deploy/device_report.sh` for bug reports and new-device reports.
- Launcher no longer assumes the `/home/ark` path.

## 0.2.0
- **Renamed from RetiCom to FireFly.** The package, app folder
  (`/home/ark/firefly`), data folder (`~/.firefly`), Ports entry
  (`FireFly.sh`) and environment variable (`FIREFLY_HOME`) all use the new name.
- Upgrading keeps your identity (same address), contacts, messages and
  settings: the installer moves `~/.reticom` to `~/.firefly`, renames the
  message database, and removes the old RetiCom app folder and Ports entry.
  FireFly does the same move itself on first start if the installer wasn't used.
- `cleanup.sh` also removes RetiCom leftovers, backing up their identity key.

Versions before 0.2.0 were released as RetiCom.

## 0.1.3
- Repository layout: docs at the top, `firefly/` folder plus the zip to install.
- `deploy/cleanup.sh`: removes earlier installs; always backs up the identity
  key first; `--keep-identity`, `--purge-user-rns`.
- Installer and launcher ignore rns/lxmf in `~/.local` (`PYTHONNOUSERSITE`).
- Install guide: copying with `scp`, identity backup and restore, updating,
  rolling back, uninstalling.

## 0.1.2
- Identity key is power-cut safe: fsync'd atomic writes, `identity.bak`,
  rejection of blank or truncated keys, automatic restore, no silent new address.
- Everything is flushed to the SD card on exit.

## 0.1.1
- Start-up screen shown immediately; start-up errors shown on screen.
- Timestamped `launch.log` (video driver, screen size, each start-up step).
- A damaged `settings.json` no longer prevents starting.

## 0.1.0
- First release: LXMF messaging over LoRa (RNode), Wi-Fi/LAN and TCP;
  delivery states; propagation-node fallback and sync; radio setup on the
  device; on-screen keyboard and quick replies; Stump node foundations.
