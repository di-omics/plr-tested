# assay-validation

Validate a sequencing target from a single cell or sample, the same way in any lab.

This packages the repo's validated WGS preparation and PCR enrichment work into one QC-gated product:
you give it an explicit run manifest (samples, locus, method profile, and run mode) and it
drives whole-genome sequencing preparation, targeted library prep around the target, and the two QC
reads that decide what is real, then hands the survivors off to fragment analyzer and the
sequencer. Every cutoff is an acceptance criterion in a config file, every number carries
where it came from, and a run that cannot be trusted stops itself before it spends a
sample.

It is built to be transferred. The core is standard-library Python so it runs on a bare
interpreter at a partner site. The public package provides deck geometry, orchestration,
gates, and instrument handoffs. Each run supplies an operator-approved method profile
with its wet-method, thermal, and QC values.

## The flow

```
  run manifest
        |
        v
  Gate 0  liquid-handling qualification   Rhodamine B, dispense CV <= 5% across the
        |                                  protocol's volumes, or STOP before any sample
        v
  WGS preparation     whole-genome sequencing preparation       whole-genome sequencing preparation on STAR + ODTC
        |
        v
  Gate 1  post-WGS preparation dsDNA yield             fluorescent dsDNA assay on Tecan; wells under the yield
        |                                  floor are dropped (PROCEED_SUBSET)
        v
  PCR enrichment  library prep at the target locus   PCR1 -> anti-dimer clean -> PCR2 -> final clean
        |
        v
  Gate 2  post-PCR-enrichment library conc         fluorescent dsDNA assay on Tecan; wells outside the loading
        |                                  window are dropped
        v
  handoff fragment analyzer QC + pooling + sequencing platform sample sheet
```

A gate is an object with named criteria and one of three decisions: PROCEED,
PROCEED_SUBSET (narrow to the wells that passed, every later stage sees only those), or
STOP (nothing downstream runs). That is what makes this a controlled pipeline and not a
script.

## Quickstart

```bash
# from packages/assay-validation/
pip install -e .            # core is stdlib-only; add .[yaml] for YAML manifests, .[test] for pytest

assay-validate doctor                          # can this lab run it, and what is missing
assay-validate demo                            # run the bundled example in simulation
assay-validate plan  configs/example_run.yaml  # validate a manifest, print the resolved plan + rubric
assay-validate run   configs/example_run.yaml  # run it, write the dossier
```

Porting to a new lab: `assay-validate doctor` (compute tier, zero setup) and
`assay-validate doctor --hardware` check every requirement and print the exact fix for each
gap. [SETUP.md](SETUP.md) is the from-clone-to-running checklist behind those checks.

`run` writes a run folder: `dossier.html` (the audit artifact), `outcome.json` (machine
readable), and `samplesheet.csv` (sequencing). Also runnable as
`python -m assay_validation ...` with no install.

## The manifest is the only thing a lab writes

```yaml
run_id: SEQ-2026-07-11-01
operator: di
mode: simulation                # or hardware
analysis: { type: variant_calling }
locus: { name: target_1, pcr_product_bp: 250 }
method:
  # Synthetic values exercise orchestration with water only; they are not a recipe.
  profile_kind: synthetic_water
  parameter_source: public example; synthetic water only
  wgs_stage_1_ul: 10
  wgs_stage_2_ul: 10
  wgs_odtc_profile: synthetic-water-only-wgs.json
  pcr_stage_1_transfer_ul: 10
  pcr_stage_2_transfer_ul: 10
  pcr_reaction_volume_ul: 20
  post_pcr1_cleanup_ratio: 1
  post_pcr2_cleanup_ratio: 1
  supernatant_margin_ul: 0
  pcr1_anneal_c: 40
  pcr2_cycles: 2
  pcr1_odtc_profile: synthetic-water-only-pcr1.json
  pcr2_odtc_profile: synthetic-water-only-pcr2.json
  wgs_qc_dilution: 1
  pcr_qc_dilution: 1
  wgs_product_volume_ul: 20
  pcr_library_volume_ul: 20
  indexing_overhang_bp: 10
  pool_target_mass_ng: 1
  fragment_window_below_bp: 5
  fragment_window_above_bp: 5
  dimer_flag_below_bp: 5
fluorescent_dsdna:
  profile_label: synthetic-water-only
  excitation_nm: 400
  emission_nm: 500
  standards_ng_per_ml: [0, 100, 200, 300]
samples:
  - { id: sample_01, well: A1 }
  - { id: pos_ctrl,  well: F1, type: pos_ctrl }
  - { id: ntc,       well: H1, type: ntc }
```

The package resolves deck geometry and the QC rubric. Biological transfer values,
cleanup ratios, QC preparation values, temperatures, cycle counts, and ODTC profile
paths, library-size checks, and normalization target are explicit in the required
`method` block. Hardware runs require an operator-approved profile.

## Shipping it to multiple labs

This is the part the product is designed around. Six things make a protocol survive a
second lab, or a robot, running it:

1. **Portable core.** The pipeline, the QC math, and the gates are standard-library
   Python. A partner site needs no scientific stack to run a simulation or to compute a
   CV the same way you do. YAML and the hardware backends are optional extras.

