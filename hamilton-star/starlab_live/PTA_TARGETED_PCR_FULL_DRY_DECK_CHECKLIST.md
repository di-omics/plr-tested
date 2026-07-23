# PTA -> Targeted PCR full dry deck setup checklist

Status: release-candidate checklist for the next attended one-column combined
dry run. This is research-use-only engineering motion with empty sacrificial
labware. It is not a wet whole-genome sequencing run.

## Put these items on the deck

Set the deck exactly as listed before starting either phase. Rail numbers match
the printed labels on the Hamilton STAR deck. Carrier position codes are
zero-based: `p0` is the first slot, `p1` is the second, `p2` is the third,
`p3` is the fourth, and `p4` is the fifth. Thus `r35p0` means labeled rail 35,
software position 0, the first carrier slot.

Position codes do not encode left/right/front/back. Follow the approved deck
map and the app's complete location label; never infer physical orientation
from the number. HHS and ODTC rows identify validated modeled targets rather
than removable carrier slots.

| Labeled rail | App location label | Put this here | Exact condition before release |
| ---: | --- | --- | --- |
| 48 | Rail 48 · p0 (first slot) | Hamilton 10 µL filter-tip rack (P10) | Tip-rack columns 1 and 2 (A1:H1 and A2:H2) fully populated and undamaged |
| 48 | Rail 48 · p1 (second slot) | Hamilton 50 µL filter-tip rack (P50) | Tip-rack columns 1 and 2 (A1:H1 and A2:H2) fully populated and undamaged |
| 48 | Rail 48 · p2 (third slot) | Hamilton 300 µL filter-tip rack (P300) | Tip-rack column 1 (A1:H1) fully populated and undamaged |
| 35 | Rail 35 · p0 (first slot) | CellTreat 229195/229196 96-well work plate | Bare, empty, square in the site, and sacrificial |
| 35 | Rail 35 · p1 (second slot) | CellTreat 229195/229196 96-well source plate | Empty for dry work; PTA addresses columns 1 and 3 and Targeted PCR addresses column 1 |
| 35 | Rail 35 · p2 (third slot) | Verified magnetic plate/block | Magnet stays installed and aligned; its plate landing area contains no plate or lid |
| 35 | Rail 35 · p3 (fourth slot) | CellTreat 12-well trough | Empty for dry work; modeled wells are A1, A2, A3, A4, and A12 |
| 35 | Rail 35 · p4 (fifth slot) | Corning 3603 park plate with the correct lid | Park plate is the lid support; seat it square with the lid completely flat |
| 27 | Rail 27 · p2 (HHS modeled target) | HHS nest | HHS stays installed; landing nest contains no plate or lid, is open and idle; no heat or shake program |
| 20 | Rail 20 · p1 (ODTC modeled target) | ODTC nest | ODTC stays installed; landing nest contains no plate or lid, is open, cool and idle; no ODTC connection or program |

Then confirm all of the following:

- [ ] All carriers are locked and every iSWAP travel path is clear.
- [ ] The iSWAP gripper is empty, channels are untipped, and no other STAR
      Python driver is running.
- [ ] The work plate is CellTreat and the park plate/lid is Corning 3603. The
      model combination is deliberate and geometry-locked.
- [ ] HHS uses the locked runner offsets x12.0, y45.5, z17.0. These are
      software reference values, not manual placement measurements; do not
      adjust hardware or infer orientation from them. Do not use the older
      y54.5 engineering value.
- [ ] A trained operator will watch the entire run with the E-stop immediately
      reachable. Nobody will leave the deck.
- [ ] The physical command will run inside a durable Pi-local `tmux` session.
      A foreground `run_on_pi.sh` STAR launch is not disconnect-tolerant and is
      not acceptable for this combined run.

## What one-column means

The current release candidate supports a requested sample count of 1 through 8,
but the 8-channel head still actuates the complete A1:H1 column. Any wells
not assigned to a sample are explicit dry blanks. A count above 8 has no
released build and must be refused until a multi-column runner passes offline,
Chatterbox, and attended physical validation.

For the di-omics workflow, sample count means biological sample wells only.
The planner and runner do not add NTCs or control wells, and there is no hidden
control-well allowance in the count.

## Release sequence at the next bench session

From `hamilton-star/` in the exact committed checkout selected for validation:

1. Print the combined inert plan:

   ```bash
   python starlab_live/run_pta_targeted_pcr_LIDDED_1col_full_dry.py \
     --mode plan --sample-count 8
   ```

2. Run both connection-free deck/model previews on the Pi:

   ```bash
   ./run_on_pi.sh starlab_live/run_pta_targeted_pcr_LIDDED_1col_full_dry.py \
     --mode deck --sample-count 8
   ```

