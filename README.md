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
  whole-genome sequencing and targeted PCR liquid handling, iSWAP plate moves, and
  heater-shaker handoffs.
- [`instrument-integrations/`](instrument-integrations) - the instruments the
  STAR hands plates to, driven from the same Pi. The Inheco ODTC (On Deck Thermal
  Cycler) over SiLA/SOAP: the whole-genome sequencing thermal programs as PyLabRobot protocols,
  and a ladder of scripts from reachability to a PCR run, run on the instrument.
  And the Tecan Infinite plate reader over USB: the library-QC endpoint, a plan and
  a script ladder from a USB probe to a Rhodamine-B fluorescence read, not yet run.
- [`packages/`](packages) - self-contained, QC-gated assay products built on the
  validated hardware work above. Each takes a sparse manifest to a gated, auditable
  dossier, is standard-library at the core so it runs at a partner site, and is
  simulation-first so the whole flow runs before an instrument is touched.
  - [`immunoassay-automation/`](packages/immunoassay-automation) - ELISpot and plate-
    immunoassay automation across a BioTek EL406 washer, an Opentrons Flex, and a spot
    imager. See its [WALKTHROUGH.md](packages/immunoassay-automation/WALKTHROUGH.md).
  - [`gene-edit/`](packages/gene-edit) - QC-gated whole-genome amplification + targeted PCR for confirming
    gene edits.
  - [`iswap-move/`](packages/iswap-move) - STAR iSWAP plate-lid moves.

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
| whole-genome sequencing single column, dry: lysis 3.0 uL source col1 to dest col1; reaction 6.0 uL source col3 to dest col1 | passed |
| iSWAP rail35 pos0 to HHS rail27 pos2, pickup +5.0 mm, drop x12.0 / y54.5 / z17.0 | passed |
| iSWAP return, HHS rail27 pos2 to rail35 pos0, pickup x12.0 / y54.5 / z9.0, drop z8.5 | passed |
| whole-genome sequencing full plate, dry: lysis and reaction, source col1 to dest cols 1-12, then iSWAP to HHS | passed |
| Repeatability: 3 consecutive single-column round trips, 6 of 6 iSWAP transfers clean, pickup landed at z 0.950 every time | passed |
| whole-genome sequencing wet single addition, discard tips | written, not yet run |

Inheco ODTC:

| What | Result |
|---|---|
| ODTC method XML matches the kit user guide Tables 1, 4, 5, 8, asserted against the real PyLabRobot backend | passed, off-instrument |
| `odtc_offline_checks.py`, 72 checks, on the Pi under PyLabRobot 0.2.1 | passed, off-instrument |
| Bring-up, block hold to 45.00 C, full cycling profile to 50.00 C, `PlateauTime` = seconds | passed on the instrument |
| `ampseq-pcr1`: 30 real PCR cycles, 36.6 min, setpoints held to a mean 0.27 C | passed on the instrument (98 C denaturation grazes the 99 C ceiling; see odtc README) |
| Full lidded targeted PCR choreography with the ODTC **called live** at both thermal legs: 13 motion legs, 22 SUCCESS, 0 failures, deck self-returned | passed on the instrument |
| ODTC Reset + Initialize with a plate and lid seated in the nest | benign, proven on the instrument |
| The two thermal programs run **inside** the choreography (`--thermocycle`) | written, reached STEP 2t clean, stopped in pre-warm on purpose; not yet run to completion |
| A the kit user guide program run at real temperatures; ODTC door move | written, not yet run |
| STAR iSWAP handoff into the ODTC | forward and return geometry tuned on hardware; passed in the full lidded choreography |

Tecan Infinite 200 PRO (first contact 2026-07-11 read-only; stage first moved 2026-07-16
from `starpi2`, the second Pi, which is where the reader now lives):

| What | Result |
|---|---|
| `tecan_offline_checks.py`, 24 checks, backend shape and 96-well geometry, no device | passed on both Pis |
| USB probe of `0c47:8007`: identified as "TECAN AUSTRIA BIO", no kernel driver | passed on the instrument (read-only) |
| Bring-up (`INIT FORCE`), stage homes | passed on the instrument, from `starpi2`. This unit rejects `ABS #BEAM DIAMETER` with `ERR1:Command is not valid`, so absorbance runs on the hardcoded 700 fallback |
| Tray cycle, open and close, timed | passed on the instrument, from `starpi2`. Five clean cycles. Close is stable at 3.6 s on all five; open is bimodal, 3.2 s from a settled stage and 5.3 s when a failed read has left the stage parked mid-scan. It tracks stage position, not the plate. Budget the worst case |
| Absorbance read of a known plate; `counts_per_mm` confirmed on this unit | **failed on the instrument, from `starpi2`.** Deterministic `TimeoutError`, 2 of 2, at `ABSOLUTE MTP,Y=` in `run_scan`. The reader never answers the Y-stage command, so no scan and no wells. This is **not** the 20-byte calibration bug, which is a decode failure downstream of a scan that streams. `counts_per_mm` is blocked behind it. See the tecan-infinite README |
| Rhodamine-B fluorescence ladder read | written, not yet run |
| STAR iSWAP handoff into the reader tray | not started |

Reagent volumes are sourced from the whole-genome Single-Cell Core
Kit user guide (the kit user guide): Lysis Mix 3.0 uL per reaction, Reaction Mix 6.0 uL
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
- Single-cell whole-genome amplification discards tips and never returns them. Carryover is fatal to
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
