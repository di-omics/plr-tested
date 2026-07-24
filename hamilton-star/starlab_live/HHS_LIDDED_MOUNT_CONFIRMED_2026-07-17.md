# HHS lidded plate mount - CONFIRMED on hardware 2026-07-17

First REAL-PLATE mount of the work plate onto the Hamilton Heater Shaker
(rail35 pos0 <-> rail27 pos2) with a robot-placed lid, walked in live with an EMPTY
sacrificial plate and a hand on the E-stop.

## Confirmed geometry (iSWAP drop offsets, mm)

| move | pickup-z | drop X | drop Y | drop Z |
|------|----------|--------|--------|--------|
| PLATE  rail35 pos0 -> rail27 pos2 | 5.0 | 12.0 | 45.5 | 17.0 |
| LID    rail35 pos4 -> rail27 pos2 | 9.0 | 12.0 | 45.5 | 17.0 |

The lid seats flush on the plate ONLY when both share the same drop-Y. The plate and lid
drop-Y must always match; Z=17 is the plate-Z at which the lid seats clean.

Commands (attended; run --mode deck FIRST - it homes the arm, prints coords, no transfer):

    ./run_on_pi.sh starlab_live/test_iswap_plate_rail35pos0_to_rail27_variable.py --mode move \
      --drop-position 2 --pickup-z-offset-mm 5.0 \
      --drop-x-offset-mm 12.0 --drop-y-offset-mm 45.5 --drop-z-offset-mm 17.0 \
      --confirm RUN_ISWAP_PLATE_TEST

    ./run_on_pi.sh starlab_live/test_iswap_lid_variable.py --mode move \
      --src-rail 35 --src-pos 4 --dst-rail 27 --dst-pos 2 --pickup-z-offset-mm 9.0 \
      --drop-x-offset-mm 12.0 --drop-y-offset-mm 45.5 --drop-z-offset-mm 17.0 \
      --confirm RUN_LID_MOVE

## What this corrects

The repo's prior HHS drop `x12 / y54.5 / z17`, marked "passed" in the root README table and
endorsed by ISWAP_HHS_RAIL27_POS2_TUNING.md, was NEVER real-plate seat-checked. Those passes
were DRY / EMPTY sacrificial plate: they validated transfers COMPLETING and pickup-Z
repeatability, not drop-XY nest seating. The CAMERA round trip
(run_full_wgs_prep_hhs_return_pcr_enrichment_CAMERA.py) drops forward at y54.5 and re-picks the return at
the SAME y54.5, so a constant Y bias is invisible - the plate is re-grabbed wherever it
landed. The first real-plate mount landed ~2 rows too far +Y. Correct drop-Y is 45.5 (not
54.5, not the demo default 47.5, not an earlier eyeball estimate of ~18.5). Keep Z=17.

## NOT yet done (do not assume)

- LID-OFF (delid) at the HHS is NOT tuned. The lid and plate share footprint 127.76 x 85.48,
  so a too-low delid pickup grabs the PLATE and strands it (reports SUCCESS). Start HIGH
  (~z16) and walk down attended; never fire it blind.
- The HHS return leg (test_iswap_plate_rail27pos2_hhs_to_rail35pos0_return.py) is UNGATED
  (no --mode / --confirm) and defaults to the stale A-family offsets - re-plate + re-check
  before chaining it.
- No wet run.
