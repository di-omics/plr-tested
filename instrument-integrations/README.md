# instrument-integrations

Instruments that sit alongside the Hamilton STAR and are driven from the same
Raspberry Pi, through PyLabRobot.

`hamilton-star/` in this repo is liquid handling: one machine, one USB cable. This
directory is everything the STAR has to hand a plate to. Those instruments are on the
network rather than on the end of a cable, they have their own state machines, and
their failure modes are different. They get their own tree.

## What is here

`odtc/` - Inheco ODTC (On Deck Thermal Cycler), over SiLA/SOAP. Public synthetic
water-only hardware profiles and an operator-owned method-profile loader, plus a
ladder of scripts from "is it even there" to "run an approved thermal method".

`tecan-infinite/` - Tecan Infinite plate reader (200 PRO, and the Nano+ sibling), over
USB. The QC endpoint: it reads a plate, it does not move liquid or heat. A plan and a
script ladder from a read-only USB probe to an absorbance read and the Rhodamine-B
fluorescence ladder. Not yet run on a reader. Unlike the ODTC this instrument is on a
cable, not the network, so its section leans on USB and libusb rather than SiLA and IP.

## Status

The ODTC is driven end to end through PyLabRobot: connect, heat, hold, and run a full
cycling profile, all confirmed on the instrument on 2026-07-10. The `PlateauTime`-is-
seconds assumption is confirmed. Wet-method values are supplied locally and are not
published here.

| What | Result |
| --- | --- |
| Method XML generation and safety limits asserted against the real backend | passed, off-instrument |
| `odtc_offline_checks.py`, 72 checks, on starpi under PyLabRobot 0.2.1 | passed, off-instrument |
| Read-only probe: reachable, SiLA 1.2.01 confirmed, `state` is a top-level element | passed on the instrument |
| PyLabRobot bring-up: Reset, Initialize, `startup` to `idle`, all 8 sensors read back | passed on the instrument |
| Block+lid hold (PreMethod): block driven to 45.00 C and held dead on target | passed on the instrument |
| Full cycling Method: pre-warm then ExecuteMethod, block to 50.00 C, completes | passed on the instrument |
| `PlateauTime` is seconds: a 60 s step held ~56-60 s on the block trace | confirmed on the instrument |
| Supervised cycling hardware exercise with an operator-owned profile | passed on the instrument |
| An approved whole-genome sequencing operator profile run at real temperatures | not yet run |
| Door open/close/cycle | written, not yet run |
| STAR iSWAP handoff into the ODTC | plate-move legs drafted (`hamilton-star/`), geometry not yet tuned |

The supervised cycling exercise approached this unit's documented block ceiling during
a fast ramp and produced non-fatal temperature warnings. Operators must review that
instrument trace when approving a local method profile; the public repository does not
encode or recommend a biological setpoint.

The Tecan reader had its first contact on 2026-07-11: plugged into the Pi, identified over
USB read-only, backend brought up in an isolated venv (`connection_verified.html` captures
it). Nothing that moves the stage has run. Its status table, its USB link, and its script
ladder live in `tecan-infinite/README.md`. The sections below are the ODTC's.

## The scripts, in the order you run them

Each rung does strictly more than the one above it. Do not skip.

| Script | Touches | What it settles |
| --- | --- | --- |
| `01_odtc_probe_raw.py` | nothing, read-only | Is a SiLA endpoint there, and what shape are its answers |
| `02_odtc_bringup.py` | device state | Does the event round trip work in both directions |
| `03_odtc_door.py` | the door motor | How long a door cycle takes, and where the opening is |
| `04_odtc_hold_block.py` | block and lid heaters | Will it hold a set point |
| `05_odtc_run_protocol.py` | block and lid heaters | Will it run a real program |

`odtc/qc/` holds the robustness QC for the supervised cycling hardware exercise: the raw instrument log,
a self-contained report generated from it (`odtc_qc_report.html`), and the generator that
turns one into the other. See `odtc/qc/README.md`.

`odtc_offline_checks.py` needs no device and no network. Run it before every live
session and after every PyLabRobot upgrade.

```bash
./run_on_pi.sh odtc/odtc_offline_checks.py
```

`01_odtc_probe_raw.py` imports nothing but the standard library, on purpose. It works
when the venv does not.

## What this firmware requires, learned on the instrument