2. **One rubric, in a file.** `configs/acceptance_criteria.yaml` is the whole definition
   of "correct, correctly executed science" for this assay - every cutoff, in one place,
   that an auditor reads without reading code. The defaults ARE the standard; a run that
   overrides one records the value it used in the dossier.

3. **Never invent.** The required method block makes reagent volumes, cleanup ratios,
   temperatures, cycle counts, ODTC profile paths, and QC preparation values explicit.
   Hardware mode requires an operator profile. Calibration values retain provenance, and
   a hardware run refuses to start while any CALIBRATE or TODO value survives.

4. **Qualify the deck, per site.** Gate 0 is the transfer test: before a sample is
   touched, the local liquid handler dispenses a Rhodamine B ladder across the exact
   volumes the protocol uses and the Tecan reads the CV. A deck that is not tight enough
   stops the run. Site-specific consumable choices (which tip-rack column to start from,
   `tip_column`) are manifest parameters, not code edits.

5. **Simulation first, hardware by run card.** Every run works end to end in simulation
   with deterministic synthetic reads, so a site can dry-run the whole flow and read a
   dossier before touching an instrument. In hardware mode each step resolves to the
   exact validated Pi command (`run_on_pi.sh ...`); the package plans and gates, the
   validated repo scripts execute. It never pretends to have driven an instrument it
   cannot reach.

6. **Remote and resumable.** A hardware plate read that has no data yet raises
   `AwaitingData` with its run card; the operator runs it on the Pi and re-runs the
   package with the captured results file, so a run can be deployed at a site you do not
   sit in and resumed asynchronously.

## What it does

| Task | Where it is in this package |
| --- | --- |
| Reduce an assay to a qualified, controlled, transferable run | The whole package: explicit run manifest to gated dossier |
| Define acceptance criteria, controls, and failure modes | `configs/acceptance_criteria.yaml`; controls (pos/neg/NTC) are sample types; STOP/SUBSET are the failure modes |
| Prove it runs reproducibly outside the lab that invented it | Stdlib core, deterministic simulation, one-file dossier, run cards for the Pi |
| Engineer distributed automation: scheduling, error handling, site calibration | `orchestrator.py` sequences and enforces gates; Gate 0 is site calibration; `tip_column` is site-specific consumable state |
| Deploy experiments remotely; control for site-specific drift | Hardware run cards + `AwaitingData` resume; Gate 0 controls for the biggest drift source (the local pipettor) |
| Orchestrate agentic comp-bio + wet-lab pipelines, legible to automation and audit | Every stage returns structured data; `outcome.json` is the machine record, `dossier.html` the human one |
| Close the loop: returning data feeds the next decision | Gate 1/2 concentrations feed forward into equal-mass pooling and the sample sheet |
| Guard the claims; nothing ships you would not defend in diligence | Provenance guard + "not yet run on hardware" honesty (see Status) |
| Build the validation backbone: checklists, rubrics, ground-truth | The acceptance rubric, the gate outcomes, and the CV/curve math are that backbone |

## Status: what is real, what is simulated

Honesty about maturity is part of the point.

- The **liquid-handling geometry, ODTC control path, and deck choreography** this points
  at are validated on hardware in this repo (see `hamilton-star/` and
  `instrument-integrations/odtc/`). Run-specific biological settings come from the
  operator-approved method profile.
- The **Tecan reads have not been run on a reader yet** (see
  `instrument-integrations/tecan-infinite/`). The Rhodamine working concentration and the
  reader gain are CALIBRATE values; a hardware run is blocked until they are measured.
  This is not a limitation to hide - it is exactly what Gate 0's provenance guard is for.
- The **simulation is deterministic and clearly flagged.** Every synthetic number comes
  from `simulation.py` and every simulated action is marked `simulated` in the record. No
  simulated value can be mistaken for a measurement.
- **fluorescent dsDNA assay yield floors and the PCR enrichment loading window are TUNABLE defaults**, to be set
  from real yields; they are marked as such in the rubric and the dossier.

## Layout

```
assay_validation/
  provenance.py     never-invent: Sourced values + the hardware guard
  qc_math.py        CV, linear fit, quantitation, Rhodamine range (stdlib, tested)
  gates.py          criteria + PROCEED / PROCEED_SUBSET / STOP
  config.py         typed run plan; manifest.py validates explicit input into it
  simulation.py     every synthetic number, quarantined and deterministic
  reagents/         rhodamine_b, fluorescent_dsdna, spri - standards and planning helpers
  instruments/      STAR / ODTC / Tecan adapters (hardware run cards + simulation)
  stages/           lh_qc, wgs_prep, qc_fluorescent_dsdna, pcr_enrichment, handoff
  orchestrator.py   run the stages, enforce the gates, assemble the dossier
  reporting/        the house-style HTML dossier
  cli.py            assay-validate run | plan | demo
configs/            acceptance_criteria.yaml, deck, example manifests
tests/              22 offline tests; run `pytest`
```

Run the tests before trusting a change: `pytest -q`.
