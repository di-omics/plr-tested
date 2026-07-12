"""
stages/lh_qc.py - Gate 0: qualify the deck before it touches a sample.

This is the rule the user asked to bake in: calibrate the liquid handler with Rhodamine
B, and only proceed if the dispense CV is under the cutoff across the volumes the real
protocol uses. It is the first stage of every run and it can stop the run before any
reagent is spent.

The method is the constant-concentration / variable-volume fluorescence read from
reagents/rhodamine_b.py: the robot dispenses each qualified volume into a column of
replicate wells, every well is topped to a common read volume, and the Tecan reads top
fluorescence. Fluorescence tracks delivered volume, so the CV across replicates is the
dispense CV at that volume. Two run-level criteria decide Gate 0:
  - per-volume CV <= the cutoff (default 5%), for every qualified volume; and
  - the signal-vs-volume line is straight (R-squared floor), which is the accuracy check
    - a deck that is precise but nonlinear across volumes would pass CV and fail this.

In hardware mode the stage first refuses to run unless the reader calibration (working
dye concentration and locked gain) has been resolved - that is the never-invent rule as
a guard, not a comment.
"""

from __future__ import annotations

from typing import List

from ..config import RunMode
from ..gates import Comparison, Criterion, evaluate_run_level
from ..qc_math import cv_percent, linear_fit, mean
from ..reagents.rhodamine_b import default_prep
from ..simulation import (
    SIM_READER_CEILING,
    SIM_READER_FLOOR,
    SIM_SIGNAL_PER_UM_FULL,
    SIM_WORKING_CONC_UM,
    rhodamine_signal,
)
from .base import Stage, StageContext, StageResult, StageStatus

N_REPLICATES = 8   # one column of channels; the STAR's 8 channels in one dispense


def _tip_for(volume_ul: float) -> str:
    if volume_ul <= 10.0:
        return "p10"
    if volume_ul <= 50.0:
        return "p50"
    return "p300"


class LiquidHandlingQC(Stage):
    name = "lh_qc"
    title = "Gate 0 - liquid-handling qualification (Rhodamine B)"

    def run(self, ctx: StageContext) -> StageResult:
        mark = ctx.action_mark()
        prep = default_prep()
        ctx.guard.add(*prep.guard_values())

        # Never-invent enforcement: a hardware Gate 0 needs the reader calibration first.
        if ctx.config.mode is RunMode.HARDWARE:
            ctx.guard.assert_ready_for_hardware()

        common_read = float(prep.common_read_volume_ul.value)
        ex = float(prep.read_ex_nm.value)
        em = float(prep.read_em_nm.value)

        volumes = sorted(ctx.config.acceptance.lh_qualified_volumes_ul)
        per_volume = []
        cv_pairs = []
        mean_signals = []

        for vol in volumes:
            tip = _tip_for(vol)
            delivered = ctx.star.qualify_dispense(ctx.config.run_id, vol, N_REPLICATES, tip)

            # In simulation the delivered volumes are known; convert to reader signals.
            # In hardware the Tecan read supplies the signals and delivered is None.
            truth = {}
            if delivered is not None:
                for i, dv in enumerate(delivered):
                    truth[f"{vol}ul_r{i+1}"] = rhodamine_signal(
                        dv, SIM_WORKING_CONC_UM, common_read,
                        SIM_SIGNAL_PER_UM_FULL, SIM_READER_FLOOR,
                    )
            signals = ctx.tecan.read(ctx.config.run_id, f"rhodamine_{vol}ul", truth, ex, em)

            values = list(signals.values())
            cv = cv_percent(values)
            m = mean(values)
            mean_signals.append(m)

            crit = ctx.config.acceptance.lh_cv_criterion(vol)
            passed = crit.check(cv)
            cv_pairs.append((crit, cv))
            per_volume.append({
                "volume_ul": vol,
                "tip": tip,
                "n": len(values),
                "cv_percent": round(cv, 3),
                "mean_signal": round(m, 1),
                "cutoff_percent": ctx.config.acceptance.lh_cv_max_percent,
                "passed": passed,
                "reader_window_ok": SIM_READER_FLOOR <= m <= SIM_READER_CEILING,
            })

        # Accuracy proxy: the signal-vs-volume line should be straight through the ladder.
        linearity = linear_fit(volumes, mean_signals)
        linearity_crit = Criterion(
            key="lh_linearity",
            label="signal-vs-volume linearity R-squared",
            comparison=Comparison.MIN,
            bound=ctx.config.acceptance.curve_r2_min,
            unit="",
            source="a precise-but-nonlinear deck would pass CV and fail this",
        )

        gate = evaluate_run_level(
            self.title,
            cv_pairs + [(linearity_crit, linearity.r_squared)],
            message_pass=(
                f"deck qualified: all {len(volumes)} volumes under "
                f"{ctx.config.acceptance.lh_cv_max_percent}% CV, "
                f"linearity R2={linearity.r_squared:.4f}"
            ),
            message_fail="deck NOT qualified; run stopped before any sample was touched",
        )

        status = StageStatus.COMPLETED if gate.passed else StageStatus.STOPPED
        return StageResult(
            name=self.name,
            title=self.title,
            status=status,
            message=gate.message,
            gate=gate,
            data={
                "volumes": per_volume,
                "linearity_r2": round(linearity.r_squared, 5),
                "linearity_slope": round(linearity.slope, 4),
                "method": "constant-concentration variable-volume Rhodamine B, common read volume",
                "read_ex_nm": ex,
                "read_em_nm": em,
                "common_read_volume_ul": common_read,
            },
            actions=ctx.actions_since(mark),
        )
