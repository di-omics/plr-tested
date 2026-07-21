# Targeted PCR + ODTC lidded single-home dry validation - 2026-07-21

Research use only.

## Run identity

- Date: 2026-07-21
- Completion observed: 11:39 PDT
- Git commit: `d0840852d669db59003beb08c71565cf0ccf829c`
- PyLabRobot: 0.2.1 release lock passed on `starpi`
- Runner: `run_ampseq_odtc_LIDDED_1col_full_v2_singlehome_dry.py`
- Mode: physical STAR, continuous single-session dry run
- Scope: empty sacrificial labware, one column, tips returned
- ODTC control: none; no connection, initialization, door command, or heating

## Pre-release evidence

- Dedicated Targeted PCR regression suite: 12 tests passed.
- Combined guarded whole-genome amplification/AmpSeq suites: 46 tests passed.
- Pi-side connection-free deck preview: exit 0.
- Pi-side full Chatterbox: exit 0.
- Pi-side normalized iSWAP trace: 20 of 20 `C0PP`/`C0PR` commands matched
  the hardware-proven standalone Targeted PCR component stream exactly.
- No competing STAR Python driver was present immediately before release.

## Physical command

```bash
./run_on_pi.sh starlab_live/run_ampseq_odtc_LIDDED_1col_full_v2_singlehome_dry.py \
  --mode star \
  --confirm RUN_AMPSEQ_ODTC_LIDDED_SINGLEHOME_DRY \
  --acknowledge R48_P10_P50_P300_R35_WORK_SOURCE_MAGNET_TROUGH_LID_R20_ODTC_EMPTY_OPEN \
  --labware-ack CELLTREAT_229195_WORK_SOURCE_CORNING_3603_LID
```

## Machine result

The command completed without a reported exception and printed the success
message only after the success-only iSWAP park and STAR stop path completed.
The USB connection then closed cleanly.

All 13 protocol legs executed in one setup/deck/session:

1. PCR1 master-mix dry transfer, p50 column 1.
2. Work plate rail35 pos0 to ODTC nest rail20 pos1.
3. PCR1 lid on.
4. PCR1 lid off.
5. Plate return to rail35 pos0.
6. Plate forward to magnet rail35 pos2.
7. Eight-workflow dry cleanup rehearsal.
8. Plate return from magnet to rail35 pos0.
9. PCR2 master-mix dry transfer, p50 column 2.
10. Work plate rail35 pos0 to ODTC nest rail20 pos1.
11. PCR2 lid on.
12. PCR2 lid off.
13. Final plate return to rail35 pos0.

Final modeled state reported by the runner:

- work plate at rail35 pos0;
- lid at rail35 pos4;
- magnet and ODTC landing sites empty;
- iSWAP parked and USB disconnected.

## Operator reconciliation

Operator visual confirmation is pending for the physical final state: plate
square at rail35 pos0, lid flat at rail35 pos4, magnet and ODTC nest empty,
tips returned/channels empty, and no observed anomaly. Do not change status to
fully physically validated until this reconciliation is recorded.
