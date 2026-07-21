# Setup

## Compute-only simulation

1. Use Python 3.9 or newer.
2. From `packages/emseq`, run `python -m emseq_automation doctor`.
3. Run `python -m emseq_automation demo`.
4. Open `runs/EMSEQ-DEMO/dossier.html` and inspect the run card.

The core is standard-library only. Install PyYAML only if YAML manifests are needed.

## Hardware qualification

Do not begin with a sample. Run `python -m emseq_automation doctor --hardware`, then
close each `MISS` item one physical leg at a time under the repo's normal safety rules.
The package will continue to block `mode: hardware` until the provenance entries are
updated from `CALIBRATE`/`TODO` after measured evidence exists.

The relevant implementation trees are:

- `hamilton-star/starlab_live/emseq/`
- `instrument-integrations/odtc/`

The safe first checks are the existing `--mode deck`, `--dry`, `--sim-lh`, and ODTC
`--dry` modes. They do not establish liquid, geometry, lid, heating, or biological
validity.

## Same-day STAR dry rehearsal

With the operator physically present, stage the empty deck and run:

- rail48 pos0/1/2: p10/p50/p300 filter tips
- rail35 pos0: empty `Cor_96_wellplate_360ul_Fb` sacrificial work plate
- rail35 pos1: empty `CellTreat_96_wellplate_350ul_Fb` reagent-source plate
- rail35 pos2: empty, seated magnetic rack/nest
- rail35 pos3: empty/dry `CellTreat_12_troughplate_15000ul_Vb`
- rail20 pos1: empty, open, clear ODTC nest

```bash
./hamilton-star/run_on_pi.sh starlab_live/emseq/run_emseq_odtc_1col_full_dry.py --deck
./hamilton-star/run_on_pi.sh starlab_live/emseq/run_emseq_odtc_1col_full_dry.py \
  --confirm RUN_EMSEQ_ODTC_FULL
```

The first command uses the real STAR backend. Normal setup/homing can occur, but every
scoped leg exits in deck mode without pipetting or iSWAP transfer. The second command
performs real STAR/iSWAP motion with empty labware, returns tips, and does not run ODTC
heating. Thermal steps are printed as operator notes. Keep a human at the E-stop for the
entire rehearsal and reconcile the physical plate before resuming after any failure.

Do not substitute the moving work plate. The ODTC and magnet iSWAP coordinates were
confirmed using the `Cor_96_wellplate_360ul_Fb` model. This dry rehearsal does not
validate the inherited liquid-handling offsets for that plate; wet runs remain blocked.
