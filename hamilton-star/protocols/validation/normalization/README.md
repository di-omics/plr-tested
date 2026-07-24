# Plate normalization on the STAR (dilute-in-place with water)

Read a plate's per-well dsDNA concentration (fluorescent dsDNA assay), then add a different
volume of water to each well so every well reaches ONE common target
concentration. No sample is moved, so the final volume differs per well: a
more-concentrated well takes more water and ends up fuller.

This is the operator's chosen model. It is NOT the transfer-to-a-fresh-plate
normalization in `di-omics/plr-epigenome` (which fixes the final volume and moves
both sample and water). Dilute-in-place is simpler (water-only) but cannot
concentrate a dilute well and cannot exceed the well's volume.

## Files

- `normalize_plan.py` - pure math, no hardware. Standard curve (RFU -> ng/uL),
  the water-add solver, the never-invent provenance guard. Unit-tested.
- `test_normalize_plan.py` - `python3 test_normalize_plan.py` (all pass).
- `normalize_plate.py` - the STAR executor + concentration sources + CLI.

## What the math does

```
mass conserved:  C_i * V0_i = Ct * (V0_i + water_i)
water_i = V0_i * (C_i / Ct - 1)          final_volume_i = V0_i * C_i / Ct
```

Per-well status:

| status | meaning | action |
|---|---|---|
| `ok` | hit the target exactly | add the computed water |
| `below_target` | conc <= target, cannot concentrate | carried neat, flagged (operator's choice) |
| `min_vol_clamped` | water add is below the reliable minimum | clamp to min (default) or skip |
| `exceeds_capacity` | target needs more volume than the well holds | fill to capacity, flagged, still above target |
| `empty` | conc <= 0 | nothing added |

## Status

**Written 2026-07-16. NOT run on hardware.** The planner math is unit-tested and
the STAR motion is chatterbox-clean on PLR 0.2.1.

| What | Result |
|------|--------|
| Planner unit tests (`test_normalize_plan.py`) | passed, off-instrument |
| `--mode plan` (compute + print, no hardware) | passed, off-instrument |
| `--mode sim` (STAR chatterbox), 80 wells, per-well distinct volumes | passed, off-instrument; firmware `dv` differs per well |
| `--mode deck` on the instrument | not yet run |
| Dry motion, `--return-tips`, `--demo` | not yet run |
| Real normalization from a real read | blocked, see below |

**This is the first script in the repo to dispense a distinct volume per well.**
Every validated transfer so far is one volume x N channels. The chatterbox proves
the firmware carries the per-well volumes; it does not prove the geometry. Two
things are new and untuned:

- **Dispense-from-above height** (`PLATE_DSP_ABOVE_HEIGHT`, default 9.0 mm). The
  motion is single-channel, one reused tip, dispensing above the liquid so the tip
  never touches sample (water is clean, so one tip serves the whole plate). That
  height is not the validated near-bottom 1.5 mm and must be tuned dry.
- **Per-well variable volume** as a motion. Prove it dry before any wet run.

## Blocker: the read

The fluorescent dsDNA assay uses an operator-profile-defined fluorescence configuration. The Tecan's fluorescence path
has never completed a read: `_configure_fluorescence` issues its config twice
before `PREPARE REF` (upstream `infinite_backend.py`, comment "UI issues the
entire FI configuration twice before PREPARE REF" above `for _ in range(2)`),
desyncing the USB stream. Absorbance is single-pass, which is why absorbance now
scans on starpi and fluorescence does not.

So until fluorescence is brought up, feed concentrations from a captured CSV or the
demo set. The absorbance MTP,Y timeout vanished when the reader moved to starpi, so
whether the fluorescence double-config actually bites on starpi is worth a cheap
test before assuming.

## Protocol values you MUST pin (never invented here)

A `--mode run` refuses to start while any of these is unset. Confirm each against
your assay, not from a default:

- `--target` common target concentration (ng/uL). No default.
- `--start-volume` starting volume already in each well (uL). No default.
- `--min-transfer` smallest water add the chosen tip dispenses reliably on THIS
  instrument (uL). A calibration value.
- `--well-capacity` useful well volume (uL). Default 300 (CellTreat 350 Fb); confirm.
- for a real read: fluorescent dsDNA assay standard series, `--assay-dilution`, assay ex/em - all
  currently tunable placeholders in the assay-validation package, confirm against the insert.

## Run cards

Off-instrument (no hardware, from anywhere with PLR 0.2.1):

```bash
python3 test_normalize_plan.py                      # the math
python3 normalize_plate.py --mode plan --demo \
    --target 2.0 --start-volume 20.0 --min-transfer 1.0     # see the plan
python3 normalize_plate.py --mode sim --demo \
    --target 2.0 --start-volume 20.0 --min-transfer 1.0 --return-tips   # the motion
```

On the instrument, from `hamilton-star/` (human at the E-stop, one process only):

```bash
# 1. deck assignment, no motion
./run_on_pi.sh protocols/validation/normalization/normalize_plate.py \
    --mode deck --demo --target 2.0 --start-volume 20.0 --min-transfer 1.0

# 2. dry motion proof, tips returned, demo concentrations, water in the reservoir.
#    Watch the dispense-from-above height; tune PLATE_DSP_ABOVE_HEIGHT between runs.
./run_on_pi.sh protocols/validation/normalization/normalize_plate.py \
    --mode run --demo --target 2.0 --start-volume 20.0 --min-transfer 1.0 --return-tips

# 3. real normalization: feed measured concentrations, discard tips
./run_on_pi.sh protocols/validation/normalization/normalize_plate.py \
    --mode run --conc-csv my_concs.csv \
    --target <ng/uL> --start-volume <uL> --min-transfer <uL>
```

Concentration source formats:

```
--conc-csv   rows: well,conc_ng_per_ul     (e.g. A1,4.2)
--rfu-csv    rows: well,rfu    assay calibration is loaded from PLR_METHOD_PARAMETERS_FILE
--demo       synthetic spread, dry proof only, NOT a real read
```

## Deck

| Rail / pos | Labware |
|---|---|
| rail48 pos2 | p300 filter conductive tips |
| rail35 pos0 | sample plate to normalize (concentrations were read from this plate) |
| rail35 pos1 | reservoir; `A1` holds the diluent water |

Geometry inherited from the dry-validated rhodamine script (reservoir aspirate, and
the work-plate XY where Y must stay > 3.20). The dispense height is the one new
value.
