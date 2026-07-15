# scRNA-seq (NEBNext Single Cell / Low Input RNA, E6420), Hamilton STAR + Inheco ODTC

End-to-end liquid handling and thermocycling for the NEBNext Single Cell/Low Input RNA
Library Prep Kit for Illumina (NEB #E6420), Section 1 "Protocol for Cells", single column,
on the current 35/48 deck.

Status: written and simulation-first. Nothing here has run on the instrument yet. Every
script runs on the STAR chatterbox backend (`--dry`) and every ODTC program runs on the
thermocycler chatterbox backend (`--dry`), but no leg has been tuned or confirmed on
hardware. See the status table below. Same repo rule as the rest of the tree: work that
has not met the instrument says so until a run says otherwise.

## What this automates

The E6420 Section 1 workflow, one 8-well column (A-H). The sample plate (rail35 pos0) is
the single plate that moves: to the ODTC nest for each thermal program, to the magnet for
each bead cleanup, and back. Reagents are added one per run from a swap-source column
(rail35 pos1), the same stepwise pattern as the confirmed PTA/WGA, ampseq, and emseq work.

Cells are sorted into 5 uL cold 1X Cell Lysis Buffer OFF-DECK (Section 1.2); the work
column starts holding those lysed cells. Workflow order (the choreography in
`run_scrnaseq_odtc_1col_full_dry.py`):

1. Primer annealing: add primer mix, ODTC `sc-anneal` (70 C 5 min).
2. Reverse transcription + template switching: add RT mix, ODTC `sc-rt` (42 C 90 min, 70 C 10 min).
3. cDNA amplification: add cDNA PCR mix, ODTC `sc-cdna-pcr` (default 18 cycles).
4. cDNA cleanup: `post-cdna` (0.6X, two-round SPRI with bead reconstitution re-bind).
5. Fragmentation / end prep: add FS mix, ODTC `sc-fs` (37 C 25 min, 65 C 30 min).
6. Adaptor ligation: add adaptor, then ligation mix, ODTC `sc-ligation` (20 C 15 min); then
   add USER enzyme, ODTC `sc-user` (37 C 15 min).
7. Cleanup: `post-ligation` (0.8X SPRI).
8. Library PCR: add index primers, then Q5 master mix, ODTC `sc-lib-pcr` (default 8 cycles).
9. Cleanup: `post-pcr` (0.9X SPRI). Final library eluate is 30 uL.

## Files

- `scrnaseq_reagent_adds.py` - one reagent addition per `--mode`, swap-source into work col 1.
  Modes: `primer-mix`, `rt-mix`, `cdna-pcr-mix`, `fs-mix`, `adaptor`, `ligation-mm`,
  `user-enzyme`, `pcr-primer`, `pcr-mm`. `--mode deck` assigns only. The 80 uL cDNA PCR mix
  is delivered as two 40 uL p50 transfers.
- `scrnaseq_cleanup.py` - the three SPRI cleanups. `--cleanup {post-cdna,post-ligation,post-pcr}`;
  `--mode all` runs the sequence, or one leg name to tune it. `post-cdna` is the two-round
  double cleanup.
- `run_scrnaseq_odtc_1col_full_dry.py` - the full choreography (32 executed legs + ODTC notes).
  `--print` shows the plan, `--sim-lh` runs the liquid-handling legs on the chatterbox,
  `--confirm RUN_SCRNASEQ_ODTC_FULL` runs the dry rehearsal on hardware.
- ODTC thermal programs live in `instrument-integrations/odtc/odtc_protocols.py`
  (`sc-anneal`, `sc-rt`, `sc-cdna-pcr`, `sc-fs`, `sc-ligation`, `sc-user`, `sc-lib-pcr`) and
  run via `05_odtc_run_protocol.py`.

## Deck (current 35/48 deck)

```
rail48 pos0 = p10 tips            rail48 pos1 = p50 tips        rail48 pos2 = p300 tips
rail35 pos0 = work plate (moves)  rail35 pos1 = reagent source (swap between reagent legs)
rail35 pos2 = magnet              rail35 pos3 = 12-well reservoir
rail20 pos1 = ODTC nest (empty, open to receive the plate)
```

Reservoir map (rail35 pos3): A1 beads, A2/A3 80% ethanol, A4 0.1X TE, A5 Bead Reconstitution
Buffer (post-cdna), A6 1X TE (post-cdna round 2), A12 waste.

## Reagent volumes (per reaction, single column)

All volumes are transcribed from the E6420 manual (v6.0), Section 1, no rounding.

| Step | Add | Tip | Reaction after |
|---|---|---|---|
| primer-mix | 4 uL (1 RT Primer Mix + 3 water) | p10 | 9 uL |
| rt-mix | 11 uL (5 RT Buffer + 1 TSO + 2 RT Enzyme + 3 water) | p50 | 20 uL |
| cdna-pcr-mix | 80 uL (50 cDNA PCR MM + 2 primer + 28 water) | p50 x2 | 100 uL |
| cleanup post-cdna | 60 uL beads (0.6X), double; elute 50 then 33, keep 30 | p300/p50 | 30 uL |
| fs-mix | 9 uL (7 FS buffer + 2 FS enzyme) | p50 | 35 uL |
| adaptor | 2.5 uL (1:25 diluted) | p10 | 37.5 uL |
| ligation-mm | 31 uL (30 ligation MM + 1 enhancer) | p50 | 68.5 uL |
| user-enzyme | 3 uL USER | p10 | 71.5 uL |
| cleanup post-ligation | 57 uL beads (0.8X), elute 17, keep 15 | p300/p50 | 15 uL |
| pcr-primer | 10 uL index mix (i7 + i5) | p50 | 25 uL |
| pcr-mm | 25 uL Q5 MM | p50 | 50 uL |
| cleanup post-pcr | 45 uL beads (0.9X), elute 33, keep 30 | p300/p50 | 30 uL |

Section 2 ("Low Input RNA") shares the ODTC programs and the fragment/ligate/enrich back
half; the differences are the total-RNA front end (no cell lysis) and one extra 0.5 uL Cell
Lysis Buffer in the cDNA amplification mix (Section 2.4.1). Not separately scripted here.

## Sourcing

- NEB #E6420 NEBNext Single Cell/Low Input RNA Library Prep Kit manual, Version 6.0 (01/24),
  Section 1 "Protocol for Cells". Only functional parameters (volumes, temperatures, times,
  cycles, bead ratios) are transcribed, each cited on the line where it is used in the code.

## What "tested" means here (status)

Nothing below is validated. "sim" = ran on a device-free chatterbox backend on this machine,
which proves the stage/step and command structure only, not geometry, not the lid, not heat,
not liquid classes.

ODTC thermal programs (`instrument-integrations/odtc`):

| What | Result |
|---|---|
| 7 sc-* programs generate valid method XML, all temps in 4-99 C, lids <= 105 C | passed, sim |
| sc-cdna-pcr / sc-lib-pcr loops encode GotoNumber 2 / LoopNumber N-1 | passed, sim |
| Run any sc-* program on the instrument at real temperatures | written, not yet run |

STAR liquid handling (`hamilton-star/starlab_live/scrnaseq`):

| What | Result |
|---|---|
| All 9 reagent-add modes, `--mode deck` and `--dry` | passed, sim |
| All 3 SPRI cleanups (incl. the post-cdna double), `--mode all --dry` | passed, sim |
| Full choreography liquid-handling legs, `--sim-lh` (12 legs, exit 0) | passed, sim |
| Any reagent add or cleanup on the instrument | written, not yet run |
| iSWAP handoff into the ODTC nest for the scRNA plate | reuses ampseq-confirmed legs, not re-run |

Known gaps that MUST be closed on hardware before trusting a real run:

- Dispense geometry is reused verbatim from the confirmed ampseq/PTA-WGA column-1 adds, tuned
  for adding into a small starting volume. Several scRNA adds go into a fuller well and the
  near-bottom dispense height (0.5 mm) needs tuning for high-volume adds before a wet run.
- No on-deck mixing. The manual asks for 10x pipette mixing at most steps; these scripts add
  and blow out only. Mixing stays an operator step until tuned.
- The post-cdna double cleanup discards 16 tip-columns, more than one 12-column p300 rack, so
  a real run needs a mid-cleanup tip replenishment (the deck has one tip rack at rail48).
- SPRI cleanups do not model the RT bead incubation, air-dry timings, or the final "transfer
  clear eluate off the beads to a fresh column" step. Those are operator/off-deck.
- The ODTC child-location coordinate is still a repo placeholder
  (`ODTC_CHILD_LOCATION_IS_MEASURED = False`); the iSWAP-into-ODTC geometry is inherited from
  the ampseq choreography and has not been re-confirmed for this workflow.

## Controls and acceptance criteria

Controls. Unlike the EM-seq kit, E6420 has no built-in spike-in control. Recommended: a
no-cell / no-template negative control well (to catch contamination and adaptor-dimer), and a
positive control of a known cell line or Universal Human Reference (UHR) RNA at a defined
input, run with the manual's recommended cycle count for that input.

RNA safety. Single-cell RNA is contamination- and RNase-sensitive. Tips are discarded, never
returned, on real runs (the default). Keep reagents cold; Murine RNase Inhibitor is in the
lysis buffer. Cells must be washed into PBS before sorting (media carryover hurts RT).

Acceptance criteria for a real run (from the manual):
- cDNA yield after the post-cdna cleanup typically 1-20 ng (Section 1.5, 1.7); quantify before
  library prep and adjust library PCR cycles if outside 1-20 ng.
- Final library: narrow distribution peaking at 300-350 bp on a Bioanalyzer HS chip (Section
  1.13). A ~80 bp (primer) or 128-140 bp (adaptor-dimer) peak means repeat the 0.9X cleanup.
- Typical library yield 100 ng - 1 ug at 8 library-PCR cycles for 1-20 ng cDNA input.

## Running

```bash
python run_scrnaseq_odtc_1col_full_dry.py --print     # review the 32-leg plan
python run_scrnaseq_odtc_1col_full_dry.py --sim-lh     # exercise the LH legs locally, no hardware

# on the Pi: deck check every leg (assignment only, no motion)
./hamilton-star/run_on_pi.sh starlab_live/scrnaseq/scrnaseq_reagent_adds.py --mode deck
./hamilton-star/run_on_pi.sh starlab_live/scrnaseq/scrnaseq_cleanup.py --cleanup post-cdna --mode deck

# an ODTC program (this heats; human at the E-stop)
./instrument-integrations/run_on_pi.sh odtc/05_odtc_run_protocol.py --program sc-rt --dry
```

Cycle counts are input-dependent: `sc-cdna-pcr` defaults to 18 (HEK single cell; E6420 table
in Section 1.5), `sc-lib-pcr` to 8 (1-20 ng cDNA). Build `sc_cdna_pcr(num_cycles=...)` /
`sc_lib_pcr(num_cycles=...)` to change.

## Safety

Same rules as the rest of this repo. Assume a script drives real hardware unless it names an
exception (`--mode deck`, `--dry`, `--sim-lh`, `--print`). Never run unattended, a person
watches with a hand near the E-stop. Run `--mode deck` first. The full choreography moves the
arm through 7 ODTC round trips and 3 magnet round trips and is gated behind
`--confirm RUN_SCRNASEQ_ODTC_FULL`. Both PCR programs denature at 98 C (1 C under the ODTC
99 C ceiling; expect out-of-spec warnings, not faults). Only one process may drive an
instrument at a time.

## Research use only

Automates a published NEBNext kit protocol (public NEB manual E6420). Not a product, not
validated for diagnostic use.
