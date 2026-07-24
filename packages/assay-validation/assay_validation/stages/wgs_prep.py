"""
stages/wgs_prep.py - WGS preparation.

For single-cell or other low-input sequencing there is not enough template to
amplify one locus directly, so the genome first passes through a generic WGS preparation workflow, and the target locus is pulled
out of that product by PCR enrichment downstream. This stage does the deck work up to the
thermal handoff and then runs the WGS preparation program on the ODTC.

It has no gate of its own. The gate is the next stage: fluorescent dsDNA assay quant decides which
wells amplified well enough to carry forward. This stage just executes and records, on
the samples still active (every sample, at this point, since Gate 0 is deck-level).

Thermal and volume values come from the required run-manifest method profile.
"""

from __future__ import annotations

from .base import Stage, StageContext, StageResult, StageStatus


class WGSPreparation(Stage):
    name = "wgs_prep"
    title = "WGS preparation (whole-genome sequencing preparation)"

    def run(self, ctx: StageContext) -> StageResult:
        mark = ctx.action_mark()
        samples = ctx.active_samples()
        method = ctx.config.method

        ctx.star.run_wgs_prep_liquid_handling(
            method.wgs_stage_1_ul, method.wgs_stage_2_ul
        )
        # Plate to the thermal cycler and run the WGS preparation program.
        ctx.star.iswap_move("work_plate", "odtc")
        ref = ctx.odtc.run_program(method.wgs_odtc_profile)
        ctx.star.iswap_move("odtc", "work_plate")

        return StageResult(
            name=self.name,
            title=self.title,
            status=StageStatus.COMPLETED,
            message=(
                f"WGS preparation run on {len(samples)} well(s); "
                f"operator profile {ref.name!r}"
            ),
            data={
                "n_wells": len(samples),
                "wells": [s.well for s in samples],
                "stage_1_ul": method.wgs_stage_1_ul,
                "stage_2_ul": method.wgs_stage_2_ul,
                "wgs_prep_program": ref.name,
                "wgs_prep_source": ref.source,
                "wgs_prep_note": ref.note,
            },
            actions=ctx.actions_since(mark),
        )
