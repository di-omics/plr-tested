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

