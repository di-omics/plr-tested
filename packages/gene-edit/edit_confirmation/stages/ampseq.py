"""
stages/ampseq.py - pull the edit locus out of the PTA product and index it.

This is the targeted library prep. It amplifies the region around the edit with locus
primers (PCR1), cleans off primer dimers, adds sample indices (PCR2), and cleans again
to the loading window. It runs only on the wells that passed the post-PTA yield gate, so
no reagent is spent building a library from a cell that did not amplify.

The four liquid-handling steps map to the validated repo scripts, and the two thermal
programs map to the ODTC's ampseq-pcr1 / ampseq-pcr2. Master-mix volumes and SPRI ratios
are transcribed from those scripts. The PCR1 annealing temperature comes from the locus
(the operator recomputes it for their primer set) or falls back to the protocol default;
the PCR2 cycle count comes from the run config within the protocol's 8 to 10 range.

No gate here. Gate 2 (post-ampseq PicoGreen) follows and decides what reaches sequencing.
"""

from __future__ import annotations

from ..provenance import transcribed
from ..reagents.spri import post_pcr1_plan, post_pcr2_plan
from .base import Stage, StageContext, StageResult, StageStatus

# Master-mix volumes, transcribed from the validated STAR scripts.
PCR1_MM_UL = transcribed(
    22.5, "01_ampseq_pcr1_mastermix_col1.py: 22.5 uL complete PCR1 master mix",
    unit="uL", name="pcr1_mm_volume",
)
PCR2_MM_UL = transcribed(
    20.5, "03_ampseq_pcr2_mastermix_col1.py: 20.5 uL common PCR2 master mix",
    unit="uL", name="pcr2_mm_volume",
)


class AmpliconSeq(Stage):
    name = "ampseq"
    title = "Amplicon-seq library prep (edit locus)"

    def run(self, ctx: StageContext) -> StageResult:
        mark = ctx.action_mark()
        samples = ctx.active_samples()
        locus = ctx.config.locus
        anneal = locus.pcr1_anneal_c  # None -> ODTC uses the protocol default 67 C

        # PCR1: target amplification.
        ctx.star.add_mastermix("PCR1", float(PCR1_MM_UL.value), "p50",
                               "01_ampseq_pcr1_mastermix_col1.py")
        ctx.star.iswap_move("work_plate", "odtc")
        pcr1_ref = ctx.odtc.run_program("ampseq-pcr1", anneal_c=anneal)
        ctx.star.iswap_move("odtc", "work_plate")

        # Anti-dimer clean.
        spri1 = post_pcr1_plan()
        ctx.star.spri_clean(spri1)

        # PCR2: indexing.
        ctx.star.add_mastermix("PCR2", float(PCR2_MM_UL.value), "p50",
                               "03_ampseq_pcr2_mastermix_col1.py")
        ctx.star.iswap_move("work_plate", "odtc")
        pcr2_ref = ctx.odtc.run_program("ampseq-pcr2", num_cycles=ctx.config.pcr2_cycles)
        ctx.star.iswap_move("odtc", "work_plate")

        # Final clean to the loading window.
        spri2 = post_pcr2_plan()
        ctx.star.spri_clean(spri2)

        return StageResult(
            name=self.name,
            title=self.title,
            status=StageStatus.COMPLETED,
            message=(f"library prep on {len(samples)} well(s); "
                     f"PCR1 anneal {anneal if anneal is not None else 'protocol default (67 C)'}, "
                     f"PCR2 {ctx.config.pcr2_cycles} cycles"),
            data={
                "n_wells": len(samples),
                "wells": [s.well for s in samples],
                "locus": locus.name,
                "amplicon_bp": locus.amplicon_bp,
                "pcr1_anneal_c": anneal,
                "pcr1_program": pcr1_ref.name,
                "pcr1_note": pcr1_ref.note,
                "pcr2_program": pcr2_ref.name,
                "pcr2_cycles": ctx.config.pcr2_cycles,
                "spri_post_pcr1": spri1.as_text(),
                "spri_post_pcr2": spri2.as_text(),
            },
            actions=ctx.actions_since(mark),
        )
