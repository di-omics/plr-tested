# Walkthrough: an ELISpot, as code

A guided tour of this package for someone reading it for the first time. It follows the
ELISpot protocol from an empty plate to called responses, and for each step points at the
file that implements it and the check that guards it. Read top to bottom, or open the files
in the order listed and talk through them.

The one idea to hold onto: this is not a macro that replays a protocol. It is a **gated
pipeline**. Between every pair of steps sits a checkpoint that can let the run continue,
continue with fewer wells, or stop it before it wastes a sample. The protocol is the easy
part; the gates and the "never invent a value" rule are the point.

---

## Run it first (about 30 seconds)

```bash
cd packages/immunoassay-automation
python3 -m immunoassay doctor      # "can this machine run it, and what is missing"
python3 -m immunoassay demo        # runs the whole flow in simulation, writes a dossier
open runs/ELI-2026-07-12-demo/dossier.html    # the audit artifact
```

Then watch a gate do its job - stop the run on a bad instrument, and void a plate on a dead
positive control:

```bash
python3 -m immunoassay run configs/example_run.json --poor-washer     # Gate 0 STOP
python3 -m immunoassay run configs/example_run.json --dead-cells       # Gate 2 voids the plate
```

Nothing here touches an instrument. Every synthetic number is quarantined in one file
([simulation.py](immunoassay/simulation.py)) and every simulated action is flagged, so no
made-up value can be mistaken for a measurement.

---

## The shape of it

- The operator writes a small **manifest** ([configs/example_run.yaml](configs/example_run.yaml)):
  which cytokine, which wells hold which antigen, which are controls. Everything else -
  reagent chain, QC cutoffs, read settings - comes from pinned defaults.
- [orchestrator.py](immunoassay/orchestrator.py) runs a fixed sequence of **stages** and, after
  each, reads its **gate** and acts on the decision: PROCEED, PROCEED_SUBSET (narrow to the
  wells that passed), or STOP.
- Every reagent value is a `Sourced` value ([provenance.py](immunoassay/provenance.py)) with an
  origin: TRANSCRIBED, TUNABLE, CALIBRATE, or TODO. A hardware run refuses to start until every
  CALIBRATE and TODO is resolved.

```
manifest -> Gate 0 readiness -> Gate 1 plate prep -> stimulation -> develop -> Gate 2 readout -> handoff
```

---

## The protocol, step by step

Each step below is: the wet-lab action, the thing that makes it hard to automate, and where
it lives in the code.

### 0. Qualify the instrument (Gate 0)
**Bench:** before you coat a plate, you trust your washer. **Automated:** you *measure* it.
The EL406 dispenses a Rhodamine ladder across the volumes the protocol uses; the CV is the
dispense precision, and the residual left after aspiration is the carryover risk. Over the
cutoff at any volume, or a residual too high, and the run stops before a sample is spent.
- [stages/readiness.py](immunoassay/stages/readiness.py) - the gate
- [instruments/washer.py](immunoassay/instruments/washer.py) - the EL406 dispense/aspirate reads
- [reagents/rhodamine_b.py](immunoassay/reagents/rhodamine_b.py) - the tracer, with its
  CALIBRATE working concentration and gain

### 1. Activate and coat the PVDF membrane (Gate 1)
**Bench:** wet the hydrophobic PVDF with a brief ethanol pre-wet, then coat with capture
antibody. **The catch that decides everything:** the membrane. This is the step an engineer
should stop at and ask "does this survive a robot".
- [membrane.py](immunoassay/membrane.py) - **read this one aloud.** The three constraints -
  probe clearance (a tip that rides too low scratches the membrane and prints false spots; it
  is CALIBRATE and blocks a hardware run until taught), no center-jet dispense, and never
  letting the membrane dry - are guarded values, not comments.
- [reagents/elispot_kit.py](immunoassay/reagents/elispot_kit.py) - the coat step; its
  concentration is TODO, transcribed from your kit, never guessed
- [stages/plate_prep.py](immunoassay/stages/plate_prep.py) - pre-wet uniformity is Gate 1