Three things about this specific ODTC (firmware `ODTC_225_BOOT_001`, SiLA 1.2.01) are
not in PyLabRobot and would each strand a run. All three are handled in
`odtc_compat.py`.

1. **A cycling Method will not run without a PreMethod pre-warm first.** `ExecuteMethod`
   on a full profile is rejected synchronously with returnCode 11, "PreMethod or
   PostHeating is required", even though the method carries `PostHeating=true`. Running
   a PreMethod to the profile's start conditions first clears it. This is the same
   pre-warm-then-run pattern used by approved operator methods. PyLabRobot's `run_protocol()` skips
   the pre-warm, so it cannot drive this device on its own. `run_cycling_method()` adds
   it, and `05_odtc_run_protocol.py` uses that.

2. **Every method finishes "with warning" because there is no SD card.** This unit has
   no SD card in its logging slot, so each method completes with returnCode 12,
   "SuccessWithWarning ... NO_SDCARD". The method ran fine; the warning is only about
   on-device trace logging. `sila_call()` treats returnCode 12 as success. Insert an SD
   card and the warning goes away, but the code does not depend on that.

3. **The device is briefly "busy" right after Initialize.** A command fired into that
   window returns returnCode 4, "Device is busy due to other command execution", even
   after `GetStatus` reports idle. `sila_call()` retries on returnCode 4.

## What is already known, before anything is plugged in

Four things about PyLabRobot's ODTC backend were established off-instrument. Three are
worked around in `odtc_compat.py`. All four are asserted in `odtc_offline_checks.py`,
so a PyLabRobot upgrade that fixes or worsens any of them shows up as a failing check
rather than as a surprise at the bench.

1. **A failed temperature read reports 0.0 C.** `get_sensor_data()` catches every
   exception and returns its cache, which starts empty; `get_block_current_temperature()`
   then returns `[temps.get("Mount", 0.0)]`. For a thermocycler that is the worst
   available default. `odtc_compat.read_sensors()` raises instead.

2. **The response parser mistakes a string for an XML node.** `_recursive_find_key()`
   branches on `hasattr(data, "find")`, and `str` has `.find`. `"Success".find(".//state")`
   returns `-1`, and the next line evaluates `(-1).text`. Whether this fires depends on
   where `state` sits in the ODTC's `GetStatus` response, which is exactly what
   `01_odtc_probe_raw.py` prints and then rules on. If it fires, every
   constant-temperature hold breaks, because they all go through `_wait_for_idle()`.

3. **`run_pcr_profile()` cannot drive this backend.** It calls `wait_for_lid()`, which
   calls `get_lid_target_temperature()` (raises `NotImplementedError`, which is a
   subclass of `RuntimeError` and so gets swallowed) and then `get_lid_status()` (raises
   the same thing, uncaught). Use `run_cycling_method()`, which is what
   `05_odtc_run_protocol.py` calls.

4. **`set_block_temperature()` applies a backend lid default.** Unless a lid target was
   already stashed on the backend instance, the setter chooses one without consulting
   the biological method. Each setter also runs its own 7 to 10 minute pre-method, so
   calling both costs twice the wait. `odtc_compat.hold_block_and_lid()` sets both
   operator-profile targets and runs one pre-method.

## PlateauTime is seconds (settled on the instrument)

The backend writes `hold_seconds` straight into the method XML's `PlateauTime` field and
assumes seconds. That was PyLabRobot's assumption, not Inheco's, and it is the one that
could silently scale every duration. It is now confirmed. The `timecheck` program is a
single 50 C step with a 60 s `PlateauTime`:

```bash
./run_on_pi.sh odtc/05_odtc_run_protocol.py --program timecheck --ip $ODTC_IP --confirm i-am-watching
```

On the block temperature trace, the 50 C plateau lasted about 56 to 60 seconds, so the
unit is seconds and every program in `odtc_protocols.py` is scaled correctly. Re-run this
check after any firmware change before trusting the long holds.

## Network

The ODTC speaks SiLA 1.x over SOAP/HTTP on port 8080, despite the PyLabRobot docs
saying SiLA 2. Confirmed on the instrument: `GetDeviceIdentification` reports
`SiLAInterfaceVersion 1.2.01`, device class 30, manufacturer inheco.com. Two
directions have to work, and only the first is obvious:

