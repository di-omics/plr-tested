# instrument-integrations

Instruments that sit alongside the Hamilton STAR and are driven from the same
Raspberry Pi, through PyLabRobot.

`hamilton-star/` in this repo is liquid handling: one machine, one USB cable. This
directory is everything the STAR has to hand a plate to. Those instruments are on the
network rather than on the end of a cable, they have their own state machines, and
their failure modes are different. They get their own tree.

## What is here

`odtc/` - Inheco ODTC (On Deck Thermal Cycler), over SiLA/SOAP. The thermal programs
of the ResolveDNA Whole Genome Single-Cell Core Kit, expressed as PyLabRobot
protocols, plus a ladder of scripts from "is it even there" to "run a PCR program".

## Status

Communication with the ODTC is established. Nothing has heated or moved yet, and no
thermal value has been confirmed against a run, so the programs stay marked unverified.

| What | Result |
| --- | --- |
| Method XML matches TAS-068.5 Tables 1, 4, 5, 8, asserted against the real backend | passed, off-instrument |
| `odtc_offline_checks.py`, 72 checks, on starpi under PyLabRobot 0.2.1 | passed, off-instrument |
| Read-only probe: reachable, SiLA 1.2.01 confirmed, `state` is a top-level element | passed on the instrument, 2026-07-10 |
| PyLabRobot bring-up: Reset, Initialize, `startup` to `idle`, all 8 sensors read back | passed on the instrument, 2026-07-10 |
| Door open/close/cycle | written, not yet run |
| Block and lid hold at a set point | written, not yet run |
| Thermal program (`PlateauTime` unit still unconfirmed) | written, not yet run |
| STAR iSWAP handoff into the ODTC | not written, geometry not measured |

## The scripts, in the order you run them

Each rung does strictly more than the one above it. Do not skip.

| Script | Touches | What it settles |
| --- | --- | --- |
| `01_odtc_probe_raw.py` | nothing, read-only | Is a SiLA endpoint there, and what shape are its answers |
| `02_odtc_bringup.py` | device state | Does the event round trip work in both directions |
| `03_odtc_door.py` | the door motor | How long a door cycle takes, and where the opening is |
| `04_odtc_hold_block.py` | block and lid heaters | Will it hold a set point |
| `05_odtc_run_protocol.py` | block and lid heaters | Will it run a real program |

`odtc_offline_checks.py` needs no device and no network. Run it before every live
session and after every PyLabRobot upgrade.

```bash
./run_on_pi.sh odtc/odtc_offline_checks.py
```

`01_odtc_probe_raw.py` imports nothing but the standard library, on purpose. It works
when the venv does not.

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
   the same thing, uncaught). Use `run_protocol()`. PyLabRobot's own ODTC notebook does.

4. **`set_block_temperature()` sets the lid to 105 C.** Unless a lid target was already
   stashed on the backend instance, it defaults to 105 C. The ResolveDNA WGA hold wants
   a 70 C lid. Each setter also runs its own 7 to 10 minute pre-method, so calling both
   costs twice the wait. `odtc_compat.hold_block_and_lid()` sets both targets and runs
   one pre-method.

## The one thing to verify first

The backend writes `hold_seconds` straight into the ODTC method XML's `PlateauTime`
field, and assumes that field is seconds. That assumption is PyLabRobot's. No Inheco
document has been read to confirm it.

```bash
./run_on_pi.sh odtc/05_odtc_run_protocol.py --program timecheck --ip $ODTC_IP --confirm i-am-watching
```

`timecheck` is one 50 C step that claims to hold for 60 seconds. Time it with a
stopwatch. If it holds for 60 s, every program in `odtc_protocols.py` is correct. If it
holds for 1 s or for an hour, they are all wrong by that factor, and a 2.5 hour WGA
amplification is not the run on which to find that out.

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

## Where the thermal values come from

Every temperature, time, and cycle count in `odtc_protocols.py` is transcribed from
BioSkryb Genomics document **TAS-068.5, 05/2025**, "ResolveDNA Whole Genome Single-Cell
Core Kit, 96 Reactions", and cited on the line where it is used.

| Program | Source | Lid | Reaction volume |
| --- | --- | --- | --- |
| `wga` | Table 1, DNA Amplification | 70 C | 12.0 uL |
| `dnaprep` | Table 4, DNAPREP | 105 C | 6.0 uL |
| `ferat` | Table 5, FERAT | 105 C | 10.0 uL |
| `ligation` | page 16, section IV step 7 | 50 C | 20.0 uL |
| `libamp` | Table 8, LIB-AMP | 105 C | 40.0 uL |
| `timecheck` | hardware exercise, not biology | 105 C | - |
| `selftest` | hardware exercise, not biology | 105 C | - |

`timecheck` and `selftest` are not protocols. Their temperatures have no biological
meaning. They exist so that the first live run of the instrument is one minute long
instead of two and a half hours.

Two translations were needed to get TAS-068.5 onto this instrument, and both are worth
knowing:

- **A 4 C infinite hold** is a final 4 C step with `hold_seconds=0` plus
  `post_heating=True`, whose backend docstring reads "keep last temperature after method
  end". The block then sits at 4 C until something stops the method. `stop_method()`, or
  a power cycle. Nothing else.
- **Per-step lid temperatures are not supported.** The backend writes
  `start_lid_temperature` onto every step. Each source table specifies one lid
  temperature for the whole program anyway, so nothing is lost, but a protocol that
  changed lid temperature mid-program could not be expressed.

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

The STAR iSWAP handoff into the ODTC is not written, and should not be until the door
has been cycled and measured. The ODTC's `child_location` is `Coordinate(0, 0, 0)`, a
placeholder PyLabRobot's own notebook flags as a TODO. It is not a measurement. Deck
geometry in this repo is tuned by hand against the physical deck, one small step at a
time, and the ODTC will be no different.
