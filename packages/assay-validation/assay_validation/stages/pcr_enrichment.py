"""
stages/pcr_enrichment.py - enrich a target locus from the WGS-preparation product and index it.

This is targeted library preparation. It amplifies a configured region with locus
primers (PCR1), cleans off primer dimers, adds sample indices (PCR2), and cleans again
to the loading window. It runs only on the wells that passed the post-whole-genome sequencing preparation yield gate, so
no reagent is spent building a library from a cell that did not amplify.

The liquid-handling and thermal values come from the required run-manifest method
profile; the public package does not supply a biological recipe.

No gate here. Gate 2 (post-PCR-enrichment fluorescent dsDNA assay) follows and decides what reaches sequencing.
"""

from __future__ import annotations

from ..reagents.spri import plan
from .base import Stage, StageContext, StageResult, StageStatus


class PCREnrichment(Stage):
    name = "pcr_enrichment"
    title = "PCR enrichment library preparation (target locus)"

    def run(self, ctx: StageContext) -> StageResult:
        mark = ctx.action_mark()
        samples = ctx.active_samples()
        locus = ctx.config.locus
        method = ctx.config.method
        anneal = method.pcr1_anneal_c

        ctx.star.add_mastermix("PCR1", method.pcr_stage_1_transfer_ul, "p50",
                               "01_pcr_enrichment_round1_mastermix_col1.py")
        ctx.star.iswap_move("work_plate", "odtc")
        pcr1_ref = ctx.odtc.run_program(method.pcr1_odtc_profile)
        ctx.star.iswap_move("odtc", "work_plate")

        spri1 = plan(
            "post-stage-1 cleanup",
            method.post_pcr1_cleanup_ratio,
            method.pcr_reaction_volume_ul,
            method.supernatant_margin_ul,
        )
        ctx.star.spri_clean(spri1)

        ctx.star.add_mastermix("PCR2", method.pcr_stage_2_transfer_ul, "p50",
                               "03_pcr_enrichment_round2_mastermix_col1.py")
        ctx.star.iswap_move("work_plate", "odtc")
        pcr2_ref = ctx.odtc.run_program(method.pcr2_odtc_profile)
        ctx.star.iswap_move("odtc", "work_plate")

        spri2 = plan(
            "post-stage-2 cleanup",
            method.post_pcr2_cleanup_ratio,
            method.pcr_reaction_volume_ul,
            method.supernatant_margin_ul,
        )
        ctx.star.spri_clean(spri2)

        return StageResult(
            name=self.name,
            title=self.title,
            status=StageStatus.COMPLETED,
            message=(f"library prep on {len(samples)} well(s); "
                     f"operator thermal profiles {pcr1_ref.name!r} and {pcr2_ref.name!r}"),
            data={
                "n_wells": len(samples),
                "wells": [s.well for s in samples],
                "locus": locus.name,
                "pcr_product_bp": locus.pcr_product_bp,
                "pcr1_anneal_c": anneal,
                "pcr1_program": pcr1_ref.name,
                "pcr1_note": pcr1_ref.note,
                "pcr2_program": pcr2_ref.name,
                "pcr2_cycles": method.pcr2_cycles,
                "spri_post_pcr1": spri1.as_text(),
                "spri_post_pcr2": spri2.as_text(),
            },
            actions=ctx.actions_since(mark),
        )
