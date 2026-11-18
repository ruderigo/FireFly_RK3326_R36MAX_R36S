# Changelog

## 0.9.8 (sandbox)
Build 86 (Stump 1.0.0-beta.86). Reticulum 1.6.1 and LXMF 1.3.1 (out 18 Nov),
instead of 1.5.6 and 1.2.0: `install.sh` downloads them on the next update
(or put the two new wheels in `wheels/`, INSTALL.md section 8). Both still
run on Python 3.9; CI tests 3.9 and 3.11 as before. Re-tested against real
Stumps of build 86: `tests/run_real_stump.py` (LoRa and Wi-Fi, 22 checks,
all pass; 25 with the Stump's new announce stamps switched on, all pass)
and `tests/run_real_stump_nolora.py` (all pass).
- **Announce stamps.** Reticulum 1.6.1 puts a proof-of-work stamp on every
  announce, and sends no announce and answers no path request before the
  stamp is made. It is made once per address and kept
  (`reticulum/storage/stamps`). FireFly asks Reticulum for a stamp worth
  23.5, not its default 25: 23.5 is what a node enforcing stamps asks by
  default, and the least a 1.6.1 node needs to take the stamp off before
  handing the name to its apps. It is about 2.8 times less work than 25:
  a few seconds on a computer, roughly half a minute (a couple of minutes
  when unlucky) estimated for an RK3326's first start after this update.
  Every start after that uses the kept stamp. The status screen says when
  it is still being made. `"announce_stamp_value"` in settings.json changes
  it. With `"managed_config": false`, your own Reticulum config decides.
- **FireFly's app tag survives LXMF 1.3.1.** LXMF 1.3.1 announces four items
  (its fourth is a fractional stamp cost, empty when none is asked). FireFly
  only added its app tag to three, so with 1.3.1 the tag and `{"z": 1}`
  would have gone missing. Now the tag takes the fourth place, as the
  Stumps put nothing there either: Stumps still see FireFly as a Stump app
  and send it packed text; other apps still read the name.
- **Names read right from stamped announces.** From 1.6.1 nodes and from
  Stumps with announce stamps on, Reticulum hands FireFly the app data
  without the stamp. A node whose stamp is cheaper than 23.5 arrives with
  the stamp still on: a NomadNet node's or an old app's plain-text name now
  reads without the 18 bytes after it (as the Stump does since beta.85).
- **Sending to a new 1.6.1 app waits longer for its path.** Such an app
  answers only once its own stamp is made (16 s on a fast computer the
  first time, minutes on a phone). FireFly gave up after 20 s; now it waits
  up to 3 minutes, asking again after 15 s and then every 30 s (as the
  Stump does since beta.85), and the message says it is waiting.
- Faster message stamps (`stamps.py`) moved with LXMF's stamp workers into
  Reticulum (`RNS.Stamps`): same stamps, used for large workblocks only;
  Reticulum's own multi-core workers do the small announce stamps.
- Tests: `run_announce_stamps.py` (new: FireFly's stamped announce read back
  by Reticulum's own validation, also under stamp enforcement; name, tag and
  `z`; 1.6.1 and cheaply stamped peers). The test peers use a cheap stamp so
  no test waits on one (as Team Stump's reference apps). `run_integration.py`
  checks the path is asked again. `run_real_stump.py` checks a Stump with
  announce stamps on: its stamped announce arrives and its name reads right.

## 0.9.7 (sandbox)
Build 82 (Stump 1.0.0-beta.82). Re-tested against real Stumps of that build:
`tests/run_real_stump.py` (LoRa and Wi-Fi, 22 checks, all pass) and
`tests/run_real_stump_nolora.py` (all pass).
- **Packed text: more of a chat line in each LoRa packet** (Stump beta.82).
  FireFly's LXMF announce now says it reads packed text (a fifth item,
  `{"z": 1}`, after its app tag; Sideband, MeshChat and upstream LXMF still
  read only the first three). A Stump then sends it packed replies: `/help`
  (867 bytes) arrives in one packet of 170 bytes instead of over a link.
  FireFly reads every packed message (`ztext.py`, the Stump's own file),
  and packs its own lines only to a Stump or app whose latest announce
  says `z`, only when that is shorter. Everyone else gets plain text, as
  before. `"packed_text": false` in settings.json turns it off.
  Checked against a real Stump: its `/help` came packed and read right,
  and a line FireFly sent packed (`/join`) was read by the Stump.
- A message that isn't text (or packed and broken) shows as a short note
  instead of being dropped.
- **No /auth over LoRa** (Stump beta.71): nothing to change. FireFly never
  sends `/auth` by itself over LoRa; the menu's *verify my identity* still
  works, for older Stumps.
- A Stump's QR code may end with `&r=<release>` (Stump beta.79): FireFly
  shows that release for a Stump added from its code until its beacon
  arrives (a hint only; the beacon has the last word).
- Tests: `run_packed_text.py` (Team Stump's fixed messages, unpacking, the
  announce flag, who gets packed text); `run_interop.py` (`r=`).

## 0.9.6 (sandbox)
Build 62.
- **Installed from the RK3326 Provisioner, sudo's password typed on its
  screen.** `deploy/install.sh` uses sudo (packages, the serial port, the
  Ports entry); from the Provisioner there's no terminal for sudo to ask
  in. Given sudo's askpass helper (the Provisioner 0.3.0-beta.16 does that),
  every sudo in it goes through the helper (`sudo -A`), so a long package install outliving sudo's ticket still gets the password;
  a wrong password stops it before anything changes. Over SSH nothing
  changes: sudo asks in the terminal as before.

## 0.9.5 (sandbox)
Build 62 (Stump 1.0.0-beta.62). Re-tested against real Stumps of that build:
`tests/run_real_stump.py` (LoRa and Wi-Fi, all pass) and
`tests/run_real_stump_nolora.py` (a Stump with no radio).
- **Rooms with a scope** (Stump beta.62: `/create`, `/setchan`, `/chanreq`;
  a room can go as far as Wi-Fi or LoRa go along a chain): `/rooms` ends
  such a room's line with `[Wi-Fi]` or `[LoRa ⚠]`. FireFly reads it as the
  room's scope (local, wifi, lora), apart from its topic, and shows it
  after it, as the Stump does. Checked against a real Stump: a Wi-Fi room
  made with `/create` read back from `/rooms`.
- Plugin bots carry their Stump's tag (Bavard-k7q2): read as any name.

## 0.9.4 (sandbox)
Build 60 (Stump 1.0.0-beta.60). Re-tested against a real Stump of that
build (`tests/run_real_stump.py`: the beacon, #lora-mesh, /rooms, /post and
/board over LoRa; the LAN, chat and DMs with the web chat, /join and /auth
over Wi-Fi: all pass).
- **"No LoRa on mesh"** (Stump beta.57): a Stump with no radio, nor any
  along its chain, keeps #lora-mesh closed to the chat. Its refusal
  (`⊘ #lora-mesh no-lora`) now reads "⊘ #lora-mesh: no LoRa radio on this
  Stump or its chain" with the Stump's own sentence, not "is no-lora";
  FireFly stays in #main. Checked against a real Stump without a Heltec
  (`tests/run_real_stump_nolora.py`, `STUMP_DIR_NO_LORA`).
- **Tagged names** (Stump beta.60: "LaBuche-k7q2", not "LaBuche1"): read
  as any nick, renames included (tests).
- #lora-mesh's answers now reach FireFly on a Stump without a Heltec
  (Stump beta.57's fix, nothing to change here).

## 0.9.3 (sandbox)
Build 53 (Stump 1.0.0-beta.53). Working with other LXMF apps, after reading
Sideband, NomadNet, MeshChat and LXMF's code, and the Stump and Android
teams' work (Stump beta.52-53, FireFly for Android 0.6.0-beta).
- **Every app's address code.** *Show QR code* (yours, NETWORK → Y; a
  contact's, its Y menu) now switches with ←→ between FireFly's
  `lxmf://<address>?key=…` (FireFly apps, Stumps; `stump=` for a Stump),
  `lxma://<address>:<key>` (Columba, MeshChatX, the T-Deck LXMF Messenger)
  and the bare address (Sideband, NomadNet). The codes carrying a key let
  the other app write to you before your announce reaches it.
- **Add contact takes any of them** (PEERS → + → *Paste a link*, handy with
  a USB keyboard): the key is checked against the address (a code whose key
  isn't its address's is refused, "not trusted"), then handed to Reticulum,
  so you can write at once. A Stump's code adds a Stump. Same rules as
  FireFly for Android and the Stump's `/address` page.
- **Requests from Sideband and MeshChat are declined politely.** Their
  location/telemetry requests, pings, echoes and signal reports
  (`FIELD_COMMANDS`) used to show as an empty message. Now: a short note
  ("⊘ Asked for location and telemetry: declined"), and one reply a contact
  can read, at most once an hour each, never to a Stump.
- **Formatted messages rendered** (`FIELD_RENDERER`): Markdown (NomadNet,
  Sideband), Micron (NomadNet) and BBCode, with real styles: **bold**,
  *italic*, bold italic, underline, strikethrough, `code` on a dark
  background (monospace), headings, bullets, ☑/☐ tasks, quotes, code blocks,
  dividers, and links underlined with their address in brackets. Italics use
  DejaVu's oblique faces when installed (fonts-dejavu-extra), else pygame
  slants the regular face, so they always show.
- **FireFly says it's a Stump app** in every LXMF announce (asked by the
  Stump team, 1.0.0-beta.53): a fourth app-data item,
  `stump:firefly-rk3326/<version>`. Stumps running packs that reword their
  messages for plain LXMF apps then never reword them for FireFly, from the
  first message and over LoRa too. Sideband, NomadNet, MeshChat and Columba
  read only the first three items: name and stamp cost unchanged.
- README: *Working with other LXMF apps*, layer by layer.
- Tests: `run_interop.py` (new, in CI): every code format both ways, forged
  keys, the lxma:// QR decoded back with zbarimg, contacts writable at once,
  commands declined once an hour and never to a Stump, Markdown, Micron and
  BBCode. The real-Stump test reads beta.53's `/address` link.

## 0.9.2 (sandbox)
- **Fixed: new lines from a Stump showed up among old ones ("yesterday").**
  0.9.1 filed lines received over Wi-Fi by the Stump's own clock, which can
  be unset or off (a CAM has no battery clock), so a new line could sort at
  the top of the chat. Stump lines are now filed by when they arrive, over
  Wi-Fi and over LoRa alike (Stump chat is never stored and forwarded, so
  arrival time is the right one). Lines already misfiled by 0.9.1 are put
  back in the order they arrived, once, at the next start.
- **The room label shows only where the room changes.** Over Wi-Fi each line
  is its own message, and each repeated `#lora-mesh` above it; now a run of
  lines from one room has one label, as a LoRa batch does.

## 0.9.1 (sandbox)
Build 51 (Stump 1.0.0-beta.51).
- **Chat with Stumps over Wi-Fi.** 0.9.0 listed the Stumps on the network
  but still chatted over LoRa only, so with no LoRa path (Heltec unplugged,
  or a Stump with no radio) Stump chat failed with "not delivered (Stump chat
  only goes directly)". Now FireFly greets each Stump on the network through
  its web API and chats over Wi-Fi:
  - `/hello`, both ways: the Stump signs a one-time code with its identity,
    checked against its LXMF address; FireFly answers with the signature
    `/auth` uses. A Stump that can't prove who it is gets nothing.
  - Polling every 2 s (backing off to 30 s on failures, with jitter); room
    lines, DMs and voice notes arrive in the same conversation as over LoRa,
    in the same form, filed by room. DMs that waited at the Stump arrive on
    the first poll; old room scrollback is not imported.
  - Sending: lines, `/msg nick` (web-chat users, `nick@otherstump` on a
    chain), `/join`, `/rooms`, `/board`, `/post`, `/auth`. A failed Wi-Fi send
    falls back to LoRa by itself; a Stump that restarted is greeted again.
  - A Stump met only on the network counts as a Stump.
  - SETUP → *Chat with Stumps over Wi-Fi* (on by default). The chat header
    and NETWORK say "over Wi-Fi as <nick>", or "Wi-Fi lost: LoRa".
- Tested against the real Stump 1.0.0-beta.51 (`tests/run_real_stump.py`):
  greeting, a line, a DM from a web-chat user and the answer back, `/join`,
  `/auth` over Wi-Fi. `tests/run_stumpweb.py` (new, in CI) against a fake.

## 0.9.0 (sandbox)
**The local network, exactly as EmulationStation set it up.**
- FireFly takes whatever network the handheld is on (Wi-Fi chosen in
  EmulationStation, a cable, a USB network adapter) and never joins, scans,
  stores or changes one: no `nmcli`, no passwords, no root. Like a ROM.
- **Followed live.** Reticulum's local discovery (how Sideband, NomadNet,
  MeshChat and other FireFlys find each other on a LAN) used to bind only to
  the networks present when FireFly started. It is now attached at runtime
  and again whenever the network changes: joined later in EmulationStation,
  another network chosen, a USB adapter plugged in, a cable pulled. FireFly
  announces itself on the new network and collects messages at once.
  SETUP's *Local network discovery* switch applies live, no restart.