3. Run both phases through Chatterbox on the Pi. This must exit 0 before STAR
   release:

   ```bash
   ./run_on_pi.sh starlab_live/run_pta_targeted_pcr_LIDDED_1col_full_dry.py \
     --mode chatterbox --sample-count 8
   ```

4. Verify that `tmux` is installed on `starpi`. If this check fails, stop and
   use a directly attached Pi console; do not fall back to foreground SSH:

   ```bash
   ssh starpi 'command -v tmux'
   ```

5. Open a durable Pi-local terminal, then run the physical command from inside
   it. The deck and Chatterbox steps above already synchronized this exact
   committed checkout to `~/plr-tested-run`:

   ```bash
   ssh -t starpi
   tmux new-session -A -s pta_targeted_pcr_full_dry
   source ~/star-lab/env/bin/activate
   cd ~/plr-tested-run
   python -u starlab_live/run_pta_targeted_pcr_LIDDED_1col_full_dry.py \
     --mode star --sample-count 8 \
     --confirm RUN_PTA_TARGETED_PCR_LIDDED_1COL_FULL_DRY \
     --acknowledge R48_P10_P50_P300_R35_WORK_SOURCE_MAGNET_TROUGH_LID_R27_HHS_EMPTY_R20_ODTC_EMPTY_OPEN \
     --labware-ack CELLTREAT_229195_WORK_SOURCE_CORNING_3603_LID
   ```

   If the SSH connection drops, the `tmux` session and robot process remain on
   the Pi. Reconnect with `ssh -t starpi` and
   `tmux attach -t pta_targeted_pcr_full_dry`. The operator must remain physically at
   the E-stop even while the terminal is disconnected.

6. After PTA exits 0, the combined runner stops at a mandatory physical
   handoff. Inspect the deck before typing the displayed token. Targeted PCR cannot
   spawn unless the exact fresh observation is entered:

   ```text
   PTA_FINAL_PLATE_R35P0_LID_R35P4_HHS_EMPTY_TIPS_CLEAR_ISWAP_PARKED
   ```

   At this hold, verify plate rail35 pos0, lid rail35 pos4, HHS empty, returned
   tips/channels clear, iSWAP parked, magnet and ODTC empty/open, and all Targeted PCR
   paths clear around the still-installed HHS.

Do not use a software stop for this combined two-phase release candidate. The
new phases do not yet expose hardware-proven cooperative stop checkpoints. Use
the physical E-stop for an immediate safety stop, then treat plate, lid, tip,
channel, and gripper state as unknown until visually reconciled.

## Required final-state reconciliation

Exit 0 is necessary but is not the complete physical acceptance result. Before
recording the run as passed, confirm with your eyes:

- [ ] Work plate is square at rail35 pos0.
- [ ] Lid is flat on its park plate at rail35 pos4.
- [ ] HHS rail27 pos2 is empty.
- [ ] Magnet landing position rail35 pos2 is empty.
- [ ] ODTC nest rail20 pos1 is empty and open.
- [ ] All dry-run tips were returned; channels and iSWAP are empty.
- [ ] iSWAP parked successfully and no collision, scrape, tip anomaly, or
      labware shift was observed.
- [ ] Operator, timestamp, exact Git SHA, terminal exit, and any video/photo
      reference were added to the validation record.

## Wet protocol boundary

The WGS preparation guide is an authorized WGS/WGA workflow source (revision
05/2025). It defines whole-genome amplification and universal library
preparation for downstream WGS. It does not define the targeted PCR workflow.
The source also states that a separate protocol is
required for hybridization-enrichment/targeted-panel library preparation.

Useful vendor requirements for a future wet implementation include:

- 3 uL starting sample volume in Cell Buffer (pages 9-12);
- lysis mix 3 uL per reaction, followed by 20 minutes mixing at 1,400 rpm
  (page 12);
- reaction mix 6 uL per reaction, followed by 1 minute mixing at 1,000 rpm and
  the WGA program (pages 12-13);
- WGA program 30 C for 2.5 hours, 65 C for 3 minutes, then 4 C hold, lid 70 C
  (page 11);
- side-wall dispensing and the seal/spin/mix/spin discipline (pages 8-9);
- fresh/discarded tips appropriate for single-cell work, wet SPRI dwell/wash/dry
  timing, and explicit thermal program control.

None of those wet operations is enabled by the combined dry runner. A wet app
release requires a separate state machine, source layout, tip plan, HHS/ODTC
control validation, and a targeted PCR SOP supplied by the team.
