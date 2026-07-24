# sequencing-validation

QC-gated orchestration for whole-genome sequencing preparation followed by
PCR enrichment.

The package coordinates a Hamilton STAR, an on-deck thermocycler, plate-reader
checkpoints, and a sequencing handoff. It keeps the reusable automation public
while leaving biological method values in an operator-controlled run manifest
and external thermocycler profiles.

## Safety boundary

- Public examples use `profile_kind: synthetic_water`.
- Synthetic profiles are motion demonstrations. Load water only.
- Hardware mode requires `profile_kind: operator`.
- An operator profile must state every liquid volume, cleanup ratio, annealing
  temperature, cycle count, QC dilution, product volume, reader wavelength,
  standard concentration, and acceptance cutoff.
- Biological thermocycler programs are JSON files outside the repository and
  are passed to `05_odtc_run_protocol.py --operator-profile`.
- The package supplies deck geometry and orchestration, not an assay recipe.

## Flow

```text
manifest + operator method
  -> liquid-handling qualification gate
  -> whole-genome sequencing preparation
  -> post-preparation dsDNA gate
  -> PCR enrichment and cleanup
  -> post-enrichment concentration gate
  -> fragment-analysis, pooling, and sequencing handoff
```

Each gate returns `PROCEED`, `PROCEED_SUBSET`, or `STOP`. A failing well is not
carried forward, and a run-level failure stops downstream work.

## Quickstart

From this directory:

```bash
pip install -e .
seq-validate doctor
seq-validate plan configs/example_run.yaml
seq-validate run configs/example_run.yaml
pytest -q
```

The bundled manifest is deterministic, synthetic, and water-only. It writes:

- `dossier.html` - human-readable gate and action record
- `outcome.json` - machine-readable run record
- `samplesheet.csv` - sequencing handoff for passing samples

## Required manifest sections

Every manifest includes samples, target metadata, a complete `method` block,
and a complete `acceptance` block. The example below is intentionally partial;
use [configs/example_run.yaml](configs/example_run.yaml) for the complete public
water-only demonstration.

```yaml
run_id: site-run-001
operator: operator-id
mode: simulation
assay: { type: targeted_sequencing }
target: { name: target-region, target_product_bp: 250 }

method:
  profile_kind: operator
  parameter_source: /secure/site-method.json
  wgs_odtc_profile: /secure/wgs-thermal.json
  pcr1_odtc_profile: /secure/pcr1-thermal.json
  pcr2_odtc_profile: /secure/pcr2-thermal.json
  # all remaining required liquid, cleanup, QC, and cycling fields are explicit

acceptance:
  # all gate thresholds are explicit and site-approved

samples:
  - { id: sample-01, well: A1 }
  - { id: positive-control, well: F1, type: pos_ctrl }
  - { id: no-template-control, well: H1, type: ntc }
```

The loader rejects missing or unknown method and acceptance fields. A hardware
manifest using the public synthetic profile is rejected before an instrument
action is planned.

## ODTC operator profiles

The thermocycler integration defines
`instrument-integrations/odtc/operator-method-profile.schema.json`. An
operator-owned profile supplies:

- method name;
- lid temperature;
- maximum reaction volume;
- ordered stages;
- repeats;
- temperatures, hold times, and optional ramp rates.

The loader validates the profile against the ODTC operating envelope before any
method is uploaded.

## Transfer to another site

1. Run `seq-validate doctor` and the simulation.
2. Verify the deck layout in `configs/deck_validation.yaml`.
3. Qualify liquid handling on the local hardware.
4. Calibrate the reader and pin the required reader values.
5. Create controlled operator method and acceptance files.
6. Review the generated run card and thermocycler XML.
7. Run hardware with an operator present at the E-stop.

Site-specific consumable state, such as the starting tip column, belongs in the
manifest rather than in deck geometry.

## Validation status

- Hamilton motion, tip policy, and selected deck handoffs have repository
  validation records.
- Public assay-category programs are synthetic water-only profiles.
- The plate-reader integration remains calibration-gated.
- Simulation output is deterministic and labeled as simulated.
- Native hardware execution still requires site review of the generated run
  card and controlled operator profiles.

## Layout

```text
sequencing_validation/
  config.py         typed run, method, deck, and acceptance data
  manifest.py       strict JSON/YAML loader
  gates.py          gate decisions and criteria
  simulation.py     deterministic synthetic data
  instruments/      STAR, ODTC, and reader run-card adapters
  stages/           qualification, WGS, PCR enrichment, QC, handoff
  orchestrator.py   sequencing and stop/subset behavior
  reporting/        dossier and handoff artifacts
configs/
  example_run.*     complete synthetic water-only demonstration
  acceptance_criteria.yaml  field template with no assay defaults
tests/
```
