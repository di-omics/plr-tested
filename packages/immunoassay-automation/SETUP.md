# Setup - from a cloned repo to a running ELISpot

The goal: a lab ports this repo to their instruments and runs the assay, and all they do is
the setup. There are two tiers. The first needs nothing. The second is the setup, and the
`doctor` command checks every step of it for you.

Run the doctor at any point to see where you are:

```bash
immunoassay doctor              # compute tier
immunoassay doctor --hardware   # compute + hardware tier, with the exact fix per gap
```

---

## Tier 1 - compute (zero setup, works immediately)

The simulation and all the QC math are standard-library Python. Nothing to install.

```bash
git clone https://github.com/di-omics/plr-tested
cd plr-tested/packages/immunoassay
python3 -m immunoassay demo
```

That runs the whole flow (Gate 0 -> plate prep -> stimulate -> develop -> Gate 2 -> handoff)
with deterministic synthetic reads and writes a dossier. A site can qualify the workflow, read
the rubric, train an operator, and see the gates stop a bad run (`--poor-washer`,
`--high-background`, `--dead-cells`) before an instrument is unboxed.

Optional niceties:

```bash
pip install -e .            # gives you the `immunoassay` command and YAML manifests
pip install -e '.[test]'    # to run `pytest`
```

`doctor` (no flag) should be all green after this.

---

## Tier 2 - hardware (this is "the setup")

Everything a real run needs, in the order `doctor --hardware` checks it.

### 1. PyLabRobot on the Pi

The line is driven from a Raspberry Pi through PyLabRobot. Install it on the Pi, then connect
the washer, the liquid handler (Opentrons Flex, or OT-2 / Hamilton STAR), and the imager.

### 2. Build the washer and imager integrations

These are not in this repo yet. Following the pattern of the repo's existing
`instrument-integrations/` (a `run_on_pi.sh` per instrument tree, geometry tuned by hand and
recorded in a dated header), build:

- `instrument-integrations/biotek-el406/` - the wash programs, the dispense ladder, and the
  aspiration-residual check the Gate 0 and develop stages call.
- `instrument-integrations/imager/` - the spot-count read the Gate 2 stage calls.

The adapters (`immunoassay/instruments/washer.py`, `imager.py`) already name the commands they
expect; point them at the real scripts once validated. A STAR-based ELISpot can reuse the
validated liquid handling in `hamilton-star/` today.

### 3. Teach the membrane clearance (per plate lot)

The single most important geometry value. Teach the wash/aspiration probe height on your
physical plate lot so the tip clears the PVDF membrane with margin, and pin it in the site
profile:

```yaml
site:
  aspiration_height_mm: 1.2   # the value you taught
```

A hardware run is blocked until this is set. A probe that rides too low scratches the membrane
and prints false spots - which is exactly why the value is measured, not guessed. Re-teach for
a new plate lot.

### 4. Calibrate the read (Gate 0)

If your Gate 0 uses the Rhodamine B fluorescence method, two values block a hardware run until
measured on your reader: the working concentration that lands the qualification volumes in the
linear range, and the reader gain, locked once on the brightest well. (A washer-only lab can
substitute the gravimetric dispense check; the CV gate is the same.)

### 5. Transcribe the kit values

The kit's antibody and conjugate concentrations are TODO, and the substrate development
endpoint is CALIBRATE. Transcribe the concentrations from your kit datasheet, set the
development endpoint by watching the first plate develop, and pin them. Until then the package
refuses to start a hardware run - that refusal is the never-invent rule, not a bug.

### 6. Confirm the validity and response cutoffs for your assay

The plate-validity bounds (positive-control floor, background ceiling), the replicate-CV
cutoff, the saturation ceiling, and the response-call thresholds are TUNABLE defaults in
`configs/acceptance_criteria.yaml`. Set them from your own assay and your kit's guidance.

---

## Then run it

```bash
immunoassay doctor --hardware        # expect all OK
immunoassay run my_run.yaml --hardware
```

In hardware mode each step resolves to the Pi command that runs it; the imager count pauses
with a run card and resumes when you supply the counts file. The package plans and gates; the
validated Pi scripts execute.
