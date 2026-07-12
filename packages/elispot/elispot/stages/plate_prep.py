"""
stages/plate_prep.py - Gate 1: activate and coat the membrane, evenly.

Between the qualified instrument and the cells, the plate itself has to be made ready: the
PVDF membrane is activated with a brief ethanol pre-wet, coated with capture antibody (unless
the kit ships a pre-coated plate), washed, and blocked. Gate 1 is the plate-lot check that
sits here: the pre-wet must go down evenly, because a membrane that wets out unevenly coats
and develops unevenly, and no downstream QC recovers from that. It is a run-level gate on the
pre-wet uniformity CV.

This is also where the reagent side of the never-invent rule is enforced. The kit's antibody
and conjugate concentrations are TODO until transcribed from the datasheet, and the substrate
development endpoint is CALIBRATE until set on the first plate. A hardware run asserts all of
them are resolved here, before the first drop of coating antibody goes down - you do not want
to discover mid-assay that the substrate time was never pinned.
"""

from __future__ import annotations

from ..config import RunMode
from ..gates import evaluate_run_level
from ..membrane import default_constraints
from ..qc_math import cv_percent, mean
from ..reagents.elispot_kit import for_cytokine
from ..simulation import GOOD_PLATE_LOT, simulate_prewet_wetout
from .base import Stage, StageContext, StageResult, StageStatus

N_PREWET_WELLS = 8


class PlatePrep(Stage):
    name = "plate_prep"
    title = "Gate 1 - plate preparation (pre-wet, coat, block)"

    def run(self, ctx: StageContext) -> StageResult:
        mark = ctx.action_mark()
        cfg = ctx.config
        membrane = default_constraints(cfg.site.aspiration_height_mm)
        kit = for_cytokine(cfg.cytokine, precoated=cfg.precoated_plate)

        # Never-invent enforcement for the reagent chain, before any reagent is dispensed.
        ctx.guard.add(*kit.guard_values())
        if cfg.mode is RunMode.HARDWARE:
            ctx.guard.assert_ready_for_hardware()

        dispense_mode = str(membrane.dispense_mode.value)
        ethanol_pct = membrane.prewet_ethanol_percent.value
        prewet_volume = min(cfg.acceptance.lh_qualified_volumes_ul)   # smallest qualified volume

        # Pre-wet the membrane and read its wet-out uniformity (Gate 1).
        ctx.lh.dispense_reagent(
            "prewet", f"membrane pre-wet ({ethanol_pct}% ethanol)", prewet_volume, dispense_mode)
        ctx.washer.wash("post-prewet rinse", cfg.site.wash_cycles, cfg.site.wash_volume_ul,
                        cfg.site.soak_seconds, cfg.site.aspiration_height_mm)
        wetout = simulate_prewet_wetout(cfg.run_id, N_PREWET_WELLS, GOOD_PLATE_LOT)
        prewet_cv = cv_percent(wetout)

        # Coat (unless pre-coated), wash, block.
        coat_step = kit.step("coat")
        if coat_step is not None:
            ctx.lh.dispense_reagent("coat", coat_step.title,
                                    float(coat_step.volume_ul.value), dispense_mode)
            ctx.washer.wash("post-coat wash", cfg.site.wash_cycles, cfg.site.wash_volume_ul,
                            cfg.site.soak_seconds, cfg.site.aspiration_height_mm)
        block_step = kit.step("block")
        ctx.lh.dispense_reagent("block", block_step.title,
                                float(block_step.volume_ul.value), dispense_mode)

        prewet_crit = cfg.acceptance.prewet_cv_criterion()
        gate = evaluate_run_level(
            self.title,
            [(prewet_crit, prewet_cv)],
            message_pass=(
                f"plate prepared: pre-wet uniformity CV {prewet_cv:.2f}% under "
                f"{cfg.acceptance.prewet_cv_max_percent}%"
                + ("" if coat_step else "; kit ships pre-coated (coat skipped)")
            ),
            message_fail=f"pre-wet uneven (CV {prewet_cv:.2f}%); the membrane is not fit to coat",
        )

        status = StageStatus.COMPLETED if gate.passed else StageStatus.STOPPED
        return StageResult(
            name=self.name,
            title=self.title,
            status=status,
            message=gate.message,
            gate=gate,
            data={
                "precoated": cfg.precoated_plate,
                "prewet_ethanol_percent": ethanol_pct,
                "prewet_volume_ul": prewet_volume,
                "prewet_cv_percent": round(prewet_cv, 3),
                "prewet_cutoff_percent": cfg.acceptance.prewet_cv_max_percent,
                "coat": (coat_step.title if coat_step else "pre-coated plate"),
                "block": block_step.title,
                "dispense_mode": dispense_mode,
                "wash_cycles": cfg.site.wash_cycles,
                "cytokine": cfg.cytokine,
            },
            actions=ctx.actions_since(mark),
        )
