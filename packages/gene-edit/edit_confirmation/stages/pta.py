"""
stages/pta.py - PTA whole-genome amplification.

For single-cell or single-embryo edit confirmation there is not enough template to
amplify one locus directly, so the genome is amplified first by PTA (Primary
Template-directed Amplification, the ResolveDNA chemistry), and the edit locus is pulled
out of that product by amplicon-seq downstream. This stage does the deck work up to the
thermal handoff and then runs the WGA program on the ODTC.

It has no gate of its own. The gate is the next stage: PicoGreen quant decides which
wells amplified well enough to carry forward. This stage just executes and records, on
the samples still active (every sample, at this point, since Gate 0 is deck-level).

Thermal and volume values are referenced from the ODTC program registry and the
ResolveDNA volume breakdown; they are not restated here.
"""

from __future__ import annotations

from ..reagents import spri  # noqa: F401  (kept for symmetry; PTA has no SPRI)
from .base import Stage, StageContext, StageResult, StageStatus

# ResolveDNA WGA volume breakdown (TAS-068.5), as summed in odtc_protocols.py VOL_UL_WGA:
# 3 uL cells/Cell Buffer + 3 uL Lysis Mix + 6 uL Reaction Mix = 12 uL.
PTA_LYSIS_UL = 3.0
PTA_REACTION_UL = 6.0


class PTA(Stage):
    name = "pta"
    title = "PTA whole-genome amplification (ResolveDNA)"

    def run(self, ctx: StageContext) -> StageResult:
        mark = ctx.action_mark()
        samples = ctx.active_samples()

        # Deck work: lysis add, manual lysis handoff, WGA reaction-mix add.
        ctx.star.run_pta_liquid_handling(PTA_LYSIS_UL, PTA_REACTION_UL)
        # Plate to the thermal cycler and run the WGA program.
        ctx.star.iswap_move("work_plate", "odtc")
        ref = ctx.odtc.run_program("wga")
        ctx.star.iswap_move("odtc", "work_plate")

        return StageResult(
            name=self.name,
            title=self.title,
            status=StageStatus.COMPLETED,
            message=(f"PTA run on {len(samples)} well(s); "
                     f"WGA program '{ref.name}' (~{ref.approx_minutes:.0f} min)"),
            data={
                "n_wells": len(samples),
                "wells": [s.well for s in samples],
                "lysis_ul": PTA_LYSIS_UL,
                "reaction_ul": PTA_REACTION_UL,
                "wga_program": ref.name,
                "wga_source": ref.source,
                "wga_note": ref.note,
            },
            actions=ctx.actions_since(mark),
        )