- This host POSTs commands to `http://<odtc>:8080/`.
- The ODTC POSTs results back to an HTTP server PyLabRobot starts here, on an ephemeral
  port, whose address it learns from the `eventReceiverURI` in the `Reset` call.

If the second direction is blocked, commands are accepted and then nothing happens.
Every SiLA call in `odtc_compat.py` carries a timeout for this reason: PyLabRobot's own
`send_command()` awaits a future that only an inbound callback resolves, so a blocked
return path hangs the process forever rather than failing.

Only one process may drive the ODTC at a time. `Reset` re-registers the event receiver,
so a second process silently steals the first one's callbacks.

### The physical link

The ODTC connects to the Pi through a USB-Ethernet adapter (ASIX AX88179B,
`cdc_ncm`), which enumerates as `eth1`. It is not the Pi's onboard `eth0`: that port
is used for something else and its link flaps. Plugging in the ODTC is what brings
`eth1` up, from no-carrier to a 100 Mbps link.

The ODTC ships configured link-local, so both ends live on `169.254.0.0/16` with no
DHCP server. Give `eth1` a link-local address, which needs root and is a bench step:

```bash
sudo ip addr add 169.254.1.1/16 dev eth1
```

This does not survive a reboot. Re-run it, or make it persistent in the Pi's network
config, after any power cycle.

Then find the ODTC's own address. Read it off the instrument's front panel or its
manual first. If it has to be discovered, ARP-sweep the link-local range from `eth1`;
`arp-scan -I eth1 169.254.0.0/16` is the usual tool, but none of `tcpdump`, `arp-scan`,
or `nmap` is installed on the Pi, so `01_odtc_probe_raw.py`'s sibling approach (a raw
`AF_PACKET` ARP sweep) is what was actually used. The sweep of 65k addresses takes a
couple of minutes and returns exactly one host, which is the cycler.

### Addresses are not committed

Pass `--ip`, or set `ODTC_IP`, which `run_on_pi.sh` forwards. The ODTC's specific
link-local address and MAC are not written into this repo, per the repository's rule
on lab-internal addresses. Discover it on the link, as above.

## Where thermal values come from

Biological temperatures, durations, cycle counts, lid settings, and reaction volumes
come only from an operator-owned JSON method profile passed to
`05_odtc_run_protocol.py --operator-profile`. The loader validates the complete shape
and refuses incomplete profiles. They are intentionally absent from public defaults.

The named public programs are synthetic water-only hardware exercises. `timecheck` and
`selftest` are also hardware exercises, not biological protocols. Their values exist
only to exercise the device and have no biological meaning.

Two backend translations apply to every operator-supplied method and are worth knowing:

- **A 4 C infinite hold** is a final 4 C step with `hold_seconds=0` plus
  `post_heating=True`, whose backend docstring reads "keep last temperature after method
  end". The block then sits at 4 C until something stops the method. `stop_method()`, or
  a power cycle. Nothing else.
- **Per-step lid temperatures are not supported.** The backend writes
  `start_lid_temperature` onto every step. A method that changes lid temperature
  mid-program cannot be expressed.

## Safety

Everything `hamilton-star/README.md` says still applies, plus:

- `--confirm i-am-watching` is required by anything that moves the door or heats the
  block. There is no way to open the door or start a program by accident.
- The block reaches 99 C and the lid 105 C. Both stay hot after a program ends, because
  `post_heating` is what implements the 4 C hold. A finished program is not a cold
  instrument.
- This backend cannot tell you whether the door is open. `get_lid_open()` and
  `get_lid_status()` raise `NotImplementedError`. Use your eyes.
- Each run uploads a new method under a timestamped name, and the backend sends
  `DeleteAllMethods=false`. Methods accumulate on the device. Whether it has a limit is
  not known.

## Next

The STAR iSWAP handoff into the ODTC has draft plate-move legs under
`hamilton-star/starlab_live/` (`test_iswap_plate_rail35pos0_to_odtc_variable.py` and its
return), but the geometry is not yet tuned on hardware, and the door has not been cycled
and measured, so nothing there is validated. The ODTC's `child_location` is
`Coordinate(0, 0, 0)`, a placeholder PyLabRobot's own notebook flags as a TODO. It is not
a measurement. Deck geometry in this repo is tuned by hand against the physical deck, one
small step at a time, and the ODTC will be no different.
