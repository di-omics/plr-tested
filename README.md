# plr-tested

PyLabRobot code that has been run on real hardware.

Most lab-automation code is written against a simulator and never touches an
instrument. This repo is the opposite. Everything here has been executed on a
physical machine, with a person watching the deck, and the run output is what
decided whether a value was right. Nothing graduates into this repo on the
strength of a simulation alone.

## What is here

- [`hamilton-star/`](hamilton-star) - protocols and validation scripts for a
  Hamilton Microlab STAR driven by PyLabRobot from a dedicated Raspberry Pi.
  ResolveDNA PTA/WGA and amplicon-seq liquid handling, iSWAP plate moves, and
  heater-shaker handoffs.

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
| PTA/WGA wet single addition, discard tips | written, not yet run |

Reagent volumes are sourced from the ResolveDNA Whole Genome Single-Cell Core
Kit user guide (TAS-068.5): Lysis Mix 3.0 uL per reaction, Reaction Mix 6.0 uL
per reaction. The 7.0 uL p10 blowout is air, not liquid. It exists to expel the
full volume onto the well wall and does not change what is delivered.

## Running

Scripts execute on the Pi that is wired to the instrument, not on a laptop.
`hamilton-star/run_on_pi.sh` syncs this repo to a dedicated run directory on the
Pi and runs a chosen script in the instrument virtualenv, without writing to the
Pi's own working directory.

```bash
./hamilton-star/run_on_pi.sh starlab_live/test_star_no_autoload.py
```

Long runs should be launched detached on the Pi, so that a dropped SSH session
cannot interrupt the arm mid-transfer.

## Safety

Every script here moves real hardware.

- Never run unattended. A person watches the deck with a hand near the E-stop.
- Run `--mode deck` first. It assigns the deck and prints geometry, no motion.
- Single-cell PTA discards tips and never returns them. Carryover is fatal to
  single-cell work. `--return-tips` is for water and dry rehearsals only.
- Only one process may drive the instrument at a time. Two clients racing for
  the USB interface produce `USBError: [Errno 16] Resource busy`.
- After any failure, reconcile the physical plate, tip, and deck state before
  rerunning. Do not kill a process mid-motion.

Lab-internal network addresses and credentials are not published here. The setup
notes carry placeholders.

## Status

Research use only. Not a product, not validated for diagnostic use.
