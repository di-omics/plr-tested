"""
stages/wgs_prep.py - WGS preparation.

For low-input assay validation there may not be enough template to enrich one target
directly, so the sample first passes through a generic WGS-preparation workflow. The
configured target is enriched downstream. This stage does the deck work up to the thermal
handoff and then runs the WGS-preparation program on the ODTC.

It has no gate of its own. The gate is the next stage: fluorescent dsDNA assay quant decides which
wells amplified well enough to carry forward. This stage just executes and records, on
the samples still active (every sample, at this point, since Gate 0 is deck-level).

Liquid and thermal values come from the manifest's explicit method block. Public
examples are water-only motion profiles.
"""

from __future__ import annotations

from ..reagents import spri  # noqa: F401  (kept for symmetry; WGS preparation has no SPRI)
from .base import Stage, StageContext, StageResult, StageStatus

class WGSPreparation(Stage):
    name = "wgs_prep"
    title = "WGS preparation (whole-genome sequencing preparation)"

    def run(self, ctx: StageContext) -> StageResult:
        mark = ctx.action_mark()
        samples = ctx.active_samples()
        method = ctx.config.method

        ctx.star.run_wgs_prep_liquid_handling(
            method.wgs_input_preparation_ul,
            method.wgs_reaction_mix_ul,
            method.profile_kind,
            method.parameter_source,
        )
        # Plate to the thermal cycler and run the WGS preparation program.
        ctx.star.iswap_move("work_plate", "odtc")
        ref = ctx.odtc.run_profile(
            method.wgs_odtc_profile,
            method.profile_kind,
        )
        ctx.star.iswap_move("odtc", "work_plate")

        return StageResult(
            name=self.name,
            title=self.title,
            status=StageStatus.COMPLETED,
            message=(f"WGS preparation run on {len(samples)} well(s); "
                     f"WGS preparation program '{ref.name}' (~{ref.approx_minutes:.0f} min)"),
            data={
                "n_wells": len(samples),
                "wells": [s.well for s in samples],
                "input_preparation_ul": method.wgs_input_preparation_ul,
                "reaction_mix_ul": method.wgs_reaction_mix_ul,
                "profile_kind": method.profile_kind.value,
                "parameter_source": method.parameter_source,
                "wgs_prep_program": ref.name,
                "wgs_prep_source": ref.source,
                "wgs_prep_note": ref.note,
            },
            actions=ctx.actions_since(mark),
        )
