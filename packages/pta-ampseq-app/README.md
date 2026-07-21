# whole-genome amplification + Targeted PCR bench planner

A local, planning-only wizard for the combined Hamilton STAR whole-genome amplification + HHS and
Targeted PCR + ODTC dry workflow.

The operator enters a sample count. The app converts it into the one-column
layout currently supported by the hardened dry runners, identifies sample and
blank wells, and presents the complete position-by-position deck checklist.
Sample count means biological samples only. The app does not add NTCs or
control wells, and there is no hidden control-well allowance.

## Safety boundary

This package cannot run hardware. It has no SSH, USB, Pi, PyLabRobot, process
launch, or instrument code. The server binds to `127.0.0.1`, and its arm API
always refuses requests.

No combined build is currently released through the app. The Hardware run
button remains locked while `pta_ampseq_app/data/releases/` contains no valid
combined physical-validation manifest. Adding such a manifest in the future
will make the release visible, but this planning-only package will still need a
separately reviewed execution layer before it can move metal.

## Current planning limit

- Accepted input: 1 through 8 biological samples.
- NTC/control allocation: none.
- Robot plan: one complete vertical column, A1 through H1.
- Fewer than 8 samples: remaining wells are explicit blanks.
- More than 8 samples: refused because no hardened combined multi-column build
  has been validated.

The planned mode is dry only: empty sacrificial labware, returned tips, no HHS
heating or shaking, and no ODTC command or heating.

## Run locally

```bash
cd packages/pta-ampseq-app
python3 -m pta_ampseq_app --port 8766
```

Then open `http://127.0.0.1:8766` in a browser on the same computer.

## Test

```bash
cd packages/pta-ampseq-app
python3 -m unittest discover -s tests -v
```

The tests are standard-library only and never connect to an instrument or the
network beyond a temporary localhost test server.
