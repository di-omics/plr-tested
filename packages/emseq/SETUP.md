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

- rail48 p0/p1/p2 (first/second/third slots): p10/p50/p300 filter tips
- rail35 p0 (first slot): empty `CellTreat_96_wellplate_350ul_Fb` sacrificial work plate
- rail35 p1 (second slot): empty `CellTreat_96_wellplate_350ul_Fb` reagent-source plate
- rail35 p2 (third slot): empty, seated magnetic rack/nest
- rail35 p3 (fourth slot): empty/dry `CellTreat_12_troughplate_15000ul_Vb`
- rail20 p1 (ODTC modeled target): empty, open, clear ODTC nest

```bash
./hamilton-star/run_on_pi.sh starlab_live/emseq/run_emseq_odtc_1col_full_dry.py --deck
./hamilton-star/run_on_pi.sh starlab_live/emseq/run_emseq_odtc_1col_full_dry.py \
  --confirm RUN_EMSEQ_ODTC_FULL \
  --labware-ack CELLTREAT_229195_WORK_SOURCE
```

The first command uses the real STAR backend. Normal setup/homing can occur, but every
scoped leg exits in deck mode without pipetting or iSWAP transfer. The second command
performs real STAR/iSWAP motion with empty labware, returns tips, and does not run ODTC
heating. Thermal steps are printed as operator notes. Keep a human at the E-stop for the
entire rehearsal and reconcile the physical plate before resuming after any failure.

This exact rehearsal passed on the physical STAR on 2026-07-21: all 36 legs completed,
the plate returned to rail35 p0, and the error scan was empty. The raw log, checksum,
operator record, and precise dry-versus-wet boundary are in
[`../../hamilton-star/starlab_live/emseq/qc/`](../../hamilton-star/starlab_live/emseq/qc/).

Do not substitute the moving work plate: the physical work and source plates are both
CellTreat 350 uL, matching the working Targeted PCR liquid-height logic. The reused iSWAP
subprocesses intentionally retain the Cor 360 motion-command stand-in used by the
hardware-proven Targeted PCR choreography. P50 source/destination heights are 0.0/1.5 mm;
P10 heights are 0.0/0.5 mm. This prevents the known low-Z p50 crush but does not validate
wet EM-seq delivery into fuller wells; wet runs remain blocked.
