# EM-seq STAR dry-choreography QC

Physical Hamilton STAR evidence for the one-column NEBNext EM-seq v2 + UltraShear
choreography, recorded 2026-07-21. The judgment is deliberately narrow:

**PASS — physical dry motion only. Wet transfers, ODTC heating, timed cleanup holds,
and biological performance remain unvalidated and blocked.**

## Run record

| Field | Record |
| --- | --- |
| Source branch | `emseq-v2-ultrashear-package` |
| Source commit | `c375117` (`emseq: match working AmpSeq liquid geometry`) |
| Instrument | Hamilton STAR, driven from the instrument Raspberry Pi |
| Runner | `starlab_live/emseq/run_emseq_odtc_1col_full_dry.py` |
| Completion | 2026-07-21 18:08:19 PDT |
| Raw log | [`emseq_full_dry_c375117_2026-07-21.log`](emseq_full_dry_c375117_2026-07-21.log) |
| Raw-log SHA-256 | `98eab846dc52236d1b2a1642f71266866de2e52099f6a03b4a066f992105c763` |
| Raw-log size | 1,231 lines; 62,287 bytes |
| Program result | 36 of 36 ordered legs completed; 37 top-level `SUCCESS:` markers including the final runner marker; no traceback, USB error, exception, or failed command |
| Final program state | Work plate returned to rail35 p0; ODTC and magnet round trips complete |
| Operator record | Human remained at the instrument and reported that the observed run went well, then authorized this GitHub record |

The exact hardware command was:

```bash
/home/lab/star-lab/env/bin/python -u \
  starlab_live/emseq/run_emseq_odtc_1col_full_dry.py \
  --confirm RUN_EMSEQ_ODTC_FULL \
  --labware-ack CELLTREAT_229195_WORK_SOURCE
```

The run used the staged empty deck documented in the parent README: CellTreat 350 uL
work and source plates, p10/p50/p300 filter tips, the rail35 p2 magnet, the dry 12-well
trough, and the open ODTC nest at rail20 p1. Tips were returned for observation.

## What passed

- All 11 reagent-add modes on the real STAR backend.
- All three SPRI cleanup motion presets: post-ligation, post-TET2, and post-PCR.
- Eight complete work-plate/ODTC round trips using the inherited Targeted PCR iSWAP geometry.
- Three complete work-plate/magnet round trips.
- The largest p50 command, 45 uL PCR master mix, completed using the AmpSeq-matched
  0.0 mm source and 1.5 mm destination heights.
- The final plate self-returned to rail35 p0 and the runner exited normally.

## What this does not prove

- The deck was empty/dry. This run does not establish delivered-volume accuracy,
  submergence, splash behavior, withdrawal behavior, or liquid-class performance.
- ODTC commands were printed as notes only. No EM-seq thermal program, heated-lid move,
  temperature hold, or cool-down was executed.
- Cleanup incubation, bead-pelleting waits, air-dry timing, and clear-eluate transfer are
  still operator/off-deck steps and were not timed or validated here.
- No 10x mixing, low-input carrier-DNA step, sequencing control, library QC, or biological
  acceptance criterion was exercised.
- This is not a wet-run release and not diagnostic validation. The product-layer hardware
  guard must remain closed until the measured qualification items are resolved.

The raw log starts with the static pre-run banner from source commit `c375117`, which
says the choreography had not yet run on hardware. That statement was true when the
commit was created and became stale only after this successful run. The log is retained
byte-for-byte rather than rewritten; its SHA-256 above authenticates the captured evidence.
