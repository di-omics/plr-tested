# elispot

Run an ELISpot the same way in any lab: qualified, gated, and walkaway, across a plate
washer, a liquid handler, and a spot imager, driven from a Raspberry Pi.

ELISpot is tedious and variability-prone in exactly the places automation is good at: many
precise washes on a delicate membrane, timed reagent additions, and a development step that
has to be stopped at the right moment. This package takes the assay from a sparse manifest
(which cytokine, which wells hold which antigen, simulation or hardware) to a controlled run:
it qualifies the instrument, prepares and coats the membrane, plates the cells, runs the
wash-and-develop chain, reads the plate, calls the responses, and stops itself the moment a
gate says the result cannot be trusted. Every cutoff is an acceptance criterion in a config
file, every reagent value carries where it came from, and nothing is invented.

The core is standard-library Python, so it runs on a bare interpreter at a partner site. The
instruments are all PyLabRobot-drivable from a Pi, so the whole line is one scriptable,
closed-loop system with no vendor lock-in - which is the point of doing it this way.

## The flow

```
  manifest (sparse: cytokine, plate layout, simulation or hardware)
        |
        v
  Gate 0  instrument readiness         Rhodamine B dispense CV <= 5% across the protocol's
        |                              volumes, signal linearity, and aspiration residual
        |                              <= 10 uL, or STOP before the plate is touched
        v
  Gate 1  plate preparation            pre-wet the PVDF membrane, coat, block; the pre-wet
        |                              must go down evenly (uniformity CV) or STOP
        v
  stimulate  plate cells + stimuli     controls placed, cells plated side-wall, then an
        |                              undisturbed 37 C incubation (off-instrument)
        v
  develop    wash off cells -> detect -> wash -> conjugate -> wash -> substrate -> stop -> dry
        |                              the wash-heavy core, at the qualified probe height
        v
  Gate 2  readout                      imager counts SFU; the mitogen positive control must
        |                              fire and the background must be low, or the plate is
        |                              VOID (STOP); then per-antigen response calls, with
        |                              replicate-CV trust and saturation flags
        v
  handoff    results + CSV + next-run recommendations (the loop-closing feed-forward)
```

A gate is an object with named criteria and one of three decisions: PROCEED, PROCEED_SUBSET
(narrow to the wells that passed; the handoff sees only those), or STOP (nothing downstream
runs). That is what makes this a controlled pipeline and not a script.

## Quickstart

```bash
# from packages/elispot/
pip install -e .            # core is stdlib-only; add .[yaml] for YAML manifests, .[test] for pytest

elispot doctor                          # can this lab run it, and what is missing
elispot demo                            # run the bundled example in simulation
elispot plan  configs/example_run.yaml  # validate a manifest, print the resolved plan + rubric
elispot run   configs/example_run.yaml  # run it, write the dossier

# see the gates do their job (simulation only):
elispot run configs/example_run.json --poor-washer      # Gate 0 stops the run
elispot run configs/example_run.json --high-background   # Gate 2 voids the plate
elispot run configs/example_run.json --dead-cells        # positive control fails -> plate void
```

`run` writes a run folder: `dossier.html` (the audit artifact), `outcome.json` (machine
readable), and `results.csv` (per-antigen calls). Also runnable as `python -m elispot ...`
with no install.

## The manifest is the only thing a lab writes

```yaml
run_id: ELI-2026-07-12-demo
operator: di
mode: simulation            # or hardware
cytokine: IFN-gamma
site:
  name: boston_bench
  cells_per_well: 250000
  wash_cycles: 5
  # aspiration_height_mm: 1.2   # teach on your plate lot; hardware is blocked until you do
wells:
  - { well: A1, role: neg_ctrl, antigen: medium }   # background
  - { well: D1, role: pos_ctrl, antigen: PHA }      # mitogen validity control
  - { well: A2, role: test,     antigen: CEF }      # a test antigen, in triplicate
  # ...
```

Everything else - the reagent chain, the QC cutoffs, the read settings - comes from the
package's pinned defaults. That is "standardized from sparse input". A scorable plate is
required to have at least one negative control, one positive control, and one test well; the
loader refuses a manifest that cannot be scored.

## The membrane is why this is hard, and where the judgment is

Most of ELISpot automates cleanly. The catch is the PVDF membrane the assay is read off, and
`membrane.py` makes the three constraints that decide success or garbage explicit, because an
engineer reading the protocol like code should stop at each one:

1. **Probe clearance.** A wash probe that rides too low scratches the membrane and prints a
   line of false spots. The safe aspiration height depends on the plate lot's seating, so it
   is `CALIBRATE` - taught on the physical plate, and a hardware run is blocked until it is.
2. **No jet at the membrane.** A center-jet dispense lifts the capture-antibody layer;
   reagents and wash go down the side wall at a capped flow rate.
3. **Never dry, never over-wash.** The membrane stays wet from coat to development, and the
   cell wash cannot be run harder "to be safe" without lifting the capture layer - so wash
   cycles and volume are QC parameters, qualified at Gate 0, not free knobs.

"That step won't survive automation" is a judgment this package encodes as a guarded value,
not a comment.

## Shipping it to multiple labs

1. **Portable core.** The pipeline, the QC math, and the gates are standard-library Python. A
   partner site needs no scientific stack to run a simulation or to compute a CV the same way
   you do. YAML and the hardware backends are optional extras.