### 2. Block
**Bench:** block the coated membrane with serum medium. **Automated:** a dispense at the
membrane-safe height and mode.
- [stages/plate_prep.py](immunoassay/stages/plate_prep.py), block step in
  [reagents/elispot_kit.py](immunoassay/reagents/elispot_kit.py)

### 3. Add cells and stimulus, then incubate
**Bench:** plate PBMCs plus each well's antigen - test pools, the mitogen positive control,
medium-only negative control, no-cell blanks - and incubate undisturbed. **Automated:** the
plate layout *is* the science, so it is first-class data.
- [config.py](immunoassay/config.py) - `WellRole` and `PlateLayout`; the controls are roles,
  not conventions
- [stages/stimulation.py](immunoassay/stages/stimulation.py) - plates the cells; the
  do-not-disturb incubation is a recorded constraint

### 4. Wash off the cells (the step that makes or breaks the assay)
**Bench:** wash the cells off. Too gentle leaves debris that prints as background; too harsh
lifts the capture antibody. **Automated:** the programmed washer runs the same cycles, volume,
and probe height every time - which is the whole reason the line exists.
- [stages/develop.py](immunoassay/stages/develop.py) - the wash-heavy core
- [instruments/washer.py](immunoassay/instruments/washer.py) - the probe height comes from the
  site profile, not a washer default

### 5-7. Detection antibody, conjugate, substrate
**Bench:** biotinylated detection antibody, wash, streptavidin-enzyme conjugate, wash,
substrate. **Automated:** the same chain, at the membrane-safe dispense mode, each step
recorded.
- [stages/develop.py](immunoassay/stages/develop.py); the reagents and their provenance in
  [reagents/elispot_kit.py](immunoassay/reagents/elispot_kit.py)
- The substrate development endpoint is CALIBRATE: time-critical and lot-dependent, set by
  watching the first plate, then pinned - never implicit.

### 8. Image and count, then call the responses (Gate 2)
**Bench:** dry the plate, image it, count spots, decide which antigens are real. **Automated:**
this is the science gate.
- [instruments/imager.py](immunoassay/instruments/imager.py) - the count; in hardware it pauses
  with a run card and resumes when the counts file is supplied (a plate that develops overnight
  at a partner site resumes asynchronously)
- [stages/readout.py](immunoassay/stages/readout.py) - **plate validity first**: the mitogen
  positive control must fire and the background must be low, or the whole plate is void. Only
  then are responses called.
- [qc_math.py](immunoassay/qc_math.py) - the response call. Two methods: the conservative
  empirical net-plus-fold rule, and a distribution-free resampling permutation test (`dfr2x`,
  in the spirit of Moodie 2010) that uses the individual replicate counts. The demo uses
  `dfr2x`; the dossier shows the permutation p-value.

### 9. Results and the loop back
**Bench:** report SFU per antigen, decide what to change next time. **Automated:** the readout's
own numbers - background, saturation, replicate scatter - become concrete next-run parameter
deltas.
- [stages/handoff.py](immunoassay/stages/handoff.py) - the results table, the CSV, and the
  recommendations

---

## The three things to point at

1. **[membrane.py](immunoassay/membrane.py)** - reading a protocol like code and catching the
   step that will not survive a robot, encoded as a guard rather than a comment.
2. **Never invent** ([provenance.py](immunoassay/provenance.py)) - the kit's concentrations are
   TODO and the substrate endpoint is CALIBRATE; a hardware run calls
   `assert_ready_for_hardware()` and refuses to start until they are resolved.
3. **The response call** ([qc_math.py](immunoassay/qc_math.py)) - shipping the field's
   gold-standard distribution-free method, and being honest in the docstring about the
   triplicate p-value floor of 1/20 that the design itself imposes.

## What is real, and what is not

Simulation-first, on purpose. No ELISpot instrument has been driven from this yet: the washer
and imager integrations are the next build, and every hardware command is recorded as the Pi
command it *would* run, never as a claim that an instrument was driven. The `README.md` status
section says exactly what is validated and what is planned. That honesty is part of the point -
nothing here is stated more confidently than it has earned.
