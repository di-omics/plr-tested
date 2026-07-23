# gene-edit

Confirm a gene edit from a single cell or embryo, the same way in any lab.

This packages the repo's validated PTA and targeted PCR work into one QC-gated product:
you give it a sparse manifest (which samples, which locus, simulation or hardware) and it
drives whole-genome amplification, targeted library prep around the edit, and the two QC
reads that decide what is real, then hands the survivors off to TapeStation and the
sequencer. Every cutoff is an acceptance criterion in a config file, every number carries
where it came from, and a run that cannot be trusted stops itself before it spends a
sample.

It is built to be transferred. The core is standard-library Python so it runs on a bare
interpreter at a partner site; the science it depends on (the STAR liquid handling, the
ODTC thermal programs, the Tecan reads) lives in this repo and the package points at it
rather than reimplementing it.

## The flow

```
  manifest (sparse)
        |
        v
  Gate 0  liquid-handling qualification   Rhodamine B, dispense CV <= 5% across the
        |                                  protocol's volumes, or STOP before any sample
        v
  PTA     whole-genome amplification       whole-genome amplification on STAR + ODTC
        |
        v
  Gate 1  post-PTA dsDNA yield             PicoGreen on Tecan; wells under the yield
        |                                  floor are dropped (PROCEED_SUBSET)
        v
  targeted PCR  library prep at the edit locus   PCR1 -> anti-dimer clean -> PCR2 -> final clean
        |
        v
  Gate 2  post-targeted PCR library conc         PicoGreen on Tecan; wells outside the loading
        |                                  window are dropped
        v
  handoff TapeStation QC + pooling + Illumina sample sheet
```

A gate is an object with named criteria and one of three decisions: PROCEED,
PROCEED_SUBSET (narrow to the wells that passed, every later stage sees only those), or
STOP (nothing downstream runs). That is what makes this a controlled pipeline and not a
script.

## Quickstart

```bash
# from packages/gene-edit/
pip install -e .            # core is stdlib-only; add .[yaml] for YAML manifests, .[test] for pytest

edit-confirm doctor                          # can this lab run it, and what is missing
edit-confirm demo                            # run the bundled example in simulation
edit-confirm plan  configs/example_run.yaml  # validate a manifest, print the resolved plan + rubric
edit-confirm run   configs/example_run.yaml  # run it, write the dossier
```

Porting to a new lab: `edit-confirm doctor` (compute tier, zero setup) and
`edit-confirm doctor --hardware` check every requirement and print the exact fix for each
gap. [SETUP.md](SETUP.md) is the from-clone-to-running checklist behind those checks.

`run` writes a run folder: `dossier.html` (the audit artifact), `outcome.json` (machine
readable), and `samplesheet.csv` (sequencing). Also runnable as
`python -m edit_confirmation ...` with no install.

## The manifest is the only thing a lab writes

```yaml
run_id: EC-2026-07-11-embryo01
operator: di
mode: simulation                # or hardware
edit: { type: crispr_indel }
locus: { name: EMX1_site1, target_product_bp: 250 }
samples:
  - { id: embryo_01, well: A1 }
  - { id: pos_ctrl,  well: F1, type: pos_ctrl }
  - { id: ntc,       well: H1, type: ntc }
```

Everything else - deck, reagent recipes, thermal programs, QC cutoffs - comes from the
package's pinned defaults. That is "standardized from sparse input".

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

3. **Never invent.** Every reagent volume, temperature, and cycle count is a `Sourced`
   value with an origin: TRANSCRIBED (cited to a document), TUNABLE (an engineering
   default, with its rationale), CALIBRATE (must be measured on this instrument first),
   or TODO (unknown). A hardware run calls `assert_ready_for_hardware()` and refuses to
   start if any CALIBRATE or TODO value survives. The rule is mechanical, not a habit.

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
| Reduce an assay to a qualified, controlled, transferable run | The whole package: sparse manifest to gated dossier, defaults as the standard |
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

- The **liquid handling, the ODTC thermal programs, and the deck** this points at are
  validated on hardware in this repo (see `hamilton-star/` and
  `instrument-integrations/odtc/`). The targeted PCR round 1 program ran 30 cycles on the ODTC.
- The **Tecan reads have not been run on a reader yet** (see
  `instrument-integrations/tecan-infinite/`). The Rhodamine working concentration and the
  reader gain are CALIBRATE values; a hardware run is blocked until they are measured.
  This is not a limitation to hide - it is exactly what Gate 0's provenance guard is for.
- The **simulation is deterministic and clearly flagged.** Every synthetic number comes
  from `simulation.py` and every simulated action is marked `simulated` in the record. No
  simulated value can be mistaken for a measurement.
- **PicoGreen yield floors and the targeted PCR loading window are TUNABLE defaults**, to be set
  from real yields; they are marked as such in the rubric and the dossier.

## Layout

```
edit_confirmation/
  provenance.py     never-invent: Sourced values + the hardware guard
  qc_math.py        CV, linear fit, quantitation, Rhodamine range (stdlib, tested)
  gates.py          criteria + PROCEED / PROCEED_SUBSET / STOP
  config.py         typed run plan; manifest.py expands sparse input into it
  simulation.py     every synthetic number, quarantined and deterministic
  reagents/         rhodamine_b, picogreen, spri - recipes with provenance
  instruments/      STAR / ODTC / Tecan adapters (hardware run cards + simulation)
  stages/           lh_qc, pta, qc_picogreen, targeted_pcr, handoff
  orchestrator.py   run the stages, enforce the gates, assemble the dossier
  reporting/        the house-style HTML dossier
  cli.py            edit-confirm run | plan | demo
configs/            acceptance_criteria.yaml, deck, example manifests
tests/              22 offline tests; run `pytest`
```

Run the tests before trusting a change: `pytest -q`.
