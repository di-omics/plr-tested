# Hamilton STAR / PyLabRobot

Protocols and validation scripts for the Preventive Medicine Hamilton Microlab STAR controlled by PyLabRobot on `starpi`.

## Repository layout

- `setup/` - STARPI setup, SSH, USB, and safe startup notes.
- `protocols/resolve_dna/` - earlier ResolveDNA protocol scripts.
- `protocols/bio_validation0/pta_wga/` - current Bio Validation 0 PTA/WGA runners.
- `protocols/bio_validation0/ampseq/` - current Bio Validation 0 amplicon-seq scripts.
- `tests/liquid_handling/` - generic STAR liquid-handling validation scripts.
- `tests/resolve_dna/` - ResolveDNA-specific focused tests.
- `tests/movement/` - movement, lid, and iSWAP tests.
- `archive/` - preserved debugging checkpoints.

## Current active deck: Bio Validation 0 / rail35-48 layout

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

## Current PTA/WGA entrypoints

- `protocols/bio_validation0/pta_wga/run_pta_wga_dry_e2e.sh`
  - Dry observation only.
  - Uses `--return-tips`.
  - Deck check -> lysis add -> manual lysis handoff -> reaction add -> thermocycler handoff.

- `protocols/bio_validation0/pta_wga/run_pta_wga_REAL_DISCARD_TIPS_e2e.sh`
  - Real PTA/WGA runtime template.
  - Does not use `--return-tips`.
  - Requires typed confirmations before real lysis and reaction additions.

## Current amplicon-seq entrypoints

- `protocols/bio_validation0/ampseq/01_ampseq_pcr1_mastermix_col1.py`
  - Validated dry.
  - p50 transfer: 22.5 uL x8 complete PCR1 master mix.
  - Source rail35 pos1 col1 -> destination rail35 pos0 col1.

- `protocols/bio_validation0/ampseq/03_ampseq_pcr2_mastermix_col1.py`
  - Validated dry.
  - p50 transfer: 20.5 uL x8 common PCR2 master mix.
  - Source rail35 pos1 col1 -> destination rail35 pos0 col1.

- `protocols/bio_validation0/ampseq/02_ampseq_pcr1_cleanup_col1_dry_v2_p50low.py`
  - Validated first dry p50-low cleanup motion.
  - Intended next work: mock-liquid bead clean validation.

## EM-seq entrypoint (UltraShear + EM-seq v2)

- `starlab_live/emseq/` - end-to-end NEBNext Enzymatic Methyl-seq v2 with UltraShear
  fragmentation, single column, on the 35/48 deck. Reagent adds, ODTC thermal handoffs,
  and three SPRI cleanups. See `starlab_live/emseq/README.md`.
  - `run_emseq_odtc_1col_full_dry.py --print` shows the full 36-leg plan.
  - `run_emseq_odtc_1col_full_dry.py --sim-lh` runs the liquid-handling legs on the
    chatterbox (no hardware).
  - ODTC programs (`emseq-*`) live in `instrument-integrations/odtc/odtc_protocols.py`.
  - Status: written, simulation-first, not yet run on the instrument.

## scRNA-seq entrypoint (NEBNext Single Cell / Low Input RNA, E6420)

- `starlab_live/scrnaseq/` - end-to-end NEBNext Single Cell/Low Input RNA library prep
  (E6420 Section 1), single column, on the 35/48 deck. RT + template switching, cDNA
  amplification, fragment/ligate/enrich, with a two-round cDNA cleanup. See
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

1. Hamilton bead clean for amplicon-seq.
2. Embryo sample biovalidation: PTA, Viaflow/manual vs Hamilton.
3. Embryo sample biovalidation: amplicon-seq, Viaflow/manual vs Hamilton.
