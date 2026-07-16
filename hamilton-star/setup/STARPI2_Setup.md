# STARPI2 Setup

Second Raspberry Pi 5 (`starpi2`), built to mirror `starpi`. OS and access are done.
The instrument environment is not built yet. See the status table below before assuming
anything works.

## Status

| What | Result |
| --- | --- |
| Raspberry Pi OS 64-bit (2026-06-18, Trixie) written to the 128 GB card, verified | passed |
| Hostname `starpi2`, user `lab`, SSH key auth, first boot on hardware | passed |
| SSH from the Mac over a direct ethernet link (IPv6 link-local) | passed |
| Routed network access (LAN or shared) | not yet |
| `~/star-lab/env` + PyLabRobot 0.2.1 + plr-mcp | written, not yet run |
| `~/tecan-lab/env` + di-omics fork `facsmelody-sorter` | written, not yet run |
| udev `99-usb.rules` | not yet |
| Any instrument attached | none |

## Known-good connection info

- Hostname: `starpi2`
- Username: `lab` (must match `starpi`; `/home/lab/...` is hardcoded in run paths)
- Password: `<PI2_PASSWORD>` (kept private; not published)
- SSH: key auth with the Mac's `id_ed25519`, installed at first boot
- Direct-link SSH: `ssh lab@<PI2_LINK_LOCAL>%<MAC_ETHERNET_IFACE>`
- Project directory: `~/star-lab` (planned)
- Virtualenv: `~/star-lab/env` (planned)

## Verified on the hardware

- Raspberry Pi 5 Model B Rev 1.1, 8 GB
- Debian GNU/Linux 13 (trixie), kernel 6.18.34+rpt-rpi-2712, aarch64
- Python 3.13.5, which matches `starpi` exactly
- 128 GB card, root resized to 117 GB
- `lab` is uid 1000, in `sudo dialout plugdev gpio i2c spi netdev` among others

## Why the standard headless Wi-Fi path does not work here

`SmartLabs-Users` is **WPA2 Enterprise**, not a pre-shared key network:

```text
802-1x.eap:          peap
802-1x.identity:     <WIFI_IDENTITY>
802-1x.phase2-auth:  mschapv2
key-mgmt:            wpa-eap
```

Every simple headless Wi-Fi mechanism (Raspberry Pi Imager's Wi-Fi fields,
`wpa_supplicant.conf`, a `wifi.txt` on the boot partition) assumes SSID plus
password. None of them can express PEAP/MSCHAPv2. They fail silently: the Pi
boots, never associates, and never appears on the network. This is the single
biggest time sink in bringing up a Pi here.

Two paths that do work:

1. **Type the credentials into the Pi directly.** Attach a monitor over
   micro-HDMI and a USB keyboard, boot the desktop, pick the network from the
   Wi-Fi menu, enter the identity and password there. This is how `starpi` is
   connected (`wlan0`, DHCP), and it is the end state for a bench Pi. The
   credential never leaves the machine that needs it.
2. **Copy the working profile from `starpi`.** The connection profile lives at
   `/etc/NetworkManager/system-connections/`. Requires root on both boxes.

Note: `starpi` runs on **Wi-Fi**, not ethernet. Its `eth0` carries no IPv4, so a
wired port is not a substitute. Do not assume a wall jack will hand out DHCP.

## Bootstrap over a direct ethernet link to the Mac

Useful before the Pi has any network config. A USB ethernet adapter on the Mac,
cable straight to the Pi.

With no DHCP server on the link, the Pi takes an IPv6 link-local address and
advertises mDNS. `ping starpi2.local` fails, because the name resolves to a
link-local address that needs a zone index. Find it and connect:

```bash
ping6 -c3 -I <MAC_ETHERNET_IFACE> ff02::1
ndp -an | grep <MAC_ETHERNET_IFACE>
ssh lab@<PI2_LINK_LOCAL>%<MAC_ETHERNET_IFACE>
```

The Pi's MAC begins `2c:cf:67`, which distinguishes it from the Mac's own
adapter on the same wire.

This gets a shell but **no internet**. For `apt` and `pip`, either enable
macOS Internet Sharing (System Settings -> General -> Sharing -> Internet
Sharing, from Wi-Fi to the USB adapter), which NATs the Pi through the Mac and
needs no Wi-Fi credentials on the Pi, or put the Pi on Wi-Fi as above.

## First boot: sshd is silent until the second boot

Expected and not a fault. On first boot the provisioning script runs in a
minimal systemd target, where `regenerate_ssh_host_keys.service` does not run.
Port 22 is open (socket activation) but sshd has no host keys, so every
connection is accepted and immediately closed:

```text
kex_exchange_identification: read: Connection reset by peer
```

The tell is that the host pings cleanly and port 22 accepts, but sshd sends no
version banner at all. Power cycle the Pi. The normal boot generates the host
keys and SSH works. Confirm with:

```bash
ssh lab@<PI2_LINK_LOCAL>%<MAC_ETHERNET_IFACE> 'ls /etc/ssh/ssh_host_*_key.pub | wc -l'
```

Three keys is correct. Also confirm the first-boot hook cleared itself, or the
Pi will re-run it every boot:

```bash
test -f /boot/firmware/firstrun.sh && echo BAD || echo ok
grep -q systemd.run /boot/firmware/cmdline.txt && echo BAD || echo ok
```

## Environment to build (not yet done)

Mirror `starpi`. The two virtualenvs must stay separate; the Tecan fork replaces
PyLabRobot, and installing it into `star-lab/env` would swap PyLabRobot under the
validated STAR and ODTC work.

- `~/star-lab/env`: **stock PyPI** `PyLabRobot==0.2.1`, plus `plr-mcp` installed
  editable from the di-omics repo at a pinned sha. `starpi` shows `INSTALLER: pip`
  and no `direct_url.json` for PyLabRobot, so it is the upstream PyPI build, not a
  fork. `packages/gene-edit/SETUP.md` says the STAR backends come from the fork;
  that is not what `starpi` runs.
- `~/tecan-lab/env`: the **di-omics PyLabRobot fork**, branch `facsmelody-sorter`,
  installed editable with the `usb` extra.

Both venvs are built with `/usr/bin/python3 -m venv` and do not include system
site packages. Trixie enforces PEP 668, so `pip install` outside a venv is
refused; this is expected, use the venv.

## udev (not yet applied)

`starpi` carries `/etc/udev/rules.d/99-usb.rules` granting `MODE="0666"` on
`usb` and `tty` subsystems. Note this is unscoped: it applies to every USB and
tty device on the box, not only to Hamilton's vendor id.

Apply it with no instrument attached, then replug or reboot rather than running
`udevadm trigger` against a connected instrument.
