# whole-genome amplification + HHS lidded single-home dry run card

Status: continuous composition passed full `STARChatterboxBackend` rehearsal on
2026-07-21. Not yet run continuously on the physical STAR. Research use only.

The component stages were run individually on the physical STAR on 2026-07-21:

- one-column lysis/reaction dry motion plus plate forward: exit 0 and visually confirmed
- lid-on: first attempt returned `Plate not found` because the lid was not seated
  flat on its park plate; no code changed; reseated retry exited 0 and was visually confirmed
- delid x12/y45.5/z16 to park drop z4: exit 0 and visually confirmed
- plate return x12/y45.5/z10 to r35p0 drop z8.5: exit 0

The continuous runner changes session composition only. Its normalized eight
iSWAP `C0PP`/`C0PR` Chatterbox commands exactly match the four individually run
mechanical stages, including coordinates and grip widths.

## Continuous scope

1. 3.0 uL x8 lysis dry motion, source column 1 to work column 1
2. 6.0 uL x8 reaction dry motion, source column 3 to work column 1
3. CellTreat work plate rail35 pos0 to HHS rail27 pos2
4. Corning 3603 lid rail35 pos4 onto the work plate on HHS
5. delid from HHS back to rail35 pos4
6. bare work plate from HHS back to rail35 pos0

There is one setup/home, one unified deck, one handler, four slow-iSWAP
contexts, and one final park/stop. There is no operator pause after physical
release. The HHS is never started, heated, or shaken. Tips are returned.

## Starting deck

- rail48 pos0: p10 filter tips, columns 1 and 2 available
- rail48 pos1: p50 rack present (modeled but unused)
- rail35 pos0: empty sacrificial CellTreat 229195/229196 work plate
- rail35 pos1: empty/dry CellTreat source plate, columns 1 and 3 clear
- rail35 pos4: Corning 3603 lid seated flat and square on its park plate
- rail27 pos2: HHS empty, open, and idle
- no samples and no reagents

Only one process may drive the STAR. A trained operator watches the complete
sequence with a hand at the E-stop. Do not release the continuous run if the
lid can rock, is skewed, or is not fully seated on the r35p4 park plate.

## Inert plan

```bash
python starlab_live/run_pta_pipetting_hhs_LIDDED_1col_singlehome_dry.py --mode plan
```

## Connection-free deck model

This builds the unified resource tree without creating a backend, connecting,
homing, or moving:

```bash
./run_on_pi.sh starlab_live/run_pta_pipetting_hhs_LIDDED_1col_singlehome_dry.py \
  --mode deck
```

## Chatterbox rehearsal

```bash
python starlab_live/run_pta_pipetting_hhs_LIDDED_1col_singlehome_dry.py \
  --mode chatterbox
```

Expected final lines:

```text
SUCCESS: continuous PTA + HHS lid/delid/return dry sequence completed.
Final modeled state: work plate r35p0; lid r35p4; HHS empty.
```

## Continuous physical STAR command

Release only after the starting deck has been rechecked immediately before the
command. Once released, do not touch the deck. Watch every operation.

```bash
./run_on_pi.sh starlab_live/run_pta_pipetting_hhs_LIDDED_1col_singlehome_dry.py \
  --mode star \
  --confirm RUN_PTA_HHS_LIDDED_FULL_DRY \
  --acknowledge FULL_DRY_DECK_LID_FLAT_HHS_EMPTY \
  --labware-ack CELLTREAT_229195_WITH_CORNING_3603_LID
```

If setup or any operation raises, the runner deliberately skips automatic
iSWAP parking and performs a best-effort disconnect. Treat the plate, lid, and
gripper state as unknown. Do not retry or run a later stage until the physical
state is reconciled.

## Final expected state

- work plate square at rail35 pos0
- lid flat on its park plate at rail35 pos4
- HHS rail27 pos2 empty
- no tips on channels
- iSWAP parked

Record the commit SHA, operator, date/time, terminal exit, observed result of
each mechanical leg, and any intervention. A successful continuous dry run is
the release evidence needed before merging this choreography into the future
whole-genome amplification + Targeted PCR team product.
