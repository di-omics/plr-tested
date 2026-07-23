# Tecan Infinite QC - Rhodamine B serial dilution on the STAR

Build the Rhodamine B absorbance/linearity QC plate for the Tecan Infinite on
the robot instead of pipetting the dilution series by hand. The plate follows
`instrument-integrations/tecan-infinite/doe-plate-map.html`.

## What it makes

A clear flat-bottom 96-well plate, rows A/B/C (triplicate), 2-fold serial
dilution across columns 1-11, column 12 blank, **100 uL in every well** so the
optical path length matches across the plate.

```
        1     2     3     4     5     6     7     8     9    10    11    12
  A/B/C 1x   1/2   1/4   1/8  1/16  1/32  1/64 1/128 1/256 1/512 1/1024 blank
```

## Deck

| Rail / pos      | Labware                                   |
|-----------------|-------------------------------------------|
| rail48 pos2     | p300 filter conductive tips (one full rack) |
| rail35 pos0     | destination QC 96WP (clear flat-bottom)   |
| rail35 pos1     | 12-well reservoir                         |

Reservoir wells: `A1` = Rhodamine B 1x working solution, `A2` = diluent
(water/PBS), `A12` = waste. Load `A1` with >= 1.2 mL and `A2` with >= 4.5 mL
(includes dead volume). Aim the col-1 (1x) target near OD 2-3 at 554 nm; err
dilute (see the DoE map notes).

### Same deck: the next step, plate normalization

The plate-normalization step (`../normalization/`, which reads a plate's per-well
concentration and adds per-well water to a common target) runs on the SAME deck
geometry as this prep: p300 tips at rail48 pos2, the work plate at rail35 pos0, the
12-well reservoir at rail35 pos1. Stage the carriers once; only the reservoir
contents and the plate change between the two steps.

| Rail / pos  | Rhodamine QC prep (this script) | Plate normalization (next) |
|-------------|---------------------------------|----------------------------|
| rail48 pos2 | p300 tips (one full rack)       | p300 tips (one tip is reused) |
| rail35 pos0 | destination QC plate (built here)| the sample plate to normalize |
| rail35 pos1 | reservoir: A1 dye, A2 diluent, A12 waste | reservoir: A1 water (>= 5 mL for a full plate) |

So a run of this prep leaves the deck already staged for normalization: swap the
plate at pos0 for the sample plate, and reload the reservoir with water in A1. The
normalizer's geometry (reservoir aspirate, work-plate XY) is inherited from this
script; only its dispense-from-above height is new and needs a dry tune. See
`../normalization/README.md` for its run cards and the protocol values to pin.

## Method

1. **diluent** - 100 uL diluent into cols 2-12, rows A-C.
2. **dye** - 200 uL Rhodamine 1x into col 1, rows A-C (seeds the chain).
3. **serial** - 10 transfers of 100 uL, col 1 -> 2 -> ... -> 11, mixing each
   destination 5x (80 uL, tunable with `--mix-cycles`), fresh tips per step.
   After col 10 -> 11, discard 100 uL from col 11 to waste so col 11 also lands
   at 100 uL.

Every dilution well briefly holds 200 uL mid-step (100 diluent + 100 transfer);
the plate well useful volume is ~300 uL, so this is within range. Tips: one full
300 uL rack is consumed exactly - rack col 1 for diluent, col 2 for dye, cols
3-12 for the ten serial steps (fresh tips per step for dilution accuracy).

## Status

**Dry-validated on the instrument 2026-07-16 (starpi). Not wet.** The full build
ran clean end to end with the in-well firmware Mix, verified leg by leg rather
than by exit code. The geometry is no longer an estimate for the dry case: the
p300 heights and the targeted PCR-derived XY held across plate columns 1-11 on the
first clean pass. It is still motion only: empty wells, so the mix cycled air and
no gradient was made.

| What | Result |
|------|--------|
| Chatterbox sim, `--mode deck` / `serial` / `all`, PLR 0.2.1 | passed, off-instrument |
| `--mode deck` on the instrument (assignment only) | passed on the instrument |
| Dry build, `--mode all --return-tips`: diluent 11/11, dye 1/1, serial 10/10, in-well mix 10/10 (50 cycles), discard 1/1, 0 faults, 0 Z errors | passed on the instrument |
| Lid on, iSWAP rail35 pos4 -> pos0, pickup z+9 / drop z+18 | passed on the instrument |
| Tecan tray opened and left open (reader on starpi), open 5.3 s | passed on the instrument |
| Real Rhodamine build (wet) | written, not yet run |
| Reader go/no-go on a built plate | blocked, see below |

