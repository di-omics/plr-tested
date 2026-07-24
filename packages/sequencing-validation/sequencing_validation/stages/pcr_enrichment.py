"""
stages/pcr_enrichment.py - enrich the configured target from WGS-preparation product and index it.

This is the PCR enrichment stage. It amplifies the configured region with target
primers (PCR1), cleans off primer dimers, adds sample indices (PCR2), and cleans again
to the loading window. It runs only on the wells that passed the post-WGS preparation yield gate, so
no reagent is spent building a library from a cell that did not amplify.

Liquid volumes, cleanup ratios, thermal-profile paths, annealing temperature, and cycle
count come from the run's explicit method block. The package supplies no biological
defaults. Public examples are synthetic water-only motion profiles.

No gate here. Gate 2 (post-PCR enrichment fluorescent dsDNA assay) follows and decides what reaches sequencing.
"""

from __future__ import annotations

from ..reagents.spri import post_pcr1_plan, post_pcr2_plan
from .base import Stage, StageContext, StageResult, StageStatus


class PCREnrichment(Stage):
    name = "pcr_enrichment"
    title = "PCR enrichment library preparation (assay target)"

    def run(self, ctx: StageContext) -> StageResult:
        mark = ctx.action_mark()
        samples = ctx.active_samples()
        target = ctx.config.target
        method = ctx.config.method

        # PCR1: target amplification.
        ctx.star.add_mastermix(
            "PCR1",
            method.pcr1_mastermix_ul,
            "p50",
            "01_pcr_enrichment_round1_mastermix_col1.py",
            method.profile_kind,
            method.parameter_source,
        )
        ctx.star.iswap_move("work_plate", "odtc")
        pcr1_ref = ctx.odtc.run_profile(
            method.pcr1_odtc_profile,
            method.profile_kind,
        )
        ctx.star.iswap_move("odtc", "work_plate")

        spri1 = post_pcr1_plan(
            method.post_pcr1_cleanup_ratio,
            method.pcr_reaction_volume_ul,
            method.supernatant_margin_ul,
        )
        ctx.star.spri_clean(spri1)

        # PCR2: indexing.
        ctx.star.add_mastermix(
            "PCR2",
            method.pcr2_mastermix_ul,
            "p50",
            "03_pcr_enrichment_round2_mastermix_col1.py",
            method.profile_kind,
            method.parameter_source,
        )
        ctx.star.iswap_move("work_plate", "odtc")
        pcr2_ref = ctx.odtc.run_profile(
            method.pcr2_odtc_profile,
            method.profile_kind,
        )
        ctx.star.iswap_move("odtc", "work_plate")

        # Final clean to the loading window.
        spri2 = post_pcr2_plan(
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
                     f"PCR1 anneal {method.pcr1_anneal_c:g} C, "
                     f"PCR2 {method.pcr2_cycles} cycles"),
            data={
                "n_wells": len(samples),
                "wells": [s.well for s in samples],
                "target": target.name,
                "target_product_bp": target.target_product_bp,
                "profile_kind": method.profile_kind.value,
                "parameter_source": method.parameter_source,
                "pcr1_anneal_c": method.pcr1_anneal_c,
                "pcr1_program": pcr1_ref.name,
                "pcr1_note": pcr1_ref.note,
                "pcr2_program": pcr2_ref.name,
                "pcr2_cycles": method.pcr2_cycles,
                "spri_post_pcr1": spri1.as_text(),
                "spri_post_pcr2": spri2.as_text(),
            },
            actions=ctx.actions_since(mark),
        )
