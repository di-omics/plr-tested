# Suggestion note: computer vision -> autonomous iSWAP handoffs

Status: forward-looking design note, not implemented. Written 2026-07-12 after a
manual iSWAP tuning session (plate drop into the ODTC nest + lidding the plate).

## The problem, stated plainly

Every offset in the committed iSWAP scripts was found by a human-in-the-loop
visual feedback loop:

    robot fires a move -> a person eyeballs the result ("too low", "5 mm left",
    "the lid was shifted") -> a person hand-edits an offset -> repeat.

That is how `test_iswap_plate_rail35pos0_to_odtc_variable.py` got its
`x2 / y36.5 / z12` and how `test_iswap_lid_variable.py` got its lid
`pickup +9 / drop +18`. It works, but:

- it is slow (many reps per move, each needing a person at the E-stop),
- it does not generalize (every new nest, plate type, or lid re-tunes from scratch),
- it blocks unattended runs (no move can be trusted without a watcher),
- firmware `SUCCESS` only means "motion completed", not "plate/lid actually seated".

This is a control problem with a missing sensor. Today the person IS the sensor.
Vision replaces the person in the loop.

## What the vision stack does today

`tools/vision/` is OFFLINE and OBSERVATIONAL: GoPro video -> `extract_frames.py`
-> `make_contact_sheet.py` -> hand-drawn deck ROIs (`example_roi_config_star.json`)
-> `analyze_roi_motion.py` (per-ROI brightness + frame-to-frame absdiff) ->
`vision_dashboard_summary.py`. Good for post-hoc QC of a run. It is not real-time,
not pose-aware, and not in the control loop (the README says to keep it separate
from active protocol scripts until validated).

The gap to close: offline ROI motion  ->  real-time, pose-aware, in-loop perception.

## Concrete CV capabilities mapped to the failures we actually hit

| Today's failure (and the manual fix) | CV capability | What it automates |
| --- | --- | --- |
| Hand-tuned drop offsets ("a bit lower", "drop +18") | Visual residual + servoing: detect plate/lid pose vs the target nest, compute the dx/dy/dz residual, apply it as the offset | Removes "a bit lower" - the loop closes itself |
| "The lid was shifted" -> missed pickup | Pre-pickup presence + pose check at the source slot | Catches a shifted/misplaced item before committing a grip |
| "Empty pos4 after a success" -> every-other-run miss | Source-slot occupancy check | No more picking at an empty slot (the move carries the lid away) |
| Z-drive "drive locked" from too-low grip | Labware-top height estimate (depth or known-geometry monocular) | Seeds pickup-z so the arm never drives into the plate |
| Firmware "SUCCESS" != seated | Post-drop seating verification (flush in nest? lid fully on?) | A real success/failure signal, enabling auto-retry and unattended runs |

## Sensing options, cheapest-and-most-robust first

1. Fiducial markers (ArUco / AprilTag). A tag on each carrier slot and on the
   labware/lid corners plus one on the iSWAP gripper gives direct 6-DoF pose with
   no ML training and sub-mm accuracy at bench distances. This is the highest-ROI
   first step and it directly measures the exact x/y/z residual we hand-tuned.
2. Eye-in-hand camera on the iSWAP. Sees the grip and drop point up close. This is
   exactly the plr-lr Phase 2 "eye-in-hand vision" work; this note is its killer app.
3. Fixed overhead camera. The GoPro already in use, upgraded from record-only to
   live frames + detection (reuse the ROI config as a prior).
4. Depth (cheap ToF or stereo module) for the z axis specifically - z is the
   variable that caused the Z-drive crash and that monocular vision estimates worst.

## Phased path (each phase is useful on its own and low-risk-first)

- Phase 0 (free, now): the scripts already print target absolute coordinates; log
  them alongside the human offset decisions to build a labeled eval set
  ("given this frame, the correct residual was dx/dy/dz").
- Phase 1 - pre-flight check (read-only, no control risk): fiducial presence + pose
  at source and dest before every move; abort with a clear message on mismatch.
  This alone kills the "shifted lid" and "empty slot" failure modes.
- Phase 2 - closed-loop offset: measure the residual and feed it back as the
  offset automatically (visual servoing on the drop and the pickup). Replaces the
  human "a bit lower" tuning entirely.
- Phase 3 - post-move seating verification: a true seated/not-seated signal ->
  auto-retry on failure -> unattended runs become trustworthy.
- Phase 4 - self-calibration: a new nest, plate, or lid tunes itself with no human
  first-pass; the ODTC round trip (including the still-unconfirmed return leg)
  converges on its own.

## Why this fits the portfolio

This is the feedback-control -> QC -> autonomy through-line made literal: today a
human closes the loop by eye; vision turns that into a real sensor inside a control
loop. It ties `tools/vision/` (observation) + plr-lr Phase 2 (eye-in-hand vision) +
`plr-tested` (validated moves) into one self-tuning DBTL-style handoff.

## Smallest experiment that proves it is closeable

Put one fiducial on rail35 pos0 and one on the iSWAP gripper, use the existing
overhead camera, and run the known-good plate drop. Then deliberately introduce a
known offset (say +5 mm in x) and confirm the vision system measures that +5 mm
residual back out. If the measured residual reproduces the offsets we hand-tuned by
eye (plate x2/y36.5/z12; lid +9/+18), the sensor is trustworthy and the loop can be
closed. That is a one-afternoon test with no new robot risk.
