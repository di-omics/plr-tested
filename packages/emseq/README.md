# emseq

QC-gated NEBNext Enzymatic Methyl-seq v2 library preparation with UltraShear
fragmentation, built around the Hamilton STAR and Inheco ODTC work already in this repo.

This is the product layer over `hamilton-star/starlab_live/emseq/` and the eight
`emseq-*` programs in `instrument-integrations/odtc/odtc_protocols.py`. It accepts a
sparse manifest, resolves the exact low- or high-input chemistry route, produces a
sourced 24-step run card, simulates the complete flow, applies library/conversion QC
gates, and writes an auditable dossier plus sequencing handoff.

Status: **complete in deterministic simulation; blocked for live sample execution.**
The underlying EM-seq scripts are written/simulation-first and have not run on the
physical instruments. The package keeps that distinction mechanical: `mode: hardware`
writes a blocked run card and cannot move or heat anything.

## What was already on GitHub

There were two useful EM-seq implementations before this package:

- `di-omics/ot-flex-automation` contains an Opentrons Flex EM-seq v2 protocol, with
  fragmentation performed before that protocol.
- This repo already contains the exact Hamilton STAR + ODTC **UltraShear-coupled**
  implementation: 11 reagent-add modes, three SPRI cleanup presets, eight thermal
  programs, and a one-column full choreography.

This package productizes the second implementation instead of creating a duplicate
repository.

## The route

```
manifest + Gate 0 deck qualification
  -> UltraShear fragmentation
  -> coupled End Prep
  -> adaptor ligation
  -> 1.1X SPRI
  -> TET2/T4-BGT protection + Fe(II) + stop
  -> 1.0X SPRI
  -> formamide denaturation
  -> APOBEC deamination
  -> indexed Q5U PCR
  -> 0.8X SPRI
  -> TapeStation + lambda/pUC19 conversion QC
  -> passing-library sample sheet
```

The protocol source is **NEB #M7634 v3.0 (3/26), Section 3**, the coupled workflow.
The standalone E8015 recipe is not interchangeable with this route.

## Quickstart

```bash
cd packages/emseq
python -m emseq_automation doctor
python -m emseq_automation plan configs/example_run.json
python -m emseq_automation demo
python -m unittest discover -s tests -v
```

Or install the command:

```bash
pip install -e .
emseq-run doctor
emseq-run demo
```

`demo` writes `outcome.json`, `dossier.html`, `run_card.md`, and
`sequencing_samplesheet.csv` under `runs/<run_id>/`.

To evaluate measured QC instead of synthetic data:

```bash
emseq-run run configs/example_run.json --metrics configs/example_metrics.json
```

## Manifest rules that prevent silent chemistry errors

- Inputs must be 0.1-200 ng double-stranded DNA.
- One run is one current hardware column: wells A1-H1 only.
- Every well has a unique NEBNext LV UDI.
- A column cannot mix `<=10 ng` and `>10 ng` samples. The low-input route uses carrier
  DNA, diluted T4-BGT, and a different post-ligation elution.
- Control-DNA dilutions are filled only for the four rows explicitly given by M7634
  (0.1, 1, 10, and 200 ng). Other inputs must record an operator-selected dilution.
- PCR cycles are inferred only for unambiguous table rows (0.1, 1, and 10 ng). A table
  range or an unlisted input requires an explicit manifest value.
- The current STAR implementation supports the recommended formamide route only.

## Gates

Gate 0 requires a liquid-handling CV measurement at every distinct protocol transfer
volume. Missing data fails the gate; a partial qualification is not treated as a pass.

Final QC requires the manual's minimum control coverage (5,000 paired lambda reads and
500 paired pUC19 reads) plus visible, configurable conversion/protection, size, yield,
and process-blank criteria. The latter are marked `TUNABLE`, not presented as NEB claims.

## Why live execution is blocked

The hardware doctor enumerates the current gaps:

```bash
emseq-run doctor --hardware
```

- Tune 31 and 45 uL additions into already-full wells.
- Implement and dye-test the required 10x mixing.
- Automate cleanup incubation/air-dry timing and clear-eluate transfer.
- Measure the ODTC child coordinate and run all eight programs on the instrument.
- Validate the 50 C ligation-lid substitution and ODTC cool-down after denaturation.
- For low input, implement the 1 uL carrier-DNA addition.

The current choreography also requires operator reagent swaps, sealing/spinning, and
instrument-state reconciliation. It is end-to-end as a sourced plan and simulation, but
it is not yet walkaway or hardware-validated.

## Research use only

Automates public NEB kit instructions. Not validated for diagnostic use. Never run the
instruments unattended; use the repo's deck-check and E-stop rules for every hardware
qualification leg.

