# Targeted PCR + ODTC lidded single-home dry run card

Research use only. This is a one-column, empty-labware movement and pipetting
rehearsal. It returns tips and does not contain samples or reagents.

## Evidence and scope

The equivalent 13-leg subprocess choreography passed on the physical STAR on
2026-07-16, including two complete plate/lid round trips through the ODTC nest
and the magnet round trip. A later dry orchestration called the ODTC read-only
at both thermal positions and self-returned the deck.

This card releases the newer single-session composition for its first attended
physical run. It uses one STAR setup/home, one unified deck, 13 protocol legs,
10 slow-iSWAP moves, and one success-only park/stop.

The runner does not connect to the ODTC, initialize it, command its door, heat,
or thermocycle. The ODTC is only a physical landing nest during this dry run.

The liquid model remains CellTreat so the proven well-bottom geometry stays
truthful. Motion-only compensation makes all 20 normalized `C0PP`/`C0PR`
commands byte-identical to the hardware-proven Corning stand-in movers. The
PyLabRobot version, model dimensions/anchors, tuned geometry, and golden command
trace are release locks.

## Exact starting deck

- One STAR driver process only. Channels are untipped; iSWAP holds nothing.
- Empty sacrificial labware only. No sample, reagent, ethanol, or water.
- Rail48 pos0: p10 filter-tip rack present; unused by this run.
- Rail48 pos1: p50 filter-tip rack; columns 1 and 2 intact.
- Rail48 pos2: p300 filter-tip rack; column 1 intact.
- Rail35 pos0: bare, empty CellTreat 229195 work plate, square and fully seated.
- Rail35 pos1: empty CellTreat 229195 source plate, square and unobstructed.
- Rail35 pos2: the correct magnet block installed, aligned, and empty.
- Rail35 pos3: CellTreat 12-well trough seated; A1, A2, A3, A4, and A12 empty.
- Rail35 pos4: Corning 3603 park plate with the correct lid flat and centered.
- Rail20 pos1: ODTC nest empty, open, cool/idle, and clear through the iSWAP path.
- All carriers are locked at their stated rails. The full iSWAP path is clear.
- A trained operator watches continuously with immediate E-stop access.

Do not touch or restage anything after the physical command is released.

## Inert checks

From `hamilton-star/`:

```bash
python starlab_live/run_targeted_pcr_odtc_LIDDED_1col_full_v2_singlehome_dry.py \
  --mode plan

python starlab_live/run_targeted_pcr_odtc_LIDDED_1col_full_v2_singlehome_dry.py \
  --mode deck

python starlab_live/run_targeted_pcr_odtc_LIDDED_1col_full_v2_singlehome_dry.py \
  --mode chatterbox
```

`deck` creates no backend, connection, setup/home, ODTC call, or motion.
`chatterbox` must exit 0 and match the exact 20-command golden movement trace.

Run the connection-free deck preview on the Pi before physical release:

```bash
./run_on_pi.sh starlab_live/run_targeted_pcr_odtc_LIDDED_1col_full_v2_singlehome_dry.py \
  --mode deck
```

## Physical STAR command

Only after every starting-deck line above is visibly true:

```bash
./run_on_pi.sh starlab_live/run_targeted_pcr_odtc_LIDDED_1col_full_v2_singlehome_dry.py \
  --mode star \
  --confirm RUN_TARGETED_PCR_ODTC_LIDDED_SINGLEHOME_DRY \
  --acknowledge R48_P10_P50_P300_R35_WORK_SOURCE_MAGNET_TROUGH_LID_R20_ODTC_EMPTY_OPEN \
  --labware-ack CELLTREAT_229195_WORK_SOURCE_CORNING_3603_LID
```

Watch especially:

1. Both ODTC plate drops seat squarely.
2. Both lid-on moves land flat.
3. Both lid-off moves lift only the lid and leave the plate seated.
4. Both ODTC returns pick the plate cleanly.
5. The magnet drop and pickup seat and clear squarely.
6. Every dry tip workflow returns tips without disturbing a rack.

## Stop rule and final state

On any exception, the runner skips automatic iSWAP parking and disconnects.
Treat plate, lid, tip, and gripper state as unknown. Do not retry or run a later
command until the physical deck is reconciled.

A complete pass ends with:

- work plate at rail35 pos0;
- lid flat on the park plate at rail35 pos4;
- ODTC nest and magnet landing site empty;
- tips returned and channels empty;
- iSWAP parked;
- process exit code 0.

Record the git SHA, PyLabRobot version, command, exit code, operator-observed
state, and any anomaly before changing the runner's validation status.
