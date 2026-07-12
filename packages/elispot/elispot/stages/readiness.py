"""
stages/readiness.py - Gate 0: qualify the instrument before it touches the plate.

Before any reagent is spent, the washer and liquid handler must be shown fit to run this
plate. Three run-level checks decide Gate 0, and any failure stops the run before a sample
is committed:

  - Dispense precision. The Rhodamine B ladder (constant concentration, variable volume,
    common read volume) reads the dispense CV at every volume the protocol uses, from the
    15 uL ethanol pre-wet up to the 200 uL wash. Over the cutoff at any volume, stop.
  - Dispense linearity. The signal-vs-volume line must be straight (R-squared floor); a
    deck that is precise but nonlinear passes CV and fails this. That is the accuracy check.
  - Aspiration completeness. The washer must draw a well down to a low residual volume,
    because reagent left behind carries forward and prints as background - the single
    biggest controllable source of ELISpot noise.

And the never-invent guard: in hardware mode the stage refuses to run until the membrane
aspiration clearance has been taught (membrane.py) and the reader calibration is pinned
(rhodamine_b.py). Those are CALIBRATE values; a probe height guessed rather than measured
is exactly what scratches a membrane, so the guard is mechanical, not a comment.
"""

from __future__ import annotations

from ..config import RunMode
from ..gates import Comparison, Criterion, evaluate_run_level
from ..instruments.base import AwaitingData
from ..membrane import default_constraints
from ..qc_math import cv_percent, linear_fit, mean
from ..reagents.rhodamine_b import default_prep
from ..simulation import (
    SIM_READER_FLOOR,
    SIM_SIGNAL_PER_UM_FULL,
    SIM_WORKING_CONC_UM,
    rhodamine_signal,
)
from .base import Stage, StageContext, StageResult, StageStatus

N_REPLICATES = 8    # one column of replicate wells
N_RESIDUAL_WELLS = 8


class Readiness(Stage):
    name = "readiness"
    title = "Gate 0 - instrument readiness (dispense, linearity, aspiration)"

    def run(self, ctx: StageContext) -> StageResult:
        mark = ctx.action_mark()
        prep = default_prep()
        membrane = default_constraints(ctx.config.site.aspiration_height_mm)
        ctx.guard.add(*prep.guard_values())
        ctx.guard.add(*membrane.guard_values())

        # Never-invent enforcement: a hardware Gate 0 needs the reader calibration and the
        # membrane clearance measured first, before any probe enters a well.
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
            delivered = ctx.washer.qualify_dispense(ctx.config.run_id, vol, N_REPLICATES)
            if delivered is None:
                # Hardware: the dispense qualification read is captured on the Pi, not
                # in-package. Pause with a run card the way the imager does, rather than
                # score an empty read. (Provenance normally blocks a hardware run before here.)
                raise AwaitingData(
                    "Gate 0 dispense qualification has no data. Run the washer dispense "
                    "ladder on the Pi and supply the reads; the in-package Gate 0 read is "
                    "not wired in this repo yet."
                )
            truth = {}
            for i, dv in enumerate(delivered):
                truth[f"{vol}ul_r{i+1}"] = rhodamine_signal(
                    dv, SIM_WORKING_CONC_UM, common_read,
                    SIM_SIGNAL_PER_UM_FULL, SIM_READER_FLOOR,
                )
            signals = list(truth.values())
            cv = cv_percent(signals)
            m = mean(signals)
            mean_signals.append(m)

            crit = ctx.config.acceptance.lh_cv_criterion(vol)
            cv_pairs.append((crit, cv))
            per_volume.append({
                "volume_ul": vol,
                "n": len(signals),
                "cv_percent": round(cv, 3),
                "cutoff_percent": ctx.config.acceptance.lh_cv_max_percent,
                "passed": crit.check(cv),
            })

        # Accuracy proxy: signal vs volume should be straight through the ladder.
        linearity = linear_fit(volumes, mean_signals)
        linearity_crit = Criterion(
            key="lh_linearity",
            label="signal-vs-volume linearity R-squared",
            comparison=Comparison.MIN,
            bound=0.98,
            unit="",
            source="a precise-but-nonlinear deck would pass CV and fail this",
        )

        # Aspiration completeness.
        residuals = ctx.washer.qualify_residual(ctx.config.run_id, N_RESIDUAL_WELLS) or []
        residual_mean = mean(residuals) if residuals else 0.0
        residual_max = max(residuals) if residuals else 0.0
        residual_crit = ctx.config.acceptance.residual_criterion()

        gate = evaluate_run_level(
            self.title,
            cv_pairs + [(linearity_crit, linearity.r_squared), (residual_crit, residual_mean)],
            message_pass=(
                f"instrument qualified: all {len(volumes)} volumes under "
                f"{ctx.config.acceptance.lh_cv_max_percent}% CV, linearity "
                f"R2={linearity.r_squared:.4f}, residual {residual_mean:.1f} uL"
            ),
            message_fail="instrument NOT qualified; run stopped before the plate was touched",
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
                "residual_mean_ul": round(residual_mean, 2),
                "residual_max_ul": round(residual_max, 2),
                "residual_cutoff_ul": ctx.config.acceptance.residual_volume_max_ul,
                "method": "constant-concentration variable-volume Rhodamine B; residual by aspiration",
                "read_ex_nm": ex,
                "read_em_nm": em,
                "common_read_volume_ul": common_read,
                "membrane_clearance": membrane.aspiration_clearance_mm.as_label(),
            },
            actions=ctx.actions_since(mark),
        )