- **NETWORK → LOCAL NETWORK:** the network's name (read with `iwgetid`), the
  handheld's address, whether it reaches the internet, how many Reticulum
  devices discovery found, or "No network: join Wi-Fi in EmulationStation's
  settings".
- **Stumps on the same network:** FireFly asks `STUMP?` (UDP 4244, Stump
  1.0.0-beta.21+) every minute and lists the answers with their web address;
  a Stump also heard over LoRa is marked so. Answers are checked (address,
  name, web address) before use. Tested against a real Stump 1.0.0-beta.50.
- NETWORK → Y → *Look at the network again*.
- `tests/run_lan.py` (new, in CI): reading the network, `STUMP?`, and the
  manager following a fake network through every change above; a real
  Reticulum AutoInterface attached and removed at runtime.

## 0.8.2 (sandbox)
Checked against **Stump 1.0.0-beta.50**, now build 50. SandBox_Stump_On is
where Stump is developed and released from beta.50 on; LaBuche-Stump keeps
the releases up to beta.48. Nothing changed for LXMF clients since beta.46:
beta.47 (a DM to a Stump answered privately by its bot) arrives as an
ordinary `[DM]` line, and beta.48 to beta.50 are provisioning and docs.
- **Tested against a real Stump, not only a fake one:** `tests/run_real_stump.py`
  starts an unmodified computer Stump from SandBox_Stump_On and talks to it
  over a simulated LoRa channel (FireFly's RNode on a pseudo-terminal, the
  Stump's "Heltec over Wi-Fi" on TCP 7633). Passed with beta.50: the Stump
  recognised from its beacon with its release, landing in `#lora-mesh`,
  `/rooms`, `/post` (`✓ #id`), `/board` listing that notice, and `/auth`
  (AUTH-OK). Skipped unless `STUMP_DIR` points to a Stump folder.
- The fake RNode can now share a channel with another (`link()`), and has a
  TCP variant for Wi-Fi-mode Heltecs.
## 0.8.1 (sandbox)
- **Build number next to the version:** the SandBox_Stump_On build this
  FireFly is tested against, now 46 (Stump 1.0.0-beta.46). The start-up
  screen says `FireFly 0.8.1 build 46` and "tested against Stump
  1.0.0-beta.46"; SETUP shows *FireFly version* 0.8.1 and *Build* 46.
- **A Stump whose beacon never arrives is still recognised** (seen with a
  computer Stump on macOS, listed as a person). FireFly now also knows a
  Stump by what only a Stump sends: a room batch titled `#lora-mesh`,
  `#wifi-mesh` or `#main`, the `→ #room` landing line, a reply token, an
  `AUTH-CHALLENGE`, a `✓ #id` post. It is then named from its announce,
  and the beacon is asked for again to fill in its release.
- **Show QR code** for an address: in a contact's Y menu, and NETWORK → Y →
  *Show my address as a QR code* (big, black on white, the address under
  it). A phone camera reads it off the screen. The encoder (qrcode 8.2, BSD,
  pure Python) is bundled, so no new package and offline updates still work.

## 0.8.0 (sandbox)
Beta testing in SandBox_FireFly_RK3326, against Stump 1.0.0-beta.46
(SandBox_Stump_On). The stable FireFly stays at 0.7.3.
- **The billboard over LoRa** (Stump 1.0.0-beta.38+): in a Stump's Y menu,
  *Billboard: newest notices* (`/board`), *search or open #id* (`/board
  <words|id>`) and *post a notice* (`/post <title> | <body>`). Notices show
  as `▪ #482193 title`, a post's confirmation as `✓ notice #482193 posted`.
- **`⧗` shows the Stump's own sentence and no longer fails your line.**
  Since beta.38 the same token also means "the radio is down, your line
  waits up to an hour", so 0.7.2's automatic "send it again" could make
  duplicates. The sentence (in the Stump's language) says which it is.
- **Forged Stump beacons are ignored**: the LXMF address a beacon names
  must belong to the beacon's own identity (as Stumps check since beta.37).
- **The Stump's release** (the beacon's sixth item, beta.35+) is shown
  instead of its "Beta A" label in its contact details.
## 0.7.3
- The version number shows on the start-up screen ("FireFly 0.7.3"), on the
  error screen if start-up fails, and at the bottom of SETUP
  ("FireFly version").

## 0.7.2
Follows LaBuche-Stump 1.0.0-beta.34 over LoRa/LXMF.
- **`#lxmf` is now `#lora-mesh`.** FireFly reads both names as the same room
  (older nodes still say `#lxmf`), in the landing message, replies, `/rooms`
  and room batch titles.
- **Chained Stumps:** `#wifi-mesh` batches are filed under their own room;
  people on other Stumps show as `nick@thatstump`, in rooms and DMs.
- **`⧗` now also means "lines too fast"** (3 at once, then one every 2 s):
  the line wasn't passed on. FireFly marks your latest line to that Stump as
  failed with "send it again", and a late delivery proof doesn't hide that.
- **New `[LoRa]` room tier** (`⊘ #lora-mesh LoRa — …`): shown with what it
  means. `/rooms` reads any tier tag, not only `[minted]`/`[hybrid]`.
- **Never looks like a Stump:** a Stump now takes LXMF batches titled
  `#lora-mesh`/`#wifi-mesh`, and lines starting `[DM>`, for another
  Stump's. FireFly never sends those to a Stump.
- The `stump.node` beacon's new fifth item (web addresses) is accepted, as
  were four-item beacons.
## 0.7.1
- **Fixed: a USB RNode could stay undetected until FireFly was restarted.**
  Opening the serial port resets ESP32 boards such as the Heltec V3, and
  Reticulum gives the board only 2.2 s to answer. A board that booted a
  little slower was taken for "not an RNode", and every retry reopened the
  port and reset it again, so it could miss indefinitely ("Could not detect
  device" every 30 s in the Reticulum log; the board's LEDs active, nothing
  sent or received). FireFly now keeps asking on the open port for up to
  8 s, without reopening it, so a slow-booting board is found on the first
  try. Seen on an R36MAX with a Heltec V3; the radio test now includes a
  board that boots that slowly.

## 0.7.0
Follows LaBuche-Stump Beta A, which carries FireFly on its SD card and
provisions Heltec radios for handhelds.
- **The release zip is now named `FireFly-RK3326-<version>.zip`**, the name
  Stump nodes look for in their SD card's `tools` folder (they offer the
  highest version on their Wi-Fi). Same content and layout; releases up to
  0.6.2 were `firefly_vX.Y.Z.zip`.
- **Off-grid updates.** The installer no longer needs internet when nothing
  new is needed: system packages already present aren't downloaded again,
  and Reticulum/LXMF are kept when the right versions are installed, so a
  zip downloaded from a Stump installs entirely off-grid. Without internet,
  missing voice decoders are skipped with a warning; missing essentials stop
  the install with the list. A `wheels/` folder (rns and lxmf wheels) makes
  even a first pip step offline.
- **radio.json**: the Stump provisioner's radio profile for a handheld's
  Heltec (frequency, bandwidth, SF, CR, TX power, optional IFAC passphrase)
  is applied at start when found in `/roms/firefly/`,
  `/roms/ports/meshcommandermax/` (the provisioner's path), `/roms/ports/firefly/`,
  the top of `/roms`, or `~/.firefly/`. Applied once per file content, so
  later changes by hand stick; reported on screen; a broken file changes
  nothing and says why. SETUP → *Load radio.json from SD card* re-applies it.
- **Network passphrase (IFAC)**: SETUP → *Network passphrase* (and an
  optional network name) for meshes that use Reticulum interface access
  codes, applied to the RNode interface live like the other radio settings.
- Same Reticulum 1.5.6 / LXMF 1.2.0 as 0.6.2, so updating needs no download.

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
