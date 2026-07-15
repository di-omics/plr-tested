# TIP-seq (targeted insertion of promoters), Hamilton STAR + Inheco ODTC

End-to-end liquid handling and thermocycling for the automatable back half of TIP-seq: T7
RNA-polymerase linear amplification and sequencing-library preparation, single column, on the
current 35/48 deck.

Status: written and simulation-first. Nothing here has run on the instrument yet. Every script
runs on the STAR chatterbox backend (`--dry`) and every ODTC program runs on the thermocycler
chatterbox backend (`--dry`), but no leg has been tuned or confirmed on hardware. Same repo rule
as the rest of the tree: work that has not met the instrument says so until a run says otherwise.

## What this automates (and what it does not)

TIP-seq combines CUT&Tag pA-Tn5 tagmentation with T7 linear amplification. The CUT&Tag front
end - conA magnetic beads, primary/secondary antibody, pA-Tn5 binding, tagmentation, and (for
single cell / sciTIP) FACS sorting into wells - is OFF-DECK operator work and is not scripted
here (it is not a liquid-handler-standard flow). Automation begins at the paper's "single-tube"
back half: the tagmented gDNA is SPRI-purified and the DNA + SPRI beads are resuspended in 8 uL
water, and the work column starts holding that. The SPRI beads are RETAINED in the well through
IVT, RT, and second-strand synthesis, and are re-bound with SPRI binding buffer at each
intermediate cleanup; they are only left behind at the final DNA purification before PCR.

Workflow order (the choreography in `run_tipseq_odtc_1col_full_dry.py`):

1. Gap fill: add Taq mix, ODTC `tip-gapfill` (72 C 3 min).
2. T7 IVT: add IVT mix, ODTC `tip-ivt` (37 C 16-19 h, default 17 h - overnight).
3. RNA cleanup: `post-ivt` (2.0X binding-buffer reactivation, elute 9 uL RNase-free water).
4. First-strand RT: add random hexamer, ODTC `tip-rt-anneal` (70 C 3 min); add RT mix, ODTC
   `tip-rt` (22 C 10 min, 42 C 60 min, 70 C 10 min); add RNase H, ODTC `tip-rnaseh` (37 C 20 min).
5. Second-strand: add sss oligo, ODTC `tip-ss-anneal` (65 C 2 min); add Taq, ODTC `tip-ss` (72 C 8 min).
6. cDNA cleanup: `post-ss` (2.0X reactivation, elute 7 uL water).
7. cDNA fragmentation: add Tn5 (ME-B) mix, ODTC `tip-tag` (55 C 6 min); operator adds GuHCl to 4 M.
8. DNA cleanup: `post-tag` (2.0X reactivation, elute 16 uL, transfer off the beads).
9. Indexing PCR: add PCR mix, ODTC `tip-pcr` (default 8 cycles).
10. Library cleanup: `post-pcr` (0.85X left-side size selection, > 200 bp).

## Files

- `tipseq_reagent_adds.py` - one reagent addition per `--mode`, swap-source into work col 1.
  Modes: `gapfill-mix`, `ivt-mix`, `hexamer`, `rt-mix`, `rnaseh`, `sss-oligo`, `ss-taq`,
  `tn5-mix`, `pcr-mix`. `--mode deck` assigns only.
- `tipseq_cleanup.py` - the four SPRI cleanups. `--cleanup {post-ivt,post-ss,post-tag,post-pcr}`;
  `--mode all` runs the sequence, or one leg name to tune it. post-ivt/post-ss/post-tag re-bind the
  retained beads with 2.0X SPRI binding buffer; post-pcr uses fresh 0.85X beads for size selection.
- `run_tipseq_odtc_1col_full_dry.py` - the full choreography (39 executed legs + operator notes).
  `--print`, `--sim-lh`, `--confirm RUN_TIPSEQ_ODTC_FULL`.
- ODTC thermal programs live in `instrument-integrations/odtc/odtc_protocols.py` (`tip-gapfill`,
  `tip-ivt`, `tip-rt-anneal`, `tip-rt`, `tip-rnaseh`, `tip-ss-anneal`, `tip-ss`, `tip-tag`,
  `tip-pcr`) and run via `05_odtc_run_protocol.py`.

