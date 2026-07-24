# Hamilton STAR / PyLabRobot

Protocols and validation scripts for a Hamilton Microlab STAR controlled by PyLabRobot on `starpi`.

## Repository layout

- `setup/` - STARPI setup, SSH, USB, and safe startup notes.
- `protocols/whole_genome_seq/` - earlier whole-genome sequencing preparation protocol scripts.
- `protocols/validation/wgs_prep/` - current sequencing validation WGS preparation runners.
- `protocols/validation/pcr_enrichment/` - current PCR-enrichment hardware-validation scripts.
- `tests/liquid_handling/` - generic STAR liquid-handling validation scripts.
- `tests/whole_genome_seq/` - whole-genome sequencing preparation-specific focused tests.
- `tests/movement/` - movement, lid, and iSWAP tests.
- `archive/` - preserved debugging checkpoints.

## Current active deck: sequencing validation / rail35-48 layout

```text
rail48 pos0 = p10 tips
rail48 pos1 = p50 tips
rail35 pos0 = destination/work plate or strip
rail35 pos1 = source/reagent plate or strip
```

Cleanup development may additionally use:

```text
rail35 pos2 = cleanup/magnet plate
rail35 pos3 = trough/reservoir
```

## Current whole-genome sequencing entrypoints

- `protocols/validation/wgs_prep/run_wgs_prep_dry_e2e.sh`
  - Dry observation only.
  - Uses `--return-tips`.
  - Deck check -> operator-defined stage 1 -> manual handoff -> operator-defined stage 2.

- `protocols/validation/wgs_prep/run_wgs_prep_REAL_DISCARD_TIPS_e2e.sh`
  - Real whole-genome sequencing runtime template.
  - Does not use `--return-tips`.
  - Requires typed confirmations before operator-defined wet additions.

## Current PCR-enrichment entrypoints

Wet-method volumes, ratios, sample assignments, and thermal settings are required
operator parameters loaded from `PLR_METHOD_PARAMETERS_FILE`. Public runs and examples
are synthetic and water-only.

- `protocols/validation/pcr_enrichment/01_pcr_enrichment_round1_mastermix_col1.py`
  - Validated dry.
  - p50 transfer volume is required from the operator profile.
  - Source rail35 pos1 col1 -> destination rail35 pos0 col1.

- `protocols/validation/pcr_enrichment/03_pcr_enrichment_round2_mastermix_col1.py`
  - Validated dry.
  - p50 transfer volume is required from the operator profile.
  - Source rail35 pos1 col1 -> destination rail35 pos0 col1.

- `protocols/validation/pcr_enrichment/02_pcr_enrichment_round1_cleanup_col1_dry_v2_p50low.py`
  - Validated first dry p50-low cleanup motion.
  - Intended next work: mock-liquid bead clean validation.

## Methylation-sequencing entrypoint

- `starlab_live/methylation_seq/` - end-to-end methylation-sequencing workflow with fragmentation
  in a single column on the 35/48 deck. Reagent adds, ODTC thermal handoffs, and three
  SPRI cleanups. See `starlab_live/methylation_seq/README.md`.
  - `run_methylation_seq_odtc_1col_full_dry.py --print` shows the full 36-leg plan.
  - `run_methylation_seq_odtc_1col_full_dry.py --sim-lh` runs the liquid-handling legs on the
    chatterbox (no hardware).
  - ODTC programs (`methylation_seq-*`) live in `instrument-integrations/odtc/odtc_protocols.py`.
  - Status: written, simulation-first, not yet run on the instrument.

## scRNA-seq entrypoint

- `starlab_live/scrnaseq/` - end-to-end scRNA-seq library-preparation motion
  scaffold, single column, on the 35/48 deck. Biological stage identities and
  optional second cleanup-stage settings come from operator-owned profiles. See
  `starlab_live/scrnaseq/README.md`.
  - `run_scrnaseq_odtc_1col_full_dry.py --print` shows the full 32-leg plan.
  - `run_scrnaseq_odtc_1col_full_dry.py --sim-lh` runs the liquid-handling legs on the
    chatterbox (no hardware).
  - ODTC programs (`sc-*`) live in `instrument-integrations/odtc/odtc_protocols.py`.
  - Status: written, simulation-first, not yet run on the instrument.

## TIP-seq entrypoint (targeted insertion of promoters, JCB 2021)

- `starlab_live/tipseq/` - the automatable T7 linear-amplification + library back half of
  TIP-seq (CUT&Tag + pA-Tn5 tagmentation front end is off-deck). Gap-fill, T7 IVT (overnight),
  RT, second-strand, Tn5 fragmentation, indexing PCR, with retained-bead SPRI reactivation
  cleanups. See `starlab_live/tipseq/README.md`.
  - `run_tipseq_odtc_1col_full_dry.py --print` shows the full 39-leg plan.
  - `run_tipseq_odtc_1col_full_dry.py --sim-lh` runs the liquid-handling legs on the chatterbox.
  - ODTC programs (`tip-*`) live in `instrument-integrations/odtc/odtc_protocols.py`.
  - Status: written, simulation-first, not yet run on the instrument.

## Current priorities

1. Hamilton bead clean for PCR enrichment.
2. Low-input sample assay validation: WGS preparation, Viaflow/manual vs Hamilton.
3. Low-input sample assay validation: PCR enrichment, Viaflow/manual vs Hamilton.
