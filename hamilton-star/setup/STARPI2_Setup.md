# STARPI2 Setup

Second Raspberry Pi 5 (`starpi2`), built to mirror `starpi`. The box and both
instrument virtualenvs are done. Nothing has been run against an instrument from
this Pi yet. See the status table before assuming anything works.

## Status

| What | Result |
| --- | --- |
| Raspberry Pi OS 64-bit (2026-06-18, Trixie) written to the 128 GB card, verified | passed |
| Hostname `starpi2`, user `lab`, SSH key auth, first boot on hardware | passed |
| Routed network access via an onsite wall jack (DHCP on the VLAN) | passed |
| `~/star-lab/env`: stock PyPI PyLabRobot 0.2.1 + `plr-mcp` pinned | passed, off-instrument |
| `~/tecan-lab/env`: di-omics fork, `facsmelody-sorter`, pinned | passed, off-instrument |
| `99-usb.rules`, byte-identical to `starpi` | passed |
| Tecan Infinite `0c47:8007` enumerates on this Pi (sysfs read, read-only) | passed on the instrument |
| Tecan bring-up (`INIT FORCE`), tray cycle, any read, from this Pi | not yet run |
| Hamilton STAR attached to this Pi | never |

Verified against `starpi` at build time: same OS (Debian 13 trixie), same kernel
line, same Python (3.13.5), same PyLabRobot (0.2.1), same udev rule md5, same
pinned shas.

## Known-good connection info

- Hostname: `starpi2`
- Username: `lab` (must match `starpi`; `/home/lab/...` is hardcoded in run paths)
- Password: `<PI2_PASSWORD>` (kept private; not published)
- SSH: key auth with the Mac's `id_ed25519`, installed at first boot
- Onsite VLAN IP (verified on 2026-07-16): `<PI2_LAN_IP>`
- Direct-link SSH (no DHCP): `ssh lab@<PI2_LINK_LOCAL>%<MAC_ETHERNET_IFACE>`
- Project directories: `~/star-lab`, `~/tecan-lab`
- Virtualenvs: `~/star-lab/env`, `~/tecan-lab/env`

`sudo` requires a password on this Pi, same as `starpi`. There is no NOPASSWD rule.

## Network: use the wall jack

**The onsite wall jacks hand out DHCP on the Preventive Medicine VLAN. Plug the
Pi straight into one and it is on the network in seconds, with internet.** This
is the shortest path by a wide margin and needs no Mac, no adapter, and no
credentials. `starpi2.local` resolved over mDNS on the VLAN.

Do not infer from `starpi` that wired ports are dead. `starpi` currently runs on
**wifi** (`wlan0`), and its `eth0` carries no IPv4, but that is because of what
its ethernet is plugged into, not because the wall jacks fail. They work.

### What does not work, and why

**macOS Internet Sharing did not start on macOS 26.5.2.** The configuration was
correct and verified in `/Library/Preferences/SystemConfiguration/com.apple.nat`:
NAT enabled, `PrimaryService` resolving to Wi-Fi (`en0`), `SharingDevices` set to
the USB ethernet adapter. The toggle showed on. Despite that: no `bridge100`
interface was created, no `natd`/`bootpd` ran, the adapter kept a self-assigned
`169.254` address, and `log show` produced **no Internet Sharing entries at all**
over 30 minutes. Not enrolled in MDM, no configuration profiles. If it fails this
way, do not keep toggling: use the wall jack.

**WPA2 Enterprise blocks every simple headless wifi path.** `SmartLabs-Users` is:

```text
802-1x.eap:          peap
802-1x.identity:     <WIFI_IDENTITY>
802-1x.phase2-auth:  mschapv2
key-mgmt:            wpa-eap
```

Raspberry Pi Imager's wifi fields, `wpa_supplicant.conf`, and a `wifi.txt` on the
boot partition all assume SSID plus pre-shared key. None can express
PEAP/MSCHAPv2. They fail **silently**: the Pi boots, never associates, never
appears. To put this Pi on wifi, either type the credentials into it directly
from a monitor and keyboard, or copy the profile from
`/etc/NetworkManager/system-connections/` on `starpi` (root on both boxes).

### Bootstrap over a direct ethernet link to the Mac

Only useful before the Pi has any network config, and it gives a shell but **no
internet**. With no DHCP server on the link the Pi takes an IPv6 link-local
address and advertises mDNS. `ping starpi2.local` fails because the name resolves
to a link-local address needing a zone index:

```bash
ping6 -c3 -I <MAC_ETHERNET_IFACE> ff02::1
ndp -an | grep <MAC_ETHERNET_IFACE>
ssh lab@<PI2_LINK_LOCAL>%<MAC_ETHERNET_IFACE>
```

The Pi's MAC begins `2c:cf:67`, distinguishing it from the Mac's own adapter.
Expect the Pi to drop off the link every few seconds in this mode: NetworkManager
cycles the interface retrying DHCP against a link with no server. That stops the
moment it gets a lease. It is not a fault.

## First boot: sshd is silent until the second boot

Expected, not a fault. The first-boot provisioning script runs in a minimal
systemd target where `regenerate_ssh_host_keys.service` does not run. Port 22 is
open (socket activation) but sshd has no host keys, so every connection is
accepted and closed instantly:

```text
kex_exchange_identification: read: Connection reset by peer
```

