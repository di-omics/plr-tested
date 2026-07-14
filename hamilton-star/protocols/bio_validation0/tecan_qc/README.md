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

**Written, not yet run on hardware.** Simulation-clean under the STAR chatterbox
backend on PyLabRobot 0.2.1 (the Pi's version): `--mode deck`, `serial`, and
`all` all complete without error, all 12 rack columns accounted for. The
geometry (aspirate/dispense heights, XY offsets) is a **starting estimate**
seeded from the validated ampseq work-plate dispense and the validated cleanup
trough/waste geometry. It has **not** been tuned against this deck. Do not wet-run
until the dry ladder below has been watched on the instrument.

| What | Result |
|------|--------|
| Chatterbox sim, `--mode deck` / `serial` / `all`, PLR 0.2.1 | passed, off-instrument |
| `--mode deck` on the instrument (assignment only, no motion) | not yet run |
| Dry motion, water, `--return-tips` (geometry tune) | not yet run |
| Real Rhodamine build | not yet run |

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

## Safety

These scripts move real hardware. `--mode deck` is the only motion-free mode.
Dry-run on the chatterbox backend and run `--mode deck` on the instrument before
any liquid handling. Never run unattended. Only one process may drive the STAR at
a time. `Y = 3.20` in a plate XY offset is blacklisted repo-wide (trips the
<9 mm adjacent-channel spacing error); keep `P300_PLATE_XY` Y above it.
