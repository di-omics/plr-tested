# WGS preparation + HHS lidded single-column dry run card

Status: written and passed end to end on `STARChatterboxBackend` on 2026-07-20.
Not yet run on the physical STAR. Research use only.

This card covers dry WGS preparation pipetting followed by the mechanical HHS round trip:

1. operator-profile lysis motion, source column 1 to work column 1
2. operator-profile reaction motion, source column 3 to work column 1
3. work plate rail35 pos0 to HHS rail27 pos2
4. lid rail35 pos4 onto the work plate on HHS
5. delid from HHS back to rail35 pos4
6. work plate HHS to rail35 pos0

It does not start, heat, or shake the HHS. The first physical run is an attended
mechanical engineering dry run using empty sacrificial labware.

## Build and labware lock

- Runner: `starlab_live/run_wgs_prep_pipetting_hhs_LIDDED_1col_dry.py`
- Base commit: `bae80c6c563e83a8ffa37678885689dbc0d482cc`
- PyLabRobot: exactly `0.2.1` (enforced before a run stage is built)
- Work/source plate model: `CellTreat_96_wellplate_350ul_Fb`, CellTreat 229195/229196
- Lid resource: `Cor_96_wellplate_360ul_Fb_Lid`, from the Corning 3603 resource
- Corrected HHS mount: x12.0 / y45.5 / z17.0

Do not use the older y54.5 HHS geometry. It completed empty-plate transfers but
did not seat the first real plate in the HHS nest. The work plate and lid must
share y45.5.

The CellTreat plate plus Corning lid combination is explicit because the
validated WGS preparation pipetting script uses CellTreat, while the earlier HHS lid mover
modeled a Corning plate. Confirm the physical catalog items before STAR motion.
The runner requires this exact acknowledgement on every moving STAR stage:

```text
--labware-ack CELLTREAT_229195_WITH_CORNING_3603_LID
```

## Starting deck

- rail48 pos0: p10 filter tips, columns 1 and 2 available
- rail48 pos1: p50 filter tip rack (modeled but unused in this rehearsal)
- rail35 pos0: empty sacrificial CellTreat work plate
- rail35 pos1: empty/dry CellTreat source plate; column 1 is lysis source and
  column 3 is reaction source
- rail35 pos4: Corning lid seated on its park plate, not directly on the carrier
- rail27 pos2: HHS nest empty and open
- no samples and no reagents

Only one process may drive the STAR. A trained operator watches the entire run
with a hand at the E-stop. After any failure, stop and reconcile the physical
plate, lid, tips, and deck before another command.

## 1. Inert plan

This imports no PyLabRobot hardware stack and makes no connection:

```bash
python starlab_live/run_wgs_prep_pipetting_hhs_LIDDED_1col_dry.py --stage plan
```

## 2. Chatterbox rehearsal

This runs all four logical stages with no hardware connection:

```bash
python starlab_live/run_wgs_prep_pipetting_hhs_LIDDED_1col_dry.py \
  --backend chatterbox --stage all
```

The expected result is exit 0 with all of these terminal banners:

- `SUCCESS: Lysis Mix ...`
- `SUCCESS: Reaction Mix ...`
- `SUCCESS: iSWAP moved work plate to corrected HHS ...`
- `CHATTERBOX STAGE: lid-on`
- `CHATTERBOX STAGE: delid`
- `CHATTERBOX STAGE: plate-return`

## 3. STAR deck assignment

This constructs and prints the complete starting resource tree. It does not
create a backend, connect to the STAR, home, pipette, or transfer anything:

```bash
./run_on_pi.sh starlab_live/run_wgs_prep_pipetting_hhs_LIDDED_1col_dry.py \
  --backend star --stage deck
```

Compare the printed resources and corrected HHS target with the physical deck.
Do not continue if any item differs. The backend argument is accepted for CLI
consistency but is ignored by this connection-free stage.

## 4. Physical stages - run one at a time

`--stage all` is refused in STAR mode. Each command ends and parks the iSWAP so
the operator can reconcile the deck before releasing the next stage.

### Stage A: WGS preparation dry pipetting and plate forward

```bash
./run_on_pi.sh starlab_live/run_wgs_prep_pipetting_hhs_LIDDED_1col_dry.py \
  --backend star --stage wgs_prep-forward \
  --confirm RUN_WGS_PREP_FORWARD_DRY \
  --acknowledge DRY_DECK_MATCHED_HHS_EMPTY \
  --labware-ack CELLTREAT_229195_WITH_CORNING_3603_LID
```

Hold point: the work plate must be visibly seated on HHS rail27 pos2. Rail35
pos0 must be empty. The lid must still be on its park plate at rail35 pos4.

### Stage B: lid on

```bash
./run_on_pi.sh starlab_live/run_wgs_prep_pipetting_hhs_LIDDED_1col_dry.py \
  --backend star --stage lid-on \
  --confirm RUN_HHS_LID_ON_DRY \
  --acknowledge PLATE_SEATED_HHS_LID_ON_PARK \
  --labware-ack CELLTREAT_229195_WITH_CORNING_3603_LID
```

Hold point: the lid must be flush on the work plate. The work plate must remain
seated on HHS. Rail35 pos4 must contain the bare park plate.

### Stage C: delid - first physical evidence

This is unvalidated. Pickup z16 is deliberately high. Plate and lid have almost
the same footprint, so a pickup that is too low can lift the plate while the
firmware reports success.

```bash
./run_on_pi.sh starlab_live/run_wgs_prep_pipetting_hhs_LIDDED_1col_dry.py \
  --backend star --stage delid \
  --confirm RUN_HHS_DELID_DRY \
  --acknowledge LID_FLUSH_HHS_WATCH_LID_NOT_PLATE \
  --labware-ack CELLTREAT_229195_WITH_CORNING_3603_LID
```

Hold point: confirm with your eyes that the lid moved to rail35 pos4 and the
bare work plate remained seated on the HHS. If the plate moved, do not run the
return stage. Reconcile the physical state first.

### Stage D: plate return - first corrected-Y evidence

This stage is also unvalidated at y45.5. Release it only after the Stage C hold
point is satisfied and rail35 pos0 is visibly empty.

```bash
./run_on_pi.sh starlab_live/run_wgs_prep_pipetting_hhs_LIDDED_1col_dry.py \
  --backend star --stage plate-return \
  --confirm RUN_HHS_RETURN_DRY \
  --acknowledge BARE_PLATE_SEATED_HHS_LID_PARKED \
  --labware-ack CELLTREAT_229195_WITH_CORNING_3603_LID
```

Expected final state: work plate rail35 pos0, lid on its park plate rail35 pos4,
and HHS rail27 pos2 empty.

## Evidence to record

For each stage record the commit SHA, operator, date/time, physical start/end
state, terminal exit, and photo/video reference. For delid, explicitly record
whether the plate remained seated. Do not mark delid or corrected-Y return as
validated until a physical run says so.

If setup or any mechanical stage raises, the runner deliberately skips
automatic iSWAP parking and performs a best-effort disconnect. Treat the
plate/lid/gripper state as unknown, inspect it in place, and use an explicit
recovery procedure before another command.

`run_on_pi.sh` syncs the current local working tree and holds a foreground SSH
connection. Run from a clean, committed checkout and do not let the laptop
sleep or drop the network during a moving stage.
