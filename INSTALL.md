# Installing FireFly

This guide covers a first install, backing up your identity, updating,
rolling back, and removing FireFly. It applies to every RK3326 handheld
running the **dArkOS image of arkos4clone** (see
[Supported devices](README.md#supported-devices)); examples use an R36MAX.

In the commands below, replace:

- `<handheld-ip>` with your handheld's IP address (shown in its Wi-Fi or
  network info screen),
- `firefly_vX.Y.Z.zip` with the zip's file name (currently `firefly_v0.4.0.zip`).

---

## 1. What you need

- The handheld, running the **dArkOS image of arkos4clone**, with **Wi-Fi or
  USB Ethernet working** (the installer downloads packages). The installer
  checks the firmware first and stops with an explanation if it's too old.
- **Remote services (SSH) enabled** on the handheld. In EmulationStation:
  Start → Options → Enable Remote Services (the wording varies a little
  between firmware builds). The login is usually user `ark`, password `ark`.
- A computer on the same network. macOS and Linux have `ssh` and `scp`
  built in; Windows 10/11 has them in PowerShell.
- A **LoRa board with RNode firmware**, plugged into the handheld's USB
  (through a hub on the OTG port if needed). FireFly also works without
  one, over Wi-Fi/LAN or the internet.
- `firefly_vX.Y.Z.zip` from the [latest release](https://github.com/ruderigo/FireFly_RK3326_R36MAX_R36S/releases/latest) (under **Assets**).

---

## 2. Prepare the LoRa radio (on your computer, once)

FireFly talks to the radio through **RNode firmware**. Supported boards
include Heltec LoRa32 v3/v4, LilyGO T-Beam, T3S3, LoRa32 and RAK4631-based
boards.

With the board plugged into your computer:

```bash
pip install rns
rnodeconf --autoinstall
```

Follow the prompts. Choose the frequency band your board was built for
(the Stump network uses 915 MHz).

---

## 3. Plug the radio into the handheld and check it

Connect the board to the handheld, then open an SSH session from your
computer:

```bash
ssh ark@<handheld-ip>
```

On the handheld:

```bash
ls /dev/ttyUSB* /dev/ttyACM*
```

You should see a device such as `/dev/ttyUSB0` (boards with a CP2102 USB
chip, like the Heltec V3) or `/dev/ttyACM0` (native-USB boards). If nothing
appears, run `dmesg | tail -20` right after plugging the board in and note
what it says: the handheld's 4.4 kernel may lack the driver for that USB chip.

FireFly finds the RNode by itself on whichever port it appears, so there's
nothing to configure here, and you can plug or unplug it while FireFly runs.
An RNode in Wi-Fi mode works too: add its IP address later in SETUP →
Wi-Fi RNodes.

Keep this SSH session open for the next steps.

---

## 4. Copy the zip to the handheld

**Option A: download it on the handheld.** In the SSH session:

```bash
cd /home/ark
wget https://github.com/ruderigo/FireFly_RK3326_R36MAX_R36S/releases/latest/download/firefly_vX.Y.Z.zip
```

**Option B: copy it from your computer.** Open a **second** terminal on your computer (on a Mac, `Cmd + T` opens a new
tab and keeps the SSH session open), then send the zip to the handheld's
home folder:

```bash
scp /path/to/firefly_vX.Y.Z.zip ark@<handheld-ip>:/home/ark/
```

**Mac shortcut:** type `scp ` (with a trailing space), drag the zip from
Finder into the terminal window, type a space, then paste
`ark@<handheld-ip>:/home/ark/`.

Enter the handheld's password (usually `ark`) when asked.

Earlier versions stay available in the repository history, so you can
always roll back (section 9).

---

## 5. Install

Back in the **SSH session on the handheld**:

```bash
# 1. Unpack into a temporary folder
mkdir -p ~/firefly-new
unzip -o ~/firefly_vX.Y.Z.zip -d ~/firefly-new

# 2. Remove any earlier install; keeps your address and settings (safe on a first install too)
bash ~/firefly-new/firefly/deploy/cleanup.sh

# 3. Install
bash ~/firefly-new/firefly/deploy/install.sh

# 4. Remove the temporary files and the copied zip
rm -rf ~/firefly-new ~/firefly_vX.Y.Z.zip

# 5. Reboot: this also applies the new serial-port permission
sudo reboot
```

What the installer does:

- installs prebuilt system packages (`python3-pygame`,
  `python3-cryptography`, `python3-serial`, `fonts-dejavu-core`), so nothing
  is compiled; that matters because the handheld has no swap,
- puts the app in `/home/ark/firefly`, on the Linux home partition; the
  exFAT `/roms` partition can't protect a private key with file permissions,
- installs Reticulum (`rns`) and LXMF in a private Python environment,
  ignoring any copies in `~/.local`,
- adds your user to the `dialout` group so it can open the radio's serial port,
- adds **FireFly** to the Ports menu (`/roms/ports/FireFly.sh`).

If `cleanup.sh` reports that **`rnsd` is running**, stop it before you
test (`pkill -f rnsd`): FireFly would otherwise attach to that Reticulum
instance and use its settings instead of its own.

---

## 6. First start

1. Open **Ports → FireFly**. An orange "Starting Reticulum and LXMF…"
   screen appears while it starts.
2. **SETUP**: set your display name. Check that the radio settings match
   your network exactly (for Stump: *Load Stump defaults*). Radio changes
   apply by themselves within a couple of seconds.
3. **NETWORK**: under LORA RADIO you should see **● online on …** with the
   board's chip and firmware. Press A to announce yourself.
4. **PEERS**: people appear as they announce. A opens a chat.

To quit, press **Select + Start**.

---

## 7. Back up your identity (do this now)

Your **identity key** is a 64-byte file: `/home/ark/.firefly/identity`. It
**is** your address. If you lose it, you get a new address and your contacts
can no longer reach you at the old one. Nobody can recover it for you.

From your computer:

```bash
scp ark@<handheld-ip>:/home/ark/.firefly/identity ~/firefly-identity-backup
```

Keep that file somewhere private, such as an encrypted drive or a password
manager that stores files. Anyone who has it can pose as you.

FireFly also protects the key on the handheld itself; see
[Your identity](README.md#your-identity) in the README.

---

## 8. Updating to a new version

An update replaces the app and keeps everything else: your identity,
contacts, messages and settings (all in `~/.firefly`).

Get the new zip onto the handheld as in section 4, then:

```bash
mkdir -p ~/firefly-new
unzip -o ~/firefly_vX.Y.Z.zip -d ~/firefly-new
bash ~/firefly-new/firefly/deploy/install.sh
rm -rf ~/firefly-new ~/firefly_vX.Y.Z.zip
```

**Don't run `cleanup.sh` for a normal update.** It deletes your messages
(it keeps your address and settings).

---

## 9. Restoring your identity (new SD card, reflash, or clean reinstall)

Install FireFly first (section 5), but **don't start it yet**. Copy your
backup to the handheld:

```bash
scp ~/firefly-identity-backup ark@<handheld-ip>:/home/ark/identity.restore
```

Then on the handheld:

```bash
mkdir -p ~/.firefly && chmod 700 ~/.firefly
cp ~/identity.restore ~/.firefly/identity
cp ~/identity.restore ~/.firefly/identity.bak
chmod 600 ~/.firefly/identity*
rm ~/identity.restore
sync
```

Start FireFly: the NETWORK tab shows your old address. Peers learn where you
are again from your next announce.

---

## 10. Clean reinstall, reset or uninstall

`cleanup.sh` removes the app, its Python environment, your messages and the
Ports launcher. It **always** backs up your identity key and settings first,
to `~/firefly-backup-<date>/`, and by default puts them straight back, so a
clean reinstall keeps your address, radio setup, port, network links and
display name.

```bash
bash ~/firefly-new/firefly/deploy/cleanup.sh                  # clean reinstall: same address, same settings
bash ~/firefly-new/firefly/deploy/cleanup.sh --new-identity   # ...but start with a NEW address
bash ~/firefly-new/firefly/deploy/cleanup.sh --factory-reset  # new address AND default settings
bash ~/firefly-new/firefly/deploy/cleanup.sh --purge-user-rns # also remove rns/lxmf from ~/.local
```

To uninstall completely, run it with `--factory-reset`, then delete
`~/.firefly` and, once you've kept a copy of your key elsewhere, the
`~/firefly-backup-*` folders.

Run it from a copy outside `/home/ark/firefly` (it refuses otherwise,
because it deletes that folder). It only reports, without touching, things
FireFly doesn't own: a running `rnsd`, a `~/.reticulum` config, and
rns/lxmf in `~/.local`. Use `--purge-user-rns` only if nothing else of
yours (NomadNet, for example) uses those.

**Settings lost to an earlier clean reinstall** (before 0.3.1, cleanup
didn't keep them) come back by themselves: on its first start, FireFly
finds the newest backup folder with customised settings and restores any
setting you haven't changed since. The NETWORK tab says what it restored.
It never touches the identity key, and a `--factory-reset` is respected.

## Testing without the screen

Over SSH, FireFly can run without its interface:

```bash
cd ~/firefly && PYTHONNOUSERSITE=1 ./venv/bin/python -m firefly --headless
```

Commands: `peers`, `send <address> <text>`, `chat <address>`, `net`,
`announce`, `sync`, `quit`.

---

## Troubleshooting

For a bug report or a newly tested device, this collects everything useful
(device model, screen, system, controller, radio, last start-up):

```bash
bash ~/firefly/deploy/device_report.sh
```

Otherwise, start with the logs:

```bash
cat ~/firefly/launch.log                  # startup steps, video driver, errors
tail -30 ~/.firefly/reticulum/logfile     # Reticulum: interfaces, radio
```

**If FireFly hangs, don't hold the power button.** A power cut can damage
files that were just written. Over SSH instead:

```bash
pkill -f firefly
sync
```

| Problem | What to do |
|---|---|
| Picture sideways or upside down | Press **Select + R1** until it's upright (saved automatically). |
| Black screen, no orange start screen | Paste `launch.log` into an issue: it shows the video driver and where startup stopped. |
| Start screen shows an error | The last lines of the error are on screen; the full trace is in `launch.log`. |
| LORA RADIO says **no radio plugged in** | The handheld sees no USB serial device: check the cable and hub, and `ls /dev/ttyUSB* /dev/ttyACM*`. |
| LORA RADIO says **searching** | Devices are there but none answers as an RNode: flash RNode firmware (section 2). NETWORK → Y → *Search for RNodes now* retries at once. |
| LORA RADIO says **RNode refused** | The line below says why: a frequency outside the board's band, a TX power above its limit, or firmware too old (update with `rnodeconf`). Change the setting and it retries by itself. |
| `Permission denied` on the serial port | Reboot after installing (the `dialout` group needs a new login). |
| Nobody appears in PEERS | Radio settings must match the other nodes exactly: frequency, bandwidth, spreading factor, coding rate. |
| "AutoInterface could not autoconfigure" in the log | Wi-Fi/LAN discovery needs the network up when FireFly starts. Doesn't affect LoRa. |
| NETWORK warns the identity key was restored or recreated | See [Your identity](README.md#your-identity). If a new address was created, restore your backup (section 10). |
| Buttons do nothing | `launch.log` lists unmapped buttons; add them to `joystick_map` in `~/.firefly/settings.json`, e.g. `{"0": "a", "1": "b"}`. |
| Squares instead of symbols | `sudo apt install fonts-dejavu-core` |
| Message stuck at ⚙ | The recipient requires a "stamp" (anti-spam proof of work); the handheld's CPU is slow at these. |
