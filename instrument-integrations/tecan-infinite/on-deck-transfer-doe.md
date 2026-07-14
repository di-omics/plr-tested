# On-deck integration DoE: does the iSWAP transfer a plate to the reader?

The first bench test for putting the Tecan within iSWAP reach. It is **decoupled from the
reader**: prove the arm can pick a plate and place it at the reader's landing coordinate,
and take it back, repeatably, BEFORE the reader is committed to the deck. Use a plate carrier
at the rail nearest the reader as a stand-in landing; refine to the reader's drawer position
once that is measured.

Script: `hamilton-star/starlab_live/test_iswap_plate_deck_to_landing_variable.py` (+ a return
twin, landing -> deck, once the forward leg is tuned).

## Objective and go / no-go

Prove: **pick -> move -> place -> retrieve, clean, 3 of 3 round trips, pickup Z deterministic.**
If any leg fouls (misgrip, collision, plate not seated), stop, reconcile, retune. Known-bad
offsets stay in the comment block so they are not rediscovered.

## Hard constraints (verified specs - do not design past these)

- iSWAP safe traverse is **~145 mm above the deck** (absolute finger ceiling ~173 mm). The
  landing nest must sit **at or below ~145 mm**. This is why the reader is recessed.
- iSWAP reaches only **~90 mm off the deck edge** (left; ~20 mm right). The landing must be
  within that band, so the reader body sits off-deck and only its carrier presents into it.
- Carrier max load is **100 g**: the arm must fully release and be support-free before it
  retracts. It cannot press down on the nest.
- Plate <= **23 mm** including lid. Fixture the landing **rigidly** (bolt/dowel) so the taught
  coordinate does not drift; the reader self-centers on chamfered edges only within ~1.2 mm.
- iSWAP has **no collision awareness**: define keep-out zones and verify the path by hand.

## The test ladder (do not skip)

| Rung | Command | Touches | Settles |
| --- | --- | --- | --- |
| 1. deck check | `... --mode deck --source-rail 35 --landing-rail R` | nothing | landing coordinate prints; confirm Z <= ~145 mm and XY in reach |
| 2. dry transfer | `... --mode move ... --confirm RUN_ISWAP_LANDING_TEST` | the arm | one clean pick -> place -> (pause) -> pick -> return; tune geometry |
| 3. repeatability | rung 2, x3 | the arm | 3 of 3 clean, pickup Z lands identically |

`--mode deck` first, always. Empty sacrificial plate. One process on the STAR USB. Watch it.

## Geometry variables to tune (the DoE factors)

| Variable | Flag | Start | Tune toward |
| --- | --- | --- | --- |
| landing rail | `--landing-rail` | the rail nearest the reader | plate centered over the nest |
| pickup Z clearance | `--pickup-z-offset-mm` | 5.0 (worked for the HHS) | just clears the plate off the source |
| drop X / Y | `--drop-x-offset-mm` / `--drop-y-offset-mm` | 0.0 | plate lands centered on the nest |
| drop Z | `--drop-z-offset-mm` | 12.0 (conservative, high) | plate seats flat, released, no slam |
| plate orientation | (physical) | A1 to the nest's keyed corner | so a later read matrix maps to the right wells |

Change **one** offset at a time, in small steps, and re-run rung 2. That is the whole method.

## Commands

```bash
# rung 1 - geometry only, no motion:
./run_on_pi.sh starlab_live/test_iswap_plate_deck_to_landing_variable.py --mode deck \
    --source-rail 35 --landing-rail 20

# rung 2 - the transfer (empty plate, watched):
./run_on_pi.sh starlab_live/test_iswap_plate_deck_to_landing_variable.py --mode move \
    --source-rail 35 --landing-rail 20 --pickup-z-offset-mm 5.0 --drop-z-offset-mm 12.0 \
    --confirm RUN_ISWAP_LANDING_TEST
```

## What this de-risks

Once pick -> place -> retrieve is clean and repeatable to a fixed landing, the reader just
inherits that coordinate: swap the stand-in carrier for the reader's recessed drawer at the
same rail/x/y/z, and fold the read between the legs (open -> place -> close -> read -> open ->
retrieve -> close). The transfer geometry is the hard part; proving it here means the reader
integration is mostly plumbing.