The tell: the host pings cleanly and port 22 accepts, but sshd sends **no version
banner at all**. Power cycle the Pi. The normal boot generates the keys.

```bash
ssh lab@<PI2_LAN_IP> 'ls /etc/ssh/ssh_host_*_key.pub | wc -l'   # 3 is correct
```

Confirm the first-boot hook cleared itself, or it re-runs every boot:

```bash
test -f /boot/firmware/firstrun.sh && echo BAD || echo ok
grep -q systemd.run /boot/firmware/cmdline.txt && echo BAD || echo ok
```

## The environment

Two virtualenvs, deliberately separate. **The Tecan fork replaces PyLabRobot;
installing it into `star-lab/env` would swap PyLabRobot under the validated STAR
and ODTC work.** They must never cross.

### `~/star-lab/env`: stock PyPI PyLabRobot

```bash
/usr/bin/python3 -m venv ~/star-lab/env
~/star-lab/env/bin/pip install --index-url https://pypi.org/simple \
    "PyLabRobot==0.2.1" "pyusb==1.3.1" "libusb-package==1.0.26.3"
git clone https://github.com/di-omics/plr-mcp.git ~/star-lab/src/plr-mcp
git -C ~/star-lab/src/plr-mcp checkout <PLR_MCP_SHA>
~/star-lab/env/bin/pip install -e ~/star-lab/src/plr-mcp
```

**PyLabRobot here is the upstream PyPI build, not a fork.** On both Pis its
dist-info shows `INSTALLER: pip`, **no `direct_url.json`** (so it came from an
index, not a VCS or path), and `Project-URL: Homepage,
https://github.com/pylabrobot/pylabrobot`. The `hamilton` and `tecan` backends are
in upstream 0.2.1. `packages/gene-edit/SETUP.md` says the STAR/ODTC/Tecan backends
live in the di-omics PyLabRobot fork and are installed with `pip install -e '.[usb]'`
from a checkout; **that is not what either Pi runs for `star-lab`.** That doc is
correct for `tecan-lab` only.

Verify the venv is not contaminated:

```bash
SP=~/star-lab/env/lib/python3.13/site-packages
cat $SP/pylabrobot-*.dist-info/INSTALLER                 # pip
test -f $SP/pylabrobot-*.dist-info/direct_url.json && echo FORK || echo ok
~/star-lab/env/bin/pip list --editable | grep -i pylabrobot   # must be empty
```

### `~/tecan-lab/env`: the di-omics fork

```bash
git clone https://github.com/di-omics/pylabrobot.git ~/tecan-lab/pylabrobot
cd ~/tecan-lab/pylabrobot
git fetch origin facsmelody-sorter && git checkout <TECAN_FORK_SHA>
/usr/bin/python3 -m venv ~/tecan-lab/env
~/tecan-lab/env/bin/pip install -e '.[usb]'
```

Both venvs use `/usr/bin/python3 -m venv` and exclude system site packages.
Trixie enforces PEP 668, so `pip install` outside a venv is refused. That is
expected; use the venv.

## udev

`/etc/udev/rules.d/99-usb.rules`, byte-identical to `starpi`:

```text
SUBSYSTEM=="usb", MODE="0666"
SUBSYSTEM=="tty", MODE="0666"
```

This is unscoped: world read/write on **every** USB and tty device on the box,
not only Hamilton's `08af` or Tecan's `0c47`. It is what the validated Pi runs, so
it is what this Pi runs, but it is worth narrowing.

**Apply it with no instrument attached, then replug rather than running
`udevadm trigger`.** `udevadm control --reload-rules` is safe with a device
attached; `udevadm trigger` re-evaluates rules against connected devices. Note
that `apt install udev usb-modeswitch` runs `udevadm trigger` **from its own
postinst**, and usb-modeswitch's rules send USB control messages to devices, so
installing those packages with an instrument plugged in touches it regardless of
what any script promises. On this Pi, `usb-modeswitch` and `rpi-usb-gadget` were
deliberately **left uninstalled** because the Tecan was attached. Install them
with the instrument unplugged.

## Gotcha: `sudo -S` and stdin

`sudo -S` reads its password from stdin. If sudo's timestamp is still cached it
does **not** consume that line, and the rest of the pipeline gets it. This:

```bash
printf 'SUBSYSTEM=="usb", MODE="0666"\n' | echo "$PW" | sudo -S tee /etc/udev/rules.d/99-usb.rules
```

wrote the **password** into the rules file instead of the rule. Pass file content
via a file, never via stdin, when stdin is also carrying a sudo password:

```bash
printf '...' > /tmp/rule
echo "$PW" | sudo -S cp /tmp/rule /etc/udev/rules.d/99-usb.rules
```

## Instruments

The **Tecan Infinite is attached to this Pi**, not to `starpi`. Confirmed by
reading sysfs (no libusb, nothing opened):

```text
0c47:8007   TECAN AUSTRIA / BIO   serial <TECAN_SERIAL>   driver: none bound
```

That matches the read-only USB probe result already recorded for `starpi`. No
Hamilton STAR has ever been attached to this Pi.

Nothing else has been run against the reader from `starpi2`. Every existing Tecan
result in this repo came from `starpi`; this Pi's first contact with the
instrument beyond enumeration has not happened. Treat any bring-up, tray move, or
read from here as a first run: attended, hand near the E-stop.
