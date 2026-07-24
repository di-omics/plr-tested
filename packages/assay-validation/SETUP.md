# Setup - from a cloned repo to a running assay

The goal: a lab ports this repo to their instrument and runs it, and all they do is the
setup. There are two tiers. The first needs nothing. The second is the setup, and the
`doctor` command checks every step of it for you.

Run the doctor at any point to see where you are:

```bash
assay-validate doctor              # compute tier
assay-validate doctor --hardware   # compute + hardware tier, with the exact fix per gap
```

---

## Tier 1 - compute (zero setup, works immediately)

The simulation and all the QC math are standard-library Python. Nothing to install.

```bash
git clone https://github.com/di-omics/plr-tested
cd plr-tested/packages/assay-validation
python3 -m assay_validation demo
```

That runs the whole flow (Gate 0 -> WGS preparation -> Gate 1 -> PCR enrichment -> Gate 2 -> handoff) with
deterministic synthetic reads and writes a dossier. A site can qualify the workflow, read
the rubric, and train an operator before an instrument is unboxed.

Optional niceties:

```bash
pip install -e .            # gives you the `assay-validate` command and YAML manifests
pip install -e '.[test]'    # to run `pytest`
```

`doctor` (no flag) should be all green after this. If it is, `assay-validate demo` works.

---

## Tier 2 - hardware (this is "the setup")

Everything a real run needs, in the order `doctor --hardware` checks it. Each item maps to
a place in this repo that already documents it.

### 1. PyLabRobot fork with the instrument backends

The STAR, ODTC, and Tecan backends live in the di-omics PyLabRobot fork. Install it on the
Pi (`starpi`) that drives the instruments:

```bash
pip install -e '.[usb]'     # from a checkout of the fork
```

`doctor --hardware` verifies `pylabrobot`, the STAR backend, and the fork-only
`pylabrobot.tecan.infinite` import.

### 2. Wire the instruments to the Pi

- **STAR**: USB cable to `starpi`. See `hamilton-star/setup/STARPI_Setup.md`.
- **ODTC**: on the network via a USB-Ethernet adapter (eth1), link-local 169.254/16.
  Give eth1 an address and discover the ODTC. See
  `instrument-integrations/odtc/README.md`, then:

  ```bash
  export ODTC_IP=<the address you discovered>
  ```

- **Tecan Infinite 200 PRO**: USB cable to the Pi. See
  `instrument-integrations/tecan-infinite/README.md`.

### 3. Tune the deck geometry

Deck geometry (offsets, heights, the iSWAP handoff legs into the ODTC) is tuned by hand
against the physical deck, one step at a time. The Validation layout this package
assumes is in `configs/deck_validation.yaml`. Site-specific consumable choices (which
tip-rack column to start from) are a manifest field, `tip_column`, not a code edit.

### 4. Calibrate the reader (Gate 0)

Two values block a hardware run until they are measured on your reader:

- the Rhodamine B working concentration that lands the qualification volumes in the 200
  PRO's linear range, and
- the reader gain, locked once on the brightest well.

Read a Rhodamine B dilution series on your reader, pick the concentration and gain, and pin
them. Until then the package refuses to start a hardware run - that refusal is the
never-invent rule, not a bug. This is also the moment the deck is qualified: Gate 0 will
only pass if the dispense CV is under the cutoff across the protocol's volumes.

### 5. Confirm the biology values for your workflow

Supply the required `method` block from your operator-approved local method. It records
the transfer volumes, cleanup ratios, QC dilutions and product volumes, annealing
temperature, cycle count, library-size checks, normalization target, and paths to the
three ODTC profiles. Hardware mode accepts only an `operator` profile; the bundled
profile is a synthetic water-only simulation.

Set the acceptance rubric in `configs/acceptance_criteria.yaml` from your samples and
instrument qualification data, including the fluorescent dsDNA yield floor and PCR
enrichment loading window.

---

## Then run it

```bash
assay-validate doctor --hardware        # expect all OK
assay-validate run my_run.yaml --hardware
```

In hardware mode each step resolves to the validated `run_on_pi.sh` command; a plate read
with no data yet pauses with a run card and resumes when you supply the results file. The
package plans and gates; the repo's validated scripts execute.