Two things a wet run needs that the dry run did not:

- **A fresh full p300 rack.** Discard mode advances rack column 3 -> 12, and the
  rack at rail48 pos2 currently only carries tips in columns 1-9. The first dry
  attempt died exactly there (NoTipError, all three channels, at serial step 8).
  The dry run now reuses one rack column, so it no longer notices.
- **The reader cannot read yet.** Absorbance is blocked upstream: this unit
  deterministically times out at `ABSOLUTE MTP,Y=` in `run_scan`, so no scan and
  no wells. Building the plate does not depend on that; reading it does.

Note on hardware location: the reader was on `starpi2` on 2026-07-16 per the repo
README, but it is now physically on **starpi** (verified: `lsusb` shows both
`08af:8000` STAR and `0c47:8007` TECAN on starpi). `starpi2` was unreachable
(host down). Run the Tecan scripts with `VENV=/home/lab/tecan-lab/env` and the
default `PI=starpi`.

## Run cards

Sim first, off-instrument (no hardware, from anywhere with PLR 0.2.1):

```bash
python3 01_rhodamine_serial_dilution_qc.py --sim --mode all --return-tips
```

On the instrument, from `hamilton-star/` (human at the E-stop, one process only):

```bash
# 1. deck assignment only, NO motion - confirm the deck matches reality
./run_on_pi.sh protocols/bio_validation0/tecan_qc/01_rhodamine_serial_dilution_qc.py --mode deck

# 2. dry-tune the geometry, step by step, tips returned, water in the reservoir.
#    Watch each motion; adjust the P300_* constants in the script between runs.
./run_on_pi.sh protocols/bio_validation0/tecan_qc/01_rhodamine_serial_dilution_qc.py --mode diluent --return-tips
./run_on_pi.sh protocols/bio_validation0/tecan_qc/01_rhodamine_serial_dilution_qc.py --mode dye     --return-tips
./run_on_pi.sh protocols/bio_validation0/tecan_qc/01_rhodamine_serial_dilution_qc.py --mode serial  --return-tips

# 3. full dry build with water, tips returned
./run_on_pi.sh protocols/bio_validation0/tecan_qc/01_rhodamine_serial_dilution_qc.py --mode all --return-tips

# 4. real build with Rhodamine (discards tips; only after the dry ladder is clean)
./run_on_pi.sh protocols/bio_validation0/tecan_qc/01_rhodamine_serial_dilution_qc.py --mode all
```

## After the build

Hand the plate to the reader go/no-go in `instrument-integrations/tecan-infinite/`:

```bash
VENV=/home/lab/tecan-lab/env ./run_on_pi.sh tecan-infinite/07_tecan_raw_absorbance.py \
  --confirm i-am-watching --preloaded --wavelength 554 --wells A1,A12
```

If A1 (1x dye) reads clearly below A12 (blank), the reader senses absorbance.
Full calibrated OD reads are still blocked upstream on the 20-byte calibration
frame (PyLabRobot issue #1093); the go/no-go and the dilution build do not depend
on that fix.

## Simulator

Two self-contained visual simulations of this build (matching house style). The
plate fills column by column into the 2-fold gradient (col 1 = 1x to
col 11 = 1/1024, col 12 blank), with the mix-cycles knob wired to `--mix-cycles`.
Both are previews only and do not drive the instrument.

- `rhodamine-dilution-app.html` - phone layout, single column. Open in any
  browser or add it to a phone home screen.
- `rhodamine-dilution-app-desktop.html` - desktop console: big plate hero, a
  four-phase tracker, and a live series readout (the 11 concentrations lighting
  up 1x to 1/1024). For a laptop or projector.

## Safety

These scripts move real hardware. `--mode deck` is the only motion-free mode.
Dry-run on the chatterbox backend and run `--mode deck` on the instrument before
any liquid handling. Never run unattended. Only one process may drive the STAR at
a time. `Y = 3.20` in a plate XY offset is blacklisted repo-wide (trips the
<9 mm adjacent-channel spacing error); keep `P300_PLATE_XY` Y above it.