## Deck (current 35/48 deck)

```
rail48 pos0 = p10 tips            rail48 pos1 = p50 tips        rail48 pos2 = p300 tips
rail35 pos0 = work plate (moves)  rail35 pos1 = reagent source (swap between reagent legs)
rail35 pos2 = magnet              rail35 pos3 = 12-well reservoir
rail20 pos1 = ODTC nest (empty, open to receive the plate)
```

Reservoir map (rail35 pos3): A1 fresh SPRI beads (post-pcr), A2/A3 80% ethanol, A4 RNase-free
water, A5 SPRI binding buffer (2.0X reactivation), A6 nuclease-free water, A7 10 mM Tris pH 8.0,
A12 waste.

## Reagent volumes (per reaction, single column)

All volumes transcribed from Bartlett et al., TIP-seq (JCB 2021, e202103078), Materials and
methods, "Bulk TIP-seq".

| Step | Add | Tip | Reaction after |
|---|---|---|---|
| gapfill-mix | 2 uL Taq 5X MM | p10 | 10 uL |
| ivt-mix | 6.3 uL (2 NTP + 2 T7 buffer + 2 T7 pol + 0.3 RNase inh) | p50 | 16.3 uL |
| cleanup post-ivt | 2.0X binding buffer, elute 9 uL RNase-free water | p300/p50 | 9 uL |
| hexamer | 2.5 uL random hexamer | p10 | 11.5 uL |
| rt-mix | 8.5 uL (4 buffer + 2 dNTP + 2 DTT + 0.5 MMLV) | p50 | 20 uL |
| rnaseh | 1 uL RNase H (1:10) | p10 | 21 uL |
| sss-oligo | 2.5 uL second-strand oligo | p10 | 23.5 uL |
| ss-taq | 5.9 uL Taq 5X MM | p50 | 29.4 uL |
| cleanup post-ss | 2.0X binding buffer, elute 7 uL water | p300/p50 | 7 uL |
| tn5-mix | 4 uL (2 TAPS + 2 Tn5 ME-B) | p10 | 11 uL |
| (operator) GuHCl to 4 M final; cleanup post-tag 2.0X, elute 16 uL off beads | | p300/p50 | 16 uL |
| pcr-mix | 24 uL (20 2X PCR MM + 2 index + 2 i7) | p50 | 40 uL |
| cleanup post-pcr | 0.85X fresh beads, left-side size select (> 200 bp) | p300/p50 | ~21 uL |

## Sourcing

- Bartlett, Dileep, Handa, Ohkawa, Kimura, Henikoff, Gilbert. "High-throughput single-cell
  epigenomic profiling by targeted insertion of promoters (TIP-seq)." J. Cell Biol. 2021,
  220(12):e202103078. https://doi.org/10.1083/jcb.202103078 . Materials and methods, "Bulk
  TIP-seq" (linear-amp + library steps) and the PCR profile from "CUT&Tag". Only functional
  parameters are transcribed, each cited on the line where it is used in the code.

Two values are choices, not transcriptions (flagged in code): the tip-ivt duration (17 h,
within the paper's 16-19 h) and the lid temperature for the 37 C steps (47 C; the paper uses an
incubator and gives no lid). tip-pcr holds at 8 C as written.

## What "tested" means here (status)

Nothing below is validated. "sim" = ran on a device-free chatterbox backend on this machine.

| What | Result |
|---|---|
| 9 tip-* ODTC programs generate valid method XML, temps in 4-99 C, lids <= 105 C | passed, sim |
| tip-pcr loop encodes GotoNumber 3 / LoopNumber 7 | passed, sim |
| `odtc_offline_checks.py` after tip-* additions | passed, sim (205/205) |
| All 9 reagent-add modes, `--mode deck` and `--dry` | passed, sim |
| All 4 SPRI cleanups, `--mode all --dry` | passed, sim |
| Full choreography liquid-handling legs, `--sim-lh` (13 legs, exit 0) | passed, sim |
| Any reagent add, cleanup, or ODTC program on the instrument | written, not yet run |

