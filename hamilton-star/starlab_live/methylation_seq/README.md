# Methylation sequencing motion scaffold

This directory contains a simulation-first, single-column Hamilton/ODTC scaffold
for methylation sequencing. It intentionally describes only generic numbered
stages and magnetic-cleanup handoffs.

Biological reagent identities, compositions, transfer volumes, cleanup ratios,
thermal temperatures, durations, cycle counts, and lid settings are not public
defaults. An operator must provide an approved local JSON profile through
`PLR_METHOD_PARAMETERS_FILE`. ODTC biological methods use a separate
operator-owned profile; the public named ODTC programs are water-only motion
checks.

Public stage interfaces:

- `methylation_seq_reagent_adds.py --mode stage-1` through `stage-11`
- `methylation_seq_cleanup.py --cleanup cleanup-1|cleanup-2|cleanup-3`
- `run_methylation_seq_odtc_1col_full_dry.py --print`
- ODTC handoffs `methylation-seq-stage-1` through `methylation-seq-stage-8`

The rail assignments, plate models, tip selection, aspiration/dispense heights,
offsets, blowout values, settle times, and iSWAP pickup/drop offsets are hardware
motion data and remain in code. These methylation-sequencing liquid transfers
are still simulation-first; a water-only rehearsal and site qualification are
required before any biological run.

Example dry inspection:

```bash
export PLR_METHOD_PARAMETERS_FILE=/secure/operator/method-parameters.json
./hamilton-star/run_on_pi.sh \
  starlab_live/methylation_seq/methylation_seq_reagent_adds.py \
  --mode stage-1 --dry --return-tips
```

Do not load samples or biological reagents when using the public water-only
profiles.
