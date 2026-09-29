# Changelog

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
