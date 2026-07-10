# plr-tested

PyLabRobot code that has been run on real hardware.

Most lab-automation code is written against a simulator and never touches an
instrument. This repo is the opposite. Code here is executed on a physical
machine, with a person watching, and the run output is what decides whether a
value is right. Nothing is marked validated on the strength of a simulation.

Work that is written but has not yet met the instrument says so, in the status
table of the directory that owns it, and it stays marked that way until a run
says otherwise.

## What is here

- [`hamilton-star/`](hamilton-star) - protocols and validation scripts for a
  Hamilton Microlab STAR driven by PyLabRobot from a dedicated Raspberry Pi.
  ResolveDNA PTA/WGA and amplicon-seq liquid handling, iSWAP plate moves, and
  heater-shaker handoffs.
- [`instrument-integrations/`](instrument-integrations) - the instruments the
  STAR hands plates to, driven from the same Pi. Currently the Inheco ODTC
  (On Deck Thermal Cycler) over SiLA/SOAP: the ResolveDNA thermal programs as
  PyLabRobot protocols, and a ladder of scripts from reachability to a PCR run.
  Not yet run on the instrument.

## What "tested" means here

Geometry is not guessed. Aspirate and dispense heights, XY offsets, and blowout
volumes are tuned by hand against the physical deck, one small step at a time.
The dated comment block at the top of each script is the authoritative record
of why each value is what it is, including the values that were tried and
rejected. Known-bad values are kept, not deleted, so they are not rediscovered
the hard way.

Validated on the instrument:

| What | Result |
|---|---|
| STAR bring-up, channels and iSWAP homed, autoload skipped | passed |
| PTA/WGA single column, dry: lysis 3.0 uL source col1 to dest col1; reaction 6.0 uL source col3 to dest col1 | passed |
| iSWAP rail35 pos0 to HHS rail27 pos2, pickup +5.0 mm, drop x12.0 / y54.5 / z17.0 | passed |
| iSWAP return, HHS rail27 pos2 to rail35 pos0, pickup x12.0 / y54.5 / z9.0, drop z8.5 | passed |
| PTA/WGA full plate, dry: lysis and reaction, source col1 to dest cols 1-12, then iSWAP to HHS | passed |
| Repeatability: 3 consecutive single-column round trips, 6 of 6 iSWAP transfers clean, pickup landed at z 0.950 every time | passed |
| PTA/WGA wet single addition, discard tips | written, not yet run |

Inheco ODTC:

| What | Result |
|---|---|
| ODTC method XML matches TAS-068.5 Tables 1, 4, 5, 8, asserted against the real PyLabRobot backend | passed, off-instrument |
| `odtc_offline_checks.py`, 72 checks, on the Pi under PyLabRobot 0.2.1 | passed, off-instrument |
| Read-only probe and PyLabRobot bring-up (Reset, Initialize, sensor read) | passed on the instrument |
| ODTC door, block hold, thermal program | written, not yet run |
| STAR iSWAP handoff into the ODTC | not written, geometry not measured |

Reagent volumes are sourced from the ResolveDNA Whole Genome Single-Cell Core
Kit user guide (TAS-068.5): Lysis Mix 3.0 uL per reaction, Reaction Mix 6.0 uL
per reaction. The 7.0 uL p10 blowout is air, not liquid. It exists to expel the
full volume onto the well wall and does not change what is delivered. The ODTC
thermal programs come from the same document, Tables 1, 4, 5, and 8.

## Running

Scripts execute on the Pi that is wired to the instrument, not on a laptop. Each
tree carries a `run_on_pi.sh` that syncs it to its own run directory on the Pi
and runs a chosen script in the instrument virtualenv, without writing to the
Pi's own working directory.

```bash
./hamilton-star/run_on_pi.sh starlab_live/test_star_no_autoload.py
./instrument-integrations/run_on_pi.sh odtc/odtc_offline_checks.py
```

Long runs should be launched detached on the Pi, so that a dropped SSH session
cannot interrupt the arm mid-transfer, or a thermal program mid-cycle.

## Safety

Assume a script drives real hardware unless it says otherwise. The exceptions
are named: `--mode deck`, `--dry`, `odtc_offline_checks.py`, and
`01_odtc_probe_raw.py` are the only things here that cannot move or heat
anything.

- Never run unattended. A person watches the instrument with a hand near the
  E-stop.
- Run `--mode deck` first. It assigns the deck and prints geometry, no motion.
- Single-cell PTA discards tips and never returns them. Carryover is fatal to
  single-cell work. `--return-tips` is for water and dry rehearsals only.
- Only one process may drive an instrument at a time. Two clients racing for the
  STAR's USB interface produce `USBError: [Errno 16] Resource busy`. On the ODTC
  the collision is quieter: a second process re-registers the event receiver and
  silently steals the first one's callbacks.
- Anything that moves the ODTC door or heats its block requires
  `--confirm i-am-watching`. The block reaches 99 C and the lid 105 C, and both
  stay hot after a program ends.
- After any failure, reconcile the physical plate, tip, and deck state before
  rerunning. Do not kill a process mid-motion.

Lab-internal network addresses and credentials are not published here. The setup
notes carry placeholders.

## Status

Research use only. Not a product, not validated for diagnostic use.