Known gaps that MUST be closed on hardware before trusting a real run:

- The work well holds SPRI beads from the start; the reused reagent-add geometry was tuned for
  beadless wells and small volumes and needs tuning (dispense height, mixing) before a wet run.
- No on-deck mixing; the paper mixes by pipetting/vortex. Operator step until tuned.
- The post-tag reaction volume includes operator-added GuHCl to 4 M final (stock-dependent), so
  the post-tag bind/supernatant volumes are estimates. The post-pcr elution volume and the
  left-side size selection are user-chosen; the value here is a plate-flow placeholder.
- tip-ivt is a 16-19 h hold that ties up the ODTC overnight; launch it detached on the Pi.
- Ethanol wash volume (200 uL) is the repo default; the paper says "wash twice with 80% EtOH"
  without a volume.
- The ODTC child-location coordinate is still a repo placeholder
  (`ODTC_CHILD_LOCATION_IS_MEASURED = False`); the iSWAP-into-ODTC geometry is inherited from the
  ampseq choreography and not re-confirmed for this workflow.

## Controls and acceptance criteria

Controls. The paper runs normal IgG as a negative control (TIP-seq for IgG in Fig. 2 A) and
compares to bulk/ENCODE reference tracks. Recommended: an IgG (no-target-antibody) negative
control well, plus a positive control antibody (e.g. H3K27me3 or CTCF) at a defined cell number.
Single-cell/sciTIP additionally uses a mixed-species barnyard for the collision (cross-
contamination) rate.

RNA safety. TIP-seq carries RNA intermediates (post-IVT RNA, first-strand RT). Tips are
discarded, never returned, on real runs (the default); keep RNase-free.

Acceptance criteria (from the paper):
- Post-PCR library checked on a TapeStation HS D1000 for a proper size distribution before pooling.
- Left-side size selection at 0.85X SPRI to remove < 200 bp fragments (primers/adapter dimer).
- Sensitivity: TIP-seq gives ~10-fold higher unique reads per single cell than PCR-based CUT&Tag;
  bulk libraries correlate with ENCODE ChIP-seq (Pearson r ~0.54-0.65 for CTCF).

## Running

```bash
python run_tipseq_odtc_1col_full_dry.py --print     # review the 39-leg plan
python run_tipseq_odtc_1col_full_dry.py --sim-lh     # exercise the LH legs locally, no hardware

# on the Pi: deck check every leg (assignment only, no motion)
./hamilton-star/run_on_pi.sh starlab_live/tipseq/tipseq_reagent_adds.py --mode deck
./hamilton-star/run_on_pi.sh starlab_live/tipseq/tipseq_cleanup.py --cleanup post-tag --mode deck

# the overnight IVT program (this heats; launch detached; human at the E-stop)
./instrument-integrations/run_on_pi.sh odtc/05_odtc_run_protocol.py --program tip-ivt --dry
```

PCR cycle count is optimized per sample (bulk ~7-9, sciTIP 7-12); `tip-pcr` defaults to 8.
Build `tip_pcr(num_cycles=...)` or `tip_ivt(ivt_hours=...)` to change.

## Safety

Same rules as the rest of this repo. Assume a script drives real hardware unless it names an
exception (`--mode deck`, `--dry`, `--sim-lh`, `--print`). Never run unattended; run `--mode deck`
first. The full choreography moves the arm through 9 ODTC round trips (one overnight) and 4 magnet
round trips and is gated behind `--confirm RUN_TIPSEQ_ODTC_FULL`. tip-pcr denatures at 98 C (1 C
under the ODTC 99 C ceiling; expect out-of-spec warnings, not faults). Only one process may drive
an instrument at a time.

## Research use only

Automates a published, peer-reviewed research method (TIP-seq, JCB 2021). Not a product, not
validated for diagnostic use. Custom oligos and the pA-Tn5 / ME-T7 transposons are prepared per
the paper and its Table S1; not provided here.