2. **One rubric, in a file.** `configs/acceptance_criteria.yaml` is the whole definition of
   "correct, correctly executed science" for this assay - every cutoff, in one place, that an
   auditor reads without reading code. The defaults ARE the standard; a run that overrides one
   records the value it used in the dossier.

3. **Never invent.** Every reagent value is a `Sourced` value with an origin: TRANSCRIBED
   (cited), TUNABLE (an engineering default with its rationale), CALIBRATE (measured on this
   instrument first), or TODO (from the kit datasheet). The kit's antibody and conjugate
   concentrations are TODO, the substrate development endpoint is CALIBRATE, and a hardware run
   calls `assert_ready_for_hardware()` and refuses to start until every one is resolved.

4. **Qualify the instrument, per site.** Gate 0 is the transfer test: before a well is coated,
   the local washer dispenses a Rhodamine B ladder across the protocol's volumes and its
   aspiration residual is measured. An instrument that is not tight enough, or does not
   aspirate clean, stops the run. Site-specific state (cells per well, wash cycles, the taught
   probe height, the imager background offset) is the `SiteProfile`, a manifest block, not a
   code edit.

5. **Simulation first, hardware by run card.** Every run works end to end in simulation with
   deterministic synthetic reads, so a site can dry-run the whole flow and read a dossier
   before touching an instrument. In hardware mode each step resolves to the Pi command that
   would run it; the package plans and gates, and never pretends to have driven an instrument
   it cannot reach.

6. **Remote and resumable.** A hardware imager count with no data yet raises `AwaitingData`
   with its run card; the operator counts the plate on the Pi and re-runs with the captured
   counts file, so a plate that develops at a partner site resumes asynchronously.

## How it maps to a founding Scientific Automation Lead mandate

| Role requirement | Where it is in this package |
| --- | --- |
| Reduce an assay to a qualified, controlled, transferable implementation | The whole package: sparse manifest to gated dossier, defaults as the standard |
| Define acceptance criteria, controls, and failure modes | `configs/acceptance_criteria.yaml`; controls are well roles (pos/neg/blank); STOP / PROCEED_SUBSET are the failure modes |
| Read a protocol like code: "that step won't survive automation" | `membrane.py` - the PVDF clearance / no-jet / wet-out constraints as guarded values |
| Prove it runs reproducibly outside the lab that invented it | Stdlib core, deterministic simulation, one-file dossier, run cards for the Pi |
| Engineer distributed automation: scheduling, error handling, site calibration | `orchestrator.py` sequences and enforces gates; Gate 0 is site calibration; `SiteProfile` is site-specific state |
| Deploy experiments remotely; control for site-specific drift | Hardware run cards + `AwaitingData` resume; Gate 0 controls the two biggest drift sources, the dispense and the wash |
| Orchestrate agentic pipelines legible to automation and audit | Every stage returns structured data; `outcome.json` is the machine record, `dossier.html` the human one |
| Close the loop: returning data feeds the next design | The readout's background / saturation / replicate numbers become concrete next-run parameter deltas in the handoff |
| Guard the claims; nothing ships you would not defend in diligence | Provenance guard + an explicit "not yet run on hardware" status below |
| Build the validation backbone: checklists, rubrics, ground-truth | The acceptance rubric, the gate outcomes, and the CV / response-call math are that backbone |

## Status: what is real, what is simulated

Honesty about maturity is part of the point.

- **No ELISpot instrument has been run from this package yet.** This is a sim-first design. The
  washer, liquid-handler, and imager adapters resolve to the Pi commands they *would* run
  against integrations that are not in this repo yet; each hardware command is labelled as a
  plan, not a claim. The repo's validated Hamilton STAR liquid handling (`hamilton-star/`) is
  the one backend a STAR-based ELISpot could reuse today.
- **The simulation is deterministic and clearly flagged.** Every synthetic number comes from
  `simulation.py` and every simulated action is marked `simulated` in the record. No simulated
  value can be mistaken for a measurement.
- **Reagent concentrations and the development endpoint are unresolved on purpose.** They are
  TODO / CALIBRATE and block a hardware run until transcribed from the kit and set on the first
  plate. That is the never-invent rule, mechanical.
- **Plate-validity and response-call cutoffs are TUNABLE defaults.** Set them from your own
  assay; the empirical response rule ships as the conservative default, with the
  distribution-free resampling method (Moodie 2010) as the intended upgrade.

## Layout

```
elispot/
  provenance.py     never-invent: Sourced values + the hardware guard
  membrane.py       the PVDF constraints that decide whether ELISpot survives a robot
  qc_math.py        CV, linear fit, net spots, stimulation index, response call (stdlib, tested)
  gates.py          criteria + PROCEED / PROCEED_SUBSET / STOP
  config.py         typed run plan (plate layout, site profile); manifest.py expands sparse input
  simulation.py     every synthetic number, quarantined and deterministic
  reagents/         rhodamine_b (Gate 0 tracer), elispot_kit (the reagent chain, with provenance)
  instruments/      washer / liquid_handler / imager adapters (hardware run cards + simulation)
  stages/           readiness, plate_prep, stimulation, develop, readout, handoff
  orchestrator.py   run the stages, enforce the gates, assemble the dossier
  reporting/        the house-style HTML dossier
  cli.py            elispot run | plan | demo | doctor
configs/            acceptance_criteria.yaml, example manifests (YAML + JSON)
tests/              39 offline tests; run `pytest`
```

Run the tests before trusting a change: `pytest -q`.
